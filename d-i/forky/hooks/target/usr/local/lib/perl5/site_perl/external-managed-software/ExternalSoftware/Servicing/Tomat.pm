package ExternalSoftware::Servicing::Tomat;

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
        or die "Tomat package is not a regular file\n";
    open my $fh, '<:raw', $path
        or die "cannot read Tomat package: $!\n";
    my $digest = Digest::SHA->new(256);
    $digest->addfile($fh);
    close $fh
        or die "cannot close Tomat package: $!\n";
    return $digest->hexdigest();
}

# Bootstrap pins are supplied explicitly by the selected installer profile.
# Do not derive their digest from mutable release metadata or fall back to latest.
sub _pinned_release {
    my ($self, $tag, $url, $sha256) = @_;
    @_ == 4 && !grep { !defined $_ || ref $_ } ($tag, $url, $sha256)
        or die "Tomat pin requires scalar tag, URL and SHA-256 values\n";
    my ($version) = $tag =~ /\Av([0-9]+\.[0-9]+\.[0-9]+)\z/;
    defined $version && length($version) <= 32
        or die "Tomat pinned release tag is invalid\n";
    my ($package_version) = $url =~ m{\Ahttps://github\.com/jolars/tomat/releases/download/\Q$tag\E/tomat_(\Q$version\E-[1-9][0-9]{0,8})_amd64\.deb\z};
    defined $package_version
        or die "Tomat pinned URL does not match its tag and amd64 Debian asset\n";
    $sha256 =~ /\A[0-9a-f]{64}\z/
        or die "Tomat pinned SHA-256 is invalid\n";
    return {
        version => $version,
        package_version => $package_version,
        url => $url,
        sha256 => $sha256,
    };
}

sub _release {
    my ($self, $path) = @_;
    my $raw = ExternalSoftware::Servicing::Atomic->read_limited($path, 1_048_576);
    my $release = eval { decode_json($raw) };
    !$@ && ref $release eq 'HASH'
        or die "Tomat release metadata is not a JSON object\n";
    !$release->{draft} && !$release->{prerelease}
        or die "Tomat latest release is not stable\n";
    my ($version) = ($release->{tag_name} // q{}) =~ /\Av([0-9]+(?:\.[0-9]+)+)\z/
        or die "Tomat release tag is invalid\n";
    # Accept the versioned upstream Debian filename and the legacy spelling.
    # Multiple matching assets remain an error; never guess a package revision.
    my @assets = grep {
        ref $_ eq 'HASH' && !ref $_->{name}
            && (($_->{name} // q{}) eq 'tomat_amd64.deb'
                || ($_->{name} // q{}) =~ /\Atomat_\Q$version\E-[1-9][0-9]{0,8}_amd64\.deb\z/)
    } @{ref $release->{assets} eq 'ARRAY' ? $release->{assets} : []};
    @assets == 1
        or die "Tomat release has no unique amd64 Debian asset\n";
    my $asset = $assets[0];
    my $name = $asset->{name};
    my ($package_version) = $name =~ /\Atomat_(\Q$version\E-[1-9][0-9]{0,8})_amd64\.deb\z/;
    my $url = $asset->{browser_download_url} // q{};
    my $expected_url = "https://github.com/jolars/tomat/releases/download/v${version}/${name}";
    $url eq $expected_url
        or die "Tomat release asset URL is outside the approved repository\n";
    my $size = $asset->{size};
    defined $size && $size =~ /\A[0-9]+\z/ && $size >= 65_536 && $size <= 134_217_728
        or die "Tomat release asset size is outside approved bounds\n";
    my ($sha256) = ($asset->{digest} // q{}) =~ /\Asha256:([0-9a-f]{64})\z/
        or die "Tomat release asset SHA-256 is invalid\n";
    return {
        version => $version,
        package_version => $package_version,
        url     => $url,
        size    => 0 + $size,
        sha256  => $sha256,
    };
}

sub download {
    my ($self, $work) = @_;
    my $metadata_path = "$work/tomat-release.json";
    $self->http()->download(
        label => 'Tomat release metadata',
        url => 'https://api.github.com/repos/jolars/tomat/releases/latest',
        destination => $metadata_path,
        minimum => 256,
        maximum => 1_048_576,
        allowed_hosts => ['api.github.com'],
        content_policy => 'metadata',
    );
    return $self->_download_release($work, $self->_release($metadata_path));
}

sub download_pinned {
    my ($self, $work, $tag, $url, $sha256) = @_;
    @_ == 5 or die "Tomat pinned download requires workspace, tag, URL and SHA-256\n";
    return $self->_download_release($work, $self->_pinned_release($tag, $url, $sha256));
}

sub _download_release {
    my ($self, $work, $release) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path('Tomat workspace', $work);
    my $deb_path = "$work/tomat.deb";
    my $minimum = $release->{size} // 65_536;
    my $maximum = $release->{size} // 134_217_728;
    $self->http()->download(
        label => 'Tomat',
        url => $release->{url},
        destination => $deb_path,
        minimum => $minimum,
        maximum => $maximum,
        allowed_hosts => [qw(github.com objects.githubusercontent.com release-assets.githubusercontent.com)],
        content_policy => 'artifact',
    );
    my $size = -s $deb_path;
    defined $size && $size >= $minimum && $size <= $maximum
        && $self->_sha256($deb_path) eq $release->{sha256}
        or die "Tomat package digest or size does not match the verified release\n";
    my $metadata = $self->deb()->validate(
        label => 'Tomat',
        path => $deb_path,
        packages => ['tomat'],
        executable => '/usr/bin/tomat',
        desktop => q{}, # Upstream ships a CLI, not a desktop entry.
        required_executables => ['/usr/bin/tomat'],
    );
    my $matches = defined $release->{package_version}
        ? $metadata->{version} eq $release->{package_version}
        : $metadata->{version} =~ /\A\Q$release->{version}\E(?:-[0-9][A-Za-z0-9.+~]*)?\z/;
    $matches or die "Tomat package version does not match the verified release\n";
    return { path => $deb_path, metadata => $metadata };
}

1;
