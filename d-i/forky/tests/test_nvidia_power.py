#!/usr/bin/env python3
"""NVIDIA storage guard and offline activation fixture checks, without a GPU."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from test_hardware_restore import make_chroot, FORKY
TARGET = FORKY / 'hooks/target'
GUARD = TARGET / 'usr/local/libexec/nvidia-vram-check'
PHASES = ('suspend', 'suspend-then-hibernate', 'hibernate', 'resume')


def load_guard():
    loader = importlib.machinery.SourceFileLoader('nvidia_vram_check', str(GUARD))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class NvidiaGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = load_guard()

    def test_all_gpu_capacity_plus_five_percent(self):
        total = (8192 + 4096) * 1024 * 1024
        self.assertEqual(self.guard.required_bytes('8192\n4096\n'), (total * 105 + 99) // 100)

    def test_unavailable_empty_zero_and_malformed_memory_fail(self):
        for output in ('', '0\n', 'N/A\n', '-1\n', '8192 MiB\n', '8192\n\n', '1' * 65537):
            with self.subTest(output=output[:30]):
                with self.assertRaises((RuntimeError, ValueError)):
                    self.guard.required_bytes(output)

    @unittest.skipUnless(os.geteuid() == 0, 'root ownership fixture')
    def test_tmpfs_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)
            path.chmod(0o700)
            with mock.patch.object(self.guard.subprocess, 'run', return_value=types.SimpleNamespace(stdout='tmpfs\n')):
                with self.assertRaisesRegex(RuntimeError, 'disk-backed'):
                    self.guard.check_directory(path)

    @unittest.skipUnless(os.geteuid() == 0, 'root ownership fixture')
    def test_indirect_or_public_backing_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)
            path.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, 'mode 0700'):
                self.guard.check_directory(path)
            path.chmod(0o700)
            link = path / 'link'
            link.symlink_to(path)
            with self.assertRaises(RuntimeError):
                self.guard.check_directory(link)

    @unittest.skipUnless(os.geteuid() == 0, 'root ownership fixture')
    def test_disk_backing_requires_successful_unnamed_file_creation(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)
            path.chmod(0o700)
            with mock.patch.object(self.guard.subprocess, 'run', return_value=types.SimpleNamespace(stdout='btrfs\n')):
                with mock.patch.object(self.guard.os, 'open', side_effect=OSError('unsupported')):
                    with self.assertRaises(OSError):
                        self.guard.check_directory(path)

    def run_main(self, available, args=None):
        with mock.patch.object(self.guard.os, 'geteuid', return_value=0), \
             mock.patch.object(self.guard, 'check_directory'), \
             mock.patch.object(self.guard.subprocess, 'run', return_value=types.SimpleNamespace(stdout='8192\n')) as command, \
             mock.patch.object(self.guard.os, 'statvfs', return_value=types.SimpleNamespace(f_bavail=available, f_frsize=1)):
            result = self.guard.main(args or [])
            return result, command

    def test_insufficient_space_blocks_sleep(self):
        with self.assertRaisesRegex(RuntimeError, 'insufficient NVIDIA backing space'):
            self.run_main(1)

    def test_sufficient_space_permits_sleep(self):
        result, command = self.run_main(16 * 1024**3)
        self.assertEqual(result, 0)
        self.assertEqual(command.call_args.kwargs['timeout'], 15)

    def test_install_time_validation_does_not_require_live_gpu(self):
        result, command = self.run_main(0, ['--directory-only'])
        self.assertEqual(result, 0)
        command.assert_not_called()

    def test_system_sleep_requires_successful_nvidia_preparation(self):
        for mode in ('suspend', 'suspend-then-hibernate', 'hibernate', 'hybrid-sleep'):
            phase = 'hibernate' if mode == 'hybrid-sleep' else mode
            text = (TARGET / f'etc/systemd/system/systemd-{mode}.service.d/20-nvidia-preserve.conf').read_text()
            self.assertIn(f'Requires=nvidia-{phase}.service', text)
            self.assertIn(f'After=nvidia-{phase}.service', text)

    def test_dropins_cover_all_sleep_modes_but_never_block_resume_on_space(self):
        for phase in PHASES:
            text = (TARGET / f'etc/systemd/system/nvidia-{phase}.service.d/20-managed-vram.conf').read_text()
            self.assertIn('RequiresMountsFor=/var/lib/nvidia-vram', text)
            self.assertIn('TimeoutStartSec=120s', text)
            self.assertIn('UMask=0077', text)
            self.assertEqual('ExecStartPre=' in text, phase != 'resume')


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('chroot') and shutil.which('busybox'), 'root chroot fixtures')
class NvidiaActivationTests(unittest.TestCase):
    def fixture(self, root, missing=None):
        make_chroot(root)
        for name in ('etc/systemd/system', 'usr/lib/systemd/system', 'usr/lib/systemd/system-sleep',
                     'usr/bin', 'usr/local/libexec', 'var/lib'):
            (root / name).mkdir(parents=True, exist_ok=True)
        for phase in PHASES:
            if phase != missing:
                (root / f'usr/lib/systemd/system/nvidia-{phase}.service').write_text('[Service]\nType=oneshot\nExecStart=/bin/true\n')
        for path, text in {
            'usr/bin/nvidia-sleep.sh': '#!/bin/sh\nexit 0\n',
            'usr/lib/systemd/system-sleep/nvidia': '#!/bin/sh\nexit 0\n',
            'usr/local/libexec/nvidia-vram-check': '#!/bin/sh\nprintf "%s\\n" "$*" > /guard.args\n',
            'bin/systemctl': '#!/bin/sh\nprintf "%s\\n" "$*" > /systemctl.args\n',
        }.items():
            file = root / path
            file.write_text(text)
            file.chmod(0o755)
        (root / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
        (root / 'etc/group').write_text('root:x:0:\n')

    def activate(self, root):
        q = shlex.quote
        code = f'''
. {q(str(FORKY / 'scripts/late/core.sh'))}
installer_repo_join_var() {{ printf '%s\\n' {q(str(TARGET))}; }}
stage_target_asset() {{ :; }}
run_in_target() {{ shift; {q(shutil.which('chroot'))} {q(str(root))} "$@"; }}
configure_target_nvidia_power_management true
'''
        return subprocess.run(['/bin/sh', '-eu', '-c', code], env={**os.environ, 'PATH':'/bin:/usr/bin'},
                              text=True, capture_output=True, timeout=15)

    def test_offline_enable_all_four_units_without_start(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            result = self.activate(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = (root / 'systemctl.args').read_text()
            self.assertTrue(arguments.startswith('--no-reload enable '))
            self.assertNotIn('--now', arguments)
            for phase in PHASES:
                self.assertIn(f'nvidia-{phase}.service', arguments)
            self.assertEqual((root / 'guard.args').read_text().strip(), '--directory-only')
            self.assertEqual(stat.S_IMODE((root / 'var/lib/nvidia-vram').stat().st_mode), 0o700)

    def test_missing_vendor_unit_stops_instead_of_partial_activation(self):
        for missing in PHASES:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                self.fixture(root, missing=missing)
                result = self.activate(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'nvidia-{missing}.service', result.stderr)
                self.assertFalse((root / 'systemctl.args').exists())

    def test_missing_vendor_recovery_hook_stops(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fixture(root)
            (root / 'usr/lib/systemd/system-sleep/nvidia').unlink()
            result = self.activate(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('sleep recovery hook', result.stderr)


if __name__ == '__main__':
    unittest.main()
