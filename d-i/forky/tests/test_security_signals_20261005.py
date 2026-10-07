"""Boot-scoped security alerts; private files and mocked notification delivery."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from payload_fixture import logging_text

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
BOOT = '00000000-0000-0000-0000-000000000001'
NEXT_BOOT = '00000000-0000-0000-0000-000000000002'


class SecuritySignalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='security-signals-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.signals = self.root / 'signals'
        self.states = self.root / 'states'
        self.signals.mkdir(mode=0o700)
        self.states.mkdir(mode=0o700)
        self.signal = self.signals / 'apparmor.signal'
        self.signal.write_bytes(b'')
        self.signal.chmod(0o640)
        source = logging_text((TARGET / 'usr/local/bin/labwc-health-notify.tmpl').read_text(encoding='utf-8'))
        self.functions = '\n'.join((
            'atomic_state() (' + source.split('atomic_state() (', 1)[1].split('\nread_state()', 1)[0],
            'read_state() (' + source.split('read_state() (', 1)[1].split('\nnotification_transport_failed=', 1)[0],
            'check_security_signal() {' + source.split('check_security_signal() {', 1)[1].split('\ncheck_security_signals()', 1)[0],
        ))

    def invoke(self, *, boot=BOOT, failure=False):
        script = self.functions + '\n' + '\n'.join((
            'umask 077',
            'USER_UID=' + str(os.getuid()),
            'ROOT_EVENT_OWNER_UID=' + str(os.getuid()),
            'SECURITY_SIGNAL_DIR=' + shlex.quote(str(self.signals)),
            'SECURITY_SIGNAL_STATE_DIR=' + shlex.quote(str(self.states)),
            'security_boot_id=' + shlex.quote(boot),
            'notification_failures=0',
            'notify() { ' + ('return 1;' if failure else 'printf "%s\\n" "$*";') + ' }',
            'check_security_signal apparmor critical security-high system.security 0 "AppArmor policy denial detected" /var/log/managed/security/apparmor/apparmor.log',
            'exit "$notification_failures"',
        ))
        result = subprocess.run(['/bin/sh', '-eu', '-c', script], capture_output=True,
                                text=True, encoding='utf-8', timeout=5)
        self.assertEqual(result.returncode, int(failure), result.stderr)
        return result.stdout

    def append(self, count=1):
        with self.signal.open('ab') as stream:
            stream.write(b'apparmor\n' * count)

    def test_empty_signal_and_repeated_login_do_not_notify(self):
        self.assertEqual(self.invoke(), '')
        self.append()
        self.assertIn('1 new event was recorded', self.invoke())
        self.assertEqual(self.invoke(), '')
        self.append(2)
        self.assertIn('2 new events were recorded', self.invoke())
        self.assertEqual(self.invoke(), '')

    def test_boot_reset_clears_old_signal_and_new_boot_events_still_notify(self):
        self.append(3)
        self.invoke()
        # tmpfiles f+! resets in place, preserving the inode across boots.
        self.signal.write_bytes(b'')
        self.assertEqual(self.invoke(boot=NEXT_BOOT), '')
        self.append(3)
        self.assertIn('3 new events were recorded', self.invoke(boot=NEXT_BOOT))
        self.assertEqual(self.invoke(boot=NEXT_BOOT), '')

    def test_same_inode_and_count_from_previous_boot_cannot_hide_new_events(self):
        self.append()
        self.invoke()
        self.assertIn('1 new event was recorded', self.invoke(boot=NEXT_BOOT))

    def test_failed_transport_does_not_acknowledge_pending_events(self):
        self.append()
        self.invoke(failure=True)
        self.assertFalse((self.states / 'apparmor.count').exists())
        self.assertIn('1 new event was recorded', self.invoke())
        self.assertEqual(self.invoke(), '')

    def test_rotation_and_legacy_acknowledgement_are_reconciled(self):
        identity = f'{self.signal.stat().st_dev}:{self.signal.stat().st_ino}'
        state = self.states / 'apparmor.count'
        state.write_text(f'{identity}|50\n', encoding='utf-8')
        state.chmod(0o600)
        self.append()
        self.assertIn('1 new event was recorded', self.invoke())
        self.signal.rename(self.signals / 'apparmor.signal.1')
        self.signal.write_bytes(b'apparmor\n')
        self.signal.chmod(0o640)
        self.assertIn('1 new event was recorded', self.invoke())
        self.assertEqual(self.invoke(), '')

    def test_signal_between_one_mib_and_rotation_threshold_is_not_ignored(self):
        self.append(120000)
        self.assertGreater(self.signal.stat().st_size, 1048576)
        self.assertIn('120000 new events were recorded', self.invoke())

    def test_symbolic_and_group_writable_signals_are_ignored(self):
        self.append()
        self.signal.chmod(0o660)
        self.assertEqual(self.invoke(), '')
        self.signal.rename(self.signals / 'unsafe')
        self.signal.symlink_to(self.signals / 'unsafe')
        self.assertEqual(self.invoke(), '')


@unittest.skipUnless(shutil.which('systemd-tmpfiles'), 'systemd-tmpfiles unavailable')
class NativeTmpfilesTests(unittest.TestCase):
    def test_boot_clears_stale_signals_and_collector_restart_preserves_current_signals(self):
        with tempfile.TemporaryDirectory(prefix='security-tmpfiles-') as temporary:
            root = Path(temporary)
            config = root / 'etc/tmpfiles.d'
            config.mkdir(parents=True)
            text = (TARGET / 'etc/tmpfiles.d/60-security-logs.conf.tmpl').read_text(encoding='utf-8')
            rows = [line for line in text.splitlines() if re.match(r'^f\+! /var/lib/labwc-notifications/security/\w+\.signal ', line)]
            self.assertEqual(len(rows), 5)
            rows = [line.replace('root logreader', f'{os.getuid()} {os.getgid()}') for line in rows]
            (config / 'signals.conf').write_text('\n'.join(rows) + '\n', encoding='utf-8')
            signals = root / 'var/lib/labwc-notifications/security'
            signals.mkdir(parents=True)
            for row in rows:
                path = root / row.split()[1].lstrip('/')
                path.write_bytes(b'stale\n')
                path.chmod(0o640)
            command = ['/usr/bin/systemd-tmpfiles', '--root=' + str(root), '--create']
            result = subprocess.run(command + ['--boot'], capture_output=True, text=True,
                                    encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            for path in signals.iterdir():
                self.assertEqual(path.read_bytes(), b'')
                path.write_bytes(b'current\n')
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            for path in signals.iterdir():
                self.assertEqual(path.read_bytes(), b'current\n')


if __name__ == '__main__':
    unittest.main()
