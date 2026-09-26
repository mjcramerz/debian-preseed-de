#!/usr/bin/env python3
"""Regressions for the supplied 2026-09-15 logs; no target service or build.

Only disposable directories and short-lived fixture processes are used. These
are not hardware, installed-kernel AppArmor, or graphical acceptance tests.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import python_library
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values

import io
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
PACKAGE = python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')
sys.path.insert(0, str(PACKAGE))
from labwc_managed_app import cli, dbus_proxy, generic, profiles


def load_script(name):
    path = TARGET / 'usr/local/bin' / name
    module = types.ModuleType('log_fixture_' + name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
    return module


class AccountStagingTests(unittest.TestCase):
    @unittest.skipUnless(os.geteuid() == 0, 'fixture chown requires root')
    def test_real_account_copy_loop_installs_git_metadata_and_preserves_private_modes(self):
        text = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))
        body = text.split('desktop_install_user_config() {', 1)[1].split('\ndesktop_unit_has_install_entry()', 1)[0]
        loop = re.search(r'^  for rel in \\\n.*?^done\n', body, re.M | re.S).group(0)
        rels = re.findall(r'^    ([.A-Za-z][^\s]+)\s*\\?$', loop, re.M)
        self.assertIn('.config/git', rels)
        self.assertIn('.config/gitops', rels)
        normalization = re.search(
            r'^find "\$account_home" -xdev -type d .*?^find "\$account_home" -xdev -type f ! .*?\n',
            body, re.M | re.S).group(0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); skel = root / 'skel'; home = root / 'home'
            for rel in rels:
                (skel / rel).mkdir(parents=True, exist_ok=True)
            samples = {'.config/git/config': '[user]\n\tname = Fixture\n',
                       '.config/gitops/gitops.env': 'GIT_ACCOUNT=fixture\n'}
            for rel, content in samples.items():
                (skel / rel).write_text(content)
                (skel / rel).chmod(0o644)
            script = ('set -eu\ninstall -d -m 0700 "$account_home" "$account_home/.config"\n' +
                      loop.replace('src="/etc/skel-desktop/${rel}"', 'src="${TEST_SKEL}/${rel}"') +
                      normalization)
            env = dict(os.environ, TEST_SKEL=str(skel), account_home=str(home),
                       uid='12345', gid='12345', copied_dirs='0')
            result = subprocess.run(payload_installed_argv(['/bin/sh', '-c', script]), env=env, capture_output=True,
                                    text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for rel, content in samples.items():
                installed = home / rel
                self.assertEqual(render_theme_defaults(payload_read_text(installed)), content)
                st = payload_source_stat(installed)
                self.assertEqual((st.st_uid, st.st_gid, st.st_mode & 0o777, st.st_nlink),
                                 (12345, 12345, 0o600, 1))
                self.assertEqual(payload_source_stat(installed.parent).st_mode & 0o777, 0o700)


    def test_firstboot_metadata_check_passes_complete_files_and_rejects_unsafe_replacements(self):
        text = render_theme_defaults(payload_read_text(FORKY / 'scripts/firstboot/04-validation.sh'))
        script = text.split("check_command git-account-metadata /bin/sh -eu -c '", 1)[1]
        script = script.split("\n    ' sh ", 1)[0]
        import pwd
        account = pwd.getpwuid(os.geteuid()).pw_name
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            files = ('.local/share/ssh/private/id_git_ed25519',
                     '.local/share/ssh/git-key-passphrase.gpg',
                     '.ssh/id_git_ed25519.pub', '.config/gitops/gitops.env',
                     '.config/git/config', '.config/systemd/user/labwc-ssh-key-load.service',
                     '.config/systemd/user/ssh-agent.socket')
            for relative in files:
                path = home / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('non-secret metadata fixture\n')
                path.chmod(0o600)
            wants = home / '.config/systemd/user/labwc-session.target.wants'
            wants.mkdir()
            for name in ('ssh-agent.socket',):
                (wants / name).symlink_to('../' + name)
            for directory in home.rglob('*'):
                if directory.is_dir():
                    directory.chmod(0o700)

            def validate():
                return subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', script, 'fixture', str(home), account]),
                                      capture_output=True, text=True, timeout=10).returncode

            self.assertEqual(validate(), 0)
            for relative in ('.config/git/config', '.config/gitops/gitops.env'):
                path = home / relative
                backup = home / 'fixture-backup'
                path.rename(backup)
                with self.subTest(path=relative, unsafe='missing'):
                    self.assertNotEqual(validate(), 0)
                path.symlink_to(backup)
                with self.subTest(path=relative, unsafe='symlink'):
                    self.assertNotEqual(validate(), 0)
                path.unlink()
                os.link(backup, path)
                with self.subTest(path=relative, unsafe='hardlink'):
                    self.assertNotEqual(validate(), 0)
                path.unlink()
                backup.rename(path)
                path.chmod(0o644)
                with self.subTest(path=relative, unsafe='public-mode'):
                    self.assertNotEqual(validate(), 0)
                path.chmod(0o600)
                self.assertEqual(validate(), 0)


class TutaPolicyTests(unittest.TestCase):
    def test_only_the_private_tray_item_can_be_owned(self):
        sandbox = profiles.PERSISTENT_SANDBOX_CONFIG['tutanota']
        self.assertEqual(sandbox['dbus_own_names'], ('org.freedesktop.StatusNotifierItem-2-1',))
        self.assertEqual(sandbox['dbus_names'], ('org.freedesktop.secrets', 'org.kde.StatusNotifierWatcher'))
        self.assertTrue(sandbox['require_session_bus'])
        self.assertTrue(sandbox['require_system_bus'])
        self.assertEqual(sandbox['system_dbus_names'], ('org.freedesktop.UPower',))
        runtime = mock.Mock()
        runtime.validate_session_bus_address.side_effect = lambda value: value
        with mock.patch.dict(os.environ, {'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}), \
             mock.patch.object(dbus_proxy, 'start_filtered_dbus_proxy', return_value=(None, None, None)) as start:
            dbus_proxy.start_session_bus_proxy('/fixture', sandbox['dbus_names'],
                                               sandbox['dbus_own_names'], required=True, runtime=runtime)
        args = start.call_args.args[3]
        self.assertIn('--own=org.freedesktop.StatusNotifierItem-2-1', args)
        self.assertNotIn('--own=org.freedesktop.*', args)
        self.assertNotIn('--own=org.kde.StatusNotifierWatcher', args)
        self.assertNotIn('--own=org.freedesktop.secrets', args)
        self.assertFalse(any('Item-*' in arg for arg in args))

    def test_native_tuta_still_unshares_pid_namespace_and_never_gets_x11(self):
        self.assertNotIn('tutanota', profiles.WAYLAND_COMPAT_APPS)
        source = render_theme_defaults(payload_read_text(PACKAGE / 'labwc_managed_app/bubblewrap.py'))
        self.assertIn('--unshare-all', source)
        self.assertNotIn('TUTA_DBUS_OWN_NAMES', render_theme_defaults(payload_read_text(PACKAGE / 'labwc_managed_app/wayland_compat.py')))


class TransientPropertyTests(unittest.TestCase):
    def command(self, executable, *arguments, kind='wayland'):
        with mock.patch.object(generic, 'assert_launch_allowed'), \
             mock.patch.object(generic, 'restart_token', return_value='fixture'), \
             mock.patch.object(generic, 'menu_action_wait_arguments', return_value=[]):
            return generic.transient_argv(kind, 'auto', [executable, *arguments], {})

    def test_timeshift_keeps_host_privileges_available_but_not_automatic(self):
        command = self.command('/usr/bin/timeshift-launcher')
        for key in ('PrivateTmp', 'PrivateIPC', 'ProtectSystem'):
            self.assertFalse(any(arg.startswith('--property=' + key + '=') for arg in command))
        for prop in ('NoNewPrivileges=no', 'Requisite=labwc-session.target', 'PartOf=labwc-session.target',
                     'KillMode=control-group', 'ExitType=cgroup', 'SendSIGKILL=yes', 'TimeoutStopSec=20s'):
            self.assertIn('--property=' + prop, command)
        self.assertNotIn('--uid=0', command)
        self.assertNotIn('/usr/bin/sudo', command)
        self.assertNotIn('--property=SuccessExitStatus=127', command)

    def test_namespaced_apps_and_similarly_named_untrusted_paths_keep_isolation(self):
        for executable in ('/usr/bin/focuswriter', '/tmp/timeshift-launcher', '/usr/local/bin/timeshift-launcher'):
            with self.subTest(executable=executable):
                command = self.command(executable)
                self.assertIn('--property=PrivateTmp=yes', command)
                self.assertIn('--property=PrivateIPC=yes', command)
                self.assertIn('--property=ProtectSystem=full', command)
        self.assertIn('--property=PrivateIPC=yes', self.command('/usr/bin/timeshift-launcher', kind='electron'))

    def test_only_default_shell_and_btop_get_hangup_status_classification(self):
        self.assertEqual(self.command('/usr/bin/foot')[-1], '/usr/bin/foot')
        self.assertIn('--property=SuccessExitStatus=1', self.command('/usr/bin/foot'))
        self.assertIn('--property=SuccessExitStatus=1', self.command('/usr/bin/foot', '-e', 'btop'))
        self.assertIn('--property=KillMode=mixed', self.command('/usr/bin/foot'))
        for executable, args in (('/usr/bin/foot', ('-e', '/bin/false')),
                                 ('/usr/bin/foot', ('/bin/false',)),
                                 ('/tmp/foot', ()), ('/usr/bin/kitty', ()),
                                 ('/usr/bin/timeshift-launcher', ())):
            command = self.command(executable, *args)
            self.assertFalse(any(arg.startswith('--property=SuccessExitStatus=') for arg in command))
        self.assertNotIn('--property=SuccessExitStatus=230', self.command('/usr/bin/foot'))


class DesktopAssetTests(unittest.TestCase):
    def test_focuswriter_serialized_font_is_a_qsettings_string_not_a_string_list(self):
        text = render_theme_defaults(payload_read_text(TARGET / 'etc/skel-desktop/.local/share/GottCode/FocusWriter/Themes/word.theme'))
        self.assertIn('\nFont="Noto Sans,12,-1,5,50,0,0,0,0,0"\n', text)
        self.assertNotIn('\nFont=Noto', text)

    def test_current_and_legacy_retroarch_vendor_desktop_ids(self):
        sync = load_script('labwc-sync-application-launchers')
        config = next(item for item in sync.APP_CONFIG if item['action_app'] == 'retroarch')
        with tempfile.TemporaryDirectory() as temporary, \
             mock.patch.object(sync, 'SYSTEM_APPLICATION_DIR', temporary):
            current = Path(temporary) / 'com.libretro.RetroArch.desktop'
            legacy = Path(temporary) / 'retroarch.desktop'
            self.assertIsNone(sync.find_desktop_file(config['desktop_names']))
            legacy.write_text('[Desktop Entry]\nType=Application\nExec=retroarch\n')
            self.assertEqual(sync.find_desktop_file(config['desktop_names'])[0], legacy.name)
            current.write_bytes(render_theme_bytes(payload_read_bytes(legacy)))
            self.assertEqual(sync.find_desktop_file(config['desktop_names'])[0], current.name)

    def test_scope_dropin_covers_all_app_prefixes_and_is_staged(self):
        units = TARGET / 'etc/skel-desktop/.config/systemd/user'
        found = list(units.glob('app-*.scope.d/*.conf'))
        path = units / 'app-.scope.d/50-session-labwc.conf'
        # The original lifecycle policy remains; launchers already select app.slice.
        # Resource-class policy is an additional, separately owned drop-in.
        self.assertEqual(set(found), {path, units / 'app-.scope.d/60-resource-class.conf'})
        text = render_theme_defaults(payload_read_text(path))
        for setting in ('Requisite=labwc-session.target', 'After=labwc-session.target',
                        'PartOf=labwc-session.target', 'KillMode=control-group',
                        'TimeoutStopSec=20s', 'SendSIGKILL=yes'):
            self.assertIn(setting, text)
        source = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))
        self.assertIn('"etc/skel-desktop/.config/systemd/user/app-.scope.d/50-session-labwc.conf"', source)
        self.assertNotIn('for scope_prefix in ', source)
        self.assertFalse(payload_source_exists(units / 'scope.d/50-session-labwc.conf'))

    def test_scope_stage_copies_actual_asset(self):
        source = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))
        stage = re.search(r'^  desktop_stage_role_asset \\\n    "etc/skel-desktop/\.config/systemd/user/app-\.scope\.d/50-session-labwc\.conf" \\\n.*?\n    0644\n', source, re.M | re.S).group(0)
        with tempfile.TemporaryDirectory() as temporary:
            script = """set -eu
