package Zram::Config::Validator;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Config::Schema qw(default_config merge_defaults);
use Zram::Error qw(fatal);
use Zram::Sizing qw(bytes_to_writeback_pages size_to_bytes);
use Zram::Types qw(
  ensure_bool ensure_percent ensure_positive_uint ensure_psi_millionths
  ensure_sint ensure_uint validate_abs_path validate_device_path validate_page_index_spec
);

our @EXPORT_OK = qw(normalize_config);

sub _get {
    my ($config, $section, $key) = @_;
    return $config->{$section}{$key};
}

sub _device_name_from_path {
    my ($path) = @_;
    my ($name) = $path =~ m{/([^/]+)\z};
    defined $name && $name =~ /\Azram[0-9]+\z/ or fatal("zram.device must end in zramN, got '$path'");
    return $name;
}

sub _join_path {
    my ($left, @parts) = @_;
    $left =~ s{/+\z}{};
    return join '/', $left, @parts;
}

sub _validate_runtime_path {
    my ($label, $path) = @_;
    validate_abs_path($label, $path);
    $path =~ m{\A/run/} or fatal("$label must stay under /run, got '$path'");
}

sub _validate_runtime_child_path {
    my ($label, $path, $runtime_dir) = @_;
    _validate_runtime_path($label, $path);
    my $prefix = $runtime_dir;
    $prefix =~ s{/+\z}{};
    $path =~ m{\A\Q$prefix\E/} or fatal("$label must stay under paths.runtime_dir, got '$path'");
}

sub _validate_log_level {
    my ($value) = @_;
    defined $value && $value =~ /\A(?:debug|info|warning|warn|error|fatal|none)\z/i
        or fatal("runtime.log_level must be debug, info, warning, error, or none");
    $value = lc($value);
    return 'warning' if $value eq 'warn';
    return 'error' if $value eq 'fatal';
    return $value;
}

sub _validate_name_token {
    my ($label, $value) = @_;
    defined $value && $value =~ /\A[A-Za-z0-9_.:+-]+\z/
        or fatal("$label contains unsafe characters: '" . (defined $value ? $value : 'unset') . "'");
    return $value;
}

sub _validate_key_size_bits {
    my ($label, $value) = @_;
    my $bits = ensure_positive_uint($label, $value);
    $bits % 8 == 0 or fatal("$label must be a multiple of 8 bits");
    return $bits;
}

sub _validate_algorithm_params {
    my ($label, $value) = @_;
    return '' if !defined $value || $value eq '';
    length($value) <= 512 or fatal("$label is too large");
    $value !~ /[\x00-\x1f\x7f]/ or fatal("$label contains control characters");
    for my $token (split /\s+/, $value) {
        $token =~ /\A[A-Za-z0-9_.:+-]+=[A-Za-z0-9_.:+-]+\z/
            or fatal("$label contains unsupported parameter token: $token");
    }
    return $value;
}

sub _validate_recompression_type {
    my ($label, $value) = @_;
    defined $value && $value =~ /\A(?:idle|huge_idle|huge)\z/
        or fatal("$label must be idle, huge_idle, or huge, got '" . (defined $value ? $value : 'unset') . "'");
    return $value;
}

sub _ensure_range {
    my ($label, $value, $minimum, $maximum) = @_;
    ($value >= $minimum && $value <= $maximum)
        or fatal("$label must be between $minimum and $maximum, got $value");
    return $value;
}

sub _validate_known_config_keys {
    my ($raw) = @_;
    my $defaults = default_config();
    for my $section (sort keys %{$raw}) {
        exists $defaults->{$section} or fatal("unknown zram config section [$section]");
        ref($raw->{$section}) eq 'HASH' or fatal("invalid zram config section [$section]");
        for my $key (sort keys %{$raw->{$section}}) {
            exists $defaults->{$section}{$key} or fatal("unknown zram config key [$section].$key");
        }
    }
}

