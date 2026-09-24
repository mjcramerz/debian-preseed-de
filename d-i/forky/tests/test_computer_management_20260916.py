"""Launcher regressions. No real bootloader, service, GUI or policy is modified."""
from __future__ import annotations
from payload_fixture import source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'

def load(relative):
    path = TARGET / relative
    module = types.ModuleType('test_' + path.name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(payload_read_bytes(path), str(path), 'exec'), module.__dict__)
    return module

BOOT = load('usr/local/libexec/labwc-apparmor-boot-state')
REMOTE = load('usr/local/bin/labwc-remote-desktop')
PODMAN = load('usr/local/bin/labwc-podman-menu')
FRAGMENT = b'# managed\nGRUB_CMDLINE_LINUX="${GRUB_CMDLINE_LINUX:+$GRUB_CMDLINE_LINUX }apparmor=1 lsm=landlock,lockdown,yama,integrity,apparmor,bpf audit=1"\n'
GRUB_ON = b'menuentry Debian {\n linux /vmlinuz root=UUID=test apparmor=1 quiet\n initrd /initrd\n}\n'
GRUB_OFF = GRUB_ON.replace(b'apparmor=1', b'apparmor=0')

class BootSyntaxTests(unittest.TestCase):
    def test_change_only_one_managed_flag_and_preserve_lsm_order(self):
        off = BOOT.requested_fragment(FRAGMENT, False)
        self.assertEqual(off, FRAGMENT.replace(b'apparmor=1', b'apparmor=0'))
        self.assertEqual(BOOT.requested_fragment(off, True), FRAGMENT)

    def test_refuse_shell_code_duplicate_missing_or_ambiguous_flags(self):
        for content in [FRAGMENT + b'touch /tmp/evil\n',
                        FRAGMENT.replace(b' audit=1', b' apparmor=1'),
                        FRAGMENT.replace(b'apparmor=1 ', b''),
                        FRAGMENT.replace(b',apparmor,', b','),
                        FRAGMENT.replace(b'audit=1', b'$(touch /tmp/evil)'), b'', b'\xff']:
            with self.subTest(content=content), self.assertRaises(BOOT.PolicyError):
                BOOT.requested_fragment(content, False)

    def test_all_kernel_entries_must_agree(self):
        BOOT.validate_grub(GRUB_ON + GRUB_ON.replace(b'linux ', b'linuxefi '), True)
        for content in [GRUB_ON + GRUB_OFF, GRUB_ON.replace(b'apparmor=1', b''),
                        GRUB_ON.replace(b'apparmor=1', b'apparmor=1 apparmor=0'), b'# no kernels\n']:
            with self.subTest(content=content), self.assertRaises(BOOT.PolicyError):
                BOOT.validate_grub(content, True)

    def test_strict_root_and_action_gate(self):
        with mock.patch.object(BOOT.os, 'getuid', return_value=1000):
            with self.assertRaises(BOOT.PolicyError): BOOT.main(['disable'])
        with mock.patch.object(BOOT.os, 'getuid', return_value=0), mock.patch.object(BOOT.os, 'geteuid', return_value=0):
            for args in [[], ['disable', '/tmp/x'], ['disable;reboot'], ['reload']]:
                with self.subTest(args=args), self.assertRaises(BOOT.PolicyError): BOOT.main(args)

