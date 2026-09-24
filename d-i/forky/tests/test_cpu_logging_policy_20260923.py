"""CPU/IO gates are independent; full directives validate even while disabled."""
from __future__ import annotations

from itertools import product
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import unittest

from payload_fixture import read_text
import test_systemd_resource_policy as resources
from test_systemd_resource_policy import PROFILES, TEMPLATES


class ConditionalCPUWeightTests(unittest.TestCase):
    def shell(self, *args, **kwargs):
        return resources.ResourcePolicyTests().shell(*args, **kwargs)

    def test_all_ten_profiles_all_four_independent_modes(self):
        for profile, cpu, io in product(PROFILES, ('true', 'false'), ('true', 'false')):
            with self.subTest(profile=profile.name, cpu=cpu, io=io), tempfile.TemporaryDirectory() as temp:
                file = Path(temp) / 'policy'
                file.write_text('\n'.join(read_text(path) for path in TEMPLATES))
                self.shell('TMP_ENV_DIR=' + shlex.quote(temp) + '\napply_systemd_resource_placeholders ' + shlex.quote(str(file)),
                           profile=profile, override=f'SYSTEMD_CPUWEIGHT_ENABLE={cpu}\nSYSTEMD_IOWEIGHT_ENABLE={io}')
                result = file.read_text()
                self.assertEqual(re.findall(r'^CPUWeight=(\d+)$', result, re.M),
                                 ['200', '100', '30', '300', '30', '50', '200', '200', '200'] if cpu == 'true' else [])
                self.assertEqual(re.findall(r'^IOWeight=(\d+)$', result, re.M),
                                 ['200', '100', '30', '300', '30', '50'] if io == 'true' else [])
                self.assertNotIn('__SYSTEMD_', result)
                self.assertNotRegex(result, r'(?m)^(?:CPU|IO)Weight=$')

    def test_invalid_and_missing_cpu_values_fail_even_when_disabled(self):
        key = 'SYSTEMD_CPUWEIGHT_USER_AUDIO_SERVICE_D'
        for enabled, setting in product(('true', 'false'), (
                'unset ' + key, key + '=200', key + '=CPUWeight=0', key + '=CPUWeight=10001',
                key + '=CPUWeight=0200', key + '=' + shlex.quote('CPUWeight=200\nExecStart=/bin/false'))):
            with self.subTest(enabled=enabled, setting=setting):
                result = self.shell('systemd_resource_placeholder_map',
                                    override=f'SYSTEMD_CPUWEIGHT_ENABLE={enabled}\n{setting}', check=False)
                self.assertNotEqual(result.returncode, 0)

    def test_empty_individual_cpu_directive_is_allowed(self):
        result = self.shell('systemd_resource_placeholder_map',
                            override='SYSTEMD_CPUWEIGHT_USER_AUDIO_SERVICE_D=""')
        self.assertIn('SYSTEMD_CPUWEIGHT_USER_AUDIO_SERVICE_D=\n', result.stdout)

    def test_both_shells_agree_for_all_gate_combinations(self):
        if not shutil.which('busybox'):
            self.skipTest('BusyBox is unavailable')
        for cpu, io in product(('true', 'false'), repeat=2):
            override = f'SYSTEMD_CPUWEIGHT_ENABLE={cpu}\nSYSTEMD_IOWEIGHT_ENABLE={io}'
            self.assertEqual(self.shell('systemd_resource_placeholder_map', override=override).stdout,
                             self.shell('systemd_resource_placeholder_map', override=override, shell='busybox').stdout)

    def test_disabled_cpu_removes_literal_startup_directives_not_io(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / 'policy'
            file.write_text('[Slice]\nCPUWeight=500\nStartupCPUWeight=900\nIOWeight=150\nStartupIOWeight=250\n')
            self.shell('TMP_ENV_DIR=' + shlex.quote(temp) + '\napply_systemd_resource_placeholders ' + shlex.quote(str(file)),
                       override='SYSTEMD_CPUWEIGHT_ENABLE=false\nSYSTEMD_IOWEIGHT_ENABLE=true')
            self.assertEqual(file.read_text(), '[Slice]\nIOWeight=150\nStartupIOWeight=250\n')


if __name__ == '__main__':
    unittest.main()
