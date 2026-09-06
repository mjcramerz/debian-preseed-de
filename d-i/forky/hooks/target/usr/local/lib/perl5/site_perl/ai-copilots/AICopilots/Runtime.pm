package AICopilots::Runtime;

use strict;
use warnings;

use Cwd qw(abs_path);
use Encode qw(encode);
use Fcntl qw(:DEFAULT O_NOFOLLOW);
use File::Basename qw(basename);
use File::Path qw(make_path);
use File::Spec;
use File::Temp qw(tempfile);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(strftime WIFEXITED WEXITSTATUS WIFSIGNALED WTERMSIG);
use Types::Standard qw(Object Str);

use AICopilots::ModelStore;
use AICopilots::Session;
use AICopilots::State;

has terminal => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/bin/labwc-terminal' },
);
has action_entrypoint => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/bin/labwc-ai-copilots-action' },
);
has session => (
    is      => 'ro',
    isa     => Object,
    lazy    => 1,
    builder => sub { AICopilots::Session->new() },
);
has state => (
    is      => 'ro',
    isa     => Object,
    lazy    => 1,
    builder => sub {
        my ($self) = @_;
        return AICopilots::State->new(home => $self->session()->home());
    },
);
has models => (
    is      => 'ro',
    isa     => Object,
    lazy    => 1,
    builder => sub {
        my ($self) = @_;
        return AICopilots::ModelStore->new(state => $self->state());
    },
);

my %ACTION_ARGUMENTS = (
    'codex-new-session'           => [0, 0],
    'codex-resume-last'           => [0, 0],
    'codex-resume-picker'         => [0, 0],
    'codex-task'                  => [1, 1],
    'codex-set-project'           => [1, 1],
    'codex-set-model'             => [1, 1],
    'codex-set-reasoning'         => [1, 1],
    'codex-clear-recent-projects' => [0, 0],
    'codex-open-project-terminal' => [0, 0],
    'codex-open-home-terminal'    => [0, 0],
    'codex-diagnostic'            => [1, 1],
    'llama-ask'                   => [1, 1],
    'llama-new-chat'              => [0, 0],
    'llama-resume-last-chat'      => [0, 0],
    'llama-set-active-model'      => [1, 1],
    'llama-set-default-model'     => [1, 1],
    'llama-set-model-alias'       => [2, 2],
    'llama-download-catalog-model' => [1, 1],
    'llama-download-model'        => [4, 4],
    'llama-open-model-search'     => [1, 2],
    'llama-favorite'              => [1, 1],
    'llama-memory'                => [1, 1],
    'llama-clear-chat-history'    => [0, 0],
    'llama-set-system-prompt'     => [1, 1],
    'llama-set-preset'            => [1, 1],
    'llama-set-runtime'           => [2, 2],
    'llama-performance-preset'    => [1, 1],
    'llama-reset-runtime'         => [0, 0],
    'llama-start-server'          => [0, 0],
    'llama-stop-server'           => [0, 0],
    'llama-prune-partials'        => [0, 0],
    'llama-model-info'            => [2, 2],
    'llama-diagnostic'            => [1, 1],
    'whisper-control'             => [1, 1],
    'whisper-dictation'           => [1, 1],
    'whisper-transcribe-file'     => [1, 1],
    'whisper-transcribe-last'     => [0, 0],
    'whisper-set-active-model'    => [1, 1],
    'whisper-download-catalog-model' => [1, 1],
    'whisper-download-model'      => [4, 4],
    'whisper-prune-partials'      => [0, 0],
    'whisper-set-language'        => [1, 1],
    'whisper-set-output'          => [1, 1],
    'whisper-set-post-processing' => [1, 1],
    'whisper-open'                => [1, 1],
    'whisper-audio'               => [1, 1],
    'whisper-diagnostic'          => [1, 1],
);

my %TERMINAL_ACTION = map { $_ => 1 } qw(
  codex-new-session
  codex-resume-last
  codex-resume-picker
  codex-task
  codex-diagnostic
  llama-ask
  llama-new-chat
  llama-resume-last-chat
  llama-download-catalog-model
  llama-download-model
  llama-model-info
  llama-diagnostic
  whisper-transcribe-file
  whisper-transcribe-last
  whisper-download-catalog-model
  whisper-download-model
  whisper-diagnostic
);

sub _fatal {
    my ($message) = @_;
    die "labwc-ai-copilots-action: $message\n";
}

sub _assert_text {
    my ($label, $value, $maximum) = @_;
    defined($value) && !ref($value) && length($value) > 0
        && length($value) <= $maximum && $value !~ /[\0\r\n]/
        or _fatal("$label is invalid or exceeds $maximum characters");
    return $value;
}

sub _assert_action_arguments {
    my ($action, @arguments) = @_;
    exists $ACTION_ARGUMENTS{$action}
        or _fatal('unsupported AI & Copilots action');
    my ($minimum, $maximum) = @{$ACTION_ARGUMENTS{$action}};
    @arguments >= $minimum && @arguments <= $maximum
        or _fatal("invalid argument count for action: $action");
    for my $argument (@arguments) {
        defined($argument) && !ref($argument) && length($argument) <= 16_384
            && $argument !~ /\0/
            or _fatal('unsafe action argument');
    }
    return 1;
}

sub _status_detail {
    my ($status) = @_;
    return "exec error: $!" if $status == -1;
    return 'terminated by signal ' . WTERMSIG($status) if WIFSIGNALED($status);
    return 'exit status ' . WEXITSTATUS($status) if WIFEXITED($status);
    return 'unknown process status';
}

sub _run {
    my ($self, @command) = @_;
    @command && defined($command[0])
        or _fatal('empty subprocess command');
    my $status = system { $command[0] } @command;
    $status == 0
        or _fatal('command failed: ' . _status_detail($status));
    return 1;
}

sub _capture {
    my ($self, $maximum, @command) = @_;
    $maximum >= 1 && $maximum <= 4_194_304
        or _fatal('capture size is outside the supported bounds');
    @command && defined($command[0])
        or _fatal('empty capture command');
    open my $fh, '-|',
        '/usr/bin/timeout',
        '--signal=TERM',
        '--kill-after=2s',
        '30s',
        @command
        or _fatal("cannot start diagnostic command: $!");
    binmode $fh, ':raw';
    my $output = q{};
    while (1) {
        my $buffer = q{};
        my $read = read($fh, $buffer, 65_536);
        defined($read)
            or _fatal("cannot read diagnostic output: $!");
        last if $read == 0;
        length($output) + $read <= $maximum
            or _fatal('diagnostic output exceeds the safety limit');
        $output .= $buffer;
    }
    close $fh
        or _fatal('diagnostic command failed');
    return $output;
}

sub _capture_allow_failure {
    my ($self, $maximum, @command) = @_;
    $maximum >= 1 && $maximum <= 4_194_304
        or _fatal('capture size is outside the supported bounds');
    @command && defined($command[0])
        or _fatal('empty capture command');
    open my $fh, '-|',
        '/usr/bin/timeout',
        '--signal=TERM',
        '--kill-after=2s',
        '30s',
        @command
        or _fatal("cannot start diagnostic command: $!");
    binmode $fh, ':raw';
    my $output = q{};
    while (1) {
        my $buffer = q{};
        my $read = read($fh, $buffer, 65_536);
        defined($read)
            or _fatal("cannot read diagnostic output: $!");
        last if $read == 0;
        length($output) + $read <= $maximum
            or _fatal('diagnostic output exceeds the safety limit');
        $output .= $buffer;
    }
    close $fh;
    return $output;
}

