"""Unexecuted storage incident fixtures; repository policy forbids running them.

Every storage/privilege delegate below is a private stub. No supplied mount path
is probed, and no system manager, device, installed helper or service is used.
"""
from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation
sys.path.pop(0)
require_test_isolation()

import json
import io
from pathlib import PurePosixPath
import shlex
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'


class StorageStagingContractTests(unittest.TestCase):
    def check_snapshot(self, *, overrides=None, missing=None, source=b'#!/bin/sh\nexit 0\n'):
        """The staged contract sees only synthetic metadata and in-memory bytes."""
        report = '/usr/local/libexec/labwc-storage-report'
        commands = {report, '/usr/bin/df', '/usr/bin/findmnt', '/usr/bin/lsblk', '/usr/bin/timeout'}
        changes = overrides or {}

        class SnapshotPath(PurePosixPath):
            def lstat(self):
                if str(self) == missing:
                    raise FileNotFoundError('fixture missing command')
                metadata = {'st_mode': (stat.S_IFREG if str(self) in commands else stat.S_IFDIR) | 0o755,
                            'st_uid': 0, 'st_gid': 0, 'st_nlink': 1, 'st_size': len(source)}
                metadata.update(changes.get(str(self), {}))
                return SimpleNamespace(**metadata)

            def open(self, mode):
                if str(self) != report or mode != 'rb':
                    raise AssertionError('fixture attempted an unowned read')
                return io.BytesIO(source)

        staging = TARGET.parents[1] / 'scripts/desktop/components/target-assets.sh'
        code = staging.read_text().split(
            'run_in_target "verify staged storage report contract" /usr/bin/python3 -I -S -B -c \'\n', 1)[1]
        code = code.split("\n'\n", 1)[0]
        with mock.patch('pathlib.Path', SnapshotPath):
            exec(compile(code, 'storage-staging-fixture', 'exec'), {})

    def test_complete_snapshot_is_accepted_without_probing_storage(self):
        self.check_snapshot()

    def test_missing_or_unsafe_code_is_rejected_before_activation(self):
        report = '/usr/local/libexec/labwc-storage-report'
        for metadata in ({'st_mode': stat.S_IFREG | 0o777}, {'st_uid': 1000},
                         {'st_gid': 1000}, {'st_nlink': 2}, {'st_size': 16385},
                         {'st_mode': stat.S_IFLNK | 0o777}):
            with self.subTest(metadata=metadata), self.assertRaises(SystemExit):
                self.check_snapshot(overrides={report: metadata})
        with self.assertRaises(SystemExit):
            self.check_snapshot(overrides={'/usr/local': {'st_mode': stat.S_IFDIR | 0o777}})
        with self.assertRaises(FileNotFoundError):
            self.check_snapshot(missing='/usr/bin/df')
        with self.assertRaises(SystemExit):
            self.check_snapshot(source=b'#!/bin/sh\n__INSTALLER_UNRESOLVED__\n')


