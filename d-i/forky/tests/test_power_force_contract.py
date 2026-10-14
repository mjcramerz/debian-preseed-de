"""Single-force regression coverage: all power subprocesses are intercepted."""
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

import contextlib
import io
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from payload_fixture import read_text
from test_power_runtime_20260920 import module

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / 'd-i/forky/hooks/target'


class ForceContractTests(unittest.TestCase):
    def setUp(self):
        self.power = module()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.commands = self.stack.enter_context(mock.patch.object(self.power, 'run', return_value=''))
        self.stack.enter_context(mock.patch.object(self.power, 'ready'))
        self.stack.enter_context(mock.patch.object(self.power, 'hold_reservation'))
        self.stack.enter_context(mock.patch.object(self.power, 'sharing_stop_groups', return_value=[]))
        self.stack.enter_context(mock.patch.object(self.power.time, 'sleep'))
        self.stack.enter_context(mock.patch.object(self.power.Worker, 'userctl', return_value=''))

    def test_authorized_actions_submit_once_without_preparation_requirements(self):
        for action in ('reboot', 'poweroff'):
            for greeter in (False, True):
                with self.subTest(action=action, greeter=greeter):
                    self.commands.reset_mock()
                    worker = self.power.Worker(1000, 'desktop', action, greeter=greeter)
                    worker.final_power_action()
                    self.commands.assert_called_once_with(['/usr/bin/systemctl', '--force', action], timeout=25, max_output=4096)
                    self.assertTrue(worker.committed and worker.handoff_attempted)
                    with self.assertRaisesRegex(self.power.Error, 'only once'):
                        worker.final_power_action()

    def test_each_preparation_failure_still_submits_for_desktop_and_greeter(self):
        for action in ('reboot', 'poweroff'):
            for greeter in (False, True):
                for stage in ('helper', 'stop_optional_guests', 'stop_network_sharing', 'prepare_external_drives', 'shutdown_run'):
                    for error in (self.power.Error('service failed'), OSError('unavailable'), subprocess.SubprocessError('timeout')):
                        with self.subTest(action=action, greeter=greeter, stage=stage, error=type(error).__name__):
                            self.commands.reset_mock()
                            worker = self.power.Worker(1000, 'desktop', action, greeter=greeter)
                            with (
                                mock.patch.object(worker, 'helper'),
                                mock.patch.object(worker, stage, side_effect=error),
                                mock.patch.object(self.power, 'PackageLocks', side_effect=AssertionError('shutdown must not wait for packages')),
                                mock.patch.object(worker, 'session_identity', side_effect=AssertionError('shutdown must not require a healthy desktop')),
                                mock.patch.object(worker, 'protect_other_sessions', side_effect=AssertionError('authorization is complete')),
                            ):
                                worker.execute()
                            handoffs = [c for c in self.commands.call_args_list if '--force' in c.args[0]]
                            self.assertEqual(handoffs, [mock.call(['/usr/bin/systemctl', '--force', action], timeout=25, max_output=4096)])

    def test_unexpected_cleanup_exception_cannot_skip_handoff(self):
        worker = self.power.Worker(1000, 'desktop', 'reboot')
        with (
            mock.patch.object(worker, 'helper'),
            mock.patch.object(worker, 'prepare_machine_shutdown', side_effect=ValueError('malformed fixture')),
            self.assertRaises(ValueError),
        ):
            worker.execute()
        self.assertEqual(self.commands.call_args.args[0], ['/usr/bin/systemctl', '--force', 'reboot'])
        self.assertTrue(worker.handoff_attempted)

    def test_cleanup_deadline_skips_remaining_work_but_still_submits(self):
        worker = self.power.Worker(1000, 'desktop', 'poweroff')
        worker.shutdown_deadline = 10
        with mock.patch.object(self.power.time, 'monotonic', return_value=11):
            worker.shutdown_run(['/usr/bin/sync'])
        self.commands.assert_not_called()
        worker.final_power_action()
        self.commands.assert_called_once_with(['/usr/bin/systemctl', '--force', 'poweroff'], timeout=25, max_output=4096)

    def test_close_save_stage_precedes_application_services_and_cleanup(self):
        for action in ('poweroff', 'reboot'):
            for greeter in (False, True):
                with self.subTest(action=action, greeter=greeter):
                    worker = self.power.Worker(1000, 'desktop', action, greeter=greeter)
                    events = []
                    with (mock.patch.object(worker, 'helper', side_effect=lambda op: events.append(op)),
                          mock.patch.object(worker, 'userctl', side_effect=lambda *args, **kwargs: events.append('apps')),
                          mock.patch.object(worker, 'stop_optional_guests', side_effect=lambda: events.append('guests')),
                          mock.patch.object(worker, 'prepare_machine_shutdown', side_effect=lambda: events.append('cleanup')),
                          mock.patch.object(worker, 'final_power_action', side_effect=lambda: events.append('force'))):
                        worker.execute()
                    self.assertEqual(events, ['guests', 'cleanup', 'force'] if greeter
                                     else [action, 'apps', 'guests', 'cleanup', 'force'])

    def test_failed_save_helper_waits_only_the_remaining_grace(self):
        worker = self.power.Worker(1000, 'desktop', 'poweroff')
        for elapsed, expected in ((0, 10), (7, 3), (10, None), (25, None)):
            with (self.subTest(elapsed=elapsed),
                  mock.patch.object(worker, 'helper', side_effect=self.power.Error('helper failed')),
                  mock.patch.object(self.power.time, 'monotonic', side_effect=(100, 100 + elapsed)),
                  mock.patch.object(self.power.time, 'sleep') as sleep):
                worker.save_window()
            if expected is None:
                sleep.assert_not_called()
            else:
                sleep.assert_called_once_with(expected)

    def test_save_helper_transport_is_bounded_and_uses_the_authorized_user_unit(self):
        worker = self.power.Worker(1000, 'desktop', 'reboot')
        with mock.patch.object(worker, 'userctl') as ctl:
            worker.helper('reboot')
        ctl.assert_called_once_with('start', 'labwc-session-state@reboot.service', timeout=25)

    def test_failed_or_uncertain_submission_never_escalates_or_retries(self):
        for action in ('reboot', 'poweroff'):
            worker = self.power.Worker(1000, 'desktop', action)
            with mock.patch.object(self.power, 'run', side_effect=self.power.Error('lost reply')) as command:
                with self.assertRaisesRegex(self.power.Error, 'uncertain; do not retry automatically'):
                    worker.final_power_action()
                with self.assertRaisesRegex(self.power.Error, 'only once'):
                    worker.final_power_action()
            command.assert_called_once_with(['/usr/bin/systemctl', '--force', action], timeout=25, max_output=4096)

    def test_shutdown_alias_dispatch_does_not_wait_for_sleep_or_package_lock(self):
        for instance, greeter in (('1000-shutdown', False), ('1000-greeter-shutdown', True)):
            with (
                self.subTest(instance=instance),
                mock.patch.object(self.power.os, 'geteuid', return_value=0),
                mock.patch.object(self.power.os, 'umask'),
                mock.patch.object(self.power, 'action_lock', side_effect=AssertionError('shutdown cannot wait for another action')),
                mock.patch.object(self.power.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='desktop')),
                mock.patch.object(self.power, 'Worker') as worker,
            ):
                self.assertEqual(self.power.main([instance]), 0)
                worker.assert_called_once_with(1000, 'desktop', 'poweroff', greeter=greeter)
                worker.return_value.execute.assert_called_once_with()


