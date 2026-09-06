package TimeshiftManaged::Command;

use strict;
use warnings;

use lib '/usr/local/lib/perl5/site_perl/managed-runtime';
use Managed::Process qw(capture_command);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(ArrayRef Str);

sub status_from_wait {
    my ($status) = @_;

    return 255 if !defined($status) || $status == -1;
    return 128 + ($status & 127) if $status & 127;
    return $status >> 8;
}

sub run {
    my ($self, @argv) = @_;

    die "command is missing\n" if !@argv || !defined($argv[0]) || $argv[0] eq q{};
    system { $argv[0] } @argv;
    return status_from_wait($?);
}

sub capture {
    my ($self, %args) = @_;
    my $result = capture_command(
        argv => $args{argv},
        input => $args{input},
        timeout => $args{timeout} // 120,
        limit => 1_048_576,
    );
    return (status_from_wait($result->{status}), $result->{stdout});
}
sub find_executable {
    my ($self, $name) = @_;

    defined($name) && $name =~ /\A[A-Za-z0-9][A-Za-z0-9+._-]*\z/
        or die "invalid executable name\n";
    for my $directory (qw(/usr/sbin /usr/bin /sbin /bin)) {
        my $candidate = "$directory/$name";
        return $candidate if -x $candidate && !-d $candidate;
    }
    return undef;
}

1;
