"""Shared, bounded parsing of the administrator's application network policy."""

from __future__ import annotations

import json
import os
from pathlib import PurePosixPath
import re
import stat

CONFIG_PATH = "/etc/app-veth.json"
MAX_CONFIG_BYTES = 65536
MAX_APPS = 128
APP_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate application network configuration key")
        result[key] = value
    return result


def parse_configuration(raw: bytes) -> dict:
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("oversized managed network configuration")
    try:
        conf = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("invalid managed network JSON") from exc
    if (not isinstance(conf, dict) or set(conf) != {"version", "desktop_user", "apps"}
            or type(conf["version"]) is not int or conf["version"] != 1
            or not isinstance(conf["desktop_user"], str)
            or re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", conf["desktop_user"]) is None
            or conf["desktop_user"] == "root"
            or not isinstance(conf["apps"], dict) or len(conf["apps"]) > MAX_APPS):
        raise ValueError("invalid managed network configuration")
    apps = {}
    paths = set()
    for name, policy in conf["apps"].items():
        if (APP_NAME.fullmatch(name) is None or not isinstance(policy, dict)
                or not set(policy) <= {"network", "block_lan", "peer_port", "pin_route", "executables"}
                or "network" not in policy):
            raise ValueError("invalid application network policy")
        enabled = policy["network"]
        block_lan = policy.get("block_lan", False)
        port = policy.get("peer_port")
        pinned = policy.get("pin_route", port is not None)
        executables = policy.get("executables", [])
        if (type(enabled) is not bool or type(block_lan) is not bool
                or type(pinned) is not bool
                or (port is not None and (type(port) is not int or not 1024 <= port <= 65535))
                or (not enabled and port is not None)
                or (port is not None and not pinned)
                or not isinstance(executables, list) or len(executables) > 16):
            raise ValueError("invalid application network settings")
        for executable in executables:
            if (not isinstance(executable, str) or len(executable) > 4096
                    or not executable.startswith(("/usr/bin/", "/usr/local/bin/", "/usr/lib/", "/opt/"))
                    or any(ord(character) < 32 or ord(character) == 127 for character in executable)
                    or str(PurePosixPath(executable)) != executable
                    or ".." in PurePosixPath(executable).parts or executable in paths):
                raise ValueError("invalid or duplicate application executable")
            paths.add(executable)
        apps[name] = {"network": enabled, "block_lan": block_lan, "peer_port": port,
                      "pin_route": pinned, "executables": tuple(executables)}
    return {"version": 1, "desktop_user": conf["desktop_user"], "apps": apps}


def read_configuration(path: str = CONFIG_PATH, *, owner_uid: int = 0) -> dict:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != owner_uid
                or meta.st_mode & 0o022 or meta.st_nlink != 1):
            raise ValueError("unsafe managed network configuration")
        raw = stream.read(MAX_CONFIG_BYTES + 1)
    return parse_configuration(raw)
