"""Validated transactions and write-ahead recovery for hardware controls.

Journal identifiers are resolved against a fresh driver inventory, never used
as user-provided filesystem paths. A failed restoration keeps its journal.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import importlib
import json
import os
from pathlib import Path
import sys
import stat
from typing import Any
from common import (CONFIG, STATE, PROFILES, VENDORS, Knob, TuningError,
                    atomic_json, read_text, trusted_json, validate_policy)


class Engine:
    def __init__(self, backend, journal: Path, policy: dict | None = None) -> None:
        self.backend, self.path, self.policy = backend, journal, policy
        self.journal = trusted_json(journal) if journal.exists() else {"version": 1, "entries": [], "profile": None}
        if (not isinstance(self.journal, dict) or set(self.journal) != {"version", "entries", "profile"}
                or type(self.journal["version"]) is not int or self.journal["version"] != 1
                or not isinstance(self.journal["entries"], list) or self.journal["profile"] not in (*PROFILES, None)):
            raise TuningError("invalid recovery journal")
        if len(self.journal["entries"]) > 8192:
            raise TuningError("recovery journal exceeds supported device count")
        ids = set()
        for entry in self.journal["entries"]:
            if not isinstance(entry, dict) or set(entry) != {"id", "before", "last", "pending", "requested"} or not isinstance(entry["id"], str) or entry["id"] in ids:
                raise TuningError("invalid or duplicate recovery entry")
            if type(entry["pending"]) is not bool:
                raise TuningError("invalid recovery phase")
            ids.add(entry["id"])
            knob = self.backend.knobs.get(entry["id"])
            if knob and knob.power_default is not None and knob.setting.startswith(("RAPL_", "DOMAIN_")):
                # Never ratchet the power-increase gate from an already-tuned limit.
                knob.power_default = entry["before"]

    def save(self) -> None:
        atomic_json(self.path, self.journal)

    def health(self) -> dict:
        conflicts = []
        for entry in self.journal["entries"]:
            knob = self.backend.knobs.get(entry["id"])
            if knob is None:
                conflicts.append(entry["id"] + ": device/control disappeared")
            elif entry["pending"]:
                conflicts.append(entry["id"] + ": interrupted transaction")
            elif knob.restorable and knob.read() != entry["last"]:
                conflicts.append(entry["id"] + ": changed by firmware/another power manager")
        checker = getattr(self.backend, "check_ownership", None)
        if checker and self.journal["entries"]:
            try:
                checker({e["id"]: e["requested"] for e in self.journal["entries"]})
            except (OSError, TuningError) as exc:
                conflicts.append(str(exc))
        temperature = self.backend.temperature()
        if temperature is None:
            for entry in self.journal["entries"]:
                knob = self.backend.knobs.get(entry["id"])
                value = entry["requested"]
                if knob and type(value) is int and ((knob.overclock and value > 0)
                        or (knob.power_default is not None and value > knob.power_default)):
                    conflicts.append("thermal sensor disappeared while an overclock/power increase is owned")
                    break
        if self.policy and temperature is not None and temperature >= self.policy["max_temperature_c"]:
            conflicts.append(f"thermal interlock: {temperature} C >= {self.policy['max_temperature_c']} C")
        return {"conflicts": conflicts, "temperature_c": temperature,
                "temperature_available": temperature is not None}

    def ordered(self, values: dict[str, Any]):
        """Re-evaluate paired limits after preceding governor/turbo writes."""
        knobs = self.backend.knobs
        early = {"CPU_GOVERNOR": 0, "CPU_NO_TURBO": 1, "CPU_MIN_PERF_PCT": 2, "CPU_MAX_PERF_PCT": 2}
        late = {"CPU_EPP": 5, "CPU_EPB": 6, "AUTO_BOOST": 7}
        done = set()
        for key in sorted(values, key=lambda k: (early.get(knobs[k].setting, late.get(knobs[k].setting, 3)), k)):
            if key in done:
                continue
            knob = knobs[key]
            group = [k for k in values if knob.pair and knobs[k].pair == knob.pair]
            if len(group) == 2:
                lo = next(k for k in group if knobs[k].side == "min")
                hi = next(k for k in group if knobs[k].side == "max")
                order = [hi, lo] if values[lo] > knobs[hi].read() else [lo, hi]
                for k in order:
                    done.add(k)
                    yield k, values[k]
            else:
                done.add(key)
                yield key, values[key]

    def reset(self) -> dict:
        entries = {e["id"]: e for e in self.journal["entries"]}
        restore, yielded, failures = {}, [], []
        for key, entry in entries.items():
            knob = self.backend.knobs.get(key)
            if knob is None:
                failures.append(f"{key}: missing from hardware inventory; retained for recovery")
                continue
            try:
                current = knob.read()
                if entry["pending"] or not knob.restorable or current == entry["last"]:
                    restore[key] = entry["before"]
                else:
                    yielded.append(key)
            except (OSError, TuningError, ValueError) as exc:
                failures.append(f"{key}: {exc}")
        # intel_pstate percentages/turbo and per-policy frequency/governor/EPP
        # controls are coupled. Yield the complete coupled CPU policy, not only
        # one directory: restoring a global knob could overwrite another power
        # manager's per-policy update as an implicit kernel side effect.
        coupled_cpu = {"CPU_GOVERNOR", "CPU_EPP", "CPU_MIN_FREQ_KHZ", "CPU_MAX_FREQ_KHZ",
                       "CPU_MIN_PERF_PCT", "CPU_MAX_PERF_PCT", "CPU_NO_TURBO", "CPU_EPB", "CPU_HWP_DYNAMIC_BOOST"}
        cpu_conflict = any(self.backend.knobs[k].setting in coupled_cpu for k in yielded)
        for key in list(restore):
            if cpu_conflict and self.backend.knobs[key].setting in coupled_cpu:
                yielded.append(key)
                del restore[key]
        complete = set(yielded)
        # Recovery is a transaction too. Persist intent before a restore write,
        # otherwise a killed reset looks like interference on the next run.
        for key in restore:
            entries[key]["pending"] = True
        if restore:
            self.save()
        for key, value in self.ordered(restore):
            knob = self.backend.knobs[key]
            try:
                if not knob.restorable or knob.read() != value or getattr(knob, "restore_value", None):
                    restore_fn = getattr(knob, "restore_value", None) or knob.write
                    restore_fn(value)
                if knob.restorable and knob.read() != value:
                    raise TuningError("restoration readback differs from original value")
                complete.add(key)
            except (OSError, TuningError, ValueError) as exc:
                failures.append(f"{key}: {exc}")
        # Later governor/global/paired writes may alter an earlier readback.
        # Verify the complete final state, not only each intermediate write.
        for key in sorted(complete - set(yielded)):
            knob = self.backend.knobs[key]
            try:
                if knob.restorable and knob.read() != entries[key]["before"]:
                    raise TuningError("final restoration readback differs from original value")
            except (OSError, TuningError, ValueError) as exc:
                complete.discard(key)
                failures.append(f"{key}: {exc}")
        # Retain the complete side-effect domain if any restoration in it
        # failed. A later retry of a governor/pair can otherwise change a
        # successfully restored companion whose baseline was already discarded.
        failed = set(restore) - complete
        retained = set(failed)
        for key in failed:
            knob = self.backend.knobs[key]
            retained.update(k for k in restore if k in knob.companions or key in self.backend.knobs[k].companions)
            if knob.pair:
                retained.update(k for k in restore if self.backend.knobs[k].pair == knob.pair)
            if knob.setting in coupled_cpu:
                retained.update(k for k in restore if self.backend.knobs[k].setting in coupled_cpu)
        complete.difference_update(retained)
        self.journal["entries"] = [e for e in self.journal["entries"] if e["id"] not in complete]
        if not self.journal["entries"]:
            self.journal["profile"] = None
        self.save()
        if failures:
            raise TuningError("restoration incomplete; journal retained: " + "; ".join(failures))
        return {"restored": len(complete) - len(set(yielded)), "external_values_preserved": sorted(set(yielded))}

    def plan(self, name: str, settings: dict) -> tuple[dict, list[str]]:
        if self.policy is None or name not in PROFILES:
            raise TuningError("invalid profile")
        profile = self.policy["profiles"][name]
        unknown = set(profile["overrides"]) - set(self.backend.knobs)
        if unknown:
            raise TuningError("unknown/unavailable device overrides: " + ", ".join(sorted(unknown)))
        values = {}
        supported = {knob.setting for knob in self.backend.knobs.values()}
        skipped = []
        for setting, value in profile["knobs"].items():
            if value != "keep" and setting not in supported:
                # Portable defaults are optional; an administrator's explicit
                # nondefault request must fail rather than pretend to apply.
                if value != settings[setting][PROFILES.index(name)]:
                    raise TuningError(f"explicit request for unsupported knob: {setting}")
                skipped.append(setting + ": unavailable; portable default skipped")
        for key, knob in self.backend.knobs.items():
            value = profile["overrides"].get(key, profile["knobs"].get(knob.setting, "keep"))
            resolved = knob.resolve(value, self.policy)
            if resolved is not None:
                if knob.setting == "TARGET_TEMPERATURE_C" and resolved > self.policy["max_temperature_c"]:
                    raise TuningError("temperature target exceeds the thermal interlock")
                # Retain even initially equal requests until coupling has been
                # resolved: a preceding governor/turbo write may change them.
                values[key] = resolved
        for key, value in list(values.items()):
            knob = self.backend.knobs[key]
            if knob.pair:
                pair = {k.side: values.get(k.id, k.read()) for k in self.backend.knobs.values() if k.pair == knob.pair}
                if len(pair) == 2 and pair["min"] > pair["max"]:
                    raise TuningError(f"inverted min/max pair: {knob.pair}")
        for knob in self.backend.knobs.values():
            if knob.setting == "CPU_EPP":
                directory = knob.id.rsplit("/", 1)[0]
                governor = next((k for k in self.backend.knobs.values() if k.setting == "CPU_GOVERNOR" and
                                 k.id.rsplit("/", 1)[0] == directory), None)
                if governor and values.get(governor.id, governor.read()) == "performance" and values.get(knob.id, knob.read()) != "performance":
                    raise TuningError("performance governor cannot be combined with non-performance EPP")
        checker = getattr(self.backend, "check_ownership", None)
        if checker:
            checker(values)
        # Non-default clock APIs must not be applied concurrently to one GPU.
        # Their side effects and precedence are not portable across generations.
        for device in {k.split("/", 1)[0] for k in values if k.startswith("GPU-")}:
            families = {self.backend.knobs[k].setting for k in values if k.startswith(device + "/")}
            if "APPLICATION_CLOCKS_MHZ" in families and families & {"GPU_LOCK_MHZ", "MEMORY_LOCK_MHZ", "GPU_OFFSET_MHZ", "MEMORY_OFFSET_MHZ"}:
                raise TuningError("choose application clocks OR offsets/clock locks for " + device)
        return values, skipped

    def apply(self, name: str, settings: dict) -> dict:
        if self.journal["entries"]:
            conflicts = self.health()["conflicts"]
            if conflicts:
                self.reset()
                raise TuningError("yielding to external/thermal policy: " + "; ".join(conflicts))
            self.reset()
        values, skipped = self.plan(name, settings)
        temperature = self.backend.temperature()
        if temperature is not None and temperature >= self.policy["max_temperature_c"]:
            raise TuningError("thermal interlock prevents applying this profile")
        risky = any(self.backend.knobs[k].overclock and v > 0 for k, v in values.items())
        risky = risky or any(self.backend.knobs[k].power_default is not None and v > self.backend.knobs[k].power_default for k, v in values.items())
        if risky and temperature is None:
            raise TuningError("overclock/power increases require a readable temperature sensor")
        # Snapshot only changed controls and their side-effect domains. Avoid
        # owning or repeatedly writing already-correct independent attributes.
        changed = {k for k, v in values.items()
                   if not self.backend.knobs[k].restorable or self.backend.knobs[k].read() != v}
        affected = set(changed)
        for key in changed:
            knob = self.backend.knobs[key]
            affected.update(k for k in knob.companions if k in self.backend.knobs)
            if knob.pair:
                affected.update(k.id for k in self.backend.knobs.values() if k.pair == knob.pair)
            if knob.setting in {"CPU_GOVERNOR", "CPU_NO_TURBO", "CPU_MIN_PERF_PCT", "CPU_MAX_PERF_PCT"}:
                affected.update(k.id for k in self.backend.knobs.values() if k.setting in
                                {"CPU_GOVERNOR", "CPU_EPP", "CPU_EPB", "CPU_MIN_PERF_PCT", "CPU_MAX_PERF_PCT",
                                 "CPU_MIN_FREQ_KHZ", "CPU_MAX_FREQ_KHZ", "CPU_NO_TURBO"})
        # Include unchanged explicit requests in any affected domain. Recheck
        # them after earlier writes instead of omitting them based on old state.
        values = {k: v for k, v in values.items() if k in affected}
        self.journal = {"version": 1, "profile": name, "entries": [
            {"id": key, "before": self.backend.knobs[key].read(), "last": None,
             "pending": True, "requested": values.get(key)} for key in sorted(affected)]}
        self.save()  # Write-ahead snapshot precedes the FIRST hardware mutation.
        try:
            written = 0
            for key, value in self.ordered(values):
                knob = self.backend.knobs[key]
                if not knob.restorable or knob.read() != value:
                    knob.write(value)
                    written += 1
            actual = {}
            for entry in self.journal["entries"]:
                knob = self.backend.knobs[entry["id"]]
                entry["last"] = knob.read() if knob.restorable else values[entry["id"]]
                if knob.restorable and entry["id"] in values:
                    knob.resolve(str(entry["last"]), self.policy)
                    if entry["last"] != values[entry["id"]]:
                        # A legal value is not evidence that our request was
                        # accepted. Do not invent portable rounding tolerances.
                        raise TuningError(f"{knob.id}: requested {values[entry['id']]!r}, "
                                          f"read back {entry['last']!r}; rejected, quantized or overridden request")
                entry["pending"] = False
                actual[entry["id"]] = {"requested": entry["requested"], "readback": entry["last"],
                                      "hardware_readback": knob.restorable}
            self.save()
            return {"profile": name, "changed": written, "controls": actual,
                    "skipped": skipped, "temperature_c": temperature}
        except BaseException as exc:
            # Includes orderly signal interruption in the worker. SIGKILL is
            # handled by the next recovery invocation using the durable intent.
            try:
                self.reset()
            except (OSError, TuningError) as recovery:
                raise TuningError(f"apply failed ({exc}); recovery failed ({recovery})") from exc
            raise

    def report(self, settings: dict) -> dict:
        installed = self.policy["profiles"]
        supported = {k.setting for k in self.backend.knobs.values()}
        preflight = {}
        for name in PROFILES:
            try:
                values, skipped = self.plan(name, settings)
                preflight[name] = {"valid": True, "planned_changes": sum(not self.backend.knobs[k].restorable or self.backend.knobs[k].read() != v for k, v in values.items()), "skipped": skipped}
            except (OSError, TuningError, ValueError) as exc:
                preflight[name] = {"valid": False, "error": str(exc)}
        return {"generated_utc": datetime.now(timezone.utc).isoformat(),
                "read_only": True, "profile": self.journal.get("profile"),
                "profile_preflight": preflight,
                "policy": self.policy, "telemetry": self.backend.telemetry,
                "platform": getattr(self.backend, "platform_report", lambda: {})(),
                "temperature_c": self.backend.temperature(),
                "controls": [k.report(installed, self.policy) for k in self.backend.knobs.values()],
                "unavailable_settings": sorted(set(settings) - supported),
                "limitations": self.backend.unavailable,
                "recovery_entries": self.journal["entries"],
                "guidance": "Resolved values are conservative configuration suggestions within reported bounds, not benchmarked stable overclocks. keep does not modify a control. Unknown bounds remain unknown."}


def execute(vendor: str, action: str, profile: str | None = None) -> dict:
    if vendor not in VENDORS or action not in {"apply", "reset", "report", "health"}:
        raise TuningError("unsupported worker operation")
    journal = STATE / f"{vendor}.json"
    if action == "reset" and not STATE.exists():
        return {"restored": 0}
    lock = os.open(STATE / f"{vendor}.lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(lock)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600:
            raise TuningError("untrusted hardware transaction lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Check only AFTER acquiring the shared apply/reset lock. Otherwise a
        # reset can race an apply and falsely report that there is no ownership.
        old = trusted_json(journal) if journal.exists() or journal.is_symlink() else None
        if action == "reset" and (old is None or isinstance(old, dict) and old.get("version") == 1 and old.get("entries") == []):
            return {"restored": 0}
        module = importlib.import_module(vendor)
        policy = None if action == "reset" else validate_policy(trusted_json(CONFIG / f"{vendor}.json"), module.SETTINGS)
        # Health/recovery need only the owned NVIDIA families, not the complete
        # offset and clock table on every five-second poll. Full reports retain
        # exhaustive capability discovery. No driver is loaded for empty reset.
        wanted = None
        if vendor == "nvidia" and action in {"health", "reset"} and old is not None:
            wanted = {e["id"] for e in old["entries"]}
        backend = module.Backend(wanted=wanted) if vendor == "nvidia" else module.Backend()
        try:
            engine = Engine(backend, journal, policy)
            if action == "reset":
                return engine.reset()
            if action == "health":
                return engine.health()
            if action == "report":
                return engine.report(module.SETTINGS)
            return engine.apply(profile, module.SETTINGS)
        finally:
            backend.close()
    finally:
        os.close(lock)


def main(argv: list[str]) -> int:
    if os.geteuid() != 0:
        raise TuningError("the hardware worker is root-only; use the bounded control socket")
    if argv == ["recover-all"]:
        results, failed = {}, False
        for vendor in VENDORS:
            # A gated-out backend has no AppArmor lock/device permissions.
            # Still attempt recovery of an existing journal after a partial
            # installation; never create an absent vendor's lock needlessly.
            paths = (CONFIG / f"{vendor}.json", STATE / f"{vendor}.json")
            if not any(path.exists() or path.is_symlink() for path in paths):
                continue
            try:
                results[vendor] = execute(vendor, "reset")
            except (OSError, TuningError, ValueError, ImportError) as exc:
                results[vendor] = {"error": str(exc)}
                failed = True
        print(json.dumps({"ok": not failed, "result": results}))
        return int(failed)
    if len(argv) not in (2, 3):
        raise TuningError("usage: hardware-tuning-worker VENDOR ACTION [PROFILE]")
    vendor, action = argv[:2]
    if (action == "apply") != (len(argv) == 3):
        raise TuningError("only apply accepts a profile")
    result = execute(vendor, action, argv[2] if len(argv) == 3 else None)
    print(json.dumps({"ok": True, "result": result}, allow_nan=False))
    return 0
