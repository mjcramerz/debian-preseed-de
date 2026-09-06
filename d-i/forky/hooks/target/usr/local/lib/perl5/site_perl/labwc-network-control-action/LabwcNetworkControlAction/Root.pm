package LabwcNetworkControlAction::Root;

use strict;
use warnings;

use File::Spec;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Str);

use LabwcNetworkControlAction::Command;
use LabwcNetworkControlAction::Validation;

has command => (
    is      => 'ro',
    default => sub {
        LabwcNetworkControlAction::Command->new(
            path => '/usr/sbin:/usr/bin:/sbin:/bin',
        );
    },
);

has sys_class_net => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/sys/class/net' },
);

has validator => (
    is      => 'ro',
    default => sub { LabwcNetworkControlAction::Validation->new() },
);

sub _fatal {
    my ($self, $message) = @_;

    $message = 'privileged network action failed' if !defined($message) || $message eq q{};
    $message =~ s/[\r\n]+\z//;
    print STDERR "fatal: $message\n";
    return 1;
}

sub _trim {
    my ($value) = @_;

    $value //= q{};
    $value =~ s/\A\s+//;
    $value =~ s/\s+\z//;
    return $value;
}

sub _read_small_file {
    my ($self, $path, $label) = @_;

    open my $handle, '<', $path
        or die "cannot read $label: $path: $!\n";
    my $content = q{};
    my $read = read $handle, $content, 4_096;
    defined($read)
        or die "cannot read $label: $path: $!\n";
    close $handle
        or die "cannot close $label: $path: $!\n";
    return _trim($content);
}

sub _require_pkexec_invoker {
    my ($self) = @_;

    my $uid = $ENV{PKEXEC_UID} // q{};
    $uid =~ /\A[1-9][0-9]*\z/
        or die "privileged network helper must be invoked by a non-root desktop user through pkexec\n";
    my $getent = $self->command()->require_executable('getent');
    my ($status, $record) = $self->command()->capture(
        argv => [$getent, 'passwd', $uid],
    );
    $status == 0 && _trim($record) ne q{}
        or die "pkexec invoking account does not exist: $uid\n";
    return $uid;
}

sub _interface_path {
    my ($self, $interface) = @_;

    $interface = $self->validator()->interface_name($interface);
    return File::Spec->catdir($self->sys_class_net(), $interface);
}

sub _validate_physical_interface {
    my ($self, $interface, $expected_type) = @_;

    $interface = $self->validator()->interface_name($interface);
    my $path = $self->_interface_path($interface);
    -d $path
        or die "network interface is unavailable: $interface\n";
    -e File::Spec->catfile($path, 'device')
        or die "network controls are restricted to physical adapters: $interface\n";
    $self->_read_small_file(File::Spec->catfile($path, 'type'), 'network interface type') eq '1'
        or die "network controls require an Ethernet-compatible adapter: $interface\n";

    if ($expected_type eq 'ethernet') {
        !-d File::Spec->catdir($path, 'wireless')
            or die "selected interface is WiFi, not Ethernet: $interface\n";
    }
    elsif ($expected_type eq 'wifi') {
        -d File::Spec->catdir($path, 'wireless')
            or die "selected interface is Ethernet, not WiFi: $interface\n";
    }
    else {
        die "unsupported physical adapter type: $expected_type\n";
    }
    return $interface;
}

sub _ifupdown_configured {
    my ($self, $interface) = @_;

    my $ifquery = $self->command()->executable('ifquery');
    return 0 if !defined $ifquery;
    my ($status) = $self->command()->capture(argv => [$ifquery, $interface]);
    return $status == 0 ? 1 : 0;
}

sub _ifupdown_is_up {
    my ($self, $interface) = @_;

    my $ifquery = $self->command()->executable('ifquery');
    return 0 if !defined $ifquery;
    my ($status) = $self->command()->capture(argv => [$ifquery, '--state', $interface]);
    return $status == 0 ? 1 : 0;
}

