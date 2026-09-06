package Zram::Command::Writeback;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Exporter qw(import);
use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Sysfs qw(writeback_spec);
use Zram::Types qw(validate_writeback_spec);

our @EXPORT_OK = qw(run);

sub run {
    return __PACKAGE__->new()->execute(@_);
}

sub execute {
    my ($self, @args) = @_;
    @args or fatal('usage: zram-writeback writeback-spec <spec...>');
    my $spec = join(' ', @args);
    validate_writeback_spec(
        'writeback-spec',
        $spec,
        0,
        cfg('ZRAM_WRITEBACK_SPEC_MAX_BYTES'),
    );
    writeback_spec($spec) or fatal('zram writeback sysfs trigger rejected all candidate values');
    return 0;
}

1;
