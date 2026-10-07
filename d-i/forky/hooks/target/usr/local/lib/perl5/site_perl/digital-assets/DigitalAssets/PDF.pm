package DigitalAssets::PDF;

use strict;
use warnings;

use Cwd qw(abs_path);
use Moo;
use MooX::StrictConstructor;
use MooX::TypeTiny;

has context  => ( is => 'ro', required => 1 );
has metadata => ( is => 'ro', required => 1 );

sub to_png {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $context->pdf_page_count($input_path);
    my $directory = $context->prepare_output_directory('pdf-to-png');
    $context->run_timed($context->command_path('pdftoppm'), '-r', '150', '-png', $input_path, "$directory/page");
    $context->directory_has_file($directory, qr/\Apage-[0-9]+\.png\z/)
        or die "labwc-digital-assets-action: PDF conversion did not create PNG files\n";
    $context->report_directory_output($directory, 'PNG pages');
}

sub to_jpeg {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $context->pdf_page_count($input_path);
    my $directory = $context->prepare_output_directory('pdf-to-jpeg');
    $context->run_timed(
        $context->command_path('pdftoppm'),
        '-r', '150', '-jpeg', '-jpegopt', 'quality=90', $input_path, "$directory/page",
    );
    $context->directory_has_file($directory, qr/\Apage-[0-9]+\.jpg\z/)
        or die "labwc-digital-assets-action: PDF conversion did not create JPEG files\n";
    $context->report_directory_output($directory, 'JPEG pages');
}

sub to_docx {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $context->pdf_page_count($input_path);
    my $output = $context->prepare_output_file('pdf-to-docx', 'docx', $input_path);
    $self->_run_managed_python(
        $self->_pdf_tool_python(),
        'pdf-to-docx.py',
        <<'PYTHON',
from pathlib import Path
from pdf2docx import Converter
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
converter = Converter(str(source))
try:
    converter.convert(str(destination))
finally:
    converter.close()
PYTHON
        $input_path,
        $output,
    );
    $context->report_file_output($output, 'DOCX file');
}

sub to_text {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('pdf-to-text', 'txt', $input_path);
    $context->run_timed($context->command_path('pdftotext'), '-layout', $input_path, $output);
    $context->report_file_output($output, 'plain-text file');
}

sub markdown_to_pdf {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('markdown-to-pdf', 'pdf', $input_path);
    $context->command_path('typst');
    $context->run_timed(
        $context->command_path('pandoc'),
        '--from=markdown', '--to=pdf', '--pdf-engine=/usr/local/bin/typst',
        "--output=$output", $input_path,
    );
    $context->report_file_output($output, 'PDF');
}

sub extract_images {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $context->pdf_page_count($input_path);
    my $directory = $context->prepare_output_directory('pdf-images');
    $context->run_timed($context->command_path('pdfimages'), '-all', $input_path, "$directory/image");
    $context->directory_has_file($directory, qr/\Aimage-/)
        or die "labwc-digital-assets-action: PDF has no extractable images\n";
    $context->report_directory_output($directory, 'extracted PDF images');
}

sub merge {
    my ($self, $list_path) = @_;
    my $context = $self->context();
    my $files = $context->read_input_list('pdf', $list_path);
    my $output = $context->prepare_output_file('pdf-merged', 'pdf', $context->home() . '/merged.pdf');
    my $argument_file = $context->create_private_file(
        'qpdf-merge.args',
        join("\n", '--empty', '--pages', @{$files}, '--', $output) . "\n",
    );
    $context->run_timed($context->command_path('qpdf'), "\@$argument_file");
    $context->report_file_output($output, 'merged PDF');
}

sub burst {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $context->pdf_page_count($input_path);
    my $directory = $context->prepare_output_directory('pdf-pages');
    $context->run_timed($context->command_path('pdfseparate'), $input_path, "$directory/page-%03d.pdf");
    $context->directory_has_file($directory, qr/\Apage-[0-9]+\.pdf\z/)
        or die "labwc-digital-assets-action: PDF split did not create page files\n";
    $context->report_directory_output($directory, 'PDF page files');
}

