"""Browser launch profiles for the managed Labwc application launcher."""

from __future__ import annotations

import os
from pathlib import Path
import re
import stat

from .integrity import system_owner
from .runtime import ANGLE_GL_ARGS, wayland_ozone_args

EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE = "OptimizationGuideModelExecution"
VIVALDI_MEDIA_DIRECTORY = "/var/opt/vivaldi"


def vivaldi_media_directory(*, root: Path = Path("/")) -> str:
    """Require a system codec accepted by this installed vendor launcher.

    Read the literal version inventory as data. Never source vendor shell or
    preload a library into the supervisor to discover codec compatibility.
    """
    owner = system_owner(root / "usr")[0]

    def trusted(path: Path, *, directory: bool = False) -> os.stat_result:
        metadata = path.lstat()
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if (not expected(metadata.st_mode) or metadata.st_uid != owner
                or metadata.st_mode & 0o022):
            raise ValueError(f"unsafe Vivaldi media path: {path}")
        return metadata

    for path in ("/opt", "/opt/vivaldi", "/var", "/var/opt", VIVALDI_MEDIA_DIRECTORY):
        trusted(root / path.lstrip("/"), directory=True)
    launcher = root / "opt/vivaldi/vivaldi"
    trusted(launcher)
    descriptor = os.open(launcher, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != owner
                or metadata.st_mode & 0o022 or metadata.st_nlink != 1):
            raise ValueError("unsafe Vivaldi launcher media inventory")
        data = handle.read(131073)
    if len(data) > 131072:
        raise ValueError("Vivaldi launcher exceeds its media inventory budget")
    source = data.decode("utf-8")
    inventories = re.findall(r'^FFMPEG_VERSIONS="([A-Za-z0-9. _-]+)"[ \t]*$', source, re.MULTILINE)
    if len(inventories) != 1:
        raise ValueError("Vivaldi launcher has no unambiguous codec version inventory")
    versions = inventories[0].split()
    if not 1 <= len(versions) <= 16 or any(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", version) is None
        for version in versions
    ):
        raise ValueError("invalid Vivaldi codec version inventory")
    for version in versions:
        directory = root / VIVALDI_MEDIA_DIRECTORY.lstrip("/") / f"media-codecs-{version}"
        try:
            trusted(directory, directory=True)
            metadata = trusted(directory / "libffmpeg.so")
        except FileNotFoundError:
            continue
        if not 65536 <= metadata.st_size <= 33554432 or metadata.st_nlink != 1:
            raise ValueError(f"invalid Vivaldi codec library: {directory}")
        return str(root / VIVALDI_MEDIA_DIRECTORY.lstrip("/"))
    raise ValueError(
        "Vivaldi has no compatible system media codec; an administrator must run "
        "/opt/vivaldi/update-ffmpeg --system before launching it"
    )


BROWSER_PROFILES = {
    "chromium": {
        "launch_disable_features": ("WaylandWpColorManagerV1",),
        "intel_features": (
            "UseOzonePlatform",
            "AcceleratedVideoDecoder",
            "AcceleratedVideoDecodeLinuxGL",
            "AcceleratedVideoEncoder",
        ),
        "intel_disable_features": (
            "WaylandWpColorManagerV1",
        ),
        "intel_extra_args": ("--enable-zero-copy",),
        "nvidia_features": (
            "UseOzonePlatform",
            "AcceleratedVideoDecoder",
            "AcceleratedVideoDecodeLinuxGL",
            "VaapiIgnoreDriverChecks",
        ),
        "nvidia_disable_features": (
            "WaylandWpColorManagerV1",
        ),
        "nvidia_extra_args": (),
    },
    "microsoft-edge": {
        "launch_disable_features": (EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE,),
        "intel_features": (
            "UseOzonePlatform",
            "AcceleratedVideoDecoder",
            "AcceleratedVideoDecodeLinuxGL",
            "AcceleratedVideoEncoder",
        ),
        "intel_disable_features": (
            EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE,
        ),
        "intel_extra_args": (),
        "nvidia_features": (
            "UseOzonePlatform",
            "AcceleratedVideoDecoder",
            "AcceleratedVideoDecodeLinuxGL",
            "VaapiIgnoreDriverChecks",
        ),
        "nvidia_disable_features": (
            EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE,
        ),
        "nvidia_extra_args": (),
    },
    "vivaldi": {
        "launch_disable_features": (),
        "intel_features": (
            "UseOzonePlatform",
            "AcceleratedVideoDecoder",
            "AcceleratedVideoDecodeLinuxGL",
        ),
        "intel_disable_features": (),
        "intel_extra_args": (),
        "nvidia_features": (
            "UseOzonePlatform",
            "AcceleratedVideoDecoder",
            "AcceleratedVideoDecodeLinuxGL",
        ),
        "nvidia_disable_features": (),
        # Keep Chromium's driver workarounds and blocklist decisions. PRIME
        # selects the GPU; it does not establish that every accelerated path
        # is safe on that driver.
        "nvidia_extra_args": (),
    },
}


def browser_args(app_name: str, mode: str) -> list[str]:
    profile = BROWSER_PROFILES[app_name]
    # Mesa can start driver threads during context creation. Enter Chromium's
    # own GPU sandbox first, while retaining its seccomp/namespace protection.
    # Keep this correction scoped to the reported Vivaldi OpenGL path.
    sandbox_args = ("--gpu-sandbox-start-early",) if app_name == "vivaldi" else ()
    if mode == "launch":
        return [
            *wayland_ozone_args(
                disable_features=profile["launch_disable_features"],
            ),
            *ANGLE_GL_ARGS,
            *sandbox_args,
        ]

    features = profile[f"{mode}_features"]
    disabled_features = profile[f"{mode}_disable_features"]
    return [
        *wayland_ozone_args(
            enable_features=features,
            disable_features=disabled_features,
        ),
        *(() if app_name == "vivaldi" else (
            "--ignore-gpu-blocklist", "--enable-gpu-rasterization",
        )),
        *ANGLE_GL_ARGS,
        *sandbox_args,
        *profile[f"{mode}_extra_args"],
    ]
