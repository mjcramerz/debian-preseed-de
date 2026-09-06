package Zram::Logger;

use strict;
use warnings;

use Exporter qw(import);
use Sys::Syslog qw(:standard :macros);

our @EXPORT_OK = qw(canonical_log_level set_active_log_level log_enabled log_msg);

my %LOG_LEVEL_VALUE = (
    debug   => 10,
    info    => 20,
    warning => 30,
    error   => 40,
    none    => 99,
);

my $ACTIVE_LOG_LEVEL = canonical_log_level($ENV{ZRAM_LOG_LEVEL} // 'error');
sub canonical_log_level {
    my ($level) = @_;
    $level = lc($level // 'error');
    return 'warning' if $level eq 'warn';
    return 'error' if $level eq 'fatal';
    return exists $LOG_LEVEL_VALUE{$level} ? $level : 'error';
}

sub set_active_log_level {
    my ($level) = @_;
    $level = canonical_log_level($level);
    exists $LOG_LEVEL_VALUE{$level} or $level = 'error';
    $ACTIVE_LOG_LEVEL = $level;
}

sub log_enabled {
    my ($level) = @_;
    my $requested = canonical_log_level($level);
    return 1 if $requested eq 'error';
    return 0 if $ACTIVE_LOG_LEVEL eq 'none';
    return $LOG_LEVEL_VALUE{$requested} >= $LOG_LEVEL_VALUE{$ACTIVE_LOG_LEVEL};
}

sub _normalize_message {
    my ($message) = @_;
    $message = '' if !defined $message;
    $message = "$message";
    $message =~ s/[\r\n]+/ /g;
    $message =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    return $message;
}

sub log_msg {
    my ($level, $message) = @_;
    $level = canonical_log_level($level);
    return if !log_enabled($level);
    my %priority = (
        debug   => LOG_DEBUG,
        info    => LOG_INFO,
        warning => LOG_WARNING,
        error   => LOG_ERR,
    );
    my $line = _normalize_message($message);
    return if !eval {
        openlog('zram-writeback', 'pid,nowait', LOG_DAEMON);
        syslog($priority{$level} // LOG_ERR, '%s', $line);
        closelog();
        1;
    };
}

1;
