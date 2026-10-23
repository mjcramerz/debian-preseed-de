"""Optional URLhaus credential publication and redaction in the isolated image."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation
sys.path.pop(0)
require_test_isolation()

import configparser
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
import signal
import stat
import tempfile
import types
import unittest
from unittest import mock

from payload_fixture import read_text

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'


def module(path):
    value = types.ModuleType('urlhaus_fixture')
    exec(compile(read_text(path), str(path), 'exec'), value.__dict__)
    return value


class URLhausConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.configure = module(SEED / 'scripts/desktop/fangfrisch-configure.py')
        self.runtime = module(TARGET / 'usr/local/libexec/clamav-fangfrisch')
        temporary = tempfile.TemporaryDirectory(prefix='installer-fangfrisch.', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.stage = Path(temporary.name)
        self.output = self.stage / 'etc'
        self.output.mkdir(mode=0o700)
        self.destination = self.output / 'fangfrisch.conf'
        self.configure.DESTINATION = self.destination
        self.runtime.CONFIG = self.destination
        self.group = types.SimpleNamespace(gr_gid=os.getegid())
        self.patcher = mock.patch.object(self.configure.grp, 'getgrnam', return_value=self.group)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        (self.stage / 'fangfrisch.conf').write_text(read_text(TARGET / 'etc/fangfrisch.conf'))
        (self.stage / 'fangfrisch.conf').chmod(0o600)

    def publish(self, key):
        (self.stage / 'auth-key').write_text(key)
        (self.stage / 'auth-key').chmod(0o600)
        capture = io.StringIO()
        with redirect_stdout(capture):
            self.configure.configure(self.stage)
        if key:
            self.assertNotIn(key, capture.getvalue())
        return capture.getvalue()

    def test_missing_or_empty_key_disables_only_urlhaus(self):
        self.assertIn('disabled-no-key', self.publish(''))
        config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
        config.read(self.destination)
        self.assertFalse(config.getboolean('urlhaus', 'enabled'))
        self.assertTrue(config.getboolean('sanesecurity', 'enabled'))
        self.assertEqual(self.runtime.auth_key(), b'')
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o640)
        self.assertFalse(list(self.output.glob('.fangfrisch-recovery.*')))

    def test_nonempty_key_is_interpolated_into_the_supported_https_feed_privately(self):
        key = 'Fixture-0123456789._~-'
        self.assertIn('configured', self.publish(key))
        config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
        config.read(self.destination)
        self.assertEqual(config.get('urlhaus', 'url_urlhaus'),
                         'https://urlhaus-api.abuse.ch/v2/files/exports/' + key + '/urlhaus_clamav.ndb')
        self.assertEqual(self.runtime.auth_key(), key.encode())
        self.assertEqual(self.destination.stat().st_uid, 0)
        self.assertEqual(self.destination.stat().st_gid, os.getegid())

    def test_invalid_key_and_replaced_private_input_do_not_publish(self):
        for key in ('bad/key', 'bad\nkey', 'bad$key', 'X' * 257):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.publish(key)
            self.assertFalse(self.destination.exists())
        key_file = self.stage / 'auth-key'
        key_file.unlink()
        key_file.symlink_to(self.stage / 'fangfrisch.conf')
        with self.assertRaises(OSError):
            self.configure.configure(self.stage)
        self.assertFalse(self.destination.exists())

    def test_unsafe_configuration_metadata_and_feed_are_rejected(self):
        self.publish('Fixture-key')
        self.destination.chmod(0o644)
        with self.assertRaises(self.runtime.UpdateFailure):
            self.runtime.auth_key()
        self.destination.chmod(0o640)
        text = self.destination.read_text().replace('https://urlhaus-api.abuse.ch/', 'http://invalid/')
        self.destination.write_text(text)
        with self.assertRaises(self.runtime.UpdateFailure):
            self.runtime.auth_key()

    def test_uncertain_publication_retains_exact_previous_bytes_metadata_and_private_evidence(self):
        self.destination.write_bytes(b'previous private configuration\n')
        self.destination.chmod(0o640)
        previous = self.destination.stat()
        original_sync = self.configure.sync_directory
        def fail_after_rename(path):
            if path == self.output and self.destination.read_bytes() != b'previous private configuration\n':
                raise OSError('fixture fsync failure')
            original_sync(path)
        with mock.patch.object(self.configure, 'sync_directory', side_effect=fail_after_rename):
            with self.assertRaises(self.configure.PublicationFailure) as error:
                self.publish('Fixture-new-key')
        recovery = error.exception.recovery
        self.assertTrue(error.exception.attempted)
        self.assertEqual(stat.S_IMODE(recovery.stat().st_mode), 0o700)
        self.assertEqual((recovery / 'previous').read_bytes(), b'previous private configuration\n')
        self.assertEqual(stat.S_IMODE((recovery / 'previous').stat().st_mode), 0o600)
        receipt = json.loads((recovery / 'state.json').read_text())
        self.assertTrue(receipt['previous_exists'])
        self.assertEqual(receipt['previous_gid'], previous.st_gid)
        self.assertEqual(receipt['previous_mode'], 0o640)

    def test_identity_replacement_before_publication_preserves_the_replacement(self):
        self.destination.write_bytes(b'previous\n')
        self.destination.chmod(0o640)
        original_sync = self.configure.sync_directory
        replaced = False
        def replace_during_staging(path):
            nonlocal replaced
            original_sync(path)
            if path == self.output and not replaced:
                candidate = self.output / 'concurrent-root-writer'
                candidate.write_bytes(b'concurrent replacement\n')
                candidate.chmod(0o640)
                candidate.replace(self.destination)
                replaced = True
        with mock.patch.object(self.configure, 'sync_directory', side_effect=replace_during_staging):
            with self.assertRaises(self.configure.PublicationFailure) as error:
                self.publish('Fixture-key')
        self.assertFalse(error.exception.attempted)
        self.assertEqual(self.destination.read_bytes(), b'concurrent replacement\n')
        self.assertEqual((error.exception.recovery / 'previous').read_bytes(), b'previous\n')


class URLhausLogRedactionTests(unittest.TestCase):
    def setUp(self):
        self.runtime = module(TARGET / 'usr/local/libexec/clamav-fangfrisch')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.record = self.root / 'record.json'
        self.control = self.root / 'control.json'
        self.delegate = self.root / 'fangfrisch'
        self.delegate.write_text('#!' + sys.executable + ' -I\n' +
            'from pathlib import Path\nimport json, os, sys, time\n' +
            f'control = json.loads(Path({str(self.control)!r}).read_text())\n' +
            f'Path({str(self.record)!r}).write_text(json.dumps([sys.argv[1:], dict(os.environ)]))\n' +
            'for fragment in control.get("fragments", []):\n' +
            '    os.write(2, fragment.encode())\n    time.sleep(0.01)\n' +
            'if control.get("sleep"):\n    time.sleep(30)\n' +
            'sys.exit(control.get("status", 0))\n')
        self.delegate.chmod(0o700)
        self.runtime.DELEGATE = str(self.delegate)
        self.runtime.CONFIG = self.root / 'private-config'
        for sig in (signal.SIGTERM, signal.SIGINT):
            self.addCleanup(signal.signal, sig, signal.getsignal(sig))

    def invoke(self, fragments=(), status=0, sleep=False):
        self.control.write_text(json.dumps({'fragments': fragments, 'status': status, 'sleep': sleep}))
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            result = self.runtime.run('refresh', b'Fixture-Current-Key')
        return result, output.getvalue()

    def test_chunked_secret_and_rotated_url_keys_are_redacted_and_status_is_preserved(self):
        result, output = self.invoke(['download https://urlhaus-api.abuse.ch/v2/files/exports/Fixture-',
            'Current-Key/urlhaus_clamav.ndb: 403 Forbidden\n',
            'old /v2/files/exports/Fixture-Rotated-Key/urlhaus_clamav.ndb\n',
            'raw Fixture-Current-Key without final newline'], status=7)
        self.assertEqual(result, 7)
        self.assertIn('403 Forbidden', output)
        self.assertNotIn('Fixture-Current-Key', output)
        self.assertNotIn('Fixture-Rotated-Key', output)
        argv, environment = json.loads(self.record.read_text())
        self.assertEqual(argv, ['--conf', str(self.runtime.CONFIG), 'refresh'])
        self.assertEqual(set(environment), {'PATH', 'HOME', 'LC_ALL'})
        self.assertNotIn('Fixture-Current-Key', json.dumps([argv, environment]))

    def test_streaming_and_final_wait_share_the_deadline(self):
        self.runtime.OPERATION_SECONDS = 0.3
        with self.assertRaises(self.runtime.UpdateFailure) as error:
            self.invoke(sleep=True)
        self.assertEqual(error.exception.status, 124)

    def test_logged_provider_failure_cannot_be_reported_as_success_when_package_returns_zero(self):
        result, output = self.invoke(['ERROR: https://urlhaus-api.abuse.ch/v2/files/exports/',
            'Fixture-Current-Key/urlhaus_clamav.ndb download failed: 403 Forbidden\n'], status=0)
        self.assertEqual(result, 1)
        self.assertIn('403 Forbidden', output)
        self.assertIn('reason=provider-error', output)
        self.assertNotIn('Fixture-Current-Key', output)

    def test_output_limits_reject_before_printing_an_unterminated_secret(self):
        self.runtime.MAX_LINE = 32
        with self.assertRaises(self.runtime.UpdateFailure) as error:
            self.invoke(['Fixture-Current-Key' * 10])
        self.assertEqual(error.exception.reason, 'line-limit')

    def test_unproven_cleanup_has_a_distinct_unknown_status(self):
        self.runtime.OPERATION_SECONDS = 0.3
        original = self.runtime.cleanup
        def unproven(process):
            original(process)
            return False
        with mock.patch.object(self.runtime, 'cleanup', side_effect=unproven):
            with self.assertRaises(self.runtime.UpdateFailure) as error:
                self.invoke(sleep=True)
        self.assertEqual(error.exception.status, 125)

    def test_public_adapter_preserves_unknown_and_cancellation_without_raw_exception_text(self):
        user = types.SimpleNamespace(pw_uid=12345)
        for failure, expected in ((self.runtime.UpdateFailure('cleanup-outcome-unknown', 125), 125),
                                  (self.runtime.UpdateFailure('cancelled', 143), 143),
                                  (ValueError('Fixture-Current-Key'), 1)):
            output = io.StringIO()
            with mock.patch.object(self.runtime.sys, 'argv', ['helper', 'refresh']), \
                 mock.patch.object(self.runtime.os, 'geteuid', return_value=12345), \
                 mock.patch.object(self.runtime.pwd, 'getpwnam', return_value=user), \
                 mock.patch.object(self.runtime, 'auth_key', return_value=b'Fixture-Current-Key'), \
                 mock.patch.object(self.runtime, 'run', side_effect=failure), redirect_stderr(output):
                self.assertEqual(self.runtime.main(), expected)
            self.assertNotIn('Fixture-Current-Key', output.getvalue())
