package AICopilots::State;

use strict;
use warnings;

use Fcntl qw(:DEFAULT :flock O_NOFOLLOW O_NONBLOCK F_SETFD FD_CLOEXEC);
use Errno qw(EINTR);
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC sleep);
use Cwd qw(abs_path);
use File::Path qw(make_path);
use File::Temp qw(tempfile);
use IO::Handle;
use JSON::PP qw(decode_json encode_json);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(HashRef Int Str);

has home => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);
has max_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 262_144 },
);
has document => (
    is      => 'ro',
    isa     => HashRef,
    lazy    => 1,
    builder => '_load',
);

sub _fatal {
    my ($message) = @_;
    die "labwc-ai-copilots-action: $message\n";
}

sub config_root {
    my ($self) = @_;
    return $self->home() . '/.config/labwc-ai-copilots';
}

sub state_root {
    my ($self) = @_;
    return $self->home() . '/.local/state/labwc-ai-copilots';
}

sub settings_path {
    my ($self) = @_;
    return $self->config_root() . '/settings.json';
}

sub _managed_directories {
    my ($self) = @_;
    return (
        $self->home() . '/.config',
        $self->config_root(),
        $self->home() . '/.local',
        $self->home() . '/.local/state',
        $self->state_root(),
    );
}

sub _ensure_directories {
    my ($self) = @_;
    my $home = $self->home();
    defined(abs_path($home)) && abs_path($home) eq $home && -d $home && !-l $home
        && (lstat $home)[4] == $< && ((lstat $home)[2] & 0022) == 0
        or _fatal('home directory is not canonical, owned and protected');
    for my $directory ($self->_managed_directories()) {
        if (!-e $directory && !-l $directory) {
            make_path($directory, { mode => 0700 })
                or _fatal("cannot create managed directory: $directory");
        }
        -d $directory && !-l $directory
            or _fatal("managed path is not a real directory: $directory");
        my @stat = lstat $directory;
        $stat[4] == $< && ($stat[2] & 0022) == 0
            or _fatal("managed directory ownership or mode is unsafe: $directory");
    }
    chmod 0700, $self->config_root(), $self->state_root()
        or _fatal("cannot secure AI & Copilots directories: $!");
    return 1;
}

sub _defaults {
    return {
        version => 1,
        codex   => {
            project         => q{},
            recent_projects => [],
            model           => q{},
            reasoning       => 'default',
        },
        llama => {
            active_model      => q{},
            default_model     => q{},
            aliases           => {},
            favorite_models   => [],
            recent_models     => [],
            persistent_memory => 0,
            prompt_history    => [],
            system_prompt     => q{},
            preset            => q{},
            runtime           => {
                context               => 0,
                threads               => 0,
                batch                 => 0,
                gpu_layers            => 0,
                gpu_layers_overridden => 0,
            },
        },
        whisper => {
            active_model    => q{},
            language        => 'auto',
            output          => 'file',
            post_processing => 'raw',
        },
    };
}

sub _assert_keys {
    my ($label, $value, @allowed) = @_;
    ref($value) eq 'HASH' or _fatal("$label is not an object");
    my %allowed = map { $_ => 1 } @allowed;
    for my $key (keys %{$value}) {
        $allowed{$key} or _fatal("$label contains an unsupported key");
    }
}

sub _assert_text {
    my ($label, $value, $maximum) = @_;
    defined($value) && !ref($value) && length($value) <= $maximum
        && $value !~ /[\0\r\n]/
        or _fatal("$label is invalid");
    return 1;
}

sub _assert_text_array {
    my ($label, $value, $maximum_items, $maximum_length) = @_;
    ref($value) eq 'ARRAY' && @{$value} <= $maximum_items
        or _fatal("$label is invalid");
    _assert_text($label, $_, $maximum_length) for @{$value};
    return 1;
}

