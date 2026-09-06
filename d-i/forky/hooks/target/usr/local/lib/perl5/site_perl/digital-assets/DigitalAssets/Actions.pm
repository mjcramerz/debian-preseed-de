package DigitalAssets::Actions;

use strict;
use warnings;

use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;
use DigitalAssets::Context;
use DigitalAssets::Document;
use DigitalAssets::Image;
use DigitalAssets::Metadata;
use DigitalAssets::PDF;

has context => (
    is      => 'ro',
    lazy    => 1,
    builder => sub { DigitalAssets::Context->new() },
);
has metadata => (
    is      => 'ro',
    lazy    => 1,
    builder => sub {
        my ($self) = @_;
        return DigitalAssets::Metadata->new(context => $self->context());
    },
);
has document => (
    is      => 'ro',
    lazy    => 1,
    builder => sub {
        my ($self) = @_;
        return DigitalAssets::Document->new(context => $self->context(), metadata => $self->metadata());
    },
);
has image => (
    is      => 'ro',
    lazy    => 1,
    builder => sub {
        my ($self) = @_;
        return DigitalAssets::Image->new(context => $self->context(), metadata => $self->metadata());
    },
);
has pdf => (
    is      => 'ro',
    lazy    => 1,
    builder => sub {
        my ($self) = @_;
        return DigitalAssets::PDF->new(context => $self->context(), metadata => $self->metadata());
    },
);

sub run {
    my ($self, $action, @arguments) = @_;
    print "\n=== Digital Assets: $action ===\n\n";
    my $result = eval {
        $self->_dispatch($action, @arguments);
        1;
    };
    my $error = $@;
    eval { $self->context()->cleanup(); 1 };
    die $error if !$result;
    print "\n=== Digital Assets action completed ===\n";
    if (-t STDIN) {
        print 'Press Enter to close this terminal...';
        scalar <STDIN>;
    }
    return 0;
}

sub _one_file {
    my ($self, $action, $kind, @arguments) = @_;
    @arguments == 1
        or die "labwc-digital-assets-action: $action requires one file\n";
    return $self->context()->validate_user_file($kind, $arguments[0]);
}

sub _one_list {
    my ($self, $action, @arguments) = @_;
    @arguments == 1
        or die "labwc-digital-assets-action: $action requires a managed selection list\n";
    return $arguments[0];
}

