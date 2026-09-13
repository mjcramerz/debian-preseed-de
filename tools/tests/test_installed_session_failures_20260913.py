#!/usr/bin/python3
"""Installed-log regressions: no live services, devices, compiler or compositor.

NVIDIA cases use real temporary directories/symlinks and synthetic character
metadata, because these tests must neither create devices nor require hardware.
"""
import ast
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / 'd-i/forky/hooks/target'
LIBEXEC = TARGET / 'usr/local/libexec'
USER_UNITS = TARGET / 'etc/skel-desktop/.config/systemd/user'


def load(leaf):
    loader = importlib.machinery.SourceFileLoader('regression_' + leaf.replace('-', '_'), str(LIBEXEC / leaf))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class NvidiaLinkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dev = Path(self.temporary.name)
        self.helper = load('managed-nvidia-char-links')
        self.real_stat = os.stat
        self.metadata = {}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(self.helper.os, 'stat', side_effect=self.device_stat))
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(contextlib.redirect_stderr(self.output))
        # Test directory trust independently of the test runner's UID.
        real_fstat = os.fstat
        def directory_stat(fd):
            st = real_fstat(fd)
            return SimpleNamespace(st_uid=0, st_mode=st.st_mode)
        self.stack.enter_context(mock.patch.object(self.helper.os, 'fstat', side_effect=directory_stat))

    def device_stat(self, *args, **kwargs):
        st = self.real_stat(*args, **kwargs)
        return self.metadata.get((st.st_dev, st.st_ino), st)

    def device(self, name='nvidia0', major=195, minor=0, uid=0):
        path = self.dev / name
        path.write_bytes(b'fixture, not a real device')
        st = self.real_stat(path)
        self.metadata[st.st_dev, st.st_ino] = SimpleNamespace(
            st_mode=stat.S_IFCHR | 0o660, st_uid=uid, st_rdev=os.makedev(major, minor))
        return path

    def test_check_is_read_only_and_reports_all_missing_links(self):
        self.device(); self.device('nvidia-uvm', 511, 0)
        self.assertEqual(self.helper.reconcile(self.dev, check=True), 2)
        self.assertFalse((self.dev / 'char').exists())
        self.assertIn('195:0', self.output.getvalue())
        self.assertIn('511:0', self.output.getvalue())

    def test_creates_links_then_is_idempotent(self):
        self.device(); self.device('nvidiactl', 195, 255)
        self.assertEqual(self.helper.reconcile(self.dev), 0)
        link = self.dev / 'char/195:0'
        before = link.lstat().st_ino
        self.assertEqual(os.readlink(link), '../nvidia0')
        self.assertEqual(self.helper.reconcile(self.dev, check=True), 0)
        self.assertEqual(self.helper.reconcile(self.dev), 0)
        self.assertEqual(link.lstat().st_ino, before)
        self.assertEqual(sorted(p.name for p in link.parent.iterdir()), ['195:0', '195:255'])

    def test_repairs_wrong_symlink_but_not_a_regular_file(self):
        self.device(); char = self.dev / 'char'; char.mkdir()
        link = char / '195:0'; link.symlink_to('../missing')
        self.assertEqual(self.helper.reconcile(self.dev, check=True), 1)
        self.assertEqual(os.readlink(link), '../missing')
        self.assertEqual(self.helper.reconcile(self.dev), 0)
        link.unlink(); link.write_text('do not overwrite')
        self.assertEqual(self.helper.reconcile(self.dev), 1)
        self.assertEqual(link.read_text(), 'do not overwrite')

    def test_reconciles_late_nodes_and_dynamic_major(self):
        self.device(); self.helper.reconcile(self.dev)
        self.device('nvidia-uvm-tools', 507, 1)
        self.assertEqual(self.helper.reconcile(self.dev), 0)
        self.assertEqual(os.readlink(self.dev / 'char/507:1'), '../nvidia-uvm-tools')

    def test_rejects_symlink_device_without_following_it(self):
        source = self.device('real-device')
        (self.dev / 'nvidia0').symlink_to(source.name)
        self.assertEqual(self.helper.reconcile(self.dev), 1)
        self.assertFalse((self.dev / 'char').exists())

    def test_rejects_untrusted_devices_and_directories(self):
        self.device(uid=1000)
        self.assertEqual(self.helper.reconcile(self.dev), 1)
        self.device(uid=0)
        char = self.dev / 'char'; char.symlink_to(self.dev, target_is_directory=True)
        with self.assertRaises(OSError): self.helper.reconcile(self.dev)
        char.unlink(); char.mkdir(mode=0o777); char.chmod(0o777)
        with self.assertRaises(ValueError): self.helper.reconcile(self.dev)

    def test_no_devices_and_unrelated_files_are_untouched(self):
        (self.dev / 'unrelated').write_text('preserve')
        self.assertEqual(self.helper.reconcile(self.dev), 0)
        self.assertEqual((self.dev / 'unrelated').read_text(), 'preserve')
        self.assertFalse((self.dev / 'char').exists())

    def test_cli_rejects_nonroot_and_caller_supplied_paths(self):
        with mock.patch.object(self.helper.os, 'geteuid', return_value=1000):
            self.assertEqual(self.helper.main([]), 1)
        for arguments in (['/tmp/other'], ['--check', '/tmp/other'], ['--force']):
            self.assertEqual(self.helper.main(arguments), 2)


