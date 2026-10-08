#!/usr/bin/python3
"""Mocked power/state regressions. Never contact PID 1 or a live compositor."""
import base64
import contextlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'd-i/forky/tests'))
from payload_fixture import read_text as payload_read_text, installed_script as payload_installed_script, python_library as payload_python_library
from theme_fixture import render_theme_defaults
from power_handoff_fixture import handoff_argv, is_handoff
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[2] / 'd-i/forky/hooks/target'


def load_module(name, leaf):
    loader = importlib.machinery.SourceFileLoader(name, str(payload_installed_script(TARGET / 'usr/local/libexec' / leaf)))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    # Exercise installed default values, not unresolved appearance tokens.
    source = render_theme_defaults(Path(loader.path).read_text())
    exec(compile(source, loader.path, "exec"), module.__dict__)
    return module


power = load_module('power_worker_test', 'labwc-admin-action-worker')
state = load_module('session_state_test', 'labwc-session-state')


class PowerWorkerTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.failure = None
        self.active_guest = False
        self.guest_stopped = False
        self.user_stopped = False
        self.managed_stopped = set()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(power, 'run', side_effect=self.mock_run))
        self.stack.enter_context(mock.patch.object(power.Worker, 'user_run', side_effect=self.mock_run))
        self.sync = self.stack.enter_context(mock.patch.object(power.os, 'sync'))
        self.stack.enter_context(mock.patch.object(power, 'ready'))
        self.stack.enter_context(mock.patch.object(power, 'hold_reservation'))
        self.stack.enter_context(mock.patch.object(power, 'PackageLocks'))
        self.stack.enter_context(mock.patch.object(power.Worker, 'session_identity', return_value='a' * 32))
        self.stack.enter_context(mock.patch.object(power, 'sharing_stop_groups', return_value=[]))

    def mock_run(self, argv, **kwargs):
        self.calls.append(argv)
        if self.failure and self.failure(argv):
            raise power.Error('injected failure')
        if argv[-1] == 'ListSessions':
            if self.user_stopped:
                return json.dumps({'type': 'a(susso)', 'data': [[]]})
            return json.dumps({'type': 'a(susso)', 'data': [[
                ['c1', 1000, 'desktop', 'seat0', '/org/freedesktop/login1/session/c1']]]})
        if argv[-1] == 'ListInhibitors':
            return json.dumps({'type': 'a(ssssuu)', 'data': [[]]})
        if '--property=Class' in argv:
            return 'user\n'
        if '--property=ActiveState,SubState,Result,ExecMainStatus' in argv:
            return 'ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus=0\n'
        if '--property=LoadState,ActiveState' in argv:
            if self.active_guest and 'podman-devops-restart.service' in argv:
                return 'LoadState=loaded\nActiveState=active\n'
            return 'LoadState=not-found\nActiveState=inactive\n'
        if '--property=LoadState,ActiveState,SubState,Result' in argv:
            if power.EXTERNAL_DRIVES_UNIT in argv:
                return 'LoadState=loaded\nActiveState=inactive\nSubState=dead\nResult=success\n'
            if argv[2] in self.managed_stopped:
                return 'LoadState=loaded\nActiveState=inactive\nSubState=dead\nResult=success\n'
            return 'LoadState=loaded\nActiveState=active\nSubState=running\nResult=success\n'
        if '--property=LoadState,ActiveState,SubState,Result,ExecMainStatus' in argv:
            self.assertEqual(argv[2], power.EXTERNAL_DRIVES_UNIT)
            return 'LoadState=loaded\nActiveState=inactive\nSubState=dead\nResult=success\nExecMainStatus=0\n'
        if 'stop' in argv and '--no-block' not in argv:
            self.managed_stopped.update(argv[argv.index('stop') + 1:])
        if 'terminate-user' in argv:
            self.user_stopped = True
        if 'stop' in argv and 'podman-devops-restart.service' in argv:
            self.guest_stopped = True
        if '--property=ActiveState,Result' in argv:
            self.assertTrue(self.guest_stopped)
            return 'ActiveState=inactive\nResult=success\n'
        if '--property=ActiveState' in argv:
            return 'inactive\n'
        if is_handoff(argv):
            self.assertEqual(argv, handoff_argv(argv[-1]))
            self.assertEqual(kwargs, {'timeout': 25, 'max_output': 4096})
        return ''

    def execute(self, action):
        worker = power.Worker(1000, 'desktop', action)
        worker.execute()
        return worker

    def test_both_actions_prepare_and_drain_guests_before_single_force(self):
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                self.calls.clear()
                self.active_guest = True
                self.guest_stopped = False
                self.user_stopped = False
                self.managed_stopped.clear()
                self.execute(action)
                prepare = next(i for i, c in enumerate(self.calls)
                               if c[-2:] == ['start', 'labwc-session-state@prepare.service'])
                guests = next(i for i, c in enumerate(self.calls)
                              if 'stop' in c and 'podman-devops-restart.service' in c)
                final = self.calls.index(['/usr/bin/systemctl', '--force', action])
                self.assertLess(prepare, guests)
                self.assertLess(guests, final)
                self.assertEqual(final, len(self.calls) - 1)
                self.assertEqual(sum(is_handoff(c) for c in self.calls), 1)
                self.assertEqual(sum(c.count('--force') for c in self.calls), 1)
                teardown = next(i for i, c in enumerate(self.calls) if 'terminate-user' in c)
                drives = self.calls.index(['/usr/bin/systemctl', '--no-ask-password',
                                          'start', power.EXTERNAL_DRIVES_UNIT])
                zram = next(i for i, c in enumerate(self.calls) if 'stop' in c and 'zram-setup.service' in c)
                fallback = next(i for i, c in enumerate(self.calls) if 'stop' in c and 'swap-fallback.service' in c)
                self.assertLess(guests, teardown)
                self.assertLess(guests, drives)
                self.assertLess(drives, teardown)
                self.assertLess(teardown, zram)
                self.assertLess(zram, fallback)
                self.assertLess(fallback, final)
                drive_calls = [i for i, c in enumerate(self.calls) if c[-2:] ==
                               ['start', power.EXTERNAL_DRIVES_UNIT]]
                self.assertEqual(len(drive_calls), 2)
                self.assertLess(fallback, drive_calls[1])
                self.assertLess(drive_calls[1], final)
                self.assertFalse(any('kill' in c or 'seatd.service' in c
                                     or 'dbus-broker.service' in c for c in self.calls))
                self.assertFalse(any('RebootWithFlags' in c or 'PowerOffWithFlags' in c
                                     for c in self.calls))
        self.assertEqual(self.sync.call_count, 2)

    def test_suspend_locks_without_saving_stopping_clearing_or_signalling_apps(self):
        self.execute('suspend')
        self.assertTrue(any(c[-2:] == ['start', 'labwc-lock.service'] for c in self.calls))
        self.assertTrue(any(c[-2:] == ['start', 'labwc-session-state@locked.service'] for c in self.calls))
        self.assertEqual(self.calls[-1], ['/usr/bin/systemctl', '--check-inhibitors=yes', '--no-ask-password', 'suspend'])
        self.assertFalse(any('stop' in c or 'terminate-user' in c or c[0].endswith('/pkill') or c[-1] == 'labwc-session-state@prepare.service' for c in self.calls))
        self.sync.assert_not_called()

    def test_logout_uses_same_preparation_without_a_machine_power_action(self):
        self.execute('logout')
        self.assertTrue(any(c[-1] == 'labwc-session-state@prepare.service' for c in self.calls))
        self.assertTrue(any('terminate-user' in c for c in self.calls))
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_prepare_failure_never_tears_down_session(self):
        self.failure = lambda command: command[-2:] == ['start', 'labwc-session-state@prepare.service']
        with self.assertRaises(power.Error):
            self.execute('poweroff')
        self.assertFalse(any(('stop' in c and c[-1] != 'labwc-session-state@prepare.service') or '--force' in c or c[0].endswith('/pkill') for c in self.calls))

    def test_failed_guest_stop_never_reaches_forced_power(self):
        self.active_guest = True
        self.failure = lambda command: 'stop' in command and 'podman-devops-restart.service' in command
        with self.assertRaises(power.Error):
            self.execute('reboot')
        self.assertFalse(any('--force' in c or 'terminate-user' in c for c in self.calls))

    def test_external_drive_preparation_failure_keeps_the_seat_and_blocks_force(self):
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                self.calls.clear()
                self.failure = lambda command: command[-2:] == ['start', power.EXTERNAL_DRIVES_UNIT]
                with self.assertRaises(power.Error):
                    self.execute(action)
                self.assertFalse(any('--force' in c or 'terminate-user' in c or
                                     ('stop' in c and 'greetd.service' in c) for c in self.calls))

    def test_late_drive_preparation_failure_still_blocks_force_without_retry(self):
        attempts = 0
        def fail_final_inventory(command):
            nonlocal attempts
            if command[-2:] == ['start', power.EXTERNAL_DRIVES_UNIT]:
                attempts += 1
                return attempts == 2
            return False
        self.failure = fail_final_inventory
        with self.assertRaises(power.Error):
            self.execute('reboot')
        self.assertEqual(attempts, 2)
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_failed_lock_never_suspends(self):
        self.failure = lambda command: command[-1] == 'labwc-session-state@locked.service'
        with self.assertRaises(power.Error):
            self.execute('suspend')
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_other_interactive_account_blocks_machine_action(self):
        with mock.patch.object(power, 'login_sessions', return_value=[('c1', 1000), ('c2', 1001)]), \
             self.assertRaisesRegex(power.Error, 'another interactive'):
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
        self.confirm = mock.patch.object(state, 'confirm_close'); self.confirm.start(); self.addCleanup(self.confirm.stop)
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

    def test_success_records_state_before_clearing_clipboard_without_premature_unit_stops(self):
        initial = {'labwc-editor.service': {'LABWC_SESSION_APP': '1', 'LABWC_SESSION_RESTORE': self.token}}
        with mock.patch.object(state, 'services', side_effect=[initial, {}]), mock.patch.object(state, 'windows', side_effect=['editor: document', '', '']):
            state.prepare(self.state, self.runtime, timeout=0)
        self.assertEqual(state.load(self.state / 'resume.json'), [dict(self.app, argv=self.app['argv'][:4])])
        self.assertEqual((self.state / 'resume.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.runtime / 'labwc-session-closing').exists())
        self.clipboard.assert_called_once()
        self.orphans.assert_not_called()

    def test_tray_process_is_left_for_the_verified_manager_stop_phase(self):
        with mock.patch.object(state, 'services', return_value={'app.service': {'LABWC_SESSION_APP': '1'}}), mock.patch.object(state, 'windows', return_value=''):
            state.prepare(self.state, self.runtime, timeout=0)
        self.clipboard.assert_called_once()
        self.orphans.assert_not_called()
        self.assertTrue((self.runtime / 'labwc-session-closing').exists())

    def test_nested_service_without_windows_is_left_for_manager_quiescence(self):
        with mock.patch.object(state, 'services', return_value={'cage.service': {'LABWC_SESSION_NESTED': '1'}}), mock.patch.object(state, 'windows', return_value=''):
            state.prepare(self.state, self.runtime, timeout=0)
        self.orphans.assert_not_called()
        self.assertFalse(any('kill' in call.args[0] for call in self.run.call_args_list))

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
        modules = str(payload_python_library(TARGET / 'usr/local/lib/python3.14/dist-packages'))
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
        text = payload_read_text(TARGET / 'usr/local/libexec/labwc-admin-action-worker')
        self.assertNotIn('"--force", "--force"', text)
        self.assertNotIn('/sys/power/state",', text)
        for name in ('labwc-power-menu', 'labwc-power-settings', 'labwc-admin-action', 'labwc-logout'):
            self.assertNotIn('systemctl --force', payload_read_text(TARGET / 'usr/local/bin' / name))

    def test_root_worker_keeps_nnp_with_inherited_command_confinement(self):
        unit = payload_read_text(TARGET / 'etc/systemd/system/labwc-admin-action@.service')
        self.assertIn('NoNewPrivileges=yes', unit)
        self.assertIn('CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_KILL CAP_SYS_BOOT\n', unit)
        profiles = payload_read_text(TARGET / 'etc/apparmor.d/desktop-wrappers')
        worker = profiles.split('profile labwc-admin-action-worker ', 1)[1].split('\n}', 1)[0]
        self.assertIn('/usr/bin/{systemctl,systemd-run,loginctl,busctl,sync} rix,', worker)
        self.assertIn('/var/lib/dpkg/{lock,lock-frontend} rk,', worker)
        self.assertNotIn('} PUx,', worker)
        self.assertIn('/run/systemd/private rw,', worker)
        self.assertIn('peer=(name=org.freedesktop.login1)', worker)
        repository = profiles.split('profile apt-repo-local ', 1)[1].split('\n}', 1)[0]
        self.assertIn('/usr/local/libexec/apt-repo-local-vendor rix,', repository)
        self.assertIn('/usr/local/libexec/discord-distro rix,', repository)
        self.assertIn('/etc/apt/keyrings/{apt-repo-local.gpg,.apt-repo-local.gpg.*} rw,', repository)
        self.assertIn('apt-repo-local.sources,.apt-repo-local.sources.*', repository)
        self.assertIn('/etc/apt/keyrings/apt-repo-local.gpg{,.tmp.*} rw,', profiles)
        self.assertNotIn('rPx', repository)

    def test_polkit_uses_exact_helpers_and_non_cached_admin_auth(self):
        text = payload_read_text(TARGET / 'etc/polkit-1/rules.d/03-labwc-power.rules')
        self.assertIn('org.freedesktop.policykit.exec', text)
        self.assertIn('/usr/local/libexec/labwc-admin-action-root', text)
        self.assertIn('/usr/local/libexec/labwc-logout-root', text)
        self.assertIn('polkit.Result.AUTH_ADMIN', text)
        self.assertNotIn('AUTH_ADMIN_KEEP', text)
        self.assertNotIn('command_line', text)

    def test_all_modified_launchers_have_cgroup_exit_and_session_ownership(self):
        module = TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app'
        sys.path.insert(0, str(payload_python_library(module.parent)))
        from labwc_managed_app import generic
        with mock.patch.object(generic, 'assert_launch_allowed'):
            arguments = generic.transient_argv('wayland', 'launch', ['/usr/bin/thunar'], {})
        for property_ in ('ExitType=cgroup', 'KillMode=control-group', 'PartOf=labwc-session.target'):
            self.assertIn('--property=' + property_, arguments)
        self.assertIn('--setenv=LABWC_SESSION_APP', arguments)
        for path in (module / 'session.py', TARGET / 'usr/local/bin/labwc-qbittorrent'):
            text = payload_read_text(path)
            self.assertIn('ExitType=cgroup', text)
            self.assertTrue('KillMode=control-group' in text or 'KillMode=" + ("mixed" if is_foot else "control-group")' in text)
            self.assertIn('PartOf=', text)
            self.assertIn('LABWC_SESSION_APP', text)
        self.assertIn('recovery.py', payload_read_text(module / 'integrity.py'))

    def test_restore_service_is_explicitly_staged_and_started_after_session(self):
        unit = TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-session-restore.service'
        self.assertIn('After=labwc-session.target', payload_read_text(unit))
        scripts = TARGET.parents[1] / 'scripts/desktop/components.sh'
        self.assertIn('labwc-session-restore.service', payload_read_text(scripts))
        self.assertIn('labwc-session-restore.service', payload_read_text(TARGET / 'usr/local/bin/labwc-autostart'))


if __name__ == '__main__':
    unittest.main()
