"""Environment construction and user-owned runtime state management."""

from __future__ import annotations

import grp
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import stat
import tempfile
import time

from .commands import managed_library_path
from .user_state import (
    ensure_managed_user_directory,
    ensure_managed_user_file,
    ensure_user_owned_directory,
    load_user_json_object,
    reject_duplicate_json_keys,
    replace_user_text_atomic,
    resolve_home_relative_path,
    validate_seed_file,
)
from .profiles import (
    APPS,
    CHATGPT_DEVOPS_READ_WRITE_HOME_DIRECTORIES,
    CHATGPT_DEVOPS_READ_WRITE_PATHS,
    DISCORD_EXECUTABLE_FILES,
    DISCORD_MODULES_FILE,
    DISCORD_MODULES_ROOT,
    DISCORD_RELEASE_FILE,
    DISCORD_REQUIRED_FILES,
    DISCORD_REQUIRED_MODULES,
    DISCORD_ROOT,
    DISCORD_STATE_FILE,
    INTEL_ACCELERATION_ENV,
    MANAGED_RUNTIME_STATE,
    NVIDIA_ACCELERATION_ENV,
    OBSIDIAN_REGISTRY_MAX_BYTES,
    OBSIDIAN_VAULT_RELATIVE_PATH,
)
from .runtime import (
    MANAGED_DEFAULTS_KEYS,
    MAX_MANAGED_DEFAULTS_BYTES,
    MANAGED_PATH,
    MANAGED_NO_VULKAN_ENVIRONMENT,
    MANAGED_WAYLAND_OPENGL_ENVIRONMENT,
    current_user_home,
    current_user_name,
    current_user_runtime_dir,
    fail,
    validate_absolute_path,
    validate_runtime_entry_name,
    validate_session_bus_address,
)

MANAGED_DEFAULT_EXEC_MODES = {
    "/usr/local/bin/labwc-managed-app launch": "launch",
    "/usr/local/bin/labwc-managed-app intel": "intel",
    "/usr/local/bin/labwc-managed-app nvidia": "nvidia",
}
DISCORD_SETTINGS_MAX_BYTES = 1024 * 1024
DISCORD_MANAGED_SETTINGS = {
    "SKIP_HOST_UPDATE": True,
    "SKIP_MODULE_UPDATE": True,
}
DISCORD_RELEASE_MAX_BYTES = 4096
DISCORD_MODULES_MAX_BYTES = 1024 * 1024
DISCORD_STATE_MAX_BYTES = 1024 * 1024
DISCORD_TREE_MAXIMUM_FILES = 40_000
DISCORD_TREE_MAXIMUM_BYTES = 2_147_483_648
DISCORD_MODULE_NAME_RE = re.compile(r"discord_[a-z0-9_]{1,64}")
DISCORD_VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){2}")
DISCORD_SHA256_RE = re.compile(r"[0-9a-f]{64}")
CHATGPT_FORBIDDEN_AMBIENT_ENVIRONMENT = (
    "BASH_ENV",
    "DESKTOP_STARTUP_ID",
    "DISPLAY",
    "ENV",
    "LD_AUDIT",
    "LD_DEBUG",
    "LD_PRELOAD",
    "PYTHONHOME",
    "PYTHONINSPECT",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "SESSION_MANAGER",
    "WINDOWID",
    "WLR_XWAYLAND",
    "XAUTHORITY",
    "XWAYLAND",
    "XWAYLAND_FORCE_SCALE",
    "XWAYLAND_NO_GLAMOR",
    "XWAYLAND_PATH",
    "XWAYLAND_RESTART_DELAY",
    "_XWAYLAND_GLOBAL_OUTPUT_SCALE",
)
CHATGPT_DEVOPS_ENVIRONMENT_RESERVED = frozenset(
    {
        "COLORTERM",
        "DBUS_SESSION_BUS_ADDRESS",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "OLDPWD",
        "PWD",
        "QT_QPA_PLATFORMTHEME",
        "SHELL",
        "SHLVL",
        "TERM",
        "TZ",
        "USER",
        "WAYLAND_DISPLAY",
        "XDG_RUNTIME_DIR",
        "_",
    }
)
CHATGPT_DEVOPS_ENVIRONMENT_MAXIMUM_BYTES = 262_144
CHATGPT_DEVOPS_ENVIRONMENT_MAXIMUM_NAMES = 256
CHATGPT_DEVOPS_PATH_MAXIMUM_ENTRIES = 128
CHATGPT_POOL_STORAGE_ROOTS = (
    "/pool/cache",
    "/pool/build",
    "/pool/db",
)
CHATGPT_POOL_ROOT_MODE = 0o3775
CHATGPT_POOL_STORAGE_MODE = 0o2770
CHATGPT_CODEX_ROOT_MODE = 0o3770
CHATGPT_SHARED_DOWNLOADS_ROOT_MODE = 0o2750
CHATGPT_CODEX_WRAPPER_DIRECTORY = "/data/codex/lib"
CHATGPT_CODEX_RELEASE_BINARY_DIRECTORY = "/data/codex/share/bin"


