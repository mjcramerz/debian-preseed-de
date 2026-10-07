package TimeshiftManaged::GrubRefresh;

use strict;
use warnings;

use Errno qw(EAGAIN EINTR EWOULDBLOCK);
use Fcntl qw(:flock O_CREAT O_NOFOLLOW O_NONBLOCK O_WRONLY O_RDONLY O_DIRECTORY);
use Cwd qw(realpath);
use Encode qw(encode FB_CROAK);
use File::Compare qw(compare);
use IO::Handle;
use File::Basename qw(basename dirname);
use File::Temp qw(tempfile);
use JSON::PP qw(decode_json);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Time::HiRes qw(sleep clock_gettime CLOCK_MONOTONIC);
use Types::Standard qw(Int Str);

use TimeshiftManaged::Command;
use TimeshiftManaged::Config;
use TimeshiftManaged::Logger;

has grub_btrfs_config => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/default/grub-btrfs/config' },
);

has logger => (
    is      => 'ro',
    default => sub { TimeshiftManaged::Logger->new(tag => 'grub-btrfs-refresh') },
);

has lock_file => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/run/lock/grub-btrfs-refresh.lock' },
);

has output_file => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/boot/grub/grub-btrfs.cfg' },
);

has profile_config => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/default/grub-profiles' },
);

has profile_generator => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/grub.d/40_custom' },
);

has command => (
    is      => 'ro',
    default => sub { TimeshiftManaged::Command->new() },
);

