"""Boot and runtime policy are distinct; these tests exercise runtime capabilities."""
from pathlib import Path
import unittest
from unittest import mock
import test_hardware_tuning_20260916 as fixture


class IntelPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = fixture.private_temp(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file('proc/cpuinfo', 'vendor_id : GenuineIntel\n')

    def file(self, relative, value):
        path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + '\n')

    def discover(self, driver='intel_pstate', governors='powersave performance',
                 preferences='performance balance_performance balance_power power', boost=True):
        base = 'sys/devices/system/cpu/cpufreq/policy0/'
        for name, value in {'scaling_driver': driver, 'scaling_available_governors': governors,
                            'scaling_governor': governors.split()[0],
                            'energy_performance_available_preferences': preferences,
                            'energy_performance_preference': preferences.split()[0]}.items():
            self.file(base + name, value)
        if boost: self.file('sys/devices/system/cpu/intel_pstate/hwp_dynamic_boost', '0')
        return {k.setting: k for k in fixture.intel.Backend(self.root).knobs.values()}

    def test_hwp_matrix_and_retained_limits(self):
        settings = fixture.intel.SETTINGS
        self.assertEqual(settings['CPU_HWP_DYNAMIC_BOOST'], ('1', '1', '1', '0'))
        self.assertEqual(settings['CPU_EPB'], ('0', '4', '6', '15'))
        self.assertEqual(settings['CPU_MAX_PERF_PCT'], ('100', '100', '100', '55'))
        self.assertEqual(settings['CPU_NO_TURBO'], ('0', '0', '0', '1'))

    def test_all_thirteen_profiles_explicit_balanced_boost(self):
        paths = list((fixture.FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(paths), 13)
        key = 'HARDWARE_INTEL_CPU_TUNING_BALANCED_CPU_HWP_DYNAMIC_BOOST'
        for path in paths:
            self.assertEqual(path.read_text().count(key + '="1"'), 1)
            self.assertEqual(path.read_text().count(key + '='), 1)
            policy = fixture.installer.policy(fixture.environment(path.stem), 'intel', fixture.intel.SETTINGS)
            self.assertEqual(policy['profiles']['balanced']['knobs']['CPU_EPP'], 'balanced')

    def test_balanced_prefers_advertised_balance_power(self):
        epp = self.discover()['CPU_EPP']
        self.assertEqual(epp.resolve('balanced', {}), 'balance_power')

    def test_balanced_fallback_is_advertised_balance_performance_only(self):
        epp = self.discover(preferences='performance balance_performance power')['CPU_EPP']
        self.assertEqual(epp.resolve('balanced', {}), 'balance_performance')
        with self.assertRaises(fixture.common.TuningError): epp.resolve('balance_power', {})
        epp = self.discover(preferences='performance power')['CPU_EPP']
        with self.assertRaises(fixture.common.TuningError): epp.resolve('balanced', {})

    def test_invalid_configured_epp_never_falls_back(self):
        epp = self.discover()['CPU_EPP']
        with self.assertRaises(fixture.common.TuningError): epp.resolve('garbage', {})
        policy = fixture.simple_policy(fixture.intel.SETTINGS)
        policy['profiles']['balanced']['knobs']['CPU_EPP'] = 'garbage'
        with self.assertRaises(fixture.common.TuningError): fixture.common.validate_policy(policy, fixture.intel.SETTINGS)
        policy['profiles']['balanced']['knobs']['CPU_EPP'] = 'balance_power'
        fixture.common.validate_policy(policy, fixture.intel.SETTINGS)

    def test_active_adaptive_is_powersave(self):
        self.assertEqual(self.discover()['CPU_GOVERNOR'].resolve('adaptive', {}), 'powersave')

    def test_passive_and_generic_adaptive_are_schedutil_with_deliberate_fallback(self):
        for driver in ('intel_cpufreq', 'acpi-cpufreq'):
            self.assertEqual(self.discover(driver, 'powersave performance schedutil ondemand')['CPU_GOVERNOR'].resolve('adaptive', {}), 'schedutil')
            self.assertEqual(self.discover(driver, 'powersave performance ondemand')['CPU_GOVERNOR'].resolve('adaptive', {}), 'ondemand')

    def test_boost_optional_but_supported_write_is_verified(self):
        self.assertNotIn('CPU_HWP_DYNAMIC_BOOST', self.discover(boost=False))
        boost = self.discover()['CPU_HWP_DYNAMIC_BOOST']
        wanted = boost.resolve(fixture.intel.SETTINGS['CPU_HWP_DYNAMIC_BOOST'][2], {})
        self.assertEqual(wanted, 1)
        boost.write(wanted); self.assertEqual(boost.read(), 1)
        # The production transaction engine independently tests rollback/readback.
        with mock.patch.object(fixture.intel.os, 'open', side_effect=PermissionError('supported write denied')):
            with self.assertRaises((PermissionError, fixture.common.TuningError)):
                boost.write(0)


if __name__ == '__main__': unittest.main()
