"""Non-destructive regressions for the September 13 keyboard/power/audit fixes.

All power-manager calls are mocked. Real subprocess tests use disposable helpers
only. Audit checks cover source-rule intent, not kernel AppArmor enforcement.
"""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
FIXTURE = Path(__file__).parent / 'fixtures/installed-apparmor-20260913-power-keyboard.json'


def module(name):
    path = TARGET / 'usr/local/libexec' / name
    result = types.ModuleType(name.replace('-', '_'))
    result.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), result.__dict__)
    return result


def block(filename, name):
    text = (TARGET / 'etc/apparmor.d' / filename).read_text()
    return text.split('profile ' + name + ' ', 1)[1].split('\nprofile ', 1)[0]


class KeyboardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.log = self.base / 'calls'
        self.state = self.base / 'state/labwc/keyboard-layout'
        self.env = dict(os.environ, HOME=str(self.base), XDG_CONFIG_HOME=str(self.base / 'config'),
                        XDG_STATE_HOME=str(self.base / 'state'), XDG_RUNTIME_DIR='/run/user/1000',
                        WAYLAND_DISPLAY='wayland-1', LABWC_SESSION_OWNER='desktop',
                        CALL_LOG=str(self.log), STATE_FILE=str(self.state),
                        RECONFIGURE_DELAY='0', FAIL_RECONFIGURE='',
                        LABWC_KEYBOARD_LAYOUTS='us se', LABWC_KEYBOARD_DEFAULT_LAYOUT='us',
                        PATH=str(self.base) + ':/usr/bin:/bin')
        self.script('labwc', '''#!/bin/sh
printf 'reconfigure-start\\n' >> "$CALL_LOG"
[ -z "$FAIL_RECONFIGURE" ] || exit 1
sleep "$RECONFIGURE_DELAY"
printf 'reconfigure-complete\\n' >> "$CALL_LOG"
''')
        self.script('systemctl', '''#!/bin/sh
case "$*" in
  *is-active*) exit 0 ;;
  *kill*) printf 'refresh:%s:%s\\n' "$*" "$(cat "$STATE_FILE")" >> "$CALL_LOG" ;;
  *) exit 2 ;;
esac
''')
        self.script('labwc-terminal', '#!/bin/sh\nprintf "UNEXPECTED-TERMINAL\\n" >> "$CALL_LOG"\nexit 99\n')
        action = (TARGET / 'usr/local/bin/labwc-system-action').read_text()
        helper = self.script('labwc-system-action', action)
        keyboard = (TARGET / 'usr/local/bin/labwc-keyboard-layout').read_text()
        keyboard = keyboard.replace('/usr/local/bin/labwc-system-action', str(helper))
        keyboard = keyboard.replace('/etc/default/labwc-desktop', str(self.base / 'no-defaults'))
        self.keyboard = self.script('keyboard', keyboard)

    def script(self, name, text):
        path = self.base / name
        path.write_text(text)
        path.chmod(0o755)
        return path

    def invoke(self, *args):
        return subprocess.run([str(self.keyboard), *args], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_repeated_clicks_alternate_and_refresh_only_after_reconfigure(self):
        for expected in ('se', 'us', 'se', 'us'):
            result = self.invoke('waybar-toggle')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['class'], expected)
            self.assertEqual(self.state.read_text().strip(), expected)
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 20)
        for offset in range(0, len(lines), 5):
            self.assertEqual(lines[offset:offset+2], ['reconfigure-start', 'reconfigure-complete'])
            for index, sig in enumerate(('RTMIN+7', 'RTMIN+8', 'RTMIN+9')):
                self.assertIn('--signal=' + sig, lines[offset+2+index])
        self.assertNotIn('UNEXPECTED-TERMINAL', self.log.read_text())

    def test_overlapping_clicks_are_queued_not_discarded(self):
        self.env['RECONFIGURE_DELAY'] = '0.08'
        children = [subprocess.Popen([str(self.keyboard), 'waybar-toggle'], env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for _ in range(6)]
        try:
            statuses = []
            for child in children:
                output, error = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, error)
                statuses.append(json.loads(output)['class'])
            self.assertEqual(statuses.count('us'), 3)
            self.assertEqual(statuses.count('se'), 3)
            self.assertEqual(self.state.read_text().strip(), 'us')
            self.assertEqual(self.log.read_text().count('refresh:'), 18)
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait()

    def test_reconfigure_failure_rolls_back_without_success_refresh(self):
        self.env['FAIL_RECONFIGURE'] = '1'
        result = self.invoke('waybar-toggle')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_text().strip(), 'us')
        self.assertNotIn('refresh:', self.log.read_text())

    def test_set_and_cli_toggle_share_the_completion_path(self):
        self.assertEqual(json.loads(self.invoke('set', 'sv').stdout)['class'], 'se')
        self.assertEqual(json.loads(self.invoke('toggle').stdout)['class'], 'us')
        self.assertNotEqual(self.invoke('set', 'de').returncode, 0)
        self.assertEqual(self.state.read_text().strip(), 'us')
        self.assertEqual(self.log.read_text().count('refresh:'), 6)

    def test_offline_set_does_not_try_to_refresh_a_desktop(self):
        self.env.pop('WAYLAND_DISPLAY')
        result = self.invoke('set', 'se')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())

    def test_both_waybar_definitions_use_completion_driven_refresh(self):
        # Exercise the real renderer, including workspace-dependent module
        # selection, without weakening the keyboard-refresh assertions.
        rendered = self.base / 'rendered'
        rendered.mkdir()
        fixture = Path(__file__).parent / 'fixtures/workspaces/render.sh'
        result = subprocess.run(['/bin/sh', str(fixture), str(TARGET.parents[3]), str(rendered)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        configurations = json.loads((rendered / 'etc/skel-desktop/.config/waybar/config').read_text())
        self.assertEqual(len(configurations), 2)
        for configuration in configurations:
            keyboard = configuration['custom/keyboard']
            self.assertFalse(keyboard['exec-on-event'])
            self.assertEqual(keyboard['signal'], 7)
            self.assertIn('labwc-keyboard-layout waybar-toggle', keyboard['on-click'])
        text = (TARGET / 'usr/local/bin/labwc-keyboard-layout').read_text()
        self.assertIn('sleep 0.03', text)
        self.assertIn('flock -w 5 9', text)
        self.assertNotIn('flock -n', text)

    def test_refresh_rejects_extra_arguments_without_terminal(self):
        result = subprocess.run([str(self.base / 'labwc-system-action'),
                                 'refresh-waybar-custom-module', 'unexpected'],
                                env=self.env, text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())


class PanelTests(unittest.TestCase):
    def test_refresh_signals_are_only_enabled_for_waybar(self):
        panel = module('labwc-panel-run')
        with mock.patch.object(panel.os, 'getuid', return_value=1000), \
             mock.patch.object(panel, 'supervise', return_value=0) as supervise:
            panel.main(['waybar'])
            self.assertEqual(supervise.call_args.kwargs['signals'], panel.SIGNALS + panel.WAYBAR_SIGNALS)
            panel.main(['crystal-dock'])
            self.assertEqual(supervise.call_args.kwargs['signals'], panel.SIGNALS)

    def test_supervisor_actually_forwards_all_three_refresh_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory) / 'child.py'
            child.write_text('''import signal, time
for offset in (7, 8, 9):
    signal.signal(signal.SIGRTMIN + offset, lambda number, frame: print(number, flush=True))
print('READY', flush=True)
while True: time.sleep(0.02)
''')
            path = TARGET / 'usr/local/libexec/labwc-panel-run'
            code = ("import runpy,sys; m=runpy.run_path(sys.argv[1]); "
                    "sys.exit(m['supervise']([sys.executable, '-u', sys.argv[2]], set(), "
                    "signals=m['SIGNALS']+m['WAYBAR_SIGNALS']))")
            process = subprocess.Popen([sys.executable, '-B', '-u', '-c', code, str(path), str(child)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            def line():
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(timeout=5), 'supervisor did not produce output')
                return process.stdout.readline().strip()
            try:
                self.assertEqual(line(), 'READY')
                for offset in (7, 8, 9):
                    process.send_signal(signal.SIGRTMIN + offset)
                    self.assertEqual(line(), str(signal.SIGRTMIN + offset))
                    self.assertIsNone(process.poll())
            finally:
                process.terminate()
                process.communicate(timeout=8)


class SessionPreparationTests(unittest.TestCase):
    def setUp(self):
        self.session = module('labwc-session-state')
        self.confirm = mock.patch.object(self.session, 'confirm_close'); self.confirm.start(); self.addCleanup(self.confirm.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / 'state'
        self.runtime = Path(tmp.name) / 'runtime'
        self.state.mkdir(mode=0o700)
        self.runtime.mkdir(mode=0o700)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(self.session, 'ctl', return_value=''))
        self.services = self.stack.enter_context(mock.patch.object(self.session, 'services', return_value={}))
        self.windows = self.stack.enter_context(mock.patch.object(self.session, 'windows', return_value=''))
        self.run = self.stack.enter_context(mock.patch.object(self.session, 'run', return_value=''))
        self.notify = self.stack.enter_context(mock.patch.object(self.session, 'notify'))
        self.sleep = self.stack.enter_context(mock.patch.object(self.session.time, 'sleep'))
        self.clipboard = self.stack.enter_context(mock.patch.object(self.session, 'clear_clipboard'))

    def test_empty_desktop_has_no_close_request_or_wait(self):
        self.session.prepare(self.state, self.runtime)
        self.sleep.assert_called_once_with(0.3)
        self.run.assert_not_called()
        self.notify.assert_not_called()
        self.services.assert_called_once()
        self.assertTrue((self.state / 'resume.json').exists())

    def test_windowless_background_and_nested_services_do_not_block(self):
        self.services.return_value = {'tray.service': {'LABWC_SESSION_APP': '1'},
                                     'nested.service': {'LABWC_SESSION_APP': '1', 'LABWC_SESSION_NESTED': '1'}}
        self.session.prepare(self.state, self.runtime)
        self.sleep.assert_called_once_with(0.3)
        self.assertTrue((self.runtime / 'labwc-session-closing').exists())

    def test_save_dialog_gets_time_but_only_one_close_request(self):
        self.windows.side_effect = ['editor: Document', 'editor: Save changes?', '', '']
        self.session.prepare(self.state, self.runtime)
        self.run.assert_called_once_with(['/usr/bin/wlrctl', 'toplevel', 'close'], timeout=5, accepted=(0, 1))
        self.assertEqual(self.sleep.call_args_list, [mock.call(0.2), mock.call(0.3)])
        self.services.assert_called_once()

    def test_unresolved_save_window_cancels_before_teardown(self):
        self.windows.return_value = 'editor: Save changes?'
        with self.assertRaises(self.session.Error):
            self.session.prepare(self.state, self.runtime, timeout=0)
        self.assertFalse((self.runtime / 'labwc-session-closing').exists())
        self.assertFalse((self.state / 'resume.json').exists())
        self.clipboard.assert_not_called()

    def test_failed_window_probe_is_not_treated_as_empty(self):
        self.windows.side_effect = self.session.Error('Wayland unavailable')
        with self.assertRaises(self.session.Error):
            self.session.prepare(self.state, self.runtime)
        self.assertFalse((self.runtime / 'labwc-session-closing').exists())

    def test_clipboard_error_cannot_strand_closed_desktop(self):
        self.clipboard.side_effect = self.session.Error('no primary-selection protocol')
        with contextlib.redirect_stderr(io.StringIO()):
            self.session.prepare(self.state, self.runtime)
        self.assertTrue((self.state / 'resume.json').exists())


class PowerWorkerTests(unittest.TestCase):
    def setUp(self):
        self.power = module('labwc-admin-action-worker')
        self.worker = self.power.Worker(1000, 'testuser', 'reboot')
        self.worker.package_locks = mock.Mock()  # acquired gate fixture; real locks tested separately

    def execution(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        events = []
        stack.enter_context(mock.patch.object(self.power, 'PackageLocks'))
        stack.enter_context(mock.patch.object(self.power, 'check_shutdown_inhibitors',
            side_effect=lambda: events.append(('inhibitors', ()))))
        stack.enter_context(mock.patch.object(self.power, 'hold_reservation', side_effect=lambda: events.append(('hold', ()))))
        stack.enter_context(mock.patch.object(self.worker, 'session_identity',
            side_effect=lambda: (self.worker.userctl('identity'), 'a' * 32)[1]))
        for name in ('userctl', 'protect_other_sessions', 'helper', 'terminate_user', 'final_power_action', 'lock', 'stop_optional_guests'):
            stack.enter_context(mock.patch.object(self.worker, name,
                side_effect=lambda *args, _name=name, **kwargs: events.append((_name, args))))
        def quiesce():
            events.append(('quiesce_desktop', ()))
            self.worker.committed = True
            self.worker.quiesced = True
        stack.enter_context(mock.patch.object(self.worker, 'quiesce_desktop', side_effect=quiesce))
        stack.enter_context(mock.patch.object(self.power, 'ready', side_effect=lambda: events.append(('ready', ()))))
        stack.enter_context(mock.patch.object(self.power, 'run', side_effect=lambda *args, **kwargs: events.append(('run', args))))
        return events

    def test_readiness_and_prepare_precede_orderly_power_transaction(self):
        events = self.execution()
        self.worker.execute()
        self.assertEqual([e[0] for e in events], ['userctl', 'protect_other_sessions', 'ready', 'userctl', 'protect_other_sessions',
                         'helper', 'protect_other_sessions', 'inhibitors', 'quiesce_desktop', 'stop_optional_guests', 'final_power_action', 'hold'])
        self.assertEqual(events[5][1], ('prepare',))
        self.assertTrue(self.worker.committed)

    def test_prepare_failure_never_starts_teardown(self):
        events = self.execution()
        self.worker.helper.side_effect = self.power.Error('unsaved document')
        with self.assertRaises(self.power.Error):
            self.worker.execute()
        self.assertFalse(self.worker.committed)
        self.worker.terminate_user.assert_not_called()
        self.worker.final_power_action.assert_not_called()

    def test_other_user_arriving_during_save_cancels_before_commit(self):
        self.execution()
        self.worker.protect_other_sessions.side_effect = [None, None, self.power.Error('other account')]
        with self.assertRaises(self.power.Error):
            self.worker.execute()
        self.assertFalse(self.worker.committed)
        self.worker.terminate_user.assert_not_called()

    def test_preflight_failure_is_not_acknowledged(self):
        events = self.execution()
        self.worker.userctl.side_effect = self.power.Error('no desktop')
        with self.assertRaises(self.power.Error):
            self.worker.execute()
        self.assertNotIn('ready', [e[0] for e in events])
        self.worker.helper.assert_not_called()

    def test_power_submission_failure_keeps_teardown_committed(self):
        self.execution()
        self.worker.final_power_action.side_effect = self.power.Error('bus unavailable')
        with self.assertRaises(self.power.Error):
            self.worker.execute()
        self.assertTrue(self.worker.committed)
        self.worker.terminate_user.assert_not_called()
        self.worker.final_power_action.assert_called_once()

    def test_logout_never_calls_machine_power(self):
        self.worker.action = 'logout'
        self.execution()
        self.worker.execute()
        self.worker.terminate_user.assert_called_once()
        self.worker.final_power_action.assert_not_called()

    def test_suspend_locks_without_closing_apps(self):
        self.worker.action = 'suspend'
        events = self.execution()
        self.worker.execute()
        self.worker.lock.assert_called_once()
        self.worker.helper.assert_called_once_with('locked')
        self.worker.terminate_user.assert_not_called()
        self.assertFalse(self.worker.committed)
        self.assertIn(['/usr/bin/systemctl', '--check-inhibitors=yes', '--no-ask-password', 'suspend'], events[-1][1])

    def test_cleanup_failure_does_not_skip_term_and_kill(self):
        self.worker.action = 'logout'
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            if argv[0].endswith('loginctl'):
                raise self.power.Error('logind unavailable')
            return ''
        with mock.patch.object(self.worker, 'userctl', side_effect=self.power.Error('user bus closed')), \
             mock.patch.object(self.power, 'run', side_effect=run), \
             mock.patch.object(self.worker, 'wait_for_exit', side_effect=[False, False, True]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.worker.terminate_user()
        self.assertTrue(any('--signal=TERM' in a for a in calls))
        self.assertTrue(any('--signal=KILL' in a for a in calls))
        self.assertTrue(any('user@1000.service' in a and '--no-block' in a for a in calls))
        for argv in calls:
            self.assertNotIn('/usr/bin/pkill', argv)
            self.assertNotIn('/usr/bin/pgrep', argv)

    def test_already_empty_user_slice_needs_no_kill_wait(self):
        self.worker.action = 'logout'
        with mock.patch.object(self.worker, 'userctl'), mock.patch.object(self.power, 'run', return_value='') as run, \
             mock.patch.object(self.worker, 'wait_for_exit', return_value=True) as wait:
            self.worker.terminate_user()
        self.assertFalse(any('kill' in c.args[0] for c in run.call_args_list))
        wait.assert_called_once_with(1)

    def test_forced_handoff_submits_once_without_any_target_barrier(self):
        for action in ('reboot', 'poweroff'):
            with self.subTest(action=action):
                self.worker = self.power.Worker(1000, 'testuser', action)
                self.worker.package_locks = mock.Mock()  # acquired gate fixture; real locks tested separately
                self.worker.quiesced = True
                with mock.patch.object(self.worker, 'stop_shutdown_runtime') as cleanup, \
                     mock.patch.object(self.power, 'run', return_value='') as run, \
                     contextlib.redirect_stderr(io.StringIO()) as output:
                    self.worker.final_power_action()
                cleanup.assert_called_once_with()
                run.assert_called_once_with(
                    ['/usr/bin/systemctl', '--force', '--no-ask-password', action], timeout=20)
                self.assertIn('systemctl --force ' + action, output.getvalue())
                self.assertTrue(self.worker.committed)

    def test_uncertain_final_submission_is_not_retried_or_cancelled(self):
        self.worker.quiesced = True
        with mock.patch.object(self.worker, 'stop_shutdown_runtime'), \
             mock.patch.object(self.power, 'run', side_effect=self.power.Error('bus failed')) as run, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(self.power.Error, 'handoff status uncertain'):
                self.worker.final_power_action()
        self.assertEqual(run.call_count, 1)
        self.assertTrue(self.worker.committed)
        self.assertTrue(self.worker.handoff_attempted)

    def test_account_teardown_rejects_machine_power_actions(self):
        with mock.patch.object(self.power, 'run') as run, mock.patch.object(self.worker, 'userctl') as userctl:
            for action in ('reboot', 'poweroff', 'suspend'):
                self.worker.action = action
                with self.subTest(action=action), self.assertRaisesRegex(self.power.Error, 'only valid for logout'):
                    self.worker.terminate_user()
            run.assert_not_called()
            userctl.assert_not_called()

    def test_machine_power_rejects_other_actions_before_any_command(self):
        with mock.patch.object(self.power, 'run') as run:
            for action in ('logout', 'suspend', 'invalid'):
                self.worker.action = action
                with self.subTest(action=action), self.assertRaisesRegex(self.power.Error, 'invalid machine shutdown action'):
                    self.worker.final_power_action()
            run.assert_not_called()

    def test_transport_timeout_reaps_descendants_holding_pipes(self):
        # Only disposable processes: never systemctl/loginctl/reboot on this host.
        start = time.monotonic()
        with self.assertRaisesRegex(self.power.Error, 'timed out'):
            self.power.run([sys.executable, '-c',
                'import os,time; os.fork(); time.sleep(30)'], timeout=0.2)
        self.assertLess(time.monotonic() - start, 4)

    def test_readiness_requires_system_manager_socket(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(self.power.Error):
                self.power.ready()

    def test_readiness_datagram_is_sent_by_worker(self):
        import socket
        with tempfile.TemporaryDirectory() as directory, socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            path = str(Path(directory) / 'notify')
            receiver.bind(path)
            receiver.settimeout(2)
            with mock.patch.dict(os.environ, NOTIFY_SOCKET=path):
                self.power.ready()
            self.assertIn(b'READY=1', receiver.recv(256))

    def test_template_acknowledges_before_frontend_returns(self):
        unit = (TARGET / 'etc/systemd/system/labwc-admin-action@.service').read_text()
        self.assertIn('Type=notify\nNotifyAccess=main', unit)
        self.assertIn('RuntimeMaxSec=infinity', unit)
        self.assertIn('NoNewPrivileges=yes', unit)
        root = (TARGET / 'usr/local/libexec/labwc-admin-action-root').read_text()
        self.assertIn('exec /usr/bin/systemctl start "$worker_unit"', root)
        self.assertNotIn('exec /usr/bin/systemctl --no-block', root)
        menu = (TARGET / 'usr/local/bin/labwc-power-menu').read_text()
        settings = (TARGET / 'usr/local/bin/labwc-power-settings').read_text()
        for action in ('suspend', 'reboot', 'poweroff', 'logout'):
            self.assertIn('exec /usr/local/bin/labwc-power-settings ' + action, menu)
        self.assertIn('suspend|reboot|poweroff|shutdown) exec /usr/local/bin/labwc-admin-action "$1"', settings)
        logout = (TARGET / 'usr/local/libexec/labwc-logout-root').read_text()
        self.assertIn('exec /usr/local/libexec/labwc-admin-action-root logout', logout)


def expand_braces(pattern):
    match = re.search(r'\{([^{}]*)\}', pattern)
    if not match:
        return [pattern]
    return [expanded for choice in match[1].split(',')
            for expanded in expand_braces(pattern[:match.start()] + choice + pattern[match.end():])]


def source_file_rules(text):
    # Deliberately limited source matcher for these logged file operations. Not
    # an AppArmor compiler: ignores non-file rules and does not model mediation.
    for line in text.splitlines():
        match = re.match(r'\s*(?:owner\s+)?(\S+)\s+([rwmalkixPUCpuc]+),', line)
        if not match:
            continue
        pattern, modes = match.groups()
        pattern = pattern.replace('@{PROC}', '/proc').replace('@{sys}', '/sys').replace('@{HOME}', '/home/*')
        for name in expand_braces(pattern):
            expression = ''
            while name:
                if name.startswith('**'):
                    expression += '.*'; name = name[2:]
                elif name.startswith('*'):
                    expression += '[^/]*'; name = name[1:]
                elif name.startswith('['):
                    end = name.index(']') + 1
                    expression += name[:end]; name = name[end:]
                else:
                    expression += re.escape(name[0]); name = name[1:]
            yield re.compile(expression + r'\Z'), set(modes)


class AuditPolicyTests(unittest.TestCase):
    def test_every_supplied_complain_event_has_a_scoped_source_fix(self):
        fixture = json.loads(FIXTURE.read_text())
        firstboot = block('managed-system-wrappers', 'managed-firstboot')
        desktop = (TARGET / 'etc/apparmor.d/abstractions/managed-wrapper-desktop').read_text()
        policies = {'managed-firstboot': firstboot,
                    'managed-desktop-launcher': block('managed-desktop-utilities', 'managed-desktop-launcher'),
                    'managed-session-controls': block('managed-labwc-session', 'managed-session-controls'),
                    'managed-waybar': block('managed-labwc-session', 'managed-waybar'),
                    'managed-labwc-bluetooth': block('managed-desktop-wrappers', 'managed-labwc-bluetooth') + desktop,
                    'managed-labwc-capture': block('managed-desktop-wrappers', 'managed-labwc-capture') + desktop}
        self.assertEqual(fixture['events'], 329)
        self.assertEqual(sum(r['count'] for r in fixture['records']), fixture['events'])
        for record in fixture['records']:
            with self.subTest(record=record):
                profile = record['profile'].split('//null-', 1)[0]
                policy = policies[profile]
                if record['operation'] == 'ptrace':
                    self.assertIn('ptrace (read) peer=' + record['peer'] + ',', policy)
                    self.assertIn('ptrace (readby) peer=managed-session-controls,',
                                  block('managed-labwc-session', 'managed-labwc-compositor'))
                    continue
                requested = set(record['mask'].replace('c', 'w').replace('a', 'w'))
                granted = set()
                for pattern, modes in source_file_rules(policy):
                    if pattern.fullmatch(record['name']):
                        granted.update(modes)
                self.assertTrue(requested <= granted, (record, granted))
        self.assertIn('/usr/bin/printf rix,', firstboot)
        self.assertIn('/usr/local/libexec/managed-nvidia-char-links rix,', firstboot)
        self.assertNotIn('profile managed-firstboot//null-', firstboot)

    def test_keyboard_refresh_has_confined_exec_and_user_bus_permissions(self):
        keyboard = block('managed-desktop-wrappers', 'managed-labwc-keyboard-layout')
        self.assertIn('/usr/local/bin/labwc-system-action rPx -> managed-labwc-system-action,', keyboard)
        action = block('managed-desktop-wrappers', 'managed-labwc-system-action')
        self.assertIn('/usr/bin/systemctl rix,', action)
        self.assertIn('owner /run/user/[0-9]*/{bus,systemd/private} rw,', action)
        self.assertIn('dbus (send) bus=session peer=(name=org.freedesktop.systemd1),', action)
        self.assertIn('/{run,var}/log/journal/** r,', action)
        self.assertIn('/sys/fs/cgroup/** r,', action)

    def test_signal_permissions_cover_both_sides_and_kernel_rt_base(self):
        self.assertEqual(int(signal.SIGRTMIN), 34, 'this fixture targets Debian glibc')
        panel = block('managed-labwc-session', 'managed-labwc-panel-run')
        waybar = block('managed-labwc-session', 'managed-waybar')
        names = ', '.join('rtmin+' + str(int(signal.SIGRTMIN) + offset - 32) for offset in (7, 8, 9))
        self.assertIn(f'signal (receive) set=({names}) peer=unconfined,', panel)
        self.assertIn(f'signal (send) set=({names}) peer=managed-waybar,', panel)
        self.assertIn(f'signal (receive) set=({names}) peer=managed-labwc-panel-run,', waybar)

    def test_power_controller_does_not_need_cross_domain_ptrace_or_kill(self):
        worker = block('managed-desktop-wrappers', 'managed-labwc-admin-action-worker')
        self.assertNotIn('ptrace (read)', worker)
        self.assertIn('capability kill,', worker)
        self.assertIn('set=(kill chld) peer=managed-labwc-admin-action-worker', worker)
        self.assertNotIn('signal (send),', worker)
        self.assertIn('/run/systemd/notify w,', worker)
        self.assertIn('signal (send, receive) set=(kill chld) peer=managed-labwc-admin-action-worker,', worker)


if __name__ == '__main__':
    unittest.main()
