"""Policy handover regressions: no host services or physical hardware are used.

Includes a real libsystemd/private-D-Bus wire fixture, deterministic unit-state
fault injection, broker recovery fixtures, and launcher confinement contracts.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_hardware_tuning_20260916 as base
import policy_owner as policy


class FakeManager:
    def __init__(self):
        self.events = []
        self.units = {name: {"enabled": name == policy.PPD, "mask": False, "runtime": False,
                             "active": "active" if name == policy.PPD else "inactive", "load": "loaded"}
                      for name in policy.UNITS}
        self.fail_at = None
        self.mutations = 0
        self.shutdown = False
        self.lie_stop = False

    def state(self, name):
        if name not in policy.UNITS:
            raise AssertionError("unexpected unit name")
        u = self.units[name]
        if u["load"] == "not-found":
            return {"load": "not-found", "active": "inactive", "file": "not-found"}
        return {"load": "masked" if u["mask"] or u["runtime"] else "loaded", "active": u["active"],
                "file": "masked" if u["mask"] else "masked-runtime" if u["runtime"] else "enabled" if u["enabled"] else "disabled"}

    def mutation(self, *event):
        self.events.append(event)
        self.mutations += 1
        if self.fail_at == self.mutations:
            raise base.common.TuningError("injected PID 1 mutation failure")

    def files(self, member, name, runtime=False):
        self.state(name)
        self.mutation(member, name, runtime)
        u = self.units[name]
        if member == "EnableUnitFiles":
            if u["mask"] or u["runtime"]:
                raise base.common.TuningError("masked unit cannot be enabled")
            u["enabled"] = True
        elif member == "DisableUnitFiles":
            # Match systemctl --root: a masked unit's install data is skipped.
            if not u["mask"] and not u["runtime"]:
                u["enabled"] = False
        elif member == "MaskUnitFiles":
            u["runtime" if runtime else "mask"] = True
        elif member == "UnmaskUnitFiles":
            u["runtime" if runtime else "mask"] = False
        else:
            raise AssertionError(member)

    def job(self, member, name):
        self.state(name)
        self.mutation(member, name)
        u = self.units[name]
        if member == "StartUnit":
            if u["mask"] or u["runtime"]:
                raise base.common.TuningError("unit masked")
            u["active"] = "active"
        elif member == "StopUnit":
            if not self.lie_stop:
                u["active"] = "inactive"
        else:
            raise AssertionError(member)

    def stopping(self):
        return self.shutdown


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = FakeManager()
        self.states = {name: "inactive" for name in policy.POWER_MANAGERS}
        self.states[policy.PPD] = "active"
        self.owner = policy.PolicyOwner(self.manager, ["intel", "nvidia"], self.root, lambda: self.states)

    def journal(self, vendor, entries):
        base.common.atomic_json(self.root / (vendor + ".json"), {"version": 1, "entries": entries, "profile": None})

    def test_temporary_start_masks_before_stop_and_retains_boot_enablement(self):
        result = self.owner.prepare(False)
        self.assertEqual(self.manager.events, [("MaskUnitFiles", policy.PPD, True), ("StopUnit", policy.PPD)])
        self.assertEqual(result["ppd"]["file"], "masked-runtime")
        self.assertEqual(result["ppd"]["active"], "inactive")
        self.assertTrue(self.manager.units[policy.PPD]["enabled"])
        self.assertFalse(self.manager.units[policy.AUTOSTART]["enabled"])
        self.assertTrue(result["claimed"])

    def test_boot_enable_disables_even_when_runtime_mask_already_exists(self):
        self.owner.prepare(False)
        self.manager.events.clear()
        self.owner.prepare(True)
        self.owner.activate()
        self.assertEqual(self.manager.events[0], ("EnableUnitFiles", policy.AUTOSTART, False))
        self.assertFalse(self.manager.units[policy.PPD]["enabled"])
        self.assertTrue(self.manager.units[policy.PPD]["mask"])
        self.assertFalse(self.manager.units[policy.PPD]["runtime"])
        self.assertEqual(self.manager.state(policy.AUTOSTART)["active"], "active")
        self.assertEqual(self.manager.state(policy.AUTOSTART)["file"], "enabled")

    def test_stop_from_boot_mode_keeps_boot_preference_but_unmasks_ppd(self):
        self.owner.prepare(True)
        self.owner.activate()
        result = self.owner.release(False)
        self.assertEqual(result["ppd"], {"load": "loaded", "active": "active", "file": "disabled"})
        self.assertEqual(result["autostart_unit"], {"load": "loaded", "active": "inactive", "file": "enabled"})
        self.assertFalse(result["claimed"])

    def test_disable_restores_ppd_before_removing_custom_boot_recovery(self):
        self.owner.prepare(True)
        self.owner.activate()
        self.manager.events.clear()
        result = self.owner.release(True)
        events = self.manager.events
        self.assertLess(events.index(("StartUnit", policy.PPD)), events.index(("DisableUnitFiles", policy.AUTOSTART, False)))
        self.assertEqual(result["ppd"], {"load": "loaded", "active": "active", "file": "enabled"})
        self.assertEqual(result["autostart_unit"]["file"], "disabled")
        self.assertEqual(result["autostart_unit"]["active"], "inactive")

    def test_default_reset_is_idempotent_and_does_not_restart_active_ppd(self):
        self.owner.release(True)
        self.owner.release(True)
        self.assertEqual(self.manager.events, [])

    def test_stacked_persistent_and_runtime_masks_are_both_removed(self):
        u = self.manager.units[policy.PPD]
        u.update(mask=True, runtime=True, active="inactive", enabled=False)
        result = self.owner.release(True)
        self.assertEqual(result["ppd"]["file"], "enabled")
        self.assertFalse(u["mask"] or u["runtime"])

    def test_owned_hardware_prevents_all_ppd_handback_mutations(self):
        self.owner.prepare(False)
        for vendor in ("intel", "nvidia"):
            with self.subTest(vendor=vendor):
                self.journal(vendor, [{"pending": True}])
                self.manager.events.clear()
                with self.assertRaisesRegex(base.common.TuningError, "recovery must complete"):
                    self.owner.release(True)
                self.assertEqual(self.manager.events, [])
                self.assertTrue(self.owner.claimed)
                self.journal(vendor, [])

    def test_prepare_boot_refuses_to_unmask_under_owned_hardware(self):
        self.journal("intel", [{"pending": False}])
        with self.assertRaisesRegex(base.common.TuningError, "recovery must complete"):
            self.owner.prepare(True)
        self.assertEqual(self.manager.events, [])

    def test_worker_lock_held_through_ppd_start(self):
        original = self.manager.job
        def job(member, name):
            for vendor in self.owner.vendors:
                with (self.root / (vendor + ".lock")).open("r+") as f:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return original(member, name)
        self.manager.job = job
        self.owner.prepare(False)
        self.owner.release(False)

    def test_existing_worker_lock_prevents_service_mutation(self):
        with policy.locked(self.root / "intel.lock"):
            with self.assertRaises(BlockingIOError):
                self.owner.prepare(False)
        self.assertEqual(self.manager.events, [])

    def test_lock_symlink_hardlink_and_mutable_directory_are_rejected(self):
        other = self.root / "other"
        other.write_text("unchanged")
        path = self.root / "bad.lock"
        path.symlink_to(other)
        with self.assertRaises(OSError):
            with policy.locked(path):
                self.fail("symlink accepted")
        path.unlink()
        other.chmod(0o600)
        os.link(other, path)
        with self.assertRaisesRegex(base.common.TuningError, "untrusted"):
            with policy.locked(path):
                self.fail("hardlink accepted")
        path.unlink()
        mutable = self.root / "mutable"
        mutable.mkdir(mode=0o777)
        mutable.chmod(0o777)
        with self.assertRaisesRegex(base.common.TuningError, "state directory"):
            with policy.locked(mutable / "bad.lock"):
                self.fail("mutable ancestor accepted")
        self.assertEqual(other.read_text(), "unchanged")

    def test_journal_symlink_and_invalid_shape_fail_closed(self):
        other = self.root / "other.json"
        other.write_text('{"version":1,"claimed":true}')
        self.owner.journal.symlink_to(other)
        with self.assertRaises(OSError):
            policy.PolicyOwner(self.manager, ["intel"], self.root)
        self.owner.journal.unlink()
        base.common.atomic_json(self.owner.journal, {"version": True, "claimed": True})
        with self.assertRaisesRegex(base.common.TuningError, "ownership journal"):
            policy.PolicyOwner(self.manager, ["intel"], self.root)

    def test_other_owners_are_not_stopped_on_takeover_or_handback(self):
        for name in policy.POWER_MANAGERS:
            if name == policy.PPD:
                continue
            with self.subTest(owner=name):
                self.states[name] = "active"
                for operation in (lambda: self.owner.prepare(False), lambda: self.owner.release(True)):
                    with self.assertRaisesRegex(base.common.TuningError, "administrator attention"):
                        operation()
                self.assertEqual(self.manager.events, [])
                self.states[name] = "inactive"

    def test_incomplete_or_unknown_policy_inventory_is_not_inactive(self):
        self.states.pop("tlp.service")
        with self.assertRaisesRegex(base.common.TuningError, "incomplete"):
            self.owner.prepare(False)
        self.states["tlp.service"] = "unknown"
        with self.assertRaisesRegex(base.common.TuningError, "administrator"):
            self.owner.prepare(False)
        self.assertEqual(self.manager.events, [])

    def test_ppd_stop_success_must_be_read_back(self):
        self.manager.lie_stop = True
        with self.assertRaisesRegex(base.common.TuningError, "exclusion could not be verified"):
            self.owner.prepare(False)
        self.assertTrue(self.owner.claimed)
        self.assertEqual(self.manager.state(policy.PPD)["file"], "masked-runtime")

    def test_missing_ppd_not_installed_or_masked_as_phantom_unit(self):
        self.manager.units[policy.PPD]["load"] = "not-found"
        self.owner.prepare(True)
        self.owner.activate()
        self.owner.release(True)
        self.assertFalse(any(len(event) > 1 and event[1] == policy.PPD for event in self.manager.events))

    def test_nvidia_only_install_never_reads_or_mutates_ppd(self):
        original = self.manager.state
        def state(name):
            self.assertNotEqual(name, policy.PPD)
            return original(name)
        self.manager.state = state
        owner = policy.PolicyOwner(self.manager, ["nvidia"], self.root,
                                   lambda: self.fail("NVIDIA-only queried CPU owners"))
        owner.prepare(True)
        owner.activate()
        result = owner.release(True)
        self.assertEqual(result["ppd"]["load"], "not-managed")

    def test_recovery_only_releases_recorded_claim_and_never_starts_at_shutdown(self):
        self.owner.release(False, recovery=True)
        self.assertEqual(self.manager.events, [])
        self.owner.prepare(True)
        self.manager.events.clear()
        self.manager.shutdown = True
        result = self.owner.release(False, recovery=True)
        self.assertEqual(self.manager.events, [])
        self.assertTrue(result["claimed"])
        self.manager.shutdown = False
        result = self.owner.release(False, recovery=True)
        self.assertEqual(result["ppd"]["active"], "active")

    def test_power_loss_at_each_boot_prepare_step_has_a_next_boot_owner(self):
        for step in range(1, 8):
            with self.subTest(step=step):
                manager = FakeManager()
                owner = policy.PolicyOwner(manager, ["intel"], self.root, lambda: self.states)
                manager.fail_at = step
                try:
                    owner.prepare(True)
                except base.common.TuningError:
                    pass
                ppd, auto = manager.units[policy.PPD], manager.units[policy.AUTOSTART]
                self.assertTrue(auto["enabled"] or ppd["enabled"] and not ppd["mask"], manager.events)

    def test_power_loss_at_each_disable_step_has_a_next_boot_owner(self):
        for step in range(1, 8):
            with self.subTest(step=step):
                manager = FakeManager()
                owner = policy.PolicyOwner(manager, ["intel"], self.root, lambda: self.states)
                owner.prepare(True)
                owner.activate()
                manager.fail_at = manager.mutations + step
                try:
                    owner.release(True)
                except base.common.TuningError:
                    pass
                ppd, auto = manager.units[policy.PPD], manager.units[policy.AUTOSTART]
                self.assertTrue(auto["enabled"] or ppd["enabled"] and not ppd["mask"], manager.events)

    def test_helper_rejects_arbitrary_actions_and_units(self):
        with self.assertRaises(base.common.TuningError):
            self.owner.execute("stop ssh.service")
        for name in ("ssh.service", "../power-profiles-daemon.service", policy.PPD + ";id"):
            with self.assertRaises(base.common.TuningError):
                policy.Systemd.unit_path(name)
        for args in ([], ["status", "ssh.service"], ["shell"]):
            with self.assertRaises(base.common.TuningError):
                policy.main(args)


class InstrumentedBroker(base.FakeBroker):
    def __init__(self):
        super().__init__()
        self.events = []
        self.policy_failure = None

    async def policy(self, action):
        self.events.append(("policy", action))
        if action == self.policy_failure:
            raise base.common.TuningError("injected policy failure: " + action)
        if action in {"stop", "disable"}:
            if any(self.owned.values()) or self.recovery_pending:
                raise AssertionError("PPD handback before hardware recovery")
        return await super().policy(action)

    async def worker(self, vendor, action, profile=None):
        self.events.append(("worker", vendor, action))
        if vendor == "intel" and action == "apply" and self.ppd_active != "inactive":
            raise AssertionError("Intel apply while PPD active")
        return await super().worker(vendor, action, profile)


class BrokerHandoverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = InstrumentedBroker()
        ac = patch.object(base.broker, "on_ac", return_value=True)
        ac.start()
        self.addCleanup(ac.stop)

    async def activate(self, boot=False):
        return await self.b.action({"action": "boot-enable" if boot else "auto-start", "confirm_policy_owner": True}, 1000)

    async def test_unconfirmed_takeover_has_no_worker_or_policy_mutation(self):
        for action in ("auto-start", "boot-enable"):
            with self.assertRaisesRegex(base.common.TuningError, "confirmation"):
                await self.b.action({"action": action}, 1000)
        self.assertEqual(self.b.events, [("policy", "status")] * 2)

    async def test_temporary_start_and_stop_ordering(self):
        await self.activate()
        events = self.b.events
        self.assertLess(events.index(("policy", "prepare-runtime")), events.index(("worker", "intel", "apply")))
        self.b.events.clear()
        result = await self.b.action({"action": "auto-stop"}, 1000)
        self.assertEqual(self.b.events[-1], ("policy", "stop"))
        self.assertFalse(result["automatic"])
        self.assertFalse(result["faults"])
        self.assertEqual(result["policy_owner"]["ppd"]["active"], "active")

    async def test_enable_is_immediate_and_second_enable_does_not_reapply(self):
        result = await self.activate(True)
        self.assertTrue(result["automatic"] and result["autostart"])
        self.assertEqual(self.b.marker_active, "active")
        self.b.calls.clear()
        await self.activate(True)
        self.assertEqual(self.b.calls, [])

    async def test_disable_and_reset_stop_all_custom_modes_and_restore_ppd(self):
        for action in ("boot-disable", "reset"):
            with self.subTest(action=action):
                await self.activate(True)
                await self.b.action({"action": "manual", "vendor": "intel", "profile": "high"}, 1000)
                result = await self.b.action({"action": action}, 1000)
                self.assertFalse(result["automatic"] or result["autostart"])
                self.assertFalse(any(result["manual"].values()) or any(result["owns_controls"].values()))
                self.assertEqual(result["policy_owner"]["ppd"]["file"], "enabled")
                self.assertEqual(result["policy_owner"]["ppd"]["active"], "active")

    async def test_pending_restore_blocks_ppd_restart_and_explicit_reset_retries(self):
        await self.activate()
        self.b.fail = ("intel", "reset")
        self.b.policy_calls.clear()
        result = await self.b.action({"action": "reset"}, 1000)
        self.assertIn("intel", result["recovery_pending"])
        self.assertNotIn("disable", self.b.policy_calls)
        self.assertEqual(result["policy_release_pending"], "disable")
        self.assertEqual(self.b.ppd_active, "inactive")
        self.b.fail = None
        result = await self.b.action({"action": "reset"}, 1000)
        self.assertFalse(result["faults"])
        self.assertIsNone(result["policy_release_pending"])
        self.assertEqual(self.b.ppd_active, "active")

    async def test_interrupted_restart_cannot_reapply_retained_manual_profile(self):
        await self.activate()
        await self.b.action({"action": "manual", "vendor": "intel", "profile": "high"}, 1000)
        self.b.fail = ("nvidia", "reset")
        result = await self.activate()
        self.assertEqual(result["manual"]["intel"], "high")
        self.assertEqual(result["policy_release_pending"], "stop")
        self.assertIn("nvidia", result["recovery_pending"])
        self.b.calls.clear()
        await self.b.reconcile(health=True)
        self.assertFalse(any(action == "apply" for _, action, _ in self.b.calls))
        self.assertIsNone(self.b.applied["intel"])
        self.assertEqual(self.b.ppd_active, "inactive")
        self.b.fail = None
        result = await self.b.action({"action": "reset"}, 1000)
        self.assertFalse(result["faults"])
        self.assertEqual(self.b.ppd_active, "active")

    async def test_failed_ppd_takeover_never_applies_and_returns_a_fault(self):
        self.b.policy_failure = "prepare-runtime"
        result = await self.activate()
        self.assertIn("policy-owner", result["faults"])
        self.assertFalse(result["automatic"])
        self.assertFalse(any(action == "apply" for _, action, _ in self.b.calls))
        self.assertEqual(self.b.ppd_active, "active")

    async def test_failed_ppd_restart_preserves_handback_intent_without_reapplying(self):
        await self.activate()
        self.b.policy_failure = "stop"
        result = await self.b.action({"action": "auto-stop"}, 1000)
        self.assertIn("policy-owner", result["faults"])
        self.assertEqual(result["policy_release_pending"], "stop")
        self.b.calls.clear()
        await self.b.reconcile()
        self.assertEqual(self.b.calls, [])

    async def test_failed_boot_activation_rolls_back_new_boot_enablement(self):
        self.b.policy_failure = "activate"
        result = await self.activate(True)
        self.assertFalse(result["automatic"] or result["autostart"])
        self.assertEqual(self.b.ppd_active, "active")
        self.assertIn("policy-owner", result["faults"])

    async def test_intel_fault_returns_all_remaining_controls_before_ppd(self):
        self.b.fail = ("intel", "apply")
        result = await self.activate()
        self.assertIn("intel", result["faults"])
        self.assertFalse(result["automatic"])
        self.assertEqual(self.b.ppd_active, "active")
        self.assertFalse(any(self.b.owned.values()))

    async def test_manual_intel_confirmation_and_nvidia_independence(self):
        with self.assertRaisesRegex(base.common.TuningError, "confirmation"):
            await self.b.action({"action": "manual", "vendor": "intel", "profile": "high"}, 1000)
        await self.b.action({"action": "manual", "vendor": "nvidia", "profile": "balanced"}, 1000)
        self.assertEqual(self.b.ppd_active, "active")
        await self.b.action({"action": "manual", "vendor": "intel", "profile": "high", "confirm_policy_owner": True}, 1000)
        self.assertEqual(self.b.applied, {"intel": "high", "nvidia": "balanced"})
        await self.b.action({"action": "profiles-reset"}, 1000)
        self.assertEqual(self.b.ppd_active, "active")

    async def test_new_boot_uses_autostart_without_local_seat_or_popup(self):
        with base.private_temp() as temp, patch.object(base.broker, "STATE", Path(temp)):
            self.b.boot_enabled = True
            self.b.seat.present = False
            await self.b.initialize()
        self.assertTrue(self.b.selection.automatic)
        self.assertEqual(self.b.ppd_active, "inactive")
        self.assertFalse(any(action == "apply" for _, action, _ in self.b.calls))
        self.b.seat.present = True
        await self.b.reconcile()
        self.assertEqual(self.b.applied["intel"], "balanced")

    async def test_same_boot_restart_honors_stop_despite_boot_enablement(self):
        with base.private_temp() as temp, patch.object(base.broker, "STATE", Path(temp)):
            self.b.boot_enabled = True
            self.b.selection.automatic = False
            base.broker.Broker.save(self.b)
            new = InstrumentedBroker()
            new.boot_enabled = True
            await new.initialize()
        self.assertFalse(new.selection.automatic)
        self.assertEqual(new.ppd_active, "active")
        self.assertNotIn("prepare-boot", new.policy_calls)

    async def test_restart_finishes_interrupted_disable(self):
        with base.private_temp() as temp, patch.object(base.broker, "STATE", Path(temp)):
            self.b.policy_release = "disable"
            base.broker.Broker.save(self.b)
            new = InstrumentedBroker()
            new.boot_enabled, new.claimed, new.ppd_active = True, True, "inactive"
            await new.initialize()
        self.assertFalse(new.boot_enabled or new.selection.automatic)
        self.assertIsNone(new.policy_release)
        self.assertEqual(new.ppd_active, "active")

    async def test_root_sleep_and_restart_do_not_bypass_fault_interlocks(self):
        await self.activate()
        await self.b.action({"action": "pause"}, 0)
        self.assertEqual(self.b.ppd_active, "inactive")
        with self.assertRaisesRegex(base.common.TuningError, "paused"):
            await self.activate()
        await self.b.action({"action": "resume"}, 0)
        self.assertEqual(self.b.applied["intel"], "balanced")

    async def test_invalid_confirmation_and_remote_start_fail_closed(self):
        for value in ("true", 1, None, {}, []):
            with self.assertRaises(base.common.TuningError):
                self.b.validate_request({"action": "auto-start", "confirm_policy_owner": value})
        for action in ("status", "reset", "auto-stop", "lease"):
            with self.assertRaises(base.common.TuningError):
                self.b.validate_request({"action": action, "confirm_policy_owner": True})
        self.b.seat.present = False
        with self.assertRaisesRegex(base.common.TuningError, "local seat"):
            await self.activate(True)


class ClientAndInstallTests(unittest.TestCase):
    def test_start_and_boot_enable_cancel_have_no_mutating_request(self):
        for selection in ("Start Automatic Tuning", "Enable Autostart Tuning at Boot"):
            with self.subTest(selection=selection):
                status = {"vendors": ["intel"], "policy_owner": {"claimed": False}}
                with patch.object(base.client, "request", return_value=status) as request, \
                        patch.object(base.client, "choose", side_effect=[selection, None]):
                    self.assertEqual(base.client.menu(), 0)
                    request.assert_called_once_with("status")

    def test_confirmed_start_sends_explicit_boolean_not_user_text(self):
        status = {"vendors": ["intel"], "policy_owner": {"claimed": False}}
        choices = []
        def choose(entries, prompt):
            choices.append(entries)
            return "Start Automatic Tuning" if len(choices) == 1 else entries[1]
        with patch.object(base.client, "request", side_effect=[status, {"faults": {}}]) as request, \
                patch.object(base.client, "choose", side_effect=choose), patch.object(base.client, "notify"):
            self.assertEqual(base.client.menu(), 0)
        self.assertTrue(choices[1][0].startswith("Cancel"))
        request.assert_called_with("auto-start", confirm_policy_owner=True)

    def test_cli_confirmation_is_explicit_and_only_valid_on_acquisition(self):
        for args in (["auto-start", "--confirm-policy-owner"], ["boot-enable", "--confirm-policy-owner"]):
            with patch.object(base.client, "request", return_value={}) as request, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(base.client.main(args), 0)
                request.assert_called_once_with(args[0], confirm_policy_owner=True)
        with self.assertRaises(base.common.TuningError):
            base.client.main(["reset", "--confirm-policy-owner"])

    def test_autostart_marker_is_root_only_and_never_calls_broker(self):
        with patch.object(base.client.os, "geteuid", return_value=0), \
                patch.object(base.client, "request", side_effect=AssertionError("deadlocking callback")):
            self.assertEqual(base.client.main(["autostart-marker"]), 0)
        with patch.object(base.client.os, "geteuid", return_value=1000):
            with self.assertRaises(base.common.TuningError):
                base.client.main(["autostart-marker"])

    def test_system_and_user_units_have_correct_slice_and_lifecycle_roles(self):
        with base.private_temp() as temp:
            root = Path(temp)
            waybar = root / "etc/skel-desktop/.config/waybar/config"
            waybar.parent.mkdir(parents=True)
            waybar.write_text('{"battery":{"on-click":"unchanged"}}')
            base.installer.install(root, 1000, 1000, base.environment(), ["intel", "nvidia"])
            units = root / "etc/systemd/system"
            for name in ("hardware-tuning.service", "hardware-tuning-autostart.service", "hardware-tuning-sleep.service"):
                self.assertIn("Slice=system.slice", (units / name).read_text())
            broker = (units / "hardware-tuning.service").read_text()
            self.assertIn("ExecStopPost=/usr/local/libexec/hardware-tuning-policy recover", broker)
            self.assertNotIn("ReadWritePaths=/run/hardware-tuning /etc/systemd", broker)
            marker = (units / "hardware-tuning-autostart.service").read_text()
            self.assertIn("RemainAfterExit=yes", marker)
            self.assertIn("BindsTo=hardware-tuning.service", marker)
            self.assertIn("autostart-marker", marker)
            self.assertNotIn("ExecStop=", marker)
            for path in (root / "etc/systemd/user").glob("*.target"):
                self.assertNotIn("Slice=", path.read_text())
            for path in (root / "etc/systemd/user").glob("hardware-tuning-*.service"):
                self.assertIn("Slice=background.slice", path.read_text())

    def test_apparmor_cgroup_read_is_owner_scoped_and_policy_domain_separate(self):
        text = (base.FORKY / "hooks/target/etc/apparmor.d/managed-hardware-tuning").read_text()
        client = text.split("profile managed-hardware-tuning-client ", 1)[1].split("profile managed-hardware-tuning-policy ", 1)[0]
        self.assertIn("owner /proc/[0-9]*/{stat,status,cgroup} r,", client)
        self.assertNotIn("systemd1.Manager", client)
        broker = text.split("profile managed-hardware-tuning-broker ", 1)[1].split("profile managed-hardware-tuning-worker ", 1)[0]
        self.assertNotIn("systemd1.Manager", broker)
        self.assertNotIn("autostart.service rw,", broker)
        helper = text.split("profile managed-hardware-tuning-policy ", 1)[1]
        self.assertNotIn("/usr/bin/systemctl", helper)
        self.assertNotIn("/sys/", helper)
        self.assertIn("-> managed-hardware-tuning-policy", broker)

    def test_recover_all_skips_uninstalled_backend_but_keeps_existing_journal(self):
        with base.private_temp() as temp:
            root = Path(temp)
            config, state = root / "config", root / "state"
            config.mkdir(); state.mkdir()
            (config / "intel.json").write_text("{}")
            with patch.object(base.engine, "CONFIG", config), patch.object(base.engine, "STATE", state), \
                    patch.object(base.engine, "execute", return_value={"restored": 0}) as execute, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(base.engine.main(["recover-all"]), 0)
                execute.assert_called_once_with("intel", "reset")
                (state / "nvidia.json").write_text("{}")
                execute.reset_mock()
                self.assertEqual(base.engine.main(["recover-all"]), 0)
                self.assertEqual([c.args for c in execute.call_args_list], [("intel", "reset"), ("nvidia", "reset")])


@unittest.skipUnless(shutil.which("cc") and shutil.which("dbus-daemon"), "private bus fixture requires cc and dbus-daemon")
class NativeBusTests(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "peer"
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", str(base.FORKY / "tests/fixtures/hardware-handover-bus.c"),
                        "-Wl,-l:libsystemd.so.0", "-o", str(self.binary)], check=True, capture_output=True, timeout=20)
        daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1",
                                   "--address=unix:path=" + str(self.root / "bus")],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.close, daemon)
        self.assertTrue(select.select([daemon.stdout], [], [], 5)[0])
        address = daemon.stdout.readline().strip()
        env = patch.dict(os.environ, {"DBUS_SYSTEM_BUS_ADDRESS": address})
        env.start(); self.addCleanup(env.stop)

    @staticmethod
    def close(process):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        process.stdout.close(); process.stderr.close()

    def peer(self, mode="ok"):
        process = subprocess.Popen([str(self.binary), mode, str(self.root / "trace")],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.close, process)
        self.assertTrue(select.select([process.stdout], [], [], 5)[0])
        self.assertEqual(process.stdout.readline().strip(), "ready")
        manager = policy.Systemd()
        self.addCleanup(manager.close)
        return manager, policy.PolicyOwner(manager, ["intel"], self.root)

    def test_real_libsystemd_complete_round_trip_and_array_boolean_signatures(self):
        manager, owner = self.peer()
        result = owner.prepare(False)
        self.assertEqual(result["ppd"]["file"], "masked-runtime")
        result = owner.prepare(True)
        self.assertEqual(result["ppd"]["file"], "masked")
        owner.activate()
        result = owner.release(False)
        self.assertEqual(result["ppd"]["file"], "disabled")
        self.assertEqual(result["ppd"]["active"], "active")
        self.assertEqual(result["autostart_unit"]["file"], "enabled")
        owner.prepare(True); owner.activate()
        result = owner.release(True)
        self.assertEqual(result["ppd"]["file"], "enabled")
        self.assertEqual(result["autostart_unit"]["file"], "disabled")
        trace = (self.root / "trace").read_text()
        self.assertIn("MaskUnitFiles power-profiles-daemon.service runtime=1 force=0", trace)
        self.assertIn("MaskUnitFiles power-profiles-daemon.service runtime=0 force=0", trace)
        self.assertIn("Reload", trace)
        self.assertNotIn("force=1", trace)

    def test_real_denied_stop_fails_without_claiming_exclusion(self):
        _, owner = self.peer("deny-stop")
        with self.assertRaisesRegex(base.common.TuningError, "denied stop"):
            owner.prepare(False)
        self.assertTrue(owner.claimed)

    def test_real_stop_return_without_inactive_state_is_not_success(self):
        _, owner = self.peer("stop-lies")
        with self.assertRaisesRegex(base.common.TuningError, "required state"):
            owner.prepare(False)

    def test_real_start_failure_preserves_claim_for_retry(self):
        _, owner = self.peer("start-fails")
        owner.prepare(False)
        with self.assertRaisesRegex(base.common.TuningError, "required state"):
            owner.release(False)
        self.assertTrue(owner.claimed)

    def test_real_pending_job_is_cancelled_within_bounded_deadline(self):
        manager, _ = self.peer("pending-job")
        manager.deadline = time.monotonic() + 2.3
        start = time.monotonic()
        with self.assertRaisesRegex(base.common.TuningError, "timed out"):
            manager.job("StopUnit", policy.PPD)
        self.assertLess(time.monotonic() - start, 3)
        self.assertIn("Cancel", (self.root / "trace").read_text())

    def test_real_missing_file_reply_is_not_accepted_as_absent_active_ppd(self):
        manager, _ = self.peer("missing-file-state")
        with self.assertRaisesRegex(base.common.TuningError, "missing file state"):
            manager.state(policy.PPD)

    def test_real_other_owner_rejected_before_unit_mutations(self):
        _, owner = self.peer("other-owner")
        with self.assertRaisesRegex(base.common.TuningError, "tlp.service"):
            owner.prepare(False)
        self.assertEqual((self.root / "trace").read_text(), "")

    def test_real_missing_ppd_and_shutdown_paths(self):
        _, owner = self.peer("missing-ppd")
        result = owner.prepare(True)
        self.assertEqual(result["ppd"]["load"], "not-found")
        result = owner.release(True)
        self.assertFalse(result["claimed"])
        self.assertNotIn("power-profiles-daemon.service", (self.root / "trace").read_text())


if __name__ == "__main__":
    unittest.main()
