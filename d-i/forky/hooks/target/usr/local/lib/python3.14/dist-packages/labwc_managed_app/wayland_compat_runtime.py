"""Cage and application supervisors, executed only inside Bubblewrap."""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import socket
import struct
import tempfile
import os
import re
import select
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import NoReturn

from .compat_protocol import (
    CONTROL_DIRECTORY, CONTROL_SOCKET, Outcome, ProtocolError, activation_arguments,
    peer_credentials, send_packet, receive_packet, stop_processes, protect_supervisor,
    INFRASTRUCTURE_RESULT, STARTUP_RESULT, CLEANUP_RESULT,
)

from .network_namespace import DiscordRPCRelay

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
XWAYLAND_EXEC_HELPER = "/usr/local/libexec/labwc-private-xwayland"
CLIPBOARD_BRIDGE_MODE = "--bridge-clipboard"
PRIMARY_SOCKET_ENVIRONMENT = "LABWC_COMPAT_PRIMARY_SOCKET"
XWAYLAND_PROTOCOL = f"{PRIVATE_RUNTIME_ROOT}/usr/lib/xorg/protocol.txt"
XKBCOMP_BINARY = "/usr/bin/xkbcomp"
WL_COPY_BINARY = "/usr/bin/wl-copy"
WL_PASTE_BINARY = "/usr/bin/wl-paste"
XCLIP_BINARY = "/usr/bin/xclip"
OUTER_WAYLAND_DISPLAY_ENVIRONMENT = "LABWC_MANAGED_OUTER_WAYLAND_DISPLAY"
MASKED_APPLICATION_MODE = "--run-masked-application"
CLIPBOARD_POLL_INTERVAL_SECONDS = 0.05
CAGE_CLIPBOARD_POLL_INTERVAL_SECONDS = 0.5
MAX_CLIPBOARD_TEXT_BYTES = 8 * 1024 * 1024
CLIPBOARD_OPERATION_TIMEOUT_SECONDS = 10
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
    "discord": ("/opt/discord",),
    "zoom": (),
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
FORBIDDEN_CAGE_ENVIRONMENT = ("WLR_DRM_DEVICES", "WLR_DRM_NO_ATOMIC")
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
    for name in tuple(environment):
        if (name.startswith(("LD_", "WLR_", "LABWC_COMPAT_", "XWAYLAND", "QT_", "QML"))
                or name in APPLICATION_X11_CONTROL_ENVIRONMENT_TO_CLEAR
                or name in {"WAYLAND_DISPLAY", "WAYLAND_SOCKET", "GDK_BACKEND", "MOZ_ENABLE_WAYLAND",
                            "SDL_VIDEODRIVER", "CLUTTER_BACKEND", "ELECTRON_OZONE_PLATFORM_HINT",
                            "__EGL_VENDOR_LIBRARY_FILENAMES", "__EGL_VENDOR_LIBRARY_DIRS"}):
            environment.pop(name, None)
    library_directories = PRIVATE_APPLICATION_LIBRARY_DIRECTORIES.get(app_name)
    if library_directories is None:
        fail("private compatibility runtime rejected application library policy")
    if library_directories:
        environment["LD_LIBRARY_PATH"] = os.pathsep.join(library_directories)
    environment.update({"GDK_BACKEND": "x11", "SDL_VIDEODRIVER": "x11", "CLUTTER_BACKEND": "x11"})
    if app_name == "zoom":
        environment["QT_QPA_PLATFORM"] = "xcb"
        environment["QT_OPENGL"] = "desktop"
    else:
        environment["ELECTRON_OZONE_PLATFORM_HINT"] = "x11"
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


def private_clipboard_x11_environment() -> dict[str, str]:
    # DISPLAY comes only from the already validated Cage supervisor and is
    # rechecked in each bridge child. Never inherit an Xauthority or host X11
    # endpoint from the launcher environment.
    display = os.environ.get("DISPLAY", "")
    match = re.fullmatch(r":(0|[1-9][0-9]{0,4})", display)
    if match is None or int(match.group(1)) > MAX_DISPLAY_NUMBER:
        fail("private clipboard bridge received an invalid Cage DISPLAY")
    require_private_x11_socket_directory()
    require_private_x11_socket(match.group(1))
    return {
        "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "DISPLAY": display,
    }


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
    if os.environ.get("WLR_XWAYLAND") != XWAYLAND_EXEC_HELPER:
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


