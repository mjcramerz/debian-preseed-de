package TimeshiftManaged::Logger;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Sys::Syslog qw(:standard :macros);
use Types::Standard qw(Str);

has tag => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

sub log {
    my ($self, $level, $message) = @_;

    my %priority = (
        debug   => LOG_DEBUG,
        info    => LOG_INFO,
        warning => LOG_WARNING,
        error   => LOG_ERR,
    );
    $level = exists $priority{$level} ? $level : 'error';
    $message = q{} if !defined $message;
    $message = "$message";
    $message =~ s/[\r\n]+/ /g;
    $message =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    $message = substr($message, 0, 2048);

    print STDERR "$level: $message\n" if $level ne 'debug';
    return if !eval {
        openlog($self->tag(), 'pid,nowait', LOG_DAEMON);
        syslog($priority{$level}, '%s', $message);
        closelog();
        1;
    };
    return;
}

sub debug {
    my ($self, $message) = @_;
    return $self->log('debug', $message);
}

sub info {
    my ($self, $message) = @_;
    return $self->log('info', $message);
}

sub warning {
    my ($self, $message) = @_;
    return $self->log('warning', $message);
}

sub error {
    my ($self, $message) = @_;
    return $self->log('error', $message);
}

1;
