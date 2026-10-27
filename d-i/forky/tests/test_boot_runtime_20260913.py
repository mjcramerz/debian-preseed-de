#!/usr/bin/env python3
"""Scoped boot/runtime regression tests. No package builds or kernel writes.

Perl tests normally use the installed Moo dependencies. In stripped-down test
containers a deliberately small test-only constructor adapter may be enabled by
MANAGED_TEST_PERL_ADAPTER=1. This exercises application control flow, not Moo's
integration or type system; it never enters the installer payload. AppArmor
commands and loaded-kernel state are always fixtures, never the real kernel.
"""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text, installed_script
from theme_fixture import render_theme_defaults, render_theme_bytes

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
LIB = TARGET / 'usr/local/lib/perl5/site_perl'
PERL = shutil.which('perl')
PERL_DEPS = bool(PERL and subprocess.run(
    payload_installed_argv([PERL, '-MMoo', '-MMooX::StrictConstructor', '-MMooX::TypeTiny',
     '-MMooX::Options', '-MTypes::Standard', '-e', '1']),
    capture_output=True, timeout=5).returncode == 0)
ADAPTER = os.environ.get('MANAGED_TEST_PERL_ADAPTER') == '1' and not PERL_DEPS

# No production file is modified or import path persisted by these fixtures.
MOO_ADAPTER = r'''
package Moo;
use strict; use warnings;
our %attributes;
sub import {
    my $class = caller;
    no strict 'refs';
    *{"${class}::has"} = sub {
        my ($name, %spec) = @_;
        $attributes{$class}{$name} = \%spec;
        *{"${class}::$name"} = sub {
            my $self = shift;
            if (@_) { die "read-only $name" unless $spec{is} eq 'rw'; $self->{$name} = shift; }
            return $self->{$name};
        };
    };
    *{"${class}::new"} = sub {
        my ($package, %args) = @_;
        my $self = bless {}, $package;
        for my $name (keys %{$attributes{$package} // {}}) {
            my $spec = $attributes{$package}{$name};
            if (exists $args{$name}) { $self->{$name} = delete $args{$name}; }
            elsif (exists $spec->{default}) {
                $self->{$name} = ref($spec->{default}) eq 'CODE' ? $spec->{default}->($self) : $spec->{default};
            }
            elsif ($spec->{required}) { die "missing $name"; }
        }
        die "unknown constructor arguments" if keys %args;
        return $self;
    };
}
1;
'''

FAKE_AA_TOOL = r'''#!/usr/bin/env python3
import json, os, pathlib, re, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
log = pathlib.Path(os.environ['AA_TEST_CALLS'])
with log.open('a') as fh:
    fh.write(json.dumps([name, *args]) + '\n')
if '--help' in args:
    print('--force')
    raise SystemExit(0)
path = pathlib.Path(args[-1])
source = path.read_text()
declarations = re.findall(r"^profile\s+([A-Za-z0-9_./-]+)([^\n{]*)\{", source, re.M)
base = pathlib.Path(args[args.index('--base') + 1]) if '--base' in args else path.parent
local = base / 'local' / path.name
if declarations and local.is_file() and 'include <local/' + path.name + '>' in source:
    declarations += [(declarations[0][0] + '//' + label, flags) for label, flags in
                     re.findall(r"^profile\s+([A-Za-z0-9_./-]+)([^\n{]*)\{", local.read_text(), re.M)]
labels = [label for label, _ in declarations]
kernel = pathlib.Path(os.environ['AA_TEST_KERNEL'])
if name == 'apparmor_parser' and '-N' in args:
    # The real parser honors disable/ even for names-only inspection.
    base = pathlib.Path(args[args.index('--base') + 1])
    if (base / 'disable' / path.name).is_symlink():
        raise SystemExit(0)
    print(''.join(label + '\n' for label in labels), end='')
    raise SystemExit(0)
if name == 'apparmor_parser' and '-Q' in args and os.environ.get('AA_TEST_COMPILE_FAIL') == '1':
    raise SystemExit(23)
if name in ('aa-enforce', 'aa-complain'):
    flags = ' flags=(complain)' if name == 'aa-complain' else ''
    source = re.sub(r'^(profile\s+\S+)(?:\s+flags=\([^)]*\))?\s*\{',
                    lambda m: m[1] + flags + ' {', source, flags=re.M)
    path.write_text(source)
if name == 'aa-audit':
    source = re.sub(r'flags=\(audit,?', 'flags=(', source)
    path.write_text(source)
if (name == 'apparmor_parser' and any(a in args for a in ('-r', '-R'))) or (
        name == 'aa-audit' and '--no-reload' not in args):
    if os.environ.get('AA_TEST_RELOAD_FAIL') == '1':
        raise SystemExit(19)
    lines = kernel.read_text().splitlines()
    lines = [line for line in lines if not any(line.startswith(label + ' (') for label in labels)]
    if '-R' not in args:
        lines += [f"{label} ({'complain' if 'complain' in flags else 'enforce'})" for label, flags in declarations]
    kernel.write_text(''.join(line + '\n' for line in lines))
'''


class PerlFixture(unittest.TestCase):
    def setUp(self):
        if not PERL or not (PERL_DEPS or ADAPTER):
            self.skipTest('Moo dependencies missing; MANAGED_TEST_PERL_ADAPTER=1 enables fixture-only control-flow tests')
        self.temp = tempfile.TemporaryDirectory(prefix='x-boot-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = os.environ.copy()
        if ADAPTER:
            self.adapter_dir = self.root / 'perl-test-adapter'
            self.adapter_dir.mkdir()
            (self.adapter_dir / 'Moo.pm').write_text(MOO_ADAPTER)
            for module in ('MooX::StrictConstructor', 'MooX::TypeTiny', 'MooX::Options'):
                p = self.adapter_dir / (module.replace('::', '/') + '.pm')
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f'package {module}; sub import {{}} 1;\n')
            p = self.adapter_dir / 'Types/Standard.pm'
            p.parent.mkdir()
            p.write_text("package Types::Standard; use Exporter 'import'; our @EXPORT_OK=qw(Str Int Bool ArrayRef); sub Str { 1 } sub Int { 1 } sub Bool { 1 } sub ArrayRef { 1 } 1;\n")
            self.env['PERL5LIB'] = str(self.adapter_dir)
        self.env['TMPDIR'] = str(self.root)


