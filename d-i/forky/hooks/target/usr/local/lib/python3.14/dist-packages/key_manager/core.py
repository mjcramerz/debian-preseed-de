"""Private storage, bounded commands and a small terminal menu interface."""
from __future__ import annotations

import contextlib
import getpass
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable

from managed_workflows.fs import Tree, open_directory

LIMIT = 8 * 1024 * 1024


def text(value: str, *, limit: int = 240) -> str:
    if not value or len(value) > limit or any(not c.isprintable() for c in value):
        raise ValueError('a nonempty printable value is required')
    return value


def name(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', value):
        raise ValueError('use a name of 1–80 letters, numbers, dots, underscores or hyphens')
    return value


def fingerprint(value: str) -> str:
    value = value.upper()
    if not re.fullmatch(r'(?:[0-9A-F]{40}|[0-9A-F]{64})', value):
        raise ValueError('a full GPG fingerprint is required')
    return value


def dns(value: str, *, wildcard: bool = False) -> str:
    value = value.lower()
    base = value[2:] if wildcard and value.startswith('*.') else value
    if len(value) > 253 or not all(re.fullmatch(
            r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in base.split('.')):
        raise ValueError('invalid DNS name; use ASCII or IDNA labels')
    return value


def number(value: str, low: int, high: int) -> int:
    if not re.fullmatch(r'[0-9]{1,8}', value) or not low <= int(value) <= high:
        raise ValueError(f'enter an integer between {low} and {high}')
    return int(value)


def prompt(label: str, default: str = '') -> str:
    value = input(label + (f' [{default}]' if default else '') + ': ').strip()
    return text(value or default, limit=4096)


def password(label: str = 'Export password') -> bytes:
    value = getpass.getpass(label + ' (at least 12 characters): ')
    if len(value) < 12 or len(value) > 1024 or any(not c.isprintable() for c in value):
        raise ValueError('use a printable password of 12–1024 characters')
    if value != getpass.getpass('Confirm ' + label.lower() + ': '):
        raise ValueError('passwords do not match')
    return value.encode('utf-8') + b'\n'


def confirm(label: str) -> bool:
    print('\n' + label)
    return choose('Confirm', ['Cancel', 'Proceed']) == 'Proceed'


def display(value: str) -> None:
    # Key UIDs, certificate subjects and external output cannot inject terminal escapes.
    print(''.join(c if c.isprintable() or c == '\n' else '?' for c in value))


def choose(label: str, options: list[str]) -> str | None:
    if not options:
        print('No entries available.')
        return None
    # Match the existing gitbuild terminal selection interface and packaged fzf.
    output = run(['/usr/bin/fzf', '--no-multi', '--no-sort', '--exact', '--height=80%',
                  '--layout=reverse', '--border', '--prompt=' + label + ' > ',
                  '--header=Arrows: navigate  Enter: select  Esc: back'],
                 capture=True, interactive=True, terminal_output=True,
                 data=('\n'.join(options) + '\n').encode(), allowed_status=(0, 1, 130))
    selected = output.decode('utf-8').rstrip('\n')
    if not selected:
        return None
    if selected not in options:
        raise ValueError('menu returned an unlisted selection')
    return selected


def menu(label: str, actions: dict[str, Callable[[], object]]) -> None:
    while (selected := choose(label, list(actions))) is not None:
        try:
            actions[selected]()
        except (OSError, ValueError, RuntimeError) as error:
            display('Operation failed: ' + str(error))


def environment() -> dict[str, str]:
    account = pwd.getpwuid(os.geteuid())
    env = {'PATH': '/usr/bin:/bin', 'HOME': account.pw_dir, 'USER': account.pw_name,
           'LOGNAME': account.pw_name, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
           'QT_QPA_PLATFORM': 'wayland'}
    for key in ('TERM', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS'):
        value = os.environ.get(key)
        if value and len(value) <= 1024 and all(c.isprintable() for c in value):
            env[key] = value
    if os.isatty(0):
        env['GPG_TTY'] = os.ttyname(0)
    runtime = Path('/run/user') / str(os.geteuid())
    try:
        fd = open_directory(runtime)
        try:
            info = os.fstat(fd)
            if info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700:
                env['XDG_RUNTIME_DIR'] = str(runtime)
                sock = os.stat('openssh_agent', dir_fd=fd, follow_symlinks=False)
                if (stat.S_ISSOCK(sock.st_mode) and sock.st_uid == os.geteuid()
                        and stat.S_IMODE(sock.st_mode) == 0o600):
                    env['SSH_AUTH_SOCK'] = str(runtime / 'openssh_agent')
        finally:
            os.close(fd)
    except FileNotFoundError:
        pass
    return env


def run(argv: list[str], *, capture: bool = False, timeout: int = 300,
        data: bytes | None = None, env: dict[str, str] | None = None,
        interactive: bool = False, on_cancel: Callable[[], None] | None = None,
        allowed_status: tuple[int, ...] = (0,), terminal_output: bool = False) -> bytes:
    """No shell; bounded output/time, terminal handoff and group cancellation.

    Secrets are passed on stdin, never argv or environment. Native interactive
    tools retain their controlling terminal for ssh-keygen and pinentry prompts.
    """
    if not argv or not argv[0].startswith('/') or any('\0' in v for v in argv):
        raise ValueError('an absolute command and NUL-free arguments are required')
    if data is not None and len(data) > LIMIT:
        raise ValueError('command input is too large')
    # Input is an anonymous descriptor: no pipe deadlock and no named secret file.
    with contextlib.ExitStack() as stack:
        source = None
        if data is not None:
            fd = os.memfd_create('key-manager-input', os.MFD_CLOEXEC)
            stack.callback(os.close, fd)
            with os.fdopen(os.dup(fd), 'wb') as stream:
                stream.write(data)
            os.lseek(fd, 0, os.SEEK_SET)
            source = fd
        terminal = None
        previous_group = None
        old_ttou = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        child = None
        try:
            if (not capture or interactive) and os.isatty(0):
                terminal = 0
                previous_group = os.tcgetpgrp(terminal)
            child = subprocess.Popen(argv, env=environment() if env is None else env,
                                     stdin=source, stdout=subprocess.PIPE if capture else None,
                                     stderr=subprocess.DEVNULL if capture and not terminal_output else None,
                                     process_group=0, umask=0o077)
            if terminal is not None:
                os.tcsetpgrp(terminal, child.pid)
                # A native tool may have attempted /dev/tty before the handoff.
                os.killpg(child.pid, signal.SIGCONT)
            deadline = time.monotonic() + timeout
            output = bytearray()
            if capture:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    while selector.get_map():
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f'{Path(argv[0]).name} timed out')
                        for key, _ in selector.select(min(0.2, max(0, deadline - time.monotonic()))):
                            chunk = os.read(key.fd, 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                            else:
                                output.extend(chunk)
                                if len(output) > LIMIT:
                                    raise RuntimeError('command output exceeds the limit')
            try:
                status = child.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(f'{Path(argv[0]).name} timed out') from error
            if status not in allowed_status:
                raise RuntimeError(f'{Path(argv[0]).name} failed (status {status})')
            return bytes(output)
        except BaseException as failure:
            if on_cancel is not None:
                try:
                    on_cancel()
                except (OSError, ValueError, RuntimeError) as cleanup_error:
                    failure.add_note('privileged job cancellation failed: ' + str(cleanup_error))
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            raise
        finally:
            if terminal is not None and previous_group is not None:
                os.tcsetpgrp(terminal, previous_group)
            signal.signal(signal.SIGTTOU, old_ttou)
            if child is not None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError('command client did not exit after cancellation') from error
                if child.stdout is not None:
                    child.stdout.close()


def public_command(argv: list[str]) -> bytes:
    """Capture public data while retaining native passphrase terminal prompts."""
    return run(argv, capture=True, interactive=True)


def encrypt_pkcs8(private: Path, output: Path) -> None:
    """Encrypt an owned staged key; passphrases stay in an anonymous descriptor."""
    run(['/usr/bin/openssl', 'pkcs8', '-topk8', '-in', str(private), '-out', str(output),
         '-v2', 'aes-256-cbc', '-v2prf', 'hmacWithSHA256', '-iter', '200000',
         '-passout', 'stdin'], data=password('Private-key password'))


@contextlib.contextmanager
def input_file(path: Path, *, private: bool = False, limit: int = LIMIT,
               owners: tuple[int, ...] | None = None):
    """Direct regular inputs only, with no symlink in any path component."""
    if not path.is_absolute():
        raise ValueError('use an absolute input path')
    parent = open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
                or (private and (stat.S_IMODE(info.st_mode) != 0o600
                                 or info.st_uid not in (owners or (os.geteuid(),))))):
            raise ValueError('unsafe, non-regular or oversized input')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            yield stream
        after = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('input changed while being read')
    finally:
        os.close(fd)


def read_file(path: Path, *, private: bool = False, limit: int = LIMIT,
              owners: tuple[int, ...] | None = None) -> bytes:
    with input_file(path, private=private, limit=limit, owners=owners) as stream:
        value = stream.read(limit + 1)
        if len(value) > limit:
            raise ValueError('input exceeds the size limit')
        return value


def chunks(source, limit: int = 16 * 1024**3):
    remaining = limit
    while remaining:
        chunk = source.read(min(remaining, 1024 * 1024))
        if not chunk:
            return
        remaining -= len(chunk)
        yield chunk
    if source.read(1):
        raise ValueError('input grew beyond the size limit')


def copy_input(path: Path, destination: Path) -> None:
    """Stream user data into an owned stage; cryptographic material stays small."""
    with input_file(path, limit=16 * 1024**3) as source, destination.open('xb') as output:
        for chunk in chunks(source):
            output.write(chunk)


def publish_file(tree: Tree, relative: str, path: Path) -> None:
    with tree.parent(relative, create=True) as (parent, leaf):
        try:
            os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('destination already exists: ' + relative)
    with Tree(path.parent, private=True) as source:
        tree.copy(relative, source, path.name)


def protected_directory(path: Path) -> None:
    """Root operations cannot trust paths below other-account writable parents."""
    for parent in [path, *path.parents]:
        fd = open_directory(parent, readable=False)
        try:
            info = os.fstat(fd)
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('privileged path has unsafe ownership or permissions')
        finally:
            os.close(fd)


def private_file(tree: Tree, relative: str) -> bytes:
    # Tree first validates the relative path and every store directory.
    value = tree.read(relative)
    with tree.parent(relative) as (parent, leaf):
        info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('private key material must have mode 0600')
    return value


def inventory(tree: Tree, relative: str, suffix: str) -> list[str]:
    if relative:
        tree.mkdir(relative)
    anchor = relative + '/.anchor' if relative else '.anchor'
    with tree.parent(anchor) as (fd, _):
        result = []
        for item in os.listdir(fd):
            if not item.endswith(suffix):
                continue
            stem = item[:-len(suffix)] if suffix else item
            try:
                name(stem)
            except ValueError:
                continue
            info = os.stat(item, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and info.st_uid == tree.uid and info.st_nlink == 1:
                result.append(stem)
        return sorted(result)


@contextlib.contextmanager
def stage(tree: Tree):
    with tempfile.TemporaryDirectory(prefix='.key-manager-', dir=tree.root) as directory:
        yield Path(directory)


def publish(tree: Tree, values: dict[str, bytes]) -> None:
    """Refuse overwrites and roll back just the files this operation created."""
    for path in values:
        if tree.read(path, missing=True) is not None:
            raise ValueError('destination already exists: ' + path)
    written = []
    try:
        for path, value in values.items():
            tree.write(path, value)
            written.append(path)
    except BaseException:
        for path in reversed(written):
            tree.write(path, None)
        raise
