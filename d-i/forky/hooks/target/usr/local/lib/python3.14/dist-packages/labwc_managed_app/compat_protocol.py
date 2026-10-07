"""Bounded, non-secret outcome records and compatibility activation messages."""

from __future__ import annotations

from dataclasses import dataclass
import json
import ctypes
import os
import re
import signal
import socket
import struct
import time
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit

APPLICATIONS = {"discord", "zoom"}
MODES = {"launch", "intel", "nvidia"}
MAX_URI_BYTES = 8192
MAX_PACKET_BYTES = 16384
CONTROL_DIRECTORY = "/run/labwc-compat-control"
CONTROL_SOCKET = CONTROL_DIRECTORY + "/instance.sock"
UNKNOWN_RESULT = 70
INFRASTRUCTURE_RESULT = 71
STARTUP_RESULT = 72
CLEANUP_RESULT = 73
OUTCOMES = {
    "startup-failed", "running", "normal-exit", "application-failed",
    "infrastructure-failed", "user-stopped", "shutdown-stopped",
    "outcome-unknown", "cleanup-failed",
}


class ProtocolError(RuntimeError):
    """Never include untrusted input in this exception's message."""


class RequiredComponentError(ProtocolError):
    """A directly observed critical-helper wait status, never inferred from 128+n."""

    def __init__(self, returncode: int):
        self.signal = -returncode if returncode < 0 else 0
        self.result = 128 + self.signal if self.signal else returncode or INFRASTRUCTURE_RESULT
        super().__init__("required compatibility component exited")


def validate_uri(uri: str, schemes: set[str]) -> str:
    if not isinstance(uri, str) or not uri:
        raise ProtocolError("URI exceeds the limit or is empty")
    try:
        if len(uri.encode("utf-8")) > MAX_URI_BYTES:
            raise ProtocolError("URI exceeds the limit")
        decoded = unquote(uri, errors="strict")
    except UnicodeError:
        raise ProtocolError("URI encoding is malformed") from None
    # Refuse shell-looking input even though no shell is used. Check decoded
    # controls too; escaped meeting/authentication values otherwise stay intact.
    if any(ord(c) <= 32 or unicodedata.category(c) in {"Cc", "Cf"} or c in "`\\\"<>|;'(){}" for c in uri):
        raise ProtocolError("URI contains forbidden characters")
    if "$" in uri or re.search(r"%(?![0-9a-fA-F]{2})", uri):
        raise ProtocolError("URI contains invalid escaping")
    if any(unicodedata.category(c) in {"Cc", "Cf"} for c in decoded):
        raise ProtocolError("URI contains escaped controls")
    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except (ValueError, UnicodeError):
        raise ProtocolError("URI is malformed") from None
    if parsed.scheme not in schemes or not parsed.netloc or not parsed.hostname:
        raise ProtocolError("URI scheme or authority is not approved")
    if parsed.username is not None or parsed.password is not None or port == 0:
        raise ProtocolError("URI credentials or port are not approved")
    return uri


def activation_arguments(app: str, arguments: list[str]) -> list[str]:
    if app not in APPLICATIONS:
        raise ProtocolError("application is not a compatibility client")
    if not isinstance(arguments, list):
        raise ProtocolError("activation argument type is invalid")
    if arguments == ["--url="] and app == "zoom":
        return []
    if not arguments:
        return []
    if len(arguments) != 1 or not isinstance(arguments[0], str):
        raise ProtocolError("activation accepts at most one application URI")
    uri = arguments[0]
    if app == "zoom":
        uri = uri.removeprefix("--url=")
        validate_uri(uri, {"zoommtg", "zoomus"})
        return ["--url=" + uri]
    return [validate_uri(uri, {"discord"})]


@dataclass(frozen=True)
class Outcome:
    primary: str
    result: int
    signal: int = 0
    cleanup: str = "ok"

    def __post_init__(self):
        if (not isinstance(self.primary, str) or self.primary not in OUTCOMES or type(self.result) is not int
                or not 0 <= self.result <= 255 or type(self.signal) is not int
                or not 0 <= self.signal < signal.NSIG or not isinstance(self.cleanup, str)
                or self.cleanup not in {"ok", "failed"}):
            raise ProtocolError("invalid outcome record")
        if self.primary != "normal-exit" and self.primary != "running" and self.result == 0:
            raise ProtocolError("unproven outcome cannot be success")
        if self.primary == "normal-exit" and (self.result != 0 or self.signal):
            raise ProtocolError("invalid normal application outcome")

    @classmethod
    def observed(cls, app: str, returncode: int) -> "Outcome":
        if returncode < 0:
            return cls("application-failed", 128 - returncode, -returncode)
        if returncode:
            return cls("application-failed", min(returncode, 255))
        # The shipped Zoom launcher contract does not prove its child's wait
        # status. Do not bypass vendor initialization or infer a clean exit.
        if app == "zoom":
            return cls("outcome-unknown", UNKNOWN_RESULT)
        return cls("normal-exit", 0)

    def packet(self) -> dict:
        return {"type": "outcome", "primary": self.primary, "result": self.result,
                "signal": self.signal, "cleanup": self.cleanup}

    def cleanup_failed(self) -> "Outcome":
        return Outcome("cleanup-failed" if self.result == 0 else self.primary,
                       self.result or CLEANUP_RESULT, self.signal, "failed")

    @classmethod
    def from_packet(cls, value: dict) -> "Outcome":
        if set(value) != {"type", "primary", "result", "signal", "cleanup"} or value["type"] != "outcome":
            raise ProtocolError("unexpected outcome fields")
        return cls(value["primary"], value["result"], value["signal"], value["cleanup"])


def send_packet(channel: socket.socket, value: dict) -> None:
    packet = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if len(packet) > MAX_PACKET_BYTES:
        raise ProtocolError("IPC packet exceeds the limit")
    if channel.send(packet) != len(packet):
        raise ProtocolError("IPC packet was truncated")


def receive_packet(channel: socket.socket) -> dict:
    packet, _ancillary, flags, _address = channel.recvmsg(MAX_PACKET_BYTES, 0)
    if not packet or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
        raise ProtocolError("IPC channel closed or packet exceeded the limit")
    try:
        result = json.loads(packet)
    except (ValueError, UnicodeError):
        raise ProtocolError("IPC packet is malformed") from None
    if not isinstance(result, dict):
        raise ProtocolError("IPC packet is not an object")
    return result


def peer_credentials(channel: socket.socket) -> tuple[int, int, int]:
    return struct.unpack("3i", channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))


def protect_supervisor() -> None:
    # The inherited AppArmor label remains shared on the target's NNP path.
    # Linux dumpability protects supervisor memory and /proc/PID/fd access from
    # its same-UID children without pretending an untested profile transition.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
        raise ProtocolError("cannot protect trusted supervisor descriptors")


def stop_processes(processes, deadline: float, *, groups: bool = False) -> bool:
    """One deadline for TERM, KILL and reaping; no process-name selection."""
    processes = [p for p in processes if p is not None]
    for p in processes:
        try:
            if groups and p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
            elif p.poll() is None:
                p.terminate()
        except ProcessLookupError:
            pass
    kill_at = max(time.monotonic(), deadline - 0.5)
    while time.monotonic() < kill_at and any(p.poll() is None for p in processes):
        time.sleep(min(0.025, max(0, kill_at - time.monotonic())))
    for p in processes:
        try:
            if groups and p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
            elif p.poll() is None:
                p.kill()
        except ProcessLookupError:
            pass
    for p in processes:
        try:
            p.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return False
    return all(p.poll() is not None for p in processes)
