package AppArmor::ManagedModes::Logger;

use strict;
use warnings;

use Exporter qw(import);
use Sys::Syslog qw(:standard :macros);

our @EXPORT_OK = qw(log_msg);

my %PRIORITY = (
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
        openlog('apparmor-managed-modes', 'pid,nowait', LOG_DAEMON);
        syslog($PRIORITY{$level}, '%s', $message);
        closelog();
        1;
    };
}

1;
