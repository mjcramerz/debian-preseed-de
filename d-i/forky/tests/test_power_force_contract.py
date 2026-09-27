"""Single-force regression coverage: all power subprocesses are intercepted."""
from __future__ import annotations

import contextlib
import io
import shlex
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
        self.stack.enter_context(mock.patch.object(self.power, 'check_shutdown_inhibitors'))
        self.stack.enter_context(mock.patch.object(self.power.Worker, 'protect_other_sessions'))
        self.commands = self.stack.enter_context(mock.patch.object(self.power, 'run', return_value=''))

    def worker(self, action, greeter=False):
        worker = self.power.Worker(1000, 'desktop', action, greeter=greeter)
        worker.prepared = not greeter
        worker.package_locks = mock.Mock()
        return worker

    def test_literal_command_for_each_desktop_and_greeter_action(self):
        for action in ('reboot', 'poweroff'):
            for greeter in (False, True):
                with self.subTest(action=action, greeter=greeter):
                    self.commands.reset_mock()
                    worker = self.worker(action, greeter)
                    worker.final_power_action()
                    self.commands.assert_called_once_with(
                        ['/usr/bin/systemctl', '--force', action], timeout=25, max_output=4096)
                    self.assertTrue(worker.committed and worker.handoff_attempted)

    def test_sync_precedes_the_last_lock_check_and_submission(self):
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                events = []
                worker = self.worker(action)
                worker.package_locks.verify.side_effect = lambda: events.append('reservation')
                with mock.patch.object(self.power.os, 'sync', side_effect=lambda: events.append('sync')), \
                     mock.patch.object(self.power, 'run', side_effect=lambda *a, **k: events.append('force')):
                    worker.final_power_action()
                self.assertEqual(events[-4:], ['sync', 'reservation', 'reservation', 'force'])

    def test_sync_failure_does_not_commit_or_submit(self):
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                self.commands.reset_mock()
                worker = self.worker(action)
                with mock.patch.object(self.power.os, 'sync', side_effect=OSError('sync failed')), \
                     self.assertRaises(OSError):
                    worker.final_power_action()
                self.commands.assert_not_called()
                self.assertFalse(worker.committed or worker.handoff_attempted)

    def test_failed_or_uncertain_submission_never_escalates_or_retries(self):
        for action in ('reboot', 'poweroff'):
            for error in (self.power.Error('transport deadline'), FileNotFoundError('systemctl'),
                          subprocess.SubprocessError('lost reply')):
                with self.subTest(action=action, error=type(error).__name__):
                    worker = self.worker(action)
                    with mock.patch.object(self.power, 'run', side_effect=error) as command:
                        with self.assertRaisesRegex(self.power.Error, 'uncertain; do not retry automatically'):
                            worker.final_power_action()
                        with self.assertRaisesRegex(self.power.Error, 'only once'):
                            worker.final_power_action()
                    command.assert_called_once_with(
                        ['/usr/bin/systemctl', '--force', action], timeout=25, max_output=4096)
                    self.assertTrue(worker.committed and worker.handoff_attempted)

    def test_shutdown_alias_is_normalized_before_worker_dispatch(self):
        for instance, greeter in (('1000-shutdown', False), ('1000-greeter-shutdown', True)):
            with self.subTest(instance=instance), \
                 mock.patch.object(self.power.os, 'geteuid', return_value=0), \
                 mock.patch.object(self.power.os, 'umask'), \
                 mock.patch.object(self.power, 'action_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(self.power.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='desktop')), \
                 mock.patch.object(self.power, 'Worker') as worker:
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
