#!/usr/bin/env python3
"""Exercise vault publication with disposable, local Git repositories."""
from __future__ import annotations

import contextlib
import importlib.util
import os
from pathlib import Path
import subprocess
import shlex
import runpy
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

SEED = Path(__file__).resolve().parents[1]
SCRIPT = SEED/'hooks/target/usr/local/libexec/obsidian-git-sync.py'
INSTALLER = SEED/'scripts/late/ssh/ssh-install.py'
SPEC = importlib.util.spec_from_file_location('obsidian_git_sync', SCRIPT)
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)
INSTALL_SPEC = importlib.util.spec_from_file_location('obsidian_installer', INSTALLER)
INSTALL = importlib.util.module_from_spec(INSTALL_SPEC)
INSTALL_SPEC.loader.exec_module(INSTALL)


class InstallerVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='obsidian-clone-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.home.chmod(0o700)
        self.syncthing = self.home/'Syncthing'
        self.syncthing.mkdir(mode=0o700)
        self.stage = self.home/'stage'
        self.stage.mkdir(mode=0o700)
        self.account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())

    def clone_fixture(self, dest: Path, stage: Path, env: dict, **kwargs):
        self.assertEqual((dest, stage, kwargs), (self.stage/'repository', self.stage,
                         {'url': INSTALL.OBSIDIAN_URL, 'branch': 'mcr/main'}))
        (dest/'.git').mkdir(parents=True)
        (dest/'note.md').write_text('remote note\n')
        (dest/'link').symlink_to('/does-not-exist')

    def test_clone_publishes_user_writable_git_checkout(self):
        with mock.patch.object(INSTALL, 'clone', side_effect=self.clone_fixture):
            INSTALL.clone_obsidian(self.account, self.home, self.stage, {})
        target = self.syncthing/'obsidian-md'
        self.assertEqual((target/'.git').stat().st_uid, os.getuid())
        self.assertEqual((target/'note.md').stat().st_mode & 0o777, 0o600)
        self.assertEqual((target/'.git').stat().st_mode & 0o777, 0o700)
        self.assertEqual((target/'link').readlink(), Path('/does-not-exist'))
        self.assertEqual(list(self.syncthing.glob('.obsidian-clone.*')), [])

    def test_existing_vault_is_preserved(self):
        target = self.syncthing/'obsidian-md'
        target.mkdir()
        (target/'note.md').write_text('my note')
        with self.assertRaisesRegex(INSTALL.InstallError, 'already exists'):
            INSTALL.clone_obsidian(self.account, self.home, self.stage, {})
        self.assertEqual((target/'note.md').read_text(), 'my note')

    def test_failed_clone_never_publishes_partial_vault(self):
        def fail(dest, stage, env, **kwargs):
            (dest/'.git').mkdir(parents=True)
            raise INSTALL.InstallError('fixture transport failure')
        with mock.patch.object(INSTALL, 'clone', side_effect=fail):
            with self.assertRaisesRegex(INSTALL.InstallError, 'transport failure'):
                INSTALL.clone_obsidian(self.account, self.home, self.stage, {})
        self.assertFalse((self.syncthing/'obsidian-md').exists())
        self.assertFalse(list(self.syncthing.glob('.obsidian-clone.*')))

    def test_every_profile_and_session_wiring_uses_approved_contract(self):
        paths = sorted((SEED/'hosts/profiles').glob('*.env'))
        self.assertEqual(len(paths), 10)
        for path in paths:
            content = path.read_text()
            for value in (
                'OBSIDIAN_GIT_REPOSITORY_URL="git@gitlab.com:core-assets/docs/obsidian-md.git"',
                'OBSIDIAN_GIT_REPOSITORY_BRANCH="mcr/main"',
                'OBSIDIAN_GIT_DIRECTORY="Syncthing/obsidian-md"',
                'OBSIDIAN_GIT_SYNC_INTERVAL="1h"',
            ):
                self.assertIn(value, content, path.name)
            expected = 'true' if '-p15s' in path.stem else 'false'
            self.assertEqual(content.count('OBSIDIAN_GIT_AUTO_ENABLE='), 1, path.name)
            self.assertIn('OBSIDIAN_GIT_AUTO_ENABLE="' + expected + '"', content, path.name)
        self.assertIn('managed_git_ssh_target_action clone-obsidian',
                      (SEED/'scripts/desktop/components/user-config.sh').read_text())
        self.assertIn('obsidian-git-sync.timer',
                      (SEED/'scripts/desktop/components/services.sh').read_text())
        self.assertIn('/obsidian-md/.git',
                      (SEED/'hooks/target/etc/skel-desktop/Syncthing/.stignore').read_text())


