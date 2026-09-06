package TimeshiftManaged::Snapshot;

use strict;
use warnings;

use Fcntl qw(:flock O_CREAT O_NOFOLLOW O_WRONLY);
use File::Basename qw(dirname);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Time::HiRes qw(sleep time);
use Types::Standard qw(Int Str);

use TimeshiftManaged::Command;
use TimeshiftManaged::EventQueue;
use TimeshiftManaged::Logger;

has binary => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has event_owner_gid => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has event_owner_uid => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has event_root => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has kind => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has lock_file => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has lock_timeout_seconds => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has logger => (
    is       => 'ro',
    required => 1,
);

has command => (
    is      => 'ro',
    default => sub { TimeshiftManaged::Command->new() },
);

sub from_environment {
    my ($class, $kind) = @_;

    return $class->new(
        binary               => $ENV{TIMESHIFT_BINARY} // '/usr/bin/timeshift',
        event_owner_gid      => _integer_from_environment('TIMESHIFT_EVENT_OWNER_GID', 0, 0, 2_147_483_647),
        event_owner_uid      => _integer_from_environment('TIMESHIFT_EVENT_OWNER_UID', 0, 0, 2_147_483_647),
        event_root           => $ENV{TIMESHIFT_EVENT_ROOT} // '/var/lib/labwc-notifications',
        kind                 => $kind,
        lock_file            => $ENV{TIMESHIFT_LOCK_FILE} // '/run/lock/timeshift-managed-snapshot.lock',
        lock_timeout_seconds => _integer_from_environment('TIMESHIFT_LOCK_TIMEOUT_SECONDS', 1800, 1, 21600),
        logger               => TimeshiftManaged::Logger->new(tag => 'timeshift-managed-snapshot'),
    );
}

sub _integer_from_environment {
    my ($name, $default, $minimum, $maximum) = @_;

    my $value = exists $ENV{$name} ? $ENV{$name} : $default;
    defined($value) && $value =~ /\A[0-9]+\z/
        or die "$name must be numeric\n";
    $value >= $minimum && $value <= $maximum
        or die "$name must be between $minimum and $maximum\n";
    return int($value);
}

sub _validate_absolute_path {
    my ($self, $label, $value) = @_;

    defined($value) && $value =~ m{\A/}
        or die "$label must be an absolute path\n";
    $value !~ m{(?:^|/)\.\.(?:/|$)}
        or die "$label contains a parent-directory component\n";
    $value !~ m{//}
        or die "$label contains an empty path component\n";
    $value =~ m{\A/[A-Za-z0-9._/@%:+,-]*\z}
        or die "$label contains unsupported path syntax\n";
    return;
}

sub _ensure_directory {
    my ($self, $directory) = @_;

    $self->_validate_absolute_path('Timeshift lock directory', $directory);
    my $current = q{};
    for my $part (grep { $_ ne q{} } split m{/+}, $directory) {
        $current .= "/$part";
        -l $current
            and die "Timeshift lock directory must not be a symlink: $current\n";
        my $created = 0;
        if (-e $current) {
            -d $current
                or die "Timeshift lock directory is not a directory: $current\n";
        }
        else {
            mkdir $current, 0755
                or die "cannot create Timeshift lock directory $current: $!\n";
            $created = 1;
        }
        if ($created || $current eq $directory) {
            chmod 0755, $current
                or die "cannot set Timeshift lock directory mode for $current: $!\n";
        }
    }
    return;
}

sub _validate {
    my ($self) = @_;

    $self->kind() =~ /\A(?:daily|weekly|monthly)\z/
        or die "unsupported managed Timeshift snapshot kind: " . $self->kind() . "\n";
    $self->_validate_absolute_path('Timeshift binary', $self->binary());
    $self->_validate_absolute_path('Timeshift event root', $self->event_root());
    $self->_validate_absolute_path('Timeshift lock file', $self->lock_file());
    -x $self->binary()
        or die "Timeshift binary is not executable: " . $self->binary() . "\n";
    return;
}

sub _queue {
    my ($self) = @_;

    return TimeshiftManaged::EventQueue->new(
        event_root => $self->event_root(),
        logger     => $self->logger(),
        owner_gid  => $self->event_owner_gid(),
        owner_uid  => $self->event_owner_uid(),
    );
}

sub _emit_or_warn {
    my ($self, $queue, %args) = @_;

    return if eval { $queue->emit(%args); 1 };
    my $error = $@ || 'unknown notification error';
    $error =~ s/\s+\z//;
    $self->logger()->warning("failed to queue Timeshift notification: $error");
    return;
}

sub _acquire_lock {
    my ($self) = @_;

    my $directory = dirname($self->lock_file());
    $self->_ensure_directory($directory);
    -l $self->lock_file()
        and die "Timeshift lock file must not be a symlink: " . $self->lock_file() . "\n";
    sysopen my $fh, $self->lock_file(), O_WRONLY | O_CREAT | O_NOFOLLOW, 0600
        or die "cannot open Timeshift snapshot lock: " . $self->lock_file() . ": $!\n";

    my $deadline = time() + $self->lock_timeout_seconds();
    while (!flock($fh, LOCK_EX | LOCK_NB)) {
        return undef if time() >= $deadline;
        sleep 0.2;
    }
    return $fh;
}

sub _command_arguments {
    my ($self) = @_;
    my %schedule = (
        daily   => ['D', 'Scheduled eight-times-daily snapshot'],
        weekly  => ['W', 'Scheduled twice-weekly snapshot'],
        monthly => ['M', 'Scheduled monthly snapshot'],
    );
    my ($tag, $comment) = @{ $schedule{ $self->kind() } };
    return (
        $self->binary(),
        '--create',
        '--scripted',
        '--yes',
        '--quiet',
        '--btrfs',
        '--tags',
        $tag,
        '--comments',
        $comment,
    );
}

sub run {
    my ($self) = @_;

    my $result = eval {
        $self->_validate();
        my $queue = $self->_queue();
        my $lock = $self->_acquire_lock();
        if (!$lock) {
            $self->logger()->warning('timed out waiting for the managed Timeshift snapshot lock');
            $self->_emit_or_warn($queue, status => 'failed', kind => $self->kind(), detail => 75);
            return 75;
        }

        $self->_emit_or_warn($queue, status => 'started', kind => $self->kind(), detail => '-');
        $self->logger()->info('starting managed Timeshift ' . $self->kind() . ' snapshot');
        local $ENV{PATH} = '/usr/local/libexec/timeshift-managed:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin';
        my $status = $self->command()->run($self->_command_arguments());
        if ($status == 0) {
            $self->_emit_or_warn($queue, status => 'completed', kind => $self->kind(), detail => '-');
            $self->logger()->info('completed managed Timeshift ' . $self->kind() . ' snapshot');
        }
        else {
            $self->_emit_or_warn($queue, status => 'failed', kind => $self->kind(), detail => $status);
            $self->logger()->error("managed Timeshift " . $self->kind() . " snapshot failed with status $status");
        }
        return $status;
    };

    if (!$result && $@) {
        my $error = $@;
        $error =~ s/\s+\z//;
        $self->logger()->error($error);
        return 1;
    }
    return $result;
}

1;
