"""Host-side lifetime lock and narrow per-application activation coordinator."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
import re
import select
import signal
import socket
import stat
import subprocess
import time
import uuid

from .compat_protocol import (
    APPLICATIONS, MODES, Outcome, ProtocolError, activation_arguments,
    peer_credentials, receive_packet, send_packet, protect_supervisor,
)
from .runtime import current_user_runtime_dir, managed_subprocess_environment, require_root_owned_executable

LAUNCH_TIMEOUT = 40.0
REQUEST_TIMEOUT = 8.0
RUNTIME_HELPER = "/usr/local/libexec/labwc-zoom-discord-compat-runtime"
UNIT_PATTERN = r"labwc-compat-(discord|zoom)-([0-9a-f]{32})\.service"


def process_unit(pid: int) -> str:
    with open(f"/proc/{pid}/cgroup", encoding="ascii") as stream:
        content = stream.read(65537)
    if len(content) > 65536:
        raise ProtocolError("cgroup identity exceeds the limit")
    for line in content.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[1] in {"", "name=systemd"}:
            unit = fields[2].rsplit("/", 1)[-1]
            if re.fullmatch(UNIT_PATTERN, unit):
                return unit
    raise ProtocolError("coordinator is outside its managed service")


def instance_directory(app: str) -> Path:
    if app not in APPLICATIONS:
        raise ProtocolError("coordinator application is not approved")
    path = Path(current_user_runtime_dir()) / ("labwc-compat-" + app)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    metadata = path.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or path.resolve() != path
            or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700):
        raise ProtocolError("coordinator directory is unsafe")
    return path


def open_lock(directory: Path, name: str) -> int:
    fd = os.open(directory / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    metadata = os.fstat(fd)
    entry = (directory / name).lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_nlink != 1
            or (metadata.st_dev, metadata.st_ino) != (entry.st_dev, entry.st_ino)):
        os.close(fd)
        raise ProtocolError("coordinator lock is unsafe or replaced")
    return fd


def acquire_lock(fd: int, deadline: float) -> None:
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise ProtocolError("coordinator lock timed out")
            time.sleep(0.025)


def verify_lock_entry(fd: int, path: Path) -> None:
    opened, entry = os.fstat(fd), path.lstat()
    if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.getuid()
            or stat.S_IMODE(entry.st_mode) != 0o600 or entry.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (entry.st_dev, entry.st_ino)):
        raise ProtocolError("coordinator lock was replaced")


def instance_owned(app: str) -> bool:
    fd = open_lock(instance_directory(app), "instance.lock")
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)


def _safe_endpoint(path: Path) -> None:
    metadata = path.lstat()
    if (not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600):
        raise ProtocolError("coordinator endpoint is unsafe")


def _verify_service(channel: socket.socket, hello: dict, app: str) -> None:
    if set(hello) != {"type", "unit", "run_id", "invocation", "app", "mode"} or hello["type"] != "instance":
        raise ProtocolError("coordinator identity is malformed")
    if not all(isinstance(v, str) for v in hello.values()):
        raise ProtocolError("coordinator identity has invalid types")
    match = re.fullmatch(UNIT_PATTERN, hello["unit"])
    if (match is None or match.group(1) != app or match.group(2) != hello["run_id"]
            or hello["app"] != app or hello["mode"] not in MODES
            or re.fullmatch(r"[0-9a-f]{32}", hello["invocation"]) is None):
        raise ProtocolError("coordinator identity is mismatched")
    pid, uid, _gid = peer_credentials(channel)
    if uid != os.getuid() or process_unit(pid) != hello["unit"]:
        raise ProtocolError("coordinator peer identity is mismatched")
    systemctl = require_root_owned_executable("systemctl", "/usr/bin/systemctl")
    result = subprocess.run(
        [systemctl, "--user", "show", hello["unit"], "--property=MainPID",
         "--property=InvocationID", "--property=ActiveState"],
        env={**managed_subprocess_environment(), "XDG_RUNTIME_DIR": current_user_runtime_dir(),
             "DBUS_SESSION_BUS_ADDRESS": f"unix:path={current_user_runtime_dir()}/bus"},
        capture_output=True, timeout=2, check=False,
    )
    if result.returncode or len(result.stdout) > 4096:
        raise ProtocolError("coordinator service identity is unavailable")
    fields = dict(line.split("=", 1) for line in result.stdout.decode("ascii").splitlines() if "=" in line)
    if (fields.get("MainPID") != str(pid) or fields.get("InvocationID") != hello["invocation"]
            or fields.get("ActiveState") not in {"active", "activating"}):
        raise ProtocolError("coordinator service is stale or forged")


def request_activation(app: str, mode: str, arguments: list[str], *, deadline: float) -> bool:
    """False only when the lifetime lock proves there is no running instance."""
    arguments = activation_arguments(app, arguments)
    directory = instance_directory(app)
    fd = open_lock(directory, "instance.lock")
    try:
        while time.monotonic() < deadline:
            verify_lock_entry(fd, directory / "instance.lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                path = directory / "instance.sock"
                if os.path.lexists(path):
                    _safe_endpoint(path)
                    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as probe:
                        probe.settimeout(0.25)
                        try:
                            probe.connect(str(path))
                        except (ConnectionRefusedError, FileNotFoundError):
                            pass
                        else:
                            raise ProtocolError("live coordinator lost its lifetime lock")
                return False
            path = directory / "instance.sock"
            try:
                _safe_endpoint(path)
            except FileNotFoundError:
                time.sleep(0.025)
                continue
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as channel:
                channel.settimeout(min(REQUEST_TIMEOUT, max(0.01, deadline - time.monotonic())))
                try:
                    channel.connect(str(path))
                except (ConnectionRefusedError, FileNotFoundError):
                    time.sleep(0.025)
                    continue
                hello = receive_packet(channel)
                _verify_service(channel, hello, app)
                if mode != "auto" and mode != hello["mode"]:
                    raise ProtocolError("active instance uses a different accelerator policy")
                send_packet(channel, {"type": "activate", "args": arguments})
                response = receive_packet(channel)
                if response == {"type": "activation", "accepted": True}:
                    return True
                if response == {"type": "activation", "accepted": False}:
                    time.sleep(0.05)
                    continue
                raise ProtocolError("invalid activation response")
        raise ProtocolError("existing instance did not become ready before timeout")
    finally:
        os.close(fd)


class CompatibilityInstance:
    """The service's main process holds this lock until all cleanup finishes."""

    def __init__(self, app: str, mode: str):
        if app not in APPLICATIONS or mode not in MODES:
            raise ProtocolError("invalid instance policy")
        self.app, self.mode = app, mode
        self.directory = instance_directory(app)
        self.unit = process_unit(os.getpid())
        match = re.fullmatch(UNIT_PATTERN, self.unit)
        if match.group(1) != app:
            raise ProtocolError("instance service application is mismatched")
        self.run_id = match.group(2)
        self.invocation = os.environ.get("INVOCATION_ID", "")
        if re.fullmatch(r"[0-9a-f]{32}", self.invocation) is None:
            raise ProtocolError("instance lacks the manager invocation identity")
        self.lock_fd = None
        self.listener = None
        self.endpoint_identity = None
        self.runtime = None
        self.clients = {}
        self.requests = {}
        self.outcome = None
        self.running = False
        self.stop_signal = None
        self.cleanup_deadline = None
        self.cleanup_failed = False
        self.handlers = {}

    def __enter__(self):
        protect_supervisor()
        self.lock_fd = open_lock(self.directory, "instance.lock")
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            path = self.directory / "instance.sock"
            if os.path.lexists(path):
                _safe_endpoint(path)
                path.unlink()  # exclusive lifetime lock proves old ownership ended
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self.listener.bind(str(path))
            path.chmod(0o600)
            metadata = path.lstat()
            self.endpoint_identity = (metadata.st_dev, metadata.st_ino)
            self.listener.listen(8)
            self.listener.setblocking(False)
            for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
                self.handlers[signum] = signal.signal(signum, self._signal)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _signal(self, signum, _frame):
        if self.stop_signal is None:
            self.stop_signal = signum
            self.begin_cleanup()

    def begin_cleanup(self) -> float:
        if self.cleanup_deadline is None:
            self.cleanup_deadline = time.monotonic() + 8
        return self.cleanup_deadline

    def _drop(self, channel):
        self.clients.pop(channel, None)
        channel.close()

    def _reply(self, channel, accepted):
        try:
            send_packet(channel, {"type": "activation", "accepted": accepted})
        except (OSError, ProtocolError):
            pass
        self._drop(channel)

    def _require_helper(self, channel, *, compositor=False):
        pid, _uid, _gid = peer_credentials(channel)
        if process_unit(pid) != self.unit:
            raise ProtocolError("helper peer is outside the managed service")
        with open(f"/proc/{pid}/cmdline", "rb") as stream:
            raw = stream.read(32769)
        command = raw.split(b"\0")
        if (len(raw) > 32768 or RUNTIME_HELPER.encode() not in command
                or (compositor and b"--supervise-cage" not in command)):
            raise ProtocolError("peer is not the required managed helper")

    def _compositor_outcome(self, value):
        if set(value) != {"type", "run_id", "result", "signal", "cleanup"} or value["run_id"] != self.run_id:
            raise ProtocolError("compositor outcome identity is invalid")
        observed = Outcome("normal-exit" if value["result"] == 0 else
                           "infrastructure-failed" if self.running else "startup-failed",
                           value["result"], value["signal"], value["cleanup"])
        # An already reported primary result precedes compositor teardown.
        if observed.result and self.outcome is None:
            self.outcome = observed
            self.begin_cleanup()
        if observed.cleanup == "failed":
            self.cleanup_failed = True
            if self.outcome is not None:
                self.outcome = self.outcome.cleanup_failed()

    def service(self):
        """Called from the network supervisor; never block its lifecycle loop."""
        if self.stop_signal is not None:
            raise InterruptedError("managed compatibility stop requested")
        now = time.monotonic()
        verify_lock_entry(self.lock_fd, self.directory / "instance.lock")
        endpoint = (self.directory / "instance.sock").lstat()
        if self.endpoint_identity != (endpoint.st_dev, endpoint.st_ino):
            raise ProtocolError("coordinator endpoint was replaced")
        for _ in range(8):
            try:
                client, _ = self.listener.accept()
            except BlockingIOError:
                break
            client.setblocking(False)
            if len(self.clients) >= 8 or peer_credentials(client)[1] != os.getuid():
                client.close()
                continue
            try:
                send_packet(client, {"type": "instance", "unit": self.unit, "run_id": self.run_id,
                                    "invocation": self.invocation, "app": self.app, "mode": self.mode})
            except (OSError, ProtocolError):
                client.close()
                continue
            self.clients[client] = now + REQUEST_TIMEOUT
        watched = [*self.clients]
        if self.runtime is not None:
            watched.append(self.runtime)
        readable = select.select(watched, [], [], 0)[0] if watched else []
        # A queued observed application result precedes teardown reports.
        readable.sort(key=lambda channel: channel is not self.runtime)
        for channel in readable:
            for _ in range(16 if channel is self.runtime else 1):
                try:
                    value = receive_packet(channel)
                    if channel is self.runtime:
                        if value == {"type": "running"} and not self.running and self.outcome is None:
                            self.running = True
                        elif value.get("type") == "outcome" and self.outcome is None:
                            self.outcome = Outcome.from_packet(value)
                            self.begin_cleanup()
                        elif set(value) == {"type", "failed"} and value["type"] == "cleanup" and type(value["failed"]) is bool and self.outcome is not None:
                            if value["failed"]:
                                self.outcome = self.outcome.cleanup_failed()
                        elif set(value) == {"type", "id", "accepted"} and value["type"] == "activation":
                            if (type(value["accepted"]) is not bool or not isinstance(value["id"], str)
                                    or re.fullmatch(r"[0-9a-f]{32}", value["id"]) is None):
                                raise ProtocolError("invalid runtime activation acknowledgement")
                            pending = self.requests.pop(value["id"], None)
                            if pending is not None:
                                self._reply(pending, value["accepted"])
                        else:
                            raise ProtocolError("unexpected runtime record")
                    elif value == {"type": "runtime", "run_id": self.run_id} and self.runtime is None:
                        self._require_helper(channel)
                        self.clients.pop(channel)
                        self.runtime = channel
                        send_packet(channel, {"type": "runtime-accepted"})
                    elif value.get("type") == "compositor-outcome":
                        self._require_helper(channel, compositor=True)
                        self._compositor_outcome(value)
                        send_packet(channel, {"type": "compositor-accepted"})
                        self._drop(channel)
                    elif set(value) == {"type", "args"} and value["type"] == "activate":
                        if not isinstance(value["args"], list):
                            raise ProtocolError("invalid activation argument type")
                        arguments = activation_arguments(self.app, value["args"])
                        if self.outcome is not None:
                            self._reply(channel, False)
                        elif not arguments:
                            self._reply(channel, True)
                        elif not self.running or self.runtime is None:
                            self._reply(channel, False)
                        elif len(self.requests) >= 8:
                            self._reply(channel, False)
                        else:
                            request = uuid.uuid4().hex
                            send_packet(self.runtime, {"type": "activate", "id": request, "args": arguments})
                            self.requests[request] = channel
                    else:
                        self._reply(channel, False)
                except (OSError, ValueError, ProtocolError):
                    if channel is self.runtime:
                        channel.close()
                        self.runtime = None
                        if self.outcome is None:
                            raise ProtocolError("trusted runtime channel failed") from None
                    else:
                        self._reply(channel, False)
                if channel is not self.runtime or not select.select([channel], [], [], 0)[0]:
                    break
        for channel, deadline in tuple(self.clients.items()):
            if now >= deadline:
                self._reply(channel, False)
                for key, pending in tuple(self.requests.items()):
                    if pending is channel:
                        del self.requests[key]

    def __exit__(self, *_):
        for channel in tuple(self.clients):
            self._reply(channel, False)
        if self.runtime is not None:
            self.runtime.close()
        if self.listener is not None:
            self.listener.close()
            path = self.directory / "instance.sock"
            try:
                metadata = path.lstat()
                if self.endpoint_identity == (metadata.st_dev, metadata.st_ino):
                    path.unlink()
                else:
                    self.cleanup_failed = True
            except OSError:
                self.cleanup_failed = True
        if self.lock_fd is not None:
            os.close(self.lock_fd)
        for signum, handler in self.handlers.items():
            signal.signal(signum, handler)
