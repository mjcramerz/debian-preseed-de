"""Distinct application theme families with genuine GTK3/GTK4 and Qt styles.

Families are the menu's top level. Light/dark and flavor/accent combinations
are variants inside a family and never count as additional theme brands.
Component profiles live separately in catalog.py and always remain dark.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from managed_workflows.fs import Tree, parts
from .catalog import Palette, native_palette


@dataclass(frozen=True)
class Theme:
    identity: str
    family: str
    label: str
    dark: bool
    qt_source: str | None
    background: str
    foreground: str
    accent: str
    style: str = 'kvantum'

    @property
    def gtk(self) -> str:
        if self.family == 'adwaita':
            return 'Adwaita-dark' if self.dark else 'Adwaita'
        return 'Labwc-' + self.identity

    @property
    def kvantum(self) -> str | None:
        return 'Labwc-' + self.identity if self.qt_source is not None else None

    @property
    def colors(self) -> Palette:
        return native_palette(self.background, self.foreground, self.accent, dark=self.dark)


@dataclass(frozen=True)
class Family:
    identity: str
    label: str
    variants: tuple[Theme, ...]


def _family(identity: str, label: str, rows: tuple) -> Family:
    # Row: variant suffix, label, dark, source Kvantum theme (or None),
    # window/text/accent colors, optional packaged Qt style name.
    variants = tuple(Theme(identity + '-' + row[0], identity, row[1], row[2], row[3],
                           *('#' + color for color in row[4:7]),
                           row[7] if len(row) == 8 else 'kvantum') for row in rows)
    return Family(identity, label, variants)


FAMILIES = (
    _family('adwaita', 'Adwaita', (
        ('light', 'Light', False, None, 'fafafa', '2e3436', '3584e4', 'Adwaita'),
        ('dark', 'Dark', True, None, '242424', 'eeeeec', '3584e4', 'Adwaita-Dark'),
    )),
    _family('ant', 'Ant', (
        ('dark', 'Dark', True, 'Ant-Dark', '192124', 'c3c7d1', '9bbfbf'),
    )),
    _family('arc', 'Arc', (
        ('light', 'Light', False, 'KvArc', 'f5f6f7', '383c4a', '5294e2'),
        ('dark', 'Dark', True, 'KvArcDark', '383c4a', 'd3dae3', '5294e2'),
    )),
    _family('breeze', 'Breeze', (
        ('light', 'Light', False, None, 'eff0f1', '232629', '3daee9', 'Breeze'),
        ('dark', 'Dark', True, None, '2a2e32', 'eff0f1', '3daee9', 'Breeze'),
    )),
    _family('canta', 'Canta', (
        ('light', 'Light', False, 'Canta-light', 'f5f5f5', '444444', '00ce99'),
        ('dark', 'Dark', True, 'Canta-dark', '343938', 'dfdfdf', '00ce99'),
    )),
    _family('catppuccin', 'Catppuccin', tuple(
        (flavor + '-' + accent, flavor.title() + ' · ' + accent.title(), flavor != 'latte',
         'catppuccin-' + flavor + '-' + accent, background, foreground, color)
        for flavor, background, foreground, accents in (
            ('latte', 'eff1f5', '4c4f69', (('blue', '1e66f5'), ('lavender', '7287fd'), ('mauve', '8839ef'), ('teal', '179299'))),
            ('frappe', '303446', 'c6d0f5', (('blue', '8caaee'), ('lavender', 'babbf1'), ('mauve', 'ca9ee6'), ('teal', '81c8be'))),
            ('macchiato', '24273a', 'cad3f5', (('blue', '8aadf4'), ('lavender', 'b7bdf8'), ('mauve', 'c6a0f6'), ('teal', '8bd5ca'))),
            ('mocha', '1e1e2e', 'cdd6f4', (('blue', '89b4fa'), ('lavender', 'b4befe'), ('mauve', 'cba6f7'), ('teal', '94e2d5'))),
        ) for accent, color in accents
    )),
    _family('chromeos', 'ChromeOS', (
        ('light', 'Light', False, 'ChromeOS-light', 'f5f5f5', '444444', '4285f4'),
        ('dark', 'Dark', True, 'ChromeOS-dark', '2a2a2a', 'dfdfdf', '4285f4'),
    )),
    _family('dracula', 'Dracula', (
        ('dark', 'Dark', True, 'Dracula', '1e1f29', 'f8f8f2', 'bd93f9'),
    )),
    _family('fluent', 'Fluent', (
        ('light', 'Light', False, 'Fluent', 'f5f5f5', '444444', '0078d4'),
        ('dark', 'Dark', True, 'FluentDark', '333333', 'dedede', '0078d4'),
    )),
    _family('layan', 'Layan', (
        ('light', 'Light', False, 'Layan', 'f4f4f9', '525252', '5657f5'),
        ('dark', 'Dark', True, 'LayanDark', '31313a', 'dfdfdf', '5657f5'),
    )),
    _family('matcha', 'Matcha', (
        ('light', 'Sea Light', False, 'Matcha-sea', 'f7f7f7', '303d41', '2eb398'),
        ('dark', 'Sea Dark', True, 'Matcha-sea-dark', '1b2224', 'd3dae3', '2eb398'),
    )),
    _family('materia', 'Materia', (
        ('light', 'Light', False, 'MateriaLight', 'f9f9f9', '444444', '1a73e8'),
        ('dark', 'Dark', True, 'MateriaDark', '121212', 'dfdfdf', '8ab4f8'),
    )),
    _family('nordic', 'Nordic', (
        ('dark', 'Dark', True, 'Nordic', '2e3440', 'd8dee9', '8fbcbb'),
    )),
    _family('orchis', 'Orchis', (
        ('light', 'Light', False, 'Orchis', 'f5f5f5', '444444', '4285f4'),
        ('dark', 'Dark', True, 'OrchisDark', '212121', 'dfdfdf', '4285f4'),
    )),
    _family('qogir', 'Qogir', (
        ('light', 'Light', False, 'Qogir-light', 'f5f6f7', '5c616c', '5294e2'),
        ('dark', 'Dark', True, 'Qogir-dark', '32343d', 'e0e5eb', '5294e2'),
    )),
    _family('rose-pine', 'Rosé Pine', (
        ('main', 'Main', True, 'rose-pine-iris', '1f1d2e', 'e0def4', 'c4a7e7'),
        ('moon', 'Moon', True, 'rose-pine-moon-iris', '2a273f', 'e0def4', 'c4a7e7'),
        ('dawn', 'Dawn', False, 'rose-pine-dawn-iris', 'fffaf3', '575279', '907aa9'),
    )),
    _family('sweet', 'Sweet', (
        ('dark', 'Dark', True, 'Sweet', '161925', 'c3c7d1', 'c50ed2'),
    )),
    _family('vimix', 'Vimix', (
        ('light', 'Doder Light', False, 'VimixDoder', 'f5f5f5', '444444', '4285f4'),
        ('dark', 'Doder Dark', True, 'VimixDoderDark', '2c2e33', 'dfdfdf', '4285f4'),
    )),
    _family('whitesur', 'WhiteSur', (
        ('light', 'Light', False, 'WhiteSur', 'f5f5f5', '333333', '3484e2'),
        ('dark', 'Dark', True, 'WhiteSurDark', '242424', 'dedede', 'a0b4f8'),
    )),
    _family('yaru', 'Yaru', (
        ('light', 'Light', False, 'KvYaru', 'f7f7f7', '3d3d3d', 'e95420'),
    )),
)

FAMILY_LABELS = {family.identity: family.label for family in FAMILIES}
VARIANTS = {theme.identity: theme for family in FAMILIES for theme in family.variants}


def variant(identity: str) -> Theme:
    try:
        return VARIANTS[identity]
    except (KeyError, TypeError) as error:
        raise ValueError('unknown desktop theme variant') from error


def validate_catalog() -> None:
    if len(FAMILIES) != 20 or len(FAMILY_LABELS) != len(FAMILIES):
        raise ValueError('desktop theme catalog must contain 20 distinct families')
    if len(VARIANTS) != sum(len(family.variants) for family in FAMILIES):
        raise ValueError('duplicate desktop theme variant')
    for family in FAMILIES:
        if not family.variants or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', family.identity):
            raise ValueError('invalid desktop theme family')
        for theme in family.variants:
            if (theme.family != family.identity or
                    not re.fullmatch(r'[a-z][a-z0-9-]{0,79}', theme.identity) or
                    theme.style not in ('Adwaita', 'Adwaita-Dark', 'Breeze', 'kvantum') or
                    (theme.style == 'kvantum') != (theme.qt_source is not None) or
                    any(not re.fullmatch(r'#[0-9a-f]{6}', color)
                        for color in (theme.background, theme.foreground, theme.accent))):
                raise ValueError('invalid GTK/Qt desktop theme pairing')


def public_catalog() -> dict:
    return {family.identity: {'label': family.label,
                             'variants': {theme.identity: theme.label for theme in family.variants}}
            for family in FAMILIES}


def require_installed(identity: str) -> None:
    """Preflight the chosen provider before writing any desktop state.

    Only root-owned data from the installer is accepted. Hash reads are bounded
    to the selected variant and its Qt engines, never all 50 variants.
    """
    theme = variant(identity)
    deadline = time.monotonic() + 15
    with Tree(Path('/usr/local/share/labwc-appearance'), uid=0) as registry:
        if registry.read('themes-install-pending.json', missing=True) is not None:
            raise RuntimeError('desktop theme installation has retained recovery evidence')
        manifest = json.loads(registry.read('themes.json', limit=6 * 1024**2))
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1 or
            not isinstance(manifest.get('variants'), dict) or set(manifest['variants']) != set(VARIANTS) or
            not isinstance(manifest.get('files'), dict) or not 0 < len(manifest['files']) <= 24000):
        raise ValueError('invalid installed desktop theme inventory')
    expected = ([] if theme.family == 'adwaita' else ['themes/' + theme.gtk])
    if theme.kvantum is not None:
        expected.append('Kvantum/' + theme.kvantum)
    if manifest['variants'][identity] != expected:
        raise ValueError('installed desktop theme pairing differs from the selected provider')
    files = {}
    size = 0
    for path, metadata in manifest['files'].items():
        parts(path)
        if (not isinstance(metadata, dict) or type(metadata.get('bytes')) is not int or
                not 0 <= metadata['bytes'] <= 16 * 1024**2 or
                not isinstance(metadata.get('sha256'), str) or
                not re.fullmatch(r'[0-9a-f]{64}', metadata['sha256'])):
            raise ValueError('invalid installed desktop theme asset descriptor')
        if any(path.startswith(directory + '/') for directory in expected):
            size += metadata['bytes']
            if size > 128 * 1024**2:
                raise ValueError('selected desktop theme exceeds the read budget')
            files[path] = metadata
    required = set()
    if theme.family != 'adwaita':
        required.update('themes/' + theme.gtk + '/gtk-' + version + '/gtk.css'
                        for version in ('3.0', '4.0'))
    if theme.kvantum is not None:
        required.update('Kvantum/' + theme.kvantum + '/' + theme.kvantum + extension
                        for extension in ('.kvconfig', '.svg'))
    if not required.issubset(files):
        raise ValueError('installed desktop theme is missing a GTK3/GTK4 or Qt provider')
    packages = manifest.get('packages')
    if (not isinstance(packages, dict) or not isinstance(packages.get('multiarch'), str) or
            not re.fullmatch(r'[a-zA-Z0-9_+-]{1,80}', packages['multiarch']) or
            not isinstance(packages.get('plugins'), dict)):
        raise ValueError('installed desktop theme has no verified Qt engine inventory')
    plugin = 'libkvantum.so' if theme.style == 'kvantum' else (
        'breeze6.so' if theme.style == 'Breeze' else 'adwaita.so')
    prefix = 'lib/' + packages['multiarch'] + '/qt6/plugins/'
    plugins = (prefix + 'styles/' + plugin, prefix + 'platformthemes/libqt6ct.so')
    with Tree(Path('/usr/share'), uid=0) as public, Tree(Path('/usr'), uid=0) as usr:
        for tree, records in ((public, files), (usr, {path: {'bytes': None, 'sha256': packages['plugins'].get(path)}
                                                    for path in plugins})):
            for path, metadata in records.items():
                if time.monotonic() >= deadline:
                    raise TimeoutError('desktop theme preflight exceeded its deadline')
                digest = metadata['sha256']
                if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                    raise ValueError('selected desktop theme engine is not installed')
                blob = tree.read(path, limit=16 * 1024**2)
                if (metadata['bytes'] is not None and len(blob) != metadata['bytes']) or hashlib.sha256(blob).hexdigest() != digest:
                    raise ValueError('installed desktop theme assets changed; refusing an incomplete provider')
