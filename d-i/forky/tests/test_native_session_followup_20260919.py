"""Native-session output-authority and thumbnail-theme regressions.

The Perl harness executes production functions with external endpoints stubbed.
It does not start a compositor or claim live Wayland acceptance. Source-builder
and source-patcher tests were retired with those implementations on 2026-09-20.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
FORKY = ROOT / 'd-i/forky'
TARGET = FORKY / 'hooks/target'


class OutputAuthorityTests(unittest.TestCase):
    def perl(self, script):
        production = (TARGET / 'usr/local/libexec/labwc-output-watch').read_text()
        # Only skip the Moo-based CLI classes and the executable entry point.
        # The production main-package functions are not rewritten.
        main = production.split('package main;', 1)[1].split('unless (caller) {', 1)[0]
        text = ('use strict; use warnings;\npackage main;\n' + main
                + '\nsub test_defaults { %defaults = @_; }\n'
                + 'no warnings "redefine";\n' + script)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'case.pl'
            p.write_text(text)
            result = subprocess.run(['perl', '-I' + str(TARGET / 'usr/local/lib/perl5/site_perl/managed-runtime'), str(p)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_policy_does_not_fall_back_during_kanshi_activation(self):
        self.perl(r'''
*session_is_active = sub { 1 }; *find_command = sub { '/bin/mock' };
*capture_command = sub { "snapshot\n" }; *load_saved_topology = sub { "snapshot\n" };
*save_topology = sub {}; *topology_changed = sub { 0 };
*selection_plan = sub { die "competing fallback writer invoked" };
for my $v (qw(true yes 1 on)) { test_defaults(LABWC_ENABLE_KANSHI => $v); refresh_outputs(q{}); }
test_defaults(LABWC_ENABLE_KANSHI => 'garbage'); eval { kanshi_is_configured() }; die 'accepted bad policy' if !$@;
''')

    def test_default_disabled_policy_batches_fallback_and_skips_noop(self):
        self.perl(r'''
*session_is_active = sub { 1 }; *find_command = sub { '/mock/wlr-randr' };
*capture_command = sub { "snapshot\n" }; *load_saved_topology = sub { "snapshot\n" };
*save_topology = sub {}; *topology_changed = sub { 0 }; *usleep = sub {};
*connected_outputs = sub { qw(eDP-1 DP-1 HDMI-A-1) };
*topology_restart_delay_us = sub { 300000 }; *scale_for_output = sub { 1 };
my @plans = map { +{ name => $_, mode => '1920x1080@60.000Hz', position => '0,0' } } qw(eDP-1 DP-1);
*selection_plan = sub { (\@plans, ['HDMI-A-1']) };
my $current = 0;
*parse_output_topology = sub { map { +{ name => $_, enabled => $current && $_ eq 'HDMI-A-1' ? 'no' : 'yes' } } qw(eDP-1 DP-1 HDMI-A-1) };
*output_plan_is_current = sub { $current };
my $stops = 0; *prepare_dock_for_output_change = sub { $stops++; 1 };
my @calls; *apply_output_transaction = sub { push @calls, [@_]; 1 };
test_defaults(LABWC_ENABLE_KANSHI => 'false'); refresh_outputs(q{});
die 'fallback split the topology' unless @calls == 1 && $stops == 1;
my @expected = ('/mock/wlr-randr');
for (qw(eDP-1 DP-1)) { push @expected, '--output', $_, '--on', '--mode', '1920x1080@60.000Hz', '--scale', 1, '--pos', '0,0'; }
push @expected, '--output', 'HDMI-A-1', '--off';
die 'wrong fallback transaction' unless join("\0", @{$calls[0]}) eq join("\0", @expected);
@calls = (); $current = 1; refresh_outputs(q{});
die 'no-op caused modeset or dock restart' if @calls || $stops != 1;
''')

    def test_idle_noop_and_multihead_transaction(self):
        self.perl(r'''
my @outputs = map { { name => $_, enabled => 'yes', mode => '1920x1080@60.000Hz', scale => 1,
  transform => 'normal', position => '0,0', logical_size => '1920x1080' } } qw(eDP-1 DP-1);
*capture_command = sub { 'snapshot' }; *parse_output_topology = sub { @outputs };
my @transactions; *apply_output_transaction = sub { push @transactions, [@_]; 1 };
die 'noop failed' unless apply_idle_topology('/mock', \@outputs);
die 'noop issued modeset' if @transactions;
my @changed = map { +{ %$_, position => '1920,0' } } @outputs;
die 'batch failed' unless apply_idle_topology('/mock', \@changed);
die 'not one transaction' unless @transactions == 1;
my @args = @{$transactions[0]}; die 'lost head' unless grep($_ eq 'eDP-1', @args) && grep($_ eq 'DP-1', @args);
@transactions=(); $changed[1]->{name}='missing';
die 'missing head accepted' if apply_idle_topology('/mock', \@changed);
die 'partial transaction' if @transactions;
''')

    def test_pause_marker_and_stop_resume_order(self):
        self.perl(r'''
my $dir = File::Temp::tempdir(CLEANUP => 1); *topology_state_dir = sub { $dir };
*session_is_active = sub { 1 }; *find_command = sub { '/mock/systemctl' };
my $idle=0; *idle_topology_active = sub { $idle };
my @calls; *run_quiet_command = sub {
  push @calls, [@_];
  if (grep($_ eq 'stop', @_)) { die 'stop before marker' unless -f authority_pause_path(); }
  if (grep($_ eq 'start', @_)) { die 'resume before marker cleared' if -e authority_pause_path(); }
  1;
};
test_defaults(LABWC_ENABLE_KANSHI => 'true'); pause_output_authority();
die 'marker not private' if ((stat authority_pause_path())[2] & 077);
$idle=1; resume_output_authority(); die 'started while asleep' unless @calls==1;
$idle=0; resume_output_authority(); die 'not resumed' unless @calls==2;
die 'stale marker' if -e authority_pause_path();
''')

    def test_stop_failure_prevents_dpms_mutation(self):
        self.perl(r'''
my $dir = File::Temp::tempdir(CLEANUP => 1); *topology_state_dir = sub { $dir };
*session_is_active = sub { 1 }; *find_command = sub { '/mock/systemctl' };
*idle_topology_active = sub { 0 }; *run_quiet_command = sub { 0 };
*run_optional = sub { die 'power mutation after failed stop' };
test_defaults(LABWC_ENABLE_KANSHI => 'true'); eval { refresh_outputs('--dpms-off'); };
die 'failed stop not propagated' unless $@ =~ /cannot stop Kanshi/;
''')

    def test_pause_symlink_is_rejected(self):
        self.perl(r'''
my $dir = File::Temp::tempdir(CLEANUP => 1); *topology_state_dir = sub { $dir };
*session_is_active = sub { 1 }; *find_command = sub { '/mock/systemctl' };
*run_quiet_command = sub { die 'called systemctl after unsafe marker' };
symlink('/etc/passwd', "$dir/output-authority.paused") or die $!;
test_defaults(LABWC_ENABLE_KANSHI => 'true'); eval { pause_output_authority(); };
die 'symlink accepted' unless $@ =~ /cannot publish/;
''')

    def test_rejected_transaction_is_not_replayed(self):
        self.perl(r'''
*session_is_active = sub { 1 }; my $count=0;
*run_command_capture_stderr = sub { $count++; (0, "busy\nunsafe\e") };
my $warning=q{}; local $SIG{__WARN__}=sub { $warning .= $_[0] };
die 'failure lost' if apply_output_transaction('/mock', '--output', 'eDP-1', '--on');
die 'stale transaction replayed' unless $count==1;
die 'diagnostic suppressed' unless $warning =~ /busy unsafe/;
die 'unsafe control retained' if $warning =~ /\e/;
''')

    def test_kanshi_launch_respects_pause_marker(self):
        script = (TARGET / 'usr/local/libexec/labwc-kanshi').read_text()
        self.assertIn('output-authority.paused', script)
        self.assertLess(script.index('output-authority.paused'), script.index('exec "$kanshi_cmd"'))


class ThemeTests(unittest.TestCase):
    def test_native_thumbnail_emerald_uses_alpha_not_global_opacity(self):
        theme = (TARGET / 'etc/skel-desktop/.config/labwc/themerc-override').read_text()
        prefix = 'osd.window-switcher.style-thumbnail.item.active.'
        self.assertIn(prefix + 'bg.color: #50C87826', theme)
        self.assertIn(prefix + 'border.color: #50C878', theme)
        rc = ET.fromstring((TARGET / 'etc/skel-desktop/.config/labwc/rc.xml.tmpl').read_text())
        action = rc.find(".//keybind[@key='F13']/action")
        self.assertEqual(action.get('name'), 'NextWindow')
        self.assertIsNone(action.get('menu'))


if __name__ == '__main__':
    unittest.main()
