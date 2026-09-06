#!/usr/bin/python3
"""Install checksum-pinned upstream DevOps tools into isolated roots.

This helper runs only inside the target chroot from the class-gated DevOps
late helper.  It downloads into a private directory below ``/usr/local/lib``,
validates every archive before extraction, prepares all tool roots without
publishing them, and rolls back the complete set if final verification fails.
"""

from __future__ import annotations

import base64
import configparser
import email.parser
import hashlib
import json
import os
import pathlib
import platform
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass
from typing import NoReturn, Sequence


CURL = pathlib.Path("/usr/bin/curl")
ARGCOMPLETE = pathlib.Path("/usr/bin/register-python-argcomplete")
MAKE = pathlib.Path("/usr/bin/make")
BASH = pathlib.Path("/bin/bash")
PYTHON = pathlib.Path("/usr/bin/python3")
PERL = pathlib.Path("/usr/bin/perl")
MAX_POLICY_BYTES = 64 * 1024
SEMVER_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
LOWER_HEX_RE = re.compile(r"[0-9a-f]+\Z")
ANSIBLE_CONSOLE_SCRIPTS = {
    "ansible": "ansible.cli.adhoc:main",
    "ansible-config": "ansible.cli.config:main",
    "ansible-console": "ansible.cli.console:main",
    "ansible-doc": "ansible.cli.doc:main",
    "ansible-galaxy": "ansible.cli.galaxy:main",
    "ansible-inventory": "ansible.cli.inventory:main",
    "ansible-playbook": "ansible.cli.playbook:main",
    "ansible-pull": "ansible.cli.pull:main",
    "ansible-test": "ansible_test._util.target.cli.ansible_test_cli_stub:main",
    "ansible-vault": "ansible.cli.vault:main",
}
ANSIBLE_CORE_REQUIREMENTS = frozenset(
    {
        "jinja2>=3.1.0",
        "PyYAML>=5.1",
        "cryptography",
        "packaging",
        "resolvelib<2.0.0,>=0.8.0",
    }
)

POLICY_KEYS = frozenset(
    {
        "DEVOPS_UPSTREAM_POLICY_SCHEMA",
        "DEVOPS_UPSTREAM_ARCHITECTURE",
        "DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS",
        "DEVOPS_UPSTREAM_NPM_TIMEOUT_SECONDS",
        "DEVOPS_UPSTREAM_MAKE_TIMEOUT_SECONDS",
        "DEVOPS_UPSTREAM_VERIFY_TIMEOUT_SECONDS",
        "DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS",
        "DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES",
        "DEVOPS_DENO_VERSION",
        "DEVOPS_DENO_URL",
        "DEVOPS_DENO_SHA256",
        "DEVOPS_DENO_BYTES",
        "DEVOPS_DENO_ARCHITECTURE",
        "DEVOPS_DENO_ARCHIVE_FILENAME",
        "DEVOPS_DENO_ARCHIVE_FILES",
        "DEVOPS_DENO_INSTALL_ROOT",
        "DEVOPS_DENO_BINARY_PATH",
        "DEVOPS_YT_DLP_VERSION",
        "DEVOPS_YT_DLP_URL",
        "DEVOPS_YT_DLP_SHA256",
        "DEVOPS_YT_DLP_BYTES",
        "DEVOPS_YT_DLP_ARCHITECTURE",
        "DEVOPS_YT_DLP_ARCHIVE_FILENAME",
        "DEVOPS_YT_DLP_INSTALL_ROOT",
        "DEVOPS_YT_DLP_BINARY_PATH",
        "DEVOPS_YT_DLP_PAYLOAD_PATH",
        "DEVOPS_ANSIBLE_CORE_VERSION",
        "DEVOPS_ANSIBLE_CORE_URL",
        "DEVOPS_ANSIBLE_CORE_SHA256",
        "DEVOPS_ANSIBLE_CORE_BYTES",
        "DEVOPS_ANSIBLE_CORE_ARCHITECTURE",
        "DEVOPS_ANSIBLE_CORE_ARCHIVE_FILENAME",
        "DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS",
        "DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT",
        "DEVOPS_ANSIBLE_CORE_MAX_ARCHIVE_MEMBERS",
        "DEVOPS_ANSIBLE_CORE_MAX_EXTRACTED_BYTES",
        "DEVOPS_ANSIBLE_CORE_INSTALL_ROOT",
        "DEVOPS_ANSIBLE_CORE_BINARY_PATH",
        "DEVOPS_OPENTOFU_VERSION",
        "DEVOPS_OPENTOFU_URL",
        "DEVOPS_OPENTOFU_SHA256",
        "DEVOPS_OPENTOFU_BYTES",
        "DEVOPS_OPENTOFU_ARCHITECTURE",
        "DEVOPS_OPENTOFU_ARCHIVE_FILENAME",
        "DEVOPS_OPENTOFU_ARCHIVE_FILES",
        "DEVOPS_OPENTOFU_INSTALL_ROOT",
        "DEVOPS_OPENTOFU_BINARY_PATH",
        "DEVOPS_TERRAFORM_VERSION",
        "DEVOPS_TERRAFORM_URL",
        "DEVOPS_TERRAFORM_SHA256",
        "DEVOPS_TERRAFORM_BYTES",
        "DEVOPS_TERRAFORM_ARCHITECTURE",
        "DEVOPS_TERRAFORM_ARCHIVE_FILENAME",
        "DEVOPS_TERRAFORM_ARCHIVE_FILES",
        "DEVOPS_TERRAFORM_INSTALL_ROOT",
        "DEVOPS_TERRAFORM_BINARY_PATH",
        "DEVOPS_PACKER_VERSION",
        "DEVOPS_PACKER_URL",
        "DEVOPS_PACKER_SHA256",
        "DEVOPS_PACKER_BYTES",
        "DEVOPS_PACKER_ARCHITECTURE",
        "DEVOPS_PACKER_ARCHIVE_FILENAME",
        "DEVOPS_PACKER_ARCHIVE_FILES",
        "DEVOPS_PACKER_INSTALL_ROOT",
        "DEVOPS_PACKER_BINARY_PATH",
        "DEVOPS_WRANGLER_VERSION",
        "DEVOPS_WRANGLER_URL",
        "DEVOPS_WRANGLER_SHA512",
        "DEVOPS_WRANGLER_NPM_INTEGRITY",
        "DEVOPS_WRANGLER_BYTES",
        "DEVOPS_WRANGLER_ARCHITECTURE",
        "DEVOPS_WRANGLER_ARCHIVE_FILENAME",
        "DEVOPS_WRANGLER_ARCHIVE_ROOT",
        "DEVOPS_WRANGLER_PACKAGE_NAME",
        "DEVOPS_WRANGLER_NODE_REQUIREMENT",
        "DEVOPS_WRANGLER_NODE_ROOT",
        "DEVOPS_WRANGLER_NPM_REGISTRY_URL",
        "DEVOPS_WRANGLER_INSTALL_ROOT",
        "DEVOPS_WRANGLER_BINARY_PATH",
        "DEVOPS_APTLY_RELEASE_VERSION",
        "DEVOPS_APTLY_RELEASE_URL",
        "DEVOPS_APTLY_RELEASE_SHA256",
        "DEVOPS_APTLY_RELEASE_BYTES",
        "DEVOPS_APTLY_RELEASE_ARCHITECTURE",
        "DEVOPS_APTLY_RELEASE_ARCHIVE_FILENAME",
        "DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT",
        "DEVOPS_APTLY_RELEASE_ARCHIVE_FILES",
        "DEVOPS_APTLY_INSTALL_ROOT",
        "DEVOPS_APTLY_BINARY_PATH",
        "DEVOPS_OSC_RELEASE_VERSION",
        "DEVOPS_OSC_RELEASE_URL",
        "DEVOPS_OSC_RELEASE_SHA256",
        "DEVOPS_OSC_RELEASE_BYTES",
        "DEVOPS_OSC_RELEASE_ARCHITECTURE",
        "DEVOPS_OSC_RELEASE_ARCHIVE_FILENAME",
        "DEVOPS_OSC_RELEASE_PACKAGE_ROOT",
        "DEVOPS_OSC_RELEASE_DIST_INFO_ROOT",
        "DEVOPS_OSC_INSTALL_ROOT",
        "DEVOPS_OSC_BINARY_PATH",
        "DEVOPS_OBS_BUILD_TAG",
        "DEVOPS_OBS_BUILD_COMMIT",
        "DEVOPS_OBS_BUILD_URL",
        "DEVOPS_OBS_BUILD_SHA256",
        "DEVOPS_OBS_BUILD_BYTES",
        "DEVOPS_OBS_BUILD_ARCHITECTURE",
        "DEVOPS_OBS_BUILD_ARCHIVE_FILENAME",
        "DEVOPS_OBS_BUILD_ARCHIVE_ROOT",
        "DEVOPS_OBS_BUILD_INSTALL_ROOT",
        "DEVOPS_OBS_BUILD_BINARY_PATH",
        "DEVOPS_OBS_BUILD_ENTRYPOINTS",
    }
)


class ToolInstallError(RuntimeError):
    """Expected validation or installation failure."""


@dataclass(frozen=True)
class DownloadArtifact:
    key: str
    name: str
    version: str
    url: str
    filename: str
    expected_bytes: int
    digest_algorithm: str
    expected_digest: str
    architecture: str


@dataclass(frozen=True)
class Artifact(DownloadArtifact):
    install_root: pathlib.Path
    binary_path: pathlib.Path


