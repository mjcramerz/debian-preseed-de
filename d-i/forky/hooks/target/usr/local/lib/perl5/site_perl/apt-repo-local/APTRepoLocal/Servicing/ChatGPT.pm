package APTRepoLocal::Servicing::ChatGPT;

use strict;
use warnings;

use lib '/usr/local/lib/perl5/site_perl/runtime';
use Managed::Process qw(capture_command);

use Moo;
use MooX::StrictConstructor;

use Fcntl qw(S_IFMT S_IFREG S_IFLNK O_RDONLY O_DIRECTORY O_NOFOLLOW O_WRONLY O_CREAT O_EXCL);
use IO::Handle;
use JSON::PP ();
use MIME::Base64 qw(encode_base64);
use File::Basename qw(dirname);
use Managed::PolicyLock qw(acquire_policy_lock with_policy_lock_handoff);
use APTRepoLocal::Servicing::Atomic;
use APTRepoLocal::Servicing::ArtifactLimits qw(MAX_DOWNLOAD_BYTES);

has state => (is => 'ro', required => 1);

use constant ENABLE_STATE              => 'chatgpt.enabled';
use constant ENABLE_STATE_CONTENT      => "addon/devops\n";
use constant CANONICAL_DIRECTORY       => '/usr/local/share/software/chatgpt';
use constant CANONICAL_DEFAULT         => CANONICAL_DIRECTORY . '/default';
use constant CANONICAL_DESKTOP         => CANONICAL_DIRECTORY . '/chatgpt.desktop';
use constant CANONICAL_APPARMOR        => CANONICAL_DIRECTORY . '/apparmor.profile';
use constant CANONICAL_ICON            => CANONICAL_DIRECTORY . '/chatgpt.png';
use constant DEFAULT_PATH              => '/etc/chatgpt/package-policy.conf';
use constant PACKAGE_DEFAULT_PATH      => '/etc/default/chatgpt';
use constant DESKTOP_PATH              => '/usr/local/share/applications/chatgpt.desktop';
use constant ICON_PATH                 => '/usr/share/pixmaps/chatgpt.png';
use constant APPARMOR_PATH             => '/etc/apparmor.d/chatgpt';
use constant APPARMOR_DISABLE_DIRECTORY => '/etc/apparmor.d/disable';
use constant APPARMOR_DISABLE_PATH     => '/etc/apparmor.d/disable/chatgpt';
use constant PACKAGE_SCRIPT_GUARD_CONTENT => "managed ChatGPT package transaction\n";
use constant DIVERSION_PATH            => '/var/lib/software/vendor/chatgpt.apparmor';
use constant VENDOR_SOURCE_PATH        => '/etc/apt/sources.list.d/chatgpt.sources';
use constant VENDOR_LEGACY_SOURCE_PATH => '/etc/apt/sources.list.d/chatgpt.list';
use constant VENDOR_KEYRING_PATH       => '/usr/share/keyrings/chatgpt-archive-keyring.gpg';
use constant MANAGED_MODES_HELPER      => '/usr/local/libexec/apparmor-modes-run';
use constant APPARMOR_PARSER           => '/usr/sbin/apparmor_parser';
use constant APPARMOR_SECURITYFS       => '/sys/kernel/security/apparmor';
use constant APPARMOR_PROFILES_PATH    => APPARMOR_SECURITYFS . '/profiles';
use constant POLICY_RECOVERY           => '/var/lib/software/chatgpt-policy-recovery';

sub _sync_directory {
    my ($self, $path) = @_;
    sysopen my $fh, $path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW
        or die "cannot open ChatGPT transaction directory: $!\n";
    $fh->sync() or die "cannot synchronize ChatGPT transaction directory: $!\n";
    close $fh or die "cannot close ChatGPT transaction directory: $!\n";
}

