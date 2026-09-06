package Zram::Metrics;

use strict;
use warnings;

use Exporter qw(import);
use POSIX qw(strftime);
use Zram::AtomicFile qw(write_atomic_text);
use Zram::Config qw(cfg cfg_default);
use Zram::Debugfs qw(block_state_path);
use Zram::Error qw(fatal);
use Zram::Lock qw(ensure_runtime_dir);
use Zram::Logger qw(log_enabled log_msg);
use Zram::Procfs qw(memory_pressure_snapshot);
use Zram::Stats qw(read_zram_stat_attrs zram_stat_names);
use Zram::Sysfs qw(read_first_line read_uint_attr);
use Zram::Tuning qw(writeback_tuning_snapshot);

our @EXPORT_OK = qw(
  snapshot_file capture_zram_state new_range_builder add_page_index_range finish_page_index_ranges
  block_state_authoritative block_state_line_limit candidate_count has_candidate
  has_candidate_at_least has_huge_idle_candidate
);

use constant MAX_BLOCK_STATE_LINE_BYTES => 4_096;

sub snapshot_file {
    my $configured = cfg_default('ZRAM_METRICS_FILE', '');
    return $configured if defined $configured && $configured ne '';
    my $dev = cfg('ZRAM_SWAP_DEVICE');
    $dev =~ s{\A.*/}{};
    return cfg('ZRAM_RUNTIME_DIR') . "/$dev.metrics";
}

sub block_state_line_limit {
    my ($disksize, $logical_block_size, %limits) = @_;
    my $maximum = $limits{maximum};
    my $fallback = $limits{fallback};
    my $logical_block_size_fallback = $limits{logical_block_size_fallback};
    defined $maximum && $maximum > 0 or fatal('block-state maximum line limit must be positive');
    defined $fallback && $fallback > 0 or fatal('block-state fallback line limit must be positive');
    $fallback <= $maximum or fatal('block-state fallback line limit must not exceed the maximum');
    defined $logical_block_size_fallback && $logical_block_size_fallback > 0
        or fatal('logical block size fallback must be positive');
    return $fallback if !defined $disksize || $disksize <= 0;
    $logical_block_size = $logical_block_size_fallback
        if !defined $logical_block_size || $logical_block_size <= 0;
    my $device_pages = int(($disksize + $logical_block_size - 1) / $logical_block_size);
    my $limit = $device_pages + 1;
    return $limit < $maximum ? $limit : $maximum;
}

sub _scan_block_state {
    my ($path, $line_limit, $callback) = @_;
    defined $line_limit && $line_limit > 0
        or fatal('block-state line limit must be positive');
    ref $callback eq 'CODE'
        or fatal('block-state scan requires a callback');

    open my $fh, '<:raw', $path or return {
        available => 0,
        truncated => 0,
        scanned_lines => 0,
    };

    my %scan = (
        available => 1,
        truncated => 0,
        scanned_lines => 0,
    );
    my $pending = '';
    my $stop = 0;

    while (!$stop) {
        my $read_size = MAX_BLOCK_STATE_LINE_BYTES + 1 - length($pending);
        $read_size > 0
            or fatal("zram block_state line exceeds byte limit: $path");
        my $read = read($fh, my $chunk, $read_size);
        defined $read
            or fatal("failed to read zram block_state $path: $!");
        last if $read == 0;
        $pending .= $chunk;

        while (1) {
            my $newline = index($pending, "\n");
            last if $newline < 0;
            my $line = substr($pending, 0, $newline + 1, '');
            length($line) <= MAX_BLOCK_STATE_LINE_BYTES
                or fatal("zram block_state line exceeds byte limit: $path");
            $scan{scanned_lines}++;
            if ($scan{scanned_lines} > $line_limit) {
                $scan{truncated} = 1;
                $stop = 1;
                last;
            }
            $callback->($line);
        }
        if (!$stop) {
            length($pending) <= MAX_BLOCK_STATE_LINE_BYTES
                or fatal("zram block_state line exceeds byte limit: $path");
        }
    }

    if (!$stop && length($pending)) {
        length($pending) <= MAX_BLOCK_STATE_LINE_BYTES
            or fatal("zram block_state line exceeds byte limit: $path");
        $scan{scanned_lines}++;
        if ($scan{scanned_lines} > $line_limit) {
            $scan{truncated} = 1;
        } else {
            $callback->($pending);
        }
    }
    close $fh or fatal("failed to close zram block_state $path: $!");
    return \%scan;
}

