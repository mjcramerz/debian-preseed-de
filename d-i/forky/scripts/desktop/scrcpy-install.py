#!/usr/bin/python3 -I
"""Install a pinned official scrcpy archive without executing archive data."""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse

BIN_DIR = Path('/usr/local/bin')
DOC_DIR = Path('/usr/local/share/doc/scrcpy')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/nonexistent'}
CLIENT = 'scrcpy'
SERVER = 'scrcpy-server'


class Error(RuntimeError):
    """Fail closed before publishing an unverified release."""


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def policy(args: argparse.Namespace) -> None:
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', args.version):
        raise Error('invalid release version')
    if args.tag != 'v' + args.version:
        raise Error('release tag must match version')
    if args.architecture != 'amd64':
        raise Error('the pinned Linux x86-64 release requires an amd64 target')
    if not re.fullmatch(r'[0-9a-f]{64}', args.sha256):
        raise Error('invalid scrcpy archive SHA-256')
    if not re.fullmatch(r'[0-9a-f]{64}', args.server_sha256):
        raise Error('invalid scrcpy server SHA-256')
    parsed = urllib.parse.urlsplit(args.url)
    archive_name = Path(parsed.path).name
    if (parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment or
            not re.fullmatch(r'[A-Za-z0-9._-]+\.tar\.gz', archive_name)):
        raise Error('invalid scrcpy release URL or archive filename')
    if not (args.max_archive > 0 and args.max_archive <= args.max_extracted and args.max_members >= 1):
        raise Error('release size/member bounds are invalid')


def download(args: argparse.Namespace, destination: Path) -> None:
    subprocess.run([
        '/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error',
        '--location', '--proto', '=https', '--proto-redir', '=https',
        '--connect-timeout', '15', '--max-time', '300', '--max-redirs', '4',
        '--retry', '2', '--retry-max-time', '300',
        '--max-filesize', str(args.max_archive), '--output', str(destination),
        '--url', args.url,
    ], env=ENV, stdin=subprocess.DEVNULL, check=True, timeout=340)
    info = destination.lstat()
    if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= args.max_archive:
        raise Error('download is not a bounded regular archive')
    actual = digest(destination)
    if actual != args.sha256:
        raise Error(f'archive SHA-256 mismatch; expected {args.sha256}, got {actual}')


def member_path(name: str) -> PurePosixPath:
    if name.startswith('./'):
        name = name[2:]
    name = name.rstrip('/')
    if (not name or len(name) > 4096 or name.startswith('/') or '\\' in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or any(part in {'', '.', '..'} or len(part) > 255 for part in name.split('/'))
            or len(name.split('/')) > 32):
        raise Error('unsafe archive path')
    return PurePosixPath(name)


def unpack(args: argparse.Namespace, archive: Path, stage: Path) -> tuple[Path, dict[str, Path]]:
    raw = stage.parent / 'release.tar'
    expanded = 0
    with gzip.open(archive, 'rb') as source, raw.open('xb') as output:
        while block := source.read(1024 * 1024):
            expanded += len(block)
            if expanded > args.max_extracted:
                raise Error('decompressed archive exceeds the configured ceiling')
            output.write(block)

    archive_name = Path(urllib.parse.urlsplit(args.url).path).name
    expected_root = archive_name.removesuffix('.tar.gz')
    with tarfile.open(raw, mode='r:') as tar:
        members: dict[PurePosixPath, tarfile.TarInfo] = {}
        total = 0
        for item in tar:
            path = member_path(item.name)
            if len(members) >= args.max_members or path in members:
                raise Error('too many or duplicate archive members')
            if (not (item.isfile() or item.isdir()) or item.issparse()
                    or any(key.startswith('GNU.sparse') for key in item.pax_headers)):
                raise Error('links, sparse files and special nodes are forbidden')
            if item.size < 0 or item.size > args.max_extracted or (item.isdir() and item.size):
                raise Error('invalid or oversized archive member')
            total += item.size
            if total > args.max_extracted:
                raise Error('archive member sizes exceed the configured ceiling')
            members[path] = item

        roots = {path.parts[0] for path in members}
        if roots != {expected_root}:
            raise Error('release must contain exactly one expected package directory')
        root_path = PurePosixPath(expected_root)
        root_item = members.get(root_path)
        if root_item is None or not root_item.isdir():
            raise Error('release package directory is missing')
        # Release archives may include bundled helpers and documentation.  The
        # desktop role needs only these two files; every other member is
        # ignored and never published, regardless of its archive mode.
        for path, item in members.items():
            if any(parent in members and not members[parent].isdir() for parent in path.parents):
                raise Error('archive file/directory collision')

        files: dict[str, Path] = {}
        root = stage / expected_root
        root.mkdir(mode=0o755)
        for name in (CLIENT, SERVER):
            path = root_path / name
            item = members.get(path)
            if item is None or not item.isfile() or item.size == 0:
                raise Error(f'release member is missing or invalid: {name}')
            source = tar.extractfile(item)
            if source is None:
                raise Error(f'release member is unreadable: {name}')
            destination = root / name
            with source, destination.open('xb') as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if destination.stat().st_size != item.size:
                raise Error(f'release member is truncated: {name}')
            destination.chmod(0o755 if name == CLIENT else 0o644)
            files[name] = destination

        if digest(files[SERVER]) != args.server_sha256:
            raise Error('scrcpy server SHA-256 does not match the pinned release')

        with files[CLIENT].open('rb') as stream:
            header = stream.read(64)
        if (len(header) != 64 or header[:6] != b'\x7fELF\x02\x01'
                or int.from_bytes(header[18:20], 'little') != 62
                or int.from_bytes(header[16:18], 'little') not in {2, 3}):
            raise Error('scrcpy client is not an x86-64 ELF executable')
    raw.unlink()
    return root, files


