package ExternalSoftware::Servicing::Discord;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Digest::SHA;
use Fcntl qw(:DEFAULT :mode O_CREAT O_EXCL O_NOFOLLOW O_WRONLY);
use File::Copy qw(copy);
use File::Find qw(find);
use File::Path qw(remove_tree);
use JSON::PP qw(decode_json);
use ExternalSoftware::Servicing::Atomic;
use ExternalSoftware::Servicing::Process;
use ExternalSoftware::Servicing::Logger qw(log_msg);

has http  => (is => 'ro', required => 1);
has event => (is => 'ro', required => 1);
has state => (is => 'ro', required => 1);

use constant MANIFEST_URL =>
    'https://updates.discord.com/distributions/app/manifests/latest?channel=stable&platform=linux&arch=x64';
use constant DISTRO_USER_AGENT => 'Discord-Updater/1';
use constant ARCHIVE_HELPER => '/usr/local/libexec/managed-discord-distro';
use constant INSTALL_ROOT => '/opt/discord';
use constant DESKTOP_FILE => '/usr/share/applications/discord.desktop';
use constant HOST_MINIMUM_BYTES => 8 * 1024 * 1024;
use constant HOST_MAXIMUM_BYTES => 314_572_800;
use constant MODULE_MINIMUM_BYTES => 128;
use constant MODULE_MAXIMUM_BYTES => 134_217_728;
use constant RELEASE_MAXIMUM_BYTES => 1_073_741_824;
use constant HOST_TAR_MAXIMUM_BYTES => 1_610_612_736;
use constant MODULE_TAR_MAXIMUM_BYTES => 536_870_912;
use constant HOST_MAXIMUM_MEMBERS => 20_000;
use constant MODULE_MAXIMUM_MEMBERS => 5_000;
use constant TREE_MAXIMUM_FILES => 40_000;
use constant TREE_MAXIMUM_BYTES => 2_147_483_648;
use constant TREE_RESERVED_FILES => 64;
use constant TREE_RESERVED_BYTES => 2_097_152;
my @REQUIRED_MODULES = qw(
    discord_desktop_core
    discord_erlpack
    discord_spellcheck
    discord_utils
    discord_voice
);

sub _keys_exact {
    my ($self, $value, @expected) = @_;
    return 0 if ref $value ne 'HASH';
    return join("\0", sort keys %{$value}) eq join("\0", sort @expected);
}

sub _assert_required_modules {
    my ($self, $modules) = @_;
    ref $modules eq 'HASH'
        or die "Discord module map is invalid\n";
    exists $modules->{$_}
        or die "Discord release omits required module $_\n"
        for @REQUIRED_MODULES;
    return 1;
}

sub _capture_limited {
    my ($self, $limit, @command) = @_;
    $limit =~ /\A[0-9]+\z/ && $limit > 0 && $limit <= 16 * 1024 * 1024
        or die "Discord command output limit is invalid\n";
    open my $fh, '-|', @command
        or die "cannot execute Discord validation command\n";
    binmode $fh, ':raw';
    my $output = q{};
    while (1) {
        my $chunk = q{};
        my $read = read $fh, $chunk, 8192;
        defined $read
            or die "cannot read Discord validation output: $!\n";
        last if $read == 0;
        length($output) + $read <= $limit
            or die "Discord validation output exceeds safe bounds\n";
        $output .= $chunk;
    }
    close $fh
        or die "Discord validation command failed\n";
    return $output;
}

sub _sha256 {
    my ($self, $path) = @_;
    -f $path && !-l $path
        or die "Discord artifact is not a regular file\n";
    open my $fh, '<:raw', $path
        or die "cannot read Discord artifact: $!\n";
    my $digest = Digest::SHA->new(256);
    $digest->addfile($fh);
    close $fh
        or die "cannot close Discord artifact: $!\n";
    return $digest->hexdigest();
}

sub _is_elf {
    my ($self, $path) = @_;
    open my $fh, '<:raw', $path
        or die "cannot inspect Discord executable: $!\n";
    my $header = q{};
    my $read = read $fh, $header, 4;
    defined $read && $read == 4
        or die "cannot read Discord executable header\n";
    close $fh
        or die "cannot close Discord executable inspection: $!\n";
    return $header eq "\x7fELF";
}

sub _canonical_json {
    my ($self, $value) = @_;
    return JSON::PP->new()->canonical(1)->utf8(0)->encode($value);
}

sub failure_detail {
    my ($self) = @_;
    return $self->{failure_detail};
}

sub _clear_failure_detail {
    my ($self) = @_;
    delete $self->{failure_detail};
    return 1;
}

sub _record_failure_detail {
    my ($self, $stage, $error) = @_;
    defined $stage && $stage =~ /\A[a-z0-9]+(?:-[a-z0-9_]+)*\z/
        or die "Discord failure stage is invalid\n";
    $error = 'unknown failure' if !defined $error || $error eq q{};
    $error =~ s/[\r\n]+/ /g;
    $error =~ s/[\x00-\x1f\x7f]/?/g;
    $error =~ s/[[:space:]]+/ /g;
    $error =~ s/\A[[:space:]]+//;
    $error =~ s/[[:space:]]+\z//;
    $error = substr($error, 0, 512);
    my $detail = "$stage: $error";
    $self->{failure_detail} = $detail;
    my $message = "Discord staging failed at $detail";
    print STDERR "[managed-external-software-update] error: $message\n";
    log_msg('error', $message);
    return $detail;
}

