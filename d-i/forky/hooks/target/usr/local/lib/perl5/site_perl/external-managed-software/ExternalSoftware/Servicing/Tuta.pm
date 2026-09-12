package ExternalSoftware::Servicing::Tuta;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Digest::SHA;
use File::Copy qw(copy);
use File::Path qw(remove_tree);
use ExternalSoftware::Servicing::Atomic;
use ExternalSoftware::Servicing::Process;

has http  => (is => 'ro', required => 1);
has event => (is => 'ro', required => 1);
has state => (is => 'ro', required => 1);

sub _sha256 {
    my ($self, $path) = @_;
    -f $path && !-l $path
        or die "Tuta AppImage is not a regular file\n";
    open my $fh, '<:raw', $path
        or die "cannot read Tuta AppImage: $!\n";
    my $digest = Digest::SHA->new(256);
    $digest->addfile($fh);
    close $fh
        or die "cannot close Tuta AppImage: $!\n";
    return $digest->hexdigest();
}

sub _is_elf {
    my ($self, $path) = @_;
    open my $fh, '<:raw', $path
        or die "cannot inspect Tuta AppImage: $!\n";
    my $header = q{};
    read $fh, $header, 4;
    close $fh
        or die "cannot close Tuta AppImage inspection: $!\n";
    return $header eq "\x7fELF";
}

sub _installed_hash {
    my ($self) = @_;
    my $raw = $self->state()->read_state('tuta.installed.sha256', 128);
    return q{} if !defined $raw;
    $raw =~ /\A([0-9a-f]{64})\n\z/
        or die "stored Tuta installation state is invalid\n";
    return $1;
}

sub _pending {
    my ($self) = @_;
    my $raw = $self->state()->read_state('tuta.pending', 256);
    return undef if !defined $raw;
    my ($hash, $name) = $raw =~ /\A([0-9a-f]{64})\|(tuta-[0-9a-f]{64}\.AppImage)\n\z/
        or die "stored Tuta pending state is invalid\n";
    return { hash => $hash, name => $name };
}

sub _event_hash {
    my ($self, $hash) = @_;
    return $hash =~ /\A[0-9a-f]{64}\z/
        ? 'sha256:' . substr($hash, 0, 12)
        : 'unknown';
}

sub fetch {
    my ($self, $work, $for_repository) = @_;
    my $install = '/opt/tuta-mail';
    return (2, 'missing') if !$for_repository && (!-d $install || -l $install || !-x "$install/AppRun");
    my $key = '/usr/local/share/software/tuta/tutao-pub.pem';
    return (1, 'signature') if !-r $key || -l $key;

    my $image = "$work/tutanota-desktop-linux.AppImage";
    my $signature = "$work/tutanota-linux-sig.bin";
    eval {
        $self->http()->download(
            label => 'Tuta Mail AppImage',
            url => 'https://app.tuta.com/desktop/tutanota-desktop-linux.AppImage',
            destination => $image,
            minimum => 1_048_576,
            maximum => 536_870_912,
            allowed_hosts => ['app.tuta.com'],
            content_policy => 'artifact',
        );
        $self->http()->download(
            label => 'Tuta Mail signature',
            url => 'https://app.tuta.com/desktop/linux-sig.bin',
            destination => $signature,
            minimum => 128,
            maximum => 16_384,
            allowed_hosts => ['app.tuta.com'],
            content_policy => 'artifact',
        );
        system('/usr/bin/openssl', 'dgst', '-sha512', '-verify', $key, '-signature', $signature, $image) == 0
            or die "Tuta signature verification failed\n";
        $self->_is_elf($image)
            or die "Tuta AppImage is not an ELF binary\n";
        1;
    } or return (1, $@ =~ /signature/i ? 'signature' : 'download');

    my $hash = eval { $self->_sha256($image) };
    return (1, 'validation') if !$hash;
    my $installed = $self->_installed_hash();
    return (2, 'current') if $installed eq $hash;

    my $name = "tuta-${hash}.AppImage";
    my $previous_pending = $self->_pending();
    my ($stored, $created) = eval {
        $self->state()->retain_artifact('tuta', $image, $name);
    };
    return (1, 'publish') if !$stored;
    $self->state()->write_state('tuta.pending', "$hash|$name\n");
    $self->event()->emit(
        'downloaded',
        'tuta',
        $self->_event_hash($installed),
        $self->_event_hash($hash),
    ) if $created || !defined $previous_pending
        || $previous_pending->{hash} ne $hash;
    return (0, 'downloaded');
}

