package WhisperMode::Transcriber;

use strict;
use warnings;

use File::Temp qw(tempfile);
use JSON::PP qw(encode_json);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use WhisperMode::Systemd ();
use WhisperMode::Logger qw(log_msg);

has artifacts => ( is => 'ro', required => 1 );
has config    => ( is => 'ro', required => 1 );
has memory    => ( is => 'ro', required => 1 );
has state     => ( is => 'ro', required => 1 );

sub _fatal {
    my ($message) = @_;
    die "whisper-record-toggle: $message\n";
}

sub _normalize {
    my ($text) = @_;
    $text //= q{};
    $text =~ s/[\p{Cc}\p{Cf}]+/ /gu;
    $text =~ s/\s+/ /gu;
    $text =~ s/\A\s+|\s+\z//gu;
    return $text;
}

sub _text_from_json {
    my ($data) = @_;
    my @parts;
    for my $key (qw(transcription segments)) {
        if (ref $data->{$key} eq 'ARRAY') {
            push @parts, map { ref $_ eq 'HASH' && defined($_->{text}) && !ref($_->{text}) ? $_->{text} : () } @{ $data->{$key} };
            last;
        }
    }
    push @parts, $data->{text} if !@parts && defined($data->{text}) && !ref($data->{text});
    push @parts, $data->{result}{text} if !@parts && ref($data->{result}) eq 'HASH' && defined($data->{result}{text}) && !ref($data->{result}{text});
    @parts || ref($data->{transcription}) eq 'ARRAY' || ref($data->{segments}) eq 'ARRAY'
        or _fatal('transcription JSON has no supported text field');
    return _normalize(join q{ }, @parts);
}

sub transcribe_pending {
    my ($self) = @_;
    # Separate lifetime and control locks: a 30-minute inference must not hold
    # the lock needed by UI actions or ExecStopPost microphone cleanup.
    my $guard = $self->state()->lock(1, 1) or _fatal('recording/transcription is already active');
    my $control = $self->state()->lock(0, 1) or _fatal('recording state is busy; retry transcription');
    my $recording = $self->state()->read() or return;
    my $wav = $self->artifacts()->validate_wav($recording);
    -f $wav && !-l $wav && -s $wav > 44 or _fatal('recorded WAV is missing or too small');
    undef $control;
    my $paths = $self->artifacts()->paths();
    my $published = "$paths->{transcribed}/$recording->{stem}.json";
    my ($temporary, $generated);
    local $SIG{HUP} = sub { die "transcription interrupted by HUP\n" };
    local $SIG{INT} = sub { die "transcription interrupted by INT\n" };
    local $SIG{TERM} = sub { die "transcription interrupted by TERM\n" };
    my $ok = eval {
        my $text;
        if (-e $published || -l $published) {
            # Resume an interrupted publish -> task -> state-clear transaction.
            $text = _text_from_json($self->artifacts()->read_json($published, 8 * 1024 * 1024, 'saved transcription'));
        } else {
            my $fh;
            ($fh, $temporary) = tempfile('.whisper-transcript.XXXXXX', DIR => $self->state()->runtime_directory(), UNLINK => 1);
            close $fh or _fatal("cannot close transcription temporary file: $!");
            if ($self->config()->persistent_memory_enabled()) {
                $generated = $temporary;
                $self->memory()->transcribe($wav, $generated);
            } else {
                $generated = "$temporary.json";
                my @command = (
                    $self->config()->value('WHISPER_CLI'),
                    '--model', $self->config()->value('WHISPER_MODEL'),
                    '--file', $wav, '--threads', $self->config()->thread_count(),
                    '--output-json', '--no-timestamps', '--output-file', $temporary,
                );
                my $result = WhisperMode::Systemd::run_command(1700, 8 * 1024 * 1024, @command);
                $result->{status} == 0 or _fatal('whisper-cli transcription failed: ' . WhisperMode::Systemd::_detail($result->{status}));
            }
            $text = _text_from_json($self->artifacts()->read_json($generated, 8 * 1024 * 1024, 'Whisper transcription output'));
            $self->artifacts()->store_transcript($recording->{stem}, $text);
        }
        $self->artifacts()->append_task($recording->{stem}, $text);
        $control = $self->state()->lock(0, 1) or _fatal('state is busy; commit will be retried');
        my $current = $self->state()->read();
        $current && $current->{stem} eq $recording->{stem} && $current->{wav} eq $wav
            or _fatal('recording state changed during transcription');
        $self->state()->clear();
        undef $control;
        log_msg('info', "transcribed Whisper recording $recording->{stem}");
        1;
    };
    my $error = $@;
    for my $path ($generated, $temporary) {
        next if !defined($path) || !-e $path;
        unlink $path or log_msg('warning', "cannot remove transient Whisper output: $path: $!");
    }
    die $error if !$ok;
    # Pruning is housekeeping, not part of the delivery transaction. A pruning
    # error must never undo success or delete a still-pending WAV.
    eval {
        $self->artifacts()->prune($paths->{audio}, 'wav');
        $self->artifacts()->prune($paths->{transcribed}, 'json');
        1;
    } or log_msg('warning', "Whisper artifact pruning failed: $@");
    return;
}

1;