sub _read_file {
    my ($self, $path, $maximum, $allow_user_owned) = @_;
    defined($path) && $path =~ m{\A/} && $path !~ /[\0\r\n]/
        or _fatal('diagnostic file path is invalid');
    -f $path && !-l $path
        or _fatal("diagnostic file is unavailable: $path");
    my @stat = lstat $path;
    my $expected_uid = $allow_user_owned ? $< : 0;
    $stat[4] == $expected_uid && ($stat[2] & 0022) == 0
        or _fatal("diagnostic file ownership or mode is unsafe: $path");
    $stat[7] <= $maximum
        or _fatal("diagnostic file exceeds the size limit: $path");
    open my $fh, '<:encoding(UTF-8)', $path
        or _fatal("cannot read diagnostic file: $!");
    local $/;
    my $content = <$fh>;
    close $fh
        or _fatal("cannot close diagnostic file: $!");
    return $content // q{};
}

sub _tail_text {
    my ($self, $content, $maximum_lines) = @_;
    my @lines = split /\n/, $content;
    splice @lines, 0, @lines - $maximum_lines if @lines > $maximum_lines;
    return join("\n", @lines) . (@lines ? "\n" : q{});
}

sub _print_title {
    my ($title) = @_;
    print "\n=== $title ===\n";
}

sub _pause {
    print STDERR "\nPress Enter to close...";
    scalar <STDIN>;
    print STDERR "\n";
    return 1;
}

sub _notify {
    my ($self, $summary, $body) = @_;
    return if !defined($ENV{DBUS_SESSION_BUS_ADDRESS})
        || !length($ENV{DBUS_SESSION_BUS_ADDRESS});
    return if !-x '/usr/bin/notify-send';
    $summary = substr($summary, 0, 128);
    $body = substr($body, 0, 512);
    system {
        '/usr/bin/notify-send'
    } '/usr/bin/notify-send',
        '-a', 'AI & Copilots',
        '-u', 'normal',
        '-i', 'applications-development',
        '-t', '8000',
        $summary,
        $body;
    return 1;
}

sub _open_terminal {
    my ($self, $action, @arguments) = @_;
    -x $self->terminal()
        or _fatal('managed terminal launcher is unavailable');
    exec {
        $self->terminal()
    } $self->terminal(), '-e', $self->action_entrypoint(), '--run',
        $action, @arguments
        or _fatal("cannot open managed terminal: $!");
}