desktop_stage_role_asset() {
  mkdir -p "$DEST$(dirname "$2")"
  install -m "$3" "$SOURCE/$1" "$DEST$2"
}
""" + stage
            result = subprocess.run(payload_installed_argv(['/bin/sh', '-c', script]),
                                    env=dict(os.environ, SOURCE=str(TARGET), DEST=temporary),
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            found = list(Path(temporary).glob('etc/skel-desktop/.config/systemd/user/*.scope.d/*.conf'))
            self.assertEqual(len(found), 1)
            for path in found:
                original = TARGET / path.relative_to(temporary)
                self.assertEqual(render_theme_bytes(payload_read_bytes(path)), render_theme_bytes(payload_read_bytes(original)))
                self.assertEqual(payload_source_stat(path).st_mode & 0o777, 0o644)


class AppArmorRegressionTests(unittest.TestCase):
    def profile(self, file, name):
        source = render_theme_defaults(payload_read_text(TARGET / 'etc/apparmor.d' / file))
        start = source.index('profile ' + name + ' ')
        following = source.find('\nprofile ', start + 1)
        return source[start:following if following >= 0 else None]

    def test_archive_helper_inherits_instead_of_creating_null_profiles(self):
        profile = self.profile('desktop-utilities', 'desktop-launcher')
        self.assertIn('/usr/lib/thunar-archive-plugin/xarchiver.tap rix,', profile)
        self.assertIn('/usr/bin/bwrap rCx -> application-bwrap,', profile)
        self.assertIn('owner /var/mail/* r,', profile)
        self.assertNotIn('/usr/lib/thunar-archive-plugin/**', profile)
        self.assertNotIn('flags=(complain', profile)

    def test_focuswriter_proc_and_qt_reads_are_local(self):
        profile = self.profile('document-applications', 'focuswriter')
        self.assertIn('owner @{PROC}/[0-9]*/{cmdline,stat} r,', profile)
        self.assertIn('/usr/share/qt6ct/colors/{,*.conf} r,', profile)
        self.assertNotIn('/proc/** rw', profile)

    def test_gpg_hardlink_permission_is_restricted_to_lock_names(self):
        profile = self.profile('desktop-wrappers', 'labwc-ssh-key-load')
        self.assertIn('owner @{HOME}/.gnupg/{.#lk*,pubring.kbx.lock} l,', profile)
        self.assertNotIn('owner @{HOME}/.gnupg/** rwkl', profile)

    def test_inherited_terminals_and_spotify_shutdown_have_explicit_permissions(self):
        for name in ('labwc-discord-command', 'labwc-zoom-command',
                     'labwc-wayland-compat-app'):
            self.assertIn('owner /dev/pts/[0-9]* rw,', self.profile('desktop-wrappers', name))
        native = self.profile('desktop-wrappers', 'labwc-app')
        self.assertIn('signal (send) set=(hup int term kill) peer=spotify,', native)
        self.assertIn('deny /opt/xwayland/** rxm,', native)
        spotify = self.profile('usr.bin.spotify', 'spotify')
        self.assertIn('signal (receive) set=(hup int term kill) peer=labwc-app,', spotify)


class SpotifyHandoffTests(unittest.TestCase):
    def run_fixture(self, program):
        output = types.SimpleNamespace(buffer=io.BytesIO())
        old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        with mock.patch.object(cli.sys, 'stdout', output), mock.patch.object(cli, 'emit'):
            status = cli._run_spotify([sys.executable, '-B', '-c', program], dict(os.environ))
        self.assertEqual(old_handlers, {sig: signal.getsignal(sig) for sig in old_handlers})
        return status, output.buffer.getvalue()

    def test_successful_second_instance_is_not_a_failed_service(self):
        code = 'import sys; print("Opening in existing browser session."); sys.exit(1)'
        status, output = self.run_fixture(code)
        self.assertEqual(status, 0)
        self.assertEqual(output, b'Opening in existing browser session.\n')

    def test_real_errors_and_nonexact_messages_remain_failures(self):
        for text, code in (('startup failed', 1), ('prefix Opening in existing browser session.', 1),
                           ('Opening in existing browser session.', 7), ('', 230)):
            with self.subTest(text=text, code=code):
                status, output = self.run_fixture(f'import sys; print({text!r}); sys.exit({code})')
                self.assertEqual(status, code)
                self.assertEqual(output, (text + '\n').encode())

    def test_long_output_is_streamed_and_does_not_create_a_false_line_match(self):
        code = 'import sys; print("x" * 200000 + "Opening in existing browser session."); sys.exit(1)'
        status, output = self.run_fixture(code)
        self.assertEqual(status, 1)
        self.assertGreater(len(output), 200000)

    def test_marker_split_over_writes_and_no_newline(self):
        code = '''import os, time
os.write(1, b"Opening in existing ")
time.sleep(0.08)
os.write(1, b"browser session.")
raise SystemExit(1)
'''
        self.assertEqual(self.run_fixture(code)[0], 0)

    def test_child_signal_is_not_success(self):
        self.assertEqual(self.run_fixture('import os, signal; os.kill(os.getpid(), signal.SIGTERM)')[0], 143)

    def test_missing_binary_remains_an_error(self):
        with self.assertRaises(FileNotFoundError):
            cli._run_spotify(['/nonexistent/spotify'], dict(os.environ))

    def test_surviving_descendant_pipe_does_not_hold_up_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'child.pid'
            code = f'''import os, time
pid = os.fork()
if pid == 0:
    time.sleep(3)
    os._exit(0)
open({str(pidfile)!r}, "w").write(str(pid))
print("Opening in existing browser session.", flush=True)
os._exit(1)
'''
            start = time.monotonic()
            try:
                self.assertEqual(self.run_fixture(code)[0], 0)
                self.assertLess(time.monotonic() - start, 2.0)
            finally:
                if payload_source_exists(pidfile):
                    try: os.kill(int(render_theme_defaults(payload_read_text(pidfile))), signal.SIGKILL)
                    except ProcessLookupError: pass

    def test_stop_signal_is_forwarded_to_the_child(self):
        runner = '''import os, sys
from labwc_managed_app.cli import _run_spotify
raise SystemExit(_run_spotify([sys.executable, '-B', '-c', sys.argv[1]], dict(os.environ)))
'''
        child_code = 'import time; print("READY", flush=True); time.sleep(20)'
        process = subprocess.Popen(payload_installed_argv([sys.executable, '-B', '-c', runner, child_code]),
                                   env=dict(os.environ, PYTHONPATH=str(PACKAGE)),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(5), 'fixture child did not start')
                self.assertEqual(process.stdout.readline(), b'READY\n')
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 143, stderr)
        finally:
            if process.poll() is None: process.kill()
            process.communicate()


if __name__ == '__main__':
    unittest.main()
