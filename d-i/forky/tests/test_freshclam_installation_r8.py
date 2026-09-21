"""FreshClam package-ownership regression: disposable files and chroot only.

The Debian postinst assigns clamav:adm and 0444 (0400 for proxy credentials).
No package is installed, no signature update is requested, and host /etc is
never changed. Unit fixtures use real chown/chmod with only NSS mocked. The
whole-helper tests use actual NSS files inside a child-only chroot, no mocks.
"""
from pathlib import Path
import errno
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'hooks/target'
HELPER = TARGET / 'usr/local/libexec/labwc-configure-session-repairs'
CLAMAV_UID = 23117  # Deliberately not a guessed Debian package UID.
CLAMAV_GID = 23118
ADM_GID = 4
DEFAULT_NOTIFY = b'NotifyClamd /etc/clamav/clamd.conf\n'
SECRET = b'fixture-proxy-secret'
CONFIG = b'DatabaseOwner clamav\n' + DEFAULT_NOTIFY + b'HTTPProxyPassword ' + SECRET + b'\n'


def load_helper():
    module = types.ModuleType('fixture_session_repairs_r8')
    module.__file__ = str(HELPER)
    exec(compile(HELPER.read_bytes(), str(HELPER), 'exec'), module.__dict__)
    return module


def file_state(path):
    meta = path.stat()
    return (path.read_bytes(), meta.st_uid, meta.st_gid,
            stat.S_IMODE(meta.st_mode), meta.st_ino, meta.st_mtime_ns)


