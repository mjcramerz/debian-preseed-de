package ExternalSoftware::Servicing::CLI;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use ExternalSoftware::Servicing::Bitwarden;
use ExternalSoftware::Servicing::ChatGPT;
use ExternalSoftware::Servicing::Deb;
use ExternalSoftware::Servicing::Discord;
use ExternalSoftware::Servicing::Event;
use ExternalSoftware::Servicing::HTTP;
use ExternalSoftware::Servicing::Ledger;
use ExternalSoftware::Servicing::Logger qw(log_msg);
use ExternalSoftware::Servicing::Notifier;
use ExternalSoftware::Servicing::Obsidian;
use ExternalSoftware::Servicing::Postman;
use ExternalSoftware::Servicing::Process;
use ExternalSoftware::Servicing::Repository;
use ExternalSoftware::Servicing::Sleek;
use ExternalSoftware::Servicing::State;
use ExternalSoftware::Servicing::Tuta;

sub _log {
    my ($self, $level, $message) = @_;
    print STDERR "[managed-external-software-update] $level: $message\n";
    log_msg($level, $message);
}

sub _clear_apply_failure_detail {
    my ($self) = @_;
    delete $self->{apply_failure_detail};
    return 1;
}

sub _record_apply_failure_detail {
    my ($self, $stage, $detail) = @_;
    defined $stage && $stage =~ /\A[a-z][a-z0-9-]{0,31}\z/
        or die "managed package failure stage is invalid\n";
    $detail = 'unknown failure' if !defined $detail || $detail eq q{};
    $detail =~ s/[\r\n\t]+/ /g;
    $detail =~ s/[\x00-\x1f\x7f]/?/g;
    $detail =~ s/\s+/ /g;
    $detail =~ s/\A\s+|\s+\z//g;
    $detail = substr($detail, 0, 1024);
    $self->{apply_failure_detail} = "$stage: $detail";
    $self->_log('warning', $self->{apply_failure_detail});
    return 1;
}

sub apply_failure_detail {
    my ($self) = @_;
    return $self->{apply_failure_detail};
}

sub _version_compare {
    my ($self, $left, $operator, $right) = @_;
    my $result = system('/usr/bin/dpkg', '--compare-versions', $left, $operator, $right);
    return 1 if $result == 0;
    return 0 if $result == 256;
    die "managed package version comparison failed\n";
}

