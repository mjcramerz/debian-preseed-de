"""Fixed PPD/autostart handover, isolated from both hardware and the desktop.

Only PID 1 changes unit files. No shell, systemctl, arbitrary unit name, hardware
write, or desktop-controlled pathname is accepted. Hardware journals and locks
are checked independently before returning policy ownership to PPD.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
import fcntl
import json
import os
from pathlib import Path
import stat
import time

from common import CONFIG, STATE, PROFILES, VENDORS, TuningError, atomic_json, trusted_json
from system_state import BusError, POWER_MANAGERS, power_managers

PPD = "power-profiles-daemon.service"
AUTOSTART = "hardware-tuning-autostart.service"
UNITS = (PPD, AUTOSTART)
DESTINATION = b"org.freedesktop.systemd1"
MANAGER_PATH = b"/org/freedesktop/systemd1"
MANAGER = b"org.freedesktop.systemd1.Manager"
ABSENT = {"org.freedesktop.systemd1.NoSuchUnit", "org.freedesktop.DBus.Error.UnknownObject",
          "org.freedesktop.systemd1.NoSuchUnitFile", "org.freedesktop.DBus.Error.FileNotFound"}
INACTIVE = {"inactive", "failed", "not-loaded"}
MASKED = {"masked", "masked-runtime"}
ACTIONS = {"status", "prepare-runtime", "prepare-boot", "activate", "stop", "disable", "recover"}


class BusFailure(TuningError):
    def __init__(self, name: str, message: str) -> None:
        super().__init__(message)
        self.name = name


class Systemd:
    """A bounded libsystemd connection; all mutation operands are constants."""
    def __init__(self) -> None:
        self.lib = C.CDLL("libsystemd.so.0")
        self.libc = C.CDLL(None)
        ptr, text = C.c_void_p, C.c_char_p
        signatures = {
            "sd_bus_open_system": ([C.POINTER(ptr)], C.c_int),
            "sd_bus_set_method_call_timeout": ([ptr, C.c_uint64], C.c_int),
            "sd_bus_call_method": ([ptr, text, text, text, text, C.POINTER(BusError), C.POINTER(ptr), text], C.c_int),
            "sd_bus_message_read": ([ptr, text], C.c_int),
            "sd_bus_get_property_string": ([ptr, text, text, text, text, C.POINTER(BusError), C.POINTER(ptr)], C.c_int),
            "sd_bus_error_free": ([C.POINTER(BusError)], ptr),
            "sd_bus_message_unref": ([ptr], ptr), "sd_bus_unref": ([ptr], ptr),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, result
        self.libc.free.argtypes, self.libc.free.restype = [ptr], None
        self.bus = ptr()
        self.deadline = time.monotonic() + 40
        if self.lib.sd_bus_open_system(C.byref(self.bus)) < 0:
            raise TuningError("system bus unavailable; no policy handover performed")

    def close(self) -> None:
        if self.bus.value:
            self.lib.sd_bus_unref(self.bus)
            self.bus = C.c_void_p()

    def bound(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TuningError("policy handover deadline expired; retry Stop or Reset")
        if self.lib.sd_bus_set_method_call_timeout(self.bus, int(min(2, remaining) * 1_000_000)) < 0:
            raise TuningError("cannot bound systemd policy operation")

    @staticmethod
    def failure(error: BusError, operation: str) -> BusFailure:
        return BusFailure((error.name or b"unknown").decode("utf-8", "replace"),
            operation + ": " + (error.message or b"systemd call failed").decode("utf-8", "replace"))

    def call(self, member: str, signature: bytes = b"", args: tuple = (), result: bytes = b"",
             *, path: bytes = MANAGER_PATH, interface: bytes = MANAGER) -> str | None:
        self.bound()
        error, reply = BusError(), C.c_void_p()
        try:
            rc = self.lib.sd_bus_call_method(self.bus, DESTINATION, path, interface,
                member.encode("ascii"), C.byref(error), C.byref(reply), signature, *args)
            if rc < 0:
                raise self.failure(error, member)
            if result:
                value = C.c_char_p()
                if self.lib.sd_bus_message_read(reply, result, C.byref(value)) <= 0 or not value.value:
                    raise TuningError("invalid systemd reply to " + member)
                return value.value.decode("ascii")
            return None
        finally:
            if reply.value:
                self.lib.sd_bus_message_unref(reply)
            self.lib.sd_bus_error_free(C.byref(error))

    def property(self, path: bytes, interface: bytes, key: bytes) -> str:
        self.bound()
        error, value = BusError(), C.c_void_p()
        try:
            if self.lib.sd_bus_get_property_string(self.bus, DESTINATION, path, interface,
                    key, C.byref(error), C.byref(value)) < 0:
                raise self.failure(error, key.decode())
            if not value.value:
                raise TuningError("empty systemd property")
            return C.string_at(value.value).decode("ascii")
        finally:
            if value.value:
                self.libc.free(value)
            self.lib.sd_bus_error_free(C.byref(error))

    @staticmethod
    def unit_path(unit: str) -> bytes:
        if unit not in UNITS:
            raise TuningError("unit is outside the policy handover allowlist")
        label = "".join(c if c.isascii() and c.isalnum() else f"_{ord(c):02x}" for c in unit)
        return ("/org/freedesktop/systemd1/unit/" + label).encode("ascii")

    def state(self, unit: str) -> dict:
        path = self.unit_path(unit)
        try:
            self.call("LoadUnit", b"s", (C.c_char_p(unit.encode()),), b"o")
        except BusFailure as exc:
            if exc.name in ABSENT:
                return {"load": "not-found", "active": "inactive", "file": "not-found"}
            raise
        load = self.property(path, b"org.freedesktop.systemd1.Unit", b"LoadState")
        active = self.property(path, b"org.freedesktop.systemd1.Unit", b"ActiveState")
        if load == "not-found" and active in INACTIVE:
            return {"load": load, "active": active, "file": "not-found"}
        if load not in {"loaded", "masked"}:
            raise TuningError("unit cannot be managed safely: " + unit + " (" + load + ")")
        # An absent/denied file-state reply AFTER loading is not proof that a
        # running daemon disappeared. Only explicit initial absence is skipped.
        file_state = self.call("GetUnitFileState", b"s", (C.c_char_p(unit.encode()),), b"s")
        if active not in {"active", "inactive", "failed", "activating", "deactivating", "reloading", "refreshing", "maintenance"}:
            raise TuningError("unrecognized systemd active state for " + unit)
        if file_state not in {"enabled", "enabled-runtime", "disabled", "masked", "masked-runtime",
                              "static", "indirect", "linked", "linked-runtime", "alias", "generated", "transient"}:
            raise TuningError("unrecognized systemd enablement state for " + unit)
        return {"load": load, "active": active, "file": file_state}

    def files(self, member: str, unit: str, runtime: bool = False) -> None:
        self.unit_path(unit)
        if member not in {"EnableUnitFiles", "DisableUnitFiles", "MaskUnitFiles", "UnmaskUnitFiles"}:
            raise TuningError("invalid unit-file operation")
        args = (C.c_size_t(1), C.c_char_p(unit.encode()), C.c_int(runtime))
        signature = b"asb"
        if member in {"EnableUnitFiles", "MaskUnitFiles"}:
            signature, args = b"asbb", (*args, C.c_int(False))  # Never force/replace a foreign unit.
        self.call(member, signature, args)
        # Unlike systemctl, the D-Bus unit-file methods do not reload PID 1.
        self.call("Reload")

    def job(self, member: str, unit: str) -> None:
        path = self.unit_path(unit)
        if member not in {"StartUnit", "StopUnit"}:
            raise TuningError("invalid lifecycle operation")
        job = self.call(member, b"ss", (C.c_char_p(unit.encode()), C.c_char_p(b"replace")), b"o")
        if not job or not job.startswith("/org/freedesktop/systemd1/job/") or not job.rsplit("/", 1)[1].isdigit():
            raise TuningError("invalid systemd job path")
        expires = min(self.deadline - 2, time.monotonic() + 20)
        try:
            while True:
                try:
                    state = self.property(job.encode(), b"org.freedesktop.systemd1.Job", b"State")
                    if state not in {"waiting", "running"}:
                        raise TuningError("unrecognized systemd job state")
                except BusFailure as exc:
                    if exc.name not in ABSENT:
                        raise
                    active = self.property(path, b"org.freedesktop.systemd1.Unit", b"ActiveState")
                    if active in ({"active"} if member == "StartUnit" else INACTIVE):
                        return
                    raise TuningError(member + " did not reach its required state: " + unit + " (" + active + ")")
                if time.monotonic() >= expires:
                    raise TuningError("systemd job timed out: " + member + " " + unit)
                time.sleep(0.05)
        except BaseException:
            # A timed-out client must not leave a queued future takeover behind.
            deadline = self.deadline
            try:
                # Reserve a final bounded cancellation attempt even when the
                # preceding property query consumed the operation deadline.
                self.deadline = max(deadline, time.monotonic() + 1)
                self.call("Cancel", path=job.encode(), interface=b"org.freedesktop.systemd1.Job")
            except TuningError:
                pass  # The mask/journal remain; no success is reported.
            finally:
                self.deadline = deadline
            raise

    def stopping(self) -> bool:
        return self.property(MANAGER_PATH, MANAGER, b"SystemState") == "stopping"


@contextmanager
def locked(path: Path):
    for directory in (path.parent, *path.parent.parents):
        st = directory.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise TuningError("untrusted policy state directory: " + str(directory))
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600:
            raise TuningError("untrusted policy/hardware transaction lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class PolicyOwner:
    def __init__(self, manager, vendors: list[str], root: Path = STATE, owners=power_managers) -> None:
        if not vendors or any(v not in VENDORS for v in vendors) or len(set(vendors)) != len(vendors):
            raise TuningError("invalid installed vendor set for policy handover")
        self.manager, self.vendors, self.root, self.owners = manager, tuple(vendors), root, owners
        self.journal = root / "policy-owner.json"
        self.claimed = False
        if self.journal.exists() or self.journal.is_symlink():
            data = trusted_json(self.journal)
            if (not isinstance(data, dict) or set(data) != {"version", "claimed"}
                    or type(data["version"]) is not int or data["version"] != 1 or type(data["claimed"]) is not bool):
                raise TuningError("invalid policy ownership journal")
            self.claimed = data["claimed"]

    def claim(self, value: bool) -> None:
        atomic_json(self.journal, {"version": 1, "claimed": value})
        self.claimed = value

    @contextmanager
    def hardware_idle(self):
        # Same locks as the hardware worker; hold them THROUGH handback so a
        # simultaneous worker cannot race the empty-journal verification.
        from contextlib import ExitStack
        with ExitStack() as locks:
            for vendor in sorted(self.vendors):
                locks.enter_context(locked(self.root / (vendor + ".lock")))
                journal = self.root / (vendor + ".json")
                if journal.exists() or journal.is_symlink():
                    data = trusted_json(journal)
                    if (not isinstance(data, dict) or set(data) != {"version", "entries", "profile"}
                            or type(data["version"]) is not int or data["version"] != 1
                            or data["profile"] not in (*PROFILES, None) or data["entries"] != []):
                        raise TuningError("hardware recovery must complete before policy handover: " + vendor)
            yield

    def ppd(self) -> dict:
        # NVIDIA-only installations must never acquire CPU-policy ownership.
        return self.manager.state(PPD) if "intel" in self.vendors else {
            "load": "not-managed", "active": "not-managed", "file": "not-managed"}

    def status(self) -> dict:
        return {"ppd": self.ppd(), "autostart_unit": self.manager.state(AUTOSTART), "claimed": self.claimed}

    def check_other_owners(self) -> None:
        if "intel" not in self.vendors:
            return
        states = self.owners()
        if set(states) != set(POWER_MANAGERS):
            raise TuningError("incomplete CPU policy-owner inventory")
        conflicts = [unit for unit, value in states.items() if unit != PPD and value not in INACTIVE]
        if conflicts:
            raise TuningError("another CPU policy owner requires administrator attention: " + ", ".join(conflicts))

    def unmask_ppd(self) -> None:
        # Remove both layers: a persistent mask hides a second runtime mask.
        self.manager.files("UnmaskUnitFiles", PPD, True)
        self.manager.files("UnmaskUnitFiles", PPD, False)

    def prepare(self, boot: bool) -> dict:
        self.check_other_owners()
        with self.hardware_idle():
            ppd = self.ppd()
            auto = self.manager.state(AUTOSTART)
            if auto["load"] != "loaded" or auto["file"] not in {"enabled", "disabled"}:
                raise TuningError("autostart unit is missing, masked or not a managed installable unit")
            # Record intent BEFORE changing either service. A killed broker's
            # ExecStopPost will restore hardware first and then return to PPD.
            self.claim(True)
            if boot and auto["file"] != "enabled":
                # Crash-safe ordering: next-boot recovery exists before PPD is
                # disabled/masked. Never leave both boot owners disabled.
                self.manager.files("EnableUnitFiles", AUTOSTART)
            if ppd["load"] != "not-managed" and ppd["load"] != "not-found":
                if boot:
                    # A masked unit cannot reliably be disabled (systemd skips
                    # its Install section). No hardware is owned during this
                    # brief unmasked window; mask+stop are verified afterwards.
                    self.unmask_ppd()
                    self.manager.files("DisableUnitFiles", PPD)
                    self.manager.files("MaskUnitFiles", PPD)
                elif ppd["file"] not in MASKED:
                    self.manager.files("MaskUnitFiles", PPD, True)
                self.manager.job("StopUnit", PPD)
                current = self.ppd()
                required = {"masked"} if boot else MASKED
                if current["file"] not in required or current["active"] not in INACTIVE:
                    raise TuningError("PPD exclusion could not be verified; custom tuning remains stopped")
            return self.status()

    def activate(self) -> dict:
        auto = self.manager.state(AUTOSTART)
        if auto["file"] == "enabled" and auto["active"] != "active":
            self.manager.job("StartUnit", AUTOSTART)
        return self.status()

    def release(self, disable: bool, recovery: bool = False) -> dict:
        if recovery and (not self.claimed or self.manager.stopping()):
            return self.status()
        with self.hardware_idle():
            ppd = self.ppd()
            if ppd["load"] not in {"not-found", "not-managed"}:
                # Starting PPD must not implicitly stop an unrelated manager
                # through the vendor unit's Conflicts= dependencies.
                self.check_other_owners()
                if ppd["file"] in MASKED:
                    self.unmask_ppd()
                if disable and self.ppd()["file"] != "enabled":
                    self.manager.files("EnableUnitFiles", PPD)
                if self.ppd()["active"] != "active":
                    self.manager.job("StartUnit", PPD)
                current = self.ppd()
                if current["active"] != "active" or current["file"] in MASKED or disable and current["file"] != "enabled":
                    raise TuningError("PPD restoration could not be verified")
            auto = self.manager.state(AUTOSTART)
            if disable and auto["file"] == "enabled":
                # Restore the default boot owner BEFORE dropping custom boot
                # recovery. A power cut in this sequence never disables both.
                self.manager.files("DisableUnitFiles", AUTOSTART)
            if auto["active"] not in INACTIVE:
                self.manager.job("StopUnit", AUTOSTART)
            self.claim(False)
            return self.status()

    def execute(self, action: str) -> dict:
        if action not in ACTIONS:
            raise TuningError("invalid policy handover operation")
        if action == "status":
            return self.status()
        if action.startswith("prepare-"):
            return self.prepare(action == "prepare-boot")
        if action == "activate":
            return self.activate()
        return self.release(action == "disable", action == "recover")


def main(argv: list[str]) -> int:
    if os.geteuid() != 0 or len(argv) != 1 or argv[0] not in ACTIONS:
        raise TuningError("policy handover is root-only and accepts one fixed operation")
    config = trusted_json(CONFIG / "broker.json")
    if not isinstance(config, dict):
        raise TuningError("invalid broker configuration")
    # The installed entrypoint never accepts an inherited alternate system bus.
    # Private-bus tests construct Systemd directly, not this privileged entrypoint.
    os.environ.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
    manager = Systemd()
    try:
        with locked(STATE / "policy-owner.lock"):
            result = PolicyOwner(manager, config.get("vendors", [])).execute(argv[0])
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    finally:
        manager.close()
