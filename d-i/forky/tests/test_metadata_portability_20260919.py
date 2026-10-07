"""Metadata checks without an external metadata executable.

Installer fixtures expose only selected BusyBox applets. Native language APIs
are independent of PATH and remain the oracle for ownership/type/mode checks.
"""
import importlib.util
import os
from pathlib import Path
import pwd
import grp
import shlex
import shutil
import subprocess
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
ROOT = FORKY.parents[1]
LIFECYCLE = FORKY / 'scripts/common/lifecycle.sh'


def minimal_installer_bin(path):
    busybox = shutil.which('busybox')
    if not busybox:
        raise RuntimeError('BusyBox is required for installer portability tests')
    path.mkdir()
    # No Python, GNU find extension or external metadata program is exposed.
    for name in ('awk', 'basename', 'cat', 'chgrp', 'chmod', 'chown', 'chroot',
                 'cmp', 'cp', 'cut', 'date', 'dd', 'dirname', 'env', 'expr',
                 'find', 'grep', 'head', 'id', 'install', 'ln', 'ls', 'mkdir', 'mktemp',
                 'mv', 'printf', 'readlink', 'rm', 'rmdir', 'sed', 'seq',
                 'sha256sum', 'sleep', 'sort', 'sync', 'tail', 'tar', 'touch',
                 'tr', 'wc'):
        (path / name).symlink_to(busybox)
    return str(path)


class InstallerMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='metadata-portability-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {'PATH': minimal_installer_bin(self.root / 'bin'), 'LC_ALL': 'C'}
        self.shells = (('/bin/dash',), (shutil.which('busybox'), 'sh'), ('/bin/bash', '--posix'))

    def run_reader(self, path, field, shell):
        code = '. ' + shlex.quote(str(LIFECYCLE)) + '\ninstaller_metadata_value "$TEST_PATH" "$TEST_FIELD"'
        return subprocess.run([*shell, '-eu', '-c', code], text=True, capture_output=True,
                              env={**self.env, 'TEST_PATH': str(path), 'TEST_FIELD': field}, timeout=5)

    def test_forbidden_executable_and_target_only_extensions_are_absent(self):
        for shell in self.shells:
            for name in ('stat', 'python3'):
                result = subprocess.run([*shell, '-c', 'command -v "$1"', 'test', name],
                                        env=self.env, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
        result = subprocess.run([str(self.root / 'bin/find'), str(self.root), '-maxdepth', '0',
                                 '-printf', '%U'], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, 'fixture accidentally exposes GNU find')

    def test_numeric_owner_group_links_and_special_modes(self):
        path = self.root / 'metadata'
        path.write_text('fixture')
        for mode in (0, 0o400, 0o600, 0o644, 0o755, 0o1755, 0o2750, 0o3770, 0o4755, 0o6750, 0o7000):
            path.chmod(mode)
            info = path.lstat()
            expected = {'uid': str(info.st_uid), 'gid': str(info.st_gid),
                        'uid_gid': f'{info.st_uid}:{info.st_gid}', 'links': str(info.st_nlink),
                        'mode': f'{info.st_mode & 0o7777:o}',
                        'uid_gid_mode': f'{info.st_uid}:{info.st_gid}:{info.st_mode & 0o7777:o}',
                        'uid_gid_mode_links': f'{info.st_uid}:{info.st_gid}:{info.st_mode & 0o7777:o}:{info.st_nlink}'}
            for shell in self.shells:
                for field, value in expected.items():
                    with self.subTest(mode=oct(mode), field=field, shell=shell):
                        result = self.run_reader(path, field, shell)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout, value + '\n')

    def test_filename_text_is_never_parsed_as_metadata(self):
        for name in ('with spaces', '-delete', 'tabs\tand\nnewlines', '0 0 777 ; $(false)'):
            path = self.root / name
            path.write_text('fixture')
            path.chmod(0o640)
            for shell in self.shells:
                result = self.run_reader(path, 'uid_gid_mode_links', shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, f'{os.getuid()}:{os.getgid()}:640:1\n')

    def test_hardlinks_and_symlinks_retain_their_own_metadata(self):
        path = self.root / 'original'
        path.write_text('fixture')
        path.chmod(0o600)
        os.link(path, self.root / 'hardlink')
        link = self.root / 'symlink'
        link.symlink_to(path)
        for shell in self.shells:
            self.assertEqual(self.run_reader(path, 'links', shell).stdout, '2\n')
            result = self.run_reader(link, 'uid_gid_mode_links', shell)
            info = link.lstat()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f'{info.st_uid}:{info.st_gid}:777:1\n')

    def test_missing_file_or_failed_inspection_is_not_success(self):
        for shell in self.shells:
            self.assertNotEqual(self.run_reader(self.root / 'absent', 'uid_gid', shell).returncode, 0)
        executable = self.root / 'bin/ls'
        executable.unlink()
        executable.write_text('#!/bin/sh\nprintf "bad metadata\\n"\n')
        executable.chmod(0o755)
        for shell in self.shells:
            self.assertNotEqual(self.run_reader(self.root, 'uid_gid', shell).returncode, 0)
        executable.write_text('#!/bin/sh\nexit 7\n')
        for shell in self.shells:
            self.assertNotEqual(self.run_reader(self.root, 'mode', shell).returncode, 0)

    def test_trusted_environment_file_loads_without_external_metadata_command(self):
        path = self.root / 'credentials.env'
        path.write_text('PRESEED_ROOT_PASSWORD="fixture-private-value"\n')
        path.chmod(0o600)
        code = '. ' + shlex.quote(str(FORKY / 'scripts/common/credentials.sh')) + '\npreseed_env_read_value root_password'
        for shell in self.shells:
            result = subprocess.run([*shell, '-eu', '-c', code], text=True, capture_output=True,
                                    env={**self.env, 'INSTALLER_PRESEED_ENV_FILE': str(path)}, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'fixture-private-value\n')
            self.assertEqual(result.stderr, '')


