package Zram::BackingDevice;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Config qw(cfg);
use Zram::Path qw(canonical_path);
use Zram::Swap qw(swap_active);
use Zram::Sysfs qw(read_first_line);

our @EXPORT_OK = qw(backing_device_status);

sub _blockdev_readonly {
    my ($device) = @_;

    my $name = canonical_path($device);
    $name = $device if !defined $name;
    $name =~ s{.*/}{};
    return undef if !defined $name;

    my $ro = read_first_line(cfg('ZRAM_SYSFS_ROOT') . "/class/block/$name/ro");
    return undef if !defined $ro || $ro !~ /\A[01]\z/;
    return int($ro);
}

sub backing_device_status {
    my $device     = cfg('ZRAM_BACKING_DEVICE');
    my $raw_device = cfg('ZRAM_BACKING_RAW_DEVICE');
    my $mapper     = cfg('ZRAM_BACKING_MAPPER_NAME');

    my %status = (
        backing_device            => $device,
        backing_device_exists     => defined($device) && -b $device ? 1 : 0,
        backing_raw_device        => $raw_device,
        backing_raw_device_exists => defined($raw_device) && $raw_device ne '' && -b $raw_device ? 1 : 0,
        backing_mapper            => $mapper,
    );

    if (defined($device) && -b $device) {
        $status{backing_device_canonical} = canonical_path($device);
        $status{backing_device_swap_active} = swap_active($device) ? 1 : 0;
        $status{backing_device_readonly} = _blockdev_readonly($device);
    }

    if (defined($raw_device) && $raw_device ne '' && -b $raw_device) {
        $status{backing_raw_device_canonical} = canonical_path($raw_device);
    }

    return \%status;
}

1;
