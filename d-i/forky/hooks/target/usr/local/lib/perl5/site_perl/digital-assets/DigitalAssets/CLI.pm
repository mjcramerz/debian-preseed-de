package DigitalAssets::CLI;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);
use DigitalAssets::Catalog qw(menu_catalog_lines);

has runtime => (
    is      => 'ro',
    isa     => Object,
    lazy    => 1,
    builder => sub {
        require DigitalAssets::Runtime;
        return DigitalAssets::Runtime->new();
    },
);

sub run {
    my ($self, @argv) = @_;
    if (@argv == 1 && $argv[0] eq '--help') {
        print STDERR "usage: labwc-digital-assets-action [--menu-catalog] [--run] <action> <file-or-list>\n";
        return 0;
    }
    if (@argv == 1 && $argv[0] eq '--menu-catalog') {
        print "$_\n" for menu_catalog_lines();
        return 0;
    }
    return $self->runtime()->run(@argv);
}

1;
