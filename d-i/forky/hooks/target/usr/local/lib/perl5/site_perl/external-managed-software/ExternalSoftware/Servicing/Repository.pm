package ExternalSoftware::Servicing::Repository;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Base qw(Str);

use Digest::SHA qw(sha256_hex);
use File::Basename qw(dirname);
use File::Copy qw(copy);
use File::Spec;
use POSIX qw(strftime);
use ExternalSoftware::Servicing::Atomic;
use ExternalSoftware::Servicing::Process;

# Debian normally exposes /etc/os-release as a symlink to this vendor file.
# Keep the strict no-symlink reader and address the canonical regular file.
use constant OS_RELEASE_PATH => '/usr/lib/os-release';

has directory => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/software/debs' },
);

has source => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/apt/sources.list.d/managed-external-software.list' },
);

has release_path => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    default => sub { $_[0]->directory() . '/Release' },
);

has inrelease_path => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    default => sub { $_[0]->directory() . '/InRelease' },
);

has release_signature_path => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    default => sub { $_[0]->directory() . '/Release.gpg' },
);

has signing_home => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/software/repository-signing' },
);

has keyring_path => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/apt/keyrings/managed-external-software.gpg' },
);

has apt_temp_directory => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    default => sub { dirname($_[0]->directory()) . '/apt-tmp' },
);

