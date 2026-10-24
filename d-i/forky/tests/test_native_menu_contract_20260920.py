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
           ('clock', 'calendar', 'on-click'))


class MenuContractTests(unittest.TestCase):
    def test_all_82_actions_are_nonblocking_and_session_owned(self):
        options = {'--user', '--collect', '--no-block', '--service-type=exec',
                   '--expand-environment=no', '--slice=app.slice',
                   '--property=Requisite=labwc-session.target',
                   '--property=After=labwc-session.target',
                   '--property=PartOf=labwc-session.target',
                   '--property=ExitType=cgroup', '--property=KillMode=control-group',
                   '--property=TimeoutStartSec=10s', '--property=TimeoutStopSec=20s'}
        count = 0
        for bar in bars():
            for module, name, event in MODULES:
                entry = bar[module]
                self.assertEqual(entry['menu'], event)
                self.assertNotIn(event, entry)
                self.assertNotIn(event + '-release', entry)
                self.assertNotIn(event, entry.get('actions', {}))
                tree = ET.parse(payload_source_path(SKEL / 'waybar' / (name + '-menu.xml')))
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
                    self.assertEqual(argv[0], '/usr/bin/systemd-run')
                    boundary = argv.index('--')
                    self.assertTrue(options <= set(argv[1:boundary]))
                    self.assertNotIn('--wait', argv)
                    self.assertNotIn('--pipe', argv)
                    self.assertNotIn('--scope', argv)
                    self.assertGreater(len(argv[boundary + 1:]), 0)
                    count += 1
        self.assertEqual(count, 82)

    def test_calendar_mapping_and_secondary_clicks(self):
        for bar in bars():
            entry = bar['clock']
            self.assertEqual(entry['menu-file'], '~/.config/waybar/calendar-menu.xml')
            self.assertEqual(set(entry['menu-actions']), set(CALENDAR))
            for key, action in CALENDAR.items():
                argv = shlex.split(entry['menu-actions'][key])
                self.assertEqual(argv[argv.index('--') + 1:], action)
                if action[0] == '/usr/local/libexec/labwc-calendar-actions':
                    self.assertIn('--property=SuccessExitStatus=2', argv[:argv.index('--')])
                else:
                    self.assertNotIn('--property=SuccessExitStatus=2', argv[:argv.index('--')])
            self.assertEqual(entry['on-click-right'], '/usr/bin/systemctl --user --no-ask-password --no-block start labwc-waycal-toggle.service')
            self.assertNotIn('on-click-right-release', entry)
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
            self.assertTrue(bar['custom/tomat']['on-click-right'].endswith(' -- /usr/local/libexec/labwc-tomat toggle'))
            self.assertTrue(bar['pulseaudio']['on-click-right'].endswith(' -- pavucontrol'))

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
            script = ('desktop_render_waybar_asset() { printf "etc/skel-desktop/.config/waybar/%s\\t/etc/skel-desktop/.config/waybar/%s\\t0644\\n" "$1" "$1"; }\n'
                      'desktop_stage_role_asset() { printf "%s\\t%s\\t%s\\n" "$1" "$2" "$3"; }\n'
                      'desktop_whisper_addon_selected() { return 1; }\n'
                      'run_in_target() { :; }\n' + function + '\ndesktop_stage_waybar_native_menus\n')
            result = subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', script]), text=True,
                                    capture_output=True, timeout=5, cwd=work, check=True)
        staged = [line.split('\t') for line in result.stdout.splitlines()]
        for _, name, _ in MODULES:
            path = f'etc/skel-desktop/.config/waybar/{name}-menu.xml'
            self.assertIn([path, '/' + path, '0644'], staged)
            self.assertTrue(payload_source_is_file(TARGET / path))

    def test_optional_whisper_is_disabled_not_dangling_and_reversible(self):
        source = payload_read_text(FORKY / 'scripts/desktop/components.sh')
        code = source.split('run_in_target "configure optional native audio menu" /usr/bin/python3 -I -c \'\n', 1)[1].split("\n' \"$native_menu_whisper\"", 1)[0]
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / 'audio-menu.xml'
            path.write_bytes(payload_read_bytes(SKEL / 'waybar/audio-menu.xml'))
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
        for text in ('menus=5', 'unwired native menu leaf', '--no-block', 'optional Whisper menu/service availability differs'):
            self.assertIn(text, function)
        self.assertIn('"format-alt" not in entry and "format-alt-click" not in entry', function)
        packages = payload_read_text(FORKY / 'classes/class-select/role/desktop.cfg').split()
        for package in ('python3-gi', 'gir1.2-gtk-3.0', 'mako-notifier', 'libgtk4-layer-shell0'):
            self.assertIn(package, packages)


