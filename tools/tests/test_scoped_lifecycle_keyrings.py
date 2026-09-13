#!/usr/bin/env python3
"""Offline regressions for the keyring, module and service-lifecycle fixes.

No compiler, installer, service manager, firewall or AppArmor policy is run.
Ownership tests need root in a disposable environment; subprocess tests use
short-lived fixture children, never the installed desktop/storage commands.
"""
from __future__ import annotations

from contextlib import ExitStack
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / 'd-i/forky/hooks/target'
LIB = TARGET / 'usr/local/lib/perl5/site_perl'
PYLIB = TARGET / 'usr/local/lib/python3.14/dist-packages'
sys.path.insert(0, str(PYLIB))
from labwc_managed_app import dbus_proxy, generic, integrity, session
from labwc_firewall import files as firewall_files, nftables
from labwc_firewall.validation import FirewallError


def load_script(name: str):
    loader = importlib.machinery.SourceFileLoader('scoped_' + name.replace('-', '_'),
        str(TARGET / 'usr/local/libexec' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


normalizer = load_script('local-apt-normalize-sources')
desktops = load_script('labwc-wrap-desktop-files')
KEY = '/usr/share/keyrings/debian-archive-keyring.gpg'
PGP = KEY[:-4] + '.pgp'


@unittest.skipUnless(os.geteuid() == 0, 'root-owned fixture checks require a disposable root environment')
class KeyringRegressionTests(unittest.TestCase):
    def setUp(self):
        # The production function intentionally rejects world-writable /tmp.
        self.temp = tempfile.TemporaryDirectory(prefix='keyring-regression-', dir='/var/lib')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parts = self.root / 'etc/apt/sources.list.d'
        self.parts.mkdir(parents=True)
        self.link = self.root / KEY.lstrip('/')
        self.key = self.root / PGP.lstrip('/')
        self.key.parent.mkdir(parents=True)
        self.key.write_bytes(b'fixture-key-material-not-for-production')
        self.link.symlink_to(self.key.name)

    def source(self, *, signed_by=''):
        text = ('Types: deb deb-src\nURIs: https://deb.debian.org/debian\n'
                'Suites: forky forky-backports\nComponents: main contrib non-free non-free-firmware\n')
        if signed_by:
            text += 'Signed-By: ' + signed_by + '\n'
        path = self.parts / 'original.sources'
        path.write_text(text)
        return path

    def test_relative_package_link_is_read_without_modification(self):
        self.assertEqual(normalizer.keyring_bytes(KEY, self.root), self.key.read_bytes())
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(os.readlink(self.link), self.key.name)

    def test_absolute_link_resolves_inside_target_not_host(self):
        self.link.unlink(); self.link.symlink_to(PGP)
        self.assertEqual(normalizer.keyring_bytes(KEY, self.root), self.key.read_bytes())

    def test_safe_directory_link_is_supported(self):
        self.link.unlink(); self.key.unlink(); self.key.parent.rmdir()
        directory = self.root / 'usr/share/package-keys'
        directory.mkdir(); (directory / self.key.name).write_bytes(b'package keys')
        self.key.parent.symlink_to('package-keys', target_is_directory=True)
        self.link.symlink_to(self.key.name)
        self.assertEqual(normalizer.keyring_bytes(KEY, self.root), b'package keys')

    def test_backports_gets_requested_signed_by_and_is_idempotent(self):
        self.source()
        normalizer.normalize(self.root)
        output = self.parts / 'debian.sources'
        records = normalizer.deb822(output.read_text())
        backports = [r for r in records if r['suites'] == 'forky-backports']
        self.assertEqual({r['types'] for r in backports}, {'deb', 'deb-src'})
        self.assertTrue(all(r['signed-by'] == KEY for r in backports))
        before = (output.read_bytes(), output.stat().st_mtime_ns)
        normalizer.normalize(self.root)
        self.assertEqual(before, (output.read_bytes(), output.stat().st_mtime_ns))
        self.assertTrue(self.link.is_symlink())

    def test_equivalent_pgp_spelling_becomes_requested_gpg_alias(self):
        self.source(signed_by=PGP)
        normalizer.normalize(self.root)
        records = normalizer.deb822((self.parts / 'debian.sources').read_text())
        self.assertTrue(all(r['signed-by'] == KEY for r in records))

    def test_custom_key_and_fingerprint_restriction_are_preserved(self):
        value = KEY + ' ' + 'A' * 40 + '!'
        self.source(signed_by=value)
        normalizer.normalize(self.root)
        records = normalizer.deb822((self.parts / 'debian.sources').read_text())
        self.assertTrue(all(r['signed-by'] == value for r in records))

    def test_gpg_reads_validated_bytes_not_reopened_link(self):
        completed = types.SimpleNamespace(returncode=1, stdout=b'')
        with mock.patch.object(normalizer.subprocess, 'run', return_value=completed) as run:
            normalizer.signed_identity(KEY, self.root, {})
        self.assertEqual(run.call_args.kwargs['input'], self.key.read_bytes())
        self.assertNotIn(str(self.link), run.call_args.args[0])

    def assert_rejected_without_writes(self):
        path = self.source()
        before = path.read_bytes()
        with self.assertRaises((normalizer.Error, OSError)):
            normalizer.normalize(self.root)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.parts / 'debian.sources').exists())

    def test_true_cycle_is_rejected_before_source_changes(self):
        self.key.unlink(); self.key.symlink_to(self.link.name)
        self.assert_rejected_without_writes()

    def test_dangling_link_is_rejected_before_source_changes(self):
        self.key.unlink()
        self.assert_rejected_without_writes()

    def test_relative_escape_above_target_root_is_rejected(self):
        self.link.unlink(); self.link.symlink_to('../../../../../../etc/passwd')
        self.assert_rejected_without_writes()

    def test_writable_key_is_rejected(self):
        self.key.chmod(0o666)
        self.assert_rejected_without_writes()

    def test_writable_key_directory_is_rejected(self):
        self.key.parent.chmod(0o777)
        self.assert_rejected_without_writes()

    def test_nonroot_link_owner_is_rejected(self):
        os.lchown(self.link, 65534, 65534)
        self.assert_rejected_without_writes()

    def test_nonroot_key_owner_is_rejected(self):
        os.chown(self.key, 65534, 65534)
        self.assert_rejected_without_writes()

    def test_fifo_target_is_rejected_without_waiting_for_a_writer(self):
        self.key.unlink(); os.mkfifo(self.key)
        started = time.monotonic()
        self.assert_rejected_without_writes()
        self.assertLess(time.monotonic() - started, 1)

    def test_source_symlink_guard_is_not_relaxed(self):
        original = self.source(); original.rename(self.parts / 'saved')
        original.symlink_to('saved')
        with self.assertRaises(OSError):
            normalizer.normalize(self.root)
        self.assertTrue(original.is_symlink())

    def test_missing_unstaged_nonlink_retains_existing_contract(self):
        self.assertIsNone(normalizer.keyring_bytes('/etc/apt/keyrings/future.gpg', self.root))


