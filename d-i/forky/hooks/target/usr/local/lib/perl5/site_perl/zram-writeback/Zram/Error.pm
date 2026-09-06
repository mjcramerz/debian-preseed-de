package Zram::Error;

use strict;
use warnings;

use Exporter qw(import);

our @EXPORT_OK = qw(fatal usage_error);

sub fatal {
    my ($message) = @_;
    $message = 'unknown zram-writeback failure' if !defined $message || $message eq '';
    if (eval { require Zram::Logger; 1 }) {
        Zram::Logger::log_msg('error', $message);
    } else {
        print STDERR "error: $message\n";
    }
    exit 1;
}

sub usage_error {
    my ($message) = @_;
    print STDERR "$message\n" if defined $message && $message ne '';
    exit 2;
}

1;
