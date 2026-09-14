"""Offline tests of managed SSH, protected Git trees and reversible boot hooks.

Only generated fixture credentials are used. Real OpenSSH checks explicitly
skip when the package is absent; no installed boot configuration is modified.
"""
from __future__ import annotations
import base64
import contextlib
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

SEED=Path(__file__).resolve().parents[1]
TARGET=SEED/'hooks/target'

def load(name,path):
    loader=importlib.machinery.SourceFileLoader(name,str(path))
    spec=importlib.util.spec_from_loader(name,loader)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    loader.exec_module(module)
    return module

gitops=load('managed_gitops_tests',TARGET/'usr/local/bin/gitops')
ssh=load('managed_ssh_install_tests',TARGET/'usr/local/libexec/managed-ssh-install.py')
debug=load('managed_debugsys_tests',TARGET/'usr/local/libexec/debugsys.py')

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='managed-git-fixture-',dir='/root' if os.geteuid()==0 else None)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

class PatternTests(Fixture):
    def config(self,a='lock/ .gitignore debian/* *.keep',b='.gitignore'):
        p=self.root/'gitops.env'
        p.write_text(f'{gitops.KEYS[0]}="{a}"\n{gitops.KEYS[1]}="{b}"\n')
        p.chmod(0o600)
        return p
    def test_distinct_lists(self):
        path=self.config()
        self.assertIn('debian/*',gitops.load_patterns(path,'forks'))
        self.assertNotIn('debian/*',gitops.load_patterns(path,'salsa'))
    def test_empty_list(self):
        self.assertEqual(gitops.load_patterns(self.config('',''),'forks'),[])
    def test_parent_components_and_rooted_subtree(self):
        for name,pattern in [('a/.gitignore','.gitignore'),('x.keep/file','*.keep'),('debian/source/format','debian/*'),('debian','debian/*'),('dir/keep/a','dir/keep'),('dir/a','dir/')]:
            with self.subTest(name=name): self.assertTrue(gitops.protected(name,[pattern]))
        self.assertFalse(gitops.protected('other/dir/a',['dir/']))
    def test_shell_code_is_never_evaluated(self):
        for value in ('$(touch /tmp/never-gitops)','`id`','../private','/etc/shadow','.git/config'):
            with self.subTest(value=value),self.assertRaises((gitops.GitOpsError,ValueError)):
                gitops.load_patterns(self.config(value),'forks')
    def test_duplicate_and_unknown_assignment_rejected(self):
        for extra in ('UNKNOWN=x','GITOPS_FORKS_MERGE_PROTECTED="x"'):
            p=self.config();p.write_text(p.read_text()+extra+'\n')
            with self.assertRaises(gitops.GitOpsError):gitops.load_patterns(p,'forks')
    def test_symlink_hardlink_and_unsafe_mode_rejected(self):
        p=self.config();alias=self.root/'alias';alias.symlink_to(p)
        with self.assertRaises(gitops.GitOpsError):gitops.load_patterns(alias,'forks')
        alias.unlink();os.link(p,alias)
        with self.assertRaises(gitops.GitOpsError):gitops.load_patterns(p,'forks')
        alias.unlink();p.chmod(0o666)
        with self.assertRaises(gitops.GitOpsError):gitops.load_patterns(p,'forks')
    def test_protected_absence_deletion_and_type_collision(self):
        local={'a/keep':('100644','old'),'lock':('120000','old-link'),'same.keep':('100755','exec')}
        source={'a':('100644','collision'),'lock/new':('100644','collision'),'new.keep':('100644','absent'),'other':('100644','new')}
        result=gitops.desired_tree(local,source,['keep','lock','*.keep'])
        self.assertEqual(result,{**local,'other':('100644','new')})

