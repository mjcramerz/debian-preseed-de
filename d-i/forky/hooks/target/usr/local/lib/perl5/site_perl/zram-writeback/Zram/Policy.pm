package Zram::Policy;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Budget qw(refresh_daily_writeback_budget writeback_budget_allows writeback_budget_pages_available);
use Zram::Config qw(cfg cfg_default);
use Zram::Error qw(fatal);
use Zram::Logger qw(log_msg);
use Zram::Metrics qw(
  block_state_authoritative capture_zram_state has_candidate_at_least
);
use Zram::Pressure qw(determine_pressure_state);
use Zram::Sysfs qw(
  compact_device recompress_spec write_attr_optional writeback_spec zram_fill_pct
);
use Zram::Tuning qw(
  apply_writeback_batch_size writeback_pass_pages_for_state
);
use Zram::Types qw(count_page_index_spec_pages);

our @EXPORT_OK = qw(
  mark_idle_for_state policy_plan run_maintenance writeback_budget_allows
);

my %STATE_IDLE_KEY = (
    normal    => 'ZRAM_IDLE_AGE_SEC',
    pressure  => 'ZRAM_PRESSURE_IDLE_AGE_SEC',
    emergency => 'ZRAM_EMERGENCY_IDLE_AGE_SEC',
);

my %TIER_RECOMPRESS_CAP_KEY = (
    idle      => 'ZRAM_COLD_TIER_RECOMPRESS_IDLE_MAX_PAGES',
    huge_idle => 'ZRAM_COLD_TIER_RECOMPRESS_HUGE_IDLE_MAX_PAGES',
    huge      => 'ZRAM_COLD_TIER_RECOMPRESS_HUGE_MAX_PAGES',
);

my %TIER_MIN_KEY = (
    idle      => 'ZRAM_COLD_TIER_MIN_IDLE_PAGES',
    huge_idle => 'ZRAM_COLD_TIER_MIN_HUGE_IDLE_PAGES',
);

my %TIER_CANDIDATE_KEYS = (
    idle      => [qw(idle_pages cold_pages targeted_idle_pages)],
    huge_idle => [qw(huge_idle_pages huge_idle_cold_pages targeted_huge_idle_pages)],
);

sub _enabled {
    my ($key) = @_;
    return cfg($key) ? 1 : 0;
}

sub _page_index_spec_pages {
    my ($label, $spec) = @_;
    return count_page_index_spec_pages(
        $label,
        $spec,
        cfg('ZRAM_WRITEBACK_SPEC_MAX_BYTES'),
    );
}

sub _state_idle_age {
    my ($state) = @_;
    my $key = $STATE_IDLE_KEY{$state} || 'ZRAM_IDLE_AGE_SEC';
    return cfg($key);
}

sub mark_idle_for_state {
    my ($state) = @_;
    my $sysfs = cfg('ZRAM_SYSFS');
    my $path = "$sysfs/idle";
    return 0 if !-e $path || !-w $path;
    my $age = _state_idle_age($state);
    return write_attr_optional($path, 'all', "zram idle mark for $state") if $age == 0;
    return write_attr_optional($path, $age, "zram idle age for $state");
}

sub _tier {
    my ($number) = @_;
    my $prefix = "ZRAM_TIER$number";
    return {
        number => $number,
        enabled => cfg("${prefix}_ENABLE") ? 1 : 0,
        type => cfg("${prefix}_TYPE"),
        algorithm => cfg("${prefix}_ALGORITHM"),
        priority => cfg("${prefix}_PRIORITY"),
        level => cfg("${prefix}_LEVEL"),
        threshold_bytes => cfg("${prefix}_THRESHOLD_BYTES"),
        max_pages => {
            normal => cfg("${prefix}_MAX_PAGES_NORMAL"),
            pressure => cfg("${prefix}_MAX_PAGES_PRESSURE"),
            emergency => cfg("${prefix}_MAX_PAGES_EMERGENCY"),
        },
    };
}

