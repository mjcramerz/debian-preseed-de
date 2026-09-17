#!/usr/bin/python3 -I
"""Install only already-gated hardware tuning policy/units. No hardware writes.

Invoked in the target by hardware-tuning.sh. This temporary installer is removed
before completion. Only literal, bounded HARDWARE_* assignments are accepted.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sys
import tempfile

PREFIXES = {"intel": "HARDWARE_INTEL_CPU_TUNING_", "nvidia": "HARDWARE_NVIDIA_GPU_TUNING_"}
PROFILES = ("performance", "high", "balanced", "silent")
# Actual systemd dash-prefix directories, NEVER literal '*' directory names.
APPLICATIONS = {
    "labwc-native-vivaldi-.service": "high",
    "labwc-native-chromium-.service": "high",
    "labwc-native-microsoft-.service": "high",
    "labwc-electron-.service": "high",
    "labwc-devops-.service": "performance",
    "llama-server.service": "performance",
    "labwc-wayland-mpv-.service": "balanced",
    "labwc-wayland-recoll-.service": "balanced",
    "labwc-wayland-obs-.service": "performance",
    "labwc-wayland-kdenlive-.service": "performance",
    "labwc-wayland-blender-.service": "performance",
    "labwc-wayland-firefox-.service": "high",
    "labwc-native-mullvad-browser-.service": "high",
    "labwc-native-code-.service": "high",
    "labwc-native-chatgpt-.service": "high",
    "labwc-native-obsidian-.service": "high",
    "labwc-native-qoredb-.service": "high",
    "labwc-native-postman-.service": "high",
    "labwc-native-sleek-.service": "high",
    "labwc-native-spotify-.service": "high",
    "labwc-native-filen-.service": "high",
    "labwc-native-discord-.service": "high",
    "labwc-native-ledger-live-.service": "high",
    "labwc-native-tutanota-.service": "high",
}
CLICK = "/usr/bin/systemd-run --user --quiet --collect --service-type=exec --expand-environment=no --slice=app.slice --property=Requisite=labwc-session.target --property=After=labwc-session.target --property=PartOf=labwc-session.target --property=ExitType=cgroup --property=KillMode=control-group --property=TimeoutStopSec=20s -- /usr/local/bin/labwc-hardware-tuning menu"


def parse_environment(text: str) -> dict[str, str]:
    if len(text) > 256 * 1024:
        raise ValueError("hardware tuning environment exceeds size limit")
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r'(HARDWARE_(?:INTEL_CPU_TUNING|NVIDIA_GPU_TUNING|TUNING)_[A-Z0-9_]+)="([A-Za-z0-9_,.-]{1,100})"', line)
        if not match or match[1] in result:
            raise ValueError("hardware policy requires unique literal NAME=\"value\" assignments")
        result[match[1]] = match[2]
    return result


def boolean(value: str) -> bool:
    if value not in ("true", "false"):
        raise ValueError("hardware enable/permission flags must be exactly true or false")
    return value == "true"


def policy(environment: dict, vendor: str, settings: dict) -> dict:
    from common import validate_policy
    prefix = PREFIXES[vendor]
    suffixes = {"ENABLE", "ALLOW_OVERCLOCK", "ALLOW_POWER_INCREASE", "EXCLUSIVE_CLOCK_CONTROL", "MAX_TEMPERATURE_C"}
    suffixes.update(profile.upper() + "_" + setting for profile in PROFILES for setting in settings)
    if vendor == "intel":
        suffixes.add("ALLOW_VERIFIED_BOUNDS")
        suffixes.update(setting + "_VERIFIED_" + bound for setting in settings if setting.startswith("RAPL_") for bound in ("MIN", "MAX"))
    unexpected = {key for key in environment if key.startswith(prefix)} - {prefix + suffix for suffix in suffixes}
    if unexpected:
        raise ValueError("unknown hardware policy fields: " + ", ".join(sorted(unexpected)))
    result = {"version": 1,
        "allow_overclock": boolean(environment[prefix + "ALLOW_OVERCLOCK"]),
        "allow_power_increase": boolean(environment[prefix + "ALLOW_POWER_INCREASE"]),
        "exclusive_clock_control": boolean(environment[prefix + "EXCLUSIVE_CLOCK_CONTROL"]),
        "max_temperature_c": int(environment[prefix + "MAX_TEMPERATURE_C"]),
        "profiles": {}}
    if vendor == "intel":
        result["allow_verified_bounds"] = boolean(environment[prefix + "ALLOW_VERIFIED_BOUNDS"])
        result["verified_bounds"] = {}
        for setting in settings:
            if not setting.startswith("RAPL_"):
                continue
            low = environment[prefix + setting + "_VERIFIED_MIN"]
            high = environment[prefix + setting + "_VERIFIED_MAX"]
            if low == high == "keep":
                continue
            if low == "keep" or high == "keep":
                raise ValueError("both verified RAPL bounds must be supplied together")
            result["verified_bounds"][setting] = {"minimum": int(low), "maximum": int(high)}
    for profile in PROFILES:
        result["profiles"][profile] = {"knobs": {setting: environment[prefix + profile.upper() + "_" + setting] for setting in settings}, "overrides": {}}
    return validate_policy(result, settings)


def ensure_directory(path: Path, root: Path, mode: int = 0o755) -> None:
    if path == root:
        return
    ensure_directory(path.parent, root)
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        pass
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise ValueError("untrusted target directory: " + str(path))


def publish(root: Path, relative: str, content: str, mode: int = 0o644) -> None:
    path = root / relative
    ensure_directory(path.parent, root)
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_uid != 0)):
        raise ValueError("unsafe target file: " + str(path))
    fd, temporary = tempfile.mkstemp(prefix=".installer-tuning-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def enable(root: Path, target: str, unit: str) -> None:
    directory = root / "etc/systemd/system" / target
    ensure_directory(directory, root)
    link = directory / unit
    destination = "/etc/systemd/system/" + unit
    if link.is_symlink() and os.readlink(link) == destination:
        return
    if link.exists() or link.is_symlink():
        raise ValueError("refusing to replace a foreign systemd enablement link")
    link.symlink_to(destination)


def install(root: Path, uid: int, gid: int, environment: dict, vendors: list[str]) -> list[str]:
    from broker import validate_config
    if not vendors or any(v not in PREFIXES for v in vendors) or len(set(vendors)) != len(vendors):
        raise ValueError("the installer must supply a nonempty, uniquely gated vendor list")
    if type(gid) is not int or not 0 <= gid < 2**31:
        raise ValueError("invalid account primary group")
    common_keys = {"HARDWARE_TUNING_" + key for key in ("POLL_SECONDS", "IDLE_AC", "IDLE_BATTERY", "AUTOSTART_ENABLE")}
    if {key for key in environment if key.startswith("HARDWARE_TUNING_")} - common_keys:
        raise ValueError("unknown common hardware tuning field")
    config = validate_config({"version": 1, "uid": uid, "vendors": vendors,
        "poll_seconds": int(environment["HARDWARE_TUNING_POLL_SECONDS"]),
        "idle_ac": environment["HARDWARE_TUNING_IDLE_AC"], "idle_battery": environment["HARDWARE_TUNING_IDLE_BATTERY"]})
    policies = {}
    # Validate everything BEFORE publishing any units or enablement.
    for vendor in vendors:
        if not boolean(environment[PREFIXES[vendor] + "ENABLE"]):
            raise ValueError("a disabled vendor may not be installed")
        module = importlib.import_module(vendor)
        policies[vendor] = policy(environment, vendor, module.SETTINGS)
    autostart = boolean(environment["HARDWARE_TUNING_AUTOSTART_ENABLE"])
    files = []
    def put(relative, text, mode=0o644):
        publish(root, relative, text, mode)
        files.append(relative)
    put("etc/hardware-tuning/broker.json", json.dumps(config, indent=2) + "\n", 0o600)
    for vendor, value in policies.items():
        put(f"etc/hardware-tuning/{vendor}.json", json.dumps(value, indent=2) + "\n", 0o600)
    put("etc/systemd/system/hardware-tuning.socket", f"""[Unit]
