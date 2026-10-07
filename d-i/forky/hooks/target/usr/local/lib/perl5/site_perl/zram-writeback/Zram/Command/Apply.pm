package Zram::Command::Apply;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Exporter qw(import);
use Zram::Budget qw(refresh_daily_writeback_budget);
use Zram::Config qw(cfg);
use Zram::Logger qw(log_msg);
use Zram::Metrics qw(capture_zram_state);
use Zram::Sysfs qw(write_attr_optional);
use Zram::Tuning qw(apply_writeback_batch_size);

our @EXPORT_OK = qw(run);

sub run {
    return __PACKAGE__->new()->execute();
}

sub execute {
    my ($self) = @_;
    if (!cfg('ZRAM_WRITEBACK_ENABLED')) {
        log_msg('debug', 'skipping zram writeback apply; policy disabled');
        return 0;
    }
    my $sysfs = cfg('ZRAM_SYSFS');
    capture_zram_state('apply-before', state => 'normal', scan_block_state => 0);
    apply_writeback_batch_size('normal');
    write_attr_optional("$sysfs/writeback_limit_enable", cfg('ZRAM_WRITEBACK_LIMIT_ENABLE'), 'zram writeback_limit_enable');
    refresh_daily_writeback_budget();
    capture_zram_state('apply-after', state => 'normal', scan_block_state => 0);
    return 0;
}

1;
