package Zram::Setup::CLI;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use Zram::Error qw(usage_error);
use Zram::Setup::Config;
use Zram::Setup::Lifecycle;

sub run {
    my ($self, @argv) = @_;
    @argv == 1 or usage_error('usage: zram-device-setup {start|stop|reset|wait-backing|status}');

    my $action = $argv[0];
    $action =~ /\A(?:start|stop|reset|wait-backing|status)\z/
        or usage_error('usage: zram-device-setup {start|stop|reset|wait-backing|status}');

    my $config = Zram::Setup::Config->new()->load();
    return Zram::Setup::Lifecycle->new(config => $config)->run($action);
}

1;
