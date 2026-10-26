"""Allowlisted native files and color-only profile/reset transformations."""
from __future__ import annotations
import re
from pathlib import Path
from .catalog import palette, readable_text, DEFAULT_PROFILE
from .editors import css, edit_ini, edit_flat, ini_values, flat_values
from .themes import variant as desktop_theme

FILES = {
 'fuzzel': ('fuzzel/base.ini', 'fuzzel/fuzzel.ini', 'fuzzel/menu.ini', 'fuzzel/computer-management.ini'),
 'waybar': ('waybar/style.css', 'waybar/config'),
 'taskview': ('waybar/taskview.css',),
 'waycal': ('waycal/style.css',),
 'dock': ('crystal-dock/labwc/appearance.conf',),
 'terminal': ('foot/foot.ini', 'kitty/kitty.conf'),
 'theme': ('gtk-3.0/settings.ini', 'gtk-4.0/settings.ini', 'gtk-4.0/gtk.css',
           'qt5ct/qt5ct.conf', 'qt6ct/qt6ct.conf',
           'qt5ct/colors/labwc-appearance.conf', 'qt6ct/colors/labwc-appearance.conf',
           'Kvantum/kvantum.kvconfig', 'labwc/themerc-override', 'labwc/environment'),
}
GREETER_FILES = ('gtkgreet.css', 'gtkgreet-power.css')
VARIANTS = ('', '.internal', '.external')
OPTIONAL = 'qt6ct/colors/labwc-appearance.conf'
OPTIONAL_FILES = frozenset((OPTIONAL, 'qt5ct/colors/labwc-appearance.conf',
                            'gtk-4.0/gtk.css', 'Kvantum/kvantum.kvconfig',
                            'qt5ct/qt5ct.conf', 'labwc/environment'))
ICON_MANAGED_FILES = frozenset({
    'fuzzel/base.ini', 'gtk-3.0/settings.ini', 'gtk-4.0/settings.ini',
    'qt5ct/qt5ct.conf', 'qt6ct/qt6ct.conf', 'waybar/config', 'waybar/style.css',
})
POINTER_MANAGED_FILES = frozenset({
    'gtk-3.0/settings.ini', 'gtk-4.0/settings.ini', 'labwc/environment',
})
GTK4_START = '/* labwc-appearance: desktop theme begin */'
GTK4_END = '/* labwc-appearance: desktop theme end */'
FUZZEL_KEYS = ('background', 'text', 'prompt', 'placeholder', 'input', 'match', 'selection',
               'selection-text', 'selection-match', 'counter', 'border')
FOOT_KEYS = ('foreground', 'background', 'selection-foreground', 'selection-background', 'urls',
             *(f'regular{i}' for i in range(8)), *(f'bright{i}' for i in range(8)))
KITTY_KEYS = ('foreground', 'background', 'selection_foreground', 'selection_background',
              'cursor', 'cursor_text_color', 'url_color', *(f'color{i}' for i in range(16)))
KITTY_STATE_KEYS = ('active_border_color', 'inactive_border_color', 'bell_border_color',
                    'active_tab_foreground', 'active_tab_background',
                    'inactive_tab_foreground', 'inactive_tab_background',
                    'tab_bar_background', 'tab_bar_margin_color')
DOCK_KEYS = ('backgroundColor', 'backgroundColor2D', 'backgroundColorMetal2D', 'borderColor',
             'borderColorMetal2D', 'activeIndicatorColor', 'activeIndicatorColor2D',
             'activeIndicatorColorMetal2D', 'inactiveIndicatorColor',
             'inactiveIndicatorColor2D', 'inactiveIndicatorColorMetal2D')


def user_paths() -> set[str]:
    return {'.config/' + path + variant for paths in FILES.values() for path in paths
            for variant in VARIANTS if path not in OPTIONAL_FILES or not variant}


def identify(path: str) -> tuple[str, str]:
    for component, paths in FILES.items():
        for base in paths:
            if path in tuple('.config/' + base + variant for variant in VARIANTS):
                return component, base
    raise ValueError('path is not an appearance-managed native file')


def _replace_setting(text: str, key: str, value: str) -> str:
    expression = re.compile(r'(?m)^(\s*' + re.escape(key) + r'\s*=\s*)[^\n]*$')
    result, count = expression.subn(lambda match: match.group(1) + value, text)
    if count != 1:
        raise ValueError('appearance setting is missing or duplicated: ' + key)
    return result