sub _tiers {
    return map { _tier($_) } 1 .. 3;
}

sub _cold_minimum_met {
    my ($stats) = @_;
    return has_candidate_at_least(
        $stats,
        cfg('ZRAM_COLD_TIER_MIN_COLD_PAGES'),
        qw(cold_pages idle_cold_pages huge_idle_cold_pages incompressible_cold_pages),
    );
}

sub _class_minimum_met {
    my ($stats, $minimum_key, @candidate_keys) = @_;
    return has_candidate_at_least($stats, cfg($minimum_key), @candidate_keys);
}

sub _tier_has_candidate {
    my ($tier, $stats, $cold_minimum_met) = @_;
    return 0 if !$tier->{enabled};
    return 0 if !$cold_minimum_met;
    if (exists $TIER_MIN_KEY{$tier->{type}}) {
        return _class_minimum_met(
            $stats,
            $TIER_MIN_KEY{$tier->{type}},
            @{$TIER_CANDIDATE_KEYS{$tier->{type}}},
        );
    }
    if ($tier->{type} eq 'huge') {
        return 1 if !block_state_authoritative($stats);
        my $huge_pages = $stats->{huge_pages} || 0;
        my $huge_idle_pages = $stats->{huge_idle_pages} || 0;
        return ($huge_pages - $huge_idle_pages) >= cfg('ZRAM_COLD_TIER_MIN_HUGE_PAGES') ? 1 : 0;
    }
    return 0;
}

sub _tier_max_pages {
    my ($tier, $state) = @_;
    my $state_max = $tier->{max_pages}{$state} // 0;
    return 0 if $state_max <= 0;
    my $cap_key = $TIER_RECOMPRESS_CAP_KEY{$tier->{type}};
    return $state_max if !defined $cap_key;
    my $class_cap = cfg($cap_key);
    return $class_cap < $state_max ? $class_cap : $state_max;
}

sub _recompress_possible {
    my ($state) = @_;
    return 0 if !_enabled('ZRAM_COLD_TIER_RECOMPRESS_ENABLE');
    for my $tier (_tiers()) {
        next if !$tier->{enabled};
        return 1 if _tier_max_pages($tier, $state) > 0;
    }
    return 0;
}

sub _writeback_possible {
    my ($state, $budget_allows) = @_;
    return 0 if $state eq 'normal';
    return 0 if !$budget_allows;
    return 0 if !_enabled('ZRAM_WRITEBACK_ENABLED');
    return 0 if !_enabled('ZRAM_COLD_TIER_WRITEBACK_ENABLE');
    return 1;
}

sub _maintenance_possible {
    my ($state, $budget_allows) = @_;
    return 0 if !_enabled('ZRAM_COLD_TIER_ENABLE');
    return 1 if _recompress_possible($state);
    return 1 if _writeback_possible($state, $budget_allows);
    return 0;
}

sub _recompress_spec {
    my ($tier, $state) = @_;
    my $max_pages = _tier_max_pages($tier, $state);
    return '' if $max_pages <= 0;
    return join ' ',
        'type=' . $tier->{type},
        'priority=' . $tier->{priority},
        'threshold=' . $tier->{threshold_bytes},
        'max_pages=' . $max_pages;
}

sub _incompressible_candidate {
    my ($stats, $cold_minimum_met) = @_;
    return $cold_minimum_met
        && has_candidate_at_least(
            $stats,
            cfg('ZRAM_COLD_TIER_MIN_INCOMPRESSIBLE_PAGES'),
            qw(incompressible_pages incompressible_cold_pages targeted_incompressible_pages),
        );
}

