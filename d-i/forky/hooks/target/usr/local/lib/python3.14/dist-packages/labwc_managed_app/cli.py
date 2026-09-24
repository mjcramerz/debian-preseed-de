"""Command-line orchestration for managed Labwc applications."""

from __future__ import annotations

import argparse
import io
import os
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

from .commands import build_argv, resolved_executable, validate_required_runtime_files
from .environment import (
    build_environment,
    ensure_discord_managed_settings,
    ensure_managed_runtime_state,
    ensure_obsidian_registry,
    load_managed_launch_policy,
    validate_acceleration_mode,
)
from .events import emit, event_context
from .profiles import APPS, WAYLAND_COMPAT_APPS
from .runtime import MANAGED_DEFAULTS_PATH, current_user_home, fail
from .sandbox import run_persistent_sandbox, run_pure_privacy
from .session import (
    redirect_bitwarden_to_session_unit,
    redirect_native_from_private_users,
    redirect_wayland_compat_to_session_unit,
)


# Keep shutdown inside the native service's existing 20-second stop budget.
_SPOTIFY_STOP_SECONDS = 15.0
_SPOTIFY_DRAIN_SECONDS = 0.2
_SPOTIFY_OUTPUT_LIMIT = 262144


def _run_spotify(command: list[str], environment: dict[str, str]) -> int:
    """Recognize the exact handoff without letting log backpressure block stop.

    Relay at most 256 KiB at a time. A full journal/pipe pauses reads from the
    child, not supervision or signal escalation. After the child exits, drain
    for a bounded interval: surviving descendants may retain its output pipe.
    """
    marker = b"Opening in existing browser session."
    pending = b""
    oversized = False
    handed_off = False
    stopping = False
    kill_sent = False
    stop_deadline = None
    drain_deadline = None
    previous_handlers = {}
    output = sys.stdout.buffer
    output_fd = None
    output_blocking = None
    queued = bytearray()
    child = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
    assert child.stdout is not None

    def forward(signum, _frame):
        nonlocal stopping, stop_deadline
        stopping = True
        if child.poll() is None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass
            if stop_deadline is None:
                stop_deadline = time.monotonic() + _SPOTIFY_STOP_SECONDS

    try:
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous_handlers[signum] = signal.signal(signum, forward)
        try:
            output_fd = output.fileno()
        except (AttributeError, io.UnsupportedOperation):
            # In-memory streams in the regression harness have no descriptor.
            # Installed launchers use the service's journal socket (fd 1).
            pass
        if output_fd is not None:
            output_blocking = os.get_blocking(output_fd)
            os.set_blocking(output_fd, False)
        os.set_blocking(child.stdout.fileno(), False)
        # poll also accepts regular-file stdout; epoll rejects that case.
        with selectors.PollSelector() as selector:
            reading = False
            writing = False
            eof = False
            while True:
                now = time.monotonic()
                status = child.poll()
                if status is not None and drain_deadline is None:
                    drain_deadline = now + _SPOTIFY_DRAIN_SECONDS
                if stop_deadline is not None and now >= stop_deadline and status is None and not kill_sent:
                    child.kill()
                    kill_sent = True
                # Never use a blocking BufferedWriter.flush() on the journal:
                # the child may have moved out of this service's cgroup.
                if queued:
                    if output_fd is None:
                        output.write(queued)
                        output.flush()
                        queued.clear()
                    else:
                        try:
                            written = os.write(output_fd, queued)
                        except BlockingIOError:
                            written = 0
                        if written:
                            del queued[:written]
                if drain_deadline is not None and now >= drain_deadline:
                    break
                if status is not None and eof and not queued:
                    break
                can_read = not eof and len(queued) < _SPOTIFY_OUTPUT_LIMIT
                if can_read and not reading:
                    selector.register(child.stdout, selectors.EVENT_READ, "child")
                    reading = True
                elif reading and not can_read:
                    selector.unregister(child.stdout)
                    reading = False
                can_write = bool(queued) and output_fd is not None
                if can_write and not writing:
                    selector.register(output_fd, selectors.EVENT_WRITE, "output")
                    writing = True
                elif writing and not can_write:
                    selector.unregister(output_fd)
                    writing = False
                for key, _ in selector.select(0.05):
                    if key.data == "output":
                        continue  # Flush the bounded queue at the loop head.
                    try:
                        chunk = os.read(key.fd, min(65536, _SPOTIFY_OUTPUT_LIMIT - len(queued)))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(child.stdout)
                        reading = False
                        eof = True
                        continue
                    queued.extend(chunk)
                    # A bounded complete-line match, never a substring in a
                    # URI or an arbitrarily long application message.
                    parts = chunk.split(b"\n")
                    for index, part in enumerate(parts):
                        if not oversized:
                            pending += part
                            if len(pending) > len(marker) + 1:
                                pending = b""
                                oversized = True
                        if index < len(parts) - 1:
                            handed_off |= not oversized and pending.rstrip(b"\r") == marker
                            pending, oversized = b"", False
        status = child.wait()
        handed_off |= not oversized and pending.rstrip(b"\r") == marker
        # Do not convert cancellation or an undelivered handoff log to success.
        if status == 1 and handed_off and not stopping and not queued:
            emit("existing-instance-handoff", status=0)
            return 0
        return 128 - status if status < 0 else status
    finally:
        # Output/setup errors must not orphan the tracked process.
        if child.poll() is None:
            child.kill()
            child.wait()
        child.stdout.close()
        try:
            if output_fd is not None and output_blocking is not None:
                os.set_blocking(output_fd, output_blocking)
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