sub _begin_policy_transaction {
    my ($self, $context) = @_;
    if ($self->{policy_transaction}) {
        $self->{policy_transaction}{context} eq $context or die "ChatGPT transaction context changed\n";
        return;
    }
    my $lock = acquire_policy_lock();
    -e POLICY_RECOVERY || -l POLICY_RECOVERY
        and die "ChatGPT recovery is pending at " . POLICY_RECOVERY . "; reconcile before retrying\n";
    my $owner = $self->_diversion_owner();
    $owner eq q{} || ($owner eq 'LOCAL' && $self->_diversion_target() eq DIVERSION_PATH)
        or die "ChatGPT AppArmor diversion is unmanaged\n";
    my @paths = (DEFAULT_PATH, PACKAGE_DEFAULT_PATH, APPARMOR_PATH, APPARMOR_DISABLE_PATH,
                 DIVERSION_PATH, DESKTOP_PATH, ICON_PATH, VENDOR_SOURCE_PATH,
                 VENDOR_LEGACY_SOURCE_PATH, VENDOR_KEYRING_PATH);
    my @previous;
    for my $path (@paths) {
        my @st = lstat $path;
        if (!@st) {
            $!{ENOENT} or die "cannot inspect previous ChatGPT policy state: $!\n";
            push @previous, {path => $path, kind => 'absent'};
            next;
        }
        $st[4] == 0 && !($st[2] & 0022)
            or die "previous ChatGPT policy state is not privately owned\n" if ($st[2] & S_IFMT) != S_IFLNK;
        my $entry = {path => $path, mode => $st[2] & 07777, uid => $st[4], gid => $st[5]};
        if (($st[2] & S_IFMT) == S_IFREG && $st[3] == 1) {
            $entry->{kind} = 'file';
            $entry->{data} = APTRepoLocal::Servicing::Atomic->read_limited($path, 1024 * 1024);
        } elsif (($st[2] & S_IFMT) == S_IFLNK && $st[4] == 0) {
            $entry->{kind} = 'link';
            $entry->{data} = readlink $path;
            defined($entry->{data}) && length($entry->{data}) <= 4096
                or die "invalid previous ChatGPT policy link\n";
        } else {
            die "previous ChatGPT policy path has an unsafe type\n";
        }
        push @previous, $entry;
    }
    my $snapshot = {version => 1, context => $context, diversion => $owner, previous => \@previous};
    my @persisted = map { my %record = %$_; $record{data} = encode_base64($record{data}, q{}) if exists $record{data}; \%record } @previous;
    my $bytes = JSON::PP->new->canonical->encode({%$snapshot, previous => \@persisted});
    APTRepoLocal::Servicing::Atomic->ensure_root_directory('/var/lib/software', 0755);
    mkdir POLICY_RECOVERY, 0700 or die "cannot reserve ChatGPT recovery directory: $!\n";
    # Record ownership before writing: an interrupted fsync retains recovery.
    $self->{policy_transaction} = {%$snapshot, lock => $lock};
    sysopen my $fh, POLICY_RECOVERY . '/previous.json', O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600
        or die "cannot create ChatGPT policy recovery snapshot: $!\n";
    print {$fh} $bytes or die "cannot write ChatGPT policy recovery snapshot: $!\n";
    $fh->flush() && $fh->sync() or die "cannot synchronize ChatGPT policy recovery snapshot: $!\n";
    close $fh or die "cannot close ChatGPT policy recovery snapshot: $!\n";
    $self->_sync_directory(POLICY_RECOVERY);
    $self->_sync_directory('/var/lib/software');
}

sub _finish_policy_transaction {
    my ($self) = @_;
    my $transaction = $self->{policy_transaction} or return;
    my %directories = map { dirname($_->{path}) => 1 } @{$transaction->{previous}};
    $self->_sync_directory($_) for grep { -d $_ } sort keys %directories;
    # Publication/verification is complete. A later evidence-cleanup failure
    # must not turn a committed generation into an automatic rollback.
    delete $self->{policy_transaction};
    unlink POLICY_RECOVERY . '/previous.json' or die "cannot retire ChatGPT recovery snapshot: $!\n";
    $self->_sync_directory(POLICY_RECOVERY);
    rmdir POLICY_RECOVERY or die "cannot retire ChatGPT recovery directory: $!\n";
    $self->_sync_directory('/var/lib/software');
}

sub package_install {
    my ($self, $callback) = @_;
    $self->{policy_transaction} or die "ChatGPT package installation has no policy owner\n";
    local $ENV{MANAGED_CHATGPT_POLICY_DEFER} = 1;
    return with_policy_lock_handoff($callback);
}

