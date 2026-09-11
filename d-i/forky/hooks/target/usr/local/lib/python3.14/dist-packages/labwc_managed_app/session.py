"""Systemd session ownership for long-running managed applications."""

from __future__ import annotations

import os

from .integrity import system_owner

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
CHATGPT_SESSION_PATH = "/usr/local/libexec/labwc-chatgpt-session"
WAYLAND_COMPAT_MANAGED_APP_PATH = "/usr/local/bin/labwc-managed-wayland-compat-app"
SYSTEMD_RUN_PATH = "/usr/bin/systemd-run"
BITWARDEN_SESSION_UNIT_MARKER = "LABWC_MANAGED_APP_SESSION_UNIT"
NATIVE_SESSION_UNIT_MARKER = "LABWC_NATIVE_APP_SESSION_UNIT"
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


def managed_session_unit_environment(
    application_label: str, *, require_session_owner: bool = True,
) -> dict[str, str]:
    if require_session_owner and os.environ.get("LABWC_SESSION_OWNER") != "desktop":
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


def redirect_native_from_private_users(
    app_name: str, mode: str, extra_args: list[str],
) -> None:
    """Re-enter the host user manager before checking host-owned app data.

    The compositor's filesystem sandbox implicitly creates a user namespace.
    In it root and supplementary group ownership cannot be distinguished.
    Do not weaken all the later ownership checks or alter that sandbox: ask
    the same user's manager to execute the existing wrapper outside it.
    --pipe/--wait retain the caller's output capture and exit-status semantics,
    including ChatGPT's dedicated, private log runner.
    """
    marker = os.environ.get(NATIVE_SESSION_UNIT_MARKER, "")
    if marker not in {"", "1"}:
        fail(f"{NATIVE_SESSION_UNIT_MARKER} has an invalid value")
    private_users = system_owner()[0] != 0
    if marker == "1":
        if private_users:
            fail("managed application user manager still hides host ownership")
        return
    # Tuta's safeStorage must not race the Secret Service provider even when
    # started from a terminal that is already outside the compositor namespace.
    if not private_users and app_name != "tutanota":
        return
    systemd_run = require_root_owned_executable("systemd-run", SYSTEMD_RUN_PATH)
    environment = managed_session_unit_environment(
        app_name, require_session_owner=False,
    )
    wayland_display = validate_runtime_entry_name(
        "WAYLAND_DISPLAY", os.environ.get("WAYLAND_DISPLAY", ""),
    )
    current_user_runtime_socket("Wayland socket", wayland_display)
    dependencies = "labwc-session.target"
    if app_name == "tutanota":
        dependencies += " labwc-kwallet-portal.service"
    # The generic entrypoint attaches the generic AppArmor profile when started
    # by systemd. ChatGPT must retain its dedicated profile and private pipes;
    # a tiny fixed-purpose reentry stub performs that explicit transition.
    command = [MANAGED_APP_PATH, mode, app_name, *extra_args]
    if app_name == "chatgpt":
        command = [CHATGPT_SESSION_PATH, mode, *extra_args]
    argv = [
        systemd_run, "--user", "--quiet", "--collect", "--pipe", "--wait",
        "--service-type=exec", "--expand-environment=no",
        f"--description=Managed {app_name} desktop client",
        f"--property=After={dependencies}",
        f"--property=Requires={dependencies}",
        f"--property=Requisite={dependencies}",
        f"--property=PartOf={dependencies}",
        "--property=KillMode=mixed", "--property=TimeoutStopSec=20s",
        f"--working-directory={os.getcwd()}",
        f"--setenv={NATIVE_SESSION_UNIT_MARKER}=1",
        f"--setenv=WAYLAND_DISPLAY={wayland_display}",
        "--", *command,
    ]
    try:
        os.execve(systemd_run, argv, environment)
    except OSError as exc:
        fail(f"failed to create the managed {app_name} session unit: {exc}")
