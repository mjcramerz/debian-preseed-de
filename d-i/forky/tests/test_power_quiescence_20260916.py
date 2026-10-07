"""Power lifecycle regressions. All manager/power calls are mocked."""
from __future__ import annotations
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
import contextlib
import io
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
BARRIERS = {'shutdown.target', 'umount.target', 'final.target', 'reboot.target', 'poweroff.target'}


def module():
    path = TARGET / 'usr/local/libexec/labwc-admin-action-worker'
    result = types.ModuleType('quiescence_worker'); result.__file__ = str(path)
    exec(compile(payload_read_bytes(path), str(path), 'exec'), result.__dict__)
    if hasattr(result, 'Worker'):
        result.os = types.SimpleNamespace(**{**vars(result.os), 'sync': mock.Mock()})
    return result


class OrderlyLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.power = module()
        self.worker = self.power.Worker(1000, 'desktop', 'reboot')
        self.events = []
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.stack.enter_context(mock.patch.object(self.power, 'ready'))
        self.stack.enter_context(mock.patch.object(self.power, 'PackageLocks'))
        self.stack.enter_context(mock.patch.object(self.power, 'hold_reservation',
                                                   side_effect=lambda: self.events.append('hold')))
        self.stack.enter_context(mock.patch.object(self.power, 'run',
                                                   side_effect=AssertionError('unmocked host command')))
        self.stack.enter_context(mock.patch.object(self.power, 'check_shutdown_inhibitors',
                                                   side_effect=lambda: self.events.append('inhibitors')))
        self.stack.enter_context(mock.patch.object(self.worker, 'session_identity', return_value='a'*32))
        for name in ('protect_other_sessions', 'helper', 'stop_optional_guests'):
            self.stack.enter_context(mock.patch.object(self.worker, name,
                side_effect=lambda *args, method=name: self.events.append((method, args))))
        self.stack.enter_context(mock.patch.object(self.worker, 'userctl',
                                                   side_effect=AssertionError('premature user teardown')))
        self.final = self.stack.enter_context(mock.patch.object(self.worker, 'final_power_action',
                                               side_effect=self.handoff))

    def handoff(self):
        self.assertTrue(self.worker.prepared)
        self.assertFalse(self.worker.committed)
        self.assertIsNotNone(self.worker.package_locks)
        self.events.append('handoff')

    def test_prepared_desktop_is_not_stopped_before_native_handoff(self):
        self.worker.execute()
        self.assertEqual(self.events[-2:], ['handoff', 'hold'])
        self.assertLess(self.events.index(('helper', ('prepare',))), self.events.index('handoff'))
        self.assertLess(self.events.index(('stop_optional_guests', ())), self.events.index('handoff'))
        self.worker.userctl.assert_not_called()
        self.power.run.assert_not_called()

    def test_session_replacement_during_preparation_never_hands_off(self):
        self.worker.session_identity.side_effect = ['a'*32, 'a'*32, 'b'*32]
        with self.assertRaisesRegex(self.power.Error, 'session changed'):
            self.worker.execute()
        self.final.assert_not_called()
        self.assertFalse(self.worker.committed)

    def test_prepare_cancel_never_stops_guests_or_desktop(self):
        self.worker.helper.side_effect = self.power.Cancelled('documents not saved')
        with self.assertRaises(self.power.Cancelled):
            self.worker.execute()
        self.assertFalse(self.worker.prepared)
        self.worker.stop_optional_guests.assert_not_called()
        self.final.assert_not_called()
        self.worker.userctl.assert_not_called()

    def test_guest_stop_failure_leaves_compositor_available(self):
        self.worker.stop_optional_guests.side_effect = self.power.Error('guest stop timed out')
        with self.assertRaises(self.power.Error):
            self.worker.execute()
        self.final.assert_not_called()
        self.worker.userctl.assert_not_called()
        self.assertFalse(self.worker.committed)

    def test_handoff_environment_cannot_redirect_bus_or_select_soft_reboot(self):
        self.assertFalse({'DBUS_SYSTEM_BUS_ADDRESS', 'DBUS_SESSION_BUS_ADDRESS'} & self.power.ENV.keys())
        source = payload_read_text(TARGET/'usr/local/libexec/labwc-admin-action-worker')
        self.assertNotIn('"--force"', source)
        self.assertNotIn('self.quiesce_desktop()', source)
        self.assertIn('"--allow-interactive-authorization=no"', source)
        self.assertIn('"org.freedesktop.login1.Manager", method, "t", "1"', source)

    def test_successfully_drained_transport_is_not_killed(self):
        original = module()
        with mock.patch.object(original.os, 'killpg') as kill:
            self.assertEqual(original.run([sys.executable, '-c', 'print("ok")']), 'ok\n')
        kill.assert_not_called()