sub verify_deferred_prepare {
    my ($self) = @_;
    exists($ENV{MANAGED_APPARMOR_POLICY_LOCK_FD})
        or die "ChatGPT deferred configuration has no inherited policy owner\n";
    my $lock = acquire_policy_lock();
    my @directory = lstat POLICY_RECOVERY;
    @directory && -d _ && !-l _ && $directory[4] == 0 && ($directory[2] & 0077) == 0
        or die "ChatGPT deferred configuration has no private recovery snapshot\n";
    $self->_root_owned_source_text(POLICY_RECOVERY . '/previous.json', 16 * 1024 * 1024);
    $self->_root_owned_source_text(APPARMOR_DISABLE_PATH, 128) eq PACKAGE_SCRIPT_GUARD_CONTENT
        or die "ChatGPT deferred configuration has no managed package guard\n";
    -l PACKAGE_DEFAULT_PATH && readlink(PACKAGE_DEFAULT_PATH) eq DEFAULT_PATH
        or die "ChatGPT deferred configuration has no managed defaults link\n";
    return 1;
}

sub spec {
    return {
        name       => 'chatgpt',
        label      => 'ChatGPT/Codex Desktop',
        url        => 'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb',
        maximum    => MAX_DOWNLOAD_BYTES,
        hosts      => ['persistent.oaistatic.com'],
        packages   => ['chatgpt'],
        validate_payload => 0,
        # The managed launcher uses native Wayland. Keep display-server and
        # GPU-driver ownership in the host profile instead of the vendor package.
        remove_dependencies => [
            'mesa-vulkan-drivers',
            'vulkan-icd',
            '*nvidia*',
            'cuda-*',
            'libcuda*',
            '*x11*',
            'libice*',
            'libsm6',
            'libxau*',
            'libxaw*',
            'libxcb*',
            'libxcomposite*',
            'libxcursor*',
            'libxdamage*',
            'libxdmcp*',
            'libxext*',
            'libxfixes*',
            'libxfont*',
            'libxft*',
            'libxi*',
            'libxkbfile*',
            'libxmu*',
            'libxpm*',
            'libxpresent*',
            'libxrandr*',
            'libxrender*',
            'libxres*',
            'libxshmfence*',
            'libxss*',
            'libxt6',
            'libxtst*',
            'libxv1',
            'libxvmc*',
            'libxxf86*',
            'xauth',
            'xfonts-*',
            'xorg*',
            'xserver-*',
            'xtrans-*',
            'xwayland*',
        ],
        executable => '/usr/lib/chatgpt/ChatGPT',
        in_use_executables => ['/usr/bin/chatgpt'],
        in_use_roots => ['/usr/lib/chatgpt'],
        desktop    => DESKTOP_PATH,
        library    => q{},
        # These paths are verified after installation. Download validation is
        # intentionally limited to Debian package identity and architecture.
        required_paths => [
            '/usr/bin/chatgpt',
            '/usr/lib/chatgpt/codex-launcher',
            '/usr/lib/chatgpt/resources/codex',
            '/usr/lib/chatgpt/resources/codex-code-mode-host',
            ICON_PATH,
        ],
        required_executables => [
            '/usr/bin/chatgpt',
            '/usr/lib/chatgpt/codex-launcher',
            '/usr/lib/chatgpt/resources/codex',
            '/usr/lib/chatgpt/resources/codex-code-mode-host',
        ],
    };
}

sub enabled {
    my ($self) = @_;
    my $value = $self->state()->read_state(ENABLE_STATE, 64);
    return 0 if !defined $value;
    $value eq ENABLE_STATE_CONTENT
        or die "ChatGPT enable state is invalid\n";
    return 1;
}

sub _capture {
    my ($self, @command) = @_;
    @command or return;
    my $result = capture_command(argv => \@command, timeout => 120, limit => 1_048_576);
    if ($result->{status} != 0) { die "ChatGPT policy query failed\n"; }
    return $result->{stdout};
}

sub _root_owned_source_text {
    my ($self, $path, $maximum) = @_;
    APTRepoLocal::Servicing::Atomic->assert_absolute_path(
        'ChatGPT canonical asset',
        $path,
    );
    my @st = lstat $path;
    @st && ($st[2] & S_IFMT) == S_IFREG && !-l _ && $st[4] == 0 && $st[5] == 0
        && !($st[2] & 0022)
        or die "ChatGPT canonical asset is unsafe: $path\n";
    return APTRepoLocal::Servicing::Atomic->read_limited($path, $maximum);
}

