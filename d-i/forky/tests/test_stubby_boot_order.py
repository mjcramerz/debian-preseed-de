"""Stubby ordering regressions for the disposable test image only.

The native check loads a private unit tree, never contacts a systemd manager,
and never starts a unit. The firstboot check executes only its extracted
function with an explicit systemctl fixture.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SEED = Path(__file__).resolve().parents[1]
UNITS = SEED / 'hooks/target/etc/systemd/system'
BASE = (UNITS / 'stubby.service').read_text(encoding='utf-8')
DROPIN = (UNITS / 'stubby.service.d/60-app-veth.conf').read_text(encoding='utf-8')
VALIDATOR = (SEED / 'scripts/firstboot/04-validation.sh.tmpl').read_text(encoding='utf-8')


class StubbyBootOrderingTests(unittest.TestCase):
    def test_native_graph_reproduces_vendor_cycle_and_accepts_managed_base(self):
        analyzer = shutil.which('systemd-analyze')
        self.assertIsNotNone(analyzer, 'systemd-analyze is required in the disposable image')
        with tempfile.TemporaryDirectory(prefix='stubby-unit-graph-') as directory:
            root = Path(directory)
            units = root / 'etc/systemd/system'
            units.mkdir(parents=True)
            binary = root / 'usr/bin/stubby'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nexit 0\n', encoding='ascii')
            binary.chmod(0o755)
            # Match the recorded path back from network-online to sysinit.
            after = {
                'network-online.target': 'NetworkManager-wait-online.service',
                'NetworkManager-wait-online.service': 'NetworkManager.service',
                'NetworkManager.service': 'NetworkManager-dispatcher.service',
                'NetworkManager-dispatcher.service': 'basic.target',
                'basic.target': 'paths.target',
                'paths.target': 'apt-repo-local-inbox.path',
                'apt-repo-local-inbox.path': 'sysinit.target',
                'sysinit.target': '',
                'local-fs.target': '',
                'shutdown.target': '',
                'systemd-sysusers.service': '',
                'apparmor.service': '',
                'systemd-resolved.service': '',
                'apt-repo-local-inbox.service': '',
            }
            for name, predecessor in after.items():
                content = '[Unit]\nDefaultDependencies=no\n'
                if predecessor:
                    content += 'Requires=' + predecessor + '\nAfter=' + predecessor + '\n'
                if name == 'sysinit.target':
                    content += 'Requires=stubby.service\n'
                if name.endswith('.service'):
                    content += '[Service]\nExecStart=/usr/bin/stubby\n'
                elif name.endswith('.path'):
                    content += '[Path]\nPathExists=/fixture-inbox\n'
                (units / name).write_text(content, encoding='ascii')
            dropins = units / 'stubby.service.d'
            dropins.mkdir()
            (dropins / '60-app-veth.conf').write_text(DROPIN, encoding='utf-8')
            command = [analyzer, '--root=' + str(root), '--generators=no', '--man=no',
                       'verify', 'stubby.service', 'sysinit.target']
            environment = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SYSTEMD_LOG_LEVEL': 'info'}
            # Debian's dependency edges survive the old empty drop-in entries.
            legacy = BASE.replace('[Service]',
                                  'Wants=network-online.target\nAfter=network-online.target\n\n[Service]', 1)
            (units / 'stubby.service').write_text(legacy, encoding='utf-8')
            (dropins / '70-ineffective-reset.conf').write_text('[Unit]\nWants=\nAfter=\n', encoding='ascii')
            result = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=20)
            self.assertIn('ordering cycle', result.stderr, result.stdout + result.stderr)
            (units / 'stubby.service').write_text(BASE, encoding='utf-8')
            result = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('ordering cycle', result.stderr)

    def test_firstboot_rejects_effective_vendor_and_missing_ordering(self):
        body = VALIDATOR.split('validate_stubby_boot_order() {\n', 1)[1].split('\n}\n', 1)[0]
        script = 'set -u\nvalidate_stubby_boot_order() {\n' + body + '\n}\nvalidate_stubby_boot_order\n'
        good = ('FragmentPath=/etc/systemd/system/stubby.service\n'
                'After=local-fs.target systemd-sysusers.service apparmor.service\n'
                'Before=sysinit.target systemd-resolved.service shutdown.target')
        cases = [(good, 0),
                 (good.replace('/etc/systemd/system/', '/usr/lib/systemd/system/'), 1),
                 (good.replace('After=', 'After=network-online.target '), 1),
                 (good.replace('After=', 'After=basic.target '), 1),
                 (good.replace('apparmor.service', ''), 1),
                 (good.replace('sysinit.target', ''), 1),
                 ('', 1)]
        with tempfile.TemporaryDirectory(prefix='stubby-firstboot-') as directory:
            root = Path(directory)
            for name, content in {
                'systemctl': '#!/bin/sh\nprintf "%s\\n" "$FIXTURE_PROPERTIES"\n',
                'timeout': '#!/bin/sh\nshift 3\nexec "$@"\n',
            }.items():
                fixture = root / name
                fixture.write_text(content, encoding='ascii')
                fixture.chmod(0o755)
            for properties, expected in cases:
                with self.subTest(properties=properties):
                    result = subprocess.run(['/bin/sh', '-c', script], stdin=subprocess.DEVNULL,
                                            env={'PATH': directory + ':/usr/bin:/bin', 'LC_ALL': 'C',
                                                 'FIXTURE_PROPERTIES': properties},
                                            capture_output=True, text=True, timeout=3)
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_installer_stages_base_and_firstboot_checks_effective_unit(self):
        staging = (SEED / 'scripts/late/security.sh').read_text(encoding='utf-8')
        self.assertIn('etc/systemd/system/stubby.service)" /etc/systemd/system/stubby.service 0644', staging)
        self.assertIn('check_command managed-stubby-boot-order validate_stubby_boot_order', VALIDATOR)
        self.assertIn('systemctl is-active --quiet stubby.service', VALIDATOR)
        for setting in ('Type=notify', 'WorkingDirectory=/run/stubby', 'RuntimeDirectory=stubby',
                        'DynamicUser=true', 'ExecStart=/usr/bin/stubby -C /etc/stubby/stubby.yml',
                        'Restart=on-failure', 'WantedBy=multi-user.target'):
            self.assertIn(setting, BASE)


if __name__ == '__main__':
    unittest.main()
