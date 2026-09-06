package AndroidADB::ADB::Device;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Validation qw(fail validate_serial);

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

has server => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub run_host {
    my ($self, $timeout_seconds, @arguments) = @_;
    $self->server->ensure_responsive;
    my $status = $self->command->run(
        $timeout_seconds,
        $self->config->require_tool('adb'),
        @arguments,
    );
    if ($status != 0 && !$self->server->probe) {
        print STDERR "ADB server stopped responding during the command; repairing it for the next action.\n";
        $self->server->repair;
    }
    return $status;
}

sub capture_host {
    my ($self, $timeout_seconds, @arguments) = @_;
    $self->server->ensure_responsive;
    my $result = $self->command->capture(
        $timeout_seconds,
        $self->config->require_tool('adb'),
        @arguments,
    );
    if ($result->{status} != 0) {
        if (!$self->server->probe) {
            print STDERR "ADB server stopped responding during the command; repairing it for the next action.\n";
            $self->server->repair;
        }
        fail('Android Debug Bridge host command failed with status ' . $result->{status});
    }
    return $result->{stdout};
}

sub capture_devices {
    my ($self) = @_;
    return $self->capture_host(12, 'devices', '-l');
}

sub device_state {
    my ($self, $serial) = @_;
    validate_serial($serial);
    my $devices = $self->capture_devices;
    for my $line (split /\n/, $devices) {
        next if $line !~ /\S/;
        my ($line_serial, $state) = split /\s+/, $line, 3;
        next if !defined($line_serial) || $line_serial ne $serial;
        return 'no-permissions' if index($line, 'no permissions') >= 0;
        return defined($state) && $state ne q{} ? $state : 'unknown';
    }
    return 'disconnected';
}

sub explain_state {
    my ($self, $serial) = @_;
    my $state = $self->device_state($serial);
    if ($state eq 'device') {
        print "Device $serial is connected and authorized.\n";
    }
    elsif ($state eq 'unauthorized') {
        print "Device $serial is unauthorized.\n";
        print "Unlock the phone, accept the RSA USB-debugging prompt, then retry.\n";
        print "If no prompt appears, revoke USB debugging authorizations on the phone, reconnect the cable, and accept the new key.\n";
    }
    elsif ($state eq 'no-permissions') {
        print "Device $serial is visible but the desktop session lacks USB permission.\n";
        print "Confirm the user is in plugdev, log out and back in after installation, reconnect the cable, and verify the managed udev rules loaded.\n";
        print "Use a data-capable USB cable and select a USB mode that exposes Android debugging.\n";
    }
    elsif ($state eq 'offline') {
        print "Device $serial is offline.\n";
        print "The launcher can reconnect offline transports; otherwise unlock and reconnect the device, then retry.\n";
    }
    elsif ($state eq 'disconnected') {
        print "Device $serial is disconnected.\n";
        print "Reconnect the USB cable or wireless endpoint. Device actions wait up to 60 seconds for the same serial to return.\n";
    }
    else {
        print "Device $serial reports state: $state\n";
    }
    return $state;
}

sub wait_for_serial {
    my ($self, $serial) = @_;
    validate_serial($serial);
    $self->server->ensure_responsive;

    my $state = $self->device_state($serial);
    if ($state eq 'device') {
        return 1;
    }
    if ($state eq 'unauthorized' || $state eq 'no-permissions') {
        $self->explain_state($serial);
        fail('device is not ready for commands');
    }
    if ($state eq 'offline') {
        print "Device $serial is offline; requesting a transport reconnect.\n";
        $self->command->run_quiet(
            12,
            $self->config->require_tool('adb'),
            '-s',
            $serial,
            'reconnect',
        );
    }
    elsif ($state eq 'disconnected') {
        print 'Waiting up to '
            . $self->config->adb_wait_seconds
            . " seconds for device $serial to reconnect.\n";
    }

    my $status = $self->command->run_signal(
        'TERM',
        3,
        $self->config->adb_wait_seconds,
        $self->config->require_tool('adb'),
        '-s',
        $serial,
        'wait-for-device',
    );
    if ($status != 0) {
        $self->explain_state($serial);
        fail("timed out waiting for device $serial");
    }

    $state = $self->device_state($serial);
    if ($state ne 'device') {
        $self->explain_state($serial);
        fail('device returned but is not authorized and ready');
    }
    return 1;
}