class WaycalToggleTests(unittest.TestCase):
    def setUp(self):
        self.helper = load('labwc-waycal-toggle')
        self.uid = mock.patch.object(self.helper.os, 'getuid', return_value=1000)
        self.uid.start()
        self.addCleanup(self.uid.stop)

    def test_popup_starts_when_closed_and_stops_when_open(self):
        for state, action in (('inactive', 'start'), ('failed', 'start'),
                              ('active', 'stop'), ('activating', 'stop'),
                              ('reloading', 'stop'), ('deactivating', 'stop')):
            with self.subTest(state=state), mock.patch.object(self.helper.subprocess, 'run', side_effect=[
                    SimpleNamespace(returncode=0, stdout=state + '\n'),
                    SimpleNamespace(returncode=0)]) as command:
                self.assertEqual(self.helper.main([]), 0)
                self.assertEqual(command.call_count, 2)
                self.assertEqual(command.call_args_list[0].args[0], self.helper.SYSTEMCTL +
                                 ['show', '--property=ActiveState', '--value', 'labwc-waycal.service'])
                self.assertEqual(command.call_args_list[1].args[0], self.helper.SYSTEMCTL +
                                 [action, 'labwc-waycal.service'])
                self.assertEqual(command.call_args_list[1].kwargs['timeout'], 8)

    def test_missing_state_and_failed_state_read_never_mutate(self):
        for output, status in (('', 0), ('unknown\n', 0), ('inactive\n', 1)):
            with mock.patch.object(self.helper.subprocess, 'run',
                                   return_value=SimpleNamespace(returncode=status, stdout=output)) as command:
                self.assertEqual(self.helper.main([]), 1)
                self.assertEqual(command.call_count, 1)

    def test_uncertain_mutation_is_not_retried(self):
        with mock.patch.object(self.helper.subprocess, 'run', side_effect=[
                SimpleNamespace(returncode=0, stdout='inactive\n'),
                subprocess.TimeoutExpired(['fixture-systemctl'], 8)]) as command:
            self.assertEqual(self.helper.main([]), 1)
            self.assertEqual(command.call_count, 2)

    def test_root_and_extra_arguments_do_not_contact_manager(self):
        with mock.patch.object(self.helper.subprocess, 'run') as command:
            self.assertEqual(self.helper.main(['unexpected']), 2)
            with mock.patch.object(self.helper.os, 'getuid', return_value=0):
                self.assertEqual(self.helper.main([]), 2)
            command.assert_not_called()

    def test_styles_and_serialized_unit_are_staged_without_login_activation(self):
        source = payload_read_text(FORKY / 'scripts/desktop/components.sh')
        self.assertIn('labwc-calendar-credentials labwc-waycal labwc-waycal-toggle', source)
        self.assertIn('etc/skel-desktop/.config/waycal/style.css', source)
        self.assertIn('.config/waycal', source)
        unit = payload_read_text(SKEL / 'systemd/user/labwc-waycal-toggle.service')
        self.assertIn('Type=oneshot', unit)
        self.assertIn('StartLimitIntervalSec=0', unit)
        self.assertIn('PartOf=labwc-session.target', unit)
        self.assertNotIn('[Install]', unit)
        style = payload_read_text(SKEL / 'waycal/style.css')
        self.assertIn('rgba(30, 23, 46, 0.94)', style)
        self.assertIn('window.waycal .waycal-root.rounded', style)
        menu = ET.fromstring(payload_read_text(SKEL / 'waybar/calendar-menu.xml'))
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
