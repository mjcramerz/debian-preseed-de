#!/usr/bin/python3
"""Safely extract a checksum-pinned managed Codex release archive."""

from __future__ import annotations

import argparse
import json
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
    """Raised when the Codex archive violates the extraction contract."""


def positive_integer(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


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


def classify_member(
    member: tarfile.TarInfo,
    *,
    binary_directory: str,
    schema_member: str,
) -> tuple[str, str | None]:
    name = member.name
    validate_member_metadata(member)

    if member.isdir():
        if member.size != 0:
            raise ArchiveValidationError(
                f"archive directory has unexpected payload bytes: {name!r}"
            )
        return ("metadata", None)
    if not member.isfile():
        raise ArchiveValidationError(
            f"archive member is not a regular file: {name!r}"
        )

    member_path = PurePosixPath(name)
    if len(member_path.parts) == 2 and member_path.parts[0] == binary_directory:
        binary_name = member_path.parts[1]
        validate_basename("archive binary name", binary_name)
        if member.size <= 0:
            raise ArchiveValidationError(f"archive binary is empty: {name!r}")
        return ("binary", binary_name)

    if name == schema_member:
        if member.size <= 0:
            raise ArchiveValidationError(f"archive schema is empty: {name!r}")
        return ("schema", name)

    return ("metadata", None)


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
    archive_path: Path,
    output_directory: Path,
    *,
    binary_directory: str,
    schema_member: str,
    maximum_extracted_bytes: int,
) -> None:
    binary_output_directory = output_directory / binary_directory
    binary_output_directory.mkdir(mode=0o700)
    os.chmod(binary_output_directory, 0o700)

    seen: set[str] = set()
    binary_names: set[str] = set()
    schema_extracted = False
    extracted_bytes = 0

    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive:
            if member.name in seen:
                raise ArchiveValidationError(
                    f"duplicate archive member: {member.name!r}"
                )
            seen.add(member.name)

            member_kind, output_name = classify_member(
                member,
                binary_directory=binary_directory,
                schema_member=schema_member,
            )
            if member_kind in ("directory", "metadata"):
                continue

            extracted_bytes += member.size
            if extracted_bytes > maximum_extracted_bytes:
                raise ArchiveValidationError(
                    "installed archive payload exceeds the configured byte limit"
                )

            source = archive.extractfile(member)
            if source is None:
                raise ArchiveValidationError(
                    f"unable to read archive member: {member.name!r}"
                )
            if member_kind == "binary":
                if output_name is None:
                    raise ArchiveValidationError("archive binary name is unavailable")
                destination_path = binary_output_directory / output_name
                output_mode = 0o755
                binary_names.add(output_name)
            else:
                destination_path = output_directory / schema_member
                output_mode = 0o644
                schema_extracted = True

            with source, create_output_file(destination_path, output_mode) as destination:
                copy_exact(source, destination, member.size)
                destination.flush()
                os.fsync(destination.fileno())

    if not binary_names:
        raise ArchiveValidationError(
            f"archive does not contain binaries below {binary_directory!r}"
        )
    if not schema_extracted:
        raise ArchiveValidationError(
            f"archive does not contain the required schema: {schema_member!r}"
        )

    schema_path = output_directory / schema_member
    try:
        with schema_path.open("r", encoding="utf-8") as schema_file:
            schema = json.load(schema_file)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveValidationError(
            f"Codex configuration schema is not valid UTF-8 JSON: {schema_member!r}"
        ) from exc
    if not isinstance(schema, dict):
        raise ArchiveValidationError(
            f"Codex configuration schema root is not an object: {schema_member!r}"
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "safely extract every direct regular file below the configured "
            "Codex binary directory plus the root configuration schema"
        )
    )
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--binary-directory", required=True)
    parser.add_argument("--schema-member", required=True)
    parser.add_argument(
        "--maximum-extracted-bytes",
        required=True,
        type=positive_integer,
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    archive_path = Path(arguments.archive)
    output_directory = Path(arguments.output_directory)

    try:
        validate_basename("binary directory", arguments.binary_directory)
        validate_basename("schema member", arguments.schema_member)
        require_direct_archive(archive_path)
        require_private_empty_directory(output_directory)
        extract_archive(
            archive_path,
            output_directory,
            binary_directory=arguments.binary_directory,
            schema_member=arguments.schema_member,
            maximum_extracted_bytes=arguments.maximum_extracted_bytes,
        )
    except (ArchiveValidationError, OSError, tarfile.TarError) as exc:
        print(f"fatal: invalid managed Codex archive: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
