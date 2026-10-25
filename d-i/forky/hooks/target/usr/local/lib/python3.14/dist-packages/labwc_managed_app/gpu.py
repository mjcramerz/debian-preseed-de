"""Native client rendering policy, resolved from kernel PCI/device identity.

Render-node numbers are enumeration order, never vendor identifiers. Select
once, use that identity for both toolkit hints and sandbox device access, and
reject a missing/ambiguous explicit accelerator before starting the client.
The separate private Xwayland runtime retains its own existing device policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat

from .integrity import system_owner
from .runtime import fail

PCI = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]")
VENDORS = {"0x8086": ("intel", {"i915", "xe"}),
           "0x10de": ("nvidia", {"nvidia"}),
           "0x1002": ("amd", {"amdgpu", "radeon"})}
SELECTOR_NAMES = (
    "DRI_PRIME", "GBM_BACKEND", "LIBVA_DRIVER_NAME", "NVD_BACKEND", "NVD_DRM_DEVICE",
    "MOZ_DRM_DEVICE", "__EGL_VENDOR_LIBRARY_FILENAMES", "__EGL_VENDOR_LIBRARY_DIRS",
    "__GLX_VENDOR_LIBRARY_NAME", "__NV_PRIME_RENDER_OFFLOAD",
    "__NV_PRIME_RENDER_OFFLOAD_PROVIDER", "__VK_LAYER_NV_optimus",
    "VK_ICD_FILENAMES", "VK_DRIVER_FILES", "MESA_LOADER_DRIVER_OVERRIDE",
    "LIBGL_ALWAYS_SOFTWARE", "MESA_VK_DEVICE_SELECT", "MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE",
)


def _identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_rdev


def _attribute(path: Path, owner: int, limit: int = 64) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != owner or metadata.st_mode & 0o022:
            fail("unsafe GPU kernel attribute")
        value = os.read(descriptor, limit + 1)
        if len(value) > limit:
            fail("GPU kernel attribute exceeds its limit")
        return value.decode("ascii").strip()
    finally:
        os.close(descriptor)


def _kernel_link(path: Path, root: Path, owner: int) -> Path:
    metadata = path.lstat()
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != owner:
        fail("unsafe GPU kernel link")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        fail("GPU kernel link leaves its expected tree")
    return resolved


def _device(path: Path, owner: int, major: int, minor: int) -> os.stat_result:
    """Validate a device identity without opening it or claiming access to it."""
    metadata = path.lstat()
    if (not stat.S_ISCHR(metadata.st_mode) or metadata.st_uid != owner
            or metadata.st_mode & 0o7111 or path.resolve(strict=True) != path
            or (os.major(metadata.st_rdev), os.minor(metadata.st_rdev)) != (major, minor)):
        fail("unsafe GPU device identity")
    # Selection can run before a user-manager or sandbox handoff. An access()
    # result in this process cannot authorize the renderer's later O_RDWR open
    # with its final credentials, namespaces and AppArmor profile. Leave that
    # decision to the actual open; never change permissions during discovery.
    return metadata


@dataclass(frozen=True)
class Selection:
    vendor: str
    pci: str
    node: Path
    bindings: tuple[tuple[Path, tuple[int, int, int]], ...]

    def add_binds(self, command: list[str], *, dev_root: Path = Path("/dev")) -> None:
        candidate = ["--dir", "/dev/dri"]
        for path, identity in self.bindings:
            if _identity(path.lstat()) != identity:
                fail("GPU device was replaced during selection")
            candidate.extend(["--dev-bind", str(path), "/dev/" + str(path.relative_to(dev_root))])
        command.extend(candidate)

    def apply_environment(self, environment: dict[str, str]) -> None:
        for name in SELECTOR_NAMES:
            environment.pop(name, None)
        environment["MOZ_DRM_DEVICE"] = str(self.node)
        if self.vendor == "nvidia":
            environment.update({
                "GBM_BACKEND": "nvidia-drm", "LIBVA_DRIVER_NAME": "nvidia",
                "NVD_BACKEND": "direct", "NVD_DRM_DEVICE": str(self.node),
                "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/10_nvidia.json",
                "__GLX_VENDOR_LIBRARY_NAME": "nvidia", "__NV_PRIME_RENDER_OFFLOAD": "1",
            })
        else:
            environment.update({
                "DRI_PRIME": "pci-" + self.pci.replace(":", "_").replace(".", "_"),
                "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
            })
            if self.vendor == "intel":
                environment["LIBVA_DRIVER_NAME"] = "iHD"

    def chromium_arguments(self, arguments: list[str]) -> list[str]:
        """Replace the Ozone device hint, preserving operands after '--'."""
        result = []
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "--":
                result.extend(arguments[index:])
                break
            key, separator, _ = argument.partition("=")
            if key in {"--render-node-override", "-render-node-override"}:
                if not separator:
                    if index + 1 >= len(arguments):
                        fail("render-node override is missing its value")
                    index += 1
            else:
                result.append(argument)
            index += 1
        # All callers pass executable argv, including the Chromium shell
        # wrappers; the switch must precede any URL or '--' operands.
        return [result[0], "--render-node-override=" + str(self.node), *result[1:]]


def select(mode: str, *, dev_root: Path = Path("/dev"), sys_root: Path = Path("/sys"),
           proc_root: Path = Path("/proc"), owner: int | None = None,
           egl_root: Path = Path("/usr/share/glvnd/egl_vendor.d")) -> Selection | None:
    if mode not in {"launch", "intel", "nvidia"}:
        fail("unsupported native rendering mode")
    if owner is None:
        owner = system_owner()[0]
    try:
        directory = dev_root / "dri"
        if not directory.exists() and mode == "launch":
            return None
        metadata = directory.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != owner
                or metadata.st_mode & 0o022 or directory.resolve(strict=True) != directory):
            fail("unsafe GPU device directory")
        identities = []
        with os.scandir(directory) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 256:
                    fail("GPU device enumeration exceeds its limit")
                if not re.fullmatch(r"renderD[1-9][0-9]{0,5}", entry.name):
                    continue
                if len(identities) >= 16:
                    fail("too many GPU render devices")
                node = directory / entry.name
                minor = int(entry.name.removeprefix("renderD"))
                if minor < 128:
                    fail("invalid GPU render minor")
                kernel_node = _kernel_link(sys_root / "class/drm" / node.name, sys_root / "devices", owner)
                if _attribute(kernel_node / "dev", owner) != f"226:{minor}":
                    fail("GPU render node and sysfs disagree")
                device = _kernel_link(kernel_node / "device", sys_root / "devices", owner)
                try:
                    vendor_id = _attribute(device / "vendor", owner).lower()
                except FileNotFoundError:
                    # Non-PCI virtual renderers have no PCI vendor attribute.
                    # They cannot satisfy an explicit Intel/NVIDIA request.
                    continue
                policy = VENDORS.get(vendor_id)
                # An unavailable proprietary driver on the other adapter must
                # not prevent an explicitly selected Intel client from starting.
                if policy is None or (mode != "launch" and policy[0] != mode):
                    continue
                driver = _kernel_link(device / "driver", sys_root / "bus", owner).name
                if driver not in policy[1] or PCI.fullmatch(device.name) is None:
                    fail("unsupported GPU vendor, driver or PCI identity")
                device_meta = _device(node, owner, 226, minor)
                identities.append((policy[0], device, node, device_meta))
        candidates = [item for item in identities if mode == "launch" or item[0] == mode]
        if mode == "launch" and len(candidates) > 1:
            candidates = [item for item in candidates if item[0] == "intel"]
        if not candidates and not identities and mode == "launch":
            return None
        if len(candidates) != 1:
            fail("native rendering requires exactly one matching GPU")
        vendor, device, node, node_meta = candidates[0]
        vendor_file, library = (("10_nvidia.json", "libEGL_nvidia.so.0") if vendor == "nvidia"
                                else ("50_mesa.json", "libEGL_mesa.so.0"))
        manifest = json.loads(_attribute(egl_root / vendor_file, owner, 16384))
        if (not isinstance(manifest, dict) or manifest.get("file_format_version") != "1.0.0"
                or not isinstance(manifest.get("ICD"), dict)
                or manifest["ICD"].get("library_path") != library):
            fail("GPU EGL vendor manifest is unavailable or inconsistent")
        bindings = [(node, _identity(node_meta))]
        if vendor == "nvidia":
            info = _attribute(proc_root / "driver/nvidia/gpus" / device.name / "information", owner, 4096)
            match = re.search(r"^Device Minor:\s*([0-9]{1,3})\s*$", info, re.M)
            if match is None or int(match[1]) >= 255:
                fail("NVIDIA GPU lacks a valid graphics minor")
            for name, minor in (("nvidiactl", 255), ("nvidia" + match[1], int(match[1]))):
                path = dev_root / name
                bindings.append((path, _identity(_device(path, owner, 195, minor))))
        return Selection(vendor, device.name, node, tuple(bindings))
    except (OSError, ValueError, UnicodeError) as exc:
        fail(f"native GPU identity is unavailable: {exc}")