sub _networkmanager_running {
    my ($self) = @_;

    my $nmcli = $self->command()->executable('nmcli');
    return 0 if !defined $nmcli;
    my ($status, $output) = $self->command()->capture(
        argv => [$nmcli, '--terse', '--fields', 'RUNNING', 'general'],
    );
    return $status == 0 && _trim($output) eq 'running' ? 1 : 0;
}

sub _require_networkmanager {
    my ($self) = @_;

    $self->command()->require_executable('nmcli');
    $self->_networkmanager_running()
        or die "NetworkManager is not running\n";
    return;
}

sub _networkmanager_managed {
    my ($self, $interface) = @_;

    return 0 if !$self->_networkmanager_running();
    my $nmcli = $self->command()->require_executable('nmcli');
    my ($status, $output) = $self->command()->capture(
        argv => [$nmcli, '--get-values', 'GENERAL.NM-MANAGED', 'device', 'show', $interface],
    );
    return $status == 0 && _trim($output) eq 'yes' ? 1 : 0;
}

sub _active_connection_uuid {
    my ($self, $interface) = @_;

    return q{} if !$self->_networkmanager_running();
    my $nmcli = $self->command()->require_executable('nmcli');
    my ($status, $output) = $self->command()->capture(
        argv => [
            $nmcli, '--terse', '--escape', 'no', '--fields', 'DEVICE,UUID',
            'connection', 'show', '--active',
        ],
    );
    return q{} if $status != 0;
    for my $line (split /\n/, $output) {
        next if $line !~ /\A\Q$interface\E:(.+)\z/;
        return $self->validator()->connection_uuid(
            $1,
            'NetworkManager returned an invalid connection UUID',
        );
    }
    return q{};
}

sub _connection_type {
    my ($self, $uuid) = @_;

    $self->_require_networkmanager();
    $uuid = $self->validator()->connection_uuid(
        $uuid,
        'NetworkManager returned an invalid connection UUID',
    );
    my $nmcli = $self->command()->require_executable('nmcli');
    my ($status, $output) = $self->command()->capture(
        argv => [$nmcli, '--get-values', 'connection.type', 'connection', 'show', 'uuid', $uuid],
    );
    my $type = _trim($output);
    $status == 0 && $type ne q{}
        or die "NetworkManager connection does not exist: $uuid\n";
    return $type;
}

sub _validate_connection_type {
    my ($self, $uuid, $expected_type) = @_;

    my $actual_type = $self->_connection_type($uuid);
    $actual_type eq $expected_type
        or die "connection $uuid has type $actual_type, expected $expected_type\n";
    return;
}

sub _connection_is_active {
    my ($self, $uuid) = @_;

    my $nmcli = $self->command()->require_executable('nmcli');
    my ($status, $output) = $self->command()->capture(
        argv => [$nmcli, '--terse', '--fields', 'UUID', 'connection', 'show', '--active'],
    );
    return 0 if $status != 0;
    my $expected = lc $uuid;
    return scalar grep { lc(_trim($_)) eq $expected } split /\n/, $output;
}

sub _reactivate_connection_if_active {
    my ($self, $uuid) = @_;

    return if !$self->_connection_is_active($uuid);
    my $nmcli = $self->command()->require_executable('nmcli');
    $self->command()->run_or_die(
        'reactivating the NetworkManager connection',
        $nmcli, '--wait', '60', 'connection', 'up', 'uuid', $uuid,
    );
    return;
}

