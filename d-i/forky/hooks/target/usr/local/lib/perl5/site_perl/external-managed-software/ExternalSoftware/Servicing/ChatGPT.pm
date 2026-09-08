package ExternalSoftware::Servicing::ChatGPT;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Fcntl qw(S_IFMT S_IFREG);
use ExternalSoftware::Servicing::Atomic;

has state => (is => 'ro', required => 1);

use constant ENABLE_STATE              => 'chatgpt.enabled';
use constant ENABLE_STATE_CONTENT      => "addon/devops\n";
use constant CANONICAL_DIRECTORY       => '/usr/local/share/software/chatgpt';
use constant CANONICAL_DEFAULT         => CANONICAL_DIRECTORY . '/default';
use constant CANONICAL_DESKTOP         => CANONICAL_DIRECTORY . '/chatgpt.desktop';
use constant CANONICAL_APPARMOR        => CANONICAL_DIRECTORY . '/apparmor.profile';
use constant CANONICAL_ICON            => CANONICAL_DIRECTORY . '/chatgpt.png';
use constant DEFAULT_PATH              => '/etc/default/chatgpt';
use constant DESKTOP_PATH              => '/usr/share/applications/chatgpt.desktop';
use constant ICON_PATH                 => '/usr/share/pixmaps/chatgpt.png';
use constant APPARMOR_PATH             => '/etc/apparmor.d/chatgpt';
use constant APPARMOR_DISABLE_DIRECTORY => '/etc/apparmor.d/disable';
use constant APPARMOR_DISABLE_PATH     => '/etc/apparmor.d/disable/chatgpt';
use constant PACKAGE_SCRIPT_GUARD_CONTENT => "managed ChatGPT package transaction\n";
use constant DIVERSION_PATH            => '/var/lib/software/vendor/chatgpt.apparmor';
use constant VENDOR_SOURCE_PATH        => '/etc/apt/sources.list.d/chatgpt.sources';
use constant VENDOR_LEGACY_SOURCE_PATH => '/etc/apt/sources.list.d/chatgpt.list';
use constant VENDOR_KEYRING_PATH       => '/usr/share/keyrings/chatgpt-archive-keyring.gpg';
use constant MANAGED_MODES_HELPER      => '/usr/local/libexec/apparmor-managed-modes-run';
use constant APPARMOR_PARSER           => '/usr/sbin/apparmor_parser';
use constant APPARMOR_SECURITYFS       => '/sys/kernel/security/apparmor';
use constant APPARMOR_PROFILES_PATH    => APPARMOR_SECURITYFS . '/profiles';

sub spec {
    return {
        name       => 'chatgpt',
        label      => 'ChatGPT/Codex Desktop',
        url        => 'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb',
        maximum    => 536_870_912,
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
    open my $fh, '-|', @command
        or die "failed to execute ChatGPT policy query\n";
    my $output = do { local $/; <$fh> // q{} };
    close $fh
        or die "ChatGPT policy query failed\n";
    return $output;
}

sub _root_owned_source_text {
    my ($self, $path, $maximum) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path(
        'ChatGPT canonical asset',
        $path,
    );
    my @st = lstat $path;
    @st && ($st[2] & S_IFMT) == S_IFREG && !-l _ && $st[4] == 0 && $st[5] == 0
        && !($st[2] & 0022)
        or die "ChatGPT canonical asset is unsafe: $path\n";
    return ExternalSoftware::Servicing::Atomic->read_limited($path, $maximum);
}

sub _install_canonical_text {
    my ($self, $source, $destination, $mode, $maximum) = @_;
    my $content = $self->_root_owned_source_text($source, $maximum);
    ExternalSoftware::Servicing::Atomic->write_text(
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
        eq ExternalSoftware::Servicing::Atomic->read_limited($destination, $maximum);
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
        ExternalSoftware::Servicing::Atomic->read_limited(
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
    ExternalSoftware::Servicing::Atomic->ensure_root_directory(
        APPARMOR_DISABLE_DIRECTORY,
        0755,
    );
    $self->_clear_package_script_guard();
    ExternalSoftware::Servicing::Atomic->write_text(
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
    ExternalSoftware::Servicing::Atomic->ensure_root_directory(
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

sub prepare_install {
    my ($self) = @_;
    $self->_install_managed_policy_files();
    # The vendor postinst removes its conventional disable symlink before
    # attempting a live AppArmor reload. A regular, root-owned guard survives
    # that check and keeps installer/runtime package transactions under the
    # managed finalization boundary.
    $self->_install_package_script_guard();
    return 1;
}

sub abort_install {
    my ($self) = @_;
    $self->_clear_package_script_guard();
    $self->_remove_vendor_repository_paths();
    return 1;
}

sub _assert_root_owned_regular_executable {
    my ($self, $label, $path) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path($label, $path);
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
    my ($self) = @_;
    return system(
        '/usr/bin/env', '-i',
        'LC_ALL=C.UTF-8',
        'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        APPARMOR_PARSER,
        '--debug',
        '--skip-kernel-load',
        '--skip-cache',
        '--Include', '/etc/apparmor.d',
        '--base', '/etc/apparmor.d',
        APPARMOR_PATH,
    ) == 0;
}

sub _validate_policy_syntax {
    my ($self) = @_;
    $self->_assert_root_owned_regular_executable(
        'managed ChatGPT AppArmor parser',
        APPARMOR_PARSER,
    );
    $self->_run_policy_syntax_validation()
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
    return system(MANAGED_MODES_HELPER) == 0;
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
    $self->_install_canonical_text(
        CANONICAL_DESKTOP,
        DESKTOP_PATH,
        0644,
        64 * 1024,
    );
    $self->_remove_vendor_repository_paths();
    system('/usr/bin/desktop-file-validate', DESKTOP_PATH) == 0
        or die "managed ChatGPT desktop entry failed validation\n";
    system('/usr/bin/update-desktop-database', '/usr/share/applications') == 0
        or die "managed ChatGPT desktop database refresh failed\n";
    $self->assert_policy();
    $self->_finalize_policy($execution_context);
    return 1;
}

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