def masked_application_argv(
    app_name: str, outer_display: str, cage_display: str, child_argv: list[str]
) -> list[str]:
    if app_name not in ALLOWED_APPLICATIONS or child_argv[:1] != [ALLOWED_APPLICATIONS[app_name]]:
        fail("private compatibility runtime rejected the masked application")
    outer_display = validate_wayland_socket_name("outer Wayland socket name", outer_display)
    cage_display = validate_wayland_socket_name("Cage Wayland socket name", cage_display)
    if outer_display == cage_display:
        fail("private compatibility runtime received duplicate Wayland sockets")
    return [
        "/usr/bin/bwrap", "--unshare-user", "--unshare-pid",
        "--die-with-parent", "--bind", "/", "/",
        # A regular --bind marks devices nodev. Rebind only the outer
        # sandbox's private /dev so Chromium can open /dev/null and the
        # already-selected camera/render nodes in this nested namespace.
        "--dev-bind", "/dev", "/dev",
        # Cage and the bridge keep the parent mount. Only the application
        # loses this exact host socket in its private mount namespace.
        "--ro-bind", "/dev/null", f"/run/user/{os.getuid()}/{outer_display}",
        "--ro-bind", "/dev/null", f"/run/user/{os.getuid()}/{cage_display}",
        "--tmpfs", CONTROL_DIRECTORY,
        "--tmpfs", PRIVATE_RUNTIME_ROOT,
        "--ro-bind", "/dev/null", CAGE_BINARY,
        "--ro-bind", "/dev/null", XWAYLAND_EXEC_HELPER,
        "--cap-drop", "ALL",
        "--proc", "/proc", "--", SANDBOX_LIFECYCLE_HELPER,
        MASKED_APPLICATION_MODE, app_name, outer_display, cage_display,
        "--", *child_argv,
    ]


def require_private_null_device() -> None:
    try:
        fd = os.open("/dev/null", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        fail(f"private compatibility application cannot open /dev/null: {exc}")
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISCHR(metadata.st_mode) or metadata.st_rdev != os.makedev(1, 3):
            fail("private compatibility application has an invalid /dev/null")
    finally:
        os.close(fd)


def require_cage_x11_display() -> str:
    if os.environ.get("WLR_XWAYLAND") != XWAYLAND_EXEC_HELPER:
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


def stop_process(process: subprocess.Popen[bytes] | None) -> bool:
    return stop_processes([process], time.monotonic() + TERMINATION_TIMEOUT_SECONDS)


def handle_signal(signum: int, _frame: object) -> None:
    global _received_signal
    if _received_signal is None:
        _received_signal = signum


def register_signal_handlers() -> None:
    global _received_signal
    _received_signal = None
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handle_signal)


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


def require_x11_connection(display_number: str) -> socket.socket:
    """Validate a real private X11 setup reply, retaining the connection as a liveness check."""
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(5)
    try:
        connection.connect(os.path.join(X11_SOCKET_DIRECTORY, "X" + display_number))
        connection.sendall(struct.pack("<BBHHHHH", ord("l"), 0, 11, 0, 0, 0, 0))
        header = bytearray()
        deadline = time.monotonic() + 5
        while len(header) < 8:
            connection.settimeout(max(0.001, deadline - time.monotonic()))
            chunk = connection.recv(8 - len(header))
            if not chunk:
                fail("private Xwayland closed during protocol readiness")
            header.extend(chunk)
        success, _unused, major, _minor, units = struct.unpack("<BBHHH", header)
        if success != 1 or major != 11 or units * 4 > 262144:
            fail("private Xwayland did not accept the managed X11 connection")
        remaining = units * 4
        while remaining:
            if time.monotonic() >= deadline:
                fail("private Xwayland readiness timed out")
            connection.settimeout(max(0.001, deadline - time.monotonic()))
            chunk = connection.recv(min(65536, remaining))
            if not chunk:
                fail("private Xwayland returned truncated readiness data")
            remaining -= len(chunk)
        connection.setblocking(False)
        return connection
    except BaseException:
        connection.close()
        raise


