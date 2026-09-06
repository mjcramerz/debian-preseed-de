package WhisperMode::Logger;

use strict;
use warnings;

use Exporter qw(import);
use Sys::Syslog qw(:standard :macros);

our @EXPORT_OK = qw(log_msg);

my %PRIORITY = (
    debug   => LOG_DEBUG,
    info    => LOG_INFO,
    warning => LOG_WARNING,
    error   => LOG_ERR,
);

sub log_msg {
    my ($level, $message) = @_;
    $level = exists $PRIORITY{$level} ? $level : 'error';
    $message = q{} if !defined $message;
    $message =~ s/[\r\n]+/ /g;
    $message =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    $message = substr($message, 0, 2048);

    return if !eval {
        openlog('whisper-record-toggle', 'pid,nowait', LOG_USER);
        syslog($PRIORITY{$level}, '%s', $message);
        closelog();
        1;
    };
}

1;
