"""Unprivileged Power Profiles D-Bus adapter; hardware authority stays in broker.

All mutations use the existing credential-checked control socket. One bounded
queue serializes backend requests off the GLib main loop. Holds are live socket
leases, so process death releases them without trusting a PID or cleanup file.
"""
from __future__ import annotations

import logging
import os
import queue
import signal
import socket
import threading
import time

from gi.repository import Gio, GLib
from client import connect_request
from common import TuningError

LOG = logging.getLogger("hardware-power-profiles")
PROFILES = {"power-saver": "silent", "balanced": "balanced", "performance": "performance"}
INTERFACES = {
    "/org/freedesktop/UPower/PowerProfiles": "org.freedesktop.UPower.PowerProfiles",
    "/net/hadess/PowerProfiles": "net.hadess.PowerProfiles",
}
PROPERTIES = "org.freedesktop.DBus.Properties"
ERROR = "org.freedesktop.DBus.Error."
XML_PROPERTIES = '''<interface name="org.freedesktop.DBus.Properties">
<method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
<method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/></method>
<signal name="PropertiesChanged"><arg type="s"/><arg type="a{sv}"/><arg type="as"/></signal>
</interface>'''
XML_API = '''<interface name="{interface}">
<method name="HoldProfile"><arg name="profile" type="s" direction="in"/><arg name="reason" type="s" direction="in"/><arg name="application_id" type="s" direction="in"/><arg name="cookie" type="u" direction="out"/></method>
<method name="ReleaseProfile"><arg name="cookie" type="u" direction="in"/></method>
<method name="SetActionEnabled"><arg type="s" direction="in"/><arg type="b" direction="in"/></method>
<signal name="ProfileReleased"><arg type="u"/></signal>
<property name="ActiveProfile" type="s" access="readwrite"/>
<property name="PerformanceInhibited" type="s" access="read"/>
<property name="PerformanceDegraded" type="s" access="read"/>
<property name="Profiles" type="aa{{sv}}" access="read"/>
<property name="Actions" type="as" access="read"/>
<property name="ActionsInfo" type="aa{{sv}}" access="read"/>
<property name="ActiveProfileHolds" type="aa{{sv}}" access="read"/>
<property name="Version" type="s" access="read"/>
<property name="BatteryAware" type="b" access="readwrite"/>
</interface>'''


def active_profile(status: dict) -> str:
    applied = status.get("applied", {}).get("intel")
    return {"silent": "power-saver", "balanced": "balanced", "high": "performance",
            "performance": "performance", None: "balanced"}[applied]