def connect_runtime(app_name: str, mode: str) -> socket.socket:
    run_id = os.environ.get("LABWC_COMPAT_RUN_ID", "")
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        fail("private runtime lacks its managed run identity")
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    channel.settimeout(5)
    try:
        channel.connect(CONTROL_SOCKET)
        hello = receive_packet(channel)
        if (hello.get("type") != "instance" or hello.get("run_id") != run_id
                or hello.get("app") != app_name or hello.get("mode") != mode
                or peer_credentials(channel)[1] != os.getuid()):
            fail("private runtime coordinator identity is mismatched")
        send_packet(channel, {"type": "runtime", "run_id": run_id})
        if receive_packet(channel) != {"type": "runtime-accepted"}:
            fail("private runtime coordinator rejected the channel")
        channel.setblocking(False)
        return channel
    except BaseException:
        channel.close()
        raise


def bounded_read(fd: int, deadline: float, limit: int = MAX_CLIPBOARD_TEXT_BYTES) -> bytes:
    """Real pipe reads, including partial input, obey size/time/stop bounds."""
    result = bytearray()
    with selectors.PollSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while True:
            if _received_signal is not None:
                fail("clipboard operation cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                fail("clipboard input timed out")
            if not selector.select(min(remaining, 0.05)):
                continue
            chunk = os.read(fd, min(65536, limit + 1 - len(result)))
            if not chunk:
                return bytes(result)
            result.extend(chunk)
            if len(result) > limit:
                fail("clipboard input exceeds the limit")


def clipboard_lock(cage_display: str, *, deadline: float | None = None) -> int:
    cage_display = validate_wayland_socket_name("clipboard lock display", cage_display)
    path = f"/run/user/{os.getuid()}/labwc-clipboard-{cage_display}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    deadline = time.monotonic() + CLIPBOARD_OPERATION_TIMEOUT_SECONDS if deadline is None else deadline
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_nlink != 1):
            fail("private clipboard lock is unsafe")
        while _received_signal is None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    fail("private clipboard lock timed out")
                time.sleep(0.025)
        fail("private clipboard lock cancelled")
    except BaseException:
        os.close(fd)
        raise


@dataclass(frozen=True)
class ClipboardSelection:
    state: str  # text, empty, cleared, unavailable
    data: bytes | None = None