sub capture_zram_state {
    my ($phase, %opts) = @_;
    my $sysfs = cfg('ZRAM_SYSFS');
    my $metrics_file = snapshot_file();
    my $block_state = block_state_path();
    my $now_epoch = time;
    my $uptime = read_first_line(cfg('ZRAM_PROCFS_ROOT') . '/uptime') || '0';
    my ($uptime_sec) = $uptime =~ /\A([0-9]+)(?:\.[0-9]+)?/;
    $uptime_sec = 0 if !defined $uptime_sec;
    my $hot_age_sec = cfg('ZRAM_HOT_AGE_SEC');
    my $idle_age_sec = exists $opts{idle_age_sec} ? $opts{idle_age_sec} : cfg('ZRAM_IDLE_AGE_SEC');
    my $scan_block_state = exists $opts{scan_block_state} ? $opts{scan_block_state} : 1;
    my $chunk_page_limit = cfg('ZRAM_COLD_TIER_WRITEBACK_SPEC_CHUNK_PAGE_LIMIT');
    my $writeback_class_caps = $opts{writeback_class_caps} || {};
    my $state = exists $opts{state} ? $opts{state} : 'normal';
    my $disksize = read_uint_attr("$sysfs/disksize");
    my $logical_block_size = read_uint_attr("$sysfs/queue/logical_block_size");
    my $block_state_line_limit = block_state_line_limit(
        $disksize,
        $logical_block_size,
        maximum => cfg('ZRAM_BLOCK_STATE_MAX_LINES'),
        fallback => cfg('ZRAM_BLOCK_STATE_FALLBACK_LINES'),
        logical_block_size_fallback => cfg('ZRAM_LOGICAL_BLOCK_SIZE_FALLBACK'),
    );
    my $pressure = memory_pressure_snapshot();
    my $tuning = writeback_tuning_snapshot($state, undef);

    my %stats = (
        zram_fill_percent => 0,
        block_state_available => 0,
        block_state_truncated => 0,
        block_state_scanned_lines => 0,
        block_state_line_limit => $block_state_line_limit,
        tracked_pages => 0,
        hot_pages => 0,
        warm_pages => 0,
        cold_pages => 0,
        same_pages => 0,
        written_back_pages => 0,
        skipped_same_or_written_pages => 0,
        huge_pages => 0,
        huge_hot_pages => 0,
        huge_cold_pages => 0,
        huge_idle_pages => 0,
        huge_idle_hot_pages => 0,
        huge_idle_cold_pages => 0,
        idle_pages => 0,
        idle_hot_pages => 0,
        idle_cold_pages => 0,
        recompressed_pages => 0,
        incompressible_pages => 0,
        incompressible_hot_pages => 0,
        incompressible_cold_pages => 0,
        targeted_idle_pages => 0,
        targeted_huge_idle_pages => 0,
        targeted_incompressible_pages => 0,
        targeted_specs_capped => 0,
        max_page_age_sec => 0,
        idle_writeback_specs => [],
        huge_idle_writeback_specs => [],
        incompressible_writeback_specs => [],
        bd_pages => 0,
        bd_reads => 0,
        bd_writes => 0,
        mem_available_bytes => $pressure->{mem_available_bytes},
        mem_total_bytes => $pressure->{mem_total_bytes},
        psi_some_avg10_millionths => $pressure->{psi_some_avg10_millionths},
        psi_full_avg10_millionths => $pressure->{psi_full_avg10_millionths},
        writeback_batch_size_effective => $tuning->{effective_batch_size},
        writeback_batch_size_configured_max => $tuning->{configured_max},
        writeback_batch_size_actual => read_uint_attr("$sysfs/writeback_batch_size") || 0,
        writeback_pass_page_limit => $tuning->{pass_page_limit},
        writeback_limit_enabled => read_uint_attr("$sysfs/writeback_limit_enable") || 0,
        writeback_limit_remaining => read_uint_attr("$sysfs/writeback_limit") || 0,
        backing_queue_depth => defined $tuning->{queue_depth} ? $tuning->{queue_depth} : 0,
        backing_rotational => defined $tuning->{rotational} ? $tuning->{rotational} : -1,
    );
    my %range_builders;
    for my $class (qw(idle huge_idle incompressible)) {
        next if !exists $writeback_class_caps->{$class};
        my $cap = $writeback_class_caps->{$class};
        next if defined $cap && $cap <= 0;
        $range_builders{$class} = new_range_builder(
            max_pages => defined $cap ? $cap : 0,
            chunk_page_limit => $chunk_page_limit,
            max_spec_bytes => cfg('ZRAM_WRITEBACK_SPEC_MAX_BYTES'),
            max_chunks => cfg('ZRAM_WRITEBACK_CHUNKS_PER_CLASS_MAX'),
        );
    }

    if ($scan_block_state) {
        my $scan = _scan_block_state($block_state, $block_state_line_limit, sub {
            my ($line) = @_;
            $line =~ /\A\s*(\d+)\s+([0-9]+)(?:\.[0-9]+)?\s+(\S+)/ or return;
            my $page_index = 0 + $1;
            my $atime = 0 + $2;
            my $flags = $3;
            my $age = $uptime_sec - $atime;
            $age = 0 if $age < 0;
            my $is_hot = $age <= $hot_age_sec;
            my $is_cold = $idle_age_sec > 0 && $age >= $idle_age_sec;
            my $is_idle = index($flags, 'i') >= 0;
            my $is_huge = index($flags, 'h') >= 0;
            my $is_incompressible = index($flags, 'n') >= 0;
            my $is_same = index($flags, 's') >= 0;
            my $is_written = index($flags, 'w') >= 0;
            my $writeback_worthy = !$is_same && !$is_written;

            $stats{tracked_pages}++;
            if ($is_hot) {
                $stats{hot_pages}++;
            } elsif ($is_cold) {
                $stats{cold_pages}++;
            } else {
                $stats{warm_pages}++;
            }
            $stats{same_pages}++ if $is_same;
            $stats{written_back_pages}++ if $is_written;
            $stats{skipped_same_or_written_pages}++ if $is_same || $is_written;
            if ($is_huge) {
                $stats{huge_pages}++;
                $stats{huge_hot_pages}++ if $is_hot;
                $stats{huge_cold_pages}++ if $is_cold;
            }
            if ($is_idle) {
                $stats{idle_pages}++;
                $stats{idle_hot_pages}++ if $is_hot;
                $stats{idle_cold_pages}++ if $is_cold;
            }
            if ($is_huge && $is_idle) {
                $stats{huge_idle_pages}++;
                $stats{huge_idle_hot_pages}++ if $is_hot;
                $stats{huge_idle_cold_pages}++ if $is_cold;
            }
            $stats{recompressed_pages}++ if index($flags, 'r') >= 0;
            if ($is_incompressible) {
                $stats{incompressible_pages}++;
                $stats{incompressible_hot_pages}++ if $is_hot;
                $stats{incompressible_cold_pages}++ if $is_cold;
            }
            $stats{max_page_age_sec} = $age if $age > $stats{max_page_age_sec};

            my $age_safe = $idle_age_sec == 0 || $is_cold;
            if (exists $range_builders{idle}
                && $writeback_worthy && $is_idle && $age_safe && (!$is_hot || $idle_age_sec == 0)) {
                add_page_index_range($range_builders{idle}, $page_index);
            }
            if (exists $range_builders{huge_idle}
                && $writeback_worthy && !$is_incompressible && $is_huge && $is_idle
                && $age_safe && (!$is_hot || $idle_age_sec == 0)) {
                add_page_index_range($range_builders{huge_idle}, $page_index);
            }
            if (exists $range_builders{incompressible}
                && $writeback_worthy && $is_incompressible
                && ($is_cold || $is_idle) && (!$is_hot || $idle_age_sec == 0)) {
                add_page_index_range($range_builders{incompressible}, $page_index);
            }
        });
        $stats{block_state_available} = $scan->{available};
        $stats{block_state_truncated} = $scan->{truncated};
        $stats{block_state_scanned_lines} = $scan->{scanned_lines};
    }

    for my $class (qw(idle huge_idle incompressible)) {
        my $builder = $range_builders{$class};
        my $spec_key = $class . '_writeback_specs';
        my $targeted_key = 'targeted_' . $class . '_pages';
        my $emitted_key = 'emitted_' . $class . '_pages';
        if ($builder) {
            $stats{$spec_key} = [finish_page_index_ranges($builder)];
            $stats{$targeted_key} = $builder->{pages};
            $stats{$emitted_key} = $builder->{emitted_pages};
            next;
        }
        $stats{$spec_key} = [];
        $stats{$targeted_key} = 0;
        $stats{$emitted_key} = 0;
    }
    $stats{idle_writeback_chunks} = scalar @{$stats{idle_writeback_specs}};
    $stats{huge_idle_writeback_chunks} = scalar @{$stats{huge_idle_writeback_specs}};
    $stats{incompressible_writeback_chunks} = scalar @{$stats{incompressible_writeback_specs}};
    $stats{targeted_specs_truncated} =
        (($range_builders{idle} && $range_builders{idle}->{truncated})
        || ($range_builders{huge_idle} && $range_builders{huge_idle}->{truncated})
        || ($range_builders{incompressible} && $range_builders{incompressible}->{truncated})) ? 1 : 0;
    $stats{targeted_specs_capped} =
        (($range_builders{idle} && $range_builders{idle}->{capped})
        || ($range_builders{huge_idle} && $range_builders{huge_idle}->{capped})
        || ($range_builders{incompressible} && $range_builders{incompressible}->{capped})) ? 1 : 0;
    my $stat_attrs = read_zram_stat_attrs($sysfs);
    my $mm_stat = $stat_attrs->{parsed}{mm_stat};
    my $orig_data_size = $mm_stat->{orig_data_size} || 0;
    $stats{zram_fill_percent} =
        defined $disksize && $disksize > 0 ? int($orig_data_size * 100 / $disksize) : 0;
    my $bd_stat = $stat_attrs->{parsed}{bd_stat};
    $stats{bd_pages} = $bd_stat->{bd_count} if defined $bd_stat->{bd_count};
    $stats{bd_reads} = $bd_stat->{bd_reads} if defined $bd_stat->{bd_reads};
    $stats{bd_writes} = $bd_stat->{bd_writes} if defined $bd_stat->{bd_writes};

    my @lines;
    push @lines, "phase=$phase";
    push @lines, 'device=' . cfg('ZRAM_SWAP_DEVICE');
    push @lines, 'backing_device=' . cfg('ZRAM_BACKING_DEVICE');
    push @lines, "captured_at_epoch=$now_epoch";
    push @lines, "captured_at_utc=" . strftime('%Y-%m-%dT%H:%M:%SZ', gmtime($now_epoch));
    push @lines, "uptime_sec=$uptime";
    push @lines, "sysfs_path=$sysfs";
    push @lines, "block_state_path=$block_state";
    for my $key (qw(
        zram_fill_percent block_state_available block_state_truncated block_state_scanned_lines
        block_state_line_limit
        tracked_pages hot_pages warm_pages cold_pages same_pages written_back_pages
        skipped_same_or_written_pages
        huge_pages huge_hot_pages huge_cold_pages huge_idle_pages huge_idle_hot_pages
        huge_idle_cold_pages idle_pages idle_hot_pages idle_cold_pages
        recompressed_pages incompressible_pages incompressible_hot_pages
        incompressible_cold_pages targeted_idle_pages targeted_huge_idle_pages
        targeted_incompressible_pages emitted_idle_pages emitted_huge_idle_pages
        emitted_incompressible_pages idle_writeback_chunks huge_idle_writeback_chunks
        incompressible_writeback_chunks targeted_specs_truncated targeted_specs_capped
        max_page_age_sec
        mem_available_bytes mem_total_bytes psi_some_avg10_millionths
        psi_full_avg10_millionths writeback_batch_size_effective
        writeback_batch_size_configured_max writeback_batch_size_actual
        writeback_pass_page_limit writeback_limit_enabled writeback_limit_remaining
        backing_queue_depth backing_rotational
    )) {
        push @lines, "$key=$stats{$key}";
    }
    for my $name (zram_stat_names()) {
        my $value = $stat_attrs->{raw}{$name};
        push @lines, "$name=$value" if defined $value;
    }
    push @lines, "bd_pages=$stats{bd_pages}";
    push @lines, "bd_reads=$stats{bd_reads}";
    push @lines, "bd_writes=$stats{bd_writes}";

    ensure_runtime_dir();
    write_atomic_text($metrics_file, join("\n", @lines) . "\n", mode => 0600);

    if (log_enabled('info')) {
        log_msg(
            'info',
            "zram snapshot phase=$phase block_state_available=$stats{block_state_available} " .
            "zram_fill_percent=$stats{zram_fill_percent} block_state_truncated=$stats{block_state_truncated} " .
            "tracked_pages=$stats{tracked_pages} hot_pages=$stats{hot_pages} " .
            "warm_pages=$stats{warm_pages} cold_pages=$stats{cold_pages} idle_pages=$stats{idle_pages} " .
            "targeted_idle_pages=$stats{targeted_idle_pages} huge_idle_pages=$stats{huge_idle_pages} " .
            "targeted_huge_idle_pages=$stats{targeted_huge_idle_pages} incompressible_pages=$stats{incompressible_pages} " .
            "targeted_incompressible_pages=$stats{targeted_incompressible_pages} targeted_specs_truncated=$stats{targeted_specs_truncated} " .
            "targeted_specs_capped=$stats{targeted_specs_capped}"
        );
    }

    return \%stats;
}

