"""Installer credential regression tests: never read real deployment secrets.

Tests model the busybox-udeb applet set (not a full GNU/desktop PATH). The
real-kernel/real-USB installation remains a separate acceptance test.
"""
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest

from test_environment import skip_unless_trusted_credential_ancestry

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / 'd-i/forky'
CANONICAL = SEED / 'scripts/common/credentials.sh'
LIBS = [(SEED / 'scripts/common/lib.sh', 'installer'),
        (SEED / 'scripts/runtime/common.sh', 'runtime')]
SHELLS = [('/bin/sh', ['/bin/sh'])]
if shutil.which('bash'):
    SHELLS.append(('bash-posix', [shutil.which('bash'), '--posix']))
if shutil.which('busybox'):
    SHELLS.append(('busybox-ash', [shutil.which('busybox'), 'sh']))
MAPPING = {
    'netcfg/wireless_wpa': 'PRESEED_WIFI_PASSPHRASE',
    'wireless_wpa': 'PRESEED_WIFI_PASSPHRASE',
    'wifi_wpa': 'PRESEED_WIFI_PASSPHRASE',
    'fruux_username': 'PRESEED_FRUUX_USERNAME',
    'fruux_password': 'PRESEED_FRUUX_PASSWORD',
    'primary_user': 'PRESEED_PRIMARY_USERNAME',
    'primary_password': 'PRESEED_PRIMARY_PASSWORD',
    'primary_gpg_passphrase': 'PRESEED_PRIMARY_GPG_PASSPHRASE',
    'root_password': 'PRESEED_ROOT_PASSWORD',
    'crowdsec_token': 'PRESEED_CROWDSEC_TOKEN',
    'crowdsec_enroll_token': 'PRESEED_CROWDSEC_TOKEN',
    'crowdsec_attachment_key': 'PRESEED_CROWDSEC_TOKEN',
    'tailscale_authkey': 'PRESEED_TAILSCALE_TOKEN',
    'tailscale_auth_key': 'PRESEED_TAILSCALE_TOKEN',
    'telegram_chat_id': 'PRESEED_TELEGRAM_CHAT_ID',
    'telegram_api_key': 'PRESEED_TELEGRAM_API_KEY',
    'cf_r2_access_key': 'PRESEED_CF_APTLY_ACCESS_KEY',
    'cf_r2_secret_key': 'PRESEED_CF_APTLY_SECRET_KEY',
    'obs_username': 'PRESEED_OBS_USERNAME',
    'obs_password': 'PRESEED_OBS_PASSWORD',
}

