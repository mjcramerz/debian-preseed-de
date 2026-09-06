package AICopilots::ModelStore;

use strict;
use warnings;

use Cwd qw(abs_path);
use Fcntl qw(O_RDONLY O_NOFOLLOW O_NONBLOCK);
use Errno qw(EINTR);
use Encode qw(decode FB_CROAK);
use File::Basename qw(basename);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(WIFEXITED WEXITSTATUS WIFSIGNALED WTERMSIG);
use Types::Standard qw(Object Str);

use AICopilots::ModelCatalog;

has state => (
    is       => 'ro',
    isa      => Object,
    required => 1,
);
has llama_model_directory => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/pool/cache/llama/models' },
);
has whisper_model_directory => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/pool/cache/whisper/models' },
);
has llama_config => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/llama/llama.conf' },
);
has pkexec => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/bin/pkexec' },
);
has root_helper => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/libexec/labwc-ai-model-install-root' },
);
has model_catalog => (
    is      => 'ro',
    isa     => Object,
    lazy    => 1,
    builder => sub { AICopilots::ModelCatalog->new() },
);

sub _fatal {
    my ($message) = @_;
    die "labwc-ai-copilots-action: $message\n";
}

sub _status_detail {
    my ($status) = @_;
    return "exec error: $!" if $status == -1;
    return 'terminated by signal ' . WTERMSIG($status) if WIFSIGNALED($status);
    return 'exit status ' . WEXITSTATUS($status) if WIFEXITED($status);
    return 'unknown process status';
}

sub _devops_gid {
    my (undef, undef, $gid) = getgrnam('devops');
    defined($gid) && $gid =~ /\A[0-9]+\z/
        or _fatal('managed devops group is unavailable');
    return int($gid);
}

