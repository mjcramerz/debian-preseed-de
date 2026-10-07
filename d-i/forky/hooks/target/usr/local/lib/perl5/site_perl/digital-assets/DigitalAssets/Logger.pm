package DigitalAssets::Logger;

use strict;
use warnings;

use Exporter qw(import);
use Sys::Syslog qw(:standard :macros);

our @EXPORT_OK = qw(log_msg);

sub log_msg {
    my ($level, $message) = @_;
    my %priority = (
        info    => LOG_INFO,
        warning => LOG_WARNING,
        error   => LOG_ERR,
    );
    $level = exists $priority{$level} ? $level : 'error';
    $message = q{} if !defined $message;
    $message =~ s/[\r\n]+/ /g;
    $message =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    $message = substr($message, 0, 2048);
    return if !eval {
        openlog('labwc-digital-assets', 'pid,nowait', LOG_USER);
        syslog($priority{$level}, '%s', $message);
        closelog();
        1;
    };
}

1;
