"""Production output functions with mocked Wayland/systemd endpoints.

No compositor, DRM device, power action, or real service is accessed. The lock
contention test uses real flock/fork on a private temporary directory.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY/'hooks/target'


class OutputReconcileTests(unittest.TestCase):
    def perl(self, script):
        source = Path(os.environ.get('LABWC_OUTPUT_TEST_SOURCE', str(TARGET/'usr/local/libexec/labwc-output-watch')))
        main = source.read_text().split('package main;', 1)[1].split('unless (caller) {', 1)[0]
        code = 'use strict; use warnings; package main;\n'+main
        code += '\nsub test_defaults { %defaults = @_; }\nno warnings "redefine";\n'+script
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'test.pl'; path.write_text(code)
            result = subprocess.run(['perl', '-I'+str(TARGET/'usr/local/lib/perl5/site_perl/managed-runtime'), str(path)],
                                    capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        return result

    def test_policy_does_not_probe_idle_in_a_separate_transaction(self):
        self.perl(r'''
my @actions; *run_refresh_action = sub { push @actions, $_[0]; 1 };
apply_output_policy();
die 'split check/action lock' unless @actions == 1 && $actions[0] eq q{};
''')

    def test_manual_and_periodic_refresh_leave_sleeping_outputs_alone(self):
        self.perl(r'''
*session_is_active = sub { 1 }; *idle_topology_active = sub { 1 };
*idle_topology_restore_requested = sub { 0 };
*find_command = sub { die 'ordinary refresh reached a display endpoint while idle' };
die 'unexpected mutation' if refresh_outputs(q{});
''')

    def test_idle_decision_is_made_only_after_the_refresh_lock_is_acquired(self):
        self.perl(r'''
my $idle = 0; my $locked = 0;
*session_is_active = sub { 1 };
*with_refresh_lock = sub { $idle = 1; $locked = 1; my $result = $_[0]->(); $locked = 0; $result };
*idle_topology_active = sub { die 'unlocked idle probe' unless $locked; $idle };
*idle_topology_restore_requested = sub { 0 }; *resume_output_authority = sub {};
*find_command = sub { die 'stale awake probe re-enabled sleeping display' };
run_refresh_action(q{});
''')

    def test_requested_idle_restore_uses_the_same_locked_reconcile(self):
        self.perl(r'''
*session_is_active = sub { 1 }; *idle_topology_active = sub { 1 };
*idle_topology_restore_requested = sub { 1 }; *pause_output_authority = sub {};
*find_command = sub { '/mock/wlr-randr' }; *prepare_dock_for_output_change = sub { 1 };
my $restores = 0; *restore_idle_topology = sub { $restores++; 300000 };
*capture_command = sub { die 'normal plan ran during restore' };
die 'restore lost' unless refresh_outputs(q{}) == 300000 && $restores == 1;
''')

    def test_omitted_mode_is_a_true_noop_but_changed_scale_or_position_is_not(self):
        self.perl(r'''
*scale_for_output = sub { 1 };
my $current = {enabled=>'yes', mode=>'1920x1080@60.000Hz', position=>'0,0', scale=>1};
for my $mode (undef, q{}, '1920x1080@60Hz') {
  die 'omitted/equivalent mode forced a commit' unless output_plan_is_current($current, {name=>'eDP-1', mode=>$mode, position=>'0,0'});
}
die 'changed position missed' if output_plan_is_current($current, {name=>'eDP-1', position=>'1,0'});
die 'changed mode missed' if output_plan_is_current($current, {name=>'eDP-1', mode=>'1280x720@60Hz', position=>'0,0'});
$current->{scale}=1.25;
die 'changed scale missed' if output_plan_is_current($current, {name=>'eDP-1', position=>'0,0'});
$current->{scale}=1; $current->{enabled}='no';
die 'disabled output missed' if output_plan_is_current($current, {name=>'eDP-1', position=>'0,0'});
''')

    def fixture(self):
        return r'''
*session_is_active = sub { 1 }; *idle_topology_active = sub { 0 };
*find_command = sub { '/mock/wlr-randr' }; *load_saved_topology = sub { "snapshot\n" };
*save_topology = sub {}; *scale_for_output = sub { 1 }; *usleep = sub {};
*connected_outputs = sub { 'eDP-1' };
*parse_output_topology = sub { ({name=>'eDP-1', enabled=>'yes'}) };
*topology_restart_delay_us = sub { 300000 };
*selection_plan = sub { ([{name=>'eDP-1', position=>'0,0', mode=>'1920x1080@60Hz'}], []) };
test_defaults(LABWC_ENABLE_KANSHI => 'false');
'''

    def test_steady_state_never_requeries_restarts_chrome_sleeps_or_mutates(self):
        self.perl(self.fixture()+r'''
my $queries = 0; *capture_command = sub { $queries++; "snapshot\n" };
*output_plan_is_current = sub { 1 };
*prepare_dock_for_output_change = sub { die 'unnecessary chrome stop' };
*apply_output_transaction = sub { die 'redundant output request' };
*usleep = sub { die 'unnecessary convergence delay' };
die 'no-op result' if refresh_outputs(q{});
die 'no-op repeated its inventory' unless $queries == 1;
''')

    def test_connector_change_during_dock_stop_defers_the_stale_plan(self):
        result = self.perl(self.fixture()+r'''
my $queries = 0; *capture_command = sub { ++$queries == 1 ? "snapshot\n" : "different connector\n" };
*output_plan_is_current = sub { 0 }; *prepare_dock_for_output_change = sub { 1 };
*apply_output_transaction = sub { die 'submitted stale output plan' };
die 'stale plan did not defer' if refresh_outputs(q{});
die 'missing revalidation query' unless $queries == 2;
''')
        self.assertIn('deferring stale transaction', result.stderr)

    def test_missing_snapshot_after_dock_stop_cannot_submit_a_plan(self):
        self.perl(self.fixture()+r'''
my $queries = 0; *capture_command = sub { ++$queries == 1 ? "snapshot\n" : q{} };
*output_plan_is_current = sub { 0 }; *prepare_dock_for_output_change = sub { 1 };
*apply_output_transaction = sub { die 'submitted without a live snapshot' };
refresh_outputs(q{});
''')

    def test_mutations_have_paired_bounded_monotonic_records_and_no_replay(self):
        result = self.perl(r'''
*session_is_active = sub { 1 }; my $calls = 0;
*run_command_capture_stderr = sub { ++$calls; return $calls == 1 ? (1,q{}) : (0,"busy\n"); };
die 'success lost' unless apply_output_transaction('/mock/wlr-randr', '--output', 'eDP-1', '--on');
die 'failure lost' if apply_output_transaction('/mock/wlr-randr', '--output', 'eDP-1', "\e" . ('x' x 3000));
die 'replayed command' unless $calls == 2;
''')
        begin = re.findall(r'transaction=(\d+-\d+) phase=begin monotonic=([\d.]+) command=([^\n]*)', result.stderr)
        end = re.findall(r'transaction=(\d+-\d+) phase=end monotonic=([\d.]+) result=(accepted|rejected)', result.stderr)
        self.assertEqual(len(begin), 2); self.assertEqual(len(end), 2)
        self.assertEqual([a[0] for a in begin], [a[0] for a in end])
        self.assertEqual([a[2] for a in end], ['accepted', 'rejected'])
        for start, finish in zip(begin, end):
            self.assertLessEqual(float(start[1]), float(finish[1]))
            self.assertLessEqual(len(start[2]), 1024)
        self.assertNotIn('\x1b', result.stderr)

    def test_dpms_uses_the_same_logged_bounded_mutation_path(self):
        self.perl(r'''
*find_command = sub { '/mock/wlopm' };
my @seen; *apply_output_transaction = sub { @seen = @_; 1 };
*run_quiet_command = sub { die 'unobserved DPMS request' };
die 'DPMS failed' unless run_optional('wlopm', '--off', '*');
die 'wrong DPMS request' unless join('|', @seen) eq '/mock/wlopm|--off|*';
''')

    def test_teardown_prevents_mutation_and_empty_transactions_are_read_only(self):
        self.perl(r'''
*run_command_capture_stderr = sub { die 'late/no-op mutation' };
*session_is_active = sub { 0 };
die 'teardown accepted' if apply_output_transaction('/mock', '--off');
*session_is_active = sub { 1 };
die 'empty transaction failed' unless apply_output_transaction('/mock');
''')

    def test_concurrent_processes_never_enter_the_refresh_section_together(self):
        self.perl(r'''
my $dir = File::Temp::tempdir(CLEANUP=>1); *session_state_dir = sub { $dir };
my @children;
for (1..4) {
  my $pid = fork(); defined $pid or die $!;
  if (!$pid) {
    with_refresh_lock(sub {
      sysopen(my $fh, "$dir/entered", O_WRONLY|O_CREAT|O_EXCL, 0600) or die 'overlapping output writer';
      sleep 0.04; close $fh; unlink "$dir/entered" or die $!;
    });
    POSIX::_exit(0);
  }
  push @children, $pid;
}
for (@children) { waitpid($_,0); die 'lock serialization failed' if $?; }
die 'stale lock section' if -e "$dir/entered";
''')


if __name__ == '__main__':
    unittest.main()
