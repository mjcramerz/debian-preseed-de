#!/usr/bin/python3 -I
"""Test-only real D-Bus notification peer, using the packaged libdbus ABI.

Run inside dbus-run-session. No desktop daemon or user session is contacted.
"""
import ctypes as c
import json
from pathlib import Path
import subprocess
import sys
import time


def run(helper: str, failures: int) -> dict:
    lib = c.CDLL('libdbus-1.so.3')
    def function(name, result, arguments):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, arguments
        return fn
    pointer, integer, string = c.c_void_p, c.c_int, c.c_char_p
    get = function('dbus_bus_get_private', pointer, [integer, pointer])
    request = function('dbus_bus_request_name', integer, [pointer, string, c.c_uint32, pointer])
    read = function('dbus_connection_read_write', integer, [pointer, integer])
    pop = function('dbus_connection_pop_message', pointer, [pointer])
    is_call = function('dbus_message_is_method_call', integer, [pointer, string, string])
    signature = function('dbus_message_get_signature', string, [pointer])
    reply = function('dbus_message_new_method_return', pointer, [pointer])
    error = function('dbus_message_new_error', pointer, [pointer, string, string])
    append = function('dbus_message_append_args', integer, [pointer, integer])  # varargs
    send = function('dbus_connection_send', integer, [pointer, pointer, pointer])
    flush = function('dbus_connection_flush', None, [pointer])
    unref = function('dbus_message_unref', None, [pointer])
    close = function('dbus_connection_close', None, [pointer])
    conn_unref = function('dbus_connection_unref', None, [pointer])
    bus = get(0, None)
    if not bus or request(bus, b'org.freedesktop.Notifications', 4, None) != 1:
        raise RuntimeError('private notification bus ownership failed')
    process = subprocess.Popen([sys.executable, '-B', helper, '-a', 'Test Health',
                                '-c', 'system.health', '--', 'Fixture', '<body & text>'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    count, signatures = 0, []
    try:
        deadline = time.monotonic() + 18
        while process.poll() is None and time.monotonic() < deadline:
            read(bus, 50)
            message = pop(bus)
            if not message:
                continue
            try:
                if not is_call(message, b'org.freedesktop.Notifications', b'Notify'):
                    continue
                count += 1
                signatures.append(signature(message).decode())
                if count <= failures:
                    response = error(message, b'org.freedesktop.DBus.Error.Failed', b'fixture failure')
                else:
                    response = reply(message)
                    notification_id = c.c_uint32(42)
                    if not append(response, ord('u'), c.byref(notification_id), c.c_int(0)):
                        raise RuntimeError('append reply failed')
                try:
                    if not send(bus, response, None):
                        raise RuntimeError('send reply failed')
                    flush(bus)
                finally:
                    unref(response)
            finally:
                unref(message)
        stdout, stderr = process.communicate(timeout=1)
        return dict(returncode=process.returncode, calls=count, signatures=signatures,
                    stdout=stdout, stderr=stderr)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        close(bus)
        conn_unref(bus)


if __name__ == '__main__':
    print(json.dumps(run(str(Path(sys.argv[1]).resolve()), int(sys.argv[2]))))
