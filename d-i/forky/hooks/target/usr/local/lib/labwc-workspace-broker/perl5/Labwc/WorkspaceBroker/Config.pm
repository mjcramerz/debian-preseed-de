package Labwc::WorkspaceBroker::Config;
use strict;
use warnings;
use Fcntl qw(:DEFAULT :mode);
my %RANGE = (
    GROUP_SLOTS => [24, 4, 64], PICKER_LINES => [12, 2, 32],
    PICKER_WIDTH => [64, 24, 120], TOOLTIP_WINDOWS => [8, 1, 32],
);
sub load {
    my %cfg = map { lc($_) => $RANGE{$_}[0] } keys %RANGE;
    my $path = '/etc/default/labwc-desktop';
    sysopen(my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or die "managed defaults: $!\n";
    my @s = stat($fh);
    die "unsafe managed defaults\n" unless S_ISREG($s[2]) && $s[4] == 0 && !($s[2] & 0022) && $s[7] <= 262144;
    while (my $line = <$fh>) {
        next unless $line =~ /\ALABWC_WORKSPACE_BROKER_([A-Z_]+)=(.*?)\s*\z/;
        my ($key, $value) = ($1, $2);
        die "unknown broker setting\n" unless exists $RANGE{$key};
        $value =~ s/\A(['"])([0-9]+)\1\z/$2/;
        my (undef, $lo, $hi) = @{$RANGE{$key}};
        die "invalid broker setting\n" unless $value =~ /\A[0-9]{1,3}\z/ && $value >= $lo && $value <= $hi;
        $cfg{lc($key)} = 0 + $value;
    }
    close $fh;
    return \%cfg;
}
1;
