"""Unexecuted regression cases for the opt-in diagnostic data contracts.

No native helper, app, service, bus, socket, package state or host configuration
is used by these cases. Repository policy still prohibits executing the suite.
"""
from pathlib import Path as _Path
import sys as _sys
_sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_sys.path.pop(0)
_require_test_isolation()

import os
from pathlib import Path
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'


class ApplicationDiagnosticContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = runpy.run_path(str(TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/diagnostics.py'))
        cls.observer = runpy.run_path(str(TARGET / 'usr/local/libexec/labwc-debug-session'))
        cls.capture = runpy.run_path(str(TARGET / 'usr/local/libexec/rsyslog-app-run.tmpl'))

    def request(self, profile='full'):
        return {'LABWC_DEBUG_PROFILE': profile, 'LABWC_DEBUG_SESSION': 'a' * 24,
                'LABWC_DEBUG_DESKTOP_ID': 'org.example.Editor.desktop',
                'LABWC_DEBUG_EXECUTABLE': '/opt/Example Editor/editor'}

    def test_profiles_preserve_native_renderer_policy_and_add_protocol_logs(self):
        for profile in ('gtk', 'qt', 'electron', 'full', 'wayland-graphics'):
            env = {'GDK_BACKEND': 'wayland', 'QT_QPA_PLATFORM': 'wayland',
                   'GDK_DISABLE': 'vulkan', 'GSK_RENDERER': 'opengl', 'QSG_RHI_BACKEND': 'opengl'}
            original = dict(env)
            with patch.dict(os.environ, self.request(profile), clear=True):
                self.policy['apply'](env)
            self.assertEqual({key: env[key] for key in original}, original)
            self.assertEqual(env['WAYLAND_DEBUG'], 'client')
            self.assertEqual(env['VK_LOADER_DEBUG'], 'error,warn,info,driver')
            self.assertNotIn('DISPLAY', env)
            self.assertNotIn('LD_PRELOAD', env)
            if profile in ('gtk', 'full'):
                self.assertEqual(env['GTK_DEBUG'], 'interactive')
            if profile in ('qt', 'full'):
                self.assertEqual(env['QT_DEBUG_PLUGINS'], '1')
            if profile in ('electron', 'full'):
                self.assertEqual(env['ELECTRON_ENABLE_LOGGING'], '1')

    def test_absent_profile_does_not_enable_debugging(self):
        with patch.dict(os.environ, {}, clear=True):
            env = {'GDK_BACKEND': 'wayland'}
            self.policy['apply'](env)
        self.assertEqual(env, {'GDK_BACKEND': 'wayland'})

    def test_malformed_profile_session_and_control_labels_fail(self):
        for key, value in (('LABWC_DEBUG_PROFILE', 'gdm'),
                           ('LABWC_DEBUG_SESSION', '../other'),
                           ('LABWC_DEBUG_DESKTOP_ID', 'app\nother'),
                           ('LABWC_DEBUG_EXECUTABLE', 'x' * 1025)):
            request = dict(self.request(), **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.policy['context'](request)

    def test_private_compatibility_environment_preserves_backend_policy(self):
        env = {'GDK_BACKEND': 'x11', 'QT_QPA_PLATFORM': 'xcb'}
        with patch.dict(os.environ, self.request('xwayland'), clear=True):
            self.policy['apply'](env, compatibility=True)
        self.assertEqual(env['GDK_BACKEND'], 'x11')
        self.assertEqual(env['QT_QPA_PLATFORM'], 'xcb')
        self.assertEqual(env['WAYLAND_DEBUG'], 'client')
        self.assertNotIn('GTK_DEBUG', env)
        with patch.dict(os.environ, self.request('gtk'), clear=True), self.assertRaises(ValueError):
            self.policy['apply'](env, compatibility=True)

    def test_real_wlrctl_format_preserves_colons_in_titles(self):
        function = self.observer['toplevels']
        report = {'status': 0, 'output': 'org.example.Editor: Project: notes\nqt6ct: Qt Settings\n'}
        with patch.dict(function.__globals__, command=lambda *args, **kwargs: dict(report)):
            result = function()
        self.assertEqual(result['records'], [
            {'app_id': 'org.example.Editor', 'title': 'Project: notes'},
            {'app_id': 'qt6ct', 'title': 'Qt Settings'}])

    def test_failed_toplevel_query_does_not_invent_identity(self):
        function = self.observer['toplevels']
        with patch.dict(function.__globals__, command=lambda *args, **kwargs: {'status': 1, 'output': 'unavailable'}):
            self.assertEqual(function()['records'], [])

    def test_path_traversal_rejected_before_filesystem_access(self):
        with self.assertRaises(ValueError):
            self.observer['open_session']('../other')
        with self.assertRaises(ValueError):
            self.observer['read_file'](-1, '../request.json')

    def test_process_replacement_does_not_publish_mapped_identity(self):
        function = self.observer['process_evidence']
        reads = iter(['1 (app) ' + ' '.join(['S', *(['0'] * 18), '10']),
                      '0::/user.slice/user-1000.slice/app.service\n',
                      '0000-0001 r-xp 0 0 0 /usr/lib/libgtk-4.so.1\n',
                      '1 (app) ' + ' '.join(['S', *(['0'] * 18), '11'])])
        fake_os = SimpleNamespace(getuid=lambda: 1000, readlink=lambda path: '/usr/bin/example')
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_uid=1000)), \
                patch.dict(function.__globals__, os=fake_os, proc_read=lambda *args: next(reads)):
            result = function(123, '/user.slice/user-1000.slice/app.service')
        self.assertEqual(result, {'pid': 123, 'unavailable': 'identity-replaced'})

    def test_second_collector_cannot_poison_active_collector_status(self):
        function = self.observer['collect']
        closed = []
        written = []
        def locked(*args):
            raise BlockingIOError('owned by another collector')
        fake_os = SimpleNamespace(open=lambda *args, **kwargs: 901, close=closed.append,
                                  O_RDWR=0, O_NOFOLLOW=0, O_CLOEXEC=0)
        fake_lock = SimpleNamespace(flock=locked, LOCK_EX=0, LOCK_NB=0)
        with patch.dict(function.__globals__, os=fake_os, fcntl=fake_lock,
                        open_session=lambda session: 900, safe_meta=lambda fd: None,
                        write_json=lambda *args: written.append(args)), self.assertRaises(BlockingIOError):
            function('a' * 24)
        self.assertEqual(closed, [901, 900])
        self.assertEqual(written, [])

    def test_output_limit_records_truncation_and_closes_only_owned_descriptor(self):
        copy = self.capture['DiagnosticCopy'].__new__(self.capture['DiagnosticCopy'])
        copy.fd, copy.remaining, copy.deadline = 901, 2048, 10
        output, closed = [], []
        fake_os = SimpleNamespace(write=lambda fd, raw: output.append((fd, raw)) or len(raw),
                                  close=closed.append)
        with patch.dict(copy.write.__globals__, os=fake_os,
                        time=SimpleNamespace(monotonic=lambda: 1)):
            copy.write({'event': 'output', 'message': 'x' * 5000})
        self.assertIn(b'capture-limit', output[0][1])
        self.assertEqual(closed, [901])
        self.assertIsNone(copy.fd)


if __name__ == '__main__':
    unittest.main()
