"""Exercise the real shutdown coordinator with every host command intercepted."""
from __future__ import annotations

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
    """The installer's public schema, with units derived by its own escaper."""
    values = settings.values
    result = dict(version=1, profile=values, peers=settings.peers,
                  server_enabled=settings.enabled('NFS_SERVER_ENABLE'),
                  client_enabled=settings.enabled('NFS_CLIENT_ENABLE'),
                  client_mount=NFS.unit_name(values['NFS_CLIENT_PATH']),
                  client_automount=NFS.unit_name(values['NFS_CLIENT_PATH'], 'automount'))
    for role in ('SERVER', 'CLIENT'):
        target = values['ACCOUNT_HOME'] + '/' + values[f'NFS_{role}_HOME_BIND_PATH']
        enabled = settings.enabled(f'NFS_{role}_BIND_ENABLE')
        result[role.lower() + '_bind_mount'] = NFS.unit_name(target) if enabled else ''
        result[role.lower() + '_bind_automount'] = (
            NFS.unit_name(target, 'automount') if enabled and role == 'CLIENT' else '')
    return result


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
                        expected += [policy[key] for key in ('client_mount', 'client_automount',
                                    'client_bind_mount', 'client_bind_automount')]
                    self.assertCountEqual(names, expected)

    def test_unbound_custom_paths_are_derived_not_assumed(self):
        values = profile(NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='false',
                         NFS_SERVER_ENABLE='false', NFS_SERVER_BIND_ENABLE='false',
                         NETWORK_SHARING_ROOT_PATH='/srv/lan-sharing',
                         NFS_SERVER_PATH='/srv/lan-sharing/server',
                         NFS_CLIENT_PATH='/srv/lan-sharing/client-1')
        policy = published_policy(NFS.Settings.from_environment(values))
        self.assertEqual(self.load(policy), [(policy['client_automount'],), (), (policy['client_mount'],)])

    def test_missing_optional_policy_has_no_mount_operations(self):
        self.assertEqual(self.power.sharing_stop_groups(), [])

    def test_untrusted_or_malformed_policy_never_selects_arbitrary_units(self):
        valid = published_policy(NFS.Settings.from_environment(profile(
            NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true')))
        for key, value in (('client_mount', 'etc.mount'), ('client_automount', '--force'),
                           ('client_bind_mount', '../home.mount'), ('version', 2)):
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
    mounts = ('home-desktop-Sharing-client.automount', 'srv-sharing-client.automount',
              'home-desktop-Sharing-server.mount', 'home-desktop-Sharing-client.mount',
              'srv-sharing-client.mount')

    def setUp(self):
        self.power = module()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        for name in ('ready', 'hold_reservation', 'PackageLocks'):
            self.stack.enter_context(mock.patch.object(self.power, name))
        self.stack.enter_context(mock.patch.object(self.power, 'run', side_effect=self.mock_run))
        self.stack.enter_context(mock.patch.object(self.power.Worker, 'user_run', side_effect=self.mock_run))
        self.stack.enter_context(mock.patch.object(self.power, 'sharing_stop_groups',
            return_value=[self.mounts[:2], self.mounts[2:4], self.mounts[4:]]))
        self.identity = self.stack.enter_context(mock.patch.object(
            self.power.Worker, 'session_identity', return_value='a' * 32))
        self.reset()

    def reset(self, action='poweroff', greeter=False):
        self.calls, self.stopped, self.absent = [], set(), set()
        self.stop_error = self.stop_result_error = self.restart = None
        self.veto = self.user_stopped = self.late_login = False
        self.worker = self.power.Worker(1000, 'desktop', action, greeter=greeter)

    def mock_run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[-1] == 'ListSessions':
            rows = [] if self.user_stopped else [
                ['c1', 1000, 'desktop', 'seat0', '/org/freedesktop/login1/session/c1']]
            if self.user_stopped and self.late_login:
                rows = [['c2', 1000, 'desktop', 'seat0', '/org/freedesktop/login1/session/c2']]
            return json.dumps({'type': 'a(susso)', 'data': [rows]})
        if argv[-1] == 'ListInhibitors':
            return json.dumps({'type': 'a(ssssuu)', 'data': [[]]})
        if 'show-session' in argv:
            if '--value' in argv:
                return 'user\n'
            return ('User=1000\nName=desktop\nClass=user-light\nActive=yes\nRemote=no\n'
                    'Service=greetd-greeter\nLeader=1234\n')
        if '--property=LoadState,ActiveState' in argv:  # Optional guest hooks.
            return 'LoadState=not-found\nActiveState=inactive\n'
        if '--property=LoadState,ActiveState,SubState,Result' in argv:
            name = argv[2]
            if name in self.absent:
                return 'LoadState=not-found\nActiveState=inactive\nSubState=dead\n'
            inactive = name in self.stopped
            if self.worker.storage_stopped and name == self.restart:
                inactive = False
            result = 'exit-code' if inactive and name == self.stop_result_error else 'success'
            return ('LoadState=loaded\nActiveState=' + ('inactive' if inactive else 'active')
                    + '\nSubState=' + ('dead' if inactive else 'running') + '\nResult=' + result + '\n')
        if '--property=ActiveState,SubState,Result,ExecMainStatus' in argv:
            return ('ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus='
                    + ('77' if self.veto else '0') + '\n')
        if '--property=ActiveState' in argv:
            return 'inactive\n' if self.user_stopped else 'active\n'
        if 'terminate-user' in argv:
            self.user_stopped = True
        if 'stop' in argv and '--user' not in argv and '--no-block' not in argv:
            names = argv[argv.index('stop') + 1:]
            if self.stop_error in names:
                raise self.power.Error('injected busy stop')
            self.stopped.update(names)
        if is_handoff(argv):
            self.assertTrue(self.user_stopped)
            self.assertEqual(argv, ['/usr/bin/systemctl', '--force', self.worker.action])
        return ''

    def stop_index(self, name):
        return next(i for i, command in enumerate(self.calls) if 'stop' in command and name in command)

    def assert_no_force(self):
        self.assertFalse(any(is_handoff(command) for command in self.calls))
        self.assertFalse(self.worker.handoff_attempted)

    def test_desktop_and_greeter_both_actions_drain_in_order(self):
        for action in ('poweroff', 'reboot'):
            for greeter in (False, True):
                with self.subTest(action=action, greeter=greeter):
                    self.reset(action, greeter)
                    self.worker.execute()
                    indices = [self.stop_index(name) for name in (
                        self.mounts[-1], 'nfs-server.service', 'nfs-idmapd.service', 'greetd.service')]
                    indices += [next(i for i, c in enumerate(self.calls) if 'terminate-user' in c)]
                    indices += [self.stop_index(name) for name in (
                        'zram-writebackd.service', 'zram-setup.service', 'swap-fallback.service')]
                    self.assertEqual(indices, sorted(set(indices)))
                    mount_stop = self.calls[indices[0]]
                    self.assertEqual(set(mount_stop[3:]), set(self.mounts))
                    self.assertEqual(sum(is_handoff(c) for c in self.calls), 1)
                    self.assertTrue(self.worker.session_stopped and self.worker.storage_stopped)
                    self.assertEqual(self.calls[-1], ['/usr/bin/systemctl', '--force', action])

    def test_busy_mount_preserves_session_and_blocks_handoff(self):
        self.stop_error = self.mounts[-1]
        with self.assertRaisesRegex(self.power.Error, 'busy'):
            self.worker.execute()
        self.assert_no_force()
        self.assertFalse(self.user_stopped or self.worker.committed)
        self.assertNotIn('nfs-server.service', self.stopped)

    def test_failed_stop_transport_or_result_never_authorizes_force(self):
        for name in ('nfs-server.service', 'greetd.service', 'zram-setup.service', 'swap-fallback.service'):
            for field in ('stop_error', 'stop_result_error'):
                with self.subTest(name=name, fault=field):
                    self.reset()
                    setattr(self, field, name)
                    with self.assertRaises(self.power.Error):
                        self.worker.execute()
                    self.assert_no_force()
                    if name == 'zram-setup.service':
                        self.assertNotIn('swap-fallback.service', self.stopped)

    def test_save_veto_precedes_all_storage_operations(self):
        self.veto = True
        with self.assertRaises(self.power.Cancelled):
            self.worker.execute()
        self.assertEqual(self.stopped, set())
        self.assertFalse(self.user_stopped)
        self.assert_no_force()

    def test_session_replacement_during_unmount_is_rejected(self):
        self.identity.side_effect = ['a' * 32] * 3 + ['b' * 32]
        with self.assertRaisesRegex(self.power.Error, 'session changed'):
            self.worker.execute()
        self.assertFalse(self.user_stopped or self.worker.committed)
        self.assert_no_force()

    def test_user_teardown_failure_prevents_swap_teardown(self):
        with mock.patch.object(self.worker, 'terminate_user', side_effect=self.power.Error('slice busy')):
            with self.assertRaisesRegex(self.power.Error, 'slice busy'):
                self.worker.execute()
        self.assertNotIn('zram-setup.service', self.stopped)
        self.assert_no_force()

    def test_new_login_or_restarted_storage_prevents_final_handoff(self):
        self.late_login = True
        with self.assertRaisesRegex(self.power.Error, 'login session'):
            self.worker.execute()
        self.assert_no_force()
        self.reset()
        self.restart = 'zram-setup.service'
        with self.assertRaisesRegex(self.power.Error, 'did not complete'):
            self.worker.execute()
        self.assert_no_force()

    def test_absent_optional_units_are_never_started(self):
        self.absent.update((*self.power.ZRAM_WORK_UNITS, 'swap-fallback.service'))
        self.worker.execute()
        self.assertTrue(self.absent.isdisjoint(self.stopped))
        self.assertFalse(any('start' in c and '--user' not in c for c in self.calls))

    def test_prepared_flag_alone_cannot_bypass_storage_cleanup(self):
        self.worker.prepared = True
        self.worker.package_locks = mock.Mock()
        with self.assertRaisesRegex(self.power.Error, 'teardown'):
            self.worker.final_power_action()
        self.assert_no_force()


if __name__ == '__main__':
    unittest.main()
