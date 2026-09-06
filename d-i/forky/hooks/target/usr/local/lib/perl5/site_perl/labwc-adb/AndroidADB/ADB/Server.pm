package AndroidADB::ADB::Server;

use strict;
use warnings;
use Fcntl qw(O_RDONLY O_NOFOLLOW O_NONBLOCK);
use File::Basename qw(dirname basename);
use File::Temp qw(tempfile);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC sleep);
use Types::Standard qw(Object);
use AndroidADB::Validation qw(fail require_value);

use constant SERVER_UNIT => 'labwc-adb-server.service';
has config => (is => 'ro', isa => Object, required => 1);
has command => (is => 'ro', isa => Object, required => 1);

sub _property {
    my ($self, $property) = @_;
    $property =~ /\A(?:MainPID|InvocationID|ActiveState)\z/ or fail('invalid unit property');
    my $result = $self->command->capture(3, $self->config->require_tool('systemctl'),
        '--user', 'show', "--property=$property", '--value', SERVER_UNIT);
    $result->{status} == 0 or fail('cannot query the managed ADB unit');
    my $value = $result->{stdout};
    $value =~ s/\s+\z//;
    return $value;
}

sub port_in_use {
    my ($self) = @_;
    my $result = $self->command->capture(3, $self->config->require_tool('ss'),
        '-H', '-ltn', 'sport = :' . $self->config->adb_server_port);
    $result->{status} == 0 or fail('cannot inspect the ADB listen port');
    return $result->{stdout} =~ /\S/ ? 1 : 0;
}

sub _read_marker {
    my ($self) = @_;
    my $path = $self->config->server_marker;
    return if !-e $path && !-l $path;
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK or fail("cannot read ADB ownership marker: $!");
    my @st = stat $fh;
    -f $fh && $st[4] == $< && $st[3] == 1 && ($st[2] & 0077) == 0 && $st[7] <= 128
        or fail('unsafe ADB ownership marker');
    my $n = sysread($fh, my $text, 129);
    defined($n) or fail("cannot read ADB ownership marker: $!");
    close $fh or fail("cannot close ADB ownership marker: $!");
    # Empty legacy markers do not establish ownership of any live process.
    return if $text !~ /\A([0-9a-f]{32}) ([1-9][0-9]*)\n\z/;
    return ($1, $2);
}

sub is_managed {
    my ($self) = @_;
    my ($invocation, $pid) = $self->_read_marker;
    return 0 if !defined $invocation;
    return 0 if $self->_property('InvocationID') ne $invocation;
    return 0 if $self->_property('MainPID') ne $pid;
    return $self->_property('ActiveState') =~ /\A(?:active|activating|reloading)\z/ ? 1 : 0;
}

sub _invocation {
    my ($self) = @_;
    my $id = $ENV{INVOCATION_ID} // q{};
    $id =~ /\A[0-9a-f]{32}\z/ && $self->_property('InvocationID') eq $id
        or fail('--service operations must be executed by labwc-adb-server.service');
    return $id;
}

sub mark_managed {
    my ($self) = @_;
    my $id = $self->_invocation;
    $self->_property('MainPID') eq "$$" or fail('only the managed main process may claim ADB ownership');
    my $path = $self->config->server_marker;
    my ($fh, $temporary) = tempfile('.' . basename($path) . '.XXXXXX', DIR => dirname($path), UNLINK => 1);
    my $ok = eval {
        print {$fh} "$id $$\n" or fail("cannot write ADB ownership marker: $!");
        close $fh or fail("cannot close ADB ownership marker: $!");
        rename $temporary, $path or fail("cannot publish ADB ownership marker: $!");
        1;
    };
    my $error = $@;
    unlink $temporary if -e $temporary;
    die $error if !$ok;
    return;
}

sub clear_marker {
    my ($self) = @_;
    my $id = $self->_invocation;
    my ($marked) = $self->_read_marker;
    return 0 if !defined($marked) || $marked ne $id;
    unlink $self->config->server_marker or fail("cannot remove ADB ownership marker: $!");
    return 0;
}

