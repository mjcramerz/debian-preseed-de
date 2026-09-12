"""Package-agnostic desktop launchers with user-manager owned lifetimes.

A separate transient service is used even when launched from a terminal. The
service is created by the host user manager, outside the compositor namespace. Native toolkit selection uses environment variables;
Chromium switches are passed only to Electron payloads.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import uuid

from .environment import (
    acceleration_availability_from_defaults, load_managed_defaults,
    validate_acceleration_mode,
)
from .recovery import assert_launch_allowed, restart_token
from .integrity import system_owner
from .profiles import INTEL_ACCELERATION_ENV, NVIDIA_ACCELERATION_ENV
from .runtime import (
    ANGLE_GL_ARGS, MANAGED_DEFAULTS_PATH, MANAGED_PATH,
    MANAGED_WAYLAND_OPENGL_ENVIRONMENT, current_user_home, current_user_name,
    current_user_runtime_dir, current_user_runtime_socket, fail,
    require_root_owned_executable, validate_runtime_entry_name,
    validate_session_bus_address, wayland_ozone_args,
)

WRAPPERS = {
    "electron": "/usr/local/bin/labwc-electron-app",
    "wayland": "/usr/local/bin/labwc-wayland-app",
}
# Never let the user manager reintroduce X11, a different GPU or loader hooks.
UNSET_ENVIRONMENT = (
    "DISPLAY", "XAUTHORITY", "LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH",
    "PYTHONPATH", "PYTHONHOME", "BASH_ENV", "ENV", "ELECTRON_RUN_AS_NODE",
    "ELECTRON_NO_SANDBOX", "NODE_OPTIONS", "GBM_BACKEND", "DRI_PRIME",
    "LIBVA_DRIVER_NAME", "NVD_BACKEND", "__GLX_VENDOR_LIBRARY_NAME",
    "__NV_PRIME_RENDER_OFFLOAD", "__VK_LAYER_NV_optimus", "VK_ICD_FILENAMES",
    "VK_DRIVER_FILES", "MESA_LOADER_DRIVER_OVERRIDE", "LIBGL_ALWAYS_SOFTWARE",
)
ELECTRON_UNSAFE_SWITCHES = {
    "--no-sandbox", "--no-zygote", "--single-process", "--disable-gpu-sandbox",
    "--disable-namespace-sandbox", "--disable-seccomp-filter-sandbox",
    "--in-process-gpu",
}


def electron_command(arguments: list[str]) -> list[str]:
    """Retain vendor arguments/field-code expansions, without policy overrides."""
    for argument in arguments[1:]:
        if argument.split("=", 1)[0] in ELECTRON_UNSAFE_SWITCHES:
            fail(f"Electron launcher refuses sandbox-disabling switch: {argument.split('=', 1)[0]}")
    # Do not pretend flags appended to a shell script become Electron switches.
    if Path(arguments[0]).name in {"sh", "bash", "dash", "zsh", "fish"}:
        fail("Electron desktop Exec must name the executable, not a shell -c script")
    enforced = [
        *wayland_ozone_args(enable_features=("UseOzonePlatform", "WebRTCPipeWireCapturer")),
        *ANGLE_GL_ARGS, "--enable-gpu-rasterization", "--disable-setuid-sandbox",
    ]
    controlled = {item.split("=", 1)[0] for item in enforced}
    remaining = []
    extra_features: dict[str, list[str]] = {"--enable-features": [], "--disable-features": []}
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            remaining.extend(arguments[index:])
            break
        key, separator, value = argument.partition("=")
        if key in controlled:
            if key in extra_features:
                if not separator and index + 1 < len(arguments):
                    index += 1
                    value = arguments[index]
                extra_features[key].extend(filter(None, value.split(",")))
            elif not separator and key in {"--ozone-platform", "--use-gl", "--use-angle", "--use-webgpu-adapter"}:
                if index + 1 >= len(arguments):
                    fail(f"Electron switch is missing its value: {key}")
                index += 1
        else:
            remaining.append(argument)
        index += 1
    for index, argument in enumerate(enforced):
        key, separator, value = argument.partition("=")
        if key in extra_features:
            features = [*value.split(","), *extra_features[key]]
            # The repository's Wayland/OpenGL policy wins over vendor Vulkan
            # toggles; unrelated vendor feature selections are retained.
            if key == "--enable-features":
                features = [f for f in features if "Vulkan" not in f and f != "WaylandWindowDecorations"]
            else:
                features = [f for f in features if f not in {"UseOzonePlatform", "WebRTCPipeWireCapturer"}]
            enforced[index] = key + "=" + ",".join(dict.fromkeys(features))
    return [arguments[0], *enforced, *remaining]


def unwrap_env(arguments: list[str], environment: dict[str, str]) -> list[str]:
    """Support the usual desktop 'env NAME=value command' without a shell."""
    if Path(arguments[0]).name != "env":
        return arguments
    remaining = arguments[1:]
    while remaining:
        item = remaining[0]
        if item == "--":
            return remaining[1:]
        if "=" not in item:
            if item.startswith("-"):
                fail("desktop env options are unsupported; use NAME=value assignments")
            return remaining
        name, value = item.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            fail("desktop env assignment has an invalid name")
        if name in UNSET_ENVIRONMENT or name.startswith(("LD_", "BASH_FUNC_", "VK_", "__VK_")):
            fail(f"desktop env assignment conflicts with launch isolation: {name}")
        if name in {"HOME", "USER", "LOGNAME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}:
            fail(f"desktop env assignment cannot replace the account identity: {name}")
        environment[name] = value
        remaining = remaining[1:]
    return []


def session_environment() -> dict[str, str]:
    home = current_user_home()
    user = current_user_name()
    runtime = current_user_runtime_dir()
    display = validate_runtime_entry_name("WAYLAND_DISPLAY", os.environ.get("WAYLAND_DISPLAY", ""))
    current_user_runtime_socket("Wayland socket", display)
    bus = validate_session_bus_address(os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""))
    environment = {"PATH": MANAGED_PATH, "LANG": "C.UTF-8"}
    for name, value in os.environ.items():
        if name in {"LANG", "LANGUAGE", "TZ", "TERM", "COLORTERM", "XDG_ACTIVATION_TOKEN", "QT_QPA_PLATFORMTHEME", "GTK_THEME"} or name.startswith("LC_"):
            environment[name] = value
    environment.update({
        "HOME": home, "USER": user, "LOGNAME": user,
        "XDG_RUNTIME_DIR": runtime, "WAYLAND_DISPLAY": display,
        "DBUS_SESSION_BUS_ADDRESS": bus,
        "XDG_CONFIG_HOME": f"{home}/.config", "XDG_CACHE_HOME": f"{home}/.cache",
        "XDG_DATA_HOME": f"{home}/.local/share", "XDG_STATE_HOME": f"{home}/.local/state",
        "XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "labwc:wlroots",
        "XDG_SESSION_DESKTOP": "labwc", "LABWC_SESSION_OWNER": "desktop",
        "SDL_VIDEODRIVER": "wayland", "SDL_VIDEO_DRIVER": "wayland",
        "CLUTTER_BACKEND": "wayland", "ELECTRON_OZONE_PLATFORM_HINT": "wayland",
        **MANAGED_WAYLAND_OPENGL_ENVIRONMENT,
    })
    return environment


def transient_argv(kind: str, mode: str, arguments: list[str], environment: dict[str, str]) -> list[str]:
    assert_launch_allowed()
    environment["LABWC_SESSION_APP"] = "1"
    environment["LABWC_SESSION_RESTORE"] = restart_token([WRAPPERS[kind], mode, "--", *arguments])
    label = re.sub(r"[^A-Za-z0-9_-]", "-", Path(arguments[0]).name)[:48] or "app"
    unit = f"labwc-{kind}-{label}-{uuid.uuid4().hex}.service"
    # A terminal is an interactive host administration boundary: implicit
    # PrivateUsers from filesystem/IPC isolation would break sudo/pkexec.
    # Keep its previous host access, but give each window its own cgroup.
    terminal = kind == "wayland" and arguments[0] in {
        "/usr/bin/foot", "/usr/bin/kitty", "/usr/bin/x-terminal-emulator",
    }
    return [
        "/usr/bin/systemd-run", "--user", "--quiet", "--collect",
        "--service-type=exec", "--expand-environment=no", "--slice=app.slice",
        f"--unit={unit}", f"--description=Labwc {kind} application: {label}",
        "--property=Requisite=labwc-session.target", "--property=After=labwc-session.target",
        "--property=PartOf=labwc-session.target", "--property=ExitType=cgroup",
        "--property=KillMode=control-group", "--property=TimeoutStopSec=20s",
        "--property=SendSIGKILL=yes", "--property=Restart=no", "--property=UMask=0077",
        # Do not force NNP/seccomp before package AppArmor -> bwrap
        # transitions. Electron and Bubblewrap set NNP inside their sandboxes.
        "--property=StandardInput=null", "--property=StandardOutput=journal",
        "--property=StandardError=journal", f"--property=SyslogIdentifier=labwc-{label}",
        "--property=LimitCORE=0", "--property=NoNewPrivileges=no",
        *([] if terminal else [
            "--property=PrivateTmp=yes", "--property=PrivateIPC=yes",
            "--property=ProtectSystem=full",
        ]),
        "--property=UnsetEnvironment=" + " ".join(name for name in UNSET_ENVIRONMENT if name not in environment),
        f"--working-directory={os.getcwd()}",
        # Passing only names keeps tokens and other values out of argv.
        *(f"--setenv={name}" for name in sorted(environment)),
        "--", *arguments,
    ]


def main(kind: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=WRAPPERS[kind])
    parser.add_argument("mode", choices=("auto", "launch", "intel", "nvidia"))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    arguments = options.command
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if not arguments or os.geteuid() == 0:
        parser.error("a desktop-user command is required; root launches are forbidden")
    environment = session_environment()
    # Defaults are in the trusted system tree. Compositor PrivateUsers maps
    # the system owner; use the same anchor as the entrypoint bootstrap.
    defaults = load_managed_defaults(MANAGED_DEFAULTS_PATH, owner_uid=system_owner()[0])
    availability = acceleration_availability_from_defaults(defaults)
    mode = options.mode
    if mode == "auto":
        value = defaults.get(f"LABWC_{kind.upper()}_APP_DEFAULT_EXEC", "")
        parsed = shlex.split(value)
        if len(parsed) != 2 or parsed[0] != WRAPPERS[kind] or parsed[1] not in {"launch", "intel", "nvidia"}:
            fail(f"invalid default command for {kind} applications")
        mode = parsed[1]
    validate_acceleration_mode(mode, availability)
    arguments = unwrap_env(arguments, environment)
    if not arguments:
        fail("desktop entry has no executable after env assignments")
    executable = shutil.which(arguments[0], path=environment["PATH"])
    if executable is None:
        fail(f"desktop executable is unavailable: {arguments[0]}")
    if os.path.realpath(executable) in WRAPPERS.values():
        fail("recursive desktop wrapper command")
    arguments[0] = executable
    environment.update(MANAGED_WAYLAND_OPENGL_ENVIRONMENT)
    environment.update(INTEL_ACCELERATION_ENV if mode == "intel" else NVIDIA_ACCELERATION_ENV if mode == "nvidia" else {})
    if kind == "electron":
        arguments = electron_command(arguments)
    try:
        systemd_run = require_root_owned_executable("systemd-run", "/usr/bin/systemd-run")
        os.execve(systemd_run, transient_argv(kind, mode, arguments, environment), environment)
    except OSError as exc:
        fail(f"desktop executable could not start: {executable}: {exc}")
    return 1
