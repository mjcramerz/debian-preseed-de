package AndroidADB::Validation;

use strict;
use warnings;

use Cwd qw(abs_path);
use Exporter qw(import);
use File::Basename qw(basename);

our @EXPORT_OK = qw(
  fail
  require_value
  validate_action
  validate_endpoint
  validate_firmware_version
  validate_local_file
  validate_package_name
  validate_pairing_code
  validate_permission_name
  validate_port
  validate_remote_path
  validate_samsung_firmware_directory_syntax
  validate_samsung_model
  validate_samsung_region
  validate_serial
);

my $MAX_SERIAL_LENGTH             = 128;
my $MAX_ENDPOINT_LENGTH           = 255;
my $MAX_PACKAGE_LENGTH            = 255;
my $MAX_PERMISSION_LENGTH         = 255;
my $MAX_REMOTE_PATH_LENGTH        = 512;
my $MAX_FIRMWARE_DIRECTORY_LENGTH = 1024;
my $MAX_FIRMWARE_VERSION_LENGTH   = 255;
my $MAX_LOCAL_FILE_BYTES          = 8 * 1024 * 1024 * 1024;

my %NO_ARGUMENT_ACTIONS = map { $_ => 1 } qw(
  server-status
  start-server
  repair-server
  stop-server
  reconnect-usb
  reconnect-offline
  wait-any-device
  list-devices
  diagnose-devices
  adb-version
  host-features
  mdns-services
  disconnect-all
  fastboot-list
);

my %SERIAL_ACTIONS = map { $_ => 1 } qw(
  device-summary
  interactive-shell
  list-packages
  current-activity
  battery-status
  storage-status
  cpu-memory
  list-android-users
  screenshot
  screenrecord
  logcat-live
  logcat-recent
  bugreport
  list-forwards
);

sub fail {
    my ($message) = @_;
    $message = 'unknown Android Debug Bridge error'
        if !defined($message) || $message eq q{};
    die "$message\n";
}

sub require_value {
    @_ == 2
        or fail('internal Android Debug Bridge validation predicate is invalid');
    my ($condition, $message) = @_;
    return 1 if $condition;
    fail($message);
}

sub _require_scalar {
    my ($value, $message) = @_;
    require_value(defined($value) && !ref($value), $message);
    return $value;
}

sub _require_length_at_most {
    my ($value, $limit, $message) = @_;
    require_value(length($value) <= $limit, $message);
    return $value;
}

sub _require_no_newline {
    my ($value, $message) = @_;
    require_value(!!($value !~ /[\r\n]/), $message);
    return $value;
}

sub validate_serial {
    my ($serial) = @_;
    _require_scalar($serial, 'invalid Android device serial: unset');
    require_value(
        ($serial ne q{} && !!($serial =~ /\A[A-Za-z0-9._:-]+\z/)),
        'invalid Android device serial: ' . ($serial eq q{} ? 'unset' : $serial),
    );
    return _require_length_at_most(
        $serial,
        $MAX_SERIAL_LENGTH,
        'Android device serial is too long',
    );
}

sub validate_endpoint {
    my ($endpoint) = @_;
    _require_scalar($endpoint, 'invalid Android wireless endpoint: unset');
    require_value(
        ($endpoint ne q{} && !!($endpoint =~ /\A[A-Za-z0-9._:\[\]-]+\z/)),
        'invalid Android wireless endpoint: '
            . ($endpoint eq q{} ? 'unset' : $endpoint),
    );
    _require_length_at_most(
        $endpoint,
        $MAX_ENDPOINT_LENGTH,
        'Android wireless endpoint is too long',
    );
    require_value(
        index($endpoint, q{:}) >= 0,
        'Android wireless endpoint must include a port',
    );
    return $endpoint;
}

sub validate_pairing_code {
    my ($pairing_code) = @_;
    _require_scalar($pairing_code, 'wireless pairing code must contain six digits');
    require_value(
        !!($pairing_code =~ /\A[0-9]{6}\z/),
        'wireless pairing code must contain six digits',
    );
    return $pairing_code;
}

sub validate_port {
    my ($name, $port) = @_;
    _require_scalar($port, "$name must be a TCP port");
    require_value(!!($port =~ /\A[0-9]+\z/), "$name must be a TCP port");
    require_value(
        $port >= 1024 && $port <= 65535,
        "$name must be between 1024 and 65535",
    );
    return $port;
}

