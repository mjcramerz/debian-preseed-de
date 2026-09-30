"""HTTPS-only OpenURI client; the filtered bus is its sole host authority."""

from __future__ import annotations

import os
import re
import signal
import stat
import sys
import uuid

from .compat_protocol import ProtocolError, validate_uri

PORTAL = "org.freedesktop.portal.Desktop"
DESKTOP = "/org/freedesktop/portal/desktop"
REQUEST = "org.freedesktop.portal.Request"
METHOD_TIMEOUT_MS = 5000
RESPONSE_TIMEOUT_MS = 120000


def filtered_bus_address() -> str:
    expected = f"/run/user/{os.getuid()}/bus"
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS") != "unix:path=" + expected:
        raise ProtocolError("URI opener requires the managed filtered bus")
    metadata = os.lstat(expected)
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ProtocolError("URI opener bus socket is unsafe")
    return "unix:path=" + expected


def open_uri(uri: str, address: str, activation_token: str = "") -> int:
    validate_uri(uri, {"https"})
    if len(activation_token) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in activation_token):
        raise ProtocolError("URI opener activation context is invalid")
    # python3-gi is already an installed desktop-role dependency. Import it
    # only after URI validation and never fall back to xdg-open or a browser.
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    loop = GLib.MainLoop()
    cancellable = Gio.Cancellable()
    connection = None
    subscription = None
    owner_subscription = None
    expected_handle = None
    method_finished = False
    response = None
    result = None
    timers = set()
    handlers = {}

    def finish(code):
        nonlocal result
        if result is None:
            result = code
        loop.quit()

    def timer(milliseconds, code):
        def expire():
            finish(code)
            return False
        source = GLib.timeout_add(milliseconds, expire)
        timers.add(source)
        return source

    def cancel(signum, _frame):
        cancellable.cancel()
        finish(128 + signum)

    def on_response(_bus, _sender, path, _interface, _signal, parameters, _data):
        nonlocal response
        if path != expected_handle:
            return
        code, _results = parameters.unpack()
        response = code if type(code) is int and code in (0, 1, 2) else 2
        if method_finished:
            finish(response)

    def on_owner(_bus, _sender, _path, _interface, _signal, parameters, _data):
        _name, previous, current = parameters.unpack()
        if previous and previous != current:
            finish(2)

    def opened(bus, async_result, _data):
        nonlocal method_finished
        try:
            handle, = bus.call_finish(async_result).unpack()
            if handle != expected_handle:
                finish(2)
                return
            method_finished = True
            if response is not None:
                finish(response)
            else:
                timer(RESPONSE_TIMEOUT_MS, 3)
        except GLib.Error:
            finish(2)

    def connected(_source, async_result, _data):
        nonlocal connection, subscription, owner_subscription, expected_handle
        try:
            connection = Gio.DBusConnection.new_for_address_finish(async_result)
            connection.set_exit_on_close(False)
            connection.connect("closed", lambda *_args: finish(2))
            unique = connection.get_unique_name()
            if not unique or re.fullmatch(r":[0-9]+\.[0-9]+", unique) is None:
                finish(2)
                return
            token = "labwc_compat_" + uuid.uuid4().hex
            expected_handle = DESKTOP + "/request/" + unique[1:].replace(".", "_") + "/" + token
            # Install the response match BEFORE OpenURI. A round-trip to the
            # bus ensures that preceding AddMatch messages have been handled.
            subscription = connection.signal_subscribe(
                PORTAL, REQUEST, "Response", expected_handle, None,
                Gio.DBusSignalFlags.NONE, on_response, None,
            )
            owner_subscription = connection.signal_subscribe(
                "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                "/org/freedesktop/DBus", PORTAL, Gio.DBusSignalFlags.NONE, on_owner, None,
            )
            connection.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                "GetId", None, GLib.VariantType.new("(s)"), Gio.DBusCallFlags.NONE,
                METHOD_TIMEOUT_MS, cancellable,
            )
            options = {"handle_token": GLib.Variant("s", token)}
            if activation_token:
                options["activation_token"] = GLib.Variant("s", activation_token)
            connection.call(
                PORTAL, DESKTOP, "org.freedesktop.portal.OpenURI", "OpenURI",
                # No legitimate host-exported parent exists for a nested X11
                # window. Empty is the portal's supported parentless request.
                GLib.Variant("(ssa{sv})", ("", uri, options)), GLib.VariantType.new("(o)"),
                Gio.DBusCallFlags.NONE, METHOD_TIMEOUT_MS, cancellable, opened, None,
            )
        except GLib.Error:
            finish(2)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            handlers[signum] = signal.signal(signum, cancel)
        setup_timer = timer(METHOD_TIMEOUT_MS * 3, 3)
        Gio.DBusConnection.new_for_address(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, cancellable, connected, None,
        )
        # Remove the setup deadline after the method reply; user interaction
        # gets its independently bounded lifetime instead.
        def setup_complete():
            if method_finished:
                GLib.source_remove(setup_timer)
                timers.discard(setup_timer)
                return False
            return result is None
        timers.add(GLib.timeout_add(25, setup_complete))
        if result is None:
            loop.run()
        return 2 if result is None else result
    finally:
        cancellable.cancel()
        if connection is not None:
            if expected_handle is not None and result not in (0, 1):
                try:
                    connection.call_sync(PORTAL, expected_handle, REQUEST, "Close", None, None,
                                         Gio.DBusCallFlags.NONE, 500, None)
                except GLib.Error:
                    pass  # preserve timeout/bus-loss/stop as the first cause
            for match in (subscription, owner_subscription):
                if match is not None:
                    connection.signal_unsubscribe(match)
            try:
                connection.close_sync(None)
            except GLib.Error:
                pass  # bus loss must not replace the already classified result
        for source in timers:
            if GLib.MainContext.default().find_source_by_id(source) is not None:
                GLib.source_remove(source)
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def main(arguments=None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if len(arguments) != 1 or os.geteuid() == 0:
            raise ProtocolError("URI opener requires one URI and a non-root user")
        validate_uri(arguments[0], {"https"})
        return open_uri(arguments[0], filtered_bus_address(), os.environ.get("XDG_ACTIVATION_TOKEN", ""))
    except (ProtocolError, OSError, ValueError, ImportError):
        # D-Bus errors can quote method parameters. Never render exception
        # text, the URI, or its reversible encoding into diagnostics.
        print("compat-open-uri: request failed", file=sys.stderr)
        return 2
