"""Notification placement/click/size regression tests, without live host changes."""
from __future__ import annotations

import contextlib
import ctypes.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from test_native_tomat_20260920 import FORKY, SKEL, bars, load


def rendered_profile_styles():
    """Expand CSS using each real desktop profile's shell variable values."""
    template = (SKEL / 'waybar/style.css.tmpl').read_text()
    styles = {}
    for profile in sorted((FORKY / 'hosts/profiles').glob('*.env')):
        if 'LABWC_WAYBAR_FONT_SIZE=' not in profile.read_text():
            continue
        result = subprocess.run(
            ['/bin/sh', '-ec', 'set -a; . "$1"; env -0', 'waybar-style-fixture', str(profile)],
            env={'PATH': '/usr/bin:/bin'}, capture_output=True, check=True, timeout=5)
        environment = dict(item.decode().split('=', 1) for item in result.stdout.split(b'\0') if item)
        styles[profile.stem] = re.sub(
            r'__INSTALLER_([A-Z0-9_]+)__', lambda match: environment[match[1]], template)
    return styles


class NotificationsFollowupTests(unittest.TestCase):
    def test_both_real_bar_layouts_end_with_controls_notifications_lock_power(self):
        configurations = bars()
        self.assertEqual(len(configurations), 2)
        for bar in configurations:
            with self.subTest(bar=bar['name']):
                controls = ('group/quick-controls-internal' if bar['name'] == 'internal'
                            else 'group/quick-controls')
                right = bar['modules-right']
                self.assertEqual(right[-4:], [controls, 'custom/notifications', 'custom/lock', 'custom/power'])
                self.assertEqual(right.count('custom/notifications'), 1)
                self.assertEqual(right[right.index(controls) - 1], 'tray')
                self.assertNotIn('custom/notifications', bar[controls]['modules'])

    def test_native_left_click_menu_has_no_competing_left_click_command(self):
        for bar in bars():
            entry = bar['custom/notifications']
            self.assertEqual(entry['menu'], 'on-click')
            self.assertNotIn('on-click', entry)
            self.assertNotIn('on-click-release', entry)
            self.assertTrue(entry['on-click-middle'].endswith(' -- /usr/local/libexec/labwc-notifications dnd'))
            self.assertTrue(entry['on-click-right'].endswith(' -- /usr/local/libexec/labwc-notifications center'))
            self.assertEqual(entry['format'], '{}')
            self.assertTrue(entry['escape'])
            self.assertEqual(entry['return-type'], 'json')
            self.assertEqual(entry['menu-file'], '~/.config/waybar/notifications-menu.xml')
            self.assertEqual(set(entry['menu-actions']), {
                'notifications_dnd', 'notifications_clear', 'notifications_center',
                'notifications_dnd_on', 'notifications_dnd_off', 'notifications_restore', 'notifications_dismiss'})
            for action in entry['menu-actions'].values():
                for option in ('--user', '--service-type=exec', '--expand-environment=no',
                               '--property=Requisite=labwc-session.target',
                               '--property=PartOf=labwc-session.target',
                               '--property=ExitType=cgroup', '--property=KillMode=control-group'):
                    self.assertIn(option, action)

    def test_status_uses_bell_icons_and_describes_actual_mouse_bindings(self):
        helper = load('labwc-notifications')
        for modes, icon, state in (('default\n', '\U0001f514', 'normal'),
                                   ('default\ndo-not-disturb\n', '\U0001f515', 'dnd')):
            with self.subTest(state=state), mock.patch.object(helper, 'environment', return_value={}), \
                    mock.patch.object(helper, 'mako', return_value=modes) as mako:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(helper.main(['status']), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result['text'], icon)
                self.assertEqual(result['class'], state)
                self.assertIn('Left: menu | Middle: DND | Right: notification center', result['tooltip'])
                mako.assert_called_once_with(['mode'], {})

    def test_every_desktop_profile_css_resolves_session_geometry(self):
        styles = rendered_profile_styles()
        self.assertEqual(len(styles), 13)
        for name, css in styles.items():
            with self.subTest(profile=name):
                self.assertNotIn('__INSTALLER_', css)
                self.assertIn('window#waybar.internal #custom-notifications,\n'
                              'window#waybar.internal #custom-lock,\n'
                              'window#waybar.internal #custom-power {', css)
                self.assertIn('#custom-notifications,\n#custom-lock,\n#custom-power {', css)
                self.assertIn('#custom-notifications:hover {\n  background: @amber;', css)

    def test_native_gtk_sizes_fonts_and_gold_hover_for_all_profiles(self):
        if not shutil.which('xvfb-run') or not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3 / Xvfb unavailable')
        with tempfile.TemporaryDirectory() as work:
            paths = []
            for name, css in rendered_profile_styles().items():
                path = Path(work) / (name + '.css')
                path.write_text(css)
                paths.append(str(path))
            # This probes GTK labels with Waybar's CSS names/classes; it does not
            # claim Wayland compositor or input-event integration acceptance.
            result = subprocess.run(
                ['xvfb-run', '-a', '/usr/bin/python3', '-I', '-B',
                 str(FORKY / 'tests/fixtures/waybar-session-buttons-gtk.py'), *paths],
                env={**os.environ, 'GDK_BACKEND': 'x11', 'NO_AT_BRIDGE': '1'},
                text=True, capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['gtk_cases'], 13 * 2 * 2 * 2)
            self.assertEqual(len(report['records']), report['gtk_cases'])
            for record in report['records']:
                if record['hover']:
                    self.assertEqual(record['hover_rgb'], [236, 184, 96])


if __name__ == '__main__':
    unittest.main()
