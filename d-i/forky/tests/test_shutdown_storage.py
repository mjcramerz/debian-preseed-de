"""Exercise the real shutdown coordinator with every host command intercepted."""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from power_handoff_fixture import is_handoff
from test_power_runtime_20260920 import module
from test_network_sharing import NFS, PROFILES, profile


def published_policy(settings):
    """Use the installer's actual public schema and unit escaper."""
    return NFS.public_config(settings)


class ShutdownPolicyTests(unittest.TestCase):
    def setUp(self):
        self.power = module()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.path = root / 'config.json'
        self.stack.enter_context(mock.patch.object(self.power, 'SHARING_CONFIG', self.path))
        # Model installed root-owned ancestors; the fixture itself is in /tmp.
        self.parents = self.stack.enter_context(mock.patch.object(
            Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)))
        real_fstat = os.fstat
        def installed_owner(fd):
            meta = real_fstat(fd)
            return SimpleNamespace(st_mode=meta.st_mode, st_uid=0, st_nlink=meta.st_nlink)
        self.stack.enter_context(mock.patch.object(self.power.os, 'fstat', side_effect=installed_owner))

    def load(self, data):
        self.path.write_text(json.dumps(data))
        self.path.chmod(0o644)
        return self.power.sharing_stop_groups()

    def test_all_installer_profiles_and_role_combinations_match(self):
        for path in PROFILES.glob('*.env'):
            for server, client in ((False, False), (True, False), (False, True), (True, True)):
                with self.subTest(profile=path.name, server=server, client=client):
                    settings = NFS.Settings.from_environment(profile(path,
                        NFS_SERVER_ENABLE=str(server).lower(), NFS_CLIENT_ENABLE=str(client).lower(),
                        NFS_SERVER_BIND_ENABLE=str(server).lower(), NFS_CLIENT_BIND_ENABLE=str(client).lower()))
                    policy = published_policy(settings)
                    groups = self.load(policy)
                    names = [name for group in groups for name in group]
                    expected = []
                    if server:
                        expected.append(policy['server_bind_mount'])
                    if client:
                        expected += [policy[key] for key in ('client_mount', 'client_bind_mount')]
                    self.assertCountEqual(names, expected)
                    self.assertTrue(all(name.endswith('.mount') for name in names))

    def test_unbound_custom_paths_are_derived_not_assumed(self):
        values = profile(NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='false',
                         NFS_SERVER_ENABLE='false', NFS_SERVER_BIND_ENABLE='false',
                         NETWORK_SHARING_ROOT_PATH='/srv/lan-sharing',
                         NFS_SERVER_PATH='/srv/lan-sharing/server',
                         NFS_CLIENT_PATH='/srv/lan-sharing/client-1')
        policy = published_policy(NFS.Settings.from_environment(values))
        self.assertEqual(self.load(policy), [(), (policy['client_mount'],)])

    def test_missing_optional_policy_has_no_mount_operations(self):
        self.assertEqual(self.power.sharing_stop_groups(), [])

    def test_untrusted_or_malformed_policy_never_selects_arbitrary_units(self):
        valid = published_policy(NFS.Settings.from_environment(profile(
            NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true')))
        for key, value in (('client_mount', 'etc.mount'), ('client_automount', ''),
                           ('client_bind_automount', ''), ('server_bind_automount', ''),
                           ('client_bind_mount', '../home.mount'), ('version', 1)):
            with self.subTest(key=key), self.assertRaises(self.power.Error):
                self.load({**valid, key: value})
        for key, value in (('NFS_CLIENT_PATH', '/etc'), ('ACCOUNT_HOME', '/home/../etc'),
                           ('NFS_CLIENT_HOME_BIND_PATH', '../../root'),
                           ('NFS_CLIENT_ENABLE', 'false')):
            with self.subTest(key=key), self.assertRaises(self.power.Error):
                self.load({**valid, 'profile': {**valid['profile'], key: value}})
        for raw in ('{', '[]', ' ' * 65537):
            self.path.write_text(raw)
            with self.assertRaises(self.power.Error):
                self.power.sharing_stop_groups()

    def test_links_special_files_and_writable_metadata_fail_closed(self):
        original = self.path.with_name('original')
        original.write_text('{}')
        self.path.symlink_to(original)
        with self.assertRaises(OSError):
            self.power.sharing_stop_groups()
        self.path.unlink()
        os.link(original, self.path)
        with self.assertRaisesRegex(self.power.Error, 'untrusted'):
            self.power.sharing_stop_groups()
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaisesRegex(self.power.Error, 'untrusted'):
            self.power.sharing_stop_groups()
        self.path.unlink()
        self.path.write_text('{}')
        self.path.chmod(0o666)
        with self.assertRaisesRegex(self.power.Error, 'untrusted'):
            self.power.sharing_stop_groups()
        self.parents.return_value = SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_uid=0)
        with self.assertRaisesRegex(self.power.Error, 'directory'):
            self.power.sharing_stop_groups()


class ShutdownFlowTests(unittest.TestCase):
    mounts = ('home-desktop-Sharing-server.mount', 'home-desktop-Sharing-client.mount',
              'srv-sharing-client.mount')

    def setUp(self):
        self.power = module()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        for name in ('ready', 'hold_reservation'):
            self.stack.enter_context(mock.patch.object(self.power, name))
        self.stack.enter_context(mock.patch.object(self.power, 'PackageLocks',
            side_effect=AssertionError('machine shutdown must not wait for packages')))
        self.stack.enter_context(mock.patch.object(self.power, 'run', side_effect=self.mock_run))
        self.stack.enter_context(mock.patch.object(self.power.Worker, 'user_run', side_effect=self.mock_run))
        self.stack.enter_context(mock.patch.object(self.power, 'sharing_stop_groups',
            return_value=[self.mounts[:2], self.mounts[2:]]))
        self.stack.enter_context(mock.patch.object(self.power.Worker, 'session_identity',
            side_effect=AssertionError('machine shutdown must not require desktop readiness')))
        self.stack.enter_context(mock.patch.object(self.power.Worker, 'protect_other_sessions',
            side_effect=AssertionError('shutdown authorization is already complete')))
        self.reset()

    def reset(self, action='poweroff', greeter=False):
        self.calls = []
        self.failure = None
        self.application_records = []
        self.worker = self.power.Worker(1000, 'desktop', action, greeter=greeter)

    def mock_run(self, argv, **kwargs):
        self.calls.append(argv)
        self.assertFalse(any(value.startswith('--property=') for value in argv),
                         'cleanup must not inspect retained unit results')
        self.assertNotIn('ListSessions', argv)
        self.assertNotIn('ListInhibitors', argv)
        if self.failure is not None and self.failure in argv:
            raise self.power.Error('injected failed cleanup')
        if 'GetUnitProcesses' in argv:
            return json.dumps({'type': 'a(sus)', 'data': [self.application_records]})
        if argv[-2:] == ['start', self.power.EXTERNAL_DRIVES_UNIT]:
            self.assertFalse(any('terminate-user' in command or 'greetd.service' in command
                                 or 'user@1000.service' in command for command in self.calls))
        return ''

    def stop_index(self, name):
        return next(i for i, command in enumerate(self.calls) if 'stop' in command and name in command)

    def assert_handoff(self):
        handoffs = [command for command in self.calls if is_handoff(command)]
        self.assertEqual(handoffs, [['/usr/bin/systemctl', '--force', self.worker.action]])
        self.assertEqual(self.calls[-1], handoffs[0])
        self.assertTrue(self.worker.committed and self.worker.handoff_attempted)

    def test_desktop_and_greeter_both_actions_attempt_ordered_cleanup_then_submit(self):
        for action in ('poweroff', 'reboot'):
            for greeter in (False, True):
                with self.subTest(action=action, greeter=greeter):
                    self.reset(action, greeter)
                    self.worker.execute()
                    indices = [self.stop_index(name) for name in (
                        self.mounts[-1], 'nfs-server.service', 'nfs-idmapd.service')]
                    indices += [next(i for i, c in enumerate(self.calls) if 'GetUnitProcesses' in c),
                                next(i for i, c in enumerate(self.calls)
                                     if c[-2:] == ['start', self.power.EXTERNAL_DRIVES_UNIT])]
                    indices += [self.stop_index('greetd.service')]
                    indices += [next(i for i, c in enumerate(self.calls) if 'terminate-user' in c)]
                    indices += [self.stop_index(name) for name in (
                        'zram-writebackd.service', 'zram-setup.service', 'swap-fallback.service')]
                    self.assertEqual(indices, sorted(set(indices)))
                    self.assertEqual(set(self.calls[self.stop_index(self.mounts[-1])][3:]), set(self.mounts))
                    self.assertIn(['/usr/bin/sync'], self.calls)
                    self.assert_handoff()
                    save = ['start', f'labwc-session-state@{action}.service']
                    requests = [c for c in self.calls if c[-2:] == save]
                    self.assertEqual(len(requests), 0 if greeter else 1)

    def test_each_failed_cleanup_still_submits_for_desktop_and_greeter(self):
        stages = (*self.mounts, 'nfs-server.service', 'nfs-idmapd.service',
                  'greetd.service', 'terminate-user', 'GetUnitProcesses', self.power.EXTERNAL_DRIVES_UNIT,
                  'zram-writebackd.service', 'zram-setup.service', 'swap-fallback.service',
                  '/usr/bin/sync', 'labwc-session-state@poweroff.service',
                  'labwc-session-state@reboot.service')
        for action in ('poweroff', 'reboot'):
            for greeter in (False, True):
                for name in stages:
                    with self.subTest(action=action, greeter=greeter, failed_stage=name):
                        self.reset(action, greeter)
                        self.failure = name
                        self.worker.execute()
                        self.assert_handoff()

    def test_untrusted_sharing_policy_skips_its_cleanup_and_still_submits(self):
        with mock.patch.object(self.power, 'sharing_stop_groups',
                               side_effect=self.power.Error('untrusted configuration')):
            self.worker.execute()
        self.assertFalse(any(name in command for command in self.calls for name in self.mounts))
        self.assert_handoff()

    def test_optional_units_are_only_stopped_and_drive_cleanup_starts_once(self):
        self.worker.execute()
        starts = [command for command in self.calls if 'start' in command and '--user' not in command]
        self.assertEqual(starts, [['/usr/bin/systemctl', '--no-ask-password', 'start',
                                   self.power.EXTERNAL_DRIVES_UNIT]])
        self.assert_handoff()

    def test_remaining_terminal_skips_removal_before_session_teardown_for_both_entrypoints(self):
        for greeter in (False, True):
            with self.subTest(greeter=greeter):
                self.reset(greeter=greeter)
                self.application_records = [[
                    '/user.slice/user-1000.slice/user@1000.service/app.slice/foot.service',
                    123, 'shell in /run/media/desktop/external']]
                self.worker.execute()
                self.assertFalse(any(c[-2:] == ['start', self.power.EXTERNAL_DRIVES_UNIT] for c in self.calls))
                inventory = next(i for i, c in enumerate(self.calls) if 'GetUnitProcesses' in c)
                self.assertLess(inventory, self.stop_index('greetd.service'))
                self.assert_handoff()

    def test_drive_wait_preserves_the_remaining_session_cleanup_budget(self):
        now = [100.0]
        self.worker.shutdown_deadline = 145
        def prepare():
            now[0] = 1000.0
        with mock.patch.object(self.power.time, 'monotonic', side_effect=lambda: now[0]), \
                mock.patch.object(self.worker, 'stop_network_sharing'), \
                mock.patch.object(self.worker, 'prepare_external_drives', side_effect=prepare):
            self.worker.prepare_machine_shutdown()
        self.assertEqual(self.worker.shutdown_deadline, 1045)
        self.assertTrue(any('terminate-user' in c for c in self.calls))
        self.assertIn(['/usr/bin/sync'], self.calls)


if __name__ == '__main__':
    unittest.main()
