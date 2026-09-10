"""Capability gates for ownership-sensitive installer integration tests.

The production helpers intentionally reject credential and APT paths whose
ancestors are not owned by the installer UID (or root where documented). Some
sandbox runtimes remap ``/`` and ``/tmp`` to an overflow UID, so those tests
cannot construct a path that satisfies the real contract. Keep production
checks fail-closed and report the unavailable fixture as an explicit skip.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest


def _temporary_ancestry_capability(
    *, allow_root_owner: bool, include_root: bool, contract: str
) -> tuple[bool, str]:
    current_uid = os.geteuid()
    path = Path(os.path.abspath(tempfile.gettempdir()))

    while True:
        if path == Path("/") and not include_root:
            return True, ""
        try:
            metadata = path.lstat()
        except OSError as exc:
            return False, f"cannot exercise {contract}: cannot inspect {path}: {exc}"
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            return False, f"cannot exercise {contract}: {path} is not a real directory"

        accepted_owners = {current_uid}
        if allow_root_owner:
            accepted_owners.add(0)
        if metadata.st_uid not in accepted_owners:
            expected = "root or the current UID" if allow_root_owner else "the installer UID"
            return False, (
                f"cannot exercise {contract}: {path} is owned by UID {metadata.st_uid}, "
                f"not {expected}"
            )

        mode = stat.S_IMODE(metadata.st_mode)
        if mode & 0o022 and not mode & stat.S_ISVTX:
            return False, (
                f"cannot exercise {contract}: {path} is writable by other users "
                "without sticky protection"
            )
        if path == Path("/"):
            return True, ""
        path = path.parent


_credential_ok, _credential_reason = _temporary_ancestry_capability(
    allow_root_owner=True,
    include_root=True,
    contract="trusted initrd credential ancestry",
)
skip_unless_trusted_credential_ancestry = unittest.skipUnless(
    _credential_ok, _credential_reason
)

_installer_apt_ok, _installer_apt_reason = _temporary_ancestry_capability(
    allow_root_owner=False,
    include_root=False,
    contract="installer-owned APT publication ancestry",
)
skip_unless_installer_apt_ancestry = unittest.skipUnless(
    _installer_apt_ok, _installer_apt_reason
)



def _socket_capability(*, family: int, contract: str) -> tuple[bool, str]:
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            if family == socket.AF_INET:
                probe.bind(("127.0.0.1", 0))
                probe.listen(1)
            else:
                with tempfile.TemporaryDirectory(prefix="socket-capability-") as temporary:
                    probe.bind(str(Path(temporary) / "socket"))
                    probe.listen(1)
    except OSError as exc:
        return False, f"cannot exercise {contract}: {type(exc).__name__}: {exc}"
    return True, ""


def _process_tree_capability() -> tuple[bool, str]:
    try:
        status = Path("/proc/self/status").read_text().splitlines()
        proc_pid = int(next(line.split()[1] for line in status if line.startswith("Pid:")))
    except (OSError, ValueError, StopIteration) as exc:
        return False, f"cannot exercise process-tree supervision: cannot inspect /proc/self: {exc}"
    runtime_pid = os.getpid()
    if proc_pid != runtime_pid:
        return False, (
            "cannot exercise process-tree supervision: os.getpid() reports "
            f"{runtime_pid} while /proc/self exposes outer PID {proc_pid}"
        )
    return True, ""


_loopback_ok, _loopback_reason = _socket_capability(
    family=socket.AF_INET,
    contract="loopback HTTP fixtures",
)
skip_unless_loopback_inet = unittest.skipUnless(_loopback_ok, _loopback_reason)


def require_loopback_inet() -> None:
    if not _loopback_ok:
        raise unittest.SkipTest(_loopback_reason)


_unix_socket_ok, _unix_socket_reason = _socket_capability(
    family=socket.AF_UNIX,
    contract="filesystem Unix-socket fixtures",
)
skip_unless_filesystem_unix_socket = unittest.skipUnless(
    _unix_socket_ok, _unix_socket_reason
)

_process_tree_ok, _process_tree_reason = _process_tree_capability()
skip_unless_process_tree_visibility = unittest.skipUnless(
    _process_tree_ok, _process_tree_reason
)
