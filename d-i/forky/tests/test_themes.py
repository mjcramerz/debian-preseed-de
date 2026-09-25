"""Installation-theme security, renderer and lifecycle regression tests.

No network, package compilation, real systemd service or kernel mutation.
Only transport/target execution boundaries are fixtures; shell/AWK rendering
and the ten production profile files are exercised directly.
"""
from __future__ import annotations
from waybar_fixture import profiles, rendered_assets
from payload_fixture import read_text as payload_read_text, copyfile as payload_copyfile, installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file, source_stat as payload_source_stat
import configparser
import ctypes.util
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import xml.etree.ElementTree as ET

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
TOOLS = SEED.parents[1] / 'tools'
CHECKER = runpy.run_path(str(TOOLS / 'check_themes.py'))
VALUES = CHECKER['load_themes']()
THEMES = SEED / 'hosts/themes'
Q = shlex.quote


class ThemeValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='theme-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('base.env', 'apps.env', 'office.env', 'theme-schema.tsv'):
            payload_copyfile(THEMES / name, self.root / name)

    def validate(self, command=None):
        args = (command or ['awk']) + ['-f', str(SEED / 'scripts/late/theme-validate.awk'),
                str(self.root / 'theme-schema.tsv')]
        args += [str(self.root / (group + '.env')) for group in ('base', 'apps', 'office')]
        return subprocess.run(payload_installed_argv(args), capture_output=True, text=True, timeout=10,
                              env={**os.environ, 'LC_ALL': 'C'})

    def replace(self, name, value):
        for group in ('base', 'apps', 'office'):
            path = self.root / (group + '.env')
            text = path.read_text()
            if re.search(r'^' + name + '=', text, re.M):
                path.write_text(re.sub(r'^' + name + r'="[^"\n]*"$',
                                      lambda _: f'{name}="{value}"', text, flags=re.M))
                return
        self.fail('missing fixture variable ' + name)

    def test_actual_catalog_and_consumers(self):
        result = CHECKER['check'](SEED)
        self.assertEqual(result['profiles'], 10)
        self.assertEqual(result['values'], len(VALUES))
        self.assertGreater(result['templates'], 90)

    def test_installer_and_busybox_awk_accept_identical_values(self):
        standard = self.validate()
        self.assertEqual(standard.returncode, 0, standard.stderr)
        self.assertEqual(dict(line.split('=', 1) for line in standard.stdout.splitlines()), VALUES)
        if shutil.which('busybox'):
            busy = self.validate([shutil.which('busybox'), 'awk'])
            self.assertEqual((busy.returncode, busy.stdout), (0, standard.stdout), busy.stderr)

    def test_shell_and_config_injection_is_rejected_without_partial_map(self):
        for bad in ('$(touch /tmp/theme-must-not-execute)', '`id`', 'x"; id; #',
                    'x\\nOther=1', 'x\nOther=1', "x';id", 'x\tvalue', 'x__THEME_FOO__'):
            with self.subTest(value=bad):
                payload_copyfile(THEMES / 'base.env', self.root / 'base.env')
                self.replace('LABWC_DESKTOP_GTK_THEME', bad)
                result = self.validate()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_invalid_paths_and_colors_are_rejected(self):
        for name, bad in (
            ('LABWC_WALLPAPER_DESKTOP_SWAYBG', '/etc/passwd'),
            ('LABWC_WALLPAPER_DESKTOP_SWAYBG', 'hooks/target/usr/share/backgrounds/../bad.png'),
            ('LABWC_WALLPAPER_DESKTOP_SWAYBG', 'hooks/target/usr/share/backgrounds//bad.png'),
            ('LABWC_WALLPAPER_DESKTOP_SWAYBG', 'hooks/target/usr/share/backgrounds/a.svg'),
            ('LABWC_TERMINAL_BACKGROUND_OPACITY', '1.01'),
            ('LABWC_DESKTOP_GTK_THEME', 'a;Other=1'),
            ('WAYBAR_BUTTON_APPS_NORMAL_ICON_PATH', 'icons/../private.svg'),
            ('WAYBAR_BUTTON_APPS_NORMAL_ICON_PATH', '/etc/private.svg'),
        ):
            with self.subTest(name=name, value=bad):
                payload_copyfile(THEMES / 'base.env', self.root / 'base.env')
                self.replace(name, bad)
                result = self.validate()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_duplicate_unknown_missing_and_wrong_group_fail_closed(self):
        base = (THEMES / 'base.env').read_text()
        name = 'LABWC_DESKTOP_GTK_THEME'
        assignment = next(line for line in base.splitlines() if line.startswith(name + '='))
        variants = [base + '\n' + assignment + '\n', base + '\nPATH="unsafe"\n',
                    base.replace(assignment + '\n', '')]
        for text in variants:
            with self.subTest(kind=text[-80:]):
                (self.root / 'base.env').write_text(text)
                self.assertNotEqual(self.validate().returncode, 0)
        (self.root / 'base.env').write_text(base.replace(assignment + '\n', ''))
        with (self.root / 'apps.env').open('a') as stream:
            stream.write('\n' + assignment + '\n')
        self.assertNotEqual(self.validate().returncode, 0)

    def test_all_tokenized_sources_match_production_awk_rendering(self):
        mapping = self.root / 'values.map'
        mapping.write_text(self.validate().stdout)
        renderer = SEED / 'scripts/late/theme-render.awk'
        for path, text in CHECKER['source_texts'](SEED):
            if '__THEME_' not in text or path.name in ('theme-render.awk', 'themes.sh', 'core.sh'):
                continue
            with self.subTest(path=str(path.relative_to(SEED))):
                actual = subprocess.run(payload_installed_argv(['awk', '-f', str(renderer), str(mapping), str(path)]),
                                        text=True, capture_output=True, timeout=5)
                self.assertEqual(actual.returncode, 0, actual.stderr)
                # AWK normalizes a missing final newline; managed text files
                # are newline-terminated and no binary assets enter this test.
                self.assertEqual(actual.stdout, CHECKER['render_text'](text, VALUES))
                if shutil.which('busybox'):
                    busy = subprocess.run(payload_installed_argv(['busybox', 'awk', '-f', str(renderer),
                        str(mapping), str(path)]), text=True, capture_output=True, timeout=5)
                    self.assertEqual((busy.returncode, busy.stdout),
                                     (0, actual.stdout), busy.stderr)


