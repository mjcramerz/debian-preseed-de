package AICopilots::ModelInstallRoot;

use strict;
use warnings;

use Cwd qw(abs_path);
use Digest::SHA;
use Fcntl qw(:DEFAULT :flock O_NOFOLLOW);
use File::Basename qw(basename);
use File::Temp qw(tempfile);
use IO::Handle;
use JSON::PP qw(decode_json);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object Str);

use AICopilots::ModelCatalog;

has curl => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/bin/curl' },
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
has model_catalog => (
    is      => 'ro',
    isa     => Object,
    lazy    => 1,
    builder => sub { AICopilots::ModelCatalog->new() },
);

sub _fatal {
    my ($message) = @_;
    die "labwc-ai-model-install-root: $message\n";
}

sub _devops_gid {
    my @group = getgrnam('devops');
    @group && defined($group[2]) && $group[2] =~ /\A[0-9]+\z/
        or _fatal('managed devops group is unavailable');
    return int($group[2]);
}

sub _family_policy {
    my ($self, $family) = @_;
    return {
        directory    => $self->llama_model_directory(),
        filename     => qr/\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.gguf\z/,
        magic        => 'GGUF',
        marker       => '.installer-llama-managed',
        marker_value => "managed=llama-models\n",
        minimum      => 1_048_576,
        maximum      => 107_374_182_400,
    } if $family eq 'llama';
    return {
        directory    => $self->whisper_model_directory(),
        filename     => qr/\Aggml-[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.bin\z/,
        magic        => pack('H*', '6c6d6767'),
        marker       => '.installer-whisper-managed',
        marker_value => "managed=whisper-models\n",
        minimum      => 1_048_576,
        maximum      => 21_474_836_480,
    } if $family eq 'whisper';
    _fatal('unsupported model family');
}

sub _validate_install_request {
    my ($family, $url, $filename, $sha256, $expected_bytes) = @_;
    my $filename_pattern =
        $family eq 'llama'
        ? qr/\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.gguf\z/
        : $family eq 'whisper'
        ? qr/\Aggml-[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.bin\z/
        : _fatal('unsupported model family');
    my ($minimum, $maximum) =
        $family eq 'llama'
        ? (1_048_576, 107_374_182_400)
        : (1_048_576, 21_474_836_480);

    defined($url) && !ref($url) && length($url) <= 2048
        && $url =~ m{\Ahttps://huggingface\.co/[A-Za-z0-9_./?&=%+,~#:@-]+\z}
        && $url !~ /[\0\r\n\s]/
        or _fatal('model URL must be a credential-free Hugging Face HTTPS URL');
    defined($filename) && !ref($filename) && $filename =~ $filename_pattern
        && $filename !~ /\.\./
        or _fatal('model filename is invalid');
    defined($sha256) && !ref($sha256)
        && $sha256 =~ /\A[0-9a-f]{64}\z/
        or _fatal('model SHA-256 is invalid');
    defined($expected_bytes) && !ref($expected_bytes)
        && $expected_bytes =~ /\A[0-9]{1,12}\z/
        && $expected_bytes >= $minimum && $expected_bytes <= $maximum
        or _fatal('expected model byte count is outside the supported bounds');
    return 1;
}

sub _metadata_url {
    my ($entry) = @_;
    return 'https://huggingface.co/api/models/'
        . $entry->{repository}
        . '/revision/'
        . $entry->{revision}
        . '?blobs=true';
}

sub _fetch_model_metadata {
    my ($self, $entry) = @_;
    -x $self->curl() && !-l $self->curl()
        or _fatal('managed curl executable is unavailable or unsafe');
    my $maximum_bytes = 4_194_304;
    my @command = (
        $self->curl(),
        '--disable',
        '--fail',
        '--silent',
        '--show-error',
        '--location',
        '--max-redirs', '3',
        '--proto', '=https',
        '--proto-redir', '=https',
        '--tlsv1.2',
        '--retry', '2',
        '--retry-all-errors',
        '--retry-delay', '1',
        '--retry-connrefused',
        '--retry-max-time', '30',
        '--connect-timeout', '10',
        '--max-time', '60',
        '--max-filesize', "$maximum_bytes",
        '--header', 'Accept: application/json',
        '--user-agent', 'labwc-ai-copilots/1',
        _metadata_url($entry),
    );
    open my $fh, '-|', @command
        or _fatal("cannot start Hugging Face metadata request: $!");
    binmode $fh, ':raw'
        or _fatal("cannot configure Hugging Face metadata stream: $!");
    my $content = q{};
    while (1) {
        my $chunk = q{};
        my $read = read($fh, $chunk, 65_536);
        defined($read)
            or _fatal("cannot read Hugging Face metadata: $!");
        last if $read == 0;
        $content .= $chunk;
        if (length($content) > $maximum_bytes) {
            close $fh;
            _fatal('Hugging Face metadata exceeds the size bound');
        }
    }
    close $fh
        or _fatal('Hugging Face metadata request failed');
    length($content) >= 2
        or _fatal('Hugging Face metadata response is empty');
    return $content;
}

sub _resolve_catalog_download {
    my ($self, $family, $entry, $content) = @_;
    defined($content) && !ref($content) && length($content) <= 4_194_304
        or _fatal('Hugging Face metadata response is invalid');
    my $metadata = eval { decode_json($content) };
    ref($metadata) eq 'HASH'
        or _fatal('Hugging Face metadata is not valid JSON');
    for my $identity_field (qw(id modelId)) {
        defined($metadata->{$identity_field})
            && !ref($metadata->{$identity_field})
            && $metadata->{$identity_field} eq $entry->{repository}
            or _fatal('Hugging Face metadata repository identity is invalid');
    }
    defined($metadata->{sha}) && !ref($metadata->{sha})
        && $metadata->{sha} eq $entry->{revision}
        or _fatal('Hugging Face metadata revision is invalid');
    exists($metadata->{private}) && !$metadata->{private}
        or _fatal('private Hugging Face repositories are unsupported');
    exists($metadata->{gated}) && !$metadata->{gated}
        or _fatal('gated Hugging Face repositories are unsupported');
    exists($metadata->{disabled}) && !$metadata->{disabled}
        or _fatal('disabled Hugging Face repositories are unsupported');

    ref($metadata->{siblings}) eq 'ARRAY'
        && @{$metadata->{siblings}} <= 10_000
        or _fatal('Hugging Face metadata file list is invalid');
    my @matches = grep {
        ref($_) eq 'HASH'
            && defined($_->{rfilename})
            && !ref($_->{rfilename})
            && $_->{rfilename} eq $entry->{remote_filename}
    } @{$metadata->{siblings}};
    @matches == 1
        or _fatal('catalog model must resolve to exactly one Hugging Face file');
    my $match = $matches[0];
    ref($match->{lfs}) eq 'HASH'
        or _fatal('catalog model is not backed by a Hugging Face LFS object');
    my $sha256 = $match->{lfs}{sha256};
    my $expected_bytes = $match->{lfs}{size};
    defined($sha256) && !ref($sha256)
        && $sha256 =~ /\A[0-9a-f]{64}\z/
        or _fatal('catalog model LFS SHA-256 is invalid');
    defined($expected_bytes) && !ref($expected_bytes)
        && "$expected_bytes" =~ /\A[0-9]{1,12}\z/
        or _fatal('catalog model LFS byte count is invalid');
    if (exists($match->{size})) {
        defined($match->{size}) && !ref($match->{size})
            && "$match->{size}" =~ /\A[0-9]{1,12}\z/
            && $match->{size} == $expected_bytes
            or _fatal('catalog model file and LFS byte counts disagree');
    }

    my $url = 'https://huggingface.co/'
        . $entry->{repository}
        . '/resolve/'
        . $entry->{revision}
        . '/'
        . $entry->{remote_filename}
        . '?download=true';
    _validate_install_request(
        $family,
        $url,
        $entry->{local_filename},
        $sha256,
        $expected_bytes,
    );
    return ($url, $sha256, int($expected_bytes));
}

sub _require_privileged_invoker {
    $< == 0 && $> == 0
        or _fatal('privileged model installer must run as root');
    my $uid = $ENV{PKEXEC_UID} // q{};
    $uid =~ /\A[1-9][0-9]*\z/
        or _fatal('privileged model installer must be invoked through pkexec');
    defined(getpwuid($uid))
        or _fatal("pkexec invoking account does not exist: $uid");
    return int($uid);
}

sub _read_bounded_file {
    my ($path, $maximum) = @_;
    -f $path && !-l $path
        or _fatal("managed file is unavailable or unsafe: $path");
    my @stat = lstat $path;
    $stat[7] <= $maximum
        or _fatal("managed file exceeds the size bound: $path");
    open my $fh, '<:raw', $path
        or _fatal("cannot read managed file: $path: $!");
    local $/;
    my $content = <$fh>;
    close $fh
        or _fatal("cannot close managed file: $path: $!");
    return $content;
}

sub _assert_directory_contract {
    my ($self, $family) = @_;
    my $policy = $self->_family_policy($family);
    my $directory = $policy->{directory};
    my $devops_gid = _devops_gid();
    -d $directory && !-l $directory
        or _fatal("managed $family model directory is unavailable");
    my $resolved = abs_path($directory);
    defined($resolved) && $resolved eq $directory
        or _fatal("managed $family model directory is not canonical");
    my @stat = lstat $directory;
    $stat[4] == 0 && $stat[5] == $devops_gid
        && ($stat[2] & 07777) == 02750
        or _fatal("managed $family model directory ownership or mode is unsafe");

    my $marker = "$directory/$policy->{marker}";
    my @marker_stat = lstat $marker;
    -f _ && !-l $marker
        && $marker_stat[4] == 0 && $marker_stat[5] == $devops_gid
        && ($marker_stat[2] & 07777) == 0600
        or _fatal("managed $family model marker is unavailable or unsafe");
    _read_bounded_file($marker, 128) eq $policy->{marker_value}
        or _fatal("managed $family model marker is invalid");
    return $policy;
}

sub _sha256_file {
    my ($path) = @_;
    open my $fh, '<:raw', $path
        or _fatal("cannot read model for SHA-256 verification: $!");
    my $digest = Digest::SHA->new(256);
    $digest->addfile($fh);
    close $fh
        or _fatal("cannot close model after SHA-256 verification: $!");
    return $digest->hexdigest();
}

sub _read_magic {
    my ($path) = @_;
    open my $fh, '<:raw', $path
        or _fatal("cannot inspect model magic: $!");
    my $magic = q{};
    read($fh, $magic, 4) == 4
        or _fatal('model is too small to contain its format magic');
    close $fh
        or _fatal("cannot close model after magic inspection: $!");
    return $magic;
}

sub _validate_model {
    my ($self, $family, $path, $sha256, $expected_bytes, $expected_mode) = @_;
    my $policy = $self->_family_policy($family);
    my $devops_gid = _devops_gid();
    -f $path && !-l $path
        or _fatal('model path must be a non-symbolic regular file');
    my $resolved = abs_path($path);
    defined($resolved) && $resolved eq $path
        or _fatal('model path must already be canonical');
    index($path, "$policy->{directory}/") == 0
        or _fatal('model path is outside the fixed family directory');
    basename($path) =~ $policy->{filename}
        or _fatal('model filename is invalid');
    my @stat = lstat $path;
    $stat[4] == 0 && $stat[5] == $devops_gid
        && ($stat[2] & 07777) == $expected_mode
        or _fatal('model ownership or mode is unsafe');
    $stat[7] == $expected_bytes
        or _fatal('model byte count does not match the requested value');
    _read_magic($path) eq $policy->{magic}
        or _fatal("$family model format magic is invalid");
    _sha256_file($path) eq $sha256
        or _fatal('model SHA-256 does not match the requested digest');
    return $path;
}

sub _open_lock {
    my ($path) = @_;
    sysopen my $fh, $path, O_CREAT | O_RDWR | O_NOFOLLOW, 0600
        or _fatal("cannot open model download lock: $!");
    chown 0, _devops_gid(), $path
        or _fatal("cannot set model download lock ownership: $!");
    chmod 0600, $path
        or _fatal("cannot secure model download lock: $!");
    my @stat = lstat $path;
    -f _ && !-l $path && $stat[4] == 0 && $stat[5] == _devops_gid()
        && ($stat[2] & 07777) == 0600
        or _fatal('model download lock ownership or mode is unsafe');
    flock $fh, LOCK_EX
        or _fatal("cannot lock model download: $!");
    return $fh;
}

sub _download {
    my ($self, $family, $url, $filename, $sha256, $expected_bytes) = @_;
    _validate_install_request(
        $family,
        $url,
        $filename,
        $sha256,
        $expected_bytes,
    );
    my $policy = $self->_assert_directory_contract($family);
    -x $self->curl() && !-l $self->curl()
        or _fatal('managed curl executable is unavailable or unsafe');

    my $directory = $policy->{directory};
    my $target = "$directory/$filename";
    my $lock = _open_lock("$directory/.$filename.lock");
    if (-e $target || -l $target) {
        $self->_validate_model(
            $family,
            $target,
            $sha256,
            $expected_bytes,
            0640,
        );
        print "$target\n";
        return 0;
    }

    my $partial;
    my $completed = eval {
        my ($fh, $temporary) = tempfile(
            ".$filename.partial.XXXXXX",
            DIR    => $directory,
            UNLINK => 0,
        );
        $partial = $temporary;
        close $fh
            or _fatal("cannot close model staging file: $!");
        chown 0, _devops_gid(), $partial
            or _fatal("cannot set model staging file ownership: $!");
        chmod 0600, $partial
            or _fatal("cannot secure model staging file: $!");

        my @command = (
            $self->curl(),
            '--disable',
            '--fail',
            '--silent',
            '--show-error',
            '--location',
            '--proto', '=https',
            '--proto-redir', '=https',
            '--tlsv1.2',
            '--retry', '3',
            '--retry-all-errors',
            '--retry-delay', '2',
            '--retry-connrefused',
            '--retry-max-time', '600',
            '--connect-timeout', '20',
            '--max-time', '14400',
            '--max-filesize', "$expected_bytes",
            '--output', $partial,
            $url,
        );
        my $status = system { $command[0] } @command;
        $status == 0
            or _fatal('model download failed');

        $self->_validate_model(
            $family,
            $partial,
            $sha256,
            $expected_bytes,
            0600,
        );
        open my $sync_fh, '<:raw', $partial
            or _fatal("cannot reopen verified model for synchronization: $!");
        $sync_fh->sync()
            or _fatal("cannot synchronize verified model: $!");
        close $sync_fh
            or _fatal("cannot close synchronized model: $!");
        chmod 0640, $partial
            or _fatal("cannot set verified model mode: $!");
        !-e $target && !-l $target
            or _fatal('model target appeared during verified download');
        rename $partial, $target
            or _fatal("cannot publish verified model: $!");
        $partial = undef;
        $self->_validate_model(
            $family,
            $target,
            $sha256,
            $expected_bytes,
            0640,
        );
        1;
    };
    if (!$completed) {
        my $error = $@ || "model installation failed\n";
        unlink $partial if defined($partial) && (-f $partial || -l $partial);
        die $error;
    }

    print "$target\n";
    return 0;
}

sub _download_catalog {
    my ($self, $family, $requested_id) = @_;
    my $entry = $self->model_catalog()->entry_by_id($family, $requested_id);
    $self->_assert_directory_contract($family);
    my $metadata = $self->_fetch_model_metadata($entry);
    my ($url, $sha256, $expected_bytes) =
        $self->_resolve_catalog_download($family, $entry, $metadata);
    return $self->_download(
        $family,
        $url,
        $entry->{local_filename},
        $sha256,
        $expected_bytes,
    );
}

sub _prune {
    my ($self, $family) = @_;
    my $policy = $self->_assert_directory_contract($family);
    my $directory = $policy->{directory};
    opendir my $dh, $directory
        or _fatal("cannot inspect model directory: $!");
    my $removed = 0;
    while (my $entry = readdir $dh) {
        next if $entry !~
            /\A\.[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(?:gguf|bin)\.partial\.[A-Za-z0-9]+\z/;
        my $path = "$directory/$entry";
        next if !-f $path || -l $path;
        my @stat = lstat $path;
        next if $stat[4] != 0 || $stat[5] != _devops_gid()
            || ($stat[2] & 07777) != 0600;
        unlink $path
            or _fatal("cannot remove partial model download: $!");
        $removed++;
        $removed <= 100
            or _fatal('too many partial model downloads to prune safely');
    }
    closedir $dh
        or _fatal("cannot close model directory: $!");
    print "$removed\n";
    return 0;
}

sub run {
    my ($self, @argv) = @_;
    _require_privileged_invoker();
    @argv
        or _fatal(
            'usage: labwc-ai-model-install-root '
            . '<install|install-catalog|prune> <family> [arguments]'
        );
    my $action = shift @argv;
    if ($action eq 'install') {
        @argv == 5
            or _fatal('install requires family, URL, filename, SHA-256, and byte count');
        return $self->_download(@argv);
    }
    if ($action eq 'install-catalog') {
        @argv == 2
            or _fatal('install-catalog requires a model family and catalog identifier');
        return $self->_download_catalog(@argv);
    }
    if ($action eq 'prune') {
        @argv == 1
            or _fatal('prune requires exactly one model family');
        return $self->_prune($argv[0]);
    }
    _fatal('unsupported privileged model action');
}

1;
