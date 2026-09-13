#!/usr/bin/env python3
"""Installer integration regressions for the eight scoped boot/runtime fixes.

Only fixture roots are written. Renderer/enabler/copy-loop code is real; target
transport and paths are redirected to disposable directories. No native build,
service start, policy load, or hardware access is performed.
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import types
import unittest

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'


def shell_function(path: Path, name: str) -> str:
    text = path.read_text()
    match = re.search(r'^' + re.escape(name) + r'\(\) \{\n.*?^\}\n', text, re.M | re.S)
    if not match:
        raise AssertionError(f'missing shell function {name}: {path}')
    return match.group(0)


class InstallerIntegrationTests(unittest.TestCase):
    def test_actual_pipewire_renderer_preserves_custom_greeter_in_all_four_units(self):
        lib = FORKY / 'scripts/common/lib.sh'
        helpers = '\n'.join(shell_function(lib, name) for name in (
            'installer_escape_sed_replacement', 'installer_apply_scalar_placeholders'))
        for shell in (['/bin/sh'], [shutil.which('busybox'), 'sh'] if shutil.which('busybox') else []):
            if not shell:
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                script = r'''
set -eu
. "$FORKY/scripts/desktop/components.sh"
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
installer_repo_join_var() { printf '%s/%s\n' "$SOURCE" "$2"; }
fetch_hook() { cp "$1" "$2"; }
target_asset_host_path() { printf '%s%s\n' "$DEST" "$1"; }
ensure_target_asset_parent() { mkdir -p "$DEST$(dirname "$1")"; }
target_asset_assert_no_unresolved_installer_placeholders() { ! grep -q '__INSTALLER_' "$1"; }
desktop_log() { :; }
''' + helpers + '\ndesktop_stage_pipewire_user_conditions\n'
                env = dict(os.environ, FORKY=str(FORKY), SOURCE=str(TARGET), DEST=tmp,
                           TMP_ENV_DIR=tmp, LABWC_GREETER_USER='_custom_greeter')
                result = subprocess.run([*shell, '-c', script], env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                files = list(root.glob('etc/systemd/user/*.d/*.conf'))
                self.assertEqual(len(files), 4)
                for path in files:
                    text = path.read_text()
                    self.assertIn('ConditionUser=!_custom_greeter', text)
                    self.assertNotIn('__INSTALLER_', text)
                    self.assertNotIn('ConditionUser=\n', text)
                    self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_grub_owner_uses_real_enabler_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / 'target'
            dest.mkdir()
            # The helper has a literal /target contract. Only this test copy is
            # redirected; the complete original enabling logic is exercised.
            for module in ('grub', 'dbus-broker'):
                text = (FORKY / f'scripts/late/{module}.sh').read_text().replace('/target', str(dest))
                (root / f'{module}.sh').write_text(text)
            shutil.copyfile(TARGET / 'etc/systemd/system/bootprofile-apply.service.tmpl', root / 'bootprofile-apply.service.tmpl')
            (root / 'bootprofile-apply.tmpl').write_text('#!/bin/sh\nexit 0\n')
            script = r'''
set -eu
. "$TEST_ROOT/dbus-broker.sh"
. "$TEST_ROOT/grub.sh"
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
installer_trim_whitespace() { printf '%s' "$1" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'; }
render_target_template() (
  mkdir -p "$(dirname "$2")"
  sed "s|__INSTALLER_FILE_BOOTPROFILE_APPLY__|$FILE_BOOTPROFILE_APPLY|g" "$1" > "$2"
  chmod "$3" "$2"
)
install_target_bootprofile_assets
install_target_bootprofile_assets
'''
            env = dict(os.environ, TEST_ROOT=tmp, TMP_ENV_DIR=tmp,
                       FILE_BOOTPROFILE_APPLY='/usr/libexec/install-tools/bootprofile-apply',
                       FILE_BOOTPROFILE_SERVICE='/etc/systemd/system/bootprofile-apply.service',
                       DIR_SYSTEMD_SYSTEM='/etc/systemd/system', DIR_SYSTEMD_SYSTEM_LIB='/usr/lib/systemd/system',
                       DIR_SYSTEMD_SYSTEM_LEGACY='/lib/systemd/system')
            result = subprocess.run(['/bin/sh', '-c', script], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            link = dest / 'etc/systemd/system/sysinit.target.wants/bootprofile-apply.service'
            self.assertTrue(link.is_symlink())
            self.assertEqual(os.readlink(link), '/etc/systemd/system/bootprofile-apply.service')
            self.assertEqual(len(list(link.parent.iterdir())), 1)
            unit = (dest / 'etc/systemd/system/bootprofile-apply.service').read_text()
            self.assertIn('RemainAfterExit=yes', unit)
            self.assertNotIn('__INSTALLER_', unit)

    @unittest.skipUnless(os.geteuid() == 0, 'copy-loop ownership verification requires root')
    def test_actual_account_copy_loop_installs_wayscriber_with_account_ownership(self):
        text = (FORKY / 'scripts/desktop/components.sh').read_text()
        body = text.split('desktop_install_user_config() {', 1)[1].split('\ndesktop_unit_has_install_entry()', 1)[0]
        loop = re.search(r'^  for rel in \\\n.*?^done\n', body, re.M | re.S)
        self.assertIsNotNone(loop)
        loop = loop.group(0)
        rels = re.findall(r'^    ([.A-Za-z][^\s]+)\s*\\?$', loop, re.M)
        self.assertIn('.config/wayscriber', rels)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skel = root / 'skel'
            home = root / 'home/desktop'
            for rel in rels:
                (skel / rel).mkdir(parents=True, exist_ok=True)
            source = TARGET / 'etc/skel-desktop/.config/wayscriber/config.toml'
            shutil.copyfile(source, skel / '.config/wayscriber/config.toml')
            # cp -a preserves skeleton modes initially; the production function
            # normalizes all private home data after completing its copy loops.
            normalization = re.search(
                r'^find "\$account_home" -xdev -type d .*?^find "\$account_home" -xdev -type f ! .*?\n',
                body, re.M | re.S)
            self.assertIsNotNone(normalization)
            script = ('set -eu\n' +
                      'install -d -m 0700 "$account_home" "$account_home/.config"\n' +
                      loop.replace('src="/etc/skel-desktop/${rel}"', 'src="${TEST_SKEL}/${rel}"') +
                      normalization.group(0))
            env = dict(os.environ, TEST_SKEL=str(skel), account_home=str(home), uid='12345', gid='12345', copied_dirs='0')
            result = subprocess.run(['/bin/sh', '-c', script], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            installed = home / '.config/wayscriber/config.toml'
            self.assertEqual(installed.read_bytes(), source.read_bytes())
            self.assertEqual((installed.stat().st_uid, installed.stat().st_gid), (12345, 12345))
            self.assertEqual(installed.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(installed.stat().st_mode & 0o777, 0o600)
            self.assertEqual(home.stat().st_mode & 0o777, 0o700)


class NvidiaReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = TARGET / 'usr/local/libexec/managed-nvidia-char-links'
        self.module = types.ModuleType('nvidia_second_pass')
        exec(compile(source.read_bytes(), str(source), 'exec'), self.module.__dict__)

    def test_absent_devices_do_not_create_links_or_directories(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.module.reconcile(self.root), 0)
            self.assertEqual(self.module.reconcile(self.root, check=True), 0)
        self.assertFalse((self.root / 'char').exists())

    def test_symlink_device_is_rejected_without_following_it(self):
        (self.root / 'nvidia0').symlink_to('/dev/null')
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertNotEqual(self.module.reconcile(self.root), 0)
        self.assertFalse((self.root / 'char').exists())

    def test_unrelated_device_changes_never_request_reconciliation(self):
        rule = (TARGET / 'etc/udev/rules.d/71-managed-nvidia-char-links.rules').read_text()
        active = [line for line in rule.splitlines() if line and not line.startswith('#')]
        self.assertEqual(len(active), 2)
        for line in active:
            self.assertIn('KERNEL=="nvidia', line)
            self.assertIn('ACTION=="add|change"', line)
            self.assertIn('TAG+="systemd"', line)
            self.assertIn('ENV{SYSTEMD_WANTS}+=', line)
            self.assertNotIn('RUN+=', line)
        unit = (TARGET / 'etc/systemd/system/managed-nvidia-char-links.service').read_text()
        self.assertNotIn('Restart=', unit)
        self.assertNotIn('StartLimitIntervalSec=0', unit)
        self.assertFalse((TARGET / 'etc/systemd/system/managed-nvidia-char-links.path').exists())


if __name__ == '__main__':
    unittest.main()
