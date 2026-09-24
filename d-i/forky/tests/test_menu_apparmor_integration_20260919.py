"""Menu contracts and AppArmor integration; no privileged actions are executed.

Shell fixtures retain the actual chooser/dispatcher functions and replace only
external UI/action endpoints. Offline policy parsing does not claim kernel
mediation or a live Wayland session.
"""
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from fuzzel_fixture import geometry_environment, wrapper_script
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
import types
import unittest
from theme_fixture import render_theme_tree
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
BIN = TARGET / 'usr/local/bin'
AA = TARGET / 'etc/apparmor.d'


def load(name):
    path = BIN / name
    module = types.ModuleType('menu_fixture_' + name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
    return module


def function(name, script):
    source = render_theme_defaults(payload_read_text(BIN / script))
    found = re.search(r'^' + re.escape(name) + r'\(\) \{\n.*?^\}', source, re.M | re.S)
    if not found:
        raise AssertionError('missing fixture function: ' + script + ':' + name)
    return found.group(0) + '\n'


def shell(script, *, env=None, data='', args=()):
    return subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', script, 'fixture', *args]),
                          input=data, text=True, capture_output=True, timeout=10,
                          env={**os.environ, **(env or {})})


def profile(source, name):
    # Top-level policy boundaries only; braces in AppArmor path globs do not
    # affect the source-file convention of closing a top-level block at col 0.
    found = re.search(r'^profile ' + re.escape(name) + r' .*?^\}',
                      render_theme_defaults(payload_read_text(source)), re.M | re.S)
    if not found:
        raise AssertionError('missing profile: ' + name)
    return found.group(0)


SHELL_MENUS = ('labwc-bluetooth', 'labwc-brightness-control', 'labwc-capture',
               'labwc-external-drives', 'labwc-firewall-menu',
               'labwc-maintenance-menu', 'labwc-network-control-menu',
               'labwc-network-scan-menu', 'labwc-power-menu',
               'labwc-power-settings', 'labwc-users-groups-menu')


