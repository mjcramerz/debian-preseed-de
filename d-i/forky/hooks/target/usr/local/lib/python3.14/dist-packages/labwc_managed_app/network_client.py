"""Unprivileged, lifetime-bound client for the managed kernel network service."""

from __future__ import annotations

import array
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import select
import socket
import stat
import struct

from .integrity import IntegrityError, require_managed_module, system_owner

SOCKET_PATH = "/run/app-veth/control.sock"
DNS_ADDRESS = "10.0.2.3"
RESOLVER_CONFIGURATION = f"nameserver {DNS_ADDRESS}\noptions timeout:2 attempts:3\n"
STUB_RESOLVER_PATH = "/run/systemd/resolve/stub-resolv.conf"
CODEX_SOCKET_ROOT = Path("/data/codex/sockets")
CODEX_SOCKET_NAMES = (
    "app-server-backend.sock",
    "app-server-control.sock",
    "codex-mcp.sock",
)
CODEX_SOCKET_DAEMON_ROOT = Path("/tmp")
CODEX_SOCKET_DAEMON_NAME = re.compile(r"codex-daemon-[0-9]+")


def _configuration() -> dict:
    # Load lazily so Podman's installer-time adapter probe needs only its
    # minimal client package, before the security stage publishes this policy.
    owner = system_owner()
    try:
        require_managed_module(Path(__file__).parent.parent / "app_veth_policy.py", owner=owner)
        from app_veth_policy import read_configuration
        return read_configuration(owner_uid=owner[0])
    except (OSError, ValueError) as exc:
        raise IntegrityError(f"managed application network policy is unavailable or invalid: {exc}") from exc


def configured_network_policy(app: str) -> dict | None:
    return _configuration()["apps"].get(app)


def network_enabled(app: str) -> bool:
    policy = configured_network_policy(app)
    return policy is not None and policy["network"]


def configured_executable_application(executable: str) -> str | None:
    executable = os.path.realpath(executable)
    matches = [name for name, policy in _configuration()["apps"].items()
               if any(executable == os.path.realpath(path) for path in policy["executables"])]
    if len(matches) > 1:
        raise ValueError("executable matches more than one application network policy")
    return matches[0] if matches else None


def pin_sandbox_init(pid: int) -> int:
    """Pin only the init of a separate PID namespace, never a host process."""
    pidfd = os.pidfd_open(pid)
    namespace_fd = None
    try:
        namespace_fd = os.open(f"/proc/{pid}/ns/pid", os.O_RDONLY | os.O_CLOEXEC)
        namespace = os.fstat(namespace_fd)
        current = os.stat("/proc/self/ns/pid")
        if (namespace.st_dev, namespace.st_ino) == (current.st_dev, current.st_ino):
            raise ValueError("Bubblewrap did not create a separate PID namespace")
        with open(f"/proc/{pid}/status", "rb") as source:
            status = source.read(65537)
        if len(status) > 65536:
            raise ValueError("oversized Bubblewrap process status")
        identities = [line.split()[1:] for line in status.splitlines() if line.startswith(b"NSpid:")]
        if len(identities) != 1 or len(identities[0]) < 2 or identities[0][-1] != b"1":
            raise ValueError("Bubblewrap child is not its private PID namespace init")
        if select.select([pidfd], [], [], 0)[0]:
            raise ValueError("Bubblewrap PID namespace init has already exited")
        return pidfd
    except BaseException:
        os.close(pidfd)
        raise
    finally:
        if namespace_fd is not None:
            os.close(namespace_fd)


