package Labwc::WorkspaceBroker::State;
use strict;
use warnings;
use Moo;
use MooX::StrictConstructor;
use Types::Standard qw(HashRef);
use Labwc::WorkspaceBroker::Policy ();

has config => (is => 'ro', isa => HashRef, required => 1);
has _model => (is => 'ro', isa => HashRef, init_arg => undef, lazy => 1,
    default => sub { Labwc::WorkspaceBroker::Policy::new_model($_[0]->config->{group_slots}) });

# Explicit entry points only: no public attribute setters, trigger cascades,
# driver-owned semantic state, or persisted workspace guesses.
sub commit { my ($self, $atoms, $now) = @_; Labwc::WorkspaceBroker::Policy::apply_batch($self->_model, $atoms, $now); }
sub view { my $self = shift; return Labwc::WorkspaceBroker::Policy::view_for($self->_model, @_); }
sub action { my $self = shift; return Labwc::WorkspaceBroker::Policy::action_for($self->_model, @_); }
sub choose { my $self = shift; return Labwc::WorkspaceBroker::Policy::picker_choose($self->_model, @_); }
sub picker_valid { my $self = shift; return Labwc::WorkspaceBroker::Policy::picker_valid($self->_model, @_); }
sub diagnose { return Labwc::WorkspaceBroker::Policy::diagnose($_[0]->_model); }
sub output_names { return { %{$_[0]->_model->{outputs}} }; }
1;
