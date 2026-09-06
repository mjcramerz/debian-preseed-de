package DigitalAssets::Context;

use strict;
use warnings;

use lib '/usr/local/lib/perl5/site_perl/managed-runtime';
use Managed::Process qw(capture_command);
use Cwd qw(abs_path);
use Errno qw(EINTR);
use Fcntl qw(:flock O_CREAT O_EXCL O_NOFOLLOW O_RDONLY O_RDWR O_TRUNC O_WRONLY);
use File::Basename qw(basename);
use File::Path qw(make_path remove_tree);
use File::Spec;
use File::Temp qw(tempdir tempfile);
use IO::Handle;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(WIFEXITED WEXITSTATUS WIFSIGNALED WTERMSIG);
use Types::Standard qw(ArrayRef Int Str);

has max_input_bytes => ( is => 'ro', isa => Int, default => sub { 209_715_200 } );
has max_pdf_pages   => ( is => 'ro', isa => Int, default => sub { 500 } );
has max_multi_files => ( is => 'ro', isa => Int, default => sub { 20 } );
has timeout_seconds => ( is => 'ro', isa => Int, default => sub { 600 } );
has home => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    builder => '_build_home',
);
has runtime_directory => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    builder => '_build_runtime_directory',
);
has work_directory => (
    is      => 'ro',
    isa     => Str,
    lazy    => 1,
    builder => '_build_work_directory',
    predicate => 'has_work_directory',
);

sub _fatal {
    my ($message) = @_;
    die "labwc-digital-assets-action: $message\n";
}

sub _build_home {
    my $home = $ENV{HOME} // q{};
    _safe_absolute_path('HOME', $home);
    -d $home && !-l $home or _fatal('HOME must be a real directory');
    my @stat = lstat $home;
    $stat[4] == $< or _fatal('HOME must be owned by the active user');
    return $home;
}

sub _build_runtime_directory {
    my $runtime = $ENV{XDG_RUNTIME_DIR} // q{};
    my ($runtime_uid) = $runtime =~ m{\A/run/user/([1-9][0-9]*)\z};
    defined($runtime_uid) && $runtime_uid == $<
        or _fatal('XDG_RUNTIME_DIR is invalid');
    -d $runtime && !-l $runtime
        or _fatal('XDG_RUNTIME_DIR must be a real directory');
    my @stat = lstat $runtime;
    $stat[4] == $< && ($stat[2] & 0077) == 0
        or _fatal('XDG_RUNTIME_DIR ownership or mode is unsafe');
    return $runtime;
}

sub _build_work_directory {
    my ($self) = @_;
    my $path = tempdir('labwc-digital-assets.XXXXXX', DIR => $self->runtime_directory(), CLEANUP => 0);
    chmod 0700, $path or _fatal("cannot secure Digital Assets workspace: $!");
    return $path;
}

sub cleanup {
    my ($self) = @_;
    return if !$self->has_work_directory();
    my $path = $self->work_directory();
    return if !-e $path && !-l $path;
    -d $path && !-l $path or _fatal('Digital Assets workspace is unsafe to remove');
    remove_tree($path, { safe => 1 });
    !-e $path && !-l $path or _fatal('cannot remove Digital Assets workspace');
}

