"""Power lifecycle regressions. All manager/power calls are mocked."""
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
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.stack.enter_context(mock.patch.object(self.power, 'ready'))
        self.stack.enter_context(mock.patch.object(self.power, 'hold_reservation'))
        self.stack.enter_context(mock.patch.object(self.worker, 'helper'))
        self.stack.enter_context(mock.patch.object(self.worker, 'stop_optional_guests'))
        self.stack.enter_context(mock.patch.object(self.worker, 'prepare_machine_shutdown'))
        self.final = self.stack.enter_context(mock.patch.object(self.worker, 'final_power_action'))

    def test_cleanup_failures_do_not_skip_power_handoff(self):
        for stage in ('helper', 'stop_optional_guests', 'prepare_machine_shutdown'):
            with self.subTest(stage=stage):
                self.final.reset_mock()
                with mock.patch.object(self.worker, stage, side_effect=self.power.Error('failed cleanup')):
                    self.worker.execute()
                self.final.assert_called_once()

    def test_shutdown_does_not_wait_for_package_or_session_queries(self):
        with (
            mock.patch.object(self.power, 'PackageLocks', side_effect=AssertionError('package gate')),
            mock.patch.object(self.worker, 'session_identity', side_effect=AssertionError('session gate')),
            mock.patch.object(self.worker, 'protect_other_sessions', side_effect=AssertionError('session gate')),
        ):
            self.worker.execute()
        self.worker.helper.assert_called_once_with('close')
        self.final.assert_called_once()

    def test_handoff_environment_cannot_redirect_bus_or_select_soft_reboot(self):
        self.assertFalse({'DBUS_SYSTEM_BUS_ADDRESS', 'DBUS_SESSION_BUS_ADDRESS'} & self.power.ENV.keys())
        self.assertEqual(self.power.ENV['SYSTEMCTL_FORCE_BUS'], '0')
        self.assertEqual(self.power.ENV['SYSTEMCTL_SKIP_AUTO_KEXEC'], '1')
        self.assertEqual(self.power.ENV['SYSTEMCTL_SKIP_AUTO_SOFT_REBOOT'], '1')

    def test_successfully_drained_transport_is_not_killed(self):
        original = module()
        with mock.patch.object(original.os, 'killpg') as kill:
            self.assertEqual(original.run([sys.executable, '-c', 'print("ok")']), 'ok\n')
        kill.assert_not_called()


class GuestHookTests(unittest.TestCase):
    def test_fixed_guest_hooks_have_bounded_best_effort_stop(self):
        power = module()
        worker = power.Worker(1000, 'desktop', 'poweroff')
        worker.shutdown_deadline = 20
        with mock.patch.object(power.time, 'monotonic', return_value=15), mock.patch.object(power, 'run', return_value='') as run:
            worker.stop_optional_guests()
        run.assert_called_once_with(['/usr/bin/systemctl', '--no-ask-password', 'stop',
                                     'podman-devops-restart.service', 'incus-startup.service'],
                                    timeout=5, max_output=16384)
        self.assertFalse(any('show' in c.args[0] for c in run.call_args_list))


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
