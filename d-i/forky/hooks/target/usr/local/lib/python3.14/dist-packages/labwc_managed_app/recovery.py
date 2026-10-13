"""Prevent new application launches while the desktop is closing."""
from __future__ import annotations
from pathlib import Path

from .runtime import current_user_runtime_dir, fail


def assert_launch_allowed() -> None:
    marker = Path(current_user_runtime_dir()) / "labwc-session-closing"
    if marker.exists() or marker.is_symlink():
        fail("the desktop is closing; finish or cancel the power request before launching applications")
