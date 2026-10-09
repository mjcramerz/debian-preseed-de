"""R7 app argument and descriptor safety regressions, without services."""
from __future__ import annotations
from payload_fixture import source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import python_library
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from test_dynamic_storage_sizing_20260921 import TARGET
LIB = python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
from labwc_managed_app import browsers, commands, generic, mounts, profiles, sandbox, user_state


class ManagedArgumentReviewTests(unittest.TestCase):
    def test_vivaldi_preserves_driver_safety_decisions_in_each_acceleration_mode(self):
        for mode in ('launch', 'intel', 'nvidia'):
            with self.subTest(mode=mode):
                argv = browsers.browser_args('vivaldi', mode)
                self.assertIn('--ozone-platform=wayland', argv)
                self.assertIn('--use-angle=gl', argv)
                self.assertNotIn('--ignore-gpu-blocklist', argv)
                self.assertNotIn('--enable-gpu-rasterization', argv)
                self.assertNotIn('--disable-gpu-driver-bug-workarounds', argv)
                self.assertFalse(any('VaapiIgnoreDriverChecks' in value for value in argv))

    def test_sandbox_disable_switch_names_are_checked_not_boolean_values(self):
        names = ('disable-gpu-sandbox','disable-namespace-sandbox','disable-sandbox',
                 'disable-seccomp-filter-sandbox','disable-setuid-sandbox',
                 'no-sandbox','single-process','no-zygote','in-process-gpu')
        for mode in ('launch','intel','nvidia','pure-privacy'):
            for name in names:
                for prefix in ('-', '--'):
                    for value in ('', '=true', '=false', '=', '=0'):
                        argument = prefix+name+value
                        with self.subTest(mode=mode, argument=argument), redirect_stderr(io.StringIO()):
                            with self.assertRaises(SystemExit):
                                commands.validate_managed_arguments(mode, [argument])

    def test_split_or_missing_control_values_cannot_evade_validation(self):
        for name in ('ozone-platform','ozone-platform-hint','use-angle','use-gl',
                     'enable-features','disable-features'):
            for prefix in ('-', '--'):
                with self.subTest(name=name, prefix=prefix), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        commands.validate_managed_arguments('intel', [prefix+name, 'x11'])

    def test_native_wayland_and_opengl_arguments_remain_accepted(self):
        for prefix in ('-', '--'):
            commands.validate_managed_arguments('intel', [prefix+'ozone-platform=wayland',
                prefix+'use-angle=gl', prefix+'use-gl=angle'])
        arguments = ['https://example.org/doc', '/home/test/notes.txt']
        commands.validate_managed_arguments('launch', arguments)
        self.assertEqual(commands.normalize_managed_arguments('zoom', ['--url=', *arguments]), arguments)

    def test_gpu_disable_switch_values_are_rejected_in_accelerated_modes(self):
        for mode in ('intel','nvidia'):
            for option in ('disable-gpu','disable-gpu-compositing','disable-gpu-rasterization'):
                with self.subTest(mode=mode, option=option), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        commands.validate_managed_arguments(mode, ['-'+option+'=false'])

    def test_generic_electron_rejects_single_dash_and_equals_disable_switches(self):
        for switch in generic.ELECTRON_UNSAFE_SWITCHES:
            for prefix in ('-', '--'):
                for value in ('', '=false', '=0'):
                    with self.subTest(switch=switch, prefix=prefix, value=value), redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            generic.electron_command(['/opt/fixture/app', prefix+switch[2:]+value])

    def test_generic_electron_single_dash_control_cannot_override_enforced_platform(self):
        result = generic.electron_command(['/opt/fixture/app', '-ozone-platform=x11',
            '-use-angle=vulkan', '-use-gl=desktop', '--vendor-option=yes', 'https://example.org'])
        self.assertIn('--ozone-platform=wayland', result)
        self.assertIn('--use-angle=gl', result)
        self.assertIn('--use-gl=angle', result)
        self.assertNotIn('-ozone-platform=x11', result)
        self.assertNotIn('-use-angle=vulkan', result)
        self.assertNotIn('-use-gl=desktop', result)
        self.assertEqual(result[-2:], ['--vendor-option=yes', 'https://example.org'])

    def test_generic_electron_single_dash_features_get_same_filter_as_double_dash(self):
        single = generic.electron_command(['/opt/fixture/app', '-enable-features=VendorFeature,Vulkan'])
        double = generic.electron_command(['/opt/fixture/app', '--enable-features=VendorFeature,Vulkan'])
        self.assertEqual(single, double)
        enabled = next(a for a in single if a.startswith('--enable-features='))
        self.assertIn('VendorFeature', enabled)
        self.assertNotIn('Vulkan', enabled)