@unittest.skipUnless(os.geteuid() == 0, 'real root-owned filesystem fixtures required')
class BootTransactionTests(unittest.TestCase):
    def setUp(self):
        # /tmp and /mnt/data are intentionally not trusted root-only ancestors.
        self.tmp = tempfile.TemporaryDirectory(prefix='labwc-boot-test-', dir='/root')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fragment = self.root / 'security.cfg'
        self.grub = self.root / 'grub.cfg'
        self.fragment.write_bytes(FRAGMENT); self.grub.write_bytes(GRUB_ON)
        self.state = BOOT.BootState(self.fragment, self.grub, self.root)
        self.command = mock.patch.object(BOOT, 'run_bounded', side_effect=self.run_tool).start()
        self.addCleanup(mock.patch.stopall)
        self.output = contextlib.redirect_stdout(io.StringIO()); self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def run_tool(self, argv, **kwargs):
        if argv == ['/usr/sbin/grub-mkconfig']:
            return GRUB_OFF if b'apparmor=0' in payload_read_bytes(self.fragment) else GRUB_ON
        self.assertEqual(argv[0], '/usr/bin/grub-script-check')
        self.assertTrue(Path(argv[1]).is_relative_to(self.root))
        return b''

    def old_pair(self):
        self.assertEqual(payload_read_bytes(self.fragment), FRAGMENT)
        self.assertEqual(payload_read_bytes(self.grub), GRUB_ON)

    def test_disable_enable_and_idempotence(self):
        self.state.stage(False)
        self.assertEqual(payload_read_bytes(self.grub), GRUB_OFF)
        self.assertFalse(payload_source_exists(self.state.journal))
        count = self.command.call_count
        self.state.stage(False); self.assertEqual(self.command.call_count, count)
        self.state.stage(True); self.old_pair()

    def test_no_op_does_not_run_grub_tools(self):
        self.state.stage(True); self.command.assert_not_called(); self.old_pair()

    def test_generator_and_checker_failure_restore_both_files(self):
        for failure in ('generate', 'check'):
            def tool(argv, **kwargs):
                if failure == 'generate' or argv[0].endswith('grub-script-check'):
                    raise BOOT.PolicyError('injected tool failure')
                return GRUB_OFF
            with self.subTest(failure=failure):
                self.command.side_effect = tool
                with self.assertRaises(BOOT.PolicyError): self.state.stage(False)
                self.old_pair(); self.assertFalse(payload_source_exists(self.state.journal))

    def test_invalid_generated_kernel_flags_never_publish(self):
        self.command.side_effect = lambda *a, **kw: GRUB_ON
        with self.assertRaises(BOOT.PolicyError): self.state.stage(False)
        self.old_pair()

    def test_publication_failure_rolls_back(self):
        original = BOOT.write_atomic
        once = [False]
        def failing(path, content, mode):
            if path == self.grub and content == GRUB_OFF and not once[0]:
                once[0] = True; raise OSError('injected disk failure')
            return original(path, content, mode)
        with mock.patch.object(BOOT, 'write_atomic', side_effect=failing):
            with self.assertRaises(OSError): self.state.stage(False)
        self.old_pair()

    def test_commit_journal_failure_rolls_back_published_pair(self):
        record = self.state.record
        def failing(transaction):
            if transaction['committed']: raise OSError('injected fsync failure')
            record(transaction)
        with mock.patch.object(self.state, 'record', side_effect=failing):
            with self.assertRaises(OSError): self.state.stage(False)
        self.old_pair()

    def test_external_root_changes_are_not_overwritten(self):
        def changing(argv, **kwargs):
            self.grub.write_bytes(b'changed externally\n')
            return GRUB_OFF
        self.command.side_effect = changing
        with self.assertRaisesRegex(BOOT.PolicyError, 'recovery also failed'):
            self.state.stage(False)
        self.assertEqual(payload_read_bytes(self.grub), b'changed externally\n')
        self.assertTrue(payload_source_exists(self.state.journal))

    def test_interrupted_transaction_is_recovered_on_next_invocation(self):
        transaction = dict(version=1, committed=False, fragment_mode=0o644, grub_mode=0o644,
                           old_fragment=base64.b64encode(FRAGMENT).decode(),
                           new_fragment=base64.b64encode(FRAGMENT.replace(b'apparmor=1', b'apparmor=0')).decode(),
                           old_grub=base64.b64encode(GRUB_ON).decode(), new_grub=base64.b64encode(GRUB_OFF).decode())
        self.state.record(transaction)
        self.fragment.write_bytes(FRAGMENT.replace(b'apparmor=1', b'apparmor=0'))
        self.grub.write_bytes(GRUB_OFF)
        self.state.recover(); self.old_pair(); self.assertFalse(payload_source_exists(self.state.journal))

    def test_hardlinks_symlinks_and_writable_files_are_rejected(self):
        link = self.root / 'link'; os.link(self.fragment, link)
        with self.assertRaises(BOOT.PolicyError): BOOT.read_file(self.fragment, 65536)
        link.unlink(); link.symlink_to(self.fragment)
        with self.assertRaises(OSError): BOOT.read_file(link, 65536)
        self.fragment.chmod(0o666)
        with self.assertRaises(BOOT.PolicyError): BOOT.read_file(self.fragment, 65536)

    def test_symlink_ancestor_and_non_root_parent_are_rejected(self):
        link = self.root / 'directory'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(BOOT.PolicyError): BOOT.read_file(link / 'security.cfg', 65536)
        with self.assertRaises(BOOT.PolicyError): BOOT.trusted_directory(Path('/tmp'))

    def test_corrupt_journal_is_preserved_for_manual_review(self):
        self.state.journal.write_text('{bad')
        with self.assertRaises(BOOT.PolicyError): self.state.recover()
        self.assertTrue(payload_source_exists(self.state.journal)); self.old_pair()

    def test_file_modes_are_preserved(self):
        self.fragment.chmod(0o640); self.grub.chmod(0o600)
        self.state.stage(False)
        self.assertEqual(payload_source_stat(self.fragment).st_mode & 0o777, 0o640)
        self.assertEqual(payload_source_stat(self.grub).st_mode & 0o777, 0o600)

