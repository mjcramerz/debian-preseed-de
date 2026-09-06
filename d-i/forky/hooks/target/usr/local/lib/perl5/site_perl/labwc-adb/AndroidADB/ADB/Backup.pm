package AndroidADB::ADB::Backup;

use strict;
use warnings;

use File::Spec;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Validation qw(fail require_value validate_serial);

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

has device => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has lock => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has storage => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub backup {
    my ($self, $serial) = @_;
    validate_serial($serial);

    my $lock_root = $self->storage->prepare_output_directory('.locks');
    $self->lock->acquire('backup', $lock_root);
    $self->device->wait_for_serial($serial);

    my $backup_root = $self->storage->prepare_output_directory('backups');
    $self->_preflight_space($serial, $backup_root);
    my $timestamp = $self->storage->output_timestamp;
    my $final_path = File::Spec->catdir($backup_root, "$timestamp-$serial");
    require_value(
        !-e $final_path && !-l $final_path,
        'managed backup destination already exists',
    );
    my $partial_path = $self->storage->create_partial_directory(
        $backup_root,
        "$timestamp-$serial",
    );
    $self->lock->register_partial_directory($partial_path);
    my $shared_storage = File::Spec->catdir($partial_path, 'shared-storage');
    $self->storage->create_directory($shared_storage);

    $self->storage->write_text(
        File::Spec->catfile($partial_path, 'README.txt'),
        <<'README',
This is a best-effort Android Debug Bridge backup.

It includes shared storage, device and package metadata, a bugreport when the
device permits one, and a legacy Android Backup archive when both the installed
ADB client and the device support that deprecated protocol. Production Android
security does not permit ADB to copy every app's private data, hardware-backed
keys, or protected system partitions. An unlocked device confirmation may be
required while the backup is running.
README
    );

    $self->_write_serial_capture(
        File::Spec->catfile($partial_path, 'device-summary.txt'),
        sub { $self->device->device_summary($serial) },
        1,
    );
    $self->_write_serial_capture(
        File::Spec->catfile($partial_path, 'properties.txt'),
        sub {
            $self->device->capture_serial(
                $self->config->adb_command_seconds,
                $serial,
                'shell',
                'getprop',
            );
        },
        0,
    );
    $self->_write_serial_capture(
        File::Spec->catfile($partial_path, 'packages.txt'),
        sub {
            $self->device->capture_serial(
                $self->config->adb_command_seconds,
                $serial,
                'shell',
                'pm',
                'list',
                'packages',
                '-f',
                '-U',
                '-u',
            );
        },
        0,
    );
    $self->_write_serial_capture(
        File::Spec->catfile($partial_path, 'android-users.txt'),
        sub {
            $self->device->capture_serial(
                $self->config->adb_command_seconds,
                $serial,
                'shell',
                'pm',
                'list',
                'users',
            );
        },
        0,
    );
    $self->_write_serial_capture(
        File::Spec->catfile($partial_path, 'device-filesystems.txt'),
        sub {
            $self->device->capture_serial(
                $self->config->adb_command_seconds,
                $serial,
                'shell',
                'df',
                '-k',
            );
        },
        0,
    );

    my $global_settings = $self->_capture_settings(
        $partial_path,
        $serial,
        'global',
    );
    $self->_capture_settings($partial_path, $serial, 'system');
    $self->_capture_settings($partial_path, $serial, 'secure');

    print "Copying all ADB-readable shared storage. This can take several hours.\n";
    _require_success(
        $self->device->run_serial(
            $self->config->adb_backup_seconds,
            $serial,
            'pull',
            '/sdcard/',
            "$shared_storage/",
        ),
        'Android shared-storage backup failed',
    );

    my $legacy_status = $self->_legacy_backup($partial_path, $serial);
    my $bugreport_status = $self->_backup_bugreport($partial_path, $serial);
    $self->storage->write_text(
        File::Spec->catfile($partial_path, 'backup-status.txt'),
        join(
            q{},
            "format=managed-adb-backup-v1\n",
            "serial=$serial\n",
            "completed_at=$timestamp\n",
            "shared_storage=created\n",
            "legacy_android_backup=$legacy_status\n",
            "bugreport=$bugreport_status\n",
            'global_settings=' . ($global_settings ? 'available' : 'unavailable') . "\n",
        ),
    );

    $self->_write_checksums($partial_path);
    $self->storage->secure_tree($partial_path);
    $self->storage->finalize_directory($partial_path, $final_path);
    $self->lock->complete_partial_directory($partial_path);
    print "Completed best-effort device backup: $final_path\n";
    print "Legacy Android Backup: $legacy_status; bugreport: $bugreport_status.\n";
    return 0;
}

