package LabwcSecurityAction::AppArmor::RuleGenerator;

use strict;
use warnings;

use Cwd qw(abs_path);
use File::Basename qw(basename dirname);
use File::Copy qw(copy);
use File::Path qw(make_path remove_tree);
use File::Temp qw(tempdir tempfile);
use Fcntl qw(
  LOCK_EX LOCK_NB O_CREAT O_NOFOLLOW O_RDONLY O_RDWR
);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Bool Int Object Str);

use LabwcSecurityAction::AppArmor::AuditLog;
use LabwcSecurityAction::AppArmor::ProfileIndex;
use LabwcSecurityAction::AppArmor::RuleRenderer;
use LabwcSecurityAction::Command;

my $GENERATED_BEGIN = '# BEGIN managed generated AppArmor rules';
my $GENERATED_END   = '# END managed generated AppArmor rules';

has trusted_uid => (
    is      => 'ro',
    isa     => Int,
    default => sub { 0 },
);

has audit_log => (
    is      => 'ro',
    isa     => Object,
    default => sub {
        my ($self) = @_;
        return LabwcSecurityAction::AppArmor::AuditLog->new(
            trusted_uid => $self->trusted_uid(),
        );
    },
);

has backup_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/lib/apparmor/generated-rule-backups' },
);

has command => (
    is      => 'ro',
    isa     => Object,
    default => sub {
        return LabwcSecurityAction::Command->new(
            path => '/usr/sbin:/usr/bin:/sbin:/bin',
        );
    },
);

has event_log => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/var/log/managed/apparmor/apparmor.log' },
);

has maximum_include_bytes => (
    is      => 'ro',
    isa     => Int,
    default => sub { 1_048_576 },
);

has maximum_local_entries => (
    is      => 'ro',
    isa     => Int,
    default => sub { 1_024 },
);

has maximum_rules => (
    is      => 'ro',
    isa     => Int,
    default => sub { 2_048 },
);

has parser_config => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/apparmor/parser.conf' },
);

has profile_dir => (
    is      => 'ro',
    isa     => Str,
    default => sub { '/etc/apparmor.d' },
);

has profile_index => (
    is      => 'ro',
    isa     => Object,
    default => sub {
        my ($self) = @_;
        return LabwcSecurityAction::AppArmor::ProfileIndex->new(
            command     => $self->command(),
            parser_config => $self->parser_config(),
            profile_dir => $self->profile_dir(),
            trusted_uid => $self->trusted_uid(),
        );
    },
);

has reload_profiles => (
    is      => 'ro',
    isa     => Bool,
    default => sub { 1 },
);

has renderer => (
    is      => 'ro',
    isa     => Object,
    default => sub { LabwcSecurityAction::AppArmor::RuleRenderer->new() },
);

