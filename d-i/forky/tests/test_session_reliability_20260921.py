"""Non-destructive regressions for the September 21 log-driven repairs.

All power calls and desktop applications are mocked. FD tests run only in an
isolated Python child; root-file tests use a temporary directory, not /etc.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import python_library
from payload_fixture import installed_script
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import contextlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'


def load(leaf):
    loader = importlib.machinery.SourceFileLoader(leaf, str(installed_script(TARGET/'usr/local/libexec'/leaf)))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FootResults(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(python_library(TARGET/'usr/local/lib/python3.14/dist-packages')))
        self.addCleanup(sys.path.pop, 0)
        from labwc_managed_app import generic
        self.m = generic

    def command(self, arguments, kind='wayland', environment=None):
        with mock.patch.object(self.m, 'assert_launch_allowed'), \
             mock.patch.object(self.m, 'restart_token', return_value='fixture'), \
             mock.patch.object(self.m, 'menu_action_wait_arguments', return_value=[]):
            return self.m.transient_argv(kind, 'auto', arguments,
                                         {} if environment is None else environment)

    def test_normal_default_shell_hangup_is_success_without_wrapper(self):
        command = self.command(['/usr/bin/foot'])
        self.assertEqual(command[command.index('--')+1:], ['/usr/bin/foot'])
        self.assertIn('--property=SuccessExitStatus=1', command)
        self.assertNotIn('labwc-foot-supervisor', ' '.join(command))

    def test_explicit_commands_and_options_keep_their_exit_status(self):
        for tail in (['-e', '/bin/false'], ['/bin/false'], ['--login-shell'], ['--version']):
            with self.subTest(tail=tail):
                command = self.command(['/usr/bin/foot', *tail])
                self.assertEqual(command[command.index('--')+1:], ['/usr/bin/foot', *tail])
                self.assertFalse(any(item.startswith('--property=SuccessExitStatus=') for item in command))

    def test_internal_error_is_never_hidden(self):
        for arguments in (['/usr/bin/foot'], ['/usr/bin/foot', '/bin/false']):
            command = self.command(arguments)
            statuses = [item.split('=', 2)[2].split() for item in command
                        if item.startswith('--property=SuccessExitStatus=')]
            self.assertFalse(any('230' in item for item in statuses))

    def test_native_stop_keeps_cgroup_cleanup_and_session_lifetime(self):
        command = self.command(['/usr/bin/foot'])
        for item in ('KillMode=mixed', 'ExitType=cgroup', 'TimeoutStopSec=20s',
                     'SendSIGKILL=yes', 'Restart=no', 'Requisite=labwc-session.target',
                     'After=labwc-session.target', 'PartOf=labwc-session.target'):
            self.assertIn('--property='+item, command)
        self.assertIn('--collect', command)
        self.assertIn('--service-type=exec', command)

    def test_other_executables_do_not_inherit_terminal_exception(self):
        for kind, executable in (('wayland', '/tmp/foot'), ('wayland', '/usr/bin/kitty'),
                                 ('wayland', '/usr/bin/featherpad'), ('electron', '/usr/bin/foot')):
            with self.subTest(kind=kind, executable=executable):
                command = self.command([executable], kind)
                self.assertIn('--property=KillMode=control-group', command)
                self.assertFalse(any(item.startswith('--property=SuccessExitStatus=') for item in command))

    def test_session_restore_retains_original_application_command(self):
        environment = {}
        with mock.patch.object(self.m, 'assert_launch_allowed'), \
             mock.patch.object(self.m, 'restart_token', return_value='fixture') as token, \
             mock.patch.object(self.m, 'menu_action_wait_arguments', return_value=[]):
            self.m.transient_argv('wayland', 'auto', ['/usr/bin/foot'], environment)
        token.assert_called_once_with([self.m.WRAPPERS['wayland'], 'auto', '--', '/usr/bin/foot'])
        self.assertEqual(environment['LABWC_SESSION_APP'], '1')
        self.assertEqual(environment['LABWC_SESSION_RESTORE'], 'fixture')

    def test_removed_helpers_have_no_installer_or_runtime_dependencies(self):
        for name in ('labwc-foot-supervisor', 'labwc-stage-waybar-icons'):
            self.assertFalse(payload_source_exists(TARGET/'usr/local/libexec'/name))
            for relative in ('scripts/desktop/components.sh', 'scripts/desktop/labwc.sh',
                             'scripts/desktop/verify.sh'):
                self.assertNotIn(name, render_theme_defaults(payload_read_text(TARGET.parents[1]/relative)))
        self.assertNotIn('desktop_prepare_native_drawer_icons',
                         render_theme_defaults(payload_read_text(TARGET.parents[1]/'scripts/desktop/verify.sh')))


class SaveVeto(unittest.TestCase):
    def setUp(self):
        self.m = load('labwc-session-state')

    def response(self, code, text):
        return mock.patch.object(self.m.subprocess, 'run', return_value=SimpleNamespace(returncode=code, stdout=text))

    def test_only_exact_second_index_allows_close(self):
        with self.response(0, '1\n') as run:
            self.m.confirm_close()
        kw = run.call_args.kwargs
        self.assertTrue(kw['input'].startswith('Cancel -'))
        self.assertEqual(len(kw['input'].splitlines()), 2)
        self.assertEqual(kw['env']['LABWC_MENU_BACKEND'], 'fuzzel')
        self.assertEqual(kw['env']['LABWC_FUZZEL_MANAGED_ICONS'], '0')
        self.assertIn('--no-sort', run.call_args.args[0])
        self.assertTrue(kw['close_fds'])

    def test_cancel_default_escape_and_timeout_are_vetoes(self):
        for code,text in ((0,'0\n'), (1,'')):
            with self.response(code,text), self.assertRaises(self.m.Cancelled):
                self.m.confirm_close()
        with mock.patch.object(self.m.subprocess,'run',side_effect=subprocess.TimeoutExpired('fixture',120)), \
             self.assertRaises(self.m.Cancelled):
            self.m.confirm_close()

    def test_malformed_and_backend_errors_fail_closed(self):
        for code,text in ((2,''), (0,''), (0,'01'), (0,'1\n0'), (0,'2'), (-9,'1')):
            with self.subTest(code=code,text=text), self.response(code,text), self.assertRaises(self.m.Error):
                self.m.confirm_close()

    def test_all_named_editors_and_browsers_are_protected(self):
        for app in self.m.PROTECTED_APPS:
            for kind in ('wayland','electron','native'):
                name = 'labwc-' + kind + '-' + app + '-' + 'a'*32 + '.service'
                self.assertEqual(self.m.protected_services({name:{'LABWC_SESSION_APP':'1'}}), {name})
                self.assertEqual(self.m.protected_services({name:{}}), set())

    def test_unmanaged_and_non_editor_jobs_are_not_relabelled(self):
        apps={'labwc-wayland-foot-'+'a'*32+'.service':{'LABWC_SESSION_APP':'1'},
              'labwc-wayland-featherpad-invalid.service':{'LABWC_SESSION_APP':'1'}}
        self.assertEqual(self.m.protected_services(apps), set())

    def test_protected_background_saves_require_terminal_state(self):
        for value in ({}, {'LoadState':'loaded','ActiveState':'active'},
                      {'LoadState':'loaded','ActiveState':'deactivating'}, {'LoadState':'error'}):
            with mock.patch.object(self.m,'properties',return_value=value):
                self.assertTrue(self.m.protected_still_running({'example.service'}))
        for value in ({'LoadState':'not-found'}, {'LoadState':'loaded','ActiveState':'inactive'},
                      {'LoadState':'loaded','ActiveState':'failed'}):
            with mock.patch.object(self.m,'properties',return_value=value):
                self.assertFalse(self.m.protected_still_running({'example.service'}))

    def test_user_veto_removes_closing_marker_without_closing_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); state=root/'state'; runtime=root/'runtime'; state.mkdir(); runtime.mkdir()
            with mock.patch.object(self.m,'ctl'), mock.patch.object(self.m,'services',return_value={}), \
                 mock.patch.object(self.m,'windows',return_value='firefox: draft'), \
                 mock.patch.object(self.m,'confirm_close',side_effect=self.m.Cancelled('fixture')), \
                 mock.patch.object(self.m,'run') as run, self.assertRaises(self.m.Cancelled):
                self.m.prepare(state,runtime)
            run.assert_not_called()
            self.assertFalse(payload_source_exists(runtime/'labwc-session-closing'))
            self.assertFalse(payload_source_exists(state/'resume.json'))


class WorkerVeto(unittest.TestCase):
    def setUp(self):
        self.m=load('labwc-admin-action-worker'); self.worker=self.m.Worker(1000,'desktop','reboot')

    def test_verified_zero_preparation_result_allows_next_phase(self):
        with mock.patch.object(self.worker,'userctl',side_effect=['','','ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus=0\n','']):
            self.worker.helper('prepare')

    def test_verified_veto_is_not_permission_for_shutdown(self):
        with mock.patch.object(self.worker,'userctl',side_effect=['','','ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus=77\n','']), \
             self.assertRaises(self.m.Cancelled):
            self.worker.helper('prepare')
        self.assertFalse(self.worker.committed)

    def test_missing_malformed_and_failed_preparation_never_authorize(self):
        for response in ('', 'ActiveState=inactive\nResult=success',
                         'ActiveState=inactive\nResult=exit-code\nExecMainStatus=77',
                         'ActiveState=active\nResult=success\nExecMainStatus=0',
                         'ActiveState=inactive\nResult=success\nExecMainStatus=42'):
            with mock.patch.object(self.worker,'userctl',side_effect=['','',response,'']), self.assertRaises(self.m.Error):
                self.worker.helper('prepare')

    def test_retained_result_is_read_before_release_and_duplicate_fields_fail(self):
        response='ActiveState=active\nSubState=exited\nResult=success\nExecMainStatus=0\n'
        with mock.patch.object(self.worker,'userctl',side_effect=['','',response,'']) as ctl:
            self.worker.helper('prepare')
        self.assertEqual([c.args[0] for c in ctl.call_args_list],['stop','start','show','stop'])
        for invalid in (response+'ExecMainStatus=77\n', response.replace('active','inactive',1)):
            with mock.patch.object(self.worker,'userctl',side_effect=['','',invalid]), self.assertRaises(self.m.Error):
                self.worker.helper('prepare')

    def test_direct_transport_drops_groups_and_uses_canonical_bus(self):
        account=SimpleNamespace(pw_uid=1000,pw_gid=1000,pw_name='desktop',pw_dir='/home/desktop')
        child=mock.Mock(returncode=0); child.communicate.return_value=('ok','')
        with mock.patch.object(self.m.subprocess,'Popen',return_value=child) as start:
            self.assertEqual(self.m.run(['/usr/bin/systemctl','--user','show'],account=account),'ok')
        kw=start.call_args.kwargs
        self.assertEqual((kw['user'],kw['group'],kw['extra_groups']),(1000,1000,()))
        self.assertEqual(kw['env']['DBUS_SESSION_BUS_ADDRESS'],'unix:path=/run/user/1000/bus')
        self.assertTrue(kw['close_fds']); self.assertTrue(kw['start_new_session'])
        self.assertNotIn('LD_PRELOAD',kw['env'])
        self.assertNotIn('PYTHONPATH',kw['env'])

    def test_direct_transport_rejects_root_identity(self):
        account=SimpleNamespace(pw_uid=0,pw_gid=0,pw_name='root',pw_dir='/root')
        with self.assertRaises(self.m.Error): self.m.run(['/bin/false'],account=account)


class DescriptorBoundary(unittest.TestCase):
    def setUp(self): self.m=load('labwc-waybar-exec')

    def test_fixed_allowlist_accepts_only_status_paths(self):
        for pair in self.m.COMMANDS:
            self.assertEqual(self.m.command(list(pair)),pair)
        self.assertEqual(self.m.command(['labwc-capture','status']),('/usr/local/bin/labwc-capture','status'))
        for args in ([], ['/bin/sh','status'], ['labwc-capture','start'],
                     ['../labwc-capture','status'], ['labwc-capture','status','extra']):
            with self.assertRaises(ValueError): self.m.command(args)

    def test_actual_inherited_fd_above_lowered_limit_is_closed(self):
        # This child has no contact with a desktop or PID 1.
        program = """