sub _preflight_space {
    my ($self, $serial, $backup_root) = @_;
    my $device_df;
    eval {
        $device_df = $self->device->capture_serial(
            30,
            $serial,
            'shell',
            'df',
            '-k',
            '/sdcard',
        );
        1;
    };

    my $device_used;
    if (defined($device_df)) {
        for my $line (split /\n/, $device_df) {
            my @fields = split /\s+/, $line;
            $device_used = $fields[2]
                if @fields >= 3 && defined($fields[2]) && $fields[2] =~ /\A[0-9]+\z/;
        }
    }
    my $available = eval { $self->storage->available_kib($backup_root) };
    if (
        !defined($device_used)
            || !defined($available)
            || $device_used !~ /\A[0-9]+\z/
            || $available !~ /\A[0-9]+\z/
    ) {
        print STDERR "Warning: unable to compare device usage with host free space; the backup may fail if storage is exhausted.\n";
        return;
    }
    my $required = $device_used + $self->config->adb_backup_headroom_kib;
    require_value(
        $available >= $required,
        "backup requires at least $required KiB free, but only $available KiB is available",
    );
    print "Backup storage preflight: device-shared-used=$device_used KiB host-available=$available KiB.\n";
    return;
}

sub _write_serial_capture {
    my ($self, $path, $capture, $returns_status) = @_;
    my $content;
    {
        local *STDOUT;
        open STDOUT, '>', \$content
            or fail('unable to capture managed Android backup metadata');
        my $result = $capture->();
        if ($returns_status) {
            _require_success($result, 'Android backup metadata collection failed');
        }
        elsif (defined($result)) {
            print $result;
        }
    }
    $content //= q{};
    $self->storage->write_text($path, $content);
    return;
}

sub _capture_settings {
    my ($self, $partial_path, $serial, $scope) = @_;
    my $output_path = File::Spec->catfile($partial_path, "settings-$scope.txt");
    my $error_path  = File::Spec->catfile($partial_path, "settings-$scope.error");
    $self->device->wait_for_serial($serial);
    my $status = $self->command->run_to_file(
        $self->config->adb_command_seconds,
        $output_path,
        $error_path,
        $self->config->require_tool('adb'),
        '-s',
        $serial,
        'shell',
        'settings',
        'list',
        $scope,
    );
    if ($status == 0) {
        unlink $error_path if -e $error_path || -l $error_path;
        return $scope eq 'global' ? 1 : 0;
    }
    return 0;
}

sub _legacy_backup {
    my ($self, $partial_path, $serial) = @_;
    my $help = $self->command->capture(
        20,
        $self->config->require_tool('adb'),
        'help',
    );
    return 'unsupported'
        if $help->{status} != 0
            || $help->{stdout} !~ /(?:^|\s)backup(?:\s|$)/m;

    print "Starting the legacy Android Backup layer. Unlock the device and approve the on-device backup prompt if one appears.\n";
    my $path = File::Spec->catfile($partial_path, 'android-backup.ab');
    my $status = $self->device->run_serial(
        $self->config->adb_backup_seconds,
        $serial,
        'backup',
        '-f',
        $path,
        '-apk',
        '-obb',
        '-noshared',
        '-all',
        '-system',
    );
    if ($status != 0) {
        unlink $path if -e $path || -l $path;
        return 'failed';
    }
    return 'created' if -f $path && !-l $path && -s $path > 24;
    unlink $path if -e $path || -l $path;
    return 'empty';
}

sub _backup_bugreport {
    my ($self, $partial_path, $serial) = @_;
    my $path = File::Spec->catfile($partial_path, 'bugreport.zip');
    my $status = $self->device->run_serial(
        $self->config->adb_backup_seconds,
        $serial,
        'bugreport',
        $path,
    );
    return 'created' if $status == 0 && -f $path && !-l $path && -s $path;
    unlink $path if -e $path || -l $path;
    return $status == 0 ? 'empty' : 'failed';
}

sub _write_checksums {
    my ($self, $partial_path) = @_;
    my @names = qw(
      README.txt
      android-users.txt
      backup-status.txt
      bugreport.zip
      device-filesystems.txt
      device-summary.txt
      packages.txt
      properties.txt
      android-backup.ab
      settings-global.txt
      settings-secure.txt
      settings-system.txt
    );
    my @lines;
    for my $name (@names) {
        my $path = File::Spec->catfile($partial_path, $name);
        next if !-f $path || -l $path;
        push @lines, $self->storage->file_sha256($path) . "  $name\n";
    }
    $self->storage->write_text(
        File::Spec->catfile($partial_path, 'SHA256SUMS'),
        join(q{}, @lines),
    );
    return;
}

sub _require_success {
    my ($status, $message) = @_;
    return if $status == 0;
    fail($message);
}

1;
