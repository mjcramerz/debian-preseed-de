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

    def test_captured_defaults_schema_matches_runtime_and_installer_consumers(self):
        source = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/defaults.py').read_text(encoding='utf-8')
        runtime = ast.parse(source)
        captured_schemas = [ast.literal_eval(value)
                            for node in ast.walk(runtime) if isinstance(node, ast.Dict)
                            for key, value in zip(node.keys, node.values)
                            if isinstance(key, ast.Constant) and key.value == 'schema']
        self.assertEqual(len(captured_schemas), 1)

        appearance = (self.root / 'scripts/desktop/components/appearance.sh').read_text(encoding='utf-8')
        inspection = appearance.split("/usr/bin/python3 -I -S -B -c '\n", 1)[1].rsplit("\n'\n", 1)[0]
        installer = ast.parse(inspection)

        def schemas(tree, variable, operator):
            return [ast.literal_eval(node.comparators[0])
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Compare) and len(node.ops) == 1
                    and isinstance(node.ops[0], operator)
                    and isinstance(node.left, ast.Call)
                    and isinstance(node.left.func, ast.Attribute)
                    and isinstance(node.left.func.value, ast.Name)
                    and node.left.func.value.id == variable
                    and node.left.func.attr == 'get' and len(node.left.args) == 1
                    and isinstance(node.left.args[0], ast.Constant)
                    and node.left.args[0].value == 'schema']

        self.assertEqual(schemas(runtime, 'value', ast.NotEq), captured_schemas)
        self.assertEqual(schemas(installer, 'defaults', ast.Eq), captured_schemas)


if __name__ == '__main__':
    raise SystemExit(unittest.main())
