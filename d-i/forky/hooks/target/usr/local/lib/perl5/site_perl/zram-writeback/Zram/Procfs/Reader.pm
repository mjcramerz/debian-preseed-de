package Zram::Procfs::Reader;

use strict;
use warnings;

use Fcntl qw(O_NOFOLLOW O_RDONLY);
use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Numeric qw(PositiveInt);

use Zram::Error qw(fatal);
use Zram::Types qw(decimal_to_millionths);

has max_file_bytes => (
    is      => 'ro',
    isa     => PositiveInt,
    default => sub { 64 * 1024 },
);

has max_line_bytes => (
    is      => 'ro',
    isa     => PositiveInt,
    default => sub { 4096 },
);

sub _for_each_line {
    my ($self, $path, $callback) = @_;
    ref $callback eq 'CODE'
        or fatal('zram procfs reader requires a line callback');

    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW or return 0;
    binmode $fh, ':raw'
        or fatal("failed to set raw mode for zram procfs input $path: $!");

    my $max_file_bytes = $self->max_file_bytes();
    my $max_line_bytes = $self->max_line_bytes();
    my $read_limit = $max_file_bytes + 1;
    my $bytes_read = 0;
    my $pending = '';

    while ($bytes_read < $read_limit) {
        my $remaining = $read_limit - $bytes_read;
        my $read_size = $remaining < 4096 ? $remaining : 4096;
        my $read = read($fh, my $chunk, $read_size);
        defined $read
            or fatal("failed to read zram procfs input $path: $!");
        last if $read == 0;

        $bytes_read += $read;
        $bytes_read <= $max_file_bytes
            or fatal("zram procfs input exceeds byte limit: $path");
        $pending .= $chunk;

        while (1) {
            my $newline = index($pending, "\n");
            last if $newline < 0;
            my $line = substr($pending, 0, $newline + 1, '');
            length($line) <= $max_line_bytes
                or fatal("zram procfs input line exceeds byte limit: $path");
            $callback->($line);
        }
        length($pending) <= $max_line_bytes
            or fatal("zram procfs input line exceeds byte limit: $path");
    }

    if (length($pending)) {
        length($pending) <= $max_line_bytes
            or fatal("zram procfs input line exceeds byte limit: $path");
        $callback->($pending);
    }
    close $fh or fatal("failed to close zram procfs input $path: $!");
    return 1;
}

sub memory_psi {
    my ($self, $path) = @_;
    my %psi = (some => 0, full => 0);
    $self->_for_each_line($path, sub {
        my ($line) = @_;
        $line =~ /\A(some|full)\s/ or return;
        my $field = $1;
        $line =~ /(?:\A|\s)avg10=([0-9]+(?:\.[0-9]+)?)(?:\s|\z)/ or return;
        $psi{$field} = decimal_to_millionths("memory PSI $field avg10", $1);
    });
    return \%psi;
}

sub meminfo {
    my ($self, $path) = @_;
    my %mem = (available => 0, total => 0);
    $self->_for_each_line($path, sub {
        my ($line) = @_;
        if ($line =~ /\AMemAvailable:\s+([0-9]+)\s+kB\b/) {
            $mem{available} = (0 + $1) * 1024;
        } elsif ($line =~ /\AMemTotal:\s+([0-9]+)\s+kB\b/) {
            $mem{total} = (0 + $1) * 1024;
        }
    });
    return \%mem;
}

1;
