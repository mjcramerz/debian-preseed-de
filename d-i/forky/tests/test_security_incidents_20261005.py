"""October 5 AppArmor grants and duplicate Edge attachment regressions.

The installer function runs against private temporary target trees. The native
AppArmor reader uses synthetic profiles; no host policy is modified or loaded.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from payload_fixture import read_text


SEED = Path(__file__).resolve().parents[1]
AA = SEED / 'hooks/target/etc/apparmor.d'
SECURITY = SEED / 'scripts/late/security.sh'


def profile(file: str, name: str) -> str:
    text = read_text(AA / file, encoding='utf-8')
    return text.split('profile ' + name + ' ', 1)[1].split('\n}', 1)[0]


class AppArmorGrantTests(unittest.TestCase):
    def test_capture_can_save_its_cwd_without_reading_home_file_contents(self):
        policy = profile('desktop-wrappers', 'labwc-capture')
        self.assertIn('owner @{HOME}/ r,', policy)
        self.assertNotRegex(policy, r'(?m)^\s*(?:owner )?@\{HOME\}/\*\*')
        self.assertNotRegex(policy, r'(?m)^\s*(?:owner )?@\{HOME\}/ [^,]*[wklmx]')

    def test_terminal_hangup_has_both_exact_signal_endpoints(self):
        terminal = profile('desktop-utilities', 'desktop-launcher')
        action = profile('desktop-wrappers', 'labwc-security-action')
        self.assertIn('signal (send) set=(hup) peer=labwc-security-action,', terminal)
        self.assertIn('signal (receive) set=(hup) peer=desktop-launcher,', action)
        self.assertNotRegex(action, r'(?m)^\s*signal \(receive\)\s*,')

    def test_crashpad_memory_access_is_owner_read_only_with_same_profile_ptrace(self):
        policy = read_text(AA / 'local/vivaldi-bin', encoding='utf-8')
        self.assertIn('owner @{PROC}/[0-9]*/mem r,', policy)
        self.assertNotRegex(policy, r'(?m)^\s*@\{PROC\}/\[0-9\]\*/mem ')
        self.assertNotRegex(policy, r'(?m)^\s*owner @\{PROC\}/\[0-9\]\*/mem [^,]*[wklmx]')
        runtime = read_text(AA / 'abstractions/electron-runtime', encoding='utf-8')
        self.assertIn('ptrace (read, trace) peer=@{profile_name},', runtime)
        self.assertNotRegex(runtime, r'ptrace \([^)]*trace[^)]*\) peer=(?:unconfined|\*)')


class EdgeAttachmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='edge-attachment-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profiles = self.root / 'apparmor.d'
        self.profiles.mkdir()
        for name in ('microsoft-edge-stable', 'msedge'):
            (self.profiles / name).write_text(
                f'profile {name} /opt/microsoft/msedge/msedge {{\n}}\n', encoding='utf-8')
        source = SECURITY.read_text(encoding='utf-8')
        match = re.search(r'^apparmor_disable_superseded_edge_profile\(\) \{.*?^\}', source, re.M | re.S)
        self.assertIsNotNone(match)
        # Relocate only the hard-coded installer target; execute the actual
        # function body and retain its symlink/attachment/failure checks.
        function = match.group().replace('edge_profile_dir=/target/etc/apparmor.d', 'edge_profile_dir=$1')
        self.helper = self.root / 'disable-edge.sh'
        self.helper.write_text(
            '#!/bin/sh\nset -eu\n'
            'installer_fatal() { printf "%s\\n" "$*" >&2; exit 1; }\n'
            + function + '\napparmor_disable_superseded_edge_profile "$1"\n', encoding='utf-8')

    def invoke(self, shell=('/bin/sh',)):
        return subprocess.run([*shell, str(self.helper), str(self.profiles)],
                              capture_output=True, text=True, encoding='utf-8', timeout=5)

    def test_disables_only_the_duplicate_and_preserves_conffiles_in_both_shells(self):
        shells = [('/bin/sh',)]
        if shutil.which('busybox'):
            shells.append((shutil.which('busybox'), 'ash'))
        originals = {name: (self.profiles / name).read_bytes()
                     for name in ('microsoft-edge-stable', 'msedge')}
        for shell in shells:
            with self.subTest(shell=shell):
                result = self.invoke(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                # Repeated staging retains the same precise disable entry.
                self.assertEqual(self.invoke(shell).returncode, 0)
                link = self.profiles / 'disable/msedge'
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.readlink(), Path('../msedge'))
                self.assertEqual(list(link.parent.iterdir()), [link])
                for name, content in originals.items():
                    self.assertEqual((self.profiles / name).read_bytes(), content)

    def test_no_distribution_alias_needs_no_disable_entry(self):
        (self.profiles / 'msedge').unlink()
        self.assertEqual(self.invoke().returncode, 0)
        self.assertFalse((self.profiles / 'disable').exists())

    def test_missing_vendor_or_unexpected_attachment_is_refused_before_mutation(self):
        vendor = self.profiles / 'microsoft-edge-stable'
        vendor.unlink()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('managed Edge AppArmor profile', result.stderr)
        self.assertFalse((self.profiles / 'disable').exists())
        vendor.write_text('profile microsoft-edge-stable /different/executable {\n}\n', encoding='utf-8')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unexpected Edge AppArmor attachment', result.stderr)
        self.assertFalse((self.profiles / 'disable').exists())

    def test_symlinked_inputs_and_disable_directory_are_refused(self):
        alias = self.profiles / 'msedge'
        alias.unlink()
        alias.symlink_to('microsoft-edge-stable')
        self.assertNotEqual(self.invoke().returncode, 0)
        alias.unlink()
        alias.write_text('profile msedge /opt/microsoft/msedge/msedge {\n}\n', encoding='utf-8')
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        (self.profiles / 'disable').symlink_to(elsewhere, target_is_directory=True)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('real directory', result.stderr)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_unexpected_disable_entry_is_preserved(self):
        (self.profiles / 'disable').mkdir()
        link = self.profiles / 'disable/msedge'
        link.symlink_to('../microsoft-edge-stable')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(link.readlink(), Path('../microsoft-edge-stable'))

    def test_installer_calls_helper_and_mode_reconciliation_cannot_reenable_alias(self):
        source = SECURITY.read_text(encoding='utf-8')
        stage = source.split('stage_target_desktop_apparmor_profiles() {', 1)[1].split('\n}', 1)[0]
        self.assertIn('apparmor_disable_superseded_edge_profile\n', stage)
        rows = [line.split() for line in read_text(AA.parent / 'apparmor/modes.conf.tmpl', encoding='utf-8').splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
        self.assertNotIn('msedge', [row[2] for row in rows])
        self.assertEqual([row[1:] for row in rows if row[2] == 'microsoft-edge-stable'],
                         [['if-executable', 'microsoft-edge-stable', '/usr/bin/microsoft-edge-stable']])

    @unittest.skipUnless(importlib.util.find_spec('apparmor'), 'native AppArmor Python tools unavailable')
    def test_real_logprof_reader_reproduces_conflict_then_accepts_disabled_alias(self):
        code = ('import sys; import apparmor.aa as aa; '
                'aa.init_aa(profiledir=sys.argv[1]); aa.read_profiles(); '
                'print("PROFILE_READ_COMPLETED")')
        def read_profiles():
            return subprocess.run([sys.executable, '-B', '-c', code, str(self.profiles)],
                                  capture_output=True, text=True, encoding='utf-8', timeout=10)
        conflict = read_profiles()
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn('Profile for /opt/microsoft/msedge/msedge exists', conflict.stderr)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        fixed = read_profiles()
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        self.assertIn('PROFILE_READ_COMPLETED', fixed.stdout)


if __name__ == '__main__':
    unittest.main()
