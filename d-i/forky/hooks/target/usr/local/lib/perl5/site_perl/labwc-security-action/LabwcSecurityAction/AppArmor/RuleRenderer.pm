package LabwcSecurityAction::AppArmor::RuleRenderer;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Bool Str);

has allow_high_risk_capabilities => (
    is      => 'ro',
    isa     => Bool,
    default => sub { 0 },
);

has path_globbing => (
    is      => 'ro',
    isa     => Str,
    default => sub { 'conservative' },
);

my %CAPABILITY = map { $_ => 1 } qw(
  chown dac_override dac_read_search fowner fsetid kill setgid setuid setpcap
  linux_immutable net_bind_service net_broadcast net_admin net_raw ipc_lock
  ipc_owner sys_module sys_rawio sys_chroot sys_ptrace sys_pacct sys_admin
  sys_boot sys_nice sys_resource sys_time sys_tty_config mknod lease
  audit_write audit_control setfcap mac_override mac_admin syslog wake_alarm
  block_suspend audit_read perfmon bpf checkpoint_restore
);

my %AUTOMATIC_CAPABILITY = map { $_ => 1 } qw(
  audit_read audit_write block_suspend ipc_lock net_bind_service sys_nice
  wake_alarm
);

my %NETWORK_FAMILY = map { $_ => 1 } qw(
  unix inet ax25 ipx appletalk netrom bridge atmpvc x25 inet6 rose netbeui
  security key netlink packet ash econet atmsvc rds sna irda pppox wanpipe
  llc ib mpls can tipc bluetooth iucv rxrpc isdn phonet ieee802154 caif alg
  nfc vsock kcm qipcrtr smc xdp mctp
);

my %AUTOMATIC_NETWORK_FAMILY = map { $_ => 1 } qw(
  inet inet6
);

my %NUMERIC_NETWORK_FAMILY = (
    1  => 'unix',
    2  => 'inet',
    10 => 'inet6',
    16 => 'netlink',
    17 => 'packet',
    31 => 'bluetooth',
    40 => 'vsock',
);

my %SOCKET_TYPE = map { $_ => 1 } qw(
  stream dgram seqpacket rdm raw packet
);

my %NUMERIC_SOCKET_TYPE = (
    1  => 'stream',
    2  => 'dgram',
    3  => 'raw',
    4  => 'rdm',
    5  => 'seqpacket',
    10 => 'packet',
);

my %NETWORK_ACCESS = map { $_ => 1 } qw(
  create bind listen accept connect shutdown getattr setattr getopt setopt
  send receive r w
);

my %FILE_OPERATION = map { $_ => 1 } qw(
  chmod chown create file_inherit file_mmap file_perm getattr inode_permission
  mkdir mknod mmap open readlink rename_dest rename_src rmdir setattr
  truncate unlink
);

