package AndroidADB::Vendor::Samsung;

use strict;
use warnings;

use Cwd qw(abs_path);
use File::Basename qw(basename);
use File::Path qw(remove_tree);
use File::Spec;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Firmware::Validation qw(
  validate_component_relative_path
  validate_manifest_hash
  validate_manifest_version
);
use AndroidADB::Validation qw(
  fail
  require_value
  validate_samsung_firmware_directory_syntax
  validate_samsung_model
  validate_samsung_region
  validate_serial
);

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

has archive => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has manifest => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub download {
    my ($self, $serial, $model, $region) = @_;
    validate_serial($serial);
    validate_samsung_model($model);
    validate_samsung_region($region);
    $self->config->require_tool('samloader', 'samloader-rs is not installed');
    $self->config->require_tool(
        'samsung_extractor',
        'managed Samsung firmware extractor is not installed',
    );

    my $lock_root = $self->storage->prepare_output_directory('.locks');
    $self->lock->acquire('samsung-firmware-download', $lock_root);
    $self->device->wait_for_serial($serial);

    my $device_model = _trim(
        $self->device->capture_serial(
            30,
            $serial,
            'shell',
            'getprop',
            'ro.product.model',
        ),
    );
    require_value(
        $device_model eq $model,
        'connected device model '
            . ($device_model eq q{} ? 'unknown' : $device_model)
            . " does not match requested firmware model $model",
    );

    my $firmware_root = $self->storage->prepare_output_directory('samsung-firmware');
    my $available_kib = $self->storage->available_kib($firmware_root);
    require_value(
        $available_kib >= $self->config->samsung_download_minimum_free_kib,
        'Samsung firmware download requires at least '
            . $self->config->samsung_download_minimum_free_kib
            . " KiB free, but only $available_kib KiB is available",
    );

    my $timestamp = $self->storage->output_timestamp;
    my $label = "$model-$region-$timestamp";
    my $final_path = File::Spec->catdir($firmware_root, $label);
    require_value(
        !-e $final_path && !-l $final_path,
        'managed Samsung firmware destination already exists',
    );
    my $partial_path = $self->storage->create_partial_directory(
        $firmware_root,
        $label,
    );
    $self->lock->register_partial_directory($partial_path);

    print "Checking latest official firmware for $model/$region.\n";
    my $check = $self->command->capture_signal(
        'TERM',
        10,
        120,
        $self->config->require_tool('samloader'),
        '--usb-backend',
        'libusb',
        'check-update',
        '-m',
        $model,
        '-r',
        $region,
    );
    $check->{status} == 0
        or fail('samloader could not resolve the latest official Samsung firmware');
    my $version = _trim($check->{stdout});
    validate_manifest_version($version);

    print "Downloading and decrypting official Samsung firmware version $version.\n";
    my $status = $self->command->run_signal(
        'TERM',
        30,
        $self->config->samsung_download_seconds,
        $self->config->require_tool('samloader'),
        '--verbose',
        '--usb-backend',
        'libusb',
        'download',
        '-m',
        $model,
        '-r',
        $region,
        '-v',
        $version,
        '-j',
        '4',
        '-d',
        $partial_path,
    );
    $status == 0
        or fail('official Samsung firmware download failed');

    my $archive = $self->archive->downloaded_archive($partial_path);
    my $extract_path = File::Spec->catdir($partial_path, 'extract');
    my $files_path = File::Spec->catdir($partial_path, 'files');
    $self->storage->create_directory($extract_path);
    $self->storage->create_directory($files_path);
    $self->archive->extract($archive, $extract_path);

    my %components;
    for my $spec (
        [ bl       => 'BL',       'BL' ],
        [ ap       => 'AP',       'AP' ],
        [ cp       => 'CP',       'CP' ],
        [ csc      => 'CSC',      'CSC' ],
        [ home_csc => 'HOME_CSC', 'HOME_CSC' ],
    ) {
        my ($key, $prefix, $label_name) = @{$spec};
        my $source = $self->archive->find_single_component(
            $extract_path,
            $prefix,
            $label_name,
        );
        $components{$key} = $self->archive->move_component($source, $files_path);
    }
    remove_tree($extract_path, { safe => 1 });

    $self->archive->verify_md5(
        @components{qw(bl ap cp csc home_csc)},
    );
    my %manifest = (
        format            => $self->config->samsung_firmware_format,
        samloader_version => '2.0.0',
        model             => $model,
        region            => $region,
        firmware_version  => $version,
        downloaded_at     => $timestamp,
        archive_file      => basename($archive),
        archive_sha256    => $self->storage->file_sha256($archive),
    );
    for my $spec (
        [ bl       => 'bl' ],
        [ ap       => 'ap' ],
        [ cp       => 'cp' ],
        [ csc      => 'csc' ],
        [ home_csc => 'home_csc' ],
    ) {
        my ($component_key, $manifest_key) = @{$spec};
        my $path = $components{$component_key};
        $manifest{"${manifest_key}_file"} = 'files/' . basename($path);
        $manifest{"${manifest_key}_sha256"} = $self->storage->file_sha256($path);
    }
    $self->manifest->write(
        File::Spec->catfile($partial_path, '.managed-firmware'),
        \%manifest,
    );

    $self->storage->secure_tree($partial_path);
    $self->storage->finalize_directory($partial_path, $final_path);
    $self->lock->complete_partial_directory($partial_path);
    print "Downloaded and verified official Samsung firmware: $final_path\n";
    return 0;
}