sub _capture {
    my ($self, @command) = @_;
    open my $fh, '-|', @command or return;
    my $output = do { local $/; <$fh> // q{} };
    close $fh or return;
    return $output;
}

sub _gpg_command {
    my ($self) = @_;
    return (
        '/usr/bin/env', '-i',
        'GNUPGHOME=' . $self->signing_home(),
        'HOME=' . $self->signing_home(),
        'LC_ALL=C.UTF-8',
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        '/usr/bin/gpg',
        '--batch',
        '--no-options',
        '--homedir', $self->signing_home(),
    );
}

sub _run_gpg {
    my ($self, @arguments) = @_;
    system($self->_gpg_command(), @arguments) == 0
        or die "managed repository GPG command failed\n";
    return 1;
}

sub _secret_key_fingerprint {
    my ($self) = @_;
    my $listing = $self->_capture(
        $self->_gpg_command(),
        '--with-colons',
        '--list-secret-keys',
    );
    defined $listing
        or die "managed repository signing key inventory failed\n";
    my ($count, $fingerprint, $want_fingerprint) = (0, undef, 0);
    for my $line (split /\n/, $listing) {
        my @fields = split /:/, $line, -1;
        if (($fields[0] // q{}) eq 'sec') {
            $count++;
            $want_fingerprint = 1;
            next;
        }
        next if !$want_fingerprint || ($fields[0] // q{}) ne 'fpr';
        $fingerprint //= uc($fields[9] // q{});
        $want_fingerprint = 0;
    }
    return (0, undef) if $count == 0;
    $count == 1
        && defined $fingerprint
        && $fingerprint =~ /\A(?:[0-9A-F]{40}|[0-9A-F]{64})\z/
        or die "managed repository signing key inventory is invalid\n";
    return ($count, $fingerprint);
}

sub _prepare_generated_path {
    my ($self, $path) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        'managed repository generated path',
        $path,
    );
    return $path if !-e $path && !-l $path;
    my @st = lstat $path;
    @st && -f _ && !-l _ && $st[4] == 0 && $st[5] == 0 && !($st[2] & 0022)
        or die "managed repository generated path is unsafe: $path\n";
    unlink $path
        or die "managed repository generated path cannot be replaced: $path\n";
    return $path;
}

sub _publish_generated_file {
    my ($self, $temporary, $destination, $mode, $maximum) = @_;
    my @st = lstat $temporary;
    @st && -f _ && !-l _ && $st[4] == 0 && $st[5] == 0
        && $st[7] >= 1 && $st[7] <= $maximum
        or die "managed repository generated file is invalid: $temporary\n";
    if (-e $destination || -l $destination) {
        my @destination_stat = lstat $destination;
        @destination_stat && -f _ && !-l _
            && $destination_stat[4] == 0 && $destination_stat[5] == 0
            && !($destination_stat[2] & 0022)
            or die "managed repository destination is unsafe: $destination\n";
    }
    chmod $mode, $temporary
        or die "managed repository generated file mode cannot be set: $temporary\n";
    rename $temporary, $destination
        or die "managed repository generated file cannot be published: $destination\n";
    return $destination;
}

sub _prepare_apt_temp_directory {
    my ($self) = @_;
    # APT's clear-signature verifier runs as _apt and creates apt.sig/apt.data
    # files under TMPDIR, so do not depend on the global /tmp mode or namespace.
    my $path = ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        'managed repository APT temporary directory',
        $self->apt_temp_directory(),
    );
    ExternalSoftware::Servicing::Atomic->ensure_root_directory(
        dirname($path),
        0755,
    );
    -l $path and die "managed repository APT temporary directory must not be a symlink\n";
    if (!-e $path) {
        mkdir $path, 0700
            or die "managed repository APT temporary directory cannot be created: $!\n";
    }
    -d $path && !-l $path
        or die "managed repository APT temporary path is not a directory\n";

    my @apt_account = getpwnam '_apt';
    @apt_account && defined $apt_account[2]
        or die "managed repository APT sandbox account is unavailable\n";
    my @root_group = getgrnam 'root';
    @root_group && defined $root_group[2]
        or die "managed repository root group is unavailable\n";
    my ($apt_uid, $root_gid) = ($apt_account[2], $root_group[2]);

    chown($apt_uid, $root_gid, $path) == 1
        or die "managed repository APT temporary directory ownership cannot be set: $!\n";
    chmod(0700, $path) == 1
        or die "managed repository APT temporary directory mode cannot be set: $!\n";
    my @st = lstat $path;
    @st && -d _ && !-l _ && $st[4] == $apt_uid && $st[5] == $root_gid
        && ($st[2] & 07777) == 0700
        or die "managed repository APT temporary directory ownership or mode is unsafe\n";
    return $path;
}

sub _ensure_signing_key {
    my ($self) = @_;
    ExternalSoftware::Servicing::Atomic->ensure_root_directory(
        $self->signing_home(),
        0700,
    );
    my @signing_home_stat = lstat $self->signing_home();
    @signing_home_stat && $signing_home_stat[5] == 0
        or die "managed repository signing home must be root-owned\n";
    ExternalSoftware::Servicing::Atomic->ensure_root_directory(
        dirname($self->keyring_path()),
        0755,
    );

    my ($count, $fingerprint) = $self->_secret_key_fingerprint();
    if ($count == 0) {
        $self->_run_gpg(
            '--pinentry-mode', 'loopback',
            '--passphrase', q{},
            '--quick-generate-key',
            'Managed External Software Repository <managed-external-software@localhost>',
            'ed25519',
            'sign',
            '0',
        );
        ($count, $fingerprint) = $self->_secret_key_fingerprint();
    }
    $count == 1 && defined $fingerprint
        or die "managed repository signing key was not created\n";

    my $temporary_keyring = $self->_prepare_generated_path(
        $self->keyring_path() . ".tmp.$$",
    );
    $self->_run_gpg(
        '--output', $temporary_keyring,
        '--export-options', 'export-minimal',
        '--export', $fingerprint,
    );
    $self->_publish_generated_file(
        $temporary_keyring,
        $self->keyring_path(),
        0644,
        1_048_576,
    );
    return $fingerprint;
}

sub _sign_release {
    my ($self) = @_;
    -f $self->release_path() && !-l $self->release_path()
        or die "managed repository Release file is unavailable\n";
    my $fingerprint = $self->_ensure_signing_key();
    my $temporary_inrelease = $self->_prepare_generated_path(
        $self->inrelease_path() . ".tmp.$$",
    );
    my $temporary_signature = $self->_prepare_generated_path(
        $self->release_signature_path() . ".tmp.$$",
    );

    $self->_run_gpg(
        '--yes',
        '--local-user', $fingerprint,
        '--output', $temporary_inrelease,
        '--clearsign', $self->release_path(),
    );
    $self->_run_gpg(
        '--yes',
        '--local-user', $fingerprint,
        '--armor',
        '--output', $temporary_signature,
        '--detach-sign', $self->release_path(),
    );
    system(
        '/usr/bin/gpgv',
        '--quiet',
        '--keyring', $self->keyring_path(),
        $temporary_inrelease,
    ) == 0 or die "managed repository InRelease verification failed\n";
    system(
        '/usr/bin/gpgv',
        '--quiet',
        '--keyring', $self->keyring_path(),
        $temporary_signature,
        $self->release_path(),
    ) == 0 or die "managed repository Release signature verification failed\n";
    $self->_publish_generated_file(
        $temporary_signature,
        $self->release_signature_path(),
        0644,
        1_048_576,
    );
    $self->_publish_generated_file(
        $temporary_inrelease,
        $self->inrelease_path(),
        0644,
        2_097_152,
    );
    return 1;
}

sub _archive_name {
    my ($self, $package, $version, $architecture) = @_;
    for my $component ($package, $version, $architecture) {
        defined $component && length($component) <= 128
            && $component =~ /\A[A-Za-z0-9.+:~_-]+\z/
            or die "managed Debian archive component is invalid\n";
    }
    $architecture eq 'amd64' or die "managed Debian archive architecture is unsupported\n";
    return "${package}_${version}_${architecture}.deb";
}

sub _codename {
    my ($self) = @_;
    my $raw = ExternalSoftware::Servicing::Atomic->read_limited(OS_RELEASE_PATH, 64 * 1024);
    my ($codename) = $raw =~ /^VERSION_CODENAME="?([A-Za-z0-9.+:~_-]+)"?$/m;
    defined $codename && $codename =~ /\A[A-Za-z0-9.+:~_-]+\z/
        or die "managed Debian repository codename is unavailable\n";
    return $codename;
}

sub write_source {
    my ($self) = @_;
    ExternalSoftware::Servicing::Atomic->write_text(
        $self->source(),
        "# Managed by unattended-installer.\n"
        . "# Retained, validated vendor packages permit offline package recovery.\n"
        . "deb [signed-by=" . $self->keyring_path()
        . "] file:/var/lib/software/debs ./\n",
        0644,
    );
    return 1;
}

sub _archive_metadata {
    my ($self, $path) = @_;
    -f $path && !-l $path or die "managed package archive is not a regular file: $path\n";
    my @stat = lstat $path;
    $stat[4] == 0 && !($stat[2] & 0022)
        or die "managed package archive is not root-owned and immutable to non-root: $path\n";
    my $name = $path;
    $name =~ s{.*/}{};
    $name =~ /\A[A-Za-z0-9.+:~_-]+\.deb\z/
        or die "managed package archive name is unsafe: $name\n";
    system('/usr/bin/dpkg-deb', '--info', $path) == 0
        or die "managed package archive is invalid: $name\n";

    my %control;
    for my $field (qw(Package Version Architecture)) {
        my $value = $self->_capture('/usr/bin/dpkg-deb', '-f', $path, $field);
        defined $value or die "managed package archive lacks $field: $name\n";
        chomp $value;
        $control{$field} = $value;
    }
    my $expected = $self->_archive_name(@control{qw(Package Version Architecture)});
    $name eq $expected or die "managed archive name does not match Debian control metadata: $name\n";
    system('/usr/bin/dpkg', '--validate-version', $control{Version}) == 0
        or die "managed package archive version is invalid: $name\n";
    my $control_text = $self->_capture('/usr/bin/dpkg-deb', '-f', $path);
    defined $control_text && $control_text ne q{}
        or die "failed to read managed archive control data: $name\n";
    my ($size, $sha256) = ExternalSoftware::Servicing::Atomic->sha256_file(
        $path,
        536_870_912,
    );
    return {
        path       => $path,
        filename   => $name,
        package    => $control{Package},
        version    => $control{Version},
        arch       => $control{Architecture},
        control    => $control_text,
        size       => $size,
        sha256     => $sha256,
    };
}

sub rebuild {
    my ($self) = @_;
    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->directory(), 0755);
    opendir my $dh, $self->directory()
        or die "failed to read managed package archive directory: $!\n";
    my @archives;
    while (my $entry = readdir $dh) {
        next if $entry eq '.' || $entry eq '..';
        next if $entry !~ /\.deb\z/;
        push @archives, $self->_archive_metadata(File::Spec->catfile($self->directory(), $entry));
    }
    closedir $dh or die "failed to close managed package archive directory: $!\n";
    @archives or die "managed package archive repository is empty\n";
    @archives = sort { $a->{filename} cmp $b->{filename} } @archives;

    my $packages = join q{}, map {
        $_->{control}
            . (substr($_->{control}, -1) eq "\n" ? q{} : "\n")
            . "Filename: ./$_->{filename}\n"
            . "Size: $_->{size}\n"
            . "SHA256: $_->{sha256}\n\n"
    } @archives;
    my $packages_path = File::Spec->catfile($self->directory(), 'Packages');
    ExternalSoftware::Servicing::Atomic->write_text($packages_path, $packages, 0644);
    my $packages_bytes = ExternalSoftware::Servicing::Atomic->read_limited($packages_path, 16 * 1024 * 1024);
    my $codename = $self->_codename();
    my $release = join "\n",
        'Origin: Managed External Software',
        'Label: Managed External Software',
        "Suite: $codename",
        "Codename: $codename",
        'Architectures: amd64',
        'Date: ' . strftime('%a, %d %b %Y %H:%M:%S +0000', gmtime),
        'SHA256:',
        sprintf(' %s %d Packages', sha256_hex($packages_bytes), length($packages_bytes)),
        'Description: Retained validated vendor Debian packages',
        q{};
    ExternalSoftware::Servicing::Atomic->write_text($self->release_path(), $release, 0644);
    $self->_sign_release();
    return scalar @archives;
}

