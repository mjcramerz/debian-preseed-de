package ManagedNetwork::CLI;

use strict;
use warnings;

use File::Basename qw(basename);
use Moo;

use ManagedNetwork::Logger;
use ManagedNetwork::Validator;

sub _usage {
    print STDERR "usage: managed-network validate [--wait-seconds 0..15]\n";
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
    if (@argv) {
        if (@argv != 2 || $argv[0] ne '--wait-seconds' ||
            $argv[1] !~ /\A(?:[0-9]|1[0-5])\z/) {
            _usage();
            return 1;
        }
        $wait_seconds = 0 + $argv[1];
    }

    my $logger = ManagedNetwork::Logger->new(
        active_level => $ENV{SYSTEMD_LOG_LEVEL} // 'error',
    );
    my $status = eval {
        ManagedNetwork::Validator->from_environment(
            logger => $logger, wait_seconds => $wait_seconds,
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
