"""Package-agnostic desktop launchers with user-manager owned lifetimes.

A separate transient service is used even when launched from a terminal. The
service is created by the host user manager, outside the compositor namespace. Native toolkit selection uses environment variables;
Chromium switches are passed only to Electron payloads.

This is lifecycle/resource ownership, not an application security boundary.
The same uid still controls its files, user manager and permitted IPC endpoints;
use an explicit AppArmor/bubblewrap policy (or a distinct uid/VM) for confinement.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import tempfile
import uuid

from .environment import (
    acceleration_availability_from_defaults, load_managed_defaults,
    validate_acceleration_mode,
)
from .recovery import assert_launch_allowed, restart_token
from .integrity import system_owner
from .session import menu_action_wait_arguments, native_session_wayland_display
from .profiles import APPS, INTEL_ACCELERATION_ENV, NVIDIA_ACCELERATION_ENV, WAYLAND_COMPAT_APPS
from .runtime import (
    ANGLE_GL_ARGS, MANAGED_DEFAULTS_PATH, MANAGED_PATH,
    MANAGED_WAYLAND_OPENGL_ENVIRONMENT, current_user_home, current_user_name,
    current_user_runtime_dir, current_user_runtime_socket, fail,
    require_root_owned_executable,
    validate_session_bus_address, wayland_ozone_args,
)

WRAPPERS = {
    "electron": "/usr/local/bin/labwc-electron-app",
    "wayland": "/usr/local/bin/labwc-wayland-app",
}
CAPTURE_EXECUTABLES = frozenset({"/usr/bin/wireshark", "/usr/bin/tshark", "/usr/bin/dumpcap"})
CONFIGURED_ENVIRONMENT_NAMES = "LABWC_CONFIGURED_ENVIRONMENT_NAMES"
CONFIGURED_PAYLOAD_LAUNCHER = (
    "import json,os,sys; "
    "source=open(sys.argv[1],encoding='utf-8'); environment=json.load(source); source.close(); "
    "os.execve(sys.argv[2],sys.argv[2:],environment)"
)
# Never let the user manager reintroduce X11, a different GPU or loader hooks.
UNSET_ENVIRONMENT = (
    "DISPLAY", "XAUTHORITY", "GTK_THEME", "LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH",
    "LABWC_MENU_ACTION_WAIT",
    "PYTHONPATH", "PYTHONHOME", "BASH_ENV", "ENV", "ELECTRON_RUN_AS_NODE",
    "ELECTRON_NO_SANDBOX", "NODE_OPTIONS", "GBM_BACKEND", "DRI_PRIME",
    "LIBVA_DRIVER_NAME", "NVD_BACKEND", "__GLX_VENDOR_LIBRARY_NAME",
    "__NV_PRIME_RENDER_OFFLOAD", "__VK_LAYER_NV_optimus", "VK_ICD_FILENAMES",
    "VK_DRIVER_FILES", "MESA_LOADER_DRIVER_OVERRIDE", "LIBGL_ALWAYS_SOFTWARE",
    CONFIGURED_ENVIRONMENT_NAMES,
)
ELECTRON_UNSAFE_SWITCHES = {
    "--no-sandbox", "--no-zygote", "--single-process", "--disable-gpu-sandbox",
    "--disable-namespace-sandbox", "--disable-seccomp-filter-sandbox", "--disable-sandbox",
    "--in-process-gpu",
}
MANAGED_EXECUTABLE_ALIASES = {
    "chromium": ("/usr/lib/chromium/chromium",),
    "microsoft-edge": ("/opt/microsoft/msedge/microsoft-edge",),
    "vivaldi": ("/opt/vivaldi/vivaldi", "/opt/vivaldi/vivaldi-bin"),
    "code": ("/usr/share/code/code", "/usr/share/code/bin/code"),
    "mullvad-browser": ("/usr/lib/mullvad-browser/start-mullvad-browser",),
    "spotify": ("/usr/share/spotify/spotify",),
}


def electron_command(arguments: list[str]) -> list[str]:
    """Retain vendor arguments/field-code expansions, without policy overrides."""
    for argument in arguments[1:]:
        key = argument.split("=", 1)[0]
        # Chromium accepts a single '-' as well as '--'. A boolean switch is
        # present even when its supplied value is "false".
        if key.startswith("-") and not key.startswith("--"):
            key = "-" + key
        if key in ELECTRON_UNSAFE_SWITCHES:
            fail(f"Electron launcher refuses sandbox-disabling switch: {key}")
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
        if key.startswith("-") and not key.startswith("--"):
            key = "-" + key
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
    raw_bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not raw_bus:
        raw_bus = "unix:path=" + current_user_runtime_socket("DBUS session bus", "bus")
    bus = validate_session_bus_address(raw_bus)
    display = native_session_wayland_display({
        "PATH": MANAGED_PATH, "HOME": home, "XDG_RUNTIME_DIR": runtime,
        "DBUS_SESSION_BUS_ADDRESS": bus,
    })
    environment = {"PATH": MANAGED_PATH, "LANG": "C.UTF-8"}
    for name, value in os.environ.items():
        if name in {"LANG", "LANGUAGE", "TZ", "TERM", "COLORTERM", "XDG_ACTIVATION_TOKEN", "QT_QPA_PLATFORMTHEME"} or name.startswith("LC_"):
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


def managed_network_command(mode: str, arguments: list[str], *, kind: str = "wayland") -> list[str] | None:
    """Keep generic desktop entries for known clients on the reviewed policy.

    Match installed executable paths, never desktop names or user data. This
    covers package updates and URI handlers before launcher synchronization.
    """
    executable = os.path.realpath(arguments[0])
    for name, policy in APPS.items():
        if not policy.get("persistent_sandbox", False) and name != "qbittorrent":
            continue
        paths = (policy["exec"], *policy.get("exec_candidates", ()),
                 *MANAGED_EXECUTABLE_ALIASES.get(name, ()))
        if name == "qbittorrent":
            paths = (*paths, "/usr/bin/qbittorrent")
        if not any(executable == os.path.realpath(path) for path in dict.fromkeys(paths)):
            continue
        if name == "chatgpt":
            return ["/usr/local/bin/chatgpt", mode, *arguments[1:]]
        if name in WAYLAND_COMPAT_APPS:
            return ["/usr/local/bin/labwc-wayland-compat-app", mode, name, *arguments[1:]]
        if name == "qbittorrent":
            return ["/usr/local/bin/labwc-qbittorrent", *([f"--acceleration={mode}"] if mode in {"intel", "nvidia"} else []), *arguments[1:]]
        return ["/usr/local/bin/labwc-app", mode, name, *arguments[1:]]
    # Keep the existing host administration/recovery entrypoints usable even
    # while an administrator is repairing a malformed network policy file.
    if any(executable == os.path.realpath(path) for path in (
            "/usr/bin/foot", "/usr/bin/footclient", "/usr/bin/kitty", "/usr/bin/terminal-emulator",
            *CAPTURE_EXECUTABLES,
            "/usr/bin/thunar", "/usr/bin/Thunar", "/usr/local/bin/labwc-terminal",
            "/usr/bin/timeshift-launcher", "/usr/local/bin/mullvad-vpn", "/usr/local/bin/waypaper",
            "/usr/local/bin/labwc-desktop-appearance", "/usr/local/bin/labwc-remote-desktop",
            "/opt/Mullvad VPN/mullvad-vpn", "/opt/Mullvad VPN/mullvad-gui")):
        return None
    from .network_client import configured_executable_application
    name = configured_executable_application(executable)
    if name is not None:
        return ["/usr/local/libexec/app-veth-run", kind, mode, name, "--", *arguments]
    return None


def configured_worker_environment(environment: dict[str, str]) -> dict[str, str]:
    """Carry only names explicitly supplied by the generic launcher.

    The user manager may hold unrelated variables. Passing names separately
    preserves desktop env assignments and session restore metadata without
    exposing values in the worker's command line or copying manager secrets.
    """
    raw = os.environ.get(CONFIGURED_ENVIRONMENT_NAMES, "")
    names = raw.split()
    if len(raw) > 8192 or len(names) > 128 or len(set(names)) != len(names):
        fail("invalid configured application environment names")
    total = 0
    for name in names:
        if (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
                or name == CONFIGURED_ENVIRONMENT_NAMES or name not in os.environ):
            fail("invalid configured application environment name")
        value = os.environ[name]
        total += len(value.encode("utf-8", errors="surrogateescape"))
        if len(value) > 65536 or total > 262144:
            fail("oversized configured application environment")
        protected = (name in UNSET_ENVIRONMENT
                     or name.startswith(("LD_", "BASH_FUNC_", "VK_", "__VK_"))
                     or name in {"HOME", "USER", "LOGNAME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"})
        if protected and (name not in environment or value != environment[name]):
            fail(f"configured application environment conflicts with isolation: {name}")
        environment[name] = value
    return environment


def run_configured_network(arguments: list[str]) -> int:
    """A user-manager worker for new, explicitly configured package clients.

    Preserve the generic launcher's filesystem and IPC access. This adds a
    private network/PID namespace, rather than inventing an application-specific
    filesystem or AppArmor policy for an unknown package.
    """
    from . import network_namespace
    from .network_client import configured_executable_application, configured_network_policy
    from .network_client import resolver_configuration

    parser = argparse.ArgumentParser(prog="app-veth-run")
    parser.add_argument("kind", choices=tuple(WRAPPERS))
    parser.add_argument("mode", choices=("launch", "intel", "nvidia"))
    parser.add_argument("app")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)
    payload = options.command
    if payload[:1] == ["--"]:
        payload = payload[1:]
    if not payload or os.geteuid() == 0:
        parser.error("a configured desktop-user executable is required")
    assert_launch_allowed()
    executable = os.path.realpath(payload[0])
    if configured_executable_application(executable) != options.app:
        fail("executable is not authorized by the application network configuration")
    owner_uid = system_owner()[0]
    for parent in Path(executable).parents:
        metadata = parent.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != owner_uid
                or metadata.st_mode & 0o022):
            fail("configured executable has an unsafe parent directory")
    require_root_owned_executable("configured application", executable)
    payload[0] = executable
    environment = session_environment()
    defaults = load_managed_defaults(MANAGED_DEFAULTS_PATH, owner_uid=owner_uid)
    validate_acceleration_mode(options.mode, acceleration_availability_from_defaults(defaults))
    environment.update(INTEL_ACCELERATION_ENV if options.mode == "intel"
                       else NVIDIA_ACCELERATION_ENV if options.mode == "nvidia" else {})
    environment = configured_worker_environment(environment)
    if options.kind == "electron":
        payload = electron_command(payload)
    policy = configured_network_policy(options.app)
    if policy is None:
        fail("application network policy was removed before launch")
    bwrap = require_root_owned_executable("bubblewrap", "/usr/bin/bwrap")
    # The transient unit owns a private /tmp and removes it even after a
    # crash/SIGKILL. Payloads receive a separate empty /tmp mount.
    with tempfile.TemporaryDirectory(prefix="labwc-configured-network-", dir="/tmp") as temporary:
        resolver = Path(temporary) / "resolv.conf"
        resolver.write_text(resolver_configuration() if policy["network"] else "# Networking is disabled.\n",
                            encoding="ascii")
        resolver.chmod(0o600)
        # Desktop env assignments may contain application credentials. Keep
        # their values in a private read-only payload file, never bwrap argv.
        environment_path = Path(temporary) / "environment.json"
        with os.fdopen(os.open(environment_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                               0o600), "w", encoding="utf-8") as stream:
            json.dump(environment, stream)
        payload_environment_path = "/tmp/.labwc-app-environment.json"
        command = [bwrap, "--die-with-parent", "--new-session", "--unshare-user", "--unshare-pid",
                   "--unshare-net", "--unshare-ipc", "--unshare-uts", "--uid", str(os.getuid()),
                   "--gid", str(os.getgid()), "--bind", "/", "/", "--proc", "/proc",
                   "--tmpfs", "/tmp", "--tmpfs", "/run/app-veth", "--ro-bind", str(resolver),
                   "/etc/resolv.conf", "--ro-bind", str(environment_path), payload_environment_path,
                   "--chdir", os.getcwd(), "--cap-drop", "ALL", "--clearenv"]
        # The fixed compatibility runtime remains available only through its
        # existing Zoom/Discord launchers; generic clients cannot use it.
        if Path("/opt/xwayland").is_dir():
            command.extend(("--tmpfs", "/opt/xwayland"))
        payload = ["/usr/bin/python3", "-I", "-B", "-c", CONFIGURED_PAYLOAD_LAUNCHER,
                   payload_environment_path, *payload]
        return network_namespace.run_veth_sandbox(command, payload, temporary, (),
                                                  app=options.app, network=policy["network"])


def transient_argv(kind: str, mode: str, arguments: list[str], environment: dict[str, str],
                   *, restore_arguments: list[str] | None = None) -> list[str]:
    assert_launch_allowed()
    is_thunar = kind == "wayland" and arguments[0] in {"/usr/bin/thunar", "/usr/bin/Thunar"}
    is_capture = kind == "wayland" and arguments[0] in CAPTURE_EXECUTABLES
    if is_thunar:
        # GTK 3's GDK GL path can repaint a Thunar window erratically on this
        # desktop. Keep the diagnostic workaround local to the file manager.
        environment["GDK_DEBUG"] = "nogl"
        # Route native device unmount/eject through the ordered drive worker.
        # The managed monitor delegates inventory and mount dialogs to GVfs.
        environment["GIO_USE_VFS"] = "gvfs"
        environment["GIO_USE_VOLUME_MONITOR"] = "GProxyVolumeMonitorLabwc"
    # Native GTK settings own color mode, including labwc-tweaks.
    # The package's argument-free footclient entry has no server readiness
    # dependency; a transient unit can outrun foot-server and lose the launch.
    # Use the already managed standalone Foot path for this exact invocation.
    if kind == "wayland" and arguments == ["/usr/bin/footclient"]:
        arguments = ["/usr/bin/foot"]
    environment["LABWC_SESSION_APP"] = "1"
    restored = arguments if restore_arguments is None else restore_arguments
    environment["LABWC_SESSION_RESTORE"] = restart_token([WRAPPERS[kind], mode, "--", *restored])
    if arguments[0] == "/usr/local/libexec/app-veth-run":
        environment[CONFIGURED_ENVIRONMENT_NAMES] = " ".join(sorted(
            name for name in environment if name != CONFIGURED_ENVIRONMENT_NAMES))
    label = re.sub(r"[^A-Za-z0-9_-]", "-", Path(restored[0]).name)[:48] or "app"
    unit = f"labwc-{kind}-{label}-{uuid.uuid4().hex}.service"
    # These canonical administration launchers need host UID semantics.
    # User-manager filesystem/IPC namespaces implicitly enable PrivateUsers:
    # pkexec cannot become host root and Mullvad sees its root-owned daemon
    # socket as owned by nobody. Waypaper's post-command also validates the
    # root-owned ancestors of the user's wallpaper state; the user namespace
    # maps those ancestors to nobody and rejects every selection. Thunar needs
    # the host mount view and UID semantics for GVfs/UDisks removable-drive
    # controls and for mount/unmount changes to reach its Devices sidebar.
    # These apps retain their AppArmor profiles and session lifetime properties.
    # dumpcap's package capabilities belong to the initial user namespace.
    # PrivateTmp/ProtectSystem in a user unit implicitly create PrivateUsers,
    # where those capabilities cannot authorize host-interface packet sockets.
    host_administration = is_capture or (kind == "wayland" and arguments[0] in {
        "/usr/bin/foot", "/usr/bin/kitty", "/usr/bin/terminal-emulator",
        "/usr/bin/thunar", "/usr/bin/Thunar",
        "/usr/local/bin/labwc-terminal",
        "/usr/bin/timeshift-launcher", "/usr/local/bin/mullvad-vpn",
        "/usr/local/bin/waypaper",
        "/usr/local/bin/labwc-desktop-appearance",
    }) or (kind == "wayland" and arguments[:2] == [
        "/usr/local/bin/labwc-remote-desktop", "_connect",
    ]) or (kind == "electron" and arguments[0] in {
        "/opt/Mullvad VPN/mullvad-vpn", "/opt/Mullvad VPN/mullvad-gui",
    })
    # FreeRDP's file clipboard uses the package's setuid fusermount3 helper.
    # The connection worker needs the host root UID mapping for that helper;
    # its restricted AppArmor child owns the only permitted FUSE mount.
    is_foot = kind == "wayland" and arguments[0] == "/usr/bin/foot"
    is_terminal = kind == "wayland" and arguments[0] in {
        "/usr/bin/foot", "/usr/bin/kitty", "/usr/bin/terminal-emulator",
        "/usr/local/bin/labwc-terminal",
    }
    is_waypaper = kind == "wayland" and arguments[0] == "/usr/local/bin/waypaper"
    return [
        "/usr/bin/systemd-run", "--user", "--quiet", "--collect",
        *menu_action_wait_arguments(),
        "--service-type=exec", "--expand-environment=no", "--slice=app.slice",
        f"--unit={unit}", f"--description=Labwc {kind} application: {label}",
        "--property=Requisite=labwc-session.target",
        "--property=After=labwc-session.target" + (
            " gvfs-daemon.service labwc-gvfs-volume-monitor.service" if is_thunar else ""),
        "--property=PartOf=labwc-session.target",
        *(["--property=Wants=gvfs-daemon.service",
           "--property=Requires=labwc-gvfs-volume-monitor.service",
           "--property=PrivateMounts=no"] if is_thunar else []),
        *(["--property=PrivateNetwork=no", "--property=PrivateMounts=no"] if is_capture else []),
        # Waypaper temporarily owns swaybg while its GUI is open. Stop the
        # supervisor before native backend startup, then restore the saved
        # selection after the GUI and all its renderers have exited. This
        # handoff is independent of AppArmor's enforce/complain setting.
        *(["--property=ExecStartPre=/usr/bin/systemctl --user stop swaybg.service",
           "--property=ExecStopPost=/usr/bin/systemctl --user start swaybg.service"] if is_waypaper else []),
        # The executable is the foreground application. Its exit starts the
        # service's bounded cleanup, including detached descendants. An app
        # that the user configured to stay in its tray keeps its main alive.
        "--property=ExitType=main",
        f"--property=ConditionPathExists=!/run/user/{os.getuid()}/labwc-session-closing",
        "--property=KillMode=" + ("mixed" if is_foot else "control-group"),
        # Bound preparation/exec failure without limiting application runtime.
        "--property=TimeoutStartSec=10s", "--property=TimeoutStopSec=20s",
        "--property=SendSIGKILL=yes", "--property=Restart=no", "--property=UMask=0077",
        # Do not force NNP/seccomp before package AppArmor -> bwrap
        # transitions. Electron and Bubblewrap set NNP inside their sandboxes.
        "--property=StandardInput=null", "--property=StandardOutput=journal",
        "--property=StandardError=journal", f"--property=SyslogIdentifier=labwc-{label}",
        "--property=LimitCORE=0", "--property=NoNewPrivileges=no",
        # Signal Foot itself first so it can close/reap its PTY client.
        # systemd still owns final cgroup cleanup. Only the argument-free
        # default shell or btop gets the observed close-window HUP status (1).
        # Other commands/options and Foot internal errors (230) stay errors.
        *(["--property=SuccessExitStatus=1"] if is_foot and (
            len(arguments) == 1 or arguments == ["/usr/bin/foot", "-e", "btop"]
        ) else []),
        # Preserve the main process status. Record the actual failure after the
        # transient unit exits, including exec/namespace and Foot/parser errors.
        *(["--property=ExecStopPost=/usr/local/libexec/labwc-terminal-result"] if is_foot else []),
        *(["--property=PrivatePIDs=no", "--property=PrivateUsers=no"] if host_administration else [
            "--property=PrivateTmp=yes", "--property=PrivateIPC=yes",
            "--property=ProtectSystem=full",
        ]),
        *(["--property=ProtectProc=default", "--property=ProcSubset=all"] if is_terminal else []),
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
    network_command = managed_network_command(mode, arguments, kind=kind)
    restore_arguments = list(arguments) if network_command is not None else None
    if network_command is not None:
        arguments = network_command
    elif kind == "electron":
        arguments = electron_command(arguments)
    try:
        systemd_run = require_root_owned_executable("systemd-run", "/usr/bin/systemd-run")
        os.execve(systemd_run, transient_argv(kind, mode, arguments, environment,
                                            restore_arguments=restore_arguments), environment)
    except OSError as exc:
        fail(f"desktop executable could not start: {executable}: {exc}")
    return 1
