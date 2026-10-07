package LabwcSecurityAction::AppArmor::ProfileIndex;

use strict;
use warnings;

use File::Basename qw(basename);
use Fcntl qw(O_NOFOLLOW O_RDONLY);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Int Object Str);

use LabwcSecurityAction::Command;

has command => (
    is      => 'ro',
    isa     => Object,
    default => sub {
        return LabwcSecurityAction::Command->new(
            path => '/usr/sbin:/usr/bin:/sbin:/bin',
        );
    },
);

has maximum_labels_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 65_536 },
);

has maximum_profile_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 1_048_576 },
);

has maximum_profile_files => (
    is      => 'ro',
    isa     => Int,
    default => sub { 512 },
);

has parser_config => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/apparmor/parser.conf' },
);

has profile_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/apparmor.d' },
);

has trusted_uid => (
    is      => 'ro',
    isa     => Int,
    default => sub { 0 },
);

sub build {
    my ($self) = @_;

    $self->_validate_profile_dir();
    opendir my $dh, $self->profile_dir()
        or die "cannot read AppArmor profile directory: " . $self->profile_dir() . ": $!\n";
    my (@sources, $count);
    while (my $name = readdir $dh) {
        next if $name eq q{.} || $name eq q{..};
        next if $name !~ /\A[A-Za-z0-9][A-Za-z0-9._+-]*\z/;
        my $path = $self->profile_dir() . "/$name";
        next if !-f $path || -l $path;
        ++$count;
        $count <= $self->maximum_profile_files()
            or die "more than " . $self->maximum_profile_files()
                . " AppArmor profile files were found\n";
        $self->_validate_profile_file($path);
        push @sources, [$name, $path];
    }
    closedir $dh
        or die "cannot close AppArmor profile directory: $!\n";

    my %index;
    for my $source (sort { $a->[0] cmp $b->[0] } @sources) {
        my ($source_name, $source_path) = @{$source};
        my $labels = $self->_profile_labels($source_path);
        my $local_map = $self->_local_include_map($source_path);
        my %unique_local = map { $_ => 1 }
            grep { defined($_) && $_ ne q{} } values %{$local_map};
        my $single_local = keys(%unique_local) == 1
            ? (keys %unique_local)[0]
            : undef;

        for my $label (@{$labels}) {
            exists($index{$label})
                and die "AppArmor profile label is defined by multiple files: $label\n";
            my $local_name = $local_map->{$label};
            if (!defined($local_name) && exists($local_map->{$source_name})) {
                $local_name = $local_map->{$source_name};
            }
            $local_name = $single_local if !defined($local_name);
            $index{$label} = {
                label       => $label,
                local_name  => $local_name,
                local_path  => defined($local_name)
                    ? $self->profile_dir() . "/local/$local_name"
                    : undef,
                source_name => $source_name,
                source_path => $source_path,
            };
        }
    }
    return \%index;
}

