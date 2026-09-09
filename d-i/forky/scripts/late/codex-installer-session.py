#!/usr/bin/python3
"""Run the unprivileged Codex installer inside the target's current /run view.

This is an installer-only supervisor, not a login session or user service.
It never creates, removes, or changes /run/user/<uid> and does not need logind.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

RUNTIME_PARENT = Path('/run/codex-installer')
INSTALL_TIMEOUT = 1800.0
STOP_TIMEOUT = 5.0
SIGNALS = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)


def log(message: str) -> None:
    print(f'codex-installer-session: {message}', file=sys.stderr, flush=True)


def direct_path(value: str) -> Path:
    if not re.fullmatch(r'/[A-Za-z0-9._/@+\-]+', value):
        raise ValueError('an installer path is not an approved absolute path')
    path = Path(value)
    if str(path) != value or '..' in path.parts or value == '/':
        raise ValueError('an installer path is not normalized')
    if path.resolve(strict=True) != path:
        raise ValueError(f'installer path traverses a symlink: {path}')
    return path


def root_owned(path: Path, *, directory: bool = False) -> os.stat_result:
    entry = path.lstat()
    correct_type = stat.S_ISDIR(entry.st_mode) if directory else stat.S_ISREG(entry.st_mode)
    # The deployed /data/codex root is root:devops mode 3770. Its sticky
    # bit protects root-owned helper entries from group-member replacement.
    writable = bool(entry.st_mode & 0o022)
    protected_sticky_directory = directory and bool(entry.st_mode & stat.S_ISVTX)
    if not correct_type or entry.st_uid != 0 or (writable and not protected_sticky_directory):
        raise ValueError(f'expected a protected root-owned managed path: {path}')
    return entry


def open_runtime_parent(path: Path) -> int:
    # The fixed parent is deliberately outside logind's session-managed tree.
    root_owned(direct_path(str(path.parent)), directory=True)
    try:
        path.mkdir(mode=0o755)
    except FileExistsError:
        pass
    else:
        # mkdir honours the supervisor's private umask; only the root-owned
        # parent needs traversal permission for the child account.
        os.chmod(path, 0o755, follow_symlinks=False)
    direct_path(str(path))
    entry = root_owned(path, directory=True)
    if stat.S_IMODE(entry.st_mode) != 0o755:
        raise ValueError(f'installer runtime parent must have mode 0755: {path}')
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def lock_account(parent_fd: int, uid: int) -> int:
    fd = os.open(f'{uid}.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=parent_fd)
    try:
        entry = os.fstat(fd)
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != 0 or
                stat.S_IMODE(entry.st_mode) != 0o600 or entry.st_nlink != 1):
            raise ValueError('unsafe Codex installer lock file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another Codex installer owns the account lock') from exc
        return fd
    except BaseException:
        os.close(fd)
        raise


def live_group(pgid: int) -> bool:
    """Ignore zombies while retaining the unreaped leader as the PID anchor."""
    if not Path('/proc/self/stat').is_file():
        return True  # Still bounded by STOP_TIMEOUT when procfs is unavailable.
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rpartition(')')[2].split()
            if len(fields) >= 3 and int(fields[2]) == pgid and fields[0] != 'Z':
                return True
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            continue
    return False


def signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        pass


def supervise(command: list[str], *, account: pwd.struct_passwd,
              home: Path, environment: dict[str, str], timeout: float) -> int:
    received = 0

    def interrupt(signum: int, _frame: object) -> None:
        nonlocal received
        if not received:
            received = signum

    old_handlers = {sig: signal.signal(sig, interrupt) for sig in SIGNALS}
    process = None
    status = 1
    try:
        process = subprocess.Popen(
            command, env=environment, cwd=home, stdin=subprocess.DEVNULL,
            user=account.pw_uid, group=account.pw_gid,
            extra_groups=os.getgrouplist(account.pw_name, account.pw_gid),
            umask=0o077, start_new_session=True, close_fds=True,
        )
        deadline = time.monotonic() + timeout
        # Observe, but do not reap, the leader until every group signal has been
        # sent. This prevents a recycled PID from receiving a teardown signal.
        while True:
            result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if received:
                status = 128 + received
                log(f'interrupted by signal {received}; stopping installer process group')
                break
            if result is not None:
                status = result.si_status if result.si_code == os.CLD_EXITED else 128 + result.si_status
                break
            if time.monotonic() >= deadline:
                status = 124
                log('installer deadline exceeded; stopping installer process group')
                break
            time.sleep(0.1)
    finally:
        for sig in SIGNALS:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if process is not None:
                signal_group(process.pid, signal.SIGTERM)
                deadline = time.monotonic() + STOP_TIMEOUT
                while live_group(process.pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                signal_group(process.pid, signal.SIGKILL)
                process.wait(timeout=STOP_TIMEOUT)
                # An uninterruptible descendant must not lose its runtime files.
                deadline = time.monotonic() + STOP_TIMEOUT
                while live_group(process.pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if live_group(process.pid):
                    raise RuntimeError('installer processes remain after SIGKILL; runtime retained')
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
    return status


def main(argv: list[str], *, runtime_parent: Path = RUNTIME_PARENT,
         timeout: float = INSTALL_TIMEOUT) -> int:
    if os.geteuid() != 0:
        raise PermissionError('the installer-session supervisor must run as root inside in-target')
    if len(argv) != 7:
        raise ValueError('usage: codex-installer-session.py USER HOME HELPER URL MAX_BYTES CODEX_HOME PACKAGES')
    username, home_text, helper_text, *installer_args = argv
    try:
        account = pwd.getpwnam(username)
    except KeyError as exc:
        raise ValueError('the requested installer account does not exist') from exc
    if account.pw_uid == 0 or account.pw_dir != home_text:
        raise ValueError('the target account must be non-root and HOME must match passwd')
    home = direct_path(home_text)
    helper = direct_path(helper_text)
    root_owned(helper)
    for ancestor in helper.parents:
        root_owned(ancestor, directory=True)
    if not os.access(helper, os.X_OK):
        raise ValueError('the staged standalone installer is not executable')
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError('descriptor-relative safe runtime cleanup is unavailable')

    os.umask(0o077)
    parent_fd = open_runtime_parent(runtime_parent)
    lock_fd = None
    runtime = None
    runtime_identity = None
    stopped = True
    try:
        lock_fd = lock_account(parent_fd, account.pw_uid)
        runtime = Path(tempfile.mkdtemp(prefix=f'{account.pw_uid}.', dir=runtime_parent))
        runtime_fd = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fchmod(runtime_fd, 0o700)
            os.fchown(runtime_fd, account.pw_uid, account.pw_gid)
            entry = os.fstat(runtime_fd)
            runtime_identity = (entry.st_dev, entry.st_ino)
        finally:
            os.close(runtime_fd)
        environment = {
            'HOME': str(home), 'USER': username, 'LOGNAME': username,
            'XDG_RUNTIME_DIR': str(runtime), 'TMPDIR': str(runtime),
            'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'LC_ALL': 'C',
        }
        log(f'starting uid={account.pw_uid} with private runtime {runtime}')
        stopped = False
        status = supervise(['/bin/sh', str(helper), *installer_args], account=account,
                           home=home, environment=environment, timeout=timeout)
        stopped = True
        log(f'installer finished with status={status}')
        return status
    finally:
        try:
            if runtime is not None:
                if stopped:
                    entry = os.stat(runtime.name, dir_fd=parent_fd, follow_symlinks=False)
                    if not stat.S_ISDIR(entry.st_mode) or (entry.st_dev, entry.st_ino) != runtime_identity:
                        raise RuntimeError('installer runtime identity changed; refusing cleanup')
                    shutil.rmtree(runtime.name, dir_fd=parent_fd)
                else:
                    log(f'cleanup could not establish stopped processes; retaining {runtime}')
        finally:
            # Never unlink the persistent account lock: that permits split locks.
            if lock_fd is not None:
                os.close(lock_fd)
            os.close(parent_fd)


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        log(f'fatal: {error}')
        sys.exit(1)
