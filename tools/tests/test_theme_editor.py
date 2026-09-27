"""Color-only editing, shared palettes, and transactional publication fixtures."""
from __future__ import annotations

import contextlib
import errno
import importlib.util
import io
import os
import pty
from pathlib import Path
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
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

    def test_enter_preserves_every_existing_value_in_every_section(self):
        with themes.Editor(self.root) as editor:
            for name, section in editor.sections.items():
                for answer in ('', ' \t '):
                    with self.subTest(section=name, answer=repr(answer)):
                        prompts = []

                        def keep(prompt):
                            prompts.append(prompt)
                            return answer

                        before = themes.fingerprint(self.base.stat())
                        with contextlib.redirect_stdout(io.StringIO()) as output:
                            themes.edit_section(editor, section, keep)
                        self.assertEqual(len(prompts), len(section.fields))
                        self.assertFalse(any('APPLY' in prompt for prompt in prompts))
                        self.assertNotIn('settings will change', output.getvalue())
                        self.assertIn('No color changes.', output.getvalue())
                        self.assertEqual(self.base.read_bytes(), self.original)
                        self.assertEqual(themes.fingerprint(self.base.stat()), before)
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

    def test_shared_directory_and_file_modes_are_accepted_and_preserved(self):
        self.backups.mkdir()
        directories = [self.root, self.root/'d-i', self.root/'d-i/forky',
                       self.directory.parent, self.directory, self.backups]
        for index, (directory_mode, file_mode) in enumerate(
                ((0o755, 0o664), (0o770, 0o660), (0o2775, 0o664),
                 (0o777, 0o666), (0o1777, 0o644), (0o755, 0o444))):
            with self.subTest(directory_mode=oct(directory_mode), file_mode=oct(file_mode)):
                for directory in directories:
                    directory.chmod(directory_mode)
                self.base.chmod(file_mode)
                original = self.base.read_bytes()
                with themes.Editor(self.root) as editor:
                    backup = editor.publish({self.key: f'#{index+1:06x}'})
                    self.assertEqual(editor.values[self.key], f'#{index+1:06x}')
                self.assertEqual(backup.read_bytes(), original)
                self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(self.base.stat().st_mode), file_mode)
                for directory in directories:
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), directory_mode)

    def test_shared_permissions_enter_only_preserves_source_metadata(self):
        self.directory.chmod(0o777)
        self.base.chmod(0o666)
        before = themes.fingerprint(self.base.stat())
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            for section in editor.sections.values():
                themes.edit_section(editor, section, lambda prompt: '')
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(themes.fingerprint(self.base.stat()), before)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_shared_directory_still_serializes_editors(self):
        self.directory.chmod(0o777)
        self.backups.mkdir(mode=0o777)
        self.backups.chmod(0o777)
        with themes.Editor(self.root):
            with self.assertRaisesRegex(themes.ThemeError, 'another theme editor'):
                with themes.Editor(self.root):
                    pass
        self.assertEqual(self.base.read_bytes(), self.original)

    def test_unavailable_ownership_preservation_does_not_block_save(self):
        self.base.chmod(0o640)
        info = self.base.stat()
        with themes.Editor(self.root) as editor:
            with mock.patch.object(themes.os, 'fchown', side_effect=PermissionError(errno.EPERM, 'not owner')) as chown:
                backup = editor.publish({self.key: '#123456'})
            self.assertEqual(editor.values[self.key], '#123456')
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.base.stat().st_mode), 0o640)
        self.assertEqual([(call.args[1], call.args[2]) for call in chown.call_args_list],
                         [(info.st_uid, info.st_gid), (-1, info.st_gid)])

    def test_metadata_io_error_is_not_treated_as_ownership_denial(self):
        with themes.Editor(self.root) as editor:
            with mock.patch.object(themes.os, 'fchown', side_effect=OSError(errno.EIO, 'I/O error')):
                with self.assertRaises(OSError) as raised:
                    editor.publish({self.key: '#123456'})
                self.assertEqual(raised.exception.errno, errno.EIO)
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual((self.backups/'base.env-1.env').read_bytes(), self.original)
        self.assertEqual(list(self.directory.glob('.themes-*')), [])

    def test_mode_preservation_failure_does_not_publish(self):
        with themes.Editor(self.root) as editor:
            with mock.patch.object(themes.os, 'fchmod', side_effect=PermissionError(errno.EACCES, 'denied')):
                with self.assertRaises(PermissionError):
                    editor.publish({self.key: '#123456'})
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual((self.backups/'base.env-1.env').read_bytes(), self.original)
        self.assertEqual(list(self.directory.glob('.themes-*')), [])

    def test_replacement_does_not_copy_special_mode_bits(self):
        self.base.chmod(0o7644)
        with themes.Editor(self.root) as editor:
            editor.publish({self.key: '#123456'})
        self.assertEqual(stat.S_IMODE(self.base.stat().st_mode), 0o644)

    def test_replaced_theme_directory_refused(self):
        with themes.Editor(self.root) as editor:
            self.directory.rename(self.directory.with_name('moved'))
            self.directory.mkdir()
            with self.assertRaisesRegex(themes.ThemeError, 'directory was replaced'):
                editor.publish({self.key: '#123456'})

    def test_complete_interactive_group_flow_retries_and_saves(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()) as output:
            section = editor.sections['waybar-hardware']
            before = dict(editor.values)
            field = section.fields[0]
            answers = iter(['not a color', 'rgba(1,2,3,1)', *(['']*(len(section.fields)-1)), 'APPLY'])
            themes.edit_section(editor, section, lambda prompt: next(answers))
            self.assertIn('expected rgba', output.getvalue())
            expected = before | dict.fromkeys(field.keys, 'rgba(1, 2, 3, 1)')
            self.assertEqual(editor.values, expected)
        self.assertEqual((self.backups/'base.env-1.env').read_bytes(), self.original)

    def test_state_groups_partition_every_editable_key_once(self):
        with themes.Editor(self.root) as editor:
            for section in editor.sections.values():
                with self.subTest(section=section.name):
                    groups = themes.grouped_sections(section)
                    expected = [key for field in section.fields for key in field.keys]
                    actual = [key for group in groups.values() for field in group.fields for key in field.keys]
                    self.assertCountEqual(actual, expected)
                    self.assertEqual(len(actual), len(set(actual)))
                    for name, group in groups.items():
                        self.assertTrue(all(field.group == name for field in group.fields))

    def test_severity_groups_exclude_other_states_and_ask_once(self):
        with themes.Editor(self.root) as editor:
            hardware = editor.sections['waybar-hardware']
            groups = themes.grouped_sections(hardware)
            self.assertEqual(list(groups)[:4], ['NORMAL', 'HOVER', 'WARNING', 'CRITICAL'])
            for state in ('WARNING', 'CRITICAL'):
                with self.subTest(state=state):
                    fields = groups[state].fields
                    self.assertEqual(len(fields), 1)
                    expected = {key for field in hardware.fields for key in field.keys if state in key.split('_')}
                    self.assertEqual(set(fields[0].keys), expected)
                    self.assertEqual(len(expected), 12)
            for state in ('MUTED', 'UNAVAILABLE', 'AVAILABLE', 'CHARGING', 'FULL',
                          'NOT_CHARGING', 'PLUGGED', 'MICROPHONE_MUTED', 'MICROPHONE_NORMAL'):
                self.assertIn(state, groups)
            normal = [key for field in groups['NORMAL'].fields for key in field.keys]
            self.assertTrue(all('_NORMAL_' in key and '_MICROPHONE_' not in key for key in normal))

    def test_state_matching_is_token_based_with_severity_precedence(self):
        cases = {
            'UNAVAILABLE_ICON_COLOR': 'UNAVAILABLE',
            'AVAILABLE_TEXT_COLOR': 'AVAILABLE',
            'NOT_CHARGING_ICON_COLOR': 'NOT_CHARGING',
            'NOT_CHARGING_CRITICAL_ICON_COLOR': 'CRITICAL',
            'CHARGING_WARNING_ICON_COLOR': 'WARNING',
            'FULL_CRITICAL_ICON_COLOR': 'CRITICAL',
            'MICROPHONE_MUTED_ICON_COLOR': 'MICROPHONE_MUTED',
            'MICROPHONE_NORMAL_ICON_COLOR': 'MICROPHONE_NORMAL',
            'LONG_BREAK_PAUSED_TEXT_COLOR': 'PAUSED',
            'ACTIVE_HOVER_TEXT_COLOR': 'ACTIVE_HOVER',
            'ERROR_TEXT_COLOR': 'ERROR',
            'NOTWARNING_ICON_COLOR': 'GENERAL',
        }
        for role, expected in cases.items():
            with self.subTest(role=role):
                self.assertEqual(themes.color_group(role), expected)

    def test_enter_preserves_every_value_in_every_state_group(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(editor, 'publish') as publish:
                for section in editor.sections.values():
                    for group in themes.grouped_sections(section).values():
                        themes.edit_section(editor, group, lambda prompt: '')
                publish.assert_not_called()
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_enter_preserves_valid_literal_formatting_without_normalizing(self):
        replacements = {
            'WAYBAR_PANEL_TEXT_COLOR': '#F5EfE3',
            'WAYBAR_PANEL_BACKGROUND_COLOR': 'rgba(23,40,52,0.940)',
            'FUZZEL_MENU_BACKGROUND_COLOR': '010203AA',
            'DOCK_BACKGROUND_COLOR': '#Aa123456',
            'DOCK_APPLICATION_MENU_BACKGROUND_ALPHA': '0.8000',
        }
        lines, _ = themes.parse_base(self.original)
        data = ''.join(f'{match[1]}="{replacements[match[1]]}"{match[3]}'
                       if (match := themes.ASSIGNMENT.fullmatch(line)) and match[1] in replacements
                       else line for line in lines).encode('utf-8')
        self.base.write_bytes(data)
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            before = themes.fingerprint(self.base.stat())
            with mock.patch.object(themes, 'normalize', side_effect=AssertionError('blank must not normalize')):
                for section in editor.sections.values():
                    themes.edit_section(editor, section, lambda prompt: '')
            self.assertEqual(themes.fingerprint(self.base.stat()), before)
        self.assertEqual(self.base.read_bytes(), data)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_mixed_prompt_lists_existing_values_without_a_default_color(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()) as output:
            section = themes.grouped_sections(editor.sections['waybar-hardware'])['NORMAL']
            prompts = []

            def keep(prompt):
                prompts.append(prompt)
                return ''

            themes.edit_section(editor, section, keep)
            self.assertIn('[keep each existing value] > ', prompts)
            self.assertIn('Existing values differ. Enter keeps each one unchanged.', output.getvalue())
            for field in section.fields:
                for key in field.keys:
                    self.assertIn(f'{key}: {editor.values[key]}', output.getvalue())
        self.assertEqual(self.base.read_bytes(), self.original)

    def test_explicit_color_updates_only_selected_warning_or_critical_group(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()) as output:
            section = editor.sections['waybar-hardware']
            groups = themes.grouped_sections(section)
            for state, color in (('WARNING', '#123456'), ('CRITICAL', '#abcdef')):
                with self.subTest(state=state):
                    before = dict(editor.values)
                    original = self.base.read_bytes()
                    answers = iter([str(list(groups).index(state)+1), color, 'APPLY', '0'])
                    themes.edit_groups(editor, section, lambda prompt: next(answers))
                    keys = groups[state].fields[0].keys
                    self.assertEqual(editor.values, before | dict.fromkeys(keys, color))
                    backups = sorted(self.backups.iterdir())
                    self.assertEqual(backups[-1].read_bytes(), original)
                    self.assertEqual(len(backups), 1 if state == 'WARNING' else 2)
            self.assertNotIn('Normal Foreground |', output.getvalue())

    def test_explicit_first_color_can_unify_only_its_mixed_group(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            section = themes.grouped_sections(editor.sections['waybar-hardware'])['NORMAL']
            before = dict(editor.values)
            field = next(field for field in section.fields if len({before[key] for key in field.keys}) > 1)
            color = before[field.keys[0]]
            answers = iter([color if item == field else '' for item in section.fields] + ['APPLY'])
            themes.edit_section(editor, section, lambda prompt: next(answers))
            self.assertEqual(editor.values, before | dict.fromkeys(field.keys, color))

    def test_invalid_color_then_enter_does_not_stage_any_change(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()) as output:
            section = themes.grouped_sections(editor.sections['waybar-hardware'])['WARNING']
            answers = iter(['$(touch /tmp/theme-should-not-run)', ''])
            with mock.patch.object(editor, 'publish') as publish:
                themes.edit_section(editor, section, lambda prompt: next(answers))
                publish.assert_not_called()
            self.assertIn('No color changes.', output.getvalue())
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_cancel_discards_earlier_answers_in_unsaved_group(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            section = themes.grouped_sections(editor.sections['waybar-hardware'])['HOVER']
            answers = iter(['rgba(1,2,3,0.5)', ':cancel'])
            themes.edit_section(editor, section, lambda prompt: next(answers))
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_interrupt_or_eof_never_publishes_pending_answers(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            section = themes.grouped_sections(editor.sections['waybar-hardware'])['HOVER']
            for error in (EOFError, KeyboardInterrupt):
                for answers in (['rgba(1,2,3,0.5)', error], ['rgba(1,2,3,0.5)', '', '', error]):
                    with self.subTest(error=error, confirmation=len(answers) == 4):
                        with self.assertRaises(error):
                            themes.edit_section(editor, section, mock.Mock(side_effect=answers))
                        self.assertEqual(self.base.read_bytes(), self.original)
                        self.assertEqual(list(self.backups.iterdir()), [])

    def test_confirmation_requires_explicit_apply(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            section = themes.grouped_sections(editor.sections['waybar-hardware'])['WARNING']
            for confirmation in ('', ' ', 'apply', 'yes', ':cancel'):
                with self.subTest(confirmation=confirmation):
                    answers = iter(['#123456', confirmation])
                    themes.edit_section(editor, section, lambda prompt: next(answers))
                    self.assertEqual(self.base.read_bytes(), self.original)
                    self.assertEqual(list(self.backups.iterdir()), [])

    def test_enter_after_save_keeps_new_value_without_another_backup(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()):
            section = themes.grouped_sections(editor.sections['waybar-hardware'])['WARNING']
            answers = iter(['#123456', 'APPLY'])
            themes.edit_section(editor, section, lambda prompt: next(answers))
            saved = self.base.read_bytes()
            before = themes.fingerprint(self.base.stat())
            themes.edit_section(editor, section, lambda prompt: '')
            self.assertEqual(self.base.read_bytes(), saved)
            self.assertEqual(themes.fingerprint(self.base.stat()), before)
        self.assertEqual([path.name for path in self.backups.iterdir()], ['base.env-1.env'])

    def test_blank_or_invalid_state_selection_cannot_stage_colors(self):
        with themes.Editor(self.root) as editor, contextlib.redirect_stdout(io.StringIO()) as output:
            section = editor.sections['waybar-hardware']
            for choice in ('', ' \t ', 'q', ':cancel', '0'):
                themes.edit_groups(editor, section, lambda prompt: choice)
            for invalid in ('-1', '999', '9'*100, '1.0', '\u0661', '#123456'):
                answers = iter([invalid, ''])
                themes.edit_groups(editor, section, lambda prompt: next(answers))
            self.assertIn('Choose a displayed color-state number.', output.getvalue())
            self.assertNotIn(' | ', output.getvalue())
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_main_routes_to_the_selected_state_only(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True

        editor = themes.Editor(self.root)
        with mock.patch.object(themes, 'Editor', return_value=editor), \
                mock.patch.object(sys, 'stdin', Terminal()), mock.patch.object(sys, 'stdout', Terminal()) as output, \
                mock.patch('builtins.input', side_effect=['7', '3', '#123456', 'APPLY', '0', '0']):
            self.assertEqual(themes.main([]), 0)
            self.assertIn('WARNING (1 color prompt(s), 12 setting(s))', output.getvalue())
        _, before = themes.parse_base(self.original)
        expected = {key: '#123456' for key in before if key.startswith('WAYBAR_BUTTON_') and '_WARNING_' in key and key.endswith('_COLOR')}
        self.assertEqual(editor.values, before | expected)

    def run_make_themes(self, answers, *, expected_status=0, **identity):
        # Exercise the real make recipe and isolated (-I) CLI, not a mock of input.
        tools = self.root/'tools'
        tools.mkdir(exist_ok=True)
        shutil.copyfile(ROOT/'tools/themes.py', tools/'themes.py')
        shutil.copyfile(ROOT/'Makefile', self.root/'Makefile')
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(['make', 'themes', 'PYTHON='+sys.executable], cwd=self.root,
                                       stdin=slave, stdout=slave, stderr=slave, start_new_session=True, **identity)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        output = bytearray()
        try:
            data = ('\n'.join(answers)+'\n').encode('ascii')
            while data:
                data = data[os.write(master, data):]
            deadline = time.monotonic()+15
            while True:
                remaining = deadline-time.monotonic()
                self.assertGreater(remaining, 0, bytes(output).decode(errors='replace'))
                ready, _, _ = select.select([master], [], [], remaining)
                if not ready:
                    self.fail('make themes did not finish')
                try:
                    chunk = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                output.extend(chunk)
                self.assertLess(len(output), 1024*1024, 'unexpectedly large terminal output')
            self.assertEqual(process.wait(timeout=5), expected_status, bytes(output).decode(errors='replace'))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            os.close(master)
        return bytes(output)

    def test_make_themes_terminal_enter_only_preserves_source_and_creates_no_backup(self):
        _, values = themes.parse_base(self.original)
        sections = themes.catalog(self.directory/'theme-schema.tsv', values)
        hardware = sections['waybar-hardware']
        answers = [str(list(sections).index('waybar-hardware')+1)]
        for index, group in enumerate(themes.grouped_sections(hardware).values(), 1):
            answers.extend([str(index), *(['']*len(group.fields))])
        answers.extend(['0', '0'])
        output = self.run_make_themes(answers)
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(list(self.backups.iterdir()), [])
        self.assertNotIn(b'color settings will change', output)
        self.assertNotIn(b'Type APPLY', output)
        self.assertEqual(output.count(b'No color changes.'), len(themes.grouped_sections(hardware)))

    def prepare_foreign_owned_checkout(self, *, shared_group=True):
        # Run the CLI without root capabilities. Only these disposable fixture
        # paths are changed; no host account or repository permission is altered.
        uid = gid = 65534
        self.backups.mkdir(exist_ok=True)
        self.root.chmod(0o755)
        directories = [self.root/'d-i', self.root/'d-i/forky',
                       self.directory.parent, self.directory, self.backups]
        for directory in directories:
            os.chown(directory, 0, gid if shared_group else 0)
            directory.chmod(0o2770 if shared_group else 0o777)
        os.chown(self.base, 0, gid if shared_group else 0)
        self.base.chmod(0o640 if shared_group else 0o644)
        return dict(user=uid, group=gid, extra_groups=[])

    def assert_warning_edit_only(self):
        _, before = themes.parse_base(self.original)
        _, after = themes.parse_base(self.base.read_bytes())
        expected = {key: '#123456' for key in before
                    if key.startswith('WAYBAR_BUTTON_') and '_WARNING_' in key and key.endswith('_COLOR')}
        self.assertEqual(len(expected), 12)
        self.assertEqual(after, before | expected)
        self.assertEqual((self.backups/'base.env-1.env').read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE((self.backups/'base.env-1.env').stat().st_mode), 0o600)
        self.assertEqual(list(self.directory.glob('.themes-*')), [])

    @unittest.skipUnless(os.geteuid() == 0, 'requires root only to prepare a foreign-owned fixture and drop UID')
    def test_unprivileged_make_themes_saves_foreign_owned_shared_group_file(self):
        identity = self.prepare_foreign_owned_checkout()
        output = self.run_make_themes(['7', '3', '#123456', 'APPLY', '0', '0'], **identity)
        self.assertIn(b'12 color settings will change', output)
        self.assert_warning_edit_only()
        info = self.base.stat()
        self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)), (65534, 65534, 0o640))
        self.assertEqual(self.directory.stat().st_uid, 0)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o2770)

    @unittest.skipUnless(os.geteuid() == 0, 'requires root only to prepare a foreign-owned fixture and drop UID')
    def test_unprivileged_make_themes_saves_with_foreign_owner_and_group(self):
        identity = self.prepare_foreign_owned_checkout(shared_group=False)
        self.run_make_themes(['7', '3', '#123456', 'APPLY', '0', '0'], **identity)
        self.assert_warning_edit_only()
        info = self.base.stat()
        self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)), (65534, 65534, 0o644))
        self.assertEqual((self.directory.stat().st_uid, self.directory.stat().st_gid), (0, 0))
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o777)

    @unittest.skipUnless(os.geteuid() == 0, 'requires root only to prepare a foreign-owned fixture and drop UID')
    def test_unprivileged_make_themes_enter_preserves_foreign_owned_file(self):
        identity = self.prepare_foreign_owned_checkout()
        before = themes.fingerprint(self.base.stat())
        output = self.run_make_themes(['7', '3', '', '0', '0'], **identity)
        self.assertIn(b'No color changes.', output)
        self.assertNotIn(b'Type APPLY', output)
        self.assertEqual(themes.fingerprint(self.base.stat()), before)
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(list(self.backups.iterdir()), [])

    @unittest.skipUnless(os.geteuid() == 0, 'requires root only to prepare a foreign-owned fixture and drop UID')
    def test_unprivileged_make_themes_reports_real_write_denial_without_chmod(self):
        identity = self.prepare_foreign_owned_checkout(shared_group=False)
        self.directory.chmod(0o755)  # Search/read allowed, creation/replacement denied.
        output = self.run_make_themes(['7', '3', '#123456', 'APPLY'], expected_status=2, **identity)
        self.assertIn(b'Permission denied', output)
        self.assertNotIn(b'Saved ', output)
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual((self.backups/'base.env-1.env').read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o755)
        self.assertEqual(list(self.directory.glob('.themes-*')), [])

    @unittest.skipUnless(os.geteuid() == 0, 'requires root only to prepare a foreign-owned fixture and drop UID')
    def test_unprivileged_make_themes_reports_real_read_denial_without_chmod(self):
        identity = self.prepare_foreign_owned_checkout(shared_group=False)
        self.base.chmod(0o600)
        output = self.run_make_themes(['0'], expected_status=2, **identity)
        self.assertIn(b'Permission denied', output)
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.base.stat().st_mode), 0o600)
        self.assertEqual(list(self.backups.iterdir()), [])

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
