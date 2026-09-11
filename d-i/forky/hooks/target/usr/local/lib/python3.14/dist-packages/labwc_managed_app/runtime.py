"""Shared deterministic primitives for labwc-managed-app."""

from __future__ import annotations

import os
import pathlib
import pwd
import re
import stat
import sys
from typing import NoReturn

from .events import emit
from .integrity import system_owner

MANAGED_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
MANAGED_DEFAULTS_PATH = pathlib.Path("/etc/default/labwc-desktop")
MAX_MANAGED_DEFAULTS_BYTES = 65536
MANAGED_DEFAULTS_KEYS = {
    "LABWC_INTEL_ACCELERATION_AVAILABLE",
    "LABWC_MANAGED_APP_DEFAULT_EXEC",
    "LABWC_NVIDIA_ACCELERATION_AVAILABLE",
}
WAYLAND_OZONE_ARGS = (
    "--ozone-platform=wayland",
    "--enable-wayland-ime",
    "--disable-vulkan",
    "--disable-skia-graphite",
    "--use-webgpu-adapter=opengles",
)
WAYLAND_CSD_FEATURE = "WaylandWindowDecorations"
VULKAN_DISABLE_FEATURES = (
    "Vulkan",
    "DefaultANGLEVulkan",
    "VulkanFromANGLE",
    "ForceEnableWebGpuInterop",
)
MAX_RUNTIME_ENTRY_NAME = 128
ANGLE_GL_ARGS = (
    "--use-gl=angle",
    "--use-angle=gl",
)
MANAGED_NO_VULKAN_ENVIRONMENT = {
    "ANGLE_DEFAULT_PLATFORM": "gl",
    "GSK_RENDERER": "opengl",
    "GDK_DISABLE": "vulkan",
    "QT_OPENGL": "desktop",
    "QSG_RHI_BACKEND": "opengl",
    "SDL_RENDER_DRIVER": "opengl",
    "WGPU_BACKEND": "gl",
}
MANAGED_WAYLAND_OPENGL_ENVIRONMENT = {
    "GDK_BACKEND": "wayland",
    "MOZ_ENABLE_WAYLAND": "1",
    "QT_QPA_PLATFORM": "wayland",
    **MANAGED_NO_VULKAN_ENVIRONMENT,
}
MANAGED_CAGE_COMPOSITOR_ENVIRONMENT = {
    "WLR_RENDERER": "gles2",
    "WLR_WL_OUTPUTS": "1",
    "WLR_NO_HARDWARE_CURSORS": "1",
}
MANAGED_CAGE_ENVIRONMENT = {
    **MANAGED_WAYLAND_OPENGL_ENVIRONMENT,
    **MANAGED_CAGE_COMPOSITOR_ENVIRONMENT,
}

def wayland_ozone_args(
    *,
    enable_features: tuple[str, ...] = ("UseOzonePlatform",),
    disable_features: tuple[str, ...] = (),
) -> list[str]:
    args = [*WAYLAND_OZONE_ARGS]
    enabled_features = tuple(
        feature
        for feature in dict.fromkeys(enable_features)
        if feature != WAYLAND_CSD_FEATURE
    )
    disabled_features = tuple(
        dict.fromkeys(
            (*disable_features, WAYLAND_CSD_FEATURE, *VULKAN_DISABLE_FEATURES)
        )
    )
    if enabled_features:
        args.append(f"--enable-features={','.join(enabled_features)}")
    if disabled_features:
        args.append(f"--disable-features={','.join(disabled_features)}")
    return args



def fail(message: str) -> NoReturn:
    emit("failed", level="error", reason=message)
    print(f"fatal: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_absolute_path(label: str, value: str) -> None:
    if not value or not value.startswith("/"):
        fail(f"{label} must be an absolute path: {value or 'unset'}")


def current_user_account() -> pwd.struct_passwd:
    try:
        return pwd.getpwuid(os.getuid())
    except KeyError:
        fail(f"current desktop account is unavailable for UID {os.getuid()}")


def current_user_home() -> str:
    account = current_user_account()
    home_dir = account.pw_dir
    validate_absolute_path("current desktop HOME", home_dir)
    try:
        metadata = os.lstat(home_dir)
    except OSError as exc:
        fail(f"current desktop HOME is unavailable: {home_dir}: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        fail(f"current desktop HOME is not a directory owned by the current user: {home_dir}")
    return home_dir


def current_user_name() -> str:
    account_name = current_user_account().pw_name
    if not account_name:
        fail("current desktop account has no user name")
    return account_name


def current_user_runtime_dir() -> str:
    runtime_dir = f"/run/user/{os.getuid()}"
    try:
        metadata = os.lstat(runtime_dir)
    except OSError as exc:
        fail(f"current desktop runtime directory is unavailable: {runtime_dir}: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        fail(
            "current desktop runtime directory must be a private directory "
            f"owned by the current user: {runtime_dir}"
        )
    return runtime_dir


def validate_runtime_entry_name(label: str, value: str) -> str:
    if (
        not value
        or len(value) > MAX_RUNTIME_ENTRY_NAME
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is None
        or value in {".", ".."}
    ):
        fail(f"{label} is invalid: {value or 'unset'}")
    return value


def current_user_runtime_socket(label: str, entry_name: str) -> str:
    runtime_dir = current_user_runtime_dir()
    entry_name = validate_runtime_entry_name(label, entry_name)
    path = os.path.join(runtime_dir, entry_name)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        fail(f"{label} is unavailable: {path}: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISSOCK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        fail(f"{label} must be a socket owned by the current user: {path}")
    return path


def validate_session_bus_address(raw_value: str) -> str:
    bus_address = (raw_value or "").strip()
    if not bus_address:
        fail("DBUS_SESSION_BUS_ADDRESS must not be empty when a session bus is expected")
    if len(bus_address) > 4096:
        fail("DBUS_SESSION_BUS_ADDRESS is unexpectedly long")
    if any(character in bus_address for character in ("\n", "\r", "\0")):
        fail("DBUS_SESSION_BUS_ADDRESS contains unsupported control characters")
    if ";" in bus_address:
        fail("DBUS_SESSION_BUS_ADDRESS must contain a single unix:path transport")

    match = re.fullmatch(r"unix:path=([^,]+)(?:,[^=]+=[^,]+)*", bus_address)
    if match is None:
        fail(f"DBUS_SESSION_BUS_ADDRESS must use a local unix:path transport: {bus_address}")

    expected_path = current_user_runtime_socket("DBUS session bus", "bus")
    if match.group(1) != expected_path:
        fail(
            "DBUS_SESSION_BUS_ADDRESS must reference the current desktop "
            f"session bus: {expected_path}"
        )
    return bus_address


def require_root_owned_executable(label: str, path: str) -> str:
    validate_absolute_path(label, path)
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        fail(f"{label} is unavailable: {path}: {exc}")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        # A user-service filesystem namespace omits the host-root UID map.
        # Use the same validated /usr ownership anchor as package bootstrap;
        # never special-case or blindly trust the numeric overflow UID.
        or metadata.st_uid != system_owner()[0]
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(path, os.X_OK)
    ):
        fail(f"{label} must be a root-owned executable regular file: {path}")
    return path


def managed_subprocess_environment() -> dict[str, str]:
    return {
        "PATH": MANAGED_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
