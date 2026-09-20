"""Small, shared, non-shell hardware-tuning primitives (Python standard library)."""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Callable

PROFILES = ("performance", "high", "balanced", "silent")
VENDORS = ("intel", "nvidia")
RANK = {name: len(PROFILES) - i for i, name in enumerate(PROFILES)}
CONFIG = Path("/etc/hardware-tuning")
STATE = Path("/run/hardware-tuning")
SOCKET = "/run/hardware-tuning/control.sock"
AUTOSTART = Path("/etc/systemd/system/multi-user.target.wants/hardware-tuning-autostart.service")
AUTOSTART_UNIT = "/etc/systemd/system/hardware-tuning-autostart.service"
MAX_JSON = 4 * 1024 * 1024


class TuningError(RuntimeError):
    """An operation could not be completed safely; do not silently downgrade it."""


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TuningError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(text: str | bytes) -> Any:
    return json.loads(text, object_pairs_hook=strict_object,
                      parse_constant=lambda x: (_ for _ in ()).throw(TuningError(f"nonfinite JSON: {x}")))


def trusted_json(path: Path, maximum: int = MAX_JSON) -> Any:
    """No symlinks, nonregular files, untrusted owners, or mutable ancestors."""
    for parent in [path.parent, *path.parents][:-1]:
        st = parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise TuningError(f"untrusted directory: {parent}")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022 or st.st_size > maximum:
            raise TuningError(f"untrusted configuration/state: {path}")
        data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise TuningError("JSON size limit exceeded")
        return decode(data)


def atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    """The parent must already be a private/root-controlled directory."""
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(data) > MAX_JSON:
        raise TuningError("state exceeds size limit")
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".tuning-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def read_text(path: Path) -> str:
    with path.open("r", encoding="ascii") as stream:
        value = stream.read(16385)
    if len(value) > 16384:
        raise TuningError(f"oversized kernel attribute: {path}")
    return value.strip()


def integer(value: Any, low: int, high: int) -> int:
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r"-?(?:0|[1-9][0-9]{0,15})", value):
        result = int(value)
    else:
        raise TuningError(f"expected an integer, got {value!r}")
    if not low <= result <= high:
        raise TuningError(f"{result} is outside [{low}, {high}]")
    return result


def safe_value(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_,.-]{1,100}", value):
        raise TuningError("tuning values must be bounded scalar strings")
    return value