sub render {
    my ($self, $record) = @_;

    my $fields = $record->{fields};
    my $operation = lc($fields->{operation} // q{});
    my $class = lc($fields->{class} // q{});

    return $self->_render_capability($fields)
        if $operation eq 'capable' ||
            $class eq 'cap' ||
            $class eq 'capability';
    return $self->_render_network($fields)
        if $class eq 'net' ||
            $class eq 'network' ||
            defined($fields->{family}) ||
            (
            defined($fields->{sock_type}) &&
                $operation =~
                /\A(?:accept|bind|connect|create|listen|recvmsg|receive|send|sendmsg|shutdown|socket_create)\z/
            );
    return $self->_render_file($fields)
        if $class eq q{} ||
            $class eq 'file';
    return {
        ok     => 0,
        reason => "unsupported AppArmor class: $class",
    };
}

sub _render_capability {
    my ($self, $fields) = @_;

    my $capability = lc($fields->{capname} // $fields->{name} // q{});
    $capability =~ s/\ACAP_//i;
    $capability =~ /\A[a-z][a-z0-9_]{0,63}\z/ &&
        $CAPABILITY{$capability}
        or return {
            ok     => 0,
            reason => 'missing or unsupported capability name',
        };
    if (!$AUTOMATIC_CAPABILITY{$capability} &&
        !$self->allow_high_risk_capabilities()) {
        return {
            ok     => 0,
            reason => "high-risk capability requires manual review: $capability",
        };
    }
    return {
        kind => 'capability',
        ok   => 1,
        rule => "capability $capability,",
    };
}

sub _render_network {
    my ($self, $fields) = @_;

    my $family = lc($fields->{family} // q{});
    $family =~ s/\AAF_//i;
    $family =~ s/\Apf_//i;
    $family eq 'local' and $family = 'unix';
    $family = $NUMERIC_NETWORK_FAMILY{$family}
        if exists $NUMERIC_NETWORK_FAMILY{$family};
    $NETWORK_FAMILY{$family}
        or return {
            ok     => 0,
            reason => 'missing or unsupported network family',
        };
    $AUTOMATIC_NETWORK_FAMILY{$family}
        or return {
            ok     => 0,
            reason => "network family requires manual review: $family",
        };

    my $socket_type = lc($fields->{sock_type} // $fields->{type} // q{});
    $socket_type =~ s/\ASOCK_//i;
    $socket_type = $NUMERIC_SOCKET_TYPE{$socket_type}
        if exists $NUMERIC_SOCKET_TYPE{$socket_type};
    $SOCKET_TYPE{$socket_type}
        or return {
            ok     => 0,
            reason => 'missing or unsupported network socket type',
        };

    my ($protocol, $protocol_error) =
        $self->_network_protocol($fields->{protocol});
    defined($protocol_error)
        and return {
            ok     => 0,
            reason => $protocol_error,
        };
    if (defined($protocol) &&
        !$self->_network_protocol_matches_type($protocol, $socket_type)) {
        return {
            ok     => 0,
            reason => "network protocol $protocol is incompatible with socket type $socket_type",
        };
    }
    my $kind = defined($protocol) ? $protocol : $socket_type;
    my ($access, $access_error) =
        $self->_network_access($fields->{denied_mask}, $fields->{operation});
    defined($access)
        or return {
            ok     => 0,
            reason => $access_error,
        };
    if (defined($fields->{requested_mask}) &&
        $fields->{requested_mask} ne q{}) {
        my ($requested, $requested_error) =
            $self->_network_access(
                $fields->{requested_mask},
                $fields->{operation},
            );
        defined($requested)
            or return {
                ok     => 0,
                reason => "unsupported requested network mask: $requested_error",
            };
        $self->_network_access_contains($requested, $access)
            or return {
                ok     => 0,
                reason => 'denied network mask is not a subset of the requested mask',
            };
    }
    my $rendered_access = @{$access} == 1
        ? $access->[0]
        : '(' . join(', ', @{$access}) . ')';
    return {
        kind => 'network',
        ok   => 1,
        rule => "network $rendered_access $family $kind,",
    };
}

sub _network_protocol {
    my ($self, $value) = @_;

    return (undef, undef)
        if !defined($value) || $value eq q{} || $value eq '0';
    my %numeric = (
        1  => 'icmp',
        6  => 'tcp',
        17 => 'udp',
        58 => 'icmp',
    );
    return ($numeric{$value}, undef) if exists $numeric{$value};
    $value = lc($value);
    $value =~ s/\AIPPROTO_//i;
    return ($value, undef) if $value =~ /\A(?:tcp|udp|icmp)\z/;
    return (undef, "unsupported network protocol: $value");
}

sub _network_protocol_matches_type {
    my ($self, $protocol, $socket_type) = @_;

    return $socket_type eq 'stream' if $protocol eq 'tcp';
    return $socket_type eq 'dgram' if $protocol eq 'udp';
    return $socket_type eq 'raw' || $socket_type eq 'dgram'
        if $protocol eq 'icmp';
    return 0;
}

sub _network_access {
    my ($self, $mask, $operation) = @_;

    $mask = lc($mask // q{});
    my @tokens = grep { $_ ne q{} } split /[\s,]+/, $mask;
    if (!@tokens) {
        my %operation_access = (
            accept        => 'accept',
            bind          => 'bind',
            connect       => 'connect',
            create        => 'create',
            listen        => 'listen',
            recvmsg       => 'receive',
            receive       => 'receive',
            send          => 'send',
            sendmsg       => 'send',
            shutdown      => 'shutdown',
            socket_create => 'create',
        );
        $operation = lc($operation // q{});
        push @tokens, $operation_access{$operation}
            if exists $operation_access{$operation};
    }

    my %normalized;
    for my $token (@tokens) {
        $token eq 'recv' and $token = 'receive';
        $token eq 'write' and $token = 'w';
        $token eq 'read' and $token = 'r';
        if ($token eq 'rw') {
            $normalized{r} = 1;
            $normalized{w} = 1;
            next;
        }
        $NETWORK_ACCESS{$token}
            or return (
                undef,
                "missing or unsupported network access mask: $mask",
            );
        $normalized{$token} = 1;
    }
    keys(%normalized)
        or return (undef, 'missing or unsupported network access mask');
    my @order = qw(create bind listen accept connect shutdown getattr setattr getopt setopt send receive r w);
    return ([grep { $normalized{$_} } @order], undef);
}

sub _network_access_contains {
    my ($self, $requested, $denied) = @_;

    my %requested = map { $_ => 1 } @{$requested};
    return !grep { !$requested{$_} } @{$denied};
}

sub _render_file {
    my ($self, $fields) = @_;

    my $operation = lc($fields->{operation} // q{});
    $FILE_OPERATION{$operation}
        or return {
            ok     => 0,
            reason => "unsupported or unsafe file operation: $operation",
        };
    my $path = $fields->{name} // q{};
    $self->_safe_absolute_path($path)
        or return {
            ok     => 0,
            reason => 'file denial does not contain a safe absolute path',
        };

    my ($permissions, $permission_error) =
        $self->_file_permissions($fields->{denied_mask});
    defined($permissions)
        or return {
            ok     => 0,
            reason => $permission_error,
        };
    if (defined($fields->{requested_mask}) &&
        $fields->{requested_mask} ne q{}) {
        my ($requested) = $self->_file_permissions($fields->{requested_mask});
        defined($requested) &&
            $self->_permissions_contain($requested, $permissions)
            or return {
                ok     => 0,
                reason => 'denied file mask is not a subset of the requested mask',
            };
    }

    my $owner = defined($fields->{fsuid}) &&
        defined($fields->{ouid}) &&
        $fields->{fsuid} eq $fields->{ouid};
    $self->_file_path_allowed($path, $permissions, $owner)
        or return {
            ok     => 0,
            reason => 'file path or permission requires manual security review',
        };
    my $expression = $self->_path_expression($path, $owner);
    defined($expression)
        or return {
            ok     => 0,
            reason => 'file path cannot be rendered safely',
        };

    return {
        kind => 'file',
        ok   => 1,
        rule => ($owner ? 'owner ' : q{}) . "$expression $permissions,",
    };
}

sub _file_permissions {
    my ($self, $mask) = @_;

    defined($mask) && $mask ne q{}
        or return (undef, 'missing file denied mask');
    (my $compact = lc($mask)) =~ s/[\s,]+//g;
    $compact ne q{}
        or return (undef, 'missing file denied mask');
    my %permissions;
    for my $character (split //, $compact) {
        if ($character eq 'c' || $character eq 'd') {
            $permissions{w} = 1;
            next;
        }
        $character =~ /\A[rawkml]\z/
            or return (
                undef,
                "unsupported or unsafe file denied mask: $mask",
            );
        $permissions{$character} = 1;
    }
    $permissions{w} and delete $permissions{a};
    $permissions{l}
        and return (
            undef,
            'link permission requires a reviewed source and target pair',
        );
    my $rendered = join q{}, grep { $permissions{$_} } qw(r w a k m);
    return length($rendered)
        ? ($rendered, undef)
        : (undef, 'file denied mask produced no supported permissions');
}

sub _permissions_contain {
    my ($self, $requested, $denied) = @_;

    my %requested = map { $_ => 1 } split //, $requested;
    $requested{w} and $requested{a} = 1;
    return !grep { !$requested{$_} } split //, $denied;
}

sub _safe_absolute_path {
    my ($self, $path) = @_;

    return defined($path) &&
        $path =~ m{\A/} &&
        $path ne '/' &&
        length($path) <= 4_096 &&
        index($path, "\0") < 0 &&
        $path !~ /[\r\n\x7f]/ &&
        $path !~ m{//} &&
        $path !~ m{(?:\A|/)[.]{1,2}(?:/|\z)};
}

sub _file_path_allowed {
    my ($self, $path, $permissions, $owner) = @_;

    my $writes = $permissions =~ /[wa]/;
    return 0 if $path =~ m{\A/(?:dev/(?:kmem|mem|port)|proc/kcore)(?:/|\z)};
    return 0 if $path =~ m{\A/etc/(?:gshadow|shadow|sudoers)(?:[./]|\z)};
    return 0
        if $path =~
        m{\A/etc/(?:crypttab|NetworkManager/system-connections|ssh/ssh_host_[^/]*_key|ssl/private)(?:/|\z)};
    return 0 if $path =~ m{\A/(?:etc/apparmor(?:[.]d)?|sys/kernel/security)(?:/|\z)};
    return 0 if $path =~ m{\A/(?:root|run/(?:credentials|secrets)|var/lib/private)(?:/|\z)};
    return 0 if $path =~ m{\A/home/[^/]+/(?:[.]gnupg|[.]password-store|[.]ssh|[.]local/share/keyrings)(?:/|\z)};
    return 0 if $path =~ m{\A/proc/[0-9]+(?:/|\z)} && !$owner;
    if ($writes) {
        return 0 if $path =~ m{\A/(?:boot|dev|etc|proc|root|sys|usr)(?:/|\z)};
        return 0 if $path =~ m{\A/proc/sys(?:/|\z)};
        return 0 if $path =~ m{\A/var/lib/(?:polkit|systemd)(?:/|\z)};
        return 0 if $path =~ m{\A/home/} && !$owner;
        return 0 if $path =~ m{\A/run/user/} && !$owner;
    }
    return 1;
}

sub _path_expression {
    my ($self, $path, $owner) = @_;

    if ($self->path_globbing() eq 'conservative') {
        if ($owner && $path =~ m{\A/home/[^/]+(?<suffix>/.*|\z)}) {
            my $suffix = $+{suffix};
            return $self->_variable_path('@{HOME}', $suffix);
        }
        if ($owner && $path =~ m{\A/run/user/[0-9]+(?<suffix>/.*|\z)}) {
            my $suffix = $+{suffix};
            return $self->_pattern_path('/run/user/[0-9]*', $suffix);
        }
        if ($owner && $path =~ m{\A/proc/[0-9]+(?<suffix>/.*|\z)}) {
            my $suffix = $+{suffix};
            return $self->_pattern_path('/proc/[0-9]*', $suffix);
        }
    }
    return $self->_quoted_literal($path);
}

sub _variable_path {
    my ($self, $prefix, $suffix) = @_;

    return undef if $suffix !~ /\A(?:\/[A-Za-z0-9._+,:=@% -]+)*\/?\z/;
    return $prefix . $self->_escape_literal_suffix($suffix);
}

sub _pattern_path {
    my ($self, $prefix, $suffix) = @_;

    return undef if $suffix !~ /\A(?:\/[A-Za-z0-9._+,:=@% -]+)*\/?\z/;
    return $prefix . $self->_escape_literal_suffix($suffix);
}

sub _escape_literal_suffix {
    my ($self, $suffix) = @_;

    $suffix =~ s/\\/\\\\/g;
    $suffix =~ s/([?*\[\]{}^])/\\$1/g;
    $suffix =~ s/,/\\,/g;
    $suffix =~ s/ /\\ /g;
    return $suffix;
}

sub _quoted_literal {
    my ($self, $path) = @_;

    $path =~ s/\\/\\\\/g;
    $path =~ s/"/\\"/g;
    $path =~ s/([?*\[\]{}^])/\\$1/g;
    return qq{"$path"};
}

1;
