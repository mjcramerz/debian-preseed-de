package WhisperMode::CLI;

use strict;
use warnings;

use WhisperMode::Logger qw(log_msg);
use WhisperMode::Runtime;

sub _run {
    my ($class, @argv) = @_;
    if (@argv == 1 && $argv[0] eq '--help') {
        print STDERR "usage: whisper-record-toggle [start|stop|toggle|mute-default-source|finalize-recording|record-worker|transcribe|server-enabled|server-ready|server]\n";
        return 0;
    }
    @argv <= 1 or die "whisper-record-toggle: usage: whisper-record-toggle [start|stop|toggle|mute-default-source|finalize-recording|record-worker|transcribe|server-enabled|server-ready|server]\n";
    my $action = $argv[0] // 'toggle';
    $action =~ /\A(?:start|stop|toggle|mute-default-source|finalize-recording|record-worker|transcribe|server-enabled|server-ready|server)\z/
        or die "whisper-record-toggle: invalid action\n";
    return WhisperMode::Runtime->new()->run($action);
}

sub run {
    my ($class, @argv) = @_;
    umask 0077;
    my $status = eval { $class->_run(@argv) };
    my $error = $@;
    if (length $error) {
        my $message = $error;
        $message =~ s/[\r\n]+\z//;
        log_msg('error', $message);
        die $error;
    }
    return $status;
}

1;
