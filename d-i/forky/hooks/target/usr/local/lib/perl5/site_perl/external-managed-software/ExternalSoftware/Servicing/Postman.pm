package ExternalSoftware::Servicing::Postman;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Digest::SHA;
use File::Copy qw(copy);
use File::Find qw(find);
use File::Path qw(remove_tree);
use JSON::PP qw(decode_json);
use ExternalSoftware::Servicing::Atomic;
use ExternalSoftware::Servicing::Process;

has http  => (is => 'ro', required => 1);
has event => (is => 'ro', required => 1);
has state => (is => 'ro', required => 1);

sub _capture_limited {
    my ($self, $limit, @command) = @_;
    $limit =~ /\A[0-9]+\z/ && $limit > 0 && $limit <= 16 * 1024 * 1024
        or die "Postman command output limit is invalid\n";
    open my $fh, '-|', @command
        or die "cannot execute Postman archive inspection\n";
    binmode $fh, ':raw';
    my $output = q{};
    while (1) {
        my $chunk = q{};
        my $read = read $fh, $chunk, 8192;
        defined $read
            or die "cannot read Postman archive inspection output: $!\n";
        last if $read == 0;
        length($output) + $read <= $limit
            or die "Postman archive inspection output exceeds safe bounds\n";
        $output .= $chunk;
    }
    close $fh
        or die "Postman archive inspection failed\n";
    return $output;
}

sub _sha256 {
    my ($self, $path) = @_;
    -f $path && !-l $path
        or die "Postman archive is not a regular file\n";
    open my $fh, '<:raw', $path
        or die "cannot read Postman archive: $!\n";
    my $digest = Digest::SHA->new(256);
    $digest->addfile($fh);
    close $fh
        or die "cannot close Postman archive: $!\n";
    return $digest->hexdigest();
}

sub _is_elf {
    my ($self, $path) = @_;
    open my $fh, '<:raw', $path
        or die "cannot inspect Postman executable: $!\n";
    my $header = q{};
    read $fh, $header, 4;
    close $fh
        or die "cannot close Postman executable inspection: $!\n";
    return $header eq "\x7fELF";
}

sub _entries {
    my ($self, $archive) = @_;
    my $listing = $self->_capture_limited(
        2 * 1024 * 1024,
        '/usr/bin/tar',
        '--list',
        '--gzip',
        '--file',
        $archive,
    );
    $listing =~ /\n\z/
        or die "Postman archive listing is malformed\n";
    my @entries = split /\n/, $listing, -1;
    pop @entries;
    @entries && @entries <= 5000
        or die "Postman archive has an unsafe member count\n";
    my %seen;
    for my $entry (@entries) {
        length($entry) && length($entry) <= 512
            && $entry !~ /[[:space:]\\]/
            && $entry !~ m{\A/}
            && $entry !~ m{(?:\A|/)\.\.(?:/|\z)}
            && $entry =~ m{\APostman(?:/|\z)}
            && !$seen{$entry}++
            or die "Postman archive contains an unsafe member path\n";
    }
    for my $required (
        qw(
            Postman/Postman
            Postman/app/Postman
            Postman/app/chrome-sandbox
            Postman/app/libffmpeg.so
            Postman/app/resources/app/assets/icon.png
            Postman/app/resources/app/package.json
        )
    ) {
        $seen{$required}
            or die "Postman archive is missing $required\n";
    }
    return \@entries;
}

sub _release {
    my ($self, $archive) = @_;
    my $json = $self->_capture_limited(
        1_048_576,
        '/usr/bin/tar',
        '--extract',
        '--gzip',
        '--to-stdout',
        '--file',
        $archive,
        'Postman/app/resources/app/package.json',
    );
    my $package = eval { decode_json($json) };
    !$@ && ref $package eq 'HASH'
        or die "Postman release metadata is invalid\n";
    my $version = $package->{version};
    defined $version && $version =~ /\A[0-9]+(?:\.[0-9]+)+\z/ && length($version) <= 64
        or die "Postman release version is invalid\n";
    return $version;
}

sub validate {
    my ($self, $archive) = @_;
    -f $archive && !-l $archive
        or die "Postman archive is not a regular file\n";
    my $size = -s $archive;
    defined $size && $size >= 1_048_576 && $size <= 314_572_800
        or die "Postman archive size is outside approved bounds\n";
    $self->_entries($archive);
    return {
        version => $self->_release($archive),
        sha256  => $self->_sha256($archive),
        size    => $size,
    };
}

