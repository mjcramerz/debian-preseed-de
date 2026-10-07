"""Polkit-authenticated greeter edits; no user paths, CSS or executable input."""
from __future__ import annotations
import os
from pathlib import Path
import pwd
import re
from managed_workflows.fs import Tree
from .catalog import LABELS, palette
from .defaults import load
from .editors import css
from .native import GREETER_FILES
from . import transaction

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
    if not argv or argv[0] not in ('apply', 'commit', 'rollback'):
        raise ValueError('invalid greeter transaction operation')
    action = argv[0]
    if len(argv) != (4 if action == 'apply' else 2):
        raise ValueError('invalid greeter transaction arguments')
    token = argv[-1]
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        raise ValueError('invalid greeter transaction token')
    STATE.mkdir(mode=0o700, exist_ok=True)
    with Tree(STATE, uid=0, private=True) as state, state.lock('greeter.lock'), Tree(Path('/etc/greetd'), uid=0) as config:
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
        updates = {name: css(config.read(name).decode(), defaults['greeter'][name], colors).encode()
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