sub _writeback_class_caps {
    my ($state, $budget_pages_available) = @_;
    return {} if $state eq 'normal';
    return {} if !cfg('ZRAM_WRITEBACK_ENABLED');
    return {} if !cfg('ZRAM_COLD_TIER_WRITEBACK_ENABLE');
    return {} if defined $budget_pages_available && $budget_pages_available <= 0;

    my $pass_cap = writeback_pass_pages_for_state($state, $budget_pages_available);
    return {} if $pass_cap <= 0;

    my %caps;
    if ($state eq 'pressure' || $state eq 'emergency') {
        my $class_cap = cfg('ZRAM_COLD_TIER_WRITEBACK_INCOMPRESSIBLE_MAX_PAGES');
        $caps{incompressible} = $class_cap < $pass_cap ? $class_cap : $pass_cap;
    }
    if ($state eq 'emergency') {
        $caps{huge_idle} = $pass_cap;
    }
    return \%caps;
}

sub _huge_idle_writeback_candidate {
    my ($stats, $cold_minimum_met) = @_;
    return $cold_minimum_met
        && has_candidate_at_least(
            $stats,
            cfg('ZRAM_COLD_TIER_MIN_HUGE_IDLE_PAGES'),
            qw(huge_idle_pages huge_idle_cold_pages targeted_huge_idle_pages),
        );
}

sub _truncate_page_index_spec {
    my ($label, $spec, $max_pages) = @_;
    return '' if !defined $max_pages || $max_pages <= 0;
    return $spec if _page_index_spec_pages($label, $spec) <= $max_pages;

    my @kept;
    my $remaining = $max_pages;
    for my $token (split /\s+/, $spec) {
        last if $remaining <= 0;
        if ($token =~ /\Apage_index=([0-9]+)\z/) {
            push @kept, $token;
            $remaining--;
            next;
        }
        if ($token =~ /\Apage_indexes=([0-9]+)-([0-9]+)\z/) {
            my ($low, $high) = (0 + $1, 0 + $2);
            my $count = $high - $low + 1;
            if ($count <= $remaining) {
                push @kept, $token;
                $remaining -= $count;
                next;
            }
            my $slice_high = $low + $remaining - 1;
            push @kept,
                $slice_high == $low
                ? "page_index=$low"
                : "page_indexes=$low-$slice_high";
            $remaining = 0;
            next;
        }
        fatal("unsupported page index token while truncating $label: $token");
    }

    @kept or fatal("unable to retain any pages while truncating $label");
    return join ' ', @kept;
}

sub _add_writeback {
    my ($plan, $stats, $kind, $remaining_ref) = @_;
    my $spec_key = $kind . '_writeback_specs';
    my $targeted = $stats->{$spec_key} || [];
    for my $spec (@{$targeted}) {
        next if !defined $spec || $spec eq '';
        if (defined $remaining_ref && defined ${$remaining_ref}) {
            my $pages = _page_index_spec_pages("$kind writeback spec", $spec);
            if ($pages > ${$remaining_ref}) {
                if (${$remaining_ref} <= 0) {
                    log_msg('debug', "skipping $kind writeback spec with $pages pages; pass budget remaining=${$remaining_ref}");
                    next;
                }
                my $truncated = _truncate_page_index_spec(
                    "$kind writeback spec",
                    $spec,
                    ${$remaining_ref},
                );
                my $truncated_pages = _page_index_spec_pages(
                    "$kind writeback spec",
                    $truncated,
                );
                log_msg(
                    'debug',
                    "truncating $kind writeback spec from $pages pages to $truncated_pages pages; pass budget remaining=${$remaining_ref}",
                );
                ${$remaining_ref} -= $truncated_pages;
                push @{$plan->{writeback}}, $truncated;
                next;
            }
            ${$remaining_ref} -= $pages;
        }
        push @{$plan->{writeback}}, $spec;
    }
    return if @{$targeted};
    if (!block_state_authoritative($stats)) {
        log_msg('debug', "skipping generic $kind writeback; targeted page indexes require authoritative block_state");
        return;
    }
}

sub _fill_gate_met {
    my ($fill_pct) = @_;
    return $fill_pct >= cfg('ZRAM_COLD_TIER_MIN_ZRAM_FILL_PCT') ? 1 : 0;
}

