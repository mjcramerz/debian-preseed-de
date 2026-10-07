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
    "labwc-native-.service": "high",
    "labwc-wayland-.service": "balanced",
    "labwc-electron-.service": "high",
    "labwc-devops-.service": "performance",
    "llama-server.service": "performance",
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


def install(root: Path, uid: int, gid: int, environment: dict, vendors: list[str],
            templates: Path) -> list[str]:
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
    def put_template(relative, values=None, mode=0o644):
        candidate = templates / relative
        template = candidate.with_name(candidate.name + ".tmpl")
        if template.exists():
            candidate = template
        fd = os.open(candidate, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 256 * 1024):
                raise ValueError("unsafe hardware template: " + str(candidate))
            data = stream.read(256 * 1024 + 1)
            if len(data) > 256 * 1024:
                raise ValueError("oversized hardware template: " + str(candidate))
        text = data.decode("utf-8")
        values = values or {}
        def substitute(match):
            if match[1] not in values:
                raise ValueError("missing hardware template value: " + match[1])
            return values[match[1]]
        text = re.sub(r"__INSTALLER_([A-Z0-9_]+)__", substitute, text)
        if "__INSTALLER_" in text:
            raise ValueError("unresolved hardware template: " + relative)
        put(relative, text, mode)

    for name, value in (("broker", config), *policies.items()):
        put_template(f"etc/hardware-tuning/{name}.json", {
            "HARDWARE_JSON_" + key.upper(): json.dumps(item, ensure_ascii=True)
            for key, item in value.items()}, 0o600)
    put_template("etc/systemd/system/hardware-tuning.socket", {"HARDWARE_GID": str(gid)})
    nv = "nvidia" in vendors
    put_template("etc/systemd/system/hardware-tuning.service", {
        "HARDWARE_CAPABILITIES": "CAP_SYS_ADMIN" if nv else "",
        "HARDWARE_PRIVATE_DEVICES": "no" if nv else "yes",
        "HARDWARE_DEVICE_POLICY": "closed" if nv else "auto",
        "HARDWARE_DEVICE_ALLOW": "char-nvidia* rw" if nv else ""})
    for unit in ("hardware-tuning-autostart.service", "hardware-tuning-sleep.service"):
        put_template("etc/systemd/system/" + unit)
    for vendor in vendors:
        for profile in PROFILES:
            put_template(f"etc/systemd/user/{vendor}-{profile}.target")
            put_template(f"etc/systemd/user/hardware-tuning-{vendor}-{profile}.service")
    for application, profile in APPLICATIONS.items():
        put_template(f"etc/systemd/user/{application}.d/85-hardware-tuning.conf", {
            "HARDWARE_TARGETS": " ".join(f"{v}-{profile}.target" for v in vendors)})
    # Modify only battery right-clicks. All left-click values remain identical.
    relative = "etc/skel-desktop/.config/waybar/config"
    waybar = root / relative
    if waybar.is_symlink():
        raise ValueError("rendered Waybar configuration is a symlink")
    data = json.loads(waybar.read_text(encoding="utf-8"))
    if (not isinstance(data, list) or len(data) != 2
            or any(not isinstance(bar, dict) for bar in data)
            or [bar.get("name") for bar in data] != ["internal", "external"]):
        raise ValueError("Waybar configuration must contain the internal/external bars")
    for bar in data:
        # New installs use the sysfs reader; preserve existing native modules
        # when reconfiguring an older installation.
        key = "custom/battery" if "custom/battery" in bar else "battery"
        if not isinstance(bar.get(key), dict):
            raise ValueError("Waybar bar has no battery module")
        bar[key]["on-click-right"] = CLICK
    put(relative, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    ensure_directory(root / "etc/systemd/system/multi-user.target.wants", root)
    enable(root, "sockets.target.wants", "hardware-tuning.socket")
    enable(root, "sleep.target.requires", "hardware-tuning-sleep.service")
    if autostart:
        enable(root, "multi-user.target.wants", "hardware-tuning-autostart.service")
    return files


def main(argv: list[str]) -> int:
    if os.geteuid() != 0 or len(argv) < 4:
        raise ValueError("usage (root): hardware-tuning-config.py ENV_FILE ACCOUNT TEMPLATE_ROOT VENDOR [VENDOR]")
    environment = parse_environment(Path(argv[0]).read_text(encoding="ascii"))
    account = pwd.getpwnam(argv[1])
    install(Path("/"), account.pw_uid, account.pw_gid, environment, argv[3:], Path(argv[2]))
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.path.insert(0, "/usr/local/lib/hardware_tuning")
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print("hardware tuning installation failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
