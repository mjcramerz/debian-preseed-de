"""Regression for the installed noexec /var/tmp policy; never run a benchmark.

Synthetic ELF fixtures exercise real nobody credential changes and a real
noexec filesystem when /dev/shm provides one. No mounts or policies are changed.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes

import errno
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import test_resctl_bench_20260916 as base


@unittest.skipUnless(os.geteuid() == 0, 'root needed to test real credential dropping')
class NoexecInstallerTests(unittest.TestCase):
    def setUp(self):
        self.installer = base.module()
        self.temp = tempfile.TemporaryDirectory(prefix='resctl-noexec-test-', dir='/var/lib')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        # This is the fixture ancestor, not the private archive workspace.
        self.work.chmod(0o755)
        self.installer.BIN_DIR = self.work / 'usr/local/bin'
        self.installer.DOC_DIR = self.work / 'data/docs/resctl-bench'
        self.archive_work = self.work / 'archive-private'
        self.archive_work.mkdir(mode=0o700)
        self.archive = self.archive_work / 'release.tar.gz'
        base.archive(self.archive)
        self.root, self.binaries = self.installer.unpack(
            base.arguments(), self.archive, self.archive_work / 'stage')

    def compile_fixture(self):
        compiler = shutil.which('cc')
        if compiler is None:
            self.skipTest('C compiler needed for harmless real ELF fixture')
        account = pwd.getpwnam('nobody')
        source = self.work / 'version.c'
        source.write_text('''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
int main(int argc, char **argv) {
    struct stat st;
    if (getuid() != %d || geteuid() != %d || getgid() != %d || getegid() != %d) return 10;
    if (getgroups(0, NULL) != 0) return 11;
    if (argc != 2 || strcmp(argv[1], "--version")) return 12;
    if (!getenv("HOME") || stat(getenv("HOME"), &st)) return 13;
    if (st.st_uid != geteuid() || (st.st_mode & 0777) != 0700) return 14;
    if (access("../bin/rd-agent", W_OK) == 0) return 15;
    puts("harmless-fixture 2.2.6");
    return 0;
}
''' % (account.pw_uid, account.pw_uid, account.pw_gid, account.pw_gid))
        binary = self.work / 'fixture'
        subprocess.run(payload_installed_argv([compiler, '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)]),
                       check=True, capture_output=True, timeout=30)
        return payload_read_bytes(binary)

    def executable_archive(self, parent):
        files = base.payload()
        binary = self.compile_fixture()
        for name in self.installer.BINS:
            files['bin/' + name] = binary
        archive = parent / 'fixture.tar.gz'
        base.archive(archive, files)
        return self.installer.unpack(base.arguments(), archive, parent / 'fixture-stage')

    def assert_clean(self):
        if payload_source_exists(self.installer.BIN_DIR):
            self.assertEqual(list(self.installer.BIN_DIR.iterdir()), [])
        self.assertFalse(payload_source_exists(self.installer.DOC_DIR))

    def test_only_verified_binaries_copied_to_private_destination_staging(self):
        def check(probe, binaries, version, home):
            self.assertEqual(probe.parent, self.installer.BIN_DIR)
            self.assertTrue(probe.name.startswith('.resctl-bench-smoke-'))
            self.assertEqual(stat.S_IMODE(payload_source_stat(probe).st_mode), 0o711)
            self.assertEqual(set(p.name for p in probe.iterdir()), {'bin'})
            self.assertEqual(sorted(p.name for p in (probe/'bin').iterdir()), self.binaries)
            self.assertEqual(version, '2.2.6')
            self.assertEqual(home, probe/'home')
            self.assertEqual(stat.S_IMODE(payload_source_stat(self.archive_work).st_mode), 0o700)
            for name in binaries:
                p = probe/'bin'/name
                self.assertEqual(payload_read_bytes(p), payload_read_bytes(self.root/'bin'/name))
                self.assertEqual(stat.S_IMODE(payload_source_stat(p).st_mode), 0o555)
                self.assertEqual(payload_source_stat(p).st_uid, 0)
                self.assertNotEqual(payload_source_stat(p).st_ino, payload_source_stat(self.root/'bin'/name).st_ino)
        with mock.patch.object(self.installer, 'smoke', side_effect=check) as smoke:
            self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        smoke.assert_called_once()
        self.assert_clean()

    def test_noexec_destination_fails_without_running_or_changing_mount_policy(self):
        flags = type('Flags', (), {'f_flag': os.ST_NOEXEC})()
        with mock.patch.object(self.installer.os, 'statvfs', return_value=flags), \
                mock.patch.object(self.installer, 'smoke') as smoke:
            with self.assertRaisesRegex(self.installer.Error, 'destination .* mounted noexec'):
                self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        smoke.assert_not_called()
        self.assert_clean()

    def test_permission_denial_has_actionable_diagnostic_and_cleans_staging(self):
        with mock.patch.object(self.installer.subprocess, 'run', side_effect=PermissionError(errno.EACCES, 'denied')):
            with self.assertRaisesRegex(self.installer.Error, 'directory traversal, mount noexec, and AppArmor'):
                self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        self.assert_clean()

    def test_nonzero_probe_never_publishes_and_cleans_staging(self):
        result = subprocess.CompletedProcess([], 1, '', 'fixture error')
        with mock.patch.object(self.installer.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(self.installer.Error, 'nothing installed'):
                self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        self.assert_clean()

    def test_timeout_never_publishes_and_cleans_staging(self):
        with mock.patch.object(self.installer.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 20)):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        self.assert_clean()

    def test_bad_copy_digest_is_rejected_before_execution(self):
        original = self.installer.shutil.copyfile
        def corrupt(source, destination, **kwargs):
            original(source, destination, **kwargs)
            Path(destination).write_bytes(b'corrupted fixture copy')
        with mock.patch.object(self.installer.shutil, 'copyfile', side_effect=corrupt), \
                mock.patch.object(self.installer, 'smoke') as smoke:
            with self.assertRaisesRegex(self.installer.Error, 'checksum mismatch'):
                self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        smoke.assert_not_called()
        self.assert_clean()

    def test_untrusted_executable_or_symlink_is_rejected(self):
        source = self.root/'bin/rd-agent'
        source.chmod(0o777)
        with self.assertRaisesRegex(self.installer.Error, 'untrusted verified executable'):
            self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        self.assert_clean()
        source.unlink()
        source.symlink_to(self.root/'bin/rd-hashd')
        with self.assertRaisesRegex(self.installer.Error, 'untrusted verified executable'):
            self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        self.assert_clean()

    def test_untrusted_staging_ancestor_is_rejected(self):
        self.installer.BIN_DIR.mkdir(parents=True)
        self.installer.BIN_DIR.chmod(0o777)
        with self.assertRaisesRegex(self.installer.Error, 'unsafe installation directory'):
            self.installer.smoke_verified(self.root, self.binaries, '2.2.6')
        self.assert_clean()

    def test_unlisted_or_duplicate_binary_is_rejected(self):
        for binaries in ([], ['../rd-agent'], ['rd-agent', 'rd-agent'], ['install.py']):
            with self.subTest(binaries=binaries), self.assertRaisesRegex(self.installer.Error, 'inventory'):
                self.installer.smoke_verified(self.root, binaries, '2.2.6')
        self.assert_clean()

    def test_real_probes_work_without_exposing_private_archive_workspace(self):
        root, binaries = self.executable_archive(self.archive_work)
        self.installer.smoke_verified(root, binaries, '2.2.6')
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.archive_work).st_mode), 0o700)
        self.assert_clean()
        # Publish the ORIGINAL verified release after probes, not child-accessible copies.
        self.installer.publish(base.arguments(), root, binaries)
        for name in binaries:
            self.assertEqual(payload_read_bytes(self.installer.BIN_DIR/name), payload_read_bytes(root/'bin'/name))
            self.assertEqual(stat.S_IMODE(payload_source_stat(self.installer.BIN_DIR/name).st_mode), 0o755)
        self.assertFalse(list(self.installer.BIN_DIR.glob('.resctl-bench-smoke-*')))

    def test_real_noexec_reproduces_eacces_then_staged_probe_succeeds(self):
        noexec = Path('/dev/shm')
        if not noexec.is_dir() or not os.statvfs(noexec).f_flag & os.ST_NOEXEC:
            self.skipTest('no existing noexec /dev/shm; test never mounts filesystems')
        with tempfile.TemporaryDirectory(prefix='resctl-noexec-fixture-', dir=noexec) as temporary:
            work = Path(temporary)
            root, binaries = self.executable_archive(work)
            # Allow traversal to prove this is kernel noexec, not a 0700 parent.
            work.chmod(0o755)
            account = pwd.getpwnam('nobody')
            with self.assertRaises(PermissionError) as denied:
                subprocess.run(payload_installed_argv([str(root/'bin/rd-agent'), '--version']), user=account.pw_uid,
                               group=account.pw_gid, extra_groups=(), check=True, timeout=10,
                               capture_output=True)
            self.assertEqual(denied.exception.errno, errno.EACCES)
            work.chmod(0o700)
            self.installer.smoke_verified(root, binaries, '2.2.6')
            self.assertEqual(stat.S_IMODE(payload_source_stat(work).st_mode), 0o700)
            self.assertTrue(os.statvfs(noexec).f_flag & os.ST_NOEXEC)
            self.assert_clean()

    def test_main_uses_private_archive_then_smoke_then_publish(self):
        seen = []
        real_temporary = tempfile.TemporaryDirectory
        def temporary(**kwargs):
            self.assertEqual(kwargs, {'prefix': 'resctl-bench-', 'dir': '/var/tmp'})
            return real_temporary(prefix='main-fixture-', dir=self.work)
        def download(args, destination):
            base.archive(destination)
            seen.append('download')
        def probe(root, binaries, version):
            work = root.parent.parent
            self.assertEqual(stat.S_IMODE(payload_source_stat(work).st_mode), 0o700)
            self.assertEqual(version, '2.2.6')
            seen.append('smoke')
        def publish(args, root, binaries):
            self.assertEqual(seen, ['download', 'smoke'])
            seen.append('publish')
        args = base.arguments()
        argv = ['installer']
        for key, value in vars(args).items():
            argv.extend(['--' + key.replace('_', '-'), str(value)])
        open_real = os.open
        def open_lock(path, flags, mode=0o777, **kwargs):
            if path == '/run/resctl-bench-install.lock':
                path = self.work/'install.lock'
            return open_real(path, flags, mode, **kwargs)
        with mock.patch.object(self.installer.sys, 'argv', argv), \
                mock.patch.object(self.installer.os, 'open', side_effect=open_lock), \
                mock.patch.object(self.installer.os, 'umask'), \
                mock.patch.object(self.installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'amd64\n')), \
                mock.patch.object(self.installer.tempfile, 'TemporaryDirectory', side_effect=temporary), \
                mock.patch.object(self.installer, 'download', side_effect=download), \
                mock.patch.object(self.installer, 'smoke_verified', side_effect=probe), \
                mock.patch.object(self.installer, 'publish', side_effect=publish):
            self.assertEqual(self.installer.main(), 0)
        self.assertEqual(seen, ['download', 'smoke', 'publish'])
        self.assertFalse(list(self.work.glob('main-fixture-*')))


if __name__ == '__main__':
    unittest.main()
