"""Unexecuted static fixtures for the Desktop Appearance picker contract.

The repository forbids running these fixtures on the host. They inspect source
text only and never start Fuzzel, Mako, a service manager, or a desktop bus.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import ast
from pathlib import Path
import unittest


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


if __name__ == '__main__':
    raise SystemExit(unittest.main())