sub refresh {
    my ($self) = @_;
    $self->write_source();
    $self->rebuild();
    my $apt_temp_directory = $self->_prepare_apt_temp_directory();
    system(
        '/usr/bin/env', '-i',
        'DEBIAN_FRONTEND=noninteractive', 'HOME=/root', 'LC_ALL=C.UTF-8',
        'NEEDRESTART_SUSPEND=1',
        'TMPDIR=' . $apt_temp_directory,
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        '/usr/bin/apt-get',
        '-o', 'Dir::Etc::sourcelist=sources.list.d/managed-external-software.list',
        '-o', 'Dir::Etc::sourceparts=-',
        '-o', 'APT::Get::List-Cleanup=false',
        'update',
    ) == 0 or die "managed package repository APT index refresh failed\n";
    return 1;
}

sub retain {
    my ($self, $source, $metadata) = @_;
    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->directory(), 0755);
    -f $source && !-l $source or die "validated Debian package disappeared before retention\n";
    my $name = $self->_archive_name(
        @{$metadata}{qw(package version architecture)},
    );
    my $destination = ExternalSoftware::Servicing::Atomic->assert_child($self->directory(), $name);
    my $created = 0;
    # Bitwarden used to be repacked under the vendor version. A version match
    # must not keep that old archive, nor may apply-only trust an unmarked one.
    my $vendor_digest = $metadata->{package} eq 'bitwarden'
        ? ExternalSoftware::Servicing::Atomic->sha256_file($source, 536_870_912)
        : undef;
    my $replace_vendor = defined($vendor_digest) && -f $destination && !-l $destination
        && $vendor_digest ne ExternalSoftware::Servicing::Atomic->sha256_file(
            $destination, 536_870_912,
        );
    if ((!-e $destination && !-l $destination) || $replace_vendor) {
        my $temporary = "$destination.tmp.$$";
        copy($source, $temporary) or die "failed to retain validated Debian package: $!\n";
        chmod 0644, $temporary or die "failed to set retained package mode: $!\n";
        rename $temporary, $destination or die "failed to publish retained package: $!\n";
        $created = 1;
    } elsif (!-f $destination || -l $destination) {
        die "retained Debian package path is unsafe: $destination\n";
    }
    if (defined $vendor_digest) {
        ExternalSoftware::Servicing::Atomic->write_text(
            "$destination.vendor-sha256", "$vendor_digest\n", 0644,
        );
    }
    $self->refresh();
    return wantarray ? ($destination, $created) : $destination;
}

