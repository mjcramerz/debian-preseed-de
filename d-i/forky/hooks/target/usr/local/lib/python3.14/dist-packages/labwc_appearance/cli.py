"""Arrow-navigable Computer Management appearance submenu."""
from __future__ import annotations
import json
import subprocess
import sys
from managed_workflows.process import environment
from .catalog import COMPONENTS, LABELS
from .engine import apply_choice


def choose(labels: list[str], prompt: str) -> str | None:
    process = subprocess.run(['/usr/local/bin/labwc-fuzzel', 'computer-management',
                              '--dmenu', '--prompt', prompt + ' > '],
                             input='\n'.join(labels) + '\n', text=True,
                             stdout=subprocess.PIPE, env=environment(desktop=True), check=False)
    if process.returncode in (1, 130):
        return None
    if process.returncode != 0:
        raise RuntimeError('appearance menu picker failed')
    selected = process.stdout.rstrip('\n')
    if selected not in labels:
        raise ValueError('menu returned an unknown action')
    return selected


def perform(args: list[str]) -> None:
    needs_admin = args[0] == 'mode' or args[1] in ('greeter', 'all')
    prompt = 'Apply appearance (greeter changes require administrator authentication)' if needs_admin else 'Apply native appearance'
    if choose(['Cancel', 'Apply'], prompt) != 'Apply':
        return
    try:
        notes = apply_choice(args)
        print('Appearance applied.' + ('\n' + '\n'.join(notes) if notes else ''))
        if notes:
            choose(['Back'], 'Applied; reopen existing apps if needed. Greeter changes are used at next login')
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        text = ''.join(c if c.isprintable() else '?' for c in str(error))
        print('Desktop Appearance: ' + text, file=sys.stderr)
        choose(['Back'], 'Not completed: ' + text[:160])


def main(argv: list[str]) -> int:
    if argv == ['--catalog']:
        print(json.dumps({'mode': ['dark', 'light', 'reset'],
                          'profiles': {key: LABELS for key in COMPONENTS},
                          'reset': [*COMPONENTS, 'mode', 'all']}, indent=2))
        return 0
    if argv:
        for note in apply_choice(argv):
            print(note)
        return 0
    groups = {'Dark / Light Mode': 'mode', **{title: key for key, title in COMPONENTS.items()}}
    while True:
        group = choose([*groups, 'Reset Appearance (All)', 'Back'], 'Desktop Appearance')
        if group in (None, 'Back'):
            break
        if group == 'Reset Appearance (All)':
            perform(['reset', 'all'])
            continue
        component = groups[group]
        if component == 'mode':
            entries = {'Dark': 'dark', 'Light': 'light', 'Reset Appearance': 'reset'}
            selected = choose([*entries, 'Back'], group)
            if selected not in (None, 'Back'):
                perform(['mode', entries[selected]])
        else:
            entries = {label: key for key, label in LABELS.items()}
            selected = choose([*entries, 'Reset Appearance', 'Back'], group)
            if selected == 'Reset Appearance':
                perform(['reset', component])
            elif selected not in (None, 'Back'):
                perform(['apply', component, entries[selected]])
    return 0
