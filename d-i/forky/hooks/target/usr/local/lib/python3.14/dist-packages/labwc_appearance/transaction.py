"""Durable appearance journals with bounded, allowlisted rollback records."""
from __future__ import annotations
import base64
import re
from managed_workflows.fs import Tree


def encoded(value: bytes | None) -> str | None:
    return None if value is None else base64.b64encode(value).decode('ascii')


def decoded(value: str | None) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 12 * 1024**2:
        raise ValueError('invalid transaction file image')
    return base64.b64decode(value, validate=True)


def plan(tree: Tree, updates: dict[str, bytes | None], token: str) -> dict:
    old, new = {}, {}
    for name, data in updates.items():
        before = tree.read(name, missing=True)
        if before != data:
            old[name], new[name] = encoded(before), encoded(data)
    return {'schema': 1, 'token': token, 'phase': 'prepared', 'old': old, 'new': new}


def validate(value, allowed: set[str]) -> dict:
    if (not isinstance(value, dict) or value.get('schema') != 1 or
            not re.fullmatch(r'[0-9a-f]{32}', str(value.get('token'))) or
            value.get('phase') not in ('prepared', 'committed')):
        raise ValueError('invalid appearance transaction journal')
    old, new = value.get('old'), value.get('new')
    if not isinstance(old, dict) or not isinstance(new, dict) or set(old) != set(new) or set(old) - allowed:
        raise ValueError('appearance transaction contains an unauthorized path')
    for data in [*old.values(), *new.values()]:
        decoded(data)
    return value


def check_current(tree: Tree, journal: dict, *, rollback: bool) -> None:
    for name in journal['new']:
        current = tree.read(name, missing=True)
        acceptable = (decoded(journal['new'][name]), decoded(journal['old'][name])) if rollback else (decoded(journal['old'][name]),)
        if current not in acceptable:
            raise RuntimeError('appearance file changed concurrently; journal retained: ' + name)


def apply(tree: Tree, journal: dict, *, mode: int = 0o600) -> None:
    check_current(tree, journal, rollback=False)
    for name, data in journal['new'].items():
        tree.write(name, decoded(data), mode=mode)


def rollback(tree: Tree, journal: dict, *, mode: int = 0o600) -> None:
    check_current(tree, journal, rollback=True)
    for name, data in reversed(list(journal['old'].items())):
        raw = decoded(data)
        if tree.read(name, missing=True) != raw:
            tree.write(name, raw, mode=mode)