sub _family_policy {
    my ($self, $family) = @_;
    return {
        directory => $self->llama_model_directory(),
        filename  => qr/\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.gguf\z/,
        magic     => 'GGUF',
        minimum   => 1_048_576,
        maximum   => 107_374_182_400,
    } if $family eq 'llama';
    return {
        directory => $self->whisper_model_directory(),
        filename  => qr/\Aggml-[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.bin\z/,
        magic     => pack('H*', '6c6d6767'),
        minimum   => 1_048_576,
        maximum   => 21_474_836_480,
    } if $family eq 'whisper';
    _fatal('unsupported model family');
}

sub _assert_model_directory {
    my ($self, $family) = @_;
    my $directory = $self->_family_policy($family)->{directory};
    -d $directory && !-l $directory
        or _fatal("managed $family model directory is unavailable");
    my $resolved = abs_path($directory);
    defined($resolved) && $resolved eq $directory
        or _fatal("managed $family model directory is not canonical");
    my @stat = lstat $directory;
    $stat[4] == 0 && $stat[5] == _devops_gid()
        && ($stat[2] & 07777) == 02750
        or _fatal("managed $family model directory ownership or mode is unsafe");
    return $directory;
}

sub _read_magic {
    my ($path) = @_;
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or _fatal("cannot inspect model magic: $!");
    my @st = stat $fh;
    -f $fh && $st[4] == 0 && $st[5] == _devops_gid() && ($st[2] & 07777) == 0640
        or _fatal('opened model ownership or mode is unsafe');
    my $magic = q{};
    while (length($magic) < 4) {
        my $n = sysread($fh, my $chunk, 4 - length($magic));
        if (!defined $n) { next if $! == EINTR; _fatal("cannot read model magic: $!"); }
        $n or _fatal('model is too small to contain its format magic');
        $magic .= $chunk;
    }
    close $fh
        or _fatal("cannot close model after magic inspection: $!");
    return $magic;
}

sub _directory_models {
    my ($self, $family) = @_;
    my $policy = $self->_family_policy($family);
    my $directory = $self->_assert_model_directory($family);
    opendir my $dh, $directory
        or _fatal("cannot inspect model directory: $directory");
    my @models;
    while (my $entry = readdir $dh) {
        next if $entry eq '.' || $entry eq '..';
        next if $entry !~ $policy->{filename};
        my $path = "$directory/$entry";
        next if !-f $path || -l $path;
        my @stat = lstat $path;
        next if $stat[4] != 0 || $stat[5] != _devops_gid()
            || ($stat[2] & 07777) != 0640;
        next if $stat[7] < $policy->{minimum} || $stat[7] > $policy->{maximum};
        next if _read_magic($path) ne $policy->{magic};
        push @models, $path;
        @models <= 200
            or _fatal("too many models below $directory");
    }
    closedir $dh
        or _fatal("cannot close model directory: $directory");
    return sort @models;
}

sub list_models {
    my ($self) = @_;
    return $self->_directory_models('llama');
}

sub list_whisper_models {
    my ($self) = @_;
    return $self->_directory_models('whisper');
}

sub _model_names {
    my ($self, $family) = @_;
    return map { basename($_) } $self->_directory_models($family);
}

sub list_model_names {
    my ($self) = @_;
    return $self->_model_names('llama');
}

sub list_whisper_model_names {
    my ($self) = @_;
    return $self->_model_names('whisper');
}

sub _resolve_model_name {
    my ($self, $family, $requested_name) = @_;
    my $policy = $self->_family_policy($family);
    defined($requested_name) && !ref($requested_name)
        && $requested_name =~ $policy->{filename}
        && $requested_name !~ /\.\./
        or _fatal('model name is invalid');
    my @matches = grep {
        basename($_) eq $requested_name
    } $self->_directory_models($family);
    @matches == 1
        or _fatal('model name is not installed or is ambiguous');
    return $matches[0];
}

sub resolve_model_name {
    my ($self, $requested_name) = @_;
    return $self->_resolve_model_name('llama', $requested_name);
}

sub resolve_whisper_model_name {
    my ($self, $requested_name) = @_;
    return $self->_resolve_model_name('whisper', $requested_name);
}

sub list_favorite_models {
    my ($self) = @_;
    my (@models, %seen);
    for my $requested (
        @{$self->state()->document()->{llama}{favorite_models}}
    ) {
        my $valid = eval { $self->validate_model($requested) };
        next if !defined($valid) || !length($valid) || $seen{$valid}++;
        push @models, $valid;
        @models <= 32
            or _fatal('too many favorite models are recorded');
    }
    return @models;
}

sub list_favorite_model_names {
    my ($self) = @_;
    return map { basename($_) } $self->list_favorite_models();
}

sub resolve_favorite_model_name {
    my ($self, $requested_name) = @_;
    defined($requested_name) && !ref($requested_name)
        && $requested_name =~ $self->_family_policy('llama')->{filename}
        && $requested_name !~ /\.\./
        or _fatal('favorite model name is invalid');
    my @matches = grep {
        basename($_) eq $requested_name
    } $self->list_favorite_models();
    @matches == 1
        or _fatal('favorite model name is not recorded or is ambiguous');
    return $matches[0];
}

sub _validate_model {
    my ($self, $family, $requested) = @_;
    my $policy = $self->_family_policy($family);
    my $directory = $self->_assert_model_directory($family);
    defined($requested) && !ref($requested) && length($requested) <= 4096
        && $requested =~ m{\A/} && $requested !~ /[\0\r\n]/
        && $requested !~ m{(?:\A|/)\.\.(?:/|\z)|//}
        or _fatal('model path is invalid');
    -f $requested && !-l $requested && -r $requested
        or _fatal('model path must be a readable regular file');
    my $resolved = abs_path($requested);
    defined($resolved) && $resolved eq $requested
        or _fatal('model path must already be canonical');
    index($resolved, "$directory/") == 0
        or _fatal('model path is outside the approved model directory');
    basename($resolved) =~ $policy->{filename}
        or _fatal('model filename is invalid');
    my @stat = lstat $resolved;
    $stat[4] == 0 && $stat[5] == _devops_gid()
        && ($stat[2] & 07777) == 0640
        or _fatal('model ownership or mode is unsafe');
    $stat[7] >= $policy->{minimum} && $stat[7] <= $policy->{maximum}
        or _fatal('model size is outside the supported bounds');
    _read_magic($resolved) eq $policy->{magic}
        or _fatal("$family model format magic is invalid");
    return $resolved;
}

sub validate_model {
    my ($self, $requested) = @_;
    return $self->_validate_model('llama', $requested);
}

sub validate_whisper_model {
    my ($self, $requested) = @_;
    return $self->_validate_model('whisper', $requested);
}

sub configured_model {
    my ($self) = @_;
    my $path = $self->llama_config();
    -f $path && !-l $path
        or _fatal('managed Llama configuration is unavailable');
    my @stat = lstat $path;
    $stat[4] == 0 && ($stat[2] & 0022) == 0 && $stat[7] <= 65_536
        or _fatal('managed Llama configuration ownership or mode is unsafe');
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or _fatal("cannot read managed Llama configuration: $!");
    my @opened = stat $fh;
    -f $fh && $opened[0] == $stat[0] && $opened[1] == $stat[1]
        && $opened[4] == 0 && ($opened[2] & 0022) == 0
        or _fatal('managed Llama configuration changed identity or is unsafe');
    my $raw = q{};
    while (1) {
        my $n = sysread($fh, my $chunk, 65_537 - length($raw));
        if (!defined $n) { next if $! == EINTR; _fatal("cannot read Llama configuration: $!"); }
        last if !$n;
        $raw .= $chunk;
        length($raw) <= 65_536 or _fatal('managed Llama configuration exceeds the size limit');
    }
    my $text = eval { decode('UTF-8', $raw, FB_CROAK) };
    !$@ or _fatal('managed Llama configuration is not UTF-8');
    my $model;
    for my $line (split /\n/, $text) {
        $line =~ s/\r\z//;
        next if $line =~ /\A(?:#|\s*\z)/;
        if ($line =~ /\ALLAMA_MODEL=(\/[^[:cntrl:]]+)\z/) {
            !defined($model)
                or _fatal('managed Llama configuration repeats LLAMA_MODEL');
            $model = $1;
        }
    }
    close $fh
        or _fatal("cannot close managed Llama configuration: $!");
    defined($model)
        or _fatal('managed Llama configuration has no valid LLAMA_MODEL');
    return $self->validate_model($model);
}

sub active_model {
    my ($self) = @_;
    my $llama = $self->state()->document()->{llama};
    for my $candidate ($llama->{active_model}, $llama->{default_model}) {
        next if !defined($candidate) || !length($candidate);
        return $self->validate_model($candidate);
    }
    return $self->configured_model();
}

sub _validate_download_request {
    my ($self, $family, $url, $filename, $sha256, $expected_bytes) = @_;
    my $policy = $self->_family_policy($family);
    defined($url) && !ref($url) && length($url) <= 2048
        && $url =~ m{\Ahttps://huggingface\.co/[A-Za-z0-9_./?&=%+,~#:@-]+\z}
        && $url !~ /[\0\r\n\s]/
        or _fatal('model URL must be a credential-free Hugging Face HTTPS URL');
    defined($filename) && !ref($filename) && $filename =~ $policy->{filename}
        && $filename !~ /\.\./
        or _fatal('model filename is invalid');
    defined($sha256) && !ref($sha256)
        && $sha256 =~ /\A[0-9a-f]{64}\z/
        or _fatal('model SHA-256 is invalid');
    defined($expected_bytes) && !ref($expected_bytes)
        && $expected_bytes =~ /\A[0-9]{1,12}\z/
        && $expected_bytes >= $policy->{minimum}
        && $expected_bytes <= $policy->{maximum}
        or _fatal('expected model byte count is outside the supported bounds');
    return 1;
}

sub _run_root_helper {
    my ($self, @arguments) = @_;
    -x $self->pkexec() && !-l $self->pkexec()
        or _fatal('pkexec is unavailable or unsafe');
    -x $self->root_helper() && !-l $self->root_helper()
        or _fatal('privileged model installer is unavailable or unsafe');
    my @command = ($self->pkexec(), $self->root_helper(), @arguments);
    my $status = system { $command[0] } @command;
    $status == 0
        or _fatal('privileged model operation failed: ' . _status_detail($status));
    return 1;
}

sub list_download_models {
    my ($self, $family) = @_;
    return $self->model_catalog()->table_lines($family);
}

sub resolve_download_model {
    my ($self, $family, $requested_display) = @_;
    return $self->model_catalog()
        ->entry_by_display($family, $requested_display)->{id};
}

sub catalog_entry {
    my ($self, $family, $requested_id) = @_;
    return $self->model_catalog()->entry_by_id($family, $requested_id);
}

sub _download {
    my ($self, $family, $url, $filename, $sha256, $expected_bytes) = @_;
    $self->_validate_download_request(
        $family,
        $url,
        $filename,
        $sha256,
        $expected_bytes,
    );
    my $directory = $self->_assert_model_directory($family);
    $self->_run_root_helper(
        'install',
        $family,
        $url,
        $filename,
        $sha256,
        $expected_bytes,
    );
    my $target = "$directory/$filename";
    return $family eq 'llama'
        ? $self->validate_model($target)
        : $self->validate_whisper_model($target);
}

sub download {
    my ($self, @arguments) = @_;
    return $self->_download('llama', @arguments);
}

sub download_whisper {
    my ($self, @arguments) = @_;
    return $self->_download('whisper', @arguments);
}

sub _download_catalog {
    my ($self, $family, $requested_id) = @_;
    my $entry = $self->catalog_entry($family, $requested_id);
    my $directory = $self->_assert_model_directory($family);
    $self->_run_root_helper('install-catalog', $family, $entry->{id});
    my $target = "$directory/$entry->{local_filename}";
    return $family eq 'llama'
        ? $self->validate_model($target)
        : $self->validate_whisper_model($target);
}

sub download_catalog {
    my ($self, $requested_id) = @_;
    return $self->_download_catalog('llama', $requested_id);
}

sub download_whisper_catalog {
    my ($self, $requested_id) = @_;
    return $self->_download_catalog('whisper', $requested_id);
}

sub prune_partials {
    my ($self) = @_;
    $self->_run_root_helper('prune', 'llama');
    return 1;
}

sub prune_whisper_partials {
    my ($self) = @_;
    $self->_run_root_helper('prune', 'whisper');
    return 1;
}

1;