@dataclass(frozen=True)
class InstallPolicy:
    architecture: str
    download_timeout_seconds: int
    npm_timeout_seconds: int
    make_timeout_seconds: int
    verify_timeout_seconds: int
    max_archive_members: int
    max_extracted_bytes: int
    install_parent: pathlib.Path
    deno: Artifact
    deno_archive_files: tuple[str, ...]
    yt_dlp: Artifact
    yt_dlp_payload_path: pathlib.Path
    ansible_core: Artifact
    ansible_core_package_roots: tuple[str, ...]
    ansible_core_dist_info_root: str
    ansible_core_max_archive_members: int
    ansible_core_max_extracted_bytes: int
    opentofu: Artifact
    opentofu_archive_files: tuple[str, ...]
    terraform: Artifact
    terraform_archive_files: tuple[str, ...]
    packer: Artifact
    packer_archive_files: tuple[str, ...]
    wrangler: Artifact
    wrangler_npm_integrity: str
    wrangler_archive_root: str
    wrangler_package_name: str
    wrangler_node_requirement: str
    wrangler_node_root: pathlib.Path
    wrangler_npm_registry_url: str
    aptly: Artifact
    aptly_archive_root: str
    aptly_archive_files: tuple[str, ...]
    osc: Artifact
    osc_package_root: str
    osc_dist_info_root: str
    obs_build: Artifact
    obs_build_tag: str
    obs_build_commit: str
    obs_build_archive_root: str
    obs_build_entrypoints: tuple[str, ...]

    @property
    def artifacts(self) -> tuple[Artifact, ...]:
        return (
            self.deno,
            self.yt_dlp,
            self.ansible_core,
            self.opentofu,
            self.terraform,
            self.packer,
            self.wrangler,
            self.aptly,
            self.osc,
            self.obs_build,
        )

    @property
    def download_artifacts(self) -> tuple[DownloadArtifact, ...]:
        return (
            self.deno,
            self.yt_dlp,
            self.ansible_core,
            self.opentofu,
            self.terraform,
            self.packer,
            self.wrangler,
            self.aptly,
            self.osc,
            self.obs_build,
        )


def fail(message: str) -> NoReturn:
    raise ToolInstallError(message)


def positive_integer(values: dict[str, str], key: str, maximum: int) -> int:
    value = values[key]
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        fail(f"{key} must be a positive decimal integer")
    parsed = int(value)
    if parsed < 1 or parsed > maximum:
        fail(f"{key} is outside the supported range")
    return parsed


def semantic_version(values: dict[str, str], key: str) -> str:
    value = values[key]
    if SEMVER_RE.fullmatch(value) is None:
        fail(f"{key} must be a semantic version")
    return value


def lower_hex(values: dict[str, str], key: str, length: int) -> str:
    value = values[key]
    if len(value) != length or LOWER_HEX_RE.fullmatch(value) is None:
        fail(f"{key} must contain {length} lowercase hexadecimal characters")
    return value


def managed_path(values: dict[str, str], key: str) -> pathlib.Path:
    value = values[key]
    path = pathlib.PurePosixPath(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or ".." in path.parts
        or value == "/"
        or "//" in value
    ):
        fail(f"{key} must be a normalized absolute path")
    return pathlib.Path(value)


def archive_token(value: str, label: str) -> str:
    parts = pathlib.PurePosixPath(value).parts
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "//" in value
        or any(part in {"", ".", ".."} for part in parts)
        or str(pathlib.PurePosixPath(value)) != value
    ):
        fail(f"{label} contains an unsafe archive path: {value!r}")
    return value


def archive_tokens(values: dict[str, str], key: str) -> tuple[str, ...]:
    result = tuple(
        archive_token(item, key) for item in values[key].split()
    )
    if not result or len(result) != len(set(result)):
        fail(f"{key} must contain unique archive paths")
    return result


def validate_https_url(
    value: str,
    label: str,
    *,
    hostname: str,
    expected_path: str | None = None,
    required_prefix: str | None = None,
    required_suffix: str | None = None,
) -> None:
    if any(char.isspace() for char in value) or "\\" in value or "%" in value:
        fail(f"{label} contains unsupported URL syntax")
    parsed = urllib.parse.urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        fail(f"{label} contains an invalid port")
    if (
        parsed.scheme != "https"
        or parsed.hostname != hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or "//" in parsed.path
        or "/../" in f"/{parsed.path.strip('/')}/"
    ):
        fail(f"{label} must be one normalized HTTPS URL on {hostname}")
    if expected_path is not None and parsed.path != expected_path:
        fail(f"{label} path does not match its release policy")
    if required_prefix is not None and not parsed.path.startswith(required_prefix):
        fail(f"{label} path does not have the required prefix")
    if required_suffix is not None and not parsed.path.endswith(required_suffix):
        fail(f"{label} path does not have the required suffix")


def artifact(
    values: dict[str, str],
    *,
    key: str,
    name: str,
    prefix: str,
    version_key: str,
    digest_key: str,
    digest_algorithm: str,
    digest_length: int,
    architecture_key: str,
    install_root_key: str,
    binary_path_key: str,
) -> Artifact:
    install_root = managed_path(values, install_root_key)
    binary_path = managed_path(values, binary_path_key)
    try:
        binary_path.relative_to(install_root)
    except ValueError:
        fail(f"{binary_path_key} must remain below {install_root_key}")
    return Artifact(
        key=key,
        name=name,
        version=semantic_version(values, version_key)
        if version_key != "DEVOPS_OBS_BUILD_TAG"
        else values[version_key],
        url=values[f"{prefix}_URL"],
        filename=archive_token(values[f"{prefix}_ARCHIVE_FILENAME"], f"{prefix}_ARCHIVE_FILENAME"),
        expected_bytes=positive_integer(values, f"{prefix}_BYTES", 2**31),
        digest_algorithm=digest_algorithm,
        expected_digest=lower_hex(values, digest_key, digest_length),
        architecture=values[architecture_key],
        install_root=install_root,
        binary_path=binary_path,
    )