sub _require_absolute_path {
    my ($self, $label, $value) = @_;

    defined($value) && $value =~ m{\A/[A-Za-z0-9._/@%:+,-]*\z}
        or die "$label must be an absolute path\n";
    $value !~ m{(?:^|/)\.\.?(?:/|$)} && $value !~ m{//}
        or die "$label contains unsafe path syntax\n";
    return;
}

sub _ensure_directory {
    my ($self, $directory, $mode) = @_;

    $self->_require_absolute_path('runtime directory', $directory);
    my $current = q{};
    for my $part (grep { $_ ne q{} } split m{/+}, $directory) {
        $current .= "/$part";
        -l $current
            and die "runtime directory must not be a symbolic link: $current\n";
        my $created = 0;
        if (-e $current) {
            -d $current
                or die "runtime directory is not a directory: $current\n";
        }
        else {
            mkdir $current, $mode
                or die "cannot create runtime directory $current: $!\n";
            $created = 1;
        }
        if ($created) {
            chmod $mode, $current
                or die "cannot set runtime directory mode for $current: $!\n";
        }
    }
    return;
}

sub _acquire_lock {
    my ($self) = @_;

    my $lock_dir = dirname($self->lock_file());
    $self->_ensure_directory($lock_dir, 0755);
    -l $self->lock_file()
        and die "refresh lock must not be a symbolic link: " . $self->lock_file() . "\n";
    sysopen my $fh, $self->lock_file(), O_WRONLY | O_CREAT | O_NOFOLLOW | O_NONBLOCK, 0600
        or die "cannot open refresh lock " . $self->lock_file() . ": $!\n";
    my @lock_stat = stat $fh;
    @lock_stat && -f _ && $lock_stat[4] == $> && $lock_stat[3] == 1
        && !($lock_stat[2] & 0022)
        or die "lock must be a trusted, singly linked regular file\n";

    if (!flock($fh, LOCK_EX | LOCK_NB)) {
        ($! == EWOULDBLOCK || $! == EAGAIN) or die "cannot lock snapshot menu: $!\n";
        $self->logger()->info('another grub-btrfs-refresh run is active; skipping this event');
        return undef;
    }
    return $fh;
}

sub _runtime_snapshot_active {
    my ($self) = @_;

    for my $directory (glob('/run/timeshift/*/backup/timeshift-btrfs/snapshots')) {
        return 1 if -d $directory;
    }
    return 0;
}

sub _wait_for_timeshift_exit {
    my ($self) = @_;

    my $deadline = clock_gettime(CLOCK_MONOTONIC) + 300;
    while ($self->_runtime_snapshot_active()) {
        clock_gettime(CLOCK_MONOTONIC) < $deadline
            or die "Timeshift runtime mounts did not disappear within 300s\n";
        sleep 1;
    }
    return;
}

sub _mount_path_is_active {
    my ($self, $mount_path) = @_;

    open my $fh, '<', '/proc/mounts'
        or die "cannot read /proc/mounts: $!\n";
    while (my $line = <$fh>) {
        my @fields = split /\s+/, $line;
        if (@fields >= 2 && $fields[1] eq $mount_path) {
            close $fh;
            return 1;
        }
    }
    close $fh or die "cannot close /proc/mounts: $!\n";
    return 0;
}

sub _program {
    my ($self, $name) = @_;

    my $program = $self->command()->find_executable($name);
    defined($program)
        or die "required executable is unavailable: $name\n";
    return $program;
}

sub _cleanup_mount_path {
    my ($self, $mount_path) = @_;

    return if !defined($mount_path) || $mount_path eq q{};
    -l $mount_path and die "refresh mount path must not be a symlink\n";
    if ($self->_mount_path_is_active($mount_path)) {
        my ($status) = $self->command()->capture(
            argv => [ $self->_program('umount'), $mount_path ], timeout => 30,
        );
        $status == 0 or die "cannot unmount refresh mount $mount_path\n";
    }
    if (-d $mount_path) {
        rmdir $mount_path or die "cannot remove refresh mount directory $mount_path: $!\n";
    }
    return;
}



sub _load_configurations {
    my ($self) = @_;

    return undef if !-r $self->profile_config() || !-r $self->grub_btrfs_config();
    my $profile_reader = TimeshiftManaged::Config->new(
        allowed_keys => [
            qw(
              dev_part_boot dev_part_root dev_part_efi
              bootprofile_default bootprofile_performance bootprofile_hardened
              grub_root_flags grub_initramfs_flags grub_nvme_flags grub_cgroup_flags
              grub_security_core_flags grub_blacklist_flags grub_vfio_flags
              grub_memory_core_flags grub_hardening_flags grub_aspm_flags
              grub_systemd_mask_flags grub_profile_default_flags
              grub_profile_performance_flags grub_profile_hardened_flags
              mok_der_path grub_default_entry rescue_usb_uuid grub_gfxpayload_linux
              dualboot_enabled grub_hardware_flags
            )
        ],
        path => $self->profile_config(),
    );
    # Check the base data separately as well; the generator sources only trusted
    # root-owned files and exports data, never a menu or an arbitrary command.
    $profile_reader->load();
    my $generator = $self->profile_generator();
    $self->_require_absolute_path('profile generator', $generator);
    my @generator_stat = lstat $generator;
    @generator_stat && -f _ && !-l _ && $generator_stat[4] == $>
        && !($generator_stat[2] & 0022) && -x $generator
        or die "custom GRUB profile generator is missing or untrusted\n";
    my ($status, $export) = $self->command()->capture(
        argv => [ $generator, '--snapshot-config' ], timeout => 15,
    );
    $status == 0 or die "cannot export effective custom GRUB profiles\n";
    my $profile = $profile_reader->parse_content($export);
    my $grub_btrfs = TimeshiftManaged::Config->new(
        allowed_keys => [
            qw(GRUB_BTRFS_SNAPSHOT_DIR GRUB_BTRFS_ROOT_SUBVOLUME GRUB_BTRFS_LIMIT GRUB_BTRFS_STATE_DIR)
        ],
        path => $self->grub_btrfs_config(),
    )->load();
    return ($profile, $grub_btrfs);
}

sub _validate_relative_subvolume_path {
    my ($self, $label, $value) = @_;

    defined($value) && $value ne q{}
        or die "$label must not be empty\n";
    $value !~ m{\A/} && $value !~ m{//}
        or die "$label must be relative and contain no empty path components\n";
    $value !~ m{(?:^|/)\.\.?(?:/|$)}
        or die "$label contains a parent-directory component\n";
    $value =~ m{\A[A-Za-z0-9@._/+:-]+\z}
        or die "$label contains unsupported characters\n";
    return;
}

sub _bootable_kernel_images {
    my ($self) = @_;

    my @images = grep {
        my $version = $_;
        $version =~ s{\A/boot/vmlinuz-}{};
        $version =~ /\A[A-Za-z0-9_.:+~=-]+\z/
            && -f $_ && -f "/boot/initrd.img-$version";
    } glob('/boot/vmlinuz-*');
    return () if !@images;
    my ($status, $output) = $self->command()->capture(
        argv  => [ $self->_program('sort'), '-Vr' ],
        input => join(q{}, map { "$_\n" } @images),
    );
    $status == 0 or die "cannot sort bootable kernel images\n";
    return grep { $_ ne q{} } split /\n/, $output;
}

sub _uuid_for_device {
    my ($self, $device) = @_;

    defined($device) && $device =~ m{\A/dev/[A-Za-z0-9._/+:-]+\z}
        or die "invalid block-device path\n";
    my ($status, $output) = $self->command()->capture(
        argv => [ $self->_program('blkid'), '-s', 'UUID', '-o', 'value', $device ],
    );
    return q{} if $status != 0;
    $output =~ s/[\r\n]+\z//;
    $output =~ /\A[A-Za-z0-9-]+\z/
        or return q{};
    return $output;
}

sub _snapshot_writable {
    my ($self, $snapshot_subvolume) = @_;

    my ($status, $output) = $self->command()->capture(
        argv => [ $self->_program('btrfs'), 'property', 'get', '-ts', $snapshot_subvolume, 'ro' ],
        timeout => 5,
    );
    return 0 if $status != 0;
    $output =~ s/\s+\z//;
    return $output eq 'ro=false' ? 1 : 0;
}

sub _snapshot_metadata {
    my ($self, $snapshot_dir) = @_;

    my $info_file = "$snapshot_dir/info.json";
    sysopen my $fh, $info_file, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or return (undef, undef);
    my @stat = stat $fh;
    return (undef, undef) if !@stat || !-f _ || $stat[7] > 1_048_576;
    my $raw = q{};
    while (1) {
        my $count = sysread($fh, my $chunk, 8192);
        if (!defined $count) {
            next if $! == EINTR;
            return (undef, undef);
        }
        last if !$count;
        $raw .= $chunk;
        return (undef, undef) if length($raw) > 1_048_576;
    }
    close $fh or return (undef, undef);
    my $metadata = eval { decode_json($raw) };
    return (undef, undef) if !$metadata || ref($metadata) ne 'HASH';
    my $tags = ref($metadata->{tags}) ? q{} : ($metadata->{tags} // q{});
    my $comment = ref($metadata->{comments}) ? q{} : ($metadata->{comments} // q{});
    my %labels = (B => 'boot', D => 'daily', H => 'hourly', M => 'monthly', O => 'ondemand', W => 'weekly');
    my %seen;
    my $tag = join q{, }, map { $labels{$_} }
        grep { exists($labels{$_}) && !$seen{$_}++ } split /[ ,]+/, $tags;
    $comment =~ s/[\x00-\x1f\x7f\p{Cf}]/ /g;
    $comment = substr($comment, 0, 160);
    return ($tag, $comment);
}

sub _grub_single_quote {
    my ($self, $value) = @_;

    $value //= q{};
    $value =~ s/'/'\\''/g;
    return $value;
}

sub _grub_id_fragment {
    my ($self, $value) = @_;

    $value //= q{};
    $value =~ s/[^A-Za-z0-9_]/_/g;
    return $value;
}

sub _format_snapshot_timestamp {
    my ($self, $value) = @_;

    $value =~ s/_/ /;
    $value =~ s/(\d{2})-(\d{2})-(\d{2})\z/$1:$2:$3/;
    return $value;
}

sub _snapshot_root_flags {
    my ($self, $grub_root_flags, $snapshot_dir_rel, $snapshot_name, $root_subvolume) = @_;

    $self->_validate_relative_subvolume_path('snapshot directory', $snapshot_dir_rel);
    $self->_validate_relative_subvolume_path('root subvolume', $root_subvolume);
    $snapshot_name =~ /\A\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\z/
        or die "invalid snapshot name\n";
    $self->_validate_command_line($grub_root_flags);
    my (@flags, @options);
    for my $flag (split / +/, $grub_root_flags) {
        next if $flag eq q{};
        if ($flag =~ /\Arootflags=(.*)\z/) {
            push @options, grep { $_ ne q{} && !/\Asubvol(?:id)?=/ } split /,/, $1;
        }
        else { push @flags, $flag; }
    }
    my $subvolume = "$snapshot_dir_rel/$snapshot_name/$root_subvolume";
    push @flags, 'rootflags=' . join(q{,}, "subvol=$subvolume", @options);
    return join q{ }, @flags;
}

sub _validate_command_line {
    my ($self, $value) = @_;
    defined($value) && $value =~ m{\A[A-Za-z0-9_.,:/=@%+~!?\[\] -]*\z}
        or die "unsafe GRUB command-line flags\n";
    return;
}

sub _validate_profiles {
    my ($self, $profile) = @_;
    for my $key (qw(bootprofile_default bootprofile_performance bootprofile_hardened)) {
        ($profile->{$key} // q{}) =~ /\A[A-Za-z0-9_.:-]+\z/
            or die "invalid GRUB profile identifier: $key\n";
    }
    for my $key (grep { /\Agrub_.*_flags\z/ } keys %{$profile}) {
        $self->_validate_command_line($profile->{$key});
    }
    ($profile->{grub_gfxpayload_linux} // q{}) =~ /\A[A-Za-z0-9_,.x-]*\z/
        or die "invalid GRUB graphics payload\n";
    return;
}

sub _fallback_menu {
    return <<'GRUB';
# Managed by installer automation.
set timeout=-1

menuentry 'No BTRFS snapshots available' {
    echo 'No BTRFS snapshots are available.'
}

menuentry 'Return to main menu' --id 'installer-snapshot-return' --class os {
    configfile $prefix/grub.cfg
}
GRUB
}

sub _render_snapshot_menu {
    my ($self, %args) = @_;

    my $snapshot_root = $args{snapshot_root};
    my $snapshot_dir_rel = $args{snapshot_dir_rel};
    my $root_subvolume = $args{root_subvolume};
    my $kernel_images = $args{kernel_images};
    my $profile = $args{profile};
    my $root_arg = $args{root_arg};
    my $boot_search = $args{boot_search};
    my $base_cmdline = $args{base_cmdline};
    my $limit = $args{limit};
    $self->_validate_profiles($profile);
    $self->_validate_command_line($base_cmdline);

    my @profiles = (
        [ $profile->{bootprofile_default}, 'Balanced',    $profile->{grub_profile_default_flags} ],
        [ $profile->{bootprofile_performance}, 'Performance', $profile->{grub_profile_performance_flags} ],
        [ $profile->{bootprofile_hardened}, 'Hardened',   $profile->{grub_profile_hardened_flags} ],
    );
    my @lines = ("# Managed by installer automation.\n", "set timeout=-1\n\n");
    my $rendered = 0;
    my $count = 0;

    opendir my $dh, $snapshot_root
        or die "cannot read Timeshift snapshot root $snapshot_root: $!\n";
    my @snapshots = sort { $b cmp $a } grep {
        $_ ne q{.} && $_ ne q{..} && -d "$snapshot_root/$_" && !-l "$snapshot_root/$_";
    } readdir $dh;
    closedir $dh or die "cannot close Timeshift snapshot root $snapshot_root: $!\n";

    SNAPSHOT:
    for my $snapshot_name (@snapshots) {
        if ($snapshot_name !~ /\A\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\z/) {
            $self->logger()->warning("ignoring malformed Timeshift snapshot directory: $snapshot_name");
            next;
        }
        my $subvolume = "$snapshot_root/$snapshot_name/$root_subvolume";
        next SNAPSHOT if !-d $subvolume || (realpath($subvolume) // q{}) ne $subvolume;
        if (!$self->_snapshot_writable($subvolume)) {
            $self->logger()->warning("ignoring read-only or unreadable Timeshift snapshot: $snapshot_name");
            next;
        }

        my ($tag, $comment) = $self->_snapshot_metadata("$snapshot_root/$snapshot_name");
        next SNAPSHOT if !defined $tag; # incomplete or invalid snapshot metadata
        my $title = $self->_format_snapshot_timestamp($snapshot_name);
        $title .= " [$tag]" if $tag ne q{};
        $title .= " $comment" if $comment ne q{};
        my $entry_id = 'installer_snapshot_' . $self->_grub_id_fragment($snapshot_name);
        my $root_flags = $self->_snapshot_root_flags(
            $profile->{grub_root_flags},
            $snapshot_dir_rel,
            $snapshot_name,
            $root_subvolume,
        );
        my @snapshot_lines;
        my $has_entries = 0;
        for my $profile_spec (@profiles) {
            my ($profile_name, $profile_label, $profile_flags) = @{$profile_spec};
            next if !defined($profile_name) || $profile_name eq q{};
            my @profile_lines;
            for my $kernel_image (@{$kernel_images}) {
                my $kernel_version = $kernel_image;
                $kernel_version =~ s{\A/boot/vmlinuz-}{};
                $kernel_version =~ /\A[A-Za-z0-9_.:+~=-]+\z/
                    or die "invalid kernel version\n";
                my $modules = realpath("$subvolume/lib/modules/$kernel_version");
                # Accept Debian's relative usrmerge link, never a link escaping
                # this snapshot (including an absolute /usr/lib link).
                next if !defined($modules) || index($modules, "$subvolume/") != 0 || !-d $modules;
                my $kernel_id = $self->_grub_id_fragment($kernel_version);
                my $profile_id = $self->_grub_id_fragment($profile_name);
                push @profile_lines,
                    "    menuentry '" . $self->_grub_single_quote("[$profile_label] $kernel_version")
                    . "' --id '${entry_id}_${profile_id}_${kernel_id}' --class debian --class gnu-linux --class gnu --class os {\n",
                    "        if [ -s \$prefix/grubenv ]; then\n",
                    "            set installer_linux_last_profile='$profile_name'\n",
                    "            set installer_linux_last_kernel='$kernel_version'\n",
                    "            save_env installer_linux_last_profile\n",
                    "            save_env installer_linux_last_kernel\n",
                    "        fi\n",
                    "        insmod gzio\n",
                    "        insmod zstd\n",
                    "        insmod part_gpt\n",
                    "        insmod ext2\n",
                    "        $boot_search\n";
                if (($profile->{grub_gfxpayload_linux} // q{}) ne q{}) {
                    push @profile_lines,
                        "        set gfxpayload='" . $self->_grub_single_quote($profile->{grub_gfxpayload_linux}) . "'\n";
                }
                push @profile_lines,
                    "        linux   /vmlinuz-$kernel_version $root_arg ro $root_flags $base_cmdline systemd.setenv=BOOTPROFILE=$profile_name $profile_flags\n",
                    "        initrd  /initrd.img-$kernel_version\n",
                    "    }\n";
            }
            next if !@profile_lines;
            push @snapshot_lines,
                "submenu '" . $self->_grub_single_quote($profile_label)
                . "' --id '${entry_id}_" . $self->_grub_id_fragment($profile_name)
                . "' --class debian --class gnu-linux --class gnu --class os {\n",
                @profile_lines,
                "}\n";
            $has_entries = 1;
        }
        next if !$has_entries;
        push @lines,
            "submenu '" . $self->_grub_single_quote($title)
            . "' --id '$entry_id' --class snapshots --class btrfs --class os {\n",
            @snapshot_lines,
            "}\n\n";
        $rendered = 1;
        ++$count;
        last if $limit > 0 && $count >= $limit;
    }

    if (!$rendered) {
        return $self->_fallback_menu();
    }
    push @lines, <<'GRUB';
menuentry 'Return to main menu' --id 'installer-snapshot-return' --class os {
    configfile $prefix/grub.cfg
}
GRUB
    return join q{}, @lines;
}

sub _install_menu {
    my ($self, $menu) = @_;

    my $checker = $self->_program('grub-script-check');
    my $output = $self->output_file();
    -l $output and die "snapshot menu must not be a symbolic link\n";
    if (-e $output) {
        -f $output or die "snapshot menu must be a regular file\n";
    }
    my $output_dir = dirname($output);
    $self->_ensure_directory($output_dir, 0755);
    my ($fh, $temporary) = tempfile('.grub-btrfs.cfg.XXXXXX', DIR => $output_dir, UNLINK => 0);
    my $ok = eval {
        binmode $fh or die "cannot set snapshot menu encoding: $!\n";
        my $bytes = encode('UTF-8', $menu, FB_CROAK);
        print {$fh} $bytes or die "cannot write generated snapshot menu: $!\n";
        $fh->flush() or die "cannot flush generated snapshot menu: $!\n";
        my ($status) = $self->command()->capture(argv => [ $checker, $temporary ], timeout => 30);
        $status == 0 or die "generated grub-btrfs.cfg failed grub-script-check\n";
        chmod 0644, $temporary or die "cannot set generated snapshot menu mode: $!\n";
        $fh->sync() or die "cannot synchronize generated snapshot menu: $!\n";
        close $fh or die "cannot close generated snapshot menu: $!\n";
        if (-f $output && compare($temporary, $output) == 0) {
            unlink $temporary or die "cannot remove unchanged snapshot menu: $!\n";
            return 1;
        }
        rename $temporary, $output or die "cannot publish generated snapshot menu: $!\n";
        sysopen my $directory, $output_dir, O_RDONLY | O_DIRECTORY | O_NOFOLLOW
            or die "cannot open snapshot menu directory: $!\n";
        $directory->sync() or die "cannot synchronize snapshot menu directory: $!\n";
        close $directory or die "cannot close snapshot menu directory: $!\n";
        return 1;
    };
    my $error = $@;
    if (!$ok) {
        close $fh if defined fileno($fh);
        unlink $temporary if -e $temporary;
        die $error;
    }
    return;
}

sub run {
    my ($self, @argv) = @_;

    local $ENV{PATH} = '/usr/sbin:/usr/bin:/sbin:/bin';
    local $ENV{LC_ALL} = 'C';
    my $result = eval {
        $> == 0 or die "snapshot menu refresh requires root\n";
        @argv <= 1 && (!@argv || $argv[0] eq '--wait')
            or die "unsupported grub-btrfs-refresh mode\n";
        $self->_require_absolute_path('output file', $self->output_file());
        $self->_require_absolute_path('refresh lock file', $self->lock_file());
        my $lock = $self->_acquire_lock();
        return 0 if !$lock;
        $self->_wait_for_timeshift_exit() if @argv && $argv[0] eq '--wait';
        my ($profile, $grub_btrfs) = $self->_load_configurations();
        return 0 if !$profile;
        $self->_validate_profiles($profile);
        return 0 if ($profile->{dev_part_root} // q{}) eq q{} || ($profile->{dev_part_boot} // q{}) eq q{};

        my $snapshot_dir_rel = $grub_btrfs->{GRUB_BTRFS_SNAPSHOT_DIR} // 'timeshift-btrfs/snapshots';
        my $root_subvolume = $grub_btrfs->{GRUB_BTRFS_ROOT_SUBVOLUME} // '@';
        my $snapshot_limit = $grub_btrfs->{GRUB_BTRFS_LIMIT} // 50;
        my $state_dir = $grub_btrfs->{GRUB_BTRFS_STATE_DIR} // '/run/grub-btrfs-refresh';
        $self->_validate_relative_subvolume_path('GRUB_BTRFS_SNAPSHOT_DIR', $snapshot_dir_rel);
        $self->_validate_relative_subvolume_path('GRUB_BTRFS_ROOT_SUBVOLUME', $root_subvolume);
        $state_dir =~ m{\A/run/[A-Za-z0-9._/@%:+,-]+\z}
            or die "GRUB_BTRFS_STATE_DIR must be below /run and contain safe path syntax\n";
        $snapshot_limit =~ /\A[0-9]+\z/ && $snapshot_limit >= 1 && $snapshot_limit <= 200
            or die "GRUB_BTRFS_LIMIT must be between 1 and 200\n";
        $snapshot_limit = int($snapshot_limit);

        my @kernel_images = $self->_bootable_kernel_images();
        if (!@kernel_images) {
            $self->_install_menu($self->_fallback_menu());
            return 0;
        }

        my $root_uuid = $self->_uuid_for_device($profile->{dev_part_root});
        $root_uuid ne q{}
            or die "unable to determine UUID for $profile->{dev_part_root}\n";
        my $boot_uuid = $self->_uuid_for_device($profile->{dev_part_boot});
        $boot_uuid ne q{} or die "unable to determine the boot filesystem UUID\n";
        my $boot_search = "search --no-floppy --fs-uuid --set=root $boot_uuid";
        my $base_cmdline = join q{ },
            map { $profile->{$_} // q{} } qw(
              grub_initramfs_flags grub_nvme_flags grub_systemd_mask_flags grub_cgroup_flags
              grub_security_core_flags grub_blacklist_flags grub_vfio_flags grub_memory_core_flags
              grub_hardening_flags grub_aspm_flags grub_hardware_flags
            );

        $self->_ensure_directory($state_dir, 0700);
        my @state_stat = stat $state_dir;
        @state_stat && $state_stat[4] == $> && !($state_stat[2] & 0077)
            or die "refresh state directory must be private and root-owned\n";
        my $mount_root = "$state_dir/root";
        $self->_cleanup_mount_path($mount_root);
        $self->_ensure_directory($mount_root, 0700);
        my $mounted = 0;
        my $cleanup = sub {
            $self->_cleanup_mount_path($mount_root) if $mounted || -d $mount_root;
            rmdir $state_dir if -d $state_dir && !-l $state_dir;
        };
        my $render_result = eval {
            my ($status) = $self->command()->capture(
                argv => [ $self->_program('mount'), '-t', 'btrfs', '-o',
                    'ro,nosuid,nodev,noexec,subvolid=5',
                    "/dev/disk/by-uuid/$root_uuid", $mount_root ],
                timeout => 30,
            );
            $status == 0
                or die "cannot mount Btrfs top-level subvolume for GRUB snapshot refresh\n";
            $mounted = 1;
            my $snapshot_root = "$mount_root/$snapshot_dir_rel";
            if (!-d $snapshot_root || (realpath($snapshot_root) // q{}) ne $snapshot_root) {
                $self->_install_menu($self->_fallback_menu());
                return 0;
            }
            my $menu = $self->_render_snapshot_menu(
                base_cmdline     => $base_cmdline,
                boot_search      => $boot_search,
                kernel_images    => \@kernel_images,
                limit            => $snapshot_limit,
                profile          => $profile,
                root_arg         => "root=UUID=$root_uuid",
                root_subvolume   => $root_subvolume,
                snapshot_dir_rel => $snapshot_dir_rel,
                snapshot_root    => $snapshot_root,
            );
            $self->_install_menu($menu);
            return 0;
        };
        my $error = $@;
        my $cleaned = eval { $cleanup->(); 1 };
        my $cleanup_error = $@;
        die $error if !$render_result && $error;
        die $cleanup_error if !$cleaned;
        return $render_result;
    };

    if (!$result && $@) {
        my $error = $@;
        $error =~ s/\s+\z//;
        $self->logger()->error($error);
        return 1;
    }
    $self->logger()->info('refreshed GRUB Btrfs snapshot menu') if $result == 0;
    return $result;
}

1;
