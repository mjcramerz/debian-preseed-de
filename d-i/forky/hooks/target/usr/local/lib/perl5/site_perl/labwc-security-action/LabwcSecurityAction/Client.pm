package LabwcSecurityAction::Client;

use strict;
use warnings;

use Cwd qw(abs_path);
use Digest::SHA qw(sha256_hex sha512_hex);
use File::Basename qw(basename dirname);
use File::Find qw(find);
use File::Path qw(make_path);
use File::Spec;
use File::Temp qw(tempfile);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(strftime);
use Time::HiRes qw(time);
use Types::Standard qw(Int Object Str);

use LabwcSecurityAction::Command;
use LabwcSecurityAction::Logger;
use LabwcSecurityAction::ScannerLog;

has apparmor_easyprof_draft_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/apparmor/easyprof' },
);

has apparmor_max_draft_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 1_048_576 },
);

has apparmor_max_draft_files => (
    is      => 'ro',
    isa     => Int,
    default => sub { 64 },
);

has apparmor_profile_draft_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/apparmor/drafts' },
);

has clamav_database_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/clamav' },
);

has clamav_max_file_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 536_870_912 },
);

has command => (
    is      => 'ro',
    default => sub { LabwcSecurityAction::Command->new() },
);

has hash_manifest_max_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 107_374_182_400 },
);

has hash_manifest_max_files => (
    is      => 'ro',
    isa     => Int,
    default => sub { 50_000 },
);

has logger => (
    is      => 'ro',
    default => sub { LabwcSecurityAction::Logger->new() },
);

has scanner_log => (
    is      => 'ro',
    isa     => Object,
    default => sub { LabwcSecurityAction::ScannerLog->new() },
);

has root_helper => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/libexec/labwc-security-action-root' },
);

has self_path => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/usr/local/bin/labwc-security-action' },
);

sub _fatal {
    my ($self, $message) = @_;

    $self->logger()->error($message);
    print STDERR "fatal: $message\n";
    $self->_notify(1, 'requested-action');
    return 1;
}

sub _notify {
    my ($self, $status, $action) = @_;

    return if !defined($ENV{DBUS_SESSION_BUS_ADDRESS}) || $ENV{DBUS_SESSION_BUS_ADDRESS} eq q{};
    my $notify_send = $self->command()->executable('notify-send');
    return if !defined $notify_send;
    my ($urgency, $icon, $timeout, $summary, $body) = $status == 0
        ? (
            'normal',
            'security-high',
            10_000,
            'Security action completed',
            "The ${action} action completed successfully.",
        )
        : (
            'critical',
            'dialog-error',
            0,
            'Security action failed',
            "The ${action} action failed with status ${status}.",
        );
    $self->command()->run(
        $notify_send,
        '-a', 'Security Maintenance',
        '-u', $urgency,
        '-i', $icon,
        '-c', 'x-labwc.maintenance',
        '-t', $timeout,
        $summary,
        $body,
    );
    return;
}

sub _finish {
    my ($self, $status, $action) = @_;

    printf "\n=== Action finished with status %s ===\n", $status;
    $self->_notify($status, $action);
    if (-t STDIN) {
        print 'Press Enter to close this terminal...';
        scalar <STDIN>;
    }
    return $status;
}