def validate_managed_work_directory(
    label: str,
    path: str,
    *,
    expected_uid: int,
    expected_gid: int | None = None,
    expected_mode: int | None = None,
) -> None:
    validate_absolute_path(label, path)
    if os.path.realpath(path) != path:
        fail(f"{label} must not traverse symlinks: {path}")
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        fail(f"{label} is unavailable: {path}: {exc}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        fail(f"{label} must be a real directory: {path}")
    if metadata.st_uid != expected_uid:
        fail(f"{label} has unexpected owner: {path}: {metadata.st_uid}")
    if expected_gid is not None and metadata.st_gid != expected_gid:
        fail(f"{label} has unexpected group: {path}: {metadata.st_gid}")
    mode = stat.S_IMODE(metadata.st_mode)
    if expected_mode is not None and mode != expected_mode:
        fail(f"{label} must remain mode {expected_mode:04o}: {path}")
    if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        fail(f"{label} must remain writable by the current desktop account: {path}")


def validate_chatgpt_work_areas(user_name: str, home_dir: str) -> None:
    if (
        not re.fullmatch(r"[A-Za-z0-9_.@-]+", user_name)
        or user_name in {".", ".."}
    ):
        fail("current desktop account name is unsafe for managed ChatGPT work areas")
    validate_absolute_path("current desktop account home", home_dir)

    try:
        devops_gid = grp.getgrnam("devops").gr_gid
    except (KeyError, OSError) as exc:
        fail(f"managed devops group is unavailable: {exc}")
    try:
        group_ids = {os.getgid(), *os.getgroups()}
    except OSError as exc:
        fail(f"cannot resolve current desktop account groups: {exc}")
    if devops_gid not in group_ids:
        fail("current desktop account is not a member of the managed devops group")

    account_uid = os.getuid()
    account_gid = os.getgid()
    for relative_path in CHATGPT_DEVOPS_READ_WRITE_HOME_DIRECTORIES:
        validate_managed_work_directory(
            f"managed ChatGPT {relative_path} directory",
            os.path.join(home_dir, relative_path),
            expected_uid=account_uid,
        )

    validate_managed_work_directory(
        "managed ChatGPT pool root",
        "/pool",
        expected_uid=0,
        expected_gid=devops_gid,
        expected_mode=CHATGPT_POOL_ROOT_MODE,
    )
    for pool_root in CHATGPT_POOL_STORAGE_ROOTS:
        validate_managed_work_directory(
            f"managed ChatGPT {os.path.basename(pool_root)} root",
            pool_root,
            expected_uid=0,
            expected_gid=devops_gid,
            expected_mode=CHATGPT_POOL_STORAGE_MODE,
        )
        validate_managed_work_directory(
            f"managed ChatGPT {os.path.basename(pool_root)} account directory",
            os.path.join(pool_root, user_name),
            expected_uid=account_uid,
            expected_gid=devops_gid,
            expected_mode=CHATGPT_POOL_STORAGE_MODE,
        )
    validate_managed_work_directory(
        "managed ChatGPT Codex storage root",
        "/data/codex",
        expected_uid=0,
        expected_gid=devops_gid,
        expected_mode=CHATGPT_CODEX_ROOT_MODE,
    )
    validate_managed_work_directory(
        "managed ChatGPT shared downloads root",
        "/data/downloads",
        expected_uid=account_uid,
        expected_gid=account_gid,
        expected_mode=CHATGPT_SHARED_DOWNLOADS_ROOT_MODE,
    )

    expected_absolute_paths = (
        "/pool",
        "/data/codex",
        "/data/downloads",
    )
    if CHATGPT_DEVOPS_READ_WRITE_PATHS != expected_absolute_paths:
        fail("managed ChatGPT absolute work-area policy is inconsistent")


def load_managed_defaults(path: pathlib.Path) -> dict[str, str]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        fail(f"managed desktop defaults are unavailable: {path}: {exc}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail(f"managed desktop defaults must be a regular file: {path}")
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        fail(
            "managed desktop defaults must be root-owned and not writable by "
            f"group or others: {path}"
        )
    if metadata.st_size > MAX_MANAGED_DEFAULTS_BYTES:
        fail(f"managed desktop defaults exceed {MAX_MANAGED_DEFAULTS_BYTES} bytes: {path}")

    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"failed to read managed desktop defaults: {path}: {exc}")
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in MANAGED_DEFAULTS_KEYS:
            continue
        try:
            parsed = shlex.split(raw_value, comments=False, posix=True)
        except ValueError as exc:
            fail(f"invalid {key} assignment on line {line_number}: {exc}")
        if len(parsed) != 1:
            fail(f"invalid {key} assignment on line {line_number}")
        values[key] = parsed[0]

    return values


def acceleration_availability_from_defaults(values: dict[str, str]) -> dict[str, bool]:
    availability: dict[str, bool] = {}
    for mode, key in (
        ("intel", "LABWC_INTEL_ACCELERATION_AVAILABLE"),
        ("nvidia", "LABWC_NVIDIA_ACCELERATION_AVAILABLE"),
    ):
        value = values.get(key, "")
        if value not in {"true", "false"}:
            fail(f"{key} must be true or false in managed desktop defaults")
        availability[mode] = value == "true"
    return availability


def load_acceleration_availability(path: pathlib.Path) -> dict[str, bool]:
    return acceleration_availability_from_defaults(load_managed_defaults(path))


def load_managed_launch_policy(path: pathlib.Path) -> tuple[dict[str, bool], str]:
    values = load_managed_defaults(path)
    availability = acceleration_availability_from_defaults(values)
    default_exec = values.get("LABWC_MANAGED_APP_DEFAULT_EXEC", "")
    default_mode = MANAGED_DEFAULT_EXEC_MODES.get(default_exec)
    if default_mode is None:
        fail(
            "LABWC_MANAGED_APP_DEFAULT_EXEC must select the managed launch, "
            "intel, or nvidia command in managed desktop defaults"
        )
    validate_acceleration_mode(default_mode, availability)
    return availability, default_mode


def validate_acceleration_mode(mode: str, availability: dict[str, bool]) -> None:
    if mode in {"intel", "nvidia"} and not availability[mode]:
        fail(f"{mode} acceleration is unavailable on this target")












def managed_database_state_root(app_name: str, user_name: str) -> str | None:
    state_directory = APPS[app_name].get("database_state_directory")
    if state_directory is None:
        return None
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", state_directory) is None:
        fail(f"{app_name} database state directory is invalid")
    if (
        re.fullmatch(r"[A-Za-z0-9_.@-]+", user_name) is None
        or user_name in {".", ".."}
    ):
        fail("current desktop account name is unsafe for managed database state")
    return f"/pool/db/{user_name}/{state_directory}"




def ensure_managed_database_runtime_state(app_name: str) -> None:
    user_name = current_user_name()
    state_root = managed_database_state_root(app_name, user_name)
    if state_root is None:
        return

    try:
        devops_gid = grp.getgrnam("devops").gr_gid
    except (KeyError, OSError) as exc:
        fail(f"managed devops group is unavailable: {exc}")
    try:
        group_ids = {os.getgid(), *os.getgroups()}
    except OSError as exc:
        fail(f"cannot resolve current desktop account groups: {exc}")
    if devops_gid not in group_ids:
        fail("current desktop account is not a member of the managed devops group")

    account_uid = os.getuid()
    validate_managed_work_directory(
        "managed database pool root",
        "/pool",
        expected_uid=0,
        expected_gid=devops_gid,
        expected_mode=CHATGPT_POOL_ROOT_MODE,
    )
    validate_managed_work_directory(
        "managed database storage root",
        "/pool/db",
        expected_uid=0,
        expected_gid=devops_gid,
        expected_mode=CHATGPT_POOL_STORAGE_MODE,
    )
    validate_managed_work_directory(
        "managed database account directory",
        f"/pool/db/{user_name}",
        expected_uid=account_uid,
        expected_gid=devops_gid,
        expected_mode=CHATGPT_POOL_STORAGE_MODE,
    )

    for directory in (
        state_root,
        f"{state_root}/cache",
        f"{state_root}/config",
        f"{state_root}/data",
        f"{state_root}/state",
    ):
        if not os.path.exists(directory) and not os.path.islink(directory):
            os.mkdir(directory, 0o700)
        directory_stat = os.lstat(directory)
        if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
            fail(f"managed {app_name} database state is not a real directory: {directory}")
        if directory_stat.st_uid != account_uid or os.path.realpath(directory) != directory:
            fail(f"managed {app_name} database state has unsafe ownership or ancestry: {directory}")
        os.chown(directory, account_uid, devops_gid)
        os.chmod(directory, 0o700)
        validate_managed_work_directory(
            f"managed {app_name} database state directory",
            directory,
            expected_uid=account_uid,
            expected_gid=devops_gid,
            expected_mode=0o700,
        )


def ensure_managed_runtime_state(app_name: str, home_dir: str) -> None:
    state_spec = MANAGED_RUNTIME_STATE.get(app_name)
    if state_spec is not None:
        validate_absolute_path("managed runtime HOME", home_dir)
        home_stat = os.lstat(home_dir)
        if stat.S_ISLNK(home_stat.st_mode) or not stat.S_ISDIR(home_stat.st_mode):
            fail(f"managed runtime HOME is not a real directory: {home_dir}")
        if home_stat.st_uid != os.getuid():
            fail(f"managed runtime HOME is not owned by the current user: {home_dir}")
        for relative_path, mode in state_spec["directories"]:
            ensure_managed_user_directory(
                home_dir,
                relative_path,
                mode,
                preserve_existing_mode=app_name == "chatgpt",
            )
        for relative_path, mode, seed_path in state_spec.get("files", ()):
            ensure_managed_user_file(home_dir, relative_path, mode, seed_path)
    ensure_managed_database_runtime_state(app_name)






def require_root_owned_regular_file(
    path: str,
    *,
    executable: bool = False,
    nonempty: bool = True,
) -> os.stat_result:
    validate_absolute_path("managed root-owned file", path)
    try:
        file_stat = os.lstat(path)
    except OSError as exc:
        fail(f"managed root-owned file is unavailable: {path}: {exc}")
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        fail(f"managed root-owned file must be a regular file: {path}")
    if file_stat.st_uid != 0 or file_stat.st_gid != 0 or file_stat.st_mode & 0o022:
        fail(
            "managed root-owned file must be owned by root:root and not "
            f"writable by group or others: {path}"
        )
    if nonempty and file_stat.st_size == 0:
        fail(f"managed root-owned file must not be empty: {path}")
    if executable and not file_stat.st_mode & 0o111:
        fail(f"managed root-owned executable is not executable: {path}")
    return file_stat


def load_root_owned_text(path: str, maximum_bytes: int) -> str:
    file_stat = require_root_owned_regular_file(path)
    if file_stat.st_size > maximum_bytes:
        fail(f"managed root-owned file exceeds the size limit: {path}")
    try:
        return pathlib.Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"failed to read managed root-owned file: {path}: {exc}")