class Adapter:
    def __init__(self, bus, status: dict) -> None:
        self.bus, self.status = bus, status
        self.holds = {}
        self.cookie = 0
        self.jobs = queue.Queue(maxsize=8)
        self.polling = False
        self.unavailable = False
        self.closed = False
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.worker, name="profile-control", daemon=True)
        self.thread.start()

    def authorize(self, sender: str) -> None:
        reply = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "GetConnectionUnixUser", GLib.Variant("(s)", (sender,)),
            GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 2000, None)
        if reply.unpack()[0] not in {0, os.getuid()}:
            raise PermissionError("only the configured desktop account may change profiles")

    def properties(self) -> dict:
        faults = self.status.get("faults", {})
        degraded = ""
        if self.unavailable or self.status.get("recovery_pending") or self.status.get("policy_release_pending"):
            degraded = "unavailable"
        elif faults:
            degraded = "high-operating-temperature" if any("thermal" in str(v).lower() for v in faults.values()) else "hardware-fault"
        profiles = [{"Profile": GLib.Variant("s", name), "Driver": GLib.Variant("s", "hardware-tuning")}
                    for name in PROFILES]
        holds = [{key: GLib.Variant("s", item[key]) for key in ("Profile", "Reason", "ApplicationId")}
                 for item in self.holds.values()]
        return {
            "ActiveProfile": GLib.Variant("s", active_profile(self.status)),
            "PerformanceInhibited": GLib.Variant("s", ""),
            "PerformanceDegraded": GLib.Variant("s", degraded),
            "Profiles": GLib.Variant("aa{sv}", profiles),
            "Actions": GLib.Variant("as", []),
            "ActionsInfo": GLib.Variant("aa{sv}", []),
            "ActiveProfileHolds": GLib.Variant("aa{sv}", holds),
            "Version": GLib.Variant("s", "hardware-tuning-1"),
            "BatteryAware": GLib.Variant("b", True),
        }

    def changed(self) -> None:
        if self.closed:
            return
        for path, interface in INTERFACES.items():
            self.bus.emit_signal(None, path, PROPERTIES, "PropertiesChanged",
                                 GLib.Variant("(sa{sv}as)", (interface, self.properties(), [])))

    def release(self, cookie: int, *, notify: bool = False) -> None:
        item = self.holds.pop(cookie)
        item["socket"].close()
        if notify and not self.closed:
            self.bus.emit_signal(item["sender"], item["path"], INTERFACES[item["path"]],
                                 "ProfileReleased", GLib.Variant("(u)", (cookie,)))

    def update(self, status: dict) -> None:
        if status.get("power_profiles_api") is not True or "intel" not in status.get("vendors", []):
            raise TuningError("custom Power Profiles provider is not configured")
        before = self.properties()
        self.status, self.unavailable = status, False
        for cookie, item in list(self.holds.items()):
            dead = False
            try:
                dead = item["socket"].recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT) == b""
            except BlockingIOError:
                pass
            except OSError:
                dead = True
            if dead or item["generation"] != status["power_generation"]:
                self.release(cookie, notify=True)
        if before != self.properties():
            self.changed()

    def worker(self) -> None:
        while True:
            item = self.jobs.get()
            if item is None or self.closed:
                return
            request, done, deadline = item
            channel = None
            try:
                channel, result = connect_request(request, deadline=deadline)
                if request["action"] == "power-hold":
                    channel.setblocking(False)
                else:
                    channel.close()
                    channel = None
                GLib.idle_add(self.complete, done, channel, result, None)
            except Exception as exc:
                if channel is not None:
                    channel.close()
                GLib.idle_add(self.complete, done, None, None, exc)

    def complete(self, done, channel, result, error) -> bool:
        if self.closed:
            if channel is not None:
                channel.close()
            return False
        try:
            if result is not None:
                self.update(result)
        except Exception as exc:
            if channel is not None:
                channel.close()
            channel, result, error = None, None, exc
        try:
            done(channel, result, error)
        except Exception:
            if channel is not None:
                channel.close()
            LOG.error("power_profiles outcome=reply-failed")
        return False

    def submit(self, request: dict, done) -> None:
        try:
            deadline = time.monotonic() + (15 if request["action"] == "status" else 360)
            self.jobs.put_nowait((request, done, deadline))
        except queue.Full as exc:
            raise TuningError("power profile controller busy; request was not sent") from exc

    def poll(self) -> bool:
        if not self.polling:
            self.polling = True
            def done(_channel, _result, error):
                self.polling = False
                if error and not self.unavailable:
                    self.unavailable = True
                    LOG.error("power_profiles outcome=backend-unavailable")
                    self.changed()
            try:
                self.submit({"action": "status"}, done)
            except TuningError:
                self.polling = False
        return not self.closed

    def owner_changed(self, _bus, _sender, _path, _interface, _signal, parameters, _data) -> None:
        name, _old, new = parameters.unpack()
        if name.startswith(":") and not new:
            released = False
            for cookie, item in list(self.holds.items()):
                if item["sender"] == name:
                    self.release(cookie)
                    released = True
            if released:
                self.changed()
                self.poll()

    @staticmethod
    def failed(invocation, error) -> None:
        invocation.return_dbus_error(ERROR + "Failed",
            "Custom tuning did not confirm completion; inspect hardware tuning status. " + str(error)[:512])

    def mutate(self, invocation, request: dict, after=None) -> None:
        def done(channel, result, error):
            if error:
                self.failed(invocation, error)
                self.poll()  # Refresh only. Never retry an uncertain mutation.
            elif after is not None:
                after(channel, result)
            else:
                invocation.return_value(GLib.Variant("()", ()))
        self.submit(request, done)

    def call(self, _bus, sender, path, interface, method, parameters, invocation) -> None:
        try:
            args = parameters.unpack()
            if interface == PROPERTIES:
                if args[0] != INTERFACES[path]:
                    raise ValueError("unknown power profiles interface")
                values = self.properties()
                if method == "GetAll":
                    invocation.return_value(GLib.Variant("(a{sv})", (values,)))
                    return
                key = args[1]
                if key not in values:
                    raise ValueError("unknown power profile property")
                if method == "Get":
                    invocation.return_value(GLib.Variant("(v)", (values[key],)))
                    return
                self.authorize(sender)
                value = parameters.get_child_value(2).get_variant()
                if key == "ActiveProfile" and value.get_type_string() == "s" and value.unpack() in PROFILES:
                    self.mutate(invocation, {"action": "power-profile", "profile": PROFILES[value.unpack()]})
                    return
                if key == "BatteryAware" and value.get_type_string() == "b" and value.unpack():
                    invocation.return_value(GLib.Variant("()", ()))
                    return
                raise ValueError("property is read-only or the value is unsupported")
            self.authorize(sender)
            if method == "HoldProfile":
                profile, reason, application = args
                if profile not in {"power-saver", "performance"} or not reason or not application:
                    raise ValueError("hold requires performance/power-saver, reason and application ID")
                if any(len(text.encode("utf-8")) > 512 or any(ord(c) < 32 for c in text) for text in (reason, application)):
                    raise ValueError("hold metadata is invalid or exceeds its limit")
                if len(self.holds) >= 32:
                    raise TuningError("too many profile holds")
                def held(channel, result):
                    try:
                        self.authorize(sender)  # The caller may have exited while queued.
                        if len(self.holds) >= 32:
                            raise TuningError("too many profile holds")
                        if result["power_generation"] != self.status["power_generation"]:
                            raise TuningError("profile hold was superseded")
                        self.cookie = self.cookie % (2**32 - 1) + 1
                        while self.cookie in self.holds:
                            self.cookie = self.cookie % (2**32 - 1) + 1
                        self.holds[self.cookie] = {"sender": sender, "path": path, "socket": channel,
                            "generation": result["power_generation"], "Profile": profile,
                            "Reason": reason, "ApplicationId": application}
                        self.changed()
                        invocation.return_value(GLib.Variant("(u)", (self.cookie,)))
                    except Exception as exc:
                        channel.close()
                        self.failed(invocation, exc)
                self.mutate(invocation, {"action": "power-hold", "profile": PROFILES[profile]}, held)
                return
            if method == "ReleaseProfile":
                cookie = args[0]
                if cookie not in self.holds or self.holds[cookie]["sender"] != sender:
                    raise PermissionError("profile hold belongs to a different connection or is absent")
                self.release(cookie)
                self.changed()
                self.poll()
                invocation.return_value(GLib.Variant("()", ()))
                return
            raise ValueError("no optional profile actions are installed")
        except PermissionError as exc:
            invocation.return_dbus_error(ERROR + "AccessDenied", str(exc))
        except (ValueError, KeyError) as exc:
            invocation.return_dbus_error(ERROR + "InvalidArgs", str(exc))
        except (TuningError, GLib.Error) as exc:
            self.failed(invocation, exc)

    def run(self) -> None:
        registrations = []
        subscription = self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
            "NameOwnerChanged", "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE,
            self.owner_changed, None)
        timer = None
        try:
            for path, interface in INTERFACES.items():
                info = Gio.DBusNodeInfo.new_for_xml("<node>" + XML_PROPERTIES + XML_API.format(interface=interface) + "</node>")
                for item in info.interfaces:
                    registrations.append(self.bus.register_object(path, item, self.call, None, None))
                reply = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                    "RequestName", GLib.Variant("(su)", (interface, 4)), GLib.VariantType.new("(u)"),
                    Gio.DBusCallFlags.NONE, 2000, None)
                if reply.unpack()[0] != 1:
                    raise TuningError("another process owns the Power Profiles API")
            for signum in (signal.SIGTERM, signal.SIGINT):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self.loop.quit)
            timer = GLib.timeout_add_seconds(5, self.poll)
            self.loop.run()
        finally:
            self.closed = True
            for cookie in list(self.holds):
                self.release(cookie)
            if timer is not None:
                GLib.source_remove(timer)
            self.bus.signal_unsubscribe(subscription)
            for registration in registrations:
                self.bus.unregister_object(registration)
            # Closing the private connection releases both names and all holds.
            self.bus.close_sync(None)


def main() -> int:
    if os.getuid() < 1000 or os.geteuid() != os.getuid():
        raise TuningError("Power Profiles adapter must run as the configured desktop account")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    channel, status = connect_request({"action": "status"})
    channel.close()
    if status.get("power_profiles_api") is not True:
        raise TuningError("custom Power Profiles provider is not installed")
    bus = Gio.DBusConnection.new_for_address_sync("unix:path=/run/dbus/system_bus_socket",
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)
    bus.set_exit_on_close(True)
    Adapter(bus, status).run()
    return 0
