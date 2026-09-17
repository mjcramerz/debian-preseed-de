"""Intel's documented sysfs interfaces only. No raw MSRs, voltages, or firmware unlocks."""
from __future__ import annotations

from pathlib import Path
import os
import re
import stat
import system_state
from common import Knob, TuningError, read_text

# Values are ordered performance, high, balanced, silent. keep is deliberately
# used for controls whose board-specific thermal envelope cannot be inferred.
SETTINGS = {
    "CPU_GOVERNOR": ("adaptive",) * 4,
    "CPU_EPP": ("performance", "balance_performance", "balance_performance", "power"),
    "CPU_EPB": ("0", "4", "6", "15"),
    "CPU_MIN_PERF_PCT": ("keep",) * 4,
    "CPU_MAX_PERF_PCT": ("100", "100", "100", "55"),
    "CPU_NO_TURBO": ("0", "0", "0", "1"),
    "CPU_HWP_DYNAMIC_BOOST": ("1", "1", "0", "0"),
    "CPU_MIN_FREQ_KHZ": ("keep",) * 4,
    "CPU_MAX_FREQ_KHZ": ("keep",) * 4,
    "UNCORE_MIN_FREQ_KHZ": ("keep",) * 4,
    "UNCORE_MAX_FREQ_KHZ": ("keep",) * 4,
    "GPU_MIN_FREQ_MHZ": ("keep",) * 4,
    "GPU_MAX_FREQ_MHZ": ("max", "max", "keep", "efficient"),
    "GPU_BOOST_FREQ_MHZ": ("max", "max", "keep", "efficient"),
    "RAPL_PL1_POWER_UW": ("keep",) * 4,
    "RAPL_PL1_WINDOW_US": ("keep",) * 4,
    "RAPL_PL2_POWER_UW": ("keep",) * 4,
    "RAPL_PL2_WINDOW_US": ("keep",) * 4,
    "RAPL_PL4_POWER_UW": ("keep",) * 4,
    "RAPL_PL4_WINDOW_US": ("keep",) * 4,
}


