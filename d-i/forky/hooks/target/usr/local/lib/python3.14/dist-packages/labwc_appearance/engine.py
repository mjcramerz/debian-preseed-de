"""Per-account coordinator with rollback across native files, dconf and greeter."""
from __future__ import annotations
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import uuid
from managed_workflows.fs import Tree
from managed_workflows.process import checked
from .catalog import COMPONENTS, DEFAULT_PROFILE, LABELS
from .defaults import load
from .native import identify, render, user_paths
from . import transaction, service

STATE = '.local/state/labwc-appearance'
JOURNAL = STATE + '/pending.json'
CONFIG = STATE + '/state.json'
SCHEMA = 'org.gnome.desktop.interface'
KEYS = ('color-scheme', 'gtk-theme')
ROOT_HELPER = '/usr/local/libexec/labwc-appearance-greeter'


def settings(values: dict | None = None) -> dict:
    if values is None:
        return {key: checked(['/usr/bin/gsettings', 'get', SCHEMA, key], capture=True).strip() for key in KEYS}
    if set(values) != set(KEYS):
        raise ValueError('unexpected desktop settings keys')
    for key, value in values.items():
        if not isinstance(value, str) or not re.fullmatch(r"'[A-Za-z0-9_. +:-]{1,100}'", value):
            raise ValueError('invalid native desktop setting')
        checked(['/usr/bin/gsettings', 'set', SCHEMA, key, value], capture=True)
    observed = settings()
    if observed != values:
        raise RuntimeError('desktop settings backend did not retain the requested appearance')
    return observed


def privileged(action: str, token: str, profile: str = '', mode: str = '') -> None:
    args = [action, profile, mode, token] if action == 'apply' else [action, token]
    checked(['/usr/bin/pkexec', ROOT_HELPER, *args], timeout=180)


def initial(defaults: dict) -> dict:
    return {'schema': 1, 'mode': defaults['mode'], 'modeDefault': True,
            'profiles': dict.fromkeys(COMPONENTS)}


def validate_state(value):
    if (not isinstance(value, dict) or value.get('schema') != 1 or value.get('mode') not in ('dark', 'light') or
            type(value.get('modeDefault')) is not bool or not isinstance(value.get('profiles'), dict) or
            set(value['profiles']) != set(COMPONENTS) or
            any(p is not None and p not in LABELS for p in value['profiles'].values())):
        raise ValueError('invalid saved appearance selection')
    return value


def selection(previous: dict, argv: list[str], defaults: dict) -> tuple[dict, set[str], bool]:
    state = json.loads(json.dumps(validate_state(previous)))
    affected = set()
    greeter = False
    if len(argv) == 2 and argv[0] == 'mode' and argv[1] in ('dark', 'light', 'reset'):
        mode = argv[1]
        state['mode'] = defaults['mode'] if mode == 'reset' else mode
        state['modeDefault'] = mode == 'reset'
        affected = {'mode', 'fuzzel', 'waybar', 'dock', 'terminal'}
        # An explicit global mode also adjusts configured component profiles.
        for name in COMPONENTS:
            if state['profiles'][name] is None and mode != 'reset':
                state['profiles'][name] = DEFAULT_PROFILE
        greeter = True
    elif len(argv) == 3 and argv[0] == 'apply' and argv[1] in COMPONENTS and argv[2] in LABELS:
        name = argv[1]
        state['profiles'][name] = argv[2]
        if name == 'greeter':
            greeter = True
        else:
            affected.add(name)
    elif len(argv) == 2 and argv[0] == 'reset' and argv[1] in (*COMPONENTS, 'mode', 'all'):
        if argv[1] == 'mode':
            return selection(previous, ['mode', 'reset'], defaults)
        if argv[1] == 'all':
            state = initial(defaults)
            affected = {'mode', 'fuzzel', 'waybar', 'dock', 'terminal'}
            greeter = True
        elif argv[1] == 'greeter':
            state['profiles']['greeter'] = None
            greeter = True
        else:
            state['profiles'][argv[1]] = None
            affected.add(argv[1])
    else:
        raise ValueError('usage: labwc-desktop-appearance [mode dark|light|reset | apply COMPONENT PROFILE | reset COMPONENT|all]')
    return state, affected, greeter


