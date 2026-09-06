package AndroidADB::ADB::Package;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Validation qw(
  fail
  validate_local_file
  validate_package_name
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

sub list_user_packages {
    my ($self, $serial) = @_;
    validate_serial($serial);
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $serial,
        'shell',
        'pm',
        'list',
        'packages',
        '-3',
    );
}

sub current_activity {
    my ($self, $serial) = @_;
    validate_serial($serial);
    my $output = $self->device->capture_serial(
        $self->config->adb_command_seconds,
        $serial,
        'shell',
        'dumpsys',
        'activity',
        'activities',
    );
    my $shown = 0;
    for my $line (split /\n/, $output) {
        next if $line !~ /(?:mResumedActivity|topResumedActivity)/;
        print "$line\n";
        ++$shown;
        last if $shown >= 20;
    }
    return 0;
}

sub install {
    my ($self, $serial, $file, $replace) = @_;
    validate_serial($serial);
    my $resolved = validate_local_file($file);
    $resolved =~ /\.apk\z/
        or fail('APK installation requires a local .apk file');
    return $self->device->run_serial(
        $self->config->adb_transfer_seconds,
        $serial,
        'install',
        ($replace ? ('-r') : ()),
        $resolved,
    );
}

sub uninstall {
    my ($self, $serial, $package_name) = @_;
    validate_serial($serial);
    validate_package_name($package_name);
    return $self->device->run_serial(
        $self->config->adb_transfer_seconds,
        $serial,
        'uninstall',
        $package_name,
    );
}

sub clear_data {
    my ($self, $serial, $package_name) = @_;
    validate_serial($serial);
    validate_package_name($package_name);
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $serial,
        'shell',
        'pm',
        'clear',
        $package_name,
    );
}

1;
