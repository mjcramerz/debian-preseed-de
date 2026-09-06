package ExternalSoftware::Servicing::Event;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Base qw(Str);

use POSIX qw(strftime);
use ExternalSoftware::Servicing::Atomic;

has directory => (is => 'ro', isa => Str, required => 1);
has sequence  => (is => 'rw', default => sub { 0 });

sub _token {
    my ($self, $label, $value) = @_;
    defined $value && length($value) <= 128
        && ($value eq '-' || $value eq 'unknown' || $value =~ /\A[A-Za-z0-9._:+~-]+\z/)
        or die "$label contains unsupported characters\n";
    return $value;
}

sub emit {
    my ($self, $status, $application, $detail_a, $detail_b) = @_;
    $status =~ /\A(?:checking|downloading|downloaded|applying|updated|failed|download-complete|apply-complete|no-updates)\z/
        or die "unsupported notification event status\n";
    $application =~ /\A(?:all|bitwarden|chatgpt|obsidian|qoredb|zoom|filen|discord|sleek|postman|ledger|tuta)\z/
        or die "unsupported notification event application\n";
    $self->_token('event detail', $detail_a);
    $self->_token('event detail', $detail_b);

    ExternalSoftware::Servicing::Atomic->ensure_root_directory($self->directory(), 0755);
    my $sequence = $self->sequence() + 1;
    $self->sequence($sequence);
    my $name = sprintf('%010d-%010d-%04d.event', time(), $$, $sequence);
    my $path = ExternalSoftware::Servicing::Atomic->assert_child($self->directory(), $name);
    ExternalSoftware::Servicing::Atomic->write_text(
        $path,
        join('|', $status, $application, $detail_a, $detail_b) . "\n",
        0644,
    );
    return $path;
}

1;
