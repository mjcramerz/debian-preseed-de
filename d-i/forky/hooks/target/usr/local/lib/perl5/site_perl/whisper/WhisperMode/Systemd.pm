package WhisperMode::Systemd;

use strict;
use warnings;

use lib '/usr/local/lib/perl5/site_perl/managed-runtime';
use Managed::Process ();

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
    defined($seconds) && !ref($seconds) && $seconds =~ /\A[0-9]+(?:\.[0-9]+)?\z/
        && $seconds > 0 && $seconds <= 3600
        or die "invalid subprocess deadline\n";
    return Managed::Process::capture_command(
        argv => \@argv, timeout => $seconds, limit => $limit,
    );
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
