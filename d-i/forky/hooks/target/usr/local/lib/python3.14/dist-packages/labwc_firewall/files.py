"""Locked, atomic file transactions for firewall policy changes."""

from __future__ import annotations

from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from .validation import FirewallError, OutcomeUnknown


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
        descriptor = os.open(lock_file, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as exc:
        raise FirewallError(f"cannot open firewall lock: {lock_file}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
                or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600):
            raise FirewallError(f"unsafe firewall lock file: {lock_file}")
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    except OSError as exc:
        raise FirewallError(f"cannot lock firewall state: {lock_file}: {exc}") from exc
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_temporary(directory: Path, prefix: str, content: str, *, mode: int = 0o644) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=prefix, dir=directory)
    except OSError as exc:
        raise FirewallError(
            f"cannot create firewall candidate in {directory}: {exc}"
        ) from exc
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(path.parent)
    except BaseException as exc:
        with suppress(OSError):
            path.unlink()
        if isinstance(exc, OSError):
            raise FirewallError(f"cannot write firewall candidate {path}: {exc}") from exc
        raise
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return path


def _backup(source: Path, prefix: str, directory: Path) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=prefix, dir=directory)
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
        _sync_directory(directory)
    except BaseException as exc:
        with suppress(OSError):
            path.unlink()
        if isinstance(exc, OSError):
            raise FirewallError(f"cannot create firewall backup: {exc}") from exc
        raise
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return path


def _atomic_restore(source: Path, target: Path) -> None:
    temporary = None
    try:
        temporary = _write_temporary(
            target.parent,
            ".labwc-firewall-restore.",
            source.read_text(encoding="utf-8"),
        )
        os.replace(temporary, target)
        _sync_directory(target.parent)
    except (OSError, UnicodeError) as exc:
        raise FirewallError(
            f"cannot restore managed firewall file {target}: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink()


@dataclass
class PendingMutation:
    paths: FirewallPaths
    state_backup: Path
    fragment_backup: Path
    recovery_directory: Path
    state_candidate: Path | None = None
    fragment_candidate: Path | None = None
    rollback_failed: bool = field(default=False, init=False)

    @classmethod
    def create(cls, paths: FirewallPaths) -> "PendingMutation":
        validate_managed_file("firewall state file", paths.state_file)
        validate_managed_file("firewall fragment", paths.fragment_file)
        validate_nft_conf(paths.nft_conf)
        # A retained transaction must be reconciled before another mutation.
        # The existing caller lock serializes creation and this bounded scan.
        with os.scandir(paths.state_file.parent) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 4096:
                    raise FirewallError("firewall directory entry limit exceeded")
                if entry.name.startswith('.labwc-firewall-recovery.'):
                    raise OutcomeUnknown(f"pending firewall recovery requires reconciliation: {entry.path}")
        directory = Path(tempfile.mkdtemp(prefix='.labwc-firewall-recovery.', dir=paths.state_file.parent))
        os.chmod(directory, 0o700)
        _sync_directory(directory.parent)
        try:
            state_backup = _backup(paths.state_file, "state.", directory)
            fragment_backup = _backup(paths.fragment_file, "fragment.", directory)
            receipt = _write_temporary(directory, '.receipt.', json.dumps({
                'format': 1,
                'state': str(paths.state_file), 'state_backup': state_backup.name,
                'fragment': str(paths.fragment_file), 'fragment_backup': fragment_backup.name,
                'nft_conf': str(paths.nft_conf),
                'recovery': 'reconcile manager completion and owned live policy before retry',
            }, sort_keys=True) + '\n', mode=0o600)
            os.replace(receipt, directory / 'receipt.json')
            _sync_directory(directory)
        except BaseException as failure:
            # No publication occurred. Remove only the private snapshot created
            # here; a failed cleanup remains visible to the pending guard.
            try:
                for path in directory.iterdir():
                    path.unlink()
                directory.rmdir()
                _sync_directory(directory.parent)
            except OSError as cleanup_error:
                failure.add_note(f"snapshot cleanup failed; recovery retained at {directory}: {cleanup_error}")
            raise
        return cls(
            paths=paths,
            state_backup=state_backup,
            fragment_backup=fragment_backup,
            recovery_directory=directory,
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
        # Publication can commit and then be interrupted, including during
        # directory synchronization. Retain the snapshot until the transaction
        # owner proves application or restoration, even before live reload.
        self.rollback_failed = True
        try:
            os.replace(self.state_candidate, self.paths.state_file)
            self.state_candidate = None
            _sync_directory(self.paths.state_file.parent)
            os.replace(self.fragment_candidate, self.paths.fragment_file)
            self.fragment_candidate = None
            _sync_directory(self.paths.fragment_file.parent)
        except OSError as exc:
            raise FirewallError(
                "candidate nftables policy installation failed"
            ) from exc

    def rollback(self) -> None:
        # Retain recovery material even if restoration is interrupted.
        self.rollback_failed = True
        errors = []
        for backup, target in (
            (self.state_backup, self.paths.state_file),
            (self.fragment_backup, self.paths.fragment_file),
        ):
            try:
                _atomic_restore(backup, target)
            except FirewallError as exc:
                errors.append(str(exc))
        # The live-policy owner clears this only after required restoration.
        if errors:
            raise FirewallError(
                "; ".join(errors)
                + f"; recovery backups retained: {self.state_backup}, {self.fragment_backup}"
            )

    def cleanup(self) -> None:
        paths = [self.state_candidate, self.fragment_candidate]
        if not self.rollback_failed:
            paths.extend((self.state_backup, self.fragment_backup))
            paths.extend(self.recovery_directory / name for name in ('live.nft', 'live.json'))
        for path in paths:
            if path is None:
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if not self.rollback_failed:
            try:
                (self.recovery_directory / 'receipt.json').unlink(missing_ok=True)
                self.recovery_directory.rmdir()
                _sync_directory(self.recovery_directory.parent)
            except OSError:
                # A retained directory deliberately blocks a new transaction.
                pass
