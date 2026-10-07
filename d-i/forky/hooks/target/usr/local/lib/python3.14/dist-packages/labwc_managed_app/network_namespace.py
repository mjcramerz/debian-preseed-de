"""Private network namespace supervision for Bubblewrap sandboxes."""

from __future__ import annotations

from collections.abc import Callable

import errno
import ipaddress
import json
import socket
import os
import select
import signal
import subprocess
import time

from .runtime import fail, managed_subprocess_environment


BWRAP_INFO_MAX_BYTES = 16_384
BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS = 15
SLIRP4NETNS_BINARY = "/usr/bin/slirp4netns"
SLIRP4NETNS_DIAGNOSTIC_MAX_BYTES = 4_096
SLIRP4NETNS_DNS_ADDRESS = "10.0.2.3"
SLIRP4NETNS_MTU = 65_520
SLIRP4NETNS_STOP_TIMEOUT_SECONDS = 2
SLIRP4NETNS_TAP_NAME = "tap0"

# Bubblewrap's block-fd accepts EOF as readiness. In peer mode a second,
# inherited pipe authorizes exec only on an explicit marker; early setup
# failures and supervisor death therefore cannot start the torrent payload.
# This fixed code runs after namespace setup and closes its only extra fd
# before replacing itself, so it adds no long-lived process.
PEER_STARTUP_GATE = (
    "import os,sys; fd=int(sys.argv[1]); marker=os.read(fd,1); os.close(fd); "
    "sys.exit(1) if marker != b'1' else os.execv(sys.argv[2],sys.argv[2:])"
)


def validate_peer_forward(host_address: str, port: int) -> str:
    if not isinstance(host_address, str):
        fail("invalid private peer forwarding address")
    try:
        address = ipaddress.IPv4Address(host_address)
    except (ValueError, TypeError):
        fail("invalid private peer forwarding address")
    if (address.is_loopback or address.is_unspecified or address.is_link_local
            or address.is_multicast or address.is_reserved
            or type(port) is not int or not 1024 <= port <= 65535):
        fail("invalid private peer forwarding policy")
    return str(address)


def configure_peer_forward(api_path: str, host_address: str, port: int) -> None:
    """Forward both torrent transports before releasing the private payload."""
    address = validate_peer_forward(host_address, port)
    os.chmod(api_path, 0o600)
    for protocol in ("tcp", "udp"):
        request = {"execute": "add_hostfwd", "arguments": {
            "proto": protocol, "host_addr": address, "host_port": port,
            "guest_addr": "10.0.2.100", "guest_port": port,
        }}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.settimeout(2)
                channel.connect(api_path)
                channel.sendall(json.dumps(request).encode("ascii"))
                channel.shutdown(socket.SHUT_WR)
                response = bytearray()
                while len(response) <= 4096:
                    chunk = channel.recv(4097 - len(response))
                    if not chunk:
                        break
                    response.extend(chunk)
                value = json.loads(response) if len(response) <= 4096 else None
            if not isinstance(value, dict) or "return" not in value or "error" in value:
                raise ValueError("host forwarding was rejected")
        except (OSError, ValueError) as exc:
            fail(f"private peer {protocol} port {port} forwarding failed; no application was started: {exc}")

# slirp cannot reach a service bound to the guest's 127.0.0.1 directly.
# Its host forwards target these private TAP listeners; only this supervisor
# connects onward to Discord's namespace-local RPC ports. No namespace entry,
# host sockets in the payload, threads or additional long-lived processes.
DISCORD_RPC_PORTS = tuple(range(6463, 6473))
DISCORD_RPC_GUEST_ADDRESS = "10.0.2.100"
DISCORD_RPC_PORT_OFFSET = 10000


