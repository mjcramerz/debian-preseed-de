"""R4: pinned Tomat bootstrap and versioned release-asset regressions.

Offline fixtures are synthetic Debian archives, not vendor binaries. Method
harnesses execute the unmodified production Perl method bodies with real core
Perl, SHA-256, dpkg-deb and filesystems. Only HTTP, Moo construction/accessors and
chroot installation are doubled. A separate dependency-gated test loads the full
Moo/MooX module. No test installs a package or starts/stops a service.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
FORKY = ROOT / 'd-i/forky'
PROFILES = FORKY / 'hosts/profiles'
PERL_LIB = FORKY / 'hooks/target/usr/local/lib/perl5/site_perl/external-managed-software'
MODULES = PERL_LIB / 'ExternalSoftware/Servicing'
SOFTWARE = FORKY / 'scripts/late/software.sh'
TAG = 'v2.13.0'
URL = 'https://github.com/jolars/tomat/releases/download/v2.13.0/tomat_2.13.0-1_amd64.deb'
SHA256 = '871ee4fd19f3367cf4aa638a2364ae83de6c4ce4550a7ebe5ee6124be86c6aa1'
PINS = dict(SOFTWARE_TOMAT_TAG=TAG, SOFTWARE_TOMAT_URL=URL, SOFTWARE_TOMAT_SHA256=SHA256)


def load_build():
    spec = importlib.util.spec_from_file_location('r4_build', ROOT / 'tools/build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def method(file: str, name: str) -> str:
    match = re.search(r'^sub ' + re.escape(name) + r' \{.*?^\}',
                      (MODULES / file).read_text(), re.M | re.S)
    if not match:
        raise AssertionError(f'Cannot find production method: {file}:{name}')
    return match[0]


def perl_methods() -> str:
    """Core-only execution; this is not an emulation or test of Moo itself."""
    return (r'''
use strict; use warnings; use JSON::PP; use Digest::SHA;
{ package ExternalSoftware::Servicing::Atomic;
use Fcntl qw(:DEFAULT O_NOFOLLOW); use Errno qw(EINTR);
''' + '\n'.join(method('Atomic.pm', m) for m in ('assert_absolute_path', 'read_limited')) + r'''
}
{ package ExternalSoftware::Servicing::Deb;
use Fcntl qw(O_NOFOLLOW O_NONBLOCK O_RDONLY S_IFMT S_IFREG);
use Errno qw(EINTR);
use ExternalSoftware::Servicing::ArtifactLimits qw(MAX_DEB_BYTES);
''' + '\n'.join(method('Deb.pm', m) for m in (
    '_capture', '_capture_limited', 'control', '_archive_identity', '_archive_listing',
    '_listing_mode', '_listing_contains', 'validate')) + r'''
}
{ package ExternalSoftware::Servicing::Tomat;
use Digest::SHA; use JSON::PP qw(decode_json);
sub http { $_[0]->{http} } sub deb { $_[0]->{deb} }
''' + '\n'.join(method('Tomat.pm', m) for m in (
    '_sha256', '_pinned_release', '_release', 'download', 'download_pinned', '_download_release')) + '\n}\n')


HTTP_FIXTURE = r'''
{ package FixtureHTTP;
use File::Copy qw(copy);
sub download {
    my ($self, %a) = @_;
    push @{$self->{calls}}, { %a };
    die "fixture network unavailable\n" if $self->{options}->{http_failure};
    if ($a{content_policy} eq 'metadata') {
        copy($self->{metadata}, $a{destination}) or die "fixture metadata copy: $!";
    } else {
        copy($self->{artifact}, $a{destination}) or die "fixture artifact copy: $!";
        if ($self->{options}->{symlink}) {
            unlink $a{destination} or die $!;
            symlink $self->{artifact}, $a{destination} or die $!;
        }
        if (defined $self->{options}->{truncate}) {
            truncate $a{destination}, $self->{options}->{truncate} or die $!;
        }
    }
}
}
'''

HARNESS_MAIN = r'''
my $o = decode_json($ARGV[0]);
my $http = bless({calls => [], options => $o, artifact => $ARGV[1], metadata => $ARGV[2]}, 'FixtureHTTP');
my $adapter = bless({http => $http, deb => bless({}, 'ExternalSoftware::Servicing::Deb')},
                    'ExternalSoftware::Servicing::Tomat');
my $result;
my $ok = eval {
    if ($o->{operation} eq 'pin') {
        $result = $adapter->_pinned_release($o->{tag}, $o->{url}, $o->{sha256});
    } elsif ($o->{operation} eq 'release') {
        $result = $adapter->_release($ARGV[2]);
    } elsif ($o->{operation} eq 'latest') {
        $result = $adapter->download($ARGV[3]);
    } else {
        $result = $adapter->download_pinned($ARGV[3], $o->{tag}, $o->{url}, $o->{sha256});
    }
    1;
};
my $error = $@;
print "\nR4_RESULT=" . encode_json({ok => $ok ? 1 : 0, error => $error, result => $result, calls => $http->{calls}}) . "\n";
'''


class TomatProfilePinsTests(unittest.TestCase):
    def test_all_thirteen_profiles_have_exact_literal_pins(self):
        profiles = sorted(PROFILES.glob('*.env'))
        self.assertEqual(len(profiles), 13)
        for profile in profiles:
            with self.subTest(profile=profile.name):
                lines = [line for line in profile.read_text().splitlines() if line.startswith('SOFTWARE_TOMAT_')]
                self.assertEqual(len(lines), 3)
                self.assertEqual(set(lines), {f'{key}="{value}"' for key, value in PINS.items()})
        load_build().validate_tomat_profiles()

    def validate_fixture(self, values=None, extra=''):
        values = PINS if values is None else values
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp); profiles = seed / 'hosts/profiles'; profiles.mkdir(parents=True)
            (profiles / 'fixture.env').write_text(''.join(f'{key}="{value}"\n' for key, value in values.items()) + extra)
            build = load_build()
            with mock.patch.object(build, 'SEED', seed):
                build.validate_tomat_profiles()

    def test_builder_accepts_coherent_future_pin_without_hardcoded_release(self):
        self.validate_fixture({**PINS, 'SOFTWARE_TOMAT_TAG': 'v2.14.0',
            'SOFTWARE_TOMAT_URL': URL.replace('2.13.0', '2.14.0').replace('-1_', '-2_'),
            'SOFTWARE_TOMAT_SHA256': 'a' * 64})

    def test_builder_rejects_missing_empty_duplicate_unknown_or_nonliteral_pins(self):
        for key in PINS:
            with self.subTest(key=key, case='missing'), self.assertRaises(ValueError):
                self.validate_fixture({k: v for k, v in PINS.items() if k != key})
            for value in ('', '$VALUE', '`false`', '"', '\\', '\t'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.validate_fixture({**PINS, key: value})
            for prefix in ('', ' ', 'export '):
                with self.subTest(key=key, prefix=prefix), self.assertRaises(ValueError):
                    self.validate_fixture(extra=f'{prefix}{key}="{PINS[key]}"\n')
        with self.assertRaises(ValueError):
            self.validate_fixture(extra='SOFTWARE_TOMAT_EXTRA="x"\n')

    def test_builder_rejects_wrong_tag_url_architecture_revision_or_digest(self):
        for key, value in bad_pins():
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.validate_fixture({**PINS, key: value})

    def test_builder_rejects_no_profiles_and_checks_before_writes(self):
        build = load_build()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build, 'SEED', Path(tmp)):
            with self.assertRaises(ValueError): build.validate_tomat_profiles()
        main = (ROOT / 'tools/build.py').read_text().split('def main() -> int:', 1)[1]
        self.assertLess(main.index('validate_tomat_profiles()'), main.index('products = build()'))

    def test_real_shell_profile_to_chroot_argv_for_every_profile(self):
        text = SOFTWARE.read_text()
        start = text.index('chroot "$target_root" /usr/bin/perl', text.index('# Bootstrap only the profile-pinned Tomat'))
        block = text[start:text.index('# Neither a packaged system daemon', start)]
        shells = [['/bin/sh']]
        if shutil.which('busybox'): shells.append([shutil.which('busybox'), 'sh'])
        with tempfile.TemporaryDirectory() as tmp:
            captured = Path(tmp) / 'argv.json'
            for shell in shells:
                for profile in sorted(PROFILES.glob('*.env')):
                    with self.subTest(shell=shell, profile=profile.name):
                        code = r'''
set -eu
. "$1"
target_root=/target
work_dir=/tmp/installer-software
capture=$2
software_fatal() { printf '%s\n' "$*" >&2; exit 1; }
chroot() { /usr/bin/python3 -c 'import json,sys;open(sys.argv[1],"w").write(json.dumps(sys.argv[2:]))' "$capture" "$@"; }
''' + block
                        result = subprocess.run([*shell, '-c', code, 'r4-tomat', str(profile), str(captured)],
                            env={**os.environ, 'SOFTWARE_TOMAT_TAG': 'v999.0.0', 'SOFTWARE_TOMAT_URL': 'invalid'},
                            text=True, capture_output=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        args = json.loads(captured.read_text())
                        self.assertEqual(args[:2], ['/target', '/usr/bin/perl'])
                        self.assertEqual(args[-5:], ['--', '/tmp/installer-software', TAG, URL, SHA256])
                        self.assertIn('->download_pinned(@ARGV)', args[args.index('-e') + 1])
                        self.assertNotIn('releases/latest', args[args.index('-e') + 1])
        self.assertLess(text.index('. "$host_env"'), text.index('${SOFTWARE_TOMAT_TAG:?'))

    def test_failure_stops_before_service_masks_and_installation(self):
        text = SOFTWARE.read_text()
        start = text.index('chroot "$target_root" /usr/bin/perl', text.index('# Bootstrap only the profile-pinned Tomat'))
        end = text.index('software_download \\\n  "Postman"', start)
        block = text[start:end]
        code = r'''
set -eu
. "$1"
target_root=/target; work_dir=/tmp/installer-software; tomat_deb=$work_dir/tomat.deb
software_fatal() { printf 'FATAL:%s\n' "$*"; exit 1; }
chroot() { printf 'CHROOT\n'; return 9; }
software_install_deb() { printf 'UNREACHABLE_INSTALL\n'; }
''' + block
        result = subprocess.run(['/bin/sh', '-c', code, 'r4', str(PROFILES / 'vm-desktop.env')],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.count('CHROOT\n'), 1)
        self.assertIn('FATAL:Tomat verified binary download failed', result.stdout)
        self.assertNotIn('UNREACHABLE', result.stdout)


def bad_pins():
    return ([('SOFTWARE_TOMAT_TAG', value) for value in
             ('2.13.0', 'v2.13', 'latest', 'v2.13.0-rc1', 'v2.13.0\n', 'v' + '1' * 33 + '.0.0')]
            + [('SOFTWARE_TOMAT_URL', value) for value in
               (URL.replace('https:', 'http:'), URL.replace('github.com/', 'github.com.evil.invalid/'),
                URL.replace('jolars/', 'other/'), URL.replace('/v2.13.0/', '/v2.14.0/'),
                URL.replace('tomat_2.13.0-', 'tomat_2.12.0-'), URL.replace('_amd64.', '_arm64.'),
                URL.replace('_amd64.', '_all.'), URL.replace('tomat_2.13.0-1', 'tomat'),
                URL.replace('-1_', '-01_'), URL.replace('-1_', '-0_'), URL.replace('-1_', '-1-2_'),
                URL.replace('-1_', '-1234567890_'), URL + '?download=1', URL + '#fragment', URL + '\n',
                URL.replace('github.com/', 'user@github.com/'), URL.replace('/v2.13.0/', '/v2.13.0/../v2.13.0/'))]
            + [('SOFTWARE_TOMAT_SHA256', value) for value in ('a' * 63, 'a' * 65, 'G' * 64, SHA256.upper(), SHA256 + '\n')])


@unittest.skipUnless(shutil.which('perl') and shutil.which('dpkg-deb'), 'core Perl and dpkg-deb required')
class TomatPerlPinMethodsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='r4-tomat-fixtures-')
        cls.root = Path(cls.temp.name)
        cls.code = perl_methods() + HTTP_FIXTURE + HARNESS_MAIN
        cls.package = cls.make_package('valid')
        cls.digest = hashlib.sha256(cls.package.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def make_package(cls, name, *, package='tomat', version='2.13.0-1', architecture='amd64', executable=True):
        tree = cls.root / name; control = tree / 'DEBIAN'; control.mkdir(parents=True)
        (control / 'control').write_text(f'Package: {package}\nVersion: {version}\nArchitecture: {architecture}\n'
            'Maintainer: R4 Fixture <fixture@example.invalid>\nDescription: Synthetic validation archive, not vendor Tomat\n')
        padding = tree / 'usr/share/doc/tomat/padding'; padding.parent.mkdir(parents=True)
        padding.write_bytes(b'fixture-only\n' * 12000)
        if executable:
            binary = tree / 'usr/bin/tomat'; binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nexit 0\n'); binary.chmod(0o755)
        path = cls.root / (name + '.deb')
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Znone', '--build', str(tree), str(path)],
                       check=True, capture_output=True, timeout=20)
        return path

    def release(self, name='tomat_2.13.0-1_amd64.deb'):
        return {'tag_name': TAG, 'draft': False, 'prerelease': False, 'assets': [
            {'name': name, 'browser_download_url': URL.rsplit('/', 1)[0] + '/' + name,
             'size': self.package.stat().st_size, 'digest': 'sha256:' + self.digest}]}

    def run_case(self, operation='pinned', *, release=None, package=None, **options):
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            work = Path(tmp); metadata = work / 'metadata.json'
            metadata.write_text(json.dumps(self.release() if release is None else release))
            values = dict(operation=operation, tag=TAG, url=URL, sha256=self.digest)
            values.update(options)
            result = subprocess.run(['perl', '-I', str(PERL_LIB), '-e', self.code, json.dumps(values),
                str(package or self.package), str(metadata), str(work)], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('R4_RESULT=', result.stdout)
            return json.loads(result.stdout.rsplit('R4_RESULT=', 1)[1])

    def test_pinned_download_uses_only_exact_asset_and_real_package_hash_metadata(self):
        result = self.run_case()
        self.assertEqual(result['ok'], 1, result['error'])
        self.assertEqual(result['result']['metadata'], {'package': 'tomat', 'version': '2.13.0-1', 'architecture': 'amd64'})
        self.assertEqual(len(result['calls']), 1)
        call = result['calls'][0]
        self.assertEqual(call['url'], URL)
        self.assertEqual((call['minimum'], call['maximum']), (65536, 134217728))
        self.assertEqual(call['content_policy'], 'artifact')
        self.assertEqual(call['allowed_hosts'], ['github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'])

    def test_user_supplied_pin_is_accepted_without_network_or_metadata(self):
        result = self.run_case('pin', sha256=SHA256)
        self.assertEqual(result['ok'], 1, result['error'])
        self.assertEqual(result['result']['sha256'], SHA256)
        self.assertEqual(result['result']['package_version'], '2.13.0-1')
        self.assertEqual(result['calls'], [])

    def test_invalid_pin_is_rejected_before_http(self):
        for key, value in bad_pins():
            field = key.removeprefix('SOFTWARE_TOMAT_').lower()
            with self.subTest(key=key, value=value):
                result = self.run_case(**{field: value})
                self.assertEqual(result['ok'], 0)
                self.assertEqual(result['calls'], [])

    def test_non_scalar_missing_or_empty_pin_is_rejected_before_http(self):
        for field in ('tag', 'url', 'sha256'):
            for value in (None, {}, [], ''):
                with self.subTest(field=field, value=value):
                    result = self.run_case(**{field: value})
                    self.assertEqual(result['ok'], 0)
                    self.assertEqual(result['calls'], [])

    def test_wrong_hash_fails_without_retry_or_fallback(self):
        result = self.run_case(sha256='0' * 64)
        self.assertEqual(result['ok'], 0)
        self.assertIn('digest or size', result['error'])
        self.assertEqual(len(result['calls']), 1)

    def test_network_failure_does_not_query_latest_or_retry_unverified_asset(self):
        result = self.run_case(http_failure=True)
        self.assertEqual(result['ok'], 0)
        self.assertEqual([c['url'] for c in result['calls']], [URL])

    def test_size_bounds_and_symlink_rejected_even_with_non_enforcing_http_double(self):
        for options in ({'truncate': 65535}, {'truncate': 134217729}, {'symlink': True}):
            with self.subTest(options=options):
                result = self.run_case(**options)
                self.assertEqual(result['ok'], 0)
                self.assertEqual(len(result['calls']), 1)

    def test_hash_valid_but_wrong_debian_identity_version_or_payload_is_rejected(self):
        for name, properties in (
            ('wrong-name', {'package': 'not-tomat'}), ('wrong-arch', {'architecture': 'arm64'}),
            ('wrong-version', {'version': '2.13.1-1'}), ('wrong-revision', {'version': '2.13.0-2'}),
            ('extra-revision', {'version': '2.13.0-1-2'}), ('missing-binary', {'executable': False})):
            with self.subTest(name=name):
                path = self.make_package(name, **properties)
                result = self.run_case(package=path, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(result['ok'], 0)
                self.assertEqual(len(result['calls']), 1)

    def test_latest_adapter_accepts_versioned_asset_and_checks_exact_version(self):
        result = self.run_case('latest')
        self.assertEqual(result['ok'], 1, result['error'])
        self.assertEqual(len(result['calls']), 2)
        self.assertEqual(result['calls'][1]['url'], URL)
        self.assertEqual(result['calls'][1]['minimum'], self.package.stat().st_size)
        self.assertEqual(result['calls'][1]['maximum'], self.package.stat().st_size)
        self.assertEqual(result['result']['metadata']['version'], '2.13.0-1')

    def test_release_keeps_legacy_compatibility_but_rejects_ambiguity(self):
        result = self.run_case('release', release=self.release('tomat_amd64.deb'))
        self.assertEqual(result['ok'], 1, result['error'])
        for asset in (self.release()['assets'][0], self.release('tomat_amd64.deb')['assets'][0],
                      self.release('tomat_2.13.0-2_amd64.deb')['assets'][0]):
            release = self.release(); release['assets'].append(asset)
            with self.subTest(name=asset['name']):
                result = self.run_case('release', release=release)
                self.assertEqual(result['ok'], 0)
                self.assertIn('no unique', result['error'])

    def test_release_ignores_other_architecture_and_nondebian_assets(self):
        release = self.release()
        release['assets'] += [self.release('tomat_2.13.0-1_arm64.deb')['assets'][0],
                              {'name': 'tomat-x86_64-unknown-linux-gnu.tar.gz'}]
        result = self.run_case('release', release=release)
        self.assertEqual(result['ok'], 1, result['error'])
        self.assertEqual(result['result']['url'], URL)

    def test_release_rejects_unstable_wrong_tag_origin_digest_size_and_filename(self):
        variants = []
        for key, value in (('draft', True), ('prerelease', True), ('tag_name', 'v2.13.0-rc1')):
            release = self.release(); release[key] = value; variants.append(release)
        for key, value in (('browser_download_url', URL.replace('jolars', 'other')), ('size', 0),
                ('size', 134217729), ('digest', None), ('name', 'tomat_2.12.0-1_amd64.deb')):
            release = self.release(); release['assets'][0][key] = value; variants.append(release)
        for release in variants:
            with self.subTest(release=release):
                self.assertEqual(self.run_case('release', release=release)['ok'], 0)

    def test_full_moo_module_pin_validation_when_dependencies_are_installed(self):
        from test_managed_external_software import ManagedExternalSoftwareTests
        code = r'''
use ExternalSoftware::Servicing::Tomat;
use JSON::PP;
my $adapter = ExternalSoftware::Servicing::Tomat->new(http => bless({}, 'Fixture'), deb => bless({}, 'Fixture'));
print encode_json($adapter->_pinned_release(@ARGV));
'''
        result = ManagedExternalSoftwareTests.run_perl(self, code, TAG, URL, SHA256)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['package_version'], '2.13.0-1')


class TomatVersionedUpdaterTests(unittest.TestCase):
    def setUp(self):
        from test_native_tomat_20260920 import load
        self.mod = load('local-apt-repository')
        self.release = {'id': 1, 'tag_name': TAG, 'published_at': '2026-08-28T13:02:59Z',
            'draft': False, 'prerelease': False, 'assets': [
                {'id': 2, 'name': URL.rsplit('/', 1)[1], 'browser_download_url': URL,
                 'size': 1000000, 'digest': 'sha256:' + SHA256, 'state': 'uploaded'}]}

    def discover(self, release=None, url=URL):
        with tempfile.TemporaryDirectory() as work:
            discovery = self.mod.Discovery(Path(work))
            with mock.patch.object(discovery, 'metadata', return_value=json.dumps([release or self.release]).encode()):
                return discovery.release(self.mod.source_for(url), 'tomat', 'amd64', Path(work))

    def test_actual_versioned_asset_works_with_pinned_repo_and_legacy_source_hints(self):
        for url in (URL, 'https://github.com/jolars/tomat/releases',
                    'https://github.com/jolars/tomat/releases/latest/download/tomat_amd64.deb'):
            with self.subTest(url=url):
                result = self.discover(url=url)
                self.assertEqual(result['url'], URL)
                self.assertEqual(result['version'], '2.13.0-1')
                self.assertEqual(result['sha256'], SHA256)

    def test_versioned_refresh_requires_exact_package_revision(self):
        fields = {'Package': 'tomat', 'Architecture': 'amd64', 'Version': '2.13.0-1'}
        self.mod.verify_tomat_release_version(fields, '2.13.0-1')
        for value in ('2.13.0', '2.13.0-2', '2.13.0-1-2', '2.13.0-1+evil'):
            with self.subTest(value=value), self.assertRaises(self.mod.Error):
                self.mod.verify_tomat_release_version({**fields, 'Version': value}, '2.13.0-1')

    def test_versioned_refresh_rejects_wrong_origin_tag_name_digest_size_and_duplicates(self):
        for key, value in (('browser_download_url', URL.replace('jolars', 'other')), ('size', 1),
                ('size', 134217729), ('digest', None), ('name', 'tomat_2.12.0-1_amd64.deb')):
            release = copy.deepcopy(self.release); release['assets'][0][key] = value
            with self.subTest(key=key), self.assertRaises(self.mod.Error): self.discover(release)
        release = copy.deepcopy(self.release); release['assets'].append(copy.deepcopy(release['assets'][0]))
        with self.assertRaises(self.mod.Error): self.discover(release)

    def test_versioned_refresh_selects_only_amd64_in_multiarchitecture_release(self):
        release = copy.deepcopy(self.release)
        arm = copy.deepcopy(release['assets'][0]); arm['name'] = arm['name'].replace('amd64', 'arm64')
        arm['browser_download_url'] = arm['browser_download_url'].replace('amd64', 'arm64'); arm['id'] = 3
        release['assets'].append(arm)
        self.assertEqual(self.discover(release)['url'], URL)

    def test_legacy_family_exception_does_not_change_other_repositories(self):
        with self.assertRaises(self.mod.Error):
            self.discover(url='https://github.com/other/tomat/releases/latest/download/tomat_amd64.deb')


if __name__ == '__main__':
    unittest.main()
