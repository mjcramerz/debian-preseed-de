"""Offline regressions for the requested environment, launch and firstboot fixes.

No target services, installer stages, credentials or kernel profiles are run.
Atomic publication tests mock fsync (durability needs a real target filesystem).
"""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
sys.path.insert(0, str(TARGET / 'usr/local/lib/python3.14/dist-packages'))
from labwc_managed_app import environment, generic, integrity, runtime, session


def load_source(path: Path, name: str):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def shell_function(source: str, name: str) -> str:
    start = source.index(name + '() {')
    return source[start:source.index('\n}', start) + 2]


class DesktopHookTests(unittest.TestCase):
    def setUp(self):
        self.hook = load_source(TARGET / 'usr/local/libexec/labwc-wrap-desktop-files', 'tested_desktop_hook')
        self.prefix = '/usr/local/bin/labwc-electron-app nvidia'
        self.text = '[Desktop Entry]\nType=Application\nName=Example\nExec="/opt/My App/demo" --title "a b" %U\nDBusActivatable=true\n\n[Desktop Action New]\nName=New\nExec="/opt/My App/demo" --new %f\n'

    def test_original_command_quoting_fields_actions_and_dbus(self):
        result = self.hook.rewrite_desktop(self.text, self.prefix)
        self.assertIn('Exec=' + self.prefix + ' -- "/opt/My App/demo" --title "a b" %U\n', result)
        self.assertIn('Exec=' + self.prefix + ' -- "/opt/My App/demo" --new %f\n', result)
        self.assertIn('DBusActivatable=false\n', result)
        self.assertIn('Name=Example\n', result)

    def test_repeat_execution_does_not_stack_wrappers(self):
        once = self.hook.rewrite_desktop(self.text, self.prefix)
        self.assertEqual(self.hook.rewrite_desktop(once, self.prefix), once)

    def test_changing_default_gpu_replaces_only_our_prefix(self):
        once = self.hook.rewrite_desktop(self.text, self.prefix)
        updated = self.hook.rewrite_desktop(once, '/usr/local/bin/labwc-electron-app intel')
        self.assertEqual(updated, once.replace('labwc-electron-app nvidia', 'labwc-electron-app intel'))
        self.assertEqual(self.hook.rewrite_desktop(updated, '/usr/local/bin/labwc-electron-app intel'), updated)

    def test_nodisplay_hidden_and_nonapplication_unchanged(self):
        for entry in ('NoDisplay=true', 'Hidden=true'):
            text = self.text.replace('Type=Application', 'Type=Application\n' + entry)
            self.assertEqual(self.hook.rewrite_desktop(text, self.prefix), text)
        text = self.text.replace('Type=Application', 'Type=Link')
        self.assertEqual(self.hook.rewrite_desktop(text, self.prefix), text)

    def test_managed_entries_untouched(self):
        for command in ('/usr/local/bin/labwc-managed-app intel filen %U',
                        '"/usr/local/bin/labwc-managed-app" nvidia filen %U',
                        '"/usr/local/bin/labwc-managed-app nvidia" filen %U',
                        '/usr/local/bin/chatgpt auto %U'):
            text = '[Desktop Entry]\nType=Application\nExec=' + command + '\n'
            self.assertEqual(self.hook.rewrite_desktop(text, self.prefix), text)

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            self.hook.rewrite_desktop('[Desktop Entry]\nExec=one\nExec=two\n', self.prefix)

    def test_crlf_and_literal_dollar_are_preserved(self):
        text = '[Desktop Entry]\r\nExec=/usr/bin/demo "$HOME" %% %F\r\n'
        result = self.hook.rewrite_desktop(text, self.prefix)
        self.assertEqual(result, text.replace('Exec=', 'Exec=' + self.prefix + ' -- '))

    def test_package_query_is_read_only_and_checks_app_asar(self):
        with tempfile.TemporaryDirectory() as temp:
            asar = Path(temp) / 'resources/app.asar'
            asar.parent.mkdir(); asar.write_text('fixture')
            with mock.patch.object(self.hook, 'query', return_value=str(asar) + '\n') as query:
                self.assertTrue(self.hook.is_electron('example:amd64'))
                query.assert_called_once_with(['/usr/bin/dpkg', '-L', '--', 'example:amd64'])
            with mock.patch.object(self.hook, 'query', return_value='/opt/demo/app.asar\n'):
                self.assertFalse(self.hook.is_electron('example'))

    def test_multiarch_package_ownership(self):
        result = types.SimpleNamespace(returncode=0, stdout='example:amd64: /usr/share/applications/demo.desktop\n')
        with mock.patch.object(self.hook.subprocess, 'run', return_value=result):
            self.assertEqual(self.hook.package_for(Path('/usr/share/applications/demo.desktop')), 'example:amd64')

    def test_configuration_never_evaluates_shell(self):
        for value in ('"/usr/local/bin/labwc-electron-app nvidia; touch /oops"',
                      '"$(touch /oops)"', '"/usr/local/bin/labwc-electron-app amd"'):
            with tempfile.TemporaryDirectory() as temp:
                config = Path(temp) / 'defaults'
                config.write_text('LABWC_ELECTRON_APP_DEFAULT_EXEC=' + value + '\n')
                with mock.patch.object(self.hook, 'DEFAULTS', config), mock.patch.object(self.hook, 'trusted_file'):
                    with self.assertRaises(ValueError): self.hook.load_defaults()

    @unittest.skipUnless(os.geteuid() == 0, 'root-owned package metadata fixture')
    def test_root_group_writable_vendor_file_only(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'demo.desktop'; path.write_text(self.text); path.chmod(0o775)
            os.chown(path, 0, 0)
            self.hook.trusted_file(path, vendor=True)
            with self.assertRaises(ValueError): self.hook.trusted_file(path)
            path.chmod(0o777)
            with self.assertRaises(ValueError): self.hook.trusted_file(path, vendor=True)

    def test_symlink_publication_replaces_link_not_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'original.desktop'; source.write_text('original')
            link = root / 'alias.desktop'; link.symlink_to(source)
            before = link.lstat()
            with mock.patch.object(self.hook.os, 'fsync'):
                self.hook.write_atomic(link, 'wrapped', before)
            self.assertFalse(link.is_symlink())
            self.assertEqual(link.read_text(), 'wrapped')
            self.assertEqual(source.read_text(), 'original')

    def test_atomic_replace_rejects_inode_change(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'demo.desktop'; path.write_text('before'); before = path.stat()
            path.rename(Path(temp) / 'old'); path.write_text('concurrent update')
            with mock.patch.object(self.hook.os, 'fsync'), self.assertRaises(ValueError):
                self.hook.write_atomic(path, 'wrapped', before)
            self.assertEqual(path.read_text(), 'concurrent update')
            self.assertFalse(list(Path(temp).glob('.*.labwc-*')))

    def test_foreign_dpkg_root_does_not_touch_host(self):
        with mock.patch.object(self.hook.os, 'geteuid', return_value=0), \
             mock.patch.dict(os.environ, {'DPKG_ROOT': '/some/offline/root'}, clear=True), \
             mock.patch.object(self.hook, 'load_defaults') as load:
            self.assertEqual(self.hook.main(), 0)
            load.assert_not_called()


class GenericWrapperTests(unittest.TestCase):
    def test_electron_flags_keep_zygote_and_namespace_sandbox(self):
        command = generic.electron_command(['/opt/demo', '--ozone-platform=x11', '--use-gl=desktop', 'a b', '%', '$HOME'])
        self.assertIn('--ozone-platform=wayland', command)
        self.assertIn('--use-gl=angle', command)
        self.assertIn('--use-angle=gl', command)
        self.assertIn('--disable-setuid-sandbox', command)
        self.assertEqual(command[-3:], ['a b', '%', '$HOME'])
        self.assertNotIn('--no-sandbox', command)
        self.assertNotIn('--no-zygote', command)
        self.assertNotIn('--ozone-platform=x11', command)

    def test_sandbox_disabling_arguments_rejected(self):
        for switch in sorted(generic.ELECTRON_UNSAFE_SWITCHES):
            with self.subTest(switch=switch), self.assertRaises(SystemExit):
                generic.electron_command(['/opt/demo', switch])

    def test_vendor_features_merged_without_vulkan(self):
        command = generic.electron_command(['/opt/demo', '--enable-features=VendorFeature,Vulkan', '--disable-features=UseOzonePlatform,OtherFeature'])
        self.assertTrue(any('VendorFeature' in item for item in command))
        self.assertTrue(any('OtherFeature' in item for item in command))
        enable = next(item for item in command if item.startswith('--enable-features='))
        self.assertNotIn('Vulkan', enable)
        self.assertIn('UseOzonePlatform', enable)

    def test_shell_electron_entry_does_not_receive_fake_flags(self):
        with self.assertRaises(SystemExit): generic.electron_command(['/bin/sh', '-c', 'demo'])

    def test_transient_cgroup_lifetime_and_argument_integrity(self):
        env = {'HOME': '/home/alice', 'LIBVA_DRIVER_NAME': 'nvidia', 'TOKEN': 'secret-value'}
        args = ['/opt/demo', 'one two', '$HOME', '%U', ';false']
        one = generic.transient_argv('electron', 'nvidia', args, env)
        two = generic.transient_argv('electron', 'nvidia', args, env)
        self.assertNotEqual(next(x for x in one if x.startswith('--unit=')), next(x for x in two if x.startswith('--unit=')))
        for value in ('--collect', '--service-type=exec', '--expand-environment=no', '--property=ExitType=cgroup', '--property=KillMode=control-group', '--property=PartOf=labwc-session.target'):
            self.assertIn(value, one)
        self.assertEqual(one[one.index('--') + 1:], args)
        self.assertIn('--setenv=TOKEN', one); self.assertNotIn('secret-value', ' '.join(one))
        unset = next(x for x in one if x.startswith('--property=UnsetEnvironment='))
        self.assertNotIn('LIBVA_DRIVER_NAME', unset)
        self.assertIn('DISPLAY', unset)
        self.assertIn('--property=NoNewPrivileges=no', one)
        self.assertFalse(any('RestrictSUIDSGID=' in x for x in one))

    def test_env_assignments_are_not_shell_evaluated(self):
        env = {}
        args = generic.unwrap_env(['/usr/bin/env', 'EXAMPLE=$(touch /oops)', '/usr/bin/demo', '%U'], env)
        self.assertEqual(args, ['/usr/bin/demo', '%U']); self.assertEqual(env['EXAMPLE'], '$(touch /oops)')
        for name in ('HOME', 'DISPLAY', 'LD_PRELOAD', 'DBUS_SESSION_BUS_ADDRESS'):
            with self.assertRaises(SystemExit): generic.unwrap_env(['env', name + '=bad', 'demo'], {})

    def test_native_wrapper_uses_toolkit_environment_not_electron_arguments(self):
        for mode, expected in (('intel', 'iHD'), ('nvidia', 'nvidia')):
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(generic.os, 'geteuid', return_value=1000))
                stack.enter_context(mock.patch.object(generic, 'session_environment', return_value={'PATH': runtime.MANAGED_PATH}))
                stack.enter_context(mock.patch.object(generic, 'load_managed_defaults', return_value={}))
                stack.enter_context(mock.patch.object(generic, 'acceleration_availability_from_defaults', return_value={'intel': True, 'nvidia': True}))
                stack.enter_context(mock.patch.object(generic.shutil, 'which', return_value='/usr/bin/demo'))
                stack.enter_context(mock.patch.object(generic, 'require_root_owned_executable', return_value='/usr/bin/systemd-run'))
                execute = stack.enter_context(mock.patch.object(generic.os, 'execve'))
                generic.main('wayland', [mode, '--', 'demo', 'a b'])
                _, argv, env = execute.call_args.args
                self.assertEqual(argv[argv.index('--') + 1:], ['/usr/bin/demo', 'a b'])
                self.assertEqual(env['LIBVA_DRIVER_NAME'], expected)
                self.assertEqual(env['QT_QPA_PLATFORM'], 'wayland')

    def test_new_scopes_participate_in_integrity_inventory(self):
        for scope in (integrity.PackageScope.ELECTRON, integrity.PackageScope.WAYLAND):
            self.assertIn('generic.py', integrity.MODULES_BY_SCOPE[scope])
        self.assertIn('generic.py', integrity.ALL_MODULES)


class ChatGPTEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name); directory = self.home / '.profile.d'; directory.mkdir(mode=0o700)
        self.profile = directory / '71-devops-de.sh'
        self.profile.write_text('devops_de_apply_environment() {\nexport DEVOPS_DE_ACTIVE=1 DEVOPS_DE_ENVIRONMENT_READY=1\nexport CODEX_HOME=/data/codex/usr/home\nexport PATH=/data/codex/lib:/usr/bin:/bin\nexport PACKER_CONFIG="$HOME/.config/packer/config"\nexport EXTRA_PROFILE_EXPORT="space value"\n}\n')
        self.profile.chmod(0o600)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(environment, 'current_user_home', return_value=str(self.home)))
        self.stack.enter_context(mock.patch.object(environment, 'current_user_name', return_value='alice'))
        self.stack.enter_context(mock.patch.object(environment, 'current_user_runtime_dir', return_value='/run/user/1000'))
        self.stack.enter_context(mock.patch.object(environment, 'validate_chatgpt_work_areas'))

    def test_inactive_desktop_launch_collects_all_exports(self):
        with mock.patch.dict(os.environ, {}, clear=True): result = environment.validated_chatgpt_devops_environment()
        self.assertEqual(result['CODEX_HOME'], '/data/codex/usr/home')
        self.assertEqual(result['EXTRA_PROFILE_EXPORT'], 'space value')
        self.assertEqual(result['PACKER_CONFIG'], str(self.home) + '/.config/packer/config')
        self.assertNotIn('HOME', result)
        self.assertEqual(result['DEVOPS_DE_ENVIRONMENT_READY'], '1')

    def test_partial_activation_marker_is_repaired(self):
        with mock.patch.dict(os.environ, {'DEVOPS_DE_ACTIVE': '1'}, clear=True):
            result = environment.chatgpt_devops_source_environment()
        self.assertEqual(result['DEVOPS_DE_ENVIRONMENT_READY'], '1')
        self.assertEqual(result['CODEX_HOME'], '/data/codex/usr/home')

    def test_writable_profile_is_rejected(self):
        self.profile.chmod(0o666)
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit):
            environment.chatgpt_devops_source_environment()

    def test_backend_identity_and_canonical_wrapper(self):
        text = (TARGET / 'etc/skel-desktop/.config/systemd/user/codex-app-server.service').read_text()
        for expected in ('Environment=HOME=%h USER=%u LOGNAME=%u XDG_RUNTIME_DIR=%t',
                         'Environment=CODEX_HOME=/data/codex/usr/home',
                         'ExecStart=/data/codex/lib/codex app-server --listen unix:///data/codex/sockets/app-server-backend.sock'):
            self.assertIn(expected, text)
        wrapper = (TARGET / 'data/codex/lib/codex').read_text()
        self.assertIn('devops_de_apply_environment', wrapper)

    def test_chatgpt_handoff_preserves_exports_not_untrusted_identity(self):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {'DEVOPS_DE_ACTIVE': '1', 'DEVOPS_DE_ENVIRONMENT_READY': '1', 'HOME': '/bad', 'WAYLAND_DISPLAY': 'wayland-1', 'CODEX_HOME': '/data/codex/usr/home', 'CUSTOM_TOKEN': 'private-token'}, clear=True))
            stack.enter_context(mock.patch.object(session, 'system_owner', return_value=(0, 0)))
            stack.enter_context(mock.patch.object(session, 'require_root_owned_executable', return_value='/usr/bin/systemd-run'))
            stack.enter_context(mock.patch.object(session, 'managed_session_unit_environment', return_value={'HOME': '/home/alice'}))
            stack.enter_context(mock.patch.object(session, 'current_user_runtime_socket'))
            execute = stack.enter_context(mock.patch.object(session.os, 'execve'))
            session.redirect_native_from_private_users('chatgpt', 'intel', [])
            _, argv, env = execute.call_args.args
            self.assertEqual(env['HOME'], '/home/alice')
            self.assertEqual(env['CUSTOM_TOKEN'], 'private-token')
            self.assertIn('--setenv=CUSTOM_TOKEN', argv); self.assertNotIn('private-token', ' '.join(argv))
            self.assertIn('--property=Requires=labwc-session.target codex-app-server.socket codex-app-server-proxy.service', argv)
            self.assertIn('--property=PartOf=labwc-session.target', argv)

    def test_active_handoff_rejects_loader_injection_before_exec(self):
        for name in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'BASH_ENV'):
            with ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ, {
                    'DEVOPS_DE_ACTIVE': '1', 'DEVOPS_DE_ENVIRONMENT_READY': '1',
                    'WAYLAND_DISPLAY': 'wayland-1', name: '/bad'}, clear=True))
                stack.enter_context(mock.patch.object(session, 'system_owner', return_value=(0, 0)))
                stack.enter_context(mock.patch.object(session, 'require_root_owned_executable', return_value='/usr/bin/systemd-run'))
                stack.enter_context(mock.patch.object(session, 'managed_session_unit_environment', return_value={'HOME': '/home/alice'}))
                stack.enter_context(mock.patch.object(session, 'current_user_runtime_socket'))
                execute = stack.enter_context(mock.patch.object(session.os, 'execve'))
                with self.assertRaises(SystemExit):
                    session.redirect_native_from_private_users('chatgpt', 'intel', [])
                execute.assert_not_called()


