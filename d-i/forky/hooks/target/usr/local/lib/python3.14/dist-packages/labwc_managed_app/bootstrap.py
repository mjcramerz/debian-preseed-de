"""Trusted dispatch after the entrypoint has validated the bootstrap files."""

from __future__ import annotations

import sys
import syslog
from typing import NoReturn

from .integrity import IntegrityError, PackageScope, validate_package


_IDENTIFIER = "labwc-managed-app"


def _fatal(scope: PackageScope, message: str) -> NoReturn:
    rendered = f"managed application bootstrap failed: scope={scope.value} detail={message}"
    # ChatGPT stderr is captured by its private rsyslog transport, while the
    # inner compatibility runtime is already supervised by a journal-backed
    # transient unit. Avoid probing the deliberately denied generic socket.
    use_syslog = not (
        scope is PackageScope.COMPAT_RUNTIME
        or (
            scope is PackageScope.NATIVE
            and len(sys.argv) >= 3
            and sys.argv[2] == "chatgpt"
        )
    )
    if use_syslog:
        try:
            syslog.openlog(
                _IDENTIFIER,
                syslog.LOG_PID | syslog.LOG_NDELAY,
                syslog.LOG_USER,
            )
            syslog.syslog(syslog.LOG_ERR, rendered)
        except (OSError, ValueError):
            pass
        finally:
            try:
                syslog.closelog()
            except (OSError, ValueError):
                pass
    print(f"fatal: {rendered}", file=sys.stderr)
    raise SystemExit(1)


def run(scope: PackageScope | str) -> int:
    try:
        selected_scope = PackageScope(scope)
    except ValueError:
        print(f"fatal: unknown managed application entrypoint scope: {scope}", file=sys.stderr)
        return 1

    try:
        validate_package(selected_scope)
        if selected_scope in {PackageScope.ELECTRON, PackageScope.WAYLAND}:
            from .generic import main

            return main(selected_scope.value)
        if selected_scope is PackageScope.NATIVE:
            from .cli import main

            return main()
        if selected_scope is PackageScope.WAYLAND_COMPAT:
            from .cli import main

            return main(wayland_compat=True)
        from .wayland_compat_runtime import main

        return main()
    except IntegrityError as exc:
        _fatal(selected_scope, str(exc))
    except ImportError as exc:
        _fatal(selected_scope, f"validated module import failed: {exc}")