sub validate_package_name {
    my ($package_name) = @_;
    _require_scalar($package_name, 'invalid Android package name: unset');
    require_value(
        (
            $package_name ne q{}
            && !!($package_name !~ /\A\./)
            && !!($package_name !~ /\.\z/)
            && !!($package_name !~ /\.\./)
            && !!($package_name =~ /\A[A-Za-z0-9._]+\z/)
        ),
        'invalid Android package name: '
            . ($package_name eq q{} ? 'unset' : $package_name),
    );
    _require_length_at_most(
        $package_name,
        $MAX_PACKAGE_LENGTH,
        'Android package name is too long',
    );
    require_value(
        index($package_name, q{.}) >= 0,
        'Android package name must contain at least one dot',
    );
    return $package_name;
}

sub validate_permission_name {
    my ($permission_name) = @_;
    _require_scalar($permission_name, 'Android permission must start with android.permission.');
    require_value(
        !!($permission_name =~ /\Aandroid[.]permission[.]/),
        'Android permission must start with android.permission.',
    );
    require_value(
        !!($permission_name =~ /\A[A-Za-z0-9._]+\z/),
        'Android permission contains unsupported characters',
    );
    return _require_length_at_most(
        $permission_name,
        $MAX_PERMISSION_LENGTH,
        'Android permission name is too long',
    );
}

sub validate_remote_path {
    my ($remote_path) = @_;
    _require_scalar($remote_path, 'Android device path must be absolute');
    require_value(!!($remote_path =~ m{\A/}), 'Android device path must be absolute');
    _require_no_newline($remote_path, 'Android device path cannot contain newlines');
    return _require_length_at_most(
        $remote_path,
        $MAX_REMOTE_PATH_LENGTH,
        'Android device path is too long',
    );
}

sub validate_local_file {
    my ($requested_path) = @_;
    _require_scalar($requested_path, 'local file path must be absolute');
    require_value(!!($requested_path =~ m{\A/}), 'local file path must be absolute');
    _require_no_newline($requested_path, 'local file path cannot contain newlines');
    require_value(!-l $requested_path, 'local file symlinks are not allowed');

    my $resolved_path = abs_path($requested_path);
    require_value(
        defined($resolved_path),
        "unable to resolve local file: $requested_path",
    );
    require_value(-f $resolved_path, "local file does not exist: $resolved_path");

    my $size = -s $resolved_path;
    require_value(
        (defined($size) && !!($size =~ /\A[0-9]+\z/)),
        'unable to determine local file size',
    );
    require_value(
        $size <= $MAX_LOCAL_FILE_BYTES,
        'local file exceeds the managed 8 GiB transfer ceiling',
    );
    return $resolved_path;
}

sub validate_samsung_model {
    my ($model) = @_;
    _require_scalar(
        $model,
        'Samsung model must contain only uppercase letters, digits, and hyphens',
    );
    require_value(
        !!($model =~ /\A[A-Z0-9-]+\z/),
        'Samsung model must contain only uppercase letters, digits, and hyphens',
    );
    require_value(
        length($model) >= 4 && length($model) <= 32,
        'Samsung model must contain between 4 and 32 characters',
    );
    return $model;
}

sub validate_samsung_region {
    my ($region) = @_;
    _require_scalar(
        $region,
        'Samsung region CSC must contain only uppercase letters and digits',
    );
    require_value(
        !!($region =~ /\A[A-Z0-9]+\z/),
        'Samsung region CSC must contain only uppercase letters and digits',
    );
    require_value(
        length($region) >= 3 && length($region) <= 8,
        'Samsung region CSC must contain between 3 and 8 characters',
    );
    return $region;
}

sub validate_samsung_firmware_directory_syntax {
    my ($directory) = @_;
    _require_scalar($directory, 'Samsung firmware directory must be an absolute path');
    require_value(
        !!($directory =~ m{\A/}),
        'Samsung firmware directory must be an absolute path',
    );
    _require_no_newline(
        $directory,
        'Samsung firmware directory cannot contain newlines',
    );
    return _require_length_at_most(
        $directory,
        $MAX_FIRMWARE_DIRECTORY_LENGTH,
        'Samsung firmware directory is too long',
    );
}

sub validate_firmware_version {
    my ($version) = @_;
    _require_scalar($version, 'samloader returned an invalid Samsung firmware version');
    require_value(
        ($version ne q{} && !!($version =~ /\A[A-Za-z0-9._\/-]+\z/)),
        'samloader returned an invalid Samsung firmware version',
    );
    _require_length_at_most(
        $version,
        $MAX_FIRMWARE_VERSION_LENGTH,
        'samloader returned an overlong Samsung firmware version',
    );
    _require_no_newline(
        $version,
        'samloader returned more than one firmware version',
    );
    return $version;
}

