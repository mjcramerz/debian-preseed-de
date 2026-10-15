"""Private, atomic installation UUID overrides keyed by physical directory."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid

STATE_DIRECTORY = "/data/codex/runtime/project-identities"
MAX_RECORD_BYTES = 32768


class ProjectIdentityError(RuntimeError):
    """Unsafe or invalid project identity state; never silently replace it."""


def ensure_installation_id_target(path: str) -> None:
    """Initialize a missing native default, independently of any project UUID."""
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise ProjectIdentityError("native installation ID must not traverse symlinks")
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write((str(uuid.uuid4()) + "\n").encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
    metadata = os.stat(path, follow_symlinks=False)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_nlink > 1 or stat.S_IMODE(metadata.st_mode) not in {0o600, 0o644}):
        raise ProjectIdentityError("native installation ID must be an account-owned mode 0600 or 0644 file without hard links")


def _require_file(metadata: os.stat_result) -> None:
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_nlink > 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
        raise ProjectIdentityError("project identity must be an account-owned mode 0600 file without hard links")


def _open_state_directory(path: str, *, create: bool) -> int | None:
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise ProjectIdentityError("project identity directory must be an absolute path without symlinks")
    created = False
    if create:
        try:
            os.mkdir(path, 0o700)
            created = True
        except FileExistsError:
            pass
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        if not create:
            return None
        raise
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise ProjectIdentityError("project identity directory must be account-owned")
        if created:
            # The shared runtime parent is setgid; keep newly created state private.
            os.fchmod(descriptor, 0o700)
            parent_fd = os.open(
                os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        # A concurrent creator may not yet have cleared inherited setgid. It
        # grants no additional access when all group/other bits remain zero.
        if stat.S_IMODE(os.fstat(descriptor).st_mode) not in {0o700, 0o2700}:
            raise ProjectIdentityError("project identity directory must have mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def select_project_uuid(
    directory: str,
    *,
    rotate: bool = False,
    state_directory: str = STATE_DIRECTORY,
) -> str | None:
    """Read an override, or atomically replace it only on an explicit rotation.

    No entry means the caller must retain its native installation_id. Ordinary
    reads create no state. Concurrent readers see one complete old or new entry;
    concurrent rotations leave the last atomically published value for later runs.
    """
    try:
        if not os.path.isabs(directory):
            raise ProjectIdentityError("project directory must be absolute")
        project = os.path.realpath(directory, strict=True)
        if not os.path.isdir(project):
            raise ProjectIdentityError("project path must be a directory")
        name = hashlib.sha256(os.fsencode(project)).hexdigest() + ".json"
        directory_fd = _open_state_directory(state_directory, create=rotate)
        if directory_fd is None:
            return None
        try:
            try:
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                if not rotate:
                    return None
            else:
                with os.fdopen(descriptor, "rb") as handle:
                    _require_file(os.fstat(handle.fileno()))
                    if not rotate:
                        data = handle.read(MAX_RECORD_BYTES + 1)
                        if len(data) > MAX_RECORD_BYTES:
                            raise ProjectIdentityError("project identity exceeds the size limit")
                        try:
                            record = json.loads(data)
                            if (not isinstance(record, dict)
                                    or set(record) != {"version", "directory", "installation_id"}
                                    or type(record["version"]) is not int or record["version"] != 1
                                    or record["directory"] != project):
                                raise ValueError("invalid record")
                            value = record["installation_id"]
                            parsed = uuid.UUID(value)
                            if parsed.version != 4 or str(parsed) != value:
                                raise ValueError("invalid UUID")
                        except (ValueError, TypeError, AttributeError, UnicodeError) as exc:
                            raise ProjectIdentityError("invalid project identity record") from exc
                        return value

            value = str(uuid.uuid4())
            data = (json.dumps({"version": 1, "directory": project,
                                "installation_id": value}, sort_keys=True) + "\n").encode("ascii")
            if len(data) > MAX_RECORD_BYTES:
                raise ProjectIdentityError("project identity exceeds the size limit")
            temporary = f".{name}.{uuid.uuid4().hex}.tmp"
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=directory_fd,
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                os.fsync(directory_fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
            return value
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ProjectIdentityError(f"cannot access project identity state: {exc.strerror}") from exc
