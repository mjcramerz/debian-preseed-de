package AICopilots::CLI;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use Types::Standard qw(Object);

has runtime => (
    is      => 'ro',
    isa     => Object,
    lazy    => 1,
    builder => sub {
        require AICopilots::Runtime;
        return AICopilots::Runtime->new();
    },
);

sub run {
    my ($self, @argv) = @_;
    if (@argv == 1 && $argv[0] eq '--help') {
        print STDERR <<'EOF';
usage:
  labwc-ai-copilots-action --list-models
  labwc-ai-copilots-action --list-favorite-models
  labwc-ai-copilots-action --list-whisper-models
  labwc-ai-copilots-action --list-model-names <llama|llama-favorite|whisper>
  labwc-ai-copilots-action --resolve-model-name <llama|llama-favorite|whisper> <filename>
  labwc-ai-copilots-action --list-download-models <llama|whisper>
  labwc-ai-copilots-action --resolve-download-model <llama|whisper> <table-row>
  labwc-ai-copilots-action [--run] <action> [arguments...]
EOF
        return 0;
    }
    return $self->runtime()->run(@argv);
}

1;
