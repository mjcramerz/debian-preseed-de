"""Closed, opt-in diagnostic context; never a backend or sandbox override."""
from __future__ import annotations

import os
import re
import json
import fcntl
import stat
import time

PROFILES = {
    "gtk": {"GTK_DEBUG": "interactive", "G_MESSAGES_DEBUG": "all", "GDK_DEBUG": "misc",
            "GSK_DEBUG": "renderer"},
    "qt": {"QT_DEBUG_PLUGINS": "1", "QT_LOGGING_RULES": "*.debug=true",
           "QML_IMPORT_TRACE": "1", "QSG_INFO": "1"},
    "electron": {"ELECTRON_ENABLE_LOGGING": "1", "ELECTRON_ENABLE_STACK_DUMPING": "1"},
    "wayland-graphics": {"WAYLAND_DEBUG": "client", "LIBGL_DEBUG": "verbose",
                         "MESA_DEBUG": "1", "EGL_LOG_LEVEL": "debug",
                         "VK_LOADER_DEBUG": "error,warn,info,driver"},
    "full": {}, "xwayland": {},
}
CONTEXT_NAMES = ("LABWC_DEBUG_PROFILE", "LABWC_DEBUG_SESSION", "LABWC_DEBUG_DESKTOP_ID",
                 "LABWC_DEBUG_EXECUTABLE")
SESSION_RE = re.compile(r"[0-9a-f]{24}\Z")
DIAGNOSTIC_NAMES = frozenset((*CONTEXT_NAMES, *(key for values in PROFILES.values() for key in values)))


def _publish(name: str, record: dict) -> None:
    selected = context()
    if not selected:
        return
    descriptors = []
    try:
        for part in (f"/run/user/{os.getuid()}", "labwc-debug", selected[CONTEXT_NAMES[1]]):
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=descriptors[-1] if descriptors else None)
            descriptors.append(fd)
            meta = os.fstat(fd)
            if meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
                raise ValueError("unsafe diagnostic service directory")
        request_fd = os.open('request.json', os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=descriptors[-1])
        with os.fdopen(request_fd, 'rb') as source:
            metadata = os.fstat(source.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                    or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
                return
            request = json.loads(source.read(4097))
        if request['session'] != selected[CONTEXT_NAMES[1]] or not 0 < request['expires_at'] - time.time() <= 180:
            return
        lock = os.open('capture.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                       dir_fd=descriptors[-1])
        descriptors.append(lock)
        metadata = os.fstat(lock)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
            return
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with os.scandir(descriptors[-2]) as entries:
            count = sum(1 for _ in zip(entries, range(65)))
        if count >= 40:
            return
        # The bundle collector prepares the directory before GIO launches the
        # selected Exec. Exclusive publication preserves concurrent services.
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=descriptors[-2])
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(dict(record, created_at=time.time()), stream)
    except (OSError, ValueError, KeyError, TypeError):
        # Diagnostics must not change whether the normal application launches.
        pass
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def register_unit(unit: str, executable: str) -> None:
    """Publish service identity only, never argv or the inherited environment."""
    if re.fullmatch(r"labwc-[A-Za-z0-9_.-]{1,180}\.service", unit) is None:
        raise ValueError("invalid diagnostic service identity")
    _publish("unit-" + unit + ".json", {"unit": unit, "executable": executable})


def record_environment(environment: dict[str, str]) -> None:
    """Record only fixed diagnostic and renderer-policy names, never secrets."""
    names = DIAGNOSTIC_NAMES | {"GDK_BACKEND", "QT_QPA_PLATFORM", "GSK_RENDERER", "GDK_DISABLE",
                                "ANGLE_DEFAULT_PLATFORM", "QSG_RHI_BACKEND", "QT_OPENGL",
                                "SDL_VIDEODRIVER", "SDL_VIDEO_DRIVER", "WGPU_BACKEND"}
    _publish(f"environment-{os.getpid()}.json", {
        "pid": os.getpid(), "values": {name: environment[name] for name in sorted(names) if name in environment}})


def context(source: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    profile = source.get(CONTEXT_NAMES[0], "")
    if not profile:
        return {}
    result = {name: source.get(name, "") for name in CONTEXT_NAMES}
    if profile not in PROFILES or not SESSION_RE.fullmatch(result[CONTEXT_NAMES[1]]):
        raise ValueError("invalid application diagnostic profile or session")
    for name in CONTEXT_NAMES[2:]:
        value = result[name]
        if not value or len(value.encode("utf-8")) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid application diagnostic identity label")
    return result


def apply(environment: dict[str, str], *, compatibility: bool = False) -> None:
    selected = context()
    if not selected:
        return
    profile = selected[CONTEXT_NAMES[0]]
    if compatibility:
        # Only observational trace variables cross this optional boundary.
        # Cage's nested-Wayland renderer, private DISPLAY, Qt/XCB selection,
        # executable eligibility and private Xwayland paths stay runtime-owned.
        if profile != "xwayland":
            raise ValueError("Zoom/Discord require the private Xwayland diagnostic profile")
        environment.update(PROFILES["wayland-graphics"])
        return
    environment.update(selected)
    if profile == "xwayland":
        return
    # Every profile includes protocol and graphics evidence, keeping existing
    # renderer/driver/backend selection intact. No fatal-warning flags,
    # remote debugging ports, loader overrides, or Vulkan enablement.
    environment.update(PROFILES["wayland-graphics"])
    for name in ("gtk", "qt", "electron") if profile == "full" else (profile,):
        environment.update(PROFILES[name])
