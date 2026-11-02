"""Static regression contracts for the offline Labwc Help application.

The repository's static-only policy keeps this module unexecuted by coding
agents. It is intentionally data-oriented so a later isolated test runner can
exercise catalog, navigation, search, persistence, and deep-link fixtures
without contacting a host service or importing installed code here.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ElementTree


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "hooks/target"
HELP_ROOT = TARGET / "usr/local/share/labwc-help"
HELP_PACKAGE = TARGET / "usr/local/lib/python3.14/dist-packages/labwc_help"
CATALOG_TEMPLATE = HELP_ROOT / "catalog.json.tmpl"


class HelpStaticContracts(unittest.TestCase):
    def test_catalog_categories_topics_and_assets_are_closed(self):
        catalog = json.loads(CATALOG_TEMPLATE.read_text(encoding="utf-8"))
        categories = {item["id"] for item in catalog["categories"]}
        topics = {item["id"] for item in catalog["articles"]}
        self.assertEqual([item['title'] for item in catalog['categories']], [
            'Getting Started', 'Desktop Environment', 'Displays & Hardware',
            'Networking & Sharing', 'Security & Privacy', 'Storage & Recovery',
            'Applications & Development', 'System Maintenance',
        ])
        self.assertEqual(len(categories), 8)
        self.assertGreaterEqual(len(topics), 42)
        self.assertEqual({item["category"] for item in catalog["articles"]}, categories)
        self.assertTrue(set(catalog["featured"]) <= topics)
        for article in catalog["articles"]:
            self.assertEqual(len(article['keywords']), len(set(article['keywords'])))
            self.assertTrue(set(article["related"]) <= topics)
            self.assertTrue((HELP_ROOT / article["file"]).is_file())
            self.assertEqual(json.loads((HELP_ROOT / article["file"]).read_text(encoding="utf-8"))["version"], 1)
        self.assertIn('start.help', topics)

    def test_malicious_content_contracts_are_source_enforced(self):
        catalog = (HELP_PACKAGE / "catalog.py").read_text(encoding="utf-8")
        renderer = (HELP_PACKAGE / "render.py").read_text(encoding="utf-8")
        catalog_data = CATALOG_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("O_NOFOLLOW", catalog)
        self.assertIn("MAX_ARTICLE", catalog)
        self.assertIn("Unsupported or unresolved documentation link", catalog)
        self.assertIn("escape(source)", renderer)
        self.assertNotIn("eval(", catalog + renderer)
        self.assertNotIn("os.system(", catalog + renderer)
        self.assertNotIn("symbolic", catalog_data)

    def test_help_icons_are_installation_rendered_theme_values(self):
        window = (HELP_PACKAGE / "window.py").read_text(encoding="utf-8")
        render = (HELP_PACKAGE / "render.py").read_text(encoding="utf-8")
        theme = (HELP_PACKAGE / "theme.py").read_text(encoding="utf-8")
        theme_template = (HELP_ROOT / "theme.json.tmpl").read_text(encoding="utf-8")
        catalog_template = CATALOG_TEMPLATE.read_text(encoding="utf-8")
        desktop_template = (TARGET / "usr/local/share/applications/labwc-help.desktop.tmpl").read_text(encoding="utf-8")
        for source in (window, render, theme):
            self.assertNotRegex(source, r"(?:help-browser|go-previous|go-next|go-home|open-menu|edit-copy|dialog-error|starred|non-starred|system-search)")
        self.assertNotIn("application_icon='", window)
        self.assertIn("__THEME_FUZZEL_MENU_ACTION_HELP_ICON_NAME__", theme_template)
        self.assertIn("__THEME_FUZZEL_MENU_ACTION_HELP_ICON_NAME__", desktop_template)
        self.assertIn("__THEME_LABWC_HELP_LIST_MARKER__", theme_template)
        self.assertIn("StateWriter", (HELP_PACKAGE / "state.py").read_text(encoding="utf-8"))
        self.assertNotIn("diagnostic", window.lower())
        self.assertNotIn("systemctl", window)
        self.assertNotIn("findmnt", window)
        self.assertNotIn("dpkg-query", window)
        self.assertRegex(catalog_template, r'__THEME_LABWC_HELP_CATEGORY_[A-Z_]+_ICON_NAME__')
        self.assertIn("catalog.json.tmpl", (ROOT / "scripts/desktop/components/target-assets.sh").read_text(encoding="utf-8"))
        self.assertIn("theme.json.tmpl", (ROOT / "scripts/desktop/components/target-assets.sh").read_text(encoding="utf-8"))
        self.assertIn("theme.json", (TARGET / "etc/apparmor.d/desktop-wrappers.tmpl").read_text(encoding="utf-8"))

    def test_navigation_search_and_atomic_state_modules_parse(self):
        for name in ("navigation.py", "search.py", "state.py", "theme.py", "window.py", "app.py"):
            ast.parse((HELP_PACKAGE / name).read_text(encoding="utf-8"), filename=name)
        state = (HELP_PACKAGE / "state.py").read_text(encoding="utf-8")
        self.assertIn("os.replace", state)
        self.assertIn("fcntl.flock", state)
        self.assertIn("XDG_STATE_HOME", state)
        self.assertFalse((HELP_PACKAGE / "system.py").exists())

    def test_deep_link_and_transient_launcher_contract(self):
        app = (HELP_PACKAGE / "app.py").read_text(encoding="utf-8")
        public = (TARGET / "usr/local/bin/labwc-help").read_text(encoding="utf-8")
        profile = (TARGET / "usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl").read_text(encoding="utf-8")
        self.assertIn("Gio.ApplicationFlags.HANDLES_COMMAND_LINE", app)
        self.assertIn("--topic CATEGORY.TOPIC", app)
        self.assertIn("os.execv('/usr/local/bin/labwc-app'", public)
        self.assertRegex(profile, r'"help"\s*:\s*\{')
        self.assertIn('"exec": "/usr/local/libexec/labwc-help-gtk"', profile)

    def test_waybar_files_help_entry_uses_themed_icon_and_action(self):
        xml = ElementTree.parse(TARGET / "etc/skel-desktop/.config/waybar/gtk/system-menu.xml.tmpl")
        help_item = next(item for item in xml.iter("object") if item.get("id") == "help_help")
        labels = [node.text for node in help_item.iter("property") if node.get("name") == "label"]
        icons = [node.text for node in help_item.iter("property") if node.get("name") == "icon-name"]
        self.assertIn("Help", labels)
        self.assertEqual(icons, ["__THEME_FUZZEL_MENU_ACTION_HELP_ICON_NAME__"])
        module = (TARGET / "etc/skel-desktop/.config/waybar/modules/system.tmpl").read_text(encoding="utf-8")
        self.assertIn('"help_help": "/usr/local/libexec/labwc-waybar-run -- /usr/local/bin/labwc-system-menu-action help_help"', module)
        dispatcher = (TARGET / "usr/local/bin/labwc-system-menu-action").read_text(encoding="utf-8")
        self.assertIn("'help_help': (HELP, '--topic', 'desktop.labwc')", dispatcher)
        waybar_run = (TARGET / "usr/local/libexec/labwc-waybar-run").read_text(encoding="utf-8")
        self.assertIn('if executable == "/usr/local/bin/labwc-system-menu-action"', waybar_run)
        self.assertIn('"--collect"', waybar_run)
        self.assertIn('"--slice=app.slice"', waybar_run)
        self.assertIn('"--property=KillMode=control-group"', waybar_run)
        for menu in (TARGET / "etc/skel-desktop/.config/waybar/gtk").glob("*.xml.tmpl"):
            self.assertNotIn("symbolic", menu.read_text(encoding="utf-8"), menu)
            for node in ElementTree.parse(menu).iter("property"):
                if node.get("name") == "icon-name" and node.text:
                    self.assertTrue(node.text.startswith("__THEME_"), (menu, node.text))
        help_window = (HELP_PACKAGE / "window.py").read_text(encoding="utf-8")
        help_render = (HELP_PACKAGE / "render.py").read_text(encoding="utf-8")
        appearance_menu = (TARGET / "usr/local/lib/python3.14/dist-packages/labwc_appearance/cli.py").read_text(encoding="utf-8")
        self.assertNotIn("symbolic", help_window + help_render + appearance_menu)
        for source_path in (
            TARGET / "usr/local/bin/labwc-capture.tmpl",
            TARGET / "usr/local/bin/labwc-external-drives.tmpl",
            TARGET / "usr/local/bin/labwc-bluetooth.tmpl",
        ):
            source = source_path.read_text(encoding="utf-8")
            self.assertNotRegex(source, r'notify\([^\n]*,\s*["\'][a-z][a-z0-9.-]*["\']')

    def test_only_system_settings_popup_has_managed_help_entry(self):
        gtk_root = TARGET / "etc/skel-desktop/.config/waybar/gtk"
        modules_root = TARGET / "etc/skel-desktop/.config/waybar/modules"
        expected_action = "help_help"
        removed_actions = {
            "help_audio", "help_bluetooth", "help_calendar", "help_launcher",
            "help_notifications", "help_power", "help_screenshot", "help_tomat",
            "help_wayscriber",
        }
        menu_count = 0
        module_count = 0
        for menu in sorted(gtk_root.glob("*.xml.tmpl")):
            module_name = menu.name.removesuffix(".tmpl")
            tree = ElementTree.parse(menu)
            help_items = [item for item in tree.iter("object")
                          if item.get("class") == "GtkMenuItem"
                          and any(node.text == "Help" for node in item.iter("property")
                                  if node.get("name") == "label")]
            if module_name == "system-menu.xml":
                self.assertEqual([item.get("id") for item in help_items], [expected_action], menu)
                system_ids = {item.get("id") for item in tree.iter("object")
                              if item.get("class") == "GtkMenuItem"}
                self.assertNotIn("help_diagnostics", system_ids)
                self.assertNotIn("help_computer_management", system_ids)
                self.assertIn("system_diagnostics", system_ids)
                self.assertIn("system_computer_management", system_ids)
                icons = [node.text for node in help_items[0].iter("property")
                         if node.get("name") == "icon-name"]
                self.assertEqual(icons, ["__THEME_FUZZEL_MENU_ACTION_HELP_ICON_NAME__"], menu)
            else:
                self.assertEqual(help_items, [], menu)
            self.assertNotIn("symbolic", menu.read_text(encoding="utf-8"), menu)
            owners = [module for module in modules_root.glob("*.tmpl")
                      if f"gtk/{module_name}" in module.read_text(encoding="utf-8")]
            self.assertTrue(owners, menu)
            for module in owners:
                module_text = module.read_text(encoding="utf-8")
                if module_name == "system-menu.xml":
                    self.assertIn(
                        f'"{expected_action}": "/usr/local/libexec/labwc-waybar-run -- '
                        f'/usr/local/bin/labwc-system-menu-action {expected_action}"',
                        module_text,
                    )
                    module_count += 1
                else:
                    for action in removed_actions:
                        self.assertNotIn(f'"{action}":', module_text)
            menu_count += 1
        self.assertEqual(menu_count, 10)
        self.assertEqual(module_count, 1)

    def test_fuzzel_places_help_below_desktop_settings(self):
        menu = (TARGET / "usr/local/bin/labwc-main-menu.tmpl").read_text(encoding="utf-8")
        top_line = next(line for line in menu.splitlines()
                        if "'Files', 'Computer Management', 'Desktop Settings', 'Help'" in line)
        self.assertLess(top_line.index("'Desktop Settings'"), top_line.index("'Help'"))
        self.assertIn("'Help': ('/usr/local/bin/labwc-help', '--topic', 'desktop.fuzzel')", menu)
        self.assertIn("'Help': '__THEME_FUZZEL_MENU_ACTION_HELP_ICON_NAME__'", menu)
        labwc = (TARGET / "etc/skel-desktop/.config/labwc/menu.xml.tmpl").read_text(encoding="utf-8")
        self.assertIn('label="Help" icon="__THEME_LABWC_MENU_HELP_ICON_NAME__"', labwc)
        themes = (ROOT / "hosts/themes/base.env").read_text(encoding="utf-8")
        schema = (ROOT / "hosts/themes/theme-schema.tsv").read_text(encoding="utf-8")
        self.assertIn('FUZZEL_MENU_ACTION_HELP_ICON_NAME="help-browser"', themes)
        self.assertIn('LABWC_MENU_HELP_ICON_NAME="help-browser"', themes)
        self.assertIn("base\tFUZZEL_MENU_ACTION_HELP_ICON_NAME\ticon", schema)
        self.assertIn("base\tLABWC_MENU_HELP_ICON_NAME\ticon", schema)

    def test_app_armor_and_installer_assets_cover_help(self):
        policy = (TARGET / "etc/apparmor.d/desktop-wrappers.tmpl").read_text(encoding="utf-8")
        staging = (ROOT / "scripts/desktop/components/target-assets.sh").read_text(encoding="utf-8")
        verify = (ROOT / "scripts/desktop/verify.sh.tmpl").read_text(encoding="utf-8")
        self.assertIn("profile labwc-help-ui", policy)
        self.assertIn("deny network inet", policy)
        self.assertIn("desktop_stage_help", staging)
        self.assertIn("/usr/local/share/labwc-help/catalog.json", verify)
        self.assertIn("/usr/local/share/labwc-help/theme.json", verify)
        self.assertIn("/usr/local/bin/labwc-help", verify)
        self.assertNotIn('import gi', verify)
        self.assertNotIn('/usr/bin/desktop-file-validate /usr/local/share/applications/labwc-help.desktop', verify)
        dependencies = (ROOT / 'classes/class-select/role/desktop.cfg').read_text().split()
        self.assertIn('gir1.2-gtk-4.0', dependencies)
        self.assertIn('gir1.2-adw-1', dependencies)
        self.assertIn('/usr/local/share/labwc-help/articles/*.json', verify)
        self.assertIn('labwc_help/theme.py', verify)
        self.assertNotIn('/usr/local/share/labwc-help/installed.json', verify)
        self.assertNotIn('labwc_help/system.py', verify)
        help_profile = policy.split('profile labwc-help-ui', 1)[1].split('profile labwc-zoom-command', 1)[0]
        for forbidden in ('dpkg-query', 'findmnt', 'systemctl', 'subprocess', 'installed.json'):
            self.assertNotIn(forbidden, help_profile)
        staging = (ROOT / "scripts/desktop/components/target-assets.sh").read_text(encoding="utf-8")
        self.assertNotIn('installed.json.tmpl', staging)
        self.assertNotIn('labwc_help/system.py', staging)

    def test_contextual_utilities_open_validated_topics(self):
        computer = (TARGET / "usr/local/bin/labwc-computer-management").read_text(encoding="utf-8")
        appearance = (TARGET / "usr/local/lib/python3.14/dist-packages/labwc_appearance/cli.py").read_text(encoding="utf-8")
        display = (TARGET / "usr/local/bin/labwc-display-configuration").read_text(encoding="utf-8")
        maintenance = (TARGET / "usr/local/bin/labwc-maintenance-menu.tmpl").read_text(encoding="utf-8")
        network = (TARGET / "usr/local/bin/labwc-network-control-menu").read_text(encoding="utf-8")
        sharing = (TARGET / "usr/local/bin/labwc-network-sharing").read_text(encoding="utf-8")
        for source, topic in ((computer, "maintenance.management"),
                              (appearance, "desktop.appearance"),
                              (display, "hardware.monitors"),
                              (maintenance, "maintenance.management"),
                              (network, "network.connections"),
                              (sharing, "network.sharing")):
            self.assertIn("/usr/local/bin/labwc-help", source)
            self.assertIn(topic, source)
        self.assertIn("Help launch timed out", appearance)
        self.assertIn("timeout=120", appearance)
        self.assertIn("Help launch timed out", sharing)
        self.assertIn("timeout=120", sharing)
        self.assertIn("'Display Help': (HELP, '--topic', 'hardware.monitors')", computer)
        fuzzel = (TARGET / "usr/local/bin/labwc-fuzzel.tmpl").read_text(encoding="utf-8")
        self.assertIn('label == "Help"', fuzzel)
        self.assertIn('label == "Display Help"', fuzzel)
        apparmor = (TARGET / "etc/apparmor.d/desktop-wrappers.tmpl").read_text(encoding="utf-8")
        self.assertIn("/usr/local/bin/labwc-help rPx -> labwc-help", apparmor)
        self.assertIn("/usr/local/bin/labwc-help rPx -> labwc-help", (TARGET / "etc/apparmor.d/labwc-appearance").read_text(encoding="utf-8"))
        self.assertIn("/usr/local/bin/labwc-help rPx -> labwc-help", (TARGET / "etc/apparmor.d/network-sharing").read_text(encoding="utf-8"))

    def test_waybar_popup_help_actions_deep_link_to_their_topics(self):
        dispatcher = (TARGET / "usr/local/bin/labwc-system-menu-action").read_text(encoding="utf-8")
        expected = {"help_help": "desktop.labwc"}
        for action, topic in expected.items():
            self.assertIn(f"'{action}': (HELP, '--topic', '{topic}')", dispatcher)
        for action in (
                "help_audio", "help_bluetooth", "help_calendar", "help_launcher",
                "help_notifications", "help_power", "help_screenshot", "help_tomat",
                "help_wayscriber"):
            self.assertNotIn(f"'{action}':", dispatcher)
        staging = (ROOT / "scripts/desktop/components/target-assets.sh").read_text(encoding="utf-8")
        self.assertIn("desktop.tomat", staging)
        self.assertIn("desktop.wayscriber", staging)

    def test_shared_fuzzel_help_is_topic_aware_and_confined(self):
        fuzzel = (TARGET / "usr/local/bin/labwc-fuzzel.tmpl").read_text(encoding="utf-8")
        self.assertIn("def help_topic(prompt: str) -> str:", fuzzel)
        self.assertIn("[HELP_LAUNCHER, '--topic', help_topic(options.prompt)]", fuzzel)
        self.assertIn("prompt = prompt.rstrip(' :>\\t')", fuzzel)
        self.assertIn("os.environ.get('LABWC_MENU_INPUT_MODE') != 'text'", fuzzel)
        self.assertIn("not options.power_confirmation", fuzzel)
        self.assertIn("if help_offered and chosen == b'Help':", fuzzel)
        self.assertIn("os.environ.pop('LABWC_MENU_ACTION_WAIT', None)", (TARGET / "usr/local/bin/labwc-help").read_text(encoding="utf-8"))
        self.assertIn("'desktop.tomat'", fuzzel)
        self.assertIn("'desktop.wayscriber'", fuzzel)
        for topic in (
                "'troubleshooting.audio'", "'troubleshooting.network'",
                "'applications.codex'", "'security.apparmor'",
                "'security.firewall'", "'security.authentication'",
                "'storage.recovery'", "'storage.btrfs'", "'storage.timeshift'",
                "'maintenance.services'", "'maintenance.updates'",
                "'desktop.calendar'", "'desktop.mako'", "'desktop.waybar'",
                "'hardware.monitors'", "'hardware.peripherals'",
        ):
            self.assertIn(topic, fuzzel)
        policy = (TARGET / "etc/apparmor.d/desktop-wrappers.tmpl").read_text(encoding="utf-8")
        self.assertIn("/usr/local/bin/labwc-help rPx -> labwc-help", policy)


if __name__ == "__main__":
    unittest.main()
