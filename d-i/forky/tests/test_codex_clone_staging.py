#!/usr/bin/env python3
"""Regress the real allocator/validator boundary under the deployed setgid root.

No deployment key, Git provider, boot files or host /data is used. Integration
checks run the production clone() in a disposable chroot with real Git and a
local SSH *transport fixture*. They are not OpenSSH authentication tests. Only
already-installed executables/libraries are copied; nothing is compiled.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

SEED = Path(__file__).resolve().parents[1]
HELPER = SEED / 'hooks/target/usr/local/libexec/managed-ssh-install.py'
DEVOPS = SEED / 'scripts/late/devops.sh'
URL = 'git@gitlab.com:computes/misc/codex-home.git'
BRIDGE = r'''
import importlib.util, json, os, shutil, subprocess, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('clone_helper_fixture', sys.argv[1])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
root, destination, action = sys.argv[2:]
# This sandbox cannot mknod or mount. Keep a real /dev/null descriptor open
# before chroot so checked() has a genuine stderr sink. The empty in-chroot
# /dev/null file is only read by Git's explicitly empty global-config policy.
null_fd = os.open('/dev/null', os.O_RDWR)
real_popen = subprocess.Popen
def with_null_descriptor(*args, **kwargs):
    if kwargs.get('stderr') == subprocess.DEVNULL:
        kwargs['stderr'] = null_fd
    return real_popen(*args, **kwargs)
helper.subprocess.Popen = with_null_descriptor
os.chroot(root)
os.chdir('/')
os.umask(0o077)
stage = Path('/tmp/managed-git-ssh.Fixture123')
stage.mkdir(mode=0o700)
try:
    env = dict(helper.BASE_ENV, SSH_AUTH_SOCK=str(stage/'agent.sock'))
    helper.clone(Path(destination), stage, env)
    def git(*args):
        return helper.checked(['/usr/bin/git', '-C', destination, *args],
                              env=dict(env, GIT_CONFIG_NOSYSTEM='1',
                                       GIT_CONFIG_GLOBAL='/dev/null')).decode().strip()
    metadata = Path(destination).parent.lstat()
    current_umask = os.umask(0o077)
    os.umask(current_umask)
    receipt = {'uid': metadata.st_uid, 'gid': metadata.st_gid,
               'mode': oct(metadata.st_mode & 0o7777),
               'parent_umask': oct(current_umask),
               'ssh_stage_mode': oct(stage.stat().st_mode & 0o7777),
               'ssh_config_mode': oct((stage/'ssh_config').stat().st_mode & 0o7777),
               'branch': git('symbolic-ref', '--short', 'HEAD'),
               'upstream': git('rev-parse', '--abbrev-ref', '@{upstream}'),
               'remote': git('remote', 'get-url', 'origin'),
               'commits': git('rev-list', '--count', 'HEAD'),
               'head': (Path(destination)/'.git/HEAD').read_text(),
               'config': (Path(destination)/'.git/config').read_text(),
               'ssh_config': (stage/'ssh_config').read_text()}
    Path('/clone-receipt.json').write_text(json.dumps(receipt))
    if action == 'clone-fail-after-copy':
        raise helper.InstallError('fixture failure after clone')
except (OSError, ValueError, subprocess.SubprocessError) as exc:
    print(f'managed-ssh-install: {type(exc).__name__}: {exc}', file=sys.stderr)
    sys.exit(1)
finally:
    shutil.rmtree(stage)
    os.close(null_fd)
'''
TRANSPORT = r'''#!/bin/sh
# Intentionally local: this is not an SSH client or a host-key/auth test.
set -eu
[ "$1" = -F ] || exit 71
[ -f "$2" ] || exit 72
shift 2
if [ "${1:-}" = -o ]; then
  [ "$2" = SendEnv=GIT_PROTOCOL ] || exit 73
  shift 2
fi
[ "$#" -eq 2 ] || exit 74
[ "$1" = git@gitlab.com ] || exit 75
[ "$2" = "git-upload-pack 'computes/misc/codex-home.git'" ] || exit 76
printf called > /transport-called
[ ! -f /transport-fail ] || exit 77
exec /usr/bin/git-upload-pack /fixtures/remote.git
'''


def allocator_source() -> str:
    text = DEVOPS.read_text()
    start = text.index('devops_install_pinned_codex() (')
    end = text.index('\n)\n\ndevops_install_codex_from_clone()', start) + 3
    return text[start:end]


@unittest.skipUnless(os.geteuid() == 0, 'real root-owned installer staging fixture')
class CloneStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codex-clone-stage-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root/'target'
        self.codex = self.target/'data/codex'
        self.codex.mkdir(parents=True)
        self.gid = pwd.getpwnam('nobody').pw_gid
        os.chown(self.codex, 0, self.gid)
        self.codex.chmod(0o3770)
        self.bin = self.root/'bin'
        self.bin.mkdir()
        self.record = self.root/'calls'
        self.bridge = self.root/'bridge.py'
        self.bridge.write_text(BRIDGE)
        self.env = dict(os.environ, PATH=f'{self.bin}:/usr/bin:/bin',
                        TEST_TARGET=str(self.target), TEST_RECORD=str(self.record),
                        TEST_HELPER=str(HELPER), TEST_BRIDGE=str(self.bridge),
                        TEST_PYTHON=sys.executable, TEST_ACTION='stub')
        # Avoid ambient user Git settings in fixture creation as well.
        self.git_env = dict(self.env, HOME=str(self.root), GIT_CONFIG_NOSYSTEM='1',
                            GIT_CONFIG_GLOBAL='/dev/null',
                            GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='test@example.invalid',
                            GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='test@example.invalid')
        self.script = r'''
set -eu
target_root=$TEST_TARGET
devops_fatal() { printf 'fatal: %s\n' "$*" >&2; exit 1; }
managed_git_ssh_target_action() {
  [ "$#" -eq 2 ] && [ "$1" = clone-codex ] || return 64
  printf 'clone:%s\n' "$2" >> "$TEST_RECORD"
  path="${target_root}${2%/repository}"
  [ -d "$path" ] && [ ! -L "$path" ] || return 65
  # Only stub actions assert locally; real actions must reach the production
  # Python validator, including when run against the broken prior delivery.
  case "$TEST_ACTION" in
    stub|clone-fail|wait) [ "$(stat -c '%u:%a' -- "$path")" = 0:700 ] || return 66 ;;
  esac
  [ ! -e "${target_root}$2" ] && [ ! -L "${target_root}$2" ] || return 67
  case "$TEST_ACTION" in
    stub) mkdir "${target_root}$2" ;;
    clone-fail) mkdir "${target_root}$2"; return 28 ;;
    wait) printf ready > "$TEST_RECORD.ready"; sleep 30 ;;
    *) "$TEST_PYTHON" -B "$TEST_BRIDGE" "$TEST_HELPER" "$target_root" "$2" "$TEST_ACTION" ;;
  esac
}
devops_install_codex_from_clone() {
  printf 'publish:%s\n' "$1" >> "$TEST_RECORD"
  [ -d "${target_root}$1" ] || return 68
  [ "$TEST_ACTION" != publisher-fail ] || return 37
  mv "${target_root}$1" "${target_root}/published"
}
''' + allocator_source() + '\n'

    def command(self, name: str, body: str) -> None:
        path = self.bin/name
        path.write_text('#!/bin/sh\nset -eu\n' + body + '\n')
        path.chmod(0o755)

    def run_allocator(self, action='stub', shell=('/bin/sh',), body=None, **env):
        return subprocess.run([*shell, '-c', self.script + (body or 'devops_install_pinned_codex\n')],
                              env=dict(self.env, TEST_ACTION=action, **env),
                              text=True, capture_output=True, timeout=15)

    def assert_clean(self):
        self.assertEqual(list(self.codex.glob('.home-clone.*')), [])
        self.assertEqual((self.codex.stat().st_uid, self.codex.stat().st_gid,
                          stat.S_IMODE(self.codex.stat().st_mode)), (0, self.gid, 0o3770))

    def assert_not_called(self):
        self.assertFalse(self.record.exists(), 'private SSH action must not run')
        self.assertFalse((self.target/'published').exists())
        self.assert_clean()

    def make_parent(self, mode=0o700, name='.home-clone.Test123'):
        path = self.codex/name
        path.mkdir()
        path.chmod(mode)
        return path

    def prepare_git_chroot(self):
        if not shutil.which('ldd') or not shutil.which('git'):
            self.skipTest('installed Git and ldd are required for real clone fixture')
        # Preflight capability in a subprocess, without changing the test runner.
        probe = subprocess.run([sys.executable, '-c',
                                'import os,sys;os.chroot(sys.argv[1])', str(self.target)],
                               capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('disposable chroot is not permitted')
        copied = set()
        for source in ('/usr/bin/git', '/bin/sh'):
            paths = [source]
            output = subprocess.check_output(['ldd', source], text=True)
            paths += re.findall(r'(?:=>\s+)?(/[^\s()]+)', output)
            for name in paths:
                if name in copied:
                    continue
                copied.add(name)
                destination = self.target/name.lstrip('/')
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(name, destination)
                destination.chmod(0o755)
        for name in ('git-upload-pack', 'git-index-pack', 'git-pack-objects', 'git-rev-list'):
            (self.target/'usr/bin'/name).symlink_to('git')
        (self.target/'usr/lib/git-core').mkdir(parents=True)
        for name in ('git', 'git-upload-pack', 'git-index-pack', 'git-pack-objects', 'git-rev-list'):
            (self.target/'usr/lib/git-core'/name).symlink_to('/usr/bin/git')
        for name in ('tmp', 'root', 'dev', 'etc', 'fixtures'):
            (self.target/name).mkdir(exist_ok=True)
        (self.target/'dev/null').touch()
        # Git in this container reads /dev/urandom for temporary names. A
        # finite, freshly generated entropy fixture suffices; no device node
        # or mount is created, and no cryptographic credentials are generated.
        (self.target/'dev/urandom').write_bytes(os.urandom(65536))
        (self.target/'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
        (self.target/'etc/group').write_text('root:x:0:\n')
        # A broken ambient global Git config must not affect the managed clone.
        (self.target/'root/.gitconfig').write_text('THIS IS NOT VALID GIT CONFIG\n')
        transport = self.target/'usr/bin/ssh'
        transport.write_text(TRANSPORT)
        transport.chmod(0o755)
        source = self.root/'source'
        subprocess.run(['git', 'init', '-q', '-b', 'mcr/main', str(source)],
                       env=self.git_env, check=True, capture_output=True)
        for directory in ('agents', 'etc', 'home', 'skills'):
            path = source/directory
            path.mkdir()
            (path/'README').write_text('local fixture\n')
        (source/'etc/nested').mkdir()
        (source/'etc/nested/settings').write_text('fixture config\n')
        (source/'etc/tool').write_text('#!/bin/sh\nexit 0\n')
        (source/'etc/tool').chmod(0o755)
        def git(*args):
            subprocess.run(['git', '-C', str(source), *args], env=self.git_env,
                           check=True, capture_output=True, timeout=5)
        git('add', '.')
        git('commit', '-qm', 'fixture base')
        (source/'home/README').write_text('second local commit\n')
        git('commit', '-qam', 'fixture update')
        subprocess.run(['git', 'clone', '-q', '--bare', str(source),
                        str(self.target/'fixtures/remote.git')], env=self.git_env,
                       check=True, capture_output=True, timeout=5)

    def run_guard(self, destination):
        return subprocess.run([sys.executable, '-B', str(self.bridge), str(HELPER),
                               str(self.target), destination, 'real'],
                              env=self.env, text=True, capture_output=True, timeout=10)

    def test_original_setgid_inheritance_and_gnu_chmod_trap(self):
        parent = Path(subprocess.check_output(['mktemp', '-d', str(self.codex/'.home-clone.XXXXXXXX')],
                                             text=True).strip())
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o2700)
        subprocess.run(['/usr/bin/chmod', '0700', str(parent)], check=True)
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o2700)
        subprocess.run(['/usr/bin/chmod', 'a-s', str(parent)], check=True)
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)

    def test_gnu_allocator_normalizes_stage_and_preserves_shared_root(self):
        result = self.run_allocator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.record.read_text().splitlines()), 2)
        self.assert_clean()

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox installer tool fixture')
    def test_busybox_ash_and_applets(self):
        for name in ('mktemp', 'chmod', 'stat', 'rm', 'mkdir', 'mv'):
            (self.bin/name).symlink_to(shutil.which('busybox'))
        result = self.run_allocator(shell=(shutil.which('busybox'), 'sh'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_clean()

    def test_bash_caller(self):
        result = self.run_allocator(shell=('/bin/bash',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_clean()

    def test_stage_normalization_does_not_change_caller_umask(self):
        result = self.run_allocator(body='umask 027\ndevops_install_pinned_codex\numask\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(int(result.stdout.strip(), 8), 0o027)
        self.assert_clean()

    def test_allocation_failure_does_not_invoke_ssh(self):
        self.command('mktemp', 'exit 72')
        result = self.run_allocator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unable to allocate', result.stderr)
        self.assert_not_called()

    def test_either_chmod_failure_stops_before_ssh_and_cleans_stage(self):
        for mode in ('0700', 'a-s'):
            with self.subTest(mode=mode):
                self.command('chmod', f'[ "$1" != {mode} ] || exit 66\nexec /usr/bin/chmod "$@"')
                result = self.run_allocator()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('unable to secure', result.stderr)
                self.assert_not_called()

    def test_successful_but_ineffective_chmod_is_not_trusted(self):
        self.command('chmod', '[ "$1" != a-s ] || exit 0\nexec /usr/bin/chmod "$@"')
        result = self.run_allocator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be root-owned mode 0700', result.stderr)
        self.assert_not_called()

    def test_nonroot_allocator_output_is_rejected_without_repair(self):
        self.command('mktemp', 'p=$(/usr/bin/mktemp "$@")\n/usr/bin/chown 65534 "$p"\nprintf "%s\\n" "$p"')
        result = self.run_allocator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not root-owned', result.stderr)
        self.assert_not_called()

    def test_clone_failure_removes_partial_checkout_and_prevents_publication(self):
        result = self.run_allocator('clone-fail')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('publish:', self.record.read_text())
        self.assertFalse((self.target/'published').exists())
        self.assert_clean()

    def test_signals_remove_stage_without_publishing(self):
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=sig):
                ready = Path(str(self.record) + '.ready')
                ready.unlink(missing_ok=True)
                self.record.unlink(missing_ok=True)
                process = subprocess.Popen(['/bin/sh', '-c', self.script + 'devops_install_pinned_codex\n'],
                                           env=dict(self.env, TEST_ACTION='wait'),
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, start_new_session=True)
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(ready.exists(), 'stage did not become ready')
                    os.killpg(process.pid, sig)
                    process.communicate(timeout=5)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertNotIn('publish:', self.record.read_text())
                    self.assert_clean()
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate(timeout=5)

    def test_real_git_clone_through_production_allocator_and_validator(self):
        self.prepare_git_chroot()
        result = self.run_allocator('real')
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads((self.target/'clone-receipt.json').read_text())
        self.assertEqual((receipt['uid'], receipt['gid'], receipt['mode']), (0, self.gid, '0o700'))
        self.assertEqual(receipt['parent_umask'], '0o77')
        self.assertEqual(receipt['ssh_stage_mode'], '0o700')
        self.assertEqual(receipt['ssh_config_mode'], '0o600')
        self.assertEqual(receipt['branch'], 'mcr/main')
        self.assertEqual(receipt['upstream'], 'origin/mcr/main')
        self.assertEqual(receipt['remote'], URL)
        self.assertEqual(receipt['commits'], '2')
        self.assertEqual(receipt['head'], 'ref: refs/heads/mcr/main\n')
        for forbidden in ('agent.sock', 'ssh_config', 'core.hooksPath', 'Fixture123', 'PRIVATE KEY'):
            self.assertNotIn(forbidden, receipt['config'])
        for required in ('StrictHostKeyChecking yes', 'ForwardAgent no', 'BatchMode yes',
                         'IdentitiesOnly yes', 'IdentityFile /tmp/managed-git-ssh.Fixture123/public',
                         'UserKnownHostsFile /etc/ssh/managed_git_known_hosts'):
            self.assertIn(required, receipt['ssh_config'])
        self.assertTrue((self.target/'published/.git/HEAD').is_file())
        self.assertEqual(list((self.target/'tmp').iterdir()), [])
        self.assert_clean()


    def test_published_root_owned_config_remains_readable_by_desktop_user(self):
        self.prepare_git_chroot()
        result = self.run_allocator('real')
        self.assertEqual(result.returncode, 0, result.stderr)
        # Execute the actual publication permission/copy block, but only inside
        # this disposable fixture. Never publish into the host /etc/codex.
        text = DEVOPS.read_text()
        start = text.index('codex_chmod_without_special_bits() {')
        end = text.index('\n}\n\ncodex_chmod_group_shared()', start) + 3
        normalizer = text[start:end]
        start = text.index('cp -a -- "$repository_staging/etc/." "$config_staging/"')
        end_text = 'codex_chmod_without_special_bits 0755 "$config_staging"'
        end = text.index(end_text, start) + len(end_text)
        config = self.root/'published-config'
        config.mkdir(mode=0o700)
        script = ('set -eu\ncodex_fatal() { printf "%s\\n" "$*" >&2; exit 1; }\n'
                  + normalizer + '\n' + text[start:end] + '\n')
        subprocess.run(['/bin/sh', '-c', script], check=True, capture_output=True,
                       env=dict(self.env, repository_staging=str(self.target/'published'),
                                config_staging=str(config)), timeout=5)
        for name, mode in (('README', 0o644), ('nested', 0o755),
                           ('nested/settings', 0o644), ('tool', 0o755)):
            path = config/name
            self.assertEqual((path.stat().st_uid, path.stat().st_gid,
                              stat.S_IMODE(path.stat().st_mode)), (0, 0, mode), name)
        # Test effective access, not just root's reading of mode bits.
        self.root.chmod(0o755)
        nobody = pwd.getpwnam('nobody')
        for name in ('README', 'nested/settings', 'tool'):
            for flag, expected in (('-r', 0), ('-w', 1)):
                access = subprocess.run(['/usr/bin/test', flag, str(config/name)],
                                        user=nobody.pw_uid, group=nobody.pw_gid,
                                        extra_groups=[], timeout=5)
                self.assertEqual(access.returncode, expected, (name, flag))
        self.assert_clean()

    def test_readable_checkout_is_still_hidden_by_private_stage(self):
        self.prepare_git_chroot()
        parent = self.make_parent()
        result = self.run_guard('/data/codex/.home-clone.Test123/repository')
        self.assertEqual(result.returncode, 0, result.stderr)
        path = parent/'repository/etc/README'
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)
        for directory in (self.root, self.target, self.target/'data'):
            directory.chmod(0o755)
        nobody = pwd.getpwnam('nobody')
        result = subprocess.run(['/usr/bin/test', '-r', str(path)],
                                user=nobody.pw_uid, group=nobody.pw_gid,
                                extra_groups=[], timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(stat.S_IMODE(self.codex.stat().st_mode), 0o3770)

    def load_helper(self):
        spec = importlib.util.spec_from_file_location('managed_clone_umask_fixture', HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_checked_child_umask_does_not_change_secret_parent_or_default_child(self):
        helper = self.load_helper()
        original = os.umask(0o077)
        try:
            for name, options, mode in (('default', {}, 0o600),
                                         ('checkout', {'umask': 0o022}, 0o644)):
                path = self.root/name
                helper.checked([sys.executable, '-B', '-c',
                                'import pathlib,sys;pathlib.Path(sys.argv[1]).write_text("fixture")',
                                str(path)], **options)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
                observed = os.umask(0o077)
                self.assertEqual(observed, 0o077)
        finally:
            os.umask(original)

    def test_checked_failed_child_keeps_private_parent_umask(self):
        helper = self.load_helper()
        original = os.umask(0o077)
        try:
            with self.assertRaisesRegex(helper.InstallError, 'status 19'):
                helper.checked([sys.executable, '-B', '-c', 'raise SystemExit(19)'],
                               umask=0o022)
            observed = os.umask(0o077)
            self.assertEqual(observed, 0o077)
        finally:
            os.umask(original)

    def test_real_git_transport_failure_stops_and_cleans(self):
        self.prepare_git_chroot()
        (self.target/'transport-fail').touch()
        result = self.run_allocator('real')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('git failed (status', result.stderr)
        self.assertTrue((self.target/'transport-called').exists())
        self.assertNotIn('publish:', self.record.read_text())
        self.assertFalse((self.target/'published').exists())
        self.assertEqual(list((self.target/'tmp').iterdir()), [])
        self.assert_clean()

    def test_post_clone_failure_still_cleans(self):
        self.prepare_git_chroot()
        result = self.run_allocator('clone-fail-after-copy')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fixture failure after clone', result.stderr)
        self.assertTrue((self.target/'clone-receipt.json').exists())
        self.assertNotIn('publish:', self.record.read_text())
        self.assertFalse((self.target/'published').exists())
        self.assert_clean()

    def test_publisher_failure_preserves_failure_status_and_cleans(self):
        self.prepare_git_chroot()
        result = self.run_allocator('publisher-fail')
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertFalse((self.target/'published').exists())
        self.assert_clean()

    def test_validator_keeps_rejecting_unsafe_modes_including_inherited_setgid(self):
        self.prepare_git_chroot()
        parent = self.make_parent()
        for mode in (0o2700, 0o750, 0o770, 0o777, 0o1700, 0o4700, 0o6700):
            with self.subTest(mode=oct(mode)):
                parent.chmod(mode)
                result = self.run_guard('/data/codex/.home-clone.Test123/repository')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('unsafe Codex clone staging parent', result.stderr)
                self.assertIn(f'mode={mode:04o}', result.stderr)
                self.assertEqual(stat.S_IMODE(parent.stat().st_mode), mode)
                self.assertFalse((self.target/'transport-called').exists())

    def test_validator_rejects_nonroot_parent(self):
        self.prepare_git_chroot()
        parent = self.make_parent()
        os.chown(parent, 65534, self.gid)
        result = self.run_guard('/data/codex/.home-clone.Test123/repository')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('uid=65534', result.stderr)
        self.assertFalse((self.target/'transport-called').exists())

    def test_validator_rejects_symlink_parent_without_chmod_target(self):
        self.prepare_git_chroot()
        outside = self.target/'outside'
        outside.mkdir(mode=0o700)
        (self.codex/'.home-clone.Test123').symlink_to('/outside')
        result = self.run_guard('/data/codex/.home-clone.Test123/repository')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('directory=False', result.stderr)
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o700)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.target/'transport-called').exists())

    def test_validator_rejects_existing_checkout_or_dangling_symlink(self):
        self.prepare_git_chroot()
        parent = self.make_parent()
        destination = parent/'repository'
        for kind in ('directory', 'dangling-symlink'):
            with self.subTest(kind=kind):
                if kind == 'directory':
                    destination.mkdir()
                else:
                    destination.symlink_to('/missing-target')
                result = self.run_guard('/data/codex/.home-clone.Test123/repository')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('destination already exists', result.stderr)
                self.assertFalse((self.target/'transport-called').exists())
                if kind == 'directory':
                    destination.rmdir()
                else:
                    destination.unlink()

    def test_validator_does_not_relax_path_allowlist(self):
        self.prepare_git_chroot()
        for path in ('/tmp/repository', '/data/codex/.home-clone.bad-name/repository',
                     '/data/codex/.home-clone.Test123/not-repository'):
            with self.subTest(path=path):
                result = self.run_guard(path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('unapproved Codex clone destination', result.stderr)
                self.assertFalse((self.target/'transport-called').exists())


if __name__ == '__main__':
    unittest.main()