sub _installed {
    my ($self) = @_;
    my $raw = $self->state()->read_state('postman.installed', 256);
    return undef if !defined $raw;
    my ($version, $sha256) = $raw =~ /\A([0-9]+(?:\.[0-9]+)+)\|([0-9a-f]{64})\n\z/
        or die "stored Postman installation state is invalid\n";
    return { version => $version, sha256 => $sha256 };
}

sub _pending {
    my ($self) = @_;
    my $raw = $self->state()->read_state('postman.pending', 256);
    return undef if !defined $raw;
    my ($version, $sha256, $name) = $raw =~ /\A([0-9]+(?:\.[0-9]+)+)\|([0-9a-f]{64})\|(postman-[0-9]+(?:\.[0-9]+)+-linux-amd64\.tar\.gz)\n\z/
        or die "stored Postman pending state is invalid\n";
    return { version => $version, sha256 => $sha256, name => $name };
}

sub _version_compare {
    my ($self, $left, $operator, $right) = @_;
    my $result = system('/usr/bin/dpkg', '--compare-versions', $left, $operator, $right);
    return 1 if $result == 0;
    return 0 if $result == 256;
    die "Postman version comparison failed\n";
}

sub _normalize_tree {
    my ($self, $root) = @_;
    -d $root && !-l $root
        or die "Postman staging directory is invalid\n";
    my ($count, $bytes, $symlink_count) = (0, 0, 0);
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                return if $File::Find::name eq $root;
                $count++;
                $count <= 5000
                    or die "Postman payload exceeds file-count bounds\n";
                if (-l $_) {
                    $symlink_count++;
                    $File::Find::name eq "$root/Postman"
                        && readlink($File::Find::name) eq 'app/Postman'
                        or die "Postman payload contains an unsupported symlink\n";
                    return;
                }
                if (-d _) {
                    chown 0, 0, $File::Find::name
                        or die "failed to set Postman directory ownership: $!\n";
                    chmod 0755, $File::Find::name
                        or die "failed to set Postman directory mode: $!\n";
                    return;
                }
                -f _
                    or die "Postman payload contains an unsupported filesystem object\n";
                $bytes += -s _;
                $bytes <= 1_073_741_824
                    or die "Postman payload exceeds size bounds\n";
                chown 0, 0, $File::Find::name
                    or die "failed to set Postman file ownership: $!\n";
                chmod((stat(_))[2] & 0111 ? 0755 : 0644, $File::Find::name)
                    or die "failed to set Postman file mode: $!\n";
            },
        },
        $root,
    );
    $symlink_count == 1
        or die "Postman payload has an unexpected symlink count\n";
    for my $file (
        "$root/app/Postman",
        "$root/app/postman",
        "$root/app/chrome-sandbox",
        "$root/app/libffmpeg.so",
        "$root/app/resources/app/assets/icon.png",
        "$root/app/resources/app/package.json",
    ) {
        -f $file && !-l $file
            or die "Postman payload is missing a required regular file\n";
    }
    -x "$root/app/Postman" && -x "$root/app/postman" && $self->_is_elf("$root/app/Postman")
        or die "Postman payload executable validation failed\n";
    chmod 4755, "$root/app/chrome-sandbox"
        or die "failed to configure Postman Chromium sandbox\n";
    -u "$root/app/chrome-sandbox"
        or die "Postman Chromium sandbox is not setuid root\n";
}

sub fetch {
    my ($self, $work) = @_;
    my $install = '/opt/postman';
    return (2, 'missing') if !-d $install || -l $install || !-x "$install/app/Postman";
    my $archive = "$work/postman-linux64.tar.gz";
    eval {
        $self->http()->download(
            label => 'Postman',
            url => 'https://dl.pstmn.io/download/latest/linux64',
            destination => $archive,
            minimum => 1_048_576,
            maximum => 314_572_800,
            allowed_hosts => ['dl.pstmn.io'],
            content_policy => 'artifact',
        );
        1;
    } or return (1, 'download');
    my $release = eval { $self->validate($archive) };
    return (1, 'archive') if !$release;
    my $installed = $self->_installed();
    if ($installed) {
        return (1, 'downgrade') if $self->_version_compare($release->{version}, 'lt', $installed->{version});
        return (2, 'current') if $release->{version} eq $installed->{version}
            && $release->{sha256} eq $installed->{sha256};
        return (1, 'validation') if $release->{version} eq $installed->{version};
    }
    my $name = "postman-$release->{version}-linux-amd64.tar.gz";
    my ($stored, $created) = eval {
        $self->state()->retain_artifact('postman', $archive, $name);
    };
    return (1, 'publish') if !$stored;
    $self->state()->write_state(
        'postman.pending',
        join('|', $release->{version}, $release->{sha256}, $name) . "\n",
    );
    $self->event()->emit(
        'downloaded',
        'postman',
        $installed ? $installed->{version} : 'unknown',
        $release->{version},
    ) if $created;
    return (0, 'downloaded');
}