class CredentialFixture(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(prefix='initrd-credentials-')
        self.addCleanup(self.t.cleanup)
        self.dir = Path(self.t.name)
        self.file = self.dir / 'preseed.env'
        self.cmdfile = self.dir / 'cmdline'
        self.cmdfile.write_text('quiet\n')
        self.env = {'PATH': os.environ['PATH'], 'LC_ALL': 'C',
                    'INSTALLER_PRESEED_ENV_FILE': str(self.file),
                    'INSTALLER_CMDLINE_FILE': str(self.cmdfile)}
        self.values = {v: 'Fixture-' + v for v in MAPPING.values()}
        self.write_env()

    def write_env(self, mode=0o600, newline='\n', bom=False):
        # Exactly the supplied PRESEED_* assignment format, comments included.
        text = newline.join('# Former GRUB variable: ' + next(k for k,v in MAPPING.items() if v==name) + '='
                           + newline + name + '=' + shlex.quote(value) + newline
                           for name,value in self.values.items())
        self.file.write_bytes((b'\xef\xbb\xbf' if bom else b'') + text.encode())
        self.file.chmod(mode)

    def run_lookup(self, prefix='installer', key='root_password', cmdline='quiet',
                   shell=None, preamble='', env=None):
        lib = next(path for path,p in LIBS if p==prefix)
        script = 'set -eu\n. ' + shlex.quote(str(lib)) + '\n' + preamble
        script += prefix + '_cmdline_value ' + shlex.quote(key) + '\n'
        e = {**self.env, 'INSTALLER_CMDLINE': cmdline}
        if env:
            e.update(env)
        return subprocess.run((shell or ['/bin/sh']) + ['-c', script], cwd=self.dir,
                              env=e, text=True, capture_output=True, timeout=10)

    def assert_safe_failure(self, result, reason):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(reason, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertNotIn(self.values['PRESEED_ROOT_PASSWORD'], result.stderr)

class InitrdCredentialTests(CredentialFixture):
    def test_both_embedded_readers_are_identical_to_canonical_source(self):
        for lib,_ in LIBS:
            text = lib.read_text().split('# BEGIN EMBEDDED INITRD CREDENTIALS\n',1)[1]
            embedded = text.split('# END EMBEDDED INITRD CREDENTIALS\n',1)[0]
            self.assertEqual(embedded, CANONICAL.read_text())

    @skip_unless_trusted_credential_ancestry
    def test_full_supplied_env_format_all_mappings_all_shells(self):
        for name,shell in SHELLS:
            for prefix in ('installer','runtime'):
                for key,var in MAPPING.items():
                    with self.subTest(shell=name,resolver=prefix,key=key):
                        result = self.run_lookup(prefix,key,shell=shell)
                        self.assertEqual(result.returncode,0,result.stderr)
                        self.assertEqual(result.stdout,self.values[var]+'\n')
                        self.assertEqual(result.stderr,'')

    def test_every_mapping_cmdline_overrides_env(self):
        for prefix in ('installer','runtime'):
            for key in MAPPING:
                with self.subTest(resolver=prefix,key=key):
                    result=self.run_lookup(prefix,key,cmdline=key+'=override-fixture')
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(result.stdout,'override-fixture\n')

    def test_every_mapping_empty_cmdline_is_not_absence(self):
        for prefix in ('installer','runtime'):
            for key in MAPPING:
                with self.subTest(resolver=prefix,key=key):
                    result=self.run_lookup(prefix,key,cmdline=key+'=')
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(result.stdout,'\n')

    @skip_unless_trusted_credential_ancestry
    def test_env_fallback_works_without_stat_in_all_shells(self):
        for name,shell in SHELLS:
            for prefix in ('installer','runtime'):
                with self.subTest(shell=name,resolver=prefix):
                    result=self.run_lookup(prefix,shell=shell,
                                           preamble='stat() { echo STAT_MUST_NOT_RUN >&2; return 127; }\n')
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(result.stdout,self.values['PRESEED_ROOT_PASSWORD']+'\n')
                    self.assertNotIn('STAT_MUST_NOT_RUN',result.stderr)

    @skip_unless_trusted_credential_ancestry
    def test_read_only_shared_bits_are_hardened_before_source(self):
        for mode in (0o400,0o600,0o440,0o444,0o640,0o644,0o604,0o404):
            for prefix in ('installer','runtime'):
                with self.subTest(mode=oct(mode),resolver=prefix):
                    self.file.chmod(mode)
                    result=self.run_lookup(prefix)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn(self.file.stat().st_mode & 0o777,(0o400,0o600))

    def test_unsafe_modes_fail_closed(self):
        for mode in (0o000,0o200,0o660,0o664,0o666,0o755,0o777,0o4600):
            self.file.chmod(mode)
            reason = 'permissions' if os.access(self.file, os.R_OK) else 'readable regular file'
            self.assert_safe_failure(self.run_lookup(),reason)

    @skip_unless_trusted_credential_ancestry
    def test_chmod_failure_is_reported_not_missing_password(self):
        self.file.chmod(0o644)
        self.assert_safe_failure(self.run_lookup(preamble='chmod() { return 1; }\n'),'cannot make')

    def test_ls_failure_is_reported_without_weakening_checks(self):
        self.assert_safe_failure(self.run_lookup(preamble='ls() { return 1; }\n'),'cannot inspect')

    @skip_unless_trusted_credential_ancestry
    def test_crlf_and_bom_and_empty_other_fields_are_supported(self):
        self.values={v:'' for v in self.values}
        self.values['PRESEED_ROOT_PASSWORD']='Fixture!$\\quoted'
        for bom in (False,True):
            self.write_env(newline='\r\n',bom=bom)
            for prefix in ('installer','runtime'):
                result=self.run_lookup(prefix)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,self.values['PRESEED_ROOT_PASSWORD']+'\n')

    @skip_unless_trusted_credential_ancestry
    def test_shell_quoted_apostrophes_and_metacharacters_are_literal(self):
        self.values['PRESEED_ROOT_PASSWORD']="a'b\"$()`;|&*?[]\\#value"
        self.write_env()
        for name,shell in SHELLS:
            result=self.run_lookup(shell=shell)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,self.values['PRESEED_ROOT_PASSWORD']+'\n')

    @skip_unless_trusted_credential_ancestry
    def test_invalid_syntax_is_redacted(self):
        self.file.write_text("PRESEED_ROOT_PASSWORD='"+self.values['PRESEED_ROOT_PASSWORD'])
        self.assert_safe_failure(self.run_lookup(),'invalid shell syntax')

    @skip_unless_trusted_credential_ancestry
    def test_source_stdout_and_stderr_do_not_contaminate_password(self):
        with self.file.open('a') as stream:
            stream.write('\nprintf "NEVER_LOG_SOURCE_OUTPUT"\nprintf "NEVER_LOG_SOURCE_ERROR" >&2\n')
        result=self.run_lookup()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,self.values['PRESEED_ROOT_PASSWORD']+'\n')
        self.assertEqual(result.stderr,'')

    def test_symlink_hardlink_and_fifo_rejected(self):
        self.file.unlink()
        real=self.dir/'real.env';real.write_text("PRESEED_ROOT_PASSWORD='fixture'\n");real.chmod(0o600)
        self.file.symlink_to(real)
        self.assert_safe_failure(self.run_lookup(),'symlink')
        self.file.unlink();os.link(real,self.file)
        self.assert_safe_failure(self.run_lookup(),'hard link')
        self.file.unlink();os.mkfifo(self.file)
        self.assert_safe_failure(self.run_lookup(),'regular file')

    @unittest.skipUnless(os.geteuid()==0,'requires root to set fixture ownership')
    def test_wrong_owner_is_rejected(self):
        os.chown(self.file,65534,65534)
        self.assert_safe_failure(self.run_lookup(),'owned by')

    def test_symlinked_parent_is_rejected(self):
        link=self.dir/'linked';link.symlink_to(self.dir,target_is_directory=True)
        result=self.run_lookup(env={'INSTALLER_PRESEED_ENV_FILE':str(link/'preseed.env')})
        self.assert_safe_failure(result,'symlinked')

    def test_writable_nonsticky_parent_is_rejected(self):
        self.dir.chmod(0o777)
        try:
            self.assert_safe_failure(self.run_lookup(),'parent directory')
        finally:
            self.dir.chmod(0o700)

    @skip_unless_trusted_credential_ancestry
    def test_default_fallback_does_not_inherit_exported_secrets(self):
        self.file.write_text('# no deployment credentials\n')
        result=self.run_lookup(env={'PRESEED_ROOT_PASSWORD':'Inherited-Wrong'})
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(result.stdout,'')

    def test_cmdline_success_never_requires_env_file(self):
        self.file.unlink()
        result=self.run_lookup(cmdline='root_password=override-fixture')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'override-fixture\n')

    def test_cmdline_success_does_not_source_broken_env_file(self):
        self.file.write_text("PRESEED_ROOT_PASSWORD='invalid\n")
        result=self.run_lookup(cmdline='root_password=override-fixture')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'override-fixture\n')

    def test_both_resolvers_accept_explicit_cmdline_file(self):
        self.cmdfile.write_text('quiet root_password=file-override-fixture\n')
        for prefix in ('installer','runtime'):
            result=self.run_lookup(prefix,cmdline='')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'file-override-fixture\n')

    def test_root_account_validation_precedes_disk_discovery(self):
        text=(SEED/'hooks/installer/d-i/early.sh').read_text()
        self.assertLess(text.index('runtime_validate_account_settings'),text.index('  hook_resolve_install_disk'))

    def test_known_alias_does_not_reenable_fallback_of_another_alias(self):
        for group in [('wifi_wpa','wireless_wpa'),('tailscale_authkey','tailscale_auth_key'),
                      ('crowdsec_token','crowdsec_enroll_token')]:
            result=self.run_lookup('installer',group[0],cmdline=group[1]+'=')
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertEqual(result.stdout,'')

class UserHashPrecedenceTests(CredentialFixture):
    @skip_unless_trusted_credential_ancestry
    def test_plaintext_user_password_clears_stale_hash_in_rendered_answers(self):
        self.values['PRESEED_PRIMARY_USERNAME']='fixtureuser'
        self.write_env()
        out=self.dir/'answers.cfg'
        script='set -eu\n'
        for path in (SEED/'scripts/runtime/common.sh',SEED/'scripts/runtime/account.sh',SEED/'hosts/installer/account.env'):
            script+='. '+shlex.quote(str(path))+'\n'
        script+='runtime_write_account_answers '+shlex.quote(str(out))+'\n'
        result=subprocess.run(['/bin/sh','-c',script],env=self.env,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        text=out.read_text()
        self.assertIn('d-i passwd/user-password-crypted password\n',text)
        self.assertIn('d-i passwd/root-login boolean true\n',text)
        self.assertIn('d-i passwd/username string fixtureuser\n',text)
