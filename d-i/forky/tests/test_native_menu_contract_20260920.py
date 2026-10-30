"""Native menu dispatch, hostile data, cancellation and installer wiring.

All backends are fixtures; no real power, audio, calendar, or user-manager
operation is run. Actual GTK Builder tests live in test_native_tomat_20260920.
"""
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

from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file, source_path as payload_source_path
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

import contextlib
import ctypes.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from test_native_tomat_20260920 import FORKY, TARGET, SKEL, LIBEXEC, bars, load

CALENDAR = {'calendar_open': ['/usr/local/bin/labwc-calendar'],
            'calendar_agenda': ['/usr/local/bin/labwc-agenda']}
CALENDAR.update({key: ['/usr/local/libexec/labwc-calendar-actions', action]
                for key, action in {'calendar_new_event': 'event-create', 'calendar_edit_event': 'event-manage',
                    'calendar_tasks': 'tasks-pending', 'calendar_all_tasks': 'tasks-all', 'calendar_new_task': 'task-create',
                    'calendar_edit_task': 'task-edit', 'calendar_show_task': 'task-details',
                    'calendar_done_task': 'task-complete', 'calendar_delete_task': 'task-delete'}.items()})

MODULES = (('custom/tomat', 'tomat', 'on-click'),
           ('pulseaudio', 'audio', 'on-click'),
           ('custom/notifications', 'notifications', 'on-click'),
           ('custom/power', 'power', 'on-click'),
           ('clock', 'calendar', 'on-click-release'))

RELEASE_BINDINGS = (
    ('custom/launcher', 'on-click-release', 'on-click'),
    ('custom/wayscriber', 'on-click-release', 'on-click'),
    ('network', 'on-click-right-release', 'on-click-right'),
    ('bluetooth', 'on-click-right-release', 'on-click-right'),
    ('custom/screenshot', 'on-click-release', 'on-click'),
    ('custom/screenshot', 'on-click-right-release', 'on-click-right'),
    ('backlight', 'on-click-release', 'on-click'),
    ('custom/battery', 'on-click-release', 'on-click'),
)


