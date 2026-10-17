"""AppArmor generator recovery with explicit parser/reload failure fixtures."""
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
from payload_fixture import installed_script

LIB = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/lib/perl5/site_perl'
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C'}
DRIVER = r'''
use strict; use warnings;
require $ARGV[0];
{
    package FixtureAudit;
    sub read_denials { return ([{fields => {profile => 'fixture'}, count => 1, line_number => 1}], []); }
    package FixtureIndex;
    sub build { {} }
    sub resolve { return $_[0]->{target}; }
    package FixtureRenderer;
    sub render { return {ok => 1, rule => '/fixture/data r,', kind => 'file'}; }
    package FixtureCommand;
    sub require_executable { '/fixture/parser' }
    sub run {
        my ($self, @argv) = @_;
        if (grep { $_ eq '-Q' } @argv) { return $self->{mode} eq 'parse' ? 19 : 0; }
        ++$self->{reloads};
        return 23 if $self->{mode} eq 'rollback' || $self->{reloads} == 1;
        return 0;
    }
}
my ($module, $root, $mode) = @ARGV;
my $target = {local_name => 'fixture', local_path => "$root/profiles/local/fixture",
              source_name => 'fixture', source_path => "$root/profiles/fixture"};
my $generator = LabwcSecurityAction::AppArmor::RuleGenerator->new(
    trusted_uid => $>, profile_dir => "$root/profiles", backup_dir => "$root/backups",
    audit_log => bless({}, 'FixtureAudit'), profile_index => bless({target => $target}, 'FixtureIndex'),
    renderer => bless({}, 'FixtureRenderer'), command => bless({mode => $mode}, 'FixtureCommand'),
);
exit $generator->run('confirmed-apparmor-rule-generation');
'''


class RuleRecoveryTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which('perl'):
            self.skipTest('Perl unavailable')
        probe = subprocess.run(['perl', '-MMoo', '-MMooX::StrictConstructor', '-MMooX::TypeTiny',
                                '-MTypes::Standard', '-e', '1'], env=ENV, capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('packaged Moo dependencies unavailable')
        temporary = tempfile.TemporaryDirectory(prefix='apparmor-recovery-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'profiles/local').mkdir(parents=True)
        (self.root / 'backups').mkdir(mode=0o700)
        self.local = self.root / 'profiles/local/fixture'
        self.local.write_bytes(b'# previous include\n/old/path r,\n')
        self.local.chmod(0o644)
        (self.root / 'profiles/fixture').write_text('profile fixture {\ninclude <local/fixture>\n}\n')
        self.before = self.local.read_bytes()

    def test_parse_reload_and_failed_rollback_keep_previous_bytes_or_recovery(self):
        module = installed_script(LIB / 'labwc-security-action/LabwcSecurityAction/AppArmor/RuleGenerator.pm')
        for mode in ('parse', 'reload', 'rollback'):
            with self.subTest(mode=mode):
                result = subprocess.run(['perl', '-I' + str(LIB / 'runtime'), '-I' + str(LIB / 'labwc-security-action'),
                                         '-e', DRIVER, '--', str(module), str(self.root), mode],
                                        env=ENV, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.local.read_bytes(), self.before)
                bundles = list((self.root / 'backups').glob('generate.*'))
                if mode == 'rollback':
                    self.assertEqual(result.returncode, 3)
                    self.assertEqual(len(bundles), 1)
                    self.assertIn(str(bundles[0]), result.stderr)
                    self.assertEqual((bundles[0] / 'previous/fixture').read_bytes(), self.before)
                    self.assertIn(str(self.local), (bundles[0] / 'restore-paths').read_text())
                else:
                    self.assertEqual(bundles, [])

    def test_entrypoint_preserves_failure_cancel_and_unknown_status(self):
        wrapper = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/libexec/apparmor-generate-rules'
        code = r'''
BEGIN {
    $INC{'LabwcSecurityAction/AppArmor/RuleGenerator.pm'} = 1;
    package LabwcSecurityAction::AppArmor::RuleGenerator;
    sub new { bless {}, shift }
    sub run {
        $SIG{INT}->('INT') if $ENV{FIXTURE_RESULT} eq 'cancel';
        die "fixture rejected candidate\n" if $ENV{FIXTURE_RESULT} eq 'failure';
        return $ENV{FIXTURE_RESULT} eq 'unknown' ? 3 : 0;
    }
}
my $wrapper = shift @ARGV;
do $wrapper; die $@ if $@;
'''
        for outcome, status in (('success', 0), ('failure', 1), ('cancel', 130), ('unknown', 3)):
            with self.subTest(outcome=outcome):
                result = subprocess.run(['perl', '-e', code, '--', str(wrapper), '--apply',
                                         'confirmed-apparmor-rule-generation'],
                                        env=dict(ENV, PKEXEC_UID='1000', FIXTURE_RESULT=outcome),
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, status, result.stderr)
