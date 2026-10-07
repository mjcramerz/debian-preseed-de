"""Pinned wheel transport and per-profile desktop release contracts, offline."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

SEED = Path(__file__).resolve().parents[1]
WAYPAPER = SEED / 'scripts/desktop/waypaper.sh'
SAMLOADER = SEED / 'scripts/desktop/samloader.sh'


def values(path: Path) -> dict[str, str]:
    return dict(re.findall(r'^([A-Z0-9_]+)="([^"\n]*)"$', path.read_text(encoding='utf-8'), re.M))


class WheelIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='waypaper-wheel-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'target'
        (self.target / 'opt/waypaper').mkdir(parents=True)
        self.fixture = self.root / 'fixture.whl'
        self.fixture.write_bytes(b'fixture wheel transport bytes\n' * 2000)
        self.policy = {key: value for key, value in values(SEED / 'hosts/profiles/btrfs-de.env').items()
                       if key.startswith('LABWC_WAYPAPER_')}
        self.policy.update(ACCOUNT_USERNAME='fixture', ACCOUNT_HOME='/home/fixture')
        self.source = WAYPAPER.read_text(encoding='utf-8').replace('/target', str(self.target))
        self.wheel = '/opt/waypaper/waypaper-2.9-py3-none-any.whl'

    def run_shell(self, action, **overrides):
        assignments = {**self.policy, **overrides}
        script = '\n'.join(key + '=' + shlex.quote(value) for key, value in assignments.items())
        script += '\n' + self.source + '\n' + r'''
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
desktop_require_absolute_account_home() { :; }
attempt_in_target() {
  shift
  output=
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --output ]; then shift; output=$1; fi
    shift
  done
  [ -n "$output" ] || return 1
  cp -- "$FIXTURE_WHEEL" "${FIXTURE_TARGET}${output}"
}
'''
        script += '\n' + action
        return subprocess.run(['/bin/sh', '-eu', '-c', script], text=True, encoding='utf-8',
                              capture_output=True, timeout=5,
                              env={**os.environ, 'FIXTURE_WHEEL': str(self.fixture),
                                   'FIXTURE_TARGET': str(self.target)})

    def test_pinned_url_validation_accepts_profiles_and_refuses_impostors(self):
        result = self.run_shell('desktop_waypaper_validate_policy')
        self.assertEqual(result.returncode, 0, result.stderr)
        for url in (
            self.policy['LABWC_WAYPAPER_URL'].replace('files.pythonhosted.org', 'files.pythonhosted.org.evil.invalid'),
            self.policy['LABWC_WAYPAPER_URL'].replace('2.9-py3', '2x9-py3'),
            self.policy['LABWC_WAYPAPER_URL'].replace('https:', 'http:'),
            self.policy['LABWC_WAYPAPER_URL'] + '?untrusted=1',
        ):
            with self.subTest(url=url):
                result = self.run_shell('desktop_waypaper_validate_policy', LABWC_WAYPAPER_URL=url)
                self.assertNotEqual(result.returncode, 0)

    def test_authenticated_fixture_is_published_only_after_hash_and_size_checks(self):
        digest = hashlib.sha256(self.fixture.read_bytes()).hexdigest()
        result = self.run_shell('desktop_waypaper_download_wheel ' + shlex.quote(self.wheel),
                                LABWC_WAYPAPER_SHA256=digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.target / self.wheel.lstrip('/')
        self.assertEqual(installed.read_bytes(), self.fixture.read_bytes())
        self.assertEqual(installed.stat().st_mode & 0o777, 0o644)
        self.assertEqual(list(installed.parent.glob('.waypaper-wheel.*')), [])

    def test_wrong_hash_and_oversized_or_truncated_downloads_are_not_published(self):
        for payload in (self.fixture.read_bytes(), b'truncated', b'x' * (1048576 + 1)):
            with self.subTest(size=len(payload)):
                self.fixture.write_bytes(payload)
                result = self.run_shell('desktop_waypaper_download_wheel ' + shlex.quote(self.wheel))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.target / self.wheel.lstrip('/')).exists())
                self.assertEqual(list((self.target / 'opt/waypaper').glob('.waypaper-wheel.*')), [])

    def test_symlink_destination_is_refused_without_touching_its_target(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'preserve')
        (self.target / self.wheel.lstrip('/')).symlink_to(outside)
        result = self.run_shell('desktop_waypaper_download_wheel ' + shlex.quote(self.wheel),
                                LABWC_WAYPAPER_SHA256=hashlib.sha256(self.fixture.read_bytes()).hexdigest())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outside.read_bytes(), b'preserve')


class SamloaderArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='samloader-zip-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / 'samloader.zip'
        self.destination = self.root / 'samloader'
        source = SAMLOADER.read_text(encoding='utf-8')
        match = re.search(r"/usr/bin/python3 -I -c '(.*?)' \\\n", source, re.S)
        self.assertIsNotNone(match, 'missing isolated ZIP extractor')
        self.extractor = match[1]

    def extract(self, maximum=33554432):
        return subprocess.run([sys.executable, '-I', '-c', self.extractor,
                               str(self.archive), str(self.destination), str(maximum), '4'],
                              text=True, encoding='utf-8', capture_output=True, timeout=5)

    def write_archive(self, entries):
        with zipfile.ZipFile(self.archive, 'w', compression=zipfile.ZIP_STORED) as archive:
            for member, data in entries:
                archive.writestr(member, data)

    def test_flat_regular_file_is_extracted_without_executing_it(self):
        self.write_archive([('samloader', b'fixture binary bytes')])
        result = self.extract()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.destination.read_bytes(), b'fixture binary bytes')

    def test_unexpected_paths_duplicates_directories_and_symlinks_are_refused(self):
        link = zipfile.ZipInfo('samloader')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entries in ([('../samloader', b'bad')], [('/samloader', b'bad')],
                        [('samloader/', b'')], [(link, b'/outside')],
                        [('samloader', b'first'), ('samloader', b'second')],
                        [('samloader', b'valid'), ('extra', b'bad')]):
            with self.subTest(entries=entries):
                if len(entries) == 2 and entries[0][0] == entries[1][0]:
                    with self.assertWarns(UserWarning):
                        self.write_archive(entries)
                else:
                    self.write_archive(entries)
                result = self.extract()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.destination.exists())

    def test_existing_destination_symlink_is_never_followed(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'preserve')
        self.destination.symlink_to(outside)
        self.write_archive([('samloader', b'fixture')])
        result = self.extract()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outside.read_bytes(), b'preserve')

    def test_declared_uncompressed_size_is_bounded_before_writing(self):
        self.write_archive([('samloader', b'x' * 1025)])
        result = self.extract(maximum=1024)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.destination.exists())

    def test_corrupt_payload_fails_crc_validation(self):
        self.write_archive([('samloader', b'uncorrupted payload')])
        data = self.archive.read_bytes().replace(b'uncorrupted payload', b'Xncorrupted payload', 1)
        self.archive.write_bytes(data)
        result = self.extract()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CRC', result.stderr)


@unittest.skipUnless(shutil.which('perl'), 'native Perl interpreter unavailable')
class SamsungFirmwareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='samsung-provenance-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'samsung-firmware'
        self.directory = self.root / 'fixture'
        (self.directory / 'files').mkdir(parents=True)
        self.manifest = dict(format='managed-v1', samloader_version='2.2.0',
                             model='SM-S931U1', region='XAA', firmware_version='FIXTURE/CSC/MODEM')
        for component in ('BL', 'AP', 'CP', 'CSC', 'HOME_CSC'):
            path = self.directory / 'files' / (component + '_fixture.tar.md5')
            path.write_bytes(b'fixture component ' + component.encode('ascii'))
            key = component.lower()
            self.manifest[key + '_file'] = 'files/' + path.name
            self.manifest[key + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def load_firmware(self):
        (self.directory / '.firmware').write_text(
            ''.join(key + '=' + value + '\n' for key, value in self.manifest.items()), encoding='utf-8')
        # Execute the real provenance/path/SHA-256 validation. Device access and
        # vendor MD5 execution are explicit stubs; no flash or download is run.
        fixture = r'''
use strict;
use warnings;
use AndroidADB::Vendor::Samsung;
use AndroidADB::Firmware::Manifest;
{
    package FixtureStorage;
    use Digest::SHA;
    sub prepare_output_directory { return $_[0]->{root}; }
    sub require_regular_file { die "not a regular fixture file\n" if !-f $_[1] || -l $_[1]; }
    sub file_sha256 {
        open my $file, "<", $_[1] or die "fixture open failed: $!\n";
        binmode $file;
        my $hash = Digest::SHA->new(256)->addfile($file)->hexdigest;
        close $file or die "fixture close failed: $!\n";
        return $hash;
    }
    package FixtureConfig;
    sub samsung_firmware_format { return "managed-v1"; }
    package FixtureArchive;
    sub verify_md5 { die "expected five verified components\n" if @_ != 6; print "md5-fixture\n"; }
}
my ($root, $directory) = @ARGV;
my $storage = bless {root => $root}, "FixtureStorage";
my $unused = bless {}, "FixtureUnused";
my $samsung = AndroidADB::Vendor::Samsung->new(
    config => bless({}, "FixtureConfig"), command => $unused, device => $unused,
    lock => $unused, storage => $storage, archive => bless({}, "FixtureArchive"),
    manifest => AndroidADB::Firmware::Manifest->new(storage => $storage),
);
$samsung->load_managed_firmware($directory);
print "verified-fixture\n";
'''
        return subprocess.run(['perl', '-I', str(SEED / 'hooks/target/usr/local/lib/perl5/site_perl/labwc-adb'),
                               '-e', fixture, str(self.root), str(self.directory)],
                              text=True, encoding='utf-8', capture_output=True, timeout=10,
                              env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})

    def test_existing_and_current_download_provenance_are_accepted(self):
        for version in ('2.0.0', '2.2.0'):
            with self.subTest(version=version):
                self.manifest['samloader_version'] = version
                result = self.load_firmware()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), ['md5-fixture', 'verified-fixture'])

    def test_unknown_download_provenance_is_refused(self):
        self.manifest['samloader_version'] = 'untrusted'
        result = self.load_firmware()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported samloader-rs download version', result.stderr)
        self.assertNotIn('md5-fixture', result.stdout)

    def test_component_tampering_is_refused_before_vendor_validation(self):
        (self.directory / self.manifest['ap_file']).write_bytes(b'changed component')
        result = self.load_firmware()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('component SHA-256 changed', result.stderr)
        self.assertNotIn('md5-fixture', result.stdout)


class DesktopReleaseContractTests(unittest.TestCase):
    def test_profile_owned_deb_policy_rejects_bad_bindings_before_download(self):
        source = (SEED / 'scripts/late/software.sh.tmpl').read_text(encoding='utf-8')
        functions = source[:source.index('software_validate_abs_path "target root"')]
        start = source.index('obsidian_version=${SOFTWARE_OBSIDIAN_VERSION:')
        obsidian = source[start:source.index('\nobsidian_deb=', start)]
        start = source.index('sleek_version=${SOFTWARE_SLEEK_VERSION:')
        sleek = source[start:source.index('\nsleek_deb=', start)]
        policy = {key: value for key, value in values(SEED / 'hosts/profiles/btrfs-de.env').items()
                  if key.startswith(('SOFTWARE_OBSIDIAN_', 'SOFTWARE_SLEEK_'))}
        cases = ({}, {'SOFTWARE_OBSIDIAN_URL': policy['SOFTWARE_OBSIDIAN_URL'] + '?untrusted=1'},
                 {'SOFTWARE_SLEEK_VERSION': '2x0x29'}, {'SOFTWARE_SLEEK_SHA256': 'a' * 63},
                 {'SOFTWARE_OBSIDIAN_MAXIMUM_BYTES': '536870913'},
                 {'SOFTWARE_SLEEK_MINIMUM_BYTES': '134217729'})
        for overrides in cases:
            with self.subTest(overrides=overrides):
                assignments = '\n'.join(key + '=' + shlex.quote(value)
                                        for key, value in {**policy, **overrides}.items())
                result = subprocess.run(['/bin/sh', '-eu', '-c',
                                         functions + '\n' + assignments + '\n' + obsidian + '\n' + sleek],
                                        text=True, encoding='utf-8', capture_output=True, timeout=5)
                self.assertEqual(result.returncode == 0, not overrides, result.stderr)

    def test_all_profiles_validate_release_urls_and_hashes_before_installation(self):
        profiles = sorted((SEED / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for profile in profiles:
            policy = values(profile)
            with self.subTest(profile=profile.name):
                for name in ('QOREDB', 'OBSIDIAN', 'SLEEK'):
                    version = policy['SOFTWARE_' + name + '_VERSION']
                    url = policy['SOFTWARE_' + name + '_URL']
                    self.assertRegex(version, r'^\d+\.\d+\.\d+$')
                    self.assertIn('/v' + version + '/', url)
                    self.assertIn(version, url.rsplit('/', 1)[1])
                    self.assertRegex(policy['SOFTWARE_' + name + '_SHA256'], r'^[0-9a-f]{64}$')
                self.assertIn('/v' + policy['LABWC_SATTY_VERSION'] + '/', policy['LABWC_SATTY_URL'])
                self.assertIn('/' + policy['SOFTWARE_TOMAT_TAG'] + '/', policy['SOFTWARE_TOMAT_URL'])
                self.assertRegex(policy['LABWC_WAYPAPER_SHA256'], r'^[0-9a-f]{64}$')
                minimum = int(policy['LABWC_WAYPAPER_MINIMUM_BYTES'])
                maximum = int(policy['LABWC_WAYPAPER_MAXIMUM_BYTES'])
                self.assertLessEqual(minimum, 69176)  # Published 2.9 wheel size.
                self.assertGreaterEqual(maximum, 69176)
                self.assertEqual(policy['SAMLOADER_VERSION'], '2.2.0')
                self.assertIn('/2.2.0/samloader-v2.2.0-linux-x86_64.zip', policy['SAMLOADER_URL'])
                self.assertEqual(policy['SAMLOADER_SHA256'],
                                 'f6029dcce75b8a66acc1975529085c53903f7cdb35505e0ac0a973f2652480ff')

    def test_waypaper_pipx_consumes_verified_wheel_and_binary_dependencies(self):
        source = WAYPAPER.read_text(encoding='utf-8')
        self.assertLess(source.index('desktop_waypaper_download_wheel "$waypaper_wheel"'),
                        source.index('attempt_in_target "install pinned Waypaper with pipx"'))
        self.assertIn('PIP_ONLY_BINARY=:all:', source)
        self.assertIn('            "$waypaper_wheel"', source)

    def test_pgrep_profile_has_no_environment_reads_or_ptrace_permissions(self):
        source = (SEED / 'hooks/target/etc/apparmor.d/desktop-wrappers.tmpl').read_text(encoding='utf-8')
        child = source.split('  profile waypaper-pgrep ', 1)[1].split('\n  }', 1)[0]
        self.assertNotIn('ptrace', child)
        self.assertNotIn('environ', child)
        self.assertNotIn('capability', child)
        self.assertIn('/usr/bin/pgrep rCx -> waypaper-pgrep,', source)


if __name__ == '__main__':
    unittest.main()
