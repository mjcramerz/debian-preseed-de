"""Rootless design regressions; no account, systemd, package or container mutations.

Root-only filesystem fixtures are created in a private temporary directory.
Incus HTTP behavior uses a real AF_UNIX loopback server or an in-memory API.
"""
from __future__ import annotations
import copy
import http.server
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import stat
import subprocess
import tempfile
import threading
import time
import tomllib
import types
import unittest
from unittest import mock

from test_environment import skip_unless_filesystem_unix_socket

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
TEMPLATES = TARGET / 'data/config/podman/templates/devops'


def load(relative):
    path = TARGET / relative
    module = types.ModuleType('redesign_' + path.name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


HOST = load('usr/local/libexec/podman-devops-host')
CLIENT = load('usr/local/libexec/podman-devops-client')
MENU = load('usr/local/bin/labwc-podman-menu')
INCUS = load('usr/local/libexec/incus-host-managed')
CONFIG = {'INCUS_MANAGED_POOL_NAME': 'local',
          'INCUS_MANAGED_POOL_PATH': '/pool/incus',
          'INCUS_MANAGED_BRIDGE_NAME': 'incusbr0',
          'INCUS_MANAGED_BRIDGE_IPV4': 'auto',
          'INCUS_MANAGED_BRIDGE_IPV6': 'none',
          'INCUS_MANAGED_WAIT_SECONDS': '60',
          'INCUS_MANAGED_RETRY_DELAY_SECONDS': '3'}


def config_text(config=None):
    return '\n'.join(f'{k}="{v}"' for k, v in (config or CONFIG).items()) + '\n'


class SubordinateIDTests(unittest.TestCase):
    def test_comments_and_numeric_identity(self):
        self.assertEqual(HOST.subid_rows('# comment\n999:131072:65536\n'), [('999', 131072, 65536)])

    def test_malformed_ranges(self):
        for raw in ('u:x:3', 'u:0:3', 'u:3:0', 'u:4294967294:2', 'u:2:3:4'):
            with self.subTest(raw=raw), self.assertRaises(HOST.Failure):
                HOST.subid_rows(raw)

    def test_new_range_is_aligned_and_disjoint(self):
        self.assertEqual(HOST.choose_subids([('other', 100000, 65536)], 999, {0, 1000}), (196608, 65536, True))

    def test_new_range_skips_real_accounts(self):
        self.assertEqual(HOST.choose_subids([], 999, {131072})[0], 196608)

    def test_existing_valid_range_is_preserved(self):
        self.assertEqual(HOST.choose_subids([('devops', 100000, 65536)], 999, {0, 999}), (100000, 65536, False))

    def test_numeric_owner_is_preserved(self):
        self.assertFalse(HOST.choose_subids([('999', 131072, 65536)], 999, {999})[2])

    def test_existing_overlap_is_fatal(self):
        with self.assertRaises(HOST.Failure):
            HOST.choose_subids([('devops', 100000, 65536), ('other', 150000, 65536)], 999, {999})

    def test_duplicate_identity_ranges_are_fatal(self):
        with self.assertRaises(HOST.Failure):
            HOST.choose_subids([('devops', 100000, 65536), ('999', 200000, 65536)], 999, {999})

    def test_small_low_or_real_account_collision_is_fatal(self):
        for row, actual in [(('devops', 10, 65536), set()), (('devops', 100000, 2), set()),
                            (('devops', 100000, 65536), {100001})]:
            with self.subTest(row=row), self.assertRaises(HOST.Failure):
                HOST.choose_subids([row], 999, actual)

    def test_range_exhaustion_is_fatal(self):
        with self.assertRaises(HOST.Failure):
            HOST.choose_subids([('other', HOST.MAX_ID - 65535, 65536)], 999, set())


@unittest.skipUnless(os.geteuid() == 0, 'root-owned file fixtures require root')
class AtomicHostFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='podman-design-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = self.base / 'config'

    def test_atomic_write_is_private_and_idempotent(self):
        self.assertTrue(HOST.atomic_write(self.path, b'first', 0o640))
        before = self.path.stat()
        self.assertFalse(HOST.atomic_write(self.path, b'first', 0o640))
        self.assertEqual(self.path.stat().st_ino, before.st_ino)
        self.assertEqual(stat.S_IMODE(before.st_mode), 0o640)
        self.assertEqual(before.st_uid, 0)

    def test_interrupted_replace_preserves_old_file(self):
        HOST.atomic_write(self.path, b'first')
        with mock.patch.object(HOST.os, 'replace', side_effect=OSError('injected')):
            with self.assertRaises(OSError):
                HOST.atomic_write(self.path, b'new')
        self.assertEqual(self.path.read_bytes(), b'first')
        self.assertEqual(list(self.base.iterdir()), [self.path])

    def test_symlink_leaf_is_rejected(self):
        real = self.base / 'real'; real.write_text('original')
        self.path.symlink_to(real)
        with self.assertRaises(HOST.Failure):
            HOST.atomic_write(self.path, b'bad')
        self.assertEqual(real.read_text(), 'original')

    def test_symlink_parent_is_rejected(self):
        real = self.base / 'real'; real.mkdir()
        self.path.symlink_to(real, target_is_directory=True)
        with self.assertRaises(HOST.Failure):
            HOST.atomic_write(self.path / 'file', b'bad')

    def test_hardlinked_file_is_rejected(self):
        self.path.write_text('original'); self.path.chmod(0o644)
        os.link(self.path, self.base / 'alias')
        with self.assertRaises(HOST.Failure):
            HOST.atomic_write(self.path, b'bad')

    def test_group_writable_file_is_rejected(self):
        self.path.write_text('original'); self.path.chmod(0o664)
        with self.assertRaises(HOST.Failure):
            HOST.read_root_file(self.path)

    def test_group_writable_parent_requires_sticky(self):
        self.base.chmod(0o775)
        with self.assertRaises(HOST.Failure):
            HOST.atomic_write(self.path, b'bad')
        self.base.chmod(0o1775)
        self.assertTrue(HOST.atomic_write(self.path, b'ok'))

    def test_unrelated_directory_owner_is_not_taken_over(self):
        self.path.mkdir(); os.chown(self.path, 65534, 65534)
        with self.assertRaises(HOST.Failure):
            HOST.directory(self.path, 0o700, 12345, 12345)

    def test_existing_private_data_is_not_recursively_chowned(self):
        self.path.mkdir(); child = self.path / 'data'; child.write_text('keep')
        child.chmod(0o600); os.chown(child, 65534, 65534)
        HOST.directory(self.path, 0o700)
        self.assertEqual(child.stat().st_uid, 65534)
        self.assertEqual(child.read_text(), 'keep')

    def test_unit_links_are_idempotent_and_conflicts_refused(self):
        HOST.atomic_link(self.path, '/dev/null')
        HOST.atomic_link(self.path, '/dev/null')
        with self.assertRaises(HOST.Failure):
            HOST.atomic_link(self.path, '/other')

    def test_file_size_limit(self):
        self.path.write_bytes(b'x' * (4 * 1024 * 1024 + 1)); self.path.chmod(0o644)
        with self.assertRaises(HOST.Failure):
            HOST.read_root_file(self.path)


class HostPolicyTests(unittest.TestCase):
    def test_native_drivers_and_no_unsafe_fallback(self):
        for filesystem in ('ext2/ext3', 'xfs', 'f2fs', 'btrfs'):
            self.assertEqual(HOST.driver_for(filesystem, 'auto'), 'overlay')
        self.assertEqual(HOST.driver_for('btrfs', 'btrfs'), 'btrfs')
        for filesystem, requested in (('nfs', 'auto'), ('overlayfs', 'auto'), ('xfs', 'btrfs'), ('xfs', 'vfs')):
            with self.subTest(filesystem=filesystem, requested=requested), self.assertRaises(HOST.Failure):
                HOST.driver_for(filesystem, requested)

    def test_podman_minimum_and_modern_versions(self):
        for version in ('5.8.6', '5.8.10', '6.0.0'):
            with mock.patch.object(HOST, 'run', return_value='podman version ' + version):
                HOST.require_podman_version()
        for version in ('5.8.5', '4.9.3', 'unknown'):
            with mock.patch.object(HOST, 'run', return_value='podman version ' + version), self.assertRaises(HOST.Failure):
                HOST.require_podman_version()

    def test_legacy_account_refused_before_any_write(self):
        with mock.patch.object(HOST.pwd, 'getpwnam', return_value=object()), mock.patch.object(HOST, 'run') as run:
            with self.assertRaisesRegex(HOST.Failure, 'legacy'):
                HOST.account(True)
            run.assert_not_called()

    def test_service_account_creation_never_creates_a_home_or_copies_a_skeleton(self):
        group = types.SimpleNamespace(gr_gid=123)
        user = types.SimpleNamespace(pw_uid=999, pw_gid=123, pw_dir=str(HOST.HOME),
                                     pw_shell=HOST.NOLOGIN)
        seen_devops = 0

        def lookup(name):
            nonlocal seen_devops
            if name == 'podsvc':
                raise KeyError(name)
            self.assertEqual(name, HOST.USER)
            seen_devops += 1
            if seen_devops == 1:
                raise KeyError(name)
            return user

        with mock.patch.object(HOST.pwd, 'getpwnam', side_effect=lookup), \
             mock.patch.object(HOST.grp, 'getgrnam', return_value=group), \
             mock.patch.object(HOST.os, 'getgrouplist', return_value=[123]), \
             mock.patch.object(HOST, 'password_locked', return_value=True), \
             mock.patch.object(HOST, 'run') as run:
            self.assertEqual(HOST.account(True), (999, 123))
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], '/usr/sbin/useradd')
        self.assertIn('--system', argv)
        self.assertIn('--no-create-home', argv)
        self.assertNotIn('--create-home', argv)
        self.assertNotIn('--skel', argv)
        self.assertEqual(argv[argv.index('--shell') + 1], HOST.NOLOGIN)
        self.assertEqual(argv[argv.index('--home-dir') + 1], '/nonexistent')

    def test_existing_system_account_is_reconciled_to_locked_nologin(self):
        group = types.SimpleNamespace(gr_gid=123)
        users = iter((
            types.SimpleNamespace(pw_uid=999, pw_gid=234, pw_dir=str(HOST.HOME),
                                  pw_shell='/bin/bash'),
            types.SimpleNamespace(pw_uid=999, pw_gid=123, pw_dir=str(HOST.HOME),
                                  pw_shell=HOST.NOLOGIN),
        ))

        def lookup(name):
            if name == 'podsvc':
                raise KeyError(name)
            return next(users)

        with mock.patch.object(HOST.pwd, 'getpwnam', side_effect=lookup), \
             mock.patch.object(HOST.grp, 'getgrnam', return_value=group), \
             mock.patch.object(HOST.os, 'getgrouplist', side_effect=([234, 777], [123])), \
             mock.patch.object(HOST, 'password_locked', return_value=True), \
             mock.patch.object(HOST, 'run') as run:
            self.assertEqual(HOST.account(True), (999, 123))
        run.assert_called_once_with(['/usr/sbin/usermod', '--shell', HOST.NOLOGIN,
                                     '--gid', HOST.USER, '--groups', '', '--lock', HOST.USER])

    def test_regular_login_identity_named_devops_is_never_taken_over(self):
        group = types.SimpleNamespace(gr_gid=123)
        user = types.SimpleNamespace(pw_uid=1000, pw_gid=123, pw_dir=str(HOST.HOME),
                                     pw_shell=HOST.NOLOGIN)

        def lookup(name):
            if name == 'podsvc':
                raise KeyError(name)
            return user

        with mock.patch.object(HOST.pwd, 'getpwnam', side_effect=lookup), \
             mock.patch.object(HOST.grp, 'getgrnam', return_value=group), \
             mock.patch.object(HOST, 'run') as run, \
             self.assertRaisesRegex(HOST.Failure, 'login account'):
            HOST.account(True)
        run.assert_not_called()

    def test_service_account_rejects_home_and_legacy_home_state(self):
        with tempfile.TemporaryDirectory(prefix='podman-no-home-') as name:
            root = Path(name)
            home = root / 'nonexistent'
            legacy = root / 'legacy-home'
            with mock.patch.object(HOST, 'HOME', home), \
                 mock.patch.object(HOST, 'LEGACY_HOME', legacy):
                HOST.reject_service_account_home()
                home.mkdir()
                with self.assertRaisesRegex(HOST.Failure, 'must not have a home'):
                    HOST.reject_service_account_home()
                home.rmdir()
                legacy.mkdir()
                with self.assertRaisesRegex(HOST.Failure, 'must not have a home'):
                    HOST.reject_service_account_home()

    def test_service_account_user_manager_state_is_forbidden(self):
        with tempfile.TemporaryDirectory(prefix='podman-no-user-manager-') as name:
            root = Path(name)
            home = root / 'home'
            runtime_root = root / 'run-user'
            home.mkdir()
            runtime_root.mkdir()
            with mock.patch.object(HOST, 'HOME', home), \
                 mock.patch.object(HOST, 'USER_RUNTIME_ROOT', runtime_root):
                HOST.reject_user_manager_state(424242)
                (home / '.config/systemd').mkdir(parents=True)
                with self.assertRaisesRegex(HOST.Failure, 'user manager'):
                    HOST.reject_user_manager_state(424242)
                (home / '.config/systemd').rmdir()
                (home / '.config').rmdir()
                runtime_user = runtime_root / '424242'
                runtime_user.mkdir()
                (runtime_user / 'bus').touch()
                with self.assertRaisesRegex(HOST.Failure, 'user manager'):
                    HOST.reject_user_manager_state(424242)
                (runtime_user / 'bus').unlink()
                (runtime_user / 'systemd').mkdir()
                with self.assertRaisesRegex(HOST.Failure, 'user manager'):
                    HOST.reject_user_manager_state(424242)

    def test_preflight_does_not_acquire_activation_lock(self):
        with mock.patch.object(HOST.os, 'geteuid', return_value=0), mock.patch.object(HOST.sys, 'argv', ['host', 'verify-start']), \
             mock.patch.object(HOST, 'load_and_validate') as validate, mock.patch.object(HOST, 'locked') as lock:
            self.assertEqual(HOST.main(), 0)
            validate.assert_called_once(); lock.assert_not_called()

    def test_run_failure_includes_status_not_false_success(self):
        with self.assertRaisesRegex(HOST.Failure, 'exited 17'):
            HOST.run(['/bin/sh', '-c', 'printf failed >&2; exit 17'])

    def test_timeout_cleans_up_process_group(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            HOST.run(['/bin/sh', '-c', 'sleep 30 & wait'], timeout=0.05)

    def test_timeout_also_reaps_descendant_after_leader_exit(self):
        with tempfile.TemporaryDirectory() as root:
            survivor = Path(root) / 'descendant-survived'
            command = '(sleep 0.5; printf survived > "$1") & exit 0'
            with self.assertRaises(subprocess.TimeoutExpired):
                HOST.run(['/bin/sh', '-c', command, 'sh', str(survivor)], timeout=0.05)
            # A live descendant creates the marker after the original leader has
            # exited. This remains valid when the test runner and /proc expose
            # different PID namespaces, unlike indexing /proc by shell $!.
            time.sleep(0.7)
            self.assertFalse(survivor.exists(), 'timed-out descendant survived cleanup')

    def test_resource_parser_validation(self):
        for good in ('1%', '70%', '100%'):
            self.assertEqual(HOST.percentage(good), good)
        for bad in ('0%', '101%', '1G', '$(id)', '70.5%'):
            with self.assertRaises(Exception):
                HOST.percentage(bad)


class ClientTests(unittest.TestCase):
    def test_native_environment_preserves_desktop_identity(self):
        source = {'HOME': '/home/alice', 'USER': 'alice', 'XDG_RUNTIME_DIR': '/run/user/1000',
                  'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}
        output = CLIENT.environment(source)
        for key, value in source.items():
            self.assertEqual(output[key], value)
        self.assertEqual(output['CONTAINER_HOST'], CLIENT.URI)
        self.assertEqual(output['DOCKER_HOST'], CLIENT.URI)
        self.assertEqual(output['REGISTRY_AUTH_FILE'], '/home/alice/.config/containers/auth.json')
        self.assertEqual(output['DOCKER_CONFIG'], '/home/alice/.config/docker')

    def test_conflicting_selectors_removed_without_mutating_input(self):
        source = {key: 'untrusted' for key in CLIENT.SELECTORS}
        output = CLIENT.environment(source)
        for key in CLIENT.SELECTORS:
            self.assertNotIn(key, output)
            self.assertIn(key, source)

    def test_explicit_client_credentials_remain_client_owned(self):
        output = CLIENT.environment({'HOME': '/home/a', 'REGISTRY_AUTH_FILE': '/home/a/custom-auth', 'DOCKER_CONFIG': '/home/a/docker'})
        self.assertEqual(output['REGISTRY_AUTH_FILE'], '/home/a/custom-auth')
        self.assertEqual(output['DOCKER_CONFIG'], '/home/a/docker')

    def test_argv_is_preserved_without_shell_evaluation(self):
        args = ['run', '--name', 'literal;echo BAD', 'localhost/image', 'sh', '-c', 'printf "$HOME"']
        self.assertEqual(CLIENT.command('podman', args)[3:], args)
        self.assertEqual(CLIENT.command('docker', args)[2:], args)
        self.assertEqual(CLIENT.command('docker-compose', args)[1:], args)

    def test_common_endpoint_overrides_are_refused(self):
        for tool, flag in [('podman', '--remote=false'), ('podman', '--url=unix:///tmp/a'),
                           ('podman', '--connection=x'), ('podman', '-cother'), ('podman', '-r=false'),
                           ('docker', '-cother'), ('docker', '-Htcp://bad'),
                           ('docker', '--context=bad'), ('docker-compose', '--host=bad')]:
            with self.subTest(tool=tool, flag=flag), self.assertRaises(ValueError):
                CLIENT.command(tool, [flag, 'ps'])

    def test_endpoint_overrides_after_separate_global_values_are_refused(self):
        cases = [('podman', ['--log-level', 'debug', '--url=unix:///tmp/other', 'ps']),
                 ('docker', ['--config', '/home/a/config', '--host=unix:///tmp/other', 'ps']),
                 ('docker-compose', ['-f', 'compose.yaml', '--context=other', 'ps'])]
        for tool, args in cases:
            with self.subTest(tool=tool), self.assertRaises(ValueError):
                CLIENT.command(tool, args)

    def test_separate_global_values_and_container_arguments_are_preserved(self):
        cases = [('podman', ['--log-level', 'debug', 'run', 'image', '--url=x']),
                 ('docker', ['--config', '/home/a/config', 'run', 'image', '-c', 'echo ok']),
                 ('docker-compose', ['-f', 'compose.yaml', 'exec', 'app', '--host=x']),
                 ('podman', ['--', 'run', 'image', '--connection=x'])]
        for tool, args in cases:
            with self.subTest(tool=tool):
                self.assertEqual(CLIENT.command(tool, args)[-len(args):], args)

    def test_missing_separate_global_value_is_diagnostic(self):
        for tool, arg in [('podman', '--log-level'), ('docker', '--config'), ('docker-compose', '-f')]:
            with self.subTest(tool=tool), self.assertRaisesRegex(ValueError, 'requires a value'):
                CLIENT.command(tool, [arg])

    def test_container_command_options_not_misinterpreted_as_client_options(self):
        self.assertIn('--host', CLIENT.command('podman', ['run', 'image', '--host']))

    def test_unknown_tool_and_root_rejected(self):
        with self.assertRaises(ValueError):
            CLIENT.command('sh', [])
        with mock.patch.object(CLIENT.os, 'geteuid', return_value=0), self.assertRaises(ValueError):
            CLIENT.validate_access()

    def test_socket_missing_does_not_start_an_engine(self):
        with tempfile.TemporaryDirectory() as root:
            fake = Path(root) / 'absent'
            with mock.patch.object(CLIENT, 'SOCKET', fake), mock.patch.object(CLIENT.os, 'geteuid', return_value=1000), \
                 mock.patch.object(CLIENT.os, 'getgroups', return_value=[123]), mock.patch.object(CLIENT.os, 'getegid', return_value=1000), \
                 mock.patch.object(CLIENT.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=999)), \
                 mock.patch.object(CLIENT.grp, 'getgrnam', return_value=types.SimpleNamespace(gr_gid=123)), self.assertRaises(FileNotFoundError):
                CLIENT.validate_access()

    def test_socket_group_membership_required(self):
        with mock.patch.object(CLIENT.os, 'geteuid', return_value=1000), mock.patch.object(CLIENT.os, 'getgroups', return_value=[]), \
             mock.patch.object(CLIENT.os, 'getegid', return_value=1000), mock.patch.object(CLIENT.pwd, 'getpwnam', return_value=object()), \
             mock.patch.object(CLIENT.grp, 'getgrnam', return_value=types.SimpleNamespace(gr_gid=123)), self.assertRaisesRegex(ValueError, 'lacks group'):
            CLIENT.validate_access()


class FuzzelTests(unittest.TestCase):
    def test_labels_strip_control_characters(self):
        self.assertEqual(MENU.text('abc\n\x1bdef'), 'abc??def')

    def test_menu_rejects_freeform_selection(self):
        result = subprocess.CompletedProcess([], 0, 'rm everything\n')
        with mock.patch.object(MENU.subprocess, 'run', return_value=result):
            self.assertIsNone(MENU.menu('choose', ['safe']))

    def test_cancel_does_not_confirm(self):
        with mock.patch.object(MENU, 'menu', return_value=None):
            self.assertFalse(MENU.confirm('Delete object'))

    def test_ids_are_hex_only(self):
        self.assertEqual(MENU.identifier({'Id': 'sha256:' + 'a' * 64}), 'a' * 64)
        for invalid in ('abc', 'a;id', '--all', '../bad'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MENU.identifier({'Id': invalid})

    def test_object_records_validate_type(self):
        with mock.patch.object(MENU, 'execute', return_value='{"bad": 1}'), self.assertRaises(ValueError):
            MENU.records('ps')

    def test_null_records_are_empty(self):
        with mock.patch.object(MENU, 'execute', return_value='null'):
            self.assertEqual(MENU.records('ps'), [])

    def test_image_and_object_inputs_cannot_inject_flags_or_shell(self):
        for invalid in ('--privileged', 'docker.io/a;id', 'docker.io/a\nBAD'):
            with mock.patch.object(MENU, 'entry', return_value=invalid), self.assertRaises(ValueError):
                MENU.image_name('image')
        with mock.patch.object(MENU, 'entry', return_value='x;id'), self.assertRaises(ValueError):
            MENU.create_object('network')

    def test_terminal_launch_is_argv_only(self):
        with mock.patch.object(MENU.subprocess, 'Popen') as popen:
            MENU.terminal('podman', 'build', '/tmp/path with spaces;literal')
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-1], '/tmp/path with spaces;literal')
        self.assertNotIn('shell', popen.call_args.kwargs)
        self.assertNotIn('sudo', argv)

    def test_private_runtime_lock_rejects_second_holder(self):
        with tempfile.TemporaryDirectory() as runtime, mock.patch.dict(MENU.os.environ, {'XDG_RUNTIME_DIR': runtime}):
            fd = MENU.runtime_lock()
            try:
                with self.assertRaises(BlockingIOError):
                    MENU.runtime_lock()
            finally:
                os.close(fd)
            self.assertTrue((Path(runtime) / 'labwc-podman-menu.lock').exists())

    def test_runtime_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as runtime:
            link = Path(runtime) / 'alias'; link.symlink_to(runtime)
            with mock.patch.dict(MENU.os.environ, {'XDG_RUNTIME_DIR': str(link)}), self.assertRaises(ValueError):
                MENU.runtime_lock()