sub _helper_json {
    my ($self, @arguments) = @_;
    -x ARCHIVE_HELPER && !-l ARCHIVE_HELPER
        or die "Discord archive helper is unavailable\n";
    my $raw = $self->_capture_limited(
        2 * 1024 * 1024,
        ARCHIVE_HELPER,
        @arguments,
    );
    $raw =~ /\n\z/
        or die "Discord archive helper output is malformed\n";
    my $value = eval { decode_json($raw) };
    !$@ && ref $value eq 'HASH'
        or die "Discord archive helper returned invalid JSON\n";
    return $value;
}

sub _manifest {
    my ($self, $path) = @_;
    my $release = $self->_helper_json('manifest', '--path', $path);
    $self->_validate_release_metadata($release);
    return $release;
}

sub _decompress {
    my ($self, $source, $destination, $limit) = @_;
    -f $source && !-l $source
        or die "Discord distribution is not a regular file\n";
    $limit =~ /\A[0-9]+\z/ && $limit > 0
        or die "Discord decompression limit is invalid\n";
    unlink $destination if -e $destination || -l $destination;
    sysopen my $output, $destination, O_CREAT | O_EXCL | O_NOFOLLOW | O_WRONLY, 0600
        or die "cannot create Discord decompressed tar: $!\n";
    binmode $output, ':raw';
    open my $input, '-|', '/usr/bin/brotli', '--decompress', '--stdout', $source
        or die "cannot execute Discord Brotli decompression\n";
    binmode $input, ':raw';
    my $bytes = 0;
    my $failed;
    while (1) {
        my $chunk = q{};
        my $read = read $input, $chunk, 1024 * 1024;
        if (!defined $read) {
            $failed = "cannot read Discord Brotli output: $!";
            last;
        }
        last if $read == 0;
        $bytes += $read;
        if ($bytes > $limit) {
            $failed = 'Discord decompressed tar exceeds safe bounds';
            last;
        }
        print {$output} $chunk
            or do {
                $failed = "cannot write Discord decompressed tar: $!";
                last;
            };
    }
    close $output
        or $failed //= "cannot close Discord decompressed tar: $!";
    my $decompress_ok = close $input;
    if (defined $failed || !$decompress_ok) {
        unlink $destination;
        die((defined $failed ? $failed : 'Discord Brotli decompression failed') . "\n");
    }
    if ($bytes < 1024) {
        unlink $destination;
        die "Discord decompressed tar is unexpectedly small\n";
    }
    return $destination;
}

sub _archive_arguments {
    my ($self, $command, $tar, $kind, $version, $module_name, $module_version, $destination) = @_;
    my @arguments = (
        $command,
        '--path', $tar,
        '--kind', $kind,
        '--version', $version,
    );
    if ($kind eq 'module') {
        push @arguments,
            '--module-name', $module_name,
            '--module-version', $module_version;
    }
    push @arguments, '--destination', $destination if defined $destination;
    return @arguments;
}

sub _validate_distribution_metadata {
    my ($self, $metadata, $kind) = @_;
    my ($member_limit, $byte_limit) = $kind eq 'host'
        ? (HOST_MAXIMUM_MEMBERS, HOST_TAR_MAXIMUM_BYTES)
        : $kind eq 'module'
            ? (MODULE_MAXIMUM_MEMBERS, MODULE_TAR_MAXIMUM_BYTES)
            : die "unsupported Discord distribution kind\n";
    $self->_keys_exact(
        $metadata,
        qw(filesystem_entries members regular_files unpacked_bytes),
    )
        or die "Discord archive helper metadata is invalid\n";
    for my $field (qw(filesystem_entries members regular_files unpacked_bytes)) {
        defined $metadata->{$field}
            && !ref $metadata->{$field}
            && $metadata->{$field} =~ /\A[0-9]+\z/
            or die "Discord archive helper metadata is invalid\n";
    }
    $metadata->{members} >= 1
        && $metadata->{members} <= $member_limit
        && $metadata->{regular_files} >= 1
        && $metadata->{regular_files} <= $metadata->{filesystem_entries}
        && $metadata->{filesystem_entries} <= $member_limit
        && $metadata->{unpacked_bytes} >= 1
        && $metadata->{unpacked_bytes} <= $byte_limit
        or die "Discord archive helper metadata is outside approved bounds\n";
    return $metadata;
}

sub _accumulate_distribution_bounds {
    my ($self, $totals, $metadata) = @_;
    $totals->{files} += $metadata->{filesystem_entries};
    $totals->{bytes} += $metadata->{unpacked_bytes};
    $totals->{files} <= TREE_MAXIMUM_FILES - TREE_RESERVED_FILES
        or die "Discord release expanded file count exceeds safe bounds\n";
    $totals->{bytes} <= TREE_MAXIMUM_BYTES - TREE_RESERVED_BYTES
        or die "Discord release expanded size exceeds safe bounds\n";
    return $totals;
}

