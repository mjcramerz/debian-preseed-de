"""Standalone generator transactions with explicit nft/manager fixtures only."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/sbin/nft-policy-generate.py'


@unittest.skipUnless(os.geteuid() == 0, 'root ownership fixture')
class GenerationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.m = types.ModuleType('nft_generation_fixture')
        sys.modules[self.m.__name__] = self.m
        exec(compile(SOURCE.read_bytes(), str(SOURCE), 'exec'), self.m.__dict__)
        temporary = tempfile.TemporaryDirectory(prefix='nft-recovery-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.conf = self.root / 'etc/nftables.conf'
        self.fragment = self.root / 'etc/nftables.d/fragment.nft'
        self.fragment.parent.mkdir(parents=True)
        self.old = {self.conf: b'# previous configuration\n', self.fragment: b'# previous fragment\n'}
        for path, data in self.old.items():
            path.write_bytes(data)
            path.chmod(0o640)
        self.paths = {'nftables_conf': self.conf, 'filter': self.fragment}
        self.rendered = {self.conf: f'include "{self.fragment}"\n', self.fragment: '# candidate\n'}
        self.args = types.SimpleNamespace(check=True, reload=False, command_timeout=1,
                                          target_root=self.root, backup_dir=Path('/backups'))

    def assert_previous(self):
        for path, data in self.old.items():
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_candidate_rejection_never_publishes(self):
        def reject(argv, label, *args, **kwargs):
            self.assert_previous()
            text = Path(argv[-1]).read_text()
            self.assertNotIn(f'include "{self.fragment}"', text)
            self.assertIn('candidate-1.nft', text)
            raise self.m.PolicyError('fixture parse rejection')
        with mock.patch.object(self.m, 'run_checked', side_effect=reject), \
             self.assertRaisesRegex(self.m.PolicyError, 'previous state restored'):
            self.m.write_generation(self.args, self.paths, self.rendered)
        self.assert_previous()
        self.assertFalse(list(self.root.rglob('.nft-policy-recovery.*')))

    def test_rename_then_fsync_failure_restores_exact_bytes_and_new_absence(self):
        self.fragment.unlink()
        self.old.pop(self.fragment)
        original = self.m.atomic_write
        def fail_after_write(path, *args, **kwargs):
            original(path, *args, **kwargs)
            if path == self.fragment:
                raise OSError('fixture directory fsync failure')
        with mock.patch.object(self.m, 'atomic_write', side_effect=fail_after_write), \
             mock.patch.object(self.m, 'run_checked', return_value=''), \
             self.assertRaisesRegex(self.m.PolicyError, 'previous state restored'):
            self.m.write_generation(self.args, self.paths, self.rendered)
        self.assert_previous()
        self.assertFalse(self.fragment.exists())

    def test_failed_rollback_retains_previous_bytes_and_reported_bundle(self):
        original = self.m.os.replace
        def fail_restore(source, target):
            if Path(source).name.startswith('.nft-restore.'):
                raise OSError('fixture rollback refusal')
            return original(source, target)
        def reject_published(argv, label, *args, **kwargs):
            if label == 'nft published validation':
                raise self.m.PolicyError('fixture reload boundary rejection')
            return ''
        with mock.patch.object(self.m.os, 'replace', side_effect=fail_restore), \
             mock.patch.object(self.m, 'run_checked', side_effect=reject_published), \
             self.assertRaisesRegex(self.m.PolicyError, 'outcome unknown.*recovery retained at') as failure:
            self.m.write_generation(self.args, self.paths, self.rendered)
        bundles = list(self.root.rglob('.nft-policy-recovery.*'))
        self.assertEqual(len(bundles), 1)
        self.assertIn(str(bundles[0]), str(failure.exception))
        manifest = json.loads((bundles[0] / 'previous.json').read_text())
        for item in manifest:
            self.assertEqual(Path(item['backup']).read_bytes(), self.old[Path(item['path'])])

    def test_reload_timeout_restores_only_owned_live_tables_and_retains_evidence(self):
        self.args.reload = True
        observed = []
        def command(argv, label, *args, **kwargs):
            observed.append(label)
            if label == 'nft table snapshot':
                return json.dumps({'nftables': [{'table': {'family': 'inet', 'name': 'labwc_filter'}},
                                               {'table': {'family': 'inet', 'name': 'foreign'}}]})
            if label == 'nft owned-table snapshot':
                return 'table inet labwc_filter { chain old { } }\n'
            if label == 'nftables reload':
                raise self.m.CommandTimeout('nftables reload: timed out after 1 seconds')
            if label == 'nft live rollback':
                text = Path(argv[-1]).read_text()
                self.assertNotIn('flush ruleset', text)
                self.assertNotIn('foreign', text)
                self.assertIn('chain old', text)
            return ''
        with mock.patch.object(self.m, 'run_checked', side_effect=command), \
             self.assertRaisesRegex(self.m.PolicyError, 'outcome unknown'):
            self.m.write_generation(self.args, self.paths, self.rendered)
        self.assert_previous()
        self.assertIn('nft live rollback', observed)
        self.assertEqual(len(list(self.root.rglob('.nft-policy-recovery.*'))), 1)

    def test_invalid_option_combinations_fail_before_output_or_policy_reads(self):
        with mock.patch.object(self.m, 'load_policy') as load, mock.patch.object(self.m, 'write_generation') as write:
            for options in (['--reload', '--write'], ['--check'], ['--reload', '--check', '--write', '--target-root', str(self.root)]):
                self.assertEqual(self.m.main(['--profile', str(self.root / 'unused'), *options]), 2)
            load.assert_not_called()
            write.assert_not_called()
