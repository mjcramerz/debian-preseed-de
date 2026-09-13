package Labwc::WorkspaceBroker::Render;
use strict;
use warnings;
use Exporter 'import';
our @EXPORT_OK = qw(clean escape_markup badge empty_frame render picker_page);
sub clean {
    my ($s, $max) = @_;
    $s //= '';
    $s =~ s/[\x00-\x1f\x7f-\x9f\x{202a}-\x{202e}\x{2066}-\x{2069}]/ /g;
    $s =~ s/\s+/ /g;
    $s =~ s/^ | $//g;
    return substr($s, 0, $max // 320);
}
sub escape_markup {
    my ($s) = @_;
    $s =~ s/&/&amp;/g; $s =~ s/</&lt;/g; $s =~ s/>/&gt;/g;
    $s =~ s/"/&quot;/g; $s =~ s/'/&apos;/g;
    return $s;
}
sub badge {
    my ($n) = @_;
    return '' if $n <= 1;
    my $count = $n > 99 ? '99+' : int($n);
    return '<span size="x-small" rise="5000" weight="bold">' . $count . '</span>';
}
sub empty_frame { return { text => '', tooltip => '', class => ['workspace-app', 'empty'] }; }
sub render {
    my ($view, $icons, $cfg) = @_;
    return empty_frame() unless $view->{visible} && @{$view->{groups}};
    if (!$view->{view}{slot}) {
        my $n = scalar @{$view->{groups}};
        return { text => '+' . $n, tooltip => "$n additional application groups on this workspace",
            class => ['workspace-app', 'overflow'] };
    }
    my $g = $view->{groups}[0];
    my @tasks = @{$g->{members}};
    my $n = scalar @tasks;
    my $icon = $icons->lookup($g->{key});
    my @classes = ('workspace-app', $n == 1 ? 'single' : 'multiple', $icon->{class});
    push @classes, 'active' if grep { $_->{state} & 4 } @tasks;
    my $minimized = grep { $_->{state} & 2 } @tasks;
    push @classes, $minimized == $n ? 'minimized' : 'mixed-minimized' if $minimized;
    my @lines = (clean($icon->{name}, 160) . " - $n " . ($n == 1 ? 'window' : 'windows'));
    my $shown = 0;
    for my $t (@tasks) {
        last if $shown >= $cfg->{tooltip_windows};
        push @lines, (($t->{state} & 4) ? "\x{25cf} " : ($t->{state} & 2) ? '_ ' : '  ')
            . clean(length($t->{title}) ? $t->{title} : 'Untitled', 320);
        ++$shown;
    }
    push @lines, '+ ' . ($n - $shown) . ' more windows' if $shown < $n;
    # U+200B keeps an icon-only GtkLabel nonempty without drawing a font glyph.
    # CSS supplies the actual application image; count markup is trusted only.
    return { text => "\x{200b}" . badge($n), tooltip => escape_markup(join("\n", @lines)), class => \@classes };
}
sub picker_page {
    my ($p, $offset, $cfg) = @_;
    my $count = scalar @{$p->{rows}};
    die "invalid picker page\n" if $offset < 0 || $offset >= $count || $offset % 128;
    my $end = $offset + 127; $end = $count - 1 if $end >= $count;
    my @rows;
    for my $i ($offset .. $end) {
        my $r = $p->{rows}[$i];
        my $label = (($r->{state} & 4) ? "\x{25cf} " : ($r->{state} & 2) ? '_ ' : '  ')
            . clean($r->{app_id}, 64) . ' - ' . clean(length($r->{title}) ? $r->{title} : 'Untitled', 160);
        $label .= ' [' . join(', ', map { clean($_, 64) } @{$r->{outputs}}) . ']' if @{$r->{outputs}};
        push @rows, { index => $i, label => $label };
    }
    return { kind => 'picker', token => $p->{token}, count => $count, offset => $offset,
        rows => \@rows, mode => $p->{mode}, lines => $cfg->{picker_lines}, width => $cfg->{picker_width} };
}
1;
