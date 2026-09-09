#!/usr/bin/env python3
"""Offline policy and failure-injection tests; no running target or services."""
from __future__ import annotations
import io
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import yaml

FORKY = Path(__file__).resolve().parents[1]
os.environ["INSTALLER_SOURCE_LIBRARY"] = str(FORKY / "scripts/common/source.sh")
SHARED = FORKY / 'hooks/target'
HARDWARE = FORKY / 'hooks/target'


def load(path: Path) -> types.ModuleType:
    module = types.ModuleType('test_subject')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class ConfigSafetyTests(unittest.TestCase):
    def test_distributed_account_defaults_have_no_reusable_credentials(self):
        text = (FORKY / 'hosts/installer/account.env').read_text()
        self.assertIn('ROOT_LOGIN=true', text)
        self.assertNotIn('ROOT_PASSWORD_CRYPTED=', text)
        self.assertIn('ACCOUNT_PASSWORD_CRYPTED="${ACCOUNT_PASSWORD_CRYPTED:-}"', text)
        self.assertIn('FRUUX_CALENDAR_PASSWORD="${FRUUX_CALENDAR_PASSWORD:-}"', text)
        self.assertNotIn('$6$rounds=', text)

    def test_cpu_profile_retains_deployed_vfio_reservation(self):
        base = HARDWARE / 'etc'
        for name in ('default/grub.d/75-intel-vfio.cfg', 'modprobe.d/vfio-pci.conf'):
            active = '\n'.join(x for x in (base / name).read_text().splitlines() if not x.startswith('#'))
            self.assertIn('ids=8086:02e0', active)

    def test_default_intel_iommu_is_not_passthrough(self):
        text = (HARDWARE / 'etc/default/grub.d/80-cpu-profile-flags.intel.cfg').read_text()
        default = next(x for x in text.splitlines() if x.startswith('GRUB_PROFILE_DEFAULT_FLAGS='))
        self.assertIn('iommu.passthrough=0', default)
        self.assertIn('iommu.strict=1', default)
        self.assertNotIn('iommu=pt', default)

    def test_nvme_profile_retains_explicit_platform_compatibility_policy(self):
        path = HARDWARE / 'etc/default/grub.d/73-pcie-power.cfg'
        active = '\n'.join(x for x in path.read_text().splitlines() if not x.startswith('#'))
        self.assertIn('pcie_aspm=off', active)
        self.assertIn('autosuspend=-1', active)

    def test_nvidia_vram_preservation_has_installer_and_storage_integration(self):
        text = (HARDWARE / 'etc/modprobe.d/nvidia.conf').read_text()
        active = '\n'.join(x for x in text.splitlines() if not x.startswith('#'))
        self.assertIn('modeset=1', active)
        self.assertIn('NVreg_PreserveVideoMemoryAllocations=1', active)
        self.assertIn('NVreg_TemporaryFilePath=/var/lib/nvidia-vram', active)
        for family in ('btrfs-family.sh', 'f2fs-family.sh'):
            self.assertIn('configure_target_nvidia_power_management "$target_enable_nvidia"',
                          (FORKY / 'scripts/late' / family).read_text())

    def test_cleaner_uses_host_mount_table_inside_systemd_sandbox(self):
        text = (SHARED / 'etc/systemd/system/tmpfs-pre-clean.service.tmpl').read_text()
        self.assertIn('TMPFS_PRE_CLEAN_MOUNTINFO=/proc/1/mountinfo', text)
        self.assertIn('ProtectSystem=strict', text)
        self.assertIn('TimeoutStartSec=2min', text)

    def test_podman_api_preserves_container_lifecycle_and_rootless_helpers(self):
        base = SHARED / 'data/config/podman/templates/devops'
        api = (base / 'podman.service.tmpl').read_text()
        self.assertIn('KillMode=process', api)
        self.assertIn('Delegate=yes', api)
        self.assertNotIn('NoNewPrivileges=yes', api)
        self.assertIn('SocketMode=0660', (base / 'podman.socket').read_text())
        self.assertIn('RemoveOnStop=yes', (base / 'podman.socket').read_text())
        self.assertIn('TimeoutStopSec=30', api)

    def test_syncthing_preparation_never_runs_with_root_credentials(self):
        unit = (SHARED / 'etc/systemd/system/managed-syncthing.service.tmpl').read_text()
        script = (SHARED / 'usr/local/libexec/managed-syncthing-configure').read_text()
        installer = (FORKY / 'scripts/late/tailscale.sh').read_text()
        self.assertNotIn('PermissionsStartOnly=', unit)
        self.assertNotIn('ExecStartPre=+', unit)
        self.assertNotIn('ExecStartPre=!', unit)
        self.assertNotIn('chown -R', script)
        self.assertIn('run this helper as SYNCTHING_USER, not root', script)
        self.assertIn('/usr/sbin/runuser -u "$1" -- /usr/local/libexec/managed-syncthing-configure', installer)


