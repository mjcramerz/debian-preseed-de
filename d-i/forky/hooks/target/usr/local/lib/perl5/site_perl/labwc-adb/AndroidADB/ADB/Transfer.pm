package AndroidADB::ADB::Transfer;

use strict;
use warnings;

use File::Basename qw(basename);
use File::Spec;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Validation qw(
  fail
  require_value
  validate_local_file
  validate_remote_path
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

has storage => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has lock => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub screenshot {
    my ($self, $serial) = @_;
    validate_serial($serial);
    my $directory = $self->storage->prepare_output_directory('screenshots');
    my $path = File::Spec->catfile(
        $directory,
        $self->storage->output_timestamp . "-$serial-screenshot.png",
    );

    $self->device->wait_for_serial($serial);
    my $status = $self->command->run_to_file_signal(
        'TERM',
        5,
        60,
        $path,
        undef,
        $self->config->require_tool('adb'),
        '-s',
        $serial,
        'exec-out',
        'screencap',
        '-p',
    );
    if ($status != 0) {
        unlink $path if -e $path || -l $path;
        $self->_repair_after_capture_failure($serial);
        fail('Android screenshot capture failed');
    }
    $self->_require_nonempty_file($path, 'Android screenshot capture produced an empty file');
    chmod 0600, $path
        or fail("unable to protect Android screenshot: $!");
    print "Saved screenshot: $path\n";
    return 0;
}

sub screenrecord {
    my ($self, $serial) = @_;
    validate_serial($serial);
    my $directory = $self->storage->prepare_output_directory('recordings');
    my $timestamp = $self->storage->output_timestamp;
    my $remote_path = "/sdcard/Movies/managed-screenrecord-$timestamp.mp4";
    my $local_path = File::Spec->catfile(
        $directory,
        "$timestamp-$serial-screenrecord.mp4",
    );
    require_value(
        !-e $local_path && !-l $local_path,
        'managed Android screen recording destination already exists',
    );

    print "Recording device screen for 30 seconds...\n";
    my $status = $self->device->run_serial_signal(
        'INT',
        5,
        40,
        $serial,
        'shell',
        'screenrecord',
        '--time-limit',
        '30',
        $remote_path,
    );
    if ($status != 0) {
        $self->_repair_after_capture_failure($serial);
        fail('Android screen recording failed');
    }

    $status = $self->device->run_serial(
        $self->config->adb_transfer_seconds,
        $serial,
        'pull',
        $remote_path,
        $local_path,
    );
    $self->device->run_serial(
        $self->config->adb_command_seconds,
        $serial,
        'shell',
        'rm',
        '-f',
        $remote_path,
    );
    if ($status != 0) {
        unlink $local_path if -e $local_path || -l $local_path;
        fail('Android screen recording pull failed');
    }
    $self->_require_nonempty_file(
        $local_path,
        'Android screen recording pull produced an empty file',
    );
    chmod 0600, $local_path
        or fail("unable to protect Android screen recording: $!");
    print "Saved screen recording: $local_path\n";
    return 0;
}

sub bugreport {
    my ($self, $serial) = @_;
    validate_serial($serial);
    my $directory = $self->storage->prepare_output_directory('bugreports');
    my $path = File::Spec->catfile(
        $directory,
        $self->storage->output_timestamp . "-$serial-bugreport.zip",
    );
    require_value(
        !-e $path && !-l $path,
        'managed Android bugreport destination already exists',
    );

    my $status = $self->device->run_serial(
        $self->config->adb_transfer_seconds,
        $serial,
        'bugreport',
        $path,
    );
    $status == 0
        or fail('Android bugreport failed');
    $self->_require_nonempty_file(
        $path,
        'Android bugreport did not produce an output file',
    );
    chmod 0600, $path
        or fail("unable to protect Android bugreport: $!");
    print "Saved bugreport: $path\n";
    return 0;
}

sub pull_path {
    my ($self, $serial, $remote_path) = @_;
    validate_serial($serial);
    validate_remote_path($remote_path);
    my $directory = $self->storage->prepare_output_directory('pulls');
    my $label = $self->storage->output_timestamp . "-$serial";
    my $path = File::Spec->catdir(
        $directory,
        $label,
    );
    require_value(
        !-e $path && !-l $path,
        'managed Android pull destination already exists',
    );
    my $partial_path = $self->storage->create_partial_directory($directory, $label);
    $self->lock->register_partial_directory($partial_path);
    my $status = $self->device->run_serial(
        $self->config->adb_transfer_seconds,
        $serial,
        'pull',
        $remote_path,
        "$partial_path/",
    );
    $status == 0
        or fail('Android device path pull failed');
    $self->storage->secure_tree($partial_path);
    $self->storage->finalize_directory($partial_path, $path);
    $self->lock->complete_partial_directory($partial_path);
    print "Pulled device content into: $path\n";
    return 0;
}

sub push_download {
    my ($self, $serial, $file) = @_;
    validate_serial($serial);
    my $resolved = validate_local_file($file);
    my $basename = basename($resolved);
    require_value(
        (
            defined($basename)
                && $basename ne q{}
                && $basename ne q{.}
                && $basename ne q{..}
                && !!($basename !~ /[\r\n]/)
        ),
        'local file name is invalid for Android Download',
    );
    my $remote_path = "/sdcard/Download/$basename";
    my $status = $self->device->run_serial(
        $self->config->adb_transfer_seconds,
        $serial,
        'push',
        $resolved,
        $remote_path,
    );
    $status == 0
        or fail('Android Download push failed');
    print "Pushed file to: $remote_path\n";
    return 0;
}

sub _repair_after_capture_failure {
    my ($self, $serial) = @_;
    if (!$self->device->server->probe) {
        $self->device->server->repair;
    }
    eval { $self->device->explain_state($serial); 1 };
    return;
}

sub _require_nonempty_file {
    my ($self, $path, $message) = @_;
    require_value(
        -f $path && !-l $path && -s $path,
        $message,
    );
    return;
}

1;
