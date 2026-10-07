package LabwcNetworkControlAction::Validation;

use strict;
use warnings;

use Cwd qw(abs_path);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Socket qw(AF_INET AF_INET6 inet_ntop inet_pton);
use Types::Standard qw(Int Str);

has max_import_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 1_048_576 },
);

has wireguard_import_root => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/data/config/network/wireguard' },
);

has wireguard_root_owner_uid => (
    is      => 'ro',
    isa     => Int,
    default => sub { 0 },
);

has wireguard_file_owner_uid => (
    is      => 'ro',
    isa     => Int,
    default => sub { 0 },
);

has wireguard_root_group_gid => (
    is      => 'ro',
    isa     => Int,
    default => sub {
        my @group = getgrnam 'devops';
        @group && defined($group[2])
            or die "required WireGuard profile group is unavailable: devops\n";
        return $group[2];
    },
);

has wireguard_file_group_gid => (
    is      => 'ro',
    isa     => Int,
    default => sub { $_[0]->wireguard_root_group_gid() },
);

sub interface_name {
    my ($self, $name) = @_;

    defined($name) && $name ne q{}
        or die "network interface name is empty\n";
    length($name) <= 15
        or die "network interface name exceeds the Linux interface limit\n";
    $name !~ /\A-/ && $name =~ /\A[A-Za-z0-9_.-]+\z/
        or die "invalid network interface name: $name\n";
    return $name;
}

