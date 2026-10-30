"""Unexecuted static fixtures for the Desktop Appearance picker contract.

The repository forbids running these fixtures on the host. They inspect source
and define bounded logic cases with fake widgets; they never import GTK, start
Fuzzel, Mako, a service manager, or a desktop bus.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import ast
from collections import defaultdict
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock


class AppearancePickerContractFixtures(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def _source(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding='utf-8')

    def test_picker_uses_native_icon_metadata_with_newline_records(self):
        source = self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_appearance/cli.py'
        )
        tree = ast.parse(source)
        self.assertIn("'Mako Themes': 'preferences-desktop-notification'", source)
        self.assertIn("'Desktop Appearance': 'preferences-desktop-display'", source)
        self.assertIn("'LABWC_FUZZEL_MANAGED_ICONS': '0'", source)
        self.assertIn("'--dmenu'", source)
        self.assertNotIn("'--dmenu0'", source)
        self.assertTrue(any(isinstance(node, ast.FunctionDef) and node.name == 'choose'
                           for node in tree.body))

    def test_mako_is_a_captured_rendered_and_refreshable_component(self):
        catalog = self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_appearance/catalog.py'
        )
        native = self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_appearance/native.py'
        )
        engine = self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_appearance/engine.py'
        )
        service = self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_appearance/service.py'
        )
        apparmor = self._source('hooks/target/etc/apparmor.d/labwc-appearance')
        self.assertIn("'mako': 'Mako Themes'", catalog)
        self.assertIn("'mako': ('mako/config',)", native)
        self.assertIn("base == 'mako/config'", native)
        self.assertIn('return baseline if baseline is not None else text', native)
        self.assertIn("'mako'", engine)
        self.assertIn("'mako.service'", service)
        self.assertIn("'reload', 'mako.service'", service)
        self.assertIn('.config/mako/config', apparmor)
        self.assertIn('kitty,mako,gtk-3.0', apparmor)

    def test_editor_reads_installed_values_before_rendering_color_updates(self):
        fields = self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_appearance/fields.py'
        )
        editor = self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_appearance/editor.py'
        )
        self.assertIn('def current_values(registry: dict | None = None)', fields)
        self.assertIn('user_tree.read(path, missing=True)', fields)
        self.assertIn('greeter_tree.read(path[len(\'/etc/greetd/\'):], missing=True)', fields)
        self.assertIn('fields.current_values(registry)', editor)
        self.assertIn('warnings = fields.apply(selected)', editor)
        self.assertIn('Choose a color; the text value remains editable', editor)

    def test_proxy_accepts_only_terminal_dot_prefix_wildcards(self):
        source = self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_managed_app/dbus_proxy.py'
        )
        self.assertIn(r'(?:\.\*)?\Z', source)
        self.assertIn('socket_stat.st_nlink != 1', source)
        self.assertIn('temp_root_stat.st_uid != os.getuid()', source)
        self.assertIn('org.freedesktop.portal.*', self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_managed_app/profiles.py.tmpl'
        ))
        self.assertIn('org.mpris.MediaPlayer2.vivaldi.*', self._source(
            'hooks/target/usr/local/lib/python3.14/dist-packages/'
            'labwc_managed_app/profiles.py.tmpl'
        ))


class AppearanceDraftFixtures(unittest.TestCase):
    """Unexecuted draft/commit cases extracted without importing the editor."""

    def setUp(self):
        environment = mock.patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        commands = mock.patch.object(subprocess, 'run', side_effect=AssertionError('external command'))
        commands.start()
        self.addCleanup(commands.stop)

    def window(self):
        path = (Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/lib/python3.14/'
                'dist-packages/labwc_appearance/editor.py')
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        window = next(node for node in main.body if isinstance(node, ast.ClassDef)
                      and node.name == 'AppearanceWindow')
        methods = [node for node in window.body if isinstance(node, ast.FunctionDef)
                   and node.name in {'_remember_rows', '_component_changed', '_save', '_show_error'}]
        fixture = ast.ClassDef(name='DraftWindow', bases=[], keywords=[], body=methods,
                               decorator_list=[], type_params=[])
        ast.fix_missing_locations(fixture)
        fields = SimpleNamespace(validate_value=mock.Mock(side_effect=lambda field, value: value),
                                 apply=mock.Mock(return_value=[]), current_values=mock.Mock())
        namespace = {'fields': fields, 'subprocess': subprocess, 'defaultdict': defaultdict,
                     'WAYBAR_CATEGORY_ORDER': ()}
        exec(compile(ast.Module(body=[fixture], type_ignores=[]), str(path), 'exec'), namespace)
        result = namespace['DraftWindow']()
        result._initial = {'A': '#111111', 'B': '#222222', 'C': '#333333'}
        result._draft = dict(result._initial)
        result._field_by_key = {key: {'key': key} for key in result._initial}
        result._registry = {'components': [{'id': 'FOOT'}], 'fields': []}
        result._rows = []
        result._status = mock.Mock()
        fields.current_values.return_value = dict(result._initial)
        return result, fields

    @staticmethod
    def row(key, value):
        return {'field': {'key': key}, 'entry': SimpleNamespace(get_text=lambda: value)}

    def test_switch_remembers_values_before_removing_current_widgets(self):
        window, _fields = self.window()
        window._rows = [self.row('A', '#aaaaaa')]
        window._selector = SimpleNamespace(get_selected=lambda: 0)
        window._target_label = mock.Mock()
        child = object()
        window._content = SimpleNamespace(get_first_child=mock.Mock(side_effect=[child, None]))

        def remove(value):
            self.assertIs(value, child)
            self.assertEqual(window._draft['A'], '#aaaaaa')

        window._content.remove = remove
        window._filter_rows = mock.Mock()
        window._component_changed()
        self.assertEqual(window._draft['A'], '#aaaaaa')

    def test_save_includes_hidden_drafts_and_excludes_unchanged_fields(self):
        window, fields = self.window()
        window._rows = [self.row('A', '#aaaaaa')]
        window._remember_rows()
        window._rows = [self.row('B', '#bbbbbb')]
        window._component_changed = mock.Mock()
        fields.current_values.return_value = {'A': '#aaaaaa', 'B': '#bbbbbb', 'C': '#333333'}
        window._save()
        fields.apply.assert_called_once_with({'A': '#aaaaaa', 'B': '#bbbbbb'})
        self.assertEqual(window._draft, fields.current_values.return_value)
        window._component_changed.assert_called_once_with(remember=False)

    def test_invalid_hidden_draft_prevents_every_write_and_retains_edits(self):
        window, fields = self.window()
        window._draft['A'] = 'invalid-color'
        fields.validate_value.side_effect = ValueError('invalid fixture color')
        window._save()
        fields.apply.assert_not_called()
        self.assertEqual(window._draft['A'], 'invalid-color')
        self.assertIn('was not saved', window._status.set_text.call_args.args[0])

    def test_commit_failure_retains_draft_and_does_not_claim_no_mutation(self):
        window, fields = self.window()
        window._draft['A'] = '#aaaaaa'
        fields.apply.side_effect = RuntimeError('injected commit failure')
        window._save()
        self.assertEqual(window._draft['A'], '#aaaaaa')
        fields.apply.assert_called_once()
        fields.current_values.assert_not_called()
        self.assertIn('did not finish', window._status.set_text.call_args.args[0])

    def test_reread_failure_reports_saved_state_without_retrying_commit(self):
        window, fields = self.window()
        window._draft['A'] = '#aaaaaa'
        fields.current_values.side_effect = OSError('injected read failure')
        window._save()
        fields.apply.assert_called_once()
        self.assertIn('saved, but current colors could not be reread',
                      window._status.set_text.call_args.args[0])

    def test_unchanged_values_do_not_write_refresh_or_authenticate(self):
        window, fields = self.window()
        window._save()
        fields.apply.assert_not_called()
        fields.current_values.assert_not_called()


if __name__ == '__main__':
    raise SystemExit(unittest.main())
