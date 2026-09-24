"""Boot-log failure, retention and filesystem contracts; no live mount or journal."""
from __future__ import annotations

import fcntl
import grp
import importlib.util
import importlib.machinery
import os
from pathlib import Path
import resource
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from payload_fixture import installed_script, read_text

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
SOURCE = TARGET / 'usr/local/libexec/journal-snapshot'
BOOT = '0123456789abcdef0123456789abcdef'
STAMP = '2026-09-23-12-00'


def load():
    path = installed_script(SOURCE)
    loader = importlib.machinery.SourceFileLoader('boot_log_fixture', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@unittest.skipUnless(os.geteuid() == 0, 'root-owned filesystem boundary fixtures require root')
class BootLogTests(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.gid = grp.getgrnam(self.m.GROUP).gr_gid
        self.tmp = tempfile.TemporaryDirectory(prefix='boot-log-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.dir.chmod(0o750)
        os.chown(self.dir, 0, self.gid)
        self.fd = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.captured = []
        self.capture = patch.object(self.m, 'capture', self.write_capture)
        self.capture.start()
        self.addCleanup(self.capture.stop)

    def write_capture(self, fd, boot):
        self.captured.append(boot)
        os.write(fd, ('journal for ' + boot + '\n').encode())

    def snapshot(self, boot=BOOT, stamp=STAMP):
        return self.m.snapshot(self.fd, boot, stamp, self.gid)

    def seed(self, number, boot, stamp=STAMP):
        path = self.dir / f'boot-{number}-{stamp}-{boot}.log'
        path.write_text(boot)
        path.chmod(0o640)
        os.chown(path, 0, self.gid)
        return path

    def contents(self):
        return {p.name: p.read_bytes() for p in self.dir.iterdir()}

    def test_twelve_boots_leave_ten_ordered_files_and_no_counter(self):
        for number in range(1, 13):
            self.assertTrue(self.snapshot(f'{number:032x}'))
        names = sorted(self.dir.iterdir(), key=lambda p: int(p.name.split('-')[1]))
        self.assertEqual(len(names), 10)
        for index, path in enumerate(names, 1):
            self.assertEqual(path.name, f'boot-{index}-{STAMP}-{index + 2:032x}.log')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), (0, self.gid))
        self.assertEqual(len(self.captured), 12)

    def test_same_boot_is_not_recaptured(self):
        self.assertTrue(self.snapshot())
        before = self.contents()
        self.assertFalse(self.snapshot(stamp='2026-09-24-23-59'))
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.captured, [BOOT])

    def test_numeric_order_not_mtime_or_clock_and_gaps_are_compacted(self):
        older = self.seed(8, f'{1:032x}', '2030-12-31-23-59')
        newer = self.seed(30, f'{2:032x}', '2020-01-01-00-00')
        os.utime(older, (9000, 9000))
        os.utime(newer, (1, 1))
        self.snapshot()
        self.assertTrue((self.dir / f'boot-1-2030-12-31-23-59-{1:032x}.log').exists())
        self.assertTrue((self.dir / f'boot-2-2020-01-01-00-00-{2:032x}.log').exists())
        self.assertTrue((self.dir / f'boot-3-{STAMP}-{BOOT}.log').exists())

    def test_failed_capture_keeps_all_history_and_removes_scratch(self):
        for n in range(1, 11):
            self.seed(n, f'{n:032x}')
        before = self.contents()
        def fail(fd, boot):
            os.write(fd, b'incomplete')
            raise subprocess.TimeoutExpired('journalctl', 60)
        with patch.object(self.m, 'capture', fail), self.assertRaises(subprocess.TimeoutExpired):
            self.snapshot()
        self.assertEqual(self.contents(), before)

    def test_publication_failure_keeps_all_history(self):
        self.seed(1, f'{1:032x}')
        before = self.contents()
        with patch.object(self.m.os, 'rename', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.snapshot()
        self.assertEqual(self.contents(), before)

    def test_duplicate_boot_ids_are_rejected_before_capture(self):
        self.seed(1, BOOT)
        self.seed(2, BOOT)
        before = self.contents()
        with self.assertRaises(self.m.BootLogError):
            self.snapshot()
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.captured, [])

    def test_foreign_file_is_not_deleted_or_adopted(self):
        foreign = self.dir / 'boot-count.json'
        foreign.write_text('owned by someone else')
        with self.assertRaises(self.m.BootLogError):
            self.snapshot()
        self.assertEqual(foreign.read_text(), 'owned by someone else')
        self.assertEqual(self.captured, [])

    def test_symlink_fifo_hardlink_and_wrong_metadata_are_rejected(self):
        for kind in ('symlink', 'fifo', 'hardlink', 'mode', 'group'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                self.seed(1, f'{1:032x}')
                entry = self.dir / f'boot-2-{STAMP}-{2:032x}.log'
                outside = Path(temp) / 'outside'
                outside.write_text('protected')
                outside.chmod(0o640)
                os.chown(outside, 0, self.gid)
                if kind == 'symlink':
                    entry.symlink_to(outside)
                elif kind == 'fifo':
                    os.mkfifo(entry, 0o640)
                    os.chown(entry, 0, self.gid)
                elif kind == 'hardlink':
                    os.link(outside, entry)
                else:
                    entry = self.seed(2, f'{2:032x}')
                    if kind == 'mode':
                        entry.chmod(0o660)
                    else:
                        os.chown(entry, 0, 65534)
                with self.assertRaises(self.m.BootLogError):
                    self.snapshot()
                self.assertEqual(outside.read_text(), 'protected')
                self.assertEqual(self.captured, [])
                entry.unlink()

    def test_only_validated_own_stale_scratch_is_removed(self):
        temp = self.dir / ('.boot-log-' + 'a' * 32 + '.tmp')
        temp.write_text('interrupted')
        os.chown(temp, 0, self.gid)
        temp.chmod(0o640)
        self.assertTrue(self.snapshot())
        self.assertFalse(temp.exists())

    def test_lock_contention_does_not_write(self):
        other = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertFalse(self.snapshot())
            self.assertEqual(self.contents(), {})
        finally:
            os.close(other)
        self.assertTrue(self.snapshot())

    def test_invalid_identifiers_never_write(self):
        for boot, stamp in (('../etc/passwd', STAMP), (BOOT.upper(), STAMP),
                            (BOOT, '2026-09-23;id'), ('', STAMP)):
            with self.subTest(boot=boot, stamp=stamp), self.assertRaises(self.m.BootLogError):
                self.snapshot(boot, stamp)
        self.assertEqual(self.contents(), {})

    def test_secure_directory_walk_and_prepare(self):
        with tempfile.TemporaryDirectory(prefix='boot-secure-', dir='/root') as temp:
            root = Path(temp)
            good = root / 'state' / 'snapshots'
            fd = self.m.directory_fd(good, create=True, group=self.gid)
            os.close(fd)
            self.assertEqual(stat.S_IMODE(good.stat().st_mode), 0o750)
            self.assertEqual(good.stat().st_gid, self.gid)
            link = root / 'link'
            link.symlink_to(good, target_is_directory=True)
            with self.assertRaises(OSError):
                self.m.directory_fd(link, group=self.gid)
            (root / 'state').chmod(0o777)
            with self.assertRaises(self.m.BootLogError):
                self.m.directory_fd(good, group=self.gid)
        with self.assertRaises(self.m.BootLogError):
            self.m.directory_fd(self.dir, group=self.gid)  # /tmp is untrusted.
        for bad in (Path('relative'), Path('/root/../tmp')):
            with self.assertRaises(self.m.BootLogError):
                self.m.directory_fd(bad, group=self.gid)

    def test_prepare_creates_only_boot_directory_without_journal_reads(self):
        with tempfile.TemporaryDirectory(prefix='boot-prepare-', dir='/root') as temp:
            boot = Path(temp) / 'journal' / 'boot'
            with patch.object(self.m, 'DIRECTORY', boot), patch.object(sys, 'argv', ['journal-snapshot', '--prepare']):
                self.assertEqual(self.m.main(), 0)
                self.assertTrue(boot.is_dir())
                self.assertEqual(stat.S_IMODE(boot.stat().st_mode), 0o750)
                self.assertEqual(boot.stat().st_gid, self.gid)
                self.assertFalse(boot.with_name('power').exists())
            self.assertEqual(self.captured, [])

    def test_root_adm_can_create_and_chown_without_capabilities(self):
        if not shutil.which('setpriv'):
            self.skipTest('setpriv is unavailable')
        # Reproduce the service identity and empty capability set, not a root
        # fixture accidentally relying on CAP_CHOWN or CAP_DAC_OVERRIDE.
        file = self.dir / 'uncapped-file'
        code = ('import os; fd=os.open(%r,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o640); '
                'os.fchown(fd,0,%d); os.close(fd)' % (str(file), self.gid))
        result = subprocess.run(['setpriv', '--reuid=0', f'--regid={self.gid}',
                                 '--clear-groups', '--bounding-set=-all', '--inh-caps=-all',
                                 '--ambient-caps=-all', sys.executable, '-I', '-c', code],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


    def test_power_mode_is_rejected_before_journal_access(self):
        with patch.object(sys, 'argv', ['journal-snapshot', 'power']):
            with self.assertRaisesRegex(self.m.BootLogError, 'usage:'):
                self.m.main()
        self.assertEqual(self.captured, [])

    def test_power_action_output_is_native_append_with_private_mode(self):
        unit = read_text(TARGET / 'etc/systemd/system/labwc-admin-action@.service')
        self.assertIn('StandardOutput=append:/var/lib/journal/power/action-%i.log', unit)
        self.assertIn('StandardError=inherit', unit)
        self.assertIn('UMask=0077', unit)
        self.assertIn('RequiresMountsFor=/var/lib/journal/power', unit)
        self.assertNotIn('journal-snapshot', unit)

    def test_power_worker_never_exports_or_syncs_a_journal(self):
        text = read_text(TARGET / 'usr/local/libexec/labwc-admin-action-worker')
        self.assertNotIn('journalctl', text)
        self.assertNotIn('journal-snapshot', text)
        self.assertNotIn('power-log-capture', text)
        self.assertIn('file=sys.stderr, flush=True', text)

    def test_sleep_guard_uses_the_rotated_native_power_sink(self):
        unit = read_text(TARGET / 'etc/systemd/system/labwc-package-sleep-guard.service')
        route = read_text(TARGET / 'etc/rsyslog.d/19-power.conf')
        self.assertIn('StandardOutput=journal', unit)
        self.assertIn('$programname == "labwc-package-sleep-guard"', route)
        self.assertIn('file="/var/lib/journal/power/actions.log"', route)
        self.assertIn('  stop', route)
        self.assertNotIn('imfile', route)

class BootCaptureAndUnitTests(unittest.TestCase):
    def test_capture_uses_native_journal_argv_timeout_and_kernel_size_limit(self):
        m = load()
        previous = resource.getrlimit(resource.RLIMIT_FSIZE)
        calls = []
        with tempfile.TemporaryFile() as out:
            def run(argv, **kw):
                calls.append((argv, kw))
                if '--sync' not in argv:
                    os.write(kw['stdout'], b'complete journal\n')
                    self.assertEqual(resource.getrlimit(resource.RLIMIT_FSIZE)[0],
                                     m.MAX_BYTES if previous[0] < 0 else min(m.MAX_BYTES, previous[0]))
                return subprocess.CompletedProcess(argv, 0)
            with patch.object(m.subprocess, 'run', run):
                m.capture(out.fileno(), BOOT)
        self.assertEqual(resource.getrlimit(resource.RLIMIT_FSIZE), previous)
        self.assertEqual([item[1]['timeout'] for item in calls], [10, 60])
        self.assertIn('--boot=' + BOOT, calls[1][0])
        self.assertNotIn('shell', calls[1][1])

    def test_capture_failure_restores_limit_and_rejects_empty_success(self):
        m = load()
        before = resource.getrlimit(resource.RLIMIT_FSIZE)
        with tempfile.TemporaryFile() as out, patch.object(m.subprocess, 'run'):
            with self.assertRaisesRegex(m.BootLogError, 'empty'):
                m.capture(out.fileno(), BOOT)
        self.assertEqual(resource.getrlimit(resource.RLIMIT_FSIZE), before)

    def test_native_units_use_direct_persistent_directories(self):
        boot = read_text(TARGET / 'etc/systemd/system/boot-log.service')
        timer = read_text(TARGET / 'etc/systemd/system/boot-log.timer')
        self.assertIn('Group=adm\n', boot)
        self.assertIn('CapabilityBoundingSet=\n', boot)
        self.assertNotIn('ProcSubset=pid', boot)
        self.assertIn('ReadWritePaths=/var/lib/journal/boot\n', boot)
        self.assertIn('OnBootSec=60s\n', timer)
        self.assertNotIn('Persistent=', timer)
        for name in ('boot-log.mount', 'power-log.service', 'power-log-capture.service'):
            self.assertFalse((TARGET / ('etc/systemd/system/' + name)).exists())
            self.assertFalse((TARGET / ('etc/systemd/system/' + name + '.tmpl')).exists())

    def test_units_enable_offline_without_a_mount_or_service_start(self):
        if not shutil.which('systemctl'):
            self.skipTest('systemd utilities are unavailable')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'etc/systemd/system'
            directory.mkdir(parents=True)
            for name in ('boot-log.service', 'boot-log.timer'):
                (directory / name).write_text(read_text(TARGET / ('etc/systemd/system/' + name)))
            result = subprocess.run(['systemctl', '--root=' + temp, '--no-reload', 'enable',
                                     'boot-log.timer'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((directory / 'timers.target.wants/boot-log.timer').is_symlink())
            self.assertFalse((directory / 'sysinit.target.wants/power-log.service').exists())



if __name__ == '__main__':
    unittest.main()
