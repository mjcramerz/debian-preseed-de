package TimeshiftManaged::CLI;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Str);

use TimeshiftManaged::GrubRefresh;
use TimeshiftManaged::Logger;
use TimeshiftManaged::Snapshot;

has program => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

sub _usage {
    my ($self) = @_;

    if ($self->program() eq 'timeshift-managed-snapshot') {
        print STDERR "usage: timeshift-managed-snapshot {daily|weekly|monthly}\n";
    }
    else {
        print STDERR "usage: grub-btrfs-refresh [--wait]\n";
    }
    return;
}

sub run {
    my ($self, @argv) = @_;

    if (@argv == 1 && $argv[0] eq '--help') {
        $self->_usage();
        return 0;
    }

    if ($self->program() eq 'timeshift-managed-snapshot') {
        @argv == 1 or do {
            $self->_usage();
            return 1;
        };
        my $snapshot = eval { TimeshiftManaged::Snapshot->from_environment($argv[0]) };
        if (!$snapshot) {
            my $error = $@ || 'invalid Timeshift snapshot configuration';
            $error =~ s/\s+\z//;
            TimeshiftManaged::Logger->new(tag => 'timeshift-managed-snapshot')->error($error);
            return 1;
        }
        return $snapshot->run();
    }

    return TimeshiftManaged::GrubRefresh->new()->run(@argv);
}

1;