def load_policy(path: pathlib.Path) -> InstallPolicy:
    if not path.is_absolute():
        fail("policy path must be absolute")
    flags = os.O_RDONLY
    if not hasattr(os, "O_NOFOLLOW"):
        fail("the target kernel does not support no-follow policy reads")
    flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        fail(f"unable to open the upstream DevOps policy safely: {path}")
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            fail("upstream DevOps policy must be a regular file")
        if file_stat.st_uid != os.geteuid() or file_stat.st_gid != os.getegid():
            fail("upstream DevOps policy must be owned by the invoking identity")
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            fail("upstream DevOps policy must have mode 0600")
        if file_stat.st_size < 2 or file_stat.st_size > MAX_POLICY_BYTES:
            fail("upstream DevOps policy has an invalid size")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            values = json.load(handle)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("upstream DevOps policy is not valid UTF-8 JSON")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(values, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in values.items()
    ):
        fail("upstream DevOps policy must be a string-to-string object")
    if set(values) != POLICY_KEYS:
        missing = sorted(POLICY_KEYS - set(values))
        extra = sorted(set(values) - POLICY_KEYS)
        fail(f"upstream DevOps policy keys do not match schema; missing={missing} extra={extra}")
    if values["DEVOPS_UPSTREAM_POLICY_SCHEMA"] != "4":
        fail("unsupported upstream DevOps policy schema")
    architecture = values["DEVOPS_UPSTREAM_ARCHITECTURE"]
    if architecture != "x86_64":
        fail("upstream DevOps policy architecture must be x86_64")

    deno = artifact(
        values,
        key="deno",
        name="Deno",
        prefix="DEVOPS_DENO",
        version_key="DEVOPS_DENO_VERSION",
        digest_key="DEVOPS_DENO_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_DENO_ARCHITECTURE",
        install_root_key="DEVOPS_DENO_INSTALL_ROOT",
        binary_path_key="DEVOPS_DENO_BINARY_PATH",
    )
    yt_dlp = artifact(
        values,
        key="yt-dlp",
        name="yt-dlp",
        prefix="DEVOPS_YT_DLP",
        version_key="DEVOPS_YT_DLP_VERSION",
        digest_key="DEVOPS_YT_DLP_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_YT_DLP_ARCHITECTURE",
        install_root_key="DEVOPS_YT_DLP_INSTALL_ROOT",
        binary_path_key="DEVOPS_YT_DLP_BINARY_PATH",
    )
    ansible_core = artifact(
        values,
        key="ansible-core",
        name="Ansible Core",
        prefix="DEVOPS_ANSIBLE_CORE",
        version_key="DEVOPS_ANSIBLE_CORE_VERSION",
        digest_key="DEVOPS_ANSIBLE_CORE_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_ANSIBLE_CORE_ARCHITECTURE",
        install_root_key="DEVOPS_ANSIBLE_CORE_INSTALL_ROOT",
        binary_path_key="DEVOPS_ANSIBLE_CORE_BINARY_PATH",
    )
    opentofu = artifact(
        values,
        key="opentofu",
        name="OpenTofu",
        prefix="DEVOPS_OPENTOFU",
        version_key="DEVOPS_OPENTOFU_VERSION",
        digest_key="DEVOPS_OPENTOFU_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_OPENTOFU_ARCHITECTURE",
        install_root_key="DEVOPS_OPENTOFU_INSTALL_ROOT",
        binary_path_key="DEVOPS_OPENTOFU_BINARY_PATH",
    )
    terraform = artifact(
        values,
        key="terraform",
        name="Terraform",
        prefix="DEVOPS_TERRAFORM",
        version_key="DEVOPS_TERRAFORM_VERSION",
        digest_key="DEVOPS_TERRAFORM_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_TERRAFORM_ARCHITECTURE",
        install_root_key="DEVOPS_TERRAFORM_INSTALL_ROOT",
        binary_path_key="DEVOPS_TERRAFORM_BINARY_PATH",
    )
    packer = artifact(
        values,
        key="packer",
        name="Packer",
        prefix="DEVOPS_PACKER",
        version_key="DEVOPS_PACKER_VERSION",
        digest_key="DEVOPS_PACKER_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_PACKER_ARCHITECTURE",
        install_root_key="DEVOPS_PACKER_INSTALL_ROOT",
        binary_path_key="DEVOPS_PACKER_BINARY_PATH",
    )
    wrangler = artifact(
        values,
        key="wrangler",
        name="Wrangler",
        prefix="DEVOPS_WRANGLER",
        version_key="DEVOPS_WRANGLER_VERSION",
        digest_key="DEVOPS_WRANGLER_SHA512",
        digest_algorithm="sha512",
        digest_length=128,
        architecture_key="DEVOPS_WRANGLER_ARCHITECTURE",
        install_root_key="DEVOPS_WRANGLER_INSTALL_ROOT",
        binary_path_key="DEVOPS_WRANGLER_BINARY_PATH",
    )
    aptly = artifact(
        values,
        key="aptly",
        name="Aptly",
        prefix="DEVOPS_APTLY_RELEASE",
        version_key="DEVOPS_APTLY_RELEASE_VERSION",
        digest_key="DEVOPS_APTLY_RELEASE_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_APTLY_RELEASE_ARCHITECTURE",
        install_root_key="DEVOPS_APTLY_INSTALL_ROOT",
        binary_path_key="DEVOPS_APTLY_BINARY_PATH",
    )
    osc = artifact(
        values,
        key="osc",
        name="osc",
        prefix="DEVOPS_OSC_RELEASE",
        version_key="DEVOPS_OSC_RELEASE_VERSION",
        digest_key="DEVOPS_OSC_RELEASE_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_OSC_RELEASE_ARCHITECTURE",
        install_root_key="DEVOPS_OSC_INSTALL_ROOT",
        binary_path_key="DEVOPS_OSC_BINARY_PATH",
    )
    obs_build = artifact(
        values,
        key="obs-build",
        name="obs-build",
        prefix="DEVOPS_OBS_BUILD",
        version_key="DEVOPS_OBS_BUILD_TAG",
        digest_key="DEVOPS_OBS_BUILD_SHA256",
        digest_algorithm="sha256",
        digest_length=64,
        architecture_key="DEVOPS_OBS_BUILD_ARCHITECTURE",
        install_root_key="DEVOPS_OBS_BUILD_INSTALL_ROOT",
        binary_path_key="DEVOPS_OBS_BUILD_BINARY_PATH",
    )

    required_roots = {
        deno.install_root: pathlib.Path("/usr/local/lib/deno/bin/deno"),
        yt_dlp.install_root: pathlib.Path("/usr/local/lib/yt-dlp/bin/yt-dlp"),
        ansible_core.install_root: pathlib.Path("/usr/local/lib/ansible/bin/ansible"),
        opentofu.install_root: pathlib.Path("/usr/local/lib/opentufo/bin/tofu"),
        terraform.install_root: pathlib.Path(
            "/usr/local/lib/hashicorp/terraform/bin/terraform"
        ),
        packer.install_root: pathlib.Path(
            "/usr/local/lib/hashicorp/packer/bin/packer"
        ),
        wrangler.install_root: pathlib.Path(
            "/usr/local/lib/wrangler/node_modules/.bin/wrangler"
        ),
        aptly.install_root: pathlib.Path("/usr/local/lib/aptly/bin/aptly"),
        osc.install_root: pathlib.Path("/usr/local/lib/osc/bin/osc"),
        obs_build.install_root: pathlib.Path("/usr/local/lib/obs-build/bin/build"),
    }
    expected_roots = {
        pathlib.Path("/usr/local/lib/deno"),
        pathlib.Path("/usr/local/lib/yt-dlp"),
        pathlib.Path("/usr/local/lib/ansible"),
        pathlib.Path("/usr/local/lib/opentufo"),
        pathlib.Path("/usr/local/lib/hashicorp/terraform"),
        pathlib.Path("/usr/local/lib/hashicorp/packer"),
        pathlib.Path("/usr/local/lib/wrangler"),
        pathlib.Path("/usr/local/lib/aptly"),
        pathlib.Path("/usr/local/lib/osc"),
        pathlib.Path("/usr/local/lib/obs-build"),
    }
    if set(required_roots) != expected_roots:
        fail("upstream DevOps install roots do not match the managed roots")
    artifacts = (
        deno,
        yt_dlp,
        ansible_core,
        opentofu,
        terraform,
        packer,
        wrangler,
        aptly,
        osc,
        obs_build,
    )
    for item in artifacts:
        if item.binary_path != required_roots[item.install_root]:
            fail(f"{item.name} binary path does not match its managed root")
    install_parents = {item.install_root.parent for item in artifacts}
    if install_parents != {
        pathlib.Path("/usr/local/lib"),
        pathlib.Path("/usr/local/lib/hashicorp"),
    }:
        fail("upstream DevOps install roots do not match managed parent paths")

    if values["DEVOPS_DENO_ARCHITECTURE"] != "x86_64-unknown-linux-gnu":
        fail("Deno architecture policy is unsupported")
    if tuple(int(part) for part in deno.version.split(".")) < (2, 3, 0):
        fail("Deno version is too old for the managed yt-dlp-ejs runtime")
    if deno.filename != "deno-x86_64-unknown-linux-gnu.zip":
        fail("Deno archive filename does not match the managed architecture")
    validate_https_url(
        deno.url,
        "Deno URL",
        hostname="github.com",
        expected_path=(
            f"/denoland/deno/releases/download/v{deno.version}/{deno.filename}"
        ),
    )
    deno_archive_files = archive_tokens(values, "DEVOPS_DENO_ARCHIVE_FILES")
    if set(deno_archive_files) != {"deno"}:
        fail("Deno archive file policy must contain only the deno executable")

    if values["DEVOPS_YT_DLP_ARCHITECTURE"] != "linux-x86_64":
        fail("yt-dlp architecture policy is unsupported")
    if yt_dlp.filename != "yt-dlp_linux":
        fail("yt-dlp artifact filename does not match the managed architecture")
    validate_https_url(
        yt_dlp.url,
        "yt-dlp URL",
        hostname="github.com",
        expected_path=(
            f"/yt-dlp/yt-dlp/releases/download/{yt_dlp.version}/{yt_dlp.filename}"
        ),
    )
    yt_dlp_payload_path = managed_path(values, "DEVOPS_YT_DLP_PAYLOAD_PATH")
    try:
        yt_dlp_payload_path.relative_to(yt_dlp.install_root)
    except ValueError:
        fail("DEVOPS_YT_DLP_PAYLOAD_PATH must remain below DEVOPS_YT_DLP_INSTALL_ROOT")
    if yt_dlp_payload_path != pathlib.Path("/usr/local/lib/yt-dlp/libexec/yt-dlp"):
        fail("yt-dlp payload path does not match the managed root")

    if ansible_core.architecture != "python3-any":
        fail("Ansible Core architecture policy is unsupported")
    if ansible_core.filename != f"ansible_core-{ansible_core.version}-py3-none-any.whl":
        fail("Ansible Core wheel filename does not match its version")
    validate_https_url(
        ansible_core.url,
        "Ansible Core URL",
        hostname="files.pythonhosted.org",
        required_prefix="/packages/",
        required_suffix=f"/{ansible_core.filename}",
    )
    ansible_core_package_roots = archive_tokens(
        values,
        "DEVOPS_ANSIBLE_CORE_PACKAGE_ROOTS",
    )
    if set(ansible_core_package_roots) != {"ansible", "ansible_test"}:
        fail("Ansible Core package roots do not match the managed wheel")
    ansible_core_dist_info_root = archive_token(
        values["DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT"],
        "DEVOPS_ANSIBLE_CORE_DIST_INFO_ROOT",
    )
    if ansible_core_dist_info_root != f"ansible_core-{ansible_core.version}.dist-info":
        fail("Ansible Core dist-info root does not match its version")
    ansible_core_max_archive_members = positive_integer(
        values,
        "DEVOPS_ANSIBLE_CORE_MAX_ARCHIVE_MEMBERS",
        100_000,
    )
    ansible_core_max_extracted_bytes = positive_integer(
        values,
        "DEVOPS_ANSIBLE_CORE_MAX_EXTRACTED_BYTES",
        8 * 1024**3,
    )

    if values["DEVOPS_OPENTOFU_ARCHITECTURE"] != "linux-amd64":
        fail("OpenTofu architecture policy is unsupported")
    if opentofu.filename != f"tofu_{opentofu.version}_linux_amd64.zip":
        fail("OpenTofu archive filename does not match its version")
    validate_https_url(
        opentofu.url,
        "OpenTofu URL",
        hostname="github.com",
        expected_path=(
            f"/opentofu/opentofu/releases/download/v{opentofu.version}/"
            f"{opentofu.filename}"
        ),
    )

    if values["DEVOPS_TERRAFORM_ARCHITECTURE"] != "linux-amd64":
        fail("Terraform architecture policy is unsupported")
    if terraform.filename != f"terraform_{terraform.version}_linux_amd64.zip":
        fail("Terraform archive filename does not match its version")
    validate_https_url(
        terraform.url,
        "Terraform URL",
        hostname="releases.hashicorp.com",
        expected_path=f"/terraform/{terraform.version}/{terraform.filename}",
    )
    terraform_archive_files = archive_tokens(
        values,
        "DEVOPS_TERRAFORM_ARCHIVE_FILES",
    )
    if set(terraform_archive_files) != {"LICENSE.txt", "terraform"}:
        fail("Terraform archive file policy does not match the managed release")

    if values["DEVOPS_PACKER_ARCHITECTURE"] != "linux-amd64":
        fail("Packer architecture policy is unsupported")
    if packer.filename != f"packer_{packer.version}_linux_amd64.zip":
        fail("Packer archive filename does not match its version")
    validate_https_url(
        packer.url,
        "Packer URL",
        hostname="releases.hashicorp.com",
        expected_path=f"/packer/{packer.version}/{packer.filename}",
    )
    packer_archive_files = archive_tokens(
        values,
        "DEVOPS_PACKER_ARCHIVE_FILES",
    )
    if set(packer_archive_files) != {"LICENSE.txt", "packer"}:
        fail("Packer archive file policy does not match the managed release")

    if values["DEVOPS_WRANGLER_ARCHITECTURE"] != "node-any":
        fail("Wrangler architecture policy is unsupported")
    if wrangler.filename != f"wrangler-{wrangler.version}.tgz":
        fail("Wrangler archive filename does not match its version")
    validate_https_url(
        wrangler.url,
        "Wrangler URL",
        hostname="registry.npmjs.org",
        expected_path=f"/wrangler/-/{wrangler.filename}",
    )
    npm_integrity = values["DEVOPS_WRANGLER_NPM_INTEGRITY"]
    expected_integrity = "sha512-" + base64.b64encode(
        bytes.fromhex(wrangler.expected_digest)
    ).decode("ascii")
    if npm_integrity != expected_integrity:
        fail("Wrangler npm integrity does not match its SHA-512 digest")
    wrangler_archive_root = archive_token(
        values["DEVOPS_WRANGLER_ARCHIVE_ROOT"],
        "DEVOPS_WRANGLER_ARCHIVE_ROOT",
    )
    if wrangler_archive_root != "package":
        fail("Wrangler archive root must remain package")
    if values["DEVOPS_WRANGLER_PACKAGE_NAME"] != "wrangler":
        fail("Wrangler package name must remain wrangler")
    wrangler_node_requirement = values["DEVOPS_WRANGLER_NODE_REQUIREMENT"]
    requirement_match = re.fullmatch(
        r">=([0-9]+)\.([0-9]+)\.([0-9]+)",
        wrangler_node_requirement,
    )
    if requirement_match is None or int(requirement_match.group(1)) < 22:
        fail("Wrangler Node requirement must require Node 22 or newer")
    wrangler_node_root = managed_path(values, "DEVOPS_WRANGLER_NODE_ROOT")
    if wrangler_node_root != pathlib.Path("/usr/local/lib/node-26"):
        fail("Wrangler must use the managed Node 26 runtime")
    npm_registry_url = values["DEVOPS_WRANGLER_NPM_REGISTRY_URL"]
    validate_https_url(
        npm_registry_url,
        "Wrangler npm registry URL",
        hostname="registry.npmjs.org",
        expected_path="/",
    )

    if values["DEVOPS_APTLY_RELEASE_ARCHITECTURE"] != "linux-amd64":
        fail("Aptly architecture policy is unsupported")
    aptly_archive_root = archive_token(
        values["DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT"],
        "DEVOPS_APTLY_RELEASE_ARCHIVE_ROOT",
    )
    if aptly.filename != f"aptly_{aptly.version}_linux_amd64.zip":
        fail("Aptly archive filename does not match its version")
    if aptly_archive_root != f"aptly_{aptly.version}_linux_amd64":
        fail("Aptly archive root does not match its version")
    validate_https_url(
        aptly.url,
        "Aptly URL",
        hostname="github.com",
        expected_path=(
            f"/aptly-dev/aptly/releases/download/v{aptly.version}/{aptly.filename}"
        ),
    )

    if values["DEVOPS_OSC_RELEASE_ARCHITECTURE"] != "python3-any":
        fail("osc architecture policy is unsupported")
    if osc.filename != f"osc-{osc.version}-py3-none-any.whl":
        fail("osc wheel filename does not match its version")
    validate_https_url(
        osc.url,
        "osc URL",
        hostname="files.pythonhosted.org",
        required_prefix="/packages/",
        required_suffix=f"/{osc.filename}",
    )
    osc_package_root = archive_token(
        values["DEVOPS_OSC_RELEASE_PACKAGE_ROOT"],
        "DEVOPS_OSC_RELEASE_PACKAGE_ROOT",
    )
    osc_dist_info_root = archive_token(
        values["DEVOPS_OSC_RELEASE_DIST_INFO_ROOT"],
        "DEVOPS_OSC_RELEASE_DIST_INFO_ROOT",
    )
    if osc_package_root != "osc" or osc_dist_info_root != f"osc-{osc.version}.dist-info":
        fail("osc wheel roots do not match its version")

    obs_tag = values["DEVOPS_OBS_BUILD_TAG"]
    if re.fullmatch(r"[0-9]{8}", obs_tag) is None:
        fail("obs-build tag must contain eight digits")
    obs_commit = lower_hex(values, "DEVOPS_OBS_BUILD_COMMIT", 40)
    obs_archive_root = archive_token(
        values["DEVOPS_OBS_BUILD_ARCHIVE_ROOT"],
        "DEVOPS_OBS_BUILD_ARCHIVE_ROOT",
    )
    if values["DEVOPS_OBS_BUILD_ARCHITECTURE"] != "source-any":
        fail("obs-build architecture policy is unsupported")
    if obs_build.filename != f"obs-build-{obs_commit}.tar.gz":
        fail("obs-build archive filename does not match its commit")
    if obs_archive_root != f"obs-build-{obs_commit}":
        fail("obs-build archive root does not match its commit")
    validate_https_url(
        obs_build.url,
        "obs-build URL",
        hostname="codeload.github.com",
        expected_path=f"/openSUSE/obs-build/tar.gz/{obs_commit}",
    )

    return InstallPolicy(
        architecture=architecture,
        download_timeout_seconds=positive_integer(
            values, "DEVOPS_UPSTREAM_DOWNLOAD_TIMEOUT_SECONDS", 86_400
        ),
        npm_timeout_seconds=positive_integer(
            values, "DEVOPS_UPSTREAM_NPM_TIMEOUT_SECONDS", 86_400
        ),
        make_timeout_seconds=positive_integer(
            values, "DEVOPS_UPSTREAM_MAKE_TIMEOUT_SECONDS", 86_400
        ),
        verify_timeout_seconds=positive_integer(
            values, "DEVOPS_UPSTREAM_VERIFY_TIMEOUT_SECONDS", 3_600
        ),
        max_archive_members=positive_integer(
            values, "DEVOPS_UPSTREAM_MAX_ARCHIVE_MEMBERS", 100_000
        ),
        max_extracted_bytes=positive_integer(
            values, "DEVOPS_UPSTREAM_MAX_EXTRACTED_BYTES", 8 * 1024**3
        ),
        install_parent=pathlib.Path("/usr/local/lib"),
        deno=deno,
        deno_archive_files=deno_archive_files,
        yt_dlp=yt_dlp,
        yt_dlp_payload_path=yt_dlp_payload_path,
        ansible_core=ansible_core,
        ansible_core_package_roots=ansible_core_package_roots,
        ansible_core_dist_info_root=ansible_core_dist_info_root,
        ansible_core_max_archive_members=ansible_core_max_archive_members,
        ansible_core_max_extracted_bytes=ansible_core_max_extracted_bytes,
        opentofu=opentofu,
        opentofu_archive_files=archive_tokens(
            values, "DEVOPS_OPENTOFU_ARCHIVE_FILES"
        ),
        terraform=terraform,
        terraform_archive_files=terraform_archive_files,
        packer=packer,
        packer_archive_files=packer_archive_files,
        wrangler=wrangler,
        wrangler_npm_integrity=npm_integrity,
        wrangler_archive_root=wrangler_archive_root,
        wrangler_package_name=values["DEVOPS_WRANGLER_PACKAGE_NAME"],
        wrangler_node_requirement=wrangler_node_requirement,
        wrangler_node_root=wrangler_node_root,
        wrangler_npm_registry_url=npm_registry_url,
        aptly=aptly,
        aptly_archive_root=aptly_archive_root,
        aptly_archive_files=archive_tokens(
            values, "DEVOPS_APTLY_RELEASE_ARCHIVE_FILES"
        ),
        osc=osc,
        osc_package_root=osc_package_root,
        osc_dist_info_root=osc_dist_info_root,
        obs_build=obs_build,
        obs_build_tag=obs_tag,
        obs_build_commit=obs_commit,
        obs_build_archive_root=obs_archive_root,
        obs_build_entrypoints=archive_tokens(
            values, "DEVOPS_OBS_BUILD_ENTRYPOINTS"
        ),
    )


