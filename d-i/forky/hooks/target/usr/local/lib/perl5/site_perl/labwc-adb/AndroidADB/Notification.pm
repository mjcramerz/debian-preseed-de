package AndroidADB::Notification;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

has config => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

has command => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);

sub notify_result {
    my ($self, $status, $action_name) = @_;
    return if !defined($ENV{DBUS_SESSION_BUS_ADDRESS})
        || $ENV{DBUS_SESSION_BUS_ADDRESS} eq q{};

    my $notify_send = $self->config->tool('notify_send');
    return if !defined($notify_send) || $notify_send eq q{};

    $action_name = 'requested-action'
        if !defined($action_name) || $action_name eq q{};

    my ($urgency, $icon, $timeout_milliseconds, $summary, $body);
    if ($status == 0) {
        (
            $urgency,
            $icon,
            $timeout_milliseconds,
            $summary,
            $body,
        ) = (
            'normal',
            'phone',
            10_000,
            'Android action completed',
            "The $action_name action completed successfully.",
        );
    }
    else {
        (
            $urgency,
            $icon,
            $timeout_milliseconds,
            $summary,
            $body,
        ) = (
            'critical',
            'dialog-error',
            0,
            'Android action failed',
            "The $action_name action failed with status $status.",
        );
    }

    eval {
        $self->command->run_quiet(
            10,
            $notify_send,
            '-a', 'Android Device',
            '-u', $urgency,
            '-i', $icon,
            '-c', 'x-labwc.maintenance',
            '-t', $timeout_milliseconds,
            $summary,
            $body,
        );
        1;
    };
    return;
}

1;
