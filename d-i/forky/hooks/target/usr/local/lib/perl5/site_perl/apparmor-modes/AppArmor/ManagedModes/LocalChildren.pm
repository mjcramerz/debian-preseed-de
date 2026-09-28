package AppArmor::ManagedModes::LocalChildren;

use strict;
use warnings;

use Exporter qw(import);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

use AppArmor::ManagedModes::CLI qw(fatal);
use AppArmor::ManagedModes::Config qw(limits);
use AppArmor::ManagedModes::TrustedPath qw(
    read_bounded_file validate_real_directory validate_root_owned_file
);

our @EXPORT_OK = qw(child_mode_matches apply_child_mode);

# Only these tracked local includes define a child profile. Other local files
# contain rules or abstractions and do not have an independent kernel mode.
my %CHILDREN = (
    'microsoft-edge-stable' => 'edge-glycin-bwrap',
    'mullvad-browser'       => 'mullvad-bwrap',
    'vivaldi-bin'           => 'vivaldi-bwrap',
);

sub _source {
    my ($name, $profile_dir) = @_;
    return if !exists $CHILDREN{$name};
    my $local_dir = "$profile_dir/local";
    validate_real_directory('managed AppArmor local include directory', $local_dir);
    my $path = "$local_dir/$name";
    validate_root_owned_file('managed AppArmor child include', $path,
                             limits()->{max_profile_bytes});
    return ($path, read_bounded_file('managed AppArmor child include', $path,
                                    limits()->{max_profile_bytes}));
}

sub _header {
    my ($name, $content) = @_;
    my $child = $CHILDREN{$name};
    my @headers = $content =~ /^([ \t]*profile[ \t]+[^\n]*\{[^\n]*)$/mg;
    @headers == 1 || fatal("expected one child profile in local include: $name");
    my $header = $headers[0];
    $header =~ /^([ \t]*profile[ \t]+\Q$child\E[ \t]+flags=\()([a-z_]+(?:[ \t]*,[ \t]*[a-z_]+)*)(\)[ \t]*\{(?:[ \t]*#.*)?)$/ ||
        fatal("unsupported child profile flags in local include: $name");
    my ($prefix, $flags, $suffix) = ($1, $2, $3);
    my @flags = split /[ \t]*,[ \t]*/, $flags;
    my %seen;
    !$seen{$_}++ || fatal("duplicate child profile flag in local include: $name")
        for @flags;
    return ($header, $prefix, \@flags, $suffix);
}

sub child_mode_matches {
    my ($mode, $name, $profile_dir) = @_;
    return 1 if !exists $CHILDREN{$name};
    my (undef, $content) = _source($name, $profile_dir);
    my (undef, undef, $flags) = _header($name, $content);
    my %flag = map { $_ => 1 } @$flags;
    return 0 if $flag{audit} || $flag{unconfined} || $flag{default_allow};
    return $mode eq 'complain' ? !!$flag{complain} : !$flag{complain};
}

sub apply_child_mode {
    my ($mode, $name, $profile_dir, $workspace) = @_;
    return if !exists $CHILDREN{$name};
    my ($path, $content) = _source($name, $profile_dir);
    my ($header, $prefix, $flags, $suffix) = _header($name, $content);
    my @flags = grep { $_ ne 'complain' && $_ ne 'audit' &&
                       $_ ne 'unconfined' && $_ ne 'default_allow' } @$flags;
    push @flags, 'complain' if $mode eq 'complain';
    my $replacement = $prefix . join(', ', @flags) . $suffix;
    my $count = ($content =~ s/^\Q$header\E$/$replacement/mg);
    $count == 1 || fatal("ambiguous child profile in local include: $name");
    my ($fh, $staged) = $workspace->tempfile(
        'apparmor-local-child', "cannot stage AppArmor child include: $name");
    print {$fh} $content || fatal("cannot write AppArmor child include: $name");
    close $fh || fatal("cannot close AppArmor child include: $name");
    $workspace->publish_file($staged, $path,
                             "cannot publish AppArmor child include: $name");
    $workspace->remove_file($staged);
}

1;
