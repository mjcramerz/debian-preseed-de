package LabwcNetworkScanAction::Client;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Str);

use LabwcNetworkScanAction::Command;
use LabwcNetworkScanAction::Validation;

has command => (
    is      => 'ro',
    default => sub {
        LabwcNetworkScanAction::Command->new(
            path => '/usr/local/bin:/usr/bin:/bin',
        );
    },
);

has root_helper => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/libexec/labwc-network-scan-action-root' },
);

has self_path => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/bin/labwc-network-scan-action' },
);

has validator => (
    is      => 'ro',
    default => sub { LabwcNetworkScanAction::Validation->new() },
);

sub _fatal {
    my ($self, $message) = @_;

    $message = 'network scanning action failed' if !defined($message) || $message eq q{};
    $message =~ s/[\r\n]+\z//;
    print STDERR "fatal: $message\n";
    $self->_notify(1, 'requested-action');
    return 1;
}

sub _notify {
    my ($self, $status, $action) = @_;

    return if !defined($ENV{DBUS_SESSION_BUS_ADDRESS}) || $ENV{DBUS_SESSION_BUS_ADDRESS} eq q{};
    my $notify_send = $self->command()->executable('notify-send');
    return if !defined $notify_send;
    my ($urgency, $icon, $timeout, $summary, $body) = $status == 0
        ? (
            'normal',
            'network-workgroup',
            10_000,
            'Network scan completed',
            "The ${action} action completed successfully.",
        )
        : (
            'critical',
            'dialog-error',
            0,
            'Network scan failed',
            "The ${action} action failed with status ${status}.",
        );
    $self->command()->run(
        $notify_send,
        '-a', 'Network Scanning',
        '-u', $urgency,
        '-i', $icon,
        '-c', 'x-labwc.maintenance',
        '-t', $timeout,
        $summary,
        $body,
    );
    return;
}

sub _home {
    my ($self) = @_;

    return $ENV{HOME} // q{};
}

sub _require_capture_group {
    my ($self) = @_;

    my @group = getgrnam('wireshark');
    @group
        or die "the wireshark group is unavailable\n";
    my $wireshark_gid = $group[2];
    my %groups = map { $_ => 1 } grep { /\A[0-9]+\z/ } split /\s+/, "$)";
    $groups{$wireshark_gid}
        or die "the desktop session is not in the wireshark group; log out and back in after installation\n";
    return;
}

sub _validate_request_shape {
    my ($self, $action, @args) = @_;

    my %no_arguments = map { $_ => 1 } qw(
      dumpcap-list-interfaces tcpdump-list-interfaces wireshark-launch show-listening-ports
    );
    if ($no_arguments{$action}) {
        @args == 0 or die "$action does not accept arguments\n";
        return;
    }
    if ($action =~ /\A(?:dumpcap-capture-(?:general|dns|dhcp|tls|discovery)|tcpdump-capture-(?:general|dns|dhcp|icmp|arp|syn)|tcpdump-print-summary|tshark-live-(?:endpoints|dns|tls|retransmissions))\z/) {
        @args == 1 or die "$action requires one capture interface\n";
        $self->validator()->interface_name($args[0]);
        return;
    }
    if ($action =~ /\Anmap-(?:discovery|inventory|approved-services|tls-settings|http-headers|compliance|ssh-settings|smb-settings|dns-settings|common-ports|full-tcp)\z/) {
        @args == 2 or die "$action requires a target and scope authorization\n";
        $args[0] =~ m{\A[0-9./]+\z}
            or die "scan target contains unsupported characters\n";
        ($args[1] eq 'private-scan' || $args[1] eq 'authorized-wan-scan')
            or die "scan target scope authorization is invalid\n";
        return;
    }
    if ($action =~ /\A(?:tshark-file-(?:protocols|conversations|dns|tls|http-errors)|wireshark-open-capture)\z/) {
        @args == 1 or die "$action requires one capture file\n";
        return;
    }
    die "unsupported network scanning action: " . (defined($action) ? $action : 'unset') . "\n";
}

sub _validate_capture_interface_available {
    my ($self, $interface) = @_;

    $interface = $self->validator()->interface_name($interface);
    return if $interface eq 'any';
    my $dumpcap = $self->command()->require_executable('dumpcap');
    my ($status, $output) = $self->command()->capture(argv => [$dumpcap, '-D']);
    $status == 0
        or die "capture interface is unavailable to dumpcap: $interface\n";
    for my $line (split /\n/, $output) {
        return if $line =~ /\A[0-9]+[.] ([^\s]+)/ && $1 eq $interface;
    }
    die "capture interface is unavailable to dumpcap: $interface\n";
}

