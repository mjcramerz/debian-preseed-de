#!/usr/bin/env python3
"""Offline regressions for the supplied 2026-09-14 desktop incident.

No application builds, target services, mounts, firmware changes or kernel
policy loads. Real filesystem/menu tests use private temporary fixtures;
service and D-Bus assertions inspect commands at the launch boundary.
"""
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import python_library
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from contextlib import ExitStack
import configparser
import json
import os
from pathlib import Path
import re
import stat
import shlex
import subprocess
import sys
import tempfile
import time
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
PACKAGE = python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')
sys.path.insert(0, str(PACKAGE))
from labwc_managed_app import dbus_proxy, environment, generic, profiles, sandbox, session


def load_script(name):
    path = TARGET / 'usr/local/bin' / name
    module = types.ModuleType('fixture_' + name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(payload_read_bytes(path), str(path), 'exec'), module.__dict__)
    return module


class ExternalDriveFlowTests(unittest.TestCase):
    """Real POSIX functions with fixture devices, lsblk, sync and UDisks."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='external-drive-flow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dev = self.root / 'dev'
        self.dev.mkdir()
        for name in ('sdb', 'sdb1', 'sdb2'):
            (self.dev / name).touch()
        self.folder = self.root / 'USB volume with spaces'
        self.folder.mkdir()
        self.trace = self.root / 'operations'
        self.trace.touch()
        self.first = self.root / 'first-mounted'
        self.second = self.root / 'second-mounted'
        self.first.touch()
        self.second.touch()
        self.env = os.environ.copy()
        self.env.update(FIXTURE_DEV_ROOT=str(self.dev), FIXTURE_FOLDER=str(self.folder),
                        FIXTURE_TRACE=str(self.trace), FIXTURE_FIRST=str(self.first),
                        FIXTURE_SECOND=str(self.second), FIXTURE_MODE='success',
                        FIXTURE_TRANSPORT='usb')
        source = payload_read_text(TARGET / 'usr/local/bin/labwc-external-drives')
        definitions, marker, _main = source.partition('\nrequested_operation=menu\n')
        self.assertTrue(marker, 'fixture must exclude the manager main loop')
        # Regular files represent block nodes only in this private hardware
        # fixture. Production identity and transport validation remain intact.
        self.assertEqual(definitions.count('[ -b "$device" ]'), 1)
        self.assertEqual(definitions.count('[ -b "$disk_device" ]'), 1)
        definitions = definitions.replace('[ -b "$device" ]', '[ -f "$device" ]')
        definitions = definitions.replace('[ -b "$disk_device" ]', '[ -f "$disk_device" ]')
        self.script = self.root / 'flow.sh'
        self.script.write_text(definitions + r'''
DEV_ROOT=$FIXTURE_DEV_ROOT
UNMOUNT_CONFIRM_ATTEMPTS=0
notify_drive() { :; }
settle_udev() { :; }
choose_lines() {
  [ "$FIXTURE_MODE" != cancel ] || return 0
  printf '%s\n' 'Sync, unmount volumes, and power off'
}
findmnt() {
  printf 'findmnt:%s\n' "$*" >>"$FIXTURE_TRACE"
  printf '%s/sdb1\n' "$DEV_ROOT"
}
lsblk() {
  fixture_output=
  fixture_device=
  while [ "$#" -gt 0 ]; do
    case "$1" in --output) shift; fixture_output=$1 ;; esac
    fixture_device=$1
    shift
  done
  case "$fixture_output" in
    MAJ:MIN,TYPE,TRAN,PKNAME)
      case "$fixture_device" in
        "$DEV_ROOT/sdb")
          fixture_disk_number=8:16
          if [ "$FIXTURE_MODE" = race ] && [ ! -f "$FIXTURE_FIRST" ]; then
            fixture_disk_number=8:32
          fi
          printf 'MAJ:MIN="%s" TYPE="disk" TRAN="%s" PKNAME=""\n' \
            "$fixture_disk_number" "$FIXTURE_TRANSPORT"
          ;;
        "$DEV_ROOT/sdb1")
          printf 'MAJ:MIN="8:17" TYPE="part" TRAN="" PKNAME="%s/sdb"\n' "$DEV_ROOT"
          ;;
        "$DEV_ROOT/sdb2")
          printf 'MAJ:MIN="8:18" TYPE="part" TRAN="" PKNAME="%s/sdb"\n' "$DEV_ROOT"
          ;;
      esac
      ;;
    *)
      if [ "$fixture_output" = PATH,KNAME,TYPE,TRAN,MOUNTPOINTS,PKNAME,MAJ:MIN ]; then
        printf 'PATH="%s/sdb" KNAME="%s/sdb" TYPE="disk" TRAN="%s" MAJ:MIN="8:16" MOUNTPOINTS="" PKNAME=""\n' \
          "$DEV_ROOT" "$DEV_ROOT" "$FIXTURE_TRANSPORT"
        if [ "$FIXTURE_MODE" = system-disk ] || [ "$FIXTURE_MODE" = mapped-data ]; then
          fixture_mapped_mount=/
          [ "$FIXTURE_MODE" != mapped-data ] || fixture_mapped_mount=/fixture
          printf 'PATH="%s/mapper/system" KNAME="%s/dm-0" TYPE="crypt" TRAN="" MAJ:MIN="253:0" MOUNTPOINTS="%s" PKNAME="%s/sdb1"\n' \
            "$DEV_ROOT" "$DEV_ROOT" "$fixture_mapped_mount" "$DEV_ROOT"
        fi
      fi
      for fixture_number in 1 2; do
        fixture_state=$FIXTURE_FIRST
        [ "$fixture_number" -eq 1 ] || fixture_state=$FIXTURE_SECOND
        [ -f "$fixture_state" ] || continue
        fixture_devnum=8:17
        [ "$fixture_number" -eq 1 ] || fixture_devnum=8:18
        fixture_mountpoint=/fixture
        [ "$FIXTURE_MODE" != active-swap ] || fixture_mountpoint='[SWAP]'
        printf 'PATH="%s/sdb%s" TYPE="part" TRAN="" PKNAME="%s/sdb" MAJ:MIN="%s" MOUNTPOINTS="%s" FSTYPE="ext4"\n' \
          "$DEV_ROOT" "$fixture_number" "$DEV_ROOT" "$fixture_devnum" "$fixture_mountpoint"
      done
      ;;
  esac
}
target_is_mounted() {
  case "$1" in
    "$DEV_ROOT/sdb1") [ -f "$FIXTURE_FIRST" ] ;;
    "$DEV_ROOT/sdb2") [ -f "$FIXTURE_SECOND" ] ;;
    *) return 1 ;;
  esac
}
mountpoint_for_target() {
  target_is_mounted "$1" "$2" || return 1
  printf '%s\n' "$FIXTURE_FOLDER"
}
timeout() { shift 4; "$@"; }
sync() {
  printf 'sync:%s\n' "$*" >>"$FIXTURE_TRACE"
  [ "$FIXTURE_MODE" != sync-failure ]
}
run_udisksctl() {
  printf 'udisks:%s:cwd=%s\n' "$*" "$PWD" >>"$FIXTURE_TRACE"
  if [ "$1" = unmount ]; then
    [ "$FIXTURE_MODE" != busy ] || return 7
    [ "$FIXTURE_MODE" != lingering ] || return 0
    case "$3" in
      "$DEV_ROOT/sdb1") rm -- "$FIXTURE_FIRST" ;;
      "$DEV_ROOT/sdb2") rm -- "$FIXTURE_SECOND" ;;
    esac
  fi
}
case "$1" in
  --fixture-shutdown) prepare_shutdown_drives ;;
  --unmount-device|--power-off-device) run_device_operation "$1" "$2" ;;
  *) run_path_operation "$1" "$2" ;;
esac
''')

    def run_action(self, operation, *, mode='success', transport='usb', path=None):
        self.env.update(FIXTURE_MODE=mode, FIXTURE_TRANSPORT=transport)
        result = subprocess.run(['/bin/dash', str(self.script), operation,
                                 str(path if path is not None else self.folder)],
                                cwd=self.folder, env=self.env, capture_output=True,
                                text=True, encoding='utf-8', timeout=5)
        self.events = self.trace.read_text().splitlines()
        return result

    def test_thunar_folder_actions_do_not_offer_drive_removal(self):
        actions = ET.fromstring(payload_read_text(TARGET / 'etc/skel-desktop/.config/Thunar/uca.xml'))
        managed = [a for a in actions if 'labwc-external-drives' in a.findtext('command', '')]
        self.assertEqual(managed, [])
        self.assertIn('Open Terminal Here', [a.findtext('name') for a in actions])
        self.assertEqual(len({a.findtext('unique-id') for a in actions}), len(actions))

    def test_folder_unmount_flushes_and_leaves_its_working_directory(self):
        result = self.run_action('--unmount-path')
        self.assertEqual(result.returncode, 0, result.stderr)
        operations = [e for e in self.events if e.startswith(('sync:', 'udisks:'))]
        self.assertEqual(operations, [
            'sync:--file-system -- ' + str(self.folder),
            'udisks:unmount --block-device ' + str(self.dev / 'sdb1') + ':cwd=/'])
        self.assertFalse(self.first.exists())
        self.assertTrue(self.second.exists())
        self.assertNotIn('--force', '\n'.join(self.events))
        self.assertIn('--canonicalize --evaluate --nofsroot', self.events[0])

    def test_poweroff_syncs_all_volumes_before_unmounting_and_powering_off(self):
        result = self.run_action('--power-off-path')
        self.assertEqual(result.returncode, 0, result.stderr)
        operations = [e for e in self.events if e.startswith(('sync:', 'udisks:'))]
        self.assertEqual(len(operations), 5, operations)
        self.assertTrue(all(e.startswith('sync:') for e in operations[:2]))
        self.assertTrue(all(e.startswith('udisks:unmount') for e in operations[2:4]))
        self.assertEqual(operations[4],
                         'udisks:power-off --block-device ' + str(self.dev / 'sdb') + ':cwd=/')
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())

    def test_native_device_unmount_uses_the_same_sync_and_verified_udisks_flow(self):
        result = self.run_action('--unmount-device', path=self.dev / 'sdb1')
        self.assertEqual(result.returncode, 0, result.stderr)
        operations = [e for e in self.events if e.startswith(('sync:', 'udisks:'))]
        self.assertEqual(operations, [
            'sync:--file-system -- ' + str(self.folder),
            'udisks:unmount --block-device ' + str(self.dev / 'sdb1') + ':cwd=/'])
        self.assertFalse(self.first.exists())
        self.assertTrue(self.second.exists())
        self.assertFalse(any(e.startswith('findmnt:') for e in self.events))

    def test_native_eject_needs_no_second_picker_and_syncs_all_volumes_first(self):
        result = self.run_action('--power-off-device', path=self.dev / 'sdb', mode='cancel')
        self.assertEqual(result.returncode, 0, result.stderr)
        operations = [e for e in self.events if e.startswith(('sync:', 'udisks:'))]
        self.assertEqual(len(operations), 5, operations)
        self.assertTrue(all(e.startswith('sync:') for e in operations[:2]))
        self.assertTrue(all(e.startswith('udisks:unmount') for e in operations[2:4]))
        self.assertIn('power-off --block-device ' + str(self.dev / 'sdb'), operations[4])

    def test_native_removal_failure_or_internal_device_never_bypasses_the_worker(self):
        for mode, transport in (('sync-failure', 'usb'), ('busy', 'usb'),
                                ('lingering', 'usb'), ('success', 'sata')):
            with self.subTest(mode=mode, transport=transport):
                result = self.run_action('--power-off-device', path=self.dev / 'sdb',
                                         mode=mode, transport=transport)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any('power-off --block-device' in e for e in self.events))
                self.assertNotIn('--force', '\n'.join(self.events))

    def test_native_device_path_rejects_traversal_before_inventory_or_sync(self):
        result = self.run_action('--unmount-device', path=self.dev / '..' / 'sdb1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(e.startswith(('sync:', 'udisks:')) for e in self.events))

    def test_native_eject_rejects_usb_system_swap_and_mapped_storage_before_sync(self):
        for mode in ('system-disk', 'active-swap', 'mapped-data'):
            with self.subTest(mode=mode):
                result = self.run_action('--power-off-device', path=self.dev / 'sdb', mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('removal rejected', result.stderr)
                self.assertFalse(any(e.startswith(('sync:', 'udisks:')) for e in self.events))

    def test_failed_sync_keeps_every_volume_mounted_and_does_not_power_off(self):
        for operation in ('--unmount-path', '--power-off-path'):
            with self.subTest(operation=operation):
                result = self.run_action(operation, mode='sync-failure')
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(e.startswith('udisks:') for e in self.events))
                self.assertTrue(self.first.exists())
                self.assertTrue(self.second.exists())

    def test_busy_or_unconfirmed_volume_prevents_poweroff(self):
        for mode in ('busy', 'lingering'):
            with self.subTest(mode=mode):
                result = self.run_action('--power-off-path', mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(self.first.exists())
                self.assertFalse(any('power-off --block-device' in e for e in self.events))
                self.assertNotIn('--force', '\n'.join(self.events))

    def test_changed_disk_identity_is_retained_through_nested_volume_validation(self):
        result = self.run_action('--power-off-path', mode='race')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('disk identity changed', result.stderr)
        self.assertFalse(any('power-off --block-device' in e for e in self.events))

    def test_cancel_does_not_sync_or_mutate_the_drive(self):
        result = self.run_action('--power-off-path', mode='cancel')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(e.startswith(('sync:', 'udisks:')) for e in self.events))

    def test_internal_drive_and_invalid_path_operations_are_rejected(self):
        for operation, path, transport in (
                ('--unmount-path', self.folder, 'sata'),
                ('--power-off-path', self.folder, 'sata'),
                ('--invalid', self.folder, 'usb'),
                ('--unmount-path', Path('relative'), 'usb')):
            with self.subTest(operation=operation, path=path, transport=transport):
                result = self.run_action(operation, transport=transport, path=path)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(e.startswith(('sync:', 'udisks:')) for e in self.events))

    def test_shutdown_reuses_the_confirmed_backend_without_a_picker(self):
        result = self.run_action('--fixture-shutdown', mode='cancel')
        self.assertEqual(result.returncode, 0, result.stderr)
        operations = [e for e in self.events if e.startswith(('sync:', 'udisks:'))]
        self.assertEqual(len(operations), 5, operations)
        self.assertTrue(all(e.startswith('sync:') for e in operations[:2]))
        self.assertIn('udisks:power-off --block-device ' + str(self.dev / 'sdb'), operations[-1])

    def test_shutdown_without_external_usb_disks_is_a_noop(self):
        result = self.run_action('--fixture-shutdown', transport='sata')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(e.startswith(('sync:', 'udisks:')) for e in self.events))

    def test_usb_system_disk_is_kept_even_with_an_encrypted_descendant(self):
        result = self.run_action('--fixture-shutdown', mode='system-disk')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Keeping USB system disk available', result.stdout)
        self.assertFalse(any(e.startswith(('sync:', 'udisks:')) for e in self.events))

    def test_external_active_swap_vetoes_shutdown_preparation(self):
        result = self.run_action('--fixture-shutdown', mode='active-swap')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('active swap', result.stderr)
        self.assertFalse(any(e.startswith(('sync:', 'udisks:')) for e in self.events))

    def test_mapped_external_data_is_not_silently_skipped_before_poweroff(self):
        result = self.run_action('--fixture-shutdown', mode='mapped-data')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('open encrypted/LVM/RAID mapping', result.stderr)
        self.assertFalse(any(e.startswith(('sync:', 'udisks:')) for e in self.events))

    def test_shutdown_failure_does_not_power_off_the_busy_disk(self):
        for mode in ('sync-failure', 'busy', 'lingering', 'race'):
            with self.subTest(mode=mode):
                result = self.run_action('--fixture-shutdown', mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any('power-off --block-device' in e for e in self.events))

    @unittest.skipIf(os.geteuid() == 0, 'run the direct root-mode refusal check as an unprivileged user')
    def test_unprivileged_caller_cannot_enter_shutdown_mode(self):
        result = subprocess.run(
            ['/bin/dash', str(TARGET / 'usr/local/bin/labwc-external-drives.tmpl'),
             '--prepare-shutdown'], capture_output=True, text=True, encoding='utf-8', timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires the authorized root service', result.stderr)

    def test_termination_cleans_runtime_and_does_not_continue_drive_work(self):
        source = payload_read_text(TARGET / 'usr/local/bin/labwc-external-drives')
        cleanup = source[source.index('cleanup() {\n'):].split(
            '\nif [ "$requested_operation" = shutdown ]; then', 1)[0]
        runtime = self.root / 'signal-runtime'
        runtime.mkdir()
        (runtime / 'lsblk.snapshot').touch()
        (runtime / 'records.map').touch()
        script = self.root / 'signal.sh'
        script.write_text('set -eu\ntemp_dir=$1\nsnapshot_file=$1/lsblk.snapshot\n'
                          'map_file=$1/records.map\n' + cleanup +
                          '\nkill -s TERM "$$"\nprintf "unexpected continuation\\n"\n')
        result = subprocess.run(['/bin/dash', str(script), str(runtime)],
                                capture_output=True, text=True, encoding='utf-8', timeout=5)
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertNotIn('unexpected continuation', result.stdout)
        self.assertFalse(runtime.exists())


class TutaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tuta-integration-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.config/tutanota-desktop').mkdir(parents=True)
        (self.home / '.local/share/applications').mkdir(parents=True)
        self.mime = self.home / '.config/mimeapps.list'
        self.mime.write_text('[Default Applications]\nx-scheme-handler/mailto=tutanota-desktop.desktop;\n')
        self.desktop = self.home / '.local/share/applications/tutanota-desktop.desktop'
        self.desktop.write_text('[Desktop Entry]\nType=Application\nExec=labwc-app launch tutanota %U\n')
        self.account = self.home / '.config/tutanota-desktop/account-state'
        self.account.write_text('account data must survive')
        self.private = self.home / '.local/state/tutanota-desktop/desktop-integration'

    def prepare(self):
        sandbox.prepare_tuta_integration(str(self.home))

    def test_persistent_private_seed_is_idempotent_and_host_is_unchanged(self):
        self.prepare()
        self.assertEqual(payload_read_bytes(self.private / 'config/mimeapps.list'), payload_read_bytes(self.mime))
        (self.private / 'applications/tutanota-desktop.desktop').write_text('Tuta-owned integration')
        (self.private / 'config/tuta_integration').mkdir()
        remember = self.private / 'config/tuta_integration/no_integration'
        remember.write_text('remembered application state')
        self.prepare()
        self.assertEqual(payload_read_text(remember), 'remembered application state')
        self.assertEqual(payload_read_text(self.private / 'applications/tutanota-desktop.desktop'), 'Tuta-owned integration')
        self.assertIn('labwc-app', payload_read_text(self.desktop))
        self.assertEqual(payload_read_text(self.account), 'account data must survive')

    def test_mime_file_can_be_atomically_replaced(self):
        self.prepare()
        temporary = self.private / 'config/mimeapps.list.new'
        temporary.write_text('new private MIME state')
        os.replace(temporary, self.private / 'config/mimeapps.list')
        self.assertEqual(payload_read_text(self.private / 'config/mimeapps.list'), 'new private MIME state')
        self.assertIn('[Default Applications]', payload_read_text(self.mime))

    def test_destination_symlink_is_not_followed(self):
        self.prepare()
        destination = self.private / 'applications/tutanota-desktop.desktop'
        destination.unlink()
        destination.symlink_to(self.desktop)
        with self.assertRaises((SystemExit, OSError)):
            self.prepare()
        self.assertIn('labwc-app', payload_read_text(self.desktop))

    def test_seed_symlink_is_rejected(self):
        self.mime.unlink()
        self.mime.symlink_to(self.account)
        with self.assertRaises(SystemExit):
            self.prepare()
        self.assertEqual(payload_read_text(self.account), 'account data must survive')

    def test_absent_seed_is_not_replaced_with_invalid_empty_desktop(self):
        self.desktop.unlink()
        self.prepare()
        self.assertFalse(payload_source_exists(self.private / 'applications/tutanota-desktop.desktop'))

    def test_private_directories_and_seed_modes(self):
        self.prepare()
        for source, _destination in profiles.TUTA_INTEGRATION_DIRECTORY_BINDS:
            self.assertEqual(stat.S_IMODE(payload_source_stat(self.home / source).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.private / 'config/mimeapps.list').st_mode), 0o600)

    def test_mount_order_does_not_hide_account_state_or_bind_host_mime_inode(self):
        config = profiles.PERSISTENT_SANDBOX_CONFIG['tutanota']
        self.assertEqual(config['integration_directory_binds'][0][1], '.config')
        self.assertIn('.config/tutanota-desktop', config['persistent_paths'])
        self.assertNotIn('.config/mimeapps.list', config['ro_bind_home_paths'])
        self.assertNotIn('.local/share/applications/tutanota-desktop.desktop', config['ro_bind_home_paths'])
        source = payload_read_text(PACKAGE / 'labwc_managed_app/sandbox.py')
        self.assertLess(source.index('sandbox.get("integration_directory_binds"'),
                        source.index('for directory in persistent_directories:'))

    def test_shared_ipc_directory_is_stable_private_and_rejects_symlinks(self):
        name = profiles.PERSISTENT_SANDBOX_CONFIG['tutanota']['shared_temp_directory']
        path = Path(sandbox.persistent_runtime_directory(str(self.home), name))
        (path / 'cookie').write_text('live singleton')
        self.assertEqual(sandbox.persistent_runtime_directory(str(self.home), name), str(path))
        self.assertEqual(payload_read_text(path / 'cookie'), 'live singleton')
        self.assertEqual(stat.S_IMODE(payload_source_stat(path).st_mode), 0o700)
        (self.home / 'bad').symlink_to(path, target_is_directory=True)
        with self.assertRaises(SystemExit):
            sandbox.persistent_runtime_directory(str(self.home), 'bad')


class MailDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.sync = load_script('labwc-sync-application-launchers')
        self.temp = tempfile.TemporaryDirectory(prefix='mail-defaults-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.config').mkdir()
        self.mime = self.home / '.config/mimeapps.list'

    def repair(self):
        return self.sync.synchronize_tuta_mime_defaults(str(self.home), os.getuid(), os.getgid())

    def test_repairs_only_mail_associations_preserving_other_choices_and_comments(self):
        self.mime.write_text('# keep this comment\n[Default Applications]\n'
            'text/plain=my-editor.desktop;\nx-scheme-handler/mailto=tuta-mail.desktop;\n'
            'message/rfc822=tuta-mail.desktop;\n[Removed Associations]\n'
            'x-scheme-handler/mailto=tuta-mail.desktop;other-mail.desktop;\n')
        self.assertTrue(self.repair())
        content = payload_read_text(self.mime)
        self.assertIn('# keep this comment', content)
        self.assertIn('text/plain=my-editor.desktop;', content)
        self.assertNotIn('message/rfc822', content)
        p = configparser.ConfigParser(interpolation=None)
        p.read_string(content)
        for section in ('Default Applications', 'Added Associations'):
            for scheme in self.sync.TUTA_SCHEMES:
                self.assertEqual(p[section][scheme], 'tutanota-desktop.desktop;')
        self.assertEqual(p['Removed Associations']['x-scheme-handler/mailto'], 'other-mail.desktop;')
        self.assertFalse(self.repair())

    def test_keeps_non_tuta_rfc822_handler(self):
        self.mime.write_text('[Default Applications]\nmessage/rfc822=other-mail.desktop;\n')
        self.repair()
        self.assertIn('message/rfc822=other-mail.desktop;', payload_read_text(self.mime))

    def test_missing_mime_file_created(self):
        self.assertTrue(self.repair())
        self.assertFalse(self.repair())
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.mime).st_mode), 0o600)

    def test_symlink_and_malformed_input_are_not_replaced(self):
        other = self.home / 'other'
        other.write_text('unchanged')
        self.mime.symlink_to(other)
        with self.assertRaises((RuntimeError, OSError)):
            self.repair()
        self.assertEqual(payload_read_text(other), 'unchanged')
        self.mime.unlink()
        self.mime.write_text('broken configuration without a section')
        with self.assertRaises(configparser.Error):
            self.repair()
        self.assertEqual(payload_read_text(self.mime), 'broken configuration without a section')

    def test_root_owned_rendered_seed_fallback_and_canonical_source_are_supported(self):
        source = self.home / 'seed.desktop'
        source.write_text('[Desktop Entry]\nName=Tuta Mail\n')
        with mock.patch.object(self.sync, 'SYSTEM_APPLICATION_DIR', str(self.home / 'missing')), \
             mock.patch.object(self.sync, 'TUTA_MANAGED_DESKTOP_SOURCE', str(source)):
            self.assertEqual(self.sync.find_desktop_file(('tutanota-desktop.desktop',)),
                             ('tutanota-desktop.desktop', str(source)))
            self.assertIsNone(self.sync.find_desktop_file(('unrelated.desktop',)))

    def test_seed_desktop_and_mime_defaults_use_the_same_supported_schemes(self):
        desktop = payload_read_text(TARGET / 'etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop')
        self.assertIn('MimeType=x-scheme-handler/mailto;x-scheme-handler/tuta;', desktop)
        self.assertIn('tutanota-desktop.desktop', payload_read_text(TARGET / 'etc/xdg/mimeapps.list'))
        self.assertNotIn('message/rfc822=tuta', payload_read_text(TARGET / 'etc/skel-desktop/.config/mimeapps.list'))


class ServiceAndNotificationTests(unittest.TestCase):
    def test_capture_tools_keep_host_namespaces_and_only_dumpcap_package_privileges(self):
        for executable in ('/usr/bin/wireshark', '/usr/bin/tshark', '/usr/bin/dumpcap'):
            with self.subTest(executable=executable), mock.patch.object(generic, 'assert_launch_allowed'):
                argv = generic.transient_argv('wayland', 'launch', [executable, '-D'], {})
                self.assertIsNone(generic.managed_network_command('launch', [executable]))
            for setting in ('PrivateUsers=no', 'PrivateNetwork=no', 'PrivateMounts=no',
                            'NoNewPrivileges=no', 'PartOf=labwc-session.target', 'KillMode=control-group'):
                self.assertIn('--property=' + setting, argv)
            for setting in ('PrivateTmp=yes', 'PrivateIPC=yes', 'ProtectSystem=full'):
                self.assertNotIn('--property=' + setting, argv)
            self.assertFalse(any('AmbientCapabilities=' in item or 'CapabilityBoundingSet=' in item
                                 for item in argv))
            self.assertEqual(argv[-2:], [executable, '-D'])

    def test_thunar_keeps_host_mounts_and_native_udisks_controls(self):
        for executable in ('/usr/bin/thunar', '/usr/bin/Thunar'):
            with self.subTest(executable=executable), mock.patch.object(generic, 'assert_launch_allowed'):
                env = {'GIO_USE_VFS': 'local', 'GIO_USE_VOLUME_MONITOR': 'unix'}
                argv = generic.transient_argv('wayland', 'launch', [executable, '/run/media/fixture'], env)
            self.assertEqual(env['GIO_USE_VFS'], 'gvfs')
            self.assertEqual(env['GIO_USE_VOLUME_MONITOR'], 'GProxyVolumeMonitorLabwc')
            for setting in ('PrivateUsers=no', 'PrivatePIDs=no', 'PrivateMounts=no',
                            'Wants=gvfs-daemon.service',
                            'Requires=labwc-gvfs-volume-monitor.service thunar.service',
                            'After=labwc-session.target gvfs-daemon.service labwc-gvfs-volume-monitor.service thunar.service',
                            'PartOf=labwc-session.target'):
                self.assertIn('--property=' + setting, argv)
            for setting in ('PrivateTmp=yes', 'PrivateIPC=yes', 'ProtectSystem=full'):
                self.assertNotIn('--property=' + setting, argv)
            self.assertIn('--setenv=GIO_USE_VFS', argv)
            self.assertIn('--setenv=GIO_USE_VOLUME_MONITOR', argv)
            self.assertEqual(argv[-2:], [executable, '/run/media/fixture'])
        target = payload_read_text(TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-session.target')
        self.assertIn('Wants=gvfs-daemon.service gvfs-udisks2-volume-monitor.service', target)

    def test_other_wayland_applications_keep_their_existing_namespace_policy(self):
        with mock.patch.object(generic, 'assert_launch_allowed'):
            env = {}
            argv = generic.transient_argv('wayland', 'launch', ['/usr/bin/qimgv'], env)
        self.assertIn('--property=PrivateTmp=yes', argv)
        self.assertIn('--property=PrivateIPC=yes', argv)
        self.assertIn('--property=ProtectSystem=full', argv)
        self.assertNotIn('GIO_USE_VOLUME_MONITOR', env)

    def test_menu_wait_is_opt_in_and_does_not_attach_output_pipes(self):
        for marker in ('', '0', '1', 'yes'):
            with self.subTest(marker=marker), mock.patch.dict(os.environ, {'LABWC_MENU_ACTION_WAIT': marker}, clear=True), \
                 mock.patch.object(generic, 'assert_launch_allowed'):
                argv = generic.transient_argv('wayland', 'launch', ['/usr/bin/foot'], {})
                self.assertEqual('--wait' in argv, marker == '1')
                self.assertNotIn('--pipe', argv)
                self.assertIn('--property=ExitType=main', argv)
                self.assertTrue(any(arg.startswith('--property=UnsetEnvironment=') and
                                    'LABWC_MENU_ACTION_WAIT' in arg for arg in argv))
                self.assertFalse(any(arg.startswith('--setenv=LABWC_MENU_ACTION_WAIT') for arg in argv))

    def test_native_tuta_waits_for_service_exit_but_still_uses_secret_service_and_journal(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {'LABWC_MENU_ACTION_WAIT':'1','WAYLAND_DISPLAY':'wayland-1'}, clear=True))
            stack.enter_context(mock.patch.object(session, '_consume_session_marker', return_value=False))
            stack.enter_context(mock.patch.object(session, 'system_owner', return_value=(0,0)))
            stack.enter_context(mock.patch.object(session, 'assert_launch_allowed'))
            stack.enter_context(mock.patch.object(session, 'require_root_owned_executable', return_value='/usr/bin/systemd-run'))
            stack.enter_context(mock.patch.object(session, 'current_user_runtime_socket'))
            stack.enter_context(mock.patch.object(session, 'managed_session_unit_environment', return_value={'HOME':'/home/test'}))
            execute = stack.enter_context(mock.patch.object(session.os, 'execve'))
            session.redirect_native_from_private_users('tutanota', 'launch', ['mailto:a@example.invalid'])
        argv = execute.call_args.args[1]
        self.assertIn('--wait', argv)
        self.assertNotIn('--pipe', argv)
        self.assertIn('--property=After=labwc-session.target labwc-kwallet-portal.service', argv)
        self.assertIn('--property=UnsetEnvironment=LABWC_MENU_ACTION_WAIT', argv)
        self.assertEqual(argv[-1], 'mailto:a@example.invalid')
        for property_value in ('ExitType=main', 'KillMode=control-group', 'TimeoutStopSec=20s', 'SendSIGKILL=yes'):
            self.assertIn('--property=' + property_value, argv)

    def test_bitwarden_and_every_future_native_launcher_keep_main_owned_cleanup(self):
        with mock.patch.object(session, 'assert_launch_allowed'):
            argv = session.bitwarden_session_unit_argv('/usr/bin/systemd-run', 'launch', [])
        self.assertIn('--property=ExitType=main', argv)
        self.assertIn('--property=KillMode=control-group', argv)
        for app in (*profiles.APPS.keys(), 'future-native-app'):
            if app in profiles.WAYLAND_COMPAT_APPS or app == 'bitwarden':
                continue
            with self.subTest(app=app), ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-1'}, clear=True))
                stack.enter_context(mock.patch.object(session, '_consume_session_marker', return_value=False))
                stack.enter_context(mock.patch.object(session, 'system_owner', return_value=(0, 0)))
                stack.enter_context(mock.patch.object(session, 'assert_launch_allowed'))
                stack.enter_context(mock.patch.object(session, 'require_root_owned_executable', return_value='/usr/bin/systemd-run'))
                stack.enter_context(mock.patch.object(session, 'current_user_runtime_socket'))
                stack.enter_context(mock.patch.object(session, 'managed_session_unit_environment', return_value={'HOME': '/home/test'}))
                execute = stack.enter_context(mock.patch.object(session.os, 'execve'))
                session.redirect_native_from_private_users(app, 'launch', [])
            argv = execute.call_args.args[1]
            for property_value in ('ExitType=main', 'KillMode=control-group', 'TimeoutStopSec=20s', 'SendSIGKILL=yes'):
                self.assertIn('--property=' + property_value, argv)

    def test_activation_token_is_opaque_bounded_and_not_saved_as_restore_argument(self):
        with mock.patch.dict(os.environ, {'XDG_ACTIVATION_TOKEN':'opaque-token'}, clear=True):
            self.assertEqual(environment.desktop_activation_environment(), {'XDG_ACTIVATION_TOKEN':'opaque-token'})
        for token in ('bad\ntoken', 'a'*4097):
            with mock.patch.dict(os.environ, {'XDG_ACTIVATION_TOKEN':token}, clear=True), self.assertRaises(SystemExit):
                environment.desktop_activation_environment()
        self.assertIn('environment.update(desktop_activation_environment())',
                      payload_read_text(PACKAGE / 'labwc_managed_app/session.py'))
        self.assertIn('env: dict[str, str] = desktop_activation_environment()',
                      payload_read_text(PACKAGE / 'labwc_managed_app/environment.py'))

    def test_every_session_proxy_keeps_notifications_and_tuta_can_reach_tray(self):
        runtime = types.SimpleNamespace(validate_session_bus_address=lambda x:x)
        for extra in ((), profiles.TUTA_DBUS_NAMES):
            with mock.patch.dict(os.environ, {'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus'}), \
                 mock.patch.object(dbus_proxy,'start_filtered_dbus_proxy',return_value=(None,None,None)) as start:
                dbus_proxy.start_session_bus_proxy('/fixture',extra,runtime=runtime)
                policy = start.call_args.args[3]
                self.assertIn('--talk=org.freedesktop.Notifications', policy)
                self.assertNotIn('--talk=*',policy)
                self.assertNotIn('--own=org.freedesktop.Notifications',policy)
        self.assertIn('org.kde.StatusNotifierWatcher', profiles.TUTA_DBUS_NAMES)

    def test_mako_invokes_client_callback_instead_of_launching_a_new_generic_mail_window(self):
        config=payload_read_text(TARGET/'etc/skel-desktop/.config/mako/config')
        for setting in ('actions=1','on-button-left=invoke-default-action','on-touch=invoke-default-action',
                        '[desktop-entry=tutanota-desktop]\ngroup-by=none'):
            self.assertIn(setting,config)
        self.assertNotIn('exec labwc-tutanota',config)

    def test_remote_and_podman_terminal_helpers_wait_and_remote_returns_to_submenu(self):
        remote=load_script('labwc-remote-desktop')
        with mock.patch.object(remote.shutil,'which',return_value='/fixture/labwc-terminal'), \
             mock.patch.object(remote,'current_script_path',return_value=Path('/fixture/remote')), \
             mock.patch.object(remote.subprocess,'run') as run:
            remote.show_help()
        self.assertEqual(run.call_args.kwargs['env']['LABWC_MENU_ACTION_WAIT'],'1')
        with mock.patch.object(remote,'run_fuzzel',side_effect=['Show FreeRDP Help',None]), \
             mock.patch.object(remote,'show_help') as help_action:
            self.assertTrue(remote.main_menu())
            self.assertFalse(remote.main_menu())
            help_action.assert_called_once()
        source=payload_read_text(TARGET/'usr/local/bin/labwc-podman-menu')
        self.assertIn("subprocess.run([TERMINAL",source)
        self.assertIn("'LABWC_MENU_ACTION_WAIT': '1'",source)

    def test_remote_profile_folder_no_longer_detaches(self):
        remote = load_script('labwc-remote-desktop')
        with mock.patch.object(remote, 'profile_store_path', return_value=Path('/fixture/profiles/connections.json')), \
             mock.patch.object(remote, 'ensure_profile_directory'), \
             mock.patch.object(remote.shutil, 'which', return_value='/usr/bin/thunar'), \
             mock.patch.object(remote.subprocess, 'run') as run:
            remote.open_profile_directory()
        self.assertEqual(run.call_args.args[0], [
            '/usr/local/bin/labwc-wayland-app', 'auto', '--',
            '/usr/bin/thunar', '/fixture/profiles'])
        self.assertEqual(run.call_args.kwargs['env']['LABWC_MENU_ACTION_WAIT'], '1')

    def test_wireshark_waits_for_setsids_child(self):
        source = payload_read_text(TARGET/'usr/local/lib/perl5/site_perl/labwc-network-scan-action/LabwcNetworkScanAction/Client.pm')
        block = source.split('sub _run_wireshark_action {', 1)[1].split('sub _run_privileged_action', 1)[0]
        self.assertEqual(block.count("run($setsid, '-f', '--wait', $wireshark"), 2)
        self.assertIn("local $ENV{LABWC_MENU_ACTION_WAIT} = '1';", block)
        # Exercise util-linux process lifetime/exit propagation, without a GUI.
        result = subprocess.run(payload_installed_argv(['setsid', '-f', '--wait', '/bin/sh', '-c', 'exit 7']), check=False)
        self.assertEqual(result.returncode, 7)


class PolicyCoverageTests(unittest.TestCase):
    def test_terminal_grants_include_privileged_workers_without_owner_restriction(self):
        rule=payload_read_text(TARGET/'etc/apparmor.d/abstractions/wrapper-terminal')
        self.assertIn('\n/dev/pts/[0-9]* rw,',rule)
        self.assertNotIn('\nowner /dev/pts/',rule)
        text=payload_read_text(TARGET/'etc/apparmor.d/desktop-wrappers')
        for name in re.findall(r'^profile (labwc-[\w-]*action(?:-root|-worker)?) ',text,re.M):
            block=text.split('profile '+name+' ',1)[1].split('\nprofile ',1)[0]
            self.assertIn('#include <abstractions/wrapper-terminal>',block,name)
        self.assertIn('etc/apparmor.d/abstractions/wrapper-terminal',
                      payload_read_text(FORKY/'scripts/late/security.sh'))

    def test_readonly_process_inspection_is_bilateral(self):
        text=payload_read_text(TARGET/'etc/apparmor.d/system-wrappers') + payload_read_text(FORKY/'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl')
        self.assertIn('ptrace (read) peer=crowdsec-firstboot,',text)
        self.assertIn('ptrace (readby) peer=firstboot,',text)
        self.assertNotIn('ptrace (trace) peer=crowdsec-firstboot,',text)

    def test_ncdu_fix_is_directory_only_in_existing_file_manager_domain(self):
        text=payload_read_text(TARGET/'etc/apparmor.d/desktop-utilities')
        block=text.split('profile desktop-launcher ',1)[1].split('\nprofile ',1)[0]
        self.assertIn('\n  /**/ r,',block)
        self.assertNotIn('\n  /** r,',block)
        self.assertNotIn('\n  /** rw',block)

    def test_tuta_ipc_path_is_allowed_outside_and_inside_bubblewrap(self):
        text=payload_read_text(TARGET/'etc/apparmor.d/desktop-wrappers')
        block=text.split('profile labwc-app ',1)[1].split('\nprofile ',1)[0]
        self.assertEqual(block.count('owner /run/user/[0-9]*/labwc-tutanota-tmp/{,**} rwkl,'),2)


class MenuRoundTripTests(unittest.TestCase):
    def test_actual_menu_waits_for_action_and_returns_to_same_security_entries(self):
        with tempfile.TemporaryDirectory(prefix='menu-roundtrip-') as name:
            root=Path(name);bin_dir=root/'bin';bin_dir.mkdir()
            queue=root/'queue.json';events=root/'events.jsonl'
            choices=['Security & Accounts', 'Protection & Firewall', '\u2b9e Security Auditing',
                     'Check Firmware Security', '\u2190 Back', '\u2190 Back', 'Back', 'Exit']
            queue.write_text(json.dumps(choices))
            def executable(name,content):
                p=bin_dir/name;p.write_text(content);p.chmod(0o755)
            executable('id','#!/bin/sh\nprintf "1000\\n"\n')
            executable('ip','#!/bin/sh\nexit 0\n')
            executable('systemctl','#!/bin/sh\nexit 0\n')
            executable('labwc-fuzzel','''#!/usr/bin/python3
import json,os,pathlib,sys
root=pathlib.Path(os.environ['MENU_TEST_ROOT'])
q=root/'queue.json'; choices=json.loads(q.read_text()); choice=choices.pop(0);q.write_text(json.dumps(choices))
items=sys.stdin.read();prompt=sys.argv[sys.argv.index('--prompt')+1]
assert choice in items, (choice,items)
with (root/'events.jsonl').open('a') as f:f.write(json.dumps(['menu',prompt,items])+'\\n')
print(choice)
''')
            executable('labwc-security-action','''#!/usr/bin/python3
import json,os,pathlib,time
assert os.environ.get('LABWC_MENU_ACTION_WAIT')=='1'
p=pathlib.Path(os.environ['MENU_TEST_ROOT'])/'events.jsonl'
with p.open('a') as f:f.write(json.dumps(['action-start'])+'\\n')
time.sleep(.08)
with p.open('a') as f:f.write(json.dumps(['action-finished'])+'\\n')
raise SystemExit(7)
''')
            (bin_dir/'labwc-maintenance-menu').symlink_to(TARGET/'usr/local/bin/labwc-maintenance-menu')
            # The requested terminal UI now owns navigation; keep the real
            # maintenance subprocess and asynchronous action fixture so this
            # still proves wait/return behavior, not only static menu strings.
            menu = load_script('labwc-computer-management')
            menu.PICKER = str(bin_dir / 'labwc-fuzzel')
            outcomes = []
            def action(arguments):
                self.assertEqual(arguments, ('labwc-maintenance-menu', 'security'))
                result = subprocess.run(payload_installed_argv(['/bin/sh', str(TARGET/'usr/local/bin/labwc-maintenance-menu'), 'security']),
                                        capture_output=True, text=True, timeout=10)
                outcomes.append(result)
                return result.returncode
            with mock.patch.dict(os.environ, {'PATH':str(bin_dir)+':/usr/bin:/bin',
                    'MENU_TEST_ROOT':str(root), 'LABWC_DESKTOP_DEFAULTS_FILE':str(root/'absent')}), \
                    mock.patch.object(menu, 'run_action', side_effect=action):
                self.assertEqual(menu.run_menu(), 0)
            self.assertEqual(len(outcomes), 1)
            self.assertEqual(outcomes[0].returncode, 0, outcomes[0].stderr)
            rows=[json.loads(line) for line in payload_read_text(events).splitlines()]
            self.assertEqual([row[0] for row in rows], ['menu']*4 + ['action-start','action-finished'] + ['menu']*4)
            self.assertEqual(rows[3][1:], rows[6][1:])
            self.assertIn('returned status 7', outcomes[0].stderr)
            self.assertEqual(json.loads(payload_read_text(queue)),[])


    def test_terminal_menu_preserves_original_choice_data_and_rejects_free_text(self):
        # Graphical sizing retries no longer apply to the full-screen terminal
        # UI. The equivalent invariant is exact-choice data round-tripping.
        menu = load_script('labwc-computer-management')
        choices = ['Network & Remote', 'Files & Documents']
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(
                returncode=0, stdout='Files & Documents\n')) as run:
            self.assertEqual(menu.choose(choices, 'Computer Management'), choices[1])
            self.assertEqual(run.call_args.kwargs['input'], '\n'.join(choices) + '\n')
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(
                returncode=0, stdout='$(touch /not-an-action)\n')):
            self.assertIsNone(menu.choose(choices, 'Computer Management'))


if __name__ == '__main__':
    unittest.main()
