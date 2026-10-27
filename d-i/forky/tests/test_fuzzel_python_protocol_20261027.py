"""Unexecuted Python Fuzzel, Wi-Fi and Wayscriber regression fixtures.

Selected Python functions use local mocks. Shell orchestration uses only private
stub helpers and an unconnected fixture socket, with an explicit environment.
No host manager, desktop or installed management helper is used. Permanent
repository policy keeps this file unexecuted.
"""
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import ast
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
FUZZEL = TARGET / 'usr/local/bin/labwc-fuzzel.tmpl'
WIFI = TARGET / 'usr/local/libexec/network-wifi-configure'
WAYSCRIBER = TARGET / 'usr/local/bin/labwc-wayscriber-toggle'


def selected_functions(path, names, namespace):
    tree = ast.parse(path.read_bytes(), filename=str(path))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != set(names):
        raise ValueError('fixture function set is incomplete')
    # This selected AST is never executed as part of source inspection.
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return SimpleNamespace(**namespace)


def protocol():
    return selected_functions(FUZZEL, {
        'input_rows', 'back_choice', 'managed_rows', 'icon_for', 'picker_status', 'selected_row',
    }, {'re': re, 'Error': ValueError, 'Options': object,
        'MAX_INPUT': 1048576, 'MAX_ROWS': 1024, 'MAX_ROW': 4096,
        'MENU_FAILURE_STATUS': 2, 'MENU_DISMISSED_STATUS': 3})


def option_parser():
    tree = ast.parse(FUZZEL.read_bytes(), filename=str(FUZZEL))
    namespace = {'re': re, 'Error': ValueError}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {'VALUE_OPTIONS', 'FLAG_OPTIONS', 'PROFILE_OPTIONS'}:
                # These sets contain literal option words only; no call from
                # the production AST is executed to obtain them.
                namespace[name] = frozenset(ast.literal_eval(node.value.args[0].func.value).split())
    options = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Options')
    fields = [node.target.id for node in options.body if isinstance(node, ast.AnnAssign)]
    namespace['Options'] = lambda *values: SimpleNamespace(**dict(zip(fields, values, strict=True)))
    return selected_functions(FUZZEL, {'parse_options', 'output_name'}, namespace)


