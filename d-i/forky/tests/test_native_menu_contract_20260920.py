"""Native menu dispatch, hostile data, cancellation and installer wiring.

All backends are fixtures; no real power, audio, calendar, or user-manager
operation is run. Actual GTK Builder tests live in test_native_tomat_20260920.
"""
from __future__ import annotations

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
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from test_native_tomat_20260920 import FORKY, TARGET, SKEL, LIBEXEC, bars, load

CALENDAR = {
    'calendar_open': 'browse', 'calendar_agenda': 'agenda',
    'calendar_new_event': 'new-event', 'calendar_edit_event': 'edit-event',
    'calendar_tasks': 'tasks', 'calendar_all_tasks': 'all-tasks',
    'calendar_new_task': 'new-task', 'calendar_show_task': 'show-task',
    'calendar_edit_task': 'edit-task', 'calendar_done_task': 'done-task',
    'calendar_delete_task': 'delete-task', 'calendar_sync': 'sync-ui',
}
MODULES = (('custom/tomat', 'tomat', 'on-click-right'),
           ('pulseaudio', 'audio', 'on-click-right'),
           ('custom/notifications', 'notifications', 'on-click'),
           ('custom/power', 'power', 'on-click'),
           ('clock', 'calendar', 'on-click-right'))


class MenuContractTests(unittest.TestCase):
    def test_all_84_actions_are_nonblocking_and_session_owned(self):
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
                tree = ET.parse(SKEL / 'waybar' / (name + '-menu.xml'))
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
        self.assertEqual(count, 84)

    def test_calendar_mapping_and_legacy_primary_clicks(self):
        for bar in bars():
            entry = bar['clock']
            self.assertEqual(entry['menu-file'], '~/.config/waybar/calendar-menu.xml')
            self.assertEqual(set(entry['menu-actions']), set(CALENDAR))
            for key, action in CALENDAR.items():
                argv = shlex.split(entry['menu-actions'][key])
                self.assertEqual(argv[argv.index('--') + 1:], ['/usr/local/bin/labwc-calendar', action])
            self.assertIn('on-click', entry)
            self.assertTrue(entry['on-click-middle'].endswith(' -- labwc-calendar tasks'))
            self.assertNotIn('labwc-calendar menu', json.dumps(entry))

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
        source = (FORKY / 'scripts/desktop/components.sh').read_text()
        start = source.index('desktop_stage_waybar_native_menus() {')
        function = source[start:source.index('\n}\n', start) + 3]
        with tempfile.TemporaryDirectory() as work:
            script = ('desktop_stage_role_asset() { printf "%s\\t%s\\t%s\\n" "$1" "$2" "$3"; }\n'
                      'desktop_whisper_addon_selected() { return 1; }\n'
                      'run_in_target() { :; }\n' + function + '\ndesktop_stage_waybar_native_menus\n')
            result = subprocess.run(['/bin/sh', '-eu', '-c', script], text=True,
                                    capture_output=True, timeout=5, cwd=work, check=True)
        staged = [line.split('\t') for line in result.stdout.splitlines()]
        for _, name, _ in MODULES:
            path = f'etc/skel-desktop/.config/waybar/{name}-menu.xml'
            self.assertIn([path, '/' + path, '0644'], staged)
            self.assertTrue((TARGET / path).is_file())

    def test_optional_whisper_is_disabled_not_dangling_and_reversible(self):
        source = (FORKY / 'scripts/desktop/components.sh').read_text()
        code = source.split('run_in_target "configure optional native audio menu" /usr/bin/python3 -I -c \'\n', 1)[1].split("\n' \"$native_menu_whisper\"", 1)[0]
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / 'audio-menu.xml'
            path.write_bytes((SKEL / 'waybar/audio-menu.xml').read_bytes())
            original_ids = {obj.get('id') for obj in ET.parse(path).iter('object') if obj.get('id')}
            for enabled in ('0', '1', '0'):
                with mock.patch('pathlib.Path', return_value=path), mock.patch.object(sys, 'argv', ['fixture', enabled]):
                    exec(compile(code, 'native-audio-staging', 'exec'), {})
                tree = ET.parse(path)
                self.assertEqual({obj.get('id') for obj in tree.iter('object') if obj.get('id')}, original_ids)
                parent = next(obj for obj in tree.iter('object') if obj.get('class') == 'GtkMenuItem'
                              and obj.find('.//object[@id="whisper_record"]') is not None)
                self.assertEqual(parent.findtext('./property[@name="sensitive"]'), 'True' if enabled == '1' else 'False')
                self.assertEqual(parent.findtext('./property[@name="label"]'), 'Whisper' if enabled == '1' else 'Whisper (not installed)')

    def test_actual_gtk_honors_optional_whisper_sensitive_property(self):
        if not shutil.which('xvfb-run') or not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3 / Xvfb unavailable')
        result = subprocess.run(
            ['xvfb-run', '-a', '/usr/bin/python3', '-I', '-B',
             str(FORKY / 'tests/fixtures/native-menu-whisper-gtk.py'), str(FORKY)],
            env={**os.environ, 'GDK_BACKEND': 'x11', 'NO_AT_BRIDGE': '1'},
            text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('PASS: actual staged GtkMenu'), 3)

    def test_installer_checks_every_menu_and_required_gtk_dependency(self):
        source = (FORKY / 'scripts/desktop/verify.sh').read_text()
        function = source.split('desktop_verify_native_menus() {', 1)[1].split('\ndesktop_verify_target_staging()', 1)[0]
        for _, name, _ in MODULES:
            self.assertIn('"' + name + '"', function)
        for text in ('menus=5', 'unwired native menu leaf', '--no-block', 'optional Whisper menu/service availability differs'):
            self.assertIn(text, function)
        packages = (FORKY / 'classes/class-select/role/desktop.cfg').read_text().split()
        for package in ('python3-gi', 'gir1.2-gtk-3.0', 'mako-notifier', 'khal', 'todoman/trixie'):
            self.assertIn(package, packages)


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
        source = (LIBEXEC / 'labwc-notifications').read_text()
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


class CalendarActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'
        for name in ('khal/config', 'todoman/config.py', 'vdirsyncer/config'):
            path = self.root / '.config' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture\n')
        fixture = '''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
with open(os.environ['TEST_LOG'],'a') as stream:
 stream.write(json.dumps({'name':name,'args':sys.argv[1:]})+'\\n')
if name == 'todoman' and sys.argv[1:2] == ['list']:
 print('fixture task list')
 sys.exit(int(os.environ.get('LIST_STATUS','0')))
if name in {'khal','todoman'}:
 sys.exit(int(os.environ.get('BACKEND_STATUS','0')))
'''
        for name in ('khal', 'todoman', 'labwc-terminal', 'notify-send'):
            path = self.bin / name; path.write_text(fixture); path.chmod(0o755)
        self.env = {'HOME': str(self.root), 'PATH': str(self.bin) + ':/usr/bin:/bin',
                    'TEST_LOG': str(self.log), 'LC_ALL': 'C.UTF-8'}

    def run_action(self, action, input='', extras=(), **environment):
        self.log.unlink(missing_ok=True)
        result = subprocess.run(['/bin/sh', str(LIBEXEC / 'labwc-calendar'), action, *extras],
                                input=input, env={**self.env, **environment}, capture_output=True,
                                text=True, timeout=5)
        self.calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result

    def test_every_public_calendar_action_opens_a_terminal(self):
        for action in CALENDAR.values():
            with self.subTest(action=action):
                result = self.run_action(action)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.calls[0]['name'], 'labwc-terminal')
                self.assertEqual(self.calls[0]['args'][0], '-e')
        self.assertEqual(self.calls[0]['args'][-1], 'sync-terminal')

    def test_shell_metacharacters_and_leading_dash_are_event_data(self):
        for query in ('--delete', '$(touch /not-executed); "quotes"'):
            result = self.run_action('edit-event-terminal', query + '\n\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls, [{'name': 'khal', 'args': ['edit', '--show-past', '--', query]}])

    def test_task_id_is_one_positive_decimal_operand(self):
        for ident in ('--raw', '--yes', '0', '01', '-1', '1 2', '1;exit', '1' * 19):
            with self.subTest(ident=ident):
                result = self.run_action('edit-task-terminal', ident + '\n\n')
                self.assertEqual(result.returncode, 64)
                self.assertEqual(self.calls, [{'name': 'todoman', 'args': ['list', '--status', 'ANY']}])
        result = self.run_action('edit-task-terminal', '12\n\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls[-1], {'name': 'todoman', 'args': ['edit', '-i', '--', '12']})

    def test_empty_task_and_event_input_cancel_cleanly(self):
        for action in ('edit-task-terminal', 'edit-event-terminal'):
            result = self.run_action(action, '\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(any(call['args'][0] == 'edit' for call in self.calls))

    def test_completion_has_preview_and_default_no_confirmation(self):
        for answer in ('n', '', 'yes'):
            result = self.run_action('done-task-terminal', '12\n' + answer + '\n\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn({'name': 'todoman', 'args': ['show', '--', '12']}, self.calls)
            self.assertEqual(any(call['args'][0] == 'done' for call in self.calls), answer == 'yes')

    def test_delete_preserves_backend_confirmation(self):
        result = self.run_action('delete-task-terminal', '12\n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls[-1], {'name': 'todoman', 'args': ['delete', '--', '12']})
        self.assertNotIn('--yes', self.calls[-1]['args'])

    def test_list_error_stops_before_mutating_or_prompting_for_id(self):
        result = self.run_action('edit-task-terminal', '\n', LIST_STATUS='23')
        self.assertEqual(result.returncode, 23)
        self.assertNotIn('Task id', result.stdout)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('Press Enter to close', result.stdout)

    def test_backend_error_is_preserved_after_hold(self):
        result = self.run_action('edit-event-terminal', 'query\n\n', BACKEND_STATUS='31')
        self.assertEqual(result.returncode, 31)
        self.assertIn('Press Enter to close', result.stdout)
        self.assertIn('status 31', result.stderr)

    def test_all_tasks_includes_completed_and_new_forms_are_interactive(self):
        for action, command, args in (
                ('all-tasks-terminal', 'todoman', ['list', '--status', 'ANY']),
                ('new-task-terminal', 'todoman', ['new', '-i']),
                ('new-event-terminal', 'khal', ['new', '-i'])):
            result = self.run_action(action, '\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls, [{'name': command, 'args': args}])

    def test_extra_arguments_fail_before_launch(self):
        for action in CALENDAR.values():
            result = self.run_action(action, extras=('extra',))
            self.assertEqual(result.returncode, 64)
            self.assertEqual(self.calls, [])

    def test_calendar_cancellation_executables_are_confined_and_allowed(self):
        source = (TARGET / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
        profile = source.split('profile managed-labwc-calendar ', 1)[1].split('\nprofile ', 1)[0]
        self.assertIn('/{,usr/}bin/{kill,sleep} rix,', profile)
        self.assertIn('signal (send) set=(term, kill) peer=unconfined,', profile)
        self.assertIn('/usr/local/bin/labwc-terminal rPx -> managed-labwc-terminal,', profile)


if __name__ == '__main__':
    unittest.main()
