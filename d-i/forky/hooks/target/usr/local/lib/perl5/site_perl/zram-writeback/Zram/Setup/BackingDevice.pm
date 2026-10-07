package Zram::Setup::BackingDevice;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Cwd qw(abs_path);
use File::Basename qw(basename);
use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Path qw(same_path);
use Zram::Setup::Mapper;
use Zram::Swap qw(swap_active);
use Zram::Sysfs qw(read_first_line);

has mapper => (
    is      => 'ro',
    default => sub { Zram::Setup::Mapper->new() },
);

sub _block_read_only {
    my ($self, $device) = @_;
    my $canonical = abs_path($device);
    defined $canonical && $canonical =~ m{\A/dev/[A-Za-z0-9_.:+-]+\z}
        or fatal("unable to resolve zram backing device: $device");
    my $name = basename($canonical);
    $name =~ /\A[A-Za-z0-9_.:+-]+\z/
        or fatal("unsafe canonical zram backing device name: $canonical");
    my $value = read_first_line(cfg('ZRAM_SYSFS_ROOT') . "/class/block/$name/ro");
    return undef if !defined $value || $value !~ /\A[01]\z/;
    return int $value;
}

sub _mounted {
    my ($self, $device) = @_;
    open my $fh, '<', cfg('ZRAM_PROCFS_ROOT') . '/mounts'
        or fatal('failed to read mount state');
    while (my $line = <$fh>) {
        my ($source) = split /\s+/, $line, 2;
        if (defined $source && same_path($source, $device)) {
            close $fh;
            return 1;
        }
    }
    close $fh;
    return 0;
}

sub prepare {
    my ($self) = @_;
    $self->mapper()->ensure_open();
    my $device = cfg('ZRAM_BACKING_DEVICE');
    -b $device or fatal("missing zram backing device $device");
    !same_path($device, cfg('ZRAM_SWAP_DEVICE'))
        or fatal('zram swap device and backing device must differ');
    my $read_only = $self->_block_read_only($device);
    defined $read_only && !$read_only or fatal("zram backing device is read-only: $device");
    !$self->_mounted($device) or fatal("zram backing device must not be mounted: $device");
    !swap_active($device) or fatal("zram backing device must not be active swap: $device");

    if (system('/usr/sbin/blkid', $device) == 0) {
        system('/usr/sbin/wipefs', '-a', '-f', $device) == 0
            or fatal("failed to clear stale signatures from $device");
    }
    return 1;
}

sub wait_until_ready {
    my ($self) = @_;
    $self->mapper()->ensure_open();
    my $device = cfg('ZRAM_BACKING_DEVICE');
    -b $device or fatal("missing zram backing device $device");
    my $read_only = $self->_block_read_only($device);
    defined $read_only && !$read_only or fatal("zram backing device is read-only: $device");
    return 1;
}

sub close {
    my ($self) = @_;
    return $self->mapper()->close();
}

1;
