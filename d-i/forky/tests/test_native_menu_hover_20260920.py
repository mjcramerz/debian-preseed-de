"""Five native menus: rendered commands, real GTK states, and center reachability.

GTK is exercised through the existing shared-library ABI, not a compiled or
patched Waybar. Backend calls are inspected/intercepted; no host control action,
notification service, microphone or user manager is touched.
"""
from __future__ import annotations

import contextlib
import ctypes.util
import io
import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from test_native_tomat_20260920 import FORKY, LIBEXEC, SKEL, TARGET, load
from test_native_menu_contract_20260920 import CALENDAR, MODULES
from test_notifications_followup_20260920 import rendered_profile_styles


def rendered_profile_bars():
    """Capture substitutions from the real renderer, with only target I/O stubbed."""
    template = (SKEL / 'waybar/config.tmpl').read_text()
    script = r'''
. "$1"
. "$2/detect.sh"
. "$2/components.sh"
desktop_render_role_target_template_deferred() { shift 3; printf '%s\0' "$@"; }
desktop_assert_role_target_template_resolved() { :; }
desktop_log() { :; }
installer_warn() { :; }
desktop_render_waybar_config
'''
    result = {}
    for profile in sorted((FORKY / 'hosts/profiles').glob('*.env')):
        if 'LABWC_WAYBAR_FONT_SIZE=' not in profile.read_text():
            continue
        response = subprocess.run(
            ['/bin/sh', '-eu', '-c', script, 'native-menu-render', str(profile),
             str(FORKY / 'scripts/desktop')], env={'PATH': '/usr/bin:/bin'},
            capture_output=True, check=True, timeout=10)
        fields = response.stdout.decode().split('\0')[:-1]
        if len(fields) % 2:
            raise AssertionError('renderer returned an incomplete key/value pair')
        text = template
        for key, value in zip(fields[::2], fields[1::2]):
            text = text.replace('__INSTALLER_' + key + '__', value)
        if '__INSTALLER_' in text:
            raise AssertionError('unresolved Waybar profile: ' + profile.name)
        result[profile.stem] = json.loads(text)
    return result


