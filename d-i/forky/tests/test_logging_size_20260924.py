"""Size-driven logging and prerequisite-order regressions. No live host services.

Only the optional packaged-rsyslog test starts a private foreground instance,
using a disposable /run fixture and a private socket, never /dev/log or a journal.
"""
from __future__ import annotations

import fcntl
import grp
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from payload_fixture import installed_script, logging_text, read_text, source_path

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
APP = '/var/log/managed/apps/apps.log'


def load_rotation():
    loader = importlib.machinery.SourceFileLoader('managed_size_rotation',
        str(installed_script(TARGET / 'usr/local/libexec/rsyslog-size-rotate')))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


rotation = load_rotation()


@unittest.skipUnless(os.geteuid() == 0, 'root-owned path fixtures require root')
class SizeRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.active = self.root / APP.lstrip('/')
        self.active.parent.mkdir(parents=True, mode=0o750)
        self.gid = grp.getgrnam('adm').gr_gid

    def write(self, data: bytes, path: Path | None = None):
        path = self.active if path is None else path
        path.write_bytes(data)
        path.chmod(0o640)
        os.chown(path, 0, self.gid)
        return path

    def full(self, value: bytes = b'A'):
        return self.write(value * rotation.LIMIT)

    def test_below_threshold_is_not_rotated(self):
        self.write(b'a' * (rotation.LIMIT - 1))
        inode = self.active.stat().st_ino
        self.assertFalse(rotation.rotate(APP, root=self.root))
        self.assertEqual(self.active.stat().st_ino, inode)
        self.assertFalse(self.active.with_name('apps.log.1').exists())

    def test_exact_threshold_renames_without_inventing_or_copying_records(self):
        self.full()
        before = self.active.stat()
        self.assertTrue(rotation.rotate(APP, root=self.root))
        archive = self.active.with_name('apps.log.1')
        self.assertFalse(self.active.exists())  # omfile, not the helper, reopens it
        self.assertEqual(archive.stat().st_ino, before.st_ino)
        self.assertEqual(archive.read_bytes(), b'A' * rotation.LIMIT)
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o640)
        self.assertEqual(archive.stat().st_gid, self.gid)

    def test_oversized_record_is_preserved_whole(self):
        data = b'complete record: ' + b'x' * (rotation.LIMIT + 65536) + b'\n'
        self.write(data)
        rotation.rotate(APP, root=self.root)
        self.assertEqual(self.active.with_name('apps.log.1').read_bytes(), data)

    def test_four_archives_remain_in_order_across_repeated_rotations(self):
        for index in range(7):
            self.full(bytes([65 + index]))
            rotation.rotate(APP, root=self.root)
        for index in range(1, 5):
            path = self.active.with_name(f'apps.log.{index}')
            self.assertEqual(path.read_bytes(), bytes([72 - index]) * rotation.LIMIT)
        self.assertFalse(self.active.with_name('apps.log.5').exists())
        self.assertEqual(len(list(self.active.parent.glob('apps.log.*'))), 4)

    def test_missing_active_is_idempotent(self):
        self.assertFalse(rotation.rotate(APP, root=self.root))

    def test_unknown_relative_normalized_and_traversal_paths_are_rejected(self):
        for bad in ('apps.log', '/etc/passwd', APP + '.1', APP.replace('/apps/', '/apps/../apps/'),
                    APP.replace('/apps/', '//apps/'), APP.replace('/apps/', '/apps/./')):
            with self.subTest(path=bad), self.assertRaises(rotation.RotationError):
                rotation.rotate(bad, root=self.root)

    def test_active_symlink_is_rejected_without_touching_target(self):
        other = self.write(b'untouched', self.active.with_name('other'))
        self.active.symlink_to(other.name)
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.assertEqual(other.read_bytes(), b'untouched')

    def test_active_hardlink_is_rejected(self):
        self.full()
        os.link(self.active, self.active.with_name('other'))
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.assertTrue(self.active.exists())

    def test_archive_symlink_preflight_happens_before_any_rename(self):
        self.full()
        first = self.write(b'first', self.active.with_name('apps.log.1'))
        self.active.with_name('apps.log.4').symlink_to(first.name)
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.assertEqual(first.read_bytes(), b'first')
        self.assertTrue(self.active.exists())

    def test_archive_hardlink_is_rejected_before_any_rename(self):
        self.full()
        self.write(b'old', self.active.with_name('apps.log.2'))
        os.link(self.active.with_name('apps.log.2'), self.active.with_name('elsewhere'))
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.assertTrue(self.active.exists())

    def test_writable_or_non_root_parent_is_rejected(self):
        self.full()
        for mode, uid in ((0o770, 0), (0o750, 65534)):
            self.active.parent.chmod(mode)
            os.chown(self.active.parent, uid, self.gid)
            with self.subTest(mode=mode, uid=uid), self.assertRaises(rotation.RotationError):
                rotation.rotate(APP, root=self.root)
        os.chown(self.active.parent, 0, self.gid)

    def test_parent_symlink_is_rejected(self):
        self.full()
        saved = self.active.parent.with_name('saved')
        self.active.parent.rename(saved)
        self.active.parent.symlink_to(saved.name)
        with self.assertRaises(OSError):
            rotation.rotate(APP, root=self.root)
        self.assertTrue((saved / 'apps.log').exists())

    def test_incorrect_file_owner_group_or_mode_is_rejected(self):
        self.full()
        for mode, uid, gid in ((0o666, 0, self.gid), (0o640, 65534, self.gid), (0o640, 0, 0)):
            self.active.chmod(mode)
            os.chown(self.active, uid, gid)
            with self.subTest(mode=mode, uid=uid, gid=gid), self.assertRaises(rotation.RotationError):
                rotation.rotate(APP, root=self.root)

    def test_fifo_active_and_fifo_lock_are_rejected_without_reading(self):
        os.mkfifo(self.active, 0o640)
        os.chown(self.active, 0, self.gid)
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.active.unlink()
        lock = self.active.with_name('.apps.log.rotate.lock')
        lock.unlink()  # first rejected invocation legitimately created its lock
        os.mkfifo(lock, 0o600)
        self.full()
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)

    def test_lock_symlink_and_hardlink_are_rejected(self):
        self.full()
        lock = self.active.with_name('.apps.log.rotate.lock')
        other = self.active.with_name('other.lock')
        other.write_bytes(b''); other.chmod(0o600)
        lock.symlink_to(other.name)
        with self.assertRaises(OSError):
            rotation.rotate(APP, root=self.root)
        lock.unlink(); os.link(other, lock)
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)

    def test_concurrent_lock_refuses_instead_of_waiting(self):
        self.full()
        lock = os.open(self.active.with_name('.apps.log.rotate.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, lock)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.assertRaises(BlockingIOError):
            rotation.rotate(APP, root=self.root)
        self.assertTrue(self.active.exists())

    def test_cli_requires_root_and_exactly_one_argument(self):
        with patch.object(rotation.os, 'geteuid', return_value=65534):
            self.assertEqual(rotation.main([APP]), 1)
        self.assertEqual(rotation.main([]), 1)
        self.assertEqual(rotation.main([APP, '/etc/passwd']), 1)


class LoggingWiringTests(unittest.TestCase):
    def test_each_omfile_action_has_one_allowlisted_size_callback(self):
        found = set()
        for path in (TARGET / 'etc/rsyslog.d').glob('*.conf*'):
            for action in re.findall(r'action\([^)]*\)', logging_text(path.read_text())):
                if 'type="omfile"' not in action:
                    continue
                sink = re.search(r'\bfile="([^"]+)"', action)
                self.assertIsNotNone(sink, path.name)
                self.assertIn(sink[1], rotation.OUTPUTS, path.name)
                self.assertEqual(action.count('rotation.sizeLimit="2097152"'), 1)
                self.assertIn('rotation.sizeLimitCommand="/usr/local/libexec/rsyslog-size-rotate"', action)
                self.assertIn('rotation.sizeLimitCommandPassFileName="on"', action)
                self.assertNotIn(sink[1], found, 'competing collector writers: ' + sink[1])
                found.add(sink[1])
        self.assertEqual(found, set(rotation.OUTPUTS))

    def test_apps_have_no_per_application_directories_or_fake_catalog(self):
        layout = read_text(TARGET / 'etc/tmpfiles.d/59-log-layout.conf')
        self.assertIn('f ' + APP + ' ', layout)
        self.assertEqual(re.findall(r'^d (/var/log/managed/apps\S*) ', layout, re.M), ['/var/log/managed/apps'])
        env = (SEED / 'hosts/logging/observability.env').read_text()
        for name in ('BRAVE', 'LIBREWOLF', 'FLOORP', 'ZEN', 'VIVALDI', 'CHROMIUM', 'FEATHERPAD'):
            self.assertNotIn('LOG_' + name + '_', env)
        for number in ('21-apps.conf', '44-components.conf'):
            active = read_text(TARGET / 'etc/rsyslog.d' / number)
            self.assertNotIn('re_match(', active)
            self.assertNotIn('dynaFile=', active)
            self.assertNotIn('format="jsonf"', active)

    def test_no_competing_logrotate_or_fifteen_minute_timer(self):
        text = '\n'.join(logging_text(p.read_text()) for p in (TARGET / 'etc/logrotate.d').iterdir())
        active = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
        for sink in rotation.OUTPUTS:
            self.assertNotIn(sink, active)
        self.assertNotIn('rsyslog-rotate', active)
        timer = read_text(TARGET / 'etc/systemd/system/logrotate.timer.d/override.conf')
        self.assertIn('OnCalendar=daily\n', timer)
        self.assertNotIn('*:00/', timer)
        for name in ('fail2ban', 'codex', 'chatgpt-runtime'):
            policy = read_text(TARGET / 'etc/logrotate.d' / name)
            self.assertRegex(policy, r'(?m)^\s*size 2M$')
            self.assertNotRegex(policy, r'(?m)^\s*(daily|maxsize)\b')

    def test_both_journal_validators_agree_with_input_transport(self):
        native = read_text(TARGET / 'etc/systemd/journald.conf.d/10-storage.conf')
        self.assertIn('ForwardToSyslog=yes', native)
        self.assertIn('ReadKMsg=no', native)
        shell = (SEED / 'scripts/late/storage-maintenance.sh').read_text()
        self.assertIn("'ForwardToSyslog=yes'", shell)
        self.assertNotIn("'ForwardToSyslog=no'", shell)
        route = read_text(TARGET / 'etc/rsyslog.d/15-audit.conf')
        self.assertIn('$!uid == "0"', route)
        self.assertIn('$!exe == "/usr/sbin/audisp-syslog"', route)
        self.assertNotIn('$programname ==', route)

    def test_foundation_is_staged_before_selected_helpers_in_every_family(self):
        dispatch = (SEED / 'scripts/late/dispatch.sh').read_text()
        for family in ('btrfs', 'f2fs'):
            text = (SEED / 'scripts/late' / (family + '-family.sh')).read_text()
            self.assertIn('stage_target_logging_foundation || return $?', text)
            self.assertLess(text.index('prepare_target_volatile_mountpoints_for_first_boot\nstage_target_logging_foundation'),
                            text.rindex('installer_archive_logs_to_target'))
            self.assertLess(dispatch.index('run_' + family + '_family_late_command'),
                            dispatch.index('\nrun_selected_class_helpers\n'))
        for helper, label in (('software', 'ChatGPT'), ('devops', 'Codex')):
            text = read_text(SEED / 'scripts/late' / (helper + '.sh'))
            self.assertIn('preflight shared logging paths before ' + label + ' tmpfiles', text)
            self.assertIn('/usr/local/libexec/log-layout --preflight || return $?', text)

    def test_foundation_stager_uses_exact_assets_and_propagates_failures(self):
        source = shlex.quote(str(SEED / 'scripts/late/target-assets.sh'))
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / 'trace'
            for failure in ('', '/etc/tmpfiles.d/65-audit-syslog.conf'):
                code = f'''. {source}
installer_repo_join_var() {{ shift; printf '%s\\n' "$*"; }}
stage_target_asset() {{
  printf '%s|%s|%s\\n' "$1" "$2" "$3" >> "$TRACE"
  [ "$2" != "$FAIL" ] || return 73
}}
if stage_target_logging_foundation; then exit 0; else exit $?; fi
'''
                result = subprocess.run(['/bin/sh', '-eu', '-c', code],
                    env={**os.environ, 'TRACE': str(trace), 'FAIL': failure}, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 73 if failure else 0)
                entries = trace.read_text().splitlines()
                self.assertEqual(len(entries), 2 if failure else 3)
                self.assertEqual(entries[0], 'etc/tmpfiles.d/59-log-layout.conf|/etc/tmpfiles.d/59-log-layout.conf|0644')
                trace.unlink()

    def test_informational_paths_follow_the_actual_system_collector(self):
        for helper in ('tailscale', 'crowdsec'):
            text = (SEED / 'scripts/late' / (helper + '.sh')).read_text()
            self.assertIn('log_file=$LOG_SYSTEM_SERVICES_FILE', text)
            self.assertNotIn('LOG_NETWORK_FILE', text)
            self.assertNotIn('LOG_CROWDSEC_SERVICE_FILE', text)


def exercise_native_rsyslog(case: unittest.TestCase) -> None:
    """Real credentials, native omfile callback, restart, and line-injection probe."""
    if not shutil.which('rsyslogd') or os.geteuid() != 0:
        case.skipTest('packaged rsyslogd and root required for native socket fixture')
    with tempfile.TemporaryDirectory(prefix='managed-rsyslog-test-', dir='/run') as tmp:
        root = Path(tmp); root.chmod(0o755)
        (root / 'spool').mkdir()
        app = root / 'logs/apps/apps.log'
        system = root / 'logs/system/system.log'
        kernel = root / 'logs/system/kernel.log'
        for path in (app, system, kernel):
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            path.touch(mode=0o640)
            os.chown(path, 0, grp.getgrnam('adm').gr_gid)
        # Only fixture paths change; all production rotation logic is exercised.
        helper = root / 'rotate'
        helper.write_text(read_text(TARGET / 'usr/local/libexec/rsyslog-size-rotate').replace(
            '/var/log/managed', str(root / 'logs')))
        helper.chmod(0o700)
        routes = '\n'.join(read_text(TARGET / 'etc/rsyslog.d' / name)
            for name in ('21-apps.conf', '44-components.conf'))
        routes = routes.replace('/var/log/managed', str(root / 'logs')).replace(
            '/usr/local/libexec/rsyslog-size-rotate', str(helper))
        sock = root / 'input.sock'
        config = root / 'rsyslog.conf'
        config.write_text(f'global(workDirectory="{root / "spool"}" maxMessageSize="64k")\n'
            '$FileOwner root\n$FileGroup adm\n$FileCreateMode 0640\n'
            'module(load="imuxsock" SysSock.Use="off")\n'
            f'input(type="imuxsock" Socket="{sock}" CreatePath="off" RateLimit.Interval="0" '
            'Annotate="on" ParseTrusted="on" UsePIDFromSystem="on")\n' + routes)
        stderr = (root / 'stderr').open('w+')
        process = None
        def wait_for(predicate, description):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if predicate(): return
                if process is not None and process.poll() is not None: break
                time.sleep(.025)
            stderr.flush(); stderr.seek(0)
            case.fail(description + '\n' + stderr.read())
        def start():
            nonlocal process
            process = subprocess.Popen(['rsyslogd', '-n', '-i', str(root / 'pid'), '-f', str(config)],
                stdout=stderr, stderr=stderr)
            wait_for(sock.exists, 'private socket did not start')
            sock.chmod(0o666)
        def stop():
            if process is not None and process.poll() is None:
                process.terminate(); process.wait(timeout=15)
        def send_user(count, prefix):
            code = '''import os,socket,sys,time
os.setgroups([]); os.setgid(2000); os.setuid(2000)
s=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
for i in range(int(sys.argv[2])):
 s.sendto(('<14>tuta[123]: '+sys.argv[3]+':'+str(i)+':'+('x'*8192)).encode(),sys.argv[1]); time.sleep(.003)
time.sleep(.2)
'''
            subprocess.run([sys.executable, '-I', '-c', code, str(sock), str(count), prefix],
                check=True, timeout=15)
        try:
            start(); send_user(280, 'before-restart')
            archive = app.with_name('apps.log.1')
            wait_for(archive.exists, 'native size callback did not rotate the 2 MiB output')
            case.assertGreaterEqual(archive.stat().st_size, 2 * 1024 * 1024)
            case.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o640)
            case.assertNotIn('before-restart', system.read_text())
            # A literal newline in a real input record must not create a forged
            # second line, and a spoofed program tag must not select a filename.
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                probe.sendto(b'<14>audisp-syslog[1]: injection-probe\nforged-line', str(sock))
            finally:
                probe.close()
            wait_for(lambda: 'injection-probe' in system.read_text(), 'root fallback did not receive input')
            case.assertFalse(any(line.startswith('forged-line') for line in system.read_text().splitlines()))
            stop(); start(); send_user(1, 'after-restart')
            wait_for(lambda: app.exists() and 'after-restart' in app.read_text(), 'input was not delivered after restart')
            case.assertEqual({p.name for p in app.parent.iterdir()},
                             {'apps.log', 'apps.log.1', '.apps.log.rotate.lock'})
        finally:
            stop(); stderr.close()


if __name__ == '__main__':
    unittest.main()
