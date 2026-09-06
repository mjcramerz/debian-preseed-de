package Zram::Swap;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Config qw(cfg);
use Zram::Path qw(canonical_path);

our @EXPORT_OK = qw(swap_active swap_status);

sub _active_swap_row {
    my ($path, $type, $size_kib, $used_kib, $priority) = @_;
    return {
        active => 1,
        path => $path,
        type => $type,
        size_kib => defined $size_kib && $size_kib =~ /\A[0-9]+\z/ ? 0 + $size_kib : undef,
        used_kib => defined $used_kib && $used_kib =~ /\A[0-9]+\z/ ? 0 + $used_kib : undef,
        priority => defined $priority && $priority =~ /\A-?[0-9]+\z/ ? 0 + $priority : undef,
    };
}

sub swap_status {
    my ($device) = @_;
    $device ||= cfg('ZRAM_SWAP_DEVICE');
    my $target = canonical_path($device);
    my %status = (active => 0);
    open my $fh, '<', cfg('ZRAM_PROCFS_ROOT') . '/swaps' or return \%status;
    <$fh>;
    while (my $line = <$fh>) {
        my ($path, $type, $size_kib, $used_kib, $priority) = split /\s+/, $line;
        next if !defined $path;
        if ($path eq $device || (defined $target && $path eq $target)) {
            close $fh;
            return _active_swap_row($path, $type, $size_kib, $used_kib, $priority);
        }
        my $candidate = canonical_path($path);
        if (defined $target && defined $candidate && $candidate eq $target) {
            close $fh;
            return _active_swap_row($path, $type, $size_kib, $used_kib, $priority);
        }
    }
    close $fh;
    return \%status;
}

sub swap_active {
    my ($device) = @_;
    return swap_status($device)->{active} ? 1 : 0;
}

1;
