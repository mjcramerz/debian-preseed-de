package DigitalAssets::Policy;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(HashRef);
use DigitalAssets::Catalog qw(action_ids);

has actions => (
    is      => 'ro',
    isa     => HashRef,
    default => sub {
        return { map { $_ => 1 } action_ids() };
    },
);

sub assert_action {
    my ($self, $action) = @_;
    defined($action) && $action =~ /\A[a-z0-9-]+\z/ && $self->actions()->{$action}
        or die "labwc-digital-assets-action: unsupported Digital Assets action\n";
    return $action;
}

1;
