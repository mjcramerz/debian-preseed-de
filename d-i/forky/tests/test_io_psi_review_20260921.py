"""I/O-PSI admission regressions using real Perl parsing/policy/tuning code.

Only configuration access, memory telemetry and selected kernel operations are
injected. Temporary regular files model procfs/sysfs; no real devices, service
manager or pressure generators are touched. This is not a Moo or kernel boot
test. The command test extracts its exact production execute method because
Moo is an optional test-host dependency, not a replacement implementation.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_dynamic_storage_sizing_20260921 import (
    FORKY, PERL_LIB, PROFILES, TARGET, normalize, rendered_policy,
)
from test_profile_zram_review_20260921 import CONFIG_FIXTURE

MEMORY_FIXTURE = r'''
BEGIN {
    package Zram::Procfs;
    use Exporter 'import';
    our @EXPORT_OK = qw(memory_pressure_snapshot);
    sub memory_pressure_snapshot { return { mem_available_bytes=>1048576, mem_total_bytes=>2097152,
        psi_some_avg10_millionths=>0, psi_full_avg10_millionths=>0 } }
    $INC{'Zram/Procfs.pm'} = __FILE__;
    package Zram::Pressure;
    use Exporter 'import';
    our @EXPORT_OK = qw(determine_pressure_state);
    sub determine_pressure_state { return ('pressure', ['test fixture']) }
    $INC{'Zram/Pressure.pm'} = __FILE__;
}
'''


def sample(some='0.00', full='0.00'):
    return (f'some avg10={some} avg60=0.00 avg300=0.00 total=123\n'
            f'full avg10={full} avg60=0.00 avg300=0.00 total=12\n')


class IOFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='zram-io-review-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proc = self.root / 'proc'
        (self.proc / 'pressure').mkdir(parents=True)
        self.io = self.proc / 'pressure/io'
        self.io.write_text(sample())
        self.sysfs = self.root / 'sys/block/zram0'
        self.sysfs.mkdir(parents=True)
        self.runtime = self.root / 'run'
        self.runtime.mkdir(mode=0o700)
        for name, value in {'writeback_batch_size': '64\n', 'writeback_limit': '100001\n',
                            'writeback': '', 'recompress': '', 'compact': ''}.items():
            (self.sysfs / name).write_text(value)
        self.config = normalize(rendered_policy('btrfs-de'))
        self.config.update(ZRAM_PROCFS_ROOT=str(self.proc), ZRAM_SYSFS=str(self.sysfs),
                           ZRAM_SYSFS_ROOT=str(self.root / 'sys'),
                           ZRAM_RUNTIME_DIR=str(self.runtime),
                           ZRAM_BACKING_RAW_DEVICE='', ZRAM_BACKING_DEVICE='')

    def run_perl(self, body, *, check=True, memory=False):
        source = 'use strict; use warnings; use JSON::PP;\n' + CONFIG_FIXTURE
        if memory:
            source += MEMORY_FIXTURE
        source += "\nlocal $/; %Zram::Config::VALUES = %{decode_json(<STDIN>)};\n"
        source += body
        result = subprocess.run(payload_installed_argv(['perl', '-I'+str(PERL_LIB), '-e', source]),
                                input=json.dumps(self.config), text=True,
                                capture_output=True, timeout=10)
        if check and result.returncode:
            self.fail(result.stdout + result.stderr)
        return result

    def snap(self):
        return json.loads(self.run_perl('use Zram::IOPressure qw(io_pressure_snapshot); '
                                       'print encode_json(io_pressure_snapshot());').stdout)

    def tuning(self, state='pressure', budget=None):
        budget_text = 'undef' if budget is None else str(budget)
        return json.loads(self.run_perl('use Zram::Tuning qw(writeback_tuning_snapshot); '
            f"print encode_json(writeback_tuning_snapshot('{state}', {budget_text}));").stdout)


class IOParserTests(IOFixture):
    def test_low_and_exact_threshold_samples(self):
        for some, full, expected in [('0.00','0.00','low'), ('9.999999','1.999999','low'),
                                     ('10.00','0.00','high'), ('2.00','2.00','high'),
                                     ('100.00','100.00','high')]:
            with self.subTest(some=some, full=full):
                self.io.write_text(sample(some, full))
                value = self.snap()
                self.assertEqual(value['state'], expected)
                self.assertEqual(value['throttle'], int(expected == 'high'))
                self.assertEqual(value['some_avg10_millionths'], round(float(some)*1000000))

    def test_bad_samples_are_conservative_not_fatal(self):
        for payload in ['', 'some avg10=0.00\n', sample() + sample(),
                        sample('101.00'), sample('0.00', '1.00'), sample('-1.00'),
                        sample('1e9'), sample('0.1234567'), sample() + '\0', 'x'*4097,
                        sample().replace('avg60=0.00', 'avg60=100.01'),
                        sample().replace('total=123', 'total='+'9'*21)]:
            with self.subTest(payload=payload[:100]):
                self.io.write_text(payload)
                value = self.snap()
                self.assertEqual((value['state'], value['throttle']), ('unknown', 1))
                self.assertNotIn('some_avg10_millionths', value)

    def test_missing_symlink_directory_and_fifo_do_not_block(self):
        self.io.unlink()
        self.assertEqual(self.snap()['reason'], 'open-failed')
        target = self.root/'sample'; target.write_text(sample())
        self.io.symlink_to(target)
        self.assertEqual(self.snap()['state'], 'unknown')
        self.io.unlink(); self.io.mkdir()
        self.assertEqual(self.snap()['reason'], 'not-regular')
        self.io.rmdir(); os.mkfifo(self.io)
        self.assertEqual(self.snap()['reason'], 'not-regular')

    def test_disabled_reader_does_not_need_procfs(self):
        self.config['ZRAM_IO_PSI_ENABLE'] = 0
        del self.config['ZRAM_PROCFS_ROOT']
        self.assertEqual(self.snap(), {'state':'disabled', 'throttle':0, 'reason':'policy-disabled'})

    def test_log_fields_never_call_missing_telemetry_zero(self):
        self.io.unlink()
        result = self.run_perl('use Zram::IOPressure qw(io_pressure_snapshot io_pressure_log_fields); '
                               'print io_pressure_log_fields(io_pressure_snapshot());')
        self.assertIn('io_psi=unknown', result.stdout)
        self.assertIn('io_some_avg10_millionths=unknown', result.stdout)
        self.assertIn('io_full_avg10_millionths=unknown', result.stdout)


class IOConfigurationTests(unittest.TestCase):
    def test_all_ten_profiles_render_and_normalize_every_io_control(self):
        self.assertEqual(len(PROFILES), 10)
        for profile in PROFILES:
            with self.subTest(profile=profile):
                raw = rendered_policy(profile)
                self.assertEqual(raw['io_pressure'], {
                    'enabled':'1', 'some_avg10_min':'10.00', 'full_avg10_min':'2.00',
                    'batch_size_pressure':'8', 'batch_size_emergency':'16',
                    'max_pages_pressure':'1024', 'max_pages_emergency':'4096'})
                cfg = normalize(raw)
                self.assertEqual(cfg['ZRAM_IO_PSI_SOME_AVG10_THRESHOLD_UNITS'], 10000000)
                self.assertEqual(cfg['ZRAM_IO_PSI_FULL_AVG10_THRESHOLD_UNITS'], 2000000)
                self.assertEqual(cfg['ZRAM_IO_PSI_ENABLE'], 1)

    def test_invalid_thresholds_caps_relationships_and_keys_rejected(self):
        for key, value in [('some_avg10_min','100.01'), ('full_avg10_min','-1'),
                           ('enabled','maybe'), ('max_pages_pressure','0'),
                           ('max_pages_emergency','-1'), ('batch_size_pressure','0'),
                           ('batch_size_pressure','17'), ('batch_size_emergency','129'),
                           ('max_pages_pressure','4097'), ('max_pages_emergency','32769'),
                           ('unrecognized','1')]:
            with self.subTest(key=key, value=value):
                raw = copy.deepcopy(rendered_policy('btrfs-de'))
                raw['io_pressure'][key] = value
                self.assertNotEqual(normalize(raw, check=False).returncode, 0)

    def test_omitted_section_gets_secure_defaults(self):
        raw = copy.deepcopy(rendered_policy('btrfs-de')); del raw['io_pressure']
        cfg = normalize(raw)
        self.assertEqual(cfg['ZRAM_IO_PSI_ENABLE'], 1)
        self.assertEqual(cfg['ZRAM_IO_PSI_MAX_PAGES_EMERGENCY'], 4096)


class IOTuningTests(IOFixture):
    def test_low_high_unknown_matrix(self):
        for io_state in ('low', 'high', 'unknown'):
            for state, regular_batch, regular_pages, throttled_batch, throttled_pages in (
                    ('pressure',64,8192,8,1024), ('emergency',128,32768,16,4096)):
                with self.subTest(io=io_state, state=state):
                    self.io.write_text(sample('30.00','4.00') if io_state == 'high' else
                                       '' if io_state == 'unknown' else sample())
                    value = self.tuning(state)
                    self.assertEqual(value['io_pressure']['state'], io_state)
                    self.assertEqual(value['effective_batch_size'], regular_batch if io_state == 'low' else throttled_batch)
                    self.assertEqual(value['pass_page_limit'], regular_pages if io_state == 'low' else throttled_pages)

    def test_normal_never_gets_writeback_pages(self):
        self.io.write_text(sample('100.00','100.00'))
        self.assertEqual(self.tuning('normal')['pass_page_limit'], 0)

    def test_budget_zero_and_smaller_quotas_win(self):
        self.io.write_text(sample('30.00','4.00'))
        for budget in (0, -1, 1, 7, 511):
            with self.subTest(budget=budget):
                self.assertEqual(self.tuning(budget=budget)['pass_page_limit'], max(budget, 0))

    def test_adaptive_disabled_still_obeys_io_caps(self):
        self.config['ZRAM_WRITEBACK_BATCH_SIZE_ADAPTIVE'] = 0
        self.io.write_text(sample('30.00','4.00'))
        self.assertEqual(self.tuning()['effective_batch_size'], 8)

    def test_queue_rotational_and_global_limits_cannot_be_loosened(self):
        self.io.write_text(sample('30.00','4.00'))
        result = self.run_perl(r'''
use Zram::Tuning qw(writeback_tuning_snapshot);
no warnings 'redefine';
*Zram::Tuning::backing_queue_depth = sub { 3 };
*Zram::Tuning::backing_rotational = sub { 1 };
$Zram::Config::VALUES{ZRAM_WRITEBACK_BATCH_SIZE_ROTATIONAL_MAX} = 2;
print encode_json(writeback_tuning_snapshot('emergency', 50));
''')
        value = json.loads(result.stdout)
        self.assertEqual(value['effective_batch_size'], 2)
        self.assertEqual(value['pass_page_limit'], 50)
        self.config['ZRAM_WRITEBACK_BATCH_SIZE'] = 1
        self.assertEqual(self.tuning()['effective_batch_size'], 1)

    def test_disabled_io_retains_existing_pressure_limits(self):
        self.config['ZRAM_IO_PSI_ENABLE'] = 0; self.io.unlink()
        value = self.tuning()
        self.assertEqual((value['effective_batch_size'], value['pass_page_limit']), (64,8192))


class IOAdmissionTests(IOFixture):
    def plan(self, state, *, manual=''):
        self.config['ZRAM_MAINTENANCE_PAGE_INDEXES'] = manual
        result = self.run_perl(r'''
use Zram::Policy qw(policy_plan);
my $stats = { block_state_available=>1, block_state_truncated=>0,
 cold_pages=>20000, idle_pages=>20000, huge_idle_pages=>10000,
 incompressible_pages=>10000, huge_pages=>20000,
 incompressible_writeback_specs=>['page_indexes=0-9999'],
 huge_idle_writeback_specs=>['page_indexes=10000-19999'] };
''' + f"print encode_json(policy_plan('{state}', $stats, writeback_pages_available=>100000));", memory=True)
        return json.loads(result.stdout)

    def test_normal_recompression_only_and_bounded_pressure_emergency_plans(self):
        self.io.write_text(sample('30.00','4.00'))
        normal = self.plan('normal')
        self.assertEqual(normal['writeback'], [])
        self.assertTrue(normal['recompress'])
        for state, pages in (('pressure',1024), ('emergency',4096)):
            with self.subTest(state=state):
                plan = self.plan(state)
                self.assertTrue(plan['recompress'])
                self.assertEqual(plan['writeback'], [f'page_indexes=0-{pages-1}'])
                self.assertEqual(plan['writeback_pass_pages'], pages)

    def test_manual_page_ranges_cannot_bypass_shared_budget(self):
        self.io.write_text(sample('30.00','4.00'))
        plan = self.plan('pressure', manual='page_indexes=20000-29999')
        self.assertEqual(plan['writeback'], ['page_indexes=20000-21023'])

    def apply(self, *, state='pressure', initial=8192, after=None):
        after_perl = ''
        if after is not None:
            # A kernel-boundary hook changes telemetry during recompression;
            # the production policy must resample before the writeback pass.
            after_perl = ('open my $f, ">", cfg("ZRAM_PROCFS_ROOT")."/pressure/io" or die $!; '
                          'print {$f} '+json.dumps(after)+'; close $f;')
        body = r'''
use Zram::Policy;
use Zram::Config qw(cfg);
my @events;
no warnings 'redefine';
*Zram::Policy::recompress_spec = sub { push @events, 'recompress'; AFTER_RECOMPRESS return 1 };
*Zram::Policy::writeback_spec = sub { push @events, 'writeback:'.$_[0]; return 1 };
*Zram::Policy::compact_device = sub { push @events, 'compact'; return 1 };
my $plan = {state=>'STATE', recompress=>['type=idle max_pages=64'],
 writeback=>['page_indexes=0-699', 'page_indexes=1000-10999', 'page_indexes=20000-20999'],
 compact=>1, writeback_pass_pages=>INITIAL};
my $operations = Zram::Policy::_apply_plan($plan);
print encode_json({plan=>$plan, events=>\@events, operations=>$operations});
'''.replace('AFTER_RECOMPRESS', after_perl).replace("'STATE'", repr(state)).replace('INITIAL', str(initial))
        return self.run_perl(body, memory=True)

    def test_io_is_resampled_after_recompression_and_shared_cap_truncates(self):
        result = self.apply(after=sample('30.00','4.00'))
        value = json.loads(result.stdout)
        self.assertEqual(value['events'], ['recompress','writeback:page_indexes=0-699',
                         'writeback:page_indexes=1000-1323','compact'])
        self.assertEqual(value['plan']['writeback_pass_pages'], 1024)
        self.assertEqual(payload_read_text(self.sysfs/'writeback_batch_size').strip(), '8')
        self.assertIn('io_psi=high', result.stderr)
        self.assertIn('selected_pages=1024', result.stderr)
        self.assertIn('recompression_first=1', result.stderr)

    def test_emergency_high_io_still_allows_a_bounded_pass(self):
        self.io.write_text(sample('30.00','4.00'))
        value = json.loads(self.apply(state='emergency', initial=32768).stdout)
        self.assertEqual(value['plan']['writeback_pass_pages'], 4096)
        self.assertEqual(value['plan']['writeback_batch_size'], 16)
        self.assertEqual(value['plan']['writeback'], ['page_indexes=0-699','page_indexes=1000-4395'])

    def test_missing_batch_knob_bounds_total_pass_to_one_effective_batch(self):
        (self.sysfs/'writeback_batch_size').unlink()
        for state, cap in (('pressure',8), ('emergency',16)):
            with self.subTest(state=state):
                self.io.write_text(sample('30.00','4.00'))
                result = self.apply(state=state)
                value = json.loads(result.stdout)
                self.assertEqual(value['plan']['writeback'], [f'page_indexes=0-{cap-1}'])
                self.assertEqual(value['plan']['writeback_batch_applied'], 0)
                self.assertIn('batch knob unavailable', result.stderr)

    def test_unknown_recheck_still_allows_only_a_throttled_pass(self):
        value = json.loads(self.apply(after='invalid').stdout)
        self.assertEqual(value['plan']['io_pressure']['state'], 'unknown')
        self.assertEqual(value['plan']['writeback_pass_pages'], 1024)

    def test_existing_plan_cap_is_never_expanded_by_low_io_recheck(self):
        value = json.loads(self.apply(initial=100, after=sample()).stdout)
        self.assertEqual(value['plan']['writeback'], ['page_indexes=0-99'])

    def test_exhausted_budget_suppresses_disk_io_without_suppressing_recompression(self):
        (self.sysfs/'writeback_limit').write_text('1\n')
        value = json.loads(self.apply().stdout)
        self.assertEqual(value['plan']['writeback'], [])
        self.assertEqual(value['events'], ['recompress','compact'])

    def test_dry_run_tuning_does_not_change_sysfs(self):
        self.config['ZRAM_DRY_RUN'] = 1; self.io.write_text(sample('30.00','4.00'))
        result = self.run_perl('use Zram::Tuning qw(apply_writeback_batch_size); '
            "print encode_json(apply_writeback_batch_size('pressure')); ")
        self.assertEqual(json.loads(result.stdout)['effective_batch_size'], 8)
        self.assertEqual(payload_read_text(self.sysfs/'writeback_batch_size'), '64\n')
        self.assertIn('dry-run:', result.stderr)

    def command(self, spec, *, high=True):
        self.io.write_text(sample('30.00','4.00') if high else sample())
        source = payload_read_text(PERL_LIB/'Zram/Command/Writeback.pm')
        execute = re.search(r'^sub execute \{.*?^\}', source, re.M|re.S).group()
        body = r'''
use Zram::Config qw(cfg); use Zram::Error qw(fatal);
use Zram::Budget qw(writeback_budget_pages_available);
use Zram::IOPressure qw(io_pressure_snapshot io_pressure_log_fields);
use Zram::Logger qw(log_msg); use Zram::Pressure qw(determine_pressure_state);
use Zram::Tuning qw(apply_writeback_batch_size writeback_pass_pages_for_state);
use Zram::Types qw(validate_writeback_spec count_page_index_spec_pages);
sub writeback_spec { print 'WRITE:'.$_[0]; return 1 }
''' + execute + '\nexecute(undef, '+json.dumps(spec)+');'
        return self.run_perl(body, check=False, memory=True)

    def test_metrics_publish_io_values_and_log_unknown_as_unknown(self):
        self.config['ZRAM_METRICS_FILE'] = str(self.runtime/'zram0.metrics')
        if os.geteuid() != 0:
            self.config['ZRAM_DRY_RUN'] = 1
        for payload, state, some in ((sample('30.00','4.00'),'high','30000000'),
                                     ('invalid','unknown','unknown')):
            with self.subTest(state=state):
                self.io.write_text(payload)
                result = self.run_perl("use Zram::Metrics qw(capture_zram_state); "
                    "print encode_json(capture_zram_state('io-review', state=>'pressure', scan_block_state=>0));",
                    memory=True)
                metrics = payload_read_text(self.runtime/'zram0.metrics')
                self.assertIn(f'io_psi_state={state}\n', metrics)
                self.assertIn(f'io_psi_some_avg10_millionths={some}\n', metrics)
                self.assertIn('io_psi_reason=', metrics)
                self.assertIn(f'io_psi={state}', result.stderr)
                self.assertNotIn('uninitialized', result.stderr)

    def test_explicit_diagnostic_command_cannot_bypass_high_io_page_bound(self):
        for spec in ('type=idle', 'type=incompressible', 'page_indexes=0-1024'):
            with self.subTest(spec=spec):
                result = self.command(spec)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('WRITE:', result.stdout)
        result = self.command('page_indexes=0-1023')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'WRITE:page_indexes=0-1023')

    def test_explicit_low_io_diagnostic_and_high_io_no_knob_paths(self):
        result = self.command('type=idle', high=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.sysfs/'writeback_batch_size').unlink()
        self.assertNotEqual(self.command('page_indexes=0-8').returncode, 0)
        self.assertEqual(self.command('page_indexes=0-7').returncode, 0)



class IOStagingTests(unittest.TestCase):
    def test_complete_perl_library_is_staged_in_all_installer_shells(self):
        source = FORKY / 'scripts/late/zram-swap.sh'
        expected = {p.relative_to(PERL_LIB).as_posix(): p
                    for p in PERL_LIB.rglob('*.pm')}
        self.assertIn('Zram/IOPressure.pm', expected)
        shells = [['/bin/dash'], ['/bin/bash']]
        busybox = shutil.which('busybox')
        if busybox:
            shells.append([busybox, 'sh'])
        for shell in shells:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as work:
                root = Path(work)
                destination = root / 'installed-library'
                code = r'''
                    . "$1"
                    SOURCE_TARGET=$2
                    DIR_ZRAM_SITE_PERL=$3
                    installer_repo_join_var() {
                        [ "$1" = DIR_HOOKS_TARGET ]
                        printf '%s/%s\n' "$SOURCE_TARGET" "$2"
                    }
                    stage_target_asset() {
                        mkdir -p "${2%/*}"
                        cp -- "$1" "$2"
                        chmod "$3" "$2"
                    }
                    zram_perl_modules
                    stage_target_zram_perl_modules
                '''
                result = subprocess.run(payload_installed_argv(shell + ['-eu', '-c', code, 'staging-fixture',
                    str(source), str(TARGET), str(destination)]), capture_output=True,
                    text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                listed = result.stdout.splitlines()
                self.assertEqual(len(listed), len(set(listed)))
                self.assertEqual(set(listed), set(expected))
                actual = {p.relative_to(destination).as_posix(): p
                          for p in destination.rglob('*.pm')}
                self.assertEqual(set(actual), set(expected))
                for relative, installed in actual.items():
                    self.assertEqual(payload_read_bytes(installed), payload_read_bytes(expected[relative]))
                    self.assertEqual(payload_source_stat(installed).st_mode & 0o7777, 0o644)

if __name__ == '__main__':
    unittest.main()
