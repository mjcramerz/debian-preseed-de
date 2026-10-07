package AICopilots::ModelCatalog;

use strict;
use warnings;

use Cwd qw(abs_path);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Str);

has catalog_directory => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/share/labwc-ai-copilots' },
);

my @CATALOG_FIELDS = qw(
    id
    display_name
    language
    parameters
    file_mib
    min_ram_gib
    recommended_ram_gib
    cpu_cores
    weights
    repository
    revision
    remote_filename
    local_filename
    notes
);

my $CATALOG_HEADER = join "\t", @CATALOG_FIELDS;
my $TABLE_FORMAT =
    '%-32.32s  %-12.12s  %-7.7s  %9.9s  %7.7s  %7.7s  %7.7s  %-10.10s  %.36s';

sub _fatal {
    my ($message) = @_;
    die "managed AI model catalog: $message\n";
}

sub _family_policy {
    my ($family) = @_;
    return {
        catalog => 'llama-models.tsv',
        filename =>
            qr/\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.gguf\z/,
        maximum_mib => 102_400,
    } if $family eq 'llama';
    return {
        catalog => 'whisper-models.tsv',
        filename =>
            qr/\Aggml-[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.bin\z/,
        maximum_mib => 20_480,
    } if $family eq 'whisper';
    _fatal('unsupported model family');
}

sub _catalog_path {
    my ($self, $family) = @_;
    my $policy = _family_policy($family);
    return $self->catalog_directory() . '/' . $policy->{catalog};
}

sub _read_catalog {
    my ($self, $family) = @_;
    my $directory = $self->catalog_directory();
    -d $directory && !-l $directory
        or _fatal('catalog directory is unavailable');
    my $resolved_directory = abs_path($directory);
    defined($resolved_directory) && $resolved_directory eq $directory
        or _fatal('catalog directory is not canonical');
    my @directory_stat = lstat $directory;
    $directory_stat[4] == 0 && $directory_stat[5] == 0
        && ($directory_stat[2] & 07777) == 0755
        or _fatal('catalog directory ownership or mode is unsafe');

    my $path = $self->_catalog_path($family);
    -f $path && !-l $path
        or _fatal("catalog file is unavailable: $family");
    my $resolved_path = abs_path($path);
    defined($resolved_path) && $resolved_path eq $path
        or _fatal("catalog file is not canonical: $family");
    my @stat = lstat $path;
    $stat[4] == 0 && $stat[5] == 0
        && ($stat[2] & 07777) == 0644
        && $stat[7] >= length($CATALOG_HEADER) + 2
        && $stat[7] <= 262_144
        or _fatal("catalog file ownership, mode, or size is unsafe: $family");

    open my $fh, '<:raw', $path
        or _fatal("cannot read catalog file: $family: $!");
    local $/;
    my $content = <$fh>;
    close $fh
        or _fatal("cannot close catalog file: $family: $!");
    return $content;
}

sub _validate_text_field {
    my ($label, $value, $maximum) = @_;
    defined($value) && !ref($value)
        && length($value) >= 1 && length($value) <= $maximum
        && $value =~ /\A[\x20-\x7e]+\z/
        && $value !~ /\A[[:space:]]|[[:space:]]\z/
        or _fatal("$label is invalid");
    return $value;
}

sub _validate_positive_integer {
    my ($label, $value, $maximum) = @_;
    defined($value) && !ref($value) && $value =~ /\A[0-9]{1,6}\z/
        && $value >= 1 && $value <= $maximum
        or _fatal("$label is outside the supported bounds");
    return int($value);
}

sub _validate_cpu_cores {
    my ($value) = @_;
    defined($value) && !ref($value)
        && $value =~ /\A([0-9]{1,3})(?:-([0-9]{1,3}))?\z/
        or _fatal('recommended CPU core count is invalid');
    my ($minimum, $maximum) = (int($1), defined($2) ? int($2) : int($1));
    $minimum >= 1 && $maximum >= $minimum && $maximum <= 128
        or _fatal('recommended CPU core count is outside the supported bounds');
    return $value;
}

sub parse_content {
    my ($self, $family, $content) = @_;
    my $policy = _family_policy($family);
    defined($content) && !ref($content)
        && length($content) <= 262_144
        && $content =~ /\A[\x09\x0a\x20-\x7e]+\z/
        && $content =~ /\n\z/
        or _fatal("catalog encoding or framing is invalid: $family");

    my @lines = split /\n/, $content, -1;
    pop @lines;
    @lines && shift(@lines) eq $CATALOG_HEADER
        or _fatal("catalog header is invalid: $family");
    @lines >= 40 && @lines <= 50
        or _fatal("catalog must contain 40 to 50 models: $family");

    my (%seen_id, %seen_filename, %seen_display, %seen_remote);
    my @entries;
    for my $line (@lines) {
        length($line) >= 1 && length($line) <= 1024
            or _fatal("catalog row length is invalid: $family");
        my @values = split /\t/, $line, -1;
        @values == @CATALOG_FIELDS
            or _fatal("catalog row field count is invalid: $family");
        my %entry;
        @entry{@CATALOG_FIELDS} = @values;

        $entry{id} =~ /\A[a-z0-9][a-z0-9._-]{0,63}\z/
            && $entry{id} !~ /\.\./
            or _fatal("catalog model identifier is invalid: $family");
        _validate_text_field('catalog model name', $entry{display_name}, 48);
        _validate_text_field('catalog model language', $entry{language}, 24);
        $entry{language} =~ /\A[A-Za-z][A-Za-z +\/-]{0,23}\z/
            or _fatal("catalog model language is invalid: $family");
        $entry{parameters} =~ /\A[0-9]{1,4}(?:\.[0-9]{1,2})?[MB]\z/
            or _fatal("catalog parameter count is invalid: $family");
        $entry{file_mib} = _validate_positive_integer(
            'catalog model file size',
            $entry{file_mib},
            $policy->{maximum_mib},
        );
        $entry{min_ram_gib} = _validate_positive_integer(
            'catalog minimum RAM',
            $entry{min_ram_gib},
            256,
        );
        $entry{recommended_ram_gib} = _validate_positive_integer(
            'catalog recommended RAM',
            $entry{recommended_ram_gib},
            512,
        );
        $entry{recommended_ram_gib} >= $entry{min_ram_gib}
            or _fatal("catalog RAM recommendation is invalid: $family");
        _validate_cpu_cores($entry{cpu_cores});
        $entry{weights} =~ /\A[A-Za-z0-9][A-Za-z0-9._+-]{0,23}\z/
            or _fatal("catalog model weights are invalid: $family");
        $entry{repository} =~
            m{\A[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}\z}
            && $entry{repository} !~ /(?:\A|\/)\.\.(?:\/|\z)/
            or _fatal("catalog repository is invalid: $family");
        $entry{revision} =~ /\A[0-9a-f]{40}\z/
            or _fatal("catalog revision is invalid: $family");
        for my $field (qw(remote_filename local_filename)) {
            $entry{$field} =~ $policy->{filename}
                && $entry{$field} !~ /\.\./
                or _fatal("catalog model filename is invalid: $family");
        }
        _validate_text_field('catalog model notes', $entry{notes}, 120);

        !$seen_id{$entry{id}}++
            or _fatal("catalog repeats a model identifier: $family");
        !$seen_filename{lc $entry{local_filename}}++
            or _fatal("catalog repeats a local filename: $family");
        my $display_identity =
            lc join "\t", $entry{display_name}, $entry{weights};
        !$seen_display{$display_identity}++
            or _fatal("catalog repeats a display identity: $family");
        my $remote_identity = join "\t",
            $entry{repository}, $entry{revision}, $entry{remote_filename};
        !$seen_remote{$remote_identity}++
            or _fatal("catalog repeats a remote file: $family");

        push @entries, \%entry;
    }
    return @entries;
}

sub entries {
    my ($self, $family) = @_;
    return $self->parse_content($family, $self->_read_catalog($family));
}

sub entry_by_id {
    my ($self, $family, $requested_id) = @_;
    defined($requested_id) && !ref($requested_id)
        && $requested_id =~ /\A[a-z0-9][a-z0-9._-]{0,63}\z/
        && $requested_id !~ /\.\./
        or _fatal('catalog model identifier is invalid');
    my @matches = grep { $_->{id} eq $requested_id } $self->entries($family);
    @matches == 1
        or _fatal('catalog model identifier is unknown');
    return $matches[0];
}

sub table_row {
    my ($self, $entry) = @_;
    return sprintf(
        $TABLE_FORMAT,
        $entry->{display_name},
        $entry->{language},
        $entry->{parameters},
        $entry->{file_mib} . ' MiB',
        $entry->{min_ram_gib} . ' GiB',
        $entry->{recommended_ram_gib} . ' GiB',
        $entry->{cpu_cores},
        $entry->{weights},
        $entry->{notes},
    );
}

sub table_lines {
    my ($self, $family) = @_;
    my @entries = $self->entries($family);
    my $header = sprintf(
        $TABLE_FORMAT,
        'MODEL',
        'LANGUAGE',
        'PARAMS',
        'SIZE',
        'RAM MIN',
        'RAM REC',
        'CPU',
        'WEIGHTS',
        'NOTES',
    );
    my $separator = sprintf(
        $TABLE_FORMAT,
        '-' x 32,
        '-' x 12,
        '-' x 7,
        '-' x 9,
        '-' x 7,
        '-' x 7,
        '-' x 7,
        '-' x 10,
        '-' x 36,
    );
    return ($header, $separator, map { $self->table_row($_) } @entries);
}

sub entry_by_display {
    my ($self, $family, $requested_display) = @_;
    defined($requested_display) && !ref($requested_display)
        && length($requested_display) >= 1
        && length($requested_display) <= 200
        && $requested_display =~ /\A[\x20-\x7e]+\z/
        or _fatal('catalog display selection is invalid');
    my @matches = grep {
        $self->table_row($_) eq $requested_display
    } $self->entries($family);
    @matches == 1
        or _fatal('catalog display selection is unknown');
    return $matches[0];
}

1;