sub validate_action {
    my ($action, @arguments) = @_;
    _require_scalar($action, 'unsupported Android Debug Bridge action: unset');

    if ($NO_ARGUMENT_ACTIONS{$action}) {
        require_value(
            @arguments == 0,
            "$action does not accept arguments",
        );
        return 1;
    }

    if ($SERIAL_ACTIONS{$action}) {
        require_value(
            @arguments == 1,
            "$action requires one device serial",
        );
        validate_serial($arguments[0]);
        return 1;
    }

    if ($action eq 'backup-device') {
        require_value(
            @arguments == 2,
            "$action requires serial and confirmation",
        );
        validate_serial($arguments[0]);
        require_value(
            $arguments[1] eq 'confirmed-adb-action',
            "$action requires the managed confirmation",
        );
        return 1;
    }

    if ($action =~ /\A(?:install-apk|install-apk-replace|push-download|pull-path)\z/) {
        require_value(
            @arguments == 2,
            "$action requires a device serial and path",
        );
        validate_serial($arguments[0]);
        if ($action eq 'pull-path') {
            validate_remote_path($arguments[1]);
        }
        else {
            validate_local_file($arguments[1]);
        }
        return 1;
    }

    if ($action =~ /\A(?:uninstall-package|clear-app-data)\z/) {
        require_value(
            @arguments == 3,
            "$action requires serial, package, and confirmation",
        );
        validate_serial($arguments[0]);
        validate_package_name($arguments[1]);
        require_value(
            $arguments[2] eq 'confirmed-adb-action',
            "$action requires the managed confirmation",
        );
        return 1;
    }

    if ($action eq 'grant-permission') {
        require_value(
            @arguments == 4,
            "$action requires serial, package, permission, and confirmation",
        );
        validate_serial($arguments[0]);
        validate_package_name($arguments[1]);
        validate_permission_name($arguments[2]);
        require_value(
            $arguments[3] eq 'confirmed-adb-action',
            "$action requires the managed confirmation",
        );
        return 1;
    }

    if ($action eq 'pair-wireless') {
        require_value(
            @arguments == 2,
            "$action requires endpoint and pairing code",
        );
        validate_endpoint($arguments[0]);
        validate_pairing_code($arguments[1]);
        return 1;
    }

    if ($action =~ /\A(?:connect-wireless|disconnect-wireless)\z/) {
        require_value(
            @arguments == 1,
            "$action requires one endpoint",
        );
        validate_endpoint($arguments[0]);
        return 1;
    }

    if ($action =~ /\A(?:forward-tcp|reverse-tcp)\z/) {
        require_value(
            @arguments == 3,
            "$action requires serial and two ports",
        );
        validate_serial($arguments[0]);
        validate_port('host TCP port', $arguments[1]);
        validate_port('device TCP port', $arguments[2]);
        return 1;
    }

    if ($action =~ /\A(?:reboot-system|reboot-recovery|reboot-bootloader|reboot-sideload|enable-tcpip-5555)\z/) {
        require_value(
            @arguments == 2,
            "$action requires serial and confirmation",
        );
        validate_serial($arguments[0]);
        require_value(
            $arguments[1] eq 'confirmed-adb-action',
            "$action requires the managed confirmation",
        );
        return 1;
    }

    if ($action eq 'samsung-download-firmware') {
        require_value(
            @arguments == 4,
            "$action requires serial, model, region, and confirmation",
        );
        validate_serial($arguments[0]);
        validate_samsung_model($arguments[1]);
        validate_samsung_region($arguments[2]);
        require_value(
            $arguments[3] eq 'confirmed-samsung-download',
            "$action requires the managed Samsung download confirmation",
        );
        return 1;
    }

    if ($action =~ /\A(?:samsung-flash-keep-data|samsung-flash-factory-reset)\z/) {
        require_value(
            @arguments == 3,
            "$action requires serial, firmware directory, and confirmation",
        );
        validate_serial($arguments[0]);
        validate_samsung_firmware_directory_syntax($arguments[1]);
        my $expected = $action eq 'samsung-flash-keep-data'
            ? 'confirmed-samsung-keep-data-flash'
            : 'confirmed-samsung-factory-reset';
        my $description = $action eq 'samsung-flash-keep-data'
            ? 'managed HOME_CSC confirmation'
            : 'managed factory-reset confirmation';
        require_value(
            $arguments[2] eq $expected,
            "$action requires the $description",
        );
        return 1;
    }

    if ($action eq 'fastboot-info') {
        require_value(
            @arguments == 1,
            "$action requires one fastboot serial",
        );
        validate_serial($arguments[0]);
        return 1;
    }

    if ($action =~ /\A(?:fastboot-reboot|fastboot-reboot-bootloader)\z/) {
        require_value(
            @arguments == 2,
            "$action requires serial and confirmation",
        );
        validate_serial($arguments[0]);
        require_value(
            $arguments[1] eq 'confirmed-adb-action',
            "$action requires the managed confirmation",
        );
        return 1;
    }

    fail('unsupported Android Debug Bridge action: ' . ($action eq q{} ? 'unset' : $action));
}

1;