sub flash {
    my ($self, $serial, $requested_directory, $mode) = @_;
    validate_serial($serial);
    $mode =~ /\A(?:keep-data|factory-reset)\z/
        or fail('unsupported Samsung firmware flash mode');

    my $lock_root = $self->storage->prepare_output_directory('.locks');
    $self->lock->acquire('samsung-firmware-flash', $lock_root);
    $self->device->wait_for_serial($serial);
    my $firmware = $self->load_managed_firmware($requested_directory);

    my $device_model = _trim(
        $self->device->capture_serial(
            30,
            $serial,
            'shell',
            'getprop',
            'ro.product.model',
        ),
    );
    require_value(
        $device_model eq $firmware->{model},
        'connected device model '
            . ($device_model eq q{} ? 'unknown' : $device_model)
            . ' does not match firmware model '
            . $firmware->{model},
    );

    my ($csc_path, $label) = $mode eq 'keep-data'
        ? ($firmware->{home_csc}, 'HOME_CSC')
        : ($firmware->{csc}, 'CSC');
    my $log_root = $self->storage->prepare_output_directory('samsung-flash-logs');
    my $log_path = File::Spec->catfile(
        $log_root,
        $self->storage->output_timestamp . "-$serial-$mode.txt",
    );
    $self->storage->write_text(
        $log_path,
        join(
            q{},
            'model=' . $firmware->{model} . "\n",
            'region=' . $firmware->{region} . "\n",
            "mode=$mode\n",
            'csc_package=' . basename($csc_path) . "\n",
        ),
    );

    print "Rebooting selected Samsung device $serial into Download Mode.\n";
    my $status = $self->device->run_serial(
        $self->config->adb_command_seconds,
        $serial,
        'reboot',
        'download',
    );
    $status == 0
        or fail('unable to reboot selected Samsung device into Download Mode');
    $self->_wait_for_single_download_device;

    print "Flashing official Samsung firmware with $label. Do not disconnect USB or power.\n";
    $status = $self->command->run_signal(
        'TERM',
        60,
        $self->config->samsung_flash_seconds,
        $self->config->require_tool(
            'samloader',
            'samloader-rs is not installed',
        ),
        '--verbose',
        '--usb-backend',
        'libusb',
        'flash',
        '--wait',
        '-b',
        $firmware->{bl},
        '-a',
        $firmware->{ap},
        '-c',
        $firmware->{cp},
        '-s',
        $csc_path,
    );
    if ($status == 0) {
        $self->storage->append_text($log_path, "result=success\n");
        print "Samsung firmware flash completed successfully and samloader requested a reboot.\n";
    }
    else {
        $self->storage->append_text($log_path, "result=failure\nstatus=$status\n");
        fail(
            "Samsung firmware flash failed with status $status; keep the device connected and inspect the terminal output plus $log_path",
        );
    }
    print "Flash log: $log_path\n";
    return 0;
}

