package Labwc::WorkspaceBroker::Broker;
use strict;
use warnings;
use Fcntl qw(:DEFAULT :flock :mode);
use POSIX qw(WNOHANG _exit);
use IO::Select ();
use Errno qw(EAGAIN EWOULDBLOCK EINTR);
use Labwc::WorkspaceBroker::Runtime qw(now runtime_dir private_file nonblock peer listener notify);
use Labwc::WorkspaceBroker::Wire qw(frame take_frames exact_keys uint text json_bytes);
use Labwc::WorkspaceBroker::Config ();
use Labwc::WorkspaceBroker::State ();
use Labwc::WorkspaceBroker::Policy ();
use Labwc::WorkspaceBroker::Icons ();
use Labwc::WorkspaceBroker::Render qw(render picker_page);

sub run {
    umask 0077;
    my $dir = runtime_dir();
    my $lock = private_file("$dir/instance.lock", O_RDWR | O_CREAT);
    flock($lock, LOCK_EX | LOCK_NB) or die "broker already running\n";
    my $cfg = Labwc::WorkspaceBroker::Config::load();
    my $state = Labwc::WorkspaceBroker::State->new(config => $cfg);
    my $icons = Labwc::WorkspaceBroker::Icons->new($dir);
    my $stop = 0;
    local $SIG{TERM} = sub { $stop = 1 };
    local $SIG{INT} = sub { $stop = 1 };
    local $SIG{PIPE} = 'IGNORE';
    my $adapter_listener = listener("$dir/adapter.sock");
    my $control_listener;
    my $child = fork();
    die "fork adapter: $!\n" unless defined $child;
    if (!$child) {
        close $adapter_listener;
        close $lock;
        $SIG{TERM} = $SIG{INT} = $SIG{PIPE} = 'DEFAULT';
        my $display = $ENV{WAYLAND_DISPLAY} // '';
        if ($display !~ /\A(wayland-[A-Za-z0-9_.-]{1,64})\z/) { _exit(126); }
        $display = $1;
        %ENV = (PATH => '/usr/local/bin:/usr/bin:/bin', LANG => 'C.UTF-8',
            XDG_RUNTIME_DIR => "/run/user/$<", WAYLAND_DISPLAY => $display);
        exec { '/usr/bin/python3' } '/usr/bin/python3', '-I', '-B',
            '/usr/local/libexec/labwc-workspace-wayland-adapter', '--parent-pid', getppid() or _exit(127);
    }
    my %clients;
    my $adapter;
    my ($instance, $serial, $ready, $command_id) = ('', 0, 0, 0);
    my (@pending, %commands);
    my $pending_bytes = 0;
    my $started = now();
    my $last_driver = $started;
    my $last_notify = $started;
    my $last_warning = 0;
    my $error;
    my $drop = sub {
        my ($c) = @_;
        my $fd = fileno($c->{fh});
        delete $clients{$fd} if defined $fd;
        close $c->{fh};
        $c->{closed} = 1;
    };
    my $queue = sub {
        my ($c, $obj, $watch) = @_;
        my $bytes = frame($obj, $watch ? 65536 : 262144);
        return if $watch && ($c->{last_frame} // '') eq $bytes;
        $c->{last_frame} = $bytes if $watch;
        if ($watch && length($c->{out})) { $c->{next} = $bytes; }
        else { $c->{out} .= $bytes; }
        my $limit = $watch ? 65536 : 262144;
        if (length($c->{out}) + length($c->{next} // '') > $limit) {
            if ($c->{type} eq 'adapter') { die "adapter command queue limit\n"; }
            $drop->($c);
        }
    };
    my $publish_one = sub {
        my ($c) = @_;
        my $v = $state->view($c->{slot}, $c->{output});
        $queue->($c, { kind => 'frame', frame => render($v, $icons, $cfg),
            view => $v->{visible} ? $v->{view} : undef }, 1);
    };
    my $dispatch = sub {
        my ($ops) = @_;
        die "command backlog\n" if keys(%commands) + @$ops > 256;
        for my $op (@$ops) {
            ++$command_id;
            $commands{$command_id} = now();
            $queue->($adapter, { v => 1, kind => 'command', instance => $instance,
                command_id => $command_id, op => $op->{op}, id => $op->{id} }, 0);
        }
    };
    my $driver_message = sub {
        my ($msg) = @_;
        uint($msg->{v}, 1, 1);
        my $kind = text($msg->{kind}, 32);
        my $identity = text($msg->{instance}, 32);
        die "adapter instance\n" unless $identity =~ /\A[0-9a-f]{32}\z/;
        die "adapter sequence\n" unless uint($msg->{seq}, 9007199254740000, 1) == $serial + 1;
        $serial = $msg->{seq};
        if (!$instance) {
            exact_keys($msg, qw(v kind instance seq pid capabilities));
            die "expected adapter hello\n" unless $kind eq 'hello' && uint($msg->{pid}, 2147483647, 1) == $child;
            die "adapter capabilities\n" unless ref($msg->{capabilities}) eq 'ARRAY'
                && json_bytes({ c => $msg->{capabilities} }) eq json_bytes({ c => ['ext-workspace-v1', 'foreign-toplevel-v1', 'wl-output-name', 'sync-fence'] });
            $instance = $identity;
            return;
        }
        die "wrong adapter instance\n" unless $identity eq $instance;
        my %a = %$msg; delete @a{qw(v instance seq)};
        if ($kind =~ /\A(?:new|task|closed|workspaces|outputs)\z/) {
            Labwc::WorkspaceBroker::Policy::validate_atom(\%a);
            push @pending, \%a;
            $pending_bytes += length(json_bytes(\%a));
            die "observation batch limit\n" if @pending > 4096 || $pending_bytes > 8388608;
        } elsif ($kind eq 'barrier') {
            exact_keys(\%a, 'kind');
            $state->commit(\@pending, now());
            @pending = (); $pending_bytes = 0;
            for my $c (values %clients) { $publish_one->($c) if $c->{watch}; }
        } elsif ($kind eq 'ready') {
            exact_keys(\%a, 'kind');
            my $d = $state->diagnose;
            die "premature or repeated ready\n" if $ready || @pending || !$d->{workspaces} || !$d->{outputs} || !defined($d->{active_workspace});
            $control_listener = listener("$dir/control.sock");
            $ready = 1;
            notify("READY=1\nSTATUS=Workspace broker ready; activation-learned window membership");
        } elsif ($kind eq 'ack') {
            exact_keys(\%a, qw(kind command_id status));
            my $id = uint($a{command_id}, 9007199254740000, 1);
            die "unknown command acknowledgement\n" unless exists $commands{$id};
            my $status = text($a{status}, 16);
            die "ack status\n" unless $status eq 'marshalled' || $status eq 'stale';
            delete $commands{$id};
        } elsif ($kind eq 'heartbeat') {
            exact_keys(\%a, 'kind');
        } else { die "unknown adapter message\n"; }
    };
    my $public_message = sub {
        my ($c, $msg) = @_;
        uint($msg->{v}, 1, 1);
        my $kind = text($msg->{kind}, 16);
        die "request limit\n" if ++$c->{requests} > 128 || $c->{watch} || $c->{finish};
        if ($kind eq 'watch') {
            exact_keys($msg, qw(v kind slot output));
            die "duplicate subscription\n" if $c->{requests} != 1;
            die "watcher limit\n" if scalar(grep { $_->{watch} } values %clients) >= 512;
            $c->{slot} = uint($msg->{slot}, $cfg->{group_slots});
            $c->{output} = text($msg->{output}, 128);
            die "output shape\n" unless $c->{output} =~ /\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\z/;
            $c->{watch} = 1;
            $publish_one->($c);
        } elsif ($kind eq 'diagnose') {
            exact_keys($msg, qw(v kind));
            die "duplicate diagnose\n" if $c->{requests} != 1;
            $queue->($c, { kind => 'diagnostics', ready => $ready,
                watchers => scalar(grep { $_->{watch} } values %clients), %{$state->diagnose} }, 0);
            $c->{finish} = 1;
        } elsif ($kind eq 'action') {
            exact_keys($msg, qw(v kind slot view mode));
            die "duplicate action\n" if $c->{requests} != 1;
            my $slot = uint($msg->{slot}, $cfg->{group_slots});
            my $mode = text($msg->{mode}, 8);
            my $result = @pending ? { kind => 'stale' } : $state->action($slot, $msg->{view}, $mode, now());
            if ($result->{kind} eq 'picker') {
                die "picker limit\n" if scalar(grep { $_->{snapshot} } values %clients) >= 16;
                $c->{snapshot} = $result->{snapshot};
                $c->{deadline} = now() + 61;
                $queue->($c, picker_page($c->{snapshot}, 0, $cfg), 0);
            } else {
                $dispatch->($result->{commands}) if $result->{kind} eq 'commands';
                $queue->($c, { kind => $result->{kind} eq 'commands' ? 'done' : 'stale' }, 0);
                $c->{finish} = 1;
            }
        } elsif ($kind eq 'page' || $kind eq 'choose') {
            exact_keys($msg, qw(v kind token), $kind eq 'page' ? 'offset' : 'index');
            my $token = text($msg->{token}, 32);
            die "picker token shape\n" unless $token =~ /\A[0-9a-f]{32}\z/;
            if (!$c->{snapshot} || !$state->picker_valid($c->{snapshot}, $token, now())) {
                $queue->($c, { kind => 'stale' }, 0); $c->{finish} = 1; return;
            }
            if ($kind eq 'page') {
                my $offset = uint($msg->{offset}, 1023);
                $queue->($c, picker_page($c->{snapshot}, $offset, $cfg), 0);
            } else {
                my $ops = @pending ? [] : $state->choose($c->{snapshot}, $token, uint($msg->{index}, 1023), now());
                delete $c->{snapshot}; # Single-use capability, even on a stale selection.
                $dispatch->($ops);
                $queue->($c, { kind => @$ops ? 'done' : 'stale' }, 0);
                $c->{finish} = 1;
            }
        } else { die "unknown public request\n"; }
    };
    eval {
        while (!$stop) {
            my $exited = waitpid($child, WNOHANG);
            if ($exited == $child || $exited == -1) { $child = undef; die "Wayland driver exited\n"; }
            my $time = now();
            die "adapter connect timeout\n" if !$adapter && $time - $started > 5;
            die "broker initialization timeout\n" if !$ready && $time - $started > 12;
            die "adapter heartbeat timeout\n" if $adapter && $time - $last_driver > 16;
            die "command acknowledgement timeout\n" if grep { $time - $_ > 5 } values %commands;
            if ($ready && $time - $last_notify > 10) { notify('WATCHDOG=1'); $last_notify = $time; }
            my $read = IO::Select->new(); my $write = IO::Select->new();
            $read->add($adapter_listener) if $adapter_listener;
            $read->add($control_listener) if $control_listener;
            my $buffered = 0;
            for my $c (($adapter ? ($adapter) : ()), values %clients) {
                next if $c->{closed};
                if ($c->{type} ne 'adapter' && !$c->{watch} && $time > $c->{deadline}) { $drop->($c); next; }
                if (length($c->{in}) >= 4 && length($c->{in}) >= 4 + unpack('N', substr($c->{in}, 0, 4))) { $buffered = 1; }
                $read->add($c->{fh});
                $write->add($c->{fh}) if length($c->{out});
            }
            my ($r, $w) = IO::Select->select($read, $write, undef, $buffered ? 0 : 0.5);
            for my $fh (@{$r // []}) {
                if (($adapter_listener && fileno($fh) == fileno($adapter_listener))
                        || ($control_listener && fileno($fh) == fileno($control_listener))) {
                    my $is_adapter = $adapter_listener && fileno($fh) == fileno($adapter_listener);
                    for (1 .. 8) {
                        my $sock = $fh->accept() or last;
                        my $pid = eval { (peer($sock))[0] };
                        if (!$pid || ($is_adapter && $pid != $child) || (!$is_adapter && keys(%clients) >= 544)) { close $sock; next; }
                        nonblock($sock);
                        my $c = { fh => $sock, in => '', out => '', type => $is_adapter ? 'adapter' : 'public',
                            pid => $pid, requests => 0, deadline => now() + 3 };
                        if ($is_adapter) { $adapter = $c; close $adapter_listener; $adapter_listener = undef; last; }
                        $clients{fileno($sock)} = $c;
                    }
                    next;
                }
                my $c = $adapter && fileno($fh) == fileno($adapter->{fh}) ? $adapter : $clients{fileno($fh)};
                next unless $c && !$c->{closed};
                my $n = sysread($fh, my $part, 65536);
                next if !defined($n) && ($! == EAGAIN || $! == EWOULDBLOCK || $! == EINTR);
                if (!defined($n) || !$n) {
                    die "adapter channel EOF\n" if $c->{type} eq 'adapter';
                    $drop->($c); next;
                }
                $c->{in} .= $part;
                my $limit = $c->{type} eq 'adapter' ? 327680 : 81920;
                if (length($c->{in}) > $limit) {
                    die "adapter input limit\n" if $c->{type} eq 'adapter';
                    $drop->($c);
                }
            }
            # Also drain complete frames already buffered before select().
            for my $c (($adapter ? ($adapter) : ()), values %clients) {
                next if $c->{closed};
                my $ok = eval {
                    for my $msg (take_frames(\$c->{in}, $c->{type} eq 'adapter' ? 262144 : 16384, 64)) {
                        if ($c->{type} eq 'adapter') { $driver_message->($msg); $last_driver = now(); }
                        else { $public_message->($c, $msg); }
                        last if $c->{closed};
                    }
                    1;
                };
                if (!$ok) {
                    die $@ if $c->{type} eq 'adapter';
                    if (now() - $last_warning >= 5) { warn "workspace broker: rejected control request\n"; $last_warning = now(); }
                    $drop->($c) unless $c->{closed};
                }
            }
            for my $fh (@{$w // []}) {
                my $fd = fileno($fh); next unless defined $fd;
                my $c = $adapter && $fd == fileno($adapter->{fh}) ? $adapter : $clients{$fd};
                next unless $c && !$c->{closed} && length($c->{out});
                my $n = syswrite($fh, $c->{out});
                next if !defined($n) && ($! == EAGAIN || $! == EWOULDBLOCK || $! == EINTR);
                if (!defined($n) || !$n) {
                    die "adapter write failure\n" if $c->{type} eq 'adapter';
                    $drop->($c); next;
                }
                substr($c->{out}, 0, $n, '');
                if (!length($c->{out})) {
                    $c->{out} = delete($c->{next}) // '';
                    $drop->($c) if $c->{finish} && !length($c->{out});
                }
            }
        }
        1;
    } or $error = $@ || "broker failure\n";
    eval { notify('STOPPING=1') };
    close $control_listener if $control_listener;
    close $adapter_listener if $adapter_listener;
    close $adapter->{fh} if $adapter;
    close $_->{fh} for values %clients;
    if ($child) {
        # Only our unreaped child PID is signalled; never discover or kill PIDs
        # from application metadata, lock files, titles, or /proc.
        kill 'TERM', $child;
        my $until = now() + 2;
        while (now() < $until) {
            my $r = waitpid($child, WNOHANG);
            if ($r == $child || $r == -1) { $child = undef; last; }
            select undef, undef, undef, 0.02;
        }
        if ($child) { kill 'KILL', $child; waitpid($child, 0); }
    }
    for my $path ("$dir/control.sock", "$dir/adapter.sock") {
        my @s = lstat($path);
        unlink($path) if @s && S_ISSOCK($s[2]) && $s[4] == $<;
    }
    close $lock;
    die $error if $error && !$stop;
    return 0;
}
1;