class PodmanQueryTests(unittest.TestCase):
    def test_success_and_nonzero_status(self):
        self.assertEqual(PODMAN.execute([sys.executable, '-c', 'print("ok")']), 'ok\n')
        with self.assertRaisesRegex(RuntimeError, 'exited 3'):
            PODMAN.execute([sys.executable, '-c', 'raise SystemExit(3)'])

    def test_capture_is_bounded(self):
        with self.assertRaisesRegex(RuntimeError, '16 MiB'):
            PODMAN.execute([sys.executable, '-c', 'import os; os.write(1,b"x"*17000000)'])

    def test_timeout_includes_inherited_pipes_after_leader_exit(self):
        code = 'import os,time\nif os.fork() == 0: time.sleep(30)\nelse: os._exit(0)'
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            PODMAN.execute([sys.executable, '-c', code], timeout=0.3)
        self.assertLess(time.monotonic() - started, 4)

    def test_success_never_signals_a_reaped_group(self):
        with mock.patch.object(PODMAN.os, 'killpg') as kill:
            PODMAN.execute([sys.executable, '-c', 'pass'])
            kill.assert_not_called()

class RemoteLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.log = self.root / 'session.log'
        mock.patch.object(REMOTE, 'freerdp_connection_environment', return_value=os.environ.copy()).start()
        mock.patch.object(REMOTE, 'ensure_profile_directory').start()
        mock.patch.object(REMOTE, 'notify').start()
        self.addCleanup(mock.patch.stopall)

    def test_hardlink_rejection_does_not_truncate_original(self):
        original = self.root / 'important'; original.write_text('unchanged key fixture')
        os.link(original, self.log)
        with self.assertRaises(SystemExit): REMOTE.run_freerdp_command([sys.executable, '-c', 'pass'], self.log)
        self.assertEqual(payload_read_text(original), 'unchanged key fixture')

    def test_symlink_rejection_does_not_truncate_original(self):
        original = self.root / 'important'; original.write_text('unchanged')
        self.log.symlink_to(original)
        with self.assertRaises(OSError): REMOTE.run_freerdp_command([sys.executable, '-c', 'pass'], self.log)
        self.assertEqual(payload_read_text(original), 'unchanged')

    def test_fifo_rejection_does_not_block(self):
        os.mkfifo(self.log)
        with self.assertRaises(OSError): REMOTE.run_freerdp_command([sys.executable, '-c', 'pass'], self.log)

    def test_log_growth_is_bounded_and_status_preserved(self):
        code = 'import os; os.write(1,b"x"*2200000); print("FINAL"); raise SystemExit(7)'
        self.assertEqual(REMOTE.run_freerdp_command([sys.executable, '-c', code], self.log), 7)
        self.assertLessEqual(payload_source_stat(self.log).st_size, REMOTE.MAX_CONNECTION_LOG_BYTES)
        self.assertTrue(payload_read_bytes(self.log).endswith(b'FINAL\n'))
        self.assertEqual(payload_source_stat(self.log).st_mode & 0o777, 0o600)

