"""Foreground commands with bounded lifetime and whole-cgroup cancellation."""
from __future__ import annotations
from contextlib import ExitStack
import locale
import os
from pathlib import Path
import pwd
import re
import selectors
import signal
import subprocess
import time
import uuid

MAX_CAPTURE_BYTES = 64 * 1024 * 1024


class CommandError(RuntimeError):
    pass


class OutputLimitError(CommandError):
    pass


def environment(*, desktop: bool = False) -> dict[str, str]:
    account = pwd.getpwuid(os.getuid())
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': account.pw_dir,
           'USER': account.pw_name, 'LOGNAME': account.pw_name,
           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    for name in ('TERM', 'COLORTERM'):
        value = os.environ.get(name, '')
        if re.fullmatch(r'[A-Za-z0-9_.+-]{1,80}', value):
            env[name] = value
    if desktop:
        env.update(GDK_BACKEND='wayland', QT_QPA_PLATFORM='wayland')
        # Session authority is kept only in the UI/publisher, never the builder.
        for name in ('XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'WAYLAND_DISPLAY',
                     'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE', 'LABWC_MENU_BACKEND',
                     'LABWC_MENU_ACTION_WAIT'):
            if name in os.environ:
                env[name] = os.environ[name]
    return env


def _checked_capture(argv: list[str], *, cwd: Path | None, env: dict,
                     timeout: int, input: str | None,
                     max_output_bytes: int | None) -> str:
    """Capture non-interactive commands with one output budget and deadline.

    Keep the direct child unreaped while draining pipes so cancellation can
    safely signal its process group, including descendants retaining a pipe.
    Deliberately daemonizing commands belong in a supervised service instead.
    """
    output_limit = MAX_CAPTURE_BYTES if max_output_bytes is None else max_output_bytes
    if (isinstance(output_limit, bool) or not isinstance(output_limit, int)
            or not 1 <= output_limit <= MAX_CAPTURE_BYTES):
        raise ValueError('command output limit must be between 1 and MAX_CAPTURE_BYTES')
    encoding = locale.getpreferredencoding(False)
    with ExitStack() as stack:
        data = None
        if input is not None:
            if len(input) > MAX_CAPTURE_BYTES:
                raise CommandError('command input exceeds the limit')
            data = input.encode(encoding)
            if len(data) > MAX_CAPTURE_BYTES:
                raise CommandError('command input exceeds the limit')
        child = subprocess.Popen(argv, cwd=cwd, env=env,
                                 stdin=subprocess.PIPE if data is not None else None,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 process_group=0)
        stack.callback(child.stdout.close)
        stack.callback(child.stderr.close)
        if child.stdin is not None:
            stack.callback(child.stdin.close)
        try:
            deadline = time.monotonic() + timeout
            output = bytearray()
            captured = 0
            offset = 0
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                selector.register(child.stderr, selectors.EVENT_READ)
                if data:
                    os.set_blocking(child.stdin.fileno(), False)
                    selector.register(child.stdin, selectors.EVENT_WRITE)
                elif child.stdin is not None:
                    child.stdin.close()
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(argv, timeout)
                    for key, _ in selector.select(remaining):
                        if key.fileobj is child.stdin:
                            try:
                                count = os.write(key.fd, data[offset:offset + 65536])
                            except BlockingIOError:
                                continue
                            except BrokenPipeError:
                                selector.unregister(key.fileobj)
                                child.stdin.close()
                                continue
                            if count <= 0:
                                raise CommandError('command input made no progress')
                            offset += count
                            if offset == len(data):
                                selector.unregister(key.fileobj)
                                child.stdin.close()
                            continue
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        captured += len(chunk)
                        if captured > output_limit:
                            raise OutputLimitError('command output exceeds the limit')
                        if key.fileobj is child.stdout:
                            output.extend(chunk)
            status = child.wait(timeout=max(0.01, deadline - time.monotonic()))
            if status:
                raise CommandError(f'{Path(argv[0]).name} failed with status {status}')
            # Preserve subprocess.run(text=True)'s decoding and newline contract.
            return output.decode(encoding).replace('\r\n', '\n').replace('\r', '\n')
        except BaseException as failure:
            if child.returncode is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as error:
                    failure.add_note('command group cancellation failed: ' + str(error))
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    failure.add_note('command could not be reaped after cancellation')
            raise


def checked(argv: list[str], *, cwd: Path | None = None, env=None,
            capture: bool = False, timeout: int = 300, input: str | None = None,
            max_output_bytes: int | None = None) -> str:
    if not argv or not argv[0].startswith('/'):
        raise ValueError('an absolute executable is required')
    command_env = environment(desktop=True) if env is None else env
    if capture:
        return _checked_capture(argv, cwd=cwd, env=command_env, timeout=timeout,
                                input=input, max_output_bytes=max_output_bytes)
    result = subprocess.run(argv, cwd=cwd, env=command_env,
                            text=True, input=input,
                            timeout=timeout, check=False)
    if result.returncode:
        # Do not copy arbitrary subprocess bytes (or secrets) into menu prompts.
        raise CommandError(f'{Path(argv[0]).name} failed with status {result.returncode}')
    return ''


def supervised(argv: list[str], *, cwd: Path,
               prefix: str = 'gitbuild', timeout: int = 8 * 3600) -> None:
    """A unique transient service owns all descendants, even after UI death.

    RuntimeMaxSec is the final backstop; explicit HUP/TERM/INT stops the cgroup.
    No NoNewPrivileges/RestrictSUIDSGID here: sbuild's unshare backend needs the
    packaged newuidmap/newgidmap helpers. The confined worker drops session env.
    """
    unit = prefix + '-' + uuid.uuid4().hex + '.service'
    command = ['/usr/bin/systemd-run', '--user', '--quiet', '--wait', '--pipe',
               '--collect', '--expand-environment=no', '--service-type=exec', '--unit=' + unit,
               '--working-directory=' + str(cwd).replace('%', '%%'),
               '--property=KillMode=control-group', '--property=TimeoutStopSec=15s',
               '--property=RuntimeMaxSec=' + str(timeout), '--property=UMask=0077',
               '--property=LimitCORE=0', '--property=KeyringMode=private',
               '--property=TasksMax=4096', '--property=MemoryMax=75%',
               '--property=OOMPolicy=stop', '--property=MemoryOOMGroup=yes',
               '--property=SendSIGHUP=yes', '--', *argv]
    env = environment(desktop=True)
    previous = {}
    child = None
    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f'signal {signum}')
    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, interrupted)
        child = subprocess.Popen(command, env=env)
        try:
            status = child.wait(timeout=timeout + 60)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            subprocess.run(['/usr/bin/systemctl', '--user', 'stop', unit], env=env,
                           timeout=30, check=False)
            raise
        if status:
            raise CommandError(f'job failed (status {status}); see target/gitbuild job logs')
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired as exc:
                    raise CommandError(
                        f'job transport termination outcome unknown; retain job state and reconcile {unit}'
                    ) from exc
