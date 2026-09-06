package Zram::Pressure::Evaluator;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Numeric qw(PositiveInt);

use Zram::Error qw(fatal);
use Zram::Types qw(ensure_percent ensure_uint);

has max_reason_bytes => (
    is      => 'ro',
    isa     => PositiveInt,
    default => sub { 512 },
);

sub _reason {
    my ($self, $value) = @_;
    $value = substr($value, 0, $self->max_reason_bytes());
    return $value;
}

sub _snapshot_uint_or_zero {
    my ($label, $value) = @_;
    return 0 if !defined $value;
    return ensure_uint($label, $value);
}

sub evaluate {
    my ($self, $snapshot, $thresholds) = @_;
    ref $snapshot eq 'HASH' && ref $thresholds eq 'HASH'
        or fatal('zram pressure evaluator requires hash references');

    my $available = _snapshot_uint_or_zero(
        'zram pressure snapshot mem_available_bytes',
        $snapshot->{mem_available_bytes},
    );
    my $total = _snapshot_uint_or_zero(
        'zram pressure snapshot mem_total_bytes',
        $snapshot->{mem_total_bytes},
    );
    my $some = _snapshot_uint_or_zero(
        'zram pressure snapshot psi_some_avg10_millionths',
        $snapshot->{psi_some_avg10_millionths},
    );
    my $full = _snapshot_uint_or_zero(
        'zram pressure snapshot psi_full_avg10_millionths',
        $snapshot->{psi_full_avg10_millionths},
    );
    my $emergency_mem_available_pct = ensure_percent(
        'zram pressure emergency_mem_available_pct',
        $thresholds->{emergency_mem_available_pct},
    );
    my $pressure_mem_available_pct = ensure_percent(
        'zram pressure pressure_mem_available_pct',
        $thresholds->{pressure_mem_available_pct},
    );
    my $emergency_some = ensure_uint(
        'zram pressure emergency_some',
        $thresholds->{emergency_some},
    );
    my $emergency_full = ensure_uint(
        'zram pressure emergency_full',
        $thresholds->{emergency_full},
    );
    my $pressure_some = ensure_uint(
        'zram pressure pressure_some',
        $thresholds->{pressure_some},
    );
    my $pressure_full = ensure_uint(
        'zram pressure pressure_full',
        $thresholds->{pressure_full},
    );
    my $minimum_free = ensure_uint(
        'zram pressure minimum_free',
        $thresholds->{minimum_free},
    );
    my $available_pct = $total > 0 ? int(($available * 100 + $total - 1) / $total) : 0;
    my @emergency;
    my @pressure;

    push @emergency, $self->_reason("MemAvailablePct=$available_pct<=$emergency_mem_available_pct")
        if $total > 0 && $available_pct <= $emergency_mem_available_pct;
    push @emergency, $self->_reason('PSI some avg10 reached emergency threshold')
        if $some >= $emergency_some;
    push @emergency, $self->_reason('PSI full avg10 reached emergency threshold')
        if $full >= $emergency_full;
    push @pressure, $self->_reason("MemAvailablePct=$available_pct<=$pressure_mem_available_pct")
        if $total > 0 && $available_pct <= $pressure_mem_available_pct;
    push @pressure, $self->_reason('PSI some avg10 reached pressure threshold')
        if $some >= $pressure_some;
    push @pressure, $self->_reason('PSI full avg10 reached pressure threshold')
        if $full >= $pressure_full;
    push @pressure, $self->_reason('MemAvailable bytes below configured floor')
        if $minimum_free > 0 && $available > 0 && $available <= $minimum_free;

    my $facts = {
        mem_available_bytes => $available,
        mem_total_bytes => $total,
        mem_available_percent => $available_pct,
        psi_some_avg10_millionths => $some,
        psi_full_avg10_millionths => $full,
    };
    return ('emergency', \@emergency, $facts) if @emergency;
    return ('pressure', \@pressure, $facts) if @pressure;
    return ('normal', [$self->_reason('below pressure thresholds')], $facts);
}

1;