def configure_discord_rpc(api_path: str, *, runtime_check: Callable[[], None] | None = None) -> None:
    """Configure all ports before releasing the application; failure is atomic
    with respect to its lifetime because the caller tears down slirp on error.
    """
    os.chmod(api_path, 0o600)
    for port in DISCORD_RPC_PORTS:
        if runtime_check is not None:
            runtime_check()
        request = {"execute": "add_hostfwd", "arguments": {
            "proto": "tcp", "host_addr": "127.0.0.1", "host_port": port,
            "guest_addr": DISCORD_RPC_GUEST_ADDRESS,
            "guest_port": port + DISCORD_RPC_PORT_OFFSET,
        }}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.settimeout(2)
                channel.connect(api_path)
                channel.sendall(json.dumps(request).encode("ascii"))
                channel.shutdown(socket.SHUT_WR)
                response = bytearray()
                while len(response) <= 4096:
                    chunk = channel.recv(4097 - len(response))
                    if not chunk:
                        break
                    response.extend(chunk)
                value = json.loads(response) if len(response) <= 4096 else None
            if not isinstance(value, dict) or "return" not in value or "error" in value:
                raise ValueError("host forwarding was rejected")
        except (OSError, ValueError):
            fail(f"Discord loopback RPC port {port} is unavailable; no application was started")


class DiscordRPCRelay:
    """Bounded, nonblocking TAP-to-loopback relay inside Discord's namespace."""

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
        process.wait(timeout=SLIRP4NETNS_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=SLIRP4NETNS_STOP_TIMEOUT_SECONDS)
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


def _slirp4netns_diagnostic(stderr_handle) -> str:
    try:
        stderr_handle.flush()
        stderr_handle.seek(0)
        payload = stderr_handle.read(SLIRP4NETNS_DIAGNOSTIC_MAX_BYTES + 1)
    except OSError:
        return ""
    truncated = len(payload) > SLIRP4NETNS_DIAGNOSTIC_MAX_BYTES
    payload = payload[:SLIRP4NETNS_DIAGNOSTIC_MAX_BYTES]
    message = " ".join(payload.decode("utf-8", errors="replace").split())
    if truncated:
        message = f"{message} [truncated]" if message else "[truncated]"
    return message


def _slirp4netns_exit_message(
    status: int,
    stderr_handle,
    context: str,
) -> str:
    diagnostic = _slirp4netns_diagnostic(stderr_handle)
    suffix = f": {diagnostic}" if diagnostic else ""
    return f"slirp4netns exited {context} (status {status}){suffix}"


