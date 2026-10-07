package AppArmor::ManagedModes::Tool;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use AppArmor::ManagedModes::CLI qw(fatal);
use Fcntl qw(O_NOFOLLOW O_TRUNC O_WRONLY);
use POSIX qw(_exit);

has force_arguments => (
    is      => 'ro',
    default => sub { {} },
);

sub require_executable {
    my ($self, $label, $path) = @_;
    -x $path || fatal("$label is missing: $path");
    return $path;
}

sub force_argument {
    my ($self, $tool_name, $tool_path) = @_;

    if (exists $self->force_arguments()->{$tool_name}) {
        return $self->force_arguments()->{$tool_name};
    }
    if ($tool_name ne 'aa-enforce' && $tool_name ne 'aa-complain') {
        fatal("unsupported AppArmor mode tool: $tool_name");
    }

    my $supports_force = $self->_output_contains(
        '--force',
        $tool_path,
        '--help',
    );
    $self->force_arguments()->{$tool_name} = $supports_force ? '--force' : '';
    return $self->force_arguments()->{$tool_name};
}

sub run_or_exit {
    my ($self, @command) = @_;
    my $status = system { $command[0] } @command;
    _exit_for_status($status) if $status != 0;
}

sub run_with_stderr_file_limited {
    my ($self, $stderr_path, $max_bytes, $overflow_message, @command) = @_;

    return _run_to_file_limited(
        'stderr',
        $stderr_path,
        $max_bytes,
        $overflow_message,
        @command,
    );
}

sub run_stdout_to_file_limited_or_exit {
    my ($self, $stdout_path, $max_bytes, $overflow_message, @command) = @_;

    my $status = _run_to_file_limited(
        'stdout',
        $stdout_path,
        $max_bytes,
        $overflow_message,
        @command,
    );
    _exit_for_status($status) if $status != 0;
}

sub _output_contains {
    my ($self, $needle, @command) = @_;
    my ($reader, $writer);
    pipe($reader, $writer) ||
        fatal('cannot create AppArmor tool help pipe');
    my $pid = fork();
    defined($pid) || fatal('cannot fork AppArmor tool help probe');

    if ($pid == 0) {
        close $reader;
        open STDOUT, '>&', $writer || _exit(127);
        open STDERR, '>&', \*STDOUT || _exit(127);
        exec { $command[0] } @command or _exit(127);
    }

    close $writer;
    my $found = 0;
    my $tail = '';
    while (1) {
        my $buffer = '';
        my $read = sysread($reader, $buffer, 65_536);
        defined($read) || fatal('cannot read AppArmor tool help output');
        last if $read == 0;
        my $candidate = $tail . $buffer;
        $found = 1 if index($candidate, $needle) >= 0;
        my $tail_length = length($needle) - 1;
        $tail = $tail_length > 0 && length($candidate) > $tail_length
            ? substr($candidate, -$tail_length)
            : $candidate;
    }
    close $reader || fatal('cannot close AppArmor tool help pipe');
    waitpid($pid, 0);
    return $found;
}

sub _run_to_file_limited {
    my ($stream, $output_path, $max_bytes, $overflow_message, @command) = @_;

    $max_bytes >= 0 ||
        fatal('invalid AppArmor tool output limit');
    my $redirect_label = $stream eq 'stderr' ? 'stderr' : 'output';
    sysopen my $output_fh, $output_path, O_WRONLY | O_TRUNC | O_NOFOLLOW ||
        fatal("cannot redirect AppArmor tool $redirect_label: $output_path");
    binmode $output_fh, ':raw' ||
        fatal("cannot redirect AppArmor tool $redirect_label: $output_path");

    my ($reader, $writer);
    pipe($reader, $writer) ||
        fatal('cannot create AppArmor tool output pipe');
    my $pid = fork();
    defined($pid) || fatal('cannot fork AppArmor tool');

    if ($pid == 0) {
        close $reader;
        if ($stream eq 'stdout') {
            open STDOUT, '>&', $writer || _exit(127);
        }
        else {
            open STDERR, '>&', $writer || _exit(127);
        }
        close $writer || _exit(127);
        exec { $command[0] } @command or _exit(127);
    }

    close $writer;
    my $captured_bytes = 0;
    while (1) {
        my $buffer = '';
        my $read = sysread($reader, $buffer, 65_536);
        if (!defined($read)) {
            close $reader;
            close $output_fh;
            _terminate_and_reap($pid);
            fatal('cannot read AppArmor tool output');
        }
        last if $read == 0;
        if ($captured_bytes + $read > $max_bytes) {
            close $reader;
            close $output_fh;
            _terminate_and_reap($pid);
            fatal($overflow_message);
        }
        _write_all($output_fh, $buffer);
        $captured_bytes += $read;
    }
    close $reader || fatal('cannot close AppArmor tool output pipe');
    close $output_fh ||
        fatal("cannot redirect AppArmor tool $redirect_label: $output_path");
    waitpid($pid, 0);
    return $?;
}

sub _write_all {
    my ($fh, $buffer) = @_;
    my $offset = 0;
    my $length = length($buffer);

    while ($offset < $length) {
        my $written = syswrite($fh, $buffer, $length - $offset, $offset);
        defined($written) && $written > 0 ||
            fatal('cannot write AppArmor tool output');
        $offset += $written;
    }
}

sub _terminate_and_reap {
    my ($pid) = @_;

    kill 'KILL', $pid;
    waitpid($pid, 0);
}

sub _exit_for_status {
    my ($status) = @_;

    exit 1 if !defined($status) || $status == -1;
    my $signal = $status & 127;
    exit(128 + $signal) if $signal;
    exit($status >> 8);
}

1;
