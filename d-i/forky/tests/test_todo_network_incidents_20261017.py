"""Disposable-only fixtures for the supplied Bitwarden and USB Ethernet logs."""
from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation
sys.path.pop(0)
require_test_isolation()

from contextlib import redirect_stderr, redirect_stdout
import io
import os
import stat
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from payload_fixture import python_library, read_text

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
sys.path.insert(0, str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')))
from labwc_managed_app import sandbox

hotplug = types.ModuleType('hotplug_fixture')
exec(compile(read_text(TARGET / 'usr/local/libexec/network-ifup-hotplug'),
             'network-ifup-hotplug', 'exec'), hotplug.__dict__)


class BitwardenProxyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / 'home'
        self.home.mkdir(mode=0o700)
        for relative in sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS:
            (self.home / relative).mkdir(parents=True, mode=0o700)
        self.payload = b'fixture proxy bytes, never executed\n'
        patcher = mock.patch.object(sandbox, '_bitwarden_proxy_bytes', return_value=self.payload)
        self.seed = patcher.start()
        self.addCleanup(patcher.stop)

    def prepare(self):
        sandbox.prepare_bitwarden_integration(str(self.home))

    def test_all_nine_missing_proxies_get_complete_private_copies(self):
        self.prepare()
        self.assertEqual(len(sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS), 9)
        self.seed.assert_called_once_with()
        inodes = set()
        for relative in sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS:
            directory = self.home / relative
            path = directory / '.bitwarden_desktop_proxy'
            self.assertEqual(path.read_bytes(), self.payload)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertEqual(path.stat().st_nlink, 1)
            self.assertEqual(list(directory.iterdir()), [path])
            inodes.add(path.stat().st_ino)
        self.assertEqual(len(inodes), 9)

    def test_repeated_launch_preserves_existing_proxy_bytes_and_mode(self):
        self.prepare()
        first = self.home / sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS[0] / '.bitwarden_desktop_proxy'
        first.write_bytes(b'account existing proxy')
        first.chmod(0o500)
        identity = first.stat().st_ino
        self.seed.reset_mock()
        self.prepare()
        self.seed.assert_not_called()
        self.assertEqual(first.read_bytes(), b'account existing proxy')
        self.assertEqual(first.stat().st_ino, identity)
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o500)

    def test_deleted_proxy_is_repaired_on_the_next_launch(self):
        self.prepare()
        path = self.home / sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS[3] / '.bitwarden_desktop_proxy'
        path.unlink()
        self.prepare()
        self.assertEqual(path.read_bytes(), self.payload)

    def test_symlinked_destination_is_rejected_without_touching_its_target(self):
        unrelated = Path(self.temporary.name) / 'unrelated'
        unrelated.write_bytes(b'preserve')
        path = self.home / sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS[0] / '.bitwarden_desktop_proxy'
        path.symlink_to(unrelated)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.prepare()
        self.assertEqual(unrelated.read_bytes(), b'preserve')
        self.seed.assert_not_called()

    def test_symlinked_parent_is_rejected_before_any_copy(self):
        directory = self.home / sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS[0]
        directory.rmdir()
        unrelated = Path(self.temporary.name) / 'other-directory'
        unrelated.mkdir()
        directory.symlink_to(unrelated, target_is_directory=True)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.prepare()
        self.assertEqual(list(unrelated.iterdir()), [])

    def test_publication_failure_leaves_no_partial_proxy_or_temporary_file(self):
        first = self.home / sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS[0]
        with mock.patch.object(sandbox.os, 'link', side_effect=OSError('fixture failure')), \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.prepare()
        self.assertEqual(list(first.iterdir()), [])

    def test_concurrent_publication_keeps_the_winning_complete_file(self):
        link = os.link
        first = self.home / sandbox.BITWARDEN_NATIVE_MESSAGING_PATHS[0] / '.bitwarden_desktop_proxy'
        def race(source, destination, **keywords):
            if not first.exists():
                first.write_bytes(b'concurrent complete proxy')
                first.chmod(0o700)
            return link(source, destination, **keywords)
        with mock.patch.object(sandbox.os, 'link', side_effect=race):
            self.prepare()
        self.assertEqual(first.read_bytes(), b'concurrent complete proxy')
        self.assertEqual(list(first.parent.iterdir()), [first])


