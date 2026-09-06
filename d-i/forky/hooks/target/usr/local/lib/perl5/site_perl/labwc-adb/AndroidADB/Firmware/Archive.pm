package AndroidADB::Firmware::Archive;

use strict;
use warnings;

use File::Basename qw(basename);
use File::Find qw(find);
use File::Spec;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Validation qw(fail require_value);

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

has storage => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub downloaded_archive {
    my ($self, $directory) = @_;
    require_value(
        -d $directory && !-l $directory,
        'managed Samsung firmware download directory is invalid',
    );
    my @archives;
    opendir my $handle, $directory
        or fail("unable to inspect Samsung firmware download directory: $!");
    while (my $entry = readdir $handle) {
        next if $entry eq q{.} || $entry eq q{..};
        next if $entry !~ /\.zip\z/;
        my $path = File::Spec->catfile($directory, $entry);
        push @archives, $path if -f $path && !-l $path;
    }
    closedir $handle;
    require_value(
        @archives == 1,
        'samloader download must produce exactly one decrypted firmware ZIP; found ' . scalar(@archives),
    );

    my $archive = $archives[0];
    my $size = $self->storage->file_size(
        $archive,
        'unable to determine downloaded Samsung firmware ZIP size',
    );
    require_value(
        $size >= $self->config->samsung_firmware_minimum_archive_bytes,
        "downloaded Samsung firmware ZIP is unexpectedly small: $size bytes",
    );
    require_value(
        $size <= $self->config->samsung_firmware_maximum_archive_bytes,
        "downloaded Samsung firmware ZIP exceeds the managed size ceiling: $size bytes",
    );
    $self->_safe_filename(
        basename($archive),
        'downloaded Samsung firmware ZIP has an unsafe file name',
    );
    return $archive;
}

sub extract {
    my ($self, $archive, $destination) = @_;
    $self->storage->require_regular_file(
        $archive,
        'downloaded Samsung firmware ZIP must not be a symlink',
    );
    $self->storage->create_directory($destination);
    my $status = $self->command->run_signal(
        'TERM',
        30,
        7_200,
        $self->config->require_tool(
            'samsung_extractor',
            'managed Samsung firmware extractor is not installed',
        ),
        $archive,
        $destination,
    );
    $status == 0
        or fail('official Samsung firmware ZIP extraction failed');
    return $destination;
}

sub find_single_component {
    my ($self, $root, $prefix, $label) = @_;
    require_value(
        (defined($prefix) && !!($prefix =~ /\A(?:BL|AP|CP|CSC|HOME_CSC)\z/)),
        'Samsung firmware component prefix is invalid',
    );
    require_value(
        -d $root && !-l $root,
        'Samsung firmware extraction directory is invalid',
    );

    my @matches;
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                return if !-f $File::Find::name || -l $File::Find::name;
                my $name = basename($File::Find::name);
                push @matches, $File::Find::name
                    if $name =~ /\A\Q$prefix\E_.*\.tar\.md5\z/;
            },
        },
        $root,
    );
    require_value(
        @matches == 1,
        "official firmware must contain exactly one $label package; found " . scalar(@matches),
    );
    return $matches[0];
}

sub move_component {
    my ($self, $source, $destination_directory) = @_;
    $self->storage->require_regular_file(
        $source,
        'official Samsung firmware component is invalid',
    );
    $self->storage->create_directory($destination_directory);
    my $name = basename($source);
    $self->_safe_filename(
        $name,
        'official Samsung firmware contains an unsafe component file name',
    );
    my $destination = File::Spec->catfile($destination_directory, $name);
    require_value(
        !-e $destination && !-l $destination,
        'official Samsung firmware component destination already exists',
    );
    rename($source, $destination)
        or fail("unable to move official Samsung firmware component: $!");
    return $destination;
}

sub verify_md5 {
    my ($self, @components) = @_;
    require_value(@components == 5, 'managed Samsung firmware component set is invalid');
    for my $component (@components) {
        $self->storage->require_regular_file(
            $component,
            'managed Samsung firmware component is invalid',
        );
    }
    my $status = $self->command->run_signal(
        'TERM',
        30,
        3_600,
        $self->config->require_tool(
            'samloader',
            'samloader-rs is not installed',
        ),
        'verify-md5',
        @components,
    );
    $status == 0
        or fail('official Samsung firmware package MD5 verification failed');
    return 1;
}

sub _safe_filename {
    my ($self, $name, $message) = @_;
    require_value(
        (
            defined($name)
                && $name ne q{}
                && $name ne q{.}
                && $name ne q{..}
                && !!($name =~ /\A[A-Za-z0-9._-]+\z/)
        ),
        $message,
    );
    return $name;
}

1;
