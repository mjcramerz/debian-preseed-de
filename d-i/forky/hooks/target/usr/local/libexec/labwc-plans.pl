#!/usr/bin/perl

use strict;
use warnings;

package LabwcPlans::Logger;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use POSIX qw(strftime);
use Types::Standard qw(Bool);

has debug_enabled => (
    is      => 'ro',
    isa     => Bool,
    default => sub { 0 },
);

sub log {
    my ($self, $level, $message) = @_;

    return if $level eq 'debug' && !$self->debug_enabled();
    $message //= q{};
    $message =~ s/[\r\n\t]+/ /g;
    $message =~ s/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/?/g;
    $message = substr($message, 0, 2_048) if length($message) > 2_048;
    my $timestamp = strftime('%Y-%m-%dT%H:%M:%SZ', gmtime());
    print STDERR "$timestamp labwc-plans level=$level message=$message\n";
    return;
}

1;

package LabwcPlans::Config;

use strict;
use warnings;

use File::Spec;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Bool Int Str);

has enabled => (
    is       => 'ro',
    isa      => Bool,
    required => 1,
);

has home => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has input_dir => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has state_dir => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has telegram_enabled => (
    is       => 'ro',
    isa      => Bool,
    required => 1,
);

has telegram_api_base => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has telegram_api_key => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has telegram_chat_id => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has ntfy_enabled => (
    is       => 'ro',
    isa      => Bool,
    required => 1,
);

has ntfy_base_url => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has ntfy_topic => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has ntfy_access_token => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has poll_seconds => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has http_timeout_seconds => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has retry_min_seconds => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has retry_max_seconds => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has initial_catchup_seconds => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_catchup_seconds => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has notify_existing => (
    is       => 'ro',
    isa      => Bool,
    required => 1,
);

has readd_grace_seconds => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has state_retention_days => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_input_files => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_input_file_bytes => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_entries => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_line_characters => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_queue_items => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_deliveries_per_cycle => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_notification_characters => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_state_bytes => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has max_consecutive_cycle_failures => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has debug_enabled => (
    is       => 'ro',
    isa      => Bool,
    required => 1,
);

sub from_environment {
    my ($class) = @_;

    my @account = getpwuid($<);
    @account or die "cannot resolve the current desktop account\n";
    my $home = $ENV{HOME} // $account[7] // q{};
    _validate_absolute_path('HOME', $home);

    my $xdg_state_home = $ENV{XDG_STATE_HOME};
    if (!defined($xdg_state_home) || $xdg_state_home eq q{}) {
        $xdg_state_home = File::Spec->catdir($home, '.local', 'state');
    }
    _validate_absolute_path('XDG state directory', $xdg_state_home);

    my $input_dir = _env_text(
        'LABWC_PLANS_INPUT_DIR',
        File::Spec->catdir($home, 'Syncthing', 'sleek'),
        4_096,
    );
    my $state_dir = _env_text(
        'LABWC_PLANS_STATE_DIR',
        File::Spec->catdir($xdg_state_home, 'labwc-plans'),
        4_096,
    );
    _validate_absolute_path('plan input directory', $input_dir);
    _validate_absolute_path('plan state directory', $state_dir);

    my $enabled = _env_bool('LABWC_PLANS_ENABLED', 1);
    my $telegram_enabled = _env_bool('LABWC_PLANS_TELEGRAM_ENABLED', 1);
    my $ntfy_enabled = _env_bool('LABWC_PLANS_NTFY_ENABLED', 1);
    if ($enabled && !$telegram_enabled && !$ntfy_enabled) {
        die "labwc-plans requires at least one enabled notification channel\n";
    }

    my $telegram_api_base = _validate_https_base_url(
        'Telegram API base URL',
        _env_text('LABWC_PLANS_TELEGRAM_API_BASE', 'https://api.telegram.org', 1_024),
    );
    my $telegram_api_key = _env_text('LABWC_PLANS_TELEGRAM_API_KEY', q{}, 256);
    my $telegram_chat_id = _env_text('LABWC_PLANS_TELEGRAM_CHAT_ID', q{}, 64);
    if ($enabled && $telegram_enabled) {
        $telegram_api_key =~ /\A[0-9]{5,16}:[A-Za-z0-9_-]{20,128}\z/
            or die "LABWC_PLANS_TELEGRAM_API_KEY has an invalid format\n";
        $telegram_chat_id =~ /\A-?[0-9]{1,20}\z/
            or die "LABWC_PLANS_TELEGRAM_CHAT_ID has an invalid format\n";
    }

    my $ntfy_base_url = _validate_https_base_url(
        'ntfy base URL',
        _env_text('LABWC_PLANS_NTFY_BASE_URL', 'https://ntfy.sh', 1_024),
    );
    my $ntfy_topic = _env_text('LABWC_PLANS_NTFY_TOPIC', 'labwc_plans_notify', 128);
    if ($enabled && $ntfy_enabled) {
        $ntfy_topic =~ /\A[A-Za-z0-9_-]{1,64}\z/
            or die "LABWC_PLANS_NTFY_TOPIC has an invalid format\n";
    }
    my $ntfy_access_token = _env_text('LABWC_PLANS_NTFY_ACCESS_TOKEN', q{}, 512);
    $ntfy_access_token !~ /[\x00-\x20\x7f]/
        or die "LABWC_PLANS_NTFY_ACCESS_TOKEN contains whitespace or control characters\n";

    my $retry_min = _env_int('LABWC_PLANS_RETRY_MIN_SECONDS', 30, 5, 3_600);
    my $retry_max = _env_int('LABWC_PLANS_RETRY_MAX_SECONDS', 1_800, $retry_min, 86_400);
    my $initial_catchup = _env_int(
        'LABWC_PLANS_INITIAL_CATCHUP_SECONDS',
        0,
        0,
        604_800,
    );
    my $max_catchup = _env_int(
        'LABWC_PLANS_MAX_CATCHUP_SECONDS',
        604_800,
        60,
        2_592_000,
    );
    $initial_catchup <= $max_catchup
        or die "LABWC_PLANS_INITIAL_CATCHUP_SECONDS exceeds LABWC_PLANS_MAX_CATCHUP_SECONDS\n";
    my $max_queue_items = _env_int(
        'LABWC_PLANS_MAX_QUEUE_ITEMS',
        500,
        100,
        100_000,
    );
    my $max_notification_characters = _env_int(
        'LABWC_PLANS_MAX_NOTIFICATION_CHARACTERS',
        3_500,
        256,
        4_000,
    );
    my $max_state_bytes = _env_int(
        'LABWC_PLANS_MAX_STATE_BYTES',
        16_777_216,
        65_536,
        67_108_864,
    );
    my $estimated_queue_bytes = $max_queue_items *
        (($max_notification_characters * 4) + 1_024);
    $estimated_queue_bytes <= int($max_state_bytes / 2)
        or die "LABWC_PLANS_MAX_QUEUE_ITEMS and LABWC_PLANS_MAX_NOTIFICATION_CHARACTERS exceed the state-file queue budget\n";

    return $class->new(
        enabled                        => $enabled,
        home                           => $home,
        input_dir                      => $input_dir,
        state_dir                      => $state_dir,
        telegram_enabled               => $telegram_enabled,
        telegram_api_base              => $telegram_api_base,
        telegram_api_key               => $telegram_api_key,
        telegram_chat_id               => $telegram_chat_id,
        ntfy_enabled                   => $ntfy_enabled,
        ntfy_base_url                  => $ntfy_base_url,
        ntfy_topic                     => $ntfy_topic,
        ntfy_access_token              => $ntfy_access_token,
        poll_seconds                   => _env_int('LABWC_PLANS_POLL_SECONDS', 30, 5, 3_600),
        http_timeout_seconds           => _env_int('LABWC_PLANS_HTTP_TIMEOUT_SECONDS', 15, 2, 120),
        retry_min_seconds              => $retry_min,
        retry_max_seconds              => $retry_max,
        initial_catchup_seconds        => $initial_catchup,
        max_catchup_seconds            => $max_catchup,
        notify_existing                => _env_bool('LABWC_PLANS_NOTIFY_EXISTING', 1),
        readd_grace_seconds            => _env_int('LABWC_PLANS_READD_GRACE_SECONDS', 300, 0, 86_400),
        state_retention_days           => _env_int('LABWC_PLANS_STATE_RETENTION_DAYS', 400, 30, 3_650),
        max_input_files                => _env_int('LABWC_PLANS_MAX_INPUT_FILES', 128, 1, 1_000),
        max_input_file_bytes           => _env_int('LABWC_PLANS_MAX_INPUT_FILE_BYTES', 1_048_576, 1_024, 10_485_760),
        max_entries                    => _env_int('LABWC_PLANS_MAX_ENTRIES', 10_000, 1, 100_000),
        max_line_characters            => _env_int('LABWC_PLANS_MAX_LINE_CHARACTERS', 8_192, 256, 32_768),
        max_queue_items                => $max_queue_items,
        max_deliveries_per_cycle       => _env_int('LABWC_PLANS_MAX_DELIVERIES_PER_CYCLE', 100, 1, 10_000),
        max_notification_characters    => $max_notification_characters,
        max_state_bytes                => $max_state_bytes,
        max_consecutive_cycle_failures => _env_int('LABWC_PLANS_MAX_CONSECUTIVE_FAILURES', 5, 1, 100),
        debug_enabled                  => _env_bool('LABWC_PLANS_DEBUG', 0),
    );
}

