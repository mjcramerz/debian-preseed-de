"""Unexecuted Python Fuzzel, Wi-Fi and Wayscriber regression fixtures.

Selected Python functions use local mocks. Filesystem metadata, clocks, locking,
processes and session state for the changed contracts are mocked completely.
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
from pathlib import Path
import re
import stat
import subprocess
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

    def helper(self, *, start=0, ready=True, toggle=0):
        namespace = {
            'Path': Path, 'RUNTIME_BASE': Path('/run/user'),
            'os': SimpleNamespace(environ={
                'LABWC_SESSION_OWNER': 'desktop', 'XDG_SESSION_TYPE': 'wayland',
                'XDG_RUNTIME_DIR': '/run/user/1001', 'WAYLAND_DISPLAY': 'wayland-fixture',
            }, getuid=lambda: 1001, access=mock.Mock(return_value=True), X_OK=1),
            'WAYLAND_NAME': re.compile(r'^[A-Za-z0-9_.-]+$'),
            'runtime_identity': mock.Mock(return_value=True),
            'socket_identity': mock.Mock(return_value=True),
            'SYSTEMCTL': '/usr/bin/systemctl', 'SERVICE': 'wayscriber.service',
            'WAYSCRIBER': '/usr/bin/wayscriber', 'START_TIMEOUT': 5.0, 'REQUEST_TIMEOUT': 10.0,
            'run_bounded': mock.Mock(side_effect=[start, toggle]),
            'wait_for_readiness': mock.Mock(return_value=ready),
            'fail': mock.Mock(return_value=1), 'sys': SimpleNamespace(stderr=None),
        }
        return selected_functions(WAYSCRIBER, {'main'}, namespace)

    def test_real_directory_link_counts_are_accepted_without_weakening_identity(self):
        helper = selected_functions(WAYSCRIBER, {'runtime_identity'}, {
            'Path': Path, 'RUNTIME_BASE': Path('/run/user'), 'stat': stat,
        })
        runtime = Path('/run/user/1001')
        for links in (2, 8, 32):
            metadata = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1001, st_nlink=links)
            with self.subTest(links=links), mock.patch.object(Path, 'is_symlink', return_value=False), \
                    mock.patch.object(Path, 'stat', return_value=metadata):
                self.assertTrue(helper.runtime_identity(1001, runtime))
        for mode, owner in ((stat.S_IFDIR | 0o755, 1001), (stat.S_IFDIR | 0o700, 0),
                            (stat.S_IFREG | 0o700, 1001), (stat.S_IFLNK | 0o700, 1001)):
            metadata = SimpleNamespace(st_mode=mode, st_uid=owner, st_nlink=1)
            with self.subTest(mode=mode, owner=owner), mock.patch.object(Path, 'is_symlink', return_value=False), \
                    mock.patch.object(Path, 'stat', return_value=metadata):
                self.assertFalse(helper.runtime_identity(1001, runtime))
        with mock.patch.object(Path, 'is_symlink', return_value=True), mock.patch.object(Path, 'stat') as metadata:
            self.assertFalse(helper.runtime_identity(1001, runtime))
            metadata.assert_not_called()
        with mock.patch.object(Path, 'is_symlink') as symlink:
            self.assertFalse(helper.runtime_identity(1001, Path('/run/user/1002')))
            symlink.assert_not_called()

    def test_socket_aliases_and_wrong_ownership_remain_rejected(self):
        helper = selected_functions(WAYSCRIBER, {'socket_identity'}, {'Path': Path, 'stat': stat})
        path = mock.Mock()
        for mode, owner, links, accepted in (
                (stat.S_IFSOCK | 0o755, 1001, 1, True),
                (stat.S_IFSOCK | 0o600, 0, 1, False),
                (stat.S_IFSOCK | 0o600, 1001, 2, False),
                (stat.S_IFLNK | 0o777, 1001, 1, False)):
            path.lstat.return_value = SimpleNamespace(st_mode=mode, st_uid=owner, st_nlink=links)
            self.assertEqual(helper.socket_identity(path, 1001), accepted)

    def test_start_and_readiness_failures_never_dispatch(self):
        for values in ({'start': 1}, {'ready': False}):
            with self.subTest(values=values):
                helper = self.helper(**values)
                self.assertEqual(helper.main([]), 1)
                helper.run_bounded.assert_called_once_with(
                    ['/usr/bin/systemctl', '--user', 'start', 'wayscriber.service'], 5.0)

    def test_reply_failure_or_timeout_never_retries_a_toggle(self):
        for status in (1, 124, 137):
            with self.subTest(status=status):
                helper = self.helper(toggle=status)
                with mock.patch('builtins.print') as diagnostic:
                    self.assertEqual(helper.main([]), 75)
                self.assertIn('outcome-unknown', diagnostic.call_args.args[0])
                self.assertEqual(helper.run_bounded.call_args_list, [
                    mock.call(['/usr/bin/systemctl', '--user', 'start', 'wayscriber.service'], 5.0),
                    mock.call(['/usr/bin/wayscriber', '--daemon-toggle'], 10.0),
                ])

    def test_success_uses_finite_phase_and_cleanup_budgets(self):
        helper = self.helper()
        self.assertEqual(helper.main([]), 0)
        helper.wait_for_readiness.assert_called_once_with(Path('/run/user/1001/wayscriber/wayscriber.pid'), 1001)
        self.assertEqual(helper.run_bounded.call_count, 2)
        process = mock.Mock(returncode=0)
        process.wait.side_effect = subprocess.TimeoutExpired('fixture', 10)
        runner = selected_functions(WAYSCRIBER, {'run_bounded'}, {
            'subprocess': subprocess, 'terminate_process': mock.Mock(),
        })
        with mock.patch.object(subprocess, 'Popen', return_value=process) as spawn:
            self.assertEqual(runner.run_bounded(['/usr/bin/wayscriber', '--daemon-toggle'], 10.0), 124)
        spawn.assert_called_once_with(['/usr/bin/wayscriber', '--daemon-toggle'],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        runner.terminate_process.assert_called_once_with(process)
        process.wait.assert_called_once_with(timeout=10.0)


class WifiLockFixtures(unittest.TestCase):
    """Mock locking and monotonic time; never open the production lock."""

    def helper(self, results, instants):
        locks = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=mock.Mock(side_effect=results))
        clock = SimpleNamespace(monotonic=mock.Mock(side_effect=instants), sleep=mock.Mock())
        return selected_functions(WIFI, {'acquire_lock'}, {
            'fcntl': locks, 'time': clock, 'LOCK_WAIT_TIMEOUT': 45.0,
        })

    def test_boot_waits_for_the_current_writer_then_acquires_the_same_lock(self):
        helper = self.helper([BlockingIOError(), BlockingIOError(), None], [0.0, 0.0, 0.1])
        lock = object()
        helper.acquire_lock(lock, wait=True)
        self.assertEqual(helper.fcntl.flock.call_args_list, [mock.call(lock, 6)] * 3)
        self.assertEqual(helper.time.sleep.call_args_list, [mock.call(0.1)] * 2)

    def test_busy_boot_is_bounded_and_link_hooks_never_wait(self):
        helper = self.helper([BlockingIOError(), BlockingIOError()], [0.0, 44.95, 45.0])
        with self.assertRaises(BlockingIOError):
            helper.acquire_lock(object(), wait=True)
        self.assertAlmostEqual(helper.time.sleep.call_args.args[0], 0.05)
        helper = self.helper([BlockingIOError()], [0.0, 0.0])
        with self.assertRaises(BlockingIOError):
            helper.acquire_lock(object(), wait=False)
        helper.time.sleep.assert_not_called()

    def test_permission_failure_is_not_retried_as_contention(self):
        helper = self.helper([PermissionError()], [0.0])
        with self.assertRaises(PermissionError):
            helper.acquire_lock(object(), wait=True)
        helper.time.sleep.assert_not_called()
        helper.fcntl.flock.assert_called_once()

    def entrypoint(self, arguments, *, busy=False):
        lock = mock.Mock()
        lock.fileno.return_value = 42
        stream = mock.MagicMock()
        stream.__enter__.return_value = lock
        operating = SimpleNamespace(
            geteuid=lambda: 0, umask=mock.Mock(), open=mock.Mock(return_value=42),
            fdopen=mock.Mock(return_value=stream),
            fstat=mock.Mock(return_value=SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)),
            O_RDWR=1, O_CREAT=2, O_NOFOLLOW=4, O_CLOEXEC=8,
        )
        return selected_functions(WIFI, {'main'}, {
            'os': operating, 'stat': stat, 're': re,
            'sys': SimpleNamespace(argv=['fixture', *arguments], stdin=SimpleNamespace(isatty=lambda: True)),
            'ConfigurationError': ValueError,
            'acquire_lock': mock.Mock(side_effect=BlockingIOError() if busy else None),
            'firstboot': mock.Mock(), 'dispatcher_event': mock.Mock(), 'carrier_event': mock.Mock(),
        }), stream

    def test_only_firstboot_waits_and_success_reaches_reconciliation_under_the_lock(self):
        helper, stream = self.entrypoint(['--firstboot'])
        helper.main()
        helper.acquire_lock.assert_called_once_with(stream.__enter__.return_value, wait=True)
        helper.firstboot.assert_called_once_with()
        stream.__exit__.assert_called_once()
        for arguments in (['--dispatcher', 'eth0', 'up'], ['--carrier', 'eth0'], ['--nmtui']):
            helper, stream = self.entrypoint(arguments, busy=True)
            if arguments[0] == '--nmtui':
                with self.assertRaisesRegex(ValueError, 'already in progress'):
                    helper.main()
            else:
                helper.main()
            helper.acquire_lock.assert_called_once_with(stream.__enter__.return_value, wait=False)
            helper.firstboot.assert_not_called()
            helper.dispatcher_event.assert_not_called()
            helper.carrier_event.assert_not_called()
            stream.__exit__.assert_called_once()

    def test_boot_lock_deadline_is_reported_as_contention_and_never_mutates(self):
        helper, stream = self.entrypoint(['--firstboot'], busy=True)
        with self.assertRaisesRegex(ValueError, 'lock remained busy for 45 seconds'):
            helper.main()
        helper.firstboot.assert_not_called()
        stream.__exit__.assert_called_once()


if __name__ == '__main__':
    unittest.main()
