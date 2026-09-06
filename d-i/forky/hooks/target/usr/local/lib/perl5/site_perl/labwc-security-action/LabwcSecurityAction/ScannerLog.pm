package LabwcSecurityAction::ScannerLog;

use strict;
use warnings;

use Errno qw(EINTR);
use IO::Select;
use IPC::Open3 qw(open3);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Symbol qw(gensym);
use Sys::Syslog qw(:standard :macros setlogsock);
use Types::Standard qw(Int Str);

has maximum_line_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 1800 },
);

has socket_path => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/run/rsyslog/managed-security-scanners/scanner.sock' },
);

sub _validate_socket_path {
    my ($self) = @_;

    $self->socket_path()
        =~ m{\A/run/rsyslog/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+[.]sock\z}
        or die "managed scanner log socket path is invalid\n";
    return;
}

sub _status {
    my ($status) = @_;

    return 255 if !defined($status) || $status == -1;
    return 128 + ($status & 127) if $status & 127;
    return $status >> 8;
}

sub _validate_run {
    my ($self, %args) = @_;

    my $argv = $args{argv};
    ref($argv) eq 'ARRAY' && @{$argv}
        or die "scanner logging requires a non-empty argv array\n";
    defined($argv->[0]) && $argv->[0] =~ m{\A/}
        or die "scanner logging requires an absolute executable path\n";
    my $tag = $args{tag};
    defined($tag) && $tag =~ /\Amanaged-[a-z0-9]+(?:-[a-z0-9]+)*\z/
        or die "invalid managed scanner log tag\n";
    my $label = $args{label};
    defined($label) && $label =~ /\A[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?\z/
        or die "invalid managed scanner label\n";
    $self->_validate_socket_path();
    return ($argv, $tag, $label);
}

sub _sanitize_line {
    my ($self, $line) = @_;

    $line = q{} if !defined $line;
    $line =~ s/[\r\n]+\z//;
    $line =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    return $line;
}

sub _write_syslog_line {
    my ($self, $stream, $line) = @_;

    $line = $self->_sanitize_line($line);
    $line = '(empty line)' if $line eq q{};
    my $prefix = "stream=$stream message=";
    my $continuation = ' continued=true';
    my $available = $self->maximum_line_bytes() - length($prefix);
    my $chunk_bytes = $available - length($continuation);
    $chunk_bytes > 0 or die "managed scanner log line limit is too small\n";
    while (length($line) > $available) {
        my $chunk = substr($line, 0, $chunk_bytes, q{});
        syslog(LOG_INFO, '%s', "${prefix}${chunk}${continuation}");
    }
    syslog(LOG_INFO, '%s', "${prefix}${line}");
    return;
}

sub _flush_complete_lines {
    my ($self, $stream, $buffer_ref, $flush_all) = @_;

    while ($$buffer_ref =~ s/\A([^\n]*)\n//) {
        $self->_write_syslog_line($stream, $1);
    }
    if ($flush_all && $$buffer_ref ne q{}) {
        $self->_write_syslog_line($stream, $$buffer_ref);
        $$buffer_ref = q{};
    }
    while (length($$buffer_ref) > $self->maximum_line_bytes()) {
        my $chunk = substr($$buffer_ref, 0, $self->maximum_line_bytes(), q{});
        $self->_write_syslog_line($stream, $chunk);
    }
    return;
}

sub _wait_child {
    my ($pid) = @_;

    while (1) {
        my $waited = waitpid($pid, 0);
        return if $waited == $pid;
        next if $waited == -1 && $! == EINTR;
        die "cannot wait for managed scanner child $pid: $!\n";
    }
}

sub _restore_default_log_socket {
    my $error = q{};

    eval {
        closelog();
        1;
    } or $error = $@ || "cannot close the managed scanner logger\n";
    eval {
        setlogsock(['native', 'unix'])
            or die "cannot restore the default system log socket\n";
        1;
    } or $error ||= $@ || "cannot restore the default system log socket\n";
    return $error;
}

sub run {
    my ($self, %args) = @_;

    my ($argv, $tag, $label) = $self->_validate_run(%args);
    my ($pid, $stdin, $stdout);
    my $stderr = gensym();
    my $status;
    my $error = q{};

    eval {
        -S $self->socket_path()
            or die "managed scanner log socket is unavailable: " . $self->socket_path() . "\n";
        setlogsock({
            type    => 'unix',
            path    => $self->socket_path(),
            timeout => 2,
        }) or die "cannot select the managed scanner log socket\n";
        openlog($tag, 'pid,ndelay,nowait', LOG_USER);
        syslog(LOG_INFO, '%s', "scanner=$label event=started");

        $pid = open3($stdin, $stdout, $stderr, @{$argv});
        close $stdin or die "cannot close scanner input for $argv->[0]: $!\n";
        undef $stdin;

        my $selector = IO::Select->new($stdout, $stderr);
        my %stream_for = (
            fileno($stdout) => 'stdout',
            fileno($stderr) => 'stderr',
        );
        my %buffer_for = (
            stdout => q{},
            stderr => q{},
        );
        local $SIG{PIPE} = 'IGNORE';

        while ($selector->count()) {
            for my $handle ($selector->can_read()) {
                my $stream = $stream_for{fileno($handle)};
                my $chunk = q{};
                my $bytes = sysread($handle, $chunk, 8192);
                if (!defined $bytes) {
                    next if $! == EINTR;
                    die "cannot read scanner $stream output: $!\n";
                }
                if ($bytes == 0) {
                    $selector->remove($handle);
                    close $handle
                        or die "cannot close scanner $stream output: $!\n";
                    $stdout = undef if $stream eq 'stdout';
                    $stderr = undef if $stream eq 'stderr';
                    $self->_flush_complete_lines(
                        $stream,
                        \$buffer_for{$stream},
                        1,
                    );
                    next;
                }
                if ($stream eq 'stderr') {
                    print STDERR $chunk
                        or die "cannot mirror scanner stderr: $!\n";
                }
                else {
                    print STDOUT $chunk
                        or die "cannot mirror scanner stdout: $!\n";
                }
                $buffer_for{$stream} .= $chunk;
                $self->_flush_complete_lines(
                    $stream,
                    \$buffer_for{$stream},
                    0,
                );
            }
        }

        _wait_child($pid);
        $pid = undef;
        $status = _status($?);
        syslog(
            $status == 0 ? LOG_INFO : LOG_WARNING,
            '%s',
            "scanner=$label event=completed status=$status",
        );
        1;
    } or $error = $@ || "managed scanner execution failed\n";

    if (defined $pid) {
        kill 'TERM', $pid;
        eval { _wait_child($pid); 1 };
    }
    if ($error ne q{}) {
        my $log_error = $self->_sanitize_line($error);
        $log_error =~ s/\s+\z//;
        eval {
            syslog(
                LOG_ERR,
                '%s',
                "scanner=$label event=failed error=$log_error",
            );
            1;
        };
    }
    for my $handle ($stdin, $stdout, $stderr) {
        next if !defined $handle;
        close $handle;
    }
    my $cleanup_error = _restore_default_log_socket();

    if ($error ne q{}) {
        $error =~ s/\s+\z//;
        die "$error\n";
    }
    if ($cleanup_error ne q{}) {
        $cleanup_error =~ s/\s+\z//;
        die "$cleanup_error\n";
    }
    return $status;
}

1;
