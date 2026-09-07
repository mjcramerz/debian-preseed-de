#!/usr/bin/env python3
"""Compare an offline Codex publication with its verified staging tree.

Immutable files must match bytes, ownership and modes. Only named account state
is mutable. No Git command, hook, filter, config include or symlink is executed.
All traversal and regular-file reads use directory descriptors and NOFOLLOW.
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from dataclasses import dataclass

MAX_ENTRIES = 200_000
MAX_FILE = 1 << 30
MAX_TOTAL = 8 << 30
MUTABLE_TREES = frozenset({
    'home/sessions', 'home/shell_snapshots', 'home/archived_sessions', 'home/memories',
})
MUTABLE_FILES = frozenset({
    'home/auth.json', 'home/history.jsonl', 'home/session_index.jsonl',
    'home/external_agent_session_imports.json',
    'home/app-server-control/app-server-startup.lock',
})


class StateError(ValueError):
    """Unsafe or conflicting publication (messages never contain file contents)."""


@dataclass(frozen=True)
class Entry:
    kind: str
    uid: int
    gid: int
    mode: int
    digest: str = ''
    link: str = ''


def snapshot(root: Path) -> dict[str, Entry]:
    """Read a bounded tree without following symlinks or accepting hard links."""
    entries: dict[str, Entry] = {}
    total = 0
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    def walk(fd: int, prefix: str) -> None:
        nonlocal total
        for name in sorted(os.listdir(fd)):
            if any(ord(c) < 32 or ord(c) == 127 for c in name):
                raise StateError('control character in a managed filename')
            rel = f'{prefix}/{name}' if prefix else name
            if len(entries) >= MAX_ENTRIES:
                raise StateError('managed tree exceeds entry limit')
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                entries[rel] = Entry('link', info.st_uid, info.st_gid, mode,
                                     link=os.readlink(name, dir_fd=fd))
            elif stat.S_ISDIR(info.st_mode):
                child = os.open(name, flags, dir_fd=fd)
                try:
                    actual = os.fstat(child)
                    if (info.st_dev, info.st_ino) != (actual.st_dev, actual.st_ino):
                        raise StateError('managed directory changed during verification')
                    if actual.st_dev != root_device:
                        raise StateError('unexpected mount inside managed repository')
                    entries[rel] = Entry('dir', info.st_uid, info.st_gid, mode)
                    walk(child, rel)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1 or info.st_size > MAX_FILE:
                    raise StateError('hard-linked or oversized managed file')
                total += info.st_size
                if total > MAX_TOTAL:
                    raise StateError('managed tree exceeds byte limit')
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                try:
                    before = os.fstat(child)
                    if (info.st_dev, info.st_ino, info.st_nlink) != (before.st_dev, before.st_ino, before.st_nlink):
                        raise StateError('managed file changed during verification')
                    digest = hashlib.sha256()
                    read = 0
                    while data := os.read(child, 1024 * 1024):
                        read += len(data)
                        if read > MAX_FILE:
                            raise StateError('managed file grew beyond byte limit')
                        digest.update(data)
                    after = os.fstat(child)
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise StateError('managed file changed during verification')
                    entries[rel] = Entry('file', info.st_uid, info.st_gid, mode, digest.hexdigest())
                finally:
                    os.close(child)
            else:
                raise StateError('special file in managed repository')

    fd = os.open(root, flags)
    try:
        info = os.fstat(fd)
        root_device = info.st_dev
        entries['.'] = Entry('dir', info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
        walk(fd, '')
    finally:
        os.close(fd)
    return entries


def read_metadata(root: Path, name: str, limit: int) -> str:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(root, flags)
    git_fd = -1
    file_fd = -1
    try:
        git_fd = os.open('.git', flags, dir_fd=fd)
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=git_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise StateError('invalid Git metadata file')
        data = os.read(file_fd, limit + 1)
        if len(data) > limit:
            raise StateError('oversized Git metadata')
        return data.decode('utf-8')
    finally:
        for opened in (file_fd, git_fd, fd):
            if opened >= 0:
                os.close(opened)


def validate_git(root: Path, entries: dict[str, Entry], uid: int, gid: int,
                 commit: str, url: str) -> None:
    if '.git' not in entries:
        raise StateError('missing Git metadata')
    for name, entry in entries.items():
        if name != '.git' and not name.startswith('.git/'):
            continue
        expected_mode = 0o750 if entry.kind == 'dir' else 0o640
        if entry.kind not in {'dir', 'file'} or (entry.uid, entry.gid, entry.mode) != (uid, gid, expected_mode):
            raise StateError('unsafe Git metadata ownership, mode or type')
    if read_metadata(root, 'HEAD', 128).strip() != commit:
        raise StateError('existing repository is not detached at the pinned commit')
    config = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        config.read_string(read_metadata(root, 'config', 65536))
    except configparser.Error as exc:
        raise StateError('invalid Git config') from exc
    if config.defaults():
        raise StateError('unexpected Git config defaults')
    for section in config.sections():
        if section == 'core':
            allowed = {'repositoryformatversion', 'filemode', 'bare', 'logallrefupdates', 'ignorecase', 'precomposeunicode'}
        elif section == 'remote "origin"':
            allowed = {'url', 'fetch', 'tagopt'}
        elif section.startswith('branch "') and section.endswith('"'):
            allowed = {'remote', 'merge'}
            if config.get(section, 'remote', fallback='') != 'origin':
                raise StateError('unexpected Git branch remote')
        else:
            raise StateError('unexpected Git config section (includes and hooks are forbidden)')
        if set(config[section]) - allowed:
            raise StateError('unexpected Git config option')
    if config.get('remote "origin"', 'url', fallback='') != url:
        raise StateError('existing repository origin differs from policy')
    if config.get('core', 'bare', fallback='false').lower() != 'false':
        raise StateError('bare repository is not an installed worktree')


def runtime_tree(name: str) -> bool:
    return any(name == root or name.startswith(root + '/') for root in MUTABLE_TREES)


def validate_link(name: str, target: str, codex_root: str) -> None:
    managed = {
        'home/packages': codex_root + '/packages',
        'home/app-server-control/app-server-control.sock': codex_root + '/sockets/app-server-control.sock',
    }
    if name in managed:
        if target != managed[name]:
            raise StateError('managed runtime link points outside its assigned destination')
        return
    if target.startswith('/'):
        raise StateError('absolute symlink in repository content')
    # Lexically resolve relative symlinks; no filesystem traversal is necessary.
    parts: list[str] = list(PurePosixPath(name).parent.parts)
    for part in PurePosixPath(target).parts:
        if part == '..':
            if not parts:
                raise StateError('repository symlink escapes its root')
            parts.pop()
        elif part != '.':
            parts.append(part)


def compare_trees(expected: Path, actual: Path, uid: int, gid: int, commit: str,
                  url: str, codex_root: str = '/data/codex') -> None:
    wanted = snapshot(expected)
    found = snapshot(actual)
    validate_git(actual, found, uid, gid, commit, url)
    for name, entry in wanted.items():
        if entry.kind == 'link':
            validate_link(name, entry.link, codex_root)
    for name, entry in found.items():
        if name == '.git' or name.startswith('.git/'):
            continue
        if runtime_tree(name):
            if (entry.uid, entry.gid) != (uid, gid):
                raise StateError('mutable state is owned by an unexpected account')
            if entry.kind == 'dir' and entry.mode in {0o700, 0o2770}:
                pass
            elif entry.kind == 'file' and entry.mode in {0o600, 0o660}:
                pass
            else:
                raise StateError('unsafe mutable state type or permissions')
            if name == 'home/memories/.git' and entry.digest != hashlib.sha256(b'').hexdigest():
                raise StateError('memories Git boundary marker was altered')
            # Named root directories and boundary marker retain their exact policy.
            if name in wanted and name in MUTABLE_TREES | {'home/memories/.git'}:
                if entry != wanted[name]:
                    raise StateError('mutable state root differs from policy')
            continue
        if name not in wanted:
            raise StateError('unexpected state outside the mutable-state allowlist')
        if name in MUTABLE_FILES:
            w = wanted[name]
            if entry.kind != 'file' or (entry.uid, entry.gid, entry.mode) != (w.uid, w.gid, w.mode):
                raise StateError('private or shared runtime file has unsafe metadata')
        elif entry != wanted[name]:
            raise StateError('immutable repository content or metadata differs from its pin')
    for name in wanted:
        if name == '.git' or name.startswith('.git/'):
            continue
        if name not in found:
            raise StateError('required repository or runtime path is missing')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', required=True, type=Path)
    parser.add_argument('--actual', required=True, type=Path)
    parser.add_argument('--uid', required=True, type=int)
    parser.add_argument('--gid', required=True, type=int)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--codex-root', default='/data/codex')
    args = parser.parse_args()
    try:
        compare_trees(args.expected, args.actual, args.uid, args.gid, args.commit, args.url, args.codex_root)
    except (OSError, UnicodeError, StateError) as exc:
        # OSError may contain a filename, but never credential bytes or commands.
        print(f'codex-state: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
