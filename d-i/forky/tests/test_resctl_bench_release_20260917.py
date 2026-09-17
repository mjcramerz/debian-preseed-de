"""Regression for build-ID release URLs and consistent, preflighted host pins.

Offline tests: synthetic archives only; no release binary/installer executes.
The --version/noexec regressions in the existing suite retain their real ELF
fixtures and credential dropping. Tests do not weaken the integrity policy.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import test_resctl_bench_20260916 as base

ROOT = base.SEED.parents[1]
PINS = {
    'VERSION': '2.2.6',
    'TAG': 'resctl-bench-v0.0.2-P15s',
    'ARCHITECTURE': 'amd64',
    'URL': 'https://github.com/mjcramerz/resctl-bench/releases/download/resctl-bench-v0.0.2-P15s/resctl-bench-2.2.6-x86_64-unknown-linux-gnu-native-aa3786abb93aa646.tar.gz',
    'SHA256': 'bb132e73ffe5cdf32e205569b8a5cd7e2f52872dae6ffeace57b28337f2d6857',
    'MAXIMUM_BYTES': '536870912',
    'MAXIMUM_EXTRACTED_BYTES': '2147483648',
    'MAXIMUM_MEMBERS': '8192',
}
BUILD_ID = 'aa3786abb93aa646'
ASSET_ROOT = 'resctl-bench-2.2.6-x86_64-unknown-linux-gnu-native-' + BUILD_ID


def load_checker():
    path = ROOT / 'tools/check_resctl_bench.py'
    module = types.ModuleType('resctl_profile_checker')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def pin_text(**changes):
    pins = dict(PINS, **changes)
    return ''.join(f'RESCTL_BENCH_{key}="{value}"\n' for key, value in pins.items())


def argv(args, *extra):
    result = ['installer-resctl-bench']
    for name, value in vars(args).items():
        result.extend(['--' + name.replace('_', '-'), str(value)])
    return result + list(extra)


class BuildIdPolicyTests(unittest.TestCase):
    def setUp(self):
        self.installer = base.module()

    def test_exact_user_requested_pins_pass_runtime_policy(self):
        self.assertEqual(vars(base.arguments()), vars(load_checker().arguments(PINS)))
        self.installer.policy(base.arguments())

    def test_build_id_is_not_mistaken_for_archive_sha256(self):
        self.assertNotEqual(BUILD_ID, PINS['SHA256'][:16])
        self.installer.policy(base.arguments())
        # This step validates format, not archive bytes; download() still hashes.
        self.installer.policy(base.arguments(sha256='0' * 64))

    def test_legacy_exact_basename_remains_accepted(self):
        legacy = PINS['URL'].replace('-' + BUILD_ID, '')
        self.installer.policy(base.arguments(url=legacy))

    def test_build_id_shape_is_strictly_bounded(self):
        for suffix in ('a' * 15, 'a' * 17, 'A' * 16, 'g' * 16, '', 'deadbeef-1234567',
                       'a' * 16 + '.evil', 'a' * 16 + '/extra', 'a' * 16 + '%2fextra'):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(self.installer.Error, 'invalid RESCTL_BENCH_URL'):
                self.installer.policy(base.arguments(url=PINS['URL'].replace(BUILD_ID, suffix)))

    def test_wrong_origin_version_tag_architecture_and_url_aliases_are_rejected(self):
        url = PINS['URL']
        invalid = (
            url.replace('https:', 'http:'), url.replace('github.com/', 'github.com.evil/'),
            url.replace('github.com/', 'github.com:443/'), url.replace('github.com/', 'user@github.com/'),
            url.replace('mjcramerz/', 'another-user/'), url.replace(PINS['TAG'], 'resctl-bench-v0.0.1-P15s'),
            url.replace('resctl-bench-2.2.6-', 'resctl-bench-2.2.7-'),
            url.replace('x86_64-', 'aarch64-'), url.replace('-native-', '-portable-'),
            url + '?download=1', url + '#fragment', url + '\n', ' ' + url,
            url.replace('/download/', '/download//'), url.replace('/download/', '/download/../'),
            url.replace('/download/', '/%64ownload/'), url.replace('.tar.gz', '.zip'),
        )
        for value in invalid:
            with self.subTest(url=value), self.assertRaisesRegex(self.installer.Error, 'invalid RESCTL_BENCH_URL'):
                self.installer.policy(base.arguments(url=value))

    def test_bad_sha256_gets_a_sha256_specific_error(self):
        for value in ('', '0' * 63, '0' * 65, 'g' * 64, PINS['SHA256'].upper(),
                      ' ' + PINS['SHA256'], PINS['SHA256'] + '\n'):
            with self.subTest(value=value), self.assertRaisesRegex(
                    self.installer.Error, 'invalid RESCTL_BENCH_SHA256: expected exactly 64'):
                self.installer.policy(base.arguments(sha256=value))

    def test_bad_url_diagnostic_does_not_blame_a_valid_sha256(self):
        with self.assertRaises(self.installer.Error) as caught:
            self.installer.policy(base.arguments(url=PINS['URL'] + '?other=1'))
        self.assertIn('RESCTL_BENCH_URL', str(caught.exception))
        self.assertNotIn('SHA-256', str(caught.exception))
        self.assertIn(repr(PINS['URL'] + '?other=1'), str(caught.exception))

    def test_real_mismatch_reports_expected_and_actual_digests(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'archive.tar.gz'
            path.write_bytes(b'wrong release response')
            observed = hashlib.sha256(path.read_bytes()).hexdigest()
            with mock.patch.object(self.installer.subprocess, 'run'), self.assertRaises(self.installer.Error) as caught:
                self.installer.download(base.arguments(), path)
            message = str(caught.exception)
            self.assertIn('archive SHA-256 mismatch; nothing installed', message)
            self.assertIn('expected ' + PINS['SHA256'], message)
            self.assertIn('got ' + observed, message)

    def test_validate_only_is_read_only_and_does_not_require_root(self):
        with mock.patch.object(self.installer.sys, 'argv', argv(base.arguments(), '--validate-only')), \
                mock.patch.object(self.installer.os, 'geteuid', return_value=12345) as root_check, \
                mock.patch.object(self.installer.os, 'open', side_effect=AssertionError('no lock/file opening')), \
                mock.patch.object(self.installer.os, 'umask', side_effect=AssertionError('no process changes')), \
                mock.patch.object(self.installer.subprocess, 'run', side_effect=AssertionError('no subprocesses')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.installer.main(), 0)
        root_check.assert_not_called()
        self.assertIn('release pins valid', output.getvalue())

    def test_invalid_policy_fails_before_root_network_or_installation(self):
        for changed in ({'sha256': 'invalid'}, {'url': PINS['URL'] + '?bad'}):
            with self.subTest(changed=changed), \
                    mock.patch.object(self.installer.sys, 'argv', argv(base.arguments(**changed))), \
                    mock.patch.object(self.installer.os, 'geteuid', side_effect=AssertionError('no root query')), \
                    mock.patch.object(self.installer.subprocess, 'run', side_effect=AssertionError('no subprocesses')), \
                    mock.patch.object(self.installer, 'publish', side_effect=AssertionError('no publication')), \
                    self.assertRaises(self.installer.Error):
                self.installer.main()

    def test_exact_asset_directory_shape_unpacks_and_verifies_all_members(self):
        # Shape regression only. The ELF fixture is deliberately not executable.
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            path = work / 'release.tar.gz'
            base.archive(path, root=ASSET_ROOT)
            args = base.arguments(sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            self.installer.policy(args)
            with mock.patch.object(self.installer.subprocess, 'run'):
                self.installer.download(args, path)
            root, binaries = self.installer.unpack(args, path, work / 'stage')
            self.assertEqual(root.name, ASSET_ROOT)
            self.assertEqual(binaries, ['rd-agent', 'rd-hashd', 'resctl-bench'])
            self.installer.verify_release(root)


class ProfilePreflightTests(unittest.TestCase):
    def setUp(self):
        self.checker = load_checker()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / 'd-i/forky'
        self.profiles = self.seed / 'hosts/profiles'
        self.profiles.mkdir(parents=True)
        helper = self.seed / 'scripts/desktop/resctl-bench-install.py'
        helper.parent.mkdir(parents=True)
        shutil.copyfile(base.SEED / 'scripts/desktop/resctl-bench-install.py', helper)
        self.profile = self.profiles / 'a.env'
        self.profile.write_text(pin_text())

    def test_all_actual_profiles_match_the_exact_requested_values_once(self):
        profiles = sorted((base.SEED / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 13)
        for profile in profiles:
            with self.subTest(profile=profile.name):
                self.assertEqual(self.checker.read_pins(profile), PINS)
        self.assertEqual(self.checker.check(), 13)

    def test_current_profile_provenance_matches_the_synchronized_profiles(self):
        ledger = json.loads((ROOT / 'docs/migration-map.json').read_text())
        records = {item['destination']: item for item in ledger['files']
                   if item['destination'].startswith('d-i/forky/hosts/profiles/')}
        profiles = sorted((base.SEED / 'hosts/profiles').glob('*.env'))
        self.assertEqual(set(records), {str(path.relative_to(ROOT)) for path in profiles})
        for path in profiles:
            with self.subTest(profile=path.name):
                record = records[str(path.relative_to(ROOT))]
                self.assertEqual(record['current_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertRegex(record['source_sha256'], r'^[0-9a-f]{64}$')
                self.assertRegex(record['destination_sha256'], r'^[0-9a-f]{64}$')

    def test_single_and_multiple_matching_profiles_pass(self):
        self.assertEqual(self.checker.check(self.seed), 1)
        (self.profiles / 'b.env').write_text(pin_text())
        self.assertEqual(self.checker.check(self.seed), 2)

    def test_comments_are_not_assignments(self):
        self.profile.write_text('# RESCTL_BENCH_SHA256="bad"\n\n' + pin_text())
        self.assertEqual(self.checker.check(self.seed), 1)

    def test_each_missing_pin_is_rejected(self):
        for key in PINS:
            self.profile.write_text(''.join(line + '\n' for line in pin_text().splitlines()
                                           if not line.startswith('RESCTL_BENCH_' + key + '=')))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'missing RESCTL_BENCH_' + key):
                self.checker.check(self.seed)

    def test_each_duplicate_pin_is_rejected_even_when_values_match(self):
        for key, value in PINS.items():
            self.profile.write_text(pin_text() + f'RESCTL_BENCH_{key}="{value}"\n')
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'duplicate RESCTL_BENCH_' + key):
                self.checker.check(self.seed)

    def test_syntactically_valid_but_different_profile_pin_is_rejected(self):
        changes = ({'SHA256': '0' * 64}, {'MAXIMUM_BYTES': '536870911'},
                   {'MAXIMUM_EXTRACTED_BYTES': '2147483647'}, {'MAXIMUM_MEMBERS': '8191'},
                   {'URL': PINS['URL'].replace('-' + BUILD_ID, '')})
        for change in changes:
            (self.profiles / 'b.env').write_text(pin_text(**change))
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'pins differ from a.env'):
                self.checker.check(self.seed)

    def test_checker_invokes_real_installer_policy_not_just_regex_or_profile_agreement(self):
        # All profiles agree, but policy still rejects this otherwise legal literal.
        self.profile.write_text(pin_text(URL=PINS['URL'] + '?invalid'))
        with self.assertRaisesRegex(ValueError, 'invalid RESCTL_BENCH_URL'):
            self.checker.check(self.seed)

    def test_empty_profile_set_and_symlink_profile_are_rejected(self):
        self.profile.unlink()
        with self.assertRaisesRegex(ValueError, 'no desktop profiles'):
            self.checker.check(self.seed)
        target = self.root / 'elsewhere'
        target.write_text(pin_text())
        self.profile.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'bounded regular file'):
            self.checker.check(self.seed)

    def test_nonliteral_shell_expressions_never_execute(self):
        marker = self.root / 'must-not-exist'
        for expression in ('$(touch ' + str(marker) + ')', '`touch ' + str(marker) + '`', '$EVIL', 'a\\b'):
            self.profile.write_text(pin_text(SHA256=expression))
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, 'literal'):
                self.checker.check(self.seed)
        self.assertFalse(marker.exists())

    def test_unknown_keys_and_nondecimal_or_oversized_bounds_are_rejected(self):
        self.profile.write_text(pin_text() + 'RESCTL_BENCH_IGNORE_CHECKSUM="true"\n')
        with self.assertRaisesRegex(ValueError, 'unknown RESCTL_BENCH_IGNORE_CHECKSUM'):
            self.checker.check(self.seed)
        for value in ('', '-1', '+1024', '0x20000000', '1e8', '9' * 1000):
            self.profile.write_text(pin_text(MAXIMUM_BYTES=value))
            with self.subTest(value=value[:40]), self.assertRaisesRegex(ValueError, 'bounded decimal'):
                self.checker.check(self.seed)

    def test_build_and_build_check_reject_invalid_pins_before_touching_products(self):
        tools = self.root / 'tools'
        tools.mkdir()
        for name in ('build.py', 'check_resctl_bench.py'):
            shutil.copyfile(ROOT / 'tools' / name, tools / name)
        products = ('preseed.cfg', 'payload.tar.gz', 'payload.manifest')
        for name in products:
            (self.seed / name).write_bytes(b'untouched release sentinel\n')
        # No browser/build helper is present: pin errors MUST happen first.
        for kind in ('invalid-url', 'profile-drift'):
            self.profile.write_text(pin_text(URL=PINS['URL'] + '?bad') if kind == 'invalid-url' else pin_text())
            if kind == 'profile-drift':
                (self.profiles / 'b.env').write_text(pin_text(SHA256='0' * 64))
            for flag in ([], ['--check']):
                with self.subTest(kind=kind, flag=flag):
                    result = subprocess.run([sys.executable, '-I', '-B', str(tools / 'build.py'), *flag],
                                            cwd='/', text=True, capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('resctl-bench preflight:', result.stderr)
                    for name in products:
                        self.assertEqual((self.seed / name).read_bytes(), b'untouched release sentinel\n')


if __name__ == '__main__':
    unittest.main()
