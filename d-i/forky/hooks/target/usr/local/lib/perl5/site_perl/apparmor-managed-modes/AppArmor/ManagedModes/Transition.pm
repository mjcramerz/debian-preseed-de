package AppArmor::ManagedModes::Transition;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

use AppArmor::ManagedModes::CLI qw(fatal info warn);
use AppArmor::ManagedModes::Config qw(limits);
use AppArmor::ManagedModes::LoadedState qw(
    contains_label_prefix
    read_snapshot
);
use AppArmor::ManagedModes::TrustedPath qw(
    bounded_capture
    file_size
);

our @EXPORT_OK = qw(
    apply_profile_mode
    profile_defines_labels
    profile_mode_matches
);

sub profile_defines_labels {
    my ($entry, $options, $workspace, $tools) = @_;
    my $limits = limits();
    my $profile_name = $entry->{name};
    my $parser_path = "$options->{tool_dir}/apparmor_parser";
    $tools->require_executable('required AppArmor parser', $parser_path);

    my ($names_fh, $profile_names_path) =
        $workspace->tempfile(
            'apparmor-profile-names',
            'cannot create AppArmor profile-name snapshot',
        );
    close $names_fh ||
        fatal('cannot create AppArmor profile-name snapshot');
    $tools->run_stdout_to_file_limited_or_exit(
        $profile_names_path,
        $limits->{max_profile_names_bytes},
        'AppArmor profile labels exceed '
            . "$limits->{max_profile_names_bytes} bytes: $profile_name",
        $parser_path,
        '-q',
        '-N',
        '-Q',
        '-K',
        '-T',
        '-I',
        $options->{profile_dir},
        '--base',
        $options->{profile_dir},
        $entry->{path},
    );
    my $profile_names_size = file_size($profile_names_path);
    $workspace->remove_file($profile_names_path);
    return $profile_names_size > 0 ? 1 : 0;
}

sub profile_mode_matches {
    my ($mode, $profile_name, $profile_path, $profile_dir) = @_;
    my $disable_link = "$profile_dir/disable/$profile_name";

    if ($mode eq 'complain') {
        return !-e $disable_link &&
            !-l $disable_link &&
            _file_has_match(
                $profile_path,
                qr/flags=\([^)]*complain(?:[[:space:],)]|\z)/,
            ) &&
            !_file_has_match(
                $profile_path,
                qr/flags=\([^)]*audit(?:[[:space:],)]|\z)/,
            );
    }
    if ($mode eq 'enforce') {
        return !-e $disable_link &&
            !-l $disable_link &&
            !_file_has_match(
                $profile_path,
                qr/flags=\([^)]*(?:audit|complain|default_allow|unconfined)/,
            );
    }
    if ($mode eq 'disable') {
        return -l $disable_link &&
            defined(readlink($disable_link)) &&
            readlink($disable_link) eq $profile_path;
    }
    return 0;
}

sub apply_profile_mode {
    my ($entry, $options, $workspace, $tools) = @_;
    my $mode = $entry->{mode};
    my $profile_name = $entry->{name};
    my $profile_path = $entry->{path};
    my $profile_dir = $options->{profile_dir};

    _validate_disable_entry($profile_name, $profile_path, $profile_dir);

    if (($mode eq 'enforce' || $mode eq 'complain') &&
        _entry_is_optional($entry) &&
        !profile_defines_labels($entry, $options, $workspace, $tools)) {
        my $disable_link = "$profile_dir/disable/$profile_name";
        if (-l $disable_link) {
            unlink $disable_link ||
                fatal("cannot remove AppArmor disable entry: $disable_link");
        }
        info(
            'optional AppArmor profile source defines no labels; '
            . "no independent ${mode} mode exists: $profile_name"
        );
        return;
    }

    if ($mode eq 'enforce' || $mode eq 'complain') {
        if (profile_mode_matches($mode, $profile_name, $profile_path, $profile_dir)) {
            if (!$options->{reload_profiles}) {
                info("profile source already uses ${mode} mode: $profile_name");
                return;
            }
            info(
                "profile source already uses ${mode} mode; reloading: "
                . $profile_name
            );
        }

        my $disable_link = "$profile_dir/disable/$profile_name";
        if (-l $disable_link) {
            unlink $disable_link ||
                fatal("cannot remove AppArmor disable entry: $disable_link");
        }
    }

    if ($mode eq 'disable') {
        _disable_profile(
            $entry,
            $options,
            $workspace,
            $tools,
        );
        return;
    }
    $mode eq 'enforce' || $mode eq 'complain' ||
        fatal("unsupported AppArmor mode: $mode");

    my $tool_name = $mode eq 'enforce' ? 'aa-enforce' : 'aa-complain';
    my $tool_path = "$options->{tool_dir}/$tool_name";
    $tools->require_executable('required AppArmor tool', $tool_path);
    my $audit_tool_path = "$options->{tool_dir}/aa-audit";
    $tools->require_executable('required AppArmor audit tool', $audit_tool_path);

    my $mode_work_dir = $workspace->tempdir(
        'apparmor-profile-mode',
        'cannot create isolated AppArmor mode workspace',
    );
    for my $include_name (qw(abi abstractions tunables local)) {
        my $include_path = "$options->{profile_dir}/$include_name";
        next if !-e $include_path;
        symlink $include_path, "$mode_work_dir/$include_name" ||
            fatal("cannot stage AppArmor profile include: $include_path");
    }

    my $mode_profile_path = "$mode_work_dir/$profile_name";
    $workspace->copy_file(
        $profile_path,
        $mode_profile_path,
        "cannot stage AppArmor profile for mode transition: $profile_name",
    );

    my $force_argument = $tools->force_argument($tool_name, $tool_path);
    my @mode_command = ($tool_path);
    push @mode_command, $force_argument if $force_argument ne '';
    push @mode_command, '--no-reload', '-d', $mode_work_dir, $mode_profile_path;
    $tools->run_or_exit(@mode_command);

    my @audit_command = ($audit_tool_path, '--remove');
    push @audit_command, '--no-reload' if !$options->{reload_profiles};
    push @audit_command, '-d', $mode_work_dir, $mode_profile_path;
    $tools->run_or_exit(@audit_command);

    profile_mode_matches(
        $mode,
        $profile_name,
        $mode_profile_path,
        $options->{profile_dir},
    ) || fatal("AppArmor profile did not enter ${mode} mode: $profile_name");

    $workspace->publish_file(
        $mode_profile_path,
        $profile_path,
        "cannot publish AppArmor profile mode: $profile_name",
    );
    $workspace->remove_dir($mode_work_dir);
}

