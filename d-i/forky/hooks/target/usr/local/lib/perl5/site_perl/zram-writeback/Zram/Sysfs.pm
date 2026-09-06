package Zram::Sysfs;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Config qw(cfg cfg_default);
use Zram::Error qw(fatal);
use Zram::Logger qw(log_msg);

our @EXPORT_OK = qw(
  read_first_line read_uint_attr normalize_attr write_attr_optional write_attr_required
  try_values zram_fill_pct recompress_spec writeback_spec compact_device
);

use constant MAX_ATTR_BYTES => 65_536;

sub _read_attr_bytes {
    my ($path) = @_;
    open my $fh, '<:raw', $path or return undef;

    my $limit = MAX_ATTR_BYTES + 1;
    my $buffer = '';
    while (length($buffer) < $limit) {
        my $remaining = $limit - length($buffer);
        my $read = read($fh, my $chunk, $remaining);
        if (!defined $read) {
            close $fh;
            return undef;
        }
        last if $read == 0;
        $buffer .= $chunk;
    }
    close $fh or return undef;
    length($buffer) <= MAX_ATTR_BYTES
        or fatal("zram sysfs attribute exceeds byte limit: $path");
    return $buffer;
}

sub read_first_line {
    my ($path) = @_;
    my $buffer = _read_attr_bytes($path);
    return undef if !defined $buffer;
    my ($line) = split /\n/, $buffer, 2;
    return $line;
}

sub read_uint_attr {
    my ($path) = @_;
    my $line = read_first_line($path);
    return undef if !defined $line || $line !~ /\A([0-9]+)/;
    return 0 + $1;
}

sub normalize_attr {
    my ($path) = @_;
    my $buffer = _read_attr_bytes($path);
    return undef if !defined $buffer;
    $buffer =~ s/\s+/ /g;
    $buffer =~ s/\A //;
    $buffer =~ s/ \z//;
    return $buffer eq '' ? undef : $buffer;
}

sub _dry_run {
    return cfg_default('ZRAM_DRY_RUN', 0) ? 1 : 0;
}

sub _validate_attr_value {
    my ($desc, $value) = @_;
    defined $value && !ref($value)
        or fatal("zram sysfs value for $desc must be a defined scalar");
    length($value) <= MAX_ATTR_BYTES
        or fatal("zram sysfs value for $desc exceeds byte limit");
    $value !~ /[\x00-\x1f\x7f]/
        or fatal("zram sysfs value for $desc contains control characters");
    return $value;
}

sub write_attr_optional {
    my ($path, $value, $desc) = @_;
    _validate_attr_value($desc, $value);
    return 0 if !-e $path || !-w $path;
    if (_dry_run()) {
        log_msg('info', "dry-run: would set $desc via $path to '$value'");
        return 1;
    }
    my $fh;
    if (!open $fh, '>', $path) {
        log_msg('warning', "failed to set optional $desc via $path: $!");
        return 0;
    }
    my $ok = print {$fh} "$value\n";
    $ok = close($fh) && $ok;
    if (!$ok) {
        my $error = $! || 'write rejected';
        log_msg('warning', "failed to set optional $desc via $path: $error");
        return 0;
    }
    return 1;
}

sub write_attr_required {
    my ($path, $value, $desc) = @_;
    -e $path && -w $path or fatal("$desc is unavailable at $path");
    return 1 if write_attr_optional($path, $value, $desc);
    fatal("failed to set $desc via $path");
}

sub try_values {
    my ($path, $desc, @values) = @_;
    return 0 if !-e $path || !-w $path;
    my $attempted = 0;
    my $last_error = '';
    for my $value (@values) {
        next if !defined $value || $value eq '';
        _validate_attr_value($desc, $value);
        $attempted = 1;
        if (_dry_run()) {
            log_msg('info', "dry-run: would set $desc via $path to '$value'");
            return 1;
        }
        my $fh;
        if (open $fh, '>', $path) {
            my $ok = print {$fh} "$value\n";
            $ok = close($fh) && $ok;
            return 1 if $ok;
            $last_error = "$!";
        } else {
            $last_error = "$!";
        }
        $last_error = 'write rejected' if $last_error eq '';
    }
    if (!$attempted) {
        log_msg('warning', "no non-empty candidate values supplied for $desc via $path");
    } elsif ($last_error ne '') {
        log_msg('warning', "none of the candidate values worked for $desc via $path: $last_error");
    } else {
        log_msg('warning', "none of the candidate values worked for $desc via $path");
    }
    return 0;
}

sub zram_fill_pct {
    my $sysfs = cfg('ZRAM_SYSFS');
    my $disksize = read_uint_attr("$sysfs/disksize");
    return 0 if !defined $disksize || $disksize <= 0;
    my $mm_stat = read_first_line("$sysfs/mm_stat");
    return 0 if !defined $mm_stat || $mm_stat !~ /\A([0-9]+)/;
    my $orig_data_size = 0 + $1;
    return int($orig_data_size * 100 / $disksize);
}

sub recompress_spec {
    my (@specs) = @_;
    return try_values(cfg('ZRAM_SYSFS') . '/recompress', 'zram recompress trigger', @specs);
}

sub writeback_spec {
    my (@specs) = @_;
    return try_values(cfg('ZRAM_SYSFS') . '/writeback', 'zram writeback trigger', @specs);
}

sub compact_device {
    my $sysfs = cfg('ZRAM_SYSFS');
    my $changed = 0;
    $changed += write_attr_optional("$sysfs/compact", 1, 'zram compact trigger');
    $changed += write_attr_optional("$sysfs/mem_used_max", 0, 'zram mem_used_max reset');
    return $changed;
}

1;
