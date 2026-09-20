#!/usr/bin/python3 -I
"""Install profile-pinned font data; never execute archive contents.

Terminal/icon fonts and Microsoft desktop fonts have separate, fixed XDG trees.
Both immutable generations are verified before either current link is changed;
failed link publication rolls back under the existing installation lock.
Fontconfig belongs to the managed desktop skeleton, not this data installer.
Root seals the cache; HOME publication/cache permanently drops to the account.
"""
import argparse
import fcntl
import hashlib
import json
import lzma
import os
import pwd
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

CACHE = Path('/var/cache/installer-desktop-fonts')
SKEL = Path('/etc/skel-desktop')
NAMES = ('FiraCode', 'NerdFontsSymbolsOnly', 'ProFont', 'MicrosoftAptosFonts', 'MicrosoftLocalFonts')
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_MEMBER = 128 * 1024 * 1024
MAX_MEMBERS = 12000
MANIFEST = 'release-manifest.json'
GROUPS = {
    "terminal": ("FiraCode", "NerdFontsSymbolsOnly", "ProFont"),
    "microsoft": ("MicrosoftAptosFonts", "MicrosoftLocalFonts"),
}
PUBLICATION_ROOTS = {
    "terminal": ".local/share/icons/terminal-fonts",
    "microsoft": ".local/share/fonts/microsoft-fonts",
}