class IncusConfigurationTests(unittest.TestCase):
    def test_valid_native_configuration(self):
        self.assertEqual(INCUS.parse_config(config_text()), CONFIG)

    def test_staged_template_renders_to_valid_configuration(self):
        text = (TARGET / 'etc/default/incus-host-managed.tmpl').read_text()
        text = text.replace('__INSTALLER_DIR_POOL_INCUS__', '/pool/incus').replace('__INSTALLER_INCUS_BRIDGE_NAME__', 'incusbr0')
        self.assertEqual(INCUS.parse_config(text), CONFIG)

    def test_shell_evaluation_and_unknown_keys_refused(self):
        for suffix in ('\ntouch /tmp/never', '\nEVIL="x"', '\nINCUS_MANAGED_POOL_NAME="other"'):
            with self.subTest(suffix=suffix), self.assertRaises(INCUS.Failure):
                INCUS.parse_config(config_text() + suffix)

    def test_path_traversal_and_shell_substitution_refused(self):
        for path in ('/pool/../etc', '/pool//incus', '/pool/incus/', '/etc', '/pool/$(id)', '/pool'):
            config = dict(CONFIG, INCUS_MANAGED_POOL_PATH=path)
            with self.subTest(path=path), self.assertRaises(INCUS.Failure):
                INCUS.parse_config(config_text(config))

    def test_invalid_address_family_and_time_bounds_refused(self):
        for key, value in [('INCUS_MANAGED_BRIDGE_IPV4', '::1/64'), ('INCUS_MANAGED_BRIDGE_IPV6', 'bad'),
                           ('INCUS_MANAGED_WAIT_SECONDS', '999'), ('INCUS_MANAGED_RETRY_DELAY_SECONDS', '0')]:
            config = dict(CONFIG); config[key] = value
            with self.subTest(key=key), self.assertRaises(INCUS.Failure):
                INCUS.parse_config(config_text(config))

    def test_validate_mode_does_not_write_or_call_api(self):
        with mock.patch.object(INCUS.os, 'geteuid', return_value=0), mock.patch.object(INCUS.sys, 'argv', ['incus-host', '--validate-config']), \
             mock.patch.object(INCUS, 'validate_static', return_value=CONFIG), mock.patch.object(INCUS, 'locked') as lock, \
             mock.patch.object(INCUS, 'API') as api, mock.patch.object(INCUS, 'prepare_storage') as prepare:
            self.assertEqual(INCUS.main(), 0)
            lock.assert_not_called(); api.assert_not_called(); prepare.assert_not_called()

    def test_prepare_mode_does_not_activate_api(self):
        with mock.patch.object(INCUS.os, 'geteuid', return_value=0), mock.patch.object(INCUS.sys, 'argv', ['incus-host', '--prepare-install']), \
             mock.patch.object(INCUS, 'validate_static', return_value=CONFIG), mock.patch.object(INCUS, 'locked'), \
             mock.patch.object(INCUS, 'API') as api, mock.patch.object(INCUS, 'prepare_storage') as prepare:
            self.assertEqual(INCUS.main(), 0)
            api.assert_not_called(); prepare.assert_called_once_with(CONFIG)