sub run_serial {
    my ($self, $timeout_seconds, $serial, @arguments) = @_;
    validate_serial($serial);
    $self->wait_for_serial($serial);
    my $status = $self->command->run(
        $timeout_seconds,
        $self->config->require_tool('adb'),
        '-s',
        $serial,
        @arguments,
    );
    $self->_after_serial_failure($serial) if $status != 0;
    return $status;
}

sub run_serial_signal {
    my ($self, $signal, $kill_after_seconds, $timeout_seconds, $serial, @arguments) = @_;
    validate_serial($serial);
    $self->wait_for_serial($serial);
    my $status = $self->command->run_signal(
        $signal,
        $kill_after_seconds,
        $timeout_seconds,
        $self->config->require_tool('adb'),
        '-s',
        $serial,
        @arguments,
    );
    $self->_after_serial_failure($serial) if $status != 0;
    return $status;
}

sub capture_serial {
    my ($self, $timeout_seconds, $serial, @arguments) = @_;
    validate_serial($serial);
    $self->wait_for_serial($serial);
    my $result = $self->command->capture(
        $timeout_seconds,
        $self->config->require_tool('adb'),
        '-s',
        $serial,
        @arguments,
    );
    if ($result->{status} != 0) {
        $self->_after_serial_failure($serial);
        fail('Android Debug Bridge device command failed with status ' . $result->{status});
    }
    return $result->{stdout};
}

sub device_summary {
    my ($self, $serial) = @_;
    my %properties = (
        'Manufacturer'  => 'ro.product.manufacturer',
        'Model'         => 'ro.product.model',
        'Device'        => 'ro.product.device',
        'Android'       => 'ro.build.version.release',
        'API level'     => 'ro.build.version.sdk',
        'Build'         => 'ro.build.display.id',
        'Security patch'=> 'ro.build.version.security_patch',
        'Verified boot' => 'ro.boot.verifiedbootstate',
    );

    print "--- Device $serial ---\n";
    for my $label (
        'Manufacturer',
        'Model',
        'Device',
        'Android',
        'API level',
        'Build',
        'Security patch',
        'Verified boot',
    ) {
        my $value = $self->capture_serial(
            30,
            $serial,
            'shell',
            'getprop',
            $properties{$label},
        );
        $value =~ s/\r//g;
        $value =~ s/\n+\z//;
        print "$label: $value\n";
    }
    return 0;
}

sub diagnostics {
    my ($self) = @_;
    $self->server->ensure_responsive;
    my $devices = $self->capture_devices;
    print $devices;
    print "\n" if $devices !~ /\n\z/;

    my %counts = (
        device         => 0,
        'no-permissions' => 0,
        offline        => 0,
        unauthorized   => 0,
    );
    my $total = 0;
    for my $line (split /\n/, $devices) {
        next if $line !~ /\S/ || $line =~ /\AList of devices attached/;
        ++$total;
        my (undef, $state) = split /\s+/, $line, 3;
        $state = 'no-permissions' if index($line, 'no permissions') >= 0;
        ++$counts{$state} if exists($counts{$state});
    }

    print "\nSummary: total=$total ready=$counts{device} unauthorized=$counts{unauthorized} offline=$counts{offline} permission-errors=$counts{'no-permissions'}\n";
    print "No Android transports are visible. Check the data cable, USB mode, Developer Options, USB debugging, and wireless endpoint.\n"
        if $total == 0;
    print "Unauthorized devices must be unlocked and approved at the RSA debugging prompt.\n"
        if $counts{unauthorized} != 0;
    print "Offline transports can often be recovered with Reconnect Offline Devices or Repair / Restart ADB Server.\n"
        if $counts{offline} != 0;
    print "Permission errors require plugdev membership, a fresh login, and loaded Android udev rules.\n"
        if $counts{'no-permissions'} != 0;
    return 0;
}

sub menu_devices {
    my ($self) = @_;
    my $devices = $self->capture_devices;
    for my $line (split /\n/, $devices) {
        next if $line !~ /\S/ || $line =~ /\AList of devices attached/;
        my @fields = split /\s+/, $line;
        my $serial = $fields[0];
        my $state  = index($line, 'no permissions') >= 0
            ? 'no-permissions'
            : ($fields[1] // 'unknown');
        my ($model) = $line =~ /(?:^|\s)model:([^\s]+)/;
        print defined($model)
            ? "$serial [$state] $model\n"
            : "$serial [$state]\n";
    }
    return 0;
}

sub _after_serial_failure {
    my ($self, $serial) = @_;
    if (!$self->server->probe) {
        print STDERR "ADB server stopped responding during the device command; repairing it for the next action.\n";
        $self->server->repair;
    }
    eval { $self->explain_state($serial); 1 };
    return;
}

1;
