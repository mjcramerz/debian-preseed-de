"""Native multi-bar and deterministic Fuzzel contracts; no host/display changes."""
from pathlib import Path
import json
import re
import subprocess
import shlex
import tempfile
import unittest
from fuzzel_fixture import geometry_environment
from payload_fixture import installed_argv, read_text
from theme_fixture import render_theme_defaults
from test_desktop_sandbox import FuzzelOutputSizingTests as _Fixture
from waybar_fixture import FORKY, TARGET, profiles, rendered_assets


class FuzzelSelectionTests(unittest.TestCase):
    setUp = _Fixture.setUp
    invoke = _Fixture.invoke

    def test_three_classes_supply_every_geometry_argument_for_every_mode(self):
        cli = {'HORIZONTAL_PADDING':'horizontal-pad','VERTICAL_PADDING':'vertical-pad',
               'INNER_PADDING':'inner-pad','LINE_HEIGHT':'line-height',
               'BORDER_WIDTH':'border-width','BORDER_RADIUS':'border-radius'}
        values = geometry_environment()
        for mode, prefix, filename in (('launcher','LAUNCHER','fuzzel.ini'),
                                       ('menu','MENU','menu.ini'),
                                       ('computer-management','MENU','computer-management.ini')):
            for output, cls in ((None,'DEFAULT'),('eDP-1','INTERNAL'),('DP-1','EXTERNAL')):
                with self.subTest(mode=mode, cls=cls):
                    result,args=self.invoke(mode,output=output)
                    self.assertEqual(result.returncode,0,result.stderr.decode())
                    self.assertIn('--config='+str(self.config/filename),args)
                    for key, flag in cli.items():
                        self.assertIn('--'+flag+'='+values[f'FUZZEL_{cls}_{key}'],args)
                    for key in ('WIDTH','LINES'):
                        self.assertIn('--'+key.lower()+'='+values[f'FUZZEL_{prefix}_{cls}_{key}'],args)
                    font=next(arg for arg in args if arg.startswith('--font='))
                    self.assertTrue(all(part.endswith(':size='+values[f'FUZZEL_{cls}_FONT_SIZE'])
                                        for part in font.removeprefix('--font=').split(',')))
                    self.assertEqual([arg for arg in args if arg.startswith('--output=')],
                                     [] if output is None else ['--output='+output])

    def test_keyboard_bar_and_management_have_identical_visual_arguments(self):
        visual_flags=('--font=', '--width=', '--lines=', '--horizontal-pad=',
                      '--vertical-pad=', '--inner-pad=', '--line-height=',
                      '--border-width=', '--border-radius=')
        reference=None
        for mode in ('launcher','menu','computer-management'):
            for output in (None,'eDP-1','DP-1'):
                with self.subTest(mode=mode,output=output):
                    result,args=self.invoke(mode,output=output)
                    self.assertEqual(result.returncode,0,result.stderr.decode())
                    visual=tuple(arg for arg in args if arg.startswith(visual_flags))
                    self.assertEqual(len(visual),len(visual_flags))
                    if reference is None:
                        reference=visual
                    self.assertEqual(visual,reference)

    def test_install_validation_rejects_drift_between_entry_points(self):
        source=render_theme_defaults(read_text(FORKY/'scripts/desktop/detect.sh'))
        start=source.index('desktop_validate_fuzzel_geometry() (\n')
        end=source.index('\n)\n',start)+3
        function=source[start:end]
        script='''set -eu
desktop_fatal() { printf '%s\\n' "$*" >&2; exit 2; }
desktop_validate_uint_range() { [ "$2" -ge "$3" ] && [ "$2" -le "$4" ]; }
'''+function+'\ndesktop_validate_fuzzel_geometry\n'
        environment={'PATH':'/usr/bin:/bin',**geometry_environment()}
        for change, expected in (({},0),
                                 ({'FUZZEL_DEFAULT_FONT_SIZE':'15'},2),
                                 ({'FUZZEL_LAUNCHER_INTERNAL_WIDTH':'48'},2),
                                 ({'FUZZEL_MENU_EXTERNAL_LINES':'22'},2)):
            with self.subTest(change=change):
                result=subprocess.run(installed_argv(['/bin/sh','-c',script]),
                                      env=environment|change,capture_output=True,text=True)
                self.assertEqual(result.returncode,expected,result.stderr)
                if change:
                    self.assertIn('Fuzzel geometry differs',result.stderr)

    def test_unknown_is_deliberately_default_not_external(self):
        result,args=self.invoke('launcher',extra_environment={
            'FUZZEL_LAUNCHER_DEFAULT_WIDTH':'57','FUZZEL_LAUNCHER_EXTERNAL_WIDTH':'99',
            'FUZZEL_DEFAULT_FONT_SIZE':'11','FUZZEL_EXTERNAL_FONT_SIZE':'22'})
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertIn('--width=57',args)
        self.assertNotIn('--width=99',args)
        self.assertFalse(any(arg.startswith('--output=') for arg in args))
        self.assertIn(':size=11',next(arg for arg in args if arg.startswith('--font=')))

    def test_named_waybar_class_selects_geometry_without_fabricating_output(self):
        for mode, prefix in (('launcher','LAUNCHER'),('menu','MENU'),
                             ('computer-management','MENU')):
            for cls in ('INTERNAL','EXTERNAL'):
                with self.subTest(mode=mode, cls=cls):
                    result,args=self.invoke(mode,extra_environment={'LABWC_FUZZEL_OUTPUT_CLASS':cls})
                    self.assertEqual(result.returncode,0,result.stderr.decode())
                    self.assertIn('--width='+self.environment[f'FUZZEL_{prefix}_{cls}_WIDTH'],args)
                    self.assertIn('--lines='+self.environment[f'FUZZEL_{prefix}_{cls}_LINES'],args)
                    self.assertIn(':size='+self.environment[f'FUZZEL_{cls}_FONT_SIZE'],
                                  next(arg for arg in args if arg.startswith('--font=')))
                    self.assertFalse(any(arg.startswith('--output=') for arg in args))

    def test_actual_output_wins_over_bar_class_and_invalid_classes_fail_closed(self):
        for options, output in (((), 'eDP-1'), (('--output=DP-1',), None)):
            result,args=self.invoke('launcher',*options,output=output,
                                    extra_environment={'LABWC_FUZZEL_OUTPUT_CLASS':'EXTERNAL' if output else 'INTERNAL'})
            self.assertEqual(result.returncode,0,result.stderr.decode())
            cls='INTERNAL' if output else 'EXTERNAL'
            self.assertIn('--width='+self.environment[f'FUZZEL_LAUNCHER_{cls}_WIDTH'],args)
        for value in ('external', 'INTERNAL;id', 'INTERNAL\nEXTERNAL'):
            with self.subTest(value=value):
                result,args=self.invoke('launcher',extra_environment={'LABWC_FUZZEL_OUTPUT_CLASS':value})
                self.assertEqual(result.returncode,2)
                self.assertEqual(args,[])

    def test_canonical_prefixes_and_external_connectors(self):
        for output, cls in (('eDP-1','INTERNAL'),('LVDS-1','INTERNAL'),('DSI-1','INTERNAL'),
                            ('DP-1','EXTERNAL'),('HDMI-A-1','EXTERNAL')):
            with self.subTest(output=output):
                result,args=self.invoke('launcher',output=output)
                self.assertEqual(result.returncode,0,result.stderr.decode())
                self.assertIn('--width='+self.environment[f'FUZZEL_LAUNCHER_{cls}_WIDTH'],args)

    def test_invalid_shared_runtime_prefix_policy_does_not_launch(self):
        for value in ('*', '?', 'eDP [a-z]', 'eDP;id', 'eDP\nLVDS', 'eDP\tLVDS', ' ', '-eDP'):
            with self.subTest(value=value):
                result,args=self.invoke('launcher',output='eDP-1',extra_environment={
                    'LABWC_OUTPUT_INTERNAL_PREFIXES':value})
                self.assertEqual(result.returncode,2)
                self.assertEqual(args,[])

    def test_explicit_output_wins_over_even_invalid_environment(self):
        for options in (('--output','eDP-1'),('--output=eDP-1',),('-o','eDP-1'),('-oeDP-1',)):
            with self.subTest(options=options):
                result,args=self.invoke('launcher',*options,output='bad;environment')
                self.assertEqual(result.returncode,0,result.stderr.decode())
                self.assertEqual([a for a in args if a.startswith('--output=')],['--output=eDP-1'])

    def test_prompt_value_is_not_parsed_as_an_output_option(self):
        result,args=self.invoke('menu','--dmenu','--prompt','--output=eDP-1',output='DP-1')
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertEqual(args[args.index('--prompt')+1],'--output=eDP-1')
        self.assertIn('--width='+self.environment['FUZZEL_MENU_EXTERNAL_WIDTH'],args)
        self.assertEqual(args[-1],'--output=DP-1')

    def test_invalid_or_duplicate_output_does_not_launch_a_child(self):
        for options in (('--output',),('--output=',),('--output=../eDP-1',),
                        ('--output=eDP-1;id',),('--output='+('a'*129),),
                        ('--output=eDP-1','-o','DP-1')):
            with self.subTest(options=options):
                result,args=self.invoke('launcher',*options)
                self.assertEqual(result.returncode,2)
                self.assertEqual(args,[])

    def test_profile_geometry_and_config_cannot_be_overridden_by_native_flags(self):
        for option in ('--width=99','-w99','--font=x','-fX','--config=/tmp/other',
                       '--dpi-aware=no','--line-height=1px','--border-width=0',
                       '--horizontal-pad=0','--inner-pad=0','--lines=5','--border-radius=0'):
            with self.subTest(option=option):
                result,args=self.invoke('launcher',option)
                self.assertEqual(result.returncode,2)
                self.assertEqual(args,[])

    def test_invalid_selected_geometry_is_not_evaluated(self):
        marker=self.root/'not-created'
        for value in ('', '09', '-1','99999999999', f'$(touch {marker})', '9;false'):
            with self.subTest(value=value):
                result,args=self.invoke('launcher',output='eDP-1',extra_environment={'FUZZEL_INTERNAL_FONT_SIZE':value})
                self.assertEqual(result.returncode,2)
                self.assertEqual(args,[])
                self.assertFalse(marker.exists())

    def test_management_palette_is_independent_of_monitor_and_log_scope(self):
        result,args=self.invoke('menu','--dmenu',output='eDP-1',extra_environment={
            'LABWC_FUZZEL_PALETTE':'computer-management','LABWC_FUZZEL_LOG_SCOPE':'android-debug-bridge'})
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.assertIn('--config='+str(self.config/'computer-management.ini'),args)
        self.assertIn('--width='+self.environment['FUZZEL_MENU_INTERNAL_WIDTH'],args)


