package LabwcNetworkControlAction::Client;

use strict;
use warnings;

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
            path => '/usr/local/bin:/usr/bin:/bin',
        );
    },
);

has root_helper => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/libexec/labwc-network-control-action-root' },
);

has self_path => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/bin/labwc-network-control-action' },
);

has validator => (
    is      => 'ro',
    default => sub { LabwcNetworkControlAction::Validation->new() },
);

sub _fatal {
    my ($self, $message) = @_;

    $message = 'network control action failed' if !defined($message) || $message eq q{};
    $message =~ s/[\r\n]+\z//;
    print STDERR "fatal: $message\n";
    return 1;
}

sub _notify {
    my ($self, $urgency, $summary, $body) = @_;

    return if !defined($ENV{DBUS_SESSION_BUS_ADDRESS}) || $ENV{DBUS_SESSION_BUS_ADDRESS} eq q{};
    my $notify_send = $self->command()->executable('notify-send');
    return if !defined $notify_send;
    $self->command()->run(
        $notify_send,
        '-a', 'Network',
        '-u', $urgency,
        '-i', 'network-workgroup',
        $summary,
        $body,
    );
    return;
}

sub _run_root_action {
    my ($self, @argv) = @_;

    my $pkexec = $self->command()->require_executable('pkexec');
    -x $self->root_helper()
        or die "privileged network control helper is unavailable: " . $self->root_helper() . "\n";
    return $self->command()->run($pkexec, $self->root_helper(), @argv);
}

sub _finish_status {
    my ($self, $status) = @_;

    printf "\n=== Action finished with status %s ===\n", $status;
    if (-t STDIN) {
        print 'Press Enter to close this terminal...';
        scalar <STDIN>;
    }
    return $status;
}

sub _show_dns_status {
    my ($self) = @_;

    my $nmcli = $self->command()->require_executable('nmcli');
    print "=== Active NetworkManager connections ===\n\n";
    $self->command()->run_or_die(
        'listing active NetworkManager connections',
        $nmcli, '--fields', 'NAME,UUID,TYPE,DEVICE', 'connection', 'show', '--active',
    );
    print "\n=== Device DNS configuration ===\n\n";
    $self->command()->run_or_die(
        'listing NetworkManager device DNS configuration',
        $nmcli, '--fields', 'GENERAL.DEVICE,GENERAL.CONNECTION,IP4.DNS,IP6.DNS', 'device', 'show',
    );
    if (my $resolvectl = $self->command()->executable('resolvectl')) {
        print "\n=== systemd-resolved status ===\n\n";
        $self->command()->run_or_die('showing systemd-resolved status', $resolvectl, 'status');
    }
    return 0;
}

