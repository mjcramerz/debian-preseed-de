"""Canonical appearance names and native palette mappings; no target services.

The migration table records identifiers only. Default values and native formats
remain owned by the three production catalogs and their installer validator.
"""
from __future__ import annotations
from payload_fixture import copyfile as payload_copyfile, installed_argv as payload_installed_argv
from payload_fixture import read_text as payload_read_text

from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / 'd-i/forky'
TARGET = SEED / 'hooks/target'
THEMES = SEED / 'hosts/themes'
CHECKER = runpy.run_path(str(ROOT / 'tools/check_themes.py'))
VALUES = CHECKER['load_themes']()
HUES = ('BLACK', 'RED', 'GREEN', 'YELLOW', 'BLUE', 'MAGENTA', 'CYAN', 'WHITE')
TOKEN = re.compile(r'__(?:THEME|INSTALLER)_([A-Z0-9_]+?)__')
IDENTIFIER = re.compile(r'(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]*(?![A-Za-z0-9_])')


def migration_rows() -> list[tuple[str, str, str]]:
    path = ROOT / 'd-i/forky/tests/fixtures/contracts/theme-names.tsv'
    return [tuple(line.split('\t')) for line in payload_read_text(path).splitlines()
            if line and not line.startswith('#')]


def identifiers(text: str) -> set[str]:
    tokens = {match[1].removeprefix('TARGET_PATH_') for match in TOKEN.finditer(text)}
    return tokens | set(IDENTIFIER.findall(TOKEN.sub('', text)))


class ThemeNamingTests(unittest.TestCase):
    def test_migration_is_one_to_one_and_destinations_have_correct_owners(self):
        rows = migration_rows()
        self.assertEqual(len(rows), len({old for old, _, _ in rows}))
        self.assertEqual(len(rows), len({new for _, new, _ in rows}))
        schema = {}
        for line in payload_read_text(THEMES / 'theme-schema.tsv').splitlines():
            if line and not line.startswith('#'):
                owner, name, _ = line.split('\t')
                schema[name] = owner
        renderer = identifiers(payload_read_text(SEED / 'scripts/desktop/components.sh'))
        old_names = {old for old, _, _ in rows}
        self.assertFalse(old_names & set(VALUES))
        self.assertFalse(old_names & {new for _, new, _ in rows})
        for old, new, owner in rows:
            with self.subTest(old=old):
                self.assertNotEqual(old, new)
                CHECKER['check_names']([new])
                if owner in ('base', 'apps', 'office'):
                    self.assertEqual(schema.get(new), owner)
                elif owner == 'profiles':
                    self.assertIn(new, CHECKER['SIZES'])
                else:
                    self.assertEqual(owner, 'renderer')
                    self.assertIn(new, renderer)

    def test_production_sources_have_no_retired_names_or_placeholders(self):
        old_names = {old for old, _, _ in migration_rows()}
        sources = list(CHECKER['source_texts'](SEED))
        sources += [(path, payload_read_text(path)) for path in (SEED / 'hosts/profiles').glob('*.env')]
        sources += [(path, payload_read_text(path)) for path in THEMES.glob('*.env')]
        sources += [(THEMES / 'theme-schema.tsv', payload_read_text(THEMES / 'theme-schema.tsv'))]
        sources += [(ROOT / 'tools/check_themes.py', payload_read_text(ROOT / 'tools/check_themes.py'))]
        for path, text in sources:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertFalse(identifiers(text) & old_names)

    def test_naming_lint_rejects_opaque_slots_and_repeated_properties(self):
        invalid = (
            'KITTY_COLOR0_COLOR', 'FOOT_DARK_REGULAR3_COLOR',
            'TUTANOTA_DESKTOP_DESKTOP_ICON_NAME', 'SATTY_PALETTE_PALETTE_RED_COLOR',
            'WAYSCRIBER_BOARD_SLOT_0_COLOR', 'SLEEK_TEXT_BG_COLOR',
            'EXAMPLE_COLOR_HOVER_COLOR', 'EXAMPLE_COLORS_COLOR',
            'MIXED_case_COLOR', 'EXAMPLE__TEXT_COLOR',
        )
        for name in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                CHECKER['check_names']([name])
        CHECKER['check_names'](VALUES)
        CHECKER['check_names']((
            'KITTY_ANSI_NORMAL_RED_COLOR', 'FOOT_DARK_ANSI_BRIGHT_BLUE_COLOR',
            'OBSIDIAN_DARK_NEUTRAL_PALETTE_SHADE_00_COLOR',
            'VSCODE_EDITOR_BRACKET_LEVEL_1_TEXT_COLOR',
            'SHOW_DESKTOP_LAUNCHER_ICON_NAME', 'FUZZEL_INTERNAL_FONT_SIZE',
        ))

    def test_launcher_icon_names_only_control_desktop_entry_icons(self):
        launcher_names = {name for name in VALUES if '_LAUNCHER_ICON_' in name}
        self.assertTrue(launcher_names)
        seen = set()
        for path, text in CHECKER['source_texts'](SEED):
            for line in text.splitlines():
                for match in TOKEN.finditer(line):
                    if match[1] in launcher_names:
                        with self.subTest(name=match[1], path=str(path)):
                            self.assertTrue(path.name.endswith(('.desktop', '.desktop.tmpl')), str(path))
                            self.assertTrue(line.startswith('Icon='), line)
                        seen.add(match[1])
        self.assertEqual(seen, launcher_names)
        for name in ('SHOW_DESKTOP', 'TUTANOTA', 'WAYPAPER'):
            self.assertIn(name + '_LAUNCHER_ICON_NAME', VALUES)

    def test_profiles_have_one_contiguous_shared_geometry_block(self):
        keys = CHECKER['SIZES']
        for path in (SEED / 'hosts/profiles').glob('*.env'):
            with self.subTest(profile=path.name):
                assignments = re.findall(r'^(FUZZEL_[A-Z_]+)="([0-9]+)"$', payload_read_text(path), re.M)
                self.assertEqual([name for name, _ in assignments], list(keys))
                positions = [payload_read_text(path).index(name + '=') for name in keys]
                geometry = payload_read_text(path)[positions[0]:positions[-1]]
                self.assertNotRegex(geometry, r'(?m)^(?!FUZZEL_)[A-Z][A-Z0-9_]*=')

    def test_terminal_palette_roles_map_to_exact_native_slots(self):
        kitty = payload_read_text(TARGET / 'etc/skel-desktop/.config/kitty/kitty.conf')
        foot = payload_read_text(TARGET / 'etc/skel-desktop/.config/foot/foot.ini')
        vscode = payload_read_text(TARGET / 'etc/skel-desktop/.config/Code/User/settings.json')
        for bright in (False, True):
            state = 'BRIGHT' if bright else 'NORMAL'
            for index, hue in enumerate(HUES):
                with self.subTest(state=state, hue=hue):
                    slot = index + (8 if bright else 0)
                    self.assertRegex(kitty, rf'(?m)^color{slot}\s+__THEME_KITTY_ANSI_{state}_{hue}_COLOR__$')
                    native = ('bright' if bright else 'regular') + str(index)
                    self.assertRegex(foot, rf'(?m)^{native}=__THEME_FOOT_DARK_ANSI_{state}_{hue}_COLOR__$')
                    native = 'terminal.ansi' + ('Bright' if bright else '') + hue.title()
                    self.assertIn(f'"{native}": "__THEME_VSCODE_TERMINAL_ANSI_{state}_{hue}_COLOR__"', vscode)


class ThemePaletteMutationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='theme-naming-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('base.env', 'apps.env', 'office.env', 'theme-schema.tsv'):
            payload_copyfile(THEMES / name, self.root / name)

    def validate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(payload_installed_argv(['awk', '-f', str(SEED / 'scripts/late/theme-validate.awk'),
            str(self.root / 'theme-schema.tsv'),
            *[str(self.root / (owner + '.env')) for owner in ('base', 'apps', 'office')]]),
            text=True, capture_output=True, timeout=10)

    def render(self, path: Path, mapping: str) -> str:
        map_path = self.root / 'values.map'
        map_path.write_text(mapping)
        result = subprocess.run(payload_installed_argv(['awk', '-f', str(SEED / 'scripts/late/theme-render.awk'),
                                 str(map_path), str(path)]), text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_each_ansi_edit_changes_only_its_own_native_color_slot(self):
        baseline = self.validate()
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        for prefix, owner, relative in (
            ('KITTY', 'base', 'kitty/kitty.conf'),
            ('FOOT_DARK', 'base', 'foot/foot.ini'),
            ('VSCODE_TERMINAL', 'apps', 'Code/User/settings.json'),
        ):
            path = TARGET / 'etc/skel-desktop/.config' / relative
            original = self.render(path, baseline.stdout)
            catalog_path = self.root / (owner + '.env')
            catalog = payload_read_text(catalog_path)
            for bright in (False, True):
                state = 'BRIGHT' if bright else 'NORMAL'
                for index, hue in enumerate(HUES):
                    name = f'{prefix}_ANSI_{state}_{hue}_COLOR'
                    new_value = '123abc' if prefix == 'FOOT_DARK' else '#123abc'
                    with self.subTest(name=name):
                        changed, count = re.subn(r'^' + name + r'="[^"\n]*"$',
                            lambda _: f'{name}="{new_value}"', catalog, flags=re.M)
                        self.assertEqual(count, 1)
                        catalog_path.write_text(changed)
                        validated = self.validate()
                        self.assertEqual(validated.returncode, 0, validated.stderr)
                        if prefix == 'KITTY':
                            native = 'color' + str(index + (8 if bright else 0))
                            old_line = native + ' ' + VALUES[name]
                            new_line = native + ' ' + new_value
                        elif prefix == 'FOOT_DARK':
                            native = ('bright' if bright else 'regular') + str(index)
                            old_line = native + '=' + VALUES[name]
                            new_line = native + '=' + new_value
                        else:
                            native = 'terminal.ansi' + ('Bright' if bright else '') + hue.title()
                            old_line = f'"{native}": "{VALUES[name]}"'
                            new_line = f'"{native}": "{new_value}"'
                        self.assertEqual(original.count(old_line), 1)
                        self.assertEqual(self.render(path, validated.stdout), original.replace(old_line, new_line, 1))
                    catalog_path.write_text(catalog)

    def test_retired_palette_name_fails_installer_validation_without_partial_output(self):
        path = self.root / 'base.env'
        text = payload_read_text(path)
        path.write_text(text.replace('KITTY_ANSI_NORMAL_BLACK_COLOR=', 'KITTY_COLOR0_COLOR=', 1))
        result = self.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
