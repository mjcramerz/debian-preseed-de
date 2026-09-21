"""Power lifecycle regressions. All manager/power calls are mocked."""
from __future__ import annotations
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
    exec(compile(path.read_bytes(), str(path), 'exec'), result.__dict__)
    return result


class QuiescenceTests(unittest.TestCase):
    def setUp(self):
        self.power = module()
        self.worker = self.power.Worker(1000, 'desktop', 'reboot')
        self.worker.package_locks = mock.Mock()  # acquired gate fixture; real locks tested separately
        self.members = {'labwc-session.target', 'labwc-compositor.service',
                        'labwc-wayland-foot-0123456789.service', 'waybar.service', 'labwc-swayidle.service'}
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(self.power, 'run', side_effect=AssertionError('unexpected unmocked command')).start()
        self.sink = contextlib.redirect_stderr(io.StringIO()); self.sink.__enter__()
        self.addCleanup(self.sink.__exit__, None, None, None)

    def states(self, *, change=None, omit=None):
        blocks = []
        for name in sorted(self.members):
            if name == omit:
                continue
            props = dict(Id=name, LoadState='loaded', ActiveState='inactive', Job='0', MainPID='0', ControlPID='0')
            if name == 'labwc-wayland-foot-0123456789.service' and change:
                props.update(change)
            blocks.append('\n'.join(k + '=' + v for k, v in props.items()))
        return '\n\n'.join(blocks) + '\n'

    def transport(self, states=None, stop_error=None):
        def call(*args, **kwargs):
            self.assertFalse(set(args) & BARRIERS)
            self.assertNotIn('dbus.service', args)
            self.assertNotIn('dbus-broker.service', args)
            self.assertNotIn('dbus.socket', args)
            if args[0] == 'stop':
                self.assertTrue(self.worker.committed)
                self.assertNotIn('--no-block', args)
                self.assertEqual(set(args[1:]), {'labwc-session.target','labwc-compositor.service'})
                if stop_error:
                    raise stop_error
                return ''
            if '--property=ConsistsOf' in args:
                return ' '.join(sorted(self.members - {'labwc-session.target', 'labwc-compositor.service'}))
            self.assertEqual(args[:3], ('show', '--property=Id,LoadState,ActiveState,Job,MainPID,ControlPID', '--'))
            return self.states() if states is None else states
        return mock.patch.object(self.worker, 'userctl', side_effect=call)

    def test_stop_waits_for_every_client_and_compositor_and_verifies_before_handoff(self):
        with self.transport() as userctl:
            self.worker.quiesce_desktop()
        self.assertTrue(self.worker.quiesced)
        self.assertEqual([c.args[0] for c in userctl.call_args_list], ['show', 'stop', 'show', 'show'])
        self.assertEqual(userctl.call_args_list[1].kwargs['timeout'], 120)

    def test_active_deactivating_pending_job_and_live_pids_prevent_handoff(self):
        for change in ({'ActiveState': 'active'}, {'ActiveState': 'deactivating'},
                       {'Job': '243'}, {'MainPID': '832'}, {'ControlPID': '122'}, {'ActiveState': ''}):
            with self.subTest(change=change):
                self.worker.quiesced = False
                with self.transport(self.states(change=change)), self.assertRaises(self.power.Error):
                    self.worker.quiesce_desktop()
                self.assertFalse(self.worker.quiesced)
                with self.assertRaises(self.power.Error):
                    self.worker.final_power_action()
        self.power.run.assert_not_called()

    def test_terminal_failure_without_processes_is_not_misread_as_running(self):
        # Genuine historical failure stays visible; no reset-failed or blanket
        # SuccessExitStatus is used to hide it. Teardown only tests quiescence.
        with self.transport(self.states(change={'ActiveState': 'failed'})):
            self.worker.quiesce_desktop()
        self.assertTrue(self.worker.quiesced)

    def test_missing_duplicate_or_empty_property_block_fails_closed(self):
        for states in ('', self.states(omit='waybar.service'), self.states() + '\n' + self.states()):
            with self.subTest(states=states), self.transport(states), self.assertRaises(self.power.Error):
                self.worker.quiesce_desktop()
            self.assertFalse(self.worker.quiesced)

    def test_stop_timeout_is_committed_but_never_forces_or_restarts(self):
        with self.transport(stop_error=self.power.Error('timeout')), self.assertRaises(self.power.Error):
            self.worker.quiesce_desktop()
        self.assertTrue(self.worker.committed)
        self.assertFalse(self.worker.quiesced)
        self.power.run.assert_not_called()

    def test_membership_failure_before_stop_is_cancellable(self):
        for name in ('../../host.service', '--force', 'bad name.service', 'a\n--system', 'x'*300 + '.service'):
            with self.subTest(name=name), mock.patch.object(self.worker, 'userctl', return_value=name) as ctl:
                with self.assertRaises(self.power.Error):
                    self.worker.quiesce_desktop()
                self.assertEqual(ctl.call_count, 1)
                self.assertFalse(self.worker.committed)

    def test_new_member_after_stop_must_also_be_inactive(self):
        extra = 'labwc-late.service'
        with mock.patch.object(self.worker, 'desktop_members', side_effect=[self.members, self.members | {extra}]), \
                mock.patch.object(self.worker, 'userctl', side_effect=['', self.states() +
                        '\nId=' + extra + '\nActiveState=activating\n']), self.assertRaises(self.power.Error):
            self.worker.quiesce_desktop()
        self.assertFalse(self.worker.quiesced)

    def test_successfully_drained_transport_is_not_killed(self):
        # This is only a disposable Python print process, never a power command.
        original = module()
        with mock.patch.object(original.os, 'killpg') as kill:
            self.assertEqual(original.run([sys.executable, '-c', 'print("ok")']), 'ok\n')
        kill.assert_not_called()

    def test_handoff_environment_cannot_redirect_bus_or_select_soft_reboot(self):
        self.assertEqual(self.power.ENV['SYSTEMCTL_FORCE_BUS'], '0')
        self.assertEqual(self.power.ENV['SYSTEMCTL_SKIP_AUTO_KEXEC'], '1')
        self.assertEqual(self.power.ENV['SYSTEMCTL_SKIP_AUTO_SOFT_REBOOT'], '1')
        self.assertFalse({'DBUS_SYSTEM_BUS_ADDRESS', 'DBUS_SESSION_BUS_ADDRESS'} & self.power.ENV.keys())


