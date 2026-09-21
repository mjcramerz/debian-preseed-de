package Zram::IOPressure;

use strict;
use warnings;

use Exporter qw(import);
use Errno qw(EINTR);
use Fcntl qw(O_NOFOLLOW O_NONBLOCK O_RDONLY);
use Zram::Config qw(cfg);
use Zram::Types qw(decimal_to_millionths);

our @EXPORT_OK = qw(io_pressure_snapshot io_pressure_log_fields);
use constant MAX_PSI_BYTES => 4096;

sub _read_sample {
    my ($path) = @_;
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or return (undef, 'open-failed');
    if (!-f $fh) {
        close $fh;
        return (undef, 'not-regular');
    }
    my $text = '';
    while (length($text) <= MAX_PSI_BYTES) {
        my $n = sysread($fh, my $chunk, MAX_PSI_BYTES + 1 - length($text));
        if (!defined $n) {
            next if $! == EINTR;
            close $fh;
            return (undef, 'read-failed');
        }
        last if $n == 0;
        $text .= $chunk;
    }
    close $fh or return (undef, 'close-failed');
    return (undef, 'oversized') if length($text) > MAX_PSI_BYTES;
    my %values;
    for my $line (split /\n/, $text) {
        # Validate the complete record and reject duplicate/partial snapshots.
        # Kernel percentages use two decimals; tolerate up to six without floats.
        $line =~ /\A(some|full) avg10=([0-9]{1,3}(?:\.[0-9]{1,6})?) avg60=([0-9]{1,3}(?:\.[0-9]{1,6})?) avg300=([0-9]{1,3}(?:\.[0-9]{1,6})?) total=[0-9]{1,20}\z/
            or return (undef, 'malformed');
        my ($kind, @averages) = ($1, $2, $3, $4);
        return (undef, 'duplicate') if exists $values{$kind};
        my @units = map { decimal_to_millionths('I/O PSI', $_) } @averages;
        return (undef, 'out-of-range') if grep { $_ > 100_000_000 } @units;
        $values{$kind} = $units[0];
    }
    return (undef, 'incomplete') if !exists $values{some} || !exists $values{full};
    return (undef, 'inconsistent') if $values{full} > $values{some};
    return (\%values, 'sampled');
}

sub io_pressure_snapshot {
    return { state => 'disabled', throttle => 0, reason => 'policy-disabled' }
        if !cfg('ZRAM_IO_PSI_ENABLE');
    my $root = cfg('ZRAM_PROCFS_ROOT');
    $root =~ s{/+\z}{};
    my ($sample, $reason) = _read_sample("$root/pressure/io");
    return { state => 'unknown', throttle => 1, reason => $reason }
        if !defined $sample;
    my $high = $sample->{some} >= cfg('ZRAM_IO_PSI_SOME_AVG10_THRESHOLD_UNITS')
        || $sample->{full} >= cfg('ZRAM_IO_PSI_FULL_AVG10_THRESHOLD_UNITS');
    return {
        state => $high ? 'high' : 'low',
        throttle => $high ? 1 : 0,
        reason => $reason,
        some_avg10_millionths => $sample->{some},
        full_avg10_millionths => $sample->{full},
    };
}

sub io_pressure_log_fields {
    my ($sample) = @_;
    return join ' ',
        'io_psi=' . $sample->{state},
        'io_psi_reason=' . $sample->{reason},
        'io_some_avg10_millionths=' . ($sample->{some_avg10_millionths} // 'unknown'),
        'io_full_avg10_millionths=' . ($sample->{full_avg10_millionths} // 'unknown');
}

1;
