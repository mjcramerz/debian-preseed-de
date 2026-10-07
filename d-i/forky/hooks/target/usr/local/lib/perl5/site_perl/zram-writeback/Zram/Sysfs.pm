package Zram::Sysfs;

use strict;
use warnings;

use Exporter qw(import);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
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
    return undef if !defined $line || $line !~ /\A([0-9]{1,20})\s*\z/;
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

my $TRIGGER_SEQUENCE = 0;

sub _counter_field {
    my ($path, $index) = @_;
    my $line = read_first_line($path);
    return undef if !defined $line;
    # Kernel statistics use padded %8llu fields; Perl's special space split
    # discards leading whitespace instead of shifting every counter index.
    my @fields = split ' ', $line;
    my $value = $fields[$index];
    return undef if !defined $value || $value !~ /\A[0-9]{1,20}\z/;
    return 0 + $value;
}

sub _trigger_counters {
    my $sysfs = cfg('ZRAM_SYSFS');
    return {
        mem_used => _counter_field("$sysfs/mm_stat", 2),
        bd_writes => _counter_field("$sysfs/bd_stat", 2),
        remaining => read_uint_attr("$sysfs/writeback_limit"),
    };
}

sub _audited_trigger {
    my ($action, @specs) = @_;
    _validate_attr_value("zram $action trigger", $_) for grep { defined $_ && $_ ne '' } @specs;
    my $id = $$ . '-' . ++$TRIGGER_SEQUENCE;
    my $before = _trigger_counters();
    my $started = clock_gettime(CLOCK_MONOTONIC);
    # Index lists can be long: log a bounded specification plus its full length.
    my $spec = $specs[0] // '';
    log_msg('info', "event=trigger-start id=$id action=$action device=" . cfg('ZRAM_SYSFS') .
        ' spec_bytes=' . length($spec) . ' spec=' . substr($spec, 0, 256));
    my $ok = try_values(cfg('ZRAM_SYSFS') . "/$action", "zram $action trigger", @specs);
    my $after = _trigger_counters();
    my $elapsed_ms = int((clock_gettime(CLOCK_MONOTONIC) - $started) * 1000);
    my ($writes, $bytes, $memory) = ('unknown', 'unknown', 'unknown');
    if (defined $before->{bd_writes} && defined $after->{bd_writes} &&
            $after->{bd_writes} >= $before->{bd_writes}) {
        $writes = $after->{bd_writes} - $before->{bd_writes};
        $bytes = $writes * 4096; # bd_stat units are ALWAYS 4 KiB, not PAGE_SIZE
    }
    if (defined $before->{mem_used} && defined $after->{mem_used}) {
        $memory = $after->{mem_used} - $before->{mem_used};
    }
    my $remaining = $after->{remaining} // 'unknown';
    my $result = !$ok ? 'failed' : _dry_run() ? 'dry-run' : 'accepted';
    # These are observed kernel deltas, not claimed NAND writes or exclusive
    # attribution: the kernel may service concurrent swap traffic during a pass.
    log_msg($ok ? 'info' : 'warning', "event=trigger-end id=$id action=$action result=$result " .
        "elapsed_ms=$elapsed_ms bd_writes_delta_4k=$writes backing_written_bytes=$bytes " .
        "mem_used_delta_bytes=$memory writeback_limit_remaining_4k=$remaining");
    return $ok;
}

sub recompress_spec {
    return _audited_trigger('recompress', @_);
}

sub writeback_spec {
    return _audited_trigger('writeback', @_);
}

sub compact_device {
    my $sysfs = cfg('ZRAM_SYSFS');
    my $changed = 0;
    $changed += write_attr_optional("$sysfs/compact", 1, 'zram compact trigger');
    # Preserve the lifetime peak for auditing; setup resets it on initialization.
    log_msg('info', 'event=compact result=' . ($changed ? (_dry_run() ? 'dry-run' : 'accepted') : 'failed'));
    return $changed;
}

1;
