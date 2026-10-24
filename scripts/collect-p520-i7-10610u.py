#!/usr/bin/python3 -IB
"""Collect full read-only Intel i7-10610U / Pascal Quadro P520 tuning evidence.

Run ./collect-p520-i7-10610u.py with NO arguments. Every run collects full
BEFORE/AFTER CPU/Intel graphics inventories, NVIDIA inventory and 61 sample
ticks across 60 seconds. At EVERY tick, both graphics/memory offsets are queried
for all 16 P-states, plus current/bounds through four legacy getters (36 calls).
NVML symbols/unsupported responses and unwritten outputs remain explicit.

The same four files beside the physical script are REPLACED every run:
  p520-i7-10610u.txt          numbered readable report, inventories/ranges/errors
  p520-i7-10610u.json         categorized evidence and complete sampled readings
  p520-i7-10610u.samples.csv  all sampled metrics, values, units and errors
  p520-i7-10610u.offsets.csv  every timed offset query, including failures

Requires Linux, Python 3.10+ and the standard library. NVIDIA's installed
libnvidia-ml.so.1 supplies NVML; no Python NVIDIA bindings needed. lscpu,
cpupower, sensors and nvidia-smi are optional additional read-only sources.
CPU/iGPU collection covers P-state, EPP/EPB, idle/governor, uncore, both RAPL
backends, DPTF bounds/TCC offset, thermal/cooling state and graphics clocks/RC6.

Reports are private (0600), use fixed names, and replace the previous run.
A writer lock prevents overlapping runs. Complete candidates are staged, with
old inodes retained until replacement succeeds; uncertain recovery is retained
and reported. No date/UUID output names, Makefile or installer integration.

No sudo, profile/clock/offset/power writes, load generation, module loading,
installation, network or service/D-Bus access. No raw MSR/debugfs/firmware
probing. Reports contain GPU UUIDs/PCI IDs but no hostname, serials, process
lists, full environments or application/user data. Reads can wake the GPU.
Advertised offset bounds do not prove stable overclocking or setter support.
Bounded workers preserve completed records after timeout or a driver crash.
Nothing is automatically collected when the module is imported.

Interfaces:
  https://docs.nvidia.com/deploy/nvidia-smi/
  https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html
  https://docs.kernel.org/admin-guide/pm/intel_pstate.html
  https://docs.kernel.org/power/powercap/powercap.html
  https://docs.kernel.org/driver-api/thermal/intel_dptf.html
"""
from __future__ import annotations

import argparse
import csv
import errno
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import fcntl

VERSION = "2.2"
OUTPUT_PREFIX = "p520-i7-10610u"
OUTPUT_SUFFIXES = ("json", "txt", "samples.csv", "offsets.csv")
REPORT_TITLE = "P520 / INTEL i7-10610U TUNING EVIDENCE"
CPU_MODEL = "i7-10610U"
TARGET_CPU = "Intel Core i7-10610U"
IS_NVIDIA = True
SAMPLE_COUNT = 61
SAMPLE_INTERVAL_SECONDS = 1.0
SAMPLE_SPAN_SECONDS = (SAMPLE_COUNT - 1) * SAMPLE_INTERVAL_SECONDS
ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"}
MAX_CAPTURE = 4 * 1024 * 1024
MAX_SAMPLE_CAPTURE = 20 * 1024 * 1024
MAX_TOTAL_CAPTURE = 32 * 1024 * 1024
MAX_FILES = 4096
MAX_FILE_BYTES = 65536
MAX_ENTRIES = 256
TOTAL_SECONDS = 300
CPU_ROOT = Path("/sys/devices/system/cpu")
POLICY_FIELDS = ("affected_cpus", "related_cpus", "scaling_driver", "scaling_governor",
    "scaling_available_governors", "energy_performance_available_preferences",
    "energy_performance_preference", "scaling_available_frequencies", "scaling_min_freq",
    "scaling_max_freq", "scaling_cur_freq", "cpuinfo_min_freq", "cpuinfo_max_freq",
    "cpuinfo_cur_freq", "cpuinfo_avg_freq", "cpuinfo_transition_latency", "base_frequency", "bios_limit", "scaling_setspeed")
POLICY_SAMPLE_FIELDS = ("scaling_driver", "scaling_cur_freq", "cpuinfo_cur_freq", "cpuinfo_avg_freq",
    "scaling_min_freq", "scaling_max_freq", "scaling_governor", "energy_performance_preference", "scaling_setspeed")
PSTATE_FIELDS = ("status", "min_perf_pct", "max_perf_pct", "no_turbo",
                 "hwp_dynamic_boost", "num_pstates", "turbo_pct")
UNCORE_FIELDS = ("min_freq_khz", "max_freq_khz", "current_freq_khz",
                 "initial_min_freq_khz", "initial_max_freq_khz")
CONSTRAINT_RE = r"constraint_[0-9]+_(?:name|power_limit_uw|time_window_us|min_power_uw|max_power_uw|min_time_window_us|max_time_window_us)"
GPU_RE = r"(?:(?:gt|rps)_(?:cur|act|min|max|boost|RP0|RP1|RPn)_freq_mhz|rps_(?:up|down)_threshold_pct|throttle_reason_[a-z0-9_]+|rc6(?:p|pp)?_residency_ms|rc6_enable)"
SENSOR_RE = r"(?:temp[0-9]+_(?:label|input|max|crit|crit_alarm)|in[0-9]+_(?:label|input|min|max)|fan[0-9]+_input|power[0-9]+_(?:average|input|cap|max|crit|rated_max|max_interval)|energy[0-9]+_input)"
SAMPLE_INTERVAL = SAMPLE_INTERVAL_SECONDS
SAMPLE_SPAN = SAMPLE_SPAN_SECONDS

U, I, H, U64 = C.c_uint, C.c_int, C.c_void_p, C.c_ulonglong
OFFSET_SENTINELS = (-2147483648, -2147483647, -2147483646)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(key: str, value: object) -> None:
    print(json.dumps({"key": key, "value": value, "utc": utc()}, allow_nan=False), flush=True)


