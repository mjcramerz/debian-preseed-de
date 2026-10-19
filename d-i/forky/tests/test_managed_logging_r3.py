"""Revision-3 logging: real profile renderer, native precedence and bounded routes.

No live journal, mounted storage, system service, or physical device is changed.
Native rsyslog integration tests skip explicitly when its packaged binary is absent.
"""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from payload_fixture import installed_script, source_path, logging_text
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

import grp
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import test_systemd_resource_policy as resource

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
CATEGORIES = ('apps', 'security', 'system', 'desktop', 'models')
NEW_ASSETS = (
    'etc/rsyslog.d/44-components.conf',
    'usr/local/libexec/native-logging',
    'etc/tmpfiles.d/59-log-layout.conf',
    'etc/systemd/system/rsyslog.service.d/20-log-layout.conf',
    'usr/local/libexec/journal-check',
    'usr/local/libexec/log-layout',
)


def module(name, relative):
    loader = importlib.machinery.SourceFileLoader(name, str(installed_script(TARGET / relative)))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


journal = module('managed_journal_check_r3', 'usr/local/libexec/journal-check')
forwarder = module('managed_journal_forwarding_r3', 'usr/local/libexec/journal-forwarding')
layout = module('managed_log_layout_r3', 'usr/local/libexec/log-layout')
BASE = ('[Journal]\nStorage=volatile\nForwardToSyslog=no\nReadKMsg=no\nSeal=no\n'
        'MaxLevelStore=debug\nMaxLevelSyslog=info\nRateLimitIntervalSec=30s\nRateLimitBurst=10000\n')