sub _rollback {
    my ($self, $install, $backup, $old) = @_;
    (-l $install || -l $backup)
        and die "refusing to roll back a symlinked Postman installation\n";
    remove_tree($install, { safe => 1 }) if -e $install;
    rename $backup, $install if -d $backup;
    if ($old) {
        $self->state()->write_state(
            'postman.installed',
            "$old->{version}|$old->{sha256}\n",
        );
    } else {
        $self->state()->delete_state('postman.installed');
    }
}

sub apply {
    my ($self, $work) = @_;
    my $pending = $self->_pending();
    return (2, 'current') if !defined $pending;

    my $install = '/opt/postman';
    return (1, 'missing') if !-d $install || -l $install || !-x "$install/app/Postman";
    my $stored = $self->state()->artifact_path('postman', $pending->{name});
    -f $stored && !-l $stored
        or return (1, 'validation');
    my $release = eval { $self->validate($stored) };
    return (1, 'archive') if !$release || $release->{version} ne $pending->{version}
        || $release->{sha256} ne $pending->{sha256};

    my $old = $self->_installed();
    if ($old) {
        if ($self->_version_compare($pending->{version}, 'lt', $old->{version})) {
            $self->state()->delete_state('postman.pending');
            return (2, 'current');
        }
        if ($pending->{version} eq $old->{version}) {
            if ($pending->{sha256} eq $old->{sha256}) {
                $self->state()->delete_state('postman.pending');
                return (2, 'current');
            }
            return (1, 'validation');
        }
    }
    return (1, 'in-use') if ExternalSoftware::Servicing::Process->application_running(
        executables => ["$install/app/Postman", "$install/app/postman"],
        roots       => [$install],
    );
    $self->event()->emit(
        'applying',
        'postman',
        $old ? $old->{version} : 'unknown',
        $pending->{version},
    );

    my $archive = "$work/postman-linux64.tar.gz";
    copy($stored, $archive)
        or return (1, 'publish');
    my $staged = "/opt/.postman.new.$$";
    my $backup = '/opt/.postman.previous';
    return (1, 'publish') if -l $staged || -l $backup;
    remove_tree($staged, { safe => 1 }) if -e $staged;
    remove_tree($backup, { safe => 1 }) if -e $backup;
    mkdir $staged, 0700
        or return (1, 'publish');
    system(
        '/usr/bin/tar',
        '--extract',
        '--gzip',
        '--file',
        $archive,
        '--directory',
        $staged,
        '--strip-components=1',
        '--no-same-owner',
        '--no-same-permissions',
    ) == 0 or do {
        remove_tree($staged, { safe => 1 });
        return (1, 'extract');
    };
    eval {
        $self->_normalize_tree($staged);
        ExternalSoftware::Servicing::Atomic->write_text(
            "$staged/.managed-release",
            join(
                q{},
                "version=$pending->{version}\n",
                "archive_sha256=$pending->{sha256}\n",
                "architecture=amd64\n",
            ),
            0644,
        );
        1;
    } or do {
        remove_tree($staged, { safe => 1 });
        return (1, 'publish');
    };

    rename $install, $backup
        or return (1, 'publish');
    if (!rename $staged, $install) {
        rename $backup, $install;
        return (1, 'publish');
    }
    my $published = eval {
        $self->state()->write_state(
            'postman.installed',
            "$pending->{version}|$pending->{sha256}\n",
        );
        -x "$install/app/Postman" && -u "$install/app/chrome-sandbox"
            or die "Postman post-install payload validation failed\n";
        system('/usr/bin/desktop-file-validate', '/usr/share/applications/postman.desktop') == 0
            or die "Postman desktop entry validation failed\n";
        1;
    };
    if (!$published) {
        $self->_rollback($install, $backup, $old);
        return (1, 'postinstall');
    }
    remove_tree($backup, { safe => 1 });
    $self->state()->delete_state('postman.pending');
    system('/usr/bin/update-desktop-database', '/usr/share/applications');
    $self->event()->emit(
        'updated',
        'postman',
        $old ? $old->{version} : 'unknown',
        $pending->{version},
    );
    return (0, 'updated');
}

1;