sub _run_dumpcap_capture {
    my ($self, $action, $interface) = @_;

    my $dumpcap = $self->command()->require_executable('dumpcap');
    my $timeout = $self->command()->require_executable('timeout');
    $self->_require_capture_group();
    $self->_validate_capture_interface_available($interface);
    my $kind = $action;
    $kind =~ s/\Adumpcap-capture-//;
    my $output = $self->validator()->new_capture_path($self->_home(), 'dumpcap', $kind, 'pcapng');
    my %filters = (
        'dumpcap-capture-dns'       => 'port 53',
        'dumpcap-capture-dhcp'      => 'port 67 or port 68 or port 546 or port 547',
        'dumpcap-capture-tls'       => 'tcp port 443 or tcp port 465 or tcp port 636 or tcp port 853 or tcp port 993 or tcp port 995',
        'dumpcap-capture-discovery' => 'arp or icmp or icmp6 or udp port 5353 or udp port 1900',
    );
    exists($filters{$action}) || $action eq 'dumpcap-capture-general'
        or die "unsupported dumpcap capture action: $action\n";

    print "Writing bounded capture to $output\n";
    my @argv = (
        $timeout, '--preserve-status', '--signal=INT', '--kill-after=5s', '70s',
        $dumpcap, '-q', '-i', $interface, '-s', '256',
        '-a', 'duration:60', '-a', 'filesize:10240',
    );
    push @argv, ('-f', $filters{$action}) if exists $filters{$action};
    push @argv, ('-w', $output);
    $self->command()->run_or_die('writing bounded dumpcap capture', @argv);
    chmod 0600, $output
        or die "cannot set capture permissions: $output: $!\n";
    print "Capture completed: $output\n";
    return 0;
}

sub _run_tcpdump_capture {
    my ($self, $action, $interface) = @_;

    my $pkexec = $self->command()->require_executable('pkexec');
    -x $self->root_helper()
        or die "privileged network helper is unavailable: " . $self->root_helper() . "\n";
    $interface = $self->validator()->interface_name($interface);
    my $kind = $action;
    $kind =~ s/\Atcpdump-capture-//;
    my $output = $self->validator()->new_capture_path($self->_home(), 'tcpdump', $kind, 'pcap');
    print "Writing bounded capture to $output\n";
    my $status = eval {
        $self->command()->run_to_new_file($output, $pkexec, $self->root_helper(), $action, $interface);
    };
    if ($@) {
        unlink $output;
        die $@;
    }
    if ($status != 0) {
        unlink $output;
        return $status;
    }
    chmod 0600, $output
        or die "cannot set capture permissions: $output: $!\n";
    print "Capture completed: $output\n";
    return 0;
}

sub _run_tshark_action {
    my ($self, $action, $argument) = @_;

    my $tshark = $self->command()->require_executable('tshark');
    if ($action =~ /\Atshark-live-/) {
        $self->_require_capture_group();
        $self->_validate_capture_interface_available($argument);
    }
    if ($action eq 'tshark-live-endpoints') {
        return $self->command()->run($tshark, '-q', '-i', $argument, '-a', 'duration:30', '-c', '5000', '-z', 'endpoints,ip');
    }
    if ($action eq 'tshark-live-dns') {
        return $self->command()->run($tshark, '-i', $argument, '-a', 'duration:30', '-c', '5000', '-Y', 'dns.flags.response == 0', '-T', 'fields', '-e', 'frame.time', '-e', 'ip.src', '-e', 'ipv6.src', '-e', 'dns.qry.name');
    }
    if ($action eq 'tshark-live-tls') {
        return $self->command()->run($tshark, '-i', $argument, '-a', 'duration:30', '-c', '5000', '-Y', 'tls.handshake.extensions_server_name', '-T', 'fields', '-e', 'frame.time', '-e', 'ip.src', '-e', 'ip.dst', '-e', 'tls.handshake.extensions_server_name');
    }
    if ($action eq 'tshark-live-retransmissions') {
        return $self->command()->run($tshark, '-i', $argument, '-a', 'duration:30', '-c', '5000', '-Y', 'tcp.analysis.retransmission or tcp.analysis.fast_retransmission', '-T', 'fields', '-e', 'frame.time', '-e', 'ip.src', '-e', 'tcp.srcport', '-e', 'ip.dst', '-e', 'tcp.dstport');
    }

    my $capture_file = $self->validator()->capture_file($self->_home(), $argument);
    if ($action eq 'tshark-file-protocols') {
        return $self->command()->run($tshark, '-r', $capture_file, '-q', '-z', 'io,phs');
    }
    if ($action eq 'tshark-file-conversations') {
        return $self->command()->run($tshark, '-r', $capture_file, '-q', '-z', 'conv,ip');
    }
    if ($action eq 'tshark-file-dns') {
        return $self->command()->run($tshark, '-r', $capture_file, '-Y', 'dns.flags.response == 0', '-T', 'fields', '-e', 'frame.time', '-e', 'ip.src', '-e', 'ipv6.src', '-e', 'dns.qry.name');
    }
    if ($action eq 'tshark-file-tls') {
        return $self->command()->run($tshark, '-r', $capture_file, '-Y', 'tls.handshake.extensions_server_name', '-T', 'fields', '-e', 'frame.time', '-e', 'ip.src', '-e', 'ip.dst', '-e', 'tls.handshake.extensions_server_name');
    }
    if ($action eq 'tshark-file-http-errors') {
        return $self->command()->run($tshark, '-r', $capture_file, '-Y', 'http.response.code >= 400', '-T', 'fields', '-e', 'frame.time', '-e', 'ip.src', '-e', 'ip.dst', '-e', 'http.host', '-e', 'http.request.uri', '-e', 'http.response.code');
    }
    die "unsupported TShark action: $action\n";
}

