#!/usr/bin/env python3
"""Scoped boot/runtime regression tests. No package builds or kernel writes.

Perl tests normally use the installed Moo dependencies. In stripped-down test
containers a deliberately small test-only constructor adapter may be enabled by
MANAGED_TEST_PERL_ADAPTER=1. This exercises application control flow, not Moo's
integration or type system; it never enters the installer payload. AppArmor
commands and loaded-kernel state are always fixtures, never the real kernel.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes

from contextlib import ExitStack, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import re
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
labels = re.findall(r'^profile\s+([A-Za-z0-9_./-]+)', source, re.M)
kernel = pathlib.Path(os.environ['AA_TEST_KERNEL'])
if name == 'apparmor_parser' and '-N' in args:
    # The real parser honors disable/ even for names-only inspection.
    base = pathlib.Path(args[args.index('--base') + 1])
    if (base / 'disable' / path.name).is_symlink():
        raise SystemExit(0)
    print(''.join(label + '\n' for label in labels), end='')
    raise SystemExit(0)
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
        mode = 'complain' if 'complain' in source else 'enforce'
        lines += [f'{label} ({mode})' for label in labels]
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
            p.write_text("package Types::Standard; use Exporter 'import'; our @EXPORT_OK=qw(Str Int ArrayRef); sub Str { 1 } sub Int { 1 } sub ArrayRef { 1 } 1;\n")
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
        return [call for call in self.tool_calls() if '-N' not in call and '--help' not in call]

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

    def test_source_drift_changes_only_mismatching_profile_and_is_idempotent(self):
        self.profile(source='enforce', loaded='enforce')
        unchanged = self.profile('beta')
        before = payload_source_stat(unchanged).st_ino
        result = self.run_policy()
        self.assert_success(result)
        self.assertEqual([c[0] for c in self.mutations()], ['aa-complain', 'aa-audit'])
        self.assertEqual(payload_source_stat(unchanged).st_ino, before)
        self.assertIn('flags=(complain)', render_theme_defaults(payload_read_text(self.profiles / 'alpha')))
        self.calls.unlink()
        self.assert_success(self.run_policy())
        self.assertEqual(self.mutations(), [])

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
        self.profile()
        self.kernel.unlink()
        self.assert_success(self.run_policy('--no-reload'))
        self.assertEqual(self.mutations(), [])

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
        self.assertEqual([c[0] for c in self.mutations()], ['aa-complain', 'aa-audit'])
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

    def test_child_modes_remain_confined_without_forcing_parent_mode(self):
        p = self.profile()
        with p.open('a') as fh:
            fh.write('profile alpha//child {\n}\n')
        with self.kernel.open('a') as fh:
            fh.write('alpha//child (enforce)\n')
        self.assert_success(self.run_policy())
        self.assertEqual(self.mutations(), [])
        self.kernel.write_text('alpha (complain)\nalpha//child (unconfined)\n')
        self.assertNotEqual(self.run_policy('--check-loaded').returncode, 0)

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


class NetworkReadinessTests(PerlFixture):
    def setUp(self):
        super().setUp()
        self.sysfs = self.root / 'net'
        self.sysfs.mkdir()
        (self.root / 'etc/default').mkdir(parents=True)
        (self.root / 'etc/network/interfaces.d').mkdir(parents=True)
        self.config = self.root / 'etc/network/host.conf'
        self.config.write_text("""MANAGED_NETWORK_MODE=static
MANAGED_NETWORK_LINK_TYPES=ethernet
MANAGED_NETWORK_ETHERNET_IFACE=enp1s0
MANAGED_NETWORK_ETHERNET_MAC=02:00:00:00:00:01
MANAGED_NETWORK_ETHERNET_IPV4_CIDR=192.0.2.2/24
MANAGED_NETWORK_IPV4_GATEWAY=192.0.2.1
MANAGED_NETWORK_IPV6_ENABLED=false
""")
        self.config.chmod(0o600)
        (self.root / 'etc/network/interfaces').write_text('source /etc/network/interfaces.d/*\n')
        self.staged = self.root / 'etc/network/interfaces.d/50-network'
        self.staged.write_text('iface enp1s0 inet static\n')
        self.staged.chmod(0o600)
        self.env.update(MANAGED_TARGET_ROOT=str(self.root), MANAGED_SYS_CLASS_NET=str(self.sysfs), SYSTEMD_LOG_LEVEL='info')

    def adapter(self, name='enp1s0', mac='02:00:00:00:00:01', type_='1', wireless=False):
        p = self.sysfs / name
        p.mkdir(exist_ok=True)
        (p / 'address').write_text(mac + '\n')
        (p / 'type').write_text(type_ + '\n')
        if wireless:
            (p / 'wireless').mkdir(exist_ok=True)

    def validate(self, *args):
        return subprocess.run(payload_installed_argv([PERL, str(TARGET / 'usr/local/libexec/network-run'), 'validate', *args]),
            env=self.env, capture_output=True, text=True, timeout=5)

    def test_present_adapter_does_not_wait_for_other_devices(self):
        self.adapter()
        result = self.validate('--wait-seconds', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('waiting for managed', result.stderr)

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

    def test_both_adapters_share_one_deadline(self):
        with self.config.open('a') as fh:
            fh.write("MANAGED_NETWORK_LINK_TYPES='ethernet wifi'\nMANAGED_NETWORK_WIFI_IFACE=wlan0\n")
        with self.staged.open('a') as fh:
            fh.write('iface wlan0 inet static\n')
        start = time.monotonic()
        result = self.validate('--wait-seconds', '1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('enp1s0,wlan0', result.stderr)
        self.assertLess(time.monotonic() - start, 2)


class IntegrationTests(unittest.TestCase):
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
        self.assertIn('TimeoutStartSec=20s', unit)

    def test_firstboot_uses_one_combined_apparmor_check(self):
        firstboot = render_theme_defaults(payload_read_text(FORKY / 'scripts/firstboot/04-validation.sh'))
        self.assertEqual(firstboot.count('apparmor-modes-run --check-loaded'), 1)
        self.assertNotRegex(firstboot, r'apparmor-modes-run --check(?:\s|$)')
        unit = render_theme_defaults(payload_read_text(TARGET / 'etc/systemd/system/apparmor-modes.service'))
        self.assertIn('SyslogIdentifier=apparmor-modes', unit)
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


class LauncherObservabilityTests(unittest.TestCase):
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
