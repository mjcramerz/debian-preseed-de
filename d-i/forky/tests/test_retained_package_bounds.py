#!/usr/bin/env python3
"""Offline retained-package boundary regressions; never install a package.

The Perl harness evaluates the exact production method bodies with core Perl
imports and explicit fixture objects. It deliberately does not replace Moo or
claim constructor/module-load coverage. This keeps the archive and filesystem
checks executable even on a publishing host without the target's Moo packages.
Full module loading remains part of audit_codebase.py and the existing managed
external-software tests. The Python publisher and dpkg-deb are executed directly.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import resource
import runpy
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
PERL_LIB = FORKY / 'hooks/target/usr/local/lib/perl5/site_perl/external-managed-software'
SERVICING = PERL_LIB / 'ExternalSoftware/Servicing'
HELPER = FORKY / 'hooks/target/usr/local/libexec/local-apt-repository'
MAX_DEB = 1 << 32
MAX_PUBLISHER = 1 << 31
OLD_BOUND = 1 << 29
ENV = {**os.environ, 'LC_ALL': 'C.UTF-8', 'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'PERL5OPT': ''}


def method(filename: str, name: str) -> str:
    """Take a complete top-level method verbatim, without rewriting its body."""
    text = (SERVICING / filename).read_text()
    match = re.search(rf'^sub {re.escape(name)}\s*\{{.*?(?=^sub [A-Za-z_]|^1;\s*$)',
                      text, re.M | re.S)
    if match is None:
        raise AssertionError(f'production method missing: {filename}:{name}')
    return match.group(0)


def perl_program() -> str:
    # Only the catalogue transport and Moo constructors are fixture boundaries.
    # The validation, path policy, hashing, spec and selection methods are the
    # actual production source. No command, file-size or dpkg result is faked.
    common = '''use strict; use warnings;
use Fcntl qw(:DEFAULT O_NOFOLLOW O_NONBLOCK S_IFMT S_IFREG);
use Errno qw(EINTR); use Digest::SHA; use JSON::PP;
use ExternalSoftware::Servicing::ArtifactLimits qw(MAX_DEB_BYTES MAX_DOWNLOAD_BYTES);
'''
    constants = '\n'.join(re.findall(r'^use constant\s+.*?;',
                                     (SERVICING / 'ChatGPT.pm').read_text(), re.M | re.S))
    return ('package ExternalSoftware::Servicing::Atomic;\n' + common
            + method('Atomic.pm', 'assert_absolute_path')
            + method('Atomic.pm', 'read_limited') + method('Atomic.pm', 'sha256_file')
            + 'package ExternalSoftware::Servicing::ChatGPT;\n' + common + constants + '\n'
            + method('ChatGPT.pm', 'spec')
            + 'package ExternalSoftware::Servicing::Deb;\n' + common
            + method('Deb.pm', '_capture') + method('Deb.pm', 'control')
            + method('Deb.pm', 'validate') + method('Deb.pm', 'validate_spec')
            + 'package ExternalSoftware::Servicing::Repository;\n' + common
            + "use constant HELPER => '/fixture/catalogue-transport';\n"
            + 'sub directory { return $_[0]->{directory}; }\n'
            + 'sub _capture { return $_[0]->{catalogue}; }\n'
            + method('Repository.pm', 'latest')
            + method('Repository.pm', 'bitwarden_vendor_digest_matches')
            + '''package main;
use strict; use warnings; use JSON::PP;
my ($action, $path, $extra) = @ARGV;
my $deb = bless {}, 'ExternalSoftware::Servicing::Deb';
my $spec = ExternalSoftware::Servicing::ChatGPT->spec();
my $result;
if ($action eq 'limit') {
    $result = ExternalSoftware::Servicing::ArtifactLimits::MAX_DEB_BYTES();
} elsif ($action eq 'spec-limit') {
    $result = $spec->{maximum};
} elsif ($action eq 'path') {
    $result = ExternalSoftware::Servicing::Atomic->assert_absolute_path('fixture', $path);
} elsif ($action eq 'digest') {
    my ($size, $sha256) = ExternalSoftware::Servicing::Atomic->sha256_file($path, $extra);
    $result = { size => $size, sha256 => $sha256 };
} elsif ($action eq 'validate') {
    $result = $deb->validate_spec($path, $spec, "$spec->{label} retained archive");
} elsif ($action eq 'changed') {
    my $original = \\&ExternalSoftware::Servicing::Deb::control;
    no warnings 'redefine';
    local *ExternalSoftware::Servicing::Deb::control = sub {
        my $value = $original->(@_);
        if ($_[2] eq 'Architecture') {
            open my $out, '>>', $_[1] or die "fixture append: $!";
            print {$out} "changed"; close $out or die "fixture close: $!";
        }
        return $value;
    };
    $result = $deb->validate_spec($path, $spec);
} elsif ($action eq 'latest') {
    my $repository = bless { directory => $path, catalogue => $extra },
        'ExternalSoftware::Servicing::Repository';
    $result = $repository->latest($deb, $spec);
} elsif ($action eq 'latest-bitwarden') {
    my $repository = bless { directory => $path, catalogue => $extra },
        'ExternalSoftware::Servicing::Repository';
    $spec = { %$spec, name => 'bitwarden', packages => ['bitwarden'], label => 'Bitwarden' };
    $result = $repository->latest($deb, $spec);
} else {
    die "unknown fixture action\\n";
}
print 'RESULT:' . JSON::PP->new->canonical->encode($result) . "\\n";
''')


def ar_header(name: str, size: int) -> bytes:
    return (f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{size:<10}`\n').encode('ascii')


def sparse_deb(path: Path, size: int = 8192, *, package: str = 'chatgpt',
               version: str = '1.0+localrepo1', architecture: str = 'amd64') -> None:
    """Create a real ar/control/data Debian archive with a sparse zero payload."""
    control = (f'Package: {package}\nVersion: {version}\nArchitecture: {architecture}\n'
               'Maintainer: Fixture <fixture@localhost>\nDescription: Offline boundary fixture\n').encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        member = tarfile.TarInfo('./control')
        member.mode, member.size = 0o644, len(control)
        archive.addfile(member, io.BytesIO(control))
    control_archive = gzip.compress(stream.getvalue(), mtime=0)
    with path.open('wb') as output:
        output.write(b'!<arch>\n')
        for name, data in (('debian-binary', b'2.0\n'), ('control.tar.gz', control_archive)):
            output.write(ar_header(name, len(data)))
            output.write(data)
            if len(data) % 2:
                output.write(b'\n')
        data_size = size - output.tell() - 60
        if data_size < 2048 or data_size % 2:
            raise ValueError('fixture size must leave an even, complete data archive')
        output.write(ar_header('data.tar', data_size))
        member = tarfile.TarInfo('./usr/share/fixture/padding')
        member.mode = 0o644
        member.size = ((data_size - 1536) // 512) * 512
        output.write(member.tobuf(format=tarfile.USTAR_FORMAT))
        output.seek(member.size, os.SEEK_CUR)
        output.write(b'\0' * (data_size - 512 - member.size))
    path.chmod(0o600)
    if path.stat().st_size != size:
        raise AssertionError('fixture size mismatch')


def run_perl(action: str, path: object = '', extra: object = '', *, memory_limit: bool = False):
    def limit_memory():
        resource.setrlimit(resource.RLIMIT_AS, (128 << 20, 128 << 20))
    return subprocess.run(['/usr/bin/perl', '-I', str(PERL_LIB), '-e', perl_program(),
                           action, str(path), str(extra)], text=True, capture_output=True,
                          env=ENV, timeout=45,
                          preexec_fn=limit_memory if memory_limit else None)


def result_value(result):
    if result.returncode:
        raise AssertionError(result.stderr)
    records = [line.removeprefix('RESULT:') for line in result.stdout.splitlines()
               if line.startswith('RESULT:')]
    if len(records) != 1:
        raise AssertionError(result.stdout)
    return json.loads(records[0])


class RetainedPackageBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='retained-package-bounds-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.small = cls.directory / 'chatgpt-small.deb'
        cls.large = cls.directory / 'chatgpt-large.deb'
        cls.at_limit = cls.directory / 'chatgpt-at-limit.deb'
        sparse_deb(cls.small)
        sparse_deb(cls.large, OLD_BOUND + 4096)
        sparse_deb(cls.at_limit, MAX_DEB)
        cls.publisher = runpy.run_path(str(HELPER), run_name='retained_package_publisher_test')

    def assert_rejected(self, path, reason: str, *, action='validate', extra=''):
        result = run_perl(action, path, extra)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(reason, result.stderr)
        return result

    def test_publisher_and_retained_archive_have_explicit_separate_ceilings(self):
        self.assertEqual(result_value(run_perl('limit')), MAX_DEB)
        self.assertEqual(self.publisher['MAX_DEB'], MAX_PUBLISHER)
        self.assertEqual(MAX_DEB, 2 * MAX_PUBLISHER)

    def test_chatgpt_transport_matches_the_publisher_not_the_archive_ceiling(self):
        self.assertEqual(result_value(run_perl('spec-limit')), MAX_PUBLISHER)

    def test_limit_module_is_in_the_installer_staging_inventory(self):
        script = (FORKY / 'scripts/late/software.sh').read_text()
        inventory = re.search(r"software_perl_modules\(\) \{\s*cat <<'EOF'\n(.*?)\nEOF", script, re.S)
        self.assertIsNotNone(inventory)
        entries = inventory[1].splitlines()
        self.assertEqual(entries.count('ExternalSoftware/Servicing/ArtifactLimits.pm'), 1)
        for entry in entries:
            self.assertTrue((PERL_LIB / entry).is_file(), entry)

    def test_small_valid_debian_archive_still_passes(self):
        self.assertEqual(result_value(run_perl('validate', self.small)),
                         {'package': 'chatgpt', 'version': '1.0+localrepo1', 'architecture': 'amd64'})

    def test_real_archive_above_old_512_mib_limit_passes_both_readers(self):
        fields = self.publisher['inspect_deb'](self.large, {'amd64'})
        self.assertEqual(fields['Package'], 'chatgpt')
        self.assertEqual(result_value(run_perl('validate', self.large))['version'], fields['Version'])
        self.assertGreater(self.large.stat().st_size, OLD_BOUND)

    def test_real_archive_exactly_at_four_gib_is_accepted(self):
        self.assertEqual(result_value(run_perl('validate', self.at_limit))['package'], 'chatgpt')
        self.assertEqual(self.at_limit.stat().st_size, MAX_DEB)

    def test_one_byte_over_limit_reports_actual_size_path_and_ceiling(self):
        path = self.directory / 'oversized.deb'
        with path.open('wb') as output:
            output.write(b'!<arch>\n')
            output.truncate(MAX_DEB + 1)
        result = self.assert_rejected(path, 'not a bounded regular file')
        for text in (str(path), f'size={MAX_DEB + 1}', f'permitted=8..{MAX_DEB}'):
            self.assertIn(text, result.stderr)
        with self.assertRaises(self.publisher['Error']):
            fd = self.publisher['checked_file'](path)
            os.close(fd)

    def test_publisher_accepts_exactly_two_gib_and_rejects_one_byte_more(self):
        path = self.directory / 'publisher-boundary.deb'
        sparse_deb(path, MAX_PUBLISHER)
        os.chmod(path, 0o600)
        fd = self.publisher['checked_file'](path)
        os.close(fd)
        with path.open('ab') as stream:
            stream.write(b'x')
        with self.assertRaises(self.publisher['Error']):
            self.publisher['checked_file'](path)
        # The larger retained policy deliberately still accepts this size.
        path.unlink()

    def test_retained_archive_above_publisher_budget_is_still_valid(self):
        path = self.directory / 'retained-expanded.deb'
        sparse_deb(path, MAX_PUBLISHER + 4096)
        self.assertEqual(result_value(run_perl('validate', path))['package'], 'chatgpt')
        with self.assertRaises(self.publisher['Error']):
            self.publisher['checked_file'](path, private=False)
        path.unlink()

    def test_empty_and_short_archives_are_rejected(self):
        for size in range(8):
            with self.subTest(size=size):
                path = self.directory / f'truncated-{size}.deb'
                path.write_bytes(b'!<arch>\n'[:size])
                self.assert_rejected(path, f'size={size}')

    def test_missing_file_is_distinguished_from_excess_size(self):
        self.assert_rejected(self.directory / 'missing.deb', 'cannot be inspected')

    def test_regular_and_dangling_symlinks_are_rejected(self):
        for name, target in (('linked.deb', self.small), ('dangling.deb', self.directory / 'absent')):
            with self.subTest(name=name):
                path = self.directory / name
                path.symlink_to(target)
                self.assert_rejected(path, 'symlinks and special files are forbidden')

    def test_directory_and_fifo_are_rejected_without_blocking(self):
        path = self.directory / 'fifo.deb'
        os.mkfifo(path, 0o600)
        for candidate in (self.directory, path):
            self.assert_rejected(candidate, 'symlinks and special files are forbidden')

    def test_open_is_nonblocking_nofollow_and_descriptor_checked(self):
        source = method('Deb.pm', 'validate')
        self.assertIn('O_RDONLY | O_NOFOLLOW | O_NONBLOCK', source)
        self.assertIn('my @opened_stat = stat $package_fh', source)
        self.assertIn('package changed while opening', source)

    def test_non_debian_header_is_rejected(self):
        path = self.directory / 'html.deb'
        path.write_bytes(b'<html>not a Debian archive</html>')
        self.assert_rejected(path, 'does not have Debian archive framing')

    def test_framing_alone_does_not_bypass_dpkg_validation(self):
        path = self.directory / 'magic-only.deb'
        path.write_bytes(b'!<arch>\n')
        self.assert_rejected(path, 'is not a valid Debian package')

    def test_wrong_identity_and_architecture_are_still_rejected(self):
        for name, architecture, reason in (
                ('unapproved', 'amd64', 'package name is unapproved'),
                ('chatgpt', 'arm64', 'package architecture is not amd64')):
            with self.subTest(name=name, architecture=architecture):
                path = self.directory / f'{name}-{architecture}.deb'
                sparse_deb(path, package=name, architecture=architecture)
                self.assert_rejected(path, reason)

    def test_modification_during_metadata_validation_is_rejected(self):
        path = self.directory / 'changing.deb'
        shutil.copyfile(self.small, path)
        self.assert_rejected(path, 'package changed during validation', action='changed')

    def test_valid_tilde_version_filename_is_accepted(self):
        path = self.directory / 'chatgpt_1.0~rc1+localrepo1_amd64.deb'
        sparse_deb(path, version='1.0~rc1+localrepo1')
        self.assertEqual(result_value(run_perl('validate', path))['version'], '1.0~rc1+localrepo1')

    def test_unsafe_path_characters_and_traversal_remain_rejected(self):
        for path in ('relative.deb', '/tmp/../file.deb', '/tmp/./file.deb',
                     '/tmp/file;touch.deb', '/tmp/file\n.deb', '/tmp/file with space.deb'):
            with self.subTest(path=path):
                result = run_perl('path', path)
                self.assertNotEqual(result.returncode, 0)

    def test_streaming_digest_accepts_large_retained_file_under_memory_cap(self):
        with self.large.open('rb') as source:
            expected = hashlib.file_digest(source, 'sha256').hexdigest()
        self.assertEqual(result_value(run_perl('digest', self.large, MAX_DEB, memory_limit=True)),
                         {'size': self.large.stat().st_size, 'sha256': expected})

    def test_digest_keeps_explicit_smaller_transport_limits(self):
        self.assert_rejected(self.large, 'not a bounded regular file', action='digest', extra=OLD_BOUND)

    def test_digest_rejects_unbounded_or_invalid_limits(self):
        for limit in (0, -1, MAX_DEB + 1, 'unlimited', '1.5', '1e9', '01'):
            with self.subTest(limit=limit):
                self.assert_rejected(self.small, 'invalid digest input limit', action='digest', extra=limit)

    def test_digest_does_not_follow_symlinks(self):
        path = self.directory / 'digest-link.deb'
        path.symlink_to(self.small)
        self.assert_rejected(path, 'not a bounded regular file', action='digest', extra=MAX_DEB)

    def test_latest_reads_a_large_retained_catalogue_candidate(self):
        root = self.directory / 'catalogue'
        pool = root / 'pool/chatgpt' / ('a' * 64)
        pool.mkdir(parents=True)
        path = pool / 'chatgpt_1.0+localrepo1_amd64.deb'
        sparse_deb(path, OLD_BOUND + 4096)
        # Only the list transport is fixture-provided; selection and validation
        # use the production methods and actual on-disk Debian archive.
        catalogue = json.dumps({'packages': {'chatgpt:amd64': {
            'package': 'chatgpt', 'filename': str(path.relative_to(root))}}})
        record = result_value(run_perl('latest', root, catalogue))
        self.assertEqual(record['path'], str(path))
        self.assertEqual(record['metadata']['package'], 'chatgpt')

    def test_bitwarden_retained_digest_also_uses_repository_ceiling(self):
        root = self.directory / 'bitwarden-catalogue'
        pool = root / 'pool/bitwarden' / ('b' * 64)
        pool.mkdir(parents=True)
        path = pool / 'bitwarden_1.0+localrepo1_amd64.deb'
        sparse_deb(path, OLD_BOUND + 4096, package='bitwarden')
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        receipt = Path(str(path) + '.vendor-sha256')
        receipt.write_text(digest + '\n')
        receipt.chmod(0o644)
        catalogue = json.dumps({'packages': {'bitwarden:amd64': {
            'package': 'bitwarden', 'filename': str(path.relative_to(root))}}})
        record = result_value(run_perl('latest-bitwarden', root, catalogue))
        self.assertEqual(record['vendor_sha256'], digest)
        receipt.write_text('0' * 64 + '\n')
        self.assertIsNone(result_value(run_perl('latest-bitwarden', root, catalogue)))


if __name__ == '__main__':
    unittest.main()
