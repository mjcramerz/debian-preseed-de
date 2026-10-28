"""Unexecuted dismissal/back regressions; every picker endpoint is mocked.

Permanent repository policy prohibits running this file. Source inspection and
AST parsing do not establish native Fuzzel, Wayland or AppArmor acceptance.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import ast
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import types
import unicodedata
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
BIN = TARGET / 'usr/local/bin'
PACKAGES = TARGET / 'usr/local/lib/python3.14/dist-packages'


def functions(path, names, namespace):
    """Select function ASTs as data; do not import an entrypoint or its modules."""
    tree = ast.parse(path.read_text(), filename=str(path))
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in body} != set(names):
        raise ValueError('missing fixture function')
    selected = ast.Module(body=body, type_ignores=[])
    exec(compile(selected, str(path), 'exec'), namespace)
    return types.SimpleNamespace(**namespace)


class PickerAdapters(unittest.TestCase):
    def test_dismissal_is_never_a_selected_row_or_a_back_result(self):
        cases = (
            (BIN/'labwc-main-menu.tmpl', 'choose', ({'Allowed': None}, 'Menu')),
            (BIN/'labwc-computer-management', 'choose', (['Allowed'], 'Menu')),
            (BIN/'labwc-network-sharing', 'choose', (['Allowed'], 'Menu')),
            (BIN/'labwc-podman-menu', 'menu', ('Menu', ['Allowed'])),
            (BIN/'labwc-podman-menu', 'entry', ('Menu',)),
            (BIN/'labwc-remote-desktop.tmpl', 'run_fuzzel', ('Menu', ['Allowed'])),
            (TARGET/'usr/local/lib/hardware_tuning/client.py', 'choose', (['Allowed'], 'Menu')),
            (PACKAGES/'labwc_appearance/cli.py', 'choose', (['Allowed'], 'Menu')),
        )
        for path, name, arguments in cases:
            for status in (1, 2, 3):
                with self.subTest(path=path.name, function=name, status=status):
                    run = mock.Mock(return_value=types.SimpleNamespace(
                        returncode=status, stdout='Allowed\n'))
                    def fail(message):
                        raise RuntimeError(message)
                    namespace = {
                        'subprocess': types.SimpleNamespace(run=run, PIPE=-1),
                        'os': types.SimpleNamespace(environ={}),
                        'shutil': types.SimpleNamespace(which=lambda _: '/fixture/picker'),
                        'environment': lambda **_: {}, 'clean': lambda value, *_: value,
                        'fail': fail, 'TuningError': RuntimeError,
                        'PICKER': '/fixture/picker', 'FUZZEL': '/fixture/picker',
                        'MAX_LABEL': 4096, 'MAX_APPS': 100, 'MAX_MENU_BYTES': 1048576,
                        'MENU_ICONS': {}, 'BACK': 'Back', 'DEFAULT_ICON': 'fixture-icon',
                        'safe_icon': lambda _: 'fixture-icon',
                        'unicodedata': unicodedata,
                    }
                    adapter = functions(path, [name], namespace)
                    if status == 1:
                        self.assertIsNone(getattr(adapter, name)(*arguments))
                    elif status == 3:
                        with self.assertRaises(SystemExit) as raised:
                            getattr(adapter, name)(*arguments)
                        self.assertEqual(raised.exception.code, 3)
                    else:
                        with self.assertRaises(RuntimeError):
                            getattr(adapter, name)(*arguments)
                    self.assertEqual(run.call_count, 1)

    def test_management_child_dismissal_does_not_reopen_any_parent(self):
        run = mock.Mock(return_value=types.SimpleNamespace(returncode=3))
        choose = mock.Mock(side_effect=['Devices & Desktop', 'Desktop Appearance'])
        namespace = {
            'subprocess': types.SimpleNamespace(run=run, DEVNULL=-3),
            'os': types.SimpleNamespace(environ={}),
            'Path': lambda value: types.SimpleNamespace(
                name=PurePosixPath(value).name, is_file=lambda: False),
            'LOG': '/fixture/logger', 'choose': choose,
            'MENUS': {'Devices & Desktop': {'Desktop Appearance': ('labwc-desktop-appearance',)}},
        }
        menu = functions(BIN/'labwc-computer-management', ['run_action', 'run_menu'], namespace)
        with self.assertRaises(SystemExit) as raised:
            menu.run_menu()
        self.assertEqual(raised.exception.code, 3)
        self.assertEqual(choose.call_count, 2)
        self.assertEqual(run.call_count, 1)

    def test_main_menu_preserves_child_dismissal_but_reports_real_failure(self):
        for status in (3, 2):
            run = mock.Mock(return_value=types.SimpleNamespace(returncode=status))
            menu = functions(BIN/'labwc-main-menu.tmpl', ['run_action'], {
                'subprocess': types.SimpleNamespace(run=run, CalledProcessError=subprocess.CalledProcessError)})
            if status == 3:
                with self.assertRaises(SystemExit) as raised:
                    menu.run_action(('/fixture/menu',))
                self.assertEqual(raised.exception.code, 3)
            else:
                with self.assertRaises(subprocess.CalledProcessError):
                    menu.run_action(('/fixture/menu',))

    def test_component_confirmation_returns_to_profile_list_before_parent(self):
        choose = mock.Mock(side_effect=['Fuzzel', 'Midnight', 'Back', 'Back'])
        perform = mock.Mock()  # Models Back from the confirmation picker.
        menu = functions(PACKAGES/'labwc_appearance/cli.py', ['main'], {
            'COMPONENTS': {'fuzzel': 'Fuzzel'}, 'LABELS': {'midnight-slate': 'Midnight'},
            'choose': choose, 'perform': perform})
        self.assertEqual(menu.main([]), 0)
        perform.assert_called_once_with(['apply', 'fuzzel', 'midnight-slate'])
        self.assertEqual([call.args[1] for call in choose.call_args_list],
                         ['Desktop Appearance', 'Fuzzel', 'Fuzzel', 'Desktop Appearance'])


class ShellPropagation(unittest.TestCase):
    def test_empty_digital_assets_picker_preserves_failure_and_dismissal(self):
        source = (BIN/'labwc-digital-assets').read_text()
        self.assertTrue(source.startswith('#!/usr/bin/python3 -IB'))
        self.assertIn('def choose_file', source)
        self.assertIn('path.unlink(missing_ok=True)', source)
        self.assertIn('if not candidates:', source)

    def test_maintenance_preserves_nested_menu_dismissal(self):
        source = (BIN/'labwc-maintenance-menu.tmpl').read_text()
        self.assertTrue(source.startswith('#!/usr/bin/python3 -IB'))
        self.assertIn('propagate_close=True', source)
        self.assertIn('raise SystemExit(3)', source)
        self.assertIn('def call_helper', source)