sub extract_pages {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $pages = $context->prompt_page_range($context->pdf_page_count($input_path));
    my $output = $context->prepare_output_file('pdf-extracted-pages', 'pdf', $input_path);
    $context->run_timed(
        $context->command_path('qpdf'),
        '--empty', '--pages', $input_path, $pages, '--', $output,
    );
    $context->report_file_output($output, 'extracted PDF pages');
}

sub remove_pages {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $pages = $context->prompt_page_range($context->pdf_page_count($input_path));
    my $output = $context->prepare_output_file('pdf-removed-pages', 'pdf', $input_path);
    $context->run_timed(
        $context->command_path('pdfcpu'),
        'pages', 'remove', $input_path, $output, '--pages', $pages,
    );
    $context->report_file_output($output, 'PDF with selected pages removed');
}

sub rotate_pages {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $total = $context->pdf_page_count($input_path);
    my $rotation = $context->prompt_line('Rotation in degrees (90, 180, or 270): ');
    $rotation =~ /\A(?:90|180|270)\z/
        or die "labwc-digital-assets-action: rotation must be 90, 180, or 270\n";
    my $pages = $context->prompt_line("Pages to rotate (leave blank for all $total pages): ");
    $context->validate_page_range($pages, $total) if length $pages;
    my $output = $context->prepare_output_file('pdf-rotated', 'pdf', $input_path);
    my @command = ($context->command_path('pdfcpu'), 'rotate', $input_path, $rotation, $output);
    push @command, '--pages', $pages if length $pages;
    $context->run_timed(@command);
    $context->report_file_output($output, 'rotated PDF');
}

sub edit_content {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $context->pdf_page_count($input_path);
    my $editable = $context->create_private_file('edit.md', q{});
    print "Extracting a reflowable Markdown working copy. Original page geometry, forms, signatures, and annotations are not preserved.\n";
    $self->_run_managed_python(
        $self->_pdf_tool_python(),
        'pdf-to-markdown.py',
        <<'PYTHON',
from pathlib import Path
import pymupdf4llm
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
destination.write_text(pymupdf4llm.to_markdown(str(source)), encoding="utf-8")
PYTHON
        $input_path,
        $editable,
    );
    -s $editable or die "labwc-digital-assets-action: PDF did not yield editable Markdown text\n";
    print "Edit the Markdown in FocusWriter, save, then close FocusWriter to compile a new PDF.\n";
    $context->run_interactive(
        {
            GDK_BACKEND    => 'wayland',
            QT_QPA_PLATFORM => 'wayland',
            SDL_VIDEODRIVER => 'wayland',
        },
        $context->command_path('focuswriter'),
        $editable,
    );
    -s $editable or die "labwc-digital-assets-action: edited Markdown file is empty\n";
    my $output = $context->prepare_output_file('pdf-reflowed-edit', 'pdf', $input_path);
    $context->command_path('typst');
    $context->run_timed(
        $context->command_path('pandoc'),
        '--from=markdown', '--to=pdf', '--pdf-engine=/usr/local/bin/typst',
        "--output=$output", $editable,
    );
    $context->report_file_output($output, 'reflowed edited PDF');
}

sub edit_bookmarks {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $context->pdf_page_count($input_path);
    my $bookmark_json = $context->work_directory() . '/bookmarks.json';
    $context->run_timed($context->command_path('pdfcpu'), 'bookmarks', 'export', $input_path, $bookmark_json);
    -f $bookmark_json && !-l $bookmark_json && -s $bookmark_json
        or die "labwc-digital-assets-action: pdfcpu did not produce a valid bookmarks working file\n";
    chmod 0600, $bookmark_json or die "labwc-digital-assets-action: cannot secure bookmarks working file: $!\n";
    print "Edit bookmarks.json in Nano, save, then exit Nano to write a new PDF with the edited bookmark tree.\n";
    $context->run_interactive({}, $context->command_path('nano'), $bookmark_json);
    -f $bookmark_json && !-l $bookmark_json && -s $bookmark_json
        or die "labwc-digital-assets-action: edited bookmarks working file is invalid\n";
    my $output = $context->prepare_output_file('pdf-bookmarks-edited', 'pdf', $input_path);
    $context->run_timed(
        $context->command_path('pdfcpu'),
        'bookmarks', 'import', $input_path, $bookmark_json, $output, '--replace',
    );
    $context->run_timed($context->command_path('pdfcpu'), 'validate', $output);
    $context->report_file_output($output, 'PDF with edited bookmarks');
}

