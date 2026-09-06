package LabwcSecurityAction::AppArmor;

use strict;
use warnings;

use File::Basename qw(basename dirname);
use File::Copy qw(copy);
use File::Path qw(make_path remove_tree);
use File::Temp qw(tempdir tempfile);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Int Object Str);

use LabwcSecurityAction::Command;
use LabwcSecurityAction::Logger;

has command => (
    is      => 'ro',
    isa     => Object,
    default => sub {
        return LabwcSecurityAction::Command->new(
            path => '/usr/sbin:/usr/bin:/sbin:/bin',
        );
    },
);

has easyprof_draft_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/apparmor/easyprof' },
);

has event_log => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/log/managed/apparmor/apparmor.log' },
);

has logger => (
    is      => 'ro',
    default => sub { LabwcSecurityAction::Logger->new(tag => 'labwc-security-action-root') },
);

has maximum_config_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 65_536 },
);

has maximum_draft_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 1_048_576 },
);

has maximum_draft_files => (
    is      => 'ro',
    isa     => Int,
    default => sub { 64 },
);

has maximum_executable_path_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 4096 },
);

has maximum_installed_profile_files => (
    is      => 'ro',
    isa     => Int,
    default => sub { 512 },
);

has maximum_label_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 65_536 },
);

has mode_config => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/apparmor/managed-modes.conf' },
);

has mode_helper => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/libexec/apparmor-managed-modes-run' },
);

has profile_backup_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/apparmor/backup' },
);

has profile_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/apparmor.d' },
);

has profile_draft_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/apparmor/drafts' },
);

has rule_generator => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/libexec/apparmor-generate-rules' },
);

sub _program {
    my ($self, $name) = @_;
    return $self->command()->require_executable($name);
}

sub _validate_draft_name {
    my ($self, $name) = @_;

    defined($name) && $name ne q{} && $name !~ /\A\./ && $name =~ /\A[A-Za-z0-9._+-]+\z/
        or die "invalid AppArmor draft profile name: " . (defined($name) ? $name : 'unset') . "\n";
    return $name;
}

sub _validate_mode_config {
    my ($self) = @_;

    -f $self->mode_config() && !-l $self->mode_config()
        or die "managed AppArmor mode configuration must be a regular non-symlink file\n";
    my @stat = stat $self->mode_config();
    @stat or die "cannot inspect managed AppArmor mode configuration\n";
    $stat[4] == 0
        or die "managed AppArmor mode configuration must be owned by root\n";
    ($stat[2] & 0022) == 0
        or die "managed AppArmor mode configuration must not be group- or world-writable\n";
    $stat[7] <= $self->maximum_config_bytes()
        or die "managed AppArmor mode configuration exceeds " . $self->maximum_config_bytes() . " bytes\n";
    return;
}

