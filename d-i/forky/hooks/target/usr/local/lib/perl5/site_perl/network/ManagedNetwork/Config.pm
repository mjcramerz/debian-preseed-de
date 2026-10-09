package ManagedNetwork::Config;

use strict;
use warnings;

use Errno qw(EINTR);
use Fcntl qw(O_NOFOLLOW O_NONBLOCK O_RDONLY);
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

sub read_file_limited {
    my ($class, $path, $maximum_bytes) = @_;

    defined($maximum_bytes) && !ref($maximum_bytes)
        && $maximum_bytes =~ /\A[1-9][0-9]*\z/
        or die "network file byte limit must be a positive integer\n";
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or die "cannot read $path: $!\n";
    binmode $fh, ':raw' or die "cannot set byte mode for $path: $!\n";
    my @stat = stat $fh;
    @stat && -f _
        or die "network file must be a regular file: $path\n";
    $stat[7] <= $maximum_bytes or die "network file is too large: $path\n";
    my $content = q{};
    while (1) {
        my $count = sysread($fh, $content, $maximum_bytes + 1 - length($content), length($content));
        if (!defined $count) {
            next if $! == EINTR;
            die "cannot read $path: $!\n";
        }
        last if !$count;
        length($content) <= $maximum_bytes or die "network file is too large: $path\n";
    }
    close $fh or die "cannot close $path: $!\n";
    return $content;
}

sub _read_file {
    my ($self) = @_;
    return __PACKAGE__->read_file_limited($self->path(), $self->maximum_bytes());
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
        my $parsed;
        my $complete = eval { $parsed = __PACKAGE__->parse_shell_value($raw_value); 1 };
        if (!$complete) {
            next if $@ =~ /unterminated quoted configuration value/;
            die "invalid shell value in " . $self->path() . ": $@";
        }
        my ($key) = $current =~ /\A([A-Z_][A-Z0-9_]*)=/;
        $allowed{$key}
            or die "unsupported config key in network defaults: $key\n";
        $config{$key} = $parsed;
        $current = q{};
    }
    $current eq q{}
        or die "unterminated quoted assignment in " . $self->path() . "\n";
    return \%config;
}

1;