sub _inspect_distribution {
    my ($self, $source, $tar, $kind, $version, $module_name, $module_version) = @_;
    my $limit = $kind eq 'host' ? HOST_TAR_MAXIMUM_BYTES : MODULE_TAR_MAXIMUM_BYTES;
    $self->_decompress($source, $tar, $limit);
    my $metadata = eval {
        $self->_helper_json(
            $self->_archive_arguments(
                'inspect',
                $tar,
                $kind,
                $version,
                $module_name,
                $module_version,
                undef,
            ),
        );
    };
    my $error = $@;
    unlink $tar;
    die $error if $error;
    return $self->_validate_distribution_metadata($metadata, $kind);
}

sub _extract_distribution {
    my ($self, $source, $tar, $destination, $kind, $version, $module_name, $module_version) = @_;
    my $limit = $kind eq 'host' ? HOST_TAR_MAXIMUM_BYTES : MODULE_TAR_MAXIMUM_BYTES;
    $self->_decompress($source, $tar, $limit);
    my $metadata = eval {
        $self->_helper_json(
            $self->_archive_arguments(
                'extract',
                $tar,
                $kind,
                $version,
                $module_name,
                $module_version,
                $destination,
            ),
        );
    };
    my $error = $@;
    unlink $tar;
    die $error if $error;
    return $self->_validate_distribution_metadata($metadata, $kind);
}

sub _validate_release_metadata {
    my ($self, $release) = @_;
    $self->_keys_exact(
        $release,
        qw(host modules required_modules version),
    )
        && defined $release->{version}
        && $release->{version} =~ /\A[0-9]+(?:\.[0-9]+){2}\z/
        && $self->_keys_exact($release->{host}, qw(sha256 url))
        && defined $release->{host}->{url}
        && defined $release->{host}->{sha256}
        && $release->{host}->{sha256} =~ /\A[0-9a-f]{64}\z/
        && ref $release->{modules} eq 'HASH'
        && ref $release->{required_modules} eq 'ARRAY'
        && keys(%{$release->{modules}}) >= 5
        && keys(%{$release->{modules}}) <= 32
        or die "Discord release metadata is invalid\n";
    my %required;
    for my $name (@{$release->{required_modules}}) {
        defined $name
            && $name =~ /\Adiscord_[a-z0-9_]{1,64}\z/
            && !$required{$name}
            && exists $release->{modules}->{$name}
            or die "Discord required-module metadata is invalid\n";
        $required{$name} = 1;
    }
    $self->_assert_required_modules(\%required);
    for my $name (keys %{$release->{modules}}) {
        my $module = $release->{modules}->{$name};
        $name =~ /\Adiscord_[a-z0-9_]{1,64}\z/
            && $self->_keys_exact(
                $module,
                qw(required sha256 url version),
            )
            && JSON::PP::is_bool($module->{required})
            && !!$module->{required} == !!$required{$name}
            && defined $module->{url}
            && defined $module->{version}
            && $module->{version} =~ /\A[0-9]+\z/
            && $module->{version} >= 1
            && $module->{version} <= 999_999
            && defined $module->{sha256}
            && $module->{sha256} =~ /\A[0-9a-f]{64}\z/
            or die "Discord module release metadata is invalid\n";
    }
    return 1;
}

sub _artifact_record {
    my ($self, $release, $manifest_path, $host_path, $module_paths) = @_;
    my $version = $release->{version};
    my $manifest_sha256 = $self->_sha256($manifest_path);
    my $manifest_name = "discord-$version-manifest-$manifest_sha256.json";
    my $host_sha256 = $release->{host}->{sha256};
    my $host_name = "discord-$version-host-$host_sha256.full.distro";
    my %modules;
    for my $name (sort keys %{$release->{modules}}) {
        my $module = $release->{modules}->{$name};
        my $sha256 = $module->{sha256};
        $modules{$name} = {
            file    => "discord-$version-$name-$module->{version}-$sha256.full.distro",
            path    => $module_paths->{$name},
            sha256  => $sha256,
            version => 0 + $module->{version},
        };
    }
    return {
        version  => $version,
        manifest => {
            file   => $manifest_name,
            path   => $manifest_path,
            sha256 => $manifest_sha256,
        },
        host => {
            file   => $host_name,
            path   => $host_path,
            sha256 => $host_sha256,
        },
        modules => \%modules,
    };
}

sub _state_record {
    my ($self, $release) = @_;
    my %modules = map {
        my $module = $release->{modules}->{$_};
        $_ => {
            file    => $module->{file},
            sha256  => $module->{sha256},
            version => 0 + $module->{version},
        }
    } sort keys %{$release->{modules}};
    return {
        version  => $release->{version},
        manifest => {
            file   => $release->{manifest}->{file},
            sha256 => $release->{manifest}->{sha256},
        },
        host => {
            file   => $release->{host}->{file},
            sha256 => $release->{host}->{sha256},
        },
        modules => \%modules,
    };
}

