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
from key_manager import core, gpg, tls

PRIMARY = 'A' * 40
VALID = 'B' * 40
EXPIRED = 'C' * 40
REVOKED = 'D' * 40


class CommandCleanupTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.child = mock.Mock(pid=43210, returncode=None)
        self.child.wait.side_effect = self.finished
        self.popen = self.stack.enter_context(mock.patch.object(
            core.subprocess, 'Popen', return_value=self.child))
        self.handlers = self.stack.enter_context(mock.patch.object(core.signal, 'signal'))
        self.isatty = self.stack.enter_context(mock.patch.object(core.os, 'isatty', return_value=False))
        self.stack.enter_context(mock.patch.object(core.os, 'tcgetpgrp', return_value=12345))
        self.foreground = self.stack.enter_context(mock.patch.object(core.os, 'tcsetpgrp'))
        self.killpg = self.stack.enter_context(mock.patch.object(core.os, 'killpg'))
        self.selector = mock.MagicMock()
        self.selector.__enter__.return_value = self.selector
        self.selector.get_map.return_value = {}
        self.stack.enter_context(mock.patch.object(
            core.selectors, 'DefaultSelector', return_value=self.selector))

    def finished(self, **kwargs):
        self.child.returncode = 0
        return 0

    def assert_handler_restored(self):
        self.assertEqual(self.handlers.call_args_list, [
            mock.call(core.signal.SIGTTOU, core.signal.SIG_IGN),
            mock.call(core.signal.SIGTTOU, self.handlers.return_value),
        ])

    def test_terminal_restore_failure_still_closes_output_and_restores_handler(self):
        self.isatty.return_value = True
        self.foreground.side_effect = [None, OSError('fixture terminal disappeared')]
        with self.assertRaisesRegex(OSError, 'terminal disappeared'):
            core.run(['/fixture/command'], capture=True, interactive=True, env={})
        self.child.wait.assert_called_once()
        self.child.stdout.close.assert_called_once()
        self.assert_handler_restored()
        self.assertEqual(self.foreground.call_args_list, [mock.call(0, 43210), mock.call(0, 12345)])

    def test_cancellation_reap_failure_still_closes_output_and_restores_terminal(self):
        self.isatty.return_value = True
        self.child.wait.side_effect = core.subprocess.TimeoutExpired('/fixture/command', 5)
        with self.assertRaisesRegex(RuntimeError, 'did not exit after cancellation'):
            core.run(['/fixture/command'], capture=True, interactive=True, env={})
        self.assertEqual(self.child.wait.call_count, 2)
        self.killpg.assert_called_with(43210, core.signal.SIGKILL)
        self.child.stdout.close.assert_called_once()
        self.assert_handler_restored()
        self.foreground.assert_called_with(0, 12345)

    def test_failed_reaped_child_never_signals_a_recycled_process_group(self):
        def failed(**kwargs):
            self.child.returncode = 7
            return 7
        self.child.wait.side_effect = failed
        cancel = mock.Mock(side_effect=RuntimeError('fixture cancellation failed'))
        with self.assertRaisesRegex(RuntimeError, 'status 7') as caught:
            core.run(['/fixture/command'], capture=True, env={}, on_cancel=cancel)
        self.killpg.assert_not_called()
        cancel.assert_called_once_with()
        self.assertIn('fixture cancellation failed', caught.exception.__notes__[0])
        self.child.wait.assert_called_once()
        self.child.stdout.close.assert_called_once()
        self.assert_handler_restored()

    def test_spawn_failure_restores_terminal_and_handler(self):
        self.isatty.return_value = True
        self.popen.side_effect = OSError('fixture spawn failed')
        with self.assertRaisesRegex(OSError, 'spawn failed'):
            core.run(['/fixture/command'], capture=True, interactive=True, env={})
        self.foreground.assert_called_once_with(0, 12345)
        self.killpg.assert_not_called()
        self.assert_handler_restored()

    def test_capture_waits_for_readiness_with_the_remaining_deadline(self):
        self.selector.get_map.side_effect = [{1: object()}, {}]
        self.selector.select.return_value = []
        with mock.patch.object(core.time, 'monotonic', side_effect=[10.0, 10.25, 10.5]):
            self.assertEqual(core.run(['/fixture/command'], capture=True, env={}, timeout=300), b'')
        self.selector.select.assert_called_once_with(299.75)
        self.child.wait.assert_called_once_with(timeout=299.5)


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
