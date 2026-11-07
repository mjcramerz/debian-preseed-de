#!/usr/bin/env python3
"""Serialize the independent Trixie server snapshot.

The builder is a pure serializer. It reads the Trixie source tree and the
explicit read-only Forky bridge list, then publishes only the three Trixie
products: ``payload.tar.gz``, ``payload.manifest`` and ``preseed.cfg``.
The manifest is versioned and records byte sizes, SHA-256 digests, and paths.
The explicit Forky bridge is read-only input and is authenticated by the same
manifest after it is embedded in the publication.
"""
from __future__ import annotations

import gzip
import hashlib
import io
from pathlib import Path
import re
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'd-i/trixie-server'
FORKY = ROOT / 'd-i/forky'
GENERATED = frozenset({'preseed.cfg', 'payload.manifest', 'payload.tar.gz'})
SOURCE_ONLY = frozenset({'preseed.cfg.tmpl', 'forky-payload.list'})
EXCLUDED_DIRS = frozenset({'.git', '__pycache__', '.pytest_cache', 'tests'})
PRIVATE_INPUT_NAMES = frozenset({
    'preseed.env', 'git_ed25519', 'git_ed25519.pub', 'id_git_ed25519',
    'id_rsa', 'id_ecdsa', 'id_ed25519', 'credentials', 'credentials.env',
    'runner.token', 'registration.token', 'tls-passphrase',
})
PRIVATE_INPUT_SUFFIXES = frozenset({'.pem', '.key', '.p12', '.pfx', '.gpg', '.asc'})
PRIVATE_INPUT_WORDS = ('credential', 'secret', 'password', 'passphrase', 'private-key')
PRIVATE_KEY_HEADER = re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----')
SAFE_PATH = re.compile(r'[A-Za-z0-9_./@+\-]+\Z')

sys.path.insert(0, str(ROOT / 'tools'))
from publication import publish_snapshot


def _safe_path(value: str) -> None:
    if not value or value.startswith('/') or '..' in value.split('/'):
        raise ValueError(f'unsafe payload path: {value!r}')
    if not SAFE_PATH.fullmatch(value):
        raise ValueError(f'unsupported payload path: {value!r}')


def _read_regular(path: Path, display: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'payload source is not a regular file: {display}')
    data = path.read_bytes()
    if PRIVATE_KEY_HEADER.match(data[:128].lstrip()):
        raise ValueError(f'private key cannot be packaged: {display}')
    return data


def _is_private_input(relative: Path, data: bytes | None = None) -> bool:
    """Return whether a source path is forbidden private material."""
    name = relative.name.lower()
    if name in PRIVATE_INPUT_NAMES or name.endswith(tuple(PRIVATE_INPUT_SUFFIXES)):
        return True
    if (not name.endswith(('.sh', '.py', '.cfg', '.tmpl'))
            and any(word in name for word in PRIVATE_INPUT_WORDS)):
        return True
    return data is not None and PRIVATE_KEY_HEADER.match(data[:256].lstrip()) is not None


def _trixie_sources() -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for path in sorted(SEED.rglob('*')):
        relative = path.relative_to(SEED)
        if path.is_file() or path.is_symlink():
            if _is_private_input(relative):
                raise ValueError(f'private input cannot be packaged: {relative.as_posix()}')
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        name = relative.as_posix()
        if name in GENERATED or name in SOURCE_ONLY or path.is_dir():
            continue
        _safe_path(name)
        data = _read_regular(path, name)
        if _is_private_input(relative, data):
            raise ValueError(f'private input cannot be packaged: {name}')
        contents[name] = data
    return contents


def _forky_sources() -> dict[str, bytes]:
    listing = SEED / 'forky-payload.list'
    lines = listing.read_text(encoding='utf-8').splitlines()
    contents: dict[str, bytes] = {}
    listed: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        relative = line.strip()
        if not relative or relative.startswith('#'):
            continue
        if relative in listed:
            raise ValueError(f'duplicate Forky bridge path at line {line_number}: {relative}')
        listed.add(relative)
        _safe_path(relative)
        source = FORKY / relative
        destination = f'forky/{relative}'
        _safe_path(destination)
        contents[destination] = _read_regular(source, f'forky/{relative}')
    if not contents:
        raise ValueError(f'empty Forky bridge list: {listing}')
    return contents


def payload_contents() -> dict[str, bytes]:
    contents = _trixie_sources()
    for name, data in _forky_sources().items():
        if name in contents:
            raise ValueError(f'duplicate payload path: {name}')
        contents[name] = data
    if not contents:
        raise ValueError('empty Trixie payload')
    return dict(sorted(contents.items()))


def manifest(contents: dict[str, bytes], archive_digest: str) -> bytes:
    if not re.fullmatch(r'[0-9a-f]{64}', archive_digest):
        raise ValueError('payload archive digest is malformed')
    lines = [f'format=2', f'archive_sha256={archive_digest}',
             'format_description=size<TAB>sha256<TAB>path']
    lines.extend(
        f'{len(data)}\t{hashlib.sha256(data).hexdigest()}\t{name}'
        for name, data in contents.items()
    )
    return ('\n'.join(lines) + '\n').encode('utf-8')


def archive(contents: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as tf:
            for name, data in contents.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                tf.addfile(info, io.BytesIO(data))
    return output.getvalue()


def build() -> dict[str, bytes]:
    contents = payload_contents()
    preseed_template = SEED / 'preseed.cfg.tmpl'
    preseed = _read_regular(preseed_template, 'preseed.cfg.tmpl')
    if b'\x00' in preseed:
        raise ValueError('preseed template contains a NUL byte')
    helper = contents.get('scripts/common/source.sh')
    if helper is None:
        raise ValueError('Trixie payload lacks the source helper')
    preseed = preseed.replace(
        b'@SOURCE_HELPER_SHA256@', hashlib.sha256(helper).hexdigest().encode('ascii')
    )
    if b'@SOURCE_HELPER_SHA256@' in preseed:
        raise ValueError('preseed template contains an unresolved source-helper digest')
    archive_bytes = archive(contents)
    return {
        'payload.tar.gz': archive_bytes,
        'payload.manifest': manifest(contents, hashlib.sha256(archive_bytes).hexdigest()),
        'preseed.cfg': preseed,
    }


def main() -> int:
    try:
        products = build()
        publish_snapshot(SEED, products)
        print(f'built {len(products["payload.manifest"].splitlines()) - 2} Trixie payload files')
        return 0
    except (OSError, ValueError) as error:
        print(f'Trixie build failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
