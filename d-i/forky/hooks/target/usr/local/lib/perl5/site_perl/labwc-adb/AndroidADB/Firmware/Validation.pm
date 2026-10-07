package AndroidADB::Firmware::Validation;

use strict;
use warnings;

use Exporter qw(import);

use AndroidADB::Validation qw(
  fail
  require_value
  validate_firmware_version
  validate_samsung_model
  validate_samsung_region
);

our @EXPORT_OK = qw(
  validate_component_relative_path
  validate_manifest_hash
  validate_manifest_scalar
  validate_manifest_version
);

sub validate_manifest_version {
    my ($value) = @_;
    return validate_firmware_version($value);
}

sub validate_manifest_hash {
    my ($value, $key) = @_;
    $key //= 'hash';
    require_value(
        (defined($value) && !ref($value) && !!($value =~ /\A[0-9a-f]{64}\z/)),
        "managed Samsung firmware manifest has an invalid $key",
    );
    return $value;
}

sub validate_manifest_scalar {
    my ($value, $key) = @_;
    $key //= 'value';
    require_value(
        (
            defined($value)
                && !ref($value)
                && $value ne q{}
                && !!($value !~ /[\r\n\0]/)
                && length($value) <= 1024
        ),
        "managed Samsung firmware manifest has an invalid $key",
    );
    return $value;
}

sub validate_component_relative_path {
    my ($value, $prefix, $key) = @_;
    $key //= 'component';
    validate_manifest_scalar($value, $key);
    require_value(
        (defined($prefix) && !!($prefix =~ /\A(?:BL|AP|CP|CSC|HOME_CSC)\z/)),
        'managed Samsung firmware component prefix is invalid',
    );
    require_value(
        (
            !!($value =~ /\Afiles\/\Q$prefix\E_[A-Za-z0-9._-]*[A-Za-z0-9_-]\.tar\.md5\z/)
                && index($value, '..') < 0
                && index($value, '//') < 0
        ),
        "managed Samsung firmware manifest has an invalid $key",
    );
    return $value;
}

1;
