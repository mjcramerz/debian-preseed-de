"""Disposable-only fixtures for firmware, RPS and lease readiness contracts."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / "tools"))
_isolation_sys.path.insert(0, "/workspace/repository/tools")
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import os
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import Mock, patch

import test_hardware_tuning_20260916 as base


class PlatformDiscovery(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file("proc/cpuinfo", "vendor_id : GenuineIntel\nphysical id : 0")
        self.profile = self.file("sys/devices/platform/fixture/platform-profile-0/profile", "balanced")
        self.file("sys/devices/platform/fixture/platform-profile-0/choices", "low-power balanced performance")
        self.file("sys/devices/platform/fixture/platform-profile-0/name", "fixture")
        alias = self.root / "sys/class/platform-profile/platform-profile-0"
        alias.parent.mkdir(parents=True)
        alias.symlink_to(self.profile.parent)

    def file(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value) + "\n")
        return path

    def test_single_handler_has_exact_choices_and_requires_permission(self):
        hardware = base.intel.Backend(self.root)
        knob = next(k for k in hardware.knobs.values() if k.setting == "PLATFORM_PROFILE")
        policy = base.simple_policy(base.intel.SETTINGS)
        with self.assertRaisesRegex(base.common.TuningError, "allow_power_increase"):
            knob.resolve("performance", policy)
        policy["allow_power_increase"] = True
        self.assertEqual(knob.resolve("performance", policy), "performance")
        with self.assertRaisesRegex(base.common.TuningError, "unsupported choice"):
            knob.resolve("quiet", policy)
        self.assertEqual(self.profile.read_text(), "balanced\n")

    def test_multiple_handlers_and_custom_state_are_not_flattened(self):
        self.file("sys/class/platform-profile/platform-profile-1/name", "second")
        hardware = base.intel.Backend(self.root)
        self.assertNotIn("PLATFORM_PROFILE", {k.setting for k in hardware.knobs.values()})
        self.assertTrue(any("multiple firmware handlers" in s for s in hardware.unavailable))
        (self.root / "sys/class/platform-profile/platform-profile-1/name").unlink()
        (self.root / "sys/class/platform-profile/platform-profile-1").rmdir()
        self.profile.write_text("custom\n")
        hardware = base.intel.Backend(self.root)
        self.assertNotIn("PLATFORM_PROFILE", {k.setting for k in hardware.knobs.values()})

    def test_replaced_selector_is_rejected_before_write_and_gets_a_new_recovery_id(self):
        hardware = base.intel.Backend(self.root)
        knob = next(k for k in hardware.knobs.values() if k.setting == "PLATFORM_PROFILE")
        self.profile.rename(self.profile.with_name("previous"))
        self.profile.write_text("balanced\n")
        with self.assertRaisesRegex(base.common.TuningError, "identity changed"):
            knob.write("performance")
        self.assertEqual(self.profile.read_text(), "balanced\n")
        replacement = base.intel.Backend(self.root)
        new = next(k for k in replacement.knobs.values() if k.setting == "PLATFORM_PROFILE")
        self.assertNotEqual(new.id, knob.id)

    def test_rps_pairs_do_not_share_frequency_pair_identity(self):
        self.file("sys/class/drm/card0/device/vendor", "0x8086")
        for key, value in {"rps_RPn_freq_mhz": 100, "rps_RP0_freq_mhz": 1250,
                           "rps_RP1_freq_mhz": 400, "rps_min_freq_mhz": 100,
                           "rps_max_freq_mhz": 1250, "rps_boost_freq_mhz": 1250,
                           "rps_up_threshold_pct": 95, "rps_down_threshold_pct": 85}.items():
            self.file("sys/class/drm/card0/gt/gt0/" + key, value)
        hardware = base.intel.Backend(self.root)
        knobs = {k.setting: k for k in hardware.knobs.values()}
        up, down = knobs["GPU_RPS_UP_THRESHOLD_PCT"], knobs["GPU_RPS_DOWN_THRESHOLD_PCT"]
        self.assertEqual(up.pair, down.pair)
        self.assertNotEqual(up.pair, knobs["GPU_MIN_FREQ_MHZ"].pair)
        self.assertEqual((up.minimum, up.maximum), (1, 99))


class PlatformTransactions(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hardware = base.FakeBackend()
        self.hardware.add("sys/devices/platform/fixture/platform-profile-0/profile", "PLATFORM_PROFILE", "balanced",
                          choices=("low-power", "balanced", "performance"), unit="enum")
        self.hardware.add("cpu/epp", "CPU_EPP", "performance", choices=("power", "performance"), unit="enum")
        self.hardware.add("gpu/min", "GPU_MIN_FREQ_MHZ", 100, low=100, high=1250)
        self.settings = {"PLATFORM_PROFILE": ("performance",) * 4,
                         "CPU_EPP": ("performance",) * 4, "GPU_MIN_FREQ_MHZ": ("keep",) * 4}
        self.policy = base.simple_policy(self.settings)
        self.policy["allow_power_increase"] = True
        self.tx = base.engine.Engine(self.hardware, self.root / "journal.json", self.policy)

    def change_firmware(self, key, value):
        if key == "sys/devices/platform/fixture/platform-profile-0/profile":
            self.hardware.values["cpu/epp"] = "power"
            self.hardware.values["gpu/min"] = 200 if value == "performance" else 300

    def test_firmware_precedes_cpu_and_original_side_effect_values_are_restored(self):
        self.hardware.before_write = self.change_firmware
        baseline = dict(self.hardware.values)
        self.tx.apply("performance", self.settings)
        self.assertEqual(self.hardware.writes[0], ("sys/devices/platform/fixture/platform-profile-0/profile", "performance"))
        self.assertEqual(self.hardware.values["cpu/epp"], "performance")
        self.assertEqual(self.hardware.values["gpu/min"], 200)
        self.assertEqual({e["id"]: e["before"] for e in self.tx.journal["entries"]}, baseline)
        self.tx.reset()
        self.assertEqual(self.hardware.values, baseline)
        self.assertFalse(self.tx.journal["entries"])

    def test_failed_firmware_restore_retains_dependents_without_further_writes(self):
        self.hardware.before_write = self.change_firmware
        self.tx.apply("performance", self.settings)
        entries = {e["id"] for e in self.tx.journal["entries"]}
        self.hardware.writes.clear()
        self.hardware.failure = lambda key, value: key.endswith("/profile") and value == "balanced"
        with self.assertRaisesRegex(base.common.TuningError, "restoration incomplete"):
            self.tx.reset()
        self.assertEqual(self.hardware.writes, [("sys/devices/platform/fixture/platform-profile-0/profile", "balanced")])
        self.assertEqual({e["id"] for e in self.tx.journal["entries"]}, entries)

    def test_disappeared_firmware_control_blocks_dependent_restore(self):
        self.hardware.before_write = self.change_firmware
        self.tx.apply("performance", self.settings)
        del self.hardware.knobs["sys/devices/platform/fixture/platform-profile-0/profile"]
        self.hardware.writes.clear()
        with self.assertRaisesRegex(base.common.TuningError, "restoration incomplete"):
            self.tx.reset()
        self.assertFalse(self.hardware.writes)
        self.assertEqual(len(self.tx.journal["entries"]), 3)

    def test_external_firmware_selection_preserves_the_entire_external_state(self):
        self.hardware.before_write = self.change_firmware
        self.tx.apply("performance", self.settings)
        self.hardware.values.update({"sys/devices/platform/fixture/platform-profile-0/profile": "low-power",
                                     "cpu/epp": "power", "gpu/min": 300})
        external = dict(self.hardware.values)
        self.hardware.writes.clear()
        self.tx.reset()
        self.assertEqual(self.hardware.values, external)
        self.assertFalse(self.hardware.writes)

    def test_external_gt_change_also_yields_owned_firmware(self):
        self.hardware.before_write = self.change_firmware
        self.tx.apply("performance", self.settings)
        self.hardware.values["gpu/min"] = 400
        external = dict(self.hardware.values)
        self.hardware.writes.clear()
        self.tx.reset()
        self.assertEqual(self.hardware.values, external)
        self.assertFalse(self.hardware.writes)

    def test_dependent_restore_failure_keeps_the_complete_firmware_domain(self):
        self.hardware.before_write = self.change_firmware
        self.tx.apply("performance", self.settings)
        self.hardware.failure = lambda key, value: key == "gpu/min" and value == 100
        with self.assertRaisesRegex(base.common.TuningError, "restoration incomplete"):
            self.tx.reset()
        self.assertEqual({e["id"] for e in self.tx.journal["entries"]}, set(self.hardware.knobs))
        self.hardware.failure = None
        self.tx.reset()
        self.assertEqual(self.hardware.values["gpu/min"], 100)
        self.assertFalse(self.tx.journal["entries"])

    def test_performance_requires_thermal_coverage_before_mutation_and_during_ownership(self):
        self.hardware.temperature_value = None
        with self.assertRaisesRegex(base.common.TuningError, "readable temperature"):
            self.tx.apply("performance", self.settings)
        self.assertFalse(self.hardware.writes)
        self.hardware.temperature_value = 40
        self.tx.apply("performance", self.settings)
        self.hardware.temperature_value = None
        self.assertTrue(any("thermal sensor disappeared" in s for s in self.tx.health()["conflicts"]))

    def test_rps_hysteresis_and_restore_order(self):
        hardware = base.FakeBackend()
        hardware.add("up", "GPU_RPS_UP_THRESHOLD_PCT", 95, low=1, high=99, pair="rps", side="max")
        hardware.add("down", "GPU_RPS_DOWN_THRESHOLD_PCT", 85, low=1, high=99, pair="rps", side="min")
        settings = {"GPU_RPS_UP_THRESHOLD_PCT": ("80",) * 4,
                    "GPU_RPS_DOWN_THRESHOLD_PCT": ("60",) * 4}
        tx = base.engine.Engine(hardware, self.root / "rps.json", base.simple_policy(settings))
        tx.apply("performance", settings)
        self.assertEqual(hardware.writes, [("down", 60), ("up", 80)])
        hardware.writes.clear()
        tx.reset()
        self.assertEqual(hardware.writes, [("up", 95), ("down", 85)])
        tx.policy["profiles"]["performance"]["knobs"]["GPU_RPS_DOWN_THRESHOLD_PCT"] = "80"
        hardware.writes.clear()
        with self.assertRaisesRegex(base.common.TuningError, "below its up"):
            tx.apply("performance", settings)
        self.assertFalse(hardware.writes)


class ClockSelectionAPI(base.FakeNVML):
    """NVML fixture: setters never reach a library, device or host command."""
    def __init__(self):
        super().__init__(4)
        self.default = self.application = (3004, 1303)
        self.tables = {3004: [1518, 1531], 810: [1518, 1531], 405: [607]}
        self.attempts = []
        self.reject = lambda pair: None
        self.before_attempt = None
        self.change_on_failure = False
        self.ignore_success = False
        self.reset_failure = None

    def clocks(self, name, handle, *extra):
        return list(self.tables) if name == "nvmlDeviceGetSupportedMemoryClocks" else self.tables[extra[0]]

    def scalar(self, name, handle, *extra, signed=False):
        if name == "nvmlDeviceGetDefaultApplicationsClock":
            return self.default[0 if extra == (2,) else 1]
        return super().scalar(name, handle, *extra, signed=signed)

    def call(self, name, types, args):
        if name == "nvmlDeviceSetApplicationsClocks":
            pair = tuple(args[1:])
            self.attempts.append(pair)
            if self.before_attempt:
                self.before_attempt(pair)
            status = self.reject(pair)
            if status:
                if self.change_on_failure:
                    self.application = (810, 1518)
                raise base.nvidia.NVMLFailure(name, status)
            if self.ignore_success:
                return
        if name == "nvmlDeviceResetApplicationsClocks":
            self.calls.append((name, types, args))
            if self.reset_failure:
                raise base.nvidia.NVMLFailure(name, self.reset_failure)
            self.application = self.default
            return
        return super().call(name, types, args)


class NvidiaMaximumSelection(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sequence = 0

    def transaction(self, api):
        self.sequence += 1
        key = "GPU-00000000-1111-2222-3333-444444444444/APPLICATION_CLOCKS_MHZ"
        hardware = base.nvidia.Backend(api, wanted={key})
        self.addCleanup(hardware.close)
        settings = {"APPLICATION_CLOCKS_MHZ": ("keep",) * 4}
        policy = base.simple_policy(settings)
        policy["profiles"]["performance"]["knobs"]["APPLICATION_CLOCKS_MHZ"] = "supported-max"
        tx = base.engine.Engine(hardware, self.root / f"journal-{self.sequence}.json", policy)
        return tx, settings, key

    def test_descending_graphics_and_memory_selection_has_durable_baseline_and_exact_restore(self):
        api = ClockSelectionAPI()
        api.reject = lambda pair: 2 if pair[0] == 3004 else 3 if pair == (810, 1531) else None
        tx, settings, key = self.transaction(api)

        def journal_precedes_every_attempt(pair):
            entries = base.common.trusted_json(tx.path)["entries"]
            self.assertEqual(entries[0]["before"], "3004,1303")
            self.assertTrue(entries[0]["pending"])

        api.before_attempt = journal_precedes_every_attempt
        result = tx.apply("performance", settings)
        self.assertEqual(api.attempts, [(3004, 1531), (3004, 1518), (810, 1531), (810, 1518)])
        self.assertEqual(api.application, (810, 1518))
        self.assertEqual(result["selections"][key], {"preferred": "3004,1531", "selected": "810,1518"})
        self.assertEqual(result["controls"][key]["requested"], "810,1518")
        self.assertEqual(result["controls"][key]["readback"], "810,1518")
        tx.reset()
        self.assertEqual(api.application, api.default)
        self.assertFalse(tx.journal["entries"])

    def test_lower_graphics_at_highest_memory_precedes_lower_memory(self):
        api = ClockSelectionAPI()
        api.reject = lambda pair: 2 if pair == (3004, 1531) else None
        tx, settings, key = self.transaction(api)
        tx.apply("performance", settings)
        self.assertEqual(api.attempts, [(3004, 1531), (3004, 1518)])
        self.assertEqual(api.application, (3004, 1518))

    def test_already_working_lower_pair_does_not_need_another_setter(self):
        api = ClockSelectionAPI()
        api.default = api.application = (810, 1531)
        api.reject = lambda pair: 3
        tx, settings, key = self.transaction(api)
        result = tx.apply("performance", settings)
        self.assertEqual(api.attempts, [(3004, 1531), (3004, 1518)])
        self.assertEqual(result["selections"][key]["selected"], "810,1531")
        self.assertEqual(result["changed"], 0)
        self.assertFalse(tx.journal["entries"])

    def test_all_unsupported_pairs_skip_conditional_request(self):
        api = ClockSelectionAPI()
        api.reject = lambda pair: 3
        tx, settings, key = self.transaction(api)
        result = tx.apply("performance", settings)
        self.assertEqual(api.application, api.default)
        self.assertEqual(result["changed"], 0)
        self.assertIsNone(result["selections"][key]["selected"])
        self.assertTrue(any("conditional request skipped" in s for s in result["skipped"]))
        self.assertFalse(tx.journal["entries"])
        tx.reset()
        self.assertFalse(any(name == "nvmlDeviceResetApplicationsClocks" for name, _, _ in api.calls))

    def test_permission_device_loss_and_unknown_errors_do_not_try_another_pair(self):
        for status in (4, 15, 999):
            with self.subTest(status=status):
                api = ClockSelectionAPI()
                api.reject = lambda pair, code=status: code
                tx, settings, key = self.transaction(api)
                with self.assertRaises(base.nvidia.NVMLFailure):
                    tx.apply("performance", settings)
                self.assertEqual(api.attempts, [(3004, 1531)])
                self.assertEqual(api.application, api.default)

    def test_rejected_pair_with_changed_state_does_not_retry(self):
        api = ClockSelectionAPI()
        api.reject = lambda pair: 2
        api.change_on_failure = True
        tx, settings, key = self.transaction(api)
        with self.assertRaisesRegex(base.common.TuningError, "changed state; no retry"):
            tx.apply("performance", settings)
        self.assertEqual(api.attempts, [(3004, 1531)])
        self.assertEqual(api.application, api.default)

    def test_success_without_matching_readback_does_not_retry(self):
        api = ClockSelectionAPI()
        api.ignore_success = True
        tx, settings, key = self.transaction(api)
        with self.assertRaisesRegex(base.common.TuningError, "readback differs; no retry"):
            tx.apply("performance", settings)
        self.assertEqual(api.attempts, [(3004, 1531)])
        self.assertEqual(api.application, api.default)

    def test_selection_deadline_prevents_first_mutation(self):
        api = ClockSelectionAPI()
        tx, settings, key = self.transaction(api)
        with patch.object(base.nvidia.time, "monotonic", side_effect=[0, 9]):
            with self.assertRaisesRegex(base.common.TuningError, "deadline exceeded"):
                tx.apply("performance", settings)
        self.assertFalse(api.attempts)

    def test_explicit_numeric_pair_does_not_enable_maximum_fallback(self):
        api = ClockSelectionAPI()
        api.reject = lambda pair: 2
        tx, settings, key = self.transaction(api)
        tx.policy["profiles"]["performance"]["knobs"]["APPLICATION_CLOCKS_MHZ"] = "3004,1531"
        with self.assertRaises(base.nvidia.NVMLFailure):
            tx.apply("performance", settings)
        self.assertEqual(api.attempts, [(3004, 1531)])

    def test_failed_original_restore_keeps_journal_without_lower_recovery_substitution(self):
        api = ClockSelectionAPI()
        api.reject = lambda pair: 2 if pair[0] == 3004 else None
        tx, settings, key = self.transaction(api)
        tx.apply("performance", settings)
        attempts = list(api.attempts)
        api.reset_failure = 4
        with self.assertRaisesRegex(base.common.TuningError, "restoration incomplete"):
            tx.reset()
        self.assertEqual(api.attempts, attempts)
        self.assertEqual(tx.journal["entries"][0]["before"], "3004,1303")


class ConditionalSetterAPI(ClockSelectionAPI):
    def __init__(self):
        super().__init__()
        self.persistence = 0
        self.rejections = {}
        self.change_clock_on_rejection = False

    def scalar(self, name, handle, *extra, signed=False):
        if name == "nvmlDeviceGetPersistenceMode":
            return self.persistence
        return super().scalar(name, handle, *extra, signed=signed)

    def call(self, name, types, args):
        status = self.rejections.get(name)
        if status:
            self.calls.append((name, types, args))
            if self.change_clock_on_rejection:
                self.application = (810, 1518)
            error = base.nvidia.NVMLUnsupported if status == 3 else base.nvidia.NVMLFailure
            raise error(name, status)
        if name == "nvmlDeviceSetPersistenceMode":
            self.calls.append((name, types, args))
            self.persistence = args[1]
            return
        return super().call(name, types, args)


class NvidiaConditionalSetters(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sequence = 0

    def transaction(self, api, setting="PERSISTENCE_MODE", configured="supported-1"):
        self.sequence += 1
        prefix = "GPU-00000000-1111-2222-3333-444444444444/"
        hardware = base.nvidia.Backend(api, wanted={prefix + setting, prefix + "APPLICATION_CLOCKS_MHZ"})
        self.addCleanup(hardware.close)
        settings = {setting: ("keep",) * 4, "APPLICATION_CLOCKS_MHZ": ("keep",) * 4}
        policy = base.simple_policy(settings)
        policy["allow_power_increase"] = True
        policy["profiles"]["performance"]["knobs"].update(
            {setting: configured, "APPLICATION_CLOCKS_MHZ": "supported-max"})
        tx = base.engine.Engine(hardware, self.root / f"conditional-{self.sequence}.json", policy)
        return tx, settings, prefix + setting

    def test_only_nvml_not_supported_has_the_conditional_error_type(self):
        for status in (2, 3, 4, 15, 999):
            with self.subTest(status=status):
                api = base.nvidia.NVML.__new__(base.nvidia.NVML)
                api.lib = Mock(nvmlDeviceSetPersistenceMode=Mock(return_value=status))
                with self.assertRaises(base.nvidia.NVMLFailure) as failure:
                    api.call("nvmlDeviceSetPersistenceMode", [], [])
                self.assertEqual(failure.exception.status, status)
                self.assertEqual(failure.exception.function, "nvmlDeviceSetPersistenceMode")
                self.assertEqual(isinstance(failure.exception, base.common.UnsupportedControl), status == 3)

    def test_unsupported_persistence_skips_and_maximum_clock_selection_continues(self):
        api = ConditionalSetterAPI()
        api.rejections["nvmlDeviceSetPersistenceMode"] = 3
        tx, settings, key = self.transaction(api)
        result = tx.apply("performance", settings)
        self.assertEqual(api.persistence, 0)
        self.assertEqual(api.application, (3004, 1531))
        self.assertEqual(result["changed"], 1)
        self.assertTrue(any(key + ": setter unsupported" in s for s in result["skipped"]))
        self.assertNotIn(key, {entry["id"] for entry in tx.journal["entries"]})
        tx.reset()
        self.assertEqual(api.application, api.default)
        self.assertEqual(sum(name == "nvmlDeviceSetPersistenceMode" for name, _, _ in api.calls), 1)

    def test_unsupported_conditional_power_does_not_undo_working_maximum_clocks(self):
        api = ConditionalSetterAPI()
        api.rejections["nvmlDeviceSetPowerManagementLimit"] = 3
        tx, settings, key = self.transaction(api, "POWER_LIMIT_MW", "supported-max")
        result = tx.apply("performance", settings)
        self.assertEqual(api.power_value, 25000)
        self.assertEqual(api.application, (3004, 1531))
        self.assertNotIn(key, {entry["id"] for entry in tx.journal["entries"]})
        self.assertTrue(any(key + ": setter unsupported" in s for s in result["skipped"]))
        tx.reset()
        self.assertEqual(api.application, api.default)

    def test_explicit_persistence_request_still_fails_on_unsupported_setter(self):
        api = ConditionalSetterAPI()
        api.rejections["nvmlDeviceSetPersistenceMode"] = 3
        tx, settings, key = self.transaction(api, configured="1")
        with self.assertRaises(base.nvidia.NVMLUnsupported):
            tx.apply("performance", settings)
        self.assertFalse(api.attempts)

    def test_invalid_permission_lost_device_and_unknown_errors_are_not_skipped(self):
        for status in (2, 4, 15, 999):
            with self.subTest(status=status):
                api = ConditionalSetterAPI()
                api.rejections["nvmlDeviceSetPersistenceMode"] = status
                tx, settings, key = self.transaction(api)
                with self.assertRaises(base.nvidia.NVMLFailure):
                    tx.apply("performance", settings)
                self.assertFalse(api.attempts)
                self.assertFalse(tx.journal["entries"])

    def test_unsupported_reply_with_changed_clock_is_not_skipped(self):
        api = ConditionalSetterAPI()
        api.rejections["nvmlDeviceSetPersistenceMode"] = 3
        api.change_clock_on_rejection = True
        tx, settings, key = self.transaction(api)
        with self.assertRaisesRegex(base.common.TuningError, "unsupported setter changed state"):
            tx.apply("performance", settings)
        self.assertFalse(api.attempts)
        self.assertEqual(api.application, api.default)
        self.assertFalse(tx.journal["entries"])


class LeaseReadiness(unittest.TestCase):
    def test_unrelated_vendor_fault_does_not_reject_a_reconciled_lease(self):
        for vendor, other in (("intel", "nvidia"), ("nvidia", "intel")):
            channel = Mock()
            channel.recv.return_value = b""
            result = {"faults": {other: "fixture driver rejected"}, "applied": {vendor: "high"}}
            with self.subTest(vendor=vendor), \
                    patch.object(base.client, "connect_request", return_value=(channel, result)), \
                    patch.object(base.client.socket, "socket") as notification, \
                    patch.dict(os.environ, {"NOTIFY_SOCKET": "/fixture/notify"}, clear=True):
                self.assertEqual(base.client.lease(vendor, "balanced"), 1)
            sent = notification.return_value.__enter__.return_value.sendto.call_args.args
            self.assertEqual(sent, (f"READY=1\nSTATUS=Requested {vendor} balanced; applied high".encode(),
                                    "/fixture/notify"))
            channel.close.assert_called_once()

    def test_relevant_fault_reports_bounded_cause_without_notifying_ready(self):
        for fault in ("intel", "policy-owner"):
            channel = Mock()
            result = {"faults": {fault: "fixture driver\nrejected\t" + "x" * 3000},
                      "applied": {"intel": None}}
            with self.subTest(fault=fault), \
                    patch.object(base.client, "connect_request", return_value=(channel, result)), \
                    patch.object(base.client.socket, "socket") as notification, \
                    patch.dict(os.environ, {"NOTIFY_SOCKET": "/fixture/notify"}, clear=True):
                with self.assertRaises(base.common.TuningError) as failure:
                    base.client.lease("intel", "balanced")
            event = json.loads(str(failure.exception))
            self.assertEqual(event['event'], 'tuning_lease_failed')
            self.assertEqual((event['vendor'], event['profile']), ('intel', 'balanced'))
            self.assertEqual(len(event['correlation_id']), 32)
            self.assertTrue(event['faults'][fault].startswith('fixture driver rejected '))
            self.assertEqual(len(event['faults'][fault]), 2048)
            notification.assert_not_called()
            channel.close.assert_called_once()

    def test_ready_follows_reconciled_reply_and_reports_actual_manual_selection(self):
        with base.private_temp() as temporary:
            address = str(Path(temporary) / "notify")
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
                receiver.bind(address)
                receiver.settimeout(1)
                channel = Mock()
                channel.recv.return_value = b""
                result = {"faults": {}, "applied": {"intel": "silent"}}
                with patch.object(base.client, "connect_request", return_value=(channel, result)) as request, \
                        patch.dict(os.environ, {"NOTIFY_SOCKET": address}, clear=True):
                    self.assertEqual(base.client.lease("intel", "performance"), 1)
                request.assert_called_once_with({"action": "lease", "vendor": "intel", "profile": "performance"})
                self.assertEqual(receiver.recv(512), b"READY=1\nSTATUS=Requested intel performance; applied silent")
                channel.close.assert_called_once()

    def test_fault_or_invalid_reply_never_sends_ready_and_closes_lease(self):
        for result in ({"faults": {"intel": "driver rejected"}, "applied": {"intel": None}},
                       {"faults": {"policy-owner": "handoff rejected"}, "applied": {"intel": None}},
                       {"faults": {"nvidia": []}, "applied": {"intel": "high"}},
                       {"faults": {}, "applied": {}},
                       {"faults": {}, "applied": []},
                       {"faults": {}, "applied": {"intel": "unverified"}}):
            with self.subTest(result=result):
                channel = Mock()
                with patch.object(base.client, "connect_request", return_value=(channel, result)), \
                        patch.object(base.client.socket, "socket") as notify, \
                        patch.dict(os.environ, {"NOTIFY_SOCKET": "/fixture/notify"}, clear=True):
                    with self.assertRaises(base.common.TuningError):
                        base.client.lease("intel", "performance")
                notify.assert_not_called()
                channel.close.assert_called_once()
