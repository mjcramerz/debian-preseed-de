#!/usr/bin/env python3
"""Native private D-Bus/GIO protocol checks; block operations use inert fixtures."""
from __future__ import annotations

import configparser
import os
from pathlib import Path
import runpy
import select
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from gi.repository import Gio, GLib

TARGET = Path(__file__).resolve().parents[1] / "hooks/target"
PROXY = runpy.run_path(str(TARGET / "usr/local/libexec/labwc-gvfs-volume-monitor"), run_name="fixture")


def inventory():
    drive = ("drive1", "USB", "", "", True, False, True, True, True, False, False, True,
             2, ["volume1"], {"unix-device": "/dev/sdb"}, "", {})
    volume = ("volume1", "Data", "", "", "uuid", "", True, False, "drive1", "mount1",
              {"unix-device": "/dev/sdb1"}, "", {})
    mount = ("mount1", "Data", "", "", "uuid", "file:///run/media/fixture/Data", True,
             "volume1", [], "", {})
    return ([drive], [volume], [mount])


class WiringTests(unittest.TestCase):
    def test_dbus_primary_and_transient_clients_share_the_native_monitor(self):
        path = 'etc/systemd/user/thunar.service.d/50-labwc-session.conf'
        unit = (TARGET / path).read_text(encoding='utf-8')
        for setting in ('Type=dbus', 'BusName=org.xfce.FileManager',
                        'ExecStart=/usr/bin/Thunar --daemon',
                        'Requires=labwc-gvfs-volume-monitor.service',
                        'PartOf=labwc-session.target', 'PrivateUsers=no', 'PrivateMounts=no',
                        'ConditionPathExists=!/run/user/%U/labwc-session-closing',
                        'KillMode=control-group', 'TimeoutStopSec=20s',
                        'LABWC_SESSION_APP=1',
                        'Restart=on-failure', 'GIO_USE_VOLUME_MONITOR=GProxyVolumeMonitorLabwc'):
            self.assertIn(setting, unit)
        assets = (TARGET.parents[1] / 'scripts/desktop/components/target-assets.sh').read_text(encoding='utf-8')
        self.assertIn(f'{path} /{path} 0644', assets)

    def test_native_registration_is_selected_only_for_thunar_and_all_assets_are_staged(self):
        registration = configparser.ConfigParser()
        registration.read(TARGET / 'usr/share/gvfs/remote-volume-monitors/labwc.monitor')
        values = registration['RemoteVolumeMonitor']
        self.assertEqual(values['Name'], 'GProxyVolumeMonitorLabwc')
        self.assertEqual(values['DBusName'], PROXY['NAME'])
        self.assertTrue(values.getboolean('IsNative'))
        self.assertLess(values.getint('NativePriority'), 4)
        assets = (TARGET.parents[1] / 'scripts/desktop/components/target-assets.sh').read_text(encoding='utf-8')
        for path, mode in (
                ('usr/local/libexec/labwc-gvfs-volume-monitor', '0755'),
                ('etc/systemd/user/labwc-gvfs-volume-monitor.service', '0644'),
                ('usr/share/dbus-1/services/org.gtk.vfs.LabwcVolumeMonitor.service', '0644'),
                ('usr/share/gvfs/remote-volume-monitors/labwc.monitor', '0644')):
            self.assertIn(f'{path} /{path} {mode}', assets)
        service = (TARGET / 'etc/systemd/user/labwc-gvfs-volume-monitor.service').read_text(encoding='utf-8')
        for setting in ('Type=dbus', 'BusName=' + PROXY['NAME'], 'NoNewPrivileges=yes',
                        'PrivateUsers=no', 'PrivateMounts=no',
                        'AppArmorProfile=labwc-external-drives', 'KillMode=mixed'):
            self.assertIn(setting, service)
        self.assertNotIn('CapabilityBoundingSet=', service)
        self.assertNotIn('ProtectSystem=', service)

    def test_fresh_ids_resolve_only_to_fixed_worker_argument_arrays(self):
        for method, identifier, operation, device in (
                ('MountUnmount', 'mount1', '--unmount-device', '/dev/sdb1'),
                ('DriveStop', 'drive1', '--power-off-device', '/dev/sdb'),
                ('DriveEject', 'drive1', '--power-off-device', '/dev/sdb')):
            self.assertEqual(PROXY['removal_command'](method, identifier, inventory()),
                             [PROXY['WORKER'], operation, device])
        for method, identifier in (('MountUnmount', 'stale'), ('DriveStop', 'stale'), ('VolumeMount', 'volume1')):
            with self.assertRaises(ValueError):
                PROXY['removal_command'](method, identifier, inventory())
        for device in ('/dev/../sdb', '/dev/mapper/crypt', '/dev/sdb;touch bad', '-sdb', '/dev/' + 'a' * 129):
            value = inventory()
            value[0][0][14]['unix-device'] = device
            with self.assertRaises(ValueError):
                PROXY['removal_command']('DriveStop', 'drive1', value)
        value = inventory()
        value[0].extend([value[0][0]] * 128)
        with self.assertRaises(ValueError):
            PROXY['removal_command']('DriveStop', 'drive1', value)