sub _validate_request_shape {
    my ($self, $action, @args) = @_;

    my %no_arguments = map { $_ => 1 } qw(
      audit-security-posture scan-rootkits-rkhunter scan-rootkits-chkrootkit analyze-services
      check-firmware-security check-cpu-mitigations check-known-vulnerabilities
      check-package-integrity list-users list-non-sudo-users list-groups
      list-sudo-administrators list-passwordless-accounts audit-sudo-access
      show-clamav-signature-status update-clamav-signatures apparmor-status apparmor-enabled
      apparmor-unconfined apparmor-features-abi apparmor-managed-application-modes
      apparmor-list-drafts apparmor-validate-drafts apparmor-list-disabled-profiles
      audit-apparmor-complain audit-apparmor-denied aa-remove-unknown-dry-run
    );
    if ($no_arguments{$action}) {
        @args == 0 or die "$action does not accept arguments\n";
        return;
    }
    if ($action =~ /\A(?:inspect-service|scan-file-clamav|scan-folder-clamav|retrieve-file-hashes|create-folder-hash-manifest)\z/) {
        @args == 1 or die "$action requires exactly one argument\n";
        return;
    }
    if ($action eq 'verify-file-sha256') {
        @args == 2 or die "verify-file-sha256 requires a file and expected SHA-256 digest\n";
        return;
    }
    my %confirmed = (
        'generate-apparmor-rules'       => 'confirmed-apparmor-rule-generation',
        'reload-apparmor-managed-modes' => 'confirmed-apparmor-reload',
        'reload-apparmor-service'       => 'confirmed-apparmor-service-reload',
        'aa-logprof'                    => 'confirmed-apparmor-profile-tool',
    );
    if (exists $confirmed{$action}) {
        @args == 1 && $args[0] eq $confirmed{$action}
            or die "$action requires confirmation\n";
        return;
    }
    if ($action =~ /\A(?:aa-easyprof|aa-autodep|aa-genprof)\z/) {
        @args == 2 && $args[1] eq 'confirmed-apparmor-profile-tool'
            or die "$action requires an executable path and confirmation\n";
        return;
    }
    if ($action eq 'apparmor-activate-draft') {
        @args == 3 or die "apparmor-activate-draft requires an origin, profile name, and confirmation\n";
        ($args[0] eq 'easyprof' || $args[0] eq 'drafts')
            or die "unsupported AppArmor draft origin: $args[0]\n";
        $self->_validate_draft_name($args[1]);
        $args[2] eq 'confirmed-apparmor-draft-activation'
            or die "apparmor-activate-draft requires confirmation\n";
        return;
    }
    if ($action eq 'set-apparmor-desktop-state') {
        @args == 2 && $args[0] =~ /\A(?:enforce|complain|disable)\z/
            && $args[1] eq 'confirmed-apparmor-desktop-state-change'
            or die "set-apparmor-desktop-state requires a mode and confirmation\n";
        return;
    }
    if ($action eq 'set-apparmor-application-audit') {
        @args == 3 && $self->_valid_application($args[0]) && $args[1] =~ /\A(?:enable|disable)\z/
            && $args[2] eq 'confirmed-apparmor-audit-change'
            or die "set-apparmor-application-audit requires an application, mode, and confirmation\n";
        return;
    }
    if ($action eq 'set-apparmor-application-mode') {
        @args == 3 && $self->_valid_application($args[0]) && $args[1] =~ /\A(?:enforce|complain|disable)\z/
            && $args[2] eq 'confirmed-apparmor-mode-change'
            or die "set-apparmor-application-mode requires an application, mode, and confirmation\n";
        return;
    }
    die "unsupported security action: " . (defined($action) ? $action : 'unset') . "\n";
}

sub _valid_application {
    my ($self, $application) = @_;

    my %allowed = map { $_ => 1 } qw(
      bitwarden chromium code qoredb discord filen keepassxc ledger-live microsoft-edge
      mullvad-browser obsidian postman qbittorrent retroarch sleek spotify sqlitebrowser
      telegram-desktop totem tuta-mail vivaldi zoom
    );
    return $allowed{$application} ? 1 : 0;
}

sub _validate_absolute_path {
    my ($self, $label, $requested) = @_;

    defined($requested) && $requested =~ m{\A/}
        or die "$label must be absolute\n";
    $requested !~ /[\r\n]/
        or die "$label cannot contain newlines\n";
    my $resolved = abs_path($requested);
    defined($resolved)
        or die "unable to resolve $label: $requested\n";
    return $resolved;
}

sub _validate_regular_file {
    my ($self, $label, $requested) = @_;

    my $resolved = $self->_validate_absolute_path($label, $requested);
    -f $resolved
        or die "$label is not a regular file: $resolved\n";
    -r $resolved
        or die "$label is not readable: $resolved\n";
    return $resolved;
}

