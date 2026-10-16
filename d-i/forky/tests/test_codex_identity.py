"""Codex identity/auth contracts; execute only in the prepared disposable image."""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import uuid

from payload_fixture import python_library

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / 'hooks/target/data/codex/lib/codex.tmpl'
_isolation_sys.path.insert(0, str(python_library(
    ROOT / 'hooks/target/usr/local/lib/python3.14/dist-packages'
)))
from labwc_managed_app import identity, project_identity


class CodexIdentityTests(unittest.TestCase):
    def setUp(self):
        self.c = types.ModuleType('codex_identity_fixture')
        self.c.__file__ = str(WRAPPER)
        exec(compile(WRAPPER.read_bytes(), str(WRAPPER), 'exec'), self.c.__dict__)
        temporary = tempfile.TemporaryDirectory(prefix='codex-identity-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.c.CODEX_RUNTIME_HOME = str(self.home)
        self.target = self.home / 'installation_id'
        self.target.write_bytes(b'')
        self.target.chmod(0o600)

    def require_file(self, path):
        self.c.codex_require_private_runtime_file('fixture state', str(path), 'fixture missing')

    def test_mount_data_uses_installer_target_without_modifying_it(self):
        original = b'old-installation-id\n'
        self.target.write_bytes(original)
        self.assertEqual(self.c.codex_installation_id_bind_arguments(123),
                         ['--perms', '0644', '--bind-data', '123', str(self.target)])
        self.assertEqual(self.target.read_bytes(), original)

    def test_missing_native_mount_target_is_initialized_independently(self):
        self.target.unlink()
        self.assertEqual(self.c.codex_installation_id_bind_arguments(None), [])
        self.assertFalse(self.target.exists())
        self.c.codex_installation_id_bind_arguments(123)
        native = self.target.read_text(encoding='ascii').strip()
        self.assertEqual(uuid.UUID(native).version, 4)
        self.c.codex_installation_id_bind_arguments(123)
        self.assertEqual(self.target.read_text(encoding='ascii').strip(), native)
        self.target.chmod(0o644)
        self.c.codex_installation_id_bind_arguments(123)
        self.assertEqual(self.target.read_text(encoding='ascii').strip(), native)
        self.assertEqual(self.target.stat().st_mode & 0o7777, 0o644)

    def test_mount_files_reject_symlinks_hardlinks_directories_and_public_modes(self):
        self.require_file(self.target)
        # A nested wrapper can receive Bubblewrap's already-unlinked data mount.
        metadata = self.target.stat()
        anonymous = types.SimpleNamespace(
            st_mode=metadata.st_mode, st_uid=metadata.st_uid, st_nlink=0,
        )
        with mock.patch.object(self.c.os, 'stat', return_value=anonymous):
            self.require_file(self.target)
        link = self.home / 'link'
        link.symlink_to(self.target)
        with self.assertRaises(self.c.CodexError):
            self.require_file(link)
        link.unlink()
        os.link(self.target, link)
        with self.assertRaises(self.c.CodexError):
            self.require_file(self.target)
        link.unlink()
        with self.assertRaises(self.c.CodexError):
            self.require_file(self.home)
        for mode in (0o640, 0o644, 0o660, 0o1600):
            self.target.chmod(mode)
            with self.subTest(mode=mode), self.assertRaises(self.c.CodexError):
                self.require_file(self.target)
        self.target.chmod(0o600)
        with mock.patch.object(self.c.os, 'getuid', return_value=os.getuid() + 1), \
                self.assertRaises(self.c.CodexError):
            self.require_file(self.target)

    def test_missing_auth_reports_explicit_login_mode(self):
        with self.assertRaisesRegex(self.c.CodexError, 'codex login'):
            self.c.codex_require_private_runtime_file(
                'Codex authentication state', str(self.home / 'auth.json'),
                'run codex login first',
            )
        self.assertFalse((self.home / 'auth.json').exists())

    def main_fixtures(self, stack):
        for name in ('codex_capture_app_server_environment', 'codex_prepare_environment',
                     'codex_restore_app_server_environment', 'codex_require_executable',
                     'codex_require_user_namespace_support', 'codex_require_managed_work_areas',
                     'codex_require_devops_shared_account_directory',
                     'codex_prepare_repository_metadata', 'codex_prepare_memory_area',
                     'codex_warn', 'codex_cleanup'):
            stack.enter_context(mock.patch.object(self.c, name))
        stack.enter_context(mock.patch.object(self.c.os, 'getuid', return_value=1000))
        stack.enter_context(mock.patch.object(self.c.os, 'geteuid', return_value=1000))
        stack.enter_context(mock.patch.object(self.c.signal, 'signal'))
        stack.enter_context(mock.patch.dict(os.environ, {'PATH': '/usr/bin:/bin'}, clear=True))
        stack.enter_context(mock.patch.object(self.c, 'codex_select_project_uuid',
                                             return_value='35ba8c1c-7d8d-4ceb-9e64-d4643fd2c926'))

    def test_each_mode_reuses_selected_uuid_and_closes_descriptor_on_return_and_error(self):
        values, descriptors = [], []
        def payload(descriptor):
            descriptors.append(descriptor)
            values.append(os.read(descriptor, 64).decode('ascii'))
            return 7
        with ExitStack() as stack:
            self.main_fixtures(stack)
            full = stack.enter_context(mock.patch.object(self.c, 'codex_run_sandboxed', side_effect=payload))
            direct = stack.enter_context(mock.patch.object(self.c, 'codex_run_identity_only', side_effect=payload))
            for arguments in (['exec', 'hello'], ['--no-bwrap', 'login']):
                self.assertEqual(self.c.main(arguments), 7)
                with self.assertRaises(OSError):
                    os.fstat(descriptors[-1])
            self.assertEqual(full.call_count, 1)
            self.assertEqual(direct.call_count, 1)
            self.assertEqual(len(set(values)), 1)
            for value in values:
                self.assertTrue(value.endswith('\n'))
                self.assertEqual(uuid.UUID(value.strip()).version, 4)
            for arguments, launch in (([], full), (['--no-bwrap', 'login'], direct)):
                def fail(descriptor):
                    descriptors.append(descriptor)
                    raise OSError('fixture launch failure')
                launch.side_effect = fail
                with self.assertRaisesRegex(OSError, 'fixture launch failure'):
                    self.c.main(arguments)
                with self.assertRaises(OSError):
                    os.fstat(descriptors[-1])
            self.assertEqual(self.c.codex_cleanup.call_count, 4)
        self.assertEqual(self.target.read_bytes(), b'')

    def test_no_override_uses_native_id_without_generating_anonymous_data(self):
        with ExitStack() as stack:
            self.main_fixtures(stack)
            stack.enter_context(mock.patch.object(self.c, 'codex_select_project_uuid', return_value=None))
            memory = stack.enter_context(mock.patch.object(self.c.os, 'memfd_create'))
            full = stack.enter_context(mock.patch.object(self.c, 'codex_run_sandboxed', return_value=7))
            self.assertEqual(self.c.main(['--profile', 'default']), 7)
            full.assert_called_once_with(None)
            memory.assert_not_called()
            direct = stack.enter_context(mock.patch.object(self.c, '_exec_raw_codex', side_effect=SystemExit(9)))
            with self.assertRaises(SystemExit) as result:
                self.c.main(['--no-bwrap', '--profile', 'default'])
            self.assertEqual(result.exception.code, 9)
            direct.assert_called_once_with()

    def test_new_uuid_is_a_wrapper_prefix_and_native_arguments_are_preserved(self):
        for arguments, expected in (
            (['--new-uuid', '--profile', 'default'], ['--profile', 'default']),
            (['--new-uuid', 'login'], ['login']),
            (['--no-bwrap', '--new-uuid', 'login'], ['login']),
        ):
            with self.subTest(arguments=arguments):
                self.c.codex_parse_arguments(arguments)
                self.assertTrue(self.c.CODEX_NEW_UUID)
                self.assertEqual(self.c.CODEX_ARGS, expected)
        for arguments in (['exec', '--new-uuid'], ['--', '--new-uuid'], ['a prompt', '--new-uuid']):
            self.c.codex_parse_arguments(arguments)
            self.assertFalse(self.c.CODEX_NEW_UUID)
            self.assertEqual(self.c.CODEX_ARGS, arguments)
        self.c.codex_parse_arguments(['--profile', 'default'])
        self.assertFalse(self.c.CODEX_NEW_UUID)

    def test_identity_only_passes_login_and_id_fd_without_auth_or_network_mounts(self):
        self.c.CODEX_USE_BWRAP = False
        self.c.CODEX_ARGS = ['login', '--device-auth']
        self.c.CODEX_SANDBOX_PATH = '/usr/bin:/bin'
        process = mock.Mock()
        process.wait.return_value = -2
        with mock.patch.object(self.c, 'codex_require_devops_shared_account_directory'), \
                mock.patch.dict(os.environ, {'DISPLAY': ':99'}, clear=True), \
                mock.patch.object(self.c.subprocess, 'Popen', return_value=process) as spawn:
            self.assertEqual(self.c.codex_run_identity_only(123), 130)
            self.assertNotIn('DISPLAY', os.environ)
        command = spawn.call_args.args[0]
        self.assertEqual(command[command.index('--') + 1:],
                         [self.c.CODEX_RAW_BINARY, '--config',
                          'log_dir=' + json.dumps(self.c.CODEX_HOST_LOG_ROOT), 'login', '--device-auth'])
        self.assertIn('--bind-data', command)
        self.assertNotIn('--ro-bind-data', command)
        self.assertIn(str(self.target), command)
        self.assertFalse(any('auth.json' in value for value in command))
        for flag in ('--unshare-net', '--unshare-pid', '--new-session', '--tmpfs'):
            self.assertNotIn(flag, command)
        self.assertEqual(spawn.call_args.kwargs, {'close_fds': True, 'pass_fds': (123,)})
        self.assertIsNone(self.c.CODEX_BWRAP_PROCESS)

    def test_installer_prepares_private_state_and_no_empty_native_id(self):
        policy = (ROOT / 'hooks/target/etc/tmpfiles.d/80-codex-storage.conf.tmpl').read_text()
        rules = [line.split() for line in policy.splitlines()
                 if line and not line.startswith('#')]
        identity_rules = [rule for rule in rules if rule[1].endswith('/installation_id')]
        self.assertEqual(identity_rules, [])
        state_rules = [rule for rule in rules if rule[1].endswith('/project-identities')]
        self.assertEqual(state_rules, [[
            'd', '__INSTALLER_DEVOPS_CODEX_RUNTIME_ROOT__/project-identities', '0700',
            '__INSTALLER_ACCOUNT_USERNAME__', 'devops', '-',
        ]])
        self.assertFalse(any(rule[1].endswith('/auth.json') for rule in rules))


class ChatGPTIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='chatgpt-identity-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.machine_id = self.root / 'machine-id'
        self.machine_id.write_text('0123456789abcdef0123456789abcdef\n', encoding='ascii')
        self.target = self.root / 'installation_id'
        self.target.write_bytes(b'')
        self.target.chmod(0o600)
        patcher = mock.patch.object(identity, 'MANAGED_CODEX_INSTALLATION_ID', str(self.target))
        patcher.start()
        self.addCleanup(patcher.stop)
        selector = mock.patch.object(project_identity, 'select_project_uuid',
                                     return_value='35ba8c1c-7d8d-4ceb-9e64-d4643fd2c926')
        self.selector = selector.start()
        self.addCleanup(selector.stop)
        def fail(message):
            raise RuntimeError(message)
        self.runtime = identity.IdentityRuntime(
            fail=fail,
            require_root_owned_regular_file=lambda label, path: str(self.machine_id),
            filtered_resolv_conf=lambda: 'nameserver 192.0.2.53\n',
            validate_absolute_path=lambda label, path: path,
        )

    def create(self, name):
        directory = self.root / name
        directory.mkdir(mode=0o700)
        return identity.create_synthetic_identity_files(
            str(directory), '/home/fixture', project_directory=str(self.root), runtime=self.runtime,
        )

    def test_each_launch_reuses_project_uuid_with_other_identity_fields_preserved(self):
        first, second = self.create('first'), self.create('second')
        values = [Path(item['installation_id']).read_text(encoding='ascii')
                  for item in (first, second)]
        self.assertEqual(*values)
        self.assertTrue(all(uuid.UUID(value.strip()).version == 4 for value in values))
        self.selector.assert_called_with(str(self.root))
        for name in ('machine_id', 'boot_id', 'hostname'):
            self.assertEqual(Path(first[name]).read_bytes(), Path(second[name]).read_bytes())

    def test_mount_uses_writable_launch_copy_and_preserves_native_target(self):
        generated = self.create('launch')
        command = ['bwrap', '--bind', str(self.root), str(self.root)]
        identity.add_synthetic_codex_installation_id_mount(
            command, generated['installation_id'], runtime=self.runtime,
        )
        self.assertEqual(command[-3:], ['--bind', generated['installation_id'], str(self.target)])
        self.assertEqual(self.target.read_bytes(), b'')
        self.assertEqual(Path(generated['installation_id']).stat().st_mode & 0o777, 0o644)

    def test_native_read_write_open_and_lock_cannot_change_later_launch_identity(self):
        first = self.create('first')
        source = Path(first['installation_id'])
        original = source.read_text(encoding='ascii')
        # Pinned Codex 0.159.0 opens O_RDWR|O_CREAT, locks, checks mode,
        # then reads even an already valid UUID. Use only the private fixture.
        descriptor = os.open(source, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
        with os.fdopen(descriptor, 'r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            self.assertEqual(handle.read().decode('ascii'), original)
            self.assertEqual(os.fstat(handle.fileno()).st_mode & 0o777, 0o644)
            handle.seek(0)
            handle.truncate()
            handle.write((str(uuid.uuid4()) + '\n').encode('ascii'))
        second = self.create('second')
        self.assertEqual(Path(second['installation_id']).read_text(encoding='ascii'), original)
        self.assertNotEqual(source.read_text(encoding='ascii'), original)
        self.assertEqual(self.target.read_bytes(), b'')

    def test_unsafe_source_fails_and_missing_target_gets_independent_native_id(self):
        generated = self.create('launch')
        source = Path(generated['installation_id'])
        source.chmod(0o666)
        with self.assertRaisesRegex(RuntimeError, 'safe mode'):
            identity.add_synthetic_codex_installation_id_mount(
                [], str(source), runtime=self.runtime,
            )
        source.chmod(0o644)
        self.target.unlink()
        identity.add_synthetic_codex_installation_id_mount([], str(source), runtime=self.runtime)
        native = self.target.read_text(encoding='ascii').strip()
        self.assertEqual(uuid.UUID(native).version, 4)
        self.assertNotEqual(native, source.read_text(encoding='ascii').strip())

    def test_no_project_override_uses_native_id_without_generating_one(self):
        self.selector.return_value = None
        generated = self.create('launch')
        self.assertEqual(generated['installation_id'], str(self.target))
        self.assertFalse((self.root / 'launch' / 'installation_id').exists())
        command = []
        identity.add_synthetic_codex_installation_id_mount(command, generated['installation_id'], runtime=self.runtime)
        self.assertEqual(command, [])
        self.target.unlink()
        command = []
        identity.add_synthetic_codex_installation_id_mount(command, generated['installation_id'], runtime=self.runtime)
        self.assertEqual(command, [])
        self.assertFalse(self.target.exists())


class ProjectIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='project-identity-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / 'private-state'
        self.project = self.root / 'a project caf\u00e9'
        self.other = self.root / 'another-project'
        self.project.mkdir()
        self.other.mkdir()

    def select(self, directory=None, *, rotate=False):
        return project_identity.select_project_uuid(
            str(self.project if directory is None else directory),
            rotate=rotate, state_directory=str(self.state),
        )

    def record_path(self, directory=None):
        path = self.project if directory is None else directory
        key = hashlib.sha256(os.fsencode(path.resolve())).hexdigest()
        return self.state / (key + '.json')

    def test_ordinary_launch_has_no_override_and_creates_no_state(self):
        with mock.patch.object(project_identity.uuid, 'uuid4') as generate:
            self.assertIsNone(self.select())
        generate.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_rotation_persists_and_reuses_value_without_modifying_project(self):
        value = self.select(rotate=True)
        self.assertEqual(uuid.UUID(value).version, 4)
        with mock.patch.object(project_identity.uuid, 'uuid4') as generate:
            self.assertEqual(self.select(), value)
        generate.assert_not_called()
        self.assertEqual(list(self.project.iterdir()), [])
        self.assertEqual(self.state.stat().st_mode & 0o7777, 0o700)
        record = self.record_path()
        self.assertEqual(record.stat().st_mode & 0o7777, 0o600)
        self.assertEqual(json.loads(record.read_bytes()), {
            'version': 1, 'directory': str(self.project), 'installation_id': value,
        })

    def test_rotation_affects_only_selected_directory(self):
        first = self.select(rotate=True)
        other = self.select(self.other, rotate=True)
        second = self.select(rotate=True)
        self.assertEqual(len({first, other, second}), 3)
        self.assertEqual(self.select(), second)
        self.assertEqual(self.select(self.other), other)
        child = self.project / 'subdirectory'
        child.mkdir()
        self.assertIsNone(self.select(child))

    def test_symlink_alias_uses_same_physical_directory(self):
        value = self.select(rotate=True)
        alias = self.root / 'alias'
        alias.symlink_to(self.project, target_is_directory=True)
        self.assertEqual(self.select(alias), value)
        self.assertEqual(len(list(self.state.glob('*.json'))), 1)

    def test_unsafe_directory_permissions_and_symlink_are_rejected(self):
        self.state.mkdir(mode=0o700)
        self.state.chmod(0o750)
        with self.assertRaises(project_identity.ProjectIdentityError):
            self.select()
        self.state.chmod(0o700)
        self.state.rmdir()
        self.state.symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(project_identity.ProjectIdentityError):
            self.select(rotate=True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_state_directory_must_belong_to_current_account(self):
        self.select(rotate=True)
        different_uid = os.getuid() + 1
        with mock.patch.object(project_identity.os, 'getuid', return_value=different_uid), \
                self.assertRaises(project_identity.ProjectIdentityError):
            self.select()

    def test_symlink_hardlink_fifo_and_public_record_are_rejected(self):
        self.select(rotate=True)
        record = self.record_path()
        record.chmod(0o640)
        with self.assertRaises(project_identity.ProjectIdentityError):
            self.select()
        record.chmod(0o600)
        link = self.state / 'linked'
        os.link(record, link)
        with self.assertRaises(project_identity.ProjectIdentityError):
            self.select(rotate=True)
        link.unlink()
        record.unlink()
        record.symlink_to(self.root / 'missing')
        with self.assertRaises(project_identity.ProjectIdentityError):
            self.select(rotate=True)
        record.unlink()
        os.mkfifo(record, 0o600)
        with self.assertRaises(project_identity.ProjectIdentityError):
            self.select()

    def test_invalid_records_fail_without_implicit_rotation(self):
        self.select(rotate=True)
        record = self.record_path()
        valid = json.loads(record.read_bytes())
        for data in (
            b'not-json', b'x' * (project_identity.MAX_RECORD_BYTES + 1),
            json.dumps({**valid, 'directory': str(self.other)}).encode(),
            json.dumps({**valid, 'installation_id': 'not-a-uuid'}).encode(),
            json.dumps({**valid, 'version': True}).encode(),
            json.dumps({**valid, 'extra': 'unexpected'}).encode(),
        ):
            record.write_bytes(data)
            with self.subTest(data_size=len(data)), \
                    mock.patch.object(project_identity.uuid, 'uuid4') as generate, \
                    self.assertRaises(project_identity.ProjectIdentityError):
                self.select()
            generate.assert_not_called()
        repaired = self.select(rotate=True)
        self.assertEqual(self.select(), repaired)

    def test_failed_atomic_publication_preserves_old_value_and_cleans_own_temporary(self):
        value = self.select(rotate=True)
        sentinel = self.state / 'unrelated'
        sentinel.write_text('keep', encoding='ascii')
        with mock.patch.object(project_identity.os, 'replace',
                               side_effect=OSError(errno.EIO, 'fixture publication failure')), \
                self.assertRaises(project_identity.ProjectIdentityError):
            self.select(rotate=True)
        self.assertEqual(self.select(), value)
        self.assertEqual(sentinel.read_text(encoding='ascii'), 'keep')
        self.assertEqual(list(self.state.glob('.*.tmp')), [])

    def test_concurrent_rotations_publish_complete_records(self):
        # All work is confined to this fixture's private state directory.
        with ThreadPoolExecutor(max_workers=4) as executor:
            values = list(executor.map(lambda _: self.select(rotate=True), range(12)))
        self.assertEqual(len(set(values)), 12)
        self.assertIn(self.select(), values)
        self.assertEqual(list(self.state.glob('.*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
