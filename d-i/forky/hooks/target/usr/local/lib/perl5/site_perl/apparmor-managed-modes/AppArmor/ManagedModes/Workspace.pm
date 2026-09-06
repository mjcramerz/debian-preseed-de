package AppArmor::ManagedModes::Workspace;

use strict;
use warnings;

use File::Basename qw(dirname);
use File::Path qw(remove_tree);
use File::Temp ();
use Fcntl qw(O_CREAT O_EXCL O_NOFOLLOW O_RDONLY O_TRUNC O_WRONLY);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

use AppArmor::ManagedModes::CLI qw(fatal);

has tmp_root => (
    is      => 'ro',
    default => sub {
        my $tmp_root = defined($ENV{TMPDIR}) && $ENV{TMPDIR} ne ''
            ? $ENV{TMPDIR}
            : '/tmp';
        _validate_temp_root($tmp_root);
        return $tmp_root;
    },
);
has directories => ( is => 'ro', default => sub { {} } );
has files       => ( is => 'ro', default => sub { {} } );

sub tempfile {
    my ($self, $label, $failure_message) = @_;
    $failure_message ||= "cannot create $label snapshot";
    my ($fh, $path) = eval {
        File::Temp::tempfile(
            "$label.XXXXXX",
            DIR    => $self->tmp_root(),
            UNLINK => 0,
        );
    };
    defined($fh) || fatal($failure_message);
    binmode $fh, ':raw' ||
        fatal($failure_message);
    $self->files()->{$path} = 1;
    return ($fh, $path);
}

sub tempdir {
    my ($self, $label, $failure_message) = @_;
    $failure_message ||= "cannot create $label workspace";
    my $path = eval {
        File::Temp::tempdir(
            "$label.XXXXXX",
            DIR     => $self->tmp_root(),
            CLEANUP => 0,
        );
    };
    defined($path) || fatal($failure_message);
    $self->directories()->{$path} = 1;
    return $path;
}

sub copy_file {
    my ($self, $source, $target, $message) = @_;

    sysopen my $source_fh, $source, O_RDONLY | O_NOFOLLOW ||
        fatal($message);
    binmode $source_fh, ':raw' ||
        fatal($message);
    sysopen my $target_fh,
        $target,
        O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW,
        0600 ||
        fatal($message);
    binmode $target_fh, ':raw' ||
        fatal($message);

    _copy_stream($source_fh, $target_fh, $message);
    close $source_fh || fatal($message);
    close $target_fh || fatal($message);
    chmod 0644, $target || fatal($message);
}

sub publish_file {
    my ($self, $source, $target, $message) = @_;
    my ($target_fh, $temporary_path) = eval {
        File::Temp::tempfile(
            '.apparmor-managed-modes.XXXXXX',
            DIR    => dirname($target),
            UNLINK => 0,
        );
    };
    defined($target_fh) || fatal($message);
    binmode $target_fh, ':raw' || fatal($message);
    $self->files()->{$temporary_path} = 1;

    sysopen my $source_fh, $source, O_RDONLY | O_NOFOLLOW ||
        fatal($message);
    binmode $source_fh, ':raw' ||
        fatal($message);
    _copy_stream($source_fh, $target_fh, $message);
    close $source_fh || fatal($message);
    chmod 0644, $temporary_path || fatal($message);
    close $target_fh || fatal($message);
    rename $temporary_path, $target || fatal($message);
    delete $self->files()->{$temporary_path};
}

sub truncate_file {
    my ($self, $path) = @_;

    open my $fh, '>:raw', $path ||
        fatal("cannot create AppArmor profile name snapshot: $path");
    close $fh ||
        fatal("cannot create AppArmor profile name snapshot: $path");
}

sub track_file {
    my ($self, $path) = @_;
    $self->files()->{$path} = 1;
}

sub forget_file {
    my ($self, $path) = @_;
    delete $self->files()->{$path};
}

sub remove_file {
    my ($self, $path) = @_;

    if (-e $path || -l $path) {
        unlink $path ||
            fatal("cannot remove managed temporary file: $path");
    }
    delete $self->files()->{$path};
}

sub remove_dir {
    my ($self, $path) = @_;

    _remove_directory($path) ||
        fatal("cannot remove managed temporary directory: $path");
    delete $self->directories()->{$path};
}

sub cleanup {
    my ($self) = @_;
    my $success = 1;

    for my $path (sort { length($b) <=> length($a) } keys %{ $self->directories() }) {
        _remove_directory($path) || ($success = 0);
    }
    for my $path (keys %{ $self->files() }) {
        if (-e $path || -l $path) {
            unlink $path || ($success = 0);
        }
    }
    %{ $self->directories() } = ();
    %{ $self->files() } = ();
    return $success;
}

sub _copy_stream {
    my ($source_fh, $target_fh, $message) = @_;

    while (1) {
        my $buffer = '';
        my $read = sysread($source_fh, $buffer, 65_536);
        defined($read) || fatal($message);
        last if $read == 0;

        my $offset = 0;
        while ($offset < $read) {
            my $written = syswrite($target_fh, $buffer, $read - $offset, $offset);
            defined($written) && $written > 0 || fatal($message);
            $offset += $written;
        }
    }
}

sub _remove_directory {
    my ($path) = @_;

    return 1 if !-e $path && !-l $path;
    return 0 if !-d $path || -l $path;
    my $errors;
    remove_tree($path, { error => \$errors, safe => 1 });
    return (!defined($errors) || !@$errors) && !-e $path && !-l $path;
}

sub _validate_temp_root {
    my ($path) = @_;

    my @metadata = lstat($path);
    @metadata ||
        fatal("temporary directory is unavailable: $path");
    my $mode = $metadata[2];
    ($mode & 0170000) == 0040000 && !-l $path ||
        fatal("temporary directory must be a real directory: $path");
    if ($> == 0) {
        $metadata[4] == 0 ||
            fatal("temporary directory must be owned by root: $path");
    }
    if ($mode & 0022) {
        $mode & 01000 ||
            fatal("writable temporary directory must have the sticky bit: $path");
    }
}

1;
