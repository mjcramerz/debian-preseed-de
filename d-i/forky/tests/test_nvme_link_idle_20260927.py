"""Offline sysfs fixtures only: no PCI writes, NVMe commands, or udev events."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'hooks/target'
HELPER = TARGET / 'usr/local/sbin/nvme-pcie-status'
RULE = TARGET / 'etc/udev/rules.d/74-nvme-link-idle.rules'


@unittest.skipUnless(os.geteuid() == 0, 'root-owned sysfs fixture metadata required')
class NVMeStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tree = self.root / 'devices'
        self.bus = self.root / 'bus'
        self.tree.mkdir()
        self.bus.mkdir()
        self.m = types.ModuleType('nvme_status_fixture')
        exec(compile(HELPER.read_bytes(), str(HELPER), 'exec'), self.m.__dict__)
        self.m.PCI_ROOT, self.m.DEVICE_ROOT = self.bus, self.tree
        self.m.NVME_LATENCY = self.root / 'nvme-latency'

    def device(self, address='0000:2e:00.0', vendor='0x15b7', product='0x5006', cls='0x010802'):
        dev = self.tree / 'pci0000:00' / address
        dev.mkdir(parents=True)
        (self.bus / address).symlink_to(dev, target_is_directory=True)
        for name, value in {'vendor': vendor, 'device': product, 'class': cls}.items():
            (dev / name).write_text(value + '\n')
        return dev

    def test_no_matching_device_does_not_claim_hardware_health(self):
        self.device(product='0x5007')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(self.m.main([]), 0)
        self.assertEqual(json.loads(output.getvalue()), {'devices': [], 'hardware_health_verified': False})

    def test_firmware_owned_controls_and_missing_counters_remain_unknown(self):
        self.device()
        record, = self.m.snapshot()
        self.assertEqual(record['policy_state'], 'unavailable-kernel-or-firmware-owned')
        self.assertEqual(record['link_idle_enabled'], dict.fromkeys(self.m.CONTROLS))
        self.assertIsNone(record['aer_correctable'])

    def test_disabled_controls_keep_aer_evidence_and_never_mutate_files(self):
        dev = self.device()
        link = dev / 'link'; link.mkdir()
        for name in self.m.CONTROLS:
            (link / name).write_text('0\n')
        (dev / 'aer_dev_correctable').write_text('RxErr 6\nBadTLP 0\nTOTAL_ERR_COR 6\n')
        (dev / 'current_link_speed').write_text('8.0 GT/s PCIe\n')
        (dev / 'current_link_width').write_text('4\n')
        before = {p: p.read_bytes() for p in dev.rglob('*') if p.is_file()}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.m.main([])
        result = json.loads(output.getvalue())
        record, = result['devices']
        self.assertFalse(result['hardware_health_verified'])
        self.assertEqual(record['policy_state'], 'available-controls-disabled')
        self.assertIn('RxErr 6', record['aer_correctable'])
        self.assertEqual(record['current_link_width'], '4')
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_partial_controls_do_not_invent_missing_capabilities(self):
        dev = self.device(); (dev / 'link').mkdir()
        (dev / 'link/l1_aspm').write_text('1\n')
        record, = self.m.snapshot()
        self.assertEqual(record['policy_state'], 'link-idle-still-enabled')
        self.assertIsNone(record['link_idle_enabled']['l0s_aspm'])
        self.assertTrue(record['link_idle_enabled']['l1_aspm'])

    def test_firmware_and_upstream_errors_are_read_without_identifiers_or_writes(self):
        bridge = self.tree / 'pci0000:00' / '0000:00:1d.4'
        bridge.mkdir(parents=True)
        (bridge / 'class').write_text('0x060400\n')
        (bridge / 'aer_dev_correctable').write_text('RxErr 9\n')
        (bridge / 'current_link_width').write_text('4\n')
        dev = bridge / '0000:2e:00.0'; dev.mkdir()
        (self.bus / dev.name).symlink_to(dev, target_is_directory=True)
        for name, value in {'vendor': '0x15b7', 'device': '0x5006', 'class': '0x010802'}.items():
            (dev / name).write_text(value + '\n')
        controller = dev / 'nvme' / 'nvme0'; controller.mkdir(parents=True)
        for name, value in {'model': 'WDC PC SN730', 'firmware_rev': '11170101',
                            'serial': 'must-not-collect'}.items():
            (controller / name).write_text(value + '\n')
        self.m.NVME_LATENCY.write_text('3200\n')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        record, = self.m.snapshot()
        self.assertEqual(record['controllers'], [dict(controller='nvme0', model='WDC PC SN730',
                                                      firmware_revision='11170101')])
        self.assertEqual(record['upstream_bridge']['pci_address'], bridge.name)
        self.assertEqual(record['upstream_bridge']['aer_dev_correctable'], 'RxErr 9')
        self.assertEqual(record['nvme_default_ps_max_latency_us'], '3200')
        self.assertIn('cannot verify', record['policy_note'])
        self.assertNotIn('must-not-collect', json.dumps(record))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_controller_directory_symlink_is_not_followed(self):
        dev = self.device()
        (dev / 'nvme').mkdir()
        private = self.root / 'private'; private.mkdir()
        (dev / 'nvme/nvme0').symlink_to(private, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe NVMe controller'):
            self.m.snapshot()

    def test_invalid_latency_value_is_rejected(self):
        self.device()
        self.m.NVME_LATENCY.write_text('not-a-number\n')
        with self.assertRaisesRegex(ValueError, 'latency'):
            self.m.snapshot()

    def test_exact_pci_class_required(self):
        self.device(cls='0x010601')
        self.assertEqual(self.m.snapshot(), [])

    def test_unexpected_link_control_fails(self):
        dev = self.device(); (dev / 'link').mkdir()
        (dev / 'link/l1_aspm').write_text('2\n')
        with self.assertRaisesRegex(ValueError, 'invalid link control'):
            self.m.snapshot()

    def test_redirected_link_directory_is_rejected(self):
        dev = self.device()
        (dev / 'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.m.snapshot()

    def test_attribute_symlink_is_not_followed(self):
        dev = self.device()
        victim = self.root / 'secret'; victim.write_text('private')
        (dev / 'aer_dev_correctable').symlink_to(victim)
        with self.assertRaises(OSError):
            self.m.snapshot()
        self.assertEqual(victim.read_text(), 'private')

    def test_escape_from_kernel_device_tree_is_rejected(self):
        dev = self.device()
        outside = self.root / dev.name; outside.mkdir()
        (self.bus / dev.name).unlink()
        (self.bus / dev.name).symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            self.m.snapshot()

    def test_oversized_attribute_is_rejected(self):
        dev = self.device()
        (dev / 'aer_dev_correctable').write_text('x' * 8193)
        with self.assertRaisesRegex(ValueError, 'oversized'):
            self.m.snapshot()

    def test_non_root_attribute_is_rejected(self):
        self.device()
        # Some disposable runners map only one UID, so chown on the fixture
        # cannot represent a foreign owner. Exercise the fstat boundary itself.
        foreign = types.SimpleNamespace(st_mode=stat.S_IFREG, st_uid=12345)
        with patch.object(self.m.os, 'fstat', return_value=foreign):
            with self.assertRaisesRegex(ValueError, 'unsafe sysfs'):
                self.m.snapshot()

    def test_arguments_cannot_select_paths_or_write_modes(self):
        with patch.object(self.m, 'snapshot') as snapshot:
            for args in (['--apply'], ['/tmp/alternate-sysfs'], ['--reset']):
                with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'read-only'):
                    self.m.main(args)
            snapshot.assert_not_called()


class NVMeRuleTests(unittest.TestCase):
    def test_rule_is_exact_and_never_hides_aer_or_requests_firmware_control(self):
        text = RULE.read_text()
        for guard in ('SUBSYSTEM!="pci"', 'ATTR{vendor}!="0x15b7"',
                      'ATTR{device}!="0x5006"', 'ATTR{class}!="0x010802"'):
            self.assertIn(guard, text)
        active = '\n'.join(line for line in text.splitlines() if not line.startswith('#'))
        for name in ('l0s_aspm', 'l1_2_aspm', 'l1_1_aspm',
                     'l1_2_pcipm', 'l1_1_pcipm', 'l1_aspm', 'clkpm'):
            self.assertIn(f'TEST=="link/{name}", ATTR{{link/{name}}}="0"', active)
        for prohibited in ('RUN', 'SYSTEMD_WANTS', 'setpci', 'noaer', 'reset', 'power/control', 'pcie_aspm=force'):
            self.assertNotIn(prohibited, active)

    def test_shared_staging_covers_both_filesystem_families(self):
        stage = (ROOT / 'scripts/late/storage-maintenance.sh').read_text()
        self.assertIn('etc/udev/rules.d/74-nvme-link-idle.rules', stage)
        self.assertIn('usr/local/sbin/nvme-pcie-status', stage)
        for family in ('btrfs', 'f2fs'):
            source = (ROOT / f'scripts/late/{family}-family.sh').read_text()
            self.assertIn('stage_target_common_storage_maintenance_assets', source)

    def test_failed_nvme_asset_publication_stops_shared_staging(self):
        # All writes are stubbed. In particular, never stage into the host /target.
        script = r"""
. "$1"
fail_at=$2
calls=0
advanced=0
installer_repo_join_var() { printf '%s\n' "$2"; }
stage_target_asset() { calls=$((calls + 1)); [ "$calls" -ne "$fail_at" ]; }
stage_target_systemd_resource_policy_assets() { advanced=1; return 1; }
if stage_target_common_storage_maintenance_assets; then exit 80; fi
[ "$calls" -eq "$fail_at" ] && [ "$advanced" -eq 0 ]
"""
        shells = [['/bin/sh']]
        if shutil.which('dash'):
            shells.append([shutil.which('dash')])
        if shutil.which('busybox'):
            shells.append([shutil.which('busybox'), 'ash'])
        for shell in shells:
            for fail_at in (1, 2):
                with self.subTest(shell=shell, fail_at=fail_at):
                    result = subprocess.run(shell + ['-c', script, 'nvme-staging-fixture',
                        str(ROOT / 'scripts/late/storage-maintenance.sh'), str(fail_at)],
                        capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('udevadm'), 'udevadm unavailable')
    def test_rule_parses_without_triggering_devices(self):
        result = subprocess.run(['udevadm', 'verify', str(RULE)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
