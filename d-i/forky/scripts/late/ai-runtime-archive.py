#!/usr/bin/python3
"""Validate and safely extract a checksum-pinned AI runtime archive."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
from typing import BinaryIO


COPY_CHUNK_BYTES = 1024 * 1024
SAFE_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class ArchiveValidationError(Exception):
    """Raised when a managed AI runtime archive violates its contract."""


def positive_integer(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def unique_values(label: str, values: list[str]) -> tuple[str, ...]:
    if not values:
        raise ArchiveValidationError(f"at least one {label} is required")
    if len(values) != len(set(values)):
        raise ArchiveValidationError(f"duplicate {label} value")
    return tuple(values)


def validate_basename(label: str, name: str) -> None:
    if SAFE_BASENAME.fullmatch(name) is None:
        raise ArchiveValidationError(f"{label} is unsafe: {name!r}")


def validate_relative_member_name(name: str, *, is_directory: bool) -> None:
    if not name or "\x00" in name or "\\" in name:
        raise ArchiveValidationError(f"unsafe archive member name: {name!r}")

    member_path = PurePosixPath(name)
    if member_path.is_absolute():
        raise ArchiveValidationError(f"absolute archive member path: {name!r}")
    if any(part in ("", ".", "..") for part in member_path.parts):
        raise ArchiveValidationError(f"non-normalized archive member path: {name!r}")

    normalized = str(member_path)
    if name != normalized and not (is_directory and name == f"{normalized}/"):
        raise ArchiveValidationError(f"non-normalized archive member path: {name!r}")


def require_private_empty_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ArchiveValidationError(
            f"output directory does not exist: {path}"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise ArchiveValidationError(f"output path is not a direct directory: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ArchiveValidationError(
            f"output directory is not private to the invoking user: {path}"
        )
    if metadata.st_uid != os.geteuid():
        raise ArchiveValidationError(
            f"output directory is not owned by the invoking user: {path}"
        )
    try:
        next(path.iterdir())
    except StopIteration:
        return
    raise ArchiveValidationError(f"output directory is not empty: {path}")


def require_direct_archive(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ArchiveValidationError(f"archive does not exist: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ArchiveValidationError(f"archive is not a direct regular file: {path}")
    if metadata.st_size <= 0:
        raise ArchiveValidationError(f"archive is empty: {path}")


def validate_member_metadata(member: tarfile.TarInfo) -> None:
    name = member.name
    if member.pax_headers:
        raise ArchiveValidationError(
            f"archive member uses unsupported PAX headers: {name!r}"
        )
    if member.sparse is not None:
        raise ArchiveValidationError(
            f"archive member uses unsupported sparse metadata: {name!r}"
        )
    if member.linkname:
        raise ArchiveValidationError(
            f"archive member carries an unexpected link target: {name!r}"
        )
    validate_relative_member_name(name, is_directory=member.isdir())
    if not member.isdir() and not member.isfile():
        raise ArchiveValidationError(
            f"archive member is not a directory or regular file: {name!r}"
        )
    if member.isdir() and member.size != 0:
        raise ArchiveValidationError(
            f"archive directory has unexpected payload bytes: {name!r}"
        )
    if member.size < 0:
        raise ArchiveValidationError(
            f"archive member has a negative size: {name!r}"
        )


def inspect_archive(
    archive: tarfile.TarFile,
    *,
    archive_root: str,
    required_directories: tuple[str, ...],
    required_binaries: tuple[str, ...],
    maximum_extracted_bytes: int,
    maximum_members: int,
) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    for member_count, member in enumerate(archive, start=1):
        if member_count > maximum_members:
            raise ArchiveValidationError(
                "archive contains too many members: "
                f"at least {member_count} > {maximum_members}"
            )
        members.append(member)
    if not members:
        raise ArchiveValidationError("archive is empty")

    allowed_directories = set(required_directories)
    expected_binaries = set(required_binaries)
    seen: set[str] = set()
    explicit_directories: set[str] = set()
    actual_binaries: set[str] = set()
    payload_counts = {name: 0 for name in required_directories}
    extracted_bytes = 0

    for member in members:
        validate_member_metadata(member)
        if member.name in seen:
            raise ArchiveValidationError(
                f"duplicate archive member: {member.name!r}"
            )
        seen.add(member.name)

        member_path = PurePosixPath(member.name)
        parts = member_path.parts
        if not parts or parts[0] != archive_root:
            raise ArchiveValidationError(
                f"archive member is outside the required root {archive_root!r}: "
                f"{member.name!r}"
            )

        if len(parts) == 1:
            if not member.isdir():
                raise ArchiveValidationError(
                    f"archive root is not a directory: {member.name!r}"
                )
            explicit_directories.add(member.name)
            continue

        top_directory = parts[1]
        if top_directory not in allowed_directories:
            raise ArchiveValidationError(
                f"archive member uses an unexpected top-level directory: "
                f"{member.name!r}"
            )

        if len(parts) == 2:
            if not member.isdir():
                raise ArchiveValidationError(
                    f"archive top-level entry is not a directory: {member.name!r}"
                )
            explicit_directories.add(member.name)
            continue

        if member.isdir():
            explicit_directories.add(member.name)
        else:
            extracted_bytes += member.size
            if extracted_bytes > maximum_extracted_bytes:
                raise ArchiveValidationError(
                    "archive payload exceeds the configured extracted-byte limit"
                )
            payload_counts[top_directory] += 1

        if top_directory != "bin":
            continue
        if len(parts) != 3 or not member.isfile():
            raise ArchiveValidationError(
                f"archive binary entry is not a direct regular file: {member.name!r}"
            )
        binary_name = parts[2]
        validate_basename("archive binary name", binary_name)
        if binary_name not in expected_binaries:
            raise ArchiveValidationError(
                f"archive contains an unexpected binary: {binary_name!r}"
            )
        if member.size <= 0:
            raise ArchiveValidationError(
                f"archive binary is empty: {member.name!r}"
            )
        actual_binaries.add(binary_name)

    required_root = archive_root
    if required_root not in explicit_directories:
        raise ArchiveValidationError(
            f"archive is missing its explicit root directory: {archive_root!r}"
        )
    for directory_name in required_directories:
        required_member = f"{archive_root}/{directory_name}"
        if required_member not in explicit_directories:
            raise ArchiveValidationError(
                f"archive is missing required directory: {required_member!r}"
            )
        if payload_counts[directory_name] <= 0:
            raise ArchiveValidationError(
                f"archive required directory is empty: {required_member!r}"
            )

    if actual_binaries != expected_binaries:
        missing = sorted(expected_binaries - actual_binaries)
        raise ArchiveValidationError(
            f"archive is missing required binaries: {', '.join(missing)}"
        )

    for member in members:
        if not member.isfile():
            continue
        parent = str(PurePosixPath(member.name).parent)
        if parent not in explicit_directories:
            raise ArchiveValidationError(
                f"archive file parent directory is not explicit: {member.name!r}"
            )

    return members


def copy_exact(source: BinaryIO, destination: BinaryIO, expected_bytes: int) -> None:
    remaining = expected_bytes
    while remaining:
        chunk = source.read(min(COPY_CHUNK_BYTES, remaining))
        if not chunk:
            raise ArchiveValidationError(
                "archive member ended before its advertised byte count"
            )
        destination.write(chunk)
        remaining -= len(chunk)
    if source.read(1):
        raise ArchiveValidationError(
            "archive member exceeded its advertised byte count"
        )


def create_output_file(path: Path, mode: int) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    os.fchmod(descriptor, mode)
    return os.fdopen(descriptor, "wb")


def extract_archive(
    archive: tarfile.TarFile,
    output_directory: Path,
    members: list[tarfile.TarInfo],
    *,
    archive_root: str,
) -> None:
    directory_members = sorted(
        (member for member in members if member.isdir() and member.name != archive_root),
        key=lambda member: len(PurePosixPath(member.name).parts),
    )
    for member in directory_members:
        relative_path = PurePosixPath(member.name).relative_to(archive_root)
        destination = output_directory.joinpath(*relative_path.parts)
        destination.mkdir(mode=0o755)
        os.chmod(destination, 0o755)

    for member in members:
        if not member.isfile():
            continue
        relative_path = PurePosixPath(member.name).relative_to(archive_root)
        destination = output_directory.joinpath(*relative_path.parts)
        output_mode = 0o755 if relative_path.parts[0] == "bin" else 0o644
        source = archive.extractfile(member)
        if source is None:
            raise ArchiveValidationError(
                f"unable to read archive member: {member.name!r}"
            )
        with source, create_output_file(destination, output_mode) as target:
            copy_exact(source, target, member.size)
            target.flush()
            os.fsync(target.fileno())


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "validate a managed AI runtime tar.gz archive and extract its "
            "sanitized root contents into a private empty directory"
        )
    )
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument(
        "--required-directory",
        action="append",
        default=[],
        help="required and exclusively allowed top-level archive directory",
    )
    parser.add_argument(
        "--required-binary",
        action="append",
        default=[],
        help="required and exclusively allowed direct member of bin/",
    )
    parser.add_argument(
        "--maximum-extracted-bytes",
        required=True,
        type=positive_integer,
    )
    parser.add_argument(
        "--maximum-members",
        required=True,
        type=positive_integer,
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    archive_path = Path(arguments.archive)
    output_directory = Path(arguments.output_directory)

    try:
        validate_basename("archive root", arguments.archive_root)
        required_directories = unique_values(
            "required directory", arguments.required_directory
        )
        required_binaries = unique_values(
            "required binary", arguments.required_binary
        )
        for directory_name in required_directories:
            validate_basename("required directory", directory_name)
        for binary_name in required_binaries:
            validate_basename("required binary", binary_name)
        if "bin" not in required_directories:
            raise ArchiveValidationError("required directories must include 'bin'")

        require_direct_archive(archive_path)
        require_private_empty_directory(output_directory)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = inspect_archive(
                archive,
                archive_root=arguments.archive_root,
                required_directories=required_directories,
                required_binaries=required_binaries,
                maximum_extracted_bytes=arguments.maximum_extracted_bytes,
                maximum_members=arguments.maximum_members,
            )
            extract_archive(
                archive,
                output_directory,
                members,
                archive_root=arguments.archive_root,
            )
    except (ArchiveValidationError, OSError, tarfile.TarError) as exc:
        print(f"fatal: invalid managed AI runtime archive: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
