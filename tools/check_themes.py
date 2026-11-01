#!/usr/bin/env python3
"""Validate the install-time appearance contract (Python 3.11+, POSIX awk).

The installer AWK validator is authoritative; this checker does not implement a
second permissive .env parser. Run before publishing a changed payload.
"""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[1] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import argparse
from collections import Counter
from collections.abc import Iterable
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'd-i/forky'
TOKEN = re.compile(r'__THEME_([A-Z0-9_]+?)__')
ASSIGNMENT = re.compile(r'^([A-Z][A-Z0-9_]*)=', re.M)
SIZES = (tuple(f'FUZZEL_{display}_{key}'
               for display in ('INTERNAL', 'EXTERNAL', 'DEFAULT')
               for key in ('FONT_SIZE', 'HORIZONTAL_PADDING', 'VERTICAL_PADDING', 'INNER_PADDING', 'LINE_HEIGHT', 'BORDER_WIDTH', 'BORDER_RADIUS'))
         + tuple(f'FUZZEL_{mode}_{display}_{key}'
                 for mode in ('LAUNCHER', 'MENU')
                 for display in ('INTERNAL', 'EXTERNAL', 'DEFAULT')
                 for key in ('WIDTH', 'LINES')))
BINARY_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico', '.ttf',
                   '.otf', '.woff', '.woff2', '.gz', '.xz', '.bz2', '.zip', '.deb'}


