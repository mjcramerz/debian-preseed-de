package AndroidADB::Firmware::Manifest;

use strict;
use warnings;

use Fcntl qw(O_NOFOLLOW O_RDONLY);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

use AndroidADB::Firmware::Validation qw(validate_manifest_scalar);
use AndroidADB::Validation qw(fail require_value);

my @MANIFEST_KEYS = qw(
  format
  samloader_version
  model
  region
  firmware_version
  downloaded_at
  archive_file
  archive_sha256
  bl_file
  bl_sha256
  ap_file
  ap_sha256
  cp_file
  cp_sha256
  csc_file
  csc_sha256
  home_csc_file
  home_csc_sha256
);

has storage => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub write {
    my ($self, $path, $values) = @_;
    require_value(ref($values) eq 'HASH', 'managed Samsung firmware manifest data is invalid');
    my @lines;
    for my $key (@MANIFEST_KEYS) {
        require_value(exists($values->{$key}), "managed Samsung firmware manifest is missing $key");
        validate_manifest_scalar($values->{$key}, $key);
        push @lines, "$key=$values->{$key}\n";
    }
    return $self->storage->write_text($path, join(q{}, @lines));
}

sub read {
    my ($self, $path) = @_;
    $self->storage->require_regular_file(
        $path,
        'Samsung firmware directory lacks managed download provenance',
    );
    my $flags = O_RDONLY;
    $flags |= O_NOFOLLOW if O_NOFOLLOW;
    sysopen my $file, $path, $flags
        or fail("unable to read managed Samsung firmware manifest: $!");
    my $content = q{};
    while (1) {
        my $bytes_read = read($file, my $chunk, 65_536);
        defined($bytes_read) or fail("unable to read managed Samsung firmware manifest: $!");
        last if $bytes_read == 0;
        $content .= $chunk;
        length($content) <= 65_536
            or fail('managed Samsung firmware manifest exceeds the managed size ceiling');
    }
    close $file or fail("unable to close managed Samsung firmware manifest: $!");

    my %values;
    for my $line (split /\n/, $content, -1) {
        next if $line eq q{};
        my ($key, $value) = $line =~ /\A([a-z_]+)=(.*)\z/
            or fail('managed Samsung firmware manifest contains invalid syntax');
        exists($values{$key})
            and fail("managed Samsung firmware manifest must contain one $key");
        validate_manifest_scalar($value, $key);
        $values{$key} = $value;
    }
    return \%values;
}

sub value {
    my ($self, $manifest, $key) = @_;
    require_value(ref($manifest) eq 'HASH', 'managed Samsung firmware manifest is invalid');
    require_value(
        exists($manifest->{$key}),
        "managed Samsung firmware manifest must contain one $key",
    );
    validate_manifest_scalar($manifest->{$key}, $key);
    return $manifest->{$key};
}

1;