sub _read_small_file {
    my ($self, $path, $limit, $label) = @_;

    open my $fh, '<', $path or die "cannot read $label: $!\n";
    local $/;
    my $content = <$fh>;
    close $fh or die "cannot close $label: $!\n";
    length($content // q{}) <= $limit
        or die "$label exceeds $limit bytes\n";
    return $content // q{};
}

sub _validate_executable {
    my ($self, $requested) = @_;

    defined($requested) && $requested =~ m{\A/}
        or die "AppArmor executable path must be absolute\n";
    $requested !~ /[\r\n]/
        or die "AppArmor executable path cannot contain newlines\n";
    length($requested) <= $self->maximum_executable_path_bytes()
        or die "AppArmor executable path exceeds " . $self->maximum_executable_path_bytes() . " bytes\n";
    my $readlink = $self->_program('readlink');
    my ($status, $resolved) = $self->command()->capture(
        argv => [$readlink, '-f', '--', $requested],
    );
    $status == 0
        or die "unable to resolve AppArmor executable path: $requested\n";
    $resolved =~ s/[\r\n]+\z//;
    -f $resolved && -x $resolved
        or die "AppArmor executable path is not an executable regular file: $resolved\n";
    return $resolved;
}

sub _require_profile_tool_confirmation {
    my ($self, $confirmation) = @_;

    $confirmation eq 'confirmed-apparmor-profile-tool'
        or die "AppArmor profile tools require explicit confirmation\n";
    return;
}

sub _ensure_root_directory {
    my ($self, $directory, $mode, $label) = @_;

    !-l $directory
        or die "$label cannot be a symbolic link\n";
    make_path($directory, { mode => $mode }) if !-d $directory;
    my @stat = stat $directory;
    @stat && -d _
        or die "$label is unavailable: $directory\n";
    $stat[4] == 0
        or die "$label must be owned by root\n";
    ($stat[2] & 0022) == 0
        or die "$label must not be group- or world-writable\n";
    chmod $mode, $directory
        or die "cannot set $label mode: $!\n";
    return;
}

sub _prepare_draft_dir {
    my ($self) = @_;

    return $self->_ensure_root_directory(
        $self->profile_draft_dir(),
        0755,
        'AppArmor profile draft directory',
    );
}

sub _prepare_backup_dir {
    my ($self) = @_;

    $self->_ensure_root_directory(
        $self->profile_backup_dir(),
        0700,
        'AppArmor profile backup directory',
    );
    my @stat = stat $self->profile_backup_dir();
    ($stat[2] & 0077) == 0
        or die "AppArmor profile backup directory must not be group- or world-accessible\n";
    return;
}

sub _validate_root_owned_file {
    my ($self, $label, $path) = @_;

    -f $path && !-l $path
        or die "$label must be a regular non-symlink file: $path\n";
    my @stat = stat $path;
    @stat or die "cannot inspect $label: $path\n";
    $stat[4] == 0
        or die "$label must be owned by root: $path\n";
    ($stat[2] & 0022) == 0
        or die "$label must not be group- or world-writable: $path\n";
    $stat[7] <= $self->maximum_draft_bytes()
        or die "$label exceeds " . $self->maximum_draft_bytes() . " bytes: $path\n";
    return;
}

sub _draft_path {
    my ($self, $origin, $name) = @_;

    $self->_validate_draft_name($name);
    if ($origin eq 'easyprof') {
        return $self->easyprof_draft_dir() . "/$name";
    }
    if ($origin eq 'drafts') {
        return $self->profile_draft_dir() . "/$name";
    }
    die "unsupported AppArmor draft origin: $origin\n";
}

sub _parser_validate {
    my ($self, $path) = @_;

    my $parser = $self->_program('apparmor_parser');
    return $self->command()->run(
        $parser,
        '--config-file', '/etc/apparmor/parser.conf',
        '-q', '-Q', '-K', '-T',
        $path,
    );
}

sub _profile_labels {
    my ($self, $source) = @_;

    $self->_prepare_backup_dir();
    my $parser = $self->_program('apparmor_parser');
    my ($status, $output) = $self->command()->capture(
        argv => [
            $parser,
            '--config-file', '/etc/apparmor/parser.conf',
            '-q', '-N', '-Q', '-K', '-T',
            '-I', $self->profile_dir(),
            '--base', $self->profile_backup_dir(),
            $source,
        ],
    );
    $status == 0
        or die "cannot derive AppArmor profile labels from: $source\n";
    length($output) > 0
        or die "AppArmor profile defines no labels: $source\n";
    length($output) <= $self->maximum_label_bytes()
        or die "AppArmor profile labels exceed " . $self->maximum_label_bytes() . " bytes: $source\n";
    my %unique = map { $_ => 1 } grep { $_ ne q{} } split /\n/, $output;
    return [sort keys %unique];
}

sub _same_labels {
    my ($self, $left, $right) = @_;

    return 0 if @{$left} != @{$right};
    for my $index (0 .. $#{$left}) {
        return 0 if $left->[$index] ne $right->[$index];
    }
    return 1;
}

sub _resolve_installed_profile_name {
    my ($self, $source, $requested_name) = @_;

    $self->_validate_draft_name($requested_name);
    my $candidate_labels = $self->_profile_labels($source);
    opendir my $dh, $self->profile_dir()
        or die "cannot read AppArmor profile directory: " . $self->profile_dir() . ": $!\n";
    my @matches;
    my $count = 0;
    while (my $name = readdir $dh) {
        next if $name eq q{.} || $name eq q{..};
        my $path = $self->profile_dir() . "/$name";
        next if !-f $path || -l $path;
        ++$count;
        $count <= $self->maximum_installed_profile_files()
            or die "more than " . $self->maximum_installed_profile_files() . " installed AppArmor profile files were found\n";
        $self->_validate_draft_name($name);
        my $installed_labels = $self->_profile_labels($path);
        push @matches, $name if $self->_same_labels($candidate_labels, $installed_labels);
    }
    closedir $dh or die "cannot close AppArmor profile directory: $!\n";

    if (!@matches) {
        my $target = $self->profile_dir() . "/$requested_name";
        (!-e $target && !-l $target)
            or die "AppArmor draft profile labels do not match the installed target: $requested_name\n";
        return $requested_name;
    }
    @matches == 1
        or die "AppArmor draft profile labels match multiple installed targets: $requested_name\n";
    return $matches[0];
}

sub _merge_draft {
    my ($self, $generated, $target, $label) = @_;

    $self->_parser_validate($generated) == 0
        or die "$label generated invalid AppArmor policy: " . basename($generated) . "\n";
    if (!-e $target) {
        copy($generated, $target)
            or die "cannot write AppArmor draft $target: $!\n";
        chmod 0644, $target or die "cannot set AppArmor draft mode: $!\n";
        print "Generated non-active $label draft: $target\n";
        return;
    }

    $self->_validate_root_owned_file('existing AppArmor profile draft', $target);
    my @generated = split /\n/, $self->_read_small_file($generated, $self->maximum_draft_bytes(), 'generated AppArmor draft'), -1;
    my @existing = split /\n/, $self->_read_small_file($target, $self->maximum_draft_bytes(), 'existing AppArmor draft'), -1;
    grep { $_ =~ /^\s*}\s*$/ } @generated
        or die "generated AppArmor draft does not terminate the profile block\n";
    my %generated_lines = map { (my $line = $_) =~ s/\s+\z//; $line => 1 } @generated;
    my @extras;
    for my $line (@existing) {
        (my $trimmed = $line) =~ s/\s+\z//;
        my $stripped = $trimmed;
        $stripped =~ s/\A\s+//;
        next if $stripped eq q{} || $stripped eq '}' || $stripped =~ /\A#/;
        next if $stripped =~ /\Aabi\s/ || $stripped =~ /\A#include <tunables\/global>/;
        next if $stripped =~ /\Aprofile\s/ || $stripped =~ /\Ainclude if exists <local\//;
        push @extras, $trimmed if !$generated_lines{$trimmed};
    }
    my @merged = @generated;
    if (@extras) {
        my $index;
        for my $candidate (0 .. $#merged) {
            if ($merged[$candidate] =~ /^\s*include if exists <local\//) {
                $index = $candidate;
                last;
            }
        }
        if (!defined $index) {
            for (my $candidate = $#merged; $candidate >= 0; --$candidate) {
                if ($merged[$candidate] =~ /^\s*}\s*$/) {
                    $index = $candidate;
                    last;
                }
            }
        }
        defined($index)
            or die "generated AppArmor draft has no merge anchor\n";
        splice @merged, $index, 0, @extras;
    }
    my ($fh, $temporary) = tempfile(basename($target) . '.merge.XXXXXX', DIR => dirname($target), UNLINK => 0);
    print {$fh} join("\n", @merged), "\n"
        or die "cannot write merged AppArmor draft: $!\n";
    close $fh or die "cannot close merged AppArmor draft: $!\n";
    if ($self->_parser_validate($temporary) == 0) {
        copy($temporary, $target)
            or die "cannot publish merged AppArmor draft: $!\n";
        chmod 0644, $target or die "cannot set AppArmor draft mode: $!\n";
        print "Merged non-active $label draft into existing profile: $target\n";
    }
    else {
        copy($generated, $target)
            or die "cannot replace AppArmor draft: $!\n";
        chmod 0644, $target or die "cannot set AppArmor draft mode: $!\n";
        print "Replaced existing $label draft with the newly generated profile: $target\n";
    }
    unlink $temporary;
    return;
}

