package WhisperMode::State;

use strict;
use warnings;

use Fcntl qw(:flock F_SETFD FD_CLOEXEC O_CREAT O_NOFOLLOW O_RDWR O_RDONLY O_NONBLOCK);
use IO::Handle ();
use Errno qw(EINTR);
use File::Temp qw(tempfile);
use JSON::PP qw(decode_json encode_json);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Str);

has runtime_directory => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    builder => '_build_runtime_directory',
);

sub _fatal {
    my ($message) = @_;
    die "whisper-record-toggle: $message\n";
}

sub _build_runtime_directory {
    $< != 0 or _fatal('must not run as root');
    my $path = $ENV{XDG_RUNTIME_DIR};
    defined($path) && $path eq '/run/user/' . $<
        or _fatal('XDG_RUNTIME_DIR is invalid');
    -d $path && !-l $path or _fatal('XDG_RUNTIME_DIR must be a real directory');
    my @stat = lstat $path;
    $stat[4] == $< && ($stat[2] & 0077) == 0
        or _fatal('XDG_RUNTIME_DIR ownership or mode is unsafe');
    return $path;
}

sub _path {
    my ($self, $name) = @_;
    $name =~ /\A(?:whisper-record-toggle\.(?:lock|recording|state)|\.whisper-[0-9-]+-[0-9]+\.json)\z/
        or _fatal('unsafe managed runtime file name');
    return $self->runtime_directory() . "/$name";
}

sub lock {
    my ($self, $recording, $nonblocking) = @_;
    my $name = $recording ? 'whisper-record-toggle.recording' : 'whisper-record-toggle.lock';
    my $path = $self->_path($name);
    if (-e $path || -l $path) {
        -f $path && !-l $path or _fatal("runtime lock is unsafe: $path");
        (lstat $path)[4] == $< or _fatal("runtime lock ownership is unsafe: $path");
    }
    sysopen my $fh, $path, O_CREAT | O_NOFOLLOW | O_RDWR, 0600
        or _fatal("cannot open runtime lock: $!");
    my @opened = stat $fh;
    @opened && -f $fh && $opened[4] == $< && $opened[3] == 1 && ($opened[2] & 0077) == 0
        or _fatal('runtime lock ownership, type, link count or mode is unsafe');
    fcntl($fh, F_SETFD, $recording ? 0 : FD_CLOEXEC)
        or _fatal("cannot configure runtime lock: $!");
    my $mode = LOCK_EX | ($nonblocking ? LOCK_NB : 0);
    if (!flock($fh, $mode)) {
        return undef if $nonblocking && ($!{EAGAIN} || $!{EWOULDBLOCK});
        _fatal("cannot lock runtime state: $!");
    }
    return $fh;
}

sub _state_path {
    my ($self) = @_;
    return $self->_path('whisper-record-toggle.state');
}

sub read {
    my ($self) = @_;
    my $path = $self->_state_path();
    return undef if !-e $path && !-l $path;
    -f $path && !-l $path or _fatal('runtime state is not a regular file');
    (lstat $path)[4] == $< or _fatal('runtime state ownership is unsafe');
    -s $path <= 32 * 1024 or _fatal('runtime state is too large');
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK or _fatal("cannot read runtime state: $!");
    my @opened = stat $fh;
    -f $fh && $opened[4] == $< && $opened[3] == 1 && ($opened[2] & 0077) == 0
        or _fatal('opened runtime state is unsafe');
    my $raw = q{};
    while (1) {
        my $n = sysread($fh, my $chunk, 32769 - length($raw));
        if (!defined $n) { next if $! == EINTR; _fatal("cannot read runtime state: $!"); }
        last if !$n;
        $raw .= $chunk;
        length($raw) <= 32768 or _fatal('runtime state is too large');
    }
    close $fh or _fatal("cannot close runtime state: $!");
    my $state = eval { decode_json($raw) };
    !$@ && ref($state) eq 'HASH' or _fatal('runtime state is not valid JSON');
    for my $key (qw(stem wav)) {
        defined($state->{$key}) && !ref($state->{$key}) or _fatal("runtime state is missing $key");
    }
    $state->{stem} =~ /\A[0-9]{4}(?:-[0-9]{2}){5}\z/
        or _fatal('runtime state has an invalid timestamp stem');
    $state->{wav} =~ m{\A/} && $state->{wav} !~ m{\0|(?:\A|/)\.\.(?:/|\z)|//}
        or _fatal('runtime state has an invalid recording path');
    for my $key (keys %{$state}) {
        $key =~ /\A(?:stem|wav|source_id|source_name)\z/
            or _fatal('runtime state contains an unsupported field');
    }
    if (exists($state->{source_id}) || exists($state->{source_name})) {
        defined($state->{source_id}) && !ref($state->{source_id})
            && $state->{source_id} =~ /\A[1-9][0-9]{0,9}\z/
            && defined($state->{source_name}) && !ref($state->{source_name})
            && length($state->{source_name}) <= 1024
            && $state->{source_name} =~ /\A[^\x00-\x20\x7f]+\z/
            or _fatal('runtime state has an invalid capture source');
    }
    return $state;
}

sub write {
    my ($self, $state) = @_;
    ref($state) eq 'HASH' or _fatal('runtime state must be a hash');
    my $json = encode_json($state) . "\n";
    length($json) <= 32768 or _fatal('runtime state is too large');
    my ($fh, $temporary) = tempfile('.whisper-state.XXXXXX', DIR => $self->runtime_directory(), UNLINK => 1);
    my $ok = eval {
        binmode $fh, ':raw' or _fatal("cannot set state encoding: $!");
        print {$fh} $json or _fatal("cannot write runtime state: $!");
        $fh->flush && $fh->sync or _fatal("cannot flush runtime state: $!");
        close $fh or _fatal("cannot close runtime state: $!");
        rename $temporary, $self->_state_path() or _fatal("cannot publish runtime state: $!");
        1;
    };
    my $error = $@;
    unlink $temporary if -e $temporary;
    die $error if !$ok;
    return;
}

sub clear {
    my ($self) = @_;
    my $path = $self->_state_path();
    return if !-e $path && !-l $path;
    -f $path && !-l $path && (lstat $path)[4] == $<
        or _fatal('runtime state is unsafe to remove');
    unlink $path or _fatal("cannot clear runtime state: $!");
}

1;
