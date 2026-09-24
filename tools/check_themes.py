#!/usr/bin/env python3
"""Validate the install-time appearance contract (Python 3.11+, POSIX awk).

The installer AWK validator is authoritative; this checker does not implement a
second permissive .env parser. Run before publishing a changed payload.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
import os
from pathlib import Path
import re
import subprocess
import sys

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


def check(seed: Path = SEED) -> dict[str, int]:
    values = load_themes(seed)
    check_names(values)
    check_icon_pairs(values)
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
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'themes: {exc}', file=sys.stderr)
        return 1
    print('themes: {values} validated inputs, {templates} tokenized files, '
          '{profiles} geometry-only profiles'.format(**result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
