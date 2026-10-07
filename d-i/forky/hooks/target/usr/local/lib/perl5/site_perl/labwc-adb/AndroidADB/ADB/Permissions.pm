package AndroidADB::ADB::Permissions;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Validation qw(
  validate_package_name
  validate_permission_name
  validate_serial
);

has config => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has device => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub grant {
    my ($self, $serial, $package_name, $permission_name) = @_;
    validate_serial($serial);
    validate_package_name($package_name);
    validate_permission_name($permission_name);
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $serial,
        'shell',
        'pm',
        'grant',
        $package_name,
        $permission_name,
    );
}

1;