sub _publish_generated_drafts {
    my ($self, $work_dir, $label) = @_;

    my @files = sort grep { -f $_ && !-l $_ } glob("$work_dir/*");
    @files && @files <= $self->maximum_draft_files()
        or die @files
        ? "$label generated more than " . $self->maximum_draft_files() . " profile drafts\n"
        : "$label did not generate any profile drafts\n";
    for my $file (@files) {
        my $name = basename($file);
        $self->_validate_draft_name($name);
        my @stat = stat $file;
        $stat[7] <= $self->maximum_draft_bytes()
            or die "$label generated a profile draft above " . $self->maximum_draft_bytes() . " bytes\n";
        $self->_parser_validate($file) == 0
            or die "$label generated invalid AppArmor policy: $name\n";
    }
    for my $file (@files) {
        my $canonical = $self->_resolve_installed_profile_name($file, basename($file));
        if ($canonical ne basename($file)) {
            print "Normalized generated AppArmor draft filename: " . basename($file) . " -> $canonical\n";
        }
        $self->_merge_draft($file, $self->profile_draft_dir() . "/$canonical", $label);
    }
    print "Review generated drafts before installing or loading them.\n";
    return;
}

sub _link_support_dirs {
    my ($self, $work_dir) = @_;

    for my $name (qw(abi abstractions tunables)) {
        my $source = $self->profile_dir() . "/$name";
        -d $source && !-l $source
            or die "required AppArmor profile support directory is unavailable: $source\n";
        symlink $source, "$work_dir/$name"
            or die "cannot link AppArmor support directory $source: $!\n";
    }
    my $local = $self->profile_dir() . '/local';
    symlink $local, "$work_dir/local"
        if -d $local && !-l $local;
    return;
}

sub _work_dir {
    my ($self, $prefix) = @_;

    $self->_prepare_draft_dir();
    my $work_dir = tempdir("$prefix.XXXXXX", DIR => $self->profile_draft_dir(), CLEANUP => 0);
    chmod 0700, $work_dir or die "cannot protect AppArmor workspace: $!\n";
    return $work_dir;
}

