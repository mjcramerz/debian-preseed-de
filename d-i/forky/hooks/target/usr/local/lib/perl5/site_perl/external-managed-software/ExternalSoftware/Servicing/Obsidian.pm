package ExternalSoftware::Servicing::Obsidian;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Digest::SHA;
use JSON::PP qw(decode_json);
use ExternalSoftware::Servicing::Atomic;

has http => (is => 'ro', required => 1);
has deb  => (is => 'ro', required => 1);

sub _sha256 {
    my ($self, $path) = @_;
    -f $path && !-l $path
        or die "Obsidian package is not a regular file\n";
    open my $fh, '<:raw', $path
        or die "cannot read Obsidian package: $!\n";
    my $digest = Digest::SHA->new(256);
    $digest->addfile($fh);
    close $fh
        or die "cannot close Obsidian package: $!\n";
    return $digest->hexdigest();
}

sub _release {
    my ($self, $path) = @_;
    my $raw = ExternalSoftware::Servicing::Atomic->read_limited($path, 1_048_576);
    my $release = eval { decode_json($raw) };
    !$@ && ref $release eq 'HASH'
        or die "Obsidian release metadata is not a JSON object\n";
    !$release->{draft} && !$release->{prerelease}
        or die "Obsidian latest release is not stable\n";
    my ($version) = ($release->{tag_name} // q{}) =~ /\Av([0-9]+\.[0-9]+\.[0-9]+)\z/
        or die "Obsidian release tag is invalid\n";
    my $name = "obsidian_${version}_amd64.deb";
    my @assets = grep {
        ref $_ eq 'HASH' && ($_->{name} // q{}) eq $name
    } @{ref $release->{assets} eq 'ARRAY' ? $release->{assets} : []};
    @assets == 1 or die "Obsidian release has no unique amd64 Debian asset\n";
    my $asset = $assets[0];
    my $url = $asset->{browser_download_url} // q{};
    my $expected_url = "https://github.com/obsidianmd/obsidian-releases/releases/download/v${version}/${name}";
    $url eq $expected_url or die "Obsidian release asset URL is outside the approved repository\n";
    my $size = $asset->{size};
    defined $size && $size =~ /\A[0-9]+\z/ && $size >= 67_108_864 && $size <= 209_715_200
        or die "Obsidian release asset size is outside approved bounds\n";
    my ($sha256) = ($asset->{digest} // q{}) =~ /\Asha256:([0-9a-f]{64})\z/
        or die "Obsidian release asset SHA-256 is invalid\n";
    return {
        version => $version,
        url     => $url,
        size    => 0 + $size,
        sha256  => $sha256,
    };
}

sub download {
    my ($self, $work) = @_;
    my $metadata_path = "$work/obsidian-release.json";
    my $deb_path = "$work/obsidian.deb";
    $self->http()->download(
        label => 'Obsidian release metadata',
        url => 'https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest',
        destination => $metadata_path,
        minimum => 256,
        maximum => 1_048_576,
        allowed_hosts => ['api.github.com'],
        content_policy => 'metadata',
    );
    my $release = $self->_release($metadata_path);
    $self->http()->download(
        label => 'Obsidian',
        url => $release->{url},
        destination => $deb_path,
        minimum => $release->{size},
        maximum => $release->{size},
        allowed_hosts => [qw(github.com objects.githubusercontent.com release-assets.githubusercontent.com)],
        content_policy => 'artifact',
    );
    -s $deb_path == $release->{size}
        && $self->_sha256($deb_path) eq $release->{sha256}
        or die "Obsidian package digest or size does not match release metadata\n";
    my $metadata = $self->deb()->validate(
        label => 'Obsidian',
        path => $deb_path,
        packages => ['obsidian'],
        executable => '/opt/Obsidian/obsidian',
        desktop => '/usr/share/applications/obsidian.desktop',
        library => '/opt/Obsidian/libffmpeg.so',
    );
    $metadata->{version} eq $release->{version}
        or die "Obsidian package version does not match release metadata\n";
    return { path => $deb_path, metadata => $metadata };
}

1;
