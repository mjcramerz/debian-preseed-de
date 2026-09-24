"""Additional fixture-only integration boundaries for the 2026-09-20 repair.

No installed target configuration, services, display, or authentication stack is
modified. Fuzzel/notification binaries are fixtures; shell orchestration is real.
"""
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from fuzzel_fixture import geometry_environment, wrapper_script
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import json
import os
import pwd
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'hooks/target'
BIN = TARGET / 'usr/local/bin'
LIBEXEC = TARGET / 'usr/local/libexec'


def load(path):
    module = types.ModuleType('fixture_' + path.name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
    return module


class GeometryTests(unittest.TestCase):
    def test_management_context_is_inherited_without_rewriting_child_log_scope(self):
        menu = load(BIN / 'labwc-computer-management')
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(menu.os, 'geteuid', return_value=1000), \
                mock.patch.object(menu, 'run_menu', return_value=0):
            self.assertEqual(menu.main([]), 0)
            self.assertEqual(os.environ['LABWC_FUZZEL_PALETTE'], 'computer-management')
            self.assertEqual(os.environ['LABWC_MENU_BACKEND'], 'fuzzel')

    def test_real_wrapper_enforces_main_geometry_for_every_management_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake = root / 'fuzzel'
            fake.write_text('#!/usr/bin/python3 -I\nimport json,os,sys\nfrom pathlib import Path\n'
                            'Path(os.environ["FIXTURE_ARGS"]).write_text(json.dumps(sys.argv[1:]))\n'
                            'sys.stdin.read()\n')
            fake.chmod(0o755)
            config = root / 'config/fuzzel'
            config.mkdir(parents=True)
            for name in ('base.ini', 'computer-management.ini', 'menu.ini', 'fuzzel.ini'):
                (config / name).write_text('[main]\n')
            env = {**os.environ, 'PATH': str(root) + ':/usr/bin:/bin', 'XDG_RUNTIME_DIR': str(root),
                   'XDG_CONFIG_HOME': str(root / 'config'), 'FIXTURE_ARGS': str(root / 'argv'),
                   'LABWC_MENU_BACKEND': 'fuzzel', 'LABWC_FUZZEL_MANAGED_ICONS': '0',
                   'LABWC_FUZZEL_PALETTE': 'computer-management', **geometry_environment(),
                   'FUZZEL_MENU_EXTERNAL_WIDTH': '64', 'FUZZEL_MENU_EXTERNAL_LINES': '19',
                   'FUZZEL_MENU_INTERNAL_WIDTH': '31', 'FUZZEL_MENU_INTERNAL_LINES': '12',
                   'LABWC_FUZZEL_MENU_WIDTH_OVERRIDE': '18', 'LABWC_FUZZEL_MENU_LINES_OVERRIDE': '3'}
            for scope in ('computer-management', 'android-debug-bridge'):
                for output, width, lines, config_name in [('HDMI-A-1',64,19,'computer-management.ini'), ('eDP-1',31,12,'computer-management.ini')]:
                    with self.subTest(scope=scope, output=output):
                        env.update(LABWC_FUZZEL_LOG_SCOPE=scope, WAYBAR_OUTPUT_NAME=output)
                        result = subprocess.run(payload_installed_argv(['/bin/sh', str(wrapper_script(root, fake)), 'menu', '--dmenu']),
                                                input='Back\n', text=True, capture_output=True, env=env, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        args = json.loads(render_theme_defaults(payload_read_text(root/'argv')))
                        self.assertEqual([a for a in args if a.startswith('--width=')][-1], f'--width={width}')
                        self.assertEqual([a for a in args if a.startswith('--lines=')][-1], f'--lines={lines}')
                        self.assertIn('--config=' + str(config/config_name), args)


class MenuIdentityTests(unittest.TestCase):
    def test_enumeration_categorizes_exact_identities_and_removes_only_duplicate_tweaks(self):
        menu = load(BIN / 'labwc-main-menu')
        class App:
            def __init__(self, name, categories): self.name,self.categories=name,categories
            def get_id(self): return self.name
            def get_display_name(self): return self.name
            def get_categories(self): return self.categories
            def get_filename(self): return '/fixture/' + self.name
            def get_is_hidden(self): return False
            def should_show(self): return True
            def get_string(self, key): return 'Application' if key=='Type' else 'application-x-executable'
        apps = [App('qoredb.desktop','Database;'), App('qalculate-qt.desktop','Utility;Calculator;'),
                App('org.libretro.RetroArch.desktop','System;Emulator;'),
                App('labwc-tweaks.desktop','Settings;'),App('labwc-tweaks-gtk.desktop','Settings;'),
                App('unrelated-settings.desktop','Settings;')]
        gio = types.SimpleNamespace(AppInfo=types.SimpleNamespace(get_all=lambda: apps))
        with mock.patch.object(menu, 'gio_api', return_value=(gio, App)):
            found={a['id']:a['category'] for a in menu.enumerate_apps()}
        self.assertEqual(found, {'qoredb.desktop':'Development','qalculate-qt.desktop':'Office & Productivity',
                                'org.libretro.RetroArch.desktop':'Games','unrelated-settings.desktop':'Settings'})


@unittest.skipUnless(os.getuid()==0, 'root-owned PAM fixture requires root; does not touch /etc')
class InstallerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=pwd.getpwuid(os.getuid()).pw_dir)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.pam=self.root/'etc/pam.d/sudo-i'
        self.pam.parent.mkdir(parents=True)
        self.pam.write_text('@include common-auth\n@include common-account\n@include common-session\n')
        self.pam.chmod(0o644)
        self.helper=load(LIBEXEC/'labwc-configure-session-repairs')

    def invoke(self):
        def rooted(value): return self.root / str(value).lstrip('/')
        with mock.patch.object(self.helper, 'Path', side_effect=rooted), \
                mock.patch.object(self.helper.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=1234, pw_dir='/home/fixtureuser')), \
                mock.patch.object(sys, 'argv', ['helper', 'fixtureuser']):
            self.helper.main()

    def test_pam_policy_is_idempotent_without_location_policy(self):
        self.invoke()
        first=render_theme_defaults(payload_read_text(self.pam))
        self.invoke()
        self.assertEqual(first, render_theme_defaults(payload_read_text(self.pam)))
        self.assertEqual(first.count('conffile=/etc/security/sudo-i.conf'),1)
        self.assertLess(first.index('pam_env.so'), first.index('@include common-session'))
        self.assertIn('@include common-auth\n@include common-account\n',first)
        self.invoke()
        self.assertFalse(payload_source_exists(self.root/'etc/geoclue'))
        self.assertEqual(first,render_theme_defaults(payload_read_text(self.pam)))

    def test_unknown_pam_stack_fails_without_replacing_it(self):
        self.pam.write_text('@include custom-session\n')
        with self.assertRaisesRegex(RuntimeError,'unexpected sudo-i'):
            self.invoke()
        self.assertEqual(render_theme_defaults(payload_read_text(self.pam)),'@include custom-session\n')

    def test_redirected_pam_stack_is_rejected(self):
        victim=self.root/'victim'
        victim.write_text('unchanged')
        self.pam.unlink()
        self.pam.symlink_to(victim)
        with self.assertRaises(OSError): self.invoke()
        self.assertEqual(render_theme_defaults(payload_read_text(victim)),'unchanged')


    def fixture_file(self, relative, text="managed fixture"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_obsolete_colour_cleanup_is_exact_and_idempotent(self):
        obsolete = [self.fixture_file(name) for name in (
            'usr/local/bin/labwc-gammastep-indicator',
            'usr/local/share/applications/gammastep.desktop',
            'usr/local/share/applications/gammastep-indicator.desktop',
            'etc/gammastep/config.ini',
            'etc/geoclue/conf.d/90-gammastep.conf',
            'etc/skel-desktop/.config/systemd/user/labwc-gammastep-indicator.service',
            'home/fixtureuser/.config/autostart/gammastep-indicator.desktop',
            'home/fixtureuser/.config/systemd/user/labwc-gammastep-indicator.service',
            'home/fixtureuser/.local/share/applications/gammastep-indicator.desktop')]
        victim = self.fixture_file('victim', 'preserved')
        enablement = self.root / 'home/fixtureuser/.config/systemd/user/labwc-session.target.wants/gammastep.service'
        enablement.parent.mkdir(parents=True)
        enablement.symlink_to(victim)
        preserved = [self.fixture_file(name, 'unrelated') for name in (
            'usr/bin/gammastep', 'etc/geoclue/conf.d/80-other-application.conf',
            'home/fixtureuser/.config/another-program/settings')]
        self.invoke(); self.invoke()
        self.assertTrue(all(not payload_source_exists(path) for path in obsolete))
        self.assertFalse(enablement.is_symlink())
        self.assertEqual(render_theme_defaults(payload_read_text(victim)), 'preserved')
        self.assertTrue(all(render_theme_defaults(payload_read_text(path)) == 'unrelated' for path in preserved))

    def test_colour_cleanup_rejects_redirected_parent(self):
        victim = self.fixture_file('victim/gammastep-indicator.desktop', 'preserved')
        redirected = self.root / 'usr/local/share/applications'
        redirected.parent.mkdir(parents=True)
        redirected.symlink_to(victim.parent, target_is_directory=True)
        with self.assertRaises(OSError): self.invoke()
        self.assertEqual(render_theme_defaults(payload_read_text(victim)), 'preserved')

    def test_colour_cleanup_rejects_non_regular_leaf(self):
        path = self.root / 'usr/local/bin/labwc-gammastep-indicator'
        path.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'unsafe obsolete colour asset'): self.invoke()
        self.assertTrue(path.is_dir())

    def test_colour_cleanup_unlinks_hardlink_without_writing_other_name(self):
        victim = self.fixture_file('victim', 'preserved')
        obsolete = self.root / 'usr/local/bin/labwc-gammastep-indicator'
        obsolete.parent.mkdir(parents=True)
        os.link(victim, obsolete)
        self.invoke()
        self.assertFalse(payload_source_exists(obsolete))
        self.assertEqual(render_theme_defaults(payload_read_text(victim)), 'preserved')


