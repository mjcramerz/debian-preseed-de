"""Descriptor-relative IO: no symlinks, hardlinks, special files or partial writes."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat

MAX_TEXT = 8 * 1024 * 1024


def parts(value: str) -> tuple[str, ...]:
    path = PurePosixPath(value)
    if (not value or not path.parts or path.is_absolute() or str(path) != value or
            any(p in ('', '.', '..') for p in path.parts) or
            any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('invalid relative path')
    return path.parts


def open_directory(path: Path) -> int:
    """Open an absolute directory without following *any* symlink component."""
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('directory must be absolute and normalized')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for name in path.parts[1:]:
            new = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                          os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = new
        return fd
    except BaseException:
        os.close(fd)
        raise


class Tree:
    """An owned directory capability; all child operations are relative to its fd.

    A peer already running with the same uid can rename an open directory. Such
    a peer is not an isolation boundary; these checks prevent link traversal and
    cross-account substitution, including in the privileged helpers.
    """
    def __init__(self, root: Path, uid: int | None = None, *, private: bool = False):
        self.root = root
        self.uid = os.getuid() if uid is None else uid
        self.fd = open_directory(root)
        try:
            self._directory_ok(self.fd, private)
        except BaseException:
            os.close(self.fd)
            raise

    def _directory_ok(self, fd: int, private: bool = False) -> None:
        info = os.fstat(fd)
        mask = 0o077 if private else 0o022
        if info.st_uid != self.uid or info.st_mode & mask:
            raise ValueError(f'unsafe ownership or permissions below {self.root}')

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextlib.contextmanager
    def parent(self, relative: str, *, create: bool = False):
        names = parts(relative)
        fd = os.dup(self.fd)
        try:
            for name in names[:-1]:
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                new = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                              os.O_CLOEXEC, dir_fd=fd)
                try:
                    self._directory_ok(new)
                except BaseException:
                    os.close(new)
                    raise
                os.close(fd)
                fd = new
            yield fd, names[-1]
        finally:
            os.close(fd)

    def mkdir(self, relative: str) -> None:
        with self.parent(relative + '/.anchor', create=True):
            pass

    def read(self, relative: str, limit: int = MAX_TEXT, *, missing: bool = False) -> bytes | None:
        try:
            with self.parent(relative) as (parent, name):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                             os.O_CLOEXEC, dir_fd=parent)
        except FileNotFoundError:
            if missing:
                return None
            raise
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                    before.st_uid != self.uid or before.st_mode & 0o022 or
                    before.st_size > limit):
                raise ValueError(f'unsafe file: {relative}')
            with os.fdopen(os.dup(fd), 'rb') as stream:
                data = stream.read(limit + 1)
            after = os.fstat(fd)
            if (len(data) > limit or len(data) != before.st_size or
                    (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError(f'file changed during read: {relative}')
            return data
        finally:
            os.close(fd)

    def write(self, relative: str, data: bytes | None, *, mode: int = 0o600) -> None:
        with self.parent(relative, create=data is not None) as (parent, name):
            try:
                old = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                old = None
            if old is not None and (not stat.S_ISREG(old.st_mode) or old.st_nlink != 1 or
                                    old.st_uid != self.uid or old.st_mode & 0o022):
                raise ValueError(f'unsafe destination: {relative}')
            if data is None:
                if old is not None:
                    os.unlink(name, dir_fd=parent)
                    os.fsync(parent)
                return
            temporary = '.managed-' + secrets.token_hex(12)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=parent)
            try:
                os.fchmod(fd, mode)
                with os.fdopen(fd, 'wb', closefd=False) as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(fd)
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                os.close(fd)
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass

    def json(self, relative: str, default=None):
        raw = self.read(relative, missing=True)
        return default if raw is None else json.loads(raw)

    def put_json(self, relative: str, value) -> None:
        self.write(relative, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())

    @contextlib.contextmanager
    def lock(self, relative: str):
        with self.parent(relative, create=True) as (parent, name):
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW |
                         os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.uid or
                    info.st_nlink != 1 or info.st_mode & 0o077):
                raise ValueError('unsafe lock file')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('another operation is already running') from exc
            yield
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def open_read(self, relative: str, *, limit: int = 16 * 1024**3):
        with self.parent(relative) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                         os.O_CLOEXEC, dir_fd=parent)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                    before.st_uid != self.uid or before.st_mode & 0o022 or before.st_size > limit):
                raise ValueError(f'unsafe input file: {relative}')
            with os.fdopen(os.dup(fd), 'rb') as stream:
                yield stream, before
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError(f'input changed during operation: {relative}')
        finally:
            os.close(fd)

    def copy(self, relative: str, source: 'Tree', source_name: str, *, mode: int = 0o600,
             limit: int = 16 * 1024**3) -> None:
        with source.open_read(source_name, limit=limit) as (stream, before):
            with self.parent(relative, create=True) as (parent, name):
                try:
                    existing = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    existing = None
                if existing is not None and (not stat.S_ISREG(existing.st_mode) or
                        existing.st_uid != self.uid or existing.st_nlink != 1 or existing.st_mode & 0o022):
                    raise ValueError('unsafe copy destination')
                temp = '.managed-' + secrets.token_hex(12)
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=parent)
                try:
                    with os.fdopen(fd, 'wb', closefd=False) as out:
                        remaining = before.st_size
                        while remaining:
                            chunk = stream.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                raise ValueError('copy source truncated during operation')
                            out.write(chunk)
                            remaining -= len(chunk)
                        if stream.read(1):
                            raise ValueError('copy source grew during operation')
                        out.flush()
                        os.fchmod(fd, mode)
                        os.fsync(fd)
                    after = os.fstat(stream.fileno())
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise ValueError('copy source changed during operation')
                    os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
                finally:
                    os.close(fd)
                    try:
                        os.unlink(temp, dir_fd=parent)
                    except FileNotFoundError:
                        pass
