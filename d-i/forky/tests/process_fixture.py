"""Test-only process cleanup; never changes installer behavior."""
from pathlib import Path
import os
import signal
import time


def descendants(root):
    children = {}
    for path in Path('/proc').glob('[0-9]*/status'):
        try:
            parent = int(next(line.split()[1] for line in path.read_text().splitlines() if line.startswith('PPid:')))
            children.setdefault(parent, []).append(int(path.parent.name))
        except (OSError, ValueError, StopIteration):
            pass
    result = []
    def visit(pid):
        result.append(pid)
        for child in children.get(pid, []):
            visit(child)
    visit(root)
    return result


def stop_test_tree(process):
    # Freeze only the process we spawned and its descendants before killing.
    # This also cleans terminal waits and separate setsid supervisor sessions.
    pids = descendants(process.pid)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGSTOP)
        except ProcessLookupError:
            pass
    for pid in reversed(pids):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.communicate(timeout=5)


def wait_file(path, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return True
        time.sleep(0.025)
    return False
