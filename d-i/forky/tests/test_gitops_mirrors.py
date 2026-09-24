"""Real local Git transport tests; provider APIs are mocked, never contacted."""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv
from payload_fixture import installed_script
from payload_fixture import read_bytes as payload_read_bytes
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SEED=Path(__file__).resolve().parents[1]
BIN=SEED/'hooks/target/usr/local/bin/gitops'
loader=importlib.machinery.SourceFileLoader('gitops_mirror_tests',str(installed_script(BIN)))
spec=importlib.util.spec_from_loader(loader.name,loader)
g=importlib.util.module_from_spec(spec)
sys.modules[loader.name]=g
loader.exec_module(g)

class MirrorFixture(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='gitops-mirror-',dir='/root' if os.geteuid()==0 else None)
        self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name);self.root=self.base/'work';self.remote=self.base/'mirror.git'
        self.root.mkdir()
        self.raw('init','-q','--initial-branch=mcr/main')
        self.raw('config','user.name','Fixture User');self.raw('config','user.email','fixture@example.invalid')
        (self.root/'file').write_text('first\n')
        self.raw('add','file');self.raw('commit','-qm','first')
        self.first=self.raw('rev-parse','HEAD').strip()
        for branch in ('mcr/staging','mcr/release','mcr/feature/keep'):
            self.raw('branch',branch)
        self.raw('tag','-a','local-only','-m','local-only')
        self.raw('remote','add','origin','git@github.com:owner/project.git')
        self.raw('init','--bare','-q',str(self.remote))
        self.ssh='git@gitlab.com:team/project.git'
        self.calls=[];self.api_calls=[];self.default_branch='main'
        self.original_git=g.git
        self.out=io.StringIO()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(g,'git',side_effect=self.transport).start()
        mock.patch.object(g,'provider_api',side_effect=self.api).start()
        self.quiet=contextlib.redirect_stdout(self.out);self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__,None,None,None)

    def raw(self,*args,cwd=None):
        env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        env.update({'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'})
        p=subprocess.run(payload_installed_argv(['/usr/bin/git',*args]),cwd=cwd or self.root,env=env,text=True,capture_output=True)
        if p.returncode:raise AssertionError(p.stderr)
        return p.stdout

    def transport(self,*args,**kw):
        self.calls.append(args)
        index=0
        while index<len(args) and args[index]=='-c':index+=2
        if index<len(args) and args[index] in ('push','fetch','ls-remote'):
            args=tuple(str(self.remote) if x==self.ssh else x for x in args)
        return self.original_git(*args,**kw)

    def api(self,provider,method,endpoint,body=None,**kwargs):
        self.api_calls.append((provider,method,endpoint,body))
        if method in ('PUT','PATCH'):
            self.assertEqual(body,{'default_branch':'mcr/main'})
            # This must already exist, before an old default branch is deleted.
            self.raw('rev-parse','--verify','refs/heads/mcr/main',cwd=self.remote)
            self.raw('symbolic-ref','HEAD','refs/heads/mcr/main',cwd=self.remote)
            self.default_branch='mcr/main'
        return {'id':1,'visibility':'private','default_branch':self.default_branch,
                'path_with_namespace':'team/project','ssh_url_to_repo':self.ssh}

    def seed_remote(self):
        self.raw('push',str(self.remote),'HEAD:refs/heads/main','HEAD:refs/heads/stale',
                 'refs/tags/local-only:refs/tags/old-tag')
        self.raw('symbolic-ref','HEAD','refs/heads/main',cwd=self.remote)

    def test_preview_has_no_local_or_remote_mutations(self):
        self.seed_remote()
        before=g.remote_refs(self.root,self.ssh)
        config=payload_read_bytes(self.root/'.git/config')
        g.configure_mirror(self.root,'glab','team',False)
        self.assertEqual(g.remote_refs(self.root,self.ssh),before)
        self.assertEqual(payload_read_bytes(self.root/'.git/config'),config)
        self.assertFalse(any(c[1]!='GET' for c in self.api_calls))
        self.assertIn('Preview only',self.out.getvalue())
        self.assertIn('<delete>',self.out.getvalue())

    def test_apply_prunes_with_backups_and_preserves_origin_and_local_tags(self):
        self.seed_remote()
        old_origin=self.raw('remote','get-url','origin')
        g.configure_mirror(self.root,'glab','team',True)
        self.assertEqual(g.remote_refs(self.root,self.ssh),g.promotion_tips(self.root))
        self.assertEqual(self.raw('remote','get-url','origin'),old_origin)
        self.assertEqual(self.raw('symbolic-ref','HEAD',cwd=self.remote).strip(),'refs/heads/mcr/main')
        self.assertEqual(self.raw('tag','--list').strip(),'local-only')
        backups=self.raw('for-each-ref','--format=%(refname)','refs/gitops/mirror-backups/')
        self.assertIn('/heads/main',backups);self.assertIn('/heads/stale',backups)
        self.assertIn('/tags/old-tag',backups)
        self.assertEqual(self.raw('config','--get','remote.mirror-glab.gitopsManaged').strip(),'true')
        self.assertEqual(self.raw('config','--get','remote.mirror-glab.skipFetchAll').strip(),'true')
        keys=self.raw('config','--get-regexp',r'^remote\.mirror-glab\.')
        self.assertNotIn('.fetch ',keys)
        pushes=[args for args in self.calls if 'push' in args]
        self.assertTrue(pushes)
        self.assertTrue(all('--atomic' in args for args in pushes))
        self.assertFalse(any('--force' in args or '--mirror' in args for args in pushes))

    def test_delete_removes_local_remote_only(self):
        g.configure_mirror(self.root,'glab','team',True)
        before=g.remote_refs(self.root,self.ssh)
        count=len(self.api_calls)
        g.configure_mirror(self.root,'glab','del',False)
        self.assertIn('mirror-glab',self.raw('remote'))
        g.configure_mirror(self.root,'glab','del',True)
        self.assertNotIn('mirror-glab',self.raw('remote'))
        self.assertEqual(g.remote_refs(self.root,self.ssh),before)
        self.assertEqual(len(self.api_calls),count)

    def test_origin_provider_and_retargeting_are_rejected(self):
        with self.assertRaises(g.GitOpsError):g.configure_mirror(self.root,'gh','del',True)
        self.raw('remote','add','mirror-glab','git@gitlab.com:someone/project.git')
        with self.assertRaises(g.GitOpsError):g.configure_mirror(self.root,'glab','team',True)
        self.assertEqual(self.raw('remote','get-url','mirror-glab').strip(),'git@gitlab.com:someone/project.git')

    def test_atomic_leases_reject_concurrent_creation(self):
        desired=g.promotion_tips(self.root)
        self.raw('push',str(self.remote),'HEAD:refs/heads/mcr/main')
        # An empty expected value means the ref MUST NOT exist, even at the same OID.
        # Use a different wanted tip so Git cannot optimize it as up to date.
        (self.root/'file').write_text('second\n');self.raw('commit','-qam','second')
        desired['refs/heads/mcr/main']=self.raw('rev-parse','HEAD').strip()
        with self.assertRaises(g.GitOpsError):g.leased_mirror_push(self.root,self.ssh,{},desired)
        actual=g.remote_refs(self.root,self.ssh)
        self.assertEqual(actual,{'refs/heads/mcr/main':self.first})

    def test_atomic_leases_reject_concurrent_change(self):
        self.raw('push',str(self.remote),'HEAD:refs/heads/mcr/main')
        before=g.remote_refs(self.root,self.ssh)
        (self.root/'file').write_text('other writer\n');self.raw('commit','-qam','other writer')
        other=self.raw('rev-parse','HEAD').strip()
        self.raw('push',str(self.remote),'HEAD:refs/heads/mcr/main')
        # Local source deliberately remains behind the concurrent remote tip.
        wanted={f'refs/heads/{b}':self.first for b in g.BRANCHES}
        with self.assertRaises(g.GitOpsError):g.leased_mirror_push(self.root,self.ssh,before,wanted)
        self.assertEqual(g.remote_refs(self.root,self.ssh),{'refs/heads/mcr/main':other})

    def test_normal_branch_push_never_propagates_tags_or_feature_branches(self):
        g.configure_mirror(self.root,'glab','team',True)
        # Simulate independent tag creation after setup; normal promotion leaves it alone.
        self.raw('push',str(self.remote),'HEAD:refs/tags/remote-only')
        (self.root/'file').write_text('second\n');self.raw('commit','-qam','second')
        g.push_configured_mirrors(self.root)
        actual=g.remote_refs(self.root,self.ssh)
        self.assertIn('refs/tags/remote-only',actual)
        self.assertNotIn('refs/tags/local-only',actual)
        self.assertNotIn('refs/heads/mcr/feature/keep',actual)
        for ref,tip in g.promotion_tips(self.root).items():self.assertEqual(actual[ref],tip)

    def test_failed_provider_change_does_not_prune_old_default(self):
        self.seed_remote()
        def api(*args,**kw):
            if args[1]=='PUT':raise g.GitOpsError('fixture permission denied')
            return {'id':1,'private':True,'path_with_namespace':'team/project','ssh_url_to_repo':self.ssh}
        with mock.patch.object(g,'provider_api',side_effect=api):
            with self.assertRaises(g.GitOpsError):g.configure_mirror(self.root,'glab','team',True)
        refs=g.remote_refs(self.root,self.ssh)
        self.assertIn('refs/heads/main',refs);self.assertIn('refs/tags/old-tag',refs)
        self.assertNotIn('mirror-glab',self.raw('remote'))

    def test_successful_cli_and_failure_are_not_silent(self):
        old=Path.cwd()
        try:
            os.chdir(self.root)
            with mock.patch.object(g.os,'geteuid',return_value=1000):
                self.assertEqual(g.main(['mcr-repo-status']),0)
                self.assertEqual(g.main(['mcr-branch-create','mcr/feature/logging']),0)
                self.assertEqual(g.main(['mcr-tag-create','new-tag']),0)
                self.assertEqual(g.main(['mcr-branch-delete','mcr/main']),1)
        finally:os.chdir(old)
        text=self.out.getvalue()
        for expected in ('[BEFORE]','[AFTER]','Git sha1 commit: '+self.first,
                         'SHA256(stored commit object):','mcr/feature/logging','[gitops] exit 1'):
            self.assertIn(expected,text)
        raw=self.raw('cat-file','commit',self.first).encode()
        expected=hashlib.sha256(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        self.assertIn(expected,text)

    def test_repeated_mirror_setup_is_idempotent(self):
        g.configure_mirror(self.root,'glab','team',True)
        config=payload_read_bytes(self.root/'.git/config')
        refs=g.remote_refs(self.root,self.ssh)
        g.configure_mirror(self.root,'glab','team',True)
        self.assertEqual(config,payload_read_bytes(self.root/'.git/config'))
        self.assertEqual(refs,g.remote_refs(self.root,self.ssh))

    def test_provider_identity_mismatch_cannot_prune(self):
        self.seed_remote();before=g.remote_refs(self.root,self.ssh)
        with mock.patch.object(g,'provider_api',return_value={'path_with_namespace':'elsewhere/project'}):
            with self.assertRaises(g.GitOpsError):g.configure_mirror(self.root,'glab','team',True)
        self.assertEqual(before,g.remote_refs(self.root,self.ssh))

    def test_mirror_failure_reports_origin_is_not_rolled_back(self):
        self.raw('remote','add','mirror-glab',self.ssh)
        with self.assertRaisesRegex(g.GitOpsError,'Origin push succeeded'):
            g.push_configured_mirrors(self.root)

    def test_sha256_native_and_stored_fingerprint_agree(self):
        other=self.base/'sha256';other.mkdir()
        self.raw('init','-q','--object-format=sha256','--initial-branch=mcr/main',cwd=other)
        self.raw('config','user.name','Fixture',cwd=other);self.raw('config','user.email','fixture@example.invalid',cwd=other)
        self.raw('commit','--allow-empty','-qm','SHA256 fixture',cwd=other)
        oid=self.raw('rev-parse','HEAD',cwd=other).strip()
        g.report_commit(other,'HEAD','SHA256 fixture')
        self.assertEqual(len(oid),64)
        self.assertIn('Git sha256 commit: '+oid,self.out.getvalue())
        self.assertIn('SHA256(stored commit object): '+oid,self.out.getvalue())

class SafetyTests(unittest.TestCase):
    def test_urls_and_terminal_sanitization(self):
        for url,want in [('git@github.com:owner/project.git',('gh','owner','project')),
                         ('https://gitlab.com/a/b/project.git',('glab','a/b','project')),
                         ('ssh://git@gitlab.com/a/project',('glab','a','project'))]:
            self.assertEqual(g.parse_provider_url(url),want)
        for url in ('https://token@github.com/o/r.git','git@evil.invalid:o/r.git',
                    'git@github.com:../r.git','git@github.com:o/r.git\nINJECT'):
            with self.assertRaises(g.GitOpsError):g.parse_provider_url(url)
        text=g.terminal_text('https://secret:password@github.com/o/r\x1b[31m\u202e')
        self.assertNotIn('secret',text);self.assertNotIn('password',text)
        self.assertNotIn('\x1b',text);self.assertNotIn('\u202e',text)

    def test_private_repository_creation_for_both_providers(self):
        for provider,namespace in (('gh','owner'),('glab','group/subgroup')):
            with self.subTest(provider=provider):
                created=False;calls=[]
                def api(p,method,endpoint,body=None,**kwargs):
                    nonlocal created
                    calls.append((method,endpoint,body))
                    if method=='POST':
                        created=True
                        self.assertEqual(body.get('private') if p=='gh' else body.get('visibility'),
                                         True if p=='gh' else 'private')
                        return {}
                    if endpoint.startswith(('repos/','projects/')):
                        if not created:return None
                        return {'full_name' if p=='gh' else 'path_with_namespace':namespace+'/project',
                                'ssh_url' if p=='gh' else 'ssh_url_to_repo':g.provider_url(p,namespace,'project')}
                    if endpoint.startswith('users/'):
                        return {'type':'Organization','login':namespace}
                    if endpoint.startswith('namespaces/'):
                        return {'id':42,'kind':'group','full_path':namespace}
                    raise AssertionError(endpoint)
                with mock.patch.object(g,'provider_api',side_effect=api):
                    result=g.provider_repository(provider,namespace,'project',create=True)
                self.assertIsInstance(result,dict)
                self.assertEqual(sum(c[0]=='POST' for c in calls),1)
                self.assertIn('orgs/owner/repos' if provider=='gh' else 'projects',[c[1] for c in calls])

    def test_only_actual_http_404_is_absence(self):
        for code in (200,404,401,403,429,500,0):
            with self.subTest(code=code):
                proc=mock.Mock()
                proc.pid=424242424;proc.returncode=0 if code==200 else 1
                proc.stdin=io.BytesIO();proc.stdout=io.BytesIO();proc.stderr=io.BytesIO()
                response=(f'HTTP/2.0 {code} Fixture\r\nContent-Type: application/json\r\n\r\n'.encode()+b'{"id": 1}') if code else b''
                proc.communicate.return_value=(response,b'fixture failure' if code!=200 else b'')
                with mock.patch.object(Path,'is_file',return_value=True),mock.patch.object(g.os,'access',return_value=True), \
                     mock.patch.object(g.subprocess,'Popen',return_value=proc),mock.patch.object(g.os,'killpg'),contextlib.redirect_stdout(io.StringIO()):
                    if code in (200,404):
                        result=g.provider_api('gh','GET','repos/o/r',missing_ok=True)
                        self.assertEqual(result,{'id':1} if code==200 else None)
                    else:
                        with self.assertRaises(g.GitOpsError):g.provider_api('gh','GET','repos/o/r',missing_ok=True)
                    self.assertTrue(proc.stdin.closed)
                    proc.wait.assert_called_once()

if __name__=='__main__':unittest.main()
