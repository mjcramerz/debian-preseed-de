"""Read-only policy-owner and platform inventory. No commands or hardware writes.

The systemd query surface is a fixed list of ActiveState properties. A failed
query is unknown, never evidence that a competing policy manager is stopped.
Platform diagnostics are generated on request, not in the periodic health path.
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path
import re
from common import TuningError, read_text

POWER_MANAGERS = (
    "power-profiles-daemon.service", "tlp.service", "tlp-pd.service",
    "tuned.service", "tuned-ppd.service", "auto-cpufreq.service",
    "cpufrequtils.service", "ondemand.service", "throttled.service",
)


class BusError(C.Structure):
    _fields_ = [("name", C.c_char_p), ("message", C.c_char_p), ("need_free", C.c_int)]


def power_managers() -> dict[str, str]:
    """Read systemd states via libsystemd's typed API, without activating units."""
    lib = C.CDLL("libsystemd.so.0")
    libc = C.CDLL(None)
    ptr, text = C.c_void_p, C.c_char_p
    signatures = {
        "sd_bus_open_system": ([C.POINTER(ptr)], C.c_int),
        "sd_bus_set_method_call_timeout": ([ptr, C.c_uint64], C.c_int),
        "sd_bus_get_property_string": ([ptr, text, text, text, text, C.POINTER(BusError), C.POINTER(ptr)], C.c_int),
        "sd_bus_error_free": ([C.POINTER(BusError)], ptr),
        "sd_bus_unref": ([ptr], ptr),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    libc.free.argtypes, libc.free.restype = [ptr], None
    bus = ptr()
    states = {}
    try:
        if lib.sd_bus_open_system(C.byref(bus)) < 0:
            raise TuningError("cannot verify CPU policy ownership: system bus unavailable")
        if lib.sd_bus_set_method_call_timeout(bus, 500000) < 0:
            raise TuningError("cannot bound the policy-owner query")
        for unit in POWER_MANAGERS:
            # systemd's documented D-Bus object-path label encoding. Inputs are
            # fixed unit names, never client-supplied path or service names.
            label = ''.join(c if c.isascii() and c.isalnum() else f'_{ord(c):02x}' for c in unit)
            path = ("/org/freedesktop/systemd1/unit/" + label).encode("ascii")
            error, value = BusError(), ptr()
            try:
                result = lib.sd_bus_get_property_string(bus, b"org.freedesktop.systemd1", path,
                    b"org.freedesktop.systemd1.Unit", b"ActiveState", C.byref(error), C.byref(value))
                if result < 0:
                    if error.name in (b"org.freedesktop.DBus.Error.UnknownObject", b"org.freedesktop.systemd1.NoSuchUnit"):
                        states[unit] = "not-loaded"
                    else:
                        raise TuningError("cannot verify CPU policy owner " + unit + ": " +
                                          (error.message or b"D-Bus property query failed").decode("utf-8", "replace"))
                else:
                    if not value.value:
                        raise TuningError("empty policy-owner reply")
                    state = C.string_at(value.value).decode("ascii")
                    if not re.fullmatch(r"[a-z-]{1,32}", state):
                        raise TuningError("invalid policy-owner reply")
                    states[unit] = state
            finally:
                if value.value:
                    libc.free(value)
                lib.sd_bus_error_free(C.byref(error))
    finally:
        if bus.value:
            lib.sd_bus_unref(bus)
    return states


def platform_report(root: Path) -> dict:
    """Bounded, passive inventory; no serial numbers, authorization or PM writes."""
    errors = []

    def read(path: Path):
        try:
            canonical = path.resolve(strict=True)
            if not canonical.is_relative_to((root / "sys").resolve()):
                raise TuningError("attribute escaped sysfs")
            return read_text(canonical)
        except FileNotFoundError:
            return None
        except (OSError, TuningError, ValueError) as exc:
            if len(errors) < 64:
                errors.append(f"{path.relative_to(root)}: {exc}")
            return None

    def fields(path: Path, names):
        return {name: value for name in names if (value := read(path / name)) is not None}

    pci = {}
    nodes = sorted((root / "sys/bus/pci/devices").glob("*"))
    for path in nodes[:256]:
        if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", path.name):
            continue
        pci[path.name] = fields(path, (
            "vendor", "device", "class", "current_link_speed", "current_link_width",
            "max_link_speed", "max_link_width", "power/control", "power/runtime_status",
            "aer_dev_correctable", "aer_dev_nonfatal", "aer_dev_fatal",
        ))
    if len(nodes) > 256:
        errors.append("PCI inventory limited to 256 devices")
    thunderbolt = {}
    for path in sorted((root / "sys/bus/thunderbolt/devices").glob("domain[0-9]*"))[:64]:
        thunderbolt[path.name] = fields(path, ("security", "iommu_dma_protection"))
    cpu = root / "sys/devices/system/cpu"
    idle = {p.name: fields(p, ("name", "latency", "residency", "disable"))
            for p in sorted((cpu / "cpu0/cpuidle").glob("state[0-9]*"))[:32]}
    throttling = {p.parent.name: fields(p, ("core_throttle_count", "package_throttle_count"))
                  for p in sorted(cpu.glob("cpu[0-9]*/thermal_throttle"))[:256]}
    return {
        "read_only": True,
        "intel_pstate": fields(cpu / "intel_pstate", ("status", "no_turbo", "hwp_dynamic_boost")),
        "platform_profile": read(root / "sys/firmware/acpi/platform_profile"),
        "platform_profile_choices": read(root / "sys/firmware/acpi/platform_profile_choices"),
        "pcie_aspm_policy": read(root / "sys/module/pcie_aspm/parameters/policy"),
        "pci": pci, "thunderbolt": thunderbolt,
        "cpu0_idle_states": idle, "thermal_throttle_counters": throttling,
        "i915_parameters": fields(root / "sys/module/i915/parameters", ("enable_guc", "enable_psr", "enable_fbc", "enable_dc")),
        "read_errors": errors,
        "guidance": [
            "Low PCIe speed at idle is not evidence of a bottleneck: compare under representative load.",
            "AER and thermal counters are cumulative: compare before/after snapshots on the same boot.",
            "ASPM, device runtime PM, NVMe APST, C-states, firmware and Thunderbolt authorization remain under existing platform policy.",
            "No firmware flash, raw MSR/PCI write, DMA-security reduction or automatic benchmark is performed.",
        ],
    }
