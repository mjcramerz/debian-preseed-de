package Zram::Procfs;

use strict;
use warnings;

use Exporter qw(import);
use Zram::Config qw(cfg);
use Zram::Procfs::Reader;

our @EXPORT_OK = qw(
  proc_path memory_pressure_snapshot psi_avg10_millionths mem_available_bytes mem_total_bytes
);

my $READER;

sub _reader {
    $READER ||= Zram::Procfs::Reader->new();
    return $READER;
}

sub proc_path {
    my (@parts) = @_;
    my $root = cfg('ZRAM_PROCFS_ROOT');
    $root =~ s{/+\z}{};
    return join '/', $root, @parts;
}

sub _read_memory_psi {
    return _reader()->memory_psi(proc_path('pressure', 'memory'));
}

sub _read_meminfo {
    return _reader()->meminfo(proc_path('meminfo'));
}

sub memory_pressure_snapshot {
    my $mem = _read_meminfo();
    my $psi = _read_memory_psi();
    return {
        mem_available_bytes => $mem->{available},
        mem_total_bytes => $mem->{total},
        psi_some_avg10_millionths => $psi->{some},
        psi_full_avg10_millionths => $psi->{full},
    };
}

sub psi_avg10_millionths {
    my ($field) = @_;
    return _read_memory_psi()->{$field} || 0;
}

sub mem_available_bytes {
    return _read_meminfo()->{available};
}

sub mem_total_bytes {
    return _read_meminfo()->{total};
}

1;