sub run_easyprof {
    my ($self, $executable, $confirmation) = @_;

    my $path = $self->_validate_executable($executable);
    $self->_require_profile_tool_confirmation($confirmation);
    $self->_ensure_root_directory($self->easyprof_draft_dir(), 0755, 'AppArmor easyprof draft directory');
    my $work_dir = tempdir('.draft.XXXXXX', DIR => $self->easyprof_draft_dir(), CLEANUP => 0);
    my $status = eval {
        my $tool = $self->_program('aa-easyprof');
        $self->command()->run($tool, "--output-directory=$work_dir", $path) == 0
            or die "aa-easyprof failed for executable: $path\n";
        my @files = grep { -f $_ && !-l $_ } glob("$work_dir/*");
        @files == 1 or die "aa-easyprof did not generate exactly one profile\n";
        my $name = basename($files[0]);
        $self->_validate_draft_name($name);
        my $canonical = $self->_resolve_installed_profile_name($files[0], $name);
        print "Normalized generated AppArmor easyprof draft filename: $name -> $canonical\n"
            if $canonical ne $name;
        $self->_merge_draft($files[0], $self->easyprof_draft_dir() . "/$canonical", 'easyprof');
        print "Review the draft before copying it into /etc/apparmor.d and loading it.\n";
        return 0;
    };
    my $error = $@;
    remove_tree($work_dir);
    die $error if !$status && $error;
    return $status;
}

sub run_autodep {
    my ($self, $executable, $confirmation) = @_;

    my $path = $self->_validate_executable($executable);
    $self->_require_profile_tool_confirmation($confirmation);
    my $work_dir = $self->_work_dir('.autodep');
    my $status = eval {
        $self->_link_support_dirs($work_dir);
        my $tool = $self->_program('aa-autodep');
        $self->command()->run($tool, '--no-reload', '--dir', $work_dir, $path) == 0
            or die "aa-autodep failed for executable: $path\n";
        $self->_publish_generated_drafts($work_dir, 'aa-autodep');
        return 0;
    };
    my $error = $@;
    remove_tree($work_dir);
    die $error if !$status && $error;
    return $status;
}

sub _prepare_logprof_input {
    my ($self, $work_dir) = @_;

    -f $self->event_log() && !-l $self->event_log() && -r $self->event_log()
        or die "AppArmor event log is unavailable: " . $self->event_log() . "\n";
    my @stat = stat $self->event_log();
    $stat[4] == 0 && ($stat[2] & 0022) == 0
        or die "AppArmor event log must be root-owned and not group- or world-writable\n";
    my $input_dir = "$work_dir/input";
    mkdir $input_dir, 0700 or die "cannot create temporary AppArmor logprof input directory: $!\n";
    my $input = "$input_dir/apparmor.log";
    open my $source, '<', $self->event_log() or die "cannot read AppArmor event log: $!\n";
    open my $destination, '>', $input or die "cannot write AppArmor logprof input: $!\n";
    my $found = 0;
    while (my $line = <$source>) {
        $line =~ s/^node=\S+\s+//;
        $found = 1 if $line =~ /(?:^|\s)type=(?:AVC|APPARMOR_[A-Z_]+).*apparmor="(?:ALLOWED|DENIED)"/;
        print {$destination} $line or die "cannot write AppArmor logprof input: $!\n";
    }
    close $source;
    close $destination or die "cannot close AppArmor logprof input: $!\n";
    chmod 0600, $input or die "cannot protect AppArmor logprof input: $!\n";
    $found or die "AppArmor event log contains no parseable complain-mode or enforce-mode events\n";
    return $input;
}

sub run_logprof {
    my ($self, $confirmation) = @_;

    $self->_require_profile_tool_confirmation($confirmation);
    my $work_dir = $self->_work_dir('.logprof');
    my $status = eval {
        my $input = $self->_prepare_logprof_input($work_dir);
        my $tool = $self->_program('aa-logprof');
        $self->command()->run($tool, '--dir', $self->profile_dir(), '--file', $input, '--output-dir', $work_dir) == 0
            or die "aa-logprof failed while generating profile drafts\n";
        $self->_publish_generated_drafts($work_dir, 'aa-logprof');
        return 0;
    };
    my $error = $@;
    remove_tree($work_dir);
    die $error if !$status && $error;
    return $status;
}

sub run_genprof {
    my ($self, $executable, $confirmation) = @_;

    my $path = $self->_validate_executable($executable);
    $self->_require_profile_tool_confirmation($confirmation);
    -r $self->event_log() or die "AppArmor event log is unavailable: " . $self->event_log() . "\n";
    my $work_dir = $self->_work_dir('.genprof');
    my $status = eval {
        my $tool = $self->_program('aa-genprof');
        $self->command()->run(
            $tool,
            '--dir', $self->profile_dir(),
            '--file', $self->event_log(),
            '--output-dir', $work_dir,
            $path,
        ) == 0 or die "aa-genprof failed for executable: $path\n";
        $self->_publish_generated_drafts($work_dir, 'aa-genprof');
        return 0;
    };
    my $error = $@;
    remove_tree($work_dir);
    die $error if !$status && $error;
    return $status;
}

