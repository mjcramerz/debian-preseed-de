package Zram::Setup::Lifecycle;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Zram::Setup::Device;
use Zram::Setup::Lock;

has config => (is => 'ro', required => 1);
has device => (is => 'ro', default => sub { Zram::Setup::Device->new() });
has lock   => (is => 'ro', default => sub { Zram::Setup::Lock->new() });

sub run {
    my ($self, $action) = @_;
    if ($action eq 'status') {
        return 0 if !$self->config()->enabled() && do { print "enabled=0\n"; 1 };
        return $self->device()->status();
    }
    return 0 if !$self->config()->enabled();

    my $guard = $self->lock()->acquire();
    return $self->device()->start()        if $action eq 'start';
    return $self->device()->stop()         if $action eq 'stop';
    return $self->device()->reset()        if $action eq 'reset';
    return $self->device()->wait_backing() if $action eq 'wait-backing';
    die "unreachable zram lifecycle action\n";
}

1;