class VaultSyncTests(unittest.TestCase):
    def setUp(self):
        enabled = mock.patch.object(SYNC, 'auto_enabled', return_value=True)
        enabled.start()
        self.addCleanup(enabled.stop)
        directory = tempfile.TemporaryDirectory(prefix='obsidian-sync-')
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.home.chmod(0o700)
        self.remote = self.home/'remote.git'
        self.syncthing = self.home/'Syncthing'
        self.syncthing.mkdir(mode=0o700)
        self.work = self.home/'Syncthing/obsidian-md'
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                        GIT_AUTHOR_NAME='Test Author', GIT_AUTHOR_EMAIL='author@example.invalid',
                        GIT_COMMITTER_NAME='Test Author', GIT_COMMITTER_EMAIL='author@example.invalid')
        self.call('init', '--bare', str(self.remote), cwd=self.home)
        seed = self.home/'seed'
        self.call('init', '-b', 'mcr/main', str(seed), cwd=self.home)
        (seed/'initial.md').write_text('initial\n')
        self.call('add', '-A', cwd=seed)
        self.call('commit', '-m', 'Initial', cwd=seed)
        self.call('remote', 'add', 'origin', str(self.remote), cwd=seed)
        self.call('push', 'origin', 'mcr/main:mcr/main', 'mcr/main:mcr/staging',
                  'mcr/main:mcr/release', cwd=seed)
        self.call('clone', '--single-branch', '--branch', 'mcr/main', str(self.remote),
                  str(self.work), cwd=self.home)
        self.work.chmod(0o700)
        (self.work/'.git').chmod(0o700)
        self.call('config', 'user.name', 'Test Author', cwd=self.work)
        self.call('config', 'user.email', 'author@example.invalid', cwd=self.work)
        # Test transport is local. Production git() forbids file:// and local
        # fetch/push; substitute only those three transport calls.
        self.original_git = SYNC.git
        self.original_url = SYNC.URL
        self.original_quiet = SYNC.QUIET_SECONDS
        SYNC.URL = str(self.remote)
        SYNC.QUIET_SECONDS = 0
        self.addCleanup(self.restore)

    def restore(self):
        SYNC.git = self.original_git
        SYNC.URL = self.original_url
        SYNC.QUIET_SECONDS = self.original_quiet

    def call(self, *args, cwd: Path):
        return subprocess.run(['/usr/bin/git', *args], cwd=cwd, env=self.env,
                              check=True, capture_output=True, timeout=10).stdout.strip()

    def transport(self, root: Path, *args: str):
        if args[0] in ('ls-remote', 'fetch', 'push'):
            return self.call(*args, cwd=root)
        return self.original_git(root, *args)

    def sync(self):
        with mock.patch.object(SYNC, 'git', side_effect=self.transport):
            return SYNC.sync(self.work)

    def head(self, name):
        return self.call('--git-dir='+str(self.remote), 'rev-parse', 'refs/heads/'+name,
                         cwd=self.home)

    def test_new_notes_and_deletions_commit_and_forward_atomically(self):
        (self.work/'note.md').write_text('new note\n')
        (self.work/'initial.md').unlink()
        self.assertIn('pushed mcr/main', self.sync())
        heads = [self.head(name) for name in SYNC.BRANCHES]
        self.assertEqual(len(set(heads)), 1)
        self.assertEqual(self.call('status', '--porcelain', cwd=self.work), b'')
        self.assertEqual(self.call('--git-dir='+str(self.remote), 'show',
                                   'mcr/release:note.md', cwd=self.home), b'new note')
        self.assertEqual(self.sync(), 'all branches already up to date')

    def test_disabled_publication_leaves_notes_index_refs_and_remote_untouched(self):
        (self.work/'note.md').write_text('manual work\n')
        self.call('add', 'note.md', cwd=self.work)
        (self.work/'untracked.md').write_text('do not stage automatically\n')
        head = self.call('rev-parse', 'HEAD', cwd=self.work)
        index = (self.work/'.git/index').read_bytes()
        remote = [self.head(name) for name in SYNC.BRANCHES]
        with mock.patch.object(SYNC, 'auto_enabled', return_value=False), mock.patch.object(SYNC, 'git') as git:
            self.assertIn('disabled', SYNC.sync(self.work))
            git.assert_not_called()
        self.assertEqual((self.work/'.git/index').read_bytes(), index)
        self.assertEqual(self.call('rev-parse', 'HEAD', cwd=self.work), head)
        self.assertEqual([self.head(name) for name in SYNC.BRANCHES], remote)
        self.assertEqual((self.work/'untracked.md').read_text(), 'do not stage automatically\n')

    def test_invalid_policy_does_not_reach_git(self):
        with mock.patch.object(SYNC, 'auto_enabled', side_effect=SYNC.SyncError('invalid policy')), mock.patch.object(SYNC, 'git') as git:
            with self.assertRaisesRegex(SYNC.SyncError, 'invalid policy'):
                SYNC.sync(self.work)
            git.assert_not_called()

    def test_recent_edit_waits_without_staging_or_pushing(self):
        SYNC.QUIET_SECONDS = 60
        (self.work/'note.md').write_text('still editing\n')
        old = self.head('mcr/main')
        self.assertIn('recent edits', self.sync())
        self.assertEqual(self.head('mcr/main'), old)
        self.assertEqual(self.call('diff', '--cached', '--name-only', cwd=self.work), b'')

    def test_missing_promotion_branches_are_created_atomically(self):
        for name in SYNC.BRANCHES[1:]:
            self.call('--git-dir='+str(self.remote), 'update-ref', '-d',
                      'refs/heads/'+name, cwd=self.home)
        self.assertIn('pushed mcr/main', self.sync())
        self.assertEqual(len({self.head(name) for name in SYNC.BRANCHES}), 1)

    def test_change_during_stage_is_preserved_and_not_pushed(self):
        (self.work/'note.md').write_text('first version\n')
        original = self.transport
        def editing(root, *args):
            value = original(root, *args)
            if args[:2] == ('add', '-A'):
                (self.work/'note.md').write_text('second version\n')
            return value
        previous = self.head('mcr/main')
        with mock.patch.object(SYNC, 'git', side_effect=editing):
            with self.assertRaisesRegex(SYNC.SyncError, 'changed during staging'):
                SYNC.sync(self.work)
        self.assertEqual((self.work/'note.md').read_text(), 'second version\n')
        self.assertEqual(self.head('mcr/main'), previous)

    def test_divergent_stage_ref_is_never_overwritten(self):
        other = self.home/'other'
        self.call('clone', '--branch', 'mcr/staging', str(self.remote), str(other), cwd=self.home)
        (other/'staging.md').write_text('independent staging change\n')
        self.call('add', '-A', cwd=other)
        self.call('commit', '-m', 'Staging work', cwd=other)
        self.call('push', 'origin', 'HEAD:mcr/staging', cwd=other)
        (self.work/'note.md').write_text('main change\n')
        previous = self.head('mcr/staging')
        with self.assertRaisesRegex(SYNC.SyncError, 'staging diverged'):
            self.sync()
        self.assertEqual(self.head('mcr/staging'), previous)
        self.assertNotEqual(self.head('mcr/main'), self.call('rev-parse', 'HEAD', cwd=self.work))

    def test_existing_staged_work_remains_untouched(self):
        (self.work/'note.md').write_text('staged manually\n')
        self.call('add', 'note.md', cwd=self.work)
        with self.assertRaisesRegex(SYNC.SyncError, 'user has staged changes'):
            self.sync()
        self.assertEqual(self.call('show', ':note.md', cwd=self.work), b'staged manually')

    def test_missing_commit_identity_does_not_stage_notes(self):
        self.call('config', '--unset', 'user.email', cwd=self.work)
        (self.work/'note.md').write_text('new note\n')
        with self.assertRaisesRegex(SYNC.SyncError, 'user.email'):
            self.sync()
        self.assertEqual(self.call('diff', '--cached', '--name-only', cwd=self.work), b'')

    def test_alternate_push_destination_is_rejected(self):
        self.call('remote', 'set-url', '--push', 'origin', 'git@example.invalid:other.git',
                  cwd=self.work)
        with self.assertRaisesRegex(SYNC.SyncError, 'push destination'):
            self.sync()

    def test_failed_atomic_push_preserves_local_commit_for_retry(self):
        (self.work/'note.md').write_text('pending\n')
        expected = self.head('mcr/main')
        def unavailable(root, *args):
            if args[0] == 'push':
                raise SYNC.SyncError('fixture remote temporarily unavailable')
            return self.transport(root, *args)
        with mock.patch.object(SYNC, 'git', side_effect=unavailable):
            with self.assertRaisesRegex(SYNC.SyncError, 'temporarily unavailable'):
                SYNC.sync(self.work)
        self.assertEqual(self.head('mcr/main'), expected)
        self.assertIn('pushed mcr/main', self.sync())


