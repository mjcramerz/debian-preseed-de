package ManagedNetwork::Logger;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Sys::Syslog qw(:standard :macros);
use Types::Standard qw(Str);

my %LOG_LEVEL_VALUE = (
    debug   => 10,
    info    => 20,
    warning => 30,
    error   => 40,
    none    => 99,
);

has active_level => (
    is      => 'rw',
    isa     => Str,
    default => sub { 'error' },
);

sub canonical_log_level {
    my ($class, $level) = @_;

    $level = lc($level // 'info');
    return 'warning' if $level eq 'warn';
    return $level if exists $LOG_LEVEL_VALUE{$level};
    return 'info';
}

sub validate_active_level {
    my ($self) = @_;

    my $raw = lc($self->active_level() // q{});
    $raw =~ /\A(?:debug|info|warn|warning|error|none)\z/
        or die "SYSTEMD_LOG_LEVEL must be debug, info, warning, error, or none\n";
    $self->active_level(__PACKAGE__->canonical_log_level($raw));
    return;
}

sub enabled {
    my ($self, $level) = @_;

    my $requested = __PACKAGE__->canonical_log_level($level);
    return 1 if $requested eq 'error';
    my $active = __PACKAGE__->canonical_log_level($self->active_level());
    return 0 if $active eq 'none';
    return $LOG_LEVEL_VALUE{$requested} >= $LOG_LEVEL_VALUE{$active};
}

sub log {
    my ($self, $level, $message) = @_;

    $level = __PACKAGE__->canonical_log_level($level);
    return if !$self->enabled($level);
    $message = q{} if !defined $message;
    $message = "$message";
    $message =~ s/[\r\n]+/ /g;
    $message =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    $message = substr($message, 0, 2048);
    my $line = "$level: $message";
    print STDERR "$line\n";

    my %priority = (
        debug   => LOG_DEBUG,
        info    => LOG_INFO,
        warning => LOG_WARNING,
        error   => LOG_ERR,
    );
    return if !eval {
        openlog('managed-network', 'pid,nowait', LOG_USER);
        syslog($priority{$level}, '%s', $line);
        closelog();
        1;
    };
    return;
}

sub info {
    my ($self, $message) = @_;
    return $self->log('info', $message);
}

sub error {
    my ($self, $message) = @_;
    return $self->log('error', $message);
}

1;
