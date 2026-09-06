"""Systemd session ownership for long-running managed applications."""

from __future__ import annotations

import os

from .runtime import (
    current_user_home,
    current_user_name,
    current_user_runtime_dir,
    current_user_runtime_socket,
    fail,
    managed_subprocess_environment,
    require_root_owned_executable,
    validate_runtime_entry_name,
    validate_session_bus_address,
)

MANAGED_APP_PATH = "/usr/local/bin/labwc-managed-app"
WAYLAND_COMPAT_MANAGED_APP_PATH = "/usr/local/bin/labwc-managed-wayland-compat-app"
SYSTEMD_RUN_PATH = "/usr/bin/systemd-run"
BITWARDEN_SESSION_UNIT_MARKER = "LABWC_MANAGED_APP_SESSION_UNIT"
WAYLAND_COMPAT_SESSION_UNIT_MARKER = (
    "LABWC_MANAGED_WAYLAND_COMPAT_SESSION_UNIT"
)
WAYLAND_COMPAT_SESSION_UNIT_METADATA = {
    "discord": ("Discord", "labwc-discord-cage"),
    "zoom": ("Zoom", "labwc-zoom-cage"),
}


def bitwarden_session_unit_argv(
    systemd_run: str,
    mode: str,
    extra_args: list[str],
) -> list[str]:
    return [
        systemd_run,
        "--user",
        "--quiet",
        "--collect",
        "--service-type=exec",
        "--description=Managed Bitwarden desktop client",
        "--property=After=labwc-session.target labwc-kwallet-portal.service",
        "--property=Requires=labwc-session.target labwc-kwallet-portal.service",
        "--property=Requisite=labwc-session.target labwc-kwallet-portal.service",
        "--property=PartOf=labwc-session.target labwc-kwallet-portal.service",
        "--property=KillMode=mixed",
        "--property=TimeoutStopSec=20s",
        "--property=SyslogIdentifier=labwc-bitwarden",
        f"--setenv={BITWARDEN_SESSION_UNIT_MARKER}=1",
        "--",
        MANAGED_APP_PATH,
        mode,
        "bitwarden",
        *extra_args,
    ]


def managed_session_unit_environment(application_label: str) -> dict[str, str]:
    if os.environ.get("LABWC_SESSION_OWNER") != "desktop":
        fail(f"{application_label} requires the managed Labwc desktop session")
    home_dir = current_user_home()
    user_name = current_user_name()
    runtime_dir = current_user_runtime_dir()
    session_bus_address = validate_session_bus_address(
        os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    )
    environment = managed_subprocess_environment()
    environment.update(
        {
            "HOME": home_dir,
            "USER": user_name,
            "LOGNAME": user_name,
            "XDG_RUNTIME_DIR": runtime_dir,
            "DBUS_SESSION_BUS_ADDRESS": session_bus_address,
            "SYSTEMD_COLORS": "0",
        }
    )
    return environment


def bitwarden_session_unit_environment() -> dict[str, str]:
    return managed_session_unit_environment("Bitwarden")


def wayland_compat_session_unit_argv(
    systemd_run: str,
    app_name: str,
    mode: str,
    extra_args: list[str],
) -> list[str]:
    metadata = WAYLAND_COMPAT_SESSION_UNIT_METADATA.get(app_name)
    if metadata is None:
        fail(f"managed compatibility session unit rejected {app_name}")
    display_name, syslog_identifier = metadata
    return [
        systemd_run,
        "--user",
        "--quiet",
        "--collect",
        "--service-type=exec",
        f"--description=Managed {display_name} Cage compatibility session",
        "--property=After=labwc-session.target",
        "--property=Requires=labwc-session.target",
        "--property=Requisite=labwc-session.target",
        "--property=PartOf=labwc-session.target",
        "--property=KillMode=mixed",
        "--property=TimeoutStopSec=20s",
        f"--property=SyslogIdentifier={syslog_identifier}",
        f"--setenv={WAYLAND_COMPAT_SESSION_UNIT_MARKER}=1",
        "--",
        WAYLAND_COMPAT_MANAGED_APP_PATH,
        mode,
        app_name,
        *extra_args,
    ]


def wayland_compat_session_unit_environment() -> dict[str, str]:
    environment = managed_session_unit_environment("Zoom/Discord Cage")
    wayland_display = validate_runtime_entry_name(
        "WAYLAND_DISPLAY",
        os.environ.get("WAYLAND_DISPLAY", ""),
    )
    current_user_runtime_socket("Wayland socket", wayland_display)
    environment["WAYLAND_DISPLAY"] = wayland_display
    return environment


def redirect_bitwarden_to_session_unit(mode: str, extra_args: list[str]) -> None:
    marker = os.environ.get(BITWARDEN_SESSION_UNIT_MARKER, "")
    if marker == "1":
        return
    if marker:
        fail(f"{BITWARDEN_SESSION_UNIT_MARKER} has an invalid value")

    systemd_run = require_root_owned_executable("systemd-run", SYSTEMD_RUN_PATH)
    argv = bitwarden_session_unit_argv(systemd_run, mode, extra_args)
    environment = bitwarden_session_unit_environment()
    try:
        os.execve(systemd_run, argv, environment)
    except OSError as exc:
        fail(f"failed to create the managed Bitwarden session unit: {exc}")


def redirect_wayland_compat_to_session_unit(
    app_name: str,
    mode: str,
    extra_args: list[str],
) -> None:
    marker = os.environ.get(WAYLAND_COMPAT_SESSION_UNIT_MARKER, "")
    if marker == "1":
        return
    if marker:
        fail(f"{WAYLAND_COMPAT_SESSION_UNIT_MARKER} has an invalid value")

    systemd_run = require_root_owned_executable("systemd-run", SYSTEMD_RUN_PATH)
    argv = wayland_compat_session_unit_argv(
        systemd_run,
        app_name,
        mode,
        extra_args,
    )
    environment = wayland_compat_session_unit_environment()
    try:
        os.execve(systemd_run, argv, environment)
    except OSError as exc:
        fail(
            "failed to create the managed Zoom/Discord Cage session unit: "
            f"{exc}"
        )
