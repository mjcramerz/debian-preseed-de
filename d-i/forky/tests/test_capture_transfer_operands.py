"""Fixture recorders and scp argv capture; never contacts a desktop or network."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'


class CaptureTransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='capture-transfer-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = {'PATH': str(self.bin) + ':/usr/bin:/bin', 'HOME': str(self.root),
                    'USER': 'fixture', 'LC_ALL': 'C', 'FIXTURE_ARGV': str(self.root / 'argv')}
        scp = self.bin / 'scp'
        scp.write_text('#!/usr/bin/python3 -IB\nimport json,os,sys\n'
                       'open(os.environ["FIXTURE_ARGV"],"w").write(json.dumps(sys.argv[1:]))\n')
        scp.chmod(0o755)

    def test_dns_ipv4_ipv6_scoped_ipv6_and_colon_dash_space_local_paths(self):
        for host in ('example.test', '192.0.2.1', '2001:db8::1', 'fe80::1%enp1s0'):
            for local in ('host:file', '-leading', 'space name'):
                for action in ('send', 'retrieve'):
                    with self.subTest(host=host, local=local, action=action):
                        (self.root / local).touch()
                        option = '--dest-ip' if action == 'send' else '--remote-ip'
                        operands = [local, '/remote/file'] if action == 'send' else ['/remote/file', local]
                        result = subprocess.run(['/bin/sh', str(TARGET / 'usr/local/bin' / ('xssh-' + action)),
                                                 option, host, '--port', '22', '--', *operands],
                                                cwd=self.root, env=self.env, capture_output=True, timeout=5)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        argv = json.loads((self.root / 'argv').read_text())
                        remote = 'fixture@' + ('[' + host + ']' if ':' in host else host) + ':/remote/file'
                        self.assertEqual(argv, ['-r', '-P', '22', *(['./' + local, remote] if action == 'send'
                                                                 else [remote, './' + local])])

    def test_zero_recorder_requires_nonempty_artifact(self):
        source = (TARGET / 'usr/local/bin/labwc-capture.tmpl').read_text()
        begin = source.index('  recording_stopping=0', source.index('record_worker()'))
        end = source.index('\n}\n', begin)
        # Exercise the actual worker's signal/wait/artifact/status tail, with
        # notification and recording setup supplied by this fixture only.
        worker = source[begin:end]
        recorder = self.bin / 'recorder'
        recorder.write_text('#!/bin/sh\ncase $1 in missing) ;; empty) : > "$2";; valid) printf video > "$2";; esac\nexit 0\n')
        recorder.chmod(0o755)
        for mode in ('missing', 'empty', 'valid'):
            with self.subTest(mode=mode):
                output = self.root / (mode + '.mkv')
                setup = 'set -eu\nnotify_user() { :; }\nrecording_path=$1\nRECORDING_LOG=$2\nshift 2\n'
                result = subprocess.run(['/bin/sh', '-c', setup + worker, 'capture-fixture',
                                         str(output), str(self.root / 'record.log'), str(recorder), mode, str(output)],
                                        env=self.env, capture_output=True, timeout=5)
                self.assertEqual(result.returncode == 0, mode == 'valid', result.stderr)
                self.assertEqual(output.exists(), mode == 'valid')

    def test_intentional_stop_still_saves_a_valid_artifact(self):
        source = (TARGET / 'usr/local/bin/labwc-capture.tmpl').read_text()
        begin = source.index('  recording_stopping=0', source.index('record_worker()'))
        worker = source[begin:source.index('\n}\n', begin)]
        recorder = self.bin / 'stop-recorder'
        recorder.write_text('#!/usr/bin/python3 -IB\nimport pathlib,signal,sys\n'
                            'signal.signal(signal.SIGINT, lambda *_: sys.exit(130))\n'
                            'signal.alarm(3)\npathlib.Path(sys.argv[1]).write_bytes(b"video")\n'
                            'pathlib.Path(sys.argv[2]).touch()\nsignal.pause()\n')
        recorder.chmod(0o755)
        output, ready = self.root / 'stopped.mkv', self.root / 'ready'
        setup = 'set -eu\nnotify_user() { :; }\nrecording_path=$1\nRECORDING_LOG=$2\nshift 2\n'
        process = subprocess.Popen(['/bin/sh', '-c', setup + worker, 'capture-fixture', str(output),
                                    str(self.root / 'record.log'), str(recorder), str(output), str(ready)],
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 1
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            process.send_signal(signal.SIGTERM)
            _out, error = process.communicate(timeout=4)
            self.assertEqual(process.returncode, 0, error)
            self.assertEqual(output.read_bytes(), b'video')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=4)
