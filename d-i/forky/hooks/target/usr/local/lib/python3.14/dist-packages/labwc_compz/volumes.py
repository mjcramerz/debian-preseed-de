"""Resolve complete volume sets from any selected member, without concatenating RAR."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat

from . import CompzError
from .formats import identify, stem


@dataclass(frozen=True)
class VolumeSet:
    head: Path
    members: tuple[Path, ...]
    name: str
    concatenate: bool = False


def _files(parent: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in parent.iterdir():
        result[item.name] = item
        if len(result) > 1000000:
            raise CompzError('Archive directory has more than one million entries.')
    return result


def _lookup(files: dict[str, Path], name: str) -> Path | None:
    matches = [path for key, path in files.items() if key.casefold() == name.casefold()]
    if len(matches) > 1:
        raise CompzError('Ambiguous case-colliding archive volume names.')
    return matches[0] if matches else None


def _rar_header(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as source:
        value = os.fstat(source.fileno())
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise CompzError('Archive volumes must be regular, non-linked files.')
        if source.read(8)[:7] not in (b'Rar!\x1a\x07\x00', b'Rar!\x1a\x07\x01'):
            raise CompzError('First numbered RAR volume has no RAR header.')


def _sequence(files: dict[str, Path], expression: str, first: int) -> tuple[Path, ...]:
    regex = re.compile(expression, re.I)
    numbered: dict[int, Path] = {}
    digits: dict[int, str] = {}
    for name, path in files.items():
        match = regex.fullmatch(name)
        if match:
            number = int(match[1])
            if number in numbered:
                raise CompzError('Duplicate archive volume number.')
            numbered[number] = path
            digits[number] = match[1]
    # Natural or consistently zero-padded numbering can grow at a power of ten.
    width = min(map(len, digits.values()), default=0)
    if not numbered or any(value != str(number).zfill(width) for number, value in digits.items()):
        raise CompzError('Missing or ambiguous archive volume sequence.')
    numbers = sorted(numbered)
    if numbers[0] != first or any(b != a + 1 for a, b in zip(numbers, numbers[1:])):
        raise CompzError('Missing archive volume; supply the complete contiguous set.')
    if len(numbers) > 10000:
        raise CompzError('Archive volume count exceeds 10000.')
    return tuple(numbered[number] for number in numbers)



def _legacy_sequence(files: dict[str, Path], base: str) -> tuple[Path, ...]:
    """Native old RAR advances .r99 to .s00, not .r100."""
    regex = re.compile(re.escape(base) + r'\.([r-z])([0-9]{2})', re.I)
    numbered = {}
    for name, path in files.items():
        match = regex.fullmatch(name)
        if match:
            number = (ord(match[1].lower()) - ord('r')) * 100 + int(match[2])
            if number in numbered:
                raise CompzError('Duplicate legacy RAR volume number.')
            numbered[number] = path
        elif re.fullmatch(re.escape(base) + r'\.r[0-9]{3,}', name, re.I):
            raise CompzError('Mixed legacy and extended RAR volume numbering.')
    if not numbered or sorted(numbered) != list(range(max(numbered) + 1)):
        raise CompzError('Missing archive volume; supply the complete contiguous set.')
    return tuple(numbered[number] for number in sorted(numbered))


def resolve(path: Path) -> VolumeSet:
    name = path.name
    files = _files(path.parent)
    if name not in files:
        raise CompzError('Selected archive no longer exists.')
    part = re.fullmatch(r'(.+)\.part([0-9]+)\.rar', name, re.I)
    old = re.fullmatch(r'(.+)\.r([0-9]{2,})', name, re.I)
    continuation = re.fullmatch(r'(.+)\.[s-z][0-9]{2}', name, re.I)
    if continuation and name.lower().rsplit('.', 1)[1].startswith('z'):
        # .zNN is also split ZIP. A final .zip identifies that format.
        if _lookup(files, continuation[1] + '.zip') is not None:
            continuation = None
    split = re.fullmatch(r'(.+)\.([0-9]{3,})', name)
    splitzip = re.fullmatch(r'(.+)\.z([0-9]{2,})', name, re.I)
    result: VolumeSet
    if part:
        members = _sequence(files, re.escape(part[1]) + r'\.part([0-9]+)\.rar', 1)
        result = VolumeSet(members[0], members, stem(part[1]))
    elif old or continuation or name.lower().endswith('.rar'):
        base = old[1] if old else continuation[1] if continuation else name[:-4]
        head = _lookup(files, base + '.rar')
        expression = re.escape(base) + r'\.r([0-9]{2,})'
        has_parts = any(re.fullmatch(expression, item, re.I) for item in files)
        rollover = any(re.fullmatch(re.escape(base) + r'\.[s-y][0-9]{2}', item, re.I) for item in files)
        rollover = rollover or bool(continuation)
        if rollover:
            if head is None:
                raise CompzError('Missing first legacy RAR .rar volume.')
            result = VolumeSet(head, (head,) + _legacy_sequence(files, base), stem(base))
        elif head is None:
            # Some tools number the first RAR header .r000/.r001 rather than
            # .rar. Accept only an actual RAR first-header signature.
            candidates = [p for n, p in files.items() if re.fullmatch(expression, n, re.I)]
            candidates.sort(key=lambda p: int(p.suffix[2:]))
            if not candidates:
                raise CompzError('Missing first RAR volume.')
            first = int(candidates[0].suffix[2:])
            if first not in (0, 1):
                raise CompzError('Missing first RAR volume.')
            members = _sequence(files, expression, first)
            _rar_header(members[0])
            result = VolumeSet(members[0], members, stem(base))
        else:
            first = 0
            if has_parts:
                digits = [m[1] for n in files if (m := re.fullmatch(expression, n, re.I))]
                # Three-or-more-digit RAR sets also occur as .rar + .r001.
                if all(len(d) >= 3 for d in digits) and min(map(int, digits)) == 1:
                    first = 1
            members = (head,) + (_sequence(files, expression, first) if has_parts else ())
            result = VolumeSet(head, members, stem(base))
    elif splitzip or name.lower().endswith('.zip'):
        base = splitzip[1] if splitzip else name[:-4]
        expression = re.escape(base) + r'\.z([0-9]{2,})'
        head = _lookup(files, base + '.zip')
        has_parts = any(re.fullmatch(expression, item, re.I) for item in files)
        if head is None:
            raise CompzError('Split ZIP is missing its final .zip directory volume.')
        members = _sequence(files, expression, 1) + (head,) if has_parts else (head,)
        result = VolumeSet(head, members, stem(base))
    elif split:
        members = _sequence(files, re.escape(split[1]) + r'\.([0-9]{3,})', 1)
        identify(split[1])  # Reject unknown split payloads, not arbitrary file sets.
        result = VolumeSet(members[0], members, stem(split[1]), True)
    else:
        identify(name)
        result = VolumeSet(path, (path,), stem(name))
    for member in result.members:
        value = member.lstat()
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise CompzError('Archive volumes must be regular, non-linked files.')
    return result


def rar_aliases(volumes: VolumeSet, directory: Path) -> Path:
    """Present volume numbering required by the RAR header, without moving data.

    A .rar followed by .r001 is not the native legacy .rar/.r00 sequence.
    These private, generated aliases are never published or accepted as archive
    contents. Outer targets remain read-only mounts; native CRC/volume checks
    still validate the original bytes. Never concatenate RAR volumes.
    """
    if len(volumes.members) == 1:
        return volumes.head
    descriptor = os.open(volumes.head, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as source:
        value = os.fstat(source.fileno())
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
            raise CompzError('Unsafe first RAR volume.')
        header = source.read(14)
    if header.startswith(b'Rar!\x1a\x07\x01\x00'):
        modern = True
    elif header.startswith(b'Rar!\x1a\x07\x00') and len(header) == 14 and header[9] == 0x73:
        modern = bool(int.from_bytes(header[10:12], 'little') & 0x10)
    else:
        raise CompzError('Cannot determine the RAR volume naming convention from its header.')
    directory.mkdir(mode=0o700)
    first = None
    for index, member in enumerate(volumes.members):
        if not member.is_absolute():
            raise CompzError('RAR volume aliases require absolute sandbox paths.')
        if modern:
            name = f'volume.part{index + 1:05d}.rar'
        elif index == 0:
            name = 'volume.rar'
        else:
            # Native legacy sequence increments r99 -> s00, then t00, etc.
            letter, number = divmod(index - 1, 100)
            name = f'volume.{chr(ord("r") + letter)}{number:02d}'
        alias = directory / name
        alias.symlink_to(member)
        if first is None:
            first = alias
    return first


def recognizable(name: str) -> bool:
    try:
        identify(name)
        return True
    except CompzError:
        if re.fullmatch(r'.+\.(?:r[0-9]{2,}|[s-y][0-9]{2}|z[0-9]{2,})', name, re.I):
            return True
        split = re.fullmatch(r'(.+)\.[0-9]{3,}', name)
        if split:
            try:
                identify(split[1])
                return True
            except CompzError:
                pass
        return False
