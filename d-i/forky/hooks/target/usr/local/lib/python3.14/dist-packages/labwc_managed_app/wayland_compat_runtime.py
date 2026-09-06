"""Cage and application supervisors, executed only inside Bubblewrap."""

from __future__ import annotations

import os
import re
import signal
import stat
import subprocess
import sys
import time
from typing import BinaryIO, NoReturn

from .runtime import (
    MANAGED_CAGE_COMPOSITOR_ENVIRONMENT,
    MANAGED_CAGE_ENVIRONMENT,
)

ALLOWED_APPLICATIONS = {
    "discord": "/opt/discord/Discord",
    "zoom": "/usr/bin/zoom",
}
ALLOWED_MODES = {"launch", "intel", "nvidia"}
SYSTEM_OWNER_ANCHOR = "/usr"
CAGE_BINARY = "/usr/bin/cage"
CAGE_SUPERVISOR_MODE = "--supervise-cage"
SANDBOX_LIFECYCLE_HELPER = "/usr/local/libexec/labwc-zoom-discord-compat-runtime"
PRIVATE_RUNTIME_ROOT = "/opt/xwayland"
PRIVATE_RUNTIME_LIBRARY_DIRECTORY = (
    f"{PRIVATE_RUNTIME_ROOT}/usr/lib/x86_64-linux-gnu"
)
XWAYLAND_BINARY = f"{PRIVATE_RUNTIME_ROOT}/usr/bin/Xwayland"
XWAYLAND_PROTOCOL = f"{PRIVATE_RUNTIME_ROOT}/usr/lib/xorg/protocol.txt"
XKBCOMP_BINARY = "/usr/bin/xkbcomp"
WL_COPY_BINARY = "/usr/bin/wl-copy"
WL_PASTE_BINARY = "/usr/bin/wl-paste"
OUTER_WAYLAND_DISPLAY_ENVIRONMENT = "LABWC_MANAGED_OUTER_WAYLAND_DISPLAY"
CLIPBOARD_SINK_MODE = "--copy-host-text-to-cage"
CLIPBOARD_POLL_INTERVAL_SECONDS = 0.05
PRIVATE_RUNTIME_LIBRARY_NAMES = (
    "libXau.so.6",
    "libXdmcp.so.6",
    "libXfont2.so.2",
    "libfontenc.so.1",
    "libxcb-cursor.so.0",
    "libxcb-image.so.0",
    "libxcb-render-util.so.0",
    "libxcb-render.so.0",
    "libxcb-shm.so.0",
    "libxcb-util.so.1",
    "libxcb.so.1",
    "libxcvt.so.0",
    "libxshmfence.so.1",
)
PRIVATE_APPLICATION_LIBRARY_DIRECTORIES = {
    "discord": (PRIVATE_RUNTIME_LIBRARY_DIRECTORY, "/opt/discord"),
    "zoom": (PRIVATE_RUNTIME_LIBRARY_DIRECTORY,),
}
DYNAMIC_LOADER_ENVIRONMENT_TO_CLEAR = (
    "LD_AUDIT",
    "LD_DEBUG",
    "LD_PRELOAD",
)
FORBIDDEN_INHERITED_X11_ENVIRONMENT = (
    "DESKTOP_STARTUP_ID",
    "SESSION_MANAGER",
    "WINDOWID",
    "XAUTHORITY",
    "XWAYLAND",
    "XWAYLAND_FORCE_SCALE",
    "XWAYLAND_NO_GLAMOR",
    "XWAYLAND_PATH",
    "XWAYLAND_RESTART_DELAY",
    "_XWAYLAND_GLOBAL_OUTPUT_SCALE",
)
FORBIDDEN_CAGE_ENVIRONMENT = ("WLR_BACKENDS",)
APPLICATION_X11_CONTROL_ENVIRONMENT_TO_CLEAR = (
    OUTER_WAYLAND_DISPLAY_ENVIRONMENT,
    "WLR_XWAYLAND",
    *FORBIDDEN_CAGE_ENVIRONMENT,
    *MANAGED_CAGE_COMPOSITOR_ENVIRONMENT,
    *FORBIDDEN_INHERITED_X11_ENVIRONMENT,
)
X11_SOCKET_DIRECTORY = "/tmp/.X11-unix"
MAX_DISPLAY_NUMBER = 65535
TERMINATION_TIMEOUT_SECONDS = 3.0
CAGE_STDERR_READ_BYTES = 4_096
MAX_CAGE_DIAGNOSTIC_LINE_BYTES = 4_096
CAGE_DRM_LEASE_INFO_PATTERN = re.compile(
    rb"\d{2}:\d{2}:\d{2}\.\d{3} \[INFO\] \[\.\./cage\.c:[1-9][0-9]*\] "
    rb"Failed to create wlr_drm_lease_manager_v1\r?\n"
)
XWAYLAND_BROKEN_PIPE_TEARDOWN_PATTERN = re.compile(
    rb"\(EE\) failed to write to Xwayland fd: Broken pipe\r?\n"
)
IGNORED_CAGE_DIAGNOSTIC_PATTERNS = (
    CAGE_DRM_LEASE_INFO_PATTERN,
    XWAYLAND_BROKEN_PIPE_TEARDOWN_PATTERN,
)