sub new_range_builder {
    my (%opts) = @_;
    defined $opts{max_spec_bytes} && $opts{max_spec_bytes} > 0
        or fatal('page-index builder max_spec_bytes must be positive');
    defined $opts{max_chunks} && $opts{max_chunks} > 0
        or fatal('page-index builder max_chunks must be positive');
    return {
        start => undef,
        end => undef,
        chunks => [],
        current_tokens => [],
        current_len => 0,
        current_pages => 0,
        selected_pages => 0,
        max_pages => $opts{max_pages} || 0,
        chunk_page_limit => $opts{chunk_page_limit} || 0,
        max_spec_bytes => $opts{max_spec_bytes},
        max_chunks => $opts{max_chunks},
        pages => 0,
        emitted_pages => 0,
        truncated => 0,
        capped => 0,
    };
}

sub add_page_index_range {
    my ($builder, $page_index) = @_;
    return if $builder->{truncated};
    $builder->{pages}++;
    if ($builder->{max_pages} > 0 && $builder->{selected_pages} >= $builder->{max_pages}) {
        $builder->{capped} = 1;
        return;
    }
    $builder->{selected_pages}++;
    if (!defined $builder->{start}) {
        $builder->{start} = $page_index;
        $builder->{end} = $page_index;
        return;
    }
    if ($page_index == $builder->{end} + 1) {
        $builder->{end} = $page_index;
        return;
    }
    _flush_page_index_range($builder);
    if (!$builder->{truncated}) {
        $builder->{start} = $page_index;
        $builder->{end} = $page_index;
    }
}