sub bitwarden_vendor_digest_matches {
    my ($self, $receipt, $digest) = @_;
    defined($digest) && $digest =~ /\A[0-9a-f]{64}\z/
        or die "Bitwarden vendor digest is missing or invalid\n";
    my @st = lstat $receipt;
    return 0 if !@st;
    -f _ && !-l _ && $st[4] == 0 && !($st[2] & 0022)
        or die "Bitwarden vendor receipt is unsafe: $receipt\n";
    return ExternalSoftware::Servicing::Atomic->read_limited($receipt, 65)
        eq "$digest\n";
}

sub latest {
    my ($self, $deb, $spec) = @_;
    ref $spec eq 'HASH'
        && ref $spec->{packages} eq 'ARRAY' && @{$spec->{packages}}
        or die "managed Debian package specification is invalid\n";

    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->directory(), 0755);
    opendir my $dh, $self->directory()
        or die "failed to read retained package directory: $!\n";
    my $candidate;
    while (my $entry = readdir $dh) {
        next if $entry eq '.' || $entry eq '..';
        next if $entry !~ /\A[A-Za-z0-9.+:~_-]+\.deb\z/;
        my $path = File::Spec->catfile($self->directory(), $entry);
        my @st = lstat $path;
        next if !@st || !-f _ || -l _ || $st[4] != 0 || ($st[2] & 0022);
        my $metadata = eval {
            $deb->validate_spec(
                $path,
                $spec,
                "$spec->{label} retained archive",
            );
        };
        next if !$metadata;
        my $vendor_digest;
        if ($spec->{name} eq 'bitwarden') {
            $vendor_digest = ExternalSoftware::Servicing::Atomic->sha256_file(
                $path, 536_870_912,
            );
            next if !$self->bitwarden_vendor_digest_matches(
                "$path.vendor-sha256", $vendor_digest,
            );
        }
        if (!$candidate) {
            $candidate = { path => $path, metadata => $metadata,
                vendor_sha256 => $vendor_digest };
            next;
        }
        my $comparison = system(
            '/usr/bin/dpkg',
            '--compare-versions',
            $metadata->{version},
            'gt',
            $candidate->{metadata}{version},
        );
        if ($comparison == 0) {
            $candidate = { path => $path, metadata => $metadata,
                vendor_sha256 => $vendor_digest };
        } elsif ($comparison != 256) {
            closedir $dh;
            die "managed Debian package version comparison failed\n";
        }
    }
    closedir $dh
        or die "failed to close retained package directory: $!\n";
    return $candidate;
}