class RealGitTests(PatternTests):
    def setUp(self):
        super().setUp()
        self.repo=self.root/'repo';self.repo.mkdir()
        self.env=mock.patch.dict(os.environ,{'HOME':str(self.root),'GIT_AUTHOR_NAME':'Fixture','GIT_AUTHOR_EMAIL':'fixture@example.invalid','GIT_COMMITTER_NAME':'Fixture','GIT_COMMITTER_EMAIL':'fixture@example.invalid'})
        self.env.start();self.addCleanup(self.env.stop)
        self.g('init','-q','-b','mcr/main')
        self.g('config','user.name','Fixture');self.g('config','user.email','fixture@example.invalid')
        self.write('lock/secret','local');self.write('ordinary','base');self.write('.gitignore','ignored\n')
        self.g('add','.');self.g('commit','-qm','base')
        self.old=self.g('rev-parse','HEAD').strip()
        self.g('switch','-qc','upstream')
        shutil.rmtree(self.repo/'lock');self.write('lock','replace-directory')
        self.write('ordinary','upstream');self.write('new.keep','upstream-protected-absence')
        self.g('add','-A');self.g('commit','-qm','upstream')
        self.upstream=self.g('rev-parse','HEAD').strip()
        self.g('switch','-q','mcr/main')
        self.policy=self.config()
    def g(self,*args):return gitops.git(*args,cwd=self.repo).decode()
    def write(self,name,text):
        p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    def sync(self,apply=True,workflow='forks'):
        with contextlib.redirect_stdout(io.StringIO()):
            gitops.sync(self.repo,workflow,'upstream',apply,False,self.policy)
    def test_apply_preserves_protected_content_and_absence(self):
        self.sync()
        self.assertEqual((self.repo/'lock/secret').read_text(),'local')
        self.assertFalse((self.repo/'new.keep').exists())
        self.assertEqual((self.repo/'ordinary').read_text(),'upstream')
        self.assertEqual(self.g('status','--porcelain'),'')
        parents=self.g('show','-s','--format=%P','HEAD').split()
        self.assertEqual(parents,[self.old,self.upstream])
        self.assertIn(self.old,self.g('for-each-ref','--format=%(objectname)','refs/gitops/backups'))
    def test_preview_leaves_tree_index_and_head_unchanged(self):
        before=(self.repo/'.git/index').read_bytes();self.sync(False)
        self.assertEqual(self.g('rev-parse','HEAD').strip(),self.old)
        self.assertEqual((self.repo/'.git/index').read_bytes(),before)
    def test_repeat_does_not_create_duplicate_commit(self):
        self.sync();head=self.g('rev-parse','HEAD');self.sync();self.assertEqual(head,self.g('rev-parse','HEAD'))
    def test_salsa_uses_separate_policy(self):
        self.sync(workflow='salsa')
        self.assertEqual((self.repo/'lock').read_text(),'replace-directory')
        self.assertTrue((self.repo/'new.keep').exists())
    def test_dirty_index_worktree_untracked_refused(self):
        for state in ('worktree','index','untracked'):
            with self.subTest(state=state):
                if state=='untracked':self.write('untracked','x')
                else:self.write('ordinary','dirty')
                if state=='index':self.g('add','ordinary')
                with self.assertRaises(gitops.GitOpsError):self.sync()
                self.assertEqual(self.g('rev-parse','HEAD').strip(),self.old)
                self.g('reset','--hard','HEAD')
                (self.repo/'untracked').unlink(missing_ok=True)
    def test_ignored_file_collision_refused(self):
        self.g('switch','-q','upstream');self.write('ignored','remote');self.g('add','-f','ignored');self.g('commit','-qm','ignored collision')
        self.g('switch','-q','mcr/main');self.write('ignored','private ignored')
        with self.assertRaises(gitops.GitOpsError):self.sync()
        self.assertEqual((self.repo/'ignored').read_text(),'private ignored')
    def test_skip_worktree_refused(self):
        self.g('update-index','--skip-worktree','ordinary')
        with self.assertRaises(gitops.GitOpsError):self.sync()
    def test_non_mcr_branch_refused(self):
        self.g('switch','-q','upstream')
        with self.assertRaises(gitops.GitOpsError):self.sync()
    def test_submodule_gitlink_refused(self):
        self.g('update-index','--add','--cacheinfo',f'160000,{self.old},submodule')
        self.g('commit','-qm','gitlink')
        with self.assertRaises(gitops.GitOpsError):self.sync()
    def test_mirror_detection_prefers_gitlab_mcr_namespace(self):
        self.g('update-ref','refs/remotes/origin/github/mcr/main',self.old)
        self.g('update-ref','refs/remotes/origin/gitlab/mcr/main',self.upstream)
        self.assertEqual(gitops.source_ref(self.repo,None),'origin/gitlab/mcr/main')
    def test_chain_keeps_each_branch_policy_and_restores_original(self):
        for branch in ('mcr/staging','mcr/release'):
            self.g('branch',branch,'mcr/main')
        with contextlib.redirect_stdout(io.StringIO()):
            gitops.sync_chain(self.repo,'forks','upstream',True,False,self.policy)
        self.assertEqual(self.g('symbolic-ref','--short','HEAD').strip(),'mcr/main')
        for branch in gitops.BRANCHES:
            self.assertEqual(self.g('show',branch+':ordinary'),'upstream')
            self.assertEqual(self.g('show',branch+':lock/secret'),'local')
    def test_quilt_patch_series_is_checked_without_worktree_change(self):
        self.write('debian/patches/change.patch','diff --git a/ordinary b/ordinary\n--- a/ordinary\n+++ b/ordinary\n@@ -1 +1 @@\n-base\n\\ No newline at end of file\n+patched\n\\ No newline at end of file\n')
        self.write('debian/patches/series','change.patch -p1 # fixture\n')
        before=(self.repo/'.git/index').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):gitops.patch_check(self.repo)
        self.assertEqual((self.repo/'ordinary').read_text(),'base')
        self.assertEqual((self.repo/'.git/index').read_bytes(),before)
    def test_ambient_git_index_ignored(self):
        fake=self.root/'alien-index'
        with mock.patch.dict(os.environ,{'GIT_INDEX_FILE':str(fake),'GIT_WORK_TREE':'/does-not-exist'}):self.sync()
        self.assertFalse(fake.exists())

