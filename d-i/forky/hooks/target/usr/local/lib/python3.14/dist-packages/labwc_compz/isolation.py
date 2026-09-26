"""Transactional user-service lifecycle with mandatory AppArmor and namespaces."""
from __future__ import annotations

import json
import fcntl
import sys
import os
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

from . import CompzError
from .formats import ENV, WORKER
from .safeio import audit, display, publish
from .volumes import resolve


class Cancelled(CompzError):
    """The complete service cgroup was stopped before cleanup."""


def user_environment() -> dict[str, str]:
    uid = os.geteuid()
    if uid == 0:
        raise CompzError('Run compz as your desktop account, never through sudo.')
    runtime = Path(f'/run/user/{uid}')
    value = runtime.lstat()
    if (not stat.S_ISDIR(value.st_mode) or value.st_uid != uid or value.st_mode & 0o077 or
            not stat.S_ISSOCK((runtime / 'bus').lstat().st_mode)):
        raise CompzError('A private, active systemd user session is required.')
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'LC_ALL': 'C.UTF-8',
            'XDG_RUNTIME_DIR': str(runtime), 'DBUS_SESSION_BUS_ADDRESS': f'unix:path={runtime}/bus'}


def bwrap_command(inputs: list[tuple[str, int]], work_fd: int, plan_fd: int, plan: dict) -> list[str]:
    # --bind-fd validates the mounted inode against the already-open source.
    # Only selected objects are exported, never the caller's entire home/cwd.
    command = ['--die-with-parent', '--new-session', '--unshare-all', '--unshare-user',
               '--disable-userns', '--assert-userns-disabled', '--cap-drop', 'ALL',
               '--clearenv', '--ro-bind', '/usr', '/usr']
    for alias in ('bin', 'sbin', 'lib', 'lib64'):
        path = Path('/') / alias
        if path.is_symlink():
            command += ['--symlink', os.readlink(path), '/' + alias]
        elif path.is_dir():
            command += ['--ro-bind', str(path), str(path)]
    command += ['--dir', '/etc']
    for path in ('/etc/ld.so.cache', '/etc/nsswitch.conf', '/etc/passwd', '/etc/group'):
        if Path(path).is_file():
            command += ['--ro-bind', path, path]
    command += ['--proc', '/proc', '--dev', '/dev', '--size',
                str(min(plan['max_bytes'], plan['memory_mib'] * 1024**2)), '--tmpfs', '/tmp',
                '--dir', '/input']
    for name, fd in inputs:
        command += ['--ro-bind-fd', str(fd), '/input/' + name]
    command += ['--bind-fd', str(work_fd), '/work', '--ro-bind-fd', str(plan_fd), '/plan',
                '--chdir', '/work']
    for name, value in ENV.items():
        command += ['--setenv', name, value]
    command += ['--', '/usr/bin/python3', '-I', '-B', WORKER]
    return command


