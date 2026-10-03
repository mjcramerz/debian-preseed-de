#!/usr/bin/env python3
"""Exercise the actual desktop chmod block without touching a live account.

find traversal and chmod are real. Mixed-ownership tests replace only find's
UID predicate because some containers cannot create foreign-UID fixtures. The
chmod guard models EPERM on protected paths; no immutable flag is cleared.
"""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/desktop/components/user-config.sh'
SHELLS = [['/bin/sh']]
if shutil.which('busybox'):
    SHELLS.append([shutil.which('busybox'), 'sh'])


class HomePermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='home-permissions-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root/'home/mcramer'
        self.units = self.home/'.config/systemd/user'
        self.units.mkdir(parents=True)
        self.data = self.home/'private data.txt'
        self.data.write_text('private account data\n')
        self.program = self.home/'account-program'
        self.program.write_text('#!/bin/sh\nexit 0\n')
        self.unit = self.units/'fixture.service'
        self.unit.write_text('[Service]\nExecStart=/bin/true\n')
        self.bin = self.root/'bin'
        self.bin.mkdir()
        self.log = self.root/'chmod.jsonl'
        self.env = dict(os.environ, PATH=str(self.bin)+':'+os.environ.get('PATH', '/usr/bin:/bin'),
                        PERMISSION_TEST_LOG=str(self.log), PERMISSION_TEST_DENY='[]',
                        PERMISSION_TEST_FOREIGN='[]', PERMISSION_TEST_FIND=shutil.which('find'),
                        PERMISSION_TEST_CHMOD=shutil.which('chmod'))
        text = SOURCE.read_text()
        start = text.index('\nfind ', text.index('if command -v /usr/local/bin/labwc-sync-application-launchers'))
        self.block = text[start+1:text.index('\nzsh_path=', start)]
        guard = '''import json, os, sys
from pathlib import Path
with open(os.environ['PERMISSION_TEST_LOG'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
denied = [Path(p) for p in json.loads(os.environ['PERMISSION_TEST_DENY'])]
if any(Path(p) == root or root in Path(p).parents for p in sys.argv[2:] for root in denied):
    print('chmod: changing permissions: Operation not permitted', file=sys.stderr)
    raise SystemExit(1)
os.execv(os.environ['PERMISSION_TEST_CHMOD'], ['chmod', *sys.argv[1:]])
'''
        self.write_tool('chmod', guard)
        self.reset_private_modes()

    def write_tool(self, name, program):
        path = self.bin/name
        path.write_text('#!'+sys.executable+'\n'+program)
        path.chmod(0o700)

    def reset_private_modes(self):
        for path in (self.home, self.home/'.config', self.home/'.config/systemd', self.units):
            path.chmod(0o755)
        self.data.chmod(0o644)
        self.program.chmod(0o755)
        self.unit.chmod(0o755)
        self.log.unlink(missing_ok=True)

    def simulate_foreign_ownership(self, paths):
        # Translate just -uid into an equivalent fixture ownership predicate.
        # Preserve find's real -P/-xdev, boolean operators, prune and exec actions.
        self.env['PERMISSION_TEST_FOREIGN'] = json.dumps([str(p) for p in paths])
        self.write_tool('find', '''import json, os, sys
foreign = json.loads(os.environ['PERMISSION_TEST_FOREIGN'])
argv = []
index = 1
while index < len(sys.argv):
    if sys.argv[index] == '-uid':
        assert sys.argv[index+1] == '1000'
        predicate = ['(']
        for path in foreign:
            if len(predicate) > 1:
                predicate.append('-a')
            predicate.extend(['!', '-path', path])
        predicate.append(')')
        argv.extend(predicate)
        index += 2
    else:
        argv.append(sys.argv[index])
        index += 1
os.execv(os.environ['PERMISSION_TEST_FIND'], ['find', *argv])
''')

    def run_block(self, shell, uid=None):
        program = 'set -eu\naccount_home=$1\nuid=$2\n'+self.block+'\nprintf "completed\\n"\n'
        return subprocess.run([*shell, '-c', program, 'permission-test', str(self.home),
                               str(os.geteuid() if uid is None else uid)],
                              env=self.env, capture_output=True, text=True, timeout=20)

    def mode(self, path):
        return stat.S_IMODE(path.lstat().st_mode)

    def assert_private_modes(self):
        for path in (self.home, self.home/'.config', self.home/'.config/systemd', self.units):
            self.assertEqual(self.mode(path), 0o700, path)
        self.assertEqual(self.mode(self.data), 0o600)
        self.assertEqual(self.mode(self.program), 0o700)
        self.assertEqual(self.mode(self.unit), 0o600, 'systemd units are data, never executables')

    def test_account_data_programs_and_units_keep_their_private_contract(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.reset_private_modes()
                result = self.run_block(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'completed\n')
                self.assert_private_modes()

    def test_root_managed_sharing_and_custom_parents_are_pruned_before_chmod(self):
        parents = [self.home/'Sharing', self.home/'ServerShare', self.home/'ClientShare']
        for parent in parents:
            for endpoint in ('nfs-client', 'nested/nfs-server'):
                (parent/endpoint).mkdir(parents=True)
                (parent/endpoint).chmod(0o000)
            parent.chmod(0o755)
        before = {p:self.mode(p) for parent in parents for p in [parent, *parent.rglob('*')]}
        self.simulate_foreign_ownership(parents)
        self.env['PERMISSION_TEST_DENY'] = json.dumps([str(p) for p in parents])
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.reset_private_modes()
                result = self.run_block(shell, uid=1000)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'completed\n')
                self.assert_private_modes()
                self.assertEqual({p:self.mode(p) for p in before}, before)
                calls = [json.loads(line) for line in self.log.read_text().splitlines()]
                self.assertTrue(calls)
                self.assertFalse(any(Path(p) == root or root in Path(p).parents
                                     for call in calls for p in call[1:] for root in parents))

    def test_foreign_files_and_unit_dropins_are_not_normalized(self):
        foreign_file = self.home/'root-managed.conf'
        foreign_file.write_text('root policy\n'); foreign_file.chmod(0o640)
        dropin = self.units/'root-managed.service.d'
        dropin.mkdir(); dropin.chmod(0o750)
        child = dropin/'policy.conf'
        child.write_text('[Service]\n'); child.chmod(0o640)
        foreign_unit = self.units/'root-managed.service'
        foreign_unit.write_text('[Service]\n'); foreign_unit.chmod(0o644)
        self.simulate_foreign_ownership([foreign_file, dropin, foreign_unit])
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_block(shell, uid=1000)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mode(foreign_file), 0o640)
                self.assertEqual(self.mode(dropin), 0o750)
                self.assertEqual(self.mode(child), 0o640, 'a foreign parent must prune its owned descendants')
                self.assertEqual(self.mode(foreign_unit), 0o644)
                self.assert_private_modes()

    def test_foreign_uid_tree_is_pruned_with_real_find_metadata(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_block(shell, uid=os.geteuid()+1)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mode(self.home), 0o755)
                self.assertEqual(self.mode(self.data), 0o644)
                self.assertEqual(self.mode(self.unit), 0o755)
                self.assertFalse(self.log.exists())

    def test_physical_walk_does_not_follow_links_outside_home(self):
        outside = self.root/'outside'
        outside.mkdir(); outside.chmod(0o755)
        exported = outside/'data'
        exported.write_text('external\n'); exported.chmod(0o644)
        (self.home/'linked-export').symlink_to(outside, target_is_directory=True)
        (self.units/'linked.service').symlink_to(exported)
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_block(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mode(outside), 0o755)
                self.assertEqual(self.mode(exported), 0o644)
                self.assertEqual(exported.read_text(), 'external\n')

    def test_account_chmod_failure_still_aborts_installation(self):
        self.env['PERMISSION_TEST_DENY'] = json.dumps([str(self.data)])
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_block(shell)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Operation not permitted', result.stderr)
                self.assertNotIn('completed', result.stdout)

    def test_real_foreign_parent_prunes_same_owner_descendants(self):
        sharing = self.home/'Sharing'
        sharing.mkdir(); sharing.chmod(0o755)
        endpoint = sharing/'nfs-client'
        endpoint.mkdir(); endpoint.chmod(0o000)
        try:
            os.chown(sharing, os.geteuid()+1, -1)
        except OSError as error:
            if error.errno in (errno.EINVAL, errno.EPERM, errno.EACCES):
                self.skipTest('runtime cannot create a foreign-UID ownership fixture')
            raise
        self.env['PERMISSION_TEST_DENY'] = json.dumps([str(sharing)])
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_block(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.mode(sharing), 0o755)
                self.assertEqual(self.mode(endpoint), 0o000)
                self.assert_private_modes()


if __name__ == '__main__':
    unittest.main()
