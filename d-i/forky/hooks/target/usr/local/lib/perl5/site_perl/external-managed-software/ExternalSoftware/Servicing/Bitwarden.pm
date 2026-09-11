package ExternalSoftware::Servicing::Bitwarden;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Fcntl qw(S_ISREG);
use ExternalSoftware::Servicing::Atomic;

sub _trusted_text {
    my ($self, $path, $limit) = @_;
    my @st = lstat $path;
    return undef if !@st
        || !S_ISREG($st[2])
        || $st[4] != 0
        || ($st[2] & 0022);
    my $text = eval {
        ExternalSoftware::Servicing::Atomic->read_limited($path, $limit);
    };
    return undef if $@;
    return $text;
}

sub _contains_all {
    my ($self, $text, $fragments) = @_;
    for my $fragment (@{$fragments}) {
        return 0 if index($text, $fragment) < 0;
    }
    return 1;
}

sub policy_valid {
    my ($self) = @_;
    my @requirements = (
        [
            '/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py',
            [
                '"bitwarden": {',
                '"exec": "/opt/Bitwarden/bitwarden"',
                '"ELECTRON_OZONE_PLATFORM_HINT": "wayland"',
                '"args": electron_args("bitwarden", "launch")',
            ],
        ],
        [
            '/usr/local/lib/python3.14/dist-packages/labwc_managed_app/electron.py',
            [
                'ELECTRON_PASSWORD_STORE = "--password-store=gnome-libsecret"',
                'features = ("UseOzonePlatform", *profile["features"])',
                'args.append(electron_password_store_arg(app_name))',
            ],
        ],
        [
            '/usr/local/lib/python3.14/dist-packages/labwc_managed_app/session.py',
            [
                'def bitwarden_session_unit_argv(',
                '"--property=After=labwc-session.target labwc-kwallet-portal.service"',
                '"--property=Requires=labwc-session.target labwc-kwallet-portal.service"',
                '"--property=Requisite=labwc-session.target labwc-kwallet-portal.service"',
                '"--property=PartOf=labwc-session.target labwc-kwallet-portal.service"',
            ],
        ],
        [
            '/etc/skel-desktop/.config/systemd/user/labwc-kwallet-portal.service',
            [
                'Type=dbus',
                'BusName=org.freedesktop.secrets',
                'Environment=QT_QPA_PLATFORM=wayland',
                'ExecStart=/usr/bin/ksecretd',
                'ExecStartPost=/usr/local/libexec/labwc-session-check kwallet-ready',
            ],
        ],
        [
            '/etc/skel-desktop/.local/share/dbus-1/services/org.freedesktop.secrets.service',
            [
                'Name=org.freedesktop.secrets',
                'QT_QPA_PLATFORM=wayland',
                'SystemdService=labwc-kwallet-portal.service',
            ],
        ],
        [
            '/etc/skel-desktop/.config/kwalletrc',
            [
                '[org.freedesktop.secrets]',
                'apiEnabled=true',
            ],
        ],
        [
            '/etc/apparmor.d/opt.Bitwarden.bitwarden',
            [
                'profile bitwarden /opt/Bitwarden/bitwarden',
                '#include <abstractions/managed-electron-application>',
                'owner @{HOME}/.config/Bitwarden/** rwkl,',
                'owner @{HOME}/.local/share/Bitwarden/** rwkl,',
            ],
        ],
        [
            '/etc/apparmor.d/abstractions/managed-electron-application',
            ['#include <abstractions/managed-electron-runtime>'],
        ],
        [
            '/etc/apparmor.d/abstractions/managed-electron-runtime',
            ['#include <abstractions/managed-desktop-runtime>'],
        ],
        [
            '/etc/apparmor.d/abstractions/managed-desktop-runtime',
            [
                'include if exists <abstractions/dbus-session>',
                'owner /run/user/[0-9]*/wayland-[0-9]* rw,',
            ],
        ],
        [
            '/etc/apparmor.d/managed-labwc-session',
            [
                'profile managed-ksecretd /usr/bin/ksecretd flags=(attach_disconnected, mediate_deleted)',
                'owner @{HOME}/.config/{kwallet*,ksecret*,kdeglobals}* rwkl,',
                'owner link "@{HOME}/.config/kwalletrc.*" -> "@{HOME}/.config/#[0-9]*",',
                'owner @{HOME}/.local/share/{kwalletd,ksecretd}/** rwklm,',
                'owner link "@{HOME}/.local/share/kwalletd/*.{kwl,json}.*" -> "@{HOME}/.local/share/kwalletd/#[0-9]*",',
            ],
        ],
    );

    for my $requirement (@requirements) {
        my ($path, $fragments) = @{$requirement};
        my $text = $self->_trusted_text($path, 1_048_576);
        return 0 if !defined $text || !$self->_contains_all($text, $fragments);
    }
    return 1;
}

1;
