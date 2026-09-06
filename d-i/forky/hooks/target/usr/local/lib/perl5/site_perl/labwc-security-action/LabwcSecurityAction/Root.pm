package LabwcSecurityAction::Root;

use strict;
use warnings;

use File::Basename qw(basename);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object Str);

use LabwcSecurityAction::AppArmor;
use LabwcSecurityAction::Command;
use LabwcSecurityAction::Logger;
use LabwcSecurityAction::ScannerLog;

has command => (
    is      => 'ro',
    default => sub {
        return LabwcSecurityAction::Command->new(
            path => '/usr/sbin:/usr/bin:/sbin:/bin',
        );
    },
);

has logger => (
    is      => 'ro',
    default => sub { LabwcSecurityAction::Logger->new(tag => 'labwc-security-action-root') },
);

has scanner_log => (
    is      => 'ro',
    isa     => Object,
    default => sub { LabwcSecurityAction::ScannerLog->new() },
);

has apparmor => (
    is      => 'ro',
    default => sub {
        my ($self) = @_;
        return LabwcSecurityAction::AppArmor->new(
            logger => $self->logger(),
        );
    },
);

sub _fatal {
    my ($self, $message) = @_;

    $message =~ s/\s+\z//;
    $self->logger()->error($message);
    print STDERR "fatal: $message\n";
    return 1;
}

sub _require_pkexec_invoker {
    my ($self) = @_;

    my $uid = $ENV{PKEXEC_UID} // q{};
    $uid =~ /\A[1-9][0-9]*\z/
        or die "privileged security helper must be invoked by a non-root desktop user through pkexec\n";
    my $getent = $self->command()->require_executable('getent');
    my ($status) = $self->command()->capture(
        argv => [$getent, 'passwd', $uid],
    );
    $status == 0
        or die "pkexec invoking account does not exist: $uid\n";
    return;
}

sub _validate_service_name {
    my ($self, $name) = @_;

    defined($name) && $name =~ /\A[A-Za-z0-9@_.:-]+\z/ && $name !~ /\.\./ && $name =~ /\.service\z/
        or die "invalid systemd service name: " . (defined($name) ? $name : 'unset') . "\n";
    return $name;
}

sub _getent_records {
    my ($self, $database) = @_;

    my $getent = $self->command()->require_executable('getent');
    my ($status, $output) = $self->command()->capture(
        argv => [$getent, $database],
    );
    $status == 0
        or die "cannot enumerate $database records\n";
    return grep { $_ ne q{} } split /\n/, $output;
}

sub _normal_accounts {
    my ($self) = @_;

    my @accounts;
    for my $line ($self->_getent_records('passwd')) {
        my @fields = split /:/, $line, -1;
        next if @fields < 7 || $fields[2] !~ /\A[0-9]+\z/;
        push @accounts, $fields[0] if $fields[2] >= 1000 && $fields[2] < 65534;
    }
    return @accounts;
}

sub _account_has_sudo {
    my ($self, $account) = @_;

    my $id = $self->command()->require_executable('id');
    my ($status, $groups) = $self->command()->capture(
        argv => [$id, '-nG', $account],
    );
    return 0 if $status != 0;
    return scalar grep { $_ eq 'sudo' } split /\s+/, $groups;
}

sub _print_users {
    my ($self) = @_;

    for my $line ($self->_getent_records('passwd')) {
        my @fields = split /:/, $line, -1;
        next if @fields < 7;
        printf "%-24s uid=%-6s gid=%-6s home=%-28s shell=%s\n",
            $fields[0], $fields[2], $fields[3], $fields[5], $fields[6];
    }
    return 0;
}

sub _print_non_sudo_users {
    my ($self) = @_;

    print "$_\n" for grep { !$self->_account_has_sudo($_) } $self->_normal_accounts();
    return 0;
}

sub _print_groups {
    my ($self) = @_;

    for my $line ($self->_getent_records('group')) {
        my @fields = split /:/, $line, -1;
        next if @fields < 4;
        my $members = $fields[3] eq q{} ? '(none)' : $fields[3];
        printf "%-24s gid=%-6s members=%s\n", $fields[0], $fields[2], $members;
    }
    return 0;
}