sub _validate_request {
    my ($self, $action, @args) = @_;

    defined($action) && $action ne q{}
        or die "unsupported network control action: unset\n";

    my %interface_actions = (
        'enable-ethernet'  => ['Ethernet enabled',  'Enabled Ethernet adapter %s.'],
        'disable-ethernet' => ['Ethernet disabled', 'Disabled Ethernet adapter %s.'],
        'enable-wifi'      => ['WiFi enabled',      'Enabled WiFi adapter %s.'],
        'disable-wifi'     => ['WiFi disabled',     'Disabled WiFi adapter %s.'],
    );
    if (my $notification = $interface_actions{$action}) {
        @args == 1 or die "$action requires one interface\n";
        my $interface = $self->validator()->interface_name($args[0]);
        return ($action, [$interface], $notification->[0], sprintf($notification->[1], $interface));
    }

    if ($action =~ /\A(?:activate|deactivate)-(?:connection|vpn|wireguard)\z/) {
        @args == 1 or die "$action requires one connection UUID\n";
        my $uuid = $self->validator()->connection_uuid($args[0]);
        return (
            $action,
            [$uuid],
            'Connection updated',
            "Completed $action for NetworkManager connection $uuid.",
        );
    }

    if ($action eq 'import-openvpn' || $action eq 'import-wireguard') {
        @args == 2 or die "$action requires a profile and confirmation\n";
        $args[1] eq 'confirmed-network-action'
            or die(($action eq 'import-openvpn' ? 'OpenVPN' : 'WireGuard') . " import confirmation is missing\n");
        my ($label, $path);
        if ($action eq 'import-openvpn') {
            $label = 'OpenVPN profile';
            $path = $self->validator()->import_file(
                label     => $label,
                path      => $args[0],
                suffix    => '.ovpn',
                owner_uid => $<,
            );
        }
        else {
            $label = 'WireGuard profile';
            $path = $self->validator()->wireguard_import_file(path => $args[0]);
        }
        my $summary = $action eq 'import-openvpn'
            ? 'OpenVPN profile imported'
            : 'WireGuard profile imported';
        return ($action, [$path, $args[1]], $summary, "Imported the selected $label.");
    }

    if ($action eq 'restore-automatic-dns') {
        @args == 2 or die "restore-automatic-dns requires a UUID and confirmation\n";
        my $uuid = $self->validator()->connection_uuid($args[0]);
        $args[1] eq 'confirmed-network-action'
            or die "automatic DNS confirmation is missing\n";
        return (
            $action,
            [$uuid, $args[1]],
            'Automatic DNS restored',
            "Restored automatic DNS for connection $uuid.",
        );
    }

    if ($action eq 'set-custom-dns') {
        @args == 3 or die "set-custom-dns requires a UUID, DNS list, and confirmation\n";
        my $uuid = $self->validator()->connection_uuid($args[0]);
        $args[2] eq 'confirmed-network-action'
            or die "custom DNS confirmation is missing\n";
        my $servers = $self->validator()->normalize_dns_servers($args[1]);
        return (
            $action,
            [$uuid, $servers, $args[2]],
            'Custom DNS configured',
            "Applied custom DNS servers to connection $uuid.",
        );
    }

    if ($action eq 'flush-dns-cache' || $action eq 'randomize-macs') {
        @args == 1 or die "$action requires confirmation\n";
        $args[0] eq 'confirmed-network-action'
            or die(($action eq 'flush-dns-cache'
                ? 'DNS cache flush confirmation is missing'
                : 'managed network randomization confirmation is missing') . "\n");
        my ($summary, $body) = $action eq 'flush-dns-cache'
            ? ('DNS cache flushed', 'Flushed available managed DNS caches.')
            : ('MAC addresses randomized', 'Applied randomized MAC addresses to physical network adapters.');
        return ($action, [$args[0]], $summary, $body);
    }

    die "unsupported network control action: $action\n";
}

sub _run {
    my ($self, @argv) = @_;

    $> != 0
        or die "labwc-network-control-action must run as the logged-in desktop user\n";
    @argv or die "unsupported network control action: unset\n";

    if ($argv[0] eq '--run-status') {
        @argv == 2 or die "--run-status requires one status action\n";
        $argv[1] eq 'show-dns-status'
            or die "unsupported network status action: $argv[1]\n";
        my $status = $self->_show_dns_status();
        return $self->_finish_status($status);
    }

    if ($argv[0] eq 'show-dns-status') {
        @argv == 1 or die "show-dns-status does not accept arguments\n";
        my $terminal = $self->command()->require_executable('labwc-terminal');
        $self->command()->exec($terminal, '-e', $self->self_path(), '--run-status', 'show-dns-status');
    }

    my $action = shift @argv;
    my ($root_action, $root_args, $summary, $body) = $self->_validate_request($action, @argv);
    my $status = $self->_run_root_action($root_action, @{$root_args});
    if ($status == 0) {
        $self->_notify('normal', $summary, $body);
        return 0;
    }

    $self->_notify(
        'critical',
        'Network action failed',
        'The requested NetworkManager change did not complete.',
    );
    return $status;
}

sub run {
    my ($self, @argv) = @_;

    my $status = eval {
        local $ENV{PATH}   = '/usr/local/bin:/usr/bin:/bin';
        local $ENV{LC_ALL} = 'C.UTF-8';
        $self->_run(@argv);
    };
    return $status if defined($status) && !$@;
    return $self->_fatal($@ || 'network control action failed');
}

1;
