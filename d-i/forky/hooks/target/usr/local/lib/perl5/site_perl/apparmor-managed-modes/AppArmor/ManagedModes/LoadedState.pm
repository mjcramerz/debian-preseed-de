package AppArmor::ManagedModes::LoadedState;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

use AppArmor::ManagedModes::CLI qw(fatal);

our @EXPORT_OK = qw(
    contains_exact_line
    contains_label_prefix
    read_snapshot
);

sub read_snapshot {
    my ($path) = @_;

    open my $fh, '<:raw', $path ||
        fatal("cannot read loaded AppArmor profile state: $path");
    local $/;
    my $content = <$fh>;
    close $fh ||
        fatal("cannot read loaded AppArmor profile state: $path");
    return defined($content) ? $content : '';
}

sub contains_label_prefix {
    my ($snapshot, $label) = @_;

    return index($snapshot, "$label (") == 0 ||
        index($snapshot, "\n$label (") >= 0;
}

sub contains_exact_line {
    my ($snapshot, $line) = @_;

    for my $candidate (split(/\n/, $snapshot, -1)) {
        return 1 if $candidate eq $line;
    }
    return 0;
}

1;
