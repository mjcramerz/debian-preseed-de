"""Bounded structured lifecycle events for managed desktop applications."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import sys
import syslog


IDENTIFIER = "labwc-managed-app"
MAX_FIELD_BYTES = 240
MAX_MESSAGE_BYTES = 1800
_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
_EVENT_CONTEXT: ContextVar[Mapping[str, str]] = ContextVar(
    "labwc_managed_app_event_context",
    default={},
)


def normalize_value(value: object) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\x00", "?")
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^A-Za-z0-9._:+@/&()=-]", "?", text)
    encoded = text.encode("utf-8", "replace")[:MAX_FIELD_BYTES]
    return encoded.decode("utf-8", "ignore") or "unset"


def _normalized_fields(fields: Mapping[str, object]) -> dict[str, str]:
    return {
        key: normalize_value(value)
        for key, value in fields.items()
        if _FIELD_NAME.fullmatch(key) is not None
    }


@contextmanager
def event_context(**fields: object) -> Iterator[None]:
    context = dict(_EVENT_CONTEXT.get())
    context.update(_normalized_fields(fields))
    token = _EVENT_CONTEXT.set(context)
    try:
        yield
    finally:
        _EVENT_CONTEXT.reset(token)


def current_context() -> dict[str, str]:
    return dict(_EVENT_CONTEXT.get())


def render_event(event: str, **fields: object) -> str:
    values = current_context()
    values.update(_normalized_fields(fields))
    values.pop("transport", None)
    parts = [f"event={normalize_value(event)}", f"uid={os.getuid()}"]
    parts.extend(f"{key}={values[key]}" for key in sorted(values))
    message = " ".join(parts)
    encoded = message.encode("utf-8", "replace")[:MAX_MESSAGE_BYTES]
    return encoded.decode("utf-8", "ignore")


def emit(event: str, *, level: str = "info", **fields: object) -> bool:
    priorities = {
        "debug": syslog.LOG_DEBUG,
        "info": syslog.LOG_INFO,
        "warning": syslog.LOG_WARNING,
        "error": syslog.LOG_ERR,
    }
    priority = priorities.get(level, syslog.LOG_INFO)
    message = render_event(event, **fields)
    context = current_context()
    stderr_transport = (
        context.get("transport") == "stderr"
        or context.get("application") == "chatgpt"
        or context.get("entrypoint") == "compat-runtime"
    )
    if stderr_transport:
        print(f"{IDENTIFIER}: {message}", file=sys.stderr)
        return True
    try:
        syslog.openlog(
            IDENTIFIER,
            syslog.LOG_PID | syslog.LOG_NDELAY,
            syslog.LOG_USER,
        )
        syslog.syslog(priority, message)
        return True
    except (OSError, ValueError):
        print(f"{IDENTIFIER}: {message}", file=sys.stderr)
        return False
    finally:
        try:
            syslog.closelog()
        except (OSError, ValueError):
            pass
