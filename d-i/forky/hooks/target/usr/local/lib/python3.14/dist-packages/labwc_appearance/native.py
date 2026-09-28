"""Allowlisted native files and color-only profile/reset transformations."""
from __future__ import annotations
import re
from pathlib import Path
from .catalog import palette, DEFAULT_PROFILE
from .editors import css, edit_ini, edit_flat, ini_values, flat_values

FILES = {
 'fuzzel': ('fuzzel/base.ini', 'fuzzel/fuzzel.ini', 'fuzzel/menu.ini', 'fuzzel/computer-management.ini'),
 'waybar': ('waybar/style.css',),
 'dock': ('crystal-dock/labwc/appearance.conf',),
 'terminal': ('foot/foot.ini', 'kitty/kitty.conf'),
 'mode': ('gtk-3.0/settings.ini', 'gtk-4.0/settings.ini', 'qt6ct/qt6ct.conf',
          'qt6ct/colors/labwc-appearance.conf', 'labwc/themerc-override'),
}
GREETER_FILES = ('gtkgreet.css', 'gtkgreet-power.css')
VARIANTS = ('', '.internal', '.external')
OPTIONAL = 'qt6ct/colors/labwc-appearance.conf'
FUZZEL_KEYS = ('background', 'text', 'prompt', 'placeholder', 'input', 'match', 'selection',
               'selection-text', 'selection-match', 'counter', 'border')
FOOT_KEYS = ('foreground', 'background', 'selection-foreground', 'selection-background', 'urls',
             *(f'regular{i}' for i in range(8)), *(f'bright{i}' for i in range(8)))
KITTY_KEYS = ('foreground', 'background', 'selection_foreground', 'selection_background',
              'cursor', 'cursor_text_color', 'url_color', *(f'color{i}' for i in range(16)))
DOCK_KEYS = ('backgroundColor', 'backgroundColor2D', 'backgroundColorMetal2D', 'borderColor',
             'borderColorMetal2D', 'activeIndicatorColor', 'activeIndicatorColor2D',
             'activeIndicatorColorMetal2D', 'inactiveIndicatorColor',
             'inactiveIndicatorColor2D', 'inactiveIndicatorColorMetal2D')


def user_paths() -> set[str]:
    return {'.config/' + path + variant for paths in FILES.values() for path in paths
            for variant in VARIANTS if path != OPTIONAL or not variant}


def identify(path: str) -> tuple[str, str]:
    for component, paths in FILES.items():
        for base in paths:
            if path in tuple('.config/' + base + variant for variant in VARIANTS):
                return component, base
    raise ValueError('path is not an appearance-managed native file')


def _ini(text, baseline, values, reset):
    original = ini_values(baseline)
    if reset:
        values = {key: original.get(key) for key in values}
    result = edit_ini(text, values)
    if reset:
        # Do not leave artificial empty light-theme sections after reset.
        original_sections = {section for section, _ in original}
        for section, _ in values:
            if section and section not in original_sections:
                result = re.sub(r'(?m)^\[' + re.escape(section) + r'\]\n\s*(?=\[|\Z)', '', result)
    return result


def qt_palette(p) -> str:
    # QPalette roles 0..21, including Qt 6.6 Accent. Native qt6ct QColor ARGB.
    colors = [p.foreground, p.surface, p.foreground, p.muted, p.border, p.border,
              p.foreground, p.selection_text, p.foreground, p.background, p.background,
              p.background, p.accent, p.selection_text, p.accent, p.ansi[5], p.surface,
              p.background, p.surface, p.foreground, p.muted, p.accent]
    rows = ['[ColorScheme]']
    for group in ('active_colors', 'inactive_colors', 'disabled_colors'):
        values = list(colors)
        if group == 'disabled_colors':
            for index in (0, 6, 8, 19):
                values[index] = p.muted
        rows.append(group + '=' + ', '.join('#ff' + value[1:] for value in values))
    return '\n'.join(rows) + '\n'


