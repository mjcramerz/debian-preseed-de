"""Pure Help behavior regressions for a later isolated test runner.

This module only exercises bounded catalog, navigation, search, persistence,
and link helpers. It does not launch GTK, services, subprocesses, or
host-management commands. Coding agents keep it unexecuted under the
repository's static-only validation boundary.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "hooks/target/usr/local/lib/python3.14/dist-packages/labwc_help"


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, PACKAGE_ROOT / f"{name.rsplit('.', 1)[-1]}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PACKAGE = types.ModuleType("labwc_help")
PACKAGE.__path__ = [str(PACKAGE_ROOT)]
sys.modules.setdefault("labwc_help", PACKAGE)
catalog = load_module("labwc_help.catalog")
navigation = load_module("labwc_help.navigation")
search = load_module("labwc_help.search")
state = load_module("labwc_help.state")


class HelpPureBehavior(unittest.TestCase):
    def test_navigation_history_is_bounded_and_preserves_position(self):
        history = navigation.History()
        for index in range(140):
            history.visit(f"desktop.topic-{index}", float(index))
        self.assertEqual(len(history.entries), 100)
        self.assertEqual(history.entries[-1][0], "desktop.topic-139")
        self.assertIsNone(history.move(1, 0))
        previous = history.move(-1, 12)
        self.assertEqual(previous[0], "desktop.topic-138")

    def test_search_ranks_title_and_requires_all_query_terms(self):
        articles = {
            "desktop.labwc": types.SimpleNamespace(
                id="desktop.labwc", title="Labwc desktop basics", summary="Compositor guide",
                keywords=("wayland", "compositor"), content="Open the Labwc configuration.", order=1,
                error="",
            ),
            "desktop.waybar": types.SimpleNamespace(
                id="desktop.waybar", title="Waybar", summary="Panel guide",
                keywords=("panel",), content="Labwc panel modules.", order=2, error="",
            ),
        }
        index = search.SearchIndex(types.SimpleNamespace(articles=articles))
        self.assertEqual(index.search("labwc compositor")[0].id, "desktop.labwc")
        self.assertEqual(index.search("labwc missing"), [])

    def test_catalog_rejects_unsafe_links_and_duplicate_json_fields(self):
        parser = catalog.Catalog(Path("/unused"), owner=0)
        with self.assertRaises(ValueError):
            parser._blocks({"version": 1, "blocks": [
                {"type": "paragraph", "text": "[run](javascript:alert(1))"},
            ]})
        with self.assertRaises(ValueError):
            catalog.decode(b'{"version":1,"version":2}')
        self.assertEqual(catalog.link_target("help:desktop.labwc", {"desktop.labwc"}), "topic")
        self.assertEqual(catalog.link_target("https://example.org/guide", set()), "external")
        with self.assertRaises(ValueError):
            catalog.link_target("http://example.org/guide", set())

    def test_state_sanitizes_deleted_topics_and_publishes_atomically(self):
        with TemporaryDirectory() as temporary:
            home = Path(temporary)
            with mock.patch.object(state.Path, "home", return_value=home):
                store = state.StateStore({"desktop.labwc"}, directory=home / "state")
                store.data["bookmarks"] = ["desktop.labwc", "deleted.topic"]
                store.data["recents"] = ["deleted.topic", "desktop.labwc"]
                self.assertTrue(store.save())
                saved = json.loads((home / "state" / "state.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["bookmarks"], ["desktop.labwc"])
                self.assertEqual(saved["recents"], ["desktop.labwc"])
                self.assertEqual(list((home / "state").glob(".state-*")), [])

    def test_copy_selection_contract_uses_selection_bounds(self):
        # No GTK initialization: the fake widgets model the different Python
        # return signatures (Label keeps the boolean; TextBuffer strips it).
        class Label:
            def __init__(self, selection):
                self.selection = selection

            def get_selection_bounds(self):
                return self.selection

            def get_text(self):
                return "selected article"

        class TextView:
            def __init__(self, bounds):
                self.buffer = mock.Mock()
                self.buffer.get_selection_bounds.return_value = bounds
                self.buffer.get_text.return_value = "selected code"

            def get_buffer(self):
                return self.buffer

        repository = types.ModuleType("gi.repository")
        repository.Gtk = types.SimpleNamespace(Box=object, Label=Label, TextView=TextView)
        gi = types.ModuleType("gi")
        gi.__path__ = []
        gi.repository = repository
        with mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
            renderer = load_module("labwc_help.render")
        reader = renderer.Reader.__new__(renderer.Reader)
        reader.copy = mock.Mock()
        reader.text_widgets = [Label((True, 0, 8))]
        reader.copy_selection()
        reader.copy.assert_called_once_with("selected")

        reader.copy.reset_mock()
        view = TextView(("start", "end"))
        reader.text_widgets = [Label((False, 0, 0)), TextView(()), view]
        reader.copy_selection()
        view.buffer.get_text.assert_called_once_with("start", "end", True)
        reader.copy.assert_called_once_with("selected code")


if __name__ == "__main__":
    unittest.main()
