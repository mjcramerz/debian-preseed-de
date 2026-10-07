"""Native icon ownership, safe markup/ANSI and install-time mutation regressions.

No real session, daemon, network, power endpoint or GUI application is started.
Optional native Pango/GTK/fzf tests report skips when those host tools are absent.
"""
from __future__ import annotations
from payload_fixture import waybar_config_text
from waybar_fixture import profiles, rendered_assets
from payload_fixture import copyfile as payload_copyfile, installed_argv as payload_installed_argv
from payload_fixture import read_text as payload_read_text
import contextlib
import ctypes as C
import ctypes.util
import io
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / 'd-i/forky'
TARGET = SEED / 'hooks/target'
THEMES = SEED / 'hosts/themes'
SKEL = TARGET / 'etc/skel-desktop/.config'
CHECK = runpy.run_path(str(ROOT / 'tools/check_themes.py'))
VALUES = CHECK['load_themes']()
RENDER = CHECK['render_text']


def load(relative, values=None):
    path = TARGET / relative
    mod = types.ModuleType('icon_fixture_' + path.name.replace('-', '_'))
    mod.__file__ = str(path)
    exec(compile(RENDER(payload_read_text(path), values or VALUES), str(path), 'exec'), mod.__dict__)
    return mod


def bars(values=None):
    text = RENDER(waybar_config_text(SKEL / 'waybar'), values or VALUES)
    return json.loads(re.sub(r'__INSTALLER_[A-Z0-9_]+__', '0', text))


def tree(text):
    return ET.fromstring('<markup>' + text + '</markup>')


def plain(text):
    return ''.join(tree(text).itertext())


