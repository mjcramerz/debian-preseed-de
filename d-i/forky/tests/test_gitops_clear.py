"""Destructive clear operations against disposable local Git/bare fixtures only.

No provider API, real checkout, user branch, network service or hosted remote
is changed. Git commits, transactions, transport and garbage collection are real.
"""
from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SEED = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('gitops_clear_tests', str(SEED/'hooks/target/usr/local/bin/gitops'))
spec = importlib.util.spec_from_loader(loader.name, loader)
g = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = g
loader.exec_module(g)


class ClearFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gitops-clear-fixture-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base/'work'
        self.remote = self.base/'origin.git'
        self.root.mkdir()
        self.raw('init', '-q', '--initial-branch=mcr/main')
        self.raw('config', 'user.name', 'Fixture User')
        self.raw('config', 'user.email', 'fixture@example.invalid')
        self.first = self.commit('first')
        self.boundary = self.commit('boundary')
        self.raw('tag', '-a', 'keep-oldest', '-m', 'oldest annotation')
        self.middle = self.commit('middle')
        self.raw('tag', 'discard')
        self.tip = self.commit('latest')
        self.raw('tag', '-a', 'keep-latest', '-m', 'latest annotation')
        for branch in ('mcr/staging', 'mcr/release', 'feature/old'):
            self.raw('branch', branch, self.middle)
        self.raw('init', '--bare', '-q', '--initial-branch=mcr/main', str(self.remote))
        self.raw('remote', 'add', 'origin', str(self.remote))
        self.raw('push', '-q', 'origin', '--all')
        self.raw('push', '-q', 'origin', '--tags')
        self.before_tree = self.raw('rev-parse', 'HEAD^{tree}').strip()
        self.output = io.StringIO()
        quiet = contextlib.redirect_stdout(self.output)
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def raw(self, *arguments, cwd=None, check=True):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', LC_ALL='C')
        result = subprocess.run(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', *arguments],
                                cwd=cwd or self.root, env=environment, capture_output=True,
                                text=True, encoding='utf-8', timeout=30)
        if check and result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout if check else result

    def commit(self, text):
        (self.root/'file').write_text(text+'\n', encoding='utf-8')
        self.raw('add', '--', 'file')
        self.raw('-c', 'commit.gpgsign=false', 'commit', '-qm', text)
        return self.raw('rev-parse', 'HEAD').strip()

    def clear(self, branches=True, apply=True, keep=(), none=False):
        g.clear_repository(self.root, 'branch-clear' if branches else 'tag-clear', apply, list(keep), none)

    def assert_final_branches(self):
        local = self.raw('for-each-ref', '--format=%(refname)', 'refs/heads/').splitlines()
        self.assertEqual(set(local), {'refs/heads/'+name for name in g.BRANCHES})
        self.assertEqual(self.raw('symbolic-ref', 'HEAD').strip(), 'refs/heads/mcr/main')
        self.assertEqual(self.raw('rev-parse', 'HEAD^{tree}').strip(), self.before_tree)
        self.assertEqual(self.raw('status', '--porcelain'), '')
        self.assertFalse((self.root/'.git/gitops-clear.json').exists())
        backups = list((self.root/'.git').glob('gitops-clear-*/recovery.bundle'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.raw('bundle', 'verify', str(backups[0]))

    @contextlib.contextmanager
    def configured_github_mirror(self):
        """Run the mirror CLI path; redirect provider transports to local bares."""
        self.gitlab_url = 'git@gitlab.com:fixture-group/project.git'
        self.github_url = 'git@github.com:fixture-owner/project.git'
        self.github = self.base/'github.git'
        self.raw('init', '--bare', '-q', '--initial-branch=old-default', str(self.github))
        self.raw('push', '-q', str(self.github), 'HEAD:refs/heads/old-default',
                 'HEAD:refs/heads/old-feature', 'refs/tags/discard:refs/tags/old-setup-tag')
        self.raw('remote', 'set-url', 'origin', self.gitlab_url)
        real_git = g.git
        destinations = {self.gitlab_url: str(self.remote), self.github_url: str(self.github)}
        self.provider_calls = []

        def transport(*arguments, **kwargs):
            operation = 0
            while operation < len(arguments) and arguments[operation] == '-c':
                operation += 2
            if operation < len(arguments) and arguments[operation] in ('fetch', 'push', 'ls-remote'):
                arguments = tuple(destinations.get(value, value) for value in arguments)
                if any('github.com:' in value or 'gitlab.com:' in value for value in arguments):
                    raise AssertionError('unexpected provider transport in local fixture')
            return real_git(*arguments, **kwargs)

        def api(provider, method, endpoint, body=None, **kwargs):
            self.provider_calls.append((provider, method, endpoint, body))
            self.assertEqual(provider, 'gh')
            self.assertEqual(endpoint, 'repos/fixture-owner/project')
            if method == 'PATCH':
                self.assertEqual(body, {'default_branch': 'mcr/main'})
                self.raw('rev-parse', '--verify', 'refs/heads/mcr/main', cwd=self.github)
                self.raw('symbolic-ref', 'HEAD', 'refs/heads/mcr/main', cwd=self.github)
            else:
                self.assertEqual(method, 'GET')
            return {'id': 1, 'private': True, 'full_name': 'fixture-owner/project',
                    'ssh_url': self.github_url,
                    'default_branch': self.raw('symbolic-ref', 'HEAD', cwd=self.github).strip().removeprefix('refs/heads/')}

        with mock.patch.object(g, 'git', side_effect=transport), mock.patch.object(g, 'provider_api', side_effect=api):
            original_directory = Path.cwd()
            try:
                os.chdir(self.root)
                with mock.patch.object(g.os, 'geteuid', return_value=1000):
                    self.assertEqual(g._main(['mcr-repo-mirror', 'gh', 'fixture-owner', '--apply']), 0)
            finally:
                os.chdir(original_directory)
            self.assertEqual(g.clear_remotes(self.root), [('origin', self.gitlab_url), ('mirror-gh', self.github_url)])
            self.assertEqual(self.raw('config', '--get', 'remote.mirror-gh.gitopsManaged').strip(), 'true')
            self.assertEqual(self.raw('config', '--get', 'remote.mirror-gh.skipFetchAll').strip(), 'true')
            self.assertEqual(self.raw('config', '--get', 'remote.mirror-gh.fetch', check=False).returncode, 1)
            self.assertEqual(g.remote_refs(self.root, self.github_url), g.promotion_tips(self.root))
            yield

    def test_configured_github_mirror_previews_preserve_both_providers_and_config(self):
        with self.configured_github_mirror():
            local = g.all_refs(self.root)
            remotes = [g.remote_refs(self.root, url) for url in (self.gitlab_url, self.github_url)]
            config = (self.root/'.git/config').read_bytes()
            for branches in (True, False):
                self.clear(branches=branches, apply=False, none=True)
            self.assertEqual(g.all_refs(self.root), local)
            self.assertEqual([g.remote_refs(self.root, url) for url in (self.gitlab_url, self.github_url)], remotes)
            self.assertEqual((self.root/'.git/config').read_bytes(), config)
            self.assertIn('mirror-gh', self.output.getvalue())

    def test_configured_github_mirror_branch_clear_prunes_both_providers(self):
        with self.configured_github_mirror():
            self.raw('push', '-q', str(self.github), 'HEAD:refs/heads/github-old',
                     'refs/tags/discard:refs/tags/github-discard')
            self.clear(none=True)
            self.assert_final_branches()
            expected = g.promotion_tips(self.root)
            self.assertEqual(g.remote_refs(self.root, self.gitlab_url), expected)
            self.assertEqual(g.remote_refs(self.root, self.github_url), expected)
            self.assertEqual(self.raw('rev-list', '--count', 'HEAD').strip(), '1')
            self.assertNotEqual(self.raw('cat-file', '-e', self.first, check=False).returncode, 0)

    def test_configured_github_mirror_branch_clear_rewrites_remote_only_kept_tag(self):
        with self.configured_github_mirror():
            self.raw('push', '-q', str(self.github), self.boundary+':refs/tags/github-oldest')
            self.clear(keep=['github-oldest', 'keep-latest'])
            self.assert_final_branches()
            expected = {ref: oid for ref, oid in g.all_refs(self.root).items()
                        if ref.startswith(('refs/heads/', 'refs/tags/'))}
            self.assertEqual(g.remote_refs(self.root, self.gitlab_url), expected)
            self.assertEqual(g.remote_refs(self.root, self.github_url), expected)
            self.assertEqual(self.raw('tag', '--list').splitlines(), ['github-oldest', 'keep-latest'])
            self.assertEqual(self.raw('show', '-s', '--format=%P', 'github-oldest').strip(), '')
            self.assertIn('latest annotation', self.raw('cat-file', '-p', 'keep-latest'))
            self.assertEqual(self.raw('rev-list', '--count', 'HEAD').strip(), '3')

    def test_configured_github_mirror_tag_clear_preserves_selected_tags_and_histories(self):
        with self.configured_github_mirror():
            self.raw('push', '-q', str(self.github), 'refs/tags/keep-oldest', 'refs/tags/discard',
                     self.boundary+':refs/tags/github-only')
            urls = (self.gitlab_url, self.github_url)
            before = [g.remote_refs(self.root, url) for url in urls]
            selected = {'refs/tags/keep-oldest', 'refs/tags/github-only'}
            self.clear(branches=False, keep=['keep-oldest', 'github-only'])
            for url, refs in zip(urls, before):
                self.assertEqual(g.remote_refs(self.root, url),
                                 {ref: oid for ref, oid in refs.items() if not ref.startswith('refs/tags/') or ref in selected})
            self.assertEqual(self.raw('tag', '--list').strip(), 'keep-oldest')
            self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
            self.assertEqual(self.raw('rev-list', '--count', 'HEAD').strip(), '4')

    def test_configured_github_mirror_tag_clear_removes_all_tags_on_both_providers(self):
        with self.configured_github_mirror():
            self.raw('push', '-q', '--tags', str(self.github))
            before = [g.remote_refs(self.root, url) for url in (self.gitlab_url, self.github_url)]
            self.clear(branches=False, none=True)
            for url, refs in zip((self.gitlab_url, self.github_url), before):
                self.assertEqual(g.remote_refs(self.root, url),
                                 {ref: oid for ref, oid in refs.items() if ref.startswith('refs/heads/')})
            self.assertEqual(self.raw('tag', '--list'), '')
            self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)

    def test_github_tag_clear_preserves_an_unfetched_independent_branch(self):
        with self.configured_github_mirror():
            other = self.base/'github-writer'
            self.raw('clone', '-q', '--', str(self.github), str(other))
            self.raw('config', 'user.name', 'GitHub Fixture Writer', cwd=other)
            self.raw('config', 'user.email', 'writer@example.invalid', cwd=other)
            (other/'independent').write_text('GitHub-only branch content\n', encoding='utf-8')
            self.raw('add', '--', 'independent', cwd=other)
            self.raw('-c', 'commit.gpgsign=false', 'commit', '-qm', 'Independent GitHub change', cwd=other)
            foreign = self.raw('rev-parse', 'HEAD', cwd=other).strip()
            self.raw('push', '-q', 'origin', 'HEAD:refs/heads/github-independent', cwd=other)
            self.raw('push', '-q', '--tags', str(self.github))
            before = g.remote_refs(self.root, self.github_url)
            self.assertNotEqual(self.raw('cat-file', '-e', foreign, check=False).returncode, 0)
            self.clear(branches=False, none=True)
            self.assertEqual(g.remote_refs(self.root, self.github_url),
                             {ref: oid for ref, oid in before.items() if ref.startswith('refs/heads/')})
            self.assertNotEqual(self.raw('cat-file', '-e', foreign, check=False).returncode, 0)
            self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)

    def test_configured_github_mirror_branch_clear_failure_resumes_saved_plan(self):
        with self.configured_github_mirror():
            self.raw('push', '-q', str(self.github), 'HEAD:refs/heads/github-old')
            self.raw('config', 'receive.denyDeletes', 'true', cwd=self.github)
            before = g.remote_refs(self.root, self.github_url)
            with self.assertRaises(g.GitOpsError):
                self.clear(keep=['keep-oldest', 'keep-latest'])
            self.assertEqual(g.remote_refs(self.root, self.github_url), before)
            self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
            self.assertTrue((self.root/'.git/gitops-clear.json').is_file())
            origin = g.remote_refs(self.root, self.gitlab_url)
            self.raw('config', 'receive.denyDeletes', 'false', cwd=self.github)
            self.clear(none=True)
            self.assert_final_branches()
            self.assertEqual(g.remote_refs(self.root, self.gitlab_url), origin)
            self.assertEqual(g.remote_refs(self.root, self.github_url), origin)
            self.assertEqual(self.raw('tag', '--list').splitlines(), ['keep-latest', 'keep-oldest'])

    def test_configured_github_mirror_tag_clear_failure_resumes_saved_plan(self):
        with self.configured_github_mirror():
            self.raw('push', '-q', '--tags', str(self.github))
            urls = (self.gitlab_url, self.github_url)
            before = [g.remote_refs(self.root, url) for url in urls]
            publish = g.leased_mirror_push
            def reject_github(root, url, old, desired, **kwargs):
                if url == self.github_url:
                    raise g.GitOpsError('fixture GitHub tag deletion rejected')
                return publish(root, url, old, desired, **kwargs)
            with mock.patch.object(g, 'leased_mirror_push', side_effect=reject_github):
                with self.assertRaisesRegex(g.GitOpsError, 'tag deletion rejected'):
                    self.clear(branches=False, keep=['keep-oldest'])
            self.assertEqual(g.remote_refs(self.root, self.github_url), before[1])
            self.assertEqual(self.raw('tag', '--list').splitlines(), ['discard', 'keep-latest', 'keep-oldest'])
            self.assertTrue((self.root/'.git/gitops-clear.json').is_file())
            self.clear(branches=False, none=True)
            for url, refs in zip(urls, before):
                self.assertEqual(g.remote_refs(self.root, url),
                                 {ref: oid for ref, oid in refs.items() if not ref.startswith('refs/tags/') or ref == 'refs/tags/keep-oldest'})
            self.assertEqual(self.raw('tag', '--list').strip(), 'keep-oldest')
            self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)

    def test_origin_change_during_github_publication_stops_local_clear(self):
        with self.configured_github_mirror():
            publish = g.leased_mirror_push
            def concurrent_writer(root, url, before, after, **kwargs):
                publish(root, url, before, after, **kwargs)
                if url == self.github_url:
                    self.raw('update-ref', 'refs/heads/concurrent', self.first, cwd=self.remote)
            with mock.patch.object(g, 'leased_mirror_push', side_effect=concurrent_writer):
                with self.assertRaisesRegex(g.GitOpsError, 'origin.*changed'):
                    self.clear(none=True)
            self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
            self.assertTrue((self.root/'.git/gitops-clear.json').is_file())

    def test_github_change_during_local_gc_keeps_recovery_journal(self):
        with self.configured_github_mirror():
            transport = g.git
            def concurrent_writer(*arguments, **kwargs):
                result = transport(*arguments, **kwargs)
                if arguments == ('-c', 'gc.autoDetach=false', 'gc', '--prune=now'):
                    self.raw('update-ref', 'refs/heads/concurrent', self.first, cwd=self.github)
                return result
            with mock.patch.object(g, 'git', side_effect=concurrent_writer):
                with self.assertRaisesRegex(g.GitOpsError, 'mirror-gh.*changed'):
                    self.clear(none=True)
            self.assertTrue((self.root/'.git/gitops-clear.json').is_file())
            with self.assertRaisesRegex(g.GitOpsError, 'remote refs changed'):
                self.clear(none=True)

    def test_local_change_during_final_provider_verification_keeps_journal(self):
        with self.configured_github_mirror():
            read_refs = g.remote_refs
            changed = False
            def concurrent_writer(root, url):
                nonlocal changed
                refs = read_refs(root, url)
                if not changed and url == self.github_url and g.resolve('HEAD', self.root) != self.tip:
                    self.raw('branch', 'concurrent')
                    changed = True
                return refs
            with mock.patch.object(g, 'remote_refs', side_effect=concurrent_writer):
                with self.assertRaisesRegex(g.GitOpsError, 'local clear result differs'):
                    self.clear(none=True)
            self.assertTrue(changed)
            self.assertTrue((self.root/'.git/gitops-clear.json').is_file())

    def test_preview_changes_no_refs_index_worktree_or_remote(self):
        before = g.all_refs(self.root)
        remote = g.remote_refs(self.root, str(self.remote))
        index = (self.root/'.git/index').read_bytes()
        content = (self.root/'file').read_bytes()
        self.clear(apply=False, keep=['keep-oldest', 'keep-latest'])
        self.assertEqual(g.all_refs(self.root), before)
        self.assertEqual(g.remote_refs(self.root, str(self.remote)), remote)
        self.assertEqual((self.root/'.git/index').read_bytes(), index)
        self.assertEqual((self.root/'file').read_bytes(), content)
        self.assertFalse(list((self.root/'.git').glob('gitops-clear-*')))
        self.assertIn('Preview only', self.output.getvalue())

    def test_no_kept_tags_creates_one_root_and_prunes_old_objects(self):
        self.clear(none=True)
        self.assert_final_branches()
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD').strip(), '1')
        self.assertEqual(self.raw('show', '-s', '--format=%P', 'HEAD').strip(), '')
        self.assertEqual(self.raw('tag', '--list'), '')
        self.assertNotEqual(self.raw('cat-file', '-e', self.first, check=False).returncode, 0)
        self.assertEqual(set(g.remote_refs(self.root, str(self.remote))), {'refs/heads/'+branch for branch in g.BRANCHES})
        self.assertFalse(self.raw('for-each-ref', '--format=%(refname)', 'refs/gitops/').strip())

    def test_multiple_kept_tags_rebase_from_oldest_and_keep_annotations(self):
        oldest_tree = self.raw('rev-parse', 'keep-oldest^{tree}').strip()
        self.clear(keep=['keep-oldest', 'keep-latest'])
        self.assert_final_branches()
        self.assertEqual(self.raw('tag', '--list').splitlines(), ['keep-latest', 'keep-oldest'])
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD').strip(), '3')
        self.assertEqual(self.raw('show', '-s', '--format=%P', 'keep-oldest^{}').strip(), '')
        self.assertEqual(self.raw('rev-parse', 'keep-oldest^{tree}').strip(), oldest_tree)
        self.assertEqual(self.raw('rev-parse', 'keep-latest^{}').strip(), self.raw('rev-parse', 'HEAD').strip())
        self.assertIn('oldest annotation', self.raw('cat-file', '-p', 'keep-oldest'))
        self.assertIn('latest annotation', self.raw('cat-file', '-p', 'keep-latest'))
        self.assertNotEqual(self.raw('cat-file', '-e', self.first, check=False).returncode, 0)
        self.assertEqual(g.remote_refs(self.root, str(self.remote)),
                         {ref: oid for ref, oid in g.all_refs(self.root).items() if ref.startswith(('refs/heads/', 'refs/tags/'))})

    def test_tag_clear_changes_only_local_remote_tag_refs(self):
        before = g.all_refs(self.root)
        remote = g.remote_refs(self.root, str(self.remote))
        kept = before['refs/tags/keep-oldest']
        self.clear(branches=False, keep=['keep-oldest'])
        self.assertEqual(g.all_refs(self.root), {ref: oid for ref, oid in before.items()
                         if not ref.startswith('refs/tags/') or ref == 'refs/tags/keep-oldest'})
        self.assertEqual(g.remote_refs(self.root, str(self.remote)), {ref: oid for ref, oid in remote.items()
                         if not ref.startswith('refs/tags/') or ref == 'refs/tags/keep-oldest'})
        self.assertEqual(self.raw('rev-parse', 'keep-oldest').strip(), kept)
        self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD').strip(), '4')

    def test_cli_alias_targets_dispatch_previews_and_apply(self):
        if os.geteuid() == 0:
            self.skipTest('CLI correctly refuses root; this fixture requires an ordinary account')
        aliases = SEED/'hooks/target/etc/gitops/aliases.gitconfig'
        before = g.all_refs(self.root)
        def invoke(command, apply=False):
            result = subprocess.run([sys.executable, '-I', '-B', str(SEED/'hooks/target/usr/local/bin/gitops'),
                                     command, '--keep-tag', 'keep-oldest', *(['--apply'] if apply else [])],
                                    cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        for command in ('mcr-tag-clear', 'mcr-branch-clear'):
            self.assertEqual(self.raw('config', '--file', str(aliases), '--get', 'alias.'+command).strip(),
                             '!/usr/local/bin/gitops '+command)
            self.assertIn('Preview only', invoke(command))
        self.assertEqual(g.all_refs(self.root), before)
        invoke('mcr-tag-clear', apply=True)
        self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
        self.assertEqual(self.raw('tag', '--list').strip(), 'keep-oldest')
        invoke('mcr-branch-clear', apply=True)
        self.assertEqual(set(self.raw('for-each-ref', '--format=%(refname)', 'refs/heads/').splitlines()),
                         {'refs/heads/'+name for name in g.BRANCHES})
        self.assertEqual(self.raw('rev-parse', 'HEAD^{tree}').strip(), self.before_tree)
        self.assertEqual(self.raw('show', '-s', '--format=%P', 'keep-oldest^{}').strip(), '')

    def test_split_origin_fetch_push_destinations_are_rejected(self):
        other = self.base/'other.git'
        self.raw('init', '-q', '--bare', str(other))
        self.raw('remote', 'set-url', '--push', 'origin', str(other))
        with self.assertRaisesRegex(g.GitOpsError, 'fetch and push the same'):
            self.clear(none=True)

    def test_unicode_branches_and_retained_tags_use_literal_utf8_refs(self):
        self.raw('branch', 'feature/older-\u2605')
        self.raw('tag', '-a', 'release-\u2605', '-m', 'retained annotation', self.boundary)
        self.raw('push', '-q', 'origin', '--all')
        self.raw('push', '-q', 'origin', '--tags')
        self.clear(keep=['release-\u2605'])
        self.assert_final_branches()
        self.assertEqual(self.raw('tag', '--list').strip(), 'release-\u2605')
        self.assertIn('retained annotation', self.raw('cat-file', '-p', 'release-\u2605'))

    def test_non_main_current_branch_is_recreated_as_main_without_checkout(self):
        self.raw('checkout', '-q', 'feature/old')
        self.before_tree = self.raw('rev-parse', 'HEAD^{tree}').strip()
        self.clear(none=True)
        self.assert_final_branches()

    def test_restricted_origin_fetch_is_repaired_for_new_tracking_branches(self):
        self.raw('config', '--replace-all', 'remote.origin.fetch',
                 '+refs/heads/feature/old:refs/remotes/origin/feature/old')
        self.clear(none=True)
        self.assert_final_branches()
        self.raw('fetch', '--no-tags', '--prune', 'origin')
        tracking = set(self.raw('for-each-ref', '--format=%(refname)', 'refs/remotes/origin/').splitlines())
        # Current Git can recreate the new default's symbolic tracking HEAD.
        if 'refs/remotes/origin/HEAD' in tracking:
            self.assertEqual(self.raw('symbolic-ref', 'refs/remotes/origin/HEAD').strip(),
                             'refs/remotes/origin/mcr/main')
        self.assertEqual(tracking - {'refs/remotes/origin/HEAD'},
                         {'refs/remotes/origin/'+name for name in g.BRANCHES})

    def test_non_main_remote_default_is_changed_before_pruning(self):
        self.raw('symbolic-ref', 'HEAD', 'refs/heads/feature/old', cwd=self.remote)
        self.raw('config', 'receive.denyDeleteCurrent', 'true', cwd=self.remote)
        self.clear(none=True)
        self.assert_final_branches()
        self.assertEqual(self.raw('symbolic-ref', 'HEAD', cwd=self.remote).strip(), 'refs/heads/mcr/main')

    def test_remote_only_retained_tag_is_imported_and_rewritten(self):
        self.raw('tag', '-d', 'keep-oldest')
        self.clear(keep=['keep-oldest'])
        self.assert_final_branches()
        self.assertEqual(self.raw('tag', '--list').strip(), 'keep-oldest')
        self.assertEqual(self.raw('show', '-s', '--format=%P', 'keep-oldest^{}').strip(), '')

    def test_failed_remote_push_resumes_saved_plan_automatically(self):
        with mock.patch.object(g, 'leased_mirror_push', side_effect=g.GitOpsError('fixture push rejected')):
            with self.assertRaisesRegex(g.GitOpsError, 'fixture push rejected'):
                self.clear(keep=['keep-oldest'])
        self.assertTrue((self.root/'.git/gitops-clear.json').is_file())
        self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
        self.clear(keep=['keep-latest'])  # Recovery retains the original selection.
        self.assert_final_branches()
        self.assertEqual(self.raw('tag', '--list').strip(), 'keep-oldest')
        self.assertIn('Resuming', self.output.getvalue())

    def test_remote_success_local_failure_is_recoverable(self):
        original = g.git
        def fail_local(*args, **kwargs):
            if args == ('update-ref', '--stdin') and b'update HEAD ' in kwargs.get('data', b''):
                raise g.GitOpsError('fixture local transaction interrupted')
            return original(*args, **kwargs)
        with mock.patch.object(g, 'git', side_effect=fail_local):
            with self.assertRaisesRegex(g.GitOpsError, 'transaction interrupted'):
                self.clear(none=True)
        self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
        self.assertEqual(len(g.remote_refs(self.root, str(self.remote))), 3)
        self.clear(none=True)
        self.assert_final_branches()

    def test_remote_concurrent_change_stops_before_local_branch_rewrite(self):
        original = g.leased_mirror_push
        def race(root, url, before, after, **kwargs):
            self.raw('update-ref', 'refs/heads/mcr/main', self.first, cwd=self.remote)
            return original(root, url, before, after, **kwargs)
        with mock.patch.object(g, 'leased_mirror_push', side_effect=race):
            with self.assertRaises(g.GitOpsError):
                self.clear(none=True)
        self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
        with self.assertRaisesRegex(g.GitOpsError, 'remote refs changed'):
            self.clear(none=True)

    def test_atomic_rejection_preserves_all_remote_refs_when_main_is_default(self):
        before = g.remote_refs(self.root, str(self.remote))
        self.raw('config', 'receive.denyDeletes', 'true', cwd=self.remote)
        with self.assertRaises(g.GitOpsError):
            self.clear(none=True)
        self.assertEqual(g.remote_refs(self.root, str(self.remote)), before)
        self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)

    def test_origin_success_mirror_failure_resumes_all_destinations(self):
        mirror = self.base/'mirror.git'
        self.raw('init', '--bare', '-q', '--initial-branch=mcr/main', str(mirror))
        self.raw('remote', 'add', 'mirror-glab', str(mirror))
        self.raw('config', 'remote.mirror-glab.gitopsManaged', 'true')
        self.raw('push', '-q', 'mirror-glab', '--all')
        self.raw('push', '-q', 'mirror-glab', '--tags')
        self.raw('config', 'receive.denyDeletes', 'true', cwd=mirror)
        old_mirror = g.remote_refs(self.root, str(mirror))
        with self.assertRaises(g.GitOpsError):
            self.clear(keep=['keep-oldest', 'keep-latest'])
        self.assertEqual(g.remote_refs(self.root, str(mirror)), old_mirror)
        origin = g.remote_refs(self.root, str(self.remote))
        self.assertEqual(len(origin), 5)
        self.assertNotEqual(origin['refs/heads/mcr/main'], self.tip)
        self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
        self.raw('config', 'receive.denyDeletes', 'false', cwd=mirror)
        self.clear(none=True)  # Resume the saved tags and graph, not a new plan.
        self.assert_final_branches()
        self.assertEqual(g.remote_refs(self.root, str(mirror)), origin)
        self.assertEqual(self.raw('tag', '--list').splitlines(), ['keep-latest', 'keep-oldest'])

    def test_managed_provider_mirror_identity_is_revalidated_before_transport(self):
        self.raw('remote', 'set-url', 'origin', 'git@github.com:owner/project.git')
        self.raw('remote', 'add', 'mirror-glab', 'git@gitlab.com:team/different.git')
        self.raw('config', 'remote.mirror-glab.gitopsManaged', 'true')
        with self.assertRaisesRegex(g.GitOpsError, 'identity no longer matches'):
            g.clear_remotes(self.root)

    def test_dirty_detached_and_extra_worktrees_are_rejected(self):
        (self.root/'file').write_text('uncommitted\n', encoding='utf-8')
        with self.assertRaises(g.GitOpsError):
            self.clear(none=True)
        (self.root/'file').write_text('latest\n', encoding='utf-8')
        self.raw('checkout', '--detach', '-q')
        with self.assertRaises(g.GitOpsError):
            self.clear(none=True)
        self.raw('checkout', '-q', 'mcr/main')
        self.raw('worktree', 'add', '-q', str(self.base/'second'), 'feature/old')
        with self.assertRaisesRegex(g.GitOpsError, 'one worktree'):
            self.clear(none=True)

    def test_merge_descendants_keep_parent_graph_and_exact_resolved_tree(self):
        self.raw('checkout', '-q', '-b', 'feature/merge', self.boundary)
        (self.root/'side').write_text('side\n', encoding='utf-8')
        self.raw('add', '--', 'side'); self.raw('commit', '-qm', 'side')
        self.raw('checkout', '-q', 'mcr/main')
        self.raw('merge', '--no-ff', '-qm', 'merge', 'feature/merge')
        self.before_tree = self.raw('rev-parse', 'HEAD^{tree}').strip()
        self.raw('push', '-q', 'origin', '--all')
        self.clear(keep=['keep-oldest', 'keep-latest'])
        self.assert_final_branches()
        self.assertEqual(len(self.raw('show', '-s', '--format=%P', 'HEAD').split()), 2)
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD').strip(), '5')

    def test_incomparable_kept_tags_are_rejected_without_remote_writes(self):
        self.raw('checkout', '-q', '-b', 'feature/diverged', self.first)
        self.commit('diverged')
        self.raw('tag', 'incomparable')
        self.raw('checkout', '-q', 'mcr/main')
        remote = g.remote_refs(self.root, str(self.remote))
        before = g.all_refs(self.root)
        with self.assertRaisesRegex(g.GitOpsError, 'one oldest tag'):
            self.clear(keep=['keep-oldest', 'incomparable'])
        self.assertEqual(g.remote_refs(self.root, str(self.remote)), remote)
        self.assertEqual(self.raw('rev-parse', 'HEAD').strip(), self.tip)
        self.assertEqual(g.all_refs(self.root), before)

    def test_tag_selection_needs_explicit_noninteractive_intent(self):
        with mock.patch.object(g.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(g.GitOpsError, 'noninteractive'):
                self.clear(apply=False)
        with mock.patch.object(g.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', return_value='1 3'):
            self.assertEqual(g.select_clear_tags(['a', 'b', 'c'], [], False), ['a', 'c'])
        with mock.patch.object(g.sys.stdin, 'isatty', return_value=True), mock.patch('builtins.input', return_value='cancel'):
            with self.assertRaisesRegex(g.GitOpsError, 'cancelled'):
                g.select_clear_tags(['a'], [], False)


if __name__ == '__main__':
    unittest.main()