class StorageReportTests(unittest.TestCase):
    def setUp(self):
        private = tempfile.TemporaryDirectory(prefix='storage-report-')
        self.addCleanup(private.cleanup)
        self.root = Path(private.name)
        self.control = self.root / 'control.json'
        self.calls = self.root / 'calls.jsonl'
        self.environment = {'PATH': str(self.root), 'HOME': str(self.root),
                            'TMPDIR': str(self.root), 'LC_ALL': 'C'}
        self.control.write_text('{}')
        self.stub = self.root / 'delegate'
        self.stub.write_text('#!' + sys.executable + ' -IS\n' + f'''
import json, os, pathlib, subprocess, sys
root = pathlib.Path({str(self.root)!r})
control = json.loads((root / 'control.json').read_text())
name = pathlib.Path(sys.argv[0]).name
with (root / 'calls.jsonl').open('a') as output:
    output.write(json.dumps([name, sys.argv[1:], sorted(os.environ)]) + '\\n')
if name == 'timeout':
    assert sys.argv[1:3] == ['--kill-after=2s', '10s']
    if 'timeout_status' in control:
        sys.exit(control['timeout_status'])
    assert pathlib.Path(sys.argv[3]).parent == root
    sys.exit(subprocess.run(sys.argv[3:], env=dict(os.environ), timeout=2).returncode)
if name == 'df':
    # An unrestricted capacity query represents the offline hard NFS mount.
    assert sys.argv[1:] == ['--local', '-hT', '-x', 'tmpfs', '-x', 'devtmpfs']
    print('Filesystem Type Size Used Avail Use% Mounted on\\nUUID=fixture ext4 10G 2G 8G 20% /')
elif name == 'lsblk':
    assert sys.argv[1:] == ['--output', 'NAME,SIZE,TYPE,MOUNTPOINTS']
elif name == 'findmnt':
    assert sys.argv[1:] == ['--kernel', '--list', '--real', '--nocanonicalize',
                           '--output', 'TARGET,SOURCE,FSTYPE']
    print('/srv/offline server:/ nfs')
elif name in ('pkexec', 'sudo', 'systemctl', 'ncdu'):
    sys.exit(99)
elif name == 'id':
    assert sys.argv[1:] == ['-u']
    print('0')
elif name == 'getent':
    assert sys.argv[1:] == ['passwd', '1000']
sys.exit(control.get(name + '_status', 0))
''')
        self.stub.chmod(0o700)
        for name in ('timeout', 'df', 'lsblk', 'findmnt', 'pkexec', 'sudo', 'systemctl',
                     'ncdu', 'id', 'getent', 'labwc-terminal'):
            (self.root / name).write_bytes(self.stub.read_bytes())
            (self.root / name).chmod(0o700)
        source = (TARGET / 'usr/local/libexec/labwc-storage-report').read_text()
        for name in ('timeout', 'df', 'lsblk', 'findmnt'):
            source = source.replace('/usr/bin/' + name, shlex.quote(str(self.root / name)))
        self.report = self.root / 'report'
        self.report.write_text(source)
        self.report.chmod(0o700)

    def invoke(self, control=None, arguments=(), script=None, environment=None):
        script = script or self.report
        if script.parent != self.root or script.is_symlink():
            raise ValueError('fixture command must be a private owned file')
        self.calls.unlink(missing_ok=True)
        self.control.write_text(json.dumps(control or {}))
        result = subprocess.run(['/bin/sh', str(script), *arguments],
                                env={**self.environment, **(environment or {})},
                                stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=5)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        return result, calls

    def test_local_capacity_and_remote_inventory_use_only_nontraversing_delegates(self):
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[0] for call in calls], ['timeout', 'df', 'timeout', 'lsblk', 'timeout', 'findmnt'])
        self.assertIn('Remote filesystem capacity is excluded', result.stdout)
        self.assertIn('server:/ nfs', result.stdout)
        self.assertTrue(all(not set(call[2]) & {'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR',
                                              'SSH_AUTH_SOCK', 'PKEXEC_UID'} for call in calls))

    def test_delegate_failures_and_timeout_status_stop_the_report_without_retry(self):
        for delegate, expected_calls in (('df', 2), ('lsblk', 4), ('findmnt', 6)):
            result, calls = self.invoke({delegate + '_status': 7})
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(len(calls), expected_calls)
        # Mocked timeout/forced-kill outcomes verify propagation, not native cleanup.
        for status in (124, 137):
            result, calls = self.invoke({'timeout_status': status})
            self.assertEqual(result.returncode, status)
            self.assertEqual([call[0] for call in calls], ['timeout'])

    def test_bad_arguments_and_missing_delegate_never_start_a_probe(self):
        result, calls = self.invoke(arguments=('/srv/offline',))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])
        (self.root / 'df').chmod(0o600)
        result, calls = self.invoke()
        self.assertEqual(result.returncode, 127)
        self.assertEqual(calls, [])

    def test_desktop_adapter_preserves_failure_and_never_requests_privilege(self):
        source = (TARGET / 'usr/local/bin/labwc-system-action.tmpl').read_text()
        source = source.replace('/usr/local/libexec/labwc-storage-report', str(self.report))
        client = self.root / 'client'
        client.write_text(source)
        for status in (0, 7, 124, 137):
            result, calls = self.invoke({'df_status': status}, arguments=('--run', 'storage-overview'),
                script=client, environment={'LABWC_SESSION_OWNER': 'desktop',
                                            'XDG_RUNTIME_DIR': '/run/user/1000'})
            self.assertEqual(result.returncode, status, result.stderr)
            self.assertIn('Action finished with status ' + str(status), result.stdout)
            self.assertFalse(set(call[0] for call in calls) & {'pkexec', 'sudo', 'systemctl', 'ncdu'})

    def test_root_adapter_uses_the_same_report_and_preserves_failure(self):
        source = (TARGET / 'usr/local/libexec/labwc-system-action-root').read_text()
        source = source.replace('PATH=/usr/sbin:/usr/bin:/sbin:/bin', 'PATH=' + shlex.quote(str(self.root)))
        source = source.replace('/usr/local/libexec/labwc-storage-report', str(self.report))
        helper = self.root / 'root-adapter'
        helper.write_text(source)
        result, calls = self.invoke({'df_status': 7}, arguments=('storage-overview',),
                                   script=helper, environment={'PKEXEC_UID': '1000'})
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual([call[0] for call in calls], ['id', 'getent', 'timeout', 'df'])
