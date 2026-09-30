"""Private-display policy and real inert-child lifecycle regressions."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from payload_fixture import python_library, read_text

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
LIB = python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')
sys.path.insert(0, str(LIB))
from labwc_managed_app import compat_protocol as protocol
from labwc_managed_app import compat_instance as instance
from labwc_managed_app import compat_gpu as gpu
from labwc_managed_app import compat_portal as portal
from labwc_managed_app import wayland_compat_runtime as runtime
from labwc_managed_app import commands, profiles, recovery, session, network_namespace, dbus_proxy, sandbox


def child(code, **kwargs):
    return subprocess.Popen([sys.executable, '-B', '-c',
        'import resource; resource.setrlimit(resource.RLIMIT_CORE,(0,0));' + code], **kwargs)


class OutcomeAndPipeTests(unittest.TestCase):
    def tearDown(self):
        runtime._received_signal = None

    def test_exit_7_is_application_failure(self):
        process = child('raise SystemExit(7)')
        self.assertEqual(protocol.Outcome.observed('discord', process.wait()), protocol.Outcome('application-failed', 7))

    def test_sigsegv_preserves_signal_and_nonzero_result(self):
        process = child('import os,signal; os.kill(os.getpid(),signal.SIGSEGV)')
        self.assertEqual(protocol.Outcome.observed('discord', process.wait()), protocol.Outcome('application-failed', 139, 11))

    def test_vendor_consumed_descendant_status_is_unknown(self):
        process = child('import subprocess,sys; subprocess.run([sys.executable,"-c","raise SystemExit(7)"]); raise SystemExit(0)')
        self.assertEqual(protocol.Outcome.observed('zoom', process.wait()), protocol.Outcome('outcome-unknown', 70))

    def test_normal_direct_child_is_success(self):
        process = child('raise SystemExit(0)')
        self.assertEqual(protocol.Outcome.observed('discord', process.wait()), protocol.Outcome('normal-exit', 0))

    def test_unknown_cannot_claim_success_and_cleanup_preserves_first_failure(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.Outcome('outcome-unknown', 0)
        failed = protocol.Outcome('application-failed', 139, 11).cleanup_failed()
        self.assertEqual((failed.primary, failed.result, failed.signal, failed.cleanup), ('application-failed', 139, 11, 'failed'))
        self.assertEqual(protocol.Outcome('normal-exit', 0).cleanup_failed().primary, 'cleanup-failed')

    def test_short_cage_stderr_is_inherited_without_eof_or_4k_wait(self):
        writer = reader = None
        read_fd, write_fd = os.pipe()
        original_popen = subprocess.Popen
        code = 'import os,time; os.write(2,b"short\\n"); time.sleep(.25)'
        def cage(_arguments, **kwargs):
            self.assertIsNone(kwargs['stderr'])
            return original_popen([sys.executable, '-B', '-c', code], stderr=write_fd,
                                  start_new_session=True, close_fds=True)
        handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        try:
            with mock.patch.object(runtime, 'protect_supervisor'), \
                    mock.patch.object(runtime, 'require_outer_cage_environment'), \
                    mock.patch.object(runtime, 'require_system_owned_file'), \
                    mock.patch.object(runtime.os, 'geteuid', return_value=1000), \
                    mock.patch.object(runtime.subprocess, 'Popen', side_effect=cage):
                # Run the supervisor in a fork: keep the test's reader active
                # while the inert Cage still holds stderr open.
                pid = os.fork()
                if pid == 0:
                    os.close(read_fd)
                    status = runtime.run_cage_supervisor(['discord', 'intel', '--', '/opt/discord/Discord'])
                    os._exit(status)
                os.close(write_fd)
                write_fd = None
                with selectors.DefaultSelector() as selector:
                    selector.register(read_fd, selectors.EVENT_READ)
                    self.assertTrue(selector.select(.15), 'short stderr was buffered until child exit')
                self.assertEqual(os.read(read_fd, 32), b'short\n')
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    def test_descendant_keeping_stderr_open_cannot_block_supervision(self):
        original_popen = subprocess.Popen
        children = []
        def cage(_arguments, **kwargs):
            p = original_popen([sys.executable, '-B', '-c',
                'import os,time; p=os.fork(); time.sleep(.8) if p==0 else None; os._exit(7)'],
                start_new_session=True, **{k: v for k, v in kwargs.items() if k != 'start_new_session'})
            children.append(p)
            return p
        handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        try:
            with mock.patch.object(runtime, 'protect_supervisor'), \
                    mock.patch.object(runtime, 'require_outer_cage_environment'), \
                    mock.patch.object(runtime, 'require_system_owned_file'), \
                    mock.patch.object(runtime.os, 'geteuid', return_value=1000), \
                    mock.patch.object(runtime.subprocess, 'Popen', side_effect=cage):
                start = time.monotonic()
                self.assertEqual(runtime.run_cage_supervisor(['discord','intel','--','/opt/discord/Discord']), 7)
                self.assertLess(time.monotonic() - start, .6)
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    def test_overall_cleanup_escalates_uncooperative_owned_child(self):
        process = child('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(30)',
                        stdout=subprocess.PIPE, start_new_session=True)
        self.assertEqual(process.stdout.readline(), b'ready\n')
        start = time.monotonic()
        self.assertTrue(protocol.stop_processes([process], start + .7, groups=True))
        self.assertLess(time.monotonic() - start, .9)
        self.assertEqual(process.returncode, -signal.SIGKILL)
        process.stdout.close()

    def test_actual_cage_signal_is_reported_separately_from_shell_status(self):
        original = subprocess.Popen
        def cage(_arguments, **kwargs):
            return original([sys.executable,'-B','-c',
                'import os,resource,signal;resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.kill(os.getpid(),signal.SIGSEGV)'],**kwargs)
        handlers = {s: signal.getsignal(s) for s in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM)}
        try:
            with mock.patch.object(runtime,'protect_supervisor'), \
                 mock.patch.object(runtime.os,'geteuid',return_value=1000), \
                 mock.patch.object(runtime,'require_system_owned_file'), \
                 mock.patch.object(runtime,'require_outer_cage_environment'), \
                 mock.patch.object(runtime.subprocess,'Popen',side_effect=cage), \
                 mock.patch.object(runtime,'report_compositor_outcome') as report:
                self.assertEqual(runtime.run_cage_supervisor(['discord','intel','--','/opt/discord/Discord']),139)
            report.assert_called_once_with('discord','intel',139,11,True)
        finally:
            for signum,handler in handlers.items():signal.signal(signum,handler)

    def test_cage_failure_before_readiness_never_launches_payload(self):
        with mock.patch.object(runtime, 'protect_supervisor'), \
                mock.patch.object(runtime.os, 'geteuid', return_value=1000), \
                mock.patch.object(runtime, 'require_system_owned_file'), \
                mock.patch.object(runtime, 'require_outer_cage_environment', side_effect=runtime.CompatibilityRuntimeError('readiness')), \
                mock.patch.object(runtime.subprocess, 'Popen') as create:
            with self.assertRaises(runtime.CompatibilityRuntimeError):
                runtime.run_cage_supervisor(['zoom','intel','--','/usr/bin/zoom'])
            create.assert_not_called()

    def test_intentional_slirp_end_does_not_replace_payload_exit(self):
        process = child('raise SystemExit(7)')
        slirp = child('raise SystemExit(0)')
        process.wait(); slirp.wait()
        self.assertEqual(network_namespace._wait_for_bwrap_with_slirp4netns(process, slirp, io.BytesIO()), 7)

    def test_required_slirp_failure_is_detected_while_payload_is_alive(self):
        process = child('import time; time.sleep(30)', start_new_session=True)
        slirp = child('raise SystemExit(4)')
        slirp.wait()
        try:
            with mock.patch.object(network_namespace, 'fail', side_effect=protocol.ProtocolError):
                with self.assertRaises(protocol.ProtocolError):
                    network_namespace._wait_for_bwrap_with_slirp4netns(process, slirp, io.BytesIO())
        finally:
            protocol.stop_processes([process], time.monotonic() + .5, groups=True)

    def test_required_proxy_failure_is_detected_at_runtime(self):
        p = child('raise SystemExit(3)'); p.wait()
        operations = dbus_proxy.ProxyRuntime(fail=lambda s: (_ for _ in ()).throw(protocol.ProtocolError(s)),
            require_root_owned_executable=lambda *args: args[-1], managed_subprocess_environment=lambda: {}, validate_session_bus_address=lambda x: x)
        with self.assertRaises(protocol.ProtocolError):
            dbus_proxy.require_running_dbus_proxy(p, '/absent', runtime=operations)

    def test_required_helpers_preserve_directly_observed_signal(self):
        payload = child('import time; time.sleep(10)', start_new_session=True)
        helper = child('import os,signal; os.kill(os.getpid(),signal.SIGSEGV)')
        helper.wait()
        try:
            with self.assertRaises(protocol.RequiredComponentError) as failed:
                network_namespace._wait_for_bwrap_with_slirp4netns(
                    payload, helper, io.BytesIO(), runtime_check=lambda: None)
            self.assertEqual((failed.exception.result, failed.exception.signal), (139, 11))
            with self.assertRaises(protocol.RequiredComponentError) as failed:
                sandbox.require_compatibility_dbus_proxies([(helper, '/absent', None)])
            self.assertEqual((failed.exception.result, failed.exception.signal), (139, 11))
            # A completed payload makes later intentional helper teardown moot.
            payload.terminate(); payload.wait()
            self.assertEqual(network_namespace._wait_for_bwrap_with_slirp4netns(
                payload, helper, io.BytesIO(), runtime_check=lambda: None), -signal.SIGTERM)
        finally:
            protocol.stop_processes([payload], time.monotonic() + .5, groups=True)

    def test_critical_helper_clean_exit_is_not_success(self):
        failure = protocol.RequiredComponentError(0)
        self.assertEqual((failure.result, failure.signal), (protocol.INFRASTRUCTURE_RESULT, 0))


class EnvironmentAndDisplayTests(unittest.TestCase):
    def test_discord_profile_has_one_trusted_x11_selector_in_every_mode(self):
        for mode in ('launch','intel','nvidia'):
            argv = commands.build_argv('discord', mode, [])
            self.assertEqual([a for a in argv if a.startswith('--ozone-platform=')], ['--ozone-platform=x11'])
            self.assertNotIn('--enable-wayland-ime', argv)
            self.assertNotIn('--no-sandbox', argv)

    def test_caller_backend_gpu_qt_and_sandbox_overrides_are_rejected(self):
        for app in ('discord','zoom'):
            for value in ('--ozone-platform=x11','--ozone-platform=wayland','-platform','--no-sandbox=false',
                          '-disable-gpu-sandbox','--use-gl=angle','--enable-features=Vulkan','--disable-gpu','--url=/bin/sh'):
                with self.subTest(app=app, value=value), self.assertRaises(SystemExit):
                    commands.build_argv(app, 'intel', [value])

    def test_zoom_payload_gets_xcb_and_no_host_plugin_loader_or_server_environment(self):
        poison = {'QT_QPA_PLATFORMTHEME':'qt6ct','QT_PLUGIN_PATH':'/tmp/plugins','QML2_IMPORT_PATH':'/tmp/qml',
                  'LD_PRELOAD':'/tmp/inject.so','LD_AUDIT':'/tmp/audit.so','LD_LIBRARY_PATH':runtime.PRIVATE_RUNTIME_LIBRARY_DIRECTORY,
                  'WLR_BACKENDS':'wayland','WAYLAND_DISPLAY':'wayland-0','WAYLAND_SOCKET':'9','DISPLAY':':0'}
        with mock.patch.dict(os.environ, poison, clear=True):
            env = runtime.application_process_environment('zoom')
        self.assertEqual(env['QT_QPA_PLATFORM'], 'xcb')
        self.assertEqual(env['DISPLAY'], ':0')
        for key in ('QT_QPA_PLATFORMTHEME','QT_PLUGIN_PATH','QML2_IMPORT_PATH','LD_PRELOAD','LD_AUDIT','LD_LIBRARY_PATH','WLR_BACKENDS','WAYLAND_DISPLAY','WAYLAND_SOCKET'):
            self.assertNotIn(key, env)

    def test_discord_keeps_only_its_vendor_library_directory(self):
        with mock.patch.dict(os.environ, {'LD_LIBRARY_PATH':'/tmp/poison','WLR_XWAYLAND':'/opt/xwayland/usr/bin/Xwayland'}, clear=True):
            env = runtime.application_process_environment('discord')
        self.assertEqual(env['LD_LIBRARY_PATH'], '/opt/discord')
        self.assertEqual(env['ELECTRON_OZONE_PLATFORM_HINT'], 'x11')
        self.assertNotIn('WLR_XWAYLAND', env)

    def test_unrelated_applications_keep_wayland_and_cannot_select_compatibility(self):
        self.assertIn('--ozone-platform=wayland', commands.build_argv('bitwarden','intel',[]))
        with self.assertRaises(SystemExit):
            commands.validate_managed_arguments('intel',['--ozone-platform=x11'], app_name='bitwarden')
        with self.assertRaises(protocol.ProtocolError):
            protocol.activation_arguments('bitwarden', [])
        with self.assertRaises(runtime.CompatibilityRuntimeError):
            runtime.masked_application_argv('bitwarden','wayland-0','wayland-1',['/opt/Bitwarden/bitwarden'])

    def test_payload_masks_both_wayland_sockets_and_supervisor_authority(self):
        argv = runtime.masked_application_argv('discord','wayland-0','wayland-1',['/opt/discord/Discord'])
        for display in ('wayland-0','wayland-1'):
            self.assertIn(['--ro-bind','/dev/null', f'/run/user/{os.getuid()}/{display}'], [argv[i:i+3] for i in range(len(argv))])
        for path in (protocol.CONTROL_DIRECTORY, '/opt/xwayland'):
            self.assertIn(['--tmpfs',path], [argv[i:i+2] for i in range(len(argv))])
        self.assertIn('--unshare-pid', argv)
        self.assertIn('--cap-drop', argv)

    def test_separate_outer_namespace_contains_local_x11_socket_only(self):
        text = read_text(TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py')
        self.assertIn('"--unshare-all"', text)
        self.assertIn('PRIVATE_X11_SOCKET_DIRECTORY', text)
        self.assertNotIn('"--bind", "/tmp/.X11-unix"', text)
        self.assertFalse(profiles.PERSISTENT_SANDBOX_CONFIG['discord']['share_net'])
        self.assertTrue(profiles.PERSISTENT_SANDBOX_CONFIG['discord']['slirp4netns'])
        # Identical display numbers are accepted only for the private namespace.
        with mock.patch.dict(os.environ, {'DISPLAY':':0','WLR_XWAYLAND':runtime.XWAYLAND_EXEC_HELPER}, clear=True):
            self.assertEqual(runtime.require_cage_x11_display(), '0')
        with mock.patch.dict(os.environ, {'DISPLAY':'localhost:0','WLR_XWAYLAND':runtime.XWAYLAND_EXEC_HELPER}, clear=True):
            with self.assertRaises(runtime.CompatibilityRuntimeError):
                runtime.require_cage_x11_display()

    def test_actual_x11_readiness_requires_protocol_success_not_socket_existence(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as td:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(Path(td)/'X0')); server.listen(1)
            pid = os.fork()
            if pid == 0:
                conn, _ = server.accept(); conn.recv(12); conn.sendall(b'\x00\x00\x0b\x00\x00\x00\x00\x00'); conn.close(); os._exit(0)
            try:
                with mock.patch.object(runtime,'X11_SOCKET_DIRECTORY',td):
                    with self.assertRaises(runtime.CompatibilityRuntimeError):
                        runtime.require_x11_connection('0')
            finally:
                server.close(); os.waitpid(pid,0)

    def test_private_server_wrapper_preserves_arguments_and_has_no_fallback(self):
        source = (TARGET/'usr/local/libexec/labwc-private-xwayland').read_text()
        self.assertIn('exec /opt/xwayland/usr/bin/Xwayland "$@"', source)
        self.assertNotIn('/usr/bin/Xwayland', source.replace('/opt/xwayland/usr/bin/Xwayland',''))
        self.assertNotIn('eval', source)
        subprocess.run(['/bin/dash','-n',str(TARGET/'usr/local/libexec/labwc-private-xwayland')],check=True)


class ActivationAndPolicyTests(unittest.TestCase):
    def test_compositor_status_does_not_overwrite_an_observed_application_failure(self):
        coordinator = object.__new__(instance.CompatibilityInstance)
        coordinator.run_id='a'*32; coordinator.running=True; coordinator.cleanup_deadline=None; coordinator.cleanup_failed=False
        record={'type':'compositor-outcome','run_id':'a'*32,'result':139,'signal':11,'cleanup':'ok'}
        coordinator.outcome=protocol.Outcome('application-failed',7)
        coordinator._compositor_outcome(record)
        self.assertEqual(coordinator.outcome,protocol.Outcome('application-failed',7))
        coordinator.outcome=None
        coordinator._compositor_outcome(record)
        self.assertEqual(coordinator.outcome,protocol.Outcome('infrastructure-failed',139,11))
        coordinator.outcome=protocol.Outcome('normal-exit',0)
        record.update(result=0,signal=0,cleanup='failed')
        coordinator._compositor_outcome(record)
        self.assertEqual(coordinator.outcome.primary,'cleanup-failed')
    def test_approved_https_uri_is_data_and_secret_text_is_not_logged(self):
        url = 'https://discord.com/handoff?rpc=6463&key=TEST_SECRET'
        self.assertEqual(protocol.validate_uri(url, {'https'}), url)
        with mock.patch.object(portal.os,'geteuid',return_value=1000), \
                mock.patch.object(portal,'filtered_bus_address',return_value='unix:path=/test'), \
                mock.patch.object(portal,'open_uri',return_value=0) as open_uri:
            self.assertEqual(portal.main([url]), 0)
            open_uri.assert_called_once_with(url,'unix:path=/test','')
        with mock.patch.object(portal.os,'geteuid',return_value=1000), mock.patch.object(portal.sys,'stderr',io.StringIO()) as output:
            self.assertEqual(portal.main(['file:///TEST_SECRET']), 2)
            self.assertNotIn('TEST_SECRET', output.getvalue())

    def test_unsafe_uris_and_multiple_inputs_are_rejected(self):
        values = ['file:///etc/passwd','javascript:alert(1)','data:text/html,hi','http://example.com/',
                  '/usr/bin/chromium','https:///missing','https://user:password@example.com/',
                  'https://example.com/$(id)','https://example.com/`id`','https://example.com/%00',
                  'https://example.com/\n','https://example.com/%GG','https://example.com/'+'x'*8192]
        for uri in values:
            with self.subTest(uri=uri[:40]), self.assertRaises((protocol.ProtocolError, ValueError)):
                protocol.validate_uri(uri, {'https'})
        with self.assertRaises(protocol.ProtocolError):
            protocol.activation_arguments('discord',['discord://a','discord://b'])
        with self.assertRaises(protocol.ProtocolError):
            protocol.activation_arguments('zoom',[None])

    def test_application_protocols_canonicalize_to_managed_argv(self):
        self.assertEqual(protocol.activation_arguments('zoom',['zoommtg://zoom.us/join?pwd=SECRET']), ['--url=zoommtg://zoom.us/join?pwd=SECRET'])
        self.assertEqual(protocol.activation_arguments('discord',['discord://-/handoff?key=SECRET']), ['discord://-/handoff?key=SECRET'])
        with self.assertRaises(protocol.ProtocolError):
            protocol.activation_arguments('discord',['zoommtg://zoom.us/join'])

    def test_session_restore_contains_only_safe_base_launch(self):
        import base64
        argv = [session.WAYLAND_COMPAT_MANAGED_APP_PATH,'intel','zoom','--url=zoommtg://zoom.us/join?pwd=SECRET']
        saved = json.loads(base64.urlsafe_b64decode(recovery.restart_token(argv)))
        self.assertEqual(saved['argv'], argv[:3])
        self.assertNotIn('SECRET', json.dumps(saved))

    def test_real_seqpacket_transport_bounds_input_and_preserves_signal(self):
        a,b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            expected = protocol.Outcome('application-failed',139,11)
            protocol.send_packet(a,expected.packet())
            self.assertEqual(protocol.Outcome.from_packet(protocol.receive_packet(b)), expected)
            a.send(b'x'*(protocol.MAX_PACKET_BYTES+1))
            with self.assertRaises(protocol.ProtocolError):
                protocol.receive_packet(b)
            with self.assertRaises(protocol.ProtocolError):
                protocol.Outcome.from_packet({'type':'outcome','primary':'normal-exit','result':0,'signal':0,'cleanup':'ok','secret':'unexpected'})
        finally:
            a.close(); b.close()

    def test_lock_rejects_symlink_hardlink_and_wrong_modes(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            original = directory/'other'; original.write_text(''); original.chmod(0o600)
            (directory/'instance.lock').symlink_to(original)
            with self.assertRaises(OSError): instance.open_lock(directory,'instance.lock')
            (directory/'instance.lock').unlink(); os.link(original,directory/'instance.lock')
            with self.assertRaises(protocol.ProtocolError): instance.open_lock(directory,'instance.lock')
            (directory/'instance.lock').unlink(); original.chmod(0o666)
            with self.assertRaises(protocol.ProtocolError): instance.open_lock(directory,'other')

    def test_real_lock_serializes_and_has_a_monotonic_timeout(self):
        import fcntl
        with tempfile.TemporaryDirectory() as td:
            a = instance.open_lock(Path(td),'instance.lock'); b = instance.open_lock(Path(td),'instance.lock')
            try:
                instance.acquire_lock(a,time.monotonic()+1)
                with self.assertRaises(protocol.ProtocolError): instance.acquire_lock(b,time.monotonic()+.08)
                fcntl.flock(a,fcntl.LOCK_UN)
                instance.acquire_lock(b,time.monotonic()+1)
            finally: os.close(a); os.close(b)

    def test_forged_and_stale_service_identity_is_rejected(self):
        a,b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            hello = {'type':'instance','app':'discord','mode':'intel','run_id':'a'*32,
                     'unit':'labwc-compat-discord-'+'a'*32+'.service','invocation':'b'*32}
            with mock.patch.object(instance,'process_unit',return_value=hello['unit']), \
                    mock.patch.object(instance,'require_root_owned_executable',return_value='/usr/bin/systemctl'), \
                    mock.patch.object(instance,'current_user_runtime_dir',return_value='/run/user/1000'), \
                    mock.patch.object(instance.subprocess,'run',return_value=mock.Mock(returncode=0,stdout=b'ActiveState=active\nMainPID=1\nInvocationID=forged\n')):
                with self.assertRaises(protocol.ProtocolError): instance._verify_service(a,hello,'discord')
            hello['unit'] = 'unrelated.service'
            with self.assertRaises(protocol.ProtocolError): instance._verify_service(a,hello,'discord')
        finally: a.close(); b.close()

    def test_filtered_portal_policy_excludes_service_manager_ownership_and_wildcard_talk(self):
        operations = dbus_proxy.ProxyRuntime(fail=lambda s: (_ for _ in ()).throw(protocol.ProtocolError(s)),
            require_root_owned_executable=lambda *args: args[-1], managed_subprocess_environment=lambda: {}, validate_session_bus_address=lambda x: x)
        with mock.patch.dict(os.environ,{'DBUS_SESSION_BUS_ADDRESS':'unix:path=/test'}), \
                mock.patch.object(dbus_proxy,'start_filtered_dbus_proxy',return_value=(None,None,None)) as start:
            dbus_proxy.start_session_bus_proxy('/private',compatibility=True,required=True,runtime=operations)
            rules = start.call_args.args[3]
        self.assertTrue(any('OpenURI.OpenURI@' in rule for rule in rules))
        self.assertTrue(any('Request.Response@' in rule for rule in rules))
        self.assertNotIn('--talk=org.freedesktop.portal.*', rules)
        self.assertFalse(any('systemd' in rule or rule.startswith('--own=') for rule in rules))
        self.assertEqual(profiles.ZOOM_SESSION_DBUS_OWN_NAMES, ())

    def test_effective_policy_denies_browser_daemon_and_direct_private_tools(self):
        policy = read_text(TARGET/'etc/apparmor.d/zoom-discord-compat')
        self.assertIn('deny /usr/bin/chromium rxm,', policy)
        self.assertIn('deny /usr/libexec/xdg-desktop-portal rxm,', policy)
        self.assertIn('/usr/local/libexec/labwc-{private-xwayland,compat-open-uri} rix,', policy)
        self.assertNotIn('signal (send) peer=unconfined,', policy)
        self.assertNotIn('owner @{PROC}/[0-9]*/mem r,', policy)
        prep = read_text(TARGET/'etc/apparmor.d/abstractions/bwrap-compat-preparation')
        self.assertNotIn('capability sys_ptrace,', prep)
        self.assertNotIn('capability net_admin,', prep)
        self.assertIn('profile labwc-xwayland-direct-exec-deny', policy)
        self.assertIn('profile labwc-private-xwayland-direct-deny', policy)
        self.assertIn('zoom-discord-compat', read_text(TARGET/'etc/apparmor/modes.conf'))

    def test_all_compatibility_desktop_actions_and_protocols_use_wrappers(self):
        import runpy
        wrapper = runpy.run_path(str(TARGET/'usr/local/libexec/labwc-wrap-desktop-files'))
        for binary, name in (('/usr/bin/zoom','zoom'),('/opt/discord/Discord','discord')):
            source = '[Desktop Entry]\nType=Application\nDBusActivatable=true\nExec='+binary+' %U\nActions=Open;\n[Desktop Action Open]\nExec='+binary+' %U\n'
            result = wrapper['rewrite_desktop'](source,'/usr/local/bin/labwc-wayland-app intel')
            self.assertNotIn('Exec='+binary+' ', result)
            self.assertIn('Exec=/usr/local/bin/'+name+(' %u' if name == 'zoom' else ' %U'), result)
            self.assertIn('DBusActivatable=false',result)
        discord = read_text(TARGET/'usr/local/share/applications/discord.desktop')
        self.assertIn('Exec=/usr/local/bin/discord %U', discord)
        self.assertIn('x-scheme-handler/discord', discord)

    def test_environment_prefixed_terminal_and_legacy_vendor_routes_stay_managed(self):
        import runpy
        rewrite = runpy.run_path(str(TARGET/'usr/local/libexec/labwc-wrap-desktop-files'))['rewrite_desktop']
        for command in ('env LD_PRELOAD="/tmp/with space" /usr/bin/zoom --url=%U',
                        '/opt/zoom/ZoomLauncher --url=%U',
                        '/usr/local/bin/labwc-wayland-app intel -- /opt/zoom/zoom --url=%U'):
            text = '[Desktop Entry]\nType=Application\nTerminal=true\nExec='+command+'\n'
            result = rewrite(text,'/usr/local/bin/labwc-wayland-app intel')
            self.assertIn('Exec=/usr/local/bin/zoom %u',result)
            self.assertIn('Terminal=false',result)
            self.assertNotIn('LD_PRELOAD',result)


class NamespaceDisplayTests(unittest.TestCase):
    def test_two_concurrent_displays_are_local_and_cannot_reach_other_or_host_sockets(self):
        bwrap = '/usr/bin/bwrap'
        if not Path(bwrap).is_file(): self.skipTest('Bubblewrap is unavailable')
        probe = subprocess.run([bwrap,'--unshare-all','--ro-bind','/','/','--','/bin/true'],
                               capture_output=True,timeout=5)
        if probe.returncode:
            reason = probe.stderr.decode('utf-8','replace').strip()[:300]
            self.skipTest('Kernel/private namespaces unavailable: '+reason)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            servers=[]; threads=[]; children=[]
            host_wayland = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            host_wayland.bind(str(root/'wayland-0')); host_wayland.listen(1)
            servers.append(host_wayland)
            def serve(server, name):
                server.settimeout(5)
                connection,_=server.accept(); connection.sendall(name.encode()); connection.close()
            code = '''import os,socket,sys
assert os.environ['DISPLAY']==':0'
assert 'WAYLAND_DISPLAY' not in os.environ and 'XAUTHORITY' not in os.environ
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect('/tmp/.X11-unix/X0')
assert s.recv(32).decode()==sys.argv[1];s.close()
for path in sys.argv[2:]:
 s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
 try:s.connect(path)
 except OSError:pass
 else:raise SystemExit('foreign display visible')
 finally:s.close()
'''
            try:
                for app in ('zoom','discord'):
                    path=root/(app+'.sock')
                    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));server.listen(1)
                    servers.append(server)
                    thread=threading.Thread(target=serve,args=(server,app));thread.start();threads.append(thread)
                for app in ('zoom','discord'):
                    other='zoom' if app=='discord' else 'discord'
                    argv=[bwrap,'--unshare-all','--ro-bind','/','/','--tmpfs','/tmp',
                          '--dir','/tmp/.X11-unix','--ro-bind',str(root/(app+'.sock')),'/tmp/.X11-unix/X0',
                          '--setenv','DISPLAY',':0','--unsetenv','WAYLAND_DISPLAY','--unsetenv','XAUTHORITY',
                          '--',sys.executable,'-B','-c',code,app,str(root/(other+'.sock')),str(root/'wayland-0')]
                    children.append(subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE))
                for process in children:
                    stdout,stderr=process.communicate(timeout=5)
                    self.assertEqual(process.returncode,0,(stdout+stderr).decode('utf-8','replace'))
            finally:
                protocol.stop_processes(children,time.monotonic()+1)
                for server in servers: server.close()
                for thread in threads: thread.join(5)


if __name__ == '__main__':
    unittest.main()
