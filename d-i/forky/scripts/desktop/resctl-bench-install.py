#!/usr/bin/python3 -I
"""Install a pinned resctl-bench release inside the target; never benchmark.

The archive's installer is data, never executable installation policy. Files
are copied explicitly from validated regular members, without extractall().
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

BINS = frozenset({'resctl-bench', 'rd-agent', 'rd-hashd', 'resctl-demo'})
REQUIRED_BINS = BINS - {'resctl-demo'}
BIN_DIR = Path('/usr/local/bin')
DOC_DIR = Path('/data/docs/resctl-bench')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/nonexistent'}


class Error(RuntimeError):
    """Fail closed before publishing an unverified release."""


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def policy(args: argparse.Namespace) -> None:
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', args.version):
        raise Error('invalid release version')
    if (not re.fullmatch(r'resctl-bench-v[A-Za-z0-9._-]{1,100}', args.tag)
            or '..' in args.tag):
        raise Error('invalid release tag')
    if args.architecture != 'amd64':
        raise Error('the pinned native x86-64 release requires an amd64 target')
    expected = (f'https://github.com/mjcramerz/resctl-bench/releases/download/{args.tag}/'
                f'resctl-bench-{args.version}-x86_64-unknown-linux-gnu-native.tar.gz')
    if args.url != expected or not re.fullmatch(r'[0-9a-f]{64}', args.sha256):
        raise Error('release URL/tag/version or SHA-256 is invalid')
    if not (1024 <= args.max_archive <= 536870912
            and args.max_archive <= args.max_extracted <= 2147483648
            and 3 <= args.max_members <= 16384):
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
    st = destination.lstat()
    if not stat.S_ISREG(st.st_mode) or not 1 <= st.st_size <= args.max_archive:
        raise Error('download is not a bounded regular archive')
    if digest(destination) != args.sha256:
        raise Error('archive SHA-256 mismatch; nothing installed')


def member_path(name: str) -> PurePosixPath:
    # A single conventional ./ prefix is harmless. Reject ambiguous aliases,
    # not just paths that happen to normalize outside the extraction root.
    if name.startswith('./'):
        name = name[2:]
    name = name.rstrip('/')
    if (not name or len(name) > 4096 or name.startswith('/') or '\\' in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(p in {'', '.', '..'} or len(p) > 255 for p in name.split('/'))
            or len(name.split('/')) > 32):
        raise Error('unsafe archive path')
    return PurePosixPath(name)


def unpack(args: argparse.Namespace, archive: Path, stage: Path) -> tuple[Path, list[str]]:
    # Bound the decompressed stream too: member-size totals alone do not limit
    # a gzip bomb made of PAX headers, padding, or concatenated gzip members.
    raw = stage.parent / 'release.tar'
    expanded = 0
    with gzip.open(archive, 'rb') as source, raw.open('xb') as output:
        while block := source.read(1024 * 1024):
            expanded += len(block)
            if expanded > args.max_extracted:
                raise Error('decompressed archive exceeds the configured ceiling')
            output.write(block)
    with tarfile.open(raw, mode='r:') as tar:
        members: dict[PurePosixPath, tarfile.TarInfo] = {}
        total = 0
        for item in tar:
            path = member_path(item.name)
            if len(members) >= args.max_members or path in members:
                raise Error('too many or duplicate archive members')
            if (not (item.isfile() or item.isdir()) or item.issparse()
                    or any(k.startswith('GNU.sparse') for k in item.pax_headers)):
                raise Error('links, sparse files and special nodes are forbidden')
            if item.size < 0 or item.size > args.max_extracted or (item.isdir() and item.size):
                raise Error('invalid or oversized archive member')
            total += item.size
            if total > args.max_extracted:
                raise Error('archive member sizes exceed the configured ceiling')
            members[path] = item
        roots = {p.parts[0] for p in members}
        prefix = f'resctl-bench-{args.version}-x86_64-unknown-linux-gnu-native'
        if len(roots) != 1:
            raise Error('release must have exactly one package directory')
        name = roots.pop()
        if not re.fullmatch(re.escape(prefix) + r'(?:-[A-Za-z0-9_-]{1,128})?', name):
            raise Error('unexpected release directory/version/architecture')
        for path, item in members.items():
            if len(path.parts) == 1 and not item.isdir():
                raise Error('package root must be a directory')
            for parent in path.parents:
                if parent in members and not members[parent].isdir():
                    raise Error('archive file/directory collision')
        root = stage / name
        root.mkdir(parents=True, mode=0o755)
        binaries = []
        for path, item in members.items():
            dest = stage.joinpath(*path.parts)
            if item.isdir():
                dest.mkdir(parents=True, exist_ok=True, mode=0o755)
                continue
            rel = path.relative_to(name)
            if rel.parts[0] == 'bin':
                if len(rel.parts) == 2 and rel.name in BINS:
                    binaries.append(rel.name)
                elif not (len(rel.parts) == 3 and rel.parts[1] == '.debug'
                          and rel.name in {b + '.debug' for b in BINS}):
                    raise Error('unexpected executable payload')
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            source = tar.extractfile(item)
            if source is None:
                raise Error('unreadable archive member')
            with source, dest.open('xb') as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if dest.stat().st_size != item.size:
                raise Error('truncated archive member')
            dest.chmod(0o755 if rel.as_posix() == 'bin/' + rel.name and rel.name in BINS else 0o644)
        if not REQUIRED_BINS <= set(binaries):
            raise Error('resctl-bench, rd-agent and rd-hashd are all required')
        verify_release(root)
        for binary in binaries:
            with (root / 'bin' / binary).open('rb') as stream:
                header = stream.read(64)
            if (len(header) != 64 or header[:6] != b'\x7fELF\x02\x01'
                    or int.from_bytes(header[18:20], 'little') != 62
                    or int.from_bytes(header[16:18], 'little') not in {2, 3}):
                raise Error(f'{binary} is not an x86-64 ELF executable')
    raw.unlink()
    return root, sorted(binaries)


def verify_release(root: Path) -> None:
    sums = root / 'SHA256SUMS'
    if not sums.is_file() or sums.stat().st_size > 2 * 1024 * 1024:
        raise Error('missing or oversized release SHA256SUMS')
    expected = {}
    for line in sums.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match:
            raise Error('malformed release checksum record')
        name = member_path(match[2]).as_posix()
        if name in expected or name == 'SHA256SUMS':
            raise Error('duplicate or self-referential release checksum')
        expected[name] = match[1]
    actual = {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('*')
              if p.is_file() and p != sums}
    if actual != expected:
        raise Error('release member checksums or inventory do not match')


def smoke(root: Path, binaries: list[str], version: str, home: Path) -> None:
    # Native CPU and dynamic-loader compatibility must be checked on the target,
    # not guessed from amd64 alone. Drop credentials even for --version; never
    # run a benchmark, the bundled install.py, or a runtime tuning script.
    nobody = pwd.getpwnam('nobody')
    home.mkdir(mode=0o700)
    os.chown(home, nobody.pw_uid, nobody.pw_gid)
    environment = dict(ENV, HOME=str(home), PATH=str(root / 'bin') + ':' + ENV['PATH'])
    for binary in binaries:
        result = subprocess.run([str(root / 'bin' / binary), '--version'],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, env=environment, cwd=home, timeout=20,
                                user=nobody.pw_uid, group=nobody.pw_gid, extra_groups=())
        if result.returncode or (binary == 'resctl-bench' and not re.search(
                r'(?<![0-9.])' + re.escape(version) + r'(?![0-9.])', result.stdout)):
            raise Error(f'{binary} --version failed: native CPU/loader/version incompatibility '
                        f'(status {result.returncode}); nothing installed')


def trusted_directory(path: Path) -> None:
    if not path.is_absolute():
        raise Error('installation path must be absolute')
    for parent in reversed((path, *path.parents)):
        if not parent.exists() and not parent.is_symlink():
            parent.mkdir(mode=0o755)
        st = parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise Error(f'unsafe installation directory: {parent}')


def publish(args: argparse.Namespace, root: Path, binaries: list[str]) -> None:
    trusted_directory(BIN_DIR)
    trusted_directory(DOC_DIR)
    plan: dict[Path, tuple[Path, int]] = {}
    for source in sorted(root.rglob('*')):
        if not source.is_file():
            continue
        relative = source.relative_to(root)
        binary = len(relative.parts) == 2 and relative.parts[0] == 'bin' and relative.name in binaries
        destination = BIN_DIR / relative.name if binary else DOC_DIR / 'release' / relative
        plan[destination] = (source, 0o755 if binary else 0o644)
    metadata = root.parent / 'INSTALLATION.json'
    metadata.write_text(json.dumps({
        'format': 1, 'version': args.version, 'tag': args.tag, 'url': args.url,
        'archive_sha256': args.sha256, 'architecture': args.architecture,
        'archive_root': root.name, 'native_cpu_build': True,
        'files': {str(p): {'sha256': digest(s), 'mode': oct(m)} for p, (s, m) in plan.items()},
    }, sort_keys=True, indent=2) + '\n')
    # Provenance is committed last. Repeat installs are idempotent; never replace
    # a different/locally modified executable or document without explicit review.
    plan[DOC_DIR / 'INSTALLATION.json'] = (metadata, 0o644)
    pending = []
    for dest, (source, mode) in plan.items():
        trusted_directory(dest.parent)
        if dest.exists() or dest.is_symlink():
            st = dest.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1
                    or stat.S_IMODE(st.st_mode) != mode or digest(dest) != digest(source)):
                raise Error(f'refusing to overwrite an unmanaged or changed file: {dest}')
        else:
            pending.append((dest, source, mode))
    created = []
    try:
        for dest, source, mode in pending:
            fd, temporary = tempfile.mkstemp(prefix='.resctl-bench-', dir=dest.parent)
            try:
                with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
                    shutil.copyfileobj(input_file, output, length=1024 * 1024)
                    output.flush()
                    os.fchmod(output.fileno(), mode)
                    os.fsync(output.fileno())
                # link() gives no-clobber publication, unlike replace(). Each
                # temporary file is on the destination filesystem.
                os.link(temporary, dest, follow_symlinks=False)
                created.append(dest)
            finally:
                Path(temporary).unlink(missing_ok=True)
        for parent in {p.parent for p in created}:
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except BaseException:
        for dest in reversed(created):
            dest.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('version', 'tag', 'url', 'sha256', 'architecture'):
        parser.add_argument('--' + name, required=True)
    for name in ('max-archive', 'max-extracted', 'max-members'):
        parser.add_argument('--' + name, type=int, required=True)
    args = parser.parse_args()
    policy(args)
    if os.geteuid() != 0:
        raise Error('installer must run as root inside the target')
    architecture = subprocess.run(['/usr/bin/dpkg', '--print-architecture'],
                                  env=ENV, check=True, capture_output=True,
                                  text=True, timeout=10).stdout.strip()
    if architecture != args.architecture:
        raise Error('target architecture does not match the pinned release')
    os.umask(0o022)
    lock = os.open('/run/resctl-bench-install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(lock)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600:
            raise Error('unsafe installer lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix='resctl-bench-', dir='/var/tmp') as temporary:
            work = Path(temporary)
            archive = work / 'release.tar.gz'
            download(args, archive)
            stage = work / 'stage'
            stage.mkdir(mode=0o755)
            root, binaries = unpack(args, archive, stage)
            # Only verified public release data becomes readable to the smoke
            # process. All installation destinations are still untouched.
            work.chmod(0o755)
            smoke(root, binaries, args.version, work / 'smoke-home')
            publish(args, root, binaries)
    finally:
        os.close(lock)
    print(f'Installed resctl-bench {args.version}; docs: {DOC_DIR}; no benchmark executed')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Error, OSError, EOFError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print(f'resctl-bench installer: {exc}', file=sys.stderr)
        sys.exit(1)