@dataclasses.dataclass
class Knob:
    id: str
    setting: str
    read: Callable[[], Any]
    write: Callable[[Any], None]
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    symbols: dict[str, Any] = dataclasses.field(default_factory=dict)
    unit: str = "integer"
    pair: str | None = None
    side: str | None = None
    overclock: bool = False
    power_default: int | None = None
    restorable: bool = True
    note: str = ""
    validate_extra: Callable[[Any], None] | None = None
    companions: tuple[str, ...] = ()
    verified_bounds_allowed: bool = False

    def effective_bounds(self, policy: dict[str, Any]) -> tuple[int | None, int | None, str]:
        configured = policy.get("verified_bounds", {}).get(self.setting)
        if configured is None:
            return self.minimum, self.maximum, "driver-advertised; missing bounds remain unknown"
        if not self.verified_bounds_allowed or not policy.get("allow_verified_bounds", False):
            raise TuningError(f"{self.id}: administrator-verified bounds are not enabled for this control")
        low, high = configured["minimum"], configured["maximum"]
        # Operator constraints can fill missing bounds or narrow known bounds,
        # but NEVER widen a range advertised by the kernel/driver.
        if self.minimum is not None:
            low = max(low, self.minimum)
        if self.maximum is not None:
            high = min(high, self.maximum)
        if low > high:
            raise TuningError(f"{self.id}: verified bounds do not intersect the driver range")
        return low, high, "administrator-verified platform limits, intersected with every known driver bound"

    def resolve(self, value: str, policy: dict[str, Any]) -> Any:
        safe_value(value)
        if value == "keep":
            return None
        low, high, _ = self.effective_bounds(policy)
        if value in self.symbols:
            candidate = self.symbols[value]
        elif value == "min" and low is not None:
            candidate = low
        elif value == "max" and high is not None:
            candidate = high
        else:
            candidate = value
        if self.choices:
            if str(candidate) not in self.choices:
                raise TuningError(f"{self.id}: unsupported choice {candidate!r}")
            candidate = str(candidate)
        elif self.unit == "MHz-pair":
            parts = str(candidate).split(",")
            if len(parts) != 2 or low is None or high is None:
                raise TuningError(f"{self.id}: expected two advertised clock limits")
            candidate = [integer(v, low, high) for v in parts]
            if candidate[0] > candidate[1]:
                raise TuningError(f"{self.id}: minimum exceeds maximum")
        else:
            if low is None or high is None:
                raise TuningError(f"{self.id}: hardware did not advertise usable bounds")
            candidate = integer(candidate, low, high)
        if self.overclock and candidate > 0 and not policy["allow_overclock"]:
            raise TuningError(f"{self.id}: positive offsets require allow_overclock=true")
        if self.power_default is not None and candidate > self.power_default and not policy["allow_power_increase"]:
            raise TuningError(f"{self.id}: exceeding the baseline/default power limit requires allow_power_increase=true")
        if not self.restorable and not policy["exclusive_clock_control"]:
            raise TuningError(f"{self.id}: no portable lock-range getter; exclusive_clock_control=true is required")
        if self.validate_extra:
            self.validate_extra(candidate)
        return candidate

    def report(self, profiles: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
        try:
            current, error = (self.read(), None) if self.restorable else (None, "not queryable through the portable driver ABI")
        except (OSError, TuningError) as exc:
            current, error = None, str(exc)
        try:
            effective_min, effective_max, bound_source = self.effective_bounds(policy)
        except TuningError as exc:
            effective_min, effective_max, bound_source = None, None, str(exc)
        proposed = {}
        for name in PROFILES:
            value = profiles[name]["overrides"].get(self.id, profiles[name]["knobs"].get(self.setting, "keep"))
            try:
                resolved = self.resolve(value, policy)
                proposed[name] = {"configured": value, "resolved": resolved,
                                  "meaning": "leave unchanged" if resolved is None else "bounded request; not a stability guarantee"}
            except TuningError as exc:
                proposed[name] = {"configured": value, "error": str(exc)}
        return {"id": self.id, "setting": self.setting, "unit": self.unit,
                "current": current, "read_error": error, "minimum": self.minimum,
                "maximum": self.maximum, "effective_minimum": effective_min,
                "effective_maximum": effective_max, "bounds_source": bound_source,
                "choices": self.choices,
                "symbols": self.symbols, "restores_previous_value": self.restorable,
                "note": self.note, "profiles": proposed}


def validate_policy(data: Any, settings: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    fields = {"version", "allow_overclock", "allow_power_increase", "exclusive_clock_control",
              "max_temperature_c", "profiles"}
    optional = {"allow_verified_bounds", "verified_bounds"}
    if (not isinstance(data, dict) or not fields <= set(data) or set(data) - fields - optional
            or type(data["version"]) is not int or data["version"] != 1):
        raise TuningError("invalid vendor configuration schema")
    if type(data.get("allow_verified_bounds", False)) is not bool:
        raise TuningError("allow_verified_bounds must be a JSON boolean")
    verified = data.get("verified_bounds", {})
    allowed_verified = {k for k in settings if re.fullmatch(r"RAPL_PL[124]_(?:POWER_UW|WINDOW_US)", k)}
    if not isinstance(verified, dict) or not set(verified) <= allowed_verified:
        raise TuningError("verified bounds are only supported for named package RAPL constraints")
    if verified and not data.get("allow_verified_bounds", False):
        raise TuningError("verified bounds require an explicit allow_verified_bounds=true acknowledgement")
    for bounds in verified.values():
        if (not isinstance(bounds, dict) or set(bounds) != {"minimum", "maximum"}
                or any(type(v) is not int for v in bounds.values())):
            raise TuningError("verified RAPL bounds require integer minimum and maximum")
        low = integer(bounds["minimum"], 1, 2**63 - 1)
        high = integer(bounds["maximum"], 1, 2**63 - 1)
        if low > high:
            raise TuningError("inverted verified RAPL bounds")
    for key in ("allow_overclock", "allow_power_increase", "exclusive_clock_control"):
        if type(data[key]) is not bool:
            raise TuningError(f"{key} must be a JSON boolean")
    if type(data["max_temperature_c"]) is not int:
        raise TuningError("max_temperature_c must be a JSON integer")
    integer(data["max_temperature_c"], 50, 95)
    if not isinstance(data["profiles"], dict) or set(data["profiles"]) != set(PROFILES):
        raise TuningError("all four profiles must be specified")
    for profile_name, profile in data["profiles"].items():
        if not isinstance(profile, dict) or set(profile) != {"knobs", "overrides"}:
            raise TuningError("a profile must contain knobs and overrides")
        if not isinstance(profile["knobs"], dict) or set(profile["knobs"]) != set(settings):
            raise TuningError("missing or unknown tuning knob")
        if not isinstance(profile["overrides"], dict) or len(profile["overrides"]) > 4096:
            raise TuningError("invalid per-device overrides")
        for key, value in profile["overrides"].items():
            if not isinstance(key, str) or len(key) > 512 or ".." in key:
                raise TuningError("invalid hardware identifier")
            safe_value(value)
        for value in profile["knobs"].values():
            safe_value(value)
        if "CPU_EPP" in settings:
            epp = profile["knobs"]["CPU_EPP"]
            if epp not in {"keep", "default", "performance", "balance_performance", "balance_power", "power", "balanced"}:
                raise TuningError("invalid configured Intel EPP")
            if epp == "balanced" and profile_name != "balanced":
                raise TuningError("the balanced EPP selector is restricted to the Balanced profile")
    return data
