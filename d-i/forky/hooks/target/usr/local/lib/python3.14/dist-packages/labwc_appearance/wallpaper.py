"""Bounded image snapshots and authenticated, atomic greeter wallpaper updates."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import selectors
import sys
import time

import tinycss2

from managed_workflows.fs import Tree
from . import transaction

MAX_BYTES = 32 * 1024**2
ASSET_NAME = re.compile(r'waypaper-wallpaper-[0-9a-f]{64}\.(?:png|jpg)\Z')


def image_suffix(data: bytes) -> str:
    if not 8 <= len(data) <= MAX_BYTES:
        raise ValueError('wallpaper size must be between 8 bytes and 32 MiB')
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    raise ValueError('wallpaper must be PNG or JPEG')


def snapshot(value: str, home: Path) -> bytes:
    """Read only gallery/Pictures data, with pinned no-follow descriptors."""
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('invalid wallpaper path')
    path = Path(value).expanduser().resolve(strict=True)
    gallery = Path('/usr/share/backgrounds/desktop')
    if path.is_relative_to(gallery):
        root, uid = gallery, 0
    elif path.parent == Path('/etc/greetd') and ASSET_NAME.fullmatch(path.name):
        root, uid = path.parent, 0
    elif path.is_relative_to(home / 'Pictures'):
        root, uid = home / 'Pictures', os.getuid()
    else:
        raise ValueError('choose a wallpaper from the managed gallery or your Pictures directory')
    with Tree(root, uid=uid) as tree, tree.open_read(path.relative_to(root).as_posix(), limit=MAX_BYTES) as (stream, meta):
        if meta.st_mode & 0o111:
            raise ValueError('wallpaper must not be executable')
        data = stream.read(MAX_BYTES + 1)
    image_suffix(data)
    return data


def current_greeter() -> Path | None:
    """Read the committed public CSS; no per-user hint can override it."""
    with Tree(Path('/etc/greetd'), uid=0) as config:
        raw = config.read('gtkgreet.css', limit=transaction.MAX_IMAGE_BYTES)
    selected = None
    for rule in tinycss2.parse_stylesheet(raw.decode('utf-8')):
        if rule.type != 'qualified-rule' or tinycss2.serialize(rule.prelude).strip() != 'window':
            continue
        for item in tinycss2.parse_declaration_list(rule.content):
            if item.type != 'declaration' or item.lower_name != 'background-image':
                continue
            value = tinycss2.serialize(item.value).strip()
            match = re.fullmatch(r'url\("file:///etc/greetd/(waypaper-wallpaper-[0-9a-f]{64}\.(?:png|jpg))"\)', value)
            selected = Path('/etc/greetd') / match[1] if match else None
    return selected


def read_request() -> bytes:
    """Bound stdin streaming as well as the final image size."""
    deadline = time.monotonic() + 15
    chunks = []
    size = 0
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise ValueError('wallpaper input timed out')
            chunk = os.read(sys.stdin.fileno(), min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('wallpaper exceeds 32 MiB')
            chunks.append(chunk)
    data = b''.join(chunks)
    image_suffix(data)
    return data


def stylesheet(raw: bytes, name: str) -> bytes:
    """Change only the window image; retain the user's other CSS declarations."""
    rules = tinycss2.parse_stylesheet(raw.decode('utf-8'))
    if any(rule.type == 'error' for rule in rules):
        raise ValueError('greeter stylesheet has invalid CSS')
    value = f'url("file:///etc/greetd/{name}")'
    found = False
    for rule in rules:
        if rule.type != 'qualified-rule' or tinycss2.serialize(rule.prelude).strip() != 'window':
            continue
        declarations = tinycss2.parse_declaration_list(rule.content)
        if any(item.type == 'error' for item in declarations):
            raise ValueError('greeter window declarations have invalid CSS')
        # Appending after a background shorthand also makes its precedence clear.
        declarations = [item for item in declarations if not (
            item.type == 'declaration' and item.lower_name == 'background-image')]
        rule.content = tinycss2.parse_component_value_list(
            tinycss2.serialize(declarations) + '\n  background-image: ' + value + ';\n')
        found = True
    result = tinycss2.serialize(rules)
    if not found:
        result += '\nwindow { background-image: ' + value + '; }\n'
    return result.encode('utf-8')


def publish(state: Tree, config: Tree, data: bytes) -> None:
    """Caller holds greeter.lock. Publish an immutable image, then one CSS file.

    The previous CSS remains usable throughout image staging. A durable journal
    retains the previous CSS until the publication or exact rollback is proved.
    No user path is opened by root and no image decoder runs as root.
    """
    journal_name = 'wallpaper-pending.json'
    pending = state.json(journal_name)
    if pending is not None:
        transaction.validate(pending, {'gtkgreet.css'})
        transaction.rollback(config, pending, mode=0o644)
        transaction.check_current(config, pending, rollback=False)
        state.write(journal_name, None)
    if state.json('pending.json') is not None or state.json('fields-pending.json') is not None:
        raise RuntimeError('finish the pending greeter appearance transaction first')
    # Reject malformed input before pruning any previously published asset.
    suffix = image_suffix(data)
    # Prune only our unreferenced immutable assets, under the existing writer
    # lock. Keep all images referenced by either stylesheet, including custom CSS.
    references = b'\n'.join(config.read(name) for name in ('gtkgreet.css', 'gtkgreet-power.css'))
    count = 0
    with os.scandir(config.fd) as entries:
        for entry in entries:
            count += 1
            if count > 256:
                raise ValueError('greeter directory exceeds the wallpaper entry limit')
            if ASSET_NAME.fullmatch(entry.name) and entry.name.encode() not in references:
                config.write(entry.name, None)
    name = 'waypaper-wallpaper-' + hashlib.sha256(data).hexdigest() + '.' + suffix
    existing = config.read(name, limit=MAX_BYTES, missing=True)
    if existing is not None and existing != data:
        raise ValueError('greeter wallpaper asset does not match its content hash')
    if existing is None:
        config.write(name, data, mode=0o644, replace=False)
    candidate = stylesheet(config.read('gtkgreet.css', limit=transaction.MAX_IMAGE_BYTES), name)
    journal = transaction.plan(config, {'gtkgreet.css': candidate}, os.urandom(16).hex())
    state.put_json(journal_name, journal)
    try:
        transaction.apply(config, journal, mode=0o644)
        transaction.check_committed(config, journal)
    except BaseException as error:
        try:
            transaction.rollback(config, journal, mode=0o644)
            transaction.check_current(config, journal, rollback=False)
            state.write(journal_name, None)
        except BaseException as recovery:
            raise RuntimeError('greeter wallpaper outcome unknown; recovery retained at '
                               '/var/lib/labwc-appearance/wallpaper-pending.json') from recovery
        raise error
    state.write(journal_name, None)
