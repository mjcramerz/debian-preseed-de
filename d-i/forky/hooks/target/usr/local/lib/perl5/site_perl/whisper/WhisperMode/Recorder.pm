package WhisperMode::Recorder;

use strict;
use warnings;

use Fcntl qw(O_CREAT O_EXCL O_NOFOLLOW O_WRONLY);
use POSIX qw(strftime);
use Time::HiRes qw(sleep);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use WhisperMode::Logger qw(log_msg);

has artifacts => ( is => 'ro', required => 1 );
has audio     => ( is => 'ro', required => 1 );
has state     => ( is => 'ro', required => 1 );
has systemd   => ( is => 'ro', required => 1 );

sub _fatal {
    my ($message) = @_;
    die "whisper-record-toggle: $message\n";
}

sub _stem {
    my ($self, $directory) = @_;
    for (1 .. 3) {
        my $stem = strftime('%Y-%m-%d-%H-%M-%S', localtime);
        my $path = "$directory/$stem.wav";
        if (sysopen my $reservation, $path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600) {
            close $reservation or _fatal("cannot close recording reservation: $!");
            return $stem;
        }
        $!{EEXIST} or _fatal("cannot reserve a recording: $!");
        sleep 1;
    }
    _fatal('could not create a collision-free recording name');
}

sub start {
    my ($self) = @_;
    my $paths = $self->artifacts()->paths();
    my $existing = $self->state()->read();
    if ($self->systemd()->is_running($self->systemd()->record_service())) {
        $existing or _fatal('recording service is running without managed runtime state');
        $self->artifacts()->validate_wav($existing);
        return; # Repeated start must not reselect or unmute another device.
    }
    if ($existing) {
        my $wav = $self->artifacts()->validate_wav($existing);
        -s $wav > 44 and _fatal('a completed recording is pending transcription');
        $self->audio()->mute_recorded_source($existing);
        $self->state()->clear();
    }
    my $record_guard = $self->state()->lock(1, 1)
        or _fatal('recording or transcription is already in progress');
    my $stem = $self->_stem($paths->{audio});
    my $recording = { stem => $stem, wav => "$paths->{audio}/$stem.wav" };
    # Only record-worker unmutes, after both state and the selected source are
    # durably recorded. Release the lifetime guard before starting the worker.
    undef $record_guard;
    my $ok = eval {
        $self->state()->write($recording);
        $self->systemd()->start_recording();
        1;
    };
    if (!$ok) {
        my $error = $@ || 'unknown recorder failure';
        my $stopped = eval { $self->systemd()->stop_recording(); 1 };
        eval { $self->audio()->mute_recorded_source($recording) };
        # Keep recoverable state if cancellation of the start job failed.
        if ($stopped && -f $recording->{wav} && !-l $recording->{wav}
                && -s $recording->{wav} <= 44) {
            eval { $self->state()->clear() };
            unlink $recording->{wav};
        }
        # A worker may have captured useful audio before readiness failed.
        # Keep its state and WAV available for an explicit transcription retry.
        die $error;
    }
    log_msg('info', "started Whisper recording $stem");
}

sub stop {
    my ($self) = @_;
    my $ok = eval { $self->systemd()->stop_recording(); 1 };
    if (!$ok) {
        my $error = $@;
        eval { $self->audio()->mute_recorded_source($self->state()->read()) };
        # Never transcribe/clear a file which a recorder may still be writing.
        die $error;
    }
    return $self->finalize();
}

sub finalize {
    my ($self) = @_;
    my $guard = $self->state()->lock(1, 1)
        or _fatal('cannot finalize while recording or transcription owns the WAV');
    my $recording = $self->state()->read();
    $self->audio()->mute_recorded_source($recording);
    return undef if !$recording;
    my $wav = $self->artifacts()->validate_wav($recording);
    if (!-f $wav || -l $wav || -s $wav <= 44) {
        $self->state()->clear();
        return undef;
    }
    log_msg('info', "stopped Whisper recording $recording->{stem}");
    return $recording;
}

sub record_worker {
    my ($self, $control_guard) = @_;
    my $recording = $self->state()->read()
        or _fatal('recorder service started without managed runtime state');
    my $guard = $self->state()->lock(1, 1)
        or _fatal('a Whisper recording is already active');
    my $wav = $self->artifacts()->validate_wav($recording);
    # The supervisor no longer execs: release the control lock explicitly once
    # the recording lock is held, otherwise a stop action deadlocks behind it.
    undef ${$control_guard} if ref($control_guard) eq 'GLOB' || ref($control_guard) eq 'REF' || ref($control_guard) eq 'SCALAR';
    $self->audio()->record($wav, $recording, $self->state());
}

1;