class InstallerRegressionTests(unittest.TestCase):
    def test_every_host_profile_defines_both_launchers(self):
        profiles = list((FORKY / 'hosts/profiles').glob('*.env')); self.assertTrue(profiles)
        for path in profiles:
            text = path.read_text()
            if 'LABWC_MANAGED_APP_DEFAULT_EXEC=' not in text: continue
            for kind in ('ELECTRON', 'WAYLAND'):
                self.assertIn(f'LABWC_{kind}_APP_DEFAULT_EXEC="/usr/local/bin/labwc-{kind.lower()}-app nvidia"', text)

    def test_generic_hardware_fallback_matches_selected_hardware(self):
        source = (FORKY / 'scripts/desktop/detect.sh').read_text()
        function = source[source.index('desktop_resolve_generic_app_default_exec() ('):source.index('\ndesktop_resolve_generic_app_defaults()')]
        for intel, nvidia, expected in (('true', 'true', 'nvidia'), ('true', 'false', 'intel'), ('false', 'false', 'launch')):
            script = f'LABWC_INTEL_ACCELERATION_AVAILABLE={intel}\nLABWC_NVIDIA_ACCELERATION_AVAILABLE={nvidia}\n' + function + '\ndesktop_resolve_generic_app_default_exec labwc-electron-app "/usr/local/bin/labwc-electron-app nvidia"\n'
            result = subprocess.run(['/bin/sh', '-eu', '-c', script], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '/usr/local/bin/labwc-electron-app ' + expected)

    def test_tuta_is_home_scoped_and_installed_with_ownership(self):
        self.assertFalse((TARGET / 'usr/share/applications/tuta-mail.desktop').exists())
        self.assertTrue((TARGET / 'etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop').is_file())
        components = (FORKY / 'scripts/desktop/components.sh').read_text()
        self.assertIn('"$account_home/.local/share/applications/tutanota-desktop.desktop"', components)
        self.assertIn('chown "$uid:$gid" "$account_home/.local/share/applications/tutanota-desktop.desktop"', components)

    def test_firstboot_renderer_nested_shell_is_not_truncated(self):
        function = shell_function((FORKY / 'scripts/firstboot/04-validation.sh').read_text(), 'desktop_renderer_policy_matches')
        with tempfile.TemporaryDirectory() as temp:
            recorder, capture = Path(temp) / 'record.py', Path(temp) / 'argv.json'
            recorder.write_text('import json,os,sys\nwith open(os.environ["CAPTURE"],"w") as f: json.dump(sys.argv[1:],f)\n')
            def record(body):
                body = body.replace('/bin/sh -eu -c', shlex.quote(sys.executable) + ' ' + shlex.quote(str(recorder)), 1)
                run = subprocess.run(['/bin/sh', '-c', body + '\ndesktop_renderer_policy_matches'], env={**os.environ, 'CAPTURE': str(capture)}, capture_output=True, timeout=5)
                self.assertEqual(run.returncode, 0, run.stderr)
                return json.loads(capture.read_text())
            fixed = record(function)
            self.assertEqual(len(fixed), 2)  # complete script, then argv[0]=sh
            check = subprocess.run(['/bin/sh', '-n', '-c', fixed[0]], capture_output=True, timeout=5)
            self.assertEqual(check.returncode, 0, check.stderr)
            broken = record(function.replace("'\"'\"'", "'"))
            check = subprocess.run(['/bin/sh', '-n', '-c', broken[0]], capture_output=True, timeout=5)
            self.assertNotEqual(check.returncode, 0)

    def test_tool_version_probes_have_disposable_homes(self):
        tools = load_source(FORKY / 'scripts/late/devops-tools.py', 'tested_devops_version_probe')
        captured = {}
        def verify(policy, env):
            captured.update(env); self.assertTrue(Path(env['HOME']).is_dir())
            self.assertEqual(env['CHECKPOINT_DISABLE'], '1')
            for name in ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME'):
                self.assertTrue(env[name].startswith(env['HOME'] + '/'))
        with mock.patch.object(tools, '_verify_installation', side_effect=verify): tools.verify_installation(object())
        self.assertNotEqual(captured['HOME'], '/')
        self.assertFalse(Path(captured['HOME']).exists())
        devops = (FORKY / 'scripts/late/devops.sh').read_text()
        self.assertIn('version_output=$(codex_verify_version "$candidate_binary_path"', devops)
        self.assertIn('version_output=$(codex_verify_version "$binary_path"', devops)
        self.assertIn('CODEX_HOME="$verify_home/.codex"', devops)

    def test_apparmor_covers_root_cause_not_null_profiles_or_root_codex(self):
        policy = (TARGET / 'etc/apparmor.d/managed-desktop-utilities').read_text()
        self.assertIn('/usr/bin/bwrap rCx -> editor-glycin-bwrap,', policy)
        self.assertIn('owner @{PROC}/[0-9]*/cgroup r,', policy)
        for peer in ('bitwarden', 'filen', 'vivaldi-bin', 'vivaldi-stable'):
            self.assertIn('ptrace (read) peer=' + peer + ',', policy)
        self.assertNotIn('null-/usr/bin/bwrap', policy)
        self.assertNotIn('/.codex', policy)


if __name__ == '__main__':
    unittest.main()
