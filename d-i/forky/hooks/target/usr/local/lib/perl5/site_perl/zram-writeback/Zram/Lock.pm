package Zram::Lock;

use strict;
use warnings;

use Exporter qw(import);
use Fcntl qw(:DEFAULT :flock F_GETFD F_SETFD FD_CLOEXEC O_NOFOLLOW);
use File::Basename qw(dirname);
use Zram::Config qw(cfg cfg_default);
use Zram::Error qw(fatal);
use Zram::Logger qw(log_msg);
use Zram::Types qw(validate_abs_path);

our @EXPORT_OK = qw(ensure_runtime_dir acquire_lock try_acquire_lock);

sub ensure_runtime_dir {
    my $dir = cfg('ZRAM_RUNTIME_DIR');
    validate_abs_path('runtime_dir', $dir);
    if (!-d $dir) {
        mkdir $dir, 0750 or fatal("failed to create zram runtime dir $dir: $!");
    }
    my @st = lstat($dir) or fatal("failed to stat zram runtime dir $dir: $!");
    -l _ and fatal("zram runtime dir must not be a symlink: $dir");
    -d _ or fatal("zram runtime path is not a directory: $dir");
    ($st[4] == 0 || (cfg_default('ZRAM_DRY_RUN', 0) && $st[4] == $>))
        or fatal("zram runtime dir must be owned by root: $dir");
    chmod 0750, $dir or fatal("failed to chmod zram runtime dir $dir: $!");
}

sub _ensure_lock_parent {
    my ($path) = @_;
    my $dir = dirname($path);
    validate_abs_path('lock parent', $dir);
    if (!-d $dir) {
        mkdir $dir, 0750 or fatal("failed to create zram lock parent $dir: $!");
    }
    my @st = lstat($dir) or fatal("failed to stat zram lock parent $dir: $!");
    -l _ and fatal("zram lock parent must not be a symlink: $dir");
    -d _ or fatal("zram lock parent is not a directory: $dir");
    ($st[4] == 0 || (cfg_default('ZRAM_DRY_RUN', 0) && $st[4] == $>))
        or fatal("zram lock parent must be owned by root: $dir");
    chmod 0750, $dir or fatal("failed to chmod zram lock parent $dir: $!");
}

sub _open_lock_file {
    my $path = cfg('ZRAM_LOCK_FILE');
    validate_abs_path('lock_file', $path);
    ensure_runtime_dir();
    _ensure_lock_parent($path);
    -l $path and fatal("zram lock file must not be a symlink: $path");
    sysopen my $fh, $path, O_CREAT | O_WRONLY | O_APPEND | O_NOFOLLOW, 0600
        or fatal("failed to open zram lock $path: $!");
    chmod 0600, $path or fatal("failed to chmod zram lock $path: $!");
    my $flags = fcntl($fh, F_GETFD, 0);
    fcntl($fh, F_SETFD, $flags | FD_CLOEXEC)
        or fatal("failed to set close-on-exec on zram lock $path: $!");
    return ($fh, $path);
}

sub try_acquire_lock {
    my ($fh, $path) = _open_lock_file();
    if (!flock($fh, LOCK_EX | LOCK_NB)) {
        log_msg('info', 'another zram-writeback run is active; skipping this pass');
        return undef;
    }
    return $fh;
}

sub acquire_lock {
    my $fh = try_acquire_lock();
    exit 0 if !defined $fh;
    return $fh;
}

1;