@unittest.skipUnless(os.geteuid() == 0, 'real file ownership fixtures require root')
class FreshClamFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / 'freshclam.conf'
        self.helper = load_helper()
        patch = mock.patch.object(self.helper.pwd, 'getpwnam', side_effect=self.lookup)
        self.lookup_mock = patch.start()
        self.addCleanup(patch.stop)
        self.write_config()

    @staticmethod
    def lookup(name):
        if name != 'clamav':
            raise KeyError(name)
        return types.SimpleNamespace(pw_uid=CLAMAV_UID)

    def write_config(self, data=CONFIG, uid=CLAMAV_UID, mode=0o400):
        self.path.write_bytes(data)
        os.chown(self.path, uid, ADM_GID)
        self.path.chmod(mode)

    def reconcile(self):
        return self.helper.reconcile_clamd_notification(self.directory)

    def assert_no_temporary_files(self):
        self.assertEqual(list(self.directory.glob('.freshclam.conf.*')), [])

    def test_debian_readonly_and_administrator_modes_preserve_real_metadata(self):
        for uid in (0, CLAMAV_UID):
            for mode in (0o400, 0o444, 0o600, 0o640, 0o644):
                with self.subTest(uid=uid, mode=oct(mode)):
                    self.write_config(uid=uid, mode=mode)
                    self.assertTrue(self.reconcile())
                    first = file_state(self.path)
                    self.assertEqual(first[1:4], (uid, ADM_GID, mode))
                    self.assertIn(b'HTTPProxyPassword ' + SECRET, first[0])
                    self.assertNotIn(b'\nNotifyClamd ', first[0])
                    self.assertFalse(self.reconcile())
                    self.assertEqual(file_state(self.path), first)
                    self.assert_no_temporary_files()

    def test_valid_package_file_without_notify_is_a_noop(self):
        for mode in (0o400, 0o444):
            with self.subTest(mode=oct(mode)):
                self.write_config(CONFIG.replace(DEFAULT_NOTIFY, b''), mode=mode)
                before = file_state(self.path)
                self.assertFalse(self.reconcile())
                self.assertEqual(file_state(self.path), before)

    def test_only_named_package_uid_is_trusted_not_content_or_primary_group(self):
        self.write_config(b'DatabaseOwner desktop\n' + DEFAULT_NOTIFY,
                          uid=CLAMAV_UID + 1, mode=0o444)
        before = file_state(self.path)
        with self.assertRaisesRegex(RuntimeError, 'unsafe freshclam configuration') as caught:
            self.reconcile()
        self.assertIn(f'uid={CLAMAV_UID + 1}', str(caught.exception))
        self.assertIn('gid=4 mode=0444 links=1', str(caught.exception))
        self.assertEqual(file_state(self.path), before)
        self.assert_no_temporary_files()

    def test_missing_package_account_does_not_trust_nonroot_file(self):
        self.lookup_mock.side_effect = KeyError('clamav')
        before = file_state(self.path)
        with self.assertRaisesRegex(RuntimeError, 'unsafe freshclam configuration'):
            self.reconcile()
        self.assertEqual(file_state(self.path), before)

    def test_root_owned_file_does_not_require_package_account_lookup(self):
        self.lookup_mock.side_effect = AssertionError('root needs no alternate owner')
        self.write_config(uid=0, mode=0o600)
        self.assertTrue(self.reconcile())
        self.lookup_mock.assert_not_called()

    def test_writable_executable_and_special_modes_are_rejected(self):
        for mode in (0o664, 0o666, 0o620, 0o602, 0o740, 0o641, 0o4600, 0o2600, 0o1600):
            with self.subTest(mode=oct(mode)):
                self.write_config(mode=mode)
                before = file_state(self.path)
                with self.assertRaisesRegex(RuntimeError, 'unsafe freshclam configuration'):
                    self.reconcile()
                self.assertEqual(file_state(self.path), before)
                self.assert_no_temporary_files()

    def test_diagnostic_reports_metadata_without_leaking_credentials(self):
        self.write_config(mode=0o666)
        with self.assertRaises(RuntimeError) as caught:
            self.reconcile()
        message = str(caught.exception)
        self.assertIn('mode=0666', message)
        self.assertIn('owned by root or clamav', message)
        self.assertNotIn(SECRET.decode(), message)
        self.assertNotIn('HTTPProxyPassword', message)

    def test_symlink_and_dangling_symlink_are_rejected_without_writes(self):
        self.path.unlink()
        other = self.directory / 'other'
        other.write_bytes(CONFIG)
        for destination in (other, self.directory / 'missing'):
            with self.subTest(destination=destination.name):
                self.path.symlink_to(destination)
                with self.assertRaises(OSError):
                    self.reconcile()
                self.assertTrue(self.path.is_symlink())
                self.assertEqual(other.read_bytes(), CONFIG)
                self.path.unlink()
        self.assert_no_temporary_files()

    def test_hardlink_is_rejected_without_changing_either_name(self):
        other = self.directory / 'linked'
        os.link(self.path, other)
        before = file_state(self.path)
        with self.assertRaisesRegex(RuntimeError, 'links=2'):
            self.reconcile()
        self.assertEqual(file_state(self.path), before)
        self.assertEqual(file_state(other), before)

    def test_directory_instead_of_config_is_rejected(self):
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises((OSError, RuntimeError)):
            self.reconcile()
        self.assertTrue(self.path.is_dir())
        self.assert_no_temporary_files()

    def test_clamav_directory_still_requires_root_and_no_group_write(self):
        for uid, mode in ((CLAMAV_UID, 0o755), (0, 0o775), (0, 0o777)):
            with self.subTest(uid=uid, mode=oct(mode)):
                os.chown(self.directory, uid, 0)
                self.directory.chmod(mode)
                try:
                    with self.assertRaisesRegex(RuntimeError, 'unsafe clamav configuration directory'):
                        self.reconcile()
                finally:
                    os.chown(self.directory, 0, 0)
                    self.directory.chmod(0o700)
        self.assertEqual(self.path.read_bytes(), CONFIG)

    def test_symlinked_directory_is_rejected(self):
        alias = self.directory / 'alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(OSError):
            self.helper.reconcile_clamd_notification(alias)
        self.assertEqual(self.path.read_bytes(), CONFIG)

    def test_missing_optional_files_are_noops_not_created(self):
        self.assertFalse(self.helper.reconcile_clamd_notification(self.directory / 'absent'))
        self.path.unlink()
        self.assertFalse(self.reconcile())
        self.assertFalse(self.path.exists())

    def test_present_root_owned_daemon_keeps_default_notification(self):
        daemon = self.directory / 'clamd.conf'
        daemon.write_bytes(b'LocalSocket /run/clamav/clamd.ctl\n')
        daemon.chmod(0o644)
        before, daemon_before = file_state(self.path), file_state(daemon)
        self.assertFalse(self.reconcile())
        self.assertEqual(file_state(self.path), before)
        self.assertEqual(file_state(daemon), daemon_before)

    def test_clamd_owner_and_symlink_policy_is_not_relaxed(self):
        daemon = self.directory / 'clamd.conf'
        daemon.write_bytes(b'User clamav\n')
        os.chown(daemon, CLAMAV_UID, ADM_GID)
        with self.assertRaisesRegex(RuntimeError, 'unsafe clamd configuration'):
            self.reconcile()
        daemon.unlink()
        daemon.symlink_to(self.path)
        with self.assertRaisesRegex(RuntimeError, 'unsafe clamd configuration'):
            self.reconcile()
        self.assertEqual(self.path.read_bytes(), CONFIG)

    def test_custom_paths_comments_and_other_directives_are_not_rewritten(self):
        data = (b'NotifyClamd /etc/company/clamd.conf\n'
                b'NotifyClamd /etc/clamav/clamd.conf.other\n'
                b'# NotifyClamd /etc/clamav/clamd.conf\n'
                b'HTTPProxyPassword ' + SECRET + b'\n'
                b'DatabaseCustomURL https://signatures.example.invalid/custom.ndb\n')
        self.write_config(data)
        before = file_state(self.path)
        self.assertFalse(self.reconcile())
        self.assertEqual(file_state(self.path), before)

    def test_byte_preservation_including_crlf_non_utf8_and_missing_final_newline(self):
        data = (b'# administrator comment \xff\r\n'
                b'DatabaseOwner clamav\r\n'
                b'\tNotifyClamd\t/etc/clamav/clamd.conf \t\r\n'
                b'HTTPProxyPassword ' + SECRET + b'\r\n'
                b'NotifyClamd /etc/clamav/clamd.conf')
        self.write_config(data)
        self.assertTrue(self.reconcile())
        expected = data.replace(b'\tNotifyClamd', b'# Managed scanner-only install; clamd.conf absent: \tNotifyClamd')
        expected = expected.replace(b'\nNotifyClamd', b'\n# Managed scanner-only install; clamd.conf absent: NotifyClamd')
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertFalse(self.reconcile())

    def test_byte_limit_accepts_boundary_without_creating_a_new_file(self):
        self.write_config(b'#' + b'x' * 65535)
        before = file_state(self.path)
        self.assertFalse(self.reconcile())
        self.assertEqual(file_state(self.path), before)

    def test_byte_limit_rejects_ascii_and_multibyte_oversize_before_writing(self):
        for data in (b'#' + b'x' * 65536, b'#' + b'\xc3\xa4' * 32768):
            with self.subTest(bytes=len(data)):
                self.write_config(data)
                before = file_state(self.path)
                with self.assertRaisesRegex(RuntimeError, 'limit: 65536 bytes'):
                    self.reconcile()
                self.assertEqual(file_state(self.path), before)
                self.assert_no_temporary_files()

    def test_output_growth_cannot_create_a_file_rejected_on_next_run(self):
        self.write_config(DEFAULT_NOTIFY + b'#' + b'x' * (65536 - len(DEFAULT_NOTIFY) - 1))
        before = file_state(self.path)
        with self.assertRaisesRegex(RuntimeError, 'oversized freshclam configuration after reconciliation'):
            self.reconcile()
        self.assertEqual(file_state(self.path), before)
        self.assert_no_temporary_files()

    def test_failed_chown_fsync_and_rename_leave_original_and_remove_temporary(self):
        for operation in ('fchown', 'fsync', 'replace'):
            with self.subTest(operation=operation):
                before = file_state(self.path)
                with mock.patch.object(self.helper.os, operation, side_effect=OSError(errno.EIO, 'fixture failure')):
                    with self.assertRaises(OSError):
                        self.reconcile()
                self.assertEqual(file_state(self.path), before)
                self.assert_no_temporary_files()

    def test_preexisting_temporary_symlink_is_not_followed_or_deleted(self):
        import secrets
        victim = self.directory / 'victim'
        victim.write_bytes(b'untouched')
        collision = self.directory / ('.freshclam.conf.' + 'a' * 32)
        collision.symlink_to(victim)
        before = file_state(self.path)
        with mock.patch.object(secrets, 'token_hex', return_value='a' * 32):
            with self.assertRaises(FileExistsError):
                self.reconcile()
        self.assertEqual(file_state(self.path), before)
        self.assertTrue(collision.is_symlink())
        self.assertEqual(victim.read_bytes(), b'untouched')

    def test_observed_edit_during_read_is_not_overwritten(self):
        original_fstat = os.fstat
        source_inode = self.path.stat().st_ino
        reads = 0
        edited = CONFIG + b'# concurrent edit\n'
        def fstat(fd):
            nonlocal reads
            result = original_fstat(fd)
            if result.st_ino == source_inode and stat.S_ISREG(result.st_mode):
                reads += 1
                if reads == 2:
                    self.path.write_bytes(edited)
                    return original_fstat(fd)
            return result
        with mock.patch.object(self.helper.os, 'fstat', side_effect=fstat):
            with self.assertRaisesRegex(RuntimeError, 'changed while reading'):
                self.reconcile()
        self.assertEqual(self.path.read_bytes(), edited)
        self.assert_no_temporary_files()

    def test_source_replaced_before_publication_is_not_overwritten(self):
        original_fsync = os.fsync
        edited = b'DatabaseOwner clamav\n# replacement by administrator\n'
        def fsync(fd):
            original_fsync(fd)
            if stat.S_ISREG(os.fstat(fd).st_mode):
                self.path.unlink()
                self.write_config(edited)
        with mock.patch.object(self.helper.os, 'fsync', side_effect=fsync):
            with self.assertRaisesRegex(RuntimeError, 'changed before replacement'):
                self.reconcile()
        self.assertEqual(self.path.read_bytes(), edited)
        self.assert_no_temporary_files()

    def test_new_clamd_configuration_before_publication_prevents_edit(self):
        original_fsync = os.fsync
        before = file_state(self.path)
        def fsync(fd):
            original_fsync(fd)
            if stat.S_ISREG(os.fstat(fd).st_mode):
                (self.directory / 'clamd.conf').write_bytes(b'User clamav\n')
        with mock.patch.object(self.helper.os, 'fsync', side_effect=fsync):
            with self.assertRaisesRegex(RuntimeError, 'clamd configuration appeared'):
                self.reconcile()
        self.assertEqual(file_state(self.path), before)
        self.assert_no_temporary_files()

    def test_file_descriptors_are_released_on_success_noop_and_rejection(self):
        fd_directory = Path('/proc/self/fd')
        if not fd_directory.is_dir():
            self.skipTest('procfs is needed for descriptor accounting')
        baseline = len(list(fd_directory.iterdir()))
        for _ in range(12):
            self.write_config()
            self.assertTrue(self.reconcile())
            self.assertFalse(self.reconcile())
            self.write_config(mode=0o666)
            with self.assertRaises(RuntimeError):
                self.reconcile()
        self.assertEqual(len(list(fd_directory.iterdir())), baseline)


