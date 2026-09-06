"""Deterministic synthetic host identity for privacy sandboxes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import os
import re
import stat
from typing import NoReturn
import uuid

from .mounts import add_dir_chain


MANAGED_CODEX_HOME = "/data/codex/usr/home"
MANAGED_CODEX_INSTALLATION_ID = f"{MANAGED_CODEX_HOME}/installation_id"
HOST_MACHINE_ID_PATH = "/etc/machine-id"
MAX_HOST_MACHINE_ID_BYTES = 64
SYNTHETIC_IDENTITY_DOMAIN = b"labwc-managed-app/chatgpt-identity/v1"


@dataclass(frozen=True)
class IdentityRuntime:
    """Validated facade operations used while creating identity files."""

    fail: Callable[[str], NoReturn]
    require_root_owned_regular_file: Callable[[str, str], str]
    filtered_resolv_conf: Callable[[], str]
    validate_absolute_path: Callable[[str, str], str]


def create_synthetic_identity_files(
    temp_root: str,
    home_dir: str,
    *,
    resolv_conf: str | None = None,
    shell_path: str = "/bin/sh",
    runtime: IdentityRuntime,
) -> dict[str, str]:
    if shell_path not in {"/bin/sh", "/bin/zsh"}:
        runtime.fail(f"unsupported synthetic account shell: {shell_path}")
    machine_id_path = runtime.require_root_owned_regular_file(
        "host machine ID",
        HOST_MACHINE_ID_PATH,
    )
    try:
        with open(machine_id_path, encoding="ascii") as handle:
            host_machine_id_text = handle.read(MAX_HOST_MACHINE_ID_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        runtime.fail(f"cannot read host machine ID: {exc}")
    if len(host_machine_id_text) > MAX_HOST_MACHINE_ID_BYTES:
        runtime.fail("host machine ID exceeds the managed size limit")
    host_machine_id = host_machine_id_text.strip()
    if re.fullmatch(r"[0-9a-f]{32}", host_machine_id) is None:
        runtime.fail("host machine ID must contain 32 lowercase hexadecimal characters")

    identity_seed = hashlib.sha256(
        SYNTHETIC_IDENTITY_DOMAIN
        + b"\0"
        + bytes.fromhex(host_machine_id)
        + b"\0"
        + os.getuid().to_bytes(8, byteorder="big", signed=False)
    ).digest()
    machine_id = hashlib.sha256(identity_seed + b"\0machine-id").hexdigest()[:32]
    boot_id = str(
        uuid.UUID(
            bytes=hashlib.sha256(identity_seed + b"\0boot-id").digest()[:16],
            version=5,
        )
    )
    installation_id = str(
        uuid.UUID(
            bytes=hashlib.sha256(
                identity_seed + b"\0installation-id"
            ).digest()[:16],
            version=5,
        )
    )
    hostname = f"chatgpt-{machine_id[:12]}"
    identity = {
        "machine_id": os.path.join(temp_root, "machine-id"),
        "boot_id": os.path.join(temp_root, "boot-id"),
        "installation_id": os.path.join(temp_root, "installation_id"),
        "hostname": os.path.join(temp_root, "hostname"),
        "passwd": os.path.join(temp_root, "passwd"),
        "group": os.path.join(temp_root, "group"),
        "hosts": os.path.join(temp_root, "hosts"),
        "resolv": os.path.join(temp_root, "resolv.conf"),
        "nsswitch": os.path.join(temp_root, "nsswitch.conf"),
        "cmdline": os.path.join(temp_root, "cmdline"),
        "empty": os.path.join(temp_root, "empty"),
        "hostname_value": hostname,
    }
    if resolv_conf is None:
        resolv_conf = runtime.filtered_resolv_conf()
    if (
        not resolv_conf
        or len(resolv_conf.encode("utf-8")) > 4_096
        or "\0" in resolv_conf
    ):
        runtime.fail("synthetic resolver policy is invalid")

    content = {
        "machine_id": f"{machine_id}\n",
        "boot_id": f"{boot_id}\n",
        "installation_id": installation_id,
        "hostname": f"{hostname}\n",
        "passwd": (
            "root:x:0:0:root:/root:/usr/sbin/nologin\n"
            f"developer:x:{os.getuid()}:{os.getgid()}:Managed Developer:{home_dir}:{shell_path}\n"
        ),
        "group": (
            "root:x:0:\n"
            f"developer:x:{os.getgid()}:developer\n"
        ),
        "hosts": (
            "127.0.0.1 localhost\n"
            f"127.0.1.1 {hostname}\n"
            "::1 localhost ip6-localhost ip6-loopback\n"
        ),
        "resolv": resolv_conf,
        "nsswitch": (
            "passwd: files\n"
            "group: files\n"
            "shadow: files\n"
            "gshadow: files\n"
            "hosts: files dns\n"
            "networks: files dns\n"
            "protocols: files\n"
            "services: files\n"
            "ethers: files\n"
            "rpc: files\n"
            "netgroup: files\n"
        ),
        "cmdline": "root=/dev/mapper/managed-root ro quiet\n",
        "empty": "",
    }
    for name, value in content.items():
        with open(identity[name], "w", encoding="utf-8") as handle:
            handle.write(value)
        os.chmod(identity[name], 0o644 if name == "installation_id" else 0o600)
    return identity


def add_synthetic_codex_installation_id_mount(
    command: list[str],
    installation_id_path: str,
    *,
    runtime: IdentityRuntime,
) -> None:
    runtime.validate_absolute_path(
        "synthetic Codex installation id",
        installation_id_path,
    )
    try:
        installation_id_stat = os.lstat(installation_id_path)
    except OSError as exc:
        runtime.fail(f"cannot inspect synthetic Codex installation id: {exc}")
    if (
        stat.S_ISLNK(installation_id_stat.st_mode)
        or not stat.S_ISREG(installation_id_stat.st_mode)
        or installation_id_stat.st_uid != os.getuid()
        or stat.S_IMODE(installation_id_stat.st_mode) != 0o644
    ):
        runtime.fail(
            "synthetic Codex installation id must be a current-user-owned "
            f"regular file with mode 0644: {installation_id_path}"
        )
    command.extend(
        [
            "--bind",
            installation_id_path,
            MANAGED_CODEX_INSTALLATION_ID,
        ]
    )


def add_synthetic_identity_mounts(
    command: list[str],
    identity: dict[str, str],
) -> None:
    add_dir_chain(command, "/var/lib/dbus")
    for source_name, destination in (
        ("machine_id", "/etc/machine-id"),
        ("machine_id", "/var/lib/dbus/machine-id"),
        ("hostname", "/etc/hostname"),
        ("passwd", "/etc/passwd"),
        ("group", "/etc/group"),
        ("hosts", "/etc/hosts"),
        ("resolv", "/etc/resolv.conf"),
        ("nsswitch", "/etc/nsswitch.conf"),
        ("boot_id", "/proc/sys/kernel/random/boot_id"),
        ("hostname", "/proc/sys/kernel/hostname"),
        ("cmdline", "/proc/cmdline"),
    ):
        command.extend(["--ro-bind", identity[source_name], destination])
    for destination in (
        "/proc/diskstats",
        "/proc/interrupts",
        "/proc/iomem",
        "/proc/ioports",
        "/proc/kallsyms",
        "/proc/modules",
        "/proc/partitions",
    ):
        if os.path.exists(destination):
            command.extend(["--ro-bind", identity["empty"], destination])