sub _validate_directory {
    my ($self, $label, $requested) = @_;

    my $resolved = $self->_validate_absolute_path($label, $requested);
    -d $resolved
        or die "$label is not a directory: $resolved\n";
    -r $resolved && -x $resolved
        or die "$label is not readable and searchable: $resolved\n";
    return $resolved;
}

sub _validate_sha256 {
    my ($self, $digest) = @_;

    $digest = lc($digest // q{});
    $digest =~ /\A[0-9a-f]{64}\z/
        or die "expected SHA-256 digest must contain exactly 64 hexadecimal characters\n";
    return $digest;
}

sub _digest_file {
    my ($self, $path, $bits, $deadline_seconds) = @_;

    my $started = time();
    open my $fh, '<', $path or die "cannot read $path: $!\n";
    binmode $fh;
    my $digest = Digest::SHA->new($bits);
    while (1) {
        time() - $started <= $deadline_seconds
            or die "hash calculation exceeded the managed ${deadline_seconds}s timeout\n";
        my $read = read $fh, my $buffer, 1_048_576;
        defined($read) or die "cannot read $path: $!\n";
        last if $read == 0;
        $digest->add($buffer);
    }
    close $fh or die "cannot close $path: $!\n";
    return $digest->hexdigest();
}

sub _list_drafts {
    my ($self) = @_;

    my @drafts;
    for my $spec (
        ['easyprof', $self->apparmor_easyprof_draft_dir()],
        ['drafts',   $self->apparmor_profile_draft_dir()],
    ) {
        my ($origin, $directory) = @{$spec};
        next if !-d $directory;
        opendir my $dh, $directory or die "cannot read AppArmor draft directory $directory: $!\n";
        while (my $name = readdir $dh) {
            next if $name eq q{.} || $name eq q{..};
            my $path = "$directory/$name";
            next if -l $path || !-f $path;
            $self->_validate_draft_name($name);
            my @stat = stat $path;
            @stat && $stat[7] <= $self->apparmor_max_draft_bytes()
                or die "AppArmor draft exceeds " . $self->apparmor_max_draft_bytes() . " bytes: $path\n";
            push @drafts, [$origin, $name, $path, $stat[7]];
            @drafts <= $self->apparmor_max_draft_files()
                or die "more than " . $self->apparmor_max_draft_files() . " AppArmor drafts were found\n";
        }
        closedir $dh or die "cannot close AppArmor draft directory $directory: $!\n";
    }
    return sort { $a->[2] cmp $b->[2] } @drafts;
}

sub _validate_draft_name {
    my ($self, $name) = @_;

    defined($name) && $name ne q{} && $name !~ /\A\./ && $name =~ /\A[A-Za-z0-9._+-]+\z/
        or die "invalid AppArmor draft profile name: " . (defined($name) ? $name : 'unset') . "\n";
    return;
}

sub _run_apparmor_list_drafts {
    my ($self, $action) = @_;

    printf "\n=== Security Maintenance: apparmor-list-drafts ===\n\n";
    my @drafts = $self->_list_drafts();
    if (!@drafts) {
        print "No generated AppArmor profile drafts were found.\n";
    }
    else {
        for my $draft (@drafts) {
            printf "%-9s %10s bytes  %s\n", $draft->[0], $draft->[3], $draft->[2];
        }
    }
    return $self->_finish(0, $action);
}

sub _run_apparmor_validate_drafts {
    my ($self, $action) = @_;

    my $parser = $self->command()->require_executable('apparmor_parser');
    printf "\n=== Security Maintenance: apparmor-validate-drafts ===\n\n";
    my @drafts = $self->_list_drafts();
    if (!@drafts) {
        print "No generated AppArmor profile drafts were found.\n";
        return $self->_finish(0, $action);
    }
    my $failed = 0;
    for my $draft (@drafts) {
        my $status = $self->command()->run(
            $parser,
            '--config-file', '/etc/apparmor/parser.conf',
            '-q', '-Q', '-K', '-T',
            $draft->[2],
        );
        if ($status == 0) {
            print "valid   $draft->[2]\n";
        }
        else {
            print "invalid $draft->[2]\n";
            $failed = 1;
        }
    }
    return $self->_finish($failed ? 1 : 0, $action);
}

sub _run_file_hashes {
    my ($self, $action, $requested) = @_;

    my $path = $self->_validate_regular_file('file hash path', $requested);
    my @stat = stat $path;
    @stat or die "unable to read file size: $path\n";
    my $sha256 = $self->_digest_file($path, 256, 600);
    my $sha512 = $self->_digest_file($path, 512, 600);
    printf "\n=== Security Maintenance: retrieve-file-hashes ===\n\n";
    printf "File: %s\nSize: %s bytes\n", $path, $stat[7];
    printf "SHA-256: %s\nSHA-512: %s\n", $sha256, $sha512;
    return $self->_finish(0, $action);
}

sub _run_verify_file_sha256 {
    my ($self, $action, $requested, $expected) = @_;

    my $path = $self->_validate_regular_file('SHA-256 verification path', $requested);
    $expected = $self->_validate_sha256($expected);
    my $actual = $self->_digest_file($path, 256, 600);
    printf "\n=== Security Maintenance: verify-file-sha256 ===\n\n";
    printf "File: %s\nExpected SHA-256: %s\nActual SHA-256:   %s\n\n", $path, $expected, $actual;
    if ($actual eq $expected) {
        print "Result: MATCH\n";
        return $self->_finish(0, $action);
    }
    print "Result: MISMATCH\n";
    return $self->_finish(1, $action);
}

sub _run_folder_hash_manifest {
    my ($self, $action, $requested) = @_;

    my $folder = $self->_validate_directory('folder hash path', $requested);
    my @root_stat = stat $folder;
    @root_stat or die "cannot inspect folder hash path: $folder\n";
    my ($root_device, $started) = ($root_stat[0], time());
    my (@files, $total_bytes);
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                time() - $started <= 300
                    or die "folder hash inventory exceeded the managed 300s timeout\n";
                my $path = $File::Find::name;
                my @stat = lstat $path;
                return if !@stat || !-f _;
                return if $stat[0] != $root_device;
                push @files, $path;
                @files <= $self->hash_manifest_max_files()
                    or die "folder hash inventory exceeds the managed " . $self->hash_manifest_max_files() . "-file limit\n";
                $total_bytes += $stat[7];
                $total_bytes <= $self->hash_manifest_max_bytes()
                    or die "folder hash inventory exceeds the managed " . $self->hash_manifest_max_bytes() . "-byte limit\n";
            },
        },
        $folder,
    );
    @files = sort @files;

    my $state_home = $ENV{XDG_STATE_HOME} // (($ENV{HOME} // q{}) . '/.local/state');
    $state_home =~ m{\A/}
        or die "XDG state directory must be an absolute path\n";
    my $report_dir = "$state_home/labwc/security-reports";
    make_path($report_dir, { mode => 0700 });
    chmod 0700, $report_dir or die "cannot protect security report directory $report_dir: $!\n";
    -d $report_dir && -w $report_dir
        or die "security report directory is not writable: $report_dir\n";
    my $name = 'sha256-tree-' . strftime('%Y%m%dT%H%M%SZ', gmtime()) . "-$$.txt";
    my ($fh, $temporary) = tempfile('.sha256-tree.XXXXXX', DIR => $report_dir, UNLINK => 0);
    my $hash_started = time();
    print {$fh} "# SHA-256 tree manifest\n";
    print {$fh} "# Root: $folder\n";
    print {$fh} "# Files: " . scalar(@files) . "\n";
    print {$fh} "# Bytes: $total_bytes\n";
    print {$fh} "# Filesystems: selected filesystem only\n";
    print {$fh} "# Symlinks: not followed\n";
    for my $path (@files) {
        time() - $hash_started <= 1800
            or die "folder SHA-256 manifest exceeded the managed 1800s timeout\n";
        my $digest = $self->_digest_file($path, 256, 600);
        (my $display_path = $path) =~ s/[\r\n]/?/g;
        print {$fh} "$digest  $display_path\n"
            or die "cannot write SHA-256 report: $!\n";
    }
    close $fh or die "cannot close SHA-256 report: $!\n";
    chmod 0600, $temporary or die "cannot protect SHA-256 report: $!\n";
    my $report = "$report_dir/$name";
    rename $temporary, $report or die "cannot publish SHA-256 report: $!\n";

    printf "\n=== Security Maintenance: create-folder-hash-manifest ===\n\n";
    printf "Folder: %s\nFiles: %s\nBytes: %s\nReport: %s\n\n", $folder, scalar(@files), $total_bytes, $report;
    print "--- Manifest preview ---\n";
    open my $preview, '<', $report or die "cannot read SHA-256 report: $!\n";
    for (1 .. 25) {
        my $line = <$preview>;
        last if !defined $line;
        print $line;
    }
    close $preview;
    return $self->_finish(0, $action);
}

