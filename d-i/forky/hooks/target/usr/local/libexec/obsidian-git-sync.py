#!/usr/bin/python3 -IB
"""Commit a quiescent Obsidian vault and fast-forward its configured branch."""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import os
from pathlib import Path
from pathlib import PurePosixPath
import pwd
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

QUIET_SECONDS = 30
AUTO_POLICY = Path('/etc/obsidian-git-sync.conf')
MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_VAULT_ENTRIES = 50_000
MAX_POLICY_BYTES = 4096


class SyncError(Exception):
    pass


def _read_policy_bytes() -> bytes:
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
                value = stream.read(MAX_POLICY_BYTES + 1)
                if len(value) > MAX_POLICY_BYTES:
                    raise SyncError('automatic Git policy is oversized')
        finally:
            os.close(dfd)
        return value
    for parent in AUTO_POLICY.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SyncError('untrusted automatic Git policy directory')
    try:
        fd = os.open(AUTO_POLICY, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return b''
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_nlink != 1 or info.st_mode & 0o022):
            raise SyncError('untrusted automatic Git policy file')
        value = stream.read(MAX_POLICY_BYTES + 1)
    if len(value) > MAX_POLICY_BYTES:
        raise SyncError('automatic Git policy is oversized')
    return value


def parse_policy(value: bytes) -> dict[str, object]:
    try:
        lines = value.decode('ascii').splitlines()
    except UnicodeDecodeError as exc:
        raise SyncError('invalid Obsidian Git policy encoding') from exc
    allowed = {
        'OBSIDIAN_GIT_AUTO_ENABLE',
        'OBSIDIAN_GIT_REPOSITORY_URL',
        'OBSIDIAN_GIT_REPOSITORY_BRANCH',
        'OBSIDIAN_GIT_DIRECTORY',
    }
    entries: dict[str, str] = {}
    for line in lines:
        key, separator, item = line.partition('=')
        if not separator or key not in allowed or key in entries or not item:
            raise SyncError('invalid Obsidian Git policy entry')
        if any(ord(char) < 0x20 or ord(char) == 0x7f for char in item):
            raise SyncError('invalid Obsidian Git policy value')
        entries[key] = item
    if set(entries) != allowed:
        raise SyncError('incomplete Obsidian Git policy')
    enabled = entries['OBSIDIAN_GIT_AUTO_ENABLE']
    if enabled not in ('true', 'false'):
        raise SyncError('invalid OBSIDIAN_GIT_AUTO_ENABLE policy')
    url = entries['OBSIDIAN_GIT_REPOSITORY_URL']
    if (not re.fullmatch(r'git@[A-Za-z0-9.-]+:[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+', url)
            or '..' in url or '//' in url or url.endswith('/')):
        raise SyncError('invalid Obsidian Git repository URL')
    branch = entries['OBSIDIAN_GIT_REPOSITORY_BRANCH']
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', branch)
            or branch.endswith('/') or '//' in branch or '..' in branch):
        raise SyncError('invalid Obsidian Git primary branch')
    directory = entries['OBSIDIAN_GIT_DIRECTORY']
    directory_path = PurePosixPath(directory)
    if (not re.fullmatch(r'[A-Za-z0-9._-]+/[A-Za-z0-9._-]+', directory)
            or len(directory_path.parts) != 2):
        raise SyncError('invalid Obsidian Git checkout directory')
    return {
        'enabled': enabled == 'true',
        'url': url,
        'branch': branch,
        'directory': directory_path,
    }


def load_policy() -> dict[str, object]:
    value = _read_policy_bytes()
    if not value:
        return {'enabled': False}
    return parse_policy(value)


def auto_enabled() -> bool:
    return bool(load_policy()['enabled'])


