package Zram::AtomicFile;

use strict;
use warnings;

use Exporter qw(import);
use Fcntl qw(F_GETFD F_SETFD FD_CLOEXEC);
use File::Basename qw(basename dirname);
use File::Temp qw(tempfile);
use IO::Handle qw();

use Zram::Error qw(fatal);

our @EXPORT_OK = qw(write_atomic_text);

sub _discard_temp {
    my ($path) = @_;
    return if !defined $path || $path eq '';
    unlink $path if -e $path || -l $path;
}

sub _abort {
    my ($fh, $path, $message) = @_;
    close $fh if defined $fh;
    _discard_temp($path);
    fatal($message);
}

sub _validate_destination {
    my ($path, $mode) = @_;
    defined $path && !ref($path) && $path =~ m{\A/} && $path !~ /\x00/
        or fatal('atomic write destination must be a non-empty absolute path');
    defined $mode && !ref($mode) && $mode =~ /\A[0-9]+\z/ && $mode >= 0 && $mode <= 0777
        or fatal('atomic write mode must be an octal permission value');

    my $directory = dirname($path);
    my $filename = basename($path);
    -d $directory or fatal("atomic write directory is unavailable: $directory");
    $filename ne '' && $filename ne '.' && $filename ne '..' && $filename !~ /[\x00-\x1f\x7f]/
        or fatal('atomic write destination has an unsafe filename');
    return ($directory, $filename);
}

sub write_atomic_text {
    my ($path, $text, %opts) = @_;
    defined $text && !ref($text)
        or fatal('atomic write content must be a defined scalar');

    my $mode = exists $opts{mode} ? $opts{mode} : 0600;
    my ($directory, $filename) = _validate_destination($path, $mode);

    my ($fh, $temporary);
    eval {
        ($fh, $temporary) = tempfile(
            ".${filename}.XXXXXX",
            DIR    => $directory,
            UNLINK => 0,
        );
        1;
    } or fatal("failed to create a temporary file for $path: $@");

    chmod $mode, $temporary
        or _abort($fh, $temporary, "failed to set permissions on $temporary: $!");
    my $flags = fcntl($fh, F_GETFD, 0);
    defined $flags
        or _abort($fh, $temporary, "failed to read descriptor flags for $temporary: $!");
    fcntl($fh, F_SETFD, $flags | FD_CLOEXEC)
        or _abort($fh, $temporary, "failed to set close-on-exec for $temporary: $!");
    binmode $fh, ':raw'
        or _abort($fh, $temporary, "failed to set raw mode for $temporary: $!");
    print {$fh} $text
        or _abort($fh, $temporary, "failed to write $temporary: $!");
    $fh->flush()
        or _abort($fh, $temporary, "failed to flush $temporary: $!");
    $fh->sync()
        or _abort($fh, $temporary, "failed to sync $temporary: $!");
    close $fh
        or _abort(undef, $temporary, "failed to close $temporary: $!");
    chmod $mode, $temporary
        or _abort(undef, $temporary, "failed to set final permissions on $temporary: $!");
    rename $temporary, $path
        or _abort(undef, $temporary, "failed to atomically install $path: $!");

    my @installed = lstat($path);
    @installed && -f _ && !-l _
        or fatal("atomic rename did not create a regular file at $path");
    ($installed[2] & 0777) == $mode
        or fatal("atomic rename installed $path with unexpected permissions");
    return 1;
}

1;