SHELL_PREAMBLE = r'''
set -eu
umask 077
. "$INSTALLER_SOURCE_ROOT/scripts/common/lib.sh"
installer_ensure_repo_env "$INSTALLER_SOURCE_ROOT"
. "$INSTALLER_SOURCE_ROOT/scripts/common/target.sh"
. "$INSTALLER_SOURCE_ROOT/scripts/late/core.sh"
. "$INSTALLER_SOURCE_ROOT/scripts/late/target-assets.sh"
. "$INSTALLER_SOURCE_ROOT/scripts/desktop/components.sh"
. "$INSTALLER_SOURCE_ROOT/scripts/desktop/detect.sh"
# Only authenticated transport and target command execution are fixture
# boundaries. File lookup, theme loading, validation, rendering and staging
# use the production implementations.
fetch_hook_file() { installer_fetch_seed_path "$INSTALLER_SOURCE_ROOT" "$1" "$2"; }
desktop_log() { :; }
run_in_target() { printf '%s\n' "$*" >> "$TARGET_COMMAND_LOG"; return "${TARGET_COMMAND_STATUS:-0}"; }
late_command_load_themes
'''


class ThemeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='theme-install-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'target'; self.target.mkdir()
        self.staging = self.root / 'staging'; self.staging.mkdir(mode=0o700)
        self.env = {**os.environ, 'INSTALLER_SOURCE_ROOT': str(SEED), 'SEED_BASE': str(SEED),
                    'INSTALLER_TARGET_DIR': str(self.target), 'TMP_ENV_DIR': str(self.staging),
                    'INSTALLER_RUNTIME_DIR': str(self.root / 'runtime'),
                    'INSTALLER_CMDLINE': '', 'TARGET_COMMAND_LOG': str(self.root / 'commands')}

    def shell(self, code, preamble=SHELL_PREAMBLE, **updates):
        return subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', preamble + '\n' + code]),
                              env={**self.env, **updates}, text=True, capture_output=True, timeout=25)

    def ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_managed_software_desktop_icons_render_before_publication(self):
        source = (SEED / 'scripts/late/software.sh.tmpl').read_text()
        functions = source[source.index('software_render_theme_asset() {'):
                           source.index('software_stage_menu_icon() {')]
        self.assertIn('software_render_theme_asset "$tmp_asset" "$repo_path"', functions)
        software_functions = self.root / 'software-functions.sh'
        software_functions.write_text(functions)
        preamble = SHELL_PREAMBLE.removesuffix('late_command_load_themes\n')
        code = '\n'.join((
            '. "$INSTALLER_SOURCE_ROOT/scripts/common/bootstrap.sh"',
            'seed_base=$INSTALLER_SOURCE_ROOT',
            'target_root=$INSTALLER_TARGET_DIR',
            'tmp_env_dir=$TMP_ENV_DIR',
            'software_fatal() { printf "fatal: %s\\n" "$*" >&2; exit 1; }',
            'software_validate_abs_path() { case "$2" in /*) : ;; *) exit 1 ;; esac; }',
            f'. {shlex.quote(str(software_functions))}',
            'software_stage_seed_asset hooks/target/usr/local/share/applications/chatgpt.desktop '
            ' /usr/local/share/applications/chatgpt.desktop 0644',
            'software_stage_seed_asset hooks/target/usr/local/share/applications/discord.desktop '
            ' /usr/local/share/applications/discord.desktop 0644',
            *(f'software_render_seed_asset hooks/target/usr/local/share/applications/{name}.desktop '
              f'/usr/local/share/applications/{name}.desktop 0644 '
              'LABWC_MANAGED_APP_DEFAULT_EXEC "/usr/local/bin/labwc-app launch"'
              for name in ('postman', 'ledger-live', 'sleek')),
        ))
        self.ok(self.shell(code, preamble=preamble))
        values = CHECKER['load_themes'](SEED)
        for desktop_id, icon_id in (
            ('chatgpt', 'chatgpt'), ('postman', 'postman'),
            ('discord', 'discord'), ('ledger-live', 'ledger-live-desktop'),
            ('sleek', 'sleek'),
        ):
            with self.subTest(desktop_id=desktop_id):
                entry = self.target / f'usr/local/share/applications/{desktop_id}.desktop'
                parser = configparser.ConfigParser(interpolation=None)
                parser.optionxform = str
                self.assertTrue(parser.read(entry, encoding='utf-8'))
                self.assertEqual(parser['Desktop Entry']['Icon'],
                                 f'/usr/share/icons/hicolor/512x512/apps/{icon_id}.png')
                self.assertNotIn('__THEME_', entry.read_text())
                self.assertEqual(entry.stat().st_mode & 0o777, 0o644)

    def test_individual_fetch_and_plain_asset_are_rendered(self):
        self.ok(self.shell(r'''
fetch_hook hooks/target/etc/skel-desktop/.config/swaylock/config "$TMP_ENV_DIR/lock"
stage_target_asset hooks/target/etc/skel-desktop/.config/mako/config /etc/xdg/mako/config 0644
'''))
        lock = (self.staging / 'lock').read_text()
        self.assertIn('/usr/share/backgrounds/login/lock-1920x1080.png', lock)
        self.assertNotIn('__THEME_', lock)
        mako = self.target / 'etc/xdg/mako/config'
        self.assertNotIn('__THEME_', mako.read_text())
        self.assertEqual(payload_source_stat(mako).st_mode & 0o777, 0o644)

    @unittest.skipUnless(os.geteuid() == 0, 'tree staging enforces root ownership')
    def test_copied_application_tree_is_rendered_before_publication(self):
        self.ok(self.shell('desktop_stage_role_asset_tree '
                           'etc/skel-desktop/Syncthing/obsidian-md /opt/theme-fixture'))
        outputs = list((self.target / 'opt/theme-fixture').rglob('*'))
        self.assertTrue(outputs)
        for path in outputs:
            if payload_source_is_file(path):
                self.assertNotIn(b'__THEME_', path.read_bytes())
                self.assertEqual(payload_source_stat(path).st_uid, 0)

    def test_failed_render_preserves_original_file_mode_and_bytes(self):
        original = b'keep original\n__THEME_UNKNOWN_VARIABLE__\n'
        path = self.staging / 'bad'; path.write_bytes(original); path.chmod(0o640)
        result = self.shell('installer_theme_render_file "$TMP_ENV_DIR/bad"')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(payload_source_stat(path).st_mode & 0o777, 0o640)
        self.assertFalse(list(self.staging.glob('.theme-render.*')))

    def test_symlink_is_not_rendered_and_binary_artwork_remains_identical(self):
        original = self.staging / 'original'; original.write_text('__THEME_LABWC_DESKTOP_GTK_THEME__\n')
        (self.staging / 'link').symlink_to(original)
        self.assertNotEqual(self.shell('installer_theme_render_file "$TMP_ENV_DIR/link"').returncode, 0)
        binary = self.staging / 'image.png'; binary.write_bytes(b'\x89PNG\x00__THEME_UNKNOWN__\n')
        self.ok(self.shell('installer_theme_render_file "$TMP_ENV_DIR/image.png"'))
        self.assertEqual(binary.read_bytes(), b'\x89PNG\x00__THEME_UNKNOWN__\n')
        self.assertEqual(original.read_text(), '__THEME_LABWC_DESKTOP_GTK_THEME__\n')

    def test_every_profile_renders_geometry_and_native_theme_settings(self):
        for profile in sorted((SEED / 'hosts/profiles').glob('*.env')):
            with self.subTest(profile=profile.name):
                self.ok(self.shell('. ' + Q(str(profile)) + r'''
ACCOUNT_USERNAME=desktop
ACCOUNT_HOME=/home/desktop
LABWC_INTEL_ACCELERATION_AVAILABLE=true
LABWC_NVIDIA_ACCELERATION_AVAILABLE=false
desktop_primary_account_ids() { printf '1000:1000\n'; }
desktop_render_labwc_default_config
desktop_render_labwc_rc_xml
desktop_render_waybar_config
desktop_render_labwc_environment_assets
desktop_render_labwc_session_wrappers
desktop_render_fuzzel_configs
desktop_render_gtk_settings
desktop_render_qt6ct_config
desktop_render_terminal_configs
desktop_render_waybar_style
desktop_render_gtkgreet_css
desktop_render_crystal_dock_appearance
'''))
                config = self.target / 'etc/skel-desktop/.config'
                dimensions = dict(re.findall(r'^(FUZZEL_[A-Z_]+)="([^"]*)"$', profile.read_text(), re.M))
                self.assertEqual({p.name for p in (config/'fuzzel').iterdir()},
                                 {'base.ini', 'fuzzel.ini', 'menu.ini', 'computer-management.ini'})
                for name, parent in (('fuzzel', 'base'), ('menu', 'base'),
                                     ('computer-management', 'menu')):
                    text = (config/'fuzzel'/f'{name}.ini').read_text()
                    self.assertIn(f'include=~/.config/fuzzel/{parent}.ini', text)
                    self.assertNotRegex(text, r'(?m)^(font|width|lines|line-height|horizontal-pad|vertical-pad|inner-pad)=')
                base = (config/'fuzzel/base.ini').read_text()
                self.assertIn('dpi-aware=yes', base)
                self.assertNotRegex(base, r'(?m)^(font|width|lines|line-height|horizontal-pad|vertical-pad|inner-pad)=')
                runtime = (self.target/'etc/labwc/desktop.conf').read_text()
                self.assertEqual(len(dimensions), 33)
                for name, value in dimensions.items():
                    self.assertIn(f"{name}='{value}'", runtime)
                for version in ('3', '4'):
                    text = (config / f'gtk-{version}.0/settings.ini').read_text()
                    self.assertIn('gtk-theme-name=' + VALUES['LABWC_DESKTOP_GTK_THEME'], text)
                    self.assertIn('gtk-icon-theme-name=' + VALUES['LABWC_DESKTOP_GTK_ICON_THEME'], text)
                qt = (config / 'qt6ct/qt6ct.conf').read_text()
                self.assertIn('icon_theme=' + VALUES['LABWC_DESKTOP_QT_ICON_THEME'], qt)
                self.assertIn('style=' + VALUES['LABWC_DESKTOP_QT_THEME'], qt)
                for path in self.target.rglob('*'):
                    if payload_source_is_file(path):
                        self.assertNotRegex(path.read_text(), r'__(?:THEME|INSTALLER)_')
                commands = (self.root / 'commands').read_text()
                self.assertIn('/usr/bin/foot --check-config --config /etc/skel-desktop/.config/foot/foot.ini', commands)

    def test_foot_parser_failure_is_not_converted_to_success(self):
        profile = SEED / 'hosts/profiles/btrfs-de.env'
        result = self.shell('. ' + Q(str(profile)) + '\ndesktop_render_terminal_configs',
                            TARGET_COMMAND_STATUS='230')
        self.assertEqual(result.returncode, 230, result.stderr)

    def test_custom_wallpaper_paths_are_derived_not_evaluated(self):
        # The map is validator output. Override a legitimate input in a private
        # fixture catalog and validate again before rendering its consumers.
        themes = self.staging / 'custom'; shutil.copytree(THEMES, themes)
        path = themes / 'base.env'
        source = 'hooks/target/usr/share/backgrounds/custom/new-desktop.jpg'
        path.write_text(path.read_text().replace(VALUES['LABWC_WALLPAPER_DESKTOP_SWAYBG'], source))
        code = r'''
awk -f "$INSTALLER_THEME_DIR/validate.awk" "$TMP_ENV_DIR/custom/theme-schema.tsv" \
  "$TMP_ENV_DIR/custom/base.env" "$TMP_ENV_DIR/custom/apps.env" "$TMP_ENV_DIR/custom/office.env" > "$TMP_ENV_DIR/custom/map"
INSTALLER_THEME_MAP="$TMP_ENV_DIR/custom/map"
cp "$INSTALLER_SOURCE_ROOT/hooks/target/usr/local/libexec/labwc-swaybg.tmpl" "$TMP_ENV_DIR/swaybg"
installer_theme_render_file "$TMP_ENV_DIR/swaybg"
'''
        self.ok(self.shell(code))
        text = (self.staging / 'swaybg').read_text()
        self.assertIn('/usr/share/backgrounds/custom/new-desktop.jpg', text)
        self.assertNotIn('hooks/target', text)


    def test_changed_palette_reaches_every_group_through_production_fetch(self):
        catalog = self.staging / 'custom'
        shutil.copytree(THEMES, catalog)
        replacements = {
            'WAYBAR_PANEL_BACKGROUND_COLOR': 'rgba(17, 34, 51, 0.94)',
            'VSCODE_EDITOR_BACKGROUND_COLOR': '#123456',
        }
        office_key = next(name for name in VALUES if name.startswith('OBSIDIAN_')
                          and name.endswith('BACKGROUND_COLOR') and VALUES[name].startswith('#'))
        replacements[office_key] = '#234567'
        for group in ('base', 'apps', 'office'):
            path = catalog / (group + '.env')
            text = path.read_text()
            for name, value in replacements.items():
                text = re.sub(r'^' + name + r'="[^"\n]*"$',
                              lambda _: f'{name}="{value}"', text, flags=re.M)
            path.write_text(text)
        preamble = SHELL_PREAMBLE.replace(
            'fetch_hook_file() { installer_fetch_seed_path "$INSTALLER_SOURCE_ROOT" "$1" "$2"; }',
            'fetch_hook_file() { case "$1" in hosts/themes/*) '
            'cp "$TMP_ENV_DIR/custom/${1##*/}" "$2" ;; *) '
            'installer_fetch_seed_path "$INSTALLER_SOURCE_ROOT" "$1" "$2" ;; esac; }')
        consumers = []
        for name, value in replacements.items():
            consumer = next(path for path, text in CHECKER['source_texts'](SEED)
                            if '__THEME_' + name + '__' in text)
            consumers.append((name, value, consumer))
        code = '\n'.join('fetch_hook ' + Q(str(path.relative_to(SEED))) + ' ' +
                         Q(str(self.staging / ('render-' + str(index))))
                         for index, (_, _, path) in enumerate(consumers))
        self.ok(self.shell(code, preamble=preamble))
        expected = {**VALUES, **replacements}
        for index, (_, value, source) in enumerate(consumers):
            actual = (self.staging / ('render-' + str(index))).read_text()
            self.assertEqual(actual, CHECKER['render_text'](source.read_text(), expected))
            self.assertIn(value, actual)

    def test_selected_waybar_icons_are_staged_not_the_default_names(self):
        self.ok(self.shell(r'''
desktop_stage_role_asset() { printf '%s|%s|%s\n' "$1" "$2" "$3" >> "$TARGET_COMMAND_LOG"; }
WAYBAR_BUTTON_APPS_NORMAL_ICON_PATH=icons/custom-launcher.svg
WAYBAR_BUTTON_APPS_HOVER_ICON_PATH=/usr/share/icons/package-hover.svg
WAYBAR_BUTTON_WAYSCRIBER_NORMAL_ICON_PATH=icons/custom-pen.svg
WAYBAR_BUTTON_WAYSCRIBER_HOVER_ICON_PATH=icons/custom-pen-hover.svg
desktop_stage_waybar_theme_icons
'''))
        lines = (self.root / 'commands').read_text().splitlines()
        self.assertEqual(len(lines), 3)
        for line, name in zip(lines, ('custom-launcher.svg', 'custom-pen.svg', 'custom-pen-hover.svg')):
            self.assertEqual(line, f'etc/skel-desktop/.config/waybar/icons/{name}|'
                             f'/etc/skel-desktop/.config/waybar/icons/{name}|0644')

    def test_custom_wallpaper_is_public_readable_and_binary_identical(self):
        relative = 'hooks/target/usr/share/backgrounds/custom/nested/welcome.png'
        fixture = self.staging / 'wallpaper.png'
        original = (TARGET / 'usr/share/backgrounds/login/welcome-1920x1080.png').read_bytes()
        fixture.write_bytes(original)
        preamble = SHELL_PREAMBLE.replace(
            'fetch_hook_file() { installer_fetch_seed_path "$INSTALLER_SOURCE_ROOT" "$1" "$2"; }',
            'fetch_hook_file() { case "$1" in ' + relative + ') '
            'cp "$TMP_ENV_DIR/wallpaper.png" "$2" ;; *) '
            'installer_fetch_seed_path "$INSTALLER_SOURCE_ROOT" "$1" "$2" ;; esac; }')
        destination = '/' + relative.removeprefix('hooks/target/')
        self.ok(self.shell('stage_target_asset ' + Q(relative) + ' ' + Q(destination) + ' 0644',
                           preamble=preamble))
        output = self.target / destination.lstrip('/')
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(payload_source_stat(output).st_mode & 0o777, 0o644)
        for directory in (output.parent, output.parent.parent):
            self.assertEqual(payload_source_stat(directory).st_mode & 0o777, 0o755)