class SSHTests(Fixture):
    def test_header_requires_encryption_and_bcrypt(self):
        def key(cipher,kdf,opts):
            raw=b'openssh-key-v1\0'+b''.join(struct.pack('>I',len(x))+x for x in (cipher,kdf,opts))
            return b'-----BEGIN OPENSSH PRIVATE KEY-----\n'+base64.b64encode(raw)+b'\n-----END OPENSSH PRIVATE KEY-----\n'
        ssh.encrypted_openssh(key(b'aes256-ctr',b'bcrypt',b'options'))
        for value in (key(b'none',b'none',b''),b'bad',key(b'aes',b'other',b'x')):
            with self.assertRaises(ssh.InstallError):ssh.encrypted_openssh(value)
    def test_input_permissions_symlinks_hardlinks_and_bounds(self):
        p=self.root/'key';p.write_bytes(b'encrypted fixture');p.chmod(0o600)
        self.assertEqual(ssh.read_direct(p,100,os.getuid()),b'encrypted fixture')
        for mode in (0o644,0o660):
            p.chmod(mode)
            with self.assertRaises(ssh.InstallError):ssh.read_direct(p,100,os.getuid())
        p.chmod(0o600)
        with self.assertRaises(ssh.InstallError):ssh.read_direct(p,1,os.getuid())
        other=self.root/'link';os.link(p,other)
        with self.assertRaises(ssh.InstallError):ssh.read_direct(p,100,os.getuid())
        other.unlink();other.symlink_to(p)
        with self.assertRaises(OSError):ssh.read_direct(other,100,os.getuid())
    @unittest.skipUnless(os.geteuid()==0,'root-owned atomic destination fixture')
    def test_pair_publication_rolls_back_new_private_on_failure(self):
        original=ssh.publish
        def fail_public(path,*args):
            if path.name.endswith('.pub'):raise OSError('fixture failure')
            return original(path,*args)
        with mock.patch.object(ssh,'publish',side_effect=fail_public):
            with self.assertRaises(OSError):ssh.publish_pair(self.root,b'private',b'public',0,0)
        self.assertFalse((self.root/'.local/share/managed-ssh/private/id_git_ed25519').exists())
    @unittest.skipUnless(shutil.which('gpg') and os.geteuid()==0,'GnuPG and root required for runuser fixture')
    def test_real_gpg_seal_round_trip_contains_no_plaintext_file(self):
        home=self.root/'home';home.mkdir(mode=0o700);gp=home/'.gnupg';gp.mkdir(mode=0o700)
        env={**ssh.BASE_ENV,'GNUPGHOME':str(gp),'HOME':str(home)}
        proc=subprocess.run(['gpg','--batch','--pinentry-mode','loopback','--passphrase','','--quick-generate-key','Fixture <fixture@example.invalid>','rsa2048','encr','0'],env=env,capture_output=True,timeout=45)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.addCleanup(lambda:subprocess.run(['gpgconf','--kill','gpg-agent'],env=env,capture_output=True))
        secret=b'Fixture secret % with spaces!'
        ssh.seal(pwd.getpwuid(0),home,secret)
        blob=home/'.local/share/managed-ssh/git-key-passphrase.gpg'
        self.assertEqual(stat.S_IMODE(blob.stat().st_mode),0o600)
        result=subprocess.run(['gpg','--batch','--decrypt',str(blob)],env=env,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout,secret)
        for p in home.rglob('*'):
            if p.is_file():self.assertNotIn(secret,p.read_bytes(),str(p))
    @unittest.skipUnless(all(shutil.which(n) for n in ('ssh-agent','ssh-add','ssh-keygen')),'OpenSSH client binaries are not installed in this validation container')
    def test_real_agent_correct_wrong_and_mismatched_passphrase(self):
        stage=self.root/'stage';stage.mkdir(mode=0o700)
        key=stage/'private';secret=b'Generated-fixture-only'
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N',secret.decode(),'-f',str(key)],check=True)
        (stage/'public').write_bytes((stage/'private.pub').read_bytes())
        askpass=self.root/'askpass';askpass.write_text((TARGET/'usr/local/libexec/managed-ssh-install-askpass').read_text());askpass.chmod(0o700)
        with mock.patch.object(ssh,'ASKPASS',str(askpass)):
            with ssh.temporary_agent(stage,secret) as env:self.assertNotIn('MANAGED_SSH_PASSPHRASE_FD',env)
            self.assertFalse((stage/'agent.sock').exists())
            with self.assertRaises(ssh.InstallError):
                with ssh.temporary_agent(stage,b'wrong'):pass
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(stage/'other')],check=True)
            (stage/'public').write_bytes((stage/'other.pub').read_bytes())
            with self.assertRaises(ssh.InstallError):
                with ssh.temporary_agent(stage,secret):pass
    def test_no_agent_start_in_zprofile(self):
        self.assertNotIn('ssh-agent -s',(TARGET/'etc/skel-desktop/.zprofile').read_text())
    def test_installer_input_boundary_and_pipe(self):
        text=(SEED/'scripts/common/ssh.sh').read_text().split('managed_git_ssh_target_action()',1)[1]
        self.assertIn('preseed_env_check_file /git_ed25519',text)
        self.assertIn('preseed_env_read_value git_ssh_passphrase',text)
        self.assertIn('printf \'%s\' "$secret" | chroot',text)
        self.assertNotIn('fetch_ssh_asset',text)
        self.assertNotIn('ACCOUNT_GIT_SSH_PASSPHRASE',(SEED/'scripts/runtime/account.sh').read_text())
    def test_session_unit_contract(self):
        for kind in ('socket','service'):
            text=(TARGET/f'etc/systemd/user/ssh-agent.{kind}.d/10-labwc-session.conf').read_text()
            self.assertIn('PartOf=labwc-session.target',text)
        text=(TARGET/'etc/skel-desktop/.config/systemd/user/labwc-ssh-key-load.service').read_text()
        self.assertNotIn('RemainAfterExit',text)
        self.assertIn('KillMode=control-group',text)
    def test_public_identity_and_strict_hosts_only(self):
        text=(SEED/'ssh/config').read_text()
        self.assertLess(text.index('Host gitlab.com github.com'),text.index('Host *'))
        self.assertIn('StrictHostKeyChecking yes',text)
        self.assertIn('id_git_ed25519.pub',text)
        self.assertNotIn('/private/',text)
    def test_host_fingerprints(self):
        expected={'github.com':' +DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'.strip(),'gitlab.com':'eUXGGm1YGsMAS7vkcx6JOJdOGHPem5gQp4taiCfCLB8'}
        for line in (TARGET/'etc/ssh/managed_git_known_hosts').read_text().splitlines():
            if not line or line.startswith('#'):continue
            host,kind,key=line.split()[:3]
            digest=base64.b64encode(hashlib.sha256(base64.b64decode(key)).digest()).decode().rstrip('=')
            self.assertEqual(digest,expected[host])
    def test_codex_agent_isolation_and_all_profiles(self):
        text=(TARGET/'data/codex/lib/codex').read_text()
        self.assertIn('SSH_AUTH_SOCK',text);self.assertIn('SSH_AGENT_PID',text)
        for path in (SEED/'hosts/profiles').glob('*.env'):
            self.assertNotIn('DEVOPS_CODEX_REPOSITORY_COMMIT',path.read_text())
            self.assertIn('git@gitlab.com:computes/misc/codex-home.git',path.read_text())
            self.assertIn('DEVOPS_CODEX_REPOSITORY_BRANCH="mcr/main"',path.read_text())

