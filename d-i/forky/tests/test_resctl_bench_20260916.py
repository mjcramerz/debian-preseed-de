"""Pinned release installer tests using SYNTHETIC archives, not release bytes.

No network, benchmark, package installation or service activation occurs.
"""
from __future__ import annotations
import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest import mock
import test_systemd_resource_policy as base

SEED = Path(__file__).resolve().parents[1]
PIN = '466f9d0fbdea9b9c5755bb03cd1e5905e3b3fe3fc311c564b3c3619781e2786c'
TAG = 'resctl-bench-v0.0.1-P15s'
URL = 'https://github.com/mjcramerz/resctl-bench/releases/download/' + TAG + '/resctl-bench-2.2.6-x86_64-unknown-linux-gnu-native.tar.gz'
ARCHIVE_ROOT = 'resctl-bench-2.2.6-x86_64-unknown-linux-gnu-native-20260916-test'


def module():
    path = SEED / 'scripts/desktop/resctl-bench-install.py'
    result = types.ModuleType('resctl_installer'); result.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), result.__dict__)
    return result


def arguments(**changes):
    values = dict(version='2.2.6', tag=TAG, url=URL, sha256=PIN, architecture='amd64',
                  max_archive=536870912, max_extracted=2147483648, max_members=8192)
    values.update(changes)
    return argparse.Namespace(**values)


def elf():
    header = bytearray(64)
    header[:6] = b'\x7fELF\x02\x01'
    header[16:18] = (3).to_bytes(2, 'little')
    header[18:20] = (62).to_bytes(2, 'little')
    return bytes(header) + b'SYNTHETIC TEST FILE, NOT AN EXECUTABLE\n'


def payload():
    return {**{'bin/' + b: elf() for b in ('resctl-bench', 'rd-agent', 'rd-hashd')},
            'README.md': b'test release\n', 'install.py': b'raise RuntimeError("must never execute")\n',
            'runtime_check.py': b'raise RuntimeError("must never execute")\n',
            'share/doc/resctl-bench/RUNTIME.md': b'maintenance window required\n',
            'share/licenses/resctl-bench/COPYING': b'test license\n',
            'share/resctl-bench/build/provenance.json': b'{"test":true}\n',
            'bin/.debug/resctl-bench.debug': b'test debug data\n'}


def archive(path, files=None, extras=(), root=ARCHIVE_ROOT, checksum=None):
    files = payload() if files is None else dict(files)
    files['SHA256SUMS'] = checksum if checksum is not None else ''.join(
        hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
        for name, data in sorted(files.items())).encode()
    with tarfile.open(path, 'w:gz', format=tarfile.PAX_FORMAT) as tar:
        top = tarfile.TarInfo(root); top.type = tarfile.DIRTYPE; top.mode = 0o7777
        tar.addfile(top)
        for name, data in files.items():
            item = tarfile.TarInfo(root + '/' + name); item.size = len(data); item.mode = 0o7777
            tar.addfile(item, io.BytesIO(data))
        for item, data in extras:
            tar.addfile(item, io.BytesIO(data) if data is not None else None)


