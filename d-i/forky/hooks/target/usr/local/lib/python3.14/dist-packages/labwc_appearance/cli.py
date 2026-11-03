"""Arrow-navigable Computer Management appearance submenu."""
from __future__ import annotations
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from managed_workflows.process import environment
from .catalog import COMPONENTS, LABELS
from .engine import apply_choice
from .themes import FAMILIES, public_catalog
from .icon_catalog import (ICON_COLLECTIONS, POINTER_COLLECTIONS,
                           available_collections,
                           public_catalog as asset_catalog)


MENU_ICON_REGISTRY = Path('/usr/local/share/labwc-appearance/menu-icons.json')
ICON_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z')
MENU_ICON_KEYS = frozenset({
    'Desktop Appearance', 'Desktop Themes', 'Fuzzel Themes', 'Waybar Themes',
    'Taskview Themes', 'Waycal Themes', 'Crystal-Dock Themes', 'GtkGreet Themes',
    'Terminal Themes', 'Swaylock Themes', 'Mako Themes', 'Icon Themes',
    'Pointer Themes', 'Reset Icon Theme', 'Reset Mouse Theme',
    'Reset Appearance (All)', 'Reset Appearance', 'Reset Theme', 'Help',
    'Back', 'Cancel', 'Apply', 'default',
})


def _icon(value: object) -> str:
    return value if isinstance(value, str) and ICON_NAME.fullmatch(value) else ''


def load_menu_icons() -> dict[str, str]:
    try:
        info = MENU_ICON_REGISTRY.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != 0o644 or info.st_nlink != 1
                or info.st_size > 16384):
            return {}
        data = json.loads(MENU_ICON_REGISTRY.read_text(encoding='utf-8'))
        icons = data.get('icons', {}) if isinstance(data, dict) else {}
        if not isinstance(icons, dict):
            return {}
        return {key: _icon(icons.get(key)) for key in MENU_ICON_KEYS}
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        return {}


MENU_ICONS = load_menu_icons()
DEFAULT_ICON = MENU_ICONS.get('default', '')
HELP = '/usr/local/bin/labwc-help'


def choose(labels: list[str], prompt: str) -> str | None:
    rows = ''.join(label + (('\0icon\x1f' + icon) if (icon := MENU_ICONS.get(label, DEFAULT_ICON)) else '') + '\n'
                   for label in labels)
    picker_environment = environment(desktop=True)
    # Appearance rows already use Fuzzel's native NUL/US icon metadata. Keep
    # the wrapper in transparent mode and use newline-delimited records; the
    # wrapper's --dmenu0 protocol is for NUL-separated label records and would
    # expose the metadata as literal text.
    picker_environment.update(LABWC_FUZZEL_MANAGED_ICONS='0', LABWC_FUZZEL_ROOT_MENU='0')
    process = subprocess.run(['/usr/local/bin/labwc-fuzzel', 'computer-management',
                              '--dmenu', '--prompt', prompt + ' > '],
                             input=rows, text=True, encoding='utf-8',
                             stdout=subprocess.PIPE, env=picker_environment, check=False)
    if process.returncode in (3, 130):
        raise SystemExit(3)
    if process.returncode == 1:
        return None
    if process.returncode != 0:
        raise RuntimeError('appearance menu picker failed')
    selected = process.stdout.rstrip('\0\n')
    if selected not in labels:
        raise ValueError('menu returned an unknown action')
    return selected


