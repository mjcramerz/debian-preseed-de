#!/usr/bin/python3
"""Mocked power/state regressions. Never contact PID 1 or a live compositor."""
import base64
import contextlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[2] / 'd-i/forky/hooks/target'


def load_module(name, leaf):
    loader = importlib.machinery.SourceFileLoader(name, str(TARGET / 'usr/local/libexec' / leaf))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


power = load_module('power_worker_test', 'labwc-admin-action-worker')
state = load_module('session_state_test', 'labwc-session-state')


class PowerWorkerTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.failure = None
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(power, 'run', side_effect=self.mock_run))
        self.sync = self.stack.enter_context(mock.patch.object(power.os, 'sync'))

    def mock_run(self, argv, **kwargs):
        self.calls.append(argv)
        if self.failure and self.failure(argv):
            raise power.Error('injected failure')
        return ''

    def execute(self, action):
        worker = power.Worker(1000, 'desktop', action)
        worker.execute()
        return worker

    def test_reboot_and_poweroff_order_and_exact_uid_cleanup(self):
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                self.calls.clear()
                self.execute(action)
                prepare = next(i for i, c in enumerate(self.calls) if c[-2:] == ['start', 'labwc-session-state@prepare.service'])
                stop = next(i for i, c in enumerate(self.calls) if c[-2:] == ['labwc-session.target', 'labwc-compositor.service'])
                terminate = self.calls.index(['/usr/bin/loginctl', 'terminate-user', '1000'])
                manager = self.calls.index(['/usr/bin/systemctl', 'stop', 'user@1000.service', 'user-1000.slice'])
                kill = self.calls.index(['/usr/bin/pkill', '--signal', 'TERM', '--uid', '1000'])
                final = self.calls.index(['/usr/bin/systemctl', '--force', action])
                self.assertLess(prepare, stop)
                self.assertLess(stop, terminate)
                self.assertLess(terminate, manager)
                self.assertLess(manager, kill)
                self.assertLess(kill, final)
                self.assertFalse(any(command.count('--force') > 1 for command in self.calls))

    def test_suspend_locks_without_saving_stopping_clearing_or_signalling_apps(self):
        self.execute('suspend')
        self.assertTrue(any('--service-type=forking' in c and c[-1] == '/usr/local/bin/labwc-lock' for c in self.calls))
        self.assertTrue(any(c[-2:] == ['start', 'labwc-session-state@locked.service'] for c in self.calls))
        self.assertEqual(self.calls[-1], ['/usr/bin/systemctl', '--force', 'suspend'])
        self.assertFalse(any('stop' in c or 'terminate-user' in c or c[0].endswith('/pkill') or c[-1] == 'labwc-session-state@prepare.service' for c in self.calls))
        self.sync.assert_not_called()

    def test_logout_uses_same_preparation_without_a_machine_power_action(self):
        self.execute('logout')
        self.assertTrue(any(c[-1] == 'labwc-session-state@prepare.service' for c in self.calls))
        self.assertTrue(any('terminate-user' in c for c in self.calls))
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_prepare_failure_never_tears_down_session(self):
        self.failure = lambda command: command[-1] == 'labwc-session-state@prepare.service'
        with self.assertRaises(power.Error):
            self.execute('poweroff')
        self.assertFalse(any('stop' in c or '--force' in c or c[0].endswith('/pkill') for c in self.calls))

    def test_failed_target_stop_never_reaches_forced_power(self):
        self.failure = lambda command: command[-2:] == ['labwc-session.target', 'labwc-compositor.service']
        with self.assertRaises(power.Error):
            self.execute('reboot')
        self.assertFalse(any('--force' in c or 'terminate-user' in c for c in self.calls))

    def test_failed_lock_never_suspends(self):
        self.failure = lambda command: command[-1] == 'labwc-session-state@locked.service'
        with self.assertRaises(power.Error):
            self.execute('suspend')
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_other_interactive_account_blocks_machine_action(self):
        def run(argv, **kwargs):
            self.calls.append(argv)
            if 'list-sessions' in argv:
                return 'c1 1000 desktop - -\nc2 1001 other - -\n'
            if 'show-session' in argv:
                return 'user\n'
            return ''
        with mock.patch.object(power, 'run', side_effect=run), self.assertRaisesRegex(power.Error, 'another interactive'):
            self.execute('poweroff')
        self.assertFalse(any(c[-1] == 'labwc-session-state@prepare.service' or '--force' in c for c in self.calls))

    def test_invalid_instance_never_executes_a_command(self):
        with mock.patch.object(power.os, 'geteuid', return_value=0):
            for value in ('0-poweroff', '01000-reboot', '1000-poweroff;id', '1000-hibernate', '../reboot', '1000-reboot-extra'):
                with self.subTest(value=value), self.assertRaises(power.Error):
                    power.main([value])
        self.assertEqual(self.calls, [])


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state, self.runtime = self.root / 'state', self.root / 'run'
        self.state.mkdir(mode=0o700)
        self.runtime.mkdir(mode=0o700)
        self.app = {'argv': ['/usr/local/bin/labwc-wayland-app', 'launch', '--', '/usr/bin/featherpad', '/home/user/document.txt'], 'cwd': '/home/user'}
        self.token = base64.urlsafe_b64encode(json.dumps(self.app).encode()).decode()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.ctl = self.stack.enter_context(mock.patch.object(state, 'ctl', return_value=''))
        self.run = self.stack.enter_context(mock.patch.object(state, 'run', return_value=''))
        self.stack.enter_context(mock.patch.object(state, 'notify'))
        self.clipboard = self.stack.enter_context(mock.patch.object(state, 'clear_clipboard'))
        self.orphans = self.stack.enter_context(mock.patch.object(state, 'stop_orphans'))

    def test_save_dialog_blocks_teardown_and_removes_launch_barrier(self):
        with mock.patch.object(state, 'services', return_value={}), mock.patch.object(state, 'windows', return_value='FeatherPad: Save?'):
            with self.assertRaisesRegex(state.Error, 'No session teardown'):
                state.prepare(self.state, self.runtime, timeout=0)
        self.assertFalse((self.runtime / 'labwc-session-closing').exists())
        self.assertFalse((self.state / 'resume.json').exists())
        self.clipboard.assert_not_called()
        self.orphans.assert_not_called()
        closes = [c for c in self.run.call_args_list if c.args[0] == ['/usr/bin/wlrctl', 'toplevel', 'close']]
        self.assertEqual(len(closes), 1)
        self.assertFalse(any('kill' in ' '.join(c.args[0]) for c in self.run.call_args_list))

    def test_success_records_state_before_clearing_clipboard_and_orphans(self):
        initial = {'labwc-editor.service': {'LABWC_SESSION_APP': '1', 'LABWC_SESSION_RESTORE': self.token}}
        with mock.patch.object(state, 'services', side_effect=[initial, {}]), mock.patch.object(state, 'windows', side_effect=['editor: document', '']):
            state.prepare(self.state, self.runtime, timeout=0)
        self.assertEqual(state.load(self.state / 'resume.json'), [dict(self.app, argv=self.app['argv'][:4])])
        self.assertEqual((self.state / 'resume.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.runtime / 'labwc-session-closing').exists())
        self.clipboard.assert_called_once()
        self.orphans.assert_called_once()

    def test_tray_process_blocks_even_without_windows(self):
        with mock.patch.object(state, 'services', return_value={'app.service': {'LABWC_SESSION_APP': '1'}}), mock.patch.object(state, 'windows', return_value=''):
            with self.assertRaisesRegex(state.Error, 'remaining application'):
                state.prepare(self.state, self.runtime, timeout=0)
        self.clipboard.assert_not_called()

    def test_nested_compositor_blocks_before_close_requests(self):
        with mock.patch.object(state, 'services', return_value={'cage.service': {'LABWC_SESSION_NESTED': '1'}}):
            with self.assertRaisesRegex(state.Error, 'nested Cage'):
                state.prepare(self.state, self.runtime, timeout=0)
        self.run.assert_not_called()

    def test_null_app_id_window_is_not_mistaken_for_empty_desktop(self):
        with mock.patch.object(state.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')):
            self.assertEqual(state.windows(), '(unidentified toplevel)')

    def test_missing_wayland_protocol_fails_closed(self):
        with mock.patch.object(state.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='missing protocol')):
            with self.assertRaises(state.Error):
                state.windows()

    def test_restart_descriptors_reject_shells_and_traversal(self):
        cases = [dict(self.app, argv=['/bin/sh', 'launch', '--', '/usr/bin/featherpad']),
                 dict(self.app, argv=['/usr/local/bin/labwc-wayland-app', 'launch', '--', '/bin/sh', '-c', 'id']),
                 dict(self.app, cwd='/home/user/../../root'), dict(self.app, extra='bad'),
                 dict(self.app, argv=['/usr/local/bin/labwc-wayland-app', 'launch', '--', '/usr/bin/featherpad\n'])]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(state.Error):
                state.descriptor(value)
        self.assertEqual(state.descriptor(self.app), self.app)

    def test_restore_handoff_uses_transient_service_and_exact_cwd(self):
        state.atomic(self.state / 'resume.json', {'format': 1, 'apps': [self.app]})
        with mock.patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)):
            state.restore(self.state, self.runtime)
        command = self.run.call_args.args[0]
        self.assertEqual(command[0], '/usr/bin/systemd-run')
        self.assertIn('--property=ExitType=cgroup', command)
        self.assertIn('--property=KillMode=control-group', command)
        self.assertIn('--working-directory=/home/user', command)
        self.assertEqual(command[-len(self.app['argv']):], self.app['argv'])
        self.assertFalse((self.state / 'resume.json').exists())
        self.assertEqual(state.load(self.state / 'last-session.json'), [self.app])

    def test_failed_restore_keeps_retryable_state(self):
        state.atomic(self.state / 'resume.json', {'format': 1, 'apps': [self.app]})
        self.run.side_effect = state.Error('failed exec')
        with mock.patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)):
            state.restore(self.state, self.runtime)
        self.assertEqual(state.load(self.state / 'resume.json'), [self.app])

    def test_state_helper_refuses_root(self):
        with mock.patch.object(state.os, 'getuid', return_value=0), self.assertRaisesRegex(state.Error, 'never root'):
            state.main(['prepare'])


