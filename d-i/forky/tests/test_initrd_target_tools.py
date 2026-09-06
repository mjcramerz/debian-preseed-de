"""Regression coverage for host/target applet boundaries; never change accounts."""
from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
SEED=ROOT/'d-i/forky'
SHELLS=[['/bin/sh']]
if shutil.which('busybox'):
    SHELLS.append([shutil.which('busybox'),'sh'])

class TargetToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='initrd-target-tools-')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.target=self.path/'target'
        self.storage=self.target/'var/lib/rootless-podman'
        self.storage.mkdir(parents=True)
        self.call=self.path/'call'

    def run_driver(self, requested='auto', fs='xfs', storage=None, fail=False, shell=None):
        env={'PATH':os.environ['PATH'], 'LC_ALL':'C', 'INSTALLER_TARGET_DIR':str(self.target),
             'CALL':str(self.call), 'FSTYPE':fs}
        script='set -eu\n. '+shlex.quote(str(SEED/'scripts/late/podman.sh'))+'\n'
        script+='installer_fatal() { printf "%s\\n" "$*" >&2; exit 1; }\n'
        script+='stat() { echo HOST_STAT_MUST_NOT_RUN >&2; return 127; }\n'
        script+='chroot() { printf "%s\\n" "$@" >"$CALL"; '
        script+=('return 127;' if fail else 'printf "%s\\n" "$FSTYPE";')+' }\n'
        script+='podman_resolve_native_storage_driver '+shlex.quote(requested)+' '+shlex.quote(str(storage or self.storage))+'\n'
        return subprocess.run((shell or ['/bin/sh'])+['-c',script],env=env,text=True,capture_output=True,timeout=5)

    def test_podman_uses_target_stat_without_host_applet(self):
        for shell in SHELLS:
            for fs,expected in [('btrfs','overlay'),('xfs','overlay'),('ext2/ext3','overlay'),('f2fs','overlay')]:
                with self.subTest(shell=shell,fs=fs):
                    p=self.run_driver(fs=fs,shell=shell)
                    self.assertEqual(p.returncode,0,p.stderr)
                    self.assertEqual(p.stdout,expected+'\n')
                    self.assertEqual(self.call.read_text().splitlines(),
                                     [str(self.target),'/usr/bin/stat','-f','-c','%T','--','/var/lib/rootless-podman'])
                    self.assertNotIn('HOST_STAT',p.stderr)

    def test_podman_rejects_target_stat_failure(self):
        p=self.run_driver(fail=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('target coreutils could not inspect',p.stderr)
        self.assertEqual(p.stdout,'')

    def test_podman_preserves_approved_filesystem_policy(self):
        for request,fs in [('auto','overlayfs'),('overlay','nfs'),('btrfs','xfs'),('unknown','xfs')]:
            with self.subTest(request=request,fs=fs):
                self.assertNotEqual(self.run_driver(request,fs).returncode,0)

    def test_podman_rejects_paths_outside_target(self):
        p=self.run_driver(storage=self.path)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('outside the installation target',p.stderr)
        self.assertFalse(self.call.exists())

    def test_codex_checks_invoke_target_stat_with_target_relative_paths(self):
        # Execute the four metadata expressions themselves, not the installer.
        expressions=[]
        for name in ('scripts/desktop/labwc.sh','scripts/late/devops.sh'):
            text=(SEED/name).read_text()
            found=re.findall(r'\$\((chroot [^\n]+?/usr/bin/stat -c \'%u:%g:%a\' -- [^\n]+?)\)',text)
            self.assertEqual(len(found),2,name)
            expressions.extend(found)
        helper='/usr/local/bin/codex-standalone-install'
        session='/opt/codex/.installer-codex-standalone.session.py'
        env={'PATH':os.environ['PATH'],'LC_ALL':'C','CALL':str(self.call),
             'INSTALLER_TARGET_DIR':str(self.target),'target_root':str(self.target),
             'installer_helper':helper,'session_helper':session,
             'DEVOPS_CODEX_STANDALONE_INSTALLER_HELPER':helper,
             'DEVOPS_CODEX_INSTALLER_SESSION_HELPER':session}
        for expr in expressions:
            script='set -eu\nstat() { return 127; }\nchroot() { printf "%s\\n" "$@" >"$CALL"; printf "0:0:755\\n"; }\n'+expr+'\n'
            p=subprocess.run(['/bin/sh','-c',script],env=env,text=True,capture_output=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr)
            args=self.call.read_text().splitlines()
            self.assertEqual(args[:5],[str(self.target),'/usr/bin/stat','-c','%u:%g:%a','--'])
            self.assertIn(args[5],(helper,session))

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='initrd-diagnostic-')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.envfile=self.path/'preseed.env'
        self.envfile.write_text("PRESEED_ROOT_PASSWORD='Never-Display-Fixture!2026'\n")
        self.envfile.chmod(0o600)
        self.cmdline=self.path/'cmdline'
        self.cmdline.write_text('quiet\n')

    def run_check(self):
        return subprocess.run(['/bin/sh',str(ROOT/'tools/check-installer-credentials.sh'),str(self.envfile),str(self.cmdline)],
                              env={'PATH':os.environ['PATH'],'LC_ALL':'C'},text=True,capture_output=True,timeout=5)

    def test_reports_presence_not_secrets(self):
        p=self.run_check()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('root_password: present (initrd-env)',p.stdout)
        self.assertNotIn('Never-Display',p.stdout+p.stderr)

    def test_reports_override_without_printing_it(self):
        self.cmdline.write_text('quiet root_password=Different-Never-Display-Fixture\n')
        p=self.run_check()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('root_password: present (command-line)',p.stdout)
        self.assertNotIn('Never-Display',p.stdout+p.stderr)

    def test_reports_empty_override_as_failure(self):
        self.cmdline.write_text('quiet root_password=\n')
        p=self.run_check()
        self.assertEqual(p.returncode,1,p.stderr)
        self.assertIn('root_password: explicit-empty (command-line)',p.stdout)

    def test_missing_env_is_a_nonzero_diagnostic(self):
        self.envfile.unlink()
        p=self.run_check()
        self.assertEqual(p.returncode,1,p.stderr)
        self.assertIn('root_password: missing-or-empty (initrd-env)',p.stdout)

    def test_invalid_shell_file_reports_error_without_contents(self):
        self.envfile.write_text("PRESEED_ROOT_PASSWORD='Never-Display-Broken-Quote\n")
        p=self.run_check()
        self.assertEqual(p.returncode,2)
        self.assertIn('invalid shell syntax',p.stderr)
        self.assertNotIn('Never-Display',p.stdout+p.stderr)

if __name__=='__main__':
    unittest.main()
