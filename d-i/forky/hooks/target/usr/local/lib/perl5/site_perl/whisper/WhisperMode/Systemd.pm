package WhisperMode::Systemd;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Time::HiRes qw(sleep clock_gettime CLOCK_MONOTONIC);

has record_service     => ( is => 'ro', default => sub { 'whisper-record.service' } );
has transcribe_service => ( is => 'ro', default => sub { 'whisper-transcribe.service' } );
has server_service     => ( is => 'ro', default => sub { 'whisper-server.service' } );
has session_target     => ( is => 'ro', default => sub { 'labwc-session.target' } );

sub _fatal {
    my ($message) = @_;
    die "whisper-record-toggle: $message\n";
}

# A bounded, shell-free subprocess with its own process group. Pipes are plain
# pipe/fork handles: closing them cannot unexpectedly waitpid like open '-|'.
# Capture limits and wall-clock limits also cover descendants retaining pipes.
sub run_command {
    my ($seconds, $limit, @argv) = @_;
    require IO::Select;
    require POSIX;
    require Time::HiRes;
    require Errno;
    defined($seconds) && $seconds > 0 && $seconds <= 3600
        or die "invalid subprocess deadline\n";
    defined($limit) && $limit >= 1 && $limit <= 16 * 1024 * 1024
        or die "invalid subprocess capture limit\n";
    @argv && defined($argv[0]) && $argv[0] =~ m{\A/}
        or die "subprocess requires an absolute executable path\n";
    for (@argv) {
        defined($_) && !ref($_) && !/\0/ or die "invalid subprocess argument\n";
    }
    pipe(my $out_r, my $out_w) or die "cannot create stdout pipe: $!\n";
    pipe(my $err_r, my $err_w) or die "cannot create stderr pipe: $!\n";
    pipe(my $ready_r, my $ready_w) or die "cannot create process readiness pipe: $!\n";
    my $interrupted;
    my %previous = map { $_ => $SIG{$_} } qw(HUP INT TERM);
    local $SIG{HUP} = sub { $interrupted //= 'HUP' };
    local $SIG{INT} = sub { $interrupted //= 'INT' };
    local $SIG{TERM} = sub { $interrupted //= 'TERM' };
    my $pid = fork;
    defined($pid) or die "cannot fork subprocess: $!\n";
    if (!$pid) {
        $SIG{$_} = 'DEFAULT' for qw(HUP INT TERM PIPE);
        close $out_r; close $err_r; close $ready_r;
        setpgrp(0, 0) or POSIX::_exit(126);
        syswrite($ready_w, '1', 1) == 1 or POSIX::_exit(126);
        close $ready_w;
        open STDIN, '<', '/dev/null' or POSIX::_exit(126);
        open STDOUT, '>&', $out_w or POSIX::_exit(126);
        open STDERR, '>&', $err_w or POSIX::_exit(126);
        close $out_w; close $err_w;
        exec { $argv[0] } @argv or POSIX::_exit(127);
    }
    close $out_w; close $err_w; close $ready_w;
    my $select = IO::Select->new($out_r, $err_r, $ready_r);
    my %kind = (fileno($out_r) => 'stdout', fileno($err_r) => 'stderr', fileno($ready_r) => 'ready');
    my %result = (stdout => q{}, stderr => q{});
    my ($group_ready, $reaped, $status, $failure) = (0, 0, 0, q{});
    my $deadline = Time::HiRes::clock_gettime(Time::HiRes::CLOCK_MONOTONIC()) + $seconds;
    my $ok = eval {
        while (1) {
            if ($interrupted) { $failure = "interrupted by $interrupted"; last; }
            my $left = $deadline - Time::HiRes::clock_gettime(Time::HiRes::CLOCK_MONOTONIC());
            if ($left <= 0) { $failure = 'timeout'; last; }
            for my $fh ($select->can_read($left < 0.1 ? $left : 0.1)) {
                my $read = sysread($fh, my $chunk, 8192);
                if (!defined $read) {
                    next if $! == Errno::EINTR();
                    die "cannot read subprocess output: $!\n";
                }
                if (!$read) { $select->remove($fh); close $fh; next; }
                my $stream = $kind{fileno($fh)};
                if ($stream eq 'ready') { $group_ready = 1; next; }
                $result{$stream} .= $chunk;
                length($result{stdout}) + length($result{stderr}) <= $limit
                    or die "subprocess output exceeded $limit bytes\n";
            }
            if (!$select->count) {
                my $waited = waitpid($pid, POSIX::WNOHANG());
                if ($waited == $pid) { $status = $?; $reaped = 1; last; }
                die "subprocess wait failed: $!\n" if $waited < 0 && $! != Errno::EINTR();
                Time::HiRes::sleep(0.02);
            }
        }
        1;
    };
    my $error = $@;
    if (!$reaped) {
        # The direct child has not been reaped, so its PID/process-group ID
        # cannot be recycled while escalation is in progress.
        kill 'TERM', ($group_ready ? -$pid : $pid);
        Time::HiRes::sleep(0.2);
        # If interruption happened before the handshake, terminate both the
        # child and any group it managed to establish in the meantime.
        kill 'KILL', -$pid;
        kill 'KILL', $pid;
        while (1) {
            my $waited = waitpid($pid, 0);
            next if $waited < 0 && $! == Errno::EINTR();
            $status = $? if $waited == $pid;
            last;
        }
    }
    close $_ for $select->handles;
    die $error if !$ok;
    if ($interrupted) {
        my $handler = $previous{$interrupted};
        $handler->($interrupted) if ref($handler) eq 'CODE';
        die "subprocess interrupted by $interrupted\n";
    }
    $result{status} = $failure eq 'timeout' ? (124 << 8) : $status;
    $result{error} = $failure;
    return \%result;
}

sub _run {
    my ($self, @arguments) = @_;
    my $result = run_command(25, 65536, '/usr/bin/systemctl', '--user', @arguments);
    print STDERR $result->{stderr} if length $result->{stderr};
    return $result->{status};
}

sub _detail {
    my ($status) = @_;
    return "exec error: $!" if $status == -1;
    return 'terminated by signal ' . ($status & 127) if $status & 127;
    return 'exit status ' . ($status >> 8);
}

sub _active_state {
    my ($self, $service, $seconds) = @_;
    my $result = run_command($seconds // 3, 4096, '/usr/bin/systemctl', '--user',
        'show', '--property=ActiveState', '--value', $service);
    $result->{status} == 0 or _fatal("cannot query state for $service");
    my $state = $result->{stdout};
    $state =~ s/\s+\z//;
    $state =~ /\A(?:active|activating|inactive|deactivating|failed|reloading|refreshing|maintenance)\z/
        or _fatal("invalid state returned for $service");
    return $state;
}
sub is_active { my ($self, $service) = @_; return $self->_active_state($service) eq 'active'; }
sub is_running {
    my ($self, $service) = @_;
    return $self->_active_state($service) =~ /\A(?:active|activating|deactivating|reloading|refreshing)\z/ ? 1 : 0;
}
sub is_failed { my ($self, $service) = @_; return $self->_active_state($service) eq 'failed'; }

sub _reset_failed_if_needed {
    my ($self, $service) = @_;
    return if !$self->is_failed($service);
    my $status = $self->_run('reset-failed', $service);
    $status == 0
        or _fatal("cannot reset failed state for $service: " . _detail($status));
}

sub start_recording {
    my ($self) = @_;
    $self->is_active($self->session_target())
        or _fatal('cannot start recording while the Labwc session is stopping');
    $self->_reset_failed_if_needed($self->record_service());
    $self->is_active($self->session_target())
        or _fatal('cannot start recording while the Labwc session is stopping');
    my $status = $self->_run('start', $self->record_service());
    return if $status == 0 && $self->wait_active($self->record_service(), 50);
    _fatal('cannot start recording service: ' . _detail($status));
}

sub stop_recording {
    my ($self) = @_;
    my $status = $self->_run('stop', $self->record_service());
    $status == 0 or _fatal('cannot stop recording service: ' . _detail($status));
    $self->wait_inactive($self->record_service(), 50)
        or _fatal('recording service did not stop within 5 seconds');
}

sub start_transcription {
    my ($self) = @_;
    return if !$self->is_active($self->session_target());
    $self->_reset_failed_if_needed($self->transcribe_service());
    return if !$self->is_active($self->session_target());
    my $status = $self->_run('--no-block', 'start', $self->transcribe_service());
    $status == 0 or _fatal('cannot start transcription service: ' . _detail($status));
}

sub _wait_state {
    my ($self, $service, $attempts, $active) = @_;
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + $attempts * 0.1;
    while (1) {
        my $remaining = $deadline - clock_gettime(CLOCK_MONOTONIC);
        return 0 if $remaining <= 0;
        my $state = $self->_active_state($service, $remaining < 3 ? $remaining : 3);
        return 1 if $active ? $state eq 'active' : $state =~ /\A(?:inactive|failed)\z/;
        return 0 if $active && $state eq 'failed';
        sleep 0.1;
    }
}
sub wait_active { my ($self, $service, $attempts) = @_; return $self->_wait_state($service, $attempts, 1); }
sub wait_inactive { my ($self, $service, $attempts) = @_; return $self->_wait_state($service, $attempts, 0); }

1;
