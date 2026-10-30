"""Unexecuted failure fixtures for continuous, child-free status readers.

All bus replies, clocks, signals and sockets are inert fixture objects. These
cases do not authorize executing this module or the repository test runners.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from collections import deque
from contextlib import redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'


def load_fixture(relative, name):
    loader = importlib.machinery.SourceFileLoader(name, str(TARGET / relative))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class BusError(Exception):
    pass


class Cancellable:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class Variant:
    def __init__(self, signature='', value=None, size=16):
        self.signature, self.value, self.size = signature, value, size

    def get_type_string(self):
        return self.signature

    def get_size(self):
        return self.size

    def n_children(self):
        return len(self.value)

    def get_child_value(self, index):
        return self.value[index]

    def get_string(self):
        return self.value

    def get_variant(self):
        return self.value


class Connection:
    def __init__(self):
        self.calls = []

    def call(self, *arguments):
        self.calls.append(arguments)

    def call_finish(self, result):
        if isinstance(result, Exception):
            raise result
        return result

    def complete(self, reply):
        self.calls[-1][-1](self, reply)


class EventReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_fixture('usr/local/libexec/labwc-waybar-events.tmpl', 'waybar_events_fixture')

    def setUp(self):
        self.timers = []
        self.loop = SimpleNamespace(quit=mock.Mock())
        self.glib = SimpleNamespace(
            MainLoop=lambda: self.loop, Error=BusError, Variant=Variant,
            VariantType=SimpleNamespace(new=lambda value: value),
            timeout_add=lambda delay, callback: self.timers.append((delay, callback)) or len(self.timers))
        self.gio = SimpleNamespace(Cancellable=Cancellable,
            DBusCallFlags=SimpleNamespace(NO_AUTO_START=1),
            DBusError=SimpleNamespace(get_remote_error=lambda error: str(error)))
        self.glib_unix = SimpleNamespace(signal_add=mock.Mock())
        self.connection = Connection()
        self.stream = io.StringIO()

    def reader(self, mode='notifications'):
        reader = self.module.Reader(mode, self.gio, self.glib, self.glib_unix)
        reader.connection = self.connection
        return reader

    def modes(self, *values, size=16):
        return Variant('(as)', [Variant('as', [Variant('s', value) for value in values])], size)

    def test_event_storm_coalesces_and_obsolete_reply_cannot_restore_old_state(self):
        reader = self.reader()
        with redirect_stdout(self.stream):
            for _ in range(500):
                reader.queue()
            self.assertEqual(len(self.timers), 1)
            reader.refresh()
            self.assertEqual(len(self.connection.calls), 1)
            previous = reader.pending
            reader.owner_changed(None, None, None, None, None, Variant('(sss)'), None)
            self.assertTrue(previous.cancelled)
            self.connection.complete(self.modes('do-not-disturb'))
            self.assertTrue(reader.dirty)
            self.assertEqual(len(self.timers), 2)
            reader.refresh()
            self.connection.complete(self.modes())
        states = [json.loads(line)['class'] for line in self.stream.getvalue().splitlines()]
        self.assertEqual(states, ['error', 'normal'])

    def test_reply_limits_and_bus_errors_are_unavailable_without_payload_disclosure(self):
        for reply in (self.modes(*['secret-fixture'] * 65), self.modes('x' * 129),
                      self.modes(size=16385), BusError('private-fixture-error')):
            with self.subTest(reply=type(reply).__name__):
                reader = self.reader()
                stream = io.StringIO()
                with redirect_stdout(stream):
                    reader.refresh()
                    self.connection.complete(reply)
                output = json.loads(stream.getvalue())
                self.assertEqual(output['class'], 'error')
                self.assertNotIn('secret-fixture', stream.getvalue())
                self.assertNotIn('private-fixture', stream.getvalue())

    def test_recording_subscription_race_recovers_and_missing_unit_is_idle(self):
        reader = self.reader('capture')
        with redirect_stdout(self.stream):
            reader.refresh()
            self.assertEqual(self.connection.calls[-1][3], 'Subscribe')
            self.connection.complete(BusError('org.freedesktop.systemd1.AlreadySubscribed'))
            self.assertTrue(reader.subscribed)
            reader.refresh()
            self.assertEqual(self.connection.calls[-1][3], 'Get')
            self.connection.complete(BusError('org.freedesktop.DBus.Error.UnknownObject'))
            reader.refresh()
            self.connection.complete(BusError('org.freedesktop.DBus.Error.AccessDenied'))
        self.assertEqual([json.loads(line)['class'] for line in self.stream.getvalue().splitlines()],
                         ['idle', 'unavailable'])

    def test_unchanged_status_is_cached_and_stop_cancels_only_own_request(self):
        reader = self.reader()
        with redirect_stdout(self.stream):
            reader.emit([])
            reader.emit([])
            reader.refresh()
            pending = reader.pending
            reader.stop()
            self.connection.complete(self.modes('do-not-disturb'))
        self.assertEqual(len(self.stream.getvalue().splitlines()), 1)
        self.assertTrue(pending.cancelled)
        self.assertTrue(reader.connection_cancel.cancelled)
        self.loop.quit.assert_called_once()
        self.assertIsNone(reader.pending)

    def test_consumer_exit_stops_without_a_child_or_retry_loop(self):
        reader = self.reader()
        with mock.patch('builtins.print', side_effect=BrokenPipeError):
            reader.emit([])
        self.assertFalse(reader.alive)
        self.assertFalse(reader.queue())

    def test_notification_initialization_failures_keep_visible_json_and_retry_interval(self):
        for failure in (OSError('private fixture path'), ValueError('private fixture bus'),
                        ImportError('private fixture module'), RuntimeError('private fixture detail')):
            with self.subTest(failure=type(failure).__name__):
                output, errors = io.StringIO(), io.StringIO()
                with mock.patch.object(self.module, 'main', side_effect=failure), \
                        redirect_stdout(output), redirect_stderr(errors):
                    self.assertEqual(self.module.cli(['notifications']), 0)
                payload = json.loads(output.getvalue())
                self.assertTrue(payload['text'])
                self.assertEqual(payload['class'], 'error')
                self.assertIn('Left: menu', payload['tooltip'])
                self.assertNotIn('private fixture', output.getvalue() + errors.getvalue())

    def test_disconnected_notification_reader_keeps_button_but_other_failures_stay_failures(self):
        for arguments, expected in ((['notifications'], 0), (['capture'], 1),
                                    (['notifications', 'extra'], 1)):
            output, errors = io.StringIO(), io.StringIO()
            with self.subTest(arguments=arguments), \
                    mock.patch.object(self.module, 'main', return_value=1), \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(self.module.cli(arguments), expected)
            if arguments == ['notifications']:
                self.assertEqual(json.loads(output.getvalue())['class'], 'error')
            else:
                self.assertEqual(output.getvalue(), '')

    def test_success_and_consumer_pipe_close_do_not_emit_a_spurious_error(self):
        for outcome in (0, BrokenPipeError()):
            output, errors = io.StringIO(), io.StringIO()
            patch = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
            with mock.patch.object(self.module, 'main', **patch), \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(self.module.cli(['notifications']), 0)
            self.assertEqual(output.getvalue() + errors.getvalue(), '')

    def test_glib_unix_signals_and_cleanup_use_only_owned_sources(self):
        reader = self.reader()
        self.glib.PRIORITY_DEFAULT = 0
        self.glib.timeout_add_seconds = mock.Mock(side_effect=[10, 11])
        self.glib.source_remove = mock.Mock()
        context = SimpleNamespace(find_source_by_id=mock.Mock(return_value=object()))
        self.glib.MainContext = SimpleNamespace(default=lambda: context)
        self.glib_unix.signal_add.side_effect = [12, 13, 14]
        self.gio.bus_get = mock.Mock()
        self.gio.BusType = SimpleNamespace(SESSION=1)
        self.loop.run = mock.Mock(side_effect=reader.stop)
        with redirect_stdout(self.stream):
            self.assertEqual(reader.run(), 0)
        self.assertEqual(self.glib_unix.signal_add.call_args_list, [
            mock.call(0, signum, reader.stop)
            for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        ])
        self.assertEqual(self.glib.source_remove.call_args_list,
                         [mock.call(source) for source in (10, 11, 12, 13, 14)])
        self.assertTrue(reader.connection_cancel.cancelled)


class BatteryWatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_fixture('usr/local/libexec/labwc-waybar-battery', 'waybar_battery_watch_fixture')

    def test_kernel_events_reconcile_without_reemitting_unchanged_output(self):
        handlers, now, passes, waits = {}, [100.0], [0], []
        packets = deque([(b'SUBSYSTEM=power_supply\0', [], 0, (123, 1)),
                         (b'SUBSYSTEM=power_supply\0', [], 0, (0, 1))])
        monitor = mock.Mock()
        def receive(_limit):
            if packets:
                return packets.popleft()
            raise BlockingIOError
        monitor.recvmsg.side_effect = receive
        def wait(_read, _write, _except, timeout):
            self.assertEqual(_read, [71, monitor])
            self.assertLessEqual(timeout, 60)
            waits.append(timeout)
            passes[0] += 1
            now[0] += 1
            if passes[0] >= 3:
                handlers[signal.SIGTERM](signal.SIGTERM, None)
            return ([monitor] if passes[0] == 1 else [], [], [])
        stream = io.StringIO()
        with mock.patch.object(self.module.signal, 'signal', side_effect=lambda sig, fn: handlers.update({sig: fn})), \
             mock.patch.object(self.module.signal, 'set_wakeup_fd', return_value=-1) as wakeup, \
             mock.patch.object(self.module.os, 'pipe2', return_value=(71, 72)), \
             mock.patch.object(self.module.os, 'close') as close, \
             mock.patch.object(self.module.socket, 'socket', return_value=monitor), \
             mock.patch.object(self.module.select, 'select', side_effect=wait), \
             mock.patch.object(self.module.time, 'monotonic', side_effect=lambda: now[0]), \
             mock.patch.object(self.module, 'output', return_value={'text': '50%'}) as output, \
             redirect_stdout(stream):
            self.assertEqual(self.module.watch(Path('/inert-fixture-only')), 0)
        self.assertEqual(output.call_count, 2)
        self.assertEqual(len(stream.getvalue().splitlines()), 1)
        self.assertEqual(waits[0], 60)
        self.assertEqual(wakeup.call_args_list, [mock.call(72, warn_on_full_buffer=False), mock.call(-1)])
        self.assertEqual(close.call_args_list, [mock.call(71), mock.call(72)])
        monitor.close.assert_called_once()

    def test_missing_event_socket_uses_bounded_reconciliation_and_closes_partial_socket(self):
        handlers, now, passes = {}, [100.0], [0]
        monitor = mock.Mock()
        monitor.bind.side_effect = OSError('inert fixture denial')
        def wait(readers, _write, _except, timeout):
            self.assertEqual(readers, [71])
            self.assertEqual(timeout, 60)
            passes[0] += 1
            now[0] += timeout
            if passes[0] == 2:
                handlers[signal.SIGHUP](signal.SIGHUP, None)
            return [71], [], []
        with mock.patch.object(self.module.signal, 'signal', side_effect=lambda sig, fn: handlers.update({sig: fn})), \
             mock.patch.object(self.module.signal, 'set_wakeup_fd', return_value=-1) as wakeup, \
             mock.patch.object(self.module.os, 'pipe2', return_value=(71, 72)), \
             mock.patch.object(self.module.os, 'read', return_value=b'\0'), \
             mock.patch.object(self.module.os, 'close') as close, \
             mock.patch.object(self.module.socket, 'socket', return_value=monitor), \
             mock.patch.object(self.module.select, 'select', side_effect=wait), \
             mock.patch.object(self.module.time, 'monotonic', side_effect=lambda: now[0]), \
             mock.patch.object(self.module, 'output', return_value={'text': '50%'}) as output, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(self.module.watch(Path('/inert-fixture-only')), 0)
        self.assertEqual(output.call_count, 2)
        self.assertEqual(wakeup.call_args_list, [mock.call(72, warn_on_full_buffer=False), mock.call(-1)])
        self.assertEqual(close.call_args_list, [mock.call(71), mock.call(72)])
        monitor.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
