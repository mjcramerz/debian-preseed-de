"""Filtered D-Bus proxy lifecycle for managed application sandboxes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
import re
import signal
import socket
import stat
import subprocess
from typing import NoReturn

from .profiles import (
    NOTIFICATIONS_DBUS_NAME,
    PORTAL_DBUS_BROADCAST_RULE,
    PORTAL_DBUS_NAMESPACE,
)


SYSTEM_BUS_SOCKET_PATH = "/run/dbus/system_bus_socket"
SYSTEM_BUS_ADDRESS = f"unix:path={SYSTEM_BUS_SOCKET_PATH}"
PROXY_READY_TIMEOUT_SECONDS = 5
PROXY_STOP_TIMEOUT_SECONDS = 2
PROXY_DIAGNOSTIC_MAX_CHARACTERS = 8_192


@dataclass(frozen=True)
class ProxyRuntime:
    """Runtime operations supplied by the stable sandbox facade."""

    fail: Callable[[str], NoReturn]
    require_root_owned_executable: Callable[[str, str], str]
    managed_subprocess_environment: Callable[[], dict[str, str]]
    validate_session_bus_address: Callable[[str], str]


def _close_socket(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass


def _bounded_proxy_stderr(proxy_process: subprocess.Popen | None) -> str:
    if proxy_process is None:
        return ""
    stderr_pipe = proxy_process.stderr
    if stderr_pipe is None or stderr_pipe.closed:
        return ""
    try:
        payload = stderr_pipe.read(PROXY_DIAGNOSTIC_MAX_CHARACTERS + 1)
    except (OSError, ValueError):
        payload = ""
    finally:
        try:
            stderr_pipe.close()
        except OSError:
            pass
    if not isinstance(payload, str):
        payload = payload.decode("utf-8", errors="replace")
    truncated = len(payload) > PROXY_DIAGNOSTIC_MAX_CHARACTERS
    payload = payload[:PROXY_DIAGNOSTIC_MAX_CHARACTERS]
    message = " ".join(payload.replace("\0", "\\0").split())
    if truncated:
        message = f"{message} [truncated]" if message else "[truncated]"
    return message


def _proxy_socket_problem(proxy_socket: str) -> str | None:
    try:
        socket_stat = os.lstat(proxy_socket)
    except OSError as exc:
        return f"socket is unavailable: {exc}"
    if stat.S_ISLNK(socket_stat.st_mode):
        return "socket path is a symlink"
    if not stat.S_ISSOCK(socket_stat.st_mode):
        return "socket path is not a socket"
    if socket_stat.st_uid != os.getuid():
        return (
            "socket has the wrong owner: "
            f"expected={os.getuid()} actual={socket_stat.st_uid}"
        )
    return None


def _unlink_proxy_socket(proxy_socket: str | None) -> None:
    if proxy_socket is None:
        return
    try:
        os.unlink(proxy_socket)
    except FileNotFoundError:
        pass
    except OSError:
        # Cleanup must not hide the payload status or an earlier failure.
        pass


def stop_dbus_proxy(
    proxy_process: subprocess.Popen | None,
    proxy_lifecycle: socket.socket | None,
    proxy_socket: str | None = None,
) -> str:
    """Stop one proxy and close every wrapper-owned resource.

    Closing the lifecycle socket is the normal xdg-dbus-proxy shutdown path.
    Signals are bounded fallbacks. Diagnostics are collected only after the
    child has been reaped so a pipe read cannot hold up sandbox teardown.
    """

    _close_socket(proxy_lifecycle)
    if proxy_process is not None and proxy_process.poll() is None:
        try:
            proxy_process.wait(timeout=PROXY_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                proxy_process.send_signal(signal.SIGTERM)
            except OSError:
                pass
            try:
                proxy_process.wait(timeout=PROXY_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    proxy_process.kill()
                except OSError:
                    pass
                try:
                    proxy_process.wait(timeout=PROXY_STOP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
    if proxy_process is not None and proxy_process.poll() is None:
        stderr_pipe = proxy_process.stderr
        if stderr_pipe is not None and not stderr_pipe.closed:
            try:
                stderr_pipe.close()
            except OSError:
                pass
        diagnostics = "xdg-dbus-proxy could not be reaped"
    else:
        diagnostics = _bounded_proxy_stderr(proxy_process)
    _unlink_proxy_socket(proxy_socket)
    return diagnostics


def _fail_started_proxy(
    message: str,
    proxy_process: subprocess.Popen | None,
    proxy_lifecycle: socket.socket | None,
    proxy_socket: str | None,
    *,
    runtime: ProxyRuntime,
) -> NoReturn:
    diagnostics = stop_dbus_proxy(
        proxy_process,
        proxy_lifecycle,
        proxy_socket,
    )
    suffix = f": {diagnostics}" if diagnostics else ""
    runtime.fail(f"{message}{suffix}")


def require_running_dbus_proxy(
    proxy_process: subprocess.Popen | None,
    proxy_socket: str | None,
    *,
    runtime: ProxyRuntime,
) -> None:
    """Fail closed if a configured proxy cannot serve the payload."""

    if proxy_process is None and proxy_socket is None:
        return
    if proxy_process is None or proxy_socket is None:
        runtime.fail("managed D-Bus proxy state is incomplete")
    status = proxy_process.poll()
    if status is not None:
        diagnostics = _bounded_proxy_stderr(proxy_process)
        suffix = f": {diagnostics}" if diagnostics else ""
        runtime.fail(
            "xdg-dbus-proxy exited before the managed payload launch "
            f"(status {status}){suffix}"
        )
    problem = _proxy_socket_problem(proxy_socket)
    if problem is not None:
        runtime.fail(
            "xdg-dbus-proxy socket became unsafe before the managed payload "
            f"launch: {proxy_socket}: {problem}"
        )


def require_running_dbus_proxies(
    proxies: list[
        tuple[subprocess.Popen | None, str | None, socket.socket | None]
    ],
    *,
    runtime: ProxyRuntime,
) -> None:
    for proxy_process, proxy_socket, _proxy_lifecycle in proxies:
        require_running_dbus_proxy(
            proxy_process,
            proxy_socket,
            runtime=runtime,
        )


def start_filtered_dbus_proxy(
    temp_root: str,
    proxy_name: str,
    bus_address: str,
    policy_arguments: tuple[str, ...],
    *,
    runtime: ProxyRuntime,
) -> tuple[subprocess.Popen | None, str | None, socket.socket | None]:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", proxy_name):
        runtime.fail(f"invalid D-Bus proxy name: {proxy_name or 'unset'}")
    if (
        not os.path.isabs(temp_root)
        or os.path.normpath(temp_root) != temp_root
        or os.path.realpath(temp_root) != temp_root
    ):
        runtime.fail(f"D-Bus proxy temporary root is unsafe: {temp_root}")
    try:
        temp_root_stat = os.lstat(temp_root)
    except OSError as exc:
        runtime.fail(f"D-Bus proxy temporary root is unavailable: {temp_root}: {exc}")
    if (
        stat.S_ISLNK(temp_root_stat.st_mode)
        or not stat.S_ISDIR(temp_root_stat.st_mode)
        or temp_root_stat.st_uid != os.getuid()
        or temp_root_stat.st_mode & 0o077
    ):
        runtime.fail(
            "D-Bus proxy temporary root must be a private directory owned by "
            f"the current user: {temp_root}"
        )

    proxy_binary = runtime.require_root_owned_executable(
        "xdg-dbus-proxy",
        "/usr/bin/xdg-dbus-proxy",
    )
    proxy_socket = os.path.join(temp_root, proxy_name)
    if os.path.lexists(proxy_socket):
        runtime.fail(
            "refusing to replace a pre-existing D-Bus proxy socket path: "
            f"{proxy_socket}"
        )

    readiness_parent = None
    readiness_child = None
    try:
        readiness_parent, readiness_child = socket.socketpair()
        readiness_parent.settimeout(PROXY_READY_TIMEOUT_SECONDS)
    except OSError as exc:
        _close_socket(readiness_parent)
        _close_socket(readiness_child)
        runtime.fail(f"cannot create the D-Bus proxy readiness channel: {exc}")

    proxy_argv = [
        proxy_binary,
        f"--fd={readiness_child.fileno()}",
        bus_address,
        proxy_socket,
        "--filter",
        *policy_arguments,
    ]
    try:
        proxy = subprocess.Popen(
            proxy_argv,
            cwd="/",
            env=runtime.managed_subprocess_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            pass_fds=[readiness_child.fileno()],
            text=True,
            errors="replace",
        )
    except OSError as exc:
        _close_socket(readiness_child)
        _close_socket(readiness_parent)
        runtime.fail(f"cannot start xdg-dbus-proxy: {exc}")
    except BaseException:
        _close_socket(readiness_child)
        _close_socket(readiness_parent)
        raise
    _close_socket(readiness_child)

    try:
        readiness = readiness_parent.recv(1)
    except TimeoutError:
        _fail_started_proxy(
            "xdg-dbus-proxy did not become ready before timeout",
            proxy,
            readiness_parent,
            proxy_socket,
            runtime=runtime,
        )
    except OSError as exc:
        _fail_started_proxy(
            f"cannot read xdg-dbus-proxy readiness: {exc}",
            proxy,
            readiness_parent,
            proxy_socket,
            runtime=runtime,
        )
    if readiness == b"":
        status = proxy.poll()
        status_suffix = f" (status {status})" if status is not None else ""
        _fail_started_proxy(
            "xdg-dbus-proxy closed its readiness channel without signaling "
            f"readiness{status_suffix}",
            proxy,
            readiness_parent,
            proxy_socket,
            runtime=runtime,
        )
    try:
        readiness_parent.settimeout(None)
    except OSError as exc:
        _fail_started_proxy(
            f"cannot preserve the xdg-dbus-proxy lifecycle channel: {exc}",
            proxy,
            readiness_parent,
            proxy_socket,
            runtime=runtime,
        )

    status = proxy.poll()
    if status is not None:
        _fail_started_proxy(
            "xdg-dbus-proxy exited immediately after signaling readiness "
            f"(status {status})",
            proxy,
            readiness_parent,
            proxy_socket,
            runtime=runtime,
        )
    problem = _proxy_socket_problem(proxy_socket)
    if problem is not None:
        _fail_started_proxy(
            "xdg-dbus-proxy did not create a safe sandbox socket at "
            f"{proxy_socket}: {problem}",
            proxy,
            readiness_parent,
            proxy_socket,
            runtime=runtime,
        )
    return proxy, proxy_socket, readiness_parent


def start_session_bus_proxy(
    temp_root: str,
    additional_talk_names: tuple[str, ...] = (),
    additional_own_names: tuple[str, ...] = (),
    *,
    required: bool = False,
    runtime: ProxyRuntime,
) -> tuple[subprocess.Popen | None, str | None, socket.socket | None]:
    raw_bus_address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not raw_bus_address:
        if required:
            runtime.fail(
                "DBUS_SESSION_BUS_ADDRESS is required for the managed "
                "secret-storage sandbox"
            )
        return None, None, None

    bus_address = runtime.validate_session_bus_address(raw_bus_address)
    policy_arguments = (
        f"--talk={NOTIFICATIONS_DBUS_NAME}",
        f"--see={PORTAL_DBUS_NAMESPACE}",
        f"--talk={PORTAL_DBUS_NAMESPACE}",
        f"--call={PORTAL_DBUS_NAMESPACE}=*",
        f"--broadcast={PORTAL_DBUS_NAMESPACE}={PORTAL_DBUS_BROADCAST_RULE}",
        *(f"--talk={bus_name}" for bus_name in additional_talk_names),
        *(f"--own={bus_name}" for bus_name in additional_own_names),
    )
    return start_filtered_dbus_proxy(
        temp_root,
        "session-bus",
        bus_address,
        policy_arguments,
        runtime=runtime,
    )


def start_system_bus_proxy(
    temp_root: str,
    additional_talk_names: tuple[str, ...] = (),
    *,
    required: bool = False,
    runtime: ProxyRuntime,
) -> tuple[subprocess.Popen | None, str | None, socket.socket | None]:
    try:
        system_bus_stat = os.lstat(SYSTEM_BUS_SOCKET_PATH)
    except FileNotFoundError:
        if required:
            runtime.fail(
                f"system D-Bus socket is unavailable: {SYSTEM_BUS_SOCKET_PATH}"
            )
        return None, None, None
    except OSError as exc:
        runtime.fail(
            f"cannot inspect system D-Bus socket: {SYSTEM_BUS_SOCKET_PATH}: {exc}"
        )
    if (
        stat.S_ISLNK(system_bus_stat.st_mode)
        or not stat.S_ISSOCK(system_bus_stat.st_mode)
    ):
        runtime.fail(
            "system D-Bus socket must be a socket, not a symlink: "
            f"{SYSTEM_BUS_SOCKET_PATH}"
        )

    policy_arguments = tuple(
        f"--talk={bus_name}" for bus_name in additional_talk_names
    )
    return start_filtered_dbus_proxy(
        temp_root,
        "system-bus",
        SYSTEM_BUS_ADDRESS,
        policy_arguments,
        runtime=runtime,
    )


def stop_dbus_proxies(
    proxies: list[
        tuple[subprocess.Popen | None, str | None, socket.socket | None]
    ],
) -> None:
    for proxy_process, proxy_socket, proxy_lifecycle in reversed(proxies):
        stop_dbus_proxy(proxy_process, proxy_lifecycle, proxy_socket)