def check_names(names: Iterable[str]) -> None:
    """Reject opaque or duplicated naming, independently of native value syntax.

    Domain names and meaningful indices (ANSI roles, editor levels, native tonal
    shades and duration/percentage presets) remain explicit. This is a publishing
    lint, not a second parser or a shell compatibility-alias layer.
    """
    for name in names:
        parts = name.split('_')
        if not re.fullmatch(r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*', name):
            raise ValueError(f'{name}: invalid appearance identifier')
        if any(left == right for left, right in zip(parts, parts[1:])):
            raise ValueError(f'{name}: repeated adjacent naming component')
        if (parts.count('COLOR') + parts.count('COLORS') > 1 or
                any(parts.count(word) > 1 for word in ('STYLE', 'PALETTE'))):
            raise ValueError(f'{name}: repeated appearance property')
        if {'BG', 'FG', 'HL', 'SLOT', 'CUSTOMIZATIONS'} & set(parts):
            raise ValueError(f'{name}: use a descriptive element and property')
        if re.search(r'(?:^|_)(?:COLOR|REGULAR|BRIGHT|FOREGROUND|BACKGROUND)[0-9]+(?:_|$)', name):
            raise ValueError(f'{name}: use an ANSI role or explicitly named level')



# These are native separators or report indicators, not independently tinted
# glyph widgets. Their foreground follows the adjacent label/report style.
SHARED_GLYPH_STYLES = {
    'LABWC_TASKVIEW_LABEL_SEPARATOR_ICON_GLYPH': 'LABWC_TASKVIEW_TEXT_COLOR',
    'WAYBAR_BUTTON_AUDIO_MICROPHONE_NORMAL_SEPARATOR_ICON_GLYPH': 'WAYBAR_BUTTON_AUDIO_NORMAL_TEXT_COLOR',
    'WAYBAR_BUTTON_AUDIO_MICROPHONE_MUTED_SEPARATOR_ICON_GLYPH': 'WAYBAR_BUTTON_AUDIO_MUTED_TEXT_COLOR',
    'TASKWARRIOR_TUI_MARK_INDICATOR_ICON_GLYPH': 'TASKWARRIOR_TUI_REPORT_SELECTION_STYLE',
    'TASKWARRIOR_TUI_SELECTION_INDICATOR_ICON_GLYPH': 'TASKWARRIOR_TUI_REPORT_SELECTION_STYLE',
}


def check_icon_pairs(values: dict[str, str]) -> None:
    """Do not publish a recolorable glyph without its independently owned color.

    This does not invent color controls for package-owned PNG/SVG pixels, the
    taskbar's rendered surfaces, or native applications without a tint option.
    """
    for name in values:
        if not name.endswith('_ICON_GLYPH'):
            continue
        color = SHARED_GLYPH_STYLES.get(name, name.removesuffix('_GLYPH') + '_COLOR')
        if color not in values:
            raise ValueError(f'{name}: missing native icon color/style {color}')


def load_themes(seed: Path = SEED) -> dict[str, str]:
    """Return only values accepted by the exact validator used in d-i."""
    themes = seed / 'hosts/themes'
    command = ['awk', '-f', str(seed / 'scripts/late/theme-validate.awk'),
               str(themes / 'theme-schema.tsv')]
    command.extend(str(themes / f'{group}.env') for group in ('base', 'apps', 'office'))
    result = subprocess.run(command, env={**os.environ, 'LC_ALL': 'C'},
                            capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'installer theme validator failed')
    values = dict(line.split('=', 1) for line in result.stdout.splitlines())
    if not values:
        raise ValueError('empty validated theme catalog')
    return values


def render_text(text: str, values: dict[str, str]) -> str:
    """Literal fixture/checker rendering; production uses theme-render.awk."""
    def replace(match: re.Match[str]) -> str:
        key = match[1]
        target = key.startswith('TARGET_PATH_')
        source_key = key.removeprefix('TARGET_PATH_') if target else key
        try:
            value = values[source_key]
        except KeyError as exc:
            raise ValueError(f'unknown theme token: {key}') from exc
        if target:
            if not value.startswith('hooks/target/usr/share/backgrounds/'):
                raise ValueError(f'not a wallpaper source: {source_key}')
            value = value.removeprefix('hooks/target')
        return value
    rendered = TOKEN.sub(replace, text)
    if '__THEME_' in rendered:
        raise ValueError('malformed or unresolved theme token')
    return rendered


def source_texts(seed: Path):
    """Only installer/runtime source, never generated bundles, tests or artwork."""
    for directory in ('hooks/target', 'scripts/desktop', 'scripts/late', 'scripts/firstboot'):
        for path in sorted((seed / directory).rglob('*')):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() in BINARY_SUFFIXES:
                continue
            data = path.read_bytes()
            if b'\0' in data:
                continue
            try:
                yield path, data.decode('utf-8')
            except UnicodeDecodeError:
                continue


def check_native_menu_icons(seed: Path, values: dict[str, str]) -> None:
    """Check regular XML icon names and status text as data."""
    config = seed / 'hooks/target/etc/skel-desktop/.config'
    removed_icon_css = (
        'menu-icons.css.tmpl', 'clock-icons.css.tmpl', 'audio-icons.css.tmpl',
        'system-icons.css.tmpl', 'notification-icons.css.tmpl', 'power-icons.css.tmpl',
        'tomat-icons.css.tmpl', 'wayscriber-icons.css.tmpl', 'themes.css.tmpl',
    )
    icons = config / 'waybar/icons'
    for filename in removed_icon_css:
        if (icons / filename).exists():
            raise ValueError(f'retired native icon stylesheet remains: {filename}')
    if 'WAYBAR_DROPDOWN_AUDIO_VOLUME_40_PERCENT_ICON_NAME' in values:
        raise ValueError('the obsolete Audio Volume 40% icon variable remains')
    colored_menu_icons = {
        'WAYBAR_DROPDOWN_AUDIO_MICROPHONE_MUTE_ICON_NAME': 'audio-recorder',
        'WAYBAR_DROPDOWN_AUDIO_MIXER_ICON_NAME': 'multimedia-volume-control',
        'WAYBAR_DROPDOWN_AUDIO_OUTPUT_MUTE_ICON_NAME': 'preferences-desktop-sound',
        'WAYBAR_DROPDOWN_AUDIO_SUBMENU_VOLUME_PRESETS_ICON_NAME': 'multimedia-volume-control',
        'WAYBAR_DROPDOWN_AUDIO_SUBMENU_WHISPER_ICON_NAME': 'audio-recorder',
        'WAYBAR_DROPDOWN_SYSTEM_AUDIO_VOLUME_MUTED_ICON_NAME': 'preferences-desktop-sound',
        'WAYBAR_DROPDOWN_SYSTEM_AUDIO_INPUT_MICROPHONE_ICON_NAME': 'audio-recorder',
        'WAYBAR_DROPDOWN_NOTIFICATIONS_CENTER_ICON_NAME': 'preferences-system-notifications',
        'WAYBAR_DROPDOWN_NOTIFICATIONS_CLEAR_ICON_NAME': 'trashindicator',
        'WAYBAR_DROPDOWN_NOTIFICATIONS_DISMISS_ICON_NAME': 'preferences-desktop-notification-bell',
        'WAYBAR_DROPDOWN_NOTIFICATIONS_DND_ICON_NAME': 'preferences-desktop-notification-bell',
        'WAYBAR_DROPDOWN_NOTIFICATIONS_DND_OFF_ICON_NAME': 'preferences-desktop-notification-bell',
        'WAYBAR_DROPDOWN_NOTIFICATIONS_DND_ON_ICON_NAME': 'preferences-desktop-notification-bell',
        'WAYBAR_DROPDOWN_NOTIFICATIONS_RESTORE_ICON_NAME': 'preferences-system-notifications',
        'WAYBAR_DROPDOWN_NOTIFICATIONS_SUBMENU_DO_NOT_DISTURB_ICON_NAME': 'preferences-desktop-notification-bell',
        'WAYBAR_DROPDOWN_TOMAT_SESSION_25_MINUTES_ICON_NAME': 'alarm-timer',
        'WAYBAR_DROPDOWN_TOMAT_SESSION_50_MINUTES_ICON_NAME': 'alarm-timer',
        'WAYBAR_DROPDOWN_TOMAT_SESSION_90_MINUTES_ICON_NAME': 'alarm-timer',
        'WAYBAR_DROPDOWN_TOMAT_SOUNDS_ICON_NAME': 'multimedia-volume-control',
        'WAYBAR_DROPDOWN_WHISPER_CANCEL_ICON_NAME': 'sound-recorder',
        'WAYBAR_DROPDOWN_WHISPER_RECORD_ICON_NAME': 'audio-recorder',
        'WAYBAR_DROPDOWN_WHISPER_STOP_ICON_NAME': 'sound-recorder',
        'WAYBAR_DROPDOWN_WHISPER_TRANSCRIBE_ICON_NAME': 'accessories-text-editor',
    }
    for key, expected in colored_menu_icons.items():
        if values.get(key) != expected:
            raise ValueError(f'{key} must use the reviewed regular Papirus-Dark icon {expected}')
    menus = sorted((config / 'waybar/gtk').glob('*.xml.tmpl'))
    if len(menus) != 10:
        raise ValueError('all ten native Waybar popup templates must be present')
    gtk_css = (config / 'waybar/style/gtk.css.tmpl').read_text(encoding='utf-8')
    if '-gtk-icon-style: regular;' not in gtk_css:
        raise ValueError('waybar/style/gtk.css must request regular theme icons')
    if '-gtk-icon-theme:' in gtk_css:
        raise ValueError('native Waybar popups must inherit the desktop GTK icon theme')
    waybar_css = (config / 'waybar/style.css.tmpl').read_text(encoding='utf-8')
    for filename in removed_icon_css:
        if f'icons/{filename.removesuffix(".tmpl")}' in waybar_css:
            raise ValueError(f'style.css still imports retired native icon stylesheet: {filename}')
    for path in menus:
        tree = ET.fromstring(render_text(path.read_text(encoding='utf-8'), values))
        ids = []
        for image in tree.iter('object'):
            if image.get('class') != 'GtkImage':
                continue
            image_id = image.get('id')
            icon_name = image.findtext('./property[@name="icon-name"]')
            if not image_id or not icon_name:
                raise ValueError(f'{path.name}: every native GtkImage needs an id and icon-name')
            if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}', icon_name)
                    or icon_name.endswith('-symbolic')):
                raise ValueError(f'{path.name}: GtkImage needs a regular theme icon: {image_id}')
            ids.append(image_id)
        if len(ids) != len(set(ids)):
            raise ValueError(f'{path.name}: duplicate GtkImage ids prevent deterministic icon handling')
        for item in tree.iter('object'):
            if item.get('class') != 'GtkMenuItem':
                continue
            image = item.find('./child/object[@class="GtkBox"]/child/object[@class="GtkImage"]')
            name = image.findtext('./property[@name="icon-name"]') if image is not None else ''
            if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}', name or '')
                    or name.endswith('-symbolic')):
                raise ValueError(f'{path.name}: menu row needs a regular theme icon: {item.get("id")}')
    audio = ET.fromstring(render_text((config / 'waybar/gtk/audio-menu.xml.tmpl').read_text(encoding='utf-8'), values))
    presets = next((item for item in audio.iter('object')
                    if item.get('class') == 'GtkMenuItem'
                    and item.findtext('./child/object[@class="GtkBox"]/child/object[@class="GtkLabel"]/property[@name="label"]') == 'Volume Presets'), None)
    if presets is None:
        raise ValueError('Audio menu is missing the Volume Presets submenu')
    preset_rows = presets.findall('./child[@type="submenu"]/object/child/object[@class="GtkMenuItem"]')
    if [row.get('id') for row in preset_rows] != ['audio_25', 'audio_45', 'audio_65', 'audio_85', 'audio_100']:
        raise ValueError('Audio Volume Presets must contain exactly 25, 45, 65, 85 and 100 percent')
    tomat = tomllib.loads(render_text((config / 'tomat/config.toml.tmpl').read_text(encoding='utf-8'), values))
    for key in ('work', 'break', 'long_break', 'play', 'pause', 'stop'):
        if tomat['display']['icons'][key] != values[f'WAYBAR_BUTTON_TOMAT_{key.upper()}_ICON_GLYPH']:
            raise ValueError('Tomat status text must retain its configured button glyphs')
    wayscriber = tomllib.loads(render_text((config / 'wayscriber/config.toml.tmpl').read_text(encoding='utf-8'), values))
    if wayscriber['tray']['icon_style'] != 'colored':
        raise ValueError('Wayscriber managed tray defaults must use colored artwork')


