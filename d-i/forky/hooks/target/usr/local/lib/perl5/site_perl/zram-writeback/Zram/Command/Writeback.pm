package Zram::Command::Writeback;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Exporter qw(import);
use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Budget qw(writeback_budget_pages_available);
use Zram::IOPressure qw(io_pressure_snapshot io_pressure_log_fields);
use Zram::Logger qw(log_msg);
use Zram::Pressure qw(determine_pressure_state);
use Zram::Tuning qw(apply_writeback_batch_size writeback_pass_pages_for_state);
use Zram::Sysfs qw(writeback_spec);
use Zram::Types qw(validate_writeback_spec count_page_index_spec_pages);

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
    cfg('ZRAM_WRITEBACK_ENABLED') or fatal('zram writeback is disabled');
    # This diagnostic command is an explicit operator request, not automatic
    # cold maintenance. It still cannot bypass an I/O-pressure admission cap.
    my ($state) = determine_pressure_state();
    $state = 'pressure' if $state eq 'normal';
    my $io = io_pressure_snapshot();
    my $tuning = apply_writeback_batch_size($state, $io);
    my $budget = writeback_budget_pages_available();
    defined $budget && $budget <= 0 and fatal('zram writeback budget exhausted');
    my $limit = writeback_pass_pages_for_state($state, $budget, $io);
    if ($io->{throttle}) {
        $spec !~ /(?:\A|\s)type=/
            or fatal('I/O pressure requires bounded page indexes; use run for automatic cold-page selection');
        if (!$tuning->{applied} && $limit > $tuning->{effective_batch_size}) {
            $limit = $tuning->{effective_batch_size};
        }
        my $pages = count_page_index_spec_pages('writeback-spec', $spec, cfg('ZRAM_WRITEBACK_SPEC_MAX_BYTES'));
        $pages <= $limit
            or fatal("I/O pressure limits this explicit writeback request to $limit pages");
    }
    log_msg('info', 'zram explicit writeback admission state=' . $state . ' ' .
        io_pressure_log_fields($io) . ' batch_size=' . $tuning->{effective_batch_size} .
        ' batch_applied=' . $tuning->{applied} .
        ' io_page_limit=' . ($io->{throttle} ? $limit : 'not-throttled'));
    writeback_spec($spec) or fatal('zram writeback sysfs trigger rejected all candidate values');
    return 0;
}

1;
