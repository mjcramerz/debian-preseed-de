package DigitalAssets::Runtime;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use DigitalAssets::Actions;
use DigitalAssets::Logger qw(log_msg);
use DigitalAssets::Policy;
use DigitalAssets::Session;

has terminal => ( is => 'ro', default => sub { '/usr/local/bin/labwc-terminal' } );
has policy   => ( is => 'ro', lazy => 1, builder => sub { DigitalAssets::Policy->new() } );
has session  => ( is => 'ro', lazy => 1, builder => sub { DigitalAssets::Session->new() } );
has actions  => ( is => 'ro', lazy => 1, builder => sub { DigitalAssets::Actions->new() } );

sub _validate_runtime_arguments {
    my ($self, @arguments) = @_;
    @arguments >= 1 or die "labwc-digital-assets-action: missing Digital Assets action\n";
    my $action = $self->policy()->assert_action(shift @arguments);
    @arguments >= 1 or die "labwc-digital-assets-action: action requires a file or managed selection list\n";
    for my $argument (@arguments) {
        defined($argument) && length($argument) <= 4096 && $argument !~ /[\0\r\n]/
            or die "labwc-digital-assets-action: unsafe action argument\n";
    }
    return ($action, @arguments);
}

sub run {
    my ($self, @argv) = @_;
    $self->session()->assert_desktop_user();
    my $run_in_terminal = @argv && $argv[0] eq '--run';
    shift @argv if $run_in_terminal;
    my ($action, @arguments) = $self->_validate_runtime_arguments(@argv);
    if ($run_in_terminal) {
        log_msg('info', "running Digital Assets action: $action");
        return $self->actions()->run($action, @arguments);
    }
    -x $self->terminal()
        or die "labwc-digital-assets-action: labwc-terminal is unavailable\n";
    log_msg('info', "opening Digital Assets action terminal: $action");
    exec { $self->terminal() } $self->terminal(), '-e', '/usr/local/bin/labwc-digital-assets-action', '--run', $action, @arguments
        or die "labwc-digital-assets-action: cannot open action terminal: $!\n";
}

1;
