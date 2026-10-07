#!/usr/bin/python3 -I
"""Install the pinned upstream FLZMA2-capable 7zz binary, never build source."""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
import re
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile

# Upstream immutable release asset digests (GitHub release asset SHA-256).
# https://github.com/mcmilk/7-Zip-zstd/releases/tag/v26.02-v1.5.7-R2
TAG = 'v26.02-v1.5.7-R2'
RELEASES = {
    'amd64': ('x64', 62, 'be246e5a284d3b5e738bad5cbb24c2662996ddb9776e09575b5099ab53fa0ba3'),
    'arm64': ('arm64', 183, '64511f6ebc32d5257a535b33b21a5b6712c72aa91e28524f41e1ce92e803c909'),
}
DESTINATION = Path('/usr/local/lib/compz')
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C'}
MAX_DOWNLOAD = 16 * 1024**2
MAX_EXPANDED = 64 * 1024**2


class Error(RuntimeError):
    """An unverified codec must never become executable installation policy."""


def trusted_directory(path: Path) -> None:
    if not path.is_absolute():
        raise Error('expected an absolute installation path')
    for parent in reversed((path, *path.parents)):
        if not parent.exists():
            parent.mkdir(mode=0o755)
        value = parent.lstat()
        if (not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022):
            raise Error(f'unsafe installation directory: {parent}')
    path.chmod(0o755)


def extract_binary(archive: Path, target: Path, machine: int) -> None:
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        names = set()
        total = 0
        if not 1 <= len(entries) <= 32:
            raise Error('invalid codec archive member count')
        for item in entries:
            name = item.filename
            mode = item.external_attr >> 16
            if (not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', name) or name in ('.', '..') or
                    name in names or item.flag_bits & 1 or
                    stat.S_IFMT(mode) not in (0, stat.S_IFREG) or
                    not 0 <= item.file_size <= MAX_EXPANDED):
                raise Error('invalid codec release archive member')
            names.add(name)
            total += item.file_size
        if total > MAX_EXPANDED or '7zz' not in names:
            raise Error('codec release has no bounded standalone 7zz payload')
        with package.open('7zz') as source, target.open('xb') as output:
            copied = 0
            while block := source.read(1024 * 1024):
                copied += len(block)
                if copied > MAX_EXPANDED:
                    raise Error('codec binary exceeds its extraction bound')
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
    with target.open('rb') as source:
        header = source.read(64)
    if (len(header) != 64 or header[:6] != b'\x7fELF\x02\x01' or
            struct.unpack_from('<H', header, 18)[0] != machine):
        raise Error('codec release is not an ELF64 binary for this target')
    target.chmod(0o700)


def verify_codec(binary: Path, directory: Path) -> None:
    def run(arguments: list[str]) -> str:
        result = subprocess.run([str(binary), *arguments], cwd=directory, env=ENV,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                errors='replace', timeout=60, check=True)
        return result.stdout
    if not re.search(r'\bFLZMA2\b', run(['i'])):
        raise Error('the pinned 7zz binary does not advertise FLZMA2')
    data = b'compz FLZMA2 installation verification\n' * 256
    (directory / 'probe').write_bytes(data)
    run(['a', '-bd', '-y', '-t7z', '-m0=FLZMA2', '-mx=1', '-mmt=1', '--', 'probe.7z', 'probe'])
    run(['t', '-bd', '--', 'probe.7z'])
    run(['x', '-bd', '-y', '-oextracted', '--', 'probe.7z'])
    if (directory / 'extracted/probe').read_bytes() != data:
        raise Error('FLZMA2 installation round trip failed')


def install() -> None:
    if os.geteuid() != 0 or sys.argv[1:]:
        raise Error('the codec installer requires root and takes no arguments')
    os.umask(0o077)
    architecture = subprocess.run(['/usr/bin/dpkg', '--print-architecture'], env=ENV,
                                  capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    if architecture not in RELEASES:
        raise Error('no verified upstream FLZMA2 binary is pinned for architecture ' + architecture)
    variant, machine, expected = RELEASES[architecture]
    trusted_directory(DESTINATION)
    # Keep both the lock and execution probe off noexec temporary filesystems.
    lock_fd = os.open(DESTINATION / '.install.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        value = os.fstat(lock_fd)
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_uid != 0 or value.st_mode & 0o077:
            raise Error('unsafe codec installation lock')
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix='.install-', dir=DESTINATION) as temporary:
            work = Path(temporary)
            archive = work / 'release.zip'
            url = f'https://github.com/mcmilk/7-Zip-zstd/releases/download/{TAG}/linux-gcc-{variant}.zip'
            subprocess.run(['/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error',
                            '--location', '--proto', '=https', '--proto-redir', '=https', '--max-redirs', '4',
                            '--connect-timeout', '15', '--max-time', '300', '--retry', '2',
                            '--retry-max-time', '300', '--max-filesize', str(MAX_DOWNLOAD),
                            '--output', str(archive), '--url', url], env=ENV,
                           stdin=subprocess.DEVNULL, timeout=340, check=True)
            if not 1 <= archive.stat().st_size <= MAX_DOWNLOAD:
                raise Error('invalid codec download size')
            with archive.open('rb') as source:
                actual = hashlib.file_digest(source, 'sha256').hexdigest()
            if actual != expected:
                raise Error('codec SHA-256 mismatch; nothing installed')
            binary = work / '7zz'
            extract_binary(archive, binary, machine)
            verify_codec(binary, work)
            binary.chmod(0o755)
            os.replace(binary, DESTINATION / '7zz')
            directory_fd = os.open(DESTINATION, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            print(f'compz: installed verified {TAG} {architecture} standalone FLZMA2 codec')
    finally:
        os.close(lock_fd)


def main() -> int:
    def interrupted(signum, frame):
        raise Error('codec installation interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        install()
        return 0
    except (Error, OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print('compz codec installation: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
