"""Twenty coordinated palettes, each with explicit dark and light variants."""
from __future__ import annotations
from dataclasses import dataclass

# id, display name, dark background/foreground/accent, light background/text/accent
CATALOG = (
 ('midnight-slate', 'Midnight Slate', '111827', 'e5edf8', '7cb8ff', 'f5f7fb', '192538', '245dab'),
 ('nordic-frost', 'Nordic Frost', '242c3b', 'e7edf4', '88c0d0', 'edf2f6', '293748', '2e6375'),
 ('mocha-rose', 'Mocha Rose', '241e2e', 'f2e4f4', 'e6a1c7', 'fbf0f6', '412d42', '944b77'),
 ('forest-mist', 'Forest Mist', '15251f', 'e1eee5', '88c9a2', 'f0f7ef', '233c2b', '316a49'),
 ('ocean-glass', 'Ocean Glass', '122632', 'e0f0f5', '6dcfda', 'eff8fb', '193747', '176b7b'),
 ('amber-dusk', 'Amber Dusk', '292217', 'f3ead7', 'e6bd6b', 'fcf6e9', '423422', '8a581c'),
 ('lavender-ink', 'Lavender Ink', '221f35', 'ebe7fa', 'b6a5ed', 'f6f2fd', '342c50', '6950a1'),
 ('solar-clay', 'Solar Clay', '30211d', 'f7e5dc', 'e9a083', 'fbf1e9', '4b3028', 'a44f34'),
 ('glacier-blue', 'Glacier Blue', '17293b', 'e6f0fb', '93c4f5', 'f1f7fe', '233b55', '2b6095'),
 ('sage-linen', 'Sage Linen', '242b23', 'e7ecdf', 'aec99a', 'f5f6ed', '36432e', '516f39'),
 ('plum-velvet', 'Plum Velvet', '2c1d30', 'f3e3f4', 'dba1e2', 'faf0fc', '4c2c50', '85458d'),
 ('copper-stone', 'Copper Stone', '292522', 'f0e8e0', 'dca785', 'f7f3ed', '423830', '895a38'),
 ('teal-harbor', 'Teal Harbor', '122c2b', 'dff2ed', '6ed2bd', 'effaf6', '173f39', '176e5e'),
 ('cherry-blossom', 'Cherry Blossom', '301f27', 'f8e3eb', 'ef9db9', 'fff0f5', '512c3b', 'a63d67'),
 ('cobalt-cloud', 'Cobalt Cloud', '1b2340', 'e7ecfb', '9aaff8', 'f2f5ff', '293555', '485fb1'),
 ('olive-gold', 'Olive Gold', '28291d', 'eeefda', 'c9ce83', 'f8f8eb', '3d4029', '67702b'),
 ('orchid-snow', 'Orchid Snow', '2b2239', 'f1e7fc', 'cba9f0', 'fbf5ff', '483159', '8054a5'),
 ('graphite-mint', 'Graphite Mint', '202526', 'e4eeee', '89d1b9', 'f1f7f5', '283c37', '2d725c'),
 ('sandstone-sky', 'Sandstone Sky', '292827', 'f0ece5', '90bfdd', 'faf7f0', '353c42', '336c8e'),
 ('ember-night', 'Ember Night', '2c2020', 'f5e7e3', 'efad91', 'fdf2ed', '4c302d', 'a25139'),
)
LABELS = {row[0]: row[1] for row in CATALOG}
DEFAULT_PROFILE = CATALOG[0][0]
COMPONENTS = {'fuzzel': 'Fuzzel Profiles', 'waybar': 'Waybar Profiles',
              'dock': 'Crystal-Dock Profiles', 'greeter': 'GTKGREET Profiles',
              'terminal': 'Terminal Profiles'}


def rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip('#')
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def mix(first: str, second: str, fraction: float) -> str:
    return '#' + ''.join(f'{round(a * (1 - fraction) + b * fraction):02x}'
                         for a, b in zip(rgb(first), rgb(second)))


def luminance(color: str) -> float:
    values = [c / 255 for c in rgb(color)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(a: str, b: str) -> float:
    low, high = sorted((luminance(a), luminance(b)))
    return (high + 0.05) / (low + 0.05)


@dataclass(frozen=True)
class Palette:
    background: str
    foreground: str
    accent: str
    surface: str
    muted: str
    border: str
    selection_text: str
    ansi: tuple[str, ...]


def palette(identity: str, mode: str) -> Palette:
    if identity not in LABELS or mode not in ('dark', 'light'):
        raise ValueError('unknown appearance profile or mode')
    row = next(row for row in CATALOG if row[0] == identity)
    bg, fg, accent = ['#' + value for value in (row[2:5] if mode == 'dark' else row[5:8])]
    surface = mix(bg, fg, 0.065)
    muted = mix(bg, fg, 0.67)
    border = mix(bg, accent, 0.48)
    selection = '#111111' if contrast(accent, '#111111') >= contrast(accent, '#ffffff') else '#ffffff'
    base = (('e58c8c', '92c995', 'dbbd7e', '91b9e9', 'c7a0dd', '7fcaca') if mode == 'dark'
            else ('a43745', '376d3f', '80600c', '2e62a2', '8046a0', '196b70'))
    normal = [mix(bg, fg, 0.18), *('#' + value for value in base), fg]
    # Accent coordinates the blue ANSI slot without sacrificing readable text.
    normal[4] = accent
    bright = [muted, *(mix(c, fg, 0.14) for c in normal[1:7]), fg]
    return Palette(bg, fg, accent, surface, muted, border, selection, tuple(normal + bright))
