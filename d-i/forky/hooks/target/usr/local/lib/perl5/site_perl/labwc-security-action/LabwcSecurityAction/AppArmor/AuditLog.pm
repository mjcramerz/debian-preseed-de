package LabwcSecurityAction::AppArmor::AuditLog;

use strict;
use warnings;

use Fcntl qw(O_NOFOLLOW O_RDONLY);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Int);

has maximum_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 16_777_216 },
);

has maximum_line_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 65_536 },
);

has maximum_records => (
    is      => 'ro',
    isa     => Int,
    default => sub { 20_000 },
);

has maximum_unique_records => (
    is      => 'ro',
    isa     => Int,
    default => sub { 4_096 },
);

has trusted_uid => (
    is      => 'ro',
    isa     => Int,
    default => sub { 0 },
);

sub read_denials {
    my ($self, $path) = @_;

    my $path_metadata = $self->_validate_log($path);
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW
        or die "cannot read managed AppArmor event log: $path: $!\n";
    binmode $fh, ':raw'
        or die "cannot read managed AppArmor event log: $path: $!\n";
    my @opened_metadata = stat($fh);
    $self->_validate_log_metadata(\@opened_metadata, $path);
    $opened_metadata[0] == $path_metadata->[0] &&
        $opened_metadata[1] == $path_metadata->[1]
        or die "managed AppArmor event log changed while it was being opened: $path\n";

    my (@records, @rejected);
    my %by_signature;
    my ($bytes_read, $denial_count, $line_number) = (0, 0, 0);
    while (my $line = <$fh>) {
        ++$line_number;
        $bytes_read += length($line);
        $bytes_read <= $self->maximum_bytes()
            or die "managed AppArmor event log exceeds "
                . $self->maximum_bytes() . " bytes while being read: $path\n";
        length($line) <= $self->maximum_line_bytes()
            or die "managed AppArmor event log line $line_number exceeds "
                . $self->maximum_line_bytes() . " bytes\n";
        next if index($line, 'apparmor="DENIED"') < 0;

        ++$denial_count;
        $denial_count <= $self->maximum_records()
            or die "managed AppArmor event log contains more than "
                . $self->maximum_records() . " denied records\n";

        my $record = eval { $self->_parse_denial($line, $line_number) };
        if (!$record) {
            my $error = $@ || 'unparseable AppArmor denial';
            $error =~ s/\s+\z//;
            push @rejected, {
                line_number => $line_number,
                profile     => 'unknown',
                reason      => $error,
            };
            next;
        }

        my $signature = $self->_signature($record->{fields});
        if (my $existing = $by_signature{$signature}) {
            ++$existing->{count};
            push @{ $existing->{line_numbers} }, $line_number
                if @{ $existing->{line_numbers} } < 16;
            next;
        }

        @records < $self->maximum_unique_records()
            or die "managed AppArmor event log contains more than "
                . $self->maximum_unique_records() . " unique denied records\n";
        $record->{count} = 1;
        $record->{line_numbers} = [$line_number];
        $by_signature{$signature} = $record;
        push @records, $record;
    }
    close $fh
        or die "cannot close managed AppArmor event log: $path: $!\n";

    $denial_count
        or die "managed AppArmor event log contains no DENIED records\n";
    return (\@records, \@rejected);
}

sub _validate_log {
    my ($self, $path) = @_;

    defined($path) && $path =~ m{\A/} && $path ne '/' &&
        index($path, "\0") < 0 && $path !~ /[\r\n]/
        or die "managed AppArmor event log path must be a safe absolute path\n";
    my @metadata = lstat($path);
    !-l $path
        or die "managed AppArmor event log must be a regular non-symlink file: $path\n";
    $self->_validate_log_metadata(\@metadata, $path);
    return \@metadata;
}

sub _validate_log_metadata {
    my ($self, $metadata, $path) = @_;

    @{$metadata} && ($metadata->[2] & 0170000) == 0100000
        or die "managed AppArmor event log must be a regular non-symlink file: $path\n";
    $metadata->[4] == $self->trusted_uid()
        or die "managed AppArmor event log must be owned by the trusted account: $path\n";
    ($metadata->[2] & 0022) == 0
        or die "managed AppArmor event log must not be group- or world-writable: $path\n";
    $metadata->[7] <= $self->maximum_bytes()
        or die "managed AppArmor event log exceeds " . $self->maximum_bytes()
            . " bytes: $path\n";
    return;
}