sub _flush_page_index_range {
    my ($builder) = @_;
    return if !defined $builder->{start};
    my $start = $builder->{start};
    my $end = $builder->{end};
    my $page_limit = $builder->{chunk_page_limit};
    while ($start <= $end) {
        my $slice_end = $end;
        if ($page_limit > 0 && ($slice_end - $start + 1) > $page_limit) {
            $slice_end = $start + $page_limit - 1;
        }
        my $range_pages = $slice_end - $start + 1;
        my $token = $start == $slice_end
            ? 'page_index=' . $start
            : 'page_indexes=' . $start . '-' . $slice_end;
        _add_range_token($builder, $token, $range_pages);
        last if $builder->{truncated};
        $start = $slice_end + 1;
    }
    $builder->{start} = undef;
    $builder->{end} = undef;
}

sub _add_range_token {
    my ($builder, $token, $range_pages) = @_;
    return if $builder->{truncated};
    if (!@{$builder->{current_tokens}} && @{$builder->{chunks}} >= $builder->{max_chunks}) {
        $builder->{truncated} = 1;
        return;
    }
    length($token) <= $builder->{max_spec_bytes}
        or fatal('page-index token exceeds configured writeback spec limit');
    my $page_limit = $builder->{chunk_page_limit};
    if ($page_limit > 0 && @{$builder->{current_tokens}} && ($builder->{current_pages} + $range_pages) > $page_limit) {
        _finalize_current_chunk($builder);
        return if $builder->{truncated};
        if (@{$builder->{chunks}} >= $builder->{max_chunks}) {
            $builder->{truncated} = 1;
            return;
        }
    }
    my $new_len = $builder->{current_len} + length($token) + (@{$builder->{current_tokens}} ? 1 : 0);
    if ($new_len > $builder->{max_spec_bytes}) {
        _finalize_current_chunk($builder);
        return if $builder->{truncated};
        if (@{$builder->{chunks}} >= $builder->{max_chunks}) {
            $builder->{truncated} = 1;
            return;
        }
        $new_len = length($token);
    }
    push @{$builder->{current_tokens}}, $token;
    $builder->{current_len} = $new_len;
    $builder->{current_pages} += $range_pages;
    $builder->{emitted_pages} += $range_pages;
}

