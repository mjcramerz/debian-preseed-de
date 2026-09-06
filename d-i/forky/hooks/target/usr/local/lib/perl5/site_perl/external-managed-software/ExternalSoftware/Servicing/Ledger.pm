package ExternalSoftware::Servicing::Ledger;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Cwd qw(getcwd);
use Digest::SHA qw(sha256_hex);
use Digest::SHA;
use File::Copy qw(copy);
use File::Find qw(find);
use File::Path qw(remove_tree);
use MIME::Base64 qw(encode_base64);
use ExternalSoftware::Servicing::Atomic;
use ExternalSoftware::Servicing::Process;

has http  => (is => 'ro', required => 1);
has event => (is => 'ro', required => 1);
has state => (is => 'ro', required => 1);

use constant KEY_FINGERPRINT => '0381bccfa5505e834f9fda30eeba257055782f30c495ba0604a0cd37b548c6fc';

sub _capture_bytes {
    my ($self, @command) = @_;
    open my $fh, '-|', @command
        or return;
    binmode $fh, ':raw';
    my $bytes = do { local $/; <$fh> // q{} };
    close $fh
        or return;
    return $bytes;
}

sub _digest {
    my ($self, $path, $algorithm) = @_;
    -f $path && !-l $path
        or die "Ledger AppImage is not a regular file\n";
    open my $fh, '<:raw', $path
        or die "cannot read Ledger AppImage: $!\n";
    my $digest = Digest::SHA->new($algorithm);
    $digest->addfile($fh);
    close $fh
        or die "cannot close Ledger AppImage: $!\n";
    return $digest->hexdigest();
}

sub _is_elf {
    my ($self, $path) = @_;
    open my $fh, '<:raw', $path
        or die "cannot inspect Ledger AppImage: $!\n";
    my $header = q{};
    read $fh, $header, 4;
    close $fh
        or die "cannot close Ledger AppImage inspection: $!\n";
    return $header eq "\x7fELF";
}

sub _parse_metadata {
    my ($self, $path) = @_;
    my $raw = ExternalSoftware::Servicing::Atomic->read_limited($path, 65_536);
    my %fields;
    for my $field (qw(version path sha512 size)) {
        my @values = $field eq 'size'
            ? $raw =~ /^ {4}size:\s*(.+?)\s*$/mg
            : $raw =~ /^\Q$field\E:\s*(.+?)\s*$/mg;
        @values == 1
            or die "Ledger release metadata must have one $field field\n";
        $fields{$field} = $values[0];
    }
    $fields{version} =~ /\A[0-9]+(?:\.[0-9]+)+\z/ && length($fields{version}) <= 32
        or die "Ledger release version is invalid\n";
    $fields{path} eq "ledger-live-desktop-$fields{version}-linux-x86_64.AppImage"
        or die "Ledger release filename is invalid\n";
    $fields{sha512} =~ /\A[A-Za-z0-9+\/]{86}==\z/
        or die "Ledger release SHA-512 metadata is invalid\n";
    $fields{size} =~ /\A[0-9]+\z/ && $fields{size} >= 104_857_600 && $fields{size} <= 536_870_912
        or die "Ledger release size is outside approved bounds\n";
    return \%fields;
}

sub _manifest_digest {
    my ($self, $path, $filename) = @_;
    my $raw = ExternalSoftware::Servicing::Atomic->read_limited($path, 65_536);
    my @matches = $raw =~ /^\s*([0-9a-f]{128})\s+\Q$filename\E\s*$/mg;
    @matches == 1
        or die "Ledger signed manifest lacks a unique AppImage digest\n";
    return $matches[0];
}

sub _assert_key {
    my ($self, $key) = @_;
    -r $key && !-l $key
        or die "Ledger public key is unavailable\n";
    system('/usr/bin/openssl', 'pkey', '-pubin', '-in', $key, '-noout') == 0
        or die "Ledger public key is invalid\n";
    my $der = $self->_capture_bytes('/usr/bin/openssl', 'pkey', '-pubin', '-in', $key, '-outform', 'DER');
    defined $der && sha256_hex($der) eq KEY_FINGERPRINT
        or die "Ledger public key fingerprint does not match its pinned key\n";
}

sub _tree_bounds {
    my ($self, $root) = @_;
    my ($count, $bytes, $unsafe) = (0, 0, 0);
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                return if $File::Find::name eq $root;
                $count++;
                $unsafe = 1 if -l $_;
                $bytes += -s _ if -f _;
                $unsafe = 1 if $count > 20_000 || $bytes > 1_073_741_824;
            },
        },
        $root,
    );
    !$unsafe
        or die "Ledger extracted AppImage payload exceeds safe bounds\n";
}

