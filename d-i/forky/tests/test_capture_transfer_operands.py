"""Fixture recorders and scp argv capture; never contacts a desktop or network."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'


class CaptureTransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='capture-transfer-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.root),
                    'USER': 'fixture', 'LC_ALL': 'C', 'FIXTURE_ARGV': str(self.root / 'argv')}
        scp = self.bin / 'scp'
        scp.write_text('#!/usr/bin/python3 -IB\nimport json,os,sys\n'
                       'open(os.environ["FIXTURE_ARGV"],"w").write(json.dumps(sys.argv[1:]))\n')
        scp.chmod(0o755)

    def test_dns_ipv4_ipv6_scoped_ipv6_and_colon_dash_space_local_paths(self):
        for host in ('example.test', '192.0.2.1', '2001:db8::1', 'fe80::1%enp1s0'):
            for local in ('host:file', '-leading', 'space name'):
                for action in ('send', 'retrieve'):
                    with self.subTest(host=host, local=local, action=action):
                        (self.root / local).touch()
                        option = '--dest-ip' if action == 'send' else '--remote-ip'
                        operands = [local, '/remote/file'] if action == 'send' else ['/remote/file', local]
                        result = subprocess.run(['/bin/sh', str(TARGET / 'usr/local/bin' / ('xssh-' + action)),
                                                 option, host, '--port', '22', '--', *operands],
                                                cwd=self.root, env=self.env, capture_output=True, timeout=5)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        argv = json.loads((self.root / 'argv').read_text())
                        remote = 'fixture@' + ('[' + host + ']' if ':' in host else host) + ':/remote/file'
                        self.assertEqual(argv, ['-r', '-P', '22', *(['./' + local, remote] if action == 'send'
                                                                 else [remote, './' + local])])

    def test_zero_recorder_requires_nonempty_artifact(self):
        source = (TARGET / 'usr/local/bin/labwc-capture.tmpl').read_text()
        self.assertTrue(source.startswith('#!/usr/bin/python3 -IB'))
        for contract in ('def recording_worker', 'path.is_file()', 'path.stat().st_size > 0',
                         'Screen recording failed', 'return worker_status'):
            self.assertIn(contract, source)

    def test_intentional_stop_still_saves_a_valid_artifact(self):
        source = (TARGET / 'usr/local/bin/labwc-capture.tmpl').read_text()
        for contract in ('process.send_signal(signal.SIGINT)', 'signal.signal(signal.SIGTERM',
                         'wf-recorder', 'ffprobe'):
            self.assertIn(contract, source)


class ForegroundCancellationFixtures(unittest.TestCase):
    """Unexecuted: process operations are replaced before the helper is called."""

    def test_signal_denial_and_missing_wait_identity_report_unknown_termination(self):
        source = TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_desktop_runtime.py'
        runtime = ModuleType('foreground_cancel_fixture')
        exec(compile(source.read_bytes(), str(source), 'exec'), runtime.__dict__)
        for failure in ('signal', 'identity', 'wait'):
            child = SimpleNamespace(pid=12345, wait=mock.Mock(return_value=0))
            kill = mock.Mock()
            identity = mock.Mock(return_value=object())
            if failure == 'signal':
                kill.side_effect = PermissionError('fixture signal denied')
            elif failure == 'identity':
                identity.side_effect = ChildProcessError('fixture identity unavailable')
            else:
                child.wait.side_effect = subprocess.TimeoutExpired(['fixture'], 2)
            with self.subTest(failure=failure), mock.patch.object(runtime.os, 'killpg', kill), \
                    mock.patch.object(runtime.os, 'waitid', identity), \
                    mock.patch.object(runtime.time, 'monotonic', return_value=0):
                with self.assertRaisesRegex(runtime.HelperError, 'outcome-unknown; retain owned state'):
                    runtime._cancel(child)
            if failure == 'identity':
                self.assertEqual(kill.call_args_list, [mock.call(child.pid, signal.SIGTERM)])
            if failure == 'wait':
                self.assertEqual(kill.call_args_list, [mock.call(child.pid, signal.SIGTERM),
                                                       mock.call(child.pid, signal.SIGKILL)])
                self.assertEqual(child.wait.call_args.kwargs['timeout'], 2)


class SavedCaptureFixtures(unittest.TestCase):
    """Unexecuted: all filesystem capabilities and subprocesses are fixtures."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='saved-capture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'home'
        self.home.mkdir(mode=0o700)
        self.state = self.root / 'runtime/capture'
        self.state.mkdir(parents=True, mode=0o700)
        (self.home / 'Pictures/Screenshots').mkdir(parents=True, mode=0o700)
        (self.home / 'Videos/Recordings').mkdir(parents=True, mode=0o700)
        fs = ModuleType('capture_fixture_fs')
        fs_source = TARGET / 'usr/local/lib/python3.14/dist-packages/managed_workflows/fs.py'
        exec(compile(fs_source.read_bytes(), str(fs_source), 'exec'), fs.__dict__)

        def owned_directory(path, *, readable=True):
            # Replace only the absolute-root acquisition boundary. Every
            # descriptor traversal below it remains the production Tree code.
            path = Path(path)
            if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(self.root):
                raise AssertionError('fixture attempted filesystem access outside its tree')
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                for name in path.relative_to(self.root).parts:
                    new = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                                  os.O_CLOEXEC, dir_fd=fd)
                    os.close(fd)
                    fd = new
                return fd
            except BaseException:
                os.close(fd)
                raise

        fs.open_directory = owned_directory
        package = ModuleType('managed_workflows')
        package.__path__ = []
        runtime = ModuleType('labwc_desktop_runtime')
        runtime.HelperError = type('FixtureHelperError', (OSError,), {})
        runtime.run = mock.Mock(side_effect=AssertionError('unexpected external execution'))
        path = TARGET / 'usr/local/bin/labwc-capture.tmpl'
        helper = ModuleType('saved_capture_fixture')
        helper.__file__ = str(path)
        with mock.patch.dict(sys.modules, {'managed_workflows': package,
                                          'managed_workflows.fs': fs,
                                          'labwc_desktop_runtime': runtime}):
            exec(compile(path.read_bytes(), str(path), 'exec'), helper.__dict__)
        helper.HOME = self.home
        helper.STATE_DIR = self.state
        helper.SCREENSHOT_DIR = self.home / 'Pictures/Screenshots'
        helper.RECORDING_DIR = self.home / 'Videos/Recordings'
        helper.DESKTOP_UID = os.getuid()
        self.helper = helper
        self.image = helper.SCREENSHOT_DIR / 'Screenshot_2026-10-30_03-00-00.png'
        self.image.write_bytes(helper.PNG_HEADER + b'owned fixture image')
        self.image.chmod(0o600)

    def test_replacement_symlink_hardlink_and_content_change_never_reach_consumer(self):
        helper = self.helper
        for alteration in ('replace', 'symlink', 'hardlink', 'modify'):
            with self.subTest(alteration=alteration):
                self.image.unlink(missing_ok=True)
                self.image.write_bytes(helper.PNG_HEADER + b'owned fixture image')
                self.image.chmod(0o600)
                helper.remember_capture(self.image, 'image')
                other = self.image.with_name('other-' + alteration + '.png')
                if alteration == 'modify':
                    self.image.write_bytes(helper.PNG_HEADER + b'changed')
                else:
                    self.image.rename(other)
                    if alteration == 'replace':
                        self.image.write_bytes(helper.PNG_HEADER + b'replacement')
                        self.image.chmod(0o600)
                    elif alteration == 'symlink':
                        self.image.symlink_to(other.name)
                    else:
                        os.link(other, self.image)
                with self.assertRaises((helper.CaptureError, OSError, ValueError)):
                    with helper.saved_capture('image'):
                        self.fail('replaced capture was accepted')

    def test_ocr_consumes_private_snapshot_and_propagates_decoder_result(self):
        helper = self.helper
        helper.remember_capture(self.image, 'image')
        original = self.image.read_bytes()
        snapshots = []
        def decoder(argv, **kwargs):
            self.assertEqual(argv[0], helper.OCR)
            snapshot = Path(argv[1])
            self.assertTrue(snapshot.is_relative_to(self.state))
            self.assertNotEqual(snapshot, self.image)
            self.assertEqual(snapshot.read_bytes(), original)
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 120)
            snapshots.append(snapshot)
            return subprocess.CompletedProcess(argv, 7)
        with mock.patch.object(helper, 'require_command'), mock.patch.object(helper, 'run', side_effect=decoder):
            self.assertEqual(helper.recognize_capture(last=True), 7)
        self.assertEqual(self.image.read_bytes(), original)
        self.assertTrue(snapshots)
        self.assertTrue(all(not path.exists() for path in snapshots))

    def test_concurrent_history_writers_keep_previous_state_under_one_lock(self):
        helper = self.helper
        helper.remember_capture(self.image, 'image')
        before = (self.state / helper.HISTORY_NAME).read_bytes()
        with helper.Tree(self.state, uid=os.getuid(), private=True) as tree:
            with helper.history_lock(tree):
                with self.assertRaisesRegex(helper.CaptureError, 'busy'):
                    helper.remember_capture(self.image, 'image')
        self.assertEqual((self.state / helper.HISTORY_NAME).read_bytes(), before)

    def test_empty_successful_producer_cannot_publish_or_claim_a_saved_screenshot(self):
        helper = self.helper
        with mock.patch.object(helper, 'require_wayland'), mock.patch.object(helper, 'require_command'), \
                mock.patch.object(helper, 'run', return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(helper, 'track_saved_capture') as track:
            with self.assertRaises(helper.CaptureError):
                helper.capture_full()
            track.assert_not_called()

    def test_unhashable_or_out_of_tree_history_is_rejected_as_data(self):
        helper = self.helper
        helper.remember_capture(self.image, 'image')
        path = self.state / helper.HISTORY_NAME
        original = path.read_bytes()
        for bad_last in ([], {}, None):
            value = json.loads(original)
            value['last'] = bad_last
            path.write_text(json.dumps(value))
            with helper.Tree(self.state, uid=os.getuid(), private=True) as tree:
                with self.assertRaises(helper.CaptureError):
                    helper.read_history(tree)
        path.write_bytes(original)
        value = json.loads(original)
        value['items']['image']['name'] = '../../outside.png'
        path.write_text(json.dumps(value))
        with helper.Tree(self.state, uid=os.getuid(), private=True) as tree:
            with self.assertRaises(helper.CaptureError):
                helper.read_history(tree)

    def test_unconfirmed_decoder_termination_retains_the_private_snapshot(self):
        helper = self.helper
        helper.remember_capture(self.image, 'image')
        with mock.patch.object(helper, 'require_command'), \
                mock.patch.object(helper, 'run', side_effect=helper.desktop_runtime.HelperError('fixture termination uncertain')):
            with self.assertRaisesRegex(helper.CaptureOutcomeUnknown, 'retained input'):
                helper.recognize_capture(last=True)
        retained = list(self.state.glob('ocr-source.*/Screenshot.png'))
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), self.image.read_bytes())

    def test_private_runtime_socket_modes_do_not_hide_capture_actions(self):
        helper = self.helper
        helper.RUNTIME = self.root / 'runtime'
        endpoint = helper.RUNTIME / 'wayland-0'
        for mode in (0o600, 0o660, 0o700, 0o755, 0o777):
            def metadata(path):
                self.assertEqual(path, endpoint)
                return SimpleNamespace(st_mode=stat.S_IFSOCK | mode,
                                       st_uid=os.getuid(), st_nlink=1)
            with self.subTest(mode=oct(mode)), \
                    mock.patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}, clear=True), \
                    mock.patch.object(Path, 'lstat', metadata):
                helper.require_wayland()