sub run {
    my ($self, $confirmation) = @_;

    defined($confirmation) &&
        $confirmation eq 'confirmed-apparmor-rule-generation'
        or die "AppArmor rule generation requires explicit confirmation\n";
    $self->_prepare_backup_dir();
    my $lock_fh = $self->_acquire_lock();
    my ($records, $parse_rejections) =
        $self->audit_log()->read_denials($self->event_log());
    my $index = $self->profile_index()->build();

    my (@unresolved, %groups, $candidate_count);
    push @unresolved, @{$parse_rejections};
    for my $record (@{$records}) {
        my $fields = $record->{fields};
        my $profile = $fields->{profile};
        if ($profile eq 'unconfined' || $profile =~ /\Aunconfined(?:\/|\z)/) {
            push @unresolved, $self->_unresolved(
                $record,
                'unconfined audit records cannot receive AppArmor policy rules',
            );
            next;
        }

        my $target = $self->profile_index()->resolve($index, $profile);
        if (!$target) {
            push @unresolved, $self->_unresolved(
                $record,
                'profile label cannot be mapped to an installed AppArmor source',
            );
            next;
        }
        if (!defined($target->{local_name}) ||
            $target->{local_name} !~ /\A[A-Za-z0-9][A-Za-z0-9._+@%:-]*\z/) {
            push @unresolved, $self->_unresolved(
                $record,
                'profile has no unambiguous local include for generated rules',
            );
            next;
        }

        my $rendered = $self->renderer()->render($record);
        if (!$rendered->{ok}) {
            push @unresolved, $self->_unresolved(
                $record,
                $rendered->{reason},
            );
            next;
        }

        my $group = $groups{$target->{local_path}} //= {
            local_name  => $target->{local_name},
            local_path  => $target->{local_path},
            rules       => {},
            source_name => $target->{source_name},
            source_path => $target->{source_path},
        };
        $group->{source_path} eq $target->{source_path}
            or die "generated AppArmor local include maps to multiple profile sources: "
                . $target->{local_path} . "\n";
        if (!$group->{rules}->{ $rendered->{rule} }) {
            ++$candidate_count;
            $candidate_count <= $self->maximum_rules()
                or die "AppArmor rule generation produced more than "
                    . $self->maximum_rules() . " candidate rules\n";
            $group->{rules}->{ $rendered->{rule} } = {
                count   => $record->{count},
                kind    => $rendered->{kind},
                profile => $profile,
            };
        }
        else {
            $group->{rules}->{ $rendered->{rule} }->{count} +=
                $record->{count};
        }
    }

    if (!keys(%groups)) {
        $self->_report_unresolved(\@unresolved);
        print "No safe AppArmor rules were generated.\n";
        return 2;
    }

    my $batch = tempdir(
        'generate.XXXXXX',
        DIR     => $self->backup_dir(),
        CLEANUP => 0,
    );
    chmod 0700, $batch
        or die "cannot protect AppArmor rule generation workspace: $!\n";
    my (@states, @changed_groups);
    my $status = eval {
        for my $local_path (sort keys %groups) {
            my $group = $groups{$local_path};
            my ($existing, $existed) = $self->_read_local_include($local_path);
            my ($candidate, $changed, $added) = $self->_merge_local_include(
                $existing,
                [sort keys %{ $group->{rules} }],
            );
            next if !$changed;

            my $candidate_dir = "$batch/candidates";
            make_path($candidate_dir, { mode => 0700 }) if !-d $candidate_dir;
            my $candidate_path = "$candidate_dir/$group->{local_name}";
            $self->_write_private_file($candidate_path, $candidate);
            $self->_validate_candidate($group, $candidate_path, $batch);

            my $backup_path;
            if ($existed) {
                my $backup_root = "$batch/previous";
                make_path($backup_root, { mode => 0700 }) if !-d $backup_root;
                $backup_path = "$backup_root/$group->{local_name}";
                copy($local_path, $backup_path)
                    or die "cannot back up AppArmor local policy: $local_path: $!\n";
                chmod 0600, $backup_path
                    or die "cannot protect AppArmor local policy backup: $!\n";
            }
            push @states, {
                backup_path   => $backup_path,
                candidate_path => $candidate_path,
                existed       => $existed,
                group         => $group,
                added         => $added,
                published     => 0,
            };
            push @changed_groups, $group;
        }

        for my $state (@states) {
            $self->_publish_atomic(
                $state->{candidate_path},
                $state->{group}->{local_path},
            );
            $state->{published} = 1;
        }
        if ($self->reload_profiles()) {
            my %reloaded;
            for my $group (@changed_groups) {
                next if $reloaded{ $group->{source_path} }++;
                $self->_reload_source($group);
            }
        }
        return 1;
    };
    my $error = $@;
    if (!$status) {
        my $rollback_error = $self->_rollback(\@states, \@changed_groups);
        remove_tree($batch, { safe => 1 });
        $error ||= "AppArmor rule generation failed\n";
        $error =~ s/\s+\z//;
        $error .= "; rollback warning: $rollback_error"
            if defined($rollback_error) && $rollback_error ne q{};
        die "$error\n";
    }

    remove_tree($batch, { safe => 1 });
    my $rule_total = 0;
    $rule_total += $_->{added} for @states;
    if ($rule_total) {
        printf "Applied %d unique AppArmor rule%s across %d local include%s.\n",
            $rule_total,
            $rule_total == 1 ? q{} : 's',
            scalar(@changed_groups),
            @changed_groups == 1 ? q{} : 's';
    }
    else {
        print "Every safe generated AppArmor rule was already present or subsumed.\n";
    }
    $self->_report_unresolved(\@unresolved);
    return 0;
}

