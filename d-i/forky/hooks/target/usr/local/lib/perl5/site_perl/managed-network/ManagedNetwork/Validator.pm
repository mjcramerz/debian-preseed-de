package ManagedNetwork::Validator;

use strict;
use warnings;

use File::Basename qw(dirname);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Socket qw(AF_INET6 inet_pton);
use Types::Standard qw(Str);

use ManagedNetwork::Config;
use ManagedNetwork::Logger;

my @CONFIG_KEYS = qw(
  MANAGED_NETWORK_MODE
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
        $config_path = "$prefix/etc/default/managed-network";
    }
    return $class->new(
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
    -d $self->sys_class_net()
        or die "sysfs net directory is missing: " . $self->sys_class_net() . "\n";
    $self->config_path() =~ m{\A/}
        or die "MANAGED_NETWORK_CONFIG must be absolute: " . $self->config_path() . "\n";
    -r $self->config_path()
        or die "managed-network defaults are missing: " . $self->config_path() . "\n";
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

    open my $fh, '<', $path or die "cannot read $path: $!\n";
    local $/;
    my $content = <$fh>;
    close $fh or die "cannot close $path: $!\n";
    length($content // q{}) <= 131_072
        or die "$path is too large\n";
    return $content // q{};
}

sub _iface_is_wifi {
    my ($self, $sys_iface) = @_;
    return -d "$sys_iface/wireless" || -d "$sys_iface/phy80211";
}

sub _read_sys_value {
    my ($self, $path) = @_;

    open my $fh, '<', $path or return undef;
    my $value = <$fh>;
    close $fh;
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
        lc($config->{MANAGED_NETWORK_WIFI_PSK_SECURITY}) =~ /\A(?:open|wep|open\/wep|wpa|sae)\z/
            or die "MANAGED_NETWORK_WIFI_PSK_SECURITY is invalid\n";
    }
    return @types;
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

    my $sys_iface = $self->sys_class_net() . "/$iface";
    -d $sys_iface
        or die "expected $link_type interface is absent: $iface\n";
    my $actual_mac = $self->_normalize_mac($self->_read_sys_value("$sys_iface/address") // q{});
    $actual_mac eq $mac
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

sub _validate_staged_files {
    my ($self, $config, @types) = @_;

    my $interfaces = $self->_target_path('/etc/network/interfaces');
    my $managed = $self->_target_path('/etc/network/interfaces.d/50-managed-network');
    -r $interfaces or die "missing $interfaces\n";
    -r $managed or die "missing $managed\n";
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
    my $ipv6_enabled = lc($config->{MANAGED_NETWORK_IPV6_ENABLED}) eq 'true' ? 1 : 0;
    for my $link_type (@types) {
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
        next if $link_type ne 'wifi' || $config->{MANAGED_NETWORK_WIFI_ESSID} eq q{};
        $content =~ /^[ \t]+wpa-ssid[ \t]+\Q$config->{MANAGED_NETWORK_WIFI_ESSID}\E[ \t]*$/m
            or die "$managed lacks Wi-Fi SSID stanza\n";
        my $security = lc($config->{MANAGED_NETWORK_WIFI_PSK_SECURITY});
        if ($security eq 'sae') {
            $content =~ /^[ \t]+wpa-key-mgmt[ \t]+SAE[ \t]*$/m
                or die "$managed lacks SAE key management\n";
            $content =~ /^[ \t]+wpa-psk[ \t]+\S+[ \t]*$/m
                or die "$managed lacks WPA/SAE PSK material\n";
        }
        elsif ($security eq 'wpa') {
            $content =~ /^[ \t]+wpa-key-mgmt[ \t]+WPA-PSK[ \t]*$/m
                or die "$managed lacks WPA-PSK key management\n";
            $content =~ /^[ \t]+wpa-psk[ \t]+\S+[ \t]*$/m
                or die "$managed lacks WPA/SAE PSK material\n";
        }
        elsif ($security eq 'wep') {
            $content =~ /^[ \t]+wpa-wep-key0[ \t]+\S+[ \t]*$/m
                or die "$managed lacks WEP key material\n";
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
    for my $link_type (@types) {
        $self->_validate_expected_interface($config, $link_type);
    }
    $self->_validate_staged_files($config, @types);
    $self->logger()->info('validated managed static network staging');
    return 0;
}

1;
