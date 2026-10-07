"""Regression coverage for host/target applet boundaries; never change accounts."""
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists
from payload_fixture import read_text as payload_read_text
from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from test_environment import skip_unless_trusted_credential_ancestry

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
        script+='. '+shlex.quote(str(SEED/'scripts/common/target.sh'))+'\n'
        script+='target_root_dir() { printf "%s\\n" "$INSTALLER_TARGET_DIR"; }\n'
        script+='installer_fatal() { printf "%s\\n" "$*" >&2; exit 1; }\n'
        script+='stat() { echo HOST_STAT_MUST_NOT_RUN >&2; return 127; }\n'
        script+='chroot() { printf "%s\\n" "$@" >"$CALL"; '
        script+=('return 127;' if fail else 'printf "%s\\n" "$FSTYPE";')+' }\n'
        script+='podman_resolve_native_storage_driver '+shlex.quote(requested)+' '+shlex.quote(str(storage or self.storage))+'\n'
        return subprocess.run(payload_installed_argv((shell or ['/bin/sh'])+['-c',script]),env=env,text=True,capture_output=True,timeout=5)

    def test_podman_uses_target_metadata_without_host_applet(self):
        for shell in SHELLS:
            for fs,expected in [('btrfs','overlay'),('xfs','overlay'),('ext2','overlay'),('ext3','overlay'),('ext4','overlay'),('f2fs','overlay')]:
                with self.subTest(shell=shell,fs=fs):
                    p=self.run_driver(fs=fs,shell=shell)
                    self.assertEqual(p.returncode,0,p.stderr)
                    self.assertEqual(p.stdout,expected+'\n')
                    self.assertEqual([payload_read_text(self.call).splitlines()[0], *payload_read_text(self.call).splitlines()[-7:]],
                                     [str(self.target),'/usr/bin/find','-P','/var/lib/rootless-podman','-maxdepth','0','-printf','%F'])
                    self.assertNotIn('HOST_STAT',p.stderr)

    def test_podman_filesystem_lookup_uses_installer_target_setup(self):
        # Native findutils needs the target mount table for filesystem names.
        # The shared d-i bridge arranges that; never silently inspect the host.
        bridge = self.path / 'in-target'
        bridge.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" >"$CALL"\nprintf \'%s\\n\' ext4\n')
        bridge.chmod(0o755)
        script = 'set -eu\n'
        for name in ('scripts/common/target.sh', 'scripts/late/podman.sh'):
            script += '. ' + shlex.quote(str(SEED / name)) + '\n'
        script += r'''
target_root_dir() { printf '%s\n' /target; }
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
chroot() { printf '%s\n' 'wrong direct chroot boundary' >&2; return 127; }
podman_resolve_native_storage_driver auto /target/pool/podman
'''
        result = subprocess.run(payload_installed_argv(['/bin/sh', '-c', script]), text=True, capture_output=True,
                                env={'PATH': str(self.path) + ':' + os.environ['PATH'], 'CALL': str(self.call),
                                     'INSTALLER_TARGET_DIR': '/target'}, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'overlay\n')
        call = payload_read_text(self.call).splitlines()
        self.assertEqual(call[0], '--pass-stdout')
        self.assertEqual(call[-7:], ['/usr/bin/find', '-P', '/pool/podman',
                                    '-maxdepth', '0', '-printf', '%F'])

    def test_podman_rejects_target_metadata_failure(self):
        p=self.run_driver(fail=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('target findutils could not inspect',p.stderr)
        self.assertEqual(p.stdout,'')

    def test_podman_preserves_approved_filesystem_policy(self):
        for request,fs in [('auto','overlayfs'),('overlay','nfs'),('btrfs','xfs'),('unknown','xfs')]:
            with self.subTest(request=request,fs=fs):
                self.assertNotEqual(self.run_driver(request,fs).returncode,0)

    def test_podman_rejects_paths_outside_target(self):
        p=self.run_driver(storage=self.path)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('outside the installation target',p.stderr)
        self.assertFalse(payload_source_exists(self.call))

    def test_codex_checks_invoke_target_metadata_with_target_relative_paths(self):
        # Execute the four metadata expressions themselves, not the installer.
        expressions=[]
        for name in ('scripts/desktop/labwc.sh','scripts/late/devops.sh'):
            text=payload_read_text(SEED/name)
            found=re.findall(r'\$\((chroot [^\n]+?/usr/bin/find -P [^\n]+? -maxdepth 0 -printf \'%U:%G:%m\')\)',text)
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
            p=subprocess.run(payload_installed_argv(['/bin/sh','-c',script]),env=env,text=True,capture_output=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stderr)
            args=payload_read_text(self.call).splitlines()
            self.assertEqual(args[:3],[str(self.target),'/usr/bin/find','-P'])
            self.assertIn(args[3],(helper,session))
            self.assertEqual(args[4:],['-maxdepth','0','-printf','%U:%G:%m'])

    def test_codex_app_server_metadata_uses_target_metadata_without_host_applet(self):
        text=payload_read_text(SEED/'scripts/late/devops.sh')
        stage=text.split('devops_stage_codex_app_server() {',1)[1].split(
            '\n}\n\ndevops_install_pinned_codex() (',1)[0]
        self.assertEqual(stage.count('devops_assert_target_metadata'),5)
        self.assertNotRegex(stage,r'(?<![/\w])stat\s+-c')

        start=text.index('devops_assert_target_metadata() (')
        end=text.index('\n)\n',start)+3
        helper=text[start:end]
        host_path=self.target/'etc/default'
        host_path.mkdir(parents=True)
        env={**os.environ,'LC_ALL':'C','CALL':str(self.call),'TEST_METADATA':'0:0:755'}
        for shell in SHELLS:
            with self.subTest(shell=shell):
                self.call.unlink(missing_ok=True)
                script=f'''set -eu
 target_root={shlex.quote(str(self.target))}
 devops_fatal() {{ printf 'fatal: %s\\n' "$*" >&2; exit 1; }}
 devops_validate_abs_path() {{ :; }}
 {helper}
 stat() {{ echo HOST_STAT_MUST_NOT_RUN >&2; return 127; }}
 chroot() {{ printf '%s\\n' "$@" >"$CALL"; printf '%s\\n' "$TEST_METADATA"; }}
 devops_assert_target_metadata 0:0:755 {shlex.quote(str(host_path))} 'Codex app-server base directory'
 '''
                p=subprocess.run(payload_installed_argv(shell+['-c',script]),env=env,text=True,
                                 capture_output=True,timeout=5)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertNotIn('HOST_STAT',p.stderr)
                self.assertEqual(payload_read_text(self.call).splitlines(),[
                    str(self.target),'/usr/bin/find','-P','/etc/default','-maxdepth','0','-printf','%U:%G:%m'])

                mismatch=subprocess.run(payload_installed_argv(shell+['-c',script]),
                    env={**env,'TEST_METADATA':'0:0:775'},text=True,
                    capture_output=True,timeout=5)
                self.assertNotEqual(mismatch.returncode,0)
                self.assertIn('has unsafe ownership or mode',mismatch.stderr)
                self.assertNotIn('HOST_STAT',mismatch.stderr)

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
        return subprocess.run(payload_installed_argv(['/bin/sh',str(ROOT/'tools/check-installer-credentials.sh'),str(self.envfile),str(self.cmdline)]),
                              env={'PATH':os.environ['PATH'],'LC_ALL':'C'},text=True,capture_output=True,timeout=5)

    @skip_unless_trusted_credential_ancestry
    def test_reports_presence_not_secrets(self):
        p=self.run_check()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('root_password: present (initrd-env)',p.stdout)
        self.assertNotIn('Never-Display',p.stdout+p.stderr)

    @skip_unless_trusted_credential_ancestry
    def test_reports_override_without_printing_it(self):
        self.cmdline.write_text('quiet root_password=Different-Never-Display-Fixture\n')
        p=self.run_check()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('root_password: present (command-line)',p.stdout)
        self.assertNotIn('Never-Display',p.stdout+p.stderr)

    @skip_unless_trusted_credential_ancestry
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

    @skip_unless_trusted_credential_ancestry
    def test_invalid_shell_file_reports_error_without_contents(self):
        self.envfile.write_text("PRESEED_ROOT_PASSWORD='Never-Display-Broken-Quote\n")
        p=self.run_check()
        self.assertEqual(p.returncode,2)
        self.assertIn('invalid shell syntax',p.stderr)
        self.assertNotIn('Never-Display',p.stdout+p.stderr)

if __name__=='__main__':
    unittest.main()
