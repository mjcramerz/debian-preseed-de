package DigitalAssets::Catalog;

use strict;
use warnings;

use Exporter qw(import);

our @EXPORT_OK = qw(action_entries action_ids menu_catalog_lines);

my @ENTRIES = (
    {
        category => 'docx',
        action   => 'docx-to-pdf',
        selector => 'docx',
        label    => 'Convert DOCX to PDF',
        prompt   => 'DOCX to PDF',
    },
    {
        category => 'docx',
        action   => 'docx-to-markdown',
        selector => 'docx',
        label    => 'Convert DOCX to Markdown',
        prompt   => 'DOCX to Markdown',
    },
    {
        category => 'docx',
        action   => 'docx-to-text',
        selector => 'docx',
        label    => 'Convert DOCX to Plain Text',
        prompt   => 'DOCX to Plain Text',
    },
    {
        category => 'docx',
        action   => 'docx-to-html',
        selector => 'docx',
        label    => 'Convert DOCX to HTML',
        prompt   => 'DOCX to HTML',
    },
    {
        category => 'docx',
        action   => 'docx-read-metadata',
        selector => 'docx',
        label    => 'Read Metadata',
        prompt   => 'DOCX metadata',
    },
    {
        category => 'docx',
        action   => 'docx-edit-metadata',
        selector => 'docx',
        label    => 'Edit Metadata',
        prompt   => 'DOCX metadata to edit',
    },
    {
        category => 'docx',
        action   => 'docx-remove-metadata',
        selector => 'docx',
        label    => 'Remove All Metadata',
        prompt   => 'DOCX metadata to remove',
    },
    {
        category => 'pdf',
        action   => 'pdf-to-png',
        selector => 'pdf',
        label    => 'Convert PDF to PNG',
        prompt   => 'PDF to PNG',
    },
    {
        category => 'pdf',
        action   => 'pdf-to-jpeg',
        selector => 'pdf',
        label    => 'Convert PDF to JPEG',
        prompt   => 'PDF to JPEG',
    },
    {
        category => 'pdf',
        action   => 'pdf-to-docx',
        selector => 'pdf',
        label    => 'Convert PDF to DOCX',
        prompt   => 'PDF to DOCX',
    },
    {
        category => 'pdf',
        action   => 'pdf-to-text',
        selector => 'pdf',
        label    => 'Convert PDF to Plain Text',
        prompt   => 'PDF to Plain Text',
    },
    {
        category => 'pdf',
        action   => 'markdown-to-pdf',
        selector => 'markdown',
        label    => 'Convert Markdown to PDF',
        prompt   => 'Markdown to PDF',
    },
    {
        category => 'pdf',
        action   => 'pdf-extract-images',
        selector => 'pdf',
        label    => 'Extract Images from PDF',
        prompt   => 'Extract PDF images',
    },
    {
        category => 'pdf',
        action   => 'pdf-merge',
        selector => 'pdf-list',
        label    => q{Merge Multiple PDF's},
        prompt   => 'Select PDFs to merge',
    },
    {
        category => 'pdf',
        action   => 'pdf-burst',
        selector => 'pdf',
        label    => 'Split PDF (Burst to Pages)',
        prompt   => 'Burst PDF to pages',
    },
    {
        category => 'pdf',
        action   => 'pdf-extract-pages',
        selector => 'pdf',
        label    => 'Extract Specific Pages',
        prompt   => 'Extract PDF pages',
    },
    {
        category => 'pdf',
        action   => 'pdf-remove-pages',
        selector => 'pdf',
        label    => 'Remove Specific Pages',
        prompt   => 'Remove PDF pages',
    },
    {
        category => 'pdf',
        action   => 'pdf-rotate-pages',
        selector => 'pdf',
        label    => 'Rotate Pages',
        prompt   => 'Rotate PDF pages',
    },
    {
        category => 'pdf',
        action   => 'pdf-edit-content',
        selector => 'pdf',
        label    => 'Edit PDF Content',
        prompt   => 'Edit PDF content',
    },
    {
        category => 'pdf',
        action   => 'pdf-edit-bookmarks',
        selector => 'pdf',
        label    => 'Edit PDF Bookmarks',
        prompt   => 'Edit PDF bookmarks',
    },
    {
        category => 'pdf',
        action   => 'pdf-edit-qdf',
        selector => 'pdf',
        label    => 'Edit Hyperlinks and Typos',
        prompt   => 'Edit PDF hyperlinks or text',
    },
    {
        category => 'pdf',
        action   => 'pdf-repair',
        selector => 'pdf',
        label    => 'Clean / Repair Corrupted PDF',
        prompt   => 'Repair PDF',
    },
    {
        category => 'pdf',
        action   => 'pdf-inspect',
        selector => 'pdf',
        label    => 'Inspect PDF Structure',
        prompt   => 'Inspect PDF structure',
    },
    {
        category => 'pdf',
        action   => 'pdf-encrypt',
        selector => 'pdf',
        label    => 'Encrypt / Password Protect',
        prompt   => 'Encrypt PDF',
    },
    {
        category => 'pdf',
        action   => 'pdf-decrypt',
        selector => 'pdf',
        label    => 'Decrypt / Remove Password',
        prompt   => 'Decrypt PDF',
    },
    {
        category => 'pdf',
        action   => 'pdf-linearize',
        selector => 'pdf',
        label    => 'Linearize (Optimize size for Web)',
        prompt   => 'Linearize PDF',
    },
    {
        category => 'pdf',
        action   => 'pdf-add-page-numbers',
        selector => 'pdf',
        label    => 'Add Page Numbers',
        prompt   => 'Add PDF page numbers',
    },
    {
        category => 'pdf',
        action   => 'pdf-add-watermark',
        selector => 'pdf',
        label    => 'Add Text Watermark',
        prompt   => 'Add PDF watermark',
    },
    {
        category => 'pdf',
        action   => 'pdf-extract-bookmarks',
        selector => 'pdf',
        label    => 'Extract TOC / Bookmarks',
        prompt   => 'Extract PDF bookmarks',
    },
    {
        category => 'pdf',
        action   => 'pdf-read-metadata',
        selector => 'pdf',
        label    => 'Read Metadata',
        prompt   => 'PDF metadata',
    },
    {
        category => 'pdf',
        action   => 'pdf-edit-metadata',
        selector => 'pdf',
        label    => 'Edit Metadata',
        prompt   => 'PDF metadata to edit',
    },
    {
        category => 'pdf',
        action   => 'pdf-remove-metadata',
        selector => 'pdf',
        label    => 'Remove All Metadata',
        prompt   => 'PDF metadata to remove',
    },
    {
        category => 'image',
        action   => 'image-to-png',
        selector => 'image',
        label    => 'Convert Any Image to PNG',
        prompt   => 'Image to PNG',
    },
    {
        category => 'image',
        action   => 'image-to-jpeg',
        selector => 'image',
        label    => 'Convert Any Image to JPEG',
        prompt   => 'Image to JPEG',
    },
    {
        category => 'image',
        action   => 'image-to-webp',
        selector => 'image',
        label    => 'Convert Image to WebP',
        prompt   => 'Image to WebP',
    },
    {
        category => 'image',
        action   => 'image-resize',
        selector => 'image',
        label    => 'Resize Image',
        prompt   => 'Resize image',
    },
    {
        category => 'image',
        action   => 'image-crop',
        selector => 'image',
        label    => 'Crop Image',
        prompt   => 'Crop image',
    },
    {
        category => 'image',
        action   => 'image-rotate',
        selector => 'image',
        label    => 'Rotate Image',
        prompt   => 'Rotate image',
    },
    {
        category => 'image',
        action   => 'image-flop',
        selector => 'image',
        label    => 'Flip (Horizontal)',
        prompt   => 'Flip image horizontally',
    },
    {
        category => 'image',
        action   => 'image-flip',
        selector => 'image',
        label    => 'Flip (Vertical)',
        prompt   => 'Flip image vertically',
    },
    {
        category => 'image',
        action   => 'image-grayscale',
        selector => 'image',
        label    => 'Convert to Grayscale',
        prompt   => 'Convert image to grayscale',
    },
    {
        category => 'image',
        action   => 'image-optimize-png',
        selector => 'image',
        label    => 'Compress / Optimize PNG',
        prompt   => 'Optimize PNG',
    },
    {
        category => 'image',
        action   => 'image-optimize-jpeg',
        selector => 'image',
        label    => 'Compress / Optimize JPEG',
        prompt   => 'Optimize JPEG',
    },
    {
        category => 'image',
        action   => 'image-create-gif',
        selector => 'image-list',
        label    => 'Create GIF from Images',
        prompt   => 'Select images for GIF',
    },
    {
        category => 'image',
        action   => 'image-read-metadata',
        selector => 'image',
        label    => 'Read Image Metadata',
        prompt   => 'Image metadata',
    },
    {
        category => 'image',
        action   => 'image-edit-metadata',
        selector => 'image',
        label    => 'Edit Image Metadata',
        prompt   => 'Image metadata to edit',
    },
    {
        category => 'image',
        action   => 'image-remove-metadata',
        selector => 'image',
        label    => 'Remove All Metadata',
        prompt   => 'Image metadata to remove',
    },
);

my $validated = 0;

sub _validate_catalog {
    return if $validated;

    my %actions;
    my %labels;
    for my $entry (@ENTRIES) {
        ref($entry) eq 'HASH'
            or die "Digital Assets catalog entry must be a hash reference\n";

        for my $field (qw(category action selector label prompt)) {
            defined($entry->{$field}) && length($entry->{$field})
                or die "Digital Assets catalog entry is missing $field\n";
            $entry->{$field} !~ /[\t\r\n]/
                or die "Digital Assets catalog entry contains an unsafe $field\n";
        }

        $entry->{category} =~ /\A(?:docx|pdf|image)\z/
            or die "Digital Assets catalog entry has an unsupported category\n";
        $entry->{action} =~ /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/
            or die "Digital Assets catalog entry has an unsafe action\n";
        $entry->{selector} =~ /\A(?:docx|pdf|image|markdown|pdf-list|image-list)\z/
            or die "Digital Assets catalog entry has an unsupported selector\n";
        !$actions{$entry->{action}}++
            or die "Digital Assets catalog contains a duplicate action\n";
        !$labels{"$entry->{category}\0$entry->{label}"}++
            or die "Digital Assets catalog contains a duplicate category label\n";
    }

    $validated = 1;
    return;
}

sub action_entries {
    _validate_catalog();
    return map { { %$_ } } @ENTRIES;
}

sub action_ids {
    _validate_catalog();
    return map { $_->{action} } @ENTRIES;
}

sub menu_catalog_lines {
    _validate_catalog();
    return map {
        join "\t", $_->{category}, $_->{action}, $_->{selector}, $_->{label}, $_->{prompt};
    } @ENTRIES;
}

1;