class ForceTransportTests(unittest.TestCase):
    def test_force_transport_cannot_inherit_a_bus_or_boot_mode_override(self):
        power = module()
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                proc = mock.Mock(returncode=0)
                with mock.patch.dict(power.os.environ, {
                    'DBUS_SYSTEM_BUS_ADDRESS': 'unix:path=/tmp/foreign-bus',
                    'SYSTEMD_BUS_ADDRESS': 'unix:path=/tmp/foreign-bus',
                    'SYSTEMCTL_FORCE_BUS': '1', 'SYSTEMCTL_SKIP_AUTO_KEXEC': '0',
                    'SYSTEMCTL_SKIP_AUTO_SOFT_REBOOT': '0', 'LD_PRELOAD': '/tmp/foreign.so',
                    'PATH': '/tmp/foreign-bin',
                }), mock.patch.object(power.subprocess, 'Popen', return_value=proc) as launch, \
                     mock.patch.object(power, 'bounded_output', return_value=('', '')):
                    # Popen is replaced before reaching the real production runner.
                    power.run(['/usr/bin/systemctl', '--force', action], timeout=25, max_output=4096)
                launch.assert_called_once()
                self.assertEqual(launch.call_args.args[0], ['/usr/bin/systemctl', '--force', action])
                options = launch.call_args.kwargs
                self.assertEqual(options['env'], {
                    'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C.UTF-8',
                    'SYSTEMCTL_FORCE_BUS': '0', 'SYSTEMCTL_SKIP_AUTO_KEXEC': '1',
                    'SYSTEMCTL_SKIP_AUTO_SOFT_REBOOT': '1',
                })
                self.assertTrue(options['close_fds'] and options['start_new_session'])
                self.assertNotIn('shell', options)
                self.assertNotIn('account', options)


