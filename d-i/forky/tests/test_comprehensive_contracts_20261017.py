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
import re
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
    def test_reset_password_is_bounded_and_usable_in_mokmanager(self):
        source = read_text(TARGET / 'usr/libexec/install-tools/secure-boot-tool')
        definitions = ''
        for name in ('validate_single_line_value', 'validate_single_token_value',
                     'resolve_mok_delete_password'):
            start = source.index(name + '() (\n')
            definitions += source[start:source.index('\n)\n', start) + 3] + '\n'
        for override, username, valid in [('', 'fixture-user', True), ('ignored-token', 'fixture-user', True),
                                           ('ignored-token', '', False), ('', 'x' * 256, True),
                                           ('', 'x' * 257, False), ('', 'with space', False),
                                           ('', 'with\nnewline', False), ('', 'nonascii-å', False),
                                           ('', '', False)]:
            with self.subTest(length=len(override), valid=valid):
                program = 'fatal() { printf \'%s\\n\' "$*" >&2; exit 1; }\n' + definitions
                # Match the conditional command substitution used by reset;
                # failures must propagate even when errexit is suppressed.
                program += ('\nif password=$(resolve_mok_delete_password); then\n'
                            '  printf \'%s\\n\' "$password"\nelse\n  exit 1\nfi\n')
                result = subprocess.run(['/bin/dash', '-eu', '-c', program],
                                        env={**ENV, 'SECURE_BOOT_MOK_DELETE_PASSWORD': override,
                                             'ACCOUNT_USERNAME': username},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0 if valid else 1, result.stderr)
                self.assertEqual(result.stdout, username + '\n' if valid else '')
                if override:
                    self.assertNotIn(override, result.stderr)

    def test_rendered_configuration_supplies_username_to_a_clean_helper_process(self):
        # Exercise the real map, scalar renderer, config loader and reset body.
        # Only mokutil and its EFI files are fixtures; no password resolver stub
        # or inherited ACCOUNT_USERNAME can hide a missing template field.
        seed = TARGET.parents[1]
        grub = (seed / 'scripts/late/grub.sh').read_text()
        mapping = function(grub, 'secure_boot_config_placeholder_map')
        definitions = mapping
        for relative, names in (
            ('scripts/common/target.sh', ('shell_single_quote', 'write_shell_config_var')),
            ('scripts/common/modules/files-logging.sh',
             ('installer_escape_sed_replacement', 'installer_apply_scalar_placeholders')),
            ('scripts/late/target-assets.sh', ('apply_placeholder_map_to_target',)),
        ):
            source = (seed / relative).read_text()
            definitions += ''.join(function(source, name) for name in names)
        values = {name: 'fixture-value' for name in
                  re.findall(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)', mapping)}
        values.pop('ACCOUNT_USERNAME')
        values['secure_boot_state_mode'] = 'direct'
        with tempfile.TemporaryDirectory(prefix='mok-config-') as temporary:
            root = Path(temporary)
            config = root / 'secure-boot.conf'
            config.write_bytes((TARGET / 'etc/secure-boot.conf.tmpl').read_bytes())
            config.chmod(0o600)
            program = (definitions + '\ninstaller_fatal() { exit 1; }\n'
                       'ACCOUNT_USERNAME=fixture-user\nTMP_ENV_DIR=$1\n'
                       'apply_placeholder_map_to_target "$2" secure_boot_config_placeholder_map\n')
            rendered = subprocess.run(['/bin/dash', '-eu', '-c', program, 'render-mok',
                                       str(root), str(config)], env={**ENV, **values},
                                      capture_output=True, text=True, timeout=5)
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            self.assertNotIn('__INSTALLER_', config.read_text())
            self.assertIn("ACCOUNT_USERNAME='fixture-user'\n", config.read_text())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            variables = root / 'efivars'
            variables.mkdir()
            calls = root / 'calls'
            mock_bin = root / 'bin'
            mock_bin.mkdir()
            mokutil = mock_bin / 'mokutil'
            mokutil.write_text(
                '#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n'
                f'calls = Path({str(calls)!r})\n'
                'with calls.open("a") as stream:\n'
                '    stream.write(" ".join(sys.argv[1:]) + "\\n")\n'
                'if sys.argv[1:] == ["--reset"]:\n'
                '    assert sys.stdin.buffer.read(1024) == b"fixture-user\\nfixture-user\\n"\n'
                f'    Path({str(variables / "MokAuth-605dab50-e046-4300-abb6-3dd810dd8b23")!r}).write_bytes(bytes(176))\n'
                'else:\n    assert sys.argv[1:] == ["--timeout", "900"]\n')
            mokutil.chmod(0o700)
            source = (TARGET / 'usr/libexec/install-tools/secure-boot-tool.tmpl').read_text()
            source = source.replace('PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                                    'PATH=' + shlex.quote(str(mock_bin) + ':/usr/bin:/bin'))
            source = source.replace('/sys/firmware/efi/efivars', str(variables))
            helper = root / 'secure-boot-tool'
            helper.write_text(source)
            environment = {**ENV, 'SECURE_BOOT_CONFIG_PATH': str(config)}
            self.assertNotIn('ACCOUNT_USERNAME', environment)
            valid_config = config.read_text()
            config.write_text(valid_config.replace("ACCOUNT_USERNAME='fixture-user'\n", ''))
            missing = subprocess.run(['/bin/dash', str(helper), 'reset-preflight'], env=environment,
                                     capture_output=True, text=True, timeout=5)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('ACCOUNT_USERNAME must not be empty', missing.stderr)
            self.assertFalse(calls.exists())
            self.assertEqual(list(variables.iterdir()), [])
            missing_reset = subprocess.run(['/bin/dash', str(helper), 'reset-moks'], env=environment,
                                           capture_output=True, text=True, timeout=5)
            self.assertNotEqual(missing_reset.returncode, 0)
            self.assertIn('MOK reset password is unavailable', missing_reset.stderr)
            self.assertFalse(calls.exists())
            self.assertEqual(list(variables.iterdir()), [])
            config.write_text(valid_config)
            for command, output in (('reset-preflight', ''), ('reset-moks', 'queued\n')):
                result = subprocess.run(['/bin/dash', str(helper), command], env=environment,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, output)
                self.assertNotIn('fixture-user', result.stdout + result.stderr)
                if command == 'reset-preflight':
                    self.assertFalse(calls.exists())
                    self.assertEqual(list(variables.iterdir()), [])
            self.assertEqual(calls.read_text().splitlines(), ['--reset', '--timeout 900'])

    def reset(self, failure='none'):
        source = read_text(TARGET / 'usr/libexec/install-tools/secure-boot-tool')
        start = source.index('reset_mok_state() (\n')
        body = source[start:source.index('\n)\n', start) + 3]
        with tempfile.TemporaryDirectory(prefix='mok-reset-') as temporary:
            calls = Path(temporary) / 'calls'
            stubs = r'''
require_command() { [ "$FAILURE" != missing ] || fatal 'missing command'; }
resolve_mok_delete_password() {
  [ "$FAILURE" != password ] || return 97
  printf '%s\n' 'fixture-password'
}
mok_reset_request_is_pending() { [ "$FAILURE" != pending ]; }
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
    --reset)
      [ "$#" -eq 1 ] || return 92
      IFS= read -r first && IFS= read -r second || return 93
      [ "$first" = fixture-password ] && [ "$second" = "$first" ] || return 94
      case "$FAILURE" in reset) return 74 ;; reset-timeout) return 124 ;; reset-killed) return 137 ;; esac
      return 0
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
                                    env={**ENV, 'CALLS': str(calls), 'FAILURE': failure},
                                    capture_output=True, text=True, timeout=5)
            self.assertNotIn('fixture-password', result.stdout + result.stderr)
            return result, calls.read_text().splitlines() if calls.exists() else []

    def test_full_reset_never_queries_or_depends_on_the_inventory(self):
        result, calls = self.reset()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['--reset', '--timeout 900'])
        self.assertIn('confirm the reset in MokManager', result.stderr)
        self.assertEqual(result.stdout, 'queued\n')

    def test_failed_request_is_not_retried_or_reported_as_queued(self):
        for failure in ('reset', 'reset-timeout', 'reset-killed', 'pending'):
            with self.subTest(failure=failure):
                result, calls = self.reset(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, ['--reset'])
                self.assertIn('may already be pending', result.stderr)
                self.assertNotIn('full MOK reset queued', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_missing_command_or_password_never_claims_a_queued_reset(self):
        for failure, expected in [('missing', []), ('password', [])]:
            with self.subTest(failure=failure):
                result, calls = self.reset(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, expected)
                self.assertEqual(result.stdout, '')

    def test_timeout_adjustment_failure_keeps_successful_reset_result(self):
        result, calls = self.reset('timeout')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['--reset', '--timeout 900'])
        self.assertIn('timeout could not be set', result.stderr)

    def test_pending_reset_requires_authentication_and_no_new_enrollment(self):
        source = read_text(TARGET / 'usr/libexec/install-tools/secure-boot-tool')
        start = source.index('mok_reset_request_is_pending() (\n')
        body = source[start:source.index('\n)\n', start) + 3]
        guid = '605dab50-e046-4300-abb6-3dd810dd8b23'
        for mode in ('pending', 'legacy', 'absent', 'empty-auth', 'truncated-auth',
                     'oversized-auth', 'replacement', 'auth-link', 'new-link'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                auth, new = root / ('MokAuth-' + guid), root / ('MokNew-' + guid)
                if mode != 'absent':
                    size = {'legacy': 36, 'empty-auth': 0, 'truncated-auth': 175,
                            'oversized-auth': 177}.get(mode, 176)
                    auth.write_bytes(bytes(size))
                if mode == 'replacement':
                    new.write_bytes(b'fixture-new')
                if mode == 'auth-link':
                    auth.rename(root / 'saved-auth')
                    auth.symlink_to(root / 'saved-auth')
                if mode == 'new-link':
                    new.symlink_to(root / 'absent')
                program = body.replace('/sys/firmware/efi/efivars', temporary)
                result = subprocess.run(['/bin/dash', '-eu', '-c', program +
                                         '\nmok_reset_request_is_pending'],
                                        env=ENV, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0 if mode in ('pending', 'legacy') else 1, result.stderr)

    def test_reset_and_management_queue_exits_do_not_abort_preparation(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        stage = function(source, 'stage_target_secure_boot_runtime_assets')
        queue = function(source, 'queue_target_grub_mok_enrollment_boot_for_reset')
        for failure in ('return 37', 'exit 37'):
            with self.subTest(failure=failure):
                stubs = r'''
ensure_target_secure_boot_state_mount() { :; }
write_target_secure_boot_payloads() { :; }
remove_target_secure_boot_crypttab_entry() { printf 'crypttab\n'; }
install_target_secure_boot_kernel_hooks() { printf 'kernel-hooks\n'; }
ensure_target_grub_profile_mounts() { :; }
require_target_grub_installed() { :; }
repair_target_secure_boot_nvram_entry() { :; }
run_installer_secure_boot_install_tool() { :; }
installer_warn() { printf '%s\n' "$*" >&2; }
installer_info() { printf '%s\n' "$*" >&2; }
''' + ('reset_target_secure_boot_mok_state() { ' + failure + '; }\n' +
       'repair_target_secure_boot_nvram_entry() { ' + failure + '; }\n' +
       'queue_target_grub_mok_enrollment_boot() { ' + failure + '; }\n')
                result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + stage + queue +
                                         '\nstage_target_secure_boot_runtime_assets\n'
                                         'queue_target_grub_mok_enrollment_boot_for_reset\n'
                                         "printf 'installation-continued\\n'"],
                                        env=ENV, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'crypttab\nkernel-hooks\ninstallation-continued\n')
                self.assertNotIn('continuing Secure Boot key preparation', result.stderr)
                self.assertIn('select MOK Enrollment manually', result.stderr)

    def test_successful_reset_is_not_repeated_by_a_later_installer_process(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        body = function(source, 'reset_target_secure_boot_mok_state')
        stubs = r'''
installer_lifecycle_paths() { :; }
installer_runtime_state_dir() { printf '%s\n' "$FIXTURE_ROOT"; }
installer_metadata_value() { printf '0:0:600:1\n'; }
installer_warn() { printf '%s\n' "$*" >&2; }
prepare_target_secure_boot_mok_reset() { :; }
reset_target_secure_boot_mok_state_attempt() {
  printf 'attempt\n' >>"$FIXTURE_ROOT/calls"
  printf 'queued\n'
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            for _ in range(2):
                result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body +
                                         '\nreset_target_secure_boot_mok_state'],
                                        env={**ENV, 'FIXTURE_ROOT': temporary},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((Path(temporary) / 'calls').read_text(), 'attempt\n')
            self.assertEqual((Path(temporary) / 'secure-boot-mok-reset.state').read_text(), 'queued\n')

    def test_failed_preflight_leaves_no_attempt_and_can_be_corrected(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        body = function(source, 'reset_target_secure_boot_mok_state')
        for failure in ('return 37', 'exit 37'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                stubs = r'''
installer_lifecycle_paths() { :; }
installer_runtime_state_dir() { printf '%s\n' "$FIXTURE_ROOT"; }
installer_metadata_value() { printf '0:0:600:1\n'; }
installer_warn() { printf '%s\n' "$*" >&2; }
reset_target_secure_boot_mok_state_attempt() {
  printf 'attempt\n' >>"$FIXTURE_ROOT/calls"
  printf 'queued\n'
}
'''
                prepare = 'prepare_target_secure_boot_mok_reset() { ' + failure + '; }\n'
                failed = subprocess.run(['/bin/dash', '-eu', '-c', stubs + prepare + body +
                                         '\nreset_target_secure_boot_mok_state'],
                                        env={**ENV, 'FIXTURE_ROOT': temporary},
                                        capture_output=True, text=True, timeout=5)
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn('no firmware reset was attempted', failed.stderr)
                self.assertFalse((root / 'secure-boot-mok-reset.state').exists())
                self.assertFalse((root / 'calls').exists())
                prepare = 'prepare_target_secure_boot_mok_reset() { :; }\n'
                corrected = subprocess.run(['/bin/dash', '-eu', '-c', stubs + prepare + body +
                                            '\nreset_target_secure_boot_mok_state'],
                                           env={**ENV, 'FIXTURE_ROOT': temporary},
                                           capture_output=True, text=True, timeout=5)
                self.assertEqual(corrected.returncode, 0, corrected.stderr)
                self.assertEqual((root / 'calls').read_text(), 'attempt\n')
                self.assertEqual((root / 'secure-boot-mok-reset.state').read_text(), 'queued\n')

    def test_another_process_claiming_during_preflight_cannot_be_overwritten(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        body = function(source, 'reset_target_secure_boot_mok_state')
        stubs = r'''
installer_lifecycle_paths() { :; }
installer_runtime_state_dir() { printf '%s\n' "$FIXTURE_ROOT"; }
installer_warn() { printf '%s\n' "$*" >&2; }
prepare_target_secure_boot_mok_reset() {
  (umask 077; printf 'unknown\n' >"$FIXTURE_ROOT/secure-boot-mok-reset.state")
}
reset_target_secure_boot_mok_state_attempt() { printf unexpected >"$FIXTURE_ROOT/calls"; }
'''
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body +
                                     '\nreset_target_secure_boot_mok_state'],
                                    env={**ENV, 'FIXTURE_ROOT': temporary},
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(temporary) / 'calls').exists())
            self.assertEqual((Path(temporary) / 'secure-boot-mok-reset.state').read_text(), 'unknown\n')

    def test_changed_pending_request_blocks_automatic_queue_but_installation_continues(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        body = function(source, 'queue_target_grub_mok_enrollment_boot_for_reset')
        stubs = r'''
run_installer_secure_boot_install_tool() { [ "$1" = reset-pending ] || exit 91; return 1; }
queue_target_grub_mok_enrollment_boot() { printf 'unexpected grub mutation\n'; exit 92; }
repair_target_secure_boot_nvram_entry() { printf 'unexpected firmware mutation\n'; exit 93; }
installer_warn() { printf '%s\n' "$*" >&2; }
installer_info() { printf '%s\n' "$*" >&2; }
'''
        result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body +
                                 '\nqueue_target_grub_mok_enrollment_boot_for_reset\n'
                                 "printf 'installation-continued\\n'"],
                                env=ENV, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'installation-continued\n')
        self.assertIn('select MOK Enrollment manually', result.stderr)

    def test_bridge_preflight_failure_never_records_a_mandatory_install_failure(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        start = source.index('prepare_target_secure_boot_mok_reset() (\n')
        body = source[start:source.index('\n)\n', start) + 3]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            system = root / 'installer-system'
            (system / 'firmware/efi/efivars').mkdir(parents=True)
            target_system = root / 'target-system'
            target_system.mkdir()
            body = body.replace('/target/sys', str(target_system)).replace('/sys', str(system))
            stubs = r'''
installer_fatal() { : >"$FIXTURE_ROOT/first-failure"; exit 31; }
installer_warn() { printf '%s\n' "$*" >&2; }
installer_error() { printf '%s\n' "$*" >&2; }
installer_info() { :; }
install() { :; }
mount() { :; }
target_mount_source() { return 0; }
target_efivars_are_available() { return 0; }
run_installer_secure_boot_install_tool() { installer_fatal 'fixture bridge preflight failure'; }
'''
            result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body +
                                     '\nif prepare_target_secure_boot_mok_reset; then exit 99; fi\n'
                                     "printf 'installation-continued\\n'"],
                                    env={**ENV, 'FIXTURE_ROOT': temporary},
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'installation-continued\n')
            self.assertIn('fixture bridge preflight failure', result.stderr)
            self.assertFalse((root / 'first-failure').exists())

    def test_shim_boot_entry_selection_requires_the_selected_esp_and_active_entry(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        selector = function(source, 'find_shim_boot_entry')
        selected_uuid = '12345678-1234-1234-1234-123456789abc'
        other_uuid = '87654321-1234-1234-1234-123456789abc'
        entries = [
            f'Boot0001* debian HD(1,GPT,{other_uuid},0x800,0x100)/File(\\EFI\\debian\\shimx64.efi)',
            f'Boot0002  debian HD(1,GPT,{selected_uuid},0x800,0x100)/File(\\EFI\\debian\\shimx64.efi)',
            f'Boot0003* debian HD(2,GPT,{selected_uuid},0x800,0x100)/File(\\EFI\\debian\\shimx64.efi)',
            f'Boot0004* debian HD(1,GPT,{selected_uuid},0x800,0x100)/File(\\EFI\\debian\\grubx64.efi)',
            f'Boot0005* debian HD(1,GPT,{selected_uuid},0x800,0x100)/File(\\EFI\\debian\\shimx64.efi)',
        ]
        for listing, expected in [('\n'.join(entries), '0005\n'), ('\n'.join(entries[:-1]), '')]:
            with self.subTest(expected=expected):
                program = selector + '\npart_num=1\npart_uuid=' + shlex.quote(selected_uuid) + '\n'
                program += 'find_shim_boot_entry ' + shlex.quote(r'\efi\debian\shimx64.efi')
                result = subprocess.run(['/bin/dash', '-eu', '-c', program], input=listing + '\n',
                                        env=ENV, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)

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
                         'prepare_target_secure_boot_mok_reset() { :; }\n'
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
        for state, mode, expected in [('empty\n', 0o600, 1), ('queued\n', 0o600, 0),
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

    def test_reset_runs_immediately_after_grub_in_both_storage_families(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        stage = function(source, 'stage_target_secure_boot_runtime_assets')
        self.assertNotIn('reset_target_secure_boot_mok_state', stage)
        prepkgsel = read_text(TARGET.parent / 'installer/pre-pkgsel.d/90secure-boot-dkms.sh')
        self.assertNotIn('ensure_target_mok_inventory_command', prepkgsel)
        self.assertLess(prepkgsel.index('stage_target_secure_boot_runtime_assets'),
                        prepkgsel.index('run_installer_secure_boot_install_tool prepare-dkms'))
        late = TARGET.parents[1] / 'scripts/late'
        for family in ('btrfs-family.sh', 'f2fs-family.sh'):
            caller = read_text(late / family)
            self.assertEqual(caller.count('if (finalize_target_secure_boot_mok_reset)'), 1)
            self.assertLess(caller.index('\n  run_target_grub_config_update\n'),
                            caller.index('if (finalize_target_secure_boot_mok_reset)'))
            self.assertLess(caller.index('if (finalize_target_secure_boot_mok_reset)'),
                            caller.index('\n  sync_target_secure_boot_bundle_to_installer_usb\n'))
        role = read_text(late / 'desktop.sh')
        self.assertNotIn('finalize_target_secure_boot_mok_reset', role)
        dispatch = read_text(late / 'dispatch.sh')
        self.assertLess(dispatch.index('\nrun_selected_class_helpers\n'),
                        dispatch.index('"$role_hook_dest" "$seed_base" "$host_profile"'))

    def test_only_firmware_handoff_is_automatic_including_uncertain_failure(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        body = function(source, 'queue_target_grub_mok_enrollment_boot_for_reset')
        stubs = r'''
run_installer_secure_boot_install_tool() { [ "$1" = reset-pending ]; }
repair_target_secure_boot_nvram_entry() { printf 'firmware\n'; [ "$FIRMWARE" = success ]; }
queue_target_grub_mok_enrollment_boot() { printf 'unexpected second handoff\n'; exit 92; }
installer_warn() { printf '%s\n' "$*" >&2; }
installer_info() { printf '%s\n' "$*" >&2; }
'''
        for firmware in ('success', 'failed'):
            with self.subTest(firmware=firmware):
                result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body +
                                         '\nqueue_target_grub_mok_enrollment_boot_for_reset\n'
                                         "printf 'installation-continued\\n'"],
                                        env={**ENV, 'FIRMWARE': firmware},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'firmware\ninstallation-continued\n')
                if firmware == 'failed':
                    self.assertIn('select MOK Enrollment manually', result.stderr)
                else:
                    self.assertIn('MOK management boot queued', result.stderr)

    def test_final_reset_preflight_exit_does_not_record_mandatory_failure(self):
        source = read_text(TARGET.parents[1] / 'scripts/late/grub.sh')
        start = source.index('finalize_target_secure_boot_mok_reset() (\n')
        body = source[start:source.index('\n)\n', start) + 3]
        stubs = r'''
installer_fatal() { : >"$FIXTURE_ROOT/first-failure"; exit 73; }
installer_warn() { printf '%s\n' "$*" >&2; }
late_command_load_runtime_env() { installer_fatal 'fixture final preflight failure'; }
'''
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(['/bin/dash', '-eu', '-c', stubs + body +
                                     '\nif (finalize_target_secure_boot_mok_reset); then exit 99; fi\n'
                                     "printf 'installation-continued\\n'"],
                                    env={**ENV, 'FIXTURE_ROOT': temporary},
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'installation-continued\n')
            self.assertFalse((Path(temporary) / 'first-failure').exists())

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
