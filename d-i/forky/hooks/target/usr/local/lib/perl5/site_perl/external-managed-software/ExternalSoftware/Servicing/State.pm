package ExternalSoftware::Servicing::State;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Base qw(Str);

use Fcntl qw(:DEFAULT :flock F_SETFD FD_CLOEXEC O_CREAT O_NOFOLLOW O_RDWR);
use File::Copy qw(copy);
use File::Path qw(remove_tree);
use File::Spec;
use File::Temp qw(tempdir);
use ExternalSoftware::Servicing::Atomic;

has root => (is => 'ro', isa => Str, default => sub { '/var/lib/software' });

use constant WORK_DIRECTORY     => '/tmp';
use constant WORK_PREFIX        => 'managed-external-software-update.';
use constant WORK_RANDOM_LENGTH => 6;

sub event_dir { return $_[0]->root() . '/events'; }
sub deb_dir   { return $_[0]->root() . '/debs'; }
sub artifact_dir { return $_[0]->root() . '/artifacts'; }
sub state_dir { return $_[0]->root() . '/state'; }
sub lock_path { return '/run/lock/managed-external-software-update.lock'; }

sub prepare {
    my ($self) = @_;
    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->root(), 0755);
    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->event_dir(), 0755);
    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->deb_dir(), 0755);
    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->artifact_dir(), 0755);
    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->state_dir(), 0755);
    return 1;
}

sub _identifier {
    my ($self, $label, $value) = @_;
    defined $value && $value =~ /\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\z/
        or die "$label is invalid\n";
    return $value;
}

sub artifact_directory {
    my ($self, $application) = @_;
    $self->_identifier('artifact application', $application);
    my $directory = File::Spec->catdir($self->artifact_dir(), $application);
    ExternalSoftware::Servicing::Atomic->ensure_root_directory($directory, 0755);
    return $directory;
}

sub artifact_path {
    my ($self, $application, $name) = @_;
    my $directory = $self->artifact_directory($application);
    return ExternalSoftware::Servicing::Atomic->assert_child($directory, $name);
}

sub retain_artifact {
    my ($self, $application, $source, $name) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path('artifact source', $source);
    -f $source && !-l $source
        or die "verified artifact is not a regular file: $source\n";

    my $destination = $self->artifact_path($application, $name);
    if (-e $destination || -l $destination) {
        -f $destination && !-l $destination
            or die "retained artifact is not a regular file: $destination\n";
        my @st = lstat $destination;
        $st[4] == 0 && !($st[2] & 0022)
            or die "retained artifact is unsafe: $destination\n";
        return ($destination, 0);
    }

    my $temporary = "$destination.tmp.$$";
    copy($source, $temporary)
        or die "failed to retain verified artifact: $!\n";
    chmod 0644, $temporary
        or die "failed to set retained artifact mode: $!\n";
    rename $temporary, $destination
        or die "failed to publish retained artifact: $!\n";
    return ($destination, 1);
}

sub state_path {
    my ($self, $name) = @_;
    $self->_identifier('state file name', $name);
    return ExternalSoftware::Servicing::Atomic->assert_child($self->state_dir(), $name);
}

sub read_state {
    my ($self, $name, $limit) = @_;
    $limit //= 4096;
    $limit =~ /\A[0-9]+\z/ && $limit > 0 && $limit <= 1_048_576
        or die "state file read limit is invalid\n";
    my $path = $self->state_path($name);
    return undef if !-e $path && !-l $path;
    -f $path && !-l $path
        or die "state file is not a regular file: $path\n";
    my @st = lstat $path;
    $st[4] == 0 && !($st[2] & 0022)
        or die "state file is unsafe: $path\n";
    return ExternalSoftware::Servicing::Atomic->read_limited($path, $limit);
}

sub write_state {
    my ($self, $name, $text) = @_;
    defined $text && length($text) <= 1_048_576
        or die "state file payload is invalid\n";
    return ExternalSoftware::Servicing::Atomic->write_text(
        $self->state_path($name),
        $text,
        0644,
    );
}

sub delete_state {
    my ($self, $name) = @_;
    my $path = $self->state_path($name);
    return 1 if !-e $path && !-l $path;
    -f $path && !-l $path
        or die "state file is not removable: $path\n";
    unlink $path
        or die "failed to remove state file: $!\n";
    return 1;
}

sub lock {
    my ($self) = @_;
    my $path = $self->lock_path();
    ExternalSoftware::Servicing::Atomic->assert_absolute_path('managed updater lock', $path);
    sysopen my $fh, $path, O_CREAT | O_NOFOLLOW | O_RDWR, 0600
        or die "failed to open updater lock: $!\n";
    fcntl($fh, F_SETFD, FD_CLOEXEC) or die "failed to protect updater lock: $!\n";
    return undef if !flock($fh, LOCK_EX | LOCK_NB);
    return $fh;
}

sub _assert_work_dir_path {
    my ($self, $path) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path('updater workspace', $path);
    my $prefix = WORK_DIRECTORY . '/' . WORK_PREFIX;
    my $suffix = index($path, $prefix) == 0
        ? substr($path, length($prefix))
        : q{};
    length($suffix) == WORK_RANDOM_LENGTH
        && $suffix =~ /\A[A-Za-z0-9_]+\z/
        or die "refusing to remove an unexpected updater workspace\n";
    return $path;
}

sub work_dir {
    my ($self) = @_;
    my $path = tempdir(
        WORK_PREFIX . ('X' x WORK_RANDOM_LENGTH),
        DIR     => WORK_DIRECTORY,
        CLEANUP => 0,
    );
    $self->_assert_work_dir_path($path);
    -d $path && !-l $path
        or die "updater workspace is not a directory\n";
    my @st = lstat $path
        or die "failed to stat updater workspace: $!\n";
    $st[4] == $>
        or die "updater workspace is not owned by the updater\n";
    chmod 0700, $path or die "failed to set updater workspace mode: $!\n";
    return $path;
}

sub cleanup_work_dir {
    my ($self, $path) = @_;
    $self->_assert_work_dir_path($path);
    return 1 if !-e $path && !-l $path;
    -d $path && !-l $path
        or die "refusing to remove an unsafe updater workspace\n";
    my @st = lstat $path
        or die "failed to stat updater workspace: $!\n";
    $st[4] == $> && ($st[2] & 07777) == 0700
        or die "refusing to remove an unsafe updater workspace\n";
    remove_tree($path, { safe => 1, error => \my $errors });
    @{$errors} and die "failed to clean updater workspace\n";
    return 1;
}

1;
