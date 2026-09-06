package Zram::Daemon;

use strict;
use warnings;

use Errno qw(EINTR);
use Exporter qw(import);
use Fcntl qw(F_GETFD F_SETFD FD_CLOEXEC O_NONBLOCK O_RDWR);
use IO::Handle qw();
use IO::Poll qw(POLLERR POLLHUP POLLNVAL POLLPRI);
use Time::HiRes qw(time);
use Zram::Config qw(cfg);
use Zram::Daemon::Controller;
use Zram::Error qw(fatal);
use Zram::Lock qw(try_acquire_lock);
use Zram::Logger qw(log_msg);
use Zram::Policy qw(run_maintenance);
use Zram::Pressure qw(determine_pressure_state);
use Zram::Procfs qw(proc_path);
use Zram::Tuning qw(apply_writeback_batch_size);

our @EXPORT_OK = qw(run_daemon);

# The daemon currently registers only the memory PSI "some" and "full"
# descriptors. IO::Poll keeps that bounded set simple; add Linux::Epoll only
# when the daemon gains materially broader descriptor fan-out.
sub _register_psi_trigger {
    my ($path, $kind, $stall_us, $window_us) = @_;
    return if $stall_us <= 0;

    sysopen my $fh, $path, O_RDWR | O_NONBLOCK
        or fatal("failed to open PSI trigger path $path: $!");
    my $flags = fcntl($fh, F_GETFD, 0);
    defined $flags or fatal("failed to read PSI $kind trigger descriptor flags at $path: $!");
    fcntl($fh, F_SETFD, $flags | FD_CLOEXEC)
        or fatal("failed to set close-on-exec on PSI $kind trigger at $path: $!");
    my $trigger = "$kind $stall_us $window_us\n";
    if (!print {$fh} $trigger) {
        my $error = $!;
        close $fh;
        fatal("failed to register PSI $kind trigger at $path: $error");
    }
    $fh->flush or fatal("failed to flush PSI $kind trigger at $path: $!");
    return {
        fh => $fh,
        kind => $kind,
        stall_us => $stall_us,
        window_us => $window_us,
    };
}

sub _register_triggers {
    my $path = proc_path('pressure', 'memory');
    my $window_us = cfg('ZRAM_DAEMON_PSI_WINDOW_US');
    my @triggers;

    push @triggers, _register_psi_trigger($path, 'some', cfg('ZRAM_DAEMON_PSI_SOME_STALL_US'), $window_us);
    push @triggers, _register_psi_trigger($path, 'full', cfg('ZRAM_DAEMON_PSI_FULL_STALL_US'), $window_us);
    @triggers = grep { defined $_ } @triggers;
    @triggers or fatal('zram PSI daemon requires at least one enabled memory pressure trigger');
    return @triggers;
}

sub _poll_triggers {
    my ($poll, $timeout_sec, @triggers) = @_;
    my $timeout_ms = int($timeout_sec * 1000);
    $timeout_ms = 1 if $timeout_ms < 1;
    my $ready = $poll->poll($timeout_ms);
    if (!defined $ready || $ready < 0) {
        return 0 if $! == EINTR;
        fatal("zram PSI poll failed: $!");
    }
    if ($ready > 0) {
        for my $trigger (@triggers) {
            my $events = $poll->events($trigger->{fh});
            next if !defined $events;
            if ($events & (POLLERR | POLLHUP | POLLNVAL)) {
                fatal("zram PSI $trigger->{kind} trigger became unavailable");
            }
        }
    }
    return $ready > 0 ? 1 : 0;
}

sub _run_pressure_pass {
    my ($state) = @_;
    my $lock_fh = try_acquire_lock();
    if (!defined $lock_fh) {
        log_msg('debug', "zram PSI daemon skipped $state pass because another pass is active");
        return undef;
    }
    run_maintenance(state => $state);
    return 1;
}

sub _apply_tuning_state {
    my ($state) = @_;
    my $lock_fh = try_acquire_lock();
    if (!defined $lock_fh) {
        log_msg('debug', "zram PSI daemon deferred $state iodepth update because another pass is active");
        return undef;
    }
    apply_writeback_batch_size($state);
    return 1;
}

sub run_daemon {
    return 0 if !cfg('ZRAM_DAEMON_ENABLED');
    return 0 if !cfg('ZRAM_PRESSURE_ENABLED');

    my @triggers = _register_triggers();
    my $poll = IO::Poll->new();
    for my $trigger (@triggers) {
        $poll->mask($trigger->{fh} => POLLPRI | POLLERR | POLLHUP);
        log_msg(
            'info',
            "registered zram PSI $trigger->{kind} trigger " .
            "stall_us=$trigger->{stall_us} window_us=$trigger->{window_us}"
        );
    }

    my $stop = 0;
    local $SIG{TERM} = sub { $stop = 1; };
    local $SIG{INT} = sub { $stop = 1; };

    my $controller = Zram::Daemon::Controller->new(
        pressure_cooldown_seconds => cfg('ZRAM_DAEMON_PRESSURE_COOLDOWN_SEC'),
        emergency_cooldown_seconds => cfg('ZRAM_DAEMON_EMERGENCY_COOLDOWN_SEC'),
        recovery_hysteresis_seconds => cfg('ZRAM_DAEMON_RECOVERY_HYSTERESIS_SEC'),
    );
    my $poll_timeout = cfg('ZRAM_DAEMON_POLL_TIMEOUT_SEC');

    log_msg('info', 'zram PSI daemon started');
    while (!$stop) {
        my $event = _poll_triggers($poll, $poll_timeout, @triggers);
        last if $stop;

        my $now = time;
        my ($state, $reasons) = determine_pressure_state();
        my $decision = $controller->observe($now, $state);
        if ($state eq 'normal') {
            if ($decision->{recovered}) {
                log_msg('info', 'zram PSI daemon recovered to normal pressure state');
            }
            if (defined $decision->{tune}) {
                my $tuning_applied = _apply_tuning_state($decision->{tune});
                $controller->tuning_applied($decision->{tune})
                    if defined $tuning_applied;
            } elsif ($event && $controller->last_state() ne 'normal') {
                log_msg('debug', 'zram PSI daemon ignored event below pressure thresholds');
            }
            next;
        }

        if (defined $decision->{tune}) {
            my $tuning_applied = _apply_tuning_state($decision->{tune});
            $controller->tuning_applied($decision->{tune})
                if defined $tuning_applied;
        }
        if (!$decision->{run}) {
            log_msg(
                'debug',
                'zram PSI daemon suppressed ' . $state .
                ' pass inside cooldown reason=' . join('; ', @{$reasons || []})
            );
            next;
        }

        log_msg(
            'info',
            'zram PSI daemon dispatching ' . $state .
            ' pass source=' . ($event ? 'psi' : 'periodic') .
            ' reason=' . join('; ', @{$reasons || []}),
        );
        my $pass_ran = _run_pressure_pass($state);
        if (defined $pass_ran) {
            $controller->pass_completed($state, time);
        }
    }
    log_msg('info', 'zram PSI daemon stopped');
    return 0;
}

1;