sub _clamav_signatures_available {
    my ($self) = @_;

    -d $self->clamav_database_dir()
        or die "ClamAV signatures are unavailable; run Update ClamAV Signatures first\n";
    opendir my $dh, $self->clamav_database_dir()
        or die "cannot read ClamAV database directory: $!\n";
    while (my $name = readdir $dh) {
        next if $name !~ /\.(?:cvd|cld|cud|ndb|hdb|hsb|ldb)\z/;
        if (-f $self->clamav_database_dir() . "/$name") {
            closedir $dh;
            return;
        }
    }
    closedir $dh;
    die "ClamAV signatures are unavailable; run Update ClamAV Signatures first\n";
}

sub _run_clamav_signature_status {
    my ($self, $action) = @_;

    my $clamscan = $self->command()->require_executable('clamscan');
    my $timeout = $self->command()->require_executable('timeout');
    $self->_clamav_signatures_available();
    printf "\n=== Security Maintenance: show-clamav-signature-status ===\n\n";
    my $status = $self->scanner_log()->run(
        argv => [
            $timeout,
            '--signal=INT',
            '--kill-after=5s',
            '30s',
            $clamscan,
            '--version',
        ],
        label => 'clamav',
        tag   => 'managed-clamav-scan',
    );
    return $self->_finish($status, $action) if $status != 0;
    print "\n--- Signature database files ---\n";
    opendir my $dh, $self->clamav_database_dir()
        or die "cannot read ClamAV database directory: $!\n";
    my @entries;
    while (my $name = readdir $dh) {
        next if $name !~ /\.(?:cvd|cld|cud|ndb|hdb|hsb|ldb)\z/;
        my $path = $self->clamav_database_dir() . "/$name";
        next if !-f $path;
        my @stat = stat $path;
        push @entries, sprintf '%s | %s bytes | modified %s',
            $name,
            $stat[7],
            strftime('%Y-%m-%d %H:%M:%S', localtime($stat[9]));
    }
    closedir $dh;
    print "$_\n" for sort @entries;
    return $self->_finish(0, $action);
}