sub _project_path {
    my ($self, $requested) = @_;
    _assert_text('project path', $requested, 4096);
    $requested =~ m{\A/} && $requested !~ m{(?:\A|/)\.\.(?:/|\z)|//}
        or _fatal('project path must be a safe absolute path');
    -d $requested && !-l $requested
        or _fatal('project path must be a real directory');
    my $resolved = abs_path($requested);
    defined($resolved) && $resolved eq $requested
        or _fatal('project path must already be canonical');
    my $home = $self->session()->home();
    index($resolved, "$home/") == 0 || $resolved eq $home
        || index($resolved, '/pool/') == 0
        or _fatal('project path must remain below HOME or /pool');
    my @stat = lstat $resolved;
    $stat[4] == $< && ($stat[2] & 0022) == 0
        or _fatal('project path ownership or mode is unsafe');
    return $resolved;
}

sub _codex_project {
    my ($self) = @_;
    my $configured = $self->state()->document()->{codex}{project};
    return $self->_project_path(
        length($configured) ? $configured : $self->session()->home(),
    );
}

sub _codex_options {
    my ($self) = @_;
    my $codex = $self->state()->document()->{codex};
    my @options;
    push @options, '--model', $codex->{model} if length($codex->{model});
    push @options, '--config', "model_reasoning_effort=$codex->{reasoning}"
        if $codex->{reasoning} ne 'default';
    return @options;
}

sub _exec_codex {
    my ($self, @arguments) = @_;
    my $project = $self->_codex_project();
    chdir $project
        or _fatal("cannot enter Codex project: $!");
    my @command = (
        '/data/codex/lib/codex',
        $self->_codex_options(),
        @arguments,
    );
    exec { $command[0] } @command
        or _fatal("cannot execute managed Codex wrapper: $!");
}

sub _codex_action {
    my ($self, $action, @arguments) = @_;
    if ($action eq 'codex-new-session') {
        return $self->_exec_codex();
    }
    if ($action eq 'codex-resume-last') {
        return $self->_exec_codex('resume', '--last');
    }
    if ($action eq 'codex-resume-picker') {
        return $self->_exec_codex('resume');
    }
    if ($action eq 'codex-task') {
        my $prompt = _assert_text('Codex prompt', $arguments[0], 16_384);
        return $self->_exec_codex($prompt);
    }
    if ($action eq 'codex-set-project') {
        my $project = $self->_project_path($arguments[0]);
        $self->state()->mutate(sub {
            my ($document) = @_;
            $document->{codex}{project} = $project;
            $self->state()->remember_unique(
                $document->{codex}{recent_projects},
                $project,
                20,
            );
        });
        $self->_notify('Codex project selected', $project);
        return 1;
    }
    if ($action eq 'codex-set-model') {
        my $model = _assert_text('Codex model', $arguments[0], 128);
        if ($model eq 'default') {
            $model = q{};
        }
        else {
            $model =~ /\A[A-Za-z0-9][A-Za-z0-9._:\/-]{0,127}\z/
                or _fatal('Codex model identifier is invalid');
        }
        $self->state()->mutate(sub {
            $_[0]->{codex}{model} = $model;
        });
        $self->_notify(
            'Codex model updated',
            length($model) ? $model : 'Managed default model',
        );
        return 1;
    }
    if ($action eq 'codex-set-reasoning') {
        my $effort = _assert_text('Codex reasoning effort', $arguments[0], 16);
        $effort =~ /\A(?:default|low|medium|high|xhigh)\z/
            or _fatal('Codex reasoning effort is invalid');
        $self->state()->mutate(sub {
            $_[0]->{codex}{reasoning} = $effort;
        });
        $self->_notify('Codex reasoning updated', $effort);
        return 1;
    }
    if ($action eq 'codex-clear-recent-projects') {
        $self->state()->mutate(sub {
            $_[0]->{codex}{recent_projects} = [];
        });
        $self->_notify('Codex launcher state', 'Recent project list cleared');
        return 1;
    }
    if ($action eq 'codex-open-project-terminal') {
        my $project = $self->_codex_project();
        chdir $project
            or _fatal("cannot enter Codex project: $!");
        exec { $self->terminal() } $self->terminal()
            or _fatal("cannot open project terminal: $!");
    }
    if ($action eq 'codex-open-home-terminal') {
        chdir '/data/codex/usr/home'
            or _fatal("cannot enter managed Codex home: $!");
        exec { $self->terminal() } $self->terminal()
            or _fatal("cannot open Codex home terminal: $!");
    }
    if ($action eq 'codex-diagnostic') {
        return $self->_codex_diagnostic($arguments[0]);
    }
    _fatal('unsupported Codex action');
}

sub _list_directory {
    my ($self, $directory, $maximum) = @_;
    -d $directory && !-l $directory
        or return ();
    opendir my $dh, $directory
        or _fatal("cannot inspect directory: $directory");
    my @entries;
    while (my $entry = readdir $dh) {
        next if $entry eq '.' || $entry eq '..';
        push @entries, $entry;
        @entries <= $maximum
            or _fatal("directory contains more than $maximum entries: $directory");
    }
    closedir $dh
        or _fatal("cannot close directory: $directory");
    return sort @entries;
}

sub _codex_diagnostic {
    my ($self, $kind) = @_;
    my $project = $self->_codex_project();
    my $codex = $self->state()->document()->{codex};
    if ($kind eq 'current-project') {
        _print_title('Current Codex Project');
        print "$project\n";
    }
    elsif ($kind eq 'git-status') {
        _print_title('Git Status');
        print $self->_capture(1_048_576, '/usr/bin/git', '-C', $project,
            'status', '--short', '--branch');
    }
    elsif ($kind eq 'project-files') {
        _print_title('Project Files');
        print "$_\n" for $self->_list_directory($project, 500);
    }
    elsif ($kind eq 'project-agents') {
        _print_title('Project Agent Instructions');
        my $shown = 0;
        for my $name ('AGENTS.override.md', 'AGENTS.md') {
            my $path = "$project/$name";
            next if !-f $path || -l $path;
            print "--- $path ---\n";
            print $self->_read_file($path, 262_144, 1);
            $shown = 1;
        }
        print "No project-local AGENTS file was found.\n" if !$shown;
    }
    elsif ($kind eq 'recent-projects') {
        _print_title('Recent Codex Projects');
        print "$_\n" for @{$codex->{recent_projects}};
        print "No recent projects recorded.\n" if !@{$codex->{recent_projects}};
    }
    elsif ($kind eq 'model-settings') {
        _print_title('Codex Model & Reasoning');
        printf "Model: %s\n", length($codex->{model}) ? $codex->{model} : 'managed default';
        print "Reasoning effort: $codex->{reasoning}\n";
    }
    elsif ($kind eq 'skills') {
        _print_title('Installed Codex Skills');
        print "$_\n" for $self->_list_directory('/data/codex/usr/skills', 500);
    }
    elsif ($kind eq 'codex-home') {
        _print_title('Codex Home');
        print "/data/codex/usr/home\n";
    }
    elsif ($kind eq 'memories') {
        _print_title('Codex Memory Directory');
        print "/data/codex/usr/home/memories\n";
    }
    elsif ($kind eq 'config-files') {
        _print_title('Codex Configuration Files');
        print "$_\n" for $self->_list_directory('/etc/codex', 200);
    }
    elsif ($kind eq 'wrapper' || $kind eq 'health') {
        _print_title('Managed Codex Wrapper Health');
        for my $path (
            '/data/codex/lib/codex',
            '/data/codex/share/bin/codex',
            '/data/codex/usr/home',
            '/data/codex/runtime',
        ) {
            printf "%-38s %s\n", $path,
                (-e $path && !-l $path ? 'available' : 'missing or unsafe');
        }
        print "Project: $project\n";
    }
    elsif ($kind eq 'runtime-paths' || $kind eq 'session-storage') {
        _print_title('Codex Runtime Paths');
        print <<'EOF';
Wrapper:        /data/codex/lib/codex
Binary:         /data/codex/share/bin/codex
Home:           /data/codex/usr/home
Sessions:       /data/codex/usr/home/sessions
Archived:       /data/codex/usr/home/archived_sessions
Runtime:        /data/codex/runtime
Logs:           /data/codex/log
SQLite:         /data/codex/sqlite
EOF
    }
    elsif ($kind eq 'session-index') {
        _print_title('Recent Codex Session Index');
        my $path = '/data/codex/usr/home/session_index.jsonl';
        my $content = $self->_read_file($path, 1_048_576, 1);
        print $self->_tail_text($content, 40);
    }
    elsif ($kind eq 'recent-logs') {
        _print_title('Recent Codex Logs');
        my @logs = grep { /\.log\z/ } $self->_list_directory('/data/codex/log', 200);
        print "$_\n" for @logs;
        print "No managed Codex log files found.\n" if !@logs;
    }
    elsif ($kind eq 'version') {
        _print_title('Codex Version');
        print $self->_capture(262_144, '/data/codex/lib/codex', '--version');
    }
    elsif ($kind eq 'help') {
        _print_title('Codex Help');
        print $self->_capture(1_048_576, '/data/codex/lib/codex', '--help');
    }
    else {
        _fatal('unsupported Codex diagnostic');
    }
    return _pause();
}

sub _root_config {
    my ($self, $path, $allowed) = @_;
    my $content = $self->_read_file($path, 65_536, 0);
    my %values;
    for my $line (split /\n/, $content) {
        next if $line =~ /\A(?:#|\s*\z)/;
        my ($key, $value) = $line =~ /\A([A-Z0-9_]+)=(.*)\z/
            or _fatal("managed configuration is malformed: $path");
        $allowed->{$key}
            or _fatal("managed configuration contains an unsupported key: $path");
        !exists($values{$key})
            or _fatal("managed configuration repeats a key: $path");
        $value !~ /[\0\r\n]/
            or _fatal("managed configuration contains control characters: $path");
        $values{$key} = $value;
    }
    return \%values;
}

sub _llama_config {
    my ($self) = @_;
    my %allowed = map { $_ => 1 } qw(
      LLAMA_MODEL LLAMA_CONTEXT_SIZE LLAMA_BATCH_SIZE LLAMA_UBATCH_SIZE
      LLAMA_THREADS LLAMA_THREADS_BATCH LLAMA_GPU_LAYERS LLAMA_KV_OFFLOAD
      LLAMA_PARALLEL LLAMA_SERVER_HOST LLAMA_SERVER_PORT
    );
    my $config = $self->_root_config('/etc/llama/llama.conf', \%allowed);
    ($config->{LLAMA_SERVER_HOST} // q{}) eq '127.0.0.1'
        or _fatal('managed Llama server host must be 127.0.0.1');
    my $port = $config->{LLAMA_SERVER_PORT} // q{};
    $port =~ /\A[0-9]{1,5}\z/ && $port >= 1 && $port <= 65_535
        or _fatal('managed Llama server port is invalid');
    return $config;
}

sub _llama_environment {
    my ($self) = @_;
    my $runtime = $self->state()->document()->{llama}{runtime};
    my %environment = (
        LLAMA_ARG_MODEL => $self->models()->active_model(),
    );
    $environment{LLAMA_ARG_CTX_SIZE} = $runtime->{context}
        if $runtime->{context};
    $environment{LLAMA_ARG_THREADS} = $runtime->{threads}
        if $runtime->{threads};
    $environment{LLAMA_ARG_BATCH} = $runtime->{batch}
        if $runtime->{batch};
    $environment{LLAMA_ARG_N_GPU_LAYERS} = $runtime->{gpu_layers}
        if $runtime->{gpu_layers_overridden};
    return %environment;
}

sub _preset_prompt {
    my ($preset) = @_;
    my %prompts = (
        coding          => 'Act as a careful coding assistant. Prefer correct, secure, maintainable changes.',
        'code-review'   => 'Review code for correctness, regressions, maintainability, and missing tests.',
        'security-review' => 'Perform a defensive security review. Identify trust boundaries and concrete mitigations.',
        'deep-reasoning'  => 'Reason step by step internally and provide a concise, evidence-based conclusion.',
        'concise-summary' => 'Summarize the material facts and next actions concisely.',
        brainstorm        => 'Generate several practical options, compare tradeoffs, and recommend one.',
        'shell-safety'    => 'Review shell code for quoting, injection, path, privilege, and destructive-operation risks.',
    );
    return $prompts{$preset} // q{};
}

sub _combined_llama_prompt {
    my ($self, $prompt) = @_;
    my $llama = $self->state()->document()->{llama};
    my @parts;
    push @parts, $llama->{system_prompt} if length($llama->{system_prompt});
    my $preset = _preset_prompt($llama->{preset});
    push @parts, $preset if length($preset);
    if ($llama->{persistent_memory}) {
        my @history = @{$llama->{prompt_history}};
        splice @history, 5 if @history > 5;
        if (@history) {
            push @parts, "Recent local prompts:\n"
                . join("\n", map { '- ' . $_->{prompt} } reverse @history);
        }
    }
    push @parts, $prompt if defined($prompt) && length($prompt);
    my $combined = join("\n\n", @parts);
    length($combined) <= 32_768
        or _fatal('combined Llama prompt exceeds the safety limit');
    return $combined;
}

sub _exec_llama {
    my ($self, @arguments) = @_;
    local %ENV = (%ENV, $self->_llama_environment());
    my @command = ('/data/llama/lib/llama', @arguments);
    exec { $command[0] } @command
        or _fatal("cannot execute managed Llama wrapper: $!");
}

sub _remember_model {
    my ($self, $model, $set_active) = @_;
    $self->state()->mutate(sub {
        my ($document) = @_;
        $document->{llama}{active_model} = $model if $set_active;
        $self->state()->remember_unique(
            $document->{llama}{recent_models},
            $model,
            20,
        );
    });
    return 1;
}

sub _percent_encode {
    my ($value) = @_;
    my $bytes = encode('UTF-8', $value);
    $bytes =~ s/([^A-Za-z0-9_.~-])/sprintf('%%%02X', ord($1))/ge;
    return $bytes;
}

sub _print_catalog_entry {
    my ($entry) = @_;
    print "Model: $entry->{display_name}\n";
    print "Language: $entry->{language}\n";
    print "Parameters: $entry->{parameters}\n";
    print "Weights: $entry->{weights}\n";
    print "Approximate file size: $entry->{file_mib} MiB\n";
    print "Estimated RAM: $entry->{min_ram_gib} GiB minimum; ",
        "$entry->{recommended_ram_gib} GiB recommended\n";
    print "Recommended CPU cores: $entry->{cpu_cores}\n";
    print "Notes: $entry->{notes}\n";
    print "Pinned source: $entry->{repository} at $entry->{revision}\n\n";
    return 1;
}

sub _llama_action {
    my ($self, $action, @arguments) = @_;
    if ($action eq 'llama-ask') {
        my $prompt = _assert_text('Llama prompt', $arguments[0], 16_384);
        my $combined = $self->_combined_llama_prompt($prompt);
        $self->state()->append_prompt($prompt);
        return $self->_exec_llama('cli', '-i', '-p', $combined);
    }
    if ($action eq 'llama-new-chat') {
        my $combined = $self->_combined_llama_prompt(q{});
        return length($combined)
            ? $self->_exec_llama('cli', '-i', '-p', $combined)
            : $self->_exec_llama('cli');
    }
    if ($action eq 'llama-resume-last-chat') {
        my $history = $self->state()->document()->{llama}{prompt_history};
        @{$history}
            or _fatal('there is no remembered Llama prompt to resume');
        my $combined = $self->_combined_llama_prompt($history->[0]{prompt});
        return $self->_exec_llama('cli', '-i', '-p', $combined);
    }
    if ($action eq 'llama-set-active-model' || $action eq 'llama-set-default-model') {
        my $model = $self->models()->validate_model($arguments[0]);
        $self->state()->mutate(sub {
            my ($document) = @_;
            if ($action eq 'llama-set-active-model') {
                $document->{llama}{active_model} = $model;
            }
            else {
                $document->{llama}{default_model} = $model;
            }
            $self->state()->remember_unique(
                $document->{llama}{recent_models},
                $model,
                20,
            );
        });
        $self->_notify(
            $action eq 'llama-set-active-model'
                ? 'Llama model selected'
                : 'Llama default model updated',
            basename($model),
        );
        return 1;
    }
    if ($action eq 'llama-set-model-alias') {
        my $alias = _assert_text('model alias', $arguments[0], 32);
        $alias =~ /\A[A-Za-z0-9][A-Za-z0-9._-]{0,31}\z/
            or _fatal('model alias is invalid');
        my $model = $self->models()->validate_model($arguments[1]);
        $self->state()->mutate(sub {
            $_[0]->{llama}{aliases}{$alias} = $model;
        });
        $self->_notify('Llama model alias updated', "$alias → " . basename($model));
        return 1;
    }
    if ($action eq 'llama-download-catalog-model') {
        _print_title('Curated GGUF Download');
        my $entry = $self->models()->catalog_entry('llama', $arguments[0]);
        _print_catalog_entry($entry);
        my $model = $self->models()->download_catalog($entry->{id});
        $self->_remember_model($model, 1);
        print "Installed: $model\n";
        $self->_notify('Llama model installed', basename($model));
        return _pause();
    }
    if ($action eq 'llama-download-model') {
        _print_title('Verified GGUF Download');
        my $model = $self->models()->download(@arguments);
        $self->_remember_model($model, 1);
        print "Installed: $model\n";
        $self->_notify('Llama model installed', basename($model));
        return _pause();
    }
    if ($action eq 'llama-open-model-search') {
        my $category = _assert_text('model search category', $arguments[0], 32);
        my %queries = (
            recommended => 'GGUF instruct',
            coding      => 'coding GGUF',
            reasoning   => 'reasoning GGUF',
            'small-fast'=> 'small fast GGUF',
            vision      => 'vision GGUF',
            embedding   => 'embedding GGUF',
            recent      => 'GGUF',
        );
        my $query;
        if ($category eq 'search') {
            $query = _assert_text('model search query', $arguments[1], 256);
        }
        else {
            exists($queries{$category})
                or _fatal('unsupported model search category');
            $query = $queries{$category};
        }
        my $sort = $category eq 'recent' ? 'modified' : 'trending';
        my $url = 'https://huggingface.co/models?library=gguf&sort='
            . $sort . '&search=' . _percent_encode($query);
        return $self->_run('/usr/bin/xdg-open', $url);
    }
    if ($action eq 'llama-favorite') {
        my $mode = _assert_text('favorite action', $arguments[0], 16);
        $mode =~ /\A(?:add|remove)\z/
            or _fatal('favorite action is invalid');
        my $model = $self->models()->active_model();
        $self->state()->mutate(sub {
            my ($document) = @_;
            my @favorites = grep { $_ ne $model } @{$document->{llama}{favorite_models}};
            unshift @favorites, $model if $mode eq 'add';
            splice @favorites, 32 if @favorites > 32;
            $document->{llama}{favorite_models} = \@favorites;
        });
        $self->_notify(
            'Llama favorites updated',
            ($mode eq 'add' ? 'Added ' : 'Removed ') . basename($model),
        );
        return 1;
    }
    if ($action eq 'llama-memory') {
        my $mode = _assert_text('memory action', $arguments[0], 16);
        $mode =~ /\A(?:enable|disable|clear)\z/
            or _fatal('memory action is invalid');
        $self->state()->mutate(sub {
            my ($document) = @_;
            if ($mode eq 'clear') {
                $document->{llama}{prompt_history} = [];
            }
            else {
                $document->{llama}{persistent_memory} = $mode eq 'enable' ? 1 : 0;
            }
        });
        $self->_notify(
            'Llama persistent prompt memory',
            $mode eq 'clear' ? 'Remembered prompts cleared' : ucfirst($mode) . 'd',
        );
        return 1;
    }
    if ($action eq 'llama-clear-chat-history') {
        $self->state()->mutate(sub {
            $_[0]->{llama}{prompt_history} = [];
        });
        $self->_notify('Llama chat history', 'Local prompt history cleared');
        return 1;
    }
    if ($action eq 'llama-set-system-prompt') {
        my $prompt = _assert_text('system prompt', $arguments[0], 8192);
        $prompt = q{} if $prompt eq 'clear';
        $self->state()->mutate(sub {
            $_[0]->{llama}{system_prompt} = $prompt;
        });
        $self->_notify(
            'Llama system prompt',
            length($prompt) ? 'Updated' : 'Cleared',
        );
        return 1;
    }
    if ($action eq 'llama-set-preset') {
        my $preset = _assert_text('prompt preset', $arguments[0], 32);
        $preset = q{} if $preset eq 'clear';
        $preset =~ /\A(?:|coding|code-review|security-review|deep-reasoning|concise-summary|brainstorm|shell-safety)\z/
            or _fatal('prompt preset is invalid');
        $self->state()->mutate(sub {
            $_[0]->{llama}{preset} = $preset;
        });
        $self->_notify(
            'Llama prompt preset',
            length($preset) ? $preset : 'Cleared',
        );
        return 1;
    }
    if ($action eq 'llama-set-runtime') {
        my ($key, $value) = @arguments;
        my %limits = (
            context      => [512, 1_048_576, 'context'],
            threads      => [1, 256, 'threads'],
            batch        => [1, 32_768, 'batch'],
            'gpu-layers' => [0, 999, 'gpu_layers'],
        );
        exists($limits{$key})
            or _fatal('unsupported Llama runtime setting');
        $value =~ /\A[0-9]{1,7}\z/
            or _fatal('Llama runtime value is not an integer');
        my ($minimum, $maximum, $state_key) = @{$limits{$key}};
        $value >= $minimum && $value <= $maximum
            or _fatal("Llama runtime value must be $minimum-$maximum");
        $self->state()->mutate(sub {
            $_[0]->{llama}{runtime}{$state_key} = int($value);
            $_[0]->{llama}{runtime}{gpu_layers_overridden} = 1
                if $state_key eq 'gpu_layers';
        });
        $self->_notify('Llama runtime updated', "$key=$value");
        return 1;
    }
    if ($action eq 'llama-performance-preset') {
        my $preset = _assert_text('performance preset', $arguments[0], 32);
        my %presets = (
            balanced       => {
                context               => 8192,
                threads               => 4,
                batch                 => 256,
                gpu_layers            => 0,
                gpu_layers_overridden => 1,
            },
            'low-memory'   => {
                context               => 4096,
                threads               => 2,
                batch                 => 128,
                gpu_layers            => 0,
                gpu_layers_overridden => 1,
            },
            'high-context' => {
                context               => 32768,
                threads               => 4,
                batch                 => 128,
                gpu_layers            => 0,
                gpu_layers_overridden => 1,
            },
        );
        exists($presets{$preset})
            or _fatal('unsupported Llama performance preset');
        $self->state()->mutate(sub {
            $_[0]->{llama}{runtime} = { %{$presets{$preset}} };
        });
        $self->_notify('Llama performance preset', $preset);
        return 1;
    }
    if ($action eq 'llama-reset-runtime') {
        $self->state()->mutate(sub {
            $_[0]->{llama}{runtime} = {
                context               => 0,
                threads               => 0,
                batch                 => 0,
                gpu_layers            => 0,
                gpu_layers_overridden => 0,
            };
        });
        $self->_notify('Llama runtime', 'Managed defaults restored');
        return 1;
    }
    if ($action eq 'llama-start-server') {
        $self->_run(
            '/usr/bin/systemctl',
            '--user',
            'start',
            'llama-server.service',
        );
        $self->_notify('Llama server', 'Started llama-server.service');
        return 1;
    }
    if ($action eq 'llama-stop-server') {
        $self->_run(
            '/usr/bin/systemctl',
            '--user',
            'stop',
            'llama-server.service',
        );
        $self->_notify('Llama server', 'Stopped llama-server.service');
        return 1;
    }
    if ($action eq 'llama-prune-partials') {
        $self->models()->prune_partials();
        $self->_notify('Llama storage cleanup', 'Verified partial downloads pruned');
        return 1;
    }
    if ($action eq 'llama-model-info') {
        my $field = _assert_text('model information field', $arguments[0], 32);
        $field =~ /\A(?:details|license|architecture|parameter-count|quantization|size|context-length|location)\z/
            or _fatal('model information field is invalid');
        my $model = $arguments[1] eq 'active'
            ? $self->models()->active_model()
            : $self->models()->validate_model($arguments[1]);
        _print_title('GGUF Model Information');
        $self->_run('/usr/local/libexec/labwc-ai-model-info',
            '--field', $field, $model);
        return _pause();
    }
    if ($action eq 'llama-diagnostic') {
        return $self->_llama_diagnostic($arguments[0]);
    }
    _fatal('unsupported Llama action');
}

sub _format_bytes {
    my ($bytes) = @_;
    return "$bytes B" if $bytes < 1024;
    return sprintf('%.2f KiB', $bytes / 1024) if $bytes < 1_048_576;
    return sprintf('%.2f MiB', $bytes / 1_048_576) if $bytes < 1_073_741_824;
    return sprintf('%.2f GiB', $bytes / 1_073_741_824);
}

sub _llama_diagnostic {
    my ($self, $kind) = @_;
    my $llama = $self->state()->document()->{llama};
    if ($kind eq 'installed-models') {
        _print_title('Installed GGUF Models');
        my @models = $self->models()->list_models();
        print "$_\n" for @models;
        print "No validated GGUF models found.\n" if !@models;
    }
    elsif ($kind eq 'favorites') {
        _print_title('Favorite Models');
        print "$_\n" for @{$llama->{favorite_models}};
        print "No favorite models recorded.\n" if !@{$llama->{favorite_models}};
    }
    elsif ($kind eq 'recent-models') {
        _print_title('Recent Models');
        print "$_\n" for @{$llama->{recent_models}};
        print "No recent models recorded.\n" if !@{$llama->{recent_models}};
    }
    elsif ($kind eq 'memory-status') {
        _print_title('Persistent Prompt Memory');
        print $llama->{persistent_memory} ? "Enabled\n" : "Disabled\n";
        print scalar(@{$llama->{prompt_history}}) . " prompts retained locally\n";
    }
    elsif ($kind eq 'remembered-prompts' || $kind eq 'recent-chats') {
        _print_title('Recent Local Llama Prompts');
        for my $entry (@{$llama->{prompt_history}}) {
            print scalar(localtime($entry->{created_at})) . "  $entry->{prompt}\n";
        }
        print "No prompts retained.\n" if !@{$llama->{prompt_history}};
    }
    elsif ($kind eq 'last-prompt') {
        _print_title('Last Llama Prompt');
        print @{$llama->{prompt_history}}
            ? "$llama->{prompt_history}[0]{prompt}\n"
            : "No prompts retained.\n";
    }
    elsif ($kind eq 'system-prompt') {
        _print_title('Llama System Prompt');
        print length($llama->{system_prompt})
            ? "$llama->{system_prompt}\n"
            : "No custom system prompt configured.\n";
    }
    elsif ($kind eq 'active-preset') {
        _print_title('Llama Prompt Preset');
        print length($llama->{preset}) ? "$llama->{preset}\n" : "No preset selected.\n";
    }
    elsif ($kind eq 'runtime' || $kind eq 'performance') {
        _print_title('Llama Runtime Overrides');
        for my $key (qw(context threads batch)) {
            my $value = $llama->{runtime}{$key};
            printf "%-12s %s\n", $key, $value ? $value : 'managed default';
        }
        printf "%-12s %s\n", 'gpu_layers',
            $llama->{runtime}{gpu_layers_overridden}
                ? $llama->{runtime}{gpu_layers}
                : 'managed default';
    }
    elsif ($kind eq 'active-model') {
        _print_title('Active Llama Model');
        print $self->models()->active_model(), "\n";
    }
    elsif ($kind eq 'version') {
        _print_title('Llama Version');
        print $self->_capture(262_144, '/data/llama/lib/llama', '--version');
    }
    elsif ($kind eq 'help') {
        _print_title('Llama CLI Help');
        print $self->_capture(1_048_576, '/data/llama/lib/llama', '--help');
    }
    elsif ($kind eq 'server-help') {
        _print_title('Llama Server Help');
        print $self->_capture(1_048_576, '/data/llama/lib/llama', 'server', '--help');
    }
    elsif ($kind eq 'server-status') {
        _print_title('Llama Server Status');
        print $self->_capture_allow_failure(
            262_144,
            '/usr/bin/systemctl',
            '--user',
            'status',
            '--no-pager',
            'llama-server.service',
        );
    }
    elsif ($kind eq 'server-config' || $kind eq 'server-endpoint') {
        my $config = $self->_llama_config();
        _print_title('Llama Server Configuration');
        print "Host: $config->{LLAMA_SERVER_HOST}\n";
        print "Port: $config->{LLAMA_SERVER_PORT}\n";
        print "Endpoint: http://$config->{LLAMA_SERVER_HOST}:$config->{LLAMA_SERVER_PORT}\n";
        print "User unit: llama-server.service (started on demand)\n";
    }
    elsif ($kind eq 'model-directories' || $kind eq 'download-directory') {
        _print_title('Llama Model Directories');
        print "Managed and downloaded: /pool/cache/llama/models\n";
    }
    elsif ($kind eq 'storage-usage') {
        _print_title('Llama Model Storage');
        my $total = 0;
        for my $model ($self->models()->list_models()) {
            my @stat = lstat $model;
            $total += $stat[7];
            printf "%12s  %s\n", _format_bytes($stat[7]), $model;
        }
        print "Total: ", _format_bytes($total), "\n";
    }
    elsif ($kind eq 'state-file') {
        _print_title('AI & Copilots State');
        print $self->state()->settings_path(), "\n";
    }
    elsif ($kind eq 'wrapper-config') {
        _print_title('Managed Llama Configuration');
        print $self->_read_file('/etc/llama/llama.conf', 65_536, 0);
    }
    elsif ($kind eq 'health') {
        _print_title('Managed Llama Health');
        for my $path (
            '/data/llama/lib/llama',
            '/data/llama/bin/llama-cli',
            '/data/llama/bin/llama-server',
            '/usr/local/libexec/labwc-ai-llama-server',
            '/etc/llama/llama.conf',
            $self->session()->home() . '/.config/systemd/user/llama-server.service',
            $self->models()->active_model(),
        ) {
            printf "%-48s %s\n", $path,
                (-e $path && !-l $path ? 'available' : 'missing or unsafe');
        }
    }
    else {
        _fatal('unsupported Llama diagnostic');
    }
    return _pause();
}

sub _whisper_config {
    my ($self) = @_;
    my %allowed = map { $_ => 1 } qw(
      WHISPER_CLI WHISPER_SERVER WHISPER_MODEL WHISPER_RUNTIME_THREADS
      WHISPER_PERSISTENT_MEM
    );
    return $self->_root_config('/etc/whisper/whisper.conf', \%allowed);
}

sub _whisper_directory {
    my ($self, $kind) = @_;
    my $root = $self->session()->home() . '/Music/Whisper';
    my $directory = $kind eq 'audio' ? "$root/audio"
        : $kind eq 'transcribed' ? "$root/transcribed"
        : _fatal('unsupported Whisper directory');
    for my $path (
        $self->session()->home() . '/Music',
        $root,
        $directory,
    ) {
        if (!-e $path && !-l $path) {
            make_path($path, { mode => 0700 })
                or _fatal("cannot create Whisper directory: $path");
        }
        -d $path && !-l $path
            or _fatal("Whisper directory is unsafe: $path");
        my @stat = lstat $path;
        $stat[4] == $<
            or _fatal("Whisper directory ownership is unsafe: $path");
    }
    chmod 0700, $root, $directory
        or _fatal("cannot secure Whisper directory: $!");
    return $directory;
}

sub _recent_files {
    my ($self, $directory, $pattern, $maximum) = @_;
    return () if !-d $directory || -l $directory;
    opendir my $dh, $directory
        or _fatal("cannot inspect Whisper history: $!");
    my @files;
    while (my $entry = readdir $dh) {
        next if $entry !~ $pattern;
        my $path = "$directory/$entry";
        next if !-f $path || -l $path;
        my @stat = lstat $path;
        next if $stat[4] != $< || ($stat[2] & 0022) != 0;
        push @files, [$stat[9], $path];
        @files <= 500
            or _fatal('Whisper history exceeds the safety entry limit');
    }
    closedir $dh
        or _fatal("cannot close Whisper history: $!");
    @files = sort { $b->[0] <=> $a->[0] || $a->[1] cmp $b->[1] } @files;
    splice @files, $maximum if @files > $maximum;
    return map { $_->[1] } @files;
}

sub _latest_whisper_file {
    my ($self, $kind) = @_;
    my ($directory, $pattern) = $kind eq 'audio'
        ? ($self->_whisper_directory('audio'), qr/\.(?:flac|m4a|mp3|ogg|opus|wav)\z/i)
        : ($self->_whisper_directory('transcribed'), qr/\.txt\z/i);
    my @files = $self->_recent_files($directory, $pattern, 1);
    @files
        or _fatal("no recent Whisper $kind file is available");
    return $files[0];
}

sub _validate_audio_file {
    my ($self, $path) = @_;
    _assert_text('audio file path', $path, 4096);
    $path =~ m{\A/} && $path !~ m{(?:\A|/)\.\.(?:/|\z)|//}
        or _fatal('audio file path is invalid');
    -f $path && !-l $path && -r $path
        or _fatal('audio file must be a readable regular file');
    my $resolved = abs_path($path);
    defined($resolved) && $resolved eq $path
        or _fatal('audio file path must already be canonical');
    my $home = $self->session()->home();
    index($resolved, "$home/") == 0
        or _fatal('audio file must remain below HOME');
    $resolved =~ /\.(?:flac|m4a|mp3|ogg|opus|wav)\z/i
        or _fatal('audio file extension is unsupported');
    my @stat = lstat $resolved;
    $stat[4] == $< && ($stat[2] & 0022) == 0
        && $stat[7] > 0 && $stat[7] <= 2_147_483_648
        or _fatal('audio file ownership, mode, or size is unsafe');
    return $resolved;
}

sub _write_text_file {
    my ($self, $path, $content) = @_;
    my $directory = File::Basename::dirname($path);
    my ($fh, $temporary) = tempfile('.transcript.XXXXXX',
        DIR => $directory, UNLINK => 0);
    binmode $fh, ':encoding(UTF-8)';
    print {$fh} $content
        or _fatal("cannot write transcript: $!");
    close $fh
        or _fatal("cannot close transcript: $!");
    chmod 0600, $temporary
        or _fatal("cannot secure transcript: $!");
    rename $temporary, $path
        or _fatal("cannot publish transcript: $!");
    return 1;
}

sub _copy_to_clipboard {
    my ($self, $text) = @_;
    open my $fh, '|-', '/usr/bin/wl-copy'
        or _fatal("cannot start Wayland clipboard helper: $!");
    binmode $fh, ':encoding(UTF-8)';
    print {$fh} $text
        or _fatal("cannot write transcript to clipboard: $!");
    close $fh
        or _fatal('Wayland clipboard helper failed');
    return 1;
}

sub _transcribe_audio {
    my ($self, $requested) = @_;
    my $audio = $self->_validate_audio_file($requested);
    my $whisper = $self->state()->document()->{whisper};
    my $directory = $self->_whisper_directory('transcribed');
    my $stem = basename($audio);
    $stem =~ s/\.[^.]+\z//;
    $stem =~ s/[^A-Za-z0-9._-]+/_/g;
    $stem = substr($stem, 0, 48);
    $stem = 'audio' if !length($stem);
    my $timestamp = strftime('%Y%m%d-%H%M%S', localtime());
    my $base = "$directory/${stem}-launcher-${timestamp}-$$";
    my @command = (
        '/usr/local/libexec/whisper-cli-default-model',
        '--model', $self->_whisper_model(),
        '-f', $audio,
        '-otxt',
        '-of', $base,
    );
    push @command, '-l', $whisper->{language}
        if $whisper->{language} ne 'auto';
    $self->_run(@command);
    my $transcript = "$base.txt";
    -f $transcript && !-l $transcript
        or _fatal('Whisper did not create the expected transcript');
    my $text = $self->_read_file($transcript, 16_777_216, 1);
    if ($whisper->{post_processing} eq 'normalize') {
        $text =~ s/\r\n?/\n/g;
        $text =~ s/[ \t]+/ /g;
        $text =~ s/ *\n */\n/g;
        $text =~ s/\n{3,}/\n\n/g;
        $text =~ s/\A\s+|\s+\z//g;
        $text .= "\n" if length($text);
        $self->_write_text_file($transcript, $text);
    }
    if ($whisper->{output} eq 'clipboard' || $whisper->{output} eq 'both') {
        $self->_copy_to_clipboard($text);
    }
    if ($whisper->{output} eq 'clipboard') {
        unlink $transcript
            or _fatal("cannot remove clipboard-only transcript: $!");
        print "Transcript copied to the Wayland clipboard.\n";
    }
    else {
        print "Saved transcript: $transcript\n";
        print "Transcript also copied to the Wayland clipboard.\n"
            if $whisper->{output} eq 'both';
    }
    return 1;
}

sub _whisper_action {
    my ($self, $action, @arguments) = @_;
    if ($action eq 'whisper-control') {
        my $mode = _assert_text('Whisper control action', $arguments[0], 16);
        $mode =~ /\A(?:start|stop|toggle)\z/
            or _fatal('Whisper control action is invalid');
        return $self->_run('/usr/local/libexec/whisper-record-toggle', $mode);
    }
    if ($action eq 'whisper-dictation') {
        $arguments[0] eq 'toggle'
            or _fatal('Whisper dictation action is invalid');
        return $self->_run('/usr/local/bin/labwc-wayscriber-toggle');
    }
    if ($action eq 'whisper-transcribe-file') {
        _print_title('Whisper File Transcription');
        $self->_transcribe_audio($arguments[0]);
        return _pause();
    }
    if ($action eq 'whisper-transcribe-last') {
        _print_title('Whisper Last Recording Transcription');
        $self->_transcribe_audio($self->_latest_whisper_file('audio'));
        return _pause();
    }
    if ($action eq 'whisper-set-active-model') {
        my $model = $self->models()->validate_whisper_model($arguments[0]);
        $self->state()->mutate(sub {
            $_[0]->{whisper}{active_model} = $model;
        });
        $self->_notify('Whisper launcher model selected', basename($model));
        return 1;
    }
    if ($action eq 'whisper-download-catalog-model') {
        _print_title('Curated Whisper Model Download');
        my $entry = $self->models()->catalog_entry('whisper', $arguments[0]);
        _print_catalog_entry($entry);
        my $model = $self->models()->download_whisper_catalog($entry->{id});
        $self->state()->mutate(sub {
            $_[0]->{whisper}{active_model} = $model;
        });
        print "Installed: $model\n";
        print "Launcher file transcription now uses this model.\n";
        print "Managed recording services retain the profile-configured default.\n";
        $self->_notify('Whisper model installed', basename($model));
        return _pause();
    }
    if ($action eq 'whisper-download-model') {
        _print_title('Verified Whisper Model Download');
        my $model = $self->models()->download_whisper(@arguments);
        $self->state()->mutate(sub {
            $_[0]->{whisper}{active_model} = $model;
        });
        print "Installed: $model\n";
        print "Launcher file transcription now uses this model.\n";
        print "Managed recording services retain the profile-configured default.\n";
        $self->_notify('Whisper model installed', basename($model));
        return _pause();
    }
    if ($action eq 'whisper-prune-partials') {
        $self->models()->prune_whisper_partials();
        $self->_notify('Whisper storage cleanup', 'Verified partial downloads pruned');
        return 1;
    }
    if ($action eq 'whisper-set-language') {
        my $language = _assert_text('Whisper language', $arguments[0], 8);
        $language =~ /\A(?:auto|[a-z]{2,3})\z/
            or _fatal('Whisper language is invalid');
        $self->state()->mutate(sub {
            $_[0]->{whisper}{language} = $language;
        });
        $self->_notify('Whisper language', $language);
        return 1;
    }
    if ($action eq 'whisper-set-output') {
        my $output = _assert_text('Whisper output mode', $arguments[0], 16);
        $output =~ /\A(?:file|clipboard|both)\z/
            or _fatal('Whisper output mode is invalid');
        $self->state()->mutate(sub {
            $_[0]->{whisper}{output} = $output;
        });
        $self->_notify('Whisper output mode', $output);
        return 1;
    }
    if ($action eq 'whisper-set-post-processing') {
        my $mode = _assert_text('Whisper post-processing mode', $arguments[0], 16);
        $mode =~ /\A(?:raw|normalize)\z/
            or _fatal('Whisper post-processing mode is invalid');
        $self->state()->mutate(sub {
            $_[0]->{whisper}{post_processing} = $mode;
        });
        $self->_notify('Whisper post-processing', $mode);
        return 1;
    }
    if ($action eq 'whisper-open') {
        my $target = _assert_text('Whisper open target', $arguments[0], 32);
        if ($target eq 'recording-folder') {
            return $self->_run('/usr/bin/xdg-open', $self->_whisper_directory('audio'));
        }
        if ($target eq 'transcript-folder') {
            return $self->_run('/usr/bin/xdg-open', $self->_whisper_directory('transcribed'));
        }
        if ($target eq 'audio-control') {
            return $self->_run('/usr/bin/pavucontrol');
        }
        _fatal('unsupported Whisper open target');
    }
    if ($action eq 'whisper-audio') {
        my $mode = _assert_text('Whisper audio action', $arguments[0], 16);
        my %value = (
            'toggle-mute' => 'toggle',
            mute          => '1',
            unmute        => '0',
        );
        exists($value{$mode})
            or _fatal('unsupported Whisper audio action');
        return $self->_run(
            '/usr/bin/wpctl',
            'set-mute',
            '@DEFAULT_AUDIO_SOURCE@',
            $value{$mode},
        );
    }
    if ($action eq 'whisper-diagnostic') {
        return $self->_whisper_diagnostic($arguments[0]);
    }
    _fatal('unsupported Whisper action');
}

sub _configured_whisper_model {
    my ($self) = @_;
    my $config = $self->_whisper_config();
    my $model = $config->{WHISPER_MODEL} // q{};
    return $self->models()->validate_whisper_model($model);
}

sub _whisper_model {
    my ($self) = @_;
    my $selected = $self->state()->document()->{whisper}{active_model};
    return $self->models()->validate_whisper_model($selected)
        if defined($selected) && length($selected);
    return $self->_configured_whisper_model();
}

sub _whisper_diagnostic {
    my ($self, $kind) = @_;
    my $whisper = $self->state()->document()->{whisper};
    if ($kind eq 'recording-status') {
        _print_title('Whisper Recording Status');
        print $self->_capture_allow_failure(262_144, '/usr/bin/systemctl', '--user',
            'status', '--no-pager', 'whisper-record.service');
    }
    elsif ($kind eq 'latest-recording') {
        _print_title('Latest Whisper Recording');
        print $self->_latest_whisper_file('audio'), "\n";
    }
    elsif ($kind eq 'latest-transcript') {
        _print_title('Latest Whisper Transcript');
        my $path = $self->_latest_whisper_file('transcribed');
        print "$path\n\n";
        print $self->_read_file($path, 16_777_216, 1);
    }
    elsif ($kind eq 'transcription-status') {
        _print_title('Whisper Transcription Service');
        print $self->_capture_allow_failure(262_144, '/usr/bin/systemctl', '--user',
            'status', '--no-pager', 'whisper-transcribe.service');
    }
    elsif ($kind eq 'language') {
        _print_title('Whisper Language');
        print "$whisper->{language}\n";
    }
    elsif ($kind eq 'output-mode') {
        _print_title('Whisper Output Mode');
        print "$whisper->{output}\n";
    }
    elsif ($kind eq 'post-processing') {
        _print_title('Whisper Post-Processing');
        print "$whisper->{post_processing}\n";
    }
    elsif ($kind eq 'model' || $kind eq 'model-location') {
        _print_title('Active Whisper Launcher Model');
        print $self->_whisper_model(), "\n";
    }
    elsif ($kind eq 'installed-models') {
        _print_title('Installed Whisper Models');
        my @models = $self->models()->list_whisper_models();
        print "$_\n" for @models;
        print "No validated Whisper models found.\n" if !@models;
    }
    elsif ($kind eq 'model-size') {
        my $model = $self->_whisper_model();
        my @stat = lstat $model;
        _print_title('Whisper Model Size');
        print _format_bytes($stat[7]), " ($stat[7] bytes)\n";
    }
    elsif ($kind eq 'model-health') {
        my $model = $self->_whisper_model();
        _print_title('Whisper Model Health');
        print "$model is a readable, root-owned, non-symbolic regular file.\n";
    }
    elsif ($kind eq 'config') {
        _print_title('Managed Whisper Configuration');
        print $self->_read_file('/etc/whisper/whisper.conf', 65_536, 0);
        print "\nLauncher language: $whisper->{language}\n";
        print "Launcher output: $whisper->{output}\n";
        print "Launcher post-processing: $whisper->{post_processing}\n";
        print "Launcher model: ", $self->_whisper_model(), "\n";
        print "Managed service default: ", $self->_configured_whisper_model(), "\n";
    }
    elsif ($kind eq 'recent-recordings') {
        _print_title('Recent Whisper Recordings');
        my @files = $self->_recent_files(
            $self->_whisper_directory('audio'),
            qr/\.(?:flac|m4a|mp3|ogg|opus|wav)\z/i,
            25,
        );
        print "$_\n" for @files;
        print "No recordings found.\n" if !@files;
    }
    elsif ($kind eq 'recent-transcripts') {
        _print_title('Recent Whisper Transcripts');
        my @files = $self->_recent_files(
            $self->_whisper_directory('transcribed'),
            qr/\.txt\z/i,
            25,
        );
        print "$_\n" for @files;
        print "No transcripts found.\n" if !@files;
    }
    elsif ($kind eq 'pipewire') {
        _print_title('PipeWire Audio Status');
        print $self->_capture(1_048_576, '/usr/bin/wpctl', 'status');
    }
    elsif ($kind eq 'default-source') {
        _print_title('Default Capture Source');
        print $self->_capture(262_144, '/usr/bin/wpctl', 'get-volume',
            '@DEFAULT_AUDIO_SOURCE@');
    }
    elsif ($kind eq 'services') {
        _print_title('Whisper User Services');
        for my $unit (
            'whisper-record.service',
            'whisper-transcribe.service',
            'whisper-server.service',
            'wayscriber.service',
        ) {
            my $status = system {
                '/usr/bin/systemctl'
            } '/usr/bin/systemctl', '--user', '--quiet', 'is-active', $unit;
            printf "%-32s %s\n", $unit, $status == 0 ? 'active' : 'inactive';
        }
    }
    elsif ($kind eq 'logs') {
        _print_title('Recent Whisper Logs');
        print $self->_capture(
            1_048_576,
            '/usr/bin/journalctl',
            '--user',
            '--no-pager',
            '-n', '100',
            '-u', 'whisper-record.service',
            '-u', 'whisper-transcribe.service',
            '-u', 'whisper-server.service',
        );
    }
    elsif ($kind eq 'server-status') {
        _print_title('Persistent Whisper Server');
        print $self->_capture_allow_failure(262_144, '/usr/bin/systemctl', '--user',
            'status', '--no-pager', 'whisper-server.service');
    }
    elsif ($kind eq 'help') {
        _print_title('Whisper CLI Help');
        print $self->_capture(
            1_048_576,
            '/usr/local/libexec/whisper-cli-default-model',
            '--help',
        );
    }
    elsif ($kind eq 'health') {
        _print_title('Whisper Health');
        for my $path (
            '/usr/local/libexec/whisper-record-toggle',
            '/usr/local/libexec/whisper-cli-default-model',
            '/usr/local/bin/labwc-wayscriber-toggle',
            '/etc/whisper/whisper.conf',
            $self->_whisper_model(),
            $self->_configured_whisper_model(),
        ) {
            printf "%-54s %s\n", $path,
                (-e $path && !-l $path ? 'available' : 'missing or unsafe');
        }
    }
    else {
        _fatal('unsupported Whisper diagnostic');
    }
    return _pause();
}

sub run_llama_server {
    my ($self) = @_;
    $self->session()->assert_desktop_user();
    ($ENV{LABWC_SESSION_OWNER} // q{}) eq 'desktop'
        or _fatal('the managed Labwc desktop session is required');
    return $self->_exec_llama('server');
}

sub run {
    my ($self, @argv) = @_;
    $self->session()->assert_desktop_user();

    if (@argv == 1 && $argv[0] eq '--list-models') {
        print "$_\n" for $self->models()->list_models();
        return 0;
    }
    if (@argv == 1 && $argv[0] eq '--list-favorite-models') {
        print "$_\n" for $self->models()->list_favorite_models();
        return 0;
    }
    if (@argv == 1 && $argv[0] eq '--list-whisper-models') {
        print "$_\n" for $self->models()->list_whisper_models();
        return 0;
    }
    if (@argv == 2 && $argv[0] eq '--list-model-names') {
        if ($argv[1] eq 'llama') {
            print "$_\n" for $self->models()->list_model_names();
            return 0;
        }
        if ($argv[1] eq 'llama-favorite') {
            print "$_\n" for $self->models()->list_favorite_model_names();
            return 0;
        }
        if ($argv[1] eq 'whisper') {
            print "$_\n" for $self->models()->list_whisper_model_names();
            return 0;
        }
        _fatal('unsupported model-name family');
    }
    if (@argv == 3 && $argv[0] eq '--resolve-model-name') {
        my $model =
            $argv[1] eq 'llama'
            ? $self->models()->resolve_model_name($argv[2])
            : $argv[1] eq 'llama-favorite'
            ? $self->models()->resolve_favorite_model_name($argv[2])
            : $argv[1] eq 'whisper'
            ? $self->models()->resolve_whisper_model_name($argv[2])
            : _fatal('unsupported model-name family');
        print "$model\n";
        return 0;
    }
    if (@argv == 2 && $argv[0] eq '--list-download-models') {
        $argv[1] =~ /\A(?:llama|whisper)\z/
            or _fatal('unsupported download catalog family');
        print "$_\n" for $self->models()->list_download_models($argv[1]);
        return 0;
    }
    if (@argv == 3 && $argv[0] eq '--resolve-download-model') {
        $argv[1] =~ /\A(?:llama|whisper)\z/
            or _fatal('unsupported download catalog family');
        print $self->models()->resolve_download_model($argv[1], $argv[2]), "\n";
        return 0;
    }

    my $run_in_terminal = @argv && $argv[0] eq '--run';
    shift @argv if $run_in_terminal;
    @argv
        or _fatal('missing AI & Copilots action');
    my $action = shift @argv;
    $action =~ /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/
        or _fatal('action name is invalid');
    _assert_action_arguments($action, @argv);

    if ($TERMINAL_ACTION{$action} && !$run_in_terminal) {
        return $self->_open_terminal($action, @argv);
    }
    return $self->_codex_action($action, @argv) if $action =~ /\Acodex-/;
    return $self->_llama_action($action, @argv) if $action =~ /\Allama-/;
    return $self->_whisper_action($action, @argv) if $action =~ /\Awhisper-/;
    _fatal('unsupported AI & Copilots action');
}

1;