class HealthTransactionTests(unittest.TestCase):
    def test_failed_delivery_retains_pending_record_and_success_commits_it_once(self):
        # The script validates trusted ancestors, so do not use world-writable /tmp.
        with tempfile.TemporaryDirectory(prefix='.health-fixture-',dir=pwd.getpwuid(os.getuid()).pw_dir) as temporary:
            root=Path(temporary)
            runtime=root/'run';runtime.mkdir(mode=0o700)
            wayland=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            wayland.bind(str(runtime/'wayland-0'))
            self.addCleanup(wayland.close)
            events=root/'events';events.mkdir(mode=0o700)
            event=events/'1789900000-0000000123-0001.event'
            event.write_text('Desktop Health|normal|dialog-information|system.health|12000|Fixture event|Safe details\n')
            event.chmod(0o600)
            fake=root/'notify'
            calls=root/'calls'
            fake.write_text('#!/bin/sh\nprintf "called\\n" >> "$FIXTURE_CALLS"\nexit "$FIXTURE_STATUS"\n')
            fake.chmod(0o700)
            mem=root/'meminfo';mem.write_text('MemTotal: 100000 kB\nMemAvailable: 90000 kB\n')
            env={**os.environ, 'HOME':str(root), 'XDG_STATE_HOME':str(root/'state'), 'XDG_RUNTIME_DIR':str(runtime),
                 'WAYLAND_DISPLAY':'wayland-0','XDG_SESSION_TYPE':'wayland','LABWC_SESSION_OWNER':'desktop',
                 'DBUS_SESSION_BUS_ADDRESS':'unix:path='+str(runtime/'bus'), 'NOTIFY_SEND':str(fake),
                 'FIXTURE_CALLS':str(calls),'FIXTURE_STATUS':'1','SYSTEM_EVENT_DIR':str(events),
                 'SYSTEM_EVENT_OWNER_UID':str(os.getuid()),'MEMINFO_FILE':str(mem),'MAIL':str(root/'absent'),
                 **{key:str(root/'absent') for key in ('TIMESHIFT_EVENT_DIR','UNATTENDED_EVENT_DIR','SECURITY_SIGNAL_DIR','POWER_SUPPLY_DIR','REBOOT_REQUIRED_FILE')}}
            def run():
                return subprocess.run(payload_installed_argv(['/bin/sh',str(BIN/'labwc-health-notify')]),env=env,capture_output=True,text=True,timeout=15)
            result=run()
            self.assertEqual(result.returncode,1,result.stderr)
            seen=root/'state/labwc-health-notify/system-seen'/ (event.name+'.seen')
            self.assertFalse(payload_source_exists(seen))
            self.assertEqual(render_theme_defaults(payload_read_text(calls)).splitlines(),['called'])
            env['FIXTURE_STATUS']='0'
            result=run()
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(payload_source_is_file(seen))
            count=len(render_theme_defaults(payload_read_text(calls)).splitlines())
            result=run()
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(len(render_theme_defaults(payload_read_text(calls)).splitlines()),count)


if __name__=='__main__': unittest.main()