class PickerFailureTests(unittest.TestCase):
    def test_every_shell_menu_distinguishes_cancellation_and_backend_failure(self):
        for name in SHELL_MENUS:
            helper = function('menu_failure', name)
            for status in (1, 2, 126, 127, 143):
                with self.subTest(menu=name, status=status):
                    result = shell(helper + 'menu_failure "$1"; printf continued', args=(str(status),))
                    self.assertEqual(result.returncode, 0 if status == 1 else status)
                    self.assertEqual(result.stdout, 'continued' if status == 1 else '')
                    if status != 1:
                        self.assertIn('fatal: menu picker failed', result.stderr)

    def test_actual_shell_chooser_preserves_error_not_partial_stdout(self):
        for name in ('labwc-maintenance-menu', 'labwc-network-control-menu',
                     'labwc-network-scan-menu', 'labwc-firewall-menu'):
            for status in (0, 1, 2):
                with self.subTest(menu=name, status=status):
                    script = function('menu_failure', name) + function('choose_lines', name).replace('labwc-fuzzel', 'picker_fixture')
                    script += 'picker_fixture() { cat >/dev/null; [ "$STATUS" -ne 0 ] || printf "Allowed\\n"; return "$STATUS"; };\n'
                    script += 'selected=$(choose_lines Prompt Allowed); printf "result=%s" "$selected"'
                    result = shell(script, env={'STATUS': str(status)})
                    self.assertEqual(result.returncode, 2 if status == 2 else 0, result.stderr)
                    self.assertEqual(result.stdout, '' if status == 2 else 'result=' + ('Allowed' if status == 0 else ''))

    def test_remote_picker_closed_selection_and_errors(self):
        menu = load('labwc-remote-desktop')
        with mock.patch.object(menu.shutil, 'which', return_value='/fixture/picker'):
            for code in (0, 1, 2, 127):
                with self.subTest(code=code), mock.patch.object(menu.subprocess, 'run',
                        return_value=types.SimpleNamespace(returncode=code, stdout='Allowed\n')):
                    if code > 1:
                        with self.assertRaises(SystemExit):
                            menu.run_fuzzel('Prompt', ['Allowed'])
                    else:
                        self.assertEqual(menu.run_fuzzel('Prompt', ['Allowed']), 'Allowed' if code == 0 else None)
            for value in ('Allowed\nExtra\n', 'unknown\n', 'Allowed\n\n'):
                with mock.patch.object(menu.subprocess, 'run',
                        return_value=types.SimpleNamespace(returncode=0, stdout=value)):
                    self.assertIsNone(menu.run_fuzzel('Prompt', ['Allowed']))
            with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(
                    returncode=0, stdout='value\nextra\n')), self.assertRaises(SystemExit):
                menu.run_fuzzel('Prompt', [], text_input=True)

    def test_podman_choice_and_text_errors_are_not_cancel(self):
        menu = load('labwc-podman-menu')
        for chooser in (lambda: menu.menu('Prompt', ['Allowed']), lambda: menu.entry('Prompt')):
            for code in (1, 2, 127):
                with self.subTest(code=code), mock.patch.object(menu.subprocess, 'run',
                        return_value=types.SimpleNamespace(returncode=code, stdout='Allowed\n')):
                    if code == 1:
                        self.assertIsNone(chooser())
                    else:
                        with self.assertRaises(RuntimeError): chooser()
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(
                returncode=0, stdout='Allowed\n\n')):
            self.assertIsNone(menu.menu('Prompt', ['Allowed']))
            with self.assertRaises(ValueError): menu.entry('Prompt')

    def test_invalid_fzf_mode_and_bidi_suggestions_fail_before_opening_tty(self):
        menu = load('labwc-fzf-menu')
        for mode, data in (('typo', b'Allowed\n'), ('text', 'name\u202eevil\n'.encode())):
            with self.subTest(mode=mode), mock.patch.object(menu.os, 'geteuid', return_value=1000), \
                    mock.patch.object(menu.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(data))), \
                    mock.patch.dict(os.environ, {'LABWC_MENU_INPUT_MODE': mode}), \
                    mock.patch('builtins.open') as opened, self.assertRaises(ValueError):
                menu.main(['--dmenu'])
            opened.assert_not_called()

    def test_fzf_nul_protocol_preserves_newline_filename_as_data(self):
        menu = load('labwc-fzf-menu')
        value = 'file\nname'
        with mock.patch.object(menu.os, 'geteuid', return_value=1000), \
                mock.patch.object(menu.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO((value+'\0').encode()))), \
                mock.patch.object(menu.sys, 'stdout', new_callable=io.StringIO) as output, \
                mock.patch.dict(os.environ, {'LABWC_MENU_INPUT_MODE': 'choice'}), \
                mock.patch('builtins.open', mock.mock_open()), \
                mock.patch.object(menu, 'select', return_value=(0, value)) as select:
            self.assertEqual(menu.main(['--dmenu0']), 0)
            self.assertEqual(select.call_args.args[0], [value])
            self.assertEqual(output.getvalue(), value + '\0')


