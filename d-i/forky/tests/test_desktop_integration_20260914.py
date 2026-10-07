#!/usr/bin/env python3
"""Offline regressions for the supplied 2026-09-14 desktop incident.

No application builds, target services, mounts, firmware changes or kernel
policy loads. Real filesystem/menu tests use private temporary fixtures;
service and D-Bus assertions inspect commands at the launch boundary.
"""
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import python_library
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from contextlib import ExitStack
import configparser
import json
import os
from pathlib import Path
import re
import stat
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
from labwc_managed_app import dbus_proxy, environment, generic, profiles, sandbox, session


def load_script(name):
    path = TARGET / 'usr/local/bin' / name
    module = types.ModuleType('fixture_' + name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(payload_read_bytes(path), str(path), 'exec'), module.__dict__)
    return module


class TutaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tuta-integration-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.config/tutanota-desktop').mkdir(parents=True)
        (self.home / '.local/share/applications').mkdir(parents=True)
        self.mime = self.home / '.config/mimeapps.list'
        self.mime.write_text('[Default Applications]\nx-scheme-handler/mailto=tutanota-desktop.desktop;\n')
        self.desktop = self.home / '.local/share/applications/tutanota-desktop.desktop'
        self.desktop.write_text('[Desktop Entry]\nType=Application\nExec=labwc-app launch tutanota %U\n')
        self.account = self.home / '.config/tutanota-desktop/account-state'
        self.account.write_text('account data must survive')
        self.private = self.home / '.local/state/tutanota-desktop/desktop-integration'

    def prepare(self):
        sandbox.prepare_tuta_integration(str(self.home))

    def test_persistent_private_seed_is_idempotent_and_host_is_unchanged(self):
        self.prepare()
        self.assertEqual(payload_read_bytes(self.private / 'config/mimeapps.list'), payload_read_bytes(self.mime))
        (self.private / 'applications/tutanota-desktop.desktop').write_text('Tuta-owned integration')
        (self.private / 'config/tuta_integration').mkdir()
        remember = self.private / 'config/tuta_integration/no_integration'
        remember.write_text('remembered application state')
        self.prepare()
        self.assertEqual(payload_read_text(remember), 'remembered application state')
        self.assertEqual(payload_read_text(self.private / 'applications/tutanota-desktop.desktop'), 'Tuta-owned integration')
        self.assertIn('labwc-app', payload_read_text(self.desktop))
        self.assertEqual(payload_read_text(self.account), 'account data must survive')

    def test_mime_file_can_be_atomically_replaced(self):
        self.prepare()
        temporary = self.private / 'config/mimeapps.list.new'
        temporary.write_text('new private MIME state')
        os.replace(temporary, self.private / 'config/mimeapps.list')
        self.assertEqual(payload_read_text(self.private / 'config/mimeapps.list'), 'new private MIME state')
        self.assertIn('[Default Applications]', payload_read_text(self.mime))

    def test_destination_symlink_is_not_followed(self):
        self.prepare()
        destination = self.private / 'applications/tutanota-desktop.desktop'
        destination.unlink()
        destination.symlink_to(self.desktop)
        with self.assertRaises((SystemExit, OSError)):
            self.prepare()
        self.assertIn('labwc-app', payload_read_text(self.desktop))

    def test_seed_symlink_is_rejected(self):
        self.mime.unlink()
        self.mime.symlink_to(self.account)
        with self.assertRaises(SystemExit):
            self.prepare()
        self.assertEqual(payload_read_text(self.account), 'account data must survive')

    def test_absent_seed_is_not_replaced_with_invalid_empty_desktop(self):
        self.desktop.unlink()
        self.prepare()
        self.assertFalse(payload_source_exists(self.private / 'applications/tutanota-desktop.desktop'))

    def test_private_directories_and_seed_modes(self):
        self.prepare()
        for source, _destination in profiles.TUTA_INTEGRATION_DIRECTORY_BINDS:
            self.assertEqual(stat.S_IMODE(payload_source_stat(self.home / source).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.private / 'config/mimeapps.list').st_mode), 0o600)

    def test_mount_order_does_not_hide_account_state_or_bind_host_mime_inode(self):
        config = profiles.PERSISTENT_SANDBOX_CONFIG['tutanota']
        self.assertEqual(config['integration_directory_binds'][0][1], '.config')
        self.assertIn('.config/tutanota-desktop', config['persistent_paths'])
        self.assertNotIn('.config/mimeapps.list', config['ro_bind_home_paths'])
        self.assertNotIn('.local/share/applications/tutanota-desktop.desktop', config['ro_bind_home_paths'])
        source = payload_read_text(PACKAGE / 'labwc_managed_app/sandbox.py')
        self.assertLess(source.index('sandbox.get("integration_directory_binds"'),
                        source.index('for directory in persistent_directories:'))

    def test_shared_ipc_directory_is_stable_private_and_rejects_symlinks(self):
        name = profiles.PERSISTENT_SANDBOX_CONFIG['tutanota']['shared_temp_directory']
        path = Path(sandbox.persistent_runtime_directory(str(self.home), name))
        (path / 'cookie').write_text('live singleton')
        self.assertEqual(sandbox.persistent_runtime_directory(str(self.home), name), str(path))
        self.assertEqual(payload_read_text(path / 'cookie'), 'live singleton')
        self.assertEqual(stat.S_IMODE(payload_source_stat(path).st_mode), 0o700)
        (self.home / 'bad').symlink_to(path, target_is_directory=True)
        with self.assertRaises(SystemExit):
            sandbox.persistent_runtime_directory(str(self.home), 'bad')


class MailDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.sync = load_script('labwc-sync-application-launchers')
        self.temp = tempfile.TemporaryDirectory(prefix='mail-defaults-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / '.config').mkdir()
        self.mime = self.home / '.config/mimeapps.list'

    def repair(self):
        return self.sync.synchronize_tuta_mime_defaults(str(self.home), os.getuid(), os.getgid())

    def test_repairs_only_mail_associations_preserving_other_choices_and_comments(self):
        self.mime.write_text('# keep this comment\n[Default Applications]\n'
            'text/plain=my-editor.desktop;\nx-scheme-handler/mailto=tuta-mail.desktop;\n'
            'message/rfc822=tuta-mail.desktop;\n[Removed Associations]\n'
            'x-scheme-handler/mailto=tuta-mail.desktop;other-mail.desktop;\n')
        self.assertTrue(self.repair())
        content = payload_read_text(self.mime)
        self.assertIn('# keep this comment', content)
        self.assertIn('text/plain=my-editor.desktop;', content)
        self.assertNotIn('message/rfc822', content)
        p = configparser.ConfigParser(interpolation=None)
        p.read_string(content)
        for section in ('Default Applications', 'Added Associations'):
            for scheme in self.sync.TUTA_SCHEMES:
                self.assertEqual(p[section][scheme], 'tutanota-desktop.desktop;')
        self.assertEqual(p['Removed Associations']['x-scheme-handler/mailto'], 'other-mail.desktop;')
        self.assertFalse(self.repair())

    def test_keeps_non_tuta_rfc822_handler(self):
        self.mime.write_text('[Default Applications]\nmessage/rfc822=other-mail.desktop;\n')
        self.repair()
        self.assertIn('message/rfc822=other-mail.desktop;', payload_read_text(self.mime))

    def test_missing_mime_file_created(self):
        self.assertTrue(self.repair())
        self.assertFalse(self.repair())
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.mime).st_mode), 0o600)

    def test_symlink_and_malformed_input_are_not_replaced(self):
        other = self.home / 'other'
        other.write_text('unchanged')
        self.mime.symlink_to(other)
        with self.assertRaises((RuntimeError, OSError)):
            self.repair()
        self.assertEqual(payload_read_text(other), 'unchanged')
        self.mime.unlink()
        self.mime.write_text('broken configuration without a section')
        with self.assertRaises(configparser.Error):
            self.repair()
        self.assertEqual(payload_read_text(self.mime), 'broken configuration without a section')

    def test_root_owned_rendered_seed_fallback_and_canonical_source_are_supported(self):
        source = self.home / 'seed.desktop'
        source.write_text('[Desktop Entry]\nName=Tuta Mail\n')
        with mock.patch.object(self.sync, 'SYSTEM_APPLICATION_DIR', str(self.home / 'missing')), \
             mock.patch.object(self.sync, 'TUTA_MANAGED_DESKTOP_SOURCE', str(source)):
            self.assertEqual(self.sync.find_desktop_file(('tutanota-desktop.desktop',)),
                             ('tutanota-desktop.desktop', str(source)))
            self.assertIsNone(self.sync.find_desktop_file(('unrelated.desktop',)))

    def test_seed_desktop_and_mime_defaults_use_the_same_supported_schemes(self):
        desktop = payload_read_text(TARGET / 'etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop')
        self.assertIn('MimeType=x-scheme-handler/mailto;x-scheme-handler/tuta;', desktop)
        self.assertIn('tutanota-desktop.desktop', payload_read_text(TARGET / 'etc/xdg/mimeapps.list'))
        self.assertNotIn('message/rfc822=tuta', payload_read_text(TARGET / 'etc/skel-desktop/.config/mimeapps.list'))


