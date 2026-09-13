package Labwc::WorkspaceBroker::Picker;
use strict;
use warnings;
use POSIX qw(WNOHANG _exit setpgid);
use IO::Select ();
use Errno qw(EAGAIN EWOULDBLOCK EINTR);
use Labwc::WorkspaceBroker::Runtime qw(now nonblock cloexec);
use Labwc::WorkspaceBroker::Render qw(clean);

# Only this short-lived UI helper launches a chooser. The long-lived broker
# retains the immutable snapshot and decides whether a selection is still valid.
sub choose {
    my ($page, $remaining) = @_;
    return undef if $remaining <= 0;
    my @rows = map { clean($_->{label}, 512) } @{$page->{rows}};
    my @choices = map { { index => $_->{index} } } @{$page->{rows}};
    if ($page->{offset} > 0) {
        push @rows, 'Previous page';
        push @choices, { offset => $page->{offset} - 128 };
    }
    if ($page->{offset} + @{$page->{rows}} < $page->{count}) {
        push @rows, 'Next page';
        push @choices, { offset => $page->{offset} + 128 };
    }
    my $lines = $page->{lines};
    $lines = @rows if @rows < $lines;
    $lines = 2 if $lines < 2;
    # Untrusted response values are validated again before becoming arguments.
    my ($safe_lines) = "$lines" =~ /\A([0-9]{1,2})\z/;
    my ($safe_width) = "$page->{width}" =~ /\A([0-9]{2,3})\z/;
    my ($safe_count) = "$page->{count}" =~ /\A([0-9]{1,4})\z/;
    die "invalid picker geometry\n" unless defined($safe_lines) && $safe_lines >= 2 && $safe_lines <= 32
        && defined($safe_width) && $safe_width >= 24 && $safe_width <= 120
        && defined($safe_count) && $safe_count >= 1 && $safe_count <= 1024;
    my $prompt = ($page->{mode} eq 'close' ? 'Close one window' : 'Choose window') . " ($safe_count)> ";
    pipe(my $input_read, my $input_write) or die "picker input pipe: $!\n";
    pipe(my $output_read, my $output_write) or die "picker output pipe: $!\n";
    cloexec($_) for ($input_read, $input_write, $output_read, $output_write);
    my $pid = fork();
    die "fork picker: $!\n" unless defined $pid;
    if (!$pid) {
        close $input_write; close $output_read;
        setpgid(0, 0) == 0 or _exit(126);
        open(STDIN, '<&', $input_read) or _exit(126);
        open(STDOUT, '>&', $output_write) or _exit(126);
        close $input_read; close $output_write;
        $SIG{TERM} = $SIG{INT} = $SIG{PIPE} = 'DEFAULT';
        $ENV{LABWC_FUZZEL_MANAGED_ICONS} = '0';
        $ENV{LABWC_FUZZEL_ROOT_MENU} = '0';
        delete @ENV{grep { /\AMENU_.*_OVERRIDE\z/ } keys %ENV};
        exec { '/usr/local/bin/labwc-fuzzel' } '/usr/local/bin/labwc-fuzzel', 'menu',
            '--dmenu', '--index', '--prompt', $prompt, '--lines', $safe_lines, '--width', $safe_width
            or _exit(127);
    }
    close $input_read; close $output_write;
    nonblock($input_write); nonblock($output_read);
    my $input = Encode::encode('UTF-8', join("\n", @rows) . "\n");
    my $output = '';
    my ($status, $cancel, $error);
    my $deadline = now() + $remaining;
    local $SIG{TERM} = sub { $cancel = 1 };
    local $SIG{INT} = sub { $cancel = 1 };
    local $SIG{PIPE} = 'IGNORE';
    eval {
        while (!$cancel && now() < $deadline) {
            # Preserve the wrapper PID until its entire stdout pipe reaches
            # EOF. A crashed wrapper can otherwise leave its GUI child alive.
            if (!$output_read) {
                my $r = waitpid($pid, WNOHANG);
                if ($r == $pid) { $status = $?; last; }
                die "lost picker child\n" if $r == -1;
            }
            my $reads = IO::Select->new();
            $reads->add($output_read) if $output_read;
            my $writes = IO::Select->new();
            $writes->add($input_write) if $input_write;
            my ($ready_read, $ready_write) = IO::Select->select($reads, $writes, undef, 0.1);
            for my $fh (@{$ready_write // []}) {
                my $n = syswrite($fh, $input);
                next if !defined($n) && ($! == EAGAIN || $! == EWOULDBLOCK || $! == EINTR);
                die "picker input closed\n" unless defined($n) && $n;
                substr($input, 0, $n, '');
                if (!length($input)) { close $input_write; undef $input_write; }
            }
            for my $fh (@{$ready_read // []}) {
                my $n = sysread($fh, my $part, 64);
                next if !defined($n) && ($! == EAGAIN || $! == EWOULDBLOCK || $! == EINTR);
                die "picker output failure\n" unless defined $n;
                $output .= $part;
                die "picker output limit\n" if length($output) > 16;
                if (!$n) { close $output_read; undef $output_read; }
            }
        }
        1;
    } or $error = $@;
    $cancel = 1 unless defined $status; # Deadline expiry never becomes a selection.
    close $input_write if $input_write;
    close $output_read if $output_read;
    if (!defined $status) {
        # The process group consists only of our unreaped wrapper and its GUI
        # descendants. Never read a PID file or signal application processes.
        kill 'TERM', -$pid;
        kill 'TERM', $pid; # Covers the tiny pre-setpgid startup interval.
        # Do not reap early: an unreaped wrapper reserves this process-group
        # number while we terminate all of its descendants, even if it exits
        # before a stubborn GUI child. This cannot target a recycled PID.
        my $until = now() + 1;
        while (now() < $until) { select undef, undef, undef, 0.02; }
        kill 'KILL', -$pid;
        kill 'KILL', $pid;
        my $r;
        do { $r = waitpid($pid, 0); } while $r == -1 && $! == EINTR;
        $status = $r == $pid ? $? : 1;
    }
    # Escape, timeout, a disappearing session, or malformed output is a benign
    # cancellation. None of these paths sends a selection to the broker.
    return undef if $cancel || $error || !defined($status) || $status != 0;
    return undef unless $output =~ /\A([0-9]{1,3})\n?\z/;
    my $index = 0 + $1;
    return undef if $index >= @choices;
    return $choices[$index];
}
use Encode ();
1;