class HotplugIfupTests(unittest.TestCase):
    def invoke(self, status, identities):
        with mock.patch.object(hotplug, 'device_identity', side_effect=identities), \
                mock.patch.object(hotplug.subprocess, 'run', return_value=types.SimpleNamespace(returncode=status)) as run, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = hotplug.main(['eth0'])
        return result, run

    def test_usb_removal_converts_only_ifups_ordinary_failure_to_cancellation(self):
        self.assertEqual(self.invoke(1, [(1, 2, 3), None])[0], 0)
        for status in (2, 124, -15, -9):
            with self.subTest(status=status):
                self.assertEqual(self.invoke(status, [(1, 2, 3)])[0], status)

    def test_present_or_replaced_device_does_not_hide_configuration_failure(self):
        for after in ((1, 2, 3), (1, 9, 10)):
            self.assertEqual(self.invoke(1, [(1, 2, 3), after])[0], 1)
        self.assertEqual(self.invoke(0, [(1, 2, 3), (1, 9, 10)])[0], 1)

    def test_absent_device_does_not_execute_ifup_and_success_keeps_exact_argv(self):
        result, run = self.invoke(0, [None])
        self.assertEqual(result, 0)
        run.assert_not_called()
        result, run = self.invoke(0, [(1, 2, 3), (1, 2, 3)])
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0], ['/usr/sbin/ifup', '--allow=hotplug', 'eth0'])
        self.assertEqual(run.call_args.kwargs['env'],
                         {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})

    def test_invalid_names_never_reach_sysfs_or_a_command(self):
        with mock.patch.object(hotplug, 'device_identity') as identity, \
                mock.patch.object(hotplug.subprocess, 'run') as run, redirect_stderr(io.StringIO()):
            for value in ('../eth0', '-bad', 'lo', '', 'a' * 16):
                self.assertEqual(hotplug.main([value]), 2)
        identity.assert_not_called()
        run.assert_not_called()

    def test_identity_is_read_from_owned_fixture_sysfs_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'eth0'
            directory.mkdir()
            (directory / 'ifindex').write_text('7\n', encoding='ascii')
            with mock.patch.object(hotplug, 'Path', return_value=root):
                self.assertEqual(hotplug.device_identity('eth0')[2], 7)
                self.assertIsNone(hotplug.device_identity('absent'))
                (directory / 'ifindex').write_text('invalid\n', encoding='ascii')
                with self.assertRaises(ValueError):
                    hotplug.device_identity('eth0')

    def test_public_adapter_preserves_term_and_kill_as_signals(self):
        # Run the real adapter in a disposable child, with both sysfs and
        # ifup replaced before execution. Only that child's PID is signalled.
        program = r'''
import pathlib, subprocess, sys, types
source = pathlib.Path(sys.argv[1]).read_text()
root = pathlib.Path(sys.argv[2])
status = int(sys.argv[3])
def fixture_path(value):
    if value != '/sys/class/net':
        raise AssertionError('unexpected device path')
    return root
pathlib.Path = fixture_path
subprocess.run = lambda *args, **kwargs: types.SimpleNamespace(returncode=status)
sys.argv = ['network-ifup-hotplug', 'eth0']
exec(compile(source, 'network-ifup-hotplug', 'exec'), {'__name__': '__main__'})
'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            device = root / 'eth0'
            device.mkdir()
            (device / 'ifindex').write_text('7\n', encoding='ascii')
            for status in (-15, -9):
                with self.subTest(status=status):
                    result = subprocess.run(
                        [sys.executable, '-I', '-B', '-c', program,
                         str(TARGET / 'usr/local/libexec/network-ifup-hotplug'), str(root), str(status)],
                        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': str(root)},
                        stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
                    )
                    self.assertEqual(result.returncode, status, result.stderr)


class BitwardenVendorProxyTests(unittest.TestCase):
    def test_vendor_read_is_bounded_and_rejects_nonregular_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'vendor-proxy'
            with mock.patch.object(sandbox, 'require_root_owned_regular_file', return_value=str(source)), \
                    redirect_stderr(io.StringIO()):
                source.write_bytes(b'fixture vendor bytes, never executed')
                source.chmod(0o700)
                self.assertEqual(sandbox._bitwarden_proxy_bytes(), source.read_bytes())
                with source.open('r+b') as stream:
                    stream.truncate(32 * 1024 * 1024 + 1)
                with self.assertRaises(SystemExit):
                    sandbox._bitwarden_proxy_bytes()
                source.unlink()
                os.mkfifo(source, 0o600)
                with self.assertRaises(SystemExit):
                    sandbox._bitwarden_proxy_bytes()
