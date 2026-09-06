package WhisperMode::Config;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(sysconf);
use Fcntl qw(O_RDONLY O_NOFOLLOW O_NONBLOCK);
use Errno qw(EINTR);
use Types::Standard qw(HashRef Str);

has path => (
    is      => 'ro',
    isa     => Str,
    default => sub { $ENV{WHISPER_CONFIG_FILE} // '/etc/whisper/whisper.conf' },
);

has values => (
    is      => 'lazy',
    isa     => HashRef,
    builder => '_build_values',
);

sub _fatal {
    my ($message) = @_;
    die "whisper-record-toggle: $message\n";
}

sub _safe_absolute_file {
    my ($label, $path, $executable) = @_;
    defined($path) && $path =~ m{\A/} && $path !~ m{\0|(?:\A|/)\.\.(?:/|\z)|//}
        or _fatal("$label is invalid");
    -f $path && !-l $path or _fatal("$label is unavailable: $path");
    $executable ? -x $path : -r $path
        or _fatal("$label is not accessible: $path");
    return $path;
}

sub _configuration_owner_is_trusted {
    my ($owner_uid) = @_;
    return defined($owner_uid) && ($owner_uid == 0 || $owner_uid == $<);
}

sub _build_values {
    my ($self) = @_;
    my $path = $self->path();
    _safe_absolute_file('Whisper configuration', $path, 0);
    my @stat = lstat $path;
    ($stat[2] & 0022) == 0
        or _fatal('Whisper configuration must not be writable by group or other users');
    _configuration_owner_is_trusted($stat[4])
        or _fatal('Whisper configuration must be owned by root or the active user');
    -s $path <= 16 * 1024 or _fatal('Whisper configuration is too large');

    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or _fatal("cannot read Whisper configuration: $!");
    my @opened = stat $fh;
    -f $fh && $opened[0] == $stat[0] && $opened[1] == $stat[1]
        && _configuration_owner_is_trusted($opened[4]) && ($opened[2] & 0022) == 0
        or _fatal('Whisper configuration changed identity or is unsafe');
    my $raw = q{};
    while (1) {
        my $n = sysread($fh, my $chunk, 16385 - length($raw));
        if (!defined $n) { next if $! == EINTR; _fatal("cannot read Whisper configuration: $!"); }
        last if !$n;
        $raw .= $chunk;
        length($raw) <= 16384 or _fatal('Whisper configuration is too large');
    }
    my %values;
    for my $line (split /\n/, $raw) {
        $line =~ s/\r\z//;
        next if $line eq q{} || $line =~ /\A#/;
        $line =~ /\A([A-Z_]+)=([^\r\n]*)\z/
            or _fatal('Whisper configuration contains an invalid line');
        exists $values{$1} and _fatal("Whisper configuration contains duplicate $1");
        $values{$1} = $2;
    }
    close $fh or _fatal("cannot close Whisper configuration: $!");

    for my $key (qw(WHISPER_CLI WHISPER_SERVER WHISPER_SERVER_PORT WHISPER_MODEL WHISPER_RUNTIME_THREADS WHISPER_PERSISTENT_MEM)) {
        defined $values{$key} && length $values{$key}
            or _fatal("Whisper configuration is missing $key");
    }
    _safe_absolute_file('WHISPER_CLI', $values{WHISPER_CLI}, 1);
    _safe_absolute_file('WHISPER_SERVER', $values{WHISPER_SERVER}, 1);
    $values{WHISPER_SERVER_PORT} =~ /\A[1-9][0-9]*\z/
        && $values{WHISPER_SERVER_PORT} >= 1024
        && $values{WHISPER_SERVER_PORT} <= 65535
        or _fatal('WHISPER_SERVER_PORT must be an integer from 1024 through 65535');
    _safe_absolute_file('WHISPER_MODEL', $values{WHISPER_MODEL}, 0);
    $values{WHISPER_RUNTIME_THREADS} =~ /\A(?:auto|[1-9][0-9]*)\z/
        or _fatal('WHISPER_RUNTIME_THREADS must be auto or a positive integer');
    $values{WHISPER_PERSISTENT_MEM} =~ /\A[01]\z/
        or _fatal('WHISPER_PERSISTENT_MEM must be 0 or 1');
    return \%values;
}

sub value {
    my ($self, $key) = @_;
    return $self->values()->{$key};
}

sub persistent_memory_enabled {
    my ($self) = @_;
    return $self->value('WHISPER_PERSISTENT_MEM') eq '1';
}

sub thread_count {
    my ($self) = @_;
    my $configured = $self->value('WHISPER_RUNTIME_THREADS');
    return $configured if $configured ne 'auto';
    my $count = eval { sysconf(POSIX::_SC_NPROCESSORS_ONLN()) };
    return $count if defined $count && $count =~ /\A[1-9][0-9]*\z/;
    return 1;
}

1;