sub _validate_state_record {
    my ($self, $release) = @_;
    $self->_keys_exact(
        $release,
        qw(host manifest modules version),
    )
        && defined $release->{version}
        && $release->{version} =~ /\A[0-9]+(?:\.[0-9]+){2}\z/
        && $self->_keys_exact($release->{manifest}, qw(file sha256))
        && $self->_keys_exact($release->{host}, qw(file sha256))
        && ref $release->{modules} eq 'HASH'
        && keys(%{$release->{modules}}) >= 5
        && keys(%{$release->{modules}}) <= 32
        or die "stored Discord release state is invalid\n";
    $self->_assert_required_modules($release->{modules});
    my $version = $release->{version};
    my $manifest_sha256 = $release->{manifest}->{sha256} // q{};
    my $host_sha256 = $release->{host}->{sha256} // q{};
    $manifest_sha256 =~ /\A[0-9a-f]{64}\z/
        && $host_sha256 =~ /\A[0-9a-f]{64}\z/
        && ($release->{manifest}->{file} // q{})
            eq "discord-$version-manifest-$manifest_sha256.json"
        && ($release->{host}->{file} // q{})
            eq "discord-$version-host-$host_sha256.full.distro"
        or die "stored Discord host state is invalid\n";
    for my $name (keys %{$release->{modules}}) {
        my $module = $release->{modules}->{$name};
        my $sha256 = $self->_keys_exact(
            $module,
            qw(file sha256 version),
        ) ? ($module->{sha256} // q{}) : q{};
        my $module_version = ref $module eq 'HASH' ? ($module->{version} // q{}) : q{};
        $name =~ /\Adiscord_[a-z0-9_]{1,64}\z/
            && $sha256 =~ /\A[0-9a-f]{64}\z/
            && $module_version =~ /\A[0-9]+\z/
            && $module_version >= 1
            && $module_version <= 999_999
            && ($module->{file} // q{})
                eq "discord-$version-$name-$module_version-$sha256.full.distro"
            or die "stored Discord module state is invalid\n";
    }
    return $release;
}

sub _read_release_state {
    my ($self, $name) = @_;
    my $raw = $self->state()->read_state($name, 1_048_576);
    return undef if !defined $raw;
    $raw =~ /\n\z/
        or die "stored Discord state is malformed\n";
    my $release = eval { decode_json($raw) };
    !$@ && ref $release eq 'HASH'
        or die "stored Discord state is invalid JSON\n";
    return $self->_validate_state_record($release);
}

sub _installed { return $_[0]->_read_release_state('discord.installed.json'); }
sub _pending   { return $_[0]->_read_release_state('discord.pending.json'); }

sub _write_release_state {
    my ($self, $name, $release) = @_;
    my $state_record = $self->_state_record($release);
    $self->_validate_state_record($state_record);
    return $self->state()->write_state(
        $name,
        $self->_canonical_json($state_record) . "\n",
    );
}

sub _version_compare {
    my ($self, $left, $operator, $right) = @_;
    my $result = system('/usr/bin/dpkg', '--compare-versions', $left, $operator, $right);
    return 1 if $result == 0;
    return 0 if $result == 256;
    die "Discord version comparison failed\n";
}

sub _assert_non_downgrade {
    my ($self, $candidate, $installed) = @_;
    return 1 if !defined $installed;
    if ($self->_version_compare($candidate->{version}, 'lt', $installed->{version})) {
        die "Discord release would downgrade the installed host\n";
    }
    return 1 if $candidate->{version} ne $installed->{version};
    $candidate->{host}->{sha256} eq $installed->{host}->{sha256}
        or die "Discord host digest changed without a version change\n";
    for my $name (keys %{$installed->{modules}}) {
        exists $candidate->{modules}->{$name}
            or die "Discord release removed an installed module without a host update\n";
        my $new = $candidate->{modules}->{$name};
        my $old = $installed->{modules}->{$name};
        $new->{version} >= $old->{version}
            or die "Discord module release would downgrade an installed module\n";
        if ($new->{version} == $old->{version}) {
            $new->{sha256} eq $old->{sha256}
                or die "Discord module digest changed without a module version change\n";
        }
    }
    return 1;
}

sub _download_release {
    my ($self, $work) = @_;
    my $manifest_path = "$work/discord-stable-manifest.json";
    $self->http()->download(
        label          => 'Discord stable distribution manifest',
        url            => MANIFEST_URL,
        destination    => $manifest_path,
        minimum        => 256,
        maximum        => 1_048_576,
        allowed_hosts  => ['updates.discord.com'],
        content_policy => 'metadata',
        user_agent     => DISTRO_USER_AGENT,
    );
    my $metadata = $self->_manifest($manifest_path);
    my $version = $metadata->{version};

    my $host_path = "$work/discord-$version-host.full.distro";
    $self->http()->download(
        label          => 'Discord stable host distribution',
        url            => $metadata->{host}->{url},
        destination    => $host_path,
        minimum        => HOST_MINIMUM_BYTES,
        maximum        => HOST_MAXIMUM_BYTES,
        allowed_hosts  => [qw(dl.discordapp.net stable.dl2.discordapp.net)],
        content_policy => 'artifact',
        user_agent     => DISTRO_USER_AGENT,
    );
    $self->_sha256($host_path) eq $metadata->{host}->{sha256}
        or die "Discord host distribution digest does not match the manifest\n";
    my $expanded = {
        bytes => 0,
        files => 0,
    };
    my $host_metadata = $self->_inspect_distribution(
        $host_path,
        "$work/discord-$version-host.tar",
        'host',
        $version,
        undef,
        undef,
    );
    $self->_accumulate_distribution_bounds($expanded, $host_metadata);

    my %module_paths;
    my $release_bytes = -s $host_path;
    for my $name (sort keys %{$metadata->{modules}}) {
        my $module = $metadata->{modules}->{$name};
        my $module_path = "$work/discord-$version-$name-$module->{version}.full.distro";
        $self->http()->download(
            label          => "Discord $name module",
            url            => $module->{url},
            destination    => $module_path,
            minimum        => MODULE_MINIMUM_BYTES,
            maximum        => MODULE_MAXIMUM_BYTES,
            allowed_hosts  => [qw(dl.discordapp.net stable.dl2.discordapp.net)],
            content_policy => 'artifact',
            user_agent     => DISTRO_USER_AGENT,
        );
        $self->_sha256($module_path) eq $module->{sha256}
            or die "Discord $name module digest does not match the manifest\n";
        my $module_metadata = $self->_inspect_distribution(
            $module_path,
            "$work/discord-$version-$name.tar",
            'module',
            $version,
            $name,
            $module->{version},
        );
        $self->_accumulate_distribution_bounds($expanded, $module_metadata);
        $release_bytes += -s $module_path;
        $release_bytes <= RELEASE_MAXIMUM_BYTES
            or die "Discord release artifacts exceed retained size bounds\n";
        $module_paths{$name} = $module_path;
    }
    return $self->_artifact_record(
        $metadata,
        $manifest_path,
        $host_path,
        \%module_paths,
    );
}

sub _retain_release {
    my ($self, $release) = @_;
    my $created = 0;
    for my $artifact (
        $release->{manifest},
        $release->{host},
        map { $release->{modules}->{$_} } sort keys %{$release->{modules}}
    ) {
        my (undef, $stored) = $self->state()->retain_artifact(
            'discord',
            $artifact->{path},
            $artifact->{file},
        );
        $self->_retained_path($artifact);
        $created ||= $stored;
    }
    return $created;
}

sub _retained_path {
    my ($self, $record) = @_;
    my $path = $self->state()->artifact_path('discord', $record->{file});
    -f $path && !-l $path
        or die "retained Discord artifact is unavailable\n";
    my @st = lstat $path;
    @st && $st[4] == 0 && $st[5] == 0 && !($st[2] & 0022)
        or die "retained Discord artifact ownership or mode is unsafe\n";
    $self->_sha256($path) eq $record->{sha256}
        or die "retained Discord artifact digest is invalid\n";
    return $path;
}

sub _assert_runtime {
    my ($self, $root, $release) = @_;
    my @root_st = lstat $root;
    @root_st
        or die "cannot inspect managed Discord runtime root $root: $!\n";
    my $root_mode = sprintf '%04o', $root_st[2] & 07777;
    S_ISDIR($root_st[2])
        or die "managed Discord runtime root is unsafe: $root "
            . "(mode $root_mode, expected a directory with mode 0755)\n";
    my ($count, $bytes) = (0, 0);
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                my $path = $File::Find::name;
                my @st = lstat $path;
                @st
                    or die "cannot inspect managed Discord runtime path $path: $!\n";
                my $mode = $st[2];
                my $actual_mode = sprintf '%04o', $mode & 07777;
                S_ISLNK($mode)
                    and die "managed Discord runtime contains a symlink: "
                        . "$path (mode $actual_mode)\n";
                if ($path ne $root) {
                    $count++;
                    $count <= TREE_MAXIMUM_FILES
                        or die "managed Discord runtime exceeds file-count bounds "
                            . "at $path\n";
                }
                if (S_ISREG($mode)) {
                    $st[4] == 0 && $st[5] == 0
                        or die "managed Discord runtime ownership is unsafe: "
                            . "$path (uid $st[4], gid $st[5], mode $actual_mode; "
                            . "expected uid 0, gid 0)\n";
                    my $expected_mode =
                        $path eq "$root/chrome-sandbox"
                        ? 04755
                        : $path eq "$root/Discord"
                            || $path eq "$root/chrome_crashpad_handler"
                        ? 0755
                        : ($mode & 0111 ? 0755 : 0644);
                    ($mode & 07777) == $expected_mode
                        or die "managed Discord runtime file mode is unsafe: "
                            . "$path (mode $actual_mode, expected "
                            . sprintf('%04o', $expected_mode) . ")\n";
                    $bytes += $st[7];
                    $bytes <= TREE_MAXIMUM_BYTES
                        or die "managed Discord runtime exceeds size bounds "
                            . "at $path\n";
                    return;
                }
                S_ISDIR($mode)
                    or die "managed Discord runtime contains an unsupported "
                        . "object: $path (mode $actual_mode)\n";
                $st[4] == 0 && $st[5] == 0
                    or die "managed Discord runtime ownership is unsafe: "
                        . "$path (uid $st[4], gid $st[5], mode $actual_mode; "
                        . "expected uid 0, gid 0)\n";
                ($mode & 07777) == 0755
                    or die "managed Discord runtime directory mode is unsafe: "
                        . "$path (mode $actual_mode, expected 0755)\n";
            },
        },
        $root,
    );
    for my $file (
        qw(
            Discord
            chrome-sandbox
            chrome_crashpad_handler
            discord.png
            libffmpeg.so
            modules/installed.json
            .managed-release
        )
    ) {
        -f "$root/$file" && !-l "$root/$file"
            or die "managed Discord runtime is missing $file\n";
    }
    -x "$root/Discord"
        && -x "$root/chrome_crashpad_handler"
        && -u "$root/chrome-sandbox"
        && -x "$root/chrome-sandbox"
        && $self->_is_elf("$root/Discord")
        && $self->_is_elf("$root/chrome-sandbox")
        && $self->_is_elf("$root/chrome_crashpad_handler")
        or die "managed Discord runtime executables are invalid\n";

    my $installed_modules = eval {
        decode_json(
            ExternalSoftware::Servicing::Atomic->read_limited(
                "$root/modules/installed.json",
                1_048_576,
            ),
        );
    };
    !$@ && ref $installed_modules eq 'HASH'
        or die "managed Discord module metadata is invalid\n";
    $self->_assert_required_modules($installed_modules);
    my %expected_modules = map {
        $_ => { installedVersion => 0 + $release->{modules}->{$_}->{version} }
    } sort keys %{$release->{modules}};
    $self->_canonical_json($installed_modules) eq $self->_canonical_json(\%expected_modules)
        or die "managed Discord module metadata does not match retained artifacts\n";
    for my $name (keys %expected_modules) {
        -d "$root/modules/$name" && !-l "$root/modules/$name"
            or die "managed Discord runtime is missing module $name\n";
    }

    my $managed_release = ExternalSoftware::Servicing::Atomic->read_limited(
        "$root/.managed-release",
        4096,
    );
    my $module_count = scalar keys %expected_modules;
    $managed_release eq join(
        q{},
        "channel=stable\n",
        "version=$release->{version}\n",
        "manifest_sha256=$release->{manifest}->{sha256}\n",
        "host_sha256=$release->{host}->{sha256}\n",
        "architecture=amd64\n",
        "modules=$module_count\n",
    ) or die "managed Discord release marker is invalid\n";
    return 1;
}

sub runtime_valid {
    my ($self, $release) = @_;
    $release //= $self->_installed();
    return 0 if !defined $release;
    return eval { $self->_assert_runtime(INSTALL_ROOT, $release); 1 } ? 1 : 0;
}

sub _set_root_owner {
    my ($self, $path) = @_;
    chown(0, 0, $path) == 1
        or die "failed to set Discord runtime ownership on $path: $!\n";
    return 1;
}

sub _normalize_tree {
    my ($self, $root) = @_;
    my @root_st = lstat $root;
    @root_st
        or die "cannot inspect Discord staging root $root: $!\n";
    my $root_mode = sprintf '%04o', $root_st[2] & 07777;
    S_ISDIR($root_st[2])
        or die "Discord staging root is unsafe: $root "
            . "(mode $root_mode, expected a directory)\n";
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                my $path = $File::Find::name;
                my @st = lstat $path;
                @st
                    or die "cannot inspect Discord staged runtime path $path: $!\n";
                my $mode = $st[2];
                my $actual_mode = sprintf '%04o', $mode & 07777;
                S_ISLNK($mode)
                    and die "Discord staged runtime contains a symlink: "
                        . "$path (mode $actual_mode)\n";
                my $normalized_mode;
                if (S_ISDIR($mode)) {
                    $normalized_mode = 0755;
                } elsif (S_ISREG($mode)) {
                    $normalized_mode = $mode & 0111 ? 0755 : 0644;
                } else {
                    die "Discord staged runtime contains an unsupported object: "
                        . "$path (mode $actual_mode)\n";
                }
                $self->_set_root_owner($path);
                chmod($normalized_mode, $path) == 1
                    or die "failed to set Discord runtime mode on $path to "
                        . sprintf('%04o', $normalized_mode) . ": $!\n";
            },
        },
        $root,
    );
    for my $executable (qw(Discord chrome_crashpad_handler)) {
        my $path = "$root/$executable";
        chmod(0755, $path) == 1
            or die "failed to configure Discord executable $path mode 0755: $!\n";
    }
    my $sandbox = "$root/chrome-sandbox";
    chmod(04755, $sandbox) == 1
        or die "failed to configure Discord Chromium sandbox $sandbox "
            . "mode 4755: $!\n";
    return 1;
}

