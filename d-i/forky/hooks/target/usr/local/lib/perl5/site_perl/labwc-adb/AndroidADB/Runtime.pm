package AndroidADB::Runtime;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::ADB::Backup;
use AndroidADB::ADB::Device;
use AndroidADB::ADB::Package;
use AndroidADB::ADB::Permissions;
use AndroidADB::ADB::Server;
use AndroidADB::ADB::Transfer;
use AndroidADB::Command;
use AndroidADB::Firmware::Archive;
use AndroidADB::Firmware::Manifest;
use AndroidADB::Firmware::Storage;
use AndroidADB::Lock;
use AndroidADB::Notification;
use AndroidADB::Validation qw(fail validate_serial);
use AndroidADB::Vendor::GooglePixel;
use AndroidADB::Vendor::Samsung;

has config => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has command => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_command',
);

has lock => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_lock',
);

has storage => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_storage',
);

has server => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_server',
);

has device => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_device',
);

has package => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_package',
);

has permissions => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_permissions',
);

has transfer => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_transfer',
);

has backup => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_backup',
);

has samsung => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_samsung',
);

has google_pixel => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_google_pixel',
);

has notification => (
    is      => 'lazy',
    isa     => Object,
    builder => '_build_notification',
);

sub ensure_action_tools {
    my ($self, $action) = @_;
    if ($action =~ /\Afastboot-/) {
        $self->config->require_tool('fastboot', 'fastboot is not installed');
    }
    if ($action =~ /\Asamsung-/) {
        $self->config->require_tool('samloader', 'samloader-rs is not installed');
        $self->config->require_tool(
            'samsung_extractor',
            'managed Samsung firmware extractor is not installed',
        );
    }
    return;
}

sub menu_devices {
    my ($self) = @_;
    return $self->device->menu_devices;
}

sub menu_fastboot_devices {
    my ($self) = @_;
    return $self->google_pixel->menu_devices;
}

sub cleanup {
    my ($self) = @_;
    $self->lock->cleanup;
    return;
}

