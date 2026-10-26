"""Unexecuted static fixtures for icon and pointer theme integration.

No appearance module, gsettings backend, polkit helper, icon cache utility,
desktop session, or host file is executed in this repository checkout.
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


class AppearanceAssetFixtures(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_menu_has_themes_icon_themes_and_pointer_themes(self):
        cli = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/cli.py').read_text(encoding='utf-8')
        catalog = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/catalog.py').read_text(encoding='utf-8')
        self.assertIn("'Icon Themes'", cli)
        self.assertIn("'Pointer Themes'", cli)
        self.assertIn("'Reset Mouse Theme'", cli)
        self.assertNotIn("'Reset Pointer Theme'", cli)
        self.assertIn("'GtkGreet Themes'", catalog)
        self.assertNotIn(' Profiles', catalog)

    def test_catalogs_have_twenty_collections_and_transactional_cache_path(self):
        source = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/icon_catalog.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        collections = [node for node in ast.walk(tree)
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id in ('ICON_COLLECTIONS', 'POINTER_COLLECTIONS')
                               for target in node.targets)]
        self.assertEqual(len(collections), 2)
        engine = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/engine.py').read_text(encoding='utf-8')
        greeter = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/greeter.py').read_text(encoding='utf-8')
        self.assertIn("privileged('cache-icons'", engine)
        self.assertIn("gtk-update-icon-cache", greeter)
        self.assertIn("'icon_theme'", engine)
        self.assertIn("'pointer_theme'", engine)


if __name__ == '__main__':
    raise SystemExit(unittest.main())