class IconContractTests(unittest.TestCase):
    def test_glyphs_have_color_owners_and_pair_lint_rejects_missing_color(self):
        CHECK['check_icon_pairs'](VALUES)
        for name in VALUES:
            if name.endswith('_ICON_GLYPH') and name not in CHECK['SHARED_GLYPH_STYLES']:
                with self.subTest(name=name):
                    color = name.removesuffix('_GLYPH') + '_COLOR'
                    broken = dict(VALUES); del broken[color]
                    with self.assertRaisesRegex(ValueError, re.escape(color)):
                        CHECK['check_icon_pairs'](broken)

    def test_icon_migration_is_one_to_one_and_every_destination_is_owned(self):
        path = ROOT / 'd-i/forky/tests/fixtures/contracts/icon-names.tsv'
        rows = [line.split('\t') for line in payload_read_text(path).splitlines() if line and not line.startswith('#')]
        self.assertEqual(len(rows), len({row[0] for row in rows}))
        self.assertEqual(len(rows), len({row[1] for row in rows}))
        for old, new, owner in rows:
            self.assertNotIn(old, VALUES)
            self.assertIn(new, VALUES)
            self.assertEqual(owner, 'base')
        for _, text in CHECK['source_texts'](SEED):
            for old, _, _ in rows:
                self.assertNotIn('__THEME_' + old + '__', text)

    def test_no_inoperative_taskbar_tint_is_advertised(self):
        self.assertFalse(any(name.startswith('WAYBAR_BUTTON_TASKBAR_') and
                             name.endswith('_ICON_COLOR') for name in VALUES))
        css = payload_read_text(SKEL / 'waybar/style.css.tmpl')
        self.assertRegex(css, r'#tray > widget\s*\{\s*color:\s*__THEME_WAYBAR_BUTTON_TRAY_NORMAL_ICON_COLOR__;\s*\}')
        self.assertNotIn('#tray image { color:', css)

    def test_individual_icon_edits_use_real_installer_validation_and_rendering(self):
        colors = [name for name in VALUES if name.endswith('_ICON_COLOR') and
                  (VALUES[name] == 'inherit' or re.fullmatch(r'#[0-9a-fA-F]{6}', VALUES[name]))]
        sources = [(p, text) for p, text in CHECK['source_texts'](SEED) if '__THEME_' in text]
        with tempfile.TemporaryDirectory() as work:
            work = Path(work)
            for name in ('base.env', 'apps.env', 'office.env', 'theme-schema.tsv'):
                payload_copyfile(THEMES / name, work / name)
            for name in colors:
                owner = next(group for group in ('base', 'apps', 'office')
                             if re.search(r'^' + name + '=', payload_read_text(THEMES / (group + '.env')), re.M))
                original = payload_read_text(THEMES / (owner + '.env'))
                changed = re.sub(r'^' + name + r'="[^"\n]*"$', name + '="#123abc"', original, flags=re.M)
                (work / (owner + '.env')).write_text(changed)
                command = ['awk', '-f', str(SEED / 'scripts/late/theme-validate.awk'),
                           str(work / 'theme-schema.tsv'), *[str(work / (g + '.env')) for g in ('base', 'apps', 'office')]]
                with self.subTest(name=name):
                    result = subprocess.run(payload_installed_argv(command), capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    got = dict(line.split('=', 1) for line in result.stdout.splitlines())
                    self.assertEqual(got, dict(VALUES, **{name: '#123abc'}))
                    token = '__THEME_' + name + '__'
                    consumers = [(p, text) for p, text in sources if token in text]
                    self.assertTrue(consumers, name)
                    mapping = work / 'map'; mapping.write_text(result.stdout)
                    for path, text in consumers:
                        output = subprocess.run(payload_installed_argv(['awk', '-f', str(SEED / 'scripts/late/theme-render.awk'),
                            str(mapping), str(path)]), capture_output=True, text=True, timeout=10)
                        self.assertEqual(output.returncode, 0, output.stderr)
                        self.assertEqual(output.stdout, RENDER(text.replace(token, '#123abc'), VALUES))
                (work / (owner + '.env')).write_text(original)

    def test_invalid_colors_fail_without_publishing_a_partial_map(self):
        with tempfile.TemporaryDirectory() as work:
            work = Path(work)
            for name in ('base.env', 'apps.env', 'office.env', 'theme-schema.tsv'):
                payload_copyfile(THEMES / name, work / name)
            original = payload_read_text(work / 'base.env')
            name = 'FZF_MANAGEMENT_BACK_ICON_COLOR'
            for bad in ('red', '#123', '#12345678', 'inherit;id', '$(id)', '\x1b[31m', "#123abc' weight='bold", '\u202e'):
                with self.subTest(value=repr(bad)):
                    (work / 'base.env').write_text(re.sub(r'^' + name + r'=.*$',
                        lambda _: name + '="' + bad + '"', original, flags=re.M))
                    result = subprocess.run(payload_installed_argv(['awk', '-f', str(SEED / 'scripts/late/theme-validate.awk'),
                        str(work / 'theme-schema.tsv'), *[str(work / (g + '.env')) for g in ('base', 'apps', 'office')]]),
                        capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')


class WaybarIconTests(unittest.TestCase):
    def test_mixed_native_formats_color_only_glyph_not_numeric_label(self):
        for bar in bars():
            for component, field in (('cpu','usage'), ('disk','percentage_used'), ('memory','percentage')):
                for state in ('NORMAL','WARNING','CRITICAL'):
                    with self.subTest(bar=bar['name'], component=component, state=state):
                        key = 'format' + ('' if state == 'NORMAL' else '-' + state.lower())
                        markup = bar[component][key].replace('{' + field + '}', '42')
                        node = tree(markup)
                        stem = f'WAYBAR_BUTTON_{component.upper()}_{state}'
                        self.assertEqual(len(node), 1)
                        self.assertEqual(node[0].text, VALUES[stem + '_ICON_GLYPH'])
                        self.assertEqual(node[0].attrib, {'foreground': VALUES[stem + '_ICON_COLOR']})
                        self.assertEqual(node[0].tail, ' 42%')
            for state in ('NORMAL', 'MUTED'):
                fmt = bar['pulseaudio']['format' + ('' if state == 'NORMAL' else '-muted')]
                node = tree(fmt.replace('{volume}', '42').replace('{format_source}', ''))
                self.assertEqual(node[0].text, VALUES[f'WAYBAR_BUTTON_AUDIO_{state}_ICON_GLYPH'])
                self.assertEqual(node[0].tail, ' 42% ')

    def test_battery_combined_status_state_formats_keep_native_glyph_precedence(self):
        for bar in bars():
            config = bar['battery']
            for status in ('CHARGING', 'FULL', 'PLUGGED', 'NOT_CHARGING'):
                for state in ('WARNING', 'CRITICAL'):
                    key = 'format-' + status.lower().replace('_','-') + '-' + state.lower()
                    node = tree(config[key].replace('{capacity}', '12'))
                    self.assertEqual(node[0].text, VALUES[f'WAYBAR_BUTTON_BATTERY_{status}_ICON_GLYPH'])
                    self.assertEqual(node[0].attrib['foreground'], VALUES[f'WAYBAR_BUTTON_BATTERY_{status}_{state}_ICON_COLOR'])
                    self.assertEqual(node[0].tail, ' 12%')

    def test_brightness_status_is_valid_json_with_independent_span(self):
        source = RENDER(payload_read_text(TARGET / 'usr/local/bin/labwc-brightness-control'), VALUES)
        function = source[source.index('print_status() {'):source.index('\napply_brightness() {')]
        for shell in (['/bin/sh'], *([['busybox', 'sh']] if shutil.which('busybox') else [])):
            for value in ('73', '', 'not-a-number'):
                with self.subTest(shell=shell, value=value):
                    code = 'current_percent() { printf "%s" "$1"; }\n'
                    # A private helper fixture supplies data, not a real backlight.
                    code = 'current_percent() { printf "%s" ' + shlex.quote(value) + '; }\n' + function + '\nprint_status\n'
                    result = subprocess.run(payload_installed_argv(shell + ['-eu', '-c', code]), capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = json.loads(result.stdout)
                    state = 'AVAILABLE' if value == '73' else 'UNAVAILABLE'
                    node = tree(data['text'])
                    self.assertEqual(node[0].text, VALUES[f'WAYBAR_BUTTON_BACKLIGHT_{state}_ICON_GLYPH'])
                    self.assertEqual(node[0].attrib['foreground'], VALUES[f'WAYBAR_BUTTON_BACKLIGHT_{state}_ICON_COLOR'])
                    self.assertEqual(node[0].tail, ' 73%' if state == 'AVAILABLE' else ' N/A')

    def test_screenshot_and_bluetooth_keep_existing_plain_json_protocol(self):
        screenshot = payload_read_text(TARGET / 'usr/local/bin/labwc-capture')
        for state in ('IDLE','RECORDING'):
            self.assertIn(f'__THEME_WAYBAR_BUTTON_SCREENSHOT_{state}_ICON_GLYPH__', screenshot)
        bluetooth = payload_read_text(TARGET / 'usr/local/bin/labwc-bluetooth')
        for state in ('ENABLED','CONNECTED','DISABLED','UNAVAILABLE'):
            self.assertIn(f'__THEME_WAYBAR_BUTTON_BLUETOOTH_{state}_ICON_GLYPH__', bluetooth)
        for text in (screenshot, bluetooth):
            self.assertNotIn('<span', text)
        for bar in bars():
            self.assertFalse(bar['custom/tomat']['escape'])
            self.assertTrue(bar['custom/notifications']['escape'])

    def test_keyboard_flags_use_catalog_glyphs_without_changing_status_protocol(self):
        original = payload_read_text(TARGET/'usr/local/bin/labwc-keyboard-layout')
        for variant,values in (('default',VALUES),('replacement',dict(VALUES,
                WAYBAR_BUTTON_KEYBOARD_SWEDISH_ICON_GLYPH='\uf030',
                WAYBAR_BUTTON_KEYBOARD_US_ENGLISH_ICON_GLYPH='\uf111'))):
            text = RENDER(original,values)
            functions = '\n'.join(re.search(r'^'+name+r'\(\) \{.*?^\}',text,re.M|re.S)[0]
                                  for name in ('layout_label','layout_flag','print_status_json'))
            for layout,language,label in (('se','SWEDISH','SE'),('us','US_ENGLISH','US')):
                with self.subTest(variant=variant,layout=layout):
                    script='current_layout() { printf "%s" '+shlex.quote(layout)+'; }\n'+functions+'\nprint_status_json\n'
                    result=subprocess.run(payload_installed_argv(['/bin/sh','-eu','-c',script]),text=True,capture_output=True,timeout=5)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(json.loads(result.stdout),{
                        'text':values['WAYBAR_BUTTON_KEYBOARD_'+language+'_ICON_GLYPH'],
                        'tooltip':'Keyboard layout: '+label,'class':layout})

    def test_native_tomat_icon_config_has_exact_catalog_glyphs(self):
        mod = load('usr/local/libexec/labwc-tomat')
        data = mod.validate_config(RENDER(payload_read_text(SKEL / 'tomat/config.toml'), VALUES))
        for name in ('work', 'break', 'long_break', 'play', 'pause', 'stop'):
            self.assertEqual(data['display']['icons'][name], VALUES[f'WAYBAR_BUTTON_TOMAT_{name.upper()}_ICON_GLYPH'])
        self.assertEqual(data['display']['text_format'], '{icon} {time}')


    def test_native_gtk_state_colors_symbolic_painting_and_tray_context(self):
        if not shutil.which('xvfb-run') or not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3/Xvfb unavailable')
        template = payload_read_text(SKEL / 'waybar/style.css.tmpl')
        with tempfile.TemporaryDirectory() as work:
            work = Path(work); (work/'icons').mkdir()
            for path in (SKEL/'waybar/icons').glob('*.svg*'):
                (work/'icons'/path.name.removesuffix('.tmpl')).write_text(RENDER(payload_read_text(path), VALUES))
            # Different states get different sentinels, so accidental cascade
            # coupling cannot pass merely because defaults happen to match.
            mutated = dict(VALUES)
            names = sorted(name for name in VALUES if name.endswith('_ICON_COLOR')
                           and '__THEME_'+name+'__' in template)
            for number,name in enumerate(names,1):
                mutated[name] = '#%06x' % (0x102030 + number*1031)
            for variant,values in (('default',VALUES),('independent',mutated)):
                css = rendered_assets(profiles()[0], theme_items=tuple(sorted(values.items())))['style.css']
                css = css.replace('url("icons/','url("'+str(work/'icons')+'/')
                css_path = work/(variant+'.css'); css_path.write_text(css)
                value_path = work/(variant+'.json'); value_path.write_text(json.dumps(values))
                result = subprocess.run(payload_installed_argv(['xvfb-run','-a',sys.executable,'-I',
                    str(SEED/'tests/fixtures/waybar-icon-colors-gtk.py'),str(css_path),str(value_path)]),
                    text=True,capture_output=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report['native_gtk_icon_cases'],64)


class TomatMarkupTests(unittest.TestCase):
    def setUp(self):
        self.mod = load('usr/local/libexec/labwc-tomat')

    def test_all_native_phase_classes_and_state_glyphs_have_independent_colors(self):
        for state, (glyph, color) in self.mod.STATUS_ICONS.items():
            marker = 'stop' if state == 'idle' else 'pause' if state.endswith('-paused') else 'play'
            state_glyph, state_color = self.mod.STATE_ICONS[marker]
            value = {'text': glyph + ' 25:00 ' + state_glyph, 'class': state, 'tooltip': '<unsafe>&"', 'percentage': 25}
            result = self.mod.status_markup(value)
            root = tree(result['text'])
            self.assertEqual(plain(result['text']), value['text'])
            self.assertEqual(len(root), 2)
            self.assertEqual(root[0].attrib['foreground'], color)
            self.assertEqual(root[1].attrib['foreground'], state_color)
            self.assertEqual(plain(result['tooltip']), value['tooltip'])
            self.assertNotIn('<unsafe>', result['tooltip'])
            self.assertEqual(result['percentage'], 25)

    def test_markup_injection_and_invalid_xml_are_rendered_only_as_text(self):
        value = {'text': '<span foreground="red">not an icon</span>&\x00\ud800', 'class':'work', 'tooltip':'<b>no</b>'}
        result = self.mod.status_markup(value)
        self.assertEqual(plain(result['text']), value['text'][:-2] + '\ufffd\ufffd')
        self.assertEqual(len(tree(result['text'])), 0)
        self.assertEqual(plain(result['tooltip']), '<b>no</b>')

    def test_invalid_protocol_fields_are_rejected(self):
        invalid = (None, [], {}, {'text':'ok','class':['work']}, {'text':False,'class':'work'},
                   {'text':'ok','class':'new-unknown-state'}, {'text':'x'*(self.mod.MAX_STATUS+1),'class':'work'},
                   {'text':'ok','class':'work','tooltip':None})
        for value in invalid:
            with self.subTest(value=repr(value)[:80]), self.assertRaises(self.mod.Error):
                self.mod.status_markup(value)
        for pct in (True, '20', -1, 101, float('nan'), float('inf'), 10**1000):
            with self.subTest(percentage=repr(pct)[:40]), self.assertRaises(self.mod.Error):
                self.mod.status_markup({'text':'ok','class':'work','percentage':pct})
        for color in ('red', '#123', "#123abc' size='999", 'inherit'):
            with self.assertRaises(self.mod.Error): self.mod.icon_markup('safe', color)

    def test_literal_custom_glyphs_do_not_become_regular_expressions(self):
        # Catalog glyph validation is stricter; this also exercises the runtime
        # trust boundary independently of installation.
        self.mod.STATUS_ICONS['work'] = ('<x>&.*', '#123abc')
        result = self.mod.status_markup({'text':'<x>&.* 25:00 / other', 'class':'work'})
        self.assertEqual(plain(result['text']), '<x>&.* 25:00 / other')
        self.assertEqual(len(tree(result['text'])), 1)

    def test_native_pango_accepts_all_emitted_formats_and_escaped_tooltips(self):
        library = ctypes.util.find_library('pango-1.0')
        if not library: self.skipTest('native Pango unavailable')
        pango = C.CDLL(library); glib = C.CDLL(ctypes.util.find_library('glib-2.0'))
        fn = pango.pango_parse_markup
        fn.restype = C.c_int
        fn.argtypes = [C.c_char_p, C.c_int, C.c_uint32, C.POINTER(C.c_void_p), C.POINTER(C.c_void_p), C.c_void_p, C.POINTER(C.c_void_p)]
        pango.pango_attr_list_unref.argtypes = [C.c_void_p]
        glib.g_free.argtypes = [C.c_void_p]; glib.g_error_free.argtypes = [C.c_void_p]
        strings = []
        for state, (glyph, _) in self.mod.STATUS_ICONS.items():
            value = self.mod.status_markup({'text':glyph+' 25:00 & <data>', 'class':state, 'tooltip':'<unsafe>&'})
            strings.extend([value['text'], value['tooltip']])
        for bar in bars():
            for name in ('cpu','disk','memory','battery','pulseaudio'):
                strings.extend(value for key,value in bar[name].items() if key.startswith('format') and isinstance(value,str))
        for value in strings:
            attrs = C.c_void_p(); text = C.c_void_p(); error = C.c_void_p()
            ok = fn(value.encode(), -1, 0, C.byref(attrs), C.byref(text), None, C.byref(error))
            try:
                self.assertTrue(ok, value)
                self.assertEqual(C.string_at(text).decode(), plain(value))
            finally:
                if attrs.value: pango.pango_attr_list_unref(attrs)
                if text.value: glib.g_free(text)
                if error.value: glib.g_error_free(error)


class FzfIconTests(unittest.TestCase):
    def setUp(self):
        self.mod = load('usr/local/bin/labwc-fzf-menu')

    def test_default_inheritance_preserves_uncolored_choice_protocol(self):
        displayed = self.mod.display_choices(['Back','Exit','custom input'], 'Choose')
        offered, accepted, ansi = self.mod.color_choices(displayed, 'Choose')
        self.assertFalse(ansi)
        self.assertEqual(offered, list(displayed))
        self.assertEqual(accepted, displayed)
        self.assertNotIn('\x1b', ''.join(offered))

    def test_every_management_icon_accepts_an_independent_color(self):
        for name in VALUES:
            if name.startswith('FZF_MANAGEMENT_') and name.endswith('_ICON_COLOR'):
                with self.subTest(name=name):
                    mod = load('usr/local/bin/labwc-fzf-menu', dict(VALUES, **{name:'#123abc'}))
                    styles = list(mod.ICONS.values()) + [style for _,style in mod.TOPIC_ICONS] + [mod.icon_style_for('unclassified')]
                    self.assertEqual(sum(color == '#123abc' for _,color in styles), 1)

    def test_only_trusted_glyph_receives_generated_ansi_and_exact_selection_mapping(self):
        glyph = self.mod.ICONS['Back'][0]
        self.mod.ICONS['Back'] = (glyph, '#123abc')
        displayed = self.mod.display_choices(['Back','unsafe\x1b[31m\u202e'], 'Choose')
        offered, accepted, ansi = self.mod.color_choices(displayed, 'Choose')
        self.assertTrue(ansi)
        self.assertEqual(offered[0], '\x1b[38;2;18;58;188m'+glyph+'\x1b[39m  Back')
        self.assertNotIn('\x1b', offered[1])
        self.assertEqual(accepted[offered[0]], 'Back')
        self.assertEqual(accepted[next(iter(displayed))], 'Back')
        for output in (offered[0], next(iter(displayed))):
            with mock.patch.object(self.mod.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0,stdout=output+'\n')) as run:
                self.assertEqual(self.mod.select(['Back'], 'Choose'), (0,'Back'))
                self.assertIn('--ansi', run.call_args.args[0])
                self.assertNotIn('shell', run.call_args.kwargs)
        with mock.patch.object(self.mod.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0,stdout='\x1b[31m'+next(iter(displayed))+'\n')):
            self.assertEqual(self.mod.select(['Back'], 'Choose'), (1,None))

    def test_invalid_icon_color_and_untrusted_fzf_options_cannot_create_actions(self):
        self.mod.ICONS['Back'] = (self.mod.ICONS['Back'][0], '#123abc;execute(id)')
        with self.assertRaises(ValueError): self.mod.select(['Back'], 'Choose')
        with mock.patch.dict(os.environ, {'FZF_DEFAULT_OPTS':'--bind=enter:execute(id)', 'FZF_DEFAULT_COMMAND':'id'}):
            self.assertFalse(any(key.startswith('FZF_') for key in self.mod.safe_environment()))

    def test_real_fzf_filter_keeps_the_exact_raw_data_map(self):
        executable = shutil.which('fzf')
        if not executable: self.skipTest('native fzf unavailable')
        self.mod.ICONS['Back'] = (self.mod.ICONS['Back'][0], '#123abc')
        displayed = self.mod.display_choices(['Back','Exit'], 'Choose')
        offered, accepted, _ = self.mod.color_choices(displayed, 'Choose')
        result = subprocess.run(payload_installed_argv([executable,'--ansi','--no-sort','--filter=Back']), input='\n'.join(offered)+'\n',
            text=True, capture_output=True, env=self.mod.safe_environment(), timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(accepted[result.stdout.removesuffix('\n')], 'Back')


if __name__ == '__main__':
    unittest.main()
