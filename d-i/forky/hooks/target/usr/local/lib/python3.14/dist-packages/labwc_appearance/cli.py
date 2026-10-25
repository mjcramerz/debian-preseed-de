"""Arrow-navigable Computer Management appearance submenu."""
from __future__ import annotations
import json
import subprocess
import sys
from managed_workflows.process import environment
from .catalog import COMPONENTS, LABELS
from .engine import apply_choice
from .themes import FAMILIES, public_catalog


def choose(labels: list[str], prompt: str) -> str | None:
    process = subprocess.run(['/usr/local/bin/labwc-fuzzel', 'computer-management',
                              '--dmenu', '--prompt', prompt + ' > '],
                             input='\n'.join(labels) + '\n', text=True,
                             stdout=subprocess.PIPE, env=environment(desktop=True), check=False)
    if process.returncode in (3, 130):
        raise SystemExit(3)
    if process.returncode == 1:
        return None
    if process.returncode != 0:
        raise RuntimeError('appearance menu picker failed')
    selected = process.stdout.rstrip('\n')
    if selected not in labels:
        raise ValueError('menu returned an unknown action')
    return selected


def perform(args: list[str]) -> None:
    needs_admin = args[1] in ('greeter', 'all')
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


def main(argv: list[str]) -> int:
    if argv == ['--catalog']:
        print(json.dumps({'themes': public_catalog(),
                          'profiles': {key: LABELS for key in COMPONENTS},
                          'reset': [*COMPONENTS, 'theme', 'all']}, indent=2))
        return 0
    if argv:
        for note in apply_choice(argv):
            print(note)
        return 0
    groups = {'Desktop Themes': 'theme', **{title: key for key, title in COMPONENTS.items()}}
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