def git(root: Path, *args: str) -> bytes:
    pending = root / '.git/obsidian-git-sync.pending'
    if os.path.lexists(pending):
        raise SyncError('previous Git termination is unresolved; reconcile .git/obsidian-git-sync.pending before retrying')
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
        deadline = time.monotonic() + 180
        output = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(proc.args, 180)
                    for key, _ in selector.select(remaining):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if len(output) + len(chunk) > MAX_GIT_OUTPUT_BYTES:
                            raise SyncError('Git output exceeded 16 MiB')
                        output.extend(chunk)
            proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise SyncError(f'Git {args[0]} timed out') from exc
        if proc.returncode:
            raise SyncError(f'Git {args[0]} failed (exit {proc.returncode})')
        return bytes(output)
    finally:
        try:
            if proc.returncode is None:
                # No poll/reap occurs between group signals: the unreaped
                # leader pins the group identity even if it has already exited.
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    time.sleep(0.2)
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=4.8)
                except subprocess.TimeoutExpired as exc:
                    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(b'Git process termination outcome unknown; reconcile before retry.\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                    directory = os.open(pending.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                    raise SyncError('Git termination outcome unknown; vault and recovery marker retained') from exc
        finally:
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
    names = set()
    for arguments in (('ls-tree', '-r', '--name-only', '-z', 'HEAD'),
                      ('ls-files', '--cached', '--others', '--exclude-standard', '-z')):
        data = git(root, *arguments)
        offset = 0
        while offset < len(data):
            end = data.find(b'\0', offset)
            if end < 0:
                raise SyncError('Git returned an incomplete vault entry list')
            name = data[offset:end]
            offset = end + 1
            if name:
                names.add(name)
                if len(names) > MAX_VAULT_ENTRIES:
                    raise SyncError('vault entry count exceeds 50000')
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


def sync(root: Path, policy: dict[str, object]) -> str:
    if not policy['enabled']:
        return 'automatic Git publication disabled; add, commit and push manually'
    url = str(policy['url'])
    branch = str(policy['branch'])
    owned_dir(root.parent.parent)
    owned_dir(root.parent)
    owned_dir(root)
    owned_dir(root/'.git')
    if git(root, 'rev-parse', '--show-toplevel').strip() != os.fsencode(root):
        raise SyncError('vault is not the expected Git worktree')
    if git(root, 'symbolic-ref', '--short', 'HEAD').strip() != branch.encode():
        raise SyncError(f'vault must remain checked out on {branch}')
    if git(root, 'remote', 'get-url', 'origin').strip() != url.encode():
        raise SyncError('vault origin does not match the approved SSH repository')
    if git(root, 'remote', 'get-url', '--push', '--all', 'origin').splitlines() != [url.encode()]:
        raise SyncError('vault push destination does not match the approved SSH repository')
    if git(root, 'rev-parse', '--abbrev-ref', '@{upstream}').strip() != f'origin/{branch}'.encode():
        raise SyncError(f'vault does not track origin/{branch}')

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
        # Fetch the configured branch explicitly after a single-branch clone.
        remote = {}
        advertised = git(root, 'ls-remote', '--heads', 'origin',
                         f'refs/heads/{branch}')
        for row in advertised.splitlines():
            sha, ref = row.split(b'\t', 1)
            name = ref.removeprefix(b'refs/heads/').decode('ascii')
            if name != branch or name in remote or len(sha) not in (40, 64):
                raise SyncError('unexpected remote branch advertisement')
            remote[name] = sha
        if branch not in remote:
            raise SyncError(f'remote {branch} is missing')
        git(root, 'fetch', '--no-tags', 'origin',
            f'+refs/heads/{branch}:refs/remotes/origin/{branch}')
        head = git(root, 'rev-parse', 'HEAD').strip()
        base = git(root, 'merge-base', remote[branch].decode(), head.decode()).strip()
        if base != remote[branch]:
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
        if remote.get(branch) == head:
            return 'configured branch already up to date'
        git(root, 'push', '--atomic', 'origin',
            f'{head.decode()}:refs/heads/{branch}')
        return f'pushed {branch} atomically'
    finally:
        os.close(fd)


def main() -> int:
    try:
        if os.getuid() == 0 or sys.argv[1:] not in ([], ['--check-auto-enabled']):
            raise SyncError('run as the desktop user with no arguments or --check-auto-enabled')
        policy = load_policy()
        if sys.argv[1:] == ['--check-auto-enabled']:
            return 0 if policy['enabled'] else 1
        if not policy['enabled']:
            print('obsidian-git-sync: automatic Git publication disabled; add, commit and push manually')
            return 0
        account = pwd.getpwuid(os.getuid())
        if os.environ.get('HOME') != account.pw_dir or not account.pw_dir.startswith('/home/'):
            raise SyncError('unexpected desktop account home')
        print('obsidian-git-sync: '+sync(Path(account.pw_dir)/policy['directory'], policy))
    except (OSError, ValueError, subprocess.SubprocessError, SyncError) as exc:
        print(f'obsidian-git-sync: {exc}', file=sys.stderr)
        return 2 if sys.argv[1:] == ['--check-auto-enabled'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