class UserStateTests(unittest.TestCase):
    def setUp(self):
        self.helper = load('labwc-session-state')
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(self.helper.os, 'getuid', return_value=1000))
        self.stack.enter_context(mock.patch.object(self.helper.os, 'geteuid', return_value=1000))
        self.stack.enter_context(mock.patch.object(self.helper.os, 'umask'))
        self.stack.enter_context(mock.patch.dict(os.environ, {}, clear=True))
        self.unlink = self.stack.enter_context(mock.patch.object(Path, 'unlink'))
        self.runtime_mode = stat.S_IFDIR | 0o700
        self.bus_mode = stat.S_IFSOCK | 0o600
        self.uid = 1000
        self.stack.enter_context(mock.patch.object(Path, 'lstat', autospec=True, side_effect=self.path_stat))

    def path_stat(self, path):
        mode = self.bus_mode if path.name == 'bus' else self.runtime_mode
        return SimpleNamespace(st_mode=mode, st_uid=self.uid)

    def test_reconstructs_only_the_invoking_users_canonical_bus(self):
        self.assertEqual(self.helper.main(['cancel']), 0)
        self.assertEqual(os.environ['XDG_RUNTIME_DIR'], '/run/user/1000')
        self.assertEqual(os.environ['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=/run/user/1000/bus')
        self.unlink.assert_called_once_with(missing_ok=True)

    def test_foreign_environment_is_rejected(self):
        for key, value in [('XDG_RUNTIME_DIR', '/run/user/1001'),
                           ('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/tmp/fake-bus')]:
            with self.subTest(key=key), mock.patch.dict(os.environ, {key: value}, clear=True):
                with self.assertRaises(self.helper.Error): self.helper.main(['cancel'])
        self.unlink.assert_not_called()

    def test_symlink_world_writable_and_wrong_owner_are_rejected(self):
        for runtime, bus, uid in [(stat.S_IFLNK | 0o700, self.bus_mode, 1000),
                                 (stat.S_IFDIR | 0o777, self.bus_mode, 1000),
                                 (self.runtime_mode, stat.S_IFLNK | 0o600, 1000),
                                 (self.runtime_mode, stat.S_IFREG | 0o600, 1000),
                                 (self.runtime_mode, self.bus_mode, 1001)]:
            self.runtime_mode, self.bus_mode, self.uid = runtime, bus, uid
            with self.assertRaises(self.helper.Error): self.helper.main(['cancel'])
        self.unlink.assert_not_called()

    def test_root_remains_forbidden(self):
        with mock.patch.object(self.helper.os, 'getuid', return_value=0):
            with self.assertRaisesRegex(self.helper.Error, 'never root'): self.helper.main(['cancel'])

    def test_state_and_restore_are_explicitly_user_units(self):
        for name in ('labwc-session-state@.service', 'labwc-session-restore.service'):
            content = (USER_UNITS / name).read_text()
            for required in ('Environment=XDG_RUNTIME_DIR=%t',
                             'Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus',
                             'PartOf=labwc-session.target', 'KillMode=control-group'):
                self.assertIn(required, content)
            self.assertNotIn('User=', content)
            self.assertFalse((TARGET / 'etc/systemd/system' / name).exists())
        source = (LIBEXEC / 'labwc-admin-action-worker').read_text()
        self.assertIn('"start", "labwc-session-state@" + action + ".service"', source)
        self.assertIn('"--user", "--machine=" + self.machine', source)


class RendererValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for path in ('etc/default', 'etc/environment.d', 'usr/local/bin', 'etc/skel-desktop/.config/labwc/environment.d'):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        policy = {'LABWC_WLR_RENDERER':'gles2', 'LABWC_GSK_RENDERER':'opengl',
                  'LABWC_GDK_DISABLE':'vulkan', 'LABWC_WLR_NO_HARDWARE_CURSORS':'1',
                  'LABWC_WLR_SCENE_DISABLE_DIRECT_SCANOUT':'1', 'LABWC_GREETER_WLR_RENDERER':'gles2',
                  'LABWC_GREETER_GSK_RENDERER':'opengl', 'LABWC_GREETER_GDK_DISABLE':'vulkan',
                  'LABWC_GREETER_WLR_NO_HARDWARE_CURSORS':'1'}
        self.defaults = self.root / 'etc/default/labwc-desktop'
        self.defaults.write_text('\n'.join(f'{k}={v}' for k,v in policy.items()) + '\n')
        for leaf in ('labwc-session', 'labwc-greeter-session', 'labwc-autostart'):
            source = TARGET / 'usr/local/bin' / leaf
            if not source.exists(): source = source.with_suffix('.tmpl')
            (self.root / 'usr/local/bin' / leaf).write_bytes(source.read_bytes())
        env = Path('etc/skel-desktop/.config/labwc/environment.d/10-wayland.env')
        (self.root / env).write_bytes((TARGET / (str(env) + ".tmpl")).read_bytes())
        content = (ROOT / 'd-i/forky/scripts/firstboot/04-validation.sh').read_text()
        self.function = content.split('desktop_renderer_policy_matches() {',1)[1].split('\n}\n',1)[0]
        for prefix in ('/usr/local/bin/', '/etc/'):
            self.function = self.function.replace(prefix, str(self.root) + prefix)

    def check(self):
        return subprocess.run(['/bin/sh', '-eu', '-c', self.function], capture_output=True, text=True, timeout=5)

    def test_real_guarded_exports_pass(self):
        result = self.check(); self.assertEqual(result.returncode, 0, result.stderr)

    def test_bad_policy_is_not_hidden(self):
        self.defaults.write_text(self.defaults.read_text().replace('LABWC_WLR_RENDERER=gles2', 'LABWC_WLR_RENDERER=pixman'))
        self.assertNotEqual(self.check().returncode, 0)

    def test_missing_cleanup_membership_is_not_hidden(self):
        session = self.root / 'usr/local/bin/labwc-session'
        session.write_text(session.read_text().replace('${labwc_x11_environment_names}', ''))
        self.assertNotEqual(self.check().returncode, 0)

    def test_missing_export_is_not_hidden(self):
        session = self.root / 'usr/local/bin/labwc-session'
        session.write_text(session.read_text().replace('export WLR_RENDERER=', 'WLR_RENDERER='))
        self.assertNotEqual(self.check().returncode, 0)


class PanelAndWiringTests(unittest.TestCase):
    def test_wrapper_preserves_child_signals_and_real_exit_failures(self):
        source = (LIBEXEC / 'labwc-panel-run').read_text()
        for exit_code, number in ((7, None), (143, None), (None, signal.SIGTERM), (None, signal.SIGABRT)):
            child = f'import sys; sys.exit({exit_code})' if number is None else f'import os; os.kill(os.getpid(), {int(number)})'
            command = "supervise([sys.executable, '-c', " + repr(child) + "], set())"
            script = source.replace('status = main(sys.argv[1:])', 'status = ' + command)
            # Disable core files, but do not replace the real supervisor/epilogue.
            script = 'import resource; resource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n' + script
            result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, timeout=10)
            expected = exit_code if number is None else -int(number)
            self.assertEqual(result.returncode, expected, result.stderr)

    def test_all_panel_click_commands_use_session_bound_user_services(self):
        content = (TARGET / 'etc/skel-desktop/.config/waybar/config.tmpl').read_text()
        entries = re.findall(r'"(on-(?:click(?:-middle|-right)?|scroll-up|scroll-down))"\s*:\s*("(?:[^"\\]|\\.)*")', content)
        count = 0
        for key, literal in entries:
            command = json.loads(literal)
            if command in ('activate', 'minimize-raise', 'close'): continue
            if key.startswith('on-scroll'):
                self.assertFalse(command.startswith('/usr/bin/systemd-run'))
                continue
            args = shlex.split(command)
            self.assertEqual(args[:2], ['/usr/bin/systemd-run', '--user'])
            for option in ('--collect', '--service-type=exec', '--expand-environment=no',
                           '--property=ExitType=cgroup', '--property=KillMode=control-group',
                           '--property=PartOf=labwc-session.target', '--property=Requisite=labwc-session.target'):
                self.assertIn(option, args)
            self.assertNotIn('--scope', args); self.assertNotIn('--pipe', args)
            count += 1
        self.assertEqual(count, 56)

    def test_user_bus_helpers_inherit_bounded_apparmor_profile(self):
        text = (TARGET / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
        profile = text.split('profile managed-labwc-session-state ',1)[1].split('\n}\n',1)[0]
        self.assertIn('/usr/bin/{systemctl,systemd-run,wlrctl,wl-copy,cliphist,notify-send} rix,', profile)
        self.assertIn('owner /run/user/[0-9]*/{bus,systemd/private} rw,', profile)
        self.assertNotIn('/dev/rfkill', profile)
        for line in profile.splitlines():
            if not line.lstrip().startswith('#'):
                self.assertNotRegex(line, r'\b(?:PUx|pux|Ux|ux),')
        panel = (TARGET / 'etc/apparmor.d/managed-labwc-session').read_text()
        self.assertIn('signal (send, receive) peer=managed-labwc-panel-run,', panel)

    def test_nvidia_path_unit_is_event_driven_without_exists_loop(self):
        units = TARGET / 'etc/systemd/system'
        watcher = (units / 'managed-nvidia-char-links.path').read_text()
        service = (units / 'managed-nvidia-char-links.service').read_text()
        self.assertIn('PathChanged=/dev', watcher)
        self.assertNotIn('PathExistsGlob=', watcher)
        self.assertNotIn('RemainAfterExit=yes', service)
        self.assertIn('Before=greetd.service firstboot.service', service)
        self.assertIn('CapabilityBoundingSet=\n', service)
        source = (LIBEXEC / 'managed-nvidia-char-links').read_text()
        ast.parse(source)
        self.assertNotIn('os.mknod', source)
        self.assertNotIn('subprocess', source)


class SecondaryDiagnosticTests(unittest.TestCase):
    def test_networkd_disabled_is_distinct_from_failed_or_expected_backend(self):
        text = (ROOT / 'd-i/forky/scripts/firstboot/03-network.sh').read_text()
        body = 'capture_networkctl_status() {' + text.split('capture_networkctl_status() {', 1)[1].split('\n}\n', 1)[0] + '\n}\n'
        for active, enabled, skip in [('inactive','disabled',True), ('inactive','masked',True),
                                      ('active','enabled',False), ('failed','disabled',False),
                                      ('inactive','enabled',False), ('','',False)]:
            prelude = ('timeout() { shift; shift; "$@"; }\n'
                       'capture() { printf "%s\\n" "$*"; }\n'
                       'systemctl() { case "$1" in show) printf "%s\\n" ' + shlex.quote(active) +
                       ' ;; is-enabled) printf "%s\\n" ' + shlex.quote(enabled) + ' ;; esac; }\n')
            result = subprocess.run(['/bin/sh', '-eu', '-c', prelude + body + 'capture_networkctl_status'],
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual('NOT_APPLICABLE:' in result.stdout, skip, (active, enabled, result.stdout))
            self.assertEqual('networkctl status --no-pager' in result.stdout, not skip)

    def test_bouncer_package_operation_overrides_only_child_locale(self):
        line = next(line for line in (ROOT / 'd-i/forky/scripts/late/crowdsec.sh').read_text().splitlines()
                    if line.startswith('run_in_target "install CrowdSec bouncer after engine configuration"'))
        args = shlex.split(line)
        boundary = args.index('apt-get')
        self.assertIn('LC_ALL=C', args[args.index('env') + 1:boundary])
        # Substitute only apt-get, and execute the real env argument prefix.
        result = subprocess.run(args[args.index('env'):boundary] + ['/usr/bin/locale'],
                                env=dict(os.environ, LC_ALL='missing_LOCALE'), text=True,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LC_ALL=C', result.stdout)
        self.assertNotIn('Cannot set', result.stderr)


if __name__ == '__main__':
    unittest.main()