sub _install_canonical_text {
    my ($self, $source, $destination, $mode, $maximum) = @_;
    my $content = $self->_root_owned_source_text($source, $maximum);
    my $parent = dirname($destination);
    APTRepoLocal::Servicing::Atomic->ensure_root_directory($parent, 0755) if !-e $parent;
    my @directory = lstat $parent;
    @directory && -d _ && !-l _ && $directory[4] == 0 && !($directory[2] & 0022)
        or die "unsafe ChatGPT policy destination directory\n";
    APTRepoLocal::Servicing::Atomic->_publish(
        $destination,
        $content,
        $mode,
    );
    return $content;
}

sub _destination_matches {
    my ($self, $source, $destination, $maximum) = @_;
    return 0 if !-e $destination && !-l $destination;
    my @st = lstat $destination;
    @st && ($st[2] & S_IFMT) == S_IFREG && !-l _ && $st[4] == 0 && $st[5] == 0
        && !($st[2] & 0022)
        or die "ChatGPT managed destination is unsafe: $destination\n";
    return $self->_root_owned_source_text($source, $maximum)
        eq APTRepoLocal::Servicing::Atomic->read_limited($destination, $maximum);
}

sub _remove_file_or_symlink {
    my ($self, $path) = @_;
    return 1 if !-e $path && !-l $path;
    (-f $path || -l $path)
        or die "refusing to remove unsafe ChatGPT vendor path: $path\n";
    unlink $path
        or die "failed to remove ChatGPT vendor path $path: $!\n";
    return 1;
}

sub _clear_package_script_guard {
    my ($self) = @_;
    return 1 if !-e APPARMOR_DISABLE_PATH && !-l APPARMOR_DISABLE_PATH;
    if (-l APPARMOR_DISABLE_PATH) {
        my $target = readlink APPARMOR_DISABLE_PATH;
        defined $target
            && ($target eq '.././chatgpt' || $target eq '../chatgpt')
            or die "ChatGPT AppArmor disable link is unmanaged\n";
    } elsif (-f APPARMOR_DISABLE_PATH) {
        my @st = lstat APPARMOR_DISABLE_PATH;
        @st
            && ($st[2] & S_IFMT) == S_IFREG
            && $st[4] == 0
            && $st[5] == 0
            && !($st[2] & 0022)
            or die "ChatGPT package-script guard is unsafe\n";
        APTRepoLocal::Servicing::Atomic->read_limited(
            APPARMOR_DISABLE_PATH,
            128,
        ) eq PACKAGE_SCRIPT_GUARD_CONTENT
            or die "ChatGPT package-script guard is unmanaged\n";
    } else {
        die "ChatGPT AppArmor disable path is unsafe\n";
    }
    unlink APPARMOR_DISABLE_PATH
        or die "failed to clear the ChatGPT package-script guard: $!\n";
    return 1;
}

sub _install_package_script_guard {
    my ($self) = @_;
    APTRepoLocal::Servicing::Atomic->ensure_root_directory(
        APPARMOR_DISABLE_DIRECTORY,
        0755,
    );
    $self->_clear_package_script_guard();
    APTRepoLocal::Servicing::Atomic->_publish(
        APPARMOR_DISABLE_PATH,
        PACKAGE_SCRIPT_GUARD_CONTENT,
        0644,
    );
    return 1;
}

sub _remove_vendor_repository_paths {
    my ($self) = @_;
    for my $path (
        VENDOR_SOURCE_PATH,
        VENDOR_LEGACY_SOURCE_PATH,
        VENDOR_KEYRING_PATH,
    ) {
        $self->_remove_file_or_symlink($path);
    }
    return 1;
}

sub _diversion_owner {
    my ($self) = @_;
    my $value = $self->_capture(
        '/usr/bin/env', '-i',
        'LC_ALL=C.UTF-8',
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        '/usr/bin/dpkg-divert',
        '--listpackage',
        APPARMOR_PATH,
    );
    chomp $value;
    return $value;
}

sub _diversion_target {
    my ($self) = @_;
    my $value = $self->_capture(
        '/usr/bin/env', '-i',
        'LC_ALL=C.UTF-8',
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        '/usr/bin/dpkg-divert',
        '--truename',
        APPARMOR_PATH,
    );
    chomp $value;
    return $value;
}

sub _assert_diversion {
    my ($self) = @_;
    $self->_diversion_owner() eq 'LOCAL'
        or die "ChatGPT AppArmor path is not locally diverted\n";
    $self->_diversion_target() eq DIVERSION_PATH
        or die "ChatGPT AppArmor diversion has an unexpected destination\n";
    return 1;
}

