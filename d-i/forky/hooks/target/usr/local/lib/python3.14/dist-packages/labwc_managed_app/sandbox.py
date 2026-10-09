"""Stable Bubblewrap orchestration facade for managed applications."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack

import fcntl
import json
import os
import pathlib
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import uuid

from . import dbus_proxy
from . import identity
from . import mounts
from . import network_namespace
from . import compat_gpu
from .compat_protocol import CONTROL_DIRECTORY, ProtocolError, RequiredComponentError
from .bubblewrap import PRIVATE_PROCFS_ARGUMENTS, validate_private_procfs
from .browsers import EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE
from .commands import build_argv, normalize_managed_arguments, resolved_executable, validate_managed_arguments
from .environment import (
    build_environment,
    managed_database_state_root,
    resolve_home_relative_path,
)
from .profiles import (
    APPS,
    PERSISTENT_SANDBOX_CONFIG,
    TUTA_INTEGRATION_DIRECTORY_BINDS,
    WAYLAND_COMPAT_APPS,
    WAYLAND_COMPAT_RUNTIME_ROOT,
)
from .runtime import (
    ANGLE_GL_ARGS,
    MANAGED_CAGE_ENVIRONMENT,
    MANAGED_WAYLAND_OPENGL_ENVIRONMENT,
    current_user_home,
    current_user_name,
    current_user_runtime_socket,
    fail,
    managed_subprocess_environment,
    require_root_owned_executable,
    validate_absolute_path,
    validate_runtime_entry_name,
    validate_session_bus_address,
    wayland_ozone_args,
)

SYSTEM_BUS_SOCKET_PATH = dbus_proxy.SYSTEM_BUS_SOCKET_PATH
SYSTEM_BUS_ADDRESS = dbus_proxy.SYSTEM_BUS_ADDRESS
BWRAP_INFO_MAX_BYTES = network_namespace.BWRAP_INFO_MAX_BYTES
BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS = network_namespace.BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS
VETH_DNS_ADDRESS = network_namespace.VETH_DNS_ADDRESS
PRIVATE_TEMPORARY_DIRECTORIES = mounts.PRIVATE_TEMPORARY_DIRECTORIES
PRIVATE_X11_SOCKET_DIRECTORY = "/tmp/.X11-unix"
PRIVATE_XWAYLAND_BINARY = (
    f"{WAYLAND_COMPAT_RUNTIME_ROOT}/usr/bin/Xwayland"
)
PRIVATE_XWAYLAND_LIBRARY_DIRECTORY = (
    f"{WAYLAND_COMPAT_RUNTIME_ROOT}/usr/lib/x86_64-linux-gnu"
)
PRIVATE_XKBCOMP_SOURCE = f"{WAYLAND_COMPAT_RUNTIME_ROOT}/usr/bin/xkbcomp"
PRIVATE_XKBCOMP_OVERLAY_DIRECTORY = (
    f"{WAYLAND_COMPAT_RUNTIME_ROOT}/usr/lib/xkbcomp-overlay"
)
PRIVATE_XKBCOMP_DESTINATION = "/usr/bin/xkbcomp"
COMPATIBILITY_URI_OPENER = "/usr/local/libexec/labwc-compat-open-uri"
COMPATIBILITY_URI_OPENER_DESTINATIONS = (
    "/usr/bin/xdg-open", "/bin/xdg-open", "/usr/local/bin/xdg-open",
)
OUTER_WAYLAND_DISPLAY_ENVIRONMENT = (
    "LABWC_MANAGED_OUTER_WAYLAND_DISPLAY"
)
MANAGED_CODEX_HOME = identity.MANAGED_CODEX_HOME
MANAGED_CODEX_INSTALLATION_ID = identity.MANAGED_CODEX_INSTALLATION_ID
HOST_MACHINE_ID_PATH = identity.HOST_MACHINE_ID_PATH
MAX_HOST_MACHINE_ID_BYTES = identity.MAX_HOST_MACHINE_ID_BYTES
CHATGPT_LIFECYCLE_LOCK_NAME = "labwc-chatgpt-launch.lock"
CHATGPT_SINGLETON_PROFILE_PATH = ".config/Codex"
CHATGPT_SINGLETON_NAMES = (
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
)
MAX_SINGLETON_LINK_BYTES = 4096
SYNTHETIC_IDENTITY_DOMAIN = identity.SYNTHETIC_IDENTITY_DOMAIN


def _dbus_proxy_runtime() -> dbus_proxy.ProxyRuntime:
    return dbus_proxy.ProxyRuntime(
        fail=fail,
        require_root_owned_executable=require_root_owned_executable,
        managed_subprocess_environment=managed_subprocess_environment,
        validate_session_bus_address=validate_session_bus_address,
    )


def start_filtered_dbus_proxy(
    temp_root: str,
    proxy_name: str,
    bus_address: str,
    policy_arguments: tuple[str, ...],
) -> tuple[subprocess.Popen | None, str | None, socket.socket | None]:
    return dbus_proxy.start_filtered_dbus_proxy(
        temp_root,
        proxy_name,
        bus_address,
        policy_arguments,
        runtime=_dbus_proxy_runtime(),
    )


def start_session_bus_proxy(
    temp_root: str,
    additional_talk_names: tuple[str, ...] = (),
    additional_own_names: tuple[str, ...] = (),
    *,
    required: bool = False,
    compatibility: bool = False,
) -> tuple[subprocess.Popen | None, str | None, socket.socket | None]:
    return dbus_proxy.start_session_bus_proxy(
        temp_root,
        additional_talk_names,
        additional_own_names,
        required=required,
        compatibility=compatibility,
        runtime=_dbus_proxy_runtime(),
    )


def start_system_bus_proxy(
    temp_root: str,
    additional_talk_names: tuple[str, ...] = (),
    *,
    required: bool = False,
) -> tuple[subprocess.Popen | None, str | None, socket.socket | None]:
    return dbus_proxy.start_system_bus_proxy(
        temp_root,
        additional_talk_names,
        required=required,
        runtime=_dbus_proxy_runtime(),
    )


def require_running_dbus_proxy(
    proxy_process: subprocess.Popen | None,
    proxy_socket: str | None,
) -> None:
    dbus_proxy.require_running_dbus_proxy(
        proxy_process,
        proxy_socket,
        runtime=_dbus_proxy_runtime(),
    )


def require_running_dbus_proxies(
    proxies: list[
        tuple[subprocess.Popen | None, str | None, socket.socket | None]
    ],
) -> None:
    dbus_proxy.require_running_dbus_proxies(
        proxies,
        runtime=_dbus_proxy_runtime(),
    )


def stop_dbus_proxy(
    proxy_process: subprocess.Popen | None,
    proxy_lifecycle: socket.socket | None,
    proxy_socket: str | None = None,
) -> str:
    return dbus_proxy.stop_dbus_proxy(
        proxy_process,
        proxy_lifecycle,
        proxy_socket,
    )


def stop_dbus_proxies(
    proxies: list[
        tuple[subprocess.Popen | None, str | None, socket.socket | None]
    ],
) -> None:
    dbus_proxy.stop_dbus_proxies(proxies)


def _close_file_descriptor(file_descriptor: int | None) -> None:
    network_namespace.close_file_descriptor(file_descriptor)


def run_veth_sandbox(
    command: list[str], payload_argv: list[str], temp_root: str,
    inherited_fds: tuple[int, ...], *, app: str,
    pre_payload_check: Callable[[], None] | None = None,
    runtime_check: Callable[[], None] | None = None,
    cleanup_deadline: Callable[[], float] | None = None,
    cleanup_failure: Callable[[], None] | None = None,
    network: bool = True,
) -> int:
    validate_private_procfs(command)
    return network_namespace.run_veth_sandbox(
        command, payload_argv, temp_root, inherited_fds, app=app,
        pre_payload_check=pre_payload_check, runtime_check=runtime_check,
        cleanup_deadline=cleanup_deadline, cleanup_failure=cleanup_failure, network=network,
    )


add_dir_chain = mounts.add_dir_chain
add_private_tmpfs_mounts = mounts.add_private_tmpfs_mounts
add_optional_bind = mounts.add_optional_bind
add_gpu_device_binds = mounts.add_gpu_device_binds
add_video_device_binds = mounts.add_video_device_binds
add_system_bus_proxy_bind = mounts.add_system_bus_proxy_bind
validate_no_host_audio_device_binds = mounts.validate_no_host_audio_device_binds
validate_no_host_display_device_binds = mounts.validate_no_host_display_device_binds
validate_pure_privacy_device_isolation = mounts.validate_pure_privacy_device_isolation
resolve_home_relative_file = mounts.resolve_home_relative_file
resolve_optional_home_relative_directory = mounts.resolve_optional_home_relative_directory
add_home_directory_binds = mounts.add_home_directory_binds
add_optional_home_file_binds = mounts.add_optional_home_file_binds
add_absolute_directory_binds = mounts.add_absolute_directory_binds
add_absolute_directory_bind_pairs = mounts.add_absolute_directory_bind_pairs


def require_compatibility_dbus_proxies(proxy_processes) -> None:
    for process, _path, _lifecycle in proxy_processes:
        status = process.poll()
        if status is not None:
            raise RequiredComponentError(status)
    require_running_dbus_proxies(proxy_processes)


def add_persistent_directory_binds(
    command: list[str],
    home_dir: str,
    path_pairs: tuple[tuple[str, str], ...],
) -> None:
    for source_relative, destination_relative in path_pairs:
        source_path = persistent_app_directory(home_dir, source_relative)
        destination_path = resolve_home_relative_path(
            home_dir,
            destination_relative,
        )
        add_dir_chain(command, destination_path)
        command.extend(["--bind", source_path, destination_path])


def prepare_tuta_integration(home_dir: str) -> None:
    """Seed once without changing account data or exposing host launchers.

    The directory mounts permit GLib's atomic rename and persist Tuta's own
    no-integration blacklist. Never edit desktopConfig.json or guess its schema.
    """
    for source_relative, _destination in TUTA_INTEGRATION_DIRECTORY_BINDS:
        directory = persistent_app_directory(home_dir, source_relative)
        if os.path.realpath(directory) != directory:
            fail(f"Tuta integration path must not traverse symlinks: {directory}")
    for source_relative, destination_relative in (
        (".config/mimeapps.list", "config/mimeapps.list"),
        (".local/share/applications/tutanota-desktop.desktop", "applications/tutanota-desktop.desktop"),
    ):
        destination = resolve_home_relative_path(
            home_dir, ".local/state/tutanota-desktop/desktop-integration/" + destination_relative,
        )
        # Publish a complete seed with link(2), never replace an existing file:
        # simultaneous launches cannot overwrite Tuta's remembered selection.
        if not os.path.lexists(destination):
            source = os.path.join(home_dir, source_relative)
            if not os.path.lexists(source):
                continue  # Tuta can create it; do not fabricate an empty .desktop.
            source = resolve_home_relative_file(home_dir, source_relative)
            fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as handle:
                metadata = os.fstat(handle.fileno())
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                        or metadata.st_nlink != 1 or metadata.st_mode & 0o022):
                    fail(f"unsafe Tuta integration seed: {source}")
                content = handle.read(65537)
                if len(content) > 65536:
                    fail(f"Tuta integration seed is too large: {source}")
            fd, temporary = tempfile.mkstemp(prefix=".tuta-seed-", dir=os.path.dirname(destination))
            try:
                with os.fdopen(fd, "wb") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, destination, follow_symlinks=False)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temporary)
        fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                fail(f"unsafe Tuta integration state: {destination}")
            # Do not chmod a pre-existing inode: even a user-created hardlink
            # must not let this initialization modify an unrelated host file.



def filtered_resolv_conf() -> str:
    lines: list[str] = []
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("nameserver ") or line.startswith("options "):
                    lines.append(line)
    except OSError:
        pass
    if not lines:
        lines.append("nameserver 1.1.1.1")
    return "\n".join(lines) + "\n"


def veth_resolv_conf() -> str:
    from .network_client import resolver_configuration
    return resolver_configuration()


def create_veth_resolver_file(temp_root: str) -> str:
    validate_absolute_path("veth temporary root", temp_root)
    resolver_path = os.path.join(temp_root, "veth-resolv.conf")
    try:
        with open(resolver_path, "x", encoding="utf-8") as handle:
            handle.write(veth_resolv_conf())
        os.chmod(resolver_path, 0o600)
    except OSError as exc:
        fail(f"cannot create the private veth resolver policy: {exc}")
    return resolver_path


def reserve_outer_wayland_socket_name(
    command: list[str],
    temp_root: str,
    sandbox_runtime_dir: str,
    wayland_display: str,
) -> int:
    validate_absolute_path("Wayland socket reservation root", temp_root)
    validate_absolute_path("sandbox runtime directory", sandbox_runtime_dir)
    wayland_display = validate_runtime_entry_name(
        "outer Wayland socket",
        wayland_display,
    )
    reservation_path = os.path.join(temp_root, "outer-wayland-display.lock")
    sandbox_lock_path = os.path.join(
        sandbox_runtime_dir,
        f"{wayland_display}.lock",
    )
    open_flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    reservation_fd: int | None = None
    try:
        reservation_fd = os.open(reservation_path, open_flags, 0o600)
        os.fchmod(reservation_fd, 0o600)
        fcntl.flock(reservation_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        _close_file_descriptor(reservation_fd)
        fail(f"cannot reserve the outer Wayland socket name: {exc}")
    command.extend(["--bind", reservation_path, sandbox_lock_path])
    return reservation_fd


def pure_privacy_environment(app_name: str) -> dict[str, str]:
    env = build_environment(app_name, "launch")
    sandbox_home = "/home/user"
    sandbox_runtime = f"/run/user/{os.getuid()}"
    env.update(
        {
            "USER": "user",
            "LOGNAME": "user",
            "HOME": sandbox_home,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "XDG_RUNTIME_DIR": sandbox_runtime,
            "XDG_CONFIG_HOME": f"{sandbox_home}/.config",
            "XDG_CACHE_HOME": f"{sandbox_home}/.cache",
            "XDG_DATA_HOME": f"{sandbox_home}/.local/share",
            "XDG_STATE_HOME": f"{sandbox_home}/.local/state",
            "TMPDIR": f"{sandbox_home}/.tmp",
        }
    )
    env.update(MANAGED_WAYLAND_OPENGL_ENVIRONMENT)
    for name in tuple(env):
        if name.startswith(("VK_", "__VK_", "MESA_VK_")):
            env.pop(name)
    env.pop("COLORTERM", None)
    env.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
    if app_name == "mullvad-browser":
        env["MOZ_WEBRENDER"] = "1"
        env["MOZ_WEBRENDER_SOFTWARE"] = "1"
        env["MOZ_CRASHREPORTER_DISABLE"] = "1"
    return env


def pure_privacy_argv(app_name: str, extra_args: list[str]) -> list[str]:
    app = APPS[app_name]
    executable = resolved_executable(app_name, "pure-privacy")
    extra_args = normalize_managed_arguments(app_name, extra_args)
    validate_managed_arguments("pure-privacy", extra_args)
    if app_name in {"chromium", "microsoft-edge", "vivaldi"}:
        argv = [
            executable,
            *wayland_ozone_args(
                enable_features=("UseOzonePlatform",),
                disable_features=(
                    "InterestGroupStorage",
                    "TopicsAPI",
                    "VaapiVideoDecoder",
                    "VaapiVideoEncoder",
                    "UseChromeOSDirectVideoDecoder",
                    *(
                        (EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE,)
                        if app_name == "microsoft-edge"
                        else ()
                    ),
                ),
            ),
            "--ignore-gpu-blocklist",
            "--enable-gpu-rasterization",
            *ANGLE_GL_ARGS,
            "--disable-accelerated-2d-canvas",
            "--disable-accelerated-video-decode",
            "--disable-accelerated-video-encode",
            "--disable-background-networking",
            "--no-pings",
            "--no-default-browser-check",
            "--disable-crash-reporter",
            "--disable-breakpad",
            "--disable-sync",
        ]
        argv.extend(extra_args)
        return argv
    argv = [
        executable,
        *PERSISTENT_SANDBOX_CONFIG.get(app_name, {}).get("inner_sandbox_args", ()),
    ]
    argv.extend(app.get("privacy_args", app["args"]))
    argv.extend(extra_args)
    return argv


def bwrap_command(app_name: str, bwrap: str) -> list[str]:
    if app_name == "code":
        # Code's tools retain its existing application-specific execution
        # policy. Do not grant IDE execution rights to every browser payload.
        aa_exec = require_root_owned_executable("aa-exec", "/usr/bin/aa-exec")
        return [aa_exec, "--profile=labwc-app//code-bwrap", "--", bwrap]
    return [bwrap]


def run_pure_privacy(app_name: str, extra_args: list[str]) -> int:
    with ExitStack() as resources:
        return _run_pure_privacy(app_name, extra_args, resources)


def _run_pure_privacy(app_name: str, extra_args: list[str], resources: ExitStack) -> int:
    if not APPS[app_name].get("pure_privacy", False):
        fail(f"pure-privacy mode is not supported for {app_name}")
    from .network_client import network_enabled
    network_app = "qbittorrent-privacy" if app_name == "qbittorrent" else app_name
    online = APPS[app_name].get("privacy_share_net", True)
    if type(online) is not bool:
        fail(f"PurePrivacy network policy is invalid for {app_name}")
    online = online and network_enabled(network_app)

    bwrap = require_root_owned_executable("bubblewrap", "/usr/bin/bwrap")

    env = pure_privacy_environment(app_name)
    host_runtime_dir = env["XDG_RUNTIME_DIR"]
    sandbox_runtime_dir = env["XDG_RUNTIME_DIR"]
    home_dir = env["HOME"]
    validate_absolute_path("host XDG_RUNTIME_DIR", host_runtime_dir)
    validate_absolute_path("sandbox HOME", home_dir)

    argv = pure_privacy_argv(app_name, extra_args)
    wayland_display = env["WAYLAND_DISPLAY"]
    host_wayland_socket = current_user_runtime_socket("Wayland socket", wayland_display)
    sandbox_wayland_socket = os.path.join(sandbox_runtime_dir, wayland_display)

    temp_root = tempfile.mkdtemp(prefix=f"labwc-{app_name}-privacy-", dir=host_runtime_dir if os.path.isdir(host_runtime_dir) else None)
    resources.callback(shutil.rmtree, temp_root, ignore_errors=True)
    machine_id_path = os.path.join(temp_root, "machine-id")
    hostname_path = os.path.join(temp_root, "hostname")
    passwd_path = os.path.join(temp_root, "passwd")
    group_path = os.path.join(temp_root, "group")
    hosts_path = os.path.join(temp_root, "hosts")
    resolv_path = os.path.join(temp_root, "resolv.conf")
    nsswitch_path = os.path.join(temp_root, "nsswitch.conf")
    fake_machine_id = uuid.uuid4().hex
    fake_hostname = f"pure-{uuid.uuid4().hex[:12]}"
    with open(machine_id_path, "w", encoding="utf-8") as handle:
        handle.write(fake_machine_id + "\n")
    with open(hostname_path, "w", encoding="utf-8") as handle:
        handle.write(fake_hostname + "\n")
    with open(passwd_path, "w", encoding="utf-8") as handle:
        handle.write(f"user:x:{os.getuid()}:{os.getgid()}:Sandbox User:{home_dir}:/bin/sh\n")
    with open(group_path, "w", encoding="utf-8") as handle:
        handle.write(f"user:x:{os.getgid()}:\n")
    with open(hosts_path, "w", encoding="utf-8") as handle:
        handle.write(f"127.0.0.1 localhost\n::1 localhost\n127.0.1.1 {fake_hostname}\n")
    with open(resolv_path, "w", encoding="utf-8") as handle:
        handle.write(veth_resolv_conf() if online else "# Networking is disabled.\n")
    with open(nsswitch_path, "w", encoding="utf-8") as handle:
        handle.write(
            "passwd: files\n"
            "group: files\n"
            "shadow: files\n"
            "gshadow: files\n"
            "hosts: files dns\n"
            "networks: files dns\n"
            "protocols: files\n"
            "services: files\n"
            "ethers: files\n"
            "rpc: files\n"
            "netgroup: files\n"
        )

    proxy_process, proxy_socket, proxy_lifecycle = start_session_bus_proxy(
        temp_root,
        APPS[app_name].get("privacy_dbus_names", ()),
    )
    resources.callback(stop_dbus_proxy, proxy_process, proxy_lifecycle, proxy_socket)

    command = [
        *bwrap_command(app_name, bwrap),
        "--unshare-all",
        "--new-session",
        "--die-with-parent",
        "--clearenv",
        "--uid",
        str(os.getuid()),
        "--gid",
        str(os.getgid()),
        "--hostname",
        fake_hostname,
        "--cap-drop",
        "ALL",
        *PRIVATE_PROCFS_ARGUMENTS,
        "--dev",
        "/dev",
        "--chdir",
        home_dir,
    ]
    # The existing offline policies stay offline. Online policies obtain their
    # own kernel-veth lease and never share the host namespace.
    add_dir_chain(command, os.path.dirname(home_dir))
    command.extend(["--tmpfs", home_dir, "--chmod", "0700", home_dir])
    add_dir_chain(command, os.path.dirname(sandbox_runtime_dir))
    command.extend(["--dir", sandbox_runtime_dir])
    add_dir_chain(command, "/var/lib/dbus")
    command.extend(["--dir", "/etc"])
    add_private_tmpfs_mounts(command)

    for source, destination in (
        ("/usr", "/usr"),
        ("/bin", "/bin"),
        ("/lib", "/lib"),
    ):
        command.extend(["--ro-bind", source, destination])
    for source, destination in (
        ("/sbin", "/sbin"),
        ("/lib64", "/lib64"),
        ("/lib32", "/lib32"),
        ("/opt", "/opt"),
    ):
        add_optional_bind(command, "--ro-bind", source, destination)
    for path in (
        "/etc/ssl",
        "/etc/ca-certificates",
        "/etc/chromium",
        "/etc/chromium.d",
        "/etc/opt/edge",
        "/etc/vivaldi",
        "/etc/app-veth.json",
        "/etc/pki",
        "/etc/fonts",
        "/etc/alternatives",
        "/etc/ld.so.cache",
        "/etc/ld.so.conf",
        "/etc/ld.so.conf.d",
        "/etc/mime.types",
        "/etc/xdg",
    ):
        add_optional_bind(command, "--ro-bind", path, path)

    command.extend(
        [
            "--ro-bind",
            machine_id_path,
            "/etc/machine-id",
            "--ro-bind",
            machine_id_path,
            "/var/lib/dbus/machine-id",
            "--ro-bind",
            hostname_path,
            "/etc/hostname",
            "--ro-bind",
            passwd_path,
            "/etc/passwd",
            "--ro-bind",
            group_path,
            "/etc/group",
            "--ro-bind",
            hosts_path,
            "/etc/hosts",
            "--ro-bind",
            resolv_path,
            "/etc/resolv.conf",
            "--ro-bind",
            nsswitch_path,
            "/etc/nsswitch.conf",
            "--bind",
            host_wayland_socket,
            sandbox_wayland_socket,
        ]
    )

    if proxy_socket:
        bus_socket = os.path.join(sandbox_runtime_dir, "bus")
        command.extend(["--bind", proxy_socket, bus_socket])
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_socket}"
    else:
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)

    host_home_dir = current_user_home()
    for relative_path in APPS[app_name].get("privacy_home_ro_paths", ()):
        source_path = resolve_home_relative_file(host_home_dir, relative_path)
        destination_path = os.path.join(home_dir, relative_path)
        add_dir_chain(command, os.path.dirname(destination_path))
        command.extend(["--ro-bind", source_path, destination_path])

    if APPS[app_name].get("bind_workspace", False):
        workspace_source = os.path.join(host_home_dir, "Workspace")
        workspace_destination = os.path.join(home_dir, "Workspace")
        add_optional_bind(command, "--bind", workspace_source, workspace_destination)
        add_optional_bind(command, "--ro-bind", os.path.join(host_home_dir, ".gitconfig"), os.path.join(home_dir, ".gitconfig"))

    for directory in (
        env["XDG_CONFIG_HOME"],
        env["XDG_CACHE_HOME"],
        env["XDG_DATA_HOME"],
        env["XDG_STATE_HOME"],
        env["TMPDIR"],
    ):
        add_dir_chain(command, directory)

    validate_pure_privacy_device_isolation(app_name, command)
    for key, value in env.items():
        command.extend(["--setenv", key, value])
    validate_private_procfs(command)

    require_running_dbus_proxy(proxy_process, proxy_socket)
    return run_veth_sandbox(
        command,
        argv,
        temp_root,
        (),
        pre_payload_check=lambda: require_running_dbus_proxy(proxy_process, proxy_socket),
        # The dedicated persistent torrent wrapper owns peer-port
        # forwarding. A disposable profile needs outbound networking.
        app=network_app, network=online,
    )


def persistent_app_directory(
    home_dir: str,
    relative_path: str,
    *,
    preserve_existing_mode: bool = False,
) -> str:
    if not relative_path or relative_path.startswith("/") or ".." in pathlib.PurePosixPath(relative_path).parts:
        fail(f"invalid persistent sandbox path: {relative_path or 'unset'}")
    # Resolve the existing ancestry before creating anything: a symlinked
    # parent must not cause directory creation outside HOME before rejection.
    directory = resolve_home_relative_path(home_dir, relative_path)
    validate_absolute_path("persistent sandbox directory", directory)
    existed = os.path.lexists(directory)
    if not existed:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    home_real = os.path.realpath(home_dir)
    directory_real = os.path.realpath(directory)
    if os.path.commonpath((home_real, directory_real)) != home_real:
        fail(f"persistent sandbox directory escapes HOME: {directory}")
    directory_stat = os.lstat(directory)
    if not stat.S_ISDIR(directory_stat.st_mode) or stat.S_ISLNK(directory_stat.st_mode):
        fail(f"persistent sandbox path must be a real directory: {directory}")
    if directory_stat.st_uid != os.getuid():
        fail(f"persistent sandbox directory is not owned by the current user: {directory}")
    if not existed or not preserve_existing_mode:
        os.chmod(directory, 0o700)
    return directory


def persistent_runtime_directory(runtime_dir: str, entry_name: str) -> str:
    validate_absolute_path("persistent runtime directory root", runtime_dir)
    entry_name = validate_runtime_entry_name(
        "persistent runtime directory name",
        entry_name,
    )
    directory = os.path.join(runtime_dir, entry_name)
    validate_absolute_path("persistent runtime directory", directory)
    runtime_real = os.path.realpath(runtime_dir)
    directory_real = os.path.realpath(directory)
    if os.path.commonpath((runtime_real, directory_real)) != runtime_real:
        fail(f"persistent runtime directory escapes XDG_RUNTIME_DIR: {directory}")
    try:
        os.mkdir(directory, mode=0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        fail(f"cannot create persistent runtime directory {directory}: {exc}")
    try:
        directory_stat = os.lstat(directory)
    except OSError as exc:
        fail(f"cannot inspect persistent runtime directory {directory}: {exc}")
    if (
        stat.S_ISLNK(directory_stat.st_mode)
        or not stat.S_ISDIR(directory_stat.st_mode)
        or directory_stat.st_uid != os.getuid()
    ):
        fail(
            "persistent runtime directory must be a real directory owned by "
            f"the current user: {directory}"
        )
    os.chmod(directory, 0o700)
    return directory


def open_chatgpt_lifecycle_lock(runtime_dir: str) -> tuple[int, bool]:
    lock_path = os.path.join(runtime_dir, CHATGPT_LIFECYCLE_LOCK_NAME)
    validate_absolute_path("managed ChatGPT lifecycle lock", lock_path)
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        lock_fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        fail(f"cannot open managed ChatGPT lifecycle lock {lock_path}: {exc}")
    try:
        lock_stat = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(lock_stat.st_mode)
            or lock_stat.st_uid != os.getuid()
            or lock_stat.st_nlink != 1
        ):
            fail(
                "managed ChatGPT lifecycle lock must be a current-user-owned "
                f"regular file with one link: {lock_path}"
            )
        os.fchmod(lock_fd, 0o600)
        stale_cleanup_allowed = False
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stale_cleanup_allowed = True
        except BlockingIOError:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
        return lock_fd, stale_cleanup_allowed
    except BaseException:
        os.close(lock_fd)
        raise


def remove_stale_chatgpt_singletons(home_dir: str) -> None:
    profile_directory = persistent_app_directory(
        home_dir,
        CHATGPT_SINGLETON_PROFILE_PATH,
        preserve_existing_mode=True,
    )
    directory_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    try:
        directory_fd = os.open(profile_directory, directory_flags)
    except OSError as exc:
        fail(
            "cannot open managed ChatGPT profile directory for stale-lock "
            f"cleanup: {profile_directory}: {exc}"
        )
    try:
        stale_entries: set[str] = set()
        for entry_name in CHATGPT_SINGLETON_NAMES:
            try:
                entry_stat = os.stat(
                    entry_name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            except OSError as exc:
                fail(
                    "cannot inspect managed ChatGPT singleton entry "
                    f"{profile_directory}/{entry_name}: {exc}"
                )
            if (
                not stat.S_ISLNK(entry_stat.st_mode)
                or entry_stat.st_uid != os.getuid()
            ):
                fail(
                    "managed ChatGPT singleton entry must be a symlink owned "
                    f"by the current user: {profile_directory}/{entry_name}"
                )
            try:
                target = os.readlink(entry_name, dir_fd=directory_fd)
            except OSError as exc:
                fail(
                    "cannot read managed ChatGPT singleton entry "
                    f"{profile_directory}/{entry_name}: {exc}"
                )
            if (
                not target
                or len(os.fsencode(target)) > MAX_SINGLETON_LINK_BYTES
                or any(character in target for character in ("\n", "\r", "\0"))
            ):
                fail(
                    "managed ChatGPT singleton entry has an unsafe target: "
                    f"{profile_directory}/{entry_name}"
                )
            stale_entries.add(entry_name)
        for entry_name in (
            "SingletonSocket",
            "SingletonCookie",
            "SingletonLock",
        ):
            if entry_name not in stale_entries:
                continue
            try:
                os.unlink(entry_name, dir_fd=directory_fd)
            except OSError as exc:
                fail(
                    "cannot remove stale managed ChatGPT singleton entry "
                    f"{profile_directory}/{entry_name}: {exc}"
                )
    finally:
        os.close(directory_fd)


def add_runtime_bind(
    command: list[str],
    host_runtime_dir: str,
    sandbox_runtime_dir: str,
    relative_path: str,
    expected_kind: str,
    *,
    required: bool = False,
) -> None:
    relative = pathlib.PurePosixPath(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or ".." in relative.parts
        or "\0" in relative_path
    ):
        fail(f"invalid runtime bind path: {relative_path or 'unset'}")

    source_path = os.path.join(host_runtime_dir, relative_path)
    destination_path = os.path.join(sandbox_runtime_dir, relative_path)
    host_runtime_real = os.path.realpath(host_runtime_dir)
    source_real = os.path.realpath(source_path)
    if os.path.commonpath((host_runtime_real, source_real)) != host_runtime_real:
        fail(f"runtime bind escapes XDG_RUNTIME_DIR: {source_path}")
    try:
        source_stat = os.lstat(source_path)
    except FileNotFoundError:
        if required:
            fail(f"required runtime {expected_kind} is unavailable: {source_path}")
        return
    except OSError as exc:
        fail(f"cannot inspect runtime bind source {source_path}: {exc}")

    if stat.S_ISLNK(source_stat.st_mode):
        fail(f"runtime bind source must not be a symlink: {source_path}")
    if source_stat.st_uid != os.getuid():
        fail(f"runtime bind source must be owned by the current user: {source_path}")
    if expected_kind == "directory":
        if not stat.S_ISDIR(source_stat.st_mode):
            fail(f"runtime directory bind is not a directory: {source_path}")
    elif expected_kind == "socket":
        if not stat.S_ISSOCK(source_stat.st_mode):
            fail(f"runtime bind source is not a socket: {source_path}")
    else:
        fail(f"unsupported runtime bind kind: {expected_kind}")

    add_dir_chain(command, os.path.dirname(destination_path))
    command.extend(["--bind", source_path, destination_path])


def require_root_owned_directory(label: str, path: str) -> str:
    validate_absolute_path(label, path)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        fail(f"{label} is unavailable: {path}: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        fail(
            f"{label} must be a root-owned directory not writable by group "
            f"or others: {path}"
        )
    return path


def require_root_owned_regular_file(
    label: str,
    path: str,
    *,
    executable: bool = False,
) -> str:
    validate_absolute_path(label, path)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        fail(f"{label} is unavailable: {path}: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
        or (executable and not metadata.st_mode & stat.S_IXUSR)
    ):
        suffix = " executable" if executable else ""
        fail(
            f"{label} must be a root-owned regular{suffix} file not writable "
            f"by group or others: {path}"
        )
    return path


def add_system_usr_mount(command: list[str]) -> None:
    command.extend(["--ro-bind", "/usr", "/usr"])


def add_compatibility_uri_opener(command: list[str]) -> None:
    opener = require_root_owned_regular_file(
        "compatibility URI opener", COMPATIBILITY_URI_OPENER, executable=True,
    )
    for destination in COMPATIBILITY_URI_OPENER_DESTINATIONS:
        # /usr is already read-only. An absent optional PATH entry needs no
        # replacement and cannot be created there by the sandboxed application.
        # The packaged /usr/bin entry is required; cover /bin's separate bind
        # too, since the sandbox mounts merged-/usr aliases independently.
        if destination != COMPATIBILITY_URI_OPENER_DESTINATIONS[0] and not os.path.lexists(destination):
            continue
        require_root_owned_regular_file(
            "compatibility URI opener mount point", destination, executable=True,
        )
        command.extend(["--ro-bind", opener, destination])


def require_private_xkbcomp_overlay(path: str) -> str:
    if path != PRIVATE_XKBCOMP_OVERLAY_DIRECTORY:
        fail("private XKB compiler overlay is outside the managed runtime")
    if os.path.lexists(PRIVATE_XKBCOMP_DESTINATION):
        fail("system XKB compiler must remain absent outside the managed sandbox")
    require_root_owned_directory("private XKB compiler overlay", path)
    try:
        overlay_metadata = os.lstat(path)
        overlay_entries = tuple(sorted(entry.name for entry in os.scandir(path)))
    except OSError as exc:
        fail(f"private XKB compiler overlay is unavailable: {path}: {exc}")
    if stat.S_IMODE(overlay_metadata.st_mode) != 0o555:
        fail("private XKB compiler overlay must be mode 0555")
    if overlay_entries != ("xkbcomp",):
        fail(
            "private XKB compiler overlay must contain only the managed "
            "xkbcomp entry"
        )
    overlay_entry = os.path.join(path, "xkbcomp")
    require_root_owned_regular_file(
        "private XKB compiler",
        PRIVATE_XKBCOMP_SOURCE,
        executable=True,
    )
    require_root_owned_regular_file(
        "private XKB compiler overlay entry",
        overlay_entry,
        executable=True,
    )
    try:
        same_file = os.path.samefile(PRIVATE_XKBCOMP_SOURCE, overlay_entry)
    except OSError as exc:
        fail(f"cannot compare private XKB compiler overlay entry: {exc}")
    if not same_file:
        fail("private XKB compiler overlay entry must hard-link the private binary")
    return path


def add_private_xkbcomp_overlay(command: list[str], overlay_directory: str) -> None:
    overlay_directory = require_private_xkbcomp_overlay(overlay_directory)
    command.extend(
        [
            "--overlay-src",
            "/usr/bin",
            "--overlay-src",
            overlay_directory,
            "--ro-overlay",
            "/usr/bin",
        ]
    )


def _identity_runtime() -> identity.IdentityRuntime:
    return identity.IdentityRuntime(
        fail=fail,
        require_root_owned_regular_file=require_root_owned_regular_file,
        filtered_resolv_conf=filtered_resolv_conf,
        validate_absolute_path=validate_absolute_path,
    )


def create_synthetic_identity_files(
    temp_root: str,
    home_dir: str,
    *,
    resolv_conf: str | None = None,
    shell_path: str = "/bin/sh",
) -> dict[str, str]:
    return identity.create_synthetic_identity_files(
        temp_root,
        home_dir,
        resolv_conf=resolv_conf,
        shell_path=shell_path,
        runtime=_identity_runtime(),
    )


def add_synthetic_codex_installation_id_mount(
    command: list[str],
    installation_id_path: str,
) -> None:
    identity.add_synthetic_codex_installation_id_mount(
        command,
        installation_id_path,
        runtime=_identity_runtime(),
    )


def add_synthetic_identity_mounts(
    command: list[str],
    synthetic_identity: dict[str, str],
) -> None:
    identity.add_synthetic_identity_mounts(command, synthetic_identity)


def add_synthetic_sysfs_masks(command: list[str]) -> None:
    for path in (
        "/sys/block",
        "/sys/bus/scsi/devices",
        "/sys/class/block",
        "/sys/class/dmi/id",
        "/sys/class/net",
        "/sys/class/nvme",
        "/sys/devices/virtual/block",
        "/sys/devices/virtual/dmi/id",
        "/sys/devices/virtual/net",
        "/sys/firmware",
    ):
        if os.path.isdir(path) and not os.path.islink(path):
            command.extend(["--tmpfs", path])


def add_native_device_binds(command: list[str], sandbox: dict[str, object]) -> None:
    """Retain explicitly configured USB/game peripherals in private /dev.

    Bind accessible character nodes individually; never expose the host input
    directory or turn an application device flag into arbitrary path access.
    """
    patterns = []
    if sandbox.get("usb_devices", False):
        patterns.extend(("/dev/bus/usb/[0-9][0-9][0-9]/[0-9][0-9][0-9]", "/dev/hidraw[0-9]*"))
    if sandbox.get("game_devices", False):
        patterns.extend(("/dev/input/event[0-9]*", "/dev/input/js[0-9]*", "/dev/hidraw[0-9]*", "/dev/uinput"))
    for pattern in patterns:
        for path in sorted(pathlib.Path("/").glob(pattern[1:])):
            metadata = path.lstat()
            if stat.S_ISCHR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode) and os.access(path, os.R_OK | os.W_OK):
                add_dir_chain(command, str(path.parent))
                command.extend(["--dev-bind", str(path), str(path)])


def persistent_sandbox_argv(
    app_name: str,
    mode: str,
    extra_args: list[str],
    home_dir: str,
) -> list[str]:
    sandbox = PERSISTENT_SANDBOX_CONFIG.get(app_name)
    if sandbox is None:
        fail(f"persistent sandbox mode is not supported for {app_name}")

    argv = build_argv(app_name, mode, extra_args)
    argv[1:1] = [
        *(
            argument.replace("{HOME}", home_dir)
            for argument in sandbox["config_args"]
        ),
        *sandbox.get("inner_sandbox_args", ()),
    ]
    return argv


def freerdp_shared_folder(extra_args: list[str], home_dir: str) -> tuple[list[str], str | None]:
    """Bind only the menu's explicit shared folder, below HOME or user media."""
    arguments = list(extra_args)
    selected = None
    home_root = pathlib.Path(home_dir).resolve(strict=True)
    media_root = pathlib.Path("/run/media") / current_user_name()
    roots = [home_root]
    if media_root.is_dir() and not media_root.is_symlink():
        roots.append(media_root.resolve(strict=True))
    for index, argument in enumerate(arguments):
        if not argument.startswith("/drive:"):
            continue
        if selected is not None or not argument.startswith("/drive:Shared,"):
            fail("managed FreeRDP supports one explicitly selected Shared folder")
        source = argument.removeprefix("/drive:Shared,")
        if len(source) > 1024 or "," in source or any(ord(char) < 32 or ord(char) == 127 for char in source):
            fail("invalid FreeRDP shared folder")
        validate_absolute_path("FreeRDP shared folder", source)
        try:
            resolved = pathlib.Path(source).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            fail(f"FreeRDP shared folder is unavailable: {exc}")
        if (not any(resolved == root or root in resolved.parents for root in roots)
                or not resolved.is_dir() or not os.access(resolved, os.R_OK | os.X_OK)):
            fail("FreeRDP shared folder must be readable below HOME or the current user's media directory")
        selected = str(resolved)
        arguments[index] = "/drive:Shared,/rdp-shared"
    return arguments, selected


