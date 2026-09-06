package Zram::Setup::Device;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Errno qw(EINTR);
use File::Basename qw(basename);
use POSIX qw(_exit);
use Time::HiRes qw(sleep);
use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Path qw(same_path);
use Zram::Setup::BackingDevice;
use Zram::Setup::Sysfs;
use Zram::Procfs qw(mem_total_bytes);
use Zram::Sizing qw(bytes_to_writeback_pages);
use Zram::Swap qw(swap_active);
use Zram::Sysfs qw(normalize_attr);
use Zram::Tuning qw(writeback_batch_size_for_state);

has sysfs => (is => 'ro', default => sub { Zram::Setup::Sysfs->new() });
has backing => (is => 'ro', default => sub { Zram::Setup::BackingDevice->new() });

sub _run {
    my ($self, @command) = @_;
    system @command;
    return $? == 0;
}

sub _run_quiet {
    my ($self, @command) = @_;

    my $pid = fork;
    defined $pid
        or fatal('failed to fork a bounded zram command');

    if ($pid == 0) {
        open STDOUT, '>', '/dev/null' or _exit(127);
        open STDERR, '>', '/dev/null' or _exit(127);
        exec { $command[0] } @command or _exit(127);
    }

    my $waited;
    do {
        $waited = waitpid $pid, 0;
    } while ($waited == -1 && $! == EINTR);
    $waited == $pid
        or fatal('failed to wait for a bounded zram command');

    return $? == 0;
}

sub _wait_for_block {
    my ($self, $device, $timeout) = @_;
    for (1 .. $timeout) {
        return 1 if -b $device;
        sleep 1;
    }
    return -b $device ? 1 : 0;
}

sub _is_uninitialized {
    my ($self) = @_;
    my $state = $self->sysfs()->read('initstate');
    my $size = $self->sysfs()->read_uint('disksize') // 0;
    return $size == 0 && (!defined $state || $state eq '' || $state eq '0') ? 1 : 0;
}

sub _wait_uninitialized {
    my ($self, $timeout) = @_;
    for (1 .. $timeout) {
        return 1 if $self->_is_uninitialized();
        sleep 1;
    }
    return $self->_is_uninitialized();
}

sub _wait_swap_inactive {
    my ($self, $timeout) = @_;
    for (1 .. $timeout) {
        return 1 if !swap_active(cfg('ZRAM_SWAP_DEVICE'));
        sleep 1;
    }
    return !swap_active(cfg('ZRAM_SWAP_DEVICE'));
}

sub _try_sysfs_reset {
    my ($self) = @_;
    my $path = $self->sysfs()->path('reset');
    return 0 if !-e $path || !-w $path;

    open my $fh, '>', $path or return 0;
    my $ok = print {$fh} "1\n";
    $ok = close($fh) && $ok;
    return $ok ? 1 : 0;
}

sub _reset_with_retry {
    my ($self, $device) = @_;
    my $attempts = 10;

    for my $attempt (1 .. $attempts) {
        return 1 if $self->_is_uninitialized();

        my $requested = $self->_run_quiet('/usr/sbin/zramctl', '--reset', $device);
        $requested ||= $self->_try_sysfs_reset();
        return 1 if $requested && $self->_wait_uninitialized(1);

        sleep 0.5 if $attempt < $attempts;
    }
    return 0;
}

sub _clear_runtime_state {
    my ($self) = @_;
    my $runtime = cfg('ZRAM_RUNTIME_DIR');
    my $name = cfg('ZRAM_SWAP_DEVICE_NAME');
    for my $path ("$runtime/writeback-budget.state", "$runtime/$name.metrics") {
        next if !-e $path && !-l $path;
        -d $path and fatal("unexpected directory in zram runtime state path: $path");
        unlink $path or fatal("failed to clear stale zram runtime state $path: $!");
    }
}

