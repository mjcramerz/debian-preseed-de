"""Real ownership-layout regression: user data is never a root publication root."""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import stat
import unittest

import test_resctl_bench_20260916 as base


@unittest.skipUnless(os.geteuid() == 0, 'real root/account ownership boundary requires root')
class DocumentationDestinationTests(unittest.TestCase):
    def setUp(self):
        self.installer = base.module()
        self.temp = base.tempfile.TemporaryDirectory(prefix='resctl-docs-test-', dir='/root')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.docs = self.work / 'data/docs'
        self.docs.mkdir(parents=True)
        self.marker = self.docs / 'user-notes.txt'
        self.marker.write_text('existing account data\n')
        uid, gid = pwd.getpwnam('nobody').pw_uid, pwd.getpwnam('nobody').pw_gid
        for path in (self.docs, self.marker):
            os.chown(path, uid, gid)
        self.docs.chmod(0o2750)
        self.before = {p: (p.stat().st_uid, p.stat().st_gid, stat.S_IMODE(p.stat().st_mode)) for p in (self.docs, self.marker)}
        release = self.work / 'release.tar.gz'
        base.archive(release)
        self.root, self.binaries = self.installer.unpack(base.arguments(), release, self.work / 'stage')
        self.installer.BIN_DIR = self.work / 'usr/local/bin'
        self.installer.DOC_DIR = self.work / 'usr/local/share/doc/resctl-bench'

    def test_account_owned_data_reproduces_original_rejection(self):
        with self.assertRaisesRegex(self.installer.Error, 'unsafe installation directory'):
            self.installer.trusted_directory(self.docs / 'resctl-bench')
        self.assertFalse((self.docs / 'resctl-bench').exists())

    def test_protected_destination_installs_repeatably_without_touching_user_data(self):
        for _ in range(2):
            self.installer.publish(base.arguments(), self.root, self.binaries)
        self.assertTrue((self.installer.DOC_DIR / 'INSTALLATION.json').is_file())
        self.assertTrue((self.installer.DOC_DIR / 'release/README.md').is_file())
        self.assertTrue((self.installer.DOC_DIR / 'release/share/licenses/resctl-bench/COPYING').is_file())
        self.assertEqual(self.marker.read_text(), 'existing account data\n')
        self.assertEqual({p: (p.stat().st_uid, p.stat().st_gid, stat.S_IMODE(p.stat().st_mode)) for p in self.before}, self.before)
        self.assertEqual(list(self.docs.iterdir()), [self.marker])
        for p in self.installer.DOC_DIR.rglob('*'):
            self.assertEqual(p.stat().st_uid, 0)
            self.assertEqual(stat.S_IMODE(p.stat().st_mode) & 0o022, 0)
            if p.is_file():
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o644)

    def test_system_doc_symlink_to_user_data_still_rejected(self):
        self.installer.DOC_DIR.parent.mkdir(parents=True)
        self.installer.DOC_DIR.symlink_to(self.docs, target_is_directory=True)
        with self.assertRaisesRegex(self.installer.Error, 'unsafe installation directory'):
            self.installer.publish(base.arguments(), self.root, self.binaries)
        self.assertEqual(list(self.installer.BIN_DIR.iterdir()), [])
        self.assertEqual(list(self.docs.iterdir()), [self.marker])

    def test_destination_parent_mutable_by_group_still_rejected(self):
        self.installer.DOC_DIR.parent.mkdir(parents=True)
        self.installer.DOC_DIR.parent.chmod(0o775)
        with self.assertRaisesRegex(self.installer.Error, 'unsafe installation directory'):
            self.installer.publish(base.arguments(), self.root, self.binaries)
        self.assertEqual(list(self.installer.BIN_DIR.iterdir()), [])

    def test_all_runtime_verifiers_use_same_protected_destination(self):
        self.assertEqual(base.module().DOC_DIR, Path('/usr/local/share/doc/resctl-bench'))
        for relative in ('scripts/desktop/verify.sh', 'scripts/firstboot/04-validation.sh'):
            source = (base.SEED / relative).read_text()
            self.assertIn('/usr/local/share/doc/resctl-bench/INSTALLATION.json', source)
            self.assertNotIn('/data/docs/resctl-bench/INSTALLATION.json', source)


if __name__ == '__main__':
    unittest.main()