sub _parse_denial {
    my ($self, $line, $line_number) = @_;

    my %fields;
    while ($line =~ /(?:\A|[[:space:]])([A-Za-z_][A-Za-z0-9_]*)=(?:"((?:\\.|[^"\\])*)"|([^[:space:]\x1d]+))/g) {
        my ($key, $quoted, $bare) = ($1, $2, $3);
        exists $fields{$key}
            and die "AppArmor denial line $line_number repeats field: $key\n";
        my $value = defined($quoted)
            ? $self->_decode_quoted($quoted, $line_number, $key)
            : $bare;
        $fields{$key} = $self->_decode_audit_hex($key, $value);
    }

    ($fields{apparmor} // q{}) eq 'DENIED'
        or die "AppArmor denial line $line_number is missing apparmor=DENIED\n";
    $self->_alias_numeric_field(\%fields, 'fsuid', 'FSUID', $line_number);
    $self->_alias_numeric_field(\%fields, 'ouid', 'OUID', $line_number);
    $self->_alias_text_field(
        \%fields,
        'requested_mask',
        'requested',
        $line_number,
    );
    $self->_alias_text_field(
        \%fields,
        'denied_mask',
        'denied',
        $line_number,
    );

    for my $required (qw(profile operation)) {
        defined($fields{$required}) && $fields{$required} ne q{}
            or die "AppArmor denial line $line_number is missing field: $required\n";
    }
    length($fields{profile}) <= 1_024 &&
        $fields{profile} !~ /[\x00-\x1f\x7f]/
        or die "AppArmor denial line $line_number has an invalid profile field\n";
    $fields{operation} =~ /\A[A-Za-z0-9_+-]{1,64}\z/
        or die "AppArmor denial line $line_number has an invalid operation field\n";
    if (defined($fields{class})) {
        $fields{class} =~ /\A[A-Za-z0-9_+-]{1,64}\z/
            or die "AppArmor denial line $line_number has an invalid class field\n";
    }
    for my $mask_name (qw(requested_mask denied_mask)) {
        next if !defined($fields{$mask_name});
        length($fields{$mask_name}) <= 128 &&
            $fields{$mask_name} !~ /[\x00-\x1f\x7f]/
            or die "AppArmor denial line $line_number has an invalid $mask_name field\n";
    }
    for my $uid_name (qw(fsuid ouid)) {
        next if !defined($fields{$uid_name});
        $fields{$uid_name} =~ /\A[0-9]{1,10}\z/
            or die "AppArmor denial line $line_number has an invalid $uid_name field\n";
    }
    for my $path_name (qw(name target)) {
        next if !defined($fields{$path_name});
        length($fields{$path_name}) <= 4_096 &&
            $fields{$path_name} !~ /[\x00-\x1f\x7f]/
            or die "AppArmor denial line $line_number has an invalid $path_name field\n";
    }

    return {
        fields      => \%fields,
        line_number => $line_number,
    };
}

sub _alias_numeric_field {
    my ($self, $fields, $canonical, $legacy, $line_number) = @_;

    return if !exists($fields->{$legacy});
    if (exists($fields->{$canonical}) &&
        $fields->{$canonical} ne $fields->{$legacy}) {
        die "AppArmor denial line $line_number has conflicting $canonical fields\n";
    }
    $fields->{$canonical} = delete $fields->{$legacy};
    return;
}

sub _alias_text_field {
    my ($self, $fields, $canonical, $alternate, $line_number) = @_;

    return if !exists($fields->{$alternate});
    if (exists($fields->{$canonical}) &&
        $fields->{$canonical} ne $fields->{$alternate}) {
        die "AppArmor denial line $line_number has conflicting $canonical fields\n";
    }
    $fields->{$canonical} = delete $fields->{$alternate};
    return;
}

sub _decode_quoted {
    my ($self, $value, $line_number, $field) = @_;

    my $decoded = q{};
    while (length($value)) {
        if ($value =~ s/\A([^\\]+)//s) {
            $decoded .= $1;
            next;
        }
        if ($value =~ s/\A\\x([0-9A-Fa-f]{2})//) {
            $decoded .= chr(hex($1));
            next;
        }
        if ($value =~ s/\A\\([0-7]{3})//) {
            $decoded .= chr(oct($1));
            next;
        }
        if ($value =~ s/\A\\([\\"])//) {
            $decoded .= $1;
            next;
        }
        die "AppArmor denial line $line_number has an unsupported escape in field $field\n";
    }
    $decoded !~ /[\x00\r\n]/
        or die "AppArmor denial line $line_number contains a control character in field $field\n";
    return $decoded;
}

sub _decode_audit_hex {
    my ($self, $key, $value) = @_;

    return $value
        if $key !~ /\A(?:name|target|profile|peer|peer_profile|comm)\z/;
    return $value
        if length($value) < 2 || length($value) % 2 ||
            $value !~ /\A[0-9A-Fa-f]+\z/;
    my $decoded = pack('H*', $value);
    return $value if $decoded =~ /[\x00\r\n]/;
    return $decoded
        if $decoded =~ m{\A/} ||
            $decoded =~ /\A[A-Za-z0-9_.:+@%\/-]+\z/;
    return $value;
}

sub _signature {
    my ($self, $fields) = @_;

    return join "\x1f", map {
        defined($fields->{$_}) ? $fields->{$_} : q{}
    } qw(
      profile operation class name target requested_mask denied_mask
      fsuid ouid capname family sock_type protocol peer peer_profile
      signal bus path interface member
    );
}

1;
