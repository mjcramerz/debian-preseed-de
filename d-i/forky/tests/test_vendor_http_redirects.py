"""Per-hop download policy with explicit capture fixtures; no network access."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

LIB = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/lib/perl5/site_perl'
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C'}
DRIVER = r'''
use strict; use warnings;
use APTRepoLocal::Servicing::HTTP;
use Managed::Process;
use JSON::PP;
my ($destination, $redirect) = @ARGV;
my @calls;
{
    no warnings 'redefine';
    *Managed::Process::capture_command = sub {
        my %request = @_;
        my @argv = @{$request{argv}};
        push @calls, \@argv;
        die "unexpected automatic redirect\n" if grep { $_ eq '--location' } @argv;
        die "missing curl configuration isolation\n" if $argv[1] ne '--disable';
        die "deadline exceeded\n" if $request{timeout} > 1200;
        my ($url, $partial);
        for my $index (0 .. $#argv - 1) {
            $url = $argv[$index + 1] if $argv[$index] eq '--url';
            $partial = $argv[$index + 1] if $argv[$index] eq '--output';
        }
        open my $fh, '>', $partial or die 'fixture output';
        print {$fh} 'fixture-artifact'; close $fh;
        return {status => 0, stdout => "302\n$url\ntext/html\n$redirect"}
            if @calls == 1 || $redirect eq 'https://api.example/loop';
        return {status => 0, stdout => "200\n$url\napplication/octet-stream\n"};
    };
}
my $ok = eval {
    APTRepoLocal::Servicing::HTTP->new->download(
        label => 'fixture', url => 'https://api.example/start', destination => $destination,
        minimum => 1, maximum => 1024, allowed_hosts => ['api.example', 'cdn.example'],
        content_policy => 'artifact');
    1;
};
print encode_json({ok => $ok ? 1 : 0, error => $@, calls => \@calls});
'''


class VendorHTTPTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which('perl'):
            self.skipTest('Perl unavailable')
        probe = subprocess.run(['perl', '-MMoo', '-MMooX::StrictConstructor', '-e', '1'],
                               env=ENV, capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('packaged Moo dependencies unavailable')
        temporary = tempfile.TemporaryDirectory(prefix='vendor-http-')
        self.addCleanup(temporary.cleanup)
        self.destination = Path(temporary.name) / 'artifact'

    def request(self, redirect):
        result = subprocess.run(['perl', '-I' + str(LIB / 'apt-repo-local'), '-I' + str(LIB / 'runtime'),
                                 '-e', DRIVER, '--', str(self.destination), redirect],
                                env=ENV, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_approved_redirect_contacts_only_validated_hosts_then_publishes(self):
        result = self.request('https://cdn.example/artifact')
        self.assertEqual(result['ok'], 1, result['error'])
        self.assertEqual([argv[-1] for argv in result['calls']],
                         ['https://api.example/start', 'https://cdn.example/artifact'])
        self.assertEqual(self.destination.read_bytes(), b'fixture-artifact')
        self.assertFalse(Path(str(self.destination) + '.part').exists())

    def test_disallowed_intermediate_hop_never_gets_contacted(self):
        for redirect in ('https://unapproved.example/hop', 'http://api.example/downgrade',
                         'https://user:password@cdn.example/artifact', 'https://cdn.example/bad\npath'):
            with self.subTest(redirect=redirect):
                result = self.request(redirect)
                self.assertEqual(result['ok'], 0)
                self.assertEqual(len(result['calls']), 1)
                self.assertFalse(self.destination.exists())
                self.assertFalse(Path(str(self.destination) + '.part').exists())
                self.assertNotIn('password', result['error'])

    def test_redirect_loop_has_a_bounded_request_count_and_no_publication(self):
        result = self.request('https://api.example/loop')
        self.assertEqual(result['ok'], 0)
        self.assertEqual(len(result['calls']), 9)
        self.assertFalse(self.destination.exists())
        self.assertFalse(Path(str(self.destination) + '.part').exists())
