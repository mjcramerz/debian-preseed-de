package Zram::Config;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Base qw(Str);

use Exporter qw(import);
use Zram::Config::Parser qw(parse_file);
use Zram::Config::Validator qw(normalize_config);
use Zram::Error qw(fatal);
use Zram::Logger qw(set_active_log_level);

our @EXPORT_OK = qw(load_config validate_config cfg cfg_default config);

my %CONFIG;

has path => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

sub load {
    my ($self) = @_;
    return load_config($self->path());
}

sub load_config {
    my ($path) = @_;
    my $parsed = parse_file($path);
    my $normalized = normalize_config($parsed);
    %CONFIG = %{$normalized};
    set_active_log_level($CONFIG{ZRAM_LOG_LEVEL} // $ENV{ZRAM_LOG_LEVEL} // 'error');
    return \%CONFIG;
}

sub config {
    return \%CONFIG;
}

sub cfg {
    my ($key) = @_;
    exists $CONFIG{$key} or fatal("missing required zram config key $key");
    return $CONFIG{$key};
}

sub cfg_default {
    my ($key, $default) = @_;
    return exists $CONFIG{$key} ? $CONFIG{$key} : $default;
}

sub validate_config {
    my (%opts) = @_;
    my $require_sysfs = exists $opts{require_sysfs} ? $opts{require_sysfs} : 1;
    if ($require_sysfs) {
        -d cfg('ZRAM_SYSFS') or fatal('zram sysfs path is unavailable: ' . cfg('ZRAM_SYSFS'));
    }
    if (cfg('ZRAM_WRITEBACK_ENABLED')) {
        cfg('ZRAM_SWAP_DEVICE') ne cfg('ZRAM_BACKING_DEVICE')
            or fatal('zram device and writeback backing device must differ');
    }
}

1;