sub ensure_diversion {
    my ($self) = @_;
    APTRepoLocal::Servicing::Atomic->ensure_root_directory(
        '/var/lib/software/vendor',
        0755,
    );
    my $owner = $self->_diversion_owner();
    if ($owner eq q{}) {
        if (-e APPARMOR_PATH || -l APPARMOR_PATH) {
            $self->_destination_matches(
                CANONICAL_APPARMOR,
                APPARMOR_PATH,
                1024 * 1024,
            ) or die "refusing to divert an unmanaged ChatGPT AppArmor profile\n";
            unlink APPARMOR_PATH
                or die "failed to clear the managed ChatGPT profile before diversion: $!\n";
        }
        system(
            '/usr/bin/env', '-i',
            'LC_ALL=C.UTF-8',
            'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            '/usr/bin/dpkg-divert',
            '--local',
            '--add',
            '--rename',
            '--divert', DIVERSION_PATH,
            APPARMOR_PATH,
        ) == 0
            or die "failed to establish the ChatGPT AppArmor diversion\n";
    } elsif ($owner ne 'LOCAL') {
        die "ChatGPT AppArmor path has a conflicting dpkg diversion\n";
    }
    $self->_assert_diversion();
    return 1;
}

sub _install_managed_policy_files {
    my ($self) = @_;
    $self->enabled()
        or die "ChatGPT package policy is disabled\n";
    $self->_install_canonical_text(
        CANONICAL_DEFAULT,
        DEFAULT_PATH,
        0644,
        4096,
    );
    $self->ensure_diversion();
    $self->_install_canonical_text(
        CANONICAL_APPARMOR,
        APPARMOR_PATH,
        0644,
        1024 * 1024,
    );
    return 1;
}

# Compatibility for the vendor maintainer script, not a second policy file.
# Transactions are serialized by the existing apt-repo-local software lock.
sub _clear_package_default_link {
    my ($self) = @_;
    return 1 if !-e PACKAGE_DEFAULT_PATH && !-l PACKAGE_DEFAULT_PATH;
    my @st = lstat PACKAGE_DEFAULT_PATH;
    @st && $st[4] == 0 && $st[5] == 0 && $st[3] == 1
        or die "unsafe ChatGPT package-default compatibility path\n";
    if (($st[2] & S_IFMT) == S_IFLNK) {
        my $target = readlink PACKAGE_DEFAULT_PATH;
        defined($target) && $target eq DEFAULT_PATH
            or die "unrecognized ChatGPT package-default link\n";
    } elsif (($st[2] & S_IFMT) == S_IFREG) {
        # The current vendor package may rewrite this canonical defaults file.
        $self->_destination_matches(CANONICAL_DEFAULT, PACKAGE_DEFAULT_PATH, 4096)
            or die "unrecognized ChatGPT package-default file\n";
    } else {
        die "ChatGPT package-default compatibility path is not a file\n";
    }
    unlink PACKAGE_DEFAULT_PATH
        or die "cannot remove ChatGPT package-default compatibility path: $!\n";
    return 1;
}

sub _install_package_default_link {
    my ($self) = @_;
    APTRepoLocal::Servicing::Atomic->ensure_root_directory('/etc/default', 0755);
    $self->_clear_package_default_link();
    symlink DEFAULT_PATH, PACKAGE_DEFAULT_PATH
        or die "cannot publish ChatGPT package-default compatibility link: $!\n";
    return 1;
}

sub prepare_install {
    my ($self, $execution_context) = @_;
    $execution_context //= 'runtime';
    $execution_context eq 'installer' || $execution_context eq 'runtime'
        or die "ChatGPT preparation context is invalid\n";
    # A bad candidate must not remove the previous profile, establish a
    # diversion or publish package-script guards before it has been parsed.
    $self->_validate_policy_syntax(CANONICAL_APPARMOR);
    $self->_begin_policy_transaction($execution_context);
    $self->_install_managed_policy_files();
    # The vendor postinst removes its conventional disable symlink before
    # attempting a live AppArmor reload. A regular, root-owned guard survives
    # that check and keeps installer/runtime package transactions under the
    # managed finalization boundary.
    $self->_install_package_script_guard();
    $self->_install_package_default_link();
    return 1;
}

