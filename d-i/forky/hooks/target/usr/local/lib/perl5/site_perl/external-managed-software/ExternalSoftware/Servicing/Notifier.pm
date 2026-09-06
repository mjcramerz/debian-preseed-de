package ExternalSoftware::Servicing::Notifier;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use File::Basename qw(basename);
use File::Path qw(make_path);
use File::Spec;
use Fcntl qw(:DEFAULT :flock F_SETFD FD_CLOEXEC);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
use ExternalSoftware::Servicing::Atomic;

my %APP_LABEL = (
    bitwarden => 'Bitwarden Desktop',
    chatgpt   => 'ChatGPT/Codex Desktop',
    obsidian  => 'Obsidian',
    qoredb    => 'QoreDB',
    zoom      => 'Zoom Workplace',
    filen     => 'Filen Desktop',
    discord   => 'Discord',
    sleek     => 'Sleek',
    postman   => 'Postman',
    ledger    => 'Ledger Wallet (Ledger Live)',
    tuta      => 'Tuta Mail',
    all       => 'Managed software',
);

my %FAILURE_BODY = (
    download   => 'The vendor download could not be retrieved safely.',
    validation => 'The downloaded artifact failed package or payload validation.',
    missing    => 'The managed application is no longer installed, so it was not recreated.',
    downgrade  => 'The vendor artifact is older than the installed version and was rejected.',
    install    => 'APT could not install or verify the downloaded package.',
    signature  => 'The vendor signature, checksum, or pinned public key verification failed.',
    extract    => 'The verified AppImage could not be extracted safely.',
    archive    => 'The downloaded archive failed structure or payload validation.',
    payload    => 'The installed package is missing required managed payload files.',
    policy     => 'The managed application security policy could not be restored or verified.',
    publish    => 'The verified AppImage update could not be published atomically.',
    postinstall => 'The installed application failed post-install verification.',
    'in-use'   => 'The application is still running. Close it before retrying the retained update.',
);

has event_dir => (is => 'ro', default => sub { '/var/lib/software/events' });

sub _notify {
    my ($self, $urgency, $icon, $timeout, $summary, $body) = @_;
    system(
        '/usr/bin/timeout', '--kill-after=1s', '3s', '/usr/bin/notify-send', '-a', 'Software Updater', '-u', $urgency,
        '-i', $icon, '-c', 'system.software-update', '-t', $timeout,
        q{--}, $summary, $body,
    ) == 0 or die "notify-send failed\n";
}

sub _deliver {
    my ($self, $status, $app, $a, $b) = @_;
    exists $APP_LABEL{$app} or die "unknown managed application event\n";
    if ($status eq 'checking') {
        return $self->_notify('normal', 'software-update-available', 8000, 'Checking managed software updates',
            'Bitwarden, ChatGPT/Codex Desktop, Obsidian, Zoom, Filen, Discord, Sleek, Postman, Ledger, and Tuta Mail are being checked; QoreDB remains checksum-pinned for local repair.');
    }
    if ($status eq 'downloading' || $status eq 'downloaded') {
        return $self->_notify('normal', 'software-update-available', 10000,
            $status eq 'downloaded' ? "$APP_LABEL{$app} download ready" : "Downloading $APP_LABEL{$app}",
            "$a -> $b");
    }
    if ($status eq 'updated' || $status eq 'applying') {
        return $self->_notify('normal', 'software-update-urgent', 10000,
            $status eq 'updated' ? "$APP_LABEL{$app} updated" : "Applying $APP_LABEL{$app}", "$a -> $b");
    }
    if ($status eq 'failed') {
        exists $FAILURE_BODY{$a} or die "unknown managed application failure reason\n";
        return $self->_notify('critical', 'dialog-error', 0, "$APP_LABEL{$app} update failed", $FAILURE_BODY{$a});
    }
    if ($status eq 'download-complete') {
        return $self->_notify('normal', 'software-update-available', 12000, 'Managed software download complete', "$a ready; $b failed.");
    }
    if ($status eq 'apply-complete') {
        return $self->_notify('normal', 'software-update-urgent', 12000, 'Managed software update complete', "$a updated; $b failed.");
    }
    if ($status eq 'no-updates') {
        return $self->_notify('normal', 'software-update-available', 8000, 'Managed software is current', 'No updates were available.');
    }
    die "unknown managed application event status\n";
}

