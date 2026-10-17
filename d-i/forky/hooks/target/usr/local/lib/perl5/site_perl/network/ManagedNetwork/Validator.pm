package ManagedNetwork::Validator;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Fcntl qw(S_ISREG);
use Socket qw(AF_INET6 inet_pton);
use Types::Standard qw(Bool Int Str);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC sleep);

use ManagedNetwork::Config;
use ManagedNetwork::Logger;

my @CONFIG_KEYS = qw(
  MANAGED_NETWORK_MODE
  MANAGED_NETWORK_DNS_MODE
  MANAGED_NETWORK_LINK_TYPES
  MANAGED_NETWORK_HOSTNAME
  MANAGED_NETWORK_DOMAIN
  MANAGED_NETWORK_CLASSES_RAW
  MANAGED_NETWORK_SELECTED_CLASS_REFS
  MANAGED_NETWORK_HOST_VARIANT
  MANAGED_NETWORK_ETHERNET_IFACE
  MANAGED_NETWORK_WIFI_IFACE
  MANAGED_NETWORK_IPV6_ENABLED
  MANAGED_NETWORK_IPV4_GATEWAY
  MANAGED_NETWORK_IPV4_DNS
  MANAGED_NETWORK_IPV6_GATEWAY
  MANAGED_NETWORK_IPV6_DNS
  MANAGED_NETWORK_WIFI_PSK_SECURITY
  MANAGED_NETWORK_WIFI_CIDR
  MANAGED_NETWORK_WIFI_ESSID
  MANAGED_NETWORK_ETHERNET_MAC
  MANAGED_NETWORK_ETHERNET_IPV4_CIDR
  MANAGED_NETWORK_ETHERNET_IPV6_CIDR
  MANAGED_NETWORK_WIFI_MAC
  MANAGED_NETWORK_WIFI_IPV4_CIDR
  MANAGED_NETWORK_WIFI_IPV6_CIDR
  MANAGED_NETWORK_IPV4_HOST_CIDRS
  MANAGED_NETWORK_IPV4_NETWORK_CIDRS
  MANAGED_NETWORK_IPV6_HOST_CIDRS
  MANAGED_NETWORK_IPV6_NETWORK_CIDRS
);

has wait_seconds => (
    is      => 'ro',
    isa     => Int,
    default => sub { 0 },
);

has allow_absent => (
    is      => 'ro',
    isa     => Bool,
    default => sub { 0 },
);

has staged_only => (
    is      => 'ro',
    isa     => Bool,
    default => sub { 0 },
);

has config_path => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has logger => (
    is       => 'ro',
    required => 1,
);

has sys_class_net => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has target_root => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

sub from_environment {
    my ($class, %args) = @_;

    my $target_root = $ENV{MANAGED_TARGET_ROOT} // '/';
    $target_root =~ m{\A/}
        or die "MANAGED_TARGET_ROOT must be absolute: $target_root\n";
    my $config_path = $ENV{MANAGED_NETWORK_CONFIG} // q{};
    if ($config_path eq q{}) {
        my $prefix = $target_root eq '/' ? q{} : $target_root;
        $prefix =~ s{/+\z}{};
        $config_path = "$prefix/etc/network/host.conf";
    }
    return $class->new(
        wait_seconds  => $args{wait_seconds} // 0,
        allow_absent  => $args{allow_absent} // 0,
        staged_only   => $args{staged_only} // 0,
        config_path   => $config_path,
        logger        => $args{logger},
        sys_class_net => $ENV{MANAGED_SYS_CLASS_NET} // '/sys/class/net',
        target_root   => $target_root,
    );
}

sub _target_prefix {
    my ($self) = @_;

    return q{} if $self->target_root() eq '/';
    my $prefix = $self->target_root();
    $prefix =~ s{/+\z}{};
    return $prefix;
}

sub _target_path {
    my ($self, $path) = @_;
    return $self->_target_prefix() . $path;
}

