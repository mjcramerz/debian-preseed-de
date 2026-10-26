"""Unexecuted failure-injection fixtures for management refresh contracts.

HTTP, package inspection and publication are mocks. Never instantiate the real
Repository or call a package manager, service manager or installed helper.
Repository guidance prohibits executing these fixtures in this checkout.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


class ManagementRefreshFixtures(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/libexec/apt-repo-local'
        self.mod = types.ModuleType('fixture_management_refresh')
        self.mod.__file__ = str(path)
        exec(compile(path.read_bytes(), str(path), 'exec'), self.mod.__dict__)
        temporary = tempfile.TemporaryDirectory(prefix='management-refresh-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Any unexpected subprocess request fails before creating a child.
        self.commands = mock.patch.object(self.mod, 'run', side_effect=AssertionError('unexpected command'))
        self.commands.start()
        self.addCleanup(self.commands.stop)
        self.candidate = {'kind': 'direct', 'source': 'fixture-source',
                          'url': 'https://example.invalid/demo.deb',
                          'token': 'same', 'validators': {'etag': '"same"'}}
        self.record = {'package': 'demo', 'architecture': 'amd64', 'version': '1.0',
                       'upstream_version': '1.0', 'sha256': 'a' * 64,
                       'policy': {'automatic': True, 'url': self.candidate['url'],
                                  'tracking': copy.deepcopy(self.candidate)}}

    def repository(self):
        repository = self.mod.Repository.__new__(self.mod.Repository)
        repository.root = self.root
        repository.inbox = self.root
        repository.architectures = {'amd64'}
        repository.catalog = {'packages': {'demo:amd64': copy.deepcopy(self.record)}}
        repository.discovery = types.SimpleNamespace(memory={}, candidate=mock.Mock(return_value=self.candidate))
        repository.process_inbox = mock.Mock(return_value=0)
        repository.publish = mock.Mock()
        repository.stage = mock.Mock(return_value=self.root / 'owned-stage')
        repository.ingest = mock.Mock(return_value={**self.record, 'version': '1.0+localrepo1'})
        repository.discard = mock.Mock()
        repository.remember_candidate = mock.Mock()
        repository.refresh_vendors = mock.Mock()
        return repository

    def test_xssh_identity_validation_defines_control_character_guards(self):
        for name in ('xssh-send', 'xssh-retrieve'):
            source = (Path(__file__).resolve().parents[1] /
                      'hooks/target/usr/local/bin' / name).read_text(encoding='utf-8')
            self.assertIn("CR=$(printf '\\r')", source)
            self.assertIn("LF=$(printf '\\n')", source)
            self.assertIn('*"$CR"*|*"$LF"*)', source)

    def test_force_download_retains_snapshot_condition_without_not_modified_skip(self):
        for force, expected in ((False, {'If-Match': '"same"', 'If-None-Match': '"same"'}),
                                (True, {'If-Match': '"same"'})):
            with self.subTest(force=force), mock.patch.object(self.mod, 'request',
                    return_value={'status': 200, 'headers': {'etag': '"same"'}}) as request:
                self.mod.retrieve_candidate(self.candidate, self.candidate, self.root / 'owned-part', force=force)
                self.assertEqual(request.call_args.kwargs['headers'], expected)

    def test_force_rejects_changed_representation_or_failed_snapshot_condition(self):
        for response in ({'status': 412, 'headers': {}},
                         {'status': 200, 'headers': {'etag': '"replaced"'}}):
            with self.subTest(response=response), mock.patch.object(self.mod, 'request', return_value=response), \
                    self.assertRaises(self.mod.Error):
                self.mod.retrieve_candidate(self.candidate, self.candidate, self.root / 'owned-part', force=True)

    def test_force_does_not_skip_archive_digest_checks(self):
        package = self.root / 'owned-part'
        package.write_bytes(b'fixture bytes')
        candidate = {**self.candidate, 'sha256': hashlib.sha256(b'other').hexdigest()}
        with mock.patch.object(self.mod, 'request', return_value={'status': 200, 'headers': {'etag': '"same"'}}), \
                self.assertRaisesRegex(self.mod.Error, 'SHA-256'):
            self.mod.retrieve_candidate(candidate, self.candidate, package, force=True)

    def test_force_preserves_backward_metadata_rejection(self):
        record = copy.deepcopy(self.record)
        record['policy']['tracking'].update(token='old', validators={'last_modified': 'Tue, 27 Oct 2026 12:00:00 GMT'})
        candidate = {**self.candidate, 'token': 'new',
                     'validators': {'last_modified': 'Mon, 26 Oct 2026 12:00:00 GMT'}}
        with self.assertRaisesRegex(self.mod.Error, 'backwards'):
            self.mod.Repository.vendor_decision(self.repository(), candidate, record, force=True)

    def refresh(self, repository, *, force, version='1.0', fetch_failure=None):
        # Comparison is mocked too: production uses dpkg, never a host fixture.
        newer = lambda left, right: tuple(map(int, left.split('.'))) > tuple(map(int, right.split('.')))
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(self.mod, 'newer', side_effect=newer))
            fetch = stack.enter_context(mock.patch.object(self.mod, 'retrieve_candidate',
                return_value=copy.deepcopy(self.candidate), side_effect=fetch_failure))
            stack.enter_context(mock.patch.object(self.mod, 'inspect_deb', return_value={
                'Package': 'demo', 'Architecture': 'amd64', 'Version': version}))
            publish_report = stack.enter_context(mock.patch.object(self.mod, 'atomic_bytes'))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            status = repository.refresh(force=force)
            path, data, mode = publish_report.call_args.args
            self.assertEqual(path, self.root / 'state/last-refresh.json')
            self.assertEqual(mode, 0o600)
            report = json.loads(data)
        return status, report, fetch

    def test_normal_refresh_skips_same_candidate_and_force_republishes_new_revision(self):
        repository = self.repository()
        status, report, fetch = self.refresh(repository, force=False)
        self.assertEqual(status, 0)
        fetch.assert_not_called()
        self.assertEqual(report['counts']['current'], 1)
        repository = self.repository()
        status, report, fetch = self.refresh(repository, force=True)
        self.assertEqual(status, 0)
        self.assertTrue(fetch.call_args.kwargs['force'])
        self.assertEqual(repository.stage.call_args.kwargs['policy']['local_revision'], 1)
        self.assertEqual(report['counts']['updated'], 1)
        repository.refresh_vendors.assert_called_once_with(report['results'], force=True)

    def test_force_failure_or_downgrade_preserves_previous_catalog_and_error_result(self):
        for version, failure in (('1.0', self.mod.Error('fixture transport failure')), ('0.9', None)):
            with self.subTest(version=version, failure=type(failure).__name__):
                repository = self.repository()
                before = copy.deepcopy(repository.catalog)
                status, report, _ = self.refresh(repository, force=True, version=version, fetch_failure=failure)
                self.assertEqual(status, 3)
                self.assertEqual(report['counts']['error'], 1)
                self.assertEqual(repository.catalog, before)
                repository.stage.assert_not_called()
                repository.ingest.assert_not_called()
