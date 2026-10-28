"""Bounded foreground I/O and discovery for the managed desktop wrappers.

Interactive waits have no timer. Noninteractive deadlines include input,
streaming and the final wait. Commands that outlive their foreground client
must remain owned by the existing systemd service, not this process group.
"""
from __future__ import annotations

import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time

MAX_OUTPUT = 1024 * 1024
MAX_SCAN_ENTRIES = 8000
MAX_SCAN_DIRECTORIES = 256
ENVIRONMENT = frozenset('''HOME USER LOGNAME LANG LC_ALL TZ TERM COLORTERM
XDG_RUNTIME_DIR XDG_SESSION_TYPE XDG_CURRENT_DESKTOP XDG_SESSION_DESKTOP
XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME WAYLAND_DISPLAY
DBUS_SESSION_BUS_ADDRESS LABWC_SESSION_OWNER PIPEWIRE_REMOTE GDK_BACKEND
QT_QPA_PLATFORM NO_AT_BRIDGE GTK_A11Y LABWC_MENU_ACTION_WAIT LABWC_MENU_INPUT_MODE
LABWC_FUZZEL_MANAGED_ICONS LABWC_FUZZEL_ROOT_MENU LABWC_FUZZEL_LOG_SCOPE
LABWC_FUZZEL_PALETTE'''.split())


class HelperError(OSError):
    """Fixed messages only; never include captured bytes or command operands."""


def environment(values=None):
    source = os.environ if values is None else values
    result = {key: value for key, value in source.items() if key in ENVIRONMENT
              and isinstance(value, str) and '\0' not in value}
    result.update(PATH='/usr/local/bin:/usr/bin:/bin', LC_ALL='C.UTF-8')
    return result


def runtime_root():
    uid = os.getuid()
    root = Path(os.environ.get('XDG_RUNTIME_DIR', ''))
    if (uid == 0 or os.geteuid() != uid or root != Path('/run/user') / str(uid)):
        raise HelperError('a non-root desktop runtime directory is required')
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise HelperError('the desktop runtime directory has unsafe metadata')
    return root


def _cancel(child):
    """The unreaped session leader pins the numeric process-group identity."""
    deadline = time.monotonic() + 2
    for signum, budget in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 1.5)):
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass
        if signum == signal.SIGTERM:
            # Do not reap the leader before signalling remaining group members.
            end = min(deadline, time.monotonic() + budget)
            while time.monotonic() < end:
                if os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT):
                    break
                time.sleep(0.02)
        else:
            try:
                child.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise HelperError('foreground helper termination is outcome-unknown; retain owned state') from None


def run(argv, *, input_text=None, capture=False, timeout=30, env=None,
        output_limit=MAX_OUTPUT, interactive=False):
    if (not isinstance(argv, (list, tuple)) or not argv or not isinstance(argv[0], str)
            or not argv[0].startswith('/') or any(not isinstance(arg, str) or '\0' in arg for arg in argv)
            or type(output_limit) is not int or not 1 <= output_limit <= 16 * MAX_OUTPUT
            or (timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0))):
        raise HelperError('invalid foreground helper request')
    payload = None if input_text is None else input_text.encode('utf-8')
    if payload is not None and len(payload) > MAX_OUTPUT:
        raise HelperError('foreground helper input exceeds its byte limit')
    deadline = None if timeout is None else time.monotonic() + timeout
    child = subprocess.Popen(argv, env=environment(env),
        stdin=subprocess.PIPE if payload is not None else None if interactive else subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else None if interactive else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else None if interactive else subprocess.DEVNULL,
        close_fds=True, start_new_session=True)
    streams = [stream for stream in (child.stdin, child.stdout, child.stderr) if stream is not None]
    output, diagnostics = bytearray(), bytearray()
    reaped = False
    try:
        with selectors.DefaultSelector() as selector:
            for stream, target in ((child.stdout, output), (child.stderr, diagnostics)):
                if stream is not None:
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, target)
            offset = 0
            if child.stdin is not None:
                os.set_blocking(child.stdin.fileno(), False)
                if payload:
                    selector.register(child.stdin, selectors.EVENT_WRITE)
                else:
                    child.stdin.close()
            exited_at = None
            while True:
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    raise subprocess.TimeoutExpired(['desktop-helper'], timeout)
                exited = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
                if exited:
                    exited_at = now if exited_at is None else exited_at
                    if not selector.get_map():
                        break
                    if now - exited_at >= 1:
                        raise HelperError('foreground helper exited with open channels')
                wait = min(0.1, max(0.001, deadline - now)) if deadline is not None else 0.1
                if not selector.get_map():
                    time.sleep(wait)
                    continue
                for key, _ in selector.select(wait):
                    if key.fileobj is child.stdin:
                        try:
                            offset += os.write(key.fd, payload[offset:offset + 4096])
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            offset = len(payload)
                        if offset == len(payload):
                            selector.unregister(child.stdin)
                            child.stdin.close()
                    else:
                        try:
                            block = os.read(key.fd, min(16384, output_limit + 1))
                        except BlockingIOError:
                            continue
                        if not block:
                            selector.unregister(key.fileobj)
                        else:
                            key.data.extend(block)
                            if len(output) + len(diagnostics) > output_limit:
                                raise HelperError('foreground helper output exceeds its byte limit')
        status = child.wait(timeout=0.1)
        reaped = True
        return subprocess.CompletedProcess(argv, status,
            output.decode('utf-8', 'replace') if capture else None,
            diagnostics.decode('utf-8', 'replace') if capture else None)
    finally:
        try:
            if not reaped:
                _cancel(child)
        finally:
            for stream in streams:
                stream.close()


def candidates(roots, *, files=True, suffixes=None, max_depth=3, limit=400, max_bytes=None):
    """One aggregate traversal budget, including nonmatching entries/empty dirs."""
    found, visited = set(), set()
    scanned = directories = 0
    deadline = time.monotonic() + 3
    for root in roots:
        try:
            info = root.lstat()
            if not stat.S_ISDIR(info.st_mode):
                continue
        except OSError:
            continue
        stack = [(root, 0)]
        while stack and len(found) < limit:
            if scanned >= MAX_SCAN_ENTRIES or directories >= MAX_SCAN_DIRECTORIES or time.monotonic() >= deadline:
                return sorted(found)
            directory, depth = stack.pop()
            try:
                metadata = directory.lstat()
                identity = (metadata.st_dev, metadata.st_ino)
                if not stat.S_ISDIR(metadata.st_mode) or metadata.st_dev != info.st_dev or identity in visited:
                    continue
                visited.add(identity)
                directories += 1
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        scanned += 1
                        if scanned > MAX_SCAN_ENTRIES or time.monotonic() >= deadline:
                            return sorted(found)
                        if any(ord(c) < 32 or ord(c) == 127 for c in entry.path) or len(entry.path.encode()) > 4096:
                            continue
                        try:
                            child = entry.stat(follow_symlinks=False)
                            is_directory = stat.S_ISDIR(child.st_mode)
                            if (is_directory and depth < max_depth and child.st_dev == info.st_dev
                                    and len(stack) + directories < MAX_SCAN_DIRECTORIES):
                                stack.append((Path(entry.path), depth + 1))
                            if not files and is_directory:
                                found.add(entry.path)
                            elif files and stat.S_ISREG(child.st_mode):
                                if (suffixes is None or Path(entry.name).suffix.lower() in suffixes) and (
                                        max_bytes is None or 0 < child.st_size <= max_bytes):
                                    found.add(entry.path)
                            if len(found) >= limit:
                                break
                        except OSError:
                            continue
            except OSError:
                continue
    return sorted(found)
