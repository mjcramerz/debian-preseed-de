package Zram::Setup::Sysfs;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Base qw(Str);

use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Sysfs qw(normalize_attr read_uint_attr write_attr_optional write_attr_required);

has root => (
    is      => 'ro',
    isa     => Str,
    default => sub { cfg('ZRAM_SYSFS') },
);

sub path {
    my ($self, $name) = @_;
    defined $name && $name =~ /\A[A-Za-z0-9_.-]+\z/
        or fatal('unsafe zram sysfs attribute name');
    return $self->root() . "/$name";
}

sub read {
    my ($self, $name) = @_;
    return normalize_attr($self->path($name));
}

sub read_uint {
    my ($self, $name) = @_;
    return read_uint_attr($self->path($name));
}

sub required {
    my ($self, $name, $value, $description) = @_;
    return write_attr_required($self->path($name), $value, $description);
}

sub optional {
    my ($self, $name, $value, $description) = @_;
    return write_attr_optional($self->path($name), $value, $description);
}

sub candidates {
    my ($self, $name, $description, @values) = @_;
    return Zram::Sysfs::try_values($self->path($name), $description, @values);
}

1;