@unittest.skipUnless(os.geteuid()==0,'root-only output/hook fixture contract')
class DebugTests(Fixture):
    def setUp(self):
        super().setUp()
        self.state=self.root/'state';self.logs=self.root/'logs';self.init=self.root/'initramfs';self.boot=self.root/'boot'
        self.boot.mkdir()
        self.patch=mock.patch.multiple(debug,STATE=self.state,LOGROOT=self.logs,INITRAMFS=self.init,BOOT=self.boot,TEMPLATES=TARGET/'usr/local/share/debugsys/initramfs')
        self.patch.start();self.addCleanup(self.patch.stop)
    def test_multiselection_and_conflicting_actions(self):
        self.assertEqual(debug.selections('1,6-9 12'),[1,6,7,8,9,12])
        for value in ('3,5','0,1','9-1','13','1; id',''):
            with self.assertRaises(debug.DebugError):debug.selections(value)
    def test_redacts_credentials_pem_and_terminal_escapes(self):
        result=debug.redact('password=secret PRESEED_GIT_SSH_PASSPHRASE="s e c" https://u:pw@host Bearer abc\n-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n\x1b]evil')
        for secret in ('=secret','s e c','u:pw','Bearer abc','\x1b','\nabc\n'):self.assertNotIn(secret,result)
        self.assertIn('[REDACTED]',result)
    def test_child_output_limit_timeout_and_missing(self):
        _,meta=debug.run(['/usr/bin/yes'],cap=1000);self.assertEqual(meta['status'],'output-limit')
        _,meta=debug.run(['/bin/sleep','10'],timeout=.1);self.assertEqual(meta['status'],'timeout')
        _,meta=debug.run(['not-a-real-program']);self.assertEqual(meta['status'],'not-installed')
    def test_report_files_are_private_and_hashed(self):
        report=debug.Report(['hardware'])
        report.add('hardware','fixture','evidence',{'status':'ok'})
        with contextlib.redirect_stdout(io.StringIO()):report.finish()
        self.assertEqual(stat.S_IMODE(report.path.stat().st_mode),0o700)
        for path in report.path.rglob('*'):
            if path.is_file():self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        manifest=json.loads((report.path/'manifest.json').read_text())
        self.assertEqual(manifest[0]['sha256'],hashlib.sha256((report.path/manifest[0]['evidence']).read_bytes()).hexdigest())
        self.assertTrue((report.path/'OVERVIEW.md').is_file())
    def test_symlink_output_refused(self):
        other=self.root/'other';other.mkdir();self.logs.symlink_to(other)
        with self.assertRaises(debug.DebugError):debug.Report(['boot'])
    def run_hook_action(self,enabled,fail=False):
        calls=[]
        def fake(argv,journal,label,timeout=60):
            calls.append((argv,label))
            if fail and label=='rebuild':raise debug.DebugError('injected rebuild failure')
            return ''
        with mock.patch.object(debug,'successful',side_effect=fake),mock.patch.object(debug,'verify_images'),mock.patch.object(debug,'run',return_value=('',{'status':'nonzero'})),contextlib.redirect_stdout(io.StringIO()):
            if fail:
                with self.assertRaises(debug.DebugError):debug.change_hooks(enabled)
            else:debug.change_hooks(enabled)
        return calls
    def test_enable_remove_only_owned_hooks_and_rebuild_all(self):
        other=self.init/'hooks/unrelated';other.parent.mkdir(parents=True);other.write_text('# unrelated\n')
        calls=self.run_hook_action(True)
        for path in debug.hook_files():self.assertIn(debug.MARKER,path.read_text())
        self.assertTrue((self.state/'armed').is_file())
        self.assertIn((['update-initramfs','-u','-k','all'],'rebuild'),calls)
        calls=self.run_hook_action(False)
        for path in debug.hook_files():self.assertFalse(path.exists())
        self.assertTrue(other.exists());self.assertFalse((self.state/'armed').exists())
        self.assertIn((['update-initramfs','-u','-k','all'],'rebuild'),calls)
    def test_failed_rebuild_restores_and_rebuilds_previous_images(self):
        calls=self.run_hook_action(True,fail=True)
        for path in debug.hook_files():self.assertFalse(path.exists())
        self.assertFalse((self.state/'armed').exists())
        self.assertIn((['update-initramfs','-u','-k','all'],'rollback-rebuild'),calls)
    def test_failed_removal_restores_enabled_hooks(self):
        self.run_hook_action(True)
        self.run_hook_action(False,fail=True)
        for path in debug.hook_files():self.assertTrue(path.exists())
        self.assertTrue((self.state/'armed').exists())
    def test_unmanaged_hook_never_replaced(self):
        path=self.init/'hooks/debugsys';path.parent.mkdir(parents=True);path.write_text('# administrator hook')
        with self.assertRaises(debug.DebugError):debug.change_hooks(True)
        self.assertEqual(path.read_text(),'# administrator hook')
    def test_initramfs_names_and_rebuild_validation(self):
        image=self.boot/'initrd.img-fixture';image.write_bytes(b'fixture')
        expected='usr/local/libexec/debugsys-initramfs\n'+'\n'.join('scripts/'+phase+'/debugsys' for phase in debug.PHASES)
        with mock.patch.object(debug,'successful',side_effect=lambda argv,*args: 'fixture\n' if argv[0]=='linux-version' else expected):
            debug.verify_images(True,self.root)
        with mock.patch.object(debug,'successful',side_effect=lambda argv,*args: 'fixture\n' if argv[0]=='linux-version' else ''):
            with self.assertRaises(debug.DebugError):debug.verify_images(True,self.root)
            debug.verify_images(False,self.root)
    def test_initramfs_backups_and_orphans_are_retained_not_verified_as_live(self):
        for name in ('initrd.img-fixture','initrd.img-fixture.bak','initrd.img-fixture.dpkg-bak','initrd.img-old-rescue'):
            (self.boot/name).write_bytes(b'fixture')
        calls=[]
        def fake(argv,*args):
            calls.append(argv)
            return 'fixture\n' if argv[0]=='linux-version' else ''
        with mock.patch.object(debug,'successful',side_effect=fake):debug.verify_images(False,self.root)
        self.assertEqual([a for a in calls if a[0]=='lsinitramfs'],[['lsinitramfs',str(self.boot/'initrd.img-fixture')]])
        retained=json.loads((self.root/'retained-other-images.json').read_text())
        self.assertEqual(len(retained),3)
        self.assertTrue((self.boot/'initrd.img-fixture.bak').exists())
    def test_initramfs_empty_or_unsafe_inventory_is_refused(self):
        for listing in ('','../../etc/passwd\n'):
            with mock.patch.object(debug,'successful',return_value=listing),self.assertRaises(debug.DebugError):
                debug.verify_images(False,self.root)
    def test_wrapper_enters_sudo_login(self):
        self.assertIn('sudo -i -- /usr/local/bin/debugsys',(TARGET/'usr/local/bin/debugsys').read_text())
    def test_all_menu_collectors_have_probe_and_file_plan(self):
        self.assertEqual(set(debug.CATEGORIES),set(debug.PROBES))
        self.assertEqual(set(debug.CATEGORIES),set(debug.FILES))
        self.assertEqual(set(debug.MENU[11][1]),set(debug.CATEGORIES))
        self.assertNotIn(3,debug.MENU[11][1]);self.assertNotIn(5,debug.MENU[11][1])


