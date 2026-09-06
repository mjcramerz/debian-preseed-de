package Zram::Debugfs;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Config qw(cfg);

our @EXPORT_OK = qw(block_state_path block_state_available);

sub block_state_path {
    return cfg('ZRAM_BLOCK_STATE');
}

sub block_state_available {
    return -r block_state_path() ? 1 : 0;
}

1;