class DesktopIsolationTests(unittest.TestCase):
    prefix = '/usr/local/bin/labwc-wayland-app launch'

    def test_nodisplay_mime_handler_still_gets_a_service(self):
        original = '[Desktop Entry]\nType=Application\nNoDisplay=true\nExec=/usr/bin/viewer %U\n'
        result = desktops.rewrite_desktop(original, self.prefix)
        self.assertIn('NoDisplay=true\n', result)
        self.assertIn('Exec=' + self.prefix + ' -- /usr/bin/viewer %U', result)

    def test_managed_main_does_not_hide_unmanaged_desktop_actions(self):
        original = ('[Desktop Entry]\nType=Application\nExec=/usr/local/bin/chatgpt auto %U\n'
            'DBusActivatable=true\n[Desktop Action Other]\nExec=/usr/bin/viewer %f\n')
        result = desktops.rewrite_desktop(original, self.prefix)
        self.assertIn('Exec=/usr/local/bin/chatgpt auto %U\n', result)
        self.assertIn('DBusActivatable=false\n', result)
        self.assertIn('Exec=' + self.prefix + ' -- /usr/bin/viewer %f\n', result)

    def test_managed_path_in_arguments_does_not_bypass_wrapping(self):
        self.assertFalse(desktops.managed_exec('/usr/bin/viewer /usr/local/bin/labwc-managed-app'))
        self.assertFalse(desktops.managed_exec('/usr/bin/echo "hello /usr/local/bin/chatgpt"'))
        self.assertTrue(desktops.managed_exec('/usr/bin/env VAR=value /usr/local/bin/chatgpt auto'))

    def test_terminal_desktop_keeps_pty_and_is_idempotent(self):
        original = ('[Desktop Entry]\nType=Application\nTerminal=true\nExec=/usr/bin/nnn %F\n'
            '[Desktop Action Other]\nExec=/usr/bin/nnn -d\n')
        result = desktops.rewrite_desktop(original, self.prefix)
        self.assertIn('Terminal=false\n', result)
        self.assertIn('Exec=/usr/local/bin/labwc-terminal -e /usr/bin/nnn %F\n', result)
        self.assertIn('Exec=/usr/local/bin/labwc-terminal -e /usr/bin/nnn -d\n', result)
        self.assertEqual(desktops.rewrite_desktop(result, self.prefix), result)

    def test_hidden_is_not_resurrected(self):
        text = '[Desktop Entry]\nHidden=true\nExec=/usr/bin/viewer\n'
        self.assertEqual(desktops.rewrite_desktop(text, self.prefix), text)

    def test_each_terminal_keeps_host_admin_access_but_has_its_own_cgroup(self):
        with mock.patch.object(generic, 'assert_launch_allowed'):
            argv = generic.transient_argv('wayland', 'launch', ['/usr/bin/foot'], {})
            second = generic.transient_argv('wayland', 'launch', ['/usr/bin/foot'], {})
        for setting in ('ExitType=cgroup', 'KillMode=control-group', 'TimeoutStopSec=20s',
                        'Requisite=labwc-session.target', 'PartOf=labwc-session.target'):
            self.assertIn('--property=' + setting, argv)
        self.assertIn('--service-type=exec', argv)
        self.assertNotIn('--scope', argv)
        self.assertFalse(any('PrivateTmp=' in a or 'PrivateIPC=' in a or 'ProtectSystem=' in a for a in argv))
        self.assertNotEqual(next(a for a in argv if a.startswith('--unit=')),
                            next(a for a in second if a.startswith('--unit=')))
        with mock.patch.object(generic, 'assert_launch_allowed'):
            viewer = generic.transient_argv('wayland', 'launch', ['/usr/bin/viewer'], {})
        self.assertIn('--property=ProtectSystem=full', viewer)

    def test_terminal_script_preserves_arguments_and_does_not_use_server(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            recorder = root / 'recorder'
            recorder.write_text('#!/usr/bin/python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            recorder.chmod(0o755)
            for executable in ('foot', 'kitty'):
                path = root / executable; path.write_text('#!/bin/sh\nexit 99\n'); path.chmod(0o755)
            source = (TARGET / 'usr/local/bin/labwc-terminal').read_text()
            source = source.replace('/etc/default/labwc-desktop', str(root / 'no-defaults'))
            source = source.replace('/usr/local/bin/labwc-wayland-app', str(recorder))
            script = root / 'terminal'; script.write_text(source)
            for terminal, expected in [('footclient', ['foot', '-e']), ('kitty', ['kitty']),
                                       (str(root / 'kitty'), [str(root / 'kitty')])]:
                result = subprocess.run(['/bin/sh', str(script), '-e', '/bin/echo', 'a b', '$HOME'],
                    capture_output=True, text=True, timeout=5,
                    env={'PATH': str(root) + ':/usr/bin:/bin', 'LABWC_TERMINAL_PRIMARY': terminal})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), ['auto', '--', *expected, '/bin/echo', 'a b', '$HOME'])


