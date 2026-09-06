package AndroidADB::Lock;

use strict;
use warnings;

use File::Path qw(remove_tree);
use Cwd qw(abs_path);
use Fcntl qw(:flock O_CREAT O_RDWR O_NOFOLLOW F_SETFD FD_CLOEXEC);
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

has active_lock_path => (
    is      => 'rw',
    default => sub { undef },
);

has active_partial_directory => (
    is      => 'rw',
    default => sub { undef },
);

has active_lock_handle => (is => 'rw', default => sub { undef });
has partial_identity => (is => 'rw', default => sub { undef });

sub acquire {
    my ($self, $operation_name, $lock_root) = @_;
    require_value(
        (defined($operation_name) && !!($operation_name =~ /\A[a-z0-9-]+\z/)),
        'managed Android operation name is invalid',
    );
    $self->_require_managed_directory($lock_root);

    my $lock_path = File::Spec->catfile($lock_root, 'device-maintenance.lock');
    if (defined $self->active_lock_handle) {
        $self->active_lock_path eq $lock_path or fail('this operation already owns another lock');
        return $lock_path;
    }
    # Never remove/recreate lock files: that would allow two distinct locked
    # inodes. Legacy mkdir locks require stopping old processes before removal.
    -d $lock_path and fail('legacy Android lock directory exists; stop old actions before removing the empty directory');
    sysopen my $fh, $lock_path, O_RDWR | O_CREAT | O_NOFOLLOW, 0600
        or fail("cannot open managed Android lock: $!");
    my @st = stat $fh;
    -f $fh && $st[4] == $< && $st[3] == 1 && ($st[2] & 0077) == 0
        or fail('managed Android lock metadata is unsafe');
    fcntl($fh, F_SETFD, FD_CLOEXEC) or fail("cannot protect managed Android lock: $!");
    flock($fh, LOCK_EX | LOCK_NB)
        or fail('another managed Android backup, firmware download, or flash action is already running');
    $self->active_lock_path($lock_path);
    $self->active_lock_handle($fh);
    print "Acquired managed device-operation lock for $operation_name.\n";
    return $lock_path;
}

sub register_partial_directory {
    my ($self, $directory) = @_;
    $self->_require_managed_directory($directory);
    $directory ne $self->config->output_root or fail('output root cannot be a partial operation');
    !defined($self->active_partial_directory) or fail('a partial operation is already registered');
    my @st = lstat $directory;
    $self->partial_identity([$st[0], $st[1]]);
    $self->active_partial_directory($directory);
    return $directory;
}

sub complete_partial_directory {
    my ($self, $directory) = @_;
    if (defined($self->active_partial_directory)
        && $self->active_partial_directory eq $directory) {
        $self->active_partial_directory(undef);
        $self->partial_identity(undef);
    }
    return;
}

sub release {
    my ($self) = @_;
    my $fh = $self->active_lock_handle;
    $self->active_lock_handle(undef);
    $self->active_lock_path(undef);
    close $fh or warn "cannot close Android operation lock: $!\n" if defined $fh;
    return;
}

sub cleanup {
    my ($self) = @_;
    my $partial = $self->active_partial_directory;
    my $ok = eval {
        if (defined($partial) && (-e $partial || -l $partial)) {
            $self->_require_managed_directory($partial);
            my @st = lstat $partial;
            my $identity = $self->partial_identity;
            $identity && $st[0] == $identity->[0] && $st[1] == $identity->[1]
                or fail('partial Android directory changed identity; refusing cleanup');
            remove_tree($partial, { safe => 1, error => \my $errors });
            @{$errors} and fail('could not completely remove the partial Android directory');
        }
        1;
    };
    my $error = $@;
    $self->active_partial_directory(undef);
    $self->partial_identity(undef);
    $self->release;
    # Cleanup must release its lock even when removal fails, and must not
    # replace the original operation/signal diagnostic with a second exception.
    warn "Android operation cleanup: $error" if !$ok;
    return $ok ? 1 : 0;
}

sub _require_managed_directory {
    my ($self, $directory) = @_;
    require_value(
        defined($directory) && -d $directory && !-l $directory
            && (lstat $directory)[4] == $< && ((lstat $directory)[2] & 0022) == 0,
        'managed Android operation directory is invalid',
    );
    $self->_require_managed_path($directory);
    return;
}

sub _require_managed_path {
    my ($self, $path) = @_;
    require_value(
        (
            defined($path)
                && !ref($path)
                && !!($path =~ m{\A/})
                && !!($path !~ /[\x00-\x1f\x7f]/)
                && !!($path !~ m{(?:\A|/)\.\.?(?:/|\z)|//})
        ),
        'managed Android operation path is invalid',
    );
    my $root = $self->config->output_root;
    my $resolved_root = abs_path($root);
    my $resolved_path = abs_path($path);
    require_value(
        defined($resolved_root) && $resolved_root eq $root
            && defined($resolved_path) && $resolved_path eq $path
            && ($path eq $root || index($path, "$root/") == 0),
        'managed Android operation path escapes the output root',
    );
    return;
}

1;
