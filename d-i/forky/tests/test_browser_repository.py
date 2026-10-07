#!/usr/bin/env python3
"""Browser clone, publication and Codex permission regressions; no vendor access."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SEED = Path(__file__).resolve().parents[1]
ROOT = SEED.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SSH = load('netscape_installer', SEED/'scripts/late/ssh/ssh-install.py')
BUILD = load('netscape_build', ROOT/'tools/build.py')
BROWSER = load('netscape_browser', ROOT/'tools/build_browser_config.py')


class CodexModeTests(unittest.TestCase):
    def test_real_publisher_accepts_private_settings_mode_and_clears_special_bits(self):
        text = (SEED/'scripts/late/devops/codex-release.sh').read_text()
        start = text.index('codex_chmod_without_special_bits() {')
        end = text.index('\ncodex_chmod_group_shared()', start)
        function = text[start:end]
        shells = [['/bin/sh']]
        if shutil.which('busybox'):
            shells.append([shutil.which('busybox'), 'sh'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            path.write_text('{}\n')
            for shell in shells:
                with self.subTest(shell=shell):
                    path.chmod(0o6755)
                    program = ('codex_fatal() { printf "%s\\n" "$*" >&2; exit 1; };\n'
                               + function + '\ncodex_chmod_without_special_bits "$1" "$2"')
                    good = subprocess.run([*shell, '-eu', '-c', program, 'mode-test', '0600', str(path)],
                                          capture_output=True, text=True)
                    self.assertEqual(good.returncode, 0, good.stderr)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    for forbidden in ('0666', '0777', '0640'):
                        bad = subprocess.run([*shell, '-eu', '-c', program, 'mode-test', forbidden, str(path)],
                                             capture_output=True, text=True)
                        self.assertNotEqual(bad.returncode, 0)
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class BrowserPolicyTests(unittest.TestCase):
    def test_profile_policy_rejects_missing_duplicate_injected_and_commit_pins(self):
        good = ('BROWSER_NETSCAPE_REPOSITORY_URL="' + SSH.NETSCAPE_URL + '"\n'
                'BROWSER_NETSCAPE_REPOSITORY_BRANCH="mcr/main"\n'
                'BROWSER_NETSCAPE_DIRECTORY="Workspace/netscape"\n')
        bad = [good.replace('mcr/main', 'main'), good.replace(SSH.NETSCAPE_URL, 'https://gitlab.com/other.git'),
               good.replace('Workspace/netscape', '../netscape'),
               good + 'BROWSER_NETSCAPE_REPOSITORY_BRANCH="mcr/main"\n',
               good + 'BROWSER_NETSCAPE_REPOSITORY_SHA256="' + 'a'*64 + '"\n',
               good.replace('"mcr/main"', '"$(false)"'), '']
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory)
            profiles = seed/'hosts/profiles'; profiles.mkdir(parents=True)
            path = profiles/'fixture.env'
            with mock.patch.object(BUILD, 'SEED', seed):
                path.write_text(good)
                BUILD.validate_browser_repository_profiles()
                for text in bad:
                    with self.subTest(text=text):
                        path.write_text(text)
                        with self.assertRaises(ValueError):
                            BUILD.validate_browser_repository_profiles()
                        self.assertEqual(path.read_text(), text)

    def test_no_profiles_is_a_publication_error(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(BUILD, 'SEED', Path(directory)):
            with self.assertRaises(ValueError):
                BUILD.validate_browser_repository_profiles()

    def test_managed_storage_and_locked_extension_options_are_rejected(self):
        original = json.loads((BROWSER.CONFIG/'policies.json').read_text())
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(BROWSER, 'CONFIG', Path(directory)):
            path = Path(directory)/'policies.json'
            for mutation in ('managed-storage', 'file-urls', 'force-install', 'wrong-id', 'duplicate-key'):
                with self.subTest(mutation=mutation):
                    data = json.loads(json.dumps(original))
                    if mutation == 'managed-storage':
                        data['extensions']['3rdparty'] = {'extensions': {BROWSER.BADGER: {'learnLocally': False}}}
                    elif mutation == 'file-urls':
                        data['extensions']['ExtensionSettings'][BROWSER.NOSCRIPT]['file_url_navigation_allowed'] = False
                    elif mutation == 'force-install':
                        data['extensions']['ExtensionSettings'][BROWSER.UBOL]['installation_mode'] = 'force_installed'
                    elif mutation == 'wrong-id':
                        data['extensions']['ExtensionSettings']['a'*32] = data['extensions']['ExtensionSettings'].pop(BROWSER.UBOL)
                    value = json.dumps(data)
                    if mutation == 'duplicate-key':
                        value = value.replace('"security":', '"security": {}, "security":', 1)
                    path.write_text(value)
                    with self.assertRaises(ValueError):
                        BROWSER.generate()

    def test_all_ten_profiles_and_target_staging_are_wired(self):
        profiles = list((SEED/'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        BUILD.validate_browser_repository_profiles()
        text = (SEED/'scripts/desktop/components/user-config.sh').read_text()
        self.assertLess(text.index('  desktop_bootstrap_primary_account_gpg_key\n'),
                        text.index('  desktop_install_browser_repository\n'))
        self.assertIn('managed_git_ssh_target_action clone-netscape', text)
        self.assertIn('--repository-url "$BROWSER_NETSCAPE_REPOSITORY_URL"', text)
        self.assertIn('--repository-branch "$BROWSER_NETSCAPE_REPOSITORY_BRANCH"', text)
        self.assertIn('|clone-netscape)', (SEED/'scripts/common/ssh.sh').read_text())
        staging = (SEED/'scripts/desktop/components/target-assets.sh').read_text()
        for family in BROWSER.FAMILIES:
            self.assertIn(f'desktop_stage_role_asset {family}/policies/managed/extensions.json '
                          f'/{family}/policies/managed/extensions.json 0644', staging)
        self.assertNotIn('browser-imports', staging)
        verifier = (SEED/'scripts/desktop/verify.sh.tmpl').read_text()
        self.assertNotIn('browser-imports', verifier)
        for family in BROWSER.FAMILIES:
            self.assertIn(f'/{family}/policies/managed/extensions.json', verifier)
        self.assertIn('"$account_home/Workspace/netscape/.git"', verifier)

    def test_served_source_permission_contract(self):
        paths = [p for p in ROOT.iterdir() if p.is_file()]
        for scope in ('browser-config', 'd-i', 'docs', 'tools'):
            paths.extend(p for p in (ROOT/scope).rglob('*')
                         if not {'__pycache__', '.build', '.git', '.pytest_cache'} & set(p.relative_to(ROOT).parts))
        for path in paths:
            if path.is_file():
                self.assertFalse(path.is_symlink(), str(path))
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644, str(path))
                self.assertEqual(path.stat().st_nlink, 1, str(path))
            elif path.is_dir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755, str(path))


class InstalledBrowserVerifierTests(unittest.TestCase):
    def test_real_verifier_accepts_only_complete_private_branch_checkout(self):
        text = (SEED/'scripts/desktop/verify.sh.tmpl').read_text()
        block = text[text.index('# Browser exports are account-owned Git data,'):
                     text.index('# The encrypted identity and sealed passphrase')]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home/'Workspace/netscape'
            (root/'.git').mkdir(parents=True)
            head = root/'.git/HEAD'; head.write_text('ref: refs/heads/mcr/main\n')
            export = root/'export.json'; export.write_text('{}\n')
            for path in (root.parent, root, root/'.git'):
                path.chmod(0o700)
            head.chmod(0o600); export.chmod(0o600)
            program = ('fatal() { printf "%s\\n" "$*" >&2; exit 1; };\n'
                       'check_required_owned() { [ -f "$1" ] || fatal "missing file"; };\n'
                       'check_required_owned_dir() { [ -d "$1" ] || fatal "missing directory"; };\n'
                       'account_home=$1; uid=$(id -u); gid=$(id -g);\n' + block)
            def verify():
                return subprocess.run(['/bin/sh', '-eu', '-c', program, 'verifier-test', str(home)],
                                      capture_output=True, text=True)
            self.assertEqual(verify().returncode, 0)
            export.chmod(0o640)
            self.assertNotEqual(verify().returncode, 0)
            export.chmod(0o600)
            head.write_text('ref: refs/heads/main\n')
            self.assertNotEqual(verify().returncode, 0)
            head.write_text('ref: refs/heads/mcr/main\n')
            export.unlink(); export.symlink_to(head)
            self.assertNotEqual(verify().returncode, 0)


class PrivateCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'; self.source.mkdir()
        self.target = self.root/'target'; self.target.mkdir()

    def copy(self):
        source = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        target = os.open(self.target, os.O_RDONLY | os.O_DIRECTORY)
        try:
            SSH.copy_private_checkout(source, target, os.getuid(), os.getgid())
        finally:
            os.close(source); os.close(target)

    def test_real_copy_preserves_bytes_git_metadata_and_private_modes(self):
        (self.source/'.git').mkdir()
        (self.source/'.git/config').write_text('[remote "origin"]\nurl = ' + SSH.NETSCAPE_URL + '\n')
        (self.source/'noscript.json').write_text('{"local": {}}\n')
        (self.source/'tool').write_text('#!/bin/sh\nexit 0\n')
        (self.source/'tool').chmod(0o6755)
        self.copy()
        for path in self.target.rglob('*'):
            self.assertEqual(path.stat().st_uid, os.getuid())
            self.assertEqual(path.stat().st_gid, os.getgid())
            expected = 0o700 if path.is_dir() or path.name == 'tool' else 0o600
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected)
            if path.is_file():
                self.assertEqual(path.read_bytes(), (self.source/path.relative_to(self.target)).read_bytes())
                self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o700)

    def test_symlink_hardlink_and_fifo_are_rejected(self):
        for kind in ('symlink', 'hardlink', 'fifo'):
            with self.subTest(kind=kind):
                path = self.source/'unsafe'
                if kind == 'symlink':
                    path.symlink_to('/etc/passwd')
                elif kind == 'hardlink':
                    outside = self.root/'outside'; outside.write_text('preserve')
                    os.link(outside, path)
                else:
                    os.mkfifo(path)
                try:
                    with self.assertRaises(SSH.InstallError):
                        self.copy()
                    self.assertFalse((self.target/'unsafe').exists())
                finally:
                    path.unlink()

    def test_existing_destination_is_never_followed_or_overwritten(self):
        (self.source/'export.json').write_text('new')
        outside = self.root/'outside'; outside.write_text('preserve')
        (self.target/'export.json').symlink_to(outside)
        with self.assertRaises(FileExistsError):
            self.copy()
        self.assertEqual(outside.read_text(), 'preserve')

    def test_pinned_destination_survives_parent_path_substitution(self):
        (self.source/'export.json').write_text('new')
        source = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        target = os.open(self.target, os.O_RDONLY | os.O_DIRECTORY)
        try:
            saved = self.root/'saved'; self.target.rename(saved)
            outside = self.root/'outside'; outside.mkdir()
            self.target.symlink_to(outside, target_is_directory=True)
            SSH.copy_private_checkout(source, target, os.getuid(), os.getgid())
            self.assertEqual((saved/'export.json').read_text(), 'new')
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            os.close(source); os.close(target)


@unittest.skipUnless(shutil.which('git'), 'Git is required for the local transport fixture')
class NetscapeGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root/'stage'; self.stage.mkdir(mode=0o700)
        self.source = self.root/'remote'; self.source.mkdir()
        self.env = dict(SSH.BASE_ENV, HOME=str(self.root), GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_AUTHOR_NAME='Fixture',
                        GIT_AUTHOR_EMAIL='fixture@example.invalid', GIT_COMMITTER_NAME='Fixture',
                        GIT_COMMITTER_EMAIL='fixture@example.invalid')
        self.git('init', '--initial-branch=mcr/main', str(self.source))
        (self.source/'noscript.json').write_text('{}\n')
        self.git('-C', str(self.source), 'add', '.')
        self.git('-C', str(self.source), 'commit', '-m', 'fixture')
        (self.stage/'clone.conf.tmpl').write_bytes((SEED/'scripts/late/ssh/clone.conf.tmpl').read_bytes())
        (self.stage/'clone.conf.tmpl').chmod(0o600)
        self.transport = self.root/'ssh-fixture'
        self.transport.write_text('#!/bin/sh\nset -eu\n'
            '[ "$1" = -F ] && [ -f "$2" ] || exit 71\nshift 2\n'
            'if [ "${1:-}" = -o ]; then [ "$2" = SendEnv=GIT_PROTOCOL ] || exit 72; shift 2; fi\n'
            '[ "$1" = git@gitlab.com ] || exit 73\n'
            '[ "$2" = "git-upload-pack \'core-assets/helpers/netscape.git\'" ] || exit 74\n'
            'exec ' + shlex.quote(shutil.which('git-upload-pack')) + ' ' + shlex.quote(str(self.source)) + '\n')
        self.transport.chmod(0o755)

    def git(self, *args):
        result = subprocess.run([shutil.which('git'), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_real_git_checkout_tracks_branch_without_persistent_agent_or_commit_pin(self):
        checked = SSH.checked
        calls = []
        def local_checked(argv, **kwargs):
            calls.append((argv, kwargs.copy()))
            if 'GIT_SSH_COMMAND' in kwargs.get('env', {}):
                environment = dict(kwargs['env'])
                environment['GIT_SSH_COMMAND'] = shlex.quote(str(self.transport)) + ' -F ' + shlex.quote(str(self.stage/'ssh_config'))
                kwargs['env'] = environment
            return checked(argv, **kwargs)
        destination = self.stage/'repository'
        with mock.patch.object(SSH, '__file__', str(self.stage/'ssh-install.py')), \
             mock.patch.object(SSH, 'checked', side_effect=local_checked):
            SSH.clone(destination, self.stage, dict(self.env, SSH_AUTH_SOCK='/fixture/agent.sock'),
                      url=SSH.NETSCAPE_URL, branch=SSH.NETSCAPE_BRANCH)
        self.assertEqual(self.git('-C', str(destination), 'symbolic-ref', '--short', 'HEAD'), 'mcr/main')
        self.assertEqual(self.git('-C', str(destination), 'rev-parse', '--abbrev-ref', '@{upstream}'), 'origin/mcr/main')
        self.assertEqual(self.git('-C', str(destination), 'remote', 'get-url', 'origin'), SSH.NETSCAPE_URL)
        self.assertEqual((destination/'noscript.json').read_text(), '{}\n')
        config = (destination/'.git/config').read_text()
        self.assertNotIn('ssh-fixture', config)
        self.assertNotIn('agent.sock', config)
        self.assertNotIn('hooksPath', config)
        self.assertEqual(stat.S_IMODE((self.stage/'ssh_config').stat().st_mode), 0o600)
        clone, options = calls[0]
        self.assertIn('core.hooksPath=/dev/null', clone)
        self.assertIn('--template=', clone)
        self.assertIn('--no-hardlinks', clone)
        self.assertEqual(options['umask'], 0o022)
        self.assertEqual(options['env']['GIT_CONFIG_GLOBAL'], '/dev/null')
        for option in ('StrictHostKeyChecking yes', 'ForwardAgent no', 'BatchMode yes'):
            self.assertIn(option, (self.stage/'ssh_config').read_text())

    def test_unapproved_repository_or_branch_never_starts_git(self):
        with mock.patch.object(SSH, 'checked') as checked:
            for url, branch in ((SSH.NETSCAPE_URL, 'main'), ('https://gitlab.com/netscape.git', 'mcr/main')):
                with self.assertRaises(SSH.InstallError):
                    SSH.clone(self.stage/'repository', self.stage, {}, url=url, branch=branch)
            checked.assert_not_called()


class NetscapePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root/'home'; self.home.mkdir(mode=0o700)
        self.stage = self.root/'stage'; self.stage.mkdir(mode=0o700)
        self.account = SimpleNamespace(pw_uid=65534, pw_gid=65534)
        try:
            os.chown(self.home, self.account.pw_uid, self.account.pw_gid)
        except OSError as exc:
            self.skipTest(f'real non-root ownership changes unavailable: {exc}')

    def clone_fixture(self, destination, stage, environment, **kwargs):
        self.assertEqual(kwargs, {'url': SSH.NETSCAPE_URL, 'branch': 'mcr/main'})
        (destination/'.git').mkdir(parents=True)
        (destination/'.git/config').write_text('fixture')
        (destination/'export.json').write_text('{}\n')

    def install(self):
        return SSH.clone_netscape(self.account, self.home, self.stage, {},
                                  url=SSH.NETSCAPE_URL, branch='mcr/main')

    def test_complete_checkout_has_private_account_ownership_and_no_staging(self):
        with mock.patch.object(SSH, 'clone', side_effect=self.clone_fixture):
            self.install()
        checkout = self.home/'Workspace/netscape'
        for path in (checkout.parent, checkout, *checkout.rglob('*')):
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), (65534, 65534))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
        self.assertFalse(list(checkout.parent.glob('.netscape-clone.*')))

    def test_existing_checkout_and_symlinked_workspace_are_preserved(self):
        workspace = self.home/'Workspace'; workspace.mkdir(mode=0o700)
        os.chown(workspace, 65534, 65534)
        final = workspace/'netscape'; final.mkdir()
        (final/'user.json').write_text('preserve')
        with mock.patch.object(SSH, 'clone') as clone:
            with self.assertRaises(SSH.InstallError):
                self.install()
            clone.assert_not_called()
        self.assertEqual((final/'user.json').read_text(), 'preserve')
        shutil.rmtree(workspace)
        workspace.symlink_to(self.stage, target_is_directory=True)
        with self.assertRaises(OSError):
            self.install()

    def test_invalid_entries_do_not_publish_partial_checkout(self):
        def unsafe(*args, **kwargs):
            self.clone_fixture(*args, **kwargs)
            (args[0]/'unsafe').symlink_to('/etc/passwd')
        with mock.patch.object(SSH, 'clone', side_effect=unsafe):
            with self.assertRaises(SSH.InstallError):
                self.install()
        workspace = self.home/'Workspace'
        self.assertFalse((workspace/'netscape').exists())
        self.assertFalse(list(workspace.glob('.netscape-clone.*')))

    def test_concurrent_checkout_is_never_replaced(self):
        copy = SSH.copy_private_checkout
        def concurrent(source, destination, uid, gid):
            copy(source, destination, uid, gid)
            final = self.home/'Workspace/netscape'; final.mkdir()
            (final/'user.json').write_text('preserve')
        with mock.patch.object(SSH, 'clone', side_effect=self.clone_fixture), \
             mock.patch.object(SSH, 'copy_private_checkout', side_effect=concurrent):
            with self.assertRaises(OSError):
                self.install()
        workspace = self.home/'Workspace'
        self.assertEqual((workspace/'netscape/user.json').read_text(), 'preserve')
        self.assertFalse(list(workspace.glob('.netscape-clone.*')))

class DescriptorPublicationTests(NetscapePublicationTests):
    """Real copies/renames with simulated ownership; native ownership stays separate."""
    def setUp(self):
        owners = {}
        real_stat, real_fstat = os.stat, os.fstat
        def annotate(info):
            owner = owners.get((info.st_dev, info.st_ino))
            if owner is None:
                return info
            fields = list(info)
            fields[4], fields[5] = owner
            return os.stat_result(fields)
        def chown(path, uid, gid, **kwargs):
            info = real_stat(path, **kwargs)
            owners[(info.st_dev, info.st_ino)] = (uid, gid)
        def fchown(fd, uid, gid):
            info = real_fstat(fd)
            owners[(info.st_dev, info.st_ino)] = (uid, gid)
        for name, effect in (('stat', lambda *a, **kw: annotate(real_stat(*a, **kw))),
                             ('fstat', lambda fd: annotate(real_fstat(fd))),
                             ('chown', chown), ('fchown', fchown)):
            patcher = mock.patch.object(os, name, side_effect=effect)
            patcher.start()
            self.addCleanup(patcher.stop)
        super().setUp()


if __name__ == '__main__':
    unittest.main()
