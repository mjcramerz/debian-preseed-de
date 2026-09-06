"""Locked, atomic managed-file transactions for firewall policy changes."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .validation import FirewallError


@dataclass(frozen=True)
class FirewallPaths:
    state_file: Path = Path("/etc/nftables/firewall-security.rules")
    fragment_file: Path = Path("/etc/nftables.d/95-firewall-security.nft")
    nft_conf: Path = Path("/etc/nftables.conf")
    lock_file: Path = Path("/run/lock/labwc-firewall-security.lock")


def validate_managed_file(label: str, path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FirewallError(f"{label} is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FirewallError(f"{label} cannot be a symbolic link")
    if metadata.st_uid != 0:
        raise FirewallError(f"{label} must be owned by root")
    if stat.S_IMODE(metadata.st_mode) != 0o644:
        raise FirewallError(f"{label} must use mode 0644")


def validate_nft_conf(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FirewallError(f"nftables entrypoint is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FirewallError(f"nftables entrypoint must be a regular file: {path}")
    if metadata.st_uid != 0:
        raise FirewallError(f"nftables entrypoint must be owned by root: {path}")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise FirewallError(
            f"nftables entrypoint cannot be group- or world-writable: {path}"
        )


@contextmanager
def locked(lock_file: Path, *, exclusive: bool) -> None:
    try:
        descriptor = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError as exc:
        raise FirewallError(f"cannot open firewall lock: {lock_file}: {exc}") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    except OSError as exc:
        raise FirewallError(f"cannot lock firewall state: {lock_file}: {exc}") from exc
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _write_temporary(directory: Path, prefix: str, content: str) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=prefix, dir=directory)
    except OSError as exc:
        raise FirewallError(
            f"cannot create firewall candidate in {directory}: {exc}"
        ) from exc
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise FirewallError(f"cannot write firewall candidate {path}: {exc}") from exc
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return path


def _backup(source: Path, prefix: str) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=prefix, dir="/tmp")
    except OSError as exc:
        raise FirewallError(f"cannot create firewall backup: {exc}") from exc
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            with source.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, handle)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise FirewallError(f"cannot create firewall backup: {exc}") from exc
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return path


def _atomic_restore(source: Path, target: Path) -> None:
    try:
        temporary = _write_temporary(
            target.parent,
            ".labwc-firewall-restore.",
            source.read_text(encoding="utf-8"),
        )
        os.replace(temporary, target)
    except OSError as exc:
        raise FirewallError(
            f"cannot restore managed firewall file {target}: {exc}"
        ) from exc


@dataclass
class PendingMutation:
    paths: FirewallPaths
    state_backup: Path
    fragment_backup: Path
    state_candidate: Path | None = None
    fragment_candidate: Path | None = None

    @classmethod
    def create(cls, paths: FirewallPaths) -> "PendingMutation":
        validate_managed_file("firewall state file", paths.state_file)
        validate_managed_file("firewall fragment", paths.fragment_file)
        validate_nft_conf(paths.nft_conf)
        return cls(
            paths=paths,
            state_backup=_backup(paths.state_file, "firewall-security-state."),
            fragment_backup=_backup(paths.fragment_file, "firewall-security-fragment."),
        )

    def write_candidates(self, state_content: str, fragment_content: str) -> None:
        self.state_candidate = _write_temporary(
            self.paths.state_file.parent,
            ".firewall-security-candidate.",
            state_content,
        )
        self.fragment_candidate = _write_temporary(
            self.paths.fragment_file.parent,
            ".95-firewall-security-candidate.",
            fragment_content,
        )

    def install(self) -> None:
        if self.state_candidate is None or self.fragment_candidate is None:
            raise FirewallError("firewall candidates were not prepared")
        try:
            os.replace(self.state_candidate, self.paths.state_file)
            self.state_candidate = None
            os.replace(self.fragment_candidate, self.paths.fragment_file)
            self.fragment_candidate = None
        except OSError as exc:
            raise FirewallError(
                "candidate nftables policy installation failed"
            ) from exc

    def rollback(self) -> None:
        _atomic_restore(self.state_backup, self.paths.state_file)
        _atomic_restore(self.fragment_backup, self.paths.fragment_file)

    def cleanup(self) -> None:
        for path in (
            self.state_candidate,
            self.fragment_candidate,
            self.state_backup,
            self.fragment_backup,
        ):
            if path is None:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