def load_root_json_object(path: str, maximum_bytes: int) -> dict[str, object]:
    raw = load_root_owned_text(path, maximum_bytes)
    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate_json_keys)
    except json.JSONDecodeError as exc:
        fail(f"managed root-owned JSON is invalid: {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"managed root-owned JSON must contain an object: {path}")
    return value


def require_root_owned_directory(path: str) -> None:
    validate_absolute_path("managed root-owned directory", path)
    try:
        directory_stat = os.lstat(path)
    except OSError as exc:
        fail(f"managed root-owned directory is unavailable: {path}: {exc}")
    if (
        stat.S_ISLNK(directory_stat.st_mode)
        or not stat.S_ISDIR(directory_stat.st_mode)
        or directory_stat.st_uid != 0
        or directory_stat.st_gid != 0
        or directory_stat.st_mode & 0o022
    ):
        fail(
            "managed root-owned directory must be owned by root:root and not "
            f"writable by group or others: {path}"
        )


def validate_discord_runtime_tree() -> None:
    require_root_owned_directory(DISCORD_ROOT)
    try:
        root_stat = os.lstat(DISCORD_ROOT)
    except OSError as exc:
        fail(f"managed Discord runtime cannot be inspected: {DISCORD_ROOT}: {exc}")
    if stat.S_IMODE(root_stat.st_mode) != 0o755:
        fail("managed Discord runtime root must have mode 0755")

    pending_directories = [DISCORD_ROOT]
    filesystem_entries = 0
    regular_bytes = 0
    chrome_sandbox = f"{DISCORD_ROOT}/chrome-sandbox"
    while pending_directories:
        directory = pending_directories.pop()
        try:
            entries = os.scandir(directory)
        except OSError as exc:
            fail(f"managed Discord runtime directory cannot be read: {directory}: {exc}")
        with entries:
            for entry in entries:
                path = entry.path
                try:
                    metadata = os.lstat(path)
                except OSError as exc:
                    fail(f"managed Discord runtime entry cannot be inspected: {path}: {exc}")
                if stat.S_ISLNK(metadata.st_mode):
                    fail(f"managed Discord runtime contains a symlink: {path}")
                if (
                    metadata.st_uid != 0
                    or metadata.st_gid != 0
                    or metadata.st_mode & 0o022
                ):
                    fail(
                        "managed Discord runtime entry must be owned by root:root "
                        f"and not writable by group or others: {path}"
                    )
                filesystem_entries += 1
                if filesystem_entries > DISCORD_TREE_MAXIMUM_FILES:
                    fail("managed Discord runtime exceeds its filesystem-entry limit")

                special_bits = stat.S_IMODE(metadata.st_mode) & 0o7000
                if stat.S_ISDIR(metadata.st_mode):
                    if stat.S_IMODE(metadata.st_mode) != 0o755:
                        fail(
                            "managed Discord runtime directory must have mode "
                            f"0755: {path}"
                        )
                    pending_directories.append(path)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    fail(f"managed Discord runtime contains an unsupported object: {path}")
                if path == chrome_sandbox:
                    if special_bits != stat.S_ISUID:
                        fail("managed Discord Chromium sandbox has unsafe special mode bits")
                elif special_bits:
                    fail(
                        "managed Discord runtime file has unsafe special mode bits: "
                        f"{path}"
                    )
                regular_bytes += metadata.st_size
                if regular_bytes > DISCORD_TREE_MAXIMUM_BYTES:
                    fail("managed Discord runtime exceeds its regular-file size limit")


def load_discord_release() -> tuple[str, dict[str, object]]:
    validate_discord_runtime_tree()
    require_root_owned_directory(f"{DISCORD_ROOT}/resources")
    require_root_owned_directory(DISCORD_MODULES_ROOT)
    for path in DISCORD_REQUIRED_FILES:
        require_root_owned_regular_file(
            path,
            executable=path in DISCORD_EXECUTABLE_FILES,
        )
    for path in DISCORD_EXECUTABLE_FILES:
        try:
            with open(path, "rb") as executable:
                magic = executable.read(4)
        except OSError as exc:
            fail(f"managed Discord executable cannot be inspected: {path}: {exc}")
        if magic != b"\x7fELF":
            fail(f"managed Discord executable is not ELF: {path}")
    chrome_sandbox_stat = os.lstat(f"{DISCORD_ROOT}/chrome-sandbox")
    if not chrome_sandbox_stat.st_mode & stat.S_ISUID:
        fail("managed Discord Chromium sandbox is not set-ID root")

    release_text = load_root_owned_text(
        DISCORD_RELEASE_FILE,
        DISCORD_RELEASE_MAX_BYTES,
    )
    if not release_text.endswith("\n") or "\r" in release_text:
        fail(f"managed Discord release marker is malformed: {DISCORD_RELEASE_FILE}")
    release_lines = release_text.splitlines()
    release: dict[str, str] = {}
    for line in release_lines:
        if not line or "=" not in line:
            fail(f"managed Discord release marker is malformed: {DISCORD_RELEASE_FILE}")
        key, value = line.split("=", 1)
        if key in release:
            fail(f"managed Discord release marker repeats {key}")
        release[key] = value
    if set(release) != {
        "architecture",
        "channel",
        "host_sha256",
        "manifest_sha256",
        "modules",
        "version",
    }:
        fail(f"managed Discord release marker has unexpected fields: {DISCORD_RELEASE_FILE}")
    version = release["version"]
    if (
        release["channel"] != "stable"
        or release["architecture"] != "amd64"
        or DISCORD_VERSION_RE.fullmatch(version) is None
        or DISCORD_SHA256_RE.fullmatch(release["manifest_sha256"]) is None
        or DISCORD_SHA256_RE.fullmatch(release["host_sha256"]) is None
        or not release["modules"].isascii()
        or not release["modules"].isdigit()
    ):
        fail(f"managed Discord release marker is invalid: {DISCORD_RELEASE_FILE}")

    modules = load_discord_module_metadata(version)
    if not 5 <= len(modules) <= 32 or int(release["modules"]) != len(modules):
        fail("managed Discord module count does not match its release marker")
    if not set(DISCORD_REQUIRED_MODULES).issubset(modules):
        fail("managed Discord runtime omits a required stable Linux module")
    for name, metadata in modules.items():
        if (
            not isinstance(name, str)
            or DISCORD_MODULE_NAME_RE.fullmatch(name) is None
            or not isinstance(metadata, dict)
            or set(metadata) != {"installedVersion"}
            or isinstance(metadata["installedVersion"], bool)
            or not isinstance(metadata["installedVersion"], int)
            or not 1 <= metadata["installedVersion"] <= 999_999
        ):
            fail(f"managed Discord module metadata is invalid: {name}")
        require_root_owned_directory(os.path.join(DISCORD_MODULES_ROOT, name))
    return version, modules


def discord_modules_from_state(version: str) -> dict[str, object]:
    require_root_owned_directory("/var/lib/software")
    require_root_owned_directory("/var/lib/software/state")
    state = load_root_json_object(
        DISCORD_STATE_FILE,
        DISCORD_STATE_MAX_BYTES,
    )
    if set(state) != {"host", "manifest", "modules", "version"}:
        fail(f"managed Discord retained state has unexpected fields: {DISCORD_STATE_FILE}")
    if state["version"] != version:
        fail("managed Discord retained state does not match the installed release")

    host = state["host"]
    manifest = state["manifest"]
    state_modules = state["modules"]
    if (
        not isinstance(host, dict)
        or set(host) != {"file", "sha256"}
        or not isinstance(manifest, dict)
        or set(manifest) != {"file", "sha256"}
        or not isinstance(state_modules, dict)
    ):
        fail("managed Discord retained state is invalid")
    host_sha256 = host["sha256"]
    manifest_sha256 = manifest["sha256"]
    if (
        not isinstance(host_sha256, str)
        or DISCORD_SHA256_RE.fullmatch(host_sha256) is None
        or not isinstance(manifest_sha256, str)
        or DISCORD_SHA256_RE.fullmatch(manifest_sha256) is None
        or host["file"] != f"discord-{version}-host-{host_sha256}.full.distro"
        or manifest["file"]
        != f"discord-{version}-manifest-{manifest_sha256}.json"
    ):
        fail("managed Discord retained host state is invalid")

    modules: dict[str, object] = {}
    for name, metadata in state_modules.items():
        if (
            not isinstance(name, str)
            or DISCORD_MODULE_NAME_RE.fullmatch(name) is None
            or not isinstance(metadata, dict)
            or set(metadata) != {"file", "sha256", "version"}
            or isinstance(metadata["version"], bool)
            or not isinstance(metadata["version"], int)
            or not 1 <= metadata["version"] <= 999_999
            or not isinstance(metadata["sha256"], str)
            or DISCORD_SHA256_RE.fullmatch(metadata["sha256"]) is None
            or metadata["file"]
            != (
                f"discord-{version}-{name}-{metadata['version']}-"
                f"{metadata['sha256']}.full.distro"
            )
        ):
            fail(f"managed Discord retained module state is invalid: {name}")
        modules[name] = {"installedVersion": metadata["version"]}
    return modules


def load_discord_module_metadata(version: str) -> dict[str, object]:
    try:
        metadata = os.lstat(DISCORD_MODULES_FILE)
    except FileNotFoundError:
        return discord_modules_from_state(version)
    except OSError as exc:
        fail(f"managed Discord module metadata cannot be inspected: {exc}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail(f"managed Discord module metadata is unsafe: {DISCORD_MODULES_FILE}")
    return load_root_json_object(
        DISCORD_MODULES_FILE,
        DISCORD_MODULES_MAX_BYTES,
    )


def replace_discord_user_modules(
    home_dir: str,
    version: str,
    modules: dict[str, object],
) -> None:
    version_directory = resolve_home_relative_path(
        home_dir,
        f".config/discord/{version}",
    )
    ensure_user_owned_directory(version_directory, 0o700)
    modules_path = os.path.join(version_directory, "modules")
    temporary_path = tempfile.mkdtemp(
        prefix=".managed-modules.",
        dir=version_directory,
    )
    os.chmod(temporary_path, 0o700)
    backup_path = os.path.join(version_directory, ".managed-modules.previous")
    try:
        for name in sorted(modules):
            source = os.path.join(DISCORD_MODULES_ROOT, name)
            require_root_owned_directory(source)
            os.symlink(source, os.path.join(temporary_path, name))
        write_user_json_atomic(
            os.path.join(temporary_path, "installed.json"),
            modules,
            0o600,
        )

        try:
            existing_stat = os.lstat(modules_path)
        except FileNotFoundError:
            existing_stat = None
        except OSError as exc:
            fail(f"Discord user module directory is unavailable: {modules_path}: {exc}")
        if existing_stat is not None:
            if (
                stat.S_ISLNK(existing_stat.st_mode)
                or not stat.S_ISDIR(existing_stat.st_mode)
                or existing_stat.st_uid != os.getuid()
            ):
                fail(f"Discord user module path is unsafe: {modules_path}")
            if os.path.lexists(backup_path):
                backup_stat = os.lstat(backup_path)
                if (
                    stat.S_ISLNK(backup_stat.st_mode)
                    or not stat.S_ISDIR(backup_stat.st_mode)
                    or backup_stat.st_uid != os.getuid()
                ):
                    fail(f"Discord user module backup path is unsafe: {backup_path}")
                shutil.rmtree(backup_path)
            os.replace(modules_path, backup_path)
        os.replace(temporary_path, modules_path)
        if os.path.isdir(backup_path):
            shutil.rmtree(backup_path)
    except BaseException:
        if os.path.isdir(temporary_path):
            shutil.rmtree(temporary_path)
        if not os.path.lexists(modules_path) and os.path.isdir(backup_path):
            os.replace(backup_path, modules_path)
        raise


def write_user_json_atomic(path: str, value: dict[str, object], mode: int) -> None:
    parent = os.path.dirname(path)
    ensure_user_owned_directory(parent, 0o700)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        dir=parent,
    )
    descriptor_open = True
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor_open = False
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
    file_stat = os.lstat(path)
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        fail(f"managed JSON replacement is not a regular file: {path}")
    if file_stat.st_uid != os.getuid():
        fail(f"managed JSON replacement is not owned by the current user: {path}")
    os.chmod(path, mode)


def ensure_discord_managed_settings(home_dir: str) -> None:
    version, modules = load_discord_release()
    replace_discord_user_modules(home_dir, version, modules)
    settings_path = resolve_home_relative_path(
        home_dir,
        ".config/discord/settings.json",
    )
    try:
        os.lstat(settings_path)
    except FileNotFoundError:
        settings: dict[str, object] = {}
    except OSError as exc:
        fail(f"Discord settings are unavailable: {settings_path}: {exc}")
    else:
        settings = load_user_json_object(
            settings_path,
            DISCORD_SETTINGS_MAX_BYTES,
        )

    changed = False
    for key, value in DISCORD_MANAGED_SETTINGS.items():
        if settings.get(key) is value:
            continue
        settings[key] = value
        changed = True
    if changed or not os.path.exists(settings_path):
        write_user_json_atomic(settings_path, settings, 0o600)
    else:
        os.chmod(settings_path, 0o600)
        settings_stat = os.lstat(settings_path)
        if (
            stat.S_ISLNK(settings_stat.st_mode)
            or not stat.S_ISREG(settings_stat.st_mode)
            or settings_stat.st_uid != os.getuid()
            or stat.S_IMODE(settings_stat.st_mode) != 0o600
        ):
            fail(f"Discord managed settings mode could not be enforced: {settings_path}")


def obsidian_vault_id(vault_path: str) -> str:
    validate_absolute_path("Obsidian vault path", vault_path)
    return hashlib.sha256(vault_path.encode("utf-8")).hexdigest()[:16]


def ensure_obsidian_registry(home_dir: str) -> None:
    validate_absolute_path("Obsidian HOME", home_dir)
    try:
        home_stat = os.lstat(home_dir)
    except OSError as exc:
        fail(f"Obsidian HOME is unavailable: {home_dir}: {exc}")
    if stat.S_ISLNK(home_stat.st_mode) or not stat.S_ISDIR(home_stat.st_mode):
        fail(f"Obsidian HOME is not a real directory: {home_dir}")
    if home_stat.st_uid != os.getuid():
        fail(f"Obsidian HOME is not owned by the current user: {home_dir}")

    vault_path = resolve_home_relative_path(home_dir, OBSIDIAN_VAULT_RELATIVE_PATH)
    try:
        vault_stat = os.lstat(vault_path)
    except OSError as exc:
        fail(f"installed Obsidian vault is unavailable: {vault_path}: {exc}")
    if stat.S_ISLNK(vault_stat.st_mode) or not stat.S_ISDIR(vault_stat.st_mode):
        fail(f"installed Obsidian vault is not a real directory: {vault_path}")
    if vault_stat.st_uid != os.getuid():
        fail(f"installed Obsidian vault is not owned by the current user: {vault_path}")
    os.chmod(vault_path, 0o700)
    registry_directory = resolve_home_relative_path(home_dir, ".config/obsidian")
    try:
        registry_directory_stat = os.lstat(registry_directory)
    except OSError as exc:
        fail(f"Obsidian registry directory is unavailable: {registry_directory}: {exc}")
    if (
        stat.S_ISLNK(registry_directory_stat.st_mode)
        or not stat.S_ISDIR(registry_directory_stat.st_mode)
    ):
        fail(f"Obsidian registry directory is not a real directory: {registry_directory}")
    if registry_directory_stat.st_uid != os.getuid():
        fail(
            f"Obsidian registry directory is not owned by the current user: "
            f"{registry_directory}"
        )
    os.chmod(registry_directory, 0o700)
    registry_path = resolve_home_relative_path(
        home_dir,
        ".config/obsidian/obsidian.json",
    )
    registry = load_user_json_object(registry_path, OBSIDIAN_REGISTRY_MAX_BYTES)
    vaults = registry.get("vaults", {})
    if not isinstance(vaults, dict):
        fail(f"Obsidian vault registry must be an object: {registry_path}")

    for vault_id, entry in vaults.items():
        if not isinstance(vault_id, str) or not isinstance(entry, dict):
            fail(f"Obsidian vault registry contains an invalid entry: {registry_path}")
        if entry.get("path") == vault_path:
            return

    vault_id = obsidian_vault_id(vault_path)
    if vault_id in vaults:
        fail(f"Obsidian vault identifier collision: {vault_id}")
    entry: dict[str, object] = {
        "path": vault_path,
        "ts": int(time.time() * 1000),
    }
    if not any(
        isinstance(existing, dict) and existing.get("open") is True
        for existing in vaults.values()
    ):
        entry["open"] = True
    vaults[vault_id] = entry
    registry["vaults"] = vaults
    write_user_json_atomic(registry_path, registry, 0o600)


def validated_chatgpt_devops_environment() -> dict[str, str]:
    user_name = current_user_name()
    home_dir = current_user_home()
    if os.environ.get("DEVOPS_DE_ACTIVE") != "1":
        fail("ChatGPT requires the active environment from 71-devops-de.sh")
    for name in CHATGPT_FORBIDDEN_AMBIENT_ENVIRONMENT:
        if os.environ.get(name):
            fail(f"ChatGPT launcher forbids ambient environment variable: {name}")

    devops_environment: dict[str, str] = {}
    environment_bytes = 0
    for name, value in sorted(os.environ.items()):
        if name in CHATGPT_DEVOPS_ENVIRONMENT_RESERVED:
            continue
        if name in CHATGPT_FORBIDDEN_AMBIENT_ENVIRONMENT:
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            fail("ChatGPT received an unsafe DevOps environment variable name")
        environment_bytes += len(os.fsencode(f"{name}={value}")) + 1
        if environment_bytes > CHATGPT_DEVOPS_ENVIRONMENT_MAXIMUM_BYTES:
            fail("ChatGPT DevOps environment exceeds the 256 KiB limit")
        devops_environment[name] = value
    if len(devops_environment) > CHATGPT_DEVOPS_ENVIRONMENT_MAXIMUM_NAMES:
        fail("ChatGPT DevOps environment exceeds 256 variables")

    devops_path = devops_environment.get("PATH", "")
    path_entries = devops_path.split(":")
    if not devops_path or len(path_entries) > CHATGPT_DEVOPS_PATH_MAXIMUM_ENTRIES:
        fail("ChatGPT received an invalid DevOps PATH from 71-devops-de.sh")
    seen_entries: set[str] = set()
    for entry in path_entries:
        if (
            entry == "/"
            or re.fullmatch(r"/[A-Za-z0-9._/@+-]+", entry) is None
            or any(component in {"", ".", ".."} for component in entry.split("/")[1:])
            or entry in seen_entries
        ):
            fail("ChatGPT received an unsafe DevOps PATH from 71-devops-de.sh")
        seen_entries.add(entry)

    validate_chatgpt_work_areas(user_name, home_dir)
    return devops_environment


def chatgpt_sandbox_path(devops_path: str) -> str:
    entries = [
        entry
        for entry in devops_path.split(":")
        if entry
        not in {
            CHATGPT_CODEX_WRAPPER_DIRECTORY,
            CHATGPT_CODEX_RELEASE_BINARY_DIRECTORY,
        }
    ]
    entries.append(CHATGPT_CODEX_RELEASE_BINARY_DIRECTORY)
    return ":".join(entries)


def build_environment(app_name: str, mode: str) -> dict[str, str]:
    app = APPS[app_name]
    env: dict[str, str] = {}
    home_dir = current_user_home()
    user_name = current_user_name()
    runtime_dir = current_user_runtime_dir()
    session_bus_address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if session_bus_address:
        session_bus_address = validate_session_bus_address(session_bus_address)
    wayland_display = validate_runtime_entry_name(
        "WAYLAND_DISPLAY",
        os.environ.get("WAYLAND_DISPLAY", "wayland-0"),
    )
    for name in (
        "COLORTERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TZ",
    ):
        if os.environ.get(name):
            env[name] = os.environ[name]
    env.update(
        {
            "PATH": MANAGED_PATH,
            "USER": user_name,
            "LOGNAME": user_name,
            "SHELL": "/bin/sh",
            "HOME": home_dir,
            "XDG_RUNTIME_DIR": runtime_dir,
            "XDG_CONFIG_HOME": f"{home_dir}/.config",
            "XDG_CACHE_HOME": f"{home_dir}/.cache",
            "XDG_DATA_HOME": f"{home_dir}/.local/share",
            "XDG_STATE_HOME": f"{home_dir}/.local/state",
            "WAYLAND_DISPLAY": wayland_display,
            "XDG_SESSION_TYPE": "wayland",
            "XDG_CURRENT_DESKTOP": "labwc:wlroots",
            "XDG_SESSION_DESKTOP": "labwc",
            "DESKTOP_SESSION": "labwc",
            "FONTCONFIG_FILE": "/etc/fonts/fonts.conf",
            "FONTCONFIG_PATH": "/etc/fonts",
            "GTK_CSD": "0",
            "QT_QPA_PLATFORMTHEME": os.environ.get("QT_QPA_PLATFORMTHEME", "qt6ct"),
            "QT_WAYLAND_DISABLE_WINDOWDECORATION": "1",
            "SDL_VIDEODRIVER": os.environ.get("SDL_VIDEODRIVER", "wayland"),
            "CLUTTER_BACKEND": os.environ.get("CLUTTER_BACKEND", "wayland"),
            "GTK_A11Y": "none",
            "NO_AT_BRIDGE": "1",
        }
    )
    if session_bus_address:
        env["DBUS_SESSION_BUS_ADDRESS"] = session_bus_address
    env.update(app["env"])
    database_state_root = managed_database_state_root(app_name, user_name)
    if database_state_root is not None:
        env.update(
            {
                "DEVOPS_DATABASE_HOME": f"/pool/db/{user_name}",
                "XDG_CACHE_HOME": f"{database_state_root}/cache",
                "XDG_CONFIG_HOME": f"{database_state_root}/config",
                "XDG_DATA_HOME": f"{database_state_root}/data",
                "XDG_STATE_HOME": f"{database_state_root}/state",
            }
        )
        if app_name == "qoredb":
            env["QOREDB_CONFIG_DIR"] = f"{database_state_root}/config"
    if app.get("requires_devops_environment", False):
        env.update(validated_chatgpt_devops_environment())
    if app_name == "chatgpt":
        env["SHELL"] = "/bin/zsh"
        env["PATH"] = chatgpt_sandbox_path(env["PATH"])
    xdg_config_home = app.get("xdg_config_home")
    if xdg_config_home:
        env["XDG_CONFIG_HOME"] = resolve_home_relative_path(
            home_dir,
            xdg_config_home,
        )
    env.update(MANAGED_WAYLAND_OPENGL_ENVIRONMENT)
    library_path = managed_library_path(app_name)
    if library_path:
        env["LD_LIBRARY_PATH"] = library_path
    if mode == "intel":
        env.update(app.get("intel_env", {}))
        env.update(INTEL_ACCELERATION_ENV)
    elif mode == "nvidia":
        env.update(app.get("nvidia_env", {}))
        env.update(NVIDIA_ACCELERATION_ENV)
    env.update(app.get("final_env", {}))
    env.update(MANAGED_NO_VULKAN_ENVIRONMENT)
    for name in tuple(env):
        if name.startswith(("VK_", "__VK_", "MESA_VK_")):
            env.pop(name)
    return env
