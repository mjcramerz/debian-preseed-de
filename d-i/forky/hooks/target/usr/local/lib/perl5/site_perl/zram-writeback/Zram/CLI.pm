package Zram::CLI;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::Options
  protect_argv => 0,
  flavour => [qw(require_order no_auto_abbrev)],
  usage_string => 'USAGE: %c [--config PATH] [--version] <command> [command arguments...]';
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Path::Tiny qw(path);
use Types::Path::Tiny qw(Path);
use Types::Standard qw(Bool);

use Zram;
use Zram::Runtime;

our @EXPORT_OK = qw(run);

option config => (
    is      => 'ro',
    isa     => Path,
    coerce  => Path->coercion,
    format  => 's',
    default => sub {
        return path($ENV{ZRAM_WRITEBACK_CONFIG} // '/etc/zram-writeback.conf');
    },
    doc => 'path to the zram writeback policy config',
);

option version => (
    is      => 'ro',
    isa     => Bool,
    default => sub { 0 },
    doc     => 'print the zram-writeback version and exit',
);

sub _usage {
    my ($exit_code) = @_;
    $exit_code = 2 if !defined $exit_code;
    print STDERR "usage: zram-writeback [--config PATH] {status|metrics|snapshot|run|daemon|writeback-spec <spec...>|apply|validate-runtime|reset-state}\n";
    return $exit_code;
}

sub run {
    my @argv = @_;
    local @ARGV = @argv;
    my $options = __PACKAGE__->new_with_options();

    if ($options->version()) {
        print "zram-writeback " . Zram::version() . "\n";
        return 0;
    }

    my $action = shift @ARGV;
    return _usage(2) if !defined $action || $action eq '';
    return Zram::Runtime->new(
        config_path => $options->config()->stringify(),
        action      => $action,
        arguments   => [@ARGV],
    )->run();
}

1;