def gtk_menu_report():
    """Run native GTK in a disposable X display; production stays Wayland-only."""
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        styles = rendered_profile_styles()
        profiles = []
        for name, bars in rendered_profile_bars().items():
            css = root / (name + '.css')
            css.write_text(styles[name])
            profiles.append({'name': name, 'css': str(css), 'bars': bars})
        data = root / 'profiles.json'
        data.write_text(json.dumps(profiles))
        result = subprocess.run(
            ['xvfb-run', '-a', '/usr/bin/python3', '-I', '-B',
             str(FORKY / 'tests/fixtures/native-menus-hover-gtk.py'), str(FORKY), str(data)],
            env={**os.environ, 'GDK_BACKEND': 'x11', 'NO_AT_BRIDGE': '1', 'G_DEBUG': 'fatal-criticals'},
            text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads(result.stdout)


class NativeMenuHoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = rendered_profile_bars()

    def test_real_rendered_profiles_keep_every_menu_action_and_gesture(self):
        self.assertEqual(len(self.profiles), 10)
        count = 0
        for name, bars in self.profiles.items():
            self.assertEqual(len(bars), 2)
            for bar in bars:
                for module, menu, event in MODULES:
                    with self.subTest(profile=name, layout=bar['name'], menu=menu):
                        entry = bar[module]
                        self.assertEqual(entry['menu'], event)
                        self.assertNotIn(event, entry)
                        self.assertNotIn(event + '-release', entry)
                        tree = ET.parse(SKEL / 'waybar' / (menu + '-menu.xml'))
                        ids = {item.get('id') for item in tree.iter('object')
                               if item.get('class') == 'GtkMenuItem'
                               and item.find('./child[@type="submenu"]') is None}
                        self.assertEqual(ids, set(entry['menu-actions']))
                        for command in entry['menu-actions'].values():
                            argv = shlex.split(command)
                            self.assertEqual(argv[0], '/usr/bin/systemd-run')
                            self.assertIn('--no-block', argv[:argv.index('--')])
                            self.assertIn('--property=PartOf=labwc-session.target', argv)
                            self.assertIn('--property=ExitType=cgroup', argv)
                            self.assertIn('--property=KillMode=control-group', argv)
                            self.assertNotIn('fixture', argv)
                            count += 1
        self.assertEqual(count, len(self.profiles) * 2 * 42)

    def test_every_action_has_the_intended_backend_not_just_an_existing_id(self):
        expected = {
            'custom/tomat': {
                'tomat_default': ['start', 'default'], 'tomat_25': ['start', '25'],
                'tomat_50': ['start', '50'], 'tomat_90': ['start', '90'],
                'tomat_toggle': ['toggle'], 'tomat_skip': ['skip'], 'tomat_stop': ['stop'],
                'tomat_config': ['config'], 'tomat_notifications': ['settings', 'notifications'],
                'tomat_sounds': ['settings', 'sounds']},
            'clock': {key: [value] for key, value in CALENDAR.items()},
            'custom/notifications': {
                'notifications_center': ['center'], 'notifications_restore': ['restore'],
                'notifications_dnd_on': ['dnd-on'], 'notifications_dnd_off': ['dnd-off'],
                'notifications_dnd': ['dnd'], 'notifications_dismiss': ['dismiss'],
                'notifications_clear': ['clear']},
            'custom/power': {
                'power_lock': ['lock'], 'power_suspend': ['suspend'], 'power_reboot': ['reboot'],
                'power_logout': ['logout'], 'power_shutdown': ['poweroff']},
        }
        helpers = {'custom/tomat': '/usr/local/libexec/labwc-tomat',
                   'clock': '/usr/local/bin/labwc-calendar',
                   'custom/notifications': '/usr/local/libexec/labwc-notifications',
                   'custom/power': '/usr/local/bin/labwc-power-settings'}
        audio = {
            'audio_open': ['pavucontrol'],
            'audio_mute': ['/usr/bin/wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', 'toggle'],
            'audio_mic': ['/usr/bin/wpctl', 'set-mute', '@DEFAULT_AUDIO_SOURCE@', 'toggle'],
            'audio_40': ['/usr/bin/wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', '40%', '--limit', '1.2'],
            'whisper_record': ['/usr/local/libexec/whisper-record-toggle', 'start'],
            'whisper_transcribe': ['/usr/bin/systemctl', '--user', '--no-block', 'start', 'whisper-transcribe.service'],
            'whisper_stop': ['/usr/local/libexec/whisper-record-toggle', 'stop'],
            'whisper_cancel': ['/usr/bin/systemctl', '--user', 'stop', 'whisper-transcribe.service']}
        for bars in self.profiles.values():
            for bar in bars:
                for module, actions in expected.items():
                    self.assertEqual(set(bar[module]['menu-actions']), set(actions))
                    self.assertTrue((TARGET / helpers[module].lstrip('/')).is_file())
                    for key, args in actions.items():
                        argv = shlex.split(bar[module]['menu-actions'][key])
                        self.assertEqual(argv[argv.index('--') + 1:], [helpers[module], *args])
                for key, args in audio.items():
                    argv = shlex.split(bar['pulseaudio']['menu-actions'][key])
                    self.assertEqual(argv[argv.index('--') + 1:], args)

    def test_notifications_center_label_menu_and_secondary_click_match(self):
        xml = ET.parse(SKEL / 'waybar/notifications-menu.xml')
        item = xml.find('.//object[@id="notifications_center"]')
        self.assertEqual(item.findtext('./child/object[@class="GtkBox"]/child/object[@class="GtkLabel"]/property[@name="label"]'), 'Open notifications center')
        for bars in self.profiles.values():
            for bar in bars:
                entry = bar['custom/notifications']
                commands = [entry['menu-actions']['notifications_center'], entry['on-click-right']]
                for command in commands:
                    argv = shlex.split(command)
                    self.assertEqual(argv[argv.index('--') + 1:],
                                     ['/usr/local/libexec/labwc-notifications', 'center'])

    def test_native_gtk_amber_tint_keyboard_submenus_disabled_and_callbacks(self):
        if not shutil.which('xvfb-run') or not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3 / Xvfb unavailable')
        report = gtk_menu_report()
        self.assertEqual(report['profiles'], 10)
        self.assertEqual(report['themes'], ['Adwaita', 'Adwaita-dark'])
        self.assertEqual(report['menu_roots'], 10 * 2 * 2 * 2 * 5)
        self.assertEqual(report['activations'], 10 * 2 * 2 * (42 + 38))
        self.assertEqual(report['center_activations'], 10 * 2 * 2 * 2)
        self.assertGreater(report['highlight_states'], 10000)
        self.assertGreater(report['disabled_states'], 100)
        self.assertEqual(report['hover_rgba'], [236, 184, 96, 0.16])
        self.assertEqual(report['callback_errors'], [])


class NotificationCenterReachabilityTests(unittest.TestCase):
    def setUp(self):
        self.helper = load('labwc-notifications')

    def invoke_cli(self, argv, *, backend_error=None, backend_output=None, privileged=False):
        """Exercise the actual __main__ exception/exit path with a fake process."""
        stdout, stderr = io.StringIO(), io.StringIO()
        runtime_info = types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1000)
        account = types.SimpleNamespace(pw_dir='/home/fixture', pw_name='fixture')
        original_popen = subprocess.Popen
        children = []

        def spawn(command, **kwargs):
            if backend_error is not None:
                raise backend_error
            # A real bounded pipe reader, but no real makoctl or bus access.
            self.assertEqual(command, ['/usr/bin/makoctl', 'mode'])
            source = 'import sys; sys.stdout.write(' + repr(backend_output or '') + ')'
            child = original_popen([sys.executable, '-I', '-c', source], **kwargs)
            children.append(child)
            return child

        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            stack.enter_context(mock.patch.object(sys, 'argv', ['labwc-notifications', *argv]))
            stack.enter_context(mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1000'}, clear=True))
            stack.enter_context(mock.patch('os.getuid', return_value=0 if privileged else 1000))
            stack.enter_context(mock.patch('os.geteuid', return_value=0 if privileged else 1000))
            stack.enter_context(mock.patch('pathlib.Path.lstat', return_value=runtime_info))
            stack.enter_context(mock.patch('pwd.getpwuid', return_value=account))
            child_mock = stack.enter_context(mock.patch('subprocess.Popen', side_effect=spawn))
            with self.assertRaises(SystemExit) as exit_result:
                runpy.run_path(str(LIBEXEC / 'labwc-notifications'), run_name='__main__')
        for child in children:
            self.assertIsNotNone(child.poll())
            self.assertTrue(child.stdout.closed and child.stderr.closed)
        return exit_result.exception.code, stdout.getvalue(), stderr.getvalue(), child_mock

    def test_degraded_status_is_valid_visible_json_with_mouse_guidance(self):
        for error in (FileNotFoundError('makoctl unavailable'), PermissionError('bus unavailable'),
                      subprocess.TimeoutExpired('makoctl', 4)):
            with self.subTest(error=type(error).__name__):
                code, out, err, _ = self.invoke_cli(['status'], backend_error=error)
                self.assertEqual(code, 0)
                self.assertEqual(len(out.splitlines()), 1)
                payload = json.loads(out)
                self.assertEqual(payload['class'], 'error')
                self.assertTrue(payload['text'])
                self.assertIn('Notifications unavailable:', payload['tooltip'])
                self.assertIn(self.helper.MOUSE_HINT, payload['tooltip'])
                self.assertIn('labwc-notifications:', err)

    def test_successful_normal_and_dnd_status_keep_existing_contract(self):
        for output, state in (('default\n', 'normal'), ('default\ndo-not-disturb\n', 'dnd')):
            code, out, err, _ = self.invoke_cli(['status'], backend_output=output)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)['class'], state)
            self.assertEqual(err, '')

    def test_control_failures_do_not_masquerade_as_successful_status(self):
        for action in self.helper.ACTIONS:
            with self.subTest(action=action):
                code, out, err, _ = self.invoke_cli([action], backend_error=OSError('unavailable'))
                self.assertEqual(code, 1)
                self.assertEqual(out, '')
                self.assertIn('unavailable', err)

    def test_status_fallback_does_not_bypass_privileged_user_guard(self):
        code, out, err, process = self.invoke_cli(['status'], privileged=True)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['class'], 'error')
        self.assertIn('unprivileged desktop user', err)
        process.assert_not_called()
        code, out, err, process = self.invoke_cli(['center'], privileged=True)
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        process.assert_not_called()

    def test_invalid_status_invocation_remains_a_failure(self):
        code, out, err, process = self.invoke_cli(['status', 'extra'])
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('usage:', err)
        process.assert_not_called()

    def test_native_menu_center_dispatch_reaches_the_gtk_window_path(self):
        environment = {'WAYLAND_DISPLAY': 'wayland-0'}
        with mock.patch.object(self.helper, 'environment', return_value=environment), \
                mock.patch.object(self.helper, 'show_center', return_value=0) as center, \
                mock.patch.object(self.helper, 'mako') as mako:
            self.assertEqual(self.helper.main(['center']), 0)
        center.assert_called_once_with(environment)
        mako.assert_not_called()  # Opening is not an implicit dismiss/restore/DND action.

    def test_center_requires_wayland_instead_of_falling_back_to_xwayland(self):
        with self.assertRaisesRegex(self.helper.Error, 'managed Wayland display'):
            self.helper.show_center({})

    def test_center_keeps_an_explicit_unavailable_view_when_mako_is_down(self):
        with mock.patch.object(self.helper, 'mako', side_effect=OSError('fixture unavailable')):
            result = self.helper.snapshot({'WAYLAND_DISPLAY': 'wayland-0'})
        self.assertIsNone(result['active'])
        self.assertIsNone(result['history'])
        self.assertIsNone(result['dnd'])
        self.assertEqual(len(result['errors']), 3)
        self.assertTrue(all('fixture unavailable' in message for message in result['errors']))

    def test_native_center_environment_and_single_instance_contract_are_preserved(self):
        source = (LIBEXEC / 'labwc-notifications').read_text()
        self.assertTrue(source.startswith('#!/usr/bin/python3 -I\n'))
        for required in ('application_id=APP_ID', 'flags=Gio.ApplicationFlags.FLAGS_NONE',
                         'self.window.present()', 'max_workers=1', 'self.cancel.set()',
                         'self.executor.shutdown(wait=True, cancel_futures=True)'):
            self.assertIn(required, source)
        self.assertEqual(self.helper.APP_ID, 'org.labwc.NotificationCenter')
        account = types.SimpleNamespace(pw_dir='/home/fixture', pw_name='fixture')
        runtime = types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1000)
        poisoned = {'XDG_RUNTIME_DIR': '/run/user/1000', 'WAYLAND_DISPLAY': 'wayland-0',
                    'DISPLAY': ':99', 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/wrong-bus',
                    'PYTHONPATH': '/tmp/untrusted', 'GI_TYPELIB_PATH': '/tmp/untrusted',
                    'GTK_PATH': '/tmp/untrusted', 'LD_PRELOAD': '/tmp/untrusted.so'}
        with mock.patch.dict(os.environ, poisoned, clear=True), \
                mock.patch('os.getuid', return_value=1000), mock.patch('os.geteuid', return_value=1000), \
                mock.patch('pathlib.Path.lstat', return_value=runtime), \
                mock.patch('pwd.getpwuid', return_value=account):
            environment = self.helper.environment()
        self.assertEqual(environment['GDK_BACKEND'], 'wayland')
        self.assertEqual(environment['WAYLAND_DISPLAY'], 'wayland-0')
        self.assertEqual(environment['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=/run/user/1000/bus')
        for name in ('DISPLAY', 'PYTHONPATH', 'GI_TYPELIB_PATH', 'GTK_PATH', 'LD_PRELOAD'):
            self.assertNotIn(name, environment)
        policy = (TARGET / 'etc/apparmor.d/managed-waybar-menus').read_text()
        self.assertIn('dbus (bind) bus=session name=org.labwc.NotificationCenter,', policy)


if __name__ == '__main__':
    unittest.main()
