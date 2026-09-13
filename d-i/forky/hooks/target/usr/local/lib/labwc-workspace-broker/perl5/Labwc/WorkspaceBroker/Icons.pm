package Labwc::WorkspaceBroker::Icons;
use strict;
use warnings;
use Fcntl qw(:DEFAULT :mode :flock);
use Digest::SHA qw(sha256_hex);
use Encode qw(decode FB_CROAK);
use Errno qw(EINTR);
use Labwc::WorkspaceBroker::Runtime qw(private_file);
use Labwc::WorkspaceBroker::Policy ();

# GTK3 supports real icon-theme images as CSS backgrounds on GtkLabel. This
# preserves application images without compiling Waybar or replacing them with
# font glyphs. Only safe icon specifications from package-owned desktop files
# enter CSS; the selector is a digest, never an application-controlled string.
sub new {
    my ($class, $dir) = @_;
    my $self = bless { dir => $dir, catalog => {}, rules => {}, misses => {} }, $class;
    $self->_icon('application-x-executable');
    $self->_icon('view-more-symbolic');
    my $count = 0;
    for my $root ('/usr/local/share/applications', '/usr/share/applications') {
        opendir(my $dh, $root) or next;
        my @files = sort grep { /\A[A-Za-z0-9][A-Za-z0-9_.+-]{0,191}\.desktop\z/ } readdir($dh);
        closedir $dh;
        for my $file (@files) {
            last if ++$count > 4096;
            $self->_desktop($root, $file);
        }
    }
    $self->write_css;
    return $self;
}
sub _safe_icon {
    my ($value) = @_;
    return $value if $value =~ /\A[A-Za-z0-9][A-Za-z0-9_.+-]{0,191}\z/;
    if ($value =~ m{\A/(?:usr/share/(?:icons|pixmaps)|usr/local/share/icons)/[A-Za-z0-9_./+-]+\z}
            && $value !~ m{(?:\A|/)\.\.(?:/|\z)} && length($value) <= 512) {
        return $value;
    }
    return 'application-x-executable';
}
sub _icon {
    my ($self, $value) = @_;
    $value = _safe_icon($value);
    my $class = 'wbi-' . sha256_hex($value);
    return $class if exists $self->{rules}{$class};
    die "icon catalog limit\n" if keys(%{$self->{rules}}) >= 8192;
    my $image = substr($value, 0, 1) eq '/' ? 'url("' . $value . '")' : '-gtk-icontheme("' . $value . '")';
    $self->{rules}{$class} = ".workspace-app.$class { background-image: $image; }\n";
    return $class;
}
sub _desktop {
    my ($self, $root, $file) = @_;
    sysopen(my $fh, "$root/$file", O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or return;
    my @s = stat($fh);
    if (!S_ISREG($s[2]) || $s[4] != 0 || ($s[2] & 0022) || $s[7] > 65536) { close $fh; return; }
    my $bytes = do { local $/; <$fh> };
    close $fh;
    my $data = eval { decode('UTF-8', $bytes, FB_CROAK) };
    return unless defined $data;
    my ($section, %values);
    for my $line (split /\n/, $data) {
        $line =~ s/\r\z//;
        if ($line =~ /^\[([^\]]+)\]\s*$/) { $section = $1; next; }
        next unless ($section // '') eq 'Desktop Entry';
        if ($line =~ /\A(Name|Icon|StartupWMClass)=(.*)\z/) {
            $values{$1} = $2 unless exists $values{$1};
        }
    }
    my $id = $file; $id =~ s/\.desktop\z//;
    my $icon = _safe_icon($values{Icon} // 'application-x-executable');
    my $entry = { name => substr($values{Name} // $id, 0, 160), class => $self->_icon($icon) };
    $self->{catalog}{$id} //= $entry;
    $self->{catalog}{Labwc::WorkspaceBroker::Policy::canonical($id, q{})} //= $entry;
    my $wm = $values{StartupWMClass} // '';
    $self->{catalog}{$wm} //= $entry if $wm =~ /\A[A-Za-z0-9][A-Za-z0-9_.+-]{0,191}\z/;
}
sub lookup {
    my ($self, $id) = @_;
    if (!exists $self->{catalog}{$id} && !$self->{misses}{$id}
            && $id =~ /\A[A-Za-z0-9][A-Za-z0-9_.+-]{0,191}\z/) {
        # A newly installed application's desktop entry can be picked up on its
        # first appearance, without polling directories or reloading on focus.
        for my $root ('/usr/local/share/applications', '/usr/share/applications') {
            $self->_desktop($root, "$id.desktop");
        }
        if (exists $self->{catalog}{$id}) { $self->write_css; }
        elsif (keys(%{$self->{misses}}) < 1024) { $self->{misses}{$id} = 1; }
    }
    return $self->{catalog}{$id} // { name => substr($id =~ /^\@anonymous:/ ? 'Application' : $id, 0, 160),
        class => $self->_icon('application-x-executable') };
}
sub write_css {
    my ($self) = @_;
    my $lock = private_file("$self->{dir}/icons.lock", O_RDWR | O_CREAT);
    flock($lock, LOCK_EX | LOCK_NB) or die "icon lock: $!\n";
    my $css = "/* Generated icon images only; application strings are not CSS. */\n" . join('', map { $self->{rules}{$_} } sort keys %{$self->{rules}});
    die "CSS size limit\n" if length($css) > 2097152;
    # Preserve the inode: Waybar 0.15's Gio monitor handles CHANGES_DONE_HINT,
    # not replacement/move events. close() publishes the completed small file.
    my $fh = private_file("$self->{dir}/icons.css", O_WRONLY | O_CREAT | O_TRUNC);
    my $offset = 0;
    while ($offset < length($css)) {
        my $n = syswrite($fh, $css, length($css) - $offset, $offset);
        next if !defined($n) && $! == EINTR;
        die "CSS write: $!\n" unless defined($n) && $n;
        $offset += $n;
    }
    close($fh) or die "CSS close: $!\n";
    close $lock;
}
1;