sub _prepare_module_root {
    my ($self, $staged) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        'Discord staging root',
        $staged,
    );
    -d $staged && !-l $staged
        or die "Discord staging root is unavailable\n";
    my $modules = "$staged/modules";
    # The retained manifest module archives are authoritative. Rebuild this
    # subtree even when the independently verified host archive bundles module
    # payloads so host copies can never override the separately verified set.
    if (-e $modules || -l $modules) {
        -d $modules && !-l $modules
            or die "Discord host supplied an unsafe module staging path\n";
        $self->_remove_tree_checked($modules);
    }
    mkdir $modules, 0755
        or die "cannot create Discord module staging directory: $!\n";
    chmod 0755, $modules
        or die "cannot configure Discord module staging directory: $!\n";
    return $modules;
}

sub _remove_tree_checked {
    my ($self, $path) = @_;
    return 1 if !-e $path && !-l $path;
    -d $path && !-l $path
        or die "refusing to remove an unsafe Discord publication path\n";
    remove_tree($path, { safe => 1, error => \my $errors });
    @{$errors}
        and die "failed to remove a Discord publication path\n";
    return 1;
}

sub _recover_publication_state {
    my ($self, $old) = @_;
    my $install = INSTALL_ROOT;
    my $backup = '/opt/.discord.previous';
    return 1 if !-e $backup && !-l $backup;
    defined $old
        or die "Discord publication backup exists without installed release state\n";
    -d $backup && !-l $backup
        or die "Discord publication backup is unsafe\n";

    my $install_is_old = -d $install
        && !-l $install
        && eval { $self->_assert_runtime($install, $old); 1 };
    if ($install_is_old) {
        $self->_remove_tree_checked($backup);
        return 1;
    }

    $self->_assert_runtime($backup, $old);
    if (-e $install || -l $install) {
        -d $install && !-l $install
            or die "Discord interrupted publication left an unsafe install path\n";
        $self->_remove_tree_checked($install);
    }
    rename $backup, $install
        or die "failed to restore the previous Discord runtime: $!\n";
    $self->_assert_runtime($install, $old);
    return 1;
}

