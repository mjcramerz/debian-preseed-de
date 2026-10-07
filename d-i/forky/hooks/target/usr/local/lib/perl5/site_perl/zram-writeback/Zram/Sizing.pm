package Zram::Sizing;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Error qw(fatal);
use Zram::Types qw(ensure_uint);

our @EXPORT_OK = qw(size_to_bytes bytes_to_writeback_pages);

sub size_to_bytes {
    my ($label, $value) = @_;
    return 0 if !defined $value || $value eq '';
    if ($value =~ /\A([0-9]+)\z/) {
        return 0 + $1;
    }
    if ($value =~ /\A([0-9]+)([KkMmGgTt])(?:i?[Bb])?\z/) {
        my ($number, $unit) = (0 + $1, lc($2));
        my %multiplier = (
            k => 1024,
            m => 1024 * 1024,
            g => 1024 * 1024 * 1024,
            t => 1024 * 1024 * 1024 * 1024,
        );
        return $number * $multiplier{$unit};
    }
    fatal("$label must be bytes or K/M/G/T size, got '$value'");
}

sub bytes_to_writeback_pages {
    my ($label, $bytes) = @_;
    $bytes = ensure_uint($label, $bytes);
    return int($bytes / 4096);
}

1;
