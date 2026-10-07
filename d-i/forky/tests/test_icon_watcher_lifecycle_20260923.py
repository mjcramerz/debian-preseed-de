"""Exercise only the formatter's own child lifecycle; no Tomat daemon/systemd.

All processes below are temporary Python fixtures. No PID lookup, shared
session, signal broadcast, network, or host policy changes are performed.
"""
from __future__ import annotations
from payload_fixture import read_text as payload_read_text
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
import unittest
from unittest import mock
from test_icon_colors_20260923 import load, TARGET, VALUES, RENDER


class WatcherLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.mod = load('usr/local/libexec/labwc-tomat')
        self.previous = {sig:signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        temporary = tempfile.TemporaryDirectory(prefix='x-icon-watch-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.children = []
        self.Popen = subprocess.Popen

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill(); child.wait(timeout=5)
            if child.stdout: child.stdout.close()
        self.assertEqual({sig:signal.getsignal(sig) for sig in self.previous}, self.previous)

    def child(self, code):
        path = self.directory / 'child.py'
        path.write_text(code)
        return [sys.executable, '-I', str(path)]

    def tracking_popen(self, *args, **kwargs):
        child = self.Popen(*args, **kwargs)
        self.children.append(child)
        return child

    def test_eof_retains_native_exit_status_and_reaps_child(self):
        command = self.child('import json,sys\nprint(json.dumps({"text":"plain", "class":"work"}), flush=True)\nsys.exit(7)\n')
        out = io.StringIO()
        with mock.patch.object(self.mod.subprocess, 'Popen', side_effect=self.tracking_popen) as spawn, contextlib.redirect_stdout(out):
            self.assertEqual(self.mod.watch_status(command, dict(os.environ)), 7)
        self.assertEqual(json.loads(out.getvalue())['text'], 'plain')
        self.assertEqual(self.children[0].returncode, 7)
        self.assertTrue(self.children[0].stdout.closed)
        self.assertTrue(spawn.call_args.kwargs['close_fds'])
        self.assertEqual(spawn.call_args.kwargs['stdin'], subprocess.DEVNULL)
        for key in ('shell','start_new_session','preexec_fn'):
            self.assertNotIn(key, spawn.call_args.kwargs)

    def test_malformed_truncated_and_overlong_json_terminate_only_owned_child(self):
        for literal in (b'invalid\n', b'{}', b'x'*(self.mod.MAX_STATUS+1)+b'\n', b'{"text":"x","class":"invalid"}\n', b'\xff\n'):
            with self.subTest(prefix=repr(literal[:32])):
                command = self.child('import os,time\nos.write(1,'+repr(literal)+')\nos.close(1)\ntime.sleep(60)\n')
                with mock.patch.object(self.mod.subprocess, 'Popen', side_effect=self.tracking_popen), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(self.mod.Error):
                    self.mod.watch_status(command, dict(os.environ))
                self.assertIsNotNone(self.children[-1].poll())
                self.assertTrue(self.children[-1].stdout.closed)

    def test_signal_during_process_creation_is_deferred_until_child_is_owned(self):
        command = self.child('import time\ntime.sleep(60)\n')
        def interrupted_spawn(*args, **kwargs):
            child = self.tracking_popen(*args, **kwargs)
            os.kill(os.getpid(), signal.SIGTERM)
            return child
        with mock.patch.object(self.mod.subprocess, 'Popen', side_effect=interrupted_spawn), self.assertRaises(SystemExit) as raised:
            self.mod.watch_status(command, dict(os.environ))
        self.assertEqual(raised.exception.code, 128+signal.SIGTERM)
        self.assertIsNotNone(self.children[0].poll())
        self.assertTrue(self.children[0].stdout.closed)

    def start_wrapper(self, child_code):
        child = self.directory / 'watch-child.py'
        child.write_text(child_code)
        helper = self.directory / 'labwc-tomat'
        helper.write_text(RENDER(payload_read_text(TARGET/'usr/local/libexec/labwc-tomat'), VALUES))
        wrapper = self.directory / 'wrapper.py'
        wrapper.write_text('import os,runpy,sys\n'
            'm=runpy.run_path('+repr(str(helper))+')\n'
            'try:\n'
            '    sys.exit(m["watch_status"]([sys.executable,"-I",'+repr(str(child))+'],dict(os.environ)))\n'
            'except m["Error"]:\n'
            '    sys.exit(1)\n')
        process = self.Popen([sys.executable,'-I',str(wrapper)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop_wrapper, process)
        return process

    @staticmethod
    def stop_wrapper(process):
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream and not stream.closed: stream.close()

    def line(self, process):
        with selectors.DefaultSelector() as ready:
            ready.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(ready.select(5), 'watch fixture did not emit readiness')
        return process.stdout.readline()

    def test_term_during_blocked_read_reaps_child_even_if_term_is_ignored(self):
        pidfile = self.directory / 'child.pid'
        child = ('import json,os,signal,time\n'
                 'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                 'open('+repr(str(pidfile))+',"w").write(str(os.getpid()))\n'
                 'print(json.dumps({"text":"ready","class":"work"}),flush=True)\n'
                 'time.sleep(60)\n')
        process = self.start_wrapper(child)
        self.assertEqual(json.loads(self.line(process))['text'], 'ready')
        pid = int(payload_read_text(pidfile))
        process.terminate()
        self.assertEqual(process.wait(timeout=8), 128+signal.SIGTERM)
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    def test_closed_output_reaps_exact_child_without_an_interpreter_flush_error(self):
        pidfile = self.directory / 'child.pid'
        child = ('import json,os,time\n'
                 'open('+repr(str(pidfile))+',"w").write(str(os.getpid()))\n'
                 'for i in range(200):\n'
                 '    print(json.dumps({"text":"ready","class":"work"}),flush=True)\n'
                 '    time.sleep(0.03)\n')
        process = self.start_wrapper(child)
        self.assertEqual(json.loads(self.line(process))['text'], 'ready')
        pid = int(payload_read_text(pidfile))
        process.stdout.close()
        self.assertEqual(process.wait(timeout=6), 0)
        self.assertNotIn(b'BrokenPipeError', process.stderr.read())
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    def test_missing_executable_restores_signal_handlers(self):
        with self.assertRaises(FileNotFoundError):
            self.mod.watch_status([str(self.directory/'missing')], dict(os.environ))

    def test_apparmor_change_is_limited_to_exact_peer_and_required_signals(self):
        text = payload_read_text(TARGET/'etc/apparmor.d/tomat')
        parent = text.split('profile labwc-tomat ',1)[1].split('\n}',1)[0]
        rules = [line.strip() for line in parent.splitlines() if 'signal ' in line and 'peer=tomat' in line]
        self.assertEqual(rules, ['signal (send) set=(term, kill) peer=tomat,',
                                 'signal (receive) set=(chld) peer=tomat,'])
        self.assertNotRegex(parent, r'signal \(send\)(?:\s+set=\([^)]*\))?\s*,')


if __name__ == '__main__':
    unittest.main()