class ProtocolFixtureTests(unittest.TestCase):
    """Real GLib wire values and subprocess waits, with the bus boundary mocked."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='thunar-protocol-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trace = self.root / 'trace'
        self.hold = self.root / 'hold'
        self.status = self.root / 'status'
        self.status.write_text('0', encoding='utf-8')
        worker = self.root / 'worker'
        worker.write_text('#!/bin/sh\nset -eu\nprintf "%s\\n" "$@" >>' + shlex.quote(str(self.trace)) +
                          '\nwhile [ -e ' + shlex.quote(str(self.hold)) + ' ]; do sleep 0.02; done\n' +
                          'exit "$(cat ' + shlex.quote(str(self.status)) + ')"\n', encoding='utf-8')
        worker.chmod(0o700)
        self.patch = mock.patch.dict(PROXY['removal_command'].__globals__, WORKER=str(worker))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.connection = mock.Mock()
        self.connection.call_finish.side_effect = lambda value: value
        self.connection.call.side_effect = self.upstream_call
        self.monitor = PROXY['Monitor'].__new__(PROXY['Monitor'])
        self.monitor.connection = self.connection
        self.monitor.upstream = PROXY['UPSTREAM']
        self.monitor.address = 'unix:path=' + str(self.root / 'inert-bus')
        self.monitor.clients = {}
        self.monitor.pending = 0
        self.monitor.removal = None
        self.monitor.stopping = False
        self.monitor.failed = False
        self.monitor.loop = mock.Mock()
        self.monitor.connect = mock.Mock(side_effect=lambda: mock.Mock())
        self.delayed = []
        self.delay_list = False
        self.addCleanup(self.finish_worker)

    def finish_worker(self):
        self.hold.unlink(missing_ok=True)
        self.wait_for(lambda: self.monitor.removal is None)

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        context = GLib.MainContext.default()
        while not condition():
            if time.monotonic() >= deadline:
                self.fail('timed out waiting for the GLib subprocess fixture')
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)

    def upstream_call(self, _name, _path, _interface, method, _parameters,
                      _reply_type, _flags, _timeout, _cancellable, callback, data):
        if method != 'List':
            self.fail('unexpected removal bypass: ' + method)
        deliver = lambda: (callback(self.connection, GLib.Variant(PROXY['LIST_TYPE'], inventory()), data),
                           GLib.SOURCE_REMOVE)[1]
        if self.delay_list:
            self.delayed.append(deliver)
        else:
            GLib.idle_add(deliver)

    def request(self, method, values, *, sender=':1.10'):
        invocation = mock.Mock()
        parameters = GLib.Variant('(' + ''.join(PROXY['METHODS'][method][0]) + ')', values)
        self.monitor.method_call(self.connection, sender, PROXY['PATH'], PROXY['INTERFACE'],
                                 method, parameters, invocation)
        return invocation

    def completed(self, invocation):
        return invocation.return_value.called or invocation.return_gerror.called

    def test_all_native_removals_wait_for_a_real_worker_and_return_only_after_exit(self):
        for method, identifier, operation, device in (
                ('MountUnmount', 'mount1', '--unmount-device', '/dev/sdb1'),
                ('DriveStop', 'drive1', '--power-off-device', '/dev/sdb'),
                ('DriveEject', 'drive1', '--power-off-device', '/dev/sdb')):
            self.hold.touch()
            invocation = self.request(method, (identifier, 'cancel', 0, 'dialog'))
            self.wait_for(lambda: self.monitor.removal and self.monitor.removal.process is not None)
            self.assertFalse(self.completed(invocation))
            cancel = self.request('CancelOperation', ('cancel',))
            self.assertFalse(cancel.return_value.call_args.args[0].unpack()[0])
            busy = self.request('MountUnmount', ('mount1', 'other', 0, ''))
            self.assertEqual(busy.return_gerror.call_args.args[0].code, Gio.IOErrorEnum.BUSY)
            self.hold.unlink()
            self.wait_for(lambda: self.completed(invocation))
            self.assertEqual(invocation.return_value.call_args.args[0].unpack(), ())
            self.assertEqual(self.trace.read_text(encoding='utf-8').splitlines()[-2:], [operation, device])
        self.assertEqual([call.args[3] for call in self.connection.call.call_args_list], ['List'] * 3)

    def test_worker_failure_is_not_reported_as_success_or_retried_natively(self):
        self.status.write_text('7', encoding='utf-8')
        invocation = self.request('MountUnmount', ('mount1', 'cancel', 0, ''))
        self.wait_for(lambda: self.completed(invocation))
        invocation.return_value.assert_not_called()
        self.assertEqual(invocation.return_gerror.call_args.args[0].code, Gio.IOErrorEnum.FAILED)
        self.assertEqual(self.connection.call.call_count, 1)

    def test_forced_and_stale_ids_never_reach_a_worker(self):
        for identifier, flags in (('mount1', 1), ('stale', 0)):
            invocation = self.request('MountUnmount', (identifier, 'cancel', flags, ''))
            self.wait_for(lambda: self.completed(invocation))
            invocation.return_value.assert_not_called()
        self.assertFalse(self.trace.exists())

    def test_cancel_before_sync_starts_and_client_disappearance_are_safe(self):
        self.delay_list = True
        invocation = self.request('MountUnmount', ('mount1', 'cancel', 0, ''))
        cancel = self.request('CancelOperation', ('cancel',))
        self.assertTrue(cancel.return_value.call_args.args[0].unpack()[0])
        self.delayed.pop()()
        self.assertEqual(invocation.return_gerror.call_args.args[0].code, Gio.IOErrorEnum.CANCELLED)
        self.assertFalse(self.trace.exists())
        invocation = self.request('MountUnmount', ('mount1', 'cancel', 0, ''))
        self.monitor.owner_changed(None, None, None, None, None,
                                   GLib.Variant('(sss)', (':1.10', ':1.10', '')), None)
        self.delayed.pop()()
        self.assertEqual(invocation.return_gerror.call_args.args[0].code, Gio.IOErrorEnum.CANCELLED)

    def test_stop_waits_for_an_active_worker_instead_of_abandoning_the_removal(self):
        self.hold.touch()
        invocation = self.request('DriveStop', ('drive1', 'cancel', 0, ''))
        self.wait_for(lambda: self.monitor.removal and self.monitor.removal.process is not None)
        self.monitor.stop()
        self.monitor.loop.quit.assert_not_called()
        self.hold.unlink()
        self.wait_for(lambda: self.completed(invocation))
        self.monitor.loop.quit.assert_called_once()
        self.assertFalse(self.monitor.failed)

    def test_lost_upstream_ids_or_session_bus_trigger_service_recovery(self):
        self.monitor.owner_changed(None, None, None, None, None,
                                   GLib.Variant('(sss)', (PROXY['UPSTREAM'], ':1.20', ':1.21')), None)
        self.assertTrue(self.monitor.failed)
        self.assertTrue(self.monitor.stopping)
        self.monitor.loop.quit.assert_called_once()
        self.monitor.failed = False
        self.monitor.stopping = False
        self.monitor.loop.reset_mock()
        self.monitor.closed(self.connection, True, None)
        self.assertTrue(self.monitor.failed)
        self.monitor.loop.quit.assert_called_once()

    def test_dialogs_are_unicast_and_inventory_is_broadcast_once_with_the_correct_name(self):
        volume = GLib.Variant('(ss' + PROXY['VOLUME'] + ')', (PROXY['UPSTREAM'], 'volume1', inventory()[1][0]))
        self.monitor.relay_signal(None, None, None, None, 'VolumeChanged', volume, None)
        self.monitor.relay_signal(None, None, None, None, 'VolumeChanged', volume, ':1.10')
        question = GLib.Variant('(sssas)', (PROXY['UPSTREAM'], 'dialog', 'Fixture', ['OK']))
        self.monitor.relay_signal(None, None, None, None, 'MountOpAskQuestion', question, ':1.10')
        self.monitor.relay_signal(None, None, None, None, 'MountOpAskQuestion', question, None)
        self.assertEqual(self.connection.emit_signal.call_count, 2)
        broadcast, dialog = self.connection.emit_signal.call_args_list
        self.assertIsNone(broadcast.args[0])
        self.assertEqual(dialog.args[0], ':1.10')
        for call in (broadcast, dialog):
            self.assertEqual(call.args[4].unpack()[0], PROXY['NAME'])

    def test_per_client_upstream_connections_keep_mount_reply_ownership_separate(self):
        first = self.monitor.client(':1.10')
        self.assertIs(first, self.monitor.client(':1.10'))
        second = self.monitor.client(':1.11')
        self.assertIsNot(first, second)
        self.assertEqual(first.signal_subscribe.call_args.args[-1], ':1.10')
        self.assertEqual(second.signal_subscribe.call_args.args[-1], ':1.11')
        self.monitor.owner_changed(None, None, None, None, None,
                                   GLib.Variant('(sss)', (':1.10', ':1.10', '')), None)
        first.close.assert_called_once()
        self.assertEqual(list(self.monitor.clients), [':1.11'])

    def test_client_and_request_limits_are_enforced_before_forwarding(self):
        self.monitor.clients = {str(i): object() for i in range(PROXY['MAX_CLIENTS'])}
        with self.assertRaises(ValueError):
            self.monitor.client(':1.99')
        self.monitor.pending = PROXY['MAX_PENDING']
        invocation = self.request('MountUnmount', ('mount1', 'cancel', 0, ''))
        self.assertEqual(invocation.return_gerror.call_args.args[0].code, Gio.IOErrorEnum.BUSY)
        self.connection.call.assert_not_called()


@unittest.skipUnless(shutil.which('dbus-daemon'), 'native private session bus unavailable')
class PrivateBusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='thunar-native-gvfs-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.address = 'unix:path=' + str(self.root / 'bus')
        config = self.root / 'bus.conf'
        # No activation directories: nothing can launch a host service.
        config.write_text('<busconfig><type>session</type><auth>EXTERNAL</auth>'
                          '<listen>' + self.address + '</listen><policy context="default">'
                          '<allow user="*"/><allow own="*"/><allow send_destination="*"/>'
                          '<allow receive_sender="*"/></policy></busconfig>', encoding='utf-8')
        self.daemon = subprocess.Popen([
            shutil.which('dbus-daemon'), '--nofork', '--nopidfile', '--print-address=1',
            '--config-file=' + str(config)], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.stop_daemon)
        self.assertTrue(select.select([self.daemon.stdout], [], [], 5)[0], 'private bus startup timeout')
        self.assertTrue(self.daemon.stdout.readline().startswith(self.address))
        # A bounded EXTERNAL handshake confirms readiness before GDBus calls.
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(5)
                probe.connect(str(self.root / 'bus'))
                probe.sendall(b'\0AUTH EXTERNAL ' + str(os.getuid()).encode().hex().encode() + b'\r\n')
                self.assertTrue(probe.recv(128).startswith(b'OK '))
        except OSError as error:
            self.daemon.terminate()
            _output, diagnostic = self.daemon.communicate(timeout=3)
            self.fail(f'private broker handshake failed: {error}; {diagnostic[:4096]}')
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_loop)
        self.wait_for(self.loop.is_running)
        self.connections = []
        self.addCleanup(self.close_connections)
        self.calls = []
        self.mounts = {}
        self.delay_list = False
        self.delayed = []
        try:
            self.backend = self.connect()
        except GLib.Error as error:
            if 'Failed to query AppArmor policy: Read-only file system' in str(error):
                self.skipTest('this environment prevents the native private bus from querying AppArmor policy')
            raise
        self.backend.register_object(PROXY['PATH'], PROXY['interface_info'](), self.backend_call, None, None)
        reply = self.backend.call_sync(
            'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'RequestName',
            GLib.Variant('(su)', (PROXY['UPSTREAM'], 4)), GLib.VariantType.new('(u)'),
            Gio.DBusCallFlags.NONE, 2000, None)
        self.assertEqual(reply.unpack(), (1,))
        self.trace = self.root / 'trace'
        self.hold = self.root / 'hold'
        self.status = self.root / 'status'
        self.status.write_text('0', encoding='utf-8')
        worker = self.root / 'worker'
        worker.write_text('#!/bin/sh\nset -eu\nprintf "%s\\n" "$@" >>' + shlex.quote(str(self.trace)) +
                          '\nwhile [ -e ' + shlex.quote(str(self.hold)) + ' ]; do sleep 0.02; done\n' +
                          'exit "$(cat ' + shlex.quote(str(self.status)) + ')"\n', encoding='utf-8')
        worker.chmod(0o700)
        globals_ = PROXY['removal_command'].__globals__
        original = globals_['WORKER']
        globals_['WORKER'] = str(worker)
        self.addCleanup(globals_.__setitem__, 'WORKER', original)
        self.monitor = PROXY['Monitor'](self.address)
        self.monitor.acquire()
        self.addCleanup(self.close_monitor)
        self.client = self.connect()

    def stop_daemon(self):
        self.daemon.terminate()
        try:
            self.daemon.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            self.daemon.kill()
            self.daemon.communicate(timeout=3)

    def stop_loop(self):
        self.loop.quit()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())

    def close_connections(self):
        for connection in self.connections:
            if not connection.is_closed():
                connection.close_sync(None)

    def close_monitor(self):
        self.hold.unlink(missing_ok=True)
        self.wait_for(lambda: self.monitor.removal is None)
        self.monitor.close()

    def connect(self):
        result = Gio.DBusConnection.new_for_address_sync(
            self.address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
            Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        result.set_exit_on_close(False)
        self.connections.append(result)
        return result

    def wait_for(self, condition):
        deadline = time.monotonic() + 4
        while not condition():
            if time.monotonic() >= deadline:
                self.fail('timed out waiting for the private protocol fixture')
            time.sleep(0.01)

    def call(self, method, parameters=None, *, client=None):
        return (client or self.client).call_sync(
            PROXY['NAME'], PROXY['PATH'], PROXY['INTERFACE'], method, parameters,
            GLib.VariantType.new('(' + ''.join(PROXY['METHODS'][method][1]) + ')'),
            Gio.DBusCallFlags.NONE, 3000, None)

    def call_async(self, method, parameters, *, client=None):
        results = []
        def done(connection, result, _data):
            try:
                results.append(connection.call_finish(result))
            except GLib.Error as error:
                results.append(error)
        (client or self.client).call(
            PROXY['NAME'], PROXY['PATH'], PROXY['INTERFACE'], method, parameters,
            None, Gio.DBusCallFlags.NONE, 4000, None, done, None)
        return results

    def backend_call(self, _connection, sender, _path, _interface, method, parameters, invocation):
        self.calls.append((sender, method, parameters.unpack()))
        if method == 'IsSupported':
            invocation.return_value(GLib.Variant('(b)', (True,)))
        elif method == 'List':
            if self.delay_list:
                self.delayed.append(invocation)
            else:
                invocation.return_value(GLib.Variant(PROXY['LIST_TYPE'], inventory()))
        elif method == 'CancelOperation':
            invocation.return_value(GLib.Variant('(b)', (False,)))
        elif method == 'VolumeMount':
            mount_op_id = parameters.unpack()[3]
            self.mounts[(sender, mount_op_id)] = invocation
            self.backend.emit_signal(sender, PROXY['PATH'], PROXY['INTERFACE'], 'MountOpAskQuestion',
                GLib.Variant('(sssas)', (PROXY['UPSTREAM'], mount_op_id, 'Fixture question', ['OK'])))
        elif method in ('MountOpReply', 'MountOpReply2'):
            mounted = self.mounts.pop((sender, parameters.unpack()[0]))
            mounted.return_value(GLib.Variant('()', ()))
            invocation.return_value(GLib.Variant('()', ()))
        else:
            PROXY['failure'](invocation, Gio.IOErrorEnum.NOT_SUPPORTED, 'unexpected removal bypass')

    def test_unmount_eject_and_stop_wait_for_worker_and_never_call_native_removal(self):
        for method, identifier, operation, device in (
                ('MountUnmount', 'mount1', '--unmount-device', '/dev/sdb1'),
                ('DriveEject', 'drive1', '--power-off-device', '/dev/sdb'),
                ('DriveStop', 'drive1', '--power-off-device', '/dev/sdb')):
            self.hold.touch()
            results = self.call_async(method, GLib.Variant('(ssus)', (identifier, 'cancel', 0, '')))
            self.wait_for(lambda: self.monitor.removal and self.monitor.removal.process is not None)
            self.assertEqual(results, [])
            self.assertFalse(self.call('CancelOperation', GLib.Variant('(s)', ('cancel',))).unpack()[0])
            with self.assertRaises(GLib.Error):
                self.call('MountUnmount', GLib.Variant('(ssus)', ('mount1', 'other', 0, '')))
            self.hold.unlink()
            self.wait_for(lambda: bool(results))
            self.assertIsInstance(results[0], GLib.Variant)
            self.assertEqual(results[0].unpack(), ())
            self.assertEqual(self.trace.read_text(encoding='utf-8').splitlines()[-2:], [operation, device])
        self.assertFalse(any(method in PROXY['REMOVALS'] for _sender, method, _params in self.calls))

    def test_sync_or_unmount_failure_returns_an_error_to_thunar(self):
        self.status.write_text('7', encoding='utf-8')
        with self.assertRaises(GLib.Error) as error:
            self.call('MountUnmount', GLib.Variant('(ssus)', ('mount1', 'cancel', 0, '')))
        self.assertIn('sync/removal failed', str(error.exception))
        self.assertIsNone(self.monitor.removal)
        self.assertFalse(any(method in PROXY['REMOVALS'] for _sender, method, _params in self.calls))

    def test_forced_or_stale_removal_never_starts_a_worker(self):
        for identifier, flags in (('mount1', 1), ('stale', 0)):
            with self.assertRaises(GLib.Error):
                self.call('MountUnmount', GLib.Variant('(ssus)', (identifier, 'cancel', flags, '')))
        self.assertFalse(self.trace.exists())

    def test_cancellation_before_writes_prevents_the_worker_from_starting(self):
        self.delay_list = True
        results = self.call_async('MountUnmount', GLib.Variant('(ssus)', ('mount1', 'cancel', 0, '')))
        self.wait_for(lambda: bool(self.delayed))
        self.assertTrue(self.call('CancelOperation', GLib.Variant('(s)', ('cancel',))).unpack()[0])
        self.wait_for(lambda: bool(results))
        self.assertIsInstance(results[0], GLib.Error)
        self.assertFalse(self.trace.exists())
        self.delay_list = False
        self.delayed.pop().return_value(GLib.Variant(PROXY['LIST_TYPE'], inventory()))

    def test_mount_dialogs_and_replies_preserve_each_clients_upstream_identity(self):
        other = self.connect()
        dialogs = [[], []]
        for connection, received in ((self.client, dialogs[0]), (other, dialogs[1])):
            connection.signal_subscribe(PROXY['NAME'], PROXY['INTERFACE'], 'MountOpAskQuestion',
                PROXY['PATH'], None, Gio.DBusSignalFlags.NONE,
                lambda _c, _s, _p, _i, _n, params, dest: dest.append(params.unpack()), received)
            self.call('List', client=connection)  # Ensure the match rule precedes the mount request.
        results = []
        for connection, mount_op in ((self.client, 'same-op'), (other, 'same-op')):
            results.append(self.call_async('VolumeMount', GLib.Variant('(ssus)',
                           ('volume1', 'cancel', 0, mount_op)), client=connection))
        self.wait_for(lambda: all(dialogs))
        self.assertEqual([len(d) for d in dialogs], [1, 1])
        self.assertTrue(all(d[0][0] == PROXY['NAME'] for d in dialogs))
        upstream_senders = [sender for sender, method, _p in self.calls if method == 'VolumeMount']
        self.assertEqual(len(set(upstream_senders)), 2)
        for connection in (self.client, other):
            self.call('MountOpReply2', GLib.Variant('(sisssiiba{sv})',
                      ('same-op', 0, '', '', '', 0, 0, False, {})), client=connection)
        self.wait_for(lambda: all(results))
        self.assertTrue(all(isinstance(result[0], GLib.Variant) for result in results))
        other.close_sync(None)
        self.wait_for(lambda: len(self.monitor.clients) == 1)

    def test_inventory_signals_are_rewritten_once_for_the_managed_monitor(self):
        received = []
        self.client.signal_subscribe(PROXY['NAME'], PROXY['INTERFACE'], 'VolumeChanged',
            PROXY['PATH'], None, Gio.DBusSignalFlags.NONE,
            lambda _c, _s, _p, _i, _n, parameters, _d: received.append(parameters.unpack()), None)
        self.call('CancelOperation', GLib.Variant('(s)', ('none',)))  # Create a per-client upstream connection.
        self.call('List')
        self.backend.emit_signal(None, PROXY['PATH'], PROXY['INTERFACE'], 'VolumeChanged',
            GLib.Variant('(ss' + PROXY['VOLUME'] + ')', (PROXY['UPSTREAM'], 'volume1', inventory()[1][0])))
        self.wait_for(lambda: bool(received))
        self.call('List')
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0:2], (PROXY['NAME'], 'volume1'))


if __name__ == '__main__':
    unittest.main()
