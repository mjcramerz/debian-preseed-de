package FilenSync::Daemon;
use strict;
use warnings;
use Moo;
use MooX::StrictConstructor;
use FilenSync::Config;
use Managed::Process qw(capture_command);
use IO::Select;
use POSIX qw(WNOHANG);
use Errno qw(EINTR);
use Encode qw(encode FB_CROAK LEAVE_SRC);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC sleep);

has account => (is => 'ro', required => 1);

sub event {
    my ($self, $outcome, $cause) = @_;
    print STDERR 'filen_sync account=' . $self->account . " outcome=$outcome cause=$cause\n";
}

sub output_messages {
    my ($self, $settings) = @_;
    my $remote = encode('UTF-8', $settings->{remote}, FB_CROAK | LEAVE_SRC);
    my %messages = (
        'Syncing ' . $settings->{local} . ' to ' . $remote . ' (' . $settings->{mode} . ")...\n" => 'initializing',
        "Invalid credentials!\n" => 'authentication',
        "Invalid Two Factor Authentication code!\n" => 'authentication',
        'No such cloud file or directory: ' . $remote . "\n" => 'remote-directory',
    );
    # v0.0.36 wraps error messages in these exact ANSI sequences, even when
    # stdout is a pipe. Match complete messages, never words inside filenames.
    for my $plain (keys %messages) {
        next if $messages{$plain} eq 'initializing';
        my $colored = "\e[31m" . substr($plain, 0, -1) . "\e[0m\n";
        $messages{$colored} = $messages{$plain};
    }
    return \%messages;
}

sub run {
    my ($self) = @_;
    my $config = FilenSync::Config->new(account => $self->account);
    my ($settings, $secrets);
    eval { $settings = $config->settings; 1 } or do {
        $self->event('invalid-configuration', 'settings');
        return 78;
    };
    eval { $secrets = $config->credentials; 1 } or do {
        $self->event('invalid-configuration', 'credentials');
        return 78;
    };
    local %ENV = (PATH => '/usr/sbin:/usr/bin:/sbin:/bin', LC_ALL => 'C.UTF-8',
                  HOME => '/var/lib/filen-' . $self->account, TMPDIR => '/tmp');
    # pkgsel supplies systemd-timesyncd. Wait in this Type=simple process so
    # an offline clock cannot block the desktop boot transaction indefinitely.
    my $clock_deadline = clock_gettime(CLOCK_MONOTONIC) + 180;
    while (!-f '/run/systemd/timesync/synchronized') {
        if (clock_gettime(CLOCK_MONOTONIC) >= $clock_deadline) {
            $self->event('unavailable', 'clock-not-synchronized');
            return 1;
        }
        sleep(5);
    }
    # Avoid issuing a code at the end of its 30-second validity interval.
    my $remaining = 30 - (time % 30);
    sleep($remaining + 1) if $remaining < 5;
    my $totp = capture_command(argv => ['/usr/bin/oathtool', '--totp=SHA1', '--base32', '-'],
                               input => $secrets->{seed} . "\n", timeout => 5, limit => 256);
    # capture_command returns RAW wait status, including signal bits.
    if ($totp->{status} != 0 || $totp->{stdout} !~ /\A([0-9]{6})\n\z/) {
        $self->event('failed', 'totp-generation');
        return 1;
    }
    my $code = $1;
    pipe(my $read, my $write) or die "pipe failed\n";
    my $stopped = 0;
    local $SIG{TERM} = sub { $stopped = 1 };
    local $SIG{INT} = sub { $stopped = 1 };
    local $SIG{HUP} = sub { $stopped = 1 };
    local $SIG{CHLD} = 'DEFAULT';
    my $pid = fork;
    defined($pid) or die "fork failed\n";
    if (!$pid) {
        $SIG{$_} = 'DEFAULT' for qw(TERM INT HUP CHLD);
        close $read;
        open STDIN, '<', '/dev/null' or POSIX::_exit(126);
        open STDOUT, '>&', $write or POSIX::_exit(126);
        open STDERR, '>&', $write or POSIX::_exit(126);
        close $write;
        # Filen supports environment authentication. Only this dedicated UID's
        # child receives the password and current OTP; the seed is not forwarded
        # in that environment. Both processes use this account's credential view.
        $ENV{FILEN_EMAIL} = $secrets->{email};
        $ENV{FILEN_PASSWORD} = $secrets->{password};
        $ENV{FILEN_2FA_CODE} = $code;
        $ENV{FILEN_CLI_DATA_DIR} = '/var/lib/filen-' . $self->account;
        my $registry = '/etc/filen/' . $self->account . '.sync.json';
        exec { '/usr/local/bin/filen' } '/usr/local/bin/filen', '--skip-update', 'sync', $registry, '--continuous';
        POSIX::_exit(127);
    }
    close $write;
    # No secrets are retained in the parent's environment or event stream.
    undef $secrets; undef $code; undef $totp;
    my $selector = IO::Select->new($read);
    my $messages = $self->output_messages($settings);
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + 180;
    my ($ready, $line, $failed) = (0, q{}, 0);
    $self->event('started', 'continuous-worker');
    while (!$stopped) {
        my $waited = waitpid($pid, WNOHANG);
        if ($waited == $pid) {
            my $raw = $?;
            close $read;
            # Continuous mode must remain running; even an unexpected clean
            # worker exit is a retryable failure at this public adapter.
            $self->event('failed', ($raw & 127) ? 'worker-signal' : 'worker-exit');
            return 1;
        }
        if ($waited < 0 && $! != EINTR) {
            $self->event('outcome-unknown', 'worker-identity');
            return 79;
        }
        if (!$ready && clock_gettime(CLOCK_MONOTONIC) >= $deadline) {
            $self->event('failed', 'startup-deadline');
            last;
        }
        for my $fh ($selector->can_read(1)) {
            my $count = sysread($fh, my $chunk, 4096);
            next if !defined($count) && $! == EINTR;
            defined($count) or die "worker output failed\n";
            if (!$count) { $selector->remove($fh); next; }
            # Consume bounded chunks; never log credentials, paths, hostile
            # filenames or upstream exception text. Readiness is an upstream
            # startup observation, not a claim that a sync cycle succeeded.
            $line .= $chunk;
            while ($line =~ s/\A([^\n]*\n)//) {
                my $row = $1;
                my $event = $messages->{$row} // q{};
                if (!$ready && $event eq 'initializing') {
                    $ready = 1;
                    $self->event('running', 'sync-initializing');
                }
                if ($event eq 'authentication') {
                    $self->event('failed', 'authentication');
                    $failed = 1;
                }
                if ($event eq 'remote-directory') {
                    $self->event('unavailable', 'remote-directory');
                    $failed = 1;
                }
            }
            $line = q{} if length($line) > 8192;
        }
        sleep(1) if !$selector->count;
        last if $failed;
    }
    close $read;
    # PID 1 owns and terminates the complete service cgroup, including worker
    # descendants, on main-process exit. Never signal a recycled PID or create
    # another detached supervisor/retry loop. systemd supplies bounded cleanup.
    $self->event($stopped ? 'cancelled' : 'failed', 'service-cgroup-cleanup');
    return $stopped ? 0 : 1;
}

1;
