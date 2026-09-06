package ExternalSoftware::Servicing::HTTP;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;

use ExternalSoftware::Servicing::Atomic;

sub _host {
    my ($self, $url) = @_;
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
    for my $key (qw(label url destination minimum maximum allowed_hosts content_policy)) {
        exists $args{$key} or die "missing HTTP download parameter $key\n";
    }
    $args{minimum} =~ /\A[0-9]+\z/ && $args{maximum} =~ /\A[0-9]+\z/
        && $args{minimum} <= $args{maximum}
        or die "invalid HTTP download size bounds\n";
    $args{content_policy} =~ /\A(?:artifact|metadata)\z/
        or die "unsupported HTTP content policy\n";
    my $user_agent = $args{user_agent} // 'debian-installer-managed-software/2.0';
    $user_agent =~ /\A[A-Za-z0-9][A-Za-z0-9 ._+\/-]{0,127}\z/
        or die "invalid HTTP user agent\n";
    ExternalSoftware::Servicing::Atomic->assert_absolute_path('download destination', $args{destination});
    $self->_allow($args{url}, $args{allowed_hosts});

    my $partial = "$args{destination}.part";
    unlink $partial if -e $partial || -l $partial;
    my @command = (
        '/usr/bin/curl', '--fail', '--silent', '--show-error', '--location',
        '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '15',
        '--max-time', '300', '--max-redirs', '8', '--retry', '3', '--retry-delay', '2',
        '--retry-all-errors', '--max-filesize', $args{maximum},
        '--user-agent', $user_agent,
        '--header', 'Accept: application/octet-stream, application/vnd.debian.binary-package;q=0.9, */*;q=0.1',
        '--output', $partial, '--write-out', "%{http_code}\n%{url_effective}\n%{content_type}",
        '--url', $args{url},
    );
    open my $curl, '-|', @command or die "failed to execute curl\n";
    my $metadata = do { local $/; <$curl> // q{} };
    close $curl or die "$args{label} download failed\n";
    my ($status, $effective, $content_type) = split /\n/, $metadata, 3;
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
    return $args{destination};
}

1;
