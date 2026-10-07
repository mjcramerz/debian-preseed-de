#!/usr/bin/env python3
"""Follow-up incident regressions: disposable processes, never target services."""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists
from payload_fixture import python_library
from payload_fixture import read_text as payload_read_text

import contextlib
import io
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
PACKAGE = python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')
sys.path.insert(0, str(PACKAGE))
from labwc_managed_app import cli, dbus_proxy, profiles, runtime

RUNNER = '''import os, sys
from labwc_managed_app import cli, dbus_proxy, profiles, runtime
# Shorten the production deadline for fixture processes only.
cli._SPOTIFY_STOP_SECONDS = 0.25
cli._SPOTIFY_DRAIN_SECONDS = 0.1
raise SystemExit(cli._run_spotify([sys.executable, '-B', '-c', sys.argv[1]], dict(os.environ)))
'''


class SpotifySupervisionTests(unittest.TestCase):
    def fixture(self, code, **kwargs):
        return subprocess.Popen(payload_installed_argv([sys.executable, '-B', '-c', RUNNER, code]),
                                env=dict(os.environ, PYTHONPATH=str(PACKAGE)),
                                start_new_session=True, **kwargs)

    def cleanup(self, process):
        # Include fixture descendants, even after their direct parent exits.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)

    def wait_file(self, path):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if payload_source_exists(path) and payload_read_text(path):
                return
            time.sleep(0.01)
        self.fail('fixture did not become ready')

    def test_blocked_output_cannot_prevent_stop_escalation(self):
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'child.pid'
            code = f'''import os, signal
signal.signal(signal.SIGTERM, signal.SIG_IGN)
open({str(pidfile)!r}, 'w').write(str(os.getpid()))
while True: os.write(1, b'x' * 65536)
'''
            process = self.fixture(code, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.wait_file(pidfile)
                # Deliberately do not read stdout: model a full journal socket.
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(5))
                time.sleep(0.1)
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=3), 137)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(payload_read_text(pidfile)), 0)
            finally:
                self.cleanup(process)

    def test_normal_large_output_is_forwarded_without_loss(self):
        code = 'import os; os.write(1, b"x" * 2_000_000); os.write(2, b"stderr-tail\\n")'
        process = self.fixture(code, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout, b'x' * 2_000_000 + b'stderr-tail\n')
        finally:
            self.cleanup(process)

    def test_clean_child_that_closes_stdout_early_is_reaped(self):
        code = 'import os, time; os.close(1); os.close(2); time.sleep(0.1); raise SystemExit(7)'
        process = self.fixture(code, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 7, stderr)
            self.assertEqual(stdout, b'')
        finally:
            self.cleanup(process)

    def test_sigterm_handoff_text_cannot_mask_cancellation(self):
        code = '''import signal, time
signal.signal(signal.SIGTERM, lambda *_: exit(1))
print("Opening in existing browser session.", flush=True)
time.sleep(20)
'''
        process = self.fixture(code, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(5))
                self.assertEqual(process.stdout.readline(), b'Opening in existing browser session.\n')
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 1, stderr)
        finally:
            self.cleanup(process)

    def test_real_file_output_and_descriptor_flags_are_preserved(self):
        for blocking in (False, True):
            with self.subTest(blocking=blocking), tempfile.TemporaryFile() as output:
                os.set_blocking(output.fileno(), blocking)
                with mock.patch.object(cli.sys, 'stdout', types.SimpleNamespace(buffer=output)), \
                     mock.patch.object(cli, 'emit'):
                    result = cli._run_spotify([sys.executable, '-B', '-c',
                        'print("Opening in existing browser session."); raise SystemExit(1)'], dict(os.environ))
                self.assertEqual(result, 0)
                self.assertEqual(os.get_blocking(output.fileno()), blocking)
                output.seek(0)
                self.assertEqual(output.read(), b'Opening in existing browser session.\n')

    def test_output_error_kills_and_reaps_child_and_restores_handlers(self):
        class BrokenOutput(io.BytesIO):
            def write(self, data):
                raise BrokenPipeError('fixture consumer disappeared')
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'child.pid'
            code = f'''import os, time
open({str(pidfile)!r}, 'w').write(str(os.getpid()))
print('READY', flush=True)
time.sleep(20)
'''
            signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
            previous = {sig: signal.getsignal(sig) for sig in signals}
            with mock.patch.object(cli.sys, 'stdout', types.SimpleNamespace(buffer=BrokenOutput())):
                with self.assertRaises(BrokenPipeError):
                    cli._run_spotify([sys.executable, '-B', '-c', code], dict(os.environ))
            self.assertEqual(previous, {sig: signal.getsignal(sig) for sig in signals})
            with self.assertRaises(ProcessLookupError):
                os.kill(int(payload_read_text(pidfile)), 0)

    def test_exact_handoff_on_real_pipe(self):
        process = self.fixture('print("Opening in existing browser session."); raise SystemExit(1)',
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout, b'Opening in existing browser session.\n')
        finally:
            self.cleanup(process)

    def test_sigint_and_hup_are_forwarded(self):
        for stop_signal in (signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=stop_signal), tempfile.TemporaryDirectory() as temporary:
                ready = Path(temporary) / 'ready'
                code = f'''import os, signal, time
signal.signal({int(stop_signal)}, lambda *_: os._exit(128 + {int(stop_signal)}))
open({str(ready)!r}, 'w').write('ready')
time.sleep(20)
'''
                process = self.fixture(code, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.wait_file(ready)
                    process.send_signal(stop_signal)
                    _, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 128 + stop_signal, stderr)
                finally:
                    self.cleanup(process)