import importlib.machinery, importlib.util, os, resource
loader=importlib.machinery.SourceFileLoader('boundary',%r)
spec=importlib.util.spec_from_loader(loader.name,loader)
m=importlib.util.module_from_spec(spec);loader.exec_module(m)
fd=os.open('/dev/null',os.O_RDONLY);os.dup2(fd,200);os.close(fd)
soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE,(64,hard))
m.close_inherited_fds()
try: os.fstat(200)
except OSError: pass
else: raise AssertionError('inherited descriptor was not closed')
os.write(1,b'closed; stdout retained')
""" % str(TARGET/'usr/local/libexec/labwc-waybar-exec')
        result=subprocess.run(payload_installed_argv([sys.executable,'-I','-B','-c',program]),capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'closed; stdout retained')


class AtomicKMS(unittest.TestCase):
    def test_no_legacy_backend_policy_or_host_allowlist_remains(self):
        paths = (TARGET/'etc/labwc/desktop.conf.tmpl',
                 TARGET/'usr/local/bin/labwc-session.tmpl',
                 TARGET.parents[1]/'scripts/desktop/components.sh', TARGET.parents[1]/'scripts/desktop/detect.sh')
        for path in paths:
            text = render_theme_defaults(payload_read_text(path))
            self.assertNotIn('LABWC_WLR_DRM_', text, str(path))
            self.assertNotIn('select_drm_no_atomic', text, str(path))
        self.assertNotIn('LPL-264', render_theme_defaults(payload_read_text(TARGET/'usr/local/bin/labwc-session.tmpl')))

    def test_old_override_is_unset_and_never_imported(self):
        text = render_theme_defaults(payload_read_text(TARGET/'usr/local/bin/labwc-session.tmpl'))
        cleanup = re.search(r'cleanup_environment_names="([^"]*)"', text).group(1).split()
        imported = re.search(r"compositor_environment_names='([^']*)'", text).group(1).split()
        self.assertIn('WLR_DRM_NO_ATOMIC', cleanup)
        self.assertNotIn('WLR_DRM_NO_ATOMIC', imported)
        self.assertIn('unset WLR_DRM_NO_ATOMIC', text)
        self.assertNotRegex(text, r'(?m)^\s*(?:export )?WLR_DRM_NO_ATOMIC=')
        start = text.index('--user --wait start labwc-compositor.service')
        self.assertLess(text.rindex('unset-environment $cleanup_environment_names', 0, start), start)


@unittest.skipUnless(os.getuid()==0,'installer root-file tests require disposable root-owned fixtures')
class ScannerOnlyPolicy(unittest.TestCase):
    def setUp(self):
        self.m=load('labwc-configure-session-repairs')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.path=self.root/'freshclam.conf'
        self.path.write_text('DatabaseOwner clamav\nNotifyClamd /etc/clamav/clamd.conf\nHTTPProxyPassword secret\n')
        self.path.chmod(0o600)
    def test_exact_missing_daemon_only_and_idempotent_preserving_secrets_mode(self):
        self.assertTrue(self.m.reconcile_clamd_notification(self.root))
        text=render_theme_defaults(payload_read_text(self.path));self.assertNotIn('\nNotifyClamd ',text)
        self.assertIn('HTTPProxyPassword secret',text)
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.path).st_mode),0o600)
        self.assertFalse(self.m.reconcile_clamd_notification(self.root))
        self.assertEqual(render_theme_defaults(payload_read_text(self.path)),text)
    def test_present_daemon_is_untouched(self):
        (self.root/'clamd.conf').write_text('LocalSocket /run/clamav/clamd.ctl\n')
        before=render_theme_bytes(payload_read_bytes(self.path));self.assertFalse(self.m.reconcile_clamd_notification(self.root))
        self.assertEqual(render_theme_bytes(payload_read_bytes(self.path)),before)
    def test_custom_daemon_path_is_untouched(self):
        self.path.write_text('NotifyClamd /etc/company/clamd.conf\n')
        self.assertFalse(self.m.reconcile_clamd_notification(self.root))
    def test_symlinked_freshclam_is_rejected(self):
        real=self.root/'real'; self.path.rename(real);self.path.symlink_to(real)
        with self.assertRaises(OSError): self.m.reconcile_clamd_notification(self.root)
    def test_symlinked_daemon_is_rejected(self):
        (self.root/'clamd.conf').symlink_to(self.path)
        with self.assertRaises(RuntimeError): self.m.reconcile_clamd_notification(self.root)
    def test_writable_root_directory_is_rejected(self):
        self.root.chmod(0o777)
        with self.assertRaises(RuntimeError): self.m.reconcile_clamd_notification(self.root)


class Wiring(unittest.TestCase):
    def test_wlsunset_controller_runs_in_host_user_namespace(self):
        unit=render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/systemd/user/labwc-wlsunset-start.service'))
        self.assertIn('PrivateUsers=no',unit);self.assertIn('PrivatePIDs=no',unit)
        self.assertIn('Requisite=labwc-session.target',unit)
        self.assertIn('/usr/local/bin/labwc-wlsunset start',unit)
        autostart=render_theme_defaults(payload_read_text(TARGET/'usr/local/bin/labwc-autostart'))
        self.assertIn('session_systemctl start labwc-wlsunset-start.service',autostart)
    def test_cancel_status_is_checked_not_blanket_success(self):
        unit=render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/systemd/user/labwc-session-state@.service'))
        self.assertIn('SuccessExitStatus=77',unit)
        retained=render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/systemd/user/labwc-session-state@prepare.service.d/retain-result.conf'))
        self.assertIn('RemainAfterExit=yes',retained)
        worker=render_theme_defaults(payload_read_text(TARGET/'usr/local/libexec/labwc-admin-action-worker'))
        self.assertIn('props.get("ExecMainStatus") == "77"',worker)
        self.assertIn('except Cancelled as exc:',worker)
    def test_status_transition_has_no_rfkill_permission_widening(self):
        text=render_theme_defaults(payload_read_text(TARGET/'etc/apparmor.d/waybar-menus'))
        profile=text.split('profile labwc-notifications ',1)[1].split('\nprofile ',1)[0]
        self.assertNotIn('/dev/rfkill',profile)
        waybar=render_theme_defaults(payload_read_text(TARGET/'etc/apparmor.d/labwc-session'))
        self.assertIn('local/libexec/labwc-waybar-exec',waybar)
        self.assertNotIn('/usr/local/share/labwc/waybar-icons/',waybar)



class NotificationSessionPolicy(unittest.TestCase):
    def test_clean_environment_keeps_existing_accessibility_policy(self):
        m = load('labwc-notifications')
        info = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1000)
        account = SimpleNamespace(pw_dir='/home/test', pw_name='test')
        with mock.patch.object(m.os, 'getuid', return_value=1000), \
             mock.patch.object(m.os, 'geteuid', return_value=1000), \
             mock.patch.object(m.Path, 'lstat', return_value=info), \
             mock.patch.object(m.pwd, 'getpwuid', return_value=account), \
             mock.patch.dict(m.os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}, clear=True):
            env = m.environment()
        session = render_theme_defaults(payload_read_text(TARGET/'etc/skel-desktop/.config/labwc/environment.d/10-wayland.env.tmpl'))
        for key, value in (('NO_AT_BRIDGE', '1'), ('GTK_A11Y', 'none')):
            self.assertIn(key + '=' + value, session.splitlines())
            self.assertEqual(env[key], value)
        self.assertNotIn('DISPLAY', env)
        self.assertNotIn('AT_SPI_BUS_ADDRESS', env)

    def test_dock_metadata_relaunch_is_session_owned(self):
        import configparser
        import shlex
        entry = configparser.ConfigParser(interpolation=None)
        entry.read_string(render_theme_defaults(payload_read_text(TARGET/'usr/local/share/applications/labwc-notifications.desktop')))
        item = entry['Desktop Entry']
        self.assertEqual(item['NoDisplay'], 'true')
        self.assertEqual(item['Icon'], 'preferences-system-notifications-symbolic')
        argv = shlex.split(item['Exec'])
        self.assertEqual(argv[0], '/usr/bin/systemd-run')
        for word in ('--user', '--collect', '--expand-environment=no',
                     '--property=PartOf=labwc-session.target',
                     '--property=Requisite=labwc-session.target',
                     '--property=After=labwc-session.target',
                     '--property=ExitType=cgroup', '--property=KillMode=control-group'):
            self.assertIn(word, argv)
        self.assertEqual(argv[-3:], ['--', '/usr/local/libexec/labwc-notifications', 'center'])
        self.assertNotIn('sh', argv)
        components = render_theme_defaults(payload_read_text(TARGET.parents[1]/'scripts/desktop/components.sh'))
        self.assertIn('usr/local/share/applications/labwc-notifications.desktop /usr/local/share/applications/labwc-notifications.desktop 0644', components)

if __name__ == '__main__': unittest.main()
