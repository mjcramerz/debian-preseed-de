#!/usr/bin/python3
"""Install checksum-pinned DotSlash and uv release archives as the desktop user.

This helper runs inside the target chroot under the managed desktop account. It
downloads only the profile-selected official archives, validates their exact
size and SHA-256 digest, rejects unsafe tar members, stages every selected
binary on the destination filesystem, and publishes the complete set only
after all selected archives have passed validation.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import platform
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
from dataclasses import dataclass
from typing import NoReturn, Sequence


CURL = pathlib.Path("/usr/bin/curl")
SEMVER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
LOWER_HEX_RE = re.compile(r"[0-9a-f]+\Z")


class RustToolInstallError(RuntimeError):
    """Expected policy, download, archive, or installation failure."""


@dataclass(frozen=True)
class Artifact:
    name: str
    version: str
    url: str
    sha256: str
    expected_bytes: int
    filename: str
    architecture: str
    archive_members: tuple[str, ...]
    binary_members: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class InstallPolicy:
    install_root: pathlib.Path
    download_timeout_seconds: int
    max_archive_members: int
    max_extracted_bytes: int
    dotslash_source_build: bool
    uv_source_build: bool
    dotslash: Artifact
    uv: Artifact

    @property
    def selected_artifacts(self) -> tuple[Artifact, ...]:
        selected: list[Artifact] = []
        if not self.dotslash_source_build:
            selected.append(self.dotslash)
        if not self.uv_source_build:
            selected.append(self.uv)
        return tuple(selected)


def fail(message: str) -> NoReturn:
    raise RustToolInstallError(message)


def semantic_version(value: str, label: str) -> str:
    if SEMVER_RE.fullmatch(value) is None:
        fail(f"{label} must be a semantic version")
    return value


def lower_hex(value: str, label: str, length: int) -> str:
    if len(value) != length or LOWER_HEX_RE.fullmatch(value) is None:
        fail(f"{label} must contain {length} lowercase hexadecimal characters")
    return value


def positive_integer(value: str, label: str, maximum: int) -> int:
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        fail(f"{label} must be a positive decimal integer")
    parsed = int(value)
    if parsed < 1 or parsed > maximum:
        fail(f"{label} is outside the supported range")
    return parsed


def source_build_flag(value: str, label: str) -> bool:
    if value not in {"0", "1"}:
        fail(f"{label} must be 0 or 1")
    return value == "1"


def managed_path(value: str, label: str) -> pathlib.Path:
    pure_path = pathlib.PurePosixPath(value)
    if (
        not pure_path.is_absolute()
        or str(pure_path) != value
        or value == "/"
        or ".." in pure_path.parts
        or "//" in value
    ):
        fail(f"{label} must be one normalized absolute path")
    return pathlib.Path(value)


def archive_token(value: str, label: str) -> str:
    pure_path = pathlib.PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "//" in value
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or str(pure_path) != value
    ):
        fail(f"{label} contains an unsafe archive path: {value!r}")
    return value


def archive_tokens(value: str, label: str) -> tuple[str, ...]:
    result = tuple(archive_token(item, label) for item in value.split())
    if not result or len(result) != len(set(result)):
        fail(f"{label} must contain unique archive paths")
    return result


def validate_https_url(value: str, label: str, expected_path: str) -> None:
    if any(character.isspace() for character in value) or "\\" in value or "%" in value:
        fail(f"{label} contains unsupported URL syntax")
    parsed = urllib.parse.urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        fail(f"{label} contains an invalid port")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != expected_path
        or "//" in parsed.path
    ):
        fail(f"{label} must identify the expected official GitHub release asset")


def require_program(path: pathlib.Path, label: str) -> None:
    try:
        path_stat = path.stat()
    except OSError:
        fail(f"required {label} is unavailable: {path}")
    if not stat.S_ISREG(path_stat.st_mode) or not os.access(path, os.X_OK):
        fail(f"required {label} is not executable: {path}")


def require_real_directory(path: pathlib.Path, label: str) -> os.stat_result:
    try:
        path_stat = path.lstat()
    except OSError:
        fail(f"{label} is unavailable: {path}")
    if not stat.S_ISDIR(path_stat.st_mode):
        fail(f"{label} must be a real directory: {path}")
    return path_stat


def require_install_root(policy: InstallPolicy) -> pathlib.Path:
    if os.geteuid() == 0:
        fail("the prebuilt Rust tool installer must not run as root")
    if platform.machine() != "x86_64":
        fail(f"unsupported Rust tool architecture: {platform.machine()}")

    environment_root = os.environ.get("CARGO_INSTALL_ROOT", "")
    if environment_root != str(policy.install_root):
        fail("the requested install root does not match CARGO_INSTALL_ROOT")

    root_stat = require_real_directory(policy.install_root, "Cargo install root")
    if root_stat.st_uid != os.geteuid():
        fail("the Cargo install root must be owned by the invoking account")

    bin_dir = policy.install_root / "bin"
    if os.path.lexists(bin_dir):
        bin_stat = require_real_directory(bin_dir, "Cargo install binary directory")
        if bin_stat.st_uid != os.geteuid():
            fail("the Cargo install binary directory must be owned by the invoking account")
    else:
        try:
            bin_dir.mkdir(mode=0o755)
            bin_dir.chmod(0o755)
        except OSError:
            fail("unable to create the Cargo install binary directory")
    return bin_dir


def run_checked(
    arguments: Sequence[str],
    label: str,
    *,
    timeout: int,
    environment: dict[str, str] | None = None,
) -> None:
    try:
        result = subprocess.run(
            list(arguments),
            check=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        fail(f"{label} exceeded its {timeout}-second timeout")
    except OSError:
        fail(f"{label} could not start")
    if result.returncode != 0:
        fail(f"{label} failed with status {result.returncode}")


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        fail(f"unable to hash downloaded artifact: {path.name}")
    return digest.hexdigest()


def download_artifact(
    policy: InstallPolicy,
    artifact: Artifact,
    download_dir: pathlib.Path,
) -> pathlib.Path:
    destination = download_dir / artifact.filename
    curl_home = download_dir / ".curl-home"
    if os.path.lexists(curl_home):
        curl_home_stat = require_real_directory(curl_home, "private curl home")
        if curl_home_stat.st_uid != os.geteuid():
            fail("the private curl home must be owned by the invoking account")
    else:
        curl_home.mkdir(mode=0o700)
        curl_home.chmod(0o700)
    curl_environment = {
        "HOME": str(curl_home),
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    run_checked(
        [
            str(CURL),
            "--disable",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--tlsv1.2",
            "--retry",
            "3",
            "--retry-delay",
            "2",
            "--connect-timeout",
            "15",
            "--max-time",
            str(policy.download_timeout_seconds),
            "--max-filesize",
            str(artifact.expected_bytes),
            "--output",
            str(destination),
            artifact.url,
        ],
        f"downloading {artifact.name} {artifact.version}",
        timeout=policy.download_timeout_seconds + 30,
        environment=curl_environment,
    )
    try:
        observed_bytes = destination.stat().st_size
    except OSError:
        fail(f"downloaded {artifact.name} archive is unavailable")
    if observed_bytes != artifact.expected_bytes:
        fail(
            f"{artifact.name} archive size mismatch: expected "
            f"{artifact.expected_bytes}, got {observed_bytes}"
        )
    if file_sha256(destination) != artifact.sha256:
        fail(f"{artifact.name} SHA-256 mismatch")
    return destination


def validated_tar_members(
    policy: InstallPolicy,
    artifact: Artifact,
    archive_path: pathlib.Path,
) -> tuple[tarfile.TarFile, dict[str, tarfile.TarInfo]]:
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
        infos = archive.getmembers()
    except (OSError, tarfile.TarError):
        fail(f"{artifact.name} release is not a valid gzip-compressed tar archive")
    if not infos or len(infos) > policy.max_archive_members:
        archive.close()
        fail(f"{artifact.name} archive has an invalid member count")

    members: dict[str, tarfile.TarInfo] = {}
    expanded_bytes = 0
    for info in infos:
        archive_token(info.name, f"{artifact.name} archive")
        if info.name in members:
            archive.close()
            fail(f"{artifact.name} archive contains a duplicate member: {info.name}")
        if info.isdir():
            pass
        elif info.isfile() and not info.issparse():
            if info.size < 1:
                archive.close()
                fail(f"{artifact.name} archive contains an empty binary: {info.name}")
            expanded_bytes += info.size
            if expanded_bytes > policy.max_extracted_bytes:
                archive.close()
                fail(f"{artifact.name} archive exceeds the expanded-byte ceiling")
        else:
            archive.close()
            fail(f"{artifact.name} archive contains a non-regular member: {info.name}")
        members[info.name] = info

    if set(members) != set(artifact.archive_members):
        archive.close()
        fail(f"{artifact.name} archive members do not match the profile policy")
    for source_name, _destination_name in artifact.binary_members:
        if not members[source_name].isfile():
            archive.close()
            fail(f"{artifact.name} binary member is not a regular file: {source_name}")
    return archive, members


def copy_tar_binary(
    archive: tarfile.TarFile,
    info: tarfile.TarInfo,
    destination: pathlib.Path,
) -> None:
    try:
        source = archive.extractfile(info)
    except (KeyError, OSError, tarfile.TarError):
        source = None
    if source is None:
        fail(f"unable to read archive member: {info.name}")
    copied_bytes = 0
    try:
        with source, destination.open("xb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                copied_bytes += len(chunk)
                if copied_bytes > info.size:
                    fail(f"archive member expanded past its declared size: {info.name}")
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if copied_bytes != info.size:
            fail(f"archive member size changed during extraction: {info.name}")
        with destination.open("rb") as binary_handle:
            if binary_handle.read(4) != b"\x7fELF":
                fail(f"archive member is not an ELF executable: {info.name}")
        destination.chmod(0o755)
    except OSError:
        fail(f"unable to stage archive member: {info.name}")


def prepare_artifact(
    policy: InstallPolicy,
    artifact: Artifact,
    archive_path: pathlib.Path,
    staging_bin: pathlib.Path,
) -> None:
    archive, members = validated_tar_members(policy, artifact, archive_path)
    try:
        for source_name, destination_name in artifact.binary_members:
            copy_tar_binary(
                archive,
                members[source_name],
                staging_bin / destination_name,
            )
    finally:
        archive.close()


def install_selected_artifacts(policy: InstallPolicy) -> None:
    selected = policy.selected_artifacts
    if not selected:
        fail("the prebuilt Rust tool installer was called without a selected archive")
    require_program(CURL, "curl")
    bin_dir = require_install_root(policy)

    destination_names = [
        destination_name
        for artifact in selected
        for _source_name, destination_name in artifact.binary_members
    ]
    if len(destination_names) != len(set(destination_names)):
        fail("selected Rust tool archives publish duplicate binary names")
    for destination_name in destination_names:
        destination = bin_dir / destination_name
        if os.path.lexists(destination):
            fail(f"fresh-install Rust tool binary already exists: {destination}")

    published: list[pathlib.Path] = []
    try:
        with tempfile.TemporaryDirectory(
            prefix=".installer-rust-tools-",
            dir=policy.install_root,
        ) as temporary_name:
            temporary_root = pathlib.Path(temporary_name)
            temporary_root.chmod(0o700)
            download_dir = temporary_root / "downloads"
            staging_bin = temporary_root / "bin"
            download_dir.mkdir(mode=0o700)
            staging_bin.mkdir(mode=0o700)

            for artifact in selected:
                archive_path = download_artifact(policy, artifact, download_dir)
                prepare_artifact(policy, artifact, archive_path, staging_bin)

            for destination_name in destination_names:
                staged_binary = staging_bin / destination_name
                destination = bin_dir / destination_name
                if os.path.lexists(destination):
                    fail(f"Rust tool destination changed before publication: {destination}")
                os.replace(staged_binary, destination)
                published.append(destination)

            directory_descriptor = os.open(bin_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)

        for destination in published:
            destination_stat = destination.lstat()
            if (
                not stat.S_ISREG(destination_stat.st_mode)
                or destination_stat.st_uid != os.geteuid()
                or destination_stat.st_nlink != 1
                or stat.S_IMODE(destination_stat.st_mode) != 0o755
            ):
                fail(f"published Rust tool binary is unsafe: {destination}")
    except BaseException:
        for destination in reversed(published):
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def parse_arguments(argv: Sequence[str]) -> InstallPolicy:
    parser = argparse.ArgumentParser(
        description="Install profile-pinned prebuilt DotSlash and uv archives",
    )
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--download-timeout-seconds", required=True)
    parser.add_argument("--max-archive-members", required=True)
    parser.add_argument("--max-extracted-bytes", required=True)
    for tool in ("dotslash", "uv"):
        parser.add_argument(f"--{tool}-source-build", required=True)
        parser.add_argument(f"--{tool}-version", required=True)
        parser.add_argument(f"--{tool}-url", required=True)
        parser.add_argument(f"--{tool}-sha256", required=True)
        parser.add_argument(f"--{tool}-bytes", required=True)
        parser.add_argument(f"--{tool}-architecture", required=True)
        parser.add_argument(f"--{tool}-archive-filename", required=True)
        parser.add_argument(f"--{tool}-archive-files", required=True)
    parser.add_argument("--uv-archive-root", required=True)
    args = parser.parse_args(argv)

    dotslash_version = semantic_version(args.dotslash_version, "DotSlash version")
    dotslash_filename = archive_token(
        args.dotslash_archive_filename,
        "DotSlash archive filename",
    )
    if dotslash_filename != f"dotslash-linux-musl.x86_64.v{dotslash_version}.tar.gz":
        fail("DotSlash archive filename does not match its version")
    if args.dotslash_architecture != "linux-musl.x86_64":
        fail("DotSlash archive architecture must remain linux-musl.x86_64")
    dotslash_archive_files = archive_tokens(
        args.dotslash_archive_files,
        "DotSlash archive files",
    )
    if dotslash_archive_files != ("dotslash",):
        fail("DotSlash archive must contain only the dotslash binary")
    validate_https_url(
        args.dotslash_url,
        "DotSlash URL",
        f"/facebook/dotslash/releases/download/v{dotslash_version}/{dotslash_filename}",
    )

    uv_version = semantic_version(args.uv_version, "uv version")
    uv_filename = archive_token(args.uv_archive_filename, "uv archive filename")
    uv_archive_root = archive_token(args.uv_archive_root, "uv archive root")
    if uv_filename != "uv-x86_64-unknown-linux-gnu.tar.gz":
        fail("uv archive filename must identify the official Linux GNU x86-64 release")
    if uv_archive_root != "uv-x86_64-unknown-linux-gnu":
        fail("uv archive root must identify the official Linux GNU x86-64 release")
    if args.uv_architecture != "x86_64-unknown-linux-gnu":
        fail("uv archive architecture must remain x86_64-unknown-linux-gnu")
    uv_archive_files = archive_tokens(args.uv_archive_files, "uv archive files")
    if uv_archive_files != ("uv", "uvx"):
        fail("uv archive file policy must contain uv and uvx")
    validate_https_url(
        args.uv_url,
        "uv URL",
        f"/astral-sh/uv/releases/download/{uv_version}/{uv_filename}",
    )

    return InstallPolicy(
        install_root=managed_path(args.install_root, "Cargo install root"),
        download_timeout_seconds=positive_integer(
            args.download_timeout_seconds,
            "download timeout",
            86_400,
        ),
        max_archive_members=positive_integer(
            args.max_archive_members,
            "maximum archive members",
            100_000,
        ),
        max_extracted_bytes=positive_integer(
            args.max_extracted_bytes,
            "maximum extracted bytes",
            8 * 1024**3,
        ),
        dotslash_source_build=source_build_flag(
            args.dotslash_source_build,
            "DEVOPS_DOTSLASH_SOURCE_BUILD",
        ),
        uv_source_build=source_build_flag(
            args.uv_source_build,
            "DEVOPS_UV_SOURCE_BUILD",
        ),
        dotslash=Artifact(
            name="DotSlash",
            version=dotslash_version,
            url=args.dotslash_url,
            sha256=lower_hex(args.dotslash_sha256, "DotSlash SHA-256", 64),
            expected_bytes=positive_integer(
                args.dotslash_bytes,
                "DotSlash archive bytes",
                2**31,
            ),
            filename=dotslash_filename,
            architecture=args.dotslash_architecture,
            archive_members=dotslash_archive_files,
            binary_members=(("dotslash", "dotslash"),),
        ),
        uv=Artifact(
            name="uv",
            version=uv_version,
            url=args.uv_url,
            sha256=lower_hex(args.uv_sha256, "uv SHA-256", 64),
            expected_bytes=positive_integer(
                args.uv_bytes,
                "uv archive bytes",
                2**31,
            ),
            filename=uv_filename,
            architecture=args.uv_architecture,
            archive_members=(
                uv_archive_root,
                *(f"{uv_archive_root}/{item}" for item in uv_archive_files),
            ),
            binary_members=tuple(
                (f"{uv_archive_root}/{item}", item) for item in uv_archive_files
            ),
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        policy = parse_arguments(sys.argv[1:] if argv is None else argv)
        install_selected_artifacts(policy)
    except RustToolInstallError as error:
        print(f"fatal: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