class PublishingGuardTests(Fixture):
    def setUp(self):
        super().setUp()
        self.build = load('managed_publishing_guard_tests', SEED.parents[1]/'tools/build.py')
        patch = mock.patch.object(self.build, 'ROOT', self.root)
        patch.start(); self.addCleanup(patch.stop)
    def test_private_initrd_filenames_refused_anywhere_under_public_root(self):
        for name in ('preseed.env','git_ed25519','git_ed25519.pub','id_git_ed25519'):
            with self.subTest(name=name):
                path = self.root/name; path.write_text('fixture')
                with self.assertRaises(ValueError): self.build.refuse_private_inputs()
                path.unlink()
    def test_renamed_private_key_header_refused(self):
        (self.root/'renamed.key').write_bytes(b'-----BEGIN OPENSSH PRIVATE KEY-----\nfixture')
        with self.assertRaises(ValueError): self.build.refuse_private_inputs()
    def test_public_key_and_documented_example_are_allowed(self):
        (self.root/'public.pub').write_text('ssh-ed25519 fixture')
        (self.root/'example.py').write_text('HEADER = "-----BEGIN OPENSSH PRIVATE KEY-----"')
        self.build.refuse_private_inputs()
    def test_report_requires_disk_headroom(self):
        with mock.patch.object(debug,'LOGROOT',self.root/'reports'), mock.patch.object(debug.shutil,'disk_usage') as usage:
            usage.return_value.free = debug.MAX_TOTAL
            with self.assertRaises(debug.DebugError): debug.Report(['system'])

if __name__=='__main__':unittest.main()
