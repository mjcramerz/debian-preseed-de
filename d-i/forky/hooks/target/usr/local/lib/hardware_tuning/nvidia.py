"""Feature-probed NVML backend, including Pascal-era offset/app-clock fallbacks.

All calls use explicit ctypes signatures. No nvidia-settings/X server, Coolbits,
raw register writes, shell subprocesses, or driver/firmware modifications.
"""
from __future__ import annotations

import ctypes as C
import re
from common import Knob, TuningError

SETTINGS = {
    "POWER_LIMIT_MW": ("default", "default", "keep", "min"),
    "GPU_OFFSET_MHZ": ("keep",) * 4,
    "MEMORY_OFFSET_MHZ": ("keep",) * 4,
    "GPU_LOCK_MHZ": ("keep",) * 4,
    "MEMORY_LOCK_MHZ": ("keep",) * 4,
    "APPLICATION_CLOCKS_MHZ": ("keep",) * 4,
    "PERSISTENCE_MODE": ("keep",) * 4,
    "AUTO_BOOST": ("keep",) * 4,
    "TARGET_TEMPERATURE_C": ("keep",) * 4,
}
U, I, H = C.c_uint, C.c_int, C.c_void_p
PU, PI = C.POINTER(U), C.POINTER(I)


class ClockOffset(C.Structure):
    _fields_ = [("version", U), ("type", U), ("pstate", U),
                ("clockOffsetMHz", I), ("minClockOffsetMHz", I), ("maxClockOffsetMHz", I)]


class NVML:
    def __init__(self, library: object | None = None) -> None:
        try:
            self.lib = library if library is not None else C.CDLL("libnvidia-ml.so.1")
        except OSError as exc:
            raise TuningError(f"NVML unavailable: {exc}") from exc
        self.call("nvmlInit_v2", [], [])

    def has(self, name: str) -> bool:
        return hasattr(self.lib, name)

    def call(self, name: str, types: list, args: list) -> None:
        try:
            function = getattr(self.lib, name)
        except AttributeError as exc:
            raise TuningError(f"NVML symbol unavailable: {name}") from exc
        function.argtypes, function.restype = types, I
        status = function(*args)
        if status:
            raise TuningError(f"{name}: NVML status {status} (unsupported, permission, or driver error; no write fallback)")

    def scalar(self, name: str, handle: H, *extra: int, signed: bool = False) -> int:
        out = I() if signed else U()
        self.call(name, [H] + [U] * len(extra) + [PI if signed else PU],
                  [handle, *extra, C.byref(out)])
        return out.value

    def bounds(self, name: str, handle: H, *extra: int, signed: bool = False) -> tuple[int, int]:
        a, b = (I(), I()) if signed else (U(), U())
        self.call(name, [H] + [U] * len(extra) + [PI if signed else PU] * 2,
                  [handle, *extra, C.byref(a), C.byref(b)])
        return a.value, b.value

    def text(self, name: str, handle: H) -> str:
        out = C.create_string_buffer(256)
        self.call(name, [H, C.POINTER(C.c_char), U], [handle, out, len(out)])
        return out.value.decode("ascii", errors="replace")

    def clocks(self, name: str, handle: H, *extra: int) -> list[int]:
        # A fixed bounded buffer avoids trusting a driver-provided allocation
        # count. NVML reports insufficient-size rather than overrunning it.
        count = U(4096)
        values = (U * count.value)()
        self.call(name, [H] + [U] * len(extra) + [PU, PU],
                  [handle, *extra, C.byref(count), values])
        if count.value > 4096:
            raise TuningError("NVML clock table exceeds limit")
        return sorted(set(values[:count.value]))