sub _env_text {
    my ($name, $default, $maximum) = @_;

    my $value = exists($ENV{$name}) ? $ENV{$name} : $default;
    defined($value) && !ref($value) or die "$name must be a scalar value\n";
    length($value) <= $maximum or die "$name exceeds $maximum characters\n";
    $value !~ /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/
        or die "$name contains control characters\n";
    return $value;
}

sub _env_bool {
    my ($name, $default) = @_;

    return $default if !exists($ENV{$name}) || !defined($ENV{$name}) || $ENV{$name} eq q{};
    my $value = lc $ENV{$name};
    return 1 if $value =~ /\A(?:1|true|yes|on)\z/;
    return 0 if $value =~ /\A(?:0|false|no|off)\z/;
    die "$name must be a boolean value\n";
}

sub _env_int {
    my ($name, $default, $minimum, $maximum) = @_;

    my $value = exists($ENV{$name}) && defined($ENV{$name}) && $ENV{$name} ne q{}
        ? $ENV{$name}
        : $default;
    $value =~ /\A[0-9]+\z/ or die "$name must be an integer\n";
    $value >= $minimum && $value <= $maximum
        or die "$name must be between $minimum and $maximum\n";
    return int($value);
}

sub _validate_absolute_path {
    my ($label, $value) = @_;

    defined($value) && !ref($value) && $value =~ m{\A/}
        or die "$label must be an absolute path\n";
    $value ne '/' or die "$label must not be the filesystem root\n";
    $value !~ m{(?:\A|/)\.\.(?:/|\z)}
        or die "$label contains a parent-directory component\n";
    $value !~ m{//}
        or die "$label contains an empty path component\n";
    $value !~ /[\x00-\x1f\x7f]/
        or die "$label contains control characters\n";
    length($value) <= 4_096 or die "$label is too long\n";
    return $value;
}

sub _validate_https_base_url {
    my ($label, $value) = @_;

    $value =~ s{/+\z}{};
    $value =~ m{\Ahttps://([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?(?:/[A-Za-z0-9._~%:/-]*)?\z}
        or die "$label must be a simple HTTPS URL without credentials, query, or fragment\n";
    my $host = lc $1;
    my $port = $2;
    $host =~ /\A(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\z/
        or die "$label contains an invalid host\n";
    if (defined($port)) {
        $port >= 1 && $port <= 65_535 or die "$label contains an invalid port\n";
    }
    return $value;
}

1;

package LabwcPlans::Entry;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(ArrayRef Bool Int Maybe Str);

has key => (
    is       => 'rw',
    isa      => Str,
    required => 1,
);

has fingerprint => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has file => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has line_number => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has priority => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has raw => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has display => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has source => (
    is       => 'ro',
    isa      => Maybe[Str],
    required => 1,
);

has created_date => (
    is       => 'ro',
    isa      => Maybe[Str],
    required => 1,
);

has start_date => (
    is       => 'ro',
    isa      => Maybe[Str],
    required => 1,
);

has due_date => (
    is       => 'ro',
    isa      => Maybe[Str],
    required => 1,
);

has recurrence => (
    is       => 'ro',
    isa      => Maybe[Str],
    required => 1,
);

has times => (
    is       => 'ro',
    isa      => ArrayRef[Int],
    required => 1,
);

has invalid_schedule => (
    is       => 'ro',
    isa      => Bool,
    required => 1,
);

1;

package LabwcPlans::Parser;

use strict;
use warnings;

use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

has logger => (
    is       => 'ro',
    required => 1,
);

sub parse_line {
    my ($self, $file, $line_number, $line) = @_;

    $line =~ s/\r\z//;
    $line =~ s/[ \t]+\z//;
    return if $line eq q{};
    return if $line =~ /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/;
    return if $line !~ /\A[ \t]*\(([A-Z])\)[ \t]+(.+)\z/;

    my ($priority, $body) = ($1, $2);
    return if $priority !~ /\A[ABC]\z/;

    my ($created_date) = $body =~ /\A(\d{4}-\d{2}-\d{2})(?:[ \t]+|\z)/;
    my ($start_date) = $body =~ /(?:\A|[ \t])t:(\d{4}-\d{2}-\d{2})(?=[ \t]|\z)/;
    my ($due_date) = $body =~ /(?:\A|[ \t])due:(\d{4}-\d{2}-\d{2})(?=[ \t]|\z)/;
    my ($source) = $body =~ /(?:\A|[ \t])source:([A-Za-z0-9._:-]{1,128})(?=[ \t]|\z)/;
    my ($recurrence_raw) = $body =~ /(?:\A|[ \t])rec:([^ \t]+)(?=[ \t]|\z)/;
    my $recurrence;
    my $invalid_schedule = 0;
    if (defined($recurrence_raw)) {
        $recurrence_raw = lc $recurrence_raw;
        if ($recurrence_raw =~ /\A[1-9][0-9]{0,3}[dbwmy]\z/) {
            $recurrence = $recurrence_raw;
        }
        else {
            $invalid_schedule = 1;
        }
    }

    my %time_seen;
    while ($body =~ /(?:\A|[ \t])\@([0-9]{4})(?=[ \t]|\z)/g) {
        my $time = int($1);
        my $hour = int($time / 100);
        my $minute = $time % 100;
        if ($hour > 23 || $minute > 59) {
            $invalid_schedule = 1;
            next;
        }
        $time_seen{$time} = 1;
    }
    my @times = sort { $a <=> $b } keys %time_seen;

    my $display = $body;
    $display =~ s/\A\d{4}-\d{2}-\d{2}(?:[ \t]+|\z)/ /;
    $display =~ s/(?:\A|[ \t])(?:due|t|rec|source|pm):[^ \t]+(?=[ \t]|\z)/ /g;
    $display =~ s/(?:\A|[ \t])\@[0-9]{4}(?=[ \t]|\z)/ /g;
    $display =~ s/[ \t]+/ /g;
    $display =~ s/\A //;
    $display =~ s/ \z//;
    $display = $body if $display eq q{};

    return LabwcPlans::Entry->new(
        key              => q{},
        fingerprint      => sha256_hex(encode('UTF-8', $line)),
        file             => $file,
        line_number      => $line_number,
        priority         => $priority,
        raw              => $line,
        display          => $display,
        source           => $source,
        created_date     => $created_date,
        start_date       => $start_date,
        due_date         => $due_date,
        recurrence       => $recurrence,
        times            => \@times,
        invalid_schedule => $invalid_schedule,
    );
}

1;

package LabwcPlans::Scanner;

use strict;
use warnings;

use Cwd qw(realpath);
use Digest::SHA qw(sha256_hex);
use Encode qw(FB_CROAK decode encode);
use Fcntl qw(O_NOFOLLOW O_RDONLY O_NONBLOCK S_ISDIR S_ISREG);
use File::Basename qw(basename);
use File::Glob qw(GLOB_NOSORT bsd_glob);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

has config => (
    is       => 'ro',
    required => 1,
);

has logger => (
    is       => 'ro',
    required => 1,
);

has parser => (
    is       => 'ro',
    required => 1,
);

sub scan {
    my ($self) = @_;

    my $directory = $self->config()->input_dir();
    if (!-e $directory) {
        $self->logger()->log('debug', "input directory is not present: $directory");
        return undef;
    }
    my $resolved_directory = realpath($directory);
    if (!defined($resolved_directory) || $resolved_directory ne $directory) {
        $self->logger()->log(
            'warning',
            "input path contains a symbolic or non-canonical component: $directory",
        );
        die "cannot take a trustworthy plan directory snapshot\n";
    }
    my @directory_stat = lstat($directory);
    if (!@directory_stat || !S_ISDIR($directory_stat[2]) || -l _) {
        $self->logger()->log('warning', "input path is not a safe directory: $directory");
        die "cannot take a trustworthy plan directory snapshot\n";
    }
    if ($directory_stat[4] != $<) {
        $self->logger()->log('warning', "input directory is not owned by the desktop user: $directory");
        die "cannot take a trustworthy plan directory snapshot\n";
    }

    opendir my $directory_handle, $directory or die "cannot enumerate plan directory: $!\n";
    my @names;
    while (1) {
        $! = 0;
        my $name = readdir $directory_handle;
        if (!defined $name) { die "cannot read plan directory: $!\n" if $!; last; }
        push @names, $name if $name =~ /\.txt\z/;
        @names <= $self->config()->max_input_files() or die "plan input file limit exceeded\n";
    }
    closedir $directory_handle or die "cannot close plan directory: $!\n";
    my @paths = map { "$directory/$_" } sort @names;
    if (@paths > $self->config()->max_input_files()) {
        $self->logger()->log(
            'warning',
            'input file limit exceeded; checkpoint retained',
        );
        die "plan input file limit exceeded\n";
    }

    my @entries;
    FILE:
    for my $path (@paths) {
        my $name = basename($path);
        if ($name !~ /\A[A-Za-z0-9][A-Za-z0-9._ -]{0,254}\.txt\z/) {
            $self->logger()->log('warning', 'skipping plan file with an unsafe name');
            next FILE;
        }
        my @before = lstat($path);
        die "plan file is unavailable or unsafe: $name\n" if !@before || !S_ISREG($before[2]) || -l _;
        if ($before[4] != $<) {
            $self->logger()->log('warning', "skipping plan file not owned by the desktop user: $name");
            die "incomplete plan scan: $name\n";
        }
        if ($before[7] > $self->config()->max_input_file_bytes()) {
            $self->logger()->log('warning', "skipping oversized plan file: $name");
            die "incomplete plan scan: $name\n";
        }

        sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
            or do {
                $self->logger()->log('warning', "cannot open plan file: $name");
                die "incomplete plan scan: $name\n";
            };
        my @opened = stat $fh;
        -f $fh && $opened[0] == $before[0] && $opened[1] == $before[1]
            && $opened[4] == $< && $opened[7] <= $self->config()->max_input_file_bytes()
            or die "plan file changed identity while opening: $name\n";
        binmode $fh, ':raw';
        my $raw = q{};
        while (length($raw) <= $self->config()->max_input_file_bytes()) {
            my $chunk = q{};
            my $read = sysread(
                $fh,
                $chunk,
                $self->config()->max_input_file_bytes() + 1 - length($raw),
            );
            if (!defined($read)) {
                next if $!{EINTR};
                close $fh;
                $self->logger()->log('warning', "cannot read plan file: $name");
                die "incomplete plan scan: $name\n";
            }
            last if $read == 0;
            $raw .= $chunk;
        }
        my @after = stat($fh);
        close $fh or do {
            $self->logger()->log('warning', "cannot close plan file: $name");
            die "incomplete plan scan: $name\n";
        };
        if (length($raw) > $self->config()->max_input_file_bytes()) {
            $self->logger()->log('warning', "skipping plan file that grew beyond the size limit: $name");
            die "incomplete plan scan: $name\n";
        }
        if (!@after || !S_ISREG($after[2]) || $after[4] != $< ||
            $after[0] != $before[0] || $after[1] != $before[1] ||
            $after[7] != $before[7] || $after[9] != $before[9] || $after[10] != $before[10]) {
            $self->logger()->log('warning', "plan file changed identity while being read: $name");
            die "incomplete plan scan: $name\n";
        }

        my $text = eval { decode('UTF-8', $raw, FB_CROAK) };
        if (!defined($text)) {
            $self->logger()->log('warning', "skipping non-UTF-8 plan file: $name");
            die "incomplete plan scan: $name\n";
        }

        my %duplicate_count;
        my $line_number = 0;
        for my $line (split /\n/, $text, -1) {
            $line_number++;
            die "plan line exceeds configured limit: $name:$line_number\n"
                if length($line) > $self->config()->max_line_characters();
            my $entry = $self->parser()->parse_line($name, $line_number, $line);
            next if !defined($entry);

            my $identity;
            if (defined($entry->source()) && $entry->source() ne q{}) {
                $identity = 'source:' . $entry->source();
            }
            else {
                $identity = 'content:' . $entry->fingerprint();
            }
            my $ordinal = ++$duplicate_count{$identity};
            $entry->key(
                sha256_hex(
                    encode('UTF-8', join("\0", $name, $identity, $ordinal)),
                ),
            );
            push @entries, $entry;
            if (@entries > $self->config()->max_entries()) {
                $self->logger()->log(
                    'warning',
                    'plan entry limit exceeded; checkpoint retained',
                );
                die "plan entry limit exceeded\n";
            }
        }
    }
    return \@entries;
}

1;

package LabwcPlans::Schedule;

use strict;
use warnings;

use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Time::Local qw(timegm timelocal);

has logger => (
    is       => 'ro',
    required => 1,
);

sub notifications_between {
    my ($self, $entry, $window_start, $window_end) = @_;

    return [] if $entry->invalid_schedule();
    my $recurrence = $entry->recurrence();
    my $start_string;
    if (defined($recurrence)) {
        $start_string = $entry->start_date()
            // $entry->created_date()
            // $entry->due_date();
    }
    else {
        $start_string = $entry->start_date() // $entry->due_date();
    }
    return [] if !defined($start_string);

    my $start = _parse_date($start_string);
    if (!defined($start)) {
        $self->logger()->log(
            'warning',
            "entry has an invalid start date in " . $entry->file(),
        );
        return [];
    }
    my $due;
    if (defined($entry->due_date())) {
        $due = _parse_date($entry->due_date());
        if (!defined($due)) {
            $self->logger()->log(
                'warning',
                "entry has an invalid due date in " . $entry->file(),
            );
            return [];
        }
        return [] if $due->{ordinal} < $start->{ordinal};
    }

    my $range_start = _local_date($window_start);
    my $range_end = _local_date($window_end);
    my $first_ordinal = $range_start->{ordinal} - 1;
    my $last_ordinal = $range_end->{ordinal} + 1;
    my %seen;
    my @notifications;

    for my $ordinal ($first_ordinal .. $last_ordinal) {
        my $candidate = _date_from_ordinal($ordinal);
        next if !_is_occurrence($candidate, $start, $due, $recurrence);

        my $date_string = _date_string($candidate);
        my %event_time = map { $_ => 1 } @{$entry->times()};
        if (!$event_time{1000}) {
            my $morning_epoch = _local_epoch($candidate, 10, 0);
            if (defined($morning_epoch)) {
                _append_if_due(
                    \@notifications,
                    \%seen,
                    $entry,
                    $window_start,
                    $window_end,
                    {
                        kind            => 'morning',
                        occurrence_date => $date_string,
                        event_time      => undef,
                        countdown       => undef,
                        epoch           => $morning_epoch,
                        slot            => 'morning',
                    },
                );
            }
        }

        for my $time (@{$entry->times()}) {
            my $hour = int($time / 100);
            my $minute = $time % 100;
            my $event_epoch = _local_epoch($candidate, $hour, $minute);
            next if !defined($event_epoch);
            my $time_string = sprintf('%02d:%02d', $hour, $minute);
            for my $offset (-3_600, -2_700, -1_800, -900, -600, -300, 0) {
                my $countdown = int(-$offset / 60);
                my $kind = $offset == 0 ? 'start' : 'countdown';
                _append_if_due(
                    \@notifications,
                    \%seen,
                    $entry,
                    $window_start,
                    $window_end,
                    {
                        kind            => $kind,
                        occurrence_date => $date_string,
                        event_time      => $time_string,
                        countdown       => $kind eq 'countdown' ? $countdown : undef,
                        epoch           => $event_epoch + $offset,
                        slot            => join(':', $time_string, $offset),
                    },
                );
            }
        }
    }
    @notifications = sort {
        $a->{epoch} <=> $b->{epoch} || $a->{id} cmp $b->{id}
    } @notifications;
    return \@notifications;
}

sub _append_if_due {
    my ($notifications, $seen, $entry, $window_start, $window_end, $spec) = @_;

    return if $spec->{epoch} < $window_start || $spec->{epoch} > $window_end;
    my $id = sha256_hex(
        encode(
            'UTF-8',
            join(
                "\0",
                'scheduled',
                $entry->key(),
                $spec->{occurrence_date},
                $spec->{slot},
            ),
        ),
    );
    return if $seen->{$id}++;
    $spec->{id} = $id;
    push @{$notifications}, $spec;
    return;
}

sub _parse_date {
    my ($value) = @_;

    return if !defined($value) || $value !~ /\A([0-9]{4})-([0-9]{2})-([0-9]{2})\z/;
    my ($year, $month, $day) = (int($1), int($2), int($3));
    return if $year < 1970 || $year > 9999 || $month < 1 || $month > 12 ||
        $day < 1 || $day > 31;
    my $epoch = eval { timegm(0, 0, 12, $day, $month - 1, $year) };
    return if !defined($epoch);
    my @parts = gmtime($epoch);
    return if $parts[5] + 1900 != $year || $parts[4] + 1 != $month ||
        $parts[3] != $day;
    return {
        year    => $year,
        month   => $month,
        day     => $day,
        ordinal => int($epoch / 86_400),
        weekday => $parts[6],
    };
}

sub _date_from_ordinal {
    my ($ordinal) = @_;

    my @parts = gmtime(($ordinal * 86_400) + 43_200);
    return {
        year    => $parts[5] + 1900,
        month   => $parts[4] + 1,
        day     => $parts[3],
        ordinal => $ordinal,
        weekday => $parts[6],
    };
}

sub _local_date {
    my ($epoch) = @_;

    my @parts = localtime($epoch);
    return _parse_date(
        sprintf('%04d-%02d-%02d', $parts[5] + 1900, $parts[4] + 1, $parts[3]),
    );
}

sub _local_epoch {
    my ($date, $hour, $minute) = @_;

    my $epoch = eval {
        timelocal(
            0,
            $minute,
            $hour,
            $date->{day},
            $date->{month} - 1,
            $date->{year},
        );
    };
    return if !defined($epoch);
    my @parts = localtime($epoch);
    return if $parts[5] + 1900 != $date->{year} ||
        $parts[4] + 1 != $date->{month} ||
        $parts[3] != $date->{day} ||
        $parts[2] != $hour ||
        $parts[1] != $minute;
    return $epoch;
}

sub _date_string {
    my ($date) = @_;
    return sprintf('%04d-%02d-%02d', $date->{year}, $date->{month}, $date->{day});
}

sub _is_occurrence {
    my ($candidate, $start, $due, $recurrence) = @_;

    return 0 if $candidate->{ordinal} < $start->{ordinal};
    return 0 if defined($due) && $candidate->{ordinal} > $due->{ordinal};
    return $candidate->{ordinal} == $start->{ordinal} if !defined($recurrence);

    $recurrence =~ /\A([1-9][0-9]{0,3})([dbwmy])\z/ or return 0;
    my ($interval, $unit) = (int($1), $2);
    my $difference = $candidate->{ordinal} - $start->{ordinal};
    return $difference % $interval == 0 if $unit eq 'd';
    return $difference % ($interval * 7) == 0 if $unit eq 'w';

    if ($unit eq 'm') {
        my $months = (($candidate->{year} - $start->{year}) * 12) +
            ($candidate->{month} - $start->{month});
        return 0 if $months < 0 || $months % $interval != 0;
        my $occurrence_day = $start->{day};
        my $last_day = _days_in_month($candidate->{year}, $candidate->{month});
        $occurrence_day = $last_day if $occurrence_day > $last_day;
        return $candidate->{day} == $occurrence_day;
    }
    if ($unit eq 'y') {
        my $years = $candidate->{year} - $start->{year};
        return 0 if $years < 0 || $years % $interval != 0;
        return 0 if $candidate->{month} != $start->{month};
        my $occurrence_day = $start->{day};
        my $last_day = _days_in_month($candidate->{year}, $candidate->{month});
        $occurrence_day = $last_day if $occurrence_day > $last_day;
        return $candidate->{day} == $occurrence_day;
    }
    if ($unit eq 'b') {
        my $normalized_start = $start->{ordinal};
        while (_date_from_ordinal($normalized_start)->{weekday} == 0 ||
            _date_from_ordinal($normalized_start)->{weekday} == 6) {
            $normalized_start++;
        }
        return 0 if $candidate->{ordinal} < $normalized_start;
        return 0 if $candidate->{weekday} == 0 || $candidate->{weekday} == 6;
        my $days = $candidate->{ordinal} - $normalized_start;
        my $business_index = int($days / 7) * 5;
        my $remainder = $days % 7;
        if ($remainder > 0) {
            for my $offset (0 .. $remainder - 1) {
                my $weekday = _date_from_ordinal($normalized_start + $offset)->{weekday};
                $business_index++ if $weekday >= 1 && $weekday <= 5;
            }
        }
        return $business_index % $interval == 0;
    }
    return 0;
}

sub _days_in_month {
    my ($year, $month) = @_;

    return 31 if $month == 1 || $month == 3 || $month == 5 ||
        $month == 7 || $month == 8 || $month == 10 || $month == 12;
    return 30 if $month == 4 || $month == 6 || $month == 9 || $month == 11;
    return 29 if $year % 400 == 0 ||
        ($year % 4 == 0 && $year % 100 != 0);
    return 28;
}

1;

package LabwcPlans::State;

use strict;
use warnings;

use Fcntl qw(:flock O_CREAT O_EXCL O_NOFOLLOW O_NONBLOCK O_RDONLY O_RDWR O_WRONLY F_SETFD FD_CLOEXEC);
use Cwd qw(realpath);
use File::Temp qw(tempfile);
use IO::Handle;
use File::Path qw(make_path);
use JSON::PP;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(HashRef Int Str);

has dry_run => (is => 'ro', default => sub { 0 });

has directory => (
    is       => 'ro',
    isa      => Str,
    required => 1,
);

has max_bytes => (
    is       => 'ro',
    isa      => Int,
    required => 1,
);

has logger => (
    is       => 'ro',
    required => 1,
);

has state => (
    is      => 'rw',
    isa     => HashRef,
    default => sub { _default_state() },
);

has lock_handle => (
    is => 'rw',
);

sub acquire_lock {
    my ($self) = @_;

    return if $self->dry_run() || defined($self->lock_handle());
    $self->_ensure_directory();
    my $path = $self->directory() . '/daemon.lock';
    sysopen my $fh, $path, O_RDWR | O_CREAT | O_NOFOLLOW, 0600
        or die "cannot open labwc-plans lock file: $!\n";
    my @st = stat $fh;
    -f $fh && $st[4] == $< && $st[3] == 1 && ($st[2] & 0077) == 0
        or die "unsafe labwc-plans lock file\n";
    fcntl($fh, F_SETFD, FD_CLOEXEC) or die "cannot protect labwc-plans lock: $!\n";
    flock($fh, LOCK_EX | LOCK_NB)
        or die "another labwc-plans daemon already owns the state directory\n";
    chmod 0600, $path or die "cannot secure labwc-plans lock file: $!\n";
    $self->lock_handle($fh);
    return;
}

sub load {
    my ($self) = @_;

    my $path = $self->directory() . '/state.json';
    if (!-e $path && !-l $path) {
        $self->state(_default_state());
        return $self->state();
    }
    my @metadata = lstat($path);
    if (!@metadata || !-f _ || -l _ || $metadata[4] != $< ||
        $metadata[3] != 1 || ($metadata[2] & 0077) || $metadata[7] > $self->max_bytes()) {
        return $self->_quarantine_state('state file metadata is unsafe');
    }
    sysopen my $fh, $path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK
        or return $self->_quarantine_state('state file cannot be opened');
    my @opened = stat $fh;
    -f $fh && $opened[0] == $metadata[0] && $opened[1] == $metadata[1]
        && $opened[4] == $< && $opened[3] == 1 && ($opened[2] & 0077) == 0
        or die "labwc-plans state changed identity while opening\n";
    binmode $fh, ':raw';
    my $raw = q{};
    while (length($raw) <= $self->max_bytes()) {
        my $chunk = q{};
        my $read = sysread($fh, $chunk, $self->max_bytes() + 1 - length($raw));
        if (!defined($read)) {
            next if $!{EINTR};
            close $fh;
            return $self->_quarantine_state('state file cannot be read');
        }
        last if $read == 0;
        $raw .= $chunk;
    }
    close $fh or die "cannot close labwc-plans state: $!\n";
    return $self->_quarantine_state('state file exceeds the size limit')
        if length($raw) > $self->max_bytes();

    my $decoded = eval { JSON::PP->new()->utf8(1)->decode($raw) };
    if (!defined($decoded) || ref($decoded) ne 'HASH' ||
        ($decoded->{version} // 0) != 1 ||
        ref($decoded->{seen_entries}) ne 'HASH' ||
        ref($decoded->{notifications}) ne 'HASH' ||
        ref($decoded->{sent}) ne 'HASH' ||
        !_state_shape_valid($decoded)) {
        return $self->_quarantine_state('state file is not valid labwc-plans JSON');
    }
    $decoded->{initialized} = $decoded->{initialized} ? 1 : 0;
    $decoded->{last_scan_epoch} = int($decoded->{last_scan_epoch} // 0);
    $self->state($decoded);
    return $decoded;
}

sub save {
    my ($self) = @_;
    return if $self->dry_run();
    defined($self->lock_handle()) or die "labwc-plans state write requires its lifetime lock\n";
    $self->_ensure_directory();
    my $json = JSON::PP->new()->canonical(1)->utf8(1)->encode($self->state());
    length($json) <= $self->max_bytes() or die "labwc-plans state exceeds the configured size limit\n";
    my $path = $self->directory() . '/state.json';
    -l $path and die "labwc-plans state must not be a symlink\n";
    my ($fh, $temporary) = tempfile('.state.XXXXXXXX', DIR => $self->directory(), UNLINK => 1);
    my $ok = eval {
        binmode $fh, ':raw' or die "cannot set state mode: $!\n";
        print {$fh} $json or die "cannot write temporary labwc-plans state: $!\n";
        $fh->flush && $fh->sync or die "cannot sync labwc-plans state: $!\n";
        close $fh or die "cannot close labwc-plans state: $!\n";
        rename $temporary, $path or die "cannot publish labwc-plans state: $!\n";
        sysopen my $directory, $self->directory(), O_RDONLY | O_NOFOLLOW
            or die "cannot open state directory for sync: $!\n";
        $directory->sync or die "cannot sync labwc-plans directory: $!\n";
        close $directory or die "cannot close state directory: $!\n";
        1;
    };
    my $error = $@;
    unlink $temporary if -e $temporary;
    die $error if !$ok;
    return;
}

sub _ensure_directory {
    my ($self) = @_;

    if (!-e $self->directory()) {
        make_path($self->directory(), { mode => 0700 });
    }
    my $resolved = realpath($self->directory());
    defined($resolved) && $resolved eq $self->directory()
        or die "labwc-plans state path contains a symlink or non-canonical component\n";
    my @metadata = lstat($self->directory());
    @metadata && -d _ && !-l _ && $metadata[4] == $<
        or die "labwc-plans state directory is unsafe\n";
    chmod 0700, $self->directory()
        or die "cannot secure labwc-plans state directory: $!\n";
    return;
}

sub _quarantine_state {
    my ($self, $reason) = @_;
    # Silently resetting state replays sent reminders and loses pending ones.
    # Preserve evidence and fail closed; recovery requires an explicit repair
    # or an operator-approved backup/reset of this exact state file.
    die "labwc-plans: $reason; existing state retained at " . $self->directory() . "/state.json\n";
}

sub _state_shape_valid {
    my ($state) = @_;

    return 0 if !_is_nonnegative_integer($state->{last_scan_epoch} // 0);

    for my $key (keys %{$state->{seen_entries}}) {
        return 0 if $key !~ /\A[0-9a-f]{64}\z/;
        my $record = $state->{seen_entries}->{$key};
        return 0 if ref($record) ne 'HASH';
        return 0 if ($record->{fingerprint} // q{}) !~ /\A[0-9a-f]{64}\z/;
        return 0 if !_is_nonnegative_integer($record->{generation} // 0);
        return 0 if !_is_nonnegative_integer($record->{last_seen} // 0);
        return 0 if !_is_nonnegative_integer($record->{missing_since} // 0);
    }

    for my $id (keys %{$state->{notifications}}) {
        return 0 if $id !~ /\A[0-9a-f]{64}\z/;
        my $notification = $state->{notifications}->{$id};
        return 0 if ref($notification) ne 'HASH';
        return 0 if ($notification->{id} // q{}) ne $id;
        return 0 if !_is_nonnegative_integer($notification->{created_epoch} // q{});
        return 0 if !_is_nonnegative_integer($notification->{due_epoch} // q{});
        return 0 if ($notification->{priority} // q{}) !~ /\A[ABC]\z/;
        return 0 if ref($notification->{title}) ||
            ref($notification->{message}) ||
            !defined($notification->{title}) ||
            !defined($notification->{message});
        return 0 if ref($notification->{channels}) ne 'HASH';
        for my $channel (qw(telegram ntfy)) {
            my $channel_state = $notification->{channels}->{$channel};
            return 0 if ref($channel_state) ne 'HASH';
            return 0 if ($channel_state->{status} // q{}) !~
                /\A(?:pending|delivered|disabled)\z/;
            return 0 if !_is_nonnegative_integer($channel_state->{attempts} // 0);
            return 0 if !_is_nonnegative_integer($channel_state->{next_attempt} // 0);
            return 0 if exists($channel_state->{delivered_epoch}) &&
                !_is_nonnegative_integer($channel_state->{delivered_epoch});
            return 0 if exists($channel_state->{last_error}) &&
                (ref($channel_state->{last_error}) ||
                !defined($channel_state->{last_error}));
        }
    }

    for my $id (keys %{$state->{sent}}) {
        return 0 if $id !~ /\A[0-9a-f]{64}\z/;
        return 0 if !_is_nonnegative_integer($state->{sent}->{$id});
    }
    return 1;
}

sub _is_nonnegative_integer {
    my ($value) = @_;

    return defined($value) && !ref($value) &&
        "$value" =~ /\A[0-9]+\z/;
}

sub _default_state {
    return {
        version         => 1,
        initialized     => 0,
        last_scan_epoch => 0,
        seen_entries    => {},
        notifications   => {},
        sent            => {},
    };
}

1;

package LabwcPlans::Transport;

use strict;
use warnings;

use Encode qw(encode);
use HTTP::Tiny;
use JSON::PP;
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Bool);

has config => (
    is       => 'ro',
    required => 1,
);

has logger => (
    is       => 'ro',
    required => 1,
);

has dry_run => (
    is       => 'ro',
    isa      => Bool,
    required => 1,
);

has http => (
    is      => 'lazy',
    builder => '_build_http',
);

sub _build_http {
    my ($self) = @_;

    return HTTP::Tiny->new(
        agent        => 'labwc-plans/1.0',
        max_redirect => 0,
        max_size     => 65_536,
        timeout      => $self->config()->http_timeout_seconds(),
        verify_SSL   => 1,
    );
}

sub send {
    my ($self, $channel, $notification) = @_;

    if ($self->dry_run()) {
        my $rendered = JSON::PP->new()->canonical(1)->utf8(1)->encode({
            channel => $channel,
            id      => $notification->{id},
            message => $notification->{message},
            title   => $notification->{title},
        });
        print STDOUT $rendered, "\n";
        return {
            ok          => 1,
            retry_after => 0,
            error       => q{},
        };
    }
    return $self->_send_telegram($notification) if $channel eq 'telegram';
    return $self->_send_ntfy($notification) if $channel eq 'ntfy';
    return {
        ok          => 0,
        retry_after => 0,
        error       => 'unsupported notification channel',
    };
}

sub _bounded_request {
    my ($self, @args) = @_;
    my %previous = map { $_ => $SIG{$_} } qw(INT TERM);
    local $SIG{ALRM} = sub { die "notification HTTP deadline exceeded\n" };
    local $SIG{INT} = sub {
        $previous{INT}->('INT') if ref($previous{INT}) eq 'CODE';
        die "notification delivery interrupted\n";
    };
    local $SIG{TERM} = sub {
        $previous{TERM}->('TERM') if ref($previous{TERM}) eq 'CODE';
        die "notification delivery interrupted\n";
    };
    my $response;
    my $ok = eval {
        alarm $self->config()->http_timeout_seconds();
        $response = $self->http()->request(@args);
        1;
    };
    alarm 0;
    # Do not expose endpoint URLs (which may contain bot credentials) in logs.
    return $ok ? $response : undef;
}

sub _send_telegram {
    my ($self, $notification) = @_;

    my $endpoint = $self->config()->telegram_api_base() .
        '/bot' . $self->config()->telegram_api_key() . '/sendMessage';
    my $payload = JSON::PP->new()->canonical(1)->utf8(1)->encode({
        chat_id                  => $self->config()->telegram_chat_id(),
        disable_web_page_preview => JSON::PP::true,
        text                     => $notification->{title} . "\n\n" . $notification->{message},
    });
    my $response = eval {
        $self->_bounded_request(
            'POST',
            $endpoint,
            {
                content => $payload,
                headers => {
                    accept         => 'application/json',
                    'content-type' => 'application/json',
                },
            },
        );
    };
    if (!defined($response)) {
        return {
            ok          => 0,
            retry_after => 0,
            error       => 'Telegram request failed before an HTTP response',
        };
    }

    my $decoded = eval {
        JSON::PP->new()->utf8(1)->decode($response->{content} // q{});
    };
    if ($response->{success} && ref($decoded) eq 'HASH' && $decoded->{ok}) {
        return {
            ok          => 1,
            retry_after => 0,
            error       => q{},
        };
    }
    my $retry_after = 0;
    if (ref($decoded) eq 'HASH' && ref($decoded->{parameters}) eq 'HASH' &&
        ($decoded->{parameters}->{retry_after} // q{}) =~ /\A[0-9]{1,6}\z/) {
        $retry_after = int($decoded->{parameters}->{retry_after});
    }
    return {
        ok          => 0,
        retry_after => $retry_after,
        error       => sprintf(
            'Telegram delivery returned HTTP %s',
            $response->{status} // 'unknown',
        ),
    };
}

sub _send_ntfy {
    my ($self, $notification) = @_;

    my %priority = (
        A => 5,
        B => 4,
        C => 3,
    );
    my $payload = JSON::PP->new()->canonical(1)->utf8(1)->encode({
        message     => _truncate_utf8_bytes($notification->{message}, 4_096),
        priority    => $priority{$notification->{priority}} // 3,
        sequence_id => substr($notification->{id}, 0, 48),
        tags        => ['calendar'],
        title       => $notification->{title},
        topic       => $self->config()->ntfy_topic(),
    });
    my %headers = (
        accept         => 'application/json',
        'content-type' => 'application/json',
    );
    if ($self->config()->ntfy_access_token() ne q{}) {
        $headers{authorization} = 'Bearer ' . $self->config()->ntfy_access_token();
    }
    my $response = eval {
        $self->_bounded_request(
            'POST',
            $self->config()->ntfy_base_url() . '/',
            {
                content => $payload,
                headers => \%headers,
            },
        );
    };
    if (!defined($response)) {
        return {
            ok          => 0,
            retry_after => 0,
            error       => 'ntfy request failed before an HTTP response',
        };
    }
    if ($response->{success}) {
        return {
            ok          => 1,
            retry_after => 0,
            error       => q{},
        };
    }
    my $retry_after = 0;
    my $header = $response->{headers}->{'retry-after'} // q{};
    $retry_after = int($header) if $header =~ /\A[0-9]{1,6}\z/;
    return {
        ok          => 0,
        retry_after => $retry_after,
        error       => sprintf(
            'ntfy delivery returned HTTP %s',
            $response->{status} // 'unknown',
        ),
    };
}

sub _truncate_utf8_bytes {
    my ($value, $maximum) = @_;

    return $value if length(encode('UTF-8', $value)) <= $maximum;

    my $suffix = "\x{2026}";
    my $target = $maximum - length(encode('UTF-8', $suffix));
    my ($minimum, $upper) = (0, length($value));
    while ($minimum < $upper) {
        my $middle = int(($minimum + $upper + 1) / 2);
        if (length(encode('UTF-8', substr($value, 0, $middle))) <= $target) {
            $minimum = $middle;
        }
        else {
            $upper = $middle - 1;
        }
    }
    return substr($value, 0, $minimum) . $suffix;
}

1;

package LabwcPlans::Daemon;

use strict;
use warnings;

use Digest::SHA qw(sha256_hex);
use Encode qw(encode);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Time::HiRes qw(sleep time);
use Types::Standard qw(Bool);

has config => (
    is       => 'ro',
    required => 1,
);

has logger => (
    is       => 'ro',
    required => 1,
);

has scanner => (
    is       => 'ro',
    required => 1,
);

has schedule => (
    is       => 'ro',
    required => 1,
);

has state_store => (
    is       => 'ro',
    required => 1,
);

has transport => (
    is       => 'ro',
    required => 1,
);

has stop_requested => (
    is      => 'rw',
    isa     => Bool,
    default => sub { 0 },
);

sub run_forever {
    my ($self) = @_;

    local $SIG{INT} = sub { $self->stop_requested(1) };
    local $SIG{TERM} = sub { $self->stop_requested(1) };
    local $SIG{HUP} = sub { $self->logger()->log('info', 'SIGHUP received; configuration changes require a service restart') };

    my $failures = 0;
    while (!$self->stop_requested()) {
        my $ok = eval {
            $self->run_once(int(time()));
            1;
        };
        if ($ok) {
            $failures = 0;
        }
        else {
            $failures++;
            my $error = $@ || 'unknown daemon cycle failure';
            $self->logger()->log('error', $error);
            # A failed save may leave only the in-memory checkpoint advanced.
            # Reload the last atomically published state before retrying.
            $self->state_store()->load();
            if ($failures >= $self->config()->max_consecutive_cycle_failures()) {
                die "labwc-plans exceeded the consecutive cycle failure limit\n";
            }
        }
        my $remaining = $self->config()->poll_seconds();
        while ($remaining > 0 && !$self->stop_requested()) {
            sleep($remaining > 1 ? 1 : $remaining);
            $remaining--;
        }
    }
    $self->logger()->log('info', 'daemon stopped');
    return;
}

sub run_once {
    my ($self, $now) = @_;

    my $state = $self->state_store()->state();
    my $window_start = $self->_window_start($state, $now);
    my $entries = $self->scanner()->scan();
    if (!defined $entries) {
        $self->_deliver($state, $now) if !$self->stop_requested();
        return; # An unavailable input directory is not an empty authoritative scan.
    }
    return if $self->stop_requested();
    my %current;
    my $first_scan = !$state->{initialized};
    my $queue_saturated = 0;

    for my $entry (@{$entries}) {
        $current{$entry->key()} = 1;
        my $record = $state->{seen_entries}->{$entry->key()};
        my $is_new = !defined($record);
        my $generation = defined($record)
            ? int($record->{generation} // 0)
            : 0;
        if (defined($record) && ($record->{missing_since} // 0) > 0 &&
            $now - $record->{missing_since} >= $self->config()->readd_grace_seconds()) {
            $is_new = 1;
        }
        if ($is_new) {
            $generation++;
            if (!$first_scan || $self->config()->notify_existing()) {
                my $queued = $self->_enqueue_immediate(
                    $state,
                    $entry,
                    $now,
                    $generation,
                );
                if (!$queued) {
                    $queue_saturated = 1;
                    next;
                }
            }
        }
        $state->{seen_entries}->{$entry->key()} = {
            fingerprint   => $entry->fingerprint(),
            generation    => $generation,
            last_seen     => $now,
            missing_since => 0,
        };

        my $scheduled = $self->schedule()->notifications_between(
            $entry,
            $window_start,
            $now,
        );
        for my $spec (@{$scheduled}) {
            $queue_saturated = 1
                if !$self->_enqueue_scheduled($state, $entry, $spec, $now);
        }
    }

    for my $key (keys %{$state->{seen_entries}}) {
        next if $current{$key};
        my $record = $state->{seen_entries}->{$key};
        $record->{missing_since} = $now if !($record->{missing_since} // 0);
    }

    $self->_prune_state($state, $now);
    if (!$queue_saturated) {
        $state->{initialized} = 1;
        $state->{last_scan_epoch} = $now;
    }
    else {
        $self->logger()->log(
            'warning',
            'notification queue is saturated; retaining the previous schedule checkpoint',
        );
    }
    $self->state_store()->save();
    $self->_deliver($state, $now);
    return;
}

sub _window_start {
    my ($self, $state, $now) = @_;

    my $start;
    if ($state->{initialized} && ($state->{last_scan_epoch} // 0) > 0) {
        $start = int($state->{last_scan_epoch});
        if ($start > $now) {
            $self->logger()->log('warning', 'system clock moved backwards; using one poll interval as the schedule window');
            $start = $now - $self->config()->poll_seconds();
        }
        my $minimum = $now - $self->config()->max_catchup_seconds();
        $start = $minimum if $start < $minimum;
    }
    else {
        $start = $now - $self->config()->initial_catchup_seconds();
    }
    return $start;
}

sub _enqueue_immediate {
    my ($self, $state, $entry, $now, $generation) = @_;

    my $id = sha256_hex(
        encode(
            'UTF-8',
            join(
                "\0",
                'immediate',
                $entry->key(),
                $entry->fingerprint(),
                $generation,
            ),
        ),
    );
    my $message = $entry->display() .
        "\n\nAdded from " . $entry->file() .
        ' with priority ' . $entry->priority() . '.';
    return $self->_enqueue(
        $state,
        {
            id            => $id,
            created_epoch => $now,
            due_epoch     => $now,
            priority      => $entry->priority(),
            title         => 'New plan (' . $entry->priority() . ')',
            message       => $self->_bounded_message($message),
        },
    );
}

sub _enqueue_scheduled {
    my ($self, $state, $entry, $spec, $now) = @_;

    my $title;
    if ($spec->{kind} eq 'morning') {
        $title = q{Today's plan (} . $entry->priority() . ')';
    }
    elsif ($spec->{kind} eq 'start') {
        $title = 'Plan starts now (' . $entry->priority() . ')';
    }
    else {
        $title = 'Plan in ' . $spec->{countdown} . ' minutes (' .
            $entry->priority() . ')';
    }

    my @details = ($entry->display());
    my $schedule_line = 'Date: ' . $spec->{occurrence_date};
    $schedule_line .= ' at ' . $spec->{event_time}
        if defined($spec->{event_time});
    push @details, q{}, $schedule_line;
    push @details, 'Recurrence: ' . $entry->recurrence()
        if defined($entry->recurrence());
    push @details, 'Through: ' . $entry->due_date()
        if defined($entry->due_date());
    push @details, 'File: ' . $entry->file();

    return $self->_enqueue(
        $state,
        {
            id            => $spec->{id},
            created_epoch => $now,
            due_epoch     => $spec->{epoch},
            priority      => $entry->priority(),
            title         => $title,
            message       => $self->_bounded_message(join("\n", @details)),
        },
    );
}

sub _enqueue {
    my ($self, $state, $notification) = @_;

    return 1 if exists($state->{sent}->{$notification->{id}});
    if (exists($state->{notifications}->{$notification->{id}})) {
        my $existing = $state->{notifications}->{$notification->{id}};
        $existing->{title} = $notification->{title};
        $existing->{message} = $notification->{message};
        $existing->{priority} = $notification->{priority};
        return 1;
    }
    if (scalar(keys %{$state->{notifications}}) >= $self->config()->max_queue_items()) {
        $self->logger()->log('error', 'notification queue limit reached; refusing to enqueue another notification');
        return 0;
    }
    $notification->{channels} = {
        telegram => {
            attempts     => 0,
            next_attempt => 0,
            status       => $self->config()->telegram_enabled() ? 'pending' : 'disabled',
        },
        ntfy => {
            attempts     => 0,
            next_attempt => 0,
            status       => $self->config()->ntfy_enabled() ? 'pending' : 'disabled',
        },
    };
    $state->{notifications}->{$notification->{id}} = $notification;
    return 1;
}

sub _deliver {
    my ($self, $state, $now) = @_;

    my $attempts = 0;
    for my $id (
        sort {
            ($state->{notifications}->{$a}->{due_epoch} // 0) <=>
                ($state->{notifications}->{$b}->{due_epoch} // 0) ||
                $a cmp $b
        } keys %{$state->{notifications}}
    ) {
        last if $self->stop_requested() || $attempts >= $self->config()->max_deliveries_per_cycle();
        my $notification = $state->{notifications}->{$id};
        CHANNEL:
        for my $channel (qw(telegram ntfy)) {
            last if $self->stop_requested() || $attempts >= $self->config()->max_deliveries_per_cycle();
            my $channel_state = $notification->{channels}->{$channel};
            next CHANNEL if ($channel_state->{status} // q{}) ne 'pending';
            next CHANNEL if ($channel_state->{next_attempt} // 0) > $now;
            $attempts++;
            my $result = $self->transport()->send($channel, $notification);
            if ($result->{ok}) {
                $channel_state->{status} = 'delivered';
                $channel_state->{delivered_epoch} = $now;
                $channel_state->{next_attempt} = 0;
                $self->logger()->log('info', "delivered notification channel=$channel id=$id");
            }
            else {
                $channel_state->{attempts} = int($channel_state->{attempts} // 0) + 1;
                my $delay = $self->_retry_delay($channel_state->{attempts});
                $delay = $result->{retry_after}
                    if ($result->{retry_after} && $result->{retry_after} > $delay);
                $delay = $self->config()->retry_max_seconds()
                    if $delay > $self->config()->retry_max_seconds();
                $channel_state->{next_attempt} = $now + $delay;
                $channel_state->{last_error} = $result->{error};
                $self->logger()->log(
                    'warning',
                    "delivery deferred channel=$channel id=$id retry_seconds=$delay error=$result->{error}",
                );
            }
            $self->state_store()->save();
        }
        if (_notification_complete($notification)) {
            $state->{sent}->{$id} = $now;
            delete $state->{notifications}->{$id};
            $self->state_store()->save();
        }
    }
    return;
}

sub _retry_delay {
    my ($self, $attempt) = @_;

    my $delay = $self->config()->retry_min_seconds();
    for (2 .. $attempt) {
        $delay *= 2;
        last if $delay >= $self->config()->retry_max_seconds();
    }
    return $delay > $self->config()->retry_max_seconds()
        ? $self->config()->retry_max_seconds()
        : $delay;
}

sub _prune_state {
    my ($self, $state, $now) = @_;

    my $cutoff = $now - ($self->config()->state_retention_days() * 86_400);
    for my $id (keys %{$state->{sent}}) {
        delete $state->{sent}->{$id} if ($state->{sent}->{$id} // 0) < $cutoff;
    }
    for my $key (keys %{$state->{seen_entries}}) {
        my $record = $state->{seen_entries}->{$key};
        delete $state->{seen_entries}->{$key}
            if ($record->{last_seen} // 0) < $cutoff;
    }
    return;
}

sub _bounded_message {
    my ($self, $message) = @_;

    my $maximum = $self->config()->max_notification_characters();
    return $message if length($message) <= $maximum;
    return substr($message, 0, $maximum - 1) . "\x{2026}";
}

sub _notification_complete {
    my ($notification) = @_;

    for my $channel (qw(telegram ntfy)) {
        my $status = $notification->{channels}->{$channel}->{status} // q{};
        return 0 if $status ne 'delivered' && $status ne 'disabled';
    }
    return 1;
}

1;

package main;

use strict;
use warnings;

use Getopt::Long qw(GetOptionsFromArray);
use Time::HiRes qw(time);

sub main {
umask 0077;
binmode STDERR, ':encoding(UTF-8)';
binmode STDOUT, ':raw';

my $once = 0;
my $dry_run = 0;
my $help = 0;
my $now_epoch;
GetOptionsFromArray(
    \@ARGV,
    'once'        => \$once,
    'dry-run'     => \$dry_run,
    'now-epoch=i' => \$now_epoch,
    'help'        => \$help,
) or _usage(2);
_usage(0) if $help;
@ARGV == 0 or _usage(2);
$dry_run && !$once and die "--dry-run requires --once\n";
defined($now_epoch) && !$once and die "--now-epoch requires --once\n";
defined($now_epoch) && $now_epoch < 0 and die "--now-epoch must not be negative\n";

delete @ENV{
    qw(
        ALL_PROXY HTTPS_PROXY HTTP_PROXY NO_PROXY
        all_proxy https_proxy http_proxy no_proxy
    )
};

my $config = LabwcPlans::Config->from_environment();
exit 0 if !$config->enabled();
my $logger = LabwcPlans::Logger->new(
    debug_enabled => $config->debug_enabled(),
);
my $state_store = LabwcPlans::State->new(
    dry_run   => $dry_run,
    directory => $config->state_dir(),
    logger    => $logger,
    max_bytes => $config->max_state_bytes(),
);
$state_store->acquire_lock();
$state_store->load();

my $parser = LabwcPlans::Parser->new(logger => $logger);
my $scanner = LabwcPlans::Scanner->new(
    config => $config,
    logger => $logger,
    parser => $parser,
);
my $schedule = LabwcPlans::Schedule->new(logger => $logger);
my $transport = LabwcPlans::Transport->new(
    config  => $config,
    dry_run => $dry_run,
    logger  => $logger,
);
my $daemon = LabwcPlans::Daemon->new(
    config      => $config,
    logger      => $logger,
    scanner     => $scanner,
    schedule    => $schedule,
    state_store => $state_store,
    transport   => $transport,
);

$SIG{INT} = sub { $daemon->stop_requested(1) };
$SIG{TERM} = sub { $daemon->stop_requested(1) };

if ($once) {
    $daemon->run_once(defined($now_epoch) ? $now_epoch : int(time()));
    exit 0;
}

$logger->log('info', 'daemon started');
$daemon->run_forever();
return 0;
}

sub _usage {
    my ($status) = @_;

    print STDERR "usage: labwc-plans.pl [--once [--dry-run] [--now-epoch EPOCH]]\n";
    exit $status;
}

exit main() unless caller;
1;
