"""Offline single-application policy fixtures; never touch host policy/services."""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from test_boot_runtime_20260913 import MOO_ADAPTER

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
APPARMOR = TARGET / 'usr/local/lib/perl5/site_perl/labwc-security-action/LabwcSecurityAction/AppArmor.pm.tmpl'
MENU = TARGET / 'usr/local/bin/labwc-maintenance-menu.tmpl'

PERL_FIXTURE = r'''
use strict; use warnings;
use lib $ENV{AA_ADAPTER};
BEGIN {
    $INC{'LabwcSecurityAction/Command.pm'} = 1;
    $INC{'LabwcSecurityAction/Logger.pm'} = 1;
}
my $loaded = do $ENV{AA_SOURCE}; die $@ || $! unless $loaded;
{
    package FakeCommand;
    sub require_executable { return $_[1]; }
    sub capture {
        my ($self, %args) = @_;
        die 'unexpected capture' unless grep { $_ eq '-N' } @{$args{argv}};
        return (0, ($ENV{AA_LABELS} // "spotify\nspotify//helper\n"), '');
    }
    sub run {
        my ($self, @args) = @_;
        open my $log, '>>', $ENV{AA_CALLS} or die $!;
        print {$log} join(' ', @args), "\n"; close $log or die $!;
        return 9 if $ENV{AA_FAIL_COMMAND};
        if ($args[0] eq 'apparmor_parser' && !$ENV{AA_NO_CHANGE}) {
            my @labels = grep { length } split /\n/, ($ENV{AA_LABELS} // "spotify\nspotify//helper\n");
            open my $current, '<', $ENV{AA_PROFILES} or die $!;
            my @unrelated = grep {
                my ($name) = /\A(.+) \([a-z]+\)/;
                !grep { $name eq $_ || index($name, "$_//") == 0 } @labels;
            } <$current>;
            close $current or die $!;
            open my $state, '>', $ENV{AA_PROFILES} or die $!;
            print {$state} @unrelated;
            print {$state} map { "$_ (enforce)\n" } @labels if grep { $_ eq '--replace' } @args;
            close $state or die $!;
        }
        return 0;
    }
}
my $manager = LabwcSecurityAction::AppArmor->new(
    command => bless({}, 'FakeCommand'), logger => bless({}, 'FakeLogger'),
    kernel_enabled_path => $ENV{AA_KERNEL}, loaded_profiles_path => $ENV{AA_PROFILES},
    profile_dir => $ENV{AA_DIRECTORY}, profile_backup_dir => $ENV{AA_BACKUP},
);
my $method = shift @ARGV;
$manager->$method(@ARGV);
'''