def _argument_parser(*, wayland_compat: bool) -> argparse.ArgumentParser:
    if wayland_compat:
        program_name = "labwc-wayland-compat-app"
        application_choices = WAYLAND_COMPAT_APPS
        mode_choices = ("auto", "launch", "intel", "nvidia")
    else:
        program_name = "labwc-app"
        application_choices = tuple(sorted(set(APPS).difference(WAYLAND_COMPAT_APPS)))
        mode_choices = ("auto", "launch", "intel", "nvidia", "pure-privacy")

    parser = argparse.ArgumentParser(prog=program_name)
    parser.add_argument("mode", choices=mode_choices)
    parser.add_argument("application", choices=application_choices)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(
    *,
    wayland_compat: bool = False,
    argv: Sequence[str] | None = None,
) -> int:
    options = _argument_parser(wayland_compat=wayland_compat).parse_args(argv)
    entrypoint = "wayland-compat" if wayland_compat else "native"
    transport = "stderr" if options.application == "chatgpt" else "syslog"

    with event_context(
        application=options.application,
        entrypoint=entrypoint,
        requested_mode=options.mode,
        transport=transport,
    ):
        emit("launch-requested")
        if os.geteuid() == 0:
            fail(
                "managed desktop applications must run as the configured desktop "
                "user, never root"
            )

        if options.application == "bitwarden":
            emit("session-redirect", target="bitwarden")
            redirect_bitwarden_to_session_unit(options.mode, options.args)
        if wayland_compat:
            emit("session-redirect", target="wayland-compat")
            redirect_wayland_compat_to_session_unit(
                options.application,
                options.mode,
                options.args,
            )

        if not wayland_compat and options.application != "bitwarden":
            redirect_native_from_private_users(
                options.application, options.mode, options.args,
            )

        acceleration_availability, default_mode = load_managed_launch_policy(
            MANAGED_DEFAULTS_PATH
        )
        mode = default_mode if options.mode == "auto" else options.mode
        validate_acceleration_mode(mode, acceleration_availability)

        with event_context(mode=mode):
            app = APPS[options.application]
            executable = resolved_executable(options.application, mode)
            if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
                fail(
                    "application executable is missing or not executable: "
                    f"{executable}"
                )

            validate_required_runtime_files(options.application)
            if mode != "pure-privacy":
                home_dir = current_user_home()
                ensure_managed_runtime_state(options.application, home_dir)
                if options.application == "discord":
                    ensure_discord_managed_settings(home_dir)
                if options.application == "obsidian":
                    ensure_obsidian_registry(home_dir)

            if mode == "pure-privacy":
                emit("sandbox-starting", sandbox="ephemeral")
                result = run_pure_privacy(options.application, options.args)
                emit("completed", status=result)
                return result

            if wayland_compat:
                from .wayland_compat import run_wayland_compat_sandbox

                emit("sandbox-starting", sandbox="wayland-compat")
                result = run_wayland_compat_sandbox(
                    options.application,
                    mode,
                    options.args,
                )
                emit("completed", status=result)
                return result

            if app.get("persistent_sandbox", False):
                emit("sandbox-starting", sandbox="persistent")
                result = run_persistent_sandbox(
                    options.application,
                    mode,
                    options.args,
                )
                emit("completed", status=result)
                return result

            env = build_environment(options.application, mode)
            command = build_argv(options.application, mode, options.args)
            emit("executing")
            try:
                if options.application == "spotify":
                    return _run_spotify(command, env)
                os.execvpe(command[0], command, env)
            except OSError as exc:
                fail(
                    "application execution failed: "
                    f"{command[0]}: {exc.strerror or exc}"
                )
            emit("completed", status=0)
            return 0
