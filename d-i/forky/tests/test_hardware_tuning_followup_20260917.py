"""Follow-up safety regressions; no real GPU, service, or sysfs mutation."""
from __future__ import annotations
from payload_fixture import source_exists as payload_source_exists

import unittest
from unittest.mock import patch

import test_hardware_tuning_20260916 as base


class MultipleGpuTemperatureTests(unittest.TestCase):
    def hardware(self, readings):
        hardware = object.__new__(base.nvidia.Backend)
        hardware.handles = list(range(len(readings)))
        hardware.unavailable = []
        hardware.api = base.FakeNVML()
        def scalar(name, handle, *extra):
            self.assertEqual(name, 'nvmlDeviceGetTemperature')
            value = readings[handle]
            if value is None:
                raise base.common.TuningError('sensor unavailable')
            return value
        hardware.api.scalar = scalar
        return hardware

    def test_complete_sensor_coverage_uses_hottest_gpu(self):
        self.assertEqual(self.hardware([35, 72, 48]).temperature(), 72.0)

    def test_partial_sensor_coverage_is_unknown_not_the_other_gpu_temperature(self):
        for readings in ([35, None], [None, 35], [35, 0], [35, 150]):
            with self.subTest(readings=readings):
                self.assertIsNone(self.hardware(readings).temperature())

    def test_no_readable_gpu_temperature_remains_unknown(self):
        self.assertIsNone(self.hardware([None, None]).temperature())

    def test_missing_one_sensor_blocks_positive_offset_before_any_write(self):
        backend = base.FakeBackend()
        backend.add('GPU-a/GPU_OFFSET_MHZ/P0', 'GPU_OFFSET_MHZ', 0,
                    low=-200, high=200, overclock=True)
        settings = {'GPU_OFFSET_MHZ': ('50',) * 4}
        policy = base.simple_policy(settings)
        policy['allow_overclock'] = True
        sensors = self.hardware([35, None])
        with base.private_temp() as temporary, patch.object(backend, 'temperature', sensors.temperature):
            transaction = base.engine.Engine(backend, base.Path(temporary)/'journal.json', policy)
            with self.assertRaisesRegex(base.common.TuningError, 'readable temperature sensor'):
                transaction.apply('high', settings)
            self.assertEqual(backend.writes, [])
            self.assertFalse(payload_source_exists(transaction.path))

    def test_sensor_loss_on_one_gpu_trips_owned_overclock_health_interlock(self):
        backend = base.FakeBackend()
        backend.add('GPU-a/GPU_OFFSET_MHZ/P0', 'GPU_OFFSET_MHZ', 0,
                    low=-200, high=200, overclock=True)
        settings = {'GPU_OFFSET_MHZ': ('50',) * 4}
        policy = base.simple_policy(settings)
        policy['allow_overclock'] = True
        with base.private_temp() as temporary:
            transaction = base.engine.Engine(backend, base.Path(temporary)/'journal.json', policy)
            transaction.apply('high', settings)
            with patch.object(backend, 'temperature', self.hardware([35, None]).temperature):
                self.assertIn('thermal sensor disappeared', '; '.join(transaction.health()['conflicts']))
            transaction.reset()
            self.assertEqual(backend.values['GPU-a/GPU_OFFSET_MHZ/P0'], 0)


if __name__ == '__main__':
    unittest.main()
