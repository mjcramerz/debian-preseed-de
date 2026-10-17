package APTRepoLocal::Servicing::HTTP;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use Time::HiRes qw(clock_gettime CLOCK_MONOTONIC);
use lib '/usr/local/lib/perl5/site_perl/runtime';

use APTRepoLocal::Servicing::Atomic;

sub _host {
    my ($self, $url) = @_;
    defined($url) && !ref($url) && length($url) <= 2048 && $url !~ /[\x00-\x20\x7f]/
        or die "URL contains unsupported syntax\n";
    $url =~ m{\Ahttps://([^/?#:]+)(?::443)?(?:/|\z)}
        or die "URL is not an approved HTTPS URL\n";
    my $host = lc $1;
    $host =~ /\A(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\z/
        or die "URL contains an invalid host\n";
    return $host;
}

sub _allow {
    my ($self, $url, $allowed_hosts) = @_;
    my %allowed = map { $_ => 1 } @{$allowed_hosts};
    $allowed{$self->_host($url)} or die "URL resolved to an unapproved host\n";
}

sub download {
    my ($self, %args) = @_;
    require Managed::Process;
    for my $key (qw(label url destination minimum maximum allowed_hosts content_policy)) {
        exists $args{$key} or die "missing HTTP download parameter $key\n";
    }
    $args{minimum} =~ /\A[0-9]+\z/ && $args{maximum} =~ /\A[0-9]+\z/
        && $args{minimum} <= $args{maximum}
        or die "invalid HTTP download size bounds\n";
    $args{content_policy} =~ /\A(?:artifact|metadata)\z/
        or die "unsupported HTTP content policy\n";
    my $user_agent = $args{user_agent} // 'debian-installer-software/2.0';
    $user_agent =~ /\A[A-Za-z0-9][A-Za-z0-9 ._+\/-]{0,127}\z/
        or die "invalid HTTP user agent\n";
    APTRepoLocal::Servicing::Atomic->assert_absolute_path('download destination', $args{destination});
    $self->_allow($args{url}, $args{allowed_hosts});

    my $partial = "$args{destination}.part";
    unlink $partial if -e $partial || -l $partial;
    my $url = $args{url};
    my $deadline = clock_gettime(CLOCK_MONOTONIC) + 1200;
    my ($status, $effective, $content_type);
    my $ok = eval {
        for my $hop (0 .. 8) {
            # curl never follows a redirect itself. Validate every resolved next
            # URL before contacting it, including intermediate and same-host hops.
            $self->_allow($url, $args{allowed_hosts});
            my $remaining = $deadline - clock_gettime(CLOCK_MONOTONIC);
            $remaining > 0 or die "$args{label} download timed out\n";
            my $seconds = $remaining < 300 ? $remaining : 300;
            my $retry_seconds = int($remaining) || 1;
            my @command = (
                '/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error',
                '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '15',
                '--max-time', "$seconds", '--max-redirs', '0', '--retry', '3', '--retry-delay', '2',
                '--retry-max-time', "$retry_seconds",
                '--retry-all-errors', '--max-filesize', $args{maximum},
                '--user-agent', $user_agent,
                '--header', 'Accept: application/octet-stream, application/vnd.debian.binary-package;q=0.9, */*;q=0.1',
                '--output', $partial, '--write-out', "%{http_code}\n%{url_effective}\n%{content_type}\n%{redirect_url}",
                '--url', $url,
            );
            my $result = Managed::Process::capture_command(argv => \@command, timeout => $remaining, limit => 16384);
            $result->{status} == 0 or die "$args{label} download failed\n";
            my $next;
            ($status, $effective, $content_type, $next) = split /\n/, $result->{stdout}, 4;
            defined($effective) or die "$args{label} effective URL is invalid\n";
            $self->_allow($effective, $args{allowed_hosts});
            if (defined($status) && $status =~ /\A(?:301|302|303|307|308)\z/) {
                $hop < 8 && defined($next) && length($next)
                    or die "$args{label} redirect limit or invalid redirect\n";
                $self->_allow($next, $args{allowed_hosts});
                $url = $next;
                next;
            }
            last;
        }
        defined $status && $status =~ /\A(?:200|206)\z/ or die "$args{label} download returned an unexpected HTTP status\n";
        defined $effective && length($effective) <= 2048 or die "$args{label} effective URL is invalid\n";
        $self->_allow($effective, $args{allowed_hosts});
        $content_type //= q{};
        $content_type = lc((split /;/, $content_type, 2)[0]);
        if ($args{content_policy} eq 'artifact') {
            $content_type !~ /\A(?:text\/(?:html|plain|xml)|application\/(?:json|xml))\z/
                or die "$args{label} download returned a non-artifact content type\n";
        } elsif ($content_type ne q{} && $content_type !~ /\A(?:application\/(?:octet-stream|vnd\.github\+json|json|yaml|x-yaml)|text\/(?:plain|yaml|x-yaml)|binary\/octet-stream)\z/) {
            die "$args{label} download returned an unsupported metadata content type\n";
        }
        -f $partial && !-l $partial or die "$args{label} download is not a regular file\n";
        my $size = -s $partial;
        defined $size && $size >= $args{minimum} && $size <= $args{maximum}
            or die "$args{label} download size is outside approved bounds\n";
        rename $partial, $args{destination} or die "failed to publish downloaded $args{label}: $!\n";
        1;
    };
    my $error = $@;
    if (!$ok) {
        unlink $partial if -e $partial || -l $partial;
        die $error || "$args{label} download failed\n";
    }
    return $args{destination};
}

1;