sub _restore_install {
    my ($self, $install, $backup, $old_hash) = @_;
    if (-l $install || -l $backup) {
        die "refusing to roll back a symlinked Tuta installation\n";
    }
    remove_tree($install, { safe => 1 }) if -e $install;
    rename $backup, $install if -d $backup;
    if ($old_hash =~ /\A[0-9a-f]{64}\z/) {
        $self->state()->write_state('tuta.installed.sha256', "$old_hash\n");
    } else {
        $self->state()->delete_state('tuta.installed.sha256');
    }
}

sub apply {
    my ($self, $work) = @_;
    my $pending = $self->_pending();
    return (2, 'current') if !defined $pending;

    my $install = '/opt/tuta-mail';
    return (1, 'missing') if !-d $install || -l $install || !-x "$install/AppRun";
    my $stored = $self->state()->artifact_path('tuta', $pending->{name});
    -f $stored && !-l $stored
        or return (1, 'validation');
    my $hash = eval { $self->_sha256($stored) };
    return (1, 'validation') if !$hash || $hash ne $pending->{hash} || !$self->_is_elf($stored);

    my $old_hash = $self->_installed_hash();
    if ($old_hash eq $hash) {
        $self->state()->delete_state('tuta.pending');
        return (2, 'current');
    }
    return (1, 'in-use') if ExternalSoftware::Servicing::Process->application_running(
        executables => ["$install/AppRun"],
        roots       => [$install],
    );
    $self->event()->emit(
        'applying',
        'tuta',
        $self->_event_hash($old_hash),
        $self->_event_hash($hash),
    );

    my $image = "$work/tutanota-desktop-linux.AppImage";
    copy($stored, $image)
        or return (1, 'publish');
    chmod 0700, $image
        or return (1, 'extract');
    system('/usr/bin/env', "TMPDIR=$work", $image, '--appimage-extract') == 0
        or return (1, 'extract');
    my $extracted = "$work/squashfs-root";
    -d $extracted && !-l $extracted && -x "$extracted/AppRun"
        or return (1, 'extract');

    my $staged = "/opt/.tuta-mail.new.$$";
    my $backup = '/opt/.tuta-mail.previous';
    return (1, 'publish') if -l $staged || -l $backup;
    remove_tree($staged, { safe => 1 }) if -e $staged;
    remove_tree($backup, { safe => 1 }) if -e $backup;
    system('/bin/cp', '-a', "$extracted/.", $staged) == 0
        or return (1, 'publish');
    system('/bin/chown', '-R', 'root:root', $staged) == 0
        && system('/usr/bin/find', $staged, '-xdev', '-type', 'd', '-exec', '/bin/chmod', '0755', '{}', '+') == 0
        && system('/usr/bin/find', $staged, '-xdev', '-type', 'f', '-exec', '/bin/chmod', 'a-s,go-w', '{}', '+') == 0
        && system('/bin/chmod', '0755', "$staged/AppRun") == 0
        or return (1, 'publish');
    -f "$staged/AppRun" && !-l "$staged/AppRun" && -x "$staged/AppRun"
        or return (1, 'publish');

    rename $install, $backup
        or return (1, 'publish');
    if (!rename $staged, $install) {
        rename $backup, $install;
        return (1, 'publish');
    }
    my $published = eval {
        $self->state()->write_state('tuta.installed.sha256', "$hash\n");
        system('/usr/bin/desktop-file-validate', '/etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop') == 0
            or die "Tuta desktop entry validation failed\n";
        -x "$install/AppRun" && !-l "$install/AppRun"
            or die "Tuta post-install payload validation failed\n";
        1;
    };
    if (!$published) {
        $self->_restore_install($install, $backup, $old_hash);
        return (1, 'postinstall');
    }
    remove_tree($backup, { safe => 1 });
    $self->state()->delete_state('tuta.pending');
    system('/usr/bin/update-desktop-database', '/usr/share/applications');
    $self->event()->emit(
        'updated',
        'tuta',
        $self->_event_hash($old_hash),
        $self->_event_hash($hash),
    );
    return (0, 'updated');
}

1;