sub _dispatch {
    my ($self, $action, @arguments) = @_;
    my $document = $self->document();
    my $pdf = $self->pdf();
    my $image = $self->image();
    my $metadata = $self->metadata();

    if ($action eq 'docx-to-pdf') {
        return $document->to_pdf($self->_one_file($action, 'docx', @arguments));
    }
    if ($action eq 'docx-to-markdown') {
        return $document->to_markdown($self->_one_file($action, 'docx', @arguments));
    }
    if ($action eq 'docx-to-text') {
        return $document->to_text($self->_one_file($action, 'docx', @arguments));
    }
    if ($action eq 'docx-to-html') {
        return $document->to_html($self->_one_file($action, 'docx', @arguments));
    }
    if ($action eq 'docx-read-metadata') {
        return $metadata->read($self->_one_file($action, 'docx', @arguments));
    }
    if ($action eq 'docx-edit-metadata') {
        return $metadata->edit($self->_one_file($action, 'docx', @arguments), 'docx');
    }
    if ($action eq 'docx-remove-metadata') {
        return $metadata->remove($self->_one_file($action, 'docx', @arguments), 'docx');
    }

    if ($action eq 'pdf-to-png') {
        return $pdf->to_png($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-to-jpeg') {
        return $pdf->to_jpeg($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-to-docx') {
        return $pdf->to_docx($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-to-text') {
        return $pdf->to_text($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'markdown-to-pdf') {
        return $pdf->markdown_to_pdf($self->_one_file($action, 'markdown', @arguments));
    }
    if ($action eq 'pdf-extract-images') {
        return $pdf->extract_images($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-merge') {
        return $pdf->merge($self->_one_list($action, @arguments));
    }
    if ($action eq 'pdf-burst') {
        return $pdf->burst($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-extract-pages') {
        return $pdf->extract_pages($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-remove-pages') {
        return $pdf->remove_pages($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-rotate-pages') {
        return $pdf->rotate_pages($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-edit-content') {
        return $pdf->edit_content($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-edit-bookmarks') {
        return $pdf->edit_bookmarks($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-edit-qdf') {
        return $pdf->edit_qdf($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-repair') {
        return $pdf->repair($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-inspect') {
        return $pdf->inspect($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-encrypt') {
        return $pdf->encrypt($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-decrypt') {
        return $pdf->decrypt($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-linearize') {
        return $pdf->linearize($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-add-page-numbers') {
        return $pdf->add_page_numbers($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-add-watermark') {
        return $pdf->add_watermark($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-extract-bookmarks') {
        return $pdf->extract_bookmarks($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-read-metadata') {
        return $pdf->read_metadata($self->_one_file($action, 'pdf', @arguments));
    }
    if ($action eq 'pdf-edit-metadata') {
        return $metadata->edit($self->_one_file($action, 'pdf', @arguments), 'pdf');
    }
    if ($action eq 'pdf-remove-metadata') {
        return $metadata->remove($self->_one_file($action, 'pdf', @arguments), 'pdf');
    }

    if ($action eq 'image-to-png') {
        return $image->convert($self->_one_file($action, 'image', @arguments), 'png', $action);
    }
    if ($action eq 'image-to-jpeg') {
        return $image->convert($self->_one_file($action, 'image', @arguments), 'jpg', $action, 90);
    }
    if ($action eq 'image-to-webp') {
        return $image->convert($self->_one_file($action, 'image', @arguments), 'webp', $action, 82);
    }
    if ($action eq 'image-resize') {
        return $image->resize($self->_one_file($action, 'image', @arguments));
    }
    if ($action eq 'image-crop') {
        return $image->crop($self->_one_file($action, 'image', @arguments));
    }
    if ($action eq 'image-rotate') {
        return $image->rotate($self->_one_file($action, 'image', @arguments));
    }
    if ($action eq 'image-flop') {
        return $image->flip($self->_one_file($action, 'image', @arguments), 'flop');
    }
    if ($action eq 'image-flip') {
        return $image->flip($self->_one_file($action, 'image', @arguments), 'flip');
    }
    if ($action eq 'image-grayscale') {
        return $image->grayscale($self->_one_file($action, 'image', @arguments));
    }
    if ($action eq 'image-optimize-png') {
        my $file = $self->_one_file($action, 'image', @arguments);
        $file =~ /\.png\z/i or die "labwc-digital-assets-action: PNG optimization requires a PNG input\n";
        return $image->optimize_png($file);
    }
    if ($action eq 'image-optimize-jpeg') {
        my $file = $self->_one_file($action, 'image', @arguments);
        $file =~ /\.jpe?g\z/i or die "labwc-digital-assets-action: JPEG optimization requires a JPEG input\n";
        return $image->optimize_jpeg($file);
    }
    if ($action eq 'image-create-gif') {
        return $image->create_gif($self->_one_list($action, @arguments));
    }
    if ($action eq 'image-read-metadata') {
        return $metadata->read($self->_one_file($action, 'image', @arguments));
    }
    if ($action eq 'image-edit-metadata') {
        my $file = $self->_one_file($action, 'image', @arguments);
        my ($extension) = $file =~ /\.([A-Za-z0-9]+)\z/;
        return $metadata->edit($file, lc $extension);
    }
    if ($action eq 'image-remove-metadata') {
        my $file = $self->_one_file($action, 'image', @arguments);
        my ($extension) = $file =~ /\.([A-Za-z0-9]+)\z/;
        return $metadata->remove($file, lc $extension);
    }
    die "labwc-digital-assets-action: unsupported Digital Assets action\n";
}

1;
