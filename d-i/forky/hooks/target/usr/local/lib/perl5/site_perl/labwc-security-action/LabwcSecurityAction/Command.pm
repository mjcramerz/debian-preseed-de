package LabwcSecurityAction::Command;

use strict;
use warnings;

use lib '/usr/local/lib/perl5/site_perl/managed-runtime';
use Managed::Process qw(capture_command);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Str);

has path => (
    is      => 'ro',
    isa     => Str,
    default => sub { $ENV{PATH} // '/usr/local/bin:/usr/bin:/bin' },
);

sub _status {
    my ($status) = @_;

    return 255 if !defined($status) || $status == -1;
    return 128 + ($status & 127) if $status & 127;
    return $status >> 8;
}

sub executable {
    my ($self, $name) = @_;

    defined($name) && $name =~ /\A[A-Za-z0-9][A-Za-z0-9+._-]*\z/
        or die "invalid executable name\n";
    for my $directory (split /:/, $self->path()) {
        next if $directory !~ m{\A/};
        my $candidate = "$directory/$name";
        return $candidate if -x $candidate && !-d $candidate;
    }
    return undef;
}

sub require_executable {
    my ($self, $name) = @_;

    my $program = $self->executable($name);
    defined($program)
        or die "required security command is not installed: $name\n";
    return $program;
}

sub run {
    my ($self, @argv) = @_;

    @argv && defined($argv[0]) && $argv[0] ne q{}
        or die "cannot run an empty command\n";
    system { $argv[0] } @argv;
    return _status($?);
}

sub exec {
    my ($self, @argv) = @_;

    @argv && defined($argv[0]) && $argv[0] ne q{}
        or die "cannot execute an empty command\n";
    exec { $argv[0] } @argv;
    die "cannot execute $argv[0]: $!\n";
}

sub capture {
    my ($self, %args) = @_;
    my $result = capture_command(
        argv => $args{argv},
        input => $args{input},
        timeout => $args{timeout} // 120,
        limit => 1_048_576,
    );
    return (_status($result->{status}), $result->{stdout});
}
1;