class IntegrationContractTests(unittest.TestCase):
    def test_new_workers_and_units_are_staged(self):
        components = payload_read_text(FORKY / 'scripts/desktop/components.sh')
        security = payload_read_text(FORKY / 'scripts/late/security.sh')
        for name in ('labwc-apparmor-policy-worker', 'labwc-apparmor-boot-state'):
            self.assertIn(f'usr/local/libexec/{name} /usr/local/libexec/{name} 0755', components)
        for name in ('labwc-apparmor-policy@.service', 'labwc-apparmor-boot-recover.service'):
            self.assertIn(f'"/etc/systemd/system/{name}" 0644', security)

    def test_no_live_disable_menu_or_per_app_unload(self):
        menu = payload_read_text(TARGET / 'usr/local/bin/labwc-maintenance-menu')
        self.assertNotIn("'Disable All'", menu)
        self.assertIn("'Disable AppArmor After Reboot'", menu)
        self.assertIn("'Enable AppArmor After Reboot'", menu)
        self.assertNotIn('Disable) mode=disable', menu)
        for forbidden in ('aa-disable', 'aa-teardown', 'systemctl stop', 'reboot('):
            self.assertNotIn(forbidden, payload_read_text(TARGET / 'usr/local/libexec/labwc-apparmor-boot-state'))

    def test_critical_profile_sources_cannot_be_disabled_by_legacy_config(self):
        config = payload_read_text(TARGET / 'usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/Config.pm')
        for name in ('desktop-wrappers', 'system-wrappers', 'labwc-session', 'document-applications', 'desktop-utilities', 'usr.sbin.aa-status'):
            self.assertIn(name, config)
        self.assertIn("$mode eq 'disable' && $launch_sources{$profile_name}", config)

    def test_boot_disabled_kernel_skips_mode_reconciliation_at_boot(self):
        unit = payload_read_text(TARGET / 'etc/systemd/system/apparmor-modes.service')
        self.assertIn('ConditionSecurity=apparmor', unit)
        self.assertIn('Wants=labwc-apparmor-boot-recover.service', unit)

    def test_system_workers_do_not_share_desktop_lifetime(self):
        unit = payload_read_text(TARGET / 'etc/systemd/system/labwc-apparmor-policy@.service')
        for value in ('Type=oneshot', 'KillMode=control-group', 'ProtectHome=yes', 'ProtectSystem=strict', 'PrivatePIDs=no', 'PrivateUsers=no'):
            self.assertIn(value, unit)
        self.assertIn('StateDirectory=labwc-apparmor-policy apparmor/backup', unit)
        self.assertNotIn('PartOf=labwc-session', unit)
        self.assertNotIn('/home', '\n'.join(x for x in unit.splitlines() if x.startswith('ReadWritePaths=')))

    def test_all_digital_catalog_actions_have_dispatch_branches(self):
        base = TARGET / 'usr/local/lib/perl5/site_perl/digital-assets/DigitalAssets'
        catalog = set(re.findall(r"action\s*=>\s*'([^']+)'", payload_read_text(base / 'Catalog.pm')))
        branches = set(re.findall(r"\$action eq '([^']+)'", payload_read_text(base / 'Actions.pm')))
        self.assertGreater(len(catalog), 40)
        self.assertEqual(catalog, branches)

    def test_phone_menu_action_tokens_have_runtime_branches(self):
        menu = payload_read_text(TARGET / 'usr/local/bin/labwc-adb-menu').replace('\\\n', ' ')
        tokens = set(re.findall(r'run_adb_action\s+([a-z][a-z0-9-]+)', menu))
        runtime = payload_read_text(TARGET / 'usr/local/lib/perl5/site_perl/labwc-adb/AndroidADB/Runtime.pm')
        self.assertGreater(len(tokens), 40)
        for token in tokens:
            self.assertIn("'" + token + "'", runtime, token)

    def test_codex_prompt_cannot_become_an_option(self):
        runtime = payload_read_text(TARGET / 'usr/local/lib/perl5/site_perl/ai-copilots/AICopilots/Runtime.pm')
        self.assertIn("_exec_codex('--', $prompt)", runtime)
        self.assertIn('capture_command(argv => \\@command, timeout => 30, limit => $maximum)', runtime)

    def test_storage_inventory_failure_is_not_treated_as_unmounted(self):
        source = payload_read_text(TARGET / 'usr/local/bin/labwc-external-drives')
        self.assertIn('disk_snapshot=$(collect_snapshot "$disk_device") || return 1', source)
        self.assertIn('remaining_records=$(mounted_records_for_disk "$disk_device") || return 1', source)

if __name__ == '__main__':
    unittest.main()
