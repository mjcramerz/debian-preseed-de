package AICopilots::Session;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Bool Str);

has home => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    builder => sub { $ENV{HOME} // q{} },
);
has runtime_directory => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    builder => sub { $ENV{XDG_RUNTIME_DIR} // q{} },
);
has require_wayland => (
    is      => 'ro',
    isa     => Bool,
    default => sub { 1 },
);

sub assert_desktop_user {
    my ($self) = @_;

    $< != 0
        or die "labwc-ai-copilots-action: must run as the logged-in desktop user\n";

    my $home = $self->home();
    $home =~ m{\A/[^[:cntrl:]]+\z} && $home !~ m{(?:\A|/)\.\.(?:/|\z)|//}
        or die "labwc-ai-copilots-action: HOME is invalid\n";
    -d $home && !-l $home
        or die "labwc-ai-copilots-action: HOME must be a real directory\n";
    my @home_stat = lstat $home;
    $home_stat[4] == $<
        or die "labwc-ai-copilots-action: HOME ownership is unsafe\n";

    my $runtime = $self->runtime_directory();
    my ($runtime_uid) = $runtime =~ m{\A/run/user/([1-9][0-9]*)\z};
    defined($runtime_uid) && $runtime_uid == $< && -d $runtime && !-l $runtime
        or die "labwc-ai-copilots-action: XDG_RUNTIME_DIR is invalid\n";
    my @runtime_stat = lstat $runtime;
    $runtime_stat[4] == $< && ($runtime_stat[2] & 0077) == 0
        or die "labwc-ai-copilots-action: XDG_RUNTIME_DIR ownership or mode is unsafe\n";

    if ($self->require_wayland()) {
        my $wayland_display = $ENV{WAYLAND_DISPLAY} // q{};
        $wayland_display =~ /\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\z/
            or die "labwc-ai-copilots-action: an active Wayland display is required\n";
        -S "$runtime/$wayland_display"
            or die "labwc-ai-copilots-action: the active Wayland socket is unavailable\n";
        ($ENV{XDG_SESSION_TYPE} // 'wayland') eq 'wayland'
            or die "labwc-ai-copilots-action: a Wayland session is required\n";
        ($ENV{LABWC_SESSION_OWNER} // q{}) eq 'desktop'
            or die "labwc-ai-copilots-action: the managed Labwc desktop session is required\n";
        my $bus = $ENV{DBUS_SESSION_BUS_ADDRESS} // q{};
        (!length($bus) || $bus eq "unix:path=$runtime/bus")
            or die "labwc-ai-copilots-action: the session bus address is invalid\n";
    }

    return 1;
}

1;