sub _rollback {
    my ($self, $install, $backup, $old, $had_install) = @_;
    (-l $install || -l $backup)
        and die "refusing to roll back a symlinked Discord installation\n";
    if ($had_install) {
        -d $backup && !-l $backup
            or die "Discord rollback backup is unavailable\n";
        $self->_assert_runtime($backup, $old) if defined $old;
    }
    $self->_remove_tree_checked($install);
    if ($had_install) {
        rename $backup, $install
            or die "failed to restore the previous Discord installation: $!\n";
        $self->_assert_runtime($install, $old) if defined $old;
    }
    if ($old) {
        $self->_write_release_state('discord.installed.json', $old);
    } else {
        $self->state()->delete_state('discord.installed.json');
    }
}

sub _publish {
    my ($self, $work, $release, $old, $repository_stage) = @_;
    $self->_clear_failure_detail();
    my $version = $release->{version};
    my $host = $self->_retained_path($release->{host});
    $self->_retained_path($release->{manifest});
    my %module_paths = map {
        $_ => $self->_retained_path($release->{modules}->{$_})
    } keys %{$release->{modules}};

    my $expanded = {
        bytes => 0,
        files => 0,
    };
    my $host_metadata = eval {
        $self->_inspect_distribution(
            $host,
            "$work/discord-$version-host.tar",
            'host',
            $version,
            undef,
            undef,
        );
    };
    return (1, 'validation') if !$host_metadata;
    eval {
        $self->_accumulate_distribution_bounds($expanded, $host_metadata);
        for my $name (sort keys %module_paths) {
            my $module_metadata = $self->_inspect_distribution(
                $module_paths{$name},
                "$work/discord-$version-$name.tar",
                'module',
                $version,
                $name,
                $release->{modules}->{$name}->{version},
            );
            $self->_accumulate_distribution_bounds($expanded, $module_metadata);
        }
        1;
    } or return (1, 'validation');

    my $staged = $repository_stage // "/opt/.discord.new.$$";
    my $backup = '/opt/.discord.previous';
    return (1, 'publish') if -l $staged || -l $backup;
    eval {
        $self->_recover_publication_state($old) if !defined $repository_stage;
        $self->_remove_tree_checked($staged);
        1;
    } or return (1, 'publish');
    mkdir $staged, 0700
        or return (1, 'publish');

    my $stage = 'host-extract';
    my $extracted = eval {
        $self->_extract_distribution(
            $host,
            "$work/discord-$version-host.tar",
            $staged,
            'host',
            $version,
            undef,
            undef,
        );
        $stage = 'module-root';
        my $modules_root = $self->_prepare_module_root($staged);
        for my $name (sort keys %module_paths) {
            $stage = "module-$name";
            my $destination = "$modules_root/$name";
            mkdir $destination, 0755
                or die "cannot create Discord module directory: $!\n";
            $self->_extract_distribution(
                $module_paths{$name},
                "$work/discord-$version-$name.tar",
                $destination,
                'module',
                $version,
                $name,
                $release->{modules}->{$name}->{version},
            );
        }
        $stage = 'module-metadata';
        my %installed_modules = map {
            $_ => { installedVersion => 0 + $release->{modules}->{$_}->{version} }
        } sort keys %{$release->{modules}};
        ExternalSoftware::Servicing::Atomic->write_text(
            "$modules_root/installed.json",
            $self->_canonical_json(\%installed_modules) . "\n",
            0644,
        );
        $stage = 'release-metadata';
        my $module_count = scalar keys %installed_modules;
        ExternalSoftware::Servicing::Atomic->write_text(
            "$staged/.managed-release",
            join(
                q{},
                "channel=stable\n",
                "version=$version\n",
                "manifest_sha256=$release->{manifest}->{sha256}\n",
                "host_sha256=$release->{host}->{sha256}\n",
                "architecture=amd64\n",
                "modules=$module_count\n",
            ),
            0644,
        );
        $stage = 'normalize';
        $self->_normalize_tree($staged);
        $stage = 'runtime-validation';
        $self->_assert_runtime($staged, $release);
        1;
    };
    my $extract_error = $@;
    if (!$extracted) {
        $self->_record_failure_detail($stage, $extract_error);
        eval { $self->_remove_tree_checked($staged); 1 };
        return (1, 'extract');
    }

    return (0, 'staged') if defined $repository_stage;

    my $install = INSTALL_ROOT;
    my $had_install = -e $install || -l $install;
    if ($had_install) {
        -d $install && !-l $install
            or return (1, 'publish');
        rename $install, $backup
            or return (1, 'publish');
    }
    if (!rename $staged, $install) {
        if ($had_install) {
            rename $backup, $install
                or die "failed to restore Discord after publication failure: $!\n";
        }
        return (1, 'publish');
    }
    my $published = eval {
        $self->_write_release_state('discord.installed.json', $release);
        $self->_assert_runtime($install, $release);
        -f DESKTOP_FILE && !-l DESKTOP_FILE
            or die "Discord desktop entry is unavailable\n";
        system('/usr/bin/desktop-file-validate', DESKTOP_FILE) == 0
            or die "Discord desktop entry validation failed\n";
        1;
    };
    if (!$published) {
        $self->_rollback($install, $backup, $old, $had_install);
        return (1, 'postinstall');
    }
    $self->_remove_tree_checked($backup) if -d $backup;
    $self->state()->delete_state('discord.pending.json');
    system('/usr/bin/update-desktop-database', '/usr/share/applications');
    return (0, 'updated');
}

