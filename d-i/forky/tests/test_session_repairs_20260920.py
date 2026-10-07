#!/usr/bin/env python3
"""Scoped session repairs: no target service activation, package build or GPU.

Real inotify/child lifecycle and private D-Bus are exercised. The native swaybg
process is a fixture, not a claim of rendered first-frame/physical-input tests.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import installed_script
from payload_fixture import read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import argparse
import ctypes.util
import importlib.machinery
import importlib.util
import json
import os
import pwd
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
BIN = TARGET / 'usr/local/bin'
LIBEXEC = TARGET / 'usr/local/libexec'
AA = TARGET / 'etc/apparmor.d'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(installed_script(path)))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


WALL = load('wallpaper_repair_test', LIBEXEC / 'labwc-wallpaper-control')
NOTIFY = load('notification_repair_test', LIBEXEC / 'labwc-notification-send')


class WallpaperStateTests(unittest.TestCase):
    def setUp(self):
        # /tmp is deliberately rejected by production's trusted ancestor check.
        self.temporary = tempfile.TemporaryDirectory(prefix='.wall-test-', dir=Path(pwd.getpwuid(os.getuid()).pw_dir))
        self.root = Path(self.temporary.name)
        self.state = WALL.State(str(self.root))
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.state.close)

    def test_atomic_save_and_private_modes(self):
        with mock.patch.object(WALL, 'image_path', side_effect=lambda value, home: value):
            self.state.save('/fixture/one.png')
            self.state.save('/fixture/two.png')
            self.assertEqual(self.state.current(), '/fixture/two.png')
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.state.path / 'wallpaper').st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.state.path).st_mode), 0o700)
        self.assertEqual(sorted(p.name for p in self.state.path.iterdir()), ['.wallpaper.lock', 'wallpaper'])

    def test_symlink_destination_never_changes_target(self):
        target = self.root / 'victim'
        target.write_text('untouched')
        (self.state.path / 'wallpaper').symlink_to(target)
        with mock.patch.object(WALL, 'image_path', return_value='/fixture/one.png'):
            with self.assertRaises(ValueError): self.state.save('/fixture/one.png')
        self.assertEqual(render_theme_defaults(payload_read_text(target)), 'untouched')

    def test_hardlinked_state_rejected(self):
        victim = self.root / 'victim'
        victim.write_text('not wallpaper')
        os.link(victim, self.state.path / 'wallpaper')
        with self.assertRaises(ValueError): self.state.current()

    def test_fifo_does_not_block(self):
        os.mkfifo(self.state.path / 'wallpaper', 0o600)
        start = time.monotonic()
        with self.assertRaises(ValueError): self.state.current()
        self.assertLess(time.monotonic() - start, 1)

    def test_invalid_home_and_redirected_directory(self):
        for bad in ('/', 'relative', '/home/../tmp', '/home/invalid\nname'):
            with self.subTest(home=bad), self.assertRaises(ValueError): WALL.State(bad)
        other = self.root / 'other'
        other.mkdir()
        fake = self.root / 'fake'
        fake.symlink_to(other, target_is_directory=True)
        with self.assertRaises(OSError): WALL.State(str(fake))

    def test_interspersed_save_options(self):
        with mock.patch.object(sys, 'argv', ['helper', 'save', '--quiet', '/fixture/a.png']), \
             mock.patch.dict(os.environ, HOME=str(self.root)), \
             mock.patch.object(WALL, 'image_path', side_effect=lambda value, home: value):
            self.assertEqual(WALL.main(), 0)

    def test_apply_is_start_not_restart(self):
        with mock.patch.object(sys, 'argv', ['helper', 'save', '--apply', '/fixture/a.png']), \
             mock.patch.dict(os.environ, HOME=str(self.root), LABWC_SESSION_OWNER='desktop'), \
             mock.patch.object(WALL, 'image_path', side_effect=lambda value, home: value), \
             mock.patch.object(WALL.subprocess, 'run') as run:
            self.assertEqual(WALL.main(), 0)
            self.assertEqual(run.call_args.args[0], ['/usr/bin/systemctl', '--user', '--no-block', 'start', 'swaybg.service'])

    def test_personal_pictures_and_gallery_are_persistent_but_other_paths_are_rejected(self):
        gallery = self.root / 'gallery'
        gallery.mkdir()
        stock = gallery / 'stock.png'
        stock.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        pictures = self.root / 'Pictures'
        (pictures / 'Holiday').mkdir(parents=True)
        personal = pictures / 'Holiday' / "my 'photo'.png"
        personal.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        private = self.root / 'private.png'
        private.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        with mock.patch.object(WALL, 'ROOT', gallery):
            self.state.save(str(stock))
            self.assertEqual(self.state.current(), str(stock))
            self.state.save(str(personal))
            self.assertEqual(self.state.current(), str(personal))
            with self.assertRaisesRegex(ValueError, 'managed gallery or your Pictures'):
                self.state.save(str(private))
            self.assertEqual(self.state.current(), str(personal))
            personal.chmod(0o666)
            with self.assertRaisesRegex(ValueError, 'non-executable image'):
                self.state.save(str(personal))
            personal.chmod(0o600)
            (pictures / 'Holiday').chmod(0o777)
            with self.assertRaisesRegex(ValueError, 'unsafe Pictures directory'):
                self.state.save(str(personal))


@unittest.skipUnless(os.getuid() == 0, 'root-owned fixture images require root; no target mutation')
class WallpaperLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.wall-life-', dir=Path(pwd.getpwuid(os.getuid()).pw_dir))
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        images = self.root / 'images'
        images.mkdir()
        for name in ('default', 'one', 'two', 'broken'):
            (images / (name + '.png')).write_bytes(b'\x89PNG\r\n\x1a\nfixture')
            (images / (name + '.png')).chmod(0o644)
        self.images = images
        self.events = self.root / 'events'
        stub = self.root / 'swaybg-fixture'
        stub.write_text('''#!/usr/bin/python3 -I
import json,os,signal,sys,time
from pathlib import Path
log=Path(os.environ['FIXTURE_EVENTS'])
def record(kind):
 with log.open('a') as f: f.write(json.dumps([kind,os.getpid(),sys.argv[-1]])+'\\n')
record('start')
if sys.argv[-1].endswith('/broken.png'): sys.exit(3)
def done(*_): record('stop'); sys.exit(0)
signal.signal(signal.SIGTERM,done)
while True: time.sleep(.03)
''')
        stub.chmod(0o700)
        bootstrap = self.root / 'bootstrap.py'
        bootstrap.write_text('''import os,sys
from pathlib import Path
ns={'__name__':'wallpaper_fixture','__file__':sys.argv[1]}
exec(compile(Path(sys.argv[1]).read_text(),sys.argv[1],'exec'),ns)
ns['ROOT']=Path(sys.argv[2])
real=ns['subprocess'].Popen
def popen(argv,**kw):
 assert argv[0]=='/usr/bin/swaybg',argv
 return real([sys.argv[3],*argv[1:]],**kw)
ns['subprocess'].Popen=popen
state=ns['State'](os.environ['HOME'])
try: ns['supervise'](state,str(Path(sys.argv[2])/'default.png'))
finally: state.close()
''')
        self.command = [sys.executable, '-B', str(bootstrap), str(LIBEXEC/'labwc-wallpaper-control'), str(images), str(stub)]
        self.env = {**os.environ, 'HOME': str(self.root), 'FIXTURE_EVENTS': str(self.events)}
        self.process = subprocess.Popen(payload_installed_argv(self.command), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.finish)
        self.wait_for(lambda rows: any(row[0] == 'start' for row in rows))
        # Ensure the initial candidate has passed its liveness probe.
        time.sleep(0.6)

    def finish(self):
        if self.process.poll() is None: self.process.terminate()
        self.output = self.process.communicate(timeout=5)

    def rows(self):
        return [json.loads(line) for line in render_theme_defaults(payload_read_text(self.events)).splitlines()] if payload_source_exists(self.events) else []

    def wait_for(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            rows = self.rows()
            if predicate(rows): return rows
            if self.process.poll() is not None: self.fail(self.process.communicate()[1])
            time.sleep(0.025)
        self.fail(f'fixture did not reach expected state: {self.rows()}')

    def save(self, name):
        with mock.patch.object(WALL, 'ROOT', self.images):
            state = WALL.State(str(self.root))
            try: state.save(str(self.images / (name + '.png')))
            finally: state.close()

    def test_burst_coalesces_latest_request_and_reaps_children(self):
        for i in range(24): self.save('one' if i < 23 else 'two')
        self.wait_for(lambda rows: any(r[0]=='stop' and r[2].endswith('/default.png') for r in rows))
        starts = [r for r in self.rows() if r[0]=='start']
        self.assertEqual([Path(r[2]).stem for r in starts], ['default','two'])
        self.finish()
        self.assertEqual(self.process.returncode,0,self.output)
        for _kind,pid,_path in starts:
            with self.assertRaises(ProcessLookupError): os.kill(pid,0)

    def test_bad_replacement_keeps_existing_background_and_recovers(self):
        self.save('broken')
        self.wait_for(lambda rows: any(r[2].endswith('/broken.png') for r in rows))
        time.sleep(.65)
        self.assertFalse(any(r[0]=='stop' and r[2].endswith('/default.png') for r in self.rows()))
        self.save('two')
        self.wait_for(lambda rows: any(r[0]=='stop' and r[2].endswith('/default.png') for r in rows))
        self.finish()
        self.assertIn('retaining previous background',self.output[1])

    def test_personal_selection_applies_and_restores_after_supervisor_restart(self):
        pictures = self.root / 'Pictures'
        pictures.mkdir()
        personal = pictures / 'selected.png'
        personal.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        state = WALL.State(str(self.root))
        try:
            state.save(str(personal))
            self.assertEqual(state.current(), str(personal))
        finally:
            state.close()
        self.wait_for(lambda rows: any(row[0] == 'start' and row[2] == str(personal) for row in rows))
        self.finish()
        replacement = subprocess.Popen(payload_installed_argv(self.command), env=self.env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if sum(row[0] == 'start' and row[2] == str(personal) for row in self.rows()) == 2:
                    break
                if replacement.poll() is not None:
                    self.fail(replacement.communicate()[1])
                time.sleep(0.025)
            else:
                self.fail('restarted supervisor did not restore the personal wallpaper')
        finally:
            replacement.terminate()
            _, stderr = replacement.communicate(timeout=5)
        self.assertEqual(replacement.returncode, 0, stderr)

    def test_second_supervisor_is_rejected(self):
        second = subprocess.run(payload_installed_argv(self.command), env=self.env, capture_output=True, text=True, timeout=3)
        self.assertNotEqual(second.returncode,0)
        self.assertEqual(len([r for r in self.rows() if r[0]=='start']),1)


class NotificationTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(urgency='critical',category='system.health',app_name='Health',icon='dialog-error',
                                  summary='<title>',body='<body & data>',expire_time=0)

    def test_wire_signature_markup_and_details(self):
        argv = NOTIFY.command(self.args())
        self.assertIn('susssasa{sv}i',argv)
        self.assertIn('&lt;title&gt;',argv)
        body = next(x for x in argv if '&lt;body &amp; data&gt;' in x)
        self.assertRegex(body,r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d')
        self.assertIn('system.health',body)
        self.assertEqual(argv[-1],'0')
        self.assertNotIn('--wait',argv)

    def test_rejects_invalid_category_and_nul(self):
        args=self.args();args.category='invalid\ncategory'
        with self.assertRaises(ValueError):NOTIFY.command(args)
        args=self.args();args.body='bad\0value'
        with self.assertRaises(ValueError):NOTIFY.command(args)

    @unittest.skipUnless(shutil.which('dbus-run-session') and ctypes.util.find_library('dbus-1'), 'packaged D-Bus tools required')
    def test_real_private_dbus_success_retry_and_failure(self):
        for failures,calls,status in [(0,1,0),(1,2,0),(2,2,1)]:
            with self.subTest(failures=failures):
                result=subprocess.run(payload_installed_argv(['dbus-run-session','--',sys.executable,'-B',
                    str(Path(__file__).with_name('notification_bus_fixture.py')),
                    str(LIBEXEC/'labwc-notification-send'),str(failures)]),capture_output=True,text=True,timeout=25)
                self.assertEqual(result.returncode,0,result.stderr)
                report=json.loads(result.stdout)
                self.assertEqual(report['returncode'],status,report)
                self.assertEqual(report['calls'],calls,report)
                self.assertEqual(report['signatures'],['susssasa{sv}i']*calls)


class IntegrationTests(unittest.TestCase):
    def test_every_profile_has_explicit_opt_in_and_linked_geometry(self):
        profiles=sorted((FORKY/'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            source=render_theme_defaults(payload_read_text(path))
            self.assertEqual(source.count('WLSUNSET_ENABLED="true"'),1,path)
            for name in ('FUZZEL_MENU_EXTERNAL_WIDTH', 'FUZZEL_MENU_EXTERNAL_LINES',
                         'FUZZEL_MENU_INTERNAL_WIDTH', 'FUZZEL_MENU_INTERNAL_LINES',
                         'FUZZEL_EXTERNAL_FONT_SIZE', 'FUZZEL_INTERNAL_FONT_SIZE'):
                self.assertRegex(source, r'(?m)^' + name + r'="[0-9]+"$')
            self.assertNotIn('LABWC_FUZZEL_COMPUTER_MANAGEMENT_', source)
        defaults=render_theme_defaults(payload_read_text(TARGET/'etc/labwc/wlsunset.conf.tmpl'))
        self.assertIn('__INSTALLER_WLSUNSET_ENABLED__',defaults)

    def test_assets_are_staged_and_hwdb_built_in_target(self):
        source=render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/components.sh'))
        for name in ('labwc-wallpaper-control','labwc-notification-send','labwc-wlsunset',
                     'labwc-configure-session-repairs','90-thinkpad-extra-buttons.hwdb','sudo-i.conf'):
            self.assertIn(name,source)
        self.assertIn('/usr/bin/systemd-hwdb --strict update',source)
        self.assertIn('desktop_stage_session_repairs\n',source)
        self.assertIn('wlsunset',render_theme_defaults(payload_read_text(FORKY/'classes/class-select/role/desktop.cfg')))

    @unittest.skipUnless(shutil.which('systemd-hwdb'), 'packaged systemd-hwdb required')
    def test_retired_hwdb_does_not_override_packaged_key_mappings(self):
        # logind's existing power-switch handler retains sole suspend ownership.
        rc=render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/labwc/rc.xml.tmpl'))
        self.assertNotIn('key="XF86Sleep"',rc)
        self.assertNotIn('key="XF86PowerOff"',rc)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'etc/udev/hwdb.d';directory.mkdir(parents=True)
            match='evdev:name:ThinkPad Extra Buttons:dmi:bvnLENOVO:bvrTEST:bd01:svnLENOVO:pnTEST:pvrTEST:'
            (directory/'60-test.hwdb').write_text('evdev:name:*:dmi:*\n KEYBOARD_KEY_01=screenlock\n KEYBOARD_KEY_ff=prog1\n\n')
            self.assertFalse(payload_source_exists(TARGET/'etc/udev/hwdb.d/90-thinkpad-extra-buttons.hwdb'))
            # The installer removes the retired asset, then rebuilds this database.
            source=render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/components.sh'))
            self.assertIn('remove_target_asset /etc/udev/hwdb.d/90-thinkpad-extra-buttons.hwdb',source)
            update=subprocess.run(payload_installed_argv(['systemd-hwdb','--strict','--root',str(root),'update']),capture_output=True,text=True)
            self.assertEqual(update.returncode,0,update.stderr)
            result=subprocess.run(payload_installed_argv(['systemd-hwdb','--root',str(root),'query',match]),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('KEYBOARD_KEY_01=screenlock',result.stdout)
            self.assertIn('KEYBOARD_KEY_ff=prog1',result.stdout)
            other=subprocess.run(payload_installed_argv(['systemd-hwdb','--root',str(root),'query',match.replace('ThinkPad Extra Buttons','Other Keyboard')]),capture_output=True,text=True)
            self.assertIn('KEYBOARD_KEY_01=screenlock',other.stdout)

    def test_decoration_and_single_tweaks_policy(self):
        self.assertIn('gtk-dialogs-use-header=false',render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/gtk-3.0/settings.ini.tmpl')))
        self.assertIn('DialogsUseHeader',render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml')))
        tweaks=render_theme_defaults(payload_read_text(TARGET/'usr/local/share/applications/labwc-tweaks.desktop'))
        self.assertIn('Name=Labwc Tweaks',tweaks);self.assertIn('NoDisplay=true',tweaks)
        self.assertIn('TWEAKS_DESKTOP_IDS',render_theme_defaults(payload_read_text(BIN/'labwc-main-menu')))

    def test_confined_transitions_and_deleted_inode_flags(self):
        utilities=render_theme_defaults(payload_read_text(AA/'desktop-utilities'))
        for text in ('/usr/bin/bwrap rCx -> media-glycin-bwrap','webkit-runtime','/usr/bin/iconv rix,',
                     'profile freerdp-client','profile clipboard-fuse','/usr/bin/fusermount3 rCx -> clipboard-fuse'):
            self.assertIn(text,utilities)
        self.assertRegex(render_theme_defaults(payload_read_text(AA/'usr.bin.telegram-desktop')),r'profile telegram-desktop .*flags=\([^)]*mediate_deleted')
        self.assertIn('gio-launch-desktop rix,',render_theme_defaults(payload_read_text(AA/'usr.bin.spotify')))
        self.assertIn('profile wpctl ',render_theme_defaults(payload_read_text(AA/'labwc-session')))

    def test_graphics_selection_does_not_disable_gpu_or_atomic_kms(self):
        electrons=render_theme_defaults(payload_read_text(TARGET/'usr/local/lib/python3.14/dist-packages/labwc_managed_app/electron.py'))
        self.assertIn('"--use-webgpu-adapter=opengles"',electrons)
        delta=electrons[electrons.index('    "chatgpt": {'):electrons.index('    "code": {')]
        self.assertNotIn('--disable-gpu"',delta)
        self.assertNotIn('--no-sandbox',delta)
        self.assertNotIn('LABWC_WLR_DRM_', render_theme_defaults(payload_read_text(TARGET/'etc/labwc/desktop.conf.tmpl')))
        session = render_theme_defaults(payload_read_text(TARGET/'usr/local/bin/labwc-session.tmpl'))
        self.assertNotIn('LABWC_WLR_DRM_', session)
        self.assertIn('unset WLR_DRM_NO_ATOMIC', session)


if __name__=='__main__':unittest.main()
