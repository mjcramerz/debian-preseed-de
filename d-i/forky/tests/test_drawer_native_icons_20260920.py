"""Native application artwork contract and GTK painting; no application launch."""
from __future__ import annotations
import ctypes.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from test_native_tomat_20260920 import FORKY, SKEL, bars
from test_notifications_followup_20260920 import rendered_profile_styles

ICONS={'custom/app-terminal':('foot','Foot',(23,217,71)),
       'custom/app-files':('org.xfce.thunar','Thunar',(35,145,247)),
       'custom/app-tuta':('tuta-mail','Tuta Mail',(179,27,198)),
       'custom/app-notes':('featherpad','FeatherPad',(47,226,211)),
       'custom/app-sleek':('sleek','Sleek',(230,72,174))}


def png(color):
    def chunk(name,data):
        return struct.pack('!I',len(data))+name+data+struct.pack('!I',zlib.crc32(name+data))
    raw=(b'\0'+bytes(color)*32)*32
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',32,32,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


class NativeDrawerTests(unittest.TestCase):
    def test_both_drawers_keep_tooltips_and_owned_launch_paths_not_font_glyphs(self):
        for bar in bars():
            for module,(_,tooltip,_) in ICONS.items():
                entry=bar[module]
                self.assertEqual(entry['format'],' ')
                self.assertEqual(entry['tooltip-format'],tooltip)
                self.assertIn('--property=PartOf=labwc-session.target',entry['on-click'])
                self.assertIn('--property=KillMode=control-group',entry['on-click'])
                self.assertEqual(entry['align'],0.5)
                self.assertIn(module,bar['group/apps']['modules'])

    def test_native_artwork_is_present_above_both_background_layers(self):
        css=(SKEL/'waybar/style.css.tmpl').read_text()
        self.assertIn('-gtk-icon-theme: "hicolor";',css)
        for module,(icon,_,_) in ICONS.items():
            selector='#'+module.replace('/','-')
            for suffix in ('',':hover'):
                matches=[body for selectors,body in re.findall(r'([^{}]+)\{([^{}]*)\}',css)
                         if re.sub(r'/\*.*?\*/','',selectors,flags=re.S).strip()==selector+suffix]
                self.assertEqual(len(matches),1)
                rule=matches[0]
                self.assertIn('-gtk-icontheme("'+icon+'")',rule)
                self.assertNotIn('-gtk-recolor',rule)
                if suffix:self.assertIn('linear-gradient',rule)
            self.assertEqual(css.count('-gtk-icontheme("'+icon+'")'),2)

    def test_installed_verifier_checks_decoding_and_config_instead_of_silent_fallback(self):
        source=(FORKY/'scripts/desktop/verify.sh').read_text()
        self.assertIn('icon_theme.set_custom_theme("hicolor")',source)
        self.assertIn('icon_theme.has_icon(icon)',source)
        self.assertIn('icon_theme.load_icon(icon, 32, Gtk.IconLookupFlags.FORCE_SIZE)',source)
        for icon,_,_ in ICONS.values():self.assertIn('"'+icon+'"',source)
        # Do not start installing third-party amd64-only apps on other targets.
        self.assertIn('if (arch != "amd64" or sys.argv[3] == "0") and module in {"custom/app-tuta", "custom/app-sleek"}',source)

    def test_narrow_verifier_is_called_after_user_config_without_enabling_broad_checks(self):
        role=(FORKY/'scripts/desktop/labwc.sh').read_text().split('run_desktop_late_command() {',1)[1]
        self.assertLess(role.index('  desktop_install_user_config'),role.index('  desktop_verify_native_drawer_icons'))
        self.assertNotIn('  desktop_verify_target_staging\n',role)
        source=(FORKY/'scripts/desktop/verify.sh').read_text()
        self.assertIn('desktop_verify_native_menus() {\n  desktop_verify_native_drawer_icons',source)
        function=source.split('desktop_verify_native_drawer_icons() {',1)[1].split('desktop_verify_native_menus()',1)[0]
        python_code=function.split("/usr/bin/python3 -I -B -c '\n",1)[1].rsplit("\n' ",1)[0]
        compile(python_code,'<installed-drawer-verifier>','exec')
        self.assertIn('installer_selected_class_reference_is_selected addon/software',function)

    def test_notification_lock_and_power_palette_is_explicit(self):
        css=(SKEL/'waybar/style.css.tmpl').read_text()
        for selector,rgba in (('notifications','236, 184, 96, 0.14'),('lock','203, 213, 225, 0.14'),('power','248, 113, 113, 0.16')):
            self.assertIn('#custom-'+selector+' {\n  background: rgba('+rgba+');',css)
        self.assertIn('#custom-notifications:hover {\n  background: @amber;',css)
        self.assertIn('#custom-lock:hover {\n  background: linear-gradient(135deg, rgba(226, 232, 240, 0.84), rgba(148, 163, 184, 0.84));',css)
        self.assertIn('#custom-power:hover {\n  background: linear-gradient(135deg, rgba(236, 184, 96, 0.92), rgba(242, 159, 103, 0.92), rgba(248, 113, 113, 0.92));',css)

    def test_gtk_native_lookup_and_hover_paint_at_two_scales(self):
        if not shutil.which('xvfb-run') or not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3 / Xvfb unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);theme=root/'icons/hicolor';images=theme/'32x32/apps';images.mkdir(parents=True)
            (theme/'index.theme').write_text('[Icon Theme]\nName=hicolor\nDirectories=32x32/apps\n\n[32x32/apps]\nSize=32\nType=Fixed\nContext=Applications\n')
            for icon,_,color in ICONS.values():(images/(icon+'.png')).write_bytes(png(color))
            css=root/'style.css';css.write_text(next(iter(rendered_profile_styles().values())))
            for scale in (1,2):
                result=subprocess.run(['xvfb-run','-a','/usr/bin/python3','-I','-B',
                    str(FORKY/'tests/fixtures/waybar-native-icons-gtk.py'),str(css),str(scale)],
                    env={**os.environ,'GDK_BACKEND':'x11','NO_AT_BRIDGE':'1','XDG_DATA_HOME':str(root),'GDK_SCALE':str(scale)},
                    text=True,capture_output=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(json.loads(result.stdout)['native_icon_paint_cases'],20)



class InstalledDrawerVerifierTests(unittest.TestCase):
    """Execute the installed check's logic over real temporary configs/icons API mocks."""
    def setUp(self):
        import ast
        import types
        from unittest import mock
        self.mock=mock;self.types=types
        source=(FORKY/'scripts/desktop/verify.sh').read_text()
        function=source.split('desktop_verify_native_drawer_icons() {',1)[1].split('desktop_verify_native_menus()',1)[0]
        code=function.split("/usr/bin/python3 -I -B -c '\n",1)[1].rsplit("\n' ",1)[0]
        tree=ast.parse(code)
        tree.body=[node for node in tree.body if not isinstance(node,(ast.Import,ast.ImportFrom))]
        self.code=compile(tree,'<installed-drawer-verifier>','exec')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.configs=[]
        for relative in ('etc/skel-desktop','home/desktop'):
            config=self.root/relative/'.config/waybar';config.mkdir(parents=True)
            (config/'config').write_text(json.dumps(bars()))
            (config/'style.css').write_text((SKEL/'waybar/style.css.tmpl').read_text())
            self.configs.append(config)

    def execute(self,arch='amd64',software='1',missing=None):
        icon_theme=self.mock.Mock()
        icon_theme.has_icon.side_effect=lambda name:name!=missing
        gtk=self.types.SimpleNamespace(IconTheme=self.types.SimpleNamespace(new=lambda:icon_theme),
                                       IconLookupFlags=self.types.SimpleNamespace(FORCE_SIZE=16))
        scope={'json':json,'Path':lambda path:self.root/path.lstrip('/'),
               'pwd':self.types.SimpleNamespace(getpwnam=lambda user:self.types.SimpleNamespace(pw_uid=1000,pw_dir='/home/desktop')),
               'subprocess':self.types.SimpleNamespace(check_output=lambda *a,**kw:arch+'\n'),
               'sys':self.types.SimpleNamespace(argv=['check','/home/desktop','desktop',software]),
               'gi':self.types.SimpleNamespace(require_version=lambda *args:None),'Gtk':gtk}
        import contextlib,io
        with contextlib.redirect_stdout(io.StringIO()):exec(self.code,scope)
        return [call.args[0] for call in icon_theme.load_icon.call_args_list]

    def test_selected_amd64_bundle_requires_all_five_decodable_icons(self):
        self.assertEqual(set(self.execute()),{value[0] for value in ICONS.values()})
        with self.assertRaisesRegex(SystemExit,'not installed'):self.execute(missing='sleek')

    def test_unselected_or_other_architecture_does_not_add_package_requirements(self):
        expected={'foot','org.xfce.thunar','featherpad'}
        self.assertEqual(set(self.execute(software='0',missing='sleek')),expected)
        self.assertEqual(set(self.execute(arch='arm64',missing='tuta-mail')),expected)

    def test_corrupt_account_drawer_is_not_hidden_by_valid_skeleton(self):
        path=self.configs[1]/'config';data=json.loads(path.read_text())
        data[0]['custom/app-terminal']['format']='font-glyph';path.write_text(json.dumps(data))
        with self.assertRaisesRegex(SystemExit,'misconfigured'):self.execute()

    def test_missing_hover_artwork_is_rejected(self):
        path=self.configs[0]/'style.css';path.write_text(path.read_text().replace('-gtk-icontheme("foot")','none',1))
        with self.assertRaisesRegex(SystemExit,'survive hover'):self.execute()

    def test_invalid_software_policy_cannot_silently_skip_icons(self):
        with self.assertRaisesRegex(SystemExit,'software policy'):self.execute(software='yes')


if __name__=='__main__':unittest.main()