sub _validate {
    my ($self, $document) = @_;
    _assert_keys('state', $document, qw(version codex llama whisper));
    $document->{version} == 1
        or _fatal('state version is unsupported');

    my $codex = $document->{codex};
    _assert_keys('Codex state', $codex, qw(project recent_projects model reasoning));
    _assert_text('Codex project', $codex->{project}, 4096);
    _assert_text_array('Codex recent projects', $codex->{recent_projects}, 20, 4096);
    _assert_text('Codex model', $codex->{model}, 128);
    $codex->{reasoning} =~ /\A(?:default|low|medium|high|xhigh)\z/
        or _fatal('Codex reasoning value is invalid');

    my $llama = $document->{llama};
    _assert_keys(
        'Llama state',
        $llama,
        qw(
          active_model default_model aliases favorite_models recent_models
          persistent_memory prompt_history system_prompt preset runtime
        ),
    );
    _assert_text('Llama active model', $llama->{active_model}, 4096);
    _assert_text('Llama default model', $llama->{default_model}, 4096);
    ref($llama->{aliases}) eq 'HASH' && keys(%{$llama->{aliases}}) <= 32
        or _fatal('Llama aliases are invalid');
    for my $alias (keys %{$llama->{aliases}}) {
        $alias =~ /\A[A-Za-z0-9][A-Za-z0-9._-]{0,31}\z/
            or _fatal('Llama alias name is invalid');
        _assert_text('Llama alias target', $llama->{aliases}{$alias}, 4096);
    }
    _assert_text_array('Llama favorite models', $llama->{favorite_models}, 32, 4096);
    _assert_text_array('Llama recent models', $llama->{recent_models}, 20, 4096);
    defined($llama->{persistent_memory}) && !ref($llama->{persistent_memory})
        && $llama->{persistent_memory} =~ /\A[01]\z/
        or _fatal('Llama memory flag is invalid');
    ref($llama->{prompt_history}) eq 'ARRAY' && @{$llama->{prompt_history}} <= 20
        or _fatal('Llama prompt history is invalid');
    for my $entry (@{$llama->{prompt_history}}) {
        _assert_keys('Llama prompt history entry', $entry, qw(prompt created_at));
        _assert_text('Llama prompt', $entry->{prompt}, 16_384);
        defined($entry->{created_at}) && !ref($entry->{created_at})
            && $entry->{created_at} =~ /\A[0-9]{1,12}\z/
            or _fatal('Llama prompt timestamp is invalid');
    }
    _assert_text('Llama system prompt', $llama->{system_prompt}, 8192);
    $llama->{preset} =~ /\A(?:|coding|code-review|security-review|deep-reasoning|concise-summary|brainstorm|shell-safety)\z/
        or _fatal('Llama prompt preset is invalid');
    _assert_keys(
        'Llama runtime state',
        $llama->{runtime},
        qw(context threads batch gpu_layers gpu_layers_overridden),
    );
    for my $key (qw(context threads batch gpu_layers)) {
        defined($llama->{runtime}{$key}) && !ref($llama->{runtime}{$key})
            && $llama->{runtime}{$key} =~ /\A[0-9]{1,7}\z/
            or _fatal("Llama runtime value is invalid: $key");
    }
    defined($llama->{runtime}{gpu_layers_overridden})
        && !ref($llama->{runtime}{gpu_layers_overridden})
        && $llama->{runtime}{gpu_layers_overridden} =~ /\A[01]\z/
        or _fatal('Llama GPU-layer override flag is invalid');

    my $whisper = $document->{whisper};
    _assert_keys(
        'Whisper state',
        $whisper,
        qw(active_model language output post_processing),
    );
    _assert_text('Whisper active model', $whisper->{active_model}, 4096);
    $whisper->{language} =~ /\A(?:auto|[a-z]{2,3})\z/
        or _fatal('Whisper language is invalid');
    $whisper->{output} =~ /\A(?:file|clipboard|both)\z/
        or _fatal('Whisper output mode is invalid');
    $whisper->{post_processing} =~ /\A(?:raw|normalize)\z/
        or _fatal('Whisper post-processing mode is invalid');
    return 1;
}

sub _lock {
    my ($self) = @_;
    $self->_ensure_directories();
    my $lock_path = $self->config_root() . '/settings.lock';
    sysopen my $fh, $lock_path, O_CREAT | O_RDWR | O_NOFOLLOW, 0600
        or _fatal("cannot open AI & Copilots state lock: $!");
    my @stat = stat $fh;
    @stat && -f $fh && $stat[4] == $< && $stat[3] == 1 && ($stat[2] & 07777) == 0600
        or _fatal('AI & Copilots state lock ownership or mode is unsafe');
    fcntl($fh, F_SETFD, FD_CLOEXEC) or _fatal("cannot protect state lock: $!");
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + 5;
    while (!flock($fh, LOCK_EX | LOCK_NB)) {
        $!{EWOULDBLOCK} || $!{EAGAIN} || $!{EINTR}
            or _fatal("cannot lock AI & Copilots state: $!");
        clock_gettime(CLOCK_MONOTONIC) < $deadline
            or _fatal('AI & Copilots state is busy');
        sleep 0.05;
    }
    return $fh;
}

