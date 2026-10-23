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
    capture_loaded_state
    profile_labels
    loaded_profile_mode_matches
);
use AppArmor::ManagedModes::LocalChildren qw(child_mode_matches apply_child_mode child_source_path);
use AppArmor::ManagedModes::TrustedPath qw(read_bounded_file);

our @EXPORT_OK = qw(
    apply_profile_mode
    profile_defines_labels
    profile_mode_matches
);

sub profile_defines_labels {
    my ($entry, $options, $workspace, $tools) = @_;
    return @{profile_labels($entry, $options, $workspace, $tools)} ? 1 : 0;
}

sub profile_mode_matches {
    my ($mode, $profile_name, $profile_path, $profile_dir) = @_;
    my $disable_link = "$profile_dir/disable/$profile_name";

    if ($mode eq 'complain') {
        return !-e $disable_link &&
            !-l $disable_link &&
            _declared_profile_modes_match($profile_path, $mode) &&
            child_mode_matches($mode, $profile_name, $profile_dir);
    }
    if ($mode eq 'enforce') {
        return !-e $disable_link &&
            !-l $disable_link &&
            _declared_profile_modes_match($profile_path, $mode) &&
            child_mode_matches($mode, $profile_name, $profile_dir);
    }
    if ($mode eq 'disable') {
        return -l $disable_link &&
            defined(readlink($disable_link)) &&
            readlink($disable_link) eq $profile_path;
    }
    return 0;
}

