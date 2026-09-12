"""Installed-package trust manifest and path validation."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
import stat


PACKAGE_ROOT = Path("/usr/local/lib/python3.14/dist-packages")
PACKAGE_DIRECTORY = PACKAGE_ROOT / "labwc_managed_app"
PACKAGE_TRUST_CHAIN = (
    Path("/usr"),
    Path("/usr/local"),
    Path("/usr/local/lib"),
    Path("/usr/local/lib/python3.14"),
    PACKAGE_ROOT,
    PACKAGE_DIRECTORY,
)

CORE_MODULES = (
    "__init__.py",
    "bootstrap.py",
    "browsers.py",
    "bubblewrap.py",
    "cli.py",
    "commands.py",
    "dbus_proxy.py",
    "electron.py",
    "environment.py",
    "events.py",
    "identity.py",
    "integrity.py",
    "mounts.py",
    "network_namespace.py",
    "profiles.py",
    "recovery.py",
    "runtime.py",
    "sandbox.py",
    "session.py",
    "user_state.py",
)
COMPATIBILITY_MODULES = ("wayland_compat.py", "wayland_compat_runtime.py")
INNER_RUNTIME_MODULES = (
    "__init__.py",
    "bootstrap.py",
    "events.py",
    "integrity.py",
    "runtime.py",
    "wayland_compat_runtime.py",
)
ALL_MODULES = tuple(dict.fromkeys((*CORE_MODULES, *COMPATIBILITY_MODULES, "generic.py")))


class PackageScope(StrEnum):
    """Import surface required by one trusted package entrypoint."""

    ELECTRON = "electron"
    WAYLAND = "wayland"
    NATIVE = "native"
    WAYLAND_COMPAT = "wayland-compat"
    COMPAT_RUNTIME = "compat-runtime"


MODULES_BY_SCOPE = {
    PackageScope.ELECTRON: (*CORE_MODULES, "generic.py"),
    PackageScope.WAYLAND: (*CORE_MODULES, "generic.py"),
    PackageScope.NATIVE: CORE_MODULES,
    PackageScope.WAYLAND_COMPAT: ALL_MODULES,
    PackageScope.COMPAT_RUNTIME: INNER_RUNTIME_MODULES,
}


class IntegrityError(RuntimeError):
    """Raised when the installed package no longer satisfies its trust contract."""


def system_owner(anchor: Path = Path("/usr")) -> tuple[int, int]:
    metadata = _lstat(anchor, "managed system-owner anchor")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise IntegrityError(
            f"managed system-owner anchor is not a real directory: {anchor}"
        )
    if stat.S_IMODE(metadata.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
        raise IntegrityError(
            "managed system-owner anchor is writable by an untrusted account: "
            f"{anchor}: mode={stat.S_IMODE(metadata.st_mode):04o}"
        )
    return metadata.st_uid, metadata.st_gid


def _lstat(path: Path, label: str) -> object:
    try:
        return path.lstat()
    except OSError as exc:
        raise IntegrityError(f"{label} is unavailable: {path}: {exc}") from exc


def require_managed_directory(
    path: Path,
    *,
    owner: tuple[int, int],
    exact_mode: int | None = None,
) -> None:
    metadata = _lstat(path, "managed application package directory")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise IntegrityError(
            f"managed application package directory has the wrong type: {path}"
        )
    _require_owner_and_mode(path, metadata, owner=owner, exact_mode=exact_mode)


def require_managed_module(path: Path, *, owner: tuple[int, int]) -> None:
    metadata = _lstat(path, "managed application package module")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise IntegrityError(
            f"managed application package module has the wrong type: {path}"
        )
    if metadata.st_nlink != 1:
        raise IntegrityError(
            "managed application package module has an unsafe hard-link count: "
            f"{path}: links={metadata.st_nlink}"
        )
    _require_owner_and_mode(path, metadata, owner=owner, exact_mode=0o644)


def _require_owner_and_mode(
    path: Path,
    metadata: object,
    *,
    owner: tuple[int, int],
    exact_mode: int | None,
) -> None:
    actual_owner = (metadata.st_uid, metadata.st_gid)
    if actual_owner != owner:
        raise IntegrityError(
            "managed application package path has the wrong owner: "
            f"{path}: expected={owner[0]}:{owner[1]} "
            f"actual={actual_owner[0]}:{actual_owner[1]}"
        )
    actual_mode = stat.S_IMODE(metadata.st_mode)
    if actual_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise IntegrityError(
            "managed application package path is group/other writable: "
            f"{path}: mode={actual_mode:04o}"
        )
    if exact_mode is not None and actual_mode != exact_mode:
        raise IntegrityError(
            "managed application package path has the wrong mode: "
            f"{path}: expected={exact_mode:04o} actual={actual_mode:04o}"
        )


def _validate_manifest() -> None:
    if len(ALL_MODULES) != len(set(ALL_MODULES)):
        raise IntegrityError("managed application package manifest contains duplicates")
    if set(MODULES_BY_SCOPE) != set(PackageScope):
        raise IntegrityError("managed application package scope manifest is incomplete")
    for scope, modules in MODULES_BY_SCOPE.items():
        unknown = set(modules).difference(ALL_MODULES)
        if unknown:
            raise IntegrityError(
                f"managed application package scope {scope.value} contains unknown modules: "
                + ", ".join(sorted(unknown))
            )


def _path_type(metadata: object) -> str:
    mode = metadata.st_mode
    if stat.S_ISLNK(mode):
        return "symbolic link"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "regular file"
    if stat.S_ISFIFO(mode):
        return "FIFO"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "character device"
    if stat.S_ISBLK(mode):
        return "block device"
    return "unknown node"


def _validate_directory_inventory(package_directory: Path) -> None:
    try:
        entries = tuple(package_directory.iterdir())
    except OSError as exc:
        raise IntegrityError(
            f"managed application package inventory is unavailable: {package_directory}: {exc}"
        ) from exc

    expected_modules = set(ALL_MODULES)
    actual_names = {entry.name for entry in entries}
    for entry in sorted(entries, key=lambda candidate: candidate.name):
        metadata = _lstat(entry, "managed application package inventory entry")
        if entry.name not in expected_modules:
            raise IntegrityError(
                "managed application package contains an unexpected entry: "
                f"{entry}: type={_path_type(metadata)}"
            )
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise IntegrityError(
                "managed application package module has the wrong type: "
                f"{entry}: type={_path_type(metadata)}"
            )

    missing = expected_modules.difference(actual_names)
    if missing:
        raise IntegrityError(
            "managed application package inventory does not match the manifest: "
            + "missing="
            + ",".join(sorted(missing))
        )


def validate_package(
    scope: PackageScope | str,
    *,
    package_directory: Path = PACKAGE_DIRECTORY,
    owner: tuple[int, int] | None = None,
    trust_chain: Iterable[Path] | None = None,
) -> None:
    """Validate the exact import surface needed by an entrypoint.

    Custom package directories used by tests validate only that directory unless
    an explicit trust chain is supplied. The installed path validates every
    parent from /usr through the package directory.
    """

    _validate_manifest()
    try:
        selected_scope = PackageScope(scope)
    except ValueError as exc:
        raise IntegrityError(f"unknown managed application package scope: {scope}") from exc

    expected_owner = system_owner() if owner is None else owner
    if trust_chain is None:
        directories = (
            PACKAGE_TRUST_CHAIN
            if package_directory == PACKAGE_DIRECTORY
            else (package_directory,)
        )
    else:
        directories = tuple(trust_chain)
    if not directories or directories[-1] != package_directory:
        raise IntegrityError(
            "managed application package trust chain must end at the package directory"
        )

    for directory in directories:
        require_managed_directory(
            directory,
            owner=expected_owner,
            exact_mode=0o755 if directory == package_directory else None,
        )
    _validate_directory_inventory(package_directory)
    for module_name in MODULES_BY_SCOPE[selected_scope]:
        require_managed_module(package_directory / module_name, owner=expected_owner)
