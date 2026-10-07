package CompzArchives::Pipeline;
use strict;
use warnings;
use Errno qw(EINTR);
use POSIX qw(:sys_wait_h _exit);
use Time::HiRes qw(sleep clock_gettime CLOCK_MONOTONIC);

# Core-only on purpose: this small IPC boundary does not load user Perl paths,
# dynamic plugins, a shell, or an object framework during fork/exec.
my %ALLOWED = map { $_ => 1 } qw(
    /usr/bin/python3 /usr/bin/gzip /usr/bin/bzip2 /usr/bin/bzip3
    /usr/bin/xz /usr/bin/zstd /usr/bin/lz4 /usr/bin/lzip /usr/bin/kanzi
);

sub new {
    my ($class, %args) = @_;
    die "invalid pipeline fields\n" if keys(%args) != 1 || !exists $args{commands};
    my $commands = $args{commands};
    die "invalid pipeline length\n" unless ref($commands) eq 'ARRAY' && @$commands && @$commands <= 8;
    for my $command (@$commands) {
        die "invalid pipeline command\n" unless ref($command) eq 'ARRAY' && @$command && @$command <= 64;
        for my $arg (@$command) {
            die "invalid pipeline argument\n" if ref($arg) || !defined($arg) || length($arg) > 8192 || index($arg, "\0") >= 0;
            ($arg) = $arg =~ /\A([^\0]*)\z/s;
        }
        die "unmanaged pipeline executable\n" unless $ALLOWED{$command->[0]};
    }
    return bless { commands => $commands }, $class;
}

sub run {
    my ($self) = @_;
    my @pipes;
    my %children;
    my $signal = 0;
    my $failed = 0;
    local $SIG{INT} = sub { $signal = 2 };
    local $SIG{TERM} = sub { $signal = 15 };
    local $SIG{HUP} = sub { $signal = 1 };
    my $commands = $self->{commands};
    my $ok = eval {
        for (1 .. $#$commands) {
            pipe(my $reader, my $writer) or die "pipe failed: $!\n";
            push @pipes, [$reader, $writer];
        }
        for my $index (0 .. $#$commands) {
            die "pipeline interrupted\n" if $signal;
            my $pid = fork();
            die "fork failed: $!\n" unless defined $pid;
            if (!$pid) {
                $SIG{$_} = 'DEFAULT' for qw(INT TERM HUP PIPE);
                if ($index) {
                    open(STDIN, '<&', $pipes[$index - 1][0]) or _exit(126);
                } else {
                    open(STDIN, '<', '/dev/null') or _exit(126);
                }
                if ($index < $#$commands) {
                    open(STDOUT, '>&', $pipes[$index][1]) or _exit(126);
                }
                for my $ends (@pipes) { close($_) for @$ends; }
                my $command = $commands->[$index];
                exec { $command->[0] } @$command or _exit(127);
            }
            $children{$pid} = 1;
        }
        1;
    };
    my $error = $@;
    for my $ends (@pipes) { close($_) for @$ends; }
    $failed = 1 unless $ok;
    my $deadline;
    while (%children) {
        for my $pid (keys %children) {
            my $result = waitpid($pid, WNOHANG);
            if ($result == $pid) {
                $failed = 1 if $? != 0;
                delete $children{$pid};
            } elsif ($result == -1 && $! != EINTR) {
                $failed = 1;
                delete $children{$pid};
            }
        }
        if (($failed || $signal) && %children) {
            if (!defined $deadline) {
                kill 'TERM', keys %children;
                $deadline = clock_gettime(CLOCK_MONOTONIC) + 2;
            } elsif (clock_gettime(CLOCK_MONOTONIC) >= $deadline) {
                kill 'KILL', keys %children;
            }
        }
        sleep(0.02) if %children;
    }
    die $error if !$ok;
    return $signal ? 128 + $signal : $failed ? 1 : 0;
}

1;
