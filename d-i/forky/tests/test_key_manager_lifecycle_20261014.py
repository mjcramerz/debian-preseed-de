"""GPG expiry and TLS export regressions with native commands replaced by spies."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

LIB = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/lib/python3.14/dist-packages'
_isolation_sys.path.insert(0, str(LIB))
from key_manager import gpg, tls

PRIMARY = 'A' * 40
VALID = 'B' * 40
EXPIRED = 'C' * 40
REVOKED = 'D' * 40


def listing(subkeys=()):
    lines = ['pub:u:', 'fpr:::::::::' + PRIMARY + ':']
    for validity, fingerprint in subkeys:
        lines.extend(['sub:' + validity + ':', 'fpr:::::::::' + fingerprint + ':'])
    return ('\n'.join(lines) + '\n').encode()


class GPGExpiryTests(unittest.TestCase):
    def manager(self, data):
        manager = object.__new__(gpg.GPG)
        manager.allowed = mock.Mock()
        manager.select_key = mock.Mock(return_value=PRIMARY)
        manager.command = mock.Mock(return_value=data)
        return manager

    def test_primary_and_expired_subkeys_change_without_revoked_subkeys(self):
        manager = self.manager(listing((('u', VALID), ('e', EXPIRED), ('r', REVOKED))))
        with mock.patch.object(gpg, 'prompt', return_value='2y'):
            manager.expiry()
        self.assertEqual(manager.command.call_args_list, [
            mock.call(['--with-colons', '--with-fingerprint', '--list-keys', PRIMARY], capture=True),
            mock.call(['--quick-set-expire', PRIMARY, '2y']),
            mock.call(['--quick-set-expire', PRIMARY, '2y', VALID, EXPIRED]),
        ])

    def test_primary_without_subkeys_has_no_subkey_mutation(self):
        manager = self.manager(listing())
        with mock.patch.object(gpg, 'prompt', return_value='0'):
            manager.expiry()
        self.assertEqual(manager.command.call_args_list[-1],
                         mock.call(['--quick-set-expire', PRIMARY, '0']))
        self.assertEqual(manager.command.call_count, 2)

    def test_primary_failure_stops_before_subkey_mutation(self):
        manager = self.manager(listing((('u', VALID),)))
        manager.command.side_effect = [listing((('u', VALID),)), RuntimeError('fixture failure')]
        with mock.patch.object(gpg, 'prompt', return_value='2y'), self.assertRaises(RuntimeError):
            manager.expiry()
        self.assertEqual(manager.command.call_count, 2)

    def test_invalid_subkey_fingerprint_fails_before_any_mutation(self):
        manager = self.manager(listing((('u', 'invalid'),)))
        with mock.patch.object(gpg, 'prompt', return_value='2y'), self.assertRaises(ValueError):
            manager.expiry()
        self.assertEqual(manager.command.call_count, 1)


class TLSTraditionalExportTests(unittest.TestCase):
    def test_imported_rsa2048_and_ec_export_but_eddsa_is_rejected(self):
        for kind in ('RSA 2048', 'RSA 4096', 'ECDSA P-256', 'Ed25519'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='key-manager-fixture-') as directory:
                work = Path(directory)
                manager = tls.TLS(mock.Mock(), mock.Mock(), 1000)
                manager.select = mock.Mock(return_value='identity')
                manager.tree.read.return_value = b'fixture-certificate'

                def native_spy(argv):
                    self.assertEqual(argv[0:2], [tls.OPENSSL, 'pkey'])
                    self.assertIn('-traditional', argv)
                    self.assertEqual(Path(argv[argv.index('-out') + 1]), work / 'export.key')
                    output = work / 'export.key'
                    output.write_bytes(b'fixture-private-key')
                    output.chmod(0o600)

                with mock.patch.object(tls, 'choose', return_value='Traditional RSA / EC PEM'), \
                        mock.patch.object(tls, 'confirm', return_value=True), \
                        mock.patch.object(tls, 'stage', return_value=contextlib.nullcontext(work)), \
                        mock.patch.object(tls, 'private_file', return_value=b'fixture-private-key'), \
                        mock.patch.object(tls, 'certificate_key_type', return_value=kind), \
                        mock.patch.object(tls, 'run', side_effect=native_spy) as native, \
                        mock.patch.object(tls, 'publish') as publish:
                    if kind == 'Ed25519':
                        with self.assertRaises(ValueError):
                            manager.export_private()
                        native.assert_not_called()
                        publish.assert_not_called()
                    else:
                        manager.export_private()
                        native.assert_called_once()
                        publish.assert_called_once_with(manager.exports,
                            {'identity.traditional.pem': b'fixture-private-key'})


if __name__ == '__main__':
    unittest.main()
