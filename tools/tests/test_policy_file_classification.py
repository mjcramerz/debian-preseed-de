"""Language classification is based on policy location, not executable names."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[2] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from pathlib import Path
import runpy
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
class PolicyFileClassification(unittest.TestCase):
    def test_release_inventory_classifies_directory_links_without_traversing(self):
        checker = runpy.run_path(str(ROOT / 'tools/release_audit.py'))
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'source'
            root.mkdir()
            outside = base / 'outside'
            outside.mkdir()
            (outside / 'must-not-read').write_text('fixture')
            (root / 'escape').symlink_to(outside, target_is_directory=True)
            entries = list(checker['release_entries'](root, root / 'evidence/report.json'))
            self.assertEqual([path.name for path, _ in entries], ['escape'])
            self.assertTrue(stat.S_ISLNK(entries[0][1].st_mode))

    def test_release_inventory_excludes_actual_and_previous_evidence(self):
        checker = runpy.run_path(str(ROOT / 'tools/release_audit.py'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.txt').write_text('source')
            for name in ('custom-evidence/old-run', '.build/validation/prior-run'):
                folder = root / name
                folder.mkdir(parents=True)
                (folder / 'old.json').write_text('stale')
            entries = list(checker['release_entries'](root, root / 'custom-evidence/new.json'))
            self.assertEqual([path.name for path, _ in entries], ['source.txt'])

    def test_release_inventory_rejects_evidence_escape_and_bounds_enumeration(self):
        checker = runpy.run_path(str(ROOT / 'tools/release_audit.py'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source.txt').write_text('source')
            with self.assertRaisesRegex(ValueError, 'parent traversal'):
                list(checker['release_entries'](root, root / '../report.json'))
            checker['release_entries'].__globals__['MAX_SOURCE_ENTRIES'] = 0
            with self.assertRaisesRegex(ValueError, 'entry limit'):
                list(checker['release_entries'](root, root / 'report.json'))

    def test_shell_named_apparmor_profile_is_not_parsed_as_shell(self):
        checker=runpy.run_path(str(ROOT/'tools/check_shells.py'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);policy=root/'etc/apparmor.d/usr.local.sbin.example.sh'
            policy.parent.mkdir(parents=True)
            policy.write_text('profile example /usr/local/sbin/example.sh flags=(attach_disconnected) { }\n')
            script=root/'example.sh';script.write_text('#!/bin/sh\nexit 0\n')
            self.assertEqual(list(checker['shell_sources'](root)),[(script,'posix')])
            policy.write_text('#!/bin/sh\nexit 0\n')
            self.assertEqual(len(list(checker['shell_sources'](root))),2)

    def test_audit_does_not_count_policy_attachment_as_a_shell_failure_or_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'d-i/forky/tests/audit_codebase.py'
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/'d-i/forky/tests/audit_codebase.py',script)
            policy=root/'d-i/forky/hooks/target/etc/apparmor.d/usr.local.sbin.example.sh'
            policy.parent.mkdir(parents=True)
            policy.write_text('profile example /usr/local/sbin/example.sh flags=(attach_disconnected) { }\n')
            report=root/'audit.json'
            result=subprocess.run([sys.executable,'-B',str(script),'--output',str(report)],
                                  capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            record=json.loads(report.read_text())['files'][0]
            self.assertEqual(record['kind'],'apparmor-policy')
            self.assertEqual(record['check'],'inventory-only')
