package Zram::Tuning;

use strict;
use warnings;

use Exporter qw(import);
use File::Basename qw(basename);
use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Path qw(canonical_path);
use Zram::Sysfs qw(read_uint_attr write_attr_optional);

our @EXPORT_OK = qw(
  apply_writeback_batch_size backing_queue_depth backing_rotational
  writeback_batch_size_for_state writeback_pass_pages_for_state
  writeback_tuning_snapshot
);

my %STATE_BATCH_KEY = (
    normal    => 'ZRAM_WRITEBACK_BATCH_SIZE_NORMAL',
    pressure  => 'ZRAM_WRITEBACK_BATCH_SIZE_PRESSURE',
    emergency => 'ZRAM_WRITEBACK_BATCH_SIZE_EMERGENCY',
);

my %STATE_PASS_KEY = (
    pressure  => 'ZRAM_WRITEBACK_MAX_PAGES_PRESSURE',
    emergency => 'ZRAM_WRITEBACK_MAX_PAGES_EMERGENCY',
);

sub _validate_state {
    my ($state) = @_;
    defined $state && exists $STATE_BATCH_KEY{$state}
        or fatal("invalid zram tuning state: " . (defined $state ? $state : 'unset'));
    return $state;
}

sub _positive_min {
    my (@values) = @_;
    my $minimum;
    for my $value (@values) {
        next if !defined $value || $value <= 0;
        $minimum = $value if !defined $minimum || $value < $minimum;
    }
    return $minimum;
}

sub _device_sysfs_name {
    my ($device) = @_;
    return undef if !defined $device || $device eq '';
    my $canonical = canonical_path($device);
    return undef if !defined $canonical || $canonical eq '';
    my $name = basename($canonical);
    return $name =~ /\A[A-Za-z0-9_.:+-]+\z/ ? $name : undef;
}

sub _backing_queue_values {
    my ($attr) = @_;
    my $sysfs_root = cfg('ZRAM_SYSFS_ROOT');
    $sysfs_root =~ s{/+\z}{};
    my %seen;
    my @values;
    for my $device (cfg('ZRAM_BACKING_RAW_DEVICE'), cfg('ZRAM_BACKING_DEVICE')) {
        my $name = _device_sysfs_name($device);
        next if !defined $name;
        next if $seen{$name}++;
        my $value = read_uint_attr("$sysfs_root/class/block/$name/queue/$attr");
        push @values, $value if defined $value;
    }
    return @values;
}

sub backing_queue_depth {
    return _positive_min(_backing_queue_values('nr_requests'));
}

sub backing_rotational {
    my @values = _backing_queue_values('rotational');
    return 1 if grep { $_ == 1 } @values;
    return 0 if grep { $_ == 0 } @values;
    return undef;
}

sub _writeback_batch_size_for_state {
    my ($state, $queue_depth, $rotational) = @_;
    _validate_state($state);

    my $configured_max = cfg('ZRAM_WRITEBACK_BATCH_SIZE');
    my $target = cfg('ZRAM_WRITEBACK_BATCH_SIZE_ADAPTIVE')
        ? cfg($STATE_BATCH_KEY{$state})
        : $configured_max;

    $target = _positive_min($target, $configured_max);
    $target = _positive_min($target, cfg('ZRAM_WRITEBACK_BATCH_SIZE_ROTATIONAL_MAX'))
        if defined $rotational && $rotational == 1;
    $target = _positive_min($target, $queue_depth);
    return defined $target && $target > 0 ? $target : 1;
}

sub writeback_batch_size_for_state {
    my ($state) = @_;
    return _writeback_batch_size_for_state(
        $state,
        backing_queue_depth(),
        backing_rotational(),
    );
}

sub writeback_pass_pages_for_state {
    my ($state, $budget_pages_available) = @_;
    _validate_state($state);
    return 0 if $state eq 'normal';
    return 0 if defined $budget_pages_available && $budget_pages_available <= 0;

    my $pass_limit = cfg($STATE_PASS_KEY{$state});
    return _positive_min($pass_limit, $budget_pages_available) // 0;
}

sub writeback_tuning_snapshot {
    my ($state, $budget_pages_available) = @_;
    _validate_state($state);
    my $configured_target = cfg('ZRAM_WRITEBACK_BATCH_SIZE_ADAPTIVE')
        ? cfg($STATE_BATCH_KEY{$state})
        : cfg('ZRAM_WRITEBACK_BATCH_SIZE');
    my $queue_depth = backing_queue_depth();
    my $rotational = backing_rotational();
    return {
        state => $state,
        adaptive => cfg('ZRAM_WRITEBACK_BATCH_SIZE_ADAPTIVE') ? 1 : 0,
        configured_max => cfg('ZRAM_WRITEBACK_BATCH_SIZE'),
        configured_target => $configured_target,
        queue_depth => $queue_depth,
        rotational => $rotational,
        effective_batch_size => _writeback_batch_size_for_state(
            $state,
            $queue_depth,
            $rotational,
        ),
        pass_page_limit => writeback_pass_pages_for_state($state, $budget_pages_available),
    };
}

sub apply_writeback_batch_size {
    my ($state) = @_;
    my $snapshot = writeback_tuning_snapshot($state, undef);
    $snapshot->{applied} = 0;
    return $snapshot if !cfg('ZRAM_WRITEBACK_ENABLED');

    my $path = cfg('ZRAM_SYSFS') . '/writeback_batch_size';
    $snapshot->{applied} = write_attr_optional(
        $path,
        $snapshot->{effective_batch_size},
        "zram writeback batch size for $state",
    ) ? 1 : 0;
    return $snapshot;
}

1;
