package Zram::Setup::Lock;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Zram::Lock qw(try_acquire_lock);

sub acquire {
    my ($self) = @_;
    return try_acquire_lock();
}

1;