class FuzzelProtocolFixtures(unittest.TestCase):
    def test_modes_and_prompt_palette_output_options_keep_argument_boundaries(self):
        helper = option_parser()
        for mode in ('launcher', 'action', 'menu'):
            result = helper.parse_options([mode, '--prompt', 'Words with spaces', '-oDP-1'], {
                'LABWC_FUZZEL_PALETTE': 'computer-management',
                'LABWC_FUZZEL_LOG_SCOPE': 'android-debug-bridge',
            })
            self.assertEqual(result.mode, mode)
            self.assertEqual(result.prompt, 'Words with spaces')
            self.assertEqual(result.output, 'DP-1')
            self.assertEqual(result.palette, 'computer-management')
            self.assertEqual(result.scope, 'android-debug-bridge')
            self.assertEqual('--dmenu' in result.argv, mode != 'launcher')
        for arguments in (['menu', '--output', 'DP-1', '-oeDP-1'], ['menu', '--font', 'Other'],
                          ['menu', '--prompt'], ['menu', '--output=../bad']):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                helper.parse_options(arguments, {})

    def test_decorated_and_duplicate_rows_keep_every_raw_choice(self):
        helper = protocol()
        raw = [b'Show Status', '⮞ Show Status'.encode(), b'Show Status', b'Cancel']
        display, mapping = helper.managed_rows(raw, SimpleNamespace(root_menu=False, prompt='System'))
        rows = display.split(b'\n')[:-1]
        self.assertEqual([row.split(b'\0')[0] for row in rows],
                         [b'Show Status', b'Show Status [2:1]', b'Show Status [3:1]', b'Back'])
        self.assertEqual(list(mapping.values()), raw)
        self.assertTrue(all(b'\0icon\x1f' in row for row in rows))

    def test_appended_back_is_unique_and_recovers_an_empty_raw_choice(self):
        helper = protocol()
        display, mapping = helper.managed_rows(['★ Back'.encode()],
                                               SimpleNamespace(root_menu=False, prompt='Menu'))
        self.assertEqual(list(mapping), [b'Back', b'Back [2:1]'])
        self.assertEqual(mapping[b'Back [2:1]'], b'')
        self.assertEqual(len(display.splitlines()), 2)
        # The production invoke path turns this empty raw mapping into public
        # status 1 rather than a successful empty selection.
        self.assertEqual(helper.back_choice('Back [2:1]'), False)

    def test_native_back_close_and_failures_have_distinct_results(self):
        helper = protocol()
        for native, expected in ((0, 0), (1, 3), (2, 3), (10, 1), (130, 3), (-2, 3), (143, 143)):
            self.assertEqual(helper.picker_status(native, b''), expected)
        self.assertEqual(helper.picker_status(1, b'warn: optional warning\n'), 3)
        self.assertEqual(helper.picker_status(1, b'err: backend failure\n'), 2)
        self.assertEqual(helper.picker_status(0, b'unclassified diagnostic\n'), 2)

    def test_managed_protocol_and_aggregate_limits_reject_before_launch(self):
        helper = protocol()
        for data in (b'x\0icon\x1ffolder\n', b'x\x1f\n', b'x\r\n', b'x' * 4097,
                     b'x\n' * 1025, (b'x' * 4096 + b'\n') * 256):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                helper.input_rows(data, managed=True, nul_delimited=False)
        native = b'Alpha\0icon\x1ffolder\n'
        self.assertEqual(helper.input_rows(native, managed=False, nul_delimited=False), [native[:-1]])
        self.assertEqual(helper.input_rows(b'One\0Two\0', managed=False, nul_delimited=True), [b'One', b'Two'])

    def test_multiple_native_results_are_never_truncated_into_a_selection(self):
        helper = protocol()
        for data, nul in ((b'One\nTwo\n', False), (b'One\0Two\0', True), (b'One\r\n', False)):
            with self.subTest(data=data), self.assertRaises(ValueError):
                helper.selected_row(data, nul_delimited=nul)
        self.assertEqual(helper.selected_row(b'One\n', nul_delimited=False), b'One')
        self.assertEqual(helper.selected_row(b'One\0', nul_delimited=True), b'One')

    def test_managed_selection_accepts_one_nul_us_icon_metadata_record(self):
        helper = protocol()
        self.assertEqual(
            helper.selected_row(b'Show Status\0icon\x1fsystem-search\n',
                                nul_delimited=False, managed=True),
            b'Show Status')
        with self.assertRaises(ValueError):
            helper.selected_row(b'Show Status\0icon-without-us\n',
                                nul_delimited=False, managed=True)

    def test_cleanup_escalates_with_a_separate_bounded_wait(self):
        helper = selected_functions(FUZZEL, {'stop_process'}, {'subprocess': subprocess, 'Error': ValueError})
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 2), 0]
        helper.stop_process(process)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_args_list, [mock.call(timeout=2), mock.call(timeout=2)])
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 2),
                                    subprocess.TimeoutExpired('fixture', 2)]
        with self.assertRaisesRegex(ValueError, 'outcome-unknown'):
            helper.stop_process(process)

    def test_pid_cleanup_skips_an_identity_replacement(self):
        tree = ast.parse(FUZZEL.read_bytes(), filename=str(FUZZEL))
        node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PidFile')
        namespace = {'Path': Path, 'os': mock.Mock(), 'stat': mock.Mock(), 'Error': ValueError}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(FUZZEL), 'exec'), namespace)
        pidfile = namespace['PidFile'].__new__(namespace['PidFile'])
        pidfile.path = mock.Mock()
        pidfile.identity = (1, 2)
        pidfile.stopped = False
        pidfile.path.lstat.return_value = SimpleNamespace(st_dev=1, st_ino=2)
        pidfile.remove()
        pidfile.path.unlink.assert_not_called()
        pidfile.stopped = True
        pidfile.path.lstat.return_value = SimpleNamespace(st_dev=1, st_ino=3)
        pidfile.remove()
        pidfile.path.unlink.assert_not_called()
        pidfile.path.lstat.return_value = SimpleNamespace(st_dev=1, st_ino=2)
        pidfile.remove()
        pidfile.path.unlink.assert_called_once_with()


