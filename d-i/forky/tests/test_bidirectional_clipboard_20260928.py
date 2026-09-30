"""Bounded optional clipboard work and private application socket masking."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from payload_fixture import python_library

FORKY = Path(__file__).resolve().parents[1]
LIB = python_library(FORKY / 'hooks/target/usr/local/lib/python3.14/dist-packages')
sys.path.insert(0, str(LIB))
from labwc_managed_app import wayland_compat_runtime as bridge
from labwc_managed_app import profiles
from labwc_managed_app.compat_protocol import stop_processes


class ClipboardRoutingTests(unittest.TestCase):
    def tearDown(self):
        bridge._received_signal = None

    def test_trusted_policy_enables_host_clipboard_but_private_x11_is_kept(self):
        for app in ('zoom', 'discord'):
            self.assertIs(profiles.PERSISTENT_SANDBOX_CONFIG[app]['clipboard_bridge'], True)
        argv = bridge.masked_application_argv('discord', 'wayland-0', 'wayland-1', ['/opt/discord/Discord'])
        self.assertNotIn('/tmp/.X11-unix', argv)  # inherited private X socket is not masked
        with mock.patch.dict(os.environ, {'DISPLAY': ':0'}, clear=True):
            self.assertEqual(bridge.application_process_environment('discord')['DISPLAY'], ':0')

    def test_private_x11_bridge_rejects_inherited_host_display(self):
        with mock.patch.dict(os.environ, {'DISPLAY': 'localhost:10.0'}):
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, 'Cage DISPLAY'):
                bridge.private_clipboard_x11_environment()

    def test_actual_blocking_and_oversized_pipes_have_bounds(self):
        for code in ('import time; time.sleep(30)', 'import os; os.write(1,b"x"*65536)'):
            process = subprocess.Popen([sys.executable, '-B', '-c', code], stdout=subprocess.PIPE, start_new_session=True)
            start = time.monotonic()
            try:
                with self.assertRaises(bridge.CompatibilityRuntimeError):
                    bridge.bounded_read(process.stdout.fileno(), start + .12, limit=16)
                self.assertLess(time.monotonic() - start, .4)
            finally:
                stop_processes([process], time.monotonic() + .5, groups=True)
                process.stdout.close()

    def test_cancellation_interrupts_pending_pipe_without_waiting_for_eof(self):
        r, w = os.pipe()
        try:
            bridge._received_signal = signal.SIGTERM
            start = time.monotonic()
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, 'cancelled'):
                bridge.bounded_read(r, start + 10)
            self.assertLess(time.monotonic() - start, .1)
        finally:
            os.close(r); os.close(w)

    def test_actual_reader_classifies_empty_clear_unavailable_without_logging_data(self):
        original = subprocess.Popen
        cases = [('', 0, bridge.ClipboardSelection('empty', b'')),
                 ('import os; os.write(1,b"secret")', 0, bridge.ClipboardSelection('text', b'secret')),
                 ('import os; os.write(2,b"Nothing is copied\\n")', 1, bridge.ClipboardSelection('cleared')),
                 ('import os; os.write(2,b"unavailable")', 1, bridge.ClipboardSelection('unavailable'))]
        for code, status, expected in cases:
            def read(_argv, **kwargs):
                return original([sys.executable, '-B', '-c', code + ';raise SystemExit('+str(status)+')' if code else 'raise SystemExit(0)'], **kwargs)
            with self.subTest(expected=expected.state), mock.patch.object(bridge.subprocess, 'Popen', side_effect=read):
                self.assertEqual(bridge.read_clipboard_selection({}), expected)

    def test_actual_destination_reader_bounds_both_streams(self):
        original = subprocess.Popen
        for code in ('import os; os.write(1,b"x"*65536)', 'import os; os.write(2,b"x"*65536)', 'import time; time.sleep(30)'):
            def read(_argv, **kwargs):
                return original([sys.executable, '-B', '-c', code], **kwargs)
            with mock.patch.object(bridge, 'MAX_CLIPBOARD_TEXT_BYTES', 16), \
                 mock.patch.object(bridge, 'CLIPBOARD_OPERATION_TIMEOUT_SECONDS', .1), \
                 mock.patch.object(bridge.subprocess, 'Popen', side_effect=read):
                start = time.monotonic()
                self.assertIsNone(bridge.destination_clipboard_text({}))
                self.assertLess(time.monotonic() - start, .8)

    def test_foreground_owner_remains_alive_after_success_until_replaced_or_shutdown(self):
        original = subprocess.Popen
        captured = []
        def own(argv, **kwargs):
            captured.append(argv)
            return original([sys.executable, '-B', '-c', 'import sys,time; sys.stdin.buffer.read(); time.sleep(30)'], **kwargs)
        with mock.patch.object(bridge.subprocess, 'Popen', side_effect=own), \
             mock.patch.object(bridge, 'destination_clipboard_text', return_value=b'new'):
            owner = bridge.selection_owner(b'new', {}, x11=True)
        try:
            self.assertIn('-quiet', captured[0])
            self.assertNotIn('-silent', captured[0])
            self.assertIsNone(owner.poll())
            time.sleep(.08)
            self.assertIsNone(owner.poll())
        finally:
            self.assertTrue(stop_processes([owner], time.monotonic() + .5, groups=True))

    def test_host_text_and_empty_selection_are_mirrored_without_host_writes(self):
        state = {False: bridge.ClipboardSelection('text', b'old-secret'), True: bridge.ClipboardSelection('text', b'old-secret')}
        writes = []
        ticks = 0
        def selection(_env, *, x11=False, **_kw):
            return state[x11]
        def text(_env, *, x11=False, **_kw):
            return state[x11].data
        def own(payload, _env, *, x11):
            writes.append((x11, payload)); state[x11] = bridge.ClipboardSelection('text' if payload else 'empty', payload)
            return None
        def tick(_interval):
            nonlocal ticks
            ticks += 1
            if ticks == 1:
                state[False] = bridge.ClipboardSelection('empty', b'')
            if ticks == 3:
                bridge._received_signal = signal.SIGTERM
        with mock.patch.dict(os.environ, {bridge.OUTER_WAYLAND_DISPLAY_ENVIRONMENT: 'wayland-0'}), \
             mock.patch.object(bridge.os, 'geteuid', return_value=1000), \
             mock.patch.object(bridge, 'register_signal_handlers'), \
             mock.patch.object(bridge, 'clipboard_process_environment', return_value={}), \
             mock.patch.object(bridge, 'private_clipboard_x11_environment', return_value={}), \
             mock.patch.object(bridge, 'read_clipboard_selection', side_effect=selection), \
             mock.patch.object(bridge, 'destination_clipboard_text', side_effect=text), \
             mock.patch.object(bridge, 'selection_owner', side_effect=own), \
             mock.patch.object(bridge, 'clipboard_lock', side_effect=lambda _: os.open('/dev/null', os.O_RDONLY)), \
             mock.patch.object(bridge.time, 'sleep', side_effect=tick):
            self.assertEqual(bridge.run_clipboard_bridge([bridge.CLIPBOARD_BRIDGE_MODE, 'wayland-1']), 143)
        self.assertEqual(writes, [(True, b'old-secret'), (True, b'')])
        self.assertEqual(state[True].data, b'')

    def test_unavailable_clipboard_retries_and_never_replays_cleared_text(self):
        selections = iter([bridge.ClipboardSelection('text', b'old'),
                           bridge.ClipboardSelection('cleared'),
                           bridge.ClipboardSelection('unavailable'),
                           bridge.ClipboardSelection('text', b'fresh')])
        writes = []
        ticks = 0
        def tick(_interval):
            nonlocal ticks
            ticks += 1
            if ticks == 4:
                bridge._received_signal = signal.SIGTERM
        with mock.patch.dict(os.environ, {bridge.OUTER_WAYLAND_DISPLAY_ENVIRONMENT: 'wayland-0'}), \
             mock.patch.object(bridge.os, 'geteuid', return_value=1000), \
             mock.patch.object(bridge, 'register_signal_handlers'), \
             mock.patch.object(bridge, 'clipboard_process_environment', return_value={}), \
             mock.patch.object(bridge, 'private_clipboard_x11_environment', return_value={}), \
             mock.patch.object(bridge, 'read_clipboard_selection', side_effect=lambda _: next(selections)), \
             mock.patch.object(bridge, 'selection_owner', side_effect=lambda data, env, **kw: writes.append((data, kw))), \
             mock.patch.object(bridge.time, 'sleep', side_effect=tick):
            self.assertEqual(bridge.run_clipboard_bridge([bridge.CLIPBOARD_BRIDGE_MODE, 'wayland-1']), 143)
        self.assertEqual(writes, [(b'old', {'x11': True}), (b'fresh', {'x11': True})])

    def test_application_namespace_masks_both_wayland_sockets(self):
        argv = bridge.masked_application_argv('discord', 'wayland-0', 'wayland-1', ['/opt/discord/Discord'])
        self.assertEqual(argv[:4], ['/usr/bin/bwrap', '--unshare-user', '--unshare-pid', '--die-with-parent'])
        for display in ('wayland-0', 'wayland-1'):
            self.assertIn(['--ro-bind', '/dev/null', f'/run/user/{os.getuid()}/{display}'], [argv[i:i+3] for i in range(len(argv))])
        with self.assertRaises(bridge.CompatibilityRuntimeError):
            bridge.masked_application_argv('discord', 'wayland-0', 'wayland-0', ['/opt/discord/Discord'])

    def test_application_fails_closed_if_host_socket_remains_visible(self):
        args = [bridge.MASKED_APPLICATION_MODE, 'zoom', 'wayland-0', 'wayland-1', '--', '/usr/bin/zoom']
        with mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}', 'WAYLAND_DISPLAY': 'wayland-1'}), \
             mock.patch.object(bridge, 'protect_supervisor'), \
             mock.patch.object(bridge.os, 'geteuid', return_value=1000), \
             mock.patch.object(bridge.os, 'lstat', return_value=mock.Mock(st_mode=stat.S_IFSOCK)), \
             mock.patch.object(bridge.subprocess, 'Popen') as execute:
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, 'host Wayland socket'):
                bridge.run_masked_application(args)
            execute.assert_not_called()

    def test_application_fails_closed_if_private_null_device_is_unusable(self):
        args = [bridge.MASKED_APPLICATION_MODE, 'discord', 'wayland-0', 'wayland-1', '--', '/opt/discord/Discord']
        with mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}', 'WAYLAND_DISPLAY': 'wayland-1'}), \
             mock.patch.object(bridge, 'protect_supervisor'), \
             mock.patch.object(bridge.os, 'geteuid', return_value=1000), \
             mock.patch.object(bridge.os, 'lstat', return_value=mock.Mock(st_mode=stat.S_IFREG)), \
             mock.patch.object(bridge.os, 'open', side_effect=OSError('nodev')), \
             mock.patch.object(bridge.subprocess, 'Popen') as execute:
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, 'cannot open /dev/null'):
                bridge.run_masked_application(args)
            execute.assert_not_called()

    def test_null_device_must_be_the_expected_character_device(self):
        with mock.patch.object(bridge.os, 'open', return_value=7) as opening, \
             mock.patch.object(bridge.os, 'fstat', return_value=mock.Mock(st_mode=stat.S_IFREG, st_rdev=os.makedev(1,3))), \
             mock.patch.object(bridge.os, 'close') as close:
            with self.assertRaisesRegex(bridge.CompatibilityRuntimeError, 'invalid /dev/null'):
                bridge.require_private_null_device()
            opening.assert_called_once_with('/dev/null', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            close.assert_called_once_with(7)


if __name__ == '__main__':
    unittest.main()
