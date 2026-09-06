"""Electron launch profiles for the managed Labwc application launcher."""

from __future__ import annotations

from .runtime import ANGLE_GL_ARGS, wayland_ozone_args

ELECTRON_OLD_SPACE_SIZE_MB = {
    "bitwarden": 1408,
    "chatgpt": 2016,
    "code": 2000,
    "discord": 1664,
    "filen": 1792,
    "ledger-live": 1856,
    "obsidian": 1920,
    "postman": 1984,
    "sleek": 1888,
    "spotify": 1728,
    "tutanota": 1536,
}
if (
    len(set(ELECTRON_OLD_SPACE_SIZE_MB.values())) != len(ELECTRON_OLD_SPACE_SIZE_MB)
    or any(value <= 0 or value >= 2024 for value in ELECTRON_OLD_SPACE_SIZE_MB.values())
):
    raise RuntimeError("Electron old-space limits must be unique positive integers below 2024 MiB")
ELECTRON_PASSWORD_STORE = "--password-store=gnome-libsecret"
ELECTRON_BACKGROUND_ACTIVITY_ARGS = (
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
)


def electron_js_flags(app_name: str) -> str:
    return f"--js-flags=--max-old-space-size={ELECTRON_OLD_SPACE_SIZE_MB[app_name]}"


def electron_password_store_arg(app_name: str) -> str:
    return ELECTRON_PASSWORD_STORE



ELECTRON_PROFILES = {
    "bitwarden": {
        "background_activity": False,
        "features": (),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
    "chatgpt": {
        "background_activity": True,
        "features": ("WebRTCPipeWireCapturer",),
        "intel_extra_args": ("--enable-zero-copy",),
        "nvidia_extra_args": (),
    },
    "code": {
        "background_activity": True,
        "features": (),
        "intel_extra_args": ("--enable-zero-copy",),
        "nvidia_extra_args": (),
    },
    "discord": {
        "background_activity": True,
        "features": ("WebRTCPipeWireCapturer",),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
    "filen": {
        "background_activity": True,
        "features": (),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
    "ledger-live": {
        "background_activity": False,
        "features": (),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
    "obsidian": {
        "background_activity": False,
        "features": (),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
    "postman": {
        "background_activity": False,
        "features": (),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
    "sleek": {
        "background_activity": False,
        "features": (),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
    "spotify": {
        "background_activity": True,
        "features": (),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
    "tutanota": {
        "background_activity": False,
        "features": (),
        "intel_extra_args": (),
        "nvidia_extra_args": (),
    },
}


def electron_args(app_name: str, mode: str) -> list[str]:
    profile = ELECTRON_PROFILES[app_name]
    features = ("UseOzonePlatform", *profile["features"])
    disabled_features = profile.get("disable_features", ())
    gl_args = profile.get("gl_args", ANGLE_GL_ARGS)
    if mode == "launch":
        args = wayland_ozone_args(
            enable_features=features,
            disable_features=disabled_features,
        )
        args.extend(gl_args)
        args.extend(("--ignore-gpu-blocklist", "--enable-gpu-rasterization"))
        args.append(electron_password_store_arg(app_name))
        args.extend(profile.get("launch_extra_args", ()))
        return args

    args: list[str] = []
    if profile["background_activity"]:
        args.extend(ELECTRON_BACKGROUND_ACTIVITY_ARGS)
    args.extend(
        [
            *wayland_ozone_args(
                enable_features=features,
                disable_features=disabled_features,
            ),
            electron_password_store_arg(app_name),
            electron_js_flags(app_name),
            "--ignore-gpu-blocklist",
            "--enable-gpu-rasterization",
            *gl_args,
            *profile[f"{mode}_extra_args"],
        ]
    )
    return args


def electron_privacy_args(app_name: str) -> list[str]:
    profile = ELECTRON_PROFILES[app_name]
    features = ("UseOzonePlatform", *profile["features"])
    gl_args = profile.get("gl_args", ANGLE_GL_ARGS)
    args: list[str] = []
    if profile["background_activity"]:
        args.extend(ELECTRON_BACKGROUND_ACTIVITY_ARGS)
    args.extend(
        [
            *wayland_ozone_args(enable_features=features),
            electron_password_store_arg(app_name),
            electron_js_flags(app_name),
            "--ignore-gpu-blocklist",
            "--enable-gpu-rasterization",
            *gl_args,
        ]
    )
    return args
