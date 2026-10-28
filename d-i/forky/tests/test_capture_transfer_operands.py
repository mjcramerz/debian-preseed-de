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
        self.assertTrue(source.startswith('#!/usr/bin/python3 -IB'))
        for contract in ('def recording_worker', 'path.is_file()', 'path.stat().st_size > 0',
                         'Screen recording failed', 'return worker_status'):
            self.assertIn(contract, source)

    def test_intentional_stop_still_saves_a_valid_artifact(self):
        source = (TARGET / 'usr/local/bin/labwc-capture.tmpl').read_text()
        for contract in ('process.send_signal(signal.SIGINT)', 'signal.signal(signal.SIGTERM',
                         'wf-recorder', 'ffprobe'):
            self.assertIn(contract, source)
