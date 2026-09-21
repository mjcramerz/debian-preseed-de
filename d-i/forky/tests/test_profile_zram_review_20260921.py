"""R6 regressions. No disks, sysfs, services or AppArmor policy are changed.

Perl boundary fixtures supply configuration or kernel responses only. The real
logger, sysfs, budget and maintenance code runs; this is not a Moo integration
or a booted systemd/kernel acceptance test.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from test_dynamic_storage_sizing_20260921 import FORKY, TARGET, PERL_LIB, layout, profile_values

P = PERL_LIB / 'Zram'
CONFIG_FIXTURE = r'''
BEGIN {
    package Zram::Config;
    use Exporter 'import';
    our @EXPORT_OK = qw(cfg cfg_default);
    our %VALUES;
    sub cfg { exists $VALUES{$_[0]} or die "missing fixture config $_[0]"; $VALUES{$_[0]} }
    sub cfg_default { exists $VALUES{$_[0]} ? $VALUES{$_[0]} : $_[1] }
    $INC{'Zram/Config.pm'} = __FILE__;
}
'''


def perl(body, *, fixture=True, args=()):
    result = subprocess.run(['perl', '-I', str(PERL_LIB), '-e',
                             'use strict; use warnings;\n' + (CONFIG_FIXTURE if fixture else '') + body,
                             *map(str, args)], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result


class ProfileWiringReviewTests(unittest.TestCase):
    def test_exact_profile_inventory_and_class_pairing(self):
        expected = {f'{base}{suffix}' for base in ('btrfs-de', 'btrfs-de-p15s', 'btrfs-de-flex',
                    'f2fs-de-x360', 'f2fs-de-hp14') for suffix in ('', '-duo')}
        self.assertEqual({p.stem for p in (FORKY/'hosts/profiles').glob('*.env')}, expected)
        self.assertEqual({p.stem for p in (FORKY/'classes/class-profile').glob('*.cfg')}, expected)
        blocks = (FORKY/'classes/configs/profile.cfg').read_text().strip().split('\n\n')
        for block in blocks:
            fields = dict(line.split(': ', 1) for line in block.splitlines())
            name = fields['Name']
            self.assertEqual('addon/dualboot' in fields['RequiresClasses'].split(), name.endswith('-duo'))
            self.assertIn(name, expected)

    def test_model_match_only_p15s(self):
        for profile in ('btrfs-de-p15s', 'btrfs-de-p15s-duo'):
            self.assertEqual(profile_values(profile)['IOCOST_DEVICE_MODEL_MATCH'],
                             'WDC PC SN730 SDBQNTY-512G-1001*')
            self.assertIn('NOT measured calibration', (FORKY/'hosts/profiles'/f'{profile}.env').read_text())

    def test_p15s_disk_capacity_matrix(self):
        for profile in ('btrfs-de-p15s', 'btrfs-de-p15s-duo'):
            previous_root = 0
            for gb in (64, 128, 256, 512.11, 1024, 2048):
                disk = int(gb * 10**9)
                preserved = int(disk / 4) if profile.endswith('-duo') else 0
                with self.subTest(profile=profile, gb=gb):
                    vals, recipe = layout(profile, disk=disk, ram=32768, preserved=preserved)
                    self.assertEqual(vals['RUNTIME_DISK_TOTAL_MB'], disk // 10**6)
                    self.assertLessEqual(vals['RUNTIME_BASE_LAYOUT_MB'], vals['RUNTIME_USABLE_BUDGET_MB'])
                    self.assertGreaterEqual(vals['DEV_PART_ROOT_MB'], previous_root)
                    self.assertLessEqual(vals['DEV_PART_RAW_ZRAM_MB'], 30065)
                    self.assertIn('1000000000', recipe)  # root remains the remainder grower
                    previous_root = vals['DEV_PART_ROOT_MB']

    def test_too_small_disk_is_rejected_not_overallocated(self):
        self.assertNotEqual(layout('btrfs-de-p15s', disk=8*10**9, check=False).returncode, 0)


class TailAlignmentReviewTests(unittest.TestCase):
    def check_size(self, delta, *, target='/dev/fixturep13', shell='dash', context=''):
        code = f'''set -eu
. {shlex.quote(str(FORKY/'scripts/late/zram-swap.sh'))}
DEV_PART_RAW_ZRAM=/dev/fixturep13
RUNTIME_DEBIAN_START_SLOT=3
RUNTIME_DEBIAN_END_SLOT=13
RUNTIME_RAW_ZRAM_SLOT=13
DUALBOOT_ENABLED=true
{context}
raw_storage_partition_size_is_acceptable 17180 {17180000000+delta} {shlex.quote(target)}
'''
        cmd = ['busybox', 'sh'] if shell == 'busybox' else [shell]
        return subprocess.run([*cmd, '-c', code], capture_output=True, text=True, timeout=5)

    def test_reported_17177_mb_failure_and_4k_alignment_are_accepted(self):
        for shell in ('dash', 'bash', 'busybox'):
            if not shutil.which(shell): continue
            for actual in (17177000000, 17177999999, (17177000000//4096)*4096):
                with self.subTest(shell=shell, actual=actual):
                    self.assertEqual(self.check_size(actual-17180000000, shell=shell).returncode, 0)

    def test_tail_budget_is_bounded_in_both_directions(self):
        budget = 13 * 1048576  # 11 newly-created slots plus two boundary MiB
        for delta in (-budget, budget, 0):
            self.assertEqual(self.check_size(delta).returncode, 0)
        for delta in (-budget-1, budget+1, -100000000, 100000000):
            self.assertNotEqual(self.check_size(delta).returncode, 0)

    def test_non_tail_raw_swap_keeps_two_mib_bound(self):
        self.assertNotEqual(self.check_size(-3000000, target='/dev/fixturep12').returncode, 0)
        self.assertEqual(self.check_size(-2097152, target='/dev/fixturep12').returncode, 0)

    def test_invalid_or_missing_tail_context_fails_closed(self):
        for context in ('unset RUNTIME_RAW_ZRAM_SLOT', 'RUNTIME_DEBIAN_START_SLOT=03',
                        'RUNTIME_DEBIAN_END_SLOT=12', 'RUNTIME_DEBIAN_START_SLOT=14',
                        'DUALBOOT_ENABLED=unknown', 'RUNTIME_DEBIAN_START_SLOT=0',
                        'RUNTIME_DEBIAN_END_SLOT=100; RUNTIME_RAW_ZRAM_SLOT=100',
                        'RUNTIME_RAW_ZRAM_SLOT=999999999999999999999'):
            with self.subTest(context=context):
                self.assertNotEqual(self.check_size(0, context=context).returncode, 0)

    def test_new_esp_adds_only_one_mib(self):
        budget = 14 * 1048576
        self.assertEqual(self.check_size(-budget, context='DUALBOOT_ENABLED=false').returncode, 0)
        self.assertNotEqual(self.check_size(-budget-1, context='DUALBOOT_ENABLED=false').returncode, 0)


class LoggerAndPressureReviewTests(unittest.TestCase):
    def test_logger_info_default_bounded_normalization_and_error_state(self):
        result = perl(r'''
use Zram::Logger qw(log_msg log_enabled);
no warnings 'redefine';
*Zram::Logger::setlogsock = sub { die "no local socket" };
$! = 2; $? = 7; $@ = 'caller exception';
log_msg('info', "hello\nforged\x00\t" . ('x' x 9000));
die 'errno clobbered' unless 0+$! == 2;
die 'status clobbered' unless $? == 7;
die 'exception clobbered' unless $@ eq 'caller exception';
die 'info disabled' unless log_enabled('info');
die 'debug enabled' if log_enabled('debug');
''', fixture=False)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertIn('<6>zram-writeback: hello forged??', result.stderr)
        self.assertLess(len(result.stderr), 4200)
        self.assertIn('[truncated]', result.stderr)

    def test_syslog_success_has_no_duplicate_stderr_record(self):
        result = perl(r'''
use Zram::Logger qw(log_msg);
no warnings 'redefine';
*Zram::Logger::setlogsock = sub { die 'not unix' unless $_[0] eq 'unix'; 1 };
*Zram::Logger::openlog = sub { 1 };
*Zram::Logger::closelog = sub { 1 };
*Zram::Logger::syslog = sub { die 'not literal formatting' unless $_[1] eq '%s'; print $_[2]; 1 };
log_msg('info', 'literal %s message');
''', fixture=False)
        self.assertEqual(result.stdout, 'literal %s message')
        self.assertEqual(result.stderr, '')

    def test_poll_uses_seconds_and_actual_short_deadline(self):
        source = (P/'Daemon.pm').read_text()
        function = source.split('sub _poll_triggers {',1)[1].split('\nsub _run_pressure_pass',1)[0]
        result = perl(r'''
use IO::Poll qw(POLLERR POLLHUP POLLNVAL POLLPRI POLLIN);
use Errno qw(EINTR);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
sub fatal { die $_[0] }
''' + 'sub _poll_triggers {' + function + r'''
{ package PollFixture; sub new { bless {}, shift } sub poll { die 'not seconds' unless $_[1] == 10; 0 } }
_poll_triggers(PollFixture->new(), 10);
pipe(my $read, my $write) or die $!;
my $poll = IO::Poll->new(); $poll->mask($read => POLLIN);
my $start = clock_gettime(CLOCK_MONOTONIC);
die 'unexpected event' if _poll_triggers($poll, 0.02);
my $elapsed = clock_gettime(CLOCK_MONOTONIC)-$start;
die "wrong deadline: $elapsed" unless $elapsed >= 0.01 && $elapsed < 2;
print 'ok';
''', fixture=False)
        self.assertEqual(result.stdout, 'ok')
        self.assertIn('clock_gettime(CLOCK_MONOTONIC)', source)
        self.assertIn('run_maintenance(state => $state, reasons => $reasons)', source)

    def test_pressure_bypasses_idle_fill_gate_and_avoids_second_full_scan(self):
        source = (P/'Policy.pm').read_text()
        # Execute exact production methods without loading unused Moo-backed
        # hardware readers. All invoked boundary functions are supplied below.
        fill = source.split('sub _fill_gate_met {', 1)[1].split('\nsub policy_plan', 1)[0]
        run = source.split('sub run_maintenance {', 1)[1].rsplit('\n1;', 1)[0]
        methods = ('package Zram::Policy; use Zram::Config qw(cfg); '
                   'sub fatal { die $_[0] }\nsub _fill_gate_met {' + fill +
                   '\nsub run_maintenance {' + run + '\npackage main;\n')
        result = perl(methods + r'''
$Zram::Config::VALUES{ZRAM_COLD_TIER_ENABLE}=1;
$Zram::Config::VALUES{ZRAM_IDLE_WRITEBACK_ENABLE}=1;
$Zram::Config::VALUES{ZRAM_COLD_TIER_MIN_ZRAM_FILL_PCT}=70;
no warnings 'redefine';
my @scans; my @logs;
*Zram::Policy::_state_idle_age = sub { 60 };
*Zram::Policy::io_pressure_snapshot = sub { {state=>'low'} };
*Zram::Policy::io_pressure_log_fields = sub { 'io_psi=low' };
*Zram::Policy::refresh_daily_writeback_budget = sub { 0 };
*Zram::Policy::writeback_budget_pages_available = sub { 4096 };
*Zram::Policy::apply_writeback_batch_size = sub { {effective_batch_size=>8} };
*Zram::Policy::_maintenance_possible = sub { 1 };
*Zram::Policy::zram_fill_pct = sub { 20 };
*Zram::Policy::mark_idle_for_state = sub { 1 };
*Zram::Policy::_writeback_class_caps = sub { {} };
*Zram::Policy::capture_zram_state = sub { my($phase,%opts)=@_; push @scans,[$phase,\%opts]; {} };
*Zram::Policy::block_state_authoritative = sub { 1 };
*Zram::Policy::policy_plan = sub { {recompress=>[],writeback=>[],budget_allows=>1,writeback_pass_pages=>512} };
*Zram::Policy::_apply_plan = sub { 1 };
*Zram::Policy::log_msg = sub { push @logs,$_[1] };
for my $state ('pressure','emergency') {
 @scans=(); @logs=();
 my $r=Zram::Policy::run_maintenance(state=>$state,reasons=>['memory PSI fixture']);
 die 'pressure gated' unless $r->{operations}==1;
 die 'wrong snapshots' unless @scans==2;
 die 'after rescans candidates' unless $scans[1][1]{scan_block_state}==0;
 die 'pressure reason lost' unless grep {/memory PSI fixture/} @logs;
}
my $r=Zram::Policy::run_maintenance(state=>'normal');
die 'idle fill gate lost' unless $r->{skipped} eq 'below-fill';
print 'ok';
''')
        self.assertEqual(result.stdout, 'ok')

    def test_info_defaults_and_managed_log_route(self):
        self.assertIn('ZRAM_LOG_LEVEL="info"', (FORKY/'hosts/installer/runtime.env').read_text())
        self.assertIn("log_level => 'info'", (P/'Config/Schema.pm').read_text())
        route = (TARGET/'etc/rsyslog.d/36-zram.conf').read_text()
        self.assertIn('/var/log/managed/zram/zram.log', route)
        for text in ('zram-writeback', 'zram-device-setup', '0640', '0750'):
            self.assertIn(text, route)


class SysfsBudgetReviewTests(unittest.TestCase):
    def test_trigger_audits_observed_4k_deltas_and_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = perl(r'''
use Zram::Sysfs;
$Zram::Config::VALUES{ZRAM_SYSFS}=$ARGV[0];
sub put { open my $fh,'>',"$ARGV[0]/$_[0]" or die $!; print $fh $_[1]; close $fh or die $!; }
put('mm_stat', sprintf('%8d %8d %8d %8d %8d',100,50,4096,9999,9000)); put('bd_stat',sprintf('%8d %8d %8d',8,2,10)); put('writeback_limit','100');
no warnings 'redefine';
*Zram::Sysfs::log_msg = sub { print "$_[0] $_[1]\n" };
*Zram::Sysfs::try_values = sub { put('mm_stat',sprintf('%8d %8d %8d %8d %8d',100,40,2048,9999,9000)); put('bd_stat',sprintf('%8d %8d %8d',10,2,13)); put('writeback_limit','97'); 1 };
Zram::Sysfs::writeback_spec('page_indexes=1-3');
''', args=(tmp,))
            self.assertIn('bd_writes_delta_4k=3 backing_written_bytes=12288', result.stdout)
            self.assertIn('mem_used_delta_bytes=-2048 writeback_limit_remaining_4k=97', result.stdout)
            self.assertIn('result=accepted', result.stdout)
            ids = re.findall(r'id=(\d+-\d+)', result.stdout)
            self.assertEqual(len(ids), 2); self.assertEqual(ids[0], ids[1])

    def test_missing_counters_are_unknown_not_claimed_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = perl(r'''
use Zram::Sysfs;
$Zram::Config::VALUES{ZRAM_SYSFS}=$ARGV[0];
no warnings 'redefine';
*Zram::Sysfs::log_msg = sub { print "$_[1]\n" };
Zram::Sysfs::writeback_spec('page_index=1');
''', args=(tmp,))
            self.assertIn('result=failed', result.stdout)
            self.assertIn('bd_writes_delta_4k=unknown backing_written_bytes=unknown', result.stdout)

    def test_dry_run_does_not_touch_sysfs_or_budget_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = perl(r'''
use Zram::Sysfs;
use Zram::Budget;
%Zram::Config::VALUES=(ZRAM_SYSFS=>$ARGV[0],ZRAM_RUNTIME_DIR=>$ARGV[0],ZRAM_DRY_RUN=>1,
 ZRAM_WRITEBACK_ENABLED=>1,ZRAM_WRITEBACK_LIMIT_ENABLE=>1,ZRAM_DAILY_WRITEBACK_LIMIT_BYTES=>40960);
for my $name ('writeback','writeback_limit','writeback_limit_enable') {
 open my $fh,'>',"$ARGV[0]/$name" or die $!; print $fh 'original'; close $fh;
}
no warnings 'redefine';
*Zram::Sysfs::log_msg=sub { print "$_[1]\n" };
*Zram::Budget::log_msg=sub { print "$_[1]\n" };
Zram::Sysfs::writeback_spec('page_index=1');
Zram::Budget::refresh_daily_writeback_budget();
die 'dry-run published budget' if -e Zram::Budget::budget_state_file();
''', args=(tmp,))
            for name in ('writeback', 'writeback_limit', 'writeback_limit_enable'):
                self.assertEqual((Path(tmp)/name).read_text(), 'original')
            self.assertIn('result=dry-run', result.stdout)
            self.assertIn('pages_4k=10', result.stdout)

    def test_sysfs_uint_parser_rejects_suffixes_and_compaction_preserves_peak(self):
        with tempfile.TemporaryDirectory() as tmp:
            perl(r'''
use Zram::Sysfs;
$Zram::Config::VALUES{ZRAM_SYSFS}=$ARGV[0];
my $p="$ARGV[0]/writeback_limit";
for my $bad ('12oops','-1','123456789012345678901') {
 open my $fh,'>',$p or die $!; print $fh $bad; close $fh;
 die 'accepted invalid counter' if defined Zram::Sysfs::read_uint_attr($p);
}
''', args=(tmp,))
        compact = (P/'Sysfs.pm').read_text().split('sub compact_device {',1)[1]
        self.assertNotIn('"$sysfs/mem_used_max"', compact)


class MaintenanceIsolationReviewTests(unittest.TestCase):
    def test_maintenance_units_are_bounded_and_follow_setup_lifetime(self):
        for name in ('zram-writeback.service.tmpl', 'zram-writebackd.service.tmpl'):
            text = (TARGET/'etc/systemd/system'/name).read_text()
            for required in ('PrivatePIDs=yes', 'PrivateUsers=no', 'ProcSubset=all',
                             'KillMode=control-group', 'TimeoutStopSec=20s', 'TasksMax=16',
                             'NoNewPrivileges=yes', 'RestrictAddressFamilies=AF_UNIX',
                             'CapabilityBoundingSet=CAP_SYS_RESOURCE', 'RestrictNamespaces=yes',
                             'OOMPolicy=stop', 'BindsTo=__INSTALLER_ZRAM_SETUP_UNIT__',
                             'PartOf=__INSTALLER_ZRAM_SETUP_UNIT__'):
                self.assertIn(required, text)
            self.assertNotIn('ProtectKernelTunables=yes', text)  # would hide required writable controls

    def test_apparmor_maintenance_has_no_blanket_privilege_or_block_write(self):
        text = (TARGET/'etc/apparmor.d/managed-system-wrappers').read_text()
        block = text.split('profile managed-zram-writeback ',1)[1].split('\nprofile managed-luks-mok-open ',1)[0]
        for forbidden in ('  capability,', '  network,', '  mount,', '  userns,',
                          '/dev/mapper/zram-writeback rw', '/dev/zram[0-9]* rw', '/sys/block/** rw'):
            self.assertNotIn(forbidden, block)
        for required in ('capability sys_resource,', '/proc/pressure/memory rw,',
                         '/run/zram/** rwkl,', 'writeback_limit_enable,writeback_batch_size} w,',
                         '/sys/kernel/debug/zram/zram[0-9]*/block_state r,'):
            self.assertIn(required, block)

    @unittest.skipUnless(shutil.which('apparmor_parser'), 'AppArmor parser unavailable')
    def test_apparmor_profile_parses_without_loading_kernel_policy(self):
        text = (TARGET/'etc/apparmor.d/managed-system-wrappers').read_text()
        block = text.split('profile managed-zram-writeback ',1)[1].split('\nprofile managed-luks-mok-open ',1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'zram-profile'
            path.write_text('#include <tunables/global>\nprofile managed-zram-writeback '+block)
            result = subprocess.run(['apparmor_parser', '--skip-kernel-load', '--skip-read-cache',
                                     '-I', str(TARGET/'etc/apparmor.d'), '-I', '/etc/apparmor.d', str(path)],
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
