"""Power finalization regressions: all host commands are mocked, never executed."""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from power_handoff_fixture import handoff_argv, is_handoff
from payload_fixture import read_text as payload_read_text
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import sys
import types
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
WORKER = TARGET / 'usr/local/libexec/labwc-admin-action-worker'


def module():
    result = types.ModuleType('runtime_power_test')
    exec(compile(payload_read_text(WORKER), str(WORKER), 'exec'), result.__dict__)
    if hasattr(result, 'Worker'):
        result.os = types.SimpleNamespace(**{**vars(result.os), 'sync': mock.Mock()})
    return result


class ShutdownGateRemovalTests(unittest.TestCase):
    def test_inhibitor_probe_is_not_an_authorized_shutdown_gate(self):
        self.assertFalse(hasattr(module(), 'check_shutdown_inhibitors'))



class DirectHandoffTests(unittest.TestCase):
    """One authorized single-force handoff without cleanup vetoes."""
    def setUp(self):
        self.power = module()
        self.worker = self.power.Worker(1000, 'desktop', 'poweroff')
        self.worker.prepared = True
        self.worker.prepare_external_drives = mock.Mock()
        self.worker.package_locks = mock.Mock()
        self.events = []
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.stack.enter_context(mock.patch.object(self.power, 'run', side_effect=self.command))
        self.stack.enter_context(mock.patch.object(self.worker, 'protect_other_sessions',
                                                   side_effect=lambda: self.events.append('accounts')))

    def command(self, argv, **kwargs):
        self.events.append(argv)
        if argv[-1] == 'ListInhibitors':
            return json.dumps({'type': 'a(ssssuu)', 'data': [[]]})
        self.assertEqual(argv, handoff_argv(self.worker.action))
        self.assertEqual(kwargs, {'timeout': 25, 'max_output': 4096})
        return ''

    def test_desktop_and_greeter_both_submit_one_single_force_handoff(self):
        for action in ('poweroff', 'reboot'):
            for greeter in (False, True):
                with self.subTest(action=action, greeter=greeter):
                    self.events.clear()
                    self.worker.action = action
                    self.worker.greeter = greeter
                    self.worker.prepared = not greeter
                    self.worker.handoff_attempted = False
                    self.worker.final_power_action()
                    self.assertEqual(self.events[-1], handoff_argv(action))
                    commands = [e for e in self.events if isinstance(e, list)]
                    self.assertEqual(sum(is_handoff(c) for c in commands), 1)
                    self.assertFalse(any('stop' in c for c in commands))
                    self.assertEqual(sum(c.count('--force') for c in commands), 1)
                    self.assertTrue(self.worker.committed and self.worker.handoff_attempted)
                    self.worker.package_locks.verify.assert_not_called()

    def test_other_account_checks_are_not_a_second_shutdown_authorization_gate(self):
        with mock.patch.object(self.worker, 'protect_other_sessions', side_effect=self.power.Error('unavailable session list')) as accounts:
            self.worker.final_power_action()
        accounts.assert_not_called()
        self.assertEqual(self.events, [handoff_argv('poweroff')])

    def test_missing_package_reservation_and_unprepared_desktop_do_not_veto(self):
        self.worker.package_locks = None
        self.worker.prepared = False
        self.worker.final_power_action()
        self.assertEqual(self.events, [handoff_argv('poweroff')])

    def test_failed_status_notification_does_not_veto_submission(self):
        with mock.patch.object(self.power, 'status', side_effect=OSError('notification unavailable')):
            self.worker.final_power_action()
        self.assertEqual(self.events, [handoff_argv('poweroff')])
        self.assertTrue(self.worker.handoff_attempted)

    def test_uncertain_submission_never_retries_or_stops_root_services(self):
        def failed(argv, **kwargs):
            if is_handoff(argv):
                self.events.append(argv)
                raise self.power.Error('lost reply')
            return self.command(argv, **kwargs)
        with mock.patch.object(self.power, 'run', side_effect=failed):
            with self.assertRaisesRegex(self.power.Error, 'uncertain'):
                self.worker.final_power_action()
            with self.assertRaisesRegex(self.power.Error, 'only once'):
                self.worker.final_power_action()
        commands = [e for e in self.events if isinstance(e, list)]
        self.assertEqual(sum(is_handoff(c) for c in commands), 1)
        self.assertFalse(any('stop' in c or 'start' in c for c in commands))
        self.assertEqual(sum(c.count('--force') for c in commands), 1)