sub _normalize_tree {
    my ($self, $root) = @_;
    -d $root && !-l $root
        or die "Ledger staging root is invalid\n";
    $self->_tree_bounds($root);
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                -l $_
                    and die "Ledger payload contains symlink\n";
                chown 0, 0, $File::Find::name
                    or die "failed to set Ledger payload ownership: $!\n";
                if (-d _) {
                    chmod 0755, $File::Find::name
                        or die "failed to set Ledger directory mode: $!\n";
                } elsif (-f _) {
                    chmod((stat(_))[2] & 0111 ? 0755 : 0644, $File::Find::name)
                        or die "failed to set Ledger file mode: $!\n";
                } else {
                    die "Ledger payload contains unsupported filesystem object\n";
                }
            },
        },
        $root,
    );
    for my $file ("$root/AppRun", "$root/ledger-live-desktop") {
        -x $file && !-l $file
            or die "Ledger payload executable is missing\n";
        chmod 0755, $file
            or die "failed to normalize Ledger executable mode: $!\n";
    }
    my $sandbox = "$root/chrome-sandbox";
    -f $sandbox && !-l $sandbox
        or die "Ledger payload sandbox is missing\n";
    chmod 04755, $sandbox
        or die "failed to normalize Ledger sandbox mode: $!\n";
}

sub _installed_hash {
    my ($self) = @_;
    my $raw = $self->state()->read_state('ledger.installed.sha512', 256);
    return q{} if !defined $raw;
    $raw =~ /\A([0-9a-f]{128})\n\z/
        or die "stored Ledger installation hash is invalid\n";
    return $1;
}

sub _installed_version {
    my ($self) = @_;
    my $raw = $self->state()->read_state('ledger.installed.version', 128);
    return q{} if !defined $raw;
    $raw =~ /\A([0-9]+(?:\.[0-9]+)+)\n\z/
        or die "stored Ledger installation version is invalid\n";
    return $1;
}

sub _pending {
    my ($self) = @_;
    my $raw = $self->state()->read_state('ledger.pending', 512);
    return undef if !defined $raw;
    my ($version, $hash, $name) = $raw =~ /\A([0-9]+(?:\.[0-9]+)+)\|([0-9a-f]{128})\|(ledger-live-desktop-[0-9]+(?:\.[0-9]+)+-linux-x86_64\.AppImage)\n\z/
        or die "stored Ledger pending state is invalid\n";
    return { version => $version, hash => $hash, name => $name };
}

sub _version_compare {
    my ($self, $left, $operator, $right) = @_;
    my $result = system('/usr/bin/dpkg', '--compare-versions', $left, $operator, $right);
    return 1 if $result == 0;
    return 0 if $result == 256;
    die "Ledger version comparison failed\n";
}

sub _rollback {
    my ($self, $install, $backup, $old_hash, $old_version) = @_;
    (-l $install || -l $backup)
        and die "refusing to roll back a symlinked Ledger installation\n";
    remove_tree($install, { safe => 1 }) if -e $install;
    rename $backup, $install if -d $backup;
    if ($old_hash =~ /\A[0-9a-f]{128}\z/) {
        $self->state()->write_state('ledger.installed.sha512', "$old_hash\n");
    } else {
        $self->state()->delete_state('ledger.installed.sha512');
    }
    if ($old_version =~ /\A[0-9]+(?:\.[0-9]+)+\z/) {
        $self->state()->write_state('ledger.installed.version', "$old_version\n");
    } else {
        $self->state()->delete_state('ledger.installed.version');
    }
}

sub fetch {
    my ($self, $work) = @_;
    my $install = '/opt/ledger-live';
    return (2, 'missing') if !-d $install || -l $install || !-x "$install/AppRun"
        || !-x "$install/ledger-live-desktop" || !-u "$install/chrome-sandbox";

    my $key = '/usr/local/share/software/ledger/ledgerlive.pem';
    my ($metadata, $manifest, $signature, $image) = map { "$work/$_" } qw(
        ledger-latest-linux.yml ledger-live.sha512sum ledger-live.sha512sum.sig ledger-live-linux-x86_64.AppImage
    );
    my $release;
    eval {
        $self->_assert_key($key);
        $self->http()->download(
            label => 'Ledger release metadata',
            url => 'https://download.live.ledger.com/latest-linux.yml',
            destination => $metadata,
            minimum => 128,
            maximum => 65_536,
            allowed_hosts => ['download.live.ledger.com'],
            content_policy => 'metadata',
        );
        $release = $self->_parse_metadata($metadata);
        my $base = "https://resources.live.ledger.app/public_resources/signatures/ledger-live-desktop-$release->{version}.sha512sum";
        $self->http()->download(
            label => 'Ledger checksum manifest',
            url => $base,
            destination => $manifest,
            minimum => 128,
            maximum => 65_536,
            allowed_hosts => ['resources.live.ledger.app'],
            content_policy => 'metadata',
        );
        $self->http()->download(
            label => 'Ledger checksum signature',
            url => "$base.sig",
            destination => $signature,
            minimum => 64,
            maximum => 4_096,
            allowed_hosts => ['resources.live.ledger.app'],
            content_policy => 'artifact',
        );
        system('/usr/bin/openssl', 'dgst', '-sha256', '-verify', $key, '-signature', $signature, $manifest) == 0
            or die "Ledger checksum signature verification failed\n";
        $self->http()->download(
            label => 'Ledger Live AppImage',
            url => 'https://download.live.ledger.com/latest/linux',
            destination => $image,
            minimum => 1_048_576,
            maximum => 536_870_912,
            allowed_hosts => ['download.live.ledger.com'],
            content_policy => 'artifact',
        );
        1;
    } or return (1, $@ =~ /signature|fingerprint/i ? 'signature' : 'download');

    -s $image == $release->{size}
        or return (1, 'validation');
    my $sha512 = eval { $self->_digest($image, 512) };
    return (1, 'validation') if !$sha512 || !$self->_is_elf($image);
    $sha512 eq $self->_manifest_digest($manifest, $release->{path})
        && encode_base64(pack('H*', $sha512), q{}) eq $release->{sha512}
        or return (1, 'signature');

    my $old_hash = $self->_installed_hash();
    my $old_version = $self->_installed_version();
    if ($old_version ne q{} && $self->_version_compare($release->{version}, 'lt', $old_version)) {
        return (1, 'downgrade');
    }
    return (2, 'current') if $old_hash eq $sha512;

    my ($stored, $created) = eval {
        $self->state()->retain_artifact('ledger', $image, $release->{path});
    };
    return (1, 'publish') if !$stored;
    $self->state()->write_state(
        'ledger.pending',
        join('|', $release->{version}, $sha512, $release->{path}) . "\n",
    );
    $self->event()->emit('downloaded', 'ledger', $old_version || 'unknown', $release->{version})
        if $created;
    return (0, 'downloaded');
}

