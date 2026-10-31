#!/usr/bin/python3
"""Validate installer-owned Waybar geometry and emit a render map.

The installer runs this helper inside the installed target. It accepts a small
TSV snapshot rather than sourcing shell configuration, so the values validated
here are exactly the values consumed by the template renderer.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import sys


MAX_SCHEMA_BYTES = 64 * 1024
MAX_VALUES_BYTES = 1 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_SCHEMA_ENTRIES = 256
KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
INTEGER_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
PIXEL_RE = re.compile(r"(?:0|[1-9][0-9]*)px\Z")
VALUE_KEY_RE = re.compile(r"LABWC_WAYBAR_(INTERNAL|EXTERNAL)_([A-Z][A-Z0-9_]*)\Z")


@dataclass(frozen=True)
class GeometrySpec:
    key: str
    kind: str
    minimum: int
    maximum: int


class GeometryError(ValueError):
    """A source or profile geometry contract is invalid."""


def _read_bounded(path: Path, limit: int) -> str:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise GeometryError(f"geometry input is not a regular file: {path}")
        if info.st_size > limit:
            raise GeometryError(f"geometry input exceeds its read budget: {path}")
        with path.open("r", encoding="utf-8", newline="") as stream:
            content = stream.read(limit + 1)
    except GeometryError:
        raise
    except (OSError, UnicodeError) as error:
        raise GeometryError(f"cannot read geometry input: {path}") from error
    if len(content.encode("utf-8")) > limit:
        raise GeometryError(f"geometry input exceeds its read budget: {path}")
    return content


def read_schema(path: Path) -> tuple[GeometrySpec, ...]:
    specs: list[GeometrySpec] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(_read_bounded(path, MAX_SCHEMA_BYTES).splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            raise GeometryError(f"invalid Waybar geometry schema line {line_number}")
        key, kind, minimum_text, maximum_text = fields
        if not KEY_RE.fullmatch(key) or key in seen:
            raise GeometryError(f"invalid or duplicate Waybar geometry key: {key}")
        if kind not in {"uint", "px-tuple"}:
            raise GeometryError(f"unknown Waybar geometry type: {kind}")
        try:
            minimum = int(minimum_text, 10)
            maximum = int(maximum_text, 10)
        except ValueError as error:
            raise GeometryError(f"invalid Waybar geometry range: {key}") from error
        if minimum < 0 or maximum < minimum:
            raise GeometryError(f"invalid Waybar geometry range: {key}")
        seen.add(key)
        specs.append(GeometrySpec(key, kind, minimum, maximum))
        if len(specs) > MAX_SCHEMA_ENTRIES:
            raise GeometryError("Waybar geometry schema has too many entries")
    if not specs:
        raise GeometryError("Waybar geometry schema is empty")
    return tuple(specs)


def read_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(
        _read_bounded(path, MAX_VALUES_BYTES).splitlines(), 1
    ):
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) != 2:
            raise GeometryError(f"invalid Waybar geometry values line {line_number}")
        key, value = fields
        if not VALUE_KEY_RE.fullmatch(key) or not value or "\x00" in value:
            raise GeometryError(f"invalid Waybar geometry value key: {key}")
        if key in values:
            raise GeometryError(f"duplicate Waybar geometry value: {key}")
        values[key] = value
    if not values:
        raise GeometryError(f"Waybar geometry values are empty: {path}")
    return values


def _validate_value(name: str, value: str, spec: GeometrySpec) -> None:
    if spec.kind == "uint":
        if not INTEGER_RE.fullmatch(value):
            raise GeometryError(f"Waybar geometry must use canonical decimal integers: {name}")
        number = int(value, 10)
        if not spec.minimum <= number <= spec.maximum:
            raise GeometryError(
                f"Waybar geometry outside range for {name}: {number} "
                f"(expected {spec.minimum}..{spec.maximum})"
            )
        return
    parts = value.split()
    if len(parts) != spec.minimum or any(not PIXEL_RE.fullmatch(part) for part in parts):
        raise GeometryError(f"invalid Waybar geometry: {name}")
    if any(int(part[:-2], 10) > spec.maximum for part in parts):
        raise GeometryError(f"Waybar geometry exceeds its numeric budget: {name}")


def validate(schema_path: Path, values_path: Path) -> tuple[tuple[str, str], ...]:
    specs = read_schema(schema_path)
    values = read_values(values_path)
    expected = {
        f"LABWC_WAYBAR_{output_class}_{spec.key}"
        for output_class in ("INTERNAL", "EXTERNAL")
        for spec in specs
    }
    if set(values) != expected:
        missing = sorted(expected - set(values))
        extra = sorted(set(values) - expected)
        detail = []
        if missing:
            detail.append(f"missing={','.join(missing[:4])}")
        if extra:
            detail.append(f"unexpected={','.join(extra[:4])}")
        raise GeometryError("Waybar geometry value set does not match schema: " + " ".join(detail))

    for output_class in ("INTERNAL", "EXTERNAL"):
        for spec in specs:
            name = f"LABWC_WAYBAR_{output_class}_{spec.key}"
            _validate_value(name, values[name], spec)

    result: list[tuple[str, str]] = []
    for output_class in ("INTERNAL", "EXTERNAL"):
        for spec in specs:
            name = f"LABWC_WAYBAR_{output_class}_{spec.key}"
            result.append((name, values[name]))

    for spec in specs:
        if spec.key.startswith("MENU_BUTTON_"):
            continue
        if not (
            spec.key.startswith("MENU_")
            or spec.key.startswith("TOOLTIP_")
            or spec.key.startswith("POPUP_")
        ):
            continue
        internal = values[f"LABWC_WAYBAR_INTERNAL_{spec.key}"]
        external = values[f"LABWC_WAYBAR_EXTERNAL_{spec.key}"]
        if internal != external:
            raise GeometryError(
                "native Waybar GTK popup geometry must match "
                f"INTERNAL/EXTERNAL: {spec.key}"
            )
        result.append((f"LABWC_WAYBAR_SHARED_{spec.key}", internal))
    return tuple(result)


def write_map(path: Path, rows: tuple[tuple[str, str], ...]) -> None:
    payload = "".join(f"{key}\t{value}\n" for key, value in rows).encode("utf-8")
    if len(payload) > MAX_OUTPUT_BYTES:
        raise GeometryError("Waybar geometry render map exceeds its write budget")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    except FileExistsError as error:
        raise GeometryError(f"Waybar geometry render map already exists: {path}") from error
    except OSError as error:
        raise GeometryError(f"cannot write Waybar geometry render map: {path}") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--values", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        write_map(args.output, validate(args.schema, args.values))
    except GeometryError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
