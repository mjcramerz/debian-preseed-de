"""Polkit-authenticated greeter edits; no user paths, CSS or executable input."""
from __future__ import annotations
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import json
from managed_workflows.fs import Tree
from .catalog import LABELS, palette
from .defaults import load
from .editors import css
from .native import GREETER_FILES
from . import fields, transaction

STATE = Path('/var/lib/labwc-appearance')


def caller() -> int:
    value = os.environ.get('PKEXEC_UID', '')
    if os.getuid() != 0 or os.geteuid() != 0 or not re.fullmatch(r'[1-9][0-9]{0,9}', value):
        raise ValueError('greeter appearance requires administrator authentication')
    uid = int(value)
    pwd.getpwuid(uid)
    return uid


def main(argv: list[str]) -> int:
    uid = caller()
    if not argv or argv[0] not in ('apply', 'commit', 'rollback', 'cache-icons', 'fields'):
        raise ValueError('invalid greeter transaction operation')
    action = argv[0]
    if action == 'fields':
        if len(argv) != 1:
            raise ValueError('invalid greeter field operation arguments')
        payload = sys.stdin.buffer.read(fields.MAX_INPUT_BYTES + 1)
        if len(payload) > fields.MAX_INPUT_BYTES:
            raise ValueError('greeter appearance update is too large')
        try:
            request = json.loads(payload.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError('invalid greeter appearance update') from error
        updates = request.get('updates') if isinstance(request, dict) else None
        if (not isinstance(updates, dict) or not updates or len(updates) > fields.MAX_FIELDS
                or any(not isinstance(key, str) or not isinstance(value, str)
                       for key, value in updates.items())):
            raise ValueError('invalid greeter appearance update fields')
        fields.apply_root_greeter(updates)
        return 0
    if action == 'cache-icons':
        if len(argv) != 3 or not re.fullmatch(r'[0-9a-f]{32}', argv[2]):
            raise ValueError('invalid icon cache transaction arguments')
        from .icon_catalog import require_icon_installed
        icon_directory = require_icon_installed(argv[1])
        subprocess.run(
            ['/usr/bin/gtk-update-icon-cache', '--force', '--index-only', str(icon_directory)],
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=True, timeout=30,
        )
        return 0
    if len(argv) != (4 if action == 'apply' else 2):
        raise ValueError('invalid greeter transaction arguments')
    token = argv[-1]
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        raise ValueError('invalid greeter transaction token')
    STATE.mkdir(mode=0o700, exist_ok=True)
    with Tree(STATE, uid=0, private=True) as state, state.lock('greeter.lock'), Tree(Path('/etc/greetd'), uid=0) as config:
        if state.json('fields-pending.json') is not None:
            raise RuntimeError('a greeter color transaction needs recovery in the GTK appearance editor')
        pending = state.json('pending.json')
        if pending is not None:
            transaction.validate(pending, set(GREETER_FILES))
            if pending.get('caller') != uid or pending['token'] != token:
                raise RuntimeError('another greeter transaction needs recovery by its initiating account')
        if action in ('commit', 'rollback'):
            if pending is None:
                return 0  # idempotent recovery after an interrupted pkexec reply
            if action == 'rollback':
                transaction.rollback(config, pending, mode=0o644)
            else:
                for name, data in pending['new'].items():
                    if config.read(name) != transaction.decoded(data):
                        raise RuntimeError('greeter CSS changed before commit; journal retained')
            state.write('pending.json', None)
            return 0
        profile, mode = argv[1:3]
        if profile != 'reset' and profile not in LABELS or mode not in ('dark', 'light'):
            raise ValueError('invalid greeter appearance choice')
        if pending is not None:
            # Retry is safe only if the same prepared native files are present.
            for name, data in pending['new'].items():
                if config.read(name) != transaction.decoded(data):
                    raise RuntimeError('interrupted greeter apply requires rollback')
            return 0
        defaults = load()
        colors = None if profile == 'reset' else palette(profile, mode)
        updates = {name: css(config.read(name).decode(), defaults['greeter'][name], colors, glow=True).encode()
                   for name in GREETER_FILES}
        journal = transaction.plan(config, updates, token)
        journal['caller'] = uid
        state.put_json('pending.json', journal)
        try:
            transaction.apply(config, journal, mode=0o644)
        except BaseException:
            transaction.rollback(config, journal, mode=0o644)
            state.write('pending.json', None)
            raise
        # Commit/rollback is coordinated by the ordinary user's durable journal.
        # Deliberately never restart greetd: that would terminate their session.
    return 0