class BoundedTransportTests(unittest.TestCase):
    """Only private Python child processes; no systemd or host services."""
    def setUp(self): self.power=module()

    def test_both_pipes_are_drained_and_success_is_decoded(self):
        output=self.power.run([sys.executable,'-c',
            'import sys;sys.stderr.write("diagnostic");print("answer")'],max_output=100,timeout=3)
        self.assertEqual(output,'answer\n')

    def test_stdout_overflow_reaps_its_child(self):
        with self.assertRaisesRegex(self.power.Error,'size limit'):
            self.power.run([sys.executable,'-c',
                'import sys,time;sys.stdout.write("x"*100000);sys.stdout.flush();time.sleep(30)'],
                max_output=1024,timeout=3)

    def test_stderr_overflow_is_also_bounded(self):
        with self.assertRaisesRegex(self.power.Error,'size limit'):
            self.power.run([sys.executable,'-c',
                'import sys,time;sys.stderr.write("x"*100000);sys.stderr.flush();time.sleep(30)'],
                max_output=1024,timeout=3)

    def test_inherited_pipe_child_is_bounded_by_deadline(self):
        start=time.monotonic()
        with self.assertRaisesRegex(self.power.Error,'timed out'):
            self.power.run([sys.executable,'-c','import os,time;os.fork();time.sleep(30)'],
                           max_output=1024,timeout=0.2)
        self.assertLess(time.monotonic()-start,4)

    def test_nonzero_result_remains_an_error(self):
        with self.assertRaisesRegex(self.power.Error,'exited 3'):
            self.power.run([sys.executable,'-c','raise SystemExit(3)'],max_output=1024,timeout=3)


class OtherSessionTests(unittest.TestCase):
    """Scoped sudo repair must not exempt real root or other-user logins."""
    def setUp(self):
        self.power = module()

    def check(self, uid, session_class):
        power = self.power
        worker = power.Worker(1000, 'desktop', 'reboot')
        with mock.patch.object(power, 'login_sessions', return_value=[('c1', 1000), ('c2', uid)]), \
             mock.patch.object(power, 'run', return_value=session_class + '\n') as run:
            try:
                worker.protect_other_sessions()
            finally:
                run.assert_called_once_with(['/usr/bin/loginctl', 'show-session', 'c2',
                    '--property=Class', '--value'], timeout=5, max_output=256)

    def test_real_root_and_other_interactive_accounts_still_veto(self):
        for uid in (0, 1001):
            for session_class in ('user', 'user-early', 'user-early-light', 'user-incomplete', 'lock-screen'):
                with self.subTest(uid=uid, session_class=session_class), \
                     self.assertRaisesRegex(self.power.Error, f'another interactive.*uid={uid}, session=c2'):
                    self.check(uid, session_class)

    def test_background_and_manager_sessions_do_not_veto(self):
        for uid in (0, 999):
            for session_class in ('background', 'background-light', 'manager', 'manager-early'):
                with self.subTest(uid=uid, session_class=session_class):
                    self.check(uid, session_class)

    def test_unknown_other_session_classes_fail_closed(self):
        for session_class in ('', 'future-session-class'):
            with self.subTest(session_class=session_class), \
                 self.assertRaisesRegex(self.power.Error, 'class is unknown'):
                self.check(1001, session_class)


class HardeningTests(unittest.TestCase):
    def test_broker_free_transport_and_pid1_only_boot_capability(self):
        power=module()
        self.assertEqual(power.ENV['SYSTEMCTL_FORCE_BUS'],'0')
        self.assertFalse(any(key.startswith('DBUS_') for key in power.ENV))
        unit=payload_read_text(TARGET/'etc/systemd/system/labwc-admin-action@.service')
        self.assertIn('\nCapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_KILL CAP_SYS_BOOT\n',unit)
        self.assertIn('\nAmbientCapabilities=\n',unit)
        self.assertIn('NoNewPrivileges=yes',unit)
        self.assertIn('ProtectControlGroups=yes',unit)
        self.assertIn('Before=apt-daily.service apt-daily-upgrade.service unattended-upgrades.service packagekit.service', unit)
        source=payload_read_text(WORKER)
        self.assertNotIn('/usr/bin/pkill',source);self.assertNotIn('/usr/bin/pgrep',source)
        profile=payload_read_text(TARGET/'etc/apparmor.d/desktop-wrappers').split('profile labwc-admin-action-worker ',1)[1].split('\n}',1)[0]
        self.assertIn('capability kill,',profile)
        self.assertNotIn('capability sys_admin',profile)
        self.assertIn('set=(kill chld) peer=labwc-admin-action-worker',profile)
        self.assertNotIn('cgroup.events r,',profile)
        self.assertNotIn('cgroup.kill',profile)
        self.assertNotIn('stop_shutdown_runtime',source)


if __name__=='__main__': unittest.main()