class WiringTests(unittest.TestCase):
    def test_launch_barrier_blocks_existing_file_or_dangling_symlink(self):
        import sys
        modules = str(TARGET / 'usr/local/lib/python3.14/dist-packages')
        with mock.patch.object(sys, 'path', [modules, *sys.path]):
            from labwc_managed_app import recovery
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
                recovery, 'current_user_runtime_dir', return_value=directory):
            marker = Path(directory) / 'labwc-session-closing'
            recovery.assert_launch_allowed()
            marker.touch()
            with self.assertRaises(SystemExit):
                recovery.assert_launch_allowed()
            marker.unlink()
            marker.symlink_to(Path(directory) / 'absent')
            with self.assertRaises(SystemExit):
                recovery.assert_launch_allowed()

    def test_force_is_single_and_only_in_authorized_worker(self):
        text = (TARGET / 'usr/local/libexec/labwc-admin-action-worker').read_text()
        self.assertNotIn('"--force", "--force"', text)
        self.assertNotIn('/sys/power/state",', text)
        for name in ('labwc-power-menu', 'labwc-power-settings', 'labwc-admin-action', 'labwc-logout'):
            self.assertNotIn('systemctl --force', (TARGET / 'usr/local/bin' / name).read_text())

    def test_root_worker_keeps_nnp_with_inherited_command_confinement(self):
        unit = (TARGET / 'etc/systemd/system/labwc-admin-action@.service').read_text()
        self.assertIn('NoNewPrivileges=yes', unit)
        self.assertIn('CapabilityBoundingSet=CAP_KILL', unit)
        profiles = (TARGET / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
        worker = profiles.split('profile managed-labwc-admin-action-worker ', 1)[1].split('\n}', 1)[0]
        self.assertIn('/usr/bin/{systemctl,systemd-run,loginctl,pgrep,pkill} rix,', worker)
        self.assertNotIn('} PUx,', worker)
        self.assertIn('/run/systemd/private rw,', worker)
        self.assertIn('peer=(name=org.freedesktop.login1)', worker)
        repository = profiles.split('profile managed-local-apt-repository ', 1)[1].split('\n}', 1)[0]
        self.assertIn('/usr/local/libexec/local-apt-vendor rix,', repository)
        self.assertIn('/usr/local/libexec/managed-discord-distro rix,', repository)
        self.assertIn('/etc/apt/keyrings/{local-apt-repository.gpg,.local-apt-repository.gpg.*} rw,', repository)
        self.assertIn('local-apt-repository.sources,.local-apt-repository.sources.*', repository)
        self.assertIn('/etc/apt/keyrings/local-apt-repository.gpg{,.tmp.*} rw,', profiles)
        self.assertNotIn('rPx', repository)

    def test_polkit_uses_exact_helpers_and_non_cached_admin_auth(self):
        text = (TARGET / 'etc/polkit-1/rules.d/03-labwc-power.rules').read_text()
        self.assertIn('org.freedesktop.policykit.exec', text)
        self.assertIn('/usr/local/libexec/labwc-admin-action-root', text)
        self.assertIn('/usr/local/libexec/labwc-logout-root', text)
        self.assertIn('polkit.Result.AUTH_ADMIN', text)
        self.assertNotIn('AUTH_ADMIN_KEEP', text)
        self.assertNotIn('command_line', text)

    def test_all_modified_launchers_have_cgroup_exit_and_session_ownership(self):
        module = TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app'
        for path in (module / 'generic.py', module / 'session.py', TARGET / 'usr/local/bin/labwc-qbittorrent'):
            text = path.read_text()
            self.assertIn('ExitType=cgroup', text)
            self.assertIn('KillMode=control-group', text)
            self.assertIn('PartOf=', text)
            self.assertIn('LABWC_SESSION_APP', text)
        self.assertIn('recovery.py', (module / 'integrity.py').read_text())

    def test_restore_service_is_explicitly_staged_and_started_after_session(self):
        unit = TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-session-restore.service'
        self.assertIn('After=labwc-session.target', unit.read_text())
        scripts = TARGET.parents[1] / 'scripts/desktop/components.sh'
        self.assertIn('labwc-session-restore.service', scripts.read_text())
        self.assertIn('labwc-session-restore.service', (TARGET / 'usr/local/bin/labwc-autostart').read_text())


if __name__ == '__main__':
    unittest.main()