class ActionContractTests(unittest.TestCase):
    def test_main_menu_has_fixed_management_route_with_strict_profile_transition(self):
        menu = load('labwc-main-menu')
        self.assertEqual(menu.ACTIONS['Computer Management'], ('/usr/local/bin/labwc-computer-management',))
        policy = profile(AA / 'desktop-wrappers', 'labwc-main-menu')
        self.assertIn('/usr/local/bin/labwc-computer-management rPx -> labwc-computer-management,', policy)

    def test_all_twenty_four_management_routes_execute_only_their_fixed_argv(self):
        menu = load('labwc-computer-management')
        routes = [route for items in menu.MENUS.values() for route in items.values()]
        self.assertEqual(len(set(routes)), 24)
        with mock.patch.object(menu.Path, 'is_file', return_value=False):
            for route in routes:
                expected = route if route[0].startswith('/') else ('/usr/local/bin/' + route[0], *route[1:])
                with self.subTest(route=route), mock.patch.object(menu.subprocess, 'run',
                        return_value=types.SimpleNamespace(returncode=7)) as run:
                    self.assertEqual(menu.run_action(route), 7)
                    self.assertEqual(run.call_args.args[0], expected)
                    self.assertNotIn('shell', run.call_args.kwargs)

    def test_every_management_local_executable_exists_and_is_staged(self):
        menu = load('labwc-computer-management')
        staging = (render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))
                   + render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/hardware-tuning.sh')))
        for entries in menu.MENUS.values():
            for route in entries.values():
                command = route[0]
                path = command if command.startswith('/') else '/usr/local/bin/' + command
                if path.startswith('/usr/local/'):
                    with self.subTest(path=path):
                        self.assertTrue(payload_source_is_file(TARGET / path.lstrip('/')))
                        self.assertIn(Path(path).name, staging)

    def test_wan_prompts_allow_text_only_after_explicit_authorization(self):
        name = 'labwc-network-scan-menu'
        base = function('run_selected_nmap_action', name) + function('run_specific_wan_scan', name)
        base += r'''
choose_lines() {
  case "$1" in
    'Nmap target scope') printf 'Authorized WAN IPv4 host\n' ;;
    'WAN scan authorization') printf '%s\n' "$AUTHORIZATION" ;;
    'Authorized public IPv4 address')
      [ "${LABWC_MENU_INPUT_MODE:-choice}" = text ] || return 2
      printf '203.0.113.17\n' ;;
    *) return 2 ;;
  esac
}
run_network_action() { printf '%s\n' "$@"; }
'''
        for call, action in (('run_selected_nmap_action nmap-tls host', 'nmap-tls'),
                             ('run_specific_wan_scan', 'nmap-common-ports')):
            for approved in (False, True):
                with self.subTest(call=call, approved=approved):
                    result = shell(base + call, env={'AUTHORIZATION':
                        'I am authorized to scan this WAN host' if approved else 'Cancel'})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(),
                        [action, '203.0.113.17', 'authorized-wan-scan'] if approved else [])

    def test_ai_picker_does_not_inherit_user_command_bindings_or_loader_environment(self):
        name = 'labwc-ai-copilots'
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            recorder = directory / 'fzf-fixture'
            recorder.write_text('#!/usr/bin/python3 -I\nimport json,os,sys\n'
                                'print(json.dumps({"env":dict(os.environ), "argv":sys.argv[1:]}))\n')
            recorder.chmod(0o700)
            helper = function('fatal', name) + function('choose_fzf_input', name)
            helper = helper.replace('/usr/bin/fzf', str(recorder))
            result = shell(helper + 'choose_fzf_input Models 2', env={
                'FZF_DEFAULT_OPTS': '--bind=enter:execute(touch /not-run)',
                'FZF_DEFAULT_COMMAND': 'not-run', 'FZF_DEFAULT_OPTS_FILE': '/not-read',
                'PYTHONPATH': '/not-imported', 'TERM': 'xterm-256color'})
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertFalse(any(key.startswith('FZF_') for key in output['env']))
            self.assertNotIn('PYTHONPATH', output['env'])
            self.assertIn('--no-ansi', output['argv'])
            self.assertIn('--header-lines=2', output['argv'])
            self.assertEqual(output['env']['TERM'], 'xterm-256color')

    def test_digital_catalog_rejects_bad_later_row_and_duplicate_action_or_label(self):
        good = 'pdf\tpdf-info\tpdf\tInspect PDF\tDescription\n'
        candidates = (good, good + 'broken\n', good + good,
                      good + 'pdf\tother\tpdf\tInspect PDF\tDescription\n',
                      good + 'invalid\tother\tpdf\tOther\tDescription\n', '')
        helper = function('fatal', 'labwc-digital-assets') + function('load_menu_catalog', 'labwc-digital-assets')
        helper += 'runtime_root() { printf "%s\\n" "$FIXTURE_ROOT"; };\n'
        helper = helper.replace('labwc-digital-assets-action', 'action_fixture')
        helper += 'action_fixture() { cat "$FIXTURE_ROOT/input"; };\nload_menu_catalog; printf accepted'
        with tempfile.TemporaryDirectory() as temporary:
            for data in candidates:
                with self.subTest(data=data):
                    (Path(temporary)/'input').write_text(data)
                    result = shell(helper, env={'FIXTURE_ROOT': temporary})
                    self.assertEqual(result.returncode, 0 if data == good else 1, result.stderr)
                    self.assertEqual(result.stdout, 'accepted' if data == good else '')

    def test_power_profile_is_an_exact_closed_choice(self):
        source = render_theme_defaults(payload_read_text(BIN / 'labwc-power-settings'))
        case = source[source.index('case "$selection" in'):source.index('[ "$selected_profile"')]
        for value in ('performance', 'balanced', 'power-saver', 'balanced (current)',
                      'performance arbitrary', 'balanced; touch /not-run', 'power-saver-extra'):
            result = shell('selection=$1\n' + case + '\nprintf "%s" "$selected_profile"', args=(value,))
            valid = value in ('performance', 'balanced', 'power-saver', 'balanced (current)')
            self.assertEqual(result.returncode, 0 if valid else 1)
            if valid: self.assertEqual(result.stdout, value.removesuffix(' (current)'))


    def test_all_maintenance_and_recovery_actions_dispatch_validated_requests(self):
        source = render_theme_defaults(payload_read_text(BIN / 'labwc-maintenance-menu'))
        definitions, main = source.split('requested_category=${1:-}', 1)
        # Keep the real nested menu and action dispatch. Replace the preflight
        # and physical discovery/action endpoints; no root operation can run.
        definitions = definitions.split('command -v labwc-fuzzel >/dev/null', 1)[0]
        actions = {}
        for category, chooser, count in (('system', 'choose_system_action', 42),
                                         ('recovery', 'choose_recovery_action', 21)):
            block = function(chooser, 'labwc-maintenance-menu')
            entries = re.findall(r"^    '([^']+)'\)\n(.*?)^      ;;", block, re.M | re.S)
            labels = [(group, label) for group, body in entries
                      for label in re.findall(r"^        '([^']+)'", body, re.M)
                      if label != '\u2190 Back']
            self.assertEqual(len(labels), count)
            for group, label in labels:
                key = (category, group, label)
                actions[key] = None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            picker = root / 'picker'
            picker.write_text('#!/usr/bin/python3 -I\nimport json,os,sys\nfrom pathlib import Path\n'
                'path=Path(os.environ["FIXTURE_QUEUE"])\nqueue=json.loads(path.read_text())\n'
                'selection=queue.pop(0)\npath.write_text(json.dumps(queue))\n'
                'offered=sys.stdin.read().splitlines()\n'
                'assert selection in offered, (selection,offered)\nprint(selection)\n')
            picker.chmod(0o700)
            for category, group, label in actions:
                with self.subTest(category=category, action=label):
                    queue = [group, label]
                    if label == 'Rotate and Vacuum Journals by Time': queue += ['7 days']
                    if label == 'Rotate and Vacuum Journals by Size': queue += ['512 MiB']
                    confirmation = ('Continue with authorized recovery action' if category == 'recovery'
                                    else 'Continue with authorized system action')
                    # Record which branches require authorization from the real
                    # dispatcher, independently checked by the client's schema.
                    branch = re.search(r"^          '" + re.escape(label) + r"'\)\n(.*?)^            ;;",
                                       source, re.M | re.S).group(1)
                    if 'run_confirmed_' in branch: queue += [confirmation]
                    queue += ['\u2190 Back'] * 2
                    queue_path = root / 'queue.json'
                    queue_path.write_text(json.dumps(queue))
                    overrides = '\nchoose_lines() { shift; printf "%s\\n" "$@" | "$FIXTURE_PICKER"; }\n'
                    overrides += 'choose_service() { printf "example.service\\n"; }\n'
                    overrides += 'choose_nvme_controller() { printf "/dev/nvme0\\n"; }\n'
                    overrides += 'run_system_action() { printf "%s\\n" system "$@"; }\n'
                    overrides += 'run_recovery_action() { printf "%s\\n" recovery "$@"; }\n'
                    overrides += 'run_external_drive_manager() { printf "external-drives\\n"; }\n'
                    result = shell(definitions + overrides + 'requested_category=${1:-}' + main,
                                   env={'FIXTURE_QUEUE': str(queue_path), 'FIXTURE_PICKER': str(picker)},
                                   args=(category,))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(render_theme_defaults(payload_read_text(queue_path))), [])
                    request = result.stdout.splitlines()
                    self.assertTrue(request, label)
                    if label == 'Manage External Drives':
                        self.assertEqual(request, ['external-drives'])
                    else:
                        self.assertEqual(request[0], category)
                        client = 'labwc-' + category + '-action'
                        validation = function('fatal', client) + function('validate_request_shape', client)
                        validated = shell(validation + 'validate_request_shape "$@"', args=request[1:])
                        self.assertEqual(validated.returncode, 0, validated.stderr)
                        if 'run_confirmed_' in branch:
                            denied = shell(validation + 'validate_request_shape "$@"', args=request[1:-1])
                            self.assertNotEqual(denied.returncode, 0)

    def test_bluetooth_does_not_convert_device_picker_error_into_success(self):
        name = 'labwc-bluetooth'
        for caller, arguments in (('perform_device_action', ('connect', 'all', 'Prompt', 'Done', 'Done')),
                                  ('pair_device', ()), ('manage_device', ())):
            for status in (1, 2):
                with self.subTest(caller=caller, status=status):
                    fixture = function(caller, name)
                    fixture += '\nchoose_device() { return "$STATUS"; }\nscan_devices() { :; }\n'
                    result = shell(fixture + caller + ' "$@"', env={'STATUS': str(status)}, args=arguments)
                    self.assertEqual(result.returncode, 0 if status == 1 else status, result.stderr)

    def test_cancelled_network_address_does_not_fail_the_parent_menu(self):
        for caller in ('run_selected_nmap_action', 'run_specific_wan_scan'):
            base = function(caller, 'labwc-network-scan-menu')
            base += r"""
choose_lines() {
  case "$1" in
    'Nmap target scope') printf 'Authorized WAN IPv4 host\n' ;;
    'WAN scan authorization') printf 'I am authorized to scan this WAN host\n' ;;
    'Authorized public IPv4 address') return 0 ;;
    *) return 2 ;;
  esac
}
run_network_action() { printf 'UNEXPECTED ACTION\n'; }
"""
            result = shell(base + caller + ' nmap-tls host; printf returned')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'returned')

    def test_confirmation_condition_cannot_swallow_picker_failure(self):
        for name, fn, args in (
                ('labwc-firewall-menu', 'confirm_firewall_change', ('Prompt',)),
                ('labwc-network-control-menu', 'confirm_action', ('Prompt',)),
                ('labwc-adb-menu', 'confirm_action', ('Prompt',)),
                ('labwc-adb-menu', 'confirm_phrase', ('Prompt', 'CONFIRM'))):
            with self.subTest(script=name, function=fn):
                helper = function(fn, name)
                helper += '\nchoose_lines() { return 2; }\nchoose_text() { return 2; }\n'
                result = shell(helper + 'if ' + fn + ' "$@"; then printf ACTION; fi; printf cancelled', args=args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')

    def test_adb_device_selection_preserves_cancel_vs_failure_through_or_list(self):
        name = 'labwc-adb-menu'
        for fn in ('choose_device', 'choose_fastboot_device'):
            helper = function('menu_failure', name) + function(fn, name).replace('labwc-adb-action', 'action_fixture')
            helper += '\naction_fixture() { printf "serial device\\n"; }\n'
            helper += 'choose_menu_input() { cat >/dev/null; return "$PICKER_STATUS"; }\n'
            helper += 'selected=$(' + fn + ') || { menu_failure "$?"; printf cancelled; exit 0; }\n'
            for status in (0, 2):
                with self.subTest(function=fn, status=status):
                    result = shell(helper, env={'PICKER_STATUS': str(status)})
                    self.assertEqual(result.returncode, status)
                    self.assertEqual(result.stdout, 'cancelled' if status == 0 else '')

    def test_multi_file_picker_failure_cleans_its_private_lists_and_propagates(self):
        name = 'labwc-digital-assets'
        helper = function('choose_multiple_files', name)
        helper += '\nruntime_root() { printf "%s\\n" "$FIXTURE_ROOT"; }\n'
        helper += 'create_candidate_list() { printf "/fixture.pdf\\n" >"$FIXTURE_ROOT/candidates"; printf "%s/candidates\\n" "$FIXTURE_ROOT"; }\n'
        helper += 'choose_menu_input() { cat >/dev/null; return 2; }\nMAX_CANDIDATES=400\n'
        helper += 'value=$(choose_multiple_files pdf Prompt) || exit "$?"'
        with tempfile.TemporaryDirectory() as temporary:
            result = shell(helper, env={'FIXTURE_ROOT': temporary})
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_calendar_picker_errors_are_not_silently_cancelled(self):
        name = '../libexec/labwc-calendar'
        helper = function('menu_failure', name) + function('open_menu', name).replace('labwc-fuzzel', 'picker_fixture')
        helper += '\nrequire_command() { :; }\npicker_fixture() { cat >/dev/null; return "$PICKER_STATUS"; }\nopen_menu'
        for status in (1, 2):
            result = shell(helper, env={'PICKER_STATUS': str(status)})
            self.assertEqual(result.returncode, 0 if status == 1 else status)

    def test_hardware_menu_rejects_backend_failure_and_nonexact_output(self):
        # Execute the actual chooser without importing a second hardware module
        # tree into the shared unittest interpreter.
        import ast
        path = TARGET / 'usr/local/lib/hardware_tuning/client.py'
        chooser = next(node for node in ast.parse(render_theme_defaults(payload_read_text(path))).body
                       if isinstance(node, ast.FunctionDef) and node.name == 'choose')
        namespace = {'subprocess': subprocess, 'os': os, 'TuningError': ValueError}
        exec(compile(ast.Module(body=[chooser], type_ignores=[]), str(path), 'exec'), namespace)
        for code, output in ((0, 'Allowed\n'), (1, ''), (2, ''), (0, 'Allowed\n\n'), (0, ' Allowed\n')):
            with self.subTest(code=code, output=output), mock.patch.object(subprocess, 'run',
                    return_value=types.SimpleNamespace(returncode=code, stdout=output)):
                if code == 2:
                    with self.assertRaises(ValueError): namespace['choose'](['Allowed'], 'Prompt')
                else:
                    self.assertEqual(namespace['choose'](['Allowed'], 'Prompt'),
                                     'Allowed' if code == 0 and output == 'Allowed\n' else None)


class AppArmorIntegrationTests(unittest.TestCase):
    def test_all_named_transitions_resolve_to_managed_or_declared_vendor_profiles(self):
        files = [p for p in AA.rglob('*') if payload_source_is_file(p)]
        sources = '\n'.join(render_theme_defaults(payload_read_text(p)) for p in files)
        names = set(re.findall(r'^\s*profile\s+([^\s{]+)', sources, re.M))
        targets = set(re.findall(r'\b[rcw]*[pPcCiIuUxX]+\s+->\s+([^,\s]+)', sources))
        # Chromium-family attachments are owned by vendor packages and adapted
        # by security.sh; nested // transitions are relative to their parent.
        missing = {name for name in targets if name not in names and '//' not in name}
        self.assertEqual(missing, {'chromium', 'microsoft-edge-stable', 'mullvad-browser'})
        security = render_theme_defaults(payload_read_text(FORKY / 'scripts/late/security.sh'))
        for name in missing: self.assertIn(name, security)

    def test_required_managed_includes_exist_and_have_installer_staging_references(self):
        security = render_theme_defaults(payload_read_text(FORKY / 'scripts/late/security.sh'))
        hardware = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/hardware-tuning.sh'))
        expanded = hardware
        # These native local includes are staged from literal here-document
        # inventories, not hard-coded per-file calls. Expand only those two
        # explicitly invoked inventory functions, not every available file.
        for inventory in ('apparmor_managed_local_include_files', 'apparmor_support_local_include_files'):
            self.assertIn('for apparmor_local_include in $(' + inventory + '); do', security)
            match = re.search(r'^' + inventory + r"\(\) \{\n  cat <<'EOF'\n(.*?)\nEOF\n\}", security, re.M | re.S)
            self.assertIsNotNone(match, inventory)
            for name in match.group(1).splitlines():
                self.assertRegex(name, r'^[a-z0-9][a-z0-9._-]*$')
                expanded += security.replace('${apparmor_local_include}', name)
        for variable, values in (('hardware_bridge', ('desktop-parent', 'fuzzel-parent', 'management-parent')),
                                 ('hardware_vendor', ('intel', 'nvidia'))):
            self.assertIn('${' + variable + '}', hardware)
            for value in values:
                expanded += hardware.replace('${' + variable + '}', value)
        for path in AA.rglob('*'):
            if not payload_source_is_file(path): continue
            for optional, include in re.findall(r'^\s*#?include\s+(if exists\s+)?<([^>]+)>', render_theme_defaults(payload_read_text(path)), re.M):
                if not include.startswith(('abstractions/', 'local/')): continue
                # Check every project-owned include, regardless of its name.
                # Distribution-owned abstractions are checked by the native parser.
                if not payload_source_exists(AA / include):
                    if optional: continue
                    self.assertTrue((Path('/etc/apparmor.d') / include).is_file(), include)
                    continue
                with self.subTest(source=path.name, include=include):
                    destination = AA / include
                    if optional and not payload_source_exists(destination): continue
                    self.assertTrue(payload_source_is_file(destination), include)
                    self.assertIn(include, security + expanded)

    def test_fuzzel_cleanup_signal_has_both_confined_endpoints(self):
        sender = profile(AA / 'desktop-wrappers', 'labwc-fuzzel')
        recipient = profile(AA / 'desktop-utilities', 'desktop-launcher')
        self.assertIn('signal (send) set=(term) peer=desktop-launcher,', sender)
        self.assertIn('signal (receive) set=(term) peer=labwc-fuzzel,', recipient)
        self.assertIn('/usr/bin/fuzzel rPx,', sender)

    def test_ai_fzf_has_read_only_terminal_database_access(self):
        policy = profile(AA / 'desktop-wrappers', 'labwc-ai-copilots')
        for path in ('/etc/terminfo/{,**}', '/{,usr/}lib/terminfo/{,**}', '/usr/share/terminfo/{,**}'):
            self.assertIn(path + ' r,', policy)
        self.assertIn('/usr/bin/{find,fzf,id,sed,sort} rix,', policy)
        self.assertNotIn('flags=(unconfined', policy)

    @unittest.skipUnless(shutil.which('apparmor_parser') and payload_source_is_file(Path('/etc/apparmor.d/abstractions/base')),
                         'AppArmor parser/system abstractions unavailable; source contracts still tested')
    def test_every_managed_top_level_policy_compiles_offline(self):
        with tempfile.TemporaryDirectory(prefix='menu-apparmor-') as temporary:
            base = Path(temporary) / 'apparmor.d'
            shutil.copytree('/etc/apparmor.d', base, symlinks=True)
            shutil.copytree(AA, base, dirs_exist_ok=True, symlinks=True)
            render_theme_tree(base)
            for path in sorted(AA.iterdir()):
                if not payload_source_is_file(path): continue
                with self.subTest(policy=path.name):
                    result = subprocess.run(payload_installed_argv(['apparmor_parser', '-Q', '-K', '-T',
                        '--base', str(base), '-I', str(base), str(base / path.name.removesuffix('.tmpl'))]),
                        text=True, capture_output=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr)


class FuzzelLifecycleTests(unittest.TestCase):
    def test_term_stops_and_reaps_child_and_removes_runtime_pid(self):
        # Native Wayland display is unavailable: run the real wrapper with a
        # child executable that waits, never performs actions or starts a GUI.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bin').mkdir()
            child = root / 'bin/fuzzel'
            child.write_text('#!/usr/bin/python3 -I\nimport os,signal,time\n'
                'with open(os.environ["FIXTURE_PID"], "w") as f: f.write(str(os.getpid()))\n'
                'signal.signal(signal.SIGTERM, lambda *_: exit(0))\nwhile True: time.sleep(.02)\n')
            child.chmod(0o700)
            (root / 'config/fuzzel').mkdir(parents=True)
            for name in ('fuzzel.ini', 'menu.ini', 'launcher.ini'):
                (root / 'config/fuzzel' / name).write_text('[main]\n')
            environment = {**os.environ, 'PATH': str(root/'bin') + ':/usr/bin:/bin',
                'HOME': str(root), 'XDG_CONFIG_HOME': str(root/'config'), 'XDG_RUNTIME_DIR': str(root),
                'LABWC_FUZZEL_MANAGED_ICONS': '0', 'LABWC_MENU_BACKEND': 'fuzzel',
                **geometry_environment(),
                'FIXTURE_PID': str(root/'child.pid')}
            process = subprocess.Popen(payload_installed_argv(['/bin/sh', str(wrapper_script(root, child)), 'menu', '--dmenu']),
                env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not payload_source_exists(root/'child.pid') and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                if not payload_source_exists(root/'child.pid'):
                    output, errors = process.communicate(timeout=2)
                    self.fail('fixture child did not start: ' + errors.decode())
                child_pid = int(render_theme_defaults(payload_read_text(root/'child.pid')))
                process.send_signal(signal.SIGTERM)
                output, errors = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143, errors.decode())
                self.assertFalse(payload_source_exists(root/'labwc-fuzzel.pid'))
                with self.assertRaises(ProcessLookupError): os.kill(child_pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=2)
                if payload_source_exists(root/'child.pid'):
                    try: os.kill(int(render_theme_defaults(payload_read_text(root/'child.pid'))), signal.SIGTERM)
                    except ProcessLookupError: pass


if __name__ == '__main__':
    unittest.main()
