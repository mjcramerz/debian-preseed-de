package APTRepoLocal::Servicing::Sleek;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Digest::SHA;
use JSON::PP qw(decode_json);
use APTRepoLocal::Servicing::Atomic;

has http => (is => 'ro', required => 1);
has deb  => (is => 'ro', required => 1);
has release_policy => (is => 'ro', required => 1);

sub _limit {
    my ($self, $name) = @_;
    my $value = $self->release_policy()->{release_deb_limits}{sleek}{$name};
    defined $value && !ref $value && $value =~ /\A[1-9][0-9]*\z/
        or die "Sleek release policy limit is unavailable: $name\n";
    return 0 + $value;
}

sub _metadata_limit {
    my ($self, $name) = @_;
    my $value = $self->release_policy()->{metadata_limits}{$name};
    defined $value && !ref $value && $value =~ /\A[1-9][0-9]*\z/
        or die "Sleek metadata policy limit is unavailable: $name\n";
    return 0 + $value;
}

sub _sha256 {
    my ($self, $path) = @_;
    -f $path && !-l $path
        or die "Sleek package is not a regular file\n";
    open my $fh, '<:raw', $path
        or die "cannot read Sleek package: $!\n";
    my $digest = Digest::SHA->new(256);
    $digest->addfile($fh);
    close $fh
        or die "cannot close Sleek package: $!\n";
    return $digest->hexdigest();
}

sub _release {
    my ($self, $path) = @_;
    my $raw = APTRepoLocal::Servicing::Atomic->read_limited($path, $self->_metadata_limit('maximum_bytes'));
    my $release = eval { decode_json($raw) };
    !$@ && ref $release eq 'HASH'
        or die "Sleek release metadata is not a JSON object\n";
    !$release->{draft} && !$release->{prerelease}
        or die "Sleek latest release is not stable\n";
    my ($version) = ($release->{tag_name} // q{}) =~ /\Av([0-9]+(?:\.[0-9]+)+)\z/
        or die "Sleek release tag is invalid\n";
    my $name = "sleek-${version}-linux-amd64.deb";
    my @assets = grep {
        ref $_ eq 'HASH' && ($_->{name} // q{}) eq $name
    } @{ref $release->{assets} eq 'ARRAY' ? $release->{assets} : []};
    @assets == 1
        or die "Sleek release has no unique amd64 Debian asset\n";
    my $asset = $assets[0];
    my $url = $asset->{browser_download_url} // q{};
    my $size = $asset->{size};
    defined $size && $size =~ /\A[0-9]+\z/ && $size >= $self->_limit('minimum_bytes') && $size <= $self->_limit('maximum_bytes')
        or die "Sleek release asset size is outside approved bounds\n";
    my ($sha256) = ($asset->{digest} // q{}) =~ /\Asha256:([0-9a-f]{64})\z/
        or die "Sleek release asset SHA-256 is invalid\n";
    return {
        version => $version,
        url     => $url,
        size    => 0 + $size,
        sha256  => $sha256,
    };
}

sub download {
    my ($self, $work) = @_;
    my $metadata_path = "$work/sleek-release.json";
    my $deb_path = "$work/sleek.deb";
    $self->http()->download(
        label => 'Sleek release metadata',
        url => $self->release_policy()->{service_urls}{sleek_discovery},
        destination => $metadata_path,
        minimum => $self->_metadata_limit('minimum_bytes'),
        maximum => $self->_metadata_limit('maximum_bytes'),
        content_policy => 'metadata',
    );
    my $release = $self->_release($metadata_path);
    $self->http()->download(
        label => 'Sleek',
        url => $release->{url},
        destination => $deb_path,
        minimum => $release->{size},
        maximum => $release->{size},
        content_policy => 'artifact',
    );
    -s $deb_path == $release->{size}
        && $self->_sha256($deb_path) eq $release->{sha256}
        or die "Sleek package digest or size does not match release metadata\n";
    my $metadata = $self->deb()->validate(
        label => 'Sleek',
        path => $deb_path,
        packages => ['sleek'],
        executable => '/opt/sleek/sleek',
        desktop => '/usr/share/applications/sleek.desktop',
        library => '/opt/sleek/libffmpeg.so',
    );
    $metadata->{version} eq $release->{version}
        or die "Sleek package version does not match release metadata\n";
    return { path => $deb_path, metadata => $metadata };
}

1;
