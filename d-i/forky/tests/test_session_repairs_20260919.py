"""September 19 incident regressions; UI endpoints are fixtures, never live.

Real production renderers, wrapper status/cleanup and native AppArmor syntax are
covered elsewhere as well. No test asserts that a target GPU is repaired.
"""
from payload_fixture import waybar_config_text
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists
from payload_fixture import read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import configparser
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET

from test_desktop_sandbox import FuzzelOutputSizingTests as _SizingFixture
import test_system_desktop_overrides as desktop_overrides

ROOT = Path(__file__).resolve().parents[3]
FORKY = ROOT / 'd-i/forky'
TARGET = FORKY / 'hooks/target'


# Do not inherit the whole existing test case: reuse only its sandbox transport.
class PickerIncidentTests(unittest.TestCase):
    setUp = _SizingFixture.setUp
    invoke = _SizingFixture.invoke

    def test_native_dmenu_status_is_normalized_for_all_wrapper_paths(self):
        fake = self.bin / 'fuzzel'
        fake.write_text('#!/bin/sh\ncat >/dev/null\nexit "$NATIVE_STATUS"\n')
        for args in (('menu', '--dmenu'), ('menu', '--dmenu0'), ('computer-management', '--dmenu')):
            for icons in ('0', '1'):
                for native, expected in ((0, 0), (2, 1), (1, 2), (127, 127), (143, 143), (10, 10)):
                    with self.subTest(args=args, icons=icons, native=native):
                        result, _ = self.invoke(*args, extra_environment={
                            'LABWC_FUZZEL_MANAGED_ICONS': icons, 'NATIVE_STATUS': str(native)})
                        self.assertEqual(result.returncode, expected, result.stderr.decode())
                        self.assertFalse(payload_source_exists(self.runtime / 'labwc-fuzzel.pid'))
                        self.assertFalse(list(self.runtime.glob('labwc-fuzzel-menu.*')))

    def test_launcher_status_is_not_reinterpreted_as_dmenu(self):
        (self.bin / 'fuzzel').write_text('#!/bin/sh\nexit 1\n')
        result, _ = self.invoke('launcher')
        self.assertEqual(result.returncode, 1)

    def test_main_menu_uses_one_menu_file_on_both_output_classes(self):
        for output in ('eDP-1', 'DP-1'):
            with self.subTest(output=output):
                result, args = self.invoke('menu', '--dmenu', output=output)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertIn('--config=' + str(self.config / 'menu.ini'), args)
                self.assertNotIn('--minimal-lines', args)

    def test_main_menu_does_not_inherit_compact_management_clamp(self):
        result, args = self.invoke('menu', '--dmenu', output='eDP-1', extra_environment={
            'FUZZEL_MENU_INTERNAL_WIDTH': '34',
            'FUZZEL_MENU_INTERNAL_LINES': '40',
            'LABWC_FUZZEL_MENU_WIDTH_OVERRIDE': '40'})
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn('--width=34', args)
        self.assertNotIn('--width=18', args)


del _SizingFixture  # unittest discovery must not collect the imported fixture.


class ProfileRenderingTests(unittest.TestCase):
    def test_every_profile_renders_equal_main_and_search_geometry(self):
        transport = render_theme_defaults(payload_read_text(FORKY / 'tests/fixtures/workspaces/render.sh'))
        # The same transport calls the real scalar renderer, not a template mock.
        transport = transport.split('desktop_render_labwc_rc_xml\n', 1)[0]
        transport += '. "$5"\ndesktop_render_fuzzel_configs\n'
        paths = sorted((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(paths), 10)
        for profile in paths:
            with self.subTest(profile=profile.name), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', transport, 'fixture',
                    str(ROOT), tmp, '4', 'thumbnail', str(profile)]),
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                config = Path(tmp) / 'etc/skel-desktop/.config/fuzzel'
                self.assertEqual({p.name for p in config.iterdir()},
                                 {'base.ini', 'fuzzel.ini', 'menu.ini', 'computer-management.ini'})
                search = configparser.ConfigParser(interpolation=None)
                menu = configparser.ConfigParser(interpolation=None)
                search.read(config/'fuzzel.ini'); menu.read(config/'menu.ini')
                self.assertEqual(menu['main']['include'], search['main']['include'])
                for document in (search, menu):
                    self.assertNotIn('width', document['main'])
                    self.assertNotIn('lines', document['main'])
                self.assertFalse(any('__INSTALLER_' in render_theme_defaults(payload_read_text(p)) for p in config.iterdir()))

    def test_waybar_icons_are_centered_and_microphone_has_separate_glyph_font(self):
        source = render_theme_defaults(waybar_config_text(TARGET / 'etc/skel-desktop/.config/waybar'))
        for name in ('wayscriber', 'apps', 'window-switcher'):
            blocks = re.findall(r'"custom/' + name + r'": \{(.*?)\n  \}', source, re.S)
            self.assertEqual(len(blocks), 2)
            for block in blocks:
                self.assertIn('"align": 0.5', block)
        self.assertEqual(source.count("font_family='Font Awesome 6 Free' weight='700'"), 4)
        self.assertEqual(source.count('</span>' + theme_values()['WAYBAR_BUTTON_AUDIO_MICROPHONE_NORMAL_SEPARATOR_ICON_GLYPH'] + '{volume}%'), 4)
        css = render_theme_defaults(payload_read_text(TARGET / 'etc/skel-desktop/.config/waybar/style.css.tmpl'))
        for name in ('wayscriber', 'apps', 'window-switcher', 'lock', 'power', 'backlight'):
            self.assertIn('#custom-' + name + ':hover', css)
        self.assertIn('#pulseaudio:hover', css)
        self.assertNotIn('text-align:', css)  # not GTK3 CSS

    def test_win_menu_and_panel_list_do_not_cycle_the_next_window(self):
        tree = ET.fromstring(render_theme_defaults(payload_read_text(TARGET / 'etc/skel-desktop/.config/labwc/rc.xml.tmpl')))
        bindings = {b.get('key'): b for b in tree.findall('keyboard/keybind')}
        self.assertEqual(bindings['Super_L'].find('action').get('command'), 'labwc-main-menu')
        self.assertEqual(bindings['Super_L'].get('onRelease'), 'yes')
        self.assertEqual(bindings['F13'].find('action').attrib,
                         {'name': 'NextWindow', 'workspace': 'current',
                          'output': '__INSTALLER_LABWC_WINDOW_SWITCHER_CYCLE_OUTPUT__',
                          'identifier': 'all'})
        self.assertEqual(bindings['A-Tab'].find('action').get('name'), 'NextWindow')


