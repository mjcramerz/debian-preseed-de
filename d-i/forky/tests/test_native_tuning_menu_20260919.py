"""Native icon protocol and confined management-to-tuning routing fixtures.

No Wayland session, hardware write, live systemd operation or broker is started.
"""
from __future__ import annotations
from payload_fixture import read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import ast
import json
import os
from pathlib import Path
import subprocess
import types
import unittest
from unittest import mock

import test_kanshi_fuzzel_followup_20260919 as native

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
BIN = TARGET / 'usr/local/bin'
AA = TARGET / 'etc/apparmor.d'
CLIENT = TARGET / 'usr/local/lib/hardware_tuning/client.py'
PROFILES = ('performance', 'high', 'balanced', 'silent')
TOP = ['Set Single Tuning Profile', 'Generate Hardware Tuning Report', 'Start Automatic Tuning',
       'Stop Automatic Tuning', 'Enable Autostart Tuning at Boot', 'Disable Autostart Tuning at Boot', 'Reset Hardware Tuning']
CANCEL = 'Cancel - leave power policy unchanged'
CONFIRM = 'Confirm: stop PPD and block its restart until tuning is stopped'
BOOT_CONFIRM = 'Confirm: stop, disable and mask PPD; start tuning now and at boot'


def client_functions():
    # Avoid colliding with other tests' independently imported common modules.
    selected = [node for node in ast.parse(render_theme_defaults(payload_read_text(CLIENT))).body
                if isinstance(node, ast.FunctionDef) and node.name in {'choose', 'confirm_owner', 'menu'}]
    namespace = {'os': os, 'subprocess': subprocess, 'TuningError': ValueError,
                 'PROFILES': PROFILES, 'json': json}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(CLIENT), 'exec'), namespace)
    return namespace


class NativeTuningIconTests(unittest.TestCase):
    setUp = native.NativeShellProtocolTests.setUp
    pick = native.NativeShellProtocolTests.pick

    def test_every_tuning_action_profile_and_confirmation_has_exact_native_icon(self):
        icons = dict(zip(TOP, ('preferences-system', 'text-x-generic', 'media-playback-start',
                              'media-playback-stop', 'system-run', 'process-stop', 'edit-undo')))
        icons['Hardware Tuning'] = 'preferences-system'
        icons['Reset Profiles [All]'] = 'edit-undo'
        for vendor in ('Intel', 'Nvidia'):
            for profile, icon in zip(PROFILES, ('utilities-system-monitor', 'go-up', 'preferences-system-power-management', 'battery')):
                icons[f'Set {profile.title()} Profile [{vendor}]'] = icon
        icons.update({CANCEL: 'dialog-cancel', CONFIRM: 'dialog-warning', BOOT_CONFIRM: 'dialog-warning'})
        result, payload = self.pick(list(icons), root=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = payload.rstrip(b'\n').split(b'\n')
        self.assertEqual(len(rows), len(icons) + 1)
        for (label, icon), row in zip(icons.items(), rows):
            self.assertEqual(row, (label + '\0icon\x1f' + icon).encode())
        self.assertEqual(rows[-1], b'Back\0icon\x1fgo-previous')

    def test_each_tuning_label_roundtrips_to_unchanged_dispatch_value(self):
        labels = TOP + ['Reset Profiles [All]'] + [f'Set {p.title()} Profile [{v}]' for v in ('Intel', 'Nvidia') for p in PROFILES]
        for index, label in enumerate(labels):
            with self.subTest(label=label):
                result, _ = self.pick(labels, index=index)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.decode(), label + '\n')