def resolver_configuration() -> str:
    """Keep resolved's search domains while directing every query to its stub.

    Only search suffixes are imported. Nameservers and resolver options cannot
    redirect queries away from the broker's systemd-resolved listener.
    """
    try:
        fd = os.open(STUB_RESOLVER_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except FileNotFoundError:
        return RESOLVER_CONFIGURATION
    try:
        metadata = os.fstat(fd)
        parent_metadata = Path(STUB_RESOLVER_PATH).parent.lstat()
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or not stat.S_ISDIR(parent_metadata.st_mode)
                or parent_metadata.st_mode & 0o022
                or (metadata.st_uid, metadata.st_gid)
                   != (parent_metadata.st_uid, parent_metadata.st_gid)
                or metadata.st_mode & 0o022 or metadata.st_size > 65536):
            raise ValueError("unsafe systemd-resolved search-domain file")
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized systemd-resolved search-domain file")
        domains = []
        for line in raw.decode("utf-8").splitlines():
            words = line.split("#", 1)[0].split()
            if not words or words[0] != "search":
                continue
            domains = ["." if word == "." else word.encode("idna").decode("ascii") for word in words[1:]]
            if len(domains) > 32:
                raise ValueError("too many systemd-resolved search domains")
            for domain in domains:
                if domain == ".":
                    continue  # resolved emits the DNS root for an empty search list.
                labels = (domain[:-1] if domain.endswith(".") else domain).split(".")
                if (len(domain) > 254 or any(re.fullmatch(
                        r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?", label) is None
                        for label in labels)):
                    raise ValueError("invalid systemd-resolved search domain")
        suffixes = "search " + " ".join(domains) + "\n" if domains else ""
        return RESOLVER_CONFIGURATION + suffixes
    finally:
        os.close(fd)


def control_socket_owner() -> int:
    """Authenticate host-root ownership even inside Podman's user namespace."""
    owner = system_owner()
    for path, kind, mode in (
            (Path("/run"), stat.S_ISDIR, None),
            (Path("/run/app-veth"), stat.S_ISDIR, 0o755),
            (Path(SOCKET_PATH), stat.S_ISSOCK, 0o666)):
        metadata = path.lstat()
        if (not kind(metadata.st_mode) or (metadata.st_uid, metadata.st_gid) != owner
                or (mode is None and metadata.st_mode & 0o022)
                or (mode is not None and stat.S_IMODE(metadata.st_mode) != mode)):
            raise ValueError("unsafe managed network service endpoint")
    return owner[0]


def podman_socket_arguments() -> list[str]:
    """Export the existing trusted operator API into a sandbox's private /run."""
    if not Path("/etc/podman-devops/client.conf").exists():
        return []
    account = pwd.getpwnam("devops")
    directory = Path("/run/podman-devops")
    parent = directory.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != account.pw_uid
            or stat.S_IMODE(parent.st_mode) != 0o710):
        raise ValueError("unsafe managed Podman runtime directory")
    path = directory / "podman.sock"
    info = path.lstat()
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != account.pw_uid
            or info.st_gid != account.pw_gid or stat.S_IMODE(info.st_mode) != 0o660):
        raise ValueError("unsafe managed Podman API socket")
    return ["--dir", str(directory), "--bind", str(path), str(path)]