Description=Authenticated local hardware tuning control socket

[Socket]
ListenStream=/run/hardware-tuning/control.sock
SocketUser=root
SocketGroup={gid}
SocketMode=0660
DirectoryMode=0755
RemoveOnStop=yes
Backlog=32

[Install]
WantedBy=sockets.target
""")
    nv = "nvidia" in vendors
    put("etc/systemd/system/hardware-tuning.service", """[Unit]
Description=Hardware tuning lifecycle broker (no direct hardware access)
Requires=hardware-tuning.socket apparmor.service
After=hardware-tuning.socket apparmor.service systemd-logind.service systemd-modules-load.service
Wants=systemd-logind.service
StartLimitIntervalSec=120s
StartLimitBurst=3

[Service]
Type=exec
ExecStart=/usr/local/libexec/hardware-tuningd
ExecStopPost=/usr/local/libexec/hardware-tuning-worker recover-all
Restart=on-failure
RestartSec=5s
TimeoutStopSec=75s
KillMode=control-group
RuntimeDirectory=hardware-tuning
RuntimeDirectoryMode=0755
RuntimeDirectoryPreserve=yes
UMask=0077
# Executable attachment selects broker for ExecStart and worker for ExecStopPost.
# A unit-wide AppArmorProfile would incorrectly confine recovery as the broker.
# The broker entrypoint refuses to run unless its enforced profile is attached.
# Intentional: the root-only worker must transition into its DIFFERENT,
# hardware-capable AppArmor domain. It sets NNP itself immediately after exec.
# The broker cannot execute a shell or any program except that fixed worker.
NoNewPrivileges=no
PrivateUsers=no
PrivatePIDs=no
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ProtectClock=yes
ProtectHostname=yes
ProtectKernelLogs=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ProtectKernelTunables=no
ReadOnlyPaths=/proc/sys /sys/kernel /sys/module
ReadWritePaths=/run/hardware-tuning /etc/systemd/system/multi-user.target.wants /sys/devices
RestrictAddressFamilies=AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
TasksMax=32
LimitNOFILE=256
""" + ("CapabilityBoundingSet=CAP_SYS_ADMIN\nAmbientCapabilities=\nPrivateDevices=no\nDevicePolicy=closed\nDeviceAllow=char-nvidia* rw\n" if nv else
       "CapabilityBoundingSet=\nAmbientCapabilities=\nPrivateDevices=yes\n"))
    client_hardening = """UMask=0077
