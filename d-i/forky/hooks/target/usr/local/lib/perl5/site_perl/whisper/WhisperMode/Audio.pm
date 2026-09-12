package WhisperMode::Audio;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(_exit WNOHANG);
use Errno qw(EINTR);
use Fcntl qw(O_RDONLY O_NOFOLLOW O_NONBLOCK);
use WhisperMode::Systemd ();
use Time::HiRes qw(sleep clock_gettime CLOCK_MONOTONIC);

has default_source_attempts => ( is => 'ro', default => sub { 20 } );
has default_source_retry_seconds => ( is => 'ro', default => sub { 0.5 } );
has wpctl_binary => ( is => 'ro', default => sub { '/usr/bin/wpctl' } );

use constant SOURCE_LIST_MAX_BYTES => 64 * 1024;

sub _fatal {
    my ($message) = @_;
    die "whisper-record-toggle: $message\n";
}

sub _command_status {
    my (@command) = @_;
    my $result = WhisperMode::Systemd::run_command(2, 65536, @command);
    $result->{status} == 0 or _fatal('audio command failed: ' . WhisperMode::Systemd::_detail($result->{status}));
    return 1;
}

sub _command_output_quietly {
    my ($self, @command) = @_;
    my $result = WhisperMode::Systemd::run_command(2, SOURCE_LIST_MAX_BYTES, @command);
    return ($result->{status} == 0, $result->{stdout});
}

