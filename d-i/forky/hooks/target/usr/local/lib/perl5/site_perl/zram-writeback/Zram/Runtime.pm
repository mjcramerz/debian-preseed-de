package Zram::Runtime;

use strict;
use warnings;

use Moo;
use MooX::HandlesVia;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(ArrayRef Str);

use Zram::Command qw(dispatch requires_lock requires_sysfs);
use Zram::Config;
use Zram::Config qw(validate_config);
use Zram::Lock qw(acquire_lock);

sub _assert_non_empty_string {
    my ($value) = @_;
    defined($value) && !ref($value) && length($value) > 0
        or die "action must be a non-empty string\n";
    return;
}

has config_path => (
    is      => 'ro',
    isa     => Str,
    required => 1,
);

has action => (
    is      => 'ro',
    isa     => \&_assert_non_empty_string,
    required => 1,
);

has arguments => (
    is          => 'ro',
    isa         => ArrayRef,
    default     => sub { [] },
    handles_via => 'Array',
    handles     => {
        command_arguments => 'elements',
    },
);

sub run {
    my ($self) = @_;
    Zram::Config->new(path => $self->config_path())->load();
    validate_config(require_sysfs => requires_sysfs($self->action()));
    my $lock = requires_lock($self->action()) ? acquire_lock() : undef;
    return dispatch($self->action(), $self->command_arguments());
}

1;