class WifiSuppressionFixtures(unittest.TestCase):
    def helper(self, *, autoconnect='yes', marker=False, active=True):
        events = []
        state = mock.Mock()
        state.parent.mkdir.side_effect = lambda **_: events.append('mkdir')
        def read(_):
            if not marker:
                raise FileNotFoundError
            return 'yes\n'
        namespace = {
            'read_owned': read, 'ETHERNET_SUPPRESSION_STATE': state,
            'connection_autoconnect': lambda: autoconnect,
            'connection_active': lambda: active,
            'PROFILE_UUID': 'fixture-uuid',
            'publish': mock.Mock(side_effect=lambda *_: events.append('publish-marker')),
            'run': mock.Mock(side_effect=lambda argv, **_: events.append(argv[4]) or 0),
        }
        helper = selected_functions(WIFI, {'suppress_wifi_for_ethernet'}, namespace)
        return helper, events

    def test_marker_is_retained_before_disabling_reconnect(self):
        helper, events = self.helper()
        helper.suppress_wifi_for_ethernet()
        self.assertEqual(events, ['mkdir', 'publish-marker', 'modify', 'down'])

    def test_marker_write_failure_never_changes_nm(self):
        helper, _ = self.helper()
        helper.publish.side_effect = OSError('fixture write failure')
        with self.assertRaises(OSError):
            helper.suppress_wifi_for_ethernet()
        helper.run.assert_not_called()

    def test_periodic_reconciliation_retries_disconnect_and_preserves_manual_wifi(self):
        helper, events = self.helper(autoconnect='no', marker=True)
        helper.suppress_wifi_for_ethernet()
        self.assertEqual(events, ['down'])
        manual, events = self.helper(autoconnect='no', marker=False)
        manual.suppress_wifi_for_ethernet()
        self.assertEqual(events, [])

    def test_networkmanager_mac_case_is_canonical_but_identity_stays_strict(self):
        helper = selected_functions(WIFI, {'normalize_mac'}, {'re': re, 'ConfigurationError': ValueError})
        self.assertEqual(helper.normalize_mac('0C:9A:3C:B1:CD:DA'), '0c:9a:3c:b1:cd:da')
        for value in (None, '', '0c:9a:3c:b1:cd', '0c:9a:3c:b1:cd:zz'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                helper.normalize_mac(value)


class WayscriberDispatchFixtures(unittest.TestCase):
    """Mock every helper; never contact a real user manager or native daemon."""

    def invoke(self, *, start=0, ready=0, toggle=0):
        with tempfile.TemporaryDirectory(prefix='wayscriber-dispatch-') as temporary:
            root = Path(temporary)
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            # This is an unconnected socket wholly inside the owned fixture.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as display:
                display.bind(str(runtime / 'wayland-fixture'))
                program = '''#!/usr/bin/python3 -IB
import json
import os
from pathlib import Path
import subprocess
import sys
root = Path(os.environ['FIXTURE_ROOT']).resolve(strict=True)
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / 'calls').open('a', encoding='utf-8') as stream:
    stream.write(json.dumps([name, *args]) + '\\n')
if name == 'id':
    assert args == ['-u']
    print('1001')
elif name == 'stat':
    assert args[:1] == ['-c'] and args[2] == '--'
    if args[1] == '%u %a':
        assert args[3] == str(root / 'runtime')
        print('1001 700')
    else:
        assert args[1] == '%u %h'
        assert args[3] == str(root / 'runtime/wayland-fixture')
        print('1001 1')
elif name == 'timeout':
    assert args[:2] == ['--signal=TERM', '--kill-after=2s']
    assert args[2] in {'5s', '12s'}
    command = args[3:]
    assert command[0] in {str(root / 'systemctl'), str(root / 'wayscriber')}
    sys.exit(subprocess.run(command, check=False, timeout=1).returncode)
elif name == 'systemctl':
    assert args == ['--user', 'start', 'wayscriber.service']
    if int(os.environ['FIXTURE_START']) == 0 and int(os.environ['FIXTURE_READY']) == 0:
        (root / 'runtime/wayscriber').mkdir()
        (root / 'runtime/wayscriber/wayscriber.pid').write_text('1001\n')
    sys.exit(int(os.environ['FIXTURE_START']))
elif name == 'wayscriber':
    assert args == ['--daemon-toggle']
    sys.exit(int(os.environ['FIXTURE_TOGGLE']))
elif name == 'sleep':
    assert args == ['0.1']
    sys.exit(0)
else:
    raise RuntimeError('unexpected fixture command')
'''
                source = WAYSCRIBER.read_text()
                self.assertEqual(source.count('runtime_root="/run/user/$runtime_uid"'), 1)
                source = source.replace('runtime_root="/run/user/$runtime_uid"',
                                        'runtime_root="' + str(runtime) + '"')
                for name in ('id', 'stat', 'timeout', 'systemctl', 'wayscriber', 'sleep'):
                    path = root / name
                    path.write_text(program)
                    path.chmod(0o700)
                    source = source.replace('/usr/bin/' + name, str(path))
                script = root / 'toggle.sh'
                script.write_text(source)
                env = {'PATH': '/usr/bin:/bin', 'HOME': str(root), 'LC_ALL': 'C',
                       'LABWC_SESSION_OWNER': 'desktop', 'XDG_SESSION_TYPE': 'wayland',
                       'XDG_RUNTIME_DIR': str(runtime), 'WAYLAND_DISPLAY': 'wayland-fixture',
                       'FIXTURE_ROOT': str(root), 'FIXTURE_START': str(start),
                       'FIXTURE_READY': str(ready), 'FIXTURE_TOGGLE': str(toggle)}
                result = subprocess.run(['/bin/sh', str(script)], env=env, stdin=subprocess.DEVNULL,
                                        capture_output=True, text=True, timeout=3)
                calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
                return result, calls

    def test_start_and_readiness_failures_never_dispatch(self):
        for values in ({'start': 1}, {'ready': 124}):
            with self.subTest(values=values):
                result, calls = self.invoke(**values)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(any(call[0] == 'wayscriber' for call in calls))

    def test_reply_failure_or_timeout_never_retries_a_toggle(self):
        for status in (1, 124, 137):
            with self.subTest(status=status):
                result, calls = self.invoke(toggle=status)
                self.assertEqual(result.returncode, 75)
                self.assertIn('outcome-unknown', result.stderr)
                self.assertEqual(sum(call[0] == 'wayscriber' for call in calls), 1)
                self.assertEqual(sum(call[0] == 'systemctl' for call in calls), 1)

    def test_success_uses_finite_phase_and_cleanup_budgets(self):
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        budgets = [call[3] for call in calls if call[0] == 'timeout']
        self.assertEqual(budgets, ['5s', '12s'])
        self.assertEqual(sum(call[0] == 'wayscriber' for call in calls), 1)


if __name__ == '__main__':
    unittest.main()
