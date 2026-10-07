"""IOCost literal policy, native rendering, isolated hwdb and rollback tests.

Only disposable roots are changed. No calibration, cgroup write or uevent runs.
"""
from payload_fixture import copyfile as payload_module_copyfile, installed_script
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from test_hardware_restore import copy_binary
from test_metadata_portability_20260919 import minimal_installer_bin

FORKY = Path(__file__).resolve().parents[1]
HELPER = FORKY / 'scripts/late/iocost.sh'
ASSETS = ('etc/udev/iocost.conf',
          'etc/udev/iocost.conf.d/70-unattended-installer.conf',
          'etc/udev/hwdb.d/70-unattended-installer-iocost.hwdb')
COMPAT = 'etc/udev/iocost.conf'
SAVED = COMPAT + '.unattended-installer-original'
SAVED_MARKER = b'# Managed by unattended-installer: IOCost native defaults backup.\n'
STOCK_NATIVE = FORKY / 'tests/fixtures/iocost/udev-257-iocost.conf'
# Some sandbox environments deny proc mounts. Native systemd needs /proc when
# replacing an O_TMPFILE-backed database inside a chroot. These rerun fixtures
# use the identical executable with its supported --root interface instead;
# first-install tests still exercise the production target executor/chroot.
ROOT_TOOL = r'''
target_exec() {
  [ "$1" = /usr/bin/systemd-hwdb ] || return 1
  shift
  case "$1" in --root=/*) fixture_root=${1#--root=}; shift ;; *) return 1 ;; esac
  /usr/bin/systemd-hwdb --root="${iocost_root}${fixture_root}" "$@"
}
'''


def profile(name='btrfs-de-flex'):
    pairs = re.findall(r'^(IOCOST_[A-Z0-9_]+)="([^"\n]*)"$',
                       payload_read_text(FORKY / 'hosts/profiles' / (name + '.env')), re.M)
    if len(pairs) != len(dict(pairs)):
        raise ValueError('duplicate IOCost profile field')
    return dict(pairs)


class IOCostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='iocost-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target = self.base / 'target'; self.target.mkdir()
        self.original_native = None
        self.env = {'PATH': minimal_installer_bin(self.base / 'installer-bin'), 'LC_ALL': 'C',
                    'INSTALLER_SOURCE_LIBRARY': str(FORKY / 'scripts/common/source.sh'),
                    'INSTALLER_TARGET_DIR': str(self.target), 'DIR_HOOKS_TARGET': 'hooks/target',
                    'INSTALLER_SOURCE_ROOT': str(FORKY), 'FIXTURE_SOURCE': str(FORKY)}
        if os.geteuid() == 0:
            os.chown(self.target, 0, 0)
        self.code = '\n'.join('. ' + shlex.quote(str(installed_script(FORKY / name))) for name in
                              ('scripts/common/lib.sh', 'scripts/common/target.sh',
                               'scripts/late/target-assets.sh', 'scripts/late/iocost.sh'))
        self.code += '\nfetch_hook() { cp -- "$FIXTURE_SOURCE/$1" "$2"; }\n'

    def native(self, with_defaults=True):
        if os.geteuid() != 0 or not Path('/usr/bin/systemd-hwdb').is_file():
            self.skipTest('native target hwdb fixture requires root and systemd-hwdb')
        copy_binary(self.target, '/usr/bin/systemd-hwdb')
        copy_binary(self.target, '/usr/bin/env')
        self.assertEqual(payload_read_bytes(self.target / 'usr/bin/systemd-hwdb'), payload_read_bytes(Path('/usr/bin/systemd-hwdb')))
        copy_binary(self.target, '/usr/lib/udev/iocost')
        for path in self.target.rglob('*'):
            os.chown(path, 0, 0)
        vendor = self.target / 'usr/lib/udev/hwdb.d/60-fixture.hwdb'
        vendor.parent.mkdir(parents=True)
        vendor.write_text('fixture:vendor\n VENDOR_PRESERVED=yes\n')
        if with_defaults:
            # A real Debian udev installation includes this conffile. Omitting
            # it from the old chroot fixture hid the fresh-install regression.
            native = self.target / COMPAT
            native.parent.mkdir(parents=True, exist_ok=True)
            self.original_native = payload_read_bytes(STOCK_NATIVE)
            native.write_bytes(self.original_native)
            native.chmod(0o644)

    def run_policy(self, values=None, before='', enabled=True, timeout=30):
        env = dict(self.env, **(profile() if values is None else values))
        command = self.code + before + ('\nstage_target_iocost\n' if enabled else '\niocost_placeholder_map\n')
        return subprocess.run(['/bin/sh', '-eu', '-c', command], env=env, text=True,
                              capture_output=True, timeout=timeout)

    def assert_absent(self):
        for relative in (*ASSETS[1:], SAVED):
            self.assertFalse(os.path.lexists(self.target / relative), relative)
        native = self.target / COMPAT
        if self.original_native is None:
            self.assertFalse(os.path.lexists(native), COMPAT)
        else:
            self.assertFalse(native.is_symlink())
            self.assertEqual(payload_read_bytes(native), self.original_native)
            self.assertEqual(native.stat().st_mode & 0o7777, 0o644)
        self.assertFalse(list(self.target.glob('.installer-iocost*')))

    def test_all_profiles_complete_and_exact_enable_matrix(self):
        enabled = []
        profiles = sorted((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            values = profile(path.stem)
            self.assertEqual(len(values), 113)
            result = self.run_policy(values, enabled=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(result.stdout.splitlines()), 113)
            if values['IOCOST_CALIBRATE_ENABLE'] == 'true': enabled.append(path.name)
        # The supplied dual-disk profile already opts out of calibration.
        # Preserve that policy; only the single-disk profile is enabled.
        self.assertEqual(enabled, ['btrfs-de-flex.env'])
        self.assertEqual(len(profiles) - len(enabled), 9)

    def test_complete_policy_survives_trusted_composite_profile_loading(self):
        from test_repository_integrity import records
        overrides = {row['Name'] for row in records() if row['Group'] == 'profile'}
        for path in sorted((FORKY / 'hosts/profiles').glob('*.env')):
            name = path.stem
            with self.subTest(profile=name):
                logical = ('override-' if name in overrides else '') + name
                composed = self.base / (name + '-composite.env')
                env = dict(self.env, INSTALLER_RUNTIME_DIR=str(self.base / 'runtime'), INSTALLER_CMDLINE='')
                command = self.code + '\n'.join((
                    'installer_ensure_repo_env "$INSTALLER_SOURCE_ROOT"',
                    'installer_classes_cache_ensure',
                    'installer_fetch_host_env "$INSTALLER_SOURCE_ROOT" ' + shlex.quote(logical) + ' ' + shlex.quote(str(composed)),
                    '. ' + shlex.quote(str(composed)),
                    'iocost_placeholder_map'))
                result = subprocess.run(['/bin/sh', '-eu', '-c', command], env=env, text=True,
                                        capture_output=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = self.run_policy(profile(name), enabled=False)
                self.assertEqual(expected.returncode, 0, expected.stderr)
                self.assertEqual(result.stdout, expected.stdout)
                self.assertEqual(len(result.stdout.splitlines()), 113)

    def test_enabled_then_disabled_profile_staging_and_cleanup(self):
        self.native()
        for name in ('btrfs-de-flex', 'btrfs-de-flex-duo'):
            with self.subTest(profile=name):
                result = self.run_policy(profile(name), before=ROOT_TOOL if name.endswith('-duo') else '')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if profile(name)["IOCOST_CALIBRATE_ENABLE"] == "false":
                    self.assert_absent()
                    continue
                for relative in ASSETS:
                    path = self.target / relative
                    self.assertTrue(path.is_file())
                    self.assertNotIn('__INSTALLER_', payload_read_text(path))
                    self.assertEqual(path.stat().st_mode & 0o777, 0o644)
                    self.assertEqual((path.stat().st_uid, path.stat().st_gid), (0, 0))
                self.assertFalse(list(self.target.rglob('*.tmpl')))
                self.assertFalse((self.target / COMPAT).is_symlink())
                self.assertEqual(payload_read_text(self.target / ASSETS[0]).count('TargetSolution=naive'), 1)
                self.assertIn('TargetSolution=naive', payload_read_text(self.target / ASSETS[1]))
                self.assertIn('block::name:KXG6AZNV512G TOSHIBA:fwrev:*:', payload_read_text(self.target / ASSETS[2]))
                saved = self.target / SAVED
                self.assertEqual(payload_read_bytes(saved), SAVED_MARKER + self.original_native)
                self.assertEqual(saved.stat().st_mode & 0o7777, 0o644)
                self.assertEqual((saved.stat().st_uid, saved.stat().st_gid), (0, 0))

    def test_real_installer_and_target_chroots_have_no_metadata_executable(self):
        if os.geteuid() != 0 or not Path('/usr/bin/systemd-hwdb').is_file():
            self.skipTest('two-level chroot fixture requires root and systemd-hwdb')
        outer = self.base / 'installer-root'
        outer.mkdir(mode=0o755)
        copy_binary(outer, shutil.which('busybox'), '/bin/busybox')
        for link in (self.base / 'installer-bin').iterdir():
            (outer / 'bin' / link.name).symlink_to('busybox')
        (outer / 'bin/sh').symlink_to('busybox')
        for directory in ('tmp', 'dev', 'target', 'repo'):
            (outer / directory).mkdir()
        (outer / 'tmp').chmod(0o1777)
        (outer / 'dev/null').touch()
        sources = ('repo.env', 'scripts/common/lib.sh', 'scripts/common/source.sh',
                   'scripts/common/target.sh', 'scripts/late/target-assets.sh',
                   'scripts/late/iocost.sh')
        sources += tuple('hooks/target/' + name + '.tmpl' for name in ASSETS)
        for name in sources:
            destination = outer / 'repo' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload_module_copyfile(FORKY / name, destination)
        for binary in ('/usr/bin/systemd-hwdb', '/usr/bin/env', '/usr/lib/udev/iocost'):
            copy_binary(outer / 'target', binary)
        native = outer / 'target' / COMPAT
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_bytes(payload_read_bytes(STOCK_NATIVE))
        native.chmod(0o644)
        credentials = outer / 'preseed.env'
        credentials.write_text('PRESEED_PRIMARY_USERNAME="fixture-user"\n')
        credentials.chmod(0o600)
        env = dict(profile(), PATH='/bin', LC_ALL='C', INSTALLER_SOURCE_ROOT='/repo',
                   INSTALLER_SOURCE_LIBRARY='/repo/scripts/common/source.sh',
                   INSTALLER_TARGET_DIR='/target', DIR_HOOKS_TARGET='hooks/target')
        code = r'''
! command -v stat
[ ! -e /usr/bin/stat ] && [ ! -e /target/usr/bin/stat ] && [ ! -e /target/bin/stat ]
. /repo/scripts/common/lib.sh
. /repo/scripts/common/target.sh
. /repo/scripts/late/target-assets.sh
. /repo/scripts/late/iocost.sh
fetch_hook() { cp -- "/repo/$1" "$2"; }
[ "$(preseed_env_read_value primary_user)" = fixture-user ]
stage_target_iocost
'''
        result = subprocess.run([shutil.which('chroot'), str(outer), '/bin/sh', '-eu', '-c', code],
                                env=env, text=True, capture_output=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        for relative in ASSETS:
            published = outer / 'target' / relative
            self.assertTrue(published.is_file())
            self.assertEqual(published.stat().st_mode & 0o7777, 0o644)
            self.assertNotIn('__INSTALLER_', payload_read_text(published))
        self.assertTrue((outer / 'target/etc/udev/hwdb.bin').is_file())
        self.assertFalse((outer / 'target' / COMPAT).is_symlink())
        self.assertEqual(payload_read_bytes(outer / 'target' / SAVED),
                         SAVED_MARKER + payload_read_bytes(STOCK_NATIVE))

    def test_disabled_btrfs_f2fs_create_no_files_or_database(self):
        for name in ('btrfs-de', 'f2fs-de-x360'):
            result = self.run_policy(profile(name))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_absent()
            self.assertFalse((self.target / 'etc/udev/hwdb.bin').exists())

    def invalid(self, changes=None, missing=None):
        values = profile(); values.update(changes or {})
        if missing: del values[missing]
        result = self.run_policy(values)
        self.assertNotEqual(result.returncode, 0)
        self.assert_absent()

    def test_boolean_is_canonical(self):
        for value in ('yes', '1', 'TRUE', 'enabled', ''):
            with self.subTest(value=value): self.invalid({'IOCOST_CALIBRATE_ENABLE': value})

    def test_missing_model_fails_before_publication(self):
        self.invalid(missing='IOCOST_MODEL_NAIVE_RBPS')

    def test_missing_qos_fails_before_publication(self):
        self.invalid(missing='IOCOST_QOS_NAIVE_RLAT')

    def test_target_must_be_listed(self):
        self.invalid({'IOCOST_TARGET_SOLUTION': 'typo'})
        self.invalid({'IOCOST_TARGET_SOLUTION': 'isolated-bandwidth'})

    def test_solution_duplicates_and_injection_rejected(self):
        for value in ('naive naive', 'naive;id', 'naive  isolated-bandwidth', 'naive\nisolated-bandwidth'):
            with self.subTest(value=value): self.invalid({'IOCOST_SOLUTIONS': value})

    def test_numeric_formats_and_bounds(self):
        for key, bad in (('IOCOST_MODEL_NAIVE_RBPS', '-1'), ('IOCOST_MODEL_NAIVE_RBPS', '1e9'),
                         ('IOCOST_MODEL_NAIVE_RBPS', '1000000000001'), ('IOCOST_MODEL_NAIVE_RBPS', '0'),
                         ('IOCOST_QOS_NAIVE_RPCT', '101'), ('IOCOST_QOS_NAIVE_RLAT', '0'),
                         ('IOCOST_QOS_NAIVE_MIN', '1.234'), ('IOCOST_QOS_NAIVE_MAX', '10001')):
            with self.subTest(key=key, bad=bad): self.invalid({key: bad})

    def test_minimum_cannot_exceed_maximum(self):
        self.invalid({'IOCOST_QOS_NAIVE_MIN': '100.01'})

    def test_newline_property_injection_rejected(self):
        self.invalid({'IOCOST_DEVICE_FWREV_MATCH': '*\n IOCOST_SOLUTIONS=naive'})
        self.invalid({'IOCOST_MODEL_NAIVE_RBPS': '1\nIOCOST_MODEL_NAIVE_RBPS=2'})

    def test_unsafe_and_broad_model_patterns_rejected(self):
        for value in ('*', 'NVMe*', 'KXG6*', 'KXG6AZNV512G:fwrev:*', ' KXG6AZNV512G',
                      'KXG6AZNV512G[0-9]', 'KXG6AZNV512G=bad', 'KXG6AZNV512G\r', 'A'*129):
            with self.subTest(value=value): self.invalid({'IOCOST_DEVICE_MODEL_MATCH': value})

    def test_misspelled_boolean_is_rejected(self):
        for key in ('IOCOST_CALIBRATED_ENABLE', 'IOCOST_CALIBRATE_ENABLED', 'IO_COST_CALIBRATE_ENABLE'):
            self.invalid({key: 'true'})

    def test_disabled_values_are_still_validated(self):
        self.invalid({'IOCOST_CALIBRATE_ENABLE': 'false', 'IOCOST_MODEL_NAIVE_RBPS': 'garbage'})

    def test_unresolved_template_fails_without_publication(self):
        self.native()
        before = '''
fetch_hook() {
  cp -- "$FIXTURE_SOURCE/$1" "$2"
  case "$1" in *.hwdb.tmpl) printf '%s\\n' '__INSTALLER_IOCOST_MISSING__' >>"$2" ;; esac
}
'''
        result = self.run_policy(before=before)
        self.assertNotEqual(result.returncode, 0)
        self.assert_absent()

    def test_true_to_false_removes_only_owned_files_and_rebuilds(self):
        self.native()
        result = self.run_policy(); self.assertEqual(result.returncode, 0, result.stderr)
        admin = self.target / 'etc/udev/hwdb.d/99-admin.hwdb'
        admin.write_text('fixture:admin\n ADMIN_PRESERVED=yes\n')
        result = self.run_policy(profile('f2fs-de-x360'), before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_absent(); self.assertTrue(admin.is_file())
        query = subprocess.run(['chroot', str(self.target), '/usr/bin/systemd-hwdb', 'query', 'fixture:vendor'], capture_output=True, text=True)
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertIn('VENDOR_PRESERVED=yes', query.stdout)
        query = subprocess.run(['chroot', str(self.target), '/usr/bin/systemd-hwdb', 'query', 'block::name:KXG6AZNV512G TOSHIBA:fwrev:5108AGLA:'], capture_output=True, text=True)
        self.assertNotIn('IOCOST_', query.stdout)

    def test_administrator_file_preserved_disabled_and_enabled_fails(self):
        path = self.target / ASSETS[1]; path.parent.mkdir(parents=True)
        path.write_text('[IOCost]\n# administrator\n')
        result = self.run_policy(profile('btrfs-de')); self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_policy(); self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload_read_text(path), '[IOCost]\n# administrator\n')
        self.assertFalse((self.target / ASSETS[0]).exists())

    def test_symlink_parent_cannot_escape_target(self):
        outside = self.base / 'outside'; outside.mkdir()
        (self.target / 'etc').symlink_to(outside)
        result = self.run_policy(); self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_target_hwdb_failure_rolls_back_prior_generation(self):
        self.native()
        result = self.run_policy(); self.assertEqual(result.returncode, 0, result.stderr)
        originals = {rel: payload_read_bytes(self.target / rel) for rel in (*ASSETS, 'etc/udev/hwdb.bin')}
        values = profile(); values['IOCOST_MODEL_NAIVE_RBPS'] = '999999999'
        before = '''
iocost_native_hwdb() {
  case "$1" in --root=/) return 73 ;; esac
  chroot "$iocost_root" /usr/bin/systemd-hwdb "$@"
}
'''
        result = self.run_policy(values, before)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(originals, {rel: payload_read_bytes(self.target / rel) for rel in originals})
        self.assertFalse((self.target / COMPAT).is_symlink())

    def test_first_install_hwdb_failure_removes_partial_files(self):
        self.native()
        before = '''
iocost_native_hwdb() {
  case "$1" in --root=/) return 73 ;; esac
  chroot "$iocost_root" /usr/bin/systemd-hwdb "$@"
}
'''
        result = self.run_policy(before=before)
        self.assertNotEqual(result.returncode, 0)
        self.assert_absent()
        self.assertFalse((self.target / 'etc/udev/hwdb.bin').exists())

    def test_native_default_migration_is_idempotent_and_native_parser_uses_solution(self):
        self.native()
        for run in range(2):
            result = self.run_policy(before=ROOT_TOOL if run else '')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload_read_bytes(self.target / SAVED), SAVED_MARKER + self.original_native)
        # Native parsing is observable before the intentionally nonexistent
        # device is rejected. This query never calls the apply/cgroup writer.
        result = subprocess.run(['chroot', str(self.target), '/usr/bin/env',
                                 'SYSTEMD_LOG_LEVEL=debug', 'SYSTEMD_LOG_TARGET=console',
                                 '/usr/lib/udev/iocost', 'query', '/sys/installer-nonexistent-device'],
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Target solution: naive', result.stderr)

    def test_absent_native_config_and_legacy_link_still_work(self):
        self.native(with_defaults=False)
        for run in range(2):
            result = self.run_policy(before=ROOT_TOOL if run else '')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.target / SAVED).exists())
        result = self.run_policy(profile('btrfs-de'), before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_absent()

    def test_inert_native_variants_restore_exact_bytes(self):
        self.native()
        for original in (b'', b'# site comment without a final newline',
                         b'\t; comment\n [IOCost] \n#TargetSolution=naive\n',
                         b'#' + b'x' * 65535):
            with self.subTest(bytes=len(original)):
                native = self.target / COMPAT
                native.write_bytes(original)
                native.chmod(0o644)
                self.original_native = original
                result = self.run_policy(before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(payload_read_bytes(self.target / SAVED), SAVED_MARKER + original)
                result = self.run_policy(profile('f2fs-de-x360'), before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_absent()

    def test_disabled_stock_native_file_is_untouched_without_hwdb_tools(self):
        self.native()
        before = 'target_exec() { printf "unexpected native tool call\\n" >&2; return 91; }\n'
        result = self.run_policy(profile('btrfs-de'), before=before)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_absent()
        self.assertFalse((self.target / 'etc/udev/hwdb.bin').exists())

    @unittest.skipUnless(os.geteuid() == 0, 'native configuration checks require root')
    def test_active_malformed_or_binary_native_config_fails_before_publication(self):
        native = self.target / COMPAT
        native.parent.mkdir(parents=True)
        invalid = (b'[IOCost]\nTargetSolution=naive\n',
                   b'[IOCost]\nTargetSolution=isolated-bandwidth\n',
                   b'[IOCost]\nTargetSolution=garbage\n', b'[Other]\n',
                   b'[IOCost]\n[IOCost]\n', b'# comment\x00TargetSolution=naive\n',
                   b'\x00', b'# bad\rcomment\n', b'# bad\x1bcomment\n',
                   b'[IOCost]\\\n', b'#! /bin/sh\necho unwanted\n',
                   b'#' + b'x' * 65536)
        for content in invalid:
            with self.subTest(prefix=repr(content[:80])):
                native.write_bytes(content); native.chmod(0o644)
                self.original_native = content
                result = self.run_policy()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('active settings or unsafe metadata', result.stderr)
                self.assert_absent()

    @unittest.skipUnless(os.geteuid() == 0, 'native configuration checks require root')
    def test_native_metadata_links_and_special_files_fail_closed(self):
        native = self.target / COMPAT
        native.parent.mkdir(parents=True)
        outside = self.base / 'outside-native.conf'
        outside.write_bytes(payload_read_bytes(STOCK_NATIVE)); outside.chmod(0o644)
        for kind in ('group-writable', 'private-mode', 'wrong-owner', 'wrong-group',
                     'hardlink', 'symlink', 'dangling-link', 'directory', 'fifo'):
            with self.subTest(kind=kind):
                if kind == 'hardlink': os.link(outside, native)
                elif kind == 'symlink': native.symlink_to(outside)
                elif kind == 'dangling-link': native.symlink_to('missing')
                elif kind == 'directory': native.mkdir()
                elif kind == 'fifo': os.mkfifo(native)
                else:
                    native.write_bytes(payload_read_bytes(STOCK_NATIVE)); native.chmod(0o644)
                    if kind == 'group-writable': native.chmod(0o664)
                    elif kind == 'private-mode': native.chmod(0o600)
                    elif kind == 'wrong-owner': os.chown(native, 12345, 0)
                    elif kind == 'wrong-group': os.chown(native, 0, 12345)
                before = native.lstat()
                result = self.run_policy()
                self.assertNotEqual(result.returncode, 0)
                after = native.lstat()
                self.assertEqual((before.st_mode, before.st_uid, before.st_gid, before.st_ino),
                                 (after.st_mode, after.st_uid, after.st_gid, after.st_ino))
                self.assertEqual(payload_read_bytes(outside), payload_read_bytes(STOCK_NATIVE))
                for relative in (*ASSETS[1:], SAVED):
                    self.assertFalse(os.path.lexists(self.target / relative), relative)
                if kind == 'directory': native.rmdir()
                else: native.unlink()

    def test_unmanaged_or_unsafe_native_backup_is_never_adopted(self):
        self.native()
        saved = self.target / SAVED
        for content in (payload_read_bytes(STOCK_NATIVE), SAVED_MARKER + b'[IOCost]\nTargetSolution=naive\n',
                        SAVED_MARKER + b'# bad\x00data\n'):
            saved.write_bytes(content); saved.chmod(0o644)
            result = self.run_policy()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('native-defaults backup preserved', result.stderr)
            self.assertEqual(payload_read_bytes(saved), content)
            self.assertEqual(payload_read_bytes(self.target / COMPAT), self.original_native)
            self.assertFalse(any(os.path.lexists(self.target / rel) for rel in ASSETS[1:]))
        saved.unlink()
        saved.symlink_to(self.target / COMPAT)
        result = self.run_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(saved.is_symlink())
        self.assertEqual(payload_read_bytes(self.target / COMPAT), self.original_native)

    def test_native_default_backup_and_config_publication_failures_rollback(self):
        self.native()
        before = r"""
mv() {
  command mv "$@" || return $?
  for fixture_arg do fixture_destination=$fixture_arg; done
  if [ "$fixture_destination" = "$FIXTURE_FAIL_DEST" ] && [ ! -e "$iocost_work/injected-failure" ]; then
    : >"$iocost_work/injected-failure"
    return 73
  fi
}
"""
        for relative in (SAVED, COMPAT):
            with self.subTest(destination=relative):
                self.env['FIXTURE_FAIL_DEST'] = str(self.target / relative)
                result = self.run_policy(before=before)
                self.assertNotEqual(result.returncode, 0)
                self.assert_absent()
                self.assertFalse((self.target / 'etc/udev/hwdb.bin').exists())

    def test_failed_disable_restores_native_backup_and_prior_generation(self):
        self.native()
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        originals = {rel: payload_read_bytes(self.target / rel) for rel in (*ASSETS, SAVED, 'etc/udev/hwdb.bin')}
        before = '''
iocost_native_hwdb() {
  case "$1" in --root=/) return 73 ;; esac
  chroot "$iocost_root" /usr/bin/systemd-hwdb "$@"
}
'''
        result = self.run_policy(profile('f2fs-de-x360'), before=before)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(originals, {rel: payload_read_bytes(self.target / rel) for rel in originals})
        self.assertFalse((self.target / COMPAT).is_symlink())
        self.assertFalse(list(self.target.glob('.installer-iocost*')))

    def test_disable_recovers_missing_link_or_already_restored_defaults(self):
        self.native()
        for state in ('missing', 'already-restored'):
            with self.subTest(state=state):
                result = self.run_policy(before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                native = self.target / COMPAT
                native.unlink()
                if state == 'already-restored':
                    native.write_bytes(self.original_native); native.chmod(0o644)
                result = self.run_policy(profile('f2fs-de-x360'), before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_absent()

    def test_disabled_administrator_replacement_keeps_policy_and_backup(self):
        self.native()
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        native = self.target / COMPAT
        native.unlink()
        administrator = b'[IOCost]\nTargetSolution=isolation\n'
        native.write_bytes(administrator); native.chmod(0o644)
        saved = payload_read_bytes(self.target / SAVED)
        for run in range(2):
            result = self.run_policy(profile('btrfs-de'), before=ROOT_TOOL)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload_read_bytes(native), administrator)
            self.assertEqual(payload_read_bytes(self.target / SAVED), saved)
            self.assertFalse(any(os.path.lexists(self.target / rel) for rel in ASSETS[1:]))


    def test_lock_prevents_interleaved_publishers(self):
        lock = self.target / '.installer-iocost.lock'; lock.mkdir(mode=0o700)
        result = self.run_policy(); self.assertNotEqual(result.returncode, 0)
        self.assertTrue(lock.is_dir())
        self.assertFalse(any((self.target / rel).exists() for rel in ASSETS[1:]))


    def legacy_generation(self):
        self.native()
        result = self.run_policy(before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        old = ('etc/systemd/iocost.conf',
               'etc/systemd/iocost.conf.d/70-unattended-installer.conf')
        for current, previous in zip(ASSETS[:2], old):
            destination = self.target / previous
            destination.parent.mkdir(parents=True, exist_ok=True)
            (self.target / current).rename(destination)
        (self.target / COMPAT).symlink_to('../systemd/iocost.conf.d/70-unattended-installer.conf')
        return old

    def test_legacy_owned_generation_migrates_to_regular_native_files(self):
        old = self.legacy_generation()
        result = self.run_policy(before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative in old:
            self.assertFalse((self.target / relative).exists())
        for relative in ASSETS[:2]:
            path = self.target / relative
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            self.assertEqual(payload_read_text(path).count('TargetSolution=naive'), 1)
        result = self.run_policy(profile('btrfs-de'), before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_absent()

    def test_legacy_migration_failure_restores_links_and_original_bytes(self):
        old = self.legacy_generation()
        originals = {rel: payload_read_bytes(self.target / rel) for rel in (*old, SAVED, 'etc/udev/hwdb.bin')}
        failure = ROOT_TOOL + """
iocost_native_hwdb() {
  case "$1" in --root=/) return 73 ;; esac
  target_exec /usr/bin/systemd-hwdb "$@"
}
"""
        result = self.run_policy(before=failure)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.target / COMPAT), '../systemd/iocost.conf.d/70-unattended-installer.conf')
        for relative, original in originals.items():
            self.assertEqual(payload_read_bytes(self.target / relative), original)
        self.assertFalse((self.target / ASSETS[1]).exists())

    def test_unmanaged_legacy_files_are_never_deleted(self):
        self.native()
        old = self.target / 'etc/systemd/iocost.conf'
        old.parent.mkdir(parents=True)
        old.write_text('[IOCost]\nTargetSolution=naive\n')
        for values in (profile(), profile('btrfs-de')):
            result = self.run_policy(values, before=ROOT_TOOL)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload_read_text(old), '[IOCost]\nTargetSolution=naive\n')


    def calibrated_fixture(self):
        return json.loads(payload_read_text(FORKY / 'tests/fixtures/iocost/resctl-bench-20260923.json'))

    def native_properties(self, model='KXG6AZNV512G TOSHIBA', firmware='5108AGLA'):
        result = subprocess.run(['/usr/bin/systemd-hwdb', '--root=' + str(self.target),
                                 'query', f'block::name:{model}:fwrev:{firmware}:'],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split('=', 1) for line in result.stdout.splitlines()
                    if line.startswith('IOCOST_'))

    def expected_naive_properties(self):
        fixture = self.calibrated_fixture()
        fields = ('rbps', 'rseqiops', 'rrandiops', 'wbps', 'wseqiops', 'wrandiops')
        qos_fields = ('rpct', 'rlat', 'wpct', 'wlat', 'min', 'max')
        qos = fixture['qos']
        return {'IOCOST_SOLUTIONS': 'naive',
                'IOCOST_MODEL_NAIVE': ' '.join(f'{key}={fixture["model"][key]}' for key in fields),
                'IOCOST_QOS_NAIVE': ' '.join(f'{key}={qos[key]:.2f}' if isinstance(qos[key], float)
                                           else f'{key}={qos[key]}' for key in qos_fields)}

    def synthetic_policy(self, solutions):
        # Test-only policies exercise reserved and future names, never shipped.
        values = profile()
        base = dict(values)
        values['IOCOST_SOLUTIONS'] = ' '.join(solutions)
        values['IOCOST_TARGET_SOLUTION'] = solutions[0]
        for key in values:
            if key.startswith(('IOCOST_MODEL_', 'IOCOST_QOS_')):
                values[key] = ''
        for name in solutions:
            group = name.upper().replace('-', '_')
            for kind, fields in (('MODEL', ('RBPS', 'RSEQIOPS', 'RRANDIOPS', 'WBPS', 'WSEQIOPS', 'WRANDIOPS')),
                                 ('QOS', ('RPCT', 'RLAT', 'WPCT', 'WLAT', 'MIN', 'MAX'))):
                for suffix in fields:
                    values[f'IOCOST_{kind}_{group}_{suffix}'] = base[f'IOCOST_{kind}_NAIVE_{suffix}']
        return values

    def exported_fixture(self):
        return json.loads(payload_read_text(FORKY / 'tests/fixtures/iocost/exports-20260923.json'))

    def expected_exported_properties(self):
        fixture = self.exported_fixture()
        properties = {'IOCOST_SOLUTIONS': ' '.join(fixture['solution_order'])}
        for name in fixture['solution_order']:
            group = name.upper().replace('-', '_')
            for kind, fields in (('model', ('rbps', 'rseqiops', 'rrandiops', 'wbps', 'wseqiops', 'wrandiops')),
                                 ('qos', ('rpct', 'rlat', 'wpct', 'wlat', 'min', 'max'))):
                values = fixture['solutions'][name][kind]
                properties[f'IOCOST_{kind.upper()}_{group}'] = ' '.join(
                    f'{key}={values[key]:.2f}' if key in ('rpct', 'wpct', 'min', 'max')
                    else f'{key}={values[key]}' for key in fields)
        return properties

    def test_all_profiles_match_measured_fixture_without_changing_enable_flags(self):
        fixture = self.exported_fixture()
        for path in sorted((FORKY / 'hosts/profiles').glob('*.env')):
            with self.subTest(profile=path.stem):
                values = profile(path.stem)
                self.assertEqual(values['IOCOST_DEVICE_MODEL_MATCH'], fixture['device_model'])
                self.assertEqual(values['IOCOST_DEVICE_FWREV_MATCH'], '*')
                self.assertEqual(values['IOCOST_SOLUTIONS'], ' '.join(fixture['solution_order']))
                self.assertEqual(values['IOCOST_TARGET_SOLUTION'], fixture['selected'])
                self.assertEqual(values['IOCOST_CALIBRATE_ENABLE'],
                                 'true' if path.stem == 'btrfs-de-flex' else 'false')
                for name in fixture['reserved_solution_order']:
                    group = name.upper().replace('-', '_')
                    for kind, fields in (('model', ('rbps', 'rseqiops', 'rrandiops', 'wbps', 'wseqiops', 'wrandiops')),
                                         ('qos', ('rpct', 'rlat', 'wpct', 'wlat', 'min', 'max'))):
                        for field in fields:
                            expected = ''
                            if name in fixture['solutions']:
                                value = fixture['solutions'][name][kind][field]
                                expected = f'{value:.2f}' if field in ('rpct', 'wpct', 'min', 'max') else str(value)
                            self.assertEqual(values[f'IOCOST_{kind.upper()}_{group}_{field.upper()}'], expected)

    def test_calibration_provenance_matches_original_native_export(self):
        fixture = self.calibrated_fixture()
        directory = FORKY.parents[1] / 'd-i/forky/tests/fixtures/iocost/calibration'
        for name in ('resctl-native-hwdb.txt', 'solutions.json'):
            self.assertEqual(hashlib.sha256(payload_read_bytes(directory / name)).hexdigest(),
                             fixture['source_sha256'][name])
        parsed = json.loads(payload_read_text(directory / 'solutions.json'))
        self.assertTrue(parsed['complete'])
        self.assertEqual(parsed['selected'], 'naive')
        self.assertEqual(parsed['solutions']['naive']['model'], fixture['model'])
        self.assertEqual(parsed['solutions']['naive']['qos'], fixture['qos'])
        for name in fixture['unavailable_standard_solutions']:
            self.assertNotIn(name, parsed['solutions'])
        exported = dict(line.strip().split('=', 1)
                        for line in payload_read_text(directory / 'resctl-native-hwdb.txt').splitlines()
                        if line.strip().startswith('IOCOST_'))
        for key, value in self.expected_naive_properties().items():
            self.assertEqual(exported[key], value)

    def test_native_database_contains_all_six_exact_exported_solutions(self):
        self.native()
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.native_properties(), self.expected_exported_properties())
        rendered = payload_read_text(self.target / ASSETS[2])
        properties = dict(line[1:].split('=', 1) for line in rendered.splitlines()
                          if line.startswith(' IOCOST_'))
        self.assertEqual(properties, self.expected_exported_properties())
        self.assertEqual(len(properties), 13)
        self.assertNotIn('IOCOST_QOS_ISOLATION', rendered)
        self.assertNotIn('IOCOST_QOS_BANDWIDTH', rendered)
        self.assertNotIn('IOCOST_LAB_PROFILE', rendered)
        self.assertNotIn('iocost-lab:', rendered)

    def test_native_rule_does_not_match_other_models_or_capacities(self):
        self.native()
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        for model in ('KXG6AZNV512G', 'KXG6AZNV512G TOSHIBA EXTRA',
                      'KXG6AZNV256G TOSHIBA', 'WDC PC SN730 SDBQNTY-512G-1001',
                      'KXG6AZNV512G TOSHIB', 'KXG6AZNV512G_TOSHIBA'):
            with self.subTest(model=model):
                self.assertEqual(self.native_properties(model), {})

    def test_firmware_wildcard_matches_every_test_revision_and_missing_revision(self):
        self.native()
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        for firmware in ('5108AGLA', '5108AGLB', '0000', 'next-firmware', '', '1.2.3', 'A B'):
            with self.subTest(firmware=firmware):
                self.assertEqual(self.native_properties(firmware=firmware), self.expected_exported_properties())

    def test_all_profiles_support_explicit_opt_in_with_the_same_native_output(self):
        self.native()
        for path in sorted((FORKY / 'hosts/profiles').glob('*.env')):
            with self.subTest(profile=path.stem):
                values = profile(path.stem)
                values['IOCOST_CALIBRATE_ENABLE'] = 'true'
                result = self.run_policy(values, before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.native_properties(), self.expected_exported_properties())
                self.assertIn('TargetSolution=naive', payload_read_text(self.target / COMPAT))

    def test_every_advertised_qos_field_is_required(self):
        for suffix in ('RPCT', 'RLAT', 'WPCT', 'WLAT', 'MIN', 'MAX'):
            with self.subTest(field=suffix):
                self.invalid(missing='IOCOST_QOS_NAIVE_' + suffix)

    def test_unadvertised_qos_fields_must_be_empty_even_when_disabled(self):
        for group in ('ISOLATION', 'ISOLATED_BANDWIDTH', 'BANDWIDTH'):
            for suffix in ('RPCT', 'RLAT', 'WPCT', 'WLAT', 'MIN', 'MAX'):
                with self.subTest(group=group, field=suffix):
                    self.invalid({'IOCOST_QOS_' + group + '_' + suffix: '1'})
        self.invalid({'IOCOST_CALIBRATE_ENABLE': 'false', 'IOCOST_QOS_ISOLATION_RLAT': '1000'})

    def test_adding_unmeasured_solution_without_qos_fails_before_publication(self):
        for name in ('isolation', 'isolated-bandwidth', 'bandwidth'):
            with self.subTest(solution=name):
                self.invalid({'IOCOST_SOLUTIONS': name + ' naive', 'IOCOST_TARGET_SOLUTION': name})

    def test_control_characters_in_unadvertised_fields_are_rejected(self):
        for value in ('\n', '\t', '\r', '\x01', '1\nIOCOST_QOS_NAIVE_RLAT=1'):
            with self.subTest(value=repr(value)):
                self.invalid({'IOCOST_QOS_ISOLATION_RLAT': value})

    def test_standard_solution_subsets_and_reruns_remove_stale_properties(self):
        self.native()
        for names in (('isolation', 'isolated-bandwidth', 'bandwidth', 'naive'),
                      ('bandwidth', 'naive'), ('isolation',), ('naive',)):
            with self.subTest(solutions=names):
                result = self.run_policy(self.synthetic_policy(names), before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                properties = self.native_properties()
                self.assertEqual(properties['IOCOST_SOLUTIONS'], ' '.join(names))
                expected_keys = {'IOCOST_SOLUTIONS'}
                for name in names:
                    for kind in ('MODEL', 'QOS'):
                        expected_keys.add('IOCOST_' + kind + '_' + name.upper().replace('-', '_'))
                self.assertEqual(set(properties), expected_keys)
        self.assertEqual(self.native_properties(), self.expected_naive_properties())

    def test_missing_selected_template_property_fails_before_publication(self):
        self.native()
        before = r'''
fetch_hook() {
  case "$1" in
    *.hwdb.tmpl) sed '/^ IOCOST_SOLUTIONS=/d' "$FIXTURE_SOURCE/$1" >"$2" ;;
    *) cp -- "$FIXTURE_SOURCE/$1" "$2" ;;
  esac
}
'''
        result = self.run_policy(before=before)
        self.assertNotEqual(result.returncode, 0)
        self.assert_absent()
        self.assertFalse((self.target / 'etc/udev/hwdb.bin').exists())

    def test_duplicate_selected_template_property_fails_before_publication(self):
        self.native()
        before = r'''
fetch_hook() {
  cp -- "$FIXTURE_SOURCE/$1" "$2"
  case "$1" in *.hwdb.tmpl) printf '%s\n' ' IOCOST_SOLUTIONS=naive' >>"$2" ;; esac
}
'''
        result = self.run_policy(before=before)
        self.assertNotEqual(result.returncode, 0)
        self.assert_absent()
        self.assertFalse((self.target / 'etc/udev/hwdb.bin').exists())

    def test_later_conflicting_hwdb_rule_rolls_back_publication(self):
        self.native()
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stderr)
        originals = {rel: payload_read_bytes(self.target / rel) for rel in (*ASSETS, SAVED, 'etc/udev/hwdb.bin')}
        admin = self.target / 'etc/udev/hwdb.d/99-admin.hwdb'
        content = ('block::name:KXG6AZNV512G TOSHIBA:fwrev:5108AGLA:\n'
                   ' IOCOST_QOS_NAIVE=rpct=99 rlat=100 wpct=99 wlat=100 min=75 max=100\n')
        admin.write_text(content)
        result = self.run_policy(before=ROOT_TOOL)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload_read_text(admin), content)
        self.assertEqual(originals, {rel: payload_read_bytes(self.target / rel) for rel in originals})
        self.assertFalse(list(self.target.glob('.installer-iocost*')))

    def test_new_export_json_and_hwdb_have_identical_measurements(self):
        fixture = self.exported_fixture()
        directory = FORKY.parents[1] / 'd-i/forky/tests/fixtures/iocost/exports'
        for name in ('profile.json', 'export.hwdb'):
            self.assertEqual(hashlib.sha256(payload_read_bytes(directory / name)).hexdigest(),
                             fixture['source_sha256'][name])
        source = json.loads(payload_read_text(directory / 'profile.json'))
        self.assertEqual(source['selected'], fixture['selected'])
        self.assertEqual(source['solution_order'], fixture['solution_order'])
        self.assertEqual(source['source_result_sha256'], self.calibrated_fixture()['source_sha256']['resctl-results.json'])
        for name in fixture['solution_order']:
            for group in ('model', 'qos'):
                self.assertEqual(source['solutions'][name][group], fixture['solutions'][name][group])
        actual = dict(line.strip().split('=', 1) for line in payload_read_text(directory / 'export.hwdb').splitlines()
                      if line.startswith(' IOCOST_') and not line.startswith(' IOCOST_LAB_PROFILE='))
        self.assertEqual(actual, self.expected_exported_properties())

    def test_each_exported_solution_can_be_the_native_target(self):
        self.native()
        for solution in self.exported_fixture()['solution_order']:
            with self.subTest(solution=solution):
                values = profile()
                values['IOCOST_TARGET_SOLUTION'] = solution
                result = self.run_policy(values, before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.native_properties(), self.expected_exported_properties())
                for path in ASSETS[:2]:
                    self.assertIn('TargetSolution=' + solution + '\n', payload_read_text(self.target / path))
                # Read-only native parser: abort at a nonexistent device, never apply.
                query = subprocess.run(['chroot', str(self.target), '/usr/bin/env',
                                        'SYSTEMD_LOG_LEVEL=debug', 'SYSTEMD_LOG_TARGET=console',
                                        '/usr/lib/udev/iocost', 'query', '/sys/installer-nonexistent-device'],
                                       text=True, capture_output=True, timeout=10)
                self.assertNotEqual(query.returncode, 0)
                self.assertIn('Target solution: ' + solution, query.stderr)

    def test_all_advertised_model_and_qos_fields_are_required(self):
        for name in self.exported_fixture()['solution_order']:
            group = name.upper().replace('-', '_')
            for kind, fields in (('MODEL', ('RBPS', 'RSEQIOPS', 'RRANDIOPS', 'WBPS', 'WSEQIOPS', 'WRANDIOPS')),
                                 ('QOS', ('RPCT', 'RLAT', 'WPCT', 'WLAT', 'MIN', 'MAX'))):
                for suffix in fields:
                    with self.subTest(name=name, kind=kind, field=suffix):
                        self.invalid(missing=f'IOCOST_{kind}_{group}_{suffix}')

    def test_reserved_fields_must_be_explicit_and_empty(self):
        for group in ('ISOLATION', 'ISOLATED_BANDWIDTH', 'BANDWIDTH'):
            for kind, fields in (('MODEL', ('RBPS', 'RSEQIOPS', 'RRANDIOPS', 'WBPS', 'WSEQIOPS', 'WRANDIOPS')),
                                 ('QOS', ('RPCT', 'RLAT', 'WPCT', 'WLAT', 'MIN', 'MAX'))):
                for field in fields:
                    key = f'IOCOST_{kind}_{group}_{field}'
                    with self.subTest(key=key):
                        self.invalid(missing=key)
                        self.invalid({key: '1'})

    def test_future_named_solutions_need_no_helper_or_template_change(self):
        self.native()
        for names in (('wlat-99-q2', 'balanced-v2', 'naive'), ('balanced-v2',)):
            with self.subTest(names=names):
                values = self.synthetic_policy(names)
                values['IOCOST_MODEL_BALANCED_V2_RBPS'] = '123456789'
                values['IOCOST_QOS_BALANCED_V2_RLAT'] = '1234'
                result = self.run_policy(values, before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                properties = self.native_properties()
                self.assertEqual(len(properties), 1 + 2 * len(names))
                self.assertEqual(properties['IOCOST_SOLUTIONS'], ' '.join(names))
                self.assertIn('rbps=123456789 ', properties['IOCOST_MODEL_BALANCED_V2'])
                self.assertIn(' rlat=1234 ', properties['IOCOST_QOS_BALANCED_V2'])
                self.assertIn('TargetSolution=' + names[0], payload_read_text(self.target / COMPAT))

    def test_future_names_and_colliding_spellings_are_rejected(self):
        for name in ('../naive', 'bad_name', 'Naive', 'naive--v2', '-naive', 'naive-', 'naive.v2',
                     '1naive', 'naive;id', 'a' * 49, 'naive$(id)', 'naive\tparams-naive'):
            with self.subTest(name=name):
                self.invalid({'IOCOST_SOLUTIONS': name, 'IOCOST_TARGET_SOLUTION': name})
        names = ' '.join('solution-' + str(i) for i in range(33))
        self.invalid({'IOCOST_SOLUTIONS': names, 'IOCOST_TARGET_SOLUTION': 'solution-0'})

    def test_old_shared_model_fields_are_not_silently_ignored(self):
        for field in ('RBPS', 'RSEQIOPS', 'RRANDIOPS', 'WBPS', 'WSEQIOPS', 'WRANDIOPS'):
            self.invalid({'IOCOST_MODEL_' + field: '123'})

    def test_zero_percentiles_and_latencies_follow_directional_semantics(self):
        for direction in ('R', 'W'):
            values = profile()
            values[f'IOCOST_QOS_NAIVE_{direction}PCT'] = '0.00'
            values[f'IOCOST_QOS_NAIVE_{direction}LAT'] = '0'
            result = self.run_policy(values, enabled=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            values[f'IOCOST_QOS_NAIVE_{direction}LAT'] = '500'
            result = self.run_policy(values, enabled=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.invalid({f'IOCOST_QOS_NAIVE_{direction}LAT': '0'})
        for field, value in (('WPCT', '1'), ('WLAT', '-1')):
            self.invalid({'IOCOST_QOS_RLAT_99_Q2_' + field: value})

    def test_numeric_edges_are_consistent_in_every_solution(self):
        for group in ('NAIVE', 'PARAMS_NAIVE', 'RLAT_99_Q1', 'RLAT_99_Q2', 'RLAT_99_Q3', 'RLAT_99_Q4'):
            for key, value in ((f'IOCOST_MODEL_{group}_RSEQIOPS', '1000000001'),
                               (f'IOCOST_MODEL_{group}_RBPS', '0123'),
                               (f'IOCOST_QOS_{group}_MIN', '0.99'),
                               (f'IOCOST_QOS_{group}_MAX', '0'),
                               (f'IOCOST_QOS_{group}_RLAT', '60000001'),
                               (f'IOCOST_QOS_{group}_RPCT', '00.10')):
                with self.subTest(key=key, value=value):
                    self.invalid({key: value})
        values = profile()
        values.update(IOCOST_QOS_NAIVE_MIN='1', IOCOST_QOS_NAIVE_MAX='10000',
                      IOCOST_MODEL_NAIVE_RBPS='1000000000000', IOCOST_MODEL_NAIVE_RSEQIOPS='1000000000')
        result = self.run_policy(values, enabled=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_raw_environment_control_injection_is_rejected(self):
        for value in ('1\nIOCOST_QOS_NAIVE_RLAT=2', '1\r', '1\x7f', '1\t'):
            self.invalid({'IOCOST_MODEL_RLAT_99_Q2_RBPS': value})
        self.invalid({'IOCOST_MODEL_RLAT_99_Q2_RBPS': '$(touch /tmp/not-executed)'})

    def test_nonexported_profile_scalars_and_caller_state_are_preserved(self):
        values = profile()
        assignments = '\n'.join(k + '=' + shlex.quote(v) for k, v in values.items())
        command = self.code + '\n' + assignments + r'''
IOCOST_CALLER_SENTINEL=unchanged
before=$(export -p)
iocost_placeholder_map >/dev/null
after=$(export -p)
[ "$before" = "$after" ]
[ "$IOCOST_CALLER_SENTINEL" = unchanged ]
'''
        for shell in (('/bin/sh',), ('/bin/bash',), (shutil.which('busybox'), 'sh')):
            with self.subTest(shell=shell):
                result = subprocess.run([*shell, '-eu', '-c', command], env=self.env, text=True,
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_extra_hwdb_match_or_unexpected_property_is_rejected(self):
        self.native()
        for line in ('block::name:*:fwrev:*:', ' ID_MODEL=another-drive', ' IOCOST_LAB_PROFILE=unexpected',
                     ' IOCOST_QOS_UNKNOWN=rpct=99 rlat=100 wpct=99 wlat=100 min=75 max=100'):
            with self.subTest(line=line):
                before = '''fetch_hook() {
  cp -- "$FIXTURE_SOURCE/$1" "$2"
  case "$1" in *.hwdb.tmpl) printf '%s\\n' ''' + shlex.quote(line) + ''' >>"$2" ;; esac
}
'''
                result = self.run_policy(before=before)
                self.assertNotEqual(result.returncode, 0)
                self.assert_absent()

    def test_changed_template_solution_list_is_rejected(self):
        self.native()
        before = r'''
fetch_hook() {
  case "$1" in
    *.hwdb.tmpl) sed 's/__INSTALLER_IOCOST_SOLUTIONS__/naive/' "$FIXTURE_SOURCE/$1" >"$2" ;;
    *) cp -- "$FIXTURE_SOURCE/$1" "$2" ;;
  esac
}
'''
        result = self.run_policy(before=before)
        self.assertNotEqual(result.returncode, 0)
        self.assert_absent()

    def test_wildcard_override_guard_covers_exact_prefix_and_bracket_firmware(self):
        self.native()
        admin = self.target / 'etc/udev/hwdb.d/99-admin.hwdb'
        admin.parent.mkdir(parents=True, exist_ok=True)
        for pattern in ('block::name:KXG6AZNV512G TOSHIBA:fwrev:5108AGLA:',
                        'block::name:KXG6AZNV512G TOSHIBA:fwrev:51*:',
                        'block::name:KXG6AZNV512G TOSHIBA:fwrev:51[0-9]8*:',
                        'block::name:KXG6AZNV512G TOSHIB[A]:fwrev:*:',
                        'block::name:KXG6AZNV*:fwrev:5108????:',
                        'block:*'):
            with self.subTest(pattern=pattern):
                content = pattern + '\n IOCOST_QOS_NAIVE=conflicting-values\n'
                admin.write_text(content)
                result = self.run_policy(before=ROOT_TOOL)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('overlapping hwdb record preserved', result.stderr)
                self.assertEqual(payload_read_text(admin), content)
                self.assert_absent()

    def test_lower_priority_defaults_and_same_value_overrides_remain_supported(self):
        self.native()
        vendor = self.target / 'usr/lib/udev/hwdb.d/60-iocost-default.hwdb'
        vendor.write_text('block::name:KXG6AZNV512G TOSHIBA:fwrev:*:\n'
                          ' IOCOST_SOLUTIONS=naive\n IOCOST_MODEL_NAIVE=old-model\n IOCOST_QOS_NAIVE=old-qos\n')
        admin = self.target / 'etc/udev/hwdb.d/99-admin.hwdb'
        admin.parent.mkdir(parents=True, exist_ok=True)
        qos = self.expected_exported_properties()['IOCOST_QOS_NAIVE']
        admin.write_text('block::name:KXG6AZNV512G TOSHIBA:fwrev:5108AGLA:\n IOCOST_QOS_NAIVE=' + qos + '\n')
        result = self.run_policy(before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.native_properties(), self.expected_exported_properties())
        self.assertIn('old-model', payload_read_text(vendor))

    def test_unadvertised_merged_properties_are_rejected_even_from_earlier_rules(self):
        self.native()
        vendor = self.target / 'usr/lib/udev/hwdb.d/60-iocost-default.hwdb'
        content = ('block::name:KXG6AZNV512G TOSHIBA:fwrev:5108AGLA:\n'
                   ' IOCOST_QOS_ISOLATION=unadvertised\n')
        vendor.write_text(content)
        result = self.run_policy(before=ROOT_TOOL)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload_read_text(vendor), content)
        self.assert_absent()

    def test_hwdb_same_basename_shadowing_and_dev_null_mask_are_respected(self):
        self.native()
        vendor = self.target / 'usr/lib/udev/hwdb.d/99-overridden.hwdb'
        content = 'block::name:KXG6AZNV512G TOSHIBA:fwrev:*:\n IOCOST_QOS_NAIVE=wrong\n'
        vendor.write_text(content)
        admin = self.target / 'etc/udev/hwdb.d/99-overridden.hwdb'
        admin.parent.mkdir(parents=True, exist_ok=True)
        for mask in (True, False):
            with self.subTest(mask=mask):
                if os.path.lexists(admin): admin.unlink()
                if mask:
                    admin.symlink_to('/dev/null')
                else:
                    admin.write_text('fixture:unrelated\n ADMIN_PRESERVED=yes\n')
                result = self.run_policy(before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.native_properties(), self.expected_exported_properties())
                self.assertEqual(payload_read_text(vendor), content)

    def test_unrelated_drive_and_private_lookup_records_are_preserved(self):
        self.native()
        admin = self.target / 'etc/udev/hwdb.d/99-unrelated.hwdb'
        admin.parent.mkdir(parents=True, exist_ok=True)
        content = ('block::name:UNRELATED DRIVE:fwrev:*:\n IOCOST_QOS_NAIVE=other\n\n'
                   'iocost-lab:fixture:\n IOCOST_LAB_PROFILE=fixture\n')
        admin.write_text(content)
        result = self.run_policy(before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.native_properties(), self.expected_exported_properties())
        self.assertEqual(payload_read_text(admin), content)

    def test_unsafe_hwdb_source_link_cannot_escape_staging_root(self):
        self.native()
        outside = self.base / 'outside.hwdb'
        outside.write_text('block:*\n IOCOST_SOLUTIONS=other\n')
        source = self.target / 'etc/udev/hwdb.d/99-unsafe.hwdb'
        source.parent.mkdir(parents=True, exist_ok=True)
        source.symlink_to(outside)
        result = self.run_policy(before=ROOT_TOOL)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe hwdb source preserved', result.stderr)
        self.assertEqual(payload_read_text(outside), 'block:*\n IOCOST_SOLUTIONS=other\n')
        self.assert_absent()

    def test_exact_firmware_opt_in_keeps_disjoint_firmware_rules(self):
        self.native()
        values = profile()
        values['IOCOST_DEVICE_FWREV_MATCH'] = '5108AGLA'
        admin = self.target / 'etc/udev/hwdb.d/99-other-firmware.hwdb'
        admin.parent.mkdir(parents=True, exist_ok=True)
        admin.write_text('block::name:KXG6AZNV512G TOSHIBA:fwrev:5108AGLB:\n IOCOST_SOLUTIONS=other\n')
        result = self.run_policy(values, before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.native_properties(), self.expected_exported_properties())
        self.assertEqual(self.native_properties(firmware='5108AGLB'), {'IOCOST_SOLUTIONS': 'other'})

    def test_conservative_glob_overlap_handles_installer_shells(self):
        pairs = (('AB*', 'AC*', False), ('AB', 'A?', True), ('AB', 'AC', False),
                 ('AB*', 'AB[1-9]', True), ('AB*', 'AC[1-9]', False),
                 ('*', '51[0-9]8*', True), ('AB*', 'AB\\?', True),
                 ('AB*', 'AC\\?', False), ('', '*', True),
                 ('block:*', 'iocost-lab:fixture:', False))
        for shell in (('/bin/sh',), ('/bin/bash',), (shutil.which('busybox'), 'sh')):
            for left, right, overlaps in pairs:
                with self.subTest(shell=shell, left=left, right=right):
                    command = self.code + '\niocost_patterns_may_overlap ' + shlex.quote(left) + ' ' + shlex.quote(right)
                    result = subprocess.run([*shell, '-eu', '-c', command], env=self.env, text=True,
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0 if overlaps else 1, result.stderr)


if __name__ == '__main__': unittest.main()