class Backend:
    def __init__(self, nvml: NVML | None = None) -> None:
        self.api = nvml or NVML()
        self.knobs: dict[str, Knob] = {}
        self.telemetry: dict[str, object] = {}
        self.unavailable: list[str] = []
        self.handles: list[H] = []
        count = U()
        self.api.call("nvmlDeviceGetCount_v2", [PU], [C.byref(count)])
        if not 1 <= count.value <= 64:
            raise TuningError("no physical NVIDIA GPUs, or unsupported GPU count")
        for index in range(count.value):
            handle = H()
            self.api.call("nvmlDeviceGetHandleByIndex_v2", [U, C.POINTER(H)], [index, C.byref(handle)])
            uuid = self.api.text("nvmlDeviceGetUUID", handle)
            if not re.fullmatch(r"GPU-[A-Za-z0-9-]{8,100}", uuid):
                raise TuningError("NVML did not return a physical GPU UUID")
            self.handles.append(handle)
            self.device(uuid, handle)
        self.unavailable.append("Manual fan curves, voltage control, firmware limits, ECC/compute/MIG modes and deferred driver-reload clocks are not altered")

    def optional(self, label: str, function):
        try:
            return function()
        except TuningError as exc:
            self.unavailable.append(f"{label}: {exc}")
            return None

    def scalar_knob(self, uuid: str, handle: H, setting: str, getter: str,
                    setter: str, low: int, high: int, *, symbols=None,
                    power_default=None) -> None:
        if not self.api.has(setter):
            self.unavailable.append(f"{uuid}/{setting}: setter unavailable")
            return
        read = lambda: self.api.scalar(getter, handle)
        read()  # Do not offer an unrestorable control.
        key = f"{uuid}/{setting}"
        self.knobs[key] = Knob(key, setting, read,
            lambda value: self.api.call(setter, [H, U], [handle, value]), low, high,
            symbols=symbols or {}, unit="mW" if setting == "POWER_LIMIT_MW" else "boolean",
            power_default=power_default)

    def device(self, uuid: str, handle: H) -> None:
        info = {"name": self.api.text("nvmlDeviceGetName", handle)}
        for name, call, extra in [
            ("graphics_clock_mhz", "nvmlDeviceGetClockInfo", (0,)),
            ("memory_clock_mhz", "nvmlDeviceGetClockInfo", (2,)),
            ("graphics_max_mhz", "nvmlDeviceGetMaxClockInfo", (0,)),
            ("memory_max_mhz", "nvmlDeviceGetMaxClockInfo", (2,)),
            ("power_usage_mw", "nvmlDeviceGetPowerUsage", ()),
            ("performance_state", "nvmlDeviceGetPerformanceState", ()),
            ("temperature_c", "nvmlDeviceGetTemperature", (0,)),
            ("fan_percent", "nvmlDeviceGetFanSpeed", ()),
            ("architecture", "nvmlDeviceGetArchitecture", ()),
        ]:
            info[name] = self.optional(f"{uuid}/{name}", lambda c=call, e=extra: self.api.scalar(c, handle, *e))
        self.telemetry[uuid] = info
        self.optional(uuid + "/power", lambda: self.power(uuid, handle))
        self.optional(uuid + "/persistence", lambda: self.scalar_knob(uuid, handle,
            "PERSISTENCE_MODE", "nvmlDeviceGetPersistenceMode", "nvmlDeviceSetPersistenceMode", 0, 1))
        self.optional(uuid + "/auto_boost", lambda: self.auto_boost(uuid, handle))
        for domain, prefix, setting in [(0, "Gpc", "GPU_OFFSET_MHZ"), (2, "Mem", "MEMORY_OFFSET_MHZ")]:
            found = False
            if self.api.has("nvmlDeviceGetClockOffsets") and self.api.has("nvmlDeviceSetClockOffsets"):
                for pstate in range(16):
                    try:
                        self.offset(uuid, handle, domain, pstate, setting)
                        found = True
                    except TuningError:
                        pass
            if not found:
                self.optional(uuid + "/" + setting, lambda p=prefix, s=setting: self.legacy_offset(uuid, handle, p, s))
        memories = self.optional(uuid + "/memory_clock_table", lambda: self.api.clocks("nvmlDeviceGetSupportedMemoryClocks", handle))
        tables = {}
        if memories:
            for memory in memories[:256]:
                clocks = self.optional(f"{uuid}/graphics_clock_table/{memory}",
                    lambda m=memory: self.api.clocks("nvmlDeviceGetSupportedGraphicsClocks", handle, m))
                if clocks:
                    tables[memory] = clocks
        info["supported_clocks_memory_to_graphics_mhz"] = tables
        self.optional(uuid + "/application_clocks", lambda: self.application_clocks(uuid, handle, tables))
        arch = info.get("architecture")
        if isinstance(arch, int) and 5 <= arch < 0xffffffff:
            self.optional(uuid + "/gpu_lock", lambda: self.clock_lock(uuid, handle, "GPU", tables))
        else:
            self.unavailable.append(f"{uuid}/GPU_LOCK_MHZ: Volta+ required; architecture={arch}")
        if isinstance(arch, int) and 7 <= arch < 0xffffffff and arch != 9:
            self.optional(uuid + "/memory_lock", lambda: self.clock_lock(uuid, handle, "MEMORY", tables))
        else:
            self.unavailable.append(f"{uuid}/MEMORY_LOCK_MHZ: runtime-modifiable memory locks unavailable on this architecture")
        self.optional(uuid + "/target_temperature", lambda: self.target_temperature(uuid, handle))

    def power(self, uuid: str, handle: H) -> None:
        low, high = self.api.bounds("nvmlDeviceGetPowerManagementLimitConstraints", handle)
        default = self.api.scalar("nvmlDeviceGetPowerManagementDefaultLimit", handle)
        self.scalar_knob(uuid, handle, "POWER_LIMIT_MW", "nvmlDeviceGetPowerManagementLimit",
                         "nvmlDeviceSetPowerManagementLimit", low, high,
                         symbols={"default": default}, power_default=default)

    def offset_info(self, handle: H, domain: int, pstate: int) -> ClockOffset:
        value = ClockOffset(C.sizeof(ClockOffset) | (1 << 24), domain, pstate, 0, 0, 0)
        self.api.call("nvmlDeviceGetClockOffsets", [H, C.POINTER(ClockOffset)], [handle, C.byref(value)])
        return value

    def offset(self, uuid: str, handle: H, domain: int, pstate: int, setting: str) -> None:
        info = self.offset_info(handle, domain, pstate)
        key = f"{uuid}/{setting}/P{pstate}"
        def write(value):
            request = ClockOffset(C.sizeof(ClockOffset) | (1 << 24), domain, pstate, value, 0, 0)
            self.api.call("nvmlDeviceSetClockOffsets", [H, C.POINTER(ClockOffset)], [handle, C.byref(request)])
        self.knobs[key] = Knob(key, setting,
            lambda: self.offset_info(handle, domain, pstate).clockOffsetMHz, write,
            info.minClockOffsetMHz, info.maxClockOffsetMHz, unit="MHz-offset", overclock=True)

    def legacy_offset(self, uuid: str, handle: H, prefix: str, setting: str) -> None:
        getter, setter = f"nvmlDeviceGet{prefix}ClkVfOffset", f"nvmlDeviceSet{prefix}ClkVfOffset"
        if not self.api.has(setter):
            raise TuningError("legacy offset setter unavailable")
        low, high = self.api.bounds(f"nvmlDeviceGet{prefix}ClkMinMaxVfOffset", handle, signed=True)
        read = lambda: self.api.scalar(getter, handle, signed=True)
        read()
        key = f"{uuid}/{setting}/global"
        self.knobs[key] = Knob(key, setting, read,
            lambda value: self.api.call(setter, [H, I], [handle, value]), low, high,
            unit="MHz-offset", overclock=True, note="Feature-probed legacy global VF offset ABI")

    def auto_boost(self, uuid: str, handle: H) -> None:
        def read():
            return self.api.bounds("nvmlDeviceGetAutoBoostedClocksEnabled", handle)[0]
        current, default = self.api.bounds("nvmlDeviceGetAutoBoostedClocksEnabled", handle)
        if not self.api.has("nvmlDeviceSetAutoBoostedClocksEnabled"):
            raise TuningError("auto-boost setter unavailable")
        key = f"{uuid}/AUTO_BOOST"
        self.knobs[key] = Knob(key, "AUTO_BOOST", read,
            lambda value: self.api.call("nvmlDeviceSetAutoBoostedClocksEnabled", [H, U], [handle, value]),
            0, 1, symbols={"default": default}, unit="boolean")

    def application_clocks(self, uuid: str, handle: H, tables: dict) -> None:
        if not tables or not all(self.api.has(fn) for fn in ("nvmlDeviceSetApplicationsClocks", "nvmlDeviceResetApplicationsClocks")):
            raise TuningError("no supported application-clock table/setter/resetter")
        def read():
            return ",".join(str(self.api.scalar("nvmlDeviceGetApplicationsClock", handle, domain)) for domain in (2, 0))
        read()
        def validate(value):
            if value[0] not in tables or value[1] not in tables[value[0]]:
                raise TuningError("application clocks must be an advertised memory,graphics pair")
        # A clock pair is ordered memory,graphics, NOT a min/max pair. Override
        # generic pair resolution with exact advertised choices.
        pairs = tuple(f"{m},{g}" for m, graphics in tables.items() for g in graphics)
        def write(value):
            parts = [int(v) for v in value.split(",")] if isinstance(value, str) else value
            validate(parts)
            self.api.call("nvmlDeviceSetApplicationsClocks", [H, U, U], [handle, *parts])
        key = f"{uuid}/APPLICATION_CLOCKS_MHZ"
        # Do not publish a knob before BOTH the default getter and resetter are
        # known to exist. Unsupported APIs must not leave a half-built control.
        default = ",".join(str(self.api.scalar("nvmlDeviceGetDefaultApplicationsClock", handle, domain))
                           for domain in (2, 0))
        def restore(value):
            if value == default:
                self.api.call("nvmlDeviceResetApplicationsClocks", [H], [handle])
            else:
                write(value)
        knob = Knob(key, "APPLICATION_CLOCKS_MHZ", read, write, choices=pairs,
            unit="memory,graphics MHz", note="Legacy API; not assumed available on future drivers",
            companions=(f"{uuid}/AUTO_BOOST",))
        knob.restore_value = restore
        self.knobs[key] = knob

    def clock_lock(self, uuid: str, handle: H, domain: str, tables: dict) -> None:
        prefix = "Gpu" if domain == "GPU" else "Memory"
        setter, resetter = f"nvmlDeviceSet{prefix}LockedClocks", f"nvmlDeviceReset{prefix}LockedClocks"
        if not self.api.has(setter) or not self.api.has(resetter):
            raise TuningError("clock-lock setter/resetter unavailable")
        clocks = sorted({clock for group in tables.values() for clock in group}) if domain == "GPU" else sorted(tables)
        if not clocks:
            raise TuningError("no advertised clock limits; refusing to guess")
        def validate(value):
            if any(v not in clocks for v in value):
                raise TuningError("both locked clock endpoints must be in the supported clock table")
        def write(value):
            if value == "unlocked":
                self.api.call(resetter, [H], [handle])
            else:
                self.api.call(setter, [H, U, U], [handle, *value])
        key, setting = f"{uuid}/{domain}_LOCK_MHZ", f"{domain}_LOCK_MHZ"
        self.knobs[key] = Knob(key, setting, lambda: "unlocked", write, min(clocks), max(clocks),
            unit="MHz-pair", restorable=False, validate_extra=validate,
            note="Current lock range is not queryable through the portable NVML ABI. 'unlocked' is an explicit exclusive-ownership baseline, NOT a hardware measurement; reset releases only this manager's locks.")

    def target_temperature(self, uuid: str, handle: H) -> None:
        getter = "nvmlDeviceGetTemperatureThreshold"
        low, high = [self.api.scalar(getter, handle, threshold) for threshold in (4, 6)]
        read = lambda: self.api.scalar(getter, handle, 5)
        read()
        if not self.api.has("nvmlDeviceSetTemperatureThreshold"):
            raise TuningError("temperature-target setter unavailable")
        def write(value):
            number = I(value)
            self.api.call("nvmlDeviceSetTemperatureThreshold", [H, U, PI], [handle, 5, C.byref(number)])
        key = f"{uuid}/TARGET_TEMPERATURE_C"
        self.knobs[key] = Knob(key, "TARGET_TEMPERATURE_C", read, write, low, min(high, 95), unit="C",
            note="Acoustic target only. Shutdown/slowdown thermal-protection thresholds are never changed.")

    def temperature(self) -> float | None:
        values = [self.optional("temperature", lambda h=h: self.api.scalar("nvmlDeviceGetTemperature", h, 0)) for h in self.handles]
        valid = [v for v in values if v is not None and 0 < v < 150]
        # A readable sensor on GPU A cannot prove that an offset/power
        # increase on GPU B is thermally monitored. Preserve unknown coverage
        # so the engine blocks risky writes and trips its owned-risk interlock.
        return float(max(valid)) if valid and len(valid) == len(self.handles) else None

    def close(self) -> None:
        self.api.call("nvmlShutdown", [], [])