class MenuContractTests(unittest.TestCase):
    def test_release_binding_matrix_preserves_native_controls(self):
        for bar in bars():
            for module, release, press in RELEASE_BINDINGS:
                self.assertIn(release, bar[module])
                self.assertNotIn(press, bar[module])
            self.assertNotIn('on-click', bar['custom/keyboard'])
            self.assertIn('on-click-release', bar['custom/keyboard'])
            self.assertEqual(bar['ext/workspaces']['on-click'], 'activate')
            taskbar = bar.get('wlr/taskbar')
            if taskbar:
                self.assertEqual(taskbar['on-click'], 'minimize-raise')
                self.assertEqual(taskbar['on-click-right'], 'minimize-raise')
                self.assertEqual(taskbar['on-click-middle'], 'close')

    def test_all_82_actions_are_nonblocking_and_session_owned(self):
        count = 0
        for bar in bars():
            for module, name, event in MODULES:
                entry = bar[module]
                self.assertEqual(entry['menu'], event)
                self.assertNotIn(event, entry)
                self.assertNotIn(event + '-release', entry)
                self.assertNotIn(event, entry.get('actions', {}))
                tree = ET.parse(payload_source_path(SKEL / 'waybar' / 'menus' / (name + '-menu.xml')))
                roots = tree.findall('./object[@class="GtkMenu"][@id="menu"]')
                self.assertEqual(len(roots), 1)
                ids = [node.get('id') for node in tree.iter('object') if node.get('id')]
                self.assertEqual(len(ids), len(set(ids)))
                leaves = [node for node in tree.iter('object')
                          if node.get('class') == 'GtkMenuItem'
                          and node.find('./child[@type="submenu"]') is None]
                self.assertTrue(all(node.get('id') for node in leaves))
                self.assertEqual({node.get('id') for node in leaves}, set(entry['menu-actions']))
                for action in entry['menu-actions'].values():
                    argv = shlex.split(action)
                    self.assertEqual(argv[0], '/usr/local/libexec/labwc-waybar-run')
                    boundary = argv.index('--')
                    self.assertEqual(argv[:boundary], ['/usr/local/libexec/labwc-waybar-run'])
                    self.assertGreater(len(argv[boundary + 1:]), 0)
                    count += 1
        self.assertEqual(count, 82)

    def test_calendar_mapping_and_secondary_clicks(self):
        for bar in bars():
            entry = bar['clock']
            self.assertEqual(entry['menu-file'], '~/.config/waybar/gtk/calendar-menu.xml')
            self.assertEqual(set(entry['menu-actions']), set(CALENDAR))
            for key, action in CALENDAR.items():
                argv = shlex.split(entry['menu-actions'][key])
                self.assertEqual(argv[0], '/usr/local/libexec/labwc-waybar-run')
                self.assertEqual(argv[argv.index('--') + 1:], action)
            self.assertEqual(shlex.split(entry['on-click-right-release']),
                             ['/usr/local/libexec/labwc-waycal-control', 'open'])
            self.assertNotIn('on-click-right', entry)
            self.assertNotIn('on-click-middle', entry)
            self.assertNotIn('on-click-middle-release', entry)
            self.assertFalse(entry.get('actions'))
            self.assertNotIn('format-alt', entry)
            self.assertNotIn('format-alt-click', entry)
            self.assertNotIn('tooltip-format', entry)
            self.assertIs(entry['tooltip'], False)
            self.assertNotIn('labwc-calendar menu', json.dumps(entry))

    def test_secondary_clicks_preserve_previous_primary_actions(self):
        for bar in bars():
            tomat = shlex.split(bar['custom/tomat']['on-click-right'])
            self.assertEqual(tomat[0], '/usr/local/libexec/labwc-waybar-run')
            self.assertEqual(tomat[tomat.index('--') + 1:], ['/usr/local/libexec/labwc-tomat', 'toggle'])
            audio = shlex.split(bar['pulseaudio']['on-click-right'])
            self.assertEqual(audio[0], '/usr/local/libexec/labwc-waybar-run')
            self.assertEqual(audio[audio.index('--') + 1:], ['pavucontrol'])

    def test_touchpad_keeps_a_physical_right_button_and_two_finger_right_tap(self):
        tree = ET.fromstring(payload_read_text(SKEL / 'labwc/rc.xml'))
        devices = tree.findall('./libinput/device[@category="touchpad"]')
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].findtext('clickMethod'), 'buttonAreas')
        self.assertEqual(devices[0].findtext('tapButtonMap'), 'lrm')

    def test_notification_mapping_is_the_controller_allowlist(self):
        helper = load('labwc-notifications')
        for bar in bars():
            actual = set()
            for command in bar['custom/notifications']['menu-actions'].values():
                argv = shlex.split(command)
                target = argv[argv.index('--') + 1:]
                self.assertEqual(target[0], '/usr/local/libexec/labwc-notifications')
                self.assertEqual(len(target), 2)
                actual.add(target[1])
            self.assertEqual(actual, set(helper.ACTIONS) | {'center'})

    def test_all_five_menu_assets_are_explicitly_staged(self):
        source = payload_read_text(FORKY / 'scripts/desktop/components.sh')
        start = source.index('desktop_stage_waybar_native_menus() {')
        function = source[start:source.index('\n}\n', start) + 3]
        with tempfile.TemporaryDirectory() as work:
            script = ('desktop_render_waybar_asset() { printf "etc/skel-desktop/.config/waybar/gtk/%s\\t/etc/skel-desktop/.config/waybar/gtk/%s\\t0644\\n" "$1" "$1"; }\n'
                      'desktop_stage_role_asset() { printf "%s\\t%s\\t%s\\n" "$1" "$2" "$3"; }\n'
                      'desktop_whisper_addon_selected() { return 1; }\n'
                      'run_in_target() { :; }\n' + function + '\ndesktop_stage_waybar_native_menus\n')
            result = subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', script]), text=True,
                                    capture_output=True, timeout=5, cwd=work, check=True)
        staged = [line.split('\t') for line in result.stdout.splitlines()]
        for _, name, _ in MODULES:
            path = f'etc/skel-desktop/.config/waybar/gtk/{name}-menu.xml'
            self.assertIn([path, '/' + path, '0644'], staged)
            self.assertTrue(payload_source_is_file(TARGET / path))

    def test_optional_whisper_is_disabled_not_dangling_and_reversible(self):
        source = payload_read_text(FORKY / 'scripts/desktop/components.sh')
        code = source.split('run_in_target "configure optional native audio menu" /usr/bin/python3 -I -c \'\n', 1)[1].split("\n' \"$native_menu_whisper\"", 1)[0]
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / 'audio-menu.xml'
            path.write_bytes(payload_read_bytes(SKEL / 'waybar/gtk/audio-menu.xml'))
            original_ids = {obj.get('id') for obj in ET.parse(path).iter('object') if obj.get('id')}
            for enabled in ('0', '1', '0'):
                with mock.patch('pathlib.Path', return_value=path), mock.patch.object(sys, 'argv', ['fixture', enabled]):
                    exec(compile(code, 'native-audio-staging', 'exec'), {})
                tree = ET.parse(path)
                self.assertEqual({obj.get('id') for obj in tree.iter('object') if obj.get('id')}, original_ids)
                parent = next(obj for obj in tree.iter('object') if obj.get('class') == 'GtkMenuItem'
                              and obj.find('.//object[@id="whisper_record"]') is not None)
                self.assertEqual(parent.findtext('./property[@name="sensitive"]'), 'True' if enabled == '1' else 'False')
                self.assertEqual(parent.findtext('./child/object[@class="GtkBox"]/child/object[@class="GtkLabel"]/property[@name="label"]'), 'Whisper' if enabled == '1' else 'Whisper (not installed)')

    def test_actual_gtk_honors_optional_whisper_sensitive_property(self):
        if not shutil.which('xvfb-run') or not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3 / Xvfb unavailable')
        result = subprocess.run(
            payload_installed_argv(['xvfb-run', '-a', '/usr/bin/python3', '-I', '-B',
             str(FORKY / 'tests/fixtures/native-menu-whisper-gtk.py'), str(FORKY)]),
            env={**os.environ, 'GDK_BACKEND': 'x11', 'NO_AT_BRIDGE': '1'},
            text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('PASS: actual staged GtkMenu'), 3)

    def test_installer_checks_every_menu_and_required_gtk_dependency(self):
        source = payload_read_text(FORKY / 'scripts/desktop/verify.sh')
        function = source.split('desktop_verify_native_menus() {', 1)[1].split('\ndesktop_verify_target_staging()', 1)[0]
        for _, name, _ in MODULES:
            self.assertIn('"' + name + '"', function)
        for text in ('menus=5', 'unwired native menu leaf', 'bounded Waybar runner',
                     'optional Whisper menu/service availability differs'):
            self.assertIn(text, function)
        self.assertIn('"format-alt" not in entry and "format-alt-click" not in entry', function)
        packages = payload_read_text(FORKY / 'classes/class-select/role/desktop.cfg').split()
        for package in ('python3-gi', 'gir1.2-gtk-3.0', 'gir1.2-gtklayershell-0.1',
                        'mako-notifier', 'libgtk4-layer-shell0'):
            self.assertIn(package, packages)