class JournalPolicyTests(unittest.TestCase):
    def test_runtime_forwarding_is_an_explicit_policy_state(self):
        active = BASE + '[Journal]\nForwardToSyslog=yes\n'
        journal.check(BASE, BASE)
        journal.check(BASE, active, forwarding=True)
        with self.assertRaises(journal.PolicyError):
            journal.check(BASE, active)
        with self.assertRaises(journal.PolicyError):
            journal.check(BASE, BASE, forwarding=True)
        with self.assertRaises(journal.PolicyError):
            journal.check(BASE, active + 'Storage=none\n', forwarding=True)

    def test_each_profile_requires_explicit_false_default(self):
        profiles = sorted((SEED / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            self.assertEqual(re.findall(r'^SYSTEMD_JOURNAL_VOLATILE_ENABLE=(.*)$', payload_read_text(path), re.M), ['"false"'])

    def test_both_boolean_values_all_profiles_use_production_renderer(self):
        harness = resource.ResourcePolicyTests()
        for path in resource.PROFILES:
            for enabled, value in (('true', 'volatile'), ('false', 'persistent')):
                with self.subTest(profile=path.name, enabled=enabled), tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / 'target'; target.mkdir()
                    persistent = target / 'var/log/journal/old-machine/system.journal'
                    persistent.parent.mkdir(parents=True); persistent.write_bytes(b'old journal untouched')
                    fstab = target / 'etc/fstab'; fstab.parent.mkdir(); fstab.write_bytes(b'original mount policy\n')
                    result = harness.shell(harness.staging(tmp) + '''
render_target_resource_asset hooks/target/etc/systemd/journald.conf.d/10-storage.conf "$FILE_JOURNALD_STORAGE_CONF" 0644
validate_target_journal_storage_policy
''', profile=path, override=f'SYSTEMD_JOURNAL_VOLATILE_ENABLE={enabled}')
                    self.assertEqual(result.returncode, 0)
                    rendered = payload_read_text(target / 'etc/systemd/journald.conf.d/10-storage.conf')
                    self.assertEqual(journal.journal_settings(rendered)['Storage'], value)
                    self.assertIn('ForwardToSyslog=no\n', rendered)
                    self.assertIn('ReadKMsg=no\n', rendered)
                    self.assertIn('MaxLevelStore=debug\n', rendered)
                    self.assertIn('MaxLevelSyslog=info\n', rendered)
                    self.assertIn('RateLimitIntervalSec=30s\n', rendered)
                    self.assertIn('RateLimitBurst=10000\n', rendered)
                    self.assertEqual(payload_read_bytes(persistent), b'old journal untouched')
                    self.assertEqual(payload_read_bytes(fstab), b'original mount policy\n')
                    self.assertFalse(resource.TOKEN.search(rendered))

    def test_invalid_or_missing_boolean_is_atomic_failure(self):
        harness = resource.ResourcePolicyTests()
        invalid = ['', 'TRUE', 'False', 'yes', '1', 'false ', 'true\nStorage=none', '$(touch /tmp/no-r3-eval)']
        for assignment in ['unset SYSTEMD_JOURNAL_VOLATILE_ENABLE'] + [
                'SYSTEMD_JOURNAL_VOLATILE_ENABLE=' + shlex.quote(v) for v in invalid]:
            with self.subTest(assignment=assignment), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'target'; target.mkdir()
                dest = target / 'etc/systemd/journald.conf.d/10-storage.conf'
                dest.parent.mkdir(parents=True); dest.write_text('original\n'); dest.chmod(0o644)
                result = harness.shell(harness.staging(tmp) + '''
render_target_resource_asset hooks/target/etc/systemd/journald.conf.d/10-storage.conf "$FILE_JOURNALD_STORAGE_CONF" 0644
''', override=assignment, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(payload_read_text(dest), 'original\n')

    def test_boolean_is_not_a_partition_mount_or_cleanup_input(self):
        for name in ('btrfs-family.sh', 'f2fs-family.sh', 'partition.sh'):
            path = SEED / 'scripts/late' / name
            if path.exists():
                self.assertNotIn('SYSTEMD_JOURNAL_VOLATILE_ENABLE', payload_read_text(path))
        for name in ('journal-check', 'log-layout'):
            text = payload_read_text(TARGET / 'usr/local/libexec' / name)
            self.assertNotRegex(text, r'(?:unlink|rmtree|remove)\([^\n]*journal')

    def test_shells_agree_on_both_storage_modes(self):
        harness = resource.ResourcePolicyTests()
        for value in ('true', 'false'):
            expected = harness.shell('systemd_resource_placeholder_map', override=f'SYSTEMD_JOURNAL_VOLATILE_ENABLE={value}').stdout
            for shell in ('bash', 'busybox'):
                if not shutil.which(shell):
                    continue
                self.assertEqual(expected, harness.shell('systemd_resource_placeholder_map', shell=shell,
                    override=f'SYSTEMD_JOURNAL_VOLATILE_ENABLE={value}').stdout)

    def test_conflicts_duplicates_missing_and_multiline_fail_closed(self):
        journal.check(BASE, BASE)
        for key, bad in [('Storage', 'persistent'), ('ForwardToSyslog', 'yes'), ('ReadKMsg', 'yes'),
                         ('MaxLevelStore', 'warning'), ('MaxLevelSyslog', 'warning'),
                         ('RateLimitIntervalSec', '0'), ('RateLimitBurst', '1')]:
            with self.subTest(key=key):
                with self.assertRaises(journal.PolicyError):
                    journal.check(BASE, BASE + f'{key}={bad}\n')
                with self.assertRaises(journal.PolicyError):
                    journal.check(BASE + f'{key}=no\n', BASE)
                with self.assertRaises(journal.PolicyError):
                    journal.check(BASE, BASE.replace(f'{key}=', '# removed='))
        with self.assertRaises(journal.PolicyError):
            journal.check(BASE, BASE + 'Storage=\\\nvolatile\n')
        journal.check(BASE, BASE + '[Other]\nStorage=persistent\n')
        journal.check(BASE, BASE + '# /etc/systemd/journald.conf.d/90-empty.conf\nStorage=persistent\n')
        with self.assertRaises(journal.PolicyError):
            journal.check(BASE, BASE + 'Storage=persistent\n# /etc/systemd/journald.conf.d/90-empty.conf\nStorage=volatile\n')

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'native systemd-analyze unavailable')
    def test_native_dropin_precedence_and_masks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            etc = root / 'etc/systemd/journald.conf.d'; etc.mkdir(parents=True)
            vendor = root / 'usr/lib/systemd/journald.conf.d'; vendor.mkdir(parents=True)
            (etc / '10-storage.conf').write_text(BASE)
            (vendor / '10-storage.conf').write_text('[Journal]\nStorage=none\n')
            def effective():
                result = subprocess.run(['systemd-analyze', f'--root={root}', 'cat-config', 'systemd/journald.conf'],
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout
            journal.check(BASE, effective())  # /etc shadows same vendor basename.
            # Debian systemd 262-1 ships this unnumbered vendor drop-in. It
            # sorts after both 10-storage.conf and the runtime 90-* file.
            vendor_syslog = vendor / 'syslog.conf'
            vendor_syslog.write_text('[Journal]\nForwardToSyslog=yes\n')
            vendor_bytes = vendor_syslog.read_bytes()
            with self.assertRaises(journal.PolicyError):
                journal.check(BASE, effective())
            local_syslog = etc / 'syslog.conf'
            local_syslog.write_bytes(payload_read_bytes(TARGET / 'etc/systemd/journald.conf.d/syslog.conf'))
            self.assertEqual(journal.journal_settings(local_syslog.read_text()), {})
            journal.check(BASE, effective())
            runtime = root / 'run/systemd/journald.conf.d'
            runtime.mkdir(parents=True)
            ready = runtime / journal.FORWARDING.name
            ready.write_bytes(journal.FORWARDING_BYTES)
            journal.check(BASE, effective(), forwarding=True)
            with self.assertRaises(journal.PolicyError):
                journal.check(BASE, effective())
            ready.unlink()
            journal.check(BASE, effective())
            self.assertEqual(vendor_syslog.read_bytes(), vendor_bytes)
            (vendor / '99-conflict.conf').write_text('[Journal]\nStorage=persistent\n')
            with self.assertRaises(journal.PolicyError):
                journal.check(BASE, effective())
            (etc / '99-conflict.conf').symlink_to('/dev/null')
            journal.check(BASE, effective())
            (etc / '90-local.conf').write_text('[Journal]\nForwardToSyslog=yes\n')
            with self.assertRaises(journal.PolicyError):
                journal.check(BASE, effective())

    @unittest.skipUnless(os.geteuid() == 0, 'staging ownership requires disposable fixture root')
    def test_foundation_stages_vendor_replacement_before_policy_check(self):
        harness = resource.ResourcePolicyTests()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'
            target.mkdir()
            result = harness.shell(harness.staging(tmp) + '''
# No target helper or manager may run during foundation publication.
run_in_target() { return 99; }
stage_target_logging_foundation
''')
            self.assertEqual(result.returncode, 0)
            replacement = target / 'etc/systemd/journald.conf.d/syslog.conf'
            self.assertEqual(replacement.read_bytes(),
                             payload_read_bytes(TARGET / 'etc/systemd/journald.conf.d/syslog.conf'))
            metadata = replacement.lstat()
            self.assertTrue(stat.S_ISREG(metadata.st_mode))
            self.assertEqual((metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode), metadata.st_nlink),
                             (0, 0, 0o644, 1))

    def test_managed_checker_is_staged_and_run_at_install_and_boot(self):
        components = payload_read_text(SEED / 'scripts/desktop/components.sh')
        verify = payload_read_text(SEED / 'scripts/desktop/verify.sh')
        for path in NEW_ASSETS:
            self.assertIn(path, components)
            self.assertIn('/' + path, verify)
            self.assertTrue(source_path(TARGET / path).is_file())
        unit = payload_read_text(TARGET / NEW_ASSETS[3])
        for command in ('journal-check', 'log-layout', 'rsyslogd -N1'):
            self.assertIn('ExecStartPre=/usr/', unit)
            self.assertIn(command, unit)
        self.assertIn('RequiresMountsFor=/var/lib/journal/power /var/log/managed /var/spool/rsyslog', unit)


@unittest.skipUnless(os.geteuid() == 0, 'root-owned paths require disposable fixture root')
class JournalForwardingTests(unittest.TestCase):
    def setUp(self):
        # /workspace is part of the mandatory private image, with trusted
        # ancestors. /tmp is intentionally rejected by the production checks.
        self.temp = tempfile.TemporaryDirectory(prefix='forwarding-', dir='/workspace')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'run/systemd/journald.conf.d'
        self.directory.parent.mkdir(parents=True)
        self.policy = self.directory / forwarder.POLICY.name
        for owner, name, value in ((forwarder, 'DIRECTORY', self.directory),
                                   (forwarder, 'POLICY', self.policy),
                                   (journal, 'FORWARDING', self.policy)):
            patch = mock.patch.object(owner, name, value)
            patch.start(); self.addCleanup(patch.stop)
        self.real_command = forwarder.command
        patch = mock.patch.object(forwarder, 'command')
        self.command = patch.start(); self.addCleanup(patch.stop)
        self.check = ['/usr/local/libexec/journal-check']
        self.reload = ['/usr/bin/systemctl', '--no-ask-password', '--job-mode=ignore-dependencies',
                       'reload', 'systemd-journald.service']

    def test_enable_disable_and_repeat_preserve_unrelated_dropins(self):
        self.assertEqual(forwarder.CONTENT, journal.FORWARDING_BYTES)
        self.directory.mkdir()
        other = self.directory / '20-other.conf'
        other.write_bytes(b'# unrelated\n')
        forwarder.enable()
        self.assertEqual(self.policy.read_bytes(), forwarder.CONTENT)
        self.assertEqual(stat.S_IMODE(self.policy.stat().st_mode), 0o644)
        self.assertTrue(journal.forwarding_enabled())
        self.assertEqual(self.command.call_args_list, [mock.call(self.check), mock.call(self.reload)])
        forwarder.disable(); forwarder.disable()
        self.assertFalse(self.policy.exists())
        self.assertFalse(journal.forwarding_enabled())
        self.assertEqual(other.read_bytes(), b'# unrelated\n')
        self.assertEqual(self.command.call_args_list,
                         [mock.call(self.check), mock.call(self.reload)] * 3)

    def test_absent_directory_disable_still_requests_acknowledged_reload(self):
        forwarder.disable()
        self.assertEqual(self.command.call_args_list, [mock.call(self.check), mock.call(self.reload)])
        self.assertFalse(self.directory.exists())

    def test_failed_enable_rolls_back_and_reports_disabled(self):
        self.command.side_effect = [None, forwarder.ForwardingError('reload failure'), None, None]
        with self.assertRaisesRegex(forwarder.ForwardingError, 'forwarding disabled'):
            forwarder.enable()
        self.assertFalse(self.policy.exists())
        self.assertEqual(self.command.call_args_list,
                         [mock.call(self.check), mock.call(self.reload)] * 2)

    def test_enable_timeout_retains_override_and_reports_unknown_without_retry(self):
        self.command.side_effect = [None, subprocess.TimeoutExpired(self.reload, 10)]
        with self.assertRaisesRegex(forwarder.ForwardingError, 'outcome unknown; override retained'):
            forwarder.enable()
        self.assertEqual(self.policy.read_bytes(), forwarder.CONTENT)
        self.assertEqual(self.command.call_args_list, [mock.call(self.check), mock.call(self.reload)])

    def test_disable_timeout_is_unknown(self):
        self.command.side_effect = [None, subprocess.TimeoutExpired(self.reload, 10)]
        with self.assertRaisesRegex(forwarder.ForwardingError, 'outcome unknown'):
            forwarder.disable()

    def test_failed_recovery_reports_unknown_and_does_not_succeed(self):
        self.command.side_effect = [None, forwarder.ForwardingError('reload failure'),
                                   forwarder.ForwardingError('disable check failed')]
        with self.assertRaisesRegex(forwarder.ForwardingError, 'outcome unknown'):
            forwarder.enable()
        self.assertFalse(self.policy.exists())

    def test_unsafe_files_are_never_replaced_or_removed(self):
        self.directory.mkdir()
        outside = self.root / 'outside'
        outside.write_bytes(forwarder.CONTENT); outside.chmod(0o644)
        cases = ('symlink', 'hardlink', 'mode', 'content', 'owner')
        for case in cases:
            with self.subTest(case=case):
                if case == 'symlink':
                    self.policy.symlink_to(outside)
                elif case == 'hardlink':
                    os.link(outside, self.policy)
                else:
                    self.policy.write_bytes(b'foreign\n' if case == 'content' else forwarder.CONTENT)
                    self.policy.chmod(0o666 if case == 'mode' else 0o644)
                    if case == 'owner':
                        os.chown(self.policy, 1234, 0)
                before = self.policy.lstat()
                for operation in (forwarder.enable, forwarder.disable, journal.forwarding_enabled):
                    with self.assertRaises((OSError, forwarder.ForwardingError, journal.PolicyError)):
                        operation()
                after = self.policy.lstat()
                self.assertEqual((after.st_dev, after.st_ino, after.st_uid, after.st_gid, after.st_mode),
                                 (before.st_dev, before.st_ino, before.st_uid, before.st_gid, before.st_mode))
                self.policy.unlink()
        self.command.assert_not_called()
        self.assertEqual(outside.read_bytes(), forwarder.CONTENT)

    def test_symlink_or_writable_parent_is_rejected(self):
        foreign = self.root / 'foreign'; foreign.mkdir()
        self.directory.symlink_to(foreign, target_is_directory=True)
        with self.assertRaises(forwarder.ForwardingError):
            forwarder.enable()
        self.directory.unlink()
        self.directory.mkdir(); self.directory.chmod(0o777)
        with self.assertRaises(forwarder.ForwardingError):
            forwarder.enable()
        self.command.assert_not_called()
        self.assertEqual(list(foreign.iterdir()), [])

    def test_command_uses_fixed_environment_deadline_and_propagates_failure(self):
        with mock.patch.object(forwarder.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.real_command(self.reload)
            self.assertEqual(run.call_args.kwargs['env'], forwarder.ENV)
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
            self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
            run.return_value.returncode = 1
            with self.assertRaises(forwarder.ForwardingError):
                self.real_command(self.reload)

    def test_lifecycle_foundation_and_firstboot_wiring(self):
        unit = payload_read_text(TARGET / 'etc/systemd/system/rsyslog-journal-forwarding.service')
        for line in ('BindsTo=rsyslog.service', 'PartOf=rsyslog.service',
                     'After=rsyslog.service systemd-journald.service journal-sealing.service',
                     'ExecStart=/usr/local/libexec/journal-forwarding on',
                     'ExecStopPost=/usr/local/libexec/journal-forwarding off'):
            self.assertIn(line, unit)
        request = payload_read_text(TARGET / 'etc/systemd/system/rsyslog.service.d/40-journal-forwarding.conf')
        self.assertIn('Wants=rsyslog-journal-forwarding.service', request)
        self.assertIn('Type=notify', request)
        foundation = (SEED / 'scripts/late/target-assets.sh').read_text().split(
            'stage_target_logging_foundation() {', 1)[1]
        for path in ('usr/local/libexec/journal-forwarding',
                     'etc/systemd/journald.conf.d/syslog.conf',
                     'etc/systemd/system/rsyslog-journal-forwarding.service',
                     'etc/systemd/system/rsyslog.service.d/40-journal-forwarding.conf'):
            self.assertIn(path, foundation)
            self.assertIn('/' + path, payload_read_text(SEED / 'scripts/desktop/verify.sh'))
        self.assertNotIn('stat ', foundation)
        self.assertIn('installer_metadata_value', foundation)
        validation = payload_read_text(SEED / 'scripts/firstboot/04-validation.sh')
        self.assertIn('journal-check --require-forwarding', validation)
        self.assertIn('is-active --quiet rsyslog-journal-forwarding.service', validation)


@unittest.skipUnless(os.geteuid() == 0, 'ownership/layout tests require root in a disposable fixture')
class LogLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        adm = grp.getgrnam('adm').gr_gid
        for rel in ('var', 'var/log', 'var/spool', 'var/log/managed'):
            path = self.root / rel; path.mkdir(exist_ok=True); path.chmod(0o755)
        (self.root / 'var/log/managed').chmod(0o751)
        for absolute, mode in layout.CATEGORIES.items():
            path = self.root / absolute.lstrip('/'); path.mkdir(parents=True, exist_ok=True)
            path.chmod(mode); os.chown(path, 0, adm)
        for absolute in layout.PROTECTED_FILES:
            path = self.root / absolute.lstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.parent.chmod(0o750); os.chown(path.parent, 0, adm)
            path.touch(); path.chmod(0o640); os.chown(path, 0, adm)
        spool = self.root / 'var/spool/rsyslog'; spool.mkdir(); spool.chmod(0o700)

    def test_valid_layout_is_idempotent(self):
        layout.check_layout(self.root); layout.check_layout(self.root)

    def test_symlink_category_and_parent_are_rejected(self):
        for relative in ('var/log/managed/apps', 'var/log/managed'):
            with self.subTest(path=relative):
                path = self.root / relative; saved = path.with_name(path.name + '-saved')
                path.rename(saved); path.symlink_to(saved, target_is_directory=True)
                with self.assertRaises(OSError):
                    layout.check_layout(self.root)
                path.unlink(); saved.rename(path)

    def test_symlink_and_hardlinked_runtime_files_are_rejected(self):
        path = self.root / layout.PROTECTED_FILES[0].lstrip('/')
        saved = self.root / 'saved'; path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaises(layout.LayoutError):
            layout.check_layout(self.root)
        path.unlink(); os.link(saved, path)
        with self.assertRaises(layout.LayoutError):
            layout.check_layout(self.root)
        self.assertEqual(payload_read_bytes(saved), b'')

    def test_writable_parent_and_public_spool_are_rejected(self):
        path = self.root / 'var/log/managed'; path.chmod(0o775)
        with self.assertRaises(layout.LayoutError):
            layout.check_layout(self.root)
        path.chmod(0o751)
        (self.root / 'var/spool/rsyslog').chmod(0o755)
        with self.assertRaises(layout.LayoutError):
            layout.check_layout(self.root)


    def test_application_writable_model_subtree_is_not_reowned(self):
        path = self.root / 'var/log/managed/models/openai/chatgpt/runtime'
        path.mkdir(parents=True, exist_ok=True); path.chmod(0o2770); os.chown(path, 65534, 65534)
        layout.check_layout(self.root)
        self.assertEqual(path.stat().st_uid, 65534)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o2770)

    @unittest.skipUnless(shutil.which('systemd-tmpfiles'), 'native tmpfiles unavailable')
    def test_native_tmpfiles_creation_and_repeat_preserve_existing_journal(self):
        etc = self.root / 'etc'; etc.mkdir()
        (etc / 'passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
        (etc / 'group').write_text(f'root:x:0:\nadm:x:{grp.getgrnam("adm").gr_gid}:\nsecuritylogger:x:61001:\nlogreader:x:61002:\n')
        config = self.root / 'etc/tmpfiles.d/59-log-layout.conf'; config.parent.mkdir()
        config.write_bytes(payload_read_bytes(TARGET / NEW_ASSETS[2]))
        configs = [config]
        for name in ('60-security-logs.conf', '65-audit-syslog.conf'):
            child = config.parent / name
            child.write_bytes(payload_read_bytes(TARGET / 'etc/tmpfiles.d' / name))
            configs.append(child)
        old = self.root / 'var/log/journal/machine/old.journal'; old.parent.mkdir(parents=True)
        old.write_bytes(b'original journal')
        for _ in range(2):
            result = subprocess.run(['systemd-tmpfiles', f'--root={self.root}', '--create',
                                     *[str(path) for path in configs]], text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            layout.check_layout(self.root)
            self.assertEqual(payload_read_bytes(old), b'original journal')


class RoutingContractTests(unittest.TestCase):
    def test_recording_diagnostics_use_the_existing_application_sink(self):
        capture = payload_read_text(TARGET / 'usr/local/bin/labwc-capture')
        for setting in ('StandardOutput=null', 'StandardError=null',
                        'SyslogIdentifier=labwc-screen-recording'):
            self.assertIn(setting, capture)
        self.assertIn('RECORDING_LOG="/var/log/managed/apps/apps.log"', capture)
        self.assertNotIn('>>"$RECORDING_LOG"', capture)
        self.assertNotIn(': >"$RECORDING_LOG"', capture)
        self.assertIn('/usr/local/libexec/rsyslog-app-run labwc-screen-recording --', capture)

    def test_managed_application_services_have_no_journal_stream(self):
        for relative in ('usr/local/lib/python3.14/dist-packages/labwc_managed_app/generic.py',
                         'usr/local/lib/python3.14/dist-packages/labwc_managed_app/session.py',
                         'usr/local/bin/labwc-qbittorrent',
                         'etc/skel-desktop/.config/systemd/user/codex-app-server.service',
                         'etc/skel-desktop/.config/systemd/user/codex-app-server-proxy.service'):
            with self.subTest(relative=relative):
                text = payload_read_text(TARGET / relative)
                self.assertIn('StandardOutput=null', text)
                self.assertIn('StandardError=null', text)
                self.assertNotIn('StandardOutput=journal', text)
                self.assertNotIn('StandardError=journal', text)

    def test_journal_input_and_private_sockets_are_not_duplicated(self):
        text = payload_read_text(TARGET / 'etc/rsyslog.conf')
        self.assertIn('module(load="imuxsock" SysSock.Use="on"', text)
        self.assertIn('SysSock.Annotate="on" SysSock.ParseTrusted="on"', text)
        self.assertNotIn('module(load="imjournal"', text)
        self.assertEqual(text.count('module(load="imklog")'), 1)
        self.assertNotIn('StateFile=', text)
        self.assertNotIn('omjournal', text)
        for name in ('38-openai-chatgpt.conf', '39-security-scanners.conf'):
            private = payload_read_text(TARGET / 'etc/rsyslog.d' / name)
            self.assertIn('type="imuxsock"', private)
            self.assertIn('CreatePath="off"', private)

    def test_destinations_are_constant_plain_text_and_bounded(self):
        text = payload_read_text(TARGET / NEW_ASSETS[0])
        apps = payload_read_text(TARGET / 'etc/rsyslog.d/21-apps.conf')
        self.assertEqual(set(re.findall(r'file="([^"]+)"', text)),
                         {'/var/log/managed/system/system.log', '/var/log/managed/system/kernel.log'})
        for forbidden in ('$all-json', '_CMDLINE', 'format="jsonf"', 're_match(',
                          'managed_identity', 'dynaFile=', 'managed_logfile'):
            self.assertNotIn(forbidden, text + apps)
        self.assertIn('template="RSYSLOG_FileFormat"', text + apps)
        self.assertIn('createDirs="off"', text)
        self.assertIn('queue.saveOnShutdown="on"', apps)
        self.assertIn('queue.timeoutEnqueue="0"', apps)

    def test_applications_have_one_credential_based_route(self):
        text = payload_read_text(TARGET / 'etc/rsyslog.d/21-apps.conf')
        self.assertEqual(re.findall(r'file="([^"]+)"', text), ['/var/log/managed/apps/apps.log'])
        self.assertIn('exists($!uid)', text)
        self.assertIn('cnum($!uid) >= 1000', text)
        self.assertIn('cnum($!uid) <= 59999', text)
        self.assertIn('stop', text)
        self.assertNotIn('$programname', text)

    def test_no_active_file_mirroring_and_native_audit_output(self):
        for path in (TARGET/'etc/rsyslog.d').iterdir():
            if path.is_file():
                text = logging_text(path.read_text())
                active = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
                if path.name == '30-apparmor.conf.tmpl':
                    self.assertIn('File="/var/log/managed/security/audit/auditd.log"', active)
                    self.assertEqual(active.count('module(load="imfile" mode="inotify")'), 1)
                    self.assertNotIn('pollingInterval=', active)
                    self.assertIn('PersistStateInterval="64"', active)
                    self.assertIn('persistStateAfterSubmission="on"', active)
                    self.assertIn('MaxSubmitAtOnce="64"', active)
                else:
                    self.assertNotRegex(active, r'\bimfile\b|/(?:vendor|runtime)\.log')
        for path in TARGET.glob('etc/audit/*/auditd.conf.tmpl'):
            text = logging_text(path.read_text())
            self.assertIn('log_file = /var/log/managed/security/audit/auditd.log', text)
        plugin = payload_read_text(TARGET/'etc/audit/plugins.d/syslog.conf')
        self.assertIn('active = no',plugin)

    def test_protected_outputs_have_one_rotation_owner(self):
        configs = ''.join(logging_text(p.read_text()) for p in (TARGET/'etc/tmpfiles.d').glob('*') if p.is_file())
        rotations = ''.join(logging_text(p.read_text()) for p in (TARGET/'etc/logrotate.d').glob('*') if p.is_file())
        callback = module('size_rotation_contract', 'usr/local/libexec/rsyslog-size-rotate')
        for path in layout.PROTECTED_FILES:
            self.assertIn('f '+path+' ',configs, path)
            self.assertIn(path, callback.OUTPUTS, path)
            self.assertNotIn(path, rotations, path)
        self.assertEqual(callback.LIMIT, 2 * 1024 * 1024)
        self.assertEqual(callback.KEEP, 4)


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('rsyslogd'),
                     'packaged rsyslogd is unavailable; target installer and boot enforce native -N1')
class NativeRsyslogTests(unittest.TestCase):
    def test_chatgpt_config_parses_before_desktop_rules_are_staged(self):
        # Both storage families publish the foundation before selected helpers.
        # At ChatGPT's validation point the other desktop drop-ins do not exist.
        foundation = (SEED / 'scripts/late/target-assets.sh').read_text()
        self.assertIn('etc/rsyslog.conf', foundation.split('stage_target_logging_foundation() {', 1)[1])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'spool').mkdir()
            dropins = root / 'rsyslog.d'; dropins.mkdir()
            (dropins / '38-openai-chatgpt.conf').write_text(
                payload_read_text(TARGET / 'etc/rsyslog.d/38-openai-chatgpt.conf'))
            config = root / 'rsyslog.conf'
            config.write_text(payload_read_text(TARGET / 'etc/rsyslog.conf')
                .replace('/var/spool/rsyslog', str(root / 'spool'))
                .replace('/etc/rsyslog.d/*.conf', str(dropins / '*.conf')))
            result = subprocess.run(['rsyslogd', '-N1', '-f', str(config)],
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_complete_production_config_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'spool').mkdir()
            config = root / 'rsyslog.conf'
            text = payload_read_text(TARGET / 'etc/rsyslog.conf').replace('/var/spool/rsyslog', str(root / 'spool'))
            dropins = root / 'rsyslog.d'; dropins.mkdir()
            for source in (TARGET/'etc/rsyslog.d').iterdir():
                if source.is_file():
                    (dropins/source.name.removesuffix('.tmpl')).write_text(logging_text(source.read_text()))
            text = text.replace('/etc/rsyslog.d/*.conf', str(dropins / '*.conf'))
            config.write_text(text)
            result = subprocess.run(['rsyslogd', '-N1', '-f', str(config)], text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runtime_delivery_size_rotation_and_restart(self):
        from test_logging_size_20260924 import exercise_native_rsyslog
        exercise_native_rsyslog(self)


class ApplicationCaptureTests(unittest.TestCase):
    """Fixture sockets/processes only, inside the mandatory disposable image."""

    def test_cleanup_preserves_reaped_children_and_bounds_term_then_kill(self):
        capture = module('managed_app_capture_cleanup', 'usr/local/libexec/rsyslog-app-run')
        child = mock.Mock()
        child.poll.return_value = 7
        with mock.patch.object(capture.time, 'monotonic') as clock:
            capture.stop_child(child, stopping=False)
        clock.assert_not_called()
        child.terminate.assert_not_called()
        child.kill.assert_not_called()
        child.wait.assert_not_called()

        child = mock.Mock()
        child.poll.return_value = None
        with mock.patch.object(capture.time, 'monotonic', side_effect=(100, 100)):
            capture.stop_child(child, stopping=False)
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=2.0)
        child.kill.assert_not_called()

        child = mock.Mock()
        child.poll.return_value = None
        child.wait.side_effect = (subprocess.TimeoutExpired('fixture', 2), -signal.SIGKILL)
        with mock.patch.object(capture.time, 'monotonic', side_effect=(100, 100, 103)):
            capture.stop_child(child, stopping=False)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_args_list, [mock.call(timeout=2.0), mock.call(timeout=1.0)])

    def test_elapsed_stop_grace_kills_once_and_does_not_add_another_term_grace(self):
        capture = module('managed_app_capture_stop_grace', 'usr/local/libexec/rsyslog-app-run')
        child = mock.Mock()
        child.poll.return_value = None
        with mock.patch.object(capture.time, 'monotonic', side_effect=(100, 101)):
            capture.stop_child(child, stopping=True)
        child.terminate.assert_not_called()
        child.kill.assert_called_once()
        child.wait.assert_called_once_with(timeout=3.0)

    def test_supervisor_ends_the_stop_loop_after_fifteen_seconds(self):
        capture = module('managed_app_capture_stop_deadline', 'usr/local/libexec/rsyslog-app-run')
        child = mock.Mock()
        child.poll.return_value = None
        def register(number, handler):
            if number == signal.SIGTERM and callable(handler):
                handler(number, None)
            return signal.SIG_DFL
        with mock.patch.object(capture.sys, 'stderr') as stderr, \
             mock.patch.object(capture.os, 'get_blocking', return_value=True), \
             mock.patch.object(capture.os, 'set_blocking'), \
             mock.patch.object(capture.os, 'close') as close, \
             mock.patch.object(capture.signal, 'signal', side_effect=register), \
             mock.patch.object(capture.socket, 'socket'), \
             mock.patch.object(capture.selectors, 'PollSelector') as selector, \
             mock.patch.object(capture.subprocess, 'Popen', return_value=child), \
             mock.patch.object(capture.os, 'pidfd_open', return_value=77), \
             mock.patch.object(capture.time, 'monotonic', side_effect=(100, 115)), \
             mock.patch.object(capture, 'stop_child') as stop:
            stderr.fileno.return_value = 42
            self.assertEqual(capture.supervise('fixture-app', ['/fixture/app']), -signal.SIGKILL)
        stop.assert_called_once_with(child, stopping=True)
        selector.return_value.__enter__.return_value.select.assert_not_called()
        child.send_signal.assert_called_once_with(signal.SIGTERM)
        child.kill.assert_not_called()  # Only the single cleanup owner escalates.
        child.wait.assert_not_called()
        child.stdout.close.assert_called_once()
        child.stderr.close.assert_called_once()
        close.assert_called_once_with(77)

    def test_cleanup_timeout_and_signal_failure_report_unknown_without_unbounded_wait(self):
        capture = module('managed_app_capture_cleanup_unknown', 'usr/local/libexec/rsyslog-app-run')
        for failure in ('wait', 'kill'):
            child = mock.Mock()
            child.poll.return_value = None
            if failure == 'wait':
                child.wait.side_effect = subprocess.TimeoutExpired('private fixture arguments', 2)
            else:
                child.wait.side_effect = (subprocess.TimeoutExpired('private fixture arguments', 2),)
                child.kill.side_effect = PermissionError('private fixture arguments')
            with self.subTest(failure=failure), \
                 mock.patch.object(capture.time, 'monotonic', side_effect=(100, 100, 105)), \
                 self.assertRaises(capture.CaptureCleanupUnknown) as error:
                capture.stop_child(child, stopping=False)
            self.assertNotIn('private fixture arguments', str(error.exception))
            child.kill.assert_called_once()
            expected = [mock.call(timeout=2.0), mock.call(timeout=0.0)] if failure == 'wait' else [mock.call(timeout=2.0)]
            self.assertEqual(child.wait.call_args_list, expected)

    def test_streaming_output_stops_delivery_when_the_stop_grace_expires(self):
        capture = module('managed_app_capture_stream_deadline', 'usr/local/libexec/rsyslog-app-run')
        child = mock.Mock()
        child.poll.return_value = None
        clock = [100.0]
        def register(number, handler):
            if number == signal.SIGTERM and callable(handler):
                handler(number, None)
            return signal.SIG_DFL
        def readable(_timeout):
            clock[0] = 114.0
            return [(mock.Mock(fileobj=child.stdout), 1)]
        def send(packet, _destination):
            clock[0] = 116.0
            return len(packet)
        with mock.patch.object(capture.sys, 'stderr') as stderr, \
             mock.patch.object(capture.os, 'get_blocking', return_value=True), \
             mock.patch.object(capture.os, 'set_blocking'), \
             mock.patch.object(capture.os, 'close'), \
             mock.patch.object(capture.os, 'read', return_value=b'x' * capture.LINE_LIMIT), \
             mock.patch.object(capture.signal, 'signal', side_effect=register), \
             mock.patch.object(capture.socket, 'socket') as channel, \
             mock.patch.object(capture.selectors, 'PollSelector') as selector, \
             mock.patch.object(capture.subprocess, 'Popen', return_value=child), \
             mock.patch.object(capture.os, 'pidfd_open', return_value=77), \
             mock.patch.object(capture.time, 'monotonic', side_effect=lambda: clock[0]), \
             mock.patch.object(capture, 'stop_child') as stop:
            stderr.fileno.return_value = 42
            selector.return_value.__enter__.return_value.select.side_effect = readable
            transport = channel.return_value.__enter__.return_value
            transport.sendto.side_effect = send
            self.assertEqual(capture.supervise('fixture-app', ['/fixture/app']), -signal.SIGKILL)
        transport.sendto.assert_called_once()
        selector.return_value.__enter__.return_value.select.assert_called_once()
        stop.assert_called_once_with(child, stopping=True)

    def test_unknown_cleanup_closes_output_pipes_and_restores_signals(self):
        capture = module('managed_app_capture_cleanup_resources', 'usr/local/libexec/rsyslog-app-run')
        child = mock.Mock()
        with mock.patch.object(capture.sys, 'stderr') as stderr, \
             mock.patch.object(capture.os, 'get_blocking', return_value=True), \
             mock.patch.object(capture.os, 'set_blocking') as blocking, \
             mock.patch.object(capture.signal, 'signal', return_value=signal.SIG_DFL) as handlers, \
             mock.patch.object(capture.socket, 'socket'), \
             mock.patch.object(capture.selectors, 'PollSelector'), \
             mock.patch.object(capture.subprocess, 'Popen', return_value=child), \
             mock.patch.object(capture.os, 'pidfd_open', side_effect=OSError('fixture setup failure')), \
             mock.patch.object(capture, 'stop_child', side_effect=capture.CaptureCleanupUnknown('fixture')), \
             self.assertRaises(capture.CaptureCleanupUnknown):
            stderr.fileno.return_value = 42
            capture.supervise('fixture-app', ['/fixture/app'])
        child.stdout.close.assert_called_once()
        child.stderr.close.assert_called_once()
        blocking.assert_not_called()
        self.assertEqual(handlers.call_args_list[-len(capture.SIGNALS):],
                         [mock.call(number, signal.SIG_DFL) for number in capture.SIGNALS])

    def test_cli_preserves_large_literal_argument_lists_and_status(self):
        capture = module('managed_app_capture_arguments', 'usr/local/libexec/rsyslog-app-run')
        arguments = ['/usr/bin/fixture-app', *('file with spaces' for _ in range(300)),
                     '--', '-literal-option', '$(literal)', 'literal;value', '\u00e5\u00e4\u00f6']
        with mock.patch.object(capture.os, 'getuid', return_value=1000), \
             mock.patch.object(capture.sys, 'argv', ['rsyslog-app-run', 'fixture-app', '--', *arguments]), \
             mock.patch.object(capture, 'supervise', return_value=37) as supervise:
            self.assertEqual(capture.main(), 37)
        supervise.assert_called_once_with('fixture-app', arguments)

    def test_cli_rejects_privileged_or_ambiguous_launches_before_spawning(self):
        capture = module('managed_app_capture_validation', 'usr/local/libexec/rsyslog-app-run')
        for uid, identifier, command in (
            (0, 'fixture-app', ['/usr/bin/fixture-app']),
            (1000, 'invalid\nidentifier', ['/usr/bin/fixture-app']),
            (1000, 'fixture-app', ['relative-executable']),
            (1000, 'fixture-app', []),
        ):
            with self.subTest(uid=uid, identifier=identifier, command=command), \
                 mock.patch.object(capture.os, 'getuid', return_value=uid), \
                 mock.patch.object(capture.sys, 'argv', ['rsyslog-app-run', identifier, '--', *command]), \
                 mock.patch.object(capture, 'supervise') as supervise, \
                 mock.patch.object(capture.sys, 'stderr'), \
                 self.assertRaises(SystemExit) as failure:
                capture.main()
            self.assertEqual(failure.exception.code, 2)
            supervise.assert_not_called()

    def test_levels_and_untrusted_bytes(self):
        capture = module('managed_app_capture_levels', 'usr/local/libexec/rsyslog-app-run')
        for line, stream, expected in (
            (b'<3>fatal launch failure', 'stdout', 3),
            (b'[2026-10-16] [info] ready', 'stderr', 6),
            (b'[123:ERROR:handler.cc] failure', 'stderr', 3),
            (b'warning: no device', 'stdout', 4),
            (b'unclassified diagnostic', 'stderr', 4),
            (b'ready', 'stdout', 6),
        ):
            with self.subTest(line=line):
                self.assertEqual(capture.severity(line, stream), expected)
        self.assertEqual(capture.escaped(b'hello\n\x1b\x00\xff'), r'hello\x0a\x1b\x00\xff')

    def test_fatal_diagnostic_is_private_bounded_and_redacted(self):
        capture = module('managed_app_capture_fatal', 'usr/local/libexec/rsyslog-app-run')
        for failure in (None, BlockingIOError(), FileNotFoundError()):
            with mock.patch.object(capture.socket, 'socket') as factory, \
                 mock.patch.object(capture.sys, 'stderr') as stderr:
                transport = factory.return_value.__enter__.return_value
                transport.sendto.side_effect = failure
                capture.report_capture_failure(OSError('fixture private command details'))
                transport.settimeout.assert_called_once_with(0.05)
                packet, destination = transport.sendto.call_args.args
                self.assertIn(b'event=capture-failed error=OSError', packet)
                self.assertNotIn(b'private', packet)
                self.assertEqual(destination, capture.SOCKET)
                self.assertFalse(stderr.mock_calls)

    def _capture(self, root: Path, destination: Path, script: str):
        helper = installed_script(TARGET / 'usr/local/libexec/rsyslog-app-run')
        driver = (
            'import runpy,sys; '
            'scope=runpy.run_path(sys.argv[1],run_name="isolated_capture_fixture"); '
            'run=scope["supervise"]; run.__globals__["SOCKET"]=sys.argv[2]; '
            'status=run("fixture-app",[sys.executable,"-I","-c",sys.argv[3]]); '
            'sys.exit(status if status>=0 else 128-status)'
        )
        return subprocess.run(
            [sys.executable, '-I', '-B', '-c', driver, str(helper), str(destination), script],
            cwd=root, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5, check=False,
        )

    def test_output_bypasses_journal_and_preserves_failure_status(self):
        with tempfile.TemporaryDirectory(prefix='app-capture-') as temporary:
            root = Path(temporary)
            destination = root / 'collector.sock'
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as collector:
                collector.bind(str(destination)); collector.settimeout(0.1)
                result = self._capture(root, destination,
                    'import os; os.write(1,b"ordinary output\\n"); '
                    'os.write(2,b"[info] diagnostic\\nERROR: failed\\n"); raise SystemExit(7)')
                records = []
                while True:
                    try:
                        records.append(collector.recv(8192))
                    except TimeoutError:
                        break
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(len(records), 3)
            self.assertEqual(result.stderr, b'')  # Every severity stays on the private socket.
            self.assertTrue(any(record.startswith(b'<11>') and b'ERROR: failed' in record for record in records))
            self.assertTrue(any(record.startswith(b'<14>') and b'ordinary output' in record for record in records))

    def test_collector_outage_keeps_app_status_without_journal_fallback(self):
        with tempfile.TemporaryDirectory(prefix='app-capture-outage-') as temporary:
            root = Path(temporary)
            result = self._capture(root, root / 'absent.sock',
                                   'print("fixture diagnostic"); raise SystemExit(9)')
            self.assertEqual(result.returncode, 9, result.stderr)
            self.assertEqual(result.stderr, b'')
            self.assertEqual(result.stdout, b'')

    @unittest.skipUnless(shutil.which('perl'), 'packaged Perl is unavailable in the disposable image')
    def test_fuzzel_direct_delivery_never_falls_back_to_journal(self):
        source = payload_read_text(TARGET / 'usr/local/bin/labwc-fuzzel-log')
        self.assertEqual(source.count('/run/rsyslog/apps/apps.sock'), 1)
        self.assertNotIn("'/dev/log'", source)
        with tempfile.TemporaryDirectory(prefix='fuzzel-log-') as temporary:
            root = Path(temporary)
            direct = root / 'apps.sock'
            fallback = root / 'journal.sock'
            helper = root / 'logger'
            helper.write_text(source.replace('/run/rsyslog/apps/apps.sock', str(direct))
                              .replace("'/dev/log'", repr(str(fallback))))
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as collector, \
                 socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as journal:
                collector.bind(str(direct)); collector.settimeout(0.2)
                journal.bind(str(fallback)); journal.settimeout(0.2)
                for outage in (False, True):
                    with self.subTest(outage=outage):
                        if outage:
                            direct.unlink()  # Only this fixture's directory entry.
                        result = subprocess.run(
                            [shutil.which('perl'), str(helper), 'action', 'launch-failed',
                             'application=fixture\nname'], cwd=root,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=2,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        with self.assertRaises(TimeoutError):
                            journal.recv(8192)
                        if outage:
                            with self.assertRaises(TimeoutError):
                                collector.recv(8192)
                            continue
                        packet = collector.recv(8192)
                        self.assertTrue(packet.startswith(b'<11>'), packet)
                        self.assertIn(b'labwc-fuzzel-action[', packet)
                        self.assertIn(b'event=launch-failed application=fixture_name', packet)
                        self.assertNotIn(b'\n', packet)

    def test_direct_input_is_file_only_without_journal_import_or_export(self):
        config = payload_read_text(TARGET / 'etc/rsyslog.conf')
        direct = payload_read_text(TARGET / 'etc/rsyslog.d/22-apps-socket.conf')
        apps = payload_read_text(TARGET / 'etc/rsyslog.d/21-apps.conf')
        self.assertIn('SysSock.IgnoreOwnMessages="on"', config)
        self.assertNotIn('omjournal', config + apps)
        self.assertNotIn('call managed_application_output', apps)
        self.assertNotIn('format="jsonf"', config)
        self.assertNotIn('option.jsonf=', config)
        self.assertIn('Ruleset="managed_application_output"', direct)
        self.assertIn('ParseTrusted="on"', direct)
        self.assertNotIn('$.application_from_journal', apps)
        ruleset = apps.split('ruleset(name="managed_application_output"', 1)[1].split(') {', 1)[0]
        self.assertIn('queue.type="LinkedList"', ruleset)
        self.assertIn('queue.size=', ruleset)
        self.assertIn('queue.workerThreads="1"', ruleset)
        self.assertIn('queue.timeoutEnqueue="0"', ruleset)
        fallback = payload_read_text(TARGET / 'etc/rsyslog.d/44-components.conf')
        self.assertIn('else if ($syslogseverity <= 4)', fallback)

    @unittest.skipUnless(shutil.which('perl') and shutil.which('setsid'), 'packaged Perl/setsid unavailable')
    def test_chatgpt_private_capture_preserves_status_during_collector_outage(self):
        source = payload_read_text(TARGET / 'usr/local/libexec/labwc-chatgpt-log-runner')
        profiles = payload_read_text(TARGET / 'etc/apparmor.d/desktop-wrappers')
        capture_profile = profiles.split('profile labwc-chatgpt-log-runner ', 1)[1].split('\n}', 1)[0]
        for rule in ('deny /dev/log rw,', 'deny /{,var/}run/systemd/journal/ r,',
                     'deny /{,var/}run/systemd/journal/** rw,'):
            self.assertIn(rule, capture_profile)
        self.assertNotIn('/dev/log', source)
        self.assertNotIn('/run/systemd/journal', source)
        for transport in ('direct', 'unavailable', 'full'):
            with self.subTest(transport=transport), tempfile.TemporaryDirectory(prefix='chatgpt-log-outage-') as tmp:
                root = Path(tmp)
                direct = root / 'direct.sock'
                child = root / 'child'
                child.write_text('#!/bin/sh\nprintf "fixture output\\n"\nexit 7\n')
                child.chmod(0o700)
                fixture = source
                for constant, value in (('CHILD_EXECUTABLE', child), ('SOCKET_PATH', direct)):
                    fixture, count = re.subn(r"(?m)^(\s*" + constant + r"\s*=>\s*)'[^']*'",
                                            lambda match: match[1] + repr(str(value)), fixture)
                    self.assertEqual(count, 1, constant)
                logger = root / 'logger.pl'; logger.write_text(fixture)
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as collector:
                    if transport != 'unavailable':
                        collector.bind(str(direct))
                        collector.settimeout(0.2)
                    if transport == 'full':
                        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as filler:
                            filler.setblocking(False)
                            for _ in range(256):
                                try:
                                    filler.sendto(b'fixture queue filler', str(direct))
                                except BlockingIOError:
                                    break
                            else:
                                self.fail('fixture collector queue did not fill within the bound')
                    result = subprocess.run(['/usr/bin/perl', str(logger), 'launch'], cwd=root,
                        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, stdin=subprocess.DEVNULL,
                        capture_output=True, timeout=3)
                    self.assertEqual(result.returncode, 7, result.stderr)
                    if transport == 'direct':
                        messages = [collector.recv(8192) for _ in range(3)]
                        self.assertTrue(any(b'fixture output' in packet for packet in messages))
                        self.assertTrue(any(b'event=completed status=7' in packet for packet in messages))

    @unittest.skipUnless(shutil.which('perl') and shutil.which('setsid'), 'packaged Perl/setsid unavailable')
    def test_chatgpt_capture_follows_replaced_collector_socket(self):
        with tempfile.TemporaryDirectory(prefix='chatgpt-log-restart-') as tmp:
            root = Path(tmp)
            direct, ready = root / 'direct.sock', root / 'continue'
            child = root / 'child'
            child.write_text('#!/usr/bin/python3\nimport sys,time\nfrom pathlib import Path\n'
                             'print("before restart",flush=True)\n'
                             'deadline=time.monotonic()+2\n'
                             f'while not Path({str(ready)!r}).exists():\n'
                             ' if time.monotonic()>deadline: sys.exit(99)\n'
                             ' time.sleep(.01)\n'
                             'print("after restart",flush=True)\nsys.exit(7)\n')
            child.chmod(0o700)
            source = payload_read_text(TARGET / 'usr/local/libexec/labwc-chatgpt-log-runner')
            for constant, value in (('CHILD_EXECUTABLE', child), ('SOCKET_PATH', direct)):
                source, count = re.subn(r"(?m)^(\s*" + constant + r"\s*=>\s*)'[^']*'",
                                       lambda match: match[1] + repr(str(value)), source)
                self.assertEqual(count, 1, constant)
            logger = root / 'logger.pl'; logger.write_text(source)
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as initial:
                initial.bind(str(direct)); initial.settimeout(1)
                process = subprocess.Popen(['/usr/bin/perl', str(logger), 'launch'], cwd=root,
                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.assertIn(b'event=started', initial.recv(8192))
                    self.assertIn(b'before restart', initial.recv(8192))
                    initial.close(); direct.unlink()
                    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as replacement:
                        replacement.bind(str(direct)); replacement.settimeout(1)
                        ready.touch()
                        _, errors = process.communicate(timeout=3)
                        self.assertEqual(process.returncode, 7, errors)
                        messages = [replacement.recv(8192) for _ in range(2)]
                        self.assertTrue(any(b'after restart' in packet for packet in messages))
                        self.assertTrue(any(b'event=completed status=7' in packet for packet in messages))
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=3)

    def test_chatgpt_socket_uses_the_mapped_account_without_supplementary_groups(self):
        source = payload_read_text(TARGET / 'usr/local/libexec/rsyslog-openai-socket')
        self.assertEqual(source.count('/run/rsyslog/openai/chatgpt.sock'), 1)
        self.assertEqual(source.count('/var/log/managed/models/openai/chatgpt/runtime'), 1)
        with tempfile.TemporaryDirectory(prefix='chatgpt-socket-owner-') as temporary:
            root = Path(temporary)
            runtime = root / 'runtime'; runtime.mkdir()
            destination = root / 'collector.sock'
            commands = root / 'bin'; commands.mkdir()
            trace = root / 'trace'
            for name, body in {
                'getent': 'exit 0',
                'stat': 'printf "%s\\n" "$FIXTURE_UID"',
                # Model the Debian service boundary: CAP_CHOWN is available,
                # CAP_FOWNER is absent. chmod must run while root owns it.
                'chown': '''printf "chown %s\\n" "$1" >>"$FIXTURE_TRACE"
[ "${FIXTURE_FAIL:-}" != "$1" ] || exit 1
printf '%s\\n' "${1%%:*}" >"$FIXTURE_OWNER"''',
                'chmod': '''printf "chmod %s\\n" "$1" >>"$FIXTURE_TRACE"
[ "${FIXTURE_FAIL:-}" != chmod ] || exit 1
IFS= read -r owner <"$FIXTURE_OWNER"
[ "$owner" = root ]''',
            }.items():
                command = commands / name
                command.write_text('#!/bin/sh\nset -eu\n' + body + '\n')
                command.chmod(0o700)
            helper = root / 'socket-helper'
            helper.write_text(source.replace('/run/rsyslog/openai/chatgpt.sock', str(destination))
                              .replace('/var/log/managed/models/openai/chatgpt/runtime', str(runtime)))
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as collector:
                collector.bind(str(destination))
                cases = (
                    ('1000', 'root', '', 0, 'chown root:openailogger\nchmod 0660\nchown 1000:openailogger\n'),
                    ('1000', '1000', '', 0, 'chown root:openailogger\nchmod 0660\nchown 1000:openailogger\n'),
                    ('1000', 'root', 'root:openailogger', 1, 'chown root:openailogger\n'),
                    ('1000', 'root', 'chmod', 1, 'chown root:openailogger\nchmod 0660\n'),
                    ('1000', 'root', '1000:openailogger', 1, 'chown root:openailogger\nchmod 0660\nchown 1000:openailogger\n'),
                    ('0', 'root', '', 1, ''),
                    ('60000', 'root', '', 1, ''),
                    ('invalid', 'root', '', 1, ''),
                )
                for owner, initial_owner, fail, expected, commands_run in cases:
                    with self.subTest(owner=owner, initial_owner=initial_owner, fail=fail):
                        trace.unlink(missing_ok=True)
                        owner_file = root / 'socket-owner'
                        owner_file.write_text(initial_owner + '\n')
                        result = subprocess.run(
                            ['/bin/sh', '-eu', str(helper)], cwd=root,
                            env={'PATH': str(commands), 'LC_ALL': 'C',
                                 'FIXTURE_UID': owner, 'FIXTURE_TRACE': str(trace),
                                 'FIXTURE_OWNER': str(owner_file), 'FIXTURE_FAIL': fail},
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=2,
                        )
                        self.assertEqual(result.returncode, expected, result.stderr)
                        if commands_run:
                            self.assertEqual(trace.read_text(), commands_run)
                        else:
                            self.assertFalse(trace.exists())
                        if fail:
                            self.assertIn(b'fatal: managed OpenAI log socket:', result.stderr)
                        if expected == 0:
                            self.assertEqual(owner_file.read_text(), '1000\n')
        for relative in ('etc/systemd/system/rsyslog.service.d/35-openai-chatgpt-socket.conf',
                         'etc/tmpfiles.d/61-openai-chatgpt.conf'):
            self.assertIn('0751', payload_read_text(TARGET / relative))

    def test_collector_startup_errors_have_an_independent_journal_sink(self):
        unit = payload_read_text(TARGET / 'etc/systemd/system/rsyslog.service.d/20-log-layout.conf')
        self.assertIn('\nStandardError=journal\n', unit)
        self.assertNotIn('CapabilityBoundingSet=', unit)


if __name__ == '__main__':
    unittest.main()