def render(path: str, text: str, baseline: str | None, profile: str | None,
           mode: str, home: Path) -> str | None:
    component, base = identify(path)
    reset = profile is None
    p = palette(profile or DEFAULT_PROFILE, mode)
    original = baseline or ''
    if base.endswith('.css'):
        return css(text, original, None if reset else p)
    if component == 'fuzzel':
        values = (p.background, p.foreground, p.accent, p.muted, p.foreground, p.accent,
                  p.accent, p.selection_text, p.selection_text, p.muted, p.border)
        return _ini(text, original, {('colors', key): value[1:] + 'ff'
                                    for key, value in zip(FUZZEL_KEYS, values)}, reset)
    if component == 'dock':
        values = {}
        for key in DOCK_KEYS:
            if key.startswith('background'):
                value = '#e8' + p.background[1:]  # QColor: ALPHA precedes RGB
            elif key.startswith('active'):
                value = p.accent
            elif key.startswith('inactive'):
                value = p.muted
            else:
                value = p.border
            values[('', key)] = value
        return _ini(text, original, values, reset)
    if base == 'foot/foot.ini':
        values = {('main', 'initial-color-theme'): mode}
        original_values = ini_values(original)
        for variant in ('dark', 'light'):
            colors = palette(profile or DEFAULT_PROFILE, variant)
            colorset = (colors.foreground, colors.background, colors.selection_text,
                        colors.accent, colors.accent, *colors.ansi)
            values.update({('colors-' + variant, key): value[1:]
                           for key, value in zip(FOOT_KEYS, colorset)})
            if variant == 'light':
                values[('colors-light', 'alpha')] = original_values.get(('colors-dark', 'alpha'), '1.0')
        return _ini(text, original, values, reset)
    if base == 'kitty/kitty.conf':
        values = dict(zip(KITTY_KEYS, (p.foreground, p.background, p.selection_text, p.accent,
                                     p.accent, p.background, p.accent, *p.ansi)))
        if reset:
            old = flat_values(original, ' ')
            values = {key: old.get(key) for key in values}
        return edit_flat(text, values)
    if base.startswith('gtk-'):
        values = {('Settings', 'gtk-theme-name'): 'Adwaita-dark' if mode == 'dark' else 'Adwaita',
                  ('Settings', 'gtk-application-prefer-dark-theme'): '1' if mode == 'dark' else '0',
                  ('Settings', 'gtk-icon-theme-name'): 'Papirus-Dark' if mode == 'dark' else 'Papirus'}
        return _ini(text, original, values, reset)
    if base == 'qt6ct/qt6ct.conf':
        values = {('Appearance', 'color_scheme_path'): str(home / '.config' / OPTIONAL),
                  ('Appearance', 'custom_palette'): 'true', ('Appearance', 'style'): 'Fusion',
                  ('Appearance', 'icon_theme'): 'Papirus-Dark' if mode == 'dark' else 'Papirus'}
        return _ini(text, original, values, reset)
    if base == OPTIONAL:
        return baseline if reset else qt_palette(p)
    if base == 'labwc/themerc-override':
        old = flat_values(original, ':')
        values = {}
        for key, value in old.items():
            if not (key.endswith('.color') or key.endswith('.colorTo')):
                continue
            if reset:
                values[key] = value
                continue
            selected = '.active.' in key and key.startswith('menu.')
            if 'shadow' in key:
                color = p.background
            elif 'border' in key or 'snapping' in key:
                color = p.accent
            elif 'text.color' in key or 'image.color' in key:
                color = p.selection_text if selected else p.muted if '.inactive.' in key else p.foreground
            elif selected or 'hover' in key:
                color = p.accent
            else:
                color = p.surface if 'title' in key else p.background
            def replace(match):
                alpha = match[0][7:] if len(match[0]) == 9 else ''
                return color + alpha
            values[key] = re.sub(r'#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b', replace, value)
        return edit_flat(text, values, ':')
    raise ValueError('unsupported native appearance format')
