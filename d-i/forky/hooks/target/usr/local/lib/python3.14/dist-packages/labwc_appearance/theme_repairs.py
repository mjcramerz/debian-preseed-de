"""Explicit repairs for missing images in the pinned, precompiled GTK CSS.

These small vector images use the selected theme's native colors. No Sass,
image renderer, upstream installer or software compilation is required. Every
other URL still passes the complete local/resource reference check.
"""
from __future__ import annotations
import re
from .themes import Theme

REPAIRED_FAMILIES = frozenset(('chromeos', 'matcha', 'qogir', 'vimix'))


def _svg(width: int, height: int, drawing: str) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">{drawing}</svg>\n').encode('ascii')


def repair(files: dict[str, bytes], theme: Theme) -> dict[str, bytes]:
    if theme.family not in REPAIRED_FAMILIES:
        return files
    result = dict(files)
    for version in ('3.0', '4.0'):
        directory = 'gtk-' + version + '/'
        for filename in ('gtk.css', 'gtk-dark.css'):
            path = directory + filename
            css = result[path].decode('utf-8')
            replacements = {}
            if theme.family == 'chromeos':
                # The disabled handle is neutral in both color variants. The
                # colored handles already contain their intended native color.
                for axis in ('horz', 'vert'):
                    for side in ('before', 'after'):
                        for scale in ('', '@2'):
                            prefix = 'assets/scale-' + axis + '-marks-' + side + '-slider-disabled'
                            replacements[prefix + '-pink' + scale + '.png'] = (
                                prefix + ('-dark' if theme.dark else '') + scale + '.png')
                for accent in ('pink', 'cyan'):
                    for scale in ('', '@2'):
                        replacements['assets/scale-slider-dark-' + accent + scale + '.png'] = (
                            'assets/scale-slider-' + accent + scale + '.png')
            elif theme.family == 'qogir':
                for scale in ('', '@2'):
                    replacements['assets/scalable/check-symbolic' + scale + '.svg'] = (
                        'assets/check-symbolic' + scale + '.svg')
            if theme.family in ('matcha', 'qogir'):
                old = 'assets/thumbnail-frame.png'
                replacements[old] = 'assets/labwc-thumbnail-frame.svg'
                if old in css:
                    result[directory + replacements[old]] = _svg(12, 12,
                        '<rect x="3.5" y="3.5" width="5" height="5" fill="none" '
                        'stroke="#000000" stroke-opacity="0.24"/>'
                        '<path d="M4 10h4" stroke="#000000" stroke-opacity="0.12"/>')
            if theme.family == 'qogir':
                pattern = r'assets/titlebutton-(close|maximize|minimize)(-active|-backdrop|-hover)?(-dark)?(@2)?\.png'
                for match in re.finditer(pattern, css):
                    old = match[0]
                    action, state = match[1], match[2] or ''
                    new = old.removesuffix('.png') + '.svg'
                    replacements[old] = new
                    color = theme.colors.muted if state == '-backdrop' else theme.foreground
                    background = ''
                    if state in ('-active', '-hover'):
                        p = theme.colors
                        color = p.selection_text
                        background = '<circle cx="8" cy="8" r="8" fill="' + p.accent + '"/>'
                    glyph = {'close': 'M5 5l6 6m0-6-6 6',
                             'maximize': 'M5 5h6v6H5z',
                             'minimize': 'M5 8h6'}[action]
                    result[directory + new] = _svg(16, 16, background +
                        '<path d="' + glyph + '" fill="none" stroke="' + color +
                        '" stroke-width="1.5" stroke-linecap="round"/>')
            if theme.family in ('matcha', 'vimix'):
                pattern = (r'assets/(text-select-start|text-select-end|slider-horz-scale-has-marks-above)'
                           r'(-active|-hover)?(-dark)?(@2)?\.png')
                for match in re.finditer(pattern, css):
                    old = match[0]
                    new = old.removesuffix('.png') + '.svg'
                    replacements[old] = new
                    shape, state = match[1], match[2] or ''
                    p = theme.colors
                    color = p.accent_pressed if state == '-active' else p.accent_hover if state == '-hover' else p.accent
                    drawing = ('M12 0l9 12a11 11 0 1 1-18 0z' if shape.startswith('slider-') else
                               'M12 0v18a12 12 0 1 1-12-12z' if shape.endswith('start') else
                               'M12 0v18a12 12 0 1 0 12-12z')
                    result[directory + new] = _svg(24, 30, '<path d="' + drawing + '" fill="' + color + '"/>')
                if theme.family == 'matcha':
                    for scale in ('', '@2'):
                        old = 'assets/scalable/check-symbolic' + scale + '.svg'
                        if old in css:
                            result[directory + old] = _svg(16, 16,
                                '<path d="M3 8l3 3 7-7" fill="none" stroke="#ffffff" '
                                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
            for old, new in replacements.items():
                if old not in css:
                    continue
                if directory + old in files:
                    raise ValueError('pinned missing-image repair would replace an existing vendor image')
                if directory + new not in result:
                    raise ValueError('pinned missing-image repair has no replacement asset')
                css = css.replace(old, new)
            result[path] = css.encode('utf-8')
    return result