@unittest.skipUnless(os.geteuid() == 0, 'AppArmor fixtures retain root-ownership validation')
class AppArmorReconciliationTests(PerlFixture):
    def setUp(self):
        super().setUp()
        self.profiles = self.root / 'profiles'
        self.profiles.mkdir()
        (self.profiles / 'disable').mkdir()
        self.tools = self.root / 'tools'
        self.tools.mkdir()
        for name in ('apparmor_parser', 'aa-enforce', 'aa-complain', 'aa-audit'):
            p = self.tools / name
            p.write_text(FAKE_AA_TOOL)
            p.chmod(0o755)
        self.config = self.root / 'modes.conf'
        self.config.write_text('')
        self.config.chmod(0o600)
        self.kernel = self.root / 'loaded-profiles'
        self.kernel.write_text('')
        self.calls = self.root / 'calls.jsonl'
        self.env.update(AA_TEST_CALLS=str(self.calls), AA_TEST_KERNEL=str(self.kernel))

    def profile(self, name='alpha', *, want='complain', source='complain', loaded='complain', presence='required'):
        flags = ' flags=(complain)' if source == 'complain' else ''
        p = self.profiles / name
        p.write_text(f'profile {name}{flags} {{\n}}\n')
        p.chmod(0o644)
        with self.config.open('a') as fh:
            fh.write(f'{want} {presence} {name} -\n')
        if loaded:
            with self.kernel.open('a') as fh:
                fh.write(f'{name} ({loaded})\n')
        if source == 'disable':
            (self.profiles / 'disable' / name).symlink_to(p)
        return p

    def run_policy(self, *extra):
        return subprocess.run(payload_installed_argv([PERL, str(TARGET / 'usr/local/libexec/apparmor-modes-run'),
            '--config', str(self.config), '--profile-dir', str(self.profiles),
            '--tool-dir', str(self.tools), '--loaded-profiles', str(self.kernel), *extra]),
            env=self.env, capture_output=True, text=True, timeout=10)

    def tool_calls(self):
        return [json.loads(line) for line in render_theme_defaults(payload_read_text(self.calls)).splitlines()] if payload_source_exists(self.calls) else []

    def mutations(self):
        return [call for call in self.tool_calls() if '-N' not in call and '--help' not in call
                and not (call[0] == 'apparmor_parser' and '-Q' in call)]

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_matching_sources_and_kernel_do_not_reload_or_rewrite(self):
        a = self.profile()
        b = self.profile('beta', want='enforce', source='enforce', loaded='enforce')
        before = [(render_theme_bytes(payload_read_bytes(p)), payload_source_stat(p).st_ino, payload_source_stat(p).st_mtime_ns) for p in (a, b)]
        result = self.run_policy()
        self.assert_success(result)
        self.assertEqual(self.mutations(), [])
        self.assertEqual(sum('-N' in call for call in self.tool_calls()), 2)
        self.assertIn('reconciled=0', result.stdout)
        self.assertEqual(before, [(render_theme_bytes(payload_read_bytes(p)), payload_source_stat(p).st_ino, payload_source_stat(p).st_mtime_ns) for p in (a, b)])

    def test_kernel_only_drift_reloads_only_mismatching_profile_without_editing(self):
        a = self.profile(loaded='enforce')
        b = self.profile('beta')
        before = [(render_theme_bytes(payload_read_bytes(p)), payload_source_stat(p).st_ino, payload_source_stat(p).st_mtime_ns) for p in (a, b)]
        result = self.run_policy()
        self.assert_success(result)
        calls = self.mutations()
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0][0], 'apparmor_parser')
        self.assertIn('-r', calls[0])
        self.assertEqual(calls[0][-1], str(a))
        self.assertEqual(before, [(render_theme_bytes(payload_read_bytes(p)), payload_source_stat(p).st_ino, payload_source_stat(p).st_mtime_ns) for p in (a, b)])
        self.assertIn('alpha (complain)', render_theme_defaults(payload_read_text(self.kernel)))
        self.assertIn('reconciled=1', result.stdout)

    def test_explicit_reload_updates_policy_even_when_labels_and_modes_match(self):
        a = self.profile()
        b = self.profile('beta', want='enforce', source='enforce', loaded='enforce')
        before = [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in (a, b)]
        # Changing a rule does not change the kernel's label/mode listing.
        a.write_text(a.read_text().replace('\n}', '\n  /usr/bin/loginctl rix,\n}'))
        before[0] = (a.read_bytes(), a.stat().st_ino, a.stat().st_mtime_ns)
        result = self.run_policy('--force-reload')
        self.assert_success(result)
        calls = self.mutations()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call[0], 'apparmor_parser')
            self.assertIn('-r', call)
            self.assertIn('-T', call)
        self.assertEqual({call[-1] for call in calls}, {str(a), str(b)})
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in (a, b)])

    def test_force_reload_rejects_readonly_and_no_reload_combinations(self):
        self.profile()
        for flag in ('--check', '--check-loaded', '--no-reload'):
            with self.subTest(flag=flag):
                result = self.run_policy('--force-reload', flag)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('--force-reload requires', result.stderr)
                self.assertEqual(self.mutations(), [])

    def test_source_drift_changes_only_mismatching_profile_and_is_idempotent(self):
        self.profile(source='enforce', loaded='enforce')
        unchanged = self.profile('beta')
        before = payload_source_stat(unchanged).st_ino
        result = self.run_policy()
        self.assert_success(result)
        self.assertEqual([c[0] for c in self.mutations()], ['aa-complain', 'aa-audit', 'apparmor_parser'])
        self.assertEqual(payload_source_stat(unchanged).st_ino, before)
        self.assertIn('flags=(complain)', render_theme_defaults(payload_read_text(self.profiles / 'alpha')))
        self.calls.unlink()
        self.assert_success(self.run_policy())
        self.assertEqual(self.mutations(), [])

    def test_candidate_compilation_is_separate_from_production_cache_reload(self):
        parent = self.profile(source='enforce', loaded='enforce')
        self.assert_success(self.run_policy())
        compilations = [c for c in self.tool_calls()
                        if c[0] == 'apparmor_parser' and '-Q' in c and '-N' not in c]
        self.assertEqual(len(compilations), 1)
        candidate = compilations[0]
        self.assertIn('--config-file=/dev/null', candidate)
        self.assertIn('--policy-features=/usr/share/apparmor-features/features', candidate)
        self.assertIn('/usr/share/apparmor', candidate)
        self.assertIn('-K', candidate)
        self.assertNotEqual(candidate[-1], str(parent))
        reloads = [c for c in self.tool_calls() if c[0] == 'apparmor_parser' and '-r' in c]
        self.assertEqual(len(reloads), 1)
        self.assertEqual(reloads[0][-1], str(parent))
        self.assertFalse(any(c.startswith('--config-file') for c in reloads[0]))
        self.assertNotIn('-K', reloads[0])

    def test_disabled_source_already_absent_is_noop(self):
        self.profile(want='disable', source='disable', loaded=None)
        result = self.run_policy()
        self.assert_success(result)
        self.assertEqual(self.mutations(), [])
        self.assertIn('reconciled=0', result.stdout)

    def test_disabled_source_still_loaded_is_unloaded(self):
        self.profile(want='disable', source='disable', loaded='enforce')
        result = self.run_policy()
        self.assert_success(result)
        self.assertEqual(len(self.mutations()), 1)
        self.assertIn('-R', self.mutations()[0])
        self.assertEqual(render_theme_defaults(payload_read_text(self.kernel)), '')

    def test_check_loaded_is_readonly_and_checks_both_source_and_kernel(self):
        self.profile(loaded='enforce')
        result = self.run_policy('--check-loaded')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.mutations(), [])
        self.assertIn('alpha', result.stderr)
        self.kernel.write_text('alpha (complain)\n')
        self.assert_success(self.run_policy('--check-loaded'))
        (self.profiles / 'alpha').write_text('profile alpha {\n}\n')
        self.assertNotEqual(self.run_policy('--check-loaded').returncode, 0)

    def test_no_reload_does_not_require_kernel_state(self):
        parent = self.profile()
        self.kernel.unlink()
        self.assert_success(self.run_policy('--no-reload'))
        self.assertEqual(self.mutations(), [])
        compilations = [call for call in self.tool_calls()
                        if call[0] == 'apparmor_parser' and '-Q' in call and '-N' not in call]
        self.assertEqual(len(compilations), 1)
        self.assertEqual(compilations[0][-1], str(parent))
        self.assertIn('--config-file=/dev/null', compilations[0])
        self.assertIn('--policy-features=/usr/share/apparmor-features/features', compilations[0])
        self.assertIn('-K', compilations[0])
        self.assertIn('-T', compilations[0])

    def test_no_reload_rejects_matching_mode_when_regex_compilation_fails(self):
        parent = self.profile(want='enforce', source='enforce', loaded=None)
        before = (parent.read_bytes(), parent.stat().st_ino, parent.stat().st_mtime_ns)
        self.kernel.unlink()
        # Name listing succeeds; only full, non-loading compilation rejects.
        self.env['AA_TEST_COMPILE_FAIL'] = '1'
        result = self.run_policy('--no-reload')
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertTrue(any('-N' in call for call in self.tool_calls()))
        self.assertTrue(any('-Q' in call and '-N' not in call for call in self.tool_calls()))
        self.assertEqual(self.mutations(), [])
        self.assertEqual(before, (parent.read_bytes(), parent.stat().st_ino, parent.stat().st_mtime_ns))
        self.assertNotIn('profile source already uses', result.stdout)

    def test_optional_labelless_source_is_allowed(self):
        p = self.profile(presence='optional', loaded=None)
        p.write_text('# An include, not a standalone profile.\n')
        self.assert_success(self.run_policy())
        self.assertEqual(self.mutations(), [])

    def test_optional_disabled_profile_is_reenabled_and_verified(self):
        self.profile(presence='optional', source='disable', loaded=None)
        result = self.run_policy()
        self.assert_success(result)
        self.assertFalse(payload_source_exists(self.profiles / 'disable/alpha'))
        self.assertIn('alpha (complain)', render_theme_defaults(payload_read_text(self.kernel)))
        self.assertEqual([c[0] for c in self.mutations()], ['aa-complain', 'aa-audit', 'apparmor_parser'])
        self.calls.unlink()
        self.assert_success(self.run_policy())
        self.assertEqual(self.mutations(), [])

    def test_readonly_check_rejects_disabled_optional_named_profile(self):
        source = self.profile(presence='optional', source='disable', loaded=None)
        before = (render_theme_bytes(payload_read_bytes(source)), payload_source_stat(source).st_ino, payload_source_stat(source).st_mtime_ns)
        result = self.run_policy('--check-loaded')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('source mode mismatch', result.stderr)
        self.assertTrue((self.profiles / 'disable/alpha').is_symlink())
        self.assertEqual(self.mutations(), [])
        self.assertEqual(before, (render_theme_bytes(payload_read_bytes(source)), payload_source_stat(source).st_ino, payload_source_stat(source).st_mtime_ns))

    @unittest.skipUnless(shutil.which('apparmor_parser'), 'native parser not installed')
    def test_native_parser_finds_labels_when_reenabling_disabled_optional_profile(self):
        self.profile(presence='optional', source='disable', loaded=None)
        # Only names-only inspection reaches the real parser. Kernel loads and
        # aa-* edits still use fixtures. No policy compilation or kernel writes.
        wrapper = self.tools / 'apparmor_parser'
        wrapper.write_text(FAKE_AA_TOOL.replace(
            "    # The real parser honors disable/ even for names-only inspection.",
            "    os.execv(" + repr(shutil.which('apparmor_parser')) +
            ", [" + repr(shutil.which('apparmor_parser')) + ", *args])\n"
            "    # The real parser honors disable/ even for names-only inspection."))
        result = self.run_policy()
        self.assert_success(result)
        self.assertIn('alpha (complain)', render_theme_defaults(payload_read_text(self.kernel)))
        self.assertNotIn('source defines no labels', result.stdout)

    def test_required_labelless_source_is_rejected(self):
        p = self.profile(want='enforce', source='enforce', loaded=None)
        p.write_text('# Not a profile\n')
        result = self.run_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('defines no labels', result.stderr)

    def test_child_modes_follow_the_selected_parent_mode(self):
        p = self.profile()
        with p.open('a') as fh:
            fh.write('profile alpha//child flags=(complain) {\n}\n')
        with self.kernel.open('a') as fh:
            fh.write('alpha//child (enforce)\n')
        self.assertNotEqual(self.run_policy('--check-loaded').returncode, 0)
        self.assert_success(self.run_policy())
        self.assertEqual([call[0] for call in self.mutations()], ['apparmor_parser'])
        self.assertIn('alpha//child (complain)', self.kernel.read_text())
        self.kernel.write_text('alpha (complain)\nalpha//child (unconfined)\n')
        self.assertNotEqual(self.run_policy('--check-loaded').returncode, 0)

    def test_browser_include_child_follows_both_mode_transitions(self):
        parent = self.profile('vivaldi-bin', want='complain', source='complain')
        local = self.profiles / 'local'
        local.mkdir()
        child = local / 'vivaldi-bin'
        child.write_text('profile vivaldi-bwrap flags=(attach_disconnected, mediate_deleted) {\n}\n')
        child.chmod(0o644)
        self.assertNotEqual(self.run_policy('--check').returncode, 0)
        self.assert_success(self.run_policy('--no-reload'))
        self.assertIn('mediate_deleted, complain', child.read_text())
        self.assert_success(self.run_policy('--check'))
        self.config.write_text('enforce required vivaldi-bin -\n')
        self.assert_success(self.run_policy('--no-reload'))
        self.assertNotIn('complain', child.read_text())
        self.assertNotIn('complain', parent.read_text())
        self.assert_success(self.run_policy('--check'))

    def test_all_three_local_children_converge_after_one_live_transition(self):
        for parent_name, child_name in (("microsoft-edge-stable", "edge-glycin-bwrap"),
                                        ("mullvad-browser", "mullvad-bwrap"),
                                        ("vivaldi-bin", "vivaldi-bwrap")):
            parent = self.profile(parent_name, want="enforce", source="complain", loaded="complain")
            parent.write_text(f"profile {parent_name} flags=(complain) {{\ninclude <local/{parent_name}>\n}}\n")
            local = self.profiles / "local"
            local.mkdir(exist_ok=True)
            child = local / parent_name
            child.write_text(f"profile {child_name} flags=(attach_disconnected, complain) {{\n}}\n")
            with self.kernel.open("a") as stream:
                stream.write(f"{parent_name}//{child_name} (complain)\n")
        self.assert_success(self.run_policy())
        for parent_name, child_name in (("microsoft-edge-stable", "edge-glycin-bwrap"),
                                        ("mullvad-browser", "mullvad-bwrap"),
                                        ("vivaldi-bin", "vivaldi-bwrap")):
            self.assertIn(f"{parent_name}//{child_name} (enforce)", self.kernel.read_text())
            self.assertNotIn("complain", (self.profiles / "local" / parent_name).read_text())
        self.assertEqual(sum("-r" in call for call in self.tool_calls()), 3)
        self.assertFalse(list(self.profiles.glob(".apparmor-mode-recovery.*")))
        self.config.write_text("".join(f"complain required {name} -\n" for name in
                                      ("microsoft-edge-stable", "mullvad-browser", "vivaldi-bin")))
        self.assert_success(self.run_policy())
        self.assertNotIn("(enforce)", self.kernel.read_text())

    def test_failed_mode_rollback_retains_previous_parent_and_child_bytes(self):
        parent = self.profile("vivaldi-bin", want="enforce", source="complain", loaded="complain")
        parent.write_text("profile vivaldi-bin flags=(complain) {\ninclude <local/vivaldi-bin>\n}\n")
        local = self.profiles / "local"
        local.mkdir()
        child = local / "vivaldi-bin"
        child.write_text("profile vivaldi-bwrap flags=(attach_disconnected, complain) {\n}\n")
        with self.kernel.open("a") as stream:
            stream.write("vivaldi-bin//vivaldi-bwrap (complain)\n")
        before = (parent.read_bytes(), child.read_bytes())
        self.env["AA_TEST_RELOAD_FAIL"] = "1"
        result = self.run_policy()
        self.assertEqual(result.returncode, 3)
        self.assertEqual(before, (parent.read_bytes(), child.read_bytes()))
        bundles = list(self.profiles.glob(".apparmor-mode-recovery.*"))
        self.assertEqual(len(bundles), 1)
        self.assertIn(str(bundles[0]), result.stderr)
        self.assertEqual((bundles[0] / "parent").read_bytes(), before[0])
        self.assertEqual((bundles[0] / "child").read_bytes(), before[1])

    def test_every_declaration_in_one_file_has_its_selected_source_mode(self):
        profile = self.profile(source='complain', loaded='complain')
        with profile.open('a') as stream:
            stream.write('profile beta {\n}\n')
        self.assertNotEqual(self.run_policy('--check').returncode, 0)
        self.assert_success(self.run_policy('--no-reload'))
        self.assertIn('profile beta flags=(complain)', profile.read_text())
        self.assert_success(self.run_policy('--check'))

    def test_reload_failure_remains_failure(self):
        self.profile(loaded=None)
        self.env['AA_TEST_RELOAD_FAIL'] = '1'
        result = self.run_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('mode policy verified', result.stdout)

    def test_config_symlink_and_writable_source_remain_rejected(self):
        p = self.profile()
        p.chmod(0o666)
        self.assertNotEqual(self.run_policy().returncode, 0)
        p.chmod(0o644)
        real = self.config.with_suffix('.real')
        self.config.rename(real)
        self.config.symlink_to(real)
        self.assertNotEqual(self.run_policy().returncode, 0)

    def test_logging_has_one_sanitized_copy_and_no_syslog_dependency(self):
        code = r'''use AppArmor::ManagedModes::CLI qw(info warn); info("hello\nworld"); warn("watch\x01this");'''
        result = subprocess.run(payload_installed_argv([PERL, '-I' + str(LIB / 'apparmor-modes'), '-e', code]),
            env=self.env, capture_output=True, text=True, timeout=5)
        self.assert_success(result)
        self.assertEqual(result.stdout, 'apparmor-modes: hello world\n')
        self.assertEqual(result.stderr, 'apparmor-modes: warning: watch?this\n')
        self.assertNotIn('Sys::Syslog', render_theme_defaults(payload_read_text(LIB / 'apparmor-modes/AppArmor/ManagedModes/Logger.pm')))


