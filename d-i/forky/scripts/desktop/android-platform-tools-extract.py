#!/usr/bin/python3
"""Extract the Google Platform-Tools ZIP within explicit metadata/byte limits."""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import sys
import time
import zipfile

REQUIRED = {'platform-tools/NOTICE.txt', 'platform-tools/adb',
            'platform-tools/fastboot', 'platform-tools/lib64/libc++.so',
            'platform-tools/source.properties'}
MAX_CENTRAL_BYTES = 16 * 1024 * 1024


def preflight(stream, size: int, max_members: int, deadline: float) -> None:
    # Bound central-directory allocation before constructing ZipInfo objects.
    stream.seek(max(0, size - 65557))
    tail_start = stream.tell()
    tail = stream.read(65557)
    offset = len(tail)
    while True:
        offset = tail.rfind(b'PK\x05\x06', 0, offset)
        if offset < 0:
            raise ValueError('missing ZIP end record')
        if offset + 22 <= len(tail):
            fields = struct.unpack_from('<4s4H2LH', tail, offset)
            if offset + 22 + fields[7] == len(tail):
                break
    _, disk, directory_disk, disk_entries, count, length, start, _ = fields
    if (disk or directory_disk or disk_entries != count or not 0 < count <= max_members
            or count == 0xffff or start == 0xffffffff or length == 0xffffffff
            or length > MAX_CENTRAL_BYTES or start + length != tail_start + offset):
        raise ValueError('unsupported or oversized ZIP directory')
    stream.seek(start)
    observed = 0
    while stream.tell() < start + length:
        if time.monotonic() >= deadline:
            raise ValueError('archive validation deadline exceeded')
        header = stream.read(46)
        if len(header) != 46 or header[:4] != b'PK\x01\x02':
            raise ValueError('invalid ZIP directory entry')
        observed += 1
        if observed > max_members:
            raise ValueError('ZIP directory member limit exceeded')
        name_size, extra_size, comment_size = struct.unpack_from('<3H', header, 28)
        stream.seek(name_size + extra_size + comment_size, os.SEEK_CUR)
        if stream.tell() > start + length:
            raise ValueError('invalid ZIP directory boundary')
    if observed != count:
        raise ValueError('ZIP directory count mismatch')
    stream.seek(0)


def extract(archive_path: Path, output: Path, max_bytes: int, max_members: int) -> None:
    if not 0 < max_members <= 100_000 or max_bytes <= 0:
        raise ValueError('invalid extraction limits')
    info = output.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or any(output.iterdir())):
        raise ValueError('extraction requires an empty private directory')
    deadline = time.monotonic() + 300
    descriptor = os.open(archive_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or before.st_mode & 0o022):
            raise ValueError('archive must be a direct owned regular file')
        preflight(stream, before.st_size, max_members, deadline)
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            nodes: dict[str, str] = {}
            explicit: set[str] = set()
            regular: set[str] = set()
            total = 0
            for member in members:
                if time.monotonic() >= deadline:
                    raise ValueError('archive validation deadline exceeded')
                raw = member.filename
                path = PurePosixPath(raw)
                normalized = path.as_posix()
                kind = stat.S_IFMT(member.external_attr >> 16)
                is_dir = member.is_dir()
                if (not raw or not path.parts or raw != member.orig_filename
                        or len(raw) > 1024 or '\\' in raw
                        or any(ord(char) < 32 or ord(char) == 127 for char in raw)
                        or path.is_absolute() or '..' in path.parts or len(path.parts) > 16
                        or path.parts[0] != 'platform-tools'
                        or raw != normalized + ('/' if is_dir else '')
                        or normalized in explicit or member.flag_bits & 1
                        or kind not in (0, stat.S_IFDIR if is_dir else stat.S_IFREG)
                        or (is_dir and member.file_size)):
                    raise ValueError('unsafe or unsupported ZIP member')
                explicit.add(normalized)
                for parent in reversed(path.parents):
                    if parent == PurePosixPath('.'):
                        continue
                    name = parent.as_posix()
                    if nodes.setdefault(name, 'directory') != 'directory':
                        raise ValueError('ZIP member conflicts with a parent file')
                node_kind = 'directory' if is_dir else 'file'
                if normalized in nodes and nodes[normalized] != node_kind:
                    raise ValueError('conflicting ZIP member types')
                nodes[normalized] = node_kind
                if len(nodes) > max_members:
                    raise ValueError('expanded ZIP node limit exceeded')
                total += member.file_size
                if total > max_bytes:
                    raise ValueError('ZIP expanded-byte limit exceeded')
                if not is_dir:
                    regular.add(normalized)
            if not REQUIRED <= regular:
                raise ValueError('archive is missing required Platform-Tools files')
            written = 0
            for member in members:
                if time.monotonic() >= deadline:
                    raise ValueError('archive extraction deadline exceeded')
                target = output / member.filename
                if member.is_dir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600)
                with os.fdopen(fd, 'wb') as destination, archive.open(member) as source:
                    copied = 0
                    while True:
                        if time.monotonic() >= deadline:
                            raise ValueError('archive extraction deadline exceeded')
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        written += len(chunk)
                        if copied > member.file_size or written > max_bytes:
                            raise ValueError('ZIP member expanded beyond its declared limit')
                        destination.write(chunk)
                    if copied != member.file_size:
                        raise ValueError('truncated ZIP member')
                    os.fchmod(destination.fileno(), 0o700 if member.external_attr >> 16 & 0o111 else 0o600)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('archive changed during extraction')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('max_bytes', type=int)
    parser.add_argument('max_members', type=int)
    args = parser.parse_args()
    try:
        extract(args.archive, args.output, args.max_bytes, args.max_members)
    except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError):
        print('fatal: Platform-Tools archive failed bounded extraction; private staging retained', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
