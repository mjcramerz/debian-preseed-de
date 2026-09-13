"""Wayland transport only: proxy ownership, protocol atoms, fences, requests.

No workspace learning, application aliases, grouping, badges, slots, picker
state, UI decisions or public control socket belong in this process.
"""
from __future__ import annotations
import errno
import os
from pathlib import Path
import re
import selectors
import signal
import socket
import stat
import struct
import sys
import time
import uuid
from typing import Any, Callable
from . import wire


def bounded_string(value: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError('protocol string type')
    return value.encode('utf-8', 'strict')[:limit].decode('utf-8', 'ignore')


class Driver:
    def __init__(self, display: Any, channel: socket.socket, interfaces: dict[str, Any], get_errno: Callable[[], int]):
        self.display, self.channel = display, channel
        self.interfaces, self.get_errno = interfaces, get_errno
        self.instance = uuid.uuid4().hex
        self.sequence = self.next_id = self.command_id = 0
        self.outgoing, self.incoming = bytearray(), bytearray()
        self.registry = self.seat = self.workspace_manager = self.toplevel_manager = None
        self.seat_keyboard = False
        self.globals: dict[int, tuple[str, int]] = {}
        self.outputs: dict[int, dict[str, Any]] = {}
        self.output_proxies: dict[Any, int] = {}
        self.retired_outputs: dict[int, Any] = {}
        self.workspaces: dict[int, dict[str, Any]] = {}
        self.workspace_proxies: dict[Any, int] = {}
        self.groups: dict[int, dict[str, Any]] = {}
        self.tasks: dict[int, dict[str, Any]] = {}
        self.workspace_done = self.workspace_dirty = False
        self.pending = False
        self.change_counter = 0
        self.fence = None
        self.batch_started = 0.0
        self.failure: str | None = None
        self.stopping = False
        self.last_heartbeat = time.monotonic()

    def allocate(self) -> int:
        self.next_id += 1
        if self.next_id > 2147483647:
            raise RuntimeError('adapter identity exhausted')
        return self.next_id

    def say(self, kind: str, **data: Any) -> None:
        self.sequence += 1
        if self.sequence >= 9007199254740000:
            raise RuntimeError('adapter sequence exhausted')
        self.outgoing.extend(wire.encode(dict(v=1, kind=kind, instance=self.instance, seq=self.sequence, **data)))
        if len(self.outgoing) > wire.MAX_QUEUE:
            raise RuntimeError('adapter output backpressure')

    def atom(self, kind: str, **data: Any) -> None:
        self.say(kind, **data)
        self.change_counter += 1
        if not self.pending:
            self.batch_started = time.monotonic()
        self.pending = True

    def callback(self, proxy: Any, event: str, handler: Callable[..., Any]) -> None:
        # PyWayland's C callback dispatcher catches Python exceptions. Preserve
        # failure explicitly so a bad callback cannot leave a half-live driver.
        def guarded(*args: Any) -> None:
            if self.failure:
                return
            try:
                handler(*args)
            except Exception as exc:
                self.failure = f'{event}: {type(exc).__name__}'
        proxy.dispatcher[event] = guarded

    def check(self) -> None:
        if self.failure:
            raise RuntimeError(self.failure)

    @staticmethod
    def finished(*_: Any) -> None:
        raise RuntimeError('required protocol manager finished')

    def bind_globals(self, registry: Any, name: int, interface: str, version: int) -> None:
        if interface == 'wl_output':
            if version < 4:
                raise RuntimeError('wl_output version 4 names are required')
            if len(self.outputs) >= 64:
                raise RuntimeError('output limit')
            proxy = registry.bind(name, self.interfaces[interface], 4)
            ident = self.allocate()
            row = dict(id=ident, proxy=proxy, name='', ready=False, dirty=True)
            self.outputs[ident] = row
            self.output_proxies[proxy] = ident
            self.globals[name] = ('output', ident)
            def set_name(_: Any, value: str) -> None:
                row['name'] = bounded_string(value, 128)
                row['dirty'] = True
            def done(_: Any) -> None:
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', row['name']):
                    raise ValueError('invalid output name')
                row.update(ready=True, dirty=False)
                self.publish_outputs()
            self.callback(proxy, 'name', set_name)
            self.callback(proxy, 'done', done)
            for event in ('geometry', 'mode', 'scale', 'description'):
                self.callback(proxy, event, lambda *_: None)
        elif interface == 'wl_seat' and self.seat is None:
            self.seat = registry.bind(name, self.interfaces[interface], min(version, 2))
            self.globals[name] = ('required', 0)
            def capabilities(_: Any, bits: int) -> None:
                self.seat_keyboard = bool(bits & 2)
            self.callback(self.seat, 'capabilities', capabilities)
            if version >= 2:
                self.callback(self.seat, 'name', lambda *_: None)
        elif interface == 'ext_workspace_manager_v1':
            if self.workspace_manager is not None:
                raise RuntimeError('multiple workspace managers')
            self.workspace_manager = registry.bind(name, self.interfaces[interface], 1)
            self.globals[name] = ('required', 0)
            self.callback(self.workspace_manager, 'workspace', self.new_workspace)
            self.callback(self.workspace_manager, 'workspace_group', self.new_group)
            self.callback(self.workspace_manager, 'done', self.publish_workspaces)
            self.callback(self.workspace_manager, 'finished', self.finished)
        elif interface == 'zwlr_foreign_toplevel_manager_v1':
            if self.toplevel_manager is not None:
                raise RuntimeError('multiple toplevel managers')
            self.toplevel_manager = registry.bind(name, self.interfaces[interface], min(version, 3))
            self.globals[name] = ('required', 0)
            self.callback(self.toplevel_manager, 'toplevel', self.new_task)
            self.callback(self.toplevel_manager, 'finished', self.finished)

    def remove_global(self, _: Any, name: int) -> None:
        found = self.globals.pop(name, None)
        if found is None:
            return
        kind, ident = found
        if kind == 'required':
            raise RuntimeError('required global removed')
        row = self.outputs.pop(ident)
        # Keep the proxy alive through the next synchronization fence: already
        # queued foreign/group output_leave events can still reference it.
        if len(self.retired_outputs) >= 64:
            raise RuntimeError('retired output limit')
        self.retired_outputs[ident] = row['proxy']
        self.publish_outputs()

    def release_retired_outputs(self) -> None:
        for proxy in self.retired_outputs.values():
            self.output_proxies.pop(proxy, None)
            proxy.release()
        self.retired_outputs.clear()

    def publish_outputs(self) -> None:
        self.atom('outputs', outputs=[dict(id=r['id'], name=r['name'])
                                     for _, r in sorted(self.outputs.items()) if r['ready']])

    def output_id(self, proxy: Any) -> int:
        if proxy not in self.output_proxies:
            raise RuntimeError('unknown output proxy')
        return self.output_proxies[proxy]

    def new_group(self, _: Any, proxy: Any) -> None:
        if len(self.groups) >= 64:
            raise RuntimeError('workspace group limit')
        ident = self.allocate()
        row = dict(id=ident, proxy=proxy, outputs=set(), workspaces=set())
        self.groups[ident] = row
        self.workspace_dirty = True
        def output(enter: bool, _p: Any, obj: Any) -> None:
            value = self.output_id(obj)
            (row['outputs'].add if enter else row['outputs'].discard)(value)
            self.workspace_dirty = True
        def workspace(enter: bool, _p: Any, obj: Any) -> None:
            if obj not in self.workspace_proxies:
                raise RuntimeError('unknown workspace proxy')
            value = self.workspace_proxies[obj]
            (row['workspaces'].add if enter else row['workspaces'].discard)(value)
            self.workspace_dirty = True
        def removed(_p: Any) -> None:
            del self.groups[ident]
            self.workspace_dirty = True
            proxy.destroy()
        self.callback(proxy, 'capabilities', lambda *_: None)
        self.callback(proxy, 'output_enter', lambda *args: output(True, *args))
        self.callback(proxy, 'output_leave', lambda *args: output(False, *args))
        self.callback(proxy, 'workspace_enter', lambda *args: workspace(True, *args))
        self.callback(proxy, 'workspace_leave', lambda *args: workspace(False, *args))
        self.callback(proxy, 'removed', removed)

    def new_workspace(self, _: Any, proxy: Any) -> None:
        if len(self.workspaces) >= 64:
            raise RuntimeError('workspace limit')
        ident = self.allocate()
        row = dict(id=ident, proxy=proxy, name='', stable_id='', state=0)
        self.workspaces[ident] = row
        self.workspace_proxies[proxy] = ident
        self.workspace_dirty = True
        def value(field: str, _p: Any, data: Any) -> None:
            row[field] = wire.integer(data, 7) if field == 'state' else bounded_string(data, 256)
            self.workspace_dirty = True
        def removed(_p: Any) -> None:
            del self.workspaces[ident]
            del self.workspace_proxies[proxy]
            for group in self.groups.values():
                group['workspaces'].discard(ident)
            self.workspace_dirty = True
            proxy.destroy()
        self.callback(proxy, 'id', lambda *args: value('stable_id', *args))
        self.callback(proxy, 'name', lambda *args: value('name', *args))
        self.callback(proxy, 'state', lambda *args: value('state', *args))
        self.callback(proxy, 'coordinates', lambda *_: None)
        self.callback(proxy, 'capabilities', lambda *_: None)
        self.callback(proxy, 'removed', removed)

    def publish_workspaces(self, *_: Any) -> None:
        self.atom('workspaces',
                  workspaces=[{k: r[k] for k in ('id', 'name', 'stable_id', 'state')}
                              for _, r in sorted(self.workspaces.items())],
                  groups=[dict(id=r['id'], outputs=sorted(r['outputs']), workspaces=sorted(r['workspaces']))
                          for _, r in sorted(self.groups.items())])
        self.workspace_done, self.workspace_dirty = True, False

    def new_task(self, _: Any, proxy: Any) -> None:
        if len(self.tasks) >= 1024:
            raise RuntimeError('toplevel limit')
        ident = self.allocate()
        row = dict(id=ident, proxy=proxy, title='', app_id='', state=0, outputs=set(),
                   observed_state=0, revision=0, dirty=True)
        self.tasks[ident] = row
        self.atom('new', id=ident)
        def value(field: str, _p: Any, data: str) -> None:
            row[field] = bounded_string(data, 4096 if field == 'title' else 1024)
            row['dirty'] = True
        def output(enter: bool, _p: Any, obj: Any) -> None:
            value = self.output_id(obj)
            (row['outputs'].add if enter else row['outputs'].discard)(value)
            row['dirty'] = True
        def state(_p: Any, data: bytes) -> None:
            if len(data) % 4 or len(data) > 16:
                raise ValueError('foreign state array')
            values = struct.unpack(f'={len(data) // 4}I', data)
            if len(set(values)) != len(values) or any(v > 3 for v in values):
                raise ValueError('foreign state enum')
            row.update(state=sum(1 << v for v in values), observed_state=1, dirty=True)
        def done(_p: Any) -> None:
            row['revision'] += 1
            self.atom('task', **{k: row[k] for k in ('id', 'title', 'app_id', 'state', 'observed_state', 'revision')},
                      outputs=sorted(row['outputs']))
            row.update(observed_state=0, dirty=False)
        def closed(_p: Any) -> None:
            del self.tasks[ident]
            self.atom('closed', id=ident)
            proxy.destroy()
        self.callback(proxy, 'title', lambda *args: value('title', *args))
        self.callback(proxy, 'app_id', lambda *args: value('app_id', *args))
        self.callback(proxy, 'output_enter', lambda *args: output(True, *args))
        self.callback(proxy, 'output_leave', lambda *args: output(False, *args))
        self.callback(proxy, 'state', state)
        self.callback(proxy, 'done', done)
        self.callback(proxy, 'closed', closed)
        # The v3 parent event is not an application-group or workspace relation.
        self.callback(proxy, 'parent', lambda *_: None)

    def protocol_dirty(self) -> bool:
        return self.workspace_dirty or any(r['dirty'] for r in self.tasks.values()) or any(r['dirty'] for r in self.outputs.values())

    def start_fence(self, phase: int = 0) -> None:
        counter = self.change_counter
        self.fence = self.display.sync()
        def complete(proxy: Any, _serial: int) -> None:
            proxy.destroy()
            self.fence = None
            if self.change_counter != counter or self.protocol_dirty():
                self.start_fence(0)
            elif phase == 0:
                self.start_fence(1)
            else:
                self.release_retired_outputs()
                self.say('barrier')
                self.pending = False
                self.batch_started = 0.0
        self.callback(self.fence, 'done', complete)

    def initialize(self) -> None:
        self.say('hello', pid=os.getpid(), capabilities=['ext-workspace-v1', 'foreign-toplevel-v1', 'wl-output-name', 'sync-fence'])
        self.display.connect()
        self.registry = self.display.get_registry()
        self.callback(self.registry, 'global', self.bind_globals)
        self.callback(self.registry, 'global_remove', self.remove_global)
        # Registry -> initial object properties -> idle done events. These are
        # the only blocking round trips; parent/systemd bound initialization.
        for _ in range(3):
            if self.display.roundtrip() < 0:
                raise RuntimeError('initial Wayland roundtrip failed')
            self.check()
        if self.workspace_manager is None or self.toplevel_manager is None or self.seat is None:
            raise RuntimeError('missing ext-workspace / foreign-toplevel / wl_seat global')
        if not self.seat_keyboard or not self.outputs or not all(r['ready'] for r in self.outputs.values()):
            raise RuntimeError('keyboard seat or named outputs unavailable')
        if not self.workspace_done or self.protocol_dirty():
            raise RuntimeError('initial protocol state incomplete')
        self.release_retired_outputs()
        self.say('barrier')
        self.pending = False
        self.say('ready')

    def command(self, msg: dict[str, Any]) -> None:
        wire.exact(msg, 'v', 'kind', 'instance', 'command_id', 'op', 'id')
        wire.integer(msg['v'], 1, 1)
        if msg['v'] != 1 or msg['kind'] != 'command' or msg['instance'] != self.instance:
            raise ValueError('command version/instance')
        ident = wire.integer(msg['id'], 2147483647, 1)
        command_id = wire.integer(msg['command_id'], 9007199254740000, 1)
        if command_id != self.command_id + 1:
            raise ValueError('command sequence')
        self.command_id = command_id
        if msg['op'] not in ('activate', 'set_minimized', 'unset_minimized', 'close'):
            raise ValueError('command verb')
        row = self.tasks.get(ident)
        status = 'stale'
        if row is not None:
            proxy = row['proxy']
            if msg['op'] == 'activate':
                if not self.seat_keyboard:
                    raise RuntimeError('keyboard seat disappeared')
                proxy.activate(self.seat)
            elif msg['op'] == 'set_minimized':
                proxy.set_minimized()
            elif msg['op'] == 'unset_minimized':
                proxy.unset_minimized()
            else:
                proxy.close()
            status = 'marshalled'
        # This acknowledges dispatch, not a compositor state change.
        self.say('ack', command_id=command_id, status=status)

    def flush_wayland(self) -> bool:
        result = self.display.flush()
        if result >= 0:
            return False
        code = self.get_errno()
        if code in (errno.EAGAIN, errno.EWOULDBLOCK):
            return True
        raise OSError(code, 'Wayland flush failed')

    def run(self) -> None:
        self.initialize()
        self.channel.setblocking(False)
        fd = self.display.get_fd()
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_READ, 'wayland')
            selector.register(self.channel, selectors.EVENT_READ, 'broker')
            while not self.stopping:
                self.display.dispatch(block=False)
                self.check()
                for msg in wire.take(self.incoming):
                    self.command(msg)
                if self.pending and self.fence is None:
                    self.start_fence()
                now = time.monotonic()
                if self.pending and now - self.batch_started > 5:
                    raise RuntimeError('protocol batch never became coherent')
                if now - self.last_heartbeat >= 5:
                    self.say('heartbeat')
                    self.last_heartbeat = now
                need_write = self.flush_wayland()
                selector.modify(fd, selectors.EVENT_READ | (selectors.EVENT_WRITE if need_write else 0), 'wayland')
                selector.modify(self.channel, selectors.EVENT_READ | (selectors.EVENT_WRITE if self.outgoing else 0), 'broker')
                # Already buffered complete requests must not wait for another
                # read edge when the per-iteration fairness budget was reached.
                complete = len(self.incoming) >= 4 and len(self.incoming) >= 4 + struct.unpack_from('!I', self.incoming)[0]
                for key, mask in selector.select(0 if complete else 0.5):
                    if key.data == 'wayland':
                        if mask & selectors.EVENT_READ:
                            self.display.read()
                    else:
                        if mask & selectors.EVENT_READ:
                            try:
                                data = self.channel.recv(65536)
                            except BlockingIOError:
                                data = None
                            if data == b'':
                                raise RuntimeError('parent channel closed')
                            if data:
                                self.incoming.extend(data)
                                if len(self.incoming) > wire.MAX_FRAME + 65536:
                                    raise RuntimeError('command input limit')
                        if mask & selectors.EVENT_WRITE and self.outgoing:
                            try:
                                sent = self.channel.send(self.outgoing)
                            except BlockingIOError:
                                sent = 0
                            if sent:
                                del self.outgoing[:sent]


