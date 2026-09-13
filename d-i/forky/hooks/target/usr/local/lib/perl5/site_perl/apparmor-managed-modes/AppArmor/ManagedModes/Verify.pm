package AppArmor::ManagedModes::Verify;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

use AppArmor::ManagedModes::CLI qw(fatal info);
use AppArmor::ManagedModes::LoadedState qw(
    contains_exact_line
    contains_label_prefix
    capture_loaded_state
    profile_labels
);
use AppArmor::ManagedModes::Transition qw(
    profile_defines_labels
    profile_mode_matches
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
    my ($entries, $options, $workspace, $tools, $loaded_state) = @_;
    $loaded_state = capture_loaded_state($options, $workspace)
        if !defined $loaded_state;

    for my $entry (@$entries) {
        my $labels = profile_labels($entry, $options, $workspace, $tools);
        if (!@$labels && _entry_is_optional($entry)) {
            info('optional AppArmor profile defines no labels; skipping '
                . "loaded-state verification: $entry->{name}");
        }
        for my $profile_label (@$labels) {
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
    }

    info('loaded profile modes verified');
}

sub _entry_is_optional {
    my ($entry) = @_;
    return defined($entry->{presence}) && $entry->{presence} eq 'optional';
}

1;
