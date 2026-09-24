"""Revision-3 logging: real profile renderer, native precedence and bounded routes.

No live journal, mounted storage, system service, or physical device is changed.
Native rsyslog integration tests skip explicitly when its packaged binary is absent.
"""
from __future__ import annotations
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
import stat
import subprocess
import tempfile
import time
import unittest

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
layout = module('managed_log_layout_r3', 'usr/local/libexec/log-layout')
BASE = '[Journal]\nStorage=volatile\nForwardToSyslog=yes\nReadKMsg=no\nSeal=no\n'


class JournalPolicyTests(unittest.TestCase):
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
                    self.assertIn('ForwardToSyslog=yes\n', rendered)
                    self.assertIn('ReadKMsg=no\n', rendered)
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
        for key, bad in [('Storage', 'persistent'), ('ForwardToSyslog', 'no'), ('ReadKMsg', 'yes')]:
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
            (vendor / '99-conflict.conf').write_text('[Journal]\nStorage=persistent\n')
            with self.assertRaises(journal.PolicyError):
                journal.check(BASE, effective())
            (etc / '99-conflict.conf').symlink_to('/dev/null')
            journal.check(BASE, effective())
            (etc / '90-local.conf').write_text('[Journal]\nForwardToSyslog=no\n')
            with self.assertRaises(journal.PolicyError):
                journal.check(BASE, effective())

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

    def test_only_exact_old_root_owned_auth_link_migrates(self):
        path = self.root / 'var/log/auth.log'; path.symlink_to(layout.OLD_AUTH)
        layout.migrate_auth_link(self.root)
        self.assertEqual(os.readlink(path), layout.NEW_AUTH)
        layout.migrate_auth_link(self.root)
        self.assertEqual(os.readlink(path), layout.NEW_AUTH)
        self.assertFalse(list(path.parent.glob('.auth-link-*')))

    def test_administrator_real_file_link_and_unowned_link_are_preserved(self):
        path = self.root / 'var/log/auth.log'
        path.write_bytes(b'legacy auth remains')
        layout.migrate_auth_link(self.root); self.assertEqual(payload_read_bytes(path), b'legacy auth remains')
        path.unlink(); path.symlink_to('/administrator/auth.log')
        layout.migrate_auth_link(self.root); self.assertEqual(os.readlink(path), '/administrator/auth.log')
        path.unlink(); path.symlink_to(layout.OLD_AUTH); os.chown(path, 65534, 65534, follow_symlinks=False)
        layout.migrate_auth_link(self.root); self.assertEqual(os.readlink(path), layout.OLD_AUTH)

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
    def test_journal_input_and_private_sockets_are_not_duplicated(self):
        text = payload_read_text(TARGET / 'etc/rsyslog.conf')
        self.assertIn('module(load="imuxsock" SysSock.Use="on"', text)
        self.assertIn('SysSock.Annotate="on" SysSock.ParseTrusted="on"', text)
        self.assertNotIn('module(load="imjournal"', text)
        self.assertEqual(text.count('module(load="imklog")'), 1)
        self.assertNotIn('StateFile=', text)
        self.assertNotIn('load="omjournal"', text)
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
                self.assertNotRegex(active, r'\bimfile\b|/(?:vendor|runtime)\.log')
        for path in TARGET.glob('etc/audit/*/auditd.conf.tmpl'):
            text = logging_text(path.read_text())
            self.assertIn('log_file = /var/log/managed/system/audit/auditd.log', text)
        plugin = payload_read_text(TARGET/'etc/audit/plugins.d/syslog.conf')
        self.assertIn('active = yes',plugin)

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


if __name__ == '__main__':
    unittest.main()