@unittest.skipUnless(all(shutil.which(tool) for tool in ('dbus-daemon', 'busctl', 'xdg-dbus-proxy')),
                     'live filtered-bus test requires preinstalled dbus-daemon, busctl and xdg-dbus-proxy')
class TutaLiveProxyTests(unittest.TestCase):
    def test_real_proxy_allows_only_the_configured_tray_name(self):
        # Never connect to the host session/system bus or activate applications.
        # This isolated bus has no service directories or activation entries.
        with tempfile.TemporaryDirectory(prefix='tuta-bus-fixture-') as temporary:
            root = Path(temporary)
            address = 'unix:path=' + str(root / 'upstream-bus')
            config = root / 'bus.conf'
            config.write_text('<busconfig><type>session</type><listen>' + address + '</listen>'
                '<auth>EXTERNAL</auth><policy context="default">'
                '<allow user="*"/><allow own="*"/><allow send_destination="*"/>'
                '<allow receive_sender="*"/></policy></busconfig>')
            daemon = subprocess.Popen(payload_installed_argv([shutil.which('dbus-daemon'), '--nofork', '--nopidfile',
                '--print-address=1', '--config-file=' + str(config)]),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            proxy = lifecycle = proxy_socket = None
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(daemon.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(5), 'private fixture bus did not become ready')
                self.assertTrue(daemon.stdout.readline().decode().startswith(address))
                # Production validation deliberately permits only the real user
                # bus path. Redirect that one check to this private test bus.
                operations = dbus_proxy.ProxyRuntime(
                    fail=self.fail,
                    require_root_owned_executable=runtime.require_root_owned_executable,
                    managed_subprocess_environment=lambda: dict(os.environ),
                    validate_session_bus_address=lambda value: address if value == address else self.fail(value),
                )
                sandbox = profiles.PERSISTENT_SANDBOX_CONFIG['tutanota']
                with mock.patch.dict(os.environ, {'DBUS_SESSION_BUS_ADDRESS': address}):
                    proxy, proxy_socket, lifecycle = dbus_proxy.start_session_bus_proxy(
                        str(root), sandbox['dbus_names'], sandbox['dbus_own_names'],
                        required=True, runtime=operations)
                dbus_proxy.require_running_dbus_proxy(proxy, proxy_socket, runtime=operations)
                def request(name):
                    return subprocess.run(payload_installed_argv([shutil.which('busctl'), '--timeout=2s',
                        '--address=unix:path=' + proxy_socket, 'call', 'org.freedesktop.DBus',
                        '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'RequestName', 'su', name, '0']),
                        capture_output=True, text=True, timeout=5)
                allowed = request('org.freedesktop.StatusNotifierItem-2-1')
                self.assertEqual(allowed.returncode, 0, allowed.stderr)
                self.assertEqual(allowed.stdout.strip(), 'u 1')
                for name in ('org.kde.StatusNotifierWatcher', 'org.freedesktop.secrets',
                             'org.freedesktop.Notifications', 'org.freedesktop.StatusNotifierItem-2-2'):
                    with self.subTest(forbidden_name=name):
                        denied = request(name)
                        self.assertNotEqual(denied.returncode, 0, denied.stdout)
                        self.assertRegex(denied.stderr.lower(), r'denied|not allowed')
            finally:
                diagnostics = dbus_proxy.stop_dbus_proxy(proxy, lifecycle, proxy_socket)
                daemon.terminate()
                try:
                    daemon.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.communicate(timeout=3)
            self.assertEqual(proxy.returncode, 0, diagnostics)
            self.assertFalse(payload_source_exists(Path(proxy_socket)))


if __name__ == '__main__':
    unittest.main()