sub abort_install {
    my ($self) = @_;
    my $transaction = $self->{policy_transaction} or return 1;
    !$self->{policy_outcome_unknown}
        or die "ChatGPT policy writer outcome unknown; no competing rollback started; recovery retained at " . POLICY_RECOVERY . "\n";
    my $ok = eval {
        if ($transaction->{diversion} eq q{} && $self->_diversion_owner() ne q{}) {
            $self->_assert_diversion();
            system('/usr/bin/dpkg-divert', '--local', '--remove', '--no-rename',
                   '--divert', DIVERSION_PATH, APPARMOR_PATH) == 0
                or die "cannot restore previous ChatGPT diversion state\n";
        }
        for my $entry (@{$transaction->{previous}}) {
            my $path = $entry->{path};
            $self->_remove_file_or_symlink($path);
            if ($entry->{kind} eq 'file') {
                APTRepoLocal::Servicing::Atomic->_publish($path, $entry->{data}, $entry->{mode});
                chown $entry->{uid}, $entry->{gid}, $path or die "cannot restore ChatGPT policy ownership\n";
                chmod $entry->{mode}, $path or die "cannot restore ChatGPT policy mode\n";
                sysopen my $file, $path, O_RDONLY | O_NOFOLLOW or die "cannot open restored ChatGPT policy\n";
                $file->sync() or die "cannot synchronize restored ChatGPT policy\n";
            } elsif ($entry->{kind} eq 'link') {
                symlink $entry->{data}, $path or die "cannot restore ChatGPT policy link\n";
                my $ownership = capture_command(
                    argv => ['/usr/bin/chown', '-h', "$entry->{uid}:$entry->{gid}", '--', $path],
                    timeout => 5, limit => 1024,
                );
                $ownership->{status} == 0 or die "cannot restore ChatGPT policy link ownership\n";
            }
            $self->_sync_directory(dirname($path)) if -d dirname($path);
        }
        if ($transaction->{context} eq 'runtime') {
            # An absent previous profile or unavailable kernel interface cannot
            # prove removal of a newly loaded policy. Keep the durable record.
            -f APPARMOR_PATH && $self->_live_apparmor_interface_is_available()
                or die "previous loaded ChatGPT policy cannot be verified\n";
            $self->_reload_policy_if_available();
        }
        $self->_finish_policy_transaction();
        1;
    };
    die "ChatGPT rollback outcome unknown; recovery retained at " . POLICY_RECOVERY . ": " . ($@ || 'unknown failure') if !$ok;
    return 1;
}

sub _assert_root_owned_regular_executable {
    my ($self, $label, $path) = @_;
    APTRepoLocal::Servicing::Atomic->assert_absolute_path($label, $path);
    my @st = lstat $path;
    @st
        && ($st[2] & S_IFMT) == S_IFREG
        && !-l _
        && $st[4] == 0
        && $st[5] == 0
        && !($st[2] & 0022)
        && ($st[2] & 0001)
        or die "$label is unsafe\n";
    return 1;
}

sub _run_policy_syntax_validation {
    my ($self, $policy_path) = @_;
    $policy_path //= APPARMOR_PATH;
    my @command = (
        '/usr/bin/env', '-i',
        'LC_ALL=C.UTF-8',
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        APPARMOR_PARSER,
        '--debug',
        '--skip-kernel-load',
        '--skip-cache',
        '--Include', '/etc/apparmor.d',
        '--base', '/etc/apparmor.d',
        $policy_path,
    );
    my $result = capture_command(argv => \@command, timeout => 30, limit => 1_048_576);
    return $result->{status} == 0;
}

sub _validate_policy_syntax {
    my ($self, $policy_path) = @_;
    $policy_path //= APPARMOR_PATH;
    $policy_path eq APPARMOR_PATH || $policy_path eq CANONICAL_APPARMOR
        or die "ChatGPT policy validation path is unmanaged\n";
    $self->_root_owned_source_text($policy_path, 1024 * 1024);
    $self->_assert_root_owned_regular_executable(
        'managed ChatGPT AppArmor parser',
        APPARMOR_PARSER,
    );
    $self->_run_policy_syntax_validation($policy_path)
        or die "managed ChatGPT AppArmor policy failed offline validation\n";
    return 1;
}

sub _live_apparmor_interface_is_available {
    my ($self) = @_;
    return 0 if !-d APPARMOR_SECURITYFS || -l APPARMOR_SECURITYFS;
    return 0 if !-e APPARMOR_PROFILES_PATH
        || -l APPARMOR_PROFILES_PATH
        || !-r APPARMOR_PROFILES_PATH;
    return 1;
}

