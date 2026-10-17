"""Packaged qpdf/fix-qdf fixtures using real encrypted and edited PDF bytes."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

LIB = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/lib/perl5/site_perl/digital-assets'
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C'}
DRIVER = r'''
use strict; use warnings;
use DigitalAssets::PDF;
{
    package FixtureContext;
    use File::Temp qw(tempfile);
    sub work_directory { $_[0]->{root} }
    sub home { $_[0]->{root} }
    sub command_path { '/usr/bin/' . $_[1] }
    sub prompt_secret { shift @{$_[0]->{secrets}} }
    sub prompt_line { shift @{$_[0]->{lines}} }
    sub validate_password { $_[2] }
    sub validate_ascii_text { 1 }
    sub pdf_page_count { 1 }
    sub prepare_output_file { $_[0]->{root} . '/output.pdf' }
    sub create_private_file {
        my ($self, $name, $data) = @_;
        my ($fh, $path) = tempfile('.' . $name . '.XXXXXX', DIR => $self->{root});
        print {$fh} $data or die 'fixture write';
        close $fh or die 'fixture close';
        chmod 0600, $path or die 'fixture chmod';
        return $path;
    }
    sub run_timed {
        my ($self, @argv) = @_;
        open my $log, '>>', $self->{root} . '/argv' or die 'fixture argv log';
        print {$log} join("\t", @argv), "\n";
        close $log;
        system { $argv[0] } @argv;
        $? == 0 or die "fixture command failed raw_status=$?\n";
    }
    sub report_file_output { print "fixture output verified\n" }
}
my ($mode, $root, $input) = @ARGV;
my $context = bless {
    root => $root,
    secrets => ['fixture-user-password', 'fixture-user-password', 'fixture-owner-password', 'fixture-owner-password'],
    lines => ['uri', 'https://example.test/a', 'https://example.test/a-much-longer-uri'],
}, 'FixtureContext';
my $pdf = DigitalAssets::PDF->new(context => $context, metadata => bless({}, 'FixtureUnused'));
if ($mode eq 'encrypt') { $pdf->encrypt($input); }
else { $pdf->edit_qdf($input, 'uri'); }
'''


def pdf_bytes():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Annots [4 0 R] >>',
               b'<< /Type /Annot /Subtype /Link /Rect [0 0 20 20] /A << /S /URI /URI (https://example.test/a) >> >>']
    output = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(str(number).encode() + b' 0 obj\n' + body + b'\nendobj\n')
    start = len(output)
    output.extend(b'xref\n0 5\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(output)


class PDFOutputTests(unittest.TestCase):
    def setUp(self):
        if not all(shutil.which(tool) for tool in ('perl', 'qpdf', 'fix-qdf')):
            self.skipTest('packaged Perl/qpdf/fix-qdf unavailable')
        probe = subprocess.run(['perl', '-MMoo', '-MMooX::StrictConstructor', '-MMooX::TypeTiny', '-e', '1'],
                               env=ENV, capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('packaged Moo dependencies unavailable')
        temporary = tempfile.TemporaryDirectory(prefix='pdf-output-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input = self.root / 'input.pdf'
        self.input.write_bytes(pdf_bytes())

    def run_pdf(self, mode):
        return subprocess.run(['perl', '-I' + str(LIB), '-e', DRIVER, '--', mode, str(self.root), str(self.input)],
                              env=ENV, capture_output=True, text=True, timeout=20)

    def test_nonempty_password_encryption_checks_privately(self):
        result = self.run_pdf('encrypt')
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = (self.root / 'argv').read_text()
        self.assertNotIn('fixture-user-password', argv + result.stdout + result.stderr)
        self.assertNotIn('fixture-owner-password', argv + result.stdout + result.stderr)
        self.assertIn('--password-file=', argv)
        output = self.root / 'output.pdf'
        without = subprocess.run(['qpdf', '--check', str(output)], env=ENV, capture_output=True, timeout=5)
        self.assertNotEqual(without.returncode, 0)
        password = next(self.root.glob('.pdf-encrypt-password.*'))
        self.assertEqual(password.stat().st_mode & 0o777, 0o600)
        checked = subprocess.run(['qpdf', '--password-file=' + str(password), '--check', str(output)],
                                 env=ENV, capture_output=True, timeout=5)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_length_changing_qdf_edit_consumes_repaired_output_without_stdout_body(self):
        result = self.run_pdf('qdf')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('%PDF-', result.stdout)
        self.assertNotIn('https://example.test/a', result.stdout)
        argv = (self.root / 'argv').read_text().splitlines()
        repair = next(line.split('\t') for line in argv if '/fix-qdf\t' in line)
        self.assertEqual(len(repair), 3)
        self.assertNotEqual(repair[1], repair[2])
        self.assertTrue(any(line.startswith('/usr/bin/qpdf\t' + repair[2] + '\t') for line in argv))
        checked = subprocess.run(['qpdf', '--check', str(self.root / 'output.pdf')], env=ENV, capture_output=True, timeout=5)
        self.assertEqual(checked.returncode, 0, checked.stderr)