class FakeAPI:
    def __init__(self):
        self.state = {'/1.0': {'config': {}}, '/1.0/profiles/default': {'description': 'keep', 'config': {'user.note': 'retain'}, 'devices': {}}}
        self.writes = []
        self.conflicts = 0

    def get(self, path):
        if path not in self.state:
            raise INCUS.HTTPFailure(404, 'not found')
        return copy.deepcopy(self.state[path]), '"v1"'

    def exists(self, path):
        return copy.deepcopy(self.state.get(path))

    def create(self, path, payload):
        self.writes.append(('POST', path))
        value = copy.deepcopy(payload)
        if path == '/1.0/networks':
            value['managed'] = True
            if value['config']['ipv4.address'] == 'auto':
                value['config']['ipv4.address'] = '10.123.0.1/24'
        self.state[path + '/' + value['name']] = value

    def mutate(self, method, path, payload, etag=None):
        if etag != '"v1"':
            raise AssertionError('missing expected ETag')
        self.writes.append((method, path))
        if self.conflicts:
            self.conflicts -= 1
            raise INCUS.HTTPFailure(412, 'changed')
        self.state[path] = copy.deepcopy(payload)


class IncusReconciliationTests(unittest.TestCase):
    def test_empty_host_is_initialized_and_rerun_is_noop(self):
        api = FakeAPI(); INCUS.reconcile(api, CONFIG)
        self.assertEqual(len(api.writes), 3)
        profile = api.state['/1.0/profiles/default']
        self.assertEqual(profile['config']['user.note'], 'retain')
        self.assertEqual(profile['config']['security.privileged'], 'false')
        self.assertEqual(profile['devices']['root']['pool'], 'local')
        api.writes.clear(); INCUS.reconcile(api, CONFIG)
        self.assertEqual(api.writes, [])

    def test_existing_pool_does_not_skip_missing_network_or_profile(self):
        api = FakeAPI()
        api.state['/1.0/storage-pools/local'] = {'driver': 'dir', 'config': {'source': '/pool/incus'}}
        INCUS.reconcile(api, CONFIG)
        self.assertEqual([m for m, _ in api.writes], ['POST', 'PUT'])

    def test_remote_api_is_not_adopted(self):
        api = FakeAPI(); api.state['/1.0']['config']['core.https_address'] = '[::]:8443'
        with self.assertRaises(INCUS.Failure):
            INCUS.reconcile(api, CONFIG)
        self.assertFalse(api.writes)

    def test_wrong_storage_driver_or_source_is_not_overwritten(self):
        for pool in ({'driver': 'btrfs', 'config': {'source': '/pool/incus'}}, {'driver': 'dir', 'config': {'source': '/other'}}):
            api = FakeAPI(); api.state['/1.0/storage-pools/local'] = pool
            with self.subTest(pool=pool), self.assertRaises(INCUS.Failure):
                INCUS.reconcile(api, CONFIG)
            self.assertFalse(api.writes)

    def test_privileged_default_is_not_silently_reconfigured(self):
        api = FakeAPI(); api.state['/1.0/profiles/default']['config']['security.privileged'] = 'true'
        with self.assertRaises(INCUS.Failure):
            INCUS.reconcile(api, CONFIG)
        self.assertEqual(api.state['/1.0/profiles/default']['config']['security.privileged'], 'true')

    def test_conflicting_profile_device_is_not_overwritten(self):
        api = FakeAPI(); api.state['/1.0/profiles/default']['devices']['root'] = {'type': 'disk', 'pool': 'other'}
        with self.assertRaises(INCUS.Failure):
            INCUS.reconcile(api, CONFIG)

    def test_etag_conflict_retries_are_bounded(self):
        api = FakeAPI(); api.conflicts = 2
        INCUS.reconcile(api, CONFIG)
        self.assertEqual(sum(method == 'PUT' for method, _ in api.writes), 3)
        api = FakeAPI(); api.conflicts = 99
        with self.assertRaises(INCUS.HTTPFailure):
            INCUS.reconcile(api, CONFIG)
        self.assertEqual(sum(method == 'PUT' for method, _ in api.writes), 3)

    def test_missing_etag_prevents_profile_write(self):
        api = FakeAPI(); original = api.get
        api.get = lambda path: (original(path)[0], None)
        with self.assertRaisesRegex(INCUS.Failure, 'ETag'):
            INCUS.reconcile(api, CONFIG)
        self.assertNotIn(('PUT', '/1.0/profiles/default'), api.writes)

    def test_bridge_address_and_nat_are_validated(self):
        bridge = {'type': 'bridge', 'managed': True, 'config': {'ipv4.address': '10.5.0.1/24', 'ipv6.address': 'none', 'ipv4.nat': 'true'}}
        INCUS.verify_network(bridge, CONFIG)
        for key, value in [('ipv4.address', 'auto'), ('ipv4.nat', 'false'), ('ipv6.address', 'auto')]:
            wrong = copy.deepcopy(bridge); wrong['config'][key] = value
            with self.subTest(key=key), self.assertRaises(INCUS.Failure):
                INCUS.verify_network(wrong, CONFIG)

    def test_api_only_404_means_missing(self):
        api = INCUS.API()
        with mock.patch.object(api, 'get', side_effect=INCUS.HTTPFailure(404, 'absent')):
            self.assertIsNone(api.exists('/1.0/test'))
        for code in (401, 403, 409, 500, 503):
            with mock.patch.object(api, 'get', side_effect=INCUS.HTTPFailure(code, 'error')), self.assertRaises(INCUS.HTTPFailure):
                api.exists('/1.0/test')

    def test_only_create_conflict_is_deferred_to_verification(self):
        api = INCUS.API()
        with mock.patch.object(api, 'mutate', side_effect=INCUS.HTTPFailure(409, 'exists')):
            api.create('/1.0/networks', {})
        with mock.patch.object(api, 'mutate', side_effect=INCUS.HTTPFailure(503, 'offline')), self.assertRaises(INCUS.HTTPFailure):
            api.create('/1.0/networks', {})

    def test_async_operation_path_cannot_escape_local_endpoint(self):
        api = INCUS.API()
        for path in ('http://host/steal', '/1.0/../bad', '/1.0/operations/not-hex'):
            with mock.patch.object(api, 'request', return_value=({'type': 'async', 'operation': path}, None)), self.assertRaises(INCUS.Failure):
                api.mutate('POST', '/1.0/networks', {})

    def test_async_operation_success_and_failure(self):
        api = INCUS.API()
        with mock.patch.object(api, 'request', return_value=({'type': 'async', 'operation': '/1.0/operations/abcd-1234'}, None)), \
             mock.patch.object(api, 'get', return_value=({'status_code': 200}, None)):
            api.mutate('POST', '/1.0/networks', {})
        with mock.patch.object(api, 'request', return_value=({'type': 'async', 'operation': '/1.0/operations/abcd-1234'}, None)), \
             mock.patch.object(api, 'get', return_value=({'status_code': 400, 'err': 'injected'}, None)), self.assertRaises(INCUS.Failure):
            api.mutate('POST', '/1.0/networks', {})