sub _import_network_profile {
    my ($self, $type, $path, $confirmation, $invoker_uid) = @_;

    $confirmation eq 'confirmed-network-action'
        or die(($type eq 'openvpn' ? 'OpenVPN' : 'WireGuard') . " import confirmation is missing\n");
    if ($type eq 'openvpn') {
        $path = $self->validator()->import_file(
            label     => 'OpenVPN profile',
            path      => $path,
            suffix    => '.ovpn',
            owner_uid => $invoker_uid,
        );
    }
    elsif ($type eq 'wireguard') {
        $path = $self->validator()->wireguard_import_file(path => $path);
    }
    else {
        die "unsupported NetworkManager import type: $type\n";
    }
    $self->_require_networkmanager();
    my $nmcli = $self->command()->require_executable('nmcli');
    $self->command()->exec($nmcli, '--wait', '30', 'connection', 'import', 'type', $type, 'file', $path);
}

sub _restore_automatic_dns {
    my ($self, $uuid) = @_;

    $self->_connection_type($uuid);
    my $nmcli = $self->command()->require_executable('nmcli');
    $self->command()->run_or_die(
        'restoring automatic DNS',
        $nmcli, '--wait', '30', 'connection', 'modify', 'uuid', $uuid,
        'ipv4.ignore-auto-dns', 'no',
        'ipv6.ignore-auto-dns', 'no',
        'ipv4.dns', q{},
        'ipv6.dns', q{},
    );
    $self->_reactivate_connection_if_active($uuid);
    return 0;
}

sub _set_custom_dns {
    my ($self, $uuid, $servers) = @_;

    $self->_connection_type($uuid);
    my ($ipv4_dns, $ipv6_dns) = $self->validator()->normalize_dns_families($servers);
    my $nmcli = $self->command()->require_executable('nmcli');
    $self->command()->run_or_die(
        'configuring custom DNS',
        $nmcli, '--wait', '30', 'connection', 'modify', 'uuid', $uuid,
        'ipv4.ignore-auto-dns', 'yes',
        'ipv6.ignore-auto-dns', 'yes',
        'ipv4.dns', $ipv4_dns,
        'ipv6.dns', $ipv6_dns,
    );
    $self->_reactivate_connection_if_active($uuid);
    return 0;
}

sub _flush_dns_cache {
    my ($self) = @_;

    $self->_require_networkmanager();
    my $nmcli = $self->command()->require_executable('nmcli');
    $self->command()->run_or_die('reloading NetworkManager DNS', $nmcli, 'general', 'reload', 'dns-rc');
    if (my $resolvectl = $self->command()->executable('resolvectl')) {
        $self->command()->run_or_die('flushing systemd-resolved DNS cache', $resolvectl, 'flush-caches');
    }
    return 0;
}

sub _enable_interface {
    my ($self, $interface, $type) = @_;

    if ($type eq 'wifi') {
        if (my $rfkill = $self->command()->executable('rfkill')) {
            $self->command()->run($rfkill, 'unblock', 'wlan');
        }
    }
    if ($self->_ifupdown_configured($interface)) {
        my $ifup = $self->command()->require_executable('ifup');
        $self->command()->exec($ifup, $interface);
    }
    if ($self->_networkmanager_managed($interface)) {
        my $nmcli = $self->command()->require_executable('nmcli');
        if ($type eq 'wifi') {
            $self->command()->run_or_die('enabling NetworkManager WiFi radio', $nmcli, '--wait', '30', 'radio', 'wifi', 'on');
        }
        $self->command()->exec($nmcli, '--wait', '60', 'device', 'connect', $interface);
    }
    my $ip = $self->command()->require_executable('ip');
    $self->command()->exec($ip, 'link', 'set', 'dev', $interface, 'up');
}

sub _disable_interface {
    my ($self, $interface) = @_;

    if ($self->_ifupdown_configured($interface)) {
        my $ifdown = $self->command()->require_executable('ifdown');
        $self->command()->exec($ifdown, $interface);
    }
    if ($self->_networkmanager_managed($interface)) {
        my $nmcli = $self->command()->require_executable('nmcli');
        $self->command()->exec($nmcli, '--wait', '30', 'device', 'disconnect', $interface);
    }
    my $ip = $self->command()->require_executable('ip');
    $self->command()->exec($ip, 'link', 'set', 'dev', $interface, 'down');
}