class ForceUnitConfinementTests(unittest.TestCase):
    def test_boot_capability_is_limited_to_pid1_transport_not_direct_syscalls(self):
        text = read_text(TARGET / 'etc/systemd/system/labwc-admin-action@.service')
        assignments = [line for line in text.splitlines() if line and not line.startswith('#')]
        self.assertEqual([line for line in assignments if line.startswith('CapabilityBoundingSet=')],
                         ['CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_KILL CAP_SYS_BOOT'])
        self.assertEqual([line for line in assignments if line.startswith('SystemCallFilter=')],
                         ['SystemCallFilter=@system-service', 'SystemCallFilter=~@reboot'])
        for assignment in ('AmbientCapabilities=', 'NoNewPrivileges=yes', 'PrivateUsers=no',
                           'PrivatePIDs=no', 'AppArmorProfile=labwc-admin-action-worker'):
            self.assertIn(assignment, assignments)

    def test_drive_service_uses_the_shared_manager_and_preserves_host_mounts(self):
        source = TARGET / 'etc/systemd/system/labwc-external-drives-shutdown.service'
        text = read_text(source)
        assignments = [line for line in text.splitlines() if line and not line.startswith('#')]
        for assignment in (
                'Type=oneshot', 'WorkingDirectory=/', 'TimeoutStartSec=15min',
                'ExecStart=/usr/local/bin/labwc-external-drives --prepare-shutdown',
                'AppArmorProfile=labwc-external-drives', 'NoNewPrivileges=yes',
                'PrivateMounts=no', 'PrivateDevices=no', 'PrivateTmp=no',
                'PrivateUsers=no', 'PrivatePIDs=no', 'DevicePolicy=closed',
                'CapabilityBoundingSet=CAP_DAC_READ_SEARCH',
                'SystemCallFilter=~@mount @reboot @raw-io'):
            self.assertIn(assignment, assignments)
        self.assertNotIn('[Install]', text)
        self.assertNotIn('RemainAfterExit=', text)
        self.assertNotIn('CAP_SYS_ADMIN', text)
        self.assertNotIn('CAP_SYS_BOOT', text)
        self.assertNotIn('ProtectSystem=', text)
        self.assertNotIn('ProtectHome=', text)
        publisher = read_text(ROOT / 'd-i/forky/scripts/desktop/components/target-assets.sh')
        self.assertIn('etc/systemd/system/labwc-external-drives-shutdown.service '
                      '/etc/systemd/system/labwc-external-drives-shutdown.service 0644', publisher)
        self.assertIn('require_mode /etc/systemd/system/labwc-external-drives-shutdown.service 644',
                      read_text(ROOT / 'd-i/forky/scripts/desktop/verify.sh'))

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'native systemd parser unavailable')
    def test_drive_service_passes_native_offline_unit_verification(self):
        with tempfile.TemporaryDirectory(prefix='external-drive-unit-') as directory:
            path = Path(directory) / 'labwc-external-drives-shutdown.service'
            source = read_text(TARGET / 'etc/systemd/system' / path.name)
            # Parse all production settings with an available, inert executable
            # and a dependency stub. verify never starts these services.
            path.write_text(source.replace(
                'ExecStart=/usr/local/bin/labwc-external-drives --prepare-shutdown',
                'ExecStart=/usr/bin/true'))
            (Path(directory) / 'udisks2.service').write_text(
                '[Service]\nExecStart=/usr/bin/true\n')
            # A private user-manager runtime lets the native syntax parser
            # operate in minimal containers without /run/systemd. This is
            # parsing only, not a system-manager or device-policy live test.
            runtime = Path(directory) / 'runtime'
            runtime.mkdir(mode=0o700)
            env = dict(os.environ, SYSTEMD_UNIT_PATH=directory + ':/usr/lib/systemd/user',
                       XDG_RUNTIME_DIR=str(runtime))
            result = subprocess.run(
                [shutil.which('systemd-analyze'), '--user', '--generators=no', '--man=no',
                 '--recursive-errors=no', 'verify', str(path)],
                capture_output=True, text=True, encoding='utf-8', env=env, timeout=10)
            if (result.returncode != 0 and
                    'Failed to enable SO_PASSCRED on handoff timestamp socket: Operation not permitted'
                    in result.stderr):
                self.skipTest('kernel blocks Unix socket options required by the native unit verifier')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class ExternalDrivePreparationTests(unittest.TestCase):
    def test_external_drive_stage_is_bounded_and_never_checks_clean_result(self):
        power = module()
        worker = power.Worker(1000, 'desktop', 'poweroff')
        worker.shutdown_deadline = 50
        with mock.patch.object(power.time, 'monotonic', return_value=45),              mock.patch.object(power, 'run', return_value='') as run:
            worker.prepare_external_drives()
        run.assert_called_once_with(['/usr/bin/systemctl', '--no-ask-password', 'start', power.EXTERNAL_DRIVES_UNIT],
                                    timeout=5, max_output=16384)


class FirstbootForceValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='power-force-validation-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        paths = (
            'usr/local/sbin/greetd-power-action',
            'usr/local/libexec/greetd-power-action-root',
            'usr/local/libexec/labwc-admin-action-root',
            'usr/local/libexec/labwc-admin-action-worker',
            'etc/security/sudo-i.conf',
            'etc/systemd/system/labwc-admin-action@.service',
            'etc/systemd/system/labwc-external-drives-shutdown.service',
        )
        source = read_text(ROOT / 'd-i/forky/scripts/firstboot/04-validation.sh')
        section = source.split('  # Validate the complete greeter handoff,', 1)[1]
        section = section[section.index('  if grep '):].split('\n  fi', 1)[0] + '\n  fi\n'
        for relative in paths:
            destination = self.directory / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(read_text(TARGET / relative))
            # Redirect only grep input filenames, not the patterns being checked.
            section = section.replace(' /' + relative + ' 2>/dev/null',
                                      ' ' + shlex.quote(str(destination)) + ' 2>/dev/null')
        self.worker = self.directory / 'usr/local/libexec/labwc-admin-action-worker'
        self.greeter_frontend = self.directory / 'usr/local/sbin/greetd-power-action'
        self.worker_source = self.worker.read_text()
        self.unit = self.directory / 'etc/systemd/system/labwc-admin-action@.service'
        self.unit_source = self.unit.read_text()
        self.script = ('failures=0\nrecord() { printf "%s\\n" "$*"; }\n'
                       'log_line() { :; }\n' + section + '\n[ "$failures" -eq 0 ]\n')

    def check(self, success):
        # Execute only the production read-only grep validation, never a worker.
        result = subprocess.run(['/bin/sh', '-eu', '-c', self.script],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         ('PASS' if success else 'FAIL') + ' desktop-greeter-power-handoff')

    def test_corrected_worker_and_existing_frontends_pass_firstboot_gate(self):
        self.check(True)

    def test_firstboot_rejects_inherited_greeter_shell(self):
        source = self.greeter_frontend.read_text(encoding='utf-8')
        self.assertEqual(source.count('\nunset SHELL\n'), 1)
        self.greeter_frontend.write_text(source.replace('\nunset SHELL\n', '\n'), encoding='utf-8')
        self.check(False)

    def test_firstboot_rejects_missing_external_drive_stage_or_service(self):
        original = self.worker_source
        self.worker.write_text(original.replace('self.best_effort("external drives", self.prepare_external_drives)',
                                                 'pass  # fixture removes drive cleanup'))
        self.check(False)
        self.worker.write_text(original)
        service = self.directory / 'etc/systemd/system/labwc-external-drives-shutdown.service'
        service.write_text(service.read_text().replace('DevicePolicy=closed', 'DevicePolicy=auto'))
        self.check(False)

    def test_firstboot_rejects_missing_boot_capability_or_raw_reboot_filter(self):
        mutations = (
            ('CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_KILL CAP_SYS_BOOT',
             'CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_KILL'),
            ('SystemCallFilter=~@reboot', 'SystemCallFilter=@reboot'),
        )
        for before, after in mutations:
            with self.subTest(after=after):
                self.assertEqual(self.unit_source.count(before), 1)
                self.unit.write_text(self.unit_source.replace(before, after))
                self.check(False)

    def test_firstboot_rejects_missing_double_or_replaced_force_and_weakened_action_guard(self):
        old = 'run(["/usr/bin/systemctl", "--force", self.action],'
        mutations = (
            (old, 'run(["/usr/bin/systemctl", self.action],'),
            (old, 'run(["/usr/bin/systemctl", "--force", "--force", self.action],'),
            (old, 'run(["/usr/bin/busctl", "RebootWithFlags"],'),
            (old, 'run(["/tmp/systemctl", "--force", self.action],'),
            ('if self.action not in {"reboot", "poweroff"}:',
             'if self.action not in {"reboot", "poweroff", "suspend"}:'),
        )
        for before, after in mutations:
            with self.subTest(after=after):
                self.assertEqual(self.worker_source.count(before), 1)
                self.worker.write_text(self.worker_source.replace(before, after))
                self.check(False)


if __name__ == '__main__':
    unittest.main()
