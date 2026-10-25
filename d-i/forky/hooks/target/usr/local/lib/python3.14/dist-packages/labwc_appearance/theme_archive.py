"""Bounded theme archive reader. Members are data; nothing is extracted/run.

The installation mapper copies only named GTK3/GTK4 assets from this index.
Archive links are resolved inside the index and never become filesystem links.
"""
from __future__ import annotations
from dataclasses import dataclass
import gzip
import io
import lzma
from pathlib import PurePosixPath
import posixpath
import stat
import struct
import tarfile
import time
import zipfile

MAX_INPUT = 32 * 1024**2
MAX_ARCHIVE = 128 * 1024**2
MAX_DECODER_MEMORY = 128 * 1024**2
MAX_MEMBER = 16 * 1024**2
MAX_MEMBERS = 12000


def name(value: str) -> str:
    if value.startswith('./'):
        value = value[2:]
    value = value.rstrip('/')
    if (not value or len(value.encode('utf-8')) > 512 or '\\' in value or
            any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('invalid theme archive member name')
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or str(path) != value or '..' in path.parts or len(path.parts) > 32:
        raise ValueError('unsafe theme archive member path')
    return value


@dataclass(frozen=True)
class Link:
    target: str


class Archive:
    def __init__(self, blob: bytes, filename: str, *, deadline: float):
        if len(blob) > MAX_INPUT:
            raise ValueError('theme archive input exceeds the size limit')
        self.deadline = deadline
        self.entries: dict[str, bytes | Link | None] = {}
        self.count = self.size = 0
        if filename.endswith('.deb'):
            blob, filename = self._deb(blob)
        if filename.endswith('.zip'):
            self._zip(blob)
        else:
            if filename.endswith('.gz'):
                blob = self._expand(gzip.GzipFile(fileobj=io.BytesIO(blob)))
            elif filename.endswith('.xz'):
                blob = self._expand_xz(blob)
            else:
                raise ValueError('unsupported theme archive encoding')
            self._tar(blob)
        self.children: dict[str, set[str]] = {}
        for member in self.entries:
            parent, _, child = member.rpartition('/')
            self.children.setdefault(parent, set()).add(child)

    def _check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise TimeoutError('theme asset preparation exceeded its deadline')

    def _expand(self, stream) -> bytes:
        output = io.BytesIO()
        with stream:
            while True:
                self._check()
                chunk = stream.read(min(1024**2, MAX_ARCHIVE + 1 - output.tell()))
                if not chunk:
                    return output.getvalue()
                output.write(chunk)
                if output.tell() > MAX_ARCHIVE:
                    raise ValueError('expanded theme archive exceeds the size limit')

    def _reserve(self, size: int) -> None:
        self._check()
        self.count += 1
        self.size += size
        if self.count > MAX_MEMBERS or size < 0 or size > MAX_MEMBER or self.size > MAX_ARCHIVE:
            raise ValueError('theme archive member/byte budget exceeded')

    def _expand_xz(self, blob: bytes) -> bytes:
        # The output cap does not bound an XZ dictionary allocation. Give
        # every stream its own decoder memory cap as well as bounded output.
        output = io.BytesIO()
        while blob:
            self._check()
            decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=MAX_DECODER_MEMORY)
            pending = blob
            while not decoder.eof:
                self._check()
                try:
                    chunk = decoder.decompress(pending, max_length=min(1024**2, MAX_ARCHIVE + 1 - output.tell()))
                except lzma.LZMAError as error:
                    raise ValueError('invalid theme XZ data or decoder memory limit exceeded') from error
                output.write(chunk)
                if output.tell() > MAX_ARCHIVE:
                    raise ValueError('expanded theme archive exceeds the size limit')
                if not decoder.eof and decoder.needs_input:
                    raise ValueError('truncated theme XZ stream')
                pending = b''
            # Preserve concatenated XZ streams and valid four-byte padding.
            trailing = decoder.unused_data
            del decoder
            blob = trailing.lstrip(b'\x00')
            if (len(trailing) - len(blob)) % 4:
                raise ValueError('invalid theme XZ stream padding')
        return output.getvalue()

    def _add(self, path: str, value: bytes | Link | None) -> None:
        path = name(path)
        if path in self.entries:
            if value is None and self.entries[path] is None:
                return
            raise ValueError('duplicate theme archive member')
        parents = PurePosixPath(path).parents
        for parent in reversed(parents[:-1]):
            key = str(parent)
            if key not in self.entries:
                if len(self.entries) >= MAX_MEMBERS * 2:
                    raise ValueError('theme archive directory budget exceeded')
                self.entries[key] = None
            elif self.entries[key] is not None:
                raise ValueError('theme archive member has a non-directory parent')
        if len(self.entries) >= MAX_MEMBERS * 2:
            raise ValueError('theme archive index budget exceeded')
        self.entries[path] = value

    def _tar(self, blob: bytes) -> None:
        with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
            for member in archive:
                self._reserve(member.size)
                if member.name in ('.', './') and member.isdir():
                    continue
                path = name(member.name)
                if member.isdir():
                    value = None
                elif member.isfile():
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError('missing regular theme archive data')
                    with stream:
                        value = stream.read(member.size + 1)
                    if len(value) != member.size:
                        raise ValueError('truncated theme archive member')
                elif member.issym() or member.islnk():
                    raw = member.linkname
                    if not raw or raw.startswith('/') or '\\' in raw or any(ord(c) < 32 for c in raw):
                        raise ValueError('unsafe theme archive link')
                    target = raw if member.islnk() else posixpath.join(posixpath.dirname(path), raw)
                    value = Link(name(posixpath.normpath(target)))
                else:
                    raise ValueError('special theme archive members are prohibited')
                self._add(path, value)

    def _zip(self, blob: bytes) -> None:
        # Bound the central-directory member count before ZipFile allocates its
        # member list. The vendored theme ZIPs do not require ZIP64 or disks.
        offset = blob.rfind(b'PK\x05\x06', max(0, len(blob) - 65557))
        if offset < 0 or offset + 22 > len(blob):
            raise ValueError('missing theme ZIP directory')
        disk, start, disk_count, count, size, central, comment = struct.unpack_from('<4H2IH', blob, offset + 4)
        if (disk or start or disk_count != count or count > MAX_MEMBERS or count == 65535 or
                central + size != offset or offset + 22 + comment != len(blob)):
            raise ValueError('theme ZIP directory exceeds the supported bounds')
        # ZipFile walks central-directory records independently of the EOCD
        # count. Validate their framing before it allocates ZipInfo objects;
        # a forged small count must not bypass the member allocation budget.
        cursor = central
        for _ in range(count):
            self._check()
            if cursor + 46 > offset or blob[cursor:cursor + 4] != b'PK\x01\x02':
                raise ValueError('invalid theme ZIP directory record')
            name_size, extra_size, comment_size, member_disk = struct.unpack_from('<4H', blob, cursor + 28)
            if not 0 < name_size <= 512 or member_disk:
                raise ValueError('unsupported theme ZIP member metadata')
            cursor += 46 + name_size + extra_size + comment_size
            if cursor > offset:
                raise ValueError('truncated theme ZIP directory record')
        if cursor != offset:
            raise ValueError('theme ZIP directory count mismatch')
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            members = archive.infolist()
            if len(members) != count:
                raise ValueError('theme ZIP directory count mismatch')
            for member in members:
                self._reserve(member.file_size)
                mode = stat.S_IFMT(member.external_attr >> 16)
                if (member.flag_bits & 1 or mode not in (0, stat.S_IFREG, stat.S_IFDIR) or
                        member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError('encrypted, special or unsupported compressed theme ZIP member')
                if member.is_dir():
                    if member.file_size:
                        raise ValueError('nonempty theme ZIP directory')
                    value = None
                else:
                    with archive.open(member) as stream:
                        value = stream.read(member.file_size + 1)
                    if len(value) != member.file_size:
                        raise ValueError('truncated theme ZIP member')
                self._add(member.filename, value)

    def _deb(self, blob: bytes) -> tuple[bytes, str]:
        if not blob.startswith(b'!<arch>\n'):
            raise ValueError('invalid theme Debian data archive')
        offset = 8
        result = None
        seen = set()
        for _ in range(8):
            self._check()
            if offset == len(blob):
                break
            head = blob[offset:offset + 60]
            if len(head) != 60 or head[58:] != b'`\n' or not head[48:58].strip().isdigit():
                raise ValueError('invalid theme Debian archive framing')
            label = head[:16].decode('ascii').strip().rstrip('/')
            size = int(head[48:58])
            offset += 60
            if label in seen or size > MAX_INPUT or offset + size > len(blob):
                raise ValueError('invalid theme Debian archive member')
            seen.add(label)
            data = blob[offset:offset + size]
            if label == 'debian-binary' and data != b'2.0\n':
                raise ValueError('unsupported theme Debian archive version')
            if label in ('data.tar.xz', 'data.tar.gz'):
                if result is not None:
                    raise ValueError('duplicate theme Debian data')
                result = data, label
            offset += size + size % 2
        if offset != len(blob) or result is None or 'debian-binary' not in seen:
            raise ValueError('missing or unbounded theme Debian data archive')
        return result

    def resolve(self, path: str) -> str:
        path = name(path)
        for _ in range(16):
            self._check()
            components = path.split('/')
            for length in range(1, len(components) + 1):
                prefix = '/'.join(components[:length])
                value = self.entries.get(prefix)
                if isinstance(value, Link):
                    path = name(posixpath.join(value.target, *components[length:]))
                    break
            else:
                if path not in self.entries:
                    raise ValueError('missing selected theme archive member')
                return path
        raise ValueError('cyclic or excessively deep theme archive link')

    def read(self, path: str) -> bytes:
        value = self.entries[self.resolve(path)]
        if not isinstance(value, bytes):
            raise ValueError('selected theme asset is not a regular file')
        return value

    def tree(self, prefix: str) -> dict[str, bytes]:
        """Materialize a selected subtree in memory, following internal links."""
        if self.entries[self.resolve(prefix)] is not None:
            raise ValueError('selected theme subtree is not a directory')
        result = {}
        def visit(path: str, destination: str, parents: frozenset[str]) -> None:
            actual = self.resolve(path)
            if actual in parents:
                raise ValueError('cyclic theme asset directory')
            value = self.entries[actual]
            if isinstance(value, bytes):
                if len(result) >= MAX_MEMBERS:
                    raise ValueError('selected theme asset count exceeds the limit')
                result[destination] = value
                return
            for child in sorted(self.children.get(actual, ())):
                visit(actual + '/' + child, destination + '/' + child if destination else child,
                      parents | {actual})
        visit(prefix, '', frozenset())
        return result