del _Fixture


class NativeLayoutTests(unittest.TestCase):
    def test_templates_are_exactly_the_requested_single_file_layouts(self):
        root=TARGET/'etc/skel-desktop/.config'
        self.assertEqual({p.name for p in (root/'waybar').iterdir() if p.is_file()},
                         {'config.tmpl','style.css.tmpl',*(name+'-menu.xml.tmpl' for name in
                                                         ('audio','calendar','notifications','power','tomat'))})
        self.assertEqual({p.name for p in (root/'fuzzel').iterdir()},
                         {'base.ini.tmpl','fuzzel.ini.tmpl','menu.ini.tmpl','computer-management.ini.tmpl'})
        base=(root/'fuzzel/base.ini.tmpl').read_text()
        self.assertIn('dpi-aware=yes',base)
        self.assertNotRegex(base,r'(?m)^(font|width|lines|horizontal-pad|vertical-pad|inner-pad|line-height)=')
        management=(root/'fuzzel/computer-management.ini.tmpl').read_text()
        self.assertIn('include=~/.config/fuzzel/menu.ini',management)
        self.assertNotIn('[border]',management)

    def test_exactly_two_native_bars_no_duplicate_keys_and_disjoint_outputs(self):
        for profile in profiles():
            with self.subTest(profile=profile.name):
                assets=rendered_assets(profile)  # the real renderer also checks duplicate keys
                internal,external=json.loads(assets['config'])
                self.assertEqual([internal['name'],external['name']],['internal','external'])
                self.assertIn('eDP-1',internal['output'])
                self.assertNotIn('*',internal['output'])
                self.assertEqual(external['output'],['!'+name for name in internal['output']]+['*'])
                self.assertEqual(len(internal['output']),len(set(internal['output'])))
                for bar, cls in ((internal,'INTERNAL'),(external,'EXTERNAL')):
                    self.assertIn('group/quick-controls',bar)
                    self.assertNotIn('group/quick-controls-internal',bar)
                    click=bar['custom/launcher']['on-click']
                    self.assertIn('--setenv=LABWC_FUZZEL_OUTPUT_CLASS='+cls,click)
                    self.assertNotIn('--setenv=WAYBAR_OUTPUT_NAME',click)
                self.assertNotIn('@import',assets['style.css'])

    def test_every_profile_gives_all_entry_points_identical_geometry(self):
        for profile in profiles():
            with self.subTest(profile=profile.name):
                values=geometry_environment(profile.name)
                for key, expected in {'FONT_SIZE':'19','HORIZONTAL_PADDING':'16',
                                      'VERTICAL_PADDING':'12','INNER_PADDING':'8',
                                      'LINE_HEIGHT':'32','BORDER_WIDTH':'2',
                                      'BORDER_RADIUS':'14'}.items():
                    self.assertEqual({values[f'FUZZEL_{cls}_{key}'] for cls in
                                      ('INTERNAL','EXTERNAL','DEFAULT')},{expected})
                for mode in ('LAUNCHER','MENU'):
                    self.assertEqual([int(values[f'FUZZEL_{mode}_{cls}_WIDTH']) for cls in
                                      ('INTERNAL','EXTERNAL','DEFAULT')],[86,86,86])
                    self.assertEqual([int(values[f'FUZZEL_{mode}_{cls}_LINES']) for cls in
                                      ('INTERNAL','EXTERNAL','DEFAULT')],[18,18,18])

    def test_nonstandard_detected_internal_name_is_not_lost_to_the_wildcard(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile=Path(tmp)/'profile.env'
            profile.write_text(profiles()[0].read_text()+'\nLABWC_DETECTED_INTERNAL_OUTPUTS="eDP-89 eDP-89 DSI-67"\n')
            internal,external=json.loads(rendered_assets(profile)['config'])
            self.assertEqual(internal['output'].count('eDP-89'),1)
            self.assertIn('DSI-67',internal['output'])
            self.assertIn('!eDP-89',external['output'])
            self.assertIn('!DSI-67',external['output'])

    def test_invalid_shared_classification_stops_before_publishing(self):
        for value in ('', '   ', '.eDP', 'eDP *', 'eDP;id', 'eDP\nLVDS', 'x'*33):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                profile=Path(tmp)/'profile.env'
                profile.write_text(profiles()[0].read_text()+'\nLABWC_OUTPUT_INTERNAL_PREFIXES='+shlex.quote(value)+'\n')
                with self.assertRaises(subprocess.CalledProcessError) as error:
                    rendered_assets(profile)
                self.assertEqual(error.exception.stdout,b'')

    def test_all_profile_geometry_and_themes_are_wired(self):
        root=TARGET/'etc/skel-desktop/.config/waybar'
        text='\n'.join(p.read_text() for p in root.glob('*.tmpl'))
        keys=[line.split('\t')[0] for line in (FORKY/'scripts/desktop/waybar-geometry.tsv').read_text().splitlines()
              if line and not line.startswith('#')]
        for profile in profiles():
            source=profile.read_text()
            for cls in ('INTERNAL','EXTERNAL'):
                for key in keys:
                    self.assertEqual(len(re.findall(r'^LABWC_WAYBAR_'+cls+'_'+key+r'=',source,re.M)),1)
            self.assertEqual(len(geometry_environment(profile.name)),34)  # 33 dimensions plus canonical policy
        self.assertNotRegex(text,r'font-weight:\s*(?:\d+|bold|normal)\b')
        self.assertNotRegex(text,r'border-style:\s*(?:solid|none|dashed)\b')
        self.assertNotRegex(text,r'weight=[\'"](?:bold|[0-9]+)[\'"]')
        for cls in ('INTERNAL','EXTERNAL'):
            self.assertIn(f'__THEME_WAYBAR_{cls}_FONT_WEIGHT_EMPHASIS__',text)
            self.assertIn(f'__THEME_WAYBAR_{cls}_BORDER_STYLE__',text)

    def test_service_and_reload_keep_one_native_process_and_executable_identity(self):
        unit=read_text(TARGET/'etc/skel-desktop/.config/systemd/user/waybar.service')
        starts=re.findall(r'^ExecStart=(.*)$',unit,re.M)
        self.assertEqual(starts,['/usr/bin/waybar -c %h/.config/waybar/config -s %h/.config/waybar/style.css'])
        self.assertNotIn('labwc-panel-run',unit)
        check=read_text(TARGET/'usr/local/libexec/labwc-session-check')
        self.assertIn('.samefile("/usr/bin/waybar")',check)
        self.assertIn('pidfd_send_signal',check)
        policy=read_text(TARGET/'etc/apparmor.d/labwc-session')
        waybar=policy.split('profile waybar ',1)[1].split('\nprofile ',1)[0]
        self.assertNotIn('peer=labwc-panel-run',waybar)
        self.assertIn('ptrace (readby) peer=labwc-session-check',waybar)


if __name__ == '__main__':
    unittest.main()