class WaycalPopupTests(unittest.TestCase):
    """Mock toolkit only; compositor delivery and focus need native acceptance."""
    def setUp(self):
        self.helper = load('labwc-waycal-popup')
        self.glib = SimpleNamespace(Error=RuntimeError, idle_add=mock.Mock(), timeout_add=mock.Mock())
        self.gtk = mock.MagicMock()
        self.gtk.main_level.return_value = 1
        self.gtk.STYLE_PROVIDER_PRIORITY_USER = 800
        self.gtk.WindowType.TOPLEVEL = 'toplevel'
        self.shell = mock.MagicMock()
        self.shell.Layer.OVERLAY = 'overlay'
        self.shell.KeyboardMode.NONE = 'no-keyboard'
        self.shell.Edge.TOP, self.shell.Edge.BOTTOM = 'top', 'bottom'
        self.shell.Edge.LEFT, self.shell.Edge.RIGHT = 'left', 'right'
        self.gio = mock.MagicMock()
        self.gio.SubprocessFlags.NONE = 0
        self.popup = self.helper.Popup((SimpleNamespace(EventMask=SimpleNamespace(
            BUTTON_PRESS_MASK=1, BUTTON_RELEASE_MASK=2)), self.gio, self.glib,
            self.gtk, self.shell), 'fixture')
        log = contextlib.redirect_stderr(io.StringIO())
        log.__enter__()
        self.addCleanup(log.__exit__, None, None, None)

    def prepare(self, count=2):
        display = mock.MagicMock()
        display.get_n_monitors.return_value = count
        self.windows = [mock.MagicMock() for _ in range(max(0, min(count, 32)))]
        self.gtk.Window.side_effect = self.windows
        self.popup.prepare(display)
        return display

    def test_all_outputs_paint_before_the_fixed_waycal_launch(self):
        display = self.prepare()
        self.gio.SubprocessLauncher.new.assert_not_called()
        self.popup.mapped_window(self.windows[0], None)
        self.glib.idle_add.assert_not_called()
        self.popup.mapped_window(self.windows[1], None)
        self.popup.mapped_window(self.windows[1], None)
        self.glib.idle_add.assert_not_called()
        for window in self.windows:
            self.popup.painted_window(window.get_frame_clock(), window)
            window.get_frame_clock().disconnect.assert_called_once()
        self.glib.idle_add.assert_called_once_with(self.popup.launch)
        self.popup.launch()
        display.sync.assert_called_once()
        launcher = self.gio.SubprocessLauncher.new.return_value
        launcher.spawnv.assert_called_once_with(['/opt/waycal/waycal', '--week-start', 'monday'])
        launcher.set_cwd.assert_called_once_with('/')
        launcher.spawnv.return_value.wait_async.assert_called_once_with(None, self.popup.application_exited)

    def test_surfaces_cover_all_outputs_without_keyboard_focus_or_key_handlers(self):
        self.prepare()
        for window in self.windows:
            window.set_accept_focus.assert_called_once_with(False)
            window.set_focus_on_map.assert_called_once_with(False)
            self.shell.set_keyboard_mode.assert_any_call(window, 'no-keyboard')
            self.shell.set_layer.assert_any_call(window, 'overlay')
            self.shell.set_exclusive_zone.assert_any_call(window, -1)
            for edge in ('top', 'bottom', 'left', 'right'):
                self.shell.set_anchor.assert_any_call(window, edge, True)
            self.assertEqual({call.args[0] for call in window.connect.call_args_list},
                             {'button-press-event', 'button-release-event', 'map-event', 'destroy'})

    def test_opening_release_does_not_dismiss(self):
        self.assertTrue(self.popup.release(None, SimpleNamespace(button=3)))
        self.assertFalse(self.popup.done)

    def test_each_mouse_button_dismisses_on_release_and_consumes_the_click(self):
        for button in (1, 2, 3, 8, 9):
            self.popup.done = False
            self.assertTrue(self.popup.press(None, SimpleNamespace(button=button)))
            self.assertFalse(self.popup.done)
            self.assertTrue(self.popup.release(None, SimpleNamespace(button=button)))
            self.assertTrue(self.popup.done)
            self.assertEqual(self.popup.status, 0)

    def test_multiple_buttons_keep_capture_until_last_release(self):
        self.popup.press(None, SimpleNamespace(button=1))
        self.popup.press(None, SimpleNamespace(button=3))
        self.popup.release(None, SimpleNamespace(button=1))
        self.assertFalse(self.popup.done)
        self.popup.release(None, SimpleNamespace(button=3))
        self.assertTrue(self.popup.done)

    def test_click_before_idle_launch_never_starts_waycal(self):
        self.prepare()
        for window in self.windows:
            self.popup.mapped_window(window, None)
            self.popup.painted_window(window.get_frame_clock(), window)
        self.popup.press(None, SimpleNamespace(button=1))
        self.popup.release(None, SimpleNamespace(button=1))
        self.popup.launch()
        self.gio.SubprocessLauncher.new.assert_not_called()

    def test_launch_failure_removes_every_capture_surface(self):
        self.prepare()
        self.gio.SubprocessLauncher.new.return_value.spawnv.side_effect = RuntimeError('fixture')
        self.popup.launch()
        self.assertEqual(self.popup.status, 3)
        for window in self.windows:
            window.destroy.assert_called_once()

    def test_missing_frame_clock_and_unfinished_frame_cleanup_fail_closed(self):
        self.prepare()
        self.windows[0].get_frame_clock.return_value = None
        self.popup.mapped_window(self.windows[0], None)
        self.assertEqual(self.popup.status, 3)
        self.glib.idle_add.assert_not_called()
        for window in self.windows:
            window.destroy.assert_called_once()

    def test_show_failure_never_maps_another_surface(self):
        # A synchronous failure while showing the first surface must never
        # show another already-destroyed capture window afterwards.
        windows = [mock.MagicMock(), mock.MagicMock()]
        self.gtk.Window.side_effect = windows
        windows[0].show_all.side_effect = lambda: self.popup.finish(3, 'fixture')
        display = mock.MagicMock()
        display.get_n_monitors.return_value = 2
        self.popup.prepare(display)
        windows[0].show_all.assert_called_once()
        windows[1].show_all.assert_not_called()
        for window in windows:
            window.destroy.assert_called_once()

    def test_output_change_disconnects_pending_frame_callbacks(self):
        self.prepare()
        for window in self.windows:
            self.popup.mapped_window(window, None)
        self.popup.changed()
        for window in self.windows:
            window.get_frame_clock().disconnect.assert_called_once()
            self.popup.painted_window(window.get_frame_clock(), window)
        self.glib.idle_add.assert_not_called()

    def test_output_change_and_destroy_close_every_surface_once(self):
        self.prepare()
        for window in self.windows:
            window.destroy.side_effect = self.popup.destroyed
        self.popup.changed()
        self.popup.destroyed()
        self.assertEqual(self.popup.status, 0)
        for window in self.windows:
            window.destroy.assert_called_once()
        self.gtk.main_quit.assert_called_once()

    def test_startup_deadline_and_application_exit_clear_capture(self):
        for successful in (True, False):
            self.popup.done = False
            child = mock.Mock()
            child.get_successful.return_value = successful
            self.popup.application_exited(child, 'result')
            child.wait_finish.assert_called_once_with('result')
            self.assertEqual(self.popup.status, 0 if successful else 3)
        self.popup.done = False
        self.popup.startup_expired()
        self.assertEqual(self.popup.status, 3)

    def test_invalid_output_counts_fail_before_creating_surfaces(self):
        for count in (0, 33):
            with self.assertRaises(ValueError):
                self.prepare(count)
        self.gtk.Window.assert_not_called()

    def test_context_requires_the_owned_unit_before_gui_import(self):
        environment = {'GDK_BACKEND': 'wayland', 'INVOCATION_ID': 'a' * 32}
        with mock.patch.object(self.helper.os, 'getuid', return_value=1000), \
                mock.patch.object(self.helper.os, 'geteuid', return_value=1000), \
                mock.patch.dict(self.helper.os.environ, environment, clear=True):
            for data, expected in ((b'0::/user.slice/labwc-waycal-popup.service\n', True),
                                   (b'0::/other.service\n', False),
                                   (b'0::/labwc-waycal-popup.service/child\n', False),
                                   (b'0::/labwc-waycal-popup.service\n1::/other\n', False),
                                   (b'a' * 4097, False)):
                with mock.patch.object(self.helper.Path, 'open', mock.mock_open(read_data=data)) as source:
                    self.assertEqual(self.helper.managed_context(), expected)
                    source.return_value.read.assert_called_once_with(4097)
            with mock.patch.dict(self.helper.os.environ, {'GDK_BACKEND': 'x11'}), \
                    mock.patch.object(self.helper.Path, 'open') as source:
                self.assertFalse(self.helper.managed_context())
                source.assert_not_called()