sub _source_is_blocked {
    my ($name) = @_;
    my $normalized = lc($name // q{});

    return 1 if $normalized =~ /\Aalsa_output[.]/;
    return 1 if $normalized =~ /(?:\A|[.])monitor(?:[.]|\z)/;
    return 1 if $normalized =~ /hdmi/;
    return 1 if $normalized =~ /display(?:[._ -]?port)/;
    return 0;
}

sub _source_preference {
    my ($name) = @_;
    my $normalized = lc($name // q{});

    return 0 if $normalized =~ /\Aalsa_input[.](?:pci|platform|soc)-/;
    return 0 if $normalized =~ /(?:built[._ -]?in|internal)/;
    return 1 if $normalized =~ /\Aalsa_input[.]/;
    return 2;
}

sub _source_records_from_status {
    my ($self, $output) = @_;
    my @sources;
    my $in_audio = 0;
    my $in_sources = 0;
    my $order = 0;

    # Forky's WirePlumber supports `wpctl status --name`, but not the newer
    # `wpctl list` interface. Parse only the Audio Sources subtree, excluding
    # output monitors and HDMI/DisplayPort nodes even if WirePlumber has not
    # finished disabling them. Prefer internal ALSA capture over USB or
    # virtual sources; within one tier, retain the current default first.
    for my $line (split /\n/, $output) {
        $line =~ s/\r\z//;
        if (!$in_audio) {
            $in_audio = 1 if $line =~ /\AAudio\s*\z/;
            next;
        }
        if (!$in_sources) {
            last if $line =~ /\A\S/;
            $in_sources = 1 if $line =~ /\bSources:\s*\z/;
            next;
        }

        last if $line =~ /\A\S/;
        last if $line =~ /:\s*\z/ && $line !~ /[1-9][0-9]*[.]/;

        # wpctl draws the tree with UTF-8 box characters, while this pipe is a
        # byte stream. Match the numeric record independently of that prefix
        # instead of relying on the process locale to decode the tree glyphs.
        my ($prefix, $id, $name) = $line =~
            /\A(.*?)([1-9][0-9]*)[.]\s+(.+?)(?:\s+\[[^\]]*\])?\s*\z/;
        next if !defined($id) || !defined($name);
        next if _source_is_blocked($name);
        push @sources, {
            id         => $id,
            name       => $name,
            default    => index($prefix, '*') >= 0 ? 1 : 0,
            preference => _source_preference($name),
            order      => $order++,
        };
    }

    return sort {
        $a->{preference} <=> $b->{preference}
            || $b->{default} <=> $a->{default}
            || $a->{order} <=> $b->{order}
    } @sources;
}

sub _available_source_records {
    my ($self, $wpctl) = @_;
    my ($listed, $output) = $self->_command_output_quietly(
        $wpctl, 'status', '--name',
    );
    return if !$listed;

    return $self->_source_records_from_status($output);
}

sub _wait_for_source_records {
    my ($self, $wpctl) = @_;
    my $attempts = $self->default_source_attempts();
    $attempts =~ /\A[1-9][0-9]*\z/ or _fatal('invalid default source attempt count');
    my $retry_seconds = $self->default_source_retry_seconds();
    defined $retry_seconds && $retry_seconds =~ /\A(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\z/
        or _fatal('invalid default source retry interval');

    $attempts <= 120 && $retry_seconds <= 1 or _fatal('audio retry policy is excessive');
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + ($attempts * $retry_seconds || 1);
    for my $attempt (1 .. $attempts) {
        my @sources = $self->_available_source_records($wpctl);
        return @sources if @sources;
        last if clock_gettime(CLOCK_MONOTONIC) >= $deadline;
        sleep $retry_seconds if $attempt < $attempts;
    }
    return;
}

sub _wait_for_sources {
    my ($self, $wpctl) = @_;
    return map { $_->{id} } $self->_wait_for_source_records($wpctl);
}

sub _wait_for_source {
    my ($self, $wpctl) = @_;
    my @sources = $self->_wait_for_source_records($wpctl);
    return $sources[0];
}

sub _select_default_source {
    my ($self, $wpctl) = @_;
    my $source = $self->_wait_for_source($wpctl);
    defined $source
        or _fatal('no usable audio capture source became available');
    _command_status($wpctl, 'set-default', $source->{id});
    return $source;
}

sub set_default_source_muted {
    my ($self, $muted) = @_;
    $muted == 0 || $muted == 1 or _fatal('invalid microphone mute state');
    my $wpctl = $self->wpctl_binary();
    -x $wpctl && -f $wpctl or _fatal('wpctl is unavailable');
    if ($muted) {
        _command_status($wpctl, 'set-mute', '@DEFAULT_AUDIO_SOURCE@', '1');
        return 1;
    }
    my $source = $self->_select_default_source($wpctl);
    _command_status($wpctl, 'set-mute', $source->{id}, "$muted");
    return 1;
}

sub set_available_sources_muted {
    my ($self, $muted) = @_;
    $muted == 0 || $muted == 1 or _fatal('invalid microphone mute state');
    my $wpctl = $self->wpctl_binary();
    -x $wpctl && -f $wpctl or _fatal('wpctl is unavailable');
    my @source_ids = $self->_wait_for_sources($wpctl);
    @source_ids
        or _fatal('no usable audio capture source became available');

    for my $source_id (@source_ids) {
        _command_status($wpctl, 'set-mute', $source_id, "$muted");
    }
    return scalar @source_ids;
}

sub mute_recorded_source {
    my ($self, $recording) = @_;
    my $wpctl = $self->wpctl_binary();
    my $failed = q{};
    my @sources = $self->_available_source_records($wpctl);
    my $name = $recording ? ($recording->{source_name} // q{}) : q{};
    for my $source (@sources) {
        next if length($name) && $source->{name} ne $name;
        eval { _command_status($wpctl, 'set-mute', $source->{id}, '1'); 1 }
            or $failed .= $@;
    }
    # Also mute the current default, including a default changed mid-recording.
    eval { _command_status($wpctl, 'set-mute', '@DEFAULT_AUDIO_SOURCE@', '1'); 1 }
        or $failed .= $@;
    die $failed if length $failed;
    return 1;
}

sub record {
    my ($self, $destination, $recording, $state) = @_;
    my $binary = $ENV{WHISPER_PW_RECORD_BIN} // '/usr/bin/pw-record';
    -x $binary && -f $binary && $binary =~ m{\A/}
        or _fatal('pw-record is unavailable');
    my $wpctl = $self->wpctl_binary();
    -x $wpctl && -f $wpctl or _fatal('wpctl is unavailable');
    my $source = $self->_select_default_source($wpctl);
    if ($recording && $state) {
        $recording->{source_id} = $source->{id};
        $recording->{source_name} = $source->{name};
        $state->write($recording); # Durable before the microphone is unmuted.
    }
    _command_status($wpctl, 'set-mute', $source->{id}, '0');
    # wpctl's numeric IDs are control handles. pw-record targets a node.name or
    # object.serial, so use the name requested from `wpctl status --name`.
    return $self->_supervise_recording($destination, $binary,
        "--target=$source->{name}", '--rate=16000', '--channels=1',
        '--format=s16', $destination);
}

sub _completed_wav {
    my ($path) = @_;
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK or return 0;
    my @st = stat $fh;
    return 0 if !-f $fh || $st[4] != $< || $st[3] != 1 || $st[7] <= 44;
    my $header = q{};
    my $read = sysread($fh, $header, 12);
    return 0 if !defined($read) || $read != 12;
    return 0 if substr($header, 0, 4) ne 'RIFF' || substr($header, 8, 4) ne 'WAVE';
    # libsndfile finalizes RIFF's size on a graceful stop. An unfinished file
    # is not evidence that an exit status of 1 was the expected SIGINT path.
    return 0 if unpack('V', substr($header, 4, 4)) + 8 != $st[7];
    return 1;
}

sub _supervise_recording {
    my ($self, $destination, @command) = @_;
    my ($requested, $sent, $deadline, $killed) = (0, 0, 0, 0);
    local $SIG{INT} = sub { $requested = 1 };
    local $SIG{TERM} = sub { $requested = 1 };
    local $SIG{HUP} = sub { $requested = 1 };
    my $pid = fork;
    defined $pid or _fatal("cannot start pw-record: $!");
    if (!$pid) {
        $SIG{$_} = 'DEFAULT' for qw(INT TERM HUP);
        exec { $command[0] } @command or _exit(127);
    }
    my $end = clock_gettime(CLOCK_MONOTONIC) + 15;
    my $status;
    while (1) {
        my $waited = waitpid($pid, WNOHANG);
        if ($waited == $pid) { $status = $?; last; }
        if ($waited < 0) {
            next if $! == EINTR;
            _fatal("cannot wait for pw-record: $!");
        }
        my $now = clock_gettime(CLOCK_MONOTONIC);
        $requested = 1 if $now >= $end;
        if ($requested && !$sent) {
            kill 'INT', $pid;
            $sent = 1;
            $deadline = $now + 5;
        } elsif ($sent && !$killed && $now >= $deadline) {
            kill 'KILL', $pid;
            $killed = 1;
        }
        sleep 0.02;
    }
    return 1 if $status == 0 && _completed_wav($destination);
    # pw-cat versions which exit 1 after a handled SIGINT still produce a
    # finalized WAV. Accept only that intentional, bounded shutdown, never an
    # unsolicited status 1, startup failure, crash, or escalation to SIGKILL.
    return 1 if $sent && !$killed && $status == (1 << 8)
        && _completed_wav($destination);
    _fatal('pw-record failed: ' . WhisperMode::Systemd::_detail($status));
}

1;