sub _validate_clamav_folder_limits {
    my ($self, $folder) = @_;

    my @root_stat = stat $folder;
    @root_stat or die "cannot inspect ClamAV scan folder: $folder\n";
    my ($device, $started) = ($root_stat[0], time());
    find(
        {
            no_chdir => 1,
            wanted   => sub {
                time() - $started <= 300
                    or die "unable to validate every ClamAV scan file below: $folder\n";
                my @stat = lstat $File::Find::name;
                return if !@stat || !-f _ || $stat[0] != $device;
                $stat[7] <= $self->clamav_max_file_bytes()
                    or die "ClamAV scan folder contains a regular file above the managed "
                        . $self->clamav_max_file_bytes() . "-byte limit\n";
            },
        },
        $folder,
    );
    return;
}

sub _run_clamav_scan {
    my ($self, $action, $kind, $requested) = @_;

    my ($path, $recursive, $timeout);
    if ($kind eq 'file') {
        $path = $self->_validate_regular_file('ClamAV scan file', $requested);
        my @stat = stat $path;
        $stat[7] <= $self->clamav_max_file_bytes()
            or die "ClamAV scan file exceeds the managed " . $self->clamav_max_file_bytes() . "-byte limit: $path\n";
        ($recursive, $timeout) = ('no', '15m');
    }
    elsif ($kind eq 'folder') {
        $path = $self->_validate_directory('ClamAV scan folder', $requested);
        $self->_validate_clamav_folder_limits($path);
        ($recursive, $timeout) = ('yes', '45m');
    }
    else {
        die "unsupported ClamAV scan kind: $kind\n";
    }
    my $clamscan = $self->command()->require_executable('clamscan');
    my $timeout_program = $self->command()->require_executable('timeout');
    $self->_clamav_signatures_available();
    printf "\n=== Security Maintenance: scan-%s-clamav ===\n\n", $kind;
    printf "Path: %s\nRecursive: %s\n", $path, $recursive;
    print "Mode: report only; infected files are never moved or deleted\n\n";
    my $status = $self->scanner_log()->run(
        argv => [
            $timeout_program,
            '--signal=INT',
            '--kill-after=30s',
            $timeout,
            $clamscan,
            "--recursive=$recursive",
            '--infected',
            '--cross-fs=no',
            '--follow-dir-symlinks=0',
            '--follow-file-symlinks=0',
            '--max-filesize=512M',
            '--max-scansize=2G',
            '--',
            $path,
        ],
        label => 'clamav',
        tag   => 'managed-clamav-scan',
    );
    return $self->_finish($status, $action);
}