class NftablesCatalogTests(unittest.TestCase):
    def render_catalog(self, root: Path, ssh_enabled: bool, cmdline: str = 'fixture=1') -> Path:
        target = root / 'target'
        work = root / 'work'
        target.mkdir()
        work.mkdir()
        program = r'''\
. "$1"
. "$2"
. "$3"
. "$4"
installer_repo_join_var() {
  [ "$1" = DIR_HOOKS_TARGET ] || return 91
  printf '%s/%s\n' "$FIXTURE_SOURCE" "$2"
}
fetch_hook() { cp -- "$1" "$2"; }
target_normalize_systemd_config_parent_modes() { :; }
stage_target_nftables_all_service_assets
'''
        env = {
            **os.environ,
            'LC_ALL': 'C',
            'TZ': 'UTC',
            'INSTALLER_TARGET_DIR': str(target),
            'TMP_ENV_DIR': str(work),
            'FIXTURE_SOURCE': str(SHARED),
            'SSH_SERVER_ENABLED': 'true' if ssh_enabled else 'false',
            'INSTALLER_CMDLINE': cmdline,
        }
        result = subprocess.run(
            [
                '/bin/sh', '-eu', '-c', program, 'sh',
                str(FORKY / 'scripts/common/lib.sh'),
                str(FORKY / 'scripts/runtime/common.sh'),
                str(FORKY / 'scripts/late/target-assets.sh'),
                str(FORKY / 'scripts/late/security.sh'),
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return target / 'etc/nftables/services'

    def assert_catalog_resolved(self, catalog: Path) -> None:
        expected = {path.name for path in (SHARED / 'etc/nftables/services').glob('*.yml')}
        actual = {path.name for path in catalog.glob('*.yml')}
        self.assertEqual(actual, expected)
        for path in catalog.glob('*.yml'):
            with self.subTest(overlay=path.name):
                text = path.read_text(encoding='utf-8')
                self.assertNotRegex(text, r'__INSTALLER_[A-Z0-9_]+__')
                document = yaml.safe_load(text)
                self.assertEqual(document['apiVersion'], 'cybops.nftables/v1')
                self.assertEqual(document['kind'], 'NftablesServiceOverlay')

    def test_full_catalog_is_rendered_without_optional_addons(self):
        with tempfile.TemporaryDirectory(prefix='nftables-catalog-inactive-') as tmp:
            catalog = self.render_catalog(Path(tmp), ssh_enabled=False)
            self.assert_catalog_resolved(catalog)
            ssh = yaml.safe_load((catalog / 'ssh-server.yml').read_text(encoding='utf-8'))
            self.assertEqual(ssh['services']['ssh_server']['ports'], [22])

    def test_selected_ssh_port_is_preserved_in_rendered_catalog(self):
        with tempfile.TemporaryDirectory(prefix='nftables-catalog-ssh-') as tmp:
            catalog = self.render_catalog(Path(tmp), ssh_enabled=True, cmdline='ssh_port=2222')
            self.assert_catalog_resolved(catalog)
            ssh = yaml.safe_load((catalog / 'ssh-server.yml').read_text(encoding='utf-8'))
            self.assertEqual(ssh['services']['ssh_server']['ports'], [2222])


class SyncthingConfigTests(unittest.TestCase):
    def setUp(self):
        script = (SHARED / 'usr/local/libexec/managed-syncthing-configure').read_text()
        self.code = script.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        self.temp = tempfile.TemporaryDirectory(prefix='syncthing-config-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / 'config.xml'
        self.config.write_text('<configuration version="37"><device id="test-id"/><gui enabled="true"><address>0.0.0.0:8384</address></gui></configuration>')
        self.config.chmod(0o600)

    def invoke(self, mode='--prepare'):
        argv = ['renderer', str(self.config), str(self.base / 'data'), '35000', 'false', mode]
        # Keep test runner signal handlers intact; production installs these on itself.
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(signal, 'signal'):
            exec(compile(self.code, '<syncthing-config>', 'exec'), {})

    def test_prepare_atomic_private_and_validated_without_rewriting(self):
        self.invoke()
        root = ET.parse(self.config).getroot()
        self.assertEqual(root.findtext('options/listenAddress'), 'tcp://0.0.0.0:35000')
        self.assertEqual(root.find('gui').get('enabled'), 'false')
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        before = self.config.stat().st_mtime_ns
        with self.assertRaises(SystemExit) as result:
            self.invoke('--validate-config')
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(before, self.config.stat().st_mtime_ns)

    def test_failed_rename_preserves_old_xml_and_removes_scratch(self):
        before = self.config.read_bytes()
        with mock.patch.object(os, 'replace', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                self.invoke()
        self.assertEqual(before, self.config.read_bytes())
        self.assertEqual(list(self.base.iterdir()), [self.config])

    def test_symlink_configuration_rejected(self):
        real = self.base / 'real'
        self.config.rename(real)
        self.config.symlink_to(real)
        with self.assertRaises(OSError):
            self.invoke()

    def test_validation_mismatch_is_not_mutated(self):
        before = self.config.read_bytes()
        with self.assertRaises(RuntimeError):
            self.invoke('--validate-config')
        self.assertEqual(before, self.config.read_bytes())


class CodexCleanupTests(unittest.TestCase):
    def setUp(self):
        self.c = load(SHARED / 'data/codex/lib/codex')

    def test_exit_race_still_waits_for_owned_child(self):
        child = mock.Mock()
        child.poll.return_value = None
        child.terminate.side_effect = ProcessLookupError
        self.c._terminate_process(child)
        child.wait.assert_called_once()

    def test_second_timeout_does_not_abort_other_teardown(self):
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired('child', 1)
        with mock.patch.object(sys, 'stderr', io.StringIO()) as log:
            self.c._terminate_process(child)
        self.assertIn('SIGKILL', log.getvalue())
        child.kill.assert_called_once()

    def test_pidfd_stays_open_until_final_sandbox_signal(self):
        c = self.c
        events = []
        c.CODEX_SANDBOX_PIDFD = 234
        with mock.patch.object(c, 'codex_clear_app_server_environment'), \
             mock.patch.object(c, '_terminate_process'), \
             mock.patch.object(c, '_signal_sandbox', side_effect=lambda sig: events.append(('signal', sig, c.CODEX_SANDBOX_PIDFD))), \
             mock.patch.object(c, '_close_fd', side_effect=lambda fd: events.append(('close', fd))):
            c.codex_cleanup()
        self.assertLess(events.index(('signal', signal.SIGKILL, 234)), events.index(('close', 234)))
        self.assertIsNone(c.CODEX_SANDBOX_PIDFD)
        self.assertTrue(c.CODEX_SIGNALLED)
        c.codex_handle_signal(signal.SIGTERM)  # Must not interrupt cleanup again.


class BrokerFinalTests(unittest.TestCase):
    def test_signal_handler_disarms_repeated_signals_before_unwinding(self):
        helper = load(SHARED / 'usr/local/libexec/dbus-broker-maintain')
        with mock.patch.object(signal, 'signal') as install:
            helper.install_signal_handlers()
            handler = install.call_args_list[0].args[1]
            with self.assertRaises(SystemExit) as outcome:
                handler(signal.SIGTERM, None)
            self.assertEqual(outcome.exception.code, 143)
            self.assertEqual(install.call_args_list[-1].args, (signal.SIGTERM, signal.SIG_IGN))

    @unittest.skipUnless(os.geteuid() == 0, 'root-owned-file validation')
    def test_unchanged_config_with_wrong_mode_is_repaired(self):
        helper = load(SHARED / 'usr/local/libexec/dbus-broker-maintain')
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'config'
            path.write_bytes(b'unchanged')
            path.chmod(0o600)
            helper.atomic_write(path, b'unchanged')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)


if __name__ == '__main__':
    unittest.main()
