"""Bounded ownership of a disposable validator's direct child and session.

Callers must establish the disposable-image boundary before invoking this API.
This helper does not provision isolation or own deliberately detached services.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess
import time


class CleanupUnknown(RuntimeError):
    """The caller must stop subsequent stages and retain its evidence."""


@dataclass(frozen=True)
class StageResult:
    returncode: int
    timed_out: bool
    cancelled: int | None


def run_stage(command: list[str], *, cwd, env: dict[str, str], timeout: float,
              stdout=None, stderr=None) -> StageResult:
    if timeout <= 0 or not command or not command[0].startswith('/'):
        raise ValueError('a positive deadline and an absolute executable are required')
    if stdout == subprocess.PIPE or stderr == subprocess.PIPE:
        raise ValueError('stage output must use owned log files, never undrained pipes')
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               stdout=stdout, stderr=stderr, start_new_session=True)
    cancelled = None
    handlers = {}
    timed_out = False

    def interrupted(signum, _frame):
        nonlocal cancelled
        cancelled = cancelled or signum

    def held_child() -> bool:
        try:
            state = os.waitid(os.P_PID, process.pid,
                              os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError as exc:
            raise CleanupUnknown('validator child identity was lost; no group signal sent') from exc
        return state is not None

    def signal_group(signum):
        # WNOWAIT retains the leader, including a zombie leader, until all
        # escalation is complete. No numeric group signal follows reaping.
        held_child()
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    try:
        for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, interrupted)
        deadline = time.monotonic() + timeout
        while not held_child() and cancelled is None:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    finally:
        try:
            signal_group(signal.SIGTERM)
            # Even an exited leader may have surviving descendants. Keep the
            # identity pinned throughout the separate cleanup budget.
            grace = 5 if timed_out or cancelled else 0.2
            end = time.monotonic() + grace
            while time.monotonic() < end:
                time.sleep(min(0.05, max(0, end - time.monotonic())))
            signal_group(signal.SIGKILL)
            try:
                status = process.wait(timeout=2)
            except subprocess.TimeoutExpired as exc:
                raise CleanupUnknown('validator could not be reaped; evidence retained') from exc
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
    if cancelled is not None:
        return StageResult(128 + cancelled, timed_out, cancelled)
    return StageResult(124 if timed_out else status, timed_out, None)
