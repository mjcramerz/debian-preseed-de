#!/usr/bin/env python3
"""Hardware tuning regression tests. No real hardware control is written.

Driver calls/sysfs are fixtures; root-owned policy checks use a private /root
fixture when run as root. Unit generation and d-i gate matrices execute for real.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file, source_stat as payload_source_stat
from payload_fixture import read_text as payload_read_text
import asyncio
import copy
import ctypes
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

FORKY = Path(__file__).resolve().parents[1]
LIB = FORKY / "hooks/target/usr/local/lib/hardware_tuning"
sys.path.insert(0, str(LIB))
import common
import engine
import intel
import nvidia
import broker
import client
spec = importlib.util.spec_from_file_location("hardware_tuning_installer", FORKY / "scripts/desktop/hardware-tuning-config.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def environment(name="btrfs-de-p15s"):
    text = payload_read_text(FORKY / f"hosts/profiles/{name}.env")
    return installer.parse_environment("\n".join(line for line in text.splitlines() if line.startswith("HARDWARE_")))


def private_temp():
    return tempfile.TemporaryDirectory(prefix="hardware-tuning-test-", dir="/root" if os.geteuid() == 0 else None)


def simple_policy(settings):
    return {"version": 1, "allow_overclock": False, "allow_power_increase": False,
            "exclusive_clock_control": False, "max_temperature_c": 85,
            "profiles": {name: {"knobs": {k: v[i] for k, v in settings.items()}, "overrides": {}}
                         for i, name in enumerate(common.PROFILES)}}


class FakeBackend:
    def __init__(self):
        self.knobs, self.values, self.writes = {}, {}, []
        self.telemetry, self.unavailable = {}, []
        self.temperature_value = 35
        self.failure = None
        self.journal = None
        self.before_write = None

    def add(self, key, setting, value, low=0, high=100, **kwargs):
        self.values[key] = value
        def write(new):
            if self.before_write:
                self.before_write(key, new)
            self.writes.append((key, new))
            if self.failure and self.failure(key, new):
                raise common.TuningError("injected driver rejection")
            knob = self.knobs[key]
            if knob.pair:
                siblings = [k for k in self.knobs.values() if k.pair == knob.pair and k.id != key]
                if siblings:
                    other = self.values[siblings[0].id]
                    if (knob.side == "min" and new > other) or (knob.side == "max" and new < other):
                        raise common.TuningError("inverted driver pair")
            self.values[key] = new
        self.knobs[key] = common.Knob(key, setting, lambda: self.values[key], write, low, high, **kwargs)
        return self.knobs[key]

    def temperature(self):
        return self.temperature_value

    def close(self):
        pass


class PolicyTests(unittest.TestCase):
    def test_all_ten_profiles_have_complete_matching_schemas(self):
        profiles = list((FORKY / "hosts/profiles").glob("*.env"))
        self.assertEqual(len(profiles), 10)
        enabled = {"btrfs-de-p15s", "btrfs-de-p15s-duo", "btrfs-de-flex", "btrfs-de-flex-duo"}
        reference_keys = set(environment())
        for path in profiles:
            with self.subTest(path=path.name):
                env = environment(path.stem)
                self.assertEqual(set(env), reference_keys)
                for vendor, module in (("intel", intel), ("nvidia", nvidia)):
                    self.assertEqual(env[installer.PREFIXES[vendor] + "ENABLE"], str(path.stem in (enabled if vendor == "intel" else {"btrfs-de-p15s", "btrfs-de-p15s-duo"})).lower())
                    value = installer.policy(env, vendor, module.SETTINGS)
                    self.assertFalse(value["allow_overclock"])
                    self.assertFalse(value["allow_power_increase"])
                    self.assertFalse(value["exclusive_clock_control"])
                    self.assertEqual(set(value["profiles"]), set(common.PROFILES))
                    for i, profile in enumerate(common.PROFILES):
                        self.assertEqual(value["profiles"][profile]["knobs"], {k: vals[i] for k, vals in module.SETTINGS.items()})
                self.assertEqual(env["HARDWARE_TUNING_AUTOSTART_ENABLE"], "false")

    def test_no_shell_evaluation_in_literal_parser(self):
        bad = ['HARDWARE_TUNING_IDLE_AC="$(touch /tmp/unsafe)"',
               'HARDWARE_TUNING_IDLE_AC="balanced"; true',
               'HARDWARE_TUNING_IDLE_AC="balanced"\nHARDWARE_TUNING_IDLE_AC="silent"',
               'NOT_HARDWARE="true"', 'HARDWARE_TUNING_IDLE_AC=balanced']
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                installer.parse_environment(text)

    def test_boolean_is_not_truthiness(self):
        for value in ("yes", "1", "TRUE", "False", "", "true "):
            with self.subTest(value=value), self.assertRaises(ValueError):
                installer.boolean(value)

    def test_duplicate_nonfinite_unknown_json_rejected(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.subTest(text=text), self.assertRaises(common.TuningError):
                common.decode(text)
        value = simple_policy({"X": ("keep",) * 4})
        value["unknown"] = True
        with self.assertRaises(common.TuningError):
            common.validate_policy(value, {"X": ("keep",) * 4})

    def test_strict_schema_types(self):
        settings = {"X": ("keep",) * 4}
        for key, bad in (("version", True), ("allow_overclock", "true"), ("max_temperature_c", "85"), ("max_temperature_c", 99)):
            value = simple_policy(settings)
            value[key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(common.TuningError):
                common.validate_policy(value, settings)

    def test_semantic_value_injection_and_unknown_override_are_rejected(self):
        for bad in ("10\n20", "/sys/devices/foo", "$(id)", "1 2", True, 10):
            with self.subTest(bad=bad), self.assertRaises(common.TuningError):
                common.safe_value(bad)
        policy = simple_policy({"X": ("keep",) * 4})
        policy["profiles"]["high"]["overrides"]["../../etc/shadow"] = "10"
        with self.assertRaises(common.TuningError):
            common.validate_policy(policy, {"X": ("keep",) * 4})

    def test_broker_config_cannot_select_privileged_account_or_unknown_vendor(self):
        data = {"version": 1, "uid": 1000, "vendors": ["intel"], "poll_seconds": 5, "idle_ac": "balanced", "idle_battery": "silent"}
        for key, bad in (("uid", 0), ("vendors", ["intel", "intel"]), ("vendors", ["../nvidia"]), ("poll_seconds", 1), ("idle_ac", "turbo")):
            with self.subTest(key=key), self.assertRaises(common.TuningError):
                broker.validate_config(dict(data, **{key: bad}))

    @unittest.skipUnless(os.geteuid() == 0, "root-owned path validation requires root fixtures")
    def test_root_configuration_file_and_ancestor_checks(self):
        with private_temp() as temporary:
            root = Path(temporary)
            data = root / "value.json"
            common.atomic_json(data, {"value": 1})
            self.assertEqual(common.trusted_json(data), {"value": 1})
            self.assertEqual(payload_source_stat(data).st_mode & 0o777, 0o600)
            link = root / "link.json"
            link.symlink_to(data)
            with self.assertRaises((OSError, common.TuningError)):
                common.trusted_json(link)
            data.chmod(0o666)
            with self.assertRaises(common.TuningError):
                common.trusted_json(data)
            data.chmod(0o600)
            root.chmod(0o777)
            with self.assertRaises(common.TuningError):
                common.trusted_json(data)
            root.chmod(0o700)
            with self.assertRaises(common.TuningError):
                common.trusted_json(data, maximum=2)


class InstallerTests(unittest.TestCase):
    def test_all_32_flag_class_and_detection_combinations(self):
        source = FORKY / "scripts/desktop/hardware-tuning.sh"
        for intelflag, intelcpu, nvflag, nvclass, nvgpu in itertools.product((False, True), repeat=5):
            with self.subTest(flags=(intelflag, intelcpu, nvflag, nvclass, nvgpu)), private_temp() as temporary:
                root = Path(temporary)
                (root / "target/tmp").mkdir(parents=True)
                profile = root / "profile.env"
                profile.write_text("HARDWARE_TUNING_POLL_SECONDS=\"5\"\n")
                script = f'''
. {shlex.quote(str(FORKY / "scripts/late/target-assets.sh"))}
. {shlex.quote(str(source))}
desktop_hardware_intel_detected() {{ return {0 if intelcpu else 1}; }}
installer_nvidia_addon_selected() {{ return {0 if nvclass else 1}; }}
installer_nvidia_gpu_detected() {{ return {0 if nvgpu else 1}; }}
desktop_log() {{ :; }}
installer_fatal() {{ echo "$*" >&2; return 1; }}
desktop_stage_role_asset() {{ printf '%s\\n' "$1" >> "$FIXTURE/trace"; }}
ensure_target_asset_parent() {{ mkdir -p "$FIXTURE/target$(dirname "$1")"; }}
target_asset_host_path() {{ printf '%s/target%s\\n' "$FIXTURE" "$1"; }}
fetch_hook() {{ cp "$FIXTURE_SOURCE/$1" "$2"; }}
installer_repo_join_var() {{ printf '%s/%s\\n' hooks/target "$2"; }}
run_in_target() {{ printf '%s\\n' "$*" >> "$FIXTURE/commands"; }}
HARDWARE_INTEL_CPU_TUNING_ENABLE={str(intelflag).lower()}
HARDWARE_NVIDIA_GPU_TUNING_ENABLE={str(nvflag).lower()}
LATE_COMMAND_HOST_ENV="$FIXTURE/profile.env"
ACCOUNT_USERNAME=desktop
desktop_install_hardware_tuning
'''
                result = subprocess.run(payload_installed_argv(["/bin/sh", "-eu", "-c", script]), env=dict(os.environ, FIXTURE=str(root), FIXTURE_SOURCE=str(FORKY)), capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                assets = payload_read_text(root / "trace").splitlines() if payload_source_exists(root / "trace") else []
                wanted_intel, wanted_nv = intelflag and intelcpu, nvflag and nvclass and nvgpu
                self.assertEqual("usr/local/lib/hardware_tuning/intel.py" in assets, wanted_intel)
                self.assertEqual("usr/local/lib/hardware_tuning/system_state.py" in assets, wanted_intel or wanted_nv)
                self.assertEqual("usr/local/lib/hardware_tuning/policy_owner.py" in assets, wanted_intel or wanted_nv)
                self.assertEqual("usr/local/lib/hardware_tuning/nvidia.py" in assets, wanted_nv)
                self.assertEqual("etc/apparmor.d/abstractions/hardware-tuning-intel" in assets, wanted_intel)
                self.assertEqual("etc/apparmor.d/abstractions/hardware-tuning-nvidia" in assets, wanted_nv)
                self.assertEqual(bool(assets), wanted_intel or wanted_nv)
                self.assertEqual(list((root / "target/tmp").glob("installer-hardware-tuning.*")), [])

    @unittest.skipUnless(os.geteuid() == 0, "installer fixture requires root ownership")
    def test_generation_vendor_matrix_and_preserved_left_click(self):
        for vendors in (["intel"], ["nvidia"], ["intel", "nvidia"]):
            with self.subTest(vendors=vendors), private_temp() as temporary:
                root = Path(temporary)
                path = root / "etc/skel-desktop/.config/waybar/config"
                path.parent.mkdir(parents=True)
                original = [{"name": "internal", "battery": {"on-click": "original-energy-profile-command", "interval": 5}},
                            {"name": "external", "battery": {"on-click": "another original", "states": {"critical": 15}}}]
                path.write_text(json.dumps(original))
                installer.install(root, 1000, 1000, environment(), vendors, FORKY / "hooks/target")
                installed = json.loads(payload_read_text(path))
                for before, after in zip(original, installed):
                    self.assertEqual(after["battery"].pop("on-click-right"), installer.CLICK)
                    self.assertEqual(after, before)
                self.assertTrue((root / "etc/systemd/system/sockets.target.wants/hardware-tuning.socket").is_symlink())
                self.assertTrue((root / "etc/systemd/system/sleep.target.requires/hardware-tuning-sleep.service").is_symlink())
                self.assertFalse(payload_source_exists(root / "etc/systemd/system/multi-user.target.wants/hardware-tuning-autostart.service"))
                for vendor in common.VENDORS:
                    self.assertEqual(payload_source_is_file(root / f"etc/hardware-tuning/{vendor}.json"), vendor in vendors)
                    for profile in common.PROFILES:
                        target = root / f"etc/systemd/user/{vendor}-{profile}.target"
                        service = root / f"etc/systemd/user/hardware-tuning-{vendor}-{profile}.service"
                        self.assertEqual(payload_source_is_file(target), vendor in vendors)
                        self.assertEqual(payload_source_is_file(service), vendor in vendors)
                        if vendor in vendors:
                            self.assertIn("StopWhenUnneeded=yes", payload_read_text(target))
                            self.assertIn(f"PartOf={vendor}-{profile}.target labwc-session.target", payload_read_text(service))
                for app, profile in installer.APPLICATIONS.items():
                    self.assertNotIn("*", app)
                    text = payload_read_text(root / f"etc/systemd/user/{app}.d/85-hardware-tuning.conf")
                    actual = [line for line in text.splitlines() if line and not line.startswith("#")]
                    self.assertFalse(any(line.startswith(("PartOf=", "BindsTo=", "Requires=")) for line in actual))
                    self.assertIn("Wants=" + " ".join(f"{v}-{profile}.target" for v in vendors), actual)
                    self.assertIn("Upholds=" + " ".join(f"{v}-{profile}.target" for v in vendors), actual)
                system_unit = payload_read_text(root / "etc/systemd/system/hardware-tuning.service")
                self.assertIn("ExecStopPost=/usr/local/libexec/hardware-tuning-worker recover-all", system_unit)
                self.assertEqual("CapabilityBoundingSet=CAP_SYS_ADMIN" in system_unit, "nvidia" in vendors)

    def test_tuning_uses_only_supported_dash_prefix_families(self):
        self.assertEqual(installer.APPLICATIONS, {
            "labwc-native-.service": "high",
            "labwc-wayland-.service": "balanced",
            "labwc-electron-.service": "high",
            "labwc-devops-.service": "performance",
            "llama-server.service": "performance",
        })

    @unittest.skipUnless(os.geteuid() == 0, "installer fixture requires root ownership")
    def test_disabled_vendor_and_unsafe_target_rejected(self):
        with private_temp() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                installer.install(root, 1000, 1000, environment("btrfs-de"), ["intel"], FORKY / "hooks/target")
            self.assertEqual(list(root.iterdir()), [])
            (root / "etc").symlink_to("/tmp")
            with self.assertRaises(ValueError):
                installer.publish(root, "etc/should-not-exist", "test")

    def test_devops_shell_itself_is_not_replaced(self):
        text = payload_read_text(FORKY / "hooks/target/etc/skel-desktop/.profile.d/71-devops-de.sh")
        self.assertIn('  "$devops_de_shell" -i\n  devops_de_shell_status=$?', text)
        self.assertIn("/usr/local/bin/labwc-hardware-tuning devops-start ||", text)
        self.assertNotIn("$(/usr/local/bin/labwc-hardware-tuning devops-start", text)
        orchestrator = payload_read_text(FORKY / "scripts/desktop/labwc.sh")
        self.assertLess(orchestrator.index("  desktop_render_labwc_default_config\n"), orchestrator.index("  desktop_install_hardware_tuning\n"))
        self.assertLess(orchestrator.index("  desktop_install_hardware_tuning\n"), orchestrator.index("  desktop_install_user_config\n"))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = private_temp()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "intel.json"
        self.backend = FakeBackend()
        # Nonroot users can still run pure transaction tests; trusted_json's
        # real root/symlink tests above are separate and not silently weakened.
        if os.geteuid() != 0:
            self.reader = patch.object(engine, "trusted_json", lambda p: common.decode(payload_read_text(p)))
            self.reader.start()
            self.addCleanup(self.reader.stop)

    def make(self, settings):
        return engine.Engine(self.backend, self.path, simple_policy(settings))

    def test_raise_and_lower_pairs_in_correct_order_and_restore(self):
        self.backend.add("lo", "MIN", 2, 0, 10, pair="cpu", side="min")
        self.backend.add("hi", "MAX", 4, 0, 10, pair="cpu", side="max")
        settings = {"MIN": ("6",) * 4, "MAX": ("9",) * 4}
        work = self.make(settings)
        work.apply("high", settings)
        self.assertEqual(self.backend.writes[:2], [("hi", 9), ("lo", 6)])
        self.assertEqual(work.reset()["restored"], 2)
        self.assertEqual(self.backend.writes[2:], [("lo", 2), ("hi", 4)])
        self.assertEqual(json.loads(payload_read_text(self.path))["entries"], [])

    def test_snapshot_is_durable_before_the_first_write(self):
        self.backend.add("x", "X", 1)
        settings = {"X": ("3",) * 4}
        def check(_key, _new):
            snapshot = json.loads(payload_read_text(self.path))
            self.assertEqual(snapshot["entries"][0]["before"], 1)
            self.assertTrue(snapshot["entries"][0]["pending"])
        self.backend.before_write = check
        self.make(settings).apply("high", settings)

    def test_driver_error_rolls_back_earlier_writes(self):
        self.backend.add("a", "A", 1)
        self.backend.add("b", "B", 2)
        self.backend.failure = lambda key, value: key == "b" and value == 4
        settings = {"A": ("3",) * 4, "B": ("4",) * 4}
        work = self.make(settings)
        with self.assertRaises(common.TuningError):
            work.apply("high", settings)
        self.assertEqual(self.backend.values, {"a": 1, "b": 2})
        self.assertEqual(work.journal["entries"], [])

    def test_failed_recovery_keeps_write_ahead_evidence(self):
        self.backend.add("a", "A", 1)
        self.backend.add("b", "B", 2)
        self.backend.failure = lambda key, value: (key, value) in (("b", 4), ("a", 1))
        settings = {"A": ("3",) * 4, "B": ("4",) * 4}
        work = self.make(settings)
        with self.assertRaisesRegex(common.TuningError, "recovery failed"):
            work.apply("high", settings)
        disk = json.loads(payload_read_text(self.path))
        self.assertEqual([e["id"] for e in disk["entries"]], ["a"])
        self.assertEqual(disk["entries"][0]["before"], 1)
        self.backend.failure = None
        recovered = engine.Engine(self.backend, self.path)
        recovered.reset()
        self.assertEqual(self.backend.values["a"], 1)

    def test_interrupted_pending_transaction_recovers(self):
        self.backend.add("x", "X", 7)
        common.atomic_json(self.path, {"version": 1, "profile": "high", "entries": [{"id": "x", "before": 1, "last": None, "pending": True, "requested": 7}]})
        work = engine.Engine(self.backend, self.path)
        work.reset()
        self.assertEqual(self.backend.values["x"], 1)

    def test_external_change_is_preserved_not_fought(self):
        self.backend.add("a", "A", 1)
        self.backend.add("b", "B", 2)
        settings = {"A": ("3",) * 4, "B": ("4",) * 4}
        work = self.make(settings)
        work.apply("high", settings)
        self.backend.values["b"] = 8
        self.assertTrue(work.health()["conflicts"])
        result = work.reset()
        self.assertEqual(result["external_values_preserved"], ["b"])
        self.assertEqual(self.backend.values, {"a": 1, "b": 8})

    def test_external_epp_change_does_not_restore_sibling_governor(self):
        gov = "sys/policy0/scaling_governor"
        epp = "sys/policy0/energy_performance_preference"
        self.backend.add(gov, "CPU_GOVERNOR", "powersave", choices=("powersave", "performance"))
        self.backend.add(epp, "CPU_EPP", "balance_power", choices=("balance_power", "performance", "power"))
        settings = {"CPU_GOVERNOR": ("performance",) * 4, "CPU_EPP": ("performance",) * 4}
        work = self.make(settings)
        work.apply("high", settings)
        self.backend.values[epp] = "power"
        result = work.reset()
        self.assertEqual(set(result["external_values_preserved"]), {gov, epp})
        self.assertEqual(self.backend.values[gov], "performance")
        self.assertEqual(self.backend.values[epp], "power")

    def test_next_keep_profile_restores_previous_profile_controls(self):
        self.backend.add("x", "X", 1)
        settings = {"X": ("9", "8", "keep", "keep")}
        work = self.make(settings)
        work.apply("high", settings)
        work.apply("balanced", settings)
        self.assertEqual(self.backend.values["x"], 1)
        self.assertEqual(work.journal["entries"], [])

    def test_read_only_report_has_current_bounds_and_all_profiles(self):
        self.backend.add("x", "X", 1, 0, 20)
        settings = {"X": ("9", "8", "keep", "1")}
        result = self.make(settings).report(settings)
        self.assertTrue(result["read_only"])
        self.assertFalse(payload_source_exists(self.path))
        self.assertEqual(self.backend.writes, [])
        control = result["controls"][0]
        self.assertEqual((control["current"], control["minimum"], control["maximum"]), (1, 0, 20))
        self.assertEqual(set(control["profiles"]), set(common.PROFILES))
        self.assertEqual(control["profiles"]["balanced"]["resolved"], None)

    def test_thermal_interlock_rejects_before_any_write(self):
        self.backend.add("x", "X", 1)
        self.backend.temperature_value = 90
        settings = {"X": ("9",) * 4}
        with self.assertRaisesRegex(common.TuningError, "thermal"):
            self.make(settings).apply("high", settings)
        self.assertEqual(self.backend.writes, [])

    def test_positive_offset_requires_opt_in_and_temperature(self):
        self.backend.add("x", "X", 0, -200, 200, overclock=True)
        settings = {"X": ("100",) * 4}
        work = self.make(settings)
        with self.assertRaisesRegex(common.TuningError, "allow_overclock"):
            work.apply("high", settings)
        work.policy["allow_overclock"] = True
        self.backend.temperature_value = None
        with self.assertRaisesRegex(common.TuningError, "temperature sensor"):
            work.apply("high", settings)
        self.backend.temperature_value = 35
        work.apply("high", settings)
        self.assertEqual(self.backend.values["x"], 100)

    def test_power_increase_gate_and_advertised_bounds(self):
        knob = self.backend.add("x", "X", 25, 10, 50, power_default=25)
        policy = simple_policy({"X": ("keep",) * 4})
        with self.assertRaisesRegex(common.TuningError, "allow_power_increase"):
            knob.resolve("40", policy)
        policy["allow_power_increase"] = True
        self.assertEqual(knob.resolve("40", policy), 40)
        with self.assertRaises(common.TuningError):
            knob.resolve("51", policy)

    def test_unknown_bounds_are_not_fabricated(self):
        knob = self.backend.add("x", "X", 10, None, 30)
        policy = simple_policy({"X": ("keep",) * 4})
        with self.assertRaisesRegex(common.TuningError, "advertise"):
            knob.resolve("20", policy)
        self.assertIsNone(knob.resolve("keep", policy))

    def test_unknown_override_fails_without_path_access(self):
        self.backend.add("x", "X", 1)
        settings = {"X": ("keep",) * 4}
        work = self.make(settings)
        work.policy["profiles"]["high"]["overrides"]["/etc/shadow"] = "100"
        with self.assertRaisesRegex(common.TuningError, "unknown/unavailable"):
            work.apply("high", settings)
        self.assertEqual(self.backend.writes, [])

    def test_default_optional_missing_skipped_but_explicit_change_fails(self):
        settings = {"X": ("10",) * 4}
        work = self.make(settings)
        self.assertTrue(work.apply("high", settings)["skipped"])
        work.policy["profiles"]["high"]["knobs"]["X"] = "11"
        with self.assertRaisesRegex(common.TuningError, "explicit request"):
            work.apply("high", settings)

    def test_inverted_pair_rejected_before_writes(self):
        self.backend.add("lo", "MIN", 2, 0, 10, pair="pair", side="min")
        self.backend.add("hi", "MAX", 8, 0, 10, pair="pair", side="max")
        settings = {"MIN": ("9",) * 4, "MAX": ("4",) * 4}
        with self.assertRaisesRegex(common.TuningError, "inverted"):
            self.make(settings).apply("high", settings)
        self.assertEqual(self.backend.writes, [])

    def test_cannot_claim_unknown_locked_clock_range_is_measured(self):
        knob = self.backend.add("x", "X", "unlocked", 100, 1000, unit="MHz-pair", restorable=False)
        policy = simple_policy({"X": ("100,900",) * 4})
        with self.assertRaisesRegex(common.TuningError, "exclusive_clock_control"):
            knob.resolve("100,900", policy)
        result = knob.report(policy["profiles"], policy)
        self.assertIsNone(result["current"])
        self.assertIn("not queryable", result["read_error"])
        policy["exclusive_clock_control"] = True
        self.assertEqual(knob.resolve("100,900", policy), [100, 900])

    def test_recovery_without_journal_does_not_load_a_driver(self):
        with patch.object(engine, "STATE", Path(self.temporary.name)), patch.object(engine.importlib, "import_module") as load:
            self.assertEqual(engine.execute("nvidia", "reset"), {"restored": 0})
            load.assert_not_called()


class IntelInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file("proc/cpuinfo", "vendor_id : GenuineIntel\nmodel name : Intel fixture\n")

    def file(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value) + "\n")

    def test_cpufreq_pstate_and_i915_units_and_bounds(self):
        base = "sys/devices/system/cpu/cpufreq/policy0/"
        for key, value in {"scaling_driver": "intel_pstate", "scaling_available_governors": "performance powersave",
                           "scaling_governor": "powersave", "cpuinfo_min_freq": 400000, "cpuinfo_max_freq": 4100000,
                           "scaling_min_freq": 400000, "scaling_max_freq": 4100000,
                           "energy_performance_available_preferences": "performance balance_performance balance_power power",
                           "energy_performance_preference": "balance_power"}.items():
            self.file(base + key, value)
        for key, value in {"min_perf_pct": 9, "max_perf_pct": 100, "no_turbo": 0, "hwp_dynamic_boost": 0}.items():
            self.file("sys/devices/system/cpu/intel_pstate/" + key, value)
        self.file("sys/class/drm/card0/device/vendor", "0x8086")
        for key, value in {"min_freq_mhz": 100, "max_freq_mhz": 1200, "boost_freq_mhz": 1200,
                           "RPn_freq_mhz": 100, "RP0_freq_mhz": 1200, "RP1_freq_mhz": 600}.items():
            self.file("sys/class/drm/card0/gt/gt0/rps_" + key, value)
        hardware = intel.Backend(self.root)
        found = {k.setting: k for k in hardware.knobs.values()}
        self.assertEqual((found["CPU_MAX_FREQ_KHZ"].minimum, found["CPU_MAX_FREQ_KHZ"].maximum), (400000, 4100000))
        self.assertEqual(found["CPU_GOVERNOR"].symbols["adaptive"], "powersave")
        self.assertEqual(found["GPU_MAX_FREQ_MHZ"].symbols["efficient"], 600)
        self.assertEqual(found["GPU_MAX_FREQ_MHZ"].maximum, 1200)

    def test_non_intel_rejected_at_runtime_too(self):
        self.file("proc/cpuinfo", "vendor_id : AuthenticAMD")
        with self.assertRaisesRegex(common.TuningError, "Intel CPU not detected"):
            intel.Backend(self.root)

    def test_optional_rapl_bounds_remain_unknown(self):
        base = "sys/class/powercap/intel-rapl:0/"
        for key, value in {"name": "package-0", "constraint_0_name": "long_term", "constraint_0_power_limit_uw": 15000000,
                           "constraint_0_max_power_uw": 28000000, "constraint_0_time_window_us": 28000000}.items():
            self.file(base + key, value)
        hardware = intel.Backend(self.root)
        power = next(k for k in hardware.knobs.values() if k.setting == "RAPL_PL1_POWER_UW")
        self.assertIsNone(power.minimum)
        self.assertEqual(power.maximum, 28000000)
        self.assertEqual(power.read(), 15000000)

    def test_sysfs_escape_rejected(self):
        self.file("sys/placeholder", 10)
        outside = self.root / "untrusted"
        outside.write_text("10")
        (self.root / "sys/link").symlink_to(outside)
        hardware = intel.Backend(self.root)
        with self.assertRaisesRegex(common.TuningError, "escaped"):
            hardware.attribute(self.root / "sys/link", "X", 0, 10)


class FakeNVML:
    def __init__(self, architecture=4):
        self.architecture, self.calls = architecture, []
        self.offsets = {(0, 0): 0, (2, 0): 0}
        self.power_value, self.application = 25000, (1000, 600)

    def has(self, name):
        return name in {"nvmlDeviceSetPowerManagementLimit", "nvmlDeviceSetPersistenceMode", "nvmlDeviceGetClockOffsets",
                        "nvmlDeviceSetClockOffsets", "nvmlDeviceSetApplicationsClocks", "nvmlDeviceResetApplicationsClocks",
                        "nvmlDeviceSetGpuLockedClocks", "nvmlDeviceResetGpuLockedClocks",
                        "nvmlDeviceSetMemoryLockedClocks", "nvmlDeviceResetMemoryLockedClocks"}

    def call(self, name, types, args):
        self.calls.append((name, types, args))
        if name == "nvmlDeviceGetCount_v2":
            args[0]._obj.value = 1
        elif name == "nvmlDeviceGetHandleByIndex_v2":
            args[1]._obj.value = 1
        elif name in {"nvmlDeviceGetClockOffsets", "nvmlDeviceSetClockOffsets"}:
            info = args[1]._obj
            key = (info.type, info.pstate)
            if key not in self.offsets:
                raise common.TuningError("unsupported P-state")
            if name == "nvmlDeviceGetClockOffsets":
                info.clockOffsetMHz = self.offsets[key]
                info.minClockOffsetMHz, info.maxClockOffsetMHz = -200, 200
            else:
                self.offsets[key] = info.clockOffsetMHz
        elif name == "nvmlDeviceSetPowerManagementLimit":
            self.power_value = args[1]
        elif name == "nvmlDeviceSetApplicationsClocks":
            self.application = tuple(args[1:])
        elif name == "nvmlDeviceResetApplicationsClocks":
            self.application = (1000, 600)
        elif name in {"nvmlShutdown", "nvmlDeviceSetPersistenceMode", "nvmlDeviceSetGpuLockedClocks", "nvmlDeviceResetGpuLockedClocks",
                      "nvmlDeviceSetMemoryLockedClocks", "nvmlDeviceResetMemoryLockedClocks"}:
            pass
        else:
            raise common.TuningError("unsupported symbol: " + name)

    def scalar(self, name, handle, *extra, signed=False):
        values = {"nvmlDeviceGetArchitecture": self.architecture, "nvmlDeviceGetTemperature": 35,
                  "nvmlDeviceGetPowerManagementDefaultLimit": 25000, "nvmlDeviceGetPowerManagementLimit": self.power_value,
                  "nvmlDeviceGetPersistenceMode": 0, "nvmlDeviceGetClockInfo": 600, "nvmlDeviceGetMaxClockInfo": 1200,
                  "nvmlDeviceGetPowerUsage": 5000, "nvmlDeviceGetPerformanceState": 8, "nvmlDeviceGetFanSpeed": 0}
        if name in {"nvmlDeviceGetApplicationsClock", "nvmlDeviceGetDefaultApplicationsClock"}:
            value = (1000, 600) if name == "nvmlDeviceGetDefaultApplicationsClock" else self.application
            return value[0 if extra == (2,) else 1]
        if name not in values:
            raise common.TuningError("unsupported getter: " + name)
        return values[name]

    def bounds(self, name, handle, *extra, signed=False):
        if name == "nvmlDeviceGetPowerManagementLimitConstraints":
            return 10000, 35000
        raise common.TuningError("unsupported bounds")

    def clocks(self, name, handle, *extra):
        return [1000, 2000] if name == "nvmlDeviceGetSupportedMemoryClocks" else [600, 900, 1200]

    def text(self, name, handle):
        return "GPU-00000000-1111-2222-3333-444444444444" if name == "nvmlDeviceGetUUID" else "Quadro P520 fixture"


class NvidiaTests(unittest.TestCase):
    def test_clock_offset_struct_matches_versioned_24_byte_abi(self):
        self.assertEqual(ctypes.sizeof(nvidia.ClockOffset), 24)
        self.assertEqual(nvidia.ClockOffset.clockOffsetMHz.offset, 12)
        self.assertEqual(nvidia.ClockOffset.minClockOffsetMHz.offset, 16)
        value = nvidia.ClockOffset(24 | (1 << 24), 2, 0, -100, -200, 200)
        self.assertEqual(value.clockOffsetMHz, -100)

    def test_pascal_p520_does_not_offer_volta_ampere_lock_apis(self):
        api = FakeNVML(4)
        hardware = nvidia.Backend(api)
        settings = {k.setting for k in hardware.knobs.values()}
        self.assertNotIn("GPU_LOCK_MHZ", settings)
        self.assertNotIn("MEMORY_LOCK_MHZ", settings)
        self.assertIn("GPU_OFFSET_MHZ", settings)
        self.assertIn("APPLICATION_CLOCKS_MHZ", settings)
        self.assertFalse(any(name.startswith("nvmlDeviceSet") for name, _, _ in api.calls))

    def test_ampere_locks_are_exclusive_and_never_report_fake_current_values(self):
        hardware = nvidia.Backend(FakeNVML(7))
        locks = [k for k in hardware.knobs.values() if k.setting in {"GPU_LOCK_MHZ", "MEMORY_LOCK_MHZ"}]
        self.assertEqual(len(locks), 2)
        policy = installer.policy(environment(), "nvidia", nvidia.SETTINGS)
        for knob in locks:
            self.assertIsNone(knob.report(policy["profiles"], policy)["current"])
            with self.assertRaisesRegex(common.TuningError, "exclusive"):
                knob.resolve(f"{knob.minimum},{knob.maximum}", policy)

    def test_application_clocks_reset_uses_driver_reset_for_default_baseline(self):
        api = FakeNVML(4)
        hardware = nvidia.Backend(api)
        knob = next(k for k in hardware.knobs.values() if k.setting == "APPLICATION_CLOCKS_MHZ")
        before = knob.read()
        knob.write("2000,1200")
        self.assertEqual(knob.read(), "2000,1200")
        knob.restore_value(before)
        self.assertEqual(knob.read(), "1000,600")
        self.assertEqual(api.calls[-1][0], "nvmlDeviceResetApplicationsClocks")

    def test_memory_graphics_pair_must_be_in_driver_table(self):
        hardware = nvidia.Backend(FakeNVML())
        knob = next(k for k in hardware.knobs.values() if k.setting == "APPLICATION_CLOCKS_MHZ")
        policy = installer.policy(environment(), "nvidia", nvidia.SETTINGS)
        with self.assertRaises(common.TuningError):
            knob.resolve("9999,9999", policy)

    def test_signed_per_pstate_offset_preserved(self):
        api = FakeNVML()
        hardware = nvidia.Backend(api)
        knob = next(k for k in hardware.knobs.values() if k.setting == "GPU_OFFSET_MHZ")
        policy = installer.policy(environment(), "nvidia", nvidia.SETTINGS)
        self.assertEqual(knob.resolve("-100", policy), -100)
        knob.write(-100)
        self.assertEqual(knob.read(), -100)
        with self.assertRaises(common.TuningError):
            knob.resolve("201", dict(policy, allow_overclock=True))


class SelectionTests(unittest.TestCase):
    def test_manual_precedence_reset_and_automatic_preserved(self):
        selection = broker.Selection(["intel", "nvidia"])
        selection.automatic = True
        selection.change_lease("intel", "performance", 1)
        selection.manual["intel"] = "silent"
        self.assertEqual(selection.desired("intel", True, "balanced"), "silent")
        selection.manual["intel"] = None
        self.assertTrue(selection.automatic)
        self.assertEqual(selection.desired("intel", True, "balanced"), "performance")
        self.assertEqual(selection.desired("nvidia", True, "balanced"), "balanced")

    def test_two_terminals_and_two_browsers_have_independent_lifetimes(self):
        selection = broker.Selection(["intel"])
        selection.automatic = True
        for _ in range(2):
            selection.change_lease("intel", "high", 1)
            selection.change_lease("intel", "performance", 1)
        selection.change_lease("intel", "performance", -1)
        self.assertEqual(selection.desired("intel", True, "balanced"), "performance")
        selection.change_lease("intel", "performance", -1)
        self.assertEqual(selection.desired("intel", True, "balanced"), "high")
        selection.change_lease("intel", "high", -1)
        self.assertEqual(selection.desired("intel", True, "balanced"), "high")
        selection.change_lease("intel", "high", -1)
        self.assertEqual(selection.desired("intel", True, "balanced"), "balanced")

    def test_off_inactive_pause_and_fault_all_prevent_tuning(self):
        selection = broker.Selection(["intel"])
        selection.change_lease("intel", "performance", 1)
        self.assertIsNone(selection.desired("intel", True, "balanced"))
        selection.automatic = True
        self.assertIsNone(selection.desired("intel", False, "balanced"))
        selection.paused = True
        self.assertIsNone(selection.desired("intel", True, "balanced"))
        selection.paused = False
        selection.faults["intel"] = "thermal"
        self.assertIsNone(selection.desired("intel", True, "balanced"))

    def test_underflow_is_rejected(self):
        with self.assertRaises(common.TuningError):
            broker.Selection(["intel"]).change_lease("intel", "high", -1)


class FakeSeat:
    present = True
    def active(self):
        return self.present


class FakeBroker(broker.Broker):
    def __init__(self):
        super().__init__({"version": 1, "uid": 1000, "vendors": ["intel", "nvidia"], "poll_seconds": 5,
                          "idle_ac": "balanced", "idle_battery": "silent"}, FakeSeat())
        self.calls, self.fail, self.hot = [], None, False
        self.boot_enabled = False
        self.policy_calls = []
        self.claimed = False
        self.ppd_file, self.ppd_active = "enabled", "active"
        self.marker_active = "inactive"

    def save(self):
        pass

    async def policy(self, action):
        # No live systemd calls in broker fixtures. Policy transitions have
        # independent real-protocol and filesystem regression coverage.
        self.policy_calls.append(action)
        if action in {"prepare-runtime", "prepare-boot"}:
            self.claimed, self.ppd_active = True, "inactive"
            if action == "prepare-boot":
                self.boot_enabled, self.ppd_file = True, "masked"
            elif self.ppd_file != "masked":
                self.ppd_file = "masked-runtime"
        elif action in {"stop", "disable", "recover"}:
            self.claimed, self.ppd_active, self.marker_active = False, "active", "inactive"
            if action == "disable":
                self.boot_enabled = False
            self.ppd_file = "disabled" if self.boot_enabled else "enabled"
        elif action == "activate" and self.boot_enabled:
            self.marker_active = "active"
        self.policy_state = {
            "claimed": self.claimed,
            "ppd": {"load": "loaded", "active": self.ppd_active, "file": self.ppd_file},
            "autostart_unit": {"load": "loaded", "active": self.marker_active,
                               "file": "enabled" if self.boot_enabled else "disabled"}}
        return self.policy_state

    async def worker(self, vendor, action, profile=None):
        self.calls.append((vendor, action, profile))
        if (vendor, action) == self.fail:
            raise common.TuningError("injected worker error")
        if action == "health":
            return {"conflicts": ["thermal"] if self.hot else []}
        if action == "apply":
            return {"controls": {"fixture": profile}}
        return {"restored": 1}


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.work = FakeBroker()
        self.ac = patch.object(broker, "on_ac", return_value=True)
        self.ac.start()
        self.addCleanup(self.ac.stop)

    async def test_start_stop_manual_reset_and_full_reset(self):
        await self.work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)
        self.assertEqual(self.work.applied, {"intel": "balanced", "nvidia": "balanced"})
        self.work.selection.change_lease("intel", "high", 1)
        await self.work.reconcile()
        await self.work.action({"action": "manual", "vendor": "intel", "profile": "silent"}, 1000)
        self.assertEqual(self.work.applied["intel"], "silent")
        await self.work.action({"action": "profiles-reset"}, 1000)
        self.assertEqual(self.work.applied["intel"], "high")
        self.assertTrue(self.work.selection.automatic)
        await self.work.action({"action": "boot-enable", "confirm_policy_owner": True}, 1000)
        self.assertTrue(self.work.boot_enabled)
        await self.work.action({"action": "reset"}, 1000)
        self.assertEqual(self.work.applied, {"intel": None, "nvidia": None})
        self.assertFalse(self.work.selection.automatic)
        self.assertFalse(self.work.boot_enabled)
        self.assertEqual(self.work.selection.leases[("intel", "high")], 1)

    async def test_stop_auto_releases_manual_profiles_before_ppd_handback(self):
        await self.work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)
        await self.work.action({"action": "manual", "vendor": "intel", "profile": "high", "confirm_policy_owner": True}, 1000)
        await self.work.action({"action": "auto-stop"}, 1000)
        self.assertEqual(self.work.applied, {"intel": None, "nvidia": None})
        self.assertEqual(self.work.selection.manual, {"intel": None, "nvidia": None})
        self.assertEqual(self.work.ppd_active, "active")

    async def test_pause_restores_and_resume_reapplies(self):
        await self.work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)
        await self.work.action({"action": "pause"}, 0)
        self.assertEqual(self.work.applied, {"intel": None, "nvidia": None})
        await self.work.action({"action": "resume"}, 0)
        self.assertEqual(self.work.applied, {"intel": "balanced", "nvidia": "balanced"})
        with self.assertRaises(common.TuningError):
            await self.work.action({"action": "pause"}, 1000)

    async def test_losing_active_seat_restores_and_clears_manual(self):
        await self.work.action({"action": "manual", "vendor": "intel", "profile": "high", "confirm_policy_owner": True}, 1000)
        self.work.seat.present = False
        await self.work.reconcile()
        self.assertEqual(self.work.applied["intel"], None)
        self.assertEqual(self.work.selection.manual["intel"], None)
        with self.assertRaises(common.TuningError):
            await self.work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)

    async def test_worker_failure_latches_only_affected_vendor(self):
        self.work.fail = ("nvidia", "apply")
        await self.work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)
        self.assertEqual(self.work.applied["intel"], "balanced")
        self.assertEqual(self.work.applied["nvidia"], None)
        self.assertIn("nvidia", self.work.selection.faults)
        calls = len(self.work.calls)
        await self.work.reconcile()
        self.assertEqual(len(self.work.calls), calls)

    async def test_thermal_health_restores_and_does_not_thrash(self):
        await self.work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)
        self.work.hot = True
        await self.work.reconcile(health=True)
        self.assertTrue(self.work.selection.faults)
        self.assertEqual(self.work.applied, {"intel": None, "nvidia": None})
        calls = len(self.work.calls)
        await self.work.reconcile(health=True)
        self.assertEqual(len(self.work.calls), calls)

    async def test_same_profile_explicit_start_reloads_configuration(self):
        await self.work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)
        self.work.calls.clear()
        await self.work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)
        self.assertIn(("intel", "reset", None), self.work.calls)
        self.assertIn(("intel", "apply", "balanced"), self.work.calls)

    async def test_request_schema_and_rate_limit(self):
        bad = [{"action": "manual", "vendor": "intel", "profile": "high", "path": "/sys/evil"},
               {"action": "shell", "command": "id"}, {"action": "manual", "vendor": "nvidia;id", "profile": "high"}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(common.TuningError):
                self.work.validate_request(value)
        self.work.rate_limit(1000, "report")
        with self.assertRaisesRegex(common.TuningError, "30 seconds"):
            self.work.rate_limit(1000, "report")
        self.work.tokens = 0
        with self.assertRaisesRegex(common.TuningError, "rate limit"):
            self.work.rate_limit(1000, "status")

    async def test_real_unix_transport_rejects_extra_privileged_fields(self):
        with tempfile.TemporaryDirectory(prefix="hardware-tuning-socket-") as temporary:
            path = str(Path(temporary) / "control.sock")
            server = await asyncio.start_unix_server(self.work.serve, path=path, limit=4096)
            try:
                reader, writer = await asyncio.open_unix_connection(path)
                writer.write(b'{"action":"status","command":"id"}\n')
                await writer.drain()
                reply = common.decode(await asyncio.wait_for(reader.readline(), 3))
                self.assertFalse(reply["ok"])
                self.assertIn("unexpected", reply["error"])
                writer.close()
                await writer.wait_closed()
            finally:
                server.close()
                await server.wait_closed()


class DevopsAndMenuTests(unittest.TestCase):
    def test_pidfd_ends_when_parent_process_exits(self):
        child = subprocess.Popen(payload_installed_argv(["/bin/sleep", "0.12"]))
        try:
            started = client.parent_start(child.pid)
            begin = time.monotonic()
            self.assertEqual(client.watch_parent(child.pid, started), 0)
            self.assertLess(time.monotonic() - begin, 2)
        finally:
            child.wait()

    def test_wrong_starttime_cannot_attach_to_reused_pid(self):
        child = subprocess.Popen(payload_installed_argv(["/bin/sleep", "10"]))
        try:
            started = client.parent_start(child.pid)
            begin = time.monotonic()
            self.assertEqual(client.watch_parent(child.pid, str(int(started) + 1)), 0)
            self.assertLess(time.monotonic() - begin, 1)
        finally:
            child.terminate()
            child.wait()

    def test_devops_launch_is_a_unique_sidecar_not_a_shell_replacement(self):
        with patch.object(client.os, "getppid", return_value=1234), patch.object(client, "parent_start", return_value="4567"), \
             patch.object(client.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            client.devops_start()
            first = run.call_args.args[0]
            client.devops_start()
            second = run.call_args.args[0]
        self.assertNotEqual(next(v for v in first if v.startswith("--unit=")), next(v for v in second if v.startswith("--unit=")))
        self.assertEqual(first[-4:], [client.EXECUTABLE, "watch-parent", "1234", "4567"])
        self.assertNotIn("--scope", first)
        self.assertIn("--property=PartOf=labwc-session.target", first)

    def test_fuzzel_cancellation_and_unlisted_input_do_nothing(self):
        for code, text in ((1, ""), (0, "not a listed action\n")):
            with patch.object(client.subprocess, "run", return_value=subprocess.CompletedProcess([], code, text)):
                self.assertIsNone(client.choose(["allowed"], "prompt"))

    def test_menu_includes_only_installed_vendor(self):
        choices = []
        def choose(entries, prompt):
            choices.append(list(entries))
            return entries[0] if len(choices) == 1 else None
        with patch.object(client, "request", return_value={"vendors": ["intel"]}), patch.object(client, "choose", side_effect=choose):
            self.assertEqual(client.menu(), 0)
        self.assertEqual(choices[0][0], "Set Single Tuning Profile")
        self.assertEqual(choices[1][0], "Reset Profiles [All]")
        self.assertIn("Set Performance Profile [Intel]", choices[1])
        self.assertFalse(any("Nvidia" in entry for entry in choices[1]))

    def test_both_vendors_appear_without_duplicate_reset(self):
        choices = []
        def choose(entries, prompt):
            choices.append(list(entries))
            return entries[0] if len(choices) == 1 else None
        with patch.object(client, "request", return_value={"vendors": ["intel", "nvidia"]}), patch.object(client, "choose", side_effect=choose):
            client.menu()
        self.assertEqual(len(choices[1]), 9)
        self.assertIn("Set Silent Profile [Nvidia]", choices[1])



class ReviewHardeningTests(unittest.TestCase):
    def test_root_apparmor_does_not_inherit_shell_or_environment_exec(self):
        policy = payload_read_text(FORKY / "hooks/target/etc/apparmor.d/hardware-tuning")
        self.assertNotIn("#include <abstractions/wrapper-python>", policy)
        self.assertNotIn("#include <abstractions/wrapper-base>", policy)
        self.assertNotIn("/usr/bin/env rix", policy)
        source = payload_read_text(FORKY / "scripts/desktop/hardware-tuning-config.py")
        self.assertNotIn("AppArmorProfile=hardware-tuning-broker", source)
        self.assertIn("ExecStopPost=/usr/local/libexec/hardware-tuning-worker recover-all", payload_read_text(FORKY / "hooks/target/etc/systemd/system/hardware-tuning.service.tmpl"))

    def test_application_clock_getter_failure_does_not_publish_unrestorable_knob(self):
        api = FakeNVML()
        scalar = api.scalar
        def query(name, *args, **kwargs):
            if name == "nvmlDeviceGetDefaultApplicationsClock":
                raise common.TuningError("unsupported default getter")
            return scalar(name, *args, **kwargs)
        api.scalar = query
        hardware = nvidia.Backend(api)
        self.assertNotIn("APPLICATION_CLOCKS_MHZ", {k.setting for k in hardware.knobs.values()})

    def test_application_clocks_require_resetter(self):
        api = FakeNVML()
        has = api.has
        api.has = lambda name: name != "nvmlDeviceResetApplicationsClocks" and has(name)
        hardware = nvidia.Backend(api)
        self.assertNotIn("APPLICATION_CLOCKS_MHZ", {k.setting for k in hardware.knobs.values()})

    def test_verified_bounds_need_explicit_acknowledgement(self):
        policy = simple_policy(intel.SETTINGS)
        policy["verified_bounds"] = {"RAPL_PL1_POWER_UW": {"minimum": 1000000, "maximum": 28000000}}
        with self.assertRaisesRegex(common.TuningError, "acknowledgement"):
            common.validate_policy(policy, intel.SETTINGS)
        policy["allow_verified_bounds"] = True
        self.assertIs(common.validate_policy(policy, intel.SETTINGS), policy)

    def test_verified_bounds_cannot_target_non_rapl_controls(self):
        policy = simple_policy(intel.SETTINGS)
        policy.update(allow_verified_bounds=True, verified_bounds={"CPU_MAX_FREQ_KHZ": {"minimum": 1, "maximum": 999999999}})
        with self.assertRaises(common.TuningError):
            common.validate_policy(policy, intel.SETTINGS)

    def test_verified_bounds_reject_bad_types_and_inverted_ranges(self):
        for bounds in ({"minimum": True, "maximum": 10}, {"minimum": 20, "maximum": 10}, {"minimum": 0, "maximum": 10}):
            policy = simple_policy(intel.SETTINGS)
            policy.update(allow_verified_bounds=True, verified_bounds={"RAPL_PL1_POWER_UW": bounds})
            with self.subTest(bounds=bounds), self.assertRaises(common.TuningError):
                common.validate_policy(policy, intel.SETTINGS)

    def test_verified_bounds_fill_missing_but_cannot_widen_hardware_limits(self):
        knob = common.Knob("fixture", "RAPL_PL1_POWER_UW", lambda: 15000000, lambda v: None,
                           None, 28000000, verified_bounds_allowed=True)
        policy = simple_policy(intel.SETTINGS)
        policy.update(allow_verified_bounds=True, verified_bounds={"RAPL_PL1_POWER_UW": {"minimum": 1000000, "maximum": 99000000}})
        self.assertEqual(knob.resolve("25000000", policy), 25000000)
        self.assertEqual(knob.resolve("max", policy), 28000000)
        with self.assertRaises(common.TuningError):
            knob.resolve("29000000", policy)
        report = knob.report(policy["profiles"], policy)
        self.assertIsNone(report["minimum"])
        self.assertEqual(report["effective_minimum"], 1000000)
        self.assertIn("administrator-verified", report["bounds_source"])

    def test_verified_bounds_environment_is_complete_and_off_by_default(self):
        env = environment()
        policy = installer.policy(env, "intel", intel.SETTINGS)
        self.assertFalse(policy["allow_verified_bounds"])
        self.assertEqual(policy["verified_bounds"], {})
        prefix = installer.PREFIXES["intel"]
        env[prefix + "RAPL_PL1_POWER_UW_VERIFIED_MIN"] = "1000000"
        with self.assertRaises(ValueError):
            installer.policy(env, "intel", intel.SETTINGS)
        env[prefix + "RAPL_PL1_POWER_UW_VERIFIED_MAX"] = "28000000"
        with self.assertRaises(common.TuningError):
            installer.policy(env, "intel", intel.SETTINGS)
        env[prefix + "ALLOW_VERIFIED_BOUNDS"] = "true"
        self.assertEqual(installer.policy(env, "intel", intel.SETTINGS)["verified_bounds"]["RAPL_PL1_POWER_UW"]["maximum"], 28000000)

    def test_out_of_policy_driver_readback_rolls_back(self):
        with private_temp() as temporary:
            hardware = FakeBackend()
            knob = hardware.add("power", "POWER_LIMIT_MW", 25, 10, 35, power_default=25)
            write = knob.write
            knob.write = lambda value: write(30 if value == 20 else value)
            settings = {"POWER_LIMIT_MW": ("20",) * 4}
            work = engine.Engine(hardware, Path(temporary) / "journal.json", simple_policy(settings))
            with self.assertRaisesRegex(common.TuningError, "power limit"):
                work.apply("high", settings)
            self.assertEqual(hardware.values["power"], 25)
            self.assertEqual(work.journal["entries"], [])

    def test_temperature_disappearance_while_overclocking_trips_interlock(self):
        with private_temp() as temporary:
            hardware = FakeBackend()
            hardware.add("offset", "GPU_OFFSET_MHZ", 0, -200, 200, overclock=True)
            settings = {"GPU_OFFSET_MHZ": ("10",) * 4}
            policy = simple_policy(settings); policy["allow_overclock"] = True
            work = engine.Engine(hardware, Path(temporary) / "journal.json", policy)
            work.apply("high", settings)
            hardware.temperature_value = None
            self.assertIn("thermal sensor disappeared", work.health()["conflicts"][0])
            work.reset()
            self.assertEqual(hardware.values["offset"], 0)

    def test_cpu_external_change_yields_global_and_policy_knobs_together(self):
        with private_temp() as temporary:
            hardware = FakeBackend()
            hardware.add("cpu/intel_pstate/no_turbo", "CPU_NO_TURBO", 0, 0, 1)
            hardware.add("cpu/cpufreq/policy0/energy_performance_preference", "CPU_EPP", "balance_power", choices=("performance", "balance_power", "power"))
            settings = {"CPU_NO_TURBO": ("1",) * 4, "CPU_EPP": ("performance",) * 4}
            work = engine.Engine(hardware, Path(temporary) / "journal.json", simple_policy(settings))
            work.apply("high", settings)
            hardware.values["cpu/cpufreq/policy0/energy_performance_preference"] = "power"
            result = work.reset()
            self.assertEqual(len(result["external_values_preserved"]), 2)
            self.assertEqual(hardware.values["cpu/intel_pstate/no_turbo"], 1)

    def test_joint_preflight_reports_inverted_pair_without_writing(self):
        with private_temp() as temporary:
            hardware = FakeBackend()
            hardware.add("lo", "LO", 2, 0, 10, pair="pair", side="min")
            hardware.add("hi", "HI", 4, 0, 10, pair="pair", side="max")
            settings = {"LO": ("8",) * 4, "HI": ("3",) * 4}
            work = engine.Engine(hardware, Path(temporary) / "journal.json", simple_policy(settings))
            report = work.report(settings)
            self.assertFalse(report["profile_preflight"]["high"]["valid"])
            self.assertEqual(hardware.writes, [])


class PeerCredentialTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.geteuid() == 0, "requires root to create real foreign-UID peers")
    async def test_real_foreign_uid_rejected_and_authorized_lease_released_on_eof(self):
        work = FakeBroker()
        with tempfile.TemporaryDirectory(prefix="tuning-peer-test-") as temporary:
            directory = Path(temporary); directory.chmod(0o755)
            path = directory / "control.sock"
            server = await asyncio.start_unix_server(work.serve, path=str(path), limit=4096)
            path.chmod(0o666)  # Deliberately let the kernel peer-credential check do the test.
            try:
                for uid, action, expected in ((1001, "status", False), (1000, "lease", True)):
                    code = "import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.sendall(sys.argv[2].encode()+bytes([10])); print(s.recv(65536).decode(),end=''); s.close()"
                    message = {"action": action}
                    if action == "lease":
                        message.update(vendor="intel", profile="high")
                    def drop_identity():
                        os.setgroups([]); os.setgid(uid); os.setuid(uid)
                    process = await asyncio.create_subprocess_exec("/usr/bin/python3", "-I", "-c", code, str(path), json.dumps(message),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, preexec_fn=drop_identity)
                    out, err = await asyncio.wait_for(process.communicate(), 5)
                    self.assertEqual(process.returncode, 0, err.decode())
                    reply = common.decode(out)
                    self.assertEqual(reply["ok"], expected, reply)
                for _ in range(50):
                    if not work.connections:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(work.connections, 0)
                self.assertEqual(work.selection.leases, {})
            finally:
                server.close(); await server.wait_closed()

    async def test_automatic_profile_transition_checks_external_interference_first(self):
        work = FakeBroker()
        with patch.object(broker, "on_ac", return_value=True):
            await work.action({"action": "auto-start", "confirm_policy_owner": True}, 1000)
            work.calls.clear()
            work.hot = True
            work.selection.change_lease("intel", "performance", 1)
            await work.reconcile()
            self.assertIn("intel", work.selection.faults)
            self.assertNotIn(("intel", "apply", "performance"), work.calls)

if __name__ == "__main__":
    unittest.main()