_active_processes: list[subprocess.Popen[bytes]] = []
_received_signal: int | None = None


class CompatibilityRuntimeError(RuntimeError):
    """A bounded failure suitable for the outer managed launcher."""


def fail(message: str) -> NoReturn:
    raise CompatibilityRuntimeError(message)


def sandbox_system_owner() -> tuple[int, int]:
    try:
        metadata = os.lstat(SYSTEM_OWNER_ANCHOR)
    except OSError as exc:
        fail(f"private compatibility system owner is unavailable: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_mode & 0o022
    ):
        fail("private compatibility system owner is unsafe")
    return metadata.st_uid, metadata.st_gid


def require_system_owned_file(
    label: str,
    path: str,
    *,
    system_owner: tuple[int, int],
    executable: bool = False,
) -> None:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        fail(f"{label} is unavailable: {path}: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != system_owner
        or metadata.st_mode & 0o022
        or not os.access(path, os.R_OK)
        or (executable and not os.access(path, os.X_OK))
    ):
        fail(
            f"{label} must be a system-owned regular file not writable by "
            f"group or others: {path}"
        )


def require_system_owned_symlink(
    label: str,
    path: str,
    expected_target: str,
    *,
    system_owner: tuple[int, int],
) -> None:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        fail(f"{label} is unavailable: {path}: {exc}")
    if (
        not stat.S_ISLNK(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != system_owner
        or os.path.realpath(path) != expected_target
    ):
        fail(f"{label} is unsafe: {path}")
    require_system_owned_file(
        f"{label} target",
        expected_target,
        system_owner=system_owner,
    )


def require_private_runtime_library(
    library_name: str,
    *,
    system_owner: tuple[int, int],
) -> None:
    if (
        not library_name
        or "/" in library_name
        or library_name in {".", ".."}
    ):
        fail(f"private compatibility library name is invalid: {library_name!r}")
    library_path = os.path.join(PRIVATE_RUNTIME_LIBRARY_DIRECTORY, library_name)
    try:
        metadata = os.lstat(library_path)
    except OSError as exc:
        fail(f"private compatibility library is unavailable: {library_path}: {exc}")
    if stat.S_ISREG(metadata.st_mode):
        require_system_owned_file(
            "private compatibility library",
            library_path,
            system_owner=system_owner,
        )
        return
    if not stat.S_ISLNK(metadata.st_mode):
        fail(f"private compatibility library entry is unsafe: {library_path}")

    library_target = os.path.realpath(library_path)
    if (
        os.path.commonpath((PRIVATE_RUNTIME_LIBRARY_DIRECTORY, library_target))
        != PRIVATE_RUNTIME_LIBRARY_DIRECTORY
    ):
        fail(
            "private compatibility library target escapes its managed "
            f"directory: {library_target}"
        )
    require_system_owned_symlink(
        "private compatibility library",
        library_path,
        library_target,
        system_owner=system_owner,
    )


def application_process_environment(app_name: str) -> dict[str, str]:
    environment = dict(os.environ)
    for name in (
        *DYNAMIC_LOADER_ENVIRONMENT_TO_CLEAR,
        *APPLICATION_X11_CONTROL_ENVIRONMENT_TO_CLEAR,
    ):
        environment.pop(name, None)
    library_directories = PRIVATE_APPLICATION_LIBRARY_DIRECTORIES.get(app_name)
    if library_directories is None:
        fail(
            "private compatibility runtime rejected library policy for "
            f"{app_name}"
        )
    environment["LD_LIBRARY_PATH"] = os.pathsep.join(library_directories)
    return environment


def clipboard_process_environment(wayland_display: str) -> dict[str, str]:
    runtime_directory = f"/run/user/{os.getuid()}"
    if os.environ.get("XDG_RUNTIME_DIR") != runtime_directory:
        fail("clipboard bridge received an unexpected XDG_RUNTIME_DIR")
    wayland_display = validate_wayland_socket_name(
        "clipboard Wayland socket name",
        wayland_display,
    )
    require_user_wayland_socket(runtime_directory, wayland_display)
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "XDG_RUNTIME_DIR": runtime_directory,
        "WAYLAND_DISPLAY": wayland_display,
    }


