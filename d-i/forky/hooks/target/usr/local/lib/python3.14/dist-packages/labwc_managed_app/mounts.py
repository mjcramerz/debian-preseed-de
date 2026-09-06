"""Validated Bubblewrap mount and device-bind construction."""

from __future__ import annotations

import os
import pathlib
import re
import stat

from .dbus_proxy import SYSTEM_BUS_SOCKET_PATH
from .user_state import resolve_home_relative_path
from .runtime import fail, validate_absolute_path


PRIVATE_TEMPORARY_DIRECTORIES = ("/tmp", "/var/tmp", "/dev/shm")


def add_dir_chain(command: list[str], path: str) -> None:
    parts = pathlib.PurePosixPath(path).parts
    current = ""
    for part in parts:
        if part == "/":
            current = "/"
            continue
        current = os.path.join(current, part) if current != "/" else f"/{part}"
        command.extend(["--dir", current])


def add_private_tmpfs_mounts(command: list[str]) -> None:
    for directory in PRIVATE_TEMPORARY_DIRECTORIES:
        command.extend(["--tmpfs", directory, "--chmod", "01777", directory])


def add_optional_bind(command: list[str], option: str, source: str, destination: str) -> None:
    if os.path.exists(source):
        add_dir_chain(command, os.path.dirname(destination))
        command.extend([option, source, destination])


def add_gpu_device_binds(
    command: list[str],
    mode: str,
) -> None:
    if mode not in {"launch", "intel", "nvidia"}:
        fail(f"unsupported managed accelerator mode: {mode}")

    render_devices = sorted(
        path
        for path in pathlib.Path("/dev/dri").glob("renderD[0-9]*")
        if re.fullmatch(r"renderD(?:0|[1-9][0-9]{0,5})", path.name)
    )
    if render_devices:
        command.extend(["--dir", "/dev/dri"])
    device_paths = [*render_devices]
    device_paths.extend(
        (
            pathlib.Path("/dev/kfd"),
            pathlib.Path("/dev/accel"),
        )
    )
    if mode == "nvidia":
        nvidia_device_paths = [
            pathlib.Path("/dev/nvidia-caps"),
            pathlib.Path("/dev/nvidiactl"),
            pathlib.Path("/dev/nvidia-uvm"),
            pathlib.Path("/dev/nvidia-uvm-tools"),
        ]
        device_paths.extend(nvidia_device_paths)
        device_paths.extend(sorted(pathlib.Path("/dev").glob("nvidia[0-9]*")))
    for device_path in device_paths[:64]:
        try:
            metadata = device_path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            fail(f"cannot inspect managed accelerator device {device_path}: {exc}")
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISCHR(metadata.st_mode)
        ):
            fail(
                "managed accelerator path must be a directory or character "
                f"device: {device_path}"
            )
        if metadata.st_uid != 0:
            fail(f"managed accelerator path must remain root-owned: {device_path}")
        command.extend(["--dev-bind", str(device_path), str(device_path)])


def add_video_device_binds(command: list[str], enabled: bool) -> None:
    if not enabled:
        return

    camera_devices = sorted(
        {
            device_path
            for pattern in ("media[0-9]*", "v4l-subdev[0-9]*", "video[0-9]*")
            for device_path in pathlib.Path("/dev").glob(pattern)
        }
    )
    for device_path in camera_devices[:64]:
        try:
            metadata = device_path.lstat()
        except OSError as exc:
            fail(f"cannot inspect managed camera device {device_path}: {exc}")
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISCHR(metadata.st_mode):
            fail(f"managed camera device must be a character device: {device_path}")
        command.extend(["--dev-bind", str(device_path), str(device_path)])


def add_system_bus_proxy_bind(command: list[str], proxy_socket: str) -> None:
    validate_absolute_path("system D-Bus proxy socket", proxy_socket)
    add_dir_chain(command, os.path.dirname(SYSTEM_BUS_SOCKET_PATH))
    command.extend(["--bind", proxy_socket, SYSTEM_BUS_SOCKET_PATH])


def validate_no_host_audio_device_binds(app_name: str, command: list[str]) -> None:
    bind_options = {
        "--bind",
        "--bind-try",
        "--dev-bind",
        "--dev-bind-try",
        "--ro-bind",
        "--ro-bind-try",
    }
    for index, argument in enumerate(command):
        if argument not in bind_options:
            continue
        if index + 2 >= len(command):
            fail(f"malformed bubblewrap bind while launching {app_name}")
        for raw_path in command[index + 1 : index + 3]:
            normalized_path = os.path.normpath(raw_path)
            if normalized_path == "/dev/snd" or normalized_path.startswith("/dev/snd/"):
                fail(
                    f"bubblewrap forbids direct ALSA device access for {app_name}: "
                    f"{raw_path}"
                )


