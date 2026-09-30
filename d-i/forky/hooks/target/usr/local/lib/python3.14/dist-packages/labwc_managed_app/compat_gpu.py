"""Compatibility-only render-node selection from kernel device identity."""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from .compat_protocol import ProtocolError

VENDORS = {"intel": ("0x8086", {"i915", "xe"}), "nvidia": ("0x10de", {"nvidia"})}


def _attribute(path: Path, limit: int = 64) -> str:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ProtocolError("GPU identity attribute is unsafe")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ProtocolError("GPU identity changed while opening")
        value = os.read(fd, limit + 1)
        if len(value) > limit:
            raise ProtocolError("GPU identity exceeds the limit")
        return value.decode("ascii").strip()
    finally:
        os.close(fd)


def _kernel_link(path: Path, root: Path) -> Path:
    metadata = path.lstat()
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0:
        raise ProtocolError("GPU kernel link is unsafe")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise ProtocolError("GPU kernel link leaves sysfs")
    return resolved


def render_identity(node: Path, sys_root: Path = Path("/sys")) -> tuple[str | None, Path, os.stat_result]:
    metadata = node.lstat()
    if (not stat.S_ISCHR(metadata.st_mode) or metadata.st_uid != 0
            or metadata.st_mode & 0o7111 or os.major(metadata.st_rdev) != 226
            or os.minor(metadata.st_rdev) < 128 or node.resolve() != node):
        raise ProtocolError("render node has unsafe device identity")
    # Debian's render-node policy can legitimately use 0666. Character-device
    # write access does not grant inode replacement; validate the directory,
    # kernel rdev/vendor/driver and actual access instead of a code-file mode.
    directory = node.parent.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0
            or directory.st_mode & 0o022 or not os.access(node, os.R_OK | os.W_OK)):
        raise ProtocolError("render directory or access is unsafe")
    entry = _kernel_link(sys_root / "class/drm" / node.name, sys_root / "devices")
    if _attribute(entry / "dev") != f"{os.major(metadata.st_rdev)}:{os.minor(metadata.st_rdev)}":
        raise ProtocolError("render node and sysfs disagree")
    device = _kernel_link(entry / "device", sys_root / "devices")
    driver = _kernel_link(device / "driver", sys_root / "bus").name
    vendor = _attribute(device / "vendor").lower()
    for name, (expected, drivers) in VENDORS.items():
        if vendor == expected:
            if driver not in drivers:
                raise ProtocolError("render vendor and bound driver disagree")
            return name, device, metadata
    return None, device, metadata


def _nvidia_devices(device: Path, dev_root: Path, proc_root: Path) -> list[Path]:
    if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", device.name) is None:
        raise ProtocolError("NVIDIA GPU lacks a PCI identity")
    information = _attribute(proc_root / "driver/nvidia/gpus" / device.name / "information", 4096)
    match = re.search(r"^Device Minor:\s*([0-9]{1,3})\s*$", information, re.M)
    if match is None or int(match.group(1)) >= 255:
        raise ProtocolError("NVIDIA GPU lacks a validated device minor")
    minor = int(match.group(1))
    nodes = [dev_root / "nvidiactl", dev_root / f"nvidia{minor}"]
    for node, expected_minor in zip(nodes, (255, minor)):
        metadata = node.lstat()
        if (not stat.S_ISCHR(metadata.st_mode) or metadata.st_uid != 0 or node.resolve() != node
                or os.major(metadata.st_rdev) != 195 or os.minor(metadata.st_rdev) != expected_minor):
            raise ProtocolError("NVIDIA graphics device identity is unsafe")
    # No modeset, UVM/compute, caps directory, kfd or accel binding. Extending
    # this set needs a separately validated target requirement.
    return nodes


def add_device_binds(command: list[str], mode: str, *, dev_root: Path = Path("/dev"),
                     sys_root: Path = Path("/sys"), proc_root: Path = Path("/proc")) -> str:
    if mode not in {"launch", "intel", "nvidia"}:
        raise ProtocolError("unsupported compatibility GPU policy")
    identities = []
    for node in sorted((dev_root / "dri").glob("renderD[0-9]*")):
        if re.fullmatch(r"renderD[1-9][0-9]{0,5}", node.name) is None:
            raise ProtocolError("unexpected render device name")
        vendor, device, metadata = render_identity(node, sys_root)
        if vendor is not None:
            identities.append((vendor, node, device, metadata))
        if len(identities) > 16:
            raise ProtocolError("too many render devices")
    selected_mode = mode
    if mode == "launch":
        selected_mode = "intel" if any(i[0] == "intel" for i in identities) else "nvidia"
    candidates = [i for i in identities if i[0] == selected_mode]
    if len(candidates) != 1:
        raise ProtocolError("GPU policy requires exactly one matching render device")
    vendor, node, device, metadata = candidates[0]
    nodes = [node]
    if vendor == "nvidia":
        nodes += _nvidia_devices(device, dev_root, proc_root)
    # Recheck the selected inode/rdev immediately before constructing its bind.
    current = node.lstat()
    if (current.st_dev, current.st_ino, current.st_rdev) != (metadata.st_dev, metadata.st_ino, metadata.st_rdev):
        raise ProtocolError("render device was replaced during selection")
    command.extend(["--dir", "/dev/dri"])
    for path in nodes:
        command.extend(["--dev-bind", str(path), "/dev/" + str(path.relative_to(dev_root))])
    return vendor
