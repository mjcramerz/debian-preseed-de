package ExternalSoftware::Servicing::Bitwarden;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use ExternalSoftware::Servicing::Atomic;

use constant PACKAGE_HELPER => '/usr/local/libexec/managed-bitwarden-package';
use constant INSTALLED_ASAR => '/opt/Bitwarden/resources/app.asar';

sub repack {
    my ($self, $source, $work) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        'Bitwarden source package',
        $source,
    );
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        'Bitwarden repack workspace',
        $work,
    );
    -f $source && !-l $source
        or die "Bitwarden source package is not a regular file\n";
    -d $work && !-l $work
        or die "Bitwarden repack workspace is not a directory\n";
    my $output = ExternalSoftware::Servicing::Atomic->assert_child(
        $work,
        'bitwarden.managed.deb',
    );
    !-e $output && !-l $output
        or die "Bitwarden repack output already exists\n";
    -x PACKAGE_HELPER
        or die "Bitwarden package helper is unavailable\n";
    system(
        PACKAGE_HELPER,
        'transform',
        '--source', $source,
        '--destination', $output,
        '--work-directory', $work,
    ) == 0 or die "Bitwarden package transformation failed\n";
    -f $output && !-l $output
        or die "Bitwarden transformed package is unavailable\n";
    return $output;
}

sub policy_valid {
    my ($self) = @_;
    return 0 if !-x PACKAGE_HELPER;
    return system(
        PACKAGE_HELPER,
        'verify',
        '--asar', INSTALLED_ASAR,
    ) == 0 ? 1 : 0;
}

1;