sub edit_qdf {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $context->pdf_page_count($input_path);
    my $type = $context->prompt_line('Edit type (uri or text): ');
    $type =~ /\A(?:uri|text)\z/
        or die "labwc-digital-assets-action: edit type must be uri or text\n";
    my $old = $context->prompt_line('Exact old value: ');
    my $new = $context->prompt_line('Exact replacement value: ');
    $context->validate_ascii_text('old value', $old, 512);
    $context->validate_ascii_text('replacement value', $new, 512);
    length($old) && $old ne $new
        or die "labwc-digital-assets-action: QDF replacement values are invalid\n";
    if ($type eq 'uri') {
        for my $value ($old, $new) {
            $value =~ m{\A(?:https?://|mailto:)} && $value !~ /[\s<>()]/
                or die "labwc-digital-assets-action: URI edits require safe http(s) or mailto values\n";
        }
    }
    my $qdf = $context->work_directory() . '/editable.qdf.pdf';
    my $output = $context->prepare_output_file('pdf-qdf-edited', 'pdf', $input_path);
    my $qpdf = $context->command_path('qpdf');
    $context->run_timed($qpdf, '--qdf', '--object-streams=disable', $input_path, $qdf);
    $self->_run_managed_python(
        $self->_system_python(),
        'replace-qdf.py',
        <<'PYTHON',
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = sys.argv[2].encode("ascii")
new = sys.argv[3].encode("ascii")
data = path.read_bytes()
count = data.count(old)
if count == 0:
    raise SystemExit("the exact value was not found in QDF data")
if count > 200:
    raise SystemExit("the exact value occurs too many times to replace safely")
path.write_bytes(data.replace(old, new))
print(f"Replaced {count} literal QDF occurrence(s).")
PYTHON
        $qdf,
        $old,
        $new,
    );
    $context->run_timed($context->command_path('fix-qdf'), $qdf);
    $context->run_timed($qpdf, $qdf, $output);
    $context->run_timed($qpdf, '--check', $output);
    print "Warning: QDF editing invalidates signatures and does not preserve input encryption.\n";
    $context->report_file_output($output, 'QDF-edited PDF');
}

sub repair {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('pdf-repaired', 'pdf', $input_path);
    my $qpdf = $context->command_path('qpdf');
    $context->run_timed($qpdf, '--warning-exit-0', '--recompress-flate', $input_path, $output);
    $context->run_timed($qpdf, '--check', $output);
    $context->report_file_output($output, 'repaired PDF');
}

sub inspect {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    print "=== PDF information ===\n\n";
    $context->run_timed($context->command_path('pdfinfo'), $input_path);
    print "\n=== QPDF structural check ===\n";
    my $qpdf = $context->command_path('qpdf');
    $context->run_timed($qpdf, '--check', $input_path);
    print "\n=== Encryption ===\n";
    $context->run_timed_allow_failure($qpdf, '--show-encryption', $input_path);
    print "\n=== PDFCPU information ===\n";
    $context->run_timed($context->command_path('pdfcpu'), 'info', $input_path);
}

sub encrypt {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $user = $context->validate_password('document password', $context->prompt_secret('Document password: '));
    $context->prompt_secret('Confirm document password: ') eq $user
        or die "labwc-digital-assets-action: document passwords do not match\n";
    my $owner = $context->validate_password('owner password', $context->prompt_secret('Owner password: '));
    $context->prompt_secret('Confirm owner password: ') eq $owner
        or die "labwc-digital-assets-action: owner passwords do not match\n";
    my $output = $context->prepare_output_file('pdf-encrypted', 'pdf', $input_path);
    my $arguments = $context->create_private_file(
        'qpdf-encrypt.args',
        join("\n", '--encrypt', $user, $owner, '256', '--', $input_path, $output) . "\n",
    );
    my $qpdf = $context->command_path('qpdf');
    $context->run_timed($qpdf, "\@$arguments");
    $context->run_timed($qpdf, '--check', $output);
    $context->report_file_output($output, 'encrypted PDF');
}

sub decrypt {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $password = $context->validate_password('PDF password', $context->prompt_secret('PDF password: '));
    my $password_file = $context->create_private_file('pdf-password', "$password\n");
    my $output = $context->prepare_output_file('pdf-decrypted', 'pdf', $input_path);
    my $qpdf = $context->command_path('qpdf');
    $context->run_timed($qpdf, "--password-file=$password_file", '--decrypt', $input_path, $output);
    $context->run_timed($qpdf, '--check', $output);
    $context->report_file_output($output, 'decrypted PDF');
}

sub linearize {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('pdf-linearized', 'pdf', $input_path);
    my $qpdf = $context->command_path('qpdf');
    $context->run_timed($qpdf, '--linearize', $input_path, $output);
    $context->run_timed($qpdf, '--check', $output);
    $context->report_file_output($output, 'linearized PDF');
}

sub add_page_numbers {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('pdf-page-numbers', 'pdf', $input_path);
    $context->run_timed(
        $context->command_path('pdfcpu'),
        'stamp', 'add', '--mode', 'text', '--',
        'Page %p of %P', 'scale:1.0 abs, pos:bc, rot:0', $input_path, $output,
    );
    $context->report_file_output($output, 'page-numbered PDF');
}

sub add_watermark {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $text = $context->validate_ascii_text('watermark text', $context->prompt_line('Watermark text: '), 80);
    length($text) or die "labwc-digital-assets-action: watermark text cannot be empty\n";
    my $output = $context->prepare_output_file('pdf-watermarked', 'pdf', $input_path);
    $context->run_timed(
        $context->command_path('pdfcpu'),
        'watermark', 'add', '--mode', 'text', '--',
        $text, 'scale:0.5 rel, pos:c, rot:45, opacity:0.3', $input_path, $output,
    );
    $context->report_file_output($output, 'watermarked PDF');
}

sub extract_bookmarks {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    my $output = $context->prepare_output_file('pdf-bookmarks', 'json', $input_path);
    $context->run_timed($context->command_path('pdfcpu'), 'bookmarks', 'export', $input_path, $output);
    $context->report_file_output($output, 'PDF bookmarks JSON');
}

sub read_metadata {
    my ($self, $input_path) = @_;
    my $context = $self->context();
    $self->metadata()->read($input_path);
    print "\n=== PDF document properties ===\n";
    $context->run_timed_allow_failure($context->command_path('pdfcpu'), 'properties', 'list', $input_path);
}

sub _pdf_tool_python {
    my ($self) = @_;
    my $path = '/usr/local/lib/digital-assets/pipx/venvs/pdf2docx/bin/python';
    my $resolved = abs_path($path);
    defined($resolved)
        && $resolved =~ m{\A/usr/bin/python3(?:\.[0-9]+)?\z}
        && -f $resolved
        && -x $resolved
        or die "labwc-digital-assets-action: managed pdf2docx/pymupdf4llm environment is unavailable\n";
    return $path;
}

sub _system_python {
    my ($self) = @_;
    my $path = '/usr/bin/python3';
    my $resolved = abs_path($path);
    defined($resolved)
        && $resolved =~ m{\A/usr/bin/python3(?:\.[0-9]+)?\z}
        && -f $resolved
        && -x $resolved
        or die "labwc-digital-assets-action: system Python is unavailable\n";
    return $path;
}

sub _run_managed_python {
    my ($self, $python, $name, $script, @arguments) = @_;
    my $context = $self->context();
    my $script_path = $context->create_private_file($name, $script);
    $context->run_timed(
        $context->command_path('env'),
        '-i',
        'HOME=' . $context->home(),
        'PATH=/usr/local/bin:/usr/bin:/bin',
        'TMPDIR=' . $context->work_directory(),
        'PYTHONNOUSERSITE=1',
        'PYTHONDONTWRITEBYTECODE=1',
        $python,
        '-I',
        '-B',
        $script_path,
        @arguments,
    );
}

1;