class AppArmorReloadContractTests(PerlFixture):
    """Unprivileged control-flow checks; no trusted-path or kernel emulation."""

    def run_perl(self, code, *arguments):
        return subprocess.run([PERL, '-I' + str(LIB / 'apparmor-modes'), '-e', code, '--',
                               *arguments], env=self.env, capture_output=True,
                              text=True, encoding='utf-8', timeout=5)

    def test_bounded_reader_rejects_fifo_symlink_directory_and_oversize(self):
        path = self.root / 'data'
        code = r'''use AppArmor::ManagedModes::TrustedPath qw(read_bounded_file);
            my $value = read_bounded_file('fixture', $ARGV[0], 4); print $value;'''
        path.write_bytes(b'four')
        result = self.run_perl(code, str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'four')
        path.write_bytes(b'large')
        self.assertNotEqual(self.run_perl(code, str(path)).returncode, 0)
        path.unlink(); os.mkfifo(path)
        self.assertNotEqual(self.run_perl(code, str(path)).returncode, 0)
        path.unlink(); path.symlink_to('/dev/null')
        self.assertNotEqual(self.run_perl(code, str(path)).returncode, 0)
        path.unlink(); path.mkdir()
        self.assertNotEqual(self.run_perl(code, str(path)).returncode, 0)

    def test_workspace_failures_preserve_target_and_track_staging_until_cleanup(self):
        for operation in ('chmod', 'rename'):
            with self.subTest(operation=operation):
                source = self.root / 'source'
                target = self.root / 'target'
                source.write_text('candidate')
                target.write_text('previous')
                override = {
                    'chmod': r"BEGIN { *CORE::GLOBAL::chmod = sub { return 0 if $_[0] == 0644 && $_[1] =~ /[.]apparmor-modes[.]/; CORE::chmod($_[0], $_[1]); }; }",
                    'rename': r"BEGIN { *CORE::GLOBAL::rename = sub { return 0; }; }",
                }[operation]
                code = override + r'''
use AppArmor::ManagedModes::Workspace;
my ($root, $source, $target) = @ARGV;
my $workspace = AppArmor::ManagedModes::Workspace->new(tmp_root => $root);
local $AppArmor::ManagedModes::CLI::THROW_FAILURE = 1;
my $ok = eval { $workspace->publish_file($source, $target, 'injected publication failure'); 1 };
die "publication guard was ignored\n" if $ok;
die "staging forgotten\n" if !keys %{$workspace->files};
$workspace->cleanup or die "cleanup failed\n";
'''
                result = self.run_perl(code, str(self.root), str(source), str(target))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(target.read_text(), 'previous')
                self.assertFalse(list(self.root.glob('.apparmor-modes.*')))

    def test_failed_unlink_retains_workspace_ownership(self):
        code = r'''
BEGIN { *CORE::GLOBAL::unlink = sub { return 0 if $ENV{FIXTURE_UNLINK_FAIL}; CORE::unlink(@_); }; }
use AppArmor::ManagedModes::Workspace;
my $workspace = AppArmor::ManagedModes::Workspace->new(tmp_root => $ARGV[0]);
my ($fh, $path) = $workspace->tempfile('unlink-fixture'); close $fh;
local $AppArmor::ManagedModes::CLI::THROW_FAILURE = 1;
$ENV{FIXTURE_UNLINK_FAIL} = 1;
my $ok = eval { $workspace->remove_file($path); 1 };
die "unlink guard was ignored\n" if $ok;
die "failed unlink forgotten\n" if !$workspace->files->{$path} || !-f $path;
delete $ENV{FIXTURE_UNLINK_FAIL};
$workspace->cleanup or die "cleanup failed\n";
'''
        result = self.run_perl(code, str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(list(self.root.glob('unlink-fixture.*')))

    def test_open_and_redirect_failures_do_not_report_success(self):
        source = self.root / 'source'
        source.write_text('fixture')
        bad = self.root / 'directory'
        bad.mkdir()
        cases = [
            (r"use AppArmor::ManagedModes::TrustedPath qw(bounded_capture); bounded_capture('fixture', $ARGV[0], $ARGV[1], 32);", str(source), str(bad)),
            (r"use AppArmor::ManagedModes::Workspace; my $w = AppArmor::ManagedModes::Workspace->new; $w->copy_file($ARGV[0], $ARGV[1], 'fixture open failed');", str(self.root / 'missing'), str(self.root / 'out')),
            (r"use AppArmor::ManagedModes::Tool; AppArmor::ManagedModes::Tool->new->run_stdout_to_file_limited_or_exit($ARGV[0], 32, 'fixture overflow', '/usr/bin/true');", str(bad)),
        ]
        for code, *arguments in cases:
            with self.subTest(code=code):
                self.assertNotEqual(self.run_perl(code, *arguments).returncode, 0)

    def test_disable_mkdir_and_symlink_fail_at_the_original_guard(self):
        for operation in ('mkdir', 'symlink'):
            with self.subTest(operation=operation):
                profiles = self.root / operation
                profiles.mkdir()
                (profiles / 'fixture').write_text('profile fixture {\n}\n')
                overrides = {
                    'mkdir': r"BEGIN { *CORE::GLOBAL::mkdir = sub { return 0 if caller eq 'AppArmor::ManagedModes::Transition'; CORE::mkdir($_[0], $_[1]); }; }",
                    'symlink': r"BEGIN { *CORE::GLOBAL::symlink = sub { return 0; }; }",
                }
                code = overrides[operation] + r'''
use AppArmor::ManagedModes::Transition;
my $entry = {name => 'fixture', path => "$ARGV[0]/fixture", mode => 'disable'};
AppArmor::ManagedModes::Transition::_disable_profile(
    $entry, {profile_dir => $ARGV[0], reload_profiles => 0}, undef, undef, undef);
'''
                result = self.run_perl(code, str(profiles))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('cannot create AppArmor disable ' + ('directory' if operation == 'mkdir' else 'entry'), result.stderr)
                self.assertFalse((profiles / 'disable/fixture').is_symlink())

    def test_child_print_failure_never_reaches_publication(self):
        local = self.root / 'local'
        local.mkdir()
        (local / 'vivaldi-bin').write_text('profile vivaldi-bwrap flags=(attach_disconnected) {\n}\n')
        code = r'''
use AppArmor::ManagedModes::LocalChildren qw(apply_child_mode);
{ package BrokenWriter; sub TIEHANDLE { bless {}, shift } sub PRINT { 0 } sub CLOSE { 1 } }
{ package FixtureWorkspace;
  sub tempfile { tie *FixtureWorkspace::BROKEN, 'BrokenWriter'; return (\*FixtureWorkspace::BROKEN, '/fixture/not-created'); }
  sub publish_file { die "unexpected publication\n"; }
}
local $AppArmor::ManagedModes::CLI::THROW_FAILURE = 1;
my $ok = eval { apply_child_mode('complain', 'vivaldi-bin', $ARGV[0], bless({}, 'FixtureWorkspace')); 1 };
die "print guard was ignored\n" if $ok || $@ !~ /cannot write AppArmor child include/;
'''
        result = self.run_perl(code, str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ai_diagnostic_reader_bounds_bytes_and_rejects_bad_utf8(self):
        path = self.root / 'diagnostic'; path.write_bytes('value é'.encode('utf-8'))
        module = installed_script(LIB / 'ai-copilots/AICopilots/Runtime.pm')
        code = r'''binmode STDOUT, ':encoding(UTF-8)';
            require $ARGV[0]; my $reader = AICopilots::Runtime->new();
            print $reader->_read_file($ARGV[1], 16, 1);'''
        def run():
            return subprocess.run([PERL, '-I' + str(LIB / 'ai-copilots'), '-I' + str(LIB / 'runtime'),
                '-e', code, '--', str(module), str(path)], env=self.env, capture_output=True,
                text=True, encoding='utf-8', timeout=5)
        result = run(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'value é')
        for data in (b'x' * 17, b'\xff'):
            path.write_bytes(data)
            self.assertNotEqual(run().returncode, 0)
        path.unlink(); os.mkfifo(path)
        self.assertNotEqual(run().returncode, 0)

    def test_zram_config_reader_rejects_special_files_and_oversize(self):
        path = self.root / 'zram.conf'; path.write_text('[global]\nvalue=ok\n', encoding='ascii')
        code = r'''use Zram::Config::Parser;
            my $reader = Zram::Config::Parser->new(max_config_bytes => 32);
            print $reader->parse($ARGV[0])->{global}{value};'''
        def run():
            return subprocess.run([PERL, '-I' + str(LIB / 'zram-writeback'), '-e', code,
                '--', str(path)], env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=5)
        result = run(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'ok')
        path.write_bytes(b'x' * 33)
        self.assertNotEqual(run().returncode, 0)
        path.unlink(); os.mkfifo(path)
        self.assertNotEqual(run().returncode, 0)
        path.unlink(); path.symlink_to('/dev/null')
        self.assertNotEqual(run().returncode, 0)

    def test_digital_asset_selection_reader_bounds_and_decodes_the_list(self):
        path = self.root / 'labwc-digital-assets-list.abcdef'
        files = [self.root / 'one.md', self.root / 'two.md']
        for file in files:
            file.write_bytes(b'fixture')
        path.write_text('\n'.join(map(str, files)) + '\n', encoding='utf-8'); path.chmod(0o600)
        module = installed_script(LIB / 'digital-assets/DigitalAssets/Context.pm')
        code = r'''require $ARGV[0];
            my $reader = DigitalAssets::Context->new(runtime_directory => $ARGV[1], home => $ARGV[1]);
            print scalar @{$reader->read_input_list('markdown', $ARGV[2])};'''
        def run():
            return subprocess.run([PERL, '-I' + str(LIB / 'digital-assets'), '-I' + str(LIB / 'runtime'),
                '-e', code, '--', str(module), str(self.root), str(path)], env=self.env,
                capture_output=True, text=True, encoding='utf-8', timeout=5)
        result = run(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '2')
        for data in (b'x' * 16_385, b'\xff'):
            path.write_bytes(data)
            self.assertNotEqual(run().returncode, 0)
        path.unlink(); os.mkfifo(path, 0o600)
        self.assertNotEqual(run().returncode, 0)

    def test_force_reload_option_and_incompatible_flags(self):
        code = r'''use JSON::PP; use AppArmor::ManagedModes::CLI qw(parse_args);
            print encode_json(parse_args(@ARGV));'''
        result = self.run_perl(code, '--force-reload')
        self.assertEqual(result.returncode, 0, result.stderr)
        options = json.loads(result.stdout)
        self.assertEqual(options['force_reload'], 1)
        self.assertEqual(options['reload_profiles'], 1)
        for flag in ('--check', '--check-loaded', '--no-reload'):
            for arguments in (('--force-reload', flag), (flag, '--force-reload')):
                with self.subTest(arguments=arguments):
                    result = self.run_perl(code, *arguments)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('--force-reload requires', result.stderr)

    def test_force_reload_uses_parser_even_when_source_and_kernel_modes_match(self):
        # Tool and trusted-path boundaries are mocks. Execute the real
        # apply_profile_mode branch without elevating privileges or loading
        # policy into the development kernel.
        code = r'''
use JSON::PP;
use AppArmor::ManagedModes::Transition qw(apply_profile_mode);
{
    package FixtureTools;
    sub new { bless { calls => [] }, shift }
    sub require_executable { push @{$_[0]->{calls}}, ['require', $_[1], $_[2]] }
    sub run_or_exit { my $self = shift; push @{$self->{calls}}, ['run', @_] }
}
no warnings 'redefine';
local *AppArmor::ManagedModes::Transition::_validate_disable_entry = sub {};
local *AppArmor::ManagedModes::Transition::profile_defines_labels = sub { 1 };
local *AppArmor::ManagedModes::Transition::profile_mode_matches = sub { 1 };
local *AppArmor::ManagedModes::Transition::loaded_profile_mode_matches = sub { 1 };
my ($mode, $force) = @ARGV;
my $entry = { mode => $mode, name => 'fixture', path => '/fixture/profiles/fixture' };
my $options = { profile_dir => '/fixture/profiles', tool_dir => '/fixture/tools',
                reload_profiles => 1, force_reload => $force };
my $tools = FixtureTools->new;
my $changed = apply_profile_mode($entry, $options, undef, $tools, {});
print encode_json({ changed => $changed, calls => $tools->{calls} }), "\n";
'''
        for mode in ('enforce', 'complain'):
            with self.subTest(mode=mode):
                result = self.run_perl(code, mode, '1')
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(report['changed'], 1)
                mutations = [c for c in report['calls'] if c[0] == 'run']
                self.assertEqual(mutations, [['run', '/fixture/tools/apparmor_parser', '-r',
                                             '-T', '-I', '/fixture/profiles', '--base',
                                             '/fixture/profiles', '/fixture/profiles/fixture']])
                result = self.run_perl(code, mode, '0')
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(report, {'changed': 0, 'calls': []})
        # A forced reload must never enable a deliberately disabled profile.
        result = self.run_perl(code, 'disable', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1]), {'changed': 0, 'calls': []})

    def test_reload_modules_compile_with_the_installed_perl_dependencies(self):
        for module in ('CLI', 'Transition'):
            with self.subTest(module=module):
                path = LIB / 'apparmor-modes/AppArmor/ManagedModes' / (module + '.pm')
                result = subprocess.run([PERL, '-I' + str(LIB / 'apparmor-modes'), '-c',
                                         str(path)], env=self.env, capture_output=True,
                                        text=True, encoding='utf-8', timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('syntax OK', result.stderr)


class NetworkReadinessTests(PerlFixture):
    def setUp(self):
        super().setUp()
        self.sysfs = self.root / 'net'
        self.sysfs.mkdir()
        (self.root / 'etc/default').mkdir(parents=True)
        (self.root / 'etc/network/interfaces.d').mkdir(parents=True)
        self.config = self.root / 'etc/network/host.conf'
        self.config.write_text("""MANAGED_NETWORK_MODE=static
MANAGED_NETWORK_DNS_MODE=link
MANAGED_NETWORK_LINK_TYPES=ethernet
MANAGED_NETWORK_ETHERNET_IFACE=enp1s0
MANAGED_NETWORK_ETHERNET_MAC=02:00:00:00:00:01
MANAGED_NETWORK_ETHERNET_IPV4_CIDR=192.0.2.2/24
MANAGED_NETWORK_IPV4_GATEWAY=192.0.2.1
MANAGED_NETWORK_IPV4_DNS=192.0.2.53
MANAGED_NETWORK_IPV6_ENABLED=false
""")
        self.config.chmod(0o600)
        (self.root / 'etc/network/interfaces').write_text('source /etc/network/interfaces.d/*\n')
        self.staged = self.root / 'etc/network/interfaces.d/50-network'
        self.staged.write_text('iface enp1s0 inet static\n'
                              '    address 192.0.2.2\n'
                              '    netmask 255.255.255.0\n'
                              '    gateway 192.0.2.1\n'
                              '    dns-nameservers 192.0.2.53\n'
                              '    metric 100\n')
        self.staged.chmod(0o600)
        for relative, mode in (
            ('usr/local/libexec/network-ifup-hotplug', 0o755),
            ('etc/systemd/system/ifup@.service.d/40-device-lifecycle.conf', 0o644),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload_read_text(TARGET / relative), encoding='utf-8')
            path.chmod(mode)
        self.env.update(MANAGED_TARGET_ROOT=str(self.root), MANAGED_SYS_CLASS_NET=str(self.sysfs), SYSTEMD_LOG_LEVEL='info')

    def adapter(self, name='enp1s0', mac='02:00:00:00:00:01', type_='1', wireless=False):
        p = self.sysfs / name
        p.mkdir(exist_ok=True)
        (p / 'address').write_text(mac + '\n')
        (p / 'type').write_text(type_ + '\n')
        if wireless:
            (p / 'wireless').mkdir(exist_ok=True)

    def wifi_profile_fixture(self):
        profile = self.root / 'etc/network/wifi.nmconnection'
        profile.write_text('[connection]\ntype=wifi\ninterface-name=wlan0\nautoconnect=true\n'
                           '[wifi]\nmode=infrastructure\nmac-address=02:00:00:00:00:02\n'
                           '[ipv4]\nmethod=manual\nforwarding=1\naddress1=192.0.2.3/24\ngateway=192.0.2.1\n'
                           'dns=192.0.2.53;\nroute-metric=200\nignore-auto-dns=true\n'
                           'ignore-auto-routes=true\nmay-fail=false\n'
                           '[ipv6]\nmethod=disabled\nroute-metric=200\n'
                           'ignore-auto-dns=true\nignore-auto-routes=true\n')
        profile.chmod(0o600)
        nm = self.root / 'etc/NetworkManager/conf.d/90-network-external.conf'
        nm.parent.mkdir(parents=True, exist_ok=True)
        nm.write_text('[keyfile]\nunmanaged-devices=interface-name:enp1s0\n'
                      '[device-wifi]\nmatch-device=interface-name:wlan0\nmanaged=1\n')

    def validate(self, *args):
        return subprocess.run(payload_installed_argv([PERL, str(TARGET / 'usr/local/libexec/network-run'), 'validate', *args]),
            env=self.env, capture_output=True, text=True, timeout=5)

    def test_present_adapter_does_not_wait_for_other_devices(self):
        self.adapter()
        result = self.validate('--wait-seconds', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('waiting for managed', result.stderr)

    def test_generated_dns_modes_are_accepted_by_the_installed_reader(self):
        self.adapter()
        (self.sysfs / 'enp1s0/device').mkdir()
        values = {
            'MANAGED_NETWORK_TARGET_ROOT': str(self.root),
            'MANAGED_NETWORK_SYS_CLASS_NET': str(self.sysfs),
            'MANAGED_NETWORK_WAIT_SECONDS': '1',
            'MANAGED_NETWORK_DOMAIN': 'example.test',
            'MANAGED_NETWORK_IPV4_ADDRESS': '192.0.2.2',
            'MANAGED_NETWORK_IPV4_NETMASK': '255.255.255.0',
            'MANAGED_NETWORK_IPV4_GATEWAY': '192.0.2.1',
            'MANAGED_NETWORK_IPV4_DNS': '192.0.2.53',
            'MANAGED_NETWORK_IPV6_ENABLED': 'true',
            'MANAGED_NETWORK_IPV6_ADDRESS': '2001:db8::2/64',
            'MANAGED_NETWORK_IPV6_GATEWAY': '2001:db8::1',
            'MANAGED_NETWORK_IPV6_DNS': '2001:db8::53',
        }
        input_path = self.root / 'network-input.env'
        for mode in ('link', 'global'):
            with self.subTest(mode=mode):
                values['MANAGED_NETWORK_DNS_MODE'] = mode
                input_path.write_text(''.join(key + "='" + value + "'\n" for key, value in values.items()),
                                      encoding='ascii')
                generated = subprocess.run([PERL, str(FORKY / 'scripts/late/network-generate.pl'),
                    '--input', str(input_path), '--target-templates', str(TARGET),
                    '--fragments', str(FORKY / 'scripts/late/templates/network')],
                    env=self.env, capture_output=True, text=True, encoding='utf-8', timeout=5)
                self.assertEqual(generated.returncode, 0, generated.stderr)
                result = self.validate('--staged-only')
                self.assertEqual(result.returncode, 0, result.stderr)
                # Model the installed udev rename without changing a real link.
                if (self.sysfs / 'enp1s0').exists():
                    (self.sysfs / 'enp1s0').rename(self.sysfs / 'eth0')
                result = self.validate('--allow-absent')
                self.assertEqual(result.returncode, 0, result.stderr)
                result = self.validate()
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_dns_mode_fails_even_with_a_detached_adapter(self):
        with self.config.open('a', encoding='ascii') as fh:
            fh.write('MANAGED_NETWORK_DNS_MODE=invalid\n')
        result = self.validate('--allow-absent')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MANAGED_NETWORK_DNS_MODE must be link or global', result.stderr)

    def test_staged_validation_checks_policy_before_adapter_renames(self):
        self.adapter(mac='02:00:00:00:00:02')
        self.assertEqual(self.validate('--staged-only').returncode, 0)
        self.assertNotEqual(self.validate('--allow-absent').returncode, 0)
        for key, value in (('MANAGED_NETWORK_ETHERNET_MAC', 'invalid'),
                           ('MANAGED_NETWORK_ETHERNET_IPV4_CIDR', '192.0.2.2/99')):
            original = self.config.read_text(encoding='ascii')
            with self.subTest(key=key):
                with self.config.open('a', encoding='ascii') as fh:
                    fh.write(key + '=' + value + '\n')
                self.assertNotEqual(self.validate('--staged-only').returncode, 0)
                self.config.write_text(original, encoding='ascii')
        self.staged.write_text('iface enp1s0 inet dhcp\n', encoding='ascii')
        self.assertNotEqual(self.validate('--staged-only').returncode, 0)

    def test_staged_validation_does_not_require_target_sysfs(self):
        self.env['MANAGED_SYS_CLASS_NET'] = str(self.root / 'unmounted-sysfs')
        self.assertEqual(self.validate('--staged-only').returncode, 0)
        self.assertNotEqual(self.validate('--allow-absent').returncode, 0)

    def test_hotplug_assets_must_exist_and_have_private_code_authority(self):
        helper = self.root / 'usr/local/libexec/network-ifup-hotplug'
        original = helper.read_bytes()
        for kind in ('missing', 'writable', 'symlink', 'hardlink', 'placeholder'):
            with self.subTest(kind=kind):
                helper.unlink()
                helper.write_bytes(original)
                helper.chmod(0o755)
                alias = self.root / 'helper-alias'
                if kind == 'missing':
                    helper.unlink()
                elif kind == 'writable':
                    helper.chmod(0o777)
                elif kind == 'symlink':
                    alias.write_bytes(original)
                    helper.unlink()
                    helper.symlink_to(alias)
                elif kind == 'hardlink':
                    os.link(helper, alias)
                else:
                    helper.write_bytes(original + b'\n# __INSTALLER_UNRESOLVED__\n')
                result = self.validate('--staged-only')
                self.assertNotEqual(result.returncode, 0)
                alias.unlink(missing_ok=True)
                if not helper.exists() and not helper.is_symlink():
                    helper.write_bytes(original)
        helper.unlink()
        helper.write_bytes(original)
        helper.chmod(0o755)

    def test_hotplug_unit_cannot_override_its_delegate_or_lifecycle(self):
        unit = self.root / 'etc/systemd/system/ifup@.service.d/40-device-lifecycle.conf'
        original = unit.read_text()
        for suffix in ('Type=simple\n', 'ExecStart=/unexpected/helper\n', 'KillMode=process\n'):
            with self.subTest(suffix=suffix):
                unit.write_text(original + suffix)
                result = self.validate('--staged-only')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('invalid managed hotplug service contract', result.stderr)
        unit.write_text(original)

    def test_staged_only_rejects_boot_hardware_options_and_duplicates(self):
        for options in (('--staged-only', '--allow-absent'),
                        ('--allow-absent', '--staged-only'),
                        ('--staged-only', '--wait-seconds', '0'),
                        ('--staged-only', '--staged-only')):
            with self.subTest(options=options):
                self.assertNotEqual(self.validate(*options).returncode, 0)

    def test_global_dns_rejects_per_link_plain_dns_servers(self):
        with self.config.open('a', encoding='ascii') as fh:
            fh.write('MANAGED_NETWORK_DNS_MODE=global\n')
        with self.staged.open('a', encoding='ascii') as fh:
            fh.write('    dns-nameservers 192.0.2.53\n')
        result = self.validate('--staged-only')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must not configure per-link DNS in global mode', result.stderr)

    def test_network_files_reject_fifos_without_waiting_for_a_writer(self):
        self.adapter()
        for path in (self.config, self.staged, self.sysfs/'enp1s0/address'):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.unlink()
                os.mkfifo(path, 0o600)
                result = self.validate()
                self.assertNotEqual(result.returncode, 0, result.stderr)
                path.unlink()
                path.write_bytes(original)
                path.chmod(0o600)

    def test_network_reader_honors_byte_limits_and_preserves_byte_values(self):
        code = r'''use ManagedNetwork::Config;
            my ($path, $limit) = @ARGV;
            print ManagedNetwork::Config->read_file_limited($path, $limit);'''
        path = self.root/'bounded'
        for value, limit, expected in ((b'value\n', 6, 0), (b'x' * 33, 32, 1)):
            path.write_bytes(value)
            result = subprocess.run([PERL, '-I' + str(LIB/'network'), '-e', code, '--', str(path), str(limit)],
                                    env=self.env, capture_output=True, timeout=5)
            self.assertEqual(bool(result.returncode), bool(expected), result.stderr)
            if not expected:
                self.assertEqual(result.stdout, value)

    def test_delayed_expected_adapter_succeeds(self):
        timer = threading.Timer(0.3, self.adapter)
        timer.start()
        self.addCleanup(timer.join)
        start = time.monotonic()
        result = self.validate('--wait-seconds', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(time.monotonic() - start, 0.2)
        self.assertIn('enp1s0', result.stderr)

    def test_unrelated_adapter_does_not_satisfy_wait(self):
        self.adapter('unrelated0')
        start = time.monotonic()
        result = self.validate('--wait-seconds', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('timed out after 1s', result.stderr)
        self.assertIn('enp1s0', result.stderr)
        self.assertLess(time.monotonic() - start, 3)

    def test_manual_validation_does_not_wait_by_default(self):
        result = self.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expected ethernet interface is absent', result.stderr)
        self.assertNotIn('waiting for managed', result.stderr)

    def test_boot_validation_accepts_a_detached_adapter_but_keeps_policy_checks(self):
        result = self.validate('--wait-seconds', '0', '--allow-absent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('adapter is not attached: enp1s0', result.stderr)
        self.staged.write_text('iface enp1s0 inet dhcp\n')
        result = self.validate('--allow-absent')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('lacks static IPv4 stanza', result.stderr)

    def test_boot_validation_does_not_hide_present_adapter_mismatch(self):
        self.adapter(mac='02:00:00:00:00:02')
        result = self.validate('--allow-absent')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('has MAC', result.stderr)

    def test_boot_wifi_does_not_wait_for_detached_ethernet(self):
        with self.config.open('a') as fh:
            fh.write("MANAGED_NETWORK_LINK_TYPES='ethernet wifi'\nMANAGED_NETWORK_WIFI_IFACE=wlan0\n"
                     'MANAGED_NETWORK_WIFI_MAC=02:00:00:00:00:02\n'
                     'MANAGED_NETWORK_WIFI_IPV4_CIDR=192.0.2.3/24\n')
        self.wifi_profile_fixture()
        self.adapter('wlan0', mac='02:00:00:00:00:02', wireless=True)
        start = time.monotonic()
        result = self.validate('--wait-seconds', '2', '--allow-absent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertIn('adapter is not attached: enp1s0', result.stderr)

    def test_boot_validation_still_waits_for_late_adapter_registration(self):
        timer = threading.Timer(0.3, self.adapter)
        timer.start()
        self.addCleanup(timer.join)
        result = self.validate('--wait-seconds', '2', '--allow-absent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('adapter is not attached', result.stderr)

    def test_wait_cannot_hide_mac_type_or_wireless_mismatch(self):
        for changes, message in [({'mac': '02:00:00:00:00:02'}, 'has MAC'),
                                 ({'type_': '772'}, 'ARPHRD_ETHER'),
                                 ({'wireless': True}, 'marked wireless')]:
            with self.subTest(changes=changes):
                p = self.sysfs / 'enp1s0'
                if payload_source_exists(p):
                    shutil.rmtree(p)
                self.adapter(**changes)
                result = self.validate('--wait-seconds', '1')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_cli_rejects_unbounded_or_malformed_wait(self):
        for value in ('-1', '16', '100', '1.5', '01', 'abc', '1;true'):
            with self.subTest(value=value):
                result = self.validate('--wait-seconds', value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('usage:', result.stderr)

    def test_cli_accepts_boot_option_order_and_rejects_duplicates_or_unknowns(self):
        self.assertEqual(self.validate('--allow-absent', '--wait-seconds', '0').returncode, 0)
        for args in (('--allow-absent', '--allow-absent'), ('--allow-absent=true',),
                     ('--wait-seconds', '0', '--wait-seconds', '1'), ('--allow-absent', '--wait-seconds'),
                     ('--allow-absent', 'untrusted'), ('--allow-absent', '--unknown')):
            with self.subTest(args=args):
                result = self.validate(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('usage:', result.stderr)

    def test_both_adapters_share_one_deadline(self):
        with self.config.open('a') as fh:
            fh.write("MANAGED_NETWORK_LINK_TYPES='ethernet wifi'\nMANAGED_NETWORK_WIFI_IFACE=wlan0\n"
                     'MANAGED_NETWORK_WIFI_MAC=02:00:00:00:00:02\n'
                     'MANAGED_NETWORK_WIFI_IPV4_CIDR=192.0.2.3/24\n')
        self.wifi_profile_fixture()
        start = time.monotonic()
        result = self.validate('--wait-seconds', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('enp1s0,wlan0', result.stderr)
        self.assertLess(time.monotonic() - start, 2)

    def test_wifi_native_profile_preserves_static_address_and_dns_policy(self):
        self.adapter()
        self.adapter('wlp2s0', mac='02:00:00:00:00:02', wireless=True)
        for name in ('enp1s0', 'wlp2s0'):
            (self.sysfs / name / 'device').mkdir()
        values = {'MANAGED_NETWORK_TARGET_ROOT': str(self.root),
                  'MANAGED_NETWORK_SYS_CLASS_NET': str(self.sysfs),
                  'MANAGED_NETWORK_LINK_TYPES': 'ethernet wifi',
                  'MANAGED_NETWORK_IPV4_ADDRESS': '192.168.50.88',
                  'MANAGED_NETWORK_IPV4_NETMASK': '255.255.255.0',
                  'MANAGED_NETWORK_IPV4_GATEWAY': '192.168.50.1',
                  'MANAGED_NETWORK_IPV4_DNS': '192.168.50.1',
                  'MANAGED_NETWORK_WIFI_CIDR': '192.168.50.1/24',
                  'MANAGED_NETWORK_IPV6_ENABLED': 'true',
                  'MANAGED_NETWORK_IPV6_ADDRESS': '2001:db8::88/64',
                  'MANAGED_NETWORK_IPV6_GATEWAY': '2001:db8::1',
                  'MANAGED_NETWORK_IPV6_DNS': '2001:db8::53'}
        input_path = self.root / 'network-input.env'
        prepared = self.root / 'etc/network/wifi.nmconnection'
        for mode in ('link', 'global'):
            for ssid, security, password in (('', 'open', ''), ('Fixture Wi-Fi', 'open', ''),
                                             ('Fixture Wi-Fi', 'wpa', 'fixture passphrase'),
                                             ('Fixture Wi-Fi', 'sae', 'fixture passphrase'),
                                             ('Fixture Wi-Fi', 'wep', 'abcde'),
                                             ('Fixture Wi-Fi', 'legacy-wep', 'legacy passphrase')):
                with self.subTest(mode=mode, security=security, ssid=ssid):
                    values.update(MANAGED_NETWORK_DNS_MODE=mode, MANAGED_NETWORK_WIFI_ESSID=ssid,
                                  MANAGED_NETWORK_WIFI_PSK_SECURITY=security,
                                  MANAGED_NETWORK_WIFI_WPA=password, MANAGED_NETWORK_WIFI_WEP=password)
                    input_path.write_text(''.join(key + '=' + shlex.quote(value) + '\n' for key, value in values.items()))
                    generated = subprocess.run([PERL, str(FORKY / 'scripts/late/network-generate.pl'),
                        '--input', str(input_path), '--target-templates', str(TARGET),
                        '--fragments', str(FORKY / 'scripts/late/templates/network')],
                        env=self.env, capture_output=True, text=True, timeout=5)
                    self.assertEqual(generated.returncode, 0, generated.stderr)
                    self.assertEqual(self.validate('--staged-only').returncode, 0)
                    content = self.staged.read_text()
                    self.assertIn('address 192.168.50.88\n', content)
                    self.assertIn('allow-hotplug eth0\n', content)
                    self.assertNotIn('iface wifi0 ', content)
                    native = prepared.read_text()
                    self.assertEqual(prepared.stat().st_mode & 0o777, 0o600)
                    self.assertIn('address1=192.168.50.89/24\n', native)
                    self.assertIn('address1=2001:db8::89/64\n', native)
                    self.assertIn('gateway=192.168.50.1\n', native)
                    self.assertIn('gateway=2001:db8::1\n', native)
                    self.assertEqual(native.count('route-metric=200\n'), 2)
                    self.assertIn('autoconnect=false\n', native)
                    self.assertIn('permissions=\n', native)
                    self.assertIn('dns=' + ('192.168.50.1;' if mode == 'link' else '') + '\n', native)
                    self.assertIn('dns=' + ('2001:db8::53;' if mode == 'link' else '') + '\n', native)
                    unmanaged = (self.root / 'etc/NetworkManager/conf.d/90-network-external.conf').read_text()
                    self.assertNotRegex(unmanaged, r'unmanaged-devices=[^\n]*wifi0')
                    self.assertIn('match-device=interface-name:wifi0\nmanaged=1', unmanaged)
                    self.assertFalse((self.root / 'etc/NetworkManager/system-connections/wifi.nmconnection').exists())
                    for original, replacement in (('192.168.50.89/24', '192.168.50.162/24'),
                                                   ('2001:db8::89/64', '2001:db8::162/64'),
                                                   ('autoconnect=false', 'autoconnect=true'),
                                                   ('route-metric=200', 'route-metric=50')):
                        prepared.write_text(native.replace(original, replacement))
                        self.assertNotEqual(self.validate('--staged-only').returncode, 0)
                    prepared.write_text(native)
        values['MANAGED_NETWORK_WIFI_CIDR'] = '192.168.51.1/24'
        input_path.write_text(''.join(key + '=' + shlex.quote(value) + '\n' for key, value in values.items()))
        result = subprocess.run([PERL, str(FORKY / 'scripts/late/network-generate.pl'),
            '--input', str(input_path), '--target-templates', str(TARGET),
            '--fragments', str(FORKY / 'scripts/late/templates/network')],
            env=self.env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside PRESEED_WIFI_CIDR', result.stderr)

    def test_wifi_ipv6_increment_carries_and_preserves_link_order(self):
        self.adapter()
        self.adapter('wlp2s0', mac='02:00:00:00:00:02', wireless=True)
        for name in ('enp1s0', 'wlp2s0'):
            (self.sysfs / name / 'device').mkdir()
        values = {'MANAGED_NETWORK_TARGET_ROOT': str(self.root),
                  'MANAGED_NETWORK_SYS_CLASS_NET': str(self.sysfs),
                  'MANAGED_NETWORK_IPV4_ADDRESS': '192.168.50.56',
                  'MANAGED_NETWORK_IPV4_NETMASK': '255.255.255.0',
                  'MANAGED_NETWORK_IPV4_GATEWAY': '192.168.50.1',
                  'MANAGED_NETWORK_IPV4_DNS': '192.168.50.1',
                  'MANAGED_NETWORK_IPV6_ENABLED': 'true',
                  'MANAGED_NETWORK_IPV6_GATEWAY': '2001:db8::1',
                  'MANAGED_NETWORK_IPV6_DNS': '2001:db8::53'}
        input_path = self.root / 'network-input.env'
        for order in ('ethernet wifi', 'wifi ethernet'):
            values['MANAGED_NETWORK_LINK_TYPES'] = order
            for ethernet, wifi in (('2001:db8::56/64', '2001:db8::57'),
                                    ('2001:db8::ff/64', '2001:db8::100'),
                                    ('2001:db8::ffff/64', '2001:db8::1:0'),
                                    ('2001:db8::7f/121', '')):
                with self.subTest(order=order, ethernet=ethernet):
                    values['MANAGED_NETWORK_IPV6_ADDRESS'] = ethernet
                    input_path.write_text(''.join(key + "='" + value + "'\n" for key, value in values.items()))
                    result = subprocess.run([PERL, str(FORKY / 'scripts/late/network-generate.pl'),
                        '--input', str(input_path), '--target-templates', str(TARGET),
                        '--fragments', str(FORKY / 'scripts/late/templates/network')],
                        env=self.env, capture_output=True, text=True, timeout=5)
                    if not wifi:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('leaves the Ethernet subnet', result.stderr)
                        continue
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.validate('--staged-only').returncode, 0)
                    content = self.staged.read_text()
                    self.assertIn('address 192.168.50.56\n', content)
                    native = (self.root / 'etc/network/wifi.nmconnection').read_text()
                    self.assertIn('address1=192.168.50.57/24\n', native)
                    self.assertIn('address1=' + wifi + '/64\n', native)
                    self.assertIn('route-metric=200\n', native)


class IntegrationTests(unittest.TestCase):
    def test_network_reader_failure_stops_handoff_before_boot_enablement(self):
        # Publisher/systemd commands are fixtures; the shell caller is real.
        script = r'''
. "$1"
DIR_NETWORK=/etc/network
DIR_NETWORK_INTERFACES_D=/etc/network/interfaces.d
FILE_NETWORK_INTERFACES=/etc/network/interfaces
FILE_MANAGED_NETWORK_INTERFACES=/etc/network/interfaces.d/50-network
FILE_MANAGED_NETWORK_DEFAULT=/etc/network/host.conf
FILE_MANAGED_NETWORK_HELPER=/usr/local/libexec/network-run
FILE_MANAGED_NETWORK_SERVICE=/etc/systemd/system/network.service
FILE_NETWORKMANAGER_MANAGED_UNMANAGED_CONF=/etc/NetworkManager/conf.d/10-managed.conf
install() { :; }
stage_target_networkmanager_dispatcher_activation_if_available() { :; }
target_managed_network_handoff_requested() { return 0; }
target_managed_network_mode() { printf '%s\n' static; }
target_managed_network_link_types() { printf '%s\n' ethernet; }
require_in_target() { :; }
test_in_target() { return 0; }
network_link_types_has() { return 1; }
remove_target_managed_network_handoff() { :; }
generate_target_managed_network_config() { :; }
stage_target_managed_network_perl_modules() { :; }
stage_target_asset() { :; }
installer_repo_join_var() { printf '%s/%s\n' "$1" "$2"; }
run_in_target() {
  [ "$1" = 'managed network policy validation' ] || exit 90
  shift
  printf '%s\n' "$@"
  [ "$VALIDATION_STATUS" = 0 ] || exit "$VALIDATION_STATUS"
}
stage_target_systemd_unit_enabled() { printf 'enabled=%s\n' "$1"; }
enable_target_networking_service_if_available() { :; }
installer_append_log_category() { :; }
install_target_managed_network_handoff
'''
        for status in ('0', '42'):
            with self.subTest(status=status):
                result = subprocess.run(['/bin/sh', '-eu', '-c', script, 'handoff-fixture',
                    str(FORKY / 'scripts/late/network.sh')], env={**os.environ, 'VALIDATION_STATUS': status},
                    capture_output=True, text=True, encoding='utf-8', timeout=5)
                self.assertEqual(result.returncode, int(status), result.stderr)
                self.assertEqual(result.stdout.splitlines()[:4],
                    ['/usr/bin/perl', '/usr/local/libexec/network-run', 'validate', '--staged-only'])
                self.assertEqual('enabled=network.service' in result.stdout, status == '0')

    def test_installer_stages_configured_wifi_as_ethernet_fallback(self):
        busybox = shutil.which('busybox')
        if not busybox:
            self.skipTest('packaged BusyBox required for installer shell coverage')
        script = r'''
. "$1"
target_static_network_selected() { return 0; }
target_wifi_static_config_requested() { [ "$CONFIGURED_WIFI" = true ]; }
installer_network_interface_for_handoff() {
  case "$1" in
    ethernet) [ "$ETHERNET_PRESENT" = true ] ;;
    wifi) [ "$WIFI_PRESENT" = true ] ;;
    *) return 1 ;;
  esac
}
installer_default_route_interface() { printf '%s\n' eth0; }
installer_global_ipv4_interface() { return 1; }
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
target_managed_network_link_types
'''
        for configured, ethernet, wifi, expected in (
                ('true', 'true', 'true', 'ethernet wifi'),
                ('false', 'true', 'true', 'ethernet'),
                ('true', 'true', 'false', 'ethernet'),
                ('true', 'false', 'true', 'wifi')):
            for shell in (['/bin/sh'], [busybox, 'sh']):
                with self.subTest(configured=configured, ethernet=ethernet, wifi=wifi, shell=shell):
                    result = subprocess.run([*shell, '-c', script, 'network-fallback-fixture',
                        str(FORKY / 'scripts/late/network.sh')], capture_output=True, text=True,
                        encoding='utf-8', timeout=5, env={**os.environ, 'CONFIGURED_WIFI': configured,
                        'ETHERNET_PRESENT': ethernet, 'WIFI_PRESENT': wifi})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_nvidia_event_activation_and_boot_service_replace_path(self):
        self.assertFalse(payload_source_exists(TARGET / 'etc/systemd/system/nvidia-char-links.path'))
        service = render_theme_defaults(payload_read_text(TARGET / 'etc/systemd/system/nvidia-char-links.service'))
        self.assertIn('StartLimitIntervalSec=30s', service)
        self.assertIn('StartLimitBurst=5', service)
        self.assertIn('WantedBy=multi-user.target', service)
        self.assertNotIn('StartLimitIntervalSec=0', service)
        rules = render_theme_defaults(payload_read_text(TARGET / 'etc/udev/rules.d/71-nvidia-char-links.rules'))
        self.assertEqual(rules.count('ENV{SYSTEMD_WANTS}+="nvidia-char-links.service"'), 2)
        for line in rules.splitlines():
            if line.startswith('ACTION='):
                self.assertIn('KERNEL=="nvidia', line)
                self.assertIn('TAG+="systemd"', line)
                self.assertIn('SYMLINK+="char/%M:%m"', line)
        firstboot = render_theme_defaults(payload_read_text(FORKY / 'scripts/firstboot/04-validation.sh'))
        self.assertNotIn('desktop-nvidia-char-link-path', firstboot)
        self.assertNotIn('desktop-nvidia-char-link-watcher', firstboot)
        self.assertIn('desktop-nvidia-char-link-boot-enabled', firstboot)

    def test_bootprofile_has_one_enablement_owner_and_remains_active(self):
        service = render_theme_defaults(payload_read_text(TARGET / 'etc/systemd/system/bootprofile-apply.service.tmpl'))
        self.assertIn('Type=oneshot\nRemainAfterExit=yes', service)
        grub = render_theme_defaults(payload_read_text(FORKY / 'scripts/late/grub.sh'))
        owner = grub.split('install_target_bootprofile_assets() {', 1)[1].split('\n}', 1)[0]
        self.assertEqual(owner.count('stage_target_systemd_unit_enabled'), 1)
        self.assertNotIn('ln -s', owner)
        self.assertNotIn('bootprofile-apply.service', render_theme_defaults(payload_read_text(FORKY / 'scripts/late/zram-swap.sh')))
        self.assertIn('dbus-broker', render_theme_defaults(payload_read_text(FORKY / 'scripts/late/dispatch.sh')))

    def test_pipewire_all_four_units_exclude_rendered_greeter(self):
        components = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))
        for unit in ('pipewire.socket', 'pipewire.service', 'pipewire-pulse.socket', 'pipewire-pulse.service'):
            text = render_theme_defaults(payload_read_text(TARGET / f'etc/systemd/user/{unit}.d/20-no-greeter.conf.tmpl'))
            rendered = text.replace('__INSTALLER_LABWC_GREETER_USER__', '_greetd')
            self.assertIn('[Unit]\n', rendered)
            self.assertIn('ConditionUser=!_greetd', rendered)
            self.assertNotIn('ConditionUser=\n', rendered)
            self.assertIn(unit, components)
        self.assertIn('desktop_stage_pipewire_user_conditions', components)
        self.assertIn('desktop-pipewire-greeter-conditions', render_theme_defaults(payload_read_text(FORKY / 'scripts/firstboot/04-validation.sh')))

    def test_network_unit_waits_for_configured_interfaces_only(self):
        unit = render_theme_defaults(payload_read_text(TARGET / 'etc/systemd/system/network.service'))
        self.assertNotIn('systemd-udev-settle', unit)
        self.assertIn('validate --wait-seconds 15', unit)
        self.assertIn('validate --wait-seconds 15 --allow-absent', unit)
        self.assertIn('TimeoutStartSec=20s', unit)

    def test_firstboot_uses_one_combined_apparmor_check(self):
        firstboot = render_theme_defaults(payload_read_text(FORKY / 'scripts/firstboot/04-validation.sh'))
        self.assertEqual(firstboot.count('apparmor-modes-run --check-loaded'), 1)
        self.assertNotRegex(firstboot, r'apparmor-modes-run --check(?:\s|$)')
        unit = render_theme_defaults(payload_read_text(TARGET / 'etc/systemd/system/apparmor-modes.service'))
        self.assertIn('SyslogIdentifier=apparmor-modes', unit)
        self.assertIn('ExecReload=/usr/local/libexec/apparmor-modes-run --force-reload', unit)
        self.assertIn('Before=systemd-user-sessions.service display-manager.service multi-user.target', unit)

    def test_grub_recordfail_all_managed_writers_use_500(self):
        grub = render_theme_defaults(payload_read_text(FORKY / 'scripts/late/grub.sh'))
        self.assertNotIn('GRUB_RECORDFAIL_TIMEOUT=-1', grub)
        self.assertEqual(grub.count('GRUB_RECORDFAIL_TIMEOUT=500'), 3)
        template = render_theme_defaults(payload_read_text(TARGET / 'etc/default/grub.d/05-bootprofiles.cfg.tmpl'))
        self.assertIn('GRUB_RECORDFAIL_TIMEOUT=500', template)
        self.assertNotIn('GRUB_RECORDFAIL_TIMEOUT=-1', template)

    def test_wayscriber_is_parseable_comprehensive_and_copied_to_account(self):
        rel = 'etc/skel-desktop/.config/wayscriber/config.toml'
        config = tomllib.loads(render_theme_defaults(payload_read_text(TARGET / rel)))
        self.assertEqual(config['config_revision'], 3)
        for section in ('drawing', 'arrow', 'spotlight', 'presets', 'performance', 'history', 'tablet',
                        'tray', 'updates', 'ui', 'presenter_mode', 'boards', 'render_profiles', 'session', 'capture', 'export', 'keybindings'):
            self.assertIn(section, config)
        self.assertFalse(config['ui']['input_hud']['enabled'])
        self.assertEqual(config['ui']['input_hud']['mode'], 'overlay')
        self.assertFalse(config['updates']['check'])
        self.assertEqual(config['ui']['toolbar']['backend'], 'auto')
        self.assertEqual(config['ui']['toolbar']['rebind_modifier'], 'ctrl_shift')
        self.assertEqual(config['presenter_mode']['toolbar_mode'], 'hidden')
        self.assertFalse(config['presenter_mode']['enable_input_hud'])
        self.assertEqual(len(config['drawing']['quick_colors']), 11)
        components = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))
        self.assertIn(f'desktop_stage_role_asset {rel} /{rel} 0644', components)
        self.assertIn('.config/wayscriber \\', components)
        for path in ('scripts/desktop/verify.sh', 'scripts/firstboot/04-validation.sh'):
            self.assertIn('.config/wayscriber/config.toml', render_theme_defaults(payload_read_text(FORKY / path)))


class WiFiAuthenticationTests(unittest.TestCase):
    def setUp(self):
        path = TARGET / 'usr/local/libexec/network-wifi-configure'
        self.module = types.ModuleType('wifi_authentication_fixture')
        self.module.__file__ = str(path)
        exec(compile(payload_read_bytes(path), str(path), 'exec'), self.module.__dict__)

    def test_connection_rejects_ipv6_policy_drift_before_prompt_or_commands(self):
        for ethernet, wifi in (('2001:db8::56/64', '2001:db8::58/64'),
                                ('2001:db8::56/64', '2001:db8::57/63'),
                                ('2001:db8::7f/121', '2001:db8::80/121')):
            policy = {'MANAGED_NETWORK_MODE': 'static', 'MANAGED_NETWORK_LINK_TYPES': 'ethernet wifi',
                      'MANAGED_NETWORK_WIFI_IFACE': 'wifi0',
                      'MANAGED_NETWORK_ETHERNET_IPV4_CIDR': '192.168.50.56/24',
                      'MANAGED_NETWORK_WIFI_IPV4_CIDR': '192.168.50.57/24',
                      'MANAGED_NETWORK_IPV6_ENABLED': 'true',
                      'MANAGED_NETWORK_ETHERNET_IPV6_CIDR': ethernet,
                      'MANAGED_NETWORK_WIFI_IPV6_CIDR': wifi}
            content = ''.join(key + "='" + value + "'\n" for key, value in policy.items())
            with self.subTest(ethernet=ethernet, wifi=wifi), \
                    mock.patch.object(self.module, 'read_owned', return_value=content) as read, \
                    mock.patch.object(self.module, 'run') as commands, \
                    mock.patch('builtins.input') as prompt, \
                    self.assertRaisesRegex(self.module.ConfigurationError, 'Ethernet IPv6 \\+1'):
                self.module.configure('wifi0')
            read.assert_called_once_with(self.module.POLICY)
            commands.assert_not_called()
            prompt.assert_not_called()



    def test_firstboot_saves_known_ssid_without_scanning_or_resetting_radio(self):
        for ssid in ('', 'Fixture Wi-Fi'):
            policy = {'MANAGED_NETWORK_LINK_TYPES': 'ethernet wifi',
                      'MANAGED_NETWORK_WIFI_IFACE': 'wifi0', 'MANAGED_NETWORK_WIFI_ESSID': ssid}
            content = ''.join(key + '=' + shlex.quote(value) + '\n' for key, value in policy.items())
            with self.subTest(configured=bool(ssid)), \
                    mock.patch.object(self.module, 'read_owned', return_value=content), \
                    mock.patch.object(self.module, 'wifi_policy', return_value=policy), \
                    mock.patch.object(self.module, 'validate_profile'), \
                    mock.patch.object(self.module, 'publish_profile') as profiles, \
                    mock.patch.object(self.module, 'publish') as state, \
                    mock.patch.object(self.module, 'run') as commands, \
                    mock.patch.object(self.module.Path, 'exists', return_value=False), \
                    mock.patch.object(self.module.Path, 'is_symlink', return_value=False), \
                    mock.patch.object(self.module.Path, 'mkdir'):
                self.module.firstboot()
            self.assertEqual(profiles.call_count, int(bool(ssid)))
            commands.assert_not_called()
            self.assertIn('prepared-persistent' if ssid else 'skipped-missing', state.call_args.args[1])

    def test_firstboot_never_overwrites_an_existing_desktop_connection(self):
        policy = {'MANAGED_NETWORK_LINK_TYPES': 'wifi', 'MANAGED_NETWORK_WIFI_IFACE': 'wifi0'}
        with mock.patch.object(self.module, 'parse_policy', return_value=policy), \
                mock.patch.object(self.module, 'read_owned'), \
                mock.patch.object(self.module, 'wifi_policy', return_value=policy), \
                mock.patch.object(self.module, 'validate_profile'), \
                mock.patch.object(self.module, 'publish_profile') as profiles, \
                mock.patch.object(self.module, 'publish') as state, \
                mock.patch.object(self.module.Path, 'exists', return_value=True), \
                mock.patch.object(self.module.Path, 'mkdir'):
            self.module.firstboot()
        profiles.assert_not_called()
        self.assertIn('preserved-existing', state.call_args.args[1])

    def test_profile_overrides_win_and_empty_values_use_private_input(self):
        text = payload_read_text(FORKY / 'scripts/late/network.sh')
        start = text.index('target_wifi_setting() {')
        helper = text[start:text.index('\n}\n', start) + 2]
        for key, override in [('wifi_interface', 'WIFI_INTERFACE'), ('wifi_essid', 'WIFI_ESSID'),
                              ('wifi_security', 'WIFI_SECURITY'), ('wifi_cidr', 'WIFI_CIDR'),
                              ('wifi_wpa', 'WIFI_PASSPHRASE')]:
            for value, expected in [('', 'private-value'), ('profile-value', 'profile-value')]:
                with self.subTest(key=key, value=value):
                    script = helper + '\ninstaller_preseed_env_value() { printf "%s\\n" private-value; }\n'
                    script += override + '=' + shlex.quote(value) + '\n'
                    script += 'target_wifi_setting ' + shlex.quote(key) + '\n'
                    result = subprocess.run(['/bin/sh', '-eu', '-c', script],
                        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
                        capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected + '\n')





    def test_configuration_validates_policy_before_prompting_or_running_commands(self):
        values = "MANAGED_NETWORK_MODE='static'\nMANAGED_NETWORK_LINK_TYPES='ethernet wifi'\n"
        values += "MANAGED_NETWORK_WIFI_IFACE='wifi0'\nMANAGED_NETWORK_WIFI_IPV4_CIDR='192.168.50.162/24'\n"
        values += "MANAGED_NETWORK_ETHERNET_IPV4_CIDR='192.168.50.88/24'\n"
        with mock.patch.object(self.module, 'read_owned', return_value=values), \
             mock.patch.object(self.module, 'run') as run, mock.patch('builtins.input') as prompt:
            with self.assertRaisesRegex(ValueError, 'Ethernet IPv4'):
                self.module.configure('wifi0')
            run.assert_not_called()
            prompt.assert_not_called()


class LauncherObservabilityTests(unittest.TestCase):
    def test_code_current_url_handler_resolves_without_cli_fallback(self):
        path = TARGET / 'usr/local/bin/labwc-sync-application-launchers'
        module = types.ModuleType('launcher_code_url_handler_test')
        module.__file__ = str(path)
        exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
        config = next(c for c in module.APP_CONFIG
                      if c['action_app'] == 'code' and c.get('no_display'))
        desktop_id = 'com.microsoft.VSCode.UrlHandler.desktop'
        expected = module.SYSTEM_APPLICATION_DIR + '/' + desktop_id
        def lookup(candidate):
            if candidate == expected:
                return object()
            raise FileNotFoundError(candidate)
        with mock.patch.object(module.os, 'lstat', side_effect=lookup), \
                mock.patch.object(module, 'read_system_desktop_text', return_value='vendor URL entry') as read, \
                mock.patch.object(module, 'code_runtime_available', side_effect=AssertionError('unexpected CLI fallback')):
            self.assertEqual(module.desktop_source(config), (desktop_id, 'vendor URL entry'))
        read.assert_called_once_with(expected)

    def test_code_untrusted_url_handler_does_not_fall_back_to_another_alias(self):
        path = TARGET / 'usr/local/bin/labwc-sync-application-launchers'
        module = types.ModuleType('launcher_code_url_handler_rejection_test')
        module.__file__ = str(path)
        exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
        config = next(c for c in module.APP_CONFIG
                      if c['action_app'] == 'code' and c.get('no_display'))
        with mock.patch.object(module.os, 'lstat', return_value=object()), \
                mock.patch.object(module, 'read_system_desktop_text', side_effect=RuntimeError('untrusted owner')) as read, \
                mock.patch.object(module, 'code_runtime_available') as fallback:
            with self.assertRaisesRegex(RuntimeError, 'untrusted owner'):
                module.desktop_source(config)
        read.assert_called_once_with(module.LOCAL_APPLICATION_DIR + '/code-url-handler.desktop')
        fallback.assert_not_called()

    def test_absent_optional_apps_are_named_without_failing(self):
        path = TARGET / 'usr/local/bin/labwc-sync-application-launchers'
        module = types.ModuleType('launcher_boot_runtime_test')
        module.__file__ = str(path)
        exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
        selected = [c for c in module.APP_CONFIG if c['action_app'] in ('postman', 'sleek')]
        out, err = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(module, 'APP_CONFIG', selected))
            stack.enter_context(mock.patch.object(module.sys, 'argv', [str(path), 'desktop', '/home/desktop']))
            for name, value in {'validate_account_context': (1000, 1000), 'load_acceleration_availability': {},
                                'ensure_user_directory': None, 'acquire_lock': None, 'find_desktop_file': None,
                                'remove_unmanaged_tuta_launchers': 0, 'synchronize_bitwarden_autostart': False}.items():
                stack.enter_context(mock.patch.object(module, name, return_value=value))
            stack.enter_context(mock.patch.object(module.os, 'umask'))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            self.assertEqual(module.main(), 0)
        self.assertIn('processed=0 skipped_missing=2 missing=postman,sleek', out.getvalue())
        self.assertEqual(err.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