sub _run_wireshark_action {
    my ($self, $action, @args) = @_;

    my $setsid = $self->command()->require_executable('setsid');
    my $wireshark = $self->command()->require_executable('wireshark');
    $self->_require_capture_group();
    if ($action eq 'wireshark-launch') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->command()->run($setsid, '-f', $wireshark);
    }
    if ($action eq 'wireshark-open-capture') {
        @args == 1 or die "$action requires one capture file\n";
        my $capture_file = $self->validator()->capture_file($self->_home(), $args[0]);
        return $self->command()->run($setsid, '-f', $wireshark, '-r', $capture_file);
    }
    die "unsupported Wireshark action: $action\n";
}

sub _run_privileged_action {
    my ($self, $action, @args) = @_;

    my $pkexec = $self->command()->require_executable('pkexec');
    -x $self->root_helper()
        or die "privileged network helper is unavailable: " . $self->root_helper() . "\n";
    return $self->command()->run($pkexec, $self->root_helper(), $action, @args);
}

sub _run_action {
    my ($self, $action, @args) = @_;

    if ($action eq 'dumpcap-list-interfaces') {
        my $dumpcap = $self->command()->require_executable('dumpcap');
        $self->_require_capture_group();
        return $self->command()->run($dumpcap, '-D');
    }
    return $self->_run_dumpcap_capture($action, $args[0])
        if $action =~ /\Adumpcap-capture-/;
    return $self->_run_tcpdump_capture($action, $args[0])
        if $action =~ /\Atcpdump-capture-/;
    return $self->_run_privileged_action($action, @args)
        if $action eq 'tcpdump-list-interfaces' || $action eq 'tcpdump-print-summary' || $action =~ /\Anmap-/ || $action eq 'show-listening-ports';
    return $self->_run_tshark_action($action, $args[0])
        if $action =~ /\Atshark-/;
    die "unsupported network scanning action: $action\n";
}

sub _run_in_terminal {
    my ($self, $action, @args) = @_;

    print "\n=== Network Scanning: $action ===\n\n";
    my $status = eval { $self->_run_action($action, @args) };
    if ($@) {
        my $message = $@;
        $message =~ s/[\r\n]+\z//;
        print STDERR "fatal: $message\n";
        $status = 1;
    }
    $status = 1 if !defined $status;
    print "\n=== Action finished with status $status ===\n";
    $self->_notify($status, $action);
    if (-t STDIN) {
        print 'Press Enter to close this terminal...';
        scalar <STDIN>;
    }
    return $status;
}

sub _run {
    my ($self, @argv) = @_;

    $> != 0
        or die "labwc-network-scan-action must run as the logged-in desktop user\n";
    @argv or die "usage: labwc-network-scan-action <action> [argument]\n";

    if ($argv[0] eq '--run') {
        shift @argv;
        @argv or die "missing network scanning action after --run\n";
        my $action = shift @argv;
        $self->_validate_request_shape($action, @argv);
        $action !~ /\Awireshark-/
            or die "Wireshark GUI actions must be launched directly from the desktop session\n";
        return $self->_run_in_terminal($action, @argv);
    }

    my $action = shift @argv;
    $self->_validate_request_shape($action, @argv);
    if ($action =~ /\Awireshark-/) {
        return $self->_run_wireshark_action($action, @argv);
    }
    my $terminal = $self->command()->require_executable('labwc-terminal');
    $self->command()->exec($terminal, '-e', $self->self_path(), '--run', $action, @argv);
}

sub run {
    my ($self, @argv) = @_;

    my $status = eval {
        local $ENV{PATH}   = '/usr/local/bin:/usr/bin:/bin';
        local $ENV{LC_ALL} = 'C.UTF-8';
        $self->_run(@argv);
    };
    return $status if defined($status) && !$@;
    return $self->_fatal($@ || 'network scanning action failed');
}

1;