sub resolve {
    my ($self, $index, $profile) = @_;

    defined($profile) && $profile ne q{} &&
        length($profile) <= 1_024 &&
        $profile !~ /[\x00-\x1f\x7f]/
        or return;
    my $candidate = $profile;
    while (1) {
        if (my $entry = $index->{$candidate}) {
            return {
                %{$entry},
                requested_label => $profile,
                resolved_label  => $candidate,
            };
        }
        last if $candidate !~ s{//[^/]+\z}{};
    }
    return;
}

sub _validate_profile_dir {
    my ($self) = @_;

    my @metadata = lstat($self->profile_dir());
    @metadata && ($metadata[2] & 0170000) == 0040000 && !-l $self->profile_dir()
        or die "AppArmor profile directory must be a real directory: "
            . $self->profile_dir() . "\n";
    $metadata[4] == $self->trusted_uid()
        or die "AppArmor profile directory must be owned by the trusted account\n";
    ($metadata[2] & 0022) == 0
        or die "AppArmor profile directory must not be group- or world-writable\n";
    my $local_dir = $self->profile_dir() . '/local';
    my @local = lstat($local_dir);
    @local && ($local[2] & 0170000) == 0040000 && !-l $local_dir
        or die "AppArmor local policy directory must be a real directory: $local_dir\n";
    $local[4] == $self->trusted_uid()
        or die "AppArmor local policy directory must be owned by the trusted account\n";
    ($local[2] & 0022) == 0
        or die "AppArmor local policy directory must not be group- or world-writable\n";
    return;
}

sub _validate_profile_file {
    my ($self, $path) = @_;

    my @metadata = lstat($path);
    @metadata && ($metadata[2] & 0170000) == 0100000 && !-l $path
        or die "AppArmor profile must be a regular non-symlink file: $path\n";
    $metadata[4] == $self->trusted_uid()
        or die "AppArmor profile must be owned by the trusted account: $path\n";
    ($metadata[2] & 0022) == 0
        or die "AppArmor profile must not be group- or world-writable: $path\n";
    $metadata[7] <= $self->maximum_profile_bytes()
        or die "AppArmor profile exceeds " . $self->maximum_profile_bytes()
            . " bytes: $path\n";
    return;
}

sub _profile_labels {
    my ($self, $source) = @_;

    my $parser = $self->command()->require_executable('apparmor_parser');
    my ($status, $output) = $self->command()->capture(
        argv => [
            $parser,
            '--config-file', $self->parser_config(),
            '-q', '-N', '-Q', '-K', '-T',
            '-I', $self->profile_dir(),
            '--base', $self->profile_dir(),
            $source,
        ],
    );
    $status == 0
        or die "cannot derive AppArmor profile labels from: $source\n";
    length($output) > 0
        or die "AppArmor profile defines no labels: $source\n";
    length($output) <= $self->maximum_labels_bytes()
        or die "AppArmor profile labels exceed " . $self->maximum_labels_bytes()
            . " bytes: $source\n";
    my %labels;
    for my $label (split /\n/, $output) {
        next if $label eq q{};
        length($label) <= 1_024 && $label !~ /[\x00-\x1f\x7f]/
            or die "AppArmor parser returned an invalid profile label: $source\n";
        $labels{$label} = 1;
    }
    keys(%labels)
        or die "AppArmor profile defines no labels: $source\n";
    return [sort keys %labels];
}

sub _local_include_map {
    my ($self, $source) = @_;

    sysopen my $fh, $source, O_RDONLY | O_NOFOLLOW
        or die "cannot read AppArmor profile source: $source: $!\n";
    binmode $fh, ':raw'
        or die "cannot read AppArmor profile source: $source: $!\n";
    my (@stack, %includes, $line_number);
    while (my $line = <$fh>) {
        ++$line_number;
        length($line) <= 65_536
            or die "AppArmor profile line $line_number is too large: $source\n";

        if (my $label = $self->_profile_header($line, \@stack)) {
            push @stack, $label;
            next;
        }
        if ($line =~ /^\s*#?\s*include\s+if\s+exists\s+<local\/([A-Za-z0-9._+-]+)>\s*(?:#.*)?\z/) {
            my $local_name = $1;
            my $label = @stack ? $stack[-1] : basename($source);
            if (exists($includes{$label}) &&
                $includes{$label} ne $local_name) {
                $includes{$label} = undef;
            }
            elsif (!exists($includes{$label})) {
                $includes{$label} = $local_name;
            }
            next;
        }
        if ($line =~ /^\s*}\s*(?:#.*)?\z/) {
            pop @stack if @stack;
        }
    }
    close $fh
        or die "cannot close AppArmor profile source: $source: $!\n";
    return \%includes;
}

sub _profile_header {
    my ($self, $line, $stack) = @_;

    my $token;
    if ($line =~ /^\s*profile\s+("(?:\\.|[^"\\])*"|[A-Za-z0-9._+@%:\/-]+)(?:\s+.*?)?\{\s*(?:#.*)?\z/) {
        $token = $1;
    }
    elsif ($line =~ /^\s*("(?:\\.|[^"\\])*"|\/[A-Za-z0-9._+@%:\/,{}*?\[\]^-]+)(?:\s+.*?)?\{\s*(?:#.*)?\z/) {
        $token = $1;
    }
    elsif ($line =~ /^\s*(?:hat\s+|\^)("(?:\\.|[^"\\])*"|[A-Za-z0-9._+@%:\/-]+)(?:\s+.*?)?\{\s*(?:#.*)?\z/) {
        $token = $1;
    }
    else {
        return;
    }

    my $label = $self->_decode_profile_token($token);
    return @{$stack} ? $stack->[-1] . "//$label" : $label;
}

sub _decode_profile_token {
    my ($self, $token) = @_;

    if ($token =~ /\A"(.*)"\z/s) {
        $token = $1;
        my $decoded = q{};
        while (length($token)) {
            if ($token =~ s/\A([^\\]+)//s) {
                $decoded .= $1;
                next;
            }
            if ($token =~ s/\A\\([\\"])//) {
                $decoded .= $1;
                next;
            }
            die "unsupported quoted AppArmor profile label escape\n";
        }
        $token = $decoded;
    }
    length($token) <= 1_024 && $token !~ /[\x00-\x1f\x7f]/
        or die "invalid AppArmor profile label in source\n";
    return $token;
}

1;
