package WhisperMode::Memory;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Time::HiRes qw(CLOCK_MONOTONIC clock_gettime sleep);
use WhisperMode::Systemd ();
use WhisperMode::Logger qw(log_msg);

has config                       => ( is => 'ro', required => 1 );
has systemd                      => ( is => 'ro', required => 1 );
has curl_binary                  => ( is => 'ro', default => sub { '/usr/bin/curl' } );
has server_ready_retry_seconds   => ( is => 'ro', default => sub { 0.5 } );
has server_ready_timeout_seconds => ( is => 'ro', default => sub { 105 } );

use constant SERVER_HOST => '127.0.0.1';

sub _fatal {
    my ($message) = @_;
    die "whisper-record-toggle: $message\n";
}

sub enabled {
    my ($self) = @_;
    return $self->config()->persistent_memory_enabled();
}

sub _curl_binary {
    my ($self) = @_;
    my $curl = $self->curl_binary();
    defined($curl) && $curl =~ m{\A/}
        && $curl !~ m{\0|(?:\A|/)\.\.(?:/|\z)|//}
        && -x $curl && -f $curl
        or _fatal('curl is unavailable');
    return $curl;
}

sub _bounded_seconds {
    my ($label, $value, $maximum) = @_;
    defined($value) && $value =~ /\A(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\z/
        && $value <= $maximum
        or _fatal("invalid $label");
    return 0 + $value;
}

sub _server_port {
    my ($self) = @_;
    my $port = $self->config()->value('WHISPER_SERVER_PORT');
    defined($port) && $port =~ /\A[1-9][0-9]*\z/ && $port >= 1024 && $port <= 65535
        or _fatal('invalid Whisper server port');
    return 0 + $port;
}

sub _server_url {
    my ($self, $path) = @_;
    $path =~ /\A\/(?:health|inference)\z/ or _fatal('invalid Whisper server endpoint');
    return 'http://' . SERVER_HOST . ':' . $self->_server_port() . $path;
}

sub wait_until_ready {
    my ($self) = @_;
    $self->enabled() or _fatal('WHISPER_PERSISTENT_MEM must be enabled');
    my $curl = $self->_curl_binary();
    my $timeout = _bounded_seconds(
        'Whisper server readiness timeout',
        $self->server_ready_timeout_seconds(),
        110,
    );
    my $retry = _bounded_seconds(
        'Whisper server readiness retry interval',
        $self->server_ready_retry_seconds(),
        5,
    );
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + $timeout;

    while (1) {
        my @command = (
            $curl, '--disable', '--fail', '--silent', '--output', '/dev/null',
            '--noproxy', '*', '--proto', '=http',
            '--connect-timeout', '1', '--max-time', '2',
            $self->_server_url('/health'),
        );
        my $status = WhisperMode::Systemd::run_command(3, 65536, @command)->{status};
        if ($status == 0) {
            log_msg('info', 'persistent local Whisper server is ready');
            return 1;
        }

        my $remaining = $deadline - clock_gettime(CLOCK_MONOTONIC);
        last if $remaining <= 0;
        my $delay = $retry < $remaining ? $retry : $remaining;
        sleep $delay if $delay > 0;
    }

    _fatal('Whisper server did not become ready before the startup deadline');
}

sub transcribe {
    my ($self, $wav, $output) = @_;
    $self->enabled() or _fatal('persistent Whisper memory is disabled');
    $self->systemd()->is_active($self->systemd()->server_service())
        or _fatal('Whisper server is not active');
    my $curl = $self->_curl_binary();
    my $quoted_wav = $wav;
    $quoted_wav =~ s/([\\"])/\\$1/g;
    my @command = (
        $curl, '--disable', '--fail', '--silent', '--show-error',
        '--noproxy', '*', '--proto', '=http', '--connect-timeout', '10',
        '--max-time', '1700', '--request', 'POST',
        '--form', "file=\@\"$quoted_wav\";type=audio/wav",
        '--form', 'response_format=json', '--output', $output,
        $self->_server_url('/inference'),
    );
    my $status = WhisperMode::Systemd::run_command(1710, 65536, @command)->{status};
    $status == 0 or _fatal('persistent Whisper server transcription failed');
    log_msg('info', 'transcribed recording through persistent local Whisper server');
}

sub run_server {
    my ($self) = @_;
    $self->enabled() or _fatal('WHISPER_PERSISTENT_MEM must be enabled');
    my @command = (
        $self->config()->value('WHISPER_SERVER'),
        '--host', SERVER_HOST, '--port', $self->_server_port(),
        '--model', $self->config()->value('WHISPER_MODEL'),
        '--threads', $self->config()->thread_count(), '--no-timestamps',
    );
    exec { $command[0] } @command or _fatal("cannot exec Whisper server: $!");
}

1;
