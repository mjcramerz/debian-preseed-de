package DigitalAssets::Session;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Str);

has runtime_directory => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    builder => sub { $ENV{XDG_RUNTIME_DIR} // q{} },
);

sub assert_desktop_user {
    my ($self) = @_;
    $< != 0 or die "labwc-digital-assets-action: must run as the logged-in desktop user\n";
    my $runtime = $self->runtime_directory();
    my ($runtime_uid) = $runtime =~ m{\A/run/user/([1-9][0-9]*)\z};
    defined($runtime_uid) && $runtime_uid == $< && -d $runtime && !-l $runtime
        or die "labwc-digital-assets-action: XDG_RUNTIME_DIR is invalid\n";
    my @runtime_stat = lstat $runtime;
    $runtime_stat[4] == $< && ($runtime_stat[2] & 0077) == 0
        or die "labwc-digital-assets-action: XDG_RUNTIME_DIR ownership or mode is unsafe\n";
    defined($ENV{WAYLAND_DISPLAY}) && length($ENV{WAYLAND_DISPLAY})
        or die "labwc-digital-assets-action: an active Wayland display is required\n";
    ($ENV{XDG_SESSION_TYPE} // 'wayland') eq 'wayland'
        or die "labwc-digital-assets-action: a Wayland session is required\n";
    return 1;
}

1;