def require_root(policy: InstallPolicy) -> None:
    if os.geteuid() != 0:
        fail("the upstream DevOps tool installer must run as root")
    if platform.machine() != policy.architecture:
        fail(f"unsupported DevOps tool architecture: {platform.machine()}")


def require_program(path: pathlib.Path, label: str) -> None:
    try:
        resolved = path.resolve(strict=True)
        path_stat = resolved.stat()
    except OSError:
        fail(f"required {label} is unavailable: {path}")
    if not stat.S_ISREG(path_stat.st_mode) or not os.access(resolved, os.X_OK):
        fail(f"required {label} is not executable: {path}")


def require_install_parent(policy: InstallPolicy) -> None:
    install_parent = policy.install_parent
    if not os.path.lexists(install_parent):
        try:
            install_parent.mkdir(mode=0o755, parents=True)
            # pathlib.mkdir() applies the inherited process umask.  The
            # managed tools are account-facing, so publish their parent with
            # an explicit deterministic mode rather than accepting 0700/0750.
            install_parent.chmod(0o755)
        except OSError:
            fail(f"unable to create the install parent: {install_parent}")
    try:
        parent_stat = install_parent.lstat()
    except OSError:
        fail(f"unable to inspect the install parent: {install_parent}")
    if not stat.S_ISDIR(parent_stat.st_mode):
        fail(f"the install parent must be a real directory: {install_parent}")
    if parent_stat.st_uid != 0 or parent_stat.st_gid != 0:
        fail(f"the install parent must be owned by root: {install_parent}")
    if stat.S_IMODE(parent_stat.st_mode) != 0o755:
        fail(f"the install parent must have mode 0755: {install_parent}")
    managed_parents = {
        artifact_item.install_root.parent for artifact_item in policy.artifacts
    } - {install_parent}
    for managed_parent in sorted(managed_parents):
        if managed_parent.parent != install_parent:
            fail(f"unsupported nested tool parent: {managed_parent}")
        if not os.path.lexists(managed_parent):
            try:
                managed_parent.mkdir(mode=0o755)
                managed_parent.chmod(0o755)
            except OSError:
                fail(f"unable to create the nested install parent: {managed_parent}")
        try:
            managed_parent_stat = managed_parent.lstat()
        except OSError:
            fail(f"unable to inspect the nested install parent: {managed_parent}")
        if not stat.S_ISDIR(managed_parent_stat.st_mode):
            fail(f"nested install parent must be a real directory: {managed_parent}")
        if managed_parent_stat.st_uid != 0 or managed_parent_stat.st_gid != 0:
            fail(f"nested install parent must be owned by root: {managed_parent}")
        if stat.S_IMODE(managed_parent_stat.st_mode) != 0o755:
            fail(f"nested install parent must have mode 0755: {managed_parent}")
    for artifact_item in policy.artifacts:
        final_root = artifact_item.install_root
        if os.path.lexists(final_root):
            fail(
                "fresh-install DevOps tool root already exists; refusing replacement: "
                f"{final_root}"
            )


