"""Bounded archive I/O and no-replace publication; never trust archive metadata."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat
import tarfile
from typing import BinaryIO, Iterator

from . import CompzError

CHUNK = 1024 * 1024
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def display(value: str) -> str:
    # ASCII repr also neutralizes bidi, ESC/OSC hyperlinks and undecodable names.
    return ascii(value)[1:-1]


def relative(name: str) -> tuple[str, ...]:
    while name.startswith('./'):
        name = name[2:]
    name = name.rstrip('/')
    parts = tuple(name.split('/'))
    if (not name or len(os.fsencode(name)) > 4096 or len(parts) > 128 or
            name.startswith('/') or '\\' in name or ':' in parts[0] or
            any(part in ('', '.', '..') or '\0' in part or len(os.fsencode(part)) > 255 for part in parts)):
        raise CompzError('Unsafe or excessively long archive pathname.')
    return parts


@dataclass
class Budget:
    max_bytes: int
    max_files: int
    used_bytes: int = 0
    used_files: int = 0

    def add(self, size: int, count: int = 1) -> None:
        if size < 0 or count < 0:
            raise CompzError('Negative archive member size.')
        self.used_bytes += size
        self.used_files += count
        if self.used_bytes > self.max_bytes or self.used_files > self.max_files:
            raise CompzError('Archive expansion exceeds the selected byte/file budget.')


@contextmanager
def directory_fd(root: int, parts: tuple[str, ...], *, create: bool = False) -> Iterator[int]:
    current = os.dup(root)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
            next_fd = os.open(part, DIRECTORY, dir_fd=current)
            os.close(current)
            current = next_fd
        yield current
    finally:
        os.close(current)


def copy_exact(source: BinaryIO, target: BinaryIO, size: int) -> None:
    left = size
    while left:
        block = source.read(min(CHUNK, left))
        if not block:
            raise CompzError('Truncated archive data.')
        target.write(block)
        left -= len(block)


def extract_tar(source: BinaryIO, destination: Path, budget: Budget) -> None:
    """Streaming tar extraction, with descriptor-relative no-follow creation."""
    root = os.open(destination, DIRECTORY)
    seen = set()
    try:
        with tarfile.open(fileobj=source, mode='r|', encoding='utf-8', errors='surrogateescape') as archive:
            for member in archive:
                if member.name in ('.', './') and member.isdir():
                    continue
                parts = relative(member.name)
                key = '/'.join(parts)
                if key in seen:
                    raise CompzError('Duplicate archive member pathname.')
                seen.add(key)
                if not (member.isdir() or member.isreg()) or member.issparse():
                    raise CompzError('Links, devices, FIFOs and sparse tar entries are rejected.')
                budget.add(member.size if member.isreg() else 0)
                with directory_fd(root, parts[:-1], create=True) as parent:
                    if member.isdir():
                        try:
                            os.mkdir(parts[-1], 0o700, dir_fd=parent)
                        except FileExistsError:
                            with directory_fd(parent, (parts[-1],)):
                                pass
                    else:
                        descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                             os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
                        with os.fdopen(descriptor, 'wb') as output:
                            input_file = archive.extractfile(member)
                            if input_file is None:
                                raise CompzError('Tar regular member has no data stream.')
                            with input_file:
                                copy_exact(input_file, output, member.size)
                            # Never restore owners, ACLs, xattrs or special bits.
                            os.fchmod(output.fileno(), 0o700 if member.mode & 0o100 else 0o600)
    except (tarfile.TarError, OSError) as exc:
        raise CompzError(f'Tar extraction failed: {display(str(exc))}') from exc
    finally:
        os.close(root)


def produce_tar(root: Path, selected: list[str], output: BinaryIO, budget: Budget) -> None:
    """Walk descriptors, not re-resolved paths; buffer data in kernel pipes."""
    root_fd = os.open(root, DIRECTORY)
    try:
        with tarfile.open(fileobj=output, mode='w|', format=tarfile.PAX_FORMAT,
                          encoding='utf-8', errors='surrogateescape') as archive:
            def visit(parent: int, leaf: str, name: str) -> None:
                relative(name)
                before = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISDIR(before.st_mode):
                    budget.add(0)
                    child = os.open(leaf, DIRECTORY, dir_fd=parent)
                    try:
                        if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (before.st_dev, before.st_ino):
                            raise CompzError('Source directory changed during compression.')
                        entry = tarfile.TarInfo(name + '/')
                        entry.type = tarfile.DIRTYPE
                        entry.mode = 0o700
                        entry.mtime = int(before.st_mtime)
                        archive.addfile(entry)
                        # Only one directory is sorted at a time; no whole-tree
                        # pathname list or command line grows with file count.
                        with os.scandir(child) as iterator:
                            names = []
                            for item in iterator:
                                names.append(item.name)
                                if len(names) > budget.max_files:
                                    raise CompzError('Source directory exceeds file budget.')
                        for item in sorted(names):
                            visit(child, item, name + '/' + item)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(before.st_mode):
                    descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                                         dir_fd=parent)
                    with os.fdopen(descriptor, 'rb') as source:
                        actual = os.fstat(source.fileno())
                        if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino):
                            raise CompzError('Source file changed during compression.')
                        budget.add(actual.st_size)
                        entry = tarfile.TarInfo(name)
                        entry.size = actual.st_size
                        entry.mode = 0o700 if actual.st_mode & 0o100 else 0o600
                        entry.mtime = int(actual.st_mtime)
                        archive.addfile(entry, source)
                        after = os.fstat(source.fileno())
                        if (actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                            raise CompzError('Source file was modified while it was read; no archive published.')
                else:
                    raise CompzError('Selected trees must not contain symlinks, devices, sockets or FIFOs.')
            for name in selected:
                if len(relative(name)) != 1:
                    raise CompzError('Selection must contain only current-directory entries.')
                visit(root_fd, name, name)
    finally:
        os.close(root_fd)


def audit(root: Path, max_bytes: int, max_files: int, *, sanitize: bool = False) -> tuple[int, int]:
    """Reject non-regular output and bound occupancy, including intermediate files."""
    total = count = 0
    root_fd = os.open(root, DIRECTORY)
    def walk(parent: int, depth: int) -> None:
        nonlocal total, count
        if depth > 128:
            raise CompzError('Output directory nesting exceeds 128 levels.')
        with os.scandir(parent) as entries:
            for entry in entries:
                value = entry.stat(follow_symlinks=False)
                count += 1
                total += value.st_size if stat.S_ISREG(value.st_mode) else 0
                if count > max_files or total > max_bytes:
                    raise CompzError('Workspace byte/file limit exceeded.')
                if stat.S_ISDIR(value.st_mode):
                    child = os.open(entry.name, DIRECTORY, dir_fd=parent)
                    try:
                        if sanitize:
                            os.fchmod(child, 0o700)
                            for attribute in os.listxattr(child):
                                os.removexattr(child, attribute)
                        walk(child, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(value.st_mode) and value.st_nlink == 1:
                    if sanitize:
                        descriptor = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                             dir_fd=parent)
                        try:
                            actual = os.fstat(descriptor)
                            if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1 or
                                    (actual.st_dev, actual.st_ino) != (value.st_dev, value.st_ino)):
                                raise CompzError('Output file race detected.')
                            os.fchmod(descriptor, 0o700 if value.st_mode & 0o100 else 0o600)
                            for attribute in os.listxattr(descriptor):
                                os.removexattr(descriptor, attribute)
                        finally:
                            os.close(descriptor)
                else:
                    raise CompzError('Archive created a link or special file; output was not published.')
    try:
        if sanitize:
            os.fchmod(root_fd, 0o700)
            for attribute in os.listxattr(root_fd):
                os.removexattr(root_fd, attribute)
        walk(root_fd, 0)
        return total, count
    finally:
        os.close(root_fd)


def publish(source: Path, destination: Path) -> None:
    """Linux atomic RENAME_NOREPLACE; no racy exists()+rename() fallback."""
    if destination.name in ('', '.', '..'):
        raise CompzError('Invalid output name.')
    old_fd, new_fd = os.open(source.parent, DIRECTORY), os.open(destination.parent, DIRECTORY)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(old_fd, os.fsencode(source.name), new_fd, os.fsencode(destination.name), 1):
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise CompzError('Destination already exists; it was not changed.')
            raise OSError(code, os.strerror(code))
        os.fsync(new_fd)
    finally:
        os.close(old_fd)
        os.close(new_fd)