sub _run_terminal_action {
    my ($self, $action, @args) = @_;

    if ($action eq 'show-clamav-signature-status') {
        return $self->_run_clamav_signature_status($action);
    }
    if ($action eq 'scan-file-clamav') {
        return $self->_run_clamav_scan($action, 'file', $args[0]);
    }
    if ($action eq 'scan-folder-clamav') {
        return $self->_run_clamav_scan($action, 'folder', $args[0]);
    }
    if ($action eq 'retrieve-file-hashes') {
        return $self->_run_file_hashes($action, $args[0]);
    }
    if ($action eq 'create-folder-hash-manifest') {
        return $self->_run_folder_hash_manifest($action, $args[0]);
    }
    if ($action eq 'verify-file-sha256') {
        return $self->_run_verify_file_sha256($action, $args[0], $args[1]);
    }
    if ($action eq 'apparmor-list-drafts') {
        return $self->_run_apparmor_list_drafts($action);
    }
    if ($action eq 'apparmor-validate-drafts') {
        return $self->_run_apparmor_validate_drafts($action);
    }

    -x $self->root_helper()
        or die "privileged security helper is unavailable: " . $self->root_helper() . "\n";
    my $pkexec = $self->command()->require_executable('pkexec');
    printf "\n=== Security Maintenance: %s ===\n\n", $action;
    my $status = $self->command()->run($pkexec, $self->root_helper(), $action, @args);
    return $self->_finish($status, $action);
}

sub run {
    my ($self, @argv) = @_;

    return $self->_fatal('labwc-security-action must be launched by the logged-in desktop user')
        if $> == 0;
    my $status = eval {
        if (@argv && $argv[0] eq '--list-apparmor-draft-candidates') {
            shift @argv;
            @argv == 0 or die "--list-apparmor-draft-candidates does not accept arguments\n";
            print "$_->[0]/$_->[1]\n" for $self->_list_drafts();
            return 0;
        }
        my $in_terminal = 0;
        if (@argv && $argv[0] eq '--run') {
            shift @argv;
            $in_terminal = 1;
        }
        @argv or die "usage: labwc-security-action <action> [argument]\n";
        my $action = shift @argv;
        $self->_validate_request_shape($action, @argv);
        if ($in_terminal) {
            return $self->_run_terminal_action($action, @argv);
        }
        my $terminal = $self->command()->require_executable('labwc-terminal');
        return $self->command()->exec($terminal, '-e', $self->self_path(), '--run', $action, @argv);
    };
    return $status if defined($status) && !$@;
    my $error = $@ || 'security action failed';
    $error =~ s/\s+\z//;
    return $self->_fatal($error);
}

1;
