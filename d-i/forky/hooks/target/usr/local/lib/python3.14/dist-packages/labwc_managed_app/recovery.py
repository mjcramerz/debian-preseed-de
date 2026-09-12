"""Private launcher descriptors; never checkpoint or replay a shell session."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path

from .runtime import current_user_runtime_dir, fail


def assert_launch_allowed() -> None:
    marker = Path(current_user_runtime_dir()) / "labwc-session-closing"
    if marker.exists() or marker.is_symlink():
        fail("the desktop is closing; finish or cancel the power request before launching applications")


def restart_token(argv: list[str]) -> str:
    descriptor = json.dumps({"argv": argv, "cwd": os.getcwd()},
                            separators=(",", ":")).encode()
    if len(descriptor) > 32768:
        fail("application restart descriptor exceeds the size limit")
    return base64.urlsafe_b64encode(descriptor).decode()