class UnixHTTPTests(unittest.TestCase):
    @skip_unless_filesystem_unix_socket
    def test_real_unix_http_status_json_and_etag(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status = 404 if self.path.endswith('/missing') else 200
                body = b'{"error":"missing"}' if status == 404 else b'{"metadata":{"ok":true}}'
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('ETag', '"fixture"')
                self.end_headers(); self.wfile.write(body)
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as root:
            sock = Path(root) / 'api.sock'
            with socketserver.UnixStreamServer(str(sock), Handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    api = INCUS.API(sock)
                    self.assertEqual(api.get('/1.0'), ({'ok': True}, '"fixture"'))
                    self.assertIsNone(api.exists('/1.0/missing'))
                finally:
                    server.shutdown(); thread.join(timeout=2)


class IntegrationContractTests(unittest.TestCase):
    def test_desktop_skeleton_is_role_scoped_and_devops_has_no_skeleton(self):
        skeleton = TARGET / 'etc/skel-desktop'
        self.assertTrue(skeleton.is_dir())
        for relative in ('.profile', '.bashrc', '.config/labwc',
                         '.config/systemd/user/podman.service'):
            path = skeleton / relative
            if relative.endswith('podman.service'):
                self.assertFalse(path.exists())
            else:
                self.assertTrue(path.exists(), path)

        generic_skeleton = TARGET / 'etc/skel'
        self.assertFalse((generic_skeleton / 'primary').exists())
        self.assertFalse((generic_skeleton / 'devops').exists())
        hook = (FORKY / 'scripts/late/podman.sh').read_text()
        self.assertIn('etc/skel-desktop/.profile.d/71-devops-de.sh', hook)
        self.assertNotIn('etc/skel/devops/', hook)

    def test_engine_templates_are_valid_toml_with_correct_paths(self):
        containers = tomllib.loads((TEMPLATES / 'containers.conf.tmpl').read_text())
        storage = tomllib.loads(
            (TEMPLATES / 'storage.conf.tmpl').read_text().replace('@DRIVER@', 'overlay')
        )
        self.assertEqual(containers['engine']['cgroup_manager'], 'cgroupfs')
        self.assertEqual(containers['engine']['tmp_dir'],
                         '/run/podman-devops/libpod/tmp')
        self.assertEqual(containers['engine']['volume_path'], '/pool/podman/volumes')
        self.assertEqual(containers['network']['network_config_dir'],
                         '/pool/podman/networks')
        self.assertEqual(storage['storage']['graphroot'], '/pool/podman/storage')
        self.assertEqual(storage['storage']['runroot'], '/run/podman-devops/containers')
        client = tomllib.loads((TEMPLATES / 'client.conf').read_text())
        self.assertTrue(client['engine']['remote'])
        self.assertEqual(
            client['engine']['service_destinations']['devops']['uri'],
            'unix:///run/podman-devops/podman.sock',
        )
        self.assertNotIn('storage', client)
        tomllib.loads((TEMPLATES / 'registries.conf').read_text())

    def test_pid1_manages_the_rootless_service_without_a_user_manager(self):
        api = (TEMPLATES / 'podman-devops.service.tmpl').read_text()
        socket_unit = (TEMPLATES / 'podman-devops.socket').read_text()
        reboot = (TEMPLATES / 'podman-devops-restart.service.tmpl').read_text()
        for line in ('User=devops', 'Group=devops', 'Delegate=yes',
                     'RuntimeDirectory=podman-devops', 'ProtectHome=yes',
                     'Environment=HOME=/nonexistent',
                     'Environment=XDG_RUNTIME_DIR=/run/podman-devops',
                     'Environment=XDG_DATA_HOME=/pool/podman/xdg-data',
                     'Environment=XDG_CACHE_HOME=/pool/podman/xdg-cache',
                     'Environment=CONTAINERS_CONF=/etc/podman-devops/server/containers/containers.conf',
                     'Environment=CONTAINERS_STORAGE_CONF=/etc/podman-devops/server/containers/storage.conf',
                     'ExecStartPre=+/usr/local/libexec/podman-devops-host verify-start',
                     'CPUWeight=@CPU_WEIGHT@', 'IOWeight=@IO_WEIGHT@',
                     'TasksMax=@TASKS_MAX@', 'MemoryHigh=@MEMORY_HIGH@',
                     'MemoryMax=@MEMORY_MAX@'):
            self.assertIn(line, api)
        self.assertIn('KillMode=process', api)
        self.assertNotIn('NoNewPrivileges=yes', api)
        self.assertNotIn('/run/user/', api)
        self.assertNotIn('Environment=DBUS_SESSION_BUS_ADDRESS=', api)
        self.assertIn('ListenStream=/run/podman-devops/podman.sock', socket_unit)
        self.assertIn('SocketUser=devops', socket_unit)
        self.assertIn('SocketGroup=devops', socket_unit)
        self.assertIn('Service=podman-devops.service', socket_unit)
        self.assertIn('/usr/bin/podman --remote --url=unix:///run/podman-devops/podman.sock start', reboot)
        self.assertIn('--filter should-start-on-boot=true', reboot)
        self.assertIn('/usr/bin/podman --remote --url=unix:///run/podman-devops/podman.sock stop', reboot)
        self.assertIn('stop --service --all', reboot)
        self.assertFalse((TEMPLATES / 'user-manager.conf.tmpl').exists())
        self.assertFalse((TEMPLATES / 'user-slice.conf.tmpl').exists())
        self.assertFalse((TEMPLATES / 'podman.service.tmpl').exists())
        self.assertFalse((TEMPLATES / 'podman.socket').exists())
        bootstrap = (TARGET / 'etc/systemd/system/podman-devops-bootstrap.service').read_text()
        self.assertNotIn('systemd-logind.service', bootstrap)
        self.assertNotIn('systemd-user-sessions.service', bootstrap)
        self.assertNotIn('/run/user/', bootstrap)
        self.assertIn('Wants=podman-devops.socket', bootstrap)
        tmpfiles = (TARGET / 'etc/tmpfiles.d/55-podman-devops.conf').read_text()
        self.assertIn('d /run/podman-devops 0710 devops devops -', tmpfiles)

    def test_service_account_has_no_home_linger_user_units_or_desktop_inheritance(self):
        self.assertEqual(HOST.HOME, Path('/nonexistent'))
        self.assertEqual(HOST.LEGACY_HOME, Path('/data/accounts/devops'))
        self.assertFalse(hasattr(HOST, 'SERVICE_ACCOUNT_FORBIDDEN_HOME_PATHS'))
        self.assertFalse(hasattr(HOST, 'SERVICE_ACCOUNT_MASKED_USER_UNITS'))
        source = (TARGET / 'usr/local/libexec/podman-devops-host').read_text()
        self.assertIn('def reject_user_manager_state(uid: int)', source)
        self.assertIn("Path('/var/lib/systemd/linger') / USER", source)
        self.assertNotIn("'/usr/bin/loginctl'", source)
        self.assertNotIn("'/usr/bin/systemctl', '--user'", source)
        self.assertNotIn('systemctl --user', source)
        self.assertNotIn("HOME / '.config/systemd/user'", source)
        self.assertNotIn('/usr/sbin/runuser', source)
        self.assertIn("USER_RUNTIME_ROOT / str(uid) / 'bus'", source)
        self.assertIn("USER_RUNTIME_ROOT / str(uid) / 'systemd'", source)
        self.assertIn('def reject_service_account_home()', source)
        self.assertIn("raise Failure('/pool must be root:devops mode 3775')", source)
        firstboot = (FORKY / 'scripts/firstboot/04-validation.sh').read_text()
        self.assertIn('devops_processes=$(ps -U "$uid" -o comm=)', firstboot)
        for process in ('pipewire', 'wireplumber', 'mako', 'gpg-agent', 'ssh-agent',
                        'dbus-broker', 'hyprpolkitagen', 'xdg-desktop-por'):
            self.assertIn(process, firstboot)
        with mock.patch.object(HOST, 'run', return_value='') as run:
            HOST.service_command(['/usr/bin/true'])
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ['/usr/bin/env', '-i'])
        self.assertIn('HOME=/root', command)
        self.assertNotIn('HOME=/nonexistent', command)
        self.assertFalse(any(item.startswith('XDG_') for item in command))
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS=unix:', command)

        smoke_path = FORKY.parents[1] / 'tools/podman-incus-smoke.py'
        smoke = types.ModuleType('podman_incus_smoke')
        smoke.__file__ = str(smoke_path)
        exec(compile(smoke_path.read_bytes(), str(smoke_path), 'exec'), smoke.__dict__)
        self.assertFalse(hasattr(smoke, 'SERVICE_ACCOUNT_FORBIDDEN_HOME_PATHS'))
        self.assertFalse(hasattr(smoke, 'SERVICE_ACCOUNT_MASKED_USER_UNITS'))
        smoke_source = smoke_path.read_text()
        self.assertIn('0 < user.pw_uid < 1000', smoke_source)
        self.assertIn("user.pw_dir == '/nonexistent'", smoke_source)
        self.assertIn("Path('/data/accounts/devops')", smoke_source)
        self.assertIn("f'user@{user.pw_uid}.service'", smoke_source)
        self.assertIn("manager.returncode != 0", smoke_source)
        self.assertIn("Path('/var/lib/systemd/linger/devops')", smoke_source)
        self.assertIn("runtime_user = Path('/run/user') / str(user.pw_uid)", smoke_source)
        self.assertIn("unit_state('podman-devops.service')", smoke_source)
        self.assertNotIn('for unit in SERVICE_ACCOUNT_MASKED_USER_UNITS:', smoke_source)

    def test_no_container_sudo_bridge_or_container_ssh_credentials(self):
        sudo = (TARGET / 'etc/sudoers.d/account.tmpl').read_text()
        self.assertNotIn('PODBIN', sudo)
        self.assertNotIn('PODMAN_SERVICE', sudo)
        self.assertFalse((TARGET / 'usr/local/sbin/podbin.tmpl').exists())
        self.assertFalse((TARGET / 'data/config/podman/templates/rootless').exists())
        self.assertIn('DenyUsers devops', (FORKY / 'ssh/sshd_config').read_text())

    def test_selected_addon_installs_real_clients_and_profile(self):
        packages = (FORKY / 'classes/class-addon/podman.cfg').read_text()
        active = next(line for line in packages.splitlines() if line.startswith('d-i pkgsel/include string'))
        for package in ('podman', 'docker-cli', 'docker-compose', 'python3', 'uidmap', 'passt'):
            self.assertIn(package, active.split())
        self.assertNotIn('docker.io', active.split())
        self.assertNotIn('podman-docker', active.split())
        self.assertNotIn('dbus-user-session', active.split())
        hook = (FORKY / 'scripts/late/podman.sh').read_text()
        self.assertIn('install_target_account_shell_assets', hook)
        self.assertTrue((TARGET / 'data/docs/podman-devops.md').is_file())

    def test_all_host_profiles_use_devops(self):
        profiles = list((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertGreaterEqual(len(profiles), 13)
        for path in profiles:
            text = path.read_text()
            self.assertIn('PODMAN_USER="devops"', text)
            self.assertIn('PODMAN_USER_HOME="/nonexistent"', text)
            self.assertNotIn('PODMAN_USER="podsvc"', text)
            self.assertNotIn('/data/accounts/devops', text)

    def test_shared_pool_is_sticky_and_private_store_not_shared(self):
        tmpfiles = (TARGET / 'etc/tmpfiles.d/10-runtime-storage-roots.conf').read_text().replace('__INSTALLER_DIR_POOL__', '/pool').replace('__INSTALLER_DIR_POOL_PODMAN__', '/pool/podman')
        self.assertRegex(tmpfiles, r'd\s+/pool\s+3775\s+root\s+devops')
        self.assertRegex(tmpfiles, r'd\s+/pool/podman\s+0711\s+root\s+root')

    def test_profile_has_native_selectors_without_identity_impersonation(self):
        text = (TARGET / 'etc/skel-desktop/.profile.d/71-devops-de.sh').read_text().split('podman_devops_apply_environment() {', 1)[1]
        self.assertIn('CONTAINER_HOST=unix:///run/podman-devops/podman.sock', text)
        self.assertIn('DOCKER_HOST=$CONTAINER_HOST', text)
        self.assertIn('unset CONTAINER_CONNECTION', text)
        self.assertNotIn('\n  HOME=', text)
        self.assertNotIn('\n  XDG_RUNTIME_DIR=', text)
        self.assertNotIn('\n  CONTAINERS_STORAGE_CONF=', text)

    def test_bootstrap_has_no_service_user_bus_or_logind_dependency(self):
        text = (TARGET / 'etc/systemd/system/podman-devops-bootstrap.service').read_text()
        active = {line.split('=', 1)[0]: line.split('=', 1)[1]
                  for line in text.splitlines() if '=' in line and not line.lstrip().startswith('#')}
        self.assertEqual(active['ProtectHome'], 'yes')
        self.assertEqual(active['ProtectSystem'], 'strict')
        self.assertEqual(active['ReadWritePaths'], '/run/lock /run/podman-devops')
        self.assertEqual(active['NoNewPrivileges'], 'yes')
        self.assertNotIn('systemd-logind.service', text)
        self.assertNotIn('systemd-user-sessions.service', text)
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS', text)

    def test_incus_confined_group_is_not_elevated(self):
        qemu = (FORKY / 'scripts/late/qemu.sh').read_text()
        self.assertIn('incus-admin', qemu)
        self.assertNotIn('--append --groups incus-admin', qemu)
        dropin = (TARGET / 'etc/systemd/system/incus-user.service.d/20-managed-bootstrap.conf').read_text()
        self.assertIn('Requires=incus-host-managed.service', dropin)


if __name__ == '__main__':
    unittest.main()