def select_persistent_sandbox_chdir(
    home_dir: str,
    sandbox: dict[str, object],
) -> str:
    fallback = os.path.join(home_dir, str(sandbox["chdir"]))
    validate_absolute_path("persistent sandbox working directory", fallback)
    if not os.path.isdir(fallback):
        fail(f"persistent sandbox working directory is unavailable: {fallback}")
    if not sandbox.get("preserve_working_directory", False):
        return fallback

    try:
        host_cwd = os.getcwd()
    except OSError as exc:
        fail(f"cannot resolve the physical working directory: {exc}")
    validate_absolute_path("physical working directory", host_cwd)
    if "\n" in host_cwd or "\r" in host_cwd:
        fail("physical working directory contains unsupported characters")
    if os.path.realpath(host_cwd) != host_cwd:
        fail(f"physical working directory must not traverse symlinks: {host_cwd}")

    allowed_roots = (
        *(
            os.path.join(home_dir, relative_path)
            for relative_path in sandbox.get("rw_bind_home_directories", ())
        ),
        *sandbox.get("rw_bind_paths", ()),
    )
    for allowed_root in allowed_roots:
        validate_absolute_path(
            "persistent sandbox writable working-directory root",
            allowed_root,
        )
        if allowed_root == "/" or os.path.normpath(allowed_root) != allowed_root:
            fail(
                "persistent sandbox writable working-directory root is unsafe: "
                f"{allowed_root}"
            )
        if host_cwd == allowed_root or host_cwd.startswith(f"{allowed_root}/"):
            return host_cwd
    return fallback


