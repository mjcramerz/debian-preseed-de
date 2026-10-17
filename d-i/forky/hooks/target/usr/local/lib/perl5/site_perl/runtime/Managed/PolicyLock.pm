package Managed::PolicyLock;

use strict;
use warnings;
use Exporter qw(import);
use Fcntl qw(:flock O_CREAT O_RDWR O_NOFOLLOW O_NONBLOCK F_GETFD F_SETFD FD_CLOEXEC);
use Scalar::Util qw(weaken);

our @EXPORT_OK = qw(acquire_policy_lock with_policy_lock_handoff);
my $active;
my $directory = '/var/lib/labwc-apparmor-policy';
my $path = "$directory/policy.lock";
my $handoff = 'MANAGED_APPARMOR_POLICY_LOCK_FD';

sub acquire_policy_lock {
    $> == 0 or die "AppArmor policy ownership requires root\n";
    return $active if defined($active) && $active->{pid} == $$;
    for my $parent ('/', '/var', '/var/lib') {
        my @st = lstat $parent;
        @st && -d _ && !-l _ && $st[4] == 0 && !($st[2] & 0022)
            or die "unsafe AppArmor policy lock ancestry\n";
    }
    if (!-e $directory && !-l $directory) {
        mkdir $directory, 0700 or $!{EEXIST}
            or die "cannot create AppArmor policy state: $!\n";
    }
    my @dir = lstat $directory;
    @dir && -d _ && !-l _ && $dir[4] == 0 && ($dir[2] & 0077) == 0
        or die "unsafe AppArmor policy state directory\n";
    sysopen my $named, $path, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK, 0600
        or die "cannot open AppArmor policy lock: $!\n";
    my @st = stat $named;
    @st && -f _ && $st[4] == 0 && $st[3] == 1 && ($st[2] & 0077) == 0
        or die "unsafe AppArmor policy lock\n";
    my $lock = $named;
    if (exists $ENV{$handoff}) {
        my $fd = delete $ENV{$handoff};
        defined($fd) && $fd =~ /\A[0-9]{1,8}\z/ && $fd > 2
            or die "invalid AppArmor lock handoff\n";
        open my $inherited, '+<&=', $fd or die "missing AppArmor lock handoff descriptor\n";
        my @inherited = stat $inherited;
        @inherited && join(':', @inherited[0,1,2,3,4,5]) eq join(':', @st[0,1,2,3,4,5])
            or die "AppArmor lock handoff identity changed\n";
        $lock = $inherited;
    }
    flock $lock, LOCK_EX | LOCK_NB or die "another AppArmor policy operation is in progress\n";
    my $flags = fcntl($lock, F_GETFD, 0);
    defined($flags) && defined(fcntl($lock, F_SETFD, $flags | FD_CLOEXEC))
        or die "cannot protect AppArmor policy lock descriptor\n";
    my $guard = bless {fh => $lock, pid => $$}, 'Managed::PolicyLock::Guard';
    $active = $guard;
    weaken($active);
    return $guard;
}

sub with_policy_lock_handoff {
    my ($callback) = @_;
    defined($active) && $active->{pid} == $$ or die "AppArmor policy handoff has no owner\n";
    my $fh = $active->{fh};
    my $flags = fcntl($fh, F_GETFD, 0);
    defined($flags) && defined(fcntl($fh, F_SETFD, $flags & ~FD_CLOEXEC))
        or die "cannot hand off AppArmor policy lock\n";
    local $ENV{$handoff} = fileno($fh);
    my @result;
    my $ok = eval { @result = $callback->(); 1 };
    my $error = $@;
    defined(fcntl($fh, F_SETFD, $flags)) or die "cannot restore AppArmor policy lock descriptor flags\n";
    die $error if !$ok;
    return wantarray ? @result : $result[0];
}

1;