sub _finalize_current_chunk {
    my ($builder) = @_;
    return if !@{$builder->{current_tokens}};
    if (@{$builder->{chunks}} >= $builder->{max_chunks}) {
        $builder->{truncated} = 1;
        $builder->{current_tokens} = [];
        $builder->{current_len} = 0;
        $builder->{current_pages} = 0;
        return;
    }
    push @{$builder->{chunks}}, join(' ', @{$builder->{current_tokens}});
    $builder->{current_tokens} = [];
    $builder->{current_len} = 0;
    $builder->{current_pages} = 0;
}

sub finish_page_index_ranges {
    my ($builder) = @_;
    _flush_page_index_range($builder);
    _finalize_current_chunk($builder);
    return @{$builder->{chunks}};
}

sub block_state_authoritative {
    my ($stats) = @_;
    return ($stats->{block_state_available} && !$stats->{block_state_truncated}) ? 1 : 0;
}

sub candidate_count {
    my ($stats, @keys) = @_;
    my $count = 0;
    for my $key (@keys) {
        my $value = $stats->{$key} || 0;
        $count = $value if $value > $count;
    }
    return $count;
}

sub has_candidate {
    my ($stats, @keys) = @_;
    return 1 if !block_state_authoritative($stats);
    return candidate_count($stats, @keys) > 0 ? 1 : 0;
}

sub has_candidate_at_least {
    my ($stats, $minimum, @keys) = @_;
    return 1 if !block_state_authoritative($stats);
    return candidate_count($stats, @keys) >= $minimum ? 1 : 0;
}

sub has_huge_idle_candidate {
    my ($stats) = @_;
    return 1 if !block_state_authoritative($stats);
    return ($stats->{huge_idle_pages} || 0) > 0 ? 1 : 0;
}

1;