class Backend:
    def __init__(self, root: Path = Path("/")) -> None:
        self.root = root
        self.knobs: dict[str, Knob] = {}
        self.telemetry: dict[str, object] = {}
        self.unavailable: list[str] = []
        cpuinfo = (root / "proc/cpuinfo").read_text(encoding="ascii")
        if len(cpuinfo) > 4 * 1024 * 1024:
            raise TuningError("CPU inventory exceeds supported size")
        vendors = re.findall(r"^vendor_id\s*:\s*(\S+)", cpuinfo, re.M)
        if not vendors or set(vendors) != {"GenuineIntel"}:
            raise TuningError("Intel CPU not detected at runtime")
        self.telemetry["cpu_model"] = re.findall(r"^model name\s*:\s*(.*)", cpuinfo, re.M)[:1]
        self.package_count = max(1, len(set(re.findall(r"^physical id\s*:\s*(\d+)", cpuinfo, re.M))))
        self.manager_states = None
        self.manager_error = None
        self.discover()

    def optional_int(self, path: Path) -> int | None:
        try:
            return int(read_text(path))
        except (OSError, ValueError):
            return None

    def attribute(self, path: Path, setting: str, low: int | None = None,
                  high: int | None = None, **kwargs: object) -> None:
        if not path.is_file():
            return
        canonical = path.resolve(strict=True)
        if not canonical.is_relative_to((self.root / "sys").resolve()):
            raise TuningError("sysfs attribute escaped the trusted kernel tree")
        key = str(canonical.relative_to(self.root))
        if key in self.knobs:
            return  # i915 compatibility attributes can alias per-GT attributes.
        is_string = bool(kwargs.get("choices"))

        def read() -> object:
            text = read_text(canonical)
            return text if is_string else int(text)

        def write(value: object) -> None:
            # The actual attribute is not a symlink. Kernel-owned ancestor
            # symlinks were resolved above; users cannot mutate sysfs parents.
            fd = os.open(canonical, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
            try:
                content = (str(value) + "\n").encode("ascii")
                if os.write(fd, content) != len(content):
                    raise TuningError(f"short sysfs write: {key}")
            finally:
                os.close(fd)

        # Mode-bit inspection is not a write probe. The driver may still reject
        # a root-writable attribute due to firmware locks or current state.
        if not canonical.stat().st_mode & stat.S_IWUSR:
            self.unavailable.append(f"{key}: read-only kernel attribute; current={read()!r}")
            return
        self.knobs[key] = Knob(key, setting, read, write, low, high, **kwargs)

    def pair(self, directory: Path, min_name: str, max_name: str, low: int | None,
             high: int | None, min_setting: str, max_setting: str, unit: str,
             symbols: dict[str, object] | None = None) -> None:
        pair_id = str(directory.resolve())
        for leaf, setting, side in [(min_name, min_setting, "min"), (max_name, max_setting, "max")]:
            self.attribute(directory / leaf, setting, low, high, pair=pair_id,
                           side=side, unit=unit, symbols=symbols or {})

    def discover(self) -> None:
        cpu = self.root / "sys/devices/system/cpu"
        for directory in sorted((cpu / "cpufreq").glob("policy[0-9]*")):
            try:
                driver = read_text(directory / "scaling_driver")
                governors = tuple(read_text(directory / "scaling_available_governors").split())
            except OSError:
                continue
            if driver not in {"intel_pstate", "intel_cpufreq", "acpi-cpufreq"}:
                self.unavailable.append(f"{directory.name}: unsupported CPUFreq driver {driver}")
                continue
            adaptive = "powersave" if driver == "intel_pstate" else "schedutil"
            if adaptive not in governors:
                adaptive = "ondemand" if "ondemand" in governors else None
            # Generic powersave pins the minimum frequency; it is NOT the
            # adaptive intel_pstate algorithm. Never silently select it.
            self.attribute(directory / "scaling_governor", "CPU_GOVERNOR", choices=governors,
                           symbols={"adaptive": adaptive} if adaptive else {}, unit="enum")
            prefs = directory / "energy_performance_available_preferences"
            if prefs.is_file():
                choices = tuple(read_text(prefs).split())
                # An active intel_pstate performance governor rejects nonzero EPP.
                self.attribute(directory / "energy_performance_preference", "CPU_EPP",
                               choices=choices, unit="enum")
            self.pair(directory, "scaling_min_freq", "scaling_max_freq",
                      self.optional_int(directory / "cpuinfo_min_freq"),
                      self.optional_int(directory / "cpuinfo_max_freq"),
                      "CPU_MIN_FREQ_KHZ", "CPU_MAX_FREQ_KHZ", "kHz")
            self.telemetry[str(directory.relative_to(self.root))] = {
                name: self.optional_int(directory / name)
                for name in ("scaling_cur_freq", "cpuinfo_min_freq", "cpuinfo_max_freq", "base_frequency")}
        ps = cpu / "intel_pstate"
        self.pair(ps, "min_perf_pct", "max_perf_pct", 0, 100,
                  "CPU_MIN_PERF_PCT", "CPU_MAX_PERF_PCT", "%")
        for leaf, setting in [("no_turbo", "CPU_NO_TURBO"), ("hwp_dynamic_boost", "CPU_HWP_DYNAMIC_BOOST")]:
            self.attribute(ps / leaf, setting, 0, 1, unit="boolean")
        for path in sorted(cpu.glob("cpu[0-9]*/power/energy_perf_bias")):
            self.attribute(path, "CPU_EPB", 0, 15)
        uncore = sorted((cpu / "intel_uncore_frequency").glob("*"))
        # TPMI's aggregate package controls overwrite fabric-cluster limits.
        # Prefer independent cluster controls when present, never both layers.
        clusters = [p for p in uncore if re.fullmatch(r"uncore[0-9]+", p.name)]
        for directory in clusters or uncore:
            if directory.is_dir():
                self.pair(directory, "min_freq_khz", "max_freq_khz",
                          self.optional_int(directory / "initial_min_freq_khz"),
                          self.optional_int(directory / "initial_max_freq_khz"),
                          "UNCORE_MIN_FREQ_KHZ", "UNCORE_MAX_FREQ_KHZ", "kHz")
        for card in sorted((self.root / "sys/class/drm").glob("card[0-9]*")):
            if not re.fullmatch(r"card[0-9]+", card.name):
                continue
            try:
                if read_text(card / "device/vendor") != "0x8086":
                    continue
            except OSError:
                continue
            gts = sorted(card.glob("gt/gt[0-9]*"))
            if gts:
                for gt in gts:
                    self.i915(gt, "rps_")
            else:
                self.i915(card, "gt_")
            for gt in sorted((card / "device").glob("tile[0-9]*/gt[0-9]*/freq0")):
                efficient = self.optional_int(gt / "rpe_freq")
                symbols = {"efficient": efficient} if efficient is not None else {}
                self.pair(gt, "min_freq", "max_freq", self.optional_int(gt / "rpn_freq"),
                          self.optional_int(gt / "rp0_freq"), "GPU_MIN_FREQ_MHZ", "GPU_MAX_FREQ_MHZ", "MHz", symbols)
                self.telemetry[str(gt.relative_to(self.root))] = {
                    key: self.optional_int(gt / key) for key in ("act_freq", "cur_freq", "rpn_freq", "rp0_freq", "rpe_freq")}
        # Limit defaults to package domains. Per-domain controls still appear in
        # the report and can be explicitly selected using identifier overrides.
        seen = set()
        powercap = self.root / "sys/class/powercap"
        # Both flat class aliases and nested control-type layouts occur. Use
        # bounded explicit depths so kernel symlinks are followed deliberately.
        directories = set()
        for pattern in ("intel-rapl*", "intel-rapl*/intel-rapl*", "intel-rapl*/intel-rapl*/intel-rapl*"):
            directories.update(powercap.glob(pattern))
        for directory in sorted(directories):
            if not re.fullmatch(r"intel-rapl(?:-mmio)?(?::[0-9]+){1,3}", directory.name):
                continue
            if not directory.is_dir() or directory.resolve() in seen:
                continue
            seen.add(directory.resolve())
            try:
                zone = read_text(directory / "name")
            except OSError:
                continue
            enabled = self.optional_int(directory / "enabled")
            self.telemetry[str(directory.relative_to(self.root))] = {
                "name": zone, "enabled": enabled,
                "energy_uj": self.optional_int(directory / "energy_uj"),
                "max_energy_range_uj": self.optional_int(directory / "max_energy_range_uj"),
            }
            if enabled == 0:
                self.unavailable.append(f"{directory.name}/{zone}: RAPL zone disabled; not enabled or tuned implicitly")
                continue
            for name_file in sorted(directory.glob("constraint_[0-9]*_name")):
                name = read_text(name_file)
                short = {"long_term": "PL1", "short_term": "PL2", "peak_power": "PL4"}.get(name)
                if short is None:
                    continue
                prefix = name_file.name.removesuffix("name")
                for leaf, bounds, suffix, unit in [("power_limit_uw", "power_uw", "POWER_UW", "uW"),
                                                   ("time_window_us", "time_window_us", "WINDOW_US", "us")]:
                    path = directory / (prefix + leaf)
                    setting = f"RAPL_{short}_{suffix}" if zone.startswith("package-") else f"DOMAIN_{zone}_{short}_{suffix}"
                    current = self.optional_int(path)
                    self.attribute(path, setting,
                                   self.positive_bound(directory / (prefix + "min_" + bounds)),
                                   self.positive_bound(directory / (prefix + "max_" + bounds)),
                                   unit=unit, power_default=current,
                                   verified_bounds_allowed=setting.startswith("RAPL_"),
                                   note="Optional RAPL bounds may be absent. Missing bounds require explicitly acknowledged administrator-verified platform limits; no board limits are guessed.")
        self.unavailable.append("CPU/GPU voltage offsets and unlocked multiplier overclocking: no portable safe sysfs ABI; raw MSR writes are deliberately unavailable")

    def i915(self, directory: Path, prefix: str) -> None:
        lo = self.optional_int(directory / (prefix + "RPn_freq_mhz"))
        hi = self.optional_int(directory / (prefix + "RP0_freq_mhz"))
        efficient = self.optional_int(directory / (prefix + "RP1_freq_mhz"))
        symbols = {"efficient": efficient} if efficient is not None else {}
        self.pair(directory, prefix + "min_freq_mhz", prefix + "max_freq_mhz", lo, hi,
                  "GPU_MIN_FREQ_MHZ", "GPU_MAX_FREQ_MHZ", "MHz", symbols)
        self.attribute(directory / (prefix + "boost_freq_mhz"), "GPU_BOOST_FREQ_MHZ", lo, hi,
                       unit="MHz", symbols=symbols)
        self.telemetry[str(directory.relative_to(self.root))] = {
            key: self.optional_int(directory / (prefix + key))
            for key in ("cur_freq_mhz", "act_freq_mhz", "RPn_freq_mhz", "RP0_freq_mhz", "RP1_freq_mhz")}

    def positive_bound(self, path: Path) -> int | None:
        value = self.optional_int(path)
        # Zero is an unavailable RAPL bound, not permission to set a zero cap.
        return value if value is not None and value > 0 else None

    def check_ownership(self, values: dict) -> None:
        owned = {self.knobs[k].setting for k in values if k in self.knobs}
        if not any(k.startswith(("CPU_", "RAPL_", "DOMAIN_", "UNCORE_")) for k in owned):
            return
        if self.manager_states is None and self.manager_error is None:
            try:
                self.manager_states = system_state.power_managers()
            except (OSError, TuningError) as exc:
                self.manager_error = str(exc)
        if self.manager_error:
            raise TuningError(self.manager_error)
        active = [name for name, state in self.manager_states.items()
                  if state not in {"inactive", "failed", "not-loaded"}]
        if active:
            raise TuningError("CPU tuning requires one policy owner; stop/mask the competing policy service explicitly before enabling custom tuning: " + ", ".join(active))

    def platform_report(self) -> dict:
        result = system_state.platform_report(self.root)
        result["competing_policy_services"] = self.manager_states
        result["policy_owner_query_error"] = self.manager_error
        result["thermal_policy"] = "thermald and firmware protection are retained; do not disable thermal protection to force a limit"
        return result

    def temperature(self) -> float | None:
        values, devices = [], 0
        for hw in (self.root / "sys/class/hwmon").glob("hwmon[0-9]*"):
            try:
                if read_text(hw / "name") != "coretemp":
                    continue
            except OSError:
                continue
            devices += 1
            sensors = list(hw.glob("temp[0-9]*_input"))
            if not sensors:
                return None
            for path in sensors:
                value = self.optional_int(path)
                if value is None or not 0 < value < 150000:
                    return None
                values.append(value / 1000)
        # One readable package must not mask a missing sensor on another CPU.
        return max(values) if values and devices >= self.package_count else None

    def close(self) -> None:
        pass
