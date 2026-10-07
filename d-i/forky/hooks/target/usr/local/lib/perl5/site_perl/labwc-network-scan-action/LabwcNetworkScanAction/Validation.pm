package LabwcNetworkScanAction::Validation;

use strict;
use warnings;

use Cwd qw(abs_path);
use File::Path qw(make_path);
use File::Spec;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(strftime);
use Types::Standard qw(Int);

has capture_directory_mode => (
    is      => 'ro',
    isa     => Int,
    default => sub { 0700 },
);

sub interface_name {
    my ($self, $interface) = @_;

    defined($interface) && $interface ne q{} && $interface =~ /\A[A-Za-z0-9_.:-]+\z/
        or die "invalid capture interface: " . (defined($interface) ? $interface : 'unset') . "\n";
    length($interface) <= 64
        or die "capture interface name is too long: $interface\n";
    return $interface;
}

sub capture_root {
    my ($self, $home) = @_;

    defined($home) && $home =~ m{\A/}
        or die "HOME must be an absolute path\n";
    $home !~ /[\r\n]/ && index($home, '..') < 0 && index($home, '//') < 0
        or die "HOME contains unsupported path syntax\n";
    return File::Spec->catdir($home, 'Captures', 'network-scanning');
}

sub prepare_capture_root {
    my ($self, $home) = @_;

    my $root = $self->capture_root($home);
    my @home_metadata = lstat $home;
    @home_metadata && -d _ && !-l _ && $home_metadata[4] == $<
        or die "HOME must be a real directory owned by the current user\n";
    make_path($root, { mode => $self->capture_directory_mode() });
    my @metadata = lstat $root;
    @metadata && -d _ && !-l _ && $metadata[4] == $<
        or die "managed capture directory must be a real directory owned by the current user\n";
    chmod $self->capture_directory_mode(), $root
        or die "cannot set managed capture directory permissions: $root: $!\n";
    return $root;
}

sub new_capture_path {
    my ($self, $home, $tool, $kind, $extension) = @_;

    defined($tool) && $tool =~ /\A[A-Za-z0-9._-]+\z/
        or die "invalid capture tool name\n";
    defined($kind) && $kind =~ /\A[A-Za-z0-9._-]+\z/
        or die "invalid capture kind\n";
    defined($extension) && $extension =~ /\A[A-Za-z0-9]+\z/
        or die "invalid capture extension\n";
    my $root = $self->prepare_capture_root($home);
    my $timestamp = strftime('%Y%m%dT%H%M%SZ', gmtime());
    return File::Spec->catfile($root, join('-', $timestamp, $tool, $kind, $$) . ".$extension");
}

sub capture_file {
    my ($self, $home, $requested) = @_;

    defined($requested) && $requested =~ m{\A/}
        or die "capture file must be an absolute path\n";
    $requested !~ /[\r\n]/
        or die "capture file cannot contain newlines\n";
    !-l $requested
        or die "capture file symlinks are not allowed\n";
    my $resolved = abs_path($requested);
    defined($resolved)
        or die "unable to resolve capture file: $requested\n";
    my $root = $self->capture_root($home);
    !-l $root
        or die "managed capture directory symlinks are not allowed\n";
    my $resolved_root = abs_path($root);
    defined($resolved_root)
        or die "unable to resolve managed capture directory: $root\n";
    index($resolved, "$resolved_root/") == 0
        or die "capture file is outside the managed capture directory\n";
    -f $resolved && !-l $resolved
        or die "capture file does not exist: $resolved\n";
    my @metadata = stat $resolved;
    @metadata && $metadata[4] == $<
        or die "capture file must be owned by the current user: $resolved\n";
    return $resolved;
}

sub _ipv4_octets {
    my ($self, $value, $label) = @_;

    defined($value)
        && $value =~ /\A(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\z/
        or die "invalid $label IPv4 address: $value\n";
    my @octets = ($1, $2, $3, $4);
    for my $octet (@octets) {
        $octet <= 255
            or die "invalid $label IPv4 address: $value\n";
    }
    return @octets;
}

sub _private_or_loopback {
    my ($self, @octets) = @_;

    return 1 if $octets[0] == 10 || $octets[0] == 127;
    return 1 if $octets[0] == 172 && $octets[1] >= 16 && $octets[1] <= 31;
    return 1 if $octets[0] == 192 && $octets[1] == 168;
    return 0;
}

sub private_target {
    my ($self, $target) = @_;

    defined($target) && $target =~ /\A([0-9.]+)(?:\/([0-9]+))?\z/
        or die "invalid private IPv4 target: $target\n";
    my ($address, $prefix) = ($1, defined($2) ? $2 : 32);
    $prefix !~ /\A0[0-9]+\z/ && $prefix >= 24 && $prefix <= 32
        or die "private network scans are bounded to /24 through /32 prefixes: $target\n";
    my @octets = $self->_ipv4_octets($address, 'private');
    $self->_private_or_loopback(@octets)
        or die "private scan scope requires RFC1918 or loopback IPv4: $target\n";
    $octets[0] != 127 || $prefix == 32
        or die "loopback scans must target one host\n";
    return $target;
}

sub public_target {
    my ($self, $target) = @_;

    defined($target) && $target !~ m{/}
        or die "WAN scans accept one public IPv4 host, not a CIDR: $target\n";
    my @octets = $self->_ipv4_octets($target, 'WAN');
    !$self->_private_or_loopback(@octets)
        or die "WAN scan scope cannot target private or loopback IPv4: $target\n";
    my ($first, $second, $third) = @octets;
    !(
        $first == 0
        || $first >= 224
        || ($first == 100 && $second >= 64 && $second <= 127)
        || ($first == 169 && $second == 254)
        || ($first == 192 && $second == 0 && ($third == 0 || $third == 2))
        || ($first == 192 && $second == 88 && $third == 99)
        || ($first == 198 && ($second == 18 || $second == 19))
        || ($first == 198 && $second == 51 && $third == 100)
        || ($first == 203 && $second == 0 && $third == 113)
    ) or die "WAN scans reject protocol-assignment, shared, link-local, relay-anycast, benchmark, documentation, multicast, and reserved IPv4 ranges: $target\n";
    return $target;
}

sub nmap_target {
    my ($self, $target, $scope) = @_;

    return $self->private_target($target)
        if defined($scope) && $scope eq 'private-scan';
    return $self->public_target($target)
        if defined($scope) && $scope eq 'authorized-wan-scan';
    die "unsupported Nmap target scope authorization: " . (defined($scope) ? $scope : 'unset') . "\n";
}

1;