sub _unresolved {
    my ($self, $record, $reason) = @_;

    return {
        count       => $record->{count} // 1,
        line_number => $record->{line_number},
        profile     => $record->{fields}->{profile} // 'unknown',
        reason      => $reason,
    };
}

sub _report_unresolved {
    my ($self, $unresolved) = @_;

    return if !@{$unresolved};
    printf "Skipped %d unresolved or unsafe AppArmor denial type%s:\n",
        scalar(@{$unresolved}),
        @{$unresolved} == 1 ? q{} : 's';
    my $shown = 0;
    for my $entry (@{$unresolved}) {
        last if $shown >= 100;
        my $profile = $entry->{profile} // 'unknown';
        $profile =~ s/[\r\n]/?/g;
        my $reason = $entry->{reason} // 'unspecified reason';
        $reason =~ s/[\r\n]+/ /g;
        printf "  line=%s count=%s profile=%s reason=%s\n",
            $entry->{line_number} // '?',
            $entry->{count} // 1,
            $profile,
            $reason;
        ++$shown;
    }
    print "  additional unresolved records were omitted from this display\n"
        if @{$unresolved} > $shown;
    return;
}

sub _prepare_backup_dir {
    my ($self) = @_;

    defined($self->backup_dir()) &&
        $self->backup_dir() =~ m{\A/} &&
        $self->backup_dir() ne '/' &&
        index($self->backup_dir(), '..') < 0 &&
        $self->backup_dir() !~ /[\r\n\0]/
        or die "AppArmor rule backup directory must be a safe absolute path\n";
    -e $self->backup_dir()
        or die "AppArmor rule backup directory was not provisioned: "
            . $self->backup_dir() . "\n";
    my @metadata = lstat($self->backup_dir());
    @metadata && ($metadata[2] & 0170000) == 0040000 &&
        !-l $self->backup_dir()
        or die "AppArmor rule backup directory must be a real directory\n";
    $metadata[4] == $self->trusted_uid()
        or die "AppArmor rule backup directory must be owned by the trusted account\n";
    ($metadata[2] & 0077) == 0
        or die "AppArmor rule backup directory must not be accessible by other users\n";
    chmod 0700, $self->backup_dir()
        or die "cannot protect AppArmor rule backup directory: $!\n";
    return;
}

sub _acquire_lock {
    my ($self) = @_;

    my $lock_path = $self->backup_dir() . '/.generator.lock';
    sysopen my $fh, $lock_path, O_RDWR | O_CREAT | O_NOFOLLOW, 0600
        or die "cannot open AppArmor rule generator lock: $!\n";
    chmod 0600, $lock_path
        or die "cannot protect AppArmor rule generator lock: $!\n";
    my @metadata = stat($fh);
    @metadata && ($metadata[2] & 0170000) == 0100000
        or die "AppArmor rule generator lock is not a regular file\n";
    $metadata[4] == $self->trusted_uid()
        or die "AppArmor rule generator lock must be owned by the trusted account\n";
    ($metadata[2] & 0077) == 0
        or die "AppArmor rule generator lock must not be accessible by other users\n";
    flock($fh, LOCK_EX | LOCK_NB)
        or die "another AppArmor rule generation transaction is already running\n";
    return $fh;
}