class ServiceAndNotificationTests(unittest.TestCase):
    def test_menu_wait_is_opt_in_and_does_not_attach_output_pipes(self):
        for marker in ('', '0', '1', 'yes'):
            with self.subTest(marker=marker), mock.patch.dict(os.environ, {'LABWC_MENU_ACTION_WAIT': marker}, clear=True), \
                 mock.patch.object(generic, 'assert_launch_allowed'):
                argv = generic.transient_argv('wayland', 'launch', ['/usr/bin/foot'], {})
                self.assertEqual('--wait' in argv, marker == '1')
                self.assertNotIn('--pipe', argv)
                self.assertIn('--property=ExitType=cgroup', argv)
                self.assertTrue(any(arg.startswith('--property=UnsetEnvironment=') and
                                    'LABWC_MENU_ACTION_WAIT' in arg for arg in argv))
                self.assertFalse(any(arg.startswith('--setenv=LABWC_MENU_ACTION_WAIT') for arg in argv))

    def test_native_tuta_waits_for_service_exit_but_still_uses_secret_service_and_journal(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {'LABWC_MENU_ACTION_WAIT':'1','WAYLAND_DISPLAY':'wayland-1'}, clear=True))
            stack.enter_context(mock.patch.object(session, '_consume_session_marker', return_value=False))
            stack.enter_context(mock.patch.object(session, 'system_owner', return_value=(0,0)))
            stack.enter_context(mock.patch.object(session, 'assert_launch_allowed'))
            stack.enter_context(mock.patch.object(session, 'require_root_owned_executable', return_value='/usr/bin/systemd-run'))
            stack.enter_context(mock.patch.object(session, 'current_user_runtime_socket'))
            stack.enter_context(mock.patch.object(session, 'managed_session_unit_environment', return_value={'HOME':'/home/test'}))
            execute = stack.enter_context(mock.patch.object(session.os, 'execve'))
            session.redirect_native_from_private_users('tutanota', 'launch', ['mailto:a@example.invalid'])
        argv = execute.call_args.args[1]
        self.assertIn('--wait', argv)
        self.assertNotIn('--pipe', argv)
        self.assertIn('--property=After=labwc-session.target labwc-kwallet-portal.service', argv)
        self.assertIn('--property=UnsetEnvironment=LABWC_MENU_ACTION_WAIT', argv)
        self.assertEqual(argv[-1], 'mailto:a@example.invalid')

    def test_activation_token_is_opaque_bounded_and_not_saved_as_restore_argument(self):
        with mock.patch.dict(os.environ, {'XDG_ACTIVATION_TOKEN':'opaque-token'}, clear=True):
            self.assertEqual(environment.desktop_activation_environment(), {'XDG_ACTIVATION_TOKEN':'opaque-token'})
        for token in ('bad\ntoken', 'a'*4097):
            with mock.patch.dict(os.environ, {'XDG_ACTIVATION_TOKEN':token}, clear=True), self.assertRaises(SystemExit):
                environment.desktop_activation_environment()
        self.assertIn('environment.update(desktop_activation_environment())',
                      payload_read_text(PACKAGE / 'labwc_managed_app/session.py'))
        self.assertIn('env: dict[str, str] = desktop_activation_environment()',
                      payload_read_text(PACKAGE / 'labwc_managed_app/environment.py'))

    def test_every_session_proxy_keeps_notifications_and_tuta_can_reach_tray(self):
        runtime = types.SimpleNamespace(validate_session_bus_address=lambda x:x)
        for extra in ((), profiles.TUTA_DBUS_NAMES):
            with mock.patch.dict(os.environ, {'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus'}), \
                 mock.patch.object(dbus_proxy,'start_filtered_dbus_proxy',return_value=(None,None,None)) as start:
                dbus_proxy.start_session_bus_proxy('/fixture',extra,runtime=runtime)
                policy = start.call_args.args[3]
                self.assertIn('--talk=org.freedesktop.Notifications', policy)
                self.assertNotIn('--talk=*',policy)
                self.assertNotIn('--own=org.freedesktop.Notifications',policy)
        self.assertIn('org.kde.StatusNotifierWatcher', profiles.TUTA_DBUS_NAMES)

    def test_mako_invokes_client_callback_instead_of_launching_a_new_generic_mail_window(self):
        config=payload_read_text(TARGET/'etc/skel-desktop/.config/mako/config')
        for setting in ('actions=1','on-button-left=invoke-default-action','on-touch=invoke-default-action',
                        '[desktop-entry=tutanota-desktop]\ngroup-by=none'):
            self.assertIn(setting,config)
        self.assertNotIn('exec labwc-tutanota',config)

    def test_remote_and_podman_terminal_helpers_wait_and_remote_returns_to_submenu(self):
        remote=load_script('labwc-remote-desktop')
        with mock.patch.object(remote.shutil,'which',return_value='/fixture/labwc-terminal'), \
             mock.patch.object(remote,'current_script_path',return_value=Path('/fixture/remote')), \
             mock.patch.object(remote.subprocess,'run') as run:
            remote.show_help()
        self.assertEqual(run.call_args.kwargs['env']['LABWC_MENU_ACTION_WAIT'],'1')
        with mock.patch.object(remote,'run_fuzzel',side_effect=['Show FreeRDP Help',None]), \
             mock.patch.object(remote,'show_help') as help_action:
            self.assertTrue(remote.main_menu())
            self.assertFalse(remote.main_menu())
            help_action.assert_called_once()
        source=payload_read_text(TARGET/'usr/local/bin/labwc-podman-menu')
        self.assertIn("subprocess.run([TERMINAL",source)
        self.assertIn("'LABWC_MENU_ACTION_WAIT': '1'",source)

    def test_remote_profile_folder_no_longer_detaches(self):
        remote = load_script('labwc-remote-desktop')
        with mock.patch.object(remote, 'profile_store_path', return_value=Path('/fixture/profiles/connections.json')), \
             mock.patch.object(remote, 'ensure_profile_directory'), \
             mock.patch.object(remote.shutil, 'which', return_value='/usr/bin/thunar'), \
             mock.patch.object(remote.subprocess, 'run') as run:
            remote.open_profile_directory()
        self.assertEqual(run.call_args.args[0], [
            '/usr/local/bin/labwc-wayland-app', 'auto', '--',
            '/usr/bin/thunar', '/fixture/profiles'])
        self.assertEqual(run.call_args.kwargs['env']['LABWC_MENU_ACTION_WAIT'], '1')

    def test_wireshark_waits_for_setsids_child(self):
        source = payload_read_text(TARGET/'usr/local/lib/perl5/site_perl/labwc-network-scan-action/LabwcNetworkScanAction/Client.pm')
        block = source.split('sub _run_wireshark_action {', 1)[1].split('sub _run_privileged_action', 1)[0]
        self.assertEqual(block.count("run($setsid, '-f', '--wait', $wireshark"), 2)
        self.assertIn("local $ENV{LABWC_MENU_ACTION_WAIT} = '1';", block)
        # Exercise util-linux process lifetime/exit propagation, without a GUI.
        result = subprocess.run(payload_installed_argv(['setsid', '-f', '--wait', '/bin/sh', '-c', 'exit 7']), check=False)
        self.assertEqual(result.returncode, 7)