def render_asset(path: str, text: str, baseline: str | None, kind: str, name: str) -> str:
    if kind == 'icon':
        if path in ('gtk-3.0/settings.ini', 'gtk-4.0/settings.ini'):
            return _replace_setting(text, 'gtk-icon-theme-name', name)
        if path in ('qt5ct/qt5ct.conf', 'qt6ct/qt6ct.conf'):
            return _replace_setting(text, 'icon_theme', name)
        if path == 'fuzzel/base.ini':
            return _replace_setting(text, 'icon-theme', name)
        if path == 'waybar/config':
            result, count = re.subn(r'("icon-theme"\s*:\s*")[^"]*(")', r'\1' + name + r'\2', text)
            if count < 1:
                raise ValueError('Waybar icon-theme setting is missing')
            return result
        if path == 'waybar/style.css':
            result, count = re.subn(r'(-gtk-icon-theme\s*:\s*")[^"]*(")', r'\1' + name + r'\2', text)
            if count < 1:
                raise ValueError('Waybar GTK icon theme setting is missing')
            return result
    if kind == 'pointer':
        if path in ('gtk-3.0/settings.ini', 'gtk-4.0/settings.ini'):
            return _replace_setting(text, 'gtk-cursor-theme-name', name)
        if path == 'labwc/environment':
            if not text.strip():
                return 'XCURSOR_THEME=' + name + '\n'
            if not re.search(r'(?m)^\s*XCURSOR_THEME\s*=', text):
                return text.rstrip('\n') + '\nXCURSOR_THEME=' + name + '\n'
            return _replace_setting(text, 'XCURSOR_THEME', name)
    raise ValueError('unsupported appearance asset path')


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


def qt_palette(p, *, qt6: bool = True) -> str:
    # QPalette roles 0..21, including Qt 6.6 Accent. Native qt6ct QColor ARGB.
    colors = [p.foreground, p.surface, p.foreground, p.muted, p.border, p.border,
              p.foreground, p.selection_text, p.foreground, p.background, p.background,
              p.background, p.accent, p.selection_text, p.accent, p.ansi[5], p.surface,
              p.background, p.surface, p.foreground, p.muted, p.accent]
    if not qt6:
        colors = colors[:21]  # Qt5 has PlaceholderText; Accent is Qt6-only.
    rows = ['[ColorScheme]']
    for group in ('active_colors', 'inactive_colors', 'disabled_colors'):
        values = list(colors)
        if group == 'disabled_colors':
            for index in (0, 6, 8, 19):
                values[index] = p.muted
        rows.append(group + '=' + ', '.join('#ff' + value[1:] for value in values))
    return '\n'.join(rows) + '\n'


def gtk4_import(text: str, baseline: str | None, theme) -> str | None:
    starts, ends = text.count(GTK4_START), text.count(GTK4_END)
    if starts or ends:
        if starts != 1 or ends != 1 or text.index(GTK4_END) <= text.index(GTK4_START):
            raise ValueError('ambiguous managed GTK4 desktop theme import')
        start, end = text.index(GTK4_START), text.index(GTK4_END) + len(GTK4_END)
        if text[end:end + 1] == '\n':
            end += 1
        text = text[:start] + text[end:]
    if theme is not None and theme.family != 'adwaita':
        path = '/usr/share/themes/' + theme.gtk + '/gtk-4.0/gtk.css'
        return GTK4_START + '\n@import url("file://' + path + '");\n' + GTK4_END + '\n' + text
    return None if baseline is None and not text.strip() else text


