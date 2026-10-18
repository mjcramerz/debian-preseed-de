"""Failure specifications for the continuing audit; disposable execution only.

These fixtures use checkout code, private files and explicit fake signing tools.
They do not claim native cryptographic, AppArmor or firmware acceptance.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import os
import ast
import gzip
from pathlib import Path
import shlex
import runpy
import subprocess
import tempfile
import unittest
from unittest import mock
from payload_fixture import read_text, installed_script

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
LIB = TARGET / 'usr/local/lib/perl5/site_perl'
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': '/nonexistent'}


def function(source: str, name: str) -> str:
    start = source.index(name + '() {\n')
    return source[start:source.index('\n}\n', start) + 3]


class MokResetTests(unittest.TestCase):
    def reset(self, failure='none', listing='certificate'):
        source = read_text(TARGET / 'usr/libexec/install-tools/secure-boot-tool')
        start = source.index('reset_mok_state() (\n')
        body = source[start:source.index('\n)\n', start) + 3]
        with tempfile.TemporaryDirectory(prefix='mok-reset-') as temporary:
            calls = Path(temporary) / 'calls'
            stubs = r'''
require_command() { :; }
resolve_mok_delete_password() {
  case "$LISTING" in certificate|multiple|mixed) ;; *) return 97 ;; esac
  printf '%s\n' 'fixture-password'
}
fatal() { printf '%s\n' "$*" >&2; exit 1; }
log() { printf '%s\n' "$*" >&2; }
timeout() {
  [ "$1" = --kill-after=2 ] || return 90
  case "$2" in 15|30) ;; *) return 91 ;; esac
  shift 2
  "$@"
}
mokutil() {
  printf '%s\n' "$*" >>"$CALLS"
  case "$1" in
    --list-enrolled)
      [ "$#" -eq 1 ] || return 98
      case "$LISTING" in
        certificate|multiple|mixed)
          printf '%s\n' '[key 1]' 'SHA1 Fingerprint: aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd' 'Certificate:'
          if [ "$LISTING" = multiple ]; then
            printf '%s\n' '[key 2]' 'SHA1 Fingerprint: dd:ee:ff:aa:bb:cc:00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd' 'Certificate:'
          elif [ "$LISTING" = mixed ]; then
            printf '%s\n' '[key 2]' 'SHA1 Fingerprint: 53:61:0c:f8:1f:bd:7e:0c:eb:67:91:3c:9e:f3:e7:94:a9:63:3e:cb' 'Certificate:'
          fi
          ;;
        vendor) printf '%s\n' '[key 1]' 'SHA1 Fingerprint: 53:61:0C:F8:1F:BD:7E:0C:EB:67:91:3C:9E:F3:E7:94:A9:63:3E:CB' 'Certificate:' ;;
        malformed) printf '%s\n' '[key 1]' 'SHA1 Fingerprint: aa:bb:cc' 'Certificate:' ;;
        empty) : ;;
        message) printf '%s\n' 'MokListRT is empty' ;;
        hash) printf '%s\n' '[key 1]' 'Hash Algorithm: sha256' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' ;;
        *) return 99 ;;
      esac
      case "$FAILURE" in query) return 73 ;; query-timeout) return 124 ;; esac
      ;;
    --reset)
      [ "$#" -eq 1 ] || return 92
      IFS= read -r first && IFS= read -r second || return 93
      [ "$first" = fixture-password ] && [ "$second" = "$first" ] || return 94
      [ "$FAILURE" != reset ]
      ;;
    --timeout)
      [ "$#" -eq 2 ] && [ "$2" = 900 ] || return 95
      [ "$FAILURE" != timeout ]
      ;;
    *) return 96 ;;
  esac
}
'''
            result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body + '\nreset_mok_state'],
                                    env={**ENV, 'CALLS': str(calls), 'FAILURE': failure,
                                         'LISTING': listing},
                                    capture_output=True, text=True, timeout=5)
            self.assertNotIn('fixture-password', result.stdout + result.stderr)
            return result, calls.read_text().splitlines()

    def test_full_reset_when_an_owner_certificate_is_enrolled(self):
        # The newly generated certificate is intentionally absent from the
        # fixture: previous installations' keys must still be covered.
        for listing in ('certificate', 'multiple', 'mixed'):
            with self.subTest(listing=listing):
                result, calls = self.reset(listing=listing)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ['--list-enrolled', '--reset', '--timeout 900'])
                self.assertIn('confirm the reset in MokManager', result.stderr)
                self.assertEqual(result.stdout, 'queued\n')

    def test_no_certificate_skips_reset_and_password_lookup(self):
        for listing in ('empty', 'message', 'hash', 'vendor'):
            with self.subTest(listing=listing):
                result, calls = self.reset(listing=listing)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ['--list-enrolled'])
                self.assertIn('no owner-enrolled MOK certificates reported; skipping reset', result.stderr)
                self.assertEqual(result.stdout, 'empty\n')
                self.assertNotIn('full MOK reset queued', result.stderr)

    def test_malformed_fingerprint_never_queues_reset(self):
        result, calls = self.reset(listing='malformed')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ['--list-enrolled'])
        self.assertIn('invalid MOK certificate inventory', result.stderr)

    def test_failed_or_timed_out_query_never_queues_reset(self):
        # Partial certificate output must not override a failed query status.
        for failure in ('query', 'query-timeout'):
            with self.subTest(failure=failure):
                result, calls = self.reset(failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, ['--list-enrolled'])
                self.assertIn('could not query enrolled MOK certificates; skipping reset', result.stderr)
                self.assertNotIn('full MOK reset queued', result.stderr)

    def test_failed_request_is_not_retried_or_reported_as_queued(self):
        result, calls = self.reset('reset')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ['--list-enrolled', '--reset'])
        self.assertIn('may already be pending', result.stderr)
        self.assertNotIn('full MOK reset queued', result.stderr)

    def test_timeout_adjustment_failure_keeps_successful_reset_result(self):
        result, calls = self.reset('timeout')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['--list-enrolled', '--reset', '--timeout 900'])
        self.assertIn('timeout could not be set', result.stderr)

    def test_installer_continues_when_request_cannot_be_queued(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        body = function(source, 'reset_target_secure_boot_mok_state')
        caller = r'''
if reset_target_secure_boot_mok_state; then
  printf 'enrollment-queued\n'
fi
printf 'installation-continued\n'
'''
        for failure in ('return 37', 'exit 37'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                stubs = ('installer_lifecycle_paths() { :; }\n'
                         'installer_runtime_state_dir() { printf \'%s\\n\' "$FIXTURE_ROOT"; }\n'
                         'installer_metadata_value() { printf \'0:0:600:1\\n\'; }\n'
                         'reset_target_secure_boot_mok_state_attempt() { printf attempt >>"$FIXTURE_ROOT/calls"; ' + failure + '; }\n'
                         'installer_warn() { printf \'%s\\n\' "$*" >&2; }\n')
                result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body + caller],
                                        env={**ENV, 'FIXTURE_ROOT': temporary}, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'installation-continued')
                self.assertIn('continuing install', result.stderr)
                self.assertEqual((Path(temporary) / 'secure-boot-mok-reset.state').read_text(), 'unknown\n')
                # A new process must retain an uncertain result without retry.
                again = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body + caller],
                                       env={**ENV, 'FIXTURE_ROOT': temporary}, capture_output=True, text=True, timeout=5)
                self.assertEqual(again.returncode, 0, again.stderr)
                self.assertEqual((Path(temporary) / 'calls').read_text(), 'attempt')

    def test_reset_command_does_not_prepare_or_copy_enrollment_keys(self):
        source = read_text(TARGET / 'usr/libexec/install-tools/secure-boot-tool')
        body = function(source, 'cmd_reset_moks')
        stubs = ('require_root() { :; }\n'
                 'ensure_keypair() { exit 91; }\n'
                 'ensure_dkms_framework_config() { exit 92; }\n'
                 'reset_mok_state() { printf \'empty\\n\'; }\n')
        result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body + '\ncmd_reset_moks'],
                                env=ENV, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'empty\n')

    def test_cached_result_metadata_and_content_are_checked_without_firmware_retry(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        body = function(source, 'reset_target_secure_boot_mok_state')
        lifecycle = read_text(TARGET.parents[1] / 'scripts/common/lifecycle.sh')
        start = lifecycle.index('installer_metadata_value() (\n')
        metadata = lifecycle[start:lifecycle.index('\n);\n', start) + 4]
        stubs = r'''
installer_lifecycle_paths() { :; }
installer_runtime_state_dir() { printf '%s\n' "$FIXTURE_ROOT"; }
reset_target_secure_boot_mok_state_attempt() { printf unexpected >>"$FIXTURE_ROOT/calls"; return 91; }
installer_warn() { printf '%s\n' "$*" >&2; }
'''
        for state, mode, expected in [('empty\n', 0o600, 0), ('queued\n', 0o600, 0),
                                      ('unknown\n', 0o600, 1), ('queued\nextra\n', 0o600, 1),
                                      ('queued\n', 0o666, 1)]:
            with self.subTest(state=state, mode=mode), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'secure-boot-mok-reset.state'
                path.write_text(state)
                path.chmod(mode)
                result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + metadata + body +
                                         '\nreset_target_secure_boot_mok_state'],
                                        env={**ENV, 'FIXTURE_ROOT': temporary},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(path.read_text(), state)
                self.assertFalse((Path(temporary) / 'calls').exists())

    def test_shared_staging_checks_reset_before_enrollment_preparation(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        stage = function(source, 'stage_target_secure_boot_runtime_assets')
        self.assertLess(stage.index('reset_target_secure_boot_mok_state'),
                        stage.index('install_target_secure_boot_kernel_hooks'))
        prepkgsel = read_text(TARGET.parent / 'installer/pre-pkgsel.d/90secure-boot-dkms.sh')
        self.assertLess(prepkgsel.index('\nensure_target_mok_inventory_command\n'),
                        prepkgsel.index('\nstage_target_secure_boot_runtime_assets\n'))
        self.assertLess(prepkgsel.index('stage_target_secure_boot_runtime_assets'),
                        prepkgsel.index('run_installer_secure_boot_install_tool prepare-dkms'))

    def test_missing_inventory_command_is_resolved_before_preparation(self):
        source = read_text(TARGET.parent / 'installer/pre-pkgsel.d/90secure-boot-dkms.sh')
        body = function(source, 'ensure_target_mok_inventory_command')
        stubs = r'''
test_in_target() { [ "$PRESENT" = yes ]; }
run_in_target() {
  printf 'install\n'
  [ "$MODE" != failed ] || return 71
  if [ "$MODE" != still-missing ]; then PRESENT=yes; fi
}
prepkgsel_fatal() { printf 'unavailable\n' >&2; exit 72; }
'''
        for mode, present, expected in [('present', 'yes', 0), ('install', 'no', 0),
                                        ('failed', 'no', 71), ('still-missing', 'no', 72)]:
            with self.subTest(mode=mode):
                result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body + '\nensure_target_mok_inventory_command'],
                                        env={**ENV, 'MODE': mode, 'PRESENT': present},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stdout, '' if present == 'yes' else 'install\n')

    def test_reset_policy_has_scoped_efi_paths(self):
        source = read_text(TARGET / 'etc/apparmor.d/system-wrappers')
        profile = source.split('profile secure-boot-tool ', 1)[1].split('\n}', 1)[0]
        self.assertIn('/sys/firmware/efi/mok-variables/MokListRT r,', profile)
        self.assertIn('/sys/firmware/efi/efivars/MokListRT{,[0-9]*}-605dab50-e046-4300-abb6-3dd810dd8b23 r,', profile)
        self.assertIn('/sys/firmware/efi/efivars/{MokNew,MokAuth,MokTimeout}-605dab50-e046-4300-abb6-3dd810dd8b23 rw,', profile)
        self.assertNotIn('/sys/firmware/efi/**', profile)


class InstallerCleanupTests(unittest.TestCase):
    def test_missing_signal_authority_preserves_unknown_result(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/ssh/ssh-install.py')
        tree = ast.parse(source)
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and node.name == 'stop_owned']
        self.assertEqual(len(definitions), 1)
        fake_os = mock.Mock()
        for name in ('P_PID', 'WEXITED', 'WNOHANG', 'WNOWAIT'):
            setattr(fake_os, name, getattr(os, name))
        fake_os.waitid.return_value = None
        fake_os.getsid.return_value = 1234
        fake_os.killpg.side_effect = PermissionError('fixture')
        process = mock.Mock(pid=1234, returncode=None)
        error = type('CleanupUnknown', (ValueError,), {})
        namespace = {'os': fake_os, 'subprocess': subprocess, 'signal': mock.Mock(SIGKILL=9),
                     'CleanupUnknown': error}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), '<isolated-cleanup-function>', 'exec'), namespace)
        with self.assertRaisesRegex(error, 'termination could not be confirmed'):
            namespace['stop_owned'](process)
        fake_os.killpg.assert_called_once_with(1234, 9)
        process.wait.assert_not_called()

    def test_missing_child_identity_never_signals_numeric_process_group(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/ssh/ssh-install.py')
        tree = ast.parse(source)
        definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                          and node.name == 'stop_owned')
        fake_os = mock.Mock()
        for name in ('P_PID', 'WEXITED', 'WNOHANG', 'WNOWAIT'):
            setattr(fake_os, name, getattr(os, name))
        fake_os.waitid.side_effect = ChildProcessError('fixture')
        process = mock.Mock(pid=1234, returncode=None)
        error = type('CleanupUnknown', (ValueError,), {})
        namespace = {'os': fake_os, 'subprocess': subprocess, 'signal': mock.Mock(SIGKILL=9),
                     'CleanupUnknown': error}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), '<isolated-cleanup-function>', 'exec'), namespace)
        with self.assertRaisesRegex(error, 'identity unavailable'):
            namespace['stop_owned'](process)
        fake_os.killpg.assert_not_called()
        process.wait.assert_not_called()


class BootPublicationTests(unittest.TestCase):
    def test_compressed_module_expansion_is_limited_before_full_output(self):
        source = read_text(TARGET / 'usr/libexec/install-tools/verify-module-signature.py')
        with tempfile.TemporaryDirectory(prefix='module-expansion-') as temporary:
            root = Path(temporary)
            helper = root / 'verifier.py'
            helper.write_text(source.replace('MAX_MODULE_BYTES = 512 * 1024 * 1024', 'MAX_MODULE_BYTES = 1024'))
            compressed = root / 'fixture.ko.gz'
            compressed.write_bytes(gzip.compress(b'x' * 65536))
            output = root / 'module.ko'
            result = subprocess.run(['/usr/bin/python3', '-ISB', str(helper), '--decompress',
                                     str(compressed), str(output)],
                                    env=ENV, capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertLessEqual(output.stat().st_size, 1024)
            self.assertIn('size limit', result.stderr)

    def test_failed_or_unverified_signing_preserves_original_kernel(self):
        source = read_text(TARGET / 'usr/libexec/install-tools/secure-boot-tool')
        body = function(source, 'sign_kernel_image')
        for failure in ('sign', 'verify'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(prefix='boot-candidate-') as temporary:
                root = Path(temporary)
                (root / 'boot').mkdir(); (root / 'tmp').mkdir()
                original = root / 'boot/vmlinuz-fixture'
                original.write_bytes(b'previous-bootable-kernel')
                candidate = body.replace('/boot', str(root / 'boot')).replace('/tmp/', str(root / 'tmp') + '/')
                stubs = r'''
fatal() { printf '%s\n' "$*" >&2; exit 1; }
require_secure_boot_signing_commands() { :; }
log_file_with_prefix() { :; }
kernel_image_has_managed_signature() { return 1; }
sbsign() {
  output=
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --output ]; then shift; output=$1; fi
    shift
  done
  printf 'unverified-candidate' >"$output"
  [ "$FAILURE" != sign ]
}
SECURE_BOOT_MOK_KEY=fixture-key
SECURE_BOOT_MOK_CERT_PEM=fixture-cert
'''
                result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + candidate + '\nsign_kernel_image fixture'],
                                        env={**ENV, 'FAILURE': failure}, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(original.read_bytes(), b'previous-bootable-kernel')
                self.assertEqual(list((root / 'boot').iterdir()), [original])


@unittest.skipUnless(os.geteuid() == 0, 'requires root inside the disposable image')
class PolicyOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='policy-owner-', dir='/var/lib')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        module = self.root / 'Managed/PolicyLock.pm'
        module.parent.mkdir()
        source = read_text(LIB / 'runtime/Managed/PolicyLock.pm')
        self.state = self.root / 'state'
        source = source.replace("my $directory = '/var/lib/labwc-apparmor-policy';",
                                "my $directory = '" + str(self.state) + "';")
        module.write_text(source)

    def perl(self, code, *arguments):
        return subprocess.run(['/usr/bin/perl', '-I' + str(self.root), '-I' + str(LIB / 'apt-repo-local'),
                               '-e', code, '--', *arguments],
                              env=ENV, capture_output=True, text=True, timeout=5)

    def test_nested_handoff_retains_one_owner_and_close_on_exec(self):
        code = r'''
use Managed::PolicyLock qw(acquire_policy_lock with_policy_lock_handoff);
use Fcntl qw(F_GETFD FD_CLOEXEC);
my $guard = acquire_policy_lock();
die 'missing close-on-exec' unless fcntl($guard->{fh}, F_GETFD, 0) & FD_CLOEXEC;
with_policy_lock_handoff(sub {
    system($^X, '-I'.$ARGV[0], '-MManaged::PolicyLock=acquire_policy_lock',
           '-e', 'my $guard = acquire_policy_lock(); print "nested-owner\\n";') == 0 or die 'handoff failed';
});
die 'handoff leaked descriptor flags' unless fcntl($guard->{fh}, F_GETFD, 0) & FD_CLOEXEC;
system($^X, '-I'.$ARGV[0], '-MManaged::PolicyLock=acquire_policy_lock',
       '-e', 'my $guard = acquire_policy_lock();') != 0 or die 'competing owner admitted';
'''
        result = self.perl(code, str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'nested-owner')
        self.assertIn('another AppArmor policy operation', result.stderr)

    def test_handoff_to_another_inode_is_rejected(self):
        foreign = self.root / 'foreign'
        foreign.write_bytes(b'fixture')
        foreign.chmod(0o600)
        result = self.perl(r'''
use Managed::PolicyLock qw(acquire_policy_lock);
open my $foreign, '+<', $ARGV[0] or die 'fixture';
$ENV{MANAGED_APPARMOR_POLICY_LOCK_FD} = fileno($foreign);
my $guard = acquire_policy_lock();
''', str(foreign))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('handoff identity changed', result.stderr)

    def test_hardlinked_lock_is_rejected(self):
        self.state.mkdir(mode=0o700)
        lock = self.state / 'policy.lock'
        lock.write_bytes(b''); lock.chmod(0o600)
        os.link(lock, self.root / 'extra-link')
        result = self.perl('use Managed::PolicyLock qw(acquire_policy_lock); my $guard = acquire_policy_lock();')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe AppArmor policy lock', result.stderr)

    def chatgpt_transaction(self, context):
        source = read_text(LIB / 'apt-repo-local/APTRepoLocal/Servicing/ChatGPT.pm')
        replacements = {'/usr/local/share/software/chatgpt': '/canonical',
                        '/var/lib/software': '/software', '/etc': '/etc',
                        '/usr/share/pixmaps': '/pixmaps',
                        '/usr/local/share/applications': '/applications',
                        '/usr/share/keyrings': '/keyrings'}
        for old, relative in replacements.items():
            source = source.replace("'" + old, "'" + str(self.root) + relative)
        module = self.root / 'ChatGPT.pm'
        module.write_text(source)
        canonical = self.root / 'canonical'
        canonical.mkdir()
        (canonical / 'default').write_bytes(b'new-default\n')
        (canonical / 'apparmor.profile').write_bytes(b'new-profile\n')
        default = self.root / 'etc/chatgpt/package-policy.conf'
        profile = self.root / 'etc/apparmor.d/chatgpt'
        for path, data in ((default, b'previous-default\n'), (profile, b'previous-profile\n')):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data); path.chmod(0o600)
        (self.root / 'software').mkdir()
        driver = r'''
require $ARGV[0];
{
    no warnings 'redefine';
    *APTRepoLocal::Servicing::ChatGPT::enabled = sub { 1 };
    *APTRepoLocal::Servicing::ChatGPT::_validate_policy_syntax = sub { 1 };
    *APTRepoLocal::Servicing::ChatGPT::_diversion_owner = sub { 'LOCAL' };
    *APTRepoLocal::Servicing::ChatGPT::_diversion_target = sub { APTRepoLocal::Servicing::ChatGPT::DIVERSION_PATH() };
    *APTRepoLocal::Servicing::ChatGPT::_live_apparmor_interface_is_available = sub { 1 };
    *APTRepoLocal::Servicing::ChatGPT::_reload_policy_if_available = sub { die "fixture reload failure\n" };
}
my $object = APTRepoLocal::Servicing::ChatGPT->new(state => bless({}, 'FixtureState'));
$object->prepare_install($ARGV[1]);
die 'missing pre-publication snapshot' unless -f APTRepoLocal::Servicing::ChatGPT::POLICY_RECOVERY().'/previous.json';
my $ok = eval { $object->abort_install(); 1 };
if ($ARGV[1] eq 'installer') { die $@ unless $ok; }
else { die 'uncertain recovery was accepted' if $ok; die $@ unless $@ =~ /rollback outcome unknown/; }
'''
        result = self.perl(driver, str(module), context)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(default.read_bytes(), b'previous-default\n')
        self.assertEqual(profile.read_bytes(), b'previous-profile\n')
        self.assertEqual(default.stat().st_mode & 0o7777, 0o600)
        for absent in ('etc/default/chatgpt', 'etc/apparmor.d/disable/chatgpt'):
            path = self.root / absent
            self.assertFalse(path.exists() or path.is_symlink())

    def test_preparation_rollback_restores_true_previous_bytes_mode_and_absence(self):
        self.chatgpt_transaction('installer')
        self.assertFalse((self.root / 'software/chatgpt-policy-recovery').exists())

    def test_unverified_runtime_restore_retains_private_recovery(self):
        self.chatgpt_transaction('runtime')
        snapshot = self.root / 'software/chatgpt-policy-recovery/previous.json'
        self.assertTrue(snapshot.is_file())
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)


@unittest.skipUnless(os.geteuid() == 0, 'requires root-owned disposable fixtures')
class RepositorySourceRepairTests(unittest.TestCase):
    def test_unchanged_generation_repairs_missing_owned_source(self):
        implementation = runpy.run_path(str(installed_script(TARGET / 'usr/local/libexec/apt-repo-local')))
        with tempfile.TemporaryDirectory(prefix='repository-source-', dir='/var/lib') as temporary:
            root = Path(temporary)
            repository = object.__new__(implementation['Repository'])
            repository.repo = root / 'repo'
            repository.repo.mkdir()
            (repository.repo / 'current').symlink_to('.snapshots/fixture')
            repository.changed = False
            repository.source = root / 'parts/apt-repo-local.sources'
            repository.keyring = root / 'local.gpg'
            repository.source_template = root / 'source.template'
            repository.source_template.write_text('URIs: file:@@REPOSITORY@@\nSigned-By: @@KEYRING@@\n')
            repository.ensure_policies = lambda: None
            repository.finish_inbox = lambda: None
            repository.publish()
            self.assertEqual(repository.source.read_text(),
                             f'URIs: file:{repository.repo}\nSigned-By: {repository.keyring}\n')
