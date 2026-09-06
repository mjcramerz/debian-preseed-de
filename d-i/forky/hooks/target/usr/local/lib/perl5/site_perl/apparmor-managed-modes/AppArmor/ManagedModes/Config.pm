package AppArmor::ManagedModes::Config;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

use AppArmor::ManagedModes::CLI qw(fatal info warn);
use AppArmor::ManagedModes::TrustedPath qw(
    read_bounded_file
    validate_absolute_path
    validate_root_owned_file
);

our @EXPORT_OK = qw(limits load_config);

sub limits {
    return {
        max_config_bytes          => 65_536,
        max_profile_bytes         => 1_048_576,
        max_line_bytes            => 1_024,
        max_loaded_profiles_bytes => 8_388_608,
        max_profile_names_bytes   => 65_536,
        max_tool_diagnostic_bytes => 65_536,
    };
}

sub load_config {
    my ($options) = @_;
    my $limits = limits();

    validate_root_owned_file(
        'mode configuration',
        $options->{config_path},
        $limits->{max_config_bytes},
    );

    my $content = read_bounded_file(
        'mode configuration',
        $options->{config_path},
        $limits->{max_config_bytes},
    );
    my @lines = length($content) ? split(/\n/, $content, -1) : ();
    pop @lines if @lines && $content =~ /\n\z/;

    my @entries;
    my %seen_profiles;
    my $line_number = 0;

    for my $line (@lines) {
        ++$line_number;
        length($line) <= $limits->{max_line_bytes} ||
            fatal(
                "configuration line $line_number exceeds "
                . "$limits->{max_line_bytes} bytes"
            );
        next if $line eq '' || $line =~ /\A#/;

        $line =~ /\A[A-Za-z0-9._\/\@%:+,\-]+(?: +[A-Za-z0-9._\/\@%:+,\-]+){3}\z/ ||
            fatal(
                "configuration line $line_number contains unsupported "
                . 'characters or spacing'
            );

        my @fields = split(/ +/, $line, -1);
        @fields == 4 ||
            fatal(
                "configuration line $line_number must contain exactly four fields"
            );

        my ($mode, $presence, $profile_name, $executable_probe) = @fields;
        $mode =~ /\A(?:enforce|complain|disable)\z/ ||
            fatal(
                "configuration line $line_number has an invalid mode: $mode"
            );
        $presence =~ /\A(?:required|optional|if-executable)\z/ ||
            fatal(
                "configuration line $line_number has an invalid presence policy: "
                . $presence
            );
        $profile_name =~ /\A[A-Za-z0-9._+\-]+\z/ ||
            fatal(
                "configuration line $line_number has an invalid profile file: "
                . $profile_name
            );
        !$seen_profiles{$profile_name}++ ||
            fatal(
                "configuration line $line_number repeats profile file: "
                . $profile_name
            );

        if ($presence eq 'if-executable') {
            validate_absolute_path(
                'configuration executable probe',
                $executable_probe,
            );
        }
        else {
            $executable_probe eq '-' ||
                fatal(
                    "configuration line $line_number must use '-' "
                    . 'as its executable probe'
                );
        }

        if ($presence eq 'if-executable' && !-x $executable_probe) {
            info(
                "skipping profile $profile_name; executable is absent: "
                . $executable_probe
            );
            next;
        }

        my $profile_path = "$options->{profile_dir}/$profile_name";
        if (!-e $profile_path) {
            if ($presence eq 'required') {
                fatal("required AppArmor profile is missing: $profile_name");
            }
            if ($presence eq 'if-executable') {
                warn(
                    'installed executable has no package AppArmor profile; '
                    . "skipping mode management: $executable_probe -> "
                    . $profile_name
                );
            }
            else {
                info("skipping absent optional profile $profile_name");
            }
            next;
        }

        validate_root_owned_file(
            'AppArmor profile',
            $profile_path,
            $limits->{max_profile_bytes},
        );
        push @entries, {
            mode     => $mode,
            name     => $profile_name,
            path     => $profile_path,
            presence => $presence,
        };
    }

    return \@entries;
}

1;
