package DigitalAssets::Metadata;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

has context => ( is => 'ro', required => 1 );

sub read {
    my ($self, $input_path) = @_;
    $self->context()->run_timed(
        $self->context()->command_path('exiftool'),
        '-s', '-G1', '-a', '--', $input_path,
    );
}

sub edit {
    my ($self, $input_path, $output_kind) = @_;
    my $context = $self->context();
    my %metadata = (
        Title    => $context->prompt_line('Title (leave blank to preserve): '),
        Author   => $context->prompt_line('Author (leave blank to preserve): '),
        Subject  => $context->prompt_line('Subject (leave blank to preserve): '),
        Keywords => $context->prompt_line('Keywords (leave blank to preserve): '),
    );
    $context->validate_ascii_text('Title', $metadata{Title}, 256);
    $context->validate_ascii_text('Author', $metadata{Author}, 256);
    $context->validate_ascii_text('Subject', $metadata{Subject}, 512);
    $context->validate_ascii_text('Keywords', $metadata{Keywords}, 512);
    grep { length $metadata{$_} } keys %metadata
        or die "labwc-digital-assets-action: provide at least one metadata value to edit\n";

    my $output = $context->prepare_output_file('metadata-edited', $output_kind, $input_path);
    my @command = ($context->command_path('exiftool'), '-o', $output);
    for my $key (qw(Title Author Subject Keywords)) {
        push @command, "-$key=$metadata{$key}" if length $metadata{$key};
    }
    push @command, '--', $input_path;
    $context->run_timed(@command);
    $context->report_file_output($output, 'metadata-edited file');
}

sub remove {
    my ($self, $input_path, $output_kind) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('metadata-removed', $output_kind, $input_path);
    $context->run_timed(
        $context->command_path('exiftool'),
        '-all=', '-o', $output, '--', $input_path,
    );
    $context->report_file_output($output, 'metadata-removed file');
}

1;
