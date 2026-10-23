#!/usr/bin/python3
"""Installer-only private Fangfrisch configuration; never contact a service."""
from __future__ import annotations

import configparser
import grp
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

DESTINATION = Path("/etc/fangfrisch.conf")
FEED = "https://urlhaus-api.abuse.ch/v2/files/exports/${auth_key}/urlhaus_clamav.ndb"


class PublicationFailure(Exception):
    def __init__(self, recovery: Path, attempted: bool):
        self.recovery = recovery
        self.attempted = attempted


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_private(path: Path, data: bytes, group: int = 0, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        os.fchown(stream.fileno(), 0, group)
        os.fchmod(stream.fileno(), mode)
        stream.flush()
        os.fsync(stream.fileno())


def file_identity(meta: os.stat_result) -> tuple:
    return (meta.st_dev, meta.st_ino, meta.st_mode, meta.st_uid, meta.st_gid,
            meta.st_nlink, meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)


def read_private(path: Path, limit: int, mode: int = 0o600) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0
                or stat.S_IMODE(meta.st_mode) != mode or meta.st_nlink != 1
                or meta.st_size > limit):
            raise ValueError("unsafe private input")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("oversized private input")
        return raw
    finally:
        os.close(fd)


def configure(stage: Path) -> None:
    if (os.geteuid() != 0 or stage.parent != Path("/tmp")
            or re.fullmatch(r"installer-fangfrisch\.[A-Za-z0-9_-]+", stage.name) is None):
        raise ValueError("invalid private staging directory")
    meta = stage.lstat()
    if (stage.resolve(strict=True) != stage or not stat.S_ISDIR(meta.st_mode)
            or meta.st_uid != 0 or stat.S_IMODE(meta.st_mode) != 0o700):
        raise ValueError("unsafe private staging directory")
    key = read_private(stage / "auth-key", 256).decode("ascii")
    if key and re.fullmatch(r"[A-Za-z0-9._~-]{1,256}", key) is None:
        raise ValueError("invalid Auth-Key")
    config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
    config.read_string(read_private(stage / "fangfrisch.conf", 16384).decode("utf-8"))
    config.set("urlhaus", "auth_key", key)
    config.set("urlhaus", "enabled", "yes" if key else "no")
    if (config.get("urlhaus", "url_urlhaus", raw=True) != FEED
            or config.defaults().get("log_format") != "%(levelname)s: %(message)s"
            or any(config.get(section, "log_method") != "console" for section in config)):
        raise ValueError("invalid feed or logging policy")
    text = io.StringIO()
    config.write(text)
    data = text.getvalue().encode("utf-8")
    group = grp.getgrnam("clamav").gr_gid
    destination = DESTINATION
    parent = destination.parent.lstat()
    if (destination.parent.resolve(strict=True) != destination.parent
            or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022):
        raise ValueError("unsafe configuration directory")
    previous = None
    previous_bytes = b""
    try:
        previous = destination.lstat()
    except FileNotFoundError:
        pass
    else:
        if (not stat.S_ISREG(previous.st_mode) or previous.st_uid != 0
                or previous.st_nlink != 1 or previous.st_mode & 0o022
                or previous.st_size > 16384):
            raise ValueError("unsafe previous configuration")
        fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if file_identity(os.fstat(stream.fileno())) != file_identity(previous):
                raise ValueError("previous configuration changed")
            previous_bytes = stream.read(16385)
        if len(previous_bytes) > 16384:
            raise ValueError("oversized previous configuration")
    # Retain exact previous bytes/metadata (or absence) if a rename or directory
    # sync has an uncertain outcome. No automatic retry may overwrite evidence.
    recovery = Path(tempfile.mkdtemp(prefix=".fangfrisch-recovery.", dir=destination.parent))
    attempted = False
    try:
        receipt = {"destination": str(destination), "previous_exists": previous is not None,
                   "previous_mode": stat.S_IMODE(previous.st_mode) if previous else None,
                   "previous_uid": previous.st_uid if previous else None,
                   "previous_gid": previous.st_gid if previous else None,
                   "previous_atime_ns": previous.st_atime_ns if previous else None,
                   "previous_mtime_ns": previous.st_mtime_ns if previous else None,
                   "previous_sha256": hashlib.sha256(previous_bytes).hexdigest(),
                   "candidate_sha256": hashlib.sha256(data).hexdigest()}
        write_private(recovery / "previous", previous_bytes)
        write_private(recovery / "state.json", json.dumps(receipt).encode("ascii"))
        write_private(recovery / "candidate", data, group, 0o640)
        sync_directory(recovery)
        sync_directory(destination.parent)
        try:
            current = destination.lstat()
        except FileNotFoundError:
            current = None
        if (None if current is None else file_identity(current)) != (None if previous is None else file_identity(previous)):
            raise ValueError("configuration replaced during publication")
        attempted = True
        os.replace(recovery / "candidate", destination)
        sync_directory(destination.parent)
        sync_directory(recovery)
        final = destination.lstat()
        if (not stat.S_ISREG(final.st_mode) or final.st_uid != 0 or final.st_gid != group
                or final.st_nlink != 1 or stat.S_IMODE(final.st_mode) != 0o640
                or read_private(destination, 16384, 0o640) != data):
            raise ValueError("configuration publication mismatch")
    except (OSError, ValueError):
        raise PublicationFailure(recovery, attempted) from None
    try:
        for name in ("previous", "state.json"):
            (recovery / name).unlink()
        recovery.rmdir()
        sync_directory(destination.parent)
    except OSError:
        # The candidate and its parent are already durable and verified.
        # Do not misreport an unconfirmed cleanup as an uncertain publication.
        print("managed_urlhaus cleanup=unconfirmed directory=" + str(destination.parent), file=sys.stderr)
    print("managed_urlhaus status=" + ("configured" if key else "disabled-no-key"))


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("invalid arguments")
        configure(Path(sys.argv[1]))
    except PublicationFailure as failure:
        outcome = "outcome-unknown" if failure.attempted else "failed"
        print("managed_urlhaus status=" + outcome + " recovery=" + str(failure.recovery), file=sys.stderr)
        raise SystemExit(125 if failure.attempted else 1)
    except (OSError, KeyError, ValueError, configparser.Error):
        # ConfigParser and filesystem exceptions can contain credential data.
        print("fatal: cannot publish private Fangfrisch configuration", file=sys.stderr)
        raise SystemExit(1)
