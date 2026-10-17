"""Real model staging/validation with fixture downloads; disposable VM only."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

LIB = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/lib/perl5/site_perl'
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': '/nonexistent'}
DRIVER = r'''
use strict; use warnings;
use AICopilots::ModelInstallRoot;
{ no warnings 'redefine'; *AICopilots::ModelInstallRoot::_devops_gid = sub { 0 }; }
my ($action, $directory, $curl, $family, @args) = @ARGV;
if ($ENV{FIXTURE_POST_PUBLISH_FAIL}) {
    no warnings 'redefine';
    my $validate = \&AICopilots::ModelInstallRoot::_validate_model;
    *AICopilots::ModelInstallRoot::_validate_model = sub {
        my $value = $validate->(@_);
        die "fixture post-publication verification interruption\n" if !defined($_[6]);
        return $value;
    };
}
my $model = AICopilots::ModelInstallRoot->new(
    llama_model_directory => $directory, whisper_model_directory => $directory,
    curl => $curl,
);
exit($action eq 'prune' ? $model->_prune($family) : $model->_download($family, @args));
'''
CURL = '''#!/usr/bin/python3 -IB
import os, pathlib, shutil, sys
target = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
with open(os.environ['FIXTURE_CALLS'], 'a') as stream:
    stream.write(target.name + '\\n')
if os.environ.get('FIXTURE_REPLACE'):
    replacement = target.with_suffix('.replacement')
    shutil.copyfile(os.environ['FIXTURE_MODEL'], replacement)
    os.replace(replacement, target)
else:
    shutil.copyfile(os.environ['FIXTURE_MODEL'], target)
'''


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('perl'), 'root-owned native Perl fixture')
class ModelInstallTests(unittest.TestCase):
    def setUp(self):
        probe = subprocess.run(['perl', '-MMoo', '-MMooX::StrictConstructor', '-MMooX::TypeTiny',
                                '-MTypes::Standard', '-e', '1'], env=ENV, capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('packaged Perl dependencies unavailable')
        temporary = tempfile.TemporaryDirectory(prefix='model-install-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.models = self.root / 'models'
        self.models.mkdir(mode=0o2750)
        self.models.chmod(0o2750)
        self.curl = self.root / 'curl'
        self.curl.write_text(CURL)
        self.curl.chmod(0o755)
        self.input = self.root / 'input'
        self.calls = self.root / 'calls'
        self.env = dict(ENV, FIXTURE_MODEL=str(self.input), FIXTURE_CALLS=str(self.calls))

    def prepare(self, family, magic=None):
        magic = magic if magic is not None else (b'GGUF' if family == 'llama' else b'lmgg')
        self.input.write_bytes(magic + b'x' * (1048576 - len(magic)))
        marker = self.models / ('.installer-llama-managed' if family == 'llama' else '.installer-whisper-managed')
        marker.write_text(f'managed={family}-models\n')
        marker.chmod(0o600)
        return 'fixture.gguf' if family == 'llama' else 'ggml-fixture.bin'

    def run_model(self, action, family, *args):
        return subprocess.run(['perl', '-I' + str(LIB / 'runtime'), '-I' + str(LIB / 'ai-copilots'),
                               '-e', DRIVER, '--', action, str(self.models), str(self.curl), family, *args],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def download(self, family, filename, digest=None, size='1048576'):
        return self.run_model('download', family, 'https://huggingface.co/fixture/model/resolve/main/model',
                              filename, digest or hashlib.sha256(self.input.read_bytes()).hexdigest(), size)

    def test_real_partial_validates_and_publishes_once_for_both_families(self):
        for family in ('llama', 'whisper'):
            with self.subTest(family=family):
                filename = self.prepare(family)
                for _ in range(2):
                    result = self.download(family, filename)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), str(self.models / filename))
                self.assertEqual((self.models / filename).read_bytes(), self.input.read_bytes())
                self.assertEqual((self.models / filename).stat().st_mode & 0o7777, 0o640)
        self.assertEqual(len(self.calls.read_text().splitlines()), 2)
        self.assertFalse(list(self.models.glob('*.partial.*')))

    def test_bad_content_size_digest_and_replaced_inode_never_publish(self):
        for attack in ('magic', 'size', 'digest', 'inode'):
            with self.subTest(attack=attack):
                filename = self.prepare('llama', b'NOPE' if attack == 'magic' else None)
                self.env.pop('FIXTURE_REPLACE', None)
                if attack == 'inode':
                    self.env['FIXTURE_REPLACE'] = '1'
                result = self.download('llama', filename, '0' * 64 if attack == 'digest' else None,
                                       '1048577' if attack == 'size' else '1048576')
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.models / filename).exists())
                self.assertFalse(list(self.models.glob('*.partial.*')))

    def test_prune_uses_writer_lock_restats_and_preserves_recent_partials(self):
        filename = self.prepare('llama')
        active = self.models / f'.{filename}.partial.A_B123'
        stale = self.models / '.stale.gguf.partial.A_B123'
        recent = self.models / '.recent.gguf.partial.A_B123'
        for path in (active, stale, recent):
            path.write_bytes(b'partial')
            path.chmod(0o600)
        for path in (active, stale):
            os.utime(path, (time.time() - 90000,) * 2)
        lock = self.models / f'.{filename}.lock'
        with lock.open('w') as held:
            lock.chmod(0o600)
            fcntl.flock(held, fcntl.LOCK_EX)
            result = self.run_model('prune', 'llama')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '1')
            self.assertTrue(active.exists())
            self.assertFalse(stale.exists())
            self.assertTrue(recent.exists())
        result = self.run_model('prune', 'llama')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(active.exists())
        self.assertTrue(recent.exists())

    def test_failure_after_publication_is_unknown_and_keeps_verified_final_bytes(self):
        filename = self.prepare('llama')
        self.env['FIXTURE_POST_PUBLISH_FAIL'] = '1'
        result = self.download('llama', filename)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('outcome unknown', result.stderr)
        self.assertEqual((self.models / filename).read_bytes(), self.input.read_bytes())
        self.assertFalse(list(self.models.glob('*.partial.*')))