def run_checked(
    arguments: Sequence[str],
    label: str,
    *,
    timeout: int,
    cwd: pathlib.Path | None = None,
    environment: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(arguments),
            check=False,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        fail(f"{label} exceeded its {timeout}-second timeout")
    except OSError:
        fail(f"{label} could not start")
    if result.returncode != 0:
        detail = ""
        if capture_output and result.stderr:
            detail = f": {result.stderr.strip()[:400]}"
        fail(f"{label} failed with status {result.returncode}{detail}")
    return result


def file_digest(path: pathlib.Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        fail(f"unable to hash downloaded artifact: {path.name}")
    return digest.hexdigest()


def download_artifact(
    policy: InstallPolicy,
    artifact: DownloadArtifact,
    download_dir: pathlib.Path,
) -> pathlib.Path:
    destination = download_dir / artifact.filename
    run_checked(
        [
            str(CURL),
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
    )
    try:
        observed_bytes = destination.stat().st_size
    except OSError:
        fail(f"downloaded {artifact.name} artifact is unavailable")
    if observed_bytes != artifact.expected_bytes:
        fail(
            f"{artifact.name} artifact size mismatch: expected "
            f"{artifact.expected_bytes}, got {observed_bytes}"
        )
    observed_digest = file_digest(destination, artifact.digest_algorithm)
    if observed_digest != artifact.expected_digest:
        fail(f"{artifact.name} {artifact.digest_algorithm.upper()} mismatch")
    return destination


def archive_member_parts(name: str, label: str) -> tuple[str, ...]:
    if not name or "\\" in name or name.startswith("/"):
        fail(f"{label} contains an unsafe archive path: {name!r}")
    trimmed = name[:-1] if name.endswith("/") else name
    parts = tuple(trimmed.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        fail(f"{label} contains a non-normalized archive path: {name!r}")
    return parts


def validated_zip_infos(
    archive_path: pathlib.Path,
    label: str,
    max_archive_members: int,
    max_extracted_bytes: int,
) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    try:
        archive = zipfile.ZipFile(archive_path)
        infos = archive.infolist()
    except (OSError, zipfile.BadZipFile):
        fail(f"{label} is not a valid ZIP archive")
    if not infos or len(infos) > max_archive_members:
        archive.close()
        fail(f"{label} has an invalid member count")
    members: dict[str, zipfile.ZipInfo] = {}
    expanded_bytes = 0
    for info in infos:
        archive_member_parts(info.filename, label)
        if info.filename in members:
            archive.close()
            fail(f"{label} contains a duplicate member: {info.filename}")
        if info.flag_bits & 0x1:
            archive.close()
            fail(f"{label} contains an encrypted member: {info.filename}")
        member_mode = info.external_attr >> 16
        member_type = stat.S_IFMT(member_mode)
        if member_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            archive.close()
            fail(f"{label} contains a non-regular member: {info.filename}")
        if info.file_size < 0:
            archive.close()
            fail(f"{label} contains a member with an invalid size")
        expanded_bytes += info.file_size
        if expanded_bytes > max_extracted_bytes:
            archive.close()
            fail(f"{label} exceeds the expanded-byte ceiling")
        members[info.filename] = info
    return archive, members


def copy_zip_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: pathlib.Path,
    mode: int,
) -> None:
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    try:
        with archive.open(info, "r") as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        if destination.stat().st_size != info.file_size:
            fail(f"extracted member size changed: {info.filename}")
        destination.chmod(mode)
    except OSError:
        fail(f"failed to extract archive member: {info.filename}")


def write_release_record(
    root: pathlib.Path,
    artifact: DownloadArtifact,
    *extra_lines: str,
) -> None:
    record = root / ".managed-upstream-release"
    lines = [
        "schema=1",
        f"name={artifact.name}",
        f"version={artifact.version}",
        f"url={artifact.url}",
        f"bytes={artifact.expected_bytes}",
        f"{artifact.digest_algorithm}={artifact.expected_digest}",
        f"architecture={artifact.architecture}",
        *extra_lines,
    ]
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")
    record.chmod(0o644)


def rooted_zip_members(root: str, files: Sequence[str]) -> set[str]:
    members = {f"{root}/"}
    for filename in files:
        parts = filename.split("/")
        for index in range(1, len(parts)):
            members.add(f"{root}/{'/'.join(parts[:index])}/")
        members.add(f"{root}/{filename}")
    return members


def extract_ansible_wheel(
    policy: InstallPolicy,
    artifact_item: DownloadArtifact,
    wheel_path: pathlib.Path,
    library_root: pathlib.Path,
    *,
    label: str,
    distribution_name: str,
    package_roots: Sequence[str],
    dist_info_root: str,
    expected_requirements: set[str] | frozenset[str],
    expected_entrypoints: dict[str, str],
) -> None:
    archive, members = validated_zip_infos(
        wheel_path,
        label,
        policy.ansible_core_max_archive_members,
        policy.ansible_core_max_extracted_bytes,
    )
    metadata_name = f"{dist_info_root}/METADATA"
    entrypoints_name = f"{dist_info_root}/entry_points.txt"
    allowed_roots = {*package_roots, dist_info_root}
    try:
        if metadata_name not in members or entrypoints_name not in members:
            fail(f"{label} metadata or entry points are missing")
        metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_name))
        if (
            metadata.get("Name") != distribution_name
            or metadata.get("Version") != artifact_item.version
            or metadata.get("Requires-Python") != ">=3.12"
            or set(metadata.get_all("Requires-Dist") or []) != set(expected_requirements)
        ):
            fail(f"{label} identity or dependency metadata is unexpected")
        entrypoints = configparser.ConfigParser(interpolation=None)
        entrypoints.optionxform = str
        entrypoints.read_string(archive.read(entrypoints_name).decode("utf-8"))
        if entrypoints.sections() != ["console_scripts"] or dict(
            entrypoints.items("console_scripts", raw=True)
        ) != expected_entrypoints:
            fail(f"{label} console entry points are unexpected")
        for name, info in members.items():
            parts = archive_member_parts(name, label)
            if parts[0] not in allowed_roots:
                fail(f"{label} contains an unexpected root: {parts[0]}")
            destination = library_root / pathlib.Path(*parts)
            if info.is_dir():
                destination.mkdir(mode=0o755, parents=True, exist_ok=True)
                continue
            member_mode = info.external_attr >> 16
            copy_zip_member(
                archive,
                info,
                destination,
                0o644 | (member_mode & 0o111),
            )
    except (UnicodeDecodeError, configparser.Error):
        fail(f"{label} metadata is not valid UTF-8 configuration data")
    finally:
        archive.close()


def prepare_ansible_core(
    policy: InstallPolicy,
    ansible_core_wheel: pathlib.Path,
    root: pathlib.Path,
) -> None:
    root.mkdir(mode=0o755, parents=True)
    library_root = root / "lib/python3/dist-packages"
    library_root.mkdir(mode=0o755, parents=True)
    extract_ansible_wheel(
        policy,
        policy.ansible_core,
        ansible_core_wheel,
        library_root,
        label="Ansible Core wheel",
        distribution_name="ansible-core",
        package_roots=policy.ansible_core_package_roots,
        dist_info_root=policy.ansible_core_dist_info_root,
        expected_requirements=ANSIBLE_CORE_REQUIREMENTS,
        expected_entrypoints=ANSIBLE_CONSOLE_SCRIPTS,
    )

    final_library = policy.ansible_core.install_root / "lib/python3/dist-packages"
    bin_root = root / "bin"
    bin_root.mkdir(mode=0o755)
    for command, target in sorted(ANSIBLE_CONSOLE_SCRIPTS.items()):
        module_name, function_name = target.split(":", 1)
        wrapper = bin_root / command
        wrapper.write_text(
            "#!/usr/bin/python3\n"
            "# PYTHON_ARGCOMPLETE_OK\n"
            "import sys\n"
            f"sys.path.insert(0, {str(final_library)!r})\n"
            f"from {module_name} import {function_name}\n"
            f"raise SystemExit({function_name}())\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

    completion_paths = {
        "bash": root / "share/bash-completion/completions/ansible",
        "zsh": root / "share/zsh/site-functions/_ansible-managed",
    }
    for shell_name, completion_path in completion_paths.items():
        completion_fragments: list[str] = []
        for command in sorted(ANSIBLE_CONSOLE_SCRIPTS):
            result = run_checked(
                [str(ARGCOMPLETE), "--shell", shell_name, command],
                f"generating {command} {shell_name} completion",
                timeout=policy.verify_timeout_seconds,
                capture_output=True,
            )
            if not result.stdout.strip() or "\x00" in result.stdout:
                fail(
                    f"generated {command} {shell_name} completion is empty or invalid"
                )
            completion_fragments.append(result.stdout.rstrip() + "\n")
        completion_path.parent.mkdir(mode=0o755, parents=True)
        completion_path.write_text(
            "\n".join(completion_fragments),
            encoding="utf-8",
        )
        completion_path.chmod(0o644)

    write_release_record(
        root,
        policy.ansible_core,
        "distribution=pypi-wheel",
    )


def prepare_hashicorp_release(
    policy: InstallPolicy,
    archive_path: pathlib.Path,
    root: pathlib.Path,
    artifact_item: Artifact,
    archive_files: Sequence[str],
    executable_name: str,
) -> None:
    archive, members = validated_zip_infos(
        archive_path,
        f"{artifact_item.name} archive",
        policy.max_archive_members,
        policy.max_extracted_bytes,
    )
    expected_members = set(archive_files)
    if expected_members != {"LICENSE.txt", executable_name}:
        archive.close()
        fail(f"{artifact_item.name} archive policy is unexpected")
    try:
        if set(members) != expected_members:
            fail(f"{artifact_item.name} archive layout does not match its release")
        binary_relative = artifact_item.binary_path.relative_to(
            artifact_item.install_root
        )
        copy_zip_member(
            archive,
            members[executable_name],
            root / binary_relative,
            0o755,
        )
        copy_zip_member(
            archive,
            members["LICENSE.txt"],
            root / "share/doc" / artifact_item.key / "LICENSE.txt",
            0o644,
        )
    finally:
        archive.close()
    write_release_record(root, artifact_item, "distribution=hashicorp-release-zip")


def prepare_opentofu(
    policy: InstallPolicy,
    archive_path: pathlib.Path,
    root: pathlib.Path,
) -> None:
    artifact_item = policy.opentofu
    archive, members = validated_zip_infos(
        archive_path,
        "OpenTofu archive",
        policy.max_archive_members,
        policy.max_extracted_bytes,
    )
    expected_members = set(policy.opentofu_archive_files)
    if "tofu" not in expected_members:
        archive.close()
        fail("OpenTofu archive policy must include the tofu executable")
    try:
        if set(members) != expected_members:
            fail("OpenTofu archive layout does not match the managed release")
        binary_relative = artifact_item.binary_path.relative_to(
            artifact_item.install_root
        )
        copy_zip_member(archive, members["tofu"], root / binary_relative, 0o755)
        for name in sorted(expected_members - {"tofu"}):
            copy_zip_member(
                archive,
                members[name],
                root / "share/doc/opentofu" / name,
                0o644,
            )
    finally:
        archive.close()
    write_release_record(root, artifact_item)


def prepare_deno(
    policy: InstallPolicy,
    archive_path: pathlib.Path,
    root: pathlib.Path,
) -> None:
    artifact_item = policy.deno
    archive, members = validated_zip_infos(
        archive_path,
        "Deno archive",
        policy.max_archive_members,
        policy.max_extracted_bytes,
    )
    expected_members = set(policy.deno_archive_files)
    try:
        if set(members) != expected_members:
            fail("Deno archive layout does not match the managed release")
        binary_relative = artifact_item.binary_path.relative_to(
            artifact_item.install_root
        )
        copy_zip_member(
            archive,
            members["deno"],
            root / binary_relative,
            0o755,
        )
    finally:
        archive.close()
    write_release_record(root, artifact_item, "distribution=github-release-zip")


def prepare_yt_dlp(
    policy: InstallPolicy,
    payload_source: pathlib.Path,
    root: pathlib.Path,
) -> None:
    artifact_item = policy.yt_dlp
    payload_relative = policy.yt_dlp_payload_path.relative_to(
        artifact_item.install_root
    )
    wrapper_relative = artifact_item.binary_path.relative_to(
        artifact_item.install_root
    )
    payload = root / payload_relative
    wrapper = root / wrapper_relative
    payload.parent.mkdir(mode=0o755, parents=True)
    wrapper.parent.mkdir(mode=0o755, parents=True)
    try:
        with payload_source.open("rb") as source, payload.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        if payload.stat().st_size != artifact_item.expected_bytes:
            fail("yt-dlp payload size changed while preparing the managed root")
        payload.chmod(0o755)
        wrapper.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            "\n"
            f"yt_dlp_payload={policy.yt_dlp_payload_path}\n"
            f"deno_binary={policy.deno.binary_path}\n"
            "\n"
            "[ -x \"$yt_dlp_payload\" ] || {\n"
            "  printf 'fatal: managed yt-dlp payload is unavailable: %s\\n' \"$yt_dlp_payload\" >&2\n"
            "  exit 1\n"
            "}\n"
            "[ -x \"$deno_binary\" ] || {\n"
            "  printf 'fatal: managed Deno runtime is unavailable: %s\\n' \"$deno_binary\" >&2\n"
            "  exit 1\n"
            "}\n"
            "\n"
            "# Official standalone releases bundle yt-dlp-ejs. Keep remote\n"
            "# components disabled, bind the supported JS engine explicitly, and\n"
            "# preserve yt-dlp's upstream high-quality format selection defaults.\n"
            "exec \"$yt_dlp_payload\" \\\n"
            "  --no-remote-components \\\n"
            "  --no-js-runtimes \\\n"
            "  --js-runtimes \"deno:${deno_binary}\" \\\n"
            "  --ffmpeg-location /usr/bin \\\n"
            "  \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    except OSError:
        fail("failed to prepare the managed yt-dlp runtime")
    write_release_record(
        root,
        artifact_item,
        "distribution=github-standalone-executable",
        f"payload_path={policy.yt_dlp_payload_path}",
        "javascript_component=yt-dlp-ejs-bundled",
        f"javascript_runtime={policy.deno.binary_path}",
        "remote_components=disabled",
    )


def prepare_aptly(
    policy: InstallPolicy,
    archive_path: pathlib.Path,
    root: pathlib.Path,
) -> None:
    artifact_item = policy.aptly
    archive_root = policy.aptly_archive_root
    archive, members = validated_zip_infos(
        archive_path,
        "Aptly archive",
        policy.max_archive_members,
        policy.max_extracted_bytes,
    )
    expected_members = rooted_zip_members(
        archive_root,
        policy.aptly_archive_files,
    )
    destinations = {
        "aptly": (artifact_item.binary_path.relative_to(artifact_item.install_root), 0o755),
        "AUTHORS": (pathlib.Path("share/doc/aptly/AUTHORS"), 0o644),
        "LICENSE": (pathlib.Path("share/doc/aptly/LICENSE"), 0o644),
        "README.rst": (pathlib.Path("share/doc/aptly/README.rst"), 0o644),
        "man/aptly.1.gz": (pathlib.Path("share/man/man1/aptly.1.gz"), 0o644),
        "completion/bash_completion.d/aptly": (
            pathlib.Path("share/bash-completion/completions/aptly"),
            0o644,
        ),
        "completion/zsh/vendor-completions/_aptly": (
            pathlib.Path("share/zsh/site-functions/_aptly"),
            0o644,
        ),
    }
    if set(policy.aptly_archive_files) != set(destinations):
        archive.close()
        fail("Aptly archive file policy does not match the managed installation layout")
    try:
        if set(members) != expected_members:
            fail("Aptly archive layout does not match the managed release")
        for name, (destination, mode) in destinations.items():
            copy_zip_member(
                archive,
                members[f"{archive_root}/{name}"],
                root / destination,
                mode,
            )
    finally:
        archive.close()
    write_release_record(root, artifact_item)


def prepare_osc(
    policy: InstallPolicy,
    wheel_path: pathlib.Path,
    root: pathlib.Path,
) -> None:
    artifact_item = policy.osc
    archive, members = validated_zip_infos(
        wheel_path,
        "osc wheel",
        policy.max_archive_members,
        policy.max_extracted_bytes,
    )
    metadata_name = f"{policy.osc_dist_info_root}/METADATA"
    try:
        if metadata_name not in members:
            fail("osc wheel metadata is missing")
        metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_name))
        if (
            metadata.get("Name") != policy.osc_package_root
            or metadata.get("Version") != artifact_item.version
        ):
            fail("osc wheel identity does not match the managed release")
        for name, info in members.items():
            parts = archive_member_parts(name, "osc wheel")
            if parts[0] not in {
                policy.osc_package_root,
                policy.osc_dist_info_root,
            }:
                fail(f"osc wheel contains an unexpected root: {parts[0]}")
            if info.is_dir():
                (root / "lib" / pathlib.Path(*parts)).mkdir(
                    mode=0o755,
                    parents=True,
                    exist_ok=True,
                )
                continue
            copy_zip_member(
                archive,
                info,
                root / "lib" / pathlib.Path(*parts),
                0o644,
            )
    finally:
        archive.close()
    wrapper = root / artifact_item.binary_path.relative_to(
        artifact_item.install_root
    )
    wrapper.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    final_library = artifact_item.install_root / "lib"
    wrapper.write_text(
        "#!/usr/bin/python3\n"
        "import sys\n"
        f"sys.path.insert(0, {str(final_library)!r})\n"
        "from osc.babysitter import main\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    write_release_record(root, artifact_item, "distribution=pypi-wheel")


def validated_tar_members(
    archive_path: pathlib.Path,
    label: str,
    expected_root: str,
    max_archive_members: int,
    max_extracted_bytes: int,
) -> tuple[tarfile.TarFile, list[tarfile.TarInfo]]:
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
        members = archive.getmembers()
    except (OSError, tarfile.TarError):
        fail(f"{label} is not a valid gzip-compressed tar archive")
    if not members or len(members) > max_archive_members:
        archive.close()
        fail(f"{label} has an invalid member count")
    seen: set[str] = set()
    expanded_bytes = 0
    for member in members:
        parts = archive_member_parts(member.name, label)
        if parts[0] != expected_root:
            archive.close()
            fail(f"{label} contains an unexpected archive root")
        if member.name in seen:
            archive.close()
            fail(f"{label} contains a duplicate member: {member.name}")
        seen.add(member.name)
        if member.isreg():
            expanded_bytes += member.size
        elif member.isdir():
            pass
        elif member.issym():
            link_target = posixpath.normpath(
                posixpath.join(posixpath.dirname(member.name), member.linkname)
            )
            target_parts = archive_member_parts(link_target, label)
            if target_parts[0] != expected_root:
                archive.close()
                fail(f"{label} contains an escaping symbolic link: {member.name}")
            if member.linkname.startswith("/") or "\\" in member.linkname:
                archive.close()
                fail(f"{label} contains an unsafe symbolic link: {member.name}")
        else:
            archive.close()
            fail(f"{label} contains an unsupported member: {member.name}")
        if expanded_bytes > max_extracted_bytes:
            archive.close()
            fail(f"{label} exceeds the expanded-byte ceiling")
    return archive, members


def extract_validated_tar(
    archive_path: pathlib.Path,
    label: str,
    expected_root: str,
    destination: pathlib.Path,
    max_archive_members: int,
    max_extracted_bytes: int,
) -> pathlib.Path:
    archive, members = validated_tar_members(
        archive_path,
        label,
        expected_root,
        max_archive_members,
        max_extracted_bytes,
    )
    source_root = destination / expected_root
    try:
        for member in members:
            parts = archive_member_parts(member.name, label)
            target = destination / pathlib.Path(*parts)
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
        for member in members:
            if not member.isreg():
                continue
            parts = archive_member_parts(member.name, label)
            target = destination / pathlib.Path(*parts)
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                fail(f"{label} member could not be read: {member.name}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if target.stat().st_size != member.size:
                fail(f"{label} member size changed: {member.name}")
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
        for member in members:
            if not member.issym():
                continue
            parts = archive_member_parts(member.name, label)
            target = destination / pathlib.Path(*parts)
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            target.symlink_to(member.linkname)
    except OSError:
        fail(f"failed to extract {label}")
    finally:
        archive.close()
    if not source_root.is_dir() or source_root.is_symlink():
        fail(f"{label} root is missing after extraction")
    return source_root


def npm_environment(
    policy: InstallPolicy,
    workspace: pathlib.Path,
) -> dict[str, str]:
    node_bin = policy.wrangler_node_root / "bin"
    environment = {
        "HOME": str(workspace / "npm-home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
        "NODE_ENV": "production",
        "PATH": f"{node_bin}:/usr/bin:/bin",
        "TZ": "UTC",
        "NPM_CONFIG_AUDIT": "false",
        "NPM_CONFIG_CACHE": str(workspace / "npm-cache"),
        "NPM_CONFIG_FETCH_RETRIES": "3",
        "NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT": "10000",
        "NPM_CONFIG_FETCH_RETRY_MINTIMEOUT": "1000",
        "NPM_CONFIG_FETCH_TIMEOUT": "300000",
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_REGISTRY": policy.wrangler_npm_registry_url,
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    }
    for variable in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    ):
        if variable in os.environ:
            environment[variable] = os.environ[variable]
    return environment


def ensure_wrangler_command_executable(
    policy: InstallPolicy,
    root: pathlib.Path,
) -> None:
    binary_relative = policy.wrangler.binary_path.relative_to(
        policy.wrangler.install_root
    )
    staged_binary = root / binary_relative
    if not staged_binary.exists():
        fail("npm did not create the Wrangler command entrypoint")
    try:
        resolved_binary = staged_binary.resolve(strict=True)
        resolved_binary.relative_to(
            root / "node_modules" / policy.wrangler_package_name
        )
    except (OSError, ValueError):
        fail("Wrangler command entrypoint escapes the installed package")
    if not resolved_binary.is_file():
        fail("Wrangler command entrypoint does not resolve to a regular file")
    try:
        resolved_binary.chmod(0o755)
    except OSError:
        fail("failed to make the Wrangler command entrypoint executable")


def prepare_wrangler(
    policy: InstallPolicy,
    archive_path: pathlib.Path,
    root: pathlib.Path,
    workspace: pathlib.Path,
) -> None:
    artifact_item = policy.wrangler
    expected_root = policy.wrangler_archive_root
    archive, members = validated_tar_members(
        archive_path,
        "Wrangler package",
        expected_root,
        policy.max_archive_members,
        policy.max_extracted_bytes,
    )
    try:
        package_member = next(
            (
                member
                for member in members
                if member.name == f"{expected_root}/package.json"
            ),
            None,
        )
        if package_member is None or not package_member.isreg():
            fail("Wrangler package metadata is missing")
        package_stream = archive.extractfile(package_member)
        if package_stream is None:
            fail("Wrangler package metadata is unreadable")
        with package_stream:
            package_data = json.load(package_stream)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("Wrangler package metadata is invalid JSON")
    finally:
        archive.close()
    if (
        package_data.get("name") != policy.wrangler_package_name
        or package_data.get("version") != artifact_item.version
        or package_data.get("engines", {}).get("node")
        != policy.wrangler_node_requirement
    ):
        fail("Wrangler package identity or Node requirement is unexpected")

    root.mkdir(mode=0o755, parents=True)
    (workspace / "npm-home").mkdir(mode=0o700)
    run_checked(
        [
            str(policy.wrangler_node_root / "bin/npm"),
            "install",
            "--prefix",
            str(root),
            "--omit=dev",
            "--no-audit",
            "--no-fund",
            "--no-save",
            "--package-lock=false",
            "--registry",
            policy.wrangler_npm_registry_url,
            str(archive_path),
        ],
        f"installing Wrangler {artifact_item.version} with npm",
        timeout=policy.npm_timeout_seconds,
        environment=npm_environment(policy, workspace),
    )
    package_json = (
        root / "node_modules" / policy.wrangler_package_name / "package.json"
    )
    try:
        installed_package = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        fail("installed Wrangler package metadata is invalid")
    if installed_package.get("version") != artifact_item.version:
        fail("npm installed an unexpected Wrangler version")
    ensure_wrangler_command_executable(policy, root)
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "managed-wrangler-runtime",
                "private": True,
                "dependencies": {
                    policy.wrangler_package_name: artifact_item.version
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    write_release_record(
        root,
        artifact_item,
        "distribution=npm",
        f"npm_integrity={policy.wrangler_npm_integrity}",
        f"node_requirement={policy.wrangler_node_requirement}",
    )


def prepare_obs_build(
    policy: InstallPolicy,
    archive_path: pathlib.Path,
    root: pathlib.Path,
    workspace: pathlib.Path,
) -> None:
    artifact_item = policy.obs_build
    archive_root = policy.obs_build_archive_root
    source_parent = workspace / "obs-source"
    source_parent.mkdir(mode=0o700)
    source_root = extract_validated_tar(
        archive_path,
        "obs-build archive",
        archive_root,
        source_parent,
        policy.max_archive_members,
        policy.max_extracted_bytes,
    )
    destdir = workspace / "obs-destdir"
    destdir.mkdir(mode=0o700)
    run_checked(
        [
            str(MAKE),
            "-C",
            str(source_root),
            "install",
            f"DESTDIR={destdir}",
            f"prefix={artifact_item.install_root}",
        ],
        f"installing obs-build {artifact_item.version}",
        timeout=policy.make_timeout_seconds,
    )
    produced_root = destdir / artifact_item.install_root.relative_to("/")
    if not produced_root.is_dir() or produced_root.is_symlink():
        fail("obs-build make install did not create the managed root")
    shutil.move(str(produced_root), root)
    for command in policy.obs_build_entrypoints:
        entrypoint = root / "bin" / command
        if not entrypoint.is_symlink():
            fail(f"obs-build entrypoint is missing: {command}")
    write_release_record(
        root,
        artifact_item,
        f"tag={policy.obs_build_tag}",
        f"commit={policy.obs_build_commit}",
        "distribution=github-commit-archive",
    )


def sanitize_tree(root: pathlib.Path, final_root: pathlib.Path) -> None:
    if not root.is_dir() or root.is_symlink():
        fail(f"prepared tool root is invalid: {root}")
    for current_root, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current = pathlib.Path(current_root)
        for name in directory_names + file_names:
            path = current / name
            try:
                path_stat = path.lstat()
            except OSError:
                fail(f"prepared tool entry is unavailable: {path}")
            if stat.S_ISLNK(path_stat.st_mode):
                link_value = os.readlink(path)
                if os.path.isabs(link_value):
                    final_target = pathlib.PurePosixPath(link_value)
                    try:
                        relative_target = final_target.relative_to(
                            pathlib.PurePosixPath(str(final_root))
                        )
                    except ValueError:
                        fail(f"prepared tool symlink escapes its final root: {path}")
                    staged_target = root / pathlib.Path(*relative_target.parts)
                else:
                    staged_target = pathlib.Path(
                        os.path.normpath(path.parent / link_value)
                    )
                    try:
                        staged_target.relative_to(root)
                    except ValueError:
                        fail(f"prepared tool symlink escapes its root: {path}")
                if not os.path.lexists(staged_target):
                    fail(f"prepared tool symlink target is missing: {path}")
                os.lchown(path, 0, 0)
            elif stat.S_ISDIR(path_stat.st_mode):
                path.chmod(0o755)
                os.chown(path, 0, 0)
            elif stat.S_ISREG(path_stat.st_mode):
                executable_bits = stat.S_IMODE(path_stat.st_mode) & 0o111
                path.chmod(0o644 | executable_bits)
                os.chown(path, 0, 0)
            else:
                fail(f"prepared tool tree contains an unsupported entry: {path}")
    root.chmod(0o755)
    os.chown(root, 0, 0)


def verify_installation(policy: InstallPolicy) -> None:
    deno = run_checked(
        [str(policy.deno.binary_path), "--version"],
        "verifying Deno",
        timeout=policy.verify_timeout_seconds,
        capture_output=True,
    )
    if not deno.stdout.startswith(f"deno {policy.deno.version} "):
        fail("Deno version verification returned unexpected output")

    require_program(policy.yt_dlp_payload_path, "managed yt-dlp payload")
    yt_dlp = run_checked(
        [str(policy.yt_dlp.binary_path), "--version"],
        "verifying yt-dlp",
        timeout=policy.verify_timeout_seconds,
        environment={
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "TZ": "UTC",
        },
        capture_output=True,
    )
    if yt_dlp.stdout.strip() != policy.yt_dlp.version:
        fail("yt-dlp version verification returned unexpected output")

    for command in sorted(ANSIBLE_CONSOLE_SCRIPTS):
        require_program(
            policy.ansible_core.install_root / "bin" / command,
            f"Ansible Core command {command}",
        )

    # ``in-target`` can preserve the installer's locale variables even when
    # that preferred locale is not available inside the fresh target yet.
    # Ansible initializes the process locale before handling ``--version`` and
    # requires UTF-8, so verify it with a closed UTF-8 locale.
    ansible_environment = {
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TZ": "UTC",
    }
    ansible = run_checked(
        [str(policy.ansible_core.binary_path), "--version"],
        "verifying Ansible CLI from Ansible Core",
        timeout=policy.verify_timeout_seconds,
        environment=ansible_environment,
        capture_output=True,
    )
    if f"ansible [core {policy.ansible_core.version}]" not in ansible.stdout:
        fail("Ansible Core version verification returned unexpected output")
    for completion_path in (
        policy.ansible_core.install_root
        / "share/bash-completion/completions/ansible",
        policy.ansible_core.install_root
        / "share/zsh/site-functions/_ansible-managed",
    ):
        if not completion_path.is_file():
            fail(f"Ansible completion fragment is missing: {completion_path}")

    tofu = run_checked(
        [str(policy.opentofu.binary_path), "version"],
        "verifying OpenTofu",
        timeout=policy.verify_timeout_seconds,
        capture_output=True,
    )
    if f"OpenTofu v{policy.opentofu.version}" not in tofu.stdout:
        fail("OpenTofu version verification returned unexpected output")

    terraform = run_checked(
        [str(policy.terraform.binary_path), "version"],
        "verifying Terraform",
        timeout=policy.verify_timeout_seconds,
        capture_output=True,
    )
    if f"Terraform v{policy.terraform.version}" not in terraform.stdout:
        fail("Terraform version verification returned unexpected output")

    packer = run_checked(
        [str(policy.packer.binary_path), "version"],
        "verifying Packer",
        timeout=policy.verify_timeout_seconds,
        capture_output=True,
    )
    if f"Packer v{policy.packer.version}" not in packer.stdout:
        fail("Packer version verification returned unexpected output")

    aptly = run_checked(
        [str(policy.aptly.binary_path), "version"],
        "verifying Aptly",
        timeout=policy.verify_timeout_seconds,
        capture_output=True,
    )
    if policy.aptly.version not in aptly.stdout:
        fail("Aptly version verification returned unexpected output")

    # osc initializes user configuration before dispatching even its version
    # subcommand. Verify the checksum-pinned installed wheel offline so installer
    # provisioning cannot prompt for credentials or write to root's HOME.
    require_program(policy.osc.binary_path, "osc")
    osc_metadata_path = (
        policy.osc.install_root
        / "lib"
        / policy.osc_dist_info_root
        / "METADATA"
    )
    try:
        osc_metadata = email.parser.BytesParser().parsebytes(
            osc_metadata_path.read_bytes()
        )
    except OSError:
        fail("installed osc distribution metadata is unavailable")
    if (
        osc_metadata.get("Name") != policy.osc_package_root
        or osc_metadata.get("Version") != policy.osc.version
    ):
        fail("installed osc distribution metadata does not match the managed release")

    node_bin = policy.wrangler_node_root / "bin"
    wrangler_environment = {
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C",
        "PATH": f"{node_bin}:/usr/bin:/bin",
        "TZ": "UTC",
    }
    wrangler = run_checked(
        [str(policy.wrangler.binary_path), "--version"],
        "verifying Wrangler",
        timeout=policy.verify_timeout_seconds,
        environment=wrangler_environment,
        capture_output=True,
    )
    if policy.wrangler.version not in wrangler.stdout:
        fail("Wrangler version verification returned unexpected output")

    require_program(policy.obs_build.binary_path, "obs-build build launcher")
    try:
        build_script = policy.obs_build.binary_path.resolve(strict=True)
        build_script.relative_to(policy.obs_build.install_root)
    except (OSError, ValueError):
        fail("obs-build command entrypoint escapes the managed install root")
    try:
        with build_script.open("rb") as handle:
            build_shebang = handle.readline(128)
    except OSError:
        fail("obs-build build launcher is unreadable")
    if build_shebang != b"#!/bin/bash\n":
        fail("obs-build build launcher does not declare /bin/bash")
    run_checked(
        [str(BASH), "-n", str(build_script)],
        "verifying obs-build Bash syntax",
        timeout=policy.verify_timeout_seconds,
        capture_output=True,
    )


def install_tools(policy: InstallPolicy) -> None:
    require_root(policy)
    require_program(ARGCOMPLETE, "argcomplete registration helper")
    require_program(BASH, "Bash")
    require_program(CURL, "curl")
    require_program(MAKE, "make")
    require_program(PYTHON, "Python")
    require_program(PERL, "Perl")
    require_program(policy.wrangler_node_root / "bin/node", "managed Node runtime")
    require_program(policy.wrangler_node_root / "bin/npm", "managed npm runtime")
    require_install_parent(policy)

    workspace = pathlib.Path(
        tempfile.mkdtemp(prefix=".devops-upstream.", dir=policy.install_parent)
    )
    workspace.chmod(0o700)
    downloads = workspace / "downloads"
    prepared = workspace / "prepared"
    downloads.mkdir(mode=0o700)
    prepared.mkdir(mode=0o700)
    published: list[pathlib.Path] = []
    try:
        downloaded = {
            artifact_item.key: download_artifact(
                policy,
                artifact_item,
                downloads,
            )
            for artifact_item in policy.download_artifacts
        }
        prepared_roots = {
            artifact_item.install_root: prepared / artifact_item.key
            for artifact_item in policy.artifacts
        }

        prepare_deno(
            policy,
            downloaded[policy.deno.key],
            prepared_roots[policy.deno.install_root],
        )
        prepare_yt_dlp(
            policy,
            downloaded[policy.yt_dlp.key],
            prepared_roots[policy.yt_dlp.install_root],
        )
        prepare_ansible_core(
            policy,
            downloaded[policy.ansible_core.key],
            prepared_roots[policy.ansible_core.install_root],
        )
        prepare_opentofu(
            policy,
            downloaded[policy.opentofu.key],
            prepared_roots[policy.opentofu.install_root],
        )
        prepare_hashicorp_release(
            policy,
            downloaded[policy.terraform.key],
            prepared_roots[policy.terraform.install_root],
            policy.terraform,
            policy.terraform_archive_files,
            "terraform",
        )
        prepare_hashicorp_release(
            policy,
            downloaded[policy.packer.key],
            prepared_roots[policy.packer.install_root],
            policy.packer,
            policy.packer_archive_files,
            "packer",
        )
        prepare_wrangler(
            policy,
            downloaded[policy.wrangler.key],
            prepared_roots[policy.wrangler.install_root],
            workspace,
        )
        prepare_aptly(
            policy,
            downloaded[policy.aptly.key],
            prepared_roots[policy.aptly.install_root],
        )
        prepare_osc(
            policy,
            downloaded[policy.osc.key],
            prepared_roots[policy.osc.install_root],
        )
        prepare_obs_build(
            policy,
            downloaded[policy.obs_build.key],
            prepared_roots[policy.obs_build.install_root],
            workspace,
        )

        for final_root, prepared_root in prepared_roots.items():
            sanitize_tree(prepared_root, final_root)
        for final_root, prepared_root in prepared_roots.items():
            if os.path.lexists(final_root):
                fail(f"tool root appeared during staging: {final_root}")
            os.replace(prepared_root, final_root)
            published.append(final_root)
        verify_installation(policy)
    except BaseException:
        for final_root in reversed(published):
            shutil.rmtree(final_root, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    for artifact_item in policy.artifacts:
        print(
            f"installed {artifact_item.name} {artifact_item.version} "
            f"under {artifact_item.install_root}"
        )


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--policy":
        print("fatal: usage: devops-tools.py --policy ABSOLUTE_JSON_PATH", file=sys.stderr)
        return 64
    try:
        policy = load_policy(pathlib.Path(sys.argv[2]))
        install_tools(policy)
    except ToolInstallError as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("fatal: upstream DevOps tool installation interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
