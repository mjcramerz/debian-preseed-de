package TimeshiftManaged::GrubRefresh;

use strict;
use warnings;

use Fcntl qw(:flock O_CREAT O_NOFOLLOW O_WRONLY);
use File::Basename qw(basename dirname);
use File::Temp qw(tempfile);
use JSON::PP qw(decode_json);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Time::HiRes qw(sleep time);
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
    default => sub { '/etc/default/grub-profiles.conf' },
);

has command => (
    is      => 'ro',
    default => sub { TimeshiftManaged::Command->new() },
);

sub _require_absolute_path {
    my ($self, $label, $value) = @_;

    defined($value) && $value =~ m{\A/}
        or die "$label must be an absolute path\n";
    $value !~ m{(?:^|/)\.\.(?:/|$)} && $value !~ m{//}
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
        if ($created || $current eq $directory) {
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
    sysopen my $fh, $self->lock_file(), O_WRONLY | O_CREAT | O_NOFOLLOW, 0600
        or die "cannot open refresh lock " . $self->lock_file() . ": $!\n";
    if (!flock($fh, LOCK_EX | LOCK_NB)) {
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

    my $deadline = time() + 300;
    while ($self->_runtime_snapshot_active()) {
        time() < $deadline
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
    if ($self->_mount_path_is_active($mount_path)) {
        my $status = $self->command()->run($self->_program('umount'), $mount_path);
        if ($status != 0) {
            $self->command()->run($self->_program('umount'), '-l', $mount_path);
        }
    }
    rmdir $mount_path if -d $mount_path && !-l $mount_path;
    return;
}

sub _cleanup_stale_mount_roots {
    my ($self) = @_;

    for my $stale_root (glob('/run/grub-btrfs-refresh.*')) {
        next if !-d $stale_root || -l $stale_root;
        $self->_cleanup_mount_path($stale_root);
    }
    return;
}

sub _load_configurations {
    my ($self) = @_;

    return undef if !-r $self->profile_config() || !-r $self->grub_btrfs_config();
    my $profile = TimeshiftManaged::Config->new(
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
              dualboot_enabled
            )
        ],
        path => $self->profile_config(),
    )->load();
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
    $value !~ m{(?:^|/)\.\.(?:/|$)}
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
        -e "/boot/initrd.img-$version";
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
    );
    return 0 if $status != 0;
    $output =~ s/\s+\z//;
    return $output eq 'ro=false' ? 1 : 0;
}

sub _snapshot_metadata {
    my ($self, $snapshot_dir) = @_;

    my $info_file = "$snapshot_dir/info.json";
    return (q{}, q{}) if !-r $info_file || -l $info_file;
    my @stat = stat $info_file;
    return (q{}, q{}) if !@stat || !-f _ || $stat[7] > 1_048_576;
    open my $fh, '<', $info_file or return (q{}, q{});
    local $/;
    my $raw = <$fh>;
    close $fh;
    my $metadata = eval { decode_json($raw // q{}) };
    return (q{}, q{}) if !$metadata || ref($metadata) ne 'HASH';
    my $tag = ref($metadata->{tags}) ? q{} : ($metadata->{tags} // q{});
    my $comment = ref($metadata->{comments}) ? q{} : ($metadata->{comments} // q{});
    my %labels = (
        B => 'boot',
        D => 'daily',
        H => 'hourly',
        M => 'monthly',
        O => 'ondemand',
        W => 'weekly',
    );
    $tag = $labels{$tag} // $tag;
    $comment =~ s/[\r\n\x00-\x1f\x7f]/ /g;
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

    my $snapshot_subvolume = $snapshot_dir_rel;
    $snapshot_subvolume =~ s{/+\z}{};
    $root_subvolume =~ s{\A/+}{};
    $snapshot_subvolume .= "/$snapshot_name/$root_subvolume";
    if ($grub_root_flags =~ /rootflags=subvol=@,/) {
        $grub_root_flags =~ s/rootflags=subvol=@,/rootflags=subvol=$snapshot_subvolume,/;
        return $grub_root_flags;
    }
    if ($grub_root_flags =~ /rootflags=subvol=@/) {
        $grub_root_flags =~ s/rootflags=subvol=@/rootflags=subvol=$snapshot_subvolume/;
        return $grub_root_flags;
    }
    return "$grub_root_flags rootflags=subvol=$snapshot_subvolume";
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
        next SNAPSHOT if !-d $subvolume || -l $subvolume;
        if (!$self->_snapshot_writable($subvolume)) {
            $self->logger()->warning("ignoring read-only or unreadable Timeshift snapshot: $snapshot_name");
            next;
        }

        my ($tag, $comment) = $self->_snapshot_metadata("$snapshot_root/$snapshot_name");
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
                next if !-d "$subvolume/lib/modules/$kernel_version";
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

    my $output_dir = dirname($self->output_file());
    $self->_ensure_directory($output_dir, 0755);
    my ($fh, $temporary) = tempfile(basename($self->output_file()) . '.XXXXXX', DIR => $output_dir, UNLINK => 0);
    print {$fh} $menu
        or die "cannot write generated grub-btrfs menu: $!\n";
    close $fh or die "cannot close generated grub-btrfs menu: $!\n";
    chmod 0644, $temporary
        or die "cannot set generated grub-btrfs menu mode: $!\n";
    my $checker = $self->command()->find_executable('grub-script-check');
    if ($checker) {
        my $status = $self->command()->run($checker, $temporary);
        $status == 0
            or die "generated grub-btrfs.cfg failed grub-script-check\n";
    }
    rename $temporary, $self->output_file()
        or die "cannot publish generated grub-btrfs menu: $!\n";
    return;
}

sub run {
    my ($self, @argv) = @_;

    my $result = eval {
        @argv <= 1 && (!@argv || $argv[0] eq '--wait')
            or die "unsupported grub-btrfs-refresh mode\n";
        $self->_require_absolute_path('output file', $self->output_file());
        $self->_require_absolute_path('refresh lock file', $self->lock_file());
        my $lock = $self->_acquire_lock();
        return 0 if !$lock;
        $self->_wait_for_timeshift_exit() if @argv && $argv[0] eq '--wait';
        my ($profile, $grub_btrfs) = $self->_load_configurations();
        return 0 if !$profile;
        return 0 if ($profile->{dev_part_root} // q{}) eq q{} || ($profile->{dev_part_boot} // q{}) eq q{};

        my $snapshot_dir_rel = $grub_btrfs->{GRUB_BTRFS_SNAPSHOT_DIR} // 'timeshift-btrfs/snapshots';
        my $root_subvolume = $grub_btrfs->{GRUB_BTRFS_ROOT_SUBVOLUME} // '@';
        my $snapshot_limit = $grub_btrfs->{GRUB_BTRFS_LIMIT} // 50;
        my $state_dir = $grub_btrfs->{GRUB_BTRFS_STATE_DIR} // '/run/grub-btrfs-refresh';
        $self->_validate_relative_subvolume_path('GRUB_BTRFS_SNAPSHOT_DIR', $snapshot_dir_rel);
        $self->_validate_relative_subvolume_path('GRUB_BTRFS_ROOT_SUBVOLUME', $root_subvolume);
        $state_dir =~ m{\A/run/[A-Za-z0-9._/@%:+,-]+\z}
            or die "GRUB_BTRFS_STATE_DIR must be below /run and contain safe path syntax\n";
        $snapshot_limit =~ /\A[0-9]+\z/ && $snapshot_limit <= 200
            or die "GRUB_BTRFS_LIMIT must be numeric and not exceed 200\n";
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
        my $default_version = $kernel_images[0];
        $default_version =~ s{\A/boot/vmlinuz-}{};
        my $boot_search = $boot_uuid ne q{}
            ? "search --no-floppy --fs-uuid --set=root $boot_uuid"
            : "search --no-floppy --file --set=root /vmlinuz-$default_version";
        my $base_cmdline = join q{ },
            map { $profile->{$_} // q{} } qw(
              grub_initramfs_flags grub_nvme_flags grub_systemd_mask_flags grub_cgroup_flags
              grub_security_core_flags grub_blacklist_flags grub_vfio_flags grub_memory_core_flags
              grub_hardening_flags grub_aspm_flags
            );

        $self->_cleanup_stale_mount_roots();
        $self->_ensure_directory($state_dir, 0700);
        my $mount_root = "$state_dir/root";
        $self->_cleanup_mount_path($mount_root);
        $self->_ensure_directory($mount_root, 0700);
        my $mounted = 0;
        my $cleanup = sub {
            $self->_cleanup_mount_path($mount_root) if $mounted || -d $mount_root;
            rmdir $state_dir if -d $state_dir && !-l $state_dir;
        };
        my $render_result = eval {
            my $status = $self->command()->run(
                $self->_program('mount'),
                '-o',
                'ro,subvolid=5',
                "/dev/disk/by-uuid/$root_uuid",
                $mount_root,
            );
            $status == 0
                or die "cannot mount Btrfs top-level subvolume for GRUB snapshot refresh\n";
            $mounted = 1;
            my $snapshot_root = "$mount_root/$snapshot_dir_rel";
            if (!-d $snapshot_root || -l $snapshot_root) {
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
        $cleanup->();
        die $error if !$render_result && $error;
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
