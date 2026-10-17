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
        'nusb',
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
        'nusb',
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
        samloader_version => '2.2.0',
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
        File::Spec->catfile($partial_path, '.firmware'),
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

    # The packaged nusb flash interface does not bind the selected ADB serial
    # or physical USB attachment. A single detected device is not that proof.
    # Refuse before reboot or any other mutation until a bound transport exists.
    print STDERR 'unavailable: automated Samsung flashing cannot bind the selected '
        . "device across Download Mode; no device was rebooted or flashed\n";
    return 69; # EX_UNAVAILABLE, distinct from a failed or cancelled flash.
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

    my $manifest_path = File::Spec->catfile($directory, '.firmware');
    my $manifest = $self->manifest->read($manifest_path);
    require_value(
        $self->manifest->value($manifest, 'format')
            eq $self->config->samsung_firmware_format,
        'Samsung firmware manifest format is unsupported',
    );
    my $download_version = $self->manifest->value($manifest, 'samloader_version');
    require_value(
        $download_version eq '2.0.0' || $download_version eq '2.2.0',
        'Samsung firmware has an unsupported samloader-rs download version',
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

sub _trim {
    my ($value) = @_;
    $value //= q{};
    $value =~ s/\r//g;
    $value =~ s/\A\s+//;
    $value =~ s/\s+\z//;
    return $value;
}

1;