class MenuBoundaryTests(unittest.TestCase):
    def test_main_refuses_protocol_control_labels_before_spawning_picker(self):
        menu = native.load(BIN / 'labwc-main-menu')
        for label in ('A\nB', 'A\0icon\x1finjected', 'A\rB', 'A\x1fB', 'A\u2028B', 'A\ud800B'):
            with self.subTest(label=repr(label)), mock.patch.object(menu.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    menu.choose({label: ()}, 'Main Menu')
                run.assert_not_called()

    def test_main_uses_native_utf8_rows_and_preserves_theme_selection(self):
        menu = native.load(BIN / 'labwc-main-menu')
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0, stdout='Computer Management\n')) as run:
            self.assertEqual(menu.choose({'Computer Management': ()}, 'Main Menu'), 'Computer Management')
        self.assertEqual(run.call_args.kwargs['input'], 'Computer Management\0icon\x1fcomputer\n')
        self.assertEqual(run.call_args.kwargs['encoding'], 'utf-8')
        self.assertEqual(run.call_args.kwargs['env']['LABWC_FUZZEL_MANAGED_ICONS'], '0')
        self.assertNotIn('--icon-theme', ' '.join(run.call_args.args[0]))
        for name in ('base.ini.tmpl', 'menu.ini.tmpl', 'fuzzel.ini.tmpl'):
            self.assertIn('icons-enabled=yes', render_theme_defaults(payload_read_text(TARGET / 'etc/skel-desktop/.config/fuzzel' / name)))
        self.assertIn('icon-theme=' + theme_values()['FUZZEL_MENU_ICON_THEME'], render_theme_defaults(payload_read_text(TARGET / 'etc/skel-desktop/.config/fuzzel/base.ini.tmpl')))

    def test_standalone_hardware_chooser_owns_metadata_contract_without_changing_explicit_backend(self):
        client = client_functions()
        environment = {'LABWC_FUZZEL_MANAGED_ICONS': '0', 'LABWC_FUZZEL_ROOT_MENU': '1',
                       'LABWC_MENU_INPUT_MODE': 'text', 'LABWC_MENU_BACKEND': 'fzf'}
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(subprocess, 'run',
                return_value=types.SimpleNamespace(returncode=0, stdout=TOP[0] + '\n')) as run:
            self.assertEqual(client['choose'](TOP, 'Hardware tuning> '), TOP[0])
        passed = run.call_args.kwargs['env']
        self.assertEqual(passed['LABWC_FUZZEL_MANAGED_ICONS'], '1')
        self.assertEqual(passed['LABWC_FUZZEL_ROOT_MENU'], '0')
        self.assertEqual(passed['LABWC_MENU_INPUT_MODE'], 'choice')
        self.assertEqual(passed['LABWC_MENU_BACKEND'], 'fzf')
        self.assertEqual(run.call_args.args[0][:3], ['/usr/local/bin/labwc-fuzzel', 'menu', '--dmenu'])

    def test_hardware_route_is_in_devices_and_desktop_with_fixed_argv(self):
        menu = native.load(BIN / 'labwc-computer-management')
        self.assertEqual(menu.MENUS['Devices & Desktop']['Hardware Tuning'], ('labwc-hardware-tuning', 'menu'))
        self.assertEqual(sum('Hardware Tuning' in entries for entries in menu.MENUS.values()), 1)
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as run, \
                mock.patch.object(menu.Path, 'is_file', return_value=False):
            self.assertEqual(menu.run_action(menu.MENUS['Devices & Desktop']['Hardware Tuning']), 0)
        self.assertEqual(run.call_args.args[0], ('/usr/local/bin/labwc-hardware-tuning', 'menu'))
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_hardware_unavailable_is_hidden_without_mutating_catalogue(self):
        for is_file, executable, available in ((False, True, False), (True, False, False), (True, True, True)):
            with self.subTest(is_file=is_file, executable=executable):
                menu = native.load(BIN / 'labwc-computer-management')
                responses = ['Devices & Desktop'] + (['Hardware Tuning'] if available else []) + ['Back', 'Exit']
                with mock.patch.object(menu, 'choose', side_effect=responses) as choose, \
                        mock.patch.object(menu.Path, 'is_file', return_value=is_file), \
                        mock.patch.object(menu.os, 'access', return_value=executable), \
                        mock.patch.object(menu, 'run_action', return_value=0) as action:
                    self.assertEqual(menu.run_menu(), 0)
                self.assertEqual('Hardware Tuning' in choose.call_args_list[1].args[0], available)
                self.assertIn('Hardware Tuning', menu.MENUS['Devices & Desktop'])
                if available:
                    action.assert_called_once_with(('labwc-hardware-tuning', 'menu'))
                    self.assertEqual(choose.call_args_list[2].args[1], 'Computer Management / Devices & Desktop')
                else:
                    action.assert_not_called()

    def test_optional_confined_transition_and_signal_endpoints_are_staged(self):
        bridge = AA / 'abstractions/hardware-tuning-management-parent'
        self.assertIn('/usr/local/bin/labwc-hardware-tuning rPx,', render_theme_defaults(payload_read_text(bridge)))
        self.assertNotIn('rPUx', render_theme_defaults(payload_read_text(bridge)))
        self.assertIn('signal (receive) set=(chld) peer=hardware-tuning-client,', render_theme_defaults(payload_read_text(bridge)))
        self.assertIn('signal (send) set=(chld) peer=labwc-computer-management,', render_theme_defaults(payload_read_text(AA / 'hardware-tuning')))
        wrappers = render_theme_defaults(payload_read_text(AA / 'desktop-wrappers'))
        self.assertIn('include if exists <abstractions/hardware-tuning-management-parent>', wrappers)
        installer = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/hardware-tuning.sh'))
        self.assertIn('for hardware_bridge in desktop-parent fuzzel-parent management-parent;', installer)
        self.assertLess(installer.index('if [ -z "$hardware_vendors" ]'), installer.index('for hardware_bridge'))