class WaycalControlTests(unittest.TestCase):
    def setUp(self):
        self.helper = load('labwc-waycal-control')
        self.uid = mock.patch.object(self.helper.os, 'getuid', return_value=1000)
        self.uid.start()
        self.addCleanup(self.uid.stop)
        self.environment = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': '/home/fixture',
                            'XDG_RUNTIME_DIR': '/run/user/1000',
                            'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}
        self.owner_query = self.helper.require_no_external_instance
        owner = mock.patch.object(self.helper, 'require_no_external_instance')
        self.owner = owner.start()
        self.addCleanup(owner.stop)

    def test_absent_popup_creates_one_transient_request(self):
        with mock.patch.object(self.helper, 'read_state', return_value=None), \
                mock.patch.object(self.helper, 'transient_argv', return_value=['fixture-systemd-run']), \
                mock.patch.object(self.helper, 'command', return_value=(0, '')) as command:
            self.assertEqual(self.helper.operate('open', self.environment, 100), 'open-requested')
            self.owner.assert_called_once_with(self.environment, 100)
            command.assert_called_once_with(['fixture-systemd-run'], self.environment, 100)

    def test_toggle_opens_absent_popup_and_closes_existing_one(self):
        with mock.patch.object(self.helper, 'read_state', return_value=None), \
                mock.patch.object(self.helper, 'transient_argv', return_value=['fixture-systemd-run']), \
                mock.patch.object(self.helper, 'command', return_value=(0, '')) as command:
            self.assertEqual(self.helper.operate('toggle', self.environment, 100), 'open-requested')
            command.assert_called_once_with(['fixture-systemd-run'], self.environment, 100)
        for state in ('active', 'activating', 'reloading'):
            with mock.patch.object(self.helper, 'read_state', return_value=state), \
                    mock.patch.object(self.helper, 'transient_argv') as launch, \
                    mock.patch.object(self.helper, 'command', return_value=(0, '')) as command:
                self.assertEqual(self.helper.operate('toggle', self.environment, 100), 'stop-requested')
                launch.assert_not_called()
                command.assert_called_once_with(self.helper.SYSTEMCTL +
                    ['--no-block', 'stop', self.helper.UNIT], self.environment, 100)

    def test_toggle_during_expiry_never_reopens_or_resets_a_unit(self):
        for state in ('deactivating', 'inactive', 'failed'):
            with mock.patch.object(self.helper, 'read_state', return_value=state), \
                    mock.patch.object(self.helper, 'transient_argv') as launch, \
                    mock.patch.object(self.helper, 'command') as command:
                expected = 'stop-requested' if state == 'deactivating' else 'closed'
                self.assertEqual(self.helper.operate('toggle', self.environment, 100), expected)
                launch.assert_not_called()
                command.assert_not_called()

    def test_new_toggle_after_collection_starts_a_fresh_service(self):
        with mock.patch.object(self.helper, 'read_state', side_effect=[None, 'active', 'deactivating', None]), \
                mock.patch.object(self.helper, 'transient_argv', return_value=['fixture-systemd-run']) as launch, \
                mock.patch.object(self.helper, 'command', return_value=(0, '')) as command:
            self.assertEqual([self.helper.operate('toggle', self.environment, 100) for _ in range(4)],
                             ['open-requested', 'stop-requested', 'stop-requested', 'open-requested'])
            self.assertEqual(launch.call_count, 2)
            self.assertEqual(command.call_count, 3)

    def test_expiry_between_read_and_stop_is_reconciled_without_retry(self):
        for current in (None, 'inactive', 'failed', 'deactivating'):
            with mock.patch.object(self.helper, 'read_state', side_effect=['active', current]) as state, \
                    mock.patch.object(self.helper, 'command', return_value=(1, '')) as command, \
                    mock.patch.object(self.helper, 'transient_argv') as launch:
                expected = 'stop-requested' if current == 'deactivating' else 'closed'
                self.assertEqual(self.helper.operate('toggle', self.environment, 100), expected)
                self.assertEqual(state.call_count, 2)
                command.assert_called_once()
                launch.assert_not_called()

    def test_failed_stop_with_active_or_unreadable_state_is_uncertain(self):
        for current in ('active', self.helper.Unavailable('fixture read failure')):
            with mock.patch.object(self.helper, 'read_state', side_effect=['active', current]), \
                    mock.patch.object(self.helper, 'command', return_value=(1, '')) as command:
                with self.assertRaises(self.helper.Uncertain):
                    self.helper.operate('toggle', self.environment, 100)
                command.assert_called_once()

    def test_repeated_open_coalesces_and_never_replaces_a_stopping_unit(self):
        for state in ('active', 'activating', 'reloading'):
            with mock.patch.object(self.helper, 'read_state', return_value=state), \
                    mock.patch.object(self.helper, 'command') as command:
                self.assertEqual(self.helper.operate('open', self.environment, 100), 'already-requested')
                command.assert_not_called()
        for state in ('deactivating', 'inactive', 'failed'):
            with mock.patch.object(self.helper, 'read_state', return_value=state), \
                    mock.patch.object(self.helper, 'command') as command:
                with self.assertRaises(self.helper.Unavailable):
                    self.helper.operate('open', self.environment, 100)
                command.assert_not_called()

    def test_close_targets_only_the_popup_and_is_idempotent(self):
        for state in ('active', 'activating', 'reloading'):
            with mock.patch.object(self.helper, 'read_state', return_value=state), \
                    mock.patch.object(self.helper, 'command', return_value=(0, '')) as command:
                self.assertEqual(self.helper.operate('close', self.environment, 100), 'stop-requested')
                command.assert_called_once_with(self.helper.SYSTEMCTL +
                    ['--no-block', 'stop', self.helper.UNIT], self.environment, 100)
        for state in (None, 'inactive', 'failed', 'deactivating'):
            with mock.patch.object(self.helper, 'read_state', return_value=state), \
                    mock.patch.object(self.helper, 'command') as command:
                expected = 'stop-requested' if state == 'deactivating' else 'closed'
                self.assertEqual(self.helper.operate('close', self.environment, 100), expected)
                command.assert_not_called()

    def test_failed_reads_and_unit_collisions_prevent_mutation(self):
        valid = ('LoadState=loaded\nActiveState=active\nTransient=yes\nDescription='
                 + self.helper.DESCRIPTION + '\n')
        for output, status in (('', 0), (valid, 1),
                               (valid.replace('Transient=yes', 'Transient=no'), 0),
                               (valid.replace(self.helper.DESCRIPTION, 'unrelated application'), 0),
                               (valid + 'ActiveState=inactive\n', 0),
                               (valid.replace('ActiveState=active', 'ActiveState=unexpected'), 0)):
            with mock.patch.object(self.helper, 'command', return_value=(status, output)) as command:
                with self.assertRaises(self.helper.Unavailable):
                    self.helper.operate('close', self.environment, 100)
                command.assert_called_once()
        with mock.patch.object(self.helper, 'command', return_value=(0, valid)):
            self.assertEqual(self.helper.read_state(self.environment, 100), 'active')
        absent = 'LoadState=not-found\nActiveState=inactive\nTransient=no\nDescription=\n'
        for status in (0, 1):
            with mock.patch.object(self.helper, 'command', return_value=(status, absent)):
                self.assertIsNone(self.helper.read_state(self.environment, 100))

    def test_uncertain_mutation_is_not_retried(self):
        for failure in (TimeoutError(), ValueError('fixture output limit')):
            with mock.patch.object(self.helper, 'read_state', return_value=None), \
                    mock.patch.object(self.helper, 'transient_argv', return_value=['fixture-systemd-run']), \
                    mock.patch.object(self.helper, 'command', side_effect=failure) as command:
                with self.assertRaises(self.helper.Uncertain):
                    self.helper.operate('open', self.environment, 100)
                command.assert_called_once()

    def test_external_gapplication_owner_prevents_launch(self):
        with mock.patch.object(self.helper, 'read_state', return_value=None), \
                mock.patch.object(self.helper, 'transient_argv') as launch, \
                mock.patch.object(self.helper, 'command') as command:
            self.owner.side_effect = self.helper.Unavailable('application-owner')
            with self.assertRaises(self.helper.Unavailable):
                self.helper.operate('open', self.environment, 100)
            launch.assert_not_called()
            command.assert_not_called()

    def test_owner_query_is_bounded_and_only_absence_allows_launch(self):
        for status, output in ((0, 'b true\n'), (1, 'b false\n'),
                               (0, 'b false\nextra'), (0, 'invalid')):
            with mock.patch.object(self.helper, 'command', return_value=(status, output)):
                with self.assertRaises(self.helper.Unavailable):
                    self.owner_query(self.environment, 100)
        with mock.patch.object(self.helper, 'command', return_value=(0, 'b false\n')) as query:
            self.owner_query(self.environment, 100)
            argv, environment, deadline = query.call_args.args
            self.assertEqual(argv[0], '/usr/bin/busctl')
            self.assertIn('--timeout=3s', argv)
            self.assertIn('--auto-start=no', argv)
            self.assertEqual(argv[-3:], ['NameHasOwner', 's', self.helper.APP_BUS_NAME])
            self.assertEqual((environment, deadline), (self.environment, 100))

    def test_root_and_extra_arguments_do_not_contact_manager(self):
        with mock.patch.object(self.helper, 'context') as context:
            self.assertEqual(self.helper.main([]), 2)
            self.assertEqual(self.helper.main(['open', 'extra']), 2)
            with mock.patch.object(self.helper.os, 'getuid', return_value=0):
                self.assertEqual(self.helper.main(['open']), 2)
            context.assert_not_called()

    def test_toggle_cli_uses_the_shared_lock_and_releases_it(self):
        with mock.patch.object(self.helper, 'context', return_value=self.environment), \
                mock.patch.object(self.helper, 'open_lock', return_value=17) as lock, \
                mock.patch.object(self.helper, 'operate', return_value='open-requested') as operation, \
                mock.patch.object(self.helper.os, 'close') as close, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.helper.main(['toggle']), 0)
            lock.assert_called_once()
            operation.assert_called_once_with('toggle', self.environment, lock.call_args.args[1])
            close.assert_called_once_with(17)
            self.assertIn('action=toggle status=open-requested', output.getvalue())

    def test_transient_service_keeps_native_layer_shell_and_scoped_isolation(self):
        endpoint = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=1000)
        with mock.patch.dict(self.helper.os.environ, {'WAYLAND_DISPLAY': 'wayland-fixture'}, clear=True), \
                mock.patch.object(self.helper.Path, 'lstat', return_value=endpoint):
            argv = self.helper.transient_argv(self.environment)
        self.assertEqual(argv[0], '/usr/bin/systemd-run')
        for value in ('--user', '--collect', '--no-block', '--service-type=exec',
                      '--expand-environment=no', '--unit=labwc-waycal-popup.service',
                      '--property=Requisite=labwc-session.target',
                      '--property=StopPropagatedFrom=waybar.service',
                      '--property=PartOf=labwc-session.target', '--property=ExitType=main',
                      '--property=KillMode=control-group', '--property=TimeoutStartSec=10s',
                      '--property=TimeoutStopSec=1s', '--property=RuntimeMaxSec=16s',
                      '--property=RuntimeRandomizedExtraSec=0', '--property=SuccessExitStatus=124',
                      '--property=PrivateUsers=yes',
                      '--property=PrivateTmp=yes',
                      '--property=PrivateIPC=yes', '--property=PrivateNetwork=yes',
                      '--property=ProtectSystem=full', '--setenv=GDK_BACKEND=wayland'):
            self.assertIn(value, argv)
        self.assertEqual(argv[argv.index('--') + 1:],
                         ['/usr/bin/timeout', '--signal=TERM', '--kill-after=1s', '15s',
                          '/usr/local/libexec/labwc-waycal-popup'])
        self.assertNotIn('--popup', argv)
        self.assertNotIn('--scope', argv)
        self.assertNotIn('--property=PrivateDevices=yes', argv)
        self.assertEqual(self.environment['WAYLAND_DISPLAY'], 'wayland-fixture')

    def test_invalid_display_is_rejected_before_socket_access(self):
        for value in ('', '/tmp/wayland-0', '../wayland-0', 'wayland-0\nother'):
            with mock.patch.dict(self.helper.os.environ, {'WAYLAND_DISPLAY': value}, clear=True), \
                    mock.patch.object(self.helper.Path, 'lstat') as access:
                with self.assertRaises(self.helper.Unavailable):
                    self.helper.transient_argv(self.environment)
                access.assert_not_called()

    def test_output_limit_and_final_wait_have_bounded_child_cleanup(self):
        # These are disposable-environment children, never management helpers.
        # The module's isolation guard runs before this fixture is imported.
        with tempfile.TemporaryDirectory() as directory:
            environment = {'PATH': '/usr/bin:/bin', 'HOME': directory, 'LC_ALL': 'C'}
            factory = subprocess.Popen
            children = []

            def spawn(*args, **kwargs):
                child = factory(*args, **kwargs)
                children.append(child)
                return child

            with mock.patch.object(self.helper.subprocess, 'Popen', side_effect=spawn):
                with self.assertRaises(ValueError):
                    self.helper.command([sys.executable, '-I', '-B', '-c', 'print("x" * 4096)'],
                                        environment, time.monotonic() + 3)
                with self.assertRaises((TimeoutError, subprocess.TimeoutExpired)):
                    self.helper.command([sys.executable, '-I', '-B', '-c',
                                         'import os, time; os.close(1); time.sleep(30)'],
                                        environment, time.monotonic() + 0.2)
            self.assertTrue(all(child.returncode is not None for child in children))

    def test_styles_and_controller_are_staged_and_static_units_are_retired(self):
        source = payload_read_text(FORKY / 'scripts/desktop/components.sh')
        self.assertIn('usr/local/libexec/labwc-waycal-control', source)
        self.assertIn('usr/local/libexec/labwc-waycal-popup', source)
        self.assertNotIn('labwc-waycal-toggle', source)
        self.assertIn('etc/skel-desktop/.config/waycal/style.css', source)
        self.assertIn('.config/waycal', source)
        for name in ('labwc-waycal.service', 'labwc-waycal-toggle.service'):
            self.assertFalse(payload_source_exists(SKEL / 'systemd/user' / name))
        style = payload_read_text(SKEL / 'waycal/style.css')
        self.assertIn('rgba(30, 23, 46, 0.94)', style)
        self.assertIn('window.waycal .waycal-root.rounded', style)
        menu = ET.fromstring(payload_read_text(SKEL / 'waybar/gtk/calendar-menu.xml'))
        for key, label in (('calendar_new_task_label', 'Create task...'),
                           ('calendar_edit_task_label', 'Edit task...'),
                           ('calendar_delete_task_label', 'Delete task...'),
                           ('calendar_done_task_label', 'Mark task completed...')):
            self.assertEqual(menu.findtext('.//object[@id="' + key + '"]/property[@name="label"]'), label)


