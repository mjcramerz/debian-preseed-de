"""Foreground commands with bounded lifetime and whole-cgroup cancellation."""
from __future__ import annotations
import os
from pathlib import Path
import pwd
import re
import signal
import subprocess
import uuid


class CommandError(RuntimeError):
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


def checked(argv: list[str], *, cwd: Path | None = None, env=None,
            capture: bool = False, timeout: int = 300, input: str | None = None) -> str:
    if not argv or not argv[0].startswith('/'):
        raise ValueError('an absolute executable is required')
    result = subprocess.run(argv, cwd=cwd, env=env or environment(desktop=True),
                            text=True, input=input, capture_output=capture,
                            timeout=timeout, check=False)
    if result.returncode:
        # Do not copy arbitrary subprocess bytes (or secrets) into menu prompts.
        raise CommandError(f'{Path(argv[0]).name} failed with status {result.returncode}')
    return result.stdout if capture else ''


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
                child.wait()
