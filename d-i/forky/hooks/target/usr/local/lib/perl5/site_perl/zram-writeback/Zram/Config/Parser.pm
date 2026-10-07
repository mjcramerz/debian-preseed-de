package Zram::Config::Parser;

use strict;
use warnings;

use Fcntl qw(O_NOFOLLOW O_RDONLY);
use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Numeric qw(PositiveInt);

use Exporter qw(import);
use Zram::Error qw(fatal);

our @EXPORT_OK = qw(parse_file);

has max_config_bytes => (
    is      => 'ro',
    isa     => PositiveInt,
    default => sub { 65_536 },
);

has max_config_line_bytes => (
    is      => 'ro',
    isa     => PositiveInt,
    default => sub { 4_096 },
);

sub _trim {
    my ($value) = @_;
    $value =~ s/\A\s+//;
    $value =~ s/\s+\z//;
    return $value;
}

sub _parse_value {
    my ($label, $value) = @_;
    $value = _trim($value);
    if ($value =~ /\A"(.*)"\z/s) {
        $value = $1;
        $value =~ s/\\(["\\])/$1/g;
    } elsif ($value =~ /\A'(.*)'\z/s) {
        $value = $1;
    } else {
        $value =~ s/(?:\A|\s+)[;#].*\z//;
        $value = _trim($value);
    }
    $value !~ /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/ or fatal("$label contains control characters");
    return $value;
}

sub parse_file {
    my ($path) = @_;
    return __PACKAGE__->new()->parse($path);
}

sub _read_contents {
    my ($self, $path) = @_;
    defined $path && !ref($path) && $path ne ''
        or fatal('zram-writeback config path must be a non-empty scalar');

    my @stat = lstat($path)
        or fatal("missing zram-writeback config $path: $!");
    -l _ and fatal("zram-writeback config must not be a symlink: $path");
    -f _ or fatal("zram-writeback config must be a regular file: $path");
    ($stat[2] & 0022) == 0
        or fatal("zram-writeback config must not be group or world writable: $path");

    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW
        or fatal("missing zram-writeback config $path: $!");
    binmode $fh, ':raw'
        or fatal("failed to set raw mode for zram-writeback config $path: $!");

    my $max_bytes = $self->max_config_bytes();
    my $read_limit = $max_bytes + 1;
    my $contents = '';
    while (length($contents) < $read_limit) {
        my $remaining = $read_limit - length($contents);
        my $read = read($fh, my $chunk, $remaining);
        defined $read
            or fatal("failed to read zram-writeback config $path: $!");
        last if $read == 0;
        $contents .= $chunk;
    }
    close $fh or fatal("failed to close zram-writeback config $path: $!");

    length($contents) <= $max_bytes or fatal(
        "zram-writeback config $path exceeds $max_bytes bytes"
    );
    return $contents;
}

sub parse {
    my ($self, $path) = @_;
    my %config;
    my $section = '';
    my $line_no = 0;
    my $contents = $self->_read_contents($path);
    my @lines = length($contents) ? split(/\n/, $contents, -1) : ();
    pop @lines if @lines && $contents =~ /\n\z/;

    for my $line (@lines) {
        $line_no++;
        length($line) <= $self->max_config_line_bytes() or fatal(
            "line $line_no in $path exceeds " . $self->max_config_line_bytes() . ' bytes'
        );
        $line =~ s/\r\z//;
        next if $line =~ /\A\s*(?:[;#]|\z)/;
        if ($line =~ /\A\s*\[([A-Za-z][A-Za-z0-9_-]*)\]\s*(?:[;#].*)?\z/) {
            $section = lc($1);
            $config{$section} ||= {};
            next;
        }
        $section ne '' or fatal("key outside any section at $path line $line_no");
        my ($key, $value) = $line =~ /\A\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(.*)\z/;
        defined $key or fatal("invalid INI syntax at $path line $line_no");
        $key = lc($key);
        exists $config{$section}{$key} and fatal("duplicate key [$section].$key at $path line $line_no");
        $config{$section}{$key} = _parse_value("[$section].$key", $value);
    }
    return \%config;
}

1;
