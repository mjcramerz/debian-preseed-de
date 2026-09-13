package Labwc::WorkspaceBroker::Client;
use strict;
use warnings;
use Fcntl qw(:DEFAULT :flock :mode);
use IO::Select ();
use Errno qw(EAGAIN EWOULDBLOCK EINTR);
use Labwc::WorkspaceBroker::Runtime qw(now runtime_dir private_file read_private connect_socket token);
use Labwc::WorkspaceBroker::Wire qw(frame take_frames decode_json json_bytes exact_keys uint text);
use Labwc::WorkspaceBroker::Render qw(empty_frame);
use Labwc::WorkspaceBroker::Picker ();

sub write_all {
    my ($fh, $bytes) = @_;
    while (length $bytes) {
        my $n = syswrite($fh, $bytes);
        next if !defined($n) && $! == EINTR;
        die "private write failure\n" unless defined($n) && $n;
        substr($bytes, 0, $n, '');
    }
}
sub atomic_file {
    my ($path, $bytes) = @_;
    if (my @s = lstat($path)) {
        die "unsafe cache destination\n" unless S_ISREG($s[2]) && $s[4] == $< && ($s[2] & 0777) == 0600 && $s[3] == 1;
    }
    my $tmp = $path . '.' . $$ . '.' . token();
    my $fh = private_file($tmp, O_WRONLY | O_CREAT | O_EXCL);
    my $ok = eval {
        write_all($fh, $bytes);
        close($fh) or die "cache close failure\n";
        rename($tmp, $path) or die "cache rename failure\n";
        1;
    };
    my $error = $@;
    if (!$ok) { close $fh; unlink $tmp; die $error; }
}
sub send_request {
    my ($fh, $obj) = @_;
    my $bytes = frame($obj, 16384);
    my $deadline = now() + 3;
    my $select = IO::Select->new($fh);
    while (length $bytes) {
        die "control write timeout\n" if now() >= $deadline;
        next unless $select->can_write(0.1);
        my $n = syswrite($fh, $bytes);
        next if !defined($n) && ($! == EAGAIN || $! == EWOULDBLOCK || $! == EINTR);
        die "control write failure\n" unless defined($n) && $n;
        substr($bytes, 0, $n, '');
    }
}
sub receive {
    my ($fh, $buffer, $deadline) = @_;
    my $select = IO::Select->new($fh);
    while (1) {
        my @frames = take_frames($buffer, 262144, 1);
        return $frames[0] if @frames;
        die "control read timeout\n" if defined($deadline) && now() >= $deadline;
        next unless $select->can_read(0.2);
        my $n = sysread($fh, my $part, 65536);
        next if !defined($n) && ($! == EAGAIN || $! == EWOULDBLOCK || $! == EINTR);
        die "control channel closed\n" unless defined($n) && $n;
        $$buffer .= $part;
        die "control input limit\n" if length($$buffer) > 327680;
    }
}
sub _page {
    my ($p) = @_;
    exact_keys($p, qw(kind token count offset rows mode lines width));
    die "picker response\n" unless $p->{kind} eq 'picker';
    text($p->{token}, 32); die "picker token\n" unless $p->{token} =~ /\A[0-9a-f]{32}\z/;
    uint($p->{count}, 1024, 1); uint($p->{offset}, $p->{count} - 1);
    uint($p->{lines}, 32, 2); uint($p->{width}, 120, 24);
    text($p->{mode}, 8); die "picker mode\n" unless $p->{mode} eq 'primary' || $p->{mode} eq 'close';
    die "picker rows\n" unless ref($p->{rows}) eq 'ARRAY' && @{$p->{rows}} && @{$p->{rows}} <= 128 && $p->{offset} % 128 == 0;
    my $i = $p->{offset};
    for my $r (@{$p->{rows}}) {
        exact_keys($r, qw(index label));
        die "picker row index\n" unless uint($r->{index}, $p->{count} - 1) == $i++;
        text($r->{label}, 512);
    }
    my $expected = $p->{count} - $p->{offset}; $expected = 128 if $expected > 128;
    die "incomplete picker page\n" unless @{$p->{rows}} == $expected;
}
sub prepare_style {
    my ($dir) = @_;
    my @pw = getpwuid($<);
    my $home = $pw[7] // '';
    die "home path\n" unless $home =~ m{\A(/[A-Za-z0-9_./-]+)\z};
    $home = $1;
    die "home traversal\n" if $home =~ m{(?:\A|/)\.\.(?:/|\z)};
    my $style = "$home/.config/waybar/style.css";
    die "missing managed Waybar style\n" unless -f $style;
    # Must exist before Waybar installs its import-file monitor. Replacing this
    # inode later would not generate the CHANGES_DONE_HINT it listens for.
    if (!lstat("$dir/icons.css")) {
        my $fh = eval { private_file("$dir/icons.css", O_WRONLY | O_CREAT | O_EXCL) };
        close $fh if $fh;
        die "cannot initialize icon stylesheet\n" unless -f "$dir/icons.css";
    }
    my $fh = private_file("$dir/icons.css", O_RDONLY); close $fh;
    atomic_file("$dir/panel.css", qq{\@import url("$style");\n\@import url("$dir/icons.css");\n});
    print "$dir/panel.css\n" or die "style output\n";
}
sub run {
    my (@args) = @_;
    umask 0077;
    local $SIG{PIPE} = 'IGNORE';
    my $dir = runtime_dir();
    my $verb = shift(@args) // '';
    if ($verb eq 'prepare-style') {
        die "usage: prepare-style\n" if @args;
        prepare_style($dir); return 0;
    }
    my $slot;
    if ($verb eq 'watch' || $verb eq 'primary' || $verb eq 'close') {
        die "usage: watch|primary|close --slot 0..64\n" unless @args == 2 && $args[0] eq '--slot' && $args[1] =~ /\A([0-9]{1,2})\z/;
        $slot = 0 + $1;
        die "slot range\n" if $slot > 64;
    } elsif ($verb ne 'diagnose' || @args) { die "usage: watch|primary|close --slot N | diagnose | prepare-style\n"; }
    if ($verb eq 'watch') {
        $| = 1;
        my $ok = eval {
            my $output = $ENV{WAYBAR_OUTPUT_NAME} // '';
            die "missing Waybar output name\n" unless $output =~ /\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\z/;
            my $sock = connect_socket("$dir/control.sock"); my $buffer = '';
            my $last_view = '';
            send_request($sock, { v => 1, kind => 'watch', slot => $slot, output => $output });
            while (1) {
                my $msg = receive($sock, \$buffer, undef);
                exact_keys($msg, qw(kind frame view));
                die "unexpected watch response\n" unless $msg->{kind} eq 'frame' && ref($msg->{frame}) eq 'HASH';
                # The authenticated broker produces markup. Clients never append
                # a title, command or unescaped application string to this JSON.
                print json_bytes($msg->{frame}) . "\n" or die "Waybar output closed\n";
                if (defined $msg->{view}) {
                    exact_keys($msg->{view}, qw(epoch wg sg slot));
                    text($msg->{view}{epoch}, 32);
                    die "view epoch\n" unless $msg->{view}{epoch} =~ /\A[0-9a-f]{32}\z/;
                    uint($msg->{view}{wg}, 9007199254740000); uint($msg->{view}{sg}, 9007199254740000);
                    die "view slot\n" unless uint($msg->{view}{slot}, 64) == $slot;
                    # Shared slot identity is workspace-global, not output-local.
                    # An empty monitor must never erase another monitor's lease.
                    my $bytes = json_bytes($msg->{view});
                    if ($bytes ne $last_view) {
                        atomic_file("$dir/view.$slot.json", $bytes);
                        $last_view = $bytes;
                    }
                }
            }
        };
        if (!$ok) { print json_bytes(empty_frame()) . "\n"; return 1; }
    }
    my $sock = connect_socket("$dir/control.sock"); my $buffer = '';
    if ($verb eq 'diagnose') {
        send_request($sock, { v => 1, kind => 'diagnose' });
        my $d = receive($sock, \$buffer, now() + 3);
        die "diagnostics response\n" unless ($d->{kind} // '') eq 'diagnostics';
        print json_bytes($d) . "\n" or die "diagnostics output\n";
        return 0;
    }
    my $view = eval { decode_json(read_private("$dir/view.$slot.json", 4096)) };
    return 0 unless $view; # No visible/current lease is always a no-op.
    send_request($sock, { v => 1, kind => 'action', slot => $slot, view => $view, mode => $verb eq 'close' ? 'close' : 'primary' });
    my $deadline = now() + 58;
    my ($token, $count, $mode);
    while (1) {
        my $reply = receive($sock, \$buffer, now() + 3);
        my $kind = text($reply->{kind}, 32);
        return 0 if $kind eq 'done' || $kind eq 'stale';
        _page($reply);
        if (defined $token) {
            die "picker snapshot changed\n" unless $reply->{token} eq $token && $reply->{count} == $count && $reply->{mode} eq $mode;
        } else { ($token, $count, $mode) = @{$reply}{qw(token count mode)}; }
        my $selection = Labwc::WorkspaceBroker::Picker::choose($reply, $deadline - now());
        return 0 unless $selection;
        if (exists $selection->{offset}) {
            send_request($sock, { v => 1, kind => 'page', token => $token, offset => $selection->{offset} });
        } else {
            send_request($sock, { v => 1, kind => 'choose', token => $token, index => $selection->{index} });
            my $result = receive($sock, \$buffer, now() + 3);
            die "selection response\n" unless ($result->{kind} // '') eq 'done' || ($result->{kind} // '') eq 'stale';
            return 0;
        }
    }
}
1;
