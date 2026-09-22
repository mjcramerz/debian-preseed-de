"""Scoped resource-policy integration; no running managers or cgroups are changed."""
from __future__ import annotations

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

SEED = Path(__file__).resolve().parents[1]
ROOT = SEED.parents[1]
TARGET = SEED / 'hooks/target'
PROFILES = sorted((SEED / 'hosts/profiles').glob('*.env'))
TOKEN = re.compile(r'__(?:INSTALLER_)?SYSTEMD_[A-Z0-9_]+__')
USER_BASE = 'etc/skel-desktop/.config/systemd/user'
CLASSES = ('session', 'app', 'background')
WEIGHT_KEYS = {f'SYSTEMD_IOWEIGHT_HOME_USER_{name.upper()}_SLICE_D' for name in CLASSES} | {
    'SYSTEMD_IOWEIGHT_HOME_USER_LABWC_COMPOSITOR_SERVICE_D',
    'SYSTEMD_IOWEIGHT_SYSTEM_MAINTENANCE_SLICE_D',
    'SYSTEMD_IOWEIGHT_SYSTEM_BACKGROUND_SLICE_D',
}
TEMPLATES = [TARGET / f'{USER_BASE}/{name}.slice.d/60-resources.conf' for name in CLASSES] + [
    TARGET / f'{USER_BASE}/labwc-compositor.service.d/60-resources.conf',
    TARGET / 'etc/systemd/system/system-maintenance.slice.d/60-resources.conf',
    TARGET / 'etc/systemd/system/system-background.slice.d/60-resources.conf',
    TARGET / 'etc/systemd/user/pipewire.service.d/60-resources.conf',
    TARGET / 'etc/systemd/user/pipewire-pulse.service.d/60-resources.conf',
    TARGET / 'etc/systemd/user/filter-chain.service.d/60-resources.conf',
    TARGET / 'etc/systemd/system/systemd-coredump.socket.d/60-poll-limit.conf',
    TARGET / 'etc/systemd/system.conf.d/60-resource-accounting.conf',
    TARGET / 'etc/systemd/user.conf.d/60-resource-accounting.conf',
    TARGET / 'etc/systemd/coredump.conf.d/60-managed-limits.conf',
    TARGET / 'etc/systemd/journald.conf.d/10-storage.conf',
]
SERVICE_CLASSES = {
    'labwc-compositor': 'session',
    'waybar': 'app', 'crystal-dock': 'app',
    'kanshi': 'session', 'labwc-output-watch': 'session', 'swayidle': 'session',
    'labwc-calendar-sync': 'background',
    'labwc-kwallet-portal': 'session', 'labwc-ssh-key-load': 'session',
}