def validate_wayland_socket_name(label: str, value: str) -> str:
    if (
        not value
        or len(value) > 128
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is None
    ):
        fail(f"private compatibility runtime received an invalid {label}")
    return value


def require_user_wayland_socket(runtime_directory: str, socket_name: str) -> None:
    socket_path = os.path.join(runtime_directory, socket_name)
    try:
        metadata = os.lstat(socket_path)
    except OSError as exc:
        fail(f"private compatibility Wayland socket is unavailable: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        fail("private compatibility Wayland socket is unsafe")


def require_outer_cage_environment() -> None:
    runtime_directory = f"/run/user/{os.getuid()}"
    if os.environ.get("XDG_RUNTIME_DIR") != runtime_directory:
        fail("Cage supervisor received an unexpected XDG_RUNTIME_DIR")
    for name, expected_value in MANAGED_CAGE_ENVIRONMENT.items():
        if os.environ.get(name) != expected_value:
            fail(f"Cage supervisor received an unexpected {name}")
    for name in FORBIDDEN_CAGE_ENVIRONMENT:
        if name in os.environ:
            fail(f"Cage supervisor must not receive {name}")
    outer_wayland_display = validate_wayland_socket_name(
        "outer Wayland socket name",
        os.environ.get(OUTER_WAYLAND_DISPLAY_ENVIRONMENT, ""),
    )
    if os.environ.get("WAYLAND_DISPLAY") != outer_wayland_display:
        fail("Cage supervisor did not receive the imported outer Wayland socket")
    require_user_wayland_socket(runtime_directory, outer_wayland_display)
    if os.environ.get("WLR_XWAYLAND") != XWAYLAND_BINARY:
        fail("Cage supervisor received an unexpected WLR_XWAYLAND")
    inherited_x11_names = tuple(
        name
        for name in ("DISPLAY", *FORBIDDEN_INHERITED_X11_ENVIRONMENT)
        if os.environ.get(name)
    )
    if inherited_x11_names:
        fail(
            "Cage supervisor rejected inherited X11 state: "
            + ", ".join(inherited_x11_names)
        )


def require_cage_wayland_socket() -> None:
    runtime_directory = f"/run/user/{os.getuid()}"
    if os.environ.get("XDG_RUNTIME_DIR") != runtime_directory:
        fail("private compatibility runtime received an unexpected XDG_RUNTIME_DIR")
    for name, expected_value in MANAGED_CAGE_ENVIRONMENT.items():
        if os.environ.get(name) != expected_value:
            fail(
                "private compatibility runtime received an unexpected "
                f"{name}"
            )
    for name in FORBIDDEN_CAGE_ENVIRONMENT:
        if name in os.environ:
            fail(f"private compatibility runtime must not receive {name}")
    outer_wayland_display = validate_wayland_socket_name(
        "outer Wayland socket name",
        os.environ.get(OUTER_WAYLAND_DISPLAY_ENVIRONMENT, ""),
    )
    cage_wayland_display = validate_wayland_socket_name(
        "Cage Wayland socket name",
        os.environ.get("WAYLAND_DISPLAY", ""),
    )
    if cage_wayland_display == outer_wayland_display:
        fail("private compatibility runtime did not receive Cage's nested Wayland socket")
    require_user_wayland_socket(runtime_directory, outer_wayland_display)
    require_user_wayland_socket(runtime_directory, cage_wayland_display)


def clipboard_bridge_argv(cage_wayland_display: str) -> list[str]:
    cage_wayland_display = validate_wayland_socket_name(
        "Cage clipboard Wayland socket name",
        cage_wayland_display,
    )
    return [
        WL_PASTE_BINARY,
        "--type",
        "text",
        "--watch",
        SANDBOX_LIFECYCLE_HELPER,
        CLIPBOARD_SINK_MODE,
        cage_wayland_display,
    ]


def parse_clipboard_sink_arguments(arguments: list[str]) -> str:
    if len(arguments) != 2 or arguments[0] != CLIPBOARD_SINK_MODE:
        fail("private clipboard sink received malformed arguments")
    return validate_wayland_socket_name(
        "Cage clipboard Wayland socket name",
        arguments[1],
    )


def require_clipboard_sink_environment(cage_wayland_display: str) -> None:
    runtime_directory = f"/run/user/{os.getuid()}"
    outer_wayland_display = validate_wayland_socket_name(
        "outer Wayland socket name",
        os.environ.get(OUTER_WAYLAND_DISPLAY_ENVIRONMENT, ""),
    )
    if os.environ.get("WAYLAND_DISPLAY") != outer_wayland_display:
        fail("private clipboard sink did not receive the outer Wayland socket")
    if cage_wayland_display == outer_wayland_display:
        fail("private clipboard sink received the outer socket as its destination")
    require_user_wayland_socket(runtime_directory, outer_wayland_display)
    require_user_wayland_socket(runtime_directory, cage_wayland_display)


def require_cage_x11_display() -> str:
    if os.environ.get("WLR_XWAYLAND") != XWAYLAND_BINARY:
        fail("private compatibility runtime received an unexpected WLR_XWAYLAND")
    inherited_x11_names = tuple(
        name
        for name in FORBIDDEN_INHERITED_X11_ENVIRONMENT
        if os.environ.get(name)
    )
    if inherited_x11_names:
        fail(
            "private compatibility runtime rejected inherited X11 state: "
            + ", ".join(inherited_x11_names)
        )
    display = os.environ.get("DISPLAY", "")
    display_match = re.fullmatch(r":(0|[1-9][0-9]{0,4})", display)
    if display_match is None or int(display_match.group(1)) > MAX_DISPLAY_NUMBER:
        fail("private compatibility runtime received an invalid Cage DISPLAY")
    return display_match.group(1)


def require_private_x11_socket_directory() -> None:
    try:
        metadata = os.lstat(X11_SOCKET_DIRECTORY)
    except OSError as exc:
        fail(f"cannot validate the private compatibility socket directory: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o1777
    ):
        fail("private compatibility socket directory is unsafe")


def require_private_x11_socket(display_number: str) -> None:
    socket_path = os.path.join(X11_SOCKET_DIRECTORY, f"X{display_number}")
    try:
        metadata = os.lstat(socket_path)
    except OSError as exc:
        fail(f"cannot validate the private compatibility socket: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        fail("private compatibility socket is unsafe")


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=TERMINATION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=TERMINATION_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            print("warning: compatibility child did not exit after SIGKILL", file=sys.stderr)


def handle_signal(signum: int, _frame: object) -> None:
    global _received_signal
    _received_signal = signum
    for process in reversed(_active_processes):
        if process.poll() is None:
            try:
                process.send_signal(signum)
            except ProcessLookupError:
                pass


def register_signal_handlers() -> None:
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handle_signal)


def _write_stream_bytes(destination: BinaryIO, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = destination.write(payload[offset:])
        if written is None or written <= 0:
            fail("Cage supervisor could not relay a diagnostic")
        offset += written


def relay_cage_stderr(source: BinaryIO, destination: BinaryIO) -> None:
    pending = bytearray()
    passthrough_long_line = False

    while True:
        chunk = source.read(CAGE_STDERR_READ_BYTES)
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            fail("Cage supervisor received a non-binary diagnostic stream")
        pending.extend(chunk)
        emitted = False

        while True:
            newline_index = pending.find(b"\n")
            if newline_index < 0:
                break
            line = bytes(pending[: newline_index + 1])
            del pending[: newline_index + 1]
            if passthrough_long_line:
                _write_stream_bytes(destination, line)
                passthrough_long_line = False
                emitted = True
            elif not any(
                pattern.fullmatch(line) is not None
                for pattern in IGNORED_CAGE_DIAGNOSTIC_PATTERNS
            ):
                _write_stream_bytes(destination, line)
                emitted = True

        if passthrough_long_line and pending:
            _write_stream_bytes(destination, bytes(pending))
            pending.clear()
            emitted = True
        elif len(pending) > MAX_CAGE_DIAGNOSTIC_LINE_BYTES:
            _write_stream_bytes(destination, bytes(pending))
            pending.clear()
            passthrough_long_line = True
            emitted = True

        if emitted:
            destination.flush()

    if pending:
        _write_stream_bytes(destination, bytes(pending))
        destination.flush()


def parse_arguments(arguments: list[str]) -> tuple[str, str, list[str]]:
    if len(arguments) < 4 or arguments[2] != "--":
        fail("private compatibility runtime received malformed arguments")
    app_name, mode = arguments[0], arguments[1]
    child_argv = arguments[3:]
    expected_executable = ALLOWED_APPLICATIONS.get(app_name)
    if expected_executable is None or mode not in ALLOWED_MODES:
        fail("private compatibility runtime rejected the requested application")
    if not child_argv or child_argv[0] != expected_executable:
        fail("private compatibility runtime rejected the application executable")
    return app_name, mode, child_argv


def parse_cage_supervisor_arguments(arguments: list[str]) -> list[str]:
    parse_arguments(arguments)
    return arguments


def process_exit_status(returncode: int) -> int:
    if returncode < 0:
        return 128 + -returncode
    return returncode


def supervise_application(
    application: subprocess.Popen[bytes],
    clipboard_bridge: subprocess.Popen[bytes],
) -> int:
    while True:
        if _received_signal is not None:
            return 128 + _received_signal
        application_status = application.poll()
        if application_status is not None:
            return process_exit_status(application_status)
        clipboard_status = clipboard_bridge.poll()
        if clipboard_status is not None:
            fail(
                "host-to-Cage clipboard bridge exited while the application "
                f"was running (status {process_exit_status(clipboard_status)})"
            )
        time.sleep(CLIPBOARD_POLL_INTERVAL_SECONDS)


def run_clipboard_sink(arguments: list[str]) -> int:
    cage_wayland_display = parse_clipboard_sink_arguments(arguments)
    if os.geteuid() == 0:
        fail("private clipboard sink must not run as root")

    system_owner = sandbox_system_owner()
    require_clipboard_sink_environment(cage_wayland_display)
    require_system_owned_file(
        "Wayland clipboard writer",
        WL_COPY_BINARY,
        system_owner=system_owner,
        executable=True,
    )
    register_signal_handlers()

    clipboard_writer: subprocess.Popen[bytes] | None = None
    try:
        clipboard_writer = subprocess.Popen(
            [
                WL_COPY_BINARY,
                "--type",
                "text/plain;charset=utf-8",
            ],
            env=clipboard_process_environment(cage_wayland_display),
            stdin=None,
            stdout=subprocess.DEVNULL,
            stderr=None,
            close_fds=True,
        )
        _active_processes.append(clipboard_writer)
        returncode = clipboard_writer.wait()
        if _received_signal is not None:
            return 128 + _received_signal
        return process_exit_status(returncode)
    finally:
        stop_process(clipboard_writer)
        _active_processes.clear()


def run_cage_supervisor(arguments: list[str]) -> int:
    inner_arguments = parse_cage_supervisor_arguments(arguments)
    if os.geteuid() == 0:
        fail("Cage supervisor must not run as root")

    system_owner = sandbox_system_owner()
    require_system_owned_file(
        "Cage compositor",
        CAGE_BINARY,
        system_owner=system_owner,
        executable=True,
    )
    require_outer_cage_environment()
    register_signal_handlers()

    cage: subprocess.Popen[bytes] | None = None
    cage_stderr: BinaryIO | None = None
    try:
        cage = subprocess.Popen(
            [
                CAGE_BINARY,
                "-d",
                # Cage starts its compiled Xwayland integration automatically.
                # WLR_XWAYLAND selects the private server. Cage 0.2/0.3 has no
                # Xwayland enable switch; where -x exists, it disables Xwayland.
                "--",
                SANDBOX_LIFECYCLE_HELPER,
                *inner_arguments,
            ],
            stdin=None,
            stdout=None,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        _active_processes.append(cage)
        if _received_signal is not None and cage.poll() is None:
            cage.send_signal(_received_signal)
        cage_stderr = cage.stderr
        if cage_stderr is None:
            fail("Cage supervisor did not receive Cage's diagnostic stream")
        relay_cage_stderr(cage_stderr, sys.stderr.buffer)
        returncode = cage.wait()
        if _received_signal is not None:
            return 128 + _received_signal
        return process_exit_status(returncode)
    finally:
        stop_process(cage)
        if cage_stderr is not None:
            cage_stderr.close()
        _active_processes.clear()


def run(arguments: list[str]) -> int:
    app_name, _mode, child_argv = parse_arguments(arguments)
    if os.geteuid() == 0:
        fail("private compatibility runtime must not run as root")

    system_owner = sandbox_system_owner()
    require_cage_wayland_socket()
    display_number = require_cage_x11_display()
    require_private_x11_socket_directory()
    require_private_x11_socket(display_number)
    require_system_owned_file(
        "private compatibility Xwayland executable",
        XWAYLAND_BINARY,
        system_owner=system_owner,
        executable=True,
    )
    require_system_owned_file(
        "private compatibility Xwayland protocol data",
        XWAYLAND_PROTOCOL,
        system_owner=system_owner,
    )
    require_system_owned_file(
        "private compatibility XKB compiler",
        XKBCOMP_BINARY,
        system_owner=system_owner,
        executable=True,
    )
    for library_name in PRIVATE_RUNTIME_LIBRARY_NAMES:
        require_private_runtime_library(
            library_name,
            system_owner=system_owner,
        )
    require_system_owned_file(
        "Wayland clipboard reader",
        WL_PASTE_BINARY,
        system_owner=system_owner,
        executable=True,
    )
    require_system_owned_file(
        "Wayland clipboard writer",
        WL_COPY_BINARY,
        system_owner=system_owner,
        executable=True,
    )

    register_signal_handlers()
    application: subprocess.Popen[bytes] | None = None
    clipboard_bridge: subprocess.Popen[bytes] | None = None
    try:
        cage_wayland_display = validate_wayland_socket_name(
            "Cage Wayland socket name",
            os.environ.get("WAYLAND_DISPLAY", ""),
        )
        outer_wayland_display = validate_wayland_socket_name(
            "outer Wayland socket name",
            os.environ.get(OUTER_WAYLAND_DISPLAY_ENVIRONMENT, ""),
        )
        clipboard_environment = clipboard_process_environment(
            outer_wayland_display
        )
        clipboard_environment[OUTER_WAYLAND_DISPLAY_ENVIRONMENT] = (
            outer_wayland_display
        )
        clipboard_bridge = subprocess.Popen(
            clipboard_bridge_argv(cage_wayland_display),
            env=clipboard_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=None,
            close_fds=True,
        )
        _active_processes.append(clipboard_bridge)
        clipboard_status = clipboard_bridge.poll()
        if clipboard_status is not None:
            fail(
                "host-to-Cage clipboard bridge failed during startup "
                f"(status {process_exit_status(clipboard_status)})"
            )

        application_environment = application_process_environment(app_name)
        expected_display = f":{display_number}"
        if application_environment.get("DISPLAY") != expected_display:
            fail("private compatibility runtime lost Cage's DISPLAY")
        application = subprocess.Popen(
            child_argv,
            env=application_environment,
            stdin=None,
            stdout=None,
            stderr=None,
            close_fds=True,
        )
        _active_processes.append(application)
        return supervise_application(application, clipboard_bridge)
    finally:
        stop_process(application)
        stop_process(clipboard_bridge)
        _active_processes.clear()


def main(arguments: list[str] | None = None) -> int:
    runtime_arguments = list(arguments if arguments is not None else sys.argv[1:])
    try:
        if runtime_arguments[:1] == [CAGE_SUPERVISOR_MODE]:
            return run_cage_supervisor(runtime_arguments[1:])
        if runtime_arguments[:1] == [CLIPBOARD_SINK_MODE]:
            return run_clipboard_sink(runtime_arguments)
        return run(runtime_arguments)
    except CompatibilityRuntimeError as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        if _received_signal is not None:
            return 128 + _received_signal
        return 1
    except (OSError, UnicodeError, ValueError) as exc:
        print(
            f"fatal: private Zoom/Discord compatibility runtime failed: {exc}",
            file=sys.stderr,
        )
        if _received_signal is not None:
            return 128 + _received_signal
        return 1
