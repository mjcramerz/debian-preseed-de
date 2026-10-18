package FilenSync::Config;
use strict;
use warnings;
use Moo;
use MooX::StrictConstructor;
use Fcntl qw(O_RDONLY O_NOFOLLOW O_NONBLOCK S_ISREG S_ISDIR);
use JSON::PP qw(decode_json);

has account => (is => 'ro', required => 1);

sub read_file {
    my ($self, $path, $private) = @_;
    sysopen(my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK) or die "input unavailable\n";
    binmode $fh, ':raw' or die "cannot set input encoding\n";
    my @info = stat $fh;
    @info && S_ISREG($info[2]) && $info[3] == 1
        && ($private ? ($info[4] == 0 || $info[4] == $>) : $info[4] == 0)
        && !($info[2] & ($private ? 0077 : 0022)) && $info[7] <= 8192
        or die "untrusted input\n";
    my $data = q{};
    while (1) {
        my $size = sysread($fh, my $chunk, 8193 - length($data));
        defined $size or die "input read failed\n";
        last if !$size;
        $data .= $chunk;
        length($data) <= 8192 or die "input exceeds limit\n";
    }
    close $fh or die "input close failed\n";
    return $data;
}

sub settings {
    my ($self) = @_;
    my $account = $self->account;
    $account =~ /\A(?:private|offsec)\z/ or die "invalid account\n";
    for my $parent ('/etc', '/etc/filen') {
        my @info = lstat $parent;
        @info && S_ISDIR($info[2]) && $info[4] == 0 && !($info[2] & 0022)
            or die "untrusted configuration parent\n";
    }
    my $config = decode_json($self->read_file('/etc/filen/' . $account . '.json', 0));
    ref($config) eq 'HASH' && keys(%{$config}) == 5
        && ($config->{version} // 0) == 1 && ($config->{account} // q{}) eq $account
        && !ref($config->{local}) && !ref($config->{remote}) && !ref($config->{sync_mode})
        or die "invalid configuration\n";
    ($config->{local} // q{}) =~ m{\A(/(?:[A-Za-z0-9_.-]+/)+filen-\Q$account\E)\z}
        or die "invalid sync directory\n";
    my $local = $1;
    !grep { $_ eq '.' || $_ eq '..' } split m{/}, $local or die "invalid sync directory\n";
    ($config->{sync_mode} // q{}) =~ /\A(twoWay|localToCloud|cloudToLocal|localBackup|cloudBackup)\z/
        or die "invalid sync mode\n";
    my $mode = $1;
    my $remote = $config->{remote} // q{};
    length($remote) && length($remote) <= 2048 && $remote =~ m{\A/} && $remote !~ /[\x00-\x1f\x7f]/
        && ($remote eq '/' || !grep { $_ eq q{} || $_ eq '.' || $_ eq '..' } split(m{/}, substr($remote, 1), -1))
        or die "invalid remote directory\n";
    my @identity = getpwnam('filen-' . $account);
    @identity && $> == $identity[2] && $> != 0 or die "incorrect service identity\n";
    my @info = lstat $local;
    @info && S_ISDIR($info[2]) && $info[4] == $> && $info[5] == $identity[3]
        && !($info[2] & 0007) or die "incorrect sync directory identity\n";
    my $registry = decode_json($self->read_file('/etc/filen/' . $account . '.sync.json', 0));
    ref($registry) eq 'ARRAY' && @{$registry} == 1 && ref($registry->[0]) eq 'HASH'
        && ($registry->[0]{local} // q{}) eq $local && ($registry->[0]{remote} // q{}) eq $remote
        && ($registry->[0]{syncMode} // q{}) eq $mode
        && !$registry->[0]{disableLocalTrash} && !$registry->[0]{excludeDotFiles}
        or die "sync registry differs from configuration\n";
    return {account => $account, local => $local, remote => $remote, mode => $mode};
}

sub credentials {
    my ($self) = @_;
    my $account = $self->account;
    my $root = '/run/credentials/filen-sync@' . $account . '.service';
    ($ENV{CREDENTIALS_DIRECTORY} // q{}) eq $root or die "service credentials unavailable\n";
    my %values = map { $_ => $self->read_file($root . '/' . $_, 1) } qw(email password seed);
    for my $field (keys %values) {
        length($values{$field}) && $values{$field} !~ /[\x00\r\n]/ or die "invalid credential input\n";
    }
    $values{seed} =~ /\A[A-Z2-7]{16,1024}={0,6}\z/ or die "invalid TOTP seed\n";
    return \%values;
}

1;