@unittest.skipUnless(shutil.which('perl') and os.geteuid() == 0, 'Perl and root-owned fixtures required')
class LiveProfileActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); adapter = root / 'adapter'; adapter.mkdir()
        dependencies = subprocess.run([shutil.which('perl'), '-MMoo', '-MMooX::StrictConstructor',
                                       '-MMooX::TypeTiny', '-MTypes::Standard', '-e', '1'],
                                      capture_output=True, timeout=10)
        if dependencies.returncode:
            (adapter / 'Moo.pm').write_text(MOO_ADAPTER)
            for name in ('MooX/StrictConstructor.pm', 'MooX/TypeTiny.pm'):
                path = adapter / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('package ' + name.removesuffix('.pm').replace('/', '::') + '; sub import {} 1;\n')
            standard = adapter / 'Types/Standard.pm'; standard.parent.mkdir()
            standard.write_text("package Types::Standard; use Exporter 'import'; our @EXPORT_OK=qw(Str Int Object); "
                                "sub Str {'Str'} sub Int {'Int'} sub Object {'Object'} 1;\n")
        self.kernel = root / 'enabled'; self.kernel.write_text('Y\n')
        self.profiles = root / 'profiles'; self.profiles.write_text(
            'labwc-compositor (enforce)\nlabwc-security-action-root (enforce)\n'
            'spotify (enforce)\nspotify//helper (enforce)\nspotify//null-1 (complain)\n')
        self.calls = root / 'calls'; self.directory = root / 'policy'; self.directory.mkdir()
        self.source = self.directory / 'usr.bin.spotify'; self.source.write_text('profile spotify {}\n')
        self.env = {**os.environ, 'AA_ADAPTER': str(adapter), 'AA_SOURCE': str(APPARMOR),
                    'AA_KERNEL': str(self.kernel), 'AA_PROFILES': str(self.profiles),
                    'AA_CALLS': str(self.calls), 'AA_DIRECTORY': str(self.directory),
                    'AA_BACKUP': str(root / 'backup')}

    def invoke(self, method, *args, **env):
        return subprocess.run([shutil.which('perl'), '-e', PERL_FIXTURE, method, *args],
                              text=True, capture_output=True, timeout=10, env={**self.env, **env})

    def worker(self, action, name='usr.bin.spotify', **env):
        return self.invoke('_change_profile_state', action, name, **env)

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_one_application_unload_noop_and_load_preserve_desktop(self):
        first = self.worker('unload'); self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('--remove ' + str(self.source), self.calls_made()[0])
        self.assertEqual(self.profiles.read_text(),
                         'labwc-compositor (enforce)\nlabwc-security-action-root (enforce)\n')
        before = self.calls_made()
        again = self.worker('unload'); self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('Nothing to unload', again.stdout); self.assertEqual(self.calls_made(), before)
        loaded = self.worker('load'); self.assertEqual(loaded.returncode, 0, loaded.stderr)
        self.assertIn('--replace ' + str(self.source), self.calls_made()[-1])
        self.assertIn('labwc-compositor (enforce)', self.profiles.read_text())
        self.assertIn('spotify//helper (enforce)', self.profiles.read_text())

    def test_confirmation_and_independent_worker_routing(self):
        result = self.invoke('set_profile_state', 'unload', 'usr.bin.spotify',
                             'confirmed-apparmor-profile-state-change')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls_made(),
                         ['systemctl start -- labwc-apparmor-policy@profile-unload-usr.bin.spotify.service'])
        denied = self.invoke('set_profile_state', 'unload', 'usr.bin.spotify', 'wrong')
        self.assertNotEqual(denied.returncode, 0); self.assertIn('explicit confirmation', denied.stderr)

    def test_infrastructure_and_path_injection_are_rejected(self):
        for name in ('desktop-wrappers', 'system-wrappers', 'labwc-session', 'hardware-tuning',
                     'zoom-discord-compat', 'desktop-utilities', 'chatgpt', '../../etc/shadow', 'usr.bin.spotify.service/other'):
            with self.subTest(name=name):
                result = self.worker('unload', name)
                self.assertNotEqual(result.returncode, 0); self.assertIn('protected or unsupported', result.stderr)
        self.assertEqual(self.calls_made(), [])

    def test_protected_labels_cannot_hide_in_an_application_source(self):
        result = self.worker('unload', AA_LABELS='spotify\nlabwc-compositor\n')
        self.assertNotEqual(result.returncode, 0); self.assertIn('protected or unsupported', result.stderr)
        self.assertEqual(self.calls_made(), [])

    def test_package_vscode_label_and_tuta_multiple_roots_are_supported(self):
        for name, labels in (('code', 'vscode\n'), ('vscode', 'vscode\n'),
                             ('opt.tuta-mail.AppRun', 'tuta-mail\ntuta-mail//tuta-bwrap\ntuta-glycin-loader\n')):
            with self.subTest(source=name):
                (self.directory / name).write_text('profile fixture {}\n')
                result = self.worker('load', name, AA_LABELS=labels)
                self.assertEqual(result.returncode, 0, result.stderr)
                for label in labels.splitlines():
                    self.assertIn(label + ' (enforce)', self.profiles.read_text())
                result = self.worker('unload', name, AA_LABELS=labels)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('spotify (enforce)', self.profiles.read_text())

    def test_source_permissions_symlinks_and_disabled_markers_fail_closed(self):
        self.source.chmod(0o666)
        result = self.worker('load'); self.assertNotEqual(result.returncode, 0)
        self.assertIn('writable', result.stderr)
        self.source.chmod(0o644)
        disabled = self.directory / 'disable'; disabled.mkdir()
        (disabled / self.source.name).symlink_to(self.source)
        result = self.worker('load'); self.assertNotEqual(result.returncode, 0)
        self.assertIn('disabled on disk', result.stderr)
        (disabled / self.source.name).unlink()
        self.source.unlink(); self.source.symlink_to(self.kernel)
        result = self.worker('load'); self.assertNotEqual(result.returncode, 0)
        self.assertIn('non-symlink', result.stderr); self.assertEqual(self.calls_made(), [])

    def test_parser_failure_false_success_and_disabled_kernel_are_errors(self):
        result = self.worker('unload', AA_FAIL_COMMAND='1')
        self.assertNotEqual(result.returncode, 0); self.assertIn('status 9', result.stderr)
        result = self.worker('unload', AA_NO_CHANGE='1')
        self.assertNotEqual(result.returncode, 0); self.assertIn('remains loaded', result.stderr)
        self.kernel.write_text('N\n')
        result = self.worker('load'); self.assertNotEqual(result.returncode, 0)
        self.assertIn('not enabled', result.stderr)


class ProfileMenuTests(unittest.TestCase):
    def test_picker_and_confirmation_route_one_source_or_cancel(self):
        source = MENU.read_text()
        function = re.search(r'^set_apparmor_profile_state\(\) \{\n.*?^\}', source, re.M | re.S).group()
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        commands = Path(temporary.name)
        for name, body in {'labwc-security-action': '[ "${CANDIDATE_STATUS:-0}" -eq 0 ] || exit "$CANDIDATE_STATUS"; printf "%s\\n" usr.bin.spotify',
                           'labwc-fuzzel': "cat >/dev/null; printf '%s\\n' \"$PROFILE\""}.items():
            command = commands / name
            command.write_text('#!/bin/sh\n' + body + '\n'); command.chmod(0o700)
        script = function + r'''
choose_lines() { printf '%s\n' "$APPROVAL"; }
run_security_action() { printf '%s\n' "$*"; }
fatal() { exit 99; }
menu_failure() { [ "$1" -eq 1 ]; }
set_apparmor_profile_state "$1"
'''
        for action in ('load', 'unload'):
            for profile, approval in (('usr.bin.spotify', 'Continue with AppArmor profile change'),
                                      ('', 'Continue with AppArmor profile change'), ('usr.bin.spotify', 'Cancel')):
                with self.subTest(action=action, profile=profile, approval=approval):
                    result = subprocess.run(['/bin/sh', '-eu', '-c', script, 'fixture', action],
                        env={**os.environ, 'PATH': str(commands) + ':' + os.environ['PATH'],
                             'PROFILE': profile, 'APPROVAL': approval},
                        text=True, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = (f'set-apparmor-profile-state {action} usr.bin.spotify '
                                'confirmed-apparmor-profile-state-change\n') if profile and approval != 'Cancel' else ''
                    self.assertEqual(result.stdout, expected)
        failed = subprocess.run(['/bin/sh', '-eu', '-c', script, 'fixture', 'load'],
            env={**os.environ, 'PATH': str(commands) + ':' + os.environ['PATH'],
                 'CANDIDATE_STATUS': '7'}, text=True, capture_output=True, timeout=5)
        self.assertEqual(failed.returncode, 7); self.assertEqual(failed.stdout, '')
