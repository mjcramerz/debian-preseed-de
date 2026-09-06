package AndroidADB::Firmware::Storage;

use strict;
use warnings;

use Digest::SHA;
use Fcntl qw(O_APPEND O_CREAT O_EXCL O_NOFOLLOW O_RDONLY O_WRONLY);
use File::Find qw(find);
use File::Spec;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(strftime);
use Types::Standard qw(Object Str);

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

sub output_timestamp {
    return strftime('%Y%m%dT%H%M%SZ', gmtime());
}

sub prepare_output_directory {
    my ($self, $name) = @_;
    require_value(
        (
            defined($name)
                && !ref($name)
                && !!($name =~ /\A[.A-Za-z0-9_-]+\z/)
                && !!($name !~ /\.\./)
        ),
        'managed Android output directory name is invalid',
    );

    my $output_root = $self->config->output_root;
    my $home = $self->config->home;
    require_value(-d $home, 'HOME directory is unavailable for managed Android output');
    my $android_root = File::Spec->catdir($home, 'Android');
    require_value(!-l $android_root, 'managed Android output root symlinks are not allowed');
    $self->_ensure_directory($android_root);
    require_value(!-l $output_root, 'managed Android output root symlinks are not allowed');
    $self->_ensure_directory($output_root);

    my $directory = File::Spec->catdir($output_root, $name);
    require_value(!-l $directory, 'managed Android output directory symlinks are not allowed');
    $self->_ensure_directory($directory);
    return $directory;
}

sub create_partial_directory {
    my ($self, $parent, $label) = @_;
    $self->_require_managed_directory($parent);
    require_value(
        (
            defined($label)
                && !!($label =~ /\A[A-Za-z0-9._-]+\z/)
                && !!($label !~ /\.\./)
        ),
        'managed Android partial directory label is invalid',
    );
    my $path = File::Spec->catdir(
        $parent,
        q{.} . $label . q{.partial.} . $$,
    );
    require_value(
        !-e $path && !-l $path,
        'managed Android partial destination already exists',
    );
    mkdir($path, 0700)
        or fail("unable to create managed Android partial directory: $!");
    return $path;
}

sub create_directory {
    my ($self, $path) = @_;
    $self->_require_managed_path($path);
    require_value(!-l $path, 'managed Android output directory symlinks are not allowed');
    $self->_ensure_directory($path);
    return $path;
}

sub finalize_directory {
    my ($self, $partial_path, $final_path) = @_;
    $self->_require_managed_directory($partial_path);
    $self->_require_managed_path($final_path);
    require_value(
        !-e $final_path && !-l $final_path,
        'managed Android output destination already exists',
    );
    $self->secure_tree($partial_path);
    rename($partial_path, $final_path)
        or fail("unable to finalize managed Android output: $!");
    return $final_path;
}

sub write_text {
    my ($self, $path, $content) = @_;
    $self->_require_managed_path($path);
    require_value(
        defined($content) && !ref($content),
        'managed Android output content is invalid',
    );
    require_value(!-e $path && !-l $path, 'managed Android output file already exists');

    my $flags = O_WRONLY | O_CREAT | O_EXCL;
    $flags |= O_NOFOLLOW if O_NOFOLLOW;
    sysopen my $file, $path, $flags, 0600
        or fail("unable to create managed Android output file: $!");
    _write_all($file, $content);
    close $file or fail("unable to close managed Android output file: $!");
    chmod 0600, $path
        or fail("unable to protect managed Android output file: $!");
    return $path;
}

sub append_text {
    my ($self, $path, $content) = @_;
    $self->_require_managed_path($path);
    require_value(
        -f $path && !-l $path,
        'managed Android output file is invalid',
    );
    require_value(
        defined($content) && !ref($content),
        'managed Android output content is invalid',
    );

    my $flags = O_WRONLY | O_APPEND;
    $flags |= O_NOFOLLOW if O_NOFOLLOW;
    sysopen my $file, $path, $flags
        or fail("unable to append managed Android output file: $!");
    _write_all($file, $content);
    close $file or fail("unable to close managed Android output file: $!");
    return $path;
}

