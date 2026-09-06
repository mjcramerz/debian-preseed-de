package Managed::Process;

use strict;
use warnings;

use Errno qw(EAGAIN EWOULDBLOCK EINTR EPIPE ECHILD);
use Exporter qw(import);
use Fcntl qw(F_GETFL F_SETFL O_NONBLOCK);
use IO::Select;
use POSIX qw(WNOHANG);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC sleep);

our @EXPORT_OK = qw(capture_command);

sub _nonblocking {
    my ($handle) = @_;
    my $flags = fcntl($handle, F_GETFL, 0);
    defined($flags) && fcntl($handle, F_SETFL, $flags | O_NONBLOCK)
        or die "cannot configure subprocess pipe: $!\n";
}

# Synchronous, shell-free capture for non-interactive, non-daemonizing commands.
# Input/output are multiplexed; an input producer cannot deadlock behind a full
# output pipe. Deadlines use a monotonic clock and also cover inherited pipes.
# A service cgroup remains the boundary for descendants that deliberately call
# setsid() or close all streams and daemonize. Do not use this API for daemons.
sub capture_command {
    my (%args) = @_;
    my $argv = $args{argv};
    ref($argv) eq 'ARRAY' && @{$argv}
        or die "capture requires a non-empty argv array\n";
    for (@{$argv}) {
        defined($_) && !ref($_) && !/\0/ or die "invalid subprocess argument\n";
    }
    $argv->[0] =~ m{\A/} or die "capture requires an absolute executable path\n";
    my $seconds = $args{timeout} // 120;
    my $limit = $args{limit} // 1_048_576;
    !ref($seconds) && $seconds =~ /\A[0-9]+(?:\.[0-9]+)?\z/
        && $seconds > 0 && $seconds <= 172800
        or die "invalid subprocess deadline\n";
    !ref($limit) && $limit =~ /\A[1-9][0-9]*\z/ && $limit <= 16_777_216
        or die "invalid subprocess capture limit\n";
    my $input = $args{input} // q{};
    !ref($input) or die "invalid subprocess input\n";
    if (utf8::is_utf8($input)) {
        require Encode;
        $input = Encode::encode('UTF-8', $input, Encode::FB_CROAK());
    }
    length($input) <= 16_777_216 or die "subprocess input exceeds safety limit\n";

    pipe(my $in_r, my $in_w) or die "cannot create stdin pipe: $!\n";
    pipe(my $out_r, my $out_w) or die "cannot create stdout pipe: $!\n";
    pipe(my $err_r, my $err_w) or die "cannot create stderr pipe: $!\n";
    pipe(my $ready_r, my $ready_w) or die "cannot create readiness pipe: $!\n";
    # Configure before fork: a setup error cannot strand a child.
    _nonblocking($_) for ($in_w, $out_r, $err_r, $ready_r);
    my %previous = map { $_ => $SIG{$_} } qw(HUP INT TERM);
    my $interrupted;
    local $SIG{HUP} = sub { $interrupted //= 'HUP' };
    local $SIG{INT} = sub { $interrupted //= 'INT' };
    local $SIG{TERM} = sub { $interrupted //= 'TERM' };
    local $SIG{PIPE} = 'IGNORE';
    # A caller's auto-reaper must not recycle the owned PID during escalation.
    local $SIG{CHLD} = 'DEFAULT';
    my $pid = fork;
    defined($pid) or die "cannot fork subprocess: $!\n";
    if (!$pid) {
        $SIG{$_} = 'DEFAULT' for qw(HUP INT TERM PIPE CHLD);
        close $in_w; close $out_r; close $err_r; close $ready_r;
        setpgrp(0, 0) or POSIX::_exit(126);
        syswrite($ready_w, '1', 1) == 1 or POSIX::_exit(126);
        close $ready_w;
        open STDIN, '<&', $in_r or POSIX::_exit(126);
        open STDOUT, '>&', $out_w or POSIX::_exit(126);
        open STDERR, '>&', $err_w or POSIX::_exit(126);
        close $in_r; close $out_w; close $err_w;
        exec { $argv->[0] } @{$argv} or POSIX::_exit(127);
    }
    close $in_r; close $out_w; close $err_w; close $ready_w;
    my $reads = IO::Select->new($out_r, $err_r, $ready_r);
    my $writes = IO::Select->new;
    if (length($input)) { $writes->add($in_w); } else { close $in_w; }
    my %kind = (fileno($out_r) => 'stdout', fileno($err_r) => 'stderr', fileno($ready_r) => 'ready');
    my %result = (stdout => q{}, stderr => q{}, error => q{});
    my ($ready, $reaped, $status, $offset, $captured) = (0, 0, 0, 0, 0);
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + $seconds;
    my $ok = eval {
        while (1) {
            last if $interrupted;
            my $left = $deadline - clock_gettime(CLOCK_MONOTONIC);
            if ($left <= 0) { $result{error} = 'timeout'; last; }
            if (!$reads->count && !$writes->count) {
                my $waited = waitpid($pid, WNOHANG);
                if ($waited == $pid) { $status = $?; $reaped = 1; last; }
                # ECHILD means another reaper broke the ownership contract.
                # Never signal a possibly recycled PID in this situation.
                if ($waited < 0 && $! == ECHILD) { $reaped = 1; die "subprocess was reaped externally\n"; }
                die "subprocess wait failed: $!\n" if $waited < 0 && $! != EINTR;
                sleep(0.02);
                next;
            }
            $! = 0;
            my ($readable, $writable) = IO::Select->select($reads, $writes, undef, $left < 0.05 ? $left : 0.05);
            if (!defined $readable) {
                next if !$! || $! == EINTR;
                die "subprocess select failed: $!\n";
            }
            for my $fh (@{$readable}) {
                my $stream = $kind{fileno($fh)};
                my $count = sysread($fh, my $chunk, 8192);
                if (!defined $count) {
                    next if $! == EINTR || $! == EAGAIN || $! == EWOULDBLOCK;
                    die "cannot read subprocess output: $!\n";
                }
                if (!$count) { $reads->remove($fh); close $fh; next; }
                if ($stream eq 'ready') { $ready = 1; next; }
                $captured += $count;
                $captured <= $limit or die "subprocess output exceeds $limit bytes\n";
                $result{$stream} .= $chunk;
            }
            for my $fh (@{$writable}) {
                my $remaining = length($input) - $offset;
                my $count = syswrite($fh, $input, $remaining > 8192 ? 8192 : $remaining, $offset);
                if (!defined $count) {
                    next if $! == EINTR || $! == EAGAIN || $! == EWOULDBLOCK;
                    if ($! == EPIPE) { $writes->remove($fh); close $fh; next; }
                    die "cannot write subprocess input: $!\n";
                }
                $count > 0 or die "subprocess stdin made no progress\n";
                $offset += $count;
                if ($offset == length($input)) { $writes->remove($fh); close $fh; }
            }
        }
        1;
    };
    my $error = $@;
    if (!$reaped) {
        # The unreaped direct child pins its PID/PGID against reuse. Do not poll
        # waitpid between TERM and KILL: an exited leader can leave descendants.
        kill 'TERM', ($ready ? -$pid : $pid);
        sleep(0.2);
        kill 'KILL', -$pid;
        kill 'KILL', $pid;
        my $reap_deadline = clock_gettime(CLOCK_MONOTONIC) + 2;
        while (clock_gettime(CLOCK_MONOTONIC) < $reap_deadline) {
            my $waited = waitpid($pid, WNOHANG);
            if ($waited == $pid) { $status = $?; $reaped = 1; last; }
            last if $waited < 0 && $! != EINTR;
            sleep(0.02);
        }
        # Uninterruptible kernel I/O cannot be fixed in userspace. Report it;
        # systemd's cgroup cleanup is the final containment boundary.
        $error .= "subprocess could not be reaped after SIGKILL\n" if !$reaped;
    }
    close $_ for ($reads->handles, $writes->handles);
    if ($interrupted) {
        my $handler = $previous{$interrupted};
        $handler->($interrupted) if ref($handler) eq 'CODE';
        die "subprocess interrupted by $interrupted\n";
    }
    die $error if !$ok || length($error);
    $result{status} = $result{error} eq 'timeout' ? (124 << 8) : $status;
    return \%result;
}

1;