class SessionHandoffTests(unittest.TestCase):
    def test_safe_environment_is_forwarded_by_name_for_bitwarden_and_compat(self):
        env = {'HOME': '/home/alice', 'WAYLAND_DISPLAY': 'wayland-2',
               'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus',
               'LABWC_SESSION_OWNER': 'desktop'}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {}, clear=True))
            stack.enter_context(mock.patch.object(session, 'assert_launch_allowed'))
            stack.enter_context(mock.patch.object(session, 'require_root_owned_executable', return_value='/usr/bin/systemd-run'))
            stack.enter_context(mock.patch.object(session, 'bitwarden_session_unit_environment', return_value=env.copy()))
            stack.enter_context(mock.patch.object(session, 'wayland_compat_session_unit_environment', return_value=env.copy()))
            execute = stack.enter_context(mock.patch.object(session.os, 'execve'))
            for invoke in (lambda: session.redirect_bitwarden_to_session_unit('intel', ['a b', '$HOME']),
                           lambda: session.redirect_wayland_compat_to_session_unit('discord', 'intel', ['a b', '$HOME'])):
                invoke()
                executable, argv, environment = execute.call_args.args
                self.assertEqual(environment, env)
                for key in env:
                    self.assertIn('--setenv=' + key, argv)
                self.assertNotIn('/home/alice', ' '.join(argv))
                self.assertEqual(argv[-2:], ['a b', '$HOME'])
                self.assertIn('--expand-environment=no', argv)
                self.assertIn('--property=KillMode=control-group', argv)
                self.assertTrue(any(a.startswith('--working-directory=') for a in argv))
                self.assertTrue(any(a.startswith('--unit=labwc-') for a in argv))

    def test_bitwarden_wayland_socket_and_session_owner_are_explicit(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {
                'LABWC_SESSION_OWNER': 'desktop', 'WAYLAND_DISPLAY': 'wayland-4',
                'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}, clear=True))
            stack.enter_context(mock.patch.object(session, 'current_user_home', return_value='/home/alice'))
            stack.enter_context(mock.patch.object(session, 'current_user_name', return_value='alice'))
            stack.enter_context(mock.patch.object(session, 'current_user_runtime_dir', return_value='/run/user/1000'))
            stack.enter_context(mock.patch.object(session, 'validate_session_bus_address', side_effect=lambda x: x))
            socket = stack.enter_context(mock.patch.object(session, 'current_user_runtime_socket'))
            env = session.bitwarden_session_unit_environment()
        self.assertEqual(env['WAYLAND_DISPLAY'], 'wayland-4')
        self.assertEqual(env['LABWC_SESSION_OWNER'], 'desktop')
        socket.assert_called_once_with('Wayland socket', 'wayland-4')

    def test_marker_cannot_skip_service_creation_from_other_cgroup(self):
        with mock.patch.dict(os.environ, {session.NATIVE_SESSION_UNIT_MARKER: '1'}, clear=True), \
             mock.patch.object(session.Path, 'open', mock.mock_open(read_data='0::/app.slice/terminal.service\n')), \
             mock.patch('sys.stderr', new=io.StringIO()):
            with self.assertRaises(SystemExit):
                session.redirect_native_from_private_users('filen', 'intel', [])

    def test_marker_is_consumed_only_in_corresponding_service(self):
        name = session.NATIVE_SESSION_UNIT_MARKER
        cgroup = '0::/user.slice/app.slice/labwc-native-filen-' + 'a' * 32 + '.service\n'
        with mock.patch.dict(os.environ, {name: '1'}, clear=True), \
             mock.patch.object(session.Path, 'open', mock.mock_open(read_data=cgroup)), \
             mock.patch.object(session, 'system_owner', return_value=(0, 0)), \
             mock.patch.object(session.os, 'execve') as execute:
            session.redirect_native_from_private_users('filen', 'intel', [])
            self.assertNotIn(name, os.environ)
            execute.assert_not_called()


class PythonLifecycleTests(unittest.TestCase):
    @unittest.skipUnless(os.geteuid() == 0, 'root-owned lock fixture')
    def test_firewall_lock_rejects_symlink_fifo_and_foreign_owner(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            target = root / 'target'; target.write_text('untouched'); target.chmod(0o600)
            lock = root / 'lock'; lock.symlink_to(target)
            with self.assertRaises(FirewallError), firewall_files.locked(lock, exclusive=True):
                self.fail('symlink lock accepted')
            self.assertEqual(target.read_text(), 'untouched')
            lock.unlink(); os.mkfifo(lock)
            with self.assertRaises(FirewallError), firewall_files.locked(lock, exclusive=True):
                self.fail('FIFO lock accepted')
            lock.unlink(); lock.write_text(''); lock.chmod(0o600); os.chown(lock, 65534, 65534)
            with self.assertRaises(FirewallError), firewall_files.locked(lock, exclusive=True):
                self.fail('foreign lock accepted')

    @unittest.skipUnless(os.geteuid() == 0, 'root-owned lock fixture')
    def test_firewall_lock_is_private_and_released(self):
        with tempfile.TemporaryDirectory() as name:
            lock = Path(name) / 'lock'
            for _ in range(2):
                with firewall_files.locked(lock, exclusive=True):
                    self.assertEqual(lock.stat().st_mode & 0o777, 0o600)

    def test_proxy_diagnostic_read_does_not_wait_on_inherited_writer(self):
        # Keep a real writer open: reading to EOF here used to deadlock.
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b'proxy error\n')
        stream = os.fdopen(read_fd, 'r', encoding='utf-8')
        process = types.SimpleNamespace(stderr=stream)
        try:
            start = time.monotonic()
            self.assertEqual(dbus_proxy._bounded_proxy_stderr(process), 'proxy error')
            self.assertLess(time.monotonic() - start, 1)
            self.assertTrue(stream.closed)
        finally:
            os.close(write_fd)
            stream.close()

    def test_proxy_empty_open_pipe_returns_immediately(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, 'r')
        try:
            self.assertEqual(dbus_proxy._bounded_proxy_stderr(types.SimpleNamespace(stderr=stream)), '')
        finally:
            os.close(write_fd); stream.close()

    def test_proxy_diagnostics_are_bounded_and_sanitized(self):
        stream = io.StringIO('a\0\n' + 'b' * 20000)
        result = dbus_proxy._bounded_proxy_stderr(types.SimpleNamespace(stderr=stream))
        self.assertTrue(result.endswith('[truncated]'))
        self.assertNotIn('\0', result)
        self.assertIn('\\0', result)

    def firewall(self, outcomes):
        runner = mock.Mock()
        runner.require.side_effect = lambda name: {'nft': '/usr/sbin/nft', 'systemctl': '/usr/bin/systemctl'}[name]
        runner.run.side_effect = outcomes
        return runner, mock.Mock()

    def test_validation_timeout_rolls_back_without_reload(self):
        runner, mutation = self.firewall([FirewallError('timeout')])
        with self.assertRaisesRegex(FirewallError, 'previous rules restored'):
            nftables.validate_and_apply(runner, mutation, Path('/etc/nftables.conf'))
        mutation.rollback.assert_called_once()
        self.assertEqual(runner.run.call_count, 1)

    def test_reload_timeout_restores_disk_and_live_policy(self):
        runner, mutation = self.firewall([types.SimpleNamespace(returncode=0), FirewallError('timeout'), types.SimpleNamespace(returncode=0)])
        with self.assertRaisesRegex(FirewallError, 'previous rules restored'):
            nftables.validate_and_apply(runner, mutation, Path('/etc/nftables.conf'))
        mutation.rollback.assert_called_once()
        self.assertEqual(runner.run.call_args.args, ('/usr/sbin/nft', '-f', '/etc/nftables.conf'))

    def test_failed_live_restore_is_not_reported_as_success(self):
        runner, mutation = self.firewall([types.SimpleNamespace(returncode=0), FirewallError('timeout'), FirewallError('restore timeout')])
        with self.assertRaisesRegex(FirewallError, 'previous live rules could not be restored'):
            nftables.validate_and_apply(runner, mutation, Path('/etc/nftables.conf'))
        mutation.rollback.assert_called_once()

    def test_success_does_not_rollback(self):
        runner, mutation = self.firewall([types.SimpleNamespace(returncode=0), types.SimpleNamespace(returncode=0)])
        nftables.validate_and_apply(runner, mutation, Path('/etc/nftables.conf'))
        mutation.rollback.assert_not_called()


class PerlLifecycleTests(unittest.TestCase):
    paths = [LIB / 'whisper/WhisperMode/Systemd.pm', LIB / 'labwc-adb/AndroidADB/Command.pm',
             TARGET / 'usr/local/libexec/labwc-output-watch']

    def runner(self, source: str, invocation: str, argv: list[str]):
        code = ('use strict; use warnings; use Managed::Process qw(capture_command); '
                'use JSON::PP qw(encode_json);\n' + source + '\n' + invocation)
        return subprocess.run(['/usr/bin/perl', '-I', str(LIB / 'managed-runtime'), '-e', code, *argv],
                              capture_output=True, text=True, timeout=8)

    def test_all_capture_adapters_preserve_status_streams_and_handle_auto_reaper(self):
        for path in self.paths:
            with self.subTest(path=path.name):
                body = re.search(r'(?ms)^sub run_command \{\n.*?^\}', path.read_text()).group()
                result = self.runner(body, 'local $SIG{CHLD} = "IGNORE"; print encode_json(run_command(2, 100000, @ARGV));',
                                     ['/bin/sh', '-c', 'printf out; printf err >&2; exit 7'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'stdout': 'out', 'stderr': 'err', 'status': 7 << 8, 'error': ''})

    def test_capture_adapters_bound_descendants_holding_pipes(self):
        for path in self.paths:
            with self.subTest(path=path.name):
                body = re.search(r'(?ms)^sub run_command \{\n.*?^\}', path.read_text()).group()
                result = self.runner(body, 'print encode_json(run_command(0.2, 100000, @ARGV));',
                    ['/usr/bin/python3', '-c', 'import os,time; child=os.fork(); os._exit(0) if child else time.sleep(30)'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 124 << 8)

    def test_mapper_preserves_signal_failure_and_drains_both_streams(self):
        path = LIB / 'zram-writeback/Zram/Setup/Mapper.pm'
        body = re.search(r'(?ms)^sub _capture \{\n.*?^\}', path.read_text()).group()
        result = self.runner(body, 'print encode_json([_capture(undef, @ARGV)]);', ['/bin/sh', '-c', 'kill -TERM $$'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0], 128 + signal.SIGTERM)
        result = self.runner(body, 'print encode_json([_capture(undef, @ARGV)]);',
            ['/usr/bin/python3', '-c', "import os; os.write(2,b'e'*200000); os.write(1,b'o'*200000)"])
        self.assertEqual(result.returncode, 0, result.stderr)
        status, out, err = json.loads(result.stdout)
        self.assertEqual((status, len(out), len(err)), (0, 200000, 200000))


class WiringTests(unittest.TestCase):
    def test_python_staging_manifests_cover_every_module(self):
        source = (ROOT / 'd-i/forky/scripts/desktop/components.sh').read_text()
        for function, package in [('desktop_ai_copilots_python_modules', 'labwc_ai_copilots'),
                                  ('desktop_labwc_managed_app_python_modules', 'labwc_managed_app'),
                                  ('desktop_labwc_firewall_python_modules', 'labwc_firewall')]:
            match = re.search(function + r"\(\) \{\s*cat <<'EOF'\n(.*?)\nEOF", source, re.S)
            self.assertIsNotNone(match, function)
            self.assertEqual(set(match[1].splitlines()), {p.name for p in (PYLIB / package).glob('*.py')})
        self.assertEqual(set(integrity.ALL_MODULES), {p.name for p in (PYLIB / 'labwc_managed_app').glob('*.py')})

    def test_apparmor_allows_new_imports_without_broadening_package_read(self):
        text = (TARGET / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
        for profile in ('managed-labwc-chatgpt', 'managed-labwc-managed-app'):
            block = text.split('profile ' + profile + ' ', 1)[1].split('\nprofile ', 1)[0]
            self.assertIn('network_namespace,profiles,recovery,runtime', block)
        for profile in ('managed-labwc-adb-action', 'managed-labwc-output-watch',
                        'managed-labwc-mute-default-microphone', 'managed-whisper-record-toggle'):
            block = text.split('profile ' + profile + ' ', 1)[1].split('\nprofile ', 1)[0]
            self.assertIn('/managed-runtime/Managed/Process.pm r,', block)
        block = text.split('profile managed-labwc-terminal ', 1)[1].split('\nprofile ', 1)[0]
        self.assertIn('/usr/local/bin/labwc-wayland-app rPx -> managed-labwc-generic-app,', block)

    def test_ai_bootstrap_has_explicit_isolated_versioned_package_path(self):
        source = (TARGET / 'usr/local/libexec/labwc-ai-model-info').read_text()
        self.assertTrue(source.startswith('#!/usr/bin/python3 -I\n'))
        self.assertIn('sys.dont_write_bytecode = True', source)
        self.assertLess(source.index('require_managed_path(PACKAGE_DIRECTORY / name'), source.index('sys.path.insert'))
        self.assertIn('sys.path.insert(0, str(PACKAGE_ROOT))', source)
        self.assertIn('("__init__.py", "cli.py", "gguf.py")', source)


if __name__ == '__main__':
    unittest.main()
