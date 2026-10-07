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
    # Freeze each owned parent BEFORE enumerating its children. Taking one
    # snapshot first allowed fatal-hold shells to fork a sleep between the
    # snapshot and SIGSTOP, leaving open pipes and hanging test teardown.
    stopped = []
    def freeze(pid):
        try:
            os.kill(pid, signal.SIGSTOP)
        except ProcessLookupError:
            return
        stopped.append(pid)
        child_file = Path(f'/proc/{pid}/task/{pid}/children')
        try:
            children = [int(value) for value in child_file.read_text().split()]
        except OSError:
            children = []
            for path in Path('/proc').glob('[0-9]*/status'):
                try:
                    parent = int(next(line.split()[1] for line in path.read_text().splitlines()
                                      if line.startswith('PPid:')))
                    if parent == pid:
                        children.append(int(path.parent.name))
                except (OSError, ValueError, StopIteration):
                    pass
        for child in children:
            freeze(child)
    freeze(process.pid)
    for pid in reversed(stopped):
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
