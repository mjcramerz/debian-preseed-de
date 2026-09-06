package AppArmor::ManagedModes::Verify;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

use AppArmor::ManagedModes::CLI qw(fatal info);
use AppArmor::ManagedModes::Config qw(limits);
use AppArmor::ManagedModes::LoadedState qw(
    contains_exact_line
    contains_label_prefix
    read_snapshot
);
use AppArmor::ManagedModes::Transition qw(
    profile_defines_labels
    profile_mode_matches
);
use AppArmor::ManagedModes::TrustedPath qw(
    bounded_capture
    file_size
);

our @EXPORT_OK = qw(
    verify_loaded_profile_modes
    verify_source_profile_modes
);

sub verify_source_profile_modes {
    my ($entries, $options, $workspace, $tools) = @_;
    my $profile_dir = $options->{profile_dir};

    for my $entry (@$entries) {
        if (_entry_is_optional($entry) &&
            !profile_defines_labels($entry, $options, $workspace, $tools)) {
            info(
                'optional AppArmor profile source defines no labels; '
                . "skipping source-mode verification: $entry->{name}"
            );
            next;
        }
        profile_mode_matches(
            $entry->{mode},
            $entry->{name},
            $entry->{path},
            $profile_dir,
        ) || fatal(
            'AppArmor profile source mode mismatch: '
            . "$entry->{name} expected=$entry->{mode}"
        );
    }
}

sub verify_loaded_profile_modes {
    my ($entries, $options, $workspace, $tools) = @_;
    my $limits = limits();
    my $parser_path = "$options->{tool_dir}/apparmor_parser";
    $tools->require_executable('required AppArmor parser', $parser_path);

    my ($loaded_fh, $loaded_snapshot_path) =
        $workspace->tempfile(
            'apparmor-loaded-profiles',
            'cannot create loaded profile snapshot',
        );
    close $loaded_fh || fatal('cannot create loaded profile snapshot');
    my ($names_fh, $profile_names_path) =
        $workspace->tempfile(
            'apparmor-profile-names',
            'cannot create profile name snapshot',
        );
    close $names_fh || fatal('cannot create profile name snapshot');

    bounded_capture(
        'loaded AppArmor profile state',
        $options->{loaded_profiles_path},
        $loaded_snapshot_path,
        $limits->{max_loaded_profiles_bytes},
    );
    my $loaded_state = read_snapshot($loaded_snapshot_path);

    for my $entry (@$entries) {
        my $parse_path = $entry->{path};
        my $base_dir = $options->{profile_dir};
        my $label_work_dir;

        if ($entry->{mode} eq 'disable') {
            $label_work_dir = $workspace->tempdir(
                'apparmor-profile-names',
                'cannot create isolated AppArmor label workspace',
            );
            $parse_path = "$label_work_dir/$entry->{name}";
            $base_dir = $label_work_dir;
            $workspace->copy_file(
                $entry->{path},
                $parse_path,
                "cannot stage AppArmor profile for label derivation: $entry->{name}",
            );
        }

        $workspace->truncate_file($profile_names_path);
        $tools->run_stdout_to_file_limited_or_exit(
            $profile_names_path,
            $limits->{max_profile_names_bytes},
            'AppArmor profile labels exceed '
                . "$limits->{max_profile_names_bytes} bytes: $entry->{name}",
            $parser_path,
            '-q',
            '-N',
            '-Q',
            '-K',
            '-T',
            '-I',
            $options->{profile_dir},
            '--base',
            $base_dir,
            $parse_path,
        );
        if (defined $label_work_dir) {
            $workspace->remove_dir($label_work_dir);
        }

        my $profile_names_size = file_size($profile_names_path);
        if ($profile_names_size == 0 && _entry_is_optional($entry)) {
            info(
                'optional AppArmor profile defines no labels; skipping '
                . "loaded-state verification: $entry->{name}"
            );
            next;
        }
        $profile_names_size > 0 ||
            fatal("AppArmor profile defines no labels: $entry->{name}");
        $profile_names_size <= $limits->{max_profile_names_bytes} ||
            fatal(
                'AppArmor profile labels exceed '
                . "$limits->{max_profile_names_bytes} bytes: $entry->{name}"
            );

        open my $labels_fh, '<:raw', $profile_names_path ||
            fatal("cannot derive AppArmor profile labels: $entry->{name}");
        while (my $profile_label = <$labels_fh>) {
            $profile_label =~ s/\n\z//;
            $profile_label ne '' ||
                fatal("AppArmor parser returned an empty label: $entry->{name}");
            length($profile_label) <= $limits->{max_line_bytes} ||
                fatal(
                    'AppArmor profile label exceeds '
                    . "$limits->{max_line_bytes} bytes: $entry->{name}"
                );

            if ($entry->{mode} eq 'disable') {
                !contains_label_prefix($loaded_state, $profile_label) ||
                    fatal("disabled AppArmor profile remains loaded: $profile_label");
            }
            elsif (index($profile_label, '//') >= 0) {
                contains_exact_line(
                    $loaded_state,
                    "$profile_label (enforce)",
                ) || contains_exact_line(
                    $loaded_state,
                    "$profile_label (complain)",
                ) || fatal(
                    'AppArmor child profile is not loaded in a confined mode: '
                    . $profile_label
                );
            }
            else {
                contains_exact_line(
                    $loaded_state,
                    "$profile_label ($entry->{mode})",
                ) || fatal(
                    "AppArmor profile is not loaded in $entry->{mode} mode: "
                    . $profile_label
                );
            }
        }
        close $labels_fh ||
            fatal("cannot derive AppArmor profile labels: $entry->{name}");
    }

    info('loaded profile modes verified');
}

sub _entry_is_optional {
    my ($entry) = @_;
    return defined($entry->{presence}) && $entry->{presence} eq 'optional';
}

1;
