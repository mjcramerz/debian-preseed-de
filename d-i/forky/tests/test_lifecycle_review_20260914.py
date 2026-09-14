"""Scoped review regressions. No service activation or host boot writes.

Signal tests operate only on disposable fixture children, never system services.
The unit checks are a reviewed allowlist, not a claim of live namespace support.
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
SYSTEM = TARGET/'etc/systemd/system'
PRIVATE = {'bluetooth-controller-init.service', 'managed-nvidia-char-links.service',
           'zram-writeback.service.tmpl', 'zram-writebackd.service.tmpl'}


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


gitops = load('review_gitops', TARGET/'usr/local/bin/gitops')
ssh = load('review_ssh', TARGET/'usr/local/libexec/managed-ssh-install.py')
power = load('review_power', TARGET/'usr/local/libexec/labwc-admin-action-worker')
debug = load('review_debug', TARGET/'usr/local/libexec/debugsys.py')


def assignments(path, section='Service'):
    active = ''
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith('['):
            active = line.strip('[]')
        elif active == section and '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values.setdefault(key, []).append(value)
    return values


class UnitBoundaryTests(unittest.TestCase):
    def test_private_pids_is_exactly_the_four_reviewed_system_units(self):
        found = set()
        for path in TARGET.rglob('*'):
            if path.is_file() and path.name.endswith(('.service', '.service.tmpl', '.conf')):
                if 'yes' in assignments(path).get('PrivatePIDs', []):
                    self.assertEqual(path.parent, SYSTEM)
                    found.add(path.name)
        self.assertEqual(found, PRIVATE)

    def test_candidates_keep_host_identity_foreground_and_group_cleanup(self):
        for name in PRIVATE:
            with self.subTest(name=name):
                data = assignments(SYSTEM/name)
                self.assertEqual(data['PrivateUsers'], ['no'])
                self.assertIn(data['Type'][-1], ('exec', 'oneshot'))
                self.assertEqual(data['KillMode'], ['control-group'])
                self.assertEqual(data['TimeoutStopSec'], ['20s'])
                self.assertNotIn('PIDFile', data)

    def test_zram_retains_aggregate_proc_and_runtime_lock(self):
        for name in ('zram-writeback.service.tmpl', 'zram-writebackd.service.tmpl'):
            data = assignments(SYSTEM/name)
            self.assertEqual(data['ProcSubset'], ['all'])
            self.assertEqual(data['RuntimeDirectory'], ['zram'])
            self.assertNotIn('ProtectKernelTunables', data)

    def test_bluetooth_retains_host_management_capabilities(self):
        data = assignments(SYSTEM/'bluetooth-controller-init.service')
        self.assertEqual(data['CapabilityBoundingSet'], ['CAP_NET_ADMIN CAP_NET_RAW'])
        self.assertEqual(data['AmbientCapabilities'], ['CAP_NET_ADMIN CAP_NET_RAW'])
        self.assertNotIn('PrivateNetwork', data)
        self.assertNotIn('PrivateDevices', data)

    def test_host_sensitive_workers_explicitly_excluded(self):
        for name in ('labwc-admin-action@.service', 'debugsys-boot-report.service', 'tmpfs-pre-clean.service.tmpl'):
            data = assignments(SYSTEM/name)
            self.assertEqual(data['PrivatePIDs'], ['no'])
            self.assertEqual(data['PrivateUsers'], ['no'])

    def test_agent_dropins_require_ordered_active_desktop(self):
        for kind in ('socket', 'service'):
            path = TARGET/f'etc/systemd/user/ssh-agent.{kind}.d/10-labwc-session.conf'
            data = assignments(path, 'Unit')
            self.assertIn('labwc-session.target', data['Requisite'])
            self.assertIn('labwc-session.target', data['After'])
            self.assertIn('labwc-session.target', data['PartOf'])
            self.assertIn('labwc-compositor.service', data['BindsTo'])
            self.assertNotIn('ExecStart', assignments(path))
            self.assertNotIn('ListenStream', assignments(path, 'Socket'))

    def test_loader_remains_retryable_and_not_pid_namespaced(self):
        path = TARGET/'etc/skel-desktop/.config/systemd/user/labwc-ssh-key-load.service'
        data = assignments(path)
        self.assertEqual(data['PrivatePIDs'], ['no'])
        self.assertEqual(data['PrivateUsers'], ['no'])
        self.assertNotIn('RemainAfterExit', data)
        self.assertIn('labwc-session.target', ' '.join(assignments(path, 'Unit')['After']))

    def test_namespace_init_helpers_handle_term(self):
        self.assertIn("trap 'exit 143' TERM", (TARGET/'usr/local/libexec/bluetooth-controller-init').read_text())
        self.assertIn('signal.signal(sig,', (TARGET/'usr/local/libexec/managed-nvidia-char-links').read_text())
        self.assertIn('$SIG{TERM} = sub { exit 143; };', (TARGET/'usr/local/libexec/zram-writeback.tmpl').read_text())

    def test_transient_forking_lock_explicitly_keeps_host_namespaces(self):
        worker = power.Worker(1000, 'fixture', 'suspend')
        with mock.patch.object(power, 'run') as run, mock.patch.object(worker, 'helper'):
            worker.lock()
        args = run.call_args.args[0]
        for value in ('--service-type=forking', '--property=PrivatePIDs=no',
                      '--property=PrivateUsers=no', '--property=KillMode=control-group'):
            self.assertIn(value, args)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lifecycle-review-', dir='/root' if os.geteuid() == 0 else None)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)


class ProtectionTests(Fixture):
    def config(self, value):
        path = self.root/'gitops.env'
        path.write_text(f'{gitops.KEYS[0]}="{value}"\n{gitops.KEYS[1]}=""\n')
        path.chmod(0o600)
        return path

    def test_noncanonical_patterns_fail_instead_of_silently_unprotecting(self):
        for pattern in ('./important', 'a//b', 'a/./b', '.', 'a///b/', 'a//', 'a///'):
            with self.subTest(pattern=pattern), self.assertRaises(gitops.GitOpsError):
                gitops.load_patterns(self.config(pattern), 'forks')

    def test_directory_globs_protect_contents_and_type_replacements(self):
        for name in ('vendor/foo.keep', 'vendor/foo.keep/deep/item', 'vendor/bar.keep/item'):
            with self.subTest(name=name):
                self.assertTrue(gitops.protected(name, ['vendor/*.keep/']))
        self.assertFalse(gitops.protected('other/vendor/foo.keep/item', ['vendor/*.keep/']))
        self.assertFalse(gitops.protected('vendor/not-matching/item', ['vendor/*.keep/']))

    def test_globbed_protected_absence_is_not_imported(self):
        local = {'vendor/foo.keep/data': ('100644', 'local')}
        upstream = {'vendor/foo.keep': ('100644', 'replacement'),
                    'vendor/new.keep/secret': ('100644', 'new'),
                    'ordinary': ('100644', 'update')}
        result = gitops.desired_tree(local, upstream, ['vendor/*.keep/'])
        self.assertEqual(result, {**local, 'ordinary': ('100644', 'update')})

    def test_empty_independent_policies_are_still_valid(self):
        self.assertEqual(gitops.load_patterns(self.config(''), 'forks'), [])


class PublicKeyModeTests(Fixture):
    def test_public_644_allowed_without_weakening_private_check(self):
        p = self.root/'key.pub'
        p.write_bytes(b'public fixture')
        p.chmod(0o644)
        self.assertEqual(ssh.read_direct(p, 100, os.getuid(), public=True), b'public fixture')
        with self.assertRaises(ssh.InstallError):
            ssh.read_direct(p, 100, os.getuid())

    def test_public_modes_and_hardlinks_still_restricted(self):
        p = self.root/'key.pub'
        p.write_bytes(b'public fixture')
        for mode in (0o666, 0o664, 0o640, 0o755):
            p.chmod(mode)
            with self.subTest(mode=mode), self.assertRaises(ssh.InstallError):
                ssh.read_direct(p, 100, os.getuid(), public=True)
        p.chmod(0o644)
        os.link(p, self.root/'duplicate')
        with self.assertRaises(ssh.InstallError):
            ssh.read_direct(p, 100, os.getuid(), public=True)

    @unittest.skipUnless(os.geteuid() == 0, 'root-owned destination fixture')
    def test_pair_update_accepts_existing_public_644(self):
        ssh.publish_pair(self.root, b'old-private', b'old-public', 0, 0)
        public = self.root/'.ssh/id_git_ed25519.pub'
        public.chmod(0o644)
        ssh.publish_pair(self.root, b'new-private', b'new-public', 0, 0)
        self.assertEqual(public.read_bytes(), b'new-public')
        self.assertEqual((self.root/'.local/share/managed-ssh/private/id_git_ed25519').read_bytes(), b'new-private')

    @unittest.skipUnless(os.geteuid() == 0, 'root-owned destination fixture')
    def test_failed_pair_update_preserves_old_contents_and_modes(self):
        ssh.publish_pair(self.root, b'old-private', b'old-public', 0, 0)
        public = self.root/'.ssh/id_git_ed25519.pub'
        public.chmod(0o644)
        original = ssh.publish
        def fail_once(path, data, *args):
            if path == public and data == b'new-public':
                raise OSError('fixture failure')
            return original(path, data, *args)
        with mock.patch.object(ssh, 'publish', side_effect=fail_once), self.assertRaises(OSError):
            ssh.publish_pair(self.root, b'new-private', b'new-public', 0, 0)
        private = self.root/'.local/share/managed-ssh/private/id_git_ed25519'
        self.assertEqual(private.read_bytes(), b'old-private')
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
        self.assertEqual(public.read_bytes(), b'old-public')
        self.assertEqual(stat.S_IMODE(public.stat().st_mode), 0o644)


class GitSSHFlowTests(Fixture):
    def invoke(self, action, *, signed=False, metadata=True, uid='1000', active=True):
        # Rewrite absolute dependencies ONLY in this isolated test copy.
        script = (TARGET/'usr/local/bin/git-ssh').read_text()
        checks = self.root/'checks'
        checks.write_text('managed_ssh_context() { public=/fixture.pub; ' + ('true' if metadata else 'false') + '; }\nmanaged_ssh_socket() { true; }\n')
        idcmd = self.root/'id'; idcmd.write_text('#!/bin/sh\nprintf "%s\\n" '+shlex.quote(uid)+'\n'); idcmd.chmod(0o700)
        systemctl = self.root/'systemctl'
        systemctl.write_text('#!/bin/sh\n' + ('' if active else '[ "$2" != is-active ] || exit 3\n') + 'exit 0\n'); systemctl.chmod(0o700)
        add = self.root/'ssh-add'; add.write_text('#!/bin/sh\nexit '+('0' if signed else '1')+'\n'); add.chmod(0o700)
        script = script.replace('/usr/local/libexec/managed-ssh-checks', shlex.quote(str(checks)))
        for original, replacement in (('/usr/bin/id', idcmd), ('/usr/bin/systemctl', systemctl), ('/usr/bin/ssh-add', add)):
            script = script.replace(original, shlex.quote(str(replacement)))
        return subprocess.run(['/bin/sh', '-c', script, 'fixture', action], capture_output=True, text=True, timeout=5)

    def test_skipped_loader_cannot_report_success_without_identity(self):
        result = self.invoke('unlock', signed=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('identity unavailable', result.stderr)

    def test_valid_signing_identity_completes_unlock(self):
        self.assertEqual(self.invoke('unlock', signed=True).returncode, 0)

    def test_lock_works_even_when_key_metadata_is_broken(self):
        self.assertEqual(self.invoke('lock', metadata=False).returncode, 0)

    def test_status_rejects_unsafe_identity(self):
        self.assertNotEqual(self.invoke('status', metadata=False, signed=True).returncode, 0)

    def test_root_is_rejected(self):
        self.assertNotEqual(self.invoke('unlock', uid='0', signed=True).returncode, 0)

    def test_inactive_session_is_rejected(self):
        result = self.invoke('unlock', active=False, signed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('active Labwc', result.stderr)


class LifecycleTests(Fixture):
    def assert_dead(self, pid):
        for _ in range(50):
            try:
                text = Path(f'/proc/{pid}/stat').read_text()
            except FileNotFoundError:
                return
            if text.rsplit(')', 1)[1].split()[0] == 'Z':
                return  # Dead, awaiting container PID 1 reaping.
            time.sleep(.02)
        self.fail(f'fixture child {pid} survived its owner')

    def test_gitops_term_and_hup_reap_independent_descendants(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(sig=sig):
                pidfile = self.root/f'child-{sig}'
                helper = self.root/f'sleep-{sig}.sh'
                helper.write_text('#!/bin/sh\nsleep 40 &\nprintf "%s\\n" "$!" > '+shlex.quote(str(pidfile))+'\nwait\n')
                helper.chmod(0o700)
                code = ('import runpy,sys; m=runpy.run_path(sys.argv[1]); '
                        'm["install_signal_handlers"](); '
                        'm["git"]("-c", "alias.fixture=!"+sys.argv[2], "fixture")')
                proc = subprocess.Popen([sys.executable, '-B', '-c', code,
                    str(TARGET/'usr/local/bin/gitops'), str(helper)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                child = None
                try:
                    deadline = time.monotonic() + 5
                    while not pidfile.exists() and proc.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(pidfile.exists(), 'fixture never started')
                    child = int(pidfile.read_text())
                    proc.send_signal(sig)
                    _, err = proc.communicate(timeout=5)
                    self.assertEqual(proc.returncode, 128 + sig, err)
                    self.assert_dead(child)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.communicate(timeout=5)
                    if child:
                        try: os.kill(child, signal.SIGKILL)
                        except ProcessLookupError: pass

    def test_power_transport_cleans_on_unexpected_communicate_error(self):
        fake = mock.Mock(pid=987654, stdout=io.StringIO(), stderr=io.StringIO())
        fake.communicate.side_effect = UnicodeError('fixture decoding failure')
        with mock.patch.object(power.subprocess, 'Popen', return_value=fake), \
             mock.patch.object(power.os, 'killpg') as kill, self.assertRaises(UnicodeError):
            power.run(['/fixture'])
        kill.assert_called_once_with(987654, signal.SIGKILL)
        fake.wait.assert_called_once_with(timeout=2)
        self.assertTrue(fake.stdout.closed)
        self.assertTrue(fake.stderr.closed)

    def test_power_reap_timeout_still_closes_transport_pipes(self):
        fake = mock.Mock(pid=987654, stdout=io.StringIO(), stderr=io.StringIO(), returncode=0)
        fake.communicate.return_value = ('ok', '')
        fake.wait.side_effect = subprocess.TimeoutExpired('/fixture', 2)
        with mock.patch.object(power.subprocess, 'Popen', return_value=fake), \
             mock.patch.object(power.os, 'killpg'), self.assertRaises(subprocess.TimeoutExpired):
            power.run(['/fixture'])
        fake.wait.assert_called_once_with(timeout=2)
        self.assertTrue(fake.stdout.closed)
        self.assertTrue(fake.stderr.closed)

    def test_pinentry_signal_permissions_are_peer_specific_and_symmetric(self):
        text = (TARGET/'etc/apparmor.d/managed-desktop-wrappers').read_text()
        loader = text.split('profile managed-labwc-ssh-key-load ', 1)[1].split('\n}', 1)[0]
        pinentry = text.split('profile managed-labwc-ssh-pinentry ', 1)[1].split('\n}', 1)[0]
        self.assertIn('signal (send) set=(term, kill, int, hup) peer=managed-labwc-ssh-pinentry,', loader)
        self.assertIn('signal (receive) set=(term, kill, int, hup) peer=managed-labwc-ssh-key-load,', pinentry)
        self.assertIn('signal (receive) set=(chld) peer=managed-labwc-ssh-pinentry,', loader)
        self.assertIn('signal (send) set=(chld) peer=managed-labwc-ssh-key-load,', pinentry)
        self.assertNotIn('signal (send),', loader)
        self.assertNotIn('network inet', loader)


class DiagnosticsTests(unittest.TestCase):
    def test_metadata_reports_selected_namespace_properties_not_environments(self):
        names = set(debug.ISOLATION_PROPERTIES.split(','))
        self.assertTrue({'PrivatePIDs', 'PrivateUsers', 'ProcSubset', 'KillMode', 'ControlGroup', 'MainPID'} <= names)
        self.assertFalse({'Environment', 'EnvironmentFiles', 'PassEnvironment'} & names)
        self.assertTrue({name.removesuffix('.tmpl') for name in PRIVATE} <= set(debug.ISOLATION_UNITS))
        self.assertTrue(any(label == 'service-isolation' for label, _ in debug.PROBES['security']))

    def test_host_namespace_maps_are_collected_as_bounded_files(self):
        self.assertTrue(any('uid_map,gid_map' in value for value in debug.FILES['security']))

    def test_dynamic_filesystem_query_obeys_report_command_budget(self):
        source = (TARGET/'usr/local/libexec/debugsys.py').read_text()
        self.assertIn("self.command(category,'root-filesystem-type'", source)
        self.assertNotIn("run(['findmnt','-n','-o','FSTYPE','/']", source)


if __name__ == '__main__':
    unittest.main()
