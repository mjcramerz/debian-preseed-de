package ManagedNetwork::CLI;

use strict;
use warnings;

use File::Basename qw(basename);
use Moo;

use ManagedNetwork::Logger;
use ManagedNetwork::Validator;

sub _usage {
    print STDERR "usage: network validate [--wait-seconds 0..15] [--allow-absent]\n";
    return;
}

sub run {
    my ($self, @argv) = @_;

    if (@argv == 1 && $argv[0] eq '--help') {
        _usage();
        return 0;
    }
    if (!@argv || shift(@argv) ne 'validate') {
        _usage();
        return 1;
    }
    my $wait_seconds = 0;
    my $allow_absent = 0;
    my %seen;
    while (@argv) {
        my $option = shift @argv;
        if (!$seen{$option}++) {
            if ($option eq '--allow-absent') {
                $allow_absent = 1;
                next;
            }
            if ($option eq '--wait-seconds' && @argv && $argv[0] =~ /\A(?:[0-9]|1[0-5])\z/) {
                $wait_seconds = 0 + shift @argv;
                next;
            }
        }
        _usage();
        return 1;
    }

    my $logger = ManagedNetwork::Logger->new(
        active_level => $ENV{SYSTEMD_LOG_LEVEL} // 'error',
    );
    my $status = eval {
        ManagedNetwork::Validator->from_environment(
            logger => $logger, wait_seconds => $wait_seconds, allow_absent => $allow_absent,
        )->validate();
    };
    if (!$status && $@) {
        my $error = $@;
        $error =~ s/\s+\z//;
        $logger->error($error);
        return 1;
    }
    return $status;
}

1;
