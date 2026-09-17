"""Unprivileged menu, bounded control client, and lifecycle-only sidecars."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import socket
import stat
import subprocess
import sys
import uuid
from common import MAX_JSON, PROFILES, SOCKET, VENDORS, TuningError, decode

EXECUTABLE = "/usr/local/bin/labwc-hardware-tuning"


def connect_request(request: dict) -> tuple[socket.socket, dict]:
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        channel.settimeout(360)
        channel.connect(SOCKET)
        channel.sendall(json.dumps(request).encode() + b"\n")
        data = bytearray()
        while len(data) <= MAX_JSON:
            chunk = channel.recv(min(65536, MAX_JSON + 1 - len(data)))
            if not chunk:
                raise TuningError("control service closed without a complete response")
            data.extend(chunk)
            if b"\n" in chunk:
                break
        if len(data) > MAX_JSON or not data.endswith(b"\n"):
            raise TuningError("invalid or oversized control response")
        reply = decode(data)
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            raise TuningError(str(reply.get("error", "invalid response")) if isinstance(reply, dict) else "invalid response")
        return channel, reply["result"]
    except BaseException:
        channel.close()
        raise


def request(action: str, vendor: str | None = None, profile: str | None = None, *, confirm_policy_owner: bool = False) -> dict:
    value = {"action": action}
    if vendor is not None:
        value.update(vendor=vendor, profile=profile)
    if confirm_policy_owner:
        value["confirm_policy_owner"] = True
    channel, result = connect_request(value)
    channel.close()
    return result


def lease(vendor: str, profile: str) -> int:
    channel, _ = connect_request({"action": "lease", "vendor": vendor, "profile": profile})
    try:
        channel.settimeout(None)
        channel.recv(1)
        # A lost broker connection is not a normal lease completion. Let the
        # user service reconnect; systemd stops it normally when unneeded.
        return 1
    finally:
        channel.close()


def parent_start(pid: int) -> str:
    directory = Path(f"/proc/{pid}")
    if directory.stat().st_uid != os.getuid():
        raise TuningError("DevOps lifetime parent is not owned by this user")
    text = (directory / "stat").read_text(encoding="ascii")
    fields = text.rsplit(")", 1)[1].split()
    if len(fields) < 20 or not fields[19].isdigit() or fields[0] == "Z":
        raise TuningError("invalid or exited DevOps parent")
    return fields[19]


def devops_start() -> int:
    # This command MUST be called in the foreground, NOT in $(...). Its PPID
    # is the actual activation subshell, unlike POSIX $$ inside a subshell.
    pid = os.getppid()
    if pid <= 1:
        raise TuningError("DevOps activation parent has exited")
    started = parent_start(pid)
    unit = f"labwc-devops-{pid}-{started}-{uuid.uuid4().hex}.service"
    command = ["/usr/bin/systemd-run", "--user", "--quiet", "--collect", "--service-type=exec",
        "--expand-environment=no", "--slice=app.slice", "--unit=" + unit,
        "--property=Requisite=labwc-session.target", "--property=After=labwc-session.target",
        "--property=PartOf=labwc-session.target", "--property=KillMode=control-group",
        "--property=TimeoutStopSec=3s", "--property=Restart=no", "--property=UMask=0077",
        "--", EXECUTABLE, "watch-parent", str(pid), started]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, check=False, timeout=15)
    if result.returncode:
        raise TuningError("could not start the DevOps tuning sidecar; the shell remains usable")
    return 0


def watch_parent(pid: int, started: str) -> int:
    try:
        fd = os.pidfd_open(pid, 0)
    except ProcessLookupError:
        return 0
    try:
        try:
            if parent_start(pid) != started:
                return 0  # PID reuse must never extend a previous lease.
        except (FileNotFoundError, ProcessLookupError, TuningError):
            return 0
        poll = select.poll()
        poll.register(fd, select.POLLIN | select.POLLHUP | select.POLLERR)
        poll.poll()  # Kernel lifetime notification: zero periodic PID polling.
    finally:
        os.close(fd)
    return 0


def notify(message: str, error: bool = False) -> None:
    print(message, file=sys.stderr if error else sys.stdout)
    try:
        subprocess.run(["/usr/bin/notify-send", "--app-name=Hardware tuning", "--urgency=" + ("critical" if error else "normal"),
                        "--", "Hardware tuning", message[:4000]], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def choose(entries: list[str], prompt: str) -> str | None:
    result = subprocess.run(["/usr/local/bin/labwc-fuzzel", "menu", "--dmenu", "--prompt", prompt],
        input="\n".join(entries) + "\n", text=True, encoding="utf-8", stdout=subprocess.PIPE, check=False)
    if result.returncode:
        return None
    selected = result.stdout.strip()
    # Never interpret free-form dmenu input as a command or a profile name.
    return selected if selected in entries else None


def safe_report_directory() -> Path:
    # Fixed account-owned location, independent of an injected XDG path.
    import pwd
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    current = home
    for part in (".local", "state", "hardware-tuning"):
        st = current.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
            raise TuningError("report directory contains an untrusted/symlink ancestor")
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
    st = current.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise TuningError("report directory must be private (mode 0700) and owned by this user")
    return current


def render_report(data: dict) -> str:
    lines = ["HARDWARE TUNING REPORT", "", "Read-only inventory; resolved profile requests are NOT proven stable overclocks.",
             "Runtime configuration: /etc/hardware-tuning/intel.json and/or nvidia.json (root-owned).",
             "keep = no change; unknown = not exposed by this driver. All units are explicit.",
             "", "CONTROL STATUS", json.dumps(data["status"], indent=2), ""]
    for vendor, report in data["hardware"].items():
        lines.extend([vendor.upper(), "=" * len(vendor)])
        if "error" in report:
            lines.extend(["Inventory failed: " + report["error"], ""])
            continue
        lines.extend(["Generated UTC: " + report["generated_utc"],
                      "Telemetry: " + json.dumps(report["telemetry"], indent=2),
                      "Temperature C: " + str(report["temperature_c"]),
                      "Platform / policy ownership: " + json.dumps(report.get("platform", {}), indent=2),
                      "Combined profile preflight: " + json.dumps(report.get("profile_preflight", {}), indent=2)])
        for knob in report["controls"]:
            lines.extend(["", knob["id"], "  Setting: " + knob["setting"] + " [" + knob["unit"] + "]",
                "  Current: " + str(knob["current"]), "  Bounds: " + str(knob["minimum"]) + " .. " + str(knob["maximum"]),
                "  Effective bounds: " + str(knob.get("effective_minimum")) + " .. " + str(knob.get("effective_maximum")),
                "  Bound source: " + str(knob.get("bounds_source", "driver")),
                "  Choices: " + json.dumps(knob["choices"]), "  Symbols: " + json.dumps(knob["symbols"])])
            if knob["read_error"]:
                lines.append("  Read limitation: " + knob["read_error"])
            if knob["note"]:
                lines.append("  Note: " + knob["note"])
            for profile in PROFILES:
                lines.append("  " + profile + ": " + json.dumps(knob["profiles"][profile], sort_keys=True))
        lines.extend(["", "Unavailable settings: " + ", ".join(report["unavailable_settings"]),
                      "Limitations: " + json.dumps(report["limitations"], indent=2), "", report["guidance"], ""])
    return "\n".join(lines) + "\n"


def save_report(data: dict) -> tuple[Path, Path]:
    directory = safe_report_directory()
    basename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
    paths = []
    for suffix, contents in (("json", json.dumps(data, indent=2, allow_nan=False) + "\n"), ("txt", render_report(data))):
        path = directory / (basename + "." + suffix)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        paths.append(path)
    return paths[0], paths[1]


def confirm_owner(boot: bool = False) -> bool:
    # Cancellation is the default; typed/free-form responses are not commands.
    cancel = "Cancel - leave power policy unchanged"
    accept = ("Confirm: stop, disable and mask PPD; start tuning now and at boot" if boot else
              "Confirm: stop PPD and block its restart until tuning is stopped")
    return choose([cancel, accept], "power-profiles-daemon.service handover> ") == accept


def menu() -> int:
    status = request("status")
    entries = ["Set Single Tuning Profile", "Generate Hardware Tuning Report", "Start Automatic Tuning", "Stop Automatic Tuning",
               "Enable Autostart Tuning at Boot", "Disable Autostart Tuning at Boot", "Reset Hardware Tuning"]
    selected = choose(entries, "Hardware tuning> ")
    if selected is None:
        return 0
    if selected == entries[0]:
        choices = {"Reset Profiles [All]": ("profiles-reset", None, None)}
        for vendor in status["vendors"]:
            label = "Intel" if vendor == "intel" else "Nvidia"
            for profile in PROFILES:
                choices[f"Set {profile.title()} Profile [{label}]"] = ("manual", vendor, profile)
        chosen = choose(list(choices), "Single tuning profile> ")
        if chosen is None:
            return 0
        action, vendor, profile = choices[chosen]
        confirmed = False
        if vendor == "intel" and not status.get("policy_owner", {}).get("claimed"):
            if not confirm_owner():
                return 0
            confirmed = True
        result = request(action, vendor, profile, confirm_policy_owner=confirmed)
        selected = chosen
    elif selected == entries[1]:
        data = request("report")
        json_path, text_path = save_report(data)
        errors = [v for v, value in data["hardware"].items() if "error" in value]
        notify("Report saved: " + str(text_path) + ("; unavailable inventory: " + ", ".join(errors) if errors else ""), bool(errors))
        return int(bool(errors))
    else:
        action = dict(zip(entries[2:], ("auto-start", "auto-stop", "boot-enable", "boot-disable", "reset")))[selected]
        confirmed = False
        if action in {"auto-start", "boot-enable"} and "intel" in status["vendors"]:
            if not confirm_owner(action == "boot-enable"):
                return 0
            confirmed = True
        result = request(action, confirm_policy_owner=confirmed)
    if result.get("faults"):
        notify("Tuning requires attention: " + json.dumps(result["faults"]), True)
        return 1
    notify(selected + "; applied=" + json.dumps(result.get("applied")) + "; automatic=" + str(result.get("automatic"))
           + "; autostart=" + str(result.get("autostart"))
           + "; PPD=" + str(result.get("policy_owner", {}).get("ppd", {}).get("active", "unknown")))
    return 0


def main(argv: list[str]) -> int:
    if argv == ["autostart-marker"]:
        if os.geteuid() != 0:
            raise TuningError("the autostart marker is system-manager-only")
        return 0  # No socket callback into the broker's active transaction.
    if argv == ["menu"]:
        try:
            return menu()
        except (OSError, TuningError, ValueError, subprocess.SubprocessError) as exc:
            notify(str(exc), True)
            return 1
    if argv == ["devops-start"]:
        return devops_start()
    if len(argv) == 3 and argv[0] == "watch-parent" and argv[1].isdigit() and argv[2].isdigit():
        return watch_parent(int(argv[1]), argv[2])
    confirmed = bool(argv and argv[-1] == "--confirm-policy-owner")
    if confirmed:
        argv = argv[:-1]
        if not argv or argv[0] not in {"auto-start", "boot-enable", "manual"}:
            raise TuningError("--confirm-policy-owner is only valid for explicit tuning activation")
    if len(argv) == 3 and argv[0] in {"lease", "manual"} and argv[1] in VENDORS and argv[2] in PROFILES:
        if argv[0] == "lease":
            return lease(argv[1], argv[2])
        result = request(*argv, confirm_policy_owner=confirmed)
    elif len(argv) == 1 and argv[0] in {"status", "report", "auto-start", "auto-stop", "profiles-reset", "reset", "boot-enable", "boot-disable", "pause", "resume"}:
        result = request(argv[0], confirm_policy_owner=confirmed)
    else:
        raise TuningError("usage: labwc-hardware-tuning {menu|status|report|auto-start|auto-stop|profiles-reset|reset|boot-enable|boot-disable|manual VENDOR PROFILE} [--confirm-policy-owner]")
    print(json.dumps(result, indent=2, allow_nan=False))
    if argv == ["pause"]:
        return int(bool(result.get("recovery_pending")) or any(result.get("owns_controls", {}).values()))
    if argv == ["resume"]:
        return int(bool(result.get("recovery_pending")))
    return int(bool(result.get("faults")))