def _wait_for_slirp4netns_ready(
    ready_fd: int,
    bwrap_process: subprocess.Popen,
    slirp_process: subprocess.Popen,
    stderr_handle,
    runtime_check: Callable[[], None] | None = None,
) -> None:
    deadline = time.monotonic() + BWRAP_NETWORK_SETUP_TIMEOUT_SECONDS

    while True:
        if runtime_check is not None:
            runtime_check()
        bwrap_status = bwrap_process.poll()
        if bwrap_status is not None:
            if runtime_check is not None:
                from .compat_protocol import RequiredComponentError
                raise RequiredComponentError(bwrap_status)
            fail(
                "Bubblewrap exited before isolated network setup completed "
                f"(status {bwrap_status})"
            )
        slirp_status = slirp_process.poll()
        if slirp_status is not None:
            if runtime_check is not None:
                from .compat_protocol import RequiredComponentError
                raise RequiredComponentError(slirp_status)
            fail(
                _slirp4netns_exit_message(
                    slirp_status,
                    stderr_handle,
                    "before configuring the isolated network namespace",
                )
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            fail(
                "slirp4netns did not configure the isolated network namespace "
                "before timeout"
            )
        try:
            readable, _, _ = select.select(
                [ready_fd],
                [],
                [],
                min(remaining, 0.25),
            )
        except InterruptedError:
            continue
        if not readable:
            continue
        try:
            readiness = os.read(ready_fd, 2)
        except InterruptedError:
            continue
        if readiness != b"1":
            try:
                slirp_status = slirp_process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                slirp_status = None
            if slirp_status is not None:
                if runtime_check is not None:
                    from .compat_protocol import RequiredComponentError
                    raise RequiredComponentError(slirp_status)
                fail(
                    _slirp4netns_exit_message(
                        slirp_status,
                        stderr_handle,
                        "before configuring the isolated network namespace",
                    )
                )
            fail("slirp4netns returned an invalid readiness marker")
        return


def _wait_for_bwrap_with_slirp4netns(
    bwrap_process: subprocess.Popen,
    slirp_process: subprocess.Popen,
    stderr_handle,
    runtime_check: Callable[[], None] | None = None,
) -> int:
    while True:
        if runtime_check is not None:
            runtime_check()
        # Payload completion precedes intentional slirp exit-fd teardown.
        # A helper observed after that completion is not a new first cause.
        bwrap_status = bwrap_process.poll()
        if bwrap_status is not None:
            return bwrap_status
        slirp_status = slirp_process.poll()
        if slirp_status is not None:
            if runtime_check is not None:
                from .compat_protocol import RequiredComponentError
                raise RequiredComponentError(slirp_status)
            fail(
                _slirp4netns_exit_message(
                    slirp_status,
                    stderr_handle,
                    "while the managed application sandbox was running",
                )
            )
        try:
            bwrap_status = bwrap_process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            continue
        return bwrap_status


def run_slirp4netns_sandbox(
    command: list[str],
    payload_argv: list[str],
    temp_root: str,
    inherited_fds: tuple[int, ...],
    *,
    slirp_binary: str,
    pre_payload_check: Callable[[], None] | None = None,
    runtime_check: Callable[[], None] | None = None,
    cleanup_deadline: Callable[[], float] | None = None,
    cleanup_failure: Callable[[], None] | None = None,
    discord_rpc: bool = False,
    peer_forward: tuple[str, int] | None = None,
) -> int:
    if peer_forward is not None:
        # Validate before creating namespaces or listeners. The source address
        # pins outbound traffic to the same active route as the host forwards.
        validate_peer_forward(*peer_forward)
        if discord_rpc:
            fail("invalid private peer forwarding policy")
    info_read_fd = None
    info_write_fd = None
    block_read_fd = None
    block_write_fd = None
    ready_read_fd = None
    ready_write_fd = None
    exit_read_fd = None
    exit_write_fd = None
    gate_read_fd = None
    gate_write_fd = None
    bwrap_process = None
    slirp_process = None
    stderr_handle = None
    sandbox_pidfd = None
    payload_released = False
    api_path = os.path.join(temp_root, "slirp4netns.api") if discord_rpc or peer_forward is not None else None

    try:
        info_read_fd, info_write_fd = os.pipe()
        block_read_fd, block_write_fd = os.pipe()
        ready_read_fd, ready_write_fd = os.pipe()
        exit_read_fd, exit_write_fd = os.pipe()

        sandbox_argv = payload_argv
        gate_fds = ()
        if peer_forward is not None:
            gate_read_fd, gate_write_fd = os.pipe()
            gate_fds = (gate_read_fd,)
            sandbox_argv = ["/usr/bin/python3", "-I", "-B", "-c", PEER_STARTUP_GATE,
                            str(gate_read_fd), *payload_argv]

        bwrap_command = [
            *command,
            "--info-fd",
            str(info_write_fd),
            "--block-fd",
            str(block_read_fd),
            *sandbox_argv,
        ]
        bwrap_pass_fds = tuple(
            dict.fromkeys(
                (*inherited_fds, info_write_fd, block_read_fd, *gate_fds)
            )
        )
        bwrap_process = subprocess.Popen(
            bwrap_command,
            cwd="/",
            env=managed_subprocess_environment(),
            pass_fds=bwrap_pass_fds,
        )
        close_file_descriptor(info_write_fd)
        info_write_fd = None
        close_file_descriptor(block_read_fd)
        block_read_fd = None
        close_file_descriptor(gate_read_fd)
        gate_read_fd = None

        sandbox_pid = _read_bwrap_sandbox_pid(
            info_read_fd,
            bwrap_process,
            runtime_check,
        )
        close_file_descriptor(info_read_fd)
        info_read_fd = None
        if peer_forward is not None:
            # Bubblewrap's block-fd also releases on EOF. Pin the namespace
            # init so failed peer setup can kill it BEFORE closing that pipe,
            # without signalling a PID that could have been reused.
            try:
                sandbox_pidfd = os.pidfd_open(sandbox_pid)
            except OSError as exc:
                fail(f"cannot pin the private peer namespace for safe cancellation: {exc}")

        stderr_path = os.path.join(temp_root, "slirp4netns.stderr")
        stderr_handle = open(stderr_path, "w+b", buffering=0)
        os.chmod(stderr_path, 0o600)
        slirp_process = subprocess.Popen(
            [
                slirp_binary,
                "--configure",
                f"--mtu={SLIRP4NETNS_MTU}",
                "--disable-host-loopback",
                *([f"--outbound-addr={peer_forward[0]}"] if peer_forward is not None else []),
                *(["--api-socket", api_path] if api_path else []),
                "--ready-fd",
                str(ready_write_fd),
                "--exit-fd",
                str(exit_read_fd),
                str(sandbox_pid),
                SLIRP4NETNS_TAP_NAME,
            ],
            cwd="/",
            env=managed_subprocess_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            pass_fds=(ready_write_fd, exit_read_fd),
        )
        close_file_descriptor(ready_write_fd)
        ready_write_fd = None
        close_file_descriptor(exit_read_fd)
        exit_read_fd = None

        _wait_for_slirp4netns_ready(
            ready_read_fd,
            bwrap_process,
            slirp_process,
            stderr_handle,
            runtime_check,
        )
        close_file_descriptor(ready_read_fd)
        ready_read_fd = None
        if discord_rpc and api_path is not None:
            configure_discord_rpc(api_path, runtime_check=runtime_check)
        elif peer_forward is not None and api_path is not None:
            configure_peer_forward(api_path, *peer_forward)
        if pre_payload_check is not None:
            pre_payload_check()
        bwrap_status = bwrap_process.poll()
        if bwrap_status is not None:
            if runtime_check is not None:
                from .compat_protocol import RequiredComponentError
                raise RequiredComponentError(bwrap_status)
            fail(
                "Bubblewrap exited after isolated network setup completed "
                f"but before payload release (status {bwrap_status})"
            )
        slirp_status = slirp_process.poll()
        if slirp_status is not None:
            if runtime_check is not None:
                from .compat_protocol import RequiredComponentError
                raise RequiredComponentError(slirp_status)
            fail(
                _slirp4netns_exit_message(
                    slirp_status,
                    stderr_handle,
                    "after configuring the isolated network namespace "
                    "but before payload release",
                )
            )
        try:
            os.write(block_write_fd, b"1")
            if gate_write_fd is not None:
                os.write(gate_write_fd, b"1")
            payload_released = True
        except (BrokenPipeError, OSError):
            status = bwrap_process.poll()
            suffix = f" (status {status})" if status is not None else ""
            fail(f"cannot release the configured Bubblewrap sandbox{suffix}")
        close_file_descriptor(block_write_fd)
        block_write_fd = None
        close_file_descriptor(gate_write_fd)
        gate_write_fd = None

        return _wait_for_bwrap_with_slirp4netns(
            bwrap_process,
            slirp_process,
            stderr_handle,
            runtime_check,
        )
    finally:
        if sandbox_pidfd is not None:
            try:
                if not payload_released:
                    signal.pidfd_send_signal(sandbox_pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                close_file_descriptor(sandbox_pidfd)
        deadline = cleanup_deadline() if cleanup_deadline is not None else None
        cleanup_ok = True
        if deadline is not None:
            from .compat_protocol import stop_processes
            if not stop_processes([bwrap_process], deadline):
                cleanup_ok = False
        elif bwrap_process is not None and bwrap_process.poll() is None:
            _stop_subprocess(bwrap_process)
        for file_descriptor in (
            info_read_fd,
            info_write_fd,
            block_read_fd,
            block_write_fd,
            ready_read_fd,
            ready_write_fd,
            exit_read_fd,
            gate_read_fd,
            gate_write_fd,
        ):
            close_file_descriptor(file_descriptor)
        close_file_descriptor(exit_write_fd)
        if deadline is not None:
            if not stop_processes([slirp_process], deadline):
                cleanup_ok = False
        elif slirp_process is not None and slirp_process.poll() is None:
            try:
                slirp_process.wait(timeout=SLIRP4NETNS_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                _stop_subprocess(slirp_process)
        if stderr_handle is not None:
            stderr_handle.close()
        if not cleanup_ok and cleanup_failure is not None:
            cleanup_failure()
