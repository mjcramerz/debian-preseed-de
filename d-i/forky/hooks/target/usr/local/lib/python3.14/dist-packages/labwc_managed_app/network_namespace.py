"""Kernel namespace supervision for Bubblewrap sandboxes."""

from __future__ import annotations

from collections.abc import Callable
import errno
import json
import socket
import os
import select
import signal
import subprocess
import time

from .runtime import fail, managed_subprocess_environment
from .network_client import pin_sandbox_init

BWRAP_INFO_MAX_BYTES = 16_384
BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS = 15
PROCESS_STOP_TIMEOUT_SECONDS = 2
VETH_DNS_ADDRESS = "10.0.2.3"


def veth_resolv_conf() -> str:
    from .network_client import resolver_configuration
    return resolver_configuration()


# EOF on Bubblewrap's block-fd is insufficient authorization to start a payload.
PEER_STARTUP_GATE = (
    "import os,sys; fd=int(sys.argv[1]); marker=os.read(fd,1); os.close(fd); "
    "sys.exit(1) if marker != b'1' else os.execv(sys.argv[2],sys.argv[2:])"
)
DISCORD_RPC_PORTS = tuple(range(6463, 6473))
DISCORD_RPC_GUEST_ADDRESS = "0.0.0.0"
DISCORD_RPC_PORT_OFFSET = 10000


class DiscordRPCRelay:
    """Bounded, nonblocking veth-to-loopback relay inside Discord's namespace."""

    LIMIT = 32
    BUFFER_BYTES = 65536
    IDLE_SECONDS = 60

    def __init__(self):
        self.listeners = {}
        self.peers = {}
        self.buffers = {}
        self.pending = {}
        self.activity = {}
        self.eof = set()
        self.shut = set()
        try:
            for port in DISCORD_RPC_PORTS:
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.listeners[listener] = port
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((DISCORD_RPC_GUEST_ADDRESS, port + DISCORD_RPC_PORT_OFFSET))
                listener.listen(8)
                listener.setblocking(False)
        except BaseException:
            self.close()
            raise

    def _drop(self, channel):
        peer = self.peers.get(channel)
        for item in (channel, peer):
            if item is None:
                continue
            self.peers.pop(item, None)
            self.buffers.pop(item, None)
            self.pending.pop(item, None)
            self.activity.pop(item, None)
            self.eof.discard(item)
            self.shut.discard(item)
            item.close()

    def _accept(self, listener, now):
        for _ in range(4):
            try:
                front, _ = listener.accept()
            except BlockingIOError:
                return
            if len(self.peers) >= self.LIMIT * 2:
                front.close()
                continue
            back = None
            try:
                front.setblocking(False)
                back = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                back.setblocking(False)
                status = back.connect_ex(("127.0.0.1", self.listeners[listener]))
                if status not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK):
                    raise OSError(status, "private RPC listener is not ready")
                self.peers[front], self.peers[back] = back, front
                self.buffers[front], self.buffers[back] = bytearray(), bytearray()
                self.activity[front] = self.activity[back] = now
                if status:
                    self.pending[back] = now + 2
            except OSError:
                front.close()
                if back is not None:
                    back.close()

    def service(self):
        now = time.monotonic()
        for channel, last in tuple(self.activity.items()):
            if (now - last >= self.IDLE_SECONDS
                    or now >= self.pending.get(channel, float("inf"))):
                self._drop(channel)
        readers = [*self.listeners, *(channel for channel, peer in self.peers.items()
                   if channel not in self.eof and channel not in self.pending
                   and len(self.buffers[peer]) < self.BUFFER_BYTES)]
        writers = [channel for channel in self.peers
                   if channel in self.pending or self.buffers[channel]]
        readable, writable, _ = select.select(readers, writers, [], 0)
        for channel in writable:
            if channel not in self.peers:
                continue
            try:
                if channel in self.pending:
                    if channel.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
                        self._drop(channel)
                        continue
                    del self.pending[channel]
                if self.buffers[channel]:
                    count = channel.send(self.buffers[channel])
                    if not count:
                        self._drop(channel)
                        continue
                    del self.buffers[channel][:count]
                    self.activity[channel] = self.activity[self.peers[channel]] = now
            except BlockingIOError:
                pass
            except OSError:
                self._drop(channel)
        for channel in readable:
            if channel in self.listeners:
                self._accept(channel, now)
                continue
            if channel not in self.peers:
                continue
            try:
                peer = self.peers[channel]
                chunk = channel.recv(self.BUFFER_BYTES - len(self.buffers[peer]))
                if chunk:
                    self.buffers[peer].extend(chunk)
                    self.activity[channel] = self.activity[peer] = now
                else:
                    self.eof.add(channel)
            except BlockingIOError:
                pass
            except OSError:
                self._drop(channel)
        for channel, peer in tuple(self.peers.items()):
            if channel not in self.peers:
                continue
            if peer in self.eof and not self.buffers[channel] and channel not in self.pending and channel not in self.shut:
                try:
                    channel.shutdown(socket.SHUT_WR)
                    self.shut.add(channel)
                except OSError:
                    self._drop(channel)
                    continue
            if channel in self.eof and peer in self.eof and not self.buffers[channel] and not self.buffers[peer]:
                self._drop(channel)

    def close(self):
        for channel in tuple(self.peers):
            self._drop(channel)
        for listener in self.listeners:
            listener.close()
        self.listeners.clear()


