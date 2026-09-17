"""Bounded Unix-socket control plane. This process cannot write hardware.

Only a fixed root worker can change hardware. Peer credentials and active local
seat membership are checked here; no command, pathname, or knob value from a
socket request is ever passed to a shell or used as a privileged pathname.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import ctypes as C
import json
import logging
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import time
from common import (AUTOSTART, AUTOSTART_UNIT, CONFIG, MAX_JSON, PROFILES, RANK,
                    STATE, VENDORS, TuningError, atomic_json, decode, read_text, trusted_json)

LOG = logging.getLogger("hardware-tuning")
WORKER = "/usr/local/libexec/hardware-tuning-worker"


def validate_config(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != {"version", "uid", "vendors", "poll_seconds", "idle_ac", "idle_battery"}:
        raise TuningError("invalid broker configuration")
    if type(data["version"]) is not int or data["version"] != 1:
        raise TuningError("invalid broker version")
    if type(data["uid"]) is not int or not 1000 <= data["uid"] < 2**31:
        raise TuningError("broker requires a non-system desktop account")
    if not isinstance(data["vendors"], list) or not data["vendors"] or any(v not in VENDORS for v in data["vendors"]) or len(set(data["vendors"])) != len(data["vendors"]):
        raise TuningError("invalid installed vendors")
    if type(data["poll_seconds"]) is not int or not 5 <= data["poll_seconds"] <= 60:
        raise TuningError("invalid poll interval")
    if data["idle_ac"] not in (*PROFILES, "none") or data["idle_battery"] not in (*PROFILES, "none"):
        raise TuningError("invalid idle profile")
    return data


class LocalSeat:
    def __init__(self, uid: int) -> None:
        self.uid = uid
        self.lib = C.CDLL("libsystemd.so.0")
        self.test = self.lib.sd_uid_is_on_seat
        self.test.argtypes, self.test.restype = [C.c_uint, C.c_int, C.c_char_p], C.c_int

    def active(self) -> bool:
        # Errors and unknown/nonlocal sessions fail closed. SSH and lingering
        # user managers alone must never activate machine-wide tuning.
        return self.test(self.uid, 1, b"seat0") > 0


def on_ac(root: Path = Path("/sys/class/power_supply")) -> bool:
    found, battery = [], False
    for device in sorted(root.glob("*")):
        try:
            kind = read_text(device / "type")
            if kind == "Battery":
                battery = True
            if kind in ("Mains", "USB", "USB_C", "USB_PD", "USB_PD_DRP", "Wireless"):
                found.append(read_text(device / "online") == "1")
        except (OSError, TuningError):
            continue
    # A laptop with unknown AC state is treated as battery-powered. A desktop
    # without any battery retains its normal AC policy.
    return any(found) if found else not battery


class Selection:
    """Pure arbitration, separately regression tested without touching hardware."""
    def __init__(self, vendors: list[str]) -> None:
        self.vendors = tuple(vendors)
        self.automatic = False
        self.manual = {v: None for v in vendors}
        self.leases = Counter()
        self.faults: dict[str, str] = {}
        self.paused = False

    def desired(self, vendor: str, active: bool, idle: str) -> str | None:
        if not active or self.paused or vendor in self.faults:
            return None
        if self.manual[vendor] is not None:
            return self.manual[vendor]
        if not self.automatic:
            return None
        candidates = [profile for (v, profile), count in self.leases.items() if v == vendor and count > 0]
        return max(candidates, key=RANK.__getitem__) if candidates else (None if idle == "none" else idle)

    def change_lease(self, vendor: str, profile: str, delta: int) -> None:
        key = (vendor, profile)
        count = self.leases[key] + delta
        if count < 0:
            raise TuningError("unbalanced lease lifecycle")
        if count:
            self.leases[key] = count
        else:
            self.leases.pop(key, None)


class Broker:
    def __init__(self, config: dict, seat=None) -> None:
        self.config = validate_config(config)
        self.selection = Selection(config["vendors"])
        self.seat = seat if seat is not None else LocalSeat(config["uid"])
        self.lock = asyncio.Lock()
        self.applied = {v: None for v in self.selection.vendors}
        self.owned = {v: False for v in self.selection.vendors}
        self.details: dict = {}
        self.recovery_pending: set[str] = set()
        self.connections = 0
        self.tokens, self.updated = 16.0, time.monotonic()
        self.report_after = 0.0
        self.stop = asyncio.Event()
        self.writers = set()
        self.was_active = self.seat.active()

    def save(self) -> None:
        atomic_json(STATE / "controls.json", {"version": 1, "automatic": self.selection.automatic,
            "manual": self.selection.manual, "paused": self.selection.paused, "faults": self.selection.faults})

    def load(self) -> None:
        path = STATE / "controls.json"
        if not path.exists():
            return
        data = trusted_json(path)
        if not isinstance(data, dict) or set(data) != {"version", "automatic", "manual", "paused", "faults"} or type(data["version"]) is not int or data["version"] != 1:
            raise TuningError("invalid broker recovery state")
        if type(data["automatic"]) is not bool or type(data["paused"]) is not bool:
            raise TuningError("invalid automatic/pause state")
        if not isinstance(data["manual"], dict) or set(data["manual"]) != set(self.selection.vendors) or any(v not in (*PROFILES, None) for v in data["manual"].values()):
            raise TuningError("invalid manual recovery state")
        if not isinstance(data["faults"], dict) or not set(data["faults"]) <= set(self.selection.vendors) or any(not isinstance(v, str) or len(v) > 8192 for v in data["faults"].values()):
            raise TuningError("invalid fault state")
        self.selection.automatic = data["automatic"]
        self.selection.manual = data["manual"] if self.seat.active() else {v: None for v in self.selection.vendors}
        self.selection.paused = data["paused"]
        self.selection.faults = data["faults"]

    async def worker(self, vendor: str, action: str, profile: str | None = None) -> dict:
        if vendor not in self.selection.vendors or action not in ("apply", "reset", "report", "health") or profile not in (*PROFILES, None):
            raise TuningError("invalid internal worker operation")
        args = [WORKER, vendor, action] + ([profile] if profile is not None else [])
        process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}, limit=MAX_JSON + 1)
        try:
            # Read with explicit byte bounds; communicate() alone is unbounded.
            async def bounded(stream, limit):
                data = await stream.readexactly(limit + 1)
                raise TuningError("worker output limit exceeded")
            async def read_stream(stream, limit):
                try:
                    return await bounded(stream, limit)
                except asyncio.IncompleteReadError as exc:
                    return exc.partial
            output, errors, _ = await asyncio.wait_for(asyncio.gather(
                read_stream(process.stdout, MAX_JSON), read_stream(process.stderr, 65536), process.wait()), 25)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        try:
            result = decode(output)
        except (ValueError, TuningError) as exc:
            raise TuningError("worker did not return valid bounded JSON") from exc
        if process.returncode or not isinstance(result, dict) or result.get("ok") is not True:
            raise TuningError(str(result.get("error", errors.decode(errors="replace")[:4096] or "worker failure")) if isinstance(result, dict) else "worker failure")
        return result["result"]

    async def restore(self, vendor: str) -> None:
        self.details[vendor] = await self.worker(vendor, "reset")
        self.applied[vendor] = None
        self.owned[vendor] = False
        self.recovery_pending.discard(vendor)

    async def fault(self, vendor: str, exc: Exception) -> None:
        error = str(exc)
        try:
            await self.restore(vendor)
        except Exception as recovery:
            self.recovery_pending.add(vendor)
            error += "; recovery still pending: " + str(recovery)
        self.selection.faults[vendor] = error[:8192]
        LOG.error("%s: %s", vendor, error)
        self.save()

    async def reconcile(self, health: bool = False) -> None:
        active = self.seat.active()
        if self.was_active and not active:
            # Do not resurrect a previous user's manual setting on next login.
            self.selection.manual = {v: None for v in self.selection.vendors}
            self.save()
        self.was_active = active
        idle = self.config["idle_ac" if on_ac() else "idle_battery"]
        for vendor in self.selection.vendors:
            if vendor in self.selection.faults:
                continue  # Explicit reset/start retries; do not hammer a failed device.
            desired = self.selection.desired(vendor, active, idle)
            try:
                if self.owned[vendor] and (health or desired is not None and desired != self.applied[vendor]) and vendor not in self.selection.faults:
                    report = await self.worker(vendor, "health")
                    if report["conflicts"]:
                        raise TuningError("; ".join(report["conflicts"]))
                if desired != self.applied[vendor]:
                    # Restoring first also releases controls that the next
                    # profile deliberately leaves at 'keep'.
                    if self.applied[vendor] is not None or self.owned[vendor]:
                        await self.restore(vendor)
                    if desired is not None:
                        result = await self.worker(vendor, "apply", desired)
                        self.details[vendor] = result
                        self.applied[vendor] = desired
                        self.owned[vendor] = bool(result.get("controls"))
            except Exception as exc:
                await self.fault(vendor, exc)

    def boot(self, enable: bool) -> None:
        # The ONLY persistent systemd link this process is allowed to mutate.
        if AUTOSTART.is_symlink():
            if os.readlink(AUTOSTART) != AUTOSTART_UNIT:
                raise TuningError("unrecognized autostart link; refusing to replace it")
            if not enable:
                AUTOSTART.unlink()
        elif AUTOSTART.exists():
            raise TuningError("autostart path is not a managed link")
        elif enable:
            os.symlink(AUTOSTART_UNIT, AUTOSTART)
        directory = os.open(AUTOSTART.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def status(self) -> dict:
        return {"vendors": self.selection.vendors, "automatic": self.selection.automatic,
                "manual": self.selection.manual, "applied": self.applied, "owns_controls": self.owned,
                "paused": self.selection.paused, "active_local_seat": self.seat.active(),
                "autostart": AUTOSTART.is_symlink() and os.readlink(AUTOSTART) == AUTOSTART_UNIT,
                "leases": {f"{v}/{p}": n for (v, p), n in sorted(self.selection.leases.items())},
                "faults": self.selection.faults, "recovery_pending": sorted(self.recovery_pending), "last_result": self.details}

    def rate_limit(self, uid: int, action: str) -> None:
        if uid == 0:
            return
        now = time.monotonic()
        self.tokens = min(16.0, self.tokens + (now - self.updated) / 2)
        self.updated = now
        if self.tokens < 1:
            raise TuningError("control rate limit; retry after a few seconds")
        self.tokens -= 1
        if action == "report":
            if now < self.report_after:
                raise TuningError("reports are limited to one per 30 seconds")
            self.report_after = now + 30

    async def action(self, request: dict, uid: int) -> dict:
        action = request["action"]
        if action in {"pause", "resume"} and uid != 0:
            raise TuningError("sleep coordination is root-only")
        if action not in {"lease", "status", "reset", "auto-stop", "profiles-reset", "boot-disable"} and uid != 0 and not self.seat.active():
            raise TuningError("an active local seat0 session is required")
        if action == "status":
            return self.status()
        if action == "report":
            result = {"status": self.status(), "hardware": {}}
            for vendor in self.selection.vendors:
                try:
                    result["hardware"][vendor] = await self.worker(vendor, "report")
                except Exception as exc:
                    result["hardware"][vendor] = {"error": str(exc)}
            return result
        if action == "auto-start":
            self.selection.automatic = True
            self.selection.faults.clear()
            # Explicit start also reloads edited root policy, even when the
            # selected profile name has not changed.
            for vendor in self.selection.vendors:
                try:
                    await self.restore(vendor)
                except Exception as exc:
                    await self.fault(vendor, exc)
        elif action == "auto-stop":
            self.selection.automatic = False
        elif action == "manual":
            self.selection.manual[request["vendor"]] = request["profile"]
            self.selection.faults.pop(request["vendor"], None)
            # Same named profile can be reapplied after editing root config.
            try:
                await self.restore(request["vendor"])
            except Exception as exc:
                await self.fault(request["vendor"], exc)
        elif action == "profiles-reset":
            self.selection.manual = {v: None for v in self.selection.vendors}
        elif action == "reset":
            self.selection.automatic = False
            self.selection.manual = {v: None for v in self.selection.vendors}
            boot_error = None
            try:
                self.boot(False)
            except Exception as exc:
                boot_error = exc
            self.selection.faults.clear()
            for vendor in self.selection.vendors:
                try:
                    await self.restore(vendor)
                except Exception as exc:
                    await self.fault(vendor, exc)
            self.save()
            if boot_error:
                raise TuningError("hardware reset attempted, but autostart could not be disabled: " + str(boot_error))
        elif action in {"boot-enable", "boot-disable"}:
            self.boot(action == "boot-enable")
        elif action in {"pause", "resume"}:
            self.selection.paused = action == "pause"
            # A previous thermal/ownership fault must not be automatically
            # cleared by resume. Pause retries pending recovery once; sleep is
            # blocked only when hardware remains owned or unrecovered.
            if action == "pause":
                for vendor in tuple(self.recovery_pending):
                    try:
                        await self.restore(vendor)
                    except Exception as exc:
                        await self.fault(vendor, exc)
        else:
            raise TuningError("unsupported action")
        self.save()
        await self.reconcile()
        return self.status()

    def validate_request(self, request: object) -> dict:
        actions = {"status", "report", "auto-start", "auto-stop", "manual", "profiles-reset", "reset", "boot-enable", "boot-disable", "pause", "resume", "lease"}
        if not isinstance(request, dict) or request.get("action") not in actions:
            raise TuningError("invalid control request")
        required = {"action", "vendor", "profile"} if request["action"] in {"manual", "lease"} else {"action"}
        if set(request) != required:
            raise TuningError("unexpected or missing request fields")
        if len(required) > 1 and (request["vendor"] not in self.selection.vendors or request["profile"] not in PROFILES):
            raise TuningError("vendor/profile is not installed or not supported")
        return request

    @asynccontextmanager
    async def control_lock(self):
        try:
            await asyncio.wait_for(self.lock.acquire(), 5)
        except asyncio.TimeoutError as exc:
            raise TuningError("hardware controller busy; request was not executed") from exc
        try:
            yield
        finally:
            self.lock.release()

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        lease = None
        self.connections += 1
        self.writers.add(writer)
        try:
            sock = writer.get_extra_info("socket")
            _pid, uid, _gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid not in (0, self.config["uid"]):
                raise TuningError("unauthorized peer UID")
            if self.connections > (68 if uid == 0 else 64):
                raise TuningError("too many control connections")
            line = await asyncio.wait_for(reader.readline(), 5)
            if not line.endswith(b"\n") or len(line) > 4096:
                raise TuningError("one bounded JSON request is required")
            request = self.validate_request(decode(line))
            self.rate_limit(uid, request["action"])
            async with self.control_lock():
                if request["action"] == "lease":
                    if uid != self.config["uid"]:
                        raise TuningError("leases belong to the configured desktop user")
                    lease = (request["vendor"], request["profile"])
                    self.selection.change_lease(*lease, 1)
                    await self.reconcile()
                    result = self.status()
                else:
                    result = await self.action(request, uid)
            await self.reply(writer, {"ok": True, "result": result})
            if lease:
                # EOF is the release. No PID files/refcount cleanup race and
                # no need to trust a caller-supplied process identifier.
                await reader.read(1)
        except (Exception, asyncio.CancelledError) as exc:
            if not isinstance(exc, asyncio.CancelledError):
                try:
                    await self.reply(writer, {"ok": False, "error": str(exc)[:8192]})
                except (OSError, asyncio.TimeoutError):
                    pass
        finally:
            if lease:
                async with self.lock:
                    self.selection.change_lease(*lease, -1)
                    if not self.stop.is_set():
                        await self.reconcile()
            self.connections -= 1
            self.writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def reply(self, writer, value) -> None:
        data = json.dumps(value, allow_nan=False).encode() + b"\n"
        if len(data) > MAX_JSON:
            raise TuningError("reply exceeds size limit")
        writer.write(data)
        await asyncio.wait_for(writer.drain(), 5)

    async def poll(self) -> None:
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), self.config["poll_seconds"])
            except asyncio.TimeoutError:
                async with self.lock:
                    await self.reconcile(health=True)

    async def run(self, listener: socket.socket) -> None:
        self.load()
        for vendor in self.selection.vendors:
            try:
                await self.restore(vendor)
            except Exception as exc:
                await self.fault(vendor, exc)
        self.save()
        server = await asyncio.start_unix_server(self.serve, sock=listener, limit=4096)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop.set)
        ticker = asyncio.create_task(self.poll())
        async with server:
            await self.stop.wait()
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)
        for writer in list(self.writers):
            writer.close()
        async with self.lock:
            for vendor in self.selection.vendors:
                try:
                    await self.restore(vendor)
                except Exception as exc:
                    LOG.error("shutdown recovery pending for %s: %s", vendor, exc)
        # ExecStopPost runs recovery again if a handler/worker was interrupted.


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if os.geteuid() != 0 or os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise TuningError("hardware-tuningd requires one root-owned systemd activation socket")
    label = Path("/proc/self/attr/current").read_text(encoding="ascii").strip()
    if label != "managed-hardware-tuning-broker (enforce)":
        raise TuningError("the enforced hardware-tuning broker AppArmor profile is required")
    listener = socket.socket(fileno=3)
    if listener.family != socket.AF_UNIX or listener.type != socket.SOCK_STREAM:
        raise TuningError("invalid activation socket")
    os.set_inheritable(3, False)
    asyncio.run(Broker(trusted_json(CONFIG / "broker.json")).run(listener))
    return 0