sub _validate_paths {
    my ($self) = @_;

    $self->target_root() =~ m{\A/}
        or die "MANAGED_TARGET_ROOT must be absolute: " . $self->target_root() . "\n";
    -d $self->target_root()
        or die "target root is missing: " . $self->target_root() . "\n";
    $self->sys_class_net() =~ m{\A/}
        or die "MANAGED_SYS_CLASS_NET must be absolute: " . $self->sys_class_net() . "\n";
    ($self->staged_only() || -d $self->sys_class_net())
        or die "sysfs net directory is missing: " . $self->sys_class_net() . "\n";
    $self->config_path() =~ m{\A/}
        or die "MANAGED_NETWORK_CONFIG must be absolute: " . $self->config_path() . "\n";
    -r $self->config_path()
        or die "network defaults are missing: " . $self->config_path() . "\n";
    return;
}

sub _valid_iface_name {
    my ($self, $name) = @_;

    return 0 if !defined($name) || $name eq q{} || $name eq '.' || $name eq '..' || $name eq 'lo';
    return 0 if length($name) > 15;
    return $name =~ /\A[A-Za-z0-9_.-]+\z/ ? 1 : 0;
}

sub _normalize_mac {
    my ($self, $mac) = @_;

    $mac = lc($mac // q{});
    $mac =~ s/\A\s+|\s+\z//g;
    return $mac;
}

sub _valid_mac {
    my ($self, $mac) = @_;

    $mac = $self->_normalize_mac($mac);
    return 0 if $mac eq '00:00:00:00:00:00';
    return $mac =~ /\A[0-9a-f]{2}(?::[0-9a-f]{2}){5}\z/ ? 1 : 0;
}

sub _valid_ipv4 {
    my ($self, $value) = @_;

    return 0 if !defined($value) || $value !~ /\A[0-9]{1,3}(?:\.[0-9]{1,3}){3}\z/;
    return 0 if grep { $_ > 255 } split /\./, $value;
    return 1;
}

sub _valid_ipv4_cidr {
    my ($self, $value) = @_;

    my ($address, $prefix) = ($value // q{}) =~ /\A([^\/]+)\/([0-9]{1,2})\z/;
    return 0 if !defined($address) || !$self->_valid_ipv4($address);
    return $prefix >= 1 && $prefix <= 32 ? 1 : 0;
}

sub _valid_ipv6 {
    my ($self, $value) = @_;

    return defined($value) && $value ne q{} && $value !~ m{/} && defined inet_pton(AF_INET6, $value);
}

sub _valid_ipv6_cidr {
    my ($self, $value) = @_;

    my ($address, $prefix) = ($value // q{}) =~ /\A([^\/]+)\/([0-9]{1,3})\z/;
    return 0 if !defined($address) || !$self->_valid_ipv6($address);
    return $prefix >= 1 && $prefix <= 128 ? 1 : 0;
}

sub _ipv6_is_next_host {
    my ($self, $ethernet, $wifi) = @_;

    my ($ea, $ep) = split m{/}, $ethernet;
    my ($wa, $wp) = split m{/}, $wifi;
    return 0 if $ep != $wp;
    my @ethernet = unpack 'C16', inet_pton(AF_INET6, $ea);
    my @wifi = unpack 'C16', inet_pton(AF_INET6, $wa);
    my @next = @ethernet;
    my $carry = 1;
    for my $i (reverse 0 .. 15) {
        my $sum = $next[$i] + $carry;
        $next[$i] = $sum & 0xff;
        $carry = $sum >> 8;
        last if !$carry;
    }
    return 0 if $carry || pack('C16', @next) ne pack('C16', @wifi);
    for my $i (0 .. 15) {
        my $bits = $ep - ($i * 8);
        last if $bits <= 0;
        my $shift = $bits < 8 ? 8 - $bits : 0;
        return 0 if ($ethernet[$i] >> $shift) != ($wifi[$i] >> $shift);
    }
    return 1;
}

sub _valid_domain {
    my ($self, $value) = @_;

    return 1 if !defined($value) || $value eq q{};
    return 0 if length($value) > 253 || $value =~ /\A[.]|[.]\z|[.]{2}/;
    for my $part (split /\./, $value) {
        return 0 if $part eq q{} || length($part) > 63;
        return 0 if $part !~ /\A[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\z/;
    }
    return 1;
}

sub _words {
    my ($self, $value) = @_;
    return grep { $_ ne q{} } split /\s+/, $value // q{};
}

sub _link_types {
    my ($self, $config) = @_;

    my @types;
    my %seen;
    for my $item ($self->_words(lc($config->{MANAGED_NETWORK_LINK_TYPES}))) {
        ($item eq 'ethernet' || $item eq 'wifi')
            or die "unsupported link type in defaults: $item\n";
        next if $seen{$item}++;
        push @types, $item;
    }
    @types or die "MANAGED_NETWORK_LINK_TYPES must include at least one link type\n";
    return @types;
}

sub _file_mode {
    my ($self, $path) = @_;

    my @stat = stat $path;
    return q{} if !@stat;
    return sprintf '%04o', $stat[2] & 07777;
}

sub _slurp_limited {
    my ($self, $path) = @_;
    return ManagedNetwork::Config->read_file_limited($path, 131_072);
}

sub _iface_is_wifi {
    my ($self, $sys_iface) = @_;
    return -d "$sys_iface/wireless" || -d "$sys_iface/phy80211";
}

sub _read_sys_value {
    my ($self, $path) = @_;

    my $value = eval { ManagedNetwork::Config->read_file_limited($path, 8192) };
    return undef if !defined $value;
    chomp $value;
    return $value;
}

sub _validate_config_values {
    my ($self, $config) = @_;

    my @types = $self->_link_types($config);
    my %managed_type = map { $_ => 1 } @types;
    $config->{MANAGED_NETWORK_MODE} eq 'static'
        or die "MANAGED_NETWORK_MODE must be static\n";
    $config->{MANAGED_NETWORK_DNS_MODE} =~ /\A(?:link|global)\z/
        or die "MANAGED_NETWORK_DNS_MODE must be link or global\n";
    $self->_valid_domain($config->{MANAGED_NETWORK_DOMAIN})
        or die "MANAGED_NETWORK_DOMAIN is invalid\n";
    $self->_valid_ipv4($config->{MANAGED_NETWORK_IPV4_GATEWAY})
        or die "MANAGED_NETWORK_IPV4_GATEWAY is invalid\n";
    lc($config->{MANAGED_NETWORK_IPV6_ENABLED}) =~ /\A(?:true|false)\z/
        or die "MANAGED_NETWORK_IPV6_ENABLED must be true or false\n";
    for my $type (qw(ETHERNET WIFI)) {
        my $iface = $config->{"MANAGED_NETWORK_${type}_IFACE"};
        next if $iface eq q{};
        $self->_valid_iface_name($iface)
            or die "MANAGED_NETWORK_${type}_IFACE is not a valid interface name\n";
    }
    $config->{MANAGED_NETWORK_ETHERNET_IFACE} ne $config->{MANAGED_NETWORK_WIFI_IFACE}
        or $config->{MANAGED_NETWORK_ETHERNET_IFACE} eq q{}
        or die "MANAGED_NETWORK_ETHERNET_IFACE and MANAGED_NETWORK_WIFI_IFACE must differ\n";
    for my $dns ($self->_words($config->{MANAGED_NETWORK_IPV4_DNS})) {
        $self->_valid_ipv4($dns)
            or die "MANAGED_NETWORK_IPV4_DNS contains an invalid IPv4 address\n";
    }
    if (lc($config->{MANAGED_NETWORK_IPV6_ENABLED}) eq 'true') {
        $self->_valid_ipv6($config->{MANAGED_NETWORK_IPV6_GATEWAY})
            or die "MANAGED_NETWORK_IPV6_GATEWAY is invalid\n";
        for my $dns ($self->_words($config->{MANAGED_NETWORK_IPV6_DNS})) {
            $self->_valid_ipv6($dns)
                or die "MANAGED_NETWORK_IPV6_DNS contains an invalid IPv6 address\n";
        }
    }
    else {
        $config->{MANAGED_NETWORK_IPV6_GATEWAY} eq q{}
            or die "MANAGED_NETWORK_IPV6_GATEWAY requires MANAGED_NETWORK_IPV6_ENABLED=true\n";
        $config->{MANAGED_NETWORK_IPV6_DNS} eq q{}
            or die "MANAGED_NETWORK_IPV6_DNS requires MANAGED_NETWORK_IPV6_ENABLED=true\n";
    }
    if ($managed_type{wifi} && $config->{MANAGED_NETWORK_WIFI_ESSID} ne q{}) {
        lc($config->{MANAGED_NETWORK_WIFI_PSK_SECURITY}) =~ /\A(?:open|wep|legacy-wep|open\/wep|wpa|sae)\z/
            or die "MANAGED_NETWORK_WIFI_PSK_SECURITY is invalid\n";
    }
    for my $link_type (@types) {
        my $upper = uc($link_type);
        $self->_valid_ipv4_cidr($config->{"MANAGED_NETWORK_${upper}_IPV4_CIDR"})
            or die "invalid IPv4 CIDR for $link_type\n";
        if (lc($config->{MANAGED_NETWORK_IPV6_ENABLED}) eq 'true') {
            $self->_valid_ipv6_cidr($config->{"MANAGED_NETWORK_${upper}_IPV6_CIDR"})
                or die "invalid IPv6 CIDR for $link_type\n";
        }
    }
    if ($managed_type{wifi} && $config->{MANAGED_NETWORK_WIFI_CIDR} ne q{}) {
        $self->_valid_ipv4_cidr($config->{MANAGED_NETWORK_WIFI_CIDR})
            or die "invalid PRESEED_WIFI_CIDR constraint\n";
        my ($range, $prefix) = split m{/}, $config->{MANAGED_NETWORK_WIFI_CIDR};
        my ($wifi) = split m{/}, $config->{MANAGED_NETWORK_WIFI_IPV4_CIDR};
        my ($ri, $wi) = (0, 0);
        $ri = ($ri << 8) + $_ for split /\./, $range;
        $wi = ($wi << 8) + $_ for split /\./, $wifi;
        my $mask = (0xffffffff << (32 - $prefix)) & 0xffffffff;
        ($ri & $mask) == ($wi & $mask)
            or die "Ethernet IPv4 +1 is outside PRESEED_WIFI_CIDR\n";
    }
    if ($managed_type{ethernet} && $managed_type{wifi}) {
        my ($ethernet, $ep) = split m{/}, $config->{MANAGED_NETWORK_ETHERNET_IPV4_CIDR};
        my ($wifi, $wp) = split m{/}, $config->{MANAGED_NETWORK_WIFI_IPV4_CIDR};
        $self->_valid_ipv4_cidr($config->{MANAGED_NETWORK_ETHERNET_IPV4_CIDR})
            && $self->_valid_ipv4_cidr($config->{MANAGED_NETWORK_WIFI_IPV4_CIDR})
            or die "invalid Ethernet/Wi-Fi IPv4 address policy\n";
        my ($ei, $wi) = (0, 0);
        $ei = ($ei << 8) + $_ for split /\./, $ethernet;
        $wi = ($wi << 8) + $_ for split /\./, $wifi;
        my $mask = (0xffffffff << (32 - $ep)) & 0xffffffff;
        $ep == $wp && $wi == $ei + 1 && ($ei & $mask) == ($wi & $mask)
            or die "Wi-Fi must use Ethernet IPv4 +1 within the same subnet\n";
        if (lc($config->{MANAGED_NETWORK_IPV6_ENABLED}) eq 'true') {
            $self->_ipv6_is_next_host($config->{MANAGED_NETWORK_ETHERNET_IPV6_CIDR},
                                     $config->{MANAGED_NETWORK_WIFI_IPV6_CIDR})
                or die "Wi-Fi must use Ethernet IPv6 +1 within the same subnet\n";
        }
    }
    return @types;
}

sub _wait_for_expected_interfaces {
    my ($self, $config, @types) = @_;
    my $timeout = $self->wait_seconds();
    $timeout >= 0 && $timeout <= 15 or die "interface wait must be between 0 and 15 seconds\n";
    return if !$timeout;
    my @ifaces = map { $config->{"MANAGED_NETWORK_" . uc($_) . "_IFACE"} } @types;
    for my $iface (@ifaces) {
        $self->_valid_iface_name($iface) or die "invalid expected interface name\n";
    }
    # One monotonic deadline shared by all configured adapters. Do not wait for
    # carrier, DHCP, addresses, or any unrelated device or udev event.
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + $timeout;
    my $announced = 0;
    while (1) {
        my @missing = grep {
            my $path = $self->sys_class_net() . "/$_";
            !-d $path || !-r "$path/address" || !-r "$path/type"
        } @ifaces;
        return if !@missing;
        # Boot checks validate installed policy, not connectivity. A USB dock
        # may be unplugged while Wi-Fi is used. Still wait for any partially
        # registered adapter's attributes, and validate every present adapter.
        my @pending = grep { -d $self->sys_class_net() . "/$_" } @missing;
        return if $self->allow_absent() && !@pending && @missing < @ifaces;
        my $remaining = $deadline - clock_gettime(CLOCK_MONOTONIC);
        return if $remaining <= 0 && $self->allow_absent() && !@pending;
        $remaining > 0 or die "timed out after ${timeout}s waiting for managed interface(s): " . join(',', @missing) . "\n";
        if (!$announced++) {
            $self->logger()->info('waiting for managed interface(s): ' . join(',', @missing));
        }
        sleep($remaining < 0.1 ? $remaining : 0.1);
    }
}

sub _validate_expected_interface {
    my ($self, $config, $link_type) = @_;

    my $upper = uc($link_type);
    my $iface = $config->{"MANAGED_NETWORK_${upper}_IFACE"};
    my $mac = $self->_normalize_mac($config->{"MANAGED_NETWORK_${upper}_MAC"});
    my $ipv4 = $config->{"MANAGED_NETWORK_${upper}_IPV4_CIDR"};
    my $ipv6 = $config->{"MANAGED_NETWORK_${upper}_IPV6_CIDR"};
    my $ipv6_enabled = lc($config->{MANAGED_NETWORK_IPV6_ENABLED}) eq 'true' ? 1 : 0;

    $self->_valid_iface_name($iface)
        or die "missing interface name for $link_type\n";
    $self->_valid_mac($mac)
        or die "invalid MAC for $link_type\n";
    $self->_valid_ipv4_cidr($ipv4)
        or die "invalid IPv4 CIDR for $link_type\n";
    (!$ipv6_enabled || $self->_valid_ipv6_cidr($ipv6))
        or die "invalid IPv6 CIDR for $link_type\n";
    ($ipv6_enabled || $ipv6 eq q{})
        or die "unexpected IPv6 CIDR for $link_type when IPv6 is disabled\n";

    # Installation validates policy before the target's udev renames apply.
    return if $self->staged_only();

    my $sys_iface = $self->sys_class_net() . "/$iface";
    if (!-d $sys_iface && $self->allow_absent()) {
        $self->logger()->info("configured $link_type adapter is not attached: $iface");
        return;
    }
    -d $sys_iface
        or die "expected $link_type interface is absent: $iface\n";
    my $actual_mac = $self->_normalize_mac($self->_read_sys_value("$sys_iface/address") // q{});
    # NM's profile matches the permanent MAC, then assigns a random association
    # MAC under the existing privacy policy. Preserve strict checks otherwise.
    ($actual_mac eq $mac || ($link_type eq 'wifi'
        && ($self->_read_sys_value("$sys_iface/addr_assign_type") // q{}) eq '3'))
        or die "expected $link_type interface $iface has MAC $actual_mac, expected $mac\n";
    my $type = $self->_read_sys_value("$sys_iface/type") // q{};
    $type eq '1'
        or die "expected $link_type interface $iface is not an ARPHRD_ETHER adapter\n";
    if ($link_type eq 'wifi') {
        $self->_iface_is_wifi($sys_iface)
            or die "expected Wi-Fi interface $iface is not marked wireless\n";
    }
    else {
        !$self->_iface_is_wifi($sys_iface)
            or die "expected Ethernet interface $iface is marked wireless\n";
    }
    return;
}

sub _validate_wifi_profile {
    my ($self, $config, $selection) = @_;
    my $iface = $config->{MANAGED_NETWORK_WIFI_IFACE};
    $selection !~ /^iface[ \t]+\Q$iface\E[ \t]/m
        or die "Wi-Fi must be owned only by NetworkManager, not ifupdown\n";
    $selection =~ s/\\\n[ \t]*/ /g;
    for my $list ($selection =~ /^[ \t]*(?:auto|allow-\S+)[ \t]+([^\n]+)$/mg) {
        for my $name (split /[ \t]+/, $list) {
            ($name eq 'lo' || $self->_valid_iface_name($name))
                or die "automatic activation lists must use literal interface names\n";
            $name ne $iface or die "ifupdown must not automatically activate Wi-Fi\n";
        }
    }
    my $path = $self->_target_path('/etc/NetworkManager/system-connections/wifi.nmconnection');
    $path = $self->_target_path('/etc/network/wifi.nmconnection') if !-e $path;
    $self->_file_mode($path) eq '0600' or die "$path must be mode 0600\n";
    my %values;
    my $group = q{};
    for my $line (split /\n/, $self->_slurp_limited($path)) {
        next if $line =~ /\A\s*(?:#|\z)/;
        if ($line =~ /\A\[([a-z0-9-]+)\]\z/) { $group = $1; next; }
        my ($key, $value) = $line =~ /\A([a-z0-9-]+)=(.*)\z/;
        defined($key) && $group ne q{} or die "invalid managed Wi-Fi keyfile\n";
        !exists($values{"$group.$key"}) or die "duplicate managed Wi-Fi keyfile property\n";
        $values{"$group.$key"} = $value;
    }
    my @expected = (
        ['connection.type', 'wifi'], ['connection.interface-name', $iface],
        ['connection.autoconnect', 'false'], ['wifi.mode', 'infrastructure'],
        ['wifi.mac-address', $config->{MANAGED_NETWORK_WIFI_MAC}],
        ['ipv4.method', 'manual'],
        ['ipv4.forwarding', '1'],
        ['ipv4.address1', $config->{MANAGED_NETWORK_WIFI_IPV4_CIDR}],
        ['ipv4.gateway', $config->{MANAGED_NETWORK_IPV4_GATEWAY}],
    );
    my $ipv6_enabled = lc($config->{MANAGED_NETWORK_IPV6_ENABLED}) eq 'true';
    push @expected, ['ipv6.method', $ipv6_enabled ? 'manual' : 'disabled'];
    push @expected, ['ipv6.address1', $config->{MANAGED_NETWORK_WIFI_IPV6_CIDR}],
        ['ipv6.gateway', $config->{MANAGED_NETWORK_IPV6_GATEWAY}]
        if $ipv6_enabled;
    for my $family (4, 6) {
        push @expected, ["ipv$family.route-metric", '200'],
            ["ipv$family.ignore-auto-dns", 'true'], ["ipv$family.ignore-auto-routes", 'true'];
        next if $family == 6 && !$ipv6_enabled;
        my $dns = $config->{MANAGED_NETWORK_DNS_MODE} eq 'link'
            ? join(';', $self->_words($config->{"MANAGED_NETWORK_IPV${family}_DNS"})) . ';' : q{};
        push @expected, ["ipv$family.dns", $dns], ["ipv$family.may-fail", 'false'];
    }
    for my $field (@expected) {
        my ($key, $expected) = @{$field};
        ($values{$key} // q{}) eq $expected
            or die "$path has incorrect $key\n";
    }
    # SSID and secrets belong to NM/nmtui. They may be edited independently of
    # the installer address policy; never print them in validation diagnostics.
    my $nm_path = $self->_target_path('/etc/NetworkManager/conf.d/90-network-external.conf');
    my $nm = $self->_slurp_limited($nm_path);
    $nm !~ /^unmanaged-devices=[^\n]*interface-name:\Q$iface\E(?:[;\n]|\z)/m
        && $nm !~ /^unmanaged-devices=[^\n]*mac:\Q$config->{MANAGED_NETWORK_WIFI_MAC}\E(?:[;\n]|\z)/m
        or die "$nm_path must not exclude Wi-Fi\n";
    $nm =~ /\[device-wifi\]\nmatch-device=interface-name:\Q$iface\E\nmanaged=1\n/
        or die "$nm_path must make Wi-Fi managed\n";
    return;
}

sub _validate_staged_files {
    my ($self, $config, @types) = @_;

    my $interfaces = $self->_target_path('/etc/network/interfaces');
    my $managed = $self->_target_path('/etc/network/interfaces.d/50-network');
    -r $interfaces or die "missing $interfaces\n";
    -r $managed or die "missing $managed\n";
    for my $entry (
        ['/usr/local/libexec/network-ifup-hotplug', '0755'],
        ['/etc/systemd/system/ifup@.service.d/40-device-lifecycle.conf', '0644'],
    ) {
        my ($relative, $mode) = @{$entry};
        my $path = $self->_target_path($relative);
        my @metadata = lstat $path;
        @metadata && S_ISREG($metadata[2]) && $metadata[3] == 1
            && $metadata[4] == 0 && $metadata[5] == 0 && $self->_file_mode($path) eq $mode
            or die "untrusted managed hotplug asset: $path\n";
        my $source = $self->_slurp_limited($path);
        $source !~ /__[A-Z][A-Z0-9_]{2,}__/
            or die "unresolved token in managed hotplug asset: $path\n";
        if ($relative =~ /[.]conf\z/) {
            my @directives = grep { /\S/ && !/\A\s*#/ } split /\n/, $source;
            join("\n", @directives) eq join("\n",
                '[Service]', 'ExecStart=',
                'ExecStart=/usr/local/libexec/network-ifup-hotplug %I')
                or die "invalid managed hotplug service contract: $path\n";
        }
    }
    $self->_file_mode($self->config_path()) eq '0600'
        or die $self->config_path() . " must be mode 0600\n";
    if (grep { $_ eq 'wifi' } @types) {
        $self->_file_mode($managed) eq '0600'
            or die "$managed must be mode 0600 for Wi-Fi static configuration\n";
    }

    my $base = $self->_slurp_limited($interfaces);
    $base =~ /^source[ \t]+\/etc\/network\/interfaces\.d\/\*/m
        or die "$interfaces does not source interfaces.d\n";
    my $content = $self->_slurp_limited($managed);
    if ($config->{MANAGED_NETWORK_DNS_MODE} eq 'global') {
        $content !~ /^[ \t]*dns-nameservers[ \t]+\S/m
            or die "$managed must not configure per-link DNS in global mode\n";
    }
    my $ipv6_enabled = lc($config->{MANAGED_NETWORK_IPV6_ENABLED}) eq 'true' ? 1 : 0;
    for my $link_type (@types) {
        if ($link_type eq 'wifi') {
            $self->_validate_wifi_profile($config, $base . "\n" . $content);
            next;
        }
        my $upper = uc($link_type);
        my $iface = $config->{"MANAGED_NETWORK_${upper}_IFACE"};
        $content =~ /^iface[ \t]+\Q$iface\E[ \t]+inet[ \t]+static\b/m
            or die "$managed lacks static IPv4 stanza for $iface\n";
        if ($ipv6_enabled) {
            $content =~ /^iface[ \t]+\Q$iface\E[ \t]+inet6[ \t]+static\b/m
                or die "$managed lacks static IPv6 stanza for $iface\n";
        }
        else {
            $content !~ /^iface[ \t]+\Q$iface\E[ \t]+inet6[ \t]+static\b/m
                or die "$managed must not contain static IPv6 stanzas when IPv6 is disabled\n";
        }
        my @stanzas = $content =~ /^iface[ \t]+\Q$iface\E[ \t]+inet[ \t]+static[ \t]*\n((?:(?!^(?:iface|auto|allow-\S+|mapping|source)\b).*\n)*)/mg;
        @stanzas == 1 or die "$managed must contain exactly one IPv4 stanza for $iface\n";
        my ($address, $prefix) = split m{/}, $config->{"MANAGED_NETWORK_${upper}_IPV4_CIDR"};
        my $mask = (0xffffffff << (32 - $prefix)) & 0xffffffff;
        my $netmask = join '.', map { ($mask >> (8 * $_)) & 255 } reverse 0 .. 3;
        for my $field ([address => $address], [netmask => $netmask],
                       [gateway => $config->{MANAGED_NETWORK_IPV4_GATEWAY}],
                       [metric => $link_type eq 'wifi' ? 200 : 100]) {
            my ($key, $expected) = @{$field};
            my @values = $stanzas[0] =~ /^[ \t]+\Q$key\E[ \t]+([^\n]+)$/mg;
            @values == 1 && $values[0] eq $expected
                or die "$managed has incorrect $key for $iface\n";
        }
        if ($config->{MANAGED_NETWORK_DNS_MODE} eq 'link') {
            my @dns = $stanzas[0] =~ /^[ \t]+dns-nameservers[ \t]+([^\n]+)$/mg;
            @dns == 1 && $dns[0] eq $config->{MANAGED_NETWORK_IPV4_DNS}
                or die "$managed has incorrect IPv4 DNS for $iface\n";
        }
        if ($ipv6_enabled) {
            my @ipv6_stanzas = $content =~ /^iface[ \t]+\Q$iface\E[ \t]+inet6[ \t]+static[ \t]*\n((?:(?!^(?:iface|auto|allow-\S+|mapping|source)\b).*\n)*)/mg;
            @ipv6_stanzas == 1 or die "$managed must contain exactly one IPv6 stanza for $iface\n";
            my ($ipv6_address, $ipv6_prefix) = split m{/}, $config->{"MANAGED_NETWORK_${upper}_IPV6_CIDR"};
            for my $field ([address => $ipv6_address], [netmask => $ipv6_prefix],
                           [gateway => $config->{MANAGED_NETWORK_IPV6_GATEWAY}],
                           [metric => $link_type eq 'wifi' ? 200 : 100]) {
                my ($key, $expected) = @{$field};
                my @values = $ipv6_stanzas[0] =~ /^[ \t]+\Q$key\E[ \t]+([^\n]+)$/mg;
                @values == 1 && $values[0] eq $expected
                    or die "$managed has incorrect IPv6 $key for $iface\n";
            }
            if ($config->{MANAGED_NETWORK_DNS_MODE} eq 'link') {
                my @dns = $ipv6_stanzas[0] =~ /^[ \t]+dns-nameservers[ \t]+([^\n]+)$/mg;
                @dns == 1 && $dns[0] eq $config->{MANAGED_NETWORK_IPV6_DNS}
                    or die "$managed has incorrect IPv6 DNS for $iface\n";
            }
        }
    }
    return;
}

sub validate {
    my ($self) = @_;

    $self->_validate_paths();
    $self->logger()->validate_active_level();
    my $config = ManagedNetwork::Config->new(
        allowed_keys => [@CONFIG_KEYS],
        path         => $self->config_path(),
    )->load();
    my @types = $self->_validate_config_values($config);
    $self->_validate_staged_files($config, @types);
    $self->_wait_for_expected_interfaces($config, @types) if !$self->staged_only();
    for my $link_type (@types) {
        $self->_validate_expected_interface($config, $link_type);
    }
    $self->logger()->info('validated managed static network staging');
    return 0;
}

1;
