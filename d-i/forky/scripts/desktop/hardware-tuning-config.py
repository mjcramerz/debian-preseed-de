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
POWER_PROFILE_NAMES = ("org.freedesktop.UPower.PowerProfiles", "net.hadess.PowerProfiles")
# Actual systemd dash-prefix directories, NEVER literal '*' directory names.
APPLICATIONS = {
    "labwc-native-.service": "high",
    "labwc-wayland-.service": "balanced",
    "labwc-electron-.service": "high",
    "labwc-devops-.service": "performance",
    "llama-server.service": "performance",
}
CLICK = "/usr/bin/systemd-run --user --quiet --collect --service-type=exec --expand-environment=no --slice=app.slice --property=Requisite=labwc-session.target --property=After=labwc-session.target --property=PartOf=labwc-session.target --property=ExitType=cgroup --property=KillMode=control-group --property=TimeoutStopSec=20s -- /usr/local/bin/labwc-hardware-tuning menu"
MAX_WAYBAR_CONFIG_BYTES = 2 * 1024 * 1024


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


def require_power_profiles_activation(root: Path) -> None:
    """Read package activation as data before publishing the local unit drop-in."""
    for name in POWER_PROFILE_NAMES:
        duplicate = root / f"usr/local/share/dbus-1/system-services/{name}.service"
        if duplicate.exists() or duplicate.is_symlink():
            raise ValueError("duplicate local Power Profiles activation: " + name)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            for part in (None, "usr", "share", "dbus-1", "system-services"):
                if part is not None:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                                    dir_fd=directory)
                    os.close(directory)
                    directory = child
                info = os.fstat(directory)
                if info.st_uid != 0 or info.st_mode & 0o022:
                    raise ValueError("untrusted Power Profiles activation directory")
            fd = os.open(name + ".service", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 16 * 1024):
                    raise ValueError("untrusted Power Profiles activation file: " + name)
                data = stream.read(16 * 1024 + 1)
                if len(data) > 16 * 1024:
                    raise ValueError("oversized Power Profiles activation file: " + name)
        finally:
            os.close(directory)
        fields, section = {}, False
        for line in data.decode("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line == "[D-BUS Service]" and not section:
                section = True
                continue
            if not section or "=" not in line or line.startswith("["):
                raise ValueError("invalid Power Profiles activation structure: " + name)
            key, value = (item.strip() for item in line.split("=", 1))
            if key in fields:
                raise ValueError("duplicate Power Profiles activation field: " + name)
            fields[key] = value
        if fields != {"Name": name, "Exec": "/bin/false", "User": "root",
                      "SystemdService": "power-profiles-daemon.service"}:
            raise ValueError("incompatible packaged Power Profiles activation: " + name)


def _json_string(text: str, start: int) -> tuple[str, int]:
    """Decode one JSON string at *start*, without parsing the containing file."""
    try:
        value, end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid Waybar JSON string") from exc
    if not isinstance(value, str):
        raise ValueError("Waybar JSON key or action is not a string")
    return value, end


def _matching_json_delimiter(text: str, start: int) -> int:
    """Return the exclusive end of one bounded JSON object or array."""
    opening = text[start]
    closing = {"{": "}", "[": "]"}.get(opening)
    if closing is None:
        raise ValueError("Waybar JSON value is not an object or array")
    stack = [closing]
    cursor = start + 1
    while cursor < len(text):
        char = text[cursor]
        if char == '"':
            _, cursor = _json_string(text, cursor)
            continue
        if char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]":
            if not stack or char != stack[-1]:
                raise ValueError("mismatched Waybar JSON delimiters")
            stack.pop()
            if not stack:
                return cursor + 1
        cursor += 1
    raise ValueError("unterminated Waybar JSON value")


def _skip_json_value(text: str, start: int, limit: int) -> int:
    cursor = start
    if cursor >= limit:
        raise ValueError("missing Waybar JSON value")
    if text[cursor] == '"':
        _, cursor = _json_string(text, cursor)
        return cursor
    if text[cursor] in "{[":
        cursor = _matching_json_delimiter(text, cursor)
        if cursor > limit:
            raise ValueError("Waybar JSON value escapes its object")
        return cursor
    while cursor < limit and text[cursor] not in ",}":
        cursor += 1
    if not text[start:cursor].strip():
        raise ValueError("empty Waybar JSON value")
    return cursor


def _waybar_object_members(text: str, opening: int, closing: int) -> list[dict[str, int | str]]:
    """Read only the top-level members of one already located JSON object."""
    members: list[dict[str, int | str]] = []
    cursor = opening + 1
    while cursor < closing:
        while cursor < closing and text[cursor].isspace():
            cursor += 1
        if cursor >= closing:
            break
        if text[cursor] == ',':
            cursor += 1
            continue
        key_start = cursor
        key, cursor = _json_string(text, cursor)
        while cursor < closing and text[cursor].isspace():
            cursor += 1
        if cursor >= closing or text[cursor] != ':':
            raise ValueError("invalid Waybar object member")
        cursor += 1
        while cursor < closing and text[cursor].isspace():
            cursor += 1
        value_start = cursor
        value_end = _skip_json_value(text, value_start, closing)
        members.append({"key": key, "key_start": key_start,
                        "value_start": value_start, "value_end": value_end})
        cursor = value_end
        while cursor < closing and text[cursor].isspace():
            cursor += 1
        if cursor < closing and text[cursor] == ',':
            cursor += 1
            continue
        if cursor != closing:
            raise ValueError("invalid Waybar object separator")
    return members