def recover(home: Tree) -> bool:
    journal = home.json(JOURNAL)
    if journal is None:
        return False
    transaction.validate(journal, user_paths() | {CONFIG})
    if type(journal.get('greeter')) is not bool or type(journal.get('dockRunning')) is not bool:
        raise ValueError('invalid appearance recovery metadata')
    for name in ('oldSettings', 'newSettings'):
        if journal.get(name) is not None:
            if not isinstance(journal[name], dict) or set(journal[name]) != set(KEYS):
                raise ValueError('invalid desktop settings recovery metadata')
    committed = journal['phase'] == 'committed'
    started = journal.get('filesStarted', True)
    if type(started) is not bool:
        raise ValueError('invalid appearance write-phase marker')
    root_error = None
    if journal['greeter'] and started:
        try:
            privileged('commit' if committed else 'rollback', journal['token'])
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            root_error = error
    if not committed and started:
        transaction.rollback(home, journal)
        if journal['oldSettings'] is not None:
            settings(journal['oldSettings'])
    if journal['dockRunning']:
        service.dock_start()
    if root_error is not None:
        raise RuntimeError('local recovery finished; rerun Desktop Appearance to authenticate greeter recovery') from root_error
    home.write(JOURNAL, None)
    return True


def apply_choice(argv: list[str]) -> list[str]:
    if os.getuid() == 0 or os.getuid() != os.geteuid():
        raise ValueError('run Desktop Appearance as your ordinary desktop account')
    account = pwd.getpwuid(os.getuid())
    defaults = load()
    with Tree(Path(account.pw_dir)) as home:
        home.mkdir(STATE)
        with home.lock(STATE + '/appearance.lock'):
            recover(home)
            previous = validate_state(home.json(CONFIG, initial(defaults)))
            current, affected, greeter = selection(previous, argv, defaults)
            # Capture dock liveness in the journal *before* stopping it. Recovery
            # can restart it even after a power failure at the next invocation.
            dock_running = 'dock' in affected and service.active('crystal-dock.service')
            token = uuid.uuid4().hex
            old_settings = settings() if 'mode' in affected else None
            new_settings = None
            if old_settings is not None:
                new_settings = defaults['settings'] if current['modeDefault'] else {
                    'color-scheme': "'prefer-" + current['mode'] + "'",
                    'gtk-theme': "'Adwaita-dark'" if current['mode'] == 'dark' else "'Adwaita'"}
            updates = {}
            for path, baseline in defaults['files'].items():
                component, _ = identify(path)
                if component not in affected:
                    continue
                raw = home.read(path, missing=True)
                source = raw.decode('utf-8') if raw is not None else baseline or ''
                profile = (None if current['modeDefault'] else DEFAULT_PROFILE) if component == 'mode' else current['profiles'][component]
                value = render(path, source, baseline, profile, current['mode'], home.root)
                updates[path] = None if value is None else value.encode('utf-8')
            updates[CONFIG] = (json.dumps(current, sort_keys=True, indent=2) + '\n').encode()
            journal = transaction.plan(home, updates, token)
            journal.update(greeter=greeter, dockRunning=dock_running, filesStarted=False,
                           oldSettings=old_settings, newSettings=new_settings)
            transaction.validate(journal, user_paths() | {CONFIG})
            home.put_json(JOURNAL, journal)
            committed = False
            try:
                if dock_running:
                    service.dock_stop()
                    # QSettings shutdown may legitimately save other native keys.
                    # Re-render against the now-quiescent file to preserve them.
                    for path, baseline in defaults['files'].items():
                        if identify(path)[0] == 'dock':
                            source = home.read(path).decode()
                            value = render(path, source, baseline, current['profiles']['dock'], current['mode'], home.root)
                            updates[path] = value.encode()
                    replacement = transaction.plan(home, updates, token)
                    journal.update(old=replacement['old'], new=replacement['new'])
                    home.put_json(JOURNAL, journal)
                # QSettings may have saved layout during shutdown. Until this
                # marker is durable recovery restarts the dock without undoing
                # legitimate shutdown writes; no appearance file was touched.
                journal['filesStarted'] = True
                home.put_json(JOURNAL, journal)
                transaction.apply(home, journal)
                if new_settings is not None:
                    settings(new_settings)
                if greeter:
                    privileged('apply', token, current['profiles']['greeter'] or 'reset', current['mode'])
                # Durable commit decision precedes root commit. Recovery either
                # finishes BOTH sides or rolls BOTH back, including lost replies.
                journal['phase'] = 'committed'
                home.put_json(JOURNAL, journal)
                committed = True
                if greeter:
                    privileged('commit', token)
                if dock_running:
                    service.dock_start()
                home.write(JOURNAL, None)
            except BaseException:
                if not committed:
                    recover(home)
                # A committed operation with a lost root reply remains journaled
                # for idempotent finalization, never incorrectly rolled back.
                raise
            warnings = service.refresh(affected)
            if 'terminal' in affected or 'mode' in affected:
                warnings.append('Existing terminals and applications may need reopening; running shells were not terminated.')
            if greeter:
                warnings.append('Greeter colors apply at the next login screen; the running session was not restarted.')
            return warnings