def sandbox_main() -> int:
    """Trusted service launcher; argument data travels through a sealed memfd."""
    from .worker import read_plan
    descriptors = []
    try:
        if (os.geteuid() == 0 or len(sys.argv) != 4 or
                Path('/proc/self/attr/current').read_text().strip() not in
                ('compz-worker (enforce)', 'compz-worker (complain)')):
            raise CompzError('Sandbox launcher requires its managed account and AppArmor profile.')
        current, work, plan_directory = map(Path, sys.argv[1:])
        if any(not path.is_absolute() for path in (current, work, plan_directory)):
            raise CompzError('Sandbox paths must be absolute.')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        cwd_fd = os.open(current, flags)
        descriptors.append(cwd_fd)
        private = []
        for path in (work, plan_directory):
            fd = os.open(path, flags)
            descriptors.append(fd)
            value = os.fstat(fd)
            if value.st_uid != os.geteuid() or value.st_mode & 0o077:
                raise CompzError('Unsafe private operation directory.')
            private.append(fd)
        plan = read_plan(plan_directory / 'operation.json')
        selected = plan['selected']
        if plan['action'] != 'compress':
            selected = [path.name for path in resolve(current / selected[0]).members]
        if len(selected) > 10000:
            raise CompzError('Select a parent directory instead of more than 10000 top-level inputs.')
        inputs = []
        for name in selected:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=cwd_fd)
            descriptors.append(fd)
            value = os.fstat(fd)
            if not (stat.S_ISDIR(value.st_mode) or stat.S_ISREG(value.st_mode)):
                raise CompzError('Inputs must be regular files or directories, never links or devices.')
            if plan['action'] != 'compress' and (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1):
                raise CompzError('Archive volumes must be non-linked regular files.')
            inputs.append((name, fd))
        command = bwrap_command(inputs, *private, plan)
        args_fd = os.memfd_create('compz-args', os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
        descriptors.append(args_fd)
        data = b''.join(os.fsencode(arg) + b'\0' for arg in command)
        if len(data) > 8 * 1024**2:
            raise CompzError('Sandbox argument data is too large.')
        with os.fdopen(os.dup(args_fd), 'wb') as output:
            output.write(data)
        os.lseek(args_fd, 0, os.SEEK_SET)
        fcntl.fcntl(args_fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
                    fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
        # Never export a host cwd descriptor. Bubblewrap consumes/closes bind
        # descriptors; the worker also closes all fd > 2 before parsing input.
        for fd in descriptors:
            if fd != cwd_fd:
                os.set_inheritable(fd, True)
        os.execve('/usr/bin/bwrap', ['/usr/bin/bwrap', '--args', str(args_fd)], ENV)
    except (CompzError, OSError, ValueError, TypeError, KeyError) as exc:
        print('compz: ' + display(str(exc)), file=sys.stderr)
        return 1
    finally:
        for fd in descriptors:
            os.close(fd)


def service_command(unit: str, current: Path, work: Path, plan_directory: Path, plan: dict) -> list[str]:
    properties = {
        'ExitType': 'cgroup', 'KillMode': 'control-group',
        'TimeoutStopSec': '10s', 'SendSIGKILL': 'yes', 'OOMPolicy': 'kill',
        'NoNewPrivileges': 'yes', 'RestrictSUIDSGID': 'yes', 'LimitCORE': '0',
        'UMask': '0077', 'TasksMax': '256', 'MemoryMax': f"{plan['memory_mib']}M",
        'MemorySwapMax': '0', 'RuntimeMaxSec': f"{plan['hours']}h",
        'LimitFSIZE': str(plan['max_bytes']), 'LimitNOFILE': '32768',
    }
    command = ['/usr/bin/systemd-run', '--user', '--quiet', '--wait', '--pipe', '--collect',
               '--expand-environment=no', '--unit=' + unit, '--service-type=exec']
    command += ['--property=' + name + '=' + value for name, value in properties.items()]
    # AppArmorProfile= is system-service-only, including systemd 261. Use the
    # packaged unprivileged on-exec transition; aa-exec fails if the profile is
    # unavailable, and the launcher verifies its actual label before mounting.
    return command + ['--', '/usr/bin/aa-exec', '-p', 'compz-worker', '--',
                      '/usr/bin/python3', '-I', '-B', '/usr/local/libexec/compz-sandbox',
                      str(current), str(work), str(plan_directory)]


def occupancy(root: Path, byte_limit: int, file_limit: int) -> None:
    # Descriptor-relative traversal cannot follow a directory replaced by a
    # symlink between enumeration and open. Codec renames/unlinks are expected.
    count = total = 0
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    def walk(parent: int, depth: int) -> None:
        nonlocal count, total
        if depth > 128:
            raise CompzError('Workspace directory depth limit reached.')
        with os.scandir(parent) as entries:
            for entry in entries:
                try:
                    value = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                count += 1
                if count > file_limit:
                    raise CompzError('Workspace file-count limit reached.')
                if stat.S_ISREG(value.st_mode):
                    total += value.st_size
                    if total > byte_limit:
                        raise CompzError('Workspace byte limit reached.')
                elif stat.S_ISDIR(value.st_mode):
                    try:
                        child = os.open(entry.name, flags, dir_fd=parent)
                    except (FileNotFoundError, NotADirectoryError):
                        continue
                    try:
                        walk(child, depth + 1)
                    finally:
                        os.close(child)
    descriptor = os.open(root, flags)
    try:
        walk(descriptor, 0)
    finally:
        os.close(descriptor)
    if shutil.disk_usage(root).free < 256 * 1024**2:
        raise CompzError('Workspace stopped to retain 256 MiB of free disk space.')


def stop(unit: str, environment: dict[str, str]) -> None:
    subprocess.run(['/usr/bin/systemctl', '--user', 'stop', unit], env=environment,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                   timeout=25, check=False)
    # Query even after a successful stop; never remove storage while a codec is
    # still using it. Collected units legitimately return a nonzero show status.
    state = subprocess.run(['/usr/bin/systemctl', '--user', 'show', unit, '--property=LoadState',
                            '--property=ActiveState', '--property=ControlGroup'], env=environment,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=10, check=False)
    values = dict(line.split('=', 1) for line in state.stdout.splitlines() if '=' in line)
    if values.get('LoadState') == 'not-found' and values.get('ActiveState') == 'inactive':
        return
    if (state.returncode or values.get('LoadState') != 'loaded' or
            values.get('ActiveState') not in ('inactive', 'failed') or 'ControlGroup' not in values):
        raise CompzError('Cannot confirm the archive service stopped; its private workspace was retained.')
    group = values['ControlGroup']
    if group:
        if not group.startswith('/') or any(part in ('.', '..') for part in group.split('/')):
            raise CompzError('Invalid archive service cgroup path; workspace retained.')
        try:
            events = (Path('/sys/fs/cgroup') / group.lstrip('/') / 'cgroup.events').read_text()
        except FileNotFoundError:
            return
        if 'populated 0' not in events.splitlines():
            raise CompzError('Archive service cgroup is still populated; workspace retained.')


def execute(current: Path, plan: dict, passphrase: str = '') -> Path | None:
    environment = user_environment()
    if not current.is_absolute() or current.is_symlink() or not current.is_dir():
        raise CompzError('Current directory is unavailable or unsafe.')
    # Refuse before starting when the user manager is unavailable. The service
    # enters AppArmor using aa-exec; there is no unconfined fallback.
    check = subprocess.run(['/usr/bin/systemctl', '--user', 'show-environment'], env=environment,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10, check=False)
    if check.returncode:
        raise CompzError('Cannot reach the systemd user manager; no unconfined fallback is available.')
    output = current / plan['output']
    if plan['action'] in ('compress', 'extract') and (output.exists() or output.is_symlink()):
        raise CompzError('Destination already exists; select another name.')
    if len(passphrase.encode('utf-8')) > 4096 or any(c in passphrase for c in '\r\n\0'):
        raise CompzError('Invalid passphrase length or embedded control delimiter.')
    unit = 'compz-' + uuid.uuid4().hex + '.service'
    workspace = Path(tempfile.mkdtemp(prefix='.compz-', dir=current))
    plan_directory = None
    work = workspace / 'work'
    log_path = workspace / 'operation.log'
    process = None
    stopped = False
    keep = False
    handlers = {}
    def interrupt(signum, frame):
        raise Cancelled('Operation cancelled; no partial output published.')
    try:
        work.mkdir(mode=0o700)
        plan_directory = Path(tempfile.mkdtemp(prefix='compz-plan-', dir=environment['XDG_RUNTIME_DIR']))
        (plan_directory / 'operation.json').write_text(json.dumps(plan, ensure_ascii=True), encoding='ascii')
        (plan_directory / 'operation.json').chmod(0o400)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, interrupt)
        with log_path.open('xb') as log:
            process = subprocess.Popen(service_command(unit, current, work, plan_directory, plan),
                                       env=environment, stdin=subprocess.PIPE, stdout=log, stderr=log,
                                       start_new_session=True)
            try:
                process.stdin.write(json.dumps({'passphrase': passphrase}, ensure_ascii=True).encode('ascii') + b'\n')
                process.stdin.flush()
            except BrokenPipeError:
                pass
            last_report = time.monotonic()
            while process.poll() is None:
                occupancy(work, plan['max_bytes'], plan['max_files'] + 1024)
                if log_path.stat().st_size > 16 * 1024**2:
                    raise CompzError('Codec diagnostic output exceeded 16 MiB.')
                if time.monotonic() - last_report >= 15:
                    print('Archive operation is running; Ctrl+C cancels the entire job.', flush=True)
                    last_report = time.monotonic()
                time.sleep(0.25)
        # --wait with ExitType=cgroup returns only when ALL service processes
        # have exited, including codec threads and any transient GPG agent.
        stopped = process.returncode == 0
        if process.returncode or not (work / 'complete').is_file():
            with log_path.open('rb') as log:
                log.seek(max(0, log_path.stat().st_size - 8192))
                message = display(log.read().decode('utf-8', 'replace'))
            raise CompzError('Archive service failed. ' + message)
        occupancy(work, plan['max_bytes'], plan['max_files'] + 1024)
        if plan['action'] == 'list':
            with (work / 'listing.jsonl').open(encoding='utf-8') as listing:
                for line in listing:
                    item = json.loads(line)
                    print(f"{item['bytes']:>14}  {display(item['path'])}")
            return None
        if plan['action'] == 'test':
            return None
        staged = work / 'published'
        if plan['action'] == 'extract':
            audit(staged, plan['max_bytes'], plan['max_files'], sanitize=True)
        else:
            value = staged.lstat()
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or not 0 < value.st_size <= plan['max_bytes']:
                raise CompzError('Compressor result is not a bounded regular file.')
        publish(staged, output)
        return output
    finally:
        # Ignore repeated cancellation while reaping. A user interrupt must not
        # unlink paths that a still-running codec can subsequently recreate.
        for sig in handlers:
            signal.signal(sig, signal.SIG_IGN)
        try:
            if process is not None and not stopped:
                try:
                    stop(unit, environment)
                    stopped = True
                except (CompzError, OSError, subprocess.SubprocessError):
                    keep = True
                    print('Private workspace retained: ' + display(str(workspace)), file=__import__('sys').stderr)
                    raise
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            if not keep:
                shutil.rmtree(workspace)
                if plan_directory is not None:
                    shutil.rmtree(plan_directory)
        finally:
            if process is not None and process.stdin is not None:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
