package TimeshiftManaged::Lock;

use strict;
use warnings;

use Errno qw(EAGAIN EINTR EWOULDBLOCK EEXIST);
use Exporter qw(import);
use Fcntl qw(:flock O_CREAT O_NOFOLLOW O_NONBLOCK O_WRONLY F_GETFD F_SETFD FD_CLOEXEC);
use File::Basename qw(dirname);
use Time::HiRes qw(sleep clock_gettime CLOCK_MONOTONIC);

our @EXPORT_OK = qw(acquire_lock);

# Both managed snapshot mutation and menu readers use this same inode protocol.
# Never unlink lock files: replacing one would split concurrent owners.
sub acquire_lock {
    my ($path, $seconds) = @_;
    defined($path) && $path =~ m{\A/[A-Za-z0-9._/@%:+,-]+\z}
        && $path !~ m{(?:^|/)\.\.?(?:/|$)|//}
        or die "invalid Timeshift lock path\n";
    defined($seconds) && $seconds =~ /\A[0-9]+\z/ && $seconds <= 21600
        or die "invalid Timeshift lock timeout\n";

    my $current = q{};
    for my $part (grep { $_ ne q{} } split m{/}, dirname($path)) {
        $current .= "/$part";
        if (!-e $current && !-l $current) {
            mkdir($current, 0755) || $! == EEXIST
                or die "cannot create Timeshift lock directory: $!\n";
        }
        my @st = lstat $current;
        # A root-owned sticky shared directory such as /run/lock cannot let a
        # different UID replace our root-owned lock. Do not change its mode.
        @st && -d _ && !-l _ && $st[4] == $>
            && (!($st[2] & 0022) || ($st[2] & 01000))
            or die "untrusted Timeshift lock directory\n";
    }
    sysopen my $fh, $path, O_WRONLY | O_CREAT | O_NOFOLLOW | O_NONBLOCK, 0600
        or die "cannot open Timeshift lock: $!\n";
    my @st = stat $fh;
    @st && -f _ && $st[4] == $> && $st[3] == 1 && !($st[2] & 0022)
        or die "lock must be a trusted, singly linked regular file\n";
    my $flags = fcntl($fh, F_GETFD, 0);
    defined($flags) && defined(fcntl($fh, F_SETFD, $flags | FD_CLOEXEC))
        or die "cannot protect Timeshift lock descriptor\n";
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + $seconds;
    while (!flock($fh, LOCK_EX | LOCK_NB)) {
        ($! == EINTR || $! == EWOULDBLOCK || $! == EAGAIN)
            or die "cannot acquire Timeshift lock: $!\n";
        return undef if clock_gettime(CLOCK_MONOTONIC) >= $deadline;
        sleep 0.2;
    }
    my @named = lstat $path;
    @named && -f _ && !-l _ && join(':', @named[0,1,2,3,4,5]) eq join(':', @st[0,1,2,3,4,5])
        or die "Timeshift lock identity changed\n";
    return $fh;
}

1;