@unittest.skipUnless(os.geteuid() == 0, 'root-owned policy fixtures require root')
class AutoPolicyTests(unittest.TestCase):
    def setUp(self):
        # The policy parser also rejects writable ancestors such as /tmp.
        temporary = tempfile.TemporaryDirectory(prefix='obsidian-policy-', dir='/root')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root/'auto.conf'
        policy = mock.patch.object(SYNC, 'AUTO_POLICY', self.path)
        policy.start()
        self.addCleanup(policy.stop)

    def test_exact_boolean_policy_and_missing_policy_fail_closed(self):
        self.assertFalse(SYNC.auto_enabled())
        for value in ('true', 'false'):
            self.path.write_text('OBSIDIAN_GIT_AUTO_ENABLE=' + value + '\n')
            self.path.chmod(0o644)
            with mock.patch.dict(os.environ, {'OBSIDIAN_GIT_AUTO_ENABLE': 'true'}):
                self.assertEqual(SYNC.auto_enabled(), value == 'true')

    def test_invalid_or_executable_policy_is_never_evaluated(self):
        marker = self.root/'executed'
        for value in ('', 'OBSIDIAN_GIT_AUTO_ENABLE=yes\n',
                      'OBSIDIAN_GIT_AUTO_ENABLE=true\nextra\n',
                      'OBSIDIAN_GIT_AUTO_ENABLE=$(touch ' + str(marker) + ')\n',
                      'x'*1024):
            self.path.write_text(value)
            with self.assertRaises(SYNC.SyncError):
                SYNC.auto_enabled()
        self.assertFalse(marker.exists())

    def test_untrusted_file_types_links_and_writable_metadata_are_rejected(self):
        original = self.root/'original'
        original.write_text('OBSIDIAN_GIT_AUTO_ENABLE=true\n')
        self.path.symlink_to(original)
        with self.assertRaises(OSError):
            SYNC.auto_enabled()
        self.path.unlink()
        os.link(original, self.path)
        with self.assertRaises(SYNC.SyncError):
            SYNC.auto_enabled()
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(SYNC.SyncError):
            SYNC.auto_enabled()
        self.path.unlink()
        self.path.write_text(original.read_text())
        self.path.chmod(0o666)
        with self.assertRaises(SYNC.SyncError):
            SYNC.auto_enabled()
        self.path.chmod(0o644)
        self.root.chmod(0o777)
        with self.assertRaises(SYNC.SyncError):
            SYNC.auto_enabled()

    def test_disabled_wrapper_exits_before_ssh_or_git(self):
        self.path.write_text('OBSIDIAN_GIT_AUTO_ENABLE=false\n')
        wrapper = (SCRIPT.parent/'obsidian-git-sync').read_text().replace(
            '/usr/local/libexec/obsidian-git-sync.py', str(SCRIPT))
        # The real parser reads our root-owned fixture; only the CLI UID check
        # is substituted in this root-only test. No agent/vault is available.
        worker = self.root/'worker.py'
        worker.write_text(SCRIPT.read_text().replace(
            "AUTO_POLICY = Path('/etc/obsidian-git-sync.conf')", 'AUTO_POLICY = Path(' + repr(str(self.path)) + ')').replace(
            'if os.getuid() == 0 or sys.argv[1:]', 'if False or sys.argv[1:]'))
        wrapper = wrapper.replace(str(SCRIPT), str(worker))
        result = subprocess.run(['/bin/sh', '-eu', '-c', wrapper], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('disabled', result.stdout)
        self.assertNotIn('unlock', result.stderr)


class CredentialPolicyTests(unittest.TestCase):
    """Read a real private credential file while redirecting its fixed path."""
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.directory = self.root / 'credentials'
        self.directory.mkdir(mode=0o700)
        self.path = self.directory / 'automatic-git-policy'
        self.expected = f'/run/user/{os.getuid()}/credentials/obsidian-git-sync.service'
        self.stack.enter_context(mock.patch.dict(os.environ, {'CREDENTIALS_DIRECTORY': self.expected}))
        original_open = os.open
        def credential_open(path, flags, *args, **kwargs):
            if str(path) == self.expected:
                path = self.directory
            return original_open(path, flags, *args, **kwargs)
        self.stack.enter_context(mock.patch.object(SYNC.os, 'open', side_effect=credential_open))

    def test_enabled_and_disabled_credentials_do_not_inspect_unmapped_root(self):
        for enabled in ('true', 'false'):
            self.path.write_text('OBSIDIAN_GIT_AUTO_ENABLE=' + enabled + '\n')
            self.path.chmod(0o400)
            with mock.patch.object(Path, 'lstat', side_effect=AssertionError('host root is unmapped')):
                self.assertEqual(SYNC.auto_enabled(), enabled == 'true')
            self.path.chmod(0o600)

    def test_wrong_directory_does_not_fall_back_to_host_policy(self):
        with mock.patch.dict(os.environ, {'CREDENTIALS_DIRECTORY': str(self.directory)}):
            with self.assertRaisesRegex(SYNC.SyncError, 'unexpected'):
                SYNC.auto_enabled()

    def test_credential_links_and_writable_or_shared_modes_fail_closed(self):
        original = self.root / 'original'
        original.write_text('OBSIDIAN_GIT_AUTO_ENABLE=true\n')
        original.chmod(0o400)
        self.path.symlink_to(original)
        with self.assertRaises(OSError):
            SYNC.auto_enabled()
        self.path.unlink()
        os.link(original, self.path)
        with self.assertRaisesRegex(SYNC.SyncError, 'untrusted'):
            SYNC.auto_enabled()
        self.path.unlink()
        self.path.write_text(original.read_text())
        for mode in (0o600, 0o440, 0o444, 0o500):
            self.path.chmod(mode)
            with self.subTest(mode=oct(mode)), self.assertRaisesRegex(SYNC.SyncError, 'untrusted'):
                SYNC.auto_enabled()
        self.path.chmod(0o400)
        self.directory.chmod(0o750)
        with self.assertRaisesRegex(SYNC.SyncError, 'directory'):
            SYNC.auto_enabled()

    def test_missing_or_invalid_credential_never_enables_publication(self):
        with self.assertRaises(FileNotFoundError):
            SYNC.auto_enabled()
        for value in (b'', b'OBSIDIAN_GIT_AUTO_ENABLE=true\nextra', b'x' * 1024):
            self.path.write_bytes(value)
            self.path.chmod(0o400)
            with self.assertRaisesRegex(SYNC.SyncError, 'invalid'):
                SYNC.auto_enabled()
            self.path.chmod(0o600)


class TimerPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='obsidian-timer-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root/'target'
        self.links = []
        for home in ('etc/skel-desktop', 'home/test'):
            directory = self.target/home/'.config/systemd/user/labwc-session.target.wants'
            directory.mkdir(parents=True)
            self.links.append(directory/'obsidian-git-sync.timer')

    def run_policy(self, enabled):
        services = (SEED/'scripts/desktop/components/services.sh').read_text().replace('/target', str(self.target))
        validator = (SEED/'scripts/desktop/components/user-config.sh').read_text()
        stubs = '''
installer_fatal() { printf '%s\\n' "$*" >&2; exit 7; }
desktop_require_absolute_account_home() { [ "$ACCOUNT_HOME" = /home/test ]; }
desktop_stage_user_unit_wanted_by() { printf 'stage %s %s\\n' "$1" "$2"; }
desktop_log() { :; }
'''
        code = 'set -eu\n' + services + '\n' + validator + '\n' + stubs + '\nACCOUNT_USERNAME=test\nACCOUNT_HOME=/home/test\n'
        if enabled is not None:
            code += 'OBSIDIAN_GIT_AUTO_ENABLE=' + shlex.quote(enabled) + '\n'
        return subprocess.run(['/bin/sh', '-c', code + 'desktop_configure_obsidian_git_timer'],
                              text=True, capture_output=True, timeout=10,
                              env={'PATH': '/usr/bin:/bin'})

    def test_enabled_policy_stages_only_the_session_timer(self):
        result = self.run_policy('true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'stage obsidian-git-sync.timer labwc-session.target\n')

    def test_disabled_policy_removes_only_managed_links_and_is_idempotent(self):
        for link in self.links:
            link.symlink_to('../obsidian-git-sync.timer')
            (link.parent/'unrelated.timer').symlink_to('../unrelated.timer')
        for _ in range(2):
            result = self.run_policy('false')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('stage', result.stdout)
            for link in self.links:
                self.assertFalse(link.exists() or link.is_symlink())
                self.assertTrue((link.parent/'unrelated.timer').is_symlink())

    def test_unmanaged_entry_fails_before_either_link_is_removed(self):
        self.links[0].symlink_to('../obsidian-git-sync.timer')
        self.links[1].write_text('administrator entry\n')
        result = self.run_policy('false')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.links[0].is_symlink())
        self.assertEqual(self.links[1].read_text(), 'administrator entry\n')

    def test_symlinked_ancestor_is_rejected_before_removing_any_link(self):
        for link in self.links:
            link.symlink_to('../obsidian-git-sync.timer')
        config = self.target/'home/test/.config'
        saved = self.root/'saved-config'
        config.rename(saved)
        config.symlink_to(saved, target_is_directory=True)
        result = self.run_policy('false')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.links[0].is_symlink())
        self.assertTrue((saved/'systemd/user/labwc-session.target.wants/obsidian-git-sync.timer').is_symlink())

    def test_missing_and_non_boolean_flags_are_rejected(self):
        for value in (None, '', 'yes', 'TRUE', '1', 'false\n'):
            with self.subTest(value=value):
                result = self.run_policy(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('stage', result.stdout)


class PublicationPolicyTests(unittest.TestCase):
    def test_publisher_rejects_missing_duplicate_or_unsafe_automation_flags(self):
        build = runpy.run_path(str(SEED.parents[1]/'tools/build.py'))
        validate = build['validate_obsidian_git_profiles']
        with tempfile.TemporaryDirectory(prefix='obsidian-publication-') as directory:
            seed = Path(directory)
            profiles = seed/'hosts/profiles'
            profiles.mkdir(parents=True)
            profile = profiles/'example.env'
            with mock.patch.dict(validate.__globals__, {'SEED': seed}):
                for value in ('true', 'false'):
                    profile.write_text('OBSIDIAN_GIT_AUTO_ENABLE="' + value + '"\n')
                    validate()
                for text in ('', 'OBSIDIAN_GIT_AUTO_ENABLE="yes"\n',
                             'OBSIDIAN_GIT_AUTO_ENABLE=true\n',
                             'OBSIDIAN_GIT_AUTO_ENABLE="false"\nOBSIDIAN_GIT_AUTO_ENABLE="true"\n',
                             'OBSIDIAN_GIT_AUTO_ENABLE="$(id)"\n'):
                    profile.write_text(text)
                    with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'OBSIDIAN_GIT_AUTO_ENABLE'):
                        validate()


if __name__ == '__main__':
    unittest.main()
