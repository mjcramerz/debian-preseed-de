"""IOCost literal policy, native rendering, isolated hwdb and rollback tests.

Only disposable roots are changed. No calibration, cgroup write or uevent runs.
"""
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
                       (FORKY / 'hosts/profiles' / (name + '.env')).read_text(), re.M)
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
        self.code = '\n'.join('. ' + shlex.quote(str(FORKY / name)) for name in
                              ('scripts/common/lib.sh', 'scripts/common/target.sh',
                               'scripts/late/target-assets.sh', 'scripts/late/iocost.sh'))
        self.code += '\nfetch_hook() { cp -- "$FIXTURE_SOURCE/$1" "$2"; }\n'

    def native(self, with_defaults=True):
        if os.geteuid() != 0 or not Path('/usr/bin/systemd-hwdb').is_file():
            self.skipTest('native target hwdb fixture requires root and systemd-hwdb')
        copy_binary(self.target, '/usr/bin/systemd-hwdb')
        copy_binary(self.target, '/usr/bin/env')
        self.assertEqual((self.target / 'usr/bin/systemd-hwdb').read_bytes(), Path('/usr/bin/systemd-hwdb').read_bytes())
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
            self.original_native = STOCK_NATIVE.read_bytes()
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
            self.assertEqual(native.read_bytes(), self.original_native)
            self.assertEqual(native.stat().st_mode & 0o7777, 0o644)
        self.assertFalse(list(self.target.glob('.installer-iocost*')))

    def test_all_profiles_complete_and_exact_enable_matrix(self):
        enabled = []
        profiles = sorted((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 13)
        for path in profiles:
            values = profile(path.stem)
            self.assertEqual(len(values), 35)
            result = self.run_policy(values, enabled=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(result.stdout.splitlines()), 35)
            if values['IOCOST_CALIBRATE_ENABLE'] == 'true': enabled.append(path.name)
        self.assertEqual(enabled, ['btrfs-de-dual-flex.env', 'btrfs-de-flex.env'])
        self.assertEqual(len(profiles) - len(enabled), 11)

    def test_complete_policy_survives_trusted_composite_profile_loading(self):
        from test_repository_integrity import records
        name = 'btrfs-de-flex'
        overrides = {row['Name'] for row in records() if row['Group'] == 'profile'}
        logical = ('override-' if name in overrides else '') + name
        composed = self.base / 'composite.env'
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
        expected = self.run_policy(enabled=False)
        self.assertEqual(result.stdout, expected.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 35)

    def test_both_enabled_profiles_native_staging_and_query(self):
        self.native()
        for name in ('btrfs-de-flex', 'btrfs-de-dual-flex'):
            with self.subTest(profile=name):
                result = self.run_policy(profile(name), before=ROOT_TOOL if name.endswith('dual-flex') else '')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for relative in ASSETS:
                    path = self.target / relative
                    self.assertTrue(path.is_file())
                    self.assertNotIn('__INSTALLER_', path.read_text())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o644)
                    self.assertEqual((path.stat().st_uid, path.stat().st_gid), (0, 0))
                self.assertFalse(list(self.target.rglob('*.tmpl')))
                self.assertFalse((self.target / COMPAT).is_symlink())
                self.assertEqual((self.target / ASSETS[0]).read_text().count('TargetSolution=isolated-bandwidth'), 1)
                self.assertIn('TargetSolution=isolated-bandwidth', (self.target / ASSETS[1]).read_text())
                self.assertIn('block::name:KXG6AZNV512G*:fwrev:*:', (self.target / ASSETS[2]).read_text())
                saved = self.target / SAVED
                self.assertEqual(saved.read_bytes(), SAVED_MARKER + self.original_native)
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
            shutil.copyfile(FORKY / name, destination)
        for binary in ('/usr/bin/systemd-hwdb', '/usr/bin/env', '/usr/lib/udev/iocost'):
            copy_binary(outer / 'target', binary)
        native = outer / 'target' / COMPAT
        native.parent.mkdir(parents=True, exist_ok=True)
        native.write_bytes(STOCK_NATIVE.read_bytes())
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
            self.assertNotIn('__INSTALLER_', published.read_text())
        self.assertTrue((outer / 'target/etc/udev/hwdb.bin').is_file())
        self.assertFalse((outer / 'target' / COMPAT).is_symlink())
        self.assertEqual((outer / 'target' / SAVED).read_bytes(),
                         SAVED_MARKER + STOCK_NATIVE.read_bytes())

    def test_disabled_btrfs_f2fs_vm_create_no_files_or_database(self):
        for name in ('btrfs-de', 'f2fs-de', 'vm-desktop'):
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
        self.invalid(missing='IOCOST_MODEL_RBPS')

    def test_missing_qos_fails_before_publication(self):
        self.invalid(missing='IOCOST_QOS_ISOLATED_BANDWIDTH_RLAT')

    def test_target_must_be_listed(self):
        self.invalid({'IOCOST_TARGET_SOLUTION': 'typo'})
        self.invalid({'IOCOST_SOLUTIONS': 'naive'})

    def test_solution_duplicates_and_injection_rejected(self):
        for value in ('naive naive', 'naive;id', 'naive  isolated-bandwidth', 'naive\nisolated-bandwidth'):
            with self.subTest(value=value): self.invalid({'IOCOST_SOLUTIONS': value})

    def test_numeric_formats_and_bounds(self):
        for key, bad in (('IOCOST_MODEL_RBPS', '-1'), ('IOCOST_MODEL_RBPS', '1e9'),
                         ('IOCOST_MODEL_RBPS', '1000000000001'), ('IOCOST_MODEL_RBPS', '0'),
                         ('IOCOST_QOS_NAIVE_RPCT', '101'), ('IOCOST_QOS_NAIVE_RLAT', '0'),
                         ('IOCOST_QOS_NAIVE_MIN', '1.234'), ('IOCOST_QOS_NAIVE_MAX', '10001')):
            with self.subTest(key=key, bad=bad): self.invalid({key: bad})

    def test_minimum_cannot_exceed_maximum(self):
        self.invalid({'IOCOST_QOS_ISOLATION_MIN': '81'})

    def test_newline_property_injection_rejected(self):
        self.invalid({'IOCOST_DEVICE_FWREV_MATCH': '*\n IOCOST_SOLUTIONS=naive'})
        self.invalid({'IOCOST_MODEL_RBPS': '1\nIOCOST_MODEL_RBPS=2'})

    def test_unsafe_and_broad_model_patterns_rejected(self):
        for value in ('*', 'NVMe*', 'KXG6*', 'KXG6AZNV512G:fwrev:*', ' KXG6AZNV512G',
                      'KXG6AZNV512G[0-9]', 'KXG6AZNV512G=bad', 'KXG6AZNV512G\r', 'A'*129):
            with self.subTest(value=value): self.invalid({'IOCOST_DEVICE_MODEL_MATCH': value})

    def test_misspelled_boolean_is_rejected(self):
        for key in ('IOCOST_CALIBRATED_ENABLE', 'IOCOST_CALIBRATE_ENABLED', 'IO_COST_CALIBRATE_ENABLE'):
            self.invalid({key: 'true'})

    def test_disabled_values_are_still_validated(self):
        self.invalid({'IOCOST_CALIBRATE_ENABLE': 'false', 'IOCOST_MODEL_RBPS': 'garbage'})

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
        result = self.run_policy(profile('f2fs-de'), before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_absent(); self.assertTrue(admin.is_file())
        query = subprocess.run(['chroot', str(self.target), '/usr/bin/systemd-hwdb', 'query', 'fixture:vendor'], capture_output=True, text=True)
        self.assertEqual(query.returncode, 0, query.stderr)
        self.assertIn('VENDOR_PRESERVED=yes', query.stdout)
        query = subprocess.run(['chroot', str(self.target), '/usr/bin/systemd-hwdb', 'query', 'block::name:KXG6AZNV512G:fwrev:test:'], capture_output=True, text=True)
        self.assertNotIn('IOCOST_', query.stdout)

    def test_administrator_file_preserved_disabled_and_enabled_fails(self):
        path = self.target / ASSETS[1]; path.parent.mkdir(parents=True)
        path.write_text('[IOCost]\n# administrator\n')
        result = self.run_policy(profile('vm-desktop')); self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_policy(); self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_text(), '[IOCost]\n# administrator\n')
        self.assertFalse((self.target / ASSETS[0]).exists())

    def test_symlink_parent_cannot_escape_target(self):
        outside = self.base / 'outside'; outside.mkdir()
        (self.target / 'etc').symlink_to(outside)
        result = self.run_policy(); self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_target_hwdb_failure_rolls_back_prior_generation(self):
        self.native()
        result = self.run_policy(); self.assertEqual(result.returncode, 0, result.stderr)
        originals = {rel: (self.target / rel).read_bytes() for rel in (*ASSETS, 'etc/udev/hwdb.bin')}
        values = profile(); values['IOCOST_MODEL_RBPS'] = '999999999'
        before = '''
iocost_native_hwdb() {
  case "$1" in --root=/) return 73 ;; esac
  chroot "$iocost_root" /usr/bin/systemd-hwdb "$@"
}
'''
        result = self.run_policy(values, before)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(originals, {rel: (self.target / rel).read_bytes() for rel in originals})
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
            self.assertEqual((self.target / SAVED).read_bytes(), SAVED_MARKER + self.original_native)
        # Native parsing is observable before the intentionally nonexistent
        # device is rejected. This query never calls the apply/cgroup writer.
        result = subprocess.run(['chroot', str(self.target), '/usr/bin/env',
                                 'SYSTEMD_LOG_LEVEL=debug', 'SYSTEMD_LOG_TARGET=console',
                                 '/usr/lib/udev/iocost', 'query', '/sys/installer-nonexistent-device'],
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Target solution: isolated-bandwidth', result.stderr)

    def test_absent_native_config_and_legacy_link_still_work(self):
        self.native(with_defaults=False)
        for run in range(2):
            result = self.run_policy(before=ROOT_TOOL if run else '')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.target / SAVED).exists())
        result = self.run_policy(profile('vm-desktop'), before=ROOT_TOOL)
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
                self.assertEqual((self.target / SAVED).read_bytes(), SAVED_MARKER + original)
                result = self.run_policy(profile('f2fs-de'), before=ROOT_TOOL)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_absent()

    def test_disabled_stock_native_file_is_untouched_without_hwdb_tools(self):
        self.native()
        before = 'target_exec() { printf "unexpected native tool call\\n" >&2; return 91; }\n'
        result = self.run_policy(profile('vm-desktop'), before=before)
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
        outside.write_bytes(STOCK_NATIVE.read_bytes()); outside.chmod(0o644)
        for kind in ('group-writable', 'private-mode', 'wrong-owner', 'wrong-group',
                     'hardlink', 'symlink', 'dangling-link', 'directory', 'fifo'):
            with self.subTest(kind=kind):
                if kind == 'hardlink': os.link(outside, native)
                elif kind == 'symlink': native.symlink_to(outside)
                elif kind == 'dangling-link': native.symlink_to('missing')
                elif kind == 'directory': native.mkdir()
                elif kind == 'fifo': os.mkfifo(native)
                else:
                    native.write_bytes(STOCK_NATIVE.read_bytes()); native.chmod(0o644)
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
                self.assertEqual(outside.read_bytes(), STOCK_NATIVE.read_bytes())
                for relative in (*ASSETS[1:], SAVED):
                    self.assertFalse(os.path.lexists(self.target / relative), relative)
                if kind == 'directory': native.rmdir()
                else: native.unlink()

    def test_unmanaged_or_unsafe_native_backup_is_never_adopted(self):
        self.native()
        saved = self.target / SAVED
        for content in (STOCK_NATIVE.read_bytes(), SAVED_MARKER + b'[IOCost]\nTargetSolution=naive\n',
                        SAVED_MARKER + b'# bad\x00data\n'):
            saved.write_bytes(content); saved.chmod(0o644)
            result = self.run_policy()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('native-defaults backup preserved', result.stderr)
            self.assertEqual(saved.read_bytes(), content)
            self.assertEqual((self.target / COMPAT).read_bytes(), self.original_native)
            self.assertFalse(any(os.path.lexists(self.target / rel) for rel in ASSETS[1:]))
        saved.unlink()
        saved.symlink_to(self.target / COMPAT)
        result = self.run_policy()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(saved.is_symlink())
        self.assertEqual((self.target / COMPAT).read_bytes(), self.original_native)

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
        originals = {rel: (self.target / rel).read_bytes() for rel in (*ASSETS, SAVED, 'etc/udev/hwdb.bin')}
        before = '''
iocost_native_hwdb() {
  case "$1" in --root=/) return 73 ;; esac
  chroot "$iocost_root" /usr/bin/systemd-hwdb "$@"
}
'''
        result = self.run_policy(profile('f2fs-de'), before=before)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(originals, {rel: (self.target / rel).read_bytes() for rel in originals})
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
                result = self.run_policy(profile('f2fs-de'), before=ROOT_TOOL)
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
        saved = (self.target / SAVED).read_bytes()
        for run in range(2):
            result = self.run_policy(profile('vm-desktop'), before=ROOT_TOOL)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(native.read_bytes(), administrator)
            self.assertEqual((self.target / SAVED).read_bytes(), saved)
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
            self.assertEqual(path.read_text().count('TargetSolution=isolated-bandwidth'), 1)
        result = self.run_policy(profile('vm-desktop'), before=ROOT_TOOL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_absent()

    def test_legacy_migration_failure_restores_links_and_original_bytes(self):
        old = self.legacy_generation()
        originals = {rel: (self.target / rel).read_bytes() for rel in (*old, SAVED, 'etc/udev/hwdb.bin')}
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
            self.assertEqual((self.target / relative).read_bytes(), original)
        self.assertFalse((self.target / ASSETS[1]).exists())

    def test_unmanaged_legacy_files_are_never_deleted(self):
        self.native()
        old = self.target / 'etc/systemd/iocost.conf'
        old.parent.mkdir(parents=True)
        old.write_text('[IOCost]\nTargetSolution=naive\n')
        for values in (profile(), profile('vm-desktop')):
            result = self.run_policy(values, before=ROOT_TOOL)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(old.read_text(), '[IOCost]\nTargetSolution=naive\n')


if __name__ == '__main__': unittest.main()