sub _disable_profile {
    my ($entry, $options, $workspace, $tools) = @_;
    my $profile_name = $entry->{name};
    my $profile_path = $entry->{path};
    my $profile_dir = $options->{profile_dir};
    my $disable_dir = "$profile_dir/disable";
    my $disable_link = "$disable_dir/$profile_name";

    _validate_disable_entry($profile_name, $profile_path, $profile_dir);
    if (!-d $disable_dir) {
        mkdir $disable_dir, 0755 ||
            fatal("cannot create AppArmor disable directory: $disable_dir");
        chmod 0755, $disable_dir ||
            fatal("cannot set AppArmor disable directory permissions: $disable_dir");
    }
    if (!-l $disable_link) {
        symlink $profile_path, $disable_link ||
            fatal("cannot create AppArmor disable entry: $disable_link");
    }

    if ($options->{reload_profiles}) {
        my $limits = limits();
        my $parser_path = "$options->{tool_dir}/apparmor_parser";
        $tools->require_executable('required AppArmor parser', $parser_path);
        my $loaded = _profile_is_loaded(
            $entry,
            $options,
            $workspace,
            $tools,
        );
        if (!defined $loaded) {
            info(
                'optional AppArmor profile defines no labels; skipping unload: '
                . $profile_name
            );
        }
        elsif (!$loaded) {
            info(
                'disabled AppArmor profile was already absent from the kernel: '
                . $profile_name
            );
        }
        else {
            my ($error_fh, $error_snapshot) =
                $workspace->tempfile(
                    'apparmor-unload',
                    'cannot create AppArmor unload error snapshot',
                );
            close $error_fh ||
                fatal('cannot create AppArmor unload error snapshot');

            my $status = $tools->run_with_stderr_file_limited(
                $error_snapshot,
                $limits->{max_tool_diagnostic_bytes},
                'AppArmor unload diagnostics exceed '
                    . "$limits->{max_tool_diagnostic_bytes} bytes: $profile_name",
                $parser_path,
                '-I',
                $profile_dir,
                '--base',
                $profile_dir,
                '-R',
                $profile_path,
            );
            if ($status == 0) {
                # The parser removed the selected profile.
            }
            elsif (_file_contains($error_snapshot, q{Profile doesn't exist})) {
                info(
                    'disabled AppArmor profile was already absent from the kernel: '
                    . $profile_name
                );
            }
            else {
                _write_file_to_stderr($error_snapshot);
                warn(
                    'could not unload disabled AppArmor profile; loaded-state '
                    . "verification will decide: $profile_name"
                );
            }
            $workspace->remove_file($error_snapshot);
        }
    }

    profile_mode_matches('disable', $profile_name, $profile_path, $profile_dir) ||
        fatal("AppArmor profile did not enter disable mode: $profile_name");
}

sub _profile_is_loaded {
    my ($entry, $options, $workspace, $tools) = @_;
    my $limits = limits();
    my $profile_name = $entry->{name};
    my $profile_path = $entry->{path};
    my $parser_path = "$options->{tool_dir}/apparmor_parser";
    my $profile_dir = $options->{profile_dir};
    $tools->require_executable('required AppArmor parser', $parser_path);

    my ($names_fh, $profile_names_path) =
        $workspace->tempfile(
            'apparmor-profile-names',
            'cannot create AppArmor profile-name snapshot',
        );
    close $names_fh ||
        fatal('cannot create AppArmor profile-name snapshot');
    $tools->run_stdout_to_file_limited_or_exit(
        $profile_names_path,
        $limits->{max_profile_names_bytes},
        'AppArmor profile labels exceed '
            . "$limits->{max_profile_names_bytes} bytes: $profile_name",
        $parser_path,
        '-q',
        '-N',
        '-Q',
        '-K',
        '-T',
        '-I',
        $profile_dir,
        '--base',
        $profile_dir,
        $profile_path,
    );
    my $profile_names_size = file_size($profile_names_path);
    if ($profile_names_size == 0 && _entry_is_optional($entry)) {
        $workspace->remove_file($profile_names_path);
        return;
    }
    $profile_names_size > 0 ||
        fatal("AppArmor profile defines no labels: $profile_name");
    $profile_names_size <= $limits->{max_profile_names_bytes} ||
        fatal(
            'AppArmor profile labels exceed '
            . "$limits->{max_profile_names_bytes} bytes: $profile_name"
        );

    my ($loaded_fh, $loaded_snapshot_path) =
        $workspace->tempfile(
            'apparmor-loaded-profiles',
            'cannot create loaded AppArmor profile snapshot',
        );
    close $loaded_fh ||
        fatal('cannot create loaded AppArmor profile snapshot');
    bounded_capture(
        'loaded AppArmor profile state',
        $options->{loaded_profiles_path},
        $loaded_snapshot_path,
        $limits->{max_loaded_profiles_bytes},
    );
    my $loaded_state = read_snapshot($loaded_snapshot_path);
    $workspace->remove_file($loaded_snapshot_path);

    my $is_loaded = 0;
    open my $labels_fh, '<:raw', $profile_names_path ||
        fatal("cannot derive AppArmor profile labels: $profile_name");
    while (my $profile_label = <$labels_fh>) {
        $profile_label =~ s/\n\z//;
        $profile_label ne '' ||
            fatal("AppArmor parser returned an empty label: $profile_name");
        length($profile_label) <= $limits->{max_line_bytes} ||
            fatal(
                'AppArmor profile label exceeds '
                . "$limits->{max_line_bytes} bytes: $profile_name"
            );
        if (contains_label_prefix($loaded_state, $profile_label)) {
            $is_loaded = 1;
            last;
        }
    }
    close $labels_fh ||
        fatal("cannot derive AppArmor profile labels: $profile_name");
    $workspace->remove_file($profile_names_path);
    return $is_loaded;
}

sub _entry_is_optional {
    my ($entry) = @_;
    return defined($entry->{presence}) && $entry->{presence} eq 'optional';
}

sub _validate_disable_entry {
    my ($profile_name, $profile_path, $profile_dir) = @_;
    my $disable_dir = "$profile_dir/disable";
    my $disable_link = "$disable_dir/$profile_name";

    if (-e $disable_dir || -l $disable_dir) {
        -d $disable_dir && !-l $disable_dir ||
            fatal("AppArmor disable path must be a real directory: $disable_dir");
    }
    if (-e $disable_link || -l $disable_link) {
        -l $disable_link &&
            defined(readlink($disable_link)) &&
            readlink($disable_link) eq $profile_path ||
            fatal(
                'AppArmor disable entry is not the managed symlink: '
                . $disable_link
            );
    }
}

sub _file_has_match {
    my ($path, $pattern) = @_;

    open my $fh, '<:raw', $path or return 0;
    while (my $line = <$fh>) {
        if ($line =~ $pattern) {
            close $fh;
            return 1;
        }
    }
    close $fh;
    return 0;
}

sub _file_contains {
    my ($path, $needle) = @_;

    open my $fh, '<:raw', $path or return 0;
    my $tail = '';
    while (1) {
        my $buffer = '';
        my $read = sysread($fh, $buffer, 65_536);
        defined($read) || last;
        last if $read == 0;
        my $candidate = $tail . $buffer;
        if (index($candidate, $needle) >= 0) {
            close $fh;
            return 1;
        }
        my $tail_length = length($needle) - 1;
        $tail = $tail_length > 0 && length($candidate) > $tail_length
            ? substr($candidate, -$tail_length)
            : $candidate;
    }
    close $fh;
    return 0;
}

sub _write_file_to_stderr {
    my ($path) = @_;

    open my $fh, '<:raw', $path or return;
    while (1) {
        my $buffer = '';
        my $read = sysread($fh, $buffer, 65_536);
        last if !defined($read) || $read == 0;
        print STDERR $buffer;
    }
    close $fh;
}

1;