class TuningDispatchTests(unittest.TestCase):
    def exercise(self, selections, vendors=('intel', 'nvidia'), claimed=False):
        client = client_functions()
        status = {'vendors': list(vendors), 'policy_owner': {'claimed': claimed}}
        request = mock.Mock(side_effect=lambda action, *args, **kwargs: status if action == 'status' else {})
        client.update(choose=mock.Mock(side_effect=selections), request=request, notify=mock.Mock())
        result = client['menu']()
        return result, client, request

    def test_every_vendor_profile_uses_exact_broker_arguments(self):
        for vendor in ('intel', 'nvidia'):
            for profile in PROFILES:
                with self.subTest(vendor=vendor, profile=profile):
                    label = f'Set {profile.title()} Profile [{vendor.title()}]'
                    selections = [TOP[0], label] + ([CONFIRM] if vendor == 'intel' else [])
                    result, client, request = self.exercise(selections)
                    self.assertEqual(result, 0)
                    request.assert_called_with('manual', vendor, profile, confirm_policy_owner=(vendor == 'intel'))
                    self.assertEqual(client['choose'].call_args_list[0].args[0], TOP)

    def test_each_lifecycle_action_uses_fixed_broker_action_and_required_confirmation(self):
        for label, action in zip(TOP[2:], ('auto-start', 'auto-stop', 'boot-enable', 'boot-disable', 'reset')):
            confirming = action in {'auto-start', 'boot-enable'}
            selections = [label] + ([BOOT_CONFIRM if action == 'boot-enable' else CONFIRM] if confirming else [])
            with self.subTest(action=action):
                result, _, request = self.exercise(selections)
                self.assertEqual(result, 0)
                request.assert_called_with(action, confirm_policy_owner=confirming)

    def test_cancel_handover_and_back_never_send_mutating_requests(self):
        for selections in ([None], [TOP[0], None], [TOP[2], CANCEL], [TOP[4], None], [TOP[0], 'Set High Profile [Intel]', CANCEL]):
            with self.subTest(selections=selections):
                result, _, request = self.exercise(selections)
                self.assertEqual(result, 0)
                request.assert_called_once_with('status')

    def test_reset_profiles_is_vendor_neutral_and_requires_no_handover(self):
        result, _, request = self.exercise([TOP[0], 'Reset Profiles [All]'])
        self.assertEqual(result, 0)
        request.assert_called_with('profiles-reset', None, None, confirm_policy_owner=False)

    def test_report_is_read_only_and_saved_through_existing_private_writer(self):
        client = client_functions()
        report = {'hardware': {}}
        request = mock.Mock(side_effect=[{'vendors': ['intel']}, report])
        saved = mock.Mock(return_value=(Path('/fixture/report.json'), Path('/fixture/report.txt')))
        client.update(choose=mock.Mock(return_value=TOP[1]), request=request, save_report=saved, notify=mock.Mock())
        self.assertEqual(client['menu'](), 0)
        self.assertEqual(request.call_args_list, [mock.call('status'), mock.call('report')])
        saved.assert_called_once_with(report)


if __name__ == '__main__':
    unittest.main()
