"""Read-only firstboot regressions; rsyslog uses only temporary fixture files."""
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

import importlib.util
import fcntl
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


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('perl'), 'isolated root Perl fixture')
class FirstbootPolicyRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='firstboot-policy-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / 'etc/apparmor.d/firstboot'
        self.policy.parent.mkdir(parents=True)
        self.policy.write_text('profile firstboot /fixture/bootstrap {}\n')
        self.policy.chmod(0o644)
        self.lock_dir = self.root / 'var/lib/labwc-apparmor-policy'
        self.lock_dir.mkdir(parents=True, mode=0o700)
        self.lock = self.lock_dir / 'policy.lock'
        self.lock.write_text('')
        self.lock.chmod(0o600)
        libraries = self.root / 'usr/local/lib/perl5/site_perl'
        shutil.copytree(TARGET / 'usr/local/lib/perl5/site_perl/apparmor-modes',
                        libraries / 'apparmor-modes')
        runtime = libraries / 'runtime/Managed'
        runtime.mkdir(parents=True)

        def quote(path):
            return "'" + str(path).replace('\\', '\\\\').replace("'", "\\'") + "'"

        # Copy the real lock implementation, redirecting every fixed state
        # path and ancestry check into this private fixture tree.
        lock_source = (TARGET / 'usr/local/lib/perl5/site_perl/runtime/Managed/PolicyLock.pm').read_text()
        old_parents = "for my $parent ('/', '/var', '/var/lib')"
        self.assertEqual(lock_source.count(old_parents), 1)
        lock_source = lock_source.replace(old_parents, 'for my $parent (' + ', '.join(
            quote(self.root / name) for name in ('', 'var', 'var/lib')) + ')')
        lock_source = lock_source.replace("'/var/lib/labwc-apparmor-policy'", quote(self.lock_dir))
        (runtime / 'PolicyLock.pm').write_text(lock_source)

        self.helper = self.root / 'usr/local/libexec/apparmor-modes-run'
        self.helper.parent.mkdir(parents=True)
        source = (TARGET / 'usr/local/libexec/apparmor-modes-run').read_text()
        for original, target in (
            ("'/usr/local/lib/perl5/site_perl/runtime'", libraries / 'runtime'),
            ("'/usr/local/lib/perl5/site_perl/apparmor-modes'", libraries / 'apparmor-modes'),
            ("'/etc/apparmor.d/firstboot'", self.policy),
            ("'/etc/apparmor.d'", self.policy.parent),
            ("'/etc'", self.root / 'etc'),
            ("'/'", self.root),
        ):
            self.assertIn(original, source)
            source = source.replace(original, quote(target))
        self.helper.write_text(source)

    def retire(self):
        return subprocess.run(['/usr/bin/perl', str(self.helper), '--retire-firstboot'],
            env={'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'LC_ALL': 'C'},
            capture_output=True, text=True, timeout=10)

    def test_busy_policy_writer_defers_then_same_lock_allows_retirement(self):
        original = self.policy.read_bytes()
        identity = self.lock.stat().st_ino
        with self.lock.open('r+b') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.retire()
            self.assertEqual(result.returncode, 75, result.stderr)
            self.assertEqual(self.policy.read_bytes(), original)
        result = self.retire()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.policy.exists())
        self.assertEqual(self.lock.stat().st_ino, identity)
        self.assertEqual(self.retire().returncode, 0)

    def test_symlink_and_hardlink_replacements_are_rejected(self):
        retained = self.root / 'retained'
        self.policy.rename(retained)
        self.policy.symlink_to(retained)
        result = self.retire()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.policy.is_symlink())
        self.policy.unlink()
        os.link(retained, self.policy)
        result = self.retire()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.policy.exists())
        self.assertEqual(self.policy.read_bytes(), retained.read_bytes())


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
            for service in ('apparmor.service', 'auditd.service', 'journal-sealing.service'):
                self.assertIn(service, services)
        self.assertIn('rsyslog.service', re.search(r'^After=(.*)$', unit, re.M)[1].split())
        self.assertIn('rsyslog.service', re.search(r'^Wants=(.*)$', unit, re.M)[1].split())
        self.assertNotIn('rsyslog.service', re.search(r'^Requires=(.*)$', unit, re.M)[1].split())

    def test_collector_failure_is_recorded_without_short_circuiting_validation(self):
        source = (FIRSTBOOT / '04-validation.sh.tmpl').read_text()
        checker = 'check_command() {' + source.split('check_command() {', 1)[1].split(
            '\n# The required one-shot', 1)[0]
        checks = source.split('# These checks are explicit:', 1)[1].split(
            '\nif [ "$failures" -eq 0 ]; then', 1)[0]
        checks = '\n'.join(line for line in checks.splitlines()[1:] if not line.startswith('#') and line.strip())
        commands = self.root / 'commands'; commands.mkdir()
        manager = commands / 'systemctl'
        manager.write_text('''#!/bin/sh
set -eu
[ "$1" = is-active ] && [ "$2" = --quiet ] || exit 90
case "$3" in
  rsyslog.service) exit "$FIXTURE_RSYSLOG_STATUS" ;;
  syslog.socket) exit "$FIXTURE_SYSLOG_STATUS" ;;
  *) exit 91 ;;
esac
''')
        manager.chmod(0o700)
        checks = checks.replace('/usr/bin/systemctl', shlex.quote(str(manager)))
        validation = self.root / 'validation.txt'
        for service_status, socket_status, expected in ((0, 0, 0), (3, 0, 1), (0, 3, 1), (3, 3, 2)):
            with self.subTest(service_status=service_status, socket_status=socket_status):
                validation.write_text('')
                script = '''set -u
failures=0
VALIDATION_FILE=$1
record() { printf '%s\\n' "$*" >>"$VALIDATION_FILE"; }
log_line() { :; }
capture() { record "capture=$1"; }
''' + checker + '\n' + checks + '\nrecord "failures=$failures"\n'
                result = subprocess.run(
                    ['/bin/sh', '-c', script, 'fixture', str(validation)], cwd=self.root,
                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
                         'FIXTURE_RSYSLOG_STATUS': str(service_status),
                         'FIXTURE_SYSLOG_STATUS': str(socket_status)},
                    stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=3,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                report = validation.read_text()
                self.assertIn(f'failures={expected}\n', report)
                self.assertIn('capture=logging-units.txt\n', report)
                self.assertIn(('FAIL' if service_status else 'PASS') + ' rsyslog-service', report)
                self.assertIn(('FAIL' if socket_status else 'PASS') + ' syslog-socket', report)

    def test_failed_wrapper_remains_retryable_and_only_success_publishes_completion(self):
        scripts = self.root / 'stages'; scripts.mkdir()
        trace = self.root / 'stages-run.txt'
        healthy = self.root / 'collector-healthy'
        report = self.root / 'validation-result.txt'
        for name in ('01-early.sh', '02-collect.sh', '03-network.sh', '04-validation.sh'):
            body = '#!/bin/sh\nset -eu\nprintf "%s\\n" ' + shlex.quote(name) + ' >>' + shlex.quote(str(trace)) + '\n'
            if name == '04-validation.sh':
                body += ('if [ -f ' + shlex.quote(str(healthy)) + ' ]; then\n'
                         '  printf "PASS collector\\n" >' + shlex.quote(str(report)) + '\n'
                         'else\n'
                         '  printf "FAIL collector\\n" >' + shlex.quote(str(report)) + '\n'
                         '  exit 1\n'
                         'fi\n')
            stage = scripts / name
            stage.write_text(body); stage.chmod(0o700)
        # Exercise the real wrapper and marker publisher. All stages and state
        # belong to this fixture; no service manager or installed helper runs.
        cleanup = scripts / '05-cleanup.sh'
        cleanup.write_text((FIRSTBOOT / '05-cleanup.sh').read_text().replace(
            '/var/lib/firstboot/lib/logging.sh', str(scripts / 'logging.sh')))
        cleanup.chmod(0o700)
        wrapper = self.root / 'firstboot.sh'
        wrapper.write_text((FIRSTBOOT / 'firstboot.sh').read_text())
        environment = {
            'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'LC_ALL': 'C',
            'FIRSTBOOT_SCRIPT_DIR': str(scripts),
            'FIRSTBOOT_STATE_DIR': str(self.root / 'state'),
            'FIRSTBOOT_LOG_DIR': str(self.root / 'logs'),
            'FIRSTBOOT_STAGE_TIMEOUT': '2',
        }
        complete = self.root / 'state/complete'
        status = self.root / 'logs/status.env'
        def invoke():
            return subprocess.run(['/bin/sh', str(wrapper)], cwd=self.root, env=environment,
                                  stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=5)
        failed = invoke()
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertFalse(complete.exists())
        self.assertIn('status=1\n', status.read_text())
        self.assertEqual(report.read_text(), 'FAIL collector\n')
        self.assertEqual(len(trace.read_text().splitlines()), 4)
        healthy.touch()
        retried = invoke()
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertIn('status=0\n', status.read_text())
        self.assertIn('status=0\n', complete.read_text())
        self.assertEqual(report.read_text(), 'PASS collector\n')
        self.assertEqual(len(trace.read_text().splitlines()), 8)
        repeated = invoke()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn('successful completion already recorded', repeated.stdout)
        self.assertEqual(len(trace.read_text().splitlines()), 8)

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
            expected = b''.join(line for line in records if b'type=AVC ' in line)
            # Quoted application arguments/user messages are not kernel policy
            # events. They must enter neither the mirror nor the denial signal.
            records.extend((
                b'type=EXECVE msg=audit(1.0:8000): argc=1 a0=\'apparmor="DENIED"\'\n',
                b'type=USER_AVC msg=audit(1.0:8001): msg=\'type=APPARMOR_DENIED apparmor="DENIED"\'\n',
            ))
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
                    self.assertFalse(signal.exists(), 'STATUS and quoted text produced a denial signal')
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
