"""CLI for bounded GGUF metadata inspection."""

from __future__ import annotations

import argparse
import json
import sys

from .gguf import GGUFError, GGUFInfo, inspect_gguf


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024**2:
        return f"{value / 1024:.2f} KiB"
    if value < 1024**3:
        return f"{value / 1024**2:.2f} MiB"
    return f"{value / 1024**3:.2f} GiB"


def _format_parameters(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.3f}B ({value})"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.3f}M ({value})"
    if value >= 1_000:
        return f"{value / 1_000:.3f}K ({value})"
    return str(value)


def _quantization(info: GGUFInfo) -> str:
    if not info.tensor_types:
        return "unknown"
    ordered = sorted(info.tensor_types.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{name} ({count} tensors)" for name, count in ordered)


def _details(info: GGUFInfo) -> str:
    name = info.metadata.get("general.name")
    author = info.metadata.get("general.author")
    description = info.metadata.get("general.description")
    file_type = info.metadata.get("general.file_type")
    lines = [
        f"Path: {info.path}",
        f"Size: {_format_bytes(info.size_bytes)} ({info.size_bytes} bytes)",
        f"GGUF version: {info.version}",
        f"Metadata entries: {info.metadata_count}",
        f"Tensors: {info.tensor_count}",
        f"Parameters: {_format_parameters(info.parameter_count)}",
        f"Architecture: {info.architecture or 'not embedded'}",
        f"Context length: {info.context_length or 'not embedded'}",
        f"Quantization: {_quantization(info)}",
        f"GGUF file type: {file_type if file_type is not None else 'not embedded'}",
        f"License: {info.license_text or 'not embedded'}",
    ]
    if isinstance(name, str) and name:
        lines.append(f"Name: {name}")
    if isinstance(author, str) and author:
        lines.append(f"Author: {author}")
    if isinstance(description, str) and description:
        lines.append(f"Description: {description}")
    return "\n".join(lines)


def _render(info: GGUFInfo, field: str) -> str:
    if field == "details":
        return _details(info)
    if field == "license":
        return info.license_text or "not embedded"
    if field == "architecture":
        return info.architecture or "not embedded"
    if field == "parameter-count":
        return _format_parameters(info.parameter_count)
    if field == "quantization":
        return _quantization(info)
    if field == "size":
        return f"{_format_bytes(info.size_bytes)} ({info.size_bytes} bytes)"
    if field == "context-length":
        return str(info.context_length) if info.context_length else "not embedded"
    if field == "location":
        return info.path
    if field == "json":
        return json.dumps(
            {
                "path": info.path,
                "size_bytes": info.size_bytes,
                "version": info.version,
                "tensor_count": info.tensor_count,
                "metadata_count": info.metadata_count,
                "parameter_count": info.parameter_count,
                "tensor_types": info.tensor_types,
                "architecture": info.architecture,
                "context_length": info.context_length,
                "license": info.license_text,
                "metadata": info.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    raise GGUFError(f"unsupported output field: {field}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="labwc-ai-model-info",
        description="Inspect bounded metadata from an approved GGUF model.",
    )
    parser.add_argument(
        "--field",
        choices=(
            "details",
            "license",
            "architecture",
            "parameter-count",
            "quantization",
            "size",
            "context-length",
            "location",
            "json",
        ),
        default="details",
    )
    parser.add_argument("model")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        info = inspect_gguf(arguments.model)
        print(_render(info, arguments.field))
    except (GGUFError, OSError) as exc:
        print(f"labwc-ai-model-info: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