def render(path: str, text: str, baseline: str | None, profile: str | None,
           mode: str, home: Path) -> str | None:
    component, base = identify(path)
    reset = profile is None
    theme = desktop_theme(profile) if component == 'theme' and profile is not None else None
    p = theme.colors if theme is not None else palette(profile or DEFAULT_PROFILE, mode)
    original = baseline or ''
    if base == 'gtk-4.0/gtk.css':
        return gtk4_import(text, baseline, theme)
    if base in ('waybar/config', 'labwc/environment'):
        return baseline if reset else text
    if base.endswith('.css'):
        return css(text, original, None if reset else p, glow=True)
    if component == 'fuzzel':
        values = (p.background, p.foreground, p.accent_hover, p.muted, p.foreground, p.accent,
                  p.accent, p.selection_text, p.selection_text, p.disabled, p.glow)
        return _ini(text, original, {('colors', key): value[1:] + 'ff'
                                    for key, value in zip(FUZZEL_KEYS, values)}, reset)
    if component == 'dock':
        values = {}
        backgrounds = {'backgroundColor': p.background, 'backgroundColor2D': p.surface,
                       'backgroundColorMetal2D': p.surface_alt}
        active = {'activeIndicatorColor': p.accent, 'activeIndicatorColor2D': p.accent_hover,
                  'activeIndicatorColorMetal2D': p.glow}
        inactive = {'inactiveIndicatorColor': p.disabled, 'inactiveIndicatorColor2D': p.muted,
                    'inactiveIndicatorColorMetal2D': p.border}
        for key in DOCK_KEYS:
            if key in backgrounds:
                value = '#e8' + backgrounds[key][1:]  # QColor: ALPHA precedes RGB
            elif key in active:
                value = active[key]
            elif key in inactive:
                value = inactive[key]
            else:
                value = p.accent_hover if key == 'borderColorMetal2D' else p.border
            values[('', key)] = value
        return _ini(text, original, values, reset)
    if base == 'foot/foot.ini':
        values = {('main', 'initial-color-theme'): 'dark'}
        original_values = ini_values(original)
        for variant in ('dark', 'light'):
            colors = palette(profile or DEFAULT_PROFILE, variant)
            colorset = (colors.foreground, colors.background, colors.selection_text,
                        colors.accent, colors.accent, *colors.ansi)
            values.update({('colors-' + variant, key): value[1:]
                           for key, value in zip(FOOT_KEYS, colorset)})
            pairs = {'cursor': (readable_text(colors.glow), colors.glow),
                     'jump-labels': (readable_text(colors.accent_hover), colors.accent_hover),
                     'scrollback-indicator': (colors.foreground, colors.surface_alt),
                     'search-box-no-match': (readable_text(colors.error), colors.error),
                     'search-box-match': (colors.foreground, colors.hover)}
            values.update({('colors-' + variant, key): ' '.join(c[1:] for c in pair)
                           for key, pair in pairs.items()})
            values[('colors-' + variant, 'flash')] = colors.warning[1:]
            if variant == 'light':
                values[('colors-light', 'alpha')] = original_values.get(('colors-dark', 'alpha'), '1.0')
        return _ini(text, original, values, reset)
    if base == 'kitty/kitty.conf':
        values = dict(zip(KITTY_KEYS, (p.foreground, p.background, p.selection_text, p.accent,
                                     p.glow, readable_text(p.glow), p.accent_hover, *p.ansi)))
        values.update(dict(zip(KITTY_STATE_KEYS, (
            p.glow, p.border, p.warning, p.selection_text, p.accent,
            p.muted, p.surface_alt, p.surface, p.background))))
        if reset:
            old = flat_values(original, ' ')
            values = {key: old.get(key) for key in values}
        return edit_flat(text, values)
    if base.startswith('gtk-'):
        values = {('Settings', 'gtk-theme-name'): theme.gtk if theme is not None else 'Adwaita',
                  ('Settings', 'gtk-application-prefer-dark-theme'): '1' if mode == 'dark' else '0'}
        return _ini(text, original, values, reset)
    if base in ('qt5ct/qt5ct.conf', 'qt6ct/qt6ct.conf'):
        color_file = base.split('/', 1)[0] + '/colors/labwc-appearance.conf'
        style = theme.style if theme is not None else 'Adwaita'
        # Forky's Breeze is Qt6. The older Qt5 package pins incompatible
        # Breeze data; use Qt5's built-in Fusion with the same full palette.
        if base.startswith('qt5ct/') and style == 'Breeze':
            style = 'Fusion'
        values = {('Appearance', 'color_scheme_path'): str(home / '.config' / color_file),
                  ('Appearance', 'custom_palette'): 'true',
                  ('Appearance', 'style'): style}
        result = _ini(text, original, values, reset)
        return None if reset and baseline is None and not result.strip() else result
    if base in (OPTIONAL, 'qt5ct/colors/labwc-appearance.conf'):
        return baseline if reset else qt_palette(p, qt6=base.startswith('qt6ct/'))
    if base == 'Kvantum/kvantum.kvconfig':
        if theme is not None and theme.kvantum is None:
            return text if text else baseline
        values = {('General', 'theme'): theme.kvantum if theme is not None else ''}
        result = _ini(text, original, values, reset)
        return None if reset and baseline is None and not result.strip() else result
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
                color = p.shadow
            elif 'border' in key or 'snapping' in key:
                color = p.border if '.inactive.' in key else p.accent
            elif 'text.color' in key or 'image.color' in key:
                color = p.selection_text if selected else p.muted if '.inactive.' in key else p.foreground
            elif selected:
                color = p.accent
            elif 'hover' in key:
                color = p.hover
            else:
                color = p.surface_alt if key.endswith('.colorTo') else p.surface if 'title' in key else p.background
            def replace(match):
                alpha = match[0][7:] if len(match[0]) == 9 else ''
                return color + alpha
            values[key] = re.sub(r'#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b', replace, value)
        return edit_flat(text, values, ':')
    raise ValueError('unsupported native appearance format')
