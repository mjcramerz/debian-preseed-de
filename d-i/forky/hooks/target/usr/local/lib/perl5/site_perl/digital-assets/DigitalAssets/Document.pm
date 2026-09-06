package DigitalAssets::Document;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

has context  => ( is => 'ro', required => 1 );
has metadata => ( is => 'ro', required => 1 );

sub to_pdf {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('docx-to-pdf', 'pdf', $input_path);
    $context->command_path('typst');
    $context->run_timed(
        $context->command_path('pandoc'),
        '--from=docx', '--to=pdf', '--pdf-engine=/usr/local/bin/typst',
        "--output=$output", $input_path,
    );
    $context->report_file_output($output, 'PDF');
}

sub to_markdown {
    my ($self, $input_path) = @_;
    $self->_pandoc($input_path, 'docx-to-markdown', 'md', 'gfm', 'Markdown file');
}

sub to_text {
    my ($self, $input_path) = @_;
    $self->_pandoc($input_path, 'docx-to-text', 'txt', 'plain', 'plain-text file');
}

sub to_html {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('docx-to-html', 'html', $input_path);
    $context->run_timed(
        $context->command_path('pandoc'),
        '--from=docx', '--to=html5', '--standalone', "--output=$output", $input_path,
    );
    $context->report_file_output($output, 'HTML file');
}

sub _pandoc {
    my ($self, $input_path, $operation, $extension, $format, $label) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file($operation, $extension, $input_path);
    $context->run_timed(
        $context->command_path('pandoc'),
        '--from=docx', "--to=$format", "--output=$output", $input_path,
    );
    $context->report_file_output($output, $label);
}

1;
