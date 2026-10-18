"""Regression tests for the four requested repairs.

GRUB/checker, Btrfs and Wayland boundaries use named, disposable fixtures. Real
Moo integration is dependency-gated. MANAGED_TEST_PERL_ADAPTER=1 explicitly
selects the existing constructor-only adapter for core Perl behavior tests; it
is not production Moo validation and never enters the installer payload.
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

from payload_fixture import waybar_config_text
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import configparser
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

import test_boot_runtime_20260913 as runtime
import test_hardware_restore as hardware

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
LIB = TARGET / 'usr/local/lib/perl5/site_perl'


class DesktopRepairTests(unittest.TestCase):
    def test_both_bars_launch_after_button_release_in_bounded_singleton_service(self):
        text = render_theme_defaults(waybar_config_text(TARGET / 'etc/skel-desktop/.config/waybar'))
        blocks = re.findall(r'"custom/window-switcher": \{(.*?)\n  \}', text, re.S)
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertNotIn('"on-click":', block)
            command = re.search(r'"on-click-release": "([^"]+)"', block)[1]
            argv = shlex.split(command)
            self.assertEqual(argv[0], '/usr/bin/systemd-run')
            for arg in ('--no-block', '--collect', '--unit=labwc-window-switcher',
                        '--property=RuntimeMaxSec=3s', '--property=TimeoutStartSec=3s',
                        '--property=TimeoutStopSec=1s', '--property=KillMode=control-group',
                        '--property=PartOf=labwc-session.target', '--property=StandardInput=null',
                        '--property=StandardOutput=null', '--property=StandardError=journal'):
                self.assertIn(arg, argv)
            self.assertNotIn('--wait', argv)
            self.assertNotIn('--scope', argv)

    def test_icons_use_centered_symbolic_images_independent_of_font_metrics(self):
        from waybar_fixture import style
        css = style(FORKY / 'hosts/profiles/btrfs-de.env', 'external')
        text = render_theme_defaults(waybar_config_text(TARGET / 'etc/skel-desktop/.config/waybar'))
        for name in ('wayscriber', 'apps'):
            blocks = re.findall(r'"custom/' + name + r'": \{(.*?)\n  \}', text, re.S)
            self.assertEqual(len(blocks), 2)
            for block in blocks:
                self.assertIn('"format": " "', block)
                self.assertIn('"align": 0.5', block)
                self.assertIn('"justify": "center"', block)
            block = ''.join(re.findall(r'(?:^|\n)#custom-' + name + r' \{(.*?)\}', css, re.S))
            self.assertIn(f'background-image: -gtk-recolor(url("icons/{name}-symbolic.svg"));', block)
            geometry = ''.join(body for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css)
                               if f'window#waybar.external #custom-{name}' in
                               {selector.strip() for selector in selectors.split(',')})
            self.assertIn('padding: 0px 7px;', geometry)
            icon = TARGET / f'etc/skel-desktop/.config/waybar/icons/{name}-symbolic.svg'
            self.assertEqual(ET.fromstring(render_theme_defaults(payload_read_text(icon))).attrib['viewBox'], '0 0 24 24')
            stage = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))
            self.assertIn('  desktop_stage_waybar_theme_icons', stage)
            self.assertIn('WAYBAR_BUTTON_' + name.upper() + '_NORMAL_ICON_PATH', stage)
            self.assertRegex(css, rf'#custom-{name}:hover \{{[^}}]*background-image: -gtk-recolor')
        self.assertIn('background-position: center;', css)
        self.assertIn('background-size: 18px 18px, 100% 100%;', css)

    @unittest.skipUnless(os.geteuid() == 0, 'root can create a disposable unprivileged process')
    def test_real_timeout_wrapper_emits_exact_same_device_key_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); root.chmod(0o755)
            wtype = root / 'wtype'
            wtype.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            wtype.chmod(0o755)
            wrapper = root / 'switcher'
            wrapper.write_text(render_theme_defaults(payload_read_text(TARGET / 'usr/local/bin/labwc-window-switcher')).replace(
                '/usr/bin/wtype', str(wtype)))
            wrapper.chmod(0o755)
            def drop():
                os.setgroups([]); os.setgid(65534); os.setuid(65534)
            result = subprocess.run(payload_installed_argv(['/bin/sh', str(wrapper)]), preexec_fn=drop,
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['-P', 'F13', '-p', 'F13'])
            result = subprocess.run(payload_installed_argv(['/bin/sh', str(wrapper), 'arbitrary-key']),
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            result = subprocess.run(payload_installed_argv(['/bin/sh', str(wrapper)]), text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    @unittest.skipUnless(os.geteuid() == 0, 'root can create a disposable unprivileged process')
    def test_stalled_key_injector_is_terminated_not_left_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); root.chmod(0o755)
            wtype = root / 'wtype'
            wtype.write_text('#!/usr/bin/python3 -I\nimport signal,time\n'
                             'signal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n')
            wtype.chmod(0o755)
            wrapper = root / 'switcher'
            wrapper.write_text(render_theme_defaults(payload_read_text(TARGET / 'usr/local/bin/labwc-window-switcher')).replace(
                '/usr/bin/wtype', str(wtype)))
            wrapper.chmod(0o755)
            def drop():
                os.setgroups([]); os.setgid(65534); os.setuid(65534)
            start = time.monotonic()
            result = subprocess.run(payload_installed_argv(['/bin/sh', str(wrapper)]), preexec_fn=drop,
                                    capture_output=True, timeout=5)
            self.assertIn(result.returncode, (-9, 137))
            self.assertLess(time.monotonic() - start, 4.5)

    def test_firstboot_permission_matches_root_read_of_user_owned_directory_only(self):
        text = payload_read_text(FORKY / 'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl')
        profile = re.search(r'^profile firstboot .*?^}', text, re.M | re.S)[0]
        self.assertIn('  @{HOME}/.config/systemd/user/ r,', profile)
        self.assertNotIn('owner @{HOME}/.config/systemd/user/', profile)
        self.assertNotIn('@{HOME}/.config/systemd/user/**', profile)


class TimeshiftStagingTests(unittest.TestCase):
    @staticmethod
    def function(source, name):
        start = source.index(name + '() {\n')
        return source[start:source.index('\n}\n', start) + 3]

    @unittest.skipUnless(os.geteuid() == 0, 'module ownership requires disposable fixture root')
    def test_failed_publication_cannot_reuse_an_older_valid_module(self):
        source = (FORKY / 'scripts/late/btrfs-family.sh').read_text()
        functions = '\n'.join(self.function(source, name) for name in (
            'timeshift_managed_perl_modules', 'btrfs_stage_timeshift_managed_perl_modules'))
        lifecycle = (FORKY / 'scripts/common/lifecycle.sh').read_text()
        start = lifecycle.index('installer_metadata_value() (\n')
        metadata = lifecycle[start:lifecycle.index('\n);\n', start) + 4]
        with tempfile.TemporaryDirectory(prefix='timeshift-stage-') as temporary:
            root = Path(temporary)
            stale = root / 'target/usr/local/lib/perl5/site_perl/timeshift/TimeshiftManaged/Command.pm'
            stale.parent.mkdir(parents=True)
            stale.write_text('previous valid publication\n'); stale.chmod(0o644)
            script = metadata + functions + r'''
target_asset_host_path() { printf '%s%s\n' "$INSTALLER_TARGET_DIR" "$1"; }
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
target_asset_assert_no_unresolved_installer_placeholders() { return 0; }
btrfs_stage_shared_target_asset() {
  printf '%s\n' "$1" >>"$TRACE"
  case "$1" in */Command.pm) return 73 ;; esac
  destination=$INSTALLER_TARGET_DIR$2
  mkdir -p "${destination%/*}" || return 1
  printf '%s\n' 'new fixture publication' >"$destination" || return 1
  chmod "$3" "$destination"
}
if btrfs_stage_timeshift_managed_perl_modules; then exit 0; else exit $?; fi
'''
            trace = root / 'trace'
            result = subprocess.run(['/bin/sh', '-eu', '-c', script],
                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': temporary,
                     'INSTALLER_TARGET_DIR': str(root / 'target'), 'TRACE': str(trace)},
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 73, result.stderr)
            self.assertEqual(stale.read_text(), 'previous valid publication\n')
            self.assertEqual([Path(line).name for line in trace.read_text().splitlines()],
                             ['CLI.pm', 'Command.pm'])

    def test_configuration_stops_at_each_failed_boundary_before_later_work(self):
        source = (FORKY / 'scripts/late/btrfs-family.sh').read_text()
        configure = self.function(source, 'configure_target_timeshift')
        stubs = r'''
checkpoint() { printf '%s\n' "$1" >>"$TRACE"; [ "$1" != "$FAIL_POINT" ] || return 73; }
target_has_btrfs_filesystems() { return 0; }
fatal() { exit 99; }
configure_target_timeshift_btrfs_layout() { checkpoint layout; }
btrfs_render_shared_target_asset_with_placeholder_map() { checkpoint render; }
btrfs_stage_timeshift_managed_perl_modules() { checkpoint modules; }
btrfs_stage_shared_target_asset() { checkpoint "asset:$1"; }
stage_target_systemd_unit_enabled() { checkpoint "enable:$1"; }
'''
        points = ('', 'layout', 'render', 'modules',
                  'asset:etc/systemd/system/timeshift-weekly.timer',
                  'enable:timeshift-weekly.timer')
        for point in points:
            with self.subTest(failure=point), tempfile.TemporaryDirectory(prefix='timeshift-config-') as temporary:
                root = Path(temporary); trace = root / 'trace'
                env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': temporary,
                       'TRACE': str(trace), 'FAIL_POINT': point, 'TIMESHIFT_ADDON_SELECTED': 'true'}
                for name in re.findall(r'\$\{(FILE_[A-Z0-9_]+)\}', configure):
                    env[name] = str(root / name)
                script = stubs + configure + '\nif configure_target_timeshift; then exit 0; else exit $?; fi\n'
                result = subprocess.run(['/bin/sh', '-eu', '-c', script], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 73 if point else 0, result.stderr)
                steps = trace.read_text().splitlines()
                if point:
                    self.assertEqual(steps[-1], point)
                    if not point.startswith('enable:'):
                        self.assertFalse(any(step.startswith('enable:') for step in steps))
                else:
                    self.assertEqual(sum(step.startswith('enable:') for step in steps), 5)


class RefreshUnitTests(unittest.TestCase):
    def unit(self, name):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(TARGET / 'etc/systemd/system' / name)
        return parser

    def test_edge_trigger_cannot_continuously_retrigger_on_existence(self):
        path = self.unit('grub-btrfs-refresh.path')['Path']
        self.assertEqual(path['PathChanged'], '/run/timeshift')
        self.assertNotIn('PathExistsGlob', path)
        self.assertNotIn('DirectoryNotEmpty', path)

    def test_periodic_reconciliation_and_completed_snapshot_jobs_are_staged(self):
        timer = self.unit('grub-btrfs-refresh.timer')['Timer']
        self.assertEqual(timer['OnBootSec'], '2min')
        self.assertEqual(timer['OnUnitInactiveSec'], '15min')
        self.assertEqual(timer['Unit'], 'grub-btrfs-refresh.service')
        for kind in ('daily', 'weekly', 'monthly'):
            job = self.unit('timeshift-' + kind + '.service')['Service']
            self.assertEqual(job['ExecStopPost'], '/usr/bin/systemctl --no-block start grub-btrfs-refresh.service')
            self.assertNotIn('ExecStartPost', job)
            self.assertEqual(job['TimeoutStopSec'], '30s')
            self.assertEqual(job['KillMode'], 'control-group')
        stage = render_theme_defaults(payload_read_text(FORKY / 'scripts/late/btrfs-family.sh'))
        self.assertIn('etc/systemd/system/grub-btrfs-refresh.timer /etc/systemd/system/grub-btrfs-refresh.timer 0644', stage)
        self.assertIn('grub-btrfs-refresh.path \\\n    grub-btrfs-refresh.timer', stage)

    def test_refresh_does_not_wait_for_an_open_gui_and_has_finite_cgroup_lifetime(self):
        unit = self.unit('grub-btrfs-refresh.service')['Service']
        self.assertEqual(unit['ExecStart'], '/usr/local/libexec/grub-btrfs-refresh')
        self.assertEqual(unit['TimeoutStartSec'], '3m')
        self.assertEqual(unit['TimeoutStopSec'], '15s')
        self.assertEqual(unit['KillMode'], 'control-group')
        self.assertEqual(unit['PrivateMounts'], 'yes')
        self.assertEqual(unit['UMask'], '0077')


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('busybox') and shutil.which('chroot'),
                     'root and BusyBox chroot required')
class CustomGrubRepairTests(unittest.TestCase):
    setUp = hardware.GrubGeneratorTests.setUp
    invoke = hardware.GrubGeneratorTests.invoke

    def test_effective_snapshot_export_matches_hardware_policy_without_writes(self):
        result = self.invoke(install=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = {str(p.relative_to(self.root)): render_theme_bytes(payload_read_bytes(p)) for p in self.root.rglob('*') if payload_source_is_file(p)}
        result = subprocess.run(payload_installed_argv([shutil.which('chroot'), str(self.root), '/generator', '--snapshot-config']),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('grub_hardware_flags=', result.stdout)
        for flag in ('vfio-pci.ids=8086:02e0', 'nvidia-drm.modeset=1', 'iommu.strict=1'):
            self.assertIn(flag, result.stdout)
        after = {str(p.relative_to(self.root)): render_theme_bytes(payload_read_bytes(p)) for p in self.root.rglob('*') if payload_source_is_file(p)}
        self.assertEqual(before, after)
        self.assertNotIn('vfio-pci.ids', render_theme_defaults(payload_read_text(self.root / 'etc/default/grub-profiles')))

    def test_checker_failure_preserves_last_good_menu_and_cleans_private_temp(self):
        output = self.root / 'boot/grub/custom.cfg'
        output.write_text('last-good-menu\n')
        (self.root / 'bin/grub-script-check').write_text('#!/bin/sh\nexit 19\n')
        result = self.invoke(install=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed syntax validation', result.stderr)
        self.assertEqual(render_theme_defaults(payload_read_text(output)), 'last-good-menu\n')
        self.assertEqual(list(output.parent.glob('.custom.cfg.*')), [])

    def test_missing_checker_is_not_treated_as_success(self):
        (self.root / 'bin/grub-script-check').unlink()
        result = self.invoke(install=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('grub-script-check is unavailable', result.stderr)
        self.assertFalse(payload_source_exists(self.root / 'boot/grub/custom.cfg'))

    def test_unsafe_flags_are_rejected_before_any_config_publication(self):
        self.args[6] = 'rootfstype=btrfs; reboot'
        result = self.invoke(install=True)
        self.assertNotEqual(result.returncode, 0)
        # The staged input exists; invalid flags must not publish a menu.
        self.assertFalse(payload_source_exists(self.root / 'boot/grub/custom.cfg'))

    def test_user_writable_sourced_config_is_rejected(self):
        self.assertEqual(self.invoke(install=True).returncode, 0)
        (self.root / 'etc/default/grub-profiles').chmod(0o666)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('writable by non-root', result.stderr)

    def test_snapshot_submenu_has_a_missing_menu_guard(self):
        (self.root / 'etc/default/grub-btrfs').mkdir()
        (self.root / 'etc/default/grub-btrfs/config').touch()
        self.assertEqual(self.invoke(install=True).returncode, 0)
        text = render_theme_defaults(payload_read_text(self.root / 'boot/grub/custom.cfg'))
        self.assertIn('if [ -f "${prefix}/grub-btrfs.cfg" ]; then', text)


class TimeshiftPerlRepairTests(runtime.PerlFixture):
    def setUp(self):
        super().setUp()
        self.env['PERL5LIB'] = ':'.join(filter(None, [self.env.get('PERL5LIB'),
            str(LIB / 'timeshift'), str(LIB / 'runtime')]))
        self.env['FIXTURE_ROOT'] = str(self.root)
        checker = self.root / 'checker'
        checker.write_text('#!/bin/sh\n[ -s "$1" ]\n'); checker.chmod(0o755)
        self.env['FIXTURE_CHECKER'] = str(checker)

    def perl(self, body):
        preamble = r'''
use strict; use warnings;
use JSON::PP qw(encode_json decode_json);
use File::Path qw(make_path);
use Fcntl qw(:mode);
use TimeshiftManaged::GrubRefresh;
use TimeshiftManaged::Snapshot;
use TimeshiftManaged::Config;
{ package FixtureLog; sub new { bless {}, shift } sub info {} sub warning {} sub error {} }
{ package FixtureCommand;
  our @ISA = ('TimeshiftManaged::Command');
  sub find_executable {
    return $ENV{FIXTURE_CHECKER} || undef if $_[1] eq 'grub-script-check';
    return $_[0]->SUPER::find_executable($_[1]);
  }
}
my $root = $ENV{FIXTURE_ROOT};
my $logger = FixtureLog->new();
my $command = bless {}, 'FixtureCommand';
my $g = TimeshiftManaged::GrubRefresh->new(logger=>$logger, command=>$command,
    output_file=>"$root/menu.cfg", lock_file=>"$root/locks/menu.lock",
    snapshot_lock_file=>"$root/locks/snapshot.lock");
sub write_file { my ($path,$data)=@_; open my $f,'>',$path or die $!; print {$f} $data; close $f or die $!; }
sub assert { die $_[1] unless $_[0]; }
'''
        result = subprocess.run(payload_installed_argv([runtime.PERL, '-e', preamble + '\n' + body]),
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def test_all_runtime_modules_load_with_selected_dependency_mode(self):
        self.perl("use TimeshiftManaged::CLI; assert(TimeshiftManaged::CLI->new(program=>'grub-btrfs-refresh')->run('--help') == 0, 'CLI load');")

    def test_missing_keys_remain_missing_and_duplicates_fail(self):
        self.perl(r'''
my $c=TimeshiftManaged::Config->new(path=>"$root/config",allowed_keys=>['A','B']);
my $v=$c->parse_content("A='value'\n");
assert($v->{A} eq 'value' && !exists($v->{B}), 'missing key lost its default');
assert(!eval {$c->parse_content("A=one\nA=two\n");1}, 'accepted duplicate');
assert(!eval {$c->parse_content("A='unterminated\n");1}, 'accepted unterminated value');
''')

    def test_configuration_rejects_symlink_fifo_oversize_and_writable_inputs(self):
        self.perl(r'''
my $path="$root/config";
my $c=TimeshiftManaged::Config->new(path=>$path,allowed_keys=>['A'],maximum_bytes=>32);
write_file($path,"A=ok\n"); chmod 0600,$path;
assert($c->load()->{A} eq 'ok','valid config');
chmod 0666,$path; assert(!eval {$c->load();1},'accepted writable config');
unlink $path; symlink "$root/missing",$path; assert(!eval {$c->load();1},'accepted symlink');
unlink $path; require POSIX; POSIX::mkfifo($path,0600)==0 or die $!;
assert(!eval {$c->load();1},'accepted FIFO'); unlink $path;
write_file($path,'A=' . ('x' x 40)); assert(!eval {$c->load();1},'accepted oversized file');
''')

    def test_rootflags_replace_all_subvolume_selectors_without_prefix_corruption(self):
        self.perl(r'''
for my $input ('rootfstype=btrfs rootflags=subvol=@,compress=zstd:1',
               'rootfstype=btrfs rootflags=compress=zstd:1,subvolid=256',
               'rootfstype=btrfs rootflags=subvol=@home rootflags=subvolid=256,compress=zstd:1') {
 my $flags=$g->_snapshot_root_flags($input,'timeshift-btrfs/snapshots','2026-09-20_12-00-00','@');
 my @selectors=$flags =~ /rootflags=/g;
 assert(@selectors==1,'duplicate rootflags');
 assert($flags =~ m{rootflags=subvol=timeshift-btrfs/snapshots/2026-09-20_12-00-00/@,compress=zstd:1},$flags);
 assert($flags !~ /subvolid=|\@home/,'old selector');
}
assert(!eval {$g->_snapshot_root_flags('ro; reboot','snap','2026-09-20_12-00-00','@');1},'GRUB injection');
for my $bad ('a/../b','a/./b','/absolute','a//b') {
 assert(!eval {$g->_validate_relative_subvolume_path('path',$bad);1},'unsafe path');
}
''')

    def test_lock_does_not_change_parent_mode_and_rejects_unsafe_inodes(self):
        self.perl(r'''
make_path("$root/locks"); chmod 01777,"$root/locks";
my $lock=$g->_acquire_lock(); assert($lock,'first lock');
assert(((stat("$root/locks"))[2]&07777)==01777,'changed shared directory permissions');
assert(!$g->_acquire_lock(),'lock not exclusive'); close $lock;
my $path="$root/locks/menu.lock";
link $path,"$root/second-link" or die $!;
assert(!eval {$g->_acquire_lock();1},'accepted hard-linked lock'); unlink "$root/second-link";
chmod 0666,$path; assert(!eval {$g->_acquire_lock();1},'accepted writable lock');
unlink $path; symlink "$root/elsewhere",$path;
assert(!eval {$g->_acquire_lock();1},'accepted lock symlink');
''')

    def test_snapshot_lock_preserves_shared_directory_mode(self):
        self.perl(r'''
make_path("$root/locks"); chmod 01777,"$root/locks";
my $snapshot=TimeshiftManaged::Snapshot->new(binary=>'/usr/bin/true',event_owner_uid=>0,
 event_owner_gid=>0,event_root=>$root,kind=>'daily',lock_file=>"$root/locks/snapshot.lock",
 lock_timeout_seconds=>1,logger=>$logger,command=>$command);
my $lock=$snapshot->_acquire_lock(); assert($lock,'snapshot lock');
assert(((stat("$root/locks"))[2]&07777)==01777,'changed shared directory permissions');
''')

    def test_automatic_snapshots_are_not_pinned_against_native_retention(self):
        self.perl(r'''
for my $pair (['daily','D'],['weekly','W'],['monthly','M']) {
 my $snapshot=TimeshiftManaged::Snapshot->new(binary=>'/usr/bin/true',event_owner_uid=>0,
  event_owner_gid=>0,event_root=>$root,kind=>$pair->[0],lock_file=>"$root/locks/snapshot.lock",
  lock_timeout_seconds=>1,logger=>$logger,command=>$command);
 my @argv=$snapshot->_command_arguments();
 assert(join('|',@argv) eq "/usr/bin/true|--create|--scripted|--yes|--quiet|--btrfs|--tags|$pair->[1]",
  'automatic snapshot acquired a comment/ondemand pin or lost its schedule tag');
}
''')

    def test_refresh_defers_under_the_actual_managed_snapshot_lock(self):
        self.perl(r'''
use TimeshiftManaged::Lock qw(acquire_lock);
use Fcntl qw(F_GETFD FD_CLOEXEC);
make_path("$root/locks");
my $writer=acquire_lock("$root/locks/snapshot.lock",0);
assert($writer,'writer lock');
assert(fcntl($writer,F_GETFD,0)&FD_CLOEXEC,'lock descriptor can escape through exec');
no warnings 'redefine';
my @messages;
local *FixtureLog::info=sub { push @messages,$_[1]; };
local *TimeshiftManaged::GrubRefresh::_load_configurations=sub { die 'read moving snapshot state'; };
assert($g->run()==0,'refresh did not defer');
assert(!-e "$root/menu.cfg",'published a menu while mutation was active');
assert(grep(/deferring/,@messages),'missing deferral diagnostic');
assert(!grep(/refreshed GRUB/,@messages),'deferred work was reported as a refresh');
close $writer;
my $reader=acquire_lock("$root/locks/snapshot.lock",0);
assert($reader,'released writer lock remained busy');
''')

    def test_shared_lock_rejects_writable_nonsticky_parent(self):
        self.perl(r'''
use TimeshiftManaged::Lock qw(acquire_lock);
make_path("$root/unsafe"); chmod 0777,"$root/unsafe";
assert(!eval { acquire_lock("$root/unsafe/snapshot.lock",0);1 },'untrusted parent accepted');
assert(!-e "$root/unsafe/snapshot.lock",'created a lock below untrusted parent');
''')

    def test_metadata_is_bounded_regular_sanitized_and_not_a_grub_program(self):
        self.perl(r'''
make_path("$root/snapshot");
write_file("$root/snapshot/info.json",encode_json({tags=>"D W\nreboot",comments=>"hello\nworld\x{202e}"}));
my ($tag,$comment)=$g->_snapshot_metadata("$root/snapshot");
assert($tag eq 'daily','untrusted tag survived'); assert($comment eq 'hello world ','control characters survived');
unlink "$root/snapshot/info.json";
symlink "$root/checker","$root/snapshot/info.json";
($tag,$comment)=$g->_snapshot_metadata("$root/snapshot"); assert(!defined($tag),'accepted symlink metadata');
''')

    def test_metadata_accepts_native_tag_names_and_deduplicates_aliases(self):
        self.perl(r'''
make_path("$root/snapshot");
write_file("$root/snapshot/info.json",encode_json({tags=>'daily D weekly W monthly M',comments=>''}));
my ($tag,$comment)=$g->_snapshot_metadata("$root/snapshot");
assert($tag eq 'daily, weekly, monthly','native metadata tags were lost or duplicated');
''')

    def test_atomic_publish_cleans_failure_and_does_not_rewrite_unchanged_menu(self):
        self.perl(r'''
$g->_install_menu("menuentry 'fixture' {}\n");
utime 1234,1234,"$root/menu.cfg";
$g->_install_menu("menuentry 'fixture' {}\n");
assert((stat("$root/menu.cfg"))[9]==1234,'unchanged menu was rewritten');
write_file($ENV{FIXTURE_CHECKER},"#!/bin/sh\nexit 17\n");
assert(!eval {$g->_install_menu("bad menu\n");1},'bad menu published');
open my $f,'<',"$root/menu.cfg" or die $!; local $/; my $menu=<$f>;close $f;
assert($menu eq "menuentry 'fixture' {}\n",'last good menu lost');
my @temps=glob("$root/.grub-btrfs.cfg.*"); assert(!@temps,'orphan temporary files');
$ENV{FIXTURE_CHECKER}=''; assert(!eval {$g->_install_menu('bad');1},'missing validator allowed');
''')

    def test_profile_values_reject_grub_metacharacters(self):
        self.perl(r'''
my %p=(bootprofile_default=>'balanced',bootprofile_performance=>'performance',bootprofile_hardened=>'hardened',
 grub_gfxpayload_linux=>'keep',grub_root_flags=>'rootfstype=btrfs');
$g->_validate_profiles(\%p);
$p{bootprofile_default}="balanced'; reboot";
assert(!eval {$g->_validate_profiles(\%p);1},'profile identifier injection');
$p{bootprofile_default}='balanced'; $p{grub_root_flags}='rootflags=$(reboot)';
assert(!eval {$g->_validate_profiles(\%p);1},'profile flags injection');
''')

    def test_render_accepts_usrmerge_but_never_modules_outside_the_snapshot(self):
        self.perl(r'''
my $name='2026-09-20_12-00-00'; my $sub="$root/snapshots/$name/\@";
make_path("$sub/usr/lib/modules/6.12-fixture"); symlink 'usr/lib',"$sub/lib";
write_file("$root/snapshots/$name/info.json",encode_json({tags=>'D',comments=>"O'Brien"}));
my %p=(bootprofile_default=>'balanced',bootprofile_performance=>'performance',bootprofile_hardened=>'hardened',
 grub_gfxpayload_linux=>'keep',grub_root_flags=>'rootfstype=btrfs rootflags=subvol=@',
 grub_profile_default_flags=>'quiet',grub_profile_performance_flags=>'quiet',grub_profile_hardened_flags=>'quiet');
no warnings 'redefine'; local *TimeshiftManaged::GrubRefresh::_snapshot_writable=sub {1};
my %args=(snapshot_root=>"$root/snapshots",snapshot_dir_rel=>'timeshift-btrfs/snapshots',root_subvolume=>'@',
 kernel_images=>['/boot/vmlinuz-6.12-fixture'],profile=>\%p,root_arg=>'root=UUID=fixture',
 boot_search=>'search --fs-uuid fixture',base_cmdline=>'security=apparmor',limit=>50);
my $menu=$g->_render_snapshot_menu(%args);
assert($menu =~ /linux   \/vmlinuz-6\.12-fixture/,'usrmerge snapshot omitted');
assert($menu =~ /rootflags=subvol=timeshift-btrfs\/snapshots\/2026-09-20_12-00-00\/\@/,'wrong subvolume');
unlink "$sub/lib"; symlink "$sub/usr/lib","$sub/lib";
# An absolute link resolves inside this fixture, but is never valid on the target
# when it points to host /usr/lib: the path containment guard rejects that case.
unlink "$sub/lib"; make_path("$root/outside/modules/6.12-fixture"); symlink "$root/outside","$sub/lib";
$menu=$g->_render_snapshot_menu(%args);
assert($menu !~ /linux   /,'escaped snapshot modules accepted');
''')


if __name__ == '__main__':
    unittest.main()