class NotificationDataTests(unittest.TestCase):
    def setUp(self):
        self.helper = load('labwc-notifications')

    def test_actual_mako_111_nulls_and_field_names(self):
        row = {'id': 12, 'app_name': 'Mail', 'app_icon': None, 'category': None,
               'desktop_entry': None, 'summary': None, 'body': None,
               'urgency': 'normal', 'actions': {}}
        self.assertEqual(self.helper.notification_list(json.dumps([row])),
                         [{'summary': 'Notification', 'body': '', 'app': 'Mail'}])

    def test_text_controls_are_neutralized_without_interpreting_markup(self):
        raw = '<b>plain</b> $(touch /no)\n\t\0\x1b\x7f\ud800'
        row = self.helper.notification_list(json.dumps([{'summary': raw}]))[0]
        self.assertTrue(row['summary'].startswith('<b>plain</b> $(touch /no)\n\t'))
        for character in ('\0', '\x1b', '\x7f', '\ud800'):
            self.assertNotIn(character, row['summary'])

    def test_invalid_types_and_nested_json_fail_closed(self):
        for value in (1, True, {}, []):
            for key in ('summary', 'body', 'app_name'):
                with self.subTest(value=value, key=key), self.assertRaises(self.helper.Error):
                    self.helper.notification_list(json.dumps([{key: value}]))
        for text in ('invalid', '[' * 2000, 'x' * (self.helper.MAX_OUTPUT + 1)):
            with self.assertRaises(self.helper.Error):
                self.helper.notification_list(text)

    def test_named_actions_have_distinct_history_and_dnd_semantics(self):
        expected = {'dnd': ['mode', '-t', 'do-not-disturb'],
                    'dnd-on': ['mode', '-a', 'do-not-disturb'],
                    'dnd-off': ['mode', '-r', 'do-not-disturb'],
                    'dismiss': ['dismiss', '--all'],
                    'clear': ['dismiss', '--all', '--no-history'], 'restore': ['restore']}
        for action, argv in expected.items():
            with mock.patch.object(self.helper, 'environment', return_value={}), \
                    mock.patch.object(self.helper, 'mako', return_value='') as request:
                self.assertEqual(self.helper.main([action]), 0)
                request.assert_called_once_with(argv, {})

    def test_unknown_or_extra_arguments_do_not_touch_environment_or_backend(self):
        for args in ([], ['center', 'extra'], ['dnd-on', '--set'], ['clear-history'], ['menu']):
            with mock.patch.object(self.helper, 'environment') as environment, self.assertRaises(self.helper.Error):
                self.helper.main(args)
            environment.assert_not_called()

    def test_partial_history_failure_does_not_hide_current_or_dnd(self):
        with mock.patch.object(self.helper, 'mako', side_effect=[
                '[{"summary":"Hello"}]', self.helper.Error('history unavailable'), 'default\ndo-not-disturb\n']):
            result = self.helper.snapshot({})
        self.assertEqual(result['active'][0]['summary'], 'Hello')
        self.assertIsNone(result['history'])
        self.assertTrue(result['dnd'])
        self.assertEqual(result['errors'], ['History: history unavailable'])

    def test_failed_action_still_refreshes_views(self):
        with mock.patch.object(self.helper, 'mako', side_effect=[
                self.helper.Error('no history entry'), '[]', '[]', 'default\n']):
            result = self.helper.snapshot({}, 'restore')
        self.assertEqual(result['active'], [])
        self.assertEqual(result['history'], [])
        self.assertFalse(result['dnd'])
        self.assertEqual(result['errors'], ['Action: no history entry'])

    def test_cancelled_snapshot_launches_no_new_requests(self):
        event = threading.Event(); event.set()
        with mock.patch.object(self.helper, 'mako') as request:
            result = self.helper.snapshot({}, cancel=event)
        request.assert_not_called()
        self.assertIsNone(result['active'])

    def test_content_is_not_logged_or_launched_and_gui_refresh_is_bounded(self):
        source = payload_read_text(LIBEXEC / 'labwc-notifications')
        for unsafe in ('set_markup(', 'set_uri(', 'shell=True', 'os.system(', 'webbrowser.'):
            self.assertNotIn(unsafe, source)
        for required in ('max_workers=1', 'self.cancel.set()', 'wait=True, cancel_futures=True',
                         'entries == self.page_cache[index]', 'entries[:MAX_VISIBLE]'):
            self.assertIn(required, source)