sub generate_rules {
    my ($self, $confirmation) = @_;

    $confirmation eq 'confirmed-apparmor-rule-generation'
        or die "AppArmor rule generation requires explicit confirmation\n";
    my @metadata = lstat($self->rule_generator());
    @metadata && ($metadata[2] & 0170000) == 0100000 &&
        !-l $self->rule_generator() &&
        -x $self->rule_generator()
        or die "AppArmor rule generator is unavailable: "
            . $self->rule_generator() . "\n";
    $metadata[4] == 0
        or die "AppArmor rule generator must be owned by root\n";
    ($metadata[2] & 0022) == 0
        or die "AppArmor rule generator must not be group- or world-writable\n";
    return $self->command()->run(
        $self->rule_generator(),
        '--apply',
        $confirmation,
    );
}

sub _application_profiles {
    my ($self, $application) = @_;

    my %profiles = (
        bitwarden        => [qw(opt.Bitwarden.bitwarden)],
        chromium         => [qw(chromium)],
        code             => [qw(code)],
        qoredb           => [qw(usr.bin.qoredb)],
        discord          => [qw(Discord)],
        filen            => [qw(opt.Filen.Filen)],
        keepassxc        => [qw(usr.bin.keepassxc)],
        'ledger-live'    => [qw(opt.ledger-live.AppRun)],
        'microsoft-edge' => [qw(microsoft-edge-stable)],
        'mullvad-browser'=> [qw(mullvad-browser)],
        obsidian         => [qw(obsidian)],
        postman          => [qw(opt.postman.app.Postman)],
        qbittorrent      => [qw(usr.bin.qbittorrent)],
        retroarch        => [qw(usr.bin.retroarch)],
        sleek            => [qw(sleek)],
        spotify          => [qw(usr.bin.spotify)],
        sqlitebrowser    => [qw(usr.bin.sqlitebrowser)],
        'telegram-desktop' => [qw(usr.bin.telegram-desktop)],
        totem            => [qw(usr.bin.totem)],
        'tuta-mail'      => [qw(opt.tuta-mail.AppRun)],
        vivaldi          => [qw(vivaldi-stable vivaldi-bin)],
        zoom             => [qw(usr.bin.zoom)],
    );
    exists $profiles{$application}
        or die "unsupported managed AppArmor application: $application\n";
    return @{ $profiles{$application} };
}

sub _desktop_profiles {
    my ($self) = @_;

    # The global state owns every declared managed profile source. Individual
    # application actions remain limited to their application-specific rows.
    return map { $_->[2] } $self->_mode_rows();
}

