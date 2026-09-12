package AndroidADB::Command;

use strict;
use warnings;

use lib '/usr/local/lib/perl5/site_perl/managed-runtime';
use Managed::Process ();

use Errno qw(EINTR);
use Fcntl qw(O_CREAT O_EXCL O_NOFOLLOW O_TRUNC O_WRONLY);
use IO::Select;
use IPC::Open3 qw(open3);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX ();
use Symbol qw(gensym);
use Types::Standard qw(Int Object);

use AndroidADB::Validation qw(fail require_value);

has config => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has capture_limit_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 8 * 1024 * 1024 },
);

sub run {
    my ($self, $timeout_seconds, @argv) = @_;
    return $self->run_signal('TERM', 5, $timeout_seconds, @argv);
}

sub run_signal {
    my ($self, $signal, $kill_after_seconds, $timeout_seconds, @argv) = @_;
    my @command = $self->_timeout_argv(
        $signal,
        $kill_after_seconds,
        $timeout_seconds,
        @argv,
    );
    return $self->_system_status(@command);
}

sub run_unbounded {
    my ($self, @argv) = @_;
    $self->_validate_argv(@argv);
    return $self->_system_status($self->_client_argv(@argv));
}

sub _client_argv {
    my ($self, @argv) = @_;
    my $adb = $self->config->tool('adb');
    if (defined($adb) && $argv[0] eq $adb && ($argv[1] // q{}) ne '-H') {
        # All managed client commands use the explicit remote-client path.
        # A server crash between a health check and the actual operation must
        # not implicitly spawn a replacement daemon outside the owning unit.
        splice @argv, 1, 0, '-H', '127.0.0.1', '-P', $self->config->adb_server_port;
    }
    return @argv;
}

sub run_quiet {
    my ($self, $timeout_seconds, @argv) = @_;
    return $self->run_quiet_signal('TERM', 5, $timeout_seconds, @argv);
}

sub run_quiet_signal {
    my ($self, $signal, $kill_after_seconds, $timeout_seconds, @argv) = @_;
    my @command = $self->_timeout_argv(
        $signal,
        $kill_after_seconds,
        $timeout_seconds,
        @argv,
    );
    return $self->_fork_exec(
        \@command,
        stdout_path => '/dev/null',
        stderr_path => '/dev/null',
    );
}

sub capture {
    my ($self, $timeout_seconds, @argv) = @_;
    return $self->capture_signal('TERM', 5, $timeout_seconds, @argv);
}

sub capture_signal {
    my ($self, $signal, $kill_after_seconds, $timeout_seconds, @argv) = @_;
    my @command = $self->_timeout_argv(
        $signal,
        $kill_after_seconds,
        $timeout_seconds,
        @argv,
    );
    return $self->_capture(@command);
}

sub run_to_file {
    my ($self, $timeout_seconds, $stdout_path, $stderr_path, @argv) = @_;
    return $self->run_to_file_signal(
        'TERM',
        5,
        $timeout_seconds,
        $stdout_path,
        $stderr_path,
        @argv,
    );
}

sub run_to_file_signal {
    my (
        $self,
        $signal,
        $kill_after_seconds,
        $timeout_seconds,
        $stdout_path,
        $stderr_path,
        @argv,
    ) = @_;
    my @command = $self->_timeout_argv(
        $signal,
        $kill_after_seconds,
        $timeout_seconds,
        @argv,
    );
    return $self->_fork_exec(
        \@command,
        stdout_path => $stdout_path,
        stderr_path => $stderr_path,
        exclusive   => 1,
    );
}

sub _timeout_argv {
    my ($self, $signal, $kill_after_seconds, $timeout_seconds, @argv) = @_;
    require_value(
        (
            defined($timeout_seconds)
                && !!($timeout_seconds =~ /\A[1-9][0-9]*\z/)
        ),
        'Android command timeout must be a positive integer',
    );
    require_value(
        (
            defined($kill_after_seconds)
                && !!($kill_after_seconds =~ /\A[1-9][0-9]*\z/)
        ),
        'Android command kill-after timeout must be a positive integer',
    );
    require_value(
        (defined($signal) && !!($signal =~ /\A(?:TERM|INT)\z/)),
        'Android command timeout signal is invalid',
    );
    $self->_validate_argv(@argv);
    return (
        $self->config->require_tool('timeout'),
        "--signal=$signal",
        "--kill-after=${kill_after_seconds}s",
        "${timeout_seconds}s",
        $self->_client_argv(@argv),
    );
}

sub _validate_argv {
    my ($self, @argv) = @_;
    require_value(@argv > 0, 'Android command is missing');
    require_value(
        (defined($argv[0]) && !ref($argv[0]) && !!($argv[0] =~ m{\A/})),
        'Android command executable must be an absolute path',
    );
    for my $argument (@argv) {
        require_value(
            (defined($argument) && !ref($argument) && !!($argument !~ /\0/)),
            'Android command contains an invalid argument',
        );
    }
    return 1;
}

sub _system_status {
    my ($self, @argv) = @_;
    $self->_validate_argv(@argv);
    return $self->_fork_exec(\@argv);
}

# A bounded, shell-free subprocess with its own process group. Pipes are plain
# pipe/fork handles: closing them cannot unexpectedly waitpid like open '-|'.
# Capture limits and wall-clock limits also cover descendants retaining pipes.
sub run_command {
    my ($seconds, $limit, @argv) = @_;
    defined($seconds) && !ref($seconds) && $seconds =~ /\A[0-9]+(?:\.[0-9]+)?\z/
        && $seconds > 0 && $seconds <= 172800
        or die "invalid subprocess deadline\n";
    return Managed::Process::capture_command(
        argv => \@argv, timeout => $seconds, limit => $limit,
    );
}

sub _capture {
    my ($self, @argv) = @_;
    $self->_validate_argv(@argv);
    # _capture receives the GNU timeout command constructed above. The outer
    # deadline also bounds pipes retained after timeout's immediate child exits.
    my ($seconds) = $argv[3] =~ /\A([1-9][0-9]*)s\z/;
    my ($grace) = $argv[2] =~ /\A--kill-after=([1-9][0-9]*)s\z/;
    defined($seconds) && defined($grace) or fail('invalid bounded capture invocation');
    my $result = run_command($seconds + $grace + 2, $self->capture_limit_bytes, @argv);
    $result->{status} = _normalize_status($result->{status});
    return $result;
}

sub _fork_exec {
    my ($self, $argv, %options) = @_;
    $self->_validate_argv(@{$argv});
    require Time::HiRes;
    # GNU timeout creates its own group. Establish it before exec so a signal
    # during startup cannot leave a bounded command or its children behind.
    # Interactive, explicitly unbounded ADB shells retain the foreground
    # terminal group; putting those in a background group causes SIGTTIN.
    my $group = @{$argv} >= 4 && $argv->[1] =~ /\A--signal=(?:TERM|INT)\z/;
    my $interrupted;
    my %previous = map { $_ => $SIG{$_} } qw(HUP INT TERM);
    local $SIG{HUP} = sub { $interrupted //= 'HUP' };
    local $SIG{INT} = sub { $interrupted //= 'INT' };
    local $SIG{TERM} = sub { $interrupted //= 'TERM' };
    my $pid = fork();
    defined($pid) or fail("unable to fork Android command: $!");
    if (!$pid) {
        $SIG{$_} = 'DEFAULT' for qw(HUP INT TERM PIPE);
        setpgrp(0, 0) or POSIX::_exit(126) if $group;
        _redirect_handle('STDOUT', $options{stdout_path}, $options{exclusive} // 0);
        _redirect_handle('STDERR', $options{stderr_path}, $options{exclusive} // 0);
        exec { $argv->[0] } @{$argv} or POSIX::_exit(127);
    }
    my $status;
    while (1) {
        # Never reap before escalation: a reaped PID may already be reused.
        if ($interrupted) {
            kill $interrupted, ($group ? -$pid : $pid);
            kill $interrupted, $pid;
            Time::HiRes::sleep(0.2);
            kill 'KILL', -$pid if $group;
            kill 'KILL', $pid;
            while (1) {
                my $waited = waitpid($pid, 0);
                next if $waited < 0 && $! == EINTR;
                last;
            }
            my $handler = $previous{$interrupted};
            $handler->($interrupted) if ref($handler) eq 'CODE';
            return 128 + ({HUP => 1, INT => 2, TERM => 15}->{$interrupted});
        }
        my $waited = waitpid($pid, POSIX::WNOHANG());
        if ($waited == $pid) { $status = $?; last; }
        fail("unable to wait for Android command: $!") if $waited < 0 && $! != EINTR;
        Time::HiRes::sleep(0.05);
    }
    return _normalize_status($status);
}

sub _redirect_handle {
    my ($name, $path, $exclusive) = @_;
    return if !defined($path);

    my $flags = O_WRONLY;
    if ($path eq '/dev/null') {
        open my $null, '>', '/dev/null'
            or POSIX::_exit(127);
        if ($name eq 'STDOUT') {
            open STDOUT, '>&', $null
                or POSIX::_exit(127);
        }
        else {
            open STDERR, '>&', $null
                or POSIX::_exit(127);
        }
        return;
    }

    $flags |= O_CREAT;
    $flags |= $exclusive ? O_EXCL : O_TRUNC;
    $flags |= O_NOFOLLOW if O_NOFOLLOW;
    sysopen my $file, $path, $flags, 0600
        or POSIX::_exit(127);
    if ($name eq 'STDOUT') {
        open STDOUT, '>&', $file
            or POSIX::_exit(127);
    }
    else {
        open STDERR, '>&', $file
            or POSIX::_exit(127);
    }
}

sub _terminate_child {
    my ($self, $pid) = @_;
    kill 'TERM', $pid;
    select undef, undef, undef, 0.2;
    kill 'KILL', $pid;
    while (waitpid($pid, 0) < 0) { last if $! != EINTR; }
    return;
}

sub _normalize_status {
    my ($status) = @_;
    return 255 if !defined($status) || $status == -1;
    return 128 + ($status & 127) if $status & 127;
    return $status >> 8;
}

1;
