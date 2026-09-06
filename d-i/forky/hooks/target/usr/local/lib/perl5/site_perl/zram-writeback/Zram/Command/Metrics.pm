package Zram::Command::Metrics;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Exporter qw(import);
use Zram::Metrics qw(capture_zram_state);

our @EXPORT_OK = qw(run);

sub run {
    return __PACKAGE__->new()->execute(@_);
}

sub execute {
    my ($self, $phase, $print_metrics) = @_;
    $phase ||= 'metrics';
    my $stats = capture_zram_state($phase);
    if ($print_metrics) {
        for my $key (sort keys %{$stats}) {
            next if ref $stats->{$key};
            print "$key=$stats->{$key}\n";
        }
    }
    return 0;
}

1;