sub reset {
    my ($self) = @_;
    my $device = cfg('ZRAM_SWAP_DEVICE');
    -d cfg('ZRAM_SYSFS') or fatal('zram sysfs path is unavailable: ' . cfg('ZRAM_SYSFS'));
    if (swap_active($device)) {
        $self->_run('/usr/sbin/swapoff', $device) or fatal("failed to swapoff $device");
        $self->_wait_swap_inactive(30) or fatal("zram swap stayed active after swapoff: $device");
    }
    if ($self->_is_uninitialized()) {
        $self->_clear_runtime_state();
        return 1;
    }
    $self->_reset_with_retry($device)
        or fatal("zram reset stayed busy after bounded retries for $device");
    $self->_clear_runtime_state();
    return 1;
}

sub _memory_mib {
    my ($self) = @_;
    my $bytes = mem_total_bytes();
    $bytes > 0 or fatal('unable to determine total RAM');
    return int(($bytes + 1_048_575) / 1_048_576);
}

sub _backing_mib {
    my ($self) = @_;
    my $device = cfg('ZRAM_BACKING_DEVICE');
    -b $device or fatal("missing block device for size probe: $device");
    open my $fh, '-|', '/usr/sbin/blockdev', '--getsize64', $device
        or fatal("unable to determine block device size for $device");
    my $bytes = <$fh>;
    close $fh;
    defined $bytes && $bytes =~ /\A([0-9]+)\s*\z/ && $1 > 0
        or fatal("unable to determine block device size for $device");
    return int(($1 + 1_048_575) / 1_048_576);
}

sub _dynamic_sizes {
    my ($self) = @_;
    my $ram = $self->_memory_mib();
    my $size = int(($ram * cfg('ZRAM_SIZE_PERCENT') + 99) / 100);
    $size = cfg('ZRAM_SIZE_MIN_MIB') if $size < cfg('ZRAM_SIZE_MIN_MIB');
    $size = cfg('ZRAM_SIZE_MAX_MIB') if $size > cfg('ZRAM_SIZE_MAX_MIB');
    my $mem_limit = int(($size * cfg('ZRAM_MEM_LIMIT_PERCENT') + 99) / 100);
    $mem_limit = $size if $mem_limit > $size;

    my $writeback_pages = 0;
    if (cfg('ZRAM_WRITEBACK_ENABLED') && cfg('ZRAM_WRITEBACK_LIMIT_ENABLE')) {
        my $backing = $self->_backing_mib();
        my $reserve = 128;
        $backing > $reserve or fatal("zram backing device is too small after reserve: ${backing} MiB");
        my $usable = $backing - $reserve;
        my $limit = int(($size * cfg('ZRAM_WRITEBACK_LIMIT_PCT') + 99) / 100);
        my $cap = int($usable / 2);
        $cap = $usable if $cap < 1024;
        $limit = $cap if $limit > $cap;
        $writeback_pages = bytes_to_writeback_pages('zram writeback limit', $limit * 1_048_576);
    }
    return ($size, $mem_limit, $writeback_pages);
}

sub _configure_algorithms {
    my ($self) = @_;
    my $available = $self->sysfs()->read('comp_algorithm') // '';
    my $primary = cfg('ZRAM_COMPRESSION_ALGORITHM');
    $available =~ /(?:\A|\s|\[)\Q$primary\E(?:\]|\s|\z)/
        or fatal("primary zram algorithm $primary is unavailable");
    $self->sysfs()->required('comp_algorithm', $primary, 'zram comp_algorithm');
    for my $tier (1 .. 3) {
        next if !cfg("ZRAM_TIER${tier}_ENABLE");
        my $algorithm = cfg("ZRAM_TIER${tier}_ALGORITHM");
        my $priority = cfg("ZRAM_TIER${tier}_PRIORITY");
        $self->sysfs()->required(
            'recomp_algorithm',
            "algo=$algorithm priority=$priority",
            "zram recompression tier $tier algorithm",
        );
        my $level = cfg("ZRAM_TIER${tier}_LEVEL");
        next if !$level;
        $self->sysfs()->required(
            'algorithm_params',
            "algo=$algorithm priority=$priority level=$level",
            "zram recompression tier $tier parameters",
        );
    }
    my $params = cfg('ZRAM_ALGORITHM_PARAMS');
    $self->sysfs()->required('algorithm_params', $params, 'zram algorithm_params')
        if defined $params && $params ne '';
}

