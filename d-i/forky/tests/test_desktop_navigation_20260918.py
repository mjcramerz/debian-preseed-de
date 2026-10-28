"""Menu data boundaries and real installer integration, without a GUI session."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from payload_fixture import waybar_config_text
from payload_fixture import installed_argv as payload_installed_argv, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
BIN = TARGET / 'usr/local/bin'


def load(name):
    path = BIN / name
    module = types.ModuleType('fixture_' + name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
    return module




class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.menu = load('labwc-computer-management')

    def test_exactly_six_top_level_groups_and_twenty_five_unique_routes(self):
        self.assertEqual(list(self.menu.MENUS), ['System & Recovery', 'Network & Remote',
                         'Security & Accounts', 'Devices & Desktop', 'Containers & AI', 'Files & Documents'])
        routes = [route for entries in self.menu.MENUS.values() for route in entries.values()]
        # Keep all 25 existing routes and add the requested Network Sharing route.
        self.assertEqual(len(routes), 26)
        self.assertEqual(self.menu.MENUS['Network & Remote']['Network Sharing'], ('labwc-network-sharing',))
        self.assertEqual(len(routes), len(set(routes)))

    def test_all_original_management_areas_remain_reachable(self):
        routes = {route for entries in self.menu.MENUS.values() for route in entries.values()}
        for route in (('labwc-maintenance-menu','system'), ('labwc-maintenance-menu','recovery'),
                      ('labwc-maintenance-menu','security'), ('labwc-podman-menu',),
                      ('labwc-remote-desktop',), ('labwc-digital-assets',),
                      ('labwc-users-groups-menu',), ('labwc-adb-menu',),
                      ('labwc-external-drives',), ('labwc-ai-copilots',),
                      ('labwc-network-scan-menu',), ('labwc-bluetooth','menu')):
            self.assertIn(route, routes)
        for category in ('connections', 'vpn', 'wireguard', 'dns'):
            self.assertIn(('labwc-network-control-menu', category), routes)

    def test_cancel_and_exit_at_root_succeed_without_actions(self):
        for selection in (None, 'Exit'):
            with mock.patch.object(self.menu, 'choose', return_value=selection), \
                    mock.patch.object(self.menu, 'run_action') as action:
                self.assertEqual(self.menu.run_menu(), 0)
                action.assert_not_called()

    def test_back_and_cancel_return_to_parent_not_an_action(self):
        for back in ('Back', None):
            with mock.patch.object(self.menu, 'choose', side_effect=['Containers & AI', back, 'Exit']) as choose, \
                    mock.patch.object(self.menu, 'run_action') as action:
                self.assertEqual(self.menu.run_menu(), 0)
                self.assertEqual(choose.call_args.args[1], 'Computer Management')
                action.assert_not_called()

    def test_completed_action_returns_to_same_group(self):
        sequence=['Containers & AI','Containers','Back','Exit']
        with mock.patch.object(self.menu, 'choose', side_effect=sequence) as choose, \
                mock.patch.object(self.menu, 'run_action', return_value=7) as action:
            self.assertEqual(self.menu.run_menu(), 0)
            action.assert_called_once_with(('labwc-podman-menu',))
            self.assertEqual(choose.call_args_list[1].args, choose.call_args_list[2].args)

    def test_action_uses_only_argv_and_existing_wrapper(self):
        with mock.patch.object(self.menu.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as run, \
                mock.patch.object(self.menu.Path, 'is_file', return_value=False):
            self.menu.run_action(('labwc-wayland-app', 'auto', '--', '/usr/bin/pavucontrol'))
            self.assertEqual(run.call_args.args[0], ('/usr/local/bin/labwc-wayland-app', 'auto', '--', '/usr/bin/pavucontrol'))
            self.assertNotIn('shell', run.call_args.kwargs)

    def test_entry_point_uses_graphical_fuzzel_without_a_terminal(self):
        with mock.patch.object(self.menu.os, 'geteuid', return_value=1000), \
                mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(self.menu, 'run_menu', return_value=0) as run_menu, \
                mock.patch('builtins.open') as opened:
            self.assertEqual(self.menu.main([]), 0)
            run_menu.assert_called_once_with()
            opened.assert_not_called()
            self.assertNotIn('LABWC_MENU_BACKEND', os.environ)
            self.assertEqual(os.environ['LABWC_MENU_ACTION_WAIT'], '1')

    def test_root_refused_and_unknown_arguments_rejected(self):
        with mock.patch.object(self.menu.os, 'geteuid', return_value=0), self.assertRaises(ValueError):
            self.menu.main([])
        with mock.patch.object(self.menu.os, 'geteuid', return_value=1000), self.assertRaises(ValueError):
            self.menu.main(['--unknown'])

    def test_removed_terminal_mode_is_rejected_before_opening_a_tty(self):
        with mock.patch.dict(os.environ, {'FZF_DEFAULT_COMMAND':'untrusted'}, clear=True), \
                mock.patch.object(self.menu.os, 'geteuid', return_value=1000), \
                mock.patch('builtins.open', mock.mock_open()) as opened, \
                mock.patch.object(self.menu, 'run_menu') as run:
            with self.assertRaises(ValueError):
                self.menu.main(['--terminal'])
            opened.assert_not_called()
            run.assert_not_called()

    def test_maintenance_and_recovery_offer_every_action_once(self):
        import ast
        source = render_theme_defaults(payload_read_text(BIN/'labwc-maintenance-menu'))
        tree = ast.parse(source)
        values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {'SYSTEM_GROUPS', 'RECOVERY_GROUPS'}:
                        values[target.id] = ast.literal_eval(node.value)
        system = [label for labels in values['SYSTEM_GROUPS'].values() for label in labels]
        recovery = [label for labels in values['RECOVERY_GROUPS'].values() for label, _ in labels]
        self.assertEqual(len(system), 42)
        self.assertEqual(len(recovery), 21)
        self.assertEqual(len(system), len(set(system)))
        self.assertEqual(len(recovery), len(set(recovery)))
        for confirmation in ('confirmed-system-action', 'confirmed-recovery-action',
                             'confirmed-apparmor-profile-tool', 'confirmed-apparmor-profile-state-change'):
            self.assertIn(confirmation, source)

    def test_custom_data_prompts_explicitly_opt_in_not_all_action_menus(self):
        for script in ('labwc-adb-menu', 'labwc-firewall-menu', 'labwc-network-control-menu',
                       'labwc-network-scan-menu', 'labwc-maintenance-menu'):
            text = render_theme_defaults(payload_read_text(BIN/script))
            self.assertTrue('LABWC_MENU_INPUT_MODE=text' in text or
                            '"LABWC_MENU_INPUT_MODE": "text"' in text or
                            'environment["LABWC_MENU_INPUT_MODE"] = "text"' in text)
        maintenance = render_theme_defaults(payload_read_text(BIN/'labwc-maintenance-menu'))
        self.assertIn('text_input=True', maintenance)
        self.assertIn('Expected SHA-256', maintenance)
        self.assertIn('Absolute executable path', maintenance)


class DesktopIntegrationTests(unittest.TestCase):
    def test_every_fuzzel_category_has_an_explicit_distinct_icon(self):
        menu = load('labwc-main-menu')
        icons = [menu.MENU_ICONS[name] for name in menu.DISPLAY_CATEGORIES]
        self.assertEqual(len(icons), 11)
        self.assertEqual(len(set(icons)), 11)
        self.assertTrue(all(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', icon) for icon in icons))

    def test_fuzzel_icon_selection_preserves_exact_mapping(self):
        menu = load('labwc-main-menu')
        display = 'Development'
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0,stdout=display+'\n')) as run:
            self.assertEqual(menu.choose({'Development':None}, 'Main Menu'), 'Development')
            self.assertEqual(run.call_args.kwargs['input'], 'Development\0icon\x1fapplications-development\n')
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0,stdout='\uf121  Development\n')):
            self.assertIsNone(menu.choose({'Development':None}, 'Main Menu'))

    def test_application_names_are_not_rewritten_as_category_icons(self):
        menu=load('labwc-main-menu')
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0,stdout='System\n')) as run:
            self.assertEqual(menu.choose({'System':'sample.desktop'}, 'Utilities'), 'System')
            self.assertEqual(run.call_args.kwargs['input'], 'System\0icon\x1fapplication-x-executable\n')

    def test_normal_fuzzel_execution_and_search_are_not_replaced(self):
        wrapper=render_theme_defaults(payload_read_text(BIN/'labwc-fuzzel'))
        self.assertNotIn('LABWC_MENU_BACKEND', wrapper)
        self.assertNotIn('labwc-fzf-menu', wrapper)
        self.assertIn('/usr/bin/fuzzel', wrapper)
        self.assertIn('labwc-main-menu --search', render_theme_defaults(payload_read_text(BIN/'labwc-run')))

    def test_f13_native_press_binding_and_both_alt_tab_bindings(self):
        root=ET.fromstring(render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/labwc/rc.xml.tmpl')))
        binds={item.attrib['key']:item for item in root.findall('./keyboard/keybind')}
        self.assertNotIn('onRelease', binds['F13'].attrib)
        self.assertEqual(binds['F13'].find('action').attrib,
                         {'name': 'NextWindow', 'workspace': 'current',
                          'output': '__INSTALLER_LABWC_WINDOW_SWITCHER_CYCLE_OUTPUT__',
                          'identifier': 'all'})
        self.assertEqual(binds['A-Tab'].find('action').get('name'), 'NextWindow')
        self.assertEqual(binds['A-S-Tab'].find('action').get('name'), 'PreviousWindow')

    def test_button_order_is_between_workspaces_and_wayscriber(self):
        source=render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/components.sh'))
        self.assertIn('"ext/workspaces", "custom/tomat", "custom/wayscriber", "custom/window-switcher"', source)
        config=render_theme_defaults(waybar_config_text(TARGET / 'etc/skel-desktop/.config/waybar'))
        self.assertEqual(config.count('"custom/window-switcher": {'), 2)
        self.assertEqual(config.count('"modules-left": [__INSTALLER_LABWC_WAYBAR_MODULES_LEFT__]'), 2)

    def test_button_icon_green_and_transient_lifecycle_preserved(self):
        css=render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/waybar/taskview.css.tmpl'))
        blocks=re.findall(r'(?:^|\n)#custom-window-switcher\s*\{([^}]*)\}', css)
        block='\n'.join(blocks)
        self.assertIn('color: ' + theme_values()['WAYBAR_BUTTON_TASKVIEW_NORMAL_ICON_COLOR'] + ';',block)
        self.assertIn('Font Awesome 6 Free',block)
        self.assertIn('#custom-wayscriber {', payload_read_text(FORKY/'hooks/target/etc/skel-desktop/.config/waybar/style.css.tmpl'))
        config=render_theme_defaults(waybar_config_text(TARGET / 'etc/skel-desktop/.config/waybar'))
        clicks=re.findall(r'"on-click-release": "([^"\n]* -- /usr/local/bin/labwc-window-switcher)"',config)
        self.assertEqual(len(clicks),2)
        for click in clicks:
            for option in ('--user','--collect','--service-type=exec','--expand-environment=no',
                           '--property=Requisite=labwc-session.target','--property=After=labwc-session.target',
                           '--property=PartOf=labwc-session.target','--property=ExitType=cgroup',
                           '--property=KillMode=control-group','--property=TimeoutStopSec=1s',
                           '--no-block','--unit=labwc-window-switcher','--property=RuntimeMaxSec=3s'):
                self.assertIn(option,click)
        self.assertEqual(config.count('"format": "\uf24d"'),2)

    def test_wtype_wrapper_has_fixed_argv_without_alt_or_fake_mouse_grabs(self):
        wrapper=render_theme_defaults(payload_read_text(BIN/'labwc-window-switcher'))
        self.assertIn('exec /usr/bin/timeout --signal=TERM --kill-after=1s 2s /usr/bin/wtype -P F13 -p F13',wrapper)
        self.assertIn('[ "$#" -eq 0 ]',wrapper)
        self.assertNotIn('-M alt',wrapper)
        self.assertNotIn('-m alt',wrapper)
        self.assertNotIn('on-click-right', wrapper)

    def test_new_executables_and_font_policy_are_staged_and_verified(self):
        stage=render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/components.sh'))
        verify=render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/verify.sh'))
        firstboot=render_theme_defaults(payload_read_text(FORKY/'scripts/firstboot/04-validation.sh'))
        for name in ('labwc-window-switcher',):
            self.assertIn(f'usr/local/bin/{name} /usr/local/bin/{name} 0755',stage)
            self.assertIn(name,verify); self.assertIn(name,firstboot)
            self.assertTrue(payload_source_stat(BIN/name).st_mode & 0o111)
        self.assertIn('terminal-fonts/current/release-manifest.json',verify)
        self.assertIn('require_absent /usr/local/libexec/installer-desktop-fonts',verify)

    def test_apparmor_keeps_strict_profiles_and_font_access_readonly(self):
        profiles=render_theme_defaults(payload_read_text(TARGET/'etc/apparmor.d/desktop-wrappers'))
        for name in ('labwc-window-switcher',):
            self.assertIn(f'profile {name} /usr/local/bin/{name}',profiles)
        self.assertNotIn('labwc-fzf-menu', profiles)
        font_rule=render_theme_defaults(payload_read_text(TARGET/'etc/apparmor.d/abstractions/fonts.d/labwc-terminal-fonts'))
        self.assertIn('owner @{HOME}/.local/share/icons/terminal-fonts/** r,',font_rule)
        self.assertNotIn('rw',font_rule)
        self.assertIn('abstractions/fonts.d/labwc-terminal-fonts', render_theme_defaults(payload_read_text(FORKY/'scripts/late/security.sh')))

    def test_terminal_and_fuzzel_have_symbols_font_fallbacks(self):
        for relative in ('foot/foot.ini','kitty/kitty.conf'):
            self.assertIn('Symbols Nerd Font Mono', render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config'/relative)))
        self.assertIn('Symbols Nerd Font Mono', render_theme_defaults(payload_read_text(TARGET/'usr/local/bin/labwc-fuzzel')))
        base = payload_read_text(TARGET/'etc/skel-desktop/.config/fuzzel/base.ini.tmpl')
        self.assertIn('dpi-aware=yes', base)
        self.assertNotRegex(base, r'(?m)^font=')


if __name__ == '__main__':
    unittest.main()
