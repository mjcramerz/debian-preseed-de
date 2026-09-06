package ManagedNetwork::Config;

use strict;
use warnings;

use Fcntl qw(O_NOFOLLOW O_RDONLY);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(ArrayRef Int Str);

has allowed_keys => (
    is       => 'ro',
    isa      => ArrayRef,
    required => 1,
);

has maximum_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 65_536 },
);

has path => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

sub parse_shell_value {
    my ($class, $raw) = @_;

    defined($raw) or die "configuration value is undefined\n";
    $raw =~ /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/
        and die "configuration value contains a control character\n";
    $raw =~ s/\A[ \t]+//;
    $raw =~ s/[ \t]+\z//;
    return q{} if $raw eq q{};

    my $value = q{};
    my $state = 'bare';
    my $seen_space = 0;
    for (my $index = 0; $index < length($raw); ++$index) {
        my $character = substr($raw, $index, 1);
        if ($state eq 'single') {
            if ($character eq q{'}) {
                $state = 'bare';
            }
            else {
                $value .= $character;
            }
            next;
        }
        if ($state eq 'double') {
            if ($character eq q{"}) {
                $state = 'bare';
                next;
            }
            if ($character eq q{\\}) {
                ++$index < length($raw)
                    or die "unterminated escape in double-quoted configuration value\n";
                my $escaped = substr($raw, $index, 1);
                $escaped =~ /["\\\$`]/
                    or die "unsupported escape in double-quoted configuration value\n";
                $value .= $escaped;
                next;
            }
            $value .= $character;
            next;
        }

        if ($seen_space) {
            next if $character =~ /[ \t]/;
            last if $character eq '#';
            die "unsupported syntax after configuration value\n";
        }
        if ($character =~ /[ \t]/) {
            $seen_space = 1;
            next;
        }
        last if $character eq '#';
        if ($character eq q{'}) {
            $state = 'single';
            next;
        }
        if ($character eq q{"}) {
            $state = 'double';
            next;
        }
        if ($character eq q{\\}) {
            ++$index < length($raw)
                or die "unterminated escape in configuration value\n";
            my $escaped = substr($raw, $index, 1);
            $escaped =~ /[\\'# "]/ || $escaped =~ /[A-Za-z0-9._@%:+,\/=-]/
                or die "unsupported escape in configuration value\n";
            $value .= $escaped;
            next;
        }
        $character =~ /[A-Za-z0-9._@%:+,\/=\-\[\]\{\}\?]/
            or die "unsupported character in unquoted configuration value\n";
        $value .= $character;
    }
    $state eq 'bare'
        or die "unterminated quoted configuration value\n";
    return $value;
}

sub _read_file {
    my ($self) = @_;

    -l $self->path()
        and die "managed-network defaults must not be a symbolic link: " . $self->path() . "\n";
    sysopen my $fh, $self->path(), O_RDONLY | O_NOFOLLOW
        or die "cannot read " . $self->path() . ": $!\n";
    my @stat = stat $fh;
    @stat && -f _
        or die "managed-network defaults must be a regular file: " . $self->path() . "\n";
    $stat[7] <= $self->maximum_bytes()
        or die "config file is too large: " . $self->path() . "\n";
    local $/;
    my $content = <$fh>;
    close $fh or die "cannot close " . $self->path() . ": $!\n";
    return defined($content) ? $content : q{};
}

sub load {
    my ($self) = @_;

    my %allowed = map { $_ => 1 } @{ $self->allowed_keys() };
    my %config = map { $_ => q{} } @{ $self->allowed_keys() };
    my $raw = $self->_read_file();
    my $current = q{};

    for my $line (split /\n/, $raw, -1) {
        next if $current eq q{} && $line =~ /\A\s*(?:#|\z)/;
        $current = $current eq q{} ? $line : "$current\n$line";
        my ($raw_value) = $current =~ /\A[A-Z_][A-Z0-9_]*=(.*)\z/s;
        defined($raw_value)
            or die "invalid config assignment in " . $self->path() . "\n";
        my $complete = eval { __PACKAGE__->parse_shell_value($raw_value); 1 };
        if (!$complete) {
            next if $@ =~ /unterminated quoted configuration value/;
            die "invalid shell value in " . $self->path() . ": $@";
        }
        my ($key, $value) = $current =~ /\A([A-Z_][A-Z0-9_]*)=(.*)\z/s;
        $allowed{$key}
            or die "unsupported config key in managed-network defaults: $key\n";
        $config{$key} = __PACKAGE__->parse_shell_value($value);
        $current = q{};
    }
    $current eq q{}
        or die "unterminated quoted assignment in " . $self->path() . "\n";
    return \%config;
}

1;
