"""Regression coverage for packaged labwc/KWallet and native thumbnails.

The installer-flow fixture replaces target mutations with explicit stubs. It
executes the real shell orchestrator; it does not boot d-i or start Wayland.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_is_file as payload_source_is_file
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
FORKY = ROOT / 'd-i/forky'
TARGET = FORKY / 'hooks/target'

# Only these existing installer steps may run in the flow fixture. An unexpected
# new helper or target command must fail rather than being automatically stubbed.
STEPS = (
    'desktop_resolve_acceleration_availability',
    'desktop_resolve_managed_app_default_exec',
    'desktop_resolve_generic_app_defaults',
    'desktop_validate_managed_app_default_exec',
    'desktop_preflight_required_cmdline_tokens',
    'desktop_xwayland_preflight_target_architecture',
    'desktop_satty_preflight_target_architecture',
    'desktop_android_platform_tools_preflight_target_architecture',
    'desktop_samloader_preflight_target_architecture',
    'desktop_digital_assets_preflight_target_architecture',
    'desktop_resctl_bench_preflight_target_architecture',
    'desktop_detect_connected_drm_outputs',
    'desktop_resolve_greeter_user',
    'desktop_configure_greeter_access',
    'desktop_configure_usb_media_access',
    'desktop_configure_android_debug_bridge_access',
    'desktop_configure_fido2_security_key_access',
    'desktop_configure_packet_capture_access',
    'desktop_install_xwayland',
    'desktop_install_satty',
    'desktop_install_android_platform_tools',
    'desktop_install_samloader',
    'desktop_install_digital_assets',
    'desktop_install_resctl_bench',
    'desktop_install_kanshi_policy',
    'desktop_stage_target_assets',
    'desktop_render_greetd_config',
    'desktop_render_labwc_default_config',
    'desktop_install_hardware_tuning',
    'desktop_write_labwc_plans_config',
    'desktop_install_user_resource_policy',
    'desktop_install_user_config',
    'desktop_install_fonts',
    'desktop_install_waypaper',
    'desktop_enable_target_services',
    'desktop_verify_kanshi_policy',
    'desktop_verify_native_menus',
    'desktop_install_codex_standalone',
)


class PackagedNativeSessionTests(unittest.TestCase):
    def test_binary_packages_remain_selected_once(self):
        role = payload_read_text(FORKY / 'classes/class-select/role/desktop.cfg')
        packages = re.search(r'^d-i pkgsel/include string (.*)$', role, re.M)[1].split()
        self.assertEqual(packages.count('labwc'), 1)
        self.assertEqual(packages.count('kwallet6'), 1)
        self.assertIn('qt6-wayland', packages)
        self.assertIn('wtype', packages)

    def test_no_source_builder_patcher_or_staging_path_in_active_payload(self):
        retired = ('build_native.py', 'patch_sources.py', 'native-repairs',
                   '.installer-native-session-repairs', 'x-native-repairs',
                   'desktop_install_native_session_repairs')
        for directory in (FORKY / 'scripts', TARGET):
            for path in directory.rglob('*'):
                if not payload_source_is_file(path):
                    continue
                data = payload_read_bytes(path)
                for token in retired:
                    self.assertNotIn(token, str(path.relative_to(FORKY)))
                    self.assertNotIn(token.encode(), data, str(path.relative_to(FORKY)))

    def test_published_archive_and_manifest_do_not_restore_deleted_helpers(self):
        manifest = payload_read_text(FORKY / 'payload.manifest')
        self.assertNotIn('native-repairs', manifest)
        with tarfile.open(FORKY / 'payload.tar.gz', 'r:gz') as archive:
            self.assertFalse(any('native-repairs' in name for name in archive.getnames()))
            member = archive.extractfile('scripts/desktop/labwc.sh')
            self.assertIsNotNone(member)
            self.assertNotIn(b'desktop_install_native_session_repairs', member.read())

    def test_stock_binary_paths_and_existing_isolation_remain(self):
        units = TARGET / 'etc/skel-desktop/.config/systemd/user'
        compositor = payload_read_text(units / 'labwc-compositor.service')
        wallet = payload_read_text(units / 'labwc-kwallet-portal.service')
        self.assertIn('ExecStart=/usr/bin/labwc ', compositor)
        self.assertIn('InaccessiblePaths=-/opt/xwayland', compositor)
        self.assertIn('UnsetEnvironment=DISPLAY XAUTHORITY WLR_XWAYLAND', compositor)
        self.assertIn('ExecStart=/usr/bin/ksecretd\n', wallet)
        self.assertIn('Environment=QT_QPA_PLATFORM=wayland', wallet)
        for unit in (compositor, wallet):
            self.assertIn('KillMode=control-group', unit)
            self.assertIn('PartOf=labwc-session.target', unit)
        policy = payload_read_text(TARGET / 'etc/apparmor.d/labwc-session')
        self.assertIn('profile ksecretd /usr/bin/ksecretd', policy)

    def flow(self, shell, failure=''):
        definitions = ''.join(
            f'{name}() {{ printf "%s\\n" "{name}"; '
            f'if [ "${{FAIL_STEP:-}}" = "{name}" ]; then return 71; fi; }}\n'
            for name in STEPS)
        script = '''set -eu
. "$1"
desktop_log() { :; }
desktop_log_policy_context() { :; }
installer_info() { :; }
desktop_policy_enabled() { return 0; }
run_in_target() {
  case "$1" in
    'verify GIO desktop-entry binding')
      [ "$2" = /usr/bin/python3 ] && [ "$3" = -I ] && [ "$4" = -c ] || return 90 ;;
    'wrap installed desktop package launchers')
      [ "$2" = /usr/local/libexec/labwc-wrap-desktop-files ] && [ "$#" -eq 2 ] || return 90 ;;
    *) printf 'unexpected target operation: %s\\n' "$1" >&2; return 91 ;;
  esac
}
''' + definitions + '\nrun_desktop_late_command fixture fixture\n'
        environment = {
            'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
            'INSTALLER_HOST_VARIANT': 'desktop', 'HOST_PROFILE': 'fixture',
            'LABWC_MANAGED_APP_DEFAULT_EXEC': 'foot', 'ACCOUNT_USERNAME': 'test',
            'LABWC_GREETER_USER': 'greeter', 'FAIL_STEP': failure,
            **{name + '_TARGET_ARCHITECTURE': 'amd64' for name in
               ('XWAYLAND', 'SATTY', 'ANDROID_PLATFORM_TOOLS', 'SAMLOADER', 'DIGITAL_ASSETS')},
        }
        return subprocess.run(payload_installed_argv([*shell, '-c', script, 'test', str(FORKY / 'scripts/desktop/labwc.sh')]),
                              env=environment, text=True, capture_output=True, timeout=10)

    def test_desktop_flow_reaches_completion_without_source_build(self):
        shells = [('/bin/sh',)]
        if shutil.which('busybox'):
            shells.append((shutil.which('busybox'), 'sh'))
        for shell in shells:
            with self.subTest(shell=shell):
                result = self.flow(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), list(STEPS))

    def test_unrelated_install_failures_are_not_swallowed(self):
        result = self.flow(('/bin/sh',), 'desktop_install_xwayland')
        self.assertEqual(result.returncode, 71, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], 'desktop_install_xwayland')
        self.assertNotIn('desktop_install_satty', result.stdout)

    def test_native_menu_validation_failure_aborts_before_codex(self):
        result = self.flow(('/bin/sh',), 'desktop_verify_native_menus')
        self.assertEqual(result.returncode, 71, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], 'desktop_verify_native_menus')
        self.assertNotIn('desktop_install_codex_standalone', result.stdout)

    def test_list_mode_and_injection_fail_before_replacing_rendered_config(self):
        fixture = FORKY / 'tests/fixtures/workspaces/render.sh'
        for style in ('classic', 'broken', 'thumbnail" /><action name="Exit', 'thumbnail; id'):
            with self.subTest(style=style), tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp)
                config = destination / 'etc/skel-desktop/.config/labwc/rc.xml'
                config.parent.mkdir(parents=True)
                config.write_text('existing configuration\n')
                result = subprocess.run(payload_installed_argv(['/bin/sh', str(fixture), str(ROOT), tmp, '4', style]),
                                        text=True, capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('must be thumbnail', result.stderr)
                self.assertEqual(payload_read_text(config), 'existing configuration\n')

    def test_no_classic_theme_or_fields_in_managed_switcher(self):
        directory = TARGET / 'etc/skel-desktop/.config/labwc'
        self.assertNotIn('<fields>', payload_read_text(directory / 'rc.xml.tmpl'))
        self.assertNotIn('style-classic', payload_read_text(directory / 'themerc-override'))
        launcher = payload_read_text(TARGET / 'usr/local/bin/labwc-window-switcher')
        self.assertIn('exec /usr/bin/timeout --signal=TERM --kill-after=1s 2s /usr/bin/wtype -P F13 -p F13', launcher)
        for token in ('fuzzel', 'ShowMenu', '-M alt', 'sleep '):
            self.assertNotIn(token, launcher)


if __name__ == '__main__':
    unittest.main()
