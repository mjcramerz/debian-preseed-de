"""Categorization/selection unit tests and real unprivileged GIO XDG probes."""
import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
MENU = TARGET / 'usr/local/bin/labwc-main-menu'
PROBE = Path(__file__).with_name('gio_desktop_fixture.py')


def load(path):
    module = types.ModuleType('tested_menu'); module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class MenuUnitTests(unittest.TestCase):
    def setUp(self): self.menu = load(MENU)

    def test_every_main_and_additional_category_has_one_destination(self):
        for label, main, additional in self.menu.CATEGORY_RULES:
            for token in main | additional:
                with self.subTest(token=token):
                    self.assertEqual(self.menu.category_for(token + ';'), label)
        self.assertEqual(len(self.menu.DISPLAY_CATEGORIES), len(set(self.menu.DISPLAY_CATEGORIES)))

    def test_deterministic_multicategory_precedence_and_specific_refinement(self):
        cases = {'Settings;System;': 'Settings', 'Development;Utility;': 'Development',
                 'Network;Utility;': 'Internet', 'Office;Utility;': 'Office & Productivity',
                 'AudioVideo;Utility;': 'Multimedia', 'System;TerminalEmulator;': 'System',
                 'Network;Email;': 'Office & Productivity', 'System;FileManager;': 'Utilities',
                 'Network;Development;': 'Development', 'Graphics;AudioVideo;': 'Graphics',
                 'Settings;IDE;': 'Settings'}
        for tokens, label in cases.items():
            with self.subTest(tokens=tokens):
                self.assertEqual(self.menu.category_for(tokens), label)
                self.assertEqual(self.menu.category_for(';'.join(reversed(tokens.split(';')))), label)

    def test_missing_unknown_and_nonstandard_categories_fall_back_to_other(self):
        for categories in (None, '', 'X-VendorCategory;', 'AI;', 'OfficeAndProductivity;'):
            with self.subTest(categories=categories):
                self.assertEqual(self.menu.category_for(categories), 'Other')
        self.assertEqual(self.menu.category_for('ArtificialIntelligence;'), 'Education')

    def test_name_data_unicode_metacharacters_duplicates_and_stable_tiebreaker(self):
        names = ['Space Name', 'R\u00e4knare \U0001f680', 'a\tname', 'a\nname',
                 "quotes ' \" $x `cmd`; & | (x) <xml>", 'Duplicate', 'Duplicate', self.menu.BACK]
        apps = [{'id': f'app{i};$`|&.desktop', 'name': name, 'category': 'Other'} for i, name in enumerate(names)]
        choices = self.menu.app_choices(apps, 'Other')
        self.assertEqual(choices, self.menu.app_choices(list(reversed(apps)), 'Other'))
        self.assertEqual(set(choices.values()), {app['id'] for app in apps})
        self.assertEqual(len(choices), len(apps)); self.assertNotIn(self.menu.BACK, choices)
        self.assertTrue(all('\n' not in label and '\t' not in label for label in choices))
        self.assertTrue(all('[' in label for label in choices if label.startswith('Duplicate')))
        self.assertIn('R\u00e4knare \U0001f680', choices)

    def test_suffix_collision_and_back_named_application_remain_distinguishable(self):
        apps = [{'id': key, 'name': name, 'category': 'Other'} for key, name in
                [('a.desktop', 'Same'), ('b.desktop', 'Same'), ('c.desktop', 'Same [a.desktop]'),
                 ('d.desktop', self.menu.BACK)]]
        choices = self.menu.app_choices(apps, 'Other')
        self.assertEqual(len(choices), 4); self.assertNotIn(self.menu.BACK, choices)

    def test_fuzzel_is_existing_wrapper_with_exact_allowed_selection(self):
        result = types.SimpleNamespace(returncode=0, stdout='Allowed\n')
        with mock.patch.object(self.menu.subprocess, 'run', return_value=result) as run:
            self.assertEqual(self.menu.choose({'Allowed': 'id'}, 'Main Menu'), 'Allowed')
        args, kw = run.call_args
        self.assertEqual(args[0][:3], ['/usr/local/bin/labwc-fuzzel', 'main-menu', '--dmenu'])
        self.assertEqual(kw['input'], 'Allowed\0icon\x1fapplication-x-executable\n')
        self.assertEqual(kw['env']['LABWC_FUZZEL_MANAGED_ICONS'], '0')
        self.assertNotIn('shell', kw)

    def test_arbitrary_free_text_and_multiple_lines_cannot_execute(self):
        for text in ('$(touch /tmp/never-run)', '`id`', '; /bin/sh', 'Allowed\nInjected', ' Allowed', 'Allowed '):
            with self.subTest(text=text), mock.patch.object(self.menu.subprocess, 'run',
                    return_value=types.SimpleNamespace(returncode=0, stdout=text + '\n')) as run:
                self.assertIsNone(self.menu.choose({'Allowed': 'id'}, 'Test'))
                self.assertEqual(run.call_count, 1)

    def test_cancel_is_successful_and_silent(self):
        with mock.patch.object(self.menu.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1, stdout='')):
            self.assertIsNone(self.menu.choose({'x': None}, 'Test'))
        with mock.patch.object(self.menu, 'choose', return_value=None), \
             mock.patch.object(self.menu.os, 'geteuid', return_value=1000):
            self.assertEqual(self.menu.main([]), 0)

    def test_search_applications_delegates_to_search_entrypoint(self):
        with mock.patch.object(self.menu, 'choose', return_value='Search Applications'), \
             mock.patch.object(self.menu, 'run_action') as action:
            self.menu.run_menu()
        action.assert_called_once_with(('/usr/local/bin/labwc-run',))

    def test_back_returns_to_main_and_reenumerates_on_next_submenu(self):
        choices = iter(['Development', self.menu.BACK, 'Development', self.menu.BACK, None])
        with mock.patch.object(self.menu, 'choose', side_effect=lambda *_: next(choices)) as choose, \
             mock.patch.object(self.menu.subprocess, 'run', return_value=types.SimpleNamespace(stdout='[]')) as run:
            self.menu.run_menu()
        self.assertEqual([call.args[1] for call in choose.call_args_list],
                         ['Main Menu', 'Development', 'Main Menu', 'Development', 'Main Menu'])
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.args[0] == [self.menu.SELF, '--list'] for call in run.call_args_list))

    def test_selected_desktop_id_is_data_even_with_leading_dash(self):
        apps = [{'id': '-$`foo;|.desktop', 'name': 'Selected', 'category': 'Other'}]
        with mock.patch.object(self.menu, 'choose', side_effect=['Other', 'Selected']), \
             mock.patch.object(self.menu.subprocess, 'run', return_value=types.SimpleNamespace(stdout=json.dumps(apps))) as run:
            self.menu.run_menu()
        self.assertEqual(run.call_args.args[0], [self.menu.SELF, '--launch=-$`foo;|.desktop'])
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_root_is_refused_before_discovery_or_execution(self):
        for argv in ([], ['--list'], ['--launch=demo.desktop']):
            with self.subTest(argv=argv), mock.patch.object(self.menu.os, 'geteuid', return_value=0), \
                 mock.patch.object(self.menu, 'gio_api') as gio, self.assertRaises(RuntimeError):
                self.menu.main(argv)
            gio.assert_not_called()

    def test_xdg_defaults_relative_paths_and_explicit_order(self):
        with mock.patch.dict(os.environ, {'HOME': '/home/test'}, clear=True):
            self.menu.prepare_environment()
            self.assertEqual(os.environ['XDG_DATA_HOME'], '/home/test/.local/share')
            self.assertEqual(os.environ['XDG_DATA_DIRS'], '/usr/local/share:/usr/share')
            self.assertEqual(os.environ['XDG_CURRENT_DESKTOP'], 'labwc:wlroots')
        with mock.patch.dict(os.environ, {'HOME': '/home/test', 'XDG_DATA_HOME': 'relative',
                                         'XDG_DATA_DIRS': '/second:relative:/first:/second',
                                         'GIO_LAUNCH_DESKTOP': '/malicious'}, clear=True):
            self.menu.prepare_environment()
            self.assertEqual(os.environ['XDG_DATA_HOME'], '/home/test/.local/share')
            self.assertEqual(os.environ['XDG_DATA_DIRS'], '/second:/first')
            self.assertNotIn('GIO_LAUNCH_DESKTOP', os.environ)