def validate_no_host_display_device_binds(
    app_name: str,
    command: list[str],
) -> None:
    bind_options = {
        "--bind",
        "--bind-try",
        "--dev-bind",
        "--dev-bind-try",
        "--ro-bind",
        "--ro-bind-try",
    }
    for index, argument in enumerate(command):
        if argument not in bind_options:
            continue
        if index + 2 >= len(command):
            fail(f"malformed bubblewrap bind while launching {app_name}")
        for raw_path in command[index + 1 : index + 3]:
            normalized_path = os.path.normpath(raw_path)
            if (
                normalized_path == "/dev/dri"
                or (
                    normalized_path.startswith("/dev/dri/")
                    and re.fullmatch(
                        r"/dev/dri/renderD(?:0|[1-9][0-9]{0,5})",
                        normalized_path,
                    )
                    is None
                )
                or normalized_path == "/dev/nvidia-modeset"
            ):
                fail(
                    "managed application sandbox forbids host display-control "
                    f"device access for {app_name}: {raw_path}"
                )


def validate_pure_privacy_device_isolation(app_name: str, command: list[str]) -> None:
    validate_no_host_audio_device_binds(app_name, command)
    bind_options = {
        "--bind",
        "--bind-try",
        "--dev-bind",
        "--dev-bind-try",
        "--ro-bind",
        "--ro-bind-try",
    }
    for index, argument in enumerate(command):
        if argument not in bind_options:
            continue
        if index + 2 >= len(command):
            fail(f"malformed bubblewrap bind while launching {app_name}")
        for path in command[index + 1 : index + 3]:
            if (
                path == "/dev/dri"
                or path.startswith("/dev/dri/")
                or path == "/dev/kfd"
                or path == "/dev/accel"
                or path.startswith("/dev/accel/")
                or path.startswith("/dev/nvidia")
            ):
                fail(f"PurePrivacy forbids hardware GPU device access for {app_name}: {path}")