def validated_channel(parent: int) -> socket.socket:
    uid = os.getuid()
    if uid == 0 or uid != os.geteuid() or os.getppid() != parent:
        raise RuntimeError('desktop user and expected parent required')
    base = Path(f'/run/user/{uid}')
    directory = base / 'labwc-workspace-broker'
    if os.environ.get('XDG_RUNTIME_DIR') != str(base):
        raise RuntimeError('unexpected runtime directory')
    for path in (base, directory):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('unsafe runtime directory')
    display = os.environ.get('WAYLAND_DISPLAY', '')
    if not re.fullmatch(r'wayland-[A-Za-z0-9_.-]{1,64}', display):
        raise RuntimeError('invalid Wayland display name')
    info = (base / display).lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid:
        raise RuntimeError('unsafe Wayland socket')
    path = directory / 'adapter.sock'
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeError('unsafe adapter socket')
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    channel.settimeout(3)
    channel.connect(str(path))
    pid, peer_uid, _ = struct.unpack('iII', channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if pid != parent or peer_uid != uid:
        channel.close()
        raise RuntimeError('unexpected broker peer')
    channel.setblocking(False)
    return channel


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != '--parent-pid' or not re.fullmatch(r'[1-9][0-9]{0,9}', sys.argv[2]):
        raise RuntimeError('expected --parent-pid PID')
    channel = validated_channel(int(sys.argv[2]))
    # Debian binary packages provide libwayland/CFFI. Nothing is compiled here.
    from pywayland import ffi
    from pywayland.client import Display
    from pywayland.protocol.wayland import WlOutput, WlSeat
    from .protocol import ExtWorkspaceManagerV1, ZwlrForeignToplevelManagerV1
    display = Display()
    driver = Driver(display, channel, {
        'wl_output': WlOutput, 'wl_seat': WlSeat,
        'ext_workspace_manager_v1': ExtWorkspaceManagerV1,
        'zwlr_foreign_toplevel_manager_v1': ZwlrForeignToplevelManagerV1,
    }, lambda: ffi.errno)
    def stop(_signum: int, _frame: Any) -> None:
        driver.stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        driver.run()
    finally:
        channel.close()
        display.disconnect()
    return 0