def codex_socket_arguments() -> list[str]:
    """Bind the managed Codex control/MCP endpoints into a private bwrap root.

    The app-server backend is commonly a symlink into a per-UID directory below
    /tmp. Bind that exact directory because the sandboxes replace /tmp with a
    private tmpfs; binding only the symlink would leave the endpoint dangling.
    Missing endpoints are optional during startup and are left absent. Any
    endpoint that does exist must be a private, same-UID Unix socket.
    """
    root = CODEX_SOCKET_ROOT
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ValueError(f"cannot inspect managed Codex socket directory: {exc}") from exc
    if (stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700):
        raise ValueError("managed Codex socket directory has unsafe ownership or mode")

    arguments: list[str] = []
    daemon_directories: set[Path] = set()
    for name in CODEX_SOCKET_NAMES:
        path = root / name
        try:
            entry = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f"cannot inspect managed Codex socket: {path}: {exc}") from exc

        source = path
        if stat.S_ISLNK(entry.st_mode):
            if name != "app-server-backend.sock":
                raise ValueError(f"managed Codex socket must not be a symlink: {path}")
            resolved = Path(os.path.realpath(path))
            daemon_directory = resolved.parent
            expected_root = CODEX_SOCKET_DAEMON_ROOT
            if (daemon_directory.parent != expected_root
                    or CODEX_SOCKET_DAEMON_NAME.fullmatch(daemon_directory.name) is None):
                raise ValueError(f"managed Codex backend socket escapes its per-UID runtime: {path}")
            try:
                entry = resolved.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise ValueError(f"cannot inspect managed Codex backend socket: {resolved}: {exc}") from exc
            if (stat.S_ISLNK(entry.st_mode) or not stat.S_ISSOCK(entry.st_mode)
                    or entry.st_uid != os.getuid() or entry.st_nlink != 1
                    or stat.S_IMODE(entry.st_mode) & 0o077):
                raise ValueError(f"managed Codex backend socket has unsafe metadata: {resolved}")
            directory_metadata = daemon_directory.lstat()
            if (stat.S_ISLNK(directory_metadata.st_mode) or not stat.S_ISDIR(directory_metadata.st_mode)
                    or directory_metadata.st_uid != os.getuid()
                    or stat.S_IMODE(directory_metadata.st_mode) != 0o700):
                raise ValueError(f"managed Codex backend runtime directory has unsafe metadata: {daemon_directory}")
            daemon_directories.add(daemon_directory)
            continue

        if (not stat.S_ISSOCK(entry.st_mode) or entry.st_uid != os.getuid()
                or entry.st_nlink != 1 or stat.S_IMODE(entry.st_mode) & 0o077):
            raise ValueError(f"managed Codex socket has unsafe metadata: {path}")
        arguments.extend(("--bind", str(source), str(path)))

    for directory in sorted(daemon_directories):
        arguments.extend(("--bind", str(directory), str(directory)))
    return arguments


class Lease:
    """The control socket is owned by the supervisor, never the application."""

    def __init__(self, namespace_fd: int, app: str):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
        try:
            self.socket.settimeout(15)
            expected_uid = control_socket_owner()
            self.socket.connect(SOCKET_PATH)
            _pid, uid, _gid = struct.unpack("3i", self.socket.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            if uid != expected_uid:
                raise ValueError("network service is not owned by root")
            request = json.dumps({"app": app}, separators=(",", ":")).encode("ascii")
            self.socket.sendmsg([request], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                            array.array("i", [namespace_fd]))])
            response, _ancillary, flags, _address = self.socket.recvmsg(4096)
            if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                raise ValueError("oversized network readiness response")
            if not response:
                raise ValueError("network service closed the request before readiness; see managed network log")
            try:
                result = json.loads(response)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid network service response") from exc
            if not isinstance(result, dict) or result.get("ready") is not True:
                if (isinstance(result, dict) and result.get("ready") is False
                        and isinstance(result.get("error"), str)
                        and isinstance(result.get("correlation_id"), str)
                        and re.fullmatch(r"[0-9a-f]{32}", result["correlation_id"])):
                    detail = " ".join(result["error"].split())[:512]
                    raise ValueError(f"network service rejected request: {detail} "
                                     f"(correlation {result['correlation_id']})")
                raise ValueError("kernel network setup failed; see managed network log")
            self.address = str(ipaddress.IPv4Address(result["address"]))
            self.gateway = str(ipaddress.IPv4Address(result["gateway"]))
            self.interface = result["interface"]
            if self.interface != "eth0":
                raise ValueError("invalid private interface")
            self.peer_port = result.get("peer_port")
            if self.peer_port is not None and (type(self.peer_port) is not int or not 1024 <= self.peer_port <= 65535):
                raise ValueError("invalid private peer forwarding port")
            self.socket.setblocking(False)
        except BaseException:
            self.socket.close()
            raise

    @classmethod
    def for_pid(cls, pid: int, app: str) -> Lease:
        # The caller pins its blocked child with a pidfd before opening this FD.
        fd = os.open(f"/proc/{pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC)
        try:
            return cls(fd, app)
        finally:
            os.close(fd)

    def check(self) -> None:
        readable, _, _ = select.select([self.socket], [], [], 0)
        if readable:
            raise RuntimeError("kernel network lease ended; stopping the isolated application")

    def close(self) -> None:
        self.socket.close()