class NotificationCaptureTests(unittest.TestCase):
    def setUp(self):
        self.helper = load('labwc-notifications')
        self.original_popen = subprocess.Popen
        self.children = []

    def request(self, code, **kwargs):
        def spawn(argv, **options):
            self.assertEqual(argv, ['/usr/bin/makoctl', 'list', '-j'])
            self.assertNotIn('shell', options)
            child = self.original_popen([sys.executable, '-I', '-c', code], **options)
            self.children.append(child)
            return child
        with mock.patch.object(self.helper.subprocess, 'Popen', side_effect=spawn):
            return self.helper.mako(['list', '-j'], {}, **kwargs)

    def tearDown(self):
        for child in self.children:
            self.assertIsNotNone(child.poll(), 'a Mako child leaked')
            self.assertTrue(child.stdout.closed)
            self.assertTrue(child.stderr.closed)

    def test_stderr_does_not_corrupt_json(self):
        text = self.request('import sys; print("[]"); print("diagnostic", file=sys.stderr)')
        self.assertEqual(json.loads(text), [])

    def test_nonzero_error_does_not_disclose_payload_or_stderr(self):
        with self.assertRaises(self.helper.Error) as result:
            self.request('import sys; print("PRIVATE_BODY"); print("PRIVATE_ERROR",file=sys.stderr); sys.exit(7)')
        self.assertIn('exit 7', str(result.exception))
        self.assertNotIn('PRIVATE', str(result.exception))

    def test_stdout_and_stderr_are_jointly_bounded(self):
        with mock.patch.object(self.helper, 'MAX_OUTPUT', 128):
            for descriptor in (1, 2):
                with self.subTest(fd=descriptor), self.assertRaises(self.helper.Error):
                    self.request(f'import os; os.write({descriptor}, b"x" * 1024)')

    def test_invalid_utf8_is_a_controlled_error(self):
        with self.assertRaises(self.helper.Error):
            self.request('import os; os.write(1,b"\\xff")')

    def test_timeout_kills_and_reaps_the_exact_child(self):
        with mock.patch.object(self.helper, 'REQUEST_TIMEOUT', 0.15), self.assertRaises(self.helper.Error):
            self.request('import time; time.sleep(10)')
        self.assertEqual(self.children[-1].returncode, -9)

    def test_closed_pipes_cannot_bypass_the_deadline(self):
        with mock.patch.object(self.helper, 'REQUEST_TIMEOUT', 0.15), self.assertRaises(self.helper.Error):
            self.request('import os,time; os.close(1); os.close(2); time.sleep(10)')
        self.assertEqual(self.children[-1].returncode, -9)

    def test_close_cancels_an_inflight_request_promptly(self):
        event = threading.Event()
        timer = threading.Timer(0.1, event.set)
        timer.start()
        try:
            start = time.monotonic()
            with self.assertRaises(self.helper.Error):
                self.request('import time; time.sleep(10)', cancel=event)
            self.assertLess(time.monotonic() - start, 1.5)
        finally:
            timer.join()

    def test_pre_cancel_and_unsafe_command_never_spawn(self):
        event = threading.Event(); event.set()
        with mock.patch.object(self.helper.subprocess, 'Popen') as child:
            with self.assertRaises(self.helper.Error):
                self.helper.mako(['list', '-j'], {}, cancel=event)
            with self.assertRaises(self.helper.Error):
                self.helper.mako(['menu', 'sh'], {})
        child.assert_not_called()


if __name__ == '__main__':
    unittest.main()
