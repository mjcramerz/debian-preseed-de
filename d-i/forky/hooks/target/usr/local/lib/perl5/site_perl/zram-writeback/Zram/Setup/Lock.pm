package Zram::Setup::Lock;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Zram::Lock qw(acquire_lock);

sub acquire {
    my ($self) = @_;
    return acquire_lock();
}

1;