class Files:
    """Fixed kernel/public-system sources, bounded reads; no user-selected paths."""

    def __init__(self) -> None:
        self.count = 0
        self.bytes = 0

    @staticmethod
    def optional_absence(path: Path) -> dict:
        reason = ("Optional CPUFreq transition statistics are not exposed by this kernel/driver configuration."
                  if path.name == "stats" and "/cpufreq/" in str(path) else
                  "Optional interface is not exposed by the running kernel/driver configuration.")
        return {"status": "not_exposed", "path": str(path), "reason": reason}

    def read(self, path: Path, limit: int = MAX_FILE_BYTES, *, optional: bool = False) -> dict:
        self.count += 1
        if self.count > MAX_FILES or self.bytes >= MAX_CAPTURE:
            return {"status": "collection_limit", "path": str(path)}
        limit = min(limit, MAX_CAPTURE - self.bytes)
        try:
            canonical = path.resolve(strict=True)
            allowed = (str(canonical).startswith(("/sys/", "/proc/"))
                       or str(canonical) in {"/etc/os-release", "/usr/lib/os-release"})
            if not allowed:
                return {"status": "rejected_path", "path": str(path)}
            fd = os.open(canonical, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    return {"status": "not_regular", "path": str(path)}
                data = bytearray()
                while len(data) <= limit:
                    chunk = os.read(fd, min(8192, limit + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
            finally:
                os.close(fd)
            self.bytes += len(data)
            return {"status": "truncated" if len(data) > limit else "ok",
                    "value": bytes(data[:limit]).decode("utf-8", errors="replace").strip()}
        except OSError as exc:
            if optional and isinstance(exc, FileNotFoundError):
                return self.optional_absence(path)
            unavailable = {errno.ENODATA: ("no_data", "The kernel/driver exposes this attribute but returns no data."),
                errno.EOPNOTSUPP: ("not_supported", "The kernel/driver reports that this getter is unsupported."),
                errno.EAGAIN: ("temporarily_unavailable", "The kernel/driver could not provide a value at this sample.")}
            if exc.errno in unavailable:
                status, reason = unavailable[exc.errno]
                return {"status": status, "path": str(path), "errno": exc.errno, "reason": reason}
            return {"status": "permission_denied" if isinstance(exc, PermissionError) else
                    "absent" if isinstance(exc, FileNotFoundError) else "read_error",
                    "errno": exc.errno, "error": str(exc)}
        except RuntimeError as exc:
            return {"status": "path_error", "error": str(exc)}

    def children(self, path: Path, pattern: str, *, optional: bool = True) -> list[Path]:
        try:
            matches = []
            with os.scandir(path) as entries:
                for index, entry in enumerate(entries):
                    if index >= 4096:
                        emit("directory_limit", {"status": "collection_limit", "path": str(path), "entry_limit": 4096})
                        break
                    if re.fullmatch(pattern, entry.name):
                        matches.append(path / entry.name)
                        if len(matches) >= MAX_ENTRIES:
                            emit("directory_limit", {"status": "collection_limit", "path": str(path), "match_limit": MAX_ENTRIES})
                            break
            return sorted(matches)
        except OSError as exc:
            if optional and isinstance(exc, FileNotFoundError):
                emit("optional_interface_unavailable", self.optional_absence(path))
            else:
                status = "permission_denied" if isinstance(exc, PermissionError) else "directory_read_error"
                emit("directory_unavailable", {"status": status, "path": str(path),
                     "errno": exc.errno, "error": str(exc)})
            return []

    def readable_attributes(self, path: Path) -> list[str]:
        names = []
        for candidate in self.children(path, r"[A-Za-z][A-Za-z0-9_]*"):
            if candidate.name in {"reset", "trigger", "uevent"}:
                continue
            try:
                info = candidate.stat(follow_symlinks=False)
            except OSError as exc:
                emit("attribute_discovery_error", {"status": "read_error", "path": str(candidate),
                     "errno": exc.errno, "error": str(exc)})
                continue
            if stat.S_ISREG(info.st_mode) and info.st_mode & 0o444:
                names.append(candidate.name)
        return names

    def attributes(self, path: Path, names: tuple | list, *, optional: bool = True) -> dict:
        # These names are capability probes: individual attributes vary by driver,
        # operating mode and kernel version. Only ENOENT is expected absence.
        return {name: self.read(path / name, optional=optional) for name in names}


def cpu_inventory() -> None:
    files = Files()
    cpuinfo = files.read(Path("/proc/cpuinfo"), 1024 * 1024)
    emit("cpuinfo", cpuinfo)
    models = sorted(set(re.findall(r"^model name\s*:\s*(.+)$", cpuinfo.get("value", ""), re.M)))
    vendors = sorted(set(re.findall(r"^vendor_id\s*:\s*(.+)$", cpuinfo.get("value", ""), re.M)))
    emit("cpu_target", {"expected": TARGET_CPU, "models": models, "vendors": vendors,
        "matched": bool(models) and all(CPU_MODEL in name for name in models) and vendors == ["GenuineIntel"]})
    topology = discover_cpu(files)
    emit("cpu_global", readings(files, CPU_ROOT, ("online", "offline", "present", "possible", "smt/active", "smt/control")))
    emit("intel_pstate", readings(files, CPU_ROOT / "intel_pstate", PSTATE_FIELDS))
    emit("cpuidle_driver", readings(files, CPU_ROOT / "cpuidle", (
        "current_driver", "current_governor_ro", "current_governor", "available_governors", "intel_c1_demotion")))
    emit("cpufreq_global", readings(files, CPU_ROOT / "cpufreq", ("boost",)))
    for policy in topology["policies"]:
        emit(str(policy), policy_readings(files, policy, files.readable_attributes(policy)))
    for cpu in topology["cpus"]:
        emit(str(cpu), readings(files, cpu, ("online", "power/energy_perf_bias", "microcode/version",
            "topology/physical_package_id", "topology/die_id", "topology/core_id",
            "topology/thread_siblings_list", "topology/core_siblings_list")))
        emit(str(cpu / "thermal_throttle"), readings(files, cpu / "thermal_throttle",
             ("core_throttle_count", "package_throttle_count")))
    for path in topology["idle"]:
        emit(str(path), readings(files, path, ("name", "desc", "disable", "default_status",
            "latency", "residency", "time", "usage", "above", "below", "rejected")))
    for path in topology["uncore"]:
        emit(str(path), readings(files, path, UNCORE_FIELDS))
    for path in topology["rapl"]:
        names = ["name", "enabled", "energy_uj", "max_energy_range_uj", "max_power_range_uw"] + [
            p.name for p in files.children(path, CONSTRAINT_RE)]
        emit(str(path), readings(files, path, names))
    for path in topology["dptf"]:
        emit(str(path), readings(files, path, ("vendor", "device", "class", "tcc_offset_degree_celsius")))
        names = [p.name for p in files.children(path / "power_limits",
            r"power_limit_[0-9]+_(?:min_uw|max_uw|step_uw|tmin_us|tmax_us)|power_floor_status|power_floor_enable")]
        emit(str(path / "power_limits"), readings(files, path / "power_limits", names))
        emit(str(path / "workload_request"), readings(files, path / "workload_request",
             ("workload_available_types", "workload_type")))
    for path in topology["hwmon"]:
        emit(str(path), readings(files, path, ["name"] + [p.name for p in files.children(path, SENSOR_RE)]))
    for path in topology["thermal"]:
        emit(str(path), readings(files, path, ["type", "temp", "policy", "mode"] + [
            p.name for p in files.children(path, r"trip_point_[0-9]+_(?:type|temp|hyst)")]))
    for path in topology["cooling"]:
        emit(str(path), readings(files, path, ("type", "cur_state", "max_state")))
    for path in topology["supplies"]:
        emit(str(path), readings(files, path, ("type", "online", "status", "capacity", "power_now",
            "voltage_now", "current_now", "energy_now", "energy_full", "energy_full_design")))
    emit("platform_profile", readings(files, Path("/sys/firmware/acpi"), ("platform_profile", "platform_profile_choices")))
    emit("firmware_identity", readings(files, Path("/sys/class/dmi/id"), (
        "sys_vendor", "product_name", "product_version", "board_vendor", "board_name", "bios_vendor", "bios_version", "bios_date")))
    for path in (Path("/etc/os-release"), Path("/proc/pressure/cpu")):
        emit(str(path), files.read(path))
    for path in files.children(CPU_ROOT / "vulnerabilities", r"[a-z0-9_]+"):
        emit(str(path), files.read(path))
    emit("offset_availability", {"status": "not_exposed",
        "voltage_frequency_offsets": "No portable documented sysfs getter used for CPU/iGPU voltage or overclock offsets; never inferred as zero.",
        "tcc_offset": "Captured separately where exposed. This is a throttling-temperature offset, not undervolting."})
    for module, names in (
        ("intel_idle", ("max_cstate", "states_off")),
        ("processor", ("max_cstate", "ignore_ppc")),
    ):
        path = Path("/sys/module") / module / "parameters"
        emit(str(path), readings(files, path, names))
    governors = files.children(CPU_ROOT / "cpufreq", r"schedutil|ondemand|conservative")
    for policy in topology["policies"]:
        governors.extend(files.children(policy, r"schedutil|ondemand|conservative"))
        for path in files.children(policy / "stats", r"total_trans|time_in_state|trans_table"):
            emit(str(path), files.read(path))
    for path in governors:
        names = [p.name for p in files.children(path,
            r"(?:up_|down_)?rate_limit_us|sampling_rate(?:_min)?|up_threshold|down_threshold|sampling_down_factor|ignore_nice_load|io_is_busy|freq_step|powersave_bias")]
        emit(str(path), readings(files, path, names))
    for path in files.children(Path("/sys/class/platform-profile"), r"platform-profile-[0-9]+"):
        emit(str(path), readings(files, path, ("name", "profile", "choices")))
    for path in files.children(Path("/sys/bus/platform/devices"), r"(?:INT3400|INTC1040|INTC1041|INTC10A0):[0-9A-Fa-f]+"):
        emit(str(path), readings(files, path, ("production_mode",)))
        emit(str(path / "uuids"), readings(files, path / "uuids", ("available_uuids", "current_uuid")))
    pci = Path("/sys/bus/pci/devices")
    for path in files.children(pci, r"[0-9a-fA-F:.]+"):
        vendor, kind = files.read(path / "vendor"), files.read(path / "class")
        if vendor.get("value") in {"0x8086", "0x10de"} and kind.get("value", "").startswith("0x03"):
            emit(str(path) + "/graphics", readings(files, path, ("vendor", "device", "subsystem_vendor",
                "subsystem_device", "class", "revision", "current_link_speed", "current_link_width",
                "max_link_speed", "max_link_width", "power/control", "power/runtime_status",
                "power/runtime_active_time", "power/runtime_suspended_time")))
    # Select only known public CPU/idle tuning tokens; never retain a raw boot command line.
    boot = files.read(Path("/proc/cmdline"))
    patterns = (
        r"intel_pstate=(?:disable|active|passive|no_hwp|hwp_only|support_acpi_ppc|per_cpu_perf_limits|force|no_cas)(?:,(?:disable|active|passive|no_hwp|hwp_only|support_acpi_ppc|per_cpu_perf_limits|force|no_cas))*",
        r"(?:intel_idle|processor)\.max_cstate=[0-9]+",
        r"cpuidle\.off=[01]", r"idle=(?:halt|nomwait|poll)", r"nohz=(?:on|off)",
    )
    emit("kernel_tuning_context", {"boot_read_status": boot["status"],
        "selected_boot_parameters": [token for token in boot.get("value", "").split()
                                     if any(re.fullmatch(pattern, token) for pattern in patterns)]})
    for source in ("/proc/driver/nvidia/version", "/sys/module/nvidia/version"):
        if IS_NVIDIA:
            emit(source, files.read(Path(source)))
    emit("file_totals", {"reads_attempted": files.count, "bytes_read": files.bytes})


def rapl_zones(files: Files) -> list[Path]:
    pending = [(Path("/sys/class/powercap"), 0)]
    seen: set[str] = set()
    zones = []
    pattern = r"intel-rapl(?:-mmio)?(?::[0-9]+)*"
    while pending:
        parent, depth = pending.pop(0)
        for path in files.children(parent, pattern):
            if len(seen) >= MAX_ENTRIES:
                emit("rapl_limit", {"status": "collection_limit", "maximum": MAX_ENTRIES})
                return zones
            try:
                canonical = str(path.resolve(strict=True))
            except (OSError, RuntimeError) as exc:
                emit("rapl_path_error", {"status": "path_error", "path": str(path), "error": str(exc)})
                continue
            if not canonical.startswith("/sys/") or canonical in seen:
                continue
            seen.add(canonical)
            if ":" in path.name:
                zones.append(path)
            if depth < 3:
                pending.append((path, depth + 1))
    return zones


def unit_for(source: str, metric: str) -> str:
    if source.startswith("/sys/class/power_supply/"):
        if metric.startswith("voltage_"):
            return "uV"
        if metric.startswith("current_"):
            return "uA"
        if metric.startswith("energy_"):
            return "uWh"
        if metric.startswith("power_"):
            return "uW"
    if metric == "cpuinfo_transition_latency":
        return "ns"
    if metric.endswith("_freq_mhz"):
        return "MHz"
    if metric.endswith("_khz") or metric in {"scaling_cur_freq", "scaling_min_freq", "scaling_max_freq",
            "cpuinfo_cur_freq", "cpuinfo_avg_freq", "cpuinfo_min_freq", "cpuinfo_max_freq",
            "base_frequency", "bios_limit", "scaling_setspeed", "scaling_available_frequencies"}:
        return "kHz"
    if metric.endswith("_uj") or re.fullmatch(r"energy[0-9]+_input", metric):
        return "uJ"
    if metric.endswith("_uw") or re.fullmatch(r"power[0-9]+_(?:average|input|cap|max|crit|rated_max)", metric):
        return "uW"
    if metric.endswith("_us") or ("/cpuidle/state" in source and metric in {"time", "latency", "residency"}):
        return "us"
    if metric.endswith("_ms") or metric.endswith("_max_interval"):
        return "ms"
    if re.fullmatch(r"temp[0-9]+_(?:input|max|crit)", metric) or metric == "temp" or re.fullmatch(r"trip_point_[0-9]+_(?:temp|hyst)", metric):
        return "mC"
    if re.fullmatch(r"in[0-9]+_(?:input|min|max)", metric):
        return "mV"
    if re.fullmatch(r"fan[0-9]+_input", metric):
        return "RPM"
    if metric.endswith("_pct") or metric.endswith("_percent") or metric in {"capacity", "turbo_pct"}:
        return "%"
    if metric == "tcc_offset_degree_celsius":
        return "C offset"
    return "raw"


def readings(files: Files, path: Path, names: tuple | list, *, optional: bool = True) -> dict:
    values = files.attributes(path, names, optional=optional)
    for name, result in values.items():
        result["unit"] = unit_for(str(path), name)
    return values


def discover_policies(files: Files, cpus: list[Path]) -> list[Path]:
    roots = files.children(CPU_ROOT / "cpufreq", r"policy[0-9]+")
    roots += [cpu / "cpufreq" for cpu in cpus]
    policies, seen_roots, seen_policies, discovery = [], set(), set(), []
    for root in roots:
        try:
            canonical = str(root.resolve(strict=True))
        except FileNotFoundError:
            continue  # An offline CPU may have no policy link.
        except (OSError, RuntimeError) as exc:
            emit("cpufreq_discovery_error", {"status": "path_error", "path": str(root), "error": str(exc)})
            continue
        if not canonical.startswith(str(CPU_ROOT) + "/") or canonical in seen_roots:
            continue
        seen_roots.add(canonical)
        # Kernel policy roots are standard. Also inspect one numeric child level
        # for layouts such as the policy1/0 directory supplied by the user.
        for path in (root, *files.children(root, r"[0-9]+")):
            try:
                resolved = str(path.resolve(strict=True))
                info = path.stat()
            except (OSError, RuntimeError) as exc:
                emit("cpufreq_discovery_error", {"status": "path_error", "path": str(path), "error": str(exc)})
                continue
            if not resolved.startswith(str(CPU_ROOT) + "/") or resolved in seen_policies or not stat.S_ISDIR(info.st_mode):
                continue
            names = files.readable_attributes(path)
            if not set(names).intersection({"scaling_driver", "cpuinfo_max_freq", "scaling_cur_freq", "cpuinfo_avg_freq"}):
                continue
            seen_policies.add(resolved)
            policies.append(path)
            discovery.append({"path": str(path), "canonical_path": resolved,
                "readable_attributes": names, "known_attributes_not_exposed": sorted(set(POLICY_FIELDS) - set(names))})
    emit("cpufreq_policy_discovery", {"policies": discovery,
        "policy_count": len(policies), "candidate_roots_considered": len(roots),
        "unique_policy_roots": len(seen_roots)})
    return policies


def policy_readings(files: Files, policy: Path, names: list[str] | tuple[str, ...]) -> dict:
    # Discovered attributes should remain readable. Disappearance after discovery
    # is retained as a real read failure instead of being reclassified as optional.
    values = readings(files, policy, names, optional=False)
    speed = values.get("scaling_setspeed")
    if speed and speed.get("status") == "ok" and speed.get("value") == "<unsupported>":
        speed.update(status="not_applicable", reason="scaling_setspeed is functional only with the userspace governor.")
    return values


def discover_cpu(files: Files) -> dict:
    cpus = files.children(CPU_ROOT, r"cpu[0-9]+", optional=False)
    topology = {
        "cpus": cpus,
        "policies": discover_policies(files, cpus),
        "uncore": files.children(CPU_ROOT / "intel_uncore_frequency", r"(?:package_[0-9]+_die_[0-9]+|uncore[0-9]+)"),
        "idle": [state for cpu in cpus for state in files.children(cpu / "cpuidle", r"state[0-9]+")],
        "rapl": rapl_zones(files),
        "hwmon": files.children(Path("/sys/class/hwmon"), r"hwmon[0-9]+"),
        "thermal": files.children(Path("/sys/class/thermal"), r"thermal_zone[0-9]+"),
        "cooling": files.children(Path("/sys/class/thermal"), r"cooling_device[0-9]+"),
        "supplies": files.children(Path("/sys/class/power_supply"), r"[A-Za-z0-9_.:-]+"),
        "dptf": [],
    }
    for device in files.children(Path("/sys/bus/pci/devices"), r"[0-9a-fA-F:.]+"):
        if files.read(device / "vendor").get("value") != "0x8086":
            continue
        available = files.children(device, r"power_limits|workload_request|tcc_offset_degree_celsius")
        if available:
            topology["dptf"].append(device)
    return topology


def graphics_groups(files: Files) -> tuple[list[dict], list[dict]]:
    groups, identities = [], []
    seen: set[str] = set()
    for card in files.children(Path("/sys/class/drm"), r"card[0-9]+"):
        if files.read(card / "device/vendor").get("value") != "0x8086":
            continue
        identity = {"card": str(card), "fields": readings(files, card / "device",
            ("vendor", "device", "subsystem_vendor", "subsystem_device", "class", "revision"))}
        try:
            identity["driver"] = (card / "device/driver").resolve(strict=True).name
        except (OSError, RuntimeError) as exc:
            identity["driver_error"] = str(exc)
        identities.append(identity)
        directories = [card, card / "power", *files.children(card / "gt", r"gt[0-9]+")]
        for directory in directories:
            names, aliases = [], {}
            for path in files.children(directory, GPU_RE):
                try:
                    canonical = str(path.resolve(strict=True))
                except (OSError, RuntimeError):
                    names.append(path.name)  # The read will retain the exact failure.
                    continue
                if canonical in seen:
                    aliases[path.name] = canonical
                else:
                    seen.add(canonical)
                    names.append(path.name)
            if names or aliases:
                groups.append({"path": directory, "names": names, "aliases": aliases})
        groups.append({"path": card / "device/power", "names": [
            "control", "runtime_status", "runtime_active_time", "runtime_suspended_time"], "aliases": {}})
        for engine in files.children(card / "engine", r"[a-z]+[0-9]+"):
            groups.append({"path": engine, "names": [
                "heartbeat_interval_ms", "preempt_timeout_ms", "timeslice_duration_ms"], "aliases": {}})
    return groups, identities


def graphics_inventory() -> None:
    files = Files()
    groups, identities = graphics_groups(files)
    emit("intel_graphics", {"matched": bool(identities), "devices": identities})
    for group in groups:
        emit(str(group["path"]), {"readings": readings(files, group["path"], group["names"]), "aliases": group["aliases"]})
    emit("i915_parameters", readings(files, Path("/sys/module/i915/parameters"), (
        "enable_guc", "enable_dc", "enable_fbc", "enable_psr", "enable_rc6")))
    if not identities:
        emit("intel_graphics_unavailable", {"status": "not_exposed", "reason": "No Intel DRM card was exposed; no device node or debugfs access attempted."})


def number(result: dict) -> int | float | None:
    if result.get("status") != "ok":
        return None
    value = result.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return None


class Deltas:
    def __init__(self) -> None:
        self.previous: dict[str, tuple[int | float, float, int | float | None]] = {}

    def counter(self, key: str, reading: dict, scale: float, unit: str,
                modulus: int | float | None = None, wrap: bool = False) -> dict:
        value = number(reading)
        if value is None:
            return {"status": "source_unavailable", "source_status": reading.get("status"), "unit": unit}
        now = time.monotonic()
        previous = self.previous.get(key)
        self.previous[key] = value, now, modulus
        if not previous:
            return {"status": "baseline", "unit": unit}
        if previous[2] != modulus:
            return {"status": "counter_range_changed", "unit": unit}
        delta = value - previous[0]
        if delta < 0:
            if wrap and modulus is not None and modulus > 0 and 0 <= value <= modulus and 0 <= previous[0] <= modulus:
                delta += modulus
            else:
                return {"status": "counter_reset_or_wrap", "unit": unit}
        elapsed = now - previous[1]
        if elapsed <= 0:
            return {"status": "invalid_interval", "unit": unit}
        return {"status": "ok", "value": delta * scale / elapsed, "unit": unit, "interval_seconds": elapsed,
                "assumption": "At most one wrap; reset/multiple wraps cannot be distinguished." if wrap else
                              "Counter delta per elapsed wall time."}


def cpu_busy(files: Files, previous: dict[str, tuple[int, int]]) -> dict:
    raw = files.read(Path("/proc/stat"))
    result = {}
    for line in raw.get("value", "").splitlines():
        words = line.split()
        if not words or not re.fullmatch(r"cpu[0-9]*", words[0]):
            continue
        try:
            values = [int(value) for value in words[1:9]]
            if len(values) != 8:
                raise ValueError("missing CPU counters")
            total, idle = sum(values), values[3] + values[4]
            old = previous.get(words[0])
            previous[words[0]] = total, idle
            if not old:
                result[words[0] + "_busy_percent"] = {"status": "baseline", "unit": "%"}
            elif total <= old[0] or idle < old[1]:
                result[words[0] + "_busy_percent"] = {"status": "counter_reset_or_no_delta", "unit": "%"}
            else:
                busy = 100 * ((total - old[0]) - (idle - old[1])) / (total - old[0])
                result[words[0] + "_busy_percent"] = {"status": "ok", "value": max(0.0, min(100.0, busy)), "unit": "%"}
        except ValueError as exc:
            result[words[0]] = {"status": "parse_error", "error": str(exc)}
    return result or {"cpu_busy_percent": {"status": "source_unavailable", "source": raw}}


def sample_group(index: int, start: float, tag: str, source: Path | str, values: dict) -> None:
    emit("sample_group", {"index": index, "elapsed_seconds": time.monotonic() - start, "tag": tag,
                         "source": str(source), "readings": values})


class Offset(C.Structure):
    # nvmlClockOffset_v1_t, not a voltage/frequency lock or nvidia-settings ABI.
    _fields_ = [("version", U), ("type", U), ("pstate", U),
                ("clockOffsetMHz", I), ("minClockOffsetMHz", I), ("maxClockOffsetMHz", I)]


class Utilization(C.Structure):
    _fields_ = [("gpu", U), ("memory", U)]


class Memory(C.Structure):
    _fields_ = [("total", U64), ("free", U64), ("used", U64)]


class NvError(Exception):
    def __init__(self, result: dict) -> None:
        self.result = result
        super().__init__(str(result))


class NVML:
    def __init__(self) -> None:
        # Only instantiated in a time/size-bounded worker with sanitized env.
        self.library = C.CDLL("libnvidia-ml.so.1")
        self.call("nvmlInit_v2", [], [])

    def call(self, name: str, types: list, args: list) -> None:
        if not (name.startswith(("nvmlDeviceGet", "nvmlSystemGet")) or name in {"nvmlInit_v2", "nvmlShutdown"}):
            raise ValueError("NVML function is outside the read-only allowlist")
        try:
            fn = getattr(self.library, name)
        except AttributeError:
            raise NvError({"status": "symbol_missing", "function": name}) from None
        fn.argtypes, fn.restype = types, I
        rc = fn(*args)
        if rc:
            names = {1: "UNINITIALIZED", 2: "INVALID_ARGUMENT", 3: "NOT_SUPPORTED", 4: "NO_PERMISSION",
                     6: "NOT_FOUND", 7: "INSUFFICIENT_SIZE", 9: "DRIVER_NOT_LOADED", 10: "TIMEOUT",
                     13: "FUNCTION_NOT_FOUND", 15: "GPU_IS_LOST", 18: "LIB_RM_VERSION_MISMATCH",
                     21: "NO_DATA", 25: "ARGUMENT_VERSION_MISMATCH", 999: "UNKNOWN"}
            raise NvError({"status": "nvml_error", "function": name, "code": rc, "name": names.get(rc, "UNMAPPED_ERROR")})

    def text(self, name: str, handle: H | None = None) -> str:
        data = C.create_string_buffer(256)
        types, args = ([H], [handle]) if handle is not None else ([], [])
        self.call(name, types + [C.POINTER(C.c_char), U], args + [data, len(data)])
        if not data.value:
            raise NvError({"status": "incomplete_response", "function": name, "unwritten_fields": ["text"]})
        return data.value.decode("utf-8", errors="replace")

    def scalar(self, name: str, handle: H | None = None, *extra: int, signed: bool = False, wide: bool = False) -> int:
        kind = U64 if wide else I if signed else U
        sentinel = -(1 << 31) if signed and not wide else (1 << (C.sizeof(kind) * 8)) - 1
        value = kind(sentinel)
        types, args = ([H], [handle]) if handle is not None else ([], [])
        self.call(name, types + [U] * len(extra) + [C.POINTER(type(value))], args + list(extra) + [C.byref(value)])
        if value.value == sentinel:
            raise NvError({"status": "incomplete_response", "function": name, "unwritten_fields": ["value"]})
        return value.value

    def pair(self, name: str, handle: H, *extra: int, signed: bool = False) -> list[int]:
        kind, sentinel = (I, -(1 << 31)) if signed else (U, (1 << 32) - 1)
        a, b = kind(sentinel), kind(sentinel)
        self.call(name, [H] + [U] * len(extra) + [C.POINTER(type(a))] * 2,
                  [handle, *extra, C.byref(a), C.byref(b)])
        if sentinel in (a.value, b.value):
            raise NvError({"status": "incomplete_response", "function": name,
                           "unwritten_fields": [key for key, value in (("first", a.value), ("second", b.value)) if value == sentinel]})
        return [a.value, b.value]

    def array(self, name: str, handle: H, *extra: int, limit: int = 4096) -> list[int]:
        sentinel = (1 << 32) - 1
        count, values = U(limit), (U * limit)(*([sentinel] * limit))
        try:
            self.call(name, [H] + [U] * len(extra) + [C.POINTER(U)] * 2,
                      [handle, *extra, C.byref(count), values])
        except NvError as exc:
            exc.result.update(required_count=count.value, capacity=limit)
            raise
        if count.value > limit:
            raise NvError({"status": "invalid_response", "function": name, "reported_count": count.value, "capacity": limit})
        if sentinel in values[:count.value]:
            raise NvError({"status": "incomplete_response", "function": name, "unwritten_fields": ["array_values"]})
        return sorted(set(values[:count.value]))

    def struct(self, name: str, handle: H, kind: type[C.Structure]) -> dict:
        value = kind()
        sentinels = {field: (1 << (C.sizeof(field_type) * 8)) - 1 for field, field_type in kind._fields_}
        for field, sentinel in sentinels.items():
            setattr(value, field, sentinel)
        self.call(name, [H, C.POINTER(kind)], [handle, C.byref(value)])
        unwritten = [field for field, sentinel in sentinels.items() if getattr(value, field) == sentinel]
        if unwritten:
            raise NvError({"status": "incomplete_response", "function": name, "unwritten_fields": unwritten})
        return {field: getattr(value, field) for field, _ in kind._fields_}

    def supported_pstates(self, handle: H) -> list[int]:
        # NVML takes the ARRAY SIZE IN BYTES, not the element count.
        # It fills the unused tail with NVML_PSTATE_UNKNOWN (32).
        values = (I * 16)(*([OFFSET_SENTINELS[0]] * 16))
        self.call("nvmlDeviceGetSupportedPerformanceStates", [H, C.POINTER(I), U],
                  [handle, values, C.sizeof(values)])
        if any(value not in {*range(16), 32} for value in values):
            raise NvError({"status": "incomplete_response", "function": "nvmlDeviceGetSupportedPerformanceStates",
                           "returned_states": list(values)})
        result = sorted({value for value in values if value != 32})
        if not result:
            raise NvError({"status": "incomplete_response", "function": "nvmlDeviceGetSupportedPerformanceStates",
                           "reason": "No supported performance states returned"})
        return result

    def offset(self, handle: H, domain: int, pstate: int) -> dict:
        value = Offset(C.sizeof(Offset) | (1 << 24), domain, pstate, *OFFSET_SENTINELS)
        self.call("nvmlDeviceGetClockOffsets", [H, C.POINTER(Offset)], [handle, C.byref(value)])
        fields = ("clockOffsetMHz", "minClockOffsetMHz", "maxClockOffsetMHz")
        unwritten = [field for field, sentinel in zip(fields, OFFSET_SENTINELS) if getattr(value, field) == sentinel]
        if unwritten:
            raise NvError({"status": "incomplete_response", "function": "nvmlDeviceGetClockOffsets",
                           "unwritten_fields": unwritten, "pstate": pstate, "clock_type": domain,
                           "returned_fields": {field: getattr(value, field) for field in fields if field not in unwritten}})
        result = {"current_mhz": value.clockOffsetMHz, "minimum_mhz": value.minClockOffsetMHz,
                  "maximum_mhz": value.maxClockOffsetMHz, "pstate": pstate, "clock_type": domain,
                  "abi_version": value.version}
        if value.minClockOffsetMHz > value.maxClockOffsetMHz:
            raise NvError({"status": "invalid_response", "function": "nvmlDeviceGetClockOffsets", "value": result})
        return result

    def legacy_offset_current(self, handle: H, prefix: str) -> int:
        value = I(OFFSET_SENTINELS[0])
        name = f"nvmlDeviceGet{prefix}ClkVfOffset"
        self.call(name, [H, C.POINTER(I)], [handle, C.byref(value)])
        if value.value == OFFSET_SENTINELS[0]:
            raise NvError({"status": "incomplete_response", "function": name, "unwritten_fields": ["current_mhz"]})
        return value.value

    def legacy_offset_bounds(self, handle: H, prefix: str) -> list[int]:
        minimum, maximum = I(OFFSET_SENTINELS[1]), I(OFFSET_SENTINELS[2])
        name = f"nvmlDeviceGet{prefix}ClkMinMaxVfOffset"
        self.call(name, [H, C.POINTER(I), C.POINTER(I)], [handle, C.byref(minimum), C.byref(maximum)])
        unwritten = [field for field, value, sentinel in (
            ("minimum_mhz", minimum.value, OFFSET_SENTINELS[1]),
            ("maximum_mhz", maximum.value, OFFSET_SENTINELS[2])) if value == sentinel]
        if unwritten:
            raise NvError({"status": "incomplete_response", "function": name, "unwritten_fields": unwritten})
        if minimum.value > maximum.value:
            raise NvError({"status": "invalid_response", "function": name, "value": [minimum.value, maximum.value]})
        return [minimum.value, maximum.value]


def query(function, *, unit: str | None = None) -> dict:
    try:
        result = {"status": "ok", "value": function()}
    except NvError as exc:
        result = dict(exc.result)
    if unit:
        result["unit"] = unit
    return result


def offset_query(name: str, function) -> dict:
    result = query(function, unit="MHz-offset")
    result.setdefault("function", name)
    return result


def offset_queries(api: NVML, handle: H):
    """All offset getters, shared by inventory and EVERY timed sample."""
    for domain, domain_name, legacy in ((0, "graphics", "Gpc"), (2, "memory", "Mem")):
        for pstate in range(16):
            yield f"offsets/{domain_name}/P{pstate}", offset_query("nvmlDeviceGetClockOffsets",
                lambda d=domain, p=pstate: api.offset(handle, d, p))
        yield f"legacy_offsets/{domain_name}/current", offset_query(f"nvmlDeviceGet{legacy}ClkVfOffset",
            lambda prefix=legacy: api.legacy_offset_current(handle, prefix))
        yield f"legacy_offsets/{domain_name}/minimum_maximum", offset_query(f"nvmlDeviceGet{legacy}ClkMinMaxVfOffset",
            lambda prefix=legacy: api.legacy_offset_bounds(handle, prefix))


def offset_fields(key: str, result: dict) -> dict:
    """Keep zero as a real reading; never fill absent/error fields with zero."""
    fields: dict = {}
    if result.get("status") != "ok":
        return fields
    value = result.get("value")
    if key.startswith("offsets/") and isinstance(value, dict):
        fields = {name: value[name] for name in ("current_mhz", "minimum_mhz", "maximum_mhz")}
    elif key.endswith("/current") and isinstance(value, int):
        fields["current_mhz"] = value
    elif key.endswith("/minimum_maximum") and isinstance(value, list) and len(value) == 2:
        fields.update(minimum_mhz=value[0], maximum_mhz=value[1])
    if "minimum_mhz" in fields:
        low, high = fields["minimum_mhz"], fields["maximum_mhz"]
        fields["advertised_range_state"] = "zero_only" if low == high == 0 else "fixed" if low == high else "adjustable"
    return fields


def offset_snapshot(api: NVML, handle: H, identity: str, sample_index: int, elapsed: float) -> dict:
    started = time.monotonic()
    result: dict = {"started_utc": utc(), "streamed_query_count": 0}
    # Publish each completed read before trying the next driver call. A later
    # stalled call must not erase the offsets already received by the parent.
    for key, reading in offset_queries(api, handle):
        emit("offset_query_sample", {"sample_index": sample_index, "gpu_uuid": identity,
             "sample_elapsed_seconds": elapsed, "elapsed_seconds": elapsed + time.monotonic() - started,
             "captured_utc": utc(), "query": key, "result": reading})
        result["streamed_query_count"] += 1
    result["active_pstate_after"] = query(lambda: api.scalar("nvmlDeviceGetPerformanceState", handle))
    result["duration_seconds"] = time.monotonic() - started
    return result


def gpu_handles(api: NVML) -> list[tuple[str, H]]:
    count = api.scalar("nvmlDeviceGetCount_v2")
    if not 0 <= count <= 16:
        raise NvError({"status": "collection_limit", "gpu_count": count, "maximum": 16})
    targets = []
    for index in range(count):
        handle = H()
        try:
            api.call("nvmlDeviceGetHandleByIndex_v2", [U, C.POINTER(H)], [index, C.byref(handle)])
            identity = api.text("nvmlDeviceGetUUID", handle)
            name = api.text("nvmlDeviceGetName", handle)
            if not re.fullmatch(r"GPU-[A-Za-z0-9-]{8,100}", identity):
                raise NvError({"status": "invalid_response", "function": "nvmlDeviceGetUUID"})
            matched = bool(re.search(r"\bP520\b", name, re.I))
            emit("gpu_identity", {"index": index, "uuid": identity, "name": name, "target_p520": matched})
            if matched:
                targets.append((identity, handle))
        except NvError as exc:
            emit("gpu_identity", {"index": index, **exc.result})
    emit("gpu_target", {"expected": "NVIDIA Quadro P520 (Pascal)", "matched": bool(targets), "matched_count": len(targets)})
    return targets


def gpu_metrics(api: NVML, handle: H) -> dict:
    fields = {}
    for key, function, extra, unit in (
        ("pstate", "nvmlDeviceGetPerformanceState", (), "P-state"),
        ("temperature", "nvmlDeviceGetTemperature", (0,), "C"),
        ("power_usage", "nvmlDeviceGetPowerUsage", (), "mW"),
        ("graphics_clock", "nvmlDeviceGetClockInfo", (0,), "MHz"),
        ("sm_clock", "nvmlDeviceGetClockInfo", (1,), "MHz"),
        ("memory_clock", "nvmlDeviceGetClockInfo", (2,), "MHz"),
        ("video_clock", "nvmlDeviceGetClockInfo", (3,), "MHz"),
        ("power_limit", "nvmlDeviceGetPowerManagementLimit", (), "mW"),
        ("enforced_power_limit", "nvmlDeviceGetEnforcedPowerLimit", (), "mW"),
        ("pcie_generation", "nvmlDeviceGetCurrPcieLinkGeneration", (), "generation"),
        ("pcie_width", "nvmlDeviceGetCurrPcieLinkWidth", (), "lanes"),
        ("pcie_tx_throughput", "nvmlDeviceGetPcieThroughput", (0,), "KB/s over 20 ms"),
        ("pcie_rx_throughput", "nvmlDeviceGetPcieThroughput", (1,), "KB/s over 20 ms"),
        ("fan_speed", "nvmlDeviceGetFanSpeed", (), "%"),
    ):
        fields[key] = query(lambda f=function, e=extra: api.scalar(f, handle, *e), unit=unit)
    fields["utilization"] = query(lambda: api.struct("nvmlDeviceGetUtilizationRates", handle, Utilization), unit="%")
    fields["memory"] = query(lambda: api.struct("nvmlDeviceGetMemoryInfo", handle, Memory), unit="bytes")
    reasons = query(lambda: api.scalar("nvmlDeviceGetCurrentClocksEventReasons", handle, wide=True))
    if reasons["status"] == "symbol_missing":
        reasons = query(lambda: api.scalar("nvmlDeviceGetCurrentClocksThrottleReasons", handle, wide=True))
    if reasons["status"] == "ok":
        names = {1: "idle", 2: "application_clocks", 4: "software_power_cap", 8: "hardware_slowdown",
                 16: "sync_boost", 32: "software_thermal", 64: "hardware_thermal", 128: "hardware_power_brake", 256: "display_clock"}
        reasons["active"] = [name for bit, name in names.items() if reasons["value"] & bit]
        reasons["unknown_mask_hex"] = hex(reasons["value"] & ~sum(names))
    fields["clock_event_reasons"] = reasons
    return fields


def gpu_inventory(api: NVML, targets: list[tuple[str, H]]) -> None:
    for identity, handle in targets:
        # Offsets are a required part of this collector; query them before the
        # optional telemetry and potentially large clock tables.
        for key, result in offset_queries(api, handle):
            emit(identity + "/" + key, result)
        emit(identity + "/telemetry", gpu_metrics(api, handle))
        for name in ("nvmlDeviceGetVbiosVersion",):
            emit(identity + "/" + name, query(lambda n=name: api.text(n, handle)))
        for name, unit in (
            ("nvmlDeviceGetArchitecture", "NVML architecture enum; Pascal=4"),
            ("nvmlDeviceGetNumGpuCores", "CUDA cores"), ("nvmlDeviceGetMemoryBusWidth", "bits"),
            ("nvmlDeviceGetPowerManagementLimit", "mW"), ("nvmlDeviceGetPowerManagementDefaultLimit", "mW"),
            ("nvmlDeviceGetEnforcedPowerLimit", "mW"), ("nvmlDeviceGetPersistenceMode", "boolean"),
            ("nvmlDeviceGetPowerManagementMode", "boolean"), ("nvmlDeviceGetComputeMode", "enum"),
            ("nvmlDeviceGetDisplayMode", "boolean"), ("nvmlDeviceGetDisplayActive", "boolean"),
            ("nvmlDeviceGetCurrPcieLinkGeneration", "generation"), ("nvmlDeviceGetMaxPcieLinkGeneration", "generation"),
            ("nvmlDeviceGetCurrPcieLinkWidth", "lanes"), ("nvmlDeviceGetMaxPcieLinkWidth", "lanes"),
        ):
            emit(identity + "/" + name, query(lambda n=name: api.scalar(n, handle), unit=unit))
        emit(identity + "/power_limit_min_max", query(lambda: api.pair("nvmlDeviceGetPowerManagementLimitConstraints", handle), unit="mW"))
        emit(identity + "/cuda_compute_capability_major_minor", query(
            lambda: api.pair("nvmlDeviceGetCudaComputeCapability", handle, signed=True)))
        emit(identity + "/auto_boost_current_default", query(lambda: api.pair("nvmlDeviceGetAutoBoostedClocksEnabled", handle)))
        supported_reasons = query(lambda: api.scalar("nvmlDeviceGetSupportedClocksEventReasons", handle, wide=True))
        if supported_reasons["status"] == "symbol_missing":
            supported_reasons = query(lambda: api.scalar("nvmlDeviceGetSupportedClocksThrottleReasons", handle, wide=True))
        emit(identity + "/supported_clock_event_mask", supported_reasons)
        for threshold, name in enumerate(("shutdown", "slowdown", "memory_max", "gpu_max")):
            emit(identity + "/temperature_threshold/" + name,
                 query(lambda t=threshold: api.scalar("nvmlDeviceGetTemperatureThreshold", handle, t), unit="C"))
        supported_states = query(lambda: api.supported_pstates(handle))
        emit(identity + "/supported_performance_states", supported_states)
        valid_states = set(supported_states["value"]) if supported_states["status"] == "ok" else None
        for domain, domain_name, legacy in ((0, "graphics", "Gpc"), (2, "memory", "Mem")):
            for name in ("nvmlDeviceGetMaxClockInfo", "nvmlDeviceGetApplicationsClock", "nvmlDeviceGetDefaultApplicationsClock"):
                emit(f"{identity}/{domain_name}/{name}", query(lambda n=name, d=domain: api.scalar(n, handle, d), unit="MHz"))
            for pstate in range(16):
                if valid_states is not None and pstate not in valid_states:
                    emit(f"{identity}/pstate_clocks/{domain_name}/P{pstate}", {
                        "status": "not_applicable", "pstate": pstate,
                        "reason": "This P-state is not in the driver's supported-performance-state list.", "unit": "MHz"})
                    continue
                emit(f"{identity}/pstate_clocks/{domain_name}/P{pstate}", query(
                    lambda d=domain, p=pstate: api.pair("nvmlDeviceGetMinMaxClockOfPState", handle, d, p), unit="MHz"))
        memories = query(lambda: api.array("nvmlDeviceGetSupportedMemoryClocks", handle, limit=256), unit="MHz")
        emit(identity + "/supported_memory_clocks", memories)
        if memories["status"] == "ok":
            for memory in memories["value"]:
                emit(f"{identity}/supported_clock_pairs/memory_{memory}_mhz", query(
                    lambda m=memory: api.array("nvmlDeviceGetSupportedGraphicsClocks", handle, m), unit="graphics MHz"))
        emit(identity + "/identity_after_collection", query(lambda: api.text("nvmlDeviceGetUUID", handle)))


def samples(api: NVML | None, targets: list[tuple[str, H]], count: int, interval: float) -> None:
    files = Files()
    topology = discover_cpu(files)
    gpu_groups, identities = graphics_groups(files)
    emit("sampling_topology", {"policy_count": len(topology["policies"]), "cpu_count": len(topology["cpus"]),
        "rapl_domains": [str(p) for p in topology["rapl"]], "intel_graphics": identities})
    policy_fields = {}
    for path in topology["policies"]:
        exposed = set(files.readable_attributes(path))
        policy_fields[str(path)] = [name for name in POLICY_SAMPLE_FIELDS if name in exposed]
    constraints = {str(path): [p.name for p in files.children(path, CONSTRAINT_RE)] for path in topology["rapl"]}
    thermal_fields = {str(path): [p.name for p in files.children(path, r"(?:temp[0-9]+_input|power[0-9]+_(?:average|input)|energy[0-9]+_input|in[0-9]+_input|fan[0-9]+_input)")] for path in topology["hwmon"]}
    deltas, busy_previous = Deltas(), {}
    start = time.monotonic()
    for index in range(count):
        if index:
            time.sleep(max(0.0, start + index * interval - time.monotonic()))
        files = Files()
        emit("sample_start", {"index": index, "elapsed_seconds": time.monotonic() - start})
        if api:
            for identity, handle in targets:
                snapshot = offset_snapshot(api, handle, identity, index, time.monotonic() - start)
                sample_group(index, start, "nvidia_offset_state", identity, snapshot)
        for policy in topology["policies"]:
            sample_group(index, start, "cpufreq", policy, policy_readings(files, policy, policy_fields[str(policy)]))
        sample_group(index, start, "intel_pstate", CPU_ROOT / "intel_pstate",
                     readings(files, CPU_ROOT / "intel_pstate", PSTATE_FIELDS))
        sample_group(index, start, "cpu_busy", "/proc/stat", cpu_busy(files, busy_previous))
        for path in topology["rapl"]:
            values = readings(files, path, ["name", "enabled", "energy_uj", "max_energy_range_uj"] + constraints[str(path)])
            maximum = number(values["max_energy_range_uj"])
            if maximum is not None and maximum > 0:
                energy = number(values["energy_uj"])
                if energy is not None and not 0 <= energy <= maximum:
                    values["estimated_average_watts"] = {"status": "invalid_counter", "unit": "W"}
                else:
                    values["estimated_average_watts"] = deltas.counter(
                        str(path) + "/energy_uj", values["energy_uj"], 1e-6, "W", maximum, wrap=True)
            else:
                values["estimated_average_watts"] = {"status": "range_unavailable", "unit": "W",
                    "source_status": values["max_energy_range_uj"].get("status")}
            sample_group(index, start, "rapl", path, values)
        for group in gpu_groups:
            values = readings(files, group["path"], group["names"])
            for name, reading in list(values.items()):
                if name.endswith("_residency_ms"):
                    values[name + "_counter_percent"] = deltas.counter(
                        str(group["path"] / name), reading, 0.1, "%")
            sample_group(index, start, "intel_gpu", group["path"], values)
        for cpu in topology["cpus"]:
            sample_group(index, start, "epb", cpu / "power",
                         readings(files, cpu / "power", ("energy_perf_bias",)))
            sample_group(index, start, "throttle", cpu / "thermal_throttle",
                         readings(files, cpu / "thermal_throttle", ("core_throttle_count", "package_throttle_count")))
        for path in topology["idle"]:
            values = readings(files, path, ("name", "disable", "time", "usage", "above", "below", "rejected"))
            values["software_idle_counter_percent"] = deltas.counter(str(path / "time"), values["time"], 0.0001, "%")
            sample_group(index, start, "cpuidle", path, values)
        for path in topology["uncore"]:
            sample_group(index, start, "uncore", path, readings(files, path, UNCORE_FIELDS))
        for path in topology["hwmon"]:
            sample_group(index, start, "sensors", path, readings(files, path, ["name"] + thermal_fields[str(path)]))
        for path in topology["thermal"]:
            sample_group(index, start, "thermal_zone", path, readings(files, path, ("type", "temp")))
        for path in topology["cooling"]:
            sample_group(index, start, "cooling", path, readings(files, path, ("type", "cur_state", "max_state")))
        for path in topology["supplies"]:
            sample_group(index, start, "power_supply", path,
                         readings(files, path, ("type", "online", "status", "capacity", "power_now")))
        for path in topology["dptf"]:
            sample_group(index, start, "dptf", path, readings(files, path, ("tcc_offset_degree_celsius",)))
            sample_group(index, start, "dptf", path / "power_limits",
                         readings(files, path / "power_limits", ("power_floor_status", "power_floor_enable")))
        sample_group(index, start, "platform_profile", "/sys/firmware/acpi",
                     readings(files, Path("/sys/firmware/acpi"), ("platform_profile",)))
        if api:
            for identity, handle in targets:
                sample_group(index, start, "nvidia_gpu", identity, gpu_metrics(api, handle))
        emit("sample_complete", {"index": index, "elapsed_seconds": time.monotonic() - start})


def worker(phase: str) -> int:
    if phase in {"cpu", "graphics"}:
        {"cpu": cpu_inventory, "graphics": graphics_inventory}[phase]()
        return 0
    api = None
    targets = []
    try:
        try:
            api = NVML()
            for name in ("nvmlSystemGetDriverVersion", "nvmlSystemGetNVMLVersion"):
                emit(name, query(lambda n=name: api.text(n)))
            targets = gpu_handles(api)
        except (OSError, NvError) as exc:
            emit("nvml_unavailable", exc.result if isinstance(exc, NvError) else {"status": "library_unavailable", "error": str(exc)})
        if phase == "nvml" and api:
            gpu_inventory(api, targets)
        elif phase == "samples":
            samples(api, targets, SAMPLE_COUNT, SAMPLE_INTERVAL_SECONDS)
        return 0
    finally:
        if api:
            emit("nvml_shutdown", query(lambda: api.call("nvmlShutdown", [], [])))


class Capture:
    def __init__(self) -> None:
        self.remaining = MAX_TOTAL_CAPTURE
        self.deadline = time.monotonic() + TOTAL_SECONDS

    def run(self, argv: list[str], seconds: float, max_bytes: int = MAX_CAPTURE) -> dict:
        result: dict = {"argv": argv, "started_utc": utc()}
        allowance = min(max_bytes, self.remaining)
        deadline = min(self.deadline, time.monotonic() + seconds)
        if allowance <= 0 or time.monotonic() >= deadline:
            return {**result, "status": "not_attempted", "reason": "aggregate output/time budget exhausted"}
        outputs = {"stdout": bytearray(), "stderr": bytearray()}
        process = None
        started = time.monotonic()
        status = "ok"
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env=ENV, cwd="/", start_new_session=True, close_fds=True)
            with selectors.DefaultSelector() as selector:
                for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, name)
                used = 0
                while True:
                    # WNOWAIT leaves an exited child unreaped, pinning its PID
                    # and process-group identity until cleanup. Popen.poll()
                    # would reap it before a later group signal.
                    if not selector.get_map() and os.waitid(
                        os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
                    ) is not None:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        status = "timeout"
                        break
                    for key, _ in selector.select(min(0.2, remaining)):
                        chunk = os.read(key.fileobj.fileno(), min(65536, allowance - used + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            take = min(len(chunk), allowance - used)
                            outputs[key.data].extend(chunk[:take])
                            used += take
                            if take < len(chunk):
                                status = "output_limit"
                                break
                    if status != "ok":
                        break
        except KeyboardInterrupt:
            status = "interrupted"
        except OSError as exc:
            status = "launch_or_io_error"
            result["error"] = str(exc)
        finally:
            if process is not None:
                # Signal only this Popen-owned session; do not discover/signal PIDs.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    result["signal_error"] = str(exc)
                    status = "outcome_unknown"
                try:
                    process.wait(timeout=2)
                    result["exit_code"] = process.returncode
                    result["cleanup"] = "child_reaped"
                except subprocess.TimeoutExpired:
                    result["cleanup"] = "termination_unconfirmed"
                    status = "outcome_unknown"
                for pipe in (process.stdout, process.stderr):
                    if pipe:
                        pipe.close()
        used = sum(len(data) for data in outputs.values())
        self.remaining -= used
        result.update(status=status, duration_seconds=round(time.monotonic() - started, 3), captured_bytes=used,
                      **{key: bytes(value).decode("utf-8", errors="replace") for key, value in outputs.items()})
        if status == "ok" and result.get("exit_code") != 0:
            result["status"] = "command_failed"
        return result


def parse_events(result: dict) -> dict:
    events, errors = [], []
    for number, line in enumerate(result.pop("stdout", "").splitlines(), 1):
        try:
            value = json.loads(line)
            if not isinstance(value, dict) or set(value) != {"key", "value", "utc"}:
                raise ValueError("unexpected worker record")
            events.append(value)
        except ValueError as exc:
            errors.append({"line": number, "error": str(exc), "partial_line": line[:500]})
    if result.get("status") == "ok" and (errors or not events):
        result["status"] = "invalid_worker_output"
    return {**result, "events": events, "record_errors": errors}


def query_statuses(value: object, counts: dict[str, int]) -> None:
    if isinstance(value, dict):
        status = value.get("status")
        if isinstance(status, str):
            counts[status] = counts.get(status, 0) + 1
        for item in value.values():
            query_statuses(item, counts)
    elif isinstance(value, list):
        for item in value:
            query_statuses(item, counts)


def events(report: dict, phase: str, key: str) -> list[dict]:
    return [event["value"] for event in report["sections"].get(phase, {}).get("events", [])
            if event.get("key") == key]


def summarize(report: dict) -> dict:
    complete = events(report, "samples", "sample_complete")
    starts = events(report, "samples", "sample_start")
    groups = events(report, "samples", "sample_group")
    coverage: dict[str, dict] = {}
    ranges: dict[str, dict] = {}
    frequencies: set[int] = set()
    policy_frequencies: dict[str, set[int]] = {}
    for group in groups:
        tag = group["tag"]
        if tag == "cpufreq":
            policy_frequencies.setdefault(group["source"], set())
        bucket = coverage.setdefault(tag, {"sample_indices": set(), "ok_readings": 0})
        bucket["sample_indices"].add(group["index"])
        for metric, reading in leaf_readings(group["readings"]):
            if reading.get("status") == "ok":
                bucket["ok_readings"] += 1
                value = number(reading)
                if value is not None:
                    key = group["source"] + "/" + metric
                    row = ranges.setdefault(key, {"unit": reading.get("unit", "raw"), "minimum": value,
                        "maximum": value, "first": value, "last": value, "readings": 0})
                    row["minimum"], row["maximum"] = min(row["minimum"], value), max(row["maximum"], value)
                    row["last"], row["readings"] = value, row["readings"] + 1
                    if tag == "cpufreq" and metric in {"scaling_cur_freq", "cpuinfo_cur_freq", "cpuinfo_avg_freq"}:
                        frequencies.add(group["index"])
                        policy_frequencies[group["source"]].add(group["index"])
    for bucket in coverage.values():
        bucket["samples"] = len(bucket.pop("sample_indices"))
    span = starts[-1]["elapsed_seconds"] - starts[0]["elapsed_seconds"] if len(starts) > 1 else 0.0
    matched = any(value.get("matched") for value in events(report, "cpu", "cpu_target"))
    indices = {value["index"] for value in complete}
    issues = []
    if not matched:
        issues.append(f"The expected GenuineIntel {CPU_MODEL} CPU was not confirmed.")
    if indices != set(range(SAMPLE_COUNT)) or span < SAMPLE_SPAN - 0.01:
        issues.append(f"Sampling incomplete: {len(indices)}/{SAMPLE_COUNT} completed samples; observed start span {span:.3f} s.")
    if len(frequencies) != SAMPLE_COUNT:
        issues.append(f"Usable CPU frequency samples: {len(frequencies)}/{SAMPLE_COUNT}.")
    for policy, available in policy_frequencies.items():
        if len(available) != SAMPLE_COUNT:
            issues.append(f"Usable frequency samples for {policy}: {len(available)}/{SAMPLE_COUNT}.")
    return {"target_cpu_matched": matched, "completed_samples": len(indices),
            "observed_sampling_span_seconds": span, "samples_with_cpu_frequency": len(frequencies),
            "samples_with_cpu_frequency_by_policy": {key: len(value) for key, value in policy_frequencies.items()},
            "coverage": coverage, "numeric_ranges": ranges, "issues": issues}


def timed_samples(report: dict) -> list[dict]:
    return events(report, "samples", "sample_complete")


def timed_offset_rows(report: dict) -> list[dict]:
    return [event["value"] for event in report["sections"].get("samples", {}).get("events", [])
            if event.get("key") == "offset_query_sample"]


def summarize_offsets(report: dict) -> dict:
    records = timed_samples(report)
    rows = timed_offset_rows(report)
    targets = {event["value"]["uuid"]
               for phase in ("nvml", "samples")
               for event in report["sections"].get(phase, {}).get("events", [])
               if event.get("key") == "gpu_identity" and event["value"].get("target_p520")}
    targets.update(row["gpu_uuid"] for row in rows)
    summary: dict = {"requested_samples": SAMPLE_COUNT, "received_samples": len(records),
                     "streamed_offset_query_results": len(rows), "gpus": {}}
    times = [row["sample_elapsed_seconds"] for row in rows]
    span = max(times) - min(times) if times else 0.0
    summary["observed_sampling_span_seconds"] = span
    total_numeric = 0
    total_ranges = 0
    zero_only_ranges = 0
    for identity in sorted(targets):
        gpu: dict = {"offset_snapshots": 0, "snapshots_with_all_query_results": 0,
                     "complete_domain_samples": {"graphics": 0, "memory": 0},
                     "numeric_query_results": 0, "query_status_counts": {}, "zero_only_ranges": 0,
                     "adjustable_ranges": 0, "fixed_nonzero_ranges": 0}
        snapshots: dict[int, dict] = {}
        for row in rows:
            if row["gpu_uuid"] == identity:
                snapshots.setdefault(row["sample_index"], {})[row["query"]] = row["result"]
        for queries in snapshots.values():
            gpu["offset_snapshots"] += 1
            gpu["snapshots_with_all_query_results"] += len(queries) == 36
            for domain in ("graphics", "memory"):
                full_pstate = any(result.get("status") == "ok" and key.startswith(f"offsets/{domain}/")
                                  for key, result in queries.items())
                full_legacy = all(queries.get(f"legacy_offsets/{domain}/{leaf}", {}).get("status") == "ok"
                                  for leaf in ("current", "minimum_maximum"))
                gpu["complete_domain_samples"][domain] += full_pstate or full_legacy
            for key, result in queries.items():
                query_statuses(result, gpu["query_status_counts"])
                fields = offset_fields(key, result)
                gpu["numeric_query_results"] += bool(fields)
                if "advertised_range_state" in fields:
                    state = fields["advertised_range_state"]
                    gpu[{"zero_only": "zero_only_ranges", "adjustable": "adjustable_ranges",
                         "fixed": "fixed_nonzero_ranges"}[state]] += 1
                    total_ranges += 1
                    zero_only_ranges += state == "zero_only"
        total_numeric += gpu["numeric_query_results"]
        summary["gpus"][identity] = gpu
    complete = (bool(targets) and span >= SAMPLE_SPAN_SECONDS - 0.01
                and all(gpu["snapshots_with_all_query_results"] == SAMPLE_COUNT
                        and all(count == SAMPLE_COUNT for count in gpu["complete_domain_samples"].values())
                        for gpu in summary["gpus"].values()))
    summary["status"] = "captured" if complete else "partial" if total_numeric else "unavailable" if targets else "target_missing"
    summary["numeric_query_results"] = total_numeric
    summary["range_interpretation"] = (
        "driver_reports_zero_only_ranges" if total_ranges and total_ranges == zero_only_ranges else
        "nonzero_or_adjustable_ranges_reported" if total_ranges else "no_numeric_offset_bounds")
    summary["range_note"] = (
        "0..0 advertises only a zero offset through the queried interface; it does not establish writable overclocking support. "
        "Unwritten outputs are rejected, and getter success does not prove setter support or write permission.")
    return summary


def write_offset_csv(handle, report: dict) -> None:
    writer = csv.writer(handle)
    writer.writerow(("sample_index", "utc", "elapsed_seconds", "gpu_uuid", "query", "status", "function",
                     "error_code", "error_name", "current_offset_mhz", "minimum_offset_mhz", "maximum_offset_mhz",
                     "advertised_range_state", "unwritten_fields"))
    for row in report["nvidia_offsets"]["timed_queries"]:
        key, result = row["query"], row["result"]
        fields = offset_fields(key, result)
        writer.writerow((row["sample_index"], row["captured_utc"], row["elapsed_seconds"], row["gpu_uuid"],
                         key, result.get("status", "missing"), result.get("function", ""),
                         result.get("code", ""), result.get("name", ""), fields.get("current_mhz", ""),
                         fields.get("minimum_mhz", ""), fields.get("maximum_mhz", ""),
                         fields.get("advertised_range_state", ""), ";".join(result.get("unwritten_fields", []))))


class ReportFiles:
    """Serialize one writer and replace complete fixed reports, with rollback."""

    def __init__(self, directory: Path, prefix: str, suffixes: tuple[str, ...]) -> None:
        self.directory, self.prefix, self.suffixes = directory, prefix, suffixes
        self.root = self.lock = self.stage = -1
        self.stage_name = ""
        self.handles: dict = {}
        self.owned: set[str] = set()
        self.retain = False
        self.checkpoint_name = "collected.raw.json"
        self.checkpoint_complete = False

    @staticmethod
    def identity(info) -> tuple:
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode, info.st_uid

    def existing(self, name: str):
        try:
            info = os.stat(name, dir_fd=self.root, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError(f"Refusing to replace non-regular, foreign-owned or hard-linked report: {name}")
        return info

    def __enter__(self):
        try:
            self.root = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
            self.existing("." + self.prefix + ".lock")
            self.lock = os.open("." + self.prefix + ".lock",
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600, dir_fd=self.root)
            info = os.fstat(self.lock)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                raise ValueError("Unsafe collector lock file")
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another collection is running for this script; wait for it to finish") from None
            for suffix in self.suffixes:
                self.existing(self.prefix + "." + suffix)
            for attempt in range(100):
                name = f".{self.prefix}.staging-{os.getpid()}-{attempt}"
                try:
                    os.mkdir(name, 0o700, dir_fd=self.root)
                    self.stage_name = name
                    break
                except FileExistsError:
                    continue
            else:
                raise ValueError("No unused private staging name available")
            self.stage = os.open(self.stage_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=self.root)
            for suffix in self.suffixes:
                fd = os.open(suffix, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                             0o600, dir_fd=self.stage)
                self.owned.add(suffix)
                self.handles[suffix] = os.fdopen(fd, "w", encoding="utf-8", newline="")
            return self
        except BaseException:
            self.close()
            raise

    def checkpoint(self, report: dict) -> None:
        """Save raw records before any summaries or formatters can fail."""
        fd = os.open(self.checkpoint_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600, dir_fd=self.stage)
        self.owned.add(self.checkpoint_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "format": "collector-raw-recovery",
                       "report": report}, handle, indent=2, ensure_ascii=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(self.stage)
        os.fsync(self.root)
        self.checkpoint_complete = True

    def publish(self) -> None:
        lock_entry = os.stat("." + self.prefix + ".lock", dir_fd=self.root, follow_symlinks=False)
        lock_fd = os.fstat(self.lock)
        if (lock_entry.st_dev, lock_entry.st_ino) != (lock_fd.st_dev, lock_fd.st_ino):
            raise ValueError("Collector lock identity changed during collection")
        for handle in self.handles.values():
            handle.flush()
            os.fsync(handle.fileno())
        previous, replaced, published = {}, [], {}
        try:
            # Keep old inodes in the private workspace until the entire set is published.
            for suffix in self.suffixes:
                name = self.prefix + "." + suffix
                info = self.existing(name)
                previous[suffix] = None if info is None else self.identity(info)
                if info is not None:
                    backup = "previous." + suffix
                    os.link(name, backup, src_dir_fd=self.root, dst_dir_fd=self.stage, follow_symlinks=False)
                    self.owned.add(backup)
                    copied = os.stat(backup, dir_fd=self.stage, follow_symlinks=False)
                    if self.identity(copied) != previous[suffix]:
                        raise ValueError(f"Report changed while backing it up: {name}")
            os.fsync(self.stage)
            os.fsync(self.root)
            # JSON is published last and includes hashes for its companion files.
            for suffix in (*[s for s in self.suffixes if s != "json"], "json"):
                name = self.prefix + "." + suffix
                try:
                    current = os.stat(name, dir_fd=self.root, follow_symlinks=False)
                except FileNotFoundError:
                    current = None
                if (None if current is None else self.identity(current)) != previous[suffix]:
                    raise ValueError(f"Report changed during collection: {name}")
                published[suffix] = self.identity(os.stat(suffix, dir_fd=self.stage, follow_symlinks=False))
                replaced.append(suffix)
                os.replace(suffix, name, src_dir_fd=self.stage, dst_dir_fd=self.root)
                self.owned.discard(suffix)
            os.fsync(self.root)
        except BaseException as cause:
            try:
                for suffix in reversed(replaced):
                    name = self.prefix + "." + suffix
                    try:
                        current = self.identity(os.stat(name, dir_fd=self.root, follow_symlinks=False))
                    except FileNotFoundError:
                        current = None
                    if current == previous[suffix]:
                        continue  # The attempted rename did not happen.
                    if current != published[suffix]:
                        raise ValueError(f"Published report identity changed: {name}")
                    if previous[suffix] is None:
                        os.unlink(name, dir_fd=self.root)
                    else:
                        backup = "previous." + suffix
                        os.replace(backup, name, src_dir_fd=self.stage, dst_dir_fd=self.root)
                        self.owned.discard(backup)
                os.fsync(self.root)
                os.fsync(self.stage)
                # Restoration is confirmed. Drop unused backup links so a retained
                # raw checkpoint does not leave current reports multiply linked.
                for name in sorted(self.owned):
                    if name.startswith("previous."):
                        os.unlink(name, dir_fd=self.stage)
                        self.owned.discard(name)
                os.fsync(self.stage)
                os.fsync(self.root)
            except BaseException as recovery:
                self.retain = True
                raise RuntimeError(f"Report publication outcome unknown; recovery retained at "
                                   f"{self.directory / self.stage_name}: {recovery}") from cause
            raise RuntimeError(f"Report publication failed; previous reports restored: {cause}") from cause

    def companion_hashes(self) -> dict:
        result = {}
        for suffix, handle in self.handles.items():
            if suffix == "json":
                continue
            handle.flush()
            fd = os.open(suffix, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=self.stage)
            digest = hashlib.sha256()
            try:
                while chunk := os.read(fd, 65536):
                    digest.update(chunk)
            finally:
                os.close(fd)
            result[self.prefix + "." + suffix] = digest.hexdigest()
        return result

    def close(self) -> None:
        failure = None
        try:
            for handle in self.handles.values():
                try:
                    handle.close()
                except OSError as exc:
                    failure, self.retain = exc, True
            if self.stage >= 0 and not self.retain:
                try:
                    for name in sorted(self.owned):
                        try:
                            os.unlink(name, dir_fd=self.stage)
                        except FileNotFoundError:
                            pass  # A rename may have completed before an interruption.
                    os.fsync(self.stage)
                except OSError as exc:
                    failure, self.retain = exc, True
            if self.stage >= 0:
                os.close(self.stage)
                self.stage = -1
            if self.root >= 0 and self.stage_name and not self.retain:
                try:
                    os.rmdir(self.stage_name, dir_fd=self.root)
                    os.fsync(self.root)
                except OSError as exc:
                    failure, self.retain = exc, True
        finally:
            for name in ("stage", "lock", "root"):
                fd = getattr(self, name)
                if fd >= 0:
                    os.close(fd)
                    setattr(self, name, -1)
        if failure is not None:
            raise RuntimeError(f"Output cleanup incomplete; inspect {self.directory / self.stage_name}: {failure}")

    def __exit__(self, kind, value, traceback) -> None:
        if kind is not None and self.checkpoint_name in self.owned:
            self.retain = True
            state = "Complete" if self.checkpoint_complete else "Partial"
            print(f"{state} collected-data checkpoint retained at "
                  f"{self.directory / self.stage_name / self.checkpoint_name}", file=sys.stderr)
        try:
            self.close()
        except RuntimeError as cleanup:
            if kind is None:
                raise
            print(str(cleanup), file=sys.stderr)


INVENTORY_SECTIONS = (
    "cpu_identity", "pci_graphics", "cpu_frequency", "cpu_idle", "uncore", "rapl", "dptf",
    "thermals", "power_supply", "platform", "intel_graphics", "nvidia_gpu", "system", "other",
)


def inventory_category(source: str) -> str:
    if source.startswith("GPU-") or source.startswith("nvml") or source in {"gpu_identity", "gpu_target"}:
        return "nvidia_gpu"
    if source in {"cpuinfo", "cpu_target", "cpu_global"} or "/topology/" in source or re.fullmatch(r"/sys/devices/system/cpu/cpu[0-9]+", source):
        return "cpu_identity"
    if source.endswith("/graphics"):
        return "pci_graphics"
    if "powercap" in source:
        return "rapl"
    if re.search(r"/(?:INT3400|INTC1040|INTC1041|INTC10A0):", source):
        return "dptf"
    if "power_limits" in source or "workload_request" in source or source.startswith("/sys/bus/pci/devices/") and "/graphics" not in source:
        return "dptf"
    if "intel_uncore" in source:
        return "uncore"
    if "cpuidle" in source or "/intel_idle/" in source or "/processor/" in source:
        return "cpu_idle"
    if "thermal" in source or "/hwmon" in source:
        return "thermals"
    if "power_supply" in source:
        return "power_supply"
    if source.startswith("/sys/class/drm") or "i915" in source or source.startswith("intel_graphics"):
        return "intel_graphics"
    if "cpufreq" in source or "intel_pstate" in source or source == "governor_tunables":
        return "cpu_frequency"
    if "platform_profile" in source or source == "firmware_identity" or "/dmi/" in source or "platform-profile" in source:
        return "platform"
    if source.startswith("/proc/") or source.endswith("os-release") or "vulnerabilities" in source or source == "kernel_tuning_context":
        return "system"
    return "other"


def leaf_readings(value: object, prefix: str = ""):
    """Flatten only for tables/CSV. Structured originals stay in JSON."""
    if isinstance(value, dict):
        if isinstance(value.get("status"), str):
            if value["status"] == "ok" and isinstance(value.get("value"), dict):
                for name, item in value["value"].items():
                    yield from leaf_readings({"status": "ok", "value": item, "unit": value.get("unit", "raw")},
                                             prefix + "/" + name if prefix else name)
            else:
                yield prefix or "value", value
        else:
            for name, item in value.items():
                yield from leaf_readings(item, prefix + "/" + str(name) if prefix else str(name))
    else:
        yield prefix or "value", {"status": "ok", "value": value, "unit": "raw"}


def analyze_measurements(report: dict) -> dict:
    metrics, coverage, schedules = {}, {}, {}
    for event in report["sections"].get("samples", {}).get("events", []):
        value = event["value"]
        key = event["key"]
        if key in {"sample_start", "sample_complete"}:
            schedule = schedules.setdefault(value["index"], {"index": value["index"], "complete": False})
            if key == "sample_start":
                schedule.update(started_utc=event["utc"], elapsed_seconds=value["elapsed_seconds"])
            else:
                schedule.update(complete=True, completed_utc=event["utc"],
                                completed_elapsed_seconds=value["elapsed_seconds"])
        elif key == "sample_group":
            group, source = value["tag"], value["source"]
            bucket = coverage.setdefault(group, {}).setdefault(source, {"indices": set(), "ok_readings": 0})
            bucket["indices"].add(value["index"])
            target = metrics.setdefault(group, {}).setdefault(source, {})
            for name, reading in leaf_readings(value["readings"]):
                row = target.setdefault(name, {"unit": reading.get("unit", "raw"), "ok_readings": 0,
                    "status_counts": {}, "first": None, "last": None, "minimum": None, "maximum": None,
                    "mean": None, "first_numeric": None, "last_numeric": None, "last_minus_first": None, "numeric_readings": 0, "observed_values": {}, "changed": False})
                status = reading.get("status", "missing")
                row["status_counts"][status] = row["status_counts"].get(status, 0) + 1
                if status != "ok":
                    continue
                row["ok_readings"] += 1
                bucket["ok_readings"] += 1
                item = reading.get("value")
                if row["ok_readings"] == 1:
                    row["first"] = item
                else:
                    row["changed"] |= item != row["last"]
                row["last"] = item
                numeric = number(reading)
                if numeric is not None:
                    row["numeric_readings"] += 1
                    count = row["numeric_readings"]
                    if count == 1:
                        row["first_numeric"] = numeric
                    row["last_numeric"] = numeric
                    row["last_minus_first"] = numeric - row["first_numeric"]
                    row["minimum"] = numeric if count == 1 else min(row["minimum"], numeric)
                    row["maximum"] = numeric if count == 1 else max(row["maximum"], numeric)
                    row["mean"] = numeric if count == 1 else row["mean"] + (numeric - row["mean"]) / count
                else:
                    label = json.dumps(item, ensure_ascii=True, sort_keys=True)
                    # At most 61 distinct values for a normally sampled metric.
                    row["observed_values"][label] = row["observed_values"].get(label, 0) + 1
    for sources in coverage.values():
        for bucket in sources.values():
            bucket["samples"] = len(bucket.pop("indices"))
    return {"coverage_by_source": coverage, "metrics": metrics,
            "schedule": [schedules[index] for index in sorted(schedules)]}


def observed_setting_changes(inventory: dict) -> list[dict]:
    selected = re.compile(r"(?:scaling_(?:min_freq|max_freq|governor|driver)|energy_performance_preference|(?:power/)?energy_perf_bias|"
        r"min_perf_pct|max_perf_pct|no_turbo|hwp_dynamic_boost|constraint_[0-9]+_(?:power_limit_uw|time_window_us)|"
        r"(?:gt|rps)_(?:min|max|boost)_freq_mhz|(?:min|max)_freq_khz|disable|platform_profile|profile|"
        r"tcc_offset_degree_celsius|control|max_cstate|states_off|current_governor(?:_ro)?|current_driver|"
        r"(?:up_|down_)?rate_limit_us|sampling_rate(?:_min)?|up_threshold|down_threshold|sampling_down_factor)")
    changes = []
    for category, snapshots in inventory.items():
        before = {(record["source"], name): reading for record in snapshots["before"]
                  for name, reading in leaf_readings(record["readings"])
                  if selected.fullmatch(name) and reading.get("status") == "ok"}
        for record in snapshots["after"]:
            for name, reading in leaf_readings(record["readings"]):
                old = before.get((record["source"], name))
                if old is not None and reading.get("status") == "ok" and old.get("value") != reading.get("value"):
                    changes.append({"category": category, "source": record["source"], "metric": name,
                        "before": old.get("value"), "after": reading.get("value"), "unit": reading.get("unit", "raw")})
    return changes


def offset_query_summary(rows: list[dict]) -> dict:
    result = {}
    for row in rows:
        query = result.setdefault(row["gpu_uuid"], {}).setdefault(row["query"], {
            "samples": set(), "status_counts": {}, "current_mhz": None, "minimum_mhz": None, "maximum_mhz": None})
        query["samples"].add(row["sample_index"])
        reading = row["result"]
        status = reading.get("status", "missing")
        query["status_counts"][status] = query["status_counts"].get(status, 0) + 1
        fields = offset_fields(row["query"], reading)
        for name in ("current_mhz", "minimum_mhz", "maximum_mhz"):
            if name not in fields:
                continue
            value = fields[name]
            aggregate = query[name]
            if aggregate is None:
                query[name] = {"first": value, "last": value, "minimum": value, "maximum": value, "readings": 1}
            else:
                aggregate.update(last=value, minimum=min(aggregate["minimum"], value),
                                 maximum=max(aggregate["maximum"], value), readings=aggregate["readings"] + 1)
    for queries in result.values():
        for query in queries.values():
            query["samples"] = len(query["samples"])
    return result


def parse_json_output(text: str):
    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number

    def reject_constant(value: str):
        raise ValueError("Non-standard JSON numeric constant: " + value)

    return json.loads(text, parse_float=finite_float, parse_constant=reject_constant)


def reading_kind(reading: dict) -> str:
    status = reading.get("status")
    source_status = reading.get("source_status")
    if not isinstance(status, str):
        return "metadata"
    if not isinstance(source_status, str):
        source_status = None
    if status in {"ok", "baseline"}:
        return "available"
    if status == "permission_denied" or source_status == "permission_denied" or (
            status == "nvml_error" and reading.get("code") == 4):
        return "permission_denied"
    if status in {"not_exposed", "not_applicable", "not_supported", "no_data", "temporarily_unavailable", "symbol_missing"}:
        return "unavailable"
    if source_status in {"not_exposed", "not_applicable", "not_supported", "no_data", "temporarily_unavailable"}:
        return "unavailable"
    if status == "nvml_error" and reading.get("code") == 3:
        return "unavailable"
    return "error"


def nvidia_collection_assessment(inventory: dict) -> list[dict]:
    devices = {}
    for record in inventory.get("nvidia_gpu", {}).get("before", []):
        source = record["source"]
        if not source.startswith("GPU-") or "/" not in source:
            continue
        identity, query_name = source.split("/", 1)
        devices.setdefault(identity, {})[query_name] = record["readings"]
    notes = []
    for identity, values in devices.items():
        current = values.get("nvmlDeviceGetPowerManagementLimit", {})
        limits = {name: values[name] for name in ("power_limit_min_max",
            "nvmlDeviceGetPowerManagementDefaultLimit", "nvmlDeviceGetEnforcedPowerLimit")
                  if name in values and values[name].get("status") == "ok"}
        if limits and current.get("status") != "ok":
            notes.append({"gpu": identity, "topic": "power_control_not_verified",
                "message": "The driver returned numeric limit metadata while the current-power-limit getter failed. "
                           "These numbers do not establish a usable or safe power-control range.",
                "current_limit_getter": current, "driver_limit_metadata": limits})
        telemetry = values.get("telemetry", {})
        for field, topic, message in (
            ("power_usage", "gpu_power_draw_unavailable",
             "NVML did not provide GPU power draw. CPU/package RAPL readings are separate and are not substituted for it."),
            ("fan_speed", "nvml_fan_speed_unavailable",
             "NVML did not provide dedicated GPU fan speed. Shared platform fan readings, where exposed, remain separate hwmon sources."),
        ):
            reading = telemetry.get(field, {})
            if reading.get("status") != "ok":
                notes.append({"gpu": identity, "topic": topic, "message": message, "getter_result": reading})
    return notes


def organize_report(report: dict) -> dict:
    """Stable schema: no interleaving of inventories, diagnostics and time series."""
    inventory = {name: {"before": [], "after": []} for name in INVENTORY_SECTIONS}
    samples, offset_rows, notes, commands, execution, failures = [], [], [], [], [], {}
    unavailable_interfaces, permission_failures = {}, {}
    hardware = {"cpu": [], "intel_graphics": [], "nvidia_gpu": []}

    def record_failures(value: object, phase: str, source: str, stamp: str) -> None:
        for metric, reading in leaf_readings(value):
            status = reading.get("status", "missing")
            if status in {"ok", "baseline"}:
                continue
            details = {key: val for key, val in reading.items() if key not in {"value", "unit"}}
            kind = reading_kind(reading)
            destination = unavailable_interfaces if kind == "unavailable" else permission_failures if kind == "permission_denied" else failures
            identity = (source, metric, status, json.dumps(details, sort_keys=True))
            row = destination.setdefault(identity, {"phase": phase, "phases": [], "source": source, "metric": metric,
                "status": status, "occurrences": 0, "first_utc": stamp, "last_utc": stamp, "details": details})
            if phase not in row["phases"]:
                row["phases"].append(phase)
            row["occurrences"] += 1
            row["last_utc"] = stamp

    for phase, section in report["sections"].items():
        execution.append({"section": phase, **{key: value for key, value in section.items()
                                              if key not in {"events", "record_errors", "stdout"}}})
        if phase.startswith("command_"):
            command = {"section": phase, **section}
            if section.get("status") == "ok" and section.get("stdout", "").lstrip().startswith(("{", "[")):
                try:
                    command["parsed_json"] = parse_json_output(section["stdout"])
                    command.pop("stdout", None)  # Original values retained as structured JSON.
                except (ValueError, RecursionError) as exc:
                    command["json_parse_error"] = str(exc)
            commands.append(command)
            if "--json" in section.get("argv", []) and Path(section["argv"][0]).name == "lscpu":
                parsed = command.get("parsed_json")
                properties = parsed.get("lscpu", []) if isinstance(parsed, dict) else []
                hardware["cpu_properties"] = [item for item in properties if isinstance(item, dict)] if isinstance(properties, list) else []
        for error in section.get("record_errors", []):
            notes.append({"phase": phase, "kind": "worker_record_error", "value": error})
        for event in section.get("events", []):
            key, value, stamp = event["key"], event["value"], event["utc"]
            if key == "sample_group":
                samples.append({"index": value["index"], "captured_utc": stamp,
                    "elapsed_seconds": value["elapsed_seconds"], "group": value["tag"],
                    "source": value["source"], "readings": value["readings"]})
                record_failures(value["readings"], phase, value["source"], stamp)
            elif key == "offset_query_sample":
                offset_rows.append(value)
                record_failures(value["result"], phase, value["gpu_uuid"] + "/" + value["query"], stamp)
            elif key in {"sample_start", "sample_complete"}:
                continue  # Retained in sampling.schedule.
            elif phase == "samples" or key.startswith(("directory_", "optional_interface_", "attribute_discovery_", "cpufreq_discovery_", "rapl_limit", "rapl_path_error", "file_")):
                if not isinstance(value, dict) or reading_kind(value) != "unavailable":
                    notes.append({"phase": phase, "kind": key, "captured_utc": stamp, "value": value})
                source = value.get("path", key) if isinstance(value, dict) else key
                record_failures(value, phase, source, stamp)
            else:
                category = inventory_category(key)
                when = "after" if phase.endswith("_after") else "before"
                record = {"source": key, "captured_utc": stamp, "readings": value}
                inventory[category][when].append(record)
                record_failures(value, phase, key, stamp)
            if key == "cpu_target":
                hardware["cpu"].append({"phase": phase, **value})
            elif key == "intel_graphics":
                hardware["intel_graphics"].append({"phase": phase, **value})
            elif key == "gpu_identity":
                hardware["nvidia_gpu"].append({"phase": phase, **value})

    summary = report["summary"]
    collection = {key: value for key, value in report.items()
                  if key not in {"schema_version", "sections", "summary", "offset_capture", "interpretation", "query_status_counts"}}
    collection["output_files"] = [OUTPUT_PREFIX + "." + suffix for suffix in OUTPUT_SUFFIXES]
    result = {"schema_version": 2, "collection": collection,
        "overview": {key: value for key, value in summary.items() if key != "numeric_ranges"},
        "hardware": hardware,
        "inventory": {name: value for name, value in inventory.items() if value["before"] or value["after"]},
        "sampling": {**analyze_measurements(report), "readings": samples},
        "setting_changes": observed_setting_changes(inventory),
        "nvidia_collection_assessment": nvidia_collection_assessment(inventory),
        "diagnostics": {"query_status_counts": report["query_status_counts"], "execution": execution,
            "unavailable_interfaces": list(unavailable_interfaces.values()),
            "permission_failures": list(permission_failures.values()),
            "reading_failures": list(failures.values()), "discovery_and_worker_notes": notes},
        "commands": commands, "interpretation": report["interpretation"]}
    if "offset_capture" in report:
        result["nvidia_offsets"] = {"summary": report["offset_capture"], "timed_queries": offset_rows,
                                    "query_summary": offset_query_summary(offset_rows)}
    return result


def display(value: object, limit: int = 140) -> str:
    if isinstance(value, float):
        text = f"{value:.6g}"
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True)
    text = text.encode("unicode_escape").decode("ascii")
    return text if len(text) <= limit else text[:limit - 25] + "... [full value in JSON]"


def render_text(document: dict) -> str:
    collection, overview = document["collection"], document["overview"]
    lines = [REPORT_TITLE, "=" * len(REPORT_TITLE), "",
        "01  COLLECTION SUMMARY", "-" * 88,
        f"Status                  : {collection['status']}",
        f"Target CPU confirmed    : {overview['target_cpu_matched']}",
        f"Completed sample ticks  : {overview['completed_samples']} / {SAMPLE_COUNT}",
        f"Observed sample span    : {overview['observed_sampling_span_seconds']:.3f} seconds",
        f"Started UTC             : {collection['started_utc']}",
        f"Finished UTC            : {collection['finished_utc']}",
        f"Kernel                  : {collection['kernel_release']}",
        f"Collector / schema      : {VERSION} / {document['schema_version']}",
        f"Collector SHA-256       : {collection['script_sha256']}",
        "Outputs                 : " + ", ".join(collection["output_files"]), "",
        "Collection issues:"]
    lines.extend("  - " + issue for issue in overview["issues"])
    if not overview["issues"]:
        lines.append("  None detected by the collector.")
    lines += ["", "02  HARDWARE IDENTITY", "-" * 88]
    for category, records in document["hardware"].items():
        for record in records:
            lines.append(f"{category} [{record.get('phase', 'inventory')}]: {display(record, 800)}")
    lines += ["", "03  TUNING CAPABILITIES AND SETTINGS", "-" * 88,
        "Driver-advertised choices/bounds and active readings; no write/stability capability is inferred.",
        "Both BEFORE and AFTER inventories are retained to reveal changes during collection."]
    for category, snapshots in document["inventory"].items():
        lines += ["", category.upper().replace("_", " ")]
        for when, records in snapshots.items():
            for record in records:
                lines.append(f"  [{when.upper()}] {record['source']}")
                for name, reading in leaf_readings(record["readings"]):
                    status = reading.get("status", "missing")
                    value = display(reading.get("value", "")) if status == "ok" else "<unavailable>"
                    unit = reading.get("unit", "raw")
                    lines.append(f"    {name:<46} {value:<24} {unit:<12} [{status}]")
    if document["nvidia_collection_assessment"]:
        lines += ["", "NVIDIA DATA AND CONTROL LIMITATIONS"]
        for note in document["nvidia_collection_assessment"]:
            lines.append(f"  {note['gpu']} / {note['topic']}: {note['message']}")
            if "driver_limit_metadata" in note:
                lines.append("    Raw driver metadata (not a validated tuning range): " + display(note["driver_limit_metadata"], 1200))
    lines += ["", "CHANGES TO TUNING SETTINGS OBSERVED DURING COLLECTION"]
    for row in document["setting_changes"]:
        lines.append(f"  {row['source']} / {row['metric']}: {display(row['before'])} -> {display(row['after'])} {row['unit']}")
    if not document["setting_changes"]:
        lines.append("  No changes observed in the selected readable settings.")
    lines += ["", "04  SAMPLING COVERAGE", "-" * 88,
              "Group / source                                                            Ticks  OK readings"]
    for group, sources in document["sampling"]["coverage_by_source"].items():
        for source, row in sources.items():
            lines.append(f"{group} / {source:<66} {row['samples']:>3}/{SAMPLE_COUNT}  {row['ok_readings']:>8}")
    lines += ["", "05  OBSERVED MEASUREMENTS", "-" * 88,
              "Means below are arithmetic sample means. Counter first/last/change are observations, not tuning gains.",
              "Every timestamped reading and error is retained in JSON and samples.csv."]
    for group, sources in document["sampling"]["metrics"].items():
        lines += ["", group.upper().replace("_", " ")]
        for source, metrics in sources.items():
            lines.append("  " + source)
            for name, row in metrics.items():
                if row["numeric_readings"]:
                    change = row["last_minus_first"]
                    lines.append(f"    {name}: min={display(row['minimum'])}, mean={display(row['mean'])}, "
                                 f"max={display(row['maximum'])} {row['unit']}; first={display(row['first'])}, "
                                 f"last={display(row['last'])}; n={row['numeric_readings']}")
                    if change is not None:
                        lines.append(f"      last-first={display(change)} {row['unit']}")
                elif row["ok_readings"]:
                    lines.append(f"    {name}: first={display(row['first'])}; last={display(row['last'])}; "
                                 f"changed={row['changed']}; observed={display(row['observed_values'], 400)}")
                else:
                    lines.append(f"    {name}: <no usable reading>")
                non_ok = {key: count for key, count in row["status_counts"].items() if key != "ok"}
                if non_ok:
                    lines.append("      statuses: " + display(non_ok))
    if "nvidia_offsets" in document:
        offset = document["nvidia_offsets"]["summary"]
        lines += ["", "06  NVIDIA OFFSET CAPTURE", "-" * 88,
            "Offsets are configured MHz adjustments; supported operating clocks are listed separately.",
            f"Capture status: {offset['status']}; timed query results: {offset['streamed_offset_query_results']}",
            f"Sampling span: {offset['observed_sampling_span_seconds']:.3f} seconds",
            offset["range_note"]]
        for identity, gpu in offset["gpus"].items():
            lines += [identity, "  " + display(gpu, 1600)]
        lines.append("All 36 getter results per GPU/tick, including failures, are in offsets.csv and JSON.")
        for identity, queries in document["nvidia_offsets"]["query_summary"].items():
            lines.append("  " + identity + " / PER-QUERY SUMMARY (MHz offsets)")
            for name, row in queries.items():
                lines.append(f"    {name}: ticks={row['samples']}; statuses={display(row['status_counts'])}")
                for field in ("current_mhz", "minimum_mhz", "maximum_mhz"):
                    values = row[field]
                    lines.append(f"      {field}: " + (f"first={values['first']}, last={values['last']}, "
                        f"min={values['minimum']}, max={values['maximum']}, n={values['readings']}" if values else "<unavailable>"))
    lines += ["", "07  INTERFACE AVAILABILITY AND ERRORS", "-" * 88,
              "Expected absence, driver no-data responses, access denials and actual failures remain distinct."]
    for field, heading in (
        ("unavailable_interfaces", "NOT EXPOSED / NOT APPLICABLE / DRIVER HAS NO DATA"),
        ("permission_failures", "ACCESS DENIED"),
        ("reading_failures", "READ AND COLLECTION FAILURES"),
    ):
        lines.append(heading)
        rows = document["diagnostics"][field]
        if not rows:
            lines.append("  None recorded.")
        for row in rows:
            phases = ", ".join(row["phases"])
            lines += [f"  {row['source']} / {row['metric']}",
                      f"    {row['status']} x {row['occurrences']} [{phases}]; {display(row['details'], 600)}"]
    for note in document["diagnostics"]["discovery_and_worker_notes"]:
        lines.append("  " + display(note, 600))
    lines += ["", "08  TOOL AND WORKER EXECUTION", "-" * 88]
    for row in document["diagnostics"]["execution"]:
        lines.append(display(row, 1000))
    for command in document["commands"]:
        lines.append("  " + " ".join(command.get("argv", [])) + " : " + command["status"])
        if command.get("stderr"):
            lines.append("    stderr: " + display(command["stderr"], 1000))
    lines += ["  Full structured tool results and raw non-JSON command output are in the JSON report.",
              "", "09  INTERPRETATION", "-" * 88]
    lines.extend("  - " + item for item in document["interpretation"])
    return "\n".join(lines) + "\n"


def csv_cell(value: object) -> object:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, sort_keys=True, ensure_ascii=True)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) and not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value):
        return "'" + value
    return value


