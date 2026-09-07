#!/usr/bin/env python3
"""Actual uid-drop, runtime isolation, process teardown and standalone tests.

The real standalone helper's idempotent path uses a local version fixture, not
an external download. No account is created and /run/user is never modified.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
os.environ["INSTALLER_SOURCE_LIBRARY"] = str(FORKY / "scripts/common/source.sh")
SCRIPT = FORKY / 'scripts/late/codex-installer-session.py'
STANDALONE = FORKY / 'hooks/target/usr/local/bin/codex-standalone-install'


def load_module():
    spec = importlib.util.spec_from_file_location('codex_installer_session', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alive(pid):
    try:
        state = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()[0]
        return state != 'Z'
    except FileNotFoundError:
        return False


@unittest.skipUnless(os.geteuid() == 0, 'requires root to test real uid/gid dropping')
class CodexSessionTests(unittest.TestCase):
    def setUp(self):
        self.previous_umask = os.umask(0o022)
        self.addCleanup(os.umask, self.previous_umask)
        self.temp = tempfile.TemporaryDirectory(prefix='codex-session-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o755)
        base = pwd.getpwnam('nobody')
        self.home = self.root / 'home'
        self.home.mkdir(mode=0o700)
        os.chown(self.home, base.pw_uid, base.pw_gid)
        self.account = pwd.struct_passwd((base.pw_name, base.pw_passwd, base.pw_uid,
            base.pw_gid, base.pw_gecos, str(self.home), '/bin/sh'))
        self.parent = self.root / 'runtime'
        self.helper = self.root / 'installer'
        self.module = load_module()
        self.patch = mock.patch.object(self.module.pwd, 'getpwnam', return_value=self.account)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.args = [self.account.pw_name, str(self.home), str(self.helper), '1.2.3',
                     'https://chatgpt.com/codex/install.sh', '1048576',
                     str(self.home / 'codex/usr/home'), str(self.home / 'codex/packages')]

    def write_helper(self, body):
        self.helper.write_text('#!/bin/sh\nset -eu\n' + body)
        self.helper.chmod(0o755)

    def run_installer(self, timeout=5):
        return self.module.main(self.args, runtime_parent=self.parent, timeout=timeout)

    def assert_clean(self):
        entries = list(self.parent.iterdir())
        self.assertEqual([p.name for p in entries], [f'{self.account.pw_uid}.lock'])
        self.assertEqual(stat.S_IMODE(entries[0].stat().st_mode), 0o600)
        self.assertEqual(entries[0].stat().st_uid, 0)
        self.assertEqual(stat.S_IMODE(self.parent.stat().st_mode), 0o755)

    def test_actual_uid_drop_and_private_runtime_cleanup(self):
        self.write_helper('''
/usr/bin/python3 - <<'INNER'
import os, json, stat
with open(os.environ['HOME'] + '/receipt', 'w') as stream:
    json.dump({'uid': os.geteuid(), 'gid': os.getegid(),
      'runtime': os.environ['XDG_RUNTIME_DIR'], 'tmp': os.environ['TMPDIR'],
      'mode': stat.S_IMODE(os.stat(os.environ['XDG_RUNTIME_DIR']).st_mode),
      'owner': os.stat(os.environ['XDG_RUNTIME_DIR']).st_uid,
      'secret': os.environ.get('SHOULD_NOT_LEAK')}, stream)
INNER
''')
        with mock.patch.dict(os.environ, {'SHOULD_NOT_LEAK': 'parent-secret'}):
            self.assertEqual(self.run_installer(), 0)
        receipt = json.loads((self.home / 'receipt').read_text())
        self.assertEqual(receipt['uid'], self.account.pw_uid)
        self.assertEqual(receipt['gid'], self.account.pw_gid)
        self.assertEqual(receipt['mode'], 0o700)
        self.assertEqual(receipt['owner'], self.account.pw_uid)
        self.assertEqual(receipt['tmp'], receipt['runtime'])
        self.assertTrue(receipt['runtime'].startswith(str(self.parent) + '/'))
        self.assertIsNone(receipt['secret'])
        self.assertFalse(Path(receipt['runtime']).exists())
        self.assert_clean()

    def test_helper_in_deployed_root_owned_sticky_group_directory(self):
        os.chown(self.root, 0, self.account.pw_gid)
        self.root.chmod(0o3770)
        self.write_helper('printf success > "$HOME/receipt"\n')
        self.assertEqual(self.run_installer(), 0)
        self.assertEqual((self.home / 'receipt').read_text(), 'success')
        self.assert_clean()

    def test_child_exit_status_propagates_and_runtime_is_removed(self):
        self.write_helper('exit 37\n')
        self.assertEqual(self.run_installer(), 37)
        self.assert_clean()

    def test_private_runtime_is_unique_and_lock_inode_is_persistent(self):
        self.write_helper('printf "%s\\n" "$XDG_RUNTIME_DIR" >> "$HOME/receipt"\n')
        self.assertEqual(self.run_installer(), 0)
        inode = (self.parent / f'{self.account.pw_uid}.lock').stat().st_ino
        self.assertEqual(self.run_installer(), 0)
        self.assertEqual((self.parent / f'{self.account.pw_uid}.lock').stat().st_ino, inode)
        a, b = (self.home / 'receipt').read_text().splitlines()
        self.assertNotEqual(a, b)
        self.assert_clean()

    def test_concurrent_account_installation_rejected(self):
        self.write_helper('exit 0\n')
        parent = self.module.open_runtime_parent(self.parent)
        lock = self.module.lock_account(parent, self.account.pw_uid)
        try:
            with self.assertRaisesRegex(RuntimeError, 'another Codex installer'):
                self.run_installer()
        finally:
            os.close(lock)
            os.close(parent)
        self.assert_clean()

    def test_user_owned_helper_rejected_before_execution(self):
        self.write_helper('touch "$HOME/receipt"\n')
        os.chown(self.helper, self.account.pw_uid, self.account.pw_gid)
        with self.assertRaisesRegex(ValueError, 'root-owned'):
            self.run_installer()
        self.assertFalse((self.home / 'receipt').exists())

    def test_group_writable_nonsticky_helper_parent_rejected(self):
        self.write_helper('exit 0\n')
        self.root.chmod(0o775)
        with self.assertRaisesRegex(ValueError, 'root-owned'):
            self.run_installer()

    def test_indirect_runtime_parent_rejected(self):
        self.write_helper('exit 0\n')
        self.parent.symlink_to(self.home, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_installer()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_wrong_home_rejected(self):
        self.write_helper('exit 0\n')
        self.args[1] = str(self.root)
        with self.assertRaisesRegex(ValueError, 'HOME must match'):
            self.run_installer()

    def test_missing_account_has_actionable_error(self):
        self.write_helper('exit 0\n')
        with mock.patch.object(self.module.pwd, 'getpwnam', side_effect=KeyError('missing')):
            with self.assertRaisesRegex(ValueError, 'does not exist'):
                self.run_installer()

    def test_leftover_child_is_terminated_on_success(self):
        self.write_helper('sleep 60 &\nprintf "%s\\n" "$!" > "$HOME/child.pid"\nexit 0\n')
        with mock.patch.object(self.module, 'STOP_TIMEOUT', 0.4):
            self.assertEqual(self.run_installer(), 0)
        self.assertFalse(alive(int((self.home / 'child.pid').read_text())))
        self.assert_clean()

    def test_deadline_kills_term_ignoring_process_group(self):
        self.write_helper('''
trap '' TERM
sleep 60 &
printf '%s %s\\n' "$$" "$!" > "$HOME/children"
wait
''')
        start = time.monotonic()
        with mock.patch.object(self.module, 'STOP_TIMEOUT', 0.3):
            self.assertEqual(self.run_installer(timeout=0.3), 124)
        self.assertLess(time.monotonic() - start, 4)
        for pid in map(int, (self.home / 'children').read_text().split()):
            self.assertFalse(alive(pid), pid)
        self.assert_clean()

    def test_repeated_signals_stop_child_and_clean_runtime(self):
        self.write_helper('''
trap '' TERM
sleep 60 &
printf '%s %s\\n' "$$" "$!" > "$HOME/children"
wait
''')
        driver = self.root / 'driver.py'
        driver.write_text(f'''import importlib.util, pwd, pathlib, sys
spec = importlib.util.spec_from_file_location('fixture', {str(SCRIPT)!r})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
account = pwd.struct_passwd({tuple(self.account)!r})
m.pwd.getpwnam = lambda name: account
m.STOP_TIMEOUT = 0.5
sys.exit(m.main({self.args!r}, runtime_parent=pathlib.Path({str(self.parent)!r}), timeout=5))
''')
        process = subprocess.Popen([sys.executable, '-B', str(driver)], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 4
            while not (self.home / 'children').exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.home / 'children').exists())
            process.send_signal(signal.SIGTERM)
            time.sleep(0.08)
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stderr)
            for pid in map(int, (self.home / 'children').read_text().split()):
                self.assertFalse(alive(pid), pid)
            self.assert_clean()
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)

    def test_real_standalone_idempotent_path_needs_no_login_runtime(self):
        self.helper.write_text(STANDALONE.read_text())
        self.helper.chmod(0o755)
        codex_root = self.home / 'codex'
        codex_home = codex_root / 'usr/home'
        packages = codex_root / 'packages'
        binary = packages / 'standalone/releases/1.2.3/bin/codex'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nprintf "codex-cli 1.2.3\\n"\n')
        binary.chmod(0o755)
        (packages / 'standalone/current').symlink_to('releases/1.2.3')
        codex_home.mkdir(parents=True)
        (codex_home / 'packages').symlink_to(packages)
        profile = self.home / '.profile.d/71-devops-de.sh'
        profile.parent.mkdir()
        profile.write_text('devops_de_apply_environment() {\n' +
            f' CODEX_HOME={shlex.quote(str(codex_home))}\n' +
            ' XDG_RUNTIME_DIR=/run/user/1000\n TMPDIR=/run/user/1000\n' +
            ' export CODEX_HOME XDG_RUNTIME_DIR TMPDIR\n}\n')
        profile.chmod(0o644)
        for path in self.home.rglob('*'):
            os.chown(path, self.account.pw_uid, self.account.pw_gid, follow_symlinks=False)
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)
        self.assertEqual(self.run_installer(), 0)
        self.assertEqual(self.run_installer(), 0)
        self.assertEqual((codex_home / 'packages').readlink(), packages)
        self.assert_clean()


class CodexLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codex-layout-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake_bin = self.root / 'bin'
        self.fake_bin.mkdir()
        self.codex_root = self.root / 'data/codex'
        self.log_dir = self.codex_root / 'log'
        self.sqlite_home = self.codex_root / 'sqlite'
        self.runtime_root = self.codex_root / 'runtime'
        self.account = pwd.getpwuid(os.getuid()).pw_name

        self.write_command('getent', '''
if [ "$1" = group ] && [ "$2" = devops ]; then
  printf 'devops:x:%s:\\n' "$TEST_GID"
  exit 0
fi
exec /usr/bin/getent "$@"
''')
        self.write_command('install', '''
[ "$1" = -d ] || exec /usr/bin/install "$@"
shift
mode=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -m) mode=$2; shift 2 ;;
    -o|-g) shift 2 ;;
    --) shift; break ;;
    -*) exit 2 ;;
    *) break ;;
  esac
done
[ -n "$mode" ]
for destination in "$@"; do
  mkdir -p -- "$destination"
  chmod "$mode" "$destination"
done
''')
        self.write_command('stat', '''
path=
for argument in "$@"; do path=$argument; done
mode=$(/usr/bin/stat -c %a -- "$path")
case "$path" in
  "$TEST_CODEX_ROOT")
    if [ -n "${TEST_CODEX_ROOT_STAT:-}" ]; then
      printf '%s\\n' "$TEST_CODEX_ROOT_STAT"
      exit 0
    fi
    printf '0:%s:%s\\n' "$TEST_GID" "$mode"
    ;;
  "$TEST_CODEX_ROOT/share"|"$TEST_CODEX_ROOT/share/bin"|"$TEST_CODEX_ROOT/lib")
    printf '0:0:%s\\n' "$mode"
    ;;
  *)
    printf '%s:%s:%s\\n' "$TEST_UID" "$TEST_GID" "$mode"
    ;;
esac
''')

        devops = (FORKY / 'scripts/late/devops.sh').read_text()
        layout = devops.split('devops_prepare_codex_layout() {', 1)[1].split(
            '\n}\n\ndevops_apply_codex_tmpfiles() {', 1
        )[0]
        self.script = f'''\
set -eu
ACCOUNT_USERNAME=$TEST_ACCOUNT_USERNAME
DEVOPS_CODEX_ROOT=$TEST_CODEX_ROOT
DEVOPS_CODEX_LOG_DIR=$TEST_CODEX_LOG_DIR
DEVOPS_CODEX_SQLITE_HOME=$TEST_CODEX_SQLITE_HOME
DEVOPS_CODEX_RUNTIME_ROOT=$TEST_CODEX_RUNTIME_ROOT
run_in_target() {{
  shift
  "$@"
}}
devops_prepare_codex_layout() {{
{layout}
}}
'''
        self.env = dict(
            os.environ,
            PATH=f'{self.fake_bin}:/usr/bin:/bin',
            TEST_ACCOUNT_USERNAME=self.account,
            TEST_CODEX_ROOT=str(self.codex_root),
            TEST_CODEX_LOG_DIR=str(self.log_dir),
            TEST_CODEX_SQLITE_HOME=str(self.sqlite_home),
            TEST_CODEX_RUNTIME_ROOT=str(self.runtime_root),
            TEST_UID=str(os.getuid()),
            TEST_GID=str(os.getgid()),
        )

    def write_command(self, name, body):
        command = self.fake_bin / name
        command.write_text('#!/bin/sh\nset -eu\n' + body)
        command.chmod(0o755)

    def run_layout(self, body='devops_prepare_codex_layout\n', **environment):
        return subprocess.run(
            ['/bin/sh', '-c', self.script + body],
            env={**self.env, **environment},
            text=True,
            capture_output=True,
            timeout=5,
        )

    def test_exact_prepared_layout_is_idempotent(self):
        result = self.run_layout(
            'devops_prepare_codex_layout\n'
            'devops_prepare_codex_layout\n'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_modes = {
            self.codex_root: 0o3770,
            self.codex_root / 'share': 0o755,
            self.codex_root / 'share/bin': 0o755,
            self.codex_root / 'lib': 0o755,
            self.log_dir: 0o2770,
            self.sqlite_home: 0o2770,
            self.runtime_root: 0o2770,
        }
        for directory, expected_mode in expected_modes.items():
            with self.subTest(directory=directory):
                self.assertTrue(directory.is_dir())
                self.assertFalse(directory.is_symlink())
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), expected_mode)

    def test_existing_root_with_wrong_metadata_is_rejected(self):
        self.codex_root.mkdir(parents=True, mode=0o770)
        result = self.run_layout(TEST_CODEX_ROOT_STAT=f'{os.getuid()}:{os.getgid()}:770')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unexpected ownership or mode', result.stderr)
        self.assertFalse((self.codex_root / 'share').exists())

    def test_symlink_root_is_rejected_without_touching_destination(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.codex_root.parent.mkdir(parents=True)
        self.codex_root.symlink_to(outside, target_is_directory=True)
        result = self.run_layout()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must not be a symlink', result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_child_is_rejected_without_touching_destination(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.codex_root.mkdir(parents=True)
        self.codex_root.chmod(0o3770)
        (self.codex_root / 'share').symlink_to(outside, target_is_directory=True)
        result = self.run_layout()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must not be a symlink', result.stderr)
        self.assertEqual(list(outside.iterdir()), [])


class CodexDeploymentContractTests(unittest.TestCase):
    def test_managed_codex_release_is_preflighted_before_publication(self):
        devops = (FORKY / 'scripts/late/devops.sh').read_text(encoding='utf-8')
        function = devops.split('devops_install_pinned_codex() {', 1)[1].split(
            '\n}\n\ndevops_run_as_account() {', 1
        )[0]

        publication = 'rmdir -- "$codex_root/share/bin"'
        self.assertIn(publication, function)
        publication_offset = function.index(publication)
        for required_preflight in (
            'python3 "$archive_helper_path"',
            'version_output=$("$candidate_binary_path" --version',
            'git clone',
            'actual_repository_commit=$(git -C "$repository_staging" rev-parse HEAD)',
            'cp -a -- "$repository_staging/etc/." "$config_staging/"',
            'codex_tree_matches "$extracted_binary_dir" "$codex_root/share/bin" 0',
            'codex_tree_matches "$repository_staging" "$user_root" 1',
            'codex_tree_matches "$config_staging" "$system_config_dir" 0',
        ):
            with self.subTest(required_preflight=required_preflight):
                self.assertIn(required_preflight, function)
                self.assertLess(function.index(required_preflight), publication_offset)

        self.assertNotIn(
            'mv -- "$extracted_path" "$codex_root/share/bin/$binary_name"',
            function,
        )

    def test_managed_codex_publication_rolls_back_only_new_paths(self):
        devops = (FORKY / 'scripts/late/devops.sh').read_text(encoding='utf-8')
        function = devops.split('devops_install_pinned_codex() {', 1)[1].split(
            '\n}\n\ndevops_run_as_account() {', 1
        )[0]

        self.assertIn('publication_committed=0', function)
        self.assertIn('[ "$published_binary_directory" = 0 ] ||', function)
        self.assertIn('[ "$published_schema" = 0 ] ||', function)
        self.assertIn('[ "$published_repository" = 0 ] ||', function)
        self.assertIn('[ "$published_config" = 0 ] ||', function)
        self.assertIn('[ "$published_release_marker" = 0 ] ||', function)
        self.assertIn('publication_committed=1', function)
        self.assertLess(
            function.index('published_release_marker=1'),
            function.index('publication_committed=1'),
        )

    def test_target_installer_runs_after_desktop_home_population(self):
        text = STANDALONE.read_text()
        start = text.index('devops_de_apply_environment ||')
        self.assertGreater(text.index('XDG_RUNTIME_DIR=$installer_runtime'), start)
        self.assertIn("--proto-redir '=https'", text)

        old_path = FORKY / 'scripts/late/codex-standalone-install'
        self.assertFalse(old_path.exists())
        devops = (FORKY / 'scripts/late/devops.sh').read_text()
        self.assertIn(
            'DIR_HOOKS_TARGET usr/local/bin/codex-standalone-install',
            devops,
        )
        self.assertIn(
            'DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER=/usr/local/bin/codex-standalone-install',
            devops,
        )
        self.assertNotIn('devops_install_codex_standalone', devops)

        desktop = (FORKY / 'scripts/desktop/labwc.sh').read_text()
        function = desktop.split('desktop_install_codex_standalone() (', 1)[1].split('\n)\n', 1)[0]
        self.assertIn('run_in_target', function)
        self.assertIn('/usr/bin/python3 "$session_helper"', function)
        self.assertIn('installer_helper=/usr/local/bin/codex-standalone-install', function)
        self.assertIn('${ACCOUNT_HOME}/.profile.d/71-devops-de.sh', function)
        self.assertIn('${DEVOPS_CODEX_USER_ROOT}/.git', function)
        self.assertIn('install_packages=$packages_root', text)
        self.assertNotIn('runuser', function)
        self.assertNotIn('/run/user/', function)
        self.assertGreater(
            desktop.index('desktop_install_codex_standalone\n'),
            desktop.index('desktop_install_user_config\n'),
        )


if __name__ == '__main__':
    unittest.main()