sub _generate_random_mac {
    my ($self) = @_;

    open my $random, '<', '/dev/urandom'
        or die "cannot open /dev/urandom: $!\n";
    my $read = read $random, my $bytes, 6;
    defined($read) && $read == 6
        or die "short read from /dev/urandom\n";
    close $random
        or die "cannot close /dev/urandom: $!\n";
    my @octets = unpack 'C6', $bytes;
    $octets[0] = ($octets[0] | 0x02) & 0xfe;
    return join q{:}, map { sprintf '%02x', $_ } @octets;
}

sub _interface_is_up {
    my ($self, $interface) = @_;

    my $path = File::Spec->catfile($self->_interface_path($interface), 'flags');
    my $flags = $self->_read_small_file($path, 'network interface flags');
    $flags =~ /\A0x[0-9A-Fa-f]+\z/
        or die "network interface flags are invalid: $interface\n";
    return hex($flags) & 1 ? 1 : 0;
}

sub _randomize_direct_interface {
    my ($self, $interface) = @_;

    my $was_up = 0;
    my $managed_by_ifupdown = $self->_ifupdown_configured($interface);
    if ($managed_by_ifupdown) {
        $was_up = $self->_ifupdown_is_up($interface);
        my $ifdown = $self->command()->require_executable('ifdown');
        $self->command()->run_or_die('bringing interface down before MAC randomization', $ifdown, $interface);
    }
    else {
        $was_up = $self->_interface_is_up($interface);
        my $ip = $self->command()->require_executable('ip');
        $self->command()->run_or_die('bringing interface down before MAC randomization', $ip, 'link', 'set', 'dev', $interface, 'down');
    }

    my $mac = $self->_generate_random_mac();
    $mac =~ /\A(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\z/
        or die "generated MAC address is invalid\n";
    my $ip = $self->command()->require_executable('ip');
    $self->command()->run_or_die('setting randomized MAC address', $ip, 'link', 'set', 'dev', $interface, 'address', $mac);

    return if !$was_up;
    if ($managed_by_ifupdown) {
        my $ifup = $self->command()->require_executable('ifup');
        $self->command()->run_or_die('restoring interface after MAC randomization', $ifup, $interface);
    }
    else {
        $self->command()->run_or_die('restoring interface after MAC randomization', $ip, 'link', 'set', 'dev', $interface, 'up');
    }
    return;
}

sub _randomize_networkmanager_profiles {
    my ($self) = @_;

    return 0 if !$self->_networkmanager_running();
    my $nmcli = $self->command()->require_executable('nmcli');
    my ($all_status, $all_output) = $self->command()->capture(
        argv => [$nmcli, '--terse', '--fields', 'UUID', 'connection', 'show'],
    );
    $all_status == 0 or die "cannot list NetworkManager connection profiles\n";
    my ($active_status, $active_output) = $self->command()->capture(
        argv => [$nmcli, '--terse', '--fields', 'UUID', 'connection', 'show', '--active'],
    );
    $active_status == 0 or die "cannot list active NetworkManager connection profiles\n";

    my $modified = 0;
    for my $uuid (grep { $_ ne q{} } map { _trim($_) } split /\n/, $all_output) {
        $uuid = $self->validator()->connection_uuid($uuid, 'NetworkManager returned an invalid connection UUID');
        my $type = $self->_connection_type($uuid);
        my $property = $type eq '802-3-ethernet'
            ? '802-3-ethernet.cloned-mac-address'
            : $type eq '802-11-wireless'
                ? '802-11-wireless.cloned-mac-address'
                : undef;
        next if !defined $property;
        $self->command()->run_or_die(
            'setting randomized NetworkManager profile MAC address',
            $nmcli, '--wait', '30', 'connection', 'modify', 'uuid', $uuid, $property, 'random',
        );
        ++$modified;
    }

    for my $uuid (grep { $_ ne q{} } map { _trim($_) } split /\n/, $active_output) {
        $uuid = $self->validator()->connection_uuid($uuid, 'NetworkManager returned an invalid connection UUID');
        my $type = $self->_connection_type($uuid);
        next if $type ne '802-3-ethernet' && $type ne '802-11-wireless';
        $self->command()->run_or_die(
            'deactivating NetworkManager profile for MAC randomization',
            $nmcli, '--wait', '30', 'connection', 'down', 'uuid', $uuid,
        );
        $self->command()->run_or_die(
            'reactivating NetworkManager profile after MAC randomization',
            $nmcli, '--wait', '60', 'connection', 'up', 'uuid', $uuid,
        );
    }
    return $modified;
}

sub _randomize_physical_adapters {
    my ($self) = @_;

    $self->command()->require_executable('ip');
    my $profile_count = $self->_randomize_networkmanager_profiles();
    $profile_count =~ /\A[0-9]+\z/
        or die "invalid NetworkManager randomized profile count\n";

    opendir my $directory, $self->sys_class_net()
        or die "cannot read network interface directory " . $self->sys_class_net() . ": $!\n";
    my $direct_count = 0;
    while (my $interface = readdir $directory) {
        next if $interface eq q{.} || $interface eq q{..};
        next if $interface !~ /\A[A-Za-z0-9_.-]+\z/;
        my $path = File::Spec->catdir($self->sys_class_net(), $interface);
        next if !-e File::Spec->catfile($path, 'device');
        next if $self->_read_small_file(File::Spec->catfile($path, 'type'), 'network interface type') ne '1';
        if ($self->_networkmanager_managed($interface)) {
            my $active_uuid = $self->_active_connection_uuid($interface);
            next if $active_uuid ne q{};
        }
        $self->_randomize_direct_interface($interface);
        ++$direct_count;
    }
    closedir $directory
        or die "cannot close network interface directory " . $self->sys_class_net() . ": $!\n";

    my $total = $profile_count + $direct_count;
    $total > 0
        or die "no physical Ethernet or WiFi adapters or profiles were available\n";
    printf "randomized network targets: profiles=%s direct-adapters=%s\n", $profile_count, $direct_count;
    return 0;
}

sub _dispatch {
    my ($self, $invoker_uid, $action, @args) = @_;

    if ($action eq 'enable-ethernet' || $action eq 'disable-ethernet') {
        @args == 1 or die "$action requires one interface\n";
        my $interface = $self->_validate_physical_interface($args[0], 'ethernet');
        return $action eq 'enable-ethernet'
            ? $self->_enable_interface($interface, 'ethernet')
            : $self->_disable_interface($interface);
    }
    if ($action eq 'enable-wifi' || $action eq 'disable-wifi') {
        @args == 1 or die "$action requires one interface\n";
        my $interface = $self->_validate_physical_interface($args[0], 'wifi');
        return $action eq 'enable-wifi'
            ? $self->_enable_interface($interface, 'wifi')
            : $self->_disable_interface($interface);
    }
    if ($action eq 'activate-connection') {
        @args == 1 or die "$action requires one connection UUID\n";
        my $uuid = $self->validator()->connection_uuid($args[0], 'NetworkManager returned an invalid connection UUID');
        $self->_connection_type($uuid);
        my $nmcli = $self->command()->require_executable('nmcli');
        $self->command()->exec($nmcli, '--wait', '60', 'connection', 'up', 'uuid', $uuid);
    }
    if ($action eq 'deactivate-connection') {
        @args == 1 or die "$action requires one connection UUID\n";
        my $uuid = $self->validator()->connection_uuid($args[0], 'NetworkManager returned an invalid connection UUID');
        $self->_connection_type($uuid);
        $self->_connection_is_active($uuid)
            or die "NetworkManager connection is not active: $uuid\n";
        my $nmcli = $self->command()->require_executable('nmcli');
        $self->command()->exec($nmcli, '--wait', '30', 'connection', 'down', 'uuid', $uuid);
    }
    if ($action eq 'activate-vpn' || $action eq 'deactivate-vpn') {
        @args == 1 or die "$action requires one connection UUID\n";
        my $uuid = $self->validator()->connection_uuid($args[0], 'NetworkManager returned an invalid connection UUID');
        $self->_validate_connection_type($uuid, 'vpn');
        if ($action eq 'deactivate-vpn') {
            $self->_connection_is_active($uuid)
                or die "VPN connection is not active: $uuid\n";
        }
        my $nmcli = $self->command()->require_executable('nmcli');
        $self->command()->exec(
            $nmcli, '--wait', $action eq 'activate-vpn' ? '60' : '30',
            'connection', $action eq 'activate-vpn' ? 'up' : 'down', 'uuid', $uuid,
        );
    }
    if ($action eq 'activate-wireguard' || $action eq 'deactivate-wireguard') {
        @args == 1 or die "$action requires one connection UUID\n";
        my $uuid = $self->validator()->connection_uuid($args[0], 'NetworkManager returned an invalid connection UUID');
        $self->_validate_connection_type($uuid, 'wireguard');
        if ($action eq 'deactivate-wireguard') {
            $self->_connection_is_active($uuid)
                or die "WireGuard connection is not active: $uuid\n";
        }
        my $nmcli = $self->command()->require_executable('nmcli');
        $self->command()->exec(
            $nmcli, '--wait', $action eq 'activate-wireguard' ? '60' : '30',
            'connection', $action eq 'activate-wireguard' ? 'up' : 'down', 'uuid', $uuid,
        );
    }
    if ($action eq 'import-openvpn' || $action eq 'import-wireguard') {
        @args == 2 or die "$action requires a profile and confirmation\n";
        return $self->_import_network_profile(
            $action eq 'import-openvpn' ? 'openvpn' : 'wireguard',
            $args[0], $args[1], $invoker_uid,
        );
    }
    if ($action eq 'restore-automatic-dns') {
        @args == 2 or die "$action requires a UUID and confirmation\n";
        $args[1] eq 'confirmed-network-action'
            or die "automatic DNS confirmation is missing\n";
        return $self->_restore_automatic_dns($args[0]);
    }
    if ($action eq 'set-custom-dns') {
        @args == 3 or die "$action requires a UUID, DNS list, and confirmation\n";
        $args[2] eq 'confirmed-network-action'
            or die "custom DNS confirmation is missing\n";
        return $self->_set_custom_dns($args[0], $args[1]);
    }
    if ($action eq 'flush-dns-cache') {
        @args == 1 or die "$action requires confirmation\n";
        $args[0] eq 'confirmed-network-action'
            or die "DNS cache flush confirmation is missing\n";
        return $self->_flush_dns_cache();
    }
    if ($action eq 'randomize-macs') {
        @args == 1 or die "$action requires confirmation\n";
        $args[0] eq 'confirmed-network-action'
            or die "managed network randomization confirmation is missing\n";
        return $self->_randomize_physical_adapters();
    }
    die "unsupported privileged network control action: " . (defined($action) ? $action : 'unset') . "\n";
}

sub run {
    my ($self, @argv) = @_;

    return $self->_fatal('privileged network helper must run as root') if $> != 0;
    my $status = eval {
        local $ENV{PATH}   = '/usr/sbin:/usr/bin:/sbin:/bin';
        local $ENV{LC_ALL} = 'C.UTF-8';
        my $invoker_uid = $self->_require_pkexec_invoker();
        @argv or die "usage: labwc-network-control-action-root <action> [argument]\n";
        my $action = shift @argv;
        $self->_dispatch($invoker_uid, $action, @argv);
    };
    return $status if defined($status) && !$@;
    return $self->_fatal($@ || 'privileged network action failed');
}

1;
