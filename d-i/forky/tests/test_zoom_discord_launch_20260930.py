"""Real desktop expansion and read-only mount regressions from attached logs."""
from __future__ import annotations

import configparser
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from payload_fixture import python_library

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
sys.path.insert(0, str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')))
from labwc_managed_app import cli, commands, sandbox


# Keep GLib's child watchers in a fresh process: other lifecycle tests fork and
# must not inherit GIO worker threads or asynchronous child-reaping state.
GIO_LAUNCH_PROBE = r'''
import ctypes as C, os, pathlib, sys, time
try:
 gio=C.CDLL('libgio-2.0.so.0'); glib=C.CDLL('libglib-2.0.so.0'); obj=C.CDLL('libgobject-2.0.so.0')
except OSError as exc:
 print(str(exc),file=sys.stderr); raise SystemExit(77)
for library,name,result,arguments in (
 (gio,'g_desktop_app_info_new_from_filename',C.c_void_p,[C.c_char_p]),
 (gio,'g_app_info_launch',C.c_int,[C.c_void_p]*4),
 (gio,'g_app_info_launch_uris',C.c_int,[C.c_void_p]*4),
 (glib,'g_list_append',C.c_void_p,[C.c_void_p,C.c_void_p]),
 (glib,'g_list_free',None,[C.c_void_p]),
 (obj,'g_object_unref',None,[C.c_void_p]),
):
 f=getattr(library,name); f.restype,f.argtypes=result,arguments
app=gio.g_desktop_app_info_new_from_filename(os.fsencode(sys.argv[1])); assert app
uris=None
try:
 if len(sys.argv)==3:
  launched=gio.g_app_info_launch(app,None,None,None)
 else:
  buffer=C.create_string_buffer(sys.argv[3].encode())
  uris=glib.g_list_append(None,C.cast(buffer,C.c_void_p))
  launched=gio.g_app_info_launch_uris(app,uris,None,None)
 assert launched, 'GIO could not launch the inert recorder'
 record=pathlib.Path(sys.argv[2]); deadline=time.monotonic()+5
 while not record.exists() and time.monotonic()<deadline: time.sleep(.01)
 assert record.exists(), 'desktop child did not complete'
 print(record.read_text())
finally:
 if uris: glib.g_list_free(uris)
 obj.g_object_unref(app)
'''


class ZoomDesktopLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rewrite = staticmethod(runpy.run_path(
            str(TARGET / 'usr/local/libexec/labwc-wrap-desktop-files'))['rewrite_desktop'])
        cls.sync = runpy.run_path(str(TARGET / 'usr/local/bin/labwc-sync-application-launchers.tmpl'))

    def launch(self, command, uri=None):
        with tempfile.TemporaryDirectory(prefix='zoom-desktop-launch-') as td:
            root = Path(td)
            recorder, record = root / 'record.py', root / 'arguments.json'
            recorder.write_text(
                'import json,pathlib,sys\n'
                'p=pathlib.Path(sys.argv[1]); t=p.with_suffix(".tmp")\n'
                't.write_text(json.dumps(sys.argv[2:])); t.replace(p)\n')
            executable, _, arguments = command.partition(' ')
            self.assertIn(executable, ('/usr/local/bin/zoom', '/usr/local/bin/labwc-wayland-compat-app'))
            desktop = root / 'zoom.desktop'
            desktop.write_text('[Desktop Entry]\nType=Application\nName=Zoom fixture\n'
                f'Exec={sys.executable} {recorder} {record} {arguments}\n'
                'Terminal=false\nDBusActivatable=false\nStartupNotify=false\n')
            # Exercise the menu's actual GIO desktop implementation through its
            # C ABI, even on development hosts without PyGObject.
            probe = subprocess.run([sys.executable, '-B', '-c', GIO_LAUNCH_PROBE,
                                    str(desktop), str(record), *([] if uri is None else [uri])],
                                   capture_output=True, timeout=7)
            if probe.returncode == 77:
                self.skipTest('GIO desktop implementation unavailable: ' + probe.stderr.decode()[:200])
            self.assertEqual(probe.returncode, 0, probe.stderr.decode('utf-8', 'replace'))
            return json.loads(probe.stdout)

    def check_handoff(self, command):
        prefix = shlex.split(command)[1:-1]
        mode = prefix[0] if prefix else 'auto'
        uri = 'zoommtg://zoom.us/join?confno=123456&pwd=fixture%2Bpass'
        for value in (None, uri):
            with self.subTest(command=command, activation=value is not None):
                received = self.launch(command, value)
                self.assertEqual(received, prefix + ([] if value is None else [value]))
                extra_args = received[len(prefix):]
                with mock.patch.object(cli.os, 'geteuid', return_value=1000), \
                     mock.patch.object(cli, 'redirect_wayland_compat_to_session_unit',
                                       side_effect=SystemExit(0)) as handoff, \
                     redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                    cli.main(wayland_compat=True, argv=[mode, 'zoom', *extra_args])
                self.assertEqual(stopped.exception.code, 0)
                activation = [] if value is None else ['--url=' + value]
                handoff.assert_called_once_with('zoom', mode, activation)
                self.assertEqual(commands.build_argv('zoom', mode, activation), ['/usr/bin/zoom', *activation])

    def test_system_vendor_and_previous_managed_entries_launch_and_activate(self):
        for original in (
            '/usr/bin/zoom --url=%U',
            '/opt/zoom/ZoomLauncher --url=%u',
            '/usr/local/bin/zoom --url=%U',
            '/usr/local/bin/labwc-wayland-app intel -- /opt/zoom/zoom --url=%U',
            'env QT_PLUGIN_PATH=/tmp/untrusted /usr/bin/zoom --url=%U',
        ):
            text = '[Desktop Entry]\nType=Application\nName=Zoom\nExec=' + original + '\n'
            rewritten = self.rewrite(text, '/usr/local/bin/labwc-wayland-app intel')
            self.assertEqual(self.rewrite(rewritten, '/usr/local/bin/labwc-wayland-app intel'), rewritten)
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(rewritten)
            command = parser['Desktop Entry']['Exec']
            self.assertEqual(command, '/usr/local/bin/zoom %u')
            self.check_handoff(command)

    def test_user_default_and_acceleration_actions_launch_and_activate(self):
        config = next(item for item in self.sync['APP_CONFIG'] if item['action_app'] == 'zoom')
        self.assertNotIn('PurePrivacy', config['actions'])
        for mode in (None, 'launch', 'intel', 'nvidia'):
            command = (self.sync['managed_default_exec']('zoom', config['field_code']) if mode is None
                       else self.sync['managed_exec'](mode, 'zoom', config['field_code']))
            self.check_handoff(command)

    def test_desktop_repair_does_not_remove_arbitrary_runtime_arguments(self):
        command = '/usr/bin/zoom --no-sandbox --url=%U'
        rewritten = self.rewrite('[Desktop Entry]\nType=Application\nExec=' + command + '\n',
                                 '/usr/local/bin/labwc-wayland-app intel')
        self.assertIn('Exec=/usr/local/bin/zoom --no-sandbox --url=%U', rewritten)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            commands.build_argv('zoom', 'intel', ['--no-sandbox', '--url=zoommtg://zoom.us/join'])


class DiscordReadOnlyOpenerTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0:
            self.skipTest('root needed only for trusted-file ownership fixtures')
        self.temporary = tempfile.TemporaryDirectory(prefix='discord-opener-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.opener = self.root / 'compat-open-uri'
        self.opener.write_text('#!/bin/sh\nprintf "compatibility-opener\\n"\n')
        self.opener.chmod(0o755)
        self.destinations = tuple(self.root / path for path in ('usr/bin/xdg-open', 'bin/xdg-open', 'usr/local/bin/xdg-open'))
        for path in self.destinations:
            path.parent.mkdir(parents=True, exist_ok=True)
        for path in self.destinations[:2]:
            self.vendor_file(path)

    def vendor_file(self, path):
        path.write_text('#!/bin/sh\nprintf "vendor-opener\\n"\n')
        path.chmod(0o755)

    def mounts(self):
        command = []
        with mock.patch.object(sandbox, 'COMPATIBILITY_URI_OPENER', str(self.opener)), \
             mock.patch.object(sandbox, 'COMPATIBILITY_URI_OPENER_DESTINATIONS', tuple(map(str, self.destinations))):
            sandbox.add_compatibility_uri_opener(command)
        return command

    def require_namespaces(self):
        if not Path('/usr/bin/bwrap').is_file():
            self.skipTest('Bubblewrap unavailable')
        probe = subprocess.run(['/usr/bin/bwrap', '--unshare-all', '--ro-bind', '/', '/', '--', '/bin/true'],
                               capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('private namespaces unavailable: ' + probe.stderr.decode('utf-8', 'replace')[:200])

    def check_read_only_launch(self):
        # Independent /bin and /usr/bin directories reproduce the alias mounts,
        # rather than assuming that replacing one inode replaces every pathname.
        before = {path: path.read_bytes() for path in self.destinations if path.exists()}
        command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/',
                   *self.mounts(), '--cap-drop', 'ALL', '--', sys.executable, '-B', '-c',
                   '''import errno,os,subprocess,sys
for path in sys.argv[1:]:
 if os.path.exists(path):
  result=subprocess.run([path,'https://example.org/'],capture_output=True,check=True)
  assert result.stdout==b'compatibility-opener\\n'
 for target in (path, os.path.join(os.path.dirname(path),'cannot-create')):
  try: fd=os.open(target,os.O_WRONLY|os.O_CREAT,0o600)
  except OSError as exc: assert exc.errno==errno.EROFS, (target,exc)
  else: os.close(fd); raise AssertionError('system path became writable')
''', *map(str, self.destinations)]
        result = subprocess.run(command, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_missing_optional_local_entry_reproduces_error_then_launches_read_only(self):
        self.require_namespaces()
        legacy = subprocess.run(['/usr/bin/bwrap', '--unshare-all', '--ro-bind', '/', '/',
                                 '--ro-bind', str(self.opener), str(self.destinations[-1]), '--', '/bin/true'],
                                capture_output=True, timeout=5)
        self.assertNotEqual(legacy.returncode, 0)
        self.assertIn(b'Read-only file system', legacy.stderr)
        self.check_read_only_launch()
        self.assertFalse(self.destinations[-1].exists())

    def test_existing_local_entry_and_both_bin_aliases_use_the_private_handler(self):
        self.require_namespaces()
        self.vendor_file(self.destinations[-1])
        self.check_read_only_launch()

    def test_required_packaged_opener_must_exist(self):
        self.destinations[0].unlink()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.mounts()

    def test_unsafe_optional_mount_points_fail_before_starting_application(self):
        path = self.destinations[-1]
        for problem in ('symlink', 'directory', 'writable', 'nonexecutable', 'foreign-owner'):
            with self.subTest(problem=problem):
                if problem == 'symlink':
                    path.symlink_to(self.opener)
                elif problem == 'directory':
                    path.mkdir()
                else:
                    self.vendor_file(path)
                    if problem == 'writable': path.chmod(0o775)
                    if problem == 'nonexecutable': path.chmod(0o644)
                    if problem == 'foreign-owner': os.chown(path, 65534, 65534)
                try:
                    with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        self.mounts()
                finally:
                    path.rmdir() if problem == 'directory' else path.unlink()


if __name__ == '__main__':
    unittest.main()