class ResourcePolicyTests(unittest.TestCase):
    def shell(self, command, *, profile=None, override='', shell='dash', check=True):
        sources = '\n'.join('. ' + shlex.quote(str(SEED / path)) for path in (
            'scripts/common/lib.sh', 'scripts/common/target.sh',
            'scripts/late/target-assets.sh', 'scripts/late/templates.sh',
            'scripts/late/storage-maintenance.sh', 'scripts/desktop/components.sh'))
        script = ('set -eu\n' + sources + '\n. ' + shlex.quote(str(profile or PROFILES[0])) +
                  '\ninstaller_fatal() { printf "%s\\n" "$*" >&2; return 1; }\n' +
                  override + '\n' + command)
        argv = ['busybox', 'sh'] if shell == 'busybox' else [shell]
        result = subprocess.run([*argv, '-c', script], text=True, capture_output=True, timeout=40)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def staging(self, tmp):
        return f'''
INSTALLER_TARGET_DIR={shlex.quote(str(Path(tmp) / 'target'))}
TMP_ENV_DIR={shlex.quote(str(tmp))}
DIR_HOOKS_TARGET=hooks/target
FILE_JOURNALD_STORAGE_CONF=/etc/systemd/journald.conf.d/10-storage.conf
installer_repo_join_var() {{ printf 'hooks/target/%s\\n' "$2"; }}
fetch_hook() {{ cp -- {shlex.quote(str(SEED))}/"$1" "$2"; }}
desktop_log() {{ :; }}
desktop_user_unit_source_path() {{
  [ -f "$INSTALLER_TARGET_DIR/usr/lib/systemd/user/$1" ] || return 1
  printf '/usr/lib/systemd/user/%s\n' "$1"
}}
'''

    def test_all_10_profiles_define_exactly_six_managed_weight_keys(self):
        self.assertEqual(len(PROFILES), 10)
        for profile in PROFILES:
            with self.subTest(profile=profile.name):
                keys = re.findall(r'^(SYSTEMD_IOWEIGHT_(?!ENABLE=)[A-Z0-9_]+)=', profile.read_text(), re.M)
                self.assertEqual(set(keys), WEIGHT_KEYS)
                self.assertEqual(len(keys), len(WEIGHT_KEYS))
                self.assertRegex(profile.read_text(), r'(?m)^PODMAN_SERVICE_SLICE_IO_WEIGHT=100$')
                mapping = dict(line.split('=', 1) for line in
                               self.shell('systemd_resource_placeholder_map', profile=profile).stdout.splitlines())
                requested = {token[2:-2] for path in TEMPLATES for token in TOKEN.findall(path.read_text())}
                self.assertEqual(requested, set(mapping))

    def test_all_profiles_both_modes_use_production_literal_renderer(self):
        for profile in PROFILES:
            for enabled in ('true', 'false'):
                with self.subTest(profile=profile.name, io=enabled), tempfile.TemporaryDirectory() as tmp:
                    file = Path(tmp) / 'resources'
                    file.write_text('\n'.join(path.read_text() for path in TEMPLATES))
                    self.shell(f'TMP_ENV_DIR={shlex.quote(tmp)}\n'
                               'apply_systemd_resource_placeholders "$TMP_ENV_DIR/resources"',
                               profile=profile, override=f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\nSYSTEMD_IOWEIGHT_ENABLE={enabled}')
                    text = file.read_text()
                    self.assertFalse(TOKEN.search(text))
                    weights = re.findall(r'^IOWeight=(\d+)$', text, re.M)
                    self.assertEqual(weights, ['200', '100', '30', '300', '30', '50'] if enabled == 'true' else [])
                    self.assertEqual(text.count('DefaultIOAccounting=yes' if enabled == 'true'
                                                else 'DefaultIOAccounting=no'), 2)
                    self.assertNotIn('IOWeight=\n', text)

    def test_invalid_inputs_and_missing_weights_fail_before_publication(self):
        cases = {
            'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE': ['', 'yes', 'TRUE', 'true\nfalse'],
            'SYSTEMD_IOWEIGHT_ENABLE': ['', 'yes', 'TRUE', 'true\nfalse'],
            'SYSTEMD_IOWEIGHT_HOME_USER_APP_SLICE_D':
                ['IOWeight=0', 'IOWeight=10001', 'IOWeight=01', 'CPUWeight=100',
                 'IOWeight=1\nMemoryMax=1', 'IOWeight=100\r', '$(id)'],
            'SYSTEMD_CPUWEIGHT_HOME_USER_LABWC_COMPOSITOR_SERVICE_D': ['0', '10001', '0300', '300\nSlice=app.slice'],
            'SYSTEMD_CPUWEIGHT_USER_AUDIO_SERVICE_D': ['', '200s', '$(id)'],
            'SYSTEMD_COREDUMP_POLL_LIMIT_INTERVAL_SEC': ['0', '1', '61', '2s'],
            'SYSTEMD_COREDUMP_POLL_LIMIT_BURST': ['0', '1000001', '-1', '064', '64\nAccept=no'],
            'SYSTEMD_COREDUMP_STORAGE': ['journal', 'external\nCompress=no'],
            'SYSTEMD_COREDUMP_MAX_USE': ['0', '0M', '-1M', 'infinity', '1G\n2G', '9999999999G'],
            'SYSTEMD_JOURNAL_SYSTEM_MAX_FILES': ['0', '1000001', '02', '16\n17'],
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(key=name, value=value):
                    self.assertNotEqual(self.shell('systemd_resource_placeholder_map',
                        override=name+'='+shlex.quote(value), check=False).returncode, 0)
        for enabled in ('true', 'false'):
            for setting in ('unset SYSTEMD_IOWEIGHT_HOME_USER_APP_SLICE_D',
                            'SYSTEMD_IOWEIGHT_HOME_USER_APP_SLICE_D="IOWeight=bogus"'):
                self.assertNotEqual(self.shell('systemd_resource_placeholder_map', override=
                    f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\n{setting}', check=False).returncode, 0)

    def test_empty_individual_weight_and_core_metadata_only_mode(self):
        result = self.shell('systemd_resource_placeholder_map', override='''
SYSTEMD_IOWEIGHT_HOME_USER_APP_SLICE_D=""
SYSTEMD_COREDUMP_STORAGE=none
SYSTEMD_COREDUMP_PROCESS_SIZE_MAX=0
SYSTEMD_COREDUMP_EXTERNAL_SIZE_MAX=0
''')
        mapping = dict(line.split('=', 1) for line in result.stdout.splitlines())
        self.assertEqual(mapping['SYSTEMD_IOWEIGHT_HOME_USER_APP_SLICE_D'], '')
        self.assertEqual(mapping['SYSTEMD_COREDUMP_PROCESS_SIZE_MAX'], '0')
        self.assertEqual(mapping['SYSTEMD_COREDUMP_STORAGE'], 'none')

    def test_busybox_and_dash_agree(self):
        if not shutil.which('busybox'):
            self.skipTest('BusyBox is unavailable')
        for enabled in ('true', 'false'):
            override = f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\nSYSTEMD_IOWEIGHT_ENABLE={enabled}'
            self.assertEqual(self.shell('systemd_resource_placeholder_map', override=override).stdout,
                             self.shell('systemd_resource_placeholder_map', override=override,
                                        shell='busybox').stdout)

    def test_only_six_approved_templates_introduce_io_weights(self):
        found = []
        for path in TARGET.rglob('*'):
            if not path.is_file() or path.suffix not in ('.conf', '.tmpl', '.service', '.scope', '.slice'):
                continue
            if '__SYSTEMD_IOWEIGHT_' in path.read_text():
                found.append(path)
        self.assertEqual(set(found), set(TEMPLATES[:6]))
        for service, cls in SERVICE_CLASSES.items():
            text = (TARGET / f'{USER_BASE}/{service}.service.d/60-resource-class.conf').read_text()
            active = [line for line in text.splitlines() if line and not line.startswith('#')]
            self.assertEqual(active, ['[Service]', f'Slice={cls}.slice'])
        self.assertFalse(list(TARGET.glob('etc/systemd/system/managed*.slice')))
        self.assertEqual(len(list(TARGET.rglob('70-no-core.conf'))), 4)
        for path in TARGET.glob('etc/systemd/user/*/60-resources.conf'):
            self.assertNotIn('IOWeight=', path.read_text())
            self.assertNotIn('__SYSTEMD_IOWEIGHT_', path.read_text())
        self.assertFalse((TARGET / f'{USER_BASE}/app-.scope.d/60-resources.conf').exists())

    def test_original_workload_policy_is_byte_identical(self):
        # Hashes from the user's original archive, not from the rejected revision.
        manifest = json.loads((SEED / 'tests/fixtures/resource-policy-original.json').read_text())
        for relative, expected in manifest['sha256'].items():
            with self.subTest(path=relative):
                original = (ROOT / relative).read_bytes()
                # R6 isolates zram maintenance without changing its CPU/IO/RAM
                # weights. Reverse exact reviewed additions, never rebaseline.
                zram_reversions = json.loads((SEED / 'tests/fixtures/zram-isolation-workload-reversions.json').read_text())
                for change in zram_reversions.get(relative, []):
                    current = change['current'].encode()
                    self.assertEqual(original.count(current), 1)
                    original = original.replace(current, change['historical'].encode(), 1)
                # Reverse only the exact missing-executable corrections.
                # Historical workload hashes remain unchanged.
                metadata_migrations = {
                    # Save confirmation/veto time and exit classification are
                    # intentional lifecycle changes, not resource policy.
                    'd-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-session-state@.service': (
                        (b'TimeoutStartSec=285s\n# 77 is a verified user/save veto, not permission to continue shutdown.\nSuccessExitStatus=77\n',
                         b'TimeoutStartSec=145s\n'),
                    ),
                    # Wallpaper child supervision changes only these comments;
                    # retain the original immutable workload-policy hash.
                    'd-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/swaybg.service': (
                        (b'# The persistent supervisor coalesces selections and reaps its own children.\n# Restart only the supervisor after an unexpected failure.\n',
                         b'# Waypaper applies validated selections through an explicit service restart.\n# Keep automatic restarts for unexpected exits only.\n'),
                    ),
                    'd-i/forky/hooks/target/usr/local/libexec/podman-devops-host': (
                        (b"    if filesystem not in ('btrfs', 'ext2', 'ext3', 'ext4', 'xfs', 'f2fs'):\n",
                         b"    if filesystem not in ('btrfs', 'ext2/ext3', 'xfs', 'f2fs'):\n"),
                        (b"    filesystem = run(['/usr/bin/find', '-P', str(POOL), '-maxdepth', '0', '-printf', '%F'])\n",
                         b"    filesystem = run(['/usr/bin/stat', '-f', '-c', '%T', '--', str(POOL)])\n"),
                    ),
                    'd-i/forky/scripts/desktop/labwc.sh': (
                        (b'  [ "$(chroot "${INSTALLER_TARGET_DIR:-/target}" /usr/bin/find -P "$installer_helper" -maxdepth 0 -printf \'%U:%G:%m\')" = 0:0:755 ] ||\n',
                         b'  [ "$(chroot "${INSTALLER_TARGET_DIR:-/target}" /usr/bin/stat -c \'%u:%g:%a\' -- "$installer_helper")" = 0:0:755 ] ||\n'),
                        (b'  [ "$(chroot "${INSTALLER_TARGET_DIR:-/target}" /usr/bin/find -P "$session_helper" -maxdepth 0 -printf \'%U:%G:%m\')" = 0:0:700 ] ||\n',
                         b'  [ "$(chroot "${INSTALLER_TARGET_DIR:-/target}" /usr/bin/stat -c \'%u:%g:%a\' -- "$session_helper")" = 0:0:700 ] ||\n'),
                    ),
                    'd-i/forky/scripts/late/podman.sh': (
                        (b'  # The native filesystem-name lookup reads the target mount table. Use the\n  # shared executor so d-i\'s in-target performs its normal proc/chroot setup.\n  filesystem=$(target_exec /usr/bin/find -P "$relative" -maxdepth 0 -printf \'%F\') ||\n    podman_fatal \'target findutils could not inspect the Podman storage filesystem\'\n',
                         b'  filesystem=$(chroot "$target" /usr/bin/stat -f -c \'%T\' -- "$relative") ||\n    podman_fatal \'target coreutils could not inspect the Podman storage filesystem\'\n'),
                        (b'    btrfs|ext2|ext3|ext4|xfs|f2fs) ;;\n',
                         b'    btrfs|ext2/ext3|xfs|f2fs) ;;\n'),
                    ),
                }
                for current, previous in metadata_migrations.get(relative, ()):
                    self.assertEqual(original.count(current), 1)
                    original = original.replace(current, previous, 1)
                if relative == 'd-i/forky/scripts/desktop/labwc.sh':
                    # Opt-in package reconciliation is independent of workload
                    # policy. Exclude only the reviewed exact helper and calls,
                    # preserving the original immutable hash for everything else.
                    kanshi_block = re.search(br'^desktop_install_kanshi_policy\(\) \(\n.*?^\)\n\n',
                                             original, re.M | re.S)
                    self.assertIsNotNone(kanshi_block)
                    self.assertEqual(hashlib.sha256(kanshi_block.group(0)).hexdigest(),
                                     'e9bea24ba2d45756915ad8fc5dd59bcd5d8f42991cdc5686d66c677dab8694df')
                    original = original.replace(kanshi_block.group(0), b'', 1)
                    for added in (b'  desktop_install_kanshi_policy\n',
                                  b'  desktop_verify_kanshi_policy\n',
                                  b'  desktop_verify_native_menus\n'):
                        self.assertEqual(original.count(added), 1)
                        original = original.replace(added, b'', 1)
                    logger_default = b'LABWC_ENABLE_KANSHI:-false'
                    self.assertEqual(original.count(logger_default), 1)
                    original = original.replace(logger_default, b'LABWC_ENABLE_KANSHI:-true', 1)
                    # The categorized-menu task explicitly changes menu policy
                    # and adds this exact dependency check, not workload policy.
                    menu_default = b'LABWC_MENU_COMMAND:-labwc-main-menu'
                    self.assertEqual(original.count(menu_default), 1)
                    original = original.replace(menu_default, b'LABWC_MENU_COMMAND:-labwc-fuzzel launcher', 1)
                    gio_check = (
                        b'  # python3-gi is already a selected desktop dependency. Verify the small GIO\n'
                        b'  # Unix binding used by the on-demand menu in the installed target, not the d-i\n'
                        b'  # interpreter. No graphical session or root application discovery is needed.\n'
                        b'  run_in_target "verify GIO desktop-entry binding" /usr/bin/python3 -I -c \'\n'
                        b'import gi\n'
                        b'gi.require_version("Gio", "2.0")\n'
                        b'gi.require_version("GioUnix", "2.0")\n'
                        b'from gi.repository import Gio, GioUnix\n'
                        b'assert Gio.AppInfo and GioUnix.DesktopAppInfo\n'
                        b"'\n"
                    )
                    self.assertEqual(original.count(gio_check), 1)
                    original = original.replace(gio_check, b'', 1)
                    # Exclude only the four explicitly added installer calls.
                    # Hardware tuning is separate; original workload policy
                    # bytes must still match the unchanged historical fixture.
                    for added in (b'  desktop_resctl_bench_preflight_target_architecture\n',
                                  b'  desktop_install_resctl_bench\n',
                                  b'  desktop_install_hardware_tuning\n',
                                  b'  desktop_install_fonts\n'):
                        self.assertEqual(original.count(added), 1)
                        original = original.replace(added, b'', 1)
                self.assertEqual(hashlib.sha256(original).hexdigest(), expected)
        for profile in PROFILES:
            # The separate resctl-bench suite verifies every exact pin/value.
            # Remove just its added block, not any original profile policy.
            menu_policy = 'LABWC_MENU_COMMAND="labwc-main-menu"'
            self.assertEqual(profile.read_text().count(menu_policy), 1)
            profile_text = profile.read_text()
            # The I/O-PSI throttle is an intentional new profile policy block.
            profile_text, io_blocks = re.subn(
                r'# I/O PSI throttles pressure writeback; these are policy defaults, not calibration.\n'
                r'(?:ZRAM_IO_PSI_[A-Z0-9_]+="[^"\n]*"\n){7}', '', profile_text)
            self.assertEqual(io_blocks, 1)
            profile_text = profile_text.replace(menu_policy, 'LABWC_MENU_COMMAND="labwc-fuzzel launcher"', 1)
            # Session repair adds geometry only, not workload policy. Verify
            # each new value against its original search setting before removing
            # precisely this block for the unchanged historical hash fixture.
            geometry = '# Main menu shares application-search geometry; management pickers stay compact.\n'
            for added, existing in (
                    ('MAIN_MENU_WIDTH', 'WIDTH'), ('MAIN_MENU_LINES', 'LINES'),
                    ('INTERNAL_MAIN_MENU_WIDTH', 'INTERNAL_WIDTH'),
                    ('INTERNAL_MAIN_MENU_LINES', 'INTERNAL_LINES')):
                value = re.search(r'^LABWC_FUZZEL_' + existing + r'="([0-9]+)"$',
                                  profile_text, re.M)
                self.assertIsNotNone(value)
                geometry += 'LABWC_FUZZEL_' + added + '="' + value[1] + '"\n'
            self.assertEqual(profile_text.count(geometry), 1)
            profile_text = profile_text.replace(geometry, '', 1)
            # R5 changes only the requested storage sizing and its comments.
            # Reverse exact reviewed hunks, preserving the original workload
            # fingerprint. The dynamic-storage suite executes the new policy.
            reversions = json.loads((SEED / 'tests/fixtures/dynamic-storage-profile-reversions.json').read_text())
            for change in reversions.get(profile.name, []):
                self.assertEqual(profile_text.count(change['current']), 1)
                profile_text = profile_text.replace(change['current'], change['historical'], 1)
            # Governor ownership moved to CPU-family fragments on 2026-09-19.
            # Restore only those three removed tokens for this historical hash;
            # every other original workload/profile byte must still agree.
            for label, governor in (('DEFAULT', 'schedutil'), ('HARDENED', 'powersave'),
                                    ('PERFORMANCE', 'performance')):
                profile_text, restored = re.subn(
                    r'^(GRUB_PROFILE_' + label + r'_FLAGS="[^"\n]*)( mitigations=)',
                    lambda match: match[1] + ' cpufreq.default_governor=' + governor + match[2],
                    profile_text, flags=re.M)
                self.assertEqual(restored, 1)
            original, count = re.subn(
                r'# Native x86-64 resource-control benchmark release \(installation only\)\.\n'
                r'# Native CPU compatibility is checked with unprivileged --version on the target\.\n'
                r'(?:RESCTL_BENCH_[A-Z0-9_]+="[^"\n]*"\n){8}\n',
                '', profile_text, count=1)
            self.assertEqual(count, 1)
            # Release pins vary per profile; their validators own pin policy.
            # Remove only the three-key block, preserving every workload byte
            # and the original historical hash fixture.
            original, tomat_count = re.subn(
                r'\n# Pinned Tomat bootstrap release; all three values must be updated together\.\n'
                r'# Installation verifies this digest without consulting the mutable latest API\.\n'
                r'SOFTWARE_TOMAT_TAG="[^"\n]*"\n'
                r'SOFTWARE_TOMAT_URL="[^"\n]*"\n'
                r'SOFTWARE_TOMAT_SHA256="[^"\n]*"\n\n',
                '', original, count=1)
            self.assertEqual(tomat_count, 1)
            prefix = original.split('\n# Systemd accounting and user resource classes.', 1)[0]
            self.assertEqual(hashlib.sha256((prefix.rstrip()+'\n').encode()).hexdigest(),
                             manifest['profile_prefix_sha256'][profile.name])
        templates = (SEED / 'scripts/late/templates.sh').read_text().split(
            '# This allowlist is intentionally limited', 1)[0]
        self.assertNotIn('apply_systemd_resource_placeholders', templates)

    def test_staging_paths_modes_and_disabled_republication(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            for name in SERVICE_CLASSES:
                dest = target / f'{USER_BASE}/{name}.service'
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(TARGET / f'{USER_BASE}/{name}.service', dest)
            for enabled in ('true', 'false', 'true'):
                self.shell(self.staging(tmp)+'''
stage_target_systemd_resource_policy_assets
desktop_install_user_resource_policy
''', override=f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\nSYSTEMD_IOWEIGHT_ENABLE={enabled}')
                for cls in CLASSES:
                    path = target / f'{USER_BASE}/{cls}.slice.d/60-resources.conf'
                    self.assertEqual('IOWeight=' in path.read_text(), enabled == 'true')
                    self.assertEqual(path.stat().st_mode & 0o777, 0o644)
                    self.assertEqual(path.parent.stat().st_mode & 0o777, 0o755)
                for name, cls in SERVICE_CLASSES.items():
                    text = (target / f'{USER_BASE}/{name}.service.d/60-resource-class.conf').read_text()
                    self.assertIn(f'Slice={cls}.slice', text)
                compositor = target / f'{USER_BASE}/labwc-compositor.service.d/60-resources.conf'
                self.assertIn('CPUWeight=300', compositor.read_text())
                self.assertEqual('IOWeight=300' in compositor.read_text(), enabled == 'true')
                for name in ('maintenance', 'background'):
                    text = (target / f'etc/systemd/system/system-{name}.slice.d/60-resources.conf').read_text()
                    self.assertEqual('IOWeight=' in text, enabled == 'true')
                socket = (target / 'etc/systemd/system/systemd-coredump.socket.d/60-poll-limit.conf').read_text()
                self.assertNotRegex(socket, r'(?m)^MaxConnections(?:PerSource)?=')
                self.assertIn('PollLimitIntervalSec=2s', socket)
                self.assertIn('PollLimitBurst=64', socket)
                for manager in ('system', 'user'):
                    text = (target / f'etc/systemd/{manager}.conf.d/60-resource-accounting.conf').read_text()
                    self.assertIn('DefaultMemoryAccounting=yes', text)
                    self.assertIn('DefaultTasksAccounting=yes', text)
                    self.assertNotRegex(text, r'(?m)^DefaultCPUAccounting=')
                    self.assertIn('DefaultIOAccounting='+('yes' if enabled == 'true' else 'no'), text)
                text = (target / 'etc/systemd/system/user@.service.d/60-resource-delegation.conf').read_text()
                self.assertIn('Delegate=\nDelegate=cpuset cpu pids memory io\n', text)
                original = TARGET / 'etc/systemd/system/user-1000.slice.d/50-resource-accounting.conf'
                self.assertEqual((target / original.relative_to(TARGET)).read_bytes(), original.read_bytes())
                self.assertFalse(list(target.rglob('.installer-asset.*')))

    def test_optional_units_do_not_get_orphan_class_dropins(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            self.shell(self.staging(tmp)+'desktop_install_user_resource_policy')
            # Prefix policy for transient units is intentional; no base file exists.
            self.assertEqual({p.parent.name for p in target.rglob('60-resource-class.conf')},
                             {'labwc-power-lock-.service.d', 'app-.scope.d'})
            self.assertEqual(len(list(target.rglob('60-resources.conf'))), 3)
            self.assertFalse((target / 'etc/systemd/user').exists())

    def test_bad_profile_preserves_existing_policy_and_cleans_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            relative = 'etc/systemd/system.conf.d/60-resource-accounting.conf'
            dest = target / relative; dest.parent.mkdir(parents=True); dest.write_text('original\n')
            result = self.shell(self.staging(tmp)+f'''
SYSTEMD_IOWEIGHT_HOME_USER_APP_SLICE_D='IOWeight=10001'
render_target_resource_asset hooks/target/{relative} /{relative} 0644
''', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(dest.read_text(), 'original\n')
            self.assertFalse(list(target.rglob('.installer-asset.*')))

    def test_unknown_placeholder_fails_atomic_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            relative = 'etc/systemd/system.conf.d/60-resource-accounting.conf'
            dest = target / relative; dest.parent.mkdir(parents=True); dest.write_text('original\n')
            result = self.shell(self.staging(tmp)+f'''
fetch_hook() {{ printf '[Manager]\\nDefaultIOAccounting=__SYSTEMD_NOT_ALLOWED__\\n' >"$2"; }}
render_target_resource_asset unused /{relative} 0644
''', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unresolved systemd resource placeholder', result.stderr)
            self.assertEqual(dest.read_text(), 'original\n')

    def test_no_target_symlink_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            outside = Path(tmp) / 'outside'; outside.mkdir()
            (target / 'etc').symlink_to(outside, target_is_directory=True)
            result = self.shell(self.staging(tmp)+'stage_target_systemd_resource_policy_assets', check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(outside.iterdir()), [])

    def test_journal_default_and_nondefault_storage_survive_installer_validation(self):
        for values in ('', 'SYSTEMD_JOURNAL_SYSTEM_MAX_USE=512M\n'
                       'SYSTEMD_JOURNAL_RUNTIME_MAX_USE=32M\n'
                       'SYSTEMD_JOURNAL_SYSTEM_MAX_FILES=8\nSYSTEMD_JOURNAL_RUNTIME_MAX_FILES=4'):
            with self.subTest(override=values), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'target'; target.mkdir()
                self.shell(self.staging(tmp)+'''
render_target_resource_asset hooks/target/etc/systemd/journald.conf.d/10-storage.conf "$FILE_JOURNALD_STORAGE_CONF" 0644
validate_target_journal_storage_policy
''', override=values)
                actual = (target / 'etc/systemd/journald.conf.d/10-storage.conf').read_text()
                self.assertIn('SystemMaxUse=512M' if values else 'SystemMaxUse=1G', actual)
                self.assertFalse(TOKEN.search(actual))
                if not values:
                    fixture = SEED / 'tests/fixtures/journal-storage-original.conf'
                    self.assertEqual(actual, fixture.read_text())

    def test_deployment_order_and_scope_lifecycle_are_preserved(self):
        labwc = (SEED / 'scripts/desktop/labwc.sh').read_text()
        self.assertLess(labwc.index('desktop_install_user_resource_policy'),
                        labwc.index('desktop_install_user_config'))
        components = (SEED / 'scripts/desktop/components.sh').read_text()
        home_install = components.split('desktop_install_user_config() {', 1)[1]
        self.assertIn('.config/systemd', home_install)
        self.assertIn('cp -a "$src/." "$dst/"', home_install)
        self.assertIn('chown -R "$uid:$gid" "$dst"', home_install)
        self.assertIn('stage_target_systemd_resource_policy_assets || return 1',
                      (SEED / 'scripts/late/storage-maintenance.sh').read_text())

    def test_rendered_unit_dropins_parse_with_available_systemd(self):
        if not shutil.which('systemd-analyze'):
            self.skipTest('systemd-analyze is unavailable')
        for enabled in ('true', 'false'):
            with self.subTest(io=enabled), tempfile.TemporaryDirectory() as tmp:
                units = Path(tmp) / 'units'; units.mkdir()
                to_verify = []
                for name in CLASSES:
                    unit = units / f'{name}.slice'
                    unit.write_text('[Unit]\nDescription=Resource fixture\nDefaultDependencies=no\n[Slice]\n')
                    to_verify.append(unit)
                    dropin = units / f'{name}.slice.d/60-resources.conf'
                    dropin.parent.mkdir()
                    shutil.copy2(TARGET / f'{USER_BASE}/{name}.slice.d/60-resources.conf', dropin)
                    self.shell(f'TMP_ENV_DIR={shlex.quote(tmp)}\napply_systemd_resource_placeholders '+
                               shlex.quote(str(dropin)), override=f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\nSYSTEMD_IOWEIGHT_ENABLE={enabled}')
                for name in SERVICE_CLASSES:
                    unit = units / f'{name}.service'
                    unit.write_text('[Unit]\nDescription=Resource fixture\nDefaultDependencies=no\n'
                                    '[Service]\nExecStart=/usr/bin/true\n')
                    to_verify.append(unit)
                    dropin = units / f'{name}.service.d/60-resource-class.conf'
                    dropin.parent.mkdir()
                    shutil.copy2(TARGET / f'{USER_BASE}/{name}.service.d/60-resource-class.conf', dropin)
                user_unit = units / 'user@1000.service'
                user_unit.write_text('[Unit]\nDescription=Delegation fixture\nDefaultDependencies=no\n'
                                     '[Service]\nExecStart=/usr/bin/true\n')
                to_verify.append(user_unit)
                dropin = units / 'user@.service.d/60-resource-delegation.conf'
                dropin.parent.mkdir()
                shutil.copy2(TARGET / 'etc/systemd/system/user@.service.d/60-resource-delegation.conf', dropin)
                env = dict(os.environ, SYSTEMD_UNIT_PATH=str(units)+':', SYSTEMD_LOG_LEVEL='warning')
                result = subprocess.run(['systemd-analyze', '--generators=no', 'verify',
                                         *(str(path) for path in to_verify)],
                                        env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotRegex(result.stderr, r'Unknown (key|section)|Failed to parse|Invalid argument')

    def test_actual_home_copy_installs_private_dropins_for_account(self):
        # Execute the existing complete home-copy shell body in a disposable
        # chroot. No shell rewriting of /etc paths and no host home changes.
        if os.geteuid() != 0 or not shutil.which('chroot') or not shutil.which('ldd'):
            self.skipTest('disposable chroot test requires root, chroot and ldd')
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target'; target.mkdir()
            def copy_binary(source, destination=None):
                source = Path(source)
                dest = target / (destination or str(source)).lstrip('/')
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source.resolve(), dest)
                libs = subprocess.run(['ldd', str(source.resolve())], capture_output=True,
                                      text=True, timeout=10).stdout
                for lib in re.findall(r'(/[^\s()]+)', libs):
                    lib_path = Path(lib)
                    if lib_path.is_file():
                        library_dest = target / lib.lstrip('/')
                        library_dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(lib_path.resolve(), library_dest)
            for binary in ('dash', 'install', 'id', 'cp', 'chown', 'chmod', 'find',
                           'rm', 'getent', 'cut', 'dirname'):
                location = shutil.which(binary)
                if not location:
                    self.skipTest(f'{binary} is unavailable for chroot fixture')
                copy_binary(location, f'/usr/bin/{binary}')
            copy_binary(shutil.which('dash'), '/bin/sh')
            (target / 'etc').mkdir(exist_ok=True)
            (target / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n'
                                             'resource-test:x:1001:1001:Fixture:/home/resource-test:/bin/sh\n')
            (target / 'etc/group').write_text('root:x:0:\nresource-test:x:1001:\n')
            (target / 'etc/nsswitch.conf').write_text('passwd: files\ngroup: files\n')
            (target / 'dev').mkdir(); (target / 'dev/null').touch()
            shutil.copytree(TARGET / 'etc/skel-desktop', target / 'etc/skel-desktop')
            # Earlier desktop staging creates this empty cache (not archived).
            (target / 'etc/skel-desktop/.cache/recoll').mkdir(parents=True, exist_ok=True)
            setup = self.staging(tmp) + f'''
ACCOUNT_USERNAME=resource-test
ACCOUNT_HOME=/home/resource-test
run_in_target() {{
  label=$1; shift
  if [ "$label" = 'install Labwc desktop config for primary account' ]; then
    {shlex.quote(shutil.which('chroot'))} "$INSTALLER_TARGET_DIR" "$@"
  fi
}}
desktop_install_primary_account_calendar_stack() {{ :; }}
desktop_bootstrap_primary_account_gpg_key() {{ :; }}
stage_target_systemd_resource_policy_assets
desktop_install_user_resource_policy
desktop_install_user_config
'''
            self.shell(setup, override='SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE=false')
            home = target / 'home/resource-test/.config/systemd/user'
            for name in CLASSES:
                path = home / f'{name}.slice.d/60-resources.conf'
                self.assertTrue(path.is_file())
                self.assertFalse(TOKEN.search(path.read_text()))
                self.assertNotIn('IOWeight=', path.read_text())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual((path.stat().st_uid, path.stat().st_gid), (1001, 1001))
            for name, cls in SERVICE_CLASSES.items():
                path = home / f'{name}.service.d/60-resource-class.conf'
                self.assertIn(f'Slice={cls}.slice', path.read_text())
                self.assertEqual(path.stat().st_uid, 1001)
            self.assertIn('CPUWeight=300', (home / 'labwc-compositor.service.d/60-resources.conf').read_text())
            self.assertNotIn('IOWeight=', (home / 'labwc-compositor.service.d/60-resources.conf').read_text())
            for unit in ('labwc-bitwarden-', 'labwc-power-lock-', 'labwc-kwallet-portal'):
                path = home / f'{unit}.service.d/70-no-core.conf'
                self.assertIn('LimitCORE=0', path.read_text())
                self.assertEqual((path.stat().st_uid, path.stat().st_gid), (1001, 1001))
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('IOAccounting=yes', (target /
                'etc/systemd/system/user-1000.slice.d/50-resource-accounting.conf').read_text())


if __name__ == '__main__':
    unittest.main()