sub _mode_rows {
    my ($self) = @_;

    $self->_validate_mode_config();
    my $content = $self->_read_small_file($self->mode_config(), $self->maximum_config_bytes(), 'managed AppArmor mode configuration');
    my @rows;
    for my $line (split /\n/, $content) {
        next if $line =~ /^\s*(?:#|\z)/;
        my @fields = split /\s+/, $line;
        @fields == 4
            or die "managed AppArmor mode configuration is malformed\n";
        push @rows, \@fields;
    }
    return @rows;
}

sub print_application_modes {
    my ($self) = @_;

    my @rows = $self->_mode_rows();
    my %application_name = (
        'managed-desktop-wrappers' => 'Desktop wrappers',
        'managed-system-wrappers'  => 'System wrappers',
        'usr.sbin.aa-status'       => 'AppArmor status reader',
    );
    my @applications = (
        ['Bitwarden', 'bitwarden'], ['Chromium', 'chromium'], ['Code', 'code'],
        ['QoreDB', 'qoredb'],
        ['Discord', 'discord'], ['Filen', 'filen'],
        ['KeePassXC', 'keepassxc'], ['Ledger Live', 'ledger-live'],
        ['Microsoft Edge', 'microsoft-edge'], ['Mullvad Browser', 'mullvad-browser'],
        ['Obsidian', 'obsidian'], ['Postman', 'postman'], ['qBittorrent', 'qbittorrent'],
        ['RetroArch', 'retroarch'], ['Sleek', 'sleek'], ['Spotify', 'spotify'],
        ['SQLite Browser', 'sqlitebrowser'], ['Telegram', 'telegram-desktop'],
        ['Totem', 'totem'], ['Tuta Mail', 'tuta-mail'], ['Vivaldi', 'vivaldi'], ['Zoom', 'zoom'],
    );
    for my $application (@applications) {
        for my $profile ($self->_application_profiles($application->[1])) {
            $application_name{$profile} = $application->[0];
        }
    }

    print sprintf "%-18s %-36s %s\n", 'Scope', 'Profile', 'Mode';
    print sprintf "%-18s %-36s %s\n", '-' x 18, '-' x 36, '-' x 8;
    for my $row (@rows) {
        my $mode = $row->[0];
        my $profile = $row->[2];
        my $application = $application_name{$profile} // 'Managed policy';
        print sprintf "%-18s %-36s %s\n", $application, $profile, $mode;
    }
    return 0;
}

sub list_drafts {
    my ($self) = @_;

    my @drafts;
    for my $spec (
        ['easyprof', $self->easyprof_draft_dir()],
        ['drafts', $self->profile_draft_dir()],
    ) {
        next if !-d $spec->[1];
        opendir my $dh, $spec->[1] or die "cannot read AppArmor draft directory $spec->[1]: $!\n";
        while (my $name = readdir $dh) {
            next if $name eq q{.} || $name eq q{..};
            my $path = "$spec->[1]/$name";
            next if !-f $path || -l $path;
            $self->_validate_draft_name($name);
            my @stat = stat $path;
            $stat[7] <= $self->maximum_draft_bytes()
                or die "AppArmor draft exceeds " . $self->maximum_draft_bytes() . " bytes: $path\n";
            push @drafts, [$spec->[0], $path, $stat[7]];
            @drafts <= $self->maximum_draft_files()
                or die "more than " . $self->maximum_draft_files() . " AppArmor profile drafts were found\n";
        }
        closedir $dh;
    }
    if (!@drafts) {
        print "No generated AppArmor profile drafts were found.\n";
        return 0;
    }
    for my $draft (sort { $a->[1] cmp $b->[1] } @drafts) {
        printf "%-9s %10s bytes  %s\n", $draft->[0], $draft->[2], $draft->[1];
    }
    return 0;
}

sub validate_drafts {
    my ($self) = @_;

    my $parser = $self->_program('apparmor_parser');
    my @paths;
    for my $directory ($self->easyprof_draft_dir(), $self->profile_draft_dir()) {
        next if !-d $directory;
        push @paths, grep { -f $_ && !-l $_ } glob("$directory/*");
    }
    if (!@paths) {
        print "No generated AppArmor profile drafts were found.\n";
        return 0;
    }
    @paths <= $self->maximum_draft_files()
        or die "more than " . $self->maximum_draft_files() . " AppArmor profile drafts were found\n";
    my $failed = 0;
    for my $path (sort @paths) {
        $self->_validate_draft_name(basename($path));
        my @stat = stat $path;
        $stat[7] <= $self->maximum_draft_bytes()
            or die "AppArmor draft exceeds " . $self->maximum_draft_bytes() . " bytes: $path\n";
        my $status = $self->command()->run(
            $parser, '--config-file', '/etc/apparmor/parser.conf', '-q', '-Q', '-K', '-T', $path,
        );
        if ($status == 0) {
            print "valid   $path\n";
        }
        else {
            print "invalid $path\n";
            $failed = 1;
        }
    }
    $failed and die "one or more generated AppArmor profile drafts failed validation\n";
    return 0;
}

sub _management_state {
    my ($self, $profile) = @_;

    my @rows = grep { $_->[2] eq $profile } $self->_mode_rows();
    @rows <= 1
        or die "managed AppArmor mode configuration repeats profile: $profile\n";
    return @rows ? 1 : 0;
}

sub _activate_installed_profile {
    my ($self, $target, $managed) = @_;

    if ($managed) {
        -x $self->mode_helper()
            or die "managed AppArmor mode helper is unavailable: " . $self->mode_helper() . "\n";
        return $self->command()->run($self->mode_helper());
    }
    my $parser = $self->_program('apparmor_parser');
    return $self->command()->run(
        $parser,
        '--config-file', '/etc/apparmor/parser.conf',
        '-q', '-r',
        '-I', $self->profile_dir(),
        '--base', $self->profile_dir(),
        $target,
    );
}

sub _copy_atomic {
    my ($self, $source, $target, $mode) = @_;

    my ($fh, $temporary) = tempfile('.profile.XXXXXX', DIR => dirname($target), UNLINK => 0);
    close $fh;
    copy($source, $temporary) or die "cannot copy $source to $target: $!\n";
    chmod $mode, $temporary or die "cannot protect $temporary: $!\n";
    rename $temporary, $target or die "cannot publish $target: $!\n";
    return;
}

sub activate_draft {
    my ($self, $origin, $name, $confirmation) = @_;

    $confirmation eq 'confirmed-apparmor-draft-activation'
        or die "AppArmor draft activation requires explicit confirmation\n";
    $self->_validate_mode_config();
    my $draft = $self->_draft_path($origin, $name);
    $self->_validate_root_owned_file('AppArmor draft', $draft);
    $self->_prepare_backup_dir();
    my $batch = tempdir('activate.XXXXXX', DIR => $self->profile_backup_dir(), CLEANUP => 0);
    chmod 0700, $batch;
    my ($candidate, $target, $backup, $draft_original, $draft_canonical);
    my ($published, $target_existed, $managed, $renamed) = (0, 0, 0, 0);
    my $status = eval {
        $candidate = "$batch/candidate-profile";
        copy($draft, $candidate) or die "cannot snapshot AppArmor draft: $draft\n";
        chmod 0600, $candidate or die "cannot protect AppArmor draft snapshot: $!\n";
        my $canonical = $self->_resolve_installed_profile_name($candidate, $name);
        $target = $self->profile_dir() . "/$canonical";
        if ($canonical ne $name) {
            print "Resolved AppArmor draft filename: $name -> $canonical\n";
            $draft_original = $draft;
            $draft_canonical = $self->_draft_path($origin, $canonical);
            (!-e $draft_canonical && !-l $draft_canonical)
                or die "canonical AppArmor draft filename already exists: $canonical\n";
            rename $draft_original, $draft_canonical
                or die "cannot normalize AppArmor draft filename: $name\n";
            $draft = $draft_canonical;
            $renamed = 1;
        }
        if (-e $target || -l $target) {
            $self->_validate_root_owned_file('installed AppArmor profile', $target);
            my $candidate_labels = $self->_profile_labels($candidate);
            my $target_labels = $self->_profile_labels($target);
            $self->_same_labels($candidate_labels, $target_labels)
                or die "AppArmor draft profile labels do not match the installed target: $canonical\n";
            $backup = "$batch/previous-profile";
            copy($target, $backup) or die "cannot back up installed AppArmor profile: $target\n";
            $target_existed = 1;
        }
        $managed = $self->_management_state($canonical);
        $self->_copy_atomic($candidate, $target, 0644);
        $published = 1;
        my $activation_status = $self->_activate_installed_profile($target, $managed);
        $activation_status == 0
            or die "AppArmor draft activation failed with status $activation_status; the previous profile will be restored\n";
        $published = 0;
        $renamed = 0;
        print "Activated AppArmor draft: $origin/$canonical -> $target\n";
        if ($target_existed) {
            print "Previous AppArmor profile backup: $backup\n";
        }
        else {
            print "Installed a new AppArmor profile; no previous source existed.\n";
        }
        print $managed
            ? "The repository-managed AppArmor mode policy was reapplied.\n"
            : "The profile was loaded using the mode declared by the draft.\n";
        return 0;
    };
    my $error = $@;
    if ($error) {
        if ($published) {
            if ($target_existed && defined $backup && -f $backup) {
                eval { $self->_copy_atomic($backup, $target, 0644); };
                eval { $self->_activate_installed_profile($target, $managed); };
            }
            elsif (defined $target) {
                unlink $target;
                my $parser = $self->command()->executable('apparmor_parser');
                eval {
                    $self->command()->run(
                        $parser,
                        '--config-file', '/etc/apparmor/parser.conf',
                        '-q', '-R',
                        '-I', $self->profile_dir(),
                        '--base', $self->profile_dir(),
                        $candidate,
                    ) if $parser;
                };
            }
        }
        if ($renamed && defined $draft_original && defined $draft_canonical && -e $draft_canonical) {
            rename $draft_canonical, $draft_original;
        }
    }
    remove_tree($batch) if !$target_existed || $error;
    die $error if $error;
    return $status;
}

sub list_disabled_profiles {
    my ($self) = @_;

    my $directory = $self->profile_dir() . '/disable';
    if (!-d $directory) {
        print "No AppArmor disable directory exists.\n";
        return 0;
    }
    my @entries = grep { -l $_ } glob("$directory/*");
    if (!@entries) {
        print "No disabled AppArmor profiles were found.\n";
        return 0;
    }
    for my $entry (sort @entries) {
        my $target = readlink $entry;
        defined($target) or die "cannot inspect disabled AppArmor profile: $entry\n";
        printf "%-40s -> %s\n", basename($entry), $target;
    }
    return 0;
}

sub show_events {
    my ($self, $kind) = @_;

    my ($pattern, $label) = $kind eq 'complain'
        ? ('apparmor="ALLOWED"', 'complain-mode ALLOWED events')
        : $kind eq 'denied'
        ? ('apparmor="DENIED"', 'enforced DENIED events')
        : die "unsupported AppArmor audit event kind: $kind\n";
    my $journalctl = $self->_program('journalctl');
    print "--- AppArmor $label from the last 24 hours ---\n";
    my $status = $self->command()->run(
        $journalctl,
        '--dmesg',
        '--since=-24h',
        '--no-pager',
        "--grep=$pattern",
    );
    print "No AppArmor $label were found in the kernel journal.\n" if $status != 0;
    return 0;
}

sub _update_modes {
    my ($self, $profiles, $requested_mode, $label) = @_;

    $self->_validate_mode_config();
    -x $self->mode_helper()
        or die "managed AppArmor mode helper is unavailable: " . $self->mode_helper() . "\n";
    my %wanted = map { $_ => 1 } @{$profiles};
    my $content = $self->_read_small_file($self->mode_config(), $self->maximum_config_bytes(), 'managed AppArmor mode configuration');
    my %found;
    my @rendered;
    for my $line (split /\n/, $content, -1) {
        if ($line =~ /^\s*(?:#|\z)/) {
            push @rendered, $line;
            next;
        }
        my @fields = split /\s+/, $line;
        @fields == 4
            or die "managed AppArmor application profile is missing, duplicated, or malformed\n";
        if ($wanted{$fields[2]}) {
            ++$found{$fields[2]};
            $fields[0] = $requested_mode;
        }
        push @rendered, join q{ }, @fields;
    }
    for my $profile (@{$profiles}) {
        ($found{$profile} // 0) == 1
            or die "managed AppArmor application profile is missing, duplicated, or malformed\n";
    }
    my ($fh, $new_path) = tempfile('.managed-modes.new.XXXXXX', DIR => dirname($self->mode_config()), UNLINK => 0);
    print {$fh} join("\n", @rendered)
        or die "cannot write managed AppArmor mode update: $!\n";
    close $fh or die "cannot close managed AppArmor mode update: $!\n";
    chmod 0644, $new_path or die "cannot protect managed AppArmor mode update: $!\n";
    my ($backup_fh, $backup_path) = tempfile('.managed-modes.backup.XXXXXX', DIR => dirname($self->mode_config()), UNLINK => 0);
    close $backup_fh;
    copy($self->mode_config(), $backup_path)
        or die "cannot back up managed AppArmor mode configuration: $!\n";
    rename $new_path, $self->mode_config()
        or die "cannot publish managed AppArmor mode update: $!\n";
    my $status = $self->command()->run($self->mode_helper());
    if ($status == 0) {
        unlink $backup_path;
        print "Updated $label AppArmor profile mode to $requested_mode.\n";
        return 0;
    }
    rename $backup_path, $self->mode_config()
        or die "AppArmor reconciliation failed and the mode configuration could not be restored\n";
    $self->command()->run($self->mode_helper());
    die "AppArmor reconciliation failed with status $status; the previous mode policy was restored\n";
}

sub set_application_mode {
    my ($self, $application, $mode, $confirmation) = @_;

    $confirmation eq 'confirmed-apparmor-mode-change'
        or die "AppArmor application mode changes require explicit confirmation\n";
    $mode =~ /\A(?:enforce|complain|disable)\z/
        or die "unsupported AppArmor mode: $mode\n";
    my @profiles = $self->_application_profiles($application);
    return $self->_update_modes(
        \@profiles,
        $mode,
        $application,
    );
}

sub set_desktop_state {
    my ($self, $mode, $confirmation) = @_;

    $confirmation eq 'confirmed-apparmor-desktop-state-change'
        or die "AppArmor desktop profile mode changes require explicit confirmation\n";
    $mode =~ /\A(?:enforce|complain|disable)\z/
        or die "unsupported AppArmor desktop profile mode: $mode\n";
    return $self->_update_modes(
        [$self->_desktop_profiles()],
        $mode,
        'all declared managed profiles',
    );
}

sub set_application_audit {
    my ($self, $application, $mode, $confirmation) = @_;

    $confirmation eq 'confirmed-apparmor-audit-change'
        or die "AppArmor application audit changes require explicit confirmation\n";
    $mode =~ /\A(?:enable|disable)\z/
        or die "unsupported AppArmor audit mode: $mode\n";
    my $audit = $self->_program('aa-audit');
    my @changed;
    for my $profile ($self->_application_profiles($application)) {
        my @argv = $mode eq 'enable' ? ($audit, $profile) : ($audit, '--remove', $profile);
        my $status = $self->command()->run(@argv);
        if ($status != 0) {
            for my $changed (@changed) {
                my @rollback = $mode eq 'enable'
                    ? ($audit, '--remove', $changed)
                    : ($audit, $changed);
                $self->command()->run(@rollback);
            }
            die "AppArmor audit mode update failed with status $status; completed changes were rolled back\n";
        }
        push @changed, $profile;
    }
    print "Updated $application AppArmor audit mode to $mode.\n";
    return 0;
}

sub reload_managed_modes {
    my ($self, $confirmation) = @_;

    $confirmation eq 'confirmed-apparmor-reload'
        or die "managed AppArmor mode reload requires explicit confirmation\n";
    -x $self->mode_helper()
        or die "managed AppArmor mode helper is unavailable: " . $self->mode_helper() . "\n";
    return $self->command()->run($self->mode_helper());
}

sub reload_service {
    my ($self, $confirmation) = @_;

    $confirmation eq 'confirmed-apparmor-service-reload'
        or die "AppArmor service reload requires explicit confirmation\n";
    return $self->command()->run($self->_program('systemctl'), 'reload', 'apparmor.service');
}

1;
