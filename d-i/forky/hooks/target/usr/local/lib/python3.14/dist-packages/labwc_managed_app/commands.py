"""Executable and argument construction for managed applications."""

from __future__ import annotations

import os

from .profiles import APPS
from .runtime import fail, validate_absolute_path

def resolved_executable(app_name: str, mode: str) -> str:
    app = APPS[app_name]
    if mode == "pure-privacy":
        executable = app.get("privacy_exec", app["exec"])
        candidates = app.get("privacy_exec_candidates", app.get("exec_candidates", ()))
    else:
        executable = app["exec"]
        candidates = app.get("exec_candidates", ())
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return executable


def managed_library_path(app_name: str) -> str:
    app = APPS[app_name]
    library_dirs = app.get("library_dirs", ())
    for library_dir in library_dirs:
        validate_absolute_path(f"{app_name} library directory", library_dir)
        if "\0" in library_dir or os.pathsep in library_dir:
            fail(f"{app_name} library directory contains an invalid separator: {library_dir}")
    return os.pathsep.join(library_dirs)


def validate_required_runtime_files(app_name: str) -> None:
    for runtime_file in APPS[app_name].get("required_runtime_files", ()):
        validate_absolute_path(f"{app_name} runtime file", runtime_file)
        if not os.path.isfile(runtime_file) or not os.access(runtime_file, os.R_OK):
            fail(f"{app_name} runtime file is missing or unreadable: {runtime_file}")



def build_argv(app_name: str, mode: str, extra_args: list[str]) -> list[str]:
    app = APPS[app_name]
    extra_args = normalize_managed_arguments(app_name, extra_args)
    validate_managed_arguments(mode, extra_args)
    argv = [resolved_executable(app_name, mode)]
    if mode == "intel":
        argv.extend(app.get("intel_args", app["args"]))
    elif mode == "nvidia":
        argv.extend(app.get("nvidia_args", app["args"]))
    else:
        argv.extend(app["args"])
    argv.extend(extra_args)
    return argv


def normalize_managed_arguments(app_name: str, extra_args: list[str]) -> list[str]:
    normalized_args = []
    for argument in extra_args:
        if app_name == "zoom" and argument == "--url=":
            continue
        normalized_args.append(argument)
    return normalized_args


def validate_managed_arguments(mode: str, extra_args: list[str]) -> None:
    hardware_tokens = (
        "angle",
        "gpu",
        "vaapi",
        "vulkan",
        "zero-copy",
    )
    sandbox_weakening_arguments = {
        "--disable-gpu-sandbox",
        "--disable-namespace-sandbox",
        "--disable-sandbox",
        "--disable-seccomp-filter-sandbox",
        "--disable-setuid-sandbox",
        "--no-sandbox",
        "--single-process",
    }
    for argument in extra_args:
        normalized = argument.strip().lower()
        if normalized in sandbox_weakening_arguments or normalized.startswith("--no-sandbox="):
            fail(f"managed launchers forbid sandbox-disabling arguments: {argument}")
        if normalized.startswith("--ozone-platform=") and normalized != "--ozone-platform=wayland":
            fail(f"refusing non-Wayland Ozone platform override: {argument}")
        if (
            normalized.startswith("--ozone-platform-hint=")
            and normalized != "--ozone-platform-hint=wayland"
        ):
            fail(f"refusing non-Wayland Ozone platform hint: {argument}")
        if normalized.startswith("--disable-features=") and "useozoneplatform" in normalized:
            fail(f"refusing argument that disables the managed Wayland platform: {argument}")
        if "vulkan" in normalized:
            fail(f"managed Wayland launchers forbid Vulkan arguments: {argument}")
        if "graphite" in normalized:
            fail(f"managed Wayland launchers forbid Skia Graphite arguments: {argument}")
        if mode == "launch" and normalized.startswith("--") and any(
            token in normalized for token in hardware_tokens
        ):
            fail(f"normal launch accepts Wayland flags only, not GPU overrides: {argument}")
        if mode in {"intel", "nvidia"}:
            if normalized.startswith("--use-angle=") and normalized != "--use-angle=gl":
                fail(f"refusing ANGLE override outside the managed OpenGL path: {argument}")
            if normalized.startswith("--use-gl=") and normalized != "--use-gl=angle":
                fail(f"refusing GL override outside the managed ANGLE path: {argument}")
            if normalized in {
                "--disable-gpu",
                "--disable-gpu-compositing",
                "--disable-gpu-rasterization",
            }:
                fail(f"refusing argument that disables managed hardware acceleration: {argument}")
        if mode == "pure-privacy":
            if normalized.startswith("--use-angle=") and normalized != "--use-angle=gl":
                fail(f"refusing ANGLE override outside the privacy OpenGL path: {argument}")
            if normalized.startswith("--use-gl=") and normalized != "--use-gl=angle":
                fail(f"refusing GL override outside the privacy ANGLE path: {argument}")
