package Zram::Setup::Config;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Base qw(Bool Str);

use Zram::Config qw(load_config validate_config);
use Zram::Error qw(fatal);

has defaults_path => (
    is      => 'ro',
    isa     => Str,
    default => sub { $ENV{ZRAM_DEFAULT_PATH} // '/etc/default/zram-writeback' },
);

has policy_path => (
    is      => 'ro',
    isa     => Str,
    default => sub { $ENV{ZRAM_POLICY_CONFIG} // '/etc/zram-writeback.conf' },
);

has enabled => (
    is      => 'rw',
    isa     => Bool,
    default => sub { 1 },
);

sub _read_defaults {
    my ($self) = @_;
    my $path = $self->defaults_path();

    $path =~ m{\A/(?:[A-Za-z0-9_.:+-]+/)*[A-Za-z0-9_.:+-]+\z}
        or fatal("zram defaults path must be a safe absolute path: $path");
    -r $path or fatal("missing zram defaults $path");
    -l $path and fatal("zram defaults path must not be a symlink: $path");

    open my $fh, '<', $path or fatal("failed to read zram defaults $path: $!");
    my %values;
    my $line_no = 0;
    while (my $line = <$fh>) {
        $line_no++;
        length($line) <= 512 or fatal("oversized zram defaults line $line_no in $path");
        chomp $line;
        $line =~ s/\r\z//;
        next if $line =~ /\A\s*(?:#|\z)/;
        my ($key, $value) = $line =~ /\A([A-Z][A-Z0-9_]*)=(.*)\z/
            or fatal("invalid zram defaults line $line_no in $path");
        $value =~ /\A"(.*)"\z/ and $value = $1;
        $value !~ /["'\x00-\x1f\x7f]/
            or fatal("unsupported quoting or control character in zram defaults $key");
        $value =~ m{\A[A-Za-z0-9_./:+= -]*\z}
            or fatal("unsafe value in zram defaults $key");
        $values{$key} = $value;
    }
    close $fh or fatal("failed to close zram defaults $path: $!");

    if (exists $values{ZRAM_ENABLE}) {
        $values{ZRAM_ENABLE} =~ /\A[01]\z/
            or fatal("ZRAM_ENABLE must be 0 or 1, got '$values{ZRAM_ENABLE}'");
        $self->enabled($values{ZRAM_ENABLE} eq '1' ? 1 : 0);
    }
    return \%values;
}

sub load {
    my ($self) = @_;
    $self->_read_defaults();
    load_config($self->policy_path());
    validate_config(require_sysfs => 0);
    return $self;
}

1;
