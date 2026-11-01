"""Best-effort, installation-rendered Help presentation values."""
from __future__ import annotations

import re
from .catalog import ROOT, decode, read_data


ICON_KEYS = frozenset({
    'application', 'back', 'bookmark', 'bookmark-empty', 'copy', 'error',
    'forward', 'home', 'menu', 'recents', 'search',
})
THEME_ICON = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z')


def _empty() -> dict:
    return {'version': 1, 'icons': {key: '' for key in ICON_KEYS}, 'list_marker': ''}


def _icon(value: object) -> str:
    # A bad theme value only removes that decoration; it never prevents Help
    # from opening. Symbolic names remain usable for compatibility with an
    # existing installed theme; shipped values come from the theme env files.
    return value if isinstance(value, str) and THEME_ICON.fullmatch(value) else ''


def _marker(value: object) -> str:
    if (isinstance(value, str) and 1 <= len(value) <= 8
            and all(ord(char) >= 160 and not 0xd800 <= ord(char) <= 0xdfff for char in value)):
        return value
    return ''


def load() -> dict:
    result = _empty()
    try:
        data = decode(read_data(ROOT, 'theme.json', 16384))
    except (OSError, TypeError, ValueError):
        return result
    icons = data.get('icons', {}) if isinstance(data, dict) else {}
    if isinstance(icons, dict):
        result['icons'].update({key: _icon(icons.get(key)) for key in ICON_KEYS})
    result['list_marker'] = _marker(data.get('list_marker')) if isinstance(data, dict) else ''
    return result
