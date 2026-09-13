package Labwc::WorkspaceBroker::Runtime;
use strict;
use warnings;
use Exporter 'import';
use Fcntl qw(:DEFAULT :mode :flock F_GETFL F_SETFL O_NONBLOCK F_GETFD F_SETFD FD_CLOEXEC);
use Socket qw(AF_UNIX SOCK_STREAM SOCK_DGRAM SOL_SOCKET SO_PEERCRED sockaddr_un);
use IO::Socket::UNIX ();
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
use Errno qw(EINTR EEXIST);
our @EXPORT_OK = qw(now runtime_dir private_file read_private token nonblock cloexec peer listener connect_socket notify);

sub now { return clock_gettime(CLOCK_MONOTONIC); }
sub cloexec {
    my ($fh) = @_;
    my $flags = fcntl($fh, F_GETFD, 0);
    die "get descriptor flags: $!\n" unless defined $flags;
    fcntl($fh, F_SETFD, $flags | FD_CLOEXEC) or die "close-on-exec: $!\n";
}
sub nonblock {
    my ($fh) = @_;
    my $flags = fcntl($fh, F_GETFL, 0);
    die "get status flags: $!\n" unless defined $flags;
    fcntl($fh, F_SETFL, $flags | O_NONBLOCK) or die "nonblocking: $!\n";
    cloexec($fh);
}
sub _directory {
    my ($path) = @_;
    my @s = lstat($path);
    die "unsafe runtime directory\n" unless @s && S_ISDIR($s[2]) && $s[4] == $< && ($s[2] & 0777) == 0700;
}
sub runtime_dir {
    die "desktop user only\n" if !$< || $< != $>;
    my $base = "/run/user/$<";
    die "unexpected XDG_RUNTIME_DIR\n" unless ($ENV{XDG_RUNTIME_DIR} // '') eq $base;
    _directory($base);
    my $dir = "$base/labwc-workspace-broker";
    if (!lstat($dir)) { mkdir($dir, 0700) or $! == EEXIST or die "create runtime: $!\n"; }
    _directory($dir);
    # Only these absolute, UID-derived paths are ever untainted for IO/exec.
    return $dir;
}
sub private_file {
    my ($path, $flags) = @_;
    my $truncate = $flags & O_TRUNC;
    sysopen(my $fh, $path, ($flags & ~O_TRUNC) | O_NOFOLLOW | O_NONBLOCK, 0600) or die "open private file: $!\n";
    my @s = stat($fh);
    die "unsafe private file\n" unless @s && S_ISREG($s[2]) && $s[4] == $< && ($s[2] & 0777) == 0600 && $s[3] == 1;
    cloexec($fh);
    truncate($fh, 0) or die "truncate private file: $!\n" if $truncate;
    return $fh;
}
sub read_private {
    my ($path, $limit) = @_;
    my $fh = private_file($path, O_RDONLY);
    my $bytes = '';
    while (1) {
        my $n = sysread($fh, my $part, 4096);
        next if !defined($n) && $! == EINTR;
        die "private read: $!\n" unless defined $n;
        last unless $n;
        $bytes .= $part;
        die "private file too large\n" if length($bytes) > $limit;
    }
    close($fh) or die "private close: $!\n";
    return $bytes;
}
sub token {
    sysopen(my $fh, '/dev/urandom', O_RDONLY) or die "random source: $!\n";
    my $bytes = '';
    while (length($bytes) < 16) {
        my $n = sysread($fh, my $part, 16 - length($bytes));
        next if !defined($n) && $! == EINTR;
        die "random read\n" unless defined($n) && $n;
        $bytes .= $part;
    }
    close $fh;
    return unpack('H*', $bytes);
}
sub peer {
    my ($socket) = @_;
    my $cred = getsockopt($socket, SOL_SOCKET, SO_PEERCRED);
    die "peer credentials\n" unless defined($cred) && length($cred) == 12;
    my ($pid, $uid, $gid) = unpack('iII', $cred);
    die "foreign peer\n" unless $pid > 0 && $uid == $<;
    return ($pid, $uid, $gid);
}
sub listener {
    my ($path) = @_;
    if (my @s = lstat($path)) {
        die "unsafe old socket\n" unless S_ISSOCK($s[2]) && $s[4] == $<;
        unlink($path) or die "remove old socket: $!\n";
    }
    my $sock = IO::Socket::UNIX->new(Type => SOCK_STREAM, Local => $path, Listen => 32)
        or die "listen: $!\n";
    chmod(0600, $path) or die "socket mode: $!\n";
    nonblock($sock);
    return $sock;
}
sub connect_socket {
    my ($path) = @_;
    my @s = lstat($path);
    die "unsafe or absent socket\n" unless @s && S_ISSOCK($s[2]) && $s[4] == $< && ($s[2] & 0777) == 0600;
    # A local listening socket's backlog must not hang a Waybar helper forever.
    local $SIG{ALRM} = sub { die "connect timeout\n" };
    alarm 3;
    my $sock = IO::Socket::UNIX->new(Type => SOCK_STREAM, Peer => $path);
    alarm 0;
    die "connect: $!\n" unless $sock;
    peer($sock);
    nonblock($sock);
    return $sock;
}
sub notify {
    my ($message) = @_;
    my $path = $ENV{NOTIFY_SOCKET} // return;
    # Filesystem or abstract systemd notification socket, never an Internet address.
    die "notify path\n" unless length($path) <= 107 && $path =~ m{\A((?:/|@)[A-Za-z0-9_./\@:-]+)\z};
    $path = $1;
    $path =~ s/^@/\0/;
    socket(my $s, AF_UNIX, SOCK_DGRAM, 0) or die "notify socket: $!\n";
    nonblock($s);
    send($s, $message, 0, sockaddr_un($path)) // die "notify send: $!\n";
    close $s;
}
1;