class PolicyCoverageTests(unittest.TestCase):
    def test_terminal_grants_include_privileged_workers_without_owner_restriction(self):
        rule=payload_read_text(TARGET/'etc/apparmor.d/abstractions/wrapper-terminal')
        self.assertIn('\n/dev/pts/[0-9]* rw,',rule)
        self.assertNotIn('\nowner /dev/pts/',rule)
        text=payload_read_text(TARGET/'etc/apparmor.d/desktop-wrappers')
        for name in re.findall(r'^profile (labwc-[\w-]*action(?:-root|-worker)?) ',text,re.M):
            block=text.split('profile '+name+' ',1)[1].split('\nprofile ',1)[0]
            self.assertIn('#include <abstractions/wrapper-terminal>',block,name)
        self.assertIn('etc/apparmor.d/abstractions/wrapper-terminal',
                      payload_read_text(FORKY/'scripts/late/security.sh'))

    def test_readonly_process_inspection_is_bilateral(self):
        text=payload_read_text(TARGET/'etc/apparmor.d/system-wrappers') + payload_read_text(FORKY/'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl')
        self.assertIn('ptrace (read) peer=crowdsec-firstboot,',text)
        self.assertIn('ptrace (readby) peer=firstboot,',text)
        self.assertNotIn('ptrace (trace) peer=crowdsec-firstboot,',text)

    def test_ncdu_fix_is_directory_only_in_existing_file_manager_domain(self):
        text=payload_read_text(TARGET/'etc/apparmor.d/desktop-utilities')
        block=text.split('profile desktop-launcher ',1)[1].split('\nprofile ',1)[0]
        self.assertIn('\n  /**/ r,',block)
        self.assertNotIn('\n  /** r,',block)
        self.assertNotIn('\n  /** rw',block)

    def test_tuta_ipc_path_is_allowed_outside_and_inside_bubblewrap(self):
        text=payload_read_text(TARGET/'etc/apparmor.d/desktop-wrappers')
        block=text.split('profile labwc-app ',1)[1].split('\nprofile ',1)[0]
        self.assertEqual(block.count('owner /run/user/[0-9]*/labwc-tutanota-tmp/{,**} rwkl,'),2)