sub _private_directory {
    my ($path) = @_;
    ExternalSoftware::Servicing::Atomic->assert_absolute_path('notification state directory', $path);
    my $current = q{};
    for my $part (grep { length } split m{/}, $path) {
        $current .= "/$part";
        mkdir $current, 0700 if !-e $current && !-l $current;
        my @st = lstat $current;
        @st && -d _ && !-l _ && ($st[4] == 0 || $st[4] == $<) && ($st[2] & 0022) == 0
            or die "unsafe notification state path: $current\n";
    }
    my @st = lstat $path;
    $st[4] == $< or die "notification state directory belongs to another user\n";
    chmod 0700, $path or die "cannot protect notification state directory: $!\n";
    return $path;
}

sub run {
    my ($self) = @_;
    umask 0077;
    -x '/usr/bin/notify-send' && -x '/usr/bin/timeout' && length($ENV{DBUS_SESSION_BUS_ADDRESS} // q{})
        or die "notification service requires notify-send, timeout and the session bus\n";
    my $events = $self->event_dir();
    return 0 if !-e $events && !-l $events;
    my @event_stat = lstat $events;
    @event_stat && -d _ && !-l _ && $event_stat[4] == 0 && ($event_stat[2] & 0022) == 0
        or die "unsafe managed software event directory\n";
    my $root = $ENV{XDG_STATE_HOME} || (($ENV{HOME} // q{}) . '/.local/state');
    my $state = _private_directory(File::Spec->catdir($root, 'managed-external-software'));
    my $seen = _private_directory(File::Spec->catdir($state, 'seen'));
    sysopen my $lock, "$state/notify.lock", O_RDWR | O_CREAT | O_NOFOLLOW, 0600
        or die "cannot open notification lock: $!\n";
    my @lock_stat = stat $lock;
    -f $lock && $lock_stat[4] == $< && $lock_stat[3] == 1 && ($lock_stat[2] & 0077) == 0
        or die "unsafe notification lock\n";
    fcntl($lock, F_SETFD, FD_CLOEXEC) or die "cannot protect notification lock: $!\n";
    if (!flock($lock, LOCK_EX | LOCK_NB)) {
        $!{EWOULDBLOCK} || $!{EAGAIN} or die "cannot lock notifications: $!\n";
        return 0;  # The existing owner processes the same immutable event set.
    }
    opendir my $dh, $events or die "cannot open event directory: $!\n";
    my @names = sort grep { /\A[0-9]{10}-[0-9]{10}-[0-9]{4}\.event\z/ } readdir $dh;
    closedir $dh or die "cannot close event directory: $!\n";
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + 75;
    my ($failed, $processed) = (0, 0);
    for my $name (@names) {
        my $path = File::Spec->catfile($events, $name);
        my $marker = File::Spec->catfile($seen, "$name.seen");
        if (-e $marker || -l $marker) {
            my @st = lstat $marker;
            @st && -f _ && !-l _ && $st[4] == $< && $st[3] == 1 && ($st[2] & 0077) == 0
                or die "unsafe notification acknowledgement\n";
            next;
        }
        if ($processed >= 20 || clock_gettime(CLOCK_MONOTONIC) >= $deadline) {
            $failed = 1;  # Restart=on-failure drains a backlog in bounded batches.
            last;
        }
        my @st = lstat $path;
        next if !@st;  # The trusted producer may expire old events.
        if (!-f _ || -l _ || $st[4] != 0 || ($st[2] & 0022) || $st[7] > 512) {
            warn "ignoring unsafe event: $name\n";
            next;
        }
        my $line = eval { ExternalSoftware::Servicing::Atomic->read_limited($path, 512) };
        if ($@ || !defined $line || $line !~ /\A([^|\n]+)\|([^|\n]+)\|([^|\n]+)\|([^|\n]+)\n\z/) {
            warn "ignoring unreadable or malformed event: $name\n";
            next;
        }
        my @fields = ($1, $2, $3, $4);
        ++$processed;
        if (eval { $self->_deliver(@fields); 1 }) {
            ExternalSoftware::Servicing::Atomic->write_user_text($marker, q{}, 0600);
        } else {
            warn "notification delivery failed for $name: $@";
            $failed = 1;
            last;  # Do not overtake an event while the session bus is unavailable.
        }
    }
    # Retain acknowledgements while the corresponding event can still replay.
    opendir my $sdh, $seen or die "cannot open acknowledgements: $!\n";
    for my $name (readdir $sdh) {
        next if $name !~ /\A([0-9]{10}-[0-9]{10}-[0-9]{4}\.event)\.seen\z/;
        next if -e "$events/$1";
        my $marker = "$seen/$name";
        my @st = lstat $marker;
        unlink $marker or die "cannot prune acknowledgement: $!\n"
            if @st && -f _ && !-l _ && $st[4] == $<;
    }
    closedir $sdh or die "cannot close acknowledgements: $!\n";
    return $failed ? 1 : 0;
}

1;