class ChatGPTDownloadTests(unittest.TestCase):
    def test_native_save_paths_are_persistent_without_exposing_secret_directories(self):
        config = profiles.PERSISTENT_SANDBOX_CONFIG['chatgpt']
        paths = config['rw_bind_home_directories']
        self.assertTrue({'Downloads', 'Desktop', 'Documents', 'Pictures', 'Workspace'} <= set(paths))
        self.assertFalse({'.ssh', '.gnupg', '.config'} & set(paths))
        with tempfile.TemporaryDirectory() as home:
            for relative in ('Downloads', 'Desktop', 'Documents', 'Pictures', 'Workspace'):
                (Path(home)/relative).mkdir()
            command = []
            mounts.add_home_directory_binds(command, home, paths, '--bind')
            binds = [command[i+1:i+3] for i, value in enumerate(command) if value == '--bind']
            for relative in ('Downloads', 'Desktop', 'Documents', 'Pictures', 'Workspace'):
                path = str(Path(home)/relative)
                self.assertIn([path, path], binds)
            self.assertNotIn([home, home], binds)

    def test_cold_document_portal_is_activated_before_its_required_mount(self):
        runtime = '/run/user/1000'
        result = subprocess.CompletedProcess([], 0,
            json.dumps({'type': 'ay', 'data': [list((runtime + '/doc\0').encode())]}).encode(), b'')
        with mock.patch.object(sandbox.subprocess, 'run', return_value=result) as call:
            sandbox.prepare_document_portal(runtime)
        self.assertEqual(call.call_args.args[0][-1], 'GetMountPoint')
        self.assertEqual(call.call_args.kwargs['timeout'], 12)
        self.assertEqual(call.call_args.kwargs['env']['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=/run/user/1000/bus')
        config = profiles.PERSISTENT_SANDBOX_CONFIG['chatgpt']
        self.assertTrue(config['prepare_document_portal'])
        self.assertEqual(config['required_runtime_directories'], ('doc',))
        with tempfile.TemporaryDirectory() as root:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                sandbox.add_runtime_bind([], root, '/run/user/1000', 'doc', 'directory', required=True)
            (Path(root)/'doc').mkdir()
            command = []
            sandbox.add_runtime_bind(command, root, '/run/user/1000', 'doc', 'directory', required=True)
            self.assertEqual(command[-3:], ['--bind', str(Path(root)/'doc'), '/run/user/1000/doc'])

    def test_invalid_document_portal_response_cannot_expose_a_foreign_mount(self):
        for payload in (b'not json', b'{}', b'x' * 16385,
                        json.dumps({'type': 'ay', 'data': [[True]]}).encode(),
                        json.dumps({'type': 'ay', 'data': [list(b'/run/user/2000/doc\0')]}).encode(),
                        json.dumps({'type': 'ay', 'data': [list(b'/run/user/1000/../2000/doc\0')]}).encode()):
            result = subprocess.CompletedProcess([], 0, payload, b'')
            with mock.patch.object(sandbox.subprocess, 'run', return_value=result), \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                sandbox.prepare_document_portal('/run/user/1000')

    def test_document_portal_transport_errors_are_actionable(self):
        for error in (OSError('busctl unavailable'), subprocess.TimeoutExpired('busctl', 12)):
            with mock.patch.object(sandbox.subprocess, 'run', side_effect=error), \
                    redirect_stderr(io.StringIO()) as diagnostics, self.assertRaises(SystemExit):
                sandbox.prepare_document_portal('/run/user/1000')
            self.assertIn('cannot activate ChatGPT', diagnostics.getvalue())


class TutaDocumentMountTests(unittest.TestCase):
    def test_attach_and_save_use_writable_document_roots_and_only_account_media(self):
        config = profiles.PERSISTENT_SANDBOX_CONFIG['tutanota']
        self.assertTrue(config['user_media_directory'])
        writable = set(config['rw_bind_home_directories'])
        self.assertTrue({'Downloads', 'Documents', 'Pictures', 'Workspace', 'Syncthing'} <= writable)
        self.assertFalse(writable & set(config.get('ro_bind_home_directories', ())))
        self.assertNotIn('.ssh', writable)
        self.assertNotIn('.gnupg', writable)
        self.assertNotIn('/run/media', config.get('rw_bind_paths', ()))
        # The existing boot tmpfiles rule creates this stable parent before
        # applications launch, including when no USB volume is mounted yet.
        rule = payload_read_text(TARGET / 'etc/tmpfiles.d/25-desktop-media-runtime.conf')
        self.assertIn('__INSTALLER_DIR_RUN_MEDIA__/__INSTALLER_ACCOUNT_USERNAME__ 0750', rule)

    def bind(self, metadata=None, realpath=None, readable=True):
        if metadata is None:
            metadata = type('Metadata', (), {'st_mode': stat.S_IFDIR | 0o750, 'st_uid': os.getuid()})()
        command = []
        with mock.patch.object(mounts.os.path, 'realpath', side_effect=realpath or (lambda value: value)), \
             mock.patch.object(mounts.os, 'lstat', return_value=metadata), \
             mock.patch.object(mounts.os, 'access', return_value=readable) as access:
            mounts.add_user_media_directory_bind(command, 'fixture')
        return command, access

    def test_user_and_root_acl_authorized_media_parents_need_no_parent_write_access(self):
        for uid in (os.getuid(), 0):
            metadata = type('Metadata', (), {'st_mode': stat.S_IFDIR | 0o750, 'st_uid': uid})()
            command, access = self.bind(metadata)
            self.assertEqual(command[-3:], ['--bind', '/run/media/fixture', '/run/media/fixture'])
            access.assert_called_once_with('/run/media/fixture', os.R_OK | os.X_OK)
            self.assertNotIn('/run/media/other', command)

    def test_unsafe_media_ancestry_ownership_types_and_modes_are_rejected(self):
        variants = [(stat.S_IFLNK | 0o700, os.getuid()), (stat.S_IFREG | 0o600, os.getuid()),
                    (stat.S_IFDIR | 0o777, os.getuid()), (stat.S_IFDIR | 0o750, os.getuid() + 1)]
        with redirect_stderr(io.StringIO()):
            for mode, uid in variants:
                with self.subTest(mode=mode, uid=uid), self.assertRaises(SystemExit):
                    self.bind(type('Metadata', (), {'st_mode': mode, 'st_uid': uid})())
            with self.assertRaises(SystemExit):
                self.bind(realpath=lambda value: '/outside')
            with self.assertRaises(SystemExit):
                self.bind(readable=False)

    def test_missing_media_and_invalid_account_names_do_not_create_mountpoints(self):
        command = []
        with mock.patch.object(mounts.os.path, 'realpath', side_effect=lambda value: value), \
             mock.patch.object(mounts.os, 'lstat', side_effect=FileNotFoundError), \
             mock.patch.object(mounts.os, 'mkdir') as mkdir:
            mounts.add_user_media_directory_bind(command, 'fixture')
            mkdir.assert_not_called()
        self.assertEqual(command, [])
        with redirect_stderr(io.StringIO()):
            for name in ('../fixture', 'fixture/name', 'fixture;bad', ''):
                with self.subTest(name=name), self.assertRaises(SystemExit):
                    mounts.add_user_media_directory_bind(command, name)


class UserStateReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='x-state-review-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root/'home'; self.home.mkdir(mode=0o700)
        self.config = self.home/'.config'; self.config.mkdir(mode=0o700)
        self.path = self.config/'test.json'
        self.seed = self.root/'seed'; self.seed.write_text('{"seed":true}\n')
        self.seed.chmod(0o600)
        self.errors = io.StringIO()
        self.capture = redirect_stderr(self.errors); self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def ensure(self, *, seed=True):
        return user_state.ensure_managed_user_file(str(self.home), '.config/test.json',
                                                   0o600, str(self.seed) if seed else None)

    def test_new_seeded_file_and_existing_content_are_preserved(self):
        self.ensure()
        self.assertEqual(payload_read_bytes(self.path), payload_read_bytes(self.seed))
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.path).st_mode), 0o600)
        self.path.write_text('{"user":true}')
        self.ensure()
        self.assertEqual(payload_read_text(self.path), '{"user":true}')

    def test_unseeded_file_is_empty_private_and_not_replaced(self):
        self.ensure(seed=False)
        self.assertEqual(payload_read_bytes(self.path), b'')
        inode = payload_source_stat(self.path).st_ino
        self.path.write_text('keep'); self.ensure(seed=False)
        self.assertEqual(payload_source_stat(self.path).st_ino, inode)
        self.assertEqual(payload_read_text(self.path), 'keep')

    def test_dangling_symlink_does_not_create_its_target_inside_or_outside_home(self):
        for target in (self.root/'outside', self.home/'inside'):
            with self.subTest(target=target):
                self.path.symlink_to(target)
                with self.assertRaises(SystemExit): self.ensure()
                self.assertFalse(payload_source_exists(target))
                self.assertTrue(self.path.is_symlink())
                self.path.unlink()

    def test_existing_symlink_hardlink_and_fifo_are_rejected_without_mutation(self):
        target = self.home/'other'; target.write_text('unchanged'); target.chmod(0o644)
        for kind in ('symlink','hardlink','fifo','directory'):
            with self.subTest(kind=kind):
                if kind == 'symlink': self.path.symlink_to(target)
                elif kind == 'hardlink': os.link(target, self.path)
                elif kind == 'fifo': os.mkfifo(self.path)
                else: self.path.mkdir()
                with self.assertRaises(SystemExit): self.ensure()
                self.assertEqual(payload_read_text(target), 'unchanged')
                self.assertEqual(stat.S_IMODE(payload_source_stat(target).st_mode), 0o644)
                if kind == 'directory': self.path.rmdir()
                else: self.path.unlink()

    def test_failed_seed_copy_does_not_leave_a_partial_file(self):
        def interrupted(source, destination, **_kwargs):
            destination.write(b'partial'); raise OSError('fixture copy interruption')
        with mock.patch.object(user_state.shutil, 'copyfileobj', side_effect=interrupted):
            with self.assertRaises(SystemExit): self.ensure()
        self.assertFalse(payload_source_exists(self.path))
        self.ensure(); self.assertEqual(payload_read_bytes(self.path), payload_read_bytes(self.seed))

    def test_failed_copy_does_not_unlink_a_replacement_inode(self):
        def replaced(source, destination, **_kwargs):
            replacement = self.config/'replacement'; replacement.write_text('replacement')
            os.replace(replacement, self.path)
            raise OSError('fixture replacement during copy')
        with mock.patch.object(user_state.shutil, 'copyfileobj', side_effect=replaced):
            with self.assertRaises(SystemExit): self.ensure()
        self.assertEqual(payload_read_text(self.path), 'replacement')

    def test_seed_symlink_is_rejected_and_new_destination_removed(self):
        self.seed.unlink(); self.seed.symlink_to(self.root/'missing')
        with self.assertRaises(SystemExit): self.ensure()
        self.assertFalse(payload_source_exists(self.path))

    def test_directory_ancestry_checked_before_creation(self):
        outside = self.root/'outside'; outside.mkdir()
        (self.home/'linked').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SystemExit):
            sandbox.persistent_app_directory(str(self.home), 'linked/should-not-exist')
        self.assertFalse(payload_source_exists(outside/'should-not-exist'))
        self.assertEqual(sandbox.persistent_app_directory(str(self.home), 'normal/child'),
                         str(self.home/'normal/child'))

    def test_json_valid_object_and_duplicate_or_nonobject_rejection(self):
        self.path.write_text('{"valid":[1,2,3]}')
        self.assertEqual(user_state.load_user_json_object(str(self.path), 100), {'valid':[1,2,3]})
        for payload in ('{"x":1,"x":2}', '[]', 'not json', '['*1200+']'*1200):
            with self.subTest(payload=payload[:30]):
                self.path.write_text(payload)
                with self.assertRaises(SystemExit):
                    user_state.load_user_json_object(str(self.path), 4096)

    def test_json_symlink_fifo_hardlink_and_directory_rejected(self):
        target = self.home/'other'; target.write_text('{}')
        for kind in ('symlink','hardlink','fifo','directory'):
            with self.subTest(kind=kind):
                if kind == 'symlink': self.path.symlink_to(target)
                elif kind == 'hardlink': os.link(target, self.path)
                elif kind == 'fifo': os.mkfifo(self.path)
                else: self.path.mkdir()
                with self.assertRaises(SystemExit):
                    user_state.load_user_json_object(str(self.path), 100)
                if kind == 'directory': self.path.rmdir()
                else: self.path.unlink()

    def test_json_bounded_read_even_when_reported_size_is_stale(self):
        self.path.write_text('{"padding":"'+'x'*10000+'"}')
        metadata = list(payload_source_stat(self.path)); metadata[6] = 0
        with mock.patch.object(user_state.os, 'fstat', return_value=os.stat_result(metadata)):
            with self.assertRaises(SystemExit):
                user_state.load_user_json_object(str(self.path), 64)
        self.assertIn('exceeds the size limit', self.errors.getvalue())

    def test_json_reads_validated_descriptor_not_replaced_pathname(self):
        self.path.write_text('{"opened":true}')
        fdopen = os.fdopen
        def swap_path(descriptor, mode):
            self.path.rename(self.config/'old')
            self.path.write_text('{"replacement":true}')
            return fdopen(descriptor, mode)
        with mock.patch.object(user_state.os, 'fdopen', side_effect=swap_path):
            self.assertEqual(user_state.load_user_json_object(str(self.path), 100), {'opened':True})

    def test_json_positive_integer_limit_and_utf8_validation(self):
        self.path.write_text('{}')
        for limit in (0, -1, True, 1.5, '100'):
            with self.subTest(limit=limit), self.assertRaises(SystemExit):
                user_state.load_user_json_object(str(self.path), limit)
        self.path.write_bytes(b'\xff')
        with self.assertRaises(SystemExit): user_state.load_user_json_object(str(self.path), 100)