def check(seed: Path = SEED) -> dict[str, int]:
    values = load_themes(seed)
    check_names(values)
    check_icon_pairs(values)
    check_native_menu_icons(seed, values)
    references: Counter[str] = Counter()
    files = 0
    for path, text in source_texts(seed):
        # These two engines contain the token grammar, not template inputs.
        if path.name in ('themes.sh', 'theme-render.awk', 'core.sh') and path.parent.name == 'late':
            continue
        if '__THEME_' in text:
            try:
                render_text(text, values)
            except ValueError as exc:
                raise ValueError(f'{path.relative_to(seed)}: {exc}') from exc
            files += 1
        for match in TOKEN.finditer(text):
            references[match[1].removeprefix('TARGET_PATH_')] += 1
        for match in re.finditer(r'\$(?:\{)?([A-Z][A-Z0-9_]*)', text):
            if match[1] in values:
                references[match[1]] += 1
    unused = values.keys() - references.keys()
    if unused:
        raise ValueError('theme values without consumers: ' + ', '.join(sorted(unused)))
    for name in ('LABWC_WALLPAPER_DESKTOP_SWAYBG', 'LABWC_WALLPAPER_LOCKSCREEN_SWAYLOCK',
                 'LABWC_WALLPAPER_LOGIN_GTKGREET', 'LABWC_WALLPAPER_ARCHIVE'):
        path = seed / values[name]
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'{name}: source must exist as a regular payload file: {values[name]}')
        if any(parent.is_symlink() for parent in path.parents if parent != seed.parent):
            raise ValueError(f'{name}: symbolic-link source path is forbidden')
    for name, value in values.items():
        if name.startswith('WAYBAR_') and name.endswith('_ICON_PATH') and value.startswith('icons/'):
            path = seed / 'hooks/target/etc/skel-desktop/.config/waybar' / value
            template = path.with_name(path.name + '.tmpl')
            if path.exists() and template.exists():
                raise ValueError(f'{name}: ambiguous plain/template icon')
            if template.is_file():
                path = template
            if not path.is_file() or path.is_symlink():
                raise ValueError(f'{name}: selected payload icon is missing or unsafe: {value}')
    profiles = sorted((seed / 'hosts/profiles').glob('*.env'))
    for profile in profiles:
        text = profile.read_text(encoding='utf-8')
        assigned = Counter(ASSIGNMENT.findall(text))
        overlap = assigned.keys() & values.keys()
        if overlap:
            raise ValueError(f'{profile.name}: theme values belong in hosts/themes: {sorted(overlap)}')
        if any(assigned[name] != 1 for name in SIZES):
            raise ValueError(f'{profile.name}: define all {len(SIZES)} canonical Fuzzel dimensions exactly once')
        legacy = [name for name in assigned
                  if (name.startswith('FUZZEL_') and name not in SIZES)
                  or (name.startswith('LABWC_FUZZEL_') and
                      any(part in name for part in ('WIDTH', 'LINES', 'FONT_SIZE')))]
        if legacy:
            raise ValueError(f'{profile.name}: obsolete Fuzzel geometry: {legacy}')
    return {'values': len(values), 'templates': files, 'profiles': len(profiles)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=Path, default=SEED)
    args = parser.parse_args()
    try:
        result = check(args.seed.resolve())
    except (OSError, ValueError, KeyError, ET.ParseError, subprocess.SubprocessError) as exc:
        print(f'themes: {exc}', file=sys.stderr)
        return 1
    print('themes: {values} validated inputs, {templates} tokenized files, '
          '{profiles} geometry-only profiles'.format(**result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
