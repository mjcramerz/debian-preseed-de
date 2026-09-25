"""Focused contracts for greeter classes, battery output and audit routing."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'hooks/target'


def source(relative: str) -> str:
    path = TARGET / relative
    template = path.with_name(path.name + '.tmpl')
    return (template if template.exists() else path).read_text()


class BatteryOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = TARGET / 'usr/local/libexec/labwc-waybar-battery'
        loader = importlib.machinery.SourceFileLoader('managed_waybar_battery', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.battery = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.battery)

    def device(self, root: Path, name: str, **values: str) -> None:
        path = root / name
        path.mkdir()
        for key, value in values.items():
            (path / key).write_text(value + '\n', encoding='ascii')

    def test_absent_battery_is_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            value = self.battery.output(Path(temp))
            self.assertEqual((value['text'], value['alt']), ('—', 'default'))

    def test_plugged_and_low_capacity_preserve_style(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.device(root, 'BAT0', type='Battery', capacity='12', status='Not charging')
            self.device(root, 'AC', type='Mains', online='1')
            value = self.battery.output(root)
            self.assertEqual((value['text'], value['alt']), ('12%', 'plugged-critical'))
            self.assertEqual(value['class'], ['plugged', 'critical'])

    def test_multiple_batteries_use_total_energy_and_bound_invalid_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.device(root, 'BAT0', type='Battery', capacity='30', status='Charging',
                        energy_now='20', energy_full='40')
            self.device(root, 'BAT1', type='Battery', capacity='50', status='Full',
                        energy_now='40', energy_full='60')
            self.device(root, 'BAT2', type='Battery', capacity='101', status='Full')
            value = self.battery.output(root)
            self.assertEqual((value['text'], value['alt']), ('60%', 'charging'))


class IntegrationContracts(unittest.TestCase):
    def test_greeter_and_root_shell_are_light_without_desktop_bus(self):
        greeter = source('etc/pam.d/greetd-greeter')
        self.assertLess(greeter.index('conffile=/etc/security/greetd-greeter.conf'),
                        greeter.index('pam_systemd.so class=user-light'))
        self.assertIn('XDG_SESSION_CLASS DEFAULT=user-light OVERRIDE=user-light',
                      source('etc/security/greetd-greeter.conf'))
        self.assertIn('XDG_SESSION_CLASS DEFAULT=user-early-light OVERRIDE=user-early-light',
                      source('etc/security/sudo-i.conf'))
        self.assertIn('XDG_SESSION_CLASS DEFAULT=background-light OVERRIDE=background-light',
                      source('etc/security/cron-session.conf'))
        assets = (ROOT / 'scripts/desktop/components/target-assets.sh').read_text()
        self.assertLess(assets.index('etc/security/cron-session.conf'),
                        assets.index('run_in_target "configure managed session repairs"'))
        session = source('usr/local/bin/labwc-greeter-session')
        self.assertIn('${greeter_session_root}/no-session-bus', session)
        self.assertNotIn('systemctl --user', session)

    def test_audit_stream_stays_native_and_apparmor_has_file_input(self):
        self.assertIn('active = no', source('etc/audit/plugins.d/syslog.conf'))
        self.assertIn('LOG_AUDIT_DIR="${LOG_SECURITY_DIR}/audit"',
                      (ROOT / 'hosts/logging/observability.env').read_text())
        rsyslog = source('etc/rsyslog.d/30-apparmor.conf')
        self.assertIn('File="__INSTALLER_LOG_AUDIT_FILE__"', rsyslog)
        self.assertIn('Ruleset="managed_apparmor_from_audit"', rsyslog)
        self.assertIn('string="%msg%\\n"', rsyslog)

    def test_firstboot_requires_sealing_provisioning(self):
        unit = (ROOT / 'scripts/firstboot/assets/etc/systemd/system/firstboot.service').read_text()
        self.assertIn('Requires=local-fs.target systemd-tmpfiles-setup.service journal-sealing.service', unit)
        self.assertIn('After=local-fs.target systemd-tmpfiles-setup.service systemd-journald.socket journal-sealing.service', unit)
        firstboot = (ROOT / 'scripts/firstboot/04-validation.sh.tmpl').read_text()
        self.assertIn('check_command journal-sealing-status /usr/local/libexec/journal-sealing --status', firstboot)


if __name__ == '__main__':
    unittest.main()