class GuestHookTests(unittest.TestCase):
    def setUp(self):
        self.power = module(); self.worker = self.power.Worker(1000, 'desktop', 'poweroff')
        self.worker.package_locks = mock.Mock()

    def test_optional_missing_and_inactive_hooks_do_not_start_or_stop_anything(self):
        with mock.patch.object(self.power, 'run', side_effect=[
                'LoadState=not-found\nActiveState=inactive\n', 'LoadState=loaded\nActiveState=inactive\n']) as run:
            self.worker.stop_optional_guests()
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all('show' in c.args[0] for c in run.call_args_list))

    def test_running_hooks_stop_together_then_each_result_is_checked(self):
        with mock.patch.object(self.power, 'run', side_effect=[
                'LoadState=loaded\nActiveState=active\n', 'LoadState=loaded\nActiveState=active\n', '',
                'ActiveState=inactive\nResult=success\n', 'ActiveState=inactive\nResult=success\n']) as run:
            self.worker.stop_optional_guests()
        commands = [c.args[0] for c in run.call_args_list]
        self.assertEqual(commands[2], ['/usr/bin/systemctl', '--no-ask-password', 'stop',
                                      'podman-devops-restart.service', 'incus-startup.service'])
        self.assertEqual(run.call_args_list[2].kwargs['timeout'], 180)
        self.assertFalse(any(set(c) & BARRIERS or '--no-block' in c for c in commands))
        self.assertFalse(any(any('dbus' in word for word in c) for c in commands))

    def test_ambiguous_or_failed_guest_state_aborts(self):
        for state in ('', 'LoadState=loaded\nActiveState=failed', 'LoadState=masked\nActiveState=active'):
            with self.subTest(state=state), mock.patch.object(self.power, 'run', return_value=state) as run:
                with self.assertRaises(self.power.Error):
                    self.worker.stop_optional_guests()
                self.assertFalse(any('stop' in c.args[0] for c in run.call_args_list))

    def test_guest_stop_error_is_not_ignored(self):
        with mock.patch.object(self.power, 'run', side_effect=[
                'LoadState=loaded\nActiveState=active', 'LoadState=not-found\nActiveState=inactive', '',
                'ActiveState=failed\nResult=timeout']), self.assertRaises(self.power.Error):
            self.worker.stop_optional_guests()


class LaunchGraphTests(unittest.TestCase):
    def test_every_transient_launcher_has_manager_side_gate_with_absolute_path(self):
        managed = TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app'
        for path, count in ((managed/'generic.py', 1), (managed/'session.py', 3),
                            (TARGET/'usr/local/bin/labwc-qbittorrent', 1), (TARGET/'usr/local/bin/labwc-capture', 1)):
            text = payload_read_text(path)
            self.assertEqual(text.count('ConditionPathExists='), count, str(path))
            # Transient D-Bus properties do not expand unit-file specifiers.
            self.assertNotIn('ConditionPathExists=!%t/', text)
            self.assertIn('PartOf=labwc-session.target', text)
        text = payload_read_text(managed / 'session.py')
        self.assertNotIn('Requires=labwc-session.target', text)
        self.assertNotIn('Requires={startup_dependencies}', text)

    def test_existing_graph_orders_compositor_last_and_retains_bus(self):
        directory = TARGET / 'etc/skel-desktop/.config/systemd/user'
        target = payload_read_text(directory/'labwc-session.target')
        self.assertIn('After=dbus.service dbus.socket labwc-compositor.service', target)
        self.assertIn('Requires=dbus.service dbus.socket', target)
        for name in ('waybar', 'crystal-dock', 'labwc-kwallet-portal'):
            text = payload_read_text(directory / (name + '.service'))
            self.assertIn('PartOf=labwc-session.target', text)
            self.assertRegex(text, r'(?m)^After=.*labwc-session.target')
        worker = payload_read_text(TARGET/'usr/local/libexec/labwc-admin-action-worker')
        for barrier in BARRIERS:
            self.assertNotIn('"' + barrier + '"', worker)

    def test_recorder_gets_sigint_with_cgroup_lifecycle_and_existing_timeout(self):
        text = payload_read_text(TARGET / 'usr/local/bin/labwc-capture')
        for prop in ('Requisite=labwc-session.target', 'After=labwc-session.target', 'PartOf=labwc-session.target',
                     'KillMode=control-group', 'ExitType=cgroup', 'KillSignal=SIGINT', 'TimeoutStopSec=20s'):
            self.assertIn('--property=' + prop, text)


if __name__ == '__main__':
    unittest.main()