def open_help(topic: str) -> None:
    if topic != 'desktop.appearance':
        raise ValueError('unsupported appearance Help topic')
    help_environment = environment(desktop=True)
    # A menu action may carry the transient wait flag used by Fuzzel. Help is
    # informational and must not keep its caller blocked until the window
    # closes. Keep the launcher environment to the approved desktop subset;
    # never forward arbitrary session variables or credentials.
    help_environment.pop('LABWC_MENU_ACTION_WAIT', None)
    try:
        result = subprocess.run([HELP, '--topic', topic], env=help_environment,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, check=False, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Help launch timed out') from error
    if result.returncode:
        raise RuntimeError('Help launch failed')


def perform(args: list[str]) -> None:
    needs_admin = args[1] in ('greeter', 'all', 'icon')
    prompt = 'Apply appearance (greeter changes require administrator authentication)' if needs_admin else 'Apply native appearance'
    if choose(['Cancel', 'Apply'], prompt) != 'Apply':
        return
    try:
        notes = apply_choice(args)
        print('Appearance applied.' + ('\n' + '\n'.join(notes) if notes else ''))
        if notes:
            choose(['Back'], 'Applied; ' + ('greeter changes appear at next login' if needs_admin else 'existing apps may need reopening'))
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        text = ''.join(c if c.isprintable() else '?' for c in str(error))
        print('Desktop Appearance: ' + text, file=sys.stderr)
        choose(['Back'], 'Not completed: ' + text[:160])


def desktop_themes() -> None:
    families = {family.label: family for family in FAMILIES}
    while True:
        selected = choose([*families, 'Reset Theme', 'Back'], 'Desktop Themes')
        if selected in (None, 'Back'):
            return
        if selected == 'Reset Theme':
            perform(['theme', 'reset'])
            continue
        family = families[selected]
        variants = {theme.label: theme.identity for theme in family.variants}
        while True:
            selected = choose([*variants, 'Back'], family.label)
            if selected in (None, 'Back'):
                break
            perform(['theme', variants[selected]])


def asset_themes(collections, component: str, prompt: str, reset_label: str) -> None:
    families = {collection.label: collection for collection in available_collections(
        collections, pointer=component == 'pointer')}
    while True:
        selected = choose([*families, reset_label, 'Back'], prompt)
        if selected in (None, 'Back'):
            return
        if selected == reset_label:
            perform(['reset', component])
            continue
        collection = families[selected]
        variants = {name: name for name in collection.variants}
        while True:
            chosen = choose([*variants, 'Back'], collection.label)
            if chosen in (None, 'Back'):
                break
            perform(['apply', component, variants[chosen]])


def main(argv: list[str]) -> int:
    if argv == ['--gtk']:
        from .editor import main as editor_main
        return editor_main()
    if argv == ['--catalog']:
        print(json.dumps({'themes': public_catalog(), 'assets': asset_catalog(),
                          'profiles': {key: LABELS for key in COMPONENTS},
                          'reset': [*COMPONENTS, 'theme', 'icon', 'pointer', 'desktop', 'all']}, indent=2))
        return 0
    if argv:
        for note in apply_choice(argv):
            print(note)
        return 0
    groups = {'Desktop Themes': 'theme', 'Icon Themes': 'icon',
              'Pointer Themes': 'pointer', **{title: key for key, title in COMPONENTS.items()}}
    while True:
        group = choose([*groups, 'Reset Appearance (All)', 'Help', 'Back'], 'Desktop Appearance')
        if group in (None, 'Back'):
            break
        if group == 'Help':
            open_help('desktop.appearance')
            continue
        if group == 'Reset Appearance (All)':
            perform(['reset', 'all'])
            continue
        component = groups[group]
        if component == 'theme':
            desktop_themes()
        elif component == 'icon':
            asset_themes(ICON_COLLECTIONS, 'icon', 'Icon Themes', 'Reset Icon Theme')
        elif component == 'pointer':
            asset_themes(POINTER_COLLECTIONS, 'pointer', 'Pointer Themes', 'Reset Mouse Theme')
        else:
            entries = {label: key for key, label in LABELS.items()}
            while True:
                selected = choose([*entries, 'Reset Appearance', 'Back'], group)
                if selected in (None, 'Back'):
                    break
                if selected == 'Reset Appearance':
                    perform(['reset', component])
                else:
                    perform(['apply', component, entries[selected]])
    return 0
