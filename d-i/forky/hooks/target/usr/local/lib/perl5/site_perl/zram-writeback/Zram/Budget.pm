package Zram::Budget;

use strict;
use warnings;

use Exporter qw(import);
use POSIX qw(strftime);
use Zram::AtomicFile qw(write_atomic_text);
use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Lock qw(ensure_runtime_dir);
use Zram::Logger qw(log_msg);
use Zram::Sizing qw(bytes_to_writeback_pages);
use Zram::Sysfs qw(read_uint_attr write_attr_optional);

our @EXPORT_OK = qw(
  budget_state_file refresh_daily_writeback_budget writeback_budget_allows
  writeback_budget_pages_available writeback_budget_remaining
);

use constant MAX_STATE_BYTES => 4096;
use constant MAX_STATE_LINE_BYTES => 512;

sub budget_state_file {
    return cfg('ZRAM_RUNTIME_DIR') . '/writeback-budget.state';
}

sub _today_utc {
    return strftime('%Y-%m-%d', gmtime(time));
}

sub _read_state {
    my $path = budget_state_file();
    my %state;
    if (open my $fh, '<', $path) {
        my $bytes = 0;
        while (my $line = <$fh>) {
            $bytes += length($line);
            $bytes <= MAX_STATE_BYTES or fatal("zram writeback budget state $path is too large");
            length($line) <= MAX_STATE_LINE_BYTES or fatal("zram writeback budget state $path has an oversized line");
            chomp $line;
            my ($key, $value) = $line =~ /\A([A-Za-z0-9_]+)=(.*)\z/;
            next if !defined $key;
            $value =~ s/[\r\n]//g;
            $state{$key} = $value;
        }
        close $fh;
    }
    return \%state;
}

sub _write_state {
    my ($state) = @_;
    ensure_runtime_dir();
    my $path = budget_state_file();
    my @lines;
    for my $key (sort keys %{$state}) {
        my $value = defined $state->{$key} ? $state->{$key} : '';
        $value =~ s/[\r\n]//g;
        push @lines, "$key=$value";
    }
    write_atomic_text($path, join("\n", @lines) . "\n", mode => 0600);
}

sub refresh_daily_writeback_budget {
    return 0 if !cfg('ZRAM_WRITEBACK_ENABLED');
    return 0 if !cfg('ZRAM_WRITEBACK_LIMIT_ENABLE');
    my $daily_bytes = cfg('ZRAM_DAILY_WRITEBACK_LIMIT_BYTES');
    return 0 if $daily_bytes <= 0;

    my $today = _today_utc();
    my $state = _read_state();
    return 0 if ($state->{daily_budget_date} || '') eq $today;

    my $pages = bytes_to_writeback_pages('writeback.daily_writeback_limit', $daily_bytes);
    if ($pages <= 0) {
        log_msg('warning', 'configured zram daily writeback limit is below one 4 KiB page; budget reset skipped');
        return 0;
    }

    my $sysfs = cfg('ZRAM_SYSFS');
    my $limit_written = write_attr_optional("$sysfs/writeback_limit", $pages, 'zram daily writeback_limit');
    my $enable_written = write_attr_optional("$sysfs/writeback_limit_enable", 1, 'zram writeback_limit_enable');
    return 0 if !$limit_written || !$enable_written;

    $state->{daily_budget_date} = $today;
    $state->{daily_budget_pages} = $pages;
    _write_state($state);
    log_msg('info', "zram daily writeback budget reset to $pages pages");
    return 1;
}

sub writeback_budget_remaining {
    return undef if !cfg('ZRAM_WRITEBACK_LIMIT_ENABLE');
    return read_uint_attr(cfg('ZRAM_SYSFS') . '/writeback_limit');
}

sub writeback_budget_pages_available {
    return 0 if !cfg('ZRAM_WRITEBACK_ENABLED');
    return undef if !cfg('ZRAM_WRITEBACK_LIMIT_ENABLE');
    my $remaining = writeback_budget_remaining();
    return 0 if !defined $remaining;
    my $reserve = cfg('ZRAM_WRITEBACK_MIN_REMAINING_PAGES');
    return 0 if $remaining <= $reserve;
    return $remaining - $reserve;
}

sub writeback_budget_allows {
    my $available = writeback_budget_pages_available();
    return !defined $available || $available > 0 ? 1 : 0;
}

1;