AppArmorProfile=managed-hardware-tuning-client
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectHome=yes
ProtectSystem=strict
ProtectKernelTunables=yes
ProtectControlGroups=yes
ProtectKernelModules=yes
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
"""
    put("etc/systemd/system/hardware-tuning-autostart.service", """[Unit]
Description=Enable automatic hardware tuning arbitration for this boot
Requires=hardware-tuning.socket
After=hardware-tuning.socket apparmor.service systemd-logind.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/labwc-hardware-tuning auto-start
TimeoutStartSec=240s
""" + client_hardening + "\n[Install]\nWantedBy=multi-user.target\n")
    put("etc/systemd/system/hardware-tuning-sleep.service", """[Unit]
Description=Restore hardware controls before sleep and re-evaluate after resume
Requires=hardware-tuning.socket
After=hardware-tuning.socket apparmor.service
Before=sleep.target
PartOf=sleep.target
StopWhenUnneeded=yes

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/labwc-hardware-tuning pause
ExecStop=/usr/local/bin/labwc-hardware-tuning resume
TimeoutStartSec=240s
TimeoutStopSec=240s
""" + client_hardening + "\n[Install]\nRequiredBy=sleep.target\n")
    for vendor in vendors:
        for profile in PROFILES:
            target = f"{vendor}-{profile}.target"
            service = f"hardware-tuning-{vendor}-{profile}.service"
            put("etc/systemd/user/" + target, f"""[Unit]
Description=Lifetime leases for {vendor} {profile} tuning
PartOf=labwc-session.target
StopWhenUnneeded=yes
Requires={service}
""")
            put("etc/systemd/user/" + service, f"""[Unit]
Description=Unprivileged {vendor} {profile} hardware tuning lease
PartOf={target} labwc-session.target
BindsTo=labwc-session.target
After=labwc-session.target
StartLimitIntervalSec=0

[Service]
Type=exec
ExecStart=/usr/local/bin/labwc-hardware-tuning lease {vendor} {profile}
Restart=on-failure
RestartSec=5s
TimeoutStopSec=3s
KillMode=control-group
Slice=background.slice
UMask=0077
NoNewPrivileges=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_UNIX
""")
    for application, profile in APPLICATIONS.items():
        targets = " ".join(f"{v}-{profile}.target" for v in vendors)
        put(f"etc/systemd/user/{application}.d/85-hardware-tuning.conf", f"""# Managed hardware-tuning lease. Never put PartOf=tuning.target on the app.
[Unit]
Wants={targets}
Upholds={targets}
""")
    # Modify only battery right-clicks. All left-click values remain identical.
    waybar = root / "etc/skel-desktop/.config/waybar/config"
    if waybar.is_symlink():
        raise ValueError("rendered Waybar configuration is a symlink")
    data = json.loads(waybar.read_text(encoding="utf-8"))
    touched = 0
    def visit(value):
        nonlocal touched
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "battery" and isinstance(child, dict):
                    child["on-click-right"] = CLICK
                    touched += 1
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(data)
    if not touched:
        raise ValueError("rendered Waybar configuration has no battery module; refusing unwired install")
    put("etc/skel-desktop/.config/waybar/config", json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    ensure_directory(root / "etc/systemd/system/multi-user.target.wants", root)
    enable(root, "sockets.target.wants", "hardware-tuning.socket")
    enable(root, "sleep.target.requires", "hardware-tuning-sleep.service")
    if autostart:
        enable(root, "multi-user.target.wants", "hardware-tuning-autostart.service")
    put("etc/hardware-tuning/installed-files.json", json.dumps(sorted(files), indent=2) + "\n", 0o600)
    return files


def main(argv: list[str]) -> int:
    if os.geteuid() != 0 or len(argv) < 3:
        raise ValueError("usage (root): hardware-tuning-config.py ENV_FILE ACCOUNT VENDOR [VENDOR]")
    environment = parse_environment(Path(argv[0]).read_text(encoding="ascii"))
    account = pwd.getpwnam(argv[1])
    install(Path("/"), account.pw_uid, account.pw_gid, environment, argv[2:])
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.path.insert(0, "/usr/local/lib/hardware_tuning")
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print("hardware tuning installation failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
