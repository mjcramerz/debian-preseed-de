"""Real local IPC/children for optional helpers, activation and final outcomes."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from payload_fixture import python_library
ROOT = Path(__file__).resolve().parents[3]
TARGET = Path(__file__).resolve().parents[1]/'hooks/target'
sys.path.insert(0,str(python_library(TARGET/'usr/local/lib/python3.14/dist-packages')))
from labwc_managed_app import compat_instance as instance, compat_protocol as protocol
from labwc_managed_app import wayland_compat_runtime as runtime, wayland_compat, cli

PRIMARY_CHILD = '''import json,os,socket,time
s=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET)
s.connect(os.environ['LABWC_COMPAT_PRIMARY_SOCKET'])
s.send(json.dumps({'type':'primary-ready'}).encode())
s.recv(16384)
s.send(json.dumps({'type':'running'}).encode())
time.sleep(.15)
s.send(json.dumps({'type':'outcome','primary':'normal-exit','result':0,'signal':0,'cleanup':'ok'}).encode())
s.send(json.dumps({'type':'cleanup','failed':False}).encode())
s.close()
'''


class RuntimeLifecycleTests(unittest.TestCase):
    def tearDown(self): runtime._received_signal=None

    def exercise(self, clipboard, lose_x11=False):
        host, runtime_host = socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        x11, x11_peer = socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        children=[]; original=subprocess.Popen
        def launch(argv, **kwargs):
            is_bridge=argv[:2]==[runtime.SANDBOX_LIFECYCLE_HELPER,runtime.CLIPBOARD_BRIDGE_MODE]
            code='raise SystemExit(4)' if is_bridge else PRIMARY_CHILD
            p=original([sys.executable,'-B','-c',code],**kwargs)
            children.append(p); return p
        def lose():
            host.settimeout(2)
            if protocol.receive_packet(host)=={'type':'running'}: x11_peer.close()
        thread=threading.Thread(target=lose) if lose_x11 else None
        handlers={s:signal.getsignal(s) for s in (signal.SIGHUP,signal.SIGINT,signal.SIGTERM)}
        try:
            if thread: thread.start()
            with mock.patch.dict(os.environ,{'LABWC_COMPAT_CLIPBOARD':str(clipboard),
                    runtime.OUTER_WAYLAND_DISPLAY_ENVIRONMENT:'wayland-0','WAYLAND_DISPLAY':'wayland-1'}), \
                 mock.patch.object(runtime,'protect_supervisor'), \
                 mock.patch.object(runtime.os,'geteuid',return_value=1000), \
                 mock.patch.object(runtime,'connect_runtime',return_value=runtime_host), \
                 mock.patch.object(runtime,'require_cage_wayland_socket'), \
                 mock.patch.object(runtime,'require_cage_x11_display',return_value='0'), \
                 mock.patch.object(runtime,'require_private_x11_socket_directory'), \
                 mock.patch.object(runtime,'require_private_x11_socket'), \
                 mock.patch.object(runtime,'require_x11_connection',return_value=x11), \
                 mock.patch.object(runtime,'require_system_owned_file'), \
                 mock.patch.object(runtime.subprocess,'Popen',side_effect=launch), \
                 mock.patch.object(runtime.sys,'stderr',io.StringIO()) as diagnostic:
                result=runtime.run(['discord','intel','--','/opt/discord/Discord'])
            if thread: thread.join(2); self.assertFalse(thread.is_alive())
            host.settimeout(.2); packets=[]
            while True:
                try: packets.append(protocol.receive_packet(host))
                except (OSError,protocol.ProtocolError): break
            self.assertTrue(all(p.poll() is not None for p in children))
            return result, packets, children, diagnostic.getvalue()
        finally:
            protocol.stop_processes(children,time.monotonic()+.5,groups=True)
            for s in (host,runtime_host,x11,x11_peer): s.close()
            for signum,handler in handlers.items(): signal.signal(signum,handler)

    def test_optional_clipboard_failure_does_not_kill_active_application(self):
        result,packets,children,diagnostic=self.exercise(1)
        self.assertEqual(result,0)
        self.assertEqual(len(children),2)
        self.assertTrue(any(p.get('primary')=='normal-exit' for p in packets))
        self.assertIn('clipboard bridge degraded',diagnostic)

    def test_disabled_bridge_launches_no_host_clipboard_child(self):
        result,packets,children,_=self.exercise(0)
        self.assertEqual(result,0); self.assertEqual(len(children),1)

    def test_required_xwayland_loss_is_infrastructure_failure_and_cleans_application(self):
        result,packets,children,_=self.exercise(0,lose_x11=True)
        self.assertEqual(result,protocol.INFRASTRUCTURE_RESULT)
        self.assertTrue(any(p.get('primary')=='infrastructure-failed' for p in packets))
        self.assertNotEqual(children[0].returncode,0)


RUNTIME_CLIENT='''import json,socket,sys
s=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET);s.connect(sys.argv[1])
s.recv(16384);s.send(json.dumps({'type':'runtime','run_id':'a'*32}).encode());s.recv(16384)
s.send(b'{"type":"running"}')
while True:
 data=s.recv(16384)
 if not data:break
 packet=json.loads(data)
 if packet['type']=='activate':
  print(json.dumps(packet['args']),flush=True)
  s.send(json.dumps({'type':'activation','id':packet['id'],'accepted':True}).encode())
'''


class InstanceIPCTests(unittest.TestCase):
    def test_real_lifetime_lock_and_approved_uri_reuse_one_instance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            directory=Path(td); directory.chmod(0o700)
            unit='labwc-compat-discord-'+'a'*32+'.service'
            status=mock.Mock(returncode=0,stdout=f'MainPID={os.getpid()}\nInvocationID={"b"*32}\nActiveState=active\n'.encode())
            with mock.patch.dict(os.environ,{'INVOCATION_ID':'b'*32}), \
                 mock.patch.object(instance,'instance_directory',return_value=directory), \
                 mock.patch.object(instance,'process_unit',return_value=unit), \
                 mock.patch.object(instance,'protect_supervisor'), \
                 mock.patch.object(instance,'require_root_owned_executable',return_value='/usr/bin/systemctl'), \
                 mock.patch.object(instance,'current_user_runtime_dir',return_value='/run/user/1000'), \
                 mock.patch.object(instance.subprocess,'run',return_value=status):
                with instance.CompatibilityInstance('discord','intel') as coordinator:
                    process=subprocess.Popen([sys.executable,'-B','-c',RUNTIME_CLIENT,str(directory/'instance.sock'),instance.RUNTIME_HELPER],
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
                    try:
                        deadline=time.monotonic()+3
                        while not coordinator.running and time.monotonic()<deadline:
                            coordinator.service(); time.sleep(.005)
                        self.assertTrue(coordinator.running)
                        for args in ([],['discord://-/handoff?key=TEST_SECRET']):
                            results=[]
                            def activate():
                                try: results.append(instance.request_activation('discord','intel',args,deadline=time.monotonic()+2))
                                except Exception as exc: results.append(exc)
                            thread=threading.Thread(target=activate); thread.start()
                            deadline=time.monotonic()+3
                            while thread.is_alive() and time.monotonic()<deadline:
                                coordinator.service(); time.sleep(.005)
                            thread.join(.1); self.assertFalse(thread.is_alive())
                            self.assertEqual(results,[True])
                        self.assertEqual(json.loads(process.stdout.readline()),['discord://-/handoff?key=TEST_SECRET'])
                        self.assertIsNone(process.poll())
                        # A second service owner cannot acquire the lifetime lock.
                        with self.assertRaises(BlockingIOError):
                            with instance.CompatibilityInstance('discord','intel'): pass
                    finally:
                        protocol.stop_processes([process],time.monotonic()+.5,groups=True)
                        process.stdout.close(); process.stderr.close()
                self.assertFalse((directory/'instance.sock').exists())
                self.assertFalse(instance.request_activation('discord','intel',[],deadline=time.monotonic()+1))

    def test_replaced_lifetime_lock_or_endpoint_is_rejected_and_not_unlinked(self):
        for replace in ('instance.lock','instance.sock'):
            with tempfile.TemporaryDirectory(dir=ROOT) as td:
                directory=Path(td); directory.chmod(0o700)
                unit='labwc-compat-zoom-'+'a'*32+'.service'
                with mock.patch.dict(os.environ,{'INVOCATION_ID':'b'*32}), \
                     mock.patch.object(instance,'instance_directory',return_value=directory), \
                     mock.patch.object(instance,'process_unit',return_value=unit), \
                     mock.patch.object(instance,'protect_supervisor'):
                    with instance.CompatibilityInstance('zoom','intel') as coordinator:
                        path=directory/replace; path.unlink(); path.write_text('replacement'); path.chmod(0o600)
                        with self.assertRaises(protocol.ProtocolError): coordinator.service()
                    self.assertEqual(path.read_text(),'replacement')

    def test_live_endpoint_without_lifetime_owner_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            directory=Path(td); directory.chmod(0o700)
            server=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET)
            server.bind(str(directory/'instance.sock')); (directory/'instance.sock').chmod(0o600); server.listen(1)
            try:
                with mock.patch.object(instance,'instance_directory',return_value=directory):
                    with self.assertRaises(protocol.ProtocolError):
                        instance.request_activation('zoom','intel',[],deadline=time.monotonic()+1)
            finally: server.close()


class FinalOutcomeTests(unittest.TestCase):
    def exercise(self, shutdown, observed=None):
        obj=mock.Mock(run_id='a'*32,stop_signal=15,outcome=observed,running=True,cleanup_failed=False)
        obj.__enter__=mock.Mock(return_value=obj); obj.__exit__=mock.Mock(return_value=False)
        with mock.patch.object(instance,'CompatibilityInstance',return_value=obj), \
             mock.patch.object(cli,'resolved_executable',return_value='/usr/bin/true'), \
             mock.patch.object(cli,'validate_required_runtime_files'), \
             mock.patch.object(cli,'current_user_home',return_value='/home/user'), \
             mock.patch.object(cli,'ensure_managed_runtime_state'), \
             mock.patch.object(cli,'ensure_discord_managed_settings'), \
             mock.patch.object(cli,'current_user_runtime_dir',return_value='/run/user/1000'), \
             mock.patch.object(cli.os.path,'lexists',return_value=shutdown), \
             mock.patch.object(wayland_compat,'run_wayland_compat_sandbox',side_effect=InterruptedError), \
             mock.patch.object(cli,'emit') as emit:
            result=cli._run_compatibility('discord','intel',['discord://-/handoff?key=TEST_SECRET'])
        records=[call for call in emit.call_args_list if call.args[0]=='compat-outcome']
        self.assertEqual(len(records),1); self.assertNotIn('TEST_SECRET',repr(records))
        return result, records[0].kwargs

    def test_term_and_session_stop_have_separate_signal_outcomes(self):
        for shutdown,primary in ((False,'user-stopped'),(True,'shutdown-stopped')):
            result,record=self.exercise(shutdown)
            self.assertEqual(result,143); self.assertEqual(record['signal'],15); self.assertEqual(record['primary'],primary)

    def test_stop_during_cleanup_preserves_first_causal_application_failure(self):
        result,record=self.exercise(True,protocol.Outcome('application-failed',139,11))
        self.assertEqual(result,139); self.assertEqual(record['primary'],'application-failed'); self.assertEqual(record['signal'],11)


if __name__=='__main__': unittest.main()
