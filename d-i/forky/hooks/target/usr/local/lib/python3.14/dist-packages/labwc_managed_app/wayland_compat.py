"""Cage-hosted private Xwayland payload for Zoom and Discord sandboxes."""

from __future__ import annotations

import os
import stat

from .profiles import WAYLAND_COMPAT_APPS
from .runtime import fail
from .sandbox import (
    _run_persistent_sandbox,
    require_private_xkbcomp_overlay,
    require_root_owned_directory,
    require_root_owned_regular_file,
)
from .wayland_compat_runtime import CAGE_SUPERVISOR_MODE

CAGE_BINARY = "/usr/bin/cage"
PRIVATE_RUNTIME_ROOT = "/opt/xwayland"
PRIVATE_RUNTIME_BINARY = f"{PRIVATE_RUNTIME_ROOT}/usr/bin/Xwayland"
PRIVATE_RUNTIME_XKBCOMP = f"{PRIVATE_RUNTIME_ROOT}/usr/bin/xkbcomp"
PRIVATE_RUNTIME_XKBCOMP_OVERLAY_DIRECTORY = (
    f"{PRIVATE_RUNTIME_ROOT}/usr/lib/xkbcomp-overlay"
)
PRIVATE_RUNTIME_PROTOCOL = f"{PRIVATE_RUNTIME_ROOT}/usr/lib/xorg/protocol.txt"
PRIVATE_RUNTIME_LIBRARY_DIRECTORY = (
    f"{PRIVATE_RUNTIME_ROOT}/usr/lib/x86_64-linux-gnu"
)
PRIVATE_RUNTIME_LIBRARY_NAMES = (
    "libXau.so.6",
    "libXdmcp.so.6",
    "libXfont2.so.2",
    "libfontenc.so.1",
    "libxcb-cursor.so.0",
    "libxcb-image.so.0",
    "libxcb-render-util.so.0",
    "libxcb-render.so.0",
    "libxcb-shm.so.0",
    "libxcb-util.so.1",
    "libxcb.so.1",
    "libxcvt.so.0",
    "libxshmfence.so.1",
)

SANDBOX_LIFECYCLE_HELPER = "/usr/local/libexec/labwc-zoom-discord-compat-runtime"


def _validate_private_library(library_name: str) -> None:
    if (
        not library_name
        or "/" in library_name
        or library_name in {".", ".."}
    ):
        fail(f"private compatibility library name is invalid: {library_name!r}")
    library_path = os.path.join(PRIVATE_RUNTIME_LIBRARY_DIRECTORY, library_name)
    try:
        metadata = os.lstat(library_path)
    except OSError as exc:
        fail(
            "private Zoom/Discord compatibility library is unavailable: "
            f"{library_path}: {exc}"
        )
    if stat.S_ISREG(metadata.st_mode):
        require_root_owned_regular_file(
            "private Zoom/Discord compatibility library",
            library_path,
        )
        return
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0:
        fail(
            "private Zoom/Discord compatibility library entry must be a "
            f"root-owned symlink or regular file: {library_path}"
        )

    library_target = os.path.realpath(library_path)
    if (
        os.path.commonpath((PRIVATE_RUNTIME_LIBRARY_DIRECTORY, library_target))
        != PRIVATE_RUNTIME_LIBRARY_DIRECTORY
    ):
        fail(
            "private Zoom/Discord compatibility library target escapes its "
            f"managed directory: {library_target}"
        )
    require_root_owned_regular_file(
        "private Zoom/Discord compatibility library target",
        library_target,
    )


def validate_private_runtime() -> None:
    require_root_owned_regular_file(
        "Cage compositor",
        CAGE_BINARY,
        executable=True,
    )
    require_root_owned_directory("private compatibility root", PRIVATE_RUNTIME_ROOT)
    try:
        top_level_entries = {
            entry.name for entry in os.scandir(PRIVATE_RUNTIME_ROOT)
        }
    except OSError as exc:
        fail(
            "cannot inspect the private Zoom/Discord compatibility root: "
            f"{PRIVATE_RUNTIME_ROOT}: {exc}"
        )
    unexpected_entries = sorted(top_level_entries.difference({"usr", "var"}))
    if unexpected_entries:
        fail(
            "private Zoom/Discord compatibility root contains unexpected "
            f"entries: {', '.join(unexpected_entries)}"
        )

    require_root_owned_directory(
        "private compatibility usr directory",
        os.path.join(PRIVATE_RUNTIME_ROOT, "usr"),
    )
    private_var_directory = os.path.join(PRIVATE_RUNTIME_ROOT, "var")
    if os.path.lexists(private_var_directory):
        require_root_owned_directory(
            "private compatibility var directory",
            private_var_directory,
        )
    require_root_owned_directory(
        "private compatibility executable directory",
        os.path.dirname(PRIVATE_RUNTIME_BINARY),
    )
    require_root_owned_directory(
        "private compatibility protocol directory",
        os.path.dirname(PRIVATE_RUNTIME_PROTOCOL),
    )
    require_root_owned_directory(
        "private compatibility library directory",
        PRIVATE_RUNTIME_LIBRARY_DIRECTORY,
    )
    require_root_owned_regular_file(
        "private compatibility executable",
        PRIVATE_RUNTIME_BINARY,
        executable=True,
    )
    require_root_owned_regular_file(
        "private compatibility XKB compiler",
        PRIVATE_RUNTIME_XKBCOMP,
        executable=True,
    )
    require_private_xkbcomp_overlay(PRIVATE_RUNTIME_XKBCOMP_OVERLAY_DIRECTORY)
    require_root_owned_regular_file(
        "private compatibility protocol data",
        PRIVATE_RUNTIME_PROTOCOL,
    )
    require_root_owned_regular_file(
        "Zoom/Discord compatibility lifecycle helper",
        SANDBOX_LIFECYCLE_HELPER,
        executable=True,
    )
    for library_name in PRIVATE_RUNTIME_LIBRARY_NAMES:
        _validate_private_library(library_name)


def run_wayland_compat_sandbox(
    app_name: str,
    mode: str,
    extra_args: list[str],
) -> int:
    if app_name not in WAYLAND_COMPAT_APPS:
        fail(f"private compatibility sandbox is not permitted for {app_name}")
    validate_private_runtime()
    return _run_persistent_sandbox(
        app_name,
        mode,
        extra_args,
        payload_argv_prefix=(
            SANDBOX_LIFECYCLE_HELPER,
            CAGE_SUPERVISOR_MODE,
            app_name,
            mode,
            "--",
        ),
        private_xwayland_binary=PRIVATE_RUNTIME_BINARY,
        private_xkbcomp_overlay_directory=(
            PRIVATE_RUNTIME_XKBCOMP_OVERLAY_DIRECTORY
        ),
    )