sub probe {
    my ($self) = @_;
    # An explicit numeric server host uses the ADB remote-client path, avoiding
    # the local implicit start-server path during a failed readiness probe.
    # Never issue kill-server here; only the owning systemd cgroup is stopped.
    return $self->command->run_quiet_signal('TERM', 1, 2,
        $self->config->require_tool('adb'), '-H', '127.0.0.1',
        '-P', $self->config->adb_server_port, 'server-status') == 0 ? 1 : 0;
}

sub run_foreground {
    my ($self) = @_;
    $self->_invocation;
    $self->_property('MainPID') eq "$$" or fail('foreground ADB must be the unit main process');
    $self->port_in_use and fail('ADB port is already occupied; refusing to take over another server');
    $self->mark_managed;
    my $adb = $self->config->require_tool('adb');
    # systemd supervises the actual server, not a successful daemon-launch
    # command. A crash is observable and all descendants die with the unit.
    exec { $adb } $adb, '-L', 'tcp:localhost:' . $self->config->adb_server_port, 'server', 'nodaemon'
        or fail("cannot exec foreground ADB server: $!");
}

sub wait_ready {
    my ($self) = @_;
    my $invocation = $self->_invocation;
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + 20;
    while (clock_gettime(CLOCK_MONOTONIC) < $deadline) {
        # Type=exec starts ExecStartPost after exec(), not after Perl has
        # written the ownership marker. An absent marker is initially normal.
        $self->_property('InvocationID') eq $invocation
            or fail('managed ADB invocation changed during startup');
        my $pid = $self->_property('MainPID');
        $pid =~ /\A[1-9][0-9]*\z/
            or fail('managed ADB main process disappeared during startup');
        my ($marked, $marked_pid) = $self->_read_marker;
        return 0 if defined($marked) && $marked eq $invocation
            && $marked_pid eq $pid && $self->probe;
        sleep 0.2;
    }
    fail('managed ADB server did not pass its readiness probe within 20 seconds');
}

sub _service_is_active {
    my ($self) = @_;
    return $self->_property('ActiveState') eq 'active';
}
sub _service_is_failed {
    my ($self) = @_;
    return $self->_property('ActiveState') eq 'failed';
}
sub _run_service_command {
    my ($self, $operation) = @_;
    $operation =~ /\A(?:start|restart|stop)\z/ or fail('invalid ADB unit operation');
    my $systemctl = $self->config->require_tool('systemctl');
    if ($operation ne 'stop' && $self->_service_is_failed) {
        my $status = $self->command->run(5, $systemctl, '--user', 'reset-failed', SERVER_UNIT);
        return $status if $status;
    }
    return $self->command->run(65, $systemctl, '--user', $operation, SERVER_UNIT);
}
sub start_via_service {
    my ($self) = @_;
    my $status = $self->_run_service_command('start'); # Idempotent, never implicit restart.
    return $status if $status;
    return $self->show_status;
}
sub repair_via_service {
    my ($self) = @_;
    my $status = $self->_run_service_command('restart');
    return $status if $status;
    return $self->show_status;
}
sub stop_via_service {
    my ($self) = @_;
    my $status = $self->_run_service_command('stop');
    return $status if $status;
    print "Managed ADB service stopped. Unrelated listeners were not touched.\n";
    return 0;
}
# Keep internal callers on the same lifecycle boundary as launcher callers.
sub start { return $_[0]->start_via_service; }
sub stop { return $_[0]->stop_via_service; }
sub repair { return $_[0]->repair_via_service; }
sub ensure_responsive {
    my ($self) = @_;
    $self->is_managed or fail('managed ADB is stopped; start it from the Android Debug Bridge launcher');
    $self->probe or fail('managed ADB is unresponsive; choose Repair / Restart ADB Server');
    return 1;
}
sub show_status {
    my ($self) = @_;
    if (!$self->is_managed) {
        print "Managed ADB service is not running; no unrelated process will be adopted.\n";
        return 3;
    }
    if ($self->probe) {
        print "Managed ADB server is running and responsive.\n";
        return 0;
    }
    print "Managed ADB is unresponsive; choose Repair / Restart ADB Server.\n";
    return 1;
}
1;
