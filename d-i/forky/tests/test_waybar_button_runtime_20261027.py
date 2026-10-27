"""Unexecuted taskview guard fixtures; no compositor or host helper access.

All paths, metadata replies and executables belong to a private fixture tree.
The Unix socket is an inert filesystem object: nothing connects or listens.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from pathlib import Path
from contextlib import ExitStack, redirect_stderr
import io
import os
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


SOURCE = (Path(__file__).resolve().parents[1]
          / 'hooks/target/usr/local/bin/labwc-window-switcher')
LIBEXEC = SOURCE.parents[1] / 'libexec'


def load_helper(name):
    path = LIBEXEC / name
    module = ModuleType('fixture_' + name.replace('-', '_').replace('.', '_'))
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class DesktopRuntimeIdentityFixtures(unittest.TestCase):
    def invoke(self, name, *, directory_mode=0o700, directory_owner=1000,
               directory_type=stat.S_IFDIR, socket_mode=0o666, socket_owner=1000,
               socket_type=stat.S_IFSOCK, socket_links=1):
        helper = load_helper(name)
        metadata = {
            '/run/user/1000': SimpleNamespace(st_mode=directory_type | directory_mode,
                                              st_uid=directory_owner, st_nlink=8),
            '/run/user/1000/bus': SimpleNamespace(st_mode=socket_type | socket_mode,
                                                  st_uid=socket_owner, st_nlink=socket_links),
        }
        def lstat(path):
            self.assertIn(str(path), metadata)  # No fallback to host filesystem.
            return metadata[str(path)]
        gi = ModuleType('gi')
        gi.require_version = mock.Mock()
        repository = ModuleType('gi.repository')
        repository.Gio = repository.GLib = repository.GLibUnix = object()
        gi.repository = repository
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(helper.os, 'getuid', return_value=1000))
            stack.enter_context(mock.patch.object(helper.os, 'geteuid', return_value=1000))
            stack.enter_context(mock.patch.object(Path, 'lstat', lstat))
            stack.enter_context(mock.patch.dict(os.environ, {
                'LABWC_SESSION_OWNER': 'desktop', 'XDG_SESSION_TYPE': 'wayland',
                'XDG_RUNTIME_DIR': '/run/user/1000', 'WAYLAND_DISPLAY': 'wayland-0',
            }, clear=True))
            if name == 'labwc-waybar-events.tmpl':
                stack.enter_context(mock.patch.dict(sys.modules, {'gi': gi, 'gi.repository': repository}))
                reader = stack.enter_context(mock.patch.object(helper, 'Reader'))
                reader.return_value.run.return_value = 0
                return helper.main(['notifications'])
            stack.enter_context(mock.patch.object(helper.pwd, 'getpwuid',
                return_value=SimpleNamespace(pw_dir='/home/fixture', pw_name='fixture')))
            return helper.environment()

    def test_private_runtime_accepts_bus_socket_modes_for_status_controls_and_calendar(self):
        for name in ('labwc-waybar-events.tmpl', 'labwc-notifications.tmpl', 'labwc-calendar-actions'):
            for mode in (0o600, 0o660, 0o700, 0o666, 0o755, 0o777):
                with self.subTest(helper=name, mode=oct(mode)):
                    result = self.invoke(name, socket_mode=mode)
                    if isinstance(result, dict):
                        self.assertEqual(result['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=/run/user/1000/bus')
                    else:
                        self.assertEqual(result, 0)

    def test_unsafe_identity_is_rejected_before_bus_or_gtk_access(self):
        cases = (
            {'directory_mode': 0o755}, {'directory_owner': 1001},
            {'directory_type': stat.S_IFLNK}, {'socket_owner': 1001},
            {'socket_type': stat.S_IFREG}, {'socket_type': stat.S_IFLNK},
            {'socket_links': 2},
        )
        for name in ('labwc-waybar-events.tmpl', 'labwc-notifications.tmpl', 'labwc-calendar-actions'):
            for case in cases:
                with self.subTest(helper=name, case=case), self.assertRaises(Exception) as raised:
                    self.invoke(name, **case)
                self.assertEqual(type(raised.exception).__name__,
                                 'ValueError' if name == 'labwc-waybar-events.tmpl' else 'Error')

    def test_calendar_startup_errors_keep_specific_codes_without_exception_content(self):
        helper = load_helper('labwc-calendar-actions')
        cases = ((helper.Error('unsafe-account'), 1, 'error=unsafe-account'),
                 (helper.Error('credentials-unavailable'), 3, 'error=credentials-unavailable'),
                 (helper.Error('outcome-unknown'), 4, 'status=outcome-unknown'),
                 (PermissionError('private fixture detail'), 1, 'cause=PermissionError'))
        for failure, status, marker in cases:
            errors = io.StringIO()
            with self.subTest(error=type(failure).__name__), \
                    mock.patch.object(helper, 'main', side_effect=failure), redirect_stderr(errors):
                self.assertEqual(helper.cli(), status)
            self.assertIn(marker, errors.getvalue())
            self.assertNotIn('private fixture detail', errors.getvalue())


class TaskviewRuntimeFixtures(unittest.TestCase):
    def invoke(self, *, directory_metadata='1000 700', socket_metadata='1000 1',
               runtime_mismatch=False, directory_alias=False, socket_kind='socket',
               socket_mode=0o755):
        with tempfile.TemporaryDirectory(prefix='waybar-button-') as temporary:
            root = Path(temporary)
            runtime = root / '1000'
            runtime.mkdir(mode=0o700)
            # A real directory has multiple links; children must not hide taskview.
            (runtime / 'children').mkdir()
            endpoint = runtime / 'wayland-0'
            if socket_kind == 'file':
                endpoint.write_text('not a socket')
            else:
                bound = runtime / 'bound' if socket_kind == 'alias' else endpoint
                with socket.socket(socket.AF_UNIX) as inert:
                    inert.bind(str(bound))
                bound.chmod(socket_mode)
                if socket_kind == 'alias':
                    endpoint.symlink_to(bound.name)
            if directory_alias:
                moved = root / 'original'
                runtime.rename(moved)
                runtime.symlink_to(moved.name, target_is_directory=True)

            tools = {
                '/usr/bin/id': '#!/bin/sh\nprintf "%s\\n" 1000\n',
                '/usr/bin/stat': '''#!/bin/sh
set -eu
[ "$#" -eq 4 ] && [ "$1" = -c ] && [ "$3" = -- ] || exit 2
case "$4:$2" in
  "$FIXTURE_RUNTIME:%u %a") printf '%s\\n' "$FIXTURE_DIRECTORY_METADATA" ;;
  "$FIXTURE_RUNTIME/wayland-0:%u %h") printf '%s\\n' "$FIXTURE_SOCKET_METADATA" ;;
  *) exit 2 ;;
esac
''',
                # Capture the fixed timeout/wtype argv; execute neither program.
                '/usr/bin/timeout': '#!/bin/sh\nprintf "%s\\n" "$@"\n',
            }
            source = SOURCE.read_text(encoding='utf-8')
            original = 'runtime_root="/run/user/$runtime_uid"'
            self.assertEqual(source.count(original), 1)
            source = source.replace(original, 'runtime_root="$FIXTURE_ROOT/1000"')
            for installed, body in tools.items():
                tool = root / Path(installed).name
                tool.write_text(body, encoding='utf-8')
                tool.chmod(0o700)
                self.assertIn(installed, source)
                source = source.replace(installed, shlex.quote(str(tool)))
            wrapper = root / 'switcher.sh'
            wrapper.write_text(source, encoding='utf-8')
            # No inherited HOME, PATH, runtime bus, credentials or service state.
            environment = {
                'PATH': '/usr/bin:/bin', 'HOME': str(root), 'LC_ALL': 'C',
                'LABWC_SESSION_OWNER': 'desktop', 'XDG_SESSION_TYPE': 'wayland',
                'WAYLAND_DISPLAY': 'wayland-0',
                'XDG_RUNTIME_DIR': str(root / 'foreign' if runtime_mismatch else runtime),
                'FIXTURE_ROOT': str(root), 'FIXTURE_RUNTIME': str(runtime),
                'FIXTURE_DIRECTORY_METADATA': directory_metadata,
                'FIXTURE_SOCKET_METADATA': socket_metadata,
            }
            return subprocess.run(['/bin/sh', '-eu', str(wrapper)], env=environment,
                                  cwd=root, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=3)

    def test_private_parent_accepts_compositor_socket_permissions(self):
        for mode in (0o600, 0o660, 0o700, 0o755, 0o777):
            with self.subTest(mode=oct(mode)):
                result = self.invoke(socket_mode=mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), [
                    '--signal=TERM', '--kill-after=1s', '2s',
                    '/usr/bin/wtype', '-P', 'F13', '-p', 'F13'])

    def test_unsafe_runtime_or_endpoint_never_reaches_key_dispatch(self):
        cases = (
            {'runtime_mismatch': True}, {'directory_alias': True},
            {'directory_metadata': '1001 700'}, {'directory_metadata': '1000 755'},
            {'socket_kind': 'file'}, {'socket_kind': 'alias'},
            {'socket_metadata': '1001 1'}, {'socket_metadata': '1000 2'},
        )
        for case in cases:
            with self.subTest(case=case):
                result = self.invoke(**case)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn('labwc-window-switcher', result.stderr)
