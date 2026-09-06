package Zram::Pressure;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Config qw(cfg);
use Zram::Logger qw(log_msg);
use Zram::Pressure::Evaluator;
use Zram::Procfs qw(memory_pressure_snapshot);

our @EXPORT_OK = qw(determine_pressure_state memory_pressure_gate_met);

my $EVALUATOR;

sub _evaluator {
    $EVALUATOR ||= Zram::Pressure::Evaluator->new();
    return $EVALUATOR;
}

sub _thresholds {
    return {
        pressure_mem_available_pct => cfg('ZRAM_PRESSURE_MEM_AVAILABLE_PCT'),
        emergency_mem_available_pct => cfg('ZRAM_EMERGENCY_MEM_AVAILABLE_PCT'),
        pressure_some => cfg('ZRAM_PRESSURE_SOME_AVG10_THRESHOLD_UNITS'),
        pressure_full => cfg('ZRAM_PRESSURE_FULL_AVG10_THRESHOLD_UNITS'),
        emergency_some => cfg('ZRAM_EMERGENCY_SOME_AVG10_THRESHOLD_UNITS'),
        emergency_full => cfg('ZRAM_EMERGENCY_FULL_AVG10_THRESHOLD_UNITS'),
        minimum_free => cfg('ZRAM_MIN_FREE_MEMORY_BYTES'),
    };
}

sub determine_pressure_state {
    return ('normal', ['pressure policy disabled'], {}) if !cfg('ZRAM_PRESSURE_ENABLED');

    my $thresholds = _thresholds();
    my ($state, $reasons, $facts) = _evaluator()->evaluate(
        memory_pressure_snapshot(),
        $thresholds,
    );

    log_msg(
        'debug',
        'memory pressure gates ' .
        "some_avg10_millionths=$facts->{psi_some_avg10_millionths} " .
        "full_avg10_millionths=$facts->{psi_full_avg10_millionths} " .
        "mem_available_bytes=$facts->{mem_available_bytes} " .
        "mem_total_bytes=$facts->{mem_total_bytes} " .
        "mem_available_pct=$facts->{mem_available_percent} " .
        "min_free_memory_bytes=$thresholds->{minimum_free}"
    );

    return ($state, $reasons, $facts);
}

sub memory_pressure_gate_met {
    my ($state) = determine_pressure_state();
    return $state eq 'normal' ? 0 : 1;
}

1;
