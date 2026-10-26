"""Allowlisted icon and pointer theme collections for Desktop Appearance."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import stat


@dataclass(frozen=True)
class Collection:
    identity: str
    label: str
    variants: tuple[str, ...]


def _collections(rows: tuple[tuple[str, str, tuple[str, ...]], ...]) -> tuple[Collection, ...]:
    return tuple(Collection(*row) for row in rows)


ICON_COLLECTIONS = _collections((
    ('adwaita', 'Adwaita', ('Adwaita', 'Adwaita-dark', 'Adwaita-high-contrast')),
    ('breeze', 'Breeze', ('breeze', 'breeze-dark')),
    ('papirus', 'Papirus', ('Papirus', 'Papirus-Dark', 'Papirus-Light')),
    ('numix', 'Numix', ('Numix', 'Numix-Circle', 'Numix-Circle-Light')),
    ('elementary', 'elementary', ('elementary', 'elementary-xfce-dark')),
    ('yaru', 'Yaru', ('Yaru', 'Yaru-dark')),
    ('humanity', 'Humanity', ('Humanity', 'Humanity-Dark')),
    ('oxygen', 'Oxygen', ('Oxygen', 'Oxygen-White')),
    ('moka', 'Moka', ('Moka', 'Moka-Dark')),
    ('tela', 'Tela', ('Tela', 'Tela-dark', 'Tela-blue', 'Tela-blue-dark')),
    ('qogir', 'Qogir', ('Qogir', 'Qogir-dark')),
    ('zafiro', 'Zafiro', ('Zafiro', 'Zafiro-icons')),
    ('candy', 'Candy', ('Candy', 'Candy-icons')),
    ('whitesur', 'WhiteSur', ('WhiteSur', 'WhiteSur-dark')),
    ('vimix', 'Vimix', ('Vimix', 'Vimix-dark')),
    ('cupertino', 'Cupertino', ('Cupertino', 'Cupertino-dark')),
    ('fluent', 'Fluent', ('Fluent', 'Fluent-dark')),
    ('suru', 'Suru', ('Suru', 'Suru++')),
    ('high-contrast', 'High Contrast', ('HighContrast',)),
    ('hicolor', 'Hicolor', ('hicolor',)),
))

POINTER_COLLECTIONS = _collections((
    ('adwaita', 'Adwaita', ('Adwaita', 'Adwaita-HighContrast')),
    ('breeze', 'Breeze', ('Breeze', 'Breeze_Snow')),
    ('bibata', 'Bibata', ('Bibata-Modern-Classic', 'Bibata-Modern-Ice', 'Bibata-Original-Classic')),
    ('dmz', 'DMZ', ('DMZ-White', 'DMZ-Black')),
    ('oxygen', 'Oxygen', ('Oxygen_Black', 'Oxygen_White')),
    ('yaru', 'Yaru', ('Yaru', 'Yaru-bark')),
    ('capitaine', 'Capitaine', ('Capitaine-cursors', 'Capitaine-cursors-light')),
    ('phinger', 'Phinger', ('phinger-cursors', 'phinger-cursors-light')),
    ('volantes', 'Volantes', ('volantes_cursors', 'volantes_cursors_light')),
    ('numix', 'Numix', ('Numix-Cursor', 'Numix-Cursor-Light')),
    ('qogir', 'Qogir', ('Qogir-cursors', 'Qogir-cursors-light')),
    ('vimix', 'Vimix', ('Vimix-cursors', 'Vimix-cursors-light')),
    ('whitesur', 'WhiteSur', ('WhiteSur-cursors', 'WhiteSur-cursors-light')),
    ('cupertino', 'Cupertino', ('Cupertino-cursors', 'Cupertino-cursors-light')),
    ('comix', 'Comix', ('ComixCursors-Black', 'ComixCursors-Blue',
                        'ComixCursors-Green', 'ComixCursors-Orange',
                        'ComixCursors-Red', 'ComixCursors-White',
                        'ComixCursors-Slim-White')),
    ('neutral', 'Neutral', ('Neutral', 'Neutral-compact')),
    ('redglass', 'Red Glass', ('redglass',)),
    ('whiteglass', 'White Glass', ('whiteglass',)),
    ('handheld', 'Handheld', ('handhelds',)),
    ('crystal', 'Crystal', ('crystalblue', 'crystalblue_classic',
                           'crystalblue_nonanim', 'crystalgray',
                           'crystalgray_nonanim', 'crystalwhite',
                           'crystalwhite_nonanim')),
))

ICON_NAMES = frozenset(variant for collection in ICON_COLLECTIONS for variant in collection.variants)
POINTER_NAMES = frozenset(variant for collection in POINTER_COLLECTIONS for variant in collection.variants)
SAFE_THEME_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}\Z')


def _validate_name(name: str, allowed: frozenset[str], kind: str) -> str:
    if not isinstance(name, str) or name not in allowed or SAFE_THEME_NAME.fullmatch(name) is None:
        raise ValueError(f'unknown {kind} theme')
    return name


def icon_name(name: str) -> str:
    return _validate_name(name, ICON_NAMES, 'icon')


def pointer_name(name: str) -> str:
    return _validate_name(name, POINTER_NAMES, 'pointer')


def _installed_directory(name: str, *, pointer: bool = False) -> Path:
    name = pointer_name(name) if pointer else icon_name(name)
    candidates = (Path('/usr/share/icons') / name, Path('/usr/local/share/icons') / name)
    for path in candidates:
        try:
            metadata = path.lstat()
        except OSError:
            continue
        if (stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0
                and metadata.st_gid == 0 and not metadata.st_mode & 0o022):
            return path
    kind = 'pointer' if pointer else 'icon'
    raise RuntimeError(f'installed {kind} theme is unavailable: {name}')


def require_icon_installed(name: str) -> Path:
    return _installed_directory(name)


def require_pointer_installed(name: str) -> Path:
    return _installed_directory(name, pointer=True)


def available_collections(collections: tuple[Collection, ...], *, pointer: bool = False) -> tuple[Collection, ...]:
    """Return only collections with at least one safe, installed variant.

    The catalog remains stable for state validation and documentation, while
    the interactive menu never offers an option that the target cannot apply.
    """
    result = []
    for collection in collections:
        variants = []
        for variant in collection.variants:
            try:
                _installed_directory(variant, pointer=pointer)
            except RuntimeError:
                continue
            variants.append(variant)
        if variants:
            result.append(Collection(collection.identity, collection.label, tuple(variants)))
    return tuple(result)


def public_catalog() -> dict[str, dict]:
    return {
        'icons': {collection.identity: {
            'label': collection.label,
            'variants': {variant: variant for variant in collection.variants},
        } for collection in ICON_COLLECTIONS},
        'pointers': {collection.identity: {
            'label': collection.label,
            'variants': {variant: variant for variant in collection.variants},
        } for collection in POINTER_COLLECTIONS},
    }