sub run_action {
    my ($self, $action, @arguments) = @_;

    return $self->server->show_status
        if $action eq 'server-status';
    return $self->server->start_via_service
        if $action eq 'start-server';
    return $self->server->repair_via_service
        if $action eq 'repair-server';
    return $self->server->stop_via_service
        if $action eq 'stop-server';

    if ($action eq 'reconnect-usb') {
        my $status = $self->device->run_host(15, 'reconnect', 'device');
        print $self->device->capture_devices if $status == 0;
        return $status;
    }
    if ($action eq 'reconnect-offline') {
        my $status = $self->device->run_host(15, 'reconnect', 'offline');
        print $self->device->capture_devices if $status == 0;
        return $status;
    }
    if ($action eq 'wait-any-device') {
        $self->server->ensure_responsive;
        print 'Waiting up to '
            . $self->config->adb_wait_seconds
            . " seconds for an authorized device...\n";
        my $status = $self->command->run_signal(
            'TERM',
            3,
            $self->config->adb_wait_seconds,
            $self->config->require_tool('adb'),
            'wait-for-device',
        );
        if ($status != 0) {
            $self->server->repair if !$self->server->probe;
            fail('timed out waiting for an authorized Android device');
        }
        print $self->device->capture_devices;
        return 0;
    }
    if ($action eq 'list-devices') {
        print $self->device->capture_devices;
        return 0;
    }
    return $self->device->diagnostics
        if $action eq 'diagnose-devices';
    return $self->command->run(
        20,
        $self->config->require_tool('adb'),
        'version',
    ) if $action eq 'adb-version';
    if ($action eq 'host-features') {
        my $features = $self->device->capture_host(20, 'host-features');
        print join("\n", grep { $_ ne q{} } split /,/, $features), "\n";
        return 0;
    }
    return $self->device->run_host(20, 'mdns', 'services')
        if $action eq 'mdns-services';
    return $self->device->run_host(20, 'disconnect')
        if $action eq 'disconnect-all';
    return $self->device->run_host(60, 'pair', @arguments)
        if $action eq 'pair-wireless';
    return $self->device->run_host(30, 'connect', @arguments)
        if $action eq 'connect-wireless';
    return $self->device->run_host(20, 'disconnect', @arguments)
        if $action eq 'disconnect-wireless';

    return $self->device->device_summary($arguments[0])
        if $action eq 'device-summary';
    if ($action eq 'interactive-shell') {
        $self->device->wait_for_serial($arguments[0]);
        return $self->command->run_unbounded(
            $self->config->require_tool('adb'),
            '-s',
            $arguments[0],
            'shell',
        );
    }
    return $self->package->list_user_packages($arguments[0])
        if $action eq 'list-packages';
    return $self->package->current_activity($arguments[0])
        if $action eq 'current-activity';
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'shell',
        'dumpsys',
        'battery',
    ) if $action eq 'battery-status';
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'shell',
        'df',
        '-h',
    ) if $action eq 'storage-status';
    if ($action eq 'cpu-memory') {
        print "--- CPU ---\n";
        my $status = $self->device->run_serial(
            $self->config->adb_command_seconds,
            $arguments[0],
            'shell',
            'top',
            '-b',
            '-n',
            '1',
            '-m',
            '15',
        );
        return $status if $status != 0;
        print "\n--- Memory ---\n";
        return $self->device->run_serial(
            $self->config->adb_command_seconds,
            $arguments[0],
            'shell',
            'dumpsys',
            'meminfo',
        );
    }
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'shell',
        'pm',
        'list',
        'users',
    ) if $action eq 'list-android-users';

    return $self->transfer->screenshot($arguments[0])
        if $action eq 'screenshot';
    return $self->transfer->screenrecord($arguments[0])
        if $action eq 'screenrecord';
    if ($action eq 'logcat-live') {
        $self->device->wait_for_serial($arguments[0]);
        return $self->command->run_unbounded(
            $self->config->require_tool('adb'),
            '-s',
            $arguments[0],
            'logcat',
        );
    }
    return $self->device->run_serial(
        60,
        $arguments[0],
        'logcat',
        '-d',
        '-t',
        '500',
    ) if $action eq 'logcat-recent';
    return $self->transfer->bugreport($arguments[0])
        if $action eq 'bugreport';
    return $self->backup->backup($arguments[0])
        if $action eq 'backup-device';

    return $self->package->install($arguments[0], $arguments[1], 0)
        if $action eq 'install-apk';
    return $self->package->install($arguments[0], $arguments[1], 1)
        if $action eq 'install-apk-replace';
    return $self->package->uninstall($arguments[0], $arguments[1])
        if $action eq 'uninstall-package';
    return $self->package->clear_data($arguments[0], $arguments[1])
        if $action eq 'clear-app-data';
    return $self->permissions->grant($arguments[0], $arguments[1], $arguments[2])
        if $action eq 'grant-permission';
    return $self->transfer->pull_path($arguments[0], $arguments[1])
        if $action eq 'pull-path';
    return $self->transfer->push_download($arguments[0], $arguments[1])
        if $action eq 'push-download';

    if ($action eq 'list-forwards') {
        $self->device->wait_for_serial($arguments[0]);
        my $status = $self->device->run_serial(
            30,
            $arguments[0],
            'forward',
            '--list',
        );
        return $status if $status != 0;
        return $self->device->run_serial(
            30,
            $arguments[0],
            'reverse',
            '--list',
        );
    }
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'forward',
        "tcp:$arguments[1]",
        "tcp:$arguments[2]",
    ) if $action eq 'forward-tcp';
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'reverse',
        "tcp:$arguments[1]",
        "tcp:$arguments[2]",
    ) if $action eq 'reverse-tcp';

    if ($action eq 'enable-tcpip-5555') {
        my $status = $self->device->run_serial(
            $self->config->adb_command_seconds,
            $arguments[0],
            'tcpip',
            '5555',
        );
        if ($status == 0) {
            print "TCP/IP debugging is now listening on the device. Treat this as temporary and disable Wireless debugging when finished.\n";
        }
        return $status;
    }
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'reboot',
    ) if $action eq 'reboot-system';
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'reboot',
        'recovery',
    ) if $action eq 'reboot-recovery';
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'reboot',
        'bootloader',
    ) if $action eq 'reboot-bootloader';
    return $self->device->run_serial(
        $self->config->adb_command_seconds,
        $arguments[0],
        'reboot',
        'sideload',
    ) if $action eq 'reboot-sideload';

    return $self->samsung->download(
        $arguments[0],
        $arguments[1],
        $arguments[2],
    )
        if $action eq 'samsung-download-firmware';
    return $self->samsung->flash($arguments[0], $arguments[1], 'keep-data')
        if $action eq 'samsung-flash-keep-data';
    return $self->samsung->flash($arguments[0], $arguments[1], 'factory-reset')
        if $action eq 'samsung-flash-factory-reset';

    return $self->google_pixel->list_devices
        if $action eq 'fastboot-list';
    return $self->google_pixel->info($arguments[0])
        if $action eq 'fastboot-info';
    return $self->google_pixel->reboot($arguments[0], 0)
        if $action eq 'fastboot-reboot';
    return $self->google_pixel->reboot($arguments[0], 1)
        if $action eq 'fastboot-reboot-bootloader';

    fail('unsupported Android Debug Bridge action: ' . ($action // 'unset'));
}

sub run_service_action {
    my ($self, $action) = @_;
    return $self->server->run_foreground if $action eq 'run';
    return $self->server->wait_ready if $action eq 'ready';
    return $self->server->clear_marker if $action eq 'cleanup';
    # Old --service start/stop invocations are refused, not recursive unit jobs.
    fail("unsupported managed Android Debug Bridge service action: $action");
}

sub _build_command {
    my ($self) = @_;
    return AndroidADB::Command->new(config => $self->config);
}

sub _build_lock {
    my ($self) = @_;
    return AndroidADB::Lock->new(config => $self->config);
}

sub _build_storage {
    my ($self) = @_;
    return AndroidADB::Firmware::Storage->new(
        config  => $self->config,
        command => $self->command,
    );
}

sub _build_server {
    my ($self) = @_;
    return AndroidADB::ADB::Server->new(
        config  => $self->config,
        command => $self->command,
    );
}

sub _build_device {
    my ($self) = @_;
    return AndroidADB::ADB::Device->new(
        config  => $self->config,
        command => $self->command,
        server  => $self->server,
    );
}

sub _build_package {
    my ($self) = @_;
    return AndroidADB::ADB::Package->new(
        config => $self->config,
        device => $self->device,
    );
}

sub _build_permissions {
    my ($self) = @_;
    return AndroidADB::ADB::Permissions->new(
        config => $self->config,
        device => $self->device,
    );
}

sub _build_transfer {
    my ($self) = @_;
    return AndroidADB::ADB::Transfer->new(
        config  => $self->config,
        command => $self->command,
        device  => $self->device,
        lock    => $self->lock,
        storage => $self->storage,
    );
}

sub _build_backup {
    my ($self) = @_;
    return AndroidADB::ADB::Backup->new(
        config  => $self->config,
        command => $self->command,
        device  => $self->device,
        lock    => $self->lock,
        storage => $self->storage,
    );
}

sub _build_samsung {
    my ($self) = @_;
    my $archive = AndroidADB::Firmware::Archive->new(
        config  => $self->config,
        command => $self->command,
        storage => $self->storage,
    );
    return AndroidADB::Vendor::Samsung->new(
        config   => $self->config,
        command  => $self->command,
        device   => $self->device,
        lock     => $self->lock,
        storage  => $self->storage,
        archive  => $archive,
        manifest => AndroidADB::Firmware::Manifest->new(
            storage => $self->storage,
        ),
    );
}

sub _build_google_pixel {
    my ($self) = @_;
    return AndroidADB::Vendor::GooglePixel->new(
        config  => $self->config,
        command => $self->command,
    );
}

sub _build_notification {
    my ($self) = @_;
    return AndroidADB::Notification->new(
        config  => $self->config,
        command => $self->command,
    );
}

1;
