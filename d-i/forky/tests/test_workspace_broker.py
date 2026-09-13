"""Scoped workspace broker tests: actual reducer, strict IPC and fake Wayland edge.

No compositor, compiler, display capture, package install or privileged policy
load is performed. Real Moo/PyWayland import tests skip explicitly when absent.
"""
from __future__ import annotations
import ast
import errno
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
ROOT = FORKY.parents[1]
TARGET = FORKY / 'hooks/target'
APP = TARGET / 'usr/local/lib/labwc-workspace-broker'
PERL = APP / 'perl5'
sys.path.insert(0, str(APP / 'python'))
from labwc_workspace_wayland import wire
from labwc_workspace_wayland.driver import Driver, bounded_string


class Proxy:
    def __init__(self):
        self.dispatcher = {}
        self.calls = []
        self.destroyed = False
    def emit(self, name, *args):
        self.dispatcher[name](self, *args)
    def destroy(self):
        self.destroyed = True
    def release(self):
        self.calls.append(('release',))
        self.destroyed = True
    def activate(self, seat):
        self.calls.append(('activate', seat))
    def set_minimized(self):
        self.calls.append(('set_minimized',))
    def unset_minimized(self):
        self.calls.append(('unset_minimized',))
    def close(self):
        self.calls.append(('close',))


class Registry(Proxy):
    def __init__(self):
        super().__init__()
        self.bound = {}
    def bind(self, name, interface, version):
        proxy = Proxy()
        self.bound[name] = (interface, version, proxy)
        return proxy


class Display:
    def __init__(self):
        self.registry = Registry()
        self.fences = []
        self.flushed = []
        self.roundtrips = []
    def sync(self):
        p = Proxy()
        self.fences.append(p)
        return p
    def connect(self):
        pass
    def get_registry(self):
        return self.registry
    def roundtrip(self):
        if self.roundtrips:
            self.roundtrips.pop(0)()
        return 0
    def flush(self):
        return self.flushed.pop(0) if self.flushed else 0


