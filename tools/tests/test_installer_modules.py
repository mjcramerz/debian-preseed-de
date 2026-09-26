"""Direct editable input, runtime module inventory and publication contracts."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

checker = load('check_modules')
publisher = load('publication')

class ModuleContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.seed = self.root / 'd-i/forky'
        shutil.copytree(ROOT / 'd-i/forky/scripts', self.seed / 'scripts')
        shutil.copytree(ROOT / 'd-i/forky/hosts/profiles', self.seed / 'hosts/profiles')

    def test_inventory_is_explicit_complete_and_read_only(self):
        before = {p: p.read_bytes() for p in self.seed.rglob('*') if p.is_file()}
        self.assertEqual(checker.check(self.seed), 47)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertFalse((ROOT / 'src').exists())
        self.assertFalse((ROOT / 'tools/generate_installer.py').exists())

    def test_module_edit_remains_authoritative_and_is_not_repaired(self):
        path = self.seed / 'scripts/common/modules/files-logging.sh'
        path.write_text(path.read_text() + '\n# local administrator edit\n')
        before = path.read_bytes()
        checker.check(self.seed)
        self.assertEqual(path.read_bytes(), before)

    def test_profile_edit_is_read_directly_and_does_not_change_other_hosts(self):
        files = sorted((self.seed / 'hosts/profiles').glob('*.env'))
        before = {p: p.read_bytes() for p in files}
        path = files[0]
        path.write_text(path.read_text().replace('SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="256"',
                                                'SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="512"'))
        edited = path.read_bytes()
        checker.check(self.seed)
        self.assertEqual(path.read_bytes(), edited)
        self.assertEqual([p for p in files if p.read_bytes() != before[p]], [path])

    def test_invalid_flags_sizes_and_duplicates_are_rejected_without_writes(self):
        path = next((self.seed / 'hosts/profiles').glob('*.env'))
        original = path.read_text()
        bad = [original.replace('TMPFS_VAR_SPOOL_RSYSLOG="true"', 'TMPFS_VAR_SPOOL_RSYSLOG="maybe"'),
               original.replace('SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="256"', 'SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="0"'),
               original + 'TMPFS_VAR_SPOOL_RSYSLOG="false"\n',
               original.replace('SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="256"', 'SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="$(false)"')]
        for text in bad:
            with self.subTest(text=text[-90:]):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    checker.check(self.seed)
                self.assertEqual(path.read_text(), text)

    def test_orphan_duplicate_and_missing_modules_are_rejected(self):
        orphan = self.seed / 'scripts/common/modules/orphan.sh'
        orphan.write_text('#!/bin/sh\n')
        with self.assertRaises(ValueError): checker.check(self.seed)
        orphan.unlink()
        entry = self.seed / 'scripts/common/lib.sh'
        text = entry.read_text()
        line = next(line for line in text.splitlines() if line.startswith('bootstrap_source_module '))
        entry.write_text(text + line + '\n')
        with self.assertRaises(ValueError): checker.check(self.seed)
        entry.write_text(text)
        (self.seed / 'scripts/common/modules/files-logging.sh').unlink()
        with self.assertRaises(ValueError): checker.check(self.seed)

    def test_symlink_hardlink_and_path_traversal_are_rejected(self):
        path = self.seed / 'scripts/common/modules/files-logging.sh'
        path.unlink()
        path.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError): checker.check(self.seed)
        path.unlink()
        os.link(self.seed / 'scripts/common/credentials.sh', path)
        with self.assertRaises(ValueError): checker.check(self.seed)
        for name in ('../outside.sh', '/etc/passwd', 'scripts/common/../x.sh'):
            with self.assertRaises(ValueError): checker.module_file(self.seed, name)

    def test_invalid_module_syntax_is_rejected(self):
        (self.seed / 'scripts/common/modules/files-logging.sh').write_text('if then\n')
        with self.assertRaises(ValueError): checker.check(self.seed)

    def test_build_and_check_preserve_every_edited_environment_file(self):
        # A full repository copy: edits exist in the actual served files only.
        for name in ('tools', 'browser-config', 'd-i'):
            shutil.copytree(ROOT / name, self.root / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('tests', '__pycache__'))
        files = list(self.seed.rglob('*.env'))
        for path in files:
            path.write_bytes(path.read_bytes() + b'\n# administrator edit must survive publication\n')
        before = {p: (p.read_bytes(), p.stat().st_mode) for p in files}
        for args in ([], ['--check']):
            result = subprocess.run([sys.executable, '-B', str(self.root / 'tools/build.py'), *args],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mode) for p in files})

class PublicationContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.products = {name: b'new-' + name.encode() for name in publisher.SNAPSHOT_PRODUCTS}
        for name in self.products:
            (self.root / name).write_bytes(b'old-' + name.encode())
            (self.root / name).chmod(0o644)

    def test_snapshot_publication_is_idempotent(self):
        self.assertEqual(publisher.publish_snapshot(self.root, self.products), 3)
        self.assertEqual(publisher.publish_snapshot(self.root, self.products), 0)

    def test_failure_restores_previous_generation(self):
        before = {p: p.read_bytes() for p in self.root.iterdir()}
        real = publisher.atomic_write
        calls = 0
        def fail_once(*args):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError('injected publication failure')
            return real(*args)
        with mock.patch.object(publisher, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError): publisher.publish_snapshot(self.root, self.products)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.iterdir()})

    def test_environment_output_is_unconditionally_rejected(self):
        env = self.root / 'profile.env'
        env.write_bytes(b'KEEP="true"\n')
        with self.assertRaises(ValueError): publisher.atomic_write(env, b'bad', 0o644)
        with self.assertRaises(ValueError): publisher.publish_snapshot(self.root, {'profile.env': b'bad'})
        self.assertEqual(env.read_bytes(), b'KEEP="true"\n')

    def test_linked_snapshot_output_is_rejected_before_any_write(self):
        path = self.root / 'payload.manifest'
        path.unlink()
        path.symlink_to('/etc/passwd')
        old = (self.root / 'preseed.cfg').read_bytes()
        with self.assertRaises(ValueError): publisher.publish_snapshot(self.root, self.products)
        self.assertEqual((self.root / 'preseed.cfg').read_bytes(), old)

if __name__ == '__main__': unittest.main()