class ThemeRuntimeContractTests(unittest.TestCase):
    def test_wpa_preserves_protection_with_only_interface_tree_exceptions(self):
        text = (TARGET / 'etc/systemd/system/wpa_supplicant.service.d/override.conf').read_text()
        directives = [line for line in text.splitlines() if line and not line.startswith('#')]
        self.assertIn('ProtectKernelTunables=yes', directives)
        self.assertIn('ReadWritePaths=/proc/sys/net/ipv4/conf -/proc/sys/net/ipv6/conf', directives)
        caps = next(line for line in directives if line.startswith('CapabilityBoundingSet='))
        self.assertNotIn('CAP_SYS_ADMIN', caps)
        self.assertNotIn('CAP_DAC_OVERRIDE', caps)
        self.assertFalse(any(line == 'ProtectKernelTunables=no' for line in directives))

    def test_foot_result_helper_does_not_remap_or_execute_status_values(self):
        helper = TARGET / 'usr/local/libexec/labwc-terminal-result'
        for result, code, status, expected in (
            ('success', 'exited', '0', ''), ('exit-code', 'exited', '230', 'exit_status=230'),
            ('exit-code', 'exited', '203', 'exit_status=203'),
            ('signal', 'killed', 'SEGV', 'exit_status=SEGV'),
            ('exit-code', 'exited', '1;id', ''),
        ):
            with self.subTest(status=status):
                process = subprocess.run(payload_installed_argv(['/bin/sh', str(helper)]), text=True, capture_output=True,
                    env={'PATH': '/usr/bin:/bin', 'SERVICE_RESULT': result,
                         'EXIT_CODE': code, 'EXIT_STATUS': status}, timeout=5)
                self.assertEqual(process.returncode, 0)
                if expected:
                    self.assertIn(expected, process.stderr)
                else:
                    self.assertEqual(process.stderr, '')

    def test_rendered_native_app_configs_parse(self):
        for relative in ('.config/wayscriber/config.toml', '.config/satty/config.toml',
                         '.config/starship.toml'):
            path = TARGET / 'etc/skel-desktop' / relative
            if payload_source_exists(path):
                tomllib.loads(CHECKER['render_text'](payload_read_text(path), VALUES))
        for path in (TARGET / 'etc/skel-desktop/Syncthing/obsidian-md').rglob('*.json*'):
            json.loads(CHECKER['render_text'](payload_read_text(path), VALUES))
        ET.fromstring(CHECKER['render_text']((TARGET / 'etc/skel-desktop/.config/labwc/rc.xml.tmpl').read_text(), VALUES))

    @unittest.skipUnless(shutil.which('xvfb-run'), 'native GTK test needs Xvfb')
    def test_native_submenus_accept_independent_backgrounds(self):
        if not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3 library is unavailable')
        with tempfile.TemporaryDirectory(prefix='theme-submenu-') as directory:
            root = Path(directory)
            values = {**VALUES, 'WAYBAR_DROPDOWN_SUBMENU_NORMAL_BACKGROUND_COLOR':
                      'rgba(17, 34, 51, 0.60)'}
            source = TARGET / 'etc/skel-desktop/.config/waybar'
            assets = rendered_assets(profiles()[0], theme_items=tuple(sorted(values.items())))
            (root / 'style.css').write_text(assets['style.css'])
            (root / 'menu.xml').write_text(assets['tomat-menu.xml'])
            code = r'''
import ctypes as C, ctypes.util, sys, json
G = C.CDLL(ctypes.util.find_library('gtk-3'))
D = C.CDLL(ctypes.util.find_library('gdk-3'))
L = C.CDLL(ctypes.util.find_library('glib-2.0'))
def bind(lib, name, result, *args):
    fn = getattr(lib, name); fn.restype = result; fn.argtypes = args; return fn
P = C.c_void_p
class List(C.Structure): pass
List._fields_ = [('data', P), ('next', C.POINTER(List)), ('prev', C.POINTER(List))]
class Color(C.Structure):
    _fields_ = [(field, C.c_double) for field in ('red', 'green', 'blue', 'alpha')]
assert bind(G, 'gtk_init_check', C.c_int, P, P)(None, None)
provider = bind(G, 'gtk_css_provider_new', P)()
assert bind(G, 'gtk_css_provider_load_from_path', C.c_int, P, C.c_char_p, P)(provider, sys.argv[1].encode(), None)
screen = bind(D, 'gdk_screen_get_default', P)()
bind(G, 'gtk_style_context_add_provider_for_screen', None, P, P, C.c_uint)(screen, provider, 800)
builder = bind(G, 'gtk_builder_new', P)()
assert bind(G, 'gtk_builder_add_from_file', C.c_uint, P, C.c_char_p, P)(builder, sys.argv[2].encode(), None)
menu = bind(G, 'gtk_builder_get_object', P, P, C.c_char_p)(builder, b'menu')
children = bind(G, 'gtk_container_get_children', C.POINTER(List), P)(menu)
assert children
submenu = bind(G, 'gtk_menu_item_get_submenu', P, P)(children.contents.data)
bind(L, 'g_list_free', None, P)(C.cast(children, P))
assert submenu
context = bind(G, 'gtk_widget_get_style_context', P, P)
assert bind(G, 'gtk_style_context_has_class', C.c_int, P, C.c_char_p)(context(submenu), b'submenu')
background = bind(G, 'gtk_style_context_get_background_color', None, P, C.c_int, C.POINTER(Color))
def color(widget):
    result = Color(); background(context(widget), 0, C.byref(result))
    return [getattr(result, field) for field, _ in Color._fields_]
print(json.dumps({'submenu': color(submenu), 'root': color(menu)}))
'''
            result = subprocess.run(payload_installed_argv(['xvfb-run', '-a', '/usr/bin/python3', '-c', code,
                str(root / 'style.css'), str(root / 'menu.xml')]),
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            colors = json.loads(result.stdout)
            for actual, expected in zip(colors['submenu'], (17/255, 34/255, 51/255, 0.6)):
                self.assertAlmostEqual(actual, expected, places=5)
            self.assertNotEqual(colors['root'], colors['submenu'])

    def test_no_gtk_debug_override_export_is_left(self):
        for path, text in CHECKER['source_texts'](SEED):
            for number, line in enumerate(text.splitlines(), 1):
                if not line.lstrip().startswith('#'):
                    self.assertNotRegex(line, r'(?<![A-Z_])GTK_THEME=', f'{path}:{number}')


if __name__ == '__main__':
    unittest.main()