sub policy_plan {
    my ($state, $stats, %opts) = @_;
    my $budget_pages_available = exists $opts{writeback_pages_available}
        ? $opts{writeback_pages_available}
        : (exists $opts{budget_allows} ? undef : writeback_budget_pages_available());
    my $budget_allows = exists $opts{budget_allows}
        ? $opts{budget_allows}
        : (!defined $budget_pages_available || $budget_pages_available > 0 ? 1 : 0);
    my $remaining_pages = writeback_pass_pages_for_state($state, $budget_pages_available);
    my $cold_tier_enabled = _enabled('ZRAM_COLD_TIER_ENABLE');
    my $cold_minimum_met;
    my %plan = (
        state => $state,
        recompress => [],
        writeback => [],
        compact => 0,
        budget_allows => $budget_allows ? 1 : 0,
        writeback_pass_pages => $remaining_pages,
    );

    if ($cold_tier_enabled && _enabled('ZRAM_COLD_TIER_RECOMPRESS_ENABLE')) {
        $cold_minimum_met = _cold_minimum_met($stats);
        for my $tier (_tiers()) {
            next if !_tier_has_candidate($tier, $stats, $cold_minimum_met);
            my $spec = _recompress_spec($tier, $state);
            push @{$plan{recompress}}, $spec if $spec ne '';
        }
    }

    if ($cold_tier_enabled && _writeback_possible($state, $budget_allows)) {
        $cold_minimum_met = _cold_minimum_met($stats) if !defined $cold_minimum_met;
        my $manual_page_indexes = cfg_default('ZRAM_MAINTENANCE_PAGE_INDEXES', '');
        if ($state ne 'normal' && $manual_page_indexes ne '') {
            my $manual_pages = _page_index_spec_pages('maintenance_page_indexes', $manual_page_indexes);
            if ($manual_pages <= $remaining_pages) {
                push @{$plan{writeback}}, $manual_page_indexes;
                $remaining_pages -= $manual_pages;
            } elsif ($remaining_pages > 0) {
                my $truncated = _truncate_page_index_spec(
                    'maintenance_page_indexes',
                    $manual_page_indexes,
                    $remaining_pages,
                );
                my $truncated_pages = _page_index_spec_pages(
                    'maintenance_page_indexes',
                    $truncated,
                );
                log_msg(
                    'debug',
                    "truncating manual page indexes from $manual_pages pages to $truncated_pages pages; pass budget remaining=$remaining_pages",
                );
                push @{$plan{writeback}}, $truncated;
                $remaining_pages -= $truncated_pages;
            } else {
                log_msg('debug', "skipping manual page indexes with $manual_pages pages; pass budget remaining=$remaining_pages");
            }
        }
        if (($state eq 'pressure' || $state eq 'emergency') && _incompressible_candidate($stats, $cold_minimum_met)) {
            _add_writeback(
                \%plan,
                $stats,
                'incompressible',
                \$remaining_pages,
            );
        }
        if ($state eq 'emergency' && _huge_idle_writeback_candidate($stats, $cold_minimum_met)) {
            _add_writeback(\%plan, $stats, 'huge_idle', \$remaining_pages);
        }
    }

    $plan{compact} = (@{$plan{recompress}} || @{$plan{writeback}}) && _enabled('ZRAM_COLD_TIER_COMPACT_ENABLE') ? 1 : 0;
    return \%plan;
}

sub _apply_plan {
    my ($plan) = @_;
    my $operations = 0;
    for my $spec (@{$plan->{recompress}}) {
        $operations += recompress_spec($spec);
    }
    for my $spec (@{$plan->{writeback}}) {
        $operations += writeback_spec($spec);
    }
    compact_device() if $operations > 0 && $plan->{compact};
    return $operations;
}