class VendorDesktopIncidentTests(unittest.TestCase):
    def setUp(self):
        self.helper = desktop_overrides.load_helper('incident_desktop_fixture')

    def test_only_exact_lynis_command_is_requoted_and_terminal_is_preserved(self):
        value = "su-to-root -c '/usr/sbin/lynis audit system --no-colors'"
        source = '[Desktop Entry]\nType=Application\nName=Lynis\nTerminal=true\nExec=' + value + '\n'
        repaired = self.helper.repair_known_vendor_entry('lynis.desktop', source)
        self.assertIn('Exec=su-to-root -c "/usr/sbin/lynis audit system --no-colors"', repaired)
        output = self.helper.rewrite_desktop(repaired, '/usr/local/bin/labwc-wayland-app intel')
        self.assertIn('Exec=/usr/local/bin/labwc-terminal -e su-to-root -c "', output)
        self.assertEqual(self.helper.repair_known_vendor_entry('other.desktop', source), source)
        altered = source.replace('--no-colors', '--other-option')
        self.assertEqual(self.helper.repair_known_vendor_entry('lynis.desktop', altered), altered)
        self.assertEqual(self.helper.repair_known_vendor_entry('lynis.desktop', repaired), repaired)

    def test_only_missing_freerdp_edit_action_is_removed(self):
        source = '[Desktop Entry]\nType=Application\nName=FreeRDP\nActions=Edit;Connect;\n'
        fixed = self.helper.repair_known_vendor_entry('sdl-freerdp-file.desktop', source)
        self.assertIn('Actions=Connect;', fixed)
        valid = source + '[Desktop Action Edit]\nName=Edit\nExec=/usr/bin/true\n'
        self.assertEqual(self.helper.repair_known_vendor_entry('sdl-freerdp-file.desktop', valid), valid)
        self.assertEqual(self.helper.repair_known_vendor_entry('other.desktop', source), source)


class PolicyIncidentTests(unittest.TestCase):
    def block(self, filename, profile):
        source = (FORKY / 'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl'
                  if profile in ('crowdsec-firstboot', 'firstboot')
                  else TARGET / 'etc/apparmor.d' / filename)
        text = render_theme_defaults(payload_read_text(source))
        return re.search(r'^profile ' + re.escape(profile) + r' .*?^}', text, re.M | re.S).group(0)

    def test_all_recorded_missing_accesses_have_narrow_profile_rules(self):
        compositor = self.block('labwc-session', 'labwc-compositor')
        self.assertIn('owner @{HOME}/.local/share/icons/{,**} r,', compositor)
        self.assertIn('owner /tmp/wtype-?????? rw,', compositor)
        for name in ('labwc-autostart', 'labwc-calendar'):
            self.assertIn('owner @{HOME}/ r,', self.block('desktop-wrappers', name))
        self.assertIn('/usr/share/texmf/fonts/{,**} r,',
                      self.block('desktop-wrappers', 'labwc-greeter-power'))
        self.assertIn('  / r,', self.block('system-wrappers', 'crowdsec-firstboot'))
        self.assertIn('ptrace (read) peer=labwc-wrap-desktop-files,',
                      self.block('system-wrappers', 'firstboot'))
        self.assertIn('ptrace (readby) peer=firstboot,',
                      self.block('desktop-wrappers', 'labwc-wrap-desktop-files'))

    def test_unlock_remains_explicit_without_hiding_real_decryption_errors(self):
        unit = render_theme_defaults(payload_read_text(TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-ssh-key-load.service'))
        self.assertIn('TimeoutStartSec=120', unit)
        self.assertNotIn('SuccessExitStatus=', unit)
        loader = render_theme_defaults(payload_read_text(TARGET / 'usr/local/libexec/labwc-ssh-key-load'))
        self.assertIn('ssh-add', loader)
        stage = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))
        enabled = stage.split('  for unit in \\\n    labwc-output-watch.service', 1)[1].split('\n  done', 1)[0]
        self.assertNotIn('labwc-ssh-key-load.service', enabled)
        self.assertIn('ssh-agent.socket', enabled)


if __name__ == '__main__':
    unittest.main()
