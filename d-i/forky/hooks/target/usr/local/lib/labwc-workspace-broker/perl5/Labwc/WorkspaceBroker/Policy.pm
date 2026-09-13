package Labwc::WorkspaceBroker::Policy;
use strict;
use warnings;
use Digest::SHA qw(sha256_hex);
use Labwc::WorkspaceBroker::Wire qw(exact_keys uint text json_bytes);
use Labwc::WorkspaceBroker::Runtime qw(token);

# The reducer is deliberately independent of IO and of Moo's constructor. The
# production Moo State owns this record exclusively; tests feed this very same
# reducer protocol observations, without a compositor or a second model.
sub new_model {
    my ($slots) = @_;
    uint($slots, 64, 4);
    return {
        epoch => token(), limit => $slots, tasks => {}, tokens => {},
        workspaces => {}, outputs => {}, active => undef, wg => 0, seq => 0,
        max_task_id => 0, orders => {}, assignments => {}, groups => {},
        slots => {}, overflow => [], signatures => {}, generations => {},
        changed_at => {},
    };
}
sub _tick {
    my ($m) = @_;
    die "sequence exhausted\n" if $m->{seq} >= 9007199254740000;
    return ++$m->{seq};
}
sub canonical {
    my ($app, $token) = @_;
    return '@anonymous:' . $token unless length $app;
    return 'foot' if $app eq 'footclient';
    return 'thunar' if $app eq 'org.xfce.Thunar';
    # Never lowercase, infer from titles, or apply substring heuristics.
    return $app;
}
sub _array {
    my ($value, $max) = @_;
    die "expected bounded array\n" unless ref($value) eq 'ARRAY' && @$value <= $max;
    return $value;
}
sub _ids {
    my ($values, $max) = @_;
    _array($values, $max);
    my %seen;
    for (@$values) { uint($_, 2147483647, 1); die "duplicate id\n" if $seen{$_}++; }
    return $values;
}
sub _active {
    my ($ws) = @_;
    my @active = grep { ($ws->{$_}{state} & 1) && !($ws->{$_}{state} & 4) } keys %$ws;
    die "unsupported multiple active workspaces\n" if @active > 1;
    return $active[0];
}
sub _same { return ($_[0] // '') eq ($_[1] // ''); }

sub validate_atom {
    my ($a) = @_;
    die "invalid observation\n" unless ref($a) eq 'HASH';
    my $kind = text($a->{kind}, 32);
    if ($kind eq 'workspaces') {
        exact_keys($a, qw(kind workspaces groups));
        _array($a->{workspaces}, 64); _array($a->{groups}, 64);
        my (%ws, %groups, %members);
        for my $w (@{$a->{workspaces}}) {
            exact_keys($w, qw(id name stable_id state));
            uint($w->{id}, 2147483647, 1); uint($w->{state}, 7);
            text($w->{name}, 256); text($w->{stable_id}, 1024);
            die "duplicate workspace\n" if $ws{$w->{id}}++;
        }
        for my $g (@{$a->{groups}}) {
            exact_keys($g, qw(id outputs workspaces));
            uint($g->{id}, 2147483647, 1);
            die "duplicate workspace group\n" if $groups{$g->{id}}++;
            _ids($g->{outputs}, 64); _ids($g->{workspaces}, 64);
            for (@{$g->{workspaces}}) {
                die "invalid workspace group membership\n" if !$ws{$_} || $members{$_}++;
            }
        }
    } elsif ($kind eq 'outputs') {
        exact_keys($a, qw(kind outputs)); _array($a->{outputs}, 64);
        my (%ids, %names);
        for my $o (@{$a->{outputs}}) {
            exact_keys($o, qw(id name)); uint($o->{id}, 2147483647, 1);
            my $name = text($o->{name}, 128);
            die "invalid output name\n" unless $name =~ /\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\z/;
            die "duplicate output\n" if $ids{$o->{id}}++ || $names{$name}++;
        }
    } elsif ($kind eq 'new' || $kind eq 'closed') {
        exact_keys($a, qw(kind id)); uint($a->{id}, 2147483647, 1);
    } elsif ($kind eq 'task') {
        exact_keys($a, qw(kind id revision title app_id state observed_state outputs));
        uint($a->{id}, 2147483647, 1); uint($a->{revision}, 9007199254740000, 1);
        text($a->{title}, 4096); text($a->{app_id}, 1024);
        uint($a->{state}, 15); uint($a->{observed_state}, 1); _ids($a->{outputs}, 64);
    } else { die "unknown observation\n"; }
}

sub apply_batch {
    my ($m, $atoms, $now) = @_;
    _array($atoms, 4096);
    validate_atom($_) for @$atoms;
    # Decide whether learning must be deferred before processing any toplevel.
    # This removes the focus-before-workspace-done ordering dependency between
    # the two independent Wayland protocols. A driver sync fence closes a batch.
    my $last = $m->{active};
    my $transition = 0;
    for my $a (@$atoms) {
        next unless $a->{kind} eq 'workspaces';
        my %ws = map { $_->{id} => $_ } @{$a->{workspaces}};
        my $active = _active(\%ws);
        $transition ||= !_same($active, $last);
        $last = $active;
    }
    my %positive;
    for my $a (@$atoms) {
        my $kind = $a->{kind};
        if ($kind eq 'outputs') {
            $m->{outputs} = { map { $_->{id} => $_->{name} } @{$a->{outputs}} };
        } elsif ($kind eq 'workspaces') {
            $m->{workspaces} = { map { $_->{id} => { %$_ } } @{$a->{workspaces}} };
            my $active = _active($m->{workspaces});
            if (!_same($active, $m->{active})) {
                $m->{wg} = _tick($m);
                $m->{active} = $active;
            }
            for my $t (values %{$m->{tasks}}) {
                $t->{workspace} = undef if defined($t->{workspace}) && !exists($m->{workspaces}{$t->{workspace}});
            }
        } elsif ($kind eq 'new') {
            my $id = $a->{id};
            die "reused toplevel id\n" if $id <= $m->{max_task_id} || exists $m->{tasks}{$id};
            die "too many toplevels\n" if keys(%{$m->{tasks}}) >= 1024;
            $m->{max_task_id} = $id;
            my $token = token();
            die "token collision\n" if exists $m->{tokens}{$token};
            $m->{tasks}{$id} = { id => $id, token => $token, title => '', app_id => '',
                state => 0, outputs => [], revision => 0, workspace => undef,
                born => _tick($m), last_active => 0 };
            $m->{tokens}{$token} = $id;
        } elsif ($kind eq 'closed') {
            my $t = delete $m->{tasks}{$a->{id}};
            die "closed unknown toplevel\n" unless $t;
            delete $m->{tokens}{$t->{token}};
            delete $positive{$a->{id}};
        } elsif ($kind eq 'task') {
            my $t = $m->{tasks}{$a->{id}} or die "unannounced toplevel\n";
            die "toplevel revision\n" unless $a->{revision} == $t->{revision} + 1;
            @{$t}{qw(title app_id state revision)} = @{$a}{qw(title app_id state revision)};
            $t->{outputs} = [@{$a->{outputs}}];
            if ($a->{observed_state} && ($a->{state} & 4)) {
                $positive{$a->{id}} = 1;
                $t->{last_active} = _tick($m);
                $t->{workspace} = $m->{active} if !$transition && defined($m->{active});
            }
        }
    }
    if ($transition && defined($m->{active})) {
        my @active = grep { $_->{state} & 4 } values %{$m->{tasks}};
        # A cached active bit alone is NOT evidence of a workspace move.
        # Learn only a positively observed, still-active task at the fence.
        if (@active == 1 && $positive{$active[0]{id}}) {
            $active[0]{workspace} = $m->{active};
        } else {
            # A focus-preserving move can have no new foreign state event.
            # Neither retaining the old workspace nor guessing the new one is
            # safe. Hide ambiguous active tasks until positively reactivated.
            $_->{workspace} = undef for @active;
        }
    }
    derive($m, $now);
    return $m;
}

sub derive {
    my ($m, $now) = @_;
    my %all;
    for my $t (sort { $a->{born} <=> $b->{born} } values %{$m->{tasks}}) {
        next unless $t->{revision} && defined($t->{workspace}) && exists($m->{workspaces}{$t->{workspace}});
        my $key = canonical($t->{app_id}, $t->{token});
        push @{$all{$t->{workspace}}{$key}{members}}, $t;
        $all{$t->{workspace}}{$key}{key} = $key;
    }
    for my $ws (keys %{$m->{orders}}) {
        if (!exists $all{$ws}) { delete $m->{orders}{$ws}; delete $m->{assignments}{$ws}; }
    }
    for my $ws (keys %all) {
        my $order = ($m->{orders}{$ws} //= {});
        my $assigned = ($m->{assignments}{$ws} //= {});
        for (keys %$order) { delete $order->{$_} unless exists $all{$ws}{$_}; }
        for (keys %$assigned) { delete $assigned->{$_} unless exists $all{$ws}{$assigned->{$_}}; }
        for my $key (sort { $all{$ws}{$a}{members}[0]{born} <=> $all{$ws}{$b}{members}[0]{born} } keys %{$all{$ws}}) {
            $order->{$key} //= _tick($m);
        }
        my %placed = map { $_ => 1 } values %$assigned;
        for my $key (sort { $order->{$a} <=> $order->{$b} } keys %{$all{$ws}}) {
            next if $placed{$key};
            my ($slot) = grep { !exists $assigned->{$_} } 1 .. $m->{limit};
            last unless defined $slot;
            $assigned->{$slot} = $key;
        }
    }
    my $ws = $m->{active};
    my $groups = defined($ws) ? ($all{$ws} // {}) : {};
    my $assigned = defined($ws) ? ($m->{assignments}{$ws} // {}) : {};
    my %slots = map { $_ => $groups->{$assigned->{$_}} } keys %$assigned;
    my %placed = map { $_ => 1 } values %$assigned;
    my @overflow = sort { $m->{orders}{$ws}{$a->{key}} <=> $m->{orders}{$ws}{$b->{key}} }
        grep { !$placed{$_->{key}} } values %$groups;
    $m->{groups} = $groups; $m->{slots} = \%slots; $m->{overflow} = \@overflow;
    for my $slot (0 .. $m->{limit}) {
        my @g = $slot ? ($slots{$slot} ? ($slots{$slot}) : ()) : @overflow;
        my $sig = sha256_hex(json_bytes({ workspace => $ws,
            groups => [map { { key => $_->{key}, tokens => [map { $_->{token} } @{$_->{members}}] } } @g] }));
        if (($m->{signatures}{$slot} // '') ne $sig) {
            $m->{signatures}{$slot} = $sig;
            $m->{generations}{$slot} = _tick($m);
            $m->{changed_at}{$slot} = $now;
        }
    }
}
sub view_for {
    my ($m, $slot, $output) = @_;
    uint($slot, $m->{limit});
    my @g = $slot ? ($m->{slots}{$slot} ? ($m->{slots}{$slot}) : ()) : @{$m->{overflow}};
    my $visible = 0;
    for my $g (@g) {
        for my $t (@{$g->{members}}) {
            $visible = 1 if grep { ($m->{outputs}{$_} // '') eq $output } @{$t->{outputs}};
        }
    }
    return { groups => \@g, visible => $visible,
        view => { epoch => $m->{epoch}, wg => $m->{wg}, sg => $m->{generations}{$slot} // 0, slot => $slot } };
}
sub validate_view {
    my ($m, $slot, $view, $now) = @_;
    uint($slot, $m->{limit}); exact_keys($view, qw(epoch wg sg slot));
    text($view->{epoch}, 32); uint($view->{wg}, 9007199254740000);
    uint($view->{sg}, 9007199254740000); uint($view->{slot}, $m->{limit});
    return 0 unless defined($m->{active}) && $view->{epoch} eq $m->{epoch}
        && $view->{wg} == $m->{wg} && $view->{slot} == $slot
        && $view->{sg} == ($m->{generations}{$slot} // -1);
    return 0 if $now - ($m->{changed_at}{$slot} // $now) < 0.20;
    return 1;
}
sub action_for {
    my ($m, $slot, $view, $mode, $now) = @_;
    die "invalid action\n" unless $mode eq 'primary' || $mode eq 'close';
    return { kind => 'stale' } unless validate_view($m, $slot, $view, $now);
    my @groups = $slot ? ($m->{slots}{$slot} ? ($m->{slots}{$slot}) : ()) : @{$m->{overflow}};
    return { kind => 'stale' } unless @groups;
    my @members = map { @{$_->{members}} } @groups;
    if ($slot && @members == 1) {
        my $t = $members[0];
        my @ops = $mode eq 'close' ? ('close') : ($t->{state} & 4) ? ('set_minimized')
            : ($t->{state} & 2) ? ('unset_minimized', 'activate') : ('activate');
        return { kind => 'commands', commands => [map { { op => $_, id => $t->{id} } } @ops] };
    }
    my @rows;
    for my $t (sort { $b->{last_active} <=> $a->{last_active} || $a->{born} <=> $b->{born} } @members) {
        my @outputs = map { $m->{outputs}{$_} // () } @{$t->{outputs}};
        @outputs = @outputs[0 .. 3] if @outputs > 4;
        push @rows, { token => $t->{token}, key => canonical($t->{app_id}, $t->{token}),
            title => substr($t->{title}, 0, 160), app_id => substr($t->{app_id}, 0, 128),
            outputs => \@outputs, state => $t->{state} };
    }
    return { kind => 'picker', snapshot => { token => token(), epoch => $m->{epoch},
        wg => $m->{wg}, created => $now, rows => \@rows, mode => $mode } };
}
sub picker_valid {
    my ($m, $p, $token, $now) = @_;
    return $p && $p->{token} eq $token && $p->{epoch} eq $m->{epoch}
        && $p->{wg} == $m->{wg} && $now - $p->{created} <= 60;
}
sub picker_choose {
    my ($m, $p, $token, $index, $now) = @_;
    uint($index, 1023);
    return [] unless picker_valid($m, $p, $token, $now) && $index < @{$p->{rows}};
    my $row = $p->{rows}[$index];
    my $id = $m->{tokens}{$row->{token}} // return [];
    my $t = $m->{tasks}{$id} // return [];
    return [] unless defined($t->{workspace}) && _same($t->{workspace}, $m->{active})
        && canonical($t->{app_id}, $t->{token}) eq $row->{key};
    # Explicit multi-window selection always focuses; it never toggles minimize.
    my @ops = $p->{mode} eq 'close' ? ('close')
        : ($t->{state} & 2) ? ('unset_minimized', 'activate') : ('activate');
    return [map { { op => $_, id => $id } } @ops];
}
sub diagnose {
    my ($m) = @_;
    return { epoch => $m->{epoch}, workspace_generation => $m->{wg},
        active_workspace => defined($m->{active}) ? $m->{workspaces}{$m->{active}}{name} : undef,
        workspaces => scalar(keys %{$m->{workspaces}}), outputs => scalar(keys %{$m->{outputs}}),
        windows => scalar(keys %{$m->{tasks}}),
        unknown_windows => scalar(grep { !defined($_->{workspace}) } values %{$m->{tasks}}),
        current_groups => scalar(keys %{$m->{groups}}), overflow_groups => scalar(@{$m->{overflow}}),
        association => 'activation-learned; inactive workspace membership is not authoritative' };
}
1;
