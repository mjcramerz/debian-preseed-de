package AppArmor::ManagedModes::LoadedState;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

use AppArmor::ManagedModes::CLI qw(fatal);
use AppArmor::ManagedModes::Config qw(limits);
use AppArmor::ManagedModes::TrustedPath qw(bounded_capture file_size);

our @EXPORT_OK = qw(
    contains_exact_line
    contains_label_prefix
    read_snapshot
    capture_loaded_state
    profile_labels
    loaded_profile_mode_matches
);

sub read_snapshot {
    my ($path) = @_;

    open my $fh, '<:raw', $path or
        fatal("cannot read loaded AppArmor profile state: $path");
    local $/;
    my $content = <$fh>;
    close $fh ||
        fatal("cannot read loaded AppArmor profile state: $path");
    return defined($content) ? $content : '';
}

sub contains_label_prefix {
    my ($snapshot, $label) = @_;

    return index($snapshot, "$label (") == 0 ||
        index($snapshot, "\n$label (") >= 0;
}

sub contains_exact_line {
    my ($snapshot, $line) = @_;

    for my $candidate (split(/\n/, $snapshot, -1)) {
        return 1 if $candidate eq $line;
    }
    return 0;
}

# One bounded kernel snapshot per verification pass, not one per profile.
sub capture_loaded_state {
    my ($options, $workspace) = @_;
    my ($fh, $path) = $workspace->tempfile(
        'apparmor-loaded-profiles', 'cannot create loaded profile snapshot',
    );
    close $fh || fatal('cannot create loaded profile snapshot');
    bounded_capture(
        'loaded AppArmor profile state', $options->{loaded_profiles_path},
        $path, limits()->{max_loaded_profiles_bytes},
    );
    my $snapshot = read_snapshot($path);
    $workspace->remove_file($path);
    return $snapshot;
}

# Labels are cached only in this invocation's validated configuration entries.
# Never persist them across boots or assume a filename is a kernel label.
sub profile_labels {
    my ($entry, $options, $workspace, $tools) = @_;
    return $entry->{labels} if exists $entry->{labels};
    my $limits = limits();
    my $parser = "$options->{tool_dir}/apparmor_parser";
    $tools->require_executable('required AppArmor parser', $parser);
    my ($fh, $path) = $workspace->tempfile(
        'apparmor-profile-names', 'cannot create profile name snapshot',
    );
    close $fh || fatal('cannot create profile name snapshot');
    my $parse_path = $entry->{path};
    my $base_dir = $options->{profile_dir};
    my $label_work_dir;
    my $disable_entry = "$options->{profile_dir}/disable/$entry->{name}";
    if ($entry->{mode} eq 'disable' || -e $disable_entry || -l $disable_entry) {
        # The parser suppresses names for disabled files even with -N. Inspect
        # an isolated copy also when re-enabling or checking such a source;
        # otherwise a real optional profile could be cached as label-less.
        $label_work_dir = $workspace->tempdir(
            'apparmor-profile-names', 'cannot create isolated AppArmor label workspace',
        );
        $parse_path = "$label_work_dir/$entry->{name}";
        $base_dir = $label_work_dir;
        $workspace->copy_file(
            $entry->{path}, $parse_path,
            "cannot stage AppArmor profile for label derivation: $entry->{name}",
        );
    }
    $tools->run_stdout_to_file_limited_or_exit(
        $path, $limits->{max_profile_names_bytes},
        "AppArmor profile labels exceed $limits->{max_profile_names_bytes} bytes: $entry->{name}",
        $parser, '-q', '-N', '-Q', '-K', '-T', '-I', $options->{profile_dir},
        '--base', $base_dir, $parse_path,
    );
    $workspace->remove_dir($label_work_dir) if defined $label_work_dir;
    my $size = file_size($path);
    $size <= $limits->{max_profile_names_bytes} ||
        fatal("AppArmor profile labels exceed $limits->{max_profile_names_bytes} bytes: $entry->{name}");
    $size > 0 || ($entry->{presence} // '') eq 'optional' ||
        fatal("AppArmor profile defines no labels: $entry->{name}");
    open my $labels_fh, '<:raw', $path or
        fatal("cannot derive AppArmor profile labels: $entry->{name}");
    my @labels;
    while (my $label = <$labels_fh>) {
        $label =~ s/\n\z//;
        $label ne '' || fatal("AppArmor parser returned an empty label: $entry->{name}");
        length($label) <= $limits->{max_line_bytes} ||
            fatal("AppArmor profile label exceeds $limits->{max_line_bytes} bytes: $entry->{name}");
        push @labels, $label;
    }
    close $labels_fh || fatal("cannot derive AppArmor profile labels: $entry->{name}");
    $workspace->remove_file($path);
    $entry->{labels} = \@labels;
    return $entry->{labels};
}

sub loaded_profile_mode_matches {
    my ($entry, $snapshot, $options, $workspace, $tools) = @_;
    my $labels = profile_labels($entry, $options, $workspace, $tools);
    for my $label (@$labels) {
        if ($entry->{mode} eq 'disable') {
            return 0 if contains_label_prefix($snapshot, $label);
        }
        elsif (index($label, '//') >= 0) {
            # Preserve the existing policy: child profiles may independently
            # enforce or complain, but must never be unconfined or absent.
            return 0 unless contains_exact_line($snapshot, "$label (enforce)") ||
                contains_exact_line($snapshot, "$label (complain)");
        }
        else {
            return 0 unless contains_exact_line($snapshot, "$label ($entry->{mode})");
        }
    }
    return 1;
}

1;