def close_file_descriptor(file_descriptor: int | None) -> None:
    if file_descriptor is None:
        return
    try:
        os.close(file_descriptor)
    except OSError:
        pass


def _stop_subprocess(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=PROCESS_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=PROCESS_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def _read_bwrap_sandbox_pid(
    info_fd: int,
    bwrap_process: subprocess.Popen,
    runtime_check: Callable[[], None] | None = None,
) -> int:
    deadline = time.monotonic() + BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS
    payload = bytearray()

    while True:
        if runtime_check is not None:
            runtime_check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            status = bwrap_process.poll()
            if status is not None:
                fail(
                    "Bubblewrap exited before reporting a sandbox process ID "
                    f"(status {status})"
                )
            fail("Bubblewrap did not report a sandbox process ID before timeout")

        try:
            readable, _, _ = select.select(
                [info_fd],
                [],
                [],
                min(remaining, 0.25),
            )
        except InterruptedError:
            continue
        if not readable:
            status = bwrap_process.poll()
            if status is not None:
                fail(
                    "Bubblewrap exited before reporting a sandbox process ID "
                    f"(status {status})"
                )
            continue

        remaining_bytes = BWRAP_INFO_MAX_BYTES + 1 - len(payload)
        if remaining_bytes <= 0:
            fail("Bubblewrap sandbox information exceeds the managed size limit")
        try:
            chunk = os.read(info_fd, min(4_096, remaining_bytes))
        except InterruptedError:
            continue
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > BWRAP_INFO_MAX_BYTES:
            fail("Bubblewrap sandbox information exceeds the managed size limit")

    if not payload:
        fail("Bubblewrap returned empty sandbox information")
    try:
        information = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        fail("Bubblewrap returned invalid sandbox information")
    if not isinstance(information, dict):
        fail("Bubblewrap sandbox information must be a JSON object")

    sandbox_pid = information.get("child-pid")
    if (
        isinstance(sandbox_pid, bool)
        or not isinstance(sandbox_pid, int)
        or sandbox_pid <= 1
    ):
        fail("Bubblewrap returned an invalid sandbox process ID")
    if bwrap_process.poll() is not None:
        fail(
            "Bubblewrap exited while preparing the isolated network namespace "
            f"(status {bwrap_process.returncode})"
        )
    return sandbox_pid


def wait_for_payload(sandbox: subprocess.Popen, lease) -> int:
    """Wait for process exit or lease loss without periodic wakeups."""
    status = sandbox.poll()
    if status is not None:
        return status
    if lease is None:
        return sandbox.wait()
    lease.check()
    try:
        monitor_fd = os.pidfd_open(sandbox.pid)
    except ProcessLookupError:
        return sandbox.wait()
    try:
        while True:
            ready, _, _ = select.select([monitor_fd, lease.socket], [], [])
            lease.check()
            if monitor_fd in ready:
                return sandbox.wait()
    finally:
        close_file_descriptor(monitor_fd)


def run_veth_sandbox(
    command: list[str], payload_argv: list[str], temp_root: str,
    inherited_fds: tuple[int, ...], *, app: str,
    pre_payload_check: Callable[[], None] | None = None,
    runtime_check: Callable[[], None] | None = None,
    cleanup_deadline: Callable[[], float] | None = None,
    cleanup_failure: Callable[[], None] | None = None,
    on_network_ready: Callable | None = None,
    network: bool = True,
) -> int:
    """Supervise the private PID namespace, with an optional veth lease."""
    from .network_client import Lease
    descriptors = set()
    sandbox = None
    pidfd = None
    lease = None
    try:
        info_read, info_write = os.pipe()
        descriptors.update((info_read, info_write))
        block_read, block_write = os.pipe()
        descriptors.update((block_read, block_write))
        gate_read, gate_write = os.pipe()
        descriptors.update((gate_read, gate_write))
        argv = [*command, "--info-fd", str(info_write), "--block-fd", str(block_read),
                "/usr/bin/python3", "-I", "-B", "-c", PEER_STARTUP_GATE,
                str(gate_read), *payload_argv]
        sandbox = subprocess.Popen(argv, cwd="/", env=managed_subprocess_environment(),
            pass_fds=tuple(dict.fromkeys((*inherited_fds, info_write, block_read, gate_read))))
        for fd in (info_write, block_read, gate_read):
            close_file_descriptor(fd)
            descriptors.remove(fd)
        pid = _read_bwrap_sandbox_pid(info_read, sandbox, runtime_check)
        pidfd = pin_sandbox_init(pid)
        if network:
            lease = Lease.for_pid(pid, app)
        if on_network_ready is not None:
            if lease is None:
                raise ValueError("network readiness callback requires a lease")
            on_network_ready(lease)
        if pre_payload_check is not None:
            pre_payload_check()
        if runtime_check is not None:
            runtime_check()
        if lease is not None:
            lease.check()
        if sandbox.poll() is not None:
            fail("Bubblewrap stopped before kernel network readiness")
        os.write(block_write, b"1")
        os.write(gate_write, b"1")
        for fd in (block_write, gate_write, info_read):
            close_file_descriptor(fd)
            descriptors.remove(fd)
        if runtime_check is None:
            return wait_for_payload(sandbox, lease)
        while True:
            if runtime_check is not None:
                runtime_check()
            status = sandbox.poll()
            if status is not None:
                return status
            if lease is not None:
                lease.check()
            try:
                return sandbox.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                continue
    except (OSError, ValueError, RuntimeError) as exc:
        fail(f"kernel private network failed: {exc}")
    finally:
        try:
            # Bubblewrap's monitor reports the initial payload's exit while
            # its PID-1 reaper can still own detached descendants. End the
            # pinned namespace on every exit, including normal completion.
            # Killing its init makes the kernel terminate every process in
            # that PID namespace; a recycled numeric PID is never targeted.
            if pidfd is not None:
                try:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        finally:
            cleanup_ok = True
            try:
                deadline = cleanup_deadline() if cleanup_deadline is not None else None
                if deadline is not None:
                    from .compat_protocol import stop_processes
                    cleanup_ok = stop_processes([sandbox], deadline)
                else:
                    _stop_subprocess(sandbox)
            finally:
                for fd in descriptors:
                    close_file_descriptor(fd)
                close_file_descriptor(pidfd)
                if lease is not None:
                    lease.close()
            if not cleanup_ok and cleanup_failure is not None:
                cleanup_failure()