sub _print_sudo_administrators {
    my ($self) = @_;

    print "$_\n" for grep { $self->_account_has_sudo($_) } $self->_normal_accounts();
    return 0;
}

sub _print_passwordless_accounts {
    my ($self) = @_;

    open my $fh, '<', '/etc/shadow' or die "cannot read /etc/shadow: $!\n";
    my $found = 0;
    while (my $line = <$fh>) {
        my @fields = split /:/, $line, -1;
        next if @fields < 2 || $fields[1] ne q{};
        print "$fields[0]\n";
        $found = 1;
    }
    close $fh or die "cannot close /etc/shadow: $!\n";
    print "No accounts with an empty password hash were found.\n" if !$found;
    return 0;
}

sub _audit_sudo_access {
    my ($self) = @_;

    my $visudo = $self->command()->require_executable('visudo');
    my $getent = $self->command()->require_executable('getent');
    print "--- sudoers syntax ---\n";
    my $status = $self->command()->run($visudo, '-c');
    return $status if $status != 0;
    print "\n--- sudo group ---\n";
    $self->command()->run($getent, 'group', 'sudo');
    print "\n--- active sudoers directives ---\n";
    for my $path ('/etc/sudoers', glob('/etc/sudoers.d/*')) {
        next if !-f $path || -l $path;
        print "\n[$path]\n";
        open my $fh, '<', $path or die "cannot read sudoers file $path: $!\n";
        while (my $line = <$fh>) {
            next if $line =~ /^\s*(?:#|\z)/;
            print $line;
        }
        close $fh or die "cannot close sudoers file $path: $!\n";
    }
    return 0;
}

sub _exec {
    my ($self, $name, @arguments) = @_;

    return $self->command()->exec($self->command()->require_executable($name), @arguments);
}

sub _run_scanner {
    my ($self, $tag, $name, @arguments) = @_;

    return $self->scanner_log()->run(
        argv  => [$self->command()->require_executable($name), @arguments],
        label => $name,
        tag   => $tag,
    );
}

sub _dispatch {
    my ($self, $action, @args) = @_;

    if ($action eq 'audit-security-posture') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_run_scanner(
            'managed-lynis-scan',
            'lynis',
            'audit',
            'system',
            '--quick',
            '--no-colors',
            '--logfile',
            '/var/log/managed/lynis/lynis.log',
            '--report-file',
            '/var/log/managed/lynis/lynis-report.dat',
        );
    }
    if ($action eq 'scan-rootkits-rkhunter') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_run_scanner(
            'managed-rkhunter-scan',
            'rkhunter',
            '--check',
            '--skip-keypress',
            '--nocolors',
            '--appendlog',
            '--logfile',
            '/var/log/managed/rkhunter/rkhunter.log',
        );
    }
    if ($action eq 'scan-rootkits-chkrootkit') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_run_scanner('managed-chkrootkit-scan', 'chkrootkit');
    }
    if ($action eq 'analyze-services') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_exec('systemd-analyze', 'security', '--no-pager');
    }
    if ($action eq 'inspect-service') {
        @args == 1 or die "$action requires one service name\n";
        return $self->_exec('systemd-analyze', 'security', '--no-pager', $self->_validate_service_name($args[0]));
    }
    if ($action eq 'check-firmware-security') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_run_scanner('managed-fwupd-security-scan', 'fwupdmgr', 'security');
    }
    if ($action eq 'check-cpu-mitigations') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_run_scanner(
            'managed-spectre-meltdown-scan',
            'spectre-meltdown-checker',
        );
    }
    if ($action eq 'check-known-vulnerabilities') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_run_scanner('managed-debsecan-scan', 'debsecan');
    }
    if ($action eq 'check-package-integrity') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_run_scanner('managed-debsums-scan', 'debsums', '-s');
    }
    if ($action eq 'list-users') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_print_users();
    }
    if ($action eq 'list-non-sudo-users') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_print_non_sudo_users();
    }
    if ($action eq 'list-groups') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_print_groups();
    }
    if ($action eq 'list-sudo-administrators') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_print_sudo_administrators();
    }
    if ($action eq 'list-passwordless-accounts') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_print_passwordless_accounts();
    }
    if ($action eq 'audit-sudo-access') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_audit_sudo_access();
    }
    if ($action eq 'update-clamav-signatures') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_exec('systemctl', 'start', '--wait', 'managed-clamav-signature-update.service');
    }

    if ($action eq 'apparmor-status') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_exec('aa-status');
    }
    if ($action eq 'apparmor-enabled') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_exec('aa-enabled');
    }
    if ($action eq 'apparmor-unconfined') {
        @args == 0 or die "$action does not accept arguments\n";
        $self->command()->require_executable('ss');
        return $self->_exec('aa-unconfined', '--show=all', '--with-ss');
    }
    if ($action eq 'apparmor-features-abi') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_exec('aa-features-abi', '--extract', '--stdout');
    }
    if ($action eq 'apparmor-managed-application-modes') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->apparmor()->print_application_modes();
    }
    if ($action eq 'apparmor-list-drafts') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->apparmor()->list_drafts();
    }
    if ($action eq 'apparmor-validate-drafts') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->apparmor()->validate_drafts();
    }
    if ($action eq 'apparmor-activate-draft') {
        @args == 3 or die "$action requires an origin, profile name, and confirmation\n";
        return $self->apparmor()->activate_draft(@args);
    }
    if ($action eq 'apparmor-list-disabled-profiles') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->apparmor()->list_disabled_profiles();
    }
    if ($action eq 'audit-apparmor-complain') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->apparmor()->show_events('complain');
    }
    if ($action eq 'audit-apparmor-denied') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->apparmor()->show_events('denied');
    }
    if ($action eq 'aa-easyprof') {
        @args == 2 or die "$action requires an executable path and confirmation\n";
        return $self->apparmor()->run_easyprof(@args);
    }
    if ($action eq 'aa-autodep') {
        @args == 2 or die "$action requires an executable path and confirmation\n";
        return $self->apparmor()->run_autodep(@args);
    }
    if ($action eq 'aa-logprof') {
        @args == 1 or die "$action requires confirmation\n";
        return $self->apparmor()->run_logprof(@args);
    }
    if ($action eq 'generate-apparmor-rules') {
        @args == 1 or die "$action requires confirmation\n";
        return $self->apparmor()->generate_rules(@args);
    }
    if ($action eq 'aa-genprof') {
        @args == 2 or die "$action requires an executable path and confirmation\n";
        return $self->apparmor()->run_genprof(@args);
    }
    if ($action eq 'set-apparmor-application-mode') {
        @args == 3 or die "$action requires an application, mode, and confirmation\n";
        return $self->apparmor()->set_application_mode(@args);
    }
    if ($action eq 'set-apparmor-desktop-state') {
        @args == 2 or die "$action requires a mode and confirmation\n";
        return $self->apparmor()->set_desktop_state(@args);
    }
    if ($action eq 'set-apparmor-application-audit') {
        @args == 3 or die "$action requires an application, mode, and confirmation\n";
        return $self->apparmor()->set_application_audit(@args);
    }
    if ($action eq 'aa-remove-unknown-dry-run') {
        @args == 0 or die "$action does not accept arguments\n";
        return $self->_exec('aa-remove-unknown', '-n');
    }
    if ($action eq 'reload-apparmor-managed-modes') {
        @args == 1 or die "$action requires confirmation\n";
        return $self->apparmor()->reload_managed_modes(@args);
    }
    if ($action eq 'reload-apparmor-service') {
        @args == 1 or die "$action requires confirmation\n";
        return $self->apparmor()->reload_service(@args);
    }
    die "unsupported privileged security action: " . (defined($action) ? $action : 'unset') . "\n";
}

sub run {
    my ($self, @argv) = @_;

    return $self->_fatal('privileged security helper must run as root') if $> != 0;
    my $status = eval {
        local $ENV{PATH} = '/usr/sbin:/usr/bin:/sbin:/bin';
        $self->_require_pkexec_invoker();
        @argv or die "usage: labwc-security-action-root <action> [argument]\n";
        my $action = shift @argv;
        return $self->_dispatch($action, @argv);
    };
    return $status if defined($status) && !$@;
    return $self->_fatal($@ || 'privileged security action failed');
}

1;
