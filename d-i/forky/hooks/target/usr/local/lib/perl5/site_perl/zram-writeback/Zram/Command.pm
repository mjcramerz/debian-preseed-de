package Zram::Command;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Command::Apply qw();
use Zram::Command::Metrics qw();
use Zram::Command::Reset qw();
use Zram::Command::Status qw();
use Zram::Command::Writeback qw();
use Zram::Daemon qw(run_daemon);
use Zram::Error qw(fatal);
use Zram::Policy qw(run_maintenance);

our @EXPORT_OK = qw(dispatch requires_lock requires_sysfs);

sub _canonical_action {
    my ($action) = @_;
    return 'maintenance' if $action eq 'run';
    return 'maintenance' if $action eq 'idle';
    return 'maintenance' if $action eq 'idle-writeback';
    return 'maintenance' if $action eq 'cold-tier';
    return 'writeback-spec' if $action eq 'writeback';
    return 'metrics' if $action eq 'snapshot';
    return $action;
}

sub requires_lock {
    my ($action) = @_;
    $action = _canonical_action($action);
    return 0 if $action eq 'status';
    return 0 if $action eq 'validate-runtime';
    return 0 if $action eq 'daemon';
    return 1;
}

sub requires_sysfs {
    my ($action) = @_;
    $action = _canonical_action($action);
    return 0 if $action eq 'status';
    return 0 if $action eq 'reset-state';
    return 1;
}

sub dispatch {
    my ($action, @args) = @_;
    my $canonical = _canonical_action($action);
    if ($canonical eq 'maintenance') {
        my %opts;
        if (@args) {
            my $arg = shift @args;
            $arg =~ /\A--state=(normal|pressure|emergency)\z/
                or fatal("usage: zram-writeback $action [--state=normal|pressure|emergency]");
            $opts{state} = $1;
            @args and fatal("usage: zram-writeback $action [--state=normal|pressure|emergency]");
        }
        run_maintenance(%opts);
        return 0;
    }
    if ($canonical eq 'metrics') {
        my $print = $action eq 'metrics' ? 1 : 0;
        return Zram::Command::Metrics::run($action eq 'snapshot' ? 'snapshot' : 'metrics', $print);
    }
    if ($canonical eq 'writeback-spec') {
        return Zram::Command::Writeback::run(@args);
    }
    if ($canonical eq 'status') {
        return Zram::Command::Status::run(@args);
    }
    if ($canonical eq 'validate-runtime') {
        @args and fatal('usage: zram-writeback validate-runtime');
        return 0;
    }
    if ($canonical eq 'apply') {
        return Zram::Command::Apply::run(@args);
    }
    if ($canonical eq 'daemon') {
        @args and fatal('usage: zram-writeback daemon');
        return run_daemon();
    }
    if ($canonical eq 'reset-state') {
        return Zram::Command::Reset::run(@args);
    }
    fatal("unknown zram-writeback command: $action");
}

1;