class GuestHookTests(unittest.TestCase):
    def setUp(self):
        self.power = module(); self.worker = self.power.Worker(1000, 'desktop', 'poweroff')

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
            text = path.read_text()
            self.assertEqual(text.count('ConditionPathExists='), count, str(path))
            # Transient D-Bus properties do not expand unit-file specifiers.
            self.assertNotIn('ConditionPathExists=!%t/', text)
            self.assertIn('PartOf=labwc-session.target', text)
        text = (managed / 'session.py').read_text()
        self.assertNotIn('Requires=labwc-session.target', text)
        self.assertNotIn('Requires={startup_dependencies}', text)

    def test_existing_graph_orders_compositor_last_and_retains_bus(self):
        directory = TARGET / 'etc/skel-desktop/.config/systemd/user'
        target = (directory/'labwc-session.target').read_text()
        self.assertIn('After=dbus.service dbus.socket labwc-compositor.service', target)
        self.assertIn('Requires=dbus.service dbus.socket', target)
        for name in ('waybar', 'crystal-dock', 'labwc-kwallet-portal'):
            text = (directory / (name + '.service')).read_text()
            self.assertIn('PartOf=labwc-session.target', text)
            self.assertRegex(text, r'(?m)^After=.*labwc-session.target')
        worker = (TARGET/'usr/local/libexec/labwc-admin-action-worker').read_text()
        for barrier in BARRIERS:
            self.assertNotIn('"' + barrier + '"', worker)

    def test_recorder_gets_sigint_with_cgroup_lifecycle_and_existing_timeout(self):
        text = (TARGET / 'usr/local/bin/labwc-capture').read_text()
        for prop in ('Requisite=labwc-session.target', 'After=labwc-session.target', 'PartOf=labwc-session.target',
                     'KillMode=control-group', 'ExitType=cgroup', 'KillSignal=SIGINT', 'TimeoutStopSec=20s'):
            self.assertIn('--property=' + prop, text)


if __name__ == '__main__':
    unittest.main()
