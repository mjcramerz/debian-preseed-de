package AppArmor::ManagedModes::TrustedPath;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Fcntl qw(O_NOFOLLOW O_RDONLY);

use AppArmor::ManagedModes::CLI qw(fatal);

our @EXPORT_OK = qw(
    bounded_capture
    file_size
    read_bounded_file
    validate_absolute_path
    validate_real_directory
    validate_root_owned_file
);

sub validate_absolute_path {
    my ($label, $value) = @_;
    my $shown_value = defined($value) && $value ne '' ? $value : 'unset';

    defined($value) && $value =~ m{\A/} ||
        fatal("$label must be an absolute path: $shown_value");
    $value ne '/' &&
        index($value, '..') == -1 &&
        index($value, '//') == -1 &&
        $value !~ /[^A-Za-z0-9._\/\@%:+,\-]/ ||
        fatal("$label contains unsupported path syntax: $value");
}

sub validate_real_directory {
    my ($label, $path) = @_;

    -d $path && !-l $path ||
        fatal("$label must be a real directory: $path");
}

sub validate_root_owned_file {
    my ($label, $path, $max_bytes) = @_;

    -f $path && !-l $path ||
        fatal("$label must be a regular non-symlink file: $path");
    my ($owner_uid, $permissions, $size_bytes, $file_type) =
        _file_metadata($path);
    $file_type == 0100000 ||
        fatal("$label must be a regular non-symlink file: $path");
    $owner_uid == 0 ||
        fatal("$label must be owned by root: $path");
    !($permissions & 0022) ||
        fatal("$label must not be group- or world-writable: $path");
    $size_bytes <= $max_bytes ||
        fatal("$label exceeds ${max_bytes} bytes: $path");
}

sub read_bounded_file {
    my ($label, $path, $max_bytes) = @_;

    -l $path && fatal("$label must not be a symlink: $path");
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW ||
        fatal("cannot read $label: $path");
    binmode $fh, ':raw' ||
        fatal("cannot read $label: $path");

    my $content = '';
    my $remaining = $max_bytes + 1;
    while ($remaining > 0) {
        my $buffer = '';
        my $read = sysread(
            $fh,
            $buffer,
            $remaining > 65_536 ? 65_536 : $remaining,
        );
        defined($read) || fatal("cannot read $label: $path");
        last if $read == 0;
        $content .= $buffer;
        $remaining -= $read;
    }
    close $fh || fatal("cannot read $label: $path");

    length($content) <= $max_bytes ||
        fatal("$label exceeds ${max_bytes} bytes: $path");
    return $content;
}

sub bounded_capture {
    my ($label, $source, $target, $max_bytes) = @_;
    my $content = read_bounded_file($label, $source, $max_bytes);

    open my $fh, '>:raw', $target ||
        fatal("cannot read $label: $source");
    if (length($content)) {
        print {$fh} $content ||
            fatal("cannot read $label: $source");
    }
    close $fh || fatal("cannot read $label: $source");
}

sub file_size {
    my ($path) = @_;
    my @metadata = stat($path);
    @metadata || fatal("cannot inspect file metadata: $path");
    return $metadata[7];
}

sub _file_metadata {
    my ($path) = @_;

    my @metadata = lstat($path);
    @metadata ||
        fatal("cannot inspect file metadata: $path");
    my $mode = $metadata[2];
    return (
        $metadata[4],
        $mode & 07777,
        $metadata[7],
        $mode & 0170000,
    );
}

1;
