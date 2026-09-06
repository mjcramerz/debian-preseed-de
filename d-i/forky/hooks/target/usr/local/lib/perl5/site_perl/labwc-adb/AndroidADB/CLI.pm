package AndroidADB::CLI;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Str);

use AndroidADB::Config;
use AndroidADB::Logger qw(log_event);
use AndroidADB::Runtime;
use AndroidADB::Validation qw(fail require_value validate_action);

has self_path => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/bin/labwc-adb-action' },
);

sub run {
    my ($self, @argv) = @_;
    if (@argv == 1 && ($argv[0] eq '--help' || $argv[0] eq '-h')) {
        print $self->usage;
        return 0;
    }

    my ($invocation_mode, $requested_action) = _invocation_context(@argv);
    log_event(
        'info',
        'invoked',
        action => $requested_action,
        mode   => $invocation_mode,
    );

    my ($runtime, $status);
    my $action_name = $requested_action;
    my $ok = eval {
        my $config = AndroidADB::Config->from_environment;
        $runtime = AndroidADB::Runtime->new(config => $config);
        local $SIG{HUP}  = sub { $runtime->cleanup; exit 129 };
        local $SIG{INT}  = sub { $runtime->cleanup; exit 130 };
        local $SIG{TERM} = sub { $runtime->cleanup; exit 143 };

        if (@argv && $argv[0] eq '--menu-devices') {
            require_value(@argv == 1, '--menu-devices does not accept arguments');
            $status = $runtime->menu_devices;
        }
        elsif (@argv && $argv[0] eq '--menu-fastboot-devices') {
            require_value(
                @argv == 1,
                '--menu-fastboot-devices does not accept arguments',
            );
            $runtime->config->require_tool('fastboot', 'fastboot is not installed');
            $status = $runtime->menu_fastboot_devices;
        }
        elsif (@argv && $argv[0] eq '--service') {
            shift @argv;
            require_value(
                @argv == 1 && $argv[0] =~ /\A(?:run|ready|cleanup)\z/,
                '--service requires exactly one action: run, ready or cleanup',
            );
            $action_name = "service-$argv[0]";
            $status = $runtime->run_service_action($argv[0]);
        }
        elsif (@argv && $argv[0] eq '--run') {
            shift @argv;
            require_value(
                @argv > 0,
                'missing Android Debug Bridge action after --run',
            );
            $action_name = shift @argv;
            validate_action($action_name, @argv);
            $runtime->ensure_action_tools($action_name);
            $status = $self->_run_in_terminal($runtime, $action_name, @argv);
        }
        else {
            require_value(@argv > 0, 'usage: labwc-adb-action <action> [argument]');
            $action_name = shift @argv;
            validate_action($action_name, @argv);
            $runtime->ensure_action_tools($action_name);
            my $terminal = $runtime->config->require_tool(
                'terminal',
                'required Android Debug Bridge command is not installed: labwc-terminal',
            );
            log_event(
                'info',
                'terminal-dispatched',
                action => $action_name,
                mode   => $invocation_mode,
            );
            exec { $terminal } $terminal, '-e', $self->self_path, '--run', $action_name, @argv
                or fail("unable to start managed terminal: $!");
        }
        1;
    };

    if ($ok) {
        $runtime->cleanup if defined($runtime);
        my $final_status = $status // 0;
        log_event(
            $final_status == 0 ? 'info' : 'warning',
            'completed',
            action => $action_name,
            mode   => $invocation_mode,
            status => $final_status,
        );
        return $final_status;
    }

    my $message = _exception_message($@);
    log_event(
        'error',
        'failed',
        action => $action_name,
        detail => $message,
        mode   => $invocation_mode,
        status => 1,
    );
    print STDERR "fatal: $message\n";
    if (defined($runtime)) {
        eval { $runtime->notification->notify_result(1, $action_name // 'requested-action'); 1 };
        $runtime->cleanup;
    }
    return 1;
}

sub usage {
    return <<'USAGE';
usage: labwc-adb-action <action> [arguments]
       labwc-adb-action --menu-devices
       labwc-adb-action --menu-fastboot-devices
       labwc-adb-action --service <run|ready|cleanup>

The public command opens a managed terminal for actions.  --run is reserved
for that terminal and --service is reserved for labwc-adb-server.service.
USAGE
}

sub _run_in_terminal {
    my ($self, $runtime, $action, @arguments) = @_;
    print "\n=== Android Debug Bridge: $action ===\n\n";
    my $status;
    my $ok = eval {
        $status = $runtime->run_action($action, @arguments);
        1;
    };
    if (!$ok) {
        my $message = _exception_message($@);
        log_event(
            'error',
            'action-failed',
            action => $action,
            detail => $message,
            mode   => 'terminal',
            status => 1,
        );
        print STDERR "fatal: $message\n";
        $status = 1;
    }
    $status //= 0;

    print "\n=== Action finished with status $status ===\n";
    $runtime->notification->notify_result($status, $action);
    if (-t STDIN) {
        print 'Press Enter to close this terminal...';
        scalar <STDIN>;
    }
    $runtime->cleanup;
    return $status;
}

sub _invocation_context {
    my (@argv) = @_;
    return ('menu', 'menu-devices')
        if @argv && $argv[0] eq '--menu-devices';
    return ('menu', 'menu-fastboot-devices')
        if @argv && $argv[0] eq '--menu-fastboot-devices';
    return ('service', 'service-' . ($argv[1] // 'unset'))
        if @argv && $argv[0] eq '--service';
    return ('terminal', $argv[1] // 'unset')
        if @argv && $argv[0] eq '--run';
    return ('launcher', $argv[0] // 'unset');
}

sub _exception_message {
    my ($error) = @_;
    $error //= 'unknown Android Debug Bridge error';
    $error =~ s/\s+\z//;
    return $error eq q{} ? 'unknown Android Debug Bridge error' : $error;
}

1;