class ProtocolDriverTests(unittest.TestCase):
    def setUp(self):
        self.display = Display()
        self.a, self.b = socket.socketpair()
        self.addCleanup(self.a.close)
        self.addCleanup(self.b.close)
        self.driver = Driver(self.display, self.a, {k: k for k in (
            'wl_output', 'wl_seat', 'ext_workspace_manager_v1', 'zwlr_foreign_toplevel_manager_v1')}, lambda: errno.EAGAIN)
    def drain(self):
        messages = wire.take(self.driver.outgoing)
        self.assertFalse(self.driver.outgoing)
        return messages
    def output(self, name=1, label='eDP-1'):
        self.driver.bind_globals(self.display.registry, name, 'wl_output', 4)
        proxy = self.display.registry.bound[name][2]
        proxy.emit('name', label)
        proxy.emit('done')
        return proxy
    def task(self):
        p = Proxy()
        self.driver.new_task(None, p)
        return p
    def fence(self):
        self.driver.start_fence()
        first = self.driver.fence
        first.emit('done', 1)
        self.assertTrue(first.destroyed)
        self.assertIsNotNone(self.driver.fence)
        self.driver.fence.emit('done', 2)
        self.assertIsNone(self.driver.fence)
    def command(self, command_id=1, ident=None, **fields):
        if ident is None:
            ident = next(iter(self.driver.tasks))
        return dict(v=1, kind='command', instance=self.driver.instance,
                    command_id=command_id, op='activate', id=ident, **fields)
    def test_done_buffers_toplevel_and_fences(self):
        out = self.output(); self.drain()
        p = self.task()
        ident = next(iter(self.driver.tasks))
        p.emit('app_id', 'foot'); p.emit('title', 'A <title>')
        p.emit('output_enter', out); p.emit('state', struct.pack('=I', 2))
        self.assertEqual([m['kind'] for m in self.drain()], ['new'])
        p.emit('done')
        msg = self.drain()[0]
        self.assertEqual((msg['kind'], msg['state'], msg['observed_state']), ('task', 4, 1))
        self.assertEqual(msg['id'], ident)
        self.assertNotIn('workspace', msg)
        p.emit('title', 'new title'); p.emit('done')
        self.assertEqual(self.drain()[0]['observed_state'], 0)
        self.fence()
        self.assertEqual([m['kind'] for m in self.drain()], ['barrier'])
        self.assertFalse(self.driver.pending)
    def test_workspace_uint_state_manager_done(self):
        out = self.output(); self.drain()
        p = Proxy(); g = Proxy()
        self.driver.new_group(None, g); self.driver.new_workspace(None, p)
        p.emit('name', '12'); p.emit('id', 'stable'); p.emit('state', 1)
        g.emit('output_enter', out); g.emit('workspace_enter', p)
        self.assertEqual(self.drain(), [])
        self.driver.publish_workspaces()
        msg = self.drain()[0]
        self.assertEqual(msg['workspaces'][0]['state'], 1)
        self.assertEqual(msg['groups'][0]['workspaces'], [msg['workspaces'][0]['id']])
        self.assertFalse(self.driver.workspace_dirty)
        p.emit('removed'); self.driver.publish_workspaces()
        self.assertEqual(self.drain()[0]['workspaces'], [])
        self.assertTrue(p.destroyed)
    def test_fence_restarts_on_interleaved_protocol_changes(self):
        p = self.task(); p.emit('done'); self.drain()
        self.driver.start_fence()
        old = self.driver.fence
        p.emit('title', 'changed'); p.emit('done')
        old.emit('done', 1)
        self.driver.fence.emit('done', 2)
        self.assertIsNotNone(self.driver.fence)
        self.driver.fence.emit('done', 3)
        self.assertEqual([m['kind'] for m in self.drain()], ['task', 'barrier'])
    def test_hotplug_keeps_retired_proxy_until_fence(self):
        out = self.output(); p = self.task()
        p.emit('output_enter', out); p.emit('done'); self.drain()
        self.driver.remove_global(None, 1)
        self.assertFalse(out.destroyed)
        p.emit('output_leave', out); p.emit('done')
        self.fence()
        messages = self.drain()
        self.assertEqual(messages[0]['outputs'], [])
        self.assertEqual(messages[1]['outputs'], [])
        self.assertTrue(out.destroyed)
        self.assertNotIn(out, self.driver.output_proxies)
    def test_four_fixed_requests_and_actual_state_authority(self):
        self.driver.seat = Proxy(); self.driver.seat_keyboard = True
        p = self.task(); p.emit('state', struct.pack('=I', 2)); p.emit('done'); self.drain()
        ident = next(iter(self.driver.tasks))
        for n, op in enumerate(('activate', 'set_minimized', 'unset_minimized', 'close'), 1):
            cmd = self.command(n); cmd['op'] = op
            self.driver.command(cmd)
            ack = self.drain()[0]
            self.assertEqual(ack['status'], 'marshalled')
            self.assertEqual(self.driver.tasks[ident]['state'], 4)
        self.assertEqual([c[0] for c in p.calls], ['activate', 'set_minimized', 'unset_minimized', 'close'])
        p.emit('closed')
        self.assertTrue(p.destroyed)
        self.assertEqual(self.drain()[0]['kind'], 'closed')
        self.driver.command(self.command(5, ident))
        self.assertEqual(self.drain()[0]['status'], 'stale')
        p2 = self.task()
        self.assertGreater(next(iter(self.driver.tasks)), ident)
    def test_bad_command_never_dispatches(self):
        self.driver.seat = Proxy(); self.driver.seat_keyboard = True
        p = self.task(); p.emit('done'); self.drain()
        for field, value in (('v', True), ('v', '1'), ('instance', 'bad'), ('command_id', 2), ('op', 'kill')):
            self.driver.command_id = 0
            cmd = self.command(); cmd[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.driver.command(cmd)
        self.assertEqual(p.calls, [])
    def test_callback_failure_is_not_silently_swallowed(self):
        p = self.task()
        p.emit('state', b'bad')
        with self.assertRaisesRegex(RuntimeError, 'state'):
            self.driver.check()
    def test_required_global_removal_and_name_version(self):
        with self.assertRaisesRegex(RuntimeError, 'version 4'):
            self.driver.bind_globals(self.display.registry, 1, 'wl_output', 3)
        self.driver.bind_globals(self.display.registry, 2, 'ext_workspace_manager_v1', 1)
        with self.assertRaisesRegex(RuntimeError, 'required global'):
            self.driver.remove_global(None, 2)
    def test_flush_eagain_and_failure(self):
        self.display.flushed = [-1, 0]
        self.assertTrue(self.driver.flush_wayland())
        self.assertFalse(self.driver.flush_wayland())
        self.display.flushed = [-1]; self.driver.get_errno = lambda: errno.EPIPE
        with self.assertRaises(OSError):
            self.driver.flush_wayland()
    def test_initialization_requires_coherent_snapshot_and_keyboard(self):
        def announce():
            reg = self.display.registry
            reg.emit('global', 1, 'wl_output', 4)
            reg.emit('global', 2, 'wl_seat', 9)
            reg.emit('global', 3, 'ext_workspace_manager_v1', 1)
            reg.emit('global', 4, 'zwlr_foreign_toplevel_manager_v1', 3)
            op = reg.bound[1][2]; op.emit('name','eDP-1'); op.emit('done')
            self.driver.seat.emit('capabilities', 2)
            wp = Proxy(); self.driver.workspace_manager.emit('workspace', wp)
            wp.emit('name','1'); wp.emit('state',1)
            self.driver.workspace_manager.emit('done')
        self.display.roundtrips = [announce]
        self.driver.initialize()
        kinds = [m['kind'] for m in self.drain()]
        self.assertEqual(kinds[0], 'hello')
        self.assertEqual(kinds[-2:], ['barrier', 'ready'])
    def test_loop_services_ipc_and_eof_without_blocking_wayland(self):
        wl_a, wl_b = socket.socketpair()
        self.addCleanup(wl_a.close); self.addCleanup(wl_b.close)
        self.display.get_fd = lambda: wl_a.fileno()
        self.display.dispatch = lambda block=False: None
        self.display.read = lambda: wl_a.recv(16)
        self.driver.initialize = lambda: None
        failures=[]
        def run():
            try: self.driver.run()
            except RuntimeError as exc: failures.append(str(exc))
        thread=threading.Thread(target=run, daemon=True); thread.start()
        self.b.sendall(wire.encode(self.command(1, 777)))
        wl_b.sendall(b'event')
        self.b.settimeout(3); buffer=bytearray(); messages=[]
        while not messages:
            buffer.extend(self.b.recv(65536)); messages=wire.take(buffer)
        self.assertEqual(messages[0]['status'],'stale')
        self.b.close(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures,['parent channel closed'])
    def test_protocol_string_bounds_keep_valid_utf8(self):
        self.assertEqual(bounded_string('a\U0001f600b',4),'a')
        self.assertEqual(bounded_string('a\U0001f600b',5),'a\U0001f600')
        with self.assertRaises(ValueError): bounded_string(12,20)


class FramingTests(unittest.TestCase):
    def test_strict_json_and_cross_language(self):
        good=[b'{"n":1,"s":"a"}',b'{"n":true}',b'{"s":"\\ud83d\\ude00"}']
        bad=[b'{} trailing',b'[]',b'{"a":1,"a":2}',b'{"a":1,"\\u0061":2}',
             b'{"a":1.0}',b'{"a":1e0}',b'{"a":NaN}',b'{"\\ud800":1}',b'{"a":"\\ud800"}',b'{"a":"\xff"}']
        for payload in good:
            wire.decode(payload)
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises((ValueError,UnicodeError)):
                wire.decode(payload)
        if not shutil.which('perl'): self.skipTest('Perl missing')
        script='use Labwc::WorkspaceBroker::Wire qw(decode_json); local $/; eval {decode_json(<STDIN>);1} or exit 9;'
        for payload in good+bad:
            result=subprocess.run(['perl','-I'+str(PERL),'-e',script],input=payload,capture_output=True,timeout=3)
            self.assertEqual(result.returncode==0,payload in good,payload)
    def test_fragmentation_limit_and_fairness(self):
        value={'s':'日本語','n':1}; packet=wire.encode(value); buffer=bytearray(); got=[]
        for byte in packet:
            buffer.append(byte); got.extend(wire.take(buffer))
        self.assertEqual(got,[value]); self.assertFalse(buffer)
        buffer=bytearray(packet*2)
        self.assertEqual(wire.take(buffer,1),[value]); self.assertEqual(bytes(buffer),packet)
        for n in (0,wire.MAX_FRAME+1,4294967295):
            with self.assertRaises(ValueError): wire.take(bytearray(struct.pack('!I',n)))
    def test_integer_and_depth(self):
        for value in (True,1.0,'1',None,-1,9):
            with self.subTest(value=value), self.assertRaises(ValueError): wire.integer(value,8)
        with self.assertRaises(ValueError): wire.decode(b'{"x":'+b'['*22+b'0'+b']'*22+b'}')


class IntegrationSourceTests(unittest.TestCase):
    def test_perl_actual_policy_suite(self):
        if not shutil.which('perl'): self.skipTest('Perl missing')
        result=subprocess.run(['perl','-I'+str(PERL),str(FORKY/'tests/workspace_broker.t')],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_python_sources_ast_without_bytecode(self):
        for path in (APP/'python').rglob('*.py'):
            ast.parse(path.read_text(),filename=str(path))
        ast.parse((TARGET/'usr/local/libexec/labwc-panel-run').read_text())
    def test_static_protocol_signatures_regenerate_exactly(self):
        result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/workspace_broker_protocols.py'),'--check'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        tree=ast.parse((APP/'python/labwc_workspace_wayland/protocol.py').read_text())
        classes={n.name:n for n in tree.body if isinstance(n,ast.ClassDef)}
        requests=[n.name for n in classes['ZwlrForeignToplevelHandleV1Proxy'].body if isinstance(n,ast.FunctionDef)]
        self.assertEqual(requests,['set_maximized','unset_maximized','set_minimized','unset_minimized','activate','close','set_rectangle','destroy','set_fullscreen','unset_fullscreen'])
        state=next(n for n in classes['ExtWorkspaceHandleV1Resource'].body if isinstance(n,ast.FunctionDef) and n.name=='state')
        self.assertIn('ArgumentType.Uint',ast.unparse(state.decorator_list[0]))
    def test_real_pywayland_bindings_when_installed(self):
        if importlib.util.find_spec('pywayland') is None:
            self.skipTest('Debian python3-pywayland not installed in this environment')
        from labwc_workspace_wayland.protocol import ExtWorkspaceHandleV1, ZwlrForeignToplevelHandleV1
        self.assertEqual(ExtWorkspaceHandleV1.name,'ext_workspace_handle_v1')
        self.assertEqual(ZwlrForeignToplevelHandleV1.version,3)
    def test_generated_slot_fragments_and_preserved_workspace_selector(self):
        for slots in (4,24,64):
            script='. "$1"; . "$2"; LABWC_WORKSPACE_BROKER_GROUP_SLOTS="$3"; desktop_waybar_workspace_modules_json'
            result=subprocess.run(['/bin/sh','-c',script,'test',str(FORKY/'scripts/desktop/detect.sh'),str(FORKY/'scripts/desktop/components.sh'),str(slots)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            obj=json.loads('{'+result.stdout+'}')
            self.assertEqual(len(obj['group/workspace-taskbar']['modules']),slots+1)
            for key,value in obj.items():
                if not key.startswith('custom/'): continue
                self.assertFalse(value['escape']); self.assertFalse(value['exec-on-event'])
                self.assertTrue(value['hide-empty-text']); self.assertNotIn('interval',value)
                self.assertIn('labwc-workspace-broker-client',value['exec'])
        config=(TARGET/'etc/skel-desktop/.config/waybar/config.tmpl').read_text()
        self.assertEqual(config.count('"ext/workspaces":'),2)
        self.assertEqual(config.count('__INSTALLER_LABWC_WORKSPACE_BROKER_MODULES__'),2)
        self.assertNotIn('"wlr/taskbar"',config)
        self.assertEqual(config.count('"group/apps":'),2)
    def test_lifecycle_no_native_alt_tab_helper(self):
        config=(TARGET/'etc/skel-desktop/.config/labwc/rc.xml.tmpl').read_text()
        self.assertEqual(config.count('<windowSwitcher '),1)
        self.assertNotIn('workspace="all"',config)
        for action in ('NextWindow','PreviousWindow'):
            self.assertRegex(config,fr'<action name="{action}" workspace="current"')
        units=TARGET/'etc/skel-desktop/.config/systemd/user'
        broker=(units/'labwc-workspace-broker.service').read_text()
        for text in ('Type=notify','NotifyAccess=main','KillMode=control-group','NoNewPrivileges=yes','PartOf=labwc-session.target'):
            self.assertIn(text,broker)
        for unit in ('waybar.service','labwc-session-restore.service'):
            text=(units/unit).read_text()
            self.assertRegex(text,r'(?m)^Wants=.*labwc-workspace-broker.service')
            self.assertRegex(text,r'(?m)^After=.*labwc-workspace-broker.service')
            self.assertNotRegex(text,r'(?m)^Requires=.*labwc-workspace-broker.service')
        self.assertIn('DefaultDependencies=no',(units/'labwc-session.target').read_text())

if __name__=='__main__': unittest.main()
