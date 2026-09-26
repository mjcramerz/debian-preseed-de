"""Power finalization regressions: all host commands are mocked, never executed."""
from __future__ import annotations
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
    return result


class InhibitorsTests(unittest.TestCase):
    def setUp(self):
        self.power = module()

    def check(self, records):
        raw = json.dumps({'type': 'a(ssssuu)', 'data': [records]})
        with mock.patch.object(self.power, 'run', return_value=raw) as run:
            self.power.check_shutdown_inhibitors()
        command = run.call_args.args[0]
        self.assertEqual(command[0], '/usr/bin/busctl')
        self.assertEqual(command[-1], 'ListInhibitors')
        self.assertIn('--timeout=5s', command)

    def test_empty_list_permits_shutdown(self):
        self.check([])

    def test_block_and_weak_and_unknown_shutdown_modes_veto(self):
        for mode in ('block', 'block-weak', 'future-mode', ''):
            with self.subTest(mode=mode), self.assertRaisesRegex(self.power.Error, 'inhibited'):
                self.check([['shutdown:sleep', 'application', 'unsaved', mode, 1000, 123]])

    def test_delay_is_not_misrepresented_as_blocking(self):
        self.check([['shutdown', 'application', 'flush', 'delay', 1000, 123]])
        self.assertIn('not logind', self.power.check_shutdown_inhibitors.__doc__)

    def test_unrelated_inhibitors_are_not_shutdown_vetoes(self):
        self.check([['sleep:idle', 'player', 'playing', 'block', 1000, 123]])

    def test_invalid_json_signatures_and_record_types_fail_closed(self):
        invalid = ['{', 'null', '[]', '{"type":"s","data":[[]]}',
                   '{"type":"a(ssssuu)","data":[]}',
                   '{"type":"a(ssssuu)","data":[{}]}']
        records = [['shutdown', 'a', 'b', 'block', True, 1],
                   ['shutdown', 'a', 'b', 'delay', -1, 1],
                   ['shutdown', 'a', 'b', 'delay', 1, 2**32],
                   ['shutdown', 'a', 'b', 'delay', 1],
                   ['shutdown', ['a'], 'b', 'delay', 1, 1]]
        invalid += [json.dumps({'type': 'a(ssssuu)', 'data': [[record]]}) for record in records]
        for raw in invalid:
            with self.subTest(raw=raw), mock.patch.object(self.power, 'run', return_value=raw), \
                 self.assertRaisesRegex(self.power.Error, 'cannot verify'):
                self.power.check_shutdown_inhibitors()

    def test_bounded_response_records_and_strings(self):
        invalid = [' ' * 1_048_577,
                   json.dumps({'type':'a(ssssuu)', 'data':[[[]]*1025]}),
                   json.dumps({'type':'a(ssssuu)', 'data':[[['sleep', 'a'*4097, '', 'delay', 0, 1]]]})]
        for raw in invalid:
            with mock.patch.object(self.power, 'run', return_value=raw), self.assertRaises(self.power.Error):
                self.power.check_shutdown_inhibitors()

    def test_unavailable_bus_never_silently_authorizes(self):
        with mock.patch.object(self.power, 'run', side_effect=self.power.Error('timeout')), \
             self.assertRaisesRegex(self.power.Error, 'timeout'):
            self.power.check_shutdown_inhibitors()



