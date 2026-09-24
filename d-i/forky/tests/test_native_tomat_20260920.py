"""Profile-scoped hardware and native menu regressions (no live host changes).

Unit/fixture tests use temporary roots and mocked systemd/HTTP endpoints. Native
GTK builder and AppArmor parser tests run only when their host tools exist.
These are not a boot, hardware, vendor-binary or kernel-mediation qualification.
"""
from __future__ import annotations
from payload_fixture import waybar_config_text
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_path as payload_source_path, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import contextlib
import copy
import ctypes.util
import io
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
LIBEXEC = TARGET / 'usr/local/libexec'
SKEL = TARGET / 'etc/skel-desktop/.config'


def load(name):
    path = LIBEXEC / name
    module = types.ModuleType('fixture_' + name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
    return module


def bars():
    from waybar_fixture import rendered_assets
    assets = rendered_assets(FORKY / 'hosts/profiles/btrfs-de.env')
    return json.loads(assets['config'])


class HardwareProfileTests(unittest.TestCase):
    def test_exact_profile_assignments_and_no_cpu_inference(self):
        expected = {
            'btrfs-de-p15s.env': '79-thinkpad-acpi.conf',
            'btrfs-de-p15s-duo.env': '79-thinkpad-acpi.conf',
            'btrfs-de-flex.env': '79-ideapad-acpi.conf',
            'btrfs-de-flex-duo.env': '79-ideapad-acpi.conf',
        }
        expected.update({p.name: '79-chromebook.conf' for p in (FORKY / 'hosts/profiles').glob('f2fs-*.env')})
        self.assertEqual(len(expected), 8)
        for name, selected in expected.items():
            text = render_theme_defaults(payload_read_text(FORKY / 'hosts/profiles' / name))
            self.assertEqual(re.findall(r'^SYSTEM_HARDWARE_SPEC="([^"]+)"$', text, re.M), [selected])
        self.assertNotIn('79-thinkpad', render_theme_defaults(payload_read_text(FORKY / 'classes/configs/target-assets.tsv')))
        chromebook = render_theme_defaults(payload_read_text(TARGET / 'etc/modprobe.d/79-chromebook.conf'))
        self.assertIn('options mmc_block mmcblk.perdev_minors=16', chromebook)
        self.assertNotIn('options mmc_block perdev_minors=', chromebook)
        self.assertIn('options i915 enable_dpcd_backlight=1', render_theme_defaults(payload_read_text(TARGET / 'etc/modprobe.d/79-thinkpad-acpi.conf')))
        for name in ('79-ideapad-acpi.conf', '79-chromebook.conf'):
            active = '\n'.join(line for line in render_theme_defaults(payload_read_text(TARGET / 'etc/modprobe.d' / name)).splitlines() if not line.startswith('#'))
            self.assertNotIn('fan_control', active)
            self.assertNotIn('options f2fs', active)
        self.assertFalse(payload_source_exists(TARGET / 'etc/udev/hwdb.d/90-thinkpad-extra-buttons.hwdb'))

    def stage(self, target, selected):
        q = shlex.quote
        code = f'''
BOOTPROFILE_DEFAULT=balanced; BOOTPROFILE_HARDENED=hardened; BOOTPROFILE_PERFORMANCE=performance
INSTALLER_SOURCE_ROOT={q(str(FORKY))}
INSTALLER_SOURCE_LIBRARY={q(str(FORKY / 'scripts/common/source.sh'))}
. {q(str(FORKY / 'hosts/installer/runtime.env'))}
. {q(str(FORKY / 'scripts/common/lib.sh'))}
. {q(str(FORKY / 'scripts/common/target.sh'))}
. {q(str(FORKY / 'scripts/late/target-assets.sh'))}
INSTALLER_TARGET_DIR={q(str(target))}
DIR_HOOKS_TARGET={q(str(TARGET))}
SYSTEM_HARDWARE_SPEC={q(selected)}
installer_repo_join_var() {{ printf '%s/%s\\n' "$DIR_HOOKS_TARGET" "$2"; }}
fetch_hook() {{ fixture_input=$1; [ -f "$fixture_input" ] || fixture_input=$fixture_input.tmpl; cp "$fixture_input" "$2"; }}
stage_target_hardware_spec
'''
        return subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', code]), text=True, capture_output=True, timeout=10)

    def test_real_publish_switch_cleanup_and_unowned_preservation(self):
        with tempfile.TemporaryDirectory() as work:
            target = Path(work)
            destination = target / 'etc/modprobe.d'
            destination.mkdir(parents=True)
            admin = destination / '79-site.conf'
            admin.write_text('# unowned\n')
            for name in ('79-thinkpad-acpi.conf', '79-ideapad-acpi.conf', '79-chromebook.conf', ''):
                result = self.stage(target, name)
                self.assertEqual(result.returncode, 0, result.stderr)
                managed = sorted(p.name for p in destination.glob('79-*.conf') if p != admin)
                self.assertEqual(managed, [name] if name else [])
                self.assertEqual(render_theme_defaults(payload_read_text(admin)), '# unowned\n')
                if name:
                    self.assertEqual(render_theme_bytes(payload_read_bytes(destination / name)), render_theme_bytes(payload_read_bytes(TARGET / 'etc/modprobe.d' / name)))
                    self.assertEqual(stat.S_IMODE(payload_source_stat(destination / name).st_mode), 0o644)

    def test_invalid_selection_fails_before_deleting_existing_policy(self):
        with tempfile.TemporaryDirectory() as work:
            target = Path(work)
            self.assertEqual(self.stage(target, '79-thinkpad-acpi.conf').returncode, 0)
            before = {p.name: render_theme_bytes(payload_read_bytes(p)) for p in (target / 'etc/modprobe.d').iterdir()}
            for name in ('../../etc/passwd', '79-site.conf', '*', '79-thinkpad-acpi.conf;true'):
                self.assertNotEqual(self.stage(target, name).returncode, 0)
                self.assertEqual(before, {p.name: render_theme_bytes(payload_read_bytes(p)) for p in (target / 'etc/modprobe.d').iterdir()})

    def test_symlink_directory_is_not_followed(self):
        with tempfile.TemporaryDirectory() as work:
            target = Path(work) / 'target'
            (target / 'etc').mkdir(parents=True)
            outside = Path(work) / 'outside'; outside.mkdir()
            (target / 'etc/modprobe.d').symlink_to(outside)
            self.assertNotEqual(self.stage(target, '79-thinkpad-acpi.conf').returncode, 0)
            self.assertEqual(list(outside.iterdir()), [])


class TomatControllerTests(unittest.TestCase):
    def setUp(self):
        self.mod = load('labwc-tomat')
        self.text = render_theme_defaults(payload_read_text(SKEL / 'tomat/config.toml'))

    def test_defaults_and_hooks_are_valid(self):
        data = self.mod.validate_config(self.text)
        self.assertEqual(data['timer'], dict(work=45.0, long_break=15.0, sessions=3, auto_advance='to-break', **{'break': 5.0}))
        self.assertEqual(set(data['hooks']), {'on_break_start', 'on_long_break_start'})
        self.assertEqual(data['hooks']['on_break_start']['timeout'], 3)

    def test_reject_invalid_types_limits_keys_and_hook_authority(self):
        for old, new in [('work = 45.0', 'work = nan'), ('work = 45.0', 'work = true'),
                         ('work = 45.0', 'work = 601'), ('sessions = 3', 'sessions = 0'),
                         ('volume = 0.3', 'volume = 2.0'), ('timeout = 8000', 'timeout = -1'),
                         ('timeout = 3', 'timeout = 0'), ('capture_output = true', 'capture_output = false'),
                         ('text_format = "{icon} {time}"', 'text_format = 7'),
                         ('cmd = "/usr/local/libexec/labwc-tomat-hook"', 'cmd = "/bin/sh"'),
                         ('args = ["break"]', 'args = ["break", "extra"]'),
                         ('sessions = 3', 'session = 3')]:
            with self.subTest(replacement=new), self.assertRaises((ValueError, self.mod.Error)):
                self.mod.validate_config(self.text.replace(old, new))
        with self.assertRaises(self.mod.Error):
            self.mod.validate_config(self.text + '\ncwd = "/tmp"\n')
        with self.assertRaises(self.mod.Error):
            self.mod.validate_config(' ' * (self.mod.MAX_CONFIG + 1))

    def test_toggles_preserve_unrelated_config_and_comments(self):
        for setting, section, key, changed in [('notifications', 'notification', 'enabled', False), ('sounds', 'sound', 'mode', 'none')]:
            result, message = self.mod.change_setting(self.text, setting)
            self.assertEqual(self.mod.validate_config(result)[section][key], changed)
            again, _ = self.mod.change_setting(result, setting)
            self.assertEqual(again, self.text)
            self.assertTrue(message)
        text, _ = self.mod.change_setting('[sound]\nvolume = 0.4', 'sounds')
        self.assertEqual(self.mod.validate_config(text)['sound']['mode'], 'none')

    def test_ambiguous_layout_is_not_rewritten(self):
        with self.assertRaises(self.mod.Error):
            self.mod.change_setting('sound = {mode="embedded"}\n', 'sounds')

    def context(self, work):
        ctx = self.mod.Context.__new__(self.mod.Context)
        ctx.uid = os.getuid(); ctx.directory = Path(work); ctx.config = ctx.directory / 'config.toml'
        ctx.runtime = Path(work); ctx.env = {'PATH': '/usr/bin:/bin'}
        ctx.config.write_text(self.text); ctx.config.chmod(0o600)
        ctx.show = mock.Mock(return_value={'LoadState': 'loaded', 'ActiveState': 'active', 'Transient': 'yes', 'Description': self.mod.DESCRIPTION})
        ctx.run = mock.Mock(); ctx.wait_ready = mock.Mock(); ctx.session_ready = mock.Mock()
        return ctx

    def test_settings_atomic_permissions_and_restart_only_owned_unit(self):
        with tempfile.TemporaryDirectory() as work:
            ctx = self.context(work)
            before = payload_source_stat(ctx.config).st_ino
            with contextlib.redirect_stdout(io.StringIO()): ctx.setting('sounds')
            self.assertEqual(stat.S_IMODE(payload_source_stat(ctx.config).st_mode), 0o600)
            self.assertNotEqual(payload_source_stat(ctx.config).st_ino, before)
            self.assertEqual(self.mod.validate_config(render_theme_defaults(payload_read_text(ctx.config)))['sound']['mode'], 'none')
            ctx.run.assert_called_once_with([self.mod.SYSTEMCTL, '--user', 'restart', self.mod.UNIT])
            self.assertEqual(sorted(p.name for p in Path(work).iterdir()), ['config.toml'])

    def test_concurrent_config_edit_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as work:
            ctx = self.context(work)
            original = render_theme_defaults(payload_read_text(ctx.config))
            def edit(*_):
                ctx.config.write_text(original + '\n# concurrent user edit\n')
                return 'fixture'
            with mock.patch.object(self.mod.secrets, 'token_hex', side_effect=edit), self.assertRaises(self.mod.Error):
                ctx.setting('sounds')
            self.assertIn('# concurrent user edit', render_theme_defaults(payload_read_text(ctx.config)))
            ctx.run.assert_not_called()

    def test_symlink_fifo_hardlink_and_world_writable_config_rejected(self):
        for kind in ('symlink', 'fifo', 'hardlink', 'permissions'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as work:
                ctx = self.context(work)
                if kind == 'permissions': ctx.config.chmod(0o666)
                else:
                    original = ctx.directory / 'original'; ctx.config.rename(original)
                    if kind == 'symlink': ctx.config.symlink_to(original)
                    elif kind == 'fifo': os.mkfifo(ctx.config, 0o600)
                    else: os.link(original, ctx.config)
                with self.assertRaises((OSError, self.mod.Error)), ctx.config_file(): pass

    def test_lock_refuses_symlink_and_checks_private_mode(self):
        with tempfile.TemporaryDirectory() as work:
            ctx = self.context(work)
            lock = Path(work) / 'labwc-tomat-control.lock'
            lock.symlink_to(ctx.config)
            with self.assertRaises(OSError), ctx.locked(): pass
            lock.unlink(); lock.touch(mode=0o644)
            with self.assertRaises(self.mod.Error), ctx.locked(): pass
            lock.chmod(0o600)
            with ctx.locked(): pass

    def test_transient_daemon_contract_no_implicit_privileged_features(self):
        with tempfile.TemporaryDirectory() as work:
            ctx = self.context(work); ctx.show.return_value = {'LoadState': 'not-found'}
            ctx.ensure()
            command = ctx.run.call_args.args[0]
            self.assertEqual(command[-3:], ['/usr/bin/tomat', 'daemon', 'run'])
            for item in ('--property=PartOf=labwc-session.target', '--property=KillMode=control-group',
                         '--property=NoNewPrivileges=yes', '--property=RestrictAddressFamilies=AF_UNIX',
                         '--property=RuntimeDirectoryPreserve=restart', '--property=TasksMax=64'):
                self.assertIn(item, command)
            self.assertNotIn('--collect', command)
            self.assertFalse(any('AppArmorProfile=' in item for item in command))
            self.assertNotIn('daemon start', ' '.join(command))

    def test_failed_or_foreign_unit_is_not_reset_or_replaced(self):
        with tempfile.TemporaryDirectory() as work:
            ctx = self.context(work)
            for transient, description, state in [('no', self.mod.DESCRIPTION, 'active'),
                                                  ('yes', 'Other daemon', 'inactive'),
                                                  ('yes', self.mod.DESCRIPTION, 'failed')]:
                ctx.show.return_value = dict(LoadState='loaded', Transient=transient, Description=description, ActiveState=state)
                with self.assertRaises(self.mod.Error): ctx.ensure()
                ctx.run.assert_not_called()

    def test_readiness_checks_actual_unix_peer_pid_and_protocol(self):
        for correct_pid, success in ((True, True), (False, True), (True, False)):
            with self.subTest(correct_pid=correct_pid, success=success), tempfile.TemporaryDirectory() as work:
                ctx = self.context(work); directory = Path(work) / 'labwc-tomat'; directory.mkdir(mode=0o700)
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(str(directory / 'tomat.sock')); server.listen(1); server.settimeout(2)
                def serve():
                    with server:
                        connection, _ = server.accept()
                        with connection:
                            connection.settimeout(2)
                            if connection.recv(4096):
                                connection.sendall(json.dumps({'success': success}).encode() + b'\n')
                thread = threading.Thread(target=serve); thread.start()
                try:
                    if correct_pid and success: ctx.ready(os.getpid())
                    else:
                        with self.assertRaises(self.mod.Error): ctx.ready(os.getpid() if correct_pid else os.getpid() + 1)
                finally: thread.join(3)
                self.assertFalse(thread.is_alive())

    def test_root_and_invalid_dispatch_rejected_before_manager_use(self):
        with mock.patch.object(self.mod.os, 'getuid', return_value=0), self.assertRaises(self.mod.Error): self.mod.Context()
        for args in ([], ['start', '999'], ['toggle', 'extra'], ['settings', 'arbitrary'], ['daemon', 'start']):
            with self.subTest(args=args), mock.patch.object(self.mod, 'Context') as ctx, self.assertRaises(self.mod.Error):
                self.mod.main(args)
            ctx.assert_not_called()


class MenuAndHookTests(unittest.TestCase):
    def test_xml_ids_match_every_bar_action_and_no_fuzzel_power_binding(self):
        import xml.etree.ElementTree as ET
        for bar in bars():
            for module, name, event in [('custom/tomat','tomat','on-click-right'), ('pulseaudio','audio','on-click-right'),
                                       ('custom/notifications','notifications','on-click'), ('custom/power','power','on-click'),
                                       ('clock','calendar','on-click-right')]:
                entry = bar[module]
                self.assertEqual(entry['menu'], event); self.assertNotIn(event, entry)
                tree = ET.parse(payload_source_path(SKEL / 'waybar' / (name + '-menu.xml')))
                ids = [node.get('id') for node in tree.iter('object') if node.get('class') == 'GtkMenuItem' and node.get('id')]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual(set(ids), set(entry['menu-actions']))
                for command in entry['menu-actions'].values():
                    self.assertIn('--property=PartOf=labwc-session.target', command)
                    self.assertIn('--property=KillMode=control-group', command)
                self.assertNotIn('labwc-power-menu', json.dumps(entry))
            self.assertEqual(bar['custom/tomat']['restart-interval'], 5)
            self.assertFalse(bar['custom/tomat']['exec-on-event'])

    def test_gtk_builder_accepts_all_five_nested_native_menus(self):
        if not shutil.which('xvfb-run') or not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3 / Xvfb unavailable')
        code = r'''
import ctypes as C, ctypes.util, sys, xml.etree.ElementTree as ET
G=C.CDLL(ctypes.util.find_library("gtk-3")); O=C.CDLL(ctypes.util.find_library("gobject-2.0"))
G.gtk_init_check.argtypes=[C.c_void_p,C.c_void_p]; G.gtk_init_check.restype=C.c_int
assert G.gtk_init_check(None,None)
G.gtk_builder_new.restype=C.c_void_p
G.gtk_builder_add_from_file.argtypes=[C.c_void_p,C.c_char_p,C.POINTER(C.c_void_p)]; G.gtk_builder_add_from_file.restype=C.c_uint
G.gtk_builder_get_object.argtypes=[C.c_void_p,C.c_char_p]; G.gtk_builder_get_object.restype=C.c_void_p
O.g_object_unref.argtypes=[C.c_void_p]
for path in sys.argv[1:]:
    builder=G.gtk_builder_new(); error=C.c_void_p()
    assert G.gtk_builder_add_from_file(builder,path.encode(),C.byref(error)), path
    for obj in ET.parse(path).iter("object"):
        if obj.get("id"): assert G.gtk_builder_get_object(builder,obj.get("id").encode()), obj.get("id")
    O.g_object_unref(builder)
print("GTK3 native menu builders: 5 passed")
'''
        from waybar_fixture import rendered_assets
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            menus = []
            for name, text in rendered_assets(FORKY/'hosts/profiles/btrfs-de.env').items():
                if name.endswith('-menu.xml'):
                    path = root/name; path.write_text(text); menus.append(str(path))
            result = subprocess.run(payload_installed_argv(['xvfb-run', '-a', '/usr/bin/python3', '-I', '-c', code, *menus]),
                                    text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_media_hook_is_bounded_and_never_resumes(self):
        hook = load('labwc-tomat-hook')
        with mock.patch.object(hook.os, 'getuid', return_value=1000), mock.patch.object(hook.os, 'geteuid', return_value=1000):
            for action, event in [('break','break_start'), ('long-break','long_break_start')]:
                with mock.patch.dict(os.environ, {'TOMAT_EVENT': event, 'XDG_RUNTIME_DIR': '/run/user/1000'}, clear=True), \
                     mock.patch.object(hook.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as run:
                    self.assertEqual(hook.main([action]), 0)
                    self.assertEqual(run.call_args.args[0], ['/usr/bin/playerctl', '--all-players', 'pause'])
                    self.assertLess(run.call_args.kwargs['timeout'], 3)
                    self.assertNotIn('shell', run.call_args.kwargs)
            with mock.patch.dict(os.environ, {'TOMAT_EVENT':'wrong'}, clear=True), self.assertRaises(ValueError): hook.main(['break'])

    def test_notification_data_bounds_and_plain_text(self):
        mod = load('labwc-notifications')
        text = '<b>not markup</b> $(not-a-command)'
        data = mod.notification_list(json.dumps([{'summary':text,'body':'x'*10000}]))
        self.assertEqual(data[0]['summary'], text)
        self.assertEqual(len(data[0]['body']),8192)
        for bad in ({}, [1], [{}]*1025):
            with self.assertRaises(mod.Error): mod.notification_list(json.dumps(bad))
        source = render_theme_defaults(payload_read_text(LIBEXEC / 'labwc-notifications'))
        self.assertNotIn('set_markup(', source)
        self.assertIn('"dismiss", "--all", "--no-history"', source)
        self.assertIn('max_workers=1', source)

    def test_apparmor_profiles_parse_offline_and_are_staged(self):
        parser=shutil.which('apparmor_parser')
        if not parser: self.skipTest('AppArmor parser unavailable')
        for name in ('tomat','waybar-menus'):
            result=subprocess.run(payload_installed_argv([parser,'-Q','-T','-I',str(TARGET/'etc/apparmor.d'),str(TARGET/'etc/apparmor.d'/name)]),
                                  text=True,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(name,render_theme_defaults(payload_read_text(FORKY/'scripts/late/security.sh')))
            self.assertIn('__DESKTOP_APPARMOR_STATE__ required '+name+' -',render_theme_defaults(payload_read_text(TARGET/'etc/apparmor/modes.conf.tmpl')))


class TomatRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.mod=load('apt-repo-local')
        self.source=self.mod.source_for('https://github.com/jolars/tomat/releases/latest/download/tomat_amd64.deb')
        self.release={'id':1,'tag_name':'v2.13.0','published_at':'2026-01-01T00:00:00Z','draft':False,'prerelease':False,
                      'assets':[{'id':2,'name':'tomat_amd64.deb','browser_download_url':'https://github.com/jolars/tomat/releases/download/v2.13.0/tomat_amd64.deb',
                                 'size':1000000,'digest':'sha256:'+'a'*64,'state':'uploaded'}]}

    def discover(self, release):
        with tempfile.TemporaryDirectory() as work:
            discovery=self.mod.Discovery(Path(work))
            with mock.patch.object(discovery,'metadata',return_value=json.dumps([release]).encode()):
                return discovery.release(self.source,'tomat','amd64',Path(work))

    def test_updater_follows_only_the_approved_stable_asset(self):
        result=self.discover(self.release)
        self.assertEqual(result['sha256'],'a'*64)
        self.assertEqual(result['name'],'tomat_amd64.deb')
        self.assertEqual(result['version'],'2.13.0')

    def test_updater_rejects_missing_digest_bounds_wrong_origin_and_ambiguity(self):
        for key,value in [('digest',None),('size',1),('size',134217729),
                          ('browser_download_url','https://github.com/other/project/releases/download/v2.13.0/tomat_amd64.deb')]:
            release=copy.deepcopy(self.release); release['assets'][0][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(self.mod.Error): self.discover(release)
        release=copy.deepcopy(self.release);release['assets'].append(copy.deepcopy(release['assets'][0]))
        with self.assertRaises(self.mod.Error):self.discover(release)

    def test_tomat_release_version_must_match_verified_tag(self):
        fields = {"Package": "tomat", "Architecture": "amd64", "Version": "2.13.0-1"}
        self.mod.verify_tomat_release_version(fields, "2.13.0")
        for key, bad in (("Package", "other"), ("Architecture", "all"),
                         ("Version", "9.0.0"), ("Version", "2.13.0evil")):
            with self.subTest(key=key), self.assertRaises(self.mod.Error):
                self.mod.verify_tomat_release_version({**fields, key: bad}, "2.13.0")

    def test_tomat_archive_requires_real_nonprivileged_executable(self):
        if not shutil.which("dpkg-deb"): self.skipTest("dpkg-deb unavailable")
        with tempfile.TemporaryDirectory() as work:
            root = Path(work); tree = root / "tree"; control = tree / "DEBIAN"
            control.mkdir(parents=True); executable = tree / "usr/bin/tomat"
            executable.parent.mkdir(parents=True)
            (control / "control").write_text("Package: tomat\nVersion: 2.13.0-1\nArchitecture: amd64\nMaintainer: Fixture <fixture@example.invalid>\nDescription: Offline archive fixture; not Tomat\n")
            executable.write_text("#!/bin/sh\nexit 0\n")
            for mode in (0o755, 0o644, 0o4755, 0o777):
                executable.chmod(mode); package = root / (str(mode) + ".deb")
                subprocess.run(payload_installed_argv(["dpkg-deb", "--root-owner-group", "--build", str(tree), str(package)]),
                               check=True, capture_output=True, timeout=10)
                if mode == 0o755:
                    self.assertEqual(self.mod.inspect_deb(package, {"amd64"})["Version"], "2.13.0-1")
                else:
                    with self.subTest(mode=mode), self.assertRaises(self.mod.Error):
                        self.mod.inspect_deb(package, {"amd64"})
            executable.unlink(); executable.symlink_to("/usr/bin/true")
            package = root / "symlink.deb"
            subprocess.run(payload_installed_argv(["dpkg-deb", "--root-owner-group", "--build", str(tree), str(package)]),
                           check=True, capture_output=True, timeout=10)
            with self.assertRaises(self.mod.Error): self.mod.inspect_deb(package, {"amd64"})

    def test_no_dedicated_tomat_upgrade_assets_or_installer_wiring(self):
        retired = (
            'etc/systemd/system/apt-repo-local-tomat-upgrade.service',
            'etc/systemd/system/apt-repo-local-refresh.service.d/70-tomat-upgrade.conf',
            'etc/apt/tomat-unattended.conf',
            'usr/local/share/software/tomat/apt.conf',
        )
        stage = render_theme_defaults(payload_read_text(FORKY / 'scripts/late/software.sh'))
        verify = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/verify.sh'))
        for relative in retired:
            with self.subTest(relative=relative):
                self.assertFalse(payload_source_exists(TARGET / relative))
                self.assertFalse((TARGET / relative).is_symlink())
                self.assertNotIn(relative, stage)
                self.assertNotIn(relative, verify)
        self.assertFalse(payload_source_exists(TARGET / 'etc/systemd/system/apt-repo-local-tomat-upgrade.timer'))

    def test_shared_refresh_and_normal_apt_maintenance_remain(self):
        service = render_theme_defaults(payload_read_text(TARGET / 'etc/systemd/system/apt-repo-local-refresh.service'))
        timer = render_theme_defaults(payload_read_text(TARGET / 'etc/systemd/system/apt-repo-local-refresh.timer'))
        periodic = render_theme_defaults(payload_read_text(TARGET / 'etc/apt/apt.conf.d/20auto-upgrades'))
        self.assertIn('ExecStart=/usr/local/bin/apt-repo-init --refresh', service)
        self.assertNotIn('unattended-upgrade', service)
        self.assertNotIn('OnSuccess=', service)
        self.assertIn('OnCalendar=weekly', timer)
        self.assertIn('APT::Periodic::Unattended-Upgrade "1";', periodic)
        self.assertIn('tomat', render_theme_defaults(payload_read_text(FORKY / 'scripts/late/software.sh')))

    def test_perl_bootstrap_release_metadata_validation(self):
        from test_managed_external_software import ManagedAPTRepoLocalTests
        code=r'''
use APTRepoLocal::Servicing::Tomat;
use JSON::PP;
my $adapter=APTRepoLocal::Servicing::Tomat->new(http=>bless({},'Fixture'),deb=>bless({},'Fixture'));
my $value=$adapter->_release($ARGV[0]); print JSON::PP->new->canonical->encode($value);
'''
        with tempfile.TemporaryDirectory() as work:
            path=Path(work)/'release.json';path.write_text(json.dumps(self.release))
            result=ManagedAPTRepoLocalTests.run_perl(self,code,path)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['sha256'],'a'*64)
            self.release['assets'][0]['digest']=None;path.write_text(json.dumps(self.release))
            result=ManagedAPTRepoLocalTests.run_perl(self,code,path)
            self.assertNotEqual(result.returncode,0)


if __name__ == '__main__': unittest.main()
