"""Systemd session ownership for long-running managed applications."""

from __future__ import annotations

import os
from pathlib import Path
import re
import uuid

from .recovery import assert_launch_allowed, restart_token
from .integrity import system_owner
from .environment import (
    CHATGPT_DEVOPS_ENVIRONMENT_RESERVED, CHATGPT_FORBIDDEN_AMBIENT_ENVIRONMENT,
)

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


def _session_unit(prefix: str) -> str:
    if re.fullmatch(r"labwc-[a-z0-9-]+", prefix) is None:
        fail("invalid managed session unit prefix")
    return f"{prefix}-{uuid.uuid4().hex}.service"


def _consume_session_marker(name: str, prefix: str) -> bool:
    """Accept reentry only inside the expected manager-owned service cgroup.

    The flag is a loop guard, not authority by itself. Consume it before any
    payload is created so subsequently launched applications get new services.
    """
    marker = os.environ.pop(name, "")
    if not marker:
        return False
    if marker != "1":
        fail(f"{name} has an invalid value")
    try:
        with Path("/proc/self/cgroup").open(encoding="ascii") as stream:
            membership = stream.read(65537)
    except (OSError, UnicodeError) as exc:
        fail(f"cannot validate managed session cgroup: {exc}")
    pattern = re.escape(prefix) + r"-[0-9a-f]{32}\.service"
    if len(membership) <= 65536:
        for line in membership.splitlines():
            fields = line.split(":", 2)
            if (len(fields) == 3 and fields[1] in {"", "name=systemd"}
                    and re.fullmatch(pattern, fields[2].rsplit("/", 1)[-1])):
                return True
    fail(f"{name} is set outside its managed session service")


def bitwarden_session_unit_argv(
    systemd_run: str,
    mode: str,
    extra_args: list[str],
    environment: dict[str, str] | None = None,
) -> list[str]:
    assert_launch_allowed()
    return [
        systemd_run,
        "--user",
        "--quiet",
        "--collect",
        "--service-type=exec",
        "--expand-environment=no",
        "--property=StandardInput=null",
        "--property=StandardOutput=journal",
        "--property=StandardError=journal",
        "--description=Managed Bitwarden desktop client",
        "--unit=" + _session_unit("labwc-bitwarden"),
        "--property=After=labwc-session.target labwc-kwallet-portal.service",
        "--property=Requires=labwc-session.target labwc-kwallet-portal.service",
        "--property=Requisite=labwc-session.target labwc-kwallet-portal.service",
        "--property=PartOf=labwc-session.target labwc-kwallet-portal.service",
        "--slice=app.slice",
        "--property=ExitType=cgroup",
        "--property=KillMode=control-group",
        "--setenv=LABWC_SESSION_APP=1",
        "--property=TimeoutStopSec=20s",
        "--property=SendSIGKILL=yes",
        "--property=Restart=no",
        "--property=UMask=0077",
        "--property=SyslogIdentifier=labwc-bitwarden",
        f"--setenv={BITWARDEN_SESSION_UNIT_MARKER}=1",
        "--setenv=LABWC_SESSION_RESTORE=" + restart_token([MANAGED_APP_PATH, mode, "bitwarden", *extra_args]),
        f"--working-directory={os.getcwd()}",
        *(f"--setenv={name}" for name in sorted(environment or {})),
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
            "LABWC_SESSION_OWNER": "desktop",
        }
    )
    return environment


def bitwarden_session_unit_environment() -> dict[str, str]:
    environment = managed_session_unit_environment("Bitwarden")
    wayland_display = validate_runtime_entry_name(
        "WAYLAND_DISPLAY", os.environ.get("WAYLAND_DISPLAY", ""),
    )
    current_user_runtime_socket("Wayland socket", wayland_display)
    environment["WAYLAND_DISPLAY"] = wayland_display
    return environment


