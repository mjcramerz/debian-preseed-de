package Zram::Stats;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Sysfs qw(normalize_attr);

our @EXPORT_OK = qw(parse_stat_line read_zram_stat_attrs zram_stat_names);

my @STAT_NAMES = qw(mm_stat io_stat bd_stat debug_stat);

my %STAT_FIELDS = (
    mm_stat => [qw(
      orig_data_size compr_data_size mem_used_total mem_limit mem_used_max
      same_pages pages_compacted huge_pages huge_pages_since
    )],
    io_stat => [qw(
      failed_reads failed_writes invalid_io notify_free
    )],
    bd_stat => [qw(
      bd_count bd_reads bd_writes
    )],
    debug_stat => [qw(
      version
    )],
);

sub zram_stat_names {
    return @STAT_NAMES;
}

sub parse_stat_line {
    my ($name, $line) = @_;
    my %parsed;
    return \%parsed if !defined $line || $line eq '';
    my $fields = $STAT_FIELDS{$name} || [];
    my @values = split /\s+/, $line;
    for my $idx (0 .. $#values) {
        last if $idx > $#{$fields};
        next if !defined $values[$idx] || $values[$idx] !~ /\A[0-9]+\z/;
        $parsed{$fields->[$idx]} = 0 + $values[$idx];
    }
    return \%parsed;
}

sub read_zram_stat_attrs {
    my ($sysfs) = @_;
    my (%raw, %parsed);
    for my $name (@STAT_NAMES) {
        my $value = normalize_attr("$sysfs/$name");
        $raw{$name} = $value;
        $parsed{$name} = parse_stat_line($name, $value);
    }
    return {
        raw => \%raw,
        parsed => \%parsed,
    };
}

1;