sub _safe_absolute_path {
    my ($label, $path) = @_;
    defined($path) && $path =~ m{\A/} && $path !~ m{\0|(?:\A|/)\.\.(?:/|\z)|//}
        or _fatal("$label must be a safe absolute path");
    return $path;
}

sub command_path {
    my ($self, $name) = @_;
    $name =~ /\A[A-Za-z0-9][A-Za-z0-9+_.-]*\z/
        or _fatal('invalid command name');
    for my $directory (qw(/usr/local/bin /usr/local/sbin /usr/bin /usr/sbin /bin /sbin)) {
        my $candidate = "$directory/$name";
        return $candidate if -f $candidate && !-l $candidate && -x $candidate;
    }
    _fatal("required command is not installed: $name");
}

sub _status_detail {
    my ($status) = @_;
    return "exec error: $!" if $status == -1;
    return 'terminated by signal ' . WTERMSIG($status) if WIFSIGNALED($status);
    return 'exit status ' . WEXITSTATUS($status) if WIFEXITED($status);
    return 'unknown process status';
}

sub _run {
    my ($self, $allow_failure, @command) = @_;
    @command && defined $command[0] or _fatal('empty command');
    my $status = system { $command[0] } @command;
    return $status if $allow_failure || $status == 0;
    _fatal('command failed: ' . _status_detail($status));
}

sub run_timed {
    my ($self, @command) = @_;
    my $timeout = $self->command_path('timeout');
    return $self->_run(
        0,
        $timeout,
        '--signal=TERM',
        '--kill-after=15s',
        $self->timeout_seconds() . 's',
        @command,
    );
}

sub run_timed_allow_failure {
    my ($self, @command) = @_;
    my $timeout = $self->command_path('timeout');
    return $self->_run(
        1,
        $timeout,
        '--signal=TERM',
        '--kill-after=15s',
        $self->timeout_seconds() . 's',
        @command,
    );
}

sub run_interactive {
    my ($self, $environment, @command) = @_;
    ref($environment) eq 'HASH' or _fatal('interactive environment is invalid');
    @command && defined $command[0] or _fatal('empty interactive command');
    local %ENV = (%ENV, %{$environment});
    return $self->_run(0, @command);
}

sub capture_timed {
    my ($self, $limit, @command) = @_;
    my $result = capture_command(
        argv => \@command,
        timeout => $self->timeout_seconds(),
        limit => $limit,
    );
    $result->{status} == 0 or _fatal('captured command failed: ' . _status_detail($result->{status}));
    return $result->{stdout};
}

sub create_private_file {
    my ($self, $name, $content) = @_;
    $name =~ /\A[A-Za-z0-9._-]+\z/ or _fatal('unsafe workspace file name');
    my ($fh, $temporary) = tempfile(".$name.XXXXXX", DIR => $self->work_directory(), UNLINK => 0);
    binmode $fh, ':raw';
    print {$fh} $content or _fatal("cannot write workspace file: $!");
    close $fh or _fatal("cannot close workspace file: $!");
    chmod 0600, $temporary or _fatal("cannot secure workspace file: $!");
    my $target = $self->work_directory() . "/$name";
    rename $temporary, $target or _fatal("cannot publish workspace file: $!");
    return $target;
}

sub prepare_output_file {
    my ($self, $operation, $extension, $source_path) = @_;
    $operation =~ /\A[A-Za-z0-9-]+\z/ or _fatal('invalid output operation');
    $extension =~ /\A[A-Za-z0-9]+\z/ or _fatal('invalid output extension');
    my $directory = $self->_output_directory($operation);
    my $stem = $self->safe_stem($source_path);
    my ($fh, $path) = tempfile(
        "$stem-$operation.XXXXXX.$extension",
        DIR    => $directory,
        UNLINK => 0,
    );
    close $fh or _fatal("cannot allocate output file: $!");
    chmod 0600, $path or _fatal("cannot secure output file: $!");
    return $path;
}

sub prepare_output_directory {
    my ($self, $operation) = @_;
    $operation =~ /\A[A-Za-z0-9-]+\z/ or _fatal('invalid output operation');
    my $root = $self->output_root();
    my $path = tempdir("$operation.XXXXXX", DIR => $root, CLEANUP => 0);
    chmod 0700, $path or _fatal("cannot secure output directory: $!");
    return $path;
}

sub _output_directory {
    my ($self, $operation) = @_;
    my $directory = $self->output_root() . "/$operation";
    if (!-e $directory) {
        make_path($directory, { mode => 0700 }) or _fatal("cannot create output directory: $!");
    }
    -d $directory && !-l $directory or _fatal('Digital Assets output directory must be real');
    my @stat = lstat $directory;
    $stat[4] == $< or _fatal('Digital Assets output directory ownership is unsafe');
    chmod 0700, $directory or _fatal("cannot secure output directory: $!");
    return $directory;
}

sub output_root {
    my ($self) = @_;
    my $documents = $self->home() . '/Documents';
    if (!-e $documents) {
        make_path($documents, { mode => 0700 }) or _fatal("cannot create Documents directory: $!");
    }
    -d $documents && !-l $documents or _fatal('Documents must be a real directory');
    my @documents_stat = lstat $documents;
    $documents_stat[4] == $< or _fatal('Documents must be owned by the active user');
    chmod 0700, $documents or _fatal("cannot secure Documents directory: $!");

    my $root = "$documents/Digital-Assets";
    if (!-e $root) {
        make_path($root, { mode => 0700 }) or _fatal("cannot create Digital Assets output root: $!");
    }
    -d $root && !-l $root or _fatal('Digital Assets output root must be a real directory');
    my @root_stat = lstat $root;
    $root_stat[4] == $< or _fatal('Digital Assets output root must be owned by the active user');
    chmod 0700, $root or _fatal("cannot secure Digital Assets output root: $!");
    return $root;
}

sub safe_stem {
    my ($self, $source_path) = @_;
    my $name = basename($source_path);
    $name =~ s/\.[^.]+\z// or $name = 'asset';
    $name =~ s/[^A-Za-z0-9._-]+/_/g;
    $name = substr($name, 0, 64);
    return length($name) ? $name : 'asset';
}

sub report_file_output {
    my ($self, $path, $label) = @_;
    -f $path && !-l $path && -s $path
        or _fatal("$label did not create a non-empty regular output file");
    chmod 0600, $path or _fatal("cannot secure output file: $!");
    print "Saved $label: $path\n";
    $self->notify_result('Digital Assets completed', "Saved $label in ~/Documents/Digital-Assets.");
}

sub report_directory_output {
    my ($self, $path, $label) = @_;
    -d $path && !-l $path
        or _fatal("$label did not create an output directory");
    print "Saved $label in: $path\n";
    $self->notify_result('Digital Assets completed', "Saved $label in ~/Documents/Digital-Assets.");
}

sub notify_result {
    my ($self, $summary, $body) = @_;
    return if !defined($ENV{DBUS_SESSION_BUS_ADDRESS}) || !length($ENV{DBUS_SESSION_BUS_ADDRESS});
    my $notify = eval { $self->command_path('notify-send') };
    return if !$notify;
    my $pid = fork();
    return if !defined $pid;
    if ($pid == 0) {
        open STDOUT, '>', '/dev/null' or POSIX::_exit(0);
        open STDERR, '>&', \*STDOUT or POSIX::_exit(0);
        my $executed = exec { $notify } $notify, '-a', 'Digital Assets', '-u', 'normal',
            '-i', 'document-save', '-c', 'x-labwc.maintenance', '-t', '10000',
            $summary, $body;
        POSIX::_exit($executed ? 0 : 127);
    }
    waitpid($pid, 0);
}

sub prompt_line {
    my ($self, $label) = @_;
    print STDERR $label;
    my $value = <STDIN>;
    defined $value or _fatal('input was cancelled');
    $value =~ s/\r?\n\z//;
    return $value;
}

sub prompt_secret {
    my ($self, $label) = @_;
    print STDERR $label;
    my $stty = $self->command_path('stty');
    $self->_run(0, $stty, '-echo');
    my $value = <STDIN>;
    $self->_run(1, $stty, 'echo');
    print STDERR "\n";
    defined $value or _fatal('password input was cancelled');
    $value =~ s/\r?\n\z//;
    return $value;
}

sub validate_text {
    my ($self, $label, $value, $maximum) = @_;
    defined($value) && $value !~ /[\r\n]/ && length($value) <= $maximum
        or _fatal("$label is invalid or exceeds $maximum characters");
    return $value;
}

sub validate_ascii_text {
    my ($self, $label, $value, $maximum) = @_;
    $self->validate_text($label, $value, $maximum);
    $value !~ /[^\x20-\x7e]/ or _fatal("$label contains unsupported control characters");
    return $value;
}

sub validate_password {
    my ($self, $label, $value) = @_;
    $self->validate_text($label, $value, 128);
    length($value) >= 8 or _fatal("$label must contain at least eight characters");
    $value !~ /\A\@/ or _fatal("$label cannot begin with \@");
    return $value;
}

sub validate_user_file {
    my ($self, $kind, $requested_path) = @_;
    _safe_absolute_path('selected path', $requested_path);
    $requested_path !~ /[\r\n]/ or _fatal('selected path cannot contain newlines');
    !-l $requested_path && -f $requested_path && -r $requested_path
        or _fatal('selected path must be a readable non-symbolic regular file');
    my $resolved = abs_path($requested_path);
    defined($resolved) && $resolved eq $requested_path
        or _fatal('selected file must already be canonical');
    index($resolved, $self->home() . '/') == 0
        or _fatal('selected file must be inside the logged-in user home directory');
    $self->_validate_extension($kind, $resolved);
    my @stat = lstat $resolved;
    $stat[4] == $< or _fatal('selected file must be owned by the active user');
    ($stat[2] & 0022) == 0
        or _fatal('selected file cannot be writable by group or other users');
    $stat[7] > 0 && $stat[7] <= $self->max_input_bytes()
        or _fatal('selected file is empty or exceeds the safety size limit');
    return $resolved;
}

sub _validate_extension {
    my ($self, $kind, $path) = @_;
    my %patterns = (
        docx     => qr/\.docx\z/i,
        pdf      => qr/\.pdf\z/i,
        markdown => qr/\.(?:md|markdown|mdown|mkdn)\z/i,
        image    => qr/\.(?:avif|bmp|gif|heic|jpe?g|png|tiff?|webp)\z/i,
    );
    exists $patterns{$kind} && $path =~ $patterns{$kind}
        or _fatal("selected file does not have a supported $kind extension");
}

sub read_input_list {
    my ($self, $kind, $list_path) = @_;
    my $runtime = $self->runtime_directory();
    $list_path =~ /\A\Q$runtime\E\/labwc-digital-assets-list\.[A-Za-z0-9]+\z/
        or _fatal('selection list is outside the managed runtime directory');
    -f $list_path && !-l $list_path
        or _fatal('selection list is not a regular file');
    my @stat = lstat $list_path;
    $stat[4] == $< && ($stat[2] & 07777) == 0600
        or _fatal('selection list ownership or mode is unsafe');
    $stat[7] <= 16_384 or _fatal('selection list exceeds the managed size limit');
    open my $fh, '<:encoding(UTF-8)', $list_path
        or _fatal("cannot read selection list: $!");
    my @files;
    while (my $line = <$fh>) {
        $line =~ s/\r?\n\z//;
        push @files, $self->validate_user_file($kind, $line);
        @files <= $self->max_multi_files()
            or _fatal('too many files in managed selection list');
    }
    close $fh or _fatal("cannot close selection list: $!");
    @files >= 2 or _fatal('select at least two input files');
    return \@files;
}

sub pdf_page_count {
    my ($self, $path) = @_;
    my $pdfinfo = $self->command_path('pdfinfo');
    my $output = $self->capture_timed(65_536, $pdfinfo, $path);
    my ($pages) = $output =~ /^Pages:\s*([0-9]+)\s*$/m;
    defined($pages) && $pages >= 1 && $pages <= $self->max_pdf_pages()
        or _fatal('unable to determine a supported PDF page count');
    return int($pages);
}

sub validate_page_range {
    my ($self, $range, $total_pages) = @_;
    $range =~ /\A[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*\z/
        or _fatal('page range must be a comma-separated list such as 1-3,5');
    for my $part (split /,/, $range) {
        my ($first, $last) = split /-/, $part, 2;
        $last //= $first;
        $first >= 1 && $last >= $first && $last <= $total_pages
            or _fatal('page range contains a page outside the source PDF');
    }
    return $range;
}

sub prompt_page_range {
    my ($self, $total_pages) = @_;
    return $self->validate_page_range(
        $self->prompt_line("Pages (1-$total_pages, for example 1-3,5): "),
        $total_pages,
    );
}

sub directory_has_file {
    my ($self, $directory, $expression) = @_;
    opendir my $dh, $directory or _fatal("cannot inspect output directory: $!");
    while (my $entry = readdir $dh) {
        next if $entry eq '.' || $entry eq '..';
        my $path = "$directory/$entry";
        if (-f $path && !-l $path && $entry =~ $expression) {
            closedir $dh;
            return 1;
        }
    }
    closedir $dh or _fatal("cannot close output directory: $!");
    return 0;
}

1;
