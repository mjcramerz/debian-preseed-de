"""Private XDG state, bounded validation and atomic publication under one lock."""
from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import secrets
import stat
import threading

from .catalog import decode

DEFAULT = {'version': 1, 'bookmarks': [], 'recents': [], 'recent_limit': 12,
           'text_size': 100, 'appearance': 'system', 'width': 1060, 'height': 760,
           'maximized': False, 'last_topic': '', 'history': [], 'history_position': -1}


def sanitize(data, valid: set[str]) -> dict:
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('Unsupported Help preferences')
    result = {**DEFAULT, 'history': []}
    for field, maximum in (('bookmarks', 256), ('recents', 50)):
        values = data.get(field, [])
        if not isinstance(values, list) or len(values) > maximum or not all(isinstance(v, str) for v in values):
            raise ValueError('Invalid Help topic list')
        result[field] = list(dict.fromkeys(v for v in values if v in valid))
    for field, minimum, maximum in (('recent_limit', 0, 50), ('text_size', 80, 180), ('width', 320, 3840), ('height', 360, 2160)):
        value = data.get(field, DEFAULT[field])
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError('Invalid Help preference range')
        result[field] = value
    if data.get('appearance', 'system') not in ('system', 'light', 'dark'):
        raise ValueError('Invalid appearance preference')
    result['appearance'] = data.get('appearance', 'system')
    for field in ('maximized',):
        if type(data.get(field, DEFAULT[field])) is not bool:
            raise ValueError('Invalid Help boolean preference')
        result[field] = data.get(field, DEFAULT[field])
    last = data.get('last_topic', '')
    result['last_topic'] = last if isinstance(last, str) and last in valid else ''
    result['recents'] = result['recents'][:result['recent_limit']]
    history = data.get('history', [])
    if not isinstance(history, list) or len(history) > 100:
        raise ValueError('Invalid Help history')
    position = data.get('history_position', -1)
    if type(position) is not int:
        raise ValueError('Invalid Help history position')
    retained_position = -1
    for index, item in enumerate(history):
        if (not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str)
                or type(item[1]) not in (int, float) or not math.isfinite(item[1]) or not 0 <= item[1] <= 1_000_000):
            raise ValueError('Invalid Help reading position')
        if item[0] == '' or item[0] in valid:
            result['history'].append(list(item))
            if index <= position:
                retained_position = len(result['history']) - 1
    result['history_position'] = retained_position
    return result


class StateStore:
    def __init__(self, valid: set[str], *, directory: Path | None = None):
        self.valid = valid
        self.error = ''
        self.data = sanitize(DEFAULT, valid)
        home = Path.home()
        candidate = Path(os.environ.get('XDG_STATE_HOME') or home / '.local/state') / 'labwc-help' if directory is None else directory
        self.directory = candidate
        try:
            if not candidate.is_absolute() or '..' in candidate.parts or not candidate.is_relative_to(home):
                raise ValueError('Help state must be in a private directory below your home')
            self._parents()
            self.data = self._load()
        except (OSError, ValueError):
            self.error = 'Preferences could not be read safely. Help is using temporary settings; existing state was preserved.'

    def _parents(self):
        for path in (*reversed(self.directory.parents), self.directory):
            if not path.exists() and not path.is_symlink():
                path.mkdir(mode=0o700)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
                raise ValueError('Unsafe Help state directory')
        info = self.directory.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Help state directory is not private')

    @staticmethod
    def _private(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise ValueError('Unsafe Help state file')

    def _load(self):
        try:
            descriptor = os.open(self.directory / 'state.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except FileNotFoundError:
            return sanitize(DEFAULT, self.valid)
        with os.fdopen(descriptor, 'rb') as stream:
            self._private(os.fstat(stream.fileno()))
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('Help state exceeds limit')
        return sanitize(decode(raw), self.valid)

    def save(self, data=None):
        if self.error:
            return False
        lock = directory_fd = None
        temporary = '.state-' + secrets.token_hex(12)
        created = False
        try:
            self._parents()
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            lock = os.open('state.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=directory_fd)
            self._private(os.fstat(lock))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Never replace a hostile destination or overwrite corrupt state on error.
            try:
                self._private(os.stat('state.json', dir_fd=directory_fd, follow_symlinks=False))
            except FileNotFoundError:
                pass
            raw = json.dumps(sanitize(self.data if data is None else data, self.valid), ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(raw) > 65536:
                raise ValueError('Help state exceeds limit')
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory_fd)
            created = True
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, 'state.json', src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            created = False
            os.fsync(directory_fd)
            return True
        except (OSError, ValueError):
            self.error = 'Preferences could not be saved safely. Existing state or recovery evidence was preserved.'
            return False
        finally:
            # Only this call's unpredictable, owned temporary name is removed.
            if created and directory_fd is not None:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except OSError:
                    self.error = 'Preferences cleanup failed. Private recovery evidence was retained.'
            if lock is not None:
                os.close(lock)
            if directory_fd is not None:
                os.close(directory_fd)


class StateWriter:
    """One writer, at most one pending snapshot; disk sync never blocks GTK."""
    def __init__(self, store: StateStore):
        self.store = store
        self.lock = threading.Lock()
        self.pending = None
        self.running = False

    def submit(self) -> bool:
        if self.store.error:
            return False
        snapshot = sanitize(self.store.data, self.store.valid)
        with self.lock:
            self.pending = snapshot
            if not self.running:
                self.running = True
                threading.Thread(target=self._flush, name='help-preferences', daemon=False).start()
        return True

    def _flush(self):
        while True:
            with self.lock:
                snapshot, self.pending = self.pending, None
                if snapshot is None:
                    self.running = False
                    return
            self.store.save(snapshot)
