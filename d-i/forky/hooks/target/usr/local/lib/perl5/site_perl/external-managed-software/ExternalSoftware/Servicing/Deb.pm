package ExternalSoftware::Servicing::Deb;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Fcntl qw(O_NOFOLLOW O_RDONLY O_TRUNC O_WRONLY S_IFMT S_IFREG);
use File::Spec;
use POSIX qw(_exit);
use ExternalSoftware::Servicing::Atomic;

has repository => (is => 'ro', required => 1);

sub _capture {
    my ($self, @command) = @_;
    open my $fh, '-|', @command or return;
    my $output = do { local $/; <$fh> // q{} };
    close $fh or return;
    return $output;
}

sub _capture_limited {
    my ($self, $maximum, @command) = @_;
    defined $maximum && $maximum =~ /\A[1-9][0-9]*\z/
        or die "command output limit is invalid\n";
    open my $fh, '-|', @command or return;
    binmode $fh;
    my $output = q{};
    while (1) {
        my $read = read $fh, my $chunk, 65_536;
        if (!defined $read) {
            close $fh;
            return;
        }
        last if $read == 0;
        if (length($output) + $read > $maximum) {
            close $fh;
            die "command output exceeds its limit\n";
        }
        $output .= $chunk;
    }
    close $fh or return;
    return $output;
}

sub _capture_quiet {
    my ($self, @command) = @_;
    return if !@command;

    my $pid = open my $fh, '-|';
    return if !defined $pid;
    if ($pid == 0) {
        open STDERR, '>', File::Spec->devnull()
            or _exit(127);
        exec { $command[0] } @command or _exit(127);
    }

    my $output = do { local $/; <$fh> // q{} };
    close $fh or return;
    return $output;
}

sub control {
    my ($self, $path, $field) = @_;
    my $value = $self->_capture('/usr/bin/dpkg-deb', '-f', $path, $field);
    return undef if !defined $value;
    chomp $value;
    return $value;
}

sub _archive_identity {
    my ($self, $path) = @_;
    my @st = lstat $path;
    return if !@st || ($st[2] & S_IFMT) != S_IFREG || -l _;
    return join "\0", @st[0, 1, 7, 9, 10];
}

sub _archive_listing {
    my ($self, $path) = @_;
    my $identity = $self->_archive_identity($path);
    return if !defined $identity;
    my $cached = $self->{archive_listing_cache}->{$path};
    if (defined $cached && $cached->{identity} eq $identity) {
        return $cached->{content};
    }
    my $listing = $self->_capture_limited(
        16 * 1024 * 1024,
        '/usr/bin/dpkg-deb',
        '-c',
        $path,
    );
    return if !defined $listing;
    $listing !~ /\0/
        or die "Debian package listing contains invalid data\n";
    $self->{archive_listing_cache}->{$path} = {
        identity => $identity,
        content  => $listing,
    };
    return $listing;
}

sub _listing_mode {
    my ($self, $listing, $wanted) = @_;
    my @modes;
    for my $entry (split /\n/, $listing) {
        next if $entry !~ /(?:\A|\s)\.\Q$wanted\E(?:\s+->\s+\S+)?\z/;
        my ($mode) = $entry =~ /\A(\S+)\s+/;
        push @modes, $mode if defined $mode && length($mode) == 10;
    }
    return if @modes != 1;
    return $modes[0];
}

sub _listing_contains {
    my ($self, $listing, $wanted) = @_;
    return defined $self->_listing_mode($listing, $wanted) ? 1 : 0;
}

sub _contains {
    my ($self, $path, $wanted) = @_;
    my $listing = $self->_archive_listing($path);
    return 0 if !defined $listing;
    return $self->_listing_contains($listing, $wanted);
}

sub _contains_executable {
    my ($self, $path, $wanted) = @_;
    my $listing = $self->_archive_listing($path);
    return 0 if !defined $listing;
    my $mode = $self->_listing_mode($listing, $wanted);
    return 0 if !defined $mode;
    return 1 if substr($mode, 0, 1) eq 'l';
    return substr($mode, 0, 1) eq '-'
        && substr($mode, 9, 1) =~ /[xt]/ ? 1 : 0;
}

sub _installed_executable_valid {
    my ($self, $path) = @_;
    return 0 if !-e $path;
    my @st = stat $path;
    return 0 if !@st || ($st[2] & S_IFMT) != S_IFREG;
    return 0 if $st[4] != 0 || $st[5] != 0 || ($st[2] & 0022);
    return ($st[2] & 0001) ? 1 : 0;
}

sub _sandbox_presence {
    my ($self, $presence) = @_;
    $presence //= 'required';
    $presence eq 'required' || $presence eq 'optional'
        or die "Chromium sandbox presence must be required or optional\n";
    return $presence;
}

sub chromium_sandbox_valid {
    my ($self, $path, $presence) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path('Chromium sandbox', $path);
    $presence = $self->_sandbox_presence($presence);

    if (!-e $path && !-l $path) {
        return $presence eq 'optional' ? 1 : 0;
    }
    return 0 if -l $path;
    my @st = lstat $path;
    return 0 if !@st || ($st[2] & S_IFMT) != S_IFREG;
    return 0 if $st[4] != 0 || $st[5] != 0;
    return ($st[2] & 07777) == 04755 ? 1 : 0;
}

sub repair_chromium_sandbox {
    my ($self, $path, $presence) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path('Chromium sandbox', $path);
    $presence = $self->_sandbox_presence($presence);

    if (!-e $path && !-l $path) {
        return 1 if $presence eq 'optional';
        die "required Chromium sandbox is missing: $path\n";
    }
    -f $path && !-l $path
        or die "Chromium sandbox is not a regular file: $path\n";
    chown 0, 0, $path
        or die "failed to set Chromium sandbox ownership: $path: $!\n";
    chmod 04755, $path
        or die "failed to set Chromium sandbox mode: $path: $!\n";
    $self->chromium_sandbox_valid($path, $presence)
        or die "Chromium sandbox has unsafe ownership or mode: $path\n";
    return 1;
}

sub _dependency_exclusions {
    my ($self, $patterns) = @_;
    ref $patterns eq 'ARRAY' && @{$patterns}
        or die "Debian dependency exclusion policy is invalid\n";
    my %seen;
    my @validated;
    for my $pattern (@{$patterns}) {
        defined $pattern
            && length($pattern) <= 128
            && (
                $pattern =~ /\A[a-z0-9][a-z0-9+.-]*\*?\z/
                || $pattern =~ /\A\*[a-z0-9][a-z0-9+.-]*\*\z/
            )
            or die "Debian dependency exclusion pattern is invalid\n";
        !$seen{$pattern}++
            or die "Debian dependency exclusion pattern is duplicated\n";
        push @validated, $pattern;
    }
    return \@validated;
}

sub _dependency_name {
    my ($self, $alternative) = @_;
    $alternative =~ s/\A[ \t]+//;
    $alternative =~ s/[ \t]+\z//;
    $alternative ne q{}
        or die "Debian dependency alternative is empty\n";
    return undef if $alternative =~ /\A\$\{[A-Za-z0-9:+.-]+\}\z/;
    my ($name) = $alternative =~
        /\A([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9][a-z0-9-]*)?(?=[ \t]|\(|\[|<|\z)/;
    defined $name
        or die "Debian dependency alternative is invalid: $alternative\n";
    return $name;
}

sub _dependency_is_excluded {
    my ($self, $name, $patterns) = @_;
    return 0 if !defined $name;
    for my $pattern (@{$patterns}) {
        if (substr($pattern, 0, 1) eq '*') {
            my $fragment = substr($pattern, 1, -1);
            return 1 if index($name, $fragment) >= 0;
        } elsif (substr($pattern, -1, 1) eq '*') {
            my $prefix = substr($pattern, 0, -1);
            return 1 if index($name, $prefix) == 0;
        } elsif ($name eq $pattern) {
            return 1;
        }
    }
    return 0;
}

sub _filter_dependency_value {
    my ($self, $value, $patterns) = @_;
    defined $value && $value !~ /[\r\n\0]/
        or die "Debian dependency field is invalid\n";
    $patterns = $self->_dependency_exclusions($patterns);

    $value =~ s/\A[ \t]+//;
    $value =~ s/[ \t]+\z//;
    return (q{}, 0) if $value eq q{};

    my @relations;
    my $removed = 0;
    for my $relation (split /,/, $value, -1) {
        $relation =~ s/\A[ \t]+//;
        $relation =~ s/[ \t]+\z//;
        $relation ne q{}
            or die "Debian dependency relation is empty\n";
        my @alternatives;
        for my $alternative (split /\|/, $relation, -1) {
            $alternative =~ s/\A[ \t]+//;
            $alternative =~ s/[ \t]+\z//;
            my $name = $self->_dependency_name($alternative);
            if ($self->_dependency_is_excluded($name, $patterns)) {
                $removed++;
                next;
            }
            push @alternatives, $alternative;
        }
        push @relations, join(' | ', @alternatives) if @alternatives;
    }
    return (join(', ', @relations), $removed);
}

sub dependencies_allowed {
    my ($self, $value, $patterns) = @_;
    defined $value or return 0;
    my (undef, $excluded) = $self->_filter_dependency_value($value, $patterns);
    return $excluded == 0 ? 1 : 0;
}

sub installed_dependencies_allowed {
    my ($self, $package, $patterns) = @_;
    defined $package && $package =~ /\A[a-z0-9][a-z0-9+.-]{0,127}\z/
        or die "installed dependency package name is invalid\n";
    my $depends = $self->_capture_quiet(
        '/usr/bin/dpkg-query',
        '-W',
        '-f=${Depends}',
        $package,
    );
    return 0 if !defined $depends;
    return $self->dependencies_allowed($depends, $patterns);
}

sub _rewrite_control_dependencies {
    my ($self, $control, $patterns) = @_;
    defined $control
        && length($control) <= 1_048_576
        && $control !~ /[\r\0]/
        or die "Debian control file is invalid\n";

    my @lines = split /\n/, $control, -1;
    my @rewritten;
    my $depends_fields = 0;
    my $removed = 0;
    for (my $index = 0; $index < @lines;) {
        my $line = $lines[$index];
        if ($line =~ /\ADepends:[ \t]*(.*)\z/i) {
            $depends_fields++;
            $depends_fields == 1
                or die "Debian control file contains multiple Depends fields\n";
            my @parts = ($1);
            $index++;
            while ($index < @lines && $lines[$index] =~ /\A[ \t](.*)\z/) {
                push @parts, $1;
                $index++;
            }
            my ($filtered, $count) = $self->_filter_dependency_value(
                join(' ', @parts),
                $patterns,
            );
            $removed += $count;
            push @rewritten, "Depends: $filtered" if $filtered ne q{};
            next;
        }
        push @rewritten, $line;
        $index++;
    }
    my $rewritten = join "\n", @rewritten;
    return wantarray ? ($rewritten, $removed) : $rewritten;
}

sub _control_archive_member {
    my ($self, $path) = @_;
    my $content = $self->_capture(
        '/usr/bin/ar',
        't',
        $path,
    );
    defined $content
        or die "Debian control archive member is unavailable\n";
    for my $member (split /\n/, $content) {
        return $member
            if $member =~ /\Acontrol\.tar(?:\.(?:gz|xz|zst))?\z/;
    }
    die "Debian control archive member is unavailable\n";
}

sub _control_compression_args {
    my ($self, $member) = @_;
    return () if $member eq 'control.tar';
    return ('--gzip') if $member eq 'control.tar.gz';
    return ('--xz') if $member eq 'control.tar.xz';
    return ('--zstd') if $member eq 'control.tar.zst';
    die "Debian control archive compression is unsupported\n";
}

sub repack_without_dependencies {
    my ($self, %args) = @_;
    for my $key (qw(label path work name dependencies)) {
        exists $args{$key} or die "missing Debian repack parameter $key\n";
    }
    defined $args{label} && $args{label} =~ /\A[^\r\n\0]{1,128}\z/
        or die "Debian repack label is invalid\n";
    defined $args{name} && $args{name} =~ /\A[a-z0-9][a-z0-9+.-]{0,63}\z/
        or die "Debian repack name is invalid\n";
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        "$args{label} source package",
        $args{path},
    );
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        "$args{label} repack workspace",
        $args{work},
    );
    -f $args{path} && !-l $args{path}
        or die "$args{label} source package is not a regular file\n";
    -d $args{work} && !-l $args{work}
        or die "$args{label} repack workspace is not a directory\n";
    my @work_stat = lstat $args{work};
    @work_stat && $work_stat[4] == $> && !($work_stat[2] & 0022)
        or die "$args{label} repack workspace is unsafe\n";
    my $patterns = $self->_dependency_exclusions($args{dependencies});
    my $control_member = $self->_control_archive_member($args{path});
    my $control_root = ExternalSoftware::Servicing::Atomic->assert_child(
        $args{work},
        "$args{name}.control-root",
    );
    my $control_archive = ExternalSoftware::Servicing::Atomic->assert_child(
        $args{work},
        $control_member,
    );
    my $output = ExternalSoftware::Servicing::Atomic->assert_child(
        $args{work},
        "$args{name}.repacked.deb",
    );
    (!-e $control_root && !-l $control_root
        && !-e $control_archive && !-l $control_archive
        && !-e $output && !-l $output)
        or die "$args{label} repack paths already exist\n";
    mkdir $control_root, 0755
        or die "$args{label} control repack directory cannot be created: $!\n";

    system(
        '/usr/bin/env', '-i',
        'LC_ALL=C.UTF-8',
        "TMPDIR=$args{work}",
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        '/usr/bin/dpkg-deb',
        '--control',
        $args{path},
        $control_root,
    ) == 0 or die "$args{label} control archive extraction failed\n";
    my @control_root_stat = lstat $control_root;
    @control_root_stat
        && -d _
        && !-l _
        && $control_root_stat[4] == $>
        && !($control_root_stat[2] & 0022)
        or die "$args{label} extracted control directory is unsafe\n";
    my $control_path = File::Spec->catfile($control_root, 'control');
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        "$args{label} extracted control file",
        $control_path,
    );
    my @control_stat = lstat $control_path;
    @control_stat
        && ($control_stat[2] & S_IFMT) == S_IFREG
        && !-l _
        && $control_stat[4] == $>
        && !($control_stat[2] & 0022)
        or die "$args{label} extracted control file is unsafe\n";
    my $control = ExternalSoftware::Servicing::Atomic->read_limited(
        $control_path,
        1_048_576,
    );
    my $rewritten = $self->_rewrite_control_dependencies(
        $control,
        $patterns,
    );
    sysopen my $control_fh, $control_path, O_WRONLY | O_TRUNC | O_NOFOLLOW
        or die "$args{label} extracted control file cannot be opened: $!\n";
    binmode $control_fh;
    print {$control_fh} $rewritten
        or die "$args{label} extracted control file cannot be written: $!\n";
    close $control_fh
        or die "$args{label} extracted control file cannot be closed: $!\n";
    chmod 0644, $control_path
        or die "$args{label} extracted control mode cannot be set: $!\n";

    my @compression = $self->_control_compression_args($control_member);
    system(
        '/usr/bin/env', '-i',
        'LC_ALL=C.UTF-8',
        "TMPDIR=$args{work}",
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        '/usr/bin/tar',
        '--format=gnu',
        '--sort=name',
        '--owner=0',
        '--group=0',
        '--numeric-owner',
        '--mtime=@0',
        @compression,
        '--create',
        '--file', $control_archive,
        '--directory', $control_root,
        '.',
    ) == 0 or die "$args{label} control archive rebuild failed\n";
    chmod 0600, $control_archive
        or die "$args{label} rebuilt control archive mode cannot be set: $!\n";
    my @control_archive_stat = lstat $control_archive;
    @control_archive_stat
        && ($control_archive_stat[2] & S_IFMT) == S_IFREG
        && !-l _
        && $control_archive_stat[4] == $>
        && $control_archive_stat[7] > 0
        && $control_archive_stat[7] <= 16 * 1024 * 1024
        && !($control_archive_stat[2] & 0022)
        or die "$args{label} rebuilt control archive is unsafe\n";
    rename $args{path}, $output
        or die "$args{label} package workspace rename failed: $!\n";
    system(
        '/usr/bin/env', '-i',
        'LC_ALL=C.UTF-8',
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        '/usr/bin/ar',
        'rD',
        $output,
        $control_archive,
    ) == 0 or die "$args{label} control member replacement failed\n";
    chmod 0600, $output
        or die "$args{label} repacked package mode cannot be set: $!\n";
    -f $output && !-l $output
        or die "$args{label} repacked package is not a regular file\n";
    my @output_stat = lstat $output;
    @output_stat && $output_stat[4] == $> && !($output_stat[2] & 0022)
        or die "$args{label} repacked package is unsafe\n";
    my $depends = $self->control($output, 'Depends');
    if (defined $depends && $depends ne q{}) {
        my ($remaining_value, $remaining) = $self->_filter_dependency_value(
            $depends,
            $patterns,
        );
        $remaining == 0
            or die "$args{label} repacked package retains excluded dependencies\n";
    }
    return $output;
}

sub validate {
    my ($self, %args) = @_;
    for my $key (qw(label path packages executable desktop)) {
        exists $args{$key} or die "missing Debian artifact parameter $key\n";
    }
    ExternalSoftware::Servicing::Atomic->assert_absolute_path("$args{label} package", $args{path});
    my @package_stat = lstat $args{path};
    @package_stat
        && ($package_stat[2] & S_IFMT) == S_IFREG
        && !-l _
        && $package_stat[7] >= 8
        && $package_stat[7] <= 536_870_912
        or die "$args{label} package is not a bounded regular file\n";
    sysopen my $package_fh, $args{path}, O_RDONLY | O_NOFOLLOW
        or die "$args{label} package cannot be opened: $!\n";
    binmode $package_fh;
    my $magic = q{};
    my $magic_read = read $package_fh, $magic, 8;
    close $package_fh
        or die "$args{label} package cannot be closed: $!\n";
    defined $magic_read && $magic_read == 8 && $magic eq "!<arch>\n"
        or die "$args{label} does not have Debian archive framing\n";
    system('/usr/bin/dpkg-deb', '--info', $args{path}) == 0
        or die "$args{label} is not a valid Debian package\n";
    my $validate_payload = defined $args{validate_payload}
        ? $args{validate_payload}
        : 1;
    $validate_payload == 0 || $validate_payload == 1
        or die "$args{label} payload validation flag is invalid\n";
    if ($validate_payload) {
        my $listing = $self->_archive_listing($args{path});
        defined $listing
            or die "$args{label} package payload listing is unavailable\n";
        $self->_listing_contains($listing, $args{executable})
            or die "$args{label} package is missing its expected executable\n";
        $self->_listing_contains($listing, $args{desktop})
            or die "$args{label} package is missing its expected desktop entry\n";
        if (defined $args{library} && $args{library} ne q{}) {
            $self->_listing_contains($listing, $args{library})
                or die "$args{label} package is missing its expected runtime library\n";
        }
        for my $required_path (@{$args{required_paths} // []}) {
            ExternalSoftware::Servicing::Atomic->assert_absolute_path(
                "$args{label} required payload path",
                $required_path,
            );
            $self->_listing_contains($listing, $required_path)
                or die "$args{label} package is missing required payload: $required_path\n";
        }
        for my $required_executable (@{$args{required_executables} // []}) {
            ExternalSoftware::Servicing::Atomic->assert_absolute_path(
                "$args{label} required executable payload",
                $required_executable,
            );
            my $mode = $self->_listing_mode($listing, $required_executable);
            defined $mode
                && (
                    substr($mode, 0, 1) eq 'l'
                    || (
                        substr($mode, 0, 1) eq '-'
                        && substr($mode, 9, 1) =~ /[xt]/
                    )
                )
                or die "$args{label} package is missing required executable payload: $required_executable\n";
        }
        if (defined $args{sandbox} && $args{sandbox} ne q{}) {
            ExternalSoftware::Servicing::Atomic->assert_absolute_path(
                "$args{label} Chromium sandbox",
                $args{sandbox},
            );
            my $presence = $self->_sandbox_presence($args{sandbox_presence});
            if ($presence eq 'required') {
                $self->_listing_contains($listing, $args{sandbox})
                    or die "$args{label} package is missing its required Chromium sandbox\n";
            }
        }
    }
    my $package = $self->control($args{path}, 'Package');
    my $version = $self->control($args{path}, 'Version');
    my $architecture = $self->control($args{path}, 'Architecture');
    defined $package && grep { $_ eq $package } @{$args{packages}}
        or die "$args{label} package name is unapproved\n";
    defined $version && system('/usr/bin/dpkg', '--validate-version', $version) == 0
        or die "$args{label} package version is invalid\n";
    defined $architecture && $architecture eq 'amd64'
        or die "$args{label} package architecture is not amd64\n";
    return { package => $package, version => $version, architecture => $architecture };
}

sub validate_spec {
    my ($self, $path, $spec, $label) = @_;
    ref $spec eq 'HASH'
        or die "managed Debian package specification is invalid\n";
    $label //= $spec->{label};
    return $self->validate(
        label                => $label,
        path                 => $path,
        packages             => $spec->{packages},
        executable           => $spec->{executable},
        desktop              => $spec->{desktop},
        library              => $spec->{library},
        sandbox              => $spec->{sandbox},
        sandbox_presence     => $spec->{sandbox_presence},
        validate_payload     => $spec->{validate_payload},
        required_paths       => $spec->{required_paths},
        required_executables => $spec->{required_executables},
    );
}

sub installed_payload_valid {
    my ($self, $spec) = @_;
    ref $spec eq 'HASH'
        or die "managed Debian package specification is invalid\n";
    return 0 if !$self->_installed_executable_valid($spec->{executable});
    return 0 if !-r $spec->{desktop};
    return 0 if defined $spec->{library} && $spec->{library} ne q{} && !-r $spec->{library};
    for my $required_path (@{$spec->{required_paths} // []}) {
        return 0 if !-r $required_path;
    }
    for my $required_executable (@{$spec->{required_executables} // []}) {
        return 0 if !$self->_installed_executable_valid($required_executable);
    }
    return 1 if !defined $spec->{sandbox} || $spec->{sandbox} eq q{};
    return $self->chromium_sandbox_valid(
        $spec->{sandbox},
        $spec->{sandbox_presence},
    );
}

sub installed_version {
    my ($self, $package) = @_;
    my $status = $self->_capture_quiet(
        '/usr/bin/dpkg-query',
        '-W',
        '-f=${Status}',
        $package,
    );
    return undef if !defined $status || $status ne 'install ok installed';
    my $version = $self->_capture_quiet(
        '/usr/bin/dpkg-query',
        '-W',
        '-f=${Version}',
        $package,
    );
    return undef if !defined $version || system('/usr/bin/dpkg', '--validate-version', $version) != 0;
    return $version;
}

sub install {
    my ($self, $path, $reinstall) = @_;
    $reinstall //= 0;
    $reinstall == 0 || $reinstall == 1
        or die "managed Debian package reinstall flag is invalid\n";
    my @reinstall_args = $reinstall ? ('--reinstall') : ();
    system(
        '/usr/bin/env', '-i',
        'DEBIAN_FRONTEND=noninteractive', 'DEBCONF_NONINTERACTIVE_SEEN=true',
        'HOME=/root', 'LC_ALL=C.UTF-8', 'NEEDRESTART_SUSPEND=1',
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        '/usr/bin/apt-get', '-y', '-o', 'Acquire::Retries=3',
        '-o', 'Acquire::http::Timeout=30', '-o', 'Acquire::https::Timeout=30',
        '-o', 'DPkg::Lock::Timeout=120', '-o', 'DPkg::Use-Pty=0',
        '-o', 'APT::Get::AllowUnauthenticated=false',
        '-o', 'APT::Get::Allow-Downgrades=false',
        '-o', 'APT::Get::Allow-Remove-Essential=false',
        '-o', 'APT::Get::Allow-Change-Held-Packages=false',
        '--no-remove', '--no-install-recommends', '--no-install-suggests',
        @reinstall_args,
        'install', $path,
    ) == 0 or die "APT could not install the validated Debian package\n";
    return 1;
}

1;
