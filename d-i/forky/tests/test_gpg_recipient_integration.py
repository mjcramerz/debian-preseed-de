"""Regression coverage for the logged Aptly/desktop GPG keyring collision.

Cryptographic integration uses disposable GnuPG keys as an unprivileged user.
No deployment identity, private initrd, network, installed service or mount is
used. Shell transport tests replace only the target boundary, not crypto.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import pwd
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SEED = Path(__file__).resolve().parents[1]
SOURCE = SEED / 'scripts/late/ssh/ssh-install.py'
COMPONENTS = SEED / 'scripts/desktop/components.sh'
spec = importlib.util.spec_from_file_location('gpg_recipient_integration', SOURCE)
ssh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssh)
FP = 'A' * 40
SUB = 'B' * 40
OTHER = 'C' * 40


def record(kind, fingerprint, capability, *, validity='u', trust='u', local='+', created='100'):
    fields = [kind, validity, '255', '22', fingerprint[-16:], created, '', '', trust,
              '', '', capability, '', '', local, '', '', '', '', '', '']
    return ':'.join(fields) + '\nfpr:::::::::' + fingerprint + ':\n'


def public_listing():
    return (record('pub', FP, 'scESC', local='') + record('sub', SUB, 'e', local='')).encode()


def secret_listing():
    return (record('sec', FP, 'scESC') + record('ssb', SUB, 'e')).encode()


class ListingTests(unittest.TestCase):
    def test_subkey_fingerprint_is_not_primary(self):
        self.assertEqual([fp for _, fp in ssh.gpg_key_records(public_listing(), 'pub')], [FP, SUB])

    def test_v6_full_fingerprint_supported(self):
        listing = record('pub', 'D' * 64, 'eE', local='').encode()
        self.assertEqual(ssh.gpg_key_records(listing, 'pub')[0][1], 'D' * 64)

    def test_malformed_fingerprint_lengths_rejected(self):
        for count in (0, 16, 39, 41, 63, 65):
            with self.subTest(count=count), self.assertRaises(ssh.InstallError):
                ssh.gpg_key_records(record('pub', 'A' * count, 'eE').encode(), 'pub')

    def test_truncated_and_orphan_records_rejected(self):
        for listing in (b'pub:u:', b'pub:u:\nfpr:::::::::' + FP.encode() + b':',
                        b'fpr:::::::::' + FP.encode() + b':', public_listing().split(b'fpr:')[0],
                        b'sub:u:255:22:1:100::::::e:\nfpr:::::::::' + FP.encode() + b':'):
            with self.subTest(listing=listing), self.assertRaises(ssh.InstallError):
                ssh.gpg_key_records(listing, 'pub')

    def test_multiple_primary_and_duplicate_fingerprints_rejected(self):
        for extra in (record('pub', OTHER, 'eE'), record('sub', SUB, 'e')):
            with self.subTest(extra=extra), self.assertRaises(ssh.InstallError):
                ssh.gpg_key_records(public_listing() + extra.encode(), 'pub')

    def test_wrong_record_family_rejected(self):
        with self.assertRaises(ssh.InstallError):
            ssh.gpg_key_records(secret_listing(), 'pub')


@unittest.skipUnless(os.geteuid() == 0, 'root ownership/runuser contract')
class SealValidationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='gpg-selection-', dir='/root')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        (self.home / '.gnupg').mkdir(mode=0o700)
        self.calls = []
        self.public, self.private = public_listing(), secret_listing()
        self.ciphertext = b'fixture encrypted bytes'
        self.blob = self.home / '.local/share/ssh/git-key-passphrase.gpg'
        self.patch = mock.patch.object(ssh, 'checked', side_effect=self.checked)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def checked(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if '--list-keys' in argv:
            return self.public
        if '--list-secret-keys' in argv:
            return self.private
        if '--encrypt' in argv:
            return self.ciphertext
        self.assertEqual(argv[-3:], ['/usr/bin/gpgconf', '--kill', 'gpg-agent'])
        return b''

    def seal(self, fingerprint=FP):
        ssh.seal(pwd.getpwuid(0), self.home, b'not-a-deployment-passphrase', fingerprint)

    def refused(self):
        with self.assertRaises(ssh.InstallError):
            self.seal()
        self.assertFalse(payload_source_exists(self.blob))
        self.assertFalse(any('--encrypt' in argv for argv, _ in self.calls))
        self.assertIn('--kill', self.calls[-1][0])

    def test_lists_are_scoped_to_exact_desktop_fingerprint(self):
        self.seal()
        listing = [argv for argv, _ in self.calls if '--with-colons' in argv]
        self.assertEqual(len(listing), 2)
        for argv in listing:
            self.assertEqual(argv[-2:], ['--', FP])
        encrypt = next(argv for argv, _ in self.calls if '--encrypt' in argv)
        self.assertEqual(encrypt[encrypt.index('--recipient') + 1], SUB + '!')
        self.assertEqual(payload_read_bytes(self.blob), self.ciphertext)
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.blob).st_mode), 0o600)

    def test_invalid_fingerprint_refused_before_launch(self):
        for value in ('', 'A'*16, 'A'*41, FP.lower(), FP+'!', '--all'):
            with self.subTest(value=value), self.assertRaises(ssh.InstallError):
                self.seal(value)
        self.assertEqual(self.calls, [])

    def test_different_returned_primary_is_not_accepted(self):
        self.public = self.public.replace(FP.encode(), OTHER.encode())
        self.refused()

    def test_selected_signing_only_key_is_refused(self):
        self.public = record('pub', FP, 'scSC').encode()
        self.refused()

    def test_disabled_capability_is_refused(self):
        self.public = self.public.replace(b'scESC', b'scESCD')
        self.refused()

    def test_revoked_expired_invalid_primary_is_refused(self):
        for validity in ('r', 'e', 'i', 'd'):
            with self.subTest(validity=validity):
                self.public = public_listing().replace(b'pub:u:', ('pub:' + validity + ':').encode())
                self.refused()

    def test_lowercase_e_is_not_whole_key_usability(self):
        self.public = record('pub', FP, 'esc').encode()
        self.refused()

    def test_ultimate_ownertrust_is_required(self):
        self.public = record('pub', FP, 'scESC', trust='-').encode() + record('sub', SUB, 'e').encode()
        self.refused()

    def test_secret_primary_mismatch_is_refused(self):
        self.private = self.private.replace(FP.encode(), OTHER.encode())
        self.refused()

    def test_offline_or_card_only_encryption_material_is_refused(self):
        for marker in ('#', '>', '', '0123456789ABCDEF'):
            with self.subTest(marker=marker):
                self.private = (record('sec', FP, 'scESC') + record('ssb', SUB, 'e', local=marker)).encode()
                self.refused()

    def test_expired_encryption_subkey_is_refused(self):
        self.public = self.public.replace(b'sub:u:', b'sub:e:')
        self.refused()

    def test_selects_newest_usable_local_subkey_of_selected_primary(self):
        self.public += record('sub', OTHER, 'e', created='200').encode()
        self.private += record('ssb', OTHER, 'e', created='200').encode()
        self.seal()
        encrypt = next(argv for argv, _ in self.calls if '--encrypt' in argv)
        self.assertEqual(encrypt[encrypt.index('--recipient') + 1], OTHER + '!')

    def test_ignores_newer_offline_subkey(self):
        self.public += record('sub', OTHER, 'e', created='200').encode()
        self.private += record('ssb', OTHER, 'e', created='200', local='#').encode()
        self.seal()
        encrypt = next(argv for argv, _ in self.calls if '--encrypt' in argv)
        self.assertEqual(encrypt[encrypt.index('--recipient') + 1], SUB + '!')

    def test_failed_encryption_preserves_existing_ciphertext_and_stops_agent(self):
        ssh.publish(self.blob, b'previous ciphertext', 0, 0)
        self.ciphertext = b''
        with self.assertRaises(ssh.InstallError):
            self.seal()
        self.assertEqual(payload_read_bytes(self.blob), b'previous ciphertext')
        self.assertIn('--kill', self.calls[-1][0])

    def test_gpg_failure_preserves_existing_ciphertext_and_stops_agent(self):
        ssh.publish(self.blob, b'previous ciphertext', 0, 0)
        original = self.checked
        def failed(argv, **kwargs):
            if '--encrypt' in argv:
                raise ssh.InstallError('injected encryption command failure')
            return original(argv, **kwargs)
        with mock.patch.object(ssh, 'checked', side_effect=failed), self.assertRaises(ssh.InstallError):
            self.seal()
        self.assertEqual(payload_read_bytes(self.blob), b'previous ciphertext')
        self.assertIn('--kill', self.calls[-1][0])


class CliTests(unittest.TestCase):
    def test_seal_requires_explicit_fingerprint_no_keyring_fallback(self):
        p = subprocess.run(payload_installed_argv([sys.executable, '-I', '-B', str(SOURCE), 'seal', 'nobody',
                            '/tmp/git-ssh.FIXTURE']), input=b'', capture_output=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn(b'--gpg-fingerprint is required only for the seal action', p.stderr)

    def test_fingerprint_argument_not_accepted_for_provision(self):
        p = subprocess.run(payload_installed_argv([sys.executable, '-I', '-B', str(SOURCE), 'provision', 'nobody',
                            '/tmp/git-ssh.FIXTURE', '--gpg-fingerprint', FP]), input=b'', capture_output=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn(b'--gpg-fingerprint is required only', p.stderr)


def bootstrap_body():
    source = payload_read_text(COMPONENTS)
    start = source.index('  if ! attempt_in_target "bootstrap primary account GPG key for KWallet"')
    start = source.index("/bin/sh -c '\n", start) + len("/bin/sh -c '\n")
    end = source.index("\n' sh \"$ACCOUNT_USERNAME\"", start)
    return source[start:end].replace("'\\''", "'")


@unittest.skipUnless(os.geteuid() == 0 and all(shutil.which(n) for n in ('gpg', 'gpgconf', 'runuser')),
                     'real GnuPG and root required for unprivileged account fixture')
class RealBootstrapIntegrationTests(unittest.TestCase):
    def test_real_bootstrap_mixed_keyring_seal_cold_decrypt_and_idempotent_retry(self):
        account = pwd.getpwnam('nobody')
        with tempfile.TemporaryDirectory(prefix='x-gpg-integration-', dir='/home') as name, \
                tempfile.TemporaryDirectory(prefix='gpg-root-stage-') as rootname:
            home, stage = Path(name), Path(rootname)
            os.chown(home, account.pw_uid, account.pw_gid)
            gnupg = home / '.gnupg'
            gnupg.mkdir(mode=0o700)
            os.chown(gnupg, account.pw_uid, account.pw_gid)
            prefix = ['/usr/sbin/runuser', '-u', account.pw_name, '--', '/usr/bin/env', '-i',
                      f'HOME={home}', f'GNUPGHOME={gnupg}', f'USER={account.pw_name}',
                      'PATH=/usr/bin:/bin', 'LC_ALL=C.UTF-8']
            def gpg(*args, data=None):
                p = subprocess.run(payload_installed_argv(prefix + ['/usr/bin/gpg', '--no-options', '--batch'] + list(args)),
                                   input=data, capture_output=True, timeout=60)
                self.assertEqual(p.returncode, 0, p.stderr.decode(errors='replace'))
                return p.stdout
            def stop():
                subprocess.run(payload_installed_argv(prefix + ['/usr/bin/gpgconf', '--kill', 'gpg-agent']),
                               capture_output=True, timeout=15)
            passphrase = b'Disposable GPG fixture only - not deployment input!'
            ssh_secret = b'Disposable SSH fixture - spaces and % supported!'
            try:
                # Reproduce the real ordering: Aptly signing key is imported/
                # present before desktop creates its own encryption identity.
                for uid, algo, usage in [('Aptly signing fixture', 'ed25519', 'sign'),
                                         ('Unrelated encryption fixture', 'future-default', 'default')]:
                    gpg('--pinentry-mode', 'loopback', '--passphrase-fd', '0', '--quick-generate-key',
                        uid, algo, usage, 'never', data=passphrase+b'\n')
                before = ssh.gpg_key_records(gpg('--with-colons', '--list-secret-keys', '--',
                                                '=Aptly signing fixture'), 'sec')
                aptly_fp = before[0][1]
                aptly_public = gpg('--export', aptly_fp)
                stop()
                template = stage / 'gpg-agent.conf'
                template.write_bytes(payload_read_bytes(SEED/'hooks/target/etc/skel-desktop/.gnupg/gpg-agent.conf'))
                stub = stage / 'pinentry-qt'
                stub.write_text('#!/bin/sh\nexit 99\n')
                stub.chmod(0o700)
                body = bootstrap_body().replace('gpg_agent_template=/etc/skel-desktop/.gnupg/gpg-agent.conf',
                                                'gpg_agent_template='+shlex.quote(str(template)))
                output_fingerprint = None
                for attempt in range(2):
                    passfile, fingerprint_file = stage/'passphrase', stage/'fingerprint'
                    passfile.write_bytes(passphrase+b'\n'); passfile.chmod(0o600)
                    p = subprocess.run(payload_installed_argv(['/bin/sh', '-c', body, 'sh', account.pw_name, str(home),
                                        'Managed desktop fixture', str(passfile), str(fingerprint_file)]),
                                       env=dict(os.environ, PATH=str(stage)+':/usr/sbin:/usr/bin:/sbin:/bin',
                                                LC_ALL='C.UTF-8'), capture_output=True, timeout=90)
                    self.assertEqual(p.returncode, 0, p.stderr.decode(errors='replace'))
                    self.assertNotIn(passphrase, p.stdout+p.stderr)
                    self.assertFalse(payload_source_exists(passfile))
                    self.assertEqual(payload_source_stat(fingerprint_file).st_uid, 0)
                    self.assertEqual(stat.S_IMODE(payload_source_stat(fingerprint_file).st_mode), 0o600)
                    fingerprint = payload_read_text(fingerprint_file).strip()
                    if output_fingerprint is not None:
                        self.assertEqual(fingerprint, output_fingerprint)
                    output_fingerprint = fingerprint
                    self.assertNotEqual(fingerprint, aptly_fp)
                    ssh.seal(account, home, ssh_secret, fingerprint)
                    blob = home/'.local/share/ssh/git-key-passphrase.gpg'
                    self.assertEqual(payload_source_stat(blob).st_uid, account.pw_uid)
                    self.assertEqual(stat.S_IMODE(payload_source_stat(blob).st_mode), 0o600)
                    # The seal action explicitly stopped its listing agent. A
                    # fresh loopback decrypt supplies ONLY the GPG passphrase.
                    self.assertFalse(payload_source_exists(gnupg/'S.gpg-agent'))
                    plaintext = gpg('--pinentry-mode', 'loopback', '--passphrase-fd', '0',
                                    '--decrypt', str(blob), data=passphrase+b'\n')
                    self.assertEqual(plaintext, ssh_secret)
                    self.assertEqual(gpg('--export', aptly_fp), aptly_public)
                    self.assertIn(aptly_fp.encode(), gpg('--with-colons', '--list-secret-keys', '--', aptly_fp))
                    for path in home.rglob('*'):
                        if payload_source_is_file(path) and not path.is_symlink():
                            self.assertNotIn(ssh_secret, payload_read_bytes(path), str(path))
                    stop()
            finally:
                stop()


class ShellHandoffTests(unittest.TestCase):
    def run_fixture(self, kind):
        with tempfile.TemporaryDirectory(prefix='gpg-handoff-') as tmp:
            target = Path(tmp)/'target'; target.mkdir()
            source = payload_read_text(COMPONENTS)
            start = source.index('desktop_bootstrap_primary_account_gpg_key() {')
            end = source.index('\ndesktop_user_unit_template_dir()', start)
            function = source[start:end].replace('/target', str(target))
            script = '''set -eu
installer_fatal() { printf '%s\\n' "$*" >&2; exit 1; }
desktop_require_absolute_account_home() { :; }
desktop_primary_account_gpg_user_id() { printf '%s\\n' 'Managed desktop fixture'; }
desktop_primary_account_gpg_passphrase() { printf '%s\\n' 'not-a-real-secret'; }
desktop_log() { :; }
rm() {
  # Delete the disposable fixture but report failure, so the test can prove
  # cleanup failures never turn a transaction into a reported success.
  command rm "$@" || return 1
  [ "$KIND" != cleanup-failure ]
}
attempt_in_target() {
  [ "$KIND" != bootstrap-failure ] || return 1
  for last; do :; done
  case "$KIND" in
    absent) return 0 ;;
    malformed) printf '%s\\n' 'not-a-fingerprint' >"$TARGET$last" ;;
    *) printf '%s\\n' "$FINGERPRINT" >"$TARGET$last" ;;
  esac
}
managed_git_ssh_target_action() {
  [ "$#" -eq 3 ] && [ "$1" = seal ] && [ "$2" = --gpg-fingerprint ] && [ "$3" = "$FINGERPRINT" ] || exit 99
  [ "$KIND" != seal-failure ] || return 1
  printf '%s\\n' 'selected-fingerprint-handed-off'
}
'''+function+'''
ACCOUNT_USERNAME=fixture
ACCOUNT_HOME=/home/fixture
ACCOUNT_FULLNAME='Fixture Desktop'
ACCOUNT_GPG_PASSPHRASE='not-a-real-secret'
ACCOUNT_GPG_PASSPHRASE_IS_PLAIN=true
desktop_bootstrap_primary_account_gpg_key
[ "${ACCOUNT_GPG_PASSPHRASE_IS_PLAIN}" = false ]
[ -z "${ACCOUNT_GPG_PASSPHRASE+x}" ]
printf '%s\\n' completed
'''
            results = []
            shells = [['/bin/dash'], ['/bin/bash']]
            if shutil.which('busybox'): shells.append([shutil.which('busybox'), 'ash'])
            for shell in shells:
                p = subprocess.run(payload_installed_argv(shell+['-c', script]), env=dict(os.environ, KIND=kind, TARGET=str(target),
                                                               FINGERPRINT=FP), capture_output=True, timeout=15)
                self.assertEqual(list((target/'tmp').glob('desktop-gpg.*')), [])
                self.assertNotIn(b'not-a-real-secret', p.stdout+p.stderr)
                results.append(p)
            return results

    def test_success_handoff_and_staging_cleanup_three_shells(self):
        for p in self.run_fixture('success'):
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn(b'selected-fingerprint-handed-off', p.stdout)
            self.assertIn(b'completed', p.stdout)

    def test_failure_cleanup_no_continue_three_shells(self):
        for kind in ('bootstrap-failure', 'absent', 'malformed', 'seal-failure', 'cleanup-failure'):
            with self.subTest(kind=kind):
                for p in self.run_fixture(kind):
                    self.assertNotEqual(p.returncode, 0)
                    self.assertNotIn(b'completed', p.stdout)

    def test_no_unscoped_seal_call_left_in_desktop_flow(self):
        source = payload_read_text(COMPONENTS)
        self.assertNotIn('managed_git_ssh_target_action seal ||', source)
        self.assertEqual(source.count('managed_git_ssh_target_action seal --gpg-fingerprint'), 1)


class LoggedTransportTests(unittest.TestCase):
    def test_adopted_package_transactions_disable_pty_like_other_installs(self):
        source = payload_read_text(SEED/'scripts/late/software.sh')
        start = source.index('for software_binary_package in $software_binary_packages; do')
        end = source.index('\ndone', start)
        block = source[start:end]
        self.assertIn('-o DPkg::Use-Pty=0', block)
        self.assertIn('LC_ALL=C.UTF-8', block)
        self.assertIn('|| software_fatal', block)

    def test_in_target_bridge_drops_stale_locale_and_child_has_utf8(self):
        with tempfile.TemporaryDirectory(prefix='locale-boundary-') as name:
            root = Path(name)
            stub = root/'in-target'
            stub.write_text('#!/bin/sh\n[ "$LC_ALL" = C ] || exit 91\n'
                            '[ -z "${LOCPATH+x}" ] || exit 92\nshift\nexec "$@"\n')
            stub.chmod(0o700)
            script = '. '+shlex.quote(str(SEED/'scripts/common/target.sh'))+'\n'+'''
target_exec /bin/sh -c 'printf "%s:%s\\n" "$LANG" "$LC_ALL"'
target_exec /usr/bin/env LC_ALL=C /bin/sh -c 'printf "%s\\n" "$LC_ALL"'
'''
            p = subprocess.run(payload_installed_argv(['/bin/sh', '-c', script]), env=dict(os.environ, PATH=str(root)+':/usr/bin:/bin',
                              LANG='not_an_installed_locale', LC_ALL='not_an_installed_locale',
                              LOCPATH='/does/not/exist'), capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout, b'C.UTF-8:C.UTF-8\nC\n')


if __name__ == '__main__':
    unittest.main()
