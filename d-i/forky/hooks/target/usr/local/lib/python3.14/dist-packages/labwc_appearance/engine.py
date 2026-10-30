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
from .catalog import COMPONENTS, LABELS
from .defaults import load
from .native import identify, render, render_asset, user_paths, ICON_MANAGED_FILES, POINTER_MANAGED_FILES
from .icon_catalog import ICON_NAMES, POINTER_NAMES, icon_name, pointer_name, require_icon_installed, require_pointer_installed
from .themes import VARIANTS as THEMES, variant as desktop_theme, require_installed
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
    args = ([action, profile, mode, token] if action == 'apply'
            else [action, profile, token] if action == 'cache-icons'
            else [action, token])
    checked(['/usr/bin/pkexec', ROOT_HELPER, *args], timeout=180)


def initial(defaults: dict) -> dict:
    return {'schema': 3, 'mode': defaults['mode'], 'theme': None,
            'profiles': dict.fromkeys(COMPONENTS),
            'icon_theme': defaults.get('icon_theme'),
            'pointer_theme': defaults.get('pointer_theme')}


def validate_state(value):
    if (not isinstance(value, dict) or value.get('schema') != 3 or
            value.get('mode') not in ('dark', 'light') or
            not isinstance(value.get('profiles'), dict) or
            set(value['profiles']) != set(COMPONENTS) or
            any(p is not None and (not isinstance(p, str) or p not in LABELS)
                for p in value['profiles'].values())):
        raise ValueError('invalid saved appearance selection')
    profiles = dict(value['profiles'])
    value = {**value, 'profiles': profiles}
    if (not isinstance(value.get('icon_theme'), str) or value['icon_theme'] not in ICON_NAMES or
            not isinstance(value.get('pointer_theme'), str) or value['pointer_theme'] not in POINTER_NAMES):
        raise ValueError('invalid saved icon or pointer theme selection')
    if 'theme' not in value:
        raise ValueError('saved appearance selection has no desktop theme field')
    theme = value.get('theme')
    if theme is not None and (not isinstance(theme, str) or theme not in THEMES or
                              value['mode'] != ('dark' if desktop_theme(theme).dark else 'light')):
        raise ValueError('invalid saved desktop theme selection')
    return value


def selection(previous: dict, argv: list[str], defaults: dict) -> tuple[dict, set[str], bool]:
    state = json.loads(json.dumps(validate_state(previous)))
    affected = set()
    greeter = False
    if len(argv) == 2 and argv[0] == 'theme' and argv[1] in (*THEMES, 'reset'):
        state['theme'] = None if argv[1] == 'reset' else argv[1]
        state['mode'] = defaults['mode'] if state['theme'] is None else (
            'dark' if desktop_theme(state['theme']).dark else 'light')
        affected = {'theme'}
    elif len(argv) == 3 and argv[0] == 'apply' and argv[1] in ('icon', 'pointer'):
        if argv[1] == 'icon':
            state['icon_theme'] = icon_name(argv[2])
        else:
            state['pointer_theme'] = pointer_name(argv[2])
        affected = {argv[1]}
    elif len(argv) == 3 and argv[0] == 'apply' and argv[1] in COMPONENTS and argv[2] in LABELS:
        name = argv[1]
        state['profiles'][name] = argv[2]
        if name == 'greeter':
            greeter = True
        else:
            affected.add(name)
    elif len(argv) == 2 and argv[0] == 'reset' and argv[1] in (*COMPONENTS, 'theme', 'icon', 'pointer', 'all'):
        if argv[1] == 'theme':
            return selection(previous, ['theme', 'reset'], defaults)
        if argv[1] == 'all':
            state = initial(defaults)
            affected = {'theme', 'icon', 'pointer', 'fuzzel', 'waybar', 'taskview', 'waycal', 'dock', 'terminal', 'mako'}
            greeter = True
        elif argv[1] == 'icon':
            state['icon_theme'] = defaults.get('icon_theme')
            affected.add('icon')
        elif argv[1] == 'pointer':
            state['pointer_theme'] = defaults.get('pointer_theme')
            affected.add('pointer')
        elif argv[1] == 'greeter':
            state['profiles']['greeter'] = None
            greeter = True
        else:
            state['profiles'][argv[1]] = None
            affected.add(argv[1])
    else:
        raise ValueError('usage: labwc-desktop-appearance [theme THEME_VARIANT|reset | apply COMPONENT PROFILE | apply icon NAME | apply pointer NAME | reset COMPONENT|theme|icon|pointer|all]')
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
            if home.json('.config/labwc/appearance-fields.pending.json') is not None:
                raise RuntimeError('a color transaction needs recovery in the GTK appearance editor')
            recover(home)
            previous = validate_state(home.json(CONFIG, initial(defaults)))
            current, affected, greeter = selection(previous, argv, defaults)
            if 'theme' in affected and current['theme'] is not None:
                require_installed(current['theme'])
            if 'icon' in affected:
                require_icon_installed(current['icon_theme'])
            if 'pointer' in affected:
                require_pointer_installed(current['pointer_theme'])
            # Capture dock liveness in the journal *before* stopping it. Recovery
            # can restart it even after a power failure at the next invocation.
            dock_running = 'dock' in affected and service.active('crystal-dock.service')
            token = uuid.uuid4().hex
            old_settings = settings() if 'theme' in affected else None
            new_settings = None
            if old_settings is not None:
                new_settings = defaults['settings'] if current['theme'] is None else {
                    'color-scheme': "'prefer-" + current['mode'] + "'",
                    'gtk-theme': "'" + desktop_theme(current['theme']).gtk + "'"}
            updates = {}
            for path, baseline in defaults['files'].items():
                component, base = identify(path)
                if (component not in affected and
                        not ('icon' in affected and base in ICON_MANAGED_FILES) and
                        not ('pointer' in affected and base in POINTER_MANAGED_FILES)):
                    continue
                raw = home.read(path, missing=True)
                # Optional Qt compatibility files may be absent on a target.
                # Preserve that absence instead of trying to render a setting
                # into an empty file during an icon-only transaction.
                if (raw is None and baseline is None and
                        base in ('qt5ct/qt5ct.conf', 'qt6ct/qt6ct.conf')):
                    continue
                if (raw is None and baseline is None and base == 'labwc/environment'
                        and argv[:2] in (['reset', 'pointer'], ['reset', 'all'])):
                    continue
                source = raw.decode('utf-8') if raw is not None else baseline or ''
                value = source
                if 'icon' in affected and base in ICON_MANAGED_FILES:
                    value = render_asset(base, value, baseline, 'icon', current['icon_theme'])
                if 'pointer' in affected and base in POINTER_MANAGED_FILES:
                    value = render_asset(base, value, baseline, 'pointer', current['pointer_theme'])
                if component in affected:
                    profile = current['theme'] if component == 'theme' else current['profiles'][component]
                    value = render(path, value, baseline, profile, current['mode'], home.root)
                else:
                    pass
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
                if 'icon' in affected:
                    privileged('cache-icons', token, current['icon_theme'])
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
            if 'terminal' in affected or 'theme' in affected:
                warnings.append('Existing terminals and applications may need reopening; running shells were not terminated.')
            if greeter:
                warnings.append('Greeter colors apply at the next login screen; the running session was not restarted.')
            return warnings