sub _run_managed_modes {
    my ($self) = @_;
    return with_policy_lock_handoff(sub {
        my $result;
        my $completed = eval {
            $result = capture_command(argv => [MANAGED_MODES_HELPER], timeout => 240, limit => 1_048_576);
            1;
        };
        if (!$completed || $result->{status} == (124 << 8)) {
            $self->{policy_outcome_unknown} = 1;
            die "managed AppArmor writer outcome unknown; recovery must be reconciled before rollback or retry\n";
        }
        return $result->{status} == 0;
    });
}

sub _reload_policy_if_available {
    my ($self) = @_;
    return 1 if !$self->_live_apparmor_interface_is_available();
    $self->_assert_root_owned_regular_executable(
        'managed AppArmor mode helper',
        MANAGED_MODES_HELPER,
    );
    $self->_run_managed_modes()
        or die "failed to reload managed AppArmor policy after ChatGPT repair\n";
    return 1;
}

sub _finalize_policy {
    my ($self, $execution_context) = @_;
    $execution_context eq 'installer' || $execution_context eq 'runtime'
        or die "ChatGPT finalization context is invalid\n";
    $self->_validate_policy_syntax();
    # The installer target can expose the installer's kernel paths; only an
    # explicit booted-runtime action may load policy into a live kernel.
    $self->_reload_policy_if_available() if $execution_context eq 'runtime';
    return 1;
}

sub finalize_install {
    my ($self, $execution_context) = @_;
    $execution_context //= 'runtime';
    $execution_context eq 'installer' || $execution_context eq 'runtime'
        or die "ChatGPT finalization context is invalid\n";
    $self->_validate_policy_syntax(CANONICAL_APPARMOR);
    $self->_begin_policy_transaction($execution_context);
    $self->_clear_package_default_link();
    $self->_install_managed_policy_files();
    $self->_clear_package_script_guard();
    # The package owns the pixmap path, so restore the managed 256x256 icon
    # only after every package transaction has completed.
    $self->_install_canonical_text(
        CANONICAL_ICON,
        ICON_PATH,
        0644,
        1024 * 1024,
    );
    APTRepoLocal::Servicing::Atomic->ensure_root_directory(
        '/usr/local/share/applications', 0755,
    );
    $self->_install_canonical_text(
        CANONICAL_DESKTOP,
        DESKTOP_PATH,
        0644,
        64 * 1024,
    );
    $self->_remove_vendor_repository_paths();
    system('/usr/bin/desktop-file-validate', DESKTOP_PATH) == 0
        or die "managed ChatGPT desktop entry failed validation\n";
    system('/usr/bin/update-desktop-database', '/usr/local/share/applications') == 0
        or die "managed ChatGPT desktop database refresh failed\n";
    $self->assert_policy();
    $self->_finalize_policy($execution_context);
    return 1;
}

sub commit_install { return $_[0]->_finish_policy_transaction(); }

sub policy_valid {
    my ($self) = @_;
    return eval {
        $self->enabled();
        $self->_assert_diversion();
        $self->_destination_matches(
            CANONICAL_DEFAULT,
            DEFAULT_PATH,
            4096,
        ) or die "managed ChatGPT defaults drifted\n";
        $self->_destination_matches(
            CANONICAL_APPARMOR,
            APPARMOR_PATH,
            1024 * 1024,
        ) or die "managed ChatGPT AppArmor policy drifted\n";
        $self->_destination_matches(
            CANONICAL_DESKTOP,
            DESKTOP_PATH,
            64 * 1024,
        ) or die "managed ChatGPT desktop entry drifted\n";
        $self->_destination_matches(
            CANONICAL_ICON,
            ICON_PATH,
            1024 * 1024,
        ) or die "managed ChatGPT icon drifted\n";
        for my $path (
            PACKAGE_DEFAULT_PATH,
            APPARMOR_DISABLE_PATH,
            VENDOR_SOURCE_PATH,
            VENDOR_LEGACY_SOURCE_PATH,
            VENDOR_KEYRING_PATH,
        ) {
            (!-e $path && !-l $path)
                or die "ChatGPT vendor policy path is active: $path\n";
        }
        1;
    } ? 1 : 0;
}

sub assert_policy {
    my ($self) = @_;
    $self->policy_valid()
        or die "managed ChatGPT package policy verification failed\n";
    return 1;
}

1;
