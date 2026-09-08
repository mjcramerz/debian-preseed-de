package ExternalSoftware::Servicing::Atomic;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Digest::SHA;
use Fcntl qw(:DEFAULT O_CREAT O_EXCL O_NOFOLLOW);
use File::Basename qw(dirname);
use File::Path qw(make_path);
use File::Spec;
use File::Temp qw(tempfile);
use IO::Handle;
use Errno qw(EINTR);

sub assert_absolute_path {
    my ($class, $label, $path) = @_;
    defined $path && $path =~ m{\A/(?:[A-Za-z0-9._@%:+,-]+/)*[A-Za-z0-9._@%:+,-]+\z}
        or die "$label must be a safe absolute path\n";
    grep { $_ eq q{.} || $_ eq q{..} } split m{/}, $path
        and die "$label contains a traversal component\n";
    return $path;
}

sub assert_child {
    my ($class, $directory, $name) = @_;
    $class->assert_absolute_path('parent directory', $directory);
    defined $name && $name =~ /\A[A-Za-z0-9._:+~,-]+\z/
        or die "unsafe managed filename\n";
    $name ne q{.} && $name ne q{..} or die "unsafe managed filename\n";
    my $path = File::Spec->catfile($directory, $name);
    index($path, "$directory/") == 0 or die "managed path escaped its parent\n";
    return $path;
}

sub ensure_root_directory {
    my ($class, $path, $mode) = @_;
    $class->assert_absolute_path('managed directory', $path);
    if (!-e $path) {
        make_path($path, { mode => $mode }) or die "failed to create $path\n";
    }
    -d $path && !-l $path or die "managed path is not a directory: $path\n";
    my @st = lstat $path or die "failed to stat $path: $!\n";
    $st[4] == 0 or die "managed path must be root-owned: $path\n";
    chmod $mode, $path or die "failed to set mode on $path: $!\n";
    return $path;
}

sub read_limited {
    my ($class, $path, $limit) = @_;
    $class->assert_absolute_path('input path', $path);
    defined($limit) && $limit =~ /\A[1-9][0-9]*\z/ && $limit <= 64 * 1024 * 1024
        or die "invalid input limit\n";
    my @before = lstat $path;
    @before && -f _ && !-l _ or die "expected a regular file: $path\n";
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or die "failed to open $path: $!\n";
    my @st = stat $fh;
    -f $fh && $st[0] == $before[0] && $st[1] == $before[1]
        && $st[4] == $before[4] && $st[2] == $before[2] && $st[7] <= $limit
        or die "input changed or exceeds size limit: $path\n";
    my $content = q{};
    while (1) {
        my $n = sysread($fh, my $chunk, 8192);
        next if !defined($n) && $! == EINTR;
        defined($n) or die "failed to read $path: $!\n";
        last if $n == 0;
        $content .= $chunk;
        length($content) <= $limit or die "input exceeds size limit: $path\n";
    }
    close $fh or die "failed to close $path: $!\n";
    return $content;
}

sub sha256_file {
    my ($class, $path, $limit) = @_;
    $class->assert_absolute_path('digest input path', $path);
    defined($limit) && $limit =~ /\A[1-9][0-9]*\z/ && $limit <= 536_870_912
        or die "invalid digest input limit\n";

    my @before = lstat $path;
    @before && -f _ && !-l _ && $before[7] <= $limit
        or die "digest input is not a bounded regular file: $path\n";
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or die "failed to open digest input $path: $!\n";
    my @opened = stat $fh;
    @opened && -f $fh
        && join("\0", @opened[0, 1, 2, 3, 4, 5, 7])
            eq join("\0", @before[0, 1, 2, 3, 4, 5, 7])
        or die "digest input changed before hashing: $path\n";

    my $digest = Digest::SHA->new(256);
    my $size = 0;
    while (1) {
        my $read = sysread($fh, my $chunk, 65_536);
        next if !defined($read) && $! == EINTR;
        defined($read) or die "failed to read digest input $path: $!\n";
        last if $read == 0;
        $size += $read;
        $size <= $limit or die "digest input exceeds size limit: $path\n";
        $digest->add($chunk);
    }

    my @after = stat $fh;
    @after
        && $size == $opened[7]
        && join("\0", @after[0, 1, 2, 3, 4, 5, 7, 9, 10])
            eq join("\0", @opened[0, 1, 2, 3, 4, 5, 7, 9, 10])
        or die "digest input changed while hashing: $path\n";
    close $fh or die "failed to close digest input $path: $!\n";
    return wantarray ? ($size, $digest->hexdigest()) : $digest->hexdigest();
}

sub _publish {
    my ($class, $path, $text, $mode) = @_;
    -l $path and die "output path must not be a symlink: $path\n";
    my ($fh, $temporary) = tempfile('.publish.XXXXXXXX', DIR => dirname($path), UNLINK => 1);
    my $ok = eval {
        binmode $fh, ':raw' or die "cannot set output mode: $!\n";
        chmod $mode, $temporary or die "cannot set temporary mode: $!\n";
        print {$fh} $text or die "cannot write temporary output: $!\n";
        $fh->flush && $fh->sync or die "cannot sync temporary output: $!\n";
        close $fh or die "cannot close temporary output: $!\n";
        rename $temporary, $path or die "cannot publish $path: $!\n";
        1;
    };
    my $error = $@;
    unlink $temporary if -e $temporary;
    die $error if !$ok;
    return $path;
}

sub write_text {
    my ($class, $path, $text, $mode) = @_;
    $class->assert_absolute_path('output path', $path);
    $class->ensure_root_directory(dirname($path), 0755);
    return $class->_publish($path, $text, $mode);
}

sub write_user_text {
    my ($class, $path, $text, $mode) = @_;
    $class->assert_absolute_path('output path', $path);
    my @st = lstat dirname($path);
    @st && -d _ && !-l _ && $st[4] == $< && ($st[2] & 0077) == 0
        or die "unsafe user notification directory\n";
    ($mode & 0077) == 0 or die "user notification files must be private\n";
    return $class->_publish($path, $text, $mode);
}

sub remove_tree {
    my ($class, $path) = @_;
    $class->assert_absolute_path('removal path', $path);
    return 1 if !-e $path && !-l $path;
    File::Path::remove_tree($path, { safe => 1, error => \my $errors });
    @{$errors} and die "failed to remove managed path $path\n";
    return 1;
}

1;
