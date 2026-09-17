"""Regression fixtures for policy ownership, hardware transactions and lifecycle.

No writes to real sysfs, production services or driver state. The optional bus
integration fixture runs on an isolated dbus-daemon, not the host system bus.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_hardware_tuning_20260916 as base
import system_state


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'journal.json'
        self.backend = base.FakeBackend()

    def transaction(self, settings):
        return base.engine.Engine(self.backend, self.path, base.simple_policy(settings))

    def cpu(self):
        b = self.backend
        gov = b.add('policy0/governor', 'CPU_GOVERNOR', 'performance', choices=('performance', 'powersave'))
        b.add('policy0/epp', 'CPU_EPP', 'performance', choices=('performance', 'balance_performance'))
        original = gov.write
        def write(value):
            original(value)
            b.values['policy0/epp'] = 'balance_performance' if value == 'powersave' else 'performance'
        gov.write = write
        return {'CPU_GOVERNOR': ('powersave',) * 4, 'CPU_EPP': ('performance',) * 4}

    def test_initially_equal_epp_reapplied_after_governor_side_effect(self):
        settings = self.cpu()
        tx = self.transaction(settings)
        result = tx.apply('high', settings)
        self.assertEqual(self.backend.values['policy0/epp'], 'performance')
        self.assertEqual(result['changed'], 2)
        tx.reset()
        self.assertEqual(self.backend.values, {'policy0/governor': 'performance', 'policy0/epp': 'performance'})

    def test_silent_in_range_driver_ignore_is_not_success(self):
        knob = self.backend.add('X', 'X', 20)
        knob.write = lambda value: None
        settings = {'X': ('30',) * 4}
        tx = self.transaction(settings)
        with self.assertRaisesRegex(base.common.TuningError, 'read back 20'):
            tx.apply('high', settings)
        self.assertEqual(tx.journal['entries'], [])
        self.assertEqual(self.backend.values['X'], 20)

    def test_already_correct_independent_knob_not_owned(self):
        self.backend.add('X', 'X', 20)
        settings = {'X': ('20',) * 4}
        tx = self.transaction(settings)
        result = tx.apply('balanced', settings)
        self.assertEqual(result['changed'], 0)
        self.assertEqual(result['controls'], {})
        self.assertFalse(self.backend.writes)

    def test_reset_intent_durable_before_restore_write(self):
        self.backend.add('X', 'X', 20)
        settings = {'X': ('30',) * 4}
        tx = self.transaction(settings)
        tx.apply('high', settings)
        def before(key, value):
            saved = json.loads(self.path.read_text())
            self.assertTrue(saved['entries'][0]['pending'])
            raise KeyboardInterrupt('simulated interrupted recovery')
        self.backend.before_write = before
        with self.assertRaises(KeyboardInterrupt):
            tx.reset()
        self.backend.before_write = None
        recovered = base.engine.Engine(self.backend, self.path)
        recovered.reset()
        self.assertEqual(self.backend.values['X'], 20)
        self.assertEqual(recovered.journal['entries'], [])

    def test_failed_paired_restore_retains_both_baselines(self):
        b = self.backend
        b.add('low', 'LOW', 10, pair='pair', side='min')
        b.add('high', 'HIGH', 90, pair='pair', side='max')
        settings = {'LOW': ('20',) * 4, 'HIGH': ('80',) * 4}
        tx = self.transaction(settings)
        tx.apply('high', settings)
        b.failure = lambda key, value: key == 'high' and value == 90
        with self.assertRaisesRegex(base.common.TuningError, 'restoration incomplete'):
            tx.reset()
        self.assertEqual({e['id'] for e in tx.journal['entries']}, {'low', 'high'})
        self.assertTrue(all(e['pending'] for e in tx.journal['entries']))
        b.failure = None
        base.engine.Engine(b, self.path).reset()
        self.assertEqual(b.values, {'low': 10, 'high': 90})

    def test_power_gate_uses_original_journal_not_new_tuned_baseline(self):
        self.backend.add('power', 'RAPL_PL1_POWER_UW', 15, low=1, high=40, power_default=15)
        settings = {'RAPL_PL1_POWER_UW': ('20',) * 4}
        policy = base.simple_policy(settings)
        policy['allow_power_increase'] = True
        tx = base.engine.Engine(self.backend, self.path, policy)
        tx.apply('high', settings)
        self.backend.knobs['power'].power_default = 20
        reloaded = base.engine.Engine(self.backend, self.path, policy)
        self.assertEqual(self.backend.knobs['power'].power_default, 15)
        reloaded.reset()

    def test_missing_journal_reset_still_acquires_transaction_lock(self):
        with patch.object(base.engine, 'STATE', self.path.parent), \
                patch.object(base.engine.fcntl, 'flock', side_effect=BlockingIOError('busy')):
            with self.assertRaises(BlockingIOError):
                base.engine.execute('intel', 'reset')

    def test_application_clocks_and_offsets_rejected_together(self):
        key = 'GPU-00000000'
        self.backend.add(key + '/APPLICATION_CLOCKS_MHZ', 'APPLICATION_CLOCKS_MHZ', 20)
        self.backend.add(key + '/GPU_OFFSET_MHZ', 'GPU_OFFSET_MHZ', 0)
        settings = {'APPLICATION_CLOCKS_MHZ': ('30',) * 4, 'GPU_OFFSET_MHZ': ('10',) * 4}
        with self.assertRaisesRegex(base.common.TuningError, 'choose application clocks'):
            self.transaction(settings).apply('high', settings)
        self.assertFalse(self.backend.writes)


class IntelSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file('proc/cpuinfo', 'vendor_id : GenuineIntel\nphysical id : 0')

    def file(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content) + '\n')
        return path

    def hardware(self):
        self.file('sys/devices/system/cpu/intel_pstate/max_perf_pct', 100)
        return base.intel.Backend(self.root)

    def test_active_policy_owner_blocks_before_hardware_write(self):
        hardware = self.hardware()
        settings = {'CPU_MAX_PERF_PCT': ('55',) * 4}
        tx = base.engine.Engine(hardware, self.root / 'journal.json', base.simple_policy(settings))
        with patch.object(system_state, 'power_managers', return_value={'power-profiles-daemon.service': 'active'}):
            with self.assertRaisesRegex(base.common.TuningError, 'one policy owner'):
                tx.apply('silent', settings)
        self.assertEqual(next(iter(hardware.knobs.values())).read(), 100)
        self.assertFalse(tx.path.exists())

    def test_unknown_policy_bus_fails_closed(self):
        hardware = self.hardware()
        with patch.object(system_state, 'power_managers', side_effect=base.common.TuningError('system bus unavailable')):
            with self.assertRaisesRegex(base.common.TuningError, 'system bus unavailable'):
                hardware.check_ownership(dict.fromkeys(hardware.knobs, 55))

    def test_inactive_failed_and_absent_owners_allowed_thermald_excluded(self):
        hardware = self.hardware()
        with patch.object(system_state, 'power_managers', return_value={'a': 'inactive', 'b': 'failed', 'c': 'not-loaded'}):
            hardware.check_ownership(dict.fromkeys(hardware.knobs, 55))
        self.assertNotIn('thermald.service', system_state.POWER_MANAGERS)

    def test_gpu_only_values_do_not_query_cpu_policy_owner(self):
        hardware = self.hardware()
        hardware.knobs['gpu'] = base.common.Knob('gpu', 'GPU_MAX_FREQ_MHZ', lambda: 100, lambda v: None, 100, 200)
        with patch.object(system_state, 'power_managers') as query:
            hardware.check_ownership({'gpu': 200})
        query.assert_not_called()

    def test_owner_appearance_detected_during_health(self):
        b = base.FakeBackend()
        b.add('cpu', 'CPU_MAX_PERF_PCT', 100)
        settings = {'CPU_MAX_PERF_PCT': ('55',) * 4}
        tx = base.engine.Engine(b, self.root / 'journal.json', base.simple_policy(settings))
        tx.apply('silent', settings)
        b.check_ownership = lambda values: (_ for _ in ()).throw(base.common.TuningError('competing manager appeared'))
        self.assertIn('competing manager appeared', tx.health()['conflicts'])

    def test_readonly_attribute_not_offered(self):
        path = self.file('sys/devices/system/cpu/intel_pstate/no_turbo', 0)
        path.chmod(0o444)
        hardware = self.hardware()
        self.assertNotIn('CPU_NO_TURBO', {k.setting for k in hardware.knobs.values()})
        self.assertTrue(any('read-only' in s for s in hardware.unavailable))

    def test_generic_powersave_is_not_an_adaptive_fallback(self):
        prefix = 'sys/devices/system/cpu/cpufreq/policy0/'
        for name, value in {'scaling_driver': 'acpi-cpufreq', 'scaling_available_governors': 'performance powersave', 'scaling_governor': 'performance'}.items():
            self.file(prefix + name, value)
        hardware = self.hardware()
        knob = next(k for k in hardware.knobs.values() if k.setting == 'CPU_GOVERNOR')
        self.assertNotIn('adaptive', knob.symbols)
        with self.assertRaises(base.common.TuningError):
            knob.resolve('adaptive', base.simple_policy({}))

    def test_rapl_named_nested_flat_alias_deduplicated_zero_bound_unknown(self):
        path = 'sys/class/powercap/intel-rapl/intel-rapl:0/'
        for name, value in {'name': 'package-0', 'constraint_7_name': 'long_term', 'constraint_7_power_limit_uw': 15000000,
                            'constraint_7_min_power_uw': 0, 'constraint_7_max_power_uw': 28000000}.items():
            self.file(path + name, value)
        (self.root / 'sys/class/powercap/intel-rapl:0').symlink_to('intel-rapl/intel-rapl:0')
        hardware = self.hardware()
        knobs = [k for k in hardware.knobs.values() if k.setting == 'RAPL_PL1_POWER_UW']
        self.assertEqual(len(knobs), 1)
        self.assertIn('constraint_7_', knobs[0].id)
        self.assertIsNone(knobs[0].minimum)

    def test_disabled_mmio_rapl_not_enabled_or_tuned(self):
        prefix = 'sys/class/powercap/intel-rapl-mmio/intel-rapl-mmio:0/'
        for name, value in {'name': 'package-0', 'enabled': 0, 'constraint_0_name': 'long_term', 'constraint_0_power_limit_uw': 15000000}.items():
            self.file(prefix + name, value)
        hardware = self.hardware()
        self.assertFalse(any(k.setting.startswith('RAPL_') for k in hardware.knobs.values()))
        self.assertTrue(any('zone disabled' in s for s in hardware.unavailable))

    def test_uncore_cluster_preferred_over_package_aggregate(self):
        for directory in ('package_00_die_00', 'uncore00', 'uncore01'):
            for name, value in {'min_freq_khz': 400000, 'max_freq_khz': 2000000, 'initial_min_freq_khz': 400000, 'initial_max_freq_khz': 2000000}.items():
                self.file('sys/devices/system/cpu/intel_uncore_frequency/' + directory + '/' + name, value)
        knobs = [k for k in self.hardware().knobs.values() if k.setting.startswith('UNCORE_')]
        self.assertEqual(len(knobs), 4)
        self.assertFalse(any('package_00' in k.id for k in knobs))

    def test_thermal_coverage_requires_every_cpu_package(self):
        self.file('proc/cpuinfo', 'vendor_id : GenuineIntel\nphysical id : 0\nvendor_id : GenuineIntel\nphysical id : 1')
        self.file('sys/class/hwmon/hwmon0/name', 'coretemp')
        self.file('sys/class/hwmon/hwmon0/temp1_input', 40000)
        hardware = self.hardware()
        self.assertIsNone(hardware.temperature())
        self.file('sys/class/hwmon/hwmon1/name', 'coretemp')
        sensor = self.file('sys/class/hwmon/hwmon1/temp1_input', 70000)
        self.assertEqual(hardware.temperature(), 70.0)
        sensor.write_text('invalid\n')
        self.assertIsNone(hardware.temperature())

    def test_platform_inventory_is_read_only_and_omits_serials(self):
        pci = 'sys/bus/pci/devices/0000:00:02.0/'
        self.file(pci + 'vendor', '0x8086')
        power = self.file(pci + 'power/control', 'auto')
        self.file(pci + 'serial', 'private-serial')
        self.file('sys/bus/thunderbolt/devices/domain0/security', 'user')
        self.file('sys/bus/thunderbolt/devices/domain0/iommu_dma_protection', 1)
        report = system_state.platform_report(self.root)
        self.assertTrue(report['read_only'])
        self.assertNotIn('private-serial', json.dumps(report))
        self.assertEqual(report['thunderbolt']['domain0']['iommu_dma_protection'], '1')
        self.assertEqual(power.read_text(), 'auto\n')


class NvidiaCostTests(unittest.TestCase):
    UUID = 'GPU-00000000-1111-2222-3333-444444444444'

    def test_health_power_inventory_does_not_scan_clocks_or_offsets(self):
        api = base.FakeNVML()
        with patch.object(api, 'clocks', side_effect=AssertionError('expensive clock scan')):
            hardware = base.nvidia.Backend(api, wanted={self.UUID + '/POWER_LIMIT_MW'})
        self.assertEqual(set(hardware.knobs), {self.UUID + '/POWER_LIMIT_MW'})
        self.assertFalse(any('Offset' in name for name, *_ in api.calls))
        hardware.close()

    def test_health_offset_probes_only_owned_pstate(self):
        api = base.FakeNVML()
        hardware = base.nvidia.Backend(api, wanted={self.UUID + '/GPU_OFFSET_MHZ/P0'})
        self.assertEqual(sum(name == 'nvmlDeviceGetClockOffsets' for name, *_ in api.calls), 1)
        hardware.close()

    def test_constructor_failure_closes_nvml(self):
        api = base.FakeNVML()
        with patch.object(api, 'text', return_value='not-a-physical-uuid'):
            with self.assertRaises(base.common.TuningError):
                base.nvidia.Backend(api)
        self.assertEqual(sum(name == 'nvmlShutdown' for name, *_ in api.calls), 1)

    def test_oversized_clock_table_is_not_silently_truncated(self):
        api = base.FakeNVML()
        with patch.object(api, 'clocks', return_value=list(range(257))) as clocks:
            hardware = base.nvidia.Backend(api)
        self.assertEqual(clocks.call_count, 1)
        self.assertTrue(any('no truncated table' in s for s in hardware.unavailable))
        self.assertFalse(any(k.setting == 'APPLICATION_CLOCKS_MHZ' for k in hardware.knobs.values()))
        hardware.close()

    def test_close_is_idempotent(self):
        api = base.FakeNVML()
        hardware = base.nvidia.Backend(api, wanted=set())
        hardware.close()
        hardware.close()
        self.assertEqual(sum(name == 'nvmlShutdown' for name, *_ in api.calls), 1)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.b = base.FakeBroker()
        p = patch.object(base.broker, 'on_ac', return_value=True)
        p.start()
        self.addCleanup(p.stop)

    async def test_resume_does_not_clear_safely_recovered_thermal_fault(self):
        self.b.selection.automatic = True
        self.b.selection.faults['intel'] = 'thermal interlock'
        await self.b.action({'action': 'pause'}, 0)
        await self.b.action({'action': 'resume'}, 0)
        self.assertIn('intel', self.b.selection.faults)
        self.assertFalse(any(v == 'intel' and a == 'apply' for v, a, _ in self.b.calls))

    async def test_unrecoverable_device_not_hammered_by_periodic_poll(self):
        self.b.fail = ('intel', 'reset')
        await self.b.fault('intel', base.common.TuningError('failed write'))
        count = len(self.b.calls)
        for _ in range(5):
            await self.b.reconcile(health=True)
        self.assertEqual(len(self.b.calls), count)
        self.assertIn('intel', self.b.status()['recovery_pending'])
        self.b.fail = None
        await self.b.action({'action': 'pause'}, 0)
        self.assertFalse(self.b.recovery_pending)

    async def test_busy_lock_does_not_execute_or_release_someone_elses_lock(self):
        await self.b.lock.acquire()
        original = asyncio.wait_for
        async def shortened(awaitable, timeout):
            return await original(awaitable, 0.001)
        with patch.object(base.broker.asyncio, 'wait_for', side_effect=shortened):
            with self.assertRaisesRegex(base.common.TuningError, 'request was not executed'):
                async with self.b.control_lock():
                    self.fail('busy request executed')
        self.assertTrue(self.b.lock.locked())
        self.b.lock.release()

    async def test_restart_without_active_seat_does_not_restore_manual_selection(self):
        with base.private_temp() as temporary:
            root = Path(temporary)
            base.common.atomic_json(root / 'controls.json', {'version': 1, 'automatic': False, 'manual': {'intel': 'high', 'nvidia': None}, 'paused': False, 'faults': {}})
            self.b.seat.present = False
            with patch.object(base.broker, 'STATE', root):
                self.b.load()
        self.assertEqual(self.b.selection.manual, {'intel': None, 'nvidia': None})


class PolicyAndPowerTests(unittest.TestCase):
    def test_unknown_selected_vendor_field_rejected(self):
        env = base.environment()
        env['HARDWARE_INTEL_CPU_TUNING_HIGH_CPU_EPPS'] = 'performance'
        with self.assertRaisesRegex(ValueError, 'unknown hardware policy'):
            base.installer.policy(env, 'intel', base.intel.SETTINGS)

    def test_unknown_common_field_rejected_before_install(self):
        env = base.environment()
        env['HARDWARE_TUNING_IDLE_ACC'] = 'balanced'
        with base.private_temp() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, 'unknown common'):
                base.installer.install(root, 1000, 1000, env, ['intel'])
            self.assertEqual(list(root.iterdir()), [])

    def test_sleep_with_safe_historical_fault_succeeds_but_pending_recovery_fails(self):
        status = {'faults': {'intel': 'thermal'}, 'owns_controls': {'intel': False}, 'recovery_pending': []}
        with patch.object(base.client, 'request', return_value=status), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(base.client.main(['pause']), 0)
            self.assertEqual(base.client.main(['resume']), 0)
            status['recovery_pending'] = ['intel']
            self.assertEqual(base.client.main(['pause']), 1)
            self.assertEqual(base.client.main(['resume']), 1)

    def test_unknown_laptop_ac_is_battery_desktop_without_battery_is_ac(self):
        with base.private_temp() as temporary:
            root = Path(temporary)
            self.assertTrue(base.broker.on_ac(root))
            (root / 'BAT0').mkdir()
            (root / 'BAT0/type').write_text('Battery\n')
            self.assertFalse(base.broker.on_ac(root))
            (root / 'AC').mkdir()
            (root / 'AC/type').write_text('USB_PD_DRP\n')
            (root / 'AC/online').write_text('1\n')
            self.assertTrue(base.broker.on_ac(root))


@unittest.skipUnless(shutil.which('dbus-daemon') and shutil.which('cc'), 'private D-Bus ABI fixture needs dbus-daemon and C compiler')
class SystemBusIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = base.private_temp()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / 'bus-peer'
        command = ['cc', '-Wall', '-Wextra', '-Werror', str(base.FORKY / 'tests/fixtures/hardware-policy-bus.c'), '-Wl,-l:libsystemd.so.0', '-o', str(self.binary)]
        subprocess.run(command, check=True, capture_output=True, timeout=20)
        self.daemon = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1', '--address=unix:path=' + str(self.root / 'bus')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.close, self.daemon)
        self.assertTrue(select.select([self.daemon.stdout], [], [], 5)[0], 'private bus startup timeout')
        address = self.daemon.stdout.readline().strip()
        self.env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=address, PYTHONDONTWRITEBYTECODE='1')

    @staticmethod
    def close(process):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()

    def query(self, state):
        peer = subprocess.Popen([str(self.binary), state], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.close, peer)
        self.assertTrue(select.select([peer.stdout], [], [], 5)[0], 'private service startup timeout')
        self.assertEqual(peer.stdout.readline().strip(), 'ready')
        code = 'import sys,json; sys.path.insert(0, sys.argv[1]); import system_state; print(json.dumps(system_state.power_managers()))'
        return subprocess.run([sys.executable, '-B', '-c', code, str(base.LIB)], env=self.env, capture_output=True, text=True, timeout=5)

    def test_real_typed_properties_path_encoding_and_missing_unit(self):
        result = self.query('active')
        self.assertEqual(result.returncode, 0, result.stderr)
        states = json.loads(result.stdout)
        self.assertEqual(states['power-profiles-daemon.service'], 'active')
        self.assertEqual(states['tlp.service'], 'inactive')
        self.assertEqual(states['ondemand.service'], 'not-loaded')
        self.assertEqual(set(states), set(system_state.POWER_MANAGERS))

    def test_property_access_denial_is_not_treated_as_inactive(self):
        result = self.query('denied')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fixture access denied', result.stderr)

    def test_malformed_property_value_rejected(self):
        result = self.query('active;exec')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid policy-owner reply', result.stderr)

    def test_property_query_is_bounded(self):
        result = self.query('timeout')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cannot verify CPU policy owner', result.stderr)


if __name__ == '__main__':
    unittest.main()
