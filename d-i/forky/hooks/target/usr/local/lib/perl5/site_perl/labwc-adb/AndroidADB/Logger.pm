package AndroidADB::Logger;

use strict;
use warnings;

use Exporter qw(import);
use Sys::Syslog qw(:standard :macros);

our @EXPORT_OK = qw(log_event);

my %PRIORITY = (
    debug   => LOG_DEBUG,
    info    => LOG_INFO,
    warning => LOG_WARNING,
    error   => LOG_ERR,
);

sub _normalize_value {
    my ($value) = @_;
    $value = 'unset' if !defined($value) || ref($value);
    $value =~ s/[\r\n]+/_/g;
    $value =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    $value =~ s/[[:space:]]+/_/g;
    $value =~ s/[^A-Za-z0-9._:+@\/&()=-]/?/g;
    return substr($value, 0, 512);
}

sub log_event {
    my ($level, $event, %fields) = @_;
    $level = exists($PRIORITY{$level}) ? $level : 'error';
    defined($event) && !ref($event) && $event =~ /\A[a-z][a-z0-9-]{0,63}\z/
        or return 0;

    my @parts = ("event=$event");
    for my $key (sort keys %fields) {
        $key =~ /\A[a-z][a-z0-9-]{0,31}\z/ or next;
        push @parts, "$key=" . _normalize_value($fields{$key});
    }
    my $message = substr(join(q{ }, @parts), 0, 2048);

    return eval {
        openlog('labwc-adb', 'pid,nowait', LOG_USER);
        syslog($PRIORITY{$level}, '%s', $message);
        closelog();
        1;
    } ? 1 : 0;
}

1;
