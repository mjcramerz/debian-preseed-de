"""Read-only firstboot regressions; rsyslog uses only temporary fixture files."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from payload_fixture import logging_text

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
FIRSTBOOT = SEED / 'scripts/firstboot'
EVENT = b'node=fixture type=AVC msg=audit(1.000:7): apparmor="STATUS" operation="profile_load"\n'


class FirstbootDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audit = self.root / 'audit.log'
        self.output = self.root / 'apparmor.log'
        text = logging_text((FIRSTBOOT / '04-validation.sh.tmpl').read_text())
        self.function = text.split('apparmor_log_delivery() {', 1)[1].split(
            '\ncheck_command apparmor-log-delivery', 1)[0]
        self.function = 'apparmor_log_delivery() {' + self.function
        self.function = self.function.replace('/var/log/managed/security/audit/auditd.log', str(self.audit))
        self.function = self.function.replace('/var/log/managed/security/apparmor/apparmor.log', str(self.output))

    def run_check(self, sleep=':'):
        return subprocess.run(['sh', '-eu', '-c', self.function +
            '\nsleep() { ' + sleep + '; }\napparmor_log_delivery\n'],
            capture_output=True, text=True, timeout=5)

    def test_exact_native_record_is_required(self):
        self.audit.write_bytes(EVENT)
        self.output.write_bytes(EVENT.replace(b':7)', b':6)'))
        failed = self.run_check()
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('native-record-not-delivered', failed.stdout)
        self.output.write_bytes(EVENT)
        self.assertEqual(self.run_check().returncode, 0)

    def test_missing_or_empty_native_logs_never_pass(self):
        for content in (None, b'', b'type=SYSCALL msg=audit(1.0:1): success=yes\n'):
            if content is not None:
                self.audit.write_bytes(content)
            result = self.run_check()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('no-native-apparmor-record', result.stdout)

    def test_delayed_creation_and_rotation_are_observed(self):
        self.audit.with_suffix('.log.1').write_bytes(EVENT)
        self.audit.write_bytes(b'')
        self.assertEqual(self.run_check(
            f'cp {shlex.quote(str(self.audit) + ".1")} {shlex.quote(str(self.output) + ".1")}').returncode, 0)

    def test_last_native_record_and_enriched_bytes_are_preserved(self):
        enriched = EVENT.rstrip(b'\n') + b'\x1dUID="root"\n'
        self.audit.write_bytes(EVENT + enriched)
        self.output.write_bytes(EVENT)
        self.assertNotEqual(self.run_check().returncode, 0)
        self.output.write_bytes(enriched)
        self.assertEqual(self.run_check().returncode, 0)

    def test_symlinked_log_is_rejected(self):
        self.audit.write_bytes(EVENT)
        self.output.symlink_to(self.audit)
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_required_services_are_ordered_before_firstboot(self):
        unit = (FIRSTBOOT / 'assets/etc/systemd/system/firstboot.service').read_text()
        for setting in ('Requires', 'After'):
            services = re.search(r'^' + setting + '=(.*)$', unit, re.M)[1].split()
            for service in ('auditd.service', 'rsyslog.service', 'journal-sealing.service'):
                self.assertIn(service, services)

    def test_desktop_diagnostics_distinguish_system_and_user_units(self):
        source = (FIRSTBOOT / '04-validation.sh.tmpl').read_text()
        system = re.search(r'^    capture desktop-units.txt (.*)$', source, re.M)[1]
        self.assertNotIn('pipewire', system)
        self.assertNotIn('xdg-desktop-portal', system)
        self.assertIn('capture desktop-user-unit-files.txt systemctl --global list-unit-files pipewire.socket', source)


class ServiceAccountProcessesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('service_processes', FIRSTBOOT / 'service-account-processes.py')
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.proc = Path(self.temp.name)

    def process(self, pid, name, real=900, effective=900):
        entry = self.proc / str(pid)
        entry.mkdir()
        (entry / 'status').write_text(f'Name:\t{name}\nUid:\t{real}\t{effective}\t{effective}\t{effective}\n')
        # Any use of ps-style stat/exe/fd traversal would now fail.
        (entry / 'stat').mkdir()
        return entry

    def test_real_uid_is_checked_even_when_effective_uid_differs(self):
        self.process(1, 'pipewire', real=1000, effective=900)
        self.process(2, 'dbus-broker', real=900, effective=0)
        self.process(3, 'podman')
        self.assertCountEqual(self.module.process_names(900, self.proc), ['dbus-broker', 'podman'])

    def test_exit_race_is_ignored_but_malformed_identity_fails(self):
        (self.proc / '42').mkdir()
        self.assertEqual(self.module.process_names(900, self.proc), [])
        (self.proc / '42/status').write_text('Name:\tpipewire\n')
        with self.assertRaises(ValueError):
            self.module.process_names(900, self.proc)

    def test_unreadable_status_is_not_treated_as_an_exited_process(self):
        self.process(2, 'pipewire')
        with mock.patch.object(Path, 'open', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.module.process_names(900, self.proc)

    def test_invalid_uids_fail_and_helper_is_staged_and_confined(self):
        for uid in (0, -1, 4294967295):
            with self.assertRaises(ValueError):
                self.module.process_names(uid, self.proc)
        core = (SEED / 'scripts/late/core.sh').read_text()
        policy = (FIRSTBOOT / 'assets/etc/apparmor.d/firstboot.tmpl').read_text()
        self.assertIn('${DIR_FIRSTBOOT_LIB}/service-account-processes.py', core)
        self.assertIn('/var/lib/firstboot/lib/service-account-processes.py r,', policy)
        self.assertNotIn('peer=waybar,', policy)


class AuditWiringTests(unittest.TestCase):
    def test_input_batch_fits_the_smallest_permitted_queue(self):
        source = (TARGET / 'etc/rsyslog.d/30-apparmor.conf.tmpl').read_text()
        schema = (SEED / 'hosts/logging/observability-schema.tsv').read_text()
        capacity = int(re.search(r'^LOG_RSYSLOG_QUEUE_MESSAGES\s+int\s+(\d+),', schema, re.M)[1])
        batch = int(re.search(r'MaxSubmitAtOnce="(\d+)"', source)[1])
        self.assertLess(batch, capacity)
        self.assertGreater(batch, 0)

    def test_battery_uses_existing_descriptor_boundary(self):
        config = (TARGET / 'etc/skel-desktop/.config/waybar/config.tmpl').read_text()
        self.assertIn('"exec": "/usr/local/libexec/labwc-waybar-exec /usr/local/libexec/labwc-waybar-battery"', config)
        self.assertNotIn('"exec": "/usr/local/libexec/labwc-waybar-battery"', config)
        policy = (TARGET / 'etc/apparmor.d/labwc-session').read_text().split('profile labwc-waybar-battery ', 1)[1].split('\n}', 1)[0]
        self.assertNotIn('/dev/rfkill', policy)


@unittest.skipUnless(shutil.which('rsyslogd'), 'packaged rsyslogd unavailable; native delivery NOT validated')
class NativeAuditDeliveryTests(unittest.TestCase):
    def test_backlog_live_append_rotation_and_restart(self):
        with tempfile.TemporaryDirectory(prefix='apparmor-input-') as temp:
            root = Path(temp)
            spool = root / 'spool'
            spool.mkdir()
            audit = root / 'audit.log'
            output = root / 'apparmor.log'
            signal = root / 'signal'
            source = logging_text((TARGET / 'etc/rsyslog.d/30-apparmor.conf.tmpl').read_text())
            source = source.replace('/var/log/managed/security/audit/auditd.log', str(audit))
            source = source.replace('/var/log/managed/security/apparmor/apparmor.log', str(output))
            source = source.replace('/var/lib/labwc-notifications/security/apparmor.signal', str(signal))
            # Fixture identity only: support unprivileged and mapped-UID runners.
            source = re.sub(r'(file|dir)Owner="[^"]+"', rf'\1OwnerNum="{os.getuid()}"', source)
            source = re.sub(r'(file|dir)Group="[^"]+"', rf'\1GroupNum="{os.getgid()}"', source)
            config = root / 'rsyslog.conf'
            config.write_text(f'global(workDirectory="{spool}" maxMessageSize="64k")\n' + source)
            command = ['rsyslogd', '-f', str(config)]
            parsed = subprocess.run(command + ['-N1'], capture_output=True, text=True, timeout=10)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            # More than the 1000-record queue capacity; default imfile batches
            # of 1024 can stall before the first AppArmor record is delivered.
            records = []
            for index in range(4096):
                kind = 'AVC' if index % 3 == 0 else 'SYSCALL'
                data = 'apparmor="STATUS" operation="profile_load"' if kind == 'AVC' else 'success=yes'
                records.append(f'node=fixture type={kind} msg=audit(1.0:{index}): {data}\n'.encode())
            expected = b''.join(line for line in records if b'apparmor=' in line)
            audit.write_bytes(b''.join(records))
            with (root / 'stderr').open('w+') as stderr:
                process = None

                def start():
                    nonlocal process
                    process = subprocess.Popen(command + ['-n', '-i', str(root / 'pid')], stdout=stderr, stderr=stderr)

                def stop():
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                            self.fail('private rsyslog failed to terminate')

                def delivered():
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        if output.exists() and output.read_bytes() == expected:
                            return
                        if process.poll() is not None:
                            break
                        time.sleep(.05)
                    stderr.flush()
                    stderr.seek(0)
                    self.fail('incomplete native audit delivery: ' + stderr.read())

                try:
                    start()
                    delivered()
                    denied = b'type=AVC msg=audit(2.0:9000): apparmor="DENIED" operation="open"\n'
                    with audit.open('ab') as stream:
                        stream.write(denied)
                    expected += denied
                    delivered()
                    deadline = time.monotonic() + 3
                    while not signal.exists() and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertEqual(signal.read_bytes(), b'apparmor\n')
                    # Exercise auditd's rename-and-create rotation, not copytruncate.
                    audit.rename(root / 'audit.log.1')
                    rotated = EVENT.replace(b':7)', b':9001)')
                    audit.write_bytes(rotated)
                    expected += rotated
                    delivered()
                    stop()
                    start()
                    restarted = EVENT.replace(b':7)', b':9002)')
                    with audit.open('ab') as stream:
                        stream.write(restarted)
                    expected += restarted
                    delivered()
                finally:
                    stop()
                self.assertEqual(output.read_bytes(), expected)


if __name__ == '__main__':
    unittest.main()
