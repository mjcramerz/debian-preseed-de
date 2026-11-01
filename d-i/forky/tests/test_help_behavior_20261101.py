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
    def test_invalid_decorative_icon_is_removed_before_gtk_consumption(self):
        item = {'title': 'Guide', 'icon': ['invalid'], 'order': 0}
        catalog.Catalog._metadata(item)
        self.assertEqual(item['icon'], '')

    def test_removed_history_entries_preserve_the_selected_guide(self):
        value = state.sanitize({
            'version': 1,
            'history': [['deleted.topic', 1], ['desktop.labwc', 2], ['desktop.waybar', 3]],
            'history_position': 1,
        }, {'desktop.labwc', 'desktop.waybar'})
        self.assertEqual(value['history'], [['desktop.labwc', 2], ['desktop.waybar', 3]])
        self.assertEqual(value['history_position'], 0)

    def test_cleanup_failure_retains_private_evidence_and_closes_mock_descriptors(self):
        # All syscalls are mocked. These numbers never name real descriptors,
        # and this fixture never opens a directory, HOME or host state file.
        store = state.StateStore.__new__(state.StateStore)
        store.valid = {'desktop.labwc'}
        store.directory = Path('/owned-fixture/state')
        store.data = state.sanitize({'version': 1}, store.valid)
        store.error = ''
        stream = mock.MagicMock()
        stream.__enter__.return_value.fileno.return_value = 12
        with mock.patch.object(store, '_parents'), \
                mock.patch.object(store, '_private'), \
                mock.patch.object(state.secrets, 'token_hex', return_value='a' * 24), \
                mock.patch.object(state.os, 'open', side_effect=[10, 11, 12]), \
                mock.patch.object(state.os, 'fstat', return_value=object()), \
                mock.patch.object(state.os, 'stat', side_effect=FileNotFoundError), \
                mock.patch.object(state.os, 'fdopen', return_value=stream), \
                mock.patch.object(state.os, 'fsync'), \
                mock.patch.object(state.fcntl, 'flock'), \
                mock.patch.object(state.os, 'replace', side_effect=OSError), \
                mock.patch.object(state.os, 'unlink', side_effect=OSError) as unlink, \
                mock.patch.object(state.os, 'close') as close:
            self.assertFalse(store.save())
        unlink.assert_called_once_with('.state-' + 'a' * 24, dir_fd=10)
        self.assertEqual(close.call_args_list, [mock.call(11), mock.call(10)])
        self.assertIn('Private recovery evidence was retained', store.error)

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
            # Construct only the owned fixture directory; production parent
            # checks must not walk the actual host's HOME or ancestors here.
            with mock.patch.object(state.Path, "home", return_value=home), \
                    mock.patch.object(state.StateStore, '_parents',
                                      side_effect=lambda: (home / 'state').mkdir(mode=0o700, exist_ok=True)):
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
