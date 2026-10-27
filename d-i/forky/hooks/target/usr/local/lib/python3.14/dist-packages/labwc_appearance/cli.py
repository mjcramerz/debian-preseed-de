"""Arrow-navigable Computer Management appearance submenu."""
from __future__ import annotations
import json
import subprocess
import sys
from managed_workflows.process import environment
from .catalog import COMPONENTS, LABELS
from .engine import apply_choice
from .themes import FAMILIES, public_catalog
from .icon_catalog import (ICON_COLLECTIONS, POINTER_COLLECTIONS,
                           available_collections,
                           public_catalog as asset_catalog)


MENU_ICONS = {
    'Desktop Appearance': 'preferences-desktop-display',
    'Desktop Themes': 'preferences-desktop-theme',
    'Fuzzel Themes': 'system-search',
    'Waybar Themes': 'preferences-system-windows',
    'Taskview Themes': 'view-grid',
    'Waycal Themes': 'x-office-calendar-symbolic',
    'Crystal-Dock Themes': 'view-refresh',
    'GtkGreet Themes': 'system-users',
    'Terminal Themes': 'utilities-terminal',
    'Mako Themes': 'preferences-desktop-notification',
    'Icon Themes': 'preferences-desktop-icons',
    'Pointer Themes': 'input-mouse',
    'Reset Icon Theme': 'view-refresh',
    'Reset Mouse Theme': 'view-refresh',
    'Reset Appearance (All)': 'view-refresh',
    'Reset Appearance': 'view-refresh',
    'Reset Theme': 'view-refresh',
    'Back': 'go-previous',
    'Cancel': 'window-close',
    'Apply': 'dialog-ok',
}
DEFAULT_ICON = 'preferences-desktop-theme'


def choose(labels: list[str], prompt: str) -> str | None:
    rows = ''.join(label + '\0icon\x1f' + MENU_ICONS.get(label, DEFAULT_ICON) + '\n'
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
    if argv == ['--catalog']:
        print(json.dumps({'themes': public_catalog(), 'assets': asset_catalog(),
                          'profiles': {key: LABELS for key in COMPONENTS},
                          'reset': [*COMPONENTS, 'theme', 'icon', 'pointer', 'all']}, indent=2))
        return 0
    if argv:
        for note in apply_choice(argv):
            print(note)
        return 0
    groups = {'Desktop Themes': 'theme', 'Icon Themes': 'icon',
              'Pointer Themes': 'pointer', **{title: key for key, title in COMPONENTS.items()}}
    while True:
        group = choose([*groups, 'Reset Appearance (All)', 'Back'], 'Desktop Appearance')
        if group in (None, 'Back'):
            break
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