def prepare_document_portal(host_runtime_dir: str) -> None:
    """Activate the FUSE export before taking the sandbox's runtime snapshot."""
    try:
        result = subprocess.run(
            ["/usr/bin/busctl", "--user", "--timeout=10", "--json=short", "call",
             "org.freedesktop.portal.Documents", "/org/freedesktop/portal/documents",
             "org.freedesktop.portal.Documents", "GetMountPoint"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=12,
            env={**managed_subprocess_environment(), "XDG_RUNTIME_DIR": host_runtime_dir,
                 "DBUS_SESSION_BUS_ADDRESS": f"unix:path={host_runtime_dir}/bus"}, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"cannot activate ChatGPT's document portal: {exc}")
    if result.returncode or len(result.stdout) > 16384:
        fail("ChatGPT document portal is unavailable; check xdg-document-portal.service")
    try:
        value = json.loads(result.stdout)
        data = value["data"]
        if value["type"] != "ay" or not isinstance(data, list) or len(data) != 1:
            raise ValueError("invalid portal mount response")
        encoded = data[0]
        if (not isinstance(encoded, list) or not 1 <= len(encoded) <= 4096
                or any(type(number) is not int or not 0 <= number <= 255 for number in encoded)):
            raise ValueError("invalid portal mount bytes")
        mount_point = bytes(encoded).rstrip(b"\0").decode("utf-8")
        expected = os.path.join(host_runtime_dir, "doc")
        if mount_point not in {expected, expected + "/"}:
            raise ValueError("portal mount is outside the owned runtime")
    except (ValueError, KeyError, TypeError) as exc:
        fail(f"ChatGPT document portal returned an invalid mount point: {exc}")


def _run_persistent_sandbox(
    app_name: str,
    mode: str,
    extra_args: list[str],
    *,
    payload_argv_prefix: tuple[str, ...] = (),
    private_xwayland_binary: str | None = None,
    private_xkbcomp_overlay_directory: str | None = None,
    compatibility_instance=None,
) -> int:
    with ExitStack() as resources:
        return _run_persistent_sandbox_with_resources(
            app_name, mode, extra_args, resources,
            payload_argv_prefix=payload_argv_prefix,
            private_xwayland_binary=private_xwayland_binary,
            private_xkbcomp_overlay_directory=private_xkbcomp_overlay_directory,
            compatibility_instance=compatibility_instance,
        )


def _run_persistent_sandbox_with_resources(
    app_name: str,
    mode: str,
    extra_args: list[str],
    resources: ExitStack,
    *,
    payload_argv_prefix: tuple[str, ...] = (),
    private_xwayland_binary: str | None = None,
    private_xkbcomp_overlay_directory: str | None = None,
    compatibility_instance=None,
) -> int:
    sandbox = PERSISTENT_SANDBOX_CONFIG.get(app_name)
    if sandbox is None:
        fail(f"persistent sandbox mode is not supported for {app_name}")
    share_net = sandbox.get("share_net")
    from .network_client import network_enabled
    veth_enabled = network_enabled(app_name)
    if not isinstance(share_net, bool):
        fail(f"persistent sandbox network-sharing policy is invalid for {app_name}")
    if share_net and veth_enabled:
        fail(
            f"persistent sandbox cannot share the host network and use veth: {app_name}"
        )
    if private_xwayland_binary is not None and app_name not in WAYLAND_COMPAT_APPS:
        fail(f"private Xwayland is not permitted for {app_name}")
    if private_xwayland_binary is not None and (
        not payload_argv_prefix or payload_argv_prefix[-1] != "--"
    ):
        fail("private Xwayland requires a bounded lifecycle-helper prefix")
    if private_xwayland_binary is not None:
        if compatibility_instance is None:
            fail("private Xwayland requires a host instance lifetime coordinator")
        if private_xwayland_binary != PRIVATE_XWAYLAND_BINARY:
            fail("private Xwayland executable is outside the managed runtime")
        if private_xkbcomp_overlay_directory is None:
            fail("private Xwayland requires the managed XKB compiler")
        require_root_owned_regular_file(
            "private Xwayland executable",
            private_xwayland_binary,
            executable=True,
        )
    elif private_xkbcomp_overlay_directory is not None:
        fail("private XKB compiler is restricted to the private Xwayland sandbox")

    env = build_environment(app_name, mode)
    env.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
    home_dir = env["HOME"]
    host_runtime_dir = env["XDG_RUNTIME_DIR"]
    validate_absolute_path("sandbox HOME", home_dir)
    validate_absolute_path("host XDG_RUNTIME_DIR", host_runtime_dir)
    home_stat = os.lstat(home_dir)
    if stat.S_ISLNK(home_stat.st_mode) or not stat.S_ISDIR(home_stat.st_mode) or home_stat.st_uid != os.getuid():
        fail(f"sandbox HOME is not a directory owned by the current user: {home_dir}")
    freerdp_share = None
    if app_name == "freerdp":
        extra_args, freerdp_share = freerdp_shared_folder(extra_args, home_dir)
    if sandbox.get("prepare_document_portal", False):
        prepare_document_portal(host_runtime_dir)

    bwrap = require_root_owned_executable("bubblewrap", "/usr/bin/bwrap")

    persistent_directories = [
        persistent_app_directory(
            home_dir,
            relative_path,
            preserve_existing_mode=app_name == "chatgpt" or sandbox.get("preserve_persistent_modes", False),
        )
        for relative_path in sandbox["persistent_paths"]
    ]
    if app_name == "tutanota":
        prepare_tuta_integration(home_dir)
    shared_temp_directory = None
    shared_temp_entry = sandbox.get("shared_temp_directory")
    if shared_temp_entry is None and sandbox.get("shared_temp_directory_by_application", False):
        # Browser/Electron singleton sockets must remain reachable by later
        # launches using the same account profile, across private namespaces.
        # Only this application's private runtime directory is shared.
        shared_temp_entry = f"labwc-{app_name}-tmp"
    if shared_temp_entry is not None:
        if not isinstance(shared_temp_entry, str):
            fail(f"persistent sandbox shared temp name is invalid for {app_name}")
        shared_temp_directory = persistent_runtime_directory(
            host_runtime_dir,
            shared_temp_entry,
        )
        env["TMPDIR"] = shared_temp_directory
    sandbox_chdir = select_persistent_sandbox_chdir(home_dir, sandbox)
    wayland_display = env["WAYLAND_DISPLAY"]
    if private_xwayland_binary is not None:
        env.update(MANAGED_CAGE_ENVIRONMENT)
        for name in tuple(env):
            if name.startswith(("LD_", "QT_", "QML")) or name in {"ELECTRON_OZONE_PLATFORM_HINT", "GDK_BACKEND", "SDL_VIDEODRIVER", "CLUTTER_BACKEND"}:
                env.pop(name)
        env["WLR_XWAYLAND"] = "/usr/local/libexec/labwc-private-xwayland"
        env["LABWC_COMPAT_RUN_ID"] = compatibility_instance.run_id
        if type(sandbox.get("clipboard_bridge")) is not bool:
            fail("compatibility clipboard policy must be a trusted boolean")
        env["LABWC_COMPAT_CLIPBOARD"] = "1" if sandbox["clipboard_bridge"] else "0"
        env[OUTER_WAYLAND_DISPLAY_ENVIRONMENT] = wayland_display
    host_wayland_socket = current_user_runtime_socket("Wayland socket", wayland_display)

    temp_root = tempfile.mkdtemp(
        prefix=f"labwc-{app_name}-sandbox-",
        dir=host_runtime_dir if os.path.isdir(host_runtime_dir) else None,
    )
    resources.callback(shutil.rmtree, temp_root, ignore_errors=True)
    synthetic_identity = (
        create_synthetic_identity_files(
            temp_root,
            home_dir,
            resolv_conf=(
                veth_resolv_conf()
                if veth_enabled
                else None
            ),
            shell_path=env["SHELL"],
        )
        if sandbox.get("synthetic_identity", False)
        else None
    )
    veth_resolver_path = (
        create_veth_resolver_file(temp_root)
        if veth_enabled and synthetic_identity is None
        else None
    )
    proxy_processes: list[
        tuple[subprocess.Popen | None, str | None, socket.socket | None]
    ] = []
    session_proxy_socket = None
    system_proxy_socket = None
    try:
        (
            session_proxy_process,
            session_proxy_socket,
            session_proxy_lifecycle,
        ) = start_session_bus_proxy(
            temp_root,
            sandbox["dbus_names"],
            sandbox.get("dbus_own_names", ()),
            required=sandbox.get("require_session_bus", False),
            compatibility=private_xwayland_binary is not None,
        )
        if session_proxy_process is not None:
            proxy_processes.append(
                (
                    session_proxy_process,
                    session_proxy_socket,
                    session_proxy_lifecycle,
                )
            )
        if (
            "system_dbus_names" in sandbox
            or sandbox.get("require_system_bus", False)
        ):
            (
                system_proxy_process,
                system_proxy_socket,
                system_proxy_lifecycle,
            ) = start_system_bus_proxy(
                temp_root,
                sandbox.get("system_dbus_names", ()),
                required=sandbox.get("require_system_bus", False),
            )
            if system_proxy_process is not None:
                proxy_processes.append(
                    (
                        system_proxy_process,
                        system_proxy_socket,
                        system_proxy_lifecycle,
                    )
                )
    except BaseException:
        stop_dbus_proxies(proxy_processes)
        raise
    outer_wayland_lock_fd: int | None = None
    lifecycle_lock_fd: int | None = None
    try:
        argv = persistent_sandbox_argv(app_name, mode, extra_args, home_dir)
        command = [
            *bwrap_command(app_name, bwrap),
            "--unshare-all",
        ]
        if share_net:
            command.append("--share-net")
        command.extend(
            [
                "--new-session",
                "--die-with-parent",
                "--clearenv",
                "--uid",
                str(os.getuid()),
                "--gid",
                str(os.getgid()),
                "--cap-drop",
                "ALL",
                *(
                    (
                        "--hostname",
                        synthetic_identity["hostname_value"],
                    )
                    if synthetic_identity is not None
                    else ()
                ),
                *PRIVATE_PROCFS_ARGUMENTS,
                "--dev",
                "/dev",
                "--chdir",
                sandbox_chdir,
            ]
        )
        add_private_tmpfs_mounts(command)
        inherited_fds: tuple[int, ...] = ()
        if private_xwayland_binary is not None:
            command.extend(
                [
                    "--dir",
                    PRIVATE_X11_SOCKET_DIRECTORY,
                    "--chmod",
                    "01777",
                    PRIVATE_X11_SOCKET_DIRECTORY,
                ]
            )

        add_dir_chain(command, "/etc")
        add_dir_chain(command, "/opt")
        add_dir_chain(command, os.path.dirname(home_dir))

        add_system_usr_mount(command)
        if private_xkbcomp_overlay_directory is not None:
            add_private_xkbcomp_overlay(command, private_xkbcomp_overlay_directory)
        if compatibility_instance is not None:
            command.extend(["--bind", str(compatibility_instance.directory), CONTROL_DIRECTORY])
        for source, destination in (
            ("/bin", "/bin"),
            ("/lib", "/lib"),
            ("/sys", "/sys"),
        ):
            command.extend(["--ro-bind", source, destination])
        for source in sandbox["ro_bind_paths"]:
            add_optional_bind(command, "--ro-bind", source, source)
        for source, destination in (
            ("/sbin", "/sbin"),
            ("/lib64", "/lib64"),
            ("/lib32", "/lib32"),
        ):
            add_optional_bind(command, "--ro-bind", source, destination)
        synthetic_etc_paths = {
            "/etc/group",
            "/etc/hostname",
            "/etc/hosts",
            "/etc/machine-id",
            "/etc/nsswitch.conf",
            "/etc/passwd",
            "/etc/resolv.conf",
        }
        for path in (
            "/etc/alternatives",
            "/etc/app-veth.json",
            "/etc/ca-certificates",
            "/etc/chromium",
            "/etc/chromium.d",
            "/etc/fonts",
            "/etc/group",
            "/etc/hosts",
            "/etc/ld.so.cache",
            "/etc/ld.so.conf",
            "/etc/ld.so.conf.d",
            "/etc/localtime",
            "/etc/machine-id",
            "/etc/mime.types",
            "/etc/nsswitch.conf",
            "/etc/passwd",
            "/etc/pki",
            "/etc/resolv.conf",
            "/etc/ssl",
            "/etc/xdg",
        ):
            if synthetic_identity is not None and path in synthetic_etc_paths:
                continue
            if veth_resolver_path is not None and path == "/etc/resolv.conf":
                continue
            add_optional_bind(command, "--ro-bind", path, path)
        if synthetic_identity is not None:
            add_synthetic_identity_mounts(command, synthetic_identity)
            add_synthetic_sysfs_masks(command)
        elif veth_resolver_path is not None:
            command.extend(
                ["--ro-bind", veth_resolver_path, "/etc/resolv.conf"]
            )

        command.extend(["--tmpfs", home_dir, "--chmod", "0700", home_dir])
        # Mount private integration parents first, then the application's genuine
        # persistent account directory. Reversing this order would hide its data.
        add_persistent_directory_binds(
            command, home_dir, sandbox.get("integration_directory_binds", ()),
        )
        for directory in persistent_directories:
            add_dir_chain(command, directory)
            command.extend(["--bind", directory, directory])
        add_persistent_directory_binds(
            command,
            home_dir,
            sandbox.get("persistent_directory_binds", ()),
        )
        preserve_chatgpt_home_modes = app_name == "chatgpt"
        for relative_path in sandbox.get("ro_bind_home_paths", ()):
            source_path = resolve_home_relative_file(
                home_dir,
                relative_path,
                require_private_mode=not preserve_chatgpt_home_modes,
            )
            destination_path = os.path.join(home_dir, relative_path)
            add_dir_chain(command, os.path.dirname(destination_path))
            command.extend(["--ro-bind", source_path, destination_path])
        for relative_path in sandbox.get("rw_bind_home_paths", ()):
            source_path = resolve_home_relative_file(
                home_dir,
                relative_path,
                writable=True,
            )
            destination_path = os.path.join(home_dir, relative_path)
            add_dir_chain(command, os.path.dirname(destination_path))
            command.extend(["--bind", source_path, destination_path])
        add_optional_home_file_binds(
            command,
            home_dir,
            sandbox.get("ro_bind_home_optional_files", ()),
            require_private_mode=not preserve_chatgpt_home_modes,
        )
        add_home_directory_binds(
            command,
            home_dir,
            sandbox.get("ro_bind_home_directories", ()),
            "--ro-bind",
            require_private_mode=not preserve_chatgpt_home_modes,
        )
        add_home_directory_binds(
            command,
            home_dir,
            sandbox.get("rw_bind_home_directories", ()),
            "--bind",
        )
        if sandbox.get("user_media_directory", False):
            mounts.add_user_media_directory_bind(command, current_user_name())
        add_absolute_directory_binds(
            command,
            sandbox.get("ro_bind_directory_paths", ()),
            "--ro-bind",
        )
        add_absolute_directory_binds(
            command,
            sandbox.get("rw_bind_paths", ()),
            "--bind",
        )
        if freerdp_share is not None:
            command.extend(["--dir", "/rdp-shared", "--bind", freerdp_share, "/rdp-shared"])
        if sandbox.get("database_state", False):
            database_state_root = managed_database_state_root(
                app_name,
                current_user_name(),
            )
            if database_state_root is None:
                fail(f"managed database state is unavailable for {app_name}")
            add_absolute_directory_binds(
                command,
                (database_state_root,),
                "--bind",
            )
        add_absolute_directory_bind_pairs(
            command,
            sandbox.get("rw_bind_directory_pairs", ()),
            "--bind",
        )
        runtime_socket_paths = sandbox["runtime_sockets"]
        sandbox_runtime_dir = f"/run/user/{os.getuid()}"
        add_dir_chain(command, os.path.dirname(sandbox_runtime_dir))
        command.extend(["--dir", sandbox_runtime_dir, "--chmod", "0700", sandbox_runtime_dir])
        if shared_temp_directory is not None:
            add_dir_chain(command, shared_temp_directory)
            command.extend(
                [
                    "--bind",
                    shared_temp_directory,
                    shared_temp_directory,
                ]
            )
        command.extend(["--bind", host_wayland_socket, os.path.join(sandbox_runtime_dir, wayland_display)])

        for relative_runtime_path in sandbox["runtime_directories"]:
            add_runtime_bind(
                command,
                host_runtime_dir,
                sandbox_runtime_dir,
                relative_runtime_path,
                "directory",
                required=relative_runtime_path in sandbox.get("required_runtime_directories", ()),
            )
        for relative_runtime_path in runtime_socket_paths:
            add_runtime_bind(
                command,
                host_runtime_dir,
                sandbox_runtime_dir,
                relative_runtime_path,
                "socket",
                required=relative_runtime_path
                in sandbox.get("required_runtime_sockets", ()),
            )

        add_video_device_binds(command, sandbox.get("camera_devices", False))
        add_native_device_binds(command, sandbox)
        if private_xwayland_binary is not None:
            try:
                selected_gpu = compat_gpu.add_device_binds(command, mode)
            except (ProtocolError, OSError, ValueError):
                fail("compatibility render-device identity or selection failed")
            if selected_gpu == "intel":
                for name in ("GBM_BACKEND", "NVD_BACKEND", "__GLX_VENDOR_LIBRARY_NAME", "__NV_PRIME_RENDER_OFFLOAD"):
                    env.pop(name, None)
                env["LIBVA_DRIVER_NAME"] = "iHD"
            else:
                from .profiles import NVIDIA_ACCELERATION_ENV
                env.update(NVIDIA_ACCELERATION_ENV)
        else:
            add_gpu_device_binds(command, mode)

        if session_proxy_socket:
            sandbox_bus_socket = os.path.join(sandbox_runtime_dir, "bus")
            command.extend(["--bind", session_proxy_socket, sandbox_bus_socket])
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={sandbox_bus_socket}"
        else:
            env.pop("DBUS_SESSION_BUS_ADDRESS", None)

        if system_proxy_socket:
            add_system_bus_proxy_bind(command, system_proxy_socket)
            env["DBUS_SYSTEM_BUS_ADDRESS"] = SYSTEM_BUS_ADDRESS
        else:
            env.pop("DBUS_SYSTEM_BUS_ADDRESS", None)

        if synthetic_identity is not None:
            env.update(
                {
                    "USER": "developer",
                    "LOGNAME": "developer",
                    "HOSTNAME": synthetic_identity["hostname_value"],
                }
            )
        validate_no_host_audio_device_binds(app_name, command)
        validate_no_host_display_device_binds(app_name, command)

        if private_xwayland_binary is not None:
            outer_wayland_lock_fd = reserve_outer_wayland_socket_name(
                command,
                temp_root,
                sandbox_runtime_dir,
                wayland_display,
            )
        if app_name == "chatgpt":
            if synthetic_identity is None:
                fail("ChatGPT requires a synthetic identity")
            lifecycle_lock_fd, stale_cleanup_allowed = (
                open_chatgpt_lifecycle_lock(host_runtime_dir)
            )
            if stale_cleanup_allowed:
                remove_stale_chatgpt_singletons(home_dir)
                fcntl.flock(lifecycle_lock_fd, fcntl.LOCK_SH)
            # CODEX_HOME owns its persistent installation_id just as auth.json.
            # Do not shadow it with a different identity for the GUI process.
        for key, value in env.items():
            command.extend(["--setenv", key, value])
        validate_private_procfs(command)
        if compatibility_instance is not None:
            require_compatibility_dbus_proxies(proxy_processes)
        else:
            require_running_dbus_proxies(proxy_processes)
        if compatibility_instance is not None and app_name == "discord":
            # Apply after all system/vendor mounts, including merged-/usr
            # aliases, so no later directory bind restores a browser launcher.
            add_compatibility_uri_opener(command)
        if app_name == "chatgpt":
            from .network_client import codex_socket_arguments, podman_socket_arguments
            command.extend(podman_socket_arguments())
            command.extend(codex_socket_arguments())
        payload_argv = [*payload_argv_prefix, *argv]
        return run_veth_sandbox(
                command,
                payload_argv,
                temp_root,
                inherited_fds,
                pre_payload_check=lambda: (require_compatibility_dbus_proxies(proxy_processes)
                    if compatibility_instance else require_running_dbus_proxies(proxy_processes)),
                runtime_check=(lambda: (compatibility_instance.service(), require_compatibility_dbus_proxies(proxy_processes) if compatibility_instance.outcome is None else None)) if compatibility_instance else None,
                app=app_name, network=veth_enabled,
                cleanup_deadline=compatibility_instance.begin_cleanup if compatibility_instance else None,
                cleanup_failure=(lambda: setattr(compatibility_instance, "cleanup_failed", True)) if compatibility_instance else None,
            )
    finally:
        _close_file_descriptor(outer_wayland_lock_fd)
        if lifecycle_lock_fd is not None:
            os.close(lifecycle_lock_fd)
        if compatibility_instance is not None:
            if not dbus_proxy.stop_dbus_proxies(proxy_processes, deadline=compatibility_instance.begin_cleanup()):
                compatibility_instance.cleanup_failed = True
        else:
            stop_dbus_proxies(proxy_processes)


def run_persistent_sandbox(app_name: str, mode: str, extra_args: list[str]) -> int:
    if app_name in WAYLAND_COMPAT_APPS:
        fail(
            f"{app_name} must use the dedicated native-Wayland compatibility entrypoint"
        )
    return _run_persistent_sandbox(app_name, mode, extra_args)