sub _read_local_include {
    my ($self, $path) = @_;

    my $local_root = $self->profile_dir() . '/local/';
    index($path, $local_root) == 0 &&
        substr($path, length($local_root)) =~ /\A[A-Za-z0-9][A-Za-z0-9._+@%:-]*\z/
        or die "generated AppArmor local include is outside the approved policy root: $path\n";
    return (q{}, 0) if !-e $path && !-l $path;

    my @metadata = lstat($path);
    @metadata && ($metadata[2] & 0170000) == 0100000 && !-l $path
        or die "AppArmor local include must be a regular non-symlink file: $path\n";
    $metadata[4] == $self->trusted_uid()
        or die "AppArmor local include must be owned by the trusted account: $path\n";
    ($metadata[2] & 0022) == 0
        or die "AppArmor local include must not be group- or world-writable: $path\n";
    $metadata[7] <= $self->maximum_include_bytes()
        or die "AppArmor local include exceeds " . $self->maximum_include_bytes()
            . " bytes: $path\n";

    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW
        or die "cannot read AppArmor local include: $path: $!\n";
    binmode $fh, ':raw'
        or die "cannot read AppArmor local include: $path: $!\n";
    local $/;
    my $content = <$fh>;
    close $fh
        or die "cannot close AppArmor local include: $path: $!\n";
    return (defined($content) ? $content : q{}, 1);
}

