"""Feature-probed NVML backend, including Pascal-era offset/app-clock fallbacks.

All calls use explicit ctypes signatures. No nvidia-settings/X server, Coolbits,
raw register writes, shell subprocesses, or driver/firmware modifications.
"""
from __future__ import annotations

import ctypes as C
import os
import re
import stat
import subprocess
import time
from pathlib import Path
from common import Knob, TuningError, UnsupportedControl

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


class NVMLFailure(TuningError):
    def __init__(self, function: str, status: int) -> None:
        self.function, self.status = function, status
        super().__init__(f"{function}: NVML status {status}")


class NVMLUnsupported(NVMLFailure, UnsupportedControl):
    """Preserve NVML error details while identifying NOT_SUPPORTED replies."""


class NvidiaSmiFailure(TuningError):
    """A bounded nvidia-smi query or mutation failed."""


class NvidiaSmi:
    """Fixed-command fallback for drivers with incomplete NVML clock ABIs."""

    COMMAND = Path('/usr/bin/nvidia-smi')
    MAX_OUTPUT = 64 * 1024

    def __init__(self, command: Path | None = None) -> None:
        self.command = command or self.COMMAND
        try:
            metadata = self.command.lstat()
        except OSError as exc:
            raise NvidiaSmiFailure(f'nvidia-smi is unavailable: {exc}') from exc
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
                or metadata.st_gid != 0
                or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
                or not os.access(self.command, os.X_OK)):
            raise NvidiaSmiFailure('nvidia-smi is not an executable regular file')

    def run(self, uuid: str, *arguments: str) -> str:
        if re.fullmatch(r'GPU-[A-Za-z0-9-]{8,100}', uuid) is None:
            raise NvidiaSmiFailure('invalid NVIDIA GPU UUID')
        if any(not isinstance(argument, str) or
               re.fullmatch(r'[A-Za-z0-9_=+,.:-]{1,80}', argument) is None
               for argument in arguments):
            raise NvidiaSmiFailure('invalid nvidia-smi argument')
        try:
            result = subprocess.run(
                [str(self.command), '--id=' + uuid, *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='ascii',
                errors='replace',
                env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
                     'HOME': '/'},
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise NvidiaSmiFailure(f'nvidia-smi invocation failed: {exc}') from exc
        if len(result.stdout) > self.MAX_OUTPUT or len(result.stderr) > self.MAX_OUTPUT:
            raise NvidiaSmiFailure('nvidia-smi output exceeds the bounded limit')
        if result.returncode != 0:
            detail = ' '.join(result.stderr.split())[:240]
            raise NvidiaSmiFailure(
                f'nvidia-smi returned status {result.returncode}' +
                (f': {detail}' if detail else ''))
        return result.stdout

    @staticmethod
    def _pair(value: str, label: str) -> str:
        rows = [part.strip() for part in value.splitlines() if part.strip()]
        if len(rows) != 1:
            raise NvidiaSmiFailure(f'nvidia-smi returned an invalid {label} row count')
        fields = [part.strip() for part in rows[0].split(',')]
        if len(fields) != 2 or any(re.fullmatch(r'[0-9]{1,6}', part) is None for part in fields):
            raise NvidiaSmiFailure(f'nvidia-smi returned an invalid {label} pair')
        return ','.join(fields)

    def supported_clocks(self, uuid: str) -> dict[int, list[int]]:
        output = self.run(uuid, '--query-supported-clocks=memory,graphics',
                          '--format=csv,noheader,nounits')
        tables: dict[int, set[int]] = {}
        rows = [row.strip() for row in output.splitlines() if row.strip()]
        if not rows or len(rows) > 4096:
            raise NvidiaSmiFailure('nvidia-smi returned no or too many supported clocks')
        for row in rows:
            fields = [part.strip() for part in row.split(',')]
            if len(fields) != 2 or any(re.fullmatch(r'[0-9]{1,6}', part) is None for part in fields):
                raise NvidiaSmiFailure('nvidia-smi returned an invalid supported-clock row')
            memory, graphics = (int(part) for part in fields)
            tables.setdefault(memory, set()).add(graphics)
        return {memory: sorted(graphics) for memory, graphics in tables.items()}

    def application_pair(self, uuid: str, *, default: bool = False) -> str:
        prefix = 'clocks.applications' if not default else 'clocks.default_applications'
        output = self.run(uuid, '--query-gpu=' + prefix + '.memory,' + prefix + '.graphics',
                          '--format=csv,noheader,nounits')
        return self._pair(output, 'application-clock')

    def set_application_pair(self, uuid: str, pair: str) -> None:
        self.run(uuid, '--applications-clocks=' + pair)

    def reset_application_pair(self, uuid: str) -> None:
        self.run(uuid, '--reset-applications-clocks')

    def set_lock(self, uuid: str, domain: str, pair: str) -> None:
        option = '--lock-gpu-clocks=' if domain == 'GPU' else '--lock-memory-clocks='
        self.run(uuid, option + pair)

    def reset_lock(self, uuid: str, domain: str) -> None:
        self.run(uuid, '--reset-gpu-clocks' if domain == 'GPU' else '--reset-memory-clocks')


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
            raise (NVMLUnsupported if status == 3 else NVMLFailure)(name, status)

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
    def __init__(self, nvml: NVML | None = None, wanted: set[str] | None = None) -> None:
        self.api = nvml or NVML()
        self.wanted = wanted
        self.closed = False
        self.knobs: dict[str, Knob] = {}
        self.telemetry: dict[str, object] = {}
        self.unavailable: list[str] = []
        self.handles: list[H] = []
        try:
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
        except BaseException:
            try:
                self.close()
            except Exception:
                pass
            raise
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
        def wanted(setting):
            return self.wanted is None or any(k == f"{uuid}/{setting}" or k.startswith(f"{uuid}/{setting}/") for k in self.wanted)

        full = self.wanted is None
        info = {"name": self.api.text("nvmlDeviceGetName", handle)}
        if full:
            for name, call, extra in [
                ("graphics_clock_mhz", "nvmlDeviceGetClockInfo", (0,)),
                ("memory_clock_mhz", "nvmlDeviceGetClockInfo", (2,)),
                ("graphics_max_mhz", "nvmlDeviceGetMaxClockInfo", (0,)),
                ("memory_max_mhz", "nvmlDeviceGetMaxClockInfo", (2,)),
                ("power_usage_mw", "nvmlDeviceGetPowerUsage", ()),
                ("performance_state", "nvmlDeviceGetPerformanceState", ()),
                ("temperature_c", "nvmlDeviceGetTemperature", (0,)),
                ("fan_percent", "nvmlDeviceGetFanSpeed", ()),
                ("pcie_generation_current", "nvmlDeviceGetCurrPcieLinkGeneration", ()),
                ("pcie_width_current", "nvmlDeviceGetCurrPcieLinkWidth", ()),
                ("pcie_generation_max", "nvmlDeviceGetMaxPcieLinkGeneration", ()),
                ("pcie_width_max", "nvmlDeviceGetMaxPcieLinkWidth", ()),
            ]:
                info[name] = self.optional(f"{uuid}/{name}", lambda c=call, e=extra: self.api.scalar(c, handle, *e))
            def reasons():
                value = C.c_ulonglong()
                # Older drivers expose the same 64-bit flags through the
                # legacy ThrottleReasons name. This is telemetry, never a setter.
                fn = "nvmlDeviceGetCurrentClocksEventReasons"
                if not self.api.has(fn):
                    fn = "nvmlDeviceGetCurrentClocksThrottleReasons"
                self.api.call(fn, [H, C.POINTER(C.c_ulonglong)], [handle, C.byref(value)])
                return value.value
            info["clock_event_reason_mask"] = self.optional(uuid + "/clock_events", reasons)
        if full or wanted("GPU_LOCK_MHZ") or wanted("MEMORY_LOCK_MHZ"):
            info["architecture"] = self.optional(uuid + "/architecture", lambda: self.api.scalar("nvmlDeviceGetArchitecture", handle))
        self.telemetry[uuid] = info
        if wanted("POWER_LIMIT_MW"):
            self.optional(uuid + "/power", lambda: self.power(uuid, handle))
        if wanted("PERSISTENCE_MODE"):
            self.optional(uuid + "/persistence", lambda: self.scalar_knob(uuid, handle,
                "PERSISTENCE_MODE", "nvmlDeviceGetPersistenceMode", "nvmlDeviceSetPersistenceMode", 0, 1))
        if wanted("AUTO_BOOST"):
            self.optional(uuid + "/auto_boost", lambda: self.auto_boost(uuid, handle))
        for domain, prefix, setting in [(0, "Gpc", "GPU_OFFSET_MHZ"), (2, "Mem", "MEMORY_OFFSET_MHZ")]:
            if not wanted(setting):
                continue
            found = False
            if self.api.has("nvmlDeviceGetClockOffsets") and self.api.has("nvmlDeviceSetClockOffsets"):
                for pstate in range(16):
                    if not full and f"{uuid}/{setting}/P{pstate}" not in self.wanted:
                        continue
                    try:
                        self.offset(uuid, handle, domain, pstate, setting)
                        found = True
                    except TuningError:
                        pass
            if not found:
                self.optional(uuid + "/" + setting, lambda p=prefix, s=setting: self.legacy_offset(uuid, handle, p, s))
        tables = {}
        if any(wanted(k) for k in ("APPLICATION_CLOCKS_MHZ", "GPU_LOCK_MHZ", "MEMORY_LOCK_MHZ")):
            memories = self.optional(uuid + "/memory_clock_table", lambda: self.api.clocks("nvmlDeviceGetSupportedMemoryClocks", handle))
            if memories:
                if len(memories) > 256:
                    self.unavailable.append(uuid + "/clock table: more than 256 memory frequencies; no truncated table offered")
                else:
                    for memory in memories:
                        clocks = self.optional(f"{uuid}/graphics_clock_table/{memory}",
                            lambda m=memory: self.api.clocks("nvmlDeviceGetSupportedGraphicsClocks", handle, m))
                        if clocks:
                            tables[memory] = clocks
            info["supported_clocks_memory_to_graphics_mhz"] = tables
        if wanted("APPLICATION_CLOCKS_MHZ"):
            if tables and all(self.api.has(fn) for fn in (
                    "nvmlDeviceGetApplicationsClock",
                    "nvmlDeviceGetDefaultApplicationsClock",
                    "nvmlDeviceSetApplicationsClocks",
                    "nvmlDeviceResetApplicationsClocks")):
                self.optional(uuid + "/application_clocks", lambda: self.application_clocks(uuid, handle, tables))
            else:
                self.optional(uuid + "/application_clocks_nvidia_smi",
                              lambda: self.smi_application_clocks(uuid))
        arch = info.get("architecture")
        if wanted("GPU_LOCK_MHZ"):
            if isinstance(arch, int) and 5 <= arch < 0xffffffff:
                setter, resetter = "nvmlDeviceSetGpuLockedClocks", "nvmlDeviceResetGpuLockedClocks"
                if self.api.has(setter) and self.api.has(resetter):
                    self.optional(uuid + "/gpu_lock", lambda: self.clock_lock(uuid, handle, "GPU", tables))
                else:
                    self.optional(uuid + "/gpu_lock_nvidia_smi",
                                  lambda: self.smi_clock_lock(uuid, "GPU"))
            else:
                self.unavailable.append(f"{uuid}/GPU_LOCK_MHZ: Volta+ required; architecture={arch}")
        if wanted("MEMORY_LOCK_MHZ"):
            if isinstance(arch, int) and 7 <= arch < 0xffffffff and arch != 9:
                setter, resetter = "nvmlDeviceSetMemoryLockedClocks", "nvmlDeviceResetMemoryLockedClocks"
                if self.api.has(setter) and self.api.has(resetter):
                    self.optional(uuid + "/memory_lock", lambda: self.clock_lock(uuid, handle, "MEMORY", tables))
                else:
                    self.optional(uuid + "/memory_lock_nvidia_smi",
                                  lambda: self.smi_clock_lock(uuid, "MEMORY"))
            else:
                self.unavailable.append(f"{uuid}/MEMORY_LOCK_MHZ: runtime-modifiable memory locks unavailable on this architecture")
        if wanted("TARGET_TEMPERATURE_C"):
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
        try:
            read()
        except NVMLUnsupported:
            self.smi_application_clocks(uuid)
            return
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
        smi_fallback: NvidiaSmi | None = None

        def smi() -> NvidiaSmi:
            nonlocal smi_fallback
            if smi_fallback is None:
                smi_fallback = NvidiaSmi()
            return smi_fallback

        def read():
            if smi_fallback is not None:
                return smi_fallback.application_pair(uuid)
            return ",".join(str(self.api.scalar("nvmlDeviceGetApplicationsClock", handle, domain)) for domain in (2, 0))
        read()
        def validate(value):
            if value[0] not in tables or value[1] not in tables[value[0]]:
                raise TuningError("application clocks must be an advertised memory,graphics pair")
        # A clock pair is ordered memory,graphics, NOT a min/max pair. Override
        # generic pair resolution with exact advertised choices.
        if sum(len(graphics) for graphics in tables.values()) > 4096:
            raise TuningError("application clock candidate limit exceeded")
        pairs = tuple(f"{m},{g}" for m in sorted(tables, reverse=True)
                      for g in sorted(set(tables[m]), reverse=True))
        def write(value):
            parts = [int(v) for v in value.split(",")] if isinstance(value, str) else value
            validate(parts)
            if smi_fallback is not None:
                smi_fallback.set_application_pair(uuid, value)
                if read() != value:
                    raise NvidiaSmiFailure("nvidia-smi application-clock readback differs")
                return
            try:
                self.api.call("nvmlDeviceSetApplicationsClocks", [H, U, U], [handle, *parts])
            except NVMLUnsupported:
                # A symbol can be exported while the driver rejects the ABI.
                # Switch to the advertised nvidia-smi path for all subsequent
                # writes and verify the first fallback write before returning.
                smi().set_application_pair(uuid, value)
                if read() != value:
                    raise NvidiaSmiFailure("nvidia-smi application-clock readback differs")
        key = f"{uuid}/APPLICATION_CLOCKS_MHZ"
        # Do not publish a knob before BOTH the default getter and resetter are
        # known to exist. Unsupported APIs must not leave a half-built control.
        try:
            default = ",".join(str(self.api.scalar("nvmlDeviceGetDefaultApplicationsClock", handle, domain))
                               for domain in (2, 0))
        except NVMLUnsupported:
            self.smi_application_clocks(uuid)
            return
        def restore(value):
            if smi_fallback is not None:
                if value == default:
                    smi_fallback.reset_application_pair(uuid)
                else:
                    write(value)
                if read() != value:
                    raise NvidiaSmiFailure('nvidia-smi application-clock restore readback differs')
                return
            if value == default:
                try:
                    self.api.call("nvmlDeviceResetApplicationsClocks", [H], [handle])
                except NVMLUnsupported:
                    smi().reset_application_pair(uuid)
            else:
                write(value)
        fastest_memory = max(tables)
        fastest_pair = f"{fastest_memory},{max(tables[fastest_memory])}"
        def maximum():
            if smi_fallback is not None:
                deadline = time.monotonic() + 8
                before = read()
                for candidate in pairs:
                    if time.monotonic() >= deadline:
                        raise TuningError("maximum application-clock selection deadline exceeded")
                    if read() != before:
                        raise TuningError("application-clock state changed during selection")
                    if candidate == before:
                        return candidate
                    try:
                        write(candidate)
                    except NvidiaSmiFailure:
                        if read() != before:
                            raise TuningError("nvidia-smi rejection changed application-clock state; no retry")
                        continue
                    return candidate
                return None
            # Called only inside the engine's write-ahead transaction. Prefer
            # memory bandwidth first, then the highest graphics clock at that
            # memory level. Failed/missing table queries already omit a level.
            deadline = time.monotonic() + 8
            before = read()
            companions = {k: self.knobs[k].read() for k in (f"{uuid}/AUTO_BOOST",) if k in self.knobs}
            for candidate in pairs:
                if time.monotonic() >= deadline:
                    raise TuningError("maximum application-clock selection deadline exceeded")
                if read() != before or any(self.knobs[k].read() != v for k, v in companions.items()):
                    raise TuningError("application-clock state changed during selection")
                if time.monotonic() >= deadline:
                    raise TuningError("maximum application-clock selection deadline exceeded")
                if candidate == before:
                    return candidate  # Already working; no unnecessary write.
                try:
                    write(candidate)
                except NVMLFailure as exc:
                    # Retry only an explicit invalid/unsupported pair whose
                    # readback and observable side-effect state stayed intact.
                    # Permission, lost-device and unknown outcomes propagate.
                    if exc.function != "nvmlDeviceSetApplicationsClocks" or exc.status not in {2, 3}:
                        raise
                    if read() != before or any(self.knobs[k].read() != v for k, v in companions.items()):
                        raise TuningError("rejected application-clock request changed state; no retry") from exc
                    continue
                if read() != candidate:
                    raise TuningError("application-clock selection readback differs; no retry")
                if time.monotonic() >= deadline:
                    raise TuningError("maximum application-clock selection deadline exceeded")
                return candidate
            return None
        knob = Knob(key, "APPLICATION_CLOCKS_MHZ", read, write, choices=pairs,
            symbols={"max": fastest_pair},
            unit="memory,graphics MHz", note="Legacy API; not assumed available on future drivers",
            companions=(f"{uuid}/AUTO_BOOST",), write_maximum=maximum)
        knob.restore_value = restore
        self.knobs[key] = knob

    def smi_application_clocks(self, uuid: str) -> None:
        """Expose legacy ``-ac`` clocks when NVML omits that ABI."""
        smi = NvidiaSmi()
        tables = smi.supported_clocks(uuid)
        if not tables or sum(len(graphics) for graphics in tables.values()) > 4096:
            raise TuningError('nvidia-smi returned no usable application-clock table')
        pairs = tuple(f'{memory},{graphics}'
                      for memory in sorted(tables, reverse=True)
                      for graphics in sorted(set(tables[memory]), reverse=True))
        current = smi.application_pair(uuid)
        default = smi.application_pair(uuid, default=True)
        if current not in pairs or default not in pairs:
            raise TuningError('nvidia-smi application clocks are not in the advertised table')

        def read() -> str:
            return smi.application_pair(uuid)

        def validate(value: str) -> None:
            if value not in pairs:
                raise TuningError('application clocks must be an advertised memory,graphics pair')

        def write(value: str) -> None:
            validate(value)
            smi.set_application_pair(uuid, value)
            if read() != value:
                raise TuningError('nvidia-smi application-clock readback differs')

        def restore(value: str) -> None:
            if value == default:
                smi.reset_application_pair(uuid)
            else:
                write(value)
            if read() != value:
                raise TuningError('nvidia-smi application-clock restore readback differs')

        def maximum() -> str | None:
            deadline = time.monotonic() + 8
            before = read()
            for candidate in pairs:
                if time.monotonic() >= deadline:
                    raise TuningError('maximum nvidia-smi application-clock selection deadline exceeded')
                if read() != before:
                    raise TuningError('application-clock state changed during nvidia-smi selection')
                if candidate == before:
                    return candidate
                try:
                    write(candidate)
                except NvidiaSmiFailure as exc:
                    # A failed CLI request has an unknown outcome. Retry only
                    # after an exact readback proves that it did not mutate.
                    if read() != before:
                        raise TuningError('nvidia-smi rejection changed application-clock state; no retry') from exc
                    continue
                return candidate
            return None

        key = f'{uuid}/APPLICATION_CLOCKS_MHZ'
        knob = Knob(key, 'APPLICATION_CLOCKS_MHZ', read, write, choices=pairs,
                    symbols={'max': pairs[0]}, unit='memory,graphics MHz',
                    note='nvidia-smi legacy -ac fallback; driver-advertised pairs only',
                    write_maximum=maximum)
        knob.restore_value = restore
        self.knobs[key] = knob

    def smi_clock_lock(self, uuid: str, domain: str) -> None:
        """Use modern ``-lgc``/``-lmc`` locks when NVML lock symbols are absent."""
        smi = NvidiaSmi()
        tables = smi.supported_clocks(uuid)
        clocks = (sorted({clock for values in tables.values() for clock in values})
                  if domain == 'GPU' else sorted(tables))
        if not clocks:
            raise TuningError('nvidia-smi returned no advertised lock clocks')
        setter = lambda pair: smi.set_lock(uuid, domain, pair)
        resetter = lambda: smi.reset_lock(uuid, domain)
        def validate(value: list[int]) -> None:
            if any(clock not in clocks for clock in value):
                raise TuningError('both locked clock endpoints must be in the supported nvidia-smi table')
        def write(value: str | list[int]) -> None:
            if value == 'unlocked':
                resetter()
                return
            parts = [int(item) for item in value.split(',')] if isinstance(value, str) else value
            validate(parts)
            if parts[0] > parts[1]:
                raise TuningError('minimum lock clock exceeds maximum lock clock')
            setter(f'{parts[0]},{parts[1]}')
        key = f'{uuid}/{domain}_LOCK_MHZ'
        knob = Knob(key, f'{domain}_LOCK_MHZ', lambda: 'unlocked', write,
                    min(clocks), max(clocks), unit='MHz-pair', restorable=False,
                    validate_extra=validate,
                    note=('nvidia-smi modern ' + ('-lgc' if domain == 'GPU' else '-lmc') +
                          ' fallback; current lock range is intentionally not inferred'))
        self.knobs[key] = knob

    def clock_lock(self, uuid: str, handle: H, domain: str, tables: dict) -> None:
        prefix = "Gpu" if domain == "GPU" else "Memory"
        setter, resetter = f"nvmlDeviceSet{prefix}LockedClocks", f"nvmlDeviceReset{prefix}LockedClocks"
        if not self.api.has(setter) or not self.api.has(resetter):
            raise TuningError("clock-lock setter/resetter unavailable")
        clocks = sorted({clock for group in tables.values() for clock in group}) if domain == "GPU" else sorted(tables)
        if not clocks:
            raise TuningError("no advertised clock limits; refusing to guess")
        smi_fallback: NvidiaSmi | None = None
        def validate(value):
            if any(v not in clocks for v in value):
                raise TuningError("both locked clock endpoints must be in the supported clock table")
        def write(value):
            nonlocal smi_fallback
            if value == "unlocked":
                if smi_fallback is not None:
                    smi_fallback.reset_lock(uuid, domain)
                else:
                    try:
                        self.api.call(resetter, [H], [handle])
                    except NVMLUnsupported:
                        smi_fallback = NvidiaSmi()
                        smi_fallback.reset_lock(uuid, domain)
            else:
                if smi_fallback is not None:
                    smi_fallback.set_lock(uuid, domain, f'{value[0]},{value[1]}')
                else:
                    try:
                        self.api.call(setter, [H, U, U], [handle, *value])
                    except NVMLUnsupported:
                        smi_fallback = NvidiaSmi()
                        smi_fallback.set_lock(uuid, domain, f'{value[0]},{value[1]}')
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
        if not self.closed:
            self.closed = True
            self.api.call("nvmlShutdown", [], [])
