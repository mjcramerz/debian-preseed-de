package AppArmor::ManagedModes::CLI;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::Options protect_argv => 0, flavour => [qw(require_order no_auto_abbrev)];
use MooX::StrictConstructor;
use MooX::TypeTiny;
use AppArmor::ManagedModes::Logger qw(log_msg);

our @EXPORT_OK = qw(fatal info parse_args usage warn);

sub fatal {
    my ($message) = @_;
    log_msg('error', $message);
    print STDERR "fatal: $message\n";
    exit 1;
}

sub info {
    my ($message) = @_;
    log_msg('info', $message);
    print "apparmor-managed-modes: $message\n";
}

sub warn {
    my ($message) = @_;
    log_msg('warning', $message);
    print STDERR "apparmor-managed-modes: warning: $message\n";
}

sub usage {
    print <<'USAGE';
Usage: apparmor-managed-modes [--check] [--check-loaded] [--no-reload]
                               [--config PATH] [--profile-dir PATH]
                               [--tool-dir PATH] [--loaded-profiles PATH]
USAGE
}

sub parse_args {
    my @argv = @_;
    my $options = {
        config_path          => '/etc/apparmor/managed-modes.conf',
        profile_dir          => '/etc/apparmor.d',
        tool_dir             => '/usr/sbin',
        reload_profiles      => 1,
        check_only           => 0,
        check_loaded         => 0,
        loaded_profiles_path => '/sys/kernel/security/apparmor/profiles',
    };

    while (@argv) {
        my $argument = shift @argv;

        if ($argument eq '--check') {
            $options->{check_only} = 1;
        }
        elsif ($argument eq '--check-loaded') {
            $options->{check_only} = 1;
            $options->{check_loaded} = 1;
        }
        elsif ($argument eq '--no-reload') {
            $options->{reload_profiles} = 0;
        }
        elsif ($argument eq '--config') {
            @argv or fatal('--config requires a path');
            $options->{config_path} = shift @argv;
        }
        elsif ($argument eq '--profile-dir') {
            @argv or fatal('--profile-dir requires a path');
            $options->{profile_dir} = shift @argv;
        }
        elsif ($argument eq '--tool-dir') {
            @argv or fatal('--tool-dir requires a path');
            $options->{tool_dir} = shift @argv;
        }
        elsif ($argument eq '--loaded-profiles') {
            @argv or fatal('--loaded-profiles requires a path');
            $options->{loaded_profiles_path} = shift @argv;
        }
        elsif ($argument eq '-h' || $argument eq '--help') {
            usage();
            exit 0;
        }
        else {
            fatal("unsupported argument: $argument");
        }
    }

    return $options;
}

1;
