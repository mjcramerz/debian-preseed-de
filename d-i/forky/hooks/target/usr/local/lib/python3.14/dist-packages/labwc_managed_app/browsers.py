"""Browser launch profiles for the managed Labwc application launcher."""

from __future__ import annotations

from .runtime import ANGLE_GL_ARGS, wayland_ozone_args

EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE = "OptimizationGuideModelExecution"

BROWSER_PROFILES = {
    "chromium": {
        "launch_disable_features": ("WaylandWpColorManagerV1",),
        "intel_features": (
            "UseOzonePlatform",
            "VaapiVideoDecoder",
            "VaapiVideoEncoder",
        ),
        "intel_disable_features": (
            "UseChromeOSDirectVideoDecoder",
            "WaylandWpColorManagerV1",
        ),
        "intel_extra_args": ("--enable-zero-copy",),
        "nvidia_features": (
            "UseOzonePlatform",
            "VaapiVideoDecoder",
            "VaapiIgnoreDriverChecks",
        ),
        "nvidia_disable_features": (
            "UseChromeOSDirectVideoDecoder",
            "WaylandWpColorManagerV1",
        ),
        "nvidia_extra_args": (),
    },
    "microsoft-edge": {
        "launch_disable_features": (EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE,),
        "intel_features": (
            "UseOzonePlatform",
            "VaapiVideoDecoder",
            "VaapiVideoEncoder",
        ),
        "intel_disable_features": (
            "UseChromeOSDirectVideoDecoder",
            EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE,
        ),
        "intel_extra_args": (),
        "nvidia_features": (
            "UseOzonePlatform",
            "VaapiVideoDecoder",
            "VaapiIgnoreDriverChecks",
        ),
        "nvidia_disable_features": (
            "UseChromeOSDirectVideoDecoder",
            EDGE_ON_DEVICE_MODEL_DISABLE_FEATURE,
        ),
        "nvidia_extra_args": (),
    },
    "vivaldi": {
        "launch_disable_features": (),
        "intel_features": (
            "UseOzonePlatform",
            "VaapiVideoDecoder",
        ),
        "intel_disable_features": ("UseChromeOSDirectVideoDecoder",),
        "intel_extra_args": (),
        "nvidia_features": (
            "UseOzonePlatform",
            "VaapiVideoDecoder",
            "VaapiIgnoreDriverChecks",
        ),
        "nvidia_disable_features": ("UseChromeOSDirectVideoDecoder",),
        "nvidia_extra_args": ("--disable-gpu-driver-bug-workarounds",),
    },
}


def browser_args(app_name: str, mode: str) -> list[str]:
    profile = BROWSER_PROFILES[app_name]
    if mode == "launch":
        return [
            *wayland_ozone_args(
                disable_features=profile["launch_disable_features"],
            ),
            *ANGLE_GL_ARGS,
        ]

    features = profile[f"{mode}_features"]
    disabled_features = profile[f"{mode}_disable_features"]
    return [
        *wayland_ozone_args(
            enable_features=features,
            disable_features=disabled_features,
        ),
        "--ignore-gpu-blocklist",
        "--enable-gpu-rasterization",
        *ANGLE_GL_ARGS,
        *profile[f"{mode}_extra_args"],
    ]