sub _load {
    my ($self) = @_;
    my $lock = $self->_lock();
    return $self->_read_locked();
}

sub _read_locked {
    my ($self) = @_;
    my $path = $self->settings_path();
    if (!-e $path && !-l $path) {
        my $defaults = _defaults();
        $self->_save_locked($defaults);
        return $defaults;
    }
    -f $path && !-l $path
        or _fatal('AI & Copilots state is not a regular file');
    my @stat = lstat $path;
    $stat[4] == $< && ($stat[2] & 07777) == 0600
        or _fatal('AI & Copilots state ownership or mode is unsafe');
    $stat[7] <= $self->max_bytes()
        or _fatal('AI & Copilots state exceeds the size limit');
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or _fatal("cannot read AI & Copilots state: $!");
    my @opened = stat $fh;
    -f $fh && $opened[0] == $stat[0] && $opened[1] == $stat[1]
        && $opened[4] == $< && $opened[3] == 1 && ($opened[2] & 07777) == 0600
        or _fatal('AI & Copilots state changed identity or is unsafe');
    my $json = q{};
    while (1) {
        my $n = sysread($fh, my $chunk, $self->max_bytes() + 1 - length($json));
        if (!defined $n) { next if $! == EINTR; _fatal("cannot read AI & Copilots state: $!"); }
        last if !$n;
        $json .= $chunk;
        length($json) <= $self->max_bytes() or _fatal('AI & Copilots state exceeds the size limit');
    }
    close $fh or _fatal("cannot close AI & Copilots state: $!");
    my $document = eval { decode_json($json) };
    !$@ && ref($document) eq 'HASH'
        or _fatal('AI & Copilots state is malformed JSON');
    $self->_validate($document);
    return $document;
}

sub _save_locked {
    my ($self, $document) = @_;
    $self->_validate($document);
    my $json = JSON::PP->new->canonical(1)->utf8(1)->encode($document) . "\n";
    length($json) <= $self->max_bytes()
        or _fatal('AI & Copilots state exceeds the size limit');
    my ($fh, $temporary) = tempfile('.settings.XXXXXX', DIR => $self->config_root(), UNLINK => 1);
    my $ok = eval {
        binmode $fh, ':raw' or _fatal("cannot set state encoding: $!");
        print {$fh} $json or _fatal("cannot write AI & Copilots state: $!");
        $fh->flush() && $fh->sync() or _fatal("cannot synchronize AI & Copilots state: $!");
        close $fh or _fatal("cannot close AI & Copilots state: $!");
        rename $temporary, $self->settings_path()
            or _fatal("cannot publish AI & Copilots state: $!");
        sysopen my $directory, $self->config_root(), O_RDONLY | O_NOFOLLOW
            or _fatal("cannot open AI & Copilots state directory: $!");
        $directory->sync() or _fatal("cannot sync AI & Copilots state directory: $!");
        close $directory or _fatal("cannot close AI & Copilots state directory: $!");
        1;
    };
    my $error = $@;
    unlink $temporary if -e $temporary;
    die $error if !$ok;
    return 1;
}

sub mutate {
    my ($self, $callback) = @_;
    ref($callback) eq 'CODE'
        or _fatal('invalid state mutation callback');
    my $lock = $self->_lock();
    my $document = $self->_read_locked();
    my $before = JSON::PP->new->canonical(1)->utf8(1)->encode($document);
    $callback->($document);
    $self->_validate($document);
    $self->_save_locked($document)
        if JSON::PP->new->canonical(1)->utf8(1)->encode($document) ne $before;
    $self->{document} = $document;
    return $document;
}

sub remember_unique {
    my ($self, $array, $value, $maximum) = @_;
    @{$array} = ($value, grep { $_ ne $value } @{$array});
    splice @{$array}, $maximum if @{$array} > $maximum;
    return $array;
}

sub append_prompt {
    my ($self, $prompt) = @_;
    $self->mutate(sub {
        my ($document) = @_;
        unshift @{$document->{llama}{prompt_history}}, {
            prompt     => $prompt,
            created_at => time(),
        };
        splice @{$document->{llama}{prompt_history}}, 20
            if @{$document->{llama}{prompt_history}} > 20;
    });
    return 1;
}

1;