def digest(path: Path) -> str:
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_dir(path.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def checked_directory(path: Path, uid: int) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
        raise ValueError(f'unsafe directory ownership/mode/type: {path}')


def mkdir_below(base: Path, relative: str, uid: int, mode: int = 0o755) -> Path:
    checked_directory(base, uid)
    current = base
    for part in PurePosixPath(relative).parts:
        if part in ('.', '..', '/'):
            raise ValueError('unsafe directory component')
        current /= part
        try:
            current.mkdir(mode=mode)
        except FileExistsError:
            pass
        checked_directory(current, uid)
    return current


def validate_policy(triples: list[list[str]]) -> list[dict[str, str]]:
    if len(triples) != len(NAMES) or {row[0] for row in triples} != set(NAMES):
        raise ValueError('exactly the five configured font archives are required')
    policy = []
    for name, url, sha in triples:
        pattern = (r'https://github\.com/mjcramerz/fonts/releases/download/'
                   r'[A-Za-z0-9][A-Za-z0-9._-]*/' + re.escape(name) + r'\.tar\.xz')
        if not re.fullmatch(pattern, url) or not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise ValueError('invalid pinned font URL or SHA-256 for ' + name)
        policy.append({'name': name, 'url': url, 'sha256': sha})
    return sorted(policy, key=lambda item: item['name'])


def policy_id(policy: list[dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps({'schema': 1, 'archives': policy},
                                    sort_keys=True).encode()).hexdigest()


def member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or any(
            ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('unsafe font archive path')
    return path


class BoundedStream:
    """Bound all decompressed bytes, including tar/PAX headers and padding."""
    def __init__(self, stream, limit: int):
        self.stream = stream
        self.remaining = limit

    def read(self, size: int = -1) -> bytes:
        if size < 0 or size > self.remaining + 1:
            size = self.remaining + 1
        data = self.stream.read(size)
        self.remaining -= len(data)
        if self.remaining < 0:
            raise ValueError('decompressed font archive exceeds the limit')
        return data


def flush_tree(root: Path) -> None:
    for directory, _, files in os.walk(root, topdown=False):
        for name in files:
            fd = os.open(Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        sync_dir(Path(directory))


def extract_archive(archive: Path, destination: Path, sha: str) -> None:
    if archive.stat().st_size > MAX_ARCHIVE or digest(archive) != sha:
        raise ValueError('font archive size or SHA-256 mismatch')
    # Iterate streaming members to bound memory. Files are written only in a
    # private staging directory; a later invalid member can never be published.
    total = count = font_count = 0
    seen = set()
    with lzma.open(archive, 'rb') as decompressed, tarfile.open(
            fileobj=BoundedStream(decompressed, MAX_EXPANDED + MAX_MEMBERS * 2048),
            mode='r|') as source:
        for entry in source:
            count += 1
            if count > MAX_MEMBERS:
                raise ValueError('font archive has too many members')
            relative = member_path(entry.name)
            if relative == PurePosixPath('.') and entry.isdir():
                continue
            if relative in seen:
                raise ValueError('duplicate archive member')
            seen.add(relative)
            if not (entry.isdir() or entry.isfile()) or entry.issparse():
                raise ValueError('links, devices and sparse archive entries are forbidden')
            if entry.size < 0 or entry.size > MAX_MEMBER:
                raise ValueError('oversized font archive member')
            total += entry.size
            if total > MAX_EXPANDED:
                raise ValueError('font archive expands beyond the limit')
            target = destination.joinpath(*relative.parts)
            # No archive symlinks exist; all directories remain private until
            # the complete generation has passed checks and been sealed.
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if entry.isdir():
                target.mkdir(exist_ok=True, mode=0o700)
                continue
            with source.extractfile(entry) as incoming, target.open('xb') as outgoing:
                copied = 0
                while chunk := incoming.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > entry.size:
                        raise ValueError('archive member exceeds declared size')
                    outgoing.write(chunk)
                if copied != entry.size:
                    raise ValueError('truncated font archive')
            if target.suffix.lower() in ('.ttf', '.otf', '.ttc', '.otc'):
                font_count += 1
    if not font_count:
        raise ValueError('font archive contains no supported font files')


def file_inventory(root: Path, uid: int | None = None) -> dict[str, str]:
    uid = os.geteuid() if uid is None else uid
    records = {}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            checked_directory(Path(directory) / name, uid)
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == MANIFEST:
                continue
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != uid or info.st_mode & 0o022):
                raise ValueError('non-regular/hardlinked file in font generation')
            records[relative] = digest(path)
    return dict(sorted(records.items()))


def seal(root: Path, policy: list[dict[str, str]]) -> None:
    records = file_inventory(root)
    atomic_bytes(root / MANIFEST, json.dumps({'schema': 1, 'archives': policy,
                 'files': records}, sort_keys=True, indent=2).encode() + b'\n')
    for directory, _, files in os.walk(root):
        for name in files:
            os.chmod(Path(directory) / name, 0o644)
        os.chmod(directory, 0o755)
    flush_tree(root)


def verify_generation(root: Path, policy: list[dict[str, str]], uid: int | None = None,
                      expected_files: dict[str, str] | None = None) -> None:
    uid = os.geteuid() if uid is None else uid
    checked_directory(root, uid)
    if {p.name for p in root.iterdir()} != {p["name"] for p in policy} | {MANIFEST}:
        raise ValueError("unexpected archive group in font generation")
    marker = root / MANIFEST
    info = marker.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024
            or info.st_uid != uid or info.st_mode & 0o022 or info.st_nlink != 1):
        raise ValueError('invalid font generation manifest')
    record = json.loads(marker.read_text())
    if (record.get('schema') != 1 or record.get('archives') != policy or
            record.get('files') != file_inventory(root, uid) or
            (expected_files is not None and record.get('files') != expected_files)):
        raise ValueError(f'modified/incomplete font generation preserved: {root}')


def download(url: str, destination: Path, sha: str) -> None:
    subprocess.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
                    '--proto', '=https', '--proto-redir', '=https', '--tlsv1.2',
                    '--retry', '3', '--connect-timeout', '20', '--max-time', '600',
                    '--max-filesize', str(MAX_ARCHIVE), '--output', str(destination),
                    '--', url], check=True, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if destination.stat().st_size > MAX_ARCHIVE or digest(destination) != sha:
        raise ValueError('downloaded font archive failed SHA-256 verification')


def prepare_generation(cache: Path, policy: list[dict[str, str]]) -> Path:
    releases = mkdir_below(cache, 'releases', os.geteuid())
    generation = releases / policy_id(policy)
    if os.path.lexists(generation):
        verify_generation(generation, policy)
        return generation
    with tempfile.TemporaryDirectory(prefix='.font-stage-', dir=cache) as temporary:
        stage = Path(temporary)
        output = stage / 'generation'
        output.mkdir(mode=0o700)
        for item in policy:
            archive = stage / (item['name'] + '.tar.xz')
            download(item['url'], archive, item['sha256'])
            destination = output / item['name']
            destination.mkdir(mode=0o700)
            extract_archive(archive, destination, item['sha256'])
            archive.unlink()
        seal(output, policy)
        os.rename(output, generation)
        sync_dir(releases)
    return generation


def publication_group(name: str) -> str:
    for group, names in GROUPS.items():
        if name in names:
            return group
    raise ValueError("unknown font archive name")


def replace_current(current: Path, target: str) -> None:
    temporary = current.parent / (".current-" + secrets.token_hex(12))
    try:
        os.symlink(target, temporary)
        os.replace(temporary, current)
        sync_dir(current.parent)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def publish(home: Path, source: Path, policy: list[dict[str, str]]) -> tuple[tuple[Path, ...], bool]:
    # Callers hold CACHE/install.lock for cache, skeleton and user publications.
    # Source data remains root-owned in production, even after the uid drop.
    checked = validate_policy([[p["name"], p["url"], p["sha256"]] for p in policy])
    if checked != policy:
        raise ValueError("noncanonical font policy")
    uid = os.geteuid()
    source_uid = source.lstat().st_uid
    if source_uid not in (0, uid):
        raise ValueError("untrusted font cache owner")
    verify_generation(source, policy, source_uid)
    source_files = file_inventory(source, source_uid)
    identity = policy_id(policy)
    expected = "releases/" + identity
    prepared = []
    # Prepare and verify BOTH complete trees before exposing either new link.
    for group, names in GROUPS.items():
        subset = [p for p in policy if publication_group(p["name"]) == group]
        files = {name: sha for name, sha in source_files.items() if name.split("/", 1)[0] in names}
        base = mkdir_below(home, PUBLICATION_ROOTS[group], uid)
        releases = mkdir_below(base, "releases", uid)
        current = base / "current"
        previous = None
        if os.path.lexists(current):
            info = current.lstat()
            if not stat.S_ISLNK(info.st_mode) or info.st_uid != uid:
                raise ValueError("unmanaged font current entry preserved")
            previous = os.readlink(current)
            if not re.fullmatch(r"releases/[0-9a-f]{64}", previous):
                raise ValueError("unmanaged font current entry preserved")
            checked_directory(base / previous, uid)
        destination = releases / identity
        if os.path.lexists(destination):
            verify_generation(destination, subset, expected_files=files)
        else:
            with tempfile.TemporaryDirectory(prefix=".copy-", dir=base) as temporary:
                staging = Path(temporary) / "generation"
                staging.mkdir(mode=0o700)
                for item in subset:
                    # The verified cache cannot be changed by the account.
                    # Never copy a whole mixed archive set to either tree.
                    shutil.copytree(source / item["name"], staging / item["name"], symlinks=False)
                seal(staging, subset)
                verify_generation(staging, subset, expected_files=files)
                os.rename(staging, destination)
                sync_dir(releases)
        prepared.append((current, previous))
    attempted = []
    try:
        for current, previous in prepared:
            if previous != expected:
                # Record BEFORE replace: fsync can fail after a successful swap.
                attempted.append((current, previous))
                replace_current(current, expected)
    except BaseException:
        errors = []
        for current, previous in reversed(attempted):
            try:
                actual = os.readlink(current) if current.is_symlink() else None
                if actual == previous and (previous is not None or not os.path.lexists(current)):
                    continue
                if actual != expected:
                    raise ValueError("font pointer changed outside the installation lock")
                if previous is None:
                    current.unlink()
                    sync_dir(current.parent)
                else:
                    replace_current(current, previous)
            except BaseException as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("font publication rollback failed: " + "; ".join(errors))
        raise
    return tuple(current for current, _ in prepared), bool(attempted)


def font_cache(home: Path, currents: tuple[Path, ...], cache_home: Path, identity: str,
               changed: bool) -> None:
    markers = [current.parent / ".cache-ready" for current in currents]
    if (not changed and all(marker.is_file() and not marker.is_symlink()
                            and marker.read_text() == identity + "\n" for marker in markers)):
        return
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8",
           "XDG_CONFIG_HOME": str(home / ".config"),
           "XDG_DATA_HOME": str(home / ".local/share"), "XDG_CACHE_HOME": str(cache_home)}
    subprocess.run(["/usr/bin/fc-cache", "--force", *(str(p) for p in currents)], env=env, check=True)
    for marker in markers:
        atomic_bytes(marker, (identity + "\n").encode(), 0o600)


