package Zram::Path;

use strict;
use warnings;

use Exporter qw(import);
use Cwd qw(abs_path);

our @EXPORT_OK = qw(canonical_path same_path);

sub canonical_path {
    my ($path) = @_;
    return undef if !defined $path || $path eq '';
    return abs_path($path) || $path;
}

sub same_path {
    my ($left, $right) = @_;
    my $left_path = canonical_path($left);
    my $right_path = canonical_path($right);
    return 0 if !defined $left_path || !defined $right_path;
    return $left_path eq $right_path ? 1 : 0;
}

1;