class MenuRoundTripTests(unittest.TestCase):
    def test_actual_menu_waits_for_action_and_returns_to_same_security_entries(self):
        with tempfile.TemporaryDirectory(prefix='menu-roundtrip-') as name:
            root=Path(name);bin_dir=root/'bin';bin_dir.mkdir()
            queue=root/'queue.json';events=root/'events.jsonl'
            choices=['Security & Accounts', 'Protection & Firewall', '\u2b9e Security Auditing',
                     'Check Firmware Security', '\u2190 Back', '\u2190 Back', 'Back', 'Exit']
            queue.write_text(json.dumps(choices))
            def executable(name,content):
                p=bin_dir/name;p.write_text(content);p.chmod(0o755)
            executable('id','#!/bin/sh\nprintf "1000\\n"\n')
            executable('ip','#!/bin/sh\nexit 0\n')
            executable('systemctl','#!/bin/sh\nexit 0\n')
            executable('labwc-fuzzel','''#!/usr/bin/python3
import json,os,pathlib,sys
root=pathlib.Path(os.environ['MENU_TEST_ROOT'])
q=root/'queue.json'; choices=json.loads(q.read_text()); choice=choices.pop(0);q.write_text(json.dumps(choices))
items=sys.stdin.read();prompt=sys.argv[sys.argv.index('--prompt')+1]
assert choice in items, (choice,items)
with (root/'events.jsonl').open('a') as f:f.write(json.dumps(['menu',prompt,items])+'\\n')
print(choice)
''')
            executable('labwc-security-action','''#!/usr/bin/python3
import json,os,pathlib,time
assert os.environ.get('LABWC_MENU_ACTION_WAIT')=='1'
p=pathlib.Path(os.environ['MENU_TEST_ROOT'])/'events.jsonl'
with p.open('a') as f:f.write(json.dumps(['action-start'])+'\\n')
time.sleep(.08)
with p.open('a') as f:f.write(json.dumps(['action-finished'])+'\\n')
raise SystemExit(7)
''')
            (bin_dir/'labwc-maintenance-menu').symlink_to(TARGET/'usr/local/bin/labwc-maintenance-menu')
            # The requested terminal UI now owns navigation; keep the real
            # maintenance subprocess and asynchronous action fixture so this
            # still proves wait/return behavior, not only static menu strings.
            menu = load_script('labwc-computer-management')
            menu.PICKER = str(bin_dir / 'labwc-fuzzel')
            outcomes = []
            def action(arguments):
                self.assertEqual(arguments, ('labwc-maintenance-menu', 'security'))
                result = subprocess.run(payload_installed_argv(['/bin/sh', str(TARGET/'usr/local/bin/labwc-maintenance-menu'), 'security']),
                                        capture_output=True, text=True, timeout=10)
                outcomes.append(result)
                return result.returncode
            with mock.patch.dict(os.environ, {'PATH':str(bin_dir)+':/usr/bin:/bin',
                    'MENU_TEST_ROOT':str(root), 'LABWC_DESKTOP_DEFAULTS_FILE':str(root/'absent')}), \
                    mock.patch.object(menu, 'run_action', side_effect=action):
                self.assertEqual(menu.run_menu(), 0)
            self.assertEqual(len(outcomes), 1)
            self.assertEqual(outcomes[0].returncode, 0, outcomes[0].stderr)
            rows=[json.loads(line) for line in payload_read_text(events).splitlines()]
            self.assertEqual([row[0] for row in rows], ['menu']*4 + ['action-start','action-finished'] + ['menu']*4)
            self.assertEqual(rows[3][1:], rows[6][1:])
            self.assertIn('returned status 7', outcomes[0].stderr)
            self.assertEqual(json.loads(payload_read_text(queue)),[])


    def test_terminal_menu_preserves_original_choice_data_and_rejects_free_text(self):
        # Graphical sizing retries no longer apply to the full-screen terminal
        # UI. The equivalent invariant is exact-choice data round-tripping.
        menu = load_script('labwc-computer-management')
        choices = ['Network & Remote', 'Files & Documents']
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(
                returncode=0, stdout='Files & Documents\n')) as run:
            self.assertEqual(menu.choose(choices, 'Computer Management'), choices[1])
            self.assertEqual(run.call_args.kwargs['input'], '\n'.join(choices) + '\n')
        with mock.patch.object(menu.subprocess, 'run', return_value=types.SimpleNamespace(
                returncode=0, stdout='$(touch /not-an-action)\n')):
            self.assertIsNone(menu.choose(choices, 'Computer Management'))


if __name__ == '__main__':
    unittest.main()
