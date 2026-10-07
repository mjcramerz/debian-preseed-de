"""Validated primitives for managed user-owned files and directories."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import tempfile

from .runtime import fail, validate_absolute_path


def resolve_home_relative_path(home_dir: str, relative_path: str) -> str:
    relative = pathlib.PurePosixPath(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        fail(f"invalid HOME-relative path: {relative_path or 'unset'}")
    path = os.path.join(home_dir, relative_path)
    validate_absolute_path("HOME-relative path", path)
    home_real = os.path.realpath(home_dir)
    path_real = os.path.realpath(path if os.path.lexists(path) else os.path.dirname(path))
    if os.path.commonpath((home_real, path_real)) != home_real:
        fail(f"HOME-relative path escapes HOME: {path}")
    return path


def ensure_user_owned_directory(
    path: str,
    mode: int,
    *,
    preserve_existing_mode: bool = False,
) -> None:
    existed = os.path.lexists(path)
    os.makedirs(path, mode=mode, exist_ok=True)
    directory_stat = os.lstat(path)
    if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
        fail(f"managed user path is not a real directory: {path}")
    if directory_stat.st_uid != os.getuid():
        fail(f"managed user directory is not owned by the current user: {path}")
    if not existed or not preserve_existing_mode:
        os.chmod(path, mode)


def ensure_managed_user_directory(
    home_dir: str,
    relative_path: str,
    mode: int,
    *,
    preserve_existing_mode: bool = False,
) -> None:
    path = resolve_home_relative_path(home_dir, relative_path)
    ensure_user_owned_directory(
        path,
        mode,
        preserve_existing_mode=preserve_existing_mode,
    )


def validate_seed_file(source_path: str) -> None:
    validate_absolute_path("seed file path", source_path)
    try:
        source_stat = os.lstat(source_path)
    except OSError as exc:
        fail(f"seed file is unavailable: {source_path}: {exc}")
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        fail(f"seed file must be a regular file, not a symlink: {source_path}")
    if not os.access(source_path, os.R_OK):
        fail(f"seed file is not readable: {source_path}")


def _require_user_file_descriptor(descriptor: int, path: str) -> os.stat_result:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        fail(f"managed user file must be a regular file with one link: {path}")
    if metadata.st_uid != os.getuid():
        fail(f"managed user file is not owned by the current user: {path}")
    return metadata


def ensure_managed_user_file(
    home_dir: str,
    relative_path: str,
    mode: int,
    seed_path: str | None,
) -> None:
    path = resolve_home_relative_path(home_dir, relative_path)
    parent = os.path.dirname(path)
    ensure_user_owned_directory(parent, 0o700)
    # Do not create through a dangling symlink and then reject it only after
    # writing. Existing files are opened without following links; validate and
    # chmod the same descriptor, not a subsequently replaced pathname.
    descriptor = -1
    created = False
    try:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            created = True
        except FileExistsError:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        _require_user_file_descriptor(descriptor, path)
        if created and seed_path is not None:
            validate_seed_file(seed_path)
            source_fd = os.open(seed_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(source_fd, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    fail(f"seed file must be a regular file: {seed_path}")
                with os.fdopen(os.dup(descriptor), "wb") as destination:
                    shutil.copyfileobj(source, destination, length=65536)
                    destination.flush()
                    os.fsync(destination.fileno())
        os.fchmod(descriptor, mode)
    except BaseException as exc:
        # A failed seed copy must not become a valid-looking empty file on the
        # next launch. Never unlink an entry that replaced our new inode.
        if created and descriptor >= 0:
            try:
                current = os.lstat(path)
                opened = os.fstat(descriptor)
                if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
                    os.unlink(path)
            except OSError:
                pass
        if isinstance(exc, OSError):
            fail(f"cannot initialize managed user file: {path}: {exc}")
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def replace_user_text_atomic(path: str, value: str, mode: int) -> None:
    validate_absolute_path("managed user text path", path)
    parent = os.path.dirname(path)
    ensure_user_owned_directory(parent, 0o700)
    if os.path.realpath(parent) != parent:
        fail(f"managed user text parent must not traverse symlinks: {parent}")
    if os.path.lexists(path):
        file_stat = os.lstat(path)
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            fail(f"managed user text destination must be a regular file: {path}")
        if file_stat.st_uid != os.getuid():
            fail(f"managed user text destination is not owned by the current user: {path}")

    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        dir=parent,
        text=True,
    )
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="")
        descriptor = -1
        with handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        fail(f"failed to replace managed user text: {path}: {exc}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.lexists(temporary_path):
            os.unlink(temporary_path)

    file_stat = os.lstat(path)
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        fail(f"managed user text replacement is not a regular file: {path}")
    if file_stat.st_uid != os.getuid():
        fail(f"managed user text replacement is not owned by the current user: {path}")
    os.chmod(path, mode)


def reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            fail(f"managed JSON contains a duplicate key: {key}")
        value[key] = item
    return value


def load_user_json_object(path: str, maximum_bytes: int) -> dict[str, object]:
    if isinstance(maximum_bytes, bool) or not isinstance(maximum_bytes, int) or maximum_bytes <= 0:
        fail("managed JSON byte limit must be a positive integer")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            metadata = _require_user_file_descriptor(handle.fileno(), path)
            if metadata.st_size > maximum_bytes:
                fail(f"managed JSON exceeds the size limit: {path}")
            # fstat alone does not bound a concurrently growing file. Read at
            # most the limit plus one byte from the validated descriptor.
            payload = handle.read(maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            fail(f"managed JSON exceeds the size limit: {path}")
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        fail(f"managed JSON is invalid: {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"managed JSON must contain an object: {path}")
    return value
