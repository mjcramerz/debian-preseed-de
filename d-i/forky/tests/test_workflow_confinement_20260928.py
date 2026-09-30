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

    def test_user_bus_is_protected_by_private_runtime_directory(self):
        def entry(kind, owner=1000, permissions=0o600):
            return os.stat_result((kind | permissions, 0, 0, 0, owner, owner, 0, 0, 0, 0))

        directory = entry(stat.S_IFDIR, permissions=0o700)
        with mock.patch.object(isolation.os, 'geteuid', return_value=1000), \
             mock.patch.object(isolation.os, 'getuid', return_value=1000):
            # Both restricted sockets and systemd's normal SocketMode=0666 work.
            for permissions in (0o600, 0o660, 0o666, 0o777):
                bus = entry(stat.S_IFSOCK, permissions=permissions)
                with self.subTest(permissions=permissions), \
                     mock.patch.object(Path, 'lstat', side_effect=[directory, bus]):
                    environment = isolation.user_environment()
                    self.assertEqual(environment['XDG_RUNTIME_DIR'], '/run/user/1000')
                    self.assertEqual(environment['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=/run/user/1000/bus')
            for bus in (entry(stat.S_IFSOCK, owner=1001), entry(stat.S_IFREG),
                        entry(stat.S_IFLNK, permissions=0o777)):
                with self.subTest(bus=bus), mock.patch.object(Path, 'lstat', side_effect=[directory, bus]):
                    with self.assertRaises(CompzError):
                        isolation.user_environment()
            for unsafe in (entry(stat.S_IFDIR, owner=1001, permissions=0o700),
                           entry(stat.S_IFDIR, permissions=0o750),
                           entry(stat.S_IFDIR, permissions=0o777),
                           entry(stat.S_IFLNK, permissions=0o700)):
                with self.subTest(directory=unsafe), mock.patch.object(Path, 'lstat', return_value=unsafe):
                    with self.assertRaises(CompzError):
                        isolation.user_environment()
            for metadata in ([FileNotFoundError()], [directory, FileNotFoundError()]):
                with self.subTest(metadata=metadata), mock.patch.object(Path, 'lstat', side_effect=metadata):
                    with self.assertRaises(CompzError):
                        isolation.user_environment()
        with mock.patch.object(isolation.os, 'geteuid', return_value=1000), \
             mock.patch.object(isolation.os, 'getuid', return_value=1001):
            with self.assertRaises(CompzError):
                isolation.user_environment()

    def test_unreachable_user_manager_creates_no_workspace_or_worker(self):
        environment = {'XDG_RUNTIME_DIR': '/run/user/1000',
                       'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}
        with mock.patch.object(isolation, 'require_data_directory'), \
             mock.patch.object(isolation, 'user_environment', return_value=environment), \
             mock.patch.object(isolation.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as check, \
             mock.patch.object(isolation.subprocess, 'Popen') as start, \
             mock.patch.object(isolation.tempfile, 'mkdtemp') as workspace:
            with self.assertRaisesRegex(CompzError, 'no unconfined fallback'):
                isolation.execute(Path('/home/user/notes'), {}, '')
            self.assertEqual(check.call_args.args[0], ['/usr/bin/systemctl', '--user', 'show-environment'])
            self.assertEqual(check.call_args.kwargs['env'], environment)
            start.assert_not_called()
            workspace.assert_not_called()


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
        self.assertTrue(all(len(row) == 4 and
                            (row == ['enforce', 'optional', 'hardware-tuning', '-']
                             if row[2] == 'hardware-tuning'
                             else row[0] == '__DESKTOP_APPARMOR_STATE__')
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
                self.assertEqual({row[0] for row in rows if row[2] != 'hardware-tuning'}, {state})
                self.assertEqual([row for row in rows if row[2] == 'hardware-tuning'],
                                 [['enforce', 'optional', 'hardware-tuning', '-']])

    def test_installer_rejects_a_complain_hardware_policy(self):
        security = FORKY / 'scripts/late/security.sh'
        template = TARGET / 'etc/apparmor/modes.conf.tmpl'
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'modes.conf'
            unsafe = template.read_text().replace('enforce optional hardware-tuning -',
                                                  '__DESKTOP_APPARMOR_STATE__ optional hardware-tuning -')
            config.write_text(unsafe)
            result = subprocess.run(
                ['/bin/sh', '-eu', '-c',
                 '. "$1"; installer_fatal() { echo "$*" >&2; return 1; }; '
                 'installer_info() { :; }; apparmor_apply_desktop_state "$2"',
                 'test-mode-reject', str(security), str(config)],
                env={**os.environ, 'DESKTOP_APPARMOR_STATE': 'complain'},
                capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_text(), unsafe)


if __name__ == '__main__':
    unittest.main()
