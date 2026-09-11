"""Command-line orchestration for managed Labwc applications."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from .commands import build_argv, resolved_executable, validate_required_runtime_files
from .environment import (
    build_environment,
    ensure_discord_managed_settings,
    ensure_managed_runtime_state,
    ensure_obsidian_registry,
    load_managed_launch_policy,
    validate_acceleration_mode,
)
from .events import emit, event_context
from .profiles import APPS, WAYLAND_COMPAT_APPS
from .runtime import MANAGED_DEFAULTS_PATH, current_user_home, fail
from .sandbox import run_persistent_sandbox, run_pure_privacy
from .session import (
    redirect_bitwarden_to_session_unit,
    redirect_native_from_private_users,
    redirect_wayland_compat_to_session_unit,
)


def _argument_parser(*, wayland_compat: bool) -> argparse.ArgumentParser:
    if wayland_compat:
        program_name = "labwc-managed-wayland-compat-app"
        application_choices = WAYLAND_COMPAT_APPS
        mode_choices = ("auto", "launch", "intel", "nvidia")
    else:
        program_name = "labwc-managed-app"
        application_choices = tuple(sorted(set(APPS).difference(WAYLAND_COMPAT_APPS)))
        mode_choices = ("auto", "launch", "intel", "nvidia", "pure-privacy")

    parser = argparse.ArgumentParser(prog=program_name)
    parser.add_argument("mode", choices=mode_choices)
    parser.add_argument("application", choices=application_choices)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(
    *,
    wayland_compat: bool = False,
    argv: Sequence[str] | None = None,
) -> int:
    options = _argument_parser(wayland_compat=wayland_compat).parse_args(argv)
    entrypoint = "wayland-compat" if wayland_compat else "native"
    transport = "stderr" if options.application == "chatgpt" else "syslog"

    with event_context(
        application=options.application,
        entrypoint=entrypoint,
        requested_mode=options.mode,
        transport=transport,
    ):
        emit("launch-requested")
        if os.geteuid() == 0:
            fail(
                "managed desktop applications must run as the configured desktop "
                "user, never root"
            )

        if options.application == "bitwarden":
            emit("session-redirect", target="bitwarden")
            redirect_bitwarden_to_session_unit(options.mode, options.args)
        if wayland_compat:
            emit("session-redirect", target="wayland-compat")
            redirect_wayland_compat_to_session_unit(
                options.application,
                options.mode,
                options.args,
            )

        if not wayland_compat and options.application != "bitwarden":
            redirect_native_from_private_users(
                options.application, options.mode, options.args,
            )

        acceleration_availability, default_mode = load_managed_launch_policy(
            MANAGED_DEFAULTS_PATH
        )
        mode = default_mode if options.mode == "auto" else options.mode
        validate_acceleration_mode(mode, acceleration_availability)

        with event_context(mode=mode):
            app = APPS[options.application]
            executable = resolved_executable(options.application, mode)
            if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
                fail(
                    "application executable is missing or not executable: "
                    f"{executable}"
                )

            validate_required_runtime_files(options.application)
            if mode != "pure-privacy":
                home_dir = current_user_home()
                ensure_managed_runtime_state(options.application, home_dir)
                if options.application == "discord":
                    ensure_discord_managed_settings(home_dir)
                if options.application == "obsidian":
                    ensure_obsidian_registry(home_dir)

            if mode == "pure-privacy":
                emit("sandbox-starting", sandbox="ephemeral")
                result = run_pure_privacy(options.application, options.args)
                emit("completed", status=result)
                return result

            if wayland_compat:
                from .wayland_compat import run_wayland_compat_sandbox

                emit("sandbox-starting", sandbox="wayland-compat")
                result = run_wayland_compat_sandbox(
                    options.application,
                    mode,
                    options.args,
                )
                emit("completed", status=result)
                return result

            if app.get("persistent_sandbox", False):
                emit("sandbox-starting", sandbox="persistent")
                result = run_persistent_sandbox(
                    options.application,
                    mode,
                    options.args,
                )
                emit("completed", status=result)
                return result

            env = build_environment(options.application, mode)
            command = build_argv(options.application, mode, options.args)
            emit("executing")
            try:
                os.execvpe(command[0], command, env)
            except OSError as exc:
                fail(
                    "application execution failed: "
                    f"{command[0]}: {exc.strerror or exc}"
                )
            emit("completed", status=0)
            return 0