sub normalize_config {
    my ($raw) = @_;
    _validate_known_config_keys($raw);
    my $config = merge_defaults($raw);

    my $device = _get($config, 'zram', 'device');
    validate_device_path('zram.device', $device);
    my $device_name = _get($config, 'zram', 'device_name');
    $device_name = _device_name_from_path($device) if !defined $device_name || $device_name eq '';
    $device_name =~ /\Azram[0-9]+\z/ or fatal("zram.device_name must be zramN, got '$device_name'");

    my $sysfs_root = _get($config, 'paths', 'sysfs_root');
    my $debugfs_root = _get($config, 'paths', 'debugfs_root');
    my $procfs_root = _get($config, 'paths', 'procfs_root');
    my $runtime_dir = _get($config, 'paths', 'runtime_dir');
    my $lock_file = _get($config, 'runtime', 'lock_file');
    validate_abs_path('paths.sysfs_root', $sysfs_root);
    validate_abs_path('paths.debugfs_root', $debugfs_root);
    validate_abs_path('paths.procfs_root', $procfs_root);
    _validate_runtime_path('paths.runtime_dir', $runtime_dir);
    _validate_runtime_child_path('runtime.lock_file', $lock_file, $runtime_dir);
    my $metrics_file = _get($config, 'runtime', 'metrics_file');
    _validate_runtime_child_path('runtime.metrics_file', $metrics_file, $runtime_dir)
        if defined $metrics_file && $metrics_file ne '';

    my $backing_dev = _get($config, 'writeback', 'backing_dev');
    validate_device_path('writeback.backing_dev', $backing_dev);
    my $raw_backing_dev = _get($config, 'writeback', 'raw_backing_dev');
    validate_device_path('writeback.raw_backing_dev', $raw_backing_dev) if defined $raw_backing_dev && $raw_backing_dev ne '';
    my $backing_mapper = _validate_name_token('writeback.backing_mapper', _get($config, 'writeback', 'backing_mapper'));

    my %normalized = (
        ZRAM_SWAP_DEVICE => $device,
        ZRAM_SWAP_DEVICE_NAME => $device_name,
        ZRAM_SYSFS_ROOT => $sysfs_root,
        ZRAM_DEBUGFS_ROOT => $debugfs_root,
        ZRAM_PROCFS_ROOT => $procfs_root,
        ZRAM_SYSFS => _join_path($sysfs_root, 'block', $device_name),
        ZRAM_BLOCK_STATE => _join_path($debugfs_root, 'zram', $device_name, 'block_state'),
        ZRAM_RUNTIME_DIR => $runtime_dir,
        ZRAM_LOCK_FILE => $lock_file,
        ZRAM_METRICS_FILE => $metrics_file,
        ZRAM_LOG_LEVEL => _validate_log_level(_get($config, 'runtime', 'log_level')),
        ZRAM_DRY_RUN => ensure_bool('runtime.dry_run', _get($config, 'runtime', 'dry_run')),

        ZRAM_WRITEBACK_BATCH_SIZE_MAX => ensure_positive_uint('limits.writeback_batch_size_max', _get($config, 'limits', 'writeback_batch_size_max')),
        ZRAM_WRITEBACK_PASS_PAGES_MAX => ensure_positive_uint('limits.writeback_pass_pages_max', _get($config, 'limits', 'writeback_pass_pages_max')),
        ZRAM_BLOCK_STATE_MAX_LINES => ensure_positive_uint('limits.block_state_max_lines', _get($config, 'limits', 'block_state_max_lines')),
        ZRAM_BLOCK_STATE_FALLBACK_LINES => ensure_positive_uint('limits.block_state_fallback_lines', _get($config, 'limits', 'block_state_fallback_lines')),
        ZRAM_LOGICAL_BLOCK_SIZE_FALLBACK => ensure_positive_uint('limits.logical_block_size_fallback', _get($config, 'limits', 'logical_block_size_fallback')),
        ZRAM_WRITEBACK_SPEC_MAX_BYTES => ensure_positive_uint('limits.writeback_spec_max_bytes', _get($config, 'limits', 'writeback_spec_max_bytes')),
        ZRAM_WRITEBACK_CHUNKS_PER_CLASS_MAX => ensure_positive_uint('limits.writeback_chunks_per_class_max', _get($config, 'limits', 'writeback_chunks_per_class_max')),
        ZRAM_DAEMON_PSI_WINDOW_MIN_US => ensure_positive_uint('limits.psi_window_min_us', _get($config, 'limits', 'psi_window_min_us')),
        ZRAM_DAEMON_PSI_WINDOW_MAX_US => ensure_positive_uint('limits.psi_window_max_us', _get($config, 'limits', 'psi_window_max_us')),
        ZRAM_DAEMON_SECONDS_MAX => ensure_positive_uint('limits.daemon_seconds_max', _get($config, 'limits', 'daemon_seconds_max')),

        ZRAM_BACKING_DEVICE => $backing_dev,
        ZRAM_BACKING_RAW_DEVICE => $raw_backing_dev,
        ZRAM_BACKING_MAPPER_NAME => $backing_mapper,
        DMCRYPT_EPHEMERAL_CIPHER => _validate_name_token('backing_crypto.cipher', _get($config, 'backing_crypto', 'cipher')),
        DMCRYPT_EPHEMERAL_KEY_SIZE => _validate_key_size_bits('backing_crypto.key_size_bits', _get($config, 'backing_crypto', 'key_size_bits')),
        DMCRYPT_EPHEMERAL_HASH => _validate_name_token('backing_crypto.hash', _get($config, 'backing_crypto', 'hash')),
        DMCRYPT_RANDOM_KEY_FILE => _get($config, 'backing_crypto', 'random_key_file'),
        ZRAM_WRITEBACK_ENABLED => ensure_bool('writeback.enabled', _get($config, 'writeback', 'enabled')),
        ZRAM_COMPRESSED_WRITEBACK => ensure_bool('writeback.compressed_writeback', _get($config, 'writeback', 'compressed_writeback')),
        ZRAM_WRITEBACK_BATCH_SIZE => ensure_positive_uint('writeback.writeback_batch_size', _get($config, 'writeback', 'writeback_batch_size')),
        ZRAM_WRITEBACK_BATCH_SIZE_ADAPTIVE => ensure_bool('writeback.writeback_batch_size_adaptive', _get($config, 'writeback', 'writeback_batch_size_adaptive')),
        ZRAM_WRITEBACK_BATCH_SIZE_NORMAL => ensure_positive_uint('writeback.writeback_batch_size_normal', _get($config, 'writeback', 'writeback_batch_size_normal')),
        ZRAM_WRITEBACK_BATCH_SIZE_PRESSURE => ensure_positive_uint('writeback.writeback_batch_size_pressure', _get($config, 'writeback', 'writeback_batch_size_pressure')),
        ZRAM_WRITEBACK_BATCH_SIZE_EMERGENCY => ensure_positive_uint('writeback.writeback_batch_size_emergency', _get($config, 'writeback', 'writeback_batch_size_emergency')),
        ZRAM_WRITEBACK_BATCH_SIZE_ROTATIONAL_MAX => ensure_positive_uint('writeback.writeback_batch_size_rotational_max', _get($config, 'writeback', 'writeback_batch_size_rotational_max')),
        ZRAM_WRITEBACK_MAX_PAGES_PRESSURE => ensure_positive_uint('writeback.writeback_max_pages_pressure', _get($config, 'writeback', 'writeback_max_pages_pressure')),
        ZRAM_WRITEBACK_MAX_PAGES_EMERGENCY => ensure_positive_uint('writeback.writeback_max_pages_emergency', _get($config, 'writeback', 'writeback_max_pages_emergency')),
        ZRAM_WRITEBACK_LIMIT_ENABLE => ensure_bool('writeback.writeback_limit_enabled', _get($config, 'writeback', 'writeback_limit_enabled')),
        ZRAM_WRITEBACK_LIMIT_PCT => ensure_percent('writeback.writeback_limit_percent', _get($config, 'writeback', 'writeback_limit_percent')),
        ZRAM_DAILY_WRITEBACK_LIMIT_BYTES => size_to_bytes('writeback.daily_writeback_limit', _get($config, 'writeback', 'daily_writeback_limit')),
        ZRAM_MAINTENANCE_PAGE_INDEXES => _get($config, 'writeback', 'maintenance_page_indexes'),

        ZRAM_COMPRESSION_ALGORITHM => _validate_name_token('zram.algorithm', _get($config, 'zram', 'algorithm')),
        ZRAM_ALGORITHM_PARAMS => _validate_algorithm_params('zram.algorithm_params', _get($config, 'zram', 'algorithm_params')),
        ZRAM_DISKSIZE_BYTES => size_to_bytes('zram.disksize', _get($config, 'zram', 'disksize')),
        ZRAM_MEM_LIMIT_BYTES => size_to_bytes('zram.mem_limit', _get($config, 'zram', 'mem_limit')),
        ZRAM_SIZE_PERCENT => ensure_percent('zram.size_percent', _get($config, 'zram', 'size_percent')),
        ZRAM_SIZE_MIN_MIB => ensure_positive_uint('zram.size_min_mib', _get($config, 'zram', 'size_min_mib')),
        ZRAM_SIZE_MAX_MIB => ensure_positive_uint('zram.size_max_mib', _get($config, 'zram', 'size_max_mib')),
        ZRAM_MEM_LIMIT_PERCENT => ensure_percent('zram.mem_limit_percent', _get($config, 'zram', 'mem_limit_percent')),
        ZRAM_MAX_COMP_STREAMS => ensure_uint('zram.max_comp_streams', _get($config, 'zram', 'max_comp_streams')),
        ZRAM_SWAP_PRIORITY => ensure_sint('zram.swap_priority', _get($config, 'zram', 'swap_priority')),

        ZRAM_IDLE_WRITEBACK_ENABLE => ensure_bool('policy.idle_writeback_enabled', _get($config, 'policy', 'idle_writeback_enabled')),
        ZRAM_PRESSURE_ENABLED => ensure_bool('policy.pressure_enabled', _get($config, 'policy', 'pressure_enabled')),
        ZRAM_PRESSURE_MEM_AVAILABLE_PCT => ensure_percent('policy.pressure_mem_available_percent', _get($config, 'policy', 'pressure_mem_available_percent')),
        ZRAM_EMERGENCY_MEM_AVAILABLE_PCT => ensure_percent('policy.emergency_mem_available_percent', _get($config, 'policy', 'emergency_mem_available_percent')),
        ZRAM_PRESSURE_SOME_AVG10_THRESHOLD => _get($config, 'policy', 'memory_some_avg10_min'),
        ZRAM_PRESSURE_FULL_AVG10_THRESHOLD => _get($config, 'policy', 'memory_full_avg10_min'),
        ZRAM_EMERGENCY_SOME_AVG10_THRESHOLD => _get($config, 'policy', 'emergency_some_avg10_min'),
        ZRAM_EMERGENCY_FULL_AVG10_THRESHOLD => _get($config, 'policy', 'emergency_full_avg10_min'),
        ZRAM_MIN_FREE_MEMORY_BYTES => size_to_bytes('policy.min_free_memory', _get($config, 'policy', 'min_free_memory')),
        ZRAM_WRITEBACK_MIN_REMAINING_PAGES => ensure_uint('policy.writeback_min_remaining_pages', _get($config, 'policy', 'writeback_min_remaining_pages')),
        ZRAM_DAEMON_ENABLED => ensure_bool('daemon.enabled', _get($config, 'daemon', 'enabled')),
        ZRAM_DAEMON_PSI_WINDOW_US => ensure_positive_uint('daemon.psi_window_us', _get($config, 'daemon', 'psi_window_us')),
        ZRAM_DAEMON_PSI_SOME_STALL_US => ensure_uint('daemon.psi_some_stall_us', _get($config, 'daemon', 'psi_some_stall_us')),
        ZRAM_DAEMON_PSI_FULL_STALL_US => ensure_uint('daemon.psi_full_stall_us', _get($config, 'daemon', 'psi_full_stall_us')),
        ZRAM_DAEMON_POLL_TIMEOUT_SEC => ensure_positive_uint('daemon.poll_timeout_seconds', _get($config, 'daemon', 'poll_timeout_seconds')),
        ZRAM_DAEMON_PRESSURE_COOLDOWN_SEC => ensure_uint('daemon.pressure_cooldown_seconds', _get($config, 'daemon', 'pressure_cooldown_seconds')),
        ZRAM_DAEMON_EMERGENCY_COOLDOWN_SEC => ensure_uint('daemon.emergency_cooldown_seconds', _get($config, 'daemon', 'emergency_cooldown_seconds')),
        ZRAM_DAEMON_RECOVERY_HYSTERESIS_SEC => ensure_uint('daemon.recovery_hysteresis_seconds', _get($config, 'daemon', 'recovery_hysteresis_seconds')),

        ZRAM_HOT_AGE_SEC => ensure_positive_uint('writeback.hot_age_seconds', _get($config, 'writeback', 'hot_age_seconds')),
        ZRAM_IDLE_AGE_SEC => ensure_uint('writeback.idle_age_seconds', _get($config, 'writeback', 'idle_age_seconds')),
        ZRAM_PRESSURE_IDLE_AGE_SEC => ensure_uint('writeback.pressure_idle_age_seconds', _get($config, 'writeback', 'pressure_idle_age_seconds')),
        ZRAM_EMERGENCY_IDLE_AGE_SEC => ensure_uint('writeback.emergency_idle_age_seconds', _get($config, 'writeback', 'emergency_idle_age_seconds')),
        ZRAM_COLD_TIER_ENABLE => ensure_bool('cold_tier.enabled', _get($config, 'cold_tier', 'enabled')),
        ZRAM_COLD_TIER_MIN_ZRAM_FILL_PCT => ensure_percent('cold_tier.min_zram_fill_percent', _get($config, 'cold_tier', 'min_zram_fill_percent')),
        ZRAM_COLD_TIER_RECOMPRESS_ENABLE => ensure_bool('recompression.enabled', _get($config, 'recompression', 'enabled')),
        ZRAM_COLD_TIER_WRITEBACK_ENABLE => ensure_bool('cold_tier.writeback_enabled', _get($config, 'cold_tier', 'writeback_enabled')),
        ZRAM_COLD_TIER_COMPACT_ENABLE => ensure_bool('recompression.compact_after_actions', _get($config, 'recompression', 'compact_after_actions')),
        ZRAM_COLD_TIER_MIN_COLD_PAGES => ensure_positive_uint('cold_tier.min_cold_pages', _get($config, 'cold_tier', 'min_cold_pages')),
        ZRAM_COLD_TIER_MIN_IDLE_PAGES => ensure_positive_uint('cold_tier.min_idle_pages', _get($config, 'cold_tier', 'min_idle_pages')),
        ZRAM_COLD_TIER_MIN_HUGE_IDLE_PAGES => ensure_positive_uint('cold_tier.min_huge_idle_pages', _get($config, 'cold_tier', 'min_huge_idle_pages')),
        ZRAM_COLD_TIER_MIN_HUGE_PAGES => ensure_positive_uint('cold_tier.min_huge_pages', _get($config, 'cold_tier', 'min_huge_pages')),
        ZRAM_COLD_TIER_MIN_INCOMPRESSIBLE_PAGES => ensure_positive_uint('cold_tier.min_incompressible_pages', _get($config, 'cold_tier', 'min_incompressible_pages')),
        ZRAM_COLD_TIER_RECOMPRESS_IDLE_MAX_PAGES => ensure_positive_uint('cold_tier.recompress_idle_max_pages', _get($config, 'cold_tier', 'recompress_idle_max_pages')),
        ZRAM_COLD_TIER_RECOMPRESS_HUGE_IDLE_MAX_PAGES => ensure_positive_uint('cold_tier.recompress_huge_idle_max_pages', _get($config, 'cold_tier', 'recompress_huge_idle_max_pages')),
        ZRAM_COLD_TIER_RECOMPRESS_HUGE_MAX_PAGES => ensure_positive_uint('cold_tier.recompress_huge_max_pages', _get($config, 'cold_tier', 'recompress_huge_max_pages')),
        ZRAM_COLD_TIER_WRITEBACK_INCOMPRESSIBLE_MAX_PAGES => ensure_positive_uint('cold_tier.writeback_incompressible_max_pages', _get($config, 'cold_tier', 'writeback_incompressible_max_pages')),
        ZRAM_COLD_TIER_WRITEBACK_SPEC_CHUNK_PAGE_LIMIT => ensure_positive_uint('cold_tier.writeback_spec_chunk_page_limit', _get($config, 'cold_tier', 'writeback_spec_chunk_page_limit')),
    );
    validate_device_path('backing_crypto.random_key_file', $normalized{DMCRYPT_RANDOM_KEY_FILE});

    $normalized{ZRAM_PRESSURE_SOME_AVG10_THRESHOLD_UNITS} =
        ensure_psi_millionths('policy.memory_some_avg10_min', $normalized{ZRAM_PRESSURE_SOME_AVG10_THRESHOLD});
    $normalized{ZRAM_PRESSURE_FULL_AVG10_THRESHOLD_UNITS} =
        ensure_psi_millionths('policy.memory_full_avg10_min', $normalized{ZRAM_PRESSURE_FULL_AVG10_THRESHOLD});
    $normalized{ZRAM_EMERGENCY_SOME_AVG10_THRESHOLD_UNITS} =
        ensure_psi_millionths('policy.emergency_some_avg10_min', $normalized{ZRAM_EMERGENCY_SOME_AVG10_THRESHOLD});
    $normalized{ZRAM_EMERGENCY_FULL_AVG10_THRESHOLD_UNITS} =
        ensure_psi_millionths('policy.emergency_full_avg10_min', $normalized{ZRAM_EMERGENCY_FULL_AVG10_THRESHOLD});
    for my $tier (1 .. 3) {
        my $section = "recompression_tier$tier";
        my $prefix = "ZRAM_TIER$tier";
        $normalized{"${prefix}_ENABLE"} = ensure_bool("$section.enabled", _get($config, $section, 'enabled'));
        $normalized{"${prefix}_TYPE"} = _validate_recompression_type("$section.type", _get($config, $section, 'type'));
        $normalized{"${prefix}_ALGORITHM"} = _validate_name_token("$section.algorithm", _get($config, $section, 'algorithm'));
        $normalized{"${prefix}_PRIORITY"} = ensure_positive_uint("$section.priority", _get($config, $section, 'priority'));
        $normalized{"${prefix}_LEVEL"} = ensure_uint("$section.level", _get($config, $section, 'level'));
        $normalized{"${prefix}_THRESHOLD_BYTES"} = ensure_positive_uint("$section.threshold_bytes", _get($config, $section, 'threshold_bytes'));
        for my $state (qw(normal pressure emergency)) {
            my $key = "max_pages_$state";
            $normalized{"${prefix}_MAX_PAGES_" . uc($state)} = ensure_uint("$section.$key", _get($config, $section, $key));
        }
    }
    my %recompression_priority_tiers;
    for my $tier (1 .. 3) {
        my $prefix = "ZRAM_TIER$tier";
        next if !$normalized{"${prefix}_ENABLE"};
        my $priority = $normalized{"${prefix}_PRIORITY"};
        if (exists $recompression_priority_tiers{$priority}) {
            fatal(
                "enabled recompression tiers $recompression_priority_tiers{$priority} and $tier "
                . "must not share priority $priority"
            );
        }
        $recompression_priority_tiers{$priority} = $tier;
    }
    validate_page_index_spec(
        $normalized{ZRAM_MAINTENANCE_PAGE_INDEXES},
        $normalized{ZRAM_WRITEBACK_SPEC_MAX_BYTES},
    );
    $normalized{ZRAM_SIZE_PERCENT} > 0
        or fatal('zram.size_percent must be greater than zero');
    $normalized{ZRAM_MEM_LIMIT_PERCENT} > 0
        or fatal('zram.mem_limit_percent must be greater than zero');
    $normalized{ZRAM_SIZE_MIN_MIB}
        <= $normalized{ZRAM_SIZE_MAX_MIB}
        or fatal('zram.size_min_mib must not exceed zram.size_max_mib');
    if ($normalized{ZRAM_WRITEBACK_ENABLED} && $normalized{ZRAM_WRITEBACK_LIMIT_ENABLE}) {
        $normalized{ZRAM_WRITEBACK_LIMIT_PCT} > 0
            or fatal('writeback.writeback_limit_percent must be greater than zero when writeback limiting is enabled');
    }
    if ($normalized{ZRAM_DAILY_WRITEBACK_LIMIT_BYTES} > 0
        && bytes_to_writeback_pages(
            'writeback.daily_writeback_limit',
            $normalized{ZRAM_DAILY_WRITEBACK_LIMIT_BYTES},
        ) <= 0) {
        fatal('writeback.daily_writeback_limit must be at least one 4 KiB page when nonzero');
    }
    $normalized{ZRAM_BLOCK_STATE_FALLBACK_LINES}
        <= $normalized{ZRAM_BLOCK_STATE_MAX_LINES}
        or fatal('limits.block_state_fallback_lines must not exceed limits.block_state_max_lines');
    $normalized{ZRAM_DAEMON_PSI_WINDOW_MIN_US}
        <= $normalized{ZRAM_DAEMON_PSI_WINDOW_MAX_US}
        or fatal('limits.psi_window_min_us must not exceed limits.psi_window_max_us');
    $normalized{ZRAM_WRITEBACK_BATCH_SIZE_NORMAL}
        <= $normalized{ZRAM_WRITEBACK_BATCH_SIZE_PRESSURE}
        or fatal('writeback batch sizes must be nondecreasing from normal to pressure');
    $normalized{ZRAM_WRITEBACK_BATCH_SIZE_PRESSURE}
        <= $normalized{ZRAM_WRITEBACK_BATCH_SIZE_EMERGENCY}
        or fatal('writeback batch sizes must be nondecreasing from pressure to emergency');
    $normalized{ZRAM_WRITEBACK_MAX_PAGES_PRESSURE}
        <= $normalized{ZRAM_WRITEBACK_MAX_PAGES_EMERGENCY}
        or fatal('writeback max pages must be nondecreasing from pressure to emergency');
    $normalized{ZRAM_EMERGENCY_MEM_AVAILABLE_PCT}
        <= $normalized{ZRAM_PRESSURE_MEM_AVAILABLE_PCT}
        or fatal('emergency MemAvailable percentage must not exceed the pressure threshold');
    $normalized{ZRAM_EMERGENCY_SOME_AVG10_THRESHOLD_UNITS}
        >= $normalized{ZRAM_PRESSURE_SOME_AVG10_THRESHOLD_UNITS}
        or fatal('emergency PSI some threshold must not be below the pressure threshold');
    $normalized{ZRAM_EMERGENCY_FULL_AVG10_THRESHOLD_UNITS}
        >= $normalized{ZRAM_PRESSURE_FULL_AVG10_THRESHOLD_UNITS}
        or fatal('emergency PSI full threshold must not be below the pressure threshold');
    $normalized{ZRAM_PRESSURE_IDLE_AGE_SEC}
        <= $normalized{ZRAM_IDLE_AGE_SEC}
        or fatal('pressure idle age must not exceed normal idle age');
    $normalized{ZRAM_EMERGENCY_IDLE_AGE_SEC}
        <= $normalized{ZRAM_PRESSURE_IDLE_AGE_SEC}
        or fatal('emergency idle age must not exceed pressure idle age');
    for my $key (qw(
        ZRAM_IDLE_AGE_SEC
        ZRAM_PRESSURE_IDLE_AGE_SEC
        ZRAM_EMERGENCY_IDLE_AGE_SEC
    )) {
        next if $normalized{$key} == 0;
        $normalized{ZRAM_HOT_AGE_SEC} <= $normalized{$key}
            or fatal("$key must be zero or at least writeback.hot_age_seconds");
    }
    for my $tier (1 .. 3) {
        my $prefix = "ZRAM_TIER$tier";
        $normalized{"${prefix}_MAX_PAGES_NORMAL"}
            <= $normalized{"${prefix}_MAX_PAGES_PRESSURE"}
            or fatal("recompression tier $tier max pages must be nondecreasing from normal to pressure");
        $normalized{"${prefix}_MAX_PAGES_PRESSURE"}
            <= $normalized{"${prefix}_MAX_PAGES_EMERGENCY"}
            or fatal("recompression tier $tier max pages must be nondecreasing from pressure to emergency");
    }
    for my $key (qw(
        ZRAM_WRITEBACK_BATCH_SIZE
        ZRAM_WRITEBACK_BATCH_SIZE_NORMAL
        ZRAM_WRITEBACK_BATCH_SIZE_PRESSURE
        ZRAM_WRITEBACK_BATCH_SIZE_EMERGENCY
        ZRAM_WRITEBACK_BATCH_SIZE_ROTATIONAL_MAX
    )) {
        _ensure_range(
            $key,
            $normalized{$key},
            1,
            $normalized{ZRAM_WRITEBACK_BATCH_SIZE_MAX},
        );
    }
    for my $key (qw(
        ZRAM_WRITEBACK_BATCH_SIZE_NORMAL
        ZRAM_WRITEBACK_BATCH_SIZE_PRESSURE
        ZRAM_WRITEBACK_BATCH_SIZE_EMERGENCY
        ZRAM_WRITEBACK_BATCH_SIZE_ROTATIONAL_MAX
    )) {
        $normalized{$key} <= $normalized{ZRAM_WRITEBACK_BATCH_SIZE}
            or fatal("$key must not exceed writeback.writeback_batch_size");
    }
    for my $key (qw(
        ZRAM_WRITEBACK_MAX_PAGES_PRESSURE
        ZRAM_WRITEBACK_MAX_PAGES_EMERGENCY
    )) {
        _ensure_range(
            $key,
            $normalized{$key},
            1,
            $normalized{ZRAM_WRITEBACK_PASS_PAGES_MAX},
        );
    }
    _ensure_range(
        'daemon.psi_window_us',
        $normalized{ZRAM_DAEMON_PSI_WINDOW_US},
        $normalized{ZRAM_DAEMON_PSI_WINDOW_MIN_US},
        $normalized{ZRAM_DAEMON_PSI_WINDOW_MAX_US},
    );
    for my $key (qw(
        ZRAM_DAEMON_PSI_SOME_STALL_US
        ZRAM_DAEMON_PSI_FULL_STALL_US
    )) {
        $normalized{$key} <= $normalized{ZRAM_DAEMON_PSI_WINDOW_US}
            or fatal("$key must not exceed daemon.psi_window_us");
    }
    for my $key (qw(
        ZRAM_DAEMON_POLL_TIMEOUT_SEC
        ZRAM_DAEMON_PRESSURE_COOLDOWN_SEC
        ZRAM_DAEMON_EMERGENCY_COOLDOWN_SEC
        ZRAM_DAEMON_RECOVERY_HYSTERESIS_SEC
    )) {
        _ensure_range($key, $normalized{$key}, 0, $normalized{ZRAM_DAEMON_SECONDS_MAX});
    }
    $normalized{ZRAM_DAEMON_EMERGENCY_COOLDOWN_SEC}
        <= $normalized{ZRAM_DAEMON_PRESSURE_COOLDOWN_SEC}
        or fatal('daemon emergency cooldown must not exceed the pressure cooldown');
    if ($normalized{ZRAM_DAEMON_ENABLED}
        && $normalized{ZRAM_DAEMON_PSI_SOME_STALL_US} <= 0
        && $normalized{ZRAM_DAEMON_PSI_FULL_STALL_US} <= 0) {
        fatal('daemon requires at least one positive PSI trigger threshold');
    }

    return \%normalized;
}

1;
