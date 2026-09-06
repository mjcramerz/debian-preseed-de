package AndroidADB::Vendor::GooglePixel;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Validation qw(validate_serial);

# The existing public fastboot menu is device-generic.  This module owns the
# Google/Pixel-capable fastboot transport without rejecting other compatible
# fastboot devices, preserving that established public contract.

has config => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has command => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub list_devices {
    my ($self) = @_;
    return $self->command->run_signal(
        'TERM',
        2,
        15,
        $self->_fastboot,
        'devices',
        '-l',
    );
}

sub menu_devices {
    my ($self) = @_;
    my $result = $self->command->capture_signal(
        'TERM',
        2,
        12,
        $self->_fastboot,
        'devices',
        '-l',
    );
    return $result->{status} if $result->{status} != 0;
    for my $line (split /\n/, $result->{stdout}) {
        next if $line !~ /\S/;
        my @fields = split /\s+/, $line;
        my $serial = $fields[0];
        print "$serial [fastboot]";
        print " $_" for @fields[1 .. $#fields];
        print "\n";
    }
    return 0;
}

sub info {
    my ($self, $serial) = @_;
    validate_serial($serial);
    my $status = $self->command->run(
        30,
        $self->_fastboot,
        '-s',
        $serial,
        'getvar',
        'product',
    );
    return $status if $status != 0;
    for my $variable (qw(unlocked current-slot secure)) {
        $self->command->run(
            30,
            $self->_fastboot,
            '-s',
            $serial,
            'getvar',
            $variable,
        );
    }
    return 0;
}

sub reboot {
    my ($self, $serial, $bootloader) = @_;
    validate_serial($serial);
    return $self->command->run(
        60,
        $self->_fastboot,
        '-s',
        $serial,
        'reboot',
        ($bootloader ? ('bootloader') : ()),
    );
}

sub _fastboot {
    my ($self) = @_;
    return $self->config->require_tool('fastboot', 'fastboot is not installed');
}

1;