sub fetch {
    my ($self, $work) = @_;
    my $release = eval { $self->_download_release($work) };
    return (1, $@ =~ /download|HTTP|URL/i ? 'download' : 'validation') if !$release;
    my $installed = eval { $self->_installed() };
    return (1, 'validation') if $@;
    eval { $self->_assert_non_downgrade($release, $installed); 1 }
        or return (1, 'downgrade');

    my $state_release = $self->_state_record($release);
    if ($installed
        && $self->_canonical_json($state_release) eq $self->_canonical_json($installed)
        && $self->runtime_valid($installed))
    {
        $self->state()->delete_state('discord.pending.json');
        return (2, 'current');
    }
    my $previous_pending = eval { $self->_pending() };
    return (1, 'validation') if $@;
    my $created = eval { $self->_retain_release($release) };
    return (1, 'publish') if $@;
    $self->_write_release_state('discord.pending.json', $release);
    $self->event()->emit(
        'downloaded',
        'discord',
        $installed ? $installed->{version} : 'not-installed',
        $release->{version},
    ) if $created || !defined $previous_pending
        || $self->_canonical_json($previous_pending) ne $self->_canonical_json($state_release);
    return (0, 'downloaded');
}

sub apply {
    my ($self, $work) = @_;
    my $pending = eval { $self->_pending() };
    return (1, 'validation') if $@;
    my $installed = eval { $self->_installed() };
    return (1, 'validation') if $@;
    my $installed_runtime_valid = defined $installed
        && $self->runtime_valid($installed);

    if (!defined $pending) {
        return (1, 'missing') if !defined $installed;
        return (2, 'current') if $installed_runtime_valid;
        eval {
            $self->_retained_path($installed->{manifest});
            $self->_retained_path($installed->{host});
            $self->_retained_path($installed->{modules}->{$_})
                for keys %{$installed->{modules}};
            1;
        } or return (1, 'validation');
        $self->_write_release_state('discord.pending.json', $installed);
        $pending = $installed;
    }
    eval { $self->_assert_non_downgrade($pending, $installed); 1 } or do {
        $self->state()->delete_state('discord.pending.json')
            if $installed && $self->_version_compare(
                $pending->{version},
                'lt',
                $installed->{version},
            );
        return (1, 'downgrade');
    };
    if ($installed
        && $self->_canonical_json($pending) eq $self->_canonical_json($installed)
        && $installed_runtime_valid)
    {
        $self->state()->delete_state('discord.pending.json');
        return (2, 'current');
    }
    return (1, 'in-use') if ExternalSoftware::Servicing::Process->application_running(
        executables => [INSTALL_ROOT . '/Discord'],
        roots       => [INSTALL_ROOT],
    );

    $self->event()->emit(
        'applying',
        'discord',
        $installed ? $installed->{version} : 'not-installed',
        $pending->{version},
    );
    my ($result, $reason) = $self->_publish(
        $work,
        $pending,
        $installed_runtime_valid ? $installed : undef,
    );
    if ($result == 0) {
        $self->event()->emit(
            'updated',
            'discord',
            $installed ? $installed->{version} : 'not-installed',
            $pending->{version},
        );
    }
    return ($result, $reason);
}

sub repair {
    my ($self, $work) = @_;
    my $installed = eval { $self->_installed() };
    return (1, 'validation') if $@;
    return (1, 'missing') if !defined $installed;
    return (2, 'current') if $self->runtime_valid($installed);
    eval {
        $self->_retained_path($installed->{manifest});
        $self->_retained_path($installed->{host});
        $self->_retained_path($installed->{modules}->{$_})
            for keys %{$installed->{modules}};
        1;
    } or return (1, 'validation');
    $self->_write_release_state('discord.pending.json', $installed);
    return $self->apply($work);
}

sub bootstrap {
    my ($self, $work) = @_;
    $self->_clear_failure_detail();
    my ($fetch_result, $fetch_reason) = $self->fetch($work);
    return ($fetch_result, $fetch_reason) if $fetch_result == 1;
    my ($apply_result, $apply_reason) = $self->apply($work);
    return ($apply_result, $apply_reason) if $apply_result == 1;
    my $installed = $self->_installed();
    return (1, 'postinstall') if !$installed || !$self->runtime_valid($installed);
    return (0, 'updated');
}

1;
