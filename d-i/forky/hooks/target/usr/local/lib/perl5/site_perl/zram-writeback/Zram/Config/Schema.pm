package Zram::Config::Schema;

use strict;
use warnings;

use Exporter qw(import);

our @EXPORT_OK = qw(default_config merge_defaults);

sub default_config {
    return {
        zram => {
            device => '/dev/zram0',
            device_name => '',
            algorithm => 'lz4',
            algorithm_params => '',
            disksize => '',
            size_percent => '100',
            size_min_mib => '2048',
            size_max_mib => '4096',
            mem_limit => '',
            mem_limit_percent => '65',
            max_comp_streams => '0',
            swap_priority => '300',
        },
        writeback => {
            enabled => '1',
            backing_dev => '/dev/mapper/zram-writeback',
            raw_backing_dev => '',
            backing_mapper => 'zram-writeback',
            hot_age_seconds => '300',
            idle_age_seconds => '1800',
            pressure_idle_age_seconds => '900',
            emergency_idle_age_seconds => '300',
            compressed_writeback => '1',
            writeback_batch_size => undef,
            writeback_batch_size_adaptive => undef,
            writeback_batch_size_normal => undef,
            writeback_batch_size_pressure => undef,
            writeback_batch_size_emergency => undef,
            writeback_batch_size_rotational_max => undef,
            writeback_max_pages_pressure => undef,
            writeback_max_pages_emergency => undef,
            writeback_limit_enabled => '1',
            writeback_limit_percent => '25',
            daily_writeback_limit => '',
            maintenance_page_indexes => '',
        },
        backing_crypto => {
            cipher => 'aes-xts-plain64',
            key_size_bits => '512',
            hash => 'sha256',
            random_key_file => '/dev/urandom',
        },
        recompression => {
            enabled => '1',
            compact_after_actions => '1',
        },
        recompression_tier1 => {
            enabled => '1',
            type => 'idle',
            algorithm => 'lzo-rle',
            priority => '1',
            level => '0',
            threshold_bytes => '2048',
            max_pages_normal => '65536',
            max_pages_pressure => '131072',
            max_pages_emergency => '262144',
        },
        recompression_tier2 => {
            enabled => '1',
            type => 'huge_idle',
            algorithm => 'zstd',
            priority => '2',
            level => '6',
            threshold_bytes => '3000',
            max_pages_normal => '32768',
            max_pages_pressure => '65536',
            max_pages_emergency => '131072',
        },
        recompression_tier3 => {
            enabled => '1',
            type => 'huge',
            algorithm => 'zstd',
            priority => '3',
            level => '3',
            threshold_bytes => '3584',
            max_pages_normal => '0',
            max_pages_pressure => '4096',
            max_pages_emergency => '16384',
        },
        cold_tier => {
            enabled => '1',
            writeback_enabled => '1',
            min_zram_fill_percent => '50',
            min_cold_pages => '256',
            min_idle_pages => '128',
            min_huge_idle_pages => '1',
            min_huge_pages => '1',
            min_incompressible_pages => '1',
            recompress_idle_max_pages => '131072',
            recompress_huge_idle_max_pages => '65536',
            recompress_huge_max_pages => '4096',
            writeback_incompressible_max_pages => '16384',
            writeback_spec_chunk_page_limit => '2048',
        },
        policy => {
            idle_writeback_enabled => '1',
            pressure_enabled => '1',
            pressure_mem_available_percent => '12',
            emergency_mem_available_percent => '6',
            memory_some_avg10_min => '0.50',
            memory_full_avg10_min => '0.30',
            emergency_some_avg10_min => '8.00',
            emergency_full_avg10_min => '1.50',
            min_free_memory => '0',
            writeback_min_remaining_pages => '1',
        },
        daemon => {
            enabled => '1',
            psi_window_us => '10000000',
            psi_some_stall_us => '150000',
            psi_full_stall_us => '50000',
            poll_timeout_seconds => '10',
            pressure_cooldown_seconds => '120',
            emergency_cooldown_seconds => '30',
            recovery_hysteresis_seconds => '180',
        },
        limits => {
            writeback_batch_size_max => undef,
            writeback_pass_pages_max => undef,
            block_state_max_lines => undef,
            block_state_fallback_lines => undef,
            logical_block_size_fallback => undef,
            writeback_spec_max_bytes => undef,
            writeback_chunks_per_class_max => undef,
            psi_window_min_us => undef,
            psi_window_max_us => undef,
            daemon_seconds_max => undef,
        },
        paths => {
            sysfs_root => '/sys',
            debugfs_root => '/sys/kernel/debug',
            procfs_root => '/proc',
            runtime_dir => '/run/zram',
        },
        runtime => {
            lock_file => '/run/zram/zram-writeback.lock',
            metrics_file => '',
            log_level => 'error',
            dry_run => '0',
        },
    };
}

sub merge_defaults {
    my ($input) = @_;
    my $merged = default_config();
    for my $section (keys %{$input}) {
        $merged->{$section} ||= {};
        for my $key (keys %{$input->{$section}}) {
            $merged->{$section}{$key} = $input->{$section}{$key};
        }
    }
    return $merged;
}

1;
