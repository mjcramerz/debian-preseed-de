#!/usr/bin/python3 -I
"""Commit a quiescent Obsidian vault and fast-forward three GitLab branches."""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import os
from pathlib import Path
import pwd
import signal
import stat
import subprocess
import sys
import time

URL = 'git@gitlab.com:core-assets/docs/obsidian-md.git'
BRANCHES = ('mcr/main', 'mcr/staging', 'mcr/release')
QUIET_SECONDS = 30
AUTO_POLICY = Path('/etc/obsidian-git-sync.conf')


class SyncError(Exception):
    pass


def auto_enabled() -> bool:
    """Read the installed profile policy as data, never shell or environment."""
    directory = os.environ.get('CREDENTIALS_DIRECTORY')
    if directory is not None:
        # LoadCredential supplies an immutable, account-private snapshot made
        # by the user manager before filesystem sandboxing maps host root to
        # the overflow UID. Keep the namespace and the manual root-owner check.
        expected = Path(f'/run/user/{os.getuid()}/credentials/obsidian-git-sync.service')
        if directory != str(expected):
            raise SyncError('unexpected automatic Git credential directory')
        dfd = os.open(expected, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(dfd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise SyncError('untrusted automatic Git credential directory')
            fd = os.open('automatic-git-policy',
                         os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=dfd)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or info.st_mode & 0o377):
                    raise SyncError('untrusted automatic Git credential file')
                value = stream.read(128)
        finally:
            os.close(dfd)
        return parse_auto_policy(value)
    for parent in AUTO_POLICY.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SyncError('untrusted automatic Git policy directory')
    try:
        fd = os.open(AUTO_POLICY, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or info.st_mode & 0o022):
            raise SyncError('untrusted automatic Git policy file')
        value = stream.read(128)
    return parse_auto_policy(value)


def parse_auto_policy(value: bytes) -> bool:
    if value not in (b'OBSIDIAN_GIT_AUTO_ENABLE=true\n', b'OBSIDIAN_GIT_AUTO_ENABLE=false\n'):
        raise SyncError('invalid OBSIDIAN_GIT_AUTO_ENABLE policy')
    return value == b'OBSIDIAN_GIT_AUTO_ENABLE=true\n'


def git(root: Path, *args: str) -> bytes:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_') and key not in ('SSH_ASKPASS', 'SSH_AGENT_PID')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
               GIT_LFS_SKIP_SMUDGE='1', LC_ALL='C.UTF-8',
               GIT_SSH_COMMAND='/usr/bin/ssh -F '+str(Path.home()/'.ssh/config'))
    proc = subprocess.Popen(
        ['/usr/bin/git', '-c', 'core.hooksPath=/dev/null',
         '-c', 'submodule.recurse=false', '-c', 'protocol.file.allow=never',
         '-c', 'protocol.ext.allow=never', *args], cwd=root, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        try:
            output, _ = proc.communicate(timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise SyncError(f'Git {args[0]} timed out') from exc
        if proc.returncode:
            raise SyncError(f'Git {args[0]} failed (exit {proc.returncode})')
        return output
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


def owned_dir(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise SyncError('vault or parent directory is not a user-owned private directory')


def snapshot(root: Path, known: set[bytes] | None = None) -> dict[bytes, tuple]:
    """Read the same files Git can add, without following symlinks or FIFOs."""
    # HEAD retains tracked deletions even after add -A removes index entries.
    names = set(git(root, 'ls-tree', '-r', '--name-only', '-z', 'HEAD').split(b'\0'))
    names.update(git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\0'))
    names.discard(b'')
    if known is not None:
        if names - known:
            raise SyncError('new vault entries appeared during staging')
        names = known
    result: dict[bytes, tuple] = {}
    for name in sorted(filter(None, names)):
        path = os.fsencode(root) + b'/' + name
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            result[name] = ('deleted',)
            continue
        metadata = (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                    info.st_mtime_ns, info.st_ctime_ns)
        if stat.S_ISLNK(info.st_mode):
            digest = hashlib.sha256(os.fsencode(os.readlink(path))).digest()
        elif stat.S_ISREG(info.st_mode):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise SyncError('vault entry changed during inspection')
                digestor = hashlib.sha256()
                with os.fdopen(fd, 'rb', closefd=False) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digestor.update(block)
                digest = digestor.digest()
            finally:
                os.close(fd)
        else:
            raise SyncError('vault contains an unsupported file type')
        if os.lstat(path).st_mtime_ns != info.st_mtime_ns or os.lstat(path).st_ctime_ns != info.st_ctime_ns:
            raise SyncError('vault entry changed during inspection')
        result[name] = (*metadata, digest)
    return result


def sync(root: Path) -> str:
    if not auto_enabled():
        return 'automatic Git publication disabled; add, commit and push manually'
    owned_dir(root.parent.parent)
    owned_dir(root.parent)
    owned_dir(root)
    owned_dir(root/'.git')
    if git(root, 'rev-parse', '--show-toplevel').strip() != os.fsencode(root):
        raise SyncError('vault is not the expected Git worktree')
    if git(root, 'symbolic-ref', '--short', 'HEAD').strip() != BRANCHES[0].encode():
        raise SyncError('vault must remain checked out on mcr/main')
    if git(root, 'remote', 'get-url', 'origin').strip() != URL.encode():
        raise SyncError('vault origin does not match the approved SSH repository')
    if git(root, 'remote', 'get-url', '--push', '--all', 'origin').splitlines() != [URL.encode()]:
        raise SyncError('vault push destination does not match the approved SSH repository')
    if git(root, 'rev-parse', '--abbrev-ref', '@{upstream}').strip() != b'origin/mcr/main':
        raise SyncError('vault does not track origin/mcr/main')

    lock = root/'.git/obsidian-git-sync.lock'
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise SyncError('unsafe vault synchronization lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SyncError('another vault synchronization is running') from exc
        if (root/'.git/index.lock').exists():
            raise SyncError('another Git operation is active')
        if git(root, 'ls-files', '-u'):
            raise SyncError('unresolved merge conflicts')
        # Explicit refspecs also fetch staging/release after --single-branch clone.
        remote = {}
        advertised = git(root, 'ls-remote', '--heads', 'origin',
                         *(f'refs/heads/{name}' for name in BRANCHES))
        for row in advertised.splitlines():
            sha, ref = row.split(b'\t', 1)
            name = ref.removeprefix(b'refs/heads/').decode('ascii')
            if name not in BRANCHES or name in remote or len(sha) not in (40, 64):
                raise SyncError('unexpected remote branch advertisement')
            remote[name] = sha
        if BRANCHES[0] not in remote:
            raise SyncError('remote mcr/main is missing')
        git(root, 'fetch', '--no-tags', 'origin',
            *(f'+refs/heads/{name}:refs/remotes/origin/{name}' for name in remote))
        head = git(root, 'rev-parse', 'HEAD').strip()
        base = git(root, 'merge-base', remote[BRANCHES[0]].decode(), head.decode()).strip()
        if base != remote[BRANCHES[0]]:
            raise SyncError('remote main diverged; resolve manually without discarding notes')
        if git(root, 'diff', '--cached', '--name-only'):
            raise SyncError('user has staged changes; leave the index untouched')
        before = snapshot(root)
        changes = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
        if changes:
            for setting in ('user.name', 'user.email'):
                try:
                    identity = git(root, 'config', '--get', setting).strip()
                except SyncError:
                    identity = b''
                if not identity:
                    raise SyncError(f'configure a real Git {setting} before automatic commits')
            now = time.time_ns()
            if any(len(value) > 1 and now - value[4] < QUIET_SECONDS * 1_000_000_000
                   for value in before.values()):
                return 'recent edits; waiting for a quiet vault'
            git(root, 'add', '-A', '--', '.')
            if before != snapshot(root, set(before)):
                raise SyncError('vault changed during staging; no commit or push')
            if git(root, 'ls-files', '--stage').find(b'160000 ') >= 0:
                raise SyncError('nested Git repositories cannot be published as notes')
            if git(root, 'diff', '--cached', '--name-only'):
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                git(root, '-c', 'commit.gpgsign=false', 'commit', '--no-verify', '--no-gpg-sign',
                    '-m', f'Sync Obsidian vault {stamp}')
                if before != snapshot(root, set(before)):
                    raise SyncError('vault changed during commit; local commit kept, no push')
        head = git(root, 'rev-parse', 'HEAD').strip()
        for name in BRANCHES[1:]:
            if name in remote and git(root, 'merge-base', remote[name].decode(),
                                      head.decode()).strip() != remote[name]:
                raise SyncError(f'remote {name} diverged; refusing to overwrite it')
        if all(remote.get(name) == head for name in BRANCHES):
            return 'all branches already up to date'
        git(root, 'push', '--atomic', 'origin',
            *(f'{head.decode()}:refs/heads/{name}' for name in BRANCHES))
        return 'pushed mcr/main, mcr/staging and mcr/release atomically'
    finally:
        os.close(fd)


def main() -> int:
    try:
        if os.getuid() == 0 or sys.argv[1:] not in ([], ['--check-auto-enabled']):
            raise SyncError('run as the desktop user with no arguments or --check-auto-enabled')
        if sys.argv[1:] == ['--check-auto-enabled']:
            return 0 if auto_enabled() else 1
        account = pwd.getpwuid(os.getuid())
        if os.environ.get('HOME') != account.pw_dir or not account.pw_dir.startswith('/home/'):
            raise SyncError('unexpected desktop account home')
        print('obsidian-git-sync: '+sync(Path(account.pw_dir)/'Syncthing/obsidian-md'))
    except (OSError, ValueError, subprocess.SubprocessError, SyncError) as exc:
        print(f'obsidian-git-sync: {exc}', file=sys.stderr)
        return 2 if sys.argv[1:] == ['--check-auto-enabled'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
