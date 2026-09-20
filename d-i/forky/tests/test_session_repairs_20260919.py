"""September 19 incident regressions; UI endpoints are fixtures, never live.

Real production renderers, wrapper status/cleanup and native AppArmor syntax are
covered elsewhere as well. No test asserts that a target GPU is repaired.
"""
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
        for args in (('menu', '--dmenu'), ('menu', '--dmenu0'), ('main-menu', '--dmenu')):
            for icons in ('0', '1'):
                for native, expected in ((0, 0), (2, 1), (1, 2), (127, 127), (143, 143), (10, 10)):
                    with self.subTest(args=args, icons=icons, native=native):
                        result, _ = self.invoke(*args, extra_environment={
                            'LABWC_FUZZEL_MANAGED_ICONS': icons, 'NATIVE_STATUS': str(native)})
                        self.assertEqual(result.returncode, expected, result.stderr.decode())
                        self.assertFalse((self.runtime / 'labwc-fuzzel.pid').exists())
                        self.assertFalse(list(self.runtime.glob('labwc-fuzzel-menu.*')))

    def test_launcher_status_is_not_reinterpreted_as_dmenu(self):
        (self.bin / 'fuzzel').write_text('#!/bin/sh\nexit 1\n')
        result, _ = self.invoke('launcher')
        self.assertEqual(result.returncode, 1)

    def test_main_menu_uses_search_sized_files_on_both_output_classes(self):
        for name in ('main-menu.ini', 'main-menu-internal.ini'):
            (self.config / name).write_text('[main]\n')
        for output, name in (('eDP-1', 'main-menu-internal.ini'), ('DP-1', 'main-menu.ini')):
            with self.subTest(output=output):
                result, args = self.invoke('main-menu', '--dmenu', output=output)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertIn('--config=' + str(self.config / name), args)
                self.assertNotIn('--minimal-lines', args)

    def test_main_menu_does_not_inherit_compact_management_clamp(self):
        (self.config / 'main-menu-internal.ini').write_text('[main]\n')
        result, args = self.invoke('main-menu', '--dmenu', output='eDP-1', extra_environment={
            'LABWC_FUZZEL_INTERNAL_MAIN_MENU_WIDTH': '34',
            'LABWC_FUZZEL_INTERNAL_MAIN_MENU_LINES': '40',
            'LABWC_FUZZEL_MENU_WIDTH_OVERRIDE': '40'})
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn('--width=34', args)
        self.assertNotIn('--width=18', args)


del _SizingFixture  # unittest discovery must not collect the imported fixture.


class ProfileRenderingTests(unittest.TestCase):
    def test_every_profile_renders_equal_main_and_search_geometry(self):
        transport = (FORKY / 'tests/fixtures/workspaces/render.sh').read_text()
        # The same transport calls the real scalar renderer, not a template mock.
        transport = transport.split('desktop_render_labwc_rc_xml\n', 1)[0]
        transport += '. "$5"\ndesktop_render_fuzzel_configs\n'
        paths = sorted((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(paths), 13)
        for profile in paths:
            with self.subTest(profile=profile.name), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(['/bin/sh', '-eu', '-c', transport, 'fixture',
                    str(ROOT), tmp, '4', 'thumbnail', str(profile)],
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                config = Path(tmp) / 'etc/skel-desktop/.config/fuzzel'
                for suffix in ('', '-internal'):
                    search = configparser.ConfigParser(interpolation=None)
                    menu = configparser.ConfigParser(interpolation=None)
                    search.read(config / ('fuzzel' + suffix + '.ini'))
                    menu.read(config / ('main-menu' + suffix + '.ini'))
                    for key in ('include', 'width', 'lines'):
                        self.assertEqual(menu['main'][key], search['main'][key])
                self.assertFalse(any('__INSTALLER_' in p.read_text() for p in config.iterdir()))

    def test_waybar_icons_are_centered_and_microphone_has_separate_glyph_font(self):
        source = (TARGET / 'etc/skel-desktop/.config/waybar/config.tmpl').read_text()
        for name in ('wayscriber', 'apps', 'window-switcher'):
            blocks = re.findall(r'"custom/' + name + r'": \{(.*?)\n  \}', source, re.S)
            self.assertEqual(len(blocks), 2)
            for block in blocks:
                self.assertIn('"align": 0.5', block)
        self.assertEqual(source.count("font_family='Font Awesome 6 Free' weight='bold'"), 4)
        self.assertEqual(source.count('</span>&#8194;{volume}%'), 4)
        css = (TARGET / 'etc/skel-desktop/.config/waybar/style.css.tmpl').read_text()
        for name in ('wayscriber', 'apps', 'window-switcher', 'lock', 'power', 'backlight'):
            self.assertIn('#custom-' + name + ':hover', css)
        self.assertIn('#pulseaudio:hover', css)
        self.assertNotIn('text-align:', css)  # not GTK3 CSS

    def test_win_menu_and_panel_list_do_not_cycle_the_next_window(self):
        tree = ET.fromstring((TARGET / 'etc/skel-desktop/.config/labwc/rc.xml.tmpl').read_text())
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
        text = (TARGET / 'etc/apparmor.d' / filename).read_text()
        return re.search(r'^profile ' + re.escape(profile) + r' .*?^}', text, re.M | re.S).group(0)

    def test_all_recorded_missing_accesses_have_narrow_profile_rules(self):
        compositor = self.block('managed-labwc-session', 'managed-labwc-compositor')
        self.assertIn('owner @{HOME}/.local/share/icons/{,**} r,', compositor)
        self.assertIn('owner /tmp/wtype-?????? rw,', compositor)
        for name in ('managed-labwc-autostart', 'managed-labwc-calendar'):
            self.assertIn('owner @{HOME}/ r,', self.block('managed-desktop-wrappers', name))
        self.assertIn('/usr/share/texmf/fonts/{,**} r,',
                      self.block('managed-desktop-wrappers', 'managed-labwc-greeter-power'))
        self.assertIn('  / r,', self.block('managed-system-wrappers', 'managed-crowdsec-firstboot'))
        self.assertIn('ptrace (read) peer=managed-labwc-wrap-desktop-files,',
                      self.block('managed-system-wrappers', 'managed-firstboot'))
        self.assertIn('ptrace (readby) peer=managed-firstboot,',
                      self.block('managed-desktop-wrappers', 'managed-labwc-wrap-desktop-files'))

    def test_unlock_remains_explicit_without_hiding_real_decryption_errors(self):
        unit = (TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-ssh-key-load.service').read_text()
        self.assertIn('TimeoutStartSec=120', unit)
        self.assertNotIn('SuccessExitStatus=', unit)
        loader = (TARGET / 'usr/local/libexec/labwc-ssh-key-load').read_text()
        self.assertIn('ssh-add', loader)
        stage = (FORKY / 'scripts/desktop/components.sh').read_text()
        enabled = stage.split('  for unit in \\\n    labwc-output-watch.service', 1)[1].split('\n  done', 1)[0]
        self.assertNotIn('labwc-ssh-key-load.service', enabled)
        self.assertIn('ssh-agent.socket', enabled)


if __name__ == '__main__':
    unittest.main()