def prepare_user_parents(account) -> None:
    """Repair only the install-created XDG parents, never follow home links.

    The earlier skeleton installer can leave .local/share owned by root.
    Pin each directory by fd before changing ownership; all actual font data
    publication still occurs only after dropping to the account.
    """
    if account.pw_uid == 0:
        raise ValueError('font account must not be root')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(account.pw_dir, flags)
    try:
        info = os.fstat(parent)
        if info.st_uid != account.pw_uid or info.st_mode & 0o022:
            raise ValueError('font account home has unsafe ownership/mode')
        for name in ('.local', 'share'):
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            child = os.open(name, flags, dir_fd=parent)
            try:
                info = os.fstat(child)
                if info.st_uid not in (0, account.pw_uid) or info.st_mode & 0o022:
                    raise ValueError('font XDG parent has unsafe ownership/mode')
                if info.st_uid == 0:
                    os.fchown(child, account.pw_uid, account.pw_gid)
            except BaseException:
                os.close(child)
                raise
            os.close(parent)
            parent = child
    finally:
        os.close(parent)


def install_user(account, source: Path, policy: list[dict[str, str]]) -> None:
    # Only fixed XDG parent ownership is prepared via no-follow directory fds.
    # Font copying and cache execution are always unprivileged.
    prepare_user_parents(account)
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups([])
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            os.umask(0o022)
            home = Path(account.pw_dir)
            current, changed = publish(home, source, policy)
            cache_home = mkdir_below(home, '.cache', account.pw_uid, 0o700)
            font_cache(home, current, cache_home, policy_id(policy), changed)
        except Exception as error:
            print('desktop fonts (user): ' + str(error), file=sys.stderr, flush=True)
            os._exit(1)
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    if os.waitstatus_to_exitcode(status) != 0:
        raise RuntimeError('user font publication/cache failed')


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', nargs=3, action='append', metavar=('NAME', 'URL', 'SHA256'), required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--home', required=True)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise ValueError('font installation requires the installer root context')
    account = pwd.getpwnam(args.account)
    if account.pw_uid == 0 or args.home != account.pw_dir or not Path(args.home).is_absolute():
        raise ValueError('font account/home must match the non-root passwd entry')
    policy = validate_policy(args.archive)
    os.umask(0o022)
    checked_directory(CACHE.parent, 0)
    checked_directory(SKEL.parent, 0)
    CACHE.mkdir(mode=0o755, exist_ok=True)
    checked_directory(CACHE, 0)
    checked_directory(SKEL, 0)
    lock = os.open(CACHE / 'install.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('unsafe font installation lock')
        fcntl.flock(lock, fcntl.LOCK_EX)
        source = prepare_generation(CACHE, policy)
        current, changed = publish(SKEL, source, policy)
        skel_cache = mkdir_below(CACHE, 'skel-cache', 0, 0o700)
        font_cache(SKEL, current, skel_cache, policy_id(policy), changed)
        install_user(account, source, policy)
    finally:
        os.close(lock)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, RuntimeError, tarfile.TarError, lzma.LZMAError, subprocess.CalledProcessError) as error:
        print('desktop fonts: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