def wayland_compat_session_unit_argv(
    systemd_run: str,
    app_name: str,
    mode: str,
    extra_args: list[str],
    environment: dict[str, str] | None = None,
) -> list[str]:
    metadata = WAYLAND_COMPAT_SESSION_UNIT_METADATA.get(app_name)
    if metadata is None:
        fail(f"managed compatibility session unit rejected {app_name}")
    display_name, syslog_identifier = metadata
    assert_launch_allowed()
    return [
        systemd_run,
        "--user",
        "--quiet",
        "--collect",
        "--service-type=exec",
        "--expand-environment=no",
        "--property=StandardInput=null",
        "--property=StandardOutput=journal",
        "--property=StandardError=journal",
        f"--description=Managed {display_name} Cage compatibility session",
        "--unit=" + _session_unit(f"labwc-compat-{app_name}"),
        "--property=After=labwc-session.target",
        "--property=Requires=labwc-session.target",
        "--property=Requisite=labwc-session.target",
        "--property=PartOf=labwc-session.target",
        "--slice=app.slice",
        "--property=ExitType=cgroup",
        "--property=KillMode=control-group",
        "--setenv=LABWC_SESSION_APP=1",
        "--property=TimeoutStopSec=20s",
        "--property=SendSIGKILL=yes",
        "--property=Restart=no",
        "--property=UMask=0077",
        f"--property=SyslogIdentifier={syslog_identifier}",
        f"--setenv={WAYLAND_COMPAT_SESSION_UNIT_MARKER}=1",
        "--setenv=LABWC_SESSION_NESTED=1",
        "--setenv=LABWC_SESSION_RESTORE=" + restart_token([WAYLAND_COMPAT_MANAGED_APP_PATH, mode, app_name, *extra_args]),
        f"--working-directory={os.getcwd()}",
        *(f"--setenv={name}" for name in sorted(environment or {})),
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
    if _consume_session_marker(BITWARDEN_SESSION_UNIT_MARKER, "labwc-bitwarden"):
        return

    systemd_run = require_root_owned_executable("systemd-run", SYSTEMD_RUN_PATH)
    environment = bitwarden_session_unit_environment()
    argv = bitwarden_session_unit_argv(systemd_run, mode, extra_args, environment)
    try:
        os.execve(systemd_run, argv, environment)
    except OSError as exc:
        fail(f"failed to create the managed Bitwarden session unit: {exc}")


def redirect_wayland_compat_to_session_unit(
    app_name: str,
    mode: str,
    extra_args: list[str],
) -> None:
    if _consume_session_marker(WAYLAND_COMPAT_SESSION_UNIT_MARKER, f"labwc-compat-{app_name}"):
        return

    systemd_run = require_root_owned_executable("systemd-run", SYSTEMD_RUN_PATH)
    environment = wayland_compat_session_unit_environment()
    argv = wayland_compat_session_unit_argv(
        systemd_run,
        app_name,
        mode,
        extra_args,
        environment,
    )
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
    Only ChatGPT retains its private output pipes. Other applications use
    independent journal streams, never the panel/compositor stdout descriptors.
    """
    marker = _consume_session_marker(NATIVE_SESSION_UNIT_MARKER, f"labwc-native-{app_name}")
    private_users = system_owner()[0] != 0
    if marker:
        if private_users:
            fail("managed application user manager still hides host ownership")
        return
    assert_launch_allowed()
    # Every native launch gets its own service, including terminal launches.
    # Tuta additionally waits for the Secret Service provider below.
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
    environment["WAYLAND_DISPLAY"] = wayland_display
    environment["LABWC_SESSION_APP"] = "1"
    environment["LABWC_SESSION_RESTORE"] = restart_token([MANAGED_APP_PATH, mode, app_name, *extra_args])
    if app_name == "chatgpt":
        if (os.environ.get("DEVOPS_DE_ACTIVE") == "1"
                and os.environ.get("DEVOPS_DE_ENVIRONMENT_READY") == "1"):
            for name, value in os.environ.items():
                if name in CHATGPT_DEVOPS_ENVIRONMENT_RESERVED or name in {"LABWC_SESSION_APP", "LABWC_SESSION_RESTORE"}:
                    continue
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
                    fail("ChatGPT received an invalid environment variable name")
                # Reject loader/shell injection before execing systemd-run,
                # not just later in the host-side application validator.
                if (name in CHATGPT_FORBIDDEN_AMBIENT_ENVIRONMENT
                        or name.startswith(("LD_", "BASH_FUNC_"))):
                    if value:
                        fail(f"ChatGPT launcher forbids ambient environment variable: {name}")
                    continue
                # Account/bus identity is always the validated mapping above.
                environment[name] = value
        else:
            # Do not inherit stale activation markers from the user manager.
            # The host-side launcher will apply the authoritative fragment.
            environment["DEVOPS_DE_ACTIVE"] = "0"
            environment["DEVOPS_DE_ENVIRONMENT_READY"] = "0"
    startup_dependencies = dependencies
    if app_name == "chatgpt":
        startup_dependencies += " codex-app-server.socket codex-app-server-proxy.service"
    argv = [
        systemd_run, "--user", "--quiet", "--collect",
        *(["--pipe", "--wait"] if app_name == "chatgpt" else [
            "--property=StandardInput=null",
            "--property=StandardOutput=journal",
            "--property=StandardError=journal",
            f"--property=SyslogIdentifier=labwc-{app_name}",
        ]),
        "--slice=app.slice",
        "--service-type=exec", "--expand-environment=no",
        f"--description=Managed {app_name} desktop client",
        "--unit=" + _session_unit(f"labwc-native-{app_name}"),
        f"--property=After={startup_dependencies}",
        f"--property=Requires={startup_dependencies}",
        f"--property=Requisite={startup_dependencies}",
        f"--property=PartOf={dependencies}",
        "--property=ExitType=cgroup",
        "--property=KillMode=control-group", "--property=TimeoutStopSec=20s",
        "--property=SendSIGKILL=yes", "--property=Restart=no", "--property=UMask=0077",
        f"--working-directory={os.getcwd()}",
        f"--setenv={NATIVE_SESSION_UNIT_MARKER}=1",
        # Values, including optional credentials, are not exposed in argv.
        *(f"--setenv={name}" for name in sorted(environment)
          if name != NATIVE_SESSION_UNIT_MARKER),
        "--", *command,
    ]
    try:
        os.execve(systemd_run, argv, environment)
    except OSError as exc:
        fail(f"failed to create the managed {app_name} session unit: {exc}")
