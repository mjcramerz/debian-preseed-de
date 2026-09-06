package Zram::Daemon::Controller;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::Types::MooseLike::Numeric qw(PositiveOrZeroInt);
use Zram::Error qw(fatal);

sub _nonnegative_number {
    my ($value) = @_;
    return !ref($value) && $value =~ /\A(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\z/ ? 1 : 0;
}

sub _optional_nonnegative_number {
    my ($value) = @_;
    return 1 if !defined $value;
    return _nonnegative_number($value);
}

sub _pressure_state {
    my ($value) = @_;
    return defined $value && !ref($value) && $value =~ /\A(?:normal|pressure|emergency)\z/ ? 1 : 0;
}

sub _elapsed {
    my ($now, $then) = @_;
    my $elapsed = $now - $then;
    return $elapsed > 0 ? $elapsed : 0;
}

has pressure_cooldown_seconds => (
    is      => 'ro',
    isa     => PositiveOrZeroInt,
    required => 1,
);

has emergency_cooldown_seconds => (
    is      => 'ro',
    isa     => PositiveOrZeroInt,
    required => 1,
);

has recovery_hysteresis_seconds => (
    is      => 'ro',
    isa     => PositiveOrZeroInt,
    required => 1,
);

has last_state => (
    is      => 'rw',
    isa     => \&_pressure_state,
    default => sub { 'normal' },
);

has last_tuning_state => (
    is      => 'rw',
    isa     => \&_pressure_state,
    default => sub { 'normal' },
);

has last_pass_at => (
    is  => 'rw',
    isa => \&_optional_nonnegative_number,
);

has normal_since => (
    is  => 'rw',
    isa => \&_optional_nonnegative_number,
);

sub _rank {
    my ($self, $state) = @_;
    return 2 if $state eq 'emergency';
    return 1 if $state eq 'pressure';
    return 0;
}

sub _cooldown {
    my ($self, $state) = @_;
    return $self->emergency_cooldown_seconds() if $state eq 'emergency';
    return $self->pressure_cooldown_seconds();
}

sub observe {
    my ($self, $now, $observed_state) = @_;
    _nonnegative_number($now)
        or fatal('invalid zram daemon clock value');
    _pressure_state($observed_state)
        or fatal('invalid zram daemon pressure state');
    my %decision = (
        state => $observed_state,
        tune  => undef,
        run   => 0,
        recovered => 0,
    );
    if ($observed_state eq 'normal') {
        $self->normal_since($now) if !defined $self->normal_since();
        if ($self->last_state() ne 'normal'
            && _elapsed($now, $self->normal_since()) >= $self->recovery_hysteresis_seconds()) {
            $self->last_state('normal');
            $decision{recovered} = 1;
        }
        if ($self->last_state() eq 'normal' && $self->last_tuning_state() ne 'normal') {
            $decision{tune} = 'normal';
        }
        return \%decision;
    }
    $self->normal_since(undef);
    $decision{tune} = $observed_state if $self->last_tuning_state() ne $observed_state;
    my $last = $self->last_pass_at();
    $decision{run} = 1 if !defined $last
        || $self->_rank($observed_state) > $self->_rank($self->last_state())
        || _elapsed($now, $last) >= $self->_cooldown($observed_state);
    return \%decision;
}

sub tuning_applied {
    my ($self, $state) = @_;
    _pressure_state($state)
        or fatal('invalid zram daemon tuning state');
    $self->last_tuning_state($state);
}

sub pass_completed {
    my ($self, $state, $now) = @_;
    _pressure_state($state)
        or fatal('invalid zram daemon completed state');
    _nonnegative_number($now)
        or fatal('invalid zram daemon completion clock value');
    $self->last_state($state);
    $self->last_pass_at($now);
}

1;