sub load_managed_firmware {
    my ($self, $requested_directory) = @_;
    validate_samsung_firmware_directory_syntax($requested_directory);
    require_value(!-l $requested_directory, 'Samsung firmware directory symlinks are not allowed');
    my $directory = abs_path($requested_directory);
    require_value(defined($directory) && -d $directory, 'Samsung firmware directory does not exist');

    my $firmware_root = $self->storage->prepare_output_directory('samsung-firmware');
    $firmware_root = abs_path($firmware_root);
    defined($firmware_root)
        or fail('unable to resolve managed Samsung firmware root');
    require_value(
        index($directory, "$firmware_root/") == 0,
        "Samsung firmware must be selected from the managed firmware root: $firmware_root",
    );

    my $manifest_path = File::Spec->catfile($directory, '.managed-firmware');
    my $manifest = $self->manifest->read($manifest_path);
    require_value(
        $self->manifest->value($manifest, 'format')
            eq $self->config->samsung_firmware_format,
        'Samsung firmware manifest format is unsupported',
    );
    require_value(
        $self->manifest->value($manifest, 'samloader_version') eq '2.0.0',
        'Samsung firmware was not downloaded by samloader-rs 2.0.0',
    );

    my $model = $self->manifest->value($manifest, 'model');
    my $region = $self->manifest->value($manifest, 'region');
    validate_samsung_model($model);
    validate_samsung_region($region);
    validate_manifest_version($self->manifest->value($manifest, 'firmware_version'));

    my %firmware = (
        directory => $directory,
        model     => $model,
        region    => $region,
    );
    for my $spec (
        [ bl       => 'bl_file',       'bl_sha256',       'BL' ],
        [ ap       => 'ap_file',       'ap_sha256',       'AP' ],
        [ cp       => 'cp_file',       'cp_sha256',       'CP' ],
        [ csc      => 'csc_file',      'csc_sha256',      'CSC' ],
        [ home_csc => 'home_csc_file', 'home_csc_sha256', 'HOME_CSC' ],
    ) {
        my ($target_key, $file_key, $hash_key, $prefix) = @{$spec};
        my $relative_path = validate_component_relative_path(
            $self->manifest->value($manifest, $file_key),
            $prefix,
            $file_key,
        );
        my $path = File::Spec->catfile($directory, split m{/}, $relative_path);
        $self->storage->require_regular_file(
            $path,
            "managed Samsung firmware component is missing: $relative_path",
        );
        my $expected = validate_manifest_hash(
            $self->manifest->value($manifest, $hash_key),
            $hash_key,
        );
        my $actual = $self->storage->file_sha256($path);
        require_value(
            $actual eq $expected,
            "managed Samsung firmware component SHA-256 changed: $relative_path",
        );
        $firmware{$target_key} = $path;
    }

    $self->archive->verify_md5(
        @firmware{qw(bl ap cp csc home_csc)},
    );
    return \%firmware;
}

sub _wait_for_single_download_device {
    my ($self) = @_;
    print 'Waiting up to '
        . $self->config->samsung_download_wait_seconds
        . " seconds for Samsung Download Mode.\n";
    my $status = $self->command->run_signal(
        'TERM',
        5,
        $self->config->samsung_download_wait_seconds,
        $self->config->require_tool(
            'samloader',
            'samloader-rs is not installed',
        ),
        '--usb-backend',
        'libusb',
        'detect',
        '--wait',
    );
    $status == 0
        or fail('samloader did not detect a supported Samsung Download Mode device');

    my $count = $self->_count_download_devices;
    require_value(
        $count == 1,
        "exactly one supported Samsung Download Mode device is required; found $count",
    );
    return;
}

sub _count_download_devices {
    my ($self) = @_;
    my $root = '/sys/bus/usb/devices';
    opendir my $directory, $root
        or fail("unable to inspect USB devices for Samsung Download Mode: $!");
    my $count = 0;
    while (my $entry = readdir $directory) {
        next if $entry eq q{.} || $entry eq q{..};
        my $base = File::Spec->catdir($root, $entry);
        my $vendor_path = File::Spec->catfile($base, 'idVendor');
        my $product_path = File::Spec->catfile($base, 'idProduct');
        next if !-r $vendor_path || !-r $product_path;
        my $vendor = _read_trimmed($vendor_path);
        next if !defined($vendor) || lc($vendor) ne '04e8';
        my $product = _read_trimmed($product_path);
        ++$count if defined($product) && lc($product) =~ /\A(?:6601|685d|68c3)\z/;
    }
    closedir $directory;
    return $count;
}

sub _read_trimmed {
    my ($path) = @_;
    open my $file, '<', $path or return undef;
    my $value = <$file>;
    close $file;
    return undef if !defined($value);
    return _trim($value);
}

sub _trim {
    my ($value) = @_;
    $value //= q{};
    $value =~ s/\r//g;
    $value =~ s/\A\s+//;
    $value =~ s/\s+\z//;
    return $value;
}

1;