class DirectHandoffTests(unittest.TestCase):
    """The committed desktop and greeter requests skip system-wide unit stops."""

    def setUp(self):
        self.power = module()
        self.worker = self.power.Worker(1000, 'desktop', 'poweroff')
        self.worker.quiesced = True
        self.worker.package_locks = mock.Mock()
        self.events = []
        self.sink = contextlib.redirect_stderr(io.StringIO())
        self.sink.__enter__()
        self.addCleanup(self.sink.__exit__, None, None, None)
        self.transport = mock.patch.object(self.power, 'run', side_effect=self.command)
        self.transport.start()
        self.addCleanup(self.transport.stop)
        self.sessions = mock.patch.object(self.worker, 'protect_other_sessions',
                                          side_effect=lambda: self.events.append('accounts'))
        self.sessions.start()
        self.addCleanup(self.sessions.stop)

    def command(self, argv, **kwargs):
        self.events.append(argv)
        if argv[0] == '/usr/bin/busctl':
            return json.dumps({'type': 'a(ssssuu)', 'data': [[]]})
        if argv == ['/usr/bin/systemctl', '--force', '--no-ask-password', self.worker.action]:
            return ''
        raise AssertionError('unexpected system command: ' + repr(argv))

    def test_desktop_and_greeter_both_submit_one_force_after_preflight(self):
        for action in ('poweroff', 'reboot'):
            for greeter in (False, True):
                with self.subTest(action=action, greeter=greeter):
                    self.events.clear()
                    self.worker.action = action
                    self.worker.greeter = greeter
                    self.worker.quiesced = not greeter
                    self.worker.handoff_attempted = False
                    self.worker.final_power_action()
                    self.assertEqual([event if isinstance(event, str) else event[0]
                                      for event in self.events],
                                     ['accounts', '/usr/bin/busctl', '/usr/bin/systemctl'])
                    self.assertEqual(self.events[-1],
                                     ['/usr/bin/systemctl', '--force', '--no-ask-password', action])
                    self.assertEqual(sum('--force' in c for c in self.events if isinstance(c, list)), 1)
                    self.assertTrue(self.worker.committed and self.worker.handoff_attempted)
                    self.assertGreaterEqual(self.worker.package_locks.verify.call_count, 2)

    def test_other_account_or_blocking_inhibitor_vetoes_before_force(self):
        with mock.patch.object(self.worker, 'protect_other_sessions', side_effect=self.power.Error('other account')):
            with self.assertRaisesRegex(self.power.Error, 'other account'):
                self.worker.final_power_action()
        self.assertFalse(self.events)
        self.assertFalse(self.worker.handoff_attempted)
        def blocked(argv, **kwargs):
            self.events.append(argv)
            return json.dumps({'type': 'a(ssssuu)',
                               'data': [[['shutdown', 'editor', 'unsaved', 'block', 1000, 1]]]})
        with mock.patch.object(self.power, 'run', side_effect=blocked), \
             self.assertRaisesRegex(self.power.Error, 'inhibited'):
            self.worker.final_power_action()
        self.assertFalse(any('--force' in c for c in self.events))
        self.assertFalse(self.worker.handoff_attempted)

    def test_missing_reservation_or_unprepared_session_fails_without_commands(self):
        self.worker.package_locks = None
        with self.assertRaisesRegex(self.power.Error, 'reservation'):
            self.worker.final_power_action()
        self.worker.package_locks = mock.Mock()
        self.worker.quiesced = False
        with self.assertRaisesRegex(self.power.Error, 'quiesced'):
            self.worker.final_power_action()
        self.assertFalse(self.events)

    def test_reservation_loss_after_announcement_never_submits_force(self):
        import builtins
        original = builtins.print
        def lose_lock(*args, **kwargs):
            result = original(*args, **kwargs)
            if args and str(args[0]).startswith('power handoff:'):
                self.worker.package_locks.verify.side_effect = self.power.Error('reservation lost')
            return result
        with mock.patch('builtins.print', side_effect=lose_lock), \
             self.assertRaisesRegex(self.power.Error, 'reservation lost'):
            self.worker.final_power_action()
        self.assertFalse(any('--force' in c for c in self.events if isinstance(c, list)))
        self.assertTrue(self.worker.handoff_attempted)
        with self.assertRaisesRegex(self.power.Error, 'only once'):
            self.worker.final_power_action()

    def test_uncertain_submission_never_retries_or_stops_root_services(self):
        def failed(argv, **kwargs):
            self.events.append(argv)
            if '--force' in argv:
                raise self.power.Error('lost reply')
            return json.dumps({'type': 'a(ssssuu)', 'data': [[]]})
        with mock.patch.object(self.power, 'run', side_effect=failed):
            with self.assertRaisesRegex(self.power.Error, 'uncertain'):
                self.worker.final_power_action()
            with self.assertRaisesRegex(self.power.Error, 'only once'):
                self.worker.final_power_action()
        commands = [entry for entry in self.events if isinstance(entry, list)]
        self.assertEqual(sum('--force' in c for c in commands), 1)
        self.assertFalse(any('stop' in c or 'start' in c for c in commands))


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


class HardeningTests(unittest.TestCase):
    def test_broker_free_transport_and_no_privilege_expansion(self):
        power=module()
        self.assertEqual(power.ENV['SYSTEMCTL_FORCE_BUS'],'0')
        self.assertFalse(any(key.startswith('DBUS_') for key in power.ENV))
        unit=payload_read_text(TARGET/'etc/systemd/system/labwc-admin-action@.service')
        self.assertIn('\nCapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_KILL\n',unit)
        self.assertIn('\nAmbientCapabilities=\n',unit)
        self.assertIn('NoNewPrivileges=yes',unit)
        self.assertIn('ProtectControlGroups=yes',unit)
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