sub _merge_local_include {
    my ($self, $content, $rules) = @_;

    index($content, "\0") < 0
        or die "AppArmor local include contains a NUL byte\n";
    length($content) <= $self->maximum_include_bytes()
        or die "AppArmor local include exceeds " . $self->maximum_include_bytes()
            . " bytes\n";
    my @lines = split /(?<=\n)/, $content, -1;
    pop @lines if @lines && $lines[-1] eq q{};
    my (@begin, @end);
    for my $index (0 .. $#lines) {
        (my $line = $lines[$index]) =~ s/\n\z//;
        push @begin, $index if $line eq $GENERATED_BEGIN;
        push @end, $index if $line eq $GENERATED_END;
    }
    (@begin == @end && @begin <= 1)
        or die "AppArmor generated-rule marker block is malformed\n";
    if (@begin) {
        $begin[0] < $end[0]
            or die "AppArmor generated-rule marker block is malformed\n";
    }

    my @generated_rules;
    if (@begin) {
        for my $line (@lines[$begin[0] + 1 .. $end[0] - 1]) {
            $line =~ s/\n\z//;
            (my $normalized = $line) =~ s/\A\s+|\s+\z//g;
            next if $normalized eq q{} || $normalized =~ /\A#/;
            $normalized =~ /,\z/
                or die "AppArmor generated-rule block contains an invalid rule\n";
            push @generated_rules, $normalized;
        }
    }

    my %selected = map { $_ => 1 } @generated_rules;
    my @manual_lines = @lines;
    splice @manual_lines, $begin[0], $end[0] - $begin[0] + 1
        if @begin;
    my @all_existing = (@manual_lines, @generated_rules);
    my $added = 0;
    for my $rule (@{$rules}) {
        next if $self->_rule_is_subsumed($rule, \@all_existing);
        ++$added if !$selected{$rule};
        $selected{$rule} = 1;
        push @all_existing, $rule;
    }
    my @rendered_block_lines = (
        $GENERATED_BEGIN,
        '# Generated only from validated DENIED records; edit outside this block.',
        (map { "  $_" } sort keys %selected),
        $GENERATED_END,
    );
    my $rendered_block = join("\n", @rendered_block_lines) . "\n";

    my $rendered;
    if (@begin) {
        my $prefix = $begin[0] > 0
            ? join(q{}, @lines[0 .. $begin[0] - 1])
            : q{};
        my $suffix = $end[0] < $#lines
            ? join(q{}, @lines[$end[0] + 1 .. $#lines])
            : q{};
        $rendered = $prefix . $rendered_block . $suffix;
    }
    else {
        $rendered = $content;
        if (length($rendered)) {
            $rendered .= "\n" if $rendered !~ /\n\z/;
            $rendered .= "\n" if $rendered !~ /\n\n\z/;
        }
        $rendered .= $rendered_block;
    }
    length($rendered) <= $self->maximum_include_bytes()
        or die "generated AppArmor local include exceeds "
            . $self->maximum_include_bytes() . " bytes\n";
    return ($rendered, $rendered ne $content ? 1 : 0, $added);
}

sub _rule_is_subsumed {
    my ($self, $candidate, $existing_lines) = @_;

    (my $normalized_candidate = $candidate) =~ s/\A\s+|\s+\z//g;
    my $candidate_file = $self->_parse_file_rule($normalized_candidate);
    for my $line (@{$existing_lines}) {
        (my $normalized = $line) =~ s/\A\s+|\s+\z//g;
        next if $normalized eq q{} || $normalized =~ /\A#/;
        return 1 if $normalized eq $normalized_candidate;
        next if !$candidate_file;
        my $existing_file = $self->_parse_file_rule($normalized);
        next if !$existing_file;
        next if $existing_file->{owner} eq 'owner' &&
            $candidate_file->{owner} ne 'owner';
        next if $existing_file->{path} ne $candidate_file->{path};
        my %existing_permissions =
            map { $_ => 1 } split //, $existing_file->{permissions};
        $existing_permissions{w} and $existing_permissions{a} = 1;
        return 1
            if !grep { !$existing_permissions{$_} }
                split //, $candidate_file->{permissions};
    }
    return 0;
}

sub _parse_file_rule {
    my ($self, $rule) = @_;

    return if $rule !~ /\A(owner\s+)?(.+?)\s+([rawkam]+),\z/;
    return {
        owner       => defined($1) ? 'owner' : q{},
        path        => $2,
        permissions => $3,
    };
}

sub _write_private_file {
    my ($self, $path, $content) = @_;

    open my $fh, '>:raw', $path
        or die "cannot write AppArmor rule candidate: $path: $!\n";
    print {$fh} $content
        or die "cannot write AppArmor rule candidate: $path: $!\n";
    close $fh
        or die "cannot close AppArmor rule candidate: $path: $!\n";
    chmod 0600, $path
        or die "cannot protect AppArmor rule candidate: $path: $!\n";
    return;
}

sub _validate_candidate {
    my ($self, $group, $candidate_path, $batch) = @_;

    my $safe_source = $group->{source_name};
    $safe_source =~ /\A[A-Za-z0-9][A-Za-z0-9._+-]*\z/
        or die "invalid AppArmor source filename: $safe_source\n";
    my $overlay = tempdir(
        "validate-$safe_source.XXXXXX",
        DIR     => $batch,
        CLEANUP => 0,
    );
    my $overlay_local = "$overlay/local";
    mkdir $overlay_local, 0700
        or die "cannot create AppArmor validation local directory: $!\n";

    opendir my $profile_dh, $self->profile_dir()
        or die "cannot read AppArmor profile directory during validation: $!\n";
    my $profile_entries = 0;
    while (my $name = readdir $profile_dh) {
        next if $name eq q{.} || $name eq q{..} || $name eq 'local';
        ++$profile_entries;
        $profile_entries <= $self->maximum_local_entries()
            or die "AppArmor profile directory contains too many validation entries\n";
        next if $name !~ /\A[A-Za-z0-9][A-Za-z0-9._+@%:-]*\z/;
        my $source = $self->profile_dir() . "/$name";
        my $target = "$overlay/$name";
        if ($name eq $safe_source) {
            copy($group->{source_path}, $target)
                or die "cannot stage AppArmor source for validation: $!\n";
            chmod 0600, $target
                or die "cannot protect staged AppArmor source: $!\n";
        }
        else {
            symlink $source, $target
                or die "cannot link AppArmor validation dependency: $source: $!\n";
        }
    }
    closedir $profile_dh
        or die "cannot close AppArmor profile directory during validation: $!\n";

    my $actual_local = $self->profile_dir() . '/local';
    opendir my $local_dh, $actual_local
        or die "cannot read AppArmor local policy directory during validation: $!\n";
    my $local_entries = 0;
    while (my $name = readdir $local_dh) {
        next if $name eq q{.} || $name eq q{..};
        ++$local_entries;
        $local_entries <= $self->maximum_local_entries()
            or die "AppArmor local policy directory contains too many entries\n";
        next if $name eq $group->{local_name};
        next if $name !~ /\A[A-Za-z0-9][A-Za-z0-9._+@%:-]*\z/;
        symlink "$actual_local/$name", "$overlay_local/$name"
            or die "cannot link AppArmor local validation dependency: $name: $!\n";
    }
    closedir $local_dh
        or die "cannot close AppArmor local policy directory during validation: $!\n";
    copy($candidate_path, "$overlay_local/$group->{local_name}")
        or die "cannot stage generated AppArmor local policy for validation: $!\n";
    chmod 0600, "$overlay_local/$group->{local_name}"
        or die "cannot protect generated AppArmor validation policy: $!\n";

    my $parser = $self->command()->require_executable('apparmor_parser');
    my $status = $self->command()->run(
        $parser,
        '--config-file', $self->parser_config(),
        '-q', '-Q', '-K', '-T',
        '-I', $overlay,
        '--base', $overlay,
        "$overlay/$safe_source",
    );
    remove_tree($overlay, { safe => 1 });
    $status == 0
        or die "generated AppArmor rules failed parser validation for: $safe_source\n";
    return;
}

sub _publish_atomic {
    my ($self, $source, $target) = @_;

    my ($fh, $temporary) = tempfile(
        '.apparmor-generated.XXXXXX',
        DIR    => dirname($target),
        UNLINK => 0,
    );
    my $ok = eval {
        close $fh
            or die "cannot create AppArmor local policy transaction: $!\n";
        copy($source, $temporary)
            or die "cannot stage AppArmor local policy transaction: $!\n";
        chmod 0644, $temporary
            or die "cannot protect AppArmor local policy transaction: $!\n";
        rename $temporary, $target
            or die "cannot publish AppArmor local policy transaction: $!\n";
        return 1;
    };
    my $error = $@;
    unlink $temporary if !$ok && (-e $temporary || -l $temporary);
    die $error if !$ok;
    return;
}

sub _source_disabled {
    my ($self, $group) = @_;

    my $disable_link =
        $self->profile_dir() . "/disable/$group->{source_name}";
    return 0 if !-e $disable_link && !-l $disable_link;
    -l $disable_link
        or die "AppArmor disable entry is not a symlink: $disable_link\n";
    my $resolved = abs_path($disable_link);
    defined($resolved) && $resolved eq $group->{source_path}
        or die "AppArmor disable entry does not reference its profile source: $disable_link\n";
    return 1;
}

sub _reload_source {
    my ($self, $group) = @_;

    if ($self->_source_disabled($group)) {
        print "Updated disabled AppArmor source without loading it: "
            . $group->{source_name} . "\n";
        return;
    }
    my $parser = $self->command()->require_executable('apparmor_parser');
    my $status = $self->command()->run(
        $parser,
        '--config-file', $self->parser_config(),
        '-q', '-r',
        '-I', $self->profile_dir(),
        '--base', $self->profile_dir(),
        $group->{source_path},
    );
    $status == 0
        or die "cannot reload AppArmor source after generated rule update: "
            . $group->{source_name} . "\n";
    return;
}

sub _rollback {
    my ($self, $states, $changed_groups) = @_;

    my @errors;
    for my $state (reverse @{$states}) {
        next if !$state->{published};
        my $target = $state->{group}->{local_path};
        if ($state->{existed}) {
            eval { $self->_publish_atomic($state->{backup_path}, $target); 1 }
                or push @errors, "cannot restore $target";
        }
        elsif (-e $target || -l $target) {
            unlink $target
                or push @errors, "cannot remove newly generated $target";
        }
    }
    if ($self->reload_profiles()) {
        my %restored;
        for my $group (@{$changed_groups}) {
            next if $restored{ $group->{source_path} }++;
            eval { $self->_reload_source($group); 1 }
                or push @errors, "cannot reload restored $group->{source_name}";
        }
    }
    return join '; ', @errors;
}

1;
