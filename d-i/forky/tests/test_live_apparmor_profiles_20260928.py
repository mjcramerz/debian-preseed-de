"""Offline AppArmor profile action tests; no host policy or services are touched."""
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
use strict;
use warnings;
use lib $ENV{AA_ADAPTER};
BEGIN {
    $INC{'LabwcSecurityAction/Command.pm'} = 1;
    $INC{'LabwcSecurityAction/Logger.pm'} = 1;
}
my $loaded = do $ENV{AA_SOURCE};
die $@ || $! unless $loaded;
{
    package FakeCommand;
    sub run {
        my ($self, @args) = @_;
        open my $log, '>>', $ENV{AA_CALLS} or die $!;
        print {$log} join(' ', @args), "\n";
        close $log or die $!;
        return 9 if $ENV{AA_FAIL_COMMAND};
        if ($args[0] eq $ENV{AA_TEARDOWN}) {
            open my $state, '>', $ENV{AA_PROFILES} or die $!;
            close $state or die $!;
        }
        elsif ($args[0] eq $ENV{AA_LOADER}) {
            open my $state, '>', $ENV{AA_PROFILES} or die $!;
            print {$state} "fixture (enforce)\n";
            close $state or die $!;
        }
        return 0;
    }
}
{
    no warnings 'redefine';
    *LabwcSecurityAction::AppArmor::_policy_lock = sub {
        open my $lock, '<', $ENV{AA_KERNEL} or die $!;
        return $lock;
    };
    *LabwcSecurityAction::AppArmor::_validate_root_owned_file = sub { return; };
    *LabwcSecurityAction::AppArmor::_reconcile_modes = sub {
        open my $log, '>>', $ENV{AA_CALLS} or die $!;
        print {$log} "managed-modes\n";
        close $log or die $!;
        return $ENV{AA_FAIL_MODES} ? 11 : 0;
    };
}
my $manager = LabwcSecurityAction::AppArmor->new(
    command => bless({}, 'FakeCommand'),
    logger => bless({}, 'FakeLogger'),
    kernel_enabled_path => $ENV{AA_KERNEL},
    loaded_profiles_path => $ENV{AA_PROFILES},
    profile_loader => $ENV{AA_LOADER},
    profile_teardown => $ENV{AA_TEARDOWN},
);
$manager->set_profile_state(@ARGV);
'''


@unittest.skipUnless(shutil.which('perl'), 'Perl is required')
class LiveProfileActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        adapter = root / 'adapter'
        adapter.mkdir()
        (adapter / 'Moo.pm').write_text(MOO_ADAPTER)
        for name in ('MooX/StrictConstructor.pm', 'MooX/TypeTiny.pm'):
            path = adapter / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('package ' + name.removesuffix('.pm').replace('/', '::') + '; sub import {} 1;\n')
        standard = adapter / 'Types/Standard.pm'
        standard.parent.mkdir()
        standard.write_text("package Types::Standard; use Exporter 'import'; "
                            "our @EXPORT_OK=qw(Str Int Object); "
                            "sub Str {'Str'} sub Int {'Int'} sub Object {'Object'} 1;\n")
        self.kernel = root / 'enabled'
        self.kernel.write_text('Y\n')
        self.profiles = root / 'profiles'
        self.calls = root / 'calls'
        self.loader = root / 'apparmor.systemd'
        self.teardown = root / 'aa-teardown'
        for program in (self.loader, self.teardown):
            program.write_text('#!/bin/sh\nexit 0\n')
            program.chmod(0o700)
        self.env = {**os.environ, 'AA_ADAPTER': str(adapter), 'AA_SOURCE': str(APPARMOR),
                    'AA_KERNEL': str(self.kernel), 'AA_PROFILES': str(self.profiles),
                    'AA_CALLS': str(self.calls), 'AA_LOADER': str(self.loader),
                    'AA_TEARDOWN': str(self.teardown)}

    def run_action(self, action, *, confirmation='confirmed-apparmor-profile-state-change', **env):
        return subprocess.run([shutil.which('perl'), '-e', PERL_FIXTURE, action, confirmation],
                              text=True, capture_output=True, timeout=10,
                              env={**self.env, **env})

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_start_only_when_empty_then_reload_when_loaded(self):
        self.profiles.write_text('')
        first = self.run_action('load')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.calls_made(), [str(self.loader) + ' start', 'managed-modes'])
        self.calls.unlink()
        second = self.run_action('load')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.calls_made(), [str(self.loader) + ' reload', 'managed-modes'])

    def test_unload_and_empty_noop(self):
        self.profiles.write_text('fixture (enforce)\n')
        result = self.run_action('unload')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls_made(), [str(self.teardown)])
        self.calls.unlink()
        result = self.run_action('unload')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Nothing to unload', result.stdout)
        self.assertEqual(self.calls_made(), [])

    def test_denials_and_partial_failures_are_reported(self):
        self.profiles.write_text('')
        for action, confirmation, env, message in (
            ('load', 'wrong-confirmation', {}, 'explicit confirmation'),
            ('load', 'confirmed-apparmor-profile-state-change', {'AA_FAIL_COMMAND': '1'}, 'failed with status 9'),
            ('load', 'confirmed-apparmor-profile-state-change', {'AA_FAIL_MODES': '1'}, 'reconciliation failed'),
        ):
            with self.subTest(message=message):
                result = self.run_action(action, confirmation=confirmation, **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.profiles.write_text('')
        self.kernel.write_text('N\n')
        result = self.run_action('load')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not enabled', result.stderr)

    def test_menu_confirmation_routes_both_actions_and_cancel(self):
        source = MENU.read_text()
        function = re.search(r'^set_apparmor_profile_state\(\) \{\n.*?^\}', source, re.M | re.S)
        self.assertIsNotNone(function)
        script = (function.group() + '\n'
                  'choose_lines() { printf "%s\\n" "$APPROVAL"; }\n'
                  'run_security_action() { printf "%s\\n" "$*"; }\n'
                  'fatal() { printf "%s\\n" "$*" >&2; exit 1; }\n'
                  'set_apparmor_profile_state "$1"\n')
        for action in ('load', 'unload'):
            for approve in (True, False):
                with self.subTest(action=action, approve=approve):
                    result = subprocess.run(['/bin/sh', '-eu', '-c', script, 'fixture', action],
                                            env={**os.environ, 'APPROVAL':
                                                'Continue with AppArmor profile change' if approve else 'Cancel'},
                                            text=True, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = (f'set-apparmor-profile-state {action} '
                                'confirmed-apparmor-profile-state-change\n') if approve else ''
                    self.assertEqual(result.stdout, expected)
