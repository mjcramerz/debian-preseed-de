"""Color-only editing, shared palettes, and transactional publication fixtures."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('manual_themes', ROOT/'tools/themes.py')
themes = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = themes
spec.loader.exec_module(themes)


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='themes-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root/'d-i/forky/hosts/themes'
        self.directory.mkdir(parents=True, mode=0o700)
        self.base = self.directory/'base.env'
        self.backups = self.directory.parent/'backup'
        for name in ('base.env', 'apps.env', 'office.env', 'theme-schema.tsv'):
            shutil.copyfile(ROOT/'d-i/forky/hosts/themes'/name, self.directory/name)
        script = self.root/'d-i/forky/scripts/late/theme-validate.awk'
        script.parent.mkdir(parents=True)
        shutil.copyfile(ROOT/'d-i/forky/scripts/late/theme-validate.awk', script)
        self.original = self.base.read_bytes()
        self.key = 'WAYBAR_PANEL_TEXT_COLOR'

    def test_catalog_covers_only_all_target_color_keys_once(self):
        with themes.Editor(self.root) as editor:
            keys = [key for section in editor.sections.values() for field in section.fields for key in field.keys]
            self.assertEqual(len(keys), 346)
            self.assertEqual(len(keys), len(set(keys)))
            self.assertTrue(all(key.endswith('_COLOR') or key.endswith('_ALPHA') for key in keys))
            self.assertFalse(any(key.endswith(('_ICON_GLYPH', '_ICON_NAME')) or 'FONT' in key for key in keys))
            self.assertEqual(len(editor.sections['fuzzel'].fields), 11)
            self.assertTrue(all(len(field.keys) == 2 for field in editor.sections['fuzzel'].fields))

    def test_shared_buttons_ask_once_per_surface_role(self):
        with themes.Editor(self.root) as editor:
            for section, count in (('waybar-hardware', 6), ('waybar-apps', 5), ('waybar-extras', 4)):
                for suffix in ('NORMAL_BACKGROUND_COLOR', 'HOVER_BACKGROUND_COLOR', 'NORMAL_OUTLINE_COLOR', 'HOVER_OUTLINE_COLOR', 'HOVER_SHADOW_COLOR'):
                    fields = [field for field in editor.sections[section].fields if any(key.endswith(suffix) for key in field.keys)]
                    self.assertEqual(len(fields), 1, (section, suffix))
                    self.assertEqual(len(fields[0].keys), count, (section, suffix))

    def test_backup_original_and_numbering_preserve_unrelated_bytes(self):
        self.backups.mkdir()
        (self.backups/'base.env-8.env').write_bytes(b'older')
        (self.backups/'base.env-21.env').write_bytes(b'newer')
        with themes.Editor(self.root) as editor:
            backup = editor.publish({self.key: '#123456'})
            self.assertEqual(backup.name, 'base.env-22.env')
            self.assertEqual(backup.read_bytes(), self.original)
            updated = self.base.read_bytes()
            self.assertEqual(updated, self.original.replace(b'WAYBAR_PANEL_TEXT_COLOR="#f5efe3"', b'WAYBAR_PANEL_TEXT_COLOR="#123456"'))
            second = editor.publish({self.key: '#ABCDEF'})
            self.assertEqual(second.name, 'base.env-23.env')
            self.assertEqual(second.read_bytes(), updated)
            self.assertEqual(stat.S_IMODE(second.stat().st_mode), 0o600)
            self.assertIn(b'WAYBAR_PANEL_TEXT_COLOR="#abcdef"', self.base.read_bytes())

    def test_publication_preserves_file_mode_and_group(self):
        self.base.chmod(0o640)
        if os.geteuid() == 0:
            os.chown(self.base, -1, 1000)
        original = self.base.stat()
        with themes.Editor(self.root) as editor:
            editor.publish({self.key: '#123456'})
        result = self.base.stat()
        self.assertEqual((result.st_uid, result.st_gid, stat.S_IMODE(result.st_mode)),
                         (original.st_uid, original.st_gid, stat.S_IMODE(original.st_mode)))

    def test_all_shared_fields_render_to_every_member_only(self):
        formats = {'rgba': 'rgba(1, 2, 3, 0.5)', 'hash6': '#123456', 'hex8': '#12345678', 'hash8': '#80123456', 'alpha': '0.5'}
        with themes.Editor(self.root) as editor:
            before = dict(editor.values)
            chosen = {}
            for name in ('waybar-hardware', 'waybar-extras', 'waybar-apps', 'fuzzel', 'crystal-dock'):
                for field in editor.sections[name].fields:
                    chosen.update(dict.fromkeys(field.keys, formats[field.kind]))
            editor.publish(chosen)
            for name, value in editor.values.items():
                if name not in chosen:
                    self.assertEqual(value, before[name], name)
            for name in ('waybar-hardware', 'waybar-extras', 'waybar-apps', 'fuzzel', 'crystal-dock'):
                for field in editor.sections[name].fields:
                    self.assertEqual(len({editor.values[key] for key in field.keys}), 1)
            self.assertEqual(editor.values['FUZZEL_MENU_BACKGROUND_COLOR'], '12345678')
            self.assertEqual(editor.values['DOCK_BACKGROUND_COLOR'], '#80123456')

    def test_noop_and_cancel_create_no_backups(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(editor.publish({self.key: editor.values[self.key]}))
            themes.edit_section(editor, editor.sections['waybar-panel'], lambda prompt: ':cancel')
            answers = iter(['rgba(1, 2, 3, 1)', '', '', '', 'NO'])
            themes.edit_section(editor, editor.sections['waybar-panel'], lambda prompt: next(answers))
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_invalid_color_and_noncolor_changes_fail_before_backup(self):
        with themes.Editor(self.root) as editor:
            for changes in ({self.key: '#123456; id'}, {'FOOT_CURSOR_STYLE': 'block'},
                            {'FUZZEL_MENU_BACKGROUND_COLOR': '$(touch /tmp/evil)'}, {self.key: '#123456\nBAD=1'}):
                with self.assertRaises(themes.ThemeError):
                    editor.publish(changes)
            self.assertEqual(list(self.backups.iterdir()), [])
        self.assertEqual(self.base.read_bytes(), self.original)

    def test_formats_and_alpha_order_are_explicit(self):
        self.assertEqual(themes.normalize('rgba(0, 255, 42, .5)', 'rgba'), 'rgba(0, 255, 42, 0.5)')
        self.assertEqual(themes.normalize('#aa123456', 'hash8'), '#aa123456')
        self.assertEqual(themes.normalize('#123456aa', 'hex8'), '123456aa')
        for value in ('rgba(256,0,0,1)', 'rgba(0,0,0,1.1)', 'rgba(-1,0,0,1)', 'rgba(0,0,0,nan)', 'rgb(0,0,0)', 'rgba(1,2,3,1); color: red'):
            with self.assertRaises(themes.ThemeError):
                themes.normalize(value, 'rgba')
        for value in ('nan', 'inf', '-1', '1.01', '1e-2'):
            with self.assertRaises(themes.ThemeError):
                themes.normalize(value, 'alpha')

    def test_concurrent_editor_fails_without_modification(self):
        with themes.Editor(self.root):
            with self.assertRaisesRegex(themes.ThemeError, 'another theme editor'):
                with themes.Editor(self.root):
                    pass
        self.assertEqual(self.base.read_bytes(), self.original)

    def test_external_edits_and_replacement_are_not_overwritten(self):
        with themes.Editor(self.root) as editor:
            self.base.write_bytes(self.original+b'# external\n')
            with self.assertRaisesRegex(themes.ThemeError, 'changed outside'):
                editor.publish({self.key: '#123456'})
            self.assertEqual(list(self.backups.iterdir()), [])
        self.assertTrue(self.base.read_bytes().endswith(b'# external\n'))

    def test_validator_failure_retains_original_and_durable_backup(self):
        with themes.Editor(self.root) as editor:
            with mock.patch.object(editor, 'validate', side_effect=themes.ThemeError('injected')):
                with self.assertRaises(themes.ThemeError):
                    editor.publish({self.key: '#123456'})
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual((self.backups/'base.env-1.env').read_bytes(), self.original)
        self.assertEqual(list(self.directory.glob('.themes-*')), [])

    def test_backup_failure_prevents_render_and_publication(self):
        with themes.Editor(self.root) as editor:
            with mock.patch.object(editor, 'backup', side_effect=OSError('disk full')), mock.patch.object(editor, 'validate') as validate:
                with self.assertRaises(OSError):
                    editor.publish({self.key: '#123456'})
                validate.assert_not_called()
        self.assertEqual(self.base.read_bytes(), self.original)

    def test_replace_failure_keeps_base_and_backup(self):
        with themes.Editor(self.root) as editor:
            with mock.patch.object(themes.os, 'replace', side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    editor.publish({self.key: '#123456'})
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual((self.backups/'base.env-1.env').read_bytes(), self.original)

    def test_leaf_symlink_and_hardlink_refused(self):
        saved = self.directory/'original'
        self.base.rename(saved)
        self.base.symlink_to(saved)
        with self.assertRaises((OSError, themes.ThemeError)):
            with themes.Editor(self.root):
                pass
        self.base.unlink()
        os.link(saved, self.base)
        with self.assertRaises(themes.ThemeError):
            with themes.Editor(self.root):
                pass

    def test_backup_directory_symlink_refused(self):
        outside = self.root/'outside'
        outside.mkdir()
        self.backups.symlink_to(outside)
        with self.assertRaises((OSError, themes.ThemeError)):
            with themes.Editor(self.root):
                pass
        self.assertEqual(list(outside.iterdir()), [])

    def test_writable_source_or_directory_refused(self):
        self.base.chmod(0o666)
        with self.assertRaises(themes.ThemeError):
            with themes.Editor(self.root):
                pass
        self.base.chmod(0o600)
        self.directory.chmod(0o777)
        with self.assertRaises(themes.ThemeError):
            with themes.Editor(self.root):
                pass

    def test_replaced_theme_directory_refused(self):
        with themes.Editor(self.root) as editor:
            self.directory.rename(self.directory.with_name('moved'))
            self.directory.mkdir()
            with self.assertRaisesRegex(themes.ThemeError, 'directory was replaced'):
                editor.publish({self.key: '#123456'})

    def test_complete_interactive_group_flow_retries_and_saves(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()) as output:
            section = editor.sections['waybar-apps']
            answers = iter(['not a color', 'rgba(1,2,3,1)', *(['']*(len(section.fields)-1)), 'APPLY'])
            themes.edit_section(editor, section, lambda prompt: next(answers))
            self.assertIn('expected rgba', output.getvalue())
            for field in section.fields:
                self.assertEqual(len({editor.values[key] for key in field.keys}), 1)
        self.assertEqual((self.backups/'base.env-1.env').read_bytes(), self.original)

    def test_make_target_is_manual_and_has_no_callers(self):
        text = (ROOT/'Makefile').read_text()
        self.assertIn('themes:\n\t$(PYTHON) -I -B tools/themes.py', text)
        for line in text.splitlines():
            if ':' in line and not line.startswith(('.PHONY:', '\t', '#')):
                target, dependencies = line.split(':', 1)
                self.assertNotIn('themes', dependencies.split(), target)
        result = subprocess.run(['make', '-n', 'themes'], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), 'python3 -I -B tools/themes.py')


if __name__ == '__main__':
    unittest.main()