sub file_sha256 {
    my ($self, $path) = @_;
    $self->_require_managed_path($path);
    require_value(
        -f $path && !-l $path,
        'managed Android file is not a regular non-symlink file',
    );

    my $flags = O_RDONLY;
    $flags |= O_NOFOLLOW if O_NOFOLLOW;
    sysopen my $file, $path, $flags
        or fail("unable to read managed Android file: $!");
    binmode $file;

    my $digest = Digest::SHA->new(256);
    while (1) {
        my $bytes_read = read($file, my $chunk, 1_048_576);
        defined($bytes_read) or fail("unable to hash managed Android file: $!");
        last if $bytes_read == 0;
        $digest->add($chunk);
    }
    close $file or fail("unable to close managed Android file: $!");
    return $digest->hexdigest;
}

sub available_kib {
    my ($self, $path) = @_;
    $self->_require_managed_directory($path);
    my $result = $self->command->capture(
        20,
        $self->config->require_tool('df'),
        '-Pk',
        $path,
    );
    require_value(
        $result->{status} == 0,
        'unable to determine free space for the managed Samsung firmware root',
    );
    my @lines = grep { $_ ne q{} } split /\n/, $result->{stdout};
    require_value(
        @lines >= 2,
        'unable to determine free space for the managed Samsung firmware root',
    );
    my @fields = split /\s+/, $lines[1];
    my $available = $fields[3];
    require_value(
        (defined($available) && !!($available =~ /\A[0-9]+\z/)),
        'unable to determine free space for the managed Samsung firmware root',
    );
    return int($available);
}

sub secure_tree {
    my ($self, $root) = @_;
    $self->_require_managed_directory($root);
    my $failure;
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                return if defined($failure);
                my $path = $File::Find::name;
                my @stat = lstat($path);
                if (!@stat) {
                    $failure = "unable to inspect managed Android output: $!";
                    return;
                }
                if (-l _) {
                    $failure = 'managed Android output contains a symlink';
                    return;
                }
                if (-d _) {
                    chmod 0700, $path
                        or $failure = "unable to protect managed Android directory: $!";
                    return;
                }
                if (-f _) {
                    chmod 0600, $path
                        or $failure = "unable to protect managed Android file: $!";
                    return;
                }
                $failure = 'managed Android output contains an unsupported filesystem node';
            },
        },
        $root,
    );
    fail($failure) if defined($failure);
    return;
}

sub require_regular_file {
    my ($self, $path, $message) = @_;
    $self->_require_managed_path($path);
    require_value(
        -f $path && !-l $path,
        $message // 'managed Android file is not a regular non-symlink file',
    );
    return $path;
}

sub file_size {
    my ($self, $path, $message) = @_;
    $self->require_regular_file($path, $message);
    my $size = -s $path;
    require_value(
        (defined($size) && !!($size =~ /\A[0-9]+\z/)),
        $message // 'unable to determine managed Android file size',
    );
    return $size;
}

sub _ensure_directory {
    my ($self, $path) = @_;
    if (-e $path) {
        require_value(
            -d $path && !-l $path,
            'managed Android output path is not a regular directory',
        );
    }
    else {
        mkdir($path, 0700)
            or fail("unable to create managed Android output directory: $!");
    }
    chmod 0700, $path
        or fail("unable to protect managed Android output directory: $!");
    return;
}

sub _require_managed_directory {
    my ($self, $path) = @_;
    $self->_require_managed_path($path);
    require_value(
        -d $path && !-l $path,
        'managed Android output directory is invalid',
    );
    return;
}

sub _require_managed_path {
    my ($self, $path) = @_;
    require_value(
        (
            defined($path)
                && !ref($path)
                && !!($path =~ m{\A/})
                && !!($path !~ /[\r\n]/)
                && !!($path !~ m{(?:\A|/)[.]{1,2}(?:/|\z)})
                && index($path, '//') < 0
        ),
        'managed Android output path is invalid',
    );
    my $root = $self->config->output_root;
    require_value(
        $path eq $root || index($path, "$root/") == 0,
        'managed Android output path escapes the output root',
    );
    return;
}

sub _write_all {
    my ($file, $content) = @_;
    my $offset = 0;
    while ($offset < length($content)) {
        my $written = syswrite($file, $content, length($content) - $offset, $offset);
        defined($written) or fail("unable to write managed Android output file: $!");
        $offset += $written;
    }
    return;
}

1;