class ReleasePolicyTests(unittest.TestCase):
    def setUp(self):
        self.installer = module()

    def test_all_thirteen_profiles_have_each_exact_pin_once(self):
        profiles = sorted((SEED/'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 13)
        expected = dict(VERSION='2.2.6', TAG=TAG, URL=URL, SHA256=PIN, ARCHITECTURE='amd64',
                        MAXIMUM_BYTES='536870912', MAXIMUM_EXTRACTED_BYTES='2147483648', MAXIMUM_MEMBERS='8192')
        for profile in profiles:
            for key, value in expected.items():
                with self.subTest(profile=profile.name, key=key):
                    self.assertEqual(re.findall(r'^RESCTL_BENCH_' + key + r'="([^"]*)"$', profile.read_text(), re.M), [value])

    def test_valid_policy_and_each_invalid_input(self):
        self.installer.policy(arguments())
        for changes in (dict(version='2.2.6;id'), dict(tag='../x'), dict(url='http://example.com/archive'),
                        dict(url=URL+'?other=1'), dict(architecture='arm64'), dict(sha256=PIN.upper()),
                        dict(sha256='0'*63), dict(max_members=16385), dict(max_archive=536870913),
                        dict(max_extracted=1024), dict(max_extracted=2147483649)):
            with self.subTest(changes=changes), self.assertRaises(self.installer.Error):
                self.installer.policy(arguments(**changes))

    def test_download_enforces_https_bounds_and_hash_before_unpacking(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'archive'; path.write_bytes(b'synthetic response')
            with mock.patch.object(self.installer.subprocess, 'run') as run:
                with self.assertRaisesRegex(self.installer.Error, 'SHA-256 mismatch'):
                    self.installer.download(arguments(), path)
            argv = run.call_args.args[0]
            self.assertEqual(argv[:2], ['/usr/bin/curl', '--disable'])
            for flag in ('--proto', '--proto-redir'):
                self.assertEqual(argv[argv.index(flag)+1], '=https')
            self.assertEqual(argv[argv.index('--url')+1], URL)
            self.assertIn('--max-filesize', argv)
            with mock.patch.object(self.installer.subprocess, 'run'):
                self.installer.download(arguments(sha256=hashlib.sha256(path.read_bytes()).hexdigest()), path)

    def test_download_rejects_oversize_and_empty_response(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(self.installer.subprocess, 'run'):
            path = Path(temporary)/'archive'
            for data in (b'', b'x'*1025):
                path.write_bytes(data)
                with self.assertRaisesRegex(self.installer.Error, 'bounded regular'):
                    self.installer.download(arguments(max_archive=1024), path)

    def test_desktop_pipeline_fetches_and_installs_for_all_profiles(self):
        role = (SEED/'scripts/late/desktop.sh').read_text()
        self.assertIn('digital-assets resctl-bench labwc;', role)
        self.assertIn('. "${desktop_module_dir}/resctl-bench.sh"', role)
        pipeline = (SEED/'scripts/desktop/labwc.sh').read_text()
        self.assertIn('  desktop_resctl_bench_preflight_target_architecture\n', pipeline)
        self.assertIn('  desktop_install_resctl_bench\n  desktop_stage_target_assets', pipeline)
        verifier = (SEED/'scripts/desktop/verify.sh').read_text()
        self.assertLess(verifier.index('for resctl_binary'), verifier.index('desktop_verify_target_staging()'))
        firstboot = (SEED/'scripts/firstboot/04-validation.sh').read_text()
        for binary in ('resctl-bench', 'rd-agent', 'rd-hashd'):
            self.assertIn('/usr/local/bin/'+binary, firstboot)

    def test_real_shell_staging_pin_arguments_and_ephemeral_helper_cleanup(self):
        runner = base.ResourcePolicyTests()
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); (root/'target').mkdir()
                script = runner.staging(temporary) + '\n. ' + str(SEED/'scripts/desktop/resctl-bench.sh') + '''
installer_repo_join_var() { test "$1" = DIR_SCRIPTS_DESKTOP || exit 9; printf 'scripts/desktop/%s\\n' "$2"; }
capture_in_target() { printf '%s\\n' amd64; }
desktop_log() { :; }
run_in_target() {
  test -s "$INSTALLER_TARGET_DIR/usr/local/libexec/installer-resctl-bench" || exit 8
  printf '%s\\n' "$@" >"$INSTALLER_TARGET_DIR/invocation"
  return ''' + ('7' if failure else '0') + '''
}
desktop_install_resctl_bench
'''
                result = runner.shell(script, check=False)
                self.assertEqual(result.returncode, 7 if failure else 0, result.stderr)
                self.assertFalse((root/'target/usr/local/libexec/installer-resctl-bench').exists())
                args = (root/'target/invocation').read_text().splitlines()
                for value in (PIN, TAG, URL, '/usr/bin/python3', '-I', '/usr/bin/env', '-i', '900s'):
                    self.assertIn(value, args)
                self.assertFalse(list((root/'target').rglob('.installer-asset.*')))

    def test_shell_refuses_wrong_architecture_before_staging(self):
        runner = base.ResourcePolicyTests()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'target'; target.mkdir()
            result = runner.shell(runner.staging(temporary) + '\n. ' + str(SEED/'scripts/desktop/resctl-bench.sh') + '''
installer_repo_join_var() { test "$1" = DIR_SCRIPTS_DESKTOP || exit 9; printf 'scripts/desktop/%s\\n' "$2"; }
capture_in_target() { printf '%s\\n' arm64; }
desktop_install_resctl_bench
''', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('requires an amd64 target', result.stderr)
            self.assertEqual(list(target.iterdir()), [])


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.installer = module()
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.path = self.work/'release.tar.gz'
        self.stage = self.work/'stage'

    def unpack(self, **kwargs):
        return self.installer.unpack(arguments(**kwargs), self.path, self.stage)

    def test_valid_archive_preserves_docs_licenses_debug_and_companions(self):
        archive(self.path)
        root, binaries = self.unpack()
        self.assertEqual(binaries, ['rd-agent', 'rd-hashd', 'resctl-bench'])
        for name, data in payload().items():
            path = root/name
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755 if name in {'bin/'+b for b in binaries} else 0o644)
        self.assertFalse((self.work/'release.tar').exists())

    def test_optional_demo_is_validated_too(self):
        files = payload(); files['bin/resctl-demo'] = elf(); archive(self.path, files)
        _, binaries = self.unpack()
        self.assertIn('resctl-demo', binaries)

    def test_absolute_parent_alias_and_control_character_paths_are_rejected(self):
        for name in ('/root/escape', '../escape', 'a/../escape', 'a//file', 'a/./file', 'a\\file', 'a/\nfile', 'a/'+'x'*256):
            with self.subTest(name=name), self.assertRaises(self.installer.Error):
                self.installer.member_path(name)

    def test_all_link_and_special_node_types_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE):
            with self.subTest(kind=kind):
                item = tarfile.TarInfo(ARCHIVE_ROOT+'/bad'); item.type = kind; item.linkname = '/etc/passwd'
                archive(self.path, extras=[(item, None)])
                with self.assertRaisesRegex(self.installer.Error, 'special nodes'):
                    self.unpack()
                (self.work/'release.tar').unlink(missing_ok=True)

    def test_duplicate_member_is_rejected(self):
        item = tarfile.TarInfo(ARCHIVE_ROOT+'/README.md'); item.size = 3
        archive(self.path, extras=[(item, b'bad')])
        with self.assertRaisesRegex(self.installer.Error, 'duplicate'):
            self.unpack()

    def test_parent_file_collision_is_rejected(self):
        files = payload(); files['share'] = b'not a directory'; archive(self.path, files)
        with self.assertRaisesRegex(self.installer.Error, 'collision'):
            self.unpack()

    def test_wrong_release_root_or_second_root_is_rejected(self):
        archive(self.path, root='resctl-bench-9.9.9-aarch64-native')
        with self.assertRaisesRegex(self.installer.Error, 'unexpected release'):
            self.unpack()
        (self.work/'release.tar').unlink()
        extra = tarfile.TarInfo('another'); extra.type = tarfile.DIRTYPE
        archive(self.path, extras=[(extra, None)])
        with self.assertRaisesRegex(self.installer.Error, 'exactly one'):
            self.unpack()

    def test_sparse_pax_payload_is_rejected(self):
        extra = tarfile.TarInfo(ARCHIVE_ROOT+'/sparse'); extra.pax_headers = {'GNU.sparse.name': 'sparse'}
        archive(self.path, extras=[(extra, b'')])
        with self.assertRaisesRegex(self.installer.Error, 'sparse'):
            self.unpack()

    def test_missing_companion_binary_is_rejected(self):
        files = payload(); del files['bin/rd-agent']; archive(self.path, files)
        with self.assertRaisesRegex(self.installer.Error, 'all required'):
            self.unpack()

    def test_unknown_executable_is_rejected(self):
        files = payload(); files['bin/surprise'] = b'bad'; archive(self.path, files)
        with self.assertRaisesRegex(self.installer.Error, 'unexpected executable'):
            self.unpack()

    def test_non_elf_and_wrong_elf_architecture_are_rejected(self):
        for header in (b'#!/bin/sh\nexit 0\n', elf()[:18] + b'\xb7\x00' + elf()[20:]):
            with self.subTest(header=header):
                files = payload(); files['bin/resctl-bench'] = header; archive(self.path, files)
                with self.assertRaisesRegex(self.installer.Error, 'x86-64 ELF'):
                    self.unpack()
                shutil.rmtree(self.stage); (self.work/'release.tar').unlink(missing_ok=True)

    def test_checksum_inventory_or_format_mismatch_is_rejected(self):
        for checksum in (b'', b'not a checksum\n', b'0'*64+b'  README.md\n', b'0'*64+b'  SHA256SUMS\n'):
            with self.subTest(checksum=checksum):
                archive(self.path, checksum=checksum)
                with self.assertRaises(self.installer.Error):
                    self.unpack()
                shutil.rmtree(self.stage); (self.work/'release.tar').unlink(missing_ok=True)

    def test_expansion_and_member_count_are_bounded(self):
        archive(self.path)
        with self.assertRaisesRegex(self.installer.Error, 'decompressed archive'):
            self.unpack(max_extracted=512)
        (self.work/'release.tar').unlink()
        with self.assertRaisesRegex(self.installer.Error, 'too many'):
            self.unpack(max_members=3)

    def test_gzip_truncation_is_not_accepted(self):
        archive(self.path); self.path.write_bytes(self.path.read_bytes()[:-12])
        with self.assertRaises((EOFError, OSError)):
            self.unpack()

    def test_highly_compressible_member_is_not_limited_to_compressed_ceiling(self):
        files = payload(); files['share/doc/resctl-bench/large.txt'] = b'0' * 65536
        archive(self.path, files)
        self.assertLess(self.path.stat().st_size, 8192)
        self.unpack(max_archive=8192, max_extracted=262144)


@unittest.skipUnless(os.geteuid() == 0, 'publication ownership and credential-drop checks require root fixtures')
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.installer = module()
        # /var/lib is root-owned/non-world-writable. Only this temporary subtree
        # is modified, unlike a fixture below /tmp that the production guard
        # correctly rejects as an installation destination.
        self.temp = tempfile.TemporaryDirectory(prefix='resctl-test-', dir='/var/lib')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.path = self.work/'release.tar.gz'; archive(self.path)
        self.root, self.binaries = self.installer.unpack(arguments(), self.path, self.work/'stage')
        self.installer.BIN_DIR = self.work/'target/usr/local/bin'
        self.installer.DOC_DIR = self.work/'target/data/docs/resctl-bench'

    def test_publication_modes_provenance_and_identical_repeat_install(self):
        for _ in range(2):
            self.installer.publish(arguments(), self.root, self.binaries)
        for name in self.binaries:
            path = self.installer.BIN_DIR/name
            self.assertEqual(path.read_bytes(), elf())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
            self.assertEqual(path.stat().st_nlink, 1)
        docs = self.installer.DOC_DIR
        for path in docs.rglob('*'):
            if path.is_file():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        meta = json.loads((docs/'INSTALLATION.json').read_text())
        self.assertEqual(meta['archive_sha256'], PIN)
        self.assertEqual(meta['tag'], TAG)
        self.assertTrue(meta['native_cpu_build'])
        self.assertEqual((docs/'release/install.py').read_bytes(), payload()['install.py'])
        self.assertFalse(list(self.work.rglob('.resctl-bench-*')))

    def test_existing_unmanaged_binary_is_never_overwritten(self):
        self.installer.BIN_DIR.mkdir(parents=True)
        existing = self.installer.BIN_DIR/'rd-hashd'; existing.write_bytes(b'keep admin file'); existing.chmod(0o755)
        with self.assertRaisesRegex(self.installer.Error, 'refusing to overwrite'):
            self.installer.publish(arguments(), self.root, self.binaries)
        self.assertEqual(existing.read_bytes(), b'keep admin file')
        self.assertFalse((self.installer.BIN_DIR/'resctl-bench').exists())
        self.assertFalse((self.installer.DOC_DIR/'INSTALLATION.json').exists())

    def test_symlinked_destination_or_writable_parent_is_rejected(self):
        self.installer.BIN_DIR.mkdir(parents=True)
        existing = self.installer.BIN_DIR/'rd-agent'; existing.symlink_to('/etc/passwd')
        with self.assertRaises(self.installer.Error):
            self.installer.publish(arguments(), self.root, self.binaries)
        existing.unlink(); self.installer.BIN_DIR.chmod(0o777)
        with self.assertRaisesRegex(self.installer.Error, 'unsafe installation directory'):
            self.installer.publish(arguments(), self.root, self.binaries)

    def test_partial_publication_error_rolls_back_new_files(self):
        link = os.link; count = 0
        def fail_second(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('synthetic disk failure')
            return link(*args, **kwargs)
        with mock.patch.object(self.installer.os, 'link', side_effect=fail_second), self.assertRaises(OSError):
            self.installer.publish(arguments(), self.root, self.binaries)
        self.assertEqual([p for p in (self.work/'target').rglob('*') if p.is_file()], [])

    def test_smoke_drops_groups_uses_fixed_version_only_and_fails_before_publish(self):
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, 'test 2.2.6\n', '')
        with mock.patch.object(self.installer.subprocess, 'run', side_effect=run):
            self.installer.smoke(self.root, self.binaries, '2.2.6', self.work/'smoke')
        self.assertEqual(len(calls), 3)
        for argv, kwargs in calls:
            self.assertEqual(argv[1:], ['--version'])
            self.assertNotEqual(kwargs['user'], 0)
            self.assertEqual(kwargs['extra_groups'], ())
            self.assertEqual(kwargs['timeout'], 20)
            self.assertNotIn('PYTHONPATH', kwargs['env'])
        with mock.patch.object(self.installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], -4, '', '')):
            with self.assertRaisesRegex(self.installer.Error, 'native CPU/loader/version'):
                self.installer.smoke(self.root, self.binaries, '2.2.6', self.work/'smoke-fail')
        self.assertFalse(self.installer.BIN_DIR.exists())

    def test_real_unprivileged_smoke_with_harmless_compiled_fixture(self):
        compiler = shutil.which('cc')
        if compiler is None:
            self.skipTest('C compiler unavailable for synthetic ELF execution fixture')
        # Distinct from the non-executable synthetic archive entries above.
        source = self.work/'version.c'
        source.write_text('#include <stdio.h>\n#include <unistd.h>\nint main(void) { if (geteuid() == 0) return 9; puts("fixture 2.2.6"); return 0; }\n')
        subprocess.run([compiler, str(source), '-o', str(self.root/'bin/resctl-bench')], check=True, capture_output=True, timeout=30)
        self.work.chmod(0o755)
        self.installer.smoke(self.root, ['resctl-bench'], '2.2.6', self.work/'real-smoke')
        with self.assertRaisesRegex(self.installer.Error, 'version incompatibility'):
            self.installer.smoke(self.root, ['resctl-bench'], '9.9.9', self.work/'wrong-version')


if __name__ == '__main__':
    unittest.main()
