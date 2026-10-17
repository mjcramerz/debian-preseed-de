#!/usr/bin/env python3
"""Isolated Aptly publication boundary fixtures."""
from pathlib import Path as _IsolationPath
import sys as _isolation_sys

_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
_isolation_sys.path.insert(0, str(ROOT / 'd-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages'))
SCRIPT = ROOT / 'd-i/forky/hooks/target/usr/local/libexec/aptly-publishing'
LOADER = importlib.machinery.SourceFileLoader('aptly_publishing_fixture', str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
APTLY = importlib.util.module_from_spec(SPEC)
_isolation_sys.modules[LOADER.name] = APTLY
LOADER.exec_module(APTLY)
OBS_LOADER = importlib.machinery.SourceFileLoader(
    'obs_publishing_private_input_fixture', str(SCRIPT.with_name('obs-publishing')))
OBS_SPEC = importlib.util.spec_from_loader(OBS_LOADER.name, OBS_LOADER)
assert OBS_SPEC is not None
OBS = importlib.util.module_from_spec(OBS_SPEC)
_isolation_sys.modules[OBS_LOADER.name] = OBS
OBS_LOADER.exec_module(OBS)


class AptlyPublicReleaseTests(unittest.TestCase):
    def context(self):
        return SimpleNamespace(
            public_base_url='https://aptly.example.test',
            signing_key='A' * 40,
            component='main',
        )

    def test_fetch_reads_only_the_configured_https_origin_and_expected_path(self):
        with mock.patch.object(APTLY, 'checked', return_value='signed release\n200') as command:
            result = APTLY.fetch_public_inrelease(
                self.context(), 'forky', deadline=time.monotonic() + 5)
        self.assertEqual(result, b'signed release')
        argv = command.call_args.args[0]
        self.assertEqual(argv[-1], 'https://aptly.example.test/dists/forky/InRelease')
        self.assertEqual(argv[0:2], ['/usr/bin/curl', '--disable'])
        self.assertIn('--max-time', argv)
        self.assertIn('--max-filesize', argv)
        self.assertNotIn('--location', argv)
        self.assertNotIn('-L', argv)
        self.assertLessEqual(command.call_args.kwargs['timeout'], 5)

    def test_fetch_rejects_redirects_and_oversized_releases(self):
        with mock.patch.object(APTLY, 'checked', return_value='redirect body\n302') as command:
            with self.assertRaisesRegex(APTLY.PublicReleaseError, 'HTTP status 302'):
                APTLY.fetch_public_inrelease(self.context(), 'forky', deadline=time.monotonic() + 5)
        self.assertEqual(command.call_count, 1)
        with mock.patch.object(APTLY, 'PUBLIC_INRELEASE_MAX_BYTES', 8), \
                mock.patch.object(APTLY, 'checked', return_value='x' * 9 + '\n200'):
            with self.assertRaisesRegex(APTLY.PublicReleaseError, 'exceeds its size limit'):
                APTLY.fetch_public_inrelease(self.context(), 'forky', deadline=time.monotonic() + 5)

    def test_transfer_timeout_and_missing_object_are_distinct(self):
        with mock.patch.object(APTLY, 'checked', side_effect=subprocess.TimeoutExpired('curl', 1)):
            with self.assertRaisesRegex(APTLY.PublicReleaseError, 'timed out'):
                APTLY.fetch_public_inrelease(self.context(), 'forky')
        with mock.patch.object(APTLY, 'checked', return_value='not found\n404'):
            self.assertIsNone(APTLY.fetch_public_inrelease(self.context(), 'forky'))

    def test_signed_release_identity_requires_the_managed_fingerprint(self):
        data = b'complete signed InRelease fixture'
        fingerprint = 'A' * 40
        completed = SimpleNamespace(
            returncode=0,
            stdout=f'[GNUPG:] VALIDSIG {fingerprint} 20261017 1 0 4 0 1 8 00 {fingerprint}\n'.encode(),
        )
        with mock.patch.object(APTLY.subprocess, 'run', return_value=completed) as run:
            digest = APTLY.verify_public_inrelease(self.context(), data)
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        self.assertEqual(run.call_args.args[0][-2:], ['--verify', '-'])
        self.assertEqual(run.call_args.kwargs['input'], data)

        foreign = SimpleNamespace(
            returncode=0,
            stdout=(f'[GNUPG:] VALIDSIG {"B" * 40} 20261017 1 0 4 0 1 8 00\n').encode(),
        )
        with mock.patch.object(APTLY.subprocess, 'run', return_value=foreign):
            with self.assertRaisesRegex(APTLY.PublicReleaseError, 'managed repository key'):
                APTLY.verify_public_inrelease(self.context(), data)

    def signed_release(self, version='expected-snapshot', extra=''):
        return (
            '-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n'
            'Suite: forky\nCodename: forky\nComponents: main\n'
            f'Version: {version}\n{extra}'
            '-----BEGIN PGP SIGNATURE-----\n\nZmFrZQ==\n'
            '-----END PGP SIGNATURE-----\n'
        ).encode()

    def test_valid_signature_for_a_different_snapshot_is_not_publication_success(self):
        fingerprint = 'A' * 40
        status = SimpleNamespace(returncode=0, stdout=f'[GNUPG:] VALIDSIG {fingerprint}\n'.encode())
        with mock.patch.object(APTLY.subprocess, 'run', return_value=status):
            with self.assertRaisesRegex(APTLY.PublicReleaseError, 'expected snapshot'):
                APTLY.verify_public_inrelease(
                    self.context(), self.signed_release('old-snapshot'),
                    expected_snapshot='expected-snapshot', distribution='forky')
            digest = APTLY.verify_public_inrelease(
                self.context(), self.signed_release(),
                expected_snapshot='expected-snapshot', distribution='forky')
        self.assertEqual(digest, hashlib.sha256(self.signed_release()).hexdigest())

    def test_release_parser_rejects_unsigned_prefix_duplicate_identity_and_trailing_data(self):
        valid = self.signed_release()
        for invalid in (
            b'Version: expected-snapshot\n' + valid,
            valid + b'Version: expected-snapshot\n',
            self.signed_release(extra='Version: different-snapshot\n'),
            valid + valid,
        ):
            with self.subTest(data=invalid), self.assertRaises(APTLY.PublicReleaseError):
                APTLY.signed_release_fields(invalid)

    def test_publication_lock_is_private_and_rejects_a_concurrent_writer(self):
        with tempfile.TemporaryDirectory(prefix='aptly-publication-') as temporary:
            root = Path(temporary)
            context = SimpleNamespace(state_dir=root)
            with APTLY.local_publication_lock(context):
                lock = root / '.publication.lock'
                self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
                with mock.patch.object(APTLY, 'PUBLICATION_LOCK_TIMEOUT_SECONDS', 0):
                    with self.assertRaisesRegex(APTLY.PublishingError, 'another managed Aptly'):
                        with APTLY.local_publication_lock(context):
                            self.fail('second publication acquired the active lock')


class AptlyReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='aptly-receipt-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.context = SimpleNamespace(
            state_dir=self.root, config=self.root / 'aptly.conf', distributions=('forky',),
            endpoint_name='r2', publish_target='s3:r2:', public_base_url='https://aptly.example.test',
            signing_key='A' * 40, component='main',
        )
        self.snapshot = 'local-forky-20261017T120000Z-0123456789ab'
        self.receipt = dict(
            schema=1, status='unknown', distribution='forky', snapshot=self.snapshot,
            target='s3:r2:', public_base_url=self.context.public_base_url,
            signing_key=self.context.signing_key, component='main',
        )

    def test_unresolved_receipt_blocks_another_mutation_and_remains_private(self):
        with APTLY.local_publication_lock(self.context) as state:
            APTLY.save_publication_receipt(state, self.receipt)
            with self.assertRaisesRegex(APTLY.PublishingError, '--reconcile forky'):
                APTLY.require_reconciled_publication(self.context, state)
            self.assertEqual(APTLY.publication_receipt(self.context, state), self.receipt)
        self.assertEqual(stat.S_IMODE((self.root / APTLY.PUBLICATION_RECEIPT).stat().st_mode), 0o600)

    def test_receipt_is_not_reused_with_a_changed_destination(self):
        with APTLY.local_publication_lock(self.context) as state:
            APTLY.save_publication_receipt(state, self.receipt)
            self.context.public_base_url = 'https://other.example.test'
            with self.assertRaisesRegex(APTLY.PublishingError, 'differs from managed policy'):
                APTLY.publication_receipt(self.context, state)

    def test_reconciliation_never_mutates_and_requires_both_local_and_public_identity(self):
        local = dict(Distribution='forky', Version=self.snapshot, SourceKind='snapshot',
                     Sources=[dict(Component='main', Name=self.snapshot)])
        with APTLY.local_publication_lock(self.context) as state:
            APTLY.save_publication_receipt(state, self.receipt)
            with mock.patch.object(APTLY, 'require_root_owned_executable'), \
                    mock.patch.object(APTLY, 'fetch_public_inrelease', return_value=b'public release'), \
                    mock.patch.object(APTLY, 'verify_public_inrelease', return_value='f' * 64) as verify, \
                    mock.patch.object(APTLY, 'checked', return_value=json.dumps(local)) as command, \
                    mock.patch.object(APTLY, 'run_checked') as mutation:
                APTLY.verify_publication(self.context, state, self.receipt)
            self.assertEqual(verify.call_args.kwargs['expected_snapshot'], self.snapshot)
            self.assertEqual(command.call_args.args[0][2:5], ['publish', 'show', '-json'])
            mutation.assert_not_called()
            record = APTLY.publication_receipt(self.context, state)
            self.assertEqual(record['status'], 'verified')
            self.assertEqual(record['inrelease_sha256'], 'f' * 64)

            record['status'] = 'unknown'
            APTLY.save_publication_receipt(state, record)
            local['Sources'][0]['Name'] = 'another-snapshot'
            with mock.patch.object(APTLY, 'require_root_owned_executable'), \
                    mock.patch.object(APTLY, 'fetch_public_inrelease', return_value=b'public release'), \
                    mock.patch.object(APTLY, 'verify_public_inrelease', return_value='f' * 64), \
                    mock.patch.object(APTLY, 'checked', return_value=json.dumps(local)):
                with self.assertRaisesRegex(APTLY.PublicReleaseError, 'local Aptly state'):
                    APTLY.verify_publication(self.context, state, record)
            self.assertEqual(APTLY.publication_receipt(self.context, state)['status'], 'unknown')

    def test_remote_timeout_retains_the_attempt_identity_and_blocks_retry(self):
        package = self.root / 'fixture.deb'
        package.write_bytes(b'fixture package')
        attempts = []
        def command(argv, label, **kwargs):
            if 'publish' not in argv:
                return
            receipt = json.loads((self.root / APTLY.PUBLICATION_RECEIPT).read_bytes())
            self.assertEqual(receipt['status'], 'attempting')
            self.assertIn('-version=' + receipt['snapshot'], argv)
            self.assertIn('lock_fd', kwargs)
            attempts.append(receipt['snapshot'])
            raise APTLY.PublishingError('fixture: timeout after remote commit')
        with mock.patch.object(APTLY, 'load_aptly_context', return_value=self.context), \
                mock.patch.object(APTLY, 'require_root_owned_executable'), \
                mock.patch.object(APTLY, 'require_aptly_signing_key'), \
                mock.patch.object(APTLY, 'require_signed_source_descriptors'), \
                mock.patch.object(APTLY, 'aptly_environment_with_credentials', return_value={}), \
                mock.patch.object(APTLY.subprocess, 'run', return_value=SimpleNamespace(returncode=1)), \
                mock.patch.object(APTLY, 'fetch_public_inrelease', return_value=None), \
                mock.patch.object(APTLY, 'run_checked', side_effect=command):
            with self.assertRaises(APTLY.PublicationUnknown):
                APTLY.aptly_publish_local(['forky', str(package)])
            with self.assertRaisesRegex(APTLY.PublicationUnknown, '--reconcile forky'):
                APTLY.aptly_publish_local(['forky', str(package)])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(json.loads((self.root / APTLY.PUBLICATION_RECEIPT).read_bytes())['snapshot'], attempts[0])

    def test_malformed_receipt_status_is_a_controlled_failure(self):
        with APTLY.local_publication_lock(self.context) as state:
            self.receipt['status'] = []
            APTLY.save_publication_receipt(state, self.receipt)
            with self.assertRaises(APTLY.PublishingError):
                APTLY.publication_receipt(self.context, state)

    def test_command_timeout_keeps_the_lock_inherited_and_has_a_finite_reap(self):
        child = mock.Mock(pid=12345, returncode=None)
        child.wait.side_effect = [subprocess.TimeoutExpired('fixture', 1), 0]
        with mock.patch.object(APTLY.subprocess, 'Popen', return_value=child) as start:
            with self.assertRaisesRegex(APTLY.PublishingError, 'operation deadline'):
                APTLY.run_checked(['/fixture/aptly'], 'fixture publication', timeout=1, lock_fd=7)
        self.assertEqual(start.call_args.kwargs['pass_fds'], (7,))
        self.assertNotIn('process_group', start.call_args.kwargs)
        self.assertNotIn('start_new_session', start.call_args.kwargs)
        child.kill.assert_called_once_with()
        self.assertEqual(child.wait.call_args_list, [mock.call(timeout=1), mock.call(timeout=5)])

    def test_unproved_command_termination_is_unknown(self):
        child = mock.Mock(pid=12345, returncode=None)
        child.wait.side_effect = subprocess.TimeoutExpired('fixture', 1)
        with mock.patch.object(APTLY.subprocess, 'Popen', return_value=child):
            with self.assertRaisesRegex(APTLY.PublicationUnknown, 'termination is unknown'):
                APTLY.run_checked(['/fixture/aptly'], 'fixture publication', timeout=1)

    def test_operation_deadline_is_not_reset_for_each_native_command(self):
        with mock.patch.object(APTLY.time, 'monotonic', return_value=90):
            self.assertEqual(APTLY.remaining_timeout(100, 3600), 10)
        with mock.patch.object(APTLY.time, 'monotonic', return_value=100):
            with self.assertRaisesRegex(APTLY.PublishingError, 'deadline expired'):
                APTLY.remaining_timeout(100, 3600)

    def test_fifo_and_hardlinked_private_inputs_are_rejected_before_reading(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo, 0o600)
        for publisher in (APTLY, OBS):
            with self.subTest(publisher=publisher.__name__), self.assertRaisesRegex(publisher.PublishingError, 'regular'):
                publisher.require_private_regular_file(fifo, 'fixture', os.getuid(), 4096)
        secret = self.root / 'secret'
        secret.write_bytes(b'fixture')
        secret.chmod(0o600)
        os.link(secret, self.root / 'hardlink')
        for publisher in (APTLY, OBS):
            with self.subTest(publisher=publisher.__name__), self.assertRaisesRegex(publisher.PublishingError, 'hard links'):
                publisher.require_private_regular_file(secret, 'fixture', os.getuid(), 4096)


if __name__ == '__main__':
    unittest.main()