sub run_maintenance {
    my (%opts) = @_;
    if (!cfg('ZRAM_COLD_TIER_ENABLE')) {
        log_msg('debug', 'skipping zram maintenance; policy disabled');
        capture_zram_state('maintenance-disabled', scan_block_state => 0);
        return { state => 'disabled', operations => 0 };
    }

    my ($state, $reasons) = $opts{state}
        ? ($opts{state}, ['operator override'])
        : determine_pressure_state();
    $state =~ /\A(?:normal|pressure|emergency)\z/
        or fatal("invalid zram maintenance state: $state");
    my $idle_age = _state_idle_age($state);
    refresh_daily_writeback_budget();
    my $budget_pages_available = writeback_budget_pages_available();
    my $budget_allows = !defined $budget_pages_available || $budget_pages_available > 0 ? 1 : 0;
    my $tuning = apply_writeback_batch_size($state);
    if ($state eq 'normal' && !cfg('ZRAM_IDLE_WRITEBACK_ENABLE')) {
        log_msg('debug', 'skipping normal zram maintenance; normal idle policy disabled');
        capture_zram_state(
            'maintenance-normal-disabled',
            state => $state,
            idle_age_sec => $idle_age,
            scan_block_state => 0,
        );
        return { state => $state, operations => 0 };
    }
    if (!_maintenance_possible($state, $budget_allows)) {
        log_msg(
            'debug',
            'skipping zram maintenance state=' . $state .
            ' reason=no enabled recompression/writeback work'
        );
        capture_zram_state(
            "maintenance-$state-no-work",
            state => $state,
            idle_age_sec => $idle_age,
            scan_block_state => 0,
        );
        return { state => $state, operations => 0 };
    }

    my $fill_pct = zram_fill_pct();
    if (!_fill_gate_met($fill_pct)) {
        log_msg(
            'info',
            'skipping zram maintenance state=' . $state .
            ' reason=' . join('; ', @{$reasons || []}) .
            " zram_fill_percent=$fill_pct<" . cfg('ZRAM_COLD_TIER_MIN_ZRAM_FILL_PCT')
        );
        capture_zram_state(
            "maintenance-$state-below-fill",
            state => $state,
            idle_age_sec => $idle_age,
            scan_block_state => 0,
        );
        return {
            state => $state,
            operations => 0,
            skipped => 'below-fill',
            zram_fill_percent => $fill_pct,
        };
    }
    my $mark_succeeded = mark_idle_for_state($state);
    my $stats = capture_zram_state(
        "maintenance-$state-candidates",
        state => $state,
        idle_age_sec => $idle_age,
        writeback_class_caps => _writeback_class_caps($state, $budget_pages_available),
    );
    my $plan = policy_plan(
        $state,
        $stats,
        budget_allows => $budget_allows,
        writeback_pages_available => $budget_pages_available,
    );

    log_msg(
        'info',
        'zram maintenance state=' . $state .
        ' reason=' . join('; ', @{$reasons || []}) .
        ' idle_mark=' . ($mark_succeeded ? 1 : 0) .
        ' recompress=' . scalar(@{$plan->{recompress}}) .
        ' writeback=' . scalar(@{$plan->{writeback}}) .
        ' budget_allows=' . $plan->{budget_allows} .
        ' writeback_batch_size=' . $tuning->{effective_batch_size} .
        ' writeback_pass_pages=' . $plan->{writeback_pass_pages} .
        (defined $budget_pages_available ? " writeback_budget_pages=$budget_pages_available" : '')
    );
    if (!$plan->{budget_allows} && ($state eq 'pressure' || $state eq 'emergency')) {
        log_msg('info', 'zram writeback budget exhausted; writeback is suppressed for this pass');
    }

    my $operations = _apply_plan($plan);
    if ($operations > 0) {
        capture_zram_state(
            "maintenance-$state-after",
            state => $state,
            idle_age_sec => $idle_age,
        );
    }
    $plan->{writeback_batch_size} = $tuning->{effective_batch_size};
    $plan->{operations} = $operations;
    return $plan;
}

1;