class IntegrationContractTests(unittest.TestCase):
    def test_labwc_run_still_executes_searchable_fuzzel_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); binary = root / 'labwc-fuzzel'
            binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n'); binary.chmod(0o755)
            source = (TARGET / 'usr/local/bin/labwc-run').read_text()
            source = source.replace('/etc/default/labwc-desktop', str(root / 'absent-defaults'))
            result = subprocess.run(['/bin/sh', '-c', source], env={'PATH': str(root) + ':/usr/bin:/bin'},
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'launcher\n')

    def test_waybar_menu_keeps_transient_service_contract_and_search_keys_stay_search(self):
        text = (TARGET / 'etc/skel-desktop/.config/waybar/config.tmpl').read_text()
        clicks = re.findall(r'"on-click": "([^"]* -- labwc-main-menu)"', text)
        self.assertEqual(len(clicks), 2)
        for click in clicks:
            for argument in ('--user', '--collect', '--service-type=exec', '--expand-environment=no',
                             '--property=Requisite=labwc-session.target', '--property=After=labwc-session.target',
                             '--property=PartOf=labwc-session.target', '--property=ExitType=cgroup',
                             '--property=KillMode=control-group', '--property=TimeoutStopSec=20s',
                             '--setenv=WAYBAR_OUTPUT_NAME'):
                self.assertIn(argument, click)
        rc = (TARGET / 'etc/skel-desktop/.config/labwc/rc.xml.tmpl').read_text()
        self.assertIn('labwc-run', rc)
        import xml.etree.ElementTree as ET
        bindings = {item.get('key'): item for item in ET.fromstring(rc).findall('keyboard/keybind')}
        self.assertEqual(bindings['Super_L'].get('onRelease'), 'yes')
        self.assertEqual(bindings['Super_L'].find('action').get('command'), 'labwc-main-menu')
        for key in ('W-d', 'W-space', 'C-A-space'):
            self.assertEqual(bindings[key].find('action').get('command'), 'labwc-run')

    def test_root_user_watchers_and_shared_thin_dpkg_engine_are_separate(self):
        root = (TARGET / 'etc/systemd/system/labwc-system-desktop-overrides.path').read_text()
        self.assertIn('PathChanged=/usr/share/applications', root)
        self.assertNotIn('/usr/local/share/applications', root); self.assertNotIn('/home', root)
        service = (TARGET / 'etc/systemd/system/labwc-system-desktop-overrides.service').read_text()
        self.assertIn('Type=oneshot', service); self.assertIn('ExecStart=/usr/local/libexec/labwc-wrap-desktop-files', service)
        for directive in ('NoNewPrivileges=yes', 'ProtectHome=yes', 'ProtectSystem=strict', 'CapabilityBoundingSet='):
            self.assertIn(directive, service)
        user = (TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-sync-application-launchers.path').read_text()
        self.assertNotIn('.local/share/applications', user)
        hook = (TARGET / 'etc/dpkg/dpkg.cfg.d/95-labwc-desktop-apps').read_text()
        self.assertIn('labwc-wrap-desktop-files --post-invoke', hook)
        self.assertNotIn('systemctl', hook)

    def test_actual_installation_staging_enablement_initial_run_and_dependency(self):
        components = (FORKY / 'scripts/desktop/components.sh').read_text()
        self.assertIn('usr/local/bin/labwc-main-menu /usr/local/bin/labwc-main-menu 0755', components)
        for name in ('labwc-system-desktop-overrides.service', 'labwc-system-desktop-overrides.path'):
            self.assertIn(f'etc/systemd/system/{name} /etc/systemd/system/{name} 0644', components)
            self.assertIn(f'desktop_enable_unit_if_available {name} system', components)
        late = (FORKY / 'scripts/desktop/labwc.sh').read_text()
        self.assertIn('run_in_target "wrap installed desktop package launchers" /usr/local/libexec/labwc-wrap-desktop-files', late)
        self.assertIn('gi.require_version("GioUnix", "2.0")', late)
        packages = '\n'.join(path.read_text(errors='replace') for path in (FORKY / 'classes').rglob('*') if path.is_file())
        self.assertIn('python3-gi', packages); self.assertIn('desktop-file-utils', packages)

    def test_waypaper_profile_rendering_isolation_persistence_and_native_xml(self):
        template = (TARGET / 'etc/skel-desktop/.local/share/applications/waypaper.desktop.tmpl').read_text()
        self.assertIn('\nExec=__INSTALLER_LABWC_WAYLAND_APP_DEFAULT_EXEC__ -- /usr/local/bin/waypaper\n', template)
        for mode in ('intel', 'nvidia', 'launch'):
            rendered = template.replace('__INSTALLER_LABWC_WAYLAND_APP_DEFAULT_EXEC__', '/usr/local/bin/labwc-wayland-app ' + mode)
            self.assertIn(f'Exec=/usr/local/bin/labwc-wayland-app {mode} -- /usr/local/bin/waypaper', rendered)
        for source in ('components.sh', 'waypaper.sh'):
            self.assertIn('LABWC_WAYLAND_APP_DEFAULT_EXEC "$LABWC_WAYLAND_APP_DEFAULT_EXEC"',
                          (FORKY / 'scripts/desktop' / source).read_text())
        config = (TARGET / 'etc/skel-desktop/.config/waypaper/config.ini').read_text()
        self.assertIn('labwc-wallpaper-save --apply', config)
        self.assertIn('swaybg.service', (TARGET / 'usr/local/bin/labwc-wallpaper-save').read_text())
        tree = ET.parse(TARGET / 'etc/skel-desktop/.config/labwc/menu.xml')
        self.assertEqual(tree.getroot().tag, 'openbox_menu')
        self.assertTrue(any('labwc-wayland-app auto -- /usr/local/bin/waypaper' in item.attrib.get('command', '')
                            for item in tree.iter('action')))

    def test_user_sync_uses_xdg_only_as_user_and_keeps_selected_application_scope(self):
        sync = load(TARGET / 'usr/local/bin/labwc-sync-application-launchers')
        with mock.patch.dict(os.environ, {'XDG_DATA_HOME': '/custom/data'}):
            with mock.patch.object(sync.os, 'geteuid', return_value=1000):
                self.assertEqual(sync.application_data_home('/home/test'), '/custom/data')
            with mock.patch.object(sync.os, 'geteuid', return_value=0):
                self.assertEqual(sync.application_data_home('/home/test'), '/home/test/.local/share')
        self.assertTrue(sync.APP_CONFIG)
        self.assertEqual(sync.SYSTEM_APPLICATION_DIR, '/usr/share/applications')

    def test_menu_apparmor_is_readonly_for_xdg_data_and_uses_existing_launch_domain(self):
        profiles = (TARGET / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
        menu = profiles.split('profile managed-labwc-main-menu ', 1)[1]
        self.assertIn('gio-launch-desktop rPx -> managed-desktop-launcher', menu)
        self.assertIn('managed-labwc-fuzzel', menu)
        self.assertNotIn(' Ux', menu); self.assertNotIn(' ux', menu)
        for line in menu.splitlines():
            if 'applications/' in line: self.assertTrue(line.rstrip().endswith(' r,'), line)

    @unittest.skipUnless(shutil.which('desktop-file-validate'), 'desktop-file-utils not installed on test host')
    def test_all_project_desktop_entries_validate_after_template_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, source in enumerate(sorted(TARGET.rglob('*.desktop')) + sorted(TARGET.rglob('*.desktop.tmpl'))):
                text = source.read_text()
                text = text.replace('__INSTALLER_LABWC_WAYLAND_APP_DEFAULT_EXEC__', '/usr/local/bin/labwc-wayland-app intel')
                text = text.replace('__INSTALLER_LABWC_MANAGED_APP_DEFAULT_EXEC__', '/usr/local/bin/labwc-managed-app intel')
                if '__INSTALLER_' in text: continue  # non-application session templates are checked by the installer
                target = Path(directory) / f'{index}.desktop'; target.write_text(text)
                result = subprocess.run(['desktop-file-validate', str(target)], text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, f'{source}: {result.stdout} {result.stderr}')


class UserSyncXdgTests(unittest.TestCase):
    """Exercise only managed directory setup, as an actual unprivileged account."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='labwc-sync-xdg-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.root.chmod(0o755)
        self.uid = 65534 if os.geteuid() == 0 else os.getuid()
        self.gid = 65534 if os.geteuid() == 0 else os.getgid()
        self.home = self.root / 'home'; self.home.mkdir(mode=0o755)
        if os.geteuid() == 0: os.chown(self.home, self.uid, self.gid)
        self.source = self.root / 'sync'
        self.source.write_bytes((TARGET / 'usr/local/bin/labwc-sync-application-launchers').read_bytes())
        self.source.chmod(0o644)

    def invoke(self, data_home):
        code = """import json, os, pathlib, sys, types
module = types.ModuleType('fixture')
source = pathlib.Path(sys.argv[1])
exec(compile(source.read_bytes(), str(source), 'exec'), module.__dict__)
path = module.ensure_application_directory(sys.argv[2], os.getuid(), os.getgid())
print(json.dumps({'path': path, 'uid': os.geteuid(), 'mode': os.stat(path).st_mode & 0o777}))
"""
        options = {'user': self.uid, 'group': self.gid, 'extra_groups': []} if os.geteuid() == 0 else {}
        return subprocess.run(['/usr/bin/python3', '-I', '-c', code, str(self.source), str(self.home)],
            env=dict(os.environ, HOME=str(self.home), XDG_DATA_HOME=data_home),
            capture_output=True, text=True, timeout=5, **options)

    def test_custom_root_creates_private_selected_application_directory(self):
        data = self.home / 'custom/nested/data'
        result = self.invoke(str(data)); self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(actual, {'path': str(data / 'applications'), 'uid': self.uid, 'mode': 0o700})
        self.assertFalse((self.home / '.local/share/applications').exists())
        self.assertEqual(self.invoke(str(data)).returncode, 0)

    def test_existing_custom_parent_permissions_are_not_relaxed_or_rewritten(self):
        data = self.home / 'data'; data.mkdir(mode=0o750)
        if os.geteuid() == 0: os.chown(data, self.uid, self.gid)
        before = (data.stat().st_mode, self.home.stat().st_mode)
        result = self.invoke(str(data)); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((data.stat().st_mode, self.home.stat().st_mode), before)

    def test_symlink_and_shared_writable_data_roots_are_rejected(self):
        data = self.home / 'data'; data.mkdir(mode=0o755)
        if os.geteuid() == 0: os.chown(data, self.uid, self.gid)
        link = self.home / 'link'; link.symlink_to(data, target_is_directory=True)
        self.assertNotEqual(self.invoke(str(link)).returncode, 0)
        self.assertFalse((data / 'applications').exists())
        data.chmod(0o777)
        self.assertNotEqual(self.invoke(str(data)).returncode, 0)
        self.assertFalse((data / 'applications').exists())

    def test_relative_data_home_uses_standard_default(self):
        result = self.invoke('relative/path'); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['path'], str(self.home / '.local/share/applications'))


class RealGioSemanticTests(unittest.TestCase):
    """The production discovery/launch functions run against real libgio via C ABI."""
    def setUp(self):
        try: ctypes.CDLL('libgio-2.0.so.0')
        except OSError as exc: self.skipTest(str(exc))
        self.temp = tempfile.TemporaryDirectory(prefix='labwc-xdg-tests-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.root.chmod(0o755)
        # The checkout itself may deliberately be root-private. Copy only the
        # tested sources into this readable fixture, not chmod the repository.
        self.menu_source = self.root / 'labwc-main-menu'
        self.probe_source = self.root / 'gio_desktop_fixture.py'
        for source, destination in ((MENU, self.menu_source), (PROBE, self.probe_source)):
            destination.write_bytes(source.read_bytes()); destination.chmod(0o644)
        self.home = self.root / 'home'; self.home.mkdir(mode=0o755)
        self.data = self.root / 'user-data'; self.local = self.root / 'system-local'; self.vendor = self.root / 'system-vendor'
        for directory in (self.data, self.local, self.vendor): (directory / 'applications').mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), XDG_DATA_HOME=str(self.data),
                        XDG_DATA_DIRS=f'{self.local}:{self.vendor}', XDG_CURRENT_DESKTOP='labwc:wlroots',
                        LC_ALL='C.UTF-8', LANGUAGE='en', PATH='/usr/bin:/bin',
                        DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent')
        self.identity = dict(user=65534, group=65534, extra_groups=[]) if os.geteuid() == 0 else {}
        try:
            result = subprocess.run(['/usr/bin/id', '-u'], capture_output=True, text=True, timeout=5, **self.identity)
        except OSError as exc: self.skipTest(f'unprivileged fixture unavailable: {exc}')
        self.uid = int(result.stdout)
        self.assertNotEqual(self.uid, 0)

    def write(self, root=None, name='app.desktop', title='Fixture', categories='Utility;', extra='', exec_value='/usr/bin/true'):
        path = (root or self.vendor) / 'applications' / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[Desktop Entry]\nType=Application\nName={title}\nExec={exec_value}\nCategories={categories}\n{extra}', encoding='utf-8')
        path.chmod(0o644)
        return path

    def probe(self, command='--list', pygi=False):
        result = subprocess.run(['/usr/bin/python3', '-B', str(self.probe_source), str(self.menu_source), command] + ([] if pygi else ['--ctypes']),
                                text=True, capture_output=True, env=self.env, timeout=10, **self.identity)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if command == '--list' else result

    def test_xdg_home_over_local_over_vendor_duplicate_ids(self):
        self.write(self.vendor, title='Vendor'); self.write(self.local, title='Local'); self.write(self.data, title='User')
        result = self.probe(); self.assertEqual(len(result), 1); self.assertEqual(result[0]['name'], 'User')
        (self.data / 'applications/app.desktop').unlink()
        self.assertEqual(self.probe()[0]['name'], 'Local')
        (self.local / 'applications/app.desktop').unlink()
        self.assertEqual(self.probe()[0]['name'], 'Vendor')

    def test_xdg_data_dirs_order_is_not_hardcoded(self):
        self.write(self.local, title='Local'); self.write(self.vendor, title='Vendor')
        self.env['XDG_DATA_DIRS'] = f'{self.vendor}:{self.local}'
        self.assertEqual(self.probe()[0]['name'], 'Vendor')

    def test_high_precedence_hidden_masks_lower_including_minimal_tombstone(self):
        self.write(self.vendor); self.write(self.local, extra='Hidden=true\n')
        self.assertEqual(self.probe(), [])
        self.write(self.data, extra='Hidden=false\n', title='Visible user')
        self.assertEqual(self.probe()[0]['name'], 'Visible user')
        (self.data / 'applications/app.desktop').write_text('[Desktop Entry]\nHidden=true\n')
        self.assertEqual(self.probe(), [])

    def test_nodisplay_true_false_and_absent(self):
        self.write(name='hidden.desktop', extra='NoDisplay=true\n')
        self.write(name='visible.desktop', extra='NoDisplay=false\n')
        self.write(name='absent.desktop')
        self.assertEqual({app['id'] for app in self.probe()}, {'visible.desktop', 'absent.desktop'})

    def test_onlyshowin_and_notshowin_effective_desktop(self):
        self.write(name='labwc.desktop', extra='OnlyShowIn=labwc;\n')
        self.write(name='wlroots.desktop', extra='OnlyShowIn=wlroots;\n')
        self.write(name='other.desktop', extra='OnlyShowIn=GNOME;\n')
        self.write(name='excluded.desktop', extra='NotShowIn=labwc;\n')
        self.write(name='allowed.desktop', extra='NotShowIn=GNOME;\n')
        self.assertEqual({app['id'] for app in self.probe()}, {'labwc.desktop', 'wlroots.desktop', 'allowed.desktop'})

    def test_tryexec_missing_available_and_not_executable(self):
        unavailable = self.root / 'not-executable'; unavailable.write_text('data'); unavailable.chmod(0o644)
        self.write(name='missing.desktop', extra='TryExec=/not/installed\n')
        self.write(name='available.desktop', extra='TryExec=true\n')
        self.write(name='permission.desktop', extra=f'TryExec={unavailable}\n')
        self.assertEqual({app['id'] for app in self.probe()}, {'available.desktop'})

    def test_localized_name(self):
        self.write(title='Calculator', extra='Name[sv]=R\u00e4knare\n')
        self.env['LANGUAGE'] = 'sv'
        self.assertEqual(self.probe()[0]['name'], 'R\u00e4knare')

    def test_malformed_nonapplication_and_missing_type_are_not_shown(self):
        bad = self.write(name='bad.desktop'); bad.write_text('not a keyfile\n')
        link = self.write(name='link.desktop'); link.write_text('[Desktop Entry]\nType=Link\nName=Link\nURL=https://example.invalid\n')
        missing = self.write(name='missing-type.desktop'); missing.write_text('[Desktop Entry]\nName=Missing\nExec=/usr/bin/true\n')
        self.assertEqual(self.probe(), [])

    def test_nested_desktop_ids_are_flattened_by_gio(self):
        self.write(name='vendor/sub/app.desktop')
        result = self.probe(); self.assertEqual(result[0]['id'], 'vendor-sub-app.desktop')
        self.write(self.data, name='vendor-sub-app.desktop', title='User override')
        self.assertEqual(self.probe()[0]['name'], 'User override'); self.assertEqual(len(self.probe()), 1)

    def test_missing_categories_and_unknown_categories_are_other(self):
        self.write(name='unknown.desktop', categories='X-Something;')
        path = self.write(name='absent.desktop'); path.write_text(path.read_text().replace('Categories=Utility;\n', ''))
        self.assertEqual({app['category'] for app in self.probe()}, {'Other'})

    def test_all_display_categories_and_single_assignment_using_fixture_applications(self):
        fixtures = [('code.desktop', 'Code', 'Development;IDE;', 'Development'),
                    ('postman.desktop', 'Postman', 'Development;', 'Development'),
                    ('vivaldi.desktop', 'Vivaldi', 'Network;WebBrowser;', 'Internet'),
                    ('discord.desktop', 'Discord', 'Network;InstantMessaging;', 'Internet'),
                    ('chromium.desktop', 'Chromium', 'Network;WebBrowser;', 'Internet'),
                    ('tuta.desktop', 'Tuta', 'Network;Email;', 'Office & Productivity'),
                    ('focuswriter.desktop', 'FocusWriter', 'Office;WordProcessor;', 'Office & Productivity'),
                    ('gnumeric.desktop', 'Gnumeric', 'Office;Spreadsheet;', 'Office & Productivity'),
                    ('graphics.desktop', 'Graphics fixture', 'Graphics;', 'Graphics'),
                    ('media.desktop', 'Media fixture', 'AudioVideo;', 'Multimedia'),
                    ('game.desktop', 'Game fixture', 'Game;', 'Games'),
                    ('education.desktop', 'Education fixture', 'Science;ArtificialIntelligence;', 'Education'),
                    ('utility.desktop', 'Utility fixture', 'Utility;', 'Utilities'),
                    ('terminal.desktop', 'Terminal fixture', 'System;TerminalEmulator;', 'System'),
                    ('settings.desktop', 'Settings fixture', 'Settings;System;', 'Settings'),
                    ('other.desktop', 'Other fixture', '', 'Other')]
        for desktop_id, title, categories, expected in fixtures:
            self.write(name=desktop_id, title=title, categories=categories)
        result = self.probe()
        self.assertEqual({app['id']: app['category'] for app in result}, {row[0]: row[3] for row in fixtures})
        self.assertEqual(len(result), len(fixtures))

    def test_unicode_and_shell_metacharacters_in_names_and_ids_are_plain_data(self):
        desktop_id = 'name $`;&|().desktop'; title = 'Spaced R\u00e4knare \U0001f680 $`;&|() <xml> "quoted"'
        self.write(name=desktop_id, title=title)
        result = self.probe(); self.assertEqual(result[0]['id'], desktop_id); self.assertEqual(result[0]['name'], title)

    def test_new_entry_and_removal_are_visible_without_daemon_restart(self):
        self.assertEqual(self.probe(), [])
        path = self.write(); self.assertEqual(len(self.probe()), 1)
        path.unlink(); self.assertEqual(self.probe(), [])

    def test_effective_wrapper_and_field_codes_launch_unprivileged_without_shell_interpolation(self):
        output = self.root / 'result'; output.mkdir()
        if os.geteuid() == 0: os.chown(output, self.uid, self.uid)
        executable = self.root / 'managed wrapper'
        executable.write_text('#!/usr/bin/python3\nimport json,os,sys\nfrom pathlib import Path\n'
                              'Path(os.environ["MENU_FIXTURE_OUTPUT"]).write_text(json.dumps({"uid":os.getuid(),"args":sys.argv[1:]}))\n')
        executable.chmod(0o755)
        result_path = output / 'argv.json'; self.env['MENU_FIXTURE_OUTPUT'] = str(result_path)
        marker = output / 'should-not-exist'
        title = f"Fixture $(touch {marker}) `id`; & | \U0001f680"
        self.write(self.vendor, title='Wrong lower entry', exec_value='/usr/bin/false')
        self.write(self.data, title=title, exec_value=f'"{executable}" %c %% %F %u')
        self.probe('--launch=app.desktop')
        deadline = time.monotonic() + 3
        while not result_path.exists() and time.monotonic() < deadline: time.sleep(0.01)
        self.assertTrue(result_path.exists())
        launched = json.loads(result_path.read_text())
        self.assertEqual(launched['uid'], self.uid); self.assertEqual(launched['args'], [title, '%'])
        self.assertFalse(marker.exists())

    def test_pygi_binding_runs_the_same_production_discovery_when_available(self):
        check = subprocess.run(['/usr/bin/python3', '-I', '-c',
                                'import gi; gi.require_version("GioUnix", "2.0"); from gi.repository import GioUnix'],
                               capture_output=True, text=True, timeout=5)
        if check.returncode: self.skipTest('python3-gi/GioUnix typelib unavailable on test host')
        self.write(); self.assertEqual(self.probe(pygi=True), self.probe())


if __name__ == '__main__':
    unittest.main()
