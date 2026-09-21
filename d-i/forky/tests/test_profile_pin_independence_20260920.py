"""R5: independent pins through real build and shell dispatch paths.

Alternate releases and digests below are synthetic offline configuration data.
No artifact is downloaded or executed; run_in_target is intercepted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / 'd-i/forky'


def load_checker():
    return runpy.run_path(str(ROOT / 'tools/check_resctl_bench.py'), run_name='profile_pin_checker')


def resctl_fixture(number: int) -> dict[str, str]:
    version = f'2.2.{number + 6}'
    tag = f'resctl-bench-v0.0.{number + 2}-Fixture'
    return {
        'VERSION': version,
        'TAG': tag,
        'ARCHITECTURE': 'amd64',
        'URL': ('https://github.com/mjcramerz/resctl-bench/releases/download/'
                f'{tag}/resctl-bench-{version}-x86_64-unknown-linux-gnu-native-{number:016x}.tar.gz'),
        'SHA256': hashlib.sha256(f'synthetic fixture {number}'.encode()).hexdigest(),
        'MAXIMUM_BYTES': str(134217728 + number),
        'MAXIMUM_EXTRACTED_BYTES': str(268435456 + number),
        'MAXIMUM_MEMBERS': str(100 + number),
    }


def tomat_fixture(number: int) -> dict[str, str]:
    version = f'2.{13 + number}.0'
    return {
        'SOFTWARE_TOMAT_TAG': f'v{version}',
        'SOFTWARE_TOMAT_URL': ('https://github.com/jolars/tomat/releases/download/'
                               f'v{version}/tomat_{version}-{number + 1}_amd64.deb'),
        'SOFTWARE_TOMAT_SHA256': hashlib.sha256(f'synthetic Tomat {number}'.encode()).hexdigest(),
    }


def pin_text(pins: dict[str, str]) -> str:
    return ''.join(f'RESCTL_BENCH_{key}="{value}"\n' for key, value in pins.items())


def update_profile(path: Path, number: int) -> None:
    values = {**{'RESCTL_BENCH_' + k: v for k, v in resctl_fixture(number).items()},
              **tomat_fixture(number)}
    text = path.read_text()
    for key, value in values.items():
        text, count = re.subn(r'^' + key + r'="[^"\n]*"$', f'{key}="{value}"', text, flags=re.M)
        if count != 1:
            raise AssertionError(f'{path.name}: expected exactly one {key}')
    path.write_text(text)


class IndependentPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.seed = Path(temporary.name)
        self.profiles = self.seed / 'hosts/profiles'
        self.profiles.mkdir(parents=True)
        helper = self.seed / 'scripts/desktop/resctl-bench-install.py'
        helper.parent.mkdir(parents=True)
        shutil.copyfile(SEED / 'scripts/desktop/resctl-bench-install.py', helper)
        self.checker = load_checker()

    def test_thirteen_distinct_releases_and_bounds_pass_without_mutation(self):
        paths = []
        for index in range(13):
            path = self.profiles / f'{index:02}.env'
            path.write_text(pin_text(resctl_fixture(index)))
            paths.append(path)
        before = {p.name: p.read_bytes() for p in paths}
        self.assertEqual(self.checker['check'](self.seed), 13)
        self.assertEqual(before, {p.name: p.read_bytes() for p in paths})

    def test_one_profile_can_change_with_no_edit_to_others(self):
        first = self.profiles / 'a.env'
        second = self.profiles / 'b.env'
        first.write_text(pin_text(resctl_fixture(0)))
        second.write_bytes(first.read_bytes())
        self.assertEqual(self.checker['check'](self.seed), 2)
        unchanged = first.read_bytes()
        second.write_text(pin_text(resctl_fixture(12)))
        self.assertEqual(self.checker['check'](self.seed), 2)
        self.assertEqual(first.read_bytes(), unchanged)

    def test_no_sorted_reference_profile_controls_other_profiles(self):
        for order in ((0, 1), (1, 0)):
            with self.subTest(order=order):
                for name, number in zip(('a.env', 'b.env'), order):
                    (self.profiles / name).write_text(pin_text(resctl_fixture(number)))
                self.assertEqual(self.checker['check'](self.seed), 2)

    def test_each_profile_must_match_its_own_tag_not_a_neighbors(self):
        first = resctl_fixture(0)
        second = resctl_fixture(1)
        (self.profiles / 'a.env').write_text(pin_text(first))
        (self.profiles / 'b.env').write_text(pin_text(dict(second, URL=first['URL'])))
        with self.assertRaisesRegex(ValueError, r'b.env.*invalid RESCTL_BENCH_URL'):
            self.checker['check'](self.seed)

    def test_invalid_later_profile_is_not_skipped(self):
        (self.profiles / 'a.env').write_text(pin_text(resctl_fixture(0)))
        (self.profiles / 'z.env').write_text(pin_text(dict(resctl_fixture(1), SHA256='bad')))
        with self.assertRaisesRegex(ValueError, r'z.env.*invalid RESCTL_BENCH_SHA256'):
            self.checker['check'](self.seed)

    def test_security_checks_apply_to_every_profile(self):
        (self.profiles / 'a.env').write_text(pin_text(resctl_fixture(0)))
        second = self.profiles / 'z.env'
        for change in ({'ARCHITECTURE': 'arm64'}, {'MAXIMUM_MEMBERS': '16385'},
                       {'URL': resctl_fixture(1)['URL'].replace('github.com/', 'example.com/')},
                       {'MAXIMUM_EXTRACTED_BYTES': '1024'}):
            with self.subTest(change=change):
                second.write_text(pin_text(dict(resctl_fixture(1), **change)))
                with self.assertRaises(ValueError):
                    self.checker['check'](self.seed)

    def test_tomat_also_accepts_distinct_profiles_and_checks_each(self):
        build = runpy.run_path(str(ROOT / 'tools/build.py'), run_name='profile_build')
        namespace = build['validate_tomat_profiles'].__globals__
        with mock.patch.dict(namespace, {'SEED': self.seed}):
            for number in range(13):
                (self.profiles / f'{number:02}.env').write_text(
                    ''.join(f'{k}="{v}"\n' for k, v in tomat_fixture(number).items()))
            build['validate_tomat_profiles']()
            last = self.profiles / '12.env'
            last.write_text(last.read_text().replace('v2.25.0', 'v9.99.0', 1))
            with self.assertRaisesRegex(ValueError, r'12.env: Tomat URL'):
                build['validate_tomat_profiles']()


class BuildAndDispatchTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('make'), 'make is needed for the real build entry point')
    def test_real_make_build_and_check_preserve_ten_distinct_pin_sets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in ('d-i', 'tools', 'browser-config'):
                shutil.copytree(ROOT / directory, root / directory,
                                ignore=shutil.ignore_patterns('tests', '__pycache__', '.pytest_cache'))
            shutil.copyfile(ROOT / 'Makefile', root / 'Makefile')
            seed = root / 'd-i/forky'
            profiles = sorted((seed / 'hosts/profiles').glob('*.env'))
            self.assertEqual(len(profiles), 10)
            for index, profile in enumerate(profiles):
                update_profile(profile, index)
            before = {str(p.relative_to(seed)): p.read_bytes() for p in profiles}
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
            for target in ('build', 'check'):
                result = subprocess.run(['make', target, 'PYTHON=' + sys.executable],
                                        cwd=root, env=env, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('10 profiles have independently valid release pins', result.stdout)
            self.assertEqual(before, {str(p.relative_to(seed)): p.read_bytes() for p in profiles})
            manifest = dict(line.split('  ', 1)[::-1]
                            for line in (seed / 'payload.manifest').read_text().splitlines())
            with tarfile.open(seed / 'payload.tar.gz', 'r:gz') as archive:
                for name, data in before.items():
                    with self.subTest(profile=name), archive.extractfile(name) as stream:
                        self.assertEqual(stream.read(), data)
                        self.assertEqual(manifest[name], hashlib.sha256(data).hexdigest())
            products = {name: (seed / name).read_bytes()
                        for name in ('payload.tar.gz', 'payload.manifest', 'preseed.cfg')}
            # Invalid pins must still stop both commands without replacing products.
            last = profiles[-1]
            last.write_text(last.read_text().replace('RESCTL_BENCH_SHA256="', 'RESCTL_BENCH_SHA256="bad', 1))
            for target in ('build', 'check'):
                result = subprocess.run(['make', target, 'PYTHON=' + sys.executable],
                                        cwd=root, env=env, capture_output=True, text=True, timeout=120)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('invalid RESCTL_BENCH_SHA256', result.stderr)
                self.assertEqual(products, {name: (seed / name).read_bytes() for name in products})

    def test_real_shell_forwards_each_profile_pins_without_reusing_previous_release(self):
        shells = [['/bin/sh']]
        if shutil.which('busybox'):
            shells.append([shutil.which('busybox'), 'sh'])
        script = r'''
set -eu
. "$1"
. "$2"
work=$3
python=$4
capture=$work/argv.json
capture_in_target() { printf '%s\n' amd64; }
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
target_asset_host_path() { printf '%s/helper\n' "$work"; }
installer_repo_join_var() { printf 'scripts/desktop/%s\n' "$2"; }
stage_target_asset() { : >"$work/helper"; }
desktop_log() { :; }
run_in_target() {
    shift
    "$python" -B -c 'import json,sys;open(sys.argv[1],"w").write(json.dumps(sys.argv[2:]))' "$capture" "$@"
}
desktop_install_resctl_bench
'''
        flags = {'VERSION': '--version', 'TAG': '--tag', 'URL': '--url', 'SHA256': '--sha256',
                 'ARCHITECTURE': '--architecture', 'MAXIMUM_BYTES': '--max-archive',
                 'MAXIMUM_EXTRACTED_BYTES': '--max-extracted', 'MAXIMUM_MEMBERS': '--max-members'}
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            profile = work / 'profile.env'
            for shell in shells:
                for index in range(13):
                    pins = resctl_fixture(index)
                    profile.write_text(pin_text(pins))
                    with self.subTest(shell=shell, profile=index):
                        result = subprocess.run([*shell, '-c', script, 'profile-dispatch', str(profile),
                                                 str(SEED / 'scripts/desktop/resctl-bench.sh'),
                                                 str(work), sys.executable],
                                                env=dict(os.environ, RESCTL_BENCH_TAG='stale-parent-tag'),
                                                capture_output=True, text=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        args = json.loads((work / 'argv.json').read_text())
                        for key, flag in flags.items():
                            self.assertEqual(args[args.index(flag) + 1], pins[key])
                        self.assertFalse((work / 'helper').exists())


if __name__ == '__main__':
    unittest.main()