sub apply_profile_mode {
    my ($entry, $options, $workspace, $tools, $loaded_state) = @_;
    my $mode = $entry->{mode};
    my $profile_name = $entry->{name};
    my $profile_path = $entry->{path};
    my $profile_dir = $options->{profile_dir};

    _validate_disable_entry($profile_name, $profile_path, $profile_dir);

    # Reject an empty or include-only required source before editing modes.
    if (($mode eq 'enforce' || $mode eq 'complain') &&
        !_entry_is_optional($entry)) {
        profile_defines_labels($entry, $options, $workspace, $tools);
    }

    if (($mode eq 'enforce' || $mode eq 'complain') &&
        _entry_is_optional($entry) &&
        !profile_defines_labels($entry, $options, $workspace, $tools)) {
        my $disable_link = "$profile_dir/disable/$profile_name";
        my $changed = -l $disable_link ? 1 : 0;
        if (-l $disable_link) {
            unlink $disable_link or
                fatal("cannot remove AppArmor disable entry: $disable_link");
        }
        info(
            'optional AppArmor profile source defines no labels; '
            . "no independent ${mode} mode exists: $profile_name"
        );
        return $changed;
    }

    my $source_matches = profile_mode_matches(
        $mode, $profile_name, $profile_path, $profile_dir,
    );
    if ($options->{reload_profiles} && !defined $loaded_state) {
        $loaded_state = capture_loaded_state($options, $workspace);
    }
    my $force_reload = $options->{force_reload} &&
        ($mode eq 'enforce' || $mode eq 'complain');
    if ($source_matches && !$force_reload && (!$options->{reload_profiles} ||
        loaded_profile_mode_matches($entry, $loaded_state, $options, $workspace, $tools))) {
        info($options->{reload_profiles}
            ? "profile source and loaded state already agree: $profile_name mode=$mode"
            : "profile source already uses ${mode} mode: $profile_name");
        return 0;
    }

    if ($mode eq 'enforce' || $mode eq 'complain') {
        if ($source_matches) {
            # Kernel-only drift must not rewrite an already-correct source or
            # run either aa-* mode editor. Ignore stale binary read caches.
            my $parser_path = "$options->{tool_dir}/apparmor_parser";
            $tools->require_executable('required AppArmor parser', $parser_path);
            info($force_reload
                ? "profile policy reload requested: $profile_name mode=$mode"
                : "profile kernel mode differs; reloading: $profile_name mode=$mode");
            $tools->run_or_exit(
                $parser_path, '-r', '-T', '-I', $profile_dir,
                '--base', $profile_dir, $profile_path,
            );
            return 1;
        }
    }

    if ($mode eq 'disable') {
        _disable_profile(
            $entry,
            $options,
            $workspace,
            $tools,
            $loaded_state,
        );
        return 1;
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
    for my $include_name (qw(abi abstractions tunables)) {
        my $include_path = "$options->{profile_dir}/$include_name";
        next if !-e $include_path;
        symlink $include_path, "$mode_work_dir/$include_name" or
            fatal("cannot stage AppArmor profile include: $include_path");
    }

    my $child_path = child_source_path($profile_name, $profile_dir);
    if (defined($child_path)) {
        mkdir "$mode_work_dir/local", 0700
            or fatal('cannot stage AppArmor local include directory');
        opendir my $local_dh, "$profile_dir/local"
            or fatal('cannot inspect AppArmor local include directory');
        my $count = 0;
        while (my $name = readdir $local_dh) {
            next if $name eq '.' || $name eq '..';
            ++$count <= 4096 or fatal('too many AppArmor local includes');
            next if $name eq $profile_name;
            symlink "$profile_dir/local/$name", "$mode_work_dir/local/$name"
                or fatal('cannot stage AppArmor local include');
        }
        closedir $local_dh or fatal('cannot close AppArmor local include directory');
        $workspace->copy_file($child_path, "$mode_work_dir/local/$profile_name",
                              'cannot stage AppArmor child source');
    }
    elsif (-d "$profile_dir/local") {
        symlink "$profile_dir/local", "$mode_work_dir/local"
            or fatal('cannot stage AppArmor local include directory');
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

    my @audit_command = ($audit_tool_path, '--remove', '--no-reload');
    push @audit_command, '-d', $mode_work_dir, $mode_profile_path;
    $tools->run_or_exit(@audit_command);

    # aa-* edits the profile file, not an included local/ child declaration.
    # Update the three tracked child sources before checking the whole file.
    apply_child_mode($mode, $profile_name, $mode_work_dir, $workspace);

    profile_mode_matches(
        $mode,
        $profile_name,
        $mode_profile_path,
        $mode_work_dir,
    ) || fatal("AppArmor profile did not enter ${mode} mode: $profile_name");

    my $parser_path = "$options->{tool_dir}/apparmor_parser";
    $tools->require_executable('required AppArmor parser', $parser_path);
    # AppArmor 4.1.x skips cache initialization for -K but leaves write_cache
    # set when parser.conf enables write-cache. A successful -Q compilation
    # then reports "Failed to create cache" without a cache destination.
    # Validate the private candidate with explicit managed include/ABI inputs
    # and no parser configuration. The published-source reload below still
    # uses the normal configuration and updates the production cache.
    $tools->run_or_exit($parser_path, '--config-file=/dev/null',
                         '--policy-features=/usr/share/apparmor-features/features',
                         '-Q', '-K', '-T', '-I', $mode_work_dir,
                         '-I', '/usr/share/apparmor',
                         '--base', $mode_work_dir, $mode_profile_path);

    my $recovery = $workspace->tempdir('.apparmor-mode-recovery',
                                      'cannot create AppArmor mode recovery', $profile_dir);
    my @sources = ([$profile_path, $mode_profile_path, "$recovery/parent"]);
    push @sources, [$child_path, "$mode_work_dir/local/$profile_name", "$recovery/child"]
        if defined($child_path);
    for my $source (@sources) {
        $workspace->copy_file($source->[0], $source->[2], 'cannot back up AppArmor mode source');
        open my $backup_fh, '<', $source->[2] or fatal('cannot open AppArmor mode backup');
        $backup_fh->sync() or fatal('cannot synchronize AppArmor mode backup');
        close $backup_fh or fatal('cannot close AppArmor mode backup');
    }
    open my $manifest_fh, '>', "$recovery/restore-paths"
        or fatal('cannot create AppArmor recovery path record');
    print {$manifest_fh} join("\n", map { "$_->[2] -> $_->[0]" } @sources), "\n"
        or fatal('cannot write AppArmor recovery path record');
    $manifest_fh->sync() or fatal('cannot synchronize AppArmor recovery path record');
    close $manifest_fh or fatal('cannot close AppArmor recovery path record');
    $workspace->sync_directory($recovery);
    $workspace->sync_directory($profile_dir);
    # END cleanup must never delete the only recovery copy after failed rollback.
    $workspace->retain_dir($recovery);
    my $disable_link = "$profile_dir/disable/$profile_name";
    my $was_disabled = -l $disable_link;
    my $reload_attempted = 0;
    my $ok = eval {
        local $AppArmor::ManagedModes::CLI::THROW_FAILURE = 1;
        for my $source (@sources) {
            $workspace->publish_file($source->[1], $source->[0], 'cannot publish AppArmor mode source');
        }
        if ($was_disabled) {
            unlink $disable_link or fatal('cannot remove AppArmor disable entry');
            $workspace->sync_directory("$profile_dir/disable");
        }
        if ($options->{reload_profiles}) {
            $reload_attempted = 1;
            $tools->run_or_exit($parser_path, '-r', '-T', '-I', $profile_dir,
                                 '--base', $profile_dir, $profile_path);
            my $current = capture_loaded_state($options, $workspace);
            loaded_profile_mode_matches($entry, $current, $options, $workspace, $tools)
                or fatal('AppArmor loaded modes do not match the published sources');
        }
        1;
    };
    if (!$ok) {
        my $error = $@ || "AppArmor mode transition failed\n";
        my $restored = eval {
            local $AppArmor::ManagedModes::CLI::THROW_FAILURE = 1;
            for my $source (reverse @sources) {
                $workspace->publish_file($source->[2], $source->[0], 'cannot restore AppArmor mode source');
            }
            if ($was_disabled && !-l $disable_link) {
                symlink $profile_path, $disable_link or fatal('cannot restore AppArmor disable entry');
                $workspace->sync_directory("$profile_dir/disable");
            }
            if ($reload_attempted) {
                $tools->run_or_exit($parser_path, $was_disabled ? '-R' : '-r', '-T',
                                     '-I', $profile_dir, '--base', $profile_dir, $profile_path);
                my $current = capture_loaded_state($options, $workspace);
                for my $label (@{profile_labels($entry, $options, $workspace, $tools)}) {
                    my @old = grep { /^\Q$label\E \(/ } split /\n/, $loaded_state;
                    my @now = grep { /^\Q$label\E \(/ } split /\n/, $current;
                    join("\n", @old) eq join("\n", @now)
                        or fatal('restored AppArmor loaded modes differ from previous state');
                }
            }
            1;
        };
        if ($restored) {
            $workspace->remove_dir($recovery);
        }
        else {
            warn("AppArmor rollback failed; recovery retained at $recovery");
            fatal($error, 3);
        }
        fatal($error);
    }
    $workspace->remove_dir($recovery);
    $workspace->remove_dir($mode_work_dir);
    return 1;
}

sub _disable_profile {
    my ($entry, $options, $workspace, $tools, $loaded_state) = @_;
    my $profile_name = $entry->{name};
    my $profile_path = $entry->{path};
    my $profile_dir = $options->{profile_dir};
    my $disable_dir = "$profile_dir/disable";
    my $disable_link = "$disable_dir/$profile_name";

    _validate_disable_entry($profile_name, $profile_path, $profile_dir);
    if (!-d $disable_dir) {
        mkdir $disable_dir, 0755 or
            fatal("cannot create AppArmor disable directory: $disable_dir");
        chmod 0755, $disable_dir or
            fatal("cannot set AppArmor disable directory permissions: $disable_dir");
    }
    if (!-l $disable_link) {
        symlink $profile_path, $disable_link or
            fatal("cannot create AppArmor disable entry: $disable_link");
    }

    if ($options->{reload_profiles}) {
        my $limits = limits();
        my $parser_path = "$options->{tool_dir}/apparmor_parser";
        $tools->require_executable('required AppArmor parser', $parser_path);
        my $labels = profile_labels($entry, $options, $workspace, $tools);
        my $loaded = @$labels ? scalar(grep {
            contains_label_prefix($loaded_state, $_)
        } @$labels) : undef;
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

sub _declared_profile_modes_match {
    my ($path, $mode) = @_;
    my $content = read_bounded_file('AppArmor profile', $path,
                                    limits()->{max_profile_bytes});
    my $count = 0;
    for my $line (split /\n/, $content) {
        # Each declaration has its own kernel mode. A single complain flag in
        # a file with many profiles cannot stand in for all other labels.
        next unless $line =~ /^[ \t]*(?:profile[ \t]+|\^[^ \t]+[ \t]+|"?\/)[^\n]*\{[ \t]*(?:#.*)?$/;
        ++$count;
        my $flags = $line =~ /\bflags=\(([^()]*)\)/ ? $1 : '';
        my %flag = map { $_ => 1 } grep { length } split /[\s,]+/, $flags;
        return 0 if $flag{audit} || $flag{unconfined} || $flag{default_allow};
        return 0 if $mode eq 'complain' ? !$flag{complain} : $flag{complain};
    }
    return $count > 0;
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