def _waybar_battery_objects(text: str) -> list[tuple[int, int]]:
    """Find the one native custom/battery object in one menu include file."""
    objects: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] != '"':
            cursor += 1
            continue
        key, end = _json_string(text, cursor)
        cursor = end
        if key != "custom/battery":
            continue
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != ':':
            raise ValueError("Waybar battery key is not a member")
        cursor += 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != '{':
            raise ValueError("Waybar battery member is not an object")
        closing = _matching_json_delimiter(text, cursor)
        objects.append((cursor, closing - 1))
        cursor = closing
    if len(objects) != 1:
        raise ValueError("Waybar power menu must contain exactly one custom/battery object")
    return objects


def _waybar_remove_member(text: str, opening: int, closing: int,
                          member: dict[str, int | str]) -> tuple[str, int]:
    """Remove one action member while preserving all surrounding formatting."""
    key_start = int(member["key_start"])
    value_end = int(member["value_end"])
    line_start = text.rfind("\n", opening + 1, key_start) + 1
    if not text[line_start:key_start].strip():
        line_end = text.find("\n", value_end, closing)
        if line_end < 0:
            line_end = closing
        else:
            line_end += 1
        return text[:line_start] + text[line_end:], line_start
    cursor = value_end
    while cursor < closing and text[cursor].isspace():
        cursor += 1
    if cursor < closing and text[cursor] == ',':
        return text[:key_start] + text[cursor + 1:], key_start
    raise ValueError("inline Waybar battery action cannot be edited safely")


def _waybar_patch_battery_object(text: str) -> str:
    opening = 0
    closing = len(text) - 1
    members = _waybar_object_members(text, opening, closing)
    by_key: dict[str, dict[str, int | str]] = {}
    for member in members:
        key = str(member["key"])
        if key in ("on-click-right", "on-click-right-release"):
            if key in by_key:
                raise ValueError("duplicate Waybar battery action: " + key)
            by_key[key] = member

    for key, member in by_key.items():
        value_start = int(member["value_start"])
        value, value_end = _json_string(text, value_start)
        if value_end != int(member["value_end"]) or value != CLICK:
            raise ValueError("Waybar battery action conflicts with managed hardware menu: " + key)

    if "on-click-right" in by_key:
        text, _ = _waybar_remove_member(text, opening, closing, by_key["on-click-right"])
        closing = len(text) - 1
        members = _waybar_object_members(text, opening, closing)
        by_key = {str(member["key"]): member for member in members
                  if str(member["key"]) in ("on-click-right", "on-click-right-release")}

    if "on-click-right-release" in by_key:
        return text

    members = _waybar_object_members(text, opening, closing)
    if not members:
        raise ValueError("Waybar battery object is empty")
    last = members[-1]
    last_key_start = int(last["key_start"])
    previous = int(last["value_end"]) - 1
    while previous >= opening and text[previous].isspace():
        previous -= 1
    if previous < opening:
        raise ValueError("Waybar battery object has no final value")
    close_line_start = text.rfind("\n", opening + 1, closing) + 1
    close_indent = text[close_line_start:closing]
    member_line_start = text.rfind("\n", opening + 1, last_key_start) + 1
    member_indent = text[member_line_start:last_key_start]
    if not member_indent or member_indent.strip():
        member_indent = close_indent + "  "
    action = json.dumps(CLICK, ensure_ascii=False)
    return (text[:previous + 1] + "," + text[previous + 1:close_line_start]
            + member_indent + '"on-click-right-release": ' + action + "\n"
            + text[close_line_start:])


def patch_waybar_battery_actions(root: Path, relative: str) -> str:
    """Add the managed battery action without reparsing or reformatting Waybar."""
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError("rendered Waybar configuration is missing or unsafe")
    if path.stat().st_size > MAX_WAYBAR_CONFIG_BYTES:
        raise ValueError("rendered Waybar configuration is too large")
    text = path.read_text(encoding="utf-8")
    objects = _waybar_battery_objects(text)
    for opening, closing in objects:
        original = text[opening:closing + 1]
        patched = _waybar_patch_battery_object(original)
        text = text[:opening] + patched + text[closing + 1:]
    return text


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
        "power_profiles_api": "intel" in vendors,
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
    if config["power_profiles_api"]:
        require_power_profiles_activation(root)
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

    for name, value in policies.items():
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
    if config["power_profiles_api"]:
        values = {"HARDWARE_UID": str(uid), "HARDWARE_GID": str(gid)}
        put_template("etc/systemd/system/power-profiles-daemon.service.d/50-hardware-tuning.conf", values)
        put_template("etc/dbus-1/system.d/90-hardware-tuning-power-profiles.conf", values)
        # The existing desktop service stage enables the vendor unit offline.
        # Its two package activation files already select this same unit.
        # Keep package files/enablement and install only the local drop-in/policy.
    for vendor in vendors:
        for profile in PROFILES:
            put_template(f"etc/systemd/user/{vendor}-{profile}.target")
            put_template(f"etc/systemd/user/hardware-tuning-{vendor}-{profile}.service")
    for application, profile in APPLICATIONS.items():
        put_template(f"etc/systemd/user/{application}.d/85-hardware-tuning.conf", {
            "HARDWARE_TARGETS": " ".join(f"{v}-{profile}.target" for v in vendors)})
    # Modify only the two battery action members. Do not deserialize and
    # reserialize the complete Waybar configuration: doing so changes every
    # indentation and line boundary, invalidates appearance registry anchors,
    # and creates needless churn in the installed user's configuration.
    for relative in (
            "etc/skel-desktop/.config/waybar/actions/power-menu",
    ):
        put(relative, patch_waybar_battery_actions(root, relative))
    # Publish provider selection only after all of its units and activation
    # policy have been rendered. Offline staging never starts a consumer.
    put_template("etc/hardware-tuning/broker.json", {
        "HARDWARE_JSON_" + key.upper(): json.dumps(item, ensure_ascii=True)
        for key, item in config.items()}, 0o600)
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
