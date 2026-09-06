package Zram::Device;

use strict;
use warnings;

use Exporter qw(import);
use Zram::BackingDevice qw(backing_device_status);
use Zram::Config qw(cfg);
use Zram::Debugfs qw(block_state_available block_state_path);
use Zram::Swap qw(swap_status);
use Zram::Stats qw(read_zram_stat_attrs);
use Zram::Sysfs qw(normalize_attr read_uint_attr);
use Zram::Tuning qw(writeback_tuning_snapshot);

our @EXPORT_OK = qw(device_status render_status_plain render_status_json print_status);

sub _features {
    my ($sysfs) = @_;
    return {
        writeback => -e "$sysfs/writeback" ? 1 : 0,
        recompress => -e "$sysfs/recompress" ? 1 : 0,
        recomp_algorithm => -e "$sysfs/recomp_algorithm" ? 1 : 0,
        algorithm_params => -e "$sysfs/algorithm_params" ? 1 : 0,
        compressed_writeback => -e "$sysfs/compressed_writeback" ? 1 : 0,
        writeback_limit => -e "$sysfs/writeback_limit" ? 1 : 0,
        writeback_limit_enable => -e "$sysfs/writeback_limit_enable" ? 1 : 0,
        writeback_batch_size => -e "$sysfs/writeback_batch_size" ? 1 : 0,
        block_state => block_state_available(),
    };
}

sub _config_flags {
    return {
        writeback_enabled => cfg('ZRAM_WRITEBACK_ENABLED'),
        idle_writeback_enabled => cfg('ZRAM_IDLE_WRITEBACK_ENABLE'),
        pressure_enabled => cfg('ZRAM_PRESSURE_ENABLED'),
        cold_tier_enabled => cfg('ZRAM_COLD_TIER_ENABLE'),
        cold_tier_recompress_enabled => cfg('ZRAM_COLD_TIER_RECOMPRESS_ENABLE'),
        cold_tier_writeback_enabled => cfg('ZRAM_COLD_TIER_WRITEBACK_ENABLE'),
        cold_tier_compact_enabled => cfg('ZRAM_COLD_TIER_COMPACT_ENABLE'),
    };
}

sub device_status {
    my $sysfs = cfg('ZRAM_SYSFS');
    my $stat_attrs = read_zram_stat_attrs($sysfs);

    my $swap = swap_status(cfg('ZRAM_SWAP_DEVICE'));

    return {
        config => _config_flags(),
        device => {
            path => cfg('ZRAM_SWAP_DEVICE'),
            name => cfg('ZRAM_SWAP_DEVICE_NAME'),
            sysfs => $sysfs,
            exists => -b cfg('ZRAM_SWAP_DEVICE') ? 1 : 0,
            initstate => normalize_attr("$sysfs/initstate"),
            disksize => read_uint_attr("$sysfs/disksize"),
            mem_limit => read_uint_attr("$sysfs/mem_limit"),
            active_swap => $swap->{active},
        },
        swap => $swap,
        backing => backing_device_status(),
        features => _features($sysfs),
        debugfs => {
            block_state_path => block_state_path(),
            block_state_available => block_state_available(),
        },
        algorithms => {
            comp_algorithm => normalize_attr("$sysfs/comp_algorithm"),
            recomp_algorithm => normalize_attr("$sysfs/recomp_algorithm"),
        },
        writeback => {
            limit => read_uint_attr("$sysfs/writeback_limit"),
            limit_enable => read_uint_attr("$sysfs/writeback_limit_enable"),
            batch_size => read_uint_attr("$sysfs/writeback_batch_size"),
            tuning => writeback_tuning_snapshot('normal', undef),
        },
        raw => $stat_attrs->{raw},
        parsed => $stat_attrs->{parsed},
    };
}

sub _flatten {
    my ($prefix, $value, $out) = @_;
    if (ref($value) eq 'HASH') {
        for my $key (sort keys %{$value}) {
            my $next = $prefix eq '' ? $key : "$prefix.$key";
            _flatten($next, $value->{$key}, $out);
        }
        return;
    }
    return if !defined $value;
    push @{$out}, "$prefix=$value";
}

sub render_status_plain {
    my ($status) = @_;
    $status ||= device_status();
    my @lines;
    _flatten('', $status, \@lines);
    return join("\n", @lines) . "\n";
}

sub _json_escape {
    my ($value) = @_;
    $value =~ s/\\/\\\\/g;
    $value =~ s/"/\\"/g;
    $value =~ s/\n/\\n/g;
    $value =~ s/\r/\\r/g;
    $value =~ s/\t/\\t/g;
    return $value;
}

sub _json_value {
    my ($value) = @_;
    return 'null' if !defined $value;
    if (ref($value) eq 'HASH') {
        my @pairs;
        for my $key (sort keys %{$value}) {
            push @pairs, '"' . _json_escape($key) . '":' . _json_value($value->{$key});
        }
        return '{' . join(',', @pairs) . '}';
    }
    return "$value" if !ref($value) && $value =~ /\A(?:0|[1-9][0-9]*)\z/;
    return '"' . _json_escape("$value") . '"';
}

sub render_status_json {
    my ($status) = @_;
    $status ||= device_status();
    return _json_value($status) . "\n";
}

sub print_status {
    my (%opts) = @_;
    my $status = device_status();
    print $opts{json} ? render_status_json($status) : render_status_plain($status);
    return 0;
}

1;
