"""Kernel-identity policy and the asynchronous portal protocol state machine."""
from __future__ import annotations

import heapq
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

from payload_fixture import python_library
TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
sys.path.insert(0, str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')))
from labwc_managed_app import compat_gpu as gpu, compat_portal as portal
from labwc_managed_app.compat_protocol import ProtocolError


class GPUIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.dev, self.sys, self.proc = [self.root / n for n in ('dev','sys','proc')]
        (self.dev/'dri').mkdir(parents=True)
        (self.sys/'class/drm').mkdir(parents=True)
        self.identities = {}
        self.original_lstat = Path.lstat

    def tearDown(self):
        self.directory.cleanup()

    def render(self, number, vendor, driver):
        node = self.dev/'dri'/f'renderD{number}'
        node.write_text('inert fixture'); node.chmod(0o660)
        self.identities[node] = (226, number)
        device = self.sys/'devices'/f'0000:0{number-128}:00.0'
        entry = device/'drm'/node.name
        entry.mkdir(parents=True)
        (entry/'dev').write_text(f'226:{number}\n')
        (device/'vendor').write_text(vendor+'\n')
        bound = self.sys/'bus/pci/drivers'/driver
        bound.mkdir(parents=True, exist_ok=True)
        (device/'driver').symlink_to(bound, target_is_directory=True)
        (entry/'device').symlink_to(device, target_is_directory=True)
        (self.sys/'class/drm'/node.name).symlink_to(entry, target_is_directory=True)
        return node, device

    def metadata(self, path, **kwargs):
        raw = self.original_lstat(path, **kwargs)
        values = {name: getattr(raw,name) for name in dir(raw) if name.startswith('st_')}
        values['st_uid'] = 0  # Fixture attributes stand in for kernel-owned sysfs.
        if path in self.identities and not stat.S_ISLNK(raw.st_mode):
            values['st_mode'] = stat.S_IFCHR | stat.S_IMODE(raw.st_mode)
            values['st_rdev'] = os.makedev(*self.identities[path])
        return types.SimpleNamespace(**values)

    def select(self, mode):
        result = []
        with mock.patch.object(Path, 'lstat', lambda path, **kw: self.metadata(path, **kw)):
            selected = gpu.add_device_binds(result, mode, dev_root=self.dev, sys_root=self.sys, proc_root=self.proc)
        return selected, result

    def test_intel_binds_only_selected_render_identity_even_with_nvidia_present(self):
        self.render(129, '0x8086', 'xe')
        self.render(128, '0x10de', 'nvidia')
        selected, argv = self.select('intel')
        self.assertEqual(selected, 'intel')
        self.assertEqual(argv, ['--dir','/dev/dri','--dev-bind',str(self.dev/'dri/renderD129'),'/dev/dri/renderD129'])
        self.assertFalse(any(x in ' '.join(argv) for x in ('nvidiactl','nvidia0','kfd','accel','card0','controlD')))
        self.assertEqual(self.select('launch'), (selected, argv))

    def test_default_udev_render_mode_is_accepted_but_executable_device_is_rejected(self):
        node,_ = self.render(128,'0x8086','i915')
        node.chmod(0o666)
        self.assertEqual(self.select('intel')[0],'intel')
        node.chmod(0o766)
        with self.assertRaises(ProtocolError): self.select('intel')

    def test_nvidia_binds_only_matching_graphics_control_devices(self):
        _, device = self.render(128, '0x10de', 'nvidia')
        self.render(129, '0x8086', 'i915')
        information = self.proc/'driver/nvidia/gpus'/device.name/'information'
        information.parent.mkdir(parents=True); information.write_text('Device Minor: 2\n')
        for name, minor in (('nvidiactl',255),('nvidia2',2),('nvidia0',0)):
            path = self.dev/name; path.write_text('inert'); self.identities[path] = (195,minor)
        selected, argv = self.select('nvidia')
        self.assertEqual(selected, 'nvidia')
        self.assertIn('/dev/nvidiactl', argv); self.assertIn('/dev/nvidia2', argv)
        self.assertNotIn('/dev/nvidia0', argv); self.assertNotIn('/dev/dri/renderD129', argv)

    def test_rejects_symlink_vendor_driver_mismatch_and_major_minor_disagreement(self):
        node, device = self.render(128, '0x8086', 'i915')
        (device/'vendor').write_text('0x10de\n')
        with self.assertRaises(ProtocolError): self.select('intel')
        (device/'vendor').write_text('0x8086\n')
        self.identities[node] = (195,128)
        with self.assertRaises(ProtocolError): self.select('intel')
        self.identities[node] = (226,129)
        with self.assertRaises(ProtocolError): self.select('intel')
        node.unlink(); node.symlink_to('/dev/null')
        with self.assertRaises(ProtocolError): self.select('intel')

    def test_ambiguous_device_or_untrusted_mode_fails_without_software_fallback(self):
        self.render(128,'0x8086','i915'); self.render(129,'0x8086','xe')
        with self.assertRaises(ProtocolError): self.select('intel')
        with self.assertRaises(ProtocolError): self.select('--disable-gpu')

    def test_compatibility_device_scope_does_not_replace_native_mount_helper(self):
        text = (TARGET/'usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py').read_text()
        self.assertIn('if private_xwayland_binary is not None:',text)
        self.assertIn('compat_gpu.add_device_binds(command, mode)', text)
        self.assertIn('else:\n            add_gpu_device_binds(command, mode)',text)


class PortalHarness:
    """Deterministic GLib/Gio protocol fixture; no claimed target portal proof."""
    class Error(Exception): pass
    class Variant:
        def __init__(self, signature, value): self.value = value
        def unpack(self): return self.value

    def __init__(self, scenario):
        self.scenario = scenario
        self.clock = 0; self.next_id = 1; self.pending = {}; self.queue = []
        self.calls = []; self.matches = {}; self.closed = None; self.done = False
        harness = self
        class Loop:
            def run(self):
                harness.done = False  # GLib.run resets a quit made before run.
                for _ in range(20000):
                    if harness.done: return
                    when, source = heapq.heappop(harness.queue)
                    entry = harness.pending.pop(source, None)
                    if entry is None: continue
                    interval, callback = entry; harness.clock = when
                    if callback():
                        harness.pending[source] = entry
                        heapq.heappush(harness.queue,(when+interval,source))
                raise AssertionError('portal loop did not terminate')
            def quit(self): harness.done = True
        class Cancellable:
            def cancel(self): harness.calls.append('cancel')
        class Bus:
            def set_exit_on_close(self, value): pass
            def connect(self, name, callback): harness.closed = callback
            def get_unique_name(self): return ':1.23'
            def signal_subscribe(self, sender, interface, member, path, arg0, flags, callback, data):
                source = len(harness.matches)+1
                harness.matches[source] = (interface,member,path,callback)
                harness.calls.append(('subscribe',member))
                return source
            def call_sync(self, name, path, interface, method, parameters, reply, flags, timeout, cancellable):
                harness.calls.append((method, timeout)); return harness.Variant('(s)',('bus-id',))
            def call(self, name, path, interface, method, parameters, reply, flags, timeout, cancellable, callback, data):
                harness.calls.append((method, timeout))
                assert harness.matches[1][1] == 'Response'
                harness.parameters = parameters.unpack()
                handle = harness.matches[1][2]
                harness.handle = handle
                def respond(code):
                    harness.matches[1][3](self,':1.9',handle,portal.REQUEST,'Response',harness.Variant('(ua{sv})',(code,{})),None)
                if scenario in ('fast-success','cancel','backend-response'):
                    respond({'fast-success':0,'cancel':1,'backend-response':2}[scenario])
                if scenario == 'bus-loss':
                    harness.schedule(2, lambda: harness.closed(self,None,None))
                if scenario == 'stop':
                    harness.schedule(2, lambda: os.kill(os.getpid(),15))
                harness.schedule(1, lambda: callback(self,None,None))
            def call_finish(self, result):
                if scenario in ('backend-error','method-timeout'):
                    raise harness.Error('TEST_SECRET must never be logged')
                return harness.Variant('(o)',(harness.handle if scenario != 'wrong-handle' else '/unexpected',))
            def signal_unsubscribe(self, source): harness.matches.pop(source,None)
            def close_sync(self, cancellable): harness.calls.append('closed')
        self.bus = Bus()
        class Connection:
            @staticmethod
            def new_for_address(address, flags, observer, cancellable, callback, data):
                if scenario == 'stop-before-loop':
                    os.kill(os.getpid(),15)
                harness.schedule(1, lambda: callback(None,None,None))
            @staticmethod
            def new_for_address_finish(result): return harness.bus
        flags = types.SimpleNamespace(NONE=0)
        self.Gio = types.SimpleNamespace(Cancellable=Cancellable, DBusConnection=Connection,
            DBusSignalFlags=flags, DBusCallFlags=flags,
            DBusConnectionFlags=types.SimpleNamespace(AUTHENTICATION_CLIENT=1,MESSAGE_BUS_CONNECTION=2))
        self.GLib = types.SimpleNamespace(MainLoop=Loop, Error=self.Error, Variant=self.Variant,
            VariantType=types.SimpleNamespace(new=lambda value:value), timeout_add=self.schedule,
            source_remove=lambda source:self.pending.pop(source,None),
            MainContext=types.SimpleNamespace(default=lambda:types.SimpleNamespace(find_source_by_id=lambda source:self.pending.get(source))))

    def schedule(self, milliseconds, callback):
        source = self.next_id; self.next_id += 1
        self.pending[source] = (milliseconds,callback)
        heapq.heappush(self.queue,(self.clock+milliseconds,source))
        return source

    def run(self):
        gi = types.ModuleType('gi'); gi.require_version = lambda *args:None
        repository = types.ModuleType('gi.repository'); repository.Gio=self.Gio; repository.GLib=self.GLib
        with mock.patch.dict(sys.modules,{'gi':gi,'gi.repository':repository}), \
             mock.patch.object(portal.sys,'stderr',io.StringIO()) as output:
            result = portal.open_uri('https://discord.com/handoff?key=TEST_SECRET','unix:path=/filtered')
        if 'TEST_SECRET' in output.getvalue(): raise AssertionError('secret entered diagnostics')
        return result


class PortalLifecycleTests(unittest.TestCase):
    def test_stop_before_main_loop_does_not_issue_uri_or_restart_the_loop(self):
        h=PortalHarness('stop-before-loop')
        self.assertEqual(h.run(),143)
        self.assertEqual(h.clock,0)
        self.assertFalse(any(isinstance(call,tuple) and call[0]=='OpenURI' for call in h.calls))

    def test_fast_response_is_subscribed_before_method_and_does_not_race(self):
        h = PortalHarness('fast-success'); self.assertEqual(h.run(),0)
        self.assertLess(h.calls.index(('subscribe','Response')),h.calls.index(('OpenURI',5000)))
        self.assertEqual(h.parameters[0],'')
        self.assertEqual(h.parameters[1],'https://discord.com/handoff?key=TEST_SECRET')
        self.assertEqual(h.matches,{})

    def test_cancel_backend_failure_bus_loss_and_managed_stop_are_distinct(self):
        for scenario, expected in (('cancel',1),('backend-response',2),('backend-error',2),('bus-loss',2),('stop',143),('wrong-handle',2),('method-timeout',2)):
            with self.subTest(scenario=scenario):
                h=PortalHarness(scenario); self.assertEqual(h.run(),expected)
                self.assertLess(h.clock,15000)
                if expected not in (0,1): self.assertIn(('Close',500),h.calls)

    def test_user_response_has_its_own_lifetime_after_method_reply(self):
        h=PortalHarness('no-response'); self.assertEqual(h.run(),3)
        self.assertGreaterEqual(h.clock,120000)
        self.assertLess(h.clock,120010)
        self.assertIn(('Close',500),h.calls)


if __name__ == '__main__': unittest.main()
