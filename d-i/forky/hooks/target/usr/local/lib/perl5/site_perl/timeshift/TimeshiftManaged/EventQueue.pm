package TimeshiftManaged::EventQueue;

use strict;
use warnings;

use Fcntl qw(O_CREAT O_EXCL O_NOFOLLOW O_WRONLY);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(strftime);
use Time::HiRes qw(time);
use Types::Standard qw(Int Str);

use TimeshiftManaged::Logger;

has event_root => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has owner_gid => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has owner_uid => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has logger => (
    is       => 'ro',
    required => 1,
);

has sequence => (
    is      => 'rw',
    isa     => Int,
    default => sub { 0 },
);

sub event_dir {
    my ($self) = @_;
    return $self->event_root() . '/timeshift';
}

sub _validate_absolute_path {
    my ($self, $label, $value) = @_;

    defined($value) && $value =~ m{\A/}
        or die "$label must be an absolute path\n";
    $value !~ m{(?:^|/)\.\.(?:/|$)}
        or die "$label contains a parent-directory component\n";
    $value !~ m{//}
        or die "$label contains an empty path component\n";
    $value =~ m{\A/[A-Za-z0-9._/@%:+,-]*\z}
        or die "$label contains unsupported path syntax\n";
    return $value;
}

sub _ensure_directory {
    my ($self, $directory) = @_;

    $self->_validate_absolute_path('Timeshift notification path', $directory);
    my $current = q{};
    for my $part (grep { $_ ne q{} } split m{/+}, $directory) {
        $current .= "/$part";
        if (-l $current) {
            die "Timeshift notification path must not be a symlink: $current\n";
        }
        my $created = 0;
        if (-e $current) {
            -d $current
                or die "Timeshift notification path is not a directory: $current\n";
        }
        else {
            mkdir $current, 0755
                or die "cannot create Timeshift notification directory $current: $!\n";
            $created = 1;
        }
        if ($created || $current eq $directory) {
            $self->_set_owner_and_mode($current, 0755);
        }
    }
    return;
}

sub _set_owner_and_mode {
    my ($self, $path, $mode) = @_;

    my $current_uid = $>;
    my ($current_gid) = split /\s+/, $);
    if ($current_uid != $self->owner_uid() || $current_gid != $self->owner_gid()) {
        $current_uid == 0
            or die "Timeshift notification ownership requires root privileges\n";
        chown $self->owner_uid(), $self->owner_gid(), $path
            or die "cannot set Timeshift notification owner for $path: $!\n";
    }
    chmod $mode, $path
        or die "cannot set Timeshift notification mode for $path: $!\n";
    return;
}

sub _prune_expired_events {
    my ($self) = @_;
    my $directory = $self->event_dir();
    my $cutoff = time() - (45 * 24 * 60 * 60);

    opendir my $dh, $directory
        or die "cannot read Timeshift notification directory $directory: $!\n";
    while (my $name = readdir $dh) {
        next if $name !~ /\A[0-9]{10}-[0-9]{10}-[0-9]{4}\.event\z/;
        my $path = "$directory/$name";
        next if -l $path;
        my @stat = lstat $path;
        next if !@stat || !-f _;
        unlink $path
            or die "cannot remove expired Timeshift event $path: $!\n"
            if $stat[9] < $cutoff;
    }
    closedir $dh or die "cannot close Timeshift notification directory $directory: $!\n";
    return;
}

sub emit {
    my ($self, %args) = @_;

    my $status = $args{status};
    my $kind = $args{kind};
    my $detail = $args{detail};
    $status =~ /\A(?:started|completed|failed)\z/
        or die "unsupported Timeshift notification status\n";
    $kind =~ /\A(?:daily|weekly|monthly)\z/
        or die "unsupported Timeshift notification kind\n";
    if ($status eq 'failed') {
        defined($detail) && $detail =~ /\A[0-9]{1,3}\z/ && $detail <= 255
            or die "Timeshift failure notification requires an exit status\n";
    }
    else {
        (!defined($detail) || $detail eq '-')
            or die "Timeshift non-failure notification requires '-' detail\n";
        $detail = '-';
    }

    $self->_ensure_directory($self->event_root());
    $self->_ensure_directory($self->event_dir());
    $self->_prune_expired_events();

    my $epoch = int(time());
    my $sequence = $self->sequence() + 1;
    $self->sequence($sequence);
    my $name = sprintf '%010d-%010d-%04d.event', $epoch, $$, $sequence;
    my $temporary = $self->event_dir() . "/.$name.tmp";
    my $event = $self->event_dir() . "/$name";

    sysopen my $fh, $temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0644
        or die "cannot create Timeshift event $temporary: $!\n";
    print {$fh} "$status|$kind|$detail\n"
        or die "cannot write Timeshift event $temporary: $!\n";
    close $fh or die "cannot close Timeshift event $temporary: $!\n";
    $self->_set_owner_and_mode($temporary, 0644);
    rename $temporary, $event
        or die "cannot publish Timeshift event $event: $!\n";
    return;
}

1;
