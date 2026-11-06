package APTRepoLocal::Servicing::Tomat;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Digest::SHA;
use JSON::PP qw(decode_json);
use APTRepoLocal::Servicing::Atomic;

has http => (is => 'ro', required => 1);
has deb  => (is => 'ro', required => 1);
has release_policy => (is => 'ro');

sub _limit {
    my ($self, $name) = @_;
    my $value = $self->release_policy()->{release_deb_limits}{tomat}{$name};
    defined $value && !ref $value && $value =~ /\A[1-9][0-9]*\z/
        or die "Tomat release policy limit is unavailable: $name\n";
    return 0 + $value;
}

sub _metadata_limit {
    my ($self, $name) = @_;
    my $value = $self->release_policy()->{metadata_limits}{$name};
    defined $value && !ref $value && $value =~ /\A[1-9][0-9]*\z/
        or die "Tomat metadata policy limit is unavailable: $name\n";
    return 0 + $value;
}

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
    my ($asset_name) = $url =~ m{\Ahttps://[^\s/]+(?:/[^\s/]+)*/releases/download/\Q$tag\E/([^/\s]+\.deb)\z};
    defined $asset_name or die "Tomat pinned URL does not match its release tag and Debian asset\n";
    $sha256 =~ /\A[0-9a-f]{64}\z/
        or die "Tomat pinned SHA-256 is invalid\n";
    return {
        version => $version,
        package_version => undef,
        url => $url,
        sha256 => $sha256,
    };
}

sub _release {
    my ($self, $path) = @_;
    my $raw = APTRepoLocal::Servicing::Atomic->read_limited($path, $self->_metadata_limit('maximum_bytes'));
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
    my $size = $asset->{size};
    defined $size && $size =~ /\A[0-9]+\z/ && $size >= $self->_limit('minimum_bytes') && $size <= $self->_limit('maximum_bytes')
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
        url => $self->release_policy()->{service_urls}{tomat_discovery},
        destination => $metadata_path,
        minimum => $self->_metadata_limit('minimum_bytes'),
        maximum => $self->_metadata_limit('maximum_bytes'),
        content_policy => 'metadata',
    );
    return $self->_download_release($work, $self->_release($metadata_path));
}

sub download_pinned {
    my ($self, $work, $tag, $url, $sha256, $minimum, $maximum) = @_;
    @_ == 7 or die "Tomat pinned download requires workspace, tag, URL, SHA-256 and byte bounds\n";
    defined $minimum && defined $maximum
        && $minimum =~ /\A[1-9][0-9]*\z/
        && $maximum =~ /\A[1-9][0-9]*\z/
        && $minimum <= $maximum
        or die "Tomat pinned download byte bounds are invalid\n";
    return $self->_download_release(
        $work,
        $self->_pinned_release($tag, $url, $sha256),
        0 + $minimum,
        0 + $maximum,
    );
}

sub _download_release {
    my ($self, $work, $release, $minimum, $maximum) = @_;
    APTRepoLocal::Servicing::Atomic->assert_absolute_path('Tomat workspace', $work);
    my $deb_path = "$work/tomat.deb";
    $minimum //= $release->{size} // $self->_limit('minimum_bytes');
    $maximum //= $release->{size} // $self->_limit('maximum_bytes');
    $self->http()->download(
        label => 'Tomat',
        url => $release->{url},
        destination => $deb_path,
        minimum => $minimum,
        maximum => $maximum,
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
