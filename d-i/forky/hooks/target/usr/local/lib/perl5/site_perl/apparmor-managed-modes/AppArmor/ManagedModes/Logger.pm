package AppArmor::ManagedModes::Logger;

use strict;
use warnings;

use Exporter qw(import);

our @EXPORT_OK = qw(log_msg);


sub log_msg {
    my ($level, $message) = @_;
    $level = 'error' if $level !~ /\A(?:info|warning|error)\z/;
    $message = q{} if !defined $message;
    $message =~ s/[\r\n]+/ /g;
    $message =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    $message = substr($message, 0, 2048);
    # One stream only. systemd supplies the identifier and journal transport;
    # direct invocations retain the same useful, sanitized terminal messages.
    if ($level eq 'info') {
        print STDOUT "apparmor-managed-modes: $message\n";
    }
    elsif ($level eq 'warning') {
        print STDERR "apparmor-managed-modes: warning: $message\n";
    }
    else {
        print STDERR "fatal: $message\n";
    }

}

1;