# All target paths and passwd/group lookups are real inside this child chroot.
# Imports/compilation happen first: the fixture needs no copied Python runtime.
# This tests the full helper, not a full Debian installation or a FreshClam run.
CHROOT_DRIVER = r'''
import os, sys, pwd, re, stat, tempfile, secrets
from pathlib import Path
source = Path(sys.argv[2])
code = compile(source.read_bytes(), '/usr/local/libexec/labwc-configure-session-repairs', 'exec')
read_as_service = sys.argv[3] == 'read'
try:
    os.chroot(sys.argv[1])
except PermissionError:
    print('CAP_SYS_CHROOT unavailable', file=sys.stderr)
    raise SystemExit(77)
os.chdir('/')
sys.argv = ['/usr/local/libexec/labwc-configure-session-repairs', 'desktop']
exec(code, {'__name__': '__main__', '__file__': sys.argv[0]})
assert 'pam_env.so' in Path('/etc/pam.d/sudo-i').read_text()
print('target-session-repairs-completed')
if read_as_service:
    account = pwd.getpwnam('clamav')
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    assert b'DatabaseOwner clamav' in Path('/etc/clamav/freshclam.conf').read_bytes()
    print('unprivileged-clamav-read-confirmed')
'''


@unittest.skipUnless(os.geteuid() == 0 and hasattr(os, 'chroot'), 'child chroot fixtures require root')
class WholeInstallerHelperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o755)
        for name in ('etc/clamav', 'etc/pam.d', 'etc/security', 'home/desktop'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.passwd = self.root / 'etc/passwd'
        self.passwd.write_text(
            'root:x:0:0:root:/root:/bin/sh\n'
            f'clamav:x:{CLAMAV_UID}:{CLAMAV_GID}:ClamAV:/var/lib/clamav:/bin/false\n'
            'desktop:x:1000:1000:Desktop:/home/desktop:/bin/sh\n')
        (self.root / 'etc/group').write_text(
            f'root:x:0:\nadm:x:{ADM_GID}:\nclamav:x:{CLAMAV_GID}:\ndesktop:x:1000:\n')
        (self.root / 'etc/nsswitch.conf').write_text('passwd: files\ngroup: files\n')
        self.pam = self.root / 'etc/pam.d/sudo-i'
        self.original_pam = b'@include common-auth\n@include common-account\n@include common-session\n'
        self.pam.write_bytes(self.original_pam)
        (self.root / 'etc/security/managed-sudo-i.conf').write_bytes(
            (TARGET / 'etc/security/managed-sudo-i.conf').read_bytes())
        self.path = self.root / 'etc/clamav/freshclam.conf'
        self.config()

    def config(self, data=CONFIG, mode=0o400):
        self.path.write_bytes(data)
        os.chown(self.path, CLAMAV_UID, ADM_GID)
        self.path.chmod(mode)

    def invoke(self, read_as_service=True):
        result = subprocess.run(
            [sys.executable, '-I', '-B', '-c', CHROOT_DRIVER, str(self.root), str(HELPER),
             'read' if read_as_service else 'no-read'],
            text=True, capture_output=True, timeout=5)
        if result.returncode == 77 and result.stderr.strip() == 'CAP_SYS_CHROOT unavailable':
            self.skipTest('CAP_SYS_CHROOT unavailable in this environment')
        self.assertNotIn(SECRET.decode(), result.stdout + result.stderr)
        return result

    def test_preseed_without_notification_completes_with_debian_ownership(self):
        for mode in (0o400, 0o444):
            with self.subTest(mode=oct(mode)):
                self.config(CONFIG.replace(DEFAULT_NOTIFY, b''), mode=mode)
                before = file_state(self.path)
                result = self.invoke()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('unprivileged-clamav-read-confirmed', result.stdout)
                self.assertEqual(file_state(self.path), before)
                self.assertEqual(self.pam.read_bytes().count(b'pam_env.so'), 1)

    def test_stale_notification_repaired_full_helper_is_idempotent_and_readable(self):
        for mode in (0o400, 0o444):
            with self.subTest(mode=oct(mode)):
                self.config(mode=mode)
                first = self.invoke()
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertIn('disabled stale default NotifyClamd', first.stderr)
                before = file_state(self.path)
                self.assertEqual(before[1:4], (CLAMAV_UID, ADM_GID, mode))
                self.assertNotIn(b'\nNotifyClamd ', before[0])
                again = self.invoke()
                self.assertEqual(again.returncode, 0, again.stderr)
                self.assertNotIn('disabled stale default NotifyClamd', again.stderr)
                self.assertEqual(file_state(self.path), before)
                self.assertEqual(self.pam.read_bytes().count(b'pam_env.so'), 1)

    def test_installed_daemon_preserves_notification_and_completes(self):
        (self.root / 'etc/clamav/clamd.conf').write_bytes(b'User clamav\n')
        before = file_state(self.path)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(file_state(self.path), before)

    def test_custom_notification_path_is_preserved_by_full_helper(self):
        self.config(CONFIG.replace(b'/etc/clamav/clamd.conf', b'/etc/company/clamd.conf'))
        before = file_state(self.path)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(file_state(self.path), before)

    def test_unknown_file_owner_fails_with_diagnostics_and_no_pam_changes(self):
        os.chown(self.path, 1000, ADM_GID)
        before = file_state(self.path)
        result = self.invoke(False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('session-repairs: unsafe freshclam configuration: uid=1000', result.stderr)
        self.assertEqual(file_state(self.path), before)
        self.assertEqual(self.pam.read_bytes(), self.original_pam)

    def test_world_writable_configuration_still_fails_installation(self):
        self.path.chmod(0o666)
        before = file_state(self.path)
        result = self.invoke(False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('mode=0666', result.stderr)
        self.assertEqual(file_state(self.path), before)
        self.assertEqual(self.pam.read_bytes(), self.original_pam)

    def test_absent_package_account_still_fails_nonroot_configuration(self):
        self.passwd.write_text('\n'.join(line for line in self.passwd.read_text().splitlines()
                                         if not line.startswith('clamav:')) + '\n')
        result = self.invoke(False)
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'unsafe freshclam configuration: uid={CLAMAV_UID}', result.stderr)
        self.assertEqual(self.pam.read_bytes(), self.original_pam)

    def test_fifo_fails_promptly_without_waiting_for_a_writer(self):
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        result = self.invoke(False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('unsafe freshclam configuration', result.stderr)
        self.assertTrue(stat.S_ISFIFO(self.path.stat().st_mode))
        self.assertEqual(self.pam.read_bytes(), self.original_pam)


    def staged_invoke(self, shell):
        def function(path, name):
            marker = name + '() {'
            body = path.read_text().split(marker, 1)[1].split('\n}\n', 1)[0]
            return marker + body + '\n}\n'
        # Execute the production staging and mandatory-command wrapper. Only
        # transport, logging and hardware boundaries are fixture implementations.
        functions = function(ROOT / 'scripts/desktop/components.sh', 'desktop_stage_session_repairs')
        functions += function(ROOT / 'scripts/common/target.sh', 'run_in_target')
        runner = self.root / 'chroot-driver.py'
        runner.write_text(CHROOT_DRIVER)
        script = r'''
set -eu
ensure_target_asset_parent() { mkdir -p "$TARGET_FIXTURE${1%/*}"; }
target_asset_host_path() { printf '%s%s\n' "$TARGET_FIXTURE" "$1"; }
remove_target_asset() { rm -f "$TARGET_FIXTURE$1"; }
desktop_stage_role_asset() {
    mkdir -p "$TARGET_FIXTURE${2%/*}"
    cp "$TARGET_SOURCE/$1" "$TARGET_FIXTURE$2"
    chmod "$3" "$TARGET_FIXTURE$2"
}
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
installer_runtime_temp_log_path() { printf '%s/installer-output.log\n' "$TARGET_FIXTURE"; }
installer_info() { :; }
installer_error() { printf '%s\n' "$*" >&2; }
target_log_command_start() { :; }
target_log_command_complete() { :; }
target_log_command_failure() { :; }
target_log_should_emit() { return 0; }
filter_in_target_noise() { cat; }
target_exec() {
    case "$1" in
        /usr/bin/systemd-hwdb)
            [ "$#" = 3 ] && [ "$2" = --strict ] && [ "$3" = update ] || return 1
            printf '%s\n' fixture-hwdb-boundary-not-executed
            ;;
        /usr/local/libexec/labwc-configure-session-repairs)
            [ "$#" = 2 ] && [ "$2" = desktop ] || return 1
            "$FIXTURE_PYTHON" -I -B "$FIXTURE_DRIVER" "$TARGET_FIXTURE" "$TARGET_FIXTURE$1" read
            ;;
        *) return 99 ;;
    esac
}
ACCOUNT_USERNAME=desktop
'''
        environment = {**os.environ, 'TARGET_FIXTURE': str(self.root), 'TARGET_SOURCE': str(TARGET),
                       'FIXTURE_PYTHON': sys.executable, 'FIXTURE_DRIVER': str(runner)}
        result = subprocess.run([*shell, '-c', script + functions + '\ndesktop_stage_session_repairs\n'],
                                capture_output=True, text=True, env=environment, timeout=10)
        if result.returncode == 77 and 'CAP_SYS_CHROOT unavailable' in result.stderr:
            self.skipTest('CAP_SYS_CHROOT unavailable in this environment')
        self.assertNotIn(SECRET.decode(), result.stdout + result.stderr)
        return result

    def test_real_staging_and_required_runner_under_all_installer_shells(self):
        import shutil
        shells = [command for command in (['dash'], ['bash'], ['busybox', 'sh']) if shutil.which(command[0])]
        self.assertTrue(shells)
        for shell in shells:
            with self.subTest(shell=shell):
                self.config()
                result = self.staged_invoke(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('unprivileged-clamav-read-confirmed', result.stdout)
                staged = self.root / 'usr/local/libexec/labwc-configure-session-repairs'
                self.assertEqual(staged.read_bytes(), HELPER.read_bytes())
                self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o755)
                self.assertEqual(file_state(self.path)[1:4], (CLAMAV_UID, ADM_GID, 0o400))
                self.assertFalse((self.root / 'installer-output.log').exists())

    def test_required_runner_still_aborts_for_unsafe_files_under_all_shells(self):
        import shutil
        shells = [command for command in (['dash'], ['bash'], ['busybox', 'sh']) if shutil.which(command[0])]
        self.assertTrue(shells)
        for shell in shells:
            with self.subTest(shell=shell):
                self.config(mode=0o666)
                before = file_state(self.path)
                result = self.staged_invoke(shell)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('in-target failed during configure managed session repairs (status 1)', result.stderr)
                self.assertIn('session-repairs: unsafe freshclam configuration', result.stderr)
                self.assertNotIn('target-session-repairs-completed', result.stdout)
                self.assertEqual(file_state(self.path), before)
                self.assertEqual(self.pam.read_bytes(), self.original_pam)
                self.assertFalse((self.root / 'installer-output.log').exists())


if __name__ == '__main__':
    unittest.main()