class TargetMetadataTests(unittest.TestCase):
    def test_single_path_formats_match_native_metadata_without_traversal(self):
        with tempfile.TemporaryDirectory(prefix='target-metadata-') as tmp:
            root = Path(tmp)
            path = root / '-delete tabs\t and\nnewlines'
            path.mkdir()
            path.chmod(0o3770)
            (path / 'must-not-be-enumerated').write_text('fixture')
            info = path.lstat()
            expected = {'%U': str(info.st_uid), '%G': str(info.st_gid), '%m': '3770',
                        '%n': str(info.st_nlink), '%s': str(info.st_size),
                        '%u': pwd.getpwuid(info.st_uid).pw_name,
                        '%g': grp.getgrgid(info.st_gid).gr_name,
                        '%U:%G:%m': f'{info.st_uid}:{info.st_gid}:3770',
                        '%U:%n:%m': f'{info.st_uid}:{info.st_nlink}:3770'}
            for format_string, value in expected.items():
                result = subprocess.run(['/usr/bin/find', '-P', str(path), '-maxdepth', '0',
                                         '-printf', format_string], text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, value)
            self.assertTrue((path / 'must-not-be-enumerated').is_file())

    def test_link_dereference_is_explicit_and_missing_paths_fail(self):
        with tempfile.TemporaryDirectory(prefix='target-metadata-') as tmp:
            path = Path(tmp) / 'file'
            path.write_text('fixture'); path.chmod(0o600)
            link = Path(tmp) / 'link'; link.symlink_to(path)
            for option, mode in (('-P', '777'), ('-H', '600')):
                result = subprocess.run(['/usr/bin/find', option, str(link), '-maxdepth', '0', '-printf', '%m'],
                                        text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, mode)
            path.unlink()
            result = subprocess.run(['/usr/bin/find', '-P', str(path), '-maxdepth', '0', '-printf', '%U'],
                                    text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_open_lock_descriptor_is_checked_even_after_unlink(self):
        with tempfile.TemporaryDirectory(prefix='target-fd-metadata-') as tmp:
            path = Path(tmp) / 'lock'
            path.touch(mode=0o600)
            code = 'exec 9<>"$1"; rm -- "$1"; /usr/bin/find -H /proc/self/fd/9 -maxdepth 0 -printf "%U:%n:%m"'
            result = subprocess.run(['/bin/sh', '-eu', '-c', code, 'test', str(path)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            # A deleted lock must NOT be mistaken for a safe one-link lock.
            self.assertEqual(result.stdout, f'{os.getuid()}:0:600')


class MetadataDependencyGuardTests(unittest.TestCase):
    def checker(self):
        spec = importlib.util.spec_from_file_location('metadata_checker', ROOT / 'tools/check_shells.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.external_metadata_dependencies

    def test_repository_has_no_external_metadata_executable_dependencies(self):
        self.assertEqual(self.checker()(ROOT), [])

    def test_guard_rejects_shell_calls_dependency_lists_and_python_argv(self):
        with tempfile.TemporaryDirectory(prefix='metadata-guard-') as tmp:
            root = Path(tmp)
            path = root / 'd-i/forky/scripts/check.sh'; path.parent.mkdir(parents=True)
            for body in ('stat -c %u /tmp', '/usr/bin/stat -c %u /tmp',
                         'stat "$path"', 'result=$(stat ./fixture)', 'stat',
                         'busybox stat -c %u /tmp', 'for command_name in id stat; do :; done',
                         'llama_target_require_command stat',
                         'value=$(/usr/bin/stat \\\n --format=%u /tmp)'):
                path.write_text('#!/bin/sh\n' + body + '\n')
                self.assertTrue(self.checker()(root), body)
            path.unlink()
            python_path = path.with_suffix('.py')
            python_path.write_text("run(['/usr/bin/stat', '-c', '%u', '/tmp'])\n")
            self.assertTrue(self.checker()(root))
            python_path.write_text("import os\nimport stat\nos.stat('/tmp')\n")
            self.assertEqual(self.checker()(root), [])