class PreservedCompatibilityReviewTests(unittest.TestCase):
    def test_only_zoom_and_discord_remain_private_compatibility_apps(self):
        self.assertEqual(set(profiles.WAYLAND_COMPAT_APPS), {'zoom','discord'})


class ApplicationLifecycleReviewTests(unittest.TestCase):
    def test_unknown_future_wayland_and_electron_apps_use_main_exit_cleanup(self):
        for kind in ('wayland', 'electron'):
            with self.subTest(kind=kind), mock.patch.object(generic, 'assert_launch_allowed'):
                argv = generic.transient_argv(kind, 'launch', ['/opt/future-app/bin/app', 'literal; argument'], {})
            for setting in ('ExitType=main', 'KillMode=control-group', 'TimeoutStopSec=20s', 'SendSIGKILL=yes', 'Restart=no'):
                self.assertIn('--property=' + setting, argv)
            self.assertEqual(argv[-2:], ['/opt/future-app/bin/app', 'literal; argument'])

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'native systemd analyzer unavailable')
    def test_native_systemd_applies_family_policy_to_future_app_names(self):
        # The native parser loads the real dash-prefix drop-ins. This checks
        # effective properties without starting a user manager or application.
        with tempfile.TemporaryDirectory(prefix='application-units-') as directory:
            root = Path(directory)
            source = TARGET / 'etc/systemd/user'
            units = []
            for family in ('wayland', 'electron', 'native', 'devops', 'bitwarden', 'qbittorrent', 'compat'):
                drop = root / f'labwc-{family}-.service.d'
                drop.mkdir()
                (drop / '50-app-lifecycle.conf').write_text(payload_read_text(source / 'labwc-native-.service.d/50-app-lifecycle.conf'), encoding='utf-8')
                unit = root / f'labwc-{family}-future-app-0123456789abcdef0123456789abcdef.service'
                unit.write_text('[Service]\nType=exec\nExitType=cgroup\nKillMode=process\nExecStart=/usr/bin/true\n', encoding='utf-8')
                units.append(str(unit))
            result = subprocess.run(['/usr/bin/systemd-analyze', '--user', '--generators=no', '--man=no', 'verify', *units],
                env={**os.environ, 'SYSTEMD_UNIT_PATH': str(root) + ':/usr/lib/systemd/user', 'SYSTEMD_LOG_LEVEL': 'debug'},
                capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            output = result.stdout + result.stderr
            for family in ('wayland', 'electron', 'native', 'devops', 'bitwarden', 'qbittorrent', 'compat'):
                self.assertIn(str(root / f'labwc-{family}-.service.d/50-app-lifecycle.conf'), output)
            self.assertIn('ExitType=main\n', payload_read_text(source / 'labwc-native-.service.d/50-app-lifecycle.conf'))
            # service_dump() does not print ExitType; the native parser has
            # accepted that directive in every loaded family drop-in above.
            for setting in ('KillMode: control-group', 'TimeoutStopSec: 20s', 'SendSIGKILL: yes'):
                self.assertEqual(output.count(setting), 7, setting)
            stages = payload_read_text(TARGET.parents[1] / 'scripts/desktop/components/target-assets.sh')
            self.assertIn('for application_family in wayland electron native devops bitwarden qbittorrent compat; do', stages)

    @unittest.skipUnless(shutil.which('perl') and shutil.which('setsid'), 'Perl process/logging runtime unavailable')
    def test_chatgpt_log_supervision_is_independent_of_inherited_pipes_and_eof(self):
        for mode, expected in (('held-pipe', 7), ('closed-output', 137)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='chatgpt-log-lifetime-') as directory:
                root = Path(directory)
                path = root / 'log.sock'
                ready = root / 'ready'
                child = root / 'child'
                child.write_text('#!/usr/bin/python3\n' + '''import os,signal,sys,time
from pathlib import Path
ready=Path(os.environ["FIXTURE_READY"])
def publish_ready():
    # Existence is the readiness signal; publish complete PID bytes atomically.
    pending=ready.with_name("ready.tmp")
    pending.write_text(str(os.getpid()),encoding="ascii")
    pending.replace(ready)
if os.environ["FIXTURE_MODE"] == "held-pipe":
    pid=os.fork()
    if pid == 0:
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        publish_ready()
        print("fixture child output",flush=True)
        time.sleep(30)
        os._exit(0)
    while not ready.exists(): time.sleep(.01)
    sys.exit(7)
signal.signal(signal.SIGTERM,signal.SIG_IGN)
os.close(1);os.close(2)
publish_ready()
time.sleep(30)
''', encoding='utf-8')
                child.chmod(0o700)
                source = payload_read_text(TARGET / 'usr/local/libexec/labwc-chatgpt-log-runner')
                source = re.sub(r"(?m)^(\s*CHILD_EXECUTABLE\s*=>\s*)'[^']*'", lambda match: match[1] + repr(str(child)), source)
                source = re.sub(r"(?m)^(\s*SOCKET_PATH\s*=>\s*)'[^']*'", lambda match: match[1] + repr(str(path)), source)
                source = source.replace('TERMINATION_GRACE_SECS  => 5,', 'TERMINATION_GRACE_SECS  => 0.2,')
                logger = root / 'logger.pl'
                logger.write_text(source, encoding='utf-8')
                pinned = None
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sink:
                    sink.bind(str(path))
                    process = subprocess.Popen(['/usr/bin/perl', str(logger), 'launch'],
                        env={**os.environ, 'FIXTURE_MODE': mode, 'FIXTURE_READY': str(ready)},
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    try:
                        deadline = time.monotonic() + 3
                        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                            time.sleep(.01)
                        self.assertTrue(ready.exists(), 'real fixture child did not start')
                        pinned = os.pidfd_open(int(ready.read_text(encoding='ascii')))
                        if mode == 'closed-output':
                            process.terminate()
                        process.communicate(timeout=3)
                        self.assertEqual(process.returncode, expected)
                        sink.settimeout(.05)
                        messages = []
                        try:
                            while len(messages) < 64:
                                messages.append(sink.recv(8192))
                        except TimeoutError:
                            pass
                        self.assertTrue(any(f'event=completed status={expected}'.encode() in message for message in messages))
                    finally:
                        if pinned is not None:
                            try:
                                signal.pidfd_send_signal(pinned, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            os.close(pinned)
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=3)


if __name__ == '__main__':
    unittest.main()