sub _application_update_blocker {
    my ($self, $app) = @_;
    my @executables = (
        $app->{executable},
        @{$app->{in_use_executables} // []},
    );
    my $running = eval {
        ExternalSoftware::Servicing::Process->application_running(
            executables => \@executables,
            roots       => $app->{in_use_roots} // [],
        );
    };
    if ($@) {
        $self->_record_apply_failure_detail('process-check', $@);
        return 'validation';
    }
    if ($running) {
        $self->_record_apply_failure_detail(
            'in-use',
            "$app->{label} is running; its retained update was not installed",
        );
        return 'in-use';
    }
    return undef;
}

sub _payload_is_present {
    my ($self, $deb, $app, $chatgpt) = @_;
    return 0 if !$deb->installed_payload_valid($app);
    return ExternalSoftware::Servicing::Bitwarden->new()->policy_valid()
        if $app->{name} eq 'bitwarden';
    return 1 if $app->{name} ne 'chatgpt';
    return 0 if !$deb->installed_dependencies_allowed(
        $app->{packages}[0],
        $app->{remove_dependencies},
    );
    return $chatgpt->policy_valid();
}

sub _generic_deb_specs {
    my ($self, $chatgpt) = @_;
    my @specs = (
        {
            name       => 'bitwarden',
            label      => 'Bitwarden Desktop',
            url        => 'https://bitwarden.com/download/?app=desktop&platform=linux&variant=deb',
            maximum    => 314_572_800,
            hosts      => [qw(bitwarden.com github.com objects.githubusercontent.com release-assets.githubusercontent.com)],
            packages   => ['bitwarden'],
            executable => '/opt/Bitwarden/bitwarden',
            in_use_roots => ['/opt/Bitwarden'],
            desktop    => '/usr/share/applications/bitwarden.desktop',
            library    => '/opt/Bitwarden/libffmpeg.so',
            sandbox    => '/opt/Bitwarden/chrome-sandbox',
            sandbox_presence => 'required',
            required_paths => ['/opt/Bitwarden/resources/app.asar'],
            required_executables => ['/opt/Bitwarden/desktop_proxy'],
        },
        {
            name       => 'zoom',
            label      => 'Zoom Workplace',
            url        => 'https://zoom.us/client/latest/zoom_amd64.deb',
            maximum    => 536_870_912,
            hosts      => [qw(zoom.us cdn.zoom.us)],
            packages   => ['zoom'],
            executable => '/usr/bin/zoom',
            in_use_roots => ['/opt/zoom'],
            desktop    => '/usr/share/applications/Zoom.desktop',
            library    => q{},
        },
        {
            name       => 'filen',
            label      => 'Filen Desktop',
            url        => 'https://cdn.filen.io/@filen/desktop/release/latest/Filen_linux_amd64.deb',
            maximum    => 536_870_912,
            hosts      => [qw(cdn.filen.io filen.io)],
            packages   => [qw(filen filen-desktop)],
            executable => '/opt/Filen/Filen',
            in_use_roots => ['/opt/Filen'],
            desktop    => '/usr/share/applications/Filen.desktop',
            library    => '/opt/Filen/libffmpeg.so',
            sandbox    => '/opt/Filen/chrome-sandbox',
            sandbox_presence => 'optional',
        },
    );
    push @specs, $chatgpt->spec() if $chatgpt->enabled();
    return @specs;
}

sub _release_deb_specs {
    return (
        {
            name       => 'obsidian',
            label      => 'Obsidian',
            packages   => ['obsidian'],
            executable => '/opt/Obsidian/obsidian',
            in_use_roots => ['/opt/Obsidian'],
            desktop    => '/usr/share/applications/obsidian.desktop',
            library    => '/opt/Obsidian/libffmpeg.so',
        },
        {
            name       => 'sleek',
            label      => 'Sleek',
            packages   => ['sleek'],
            executable => '/opt/sleek/sleek',
            in_use_roots => ['/opt/sleek'],
            desktop    => '/usr/share/applications/sleek.desktop',
            library    => '/opt/sleek/libffmpeg.so',
        },
    );
}

sub _pinned_deb_specs {
    return (
        {
            name       => 'qoredb',
            label      => 'QoreDB',
            packages   => ['qore-db'],
            executable => '/usr/bin/qoredb',
            desktop    => '/usr/share/applications/QoreDB.desktop',
            library    => q{},
        },
    );
}

sub _all_deb_specs {
    my ($self, $chatgpt) = @_;
    return (
        $self->_generic_deb_specs($chatgpt),
        $self->_release_deb_specs(),
        $self->_pinned_deb_specs(),
    );
}

sub _stage_deb {
    my ($self, $deb, $event, $repository, $app, $path, $metadata) = @_;
    ref $metadata eq 'HASH'
        && defined $metadata->{package} && defined $metadata->{version}
        or die "$app->{label} artifact metadata is invalid\n";
    my $installed = $deb->installed_version($metadata->{package});
    if (defined $installed) {
        return (2, 'current')
            if $self->_version_compare($metadata->{version}, 'lt', $installed);
    }
    my ($retained_path, $created);
    my $retained = eval {
        ($retained_path, $created) = $repository->retain($path, $metadata);
        defined $retained_path && defined $created
            or die "managed repository retention returned no result\n";
        1;
    };
    if (!$retained) {
        my $detail = $@ || 'managed repository retention returned no result';
        $self->_record_apply_failure_detail('repository', $detail);
        return (1, 'validation');
    }
    if ($created) {
        $event->emit('downloaded', $app->{name}, $installed // 'missing', $metadata->{version});
        return (0, 'downloaded');
    }
    return (2, 'current');
}

sub _fetch_generic_deb {
    my ($self, $http, $deb, $event, $repository, $work, $app) = @_;
    my $path = "$work/$app->{name}.deb";
    $self->_clear_apply_failure_detail();
    my $stage = 'download';
    my $metadata = eval {
        $http->download(
            label          => $app->{label},
            url            => $app->{url},
            destination    => $path,
            minimum        => 1_048_576,
            maximum        => $app->{maximum},
            allowed_hosts  => $app->{hosts},
            content_policy => 'artifact',
        );
        $stage = 'source-metadata';
        my $metadata = $deb->validate_spec($path, $app, $app->{label});
        if ($app->{name} eq 'bitwarden') {
            $stage = 'bitwarden-repack';
            $path = ExternalSoftware::Servicing::Bitwarden->new()->repack(
                $path,
                $work,
            );
            my $repacked = $deb->validate_spec($path, $app, $app->{label});
            for my $field (qw(package version architecture)) {
                $repacked->{$field} eq $metadata->{$field}
                    or die "Bitwarden repack changed Debian package identity\n";
            }
            $metadata = $repacked;
        }
        if (exists $app->{remove_dependencies}) {
            my %repack = (
                label        => $app->{label},
                path         => $path,
                work         => $work,
                name         => $app->{name},
                dependencies => $app->{remove_dependencies},
            );
            $stage = 'control-rewrite';
            $path = $deb->repack_without_dependencies(%repack);
        }
        $metadata;
    };
    if (!$metadata) {
        my $detail = $@ || 'package download returned no metadata';
        $self->_record_apply_failure_detail($stage, $detail);
        return (1, $detail =~ /download|HTTP|URL/i ? 'download' : 'validation');
    }
    return $self->_stage_deb($deb, $event, $repository, $app, $path, $metadata);
}

sub _fetch_release_deb {
    my ($self, $module, $deb, $event, $repository, $work, $app) = @_;
    my $release = eval { $module->download($work) };
    return (1, $@ =~ /download|HTTP|URL/i ? 'download' : 'validation') if !$release;
    ref $release eq 'HASH' && defined $release->{path} && ref $release->{metadata} eq 'HASH'
        or return (1, 'validation');
    return $self->_stage_deb(
        $deb,
        $event,
        $repository,
        $app,
        $release->{path},
        $release->{metadata},
    );
}

sub _apply_deb {
    my ($self, $deb, $event, $repository, $app, $chatgpt, $execution_context) = @_;
    $execution_context //= 'runtime';
    $self->_clear_apply_failure_detail();
    my $candidate = eval { $repository->latest($deb, $app) };
    if ($@) {
        $self->_record_apply_failure_detail('candidate', $@);
        return (1, 'validation');
    }
    return (2, 'current') if !defined $candidate;

    my $metadata = $candidate->{metadata};
    my $installed = $deb->installed_version($metadata->{package});
    my $reinstall = 0;
    if (defined $installed) {
        my $candidate_is_older = $self->_version_compare(
            $metadata->{version},
            'lt',
            $installed,
        );
        my $candidate_is_equal = $self->_version_compare(
            $metadata->{version},
            'eq',
            $installed,
        );
        if (($candidate_is_older || $candidate_is_equal)
            && $app->{name} eq 'chatgpt'
            && $deb->installed_payload_valid($app)
            && $deb->installed_dependencies_allowed(
                $app->{packages}[0],
                $app->{remove_dependencies},
            )) {
            my $blocked = $self->_application_update_blocker($app);
            return (1, $blocked) if defined $blocked;
            my $finalized = eval {
                $chatgpt->finalize_install($execution_context);
                1;
            };
            if (!$finalized) {
                my $detail = $@ || 'policy finalization returned no result';
                my $cleanup = eval {
                    $chatgpt->abort_install();
                    1;
                };
                if (!$cleanup) {
                    my $cleanup_error = $@ || 'guard cleanup returned no result';
                    $detail .= " cleanup failure: $cleanup_error";
                }
                $self->_record_apply_failure_detail(
                    'finalize',
                    $detail,
                );
                return (1, 'policy');
            }
            return (2, 'current');
        }
        if ($candidate_is_older) {
            return (2, 'current') if $self->_payload_is_present(
                $deb,
                $app,
                $chatgpt,
            );
            return (1, 'payload');
        }
        if ($candidate_is_equal) {
            if ($self->_payload_is_present($deb, $app, $chatgpt)) {
                return (2, 'current');
            }
            $reinstall = 1;
        }
    }
    my $blocked = $self->_application_update_blocker($app);
    return (1, $blocked) if defined $blocked;
    $event->emit('applying', $app->{name}, $installed // 'missing', $metadata->{version});
    my $stage = $app->{name} eq 'chatgpt' ? 'prepare' : 'apt';
    my $applied = eval {
        $chatgpt->prepare_install() if $app->{name} eq 'chatgpt';
        $stage = 'apt';
        $deb->install($candidate->{path}, $reinstall);
        $stage = 'sandbox';
        $deb->repair_chromium_sandbox($app->{sandbox}, $app->{sandbox_presence})
            if defined $app->{sandbox} && $app->{sandbox} ne q{};
        $stage = 'finalize';
        $chatgpt->finalize_install($execution_context) if $app->{name} eq 'chatgpt';
        1;
    };
    if (!$applied) {
        my $detail = $@ || 'package transaction returned no result';
        if ($app->{name} eq 'chatgpt') {
            my $cleanup = eval {
                $chatgpt->abort_install();
                1;
            };
            if (!$cleanup) {
                my $cleanup_error = $@ || 'guard cleanup returned no result';
                $detail .= " cleanup failure: $cleanup_error";
            }
        }
        $self->_record_apply_failure_detail($stage, $detail);
        return (1, ($stage eq 'prepare' || $stage eq 'finalize') ? 'policy' : 'install');
    }
    my $verified = $deb->installed_version($metadata->{package});
    if (!defined $verified
        || $verified ne $metadata->{version}
        || !$self->_payload_is_present($deb, $app, $chatgpt)) {
        $self->_record_apply_failure_detail(
            'verify',
            'installed package version, payload, or managed policy verification failed',
        );
        return (1, 'postinstall');
    }
    $event->emit('updated', $app->{name}, $installed // 'missing', $metadata->{version});
    return (0, 'updated');
}

sub _record_result {
    my ($self, $event, $application, $result, $reason, $success_ref, $failed_ref) = @_;
    if ($result == 0) {
        $$success_ref++;
        return;
    }
    return if $result == 2;
    $$failed_ref++;
    $event->emit('failed', $application, $reason, '-');
    $self->_log('warning', "$application $reason");
}

sub _run_download {
    my ($self, $state, $event, $work) = @_;
    my $http = ExternalSoftware::Servicing::HTTP->new();
    my $repository = ExternalSoftware::Servicing::Repository->new(directory => $state->deb_dir());
    my $deb = ExternalSoftware::Servicing::Deb->new(repository => $repository);
    my $chatgpt = ExternalSoftware::Servicing::ChatGPT->new(state => $state);
    my ($ready, $failed) = (0, 0);
    $event->emit('checking', 'all', '-', '-');

    for my $app ($self->_generic_deb_specs($chatgpt)) {
        my ($result, $reason) = $self->_fetch_generic_deb($http, $deb, $event, $repository, $work, $app);
        $self->_record_result($event, $app->{name}, $result, $reason, \$ready, \$failed);
    }
    my @release_specs = $self->_release_deb_specs();
    my @release_modules = (
        ExternalSoftware::Servicing::Obsidian->new(http => $http, deb => $deb),
        ExternalSoftware::Servicing::Sleek->new(http => $http, deb => $deb),
    );
    for my $index (0 .. $#release_specs) {
        my $app = $release_specs[$index];
        my ($result, $reason) = $self->_fetch_release_deb(
            $release_modules[$index],
            $deb,
            $event,
            $repository,
            $work,
            $app,
        );
        $self->_record_result($event, $app->{name}, $result, $reason, \$ready, \$failed);
    }
    for my $handler (
        [ discord => ExternalSoftware::Servicing::Discord->new(http => $http, event => $event, state => $state) ],
        [ postman => ExternalSoftware::Servicing::Postman->new(http => $http, event => $event, state => $state) ],
        [ tuta    => ExternalSoftware::Servicing::Tuta->new(http => $http, event => $event, state => $state) ],
        [ ledger  => ExternalSoftware::Servicing::Ledger->new(http => $http, event => $event, state => $state) ],
    ) {
        my ($result, $reason) = eval { $handler->[1]->fetch($work) };
        ($result, $reason) = (1, 'validation') if $@ || !defined $result;
        $self->_record_result($event, $handler->[0], $result, $reason, \$ready, \$failed);
    }
    if (!$ready && !$failed) {
        $event->emit('no-updates', 'all', '-', '-');
    } else {
        $event->emit('download-complete', 'all', $ready, $failed);
    }
    return $failed ? 1 : 0;
}

sub _run_apply {
    my ($self, $state, $event, $work) = @_;
    my $repository = ExternalSoftware::Servicing::Repository->new(directory => $state->deb_dir());
    my $deb = ExternalSoftware::Servicing::Deb->new(repository => $repository);
    my $chatgpt = ExternalSoftware::Servicing::ChatGPT->new(state => $state);
    my $http = ExternalSoftware::Servicing::HTTP->new();
    my ($updated, $failed) = (0, 0);
    for my $app ($self->_all_deb_specs($chatgpt)) {
        my ($result, $reason) = $self->_apply_deb(
            $deb,
            $event,
            $repository,
            $app,
            $chatgpt,
        );
        $self->_record_result($event, $app->{name}, $result, $reason, \$updated, \$failed);
    }
    for my $handler (
        [ discord => ExternalSoftware::Servicing::Discord->new(http => $http, event => $event, state => $state) ],
        [ postman => ExternalSoftware::Servicing::Postman->new(http => $http, event => $event, state => $state) ],
        [ tuta    => ExternalSoftware::Servicing::Tuta->new(http => $http, event => $event, state => $state) ],
        [ ledger  => ExternalSoftware::Servicing::Ledger->new(http => $http, event => $event, state => $state) ],
    ) {
        my ($result, $reason) = eval { $handler->[1]->apply($work) };
        ($result, $reason) = (1, 'validation') if $@ || !defined $result;
        $self->_record_result($event, $handler->[0], $result, $reason, \$updated, \$failed);
    }
    if (!$updated && !$failed) {
        $event->emit('no-updates', 'all', '-', '-');
    } else {
        $event->emit('apply-complete', 'all', $updated, $failed);
    }
    return $failed ? 1 : 0;
}

sub _run_repair {
    my ($self, $state, $event, $work) = @_;
    my $repository = ExternalSoftware::Servicing::Repository->new(directory => $state->deb_dir());
    my $deb = ExternalSoftware::Servicing::Deb->new(repository => $repository);
    my $chatgpt = ExternalSoftware::Servicing::ChatGPT->new(state => $state);
    my $failed = 0;
    for my $app ($self->_all_deb_specs($chatgpt)) {
        my $repaired = eval {
            if ($app->{name} eq 'chatgpt') {
                if (defined $deb->installed_version($app->{packages}->[0])
                    && $deb->installed_payload_valid($app)
                    && $deb->installed_dependencies_allowed(
                        $app->{packages}[0],
                        $app->{remove_dependencies},
                    )) {
                    my $blocked = $self->_application_update_blocker($app);
                    if (defined $blocked) {
                        0;
                    } else {
                        $chatgpt->finalize_install('runtime');
                        1;
                    }
                } else {
                    my ($result, $reason) = $self->_apply_deb(
                        $deb,
                        $event,
                        $repository,
                        $app,
                        $chatgpt,
                    );
                    $result == 0
                        || ($result == 2
                            && $self->_payload_is_present(
                                $deb,
                                $app,
                                $chatgpt,
                            ))
                        ? 1
                        : 0;
                }
            } elsif ($app->{name} eq 'bitwarden') {
                my ($result, $reason) = $self->_apply_deb(
                    $deb,
                    $event,
                    $repository,
                    $app,
                    $chatgpt,
                );
                $result == 0
                    || ($result == 2
                        && $self->_payload_is_present(
                            $deb,
                            $app,
                            $chatgpt,
                        ))
                    ? 1
                    : 0;
            } else {
                $repository->repair($deb, $app);
            }
        };
        if (!$repaired) {
            $failed = 1;
            $self->_log('warning', "$app->{name} offline repair failed");
        }
    }
    my $http = ExternalSoftware::Servicing::HTTP->new();
    my $discord = ExternalSoftware::Servicing::Discord->new(
        http  => $http,
        event => $event,
        state => $state,
    );
    my ($discord_result, $discord_reason) = eval { $discord->repair($work) };
    ($discord_result, $discord_reason) = (1, 'validation')
        if $@ || !defined $discord_result;
    if ($discord_result == 1) {
        $failed = 1;
        $event->emit('failed', 'discord', $discord_reason, '-');
        $self->_log('warning', "discord offline repair failed: $discord_reason");
    }
    $self->_log($failed ? 'warning' : 'info', $failed
        ? 'one or more managed applications could not be repaired offline'
        : 'managed application offline repair completed');
    return $failed ? 1 : 0;
}

sub _run_bootstrap_chatgpt {
    my ($self, $state, $event, $work) = @_;
    my $chatgpt = ExternalSoftware::Servicing::ChatGPT->new(state => $state);
    $chatgpt->enabled()
        or die "ChatGPT bootstrap requires addon/devops enable state\n";
    my $http = ExternalSoftware::Servicing::HTTP->new();
    my $repository = ExternalSoftware::Servicing::Repository->new(directory => $state->deb_dir());
    my $deb = ExternalSoftware::Servicing::Deb->new(repository => $repository);
    my $app = $chatgpt->spec();

    my ($download_result, $download_reason) = $self->_fetch_generic_deb(
        $http,
        $deb,
        $event,
        $repository,
        $work,
        $app,
    );
    if ($download_result == 1) {
        my $detail = $self->apply_failure_detail();
        my $suffix = defined $detail && $detail ne q{}
            ? " ($detail)"
            : q{};
        die "ChatGPT bootstrap download failed: $download_reason$suffix\n";
    }

    my ($apply_result, $apply_reason) = $self->_apply_deb(
        $deb,
        $event,
        $repository,
        $app,
        $chatgpt,
        'installer',
    );
    if ($apply_result == 1) {
        my $detail = $self->apply_failure_detail();
        my $suffix = defined $detail && $detail ne q{}
            ? " ($detail)"
            : q{};
        die "ChatGPT bootstrap installation failed: $apply_reason$suffix\n";
    }
    return 0;
}

sub run_updater {
    my ($self, @argv) = @_;
    @argv <= 1
        && (!@argv || $argv[0] =~ /\A--(?:download-only|apply-only|repair-only|bootstrap-discord|bootstrap-chatgpt)\z/)
        or die "usage: managed-external-software-update [--download-only|--apply-only|--repair-only|--bootstrap-discord|--bootstrap-chatgpt]\n";
    $> == 0
        or die "this updater must run as root\n";
    open my $arch_fh, '-|', '/usr/bin/dpkg', '--print-architecture'
        or die "dpkg is unavailable\n";
    my $architecture = <$arch_fh> // q{};
    close $arch_fh
        or die "dpkg architecture query failed\n";
    chomp $architecture;
    $architecture eq 'amd64'
        or die "managed external software updates are supported only on amd64\n";

    my $mode = $argv[0] // '--apply-only';
    my $state = ExternalSoftware::Servicing::State->new();
    $state->prepare();
    my $lock = $state->lock();
    if (!defined $lock) {
        $self->_log('info', 'another managed external software action is already running');
        return 0;
    }
    my $work = $state->work_dir();
    my $event = ExternalSoftware::Servicing::Event->new(directory => $state->event_dir());
    my $result = eval {
        if ($mode eq '--repair-only') {
            $self->_run_repair($state, $event, $work);
        } elsif ($mode eq '--bootstrap-chatgpt') {
            $self->_run_bootstrap_chatgpt($state, $event, $work);
        } elsif ($mode eq '--bootstrap-discord') {
            my $http = ExternalSoftware::Servicing::HTTP->new();
            my $discord = ExternalSoftware::Servicing::Discord->new(
                http  => $http,
                event => $event,
                state => $state,
            );
            my ($discord_result, $discord_reason) = $discord->bootstrap($work);
            if ($discord_result != 0) {
                my $detail = $discord->failure_detail();
                my $suffix = defined $detail && $detail ne q{}
                    ? " ($detail)"
                    : q{};
                die "Discord bootstrap failed: $discord_reason$suffix\n";
            }
            0;
        } else {
            $mode eq '--download-only'
                ? $self->_run_download($state, $event, $work)
                : $self->_run_apply($state, $event, $work);
        }
    };
    my $error = $@;
    $state->cleanup_work_dir($work);
    die $error if $error;
    return $result;
}

sub run_notifier {
    my ($self, @argv) = @_;
    @argv == 0
        or die "usage: managed-external-software-notify\n";
    return ExternalSoftware::Servicing::Notifier->new()->run();
}

1;
