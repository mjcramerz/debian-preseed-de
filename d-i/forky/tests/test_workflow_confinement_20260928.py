"""Offline regression checks for optional diagnostic and archive confinement."""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
sys.path.insert(0, str(TARGET / 'usr/local/lib/python3.14/dist-packages'))

from gitbuild import worker as build_worker
from labwc_compz import CompzError
from labwc_compz import isolation


class ArchiveConfinementTests(unittest.TestCase):
    def test_only_enforcing_worker_label_is_accepted(self):
        for label in ('unconfined', 'compz-worker (complain)', 'other (enforce)'):
            with self.subTest(label=label), mock.patch.object(Path, 'read_text', return_value=label):
                with self.assertRaises(CompzError):
                    isolation.require_confinement()
        with mock.patch.object(Path, 'read_text', return_value='compz-worker (enforce)\n'):
            isolation.require_confinement()
        pipeline = (TARGET / 'usr/local/libexec/compz-pipeline').read_text()
        self.assertIn("$label eq 'compz-worker (enforce)'", pipeline)
        self.assertNotIn('compz-worker (complain)', pipeline)

    def test_user_bus_must_belong_to_account_and_be_private(self):
        def entry(kind, owner=1000, permissions=0o600):
            return os.stat_result((kind | permissions, 0, 0, 0, owner, owner, 0, 0, 0, 0))

        directory = entry(stat.S_IFDIR, permissions=0o700)
        good_bus = entry(stat.S_IFSOCK)
        bad_buses = (entry(stat.S_IFSOCK, owner=1001),
                     entry(stat.S_IFSOCK, permissions=0o666),
                     entry(stat.S_IFLNK, permissions=0o777))
        with mock.patch.object(isolation.os, 'geteuid', return_value=1000), \
             mock.patch.object(isolation.os, 'getuid', return_value=1000):
            for bus in bad_buses:
                with self.subTest(bus=bus), mock.patch.object(Path, 'lstat', side_effect=[directory, bus]):
                    with self.assertRaises(CompzError):
                        isolation.user_environment()
            with mock.patch.object(Path, 'lstat', side_effect=[directory, good_bus]):
                self.assertEqual(isolation.user_environment()['XDG_RUNTIME_DIR'], '/run/user/1000')
        with mock.patch.object(isolation.os, 'geteuid', return_value=1000), \
             mock.patch.object(isolation.os, 'getuid', return_value=1001):
            with self.assertRaises(CompzError):
                isolation.user_environment()


class BuildLogTests(unittest.TestCase):
    def test_worker_bounds_terminal_and_private_log_together(self):
        child = mock.MagicMock()
        child.__enter__.return_value = child
        child.stdout.read1.side_effect = [b'first\n', b'second\n', b'third\n', b'']
        child.wait.return_value = 0
        log = io.BytesIO()
        terminal = io.StringIO()
        with mock.patch.object(build_worker, 'MAX_LOG_BYTES', 13), \
             mock.patch.object(build_worker.subprocess, 'Popen', return_value=child), \
             contextlib.redirect_stdout(terminal):
            build_worker.execute(['/usr/bin/true'], Path('/'), log, cwd=Path('/'), env={})
        self.assertIn('first\nsecond\n', terminal.getvalue())
        self.assertNotIn('third', terminal.getvalue())
        self.assertIn('truncated', terminal.getvalue())
        self.assertIn(b'log truncated', log.getvalue())


class BootCollectorPolicyTests(unittest.TestCase):
    def test_boot_service_uses_staged_master_mode_profile(self):
        policy = (TARGET / 'etc/apparmor.d/debugsys').read_text()
        unit = (TARGET / 'etc/systemd/system/debugsys-boot-report.service.tmpl').read_text()
        security = (FORKY / 'scripts/late/security.sh').read_text()
        modes = (TARGET / 'etc/apparmor/modes.conf.tmpl').read_text()
        self.assertIn('profile debugsys-boot-report ', policy)
        self.assertIn('AppArmorProfile=debugsys-boot-report', unit)
        self.assertIn('After=local-fs.target systemd-journald.service apparmor.service', unit)
        self.assertIn('\ndebugsys\n', security)
        self.assertIn('__DESKTOP_APPARMOR_STATE__ required debugsys -', modes)
        self.assertIn('#include <abstractions/nameservice-strict>', policy)
        self.assertNotIn('#include <abstractions/nameservice>', policy)
        self.assertIn('deny /proc/[0-9]*/{environ,mem,fd/**} r,', policy)
        self.assertIn('NetworkManager/system-connections/**', policy)
        self.assertNotIn('/etc/initramfs-tools/** rw', policy)
        self.assertNotIn('network inet', policy)


class MasterModeInventoryTests(unittest.TestCase):
    def test_every_repository_profile_source_has_one_master_mode_row(self):
        template = (TARGET / 'etc/apparmor/modes.conf.tmpl').read_text()
        rows = [line.split() for line in template.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
        self.assertTrue(rows)
        self.assertTrue(all(len(row) == 4 and row[0] == '__DESKTOP_APPARMOR_STATE__'
                            for row in rows))
        names = [row[2] for row in rows]
        self.assertEqual(len(names), len(set(names)))
        sources = {path.name.removesuffix('.tmpl')
                   for path in (TARGET / 'etc/apparmor.d').iterdir() if path.is_file()}
        sources.add('firstboot')
        self.assertFalse(sources - set(names), sorted(sources - set(names)))
        self.assertIn('mullvad', names)  # Package-installed profile, if selected.
        children = (TARGET / 'usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/LocalChildren.pm').read_text()
        for name in ('microsoft-edge-stable', 'mullvad-browser', 'vivaldi-bin'):
            self.assertIn(name, names)
            self.assertIn("'" + name + "'", children)
        for name in ('firstboot', 'hardware-tuning', 'gitbuild-worker'):
            self.assertIn(name, names)
        self.assertIn('apparmor-modes-run --no-reload',
                      (FORKY / 'scripts/late/devops/gitbuild.sh').read_text())
        self.assertIn('apparmor-modes-run --no-reload',
                      (FORKY / 'scripts/desktop/hardware-tuning.sh').read_text())
        self.assertIn('apparmor-modes-run --no-reload',
                      (FORKY / 'scripts/late/core.sh').read_text())

    def test_installer_renders_both_states_for_every_declared_profile(self):
        security = FORKY / 'scripts/late/security.sh'
        template = TARGET / 'etc/apparmor/modes.conf.tmpl'
        for state in ('complain', 'enforce'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / 'modes.conf'
                shutil.copyfile(template, config)
                result = subprocess.run(
                    ['/bin/sh', '-eu', '-c',
                     '. "$1"; installer_fatal() { echo "$*" >&2; return 1; }; '
                     'installer_info() { :; }; apparmor_apply_desktop_state "$2"',
                     'test-mode-render', str(security), str(config)],
                    env={**os.environ, 'DESKTOP_APPARMOR_STATE': state},
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = [line.split() for line in config.read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith('#')]
                self.assertTrue(rows)
                self.assertEqual({row[0] for row in rows}, {state})


if __name__ == '__main__':
    unittest.main()
