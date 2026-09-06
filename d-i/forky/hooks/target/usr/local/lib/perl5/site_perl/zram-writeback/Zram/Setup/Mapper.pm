package Zram::Setup::Mapper;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Base qw(Str);

use IPC::Open3 qw(open3);
use Symbol qw(gensym);
use Time::HiRes qw(sleep);
use Zram::Config qw(cfg);
use Zram::Error qw(fatal);
use Zram::Path qw(same_path);

has mapper_name => (is => 'ro', isa => Str, default => sub { cfg('ZRAM_BACKING_MAPPER_NAME') });
has mapper_path => (is => 'ro', isa => Str, default => sub { cfg('ZRAM_BACKING_DEVICE') });
has raw_path    => (is => 'ro', isa => Str, default => sub { cfg('ZRAM_BACKING_RAW_DEVICE') });

sub _capture {
    my ($self, @command) = @_;
    my $stderr = gensym;
    my $pid = open3(undef, my $stdout, $stderr, @command);
    my $out = do { local $/; <$stdout> // '' };
    my $err = do { local $/; <$stderr> // '' };
    waitpid $pid, 0;
    return ($? >> 8, $out, $err);
}

sub _run {
    my ($self, @command) = @_;
    system @command;
    return $? == 0;
}

sub _wait_for_mapper {
    my ($self, $seconds) = @_;
    for (1 .. $seconds) {
        return 1 if -b $self->mapper_path();
        sleep 1;
    }
    return -b $self->mapper_path() ? 1 : 0;
}

sub _mapped_source {
    my ($self) = @_;
    my ($status, $out) = $self->_capture('/usr/sbin/cryptsetup', 'status', $self->mapper_name());
    return undef if $status != 0;
    my ($source) = $out =~ /^\s*device:\s*(\S+)\s*$/m;
    return $source;
}

sub ensure_open {
    my ($self) = @_;
    -b $self->raw_path() or fatal('missing raw zram writeback partition ' . $self->raw_path());
    if (-b $self->mapper_path()) {
        my $source = $self->_mapped_source();
        defined $source && same_path($source, $self->raw_path())
            or fatal('existing zram writeback mapper does not match its configured raw backing device');
        return 1;
    }

    for my $module (qw(dm_mod dm_crypt)) {
        $self->_run('/usr/sbin/modprobe', $module);
    }
    my $key_bytes = cfg('DMCRYPT_EPHEMERAL_KEY_SIZE') / 8;
    $self->_run(
        '/usr/sbin/cryptsetup',
        'open',
        '--type', 'plain',
        '--batch-mode',
        '--key-file', cfg('DMCRYPT_RANDOM_KEY_FILE'),
        '--keyfile-size', $key_bytes,
        '--cipher', cfg('DMCRYPT_EPHEMERAL_CIPHER'),
        '--key-size', cfg('DMCRYPT_EPHEMERAL_KEY_SIZE'),
        '--hash', cfg('DMCRYPT_EPHEMERAL_HASH'),
        $self->raw_path(),
        $self->mapper_name(),
    ) or fatal('failed to open ephemeral zram writeback mapper ' . $self->mapper_name());
    $self->_wait_for_mapper(10)
        or fatal('zram writeback mapper did not appear: ' . $self->mapper_path());
    return 1;
}

sub close {
    my ($self) = @_;
    return 1 if !-b $self->mapper_path();
    my $source = $self->_mapped_source();
    defined $source && same_path($source, $self->raw_path())
        or fatal('zram writeback mapper does not match its configured raw backing device');

    my $attempts = 20;
    for my $attempt (1 .. $attempts) {
        my ($status) = $self->_capture(
            '/usr/sbin/cryptsetup',
            'close',
            $self->mapper_name(),
        );
        return 1 if $status == 0 || !-b $self->mapper_path();
        sleep 0.5 if $attempt < $attempts;
    }

    fatal(
        'failed to close ephemeral zram writeback mapper after bounded retries '
            . $self->mapper_name()
    );
}

1;