def write_csv(handle, document: dict) -> None:
    writer = csv.writer(handle)
    writer.writerow(("sample_index", "utc", "elapsed_seconds", "group", "source",
                     "metric", "value", "unit", "status", "error_code", "error_name", "details"))
    for row in document["sampling"]["readings"]:
        for metric, reading in leaf_readings(row["readings"]):
            details = {key: value for key, value in reading.items()
                       if key not in {"value", "unit", "status", "code", "name"}}
            writer.writerow([csv_cell(value) for value in (
                row["index"], row["captured_utc"], row["elapsed_seconds"], row["group"], row["source"],
                metric, reading.get("value", ""), reading.get("unit", "raw"), reading.get("status", "missing"),
                reading.get("code", reading.get("errno", "")), reading.get("name", ""), details)])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choices = ("cpu", "graphics", "nvml", "samples") if IS_NVIDIA else ("cpu", "graphics", "samples")
    parser.add_argument("--_worker", choices=choices, help=argparse.SUPPRESS)
    phase = parser.parse_args()._worker
    if phase:
        if IS_NVIDIA:
            return worker(phase)
        {"cpu": cpu_inventory, "graphics": graphics_inventory, "samples": samples}[phase]()
        return 0
    os.umask(0o077)
    script = Path(__file__).resolve(strict=True)
    with script.open("rb") as source:
        script_bytes = source.read(1024 * 1024 + 1)
    if len(script_bytes) > 1024 * 1024:
        raise ValueError("Collector source exceeds the 1 MiB fingerprint limit")
    report: dict = {"collector_version": VERSION, "started_utc": utc(),
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "kernel_release": os.uname().release, "machine": os.uname().machine,
        "python_version": sys.version, "effective_uid": os.geteuid(),
        "target": {"cpu": TARGET_CPU, "gpu": "NVIDIA Quadro P520 Pascal" if IS_NVIDIA else "Intel integrated graphics"},
        "collection_mode": "full", "samples_requested": SAMPLE_COUNT, "sample_interval_seconds": SAMPLE_INTERVAL,
        "read_only_hardware_queries": True,
        "limits": {"total_seconds": TOTAL_SECONDS, "capture_bytes": MAX_CAPTURE,
            "sampling_capture_bytes": MAX_SAMPLE_CAPTURE, "total_capture_bytes": MAX_TOTAL_CAPTURE},
        "interpretation": [
            "Observed ranges and driver-advertised bounds are evidence, not recommendations or proven performance gains.",
            "scaling_cur_freq is driver-reported; cpuinfo_avg_freq, when exposed, is hardware-feedback frequency over a short kernel window.",
            "Frequency sources remain separate and retain their names/units. No MSRs are read by this collector; CPU busy treats iowait as idle.",
            "CPUIdle counters describe software-requested states, not measured hardware C-state residency.",
            "RC6 percentages come from exposed residency counters. Read activity can affect CPU/GPU idle behavior.",
            "RAPL watts are energy-delta estimates assuming at most one counter wrap; resets/multiple wraps are ambiguous.",
            "RAPL/MSR and RAPL-MMIO zones and package/core/uncore domains may overlap; never sum them blindly.",
            "Missing bounds/offsets are unknown, never zero. TCC temperature offset is separate from voltage/frequency offsets.",
            "CPU/iGPU voltage offsets lack a portable documented sysfs getter used here; no MSR/debugfs/firmware probing.",
            "Getter success does not prove setter support, write permission, stability or successful restoration.",
            "Each group is timestamped separately. The report is not an atomic hardware snapshot or a generated workload.",
            "Before/after inventories expose policy changes during collection; the collector never changes the policy.",
            "Reports describe the workload running during the collection window; idle observations cannot prove loaded behavior.",
            "Optional absence and driver no-data/unsupported results are grouped separately from access denials and read failures.",
            "JSON/CSV retain individual sampled results; discovery records list exposed CPUFreq attributes and known absent fields.",
            "Fixed reports replace the previous run, including explicit partial/interrupted collections. Old reports stay intact until publication.",
        ], "sections": {}}
    if IS_NVIDIA:
        report["interpretation"] += [
            "NVIDIA MHz offsets, supported operating clocks and measured clocks are separate quantities.",
            "All 16 P-states in both graphics/memory domains plus four legacy getters are queried at EVERY sample tick.",
            "NVML getter symbols can exist while the P520/driver rejects them; every response is retained independently.",
            "0..0 offset bounds advertise only zero through that interface; they do not establish writable overclock support.",
            "Reports include GPU UUIDs and PCI identifiers, but omit hostname, serial numbers, full environments and process lists.",
            "PCIe throughput is the driver's short (20 ms) interval reading, not an average over the full sampling interval.",
        ]
    with ReportFiles(script.parent, OUTPUT_PREFIX, OUTPUT_SUFFIXES) as output:
        capture, interrupted = Capture(), False
        try:
            print(f"{REPORT_TITLE}\nFull collection; 61 ticks over 60 seconds. Previous fixed reports will be replaced.", flush=True)
            phases = [("cpu", "cpu", 35), ("graphics", "graphics", 20)]
            if IS_NVIDIA:
                phases.append(("nvml", "nvml", 45))
            phases += [("samples", "samples", SAMPLE_SPAN + 35),
                       ("cpu_after", "cpu", 35), ("graphics_after", "graphics", 20)]
            for name, phase, timeout in phases:
                print(f"Collecting {name} (read-only)...", flush=True)
                result = capture.run([sys.executable, "-IB", str(script), "--_worker", phase], timeout,
                                     MAX_SAMPLE_CAPTURE if phase == "samples" else MAX_CAPTURE)
                report["sections"][name] = parse_events(result)
                if result["status"] in {"interrupted", "outcome_unknown"}:
                    interrupted = result["status"] == "interrupted"
                    break
            if not interrupted and all(item["status"] != "outcome_unknown" for item in report["sections"].values()):
                commands = [["lscpu", "--json"],
                    ["lscpu", "--extended=CPU,CORE,SOCKET,NODE,ONLINE,MAXMHZ,MINMHZ"],
                    ["cpupower", "frequency-info"], ["cpupower", "idle-info"], ["sensors", "-j"]]
                if IS_NVIDIA:
                    commands += [["nvidia-smi", "--version"], ["nvidia-smi", "-L"],
                        ["nvidia-smi", "--query-gpu=index,uuid,name,pci.bus_id,driver_version,vbios_version", "--format=csv"],
                        ["nvidia-smi", "-q", "-d", "CLOCK,POWER,TEMPERATURE,PERFORMANCE"],
                        ["nvidia-smi", "-q", "-d", "SUPPORTED_CLOCKS"]]
                for index, argv in enumerate(commands):
                    binary = shutil.which(argv[0], path=ENV["PATH"])
                    print("Collecting " + " ".join(argv) + "...", flush=True)
                    result = capture.run([binary, *argv[1:]], 10) if binary else {
                        "status": "tool_missing", "argv": argv, "started_utc": utc()}
                    report["sections"][f"command_{index:02d}_{argv[0]}"] = result
                    if result["status"] in {"interrupted", "outcome_unknown"}:
                        interrupted = result["status"] == "interrupted"
                        break
        except KeyboardInterrupt:
            interrupted = True
        except Exception as exc:
            report["collector_error"] = {"type": type(exc).__name__, "error": str(exc)}
        report["finished_utc"], report["interrupted"] = utc(), interrupted
        print("Saving collected data and generating reports...", flush=True)
        output.checkpoint(report)
        try:
            report["failed_sections"] = [name for name, item in report["sections"].items() if item["status"] != "ok"]
            counts: dict[str, int] = {}
            for section in report["sections"].values():
                for event in section.get("events", []):
                    query_statuses(event["value"], counts)
            report["query_status_counts"] = counts
            report["summary"] = summarize(report)
            if IS_NVIDIA:
                report["offset_capture"] = summarize_offsets(report)
                if report["offset_capture"]["status"] != "captured":
                    report["summary"]["issues"].append("Timed P520 graphics/memory offset capture is incomplete or unavailable; see nvidia_offsets.")
            report["status"] = ("interrupted" if interrupted else "partial"
                if report["failed_sections"] or report["summary"]["issues"] or "collector_error" in report else
                "collected_with_limitations" if any(key not in {"ok", "baseline"} for key in counts) else "collected")
            document = organize_report(report)
            output.handles["txt"].write(render_text(document))
            write_csv(output.handles["samples.csv"], document)
            if IS_NVIDIA:
                write_offset_csv(output.handles["offsets.csv"], document)
            document["collection"]["companion_file_sha256"] = output.companion_hashes()
            output.handles["json"].write(json.dumps(document, indent=2, ensure_ascii=True, allow_nan=False) + "\n")
        except Exception as exc:
            raise RuntimeError(f"Report generation failed ({type(exc).__name__}): {exc}. "
                               "Collected data is retained in the reported checkpoint.") from exc
        output.publish()
        for suffix in OUTPUT_SUFFIXES:
            print("Replaced " + str(script.parent / (OUTPUT_PREFIX + "." + suffix)), flush=True)
        print(f"Collection status: {report['status']}; completed ticks: {report['summary']['completed_samples']}/{SAMPLE_COUNT}.")
        if IS_NVIDIA:
            print(f"Offset capture: {report['offset_capture']['status']}; timed query results: "
                  f"{report['offset_capture']['streamed_offset_query_results']}.")
        for issue in report["summary"]["issues"]:
            print("INCOMPLETE: " + issue, file=sys.stderr)
        print("Start with the .txt report; full measurements and errors are in JSON/CSV.")
        return 130 if interrupted else 1 if report["status"] == "partial" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
