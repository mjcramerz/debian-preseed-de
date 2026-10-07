package Zram::Types;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Error qw(fatal);

our @EXPORT_OK = qw(
  ensure_uint ensure_positive_uint ensure_sint ensure_percent ensure_bool
  decimal_to_millionths ensure_probability_millionths ensure_psi_millionths
  validate_device_path validate_abs_path validate_page_index_spec validate_writeback_spec
  count_page_index_spec_pages
);

sub ensure_uint {
    my ($label, $value) = @_;
    defined $value && $value =~ /\A[0-9]+\z/
        or fatal("$label must be an integer, got '" . (defined $value ? $value : 'unset') . "'");
    return 0 + $value;
}

sub ensure_positive_uint {
    my ($label, $value) = @_;
    my $int = ensure_uint($label, $value);
    $int > 0 or fatal("$label must be greater than zero");
    return $int;
}

sub ensure_sint {
    my ($label, $value) = @_;
    defined $value && $value =~ /\A-?[0-9]+\z/
        or fatal("$label must be an integer, got '" . (defined $value ? $value : 'unset') . "'");
    return 0 + $value;
}

sub ensure_percent {
    my ($label, $value) = @_;
    my $int = ensure_uint($label, $value);
    ($int >= 0 && $int <= 100) or fatal("$label must be between 0 and 100, got $value");
    return $int;
}

sub ensure_bool {
    my ($label, $value) = @_;
    defined $value or fatal("$label must be a boolean, got unset");
    return 1 if $value eq '1';
    return 0 if $value eq '0';
    fatal("$label must be an integer 0/1 value, got '$value'");
}

sub decimal_to_millionths {
    my ($label, $value) = @_;
    defined $value && $value =~ /\A([0-9]+)(?:\.([0-9]+))?\z/
        or fatal("$label must be a decimal number, got '" . (defined $value ? $value : 'unset') . "'");
    my $whole = 0 + $1;
    my $frac = defined $2 ? $2 : '';
    $frac = substr($frac . '000000', 0, 6);
    return $whole * 1_000_000 + (0 + $frac);
}

sub ensure_probability_millionths {
    my ($label, $value) = @_;
    my $units = decimal_to_millionths($label, $value);
    ($units >= 0 && $units <= 1_000_000) or fatal("$label must be a decimal between 0 and 1, got $value");
    return $units;
}

sub ensure_psi_millionths {
    my ($label, $value) = @_;
    my $units = decimal_to_millionths($label, $value);
    ($units >= 0 && $units <= 100_000_000) or fatal("$label must be a PSI percentage between 0 and 100, got $value");
    return $units;
}

sub validate_device_path {
    my ($label, $value) = @_;
    defined $value && $value =~ m{\A/dev/[A-Za-z0-9_./:+-]+\z}
        or fatal("$label must be an absolute /dev path, got '" . (defined $value ? $value : 'unset') . "'");
}

sub validate_abs_path {
    my ($label, $value) = @_;
    defined $value
        && $value =~ m{\A/}
        && $value !~ m{(?:\A|/)\.\.(?:/|\z)}
        && $value !~ /[\x00-\x20\x7f]/
        or fatal("$label must be a safe absolute path, got '" . (defined $value ? $value : 'unset') . "'");
}

sub validate_page_index_spec {
    my ($value, $max_bytes) = @_;
    return if !defined $value || $value eq '';
    validate_writeback_spec('maintenance_page_indexes', $value, 1, $max_bytes);
}

sub count_page_index_spec_pages {
    my ($label, $value, $max_bytes) = @_;
    return 0 if !defined $value || $value eq '';
    validate_writeback_spec($label, $value, 1, $max_bytes);

    my $pages = 0;
    for my $token (split /\s+/, $value) {
        if ($token =~ /\Apage_index=([0-9]+)\z/) {
            ensure_uint("$label page_index", $1);
            $pages++;
            next;
        }
        if ($token =~ /\Apage_indexes=([0-9]+)-([0-9]+)\z/) {
            my $low = ensure_uint("$label page_indexes low", $1);
            my $high = ensure_uint("$label page_indexes high", $2);
            $low <= $high or fatal("$label page_indexes range must be ascending: $token");
            $pages += $high - $low + 1;
            next;
        }
    }
    return $pages;
}

sub validate_writeback_spec {
    my ($label, $value, $page_index_only, $max_bytes) = @_;
    defined $value && $value ne '' or fatal("$label must not be empty");
    $max_bytes = ensure_positive_uint("$label maximum bytes", $max_bytes);
    length($value) <= $max_bytes or fatal("$label is too large");
    $value !~ /[\x00-\x1f\x7f]/ or fatal("$label contains control characters");

    my @tokens = split /\s+/, $value;
    @tokens or fatal("$label must contain at least one writeback token");
    for my $token (@tokens) {
        if (!$page_index_only && $token =~ /\Atype=(idle|huge|huge_idle|incompressible)\z/) {
            next;
        }
        if ($token =~ /\Apage_index=([0-9]+)\z/) {
            ensure_uint("$label page_index", $1);
            next;
        }
        if ($token =~ /\Apage_indexes=([0-9]+)-([0-9]+)\z/) {
            my $low = ensure_uint("$label page_indexes low", $1);
            my $high = ensure_uint("$label page_indexes high", $2);
            $low <= $high or fatal("$label page_indexes range must be ascending: $token");
            next;
        }
        fatal("$label contains unsupported writeback token: $token");
    }
}

1;