sub apply {
    my ($self, $work) = @_;
    my $pending = $self->_pending();
    return (2, 'current') if !defined $pending;

    my $install = '/opt/ledger-live';
    return (1, 'missing') if !-d $install || -l $install || !-x "$install/AppRun"
        || !-x "$install/ledger-live-desktop" || !-u "$install/chrome-sandbox";
    my $stored = $self->state()->artifact_path('ledger', $pending->{name});
    -f $stored && !-l $stored
        or return (1, 'validation');
    my $sha512 = eval { $self->_digest($stored, 512) };
    return (1, 'validation') if !$sha512 || $sha512 ne $pending->{hash} || !$self->_is_elf($stored);

    my $old_hash = $self->_installed_hash();
    my $old_version = $self->_installed_version();
    if ($old_version ne q{} && $self->_version_compare($pending->{version}, 'lt', $old_version)) {
        $self->state()->delete_state('ledger.pending');
        return (2, 'current');
    }
    if ($old_version eq $pending->{version}) {
        if ($old_hash eq $sha512) {
            $self->state()->delete_state('ledger.pending');
            return (2, 'current');
        }
        return (1, 'validation');
    }
    return (1, 'in-use') if ExternalSoftware::Servicing::Process->application_running(
        executables => ["$install/AppRun", "$install/ledger-live-desktop"],
        roots       => [$install],
    );
    $self->event()->emit('applying', 'ledger', $old_version || 'unknown', $pending->{version});

    my $image = "$work/ledger-live-linux-x86_64.AppImage";
    copy($stored, $image)
        or return (1, 'publish');
    chmod 0700, $image
        or return (1, 'extract');
    my $cwd = getcwd();
    chdir $work
        or return (1, 'extract');
    my $extract_status = system($image, '--appimage-extract');
    chdir $cwd
        or die "failed to restore updater working directory\n";
    return (1, 'extract') if $extract_status != 0;
    my $extracted = "$work/squashfs-root";
    -d $extracted && !-l $extracted && -x "$extracted/AppRun"
        && -x "$extracted/ledger-live-desktop" && -f "$extracted/resources/app.asar"
        or return (1, 'extract');

    my $staged = "/opt/.ledger-live.new.$$";
    my $backup = '/opt/.ledger-live.previous';
    return (1, 'publish') if -l $staged || -l $backup;
    remove_tree($staged, { safe => 1 }) if -e $staged;
    remove_tree($backup, { safe => 1 }) if -e $backup;
    system('/bin/cp', '-a', "$extracted/.", $staged) == 0
        or return (1, 'publish');
    eval { $self->_normalize_tree($staged); 1 } or do {
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
        $self->state()->write_state('ledger.installed.sha512', "$sha512\n");
        $self->state()->write_state('ledger.installed.version', "$pending->{version}\n");
        system('/usr/bin/desktop-file-validate', '/usr/share/applications/ledger-live.desktop') == 0
            or die "Ledger desktop entry validation failed\n";
        -u "$install/chrome-sandbox" && -x "$install/AppRun" && -x "$install/ledger-live-desktop"
            or die "Ledger post-install payload validation failed\n";
        1;
    };
    if (!$published) {
        $self->_rollback($install, $backup, $old_hash, $old_version);
        return (1, 'postinstall');
    }
    remove_tree($backup, { safe => 1 });
    $self->state()->delete_state('ledger.pending');
    system('/usr/bin/update-desktop-database', '/usr/share/applications');
    $self->event()->emit('updated', 'ledger', $old_version || 'unknown', $pending->{version});
    return (0, 'updated');
}

1;