def trusted_directory(path: Path) -> None:
    if not path.is_absolute():
        raise Error('installation path must be absolute')
    for parent in reversed((path, *path.parents)):
        if not parent.exists() and not parent.is_symlink():
            parent.mkdir(mode=0o755)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Error(f'unsafe installation directory: {parent}')


def publish(args: argparse.Namespace, root: Path, files: dict[str, Path]) -> None:
    trusted_directory(BIN_DIR)
    trusted_directory(DOC_DIR)
    metadata = {
        'format': 1,
        'version': args.version,
        'tag': args.tag,
        'url': args.url,
        'archive_sha256': args.sha256,
        'server_sha256': args.server_sha256,
        'architecture': args.architecture,
        'archive_root': root.name,
        'files': {
            str(BIN_DIR / CLIENT): {'sha256': digest(files[CLIENT]), 'mode': '0755'},
            str(BIN_DIR / SERVER): {'sha256': digest(files[SERVER]), 'mode': '0644'},
        },
    }
    metadata_source = root.parent / 'INSTALLATION.json'
    metadata_source.write_text(json.dumps(metadata, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    plan = [
        (BIN_DIR / CLIENT, files[CLIENT], 0o755),
        (BIN_DIR / SERVER, files[SERVER], 0o644),
        (DOC_DIR / 'INSTALLATION.json', metadata_source, 0o644),
    ]
    pending = []
    for destination, source, mode in plan:
        trusted_directory(destination.parent)
        if destination.exists() or destination.is_symlink():
            info = destination.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) != mode or digest(destination) != digest(source)):
                raise Error(f'refusing to overwrite an unmanaged or changed file: {destination}')
        else:
            pending.append((destination, source, mode))
    created: list[Path] = []
    try:
        for destination, source, mode in pending:
            fd, temporary = tempfile.mkstemp(prefix='.scrcpy-', dir=destination.parent)
            try:
                with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
                    shutil.copyfileobj(input_file, output, length=1024 * 1024)
                    output.flush()
                    os.fchmod(output.fileno(), mode)
                    os.fsync(output.fileno())
                os.link(temporary, destination, follow_symlinks=False)
                created.append(destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
        for parent in {path.parent for path in created}:
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except BaseException:
        for destination in reversed(created):
            destination.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('version', 'tag', 'url', 'sha256', 'server-sha256', 'architecture'):
        parser.add_argument('--' + name, required=True)
    for name in ('max-archive', 'max-extracted', 'max-members'):
        parser.add_argument('--' + name, type=int, required=True)
    parser.add_argument('--validate-only', action='store_true',
                        help='validate release pins offline without downloading or installing')
    args = parser.parse_args()
    policy(args)
    if args.validate_only:
        print(f'scrcpy release pins valid: version={args.version} tag={args.tag}')
        return 0
    if os.geteuid() != 0:
        raise Error('installer must run as root inside the target')
    architecture = subprocess.run(['/usr/bin/dpkg', '--print-architecture'], env=ENV,
                                  check=True, capture_output=True, text=True,
                                  timeout=10).stdout.strip()
    if architecture != args.architecture:
        raise Error('target architecture does not match the pinned release')
    lock = os.open('/run/scrcpy-install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise Error('unsafe installer lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix='scrcpy-', dir='/var/tmp') as temporary:
            work = Path(temporary)
            archive = work / 'release.tar.gz'
            download(args, archive)
            stage = work / 'stage'
            stage.mkdir(mode=0o755)
            root, files = unpack(args, archive, stage)
            publish(args, root, files)
    finally:
        os.close(lock)
    print(f'Installed scrcpy {args.version}; metadata: {DOC_DIR / "INSTALLATION.json"}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Error, OSError, EOFError, ValueError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print(f'scrcpy installer: {exc}', file=os.sys.stderr)
        raise SystemExit(1)