sub _configure_writeback {
    my ($self, $writeback_pages) = @_;
    return if !cfg('ZRAM_WRITEBACK_ENABLED');
    $self->sysfs()->required('backing_dev', cfg('ZRAM_BACKING_DEVICE'), 'zram backing_dev');
    if (cfg('ZRAM_COMPRESSED_WRITEBACK')) {
        $self->sysfs()->candidates('compressed_writeback', 'zram compressed_writeback', qw(yes 1))
            or fatal('failed to set zram compressed_writeback');
    }
    $self->sysfs()->required(
        'writeback_batch_size',
        writeback_batch_size_for_state('normal'),
        'zram initial writeback_batch_size',
    );
    $self->sysfs()->required(
        'writeback_limit_enable',
        cfg('ZRAM_WRITEBACK_LIMIT_ENABLE'),
        'zram writeback_limit_enable',
    );
    $self->sysfs()->required('writeback_limit', $writeback_pages, 'zram writeback_limit')
        if cfg('ZRAM_WRITEBACK_LIMIT_ENABLE');
}

sub start {
    my ($self) = @_;
    my $device = cfg('ZRAM_SWAP_DEVICE');
    if (!-b $device) {
        $self->_run('/usr/sbin/modprobe', 'zram', 'num_devices=1')
            or fatal('failed to load zram kernel module');
    }
    $self->_wait_for_block($device, 10) or fatal("zram device node not present: $device");
    -d cfg('ZRAM_SYSFS') or fatal('zram sysfs path is unavailable: ' . cfg('ZRAM_SYSFS'));
    $self->backing()->prepare() if cfg('ZRAM_WRITEBACK_ENABLED');
    $self->reset();
    my ($size_mib, $mem_mib, $writeback_pages) = $self->_dynamic_sizes();
    my $streams = cfg('ZRAM_MAX_COMP_STREAMS');
    $streams = 1 if !$streams;
    $self->sysfs()->optional('max_comp_streams', $streams, 'zram max_comp_streams');
    $self->_configure_algorithms();
    $self->_configure_writeback($writeback_pages);
    $self->sysfs()->required('mem_limit', $mem_mib * 1_048_576, 'zram mem_limit');
    $self->sysfs()->required('disksize', $size_mib * 1_048_576, 'zram disksize');
    $self->sysfs()->optional('mem_used_max', 0, 'zram mem_used_max reset');
    $self->_run('/sbin/mkswap', '-L', 'zram0', $device) or fatal("failed to format zram swap $device");
    $self->_run('/sbin/swapon', '-p', cfg('ZRAM_SWAP_PRIORITY'), $device)
        or fatal("failed to activate zram swap $device");
    return 0;
}

sub stop {
    my ($self) = @_;
    $self->reset();
    $self->backing()->close() if cfg('ZRAM_WRITEBACK_ENABLED');
    return 0;
}

sub wait_backing {
    my ($self) = @_;
    return 0 if !cfg('ZRAM_WRITEBACK_ENABLED');
    $self->backing()->wait_until_ready();
    return 0;
}

sub status {
    my ($self) = @_;
    my $device = cfg('ZRAM_SWAP_DEVICE');
    my $backing = cfg('ZRAM_BACKING_DEVICE');
    my $state = $self->sysfs()->read('initstate') // 'unknown';
    my $ro = -b $backing ? $self->backing()->_block_read_only($backing) : undef;
    printf "enabled=1\n";
    printf "zram_device=%s\n", $device;
    printf "zram_device_present=%d\n", -b $device ? 1 : 0;
    printf "zram_sysfs=%s\n", cfg('ZRAM_SYSFS');
    printf "zram_sysfs_exists=%d\n", -d cfg('ZRAM_SYSFS') ? 1 : 0;
    printf "zram_initialized=%d\n", $self->_is_uninitialized() ? 0 : 1;
    printf "zram_swap_active=%d\n", swap_active($device) ? 1 : 0;
    printf "backing_mapper=%s\n", cfg('ZRAM_BACKING_MAPPER_NAME');
    printf "backing_device=%s\n", $backing;
    printf "backing_mapper_exists=%d\n", -b $backing ? 1 : 0;
    printf "backing_mapper_writable=%d\n", defined $ro && !$ro ? 1 : 0;
    return 0;
}

1;
