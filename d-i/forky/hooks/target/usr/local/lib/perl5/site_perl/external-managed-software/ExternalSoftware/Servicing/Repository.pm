package ExternalSoftware::Servicing::Repository;

use strict;
use warnings;
use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Base qw(Str);
use JSON::PP qw(decode_json);
use ExternalSoftware::Servicing::Atomic;
use ExternalSoftware::Servicing::Process;

# Compatibility boundary for explicit installer/bootstrap and offline repair.
# Runtime publication belongs exclusively to local-apt-repository; it never
# installs packages or invokes APT from an APT update hook.
has directory => (is => 'ro', isa => Str, default => sub { '/var/lib/software/repo' });
use constant HELPER => '/usr/local/libexec/local-apt-repository';

sub _capture {
    my ($self, @command) = @_;
    open my $fh, '-|', @command or return;
    my $output = do { local $/; <$fh> // q{} };
    close $fh or return;
    return $output;
}

sub refresh {
    my ($self) = @_;
    system(HELPER, 'rebuild') == 0
        or die "managed repository publication failed\n";
    return 1;
}

sub rebuild { return $_[0]->refresh(); }
sub write_source {
    system(HELPER, 'init') == 0
        or die "managed repository initialization failed\n";
    return 1;
}

sub retain {
    my ($self, $source, $metadata) = @_;
    my $path = $self->_capture(HELPER, 'import', '--', $source);
    defined $path or die "managed repository import failed\n";
    chomp $path;
    my $directory = $self->directory();
    $path =~ m{\A\Q$directory\E/pool/[a-z0-9][a-z0-9+.-]+/[0-9a-f]{64}/[A-Za-z0-9_.+:~-]+\.deb\z}
        or die "managed repository returned an unsafe package path\n";
    if ($metadata->{package} eq 'bitwarden') {
        my $digest = ExternalSoftware::Servicing::Atomic->sha256_file($source, 536_870_912);
        ExternalSoftware::Servicing::Atomic->write_text("$path.vendor-sha256", "$digest\n", 0644);
    }
    return wantarray ? ($path, 1) : $path;
}

sub latest {
    my ($self, $deb, $spec) = @_;
    my $raw = $self->_capture(HELPER, 'list');
    defined $raw or die "managed repository catalogue is unavailable\n";
    my $catalog = decode_json($raw);
    ref $catalog eq 'HASH' && ref $catalog->{packages} eq 'HASH'
        or die "managed repository catalogue is invalid\n";
    my %wanted = map { $_ => 1 } @{$spec->{packages}};
    my $candidate;
    for my $record (values %{$catalog->{packages}}) {
        next if !$wanted{$record->{package}};
        my $relative = $record->{filename};
        $relative =~ m{\Apool/[a-z0-9][a-z0-9+.-]+/[0-9a-f]{64}/[A-Za-z0-9_.+:~-]+\.deb\z}
            or die "managed repository catalogue path is invalid\n";
        my $path = $self->directory() . "/$relative";
        my $metadata = $deb->validate_spec($path, $spec, "$spec->{label} retained archive");
        next if !$metadata;
        my $digest;
        if ($spec->{name} eq 'bitwarden') {
            $digest = ExternalSoftware::Servicing::Atomic->sha256_file($path, 536_870_912);
            next if !$self->bitwarden_vendor_digest_matches("$path.vendor-sha256", $digest);
        }
        if (!$candidate || system('/usr/bin/dpkg', '--compare-versions', $metadata->{version},
                                  'gt', $candidate->{metadata}->{version}) == 0) {
            $candidate = { path => $path, metadata => $metadata, vendor_sha256 => $digest };
        }
    }
    return $candidate;
}

sub bitwarden_vendor_digest_matches {
    my ($self, $receipt, $digest) = @_;
    defined($digest) && $digest =~ /\A[0-9a-f]{64}\z/
        or die "Bitwarden vendor digest is missing or invalid\n";
    my @st = lstat $receipt;
    return 0 if !@st;
    -f _ && !-l _ && $st[4] == 0 && !($st[2] & 0022)
        or die "Bitwarden vendor receipt is unsafe: $receipt\n";
    return ExternalSoftware::Servicing::Atomic->read_limited($receipt, 65)
        eq "$digest\n";
}

sub repair {
    my ($self, $deb, $spec) = @_;
    my @packages = @{$spec->{packages}};
    for my $package (@packages) {
        my $status = $self->_capture('/usr/bin/dpkg-query', '-W', '-f=${Status}', $package) // q{};
        next if $status eq q{} || $status eq 'unknown ok not-installed'
            || $status eq 'deinstall ok config-files' || $status eq 'purge ok not-installed';
        if ($status eq 'install ok installed' && $deb->installed_payload_valid($spec)) {
            return 1;
        }
        my @executables = (
            $spec->{executable},
            @{$spec->{in_use_executables} // []},
        );
        return 0 if ExternalSoftware::Servicing::Process->application_running(
            executables => \@executables,
            roots       => $spec->{in_use_roots} // [],
        );
        my $version = $self->_capture('/usr/bin/dpkg-query', '-W', '-f=${Version}', $package) // q{};
        chomp $version;
        my $candidate = eval { $self->latest($deb, $spec) };
        my $archive = $candidate ? $candidate->{path} : undef;
        if (defined $archive && -f $archive && !-l $archive) {
            my $metadata = eval {
                $deb->validate_spec(
                    $archive,
                    $spec,
                    "$spec->{label} retained archive",
                );
            };
            my $repaired = $metadata && eval {
                $self->refresh();
                $deb->install($archive, 1);
                $deb->installed_payload_valid($spec);
            };
            if ($repaired) {
                return 1;
            }
        }
        if ($status ne 'install ok installed') {
            system('/usr/bin/dpkg', '--remove', '--force-remove-reinstreq', $package) == 0
                || system('/usr/bin/dpkg', '--purge', '--force-all', $package) == 0
                or die "$spec->{label} could not be removed from unrecoverable dpkg state\n";
        }
        return 0;
    }
    return 1;
}

1;