sub repair {
    my ($self, $deb, $spec) = @_;
    my @packages = @{$spec->{packages}};
    for my $package (@packages) {
        my $status = $self->_capture('/usr/bin/dpkg-query', '-W', '-f=${Status}', $package) // q{};
        next if $status eq q{} || $status eq 'unknown ok not-installed'
            || $status eq 'deinstall ok config-files' || $status eq 'purge ok not-installed';
        if ($status eq 'install ok installed' && $deb->installed_payload_valid($spec)) {
            return 1;
        }
        my @executables = (
            $spec->{executable},
            @{$spec->{in_use_executables} // []},
        );
        return 0 if ExternalSoftware::Servicing::Process->application_running(
            executables => \@executables,
            roots       => $spec->{in_use_roots} // [],
        );
        my $version = $self->_capture('/usr/bin/dpkg-query', '-W', '-f=${Version}', $package) // q{};
        chomp $version;
        my $archive = eval {
            File::Spec->catfile($self->directory(), $self->_archive_name($package, $version, 'amd64'));
        };
        if (defined $archive && -f $archive && !-l $archive) {
            my $metadata = eval {
                $deb->validate_spec(
                    $archive,
                    $spec,
                    "$spec->{label} retained archive",
                );
            };
            my $repaired = $metadata && eval {
                $self->refresh();
                $deb->install($archive, 1);
                $deb->installed_payload_valid($spec);
            };
            if ($repaired) {
                return 1;
            }
        }
        if ($status ne 'install ok installed') {
            system('/usr/bin/dpkg', '--remove', '--force-remove-reinstreq', $package) == 0
                || system('/usr/bin/dpkg', '--purge', '--force-all', $package) == 0
                or die "$spec->{label} could not be removed from unrecoverable dpkg state\n";
        }
        return 0;
    }
    return 1;
}

1;
