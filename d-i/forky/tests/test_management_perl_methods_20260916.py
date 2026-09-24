"""Execute the actual changed Perl method bodies with real core Perl/filesystems.

Only external policy tools, object construction/accessors and the kernel load
boundary are doubles. This does NOT emulate Moo or count as loading the full
Moo/MooX application. Full application tests remain a separate dependency gate.
"""
from payload_fixture import installed_argv as payload_installed_argv, source_is_file as payload_source_is_file
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
APPARMOR = TARGET / 'usr/local/lib/perl5/site_perl/labwc-security-action/LabwcSecurityAction/AppArmor.pm'


def method(name):
    match = re.search(r'^sub ' + re.escape(name) + r' \{.*?^\}', payload_read_text(APPARMOR), re.M | re.S)
    if not match:
        raise AssertionError('method not found: ' + name)
    return match.group()


@unittest.skipUnless(shutil.which('perl') and os.geteuid() == 0,
                     'requires real Perl and root-owned filesystem fixtures')
class PerlPolicyMethodTests(unittest.TestCase):
    def run_case(self, kind, statuses=(), **options):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'profiles').mkdir()
            (root / 'backup').mkdir(mode=0o700)
            (root / 'drafts').mkdir()
            for name in ('abi', 'abstractions', 'tunables', 'local'):
                (root / 'profiles' / name).mkdir()
            (root / 'mode').write_text('enforce required desktop-wrappers -\n')
            (root / 'enabled').write_text('Y\n')
            (root / 'helper').write_text('#!/bin/sh\nexit 0\n'); (root / 'helper').chmod(0o755)
            (root / 'profiles/vivaldi-stable').write_text('original audit policy\n')
            (root / 'profiles/vivaldi-bin').write_text('other original policy\n')
            (root / 'profiles/example').write_text('previous profile\n')
            (root / 'drafts/example').write_text('candidate profile\n')
            methods = ('_update_modes', '_validate_mode_config', '_read_small_file',
                       '_sync_mode_directory', '_ensure_root_directory', '_prepare_backup_dir',
                       '_prepare_draft_dir', '_validate_root_owned_file', '_application_profiles',
                       '_copy_atomic', '_draft_path', '_validate_draft_name', '_same_labels',
                       'activate_draft', '_update_application_audit', '_work_dir',
                       '_link_support_dirs', '_require_profile_tool_confirmation', 'run_autodep')
            code = r'''
use strict; use warnings;
use JSON::PP; use File::Basename qw(basename dirname);
use File::Copy qw(copy); use File::Path qw(make_path remove_tree);
use File::Temp qw(tempdir tempfile); use Fcntl qw(O_RDONLY O_DIRECTORY O_NOFOLLOW);
use IO::Handle;
our $o = decode_json($ARGV[0]); our $dir = $ARGV[1];
our $self = bless {
    mode_config => "$dir/mode", maximum_config_bytes => 65536,
    mode_helper => "$dir/helper", profile_dir => "$dir/profiles",
    profile_backup_dir => "$dir/backup", profile_draft_dir => "$dir/drafts",
    maximum_draft_bytes => 1048576, kernel_enabled_path => "$dir/enabled",
    command => bless({}, 'FakeCommand'), calls => 0, reloads => 0,
}, 'main';
for my $attribute (keys %{$self}) {
    my $key = $attribute;
    no strict 'refs';
    *{$key} = sub { $_[0]->{$key} };
}
sub _reconcile_modes {
    my ($s) = @_; ++$s->{calls};
    if ($o->{external_change} && $s->{calls} == 1) {
        open my $f, '>', $s->mode_config or die $!; print {$f} "external root change\n"; close $f;
    }
    return shift(@{$o->{statuses}}) // 0;
}
sub _policy_lock { return 1; } # construction/lock boundary tested separately
sub _validate_executable { return $_[1]; }
sub _program { return $_[1]; }
sub _resolve_installed_profile_name { return $_[2]; }
sub _profile_labels { return ['example']; }
sub _management_state { return 1; }
sub _parser_validate { return 0; } # real parser compilation has separate coverage
sub _activate_installed_profile { ++$self->{reloads}; return shift(@{$o->{reload_statuses}}) // 0; }
sub _publish_generated_drafts { $self->{last_workspace} = $_[1]; }
{ package FakeCommand;
  sub run {
    my ($s, @args) = @_;
    if ($args[0] eq 'aa-audit') {
      open my $f, '>', $args[-1] or die $!; print {$f} "changed flags\n"; close $f;
      return shift(@{$main::o->{statuses}}) // 0;
    }
    return 0;
  }
}
'''
            code += '\n' + '\n'.join(method(name) for name in methods) + r'''
my $result = eval {
    if ($o->{kind} eq 'mode') {
        $self->_update_modes(['desktop-wrappers'], $o->{mode} // 'complain', 'fixture');
    } elsif ($o->{kind} eq 'audit') {
        $self->_update_application_audit('vivaldi', $o->{mode} // 'enable');
    } elsif ($o->{kind} eq 'activate') {
        $self->activate_draft('drafts', 'example', 'confirmed-apparmor-draft-activation');
    } elsif ($o->{kind} eq 'autodep') {
        $self->run_autodep('/usr/bin/example', 'confirmed-apparmor-profile-tool');
    } else { die 'unknown fixture'; }
    1;
};
my $error = $@;
print "\nRESULT=" . encode_json({ok => $result ? 1 : 0, error => $error, calls => $self->{calls},
    reloads => $self->{reloads}, last_workspace => $self->{last_workspace}}) . "\n";
'''
            payload = dict(kind=kind, statuses=list(statuses), reload_statuses=[])
            payload.update(options)
            result = subprocess.run(payload_installed_argv(['perl', '-e', code, json.dumps(payload), str(root)]),
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            metadata = json.loads(result.stdout.rsplit('RESULT=', 1)[1])
            files = {str(p.relative_to(root)): payload_read_bytes(p) for p in root.rglob('*') if payload_source_is_file(p)}
            metadata['files'] = files
            metadata['directories'] = [p.name for p in (root / 'drafts').iterdir() if p.is_dir()]
            return metadata

    def test_mode_commit(self):
        result = self.run_case('mode')
        self.assertEqual(result['ok'], 1)
        self.assertEqual(result['files']['mode'], b'complain required desktop-wrappers -\n')
        self.assertEqual(result['calls'], 1)
        self.assertFalse(any(name.startswith('.modes') for name in result['files']))

    def test_failed_mode_reconcile_restores_and_reconciles(self):
        result = self.run_case('mode', [1, 0])
        self.assertEqual(result['ok'], 0)
        self.assertIn('restored and reconciled', result['error'])
        self.assertEqual(result['files']['mode'], b'enforce required desktop-wrappers -\n')
        self.assertEqual(result['calls'], 2)

    def test_failed_mode_rollback_retains_backup(self):
        result = self.run_case('mode', [1, 2])
        self.assertEqual(result['ok'], 0)
        self.assertIn('ALSO FAILED', result['error'])
        self.assertTrue(any(name.startswith('.modes.backup.') for name in result['files']))

    def test_external_mode_change_is_preserved(self):
        result = self.run_case('mode', [1], external_change=True)
        self.assertIn('changed concurrently', result['error'])
        self.assertEqual(result['files']['mode'], b'external root change\n')

    def test_live_disable_refused_before_any_mutation(self):
        result = self.run_case('mode', mode='disable')
        self.assertEqual(result['ok'], 0)
        self.assertIn('live profile unloading is not supported', result['error'])
        self.assertEqual(result['calls'], 0)
        self.assertEqual(result['files']['mode'], b'enforce required desktop-wrappers -\n')

    def test_autodep_success_still_cleans_workspace(self):
        result = self.run_case('autodep')
        self.assertEqual(result['ok'], 1, result['error'])
        self.assertIsNotNone(result['last_workspace'])
        self.assertEqual(result['directories'], [])

    def test_profile_activation_failed_rollback_retains_previous_source(self):
        result = self.run_case('activate', reload_statuses=[1, 2])
        self.assertEqual(result['ok'], 0)
        self.assertIn('Recovery ALSO FAILED', result['error'])
        self.assertEqual(result['files']['profiles/example'], b'previous profile\n')
        backups = [v for k, v in result['files'].items() if k.endswith('/previous-profile')]
        self.assertEqual(backups, [b'previous profile\n'])

    def test_profile_activation_success_keeps_previous_source(self):
        result = self.run_case('activate')
        self.assertEqual(result['ok'], 1, result['error'])
        self.assertEqual(result['files']['profiles/example'], b'candidate profile\n')
        self.assertEqual([v for k, v in result['files'].items() if k.endswith('/previous-profile')],
                         [b'previous profile\n'])

    def test_audit_failure_restores_exact_flags_not_guessed_inverse(self):
        result = self.run_case('audit', [0, 7])
        self.assertEqual(result['ok'], 0)
        self.assertEqual(result['files']['profiles/vivaldi-stable'], b'original audit policy\n')
        self.assertEqual(result['files']['profiles/vivaldi-bin'], b'other original policy\n')
        self.assertIn('Audit source backups retained', result['error'])
        self.assertEqual(result['reloads'], 2)

    def test_audit_rollback_failure_is_visible_and_backed_up(self):
        result = self.run_case('audit', [0, 7], reload_statuses=[9, 0])
        self.assertIn('Recovery ALSO FAILED', result['error'])
        self.assertTrue(any(k.startswith('backup/audit.') for k in result['files']))

    def test_audit_commit_cleans_only_transaction_backups(self):
        result = self.run_case('audit', [0, 0])
        self.assertEqual(result['ok'], 1, result['error'])
        self.assertEqual(result['reloads'], 2)
        self.assertEqual(result['files']['profiles/vivaldi-stable'], b'changed flags\n')
        self.assertFalse(any(k.startswith('backup/audit.') for k in result['files']))

if __name__ == '__main__':
    unittest.main()
