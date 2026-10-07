package Zram::Command::Status;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Exporter qw(import);
use Zram::Device qw(print_status);
use Zram::Error qw(fatal);

our @EXPORT_OK = qw(run);

sub run {
    return __PACKAGE__->new()->execute(@_);
}

sub execute {
    my ($self, @args) = @_;
    my %opts = (json => 0);
    for my $arg (@args) {
        if ($arg eq '--json') {
            $opts{json} = 1;
            next;
        }
        if ($arg eq '--plain') {
            $opts{json} = 0;
            next;
        }
        fatal('usage: zram-writeback status [--plain|--json]');
    }
    return print_status(%opts);
}

1;
