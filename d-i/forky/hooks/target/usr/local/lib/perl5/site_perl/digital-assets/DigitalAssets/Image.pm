package DigitalAssets::Image;

use strict;
use warnings;

use File::Copy qw(copy);
use File::Basename qw(basename);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

has context  => ( is => 'ro', required => 1 );
has metadata => ( is => 'ro', required => 1 );

sub convert {
    my ($self, $input_path, $extension, $operation, $quality) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file($operation, $extension, $input_path);
    my @command = ($context->command_path('gm'), 'convert', $input_path);
    push @command, '-quality', $quality if defined $quality;
    push @command, $output;
    $context->run_timed(@command);
    $context->report_file_output($output, "converted $extension image");
}

sub resize {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $maximum = $context->prompt_line('Maximum edge in pixels (64-12000): ');
    $maximum =~ /\A[0-9]+\z/ && $maximum >= 64 && $maximum <= 12_000
        or die "labwc-digital-assets-action: maximum edge must be between 64 and 12000\n";
    my $output = $context->prepare_output_file('image-resized', _extension($input_path), $input_path);
    $context->run_timed(
        $context->command_path('gm'), 'convert', $input_path,
        '-resize', "${maximum}x${maximum}>", $output,
    );
    $context->report_file_output($output, 'resized image');
}

sub crop {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $geometry = $context->prompt_line('Crop geometry (WIDTHxHEIGHT+X+Y): ');
    $geometry =~ /\A[1-9][0-9]{0,4}x[1-9][0-9]{0,4}\+[0-9]{1,5}\+[0-9]{1,5}\z/
        or die "labwc-digital-assets-action: crop geometry must look like 1200x800+10+20\n";
    my $output = $context->prepare_output_file('image-cropped', _extension($input_path), $input_path);
    $context->run_timed(
        $context->command_path('gm'), 'convert', $input_path,
        '-crop', $geometry, '+repage', $output,
    );
    $context->report_file_output($output, 'cropped image');
}

sub rotate {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $rotation = $context->prompt_line('Rotation in degrees (90, 180, or 270): ');
    $rotation =~ /\A(?:90|180|270)\z/
        or die "labwc-digital-assets-action: rotation must be 90, 180, or 270\n";
    my $output = $context->prepare_output_file('image-rotated', _extension($input_path), $input_path);
    $context->run_timed($context->command_path('gm'), 'convert', $input_path, '-rotate', $rotation, $output);
    $context->report_file_output($output, 'rotated image');
}

sub flip {
    my ($self, $input_path, $mode) = @_;
    $mode =~ /\A(?:flop|flip)\z/
        or die "labwc-digital-assets-action: unsupported image flip mode\n";
    my $context = $self->context();
    my $output = $context->prepare_output_file("image-$mode", _extension($input_path), $input_path);
    $context->run_timed($context->command_path('gm'), 'convert', $input_path, "-$mode", $output);
    $context->report_file_output($output, 'flipped image');
}

sub grayscale {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('image-grayscale', _extension($input_path), $input_path);
    $context->run_timed($context->command_path('gm'), 'convert', $input_path, '-colorspace', 'Gray', $output);
    $context->report_file_output($output, 'grayscale image');
}

sub optimize_png {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('image-optimized', 'png', $input_path);
    $context->run_timed($context->command_path('optipng'), '-o2', '-strip', 'all', '-out', $output, $input_path);
    $context->report_file_output($output, 'optimized PNG');
}

sub optimize_jpeg {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('image-optimized', 'jpg', $input_path);
    copy($input_path, $output)
        or die "labwc-digital-assets-action: cannot prepare JPEG optimization output: $!\n";
    $context->run_timed($context->command_path('jpegoptim'), '--max=85', '--strip-all', '--overwrite', $output);
    $context->report_file_output($output, 'optimized JPEG');
}

sub create_gif {
    my ($self, $list_path) = @_;
    my $context = $self->context();
    my $files = $context->read_input_list('image', $list_path);
    my $output = $context->prepare_output_file('images-to-gif', 'gif', $list_path);
    $context->run_timed($context->command_path('gm'), 'convert', '-delay', '10', '-loop', '0', @{$files}, $output);
    $context->report_file_output($output, 'animated GIF');
}

sub _extension {
    my ($path) = @_;
    my ($extension) = $path =~ /\.([A-Za-z0-9]+)\z/;
    defined($extension) && length($extension)
        or die "labwc-digital-assets-action: image path has no extension\n";
    return lc $extension;
}

1;
