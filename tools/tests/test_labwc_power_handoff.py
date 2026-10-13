#!/usr/bin/python3
"""Mocked power/state regressions. Never contact PID 1 or a live compositor."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[2] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

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

    def test_both_actions_close_and_attempt_cleanup_before_single_force(self):
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                self.calls.clear()
                self.execute(action)
                self.assertEqual(self.calls[-1], handoff_argv(action))
                self.assertEqual(sum(is_handoff(c) for c in self.calls), 1)
                close = next(i for i, c in enumerate(self.calls) if c[-2:] == ['start', 'labwc-session-state@close.service'])
                save = next(i for i, c in enumerate(self.calls) if c[-2:] == ['start', f'labwc-session-state@{action}.service'])
                guests = next(i for i, c in enumerate(self.calls) if 'stop' in c and 'podman-devops-restart.service' in c)
                drives = next(i for i, c in enumerate(self.calls) if c[-2:] == ['start', power.EXTERNAL_DRIVES_UNIT])
                terminate = next(i for i, c in enumerate(self.calls) if 'terminate-user' in c)
                self.assertLess(save, close)
                self.assertLess(close, guests)
                self.assertLess(guests, drives)
                self.assertLess(drives, terminate)
                self.assertEqual(sum(c[-2:] == ['start', power.EXTERNAL_DRIVES_UNIT] for c in self.calls), 1)
                self.assertNotIn(['/usr/bin/busctl', 'ListInhibitors'], self.calls)
                self.assertFalse(any(c[-1] == 'labwc-session-state@prepare.service' for c in self.calls))
                self.assertIn(['/usr/bin/sync'], self.calls)

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

    def test_prepare_failure_does_not_veto_power(self):
        self.failure = lambda command: command[-2:] == ['start', 'labwc-session-state@close.service']
        with contextlib.redirect_stderr(io.StringIO()):
            self.execute('poweroff')
        self.assertEqual(self.calls[-1], handoff_argv('poweroff'))
        self.assertEqual(sum(is_handoff(c) for c in self.calls), 1)

    def test_failed_save_helper_allows_grace_then_still_submits_power(self):
        self.failure = lambda command: command[-2:] == ['start', 'labwc-session-state@poweroff.service']
        with (mock.patch.object(power.time, 'monotonic', return_value=100),
              mock.patch.object(power.time, 'sleep') as sleep,
              contextlib.redirect_stderr(io.StringIO())):
            self.execute('poweroff')
        sleep.assert_called_once_with(15)
        self.assertEqual(self.calls[-1], handoff_argv('poweroff'))
        self.assertEqual(sum(is_handoff(c) for c in self.calls), 1)

    def test_failed_guest_stop_does_not_veto_power(self):
        self.failure = lambda command: 'stop' in command and 'podman-devops-restart.service' in command
        with contextlib.redirect_stderr(io.StringIO()):
            self.execute('poweroff')
        self.assertEqual(self.calls[-1], handoff_argv('poweroff'))
        self.assertEqual(sum(is_handoff(c) for c in self.calls), 1)

    def test_external_drive_preparation_failure_does_not_veto_power(self):
        self.failure = lambda command: command[-2:] == ['start', power.EXTERNAL_DRIVES_UNIT]
        with contextlib.redirect_stderr(io.StringIO()):
            self.execute('poweroff')
        self.assertEqual(self.calls[-1], handoff_argv('poweroff'))
        self.assertEqual(sum(is_handoff(c) for c in self.calls), 1)

    def test_external_drive_cleanup_is_not_repeated_as_a_second_gate(self):
        self.execute('reboot')
        self.assertEqual(sum(c[-2:] == ['start', power.EXTERNAL_DRIVES_UNIT] for c in self.calls), 1)
        self.assertEqual(sum(is_handoff(c) for c in self.calls), 1)

    def test_failed_lock_never_suspends(self):
        self.failure = lambda command: command[-1] == 'labwc-session-state@locked.service'
        with self.assertRaises(power.Error):
            self.execute('suspend')
        self.assertFalse(any('--force' in c for c in self.calls))

    def test_advisory_account_inventory_is_not_a_shutdown_gate(self):
        with mock.patch.object(power, 'login_sessions', side_effect=power.Error('logind unavailable')) as sessions:
            self.execute('poweroff')
        sessions.assert_not_called()
        self.assertEqual(self.calls[-1], handoff_argv('poweroff'))

    def test_invalid_instance_never_executes_a_command(self):
        with mock.patch.object(power.os, 'geteuid', return_value=0):
            for value in ('0-poweroff', '01000-reboot', '1000-poweroff;id', '1000-hibernate', '../reboot', '1000-reboot-extra'):
                with self.subTest(value=value), self.assertRaises(power.Error):
                    power.main([value])
        self.assertEqual(self.calls, [])


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        self.session = state
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.ctl = self.stack.enter_context(mock.patch.object(self.session, 'ctl', return_value=''))
        self.run = self.stack.enter_context(mock.patch.object(self.session, 'run', return_value=''))
        self.windows = self.stack.enter_context(mock.patch.object(self.session, 'windows', return_value=''))
        self.notify = self.stack.enter_context(mock.patch.object(self.session, 'notify'))
        self.sleep = self.stack.enter_context(mock.patch.object(self.session.time, 'sleep'))
        self.clipboard = self.stack.enter_context(mock.patch.object(self.session, 'clear_clipboard'))
        self.now = 0.0
        self.stack.enter_context(mock.patch.object(self.session.time, 'monotonic', side_effect=lambda: self.now))
        self.sleep.side_effect = self.advance

    def advance(self, seconds):
        self.now += seconds

    def test_open_editors_browsers_and_terminals_get_one_bounded_save_window(self):
        for action in ('poweroff', 'reboot'):
            with self.subTest(action=action):
                self.now = 0.0
                self.windows.return_value = ('foot: micro\nfeatherpad: document\nfocuswriter: document\n'
                                             'gnumeric: workbook\nvivaldi: page\nmsedge: page\nchromium: page')
                self.notify.reset_mock()
                self.sleep.reset_mock()
                self.session.wait_power(action)
                self.assertEqual(self.now, 15)
                self.notify.assert_called_once()
                self.assertIn('in 15 seconds', self.notify.call_args.args[0])
                self.assertIn('Save your work now', self.notify.call_args.args[0])
                self.assertEqual(self.notify.call_args.kwargs, {'timeout': 1})
                self.assertTrue(all(0 < call.args[0] <= 0.2 for call in self.sleep.call_args_list))
                self.assertTrue(all(0 < call.kwargs['timeout'] <= 1
                                    for call in self.windows.call_args_list if call.kwargs))
        self.run.assert_not_called()
        self.ctl.assert_not_called()
        self.clipboard.assert_not_called()
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_no_visible_windows_means_no_save_warning_or_delay(self):
        self.session.wait_power('poweroff')
        self.windows.assert_called_once_with()
        self.notify.assert_not_called()
        self.sleep.assert_not_called()
        self.run.assert_not_called()

    def test_all_windows_closed_during_grace_proceeds_early(self):
        self.windows.side_effect = ['featherpad: document', 'featherpad: document', '']
        self.session.wait_power('reboot')
        self.assertEqual(self.now, 0.2)
        self.notify.assert_called_once()
        self.run.assert_not_called()

    def test_failed_window_inventory_is_bounded_and_never_vetoes_power(self):
        self.windows.side_effect = self.session.Error('Wayland unavailable')
        with contextlib.redirect_stderr(io.StringIO()):
            self.session.wait_power('poweroff')
        self.assertEqual(self.now, 15)
        self.notify.assert_called_once()
        self.run.assert_not_called()

    def test_power_close_sends_one_request_without_window_or_service_gates(self):
        self.windows.side_effect = AssertionError('power close must not inspect windows')
        self.session.close(self.runtime)
        self.run.assert_called_once_with(['/usr/bin/wlrctl', 'toplevel', 'close'], timeout=5, accepted=(0, 1))
        self.ctl.assert_not_called()
        self.sleep.assert_not_called()
        self.notify.assert_not_called()
        self.assertTrue((self.runtime / 'labwc-session-closing').is_file())

    def test_logout_only_waits_for_actual_windows_without_generic_save_warning(self):
        self.windows.side_effect = ['browser: page', 'editor: Save changes?', '']
        self.session.prepare(self.runtime)
        self.assertEqual(self.sleep.call_args_list, [mock.call(0.2), mock.call(0.2)])
        self.run.assert_called_once()
        self.notify.assert_not_called()
        self.clipboard.assert_called_once()
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['runtime'])

    def test_windowless_background_apps_cannot_block_logout(self):
        self.session.prepare(self.runtime, timeout=0)
        self.sleep.assert_not_called()
        self.notify.assert_not_called()
        self.assertFalse(hasattr(self.session, 'protected_still_running'))
        self.assertFalse(hasattr(self.session, 'services'))

    def test_remaining_window_cancels_logout_and_removes_marker(self):
        self.windows.return_value = 'editor: Save changes?'
        with self.assertRaises(self.session.Cancelled):
            self.session.prepare(self.runtime, timeout=0)
        self.assertFalse((self.runtime / 'labwc-session-closing').exists())
        self.clipboard.assert_not_called()

    def test_failed_window_probe_cancels_logout_without_stranding_marker(self):
        self.windows.side_effect = self.session.Error('Wayland unavailable')
        with self.assertRaises(self.session.Error):
            self.session.prepare(self.runtime)
        self.assertFalse((self.runtime / 'labwc-session-closing').exists())

    def test_clipboard_failure_does_not_block_closed_logout(self):
        self.clipboard.side_effect = self.session.Error('clipboard unavailable')
        with contextlib.redirect_stderr(io.StringIO()):
            self.session.prepare(self.runtime)
        self.assertTrue((self.runtime / 'labwc-session-closing').exists())

    def test_restore_and_persistent_capture_are_absent(self):
        for name in ('restore', 'collect', 'descriptor', 'load', 'atomic', 'confirm_close'):
            self.assertFalse(hasattr(self.session, name))
        with (
            mock.patch.object(self.session.os, 'getuid', return_value=1000),
            mock.patch.object(self.session.os, 'geteuid', return_value=1000),
            self.assertRaises(self.session.Error),
        ):
            self.session.main(['restore'])

    def test_session_helper_refuses_root(self):
        with mock.patch.object(self.session.os, 'getuid', return_value=0), self.assertRaisesRegex(self.session.Error, 'never root'):
            self.session.main(['close'])


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
        for property_ in ('ExitType=main', 'KillMode=control-group', 'PartOf=labwc-session.target'):
            self.assertIn('--property=' + property_, arguments)
        self.assertIn('--setenv=LABWC_SESSION_APP', arguments)
        for path in (module / 'session.py', TARGET / 'usr/local/bin/labwc-qbittorrent'):
            text = payload_read_text(path)
            self.assertIn('ExitType=main', text)
            self.assertTrue('KillMode=control-group' in text or 'KillMode=" + ("mixed" if is_foot else "control-group")' in text)
            self.assertIn('PartOf=', text)
            self.assertIn('LABWC_SESSION_APP', text)
        self.assertIn('recovery.py', payload_read_text(module / 'integrity.py'))

    def test_restore_service_has_no_payload_staging_or_autostart_reference(self):
        unit = TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-session-restore.service'
        self.assertFalse(unit.exists())
        scripts = TARGET.parents[1] / 'scripts/desktop/components.sh'
        self.assertNotIn('labwc-session-restore.service', payload_read_text(scripts))
        self.assertNotIn('labwc-session-restore.service', payload_read_text(TARGET / 'usr/local/bin/labwc-autostart'))


if __name__ == '__main__':
    unittest.main()
