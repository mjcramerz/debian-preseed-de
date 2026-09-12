package WhisperMode::Runtime;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use WhisperMode::Artifacts;
use WhisperMode::Audio;
use WhisperMode::Config;
use WhisperMode::Memory;
use WhisperMode::Recorder;
use WhisperMode::State;
use WhisperMode::Systemd;
use WhisperMode::Transcriber;

has config => ( is => 'ro', lazy => 1, builder => sub { WhisperMode::Config->new() } );
has state => ( is => 'ro', lazy => 1, builder => sub { WhisperMode::State->new() } );
has artifacts => ( is => 'ro', lazy => 1, builder => sub { WhisperMode::Artifacts->new() } );
has audio => ( is => 'ro', lazy => 1, builder => sub { WhisperMode::Audio->new() } );
has systemd => ( is => 'ro', lazy => 1, builder => sub { WhisperMode::Systemd->new() } );

sub _recorder {
    my ($self) = @_;
    return WhisperMode::Recorder->new(
        artifacts => $self->artifacts(), audio => $self->audio(),
        state => $self->state(), systemd => $self->systemd(),
    );
}

sub _memory {
    my ($self) = @_;
    return WhisperMode::Memory->new(config => $self->config(), systemd => $self->systemd());
}

sub run {
    my ($self, $action) = @_;
    if ($action eq 'server-enabled') {
        return $self->_memory()->enabled() ? 0 : 1;
    }
    if ($action eq 'server-ready') {
        $self->_memory()->wait_until_ready();
        return 0;
    }
    if ($action eq 'server') {
        $self->_memory()->run_server();
        return 0;
    }
    if ($action eq 'finalize-recording') {
        my $lock = $self->state()->lock(0, 1);
        return 0 if !$lock;
        return 0 if $self->systemd()->is_active($self->systemd()->record_service());
        my $recording = $self->_recorder()->finalize();
        my $transcribe =
            defined($recording)
            && $self->systemd()->is_active($self->systemd()->session_target());
        undef $lock;
        $self->systemd()->start_transcription() if $transcribe;
        return 0;
    }
    if ($action eq 'record-worker') {
        my $lock = $self->state()->lock(0, 0);
        $self->_recorder()->record_worker(\$lock);
        return 0;
    }
    if ($action eq 'transcribe') {
        WhisperMode::Transcriber->new(
            artifacts => $self->artifacts(), config => $self->config(),
            memory => $self->_memory(), state => $self->state(),
        )->transcribe_pending();
        return 0;
    }
    if ($action eq 'mute-default-source') {
        my $lock = $self->state()->lock(0, 1);
        return 0 if !$lock;
        my $recording_guard = $self->state()->lock(1, 1);
        return 0 if !$recording_guard;
        return 0 if $self->systemd()->is_active($self->systemd()->record_service());
        my $muted = $self->audio()->set_default_source_muted(1);
        $muted or die "whisper-record-toggle: no usable audio capture source became available\n";
        return 0;
    }

    my $lock = $self->state()->lock(0, 1)
        or die "whisper-record-toggle: another control action is in progress\n";
    return 0 if $self->systemd()->is_running($self->systemd()->transcribe_service());
    my $recorder = $self->_recorder();
    my $pending = $self->state()->read();
    my $transcribe = 0;
    if ($action eq 'toggle') {
        if ($self->systemd()->is_running($self->systemd()->record_service())) {
            $transcribe = defined $recorder->stop();
        } elsif ($pending) {
            $transcribe = defined $recorder->finalize();
        } else {
            $recorder->start();
        }
    } elsif ($action eq 'start') {
        $recorder->start();
    } elsif ($action eq 'stop') {
        $transcribe = defined $recorder->stop();
    } else {
        die "whisper-record-toggle: unsupported action: $action\n";
    }
    undef $lock;
    $self->systemd()->start_transcription() if $transcribe;
    return 0;
}

1;
