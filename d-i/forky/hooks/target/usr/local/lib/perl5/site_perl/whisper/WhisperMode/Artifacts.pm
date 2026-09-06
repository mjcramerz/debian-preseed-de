package WhisperMode::Artifacts;

use strict;
use warnings;

use Fcntl qw(:flock O_APPEND O_CREAT O_NOFOLLOW O_RDWR O_WRONLY O_RDONLY O_NONBLOCK O_EXCL F_SETFD FD_CLOEXEC);
use IO::Handle ();
use Encode qw(encode);
use Errno qw(EINTR);
use File::Path qw(make_path);
use File::Spec;
use File::Temp qw(tempfile);
use JSON::PP qw(decode_json encode_json);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Int Str);

has home => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    builder => '_build_home',
);
has max_artifacts => ( is => 'ro', isa => Int, default => sub { 20 } );

sub _fatal {
    my ($message) = @_;
    die "whisper-record-toggle: $message\n";
}

sub _build_home {
    my $path = $ENV{HOME};
    defined($path) && $path =~ m{\A/} && $path !~ m{\0|(?:\A|/)\.\.(?:/|\z)|//}
        or _fatal('HOME is invalid');
    -d $path && !-l $path && (lstat $path)[4] == $<
        or _fatal('HOME must be a user-owned real directory');
    return $path;
}

sub _directory {
    my ($self, $label, $path) = @_;
    # Validate each component below HOME before mkdir, not merely the leaf.
    index($path, $self->home() . '/') == 0 or _fatal("$label escaped HOME");
    my $current = $self->home();
    for my $part (split m{/}, substr($path, length($current) + 1)) {
        $part ne q{} && $part ne '.' && $part ne '..' or _fatal('unsafe directory component');
        $current .= "/$part";
        if (!-e $current && !-l $current) {
            mkdir($current, 0700) or $!{EEXIST} or _fatal("cannot create $label: $!");
        }
        -d $current && !-l $current && (lstat $current)[4] == $<
            or _fatal("$label has an unsafe directory component");
    }
    if (!-e $path) {
        make_path($path, { mode => 0700 }) or _fatal("cannot create $label");
    }
    -d $path && !-l $path && (lstat $path)[4] == $<
        or _fatal("$label must be a user-owned real directory");
    chmod 0700, $path or _fatal("cannot secure $label: $!");
    return $path;
}

sub paths {
    my ($self) = @_;
    my $root = $self->_directory('Whisper root directory', File::Spec->catdir($self->home(), 'Music', 'Whisper'));
    return {
        audio       => $self->_directory('Whisper audio directory', File::Spec->catdir($root, 'audio')),
        transcribed => $self->_directory('Whisper transcription directory', File::Spec->catdir($root, 'transcribed')),
    };
}

sub sleek {
    my ($self) = @_;
    my $directory = $self->_directory('Sleek task directory', File::Spec->catdir($self->home(), 'Syncthing', 'sleek'));
    my $file = "$directory/whisper.txt";
    if (-e $file || -l $file) {
        -f $file && !-l $file && (lstat $file)[4] == $< && (lstat $file)[3] == 1
            or _fatal('Sleek task file is unsafe');
    } else {
        if (sysopen my $new, $file, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600) {
            close $new or _fatal("cannot close new Sleek task file: $!");
        } else { $!{EEXIST} or _fatal("cannot create Sleek task file: $!"); }
    }
    chmod 0600, $file or _fatal("cannot secure Sleek task file: $!");
    return { directory => $directory, task_file => $file };
}

sub validate_wav {
    my ($self, $state) = @_;
    my $paths = $self->paths();
    my $expected = "$paths->{audio}/$state->{stem}.wav";
    $state->{wav} eq $expected or _fatal('runtime state recording escaped the managed audio directory');
    if (-e $expected || -l $expected) {
        -f $expected && !-l $expected && (lstat $expected)[4] == $< && (lstat $expected)[3] == 1
            or _fatal('recording file is unsafe');
    }
    return $expected;
}

sub _atomic_write {
    my ($self, $directory, $name, $content) = @_;
    $name =~ /\A[0-9A-Za-z._-]+\z/ && $name ne '.' && $name ne '..'
        or _fatal('unsafe artifact name');
    my ($fh, $temporary) = tempfile(".$name.XXXXXX", DIR => $directory, UNLINK => 1);
    my $ok = eval {
        binmode $fh, ':raw' or _fatal("cannot set artifact encoding: $!");
        print {$fh} $content or _fatal("cannot write temporary artifact: $!");
        $fh->flush && $fh->sync or _fatal("cannot flush artifact: $!");
        close $fh or _fatal("cannot close temporary artifact: $!");
        rename $temporary, "$directory/$name" or _fatal("cannot publish artifact: $!");
        1;
    };
    my $error = $@;
    unlink $temporary if -e $temporary;
    die $error if !$ok;
    return;
}

sub _validated_stem {
    my ($stem) = @_;
    defined($stem) && $stem =~ /\A[0-9]{4}(?:-[0-9]{2}){5}\z/
        or _fatal('Whisper artifact stem is invalid');
    return $stem;
}

sub _normalized_task_text {
    my ($text) = @_;
    $text //= q{};
    $text =~ s/[\p{Cc}\p{Cf}]+/ /gu;
    $text =~ s/\s+/ /gu;
    $text =~ s/\A\s+|\s+\z//gu;
    return $text;
}

sub store_transcript {
    my ($self, $stem, $text) = @_;
    $stem = _validated_stem($stem);
    $text = _normalized_task_text($text);
    my $paths = $self->paths();
    $self->_atomic_write($paths->{transcribed}, "$stem.json", encode_json({ text => $text }) . "\n");
}

sub append_task {
    my ($self, $stem, $text) = @_;
    $stem = _validated_stem($stem);
    $text = _normalized_task_text($text);
    return if !length $text;
    my $sleek = $self->sleek();
    sysopen my $lock, "$sleek->{directory}/.whisper.txt.lock", O_CREAT | O_NOFOLLOW | O_RDWR, 0600
        or _fatal("cannot open Sleek task lock: $!");
    my @ls = stat $lock;
    -f $lock && $ls[4] == $< && $ls[3] == 1 && ($ls[2] & 0077) == 0
        or _fatal('Sleek lock is unsafe');
    fcntl($lock, F_SETFD, FD_CLOEXEC) or _fatal("cannot configure Sleek lock: $!");
    # Non-blocking: preserve pending state and let the caller retry, rather
    # than wedging a service indefinitely behind another process.
    flock($lock, LOCK_EX | LOCK_NB) or _fatal('Sleek task file is busy');
    sysopen my $fh, $sleek->{task_file}, O_APPEND | O_NOFOLLOW | O_RDWR
        or _fatal("cannot open Sleek task file: $!");
    my @st = stat $fh;
    -f $fh && $st[4] == $< && $st[3] == 1 && ($st[2] & 0077) == 0 && $st[7] <= 16 * 1024 * 1024
        or _fatal('Sleek task file metadata is unsafe or file exceeds 16 MiB');
    binmode $fh, ':raw';
    seek($fh, 0, 0) or _fatal("cannot rewind Sleek task file: $!");
    my ($bytes, $last) = (0, q{});
    while (my $line = <$fh>) {
        $bytes += length $line;
        $bytes <= 16 * 1024 * 1024 or _fatal('Sleek task file is too large');
        # Stable source keys make retries after an interrupted commit harmless.
        if ($line =~ /(?:\A|\s)source:\Q$stem\E(?:\s|\z)/) {
            # A crash may occur after the source key but before the newline.
            # Complete that existing record rather than duplicating it.
            if ($line !~ /\n\z/) {
                print {$fh} "\n" or _fatal("cannot complete Sleek task: $!");
            }
            $fh->flush && $fh->sync or _fatal("cannot sync existing Sleek task: $!");
            close $fh or _fatal("cannot close Sleek task: $!");
            return;
        }
        $last = substr($line, -1);
    }
    my $record = ($bytes && $last ne "\n" ? "\n" : q{})
        . substr($stem, 0, 10) . " $text +whisper \@voice source:$stem\n";
    print {$fh} encode('UTF-8', $record) or _fatal("cannot append Sleek task: $!");
    $fh->flush && $fh->sync or _fatal("cannot flush Sleek task: $!");
    close $fh or _fatal("cannot close Sleek task: $!");
    return;
}

sub prune {
    my ($self, $directory, $extension) = @_;
    opendir my $dh, $directory or _fatal("cannot read artifact directory: $!");
    my @files = sort { $b cmp $a } grep {
        /\A[0-9]{4}(?:-[0-9]{2}){5}\.\Q$extension\E\z/ &&
        -f "$directory/$_" && !-l "$directory/$_"
    } readdir $dh;
    closedir $dh or _fatal("cannot close artifact directory: $!");
    $self->max_artifacts() >= 1 or _fatal('max_artifacts must be positive');
    return if @files <= $self->max_artifacts();
    for my $name (@files[$self->max_artifacts() .. $#files]) {
        unlink "$directory/$name" or _fatal("cannot prune managed artifact: $name");
    }
}

sub read_json {
    my ($self, $path, $limit, $label) = @_;
    $limit > 0 && $limit <= 16 * 1024 * 1024 or _fatal('invalid JSON size limit');
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK or _fatal("cannot read $label: $!");
    my @st = stat $fh;
    -f $fh && $st[4] == $< && $st[7] <= $limit or _fatal("$label is unsafe or too large");
    my $raw = q{};
    while (1) {
        my $n = sysread($fh, my $chunk, $limit + 1 - length $raw);
        if (!defined $n) { next if $! == EINTR; _fatal("cannot read $label: $!"); }
        last if !$n;
        $raw .= $chunk;
        length($raw) <= $limit or _fatal("$label is too large");
    }
    close $fh or _fatal("cannot close $label: $!");
    my $data = eval { decode_json($raw) };
    !$@ && ref($data) eq 'HASH' or _fatal("$label is not valid JSON");
    return $data;
}

1;
