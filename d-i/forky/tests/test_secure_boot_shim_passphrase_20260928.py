"""Offline Secure Boot state credential checks; never touch a block device."""
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
CREDENTIALS = FORKY / 'scripts/common/credentials.sh'
GRUB = FORKY / 'scripts/late/grub.sh'
Q = shlex.quote
SHELLS = [['/bin/dash']]
if shutil.which('busybox'):
    SHELLS.append([shutil.which('busybox'), 'sh'])


class ShimSignedPassphraseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='shim-credential-')
        self.addCleanup(self.tmp.cleanup)
        self.env_file = Path(self.tmp.name) / 'preseed.env'
        self.secret = 'distinct $pass phrase with spaces'
        self.write_env('PRESEED_SHIM_SIGNED_PASSPHRASE=' + Q(self.secret) + '\n')

    def write_env(self, content):
        self.env_file.write_text(content)
        self.env_file.chmod(0o600)

    def run_shell(self, shell, code, *, mode='luks'):
        script = f'''set -eu
. {Q(str(CREDENTIALS))}
. {Q(str(GRUB))}
# This sandbox has no /tmp. Keep the production reader's private mktemp
# behavior while redirecting only its fixed staging template into the fixture.
mktemp() {{
  case "$1" in
    /tmp/preseed-env.XXXXXX) command mktemp "$TEST_PRIVATE_TMP/preseed-env.XXXXXX" ;;
    *) command mktemp "$@" ;;
  esac
}}
installer_fatal() {{ printf 'fatal: %s\\n' "$*" >&2; exit 51; }}
fatal() {{ installer_fatal "$@"; }}
target_secure_boot_state_mode() {{ printf '%s\\n' "$TEST_STATE_MODE"; }}
target_is_mounted() {{ return 0; }}
install() {{ printf 'install-called\\n' >&2; }}
DEV_PART_VAR_LIB_SHSIGNED=/dev/nonexistent-shim-test-device
LUKS_NAME_VAR_LIB_SHSIGNED=shim-test
LUKS_MAPPER_VAR_LIB_SHSIGNED=/dev/mapper/shim-test
MNT_VAR_LIB_SHSIGNED_OPTS=nosuid,nodev
DIR_VAR_LIB_SHSIGNED=/var/lib/shim-signed
DIR_SECURE_BOOT_STATE=/var/lib/secure-boot
{code}
'''
        return subprocess.run([*shell, '-c', script], text=True, capture_output=True,
                              env={**os.environ,
                                   'INSTALLER_PRESEED_ENV_FILE': str(self.env_file),
                                   'PRESEED_SHIM_SIGNED_PASSPHRASE': 'unsafe-inherited-value',
                                   'INSTALLER_CMDLINE': 'shim_signed_passphrase=unsafe-command-line',
                                   'TEST_PRIVATE_TMP': self.tmp.name,
                                   'TEST_STATE_MODE': mode}, timeout=10)

    def test_private_reader_ignores_inherited_and_cmdline_values(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell(shell, 'preseed_env_read_value shim_signed_passphrase')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, self.secret + '\n')

    def test_missing_or_empty_secret_fails_before_any_partition_action(self):
        for content in ('', 'PRESEED_SHIM_SIGNED_PASSPHRASE=\'\'\n'):
            self.write_env(content)
            for shell in SHELLS:
                with self.subTest(shell=shell, content=content):
                    result = self.run_shell(shell, 'ensure_target_secure_boot_state_mount')
                    self.assertEqual(result.returncode, 51, result.stderr)
                    self.assertIn('requires PRESEED_SHIM_SIGNED_PASSPHRASE', result.stderr)
                    self.assertNotIn('install-called', result.stderr)
                    self.assertNotIn('unsafe-inherited-value', result.stderr)

    def test_valid_secret_reaches_device_check_without_leaking_it(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell(shell, 'ensure_target_secure_boot_state_mount')
                self.assertEqual(result.returncode, 51, result.stderr)
                self.assertIn('state partition is missing', result.stderr)
                self.assertNotIn('install-called', result.stderr)
                self.assertNotIn(self.secret, result.stderr)

    def test_multiline_secret_is_rejected_without_truncation(self):
        self.write_env("PRESEED_SHIM_SIGNED_PASSPHRASE='first line\nsecond line'\n")
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell(shell, 'ensure_target_secure_boot_state_mount')
                self.assertEqual(result.returncode, 51, result.stderr)
                self.assertIn('single printable line', result.stderr)
                self.assertNotIn('install-called', result.stderr)

    def test_direct_mode_does_not_require_secret(self):
        self.write_env('')
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell(shell, 'ensure_target_secure_boot_state_mount', mode='direct')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr.count('install-called'), 2)

    def test_luks_open_receives_only_private_credential(self):
        source = GRUB.read_text()
        body = source.split('ensure_target_secure_boot_state_mount() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('preseed_env_read_value shim_signed_passphrase', body)
        self.assertIn('"$secure_boot_luks_passphrase"', body)
        self.assertNotIn('ACCOUNT_USERNAME', body)
        self.assertLess(body.index('preseed_env_read_value shim_signed_passphrase'),
                        body.index('open_luks_mapping_with_passphrase'))


if __name__ == '__main__':
    unittest.main()