sub connection_uuid {
    my ($self, $uuid, $message) = @_;

    $message //= 'invalid NetworkManager connection UUID';
    defined($uuid)
        && $uuid =~ /\A[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\z/
        or die "$message\n";
    return $uuid;
}

sub import_file {
    my ($self, %args) = @_;

    my $label        = $args{label};
    my $requested    = $args{path};
    my $suffix       = $args{suffix};
    my $expected_uid = $args{owner_uid};

    defined($label) && $label ne q{} or die "invalid import label\n";
    defined($requested) && $requested =~ m{\A/}
        or die "$label path must be absolute\n";
    $requested !~ /[\r\n]/
        or die "$label path cannot contain newlines\n";
    defined($suffix) && $suffix ne q{} && $requested =~ /\Q$suffix\E\z/
        or die "$label path must end in $suffix\n";
    !-l $requested
        or die "$label path cannot be a symbolic link\n";
    -f $requested
        or die "$label path is not a regular file\n";
    -r $requested
        or die "$label path is not readable\n";

    my $resolved = abs_path($requested);
    defined($resolved)
        or die "unable to resolve $label path\n";
    $resolved eq $requested
        or die "$label path must already be canonical\n";
    !-l $resolved && -f $resolved
        or die "$label resolved path is not a regular file\n";

    my @metadata = stat $resolved;
    @metadata
        or die "unable to inspect $label metadata\n";
    defined($expected_uid) && $metadata[4] == $expected_uid
        or die "$label file must be owned by the invoking desktop user\n";
    my $mode = $metadata[2] & 07777;
    my %allowed_modes = map { $_ => 1 } (0400, 0440, 0444, 0600, 0640, 0644);
    $allowed_modes{$mode}
        or die "$label file permissions must not allow group or other writes\n";
    $metadata[7] <= $self->max_import_bytes()
        or die "$label file exceeds the managed " . $self->max_import_bytes() . "-byte limit\n";
    return $resolved;
}

sub wireguard_import_file {
    my ($self, %args) = @_;

    my $label     = 'WireGuard profile';
    my $requested = $args{path};
    my $root      = $self->wireguard_import_root();

    defined($root) && $root =~ m{\A/} && $root ne '/' && $root !~ m{//|/\.\.?/|/\.\.?\z}
        or die "managed WireGuard import root is invalid\n";
    !-l $root && -d $root
        or die "managed WireGuard import root is not a direct directory\n";
    my $resolved_root = abs_path($root);
    defined($resolved_root) && $resolved_root eq $root
        or die "managed WireGuard import root must already be canonical\n";
    my @root_metadata = stat $resolved_root;
    @root_metadata
        or die "unable to inspect managed WireGuard import root metadata\n";
    $root_metadata[4] == $self->wireguard_root_owner_uid()
        or die "managed WireGuard import root must be owned by root\n";
    $root_metadata[5] == $self->wireguard_root_group_gid()
        or die "managed WireGuard import root must use the devops group\n";
    ($root_metadata[2] & 07777) == 0750
        or die "managed WireGuard import root must have mode 0750\n";

    defined($requested) && $requested =~ m{\A/}
        or die "$label path must be absolute\n";
    $requested !~ /[\r\n]/
        or die "$label path cannot contain newlines\n";
    $requested =~ /\.conf\z/
        or die "$label path must end in .conf\n";
    my $prefix = "$resolved_root/";
    index($requested, $prefix) == 0
        or die "$label path must be below $resolved_root\n";
    my $filename = substr $requested, length $prefix;
    $filename ne q{} && $filename !~ m{/}
        or die "$label path must be a direct child of $resolved_root\n";
    !-l $requested
        or die "$label path cannot be a symbolic link\n";
    -f $requested
        or die "$label path is not a regular file\n";

    my $resolved = abs_path($requested);
    defined($resolved) && $resolved eq $requested
        or die "$label path must already be canonical\n";
    index($resolved, $prefix) == 0 && substr($resolved, length($prefix)) !~ m{/}
        or die "$label resolved path must be a direct child of $resolved_root\n";
    !-l $resolved && -f $resolved
        or die "$label resolved path is not a regular file\n";

    my @metadata = stat $resolved;
    @metadata
        or die "unable to inspect $label metadata\n";
    $metadata[4] == $self->wireguard_file_owner_uid()
        or die "$label file must be owned by root\n";
    my $mode = $metadata[2] & 07777;
    my %allowed_modes = map { $_ => 1 } (0400, 0440, 0600, 0640);
    $allowed_modes{$mode}
        or die "$label file permissions must be one of 0400, 0440, 0600, or 0640\n";
    if (($mode & 0040) != 0) {
        $metadata[5] == $self->wireguard_file_group_gid()
            or die "$label group-readable file must use the devops group\n";
    }
    $metadata[7] >= 1 && $metadata[7] <= $self->max_import_bytes()
        or die "$label file must contain between 1 and " . $self->max_import_bytes() . " bytes\n";
    return $resolved;
}

sub normalize_dns_servers {
    my ($self, $raw) = @_;

    defined($raw) && length($raw) <= 256
        or die "DNS server list exceeds 256 characters\n";
    my @items = grep { $_ ne q{} } split /[\s,]+/, $raw;
    @items >= 1 && @items <= 4
        or die "provide between one and four DNS server IP addresses\n";

    my @normalized;
    my %seen;
    for my $item (@items) {
        my ($family, $packed);
        if (defined(my $ipv4 = inet_pton(AF_INET, $item))) {
            ($family, $packed) = (AF_INET, $ipv4);
        }
        elsif (defined(my $ipv6 = inet_pton(AF_INET6, $item))) {
            ($family, $packed) = (AF_INET6, $ipv6);
        }
        else {
            die "invalid DNS server IP address: $item\n";
        }
        my $address = inet_ntop($family, $packed);
        next if $seen{$address}++;
        push @normalized, $address;
    }
    @normalized >= 1 && @normalized <= 4
        or die "provide between one and four DNS server IP addresses\n";
    return join q{,}, @normalized;
}

sub normalize_dns_families {
    my ($self, $raw) = @_;

    my $normalized = $self->normalize_dns_servers($raw);
    my (@ipv4, @ipv6);
    for my $address (split /,/, $normalized) {
        if (defined inet_pton(AF_INET, $address)) {
            push @ipv4, $address;
        }
        else {
            push @ipv6, $address;
        }
    }
    return (join(q{,}, @ipv4), join(q{,}, @ipv6));
}

1;