def resolve_home_relative_file(
    home_dir: str,
    relative_path: str,
    *,
    writable: bool = False,
    require_private_mode: bool = True,
) -> str:
    relative = pathlib.PurePosixPath(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        fail(f"invalid HOME-relative file path: {relative_path or 'unset'}")
    source_path = os.path.join(home_dir, relative_path)
    validate_absolute_path("HOME-relative source path", source_path)
    home_real = os.path.realpath(home_dir)
    source_real = os.path.realpath(source_path)
    if os.path.commonpath((home_real, source_real)) != home_real:
        fail(f"HOME-relative file escapes HOME: {source_path}")
    if source_real != source_path:
        fail(f"HOME-relative file must not traverse symlinks: {source_path}")
    try:
        metadata = os.lstat(source_path)
    except OSError as exc:
        fail(f"required HOME-relative file is unavailable: {source_path}: {exc}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail(f"HOME-relative file must be a regular file, not a symlink: {source_path}")
    if metadata.st_uid != os.getuid() or not os.access(source_path, os.R_OK):
        fail(f"HOME-relative file must be readable and owned by the current user: {source_path}")
    if not writable and require_private_mode and metadata.st_mode & 0o022:
        fail(f"HOME-relative file must not be writable by group or other: {source_path}")
    if writable and not os.access(source_path, os.W_OK):
        fail(f"HOME-relative file must be writable by the current user: {source_path}")
    return source_path


def resolve_optional_home_relative_directory(
    home_dir: str,
    relative_path: str,
    *,
    writable: bool = False,
    require_private_mode: bool = True,
) -> str | None:
    source_path = resolve_home_relative_path(home_dir, relative_path)
    source_real = os.path.realpath(source_path)
    if source_real != source_path:
        fail(f"HOME-relative directory must not traverse symlinks: {source_path}")
    try:
        metadata = os.lstat(source_path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        fail(f"cannot inspect HOME-relative directory {source_path}: {exc}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        fail(f"HOME-relative directory must be a real directory: {source_path}")
    required_access = os.R_OK | os.X_OK
    if writable:
        required_access |= os.W_OK
    if metadata.st_uid != os.getuid() or not os.access(source_path, required_access):
        access_description = (
            "readable, searchable, and writable"
            if writable
            else "readable and searchable"
        )
        fail(
            "HOME-relative directory must be "
            f"{access_description} and owned by the current user: {source_path}"
        )
    if not writable and require_private_mode and metadata.st_mode & 0o022:
        fail(f"HOME-relative directory must not be writable by group or other: {source_path}")
    return source_path


def add_home_directory_binds(
    command: list[str],
    home_dir: str,
    relative_paths: tuple[str, ...],
    option: str,
    *,
    require_private_mode: bool = True,
) -> None:
    if option not in {"--bind", "--ro-bind"}:
        fail(f"unsupported HOME directory bind option: {option}")
    for relative_path in relative_paths:
        source_path = resolve_optional_home_relative_directory(
            home_dir,
            relative_path,
            writable=option == "--bind",
            require_private_mode=require_private_mode,
        )
        if source_path is None:
            continue
        destination_path = os.path.join(home_dir, relative_path)
        add_dir_chain(command, destination_path)
        command.extend([option, source_path, destination_path])


def add_optional_home_file_binds(
    command: list[str],
    home_dir: str,
    relative_paths: tuple[str, ...],
    *,
    require_private_mode: bool = True,
) -> None:
    for relative_path in relative_paths:
        source_path = resolve_home_relative_path(home_dir, relative_path)
        source_real = os.path.realpath(source_path)
        if source_real != source_path:
            fail(f"HOME-relative file must not traverse symlinks: {source_path}")
        try:
            metadata = os.lstat(source_path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            fail(f"cannot inspect HOME-relative file {source_path}: {exc}")
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            fail(f"HOME-relative file must be a regular file: {source_path}")
        if metadata.st_uid != os.getuid() or not os.access(source_path, os.R_OK):
            fail(
                "HOME-relative file must be readable and owned by the current "
                f"user: {source_path}"
            )
        if require_private_mode and metadata.st_mode & 0o022:
            fail(f"HOME-relative file must not be writable by group or other: {source_path}")
        destination_path = os.path.join(home_dir, relative_path)
        add_dir_chain(command, os.path.dirname(destination_path))
        command.extend(["--ro-bind", source_path, destination_path])


def add_absolute_directory_binds(
    command: list[str],
    paths: tuple[str, ...],
    option: str,
    *,
    required: bool = True,
    require_user_private: bool = False,
) -> None:
    if option not in {"--bind", "--ro-bind"}:
        fail(f"unsupported absolute directory bind option: {option}")
    for path in paths:
        validate_absolute_path("absolute sandbox directory", path)
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            if required:
                fail(f"required sandbox directory is unavailable: {path}")
            continue
        except OSError as exc:
            fail(f"required sandbox directory is unavailable: {path}: {exc}")
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            fail(f"required sandbox directory must be a real directory: {path}")
        if require_user_private:
            if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                fail(
                    "required private sandbox directory must be current-user-owned "
                    f"and mode 0700: {path}"
                )
        elif metadata.st_uid not in {0, os.getuid()} or metadata.st_mode & stat.S_IWOTH:
            fail(f"required sandbox directory has unsafe ownership or mode: {path}")
        required_access = os.R_OK | os.X_OK
        if option == "--bind":
            required_access |= os.W_OK
        if not os.access(path, required_access):
            fail(f"required sandbox directory is not accessible as requested: {path}")
        add_dir_chain(command, path)
        command.extend([option, path, path])


def add_absolute_directory_bind_pairs(
    command: list[str],
    path_pairs: tuple[tuple[str, str], ...],
    option: str,
) -> None:
    if option not in {"--bind", "--ro-bind"}:
        fail(f"unsupported absolute directory bind-pair option: {option}")
    for path_pair in path_pairs:
        if (
            not isinstance(path_pair, tuple)
            or len(path_pair) != 2
            or not all(isinstance(path, str) for path in path_pair)
        ):
            fail("absolute directory bind pair must contain two path strings")
        source_path, destination_path = path_pair
        if source_path == destination_path:
            fail(f"absolute directory bind pair must use distinct paths: {source_path}")
        for label, path in (
            ("absolute sandbox bind source directory", source_path),
            ("absolute sandbox bind destination directory", destination_path),
        ):
            validate_absolute_path(label, path)
            if (
                path == "/"
                or os.path.normpath(path) != path
                or any(character in path for character in ("\n", "\r", "\0"))
                or os.path.realpath(path) != path
            ):
                fail(f"{label} must be a direct normalized path: {path}")
            try:
                metadata = os.lstat(path)
            except OSError as exc:
                fail(f"{label} is unavailable: {path}: {exc}")
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                fail(f"{label} must be a real directory: {path}")
            if metadata.st_uid not in {0, os.getuid()} or metadata.st_mode & stat.S_IWOTH:
                fail(f"{label} has unsafe ownership or mode: {path}")
            required_access = os.R_OK | os.X_OK
            if option == "--bind":
                required_access |= os.W_OK
            if not os.access(path, required_access):
                fail(f"{label} is not accessible as requested: {path}")
        command.extend([option, source_path, destination_path])