def read_clipboard_selection(environment: dict[str, str], *, x11: bool = False,
                             deadline: float | None = None) -> ClipboardSelection:
    command = ([XCLIP_BINARY, "-selection", "clipboard", "-out", "-target", "UTF8_STRING"]
               if x11 else [WL_PASTE_BINARY, "--no-newline", "--type", "text"])
    try:
        reader = subprocess.Popen(command, env=environment, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  close_fds=True, start_new_session=True)
    except OSError:
        return ClipboardSelection("unavailable")
    try:
        deadline = time.monotonic() + CLIPBOARD_OPERATION_TIMEOUT_SECONDS if deadline is None else deadline
        buffers = {reader.stdout: bytearray(), reader.stderr: bytearray()}
        limits = {reader.stdout: MAX_CLIPBOARD_TEXT_BYTES, reader.stderr: 2048}
        # Drain both pipes concurrently; a diagnostic cannot stall the data
        # reader. Diagnostic bytes remain private and are never logged.
        with selectors.PollSelector() as selector:
            for stream in buffers:
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                if _received_signal is not None:
                    fail("clipboard operation cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return ClipboardSelection("unavailable")
                for key, _event in selector.select(min(remaining, 0.05)):
                    stream = key.fileobj
                    chunk = os.read(stream.fileno(), min(65536, limits[stream] + 1 - len(buffers[stream])))
                    if not chunk:
                        selector.unregister(stream)
                    else:
                        buffers[stream].extend(chunk)
                        if len(buffers[stream]) > limits[stream]:
                            return ClipboardSelection("unavailable")
        status = reader.wait(timeout=max(0.001, deadline - time.monotonic()))
        payload = bytes(buffers[reader.stdout])
        diagnostic = bytes(buffers[reader.stderr]).strip()
        if status == 0:
            return ClipboardSelection("text" if payload else "empty", payload)
        # These fixed helper diagnostics prove no selection owner. Other
        # versions/errors/non-text selections are unavailable, never guessed
        # empty and never replaced from a cached secret.
        cleared = (b"xclip: Error: There is no owner for the CLIPBOARD selection" if x11 else b"Nothing is copied")
        return ClipboardSelection("cleared" if status == 1 and diagnostic == cleared else "unavailable")
    except (OSError, subprocess.TimeoutExpired):
        return ClipboardSelection("unavailable")
    finally:
        stop_processes([reader], time.monotonic() + 0.5, groups=True)
        reader.stdout.close()
        reader.stderr.close()


def destination_clipboard_text(environment: dict[str, str], *, x11: bool = False,
                               deadline: float | None = None) -> bytes | None:
    return read_clipboard_selection(environment, x11=x11, deadline=deadline).data


def selection_owner(payload: bytes, environment: dict[str, str], *, x11: bool) -> subprocess.Popen:
    command = ([XCLIP_BINARY, "-selection", "clipboard", "-quiet", "-in", "-target", "UTF8_STRING"] if x11 else
               [WL_COPY_BINARY, "--foreground", "--type", "text/plain;charset=utf-8"])
    writer = subprocess.Popen(command, env=environment, stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              close_fds=True, start_new_session=True)
    try:
        deadline = time.monotonic() + CLIPBOARD_OPERATION_TIMEOUT_SECONDS
        os.set_blocking(writer.stdin.fileno(), False)
        offset = 0
        with selectors.PollSelector() as selector:
            selector.register(writer.stdin, selectors.EVENT_WRITE)
            while offset < len(payload):
                if _received_signal is not None or time.monotonic() >= deadline:
                    fail("clipboard writer cancelled or timed out")
                if not selector.select(0.05):
                    continue
                try:
                    offset += os.write(writer.stdin.fileno(), payload[offset:offset + 65536])
                except BlockingIOError:
                    pass
        writer.stdin.close()
        # Confirm ownership, rather than timing out a healthy foreground owner.
        while time.monotonic() < deadline and _received_signal is None:
            if writer.poll() is not None:
                fail("clipboard selection owner exited before ownership")
            if destination_clipboard_text(environment, x11=x11, deadline=deadline) == payload:
                return writer
            time.sleep(0.025)
        fail("clipboard selection ownership was not established")
    except BaseException:
        stop_processes([writer], time.monotonic() + 0.5, groups=True)
        if writer.stdin is not None:
            writer.stdin.close()
        raise


def run_clipboard_bridge(arguments: list[str]) -> int:
    if len(arguments) != 2 or arguments[0] != CLIPBOARD_BRIDGE_MODE:
        fail("clipboard bridge received malformed arguments")
    cage_display = validate_wayland_socket_name("Cage clipboard display", arguments[1])
    outer_display = os.environ.get(OUTER_WAYLAND_DISPLAY_ENVIRONMENT, "")
    if cage_display == outer_display or os.geteuid() == 0:
        fail("clipboard bridge lacks private display ownership")
    host_environment = clipboard_process_environment(outer_display)
    private_environment = private_clipboard_x11_environment()
    register_signal_handlers()
    owner = None
    last = None
    try:
        while _received_signal is None:
            selection = read_clipboard_selection(host_environment)
            if selection.state in {"cleared", "unavailable"}:
                # A non-text selection, cleared password, or transient failure
                # must not leave our previous host text available in the app.
                stop_processes([owner], time.monotonic() + 0.5, groups=True)
                owner, last = None, None
            elif selection != last:
                stop_processes([owner], time.monotonic() + 0.5, groups=True)
                owner = None
                try:
                    owner = selection_owner(selection.data, private_environment, x11=True)
                    last = selection
                except (OSError, CompatibilityRuntimeError):
                    # Clipboard providers can disappear between offer/read.
                    # Retry fresh host content instead of killing the bridge.
                    last = None
            # Never write to the host clipboard, or reassert an unchanged host
            # selection after the app has copied its own text. PRIMARY remains
            # independent: selecting text must not overwrite CLIPBOARD.
            time.sleep(CAGE_CLIPBOARD_POLL_INTERVAL_SECONDS)
        return 128 + _received_signal
    finally:
        stop_processes([owner], time.monotonic() + 0.5, groups=True)


def run_masked_application(arguments: list[str]) -> int:
    protect_supervisor()
    if len(arguments) < 6 or arguments[4] != "--":
        fail("masked compatibility application received malformed arguments")
    _, app_name, outer_display, cage_display, _, *child_argv = arguments
    masked_application_argv(app_name, outer_display, cage_display, child_argv)
    if os.geteuid() == 0:
        fail("masked compatibility application must not run as root")
    runtime_directory = f"/run/user/{os.getuid()}"
    if os.environ.get("XDG_RUNTIME_DIR") != runtime_directory or os.environ.get("WAYLAND_DISPLAY") != cage_display:
        fail("masked application lost its private display identity")
    for display in (outer_display, cage_display):
        if stat.S_ISSOCK(os.lstat(os.path.join(runtime_directory, display)).st_mode):
            fail("masked application can still reach a host Wayland socket")
    require_private_null_device()
    path = os.environ.get(PRIMARY_SOCKET_ENVIRONMENT, "")
    if re.fullmatch(r"/tmp/labwc-compat-primary-[A-Za-z0-9_]+/primary.sock", path) is None:
        fail("masked application has an invalid primary channel")
    metadata = os.lstat(path)
    parent = os.lstat(os.path.dirname(path))
    if (not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600 or not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700):
        fail("masked application primary channel is unsafe")
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    channel.settimeout(5)
    channel.connect(path)
    send_packet(channel, {"type": "primary-ready"})
    if receive_packet(channel) != {"type": "primary-accepted"}:
        fail("masked application primary channel was rejected")
    channel.setblocking(False)
    register_signal_handlers()
    application = None
    activations = []
    outcome = Outcome("startup-failed", STARTUP_RESULT)
    try:
        environment = application_process_environment(app_name)
        application = subprocess.Popen(child_argv, env=environment, close_fds=True, start_new_session=True)
        send_packet(channel, {"type": "running"})
        # The profile's fixed backend arguments are retained. One-time URI
        # data is replaced, never reused when another activation arrives.
        base_argv = child_argv[:-1] if child_argv[-1].startswith(("discord:", "--url=")) else child_argv
        while application.poll() is None and _received_signal is None:
            for process, deadline in tuple(activations):
                if process.poll() is not None or time.monotonic() >= deadline:
                    stop_processes([process], time.monotonic() + 0.5, groups=True)
                    activations.remove((process, deadline))
            with selectors.DefaultSelector() as selector:
                selector.register(channel, selectors.EVENT_READ)
                if selector.select(0.05):
                    packet = receive_packet(channel)
                    if set(packet) != {"type", "id", "args"} or packet["type"] != "activate":
                        fail("masked application received an invalid activation")
                    approved = activation_arguments(app_name, packet["args"])
                    accepted = bool(approved) and not activations
                    if accepted:
                        process = subprocess.Popen([*base_argv, *approved], env=environment,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            close_fds=True, start_new_session=True)
                        activations.append((process, time.monotonic() + 5))
                    send_packet(channel, {"type": "activation", "id": packet["id"], "accepted": accepted})
        outcome = (Outcome("user-stopped", 128 + _received_signal, _received_signal)
                   if _received_signal is not None else Outcome.observed(app_name, application.returncode))
    except (OSError, ProtocolError, CompatibilityRuntimeError):
        outcome = Outcome("infrastructure-failed", INFRASTRUCTURE_RESULT)
    finally:
        # Publish the observed cause before cleanup. The host starts its one
        # overall deadline now; later cleanup cannot replace this outcome.
        try:
            send_packet(channel, outcome.packet())
        finally:
            cleaned = stop_processes([application, *(p for p, _ in activations)], time.monotonic() + 3, groups=True)
            if not cleaned:
                outcome = outcome.cleanup_failed()
            try:
                send_packet(channel, {"type": "cleanup", "failed": not cleaned})
            finally:
                channel.close()
    return outcome.result


def run_cage_supervisor(arguments: list[str]) -> int:
    protect_supervisor()
    inner_arguments = parse_cage_supervisor_arguments(arguments)
    if os.geteuid() == 0:
        fail("Cage supervisor must not run as root")
    require_system_owned_file("Cage compositor", CAGE_BINARY, system_owner=sandbox_system_owner(), executable=True)
    require_outer_cage_environment()
    register_signal_handlers()
    cage = subprocess.Popen([CAGE_BINARY, "-d", "--", SANDBOX_LIFECYCLE_HELPER, *inner_arguments],
                            stdin=None, stdout=None, stderr=None, close_fds=True, start_new_session=True)
    try:
        while cage.poll() is None and _received_signal is None:
            time.sleep(0.05)
        result = 128 + _received_signal if _received_signal is not None else process_exit_status(cage.returncode)
        signum = _received_signal or (-cage.returncode if cage.returncode is not None and cage.returncode < 0 else 0)
    finally:
        cleaned = stop_processes([cage], time.monotonic() + 3, groups=True)
    if result or not cleaned:
        report_compositor_outcome(arguments[0], arguments[1], result, signum, cleaned)
    return result if cleaned else result or CLEANUP_RESULT


def report_compositor_outcome(app_name: str, mode: str, result: int, signum: int, cleaned: bool) -> None:
    """Report a directly observed Cage signal without parsing its stderr/status."""
    try:
        run_id = os.environ.get("LABWC_COMPAT_RUN_ID", "")
        if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
            raise ProtocolError("compositor lacks run identity")
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as channel:
            channel.settimeout(0.5)
            channel.connect(CONTROL_SOCKET)
            hello = receive_packet(channel)
            if (hello.get("type") != "instance" or hello.get("run_id") != run_id
                    or hello.get("app") != app_name or hello.get("mode") != mode
                    or peer_credentials(channel)[1] != os.getuid()):
                raise ProtocolError("compositor outcome coordinator is mismatched")
            send_packet(channel, {"type": "compositor-outcome", "run_id": run_id,
                                  "result": result, "signal": signum, "cleanup": "ok" if cleaned else "failed"})
            if receive_packet(channel) != {"type": "compositor-accepted"}:
                raise ProtocolError("compositor outcome was rejected")
    except (OSError, ProtocolError):
        print("compat-runtime: compositor outcome channel unavailable", file=sys.stderr)


def run(arguments: list[str]) -> int:
    protect_supervisor()
    app_name, mode, child_argv = parse_arguments(arguments)
    if os.geteuid() == 0:
        fail("private compatibility runtime must not run as root")
    register_signal_handlers()
    channel = connect_runtime(app_name, mode)
    application = None
    primary = None
    x11 = None
    bridge = None
    listener = None
    primary_directory = None
    rpc = None
    running = False
    outcome = Outcome("startup-failed", STARTUP_RESULT)
    try:
        require_cage_wayland_socket()
        display_number = require_cage_x11_display()
        require_private_x11_socket_directory()
        require_private_x11_socket(display_number)
        x11 = require_x11_connection(display_number)
        outer_display = os.environ[OUTER_WAYLAND_DISPLAY_ENVIRONMENT]
        cage_display = os.environ["WAYLAND_DISPLAY"]
        if os.environ.get("LABWC_COMPAT_CLIPBOARD") not in {"0", "1"}:
            fail("clipboard sharing policy is invalid")
        if os.environ["LABWC_COMPAT_CLIPBOARD"] == "1":
            try:
                for path in (WL_PASTE_BINARY, XCLIP_BINARY):
                    require_system_owned_file("clipboard helper", path, system_owner=sandbox_system_owner(), executable=True)
                bridge = subprocess.Popen([SANDBOX_LIFECYCLE_HELPER, CLIPBOARD_BRIDGE_MODE, cage_display],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=None,
                    close_fds=True, start_new_session=True)
            except (OSError, CompatibilityRuntimeError):
                print("compat-runtime: clipboard bridge unavailable", file=sys.stderr)
        if app_name == "discord":
            rpc = DiscordRPCRelay()
        primary_directory = tempfile.mkdtemp(prefix="labwc-compat-primary-", dir="/tmp")
        primary_path = os.path.join(primary_directory, "primary.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        listener.bind(primary_path)
        os.chmod(primary_path, 0o600)
        listener.listen(1)
        listener.settimeout(0.05)
        environment = dict(os.environ)
        environment[PRIMARY_SOCKET_ENVIRONMENT] = primary_path
        application = subprocess.Popen(masked_application_argv(app_name, outer_display, cage_display, child_argv),
            env=environment, close_fds=True, start_new_session=True)
        deadline = time.monotonic() + 5
        while primary is None and time.monotonic() < deadline and _received_signal is None:
            if application.poll() is not None:
                fail("application namespace exited before readiness")
            try:
                primary, _ = listener.accept()
            except socket.timeout:
                continue
        if primary is None:
            fail("application namespace readiness timed out")
        if peer_credentials(primary)[1] != os.getuid():
            fail("application namespace peer owner is mismatched")
        primary.settimeout(1)
        if receive_packet(primary) != {"type": "primary-ready"}:
            fail("application namespace returned invalid readiness")
        # No payload exists yet. Remove the rendezvous before acknowledging it,
        # and retain only connected, non-inheritable supervisor descriptors.
        listener.close()
        listener = None
        os.unlink(primary_path)
        os.rmdir(primary_directory)
        primary_directory = None
        send_packet(primary, {"type": "primary-accepted"})
        primary.setblocking(False)
        warned_bridge = False
        with selectors.DefaultSelector() as selector:
            selector.register(primary, selectors.EVENT_READ, "primary")
            selector.register(channel, selectors.EVENT_READ, "host")
            selector.register(x11, selectors.EVENT_READ, "x11")
            while _received_signal is None:
                if bridge is not None and bridge.poll() is not None and not warned_bridge:
                    warned_bridge = True
                    print("compat-runtime: clipboard bridge degraded", file=sys.stderr)
                if rpc is not None:
                    rpc.service()
                events = selector.select(0.05)
                # Observed application outcome wins over concurrent teardown.
                events.sort(key=lambda item: item[0].data != "primary")
                finished = False
                for key, _event in events:
                    if key.data == "primary":
                        # Drain queued state/outcome packets before X11 teardown.
                        for _ in range(16):
                            packet = receive_packet(primary)
                            if packet == {"type": "running"}:
                                running = True
                                send_packet(channel, packet)
                            elif packet.get("type") == "outcome":
                                outcome = Outcome.from_packet(packet)
                                finished = True
                                break
                            elif packet.get("type") == "activation":
                                send_packet(channel, packet)
                            else:
                                fail("invalid primary runtime packet")
                            if not select.select([primary], [], [], 0)[0]:
                                break
                        if finished:
                            break
                    elif key.data == "host":
                        send_packet(primary, receive_packet(channel))
                    elif not x11.recv(65536):
                        fail("required private Xwayland connection closed")
                if finished:
                    break
                if application.poll() is not None and not events:
                    fail("application namespace ended without a primary outcome")
            if _received_signal is not None:
                outcome = Outcome("user-stopped", 128 + _received_signal, _received_signal)
    except (OSError, ProtocolError, CompatibilityRuntimeError):
        outcome = Outcome("infrastructure-failed" if running else "startup-failed",
                          INFRASTRUCTURE_RESULT if running else STARTUP_RESULT)
    finally:
        cleanup_deadline = time.monotonic() + 8
        if rpc is not None:
            rpc.close()
        try:
            channel.settimeout(0.5)
            send_packet(channel, outcome.packet())
            cleaned = stop_processes([application, bridge], cleanup_deadline, groups=True)
            # The primary's cleanup message is non-secret, bounded, and may
            # already be queued when its namespace supervisor exits.
            if primary is not None:
                primary.settimeout(min(0.1, max(0.001, cleanup_deadline - time.monotonic())))
                try:
                    record = receive_packet(primary)
                    if record == {"type": "cleanup", "failed": True}:
                        cleaned = False
                except (OSError, ProtocolError):
                    pass
            if not cleaned:
                outcome = outcome.cleanup_failed()
            send_packet(channel, {"type": "cleanup", "failed": not cleaned})
        finally:
            # A failed control channel still requires owned-child teardown.
            stop_processes([application, bridge], cleanup_deadline, groups=True)
            for sock in (primary, x11, listener, channel):
                if sock is not None:
                    sock.close()
            if primary_directory is not None:
                path = os.path.join(primary_directory, "primary.sock")
                if os.path.lexists(path):
                    os.unlink(path)
                os.rmdir(primary_directory)
    return outcome.result


def main(arguments: list[str] | None = None) -> int:
    runtime_arguments = list(arguments if arguments is not None else sys.argv[1:])
    try:
        if runtime_arguments[:1] == [CAGE_SUPERVISOR_MODE]:
            return run_cage_supervisor(runtime_arguments[1:])
        if runtime_arguments[:1] == [CLIPBOARD_BRIDGE_MODE]:
            return run_clipboard_bridge(runtime_arguments)
        if runtime_arguments[:1] == [MASKED_APPLICATION_MODE]:
            return run_masked_application(runtime_arguments)
        return run(runtime_arguments)
    except (CompatibilityRuntimeError, ProtocolError, OSError, UnicodeError, ValueError, subprocess.TimeoutExpired):
        print("compat-runtime: required component failed", file=sys.stderr)
        return 128 + _received_signal if _received_signal is not None else STARTUP_RESULT
