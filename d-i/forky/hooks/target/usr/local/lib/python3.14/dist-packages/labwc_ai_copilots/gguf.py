"""Bounded GGUF metadata inspection for the managed Llama launcher."""

from __future__ import annotations

import grp
import os
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final


class GGUFError(ValueError):
    """Raised when a GGUF file violates the bounded reader contract."""


_SCALAR_FORMATS: Final[dict[int, str]] = {
    0: "<B",
    1: "<b",
    2: "<H",
    3: "<h",
    4: "<I",
    5: "<i",
    6: "<f",
    7: "<B",
    10: "<Q",
    11: "<q",
    12: "<d",
}
_SCALAR_SIZES: Final[dict[int, int]] = {
    value_type: struct.calcsize(fmt) for value_type, fmt in _SCALAR_FORMATS.items()
}
_STRING_TYPE: Final[int] = 8
_ARRAY_TYPE: Final[int] = 9
_LLAMA_MODEL_ROOT: Final[Path] = Path("/pool/cache/llama/models")

_TENSOR_TYPES: Final[dict[int, str]] = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    6: "Q5_0",
    7: "Q5_1",
    8: "Q8_0",
    9: "Q8_1",
    10: "Q2_K",
    11: "Q3_K",
    12: "Q4_K",
    13: "Q5_K",
    14: "Q6_K",
    15: "Q8_K",
    16: "IQ2_XXS",
    17: "IQ2_XS",
    18: "IQ3_XXS",
    19: "IQ1_S",
    20: "IQ4_NL",
    21: "IQ3_S",
    22: "IQ2_S",
    23: "IQ4_XS",
    24: "I8",
    25: "I16",
    26: "I32",
    27: "I64",
    28: "F64",
    29: "IQ1_M",
    30: "BF16",
    31: "Q4_0_4_4",
    32: "Q4_0_4_8",
    33: "Q4_0_8_8",
    34: "TQ1_0",
    35: "TQ2_0",
    36: "IQ4_NL_4_4",
    37: "IQ4_NL_4_8",
    38: "IQ4_NL_8_8",
}

_INTERESTING_KEYS: Final[frozenset[str]] = frozenset(
    {
        "general.architecture",
        "general.name",
        "general.author",
        "general.description",
        "general.license",
        "general.license.name",
        "general.license.link",
        "general.file_type",
    }
)


@dataclass(frozen=True)
class GGUFInfo:
    path: str
    size_bytes: int
    version: int
    tensor_count: int
    metadata_count: int
    parameter_count: int
    tensor_types: dict[str, int]
    metadata: dict[str, object]

    @property
    def architecture(self) -> str | None:
        value = self.metadata.get("general.architecture")
        return value if isinstance(value, str) and value else None

    @property
    def context_length(self) -> int | None:
        architecture = self.architecture
        if architecture:
            value = self.metadata.get(f"{architecture}.context_length")
            if isinstance(value, int) and value > 0:
                return value
        for key, value in self.metadata.items():
            if key.endswith(".context_length") and isinstance(value, int) and value > 0:
                return value
        return None

    @property
    def license_text(self) -> str | None:
        values: list[str] = []
        for key in ("general.license", "general.license.name", "general.license.link"):
            value = self.metadata.get(key)
            if isinstance(value, str) and value and value not in values:
                values.append(value)
        return " | ".join(values) if values else None


class _Reader:
    def __init__(
        self,
        handle: BinaryIO,
        file_size: int,
        *,
        metadata_byte_limit: int = 536_870_912,
    ) -> None:
        self._handle = handle
        self._file_size = file_size
        self._metadata_byte_limit = metadata_byte_limit
        self._metadata_start = 0

    def mark_metadata_start(self) -> None:
        self._metadata_start = self.tell()

    def tell(self) -> int:
        return self._handle.tell()

    def _check_position(self) -> None:
        position = self.tell()
        if position < 0 or position > self._file_size:
            raise GGUFError("GGUF reader moved outside the file")
        if self._metadata_start and position - self._metadata_start > self._metadata_byte_limit:
            raise GGUFError("GGUF metadata exceeds the managed byte limit")

    def read_exact(self, size: int) -> bytes:
        if size < 0 or size > 536_870_912:
            raise GGUFError("GGUF read size exceeds the managed bound")
        data = self._handle.read(size)
        if len(data) != size:
            raise GGUFError("GGUF file ended unexpectedly")
        self._check_position()
        return data

    def unpack(self, fmt: str) -> int | float:
        return struct.unpack(fmt, self.read_exact(struct.calcsize(fmt)))[0]

    def skip(self, size: int) -> None:
        if size < 0:
            raise GGUFError("GGUF skip size is negative")
        target = self.tell() + size
        if target > self._file_size:
            raise GGUFError("GGUF value extends beyond the file")
        self._handle.seek(size, os.SEEK_CUR)
        self._check_position()

    def read_string(self, *, decode: bool, maximum_decoded: int = 1_048_576) -> str | None:
        length = int(self.unpack("<Q"))
        if length > 268_435_456:
            raise GGUFError("GGUF string exceeds the managed bound")
        if not decode:
            self.skip(length)
            return None
        if length > maximum_decoded:
            raise GGUFError("interesting GGUF string exceeds the decode bound")
        raw = self.read_exact(length)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GGUFError("GGUF string is not valid UTF-8") from exc

    def read_value(self, value_type: int, *, retain: bool) -> object | None:
        if value_type in _SCALAR_FORMATS:
            value = self.unpack(_SCALAR_FORMATS[value_type])
            return value if retain else None
        if value_type == _STRING_TYPE:
            return self.read_string(decode=retain)
        if value_type == _ARRAY_TYPE:
            element_type = int(self.unpack("<I"))
            count = int(self.unpack("<Q"))
            if count > 10_000_000:
                raise GGUFError("GGUF array exceeds the managed element bound")
            if retain:
                raise GGUFError("retaining GGUF arrays is intentionally unsupported")
            self.skip_array(element_type, count)
            return None
        raise GGUFError(f"unsupported GGUF metadata value type: {value_type}")

    def skip_array(self, element_type: int, count: int) -> None:
        if element_type in _SCALAR_SIZES:
            self.skip(_SCALAR_SIZES[element_type] * count)
            return
        if element_type == _STRING_TYPE:
            if count > 2_000_000:
                raise GGUFError("GGUF string array exceeds the managed element bound")
            for _ in range(count):
                self.read_string(decode=False)
            return
        raise GGUFError("nested or unsupported GGUF array type")


def _validate_model_path(path_text: str) -> Path:
    if not path_text or "\x00" in path_text or "\n" in path_text or "\r" in path_text:
        raise GGUFError("model path is invalid")
    path = Path(path_text)
    if not path.is_absolute() or ".." in path.parts:
        raise GGUFError("model path must be a safe absolute path")
    if path.is_symlink() or not path.is_file():
        raise GGUFError("model path must be a non-symbolic regular file")
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise GGUFError("model path must already be canonical")

    try:
        resolved.relative_to(_LLAMA_MODEL_ROOT)
    except ValueError as exc:
        raise GGUFError("model path is outside the managed Llama model directory") from exc

    stat_result = resolved.stat()
    try:
        devops_gid = grp.getgrnam("devops").gr_gid
    except KeyError as exc:
        raise GGUFError("managed devops group is unavailable") from exc
    if stat_result.st_uid != 0 or stat_result.st_gid != devops_gid:
        raise GGUFError("model ownership is unsafe")
    if stat_result.st_mode & 0o777 != 0o640:
        raise GGUFError("model ownership or mode is unsafe")
    if stat_result.st_size < 24 or stat_result.st_size > 107_374_182_400:
        raise GGUFError("model size is outside the supported bounds")
    return resolved


def _inspect_gguf_file(path: Path) -> GGUFInfo:
    file_size = path.stat().st_size
    with path.open("rb", buffering=0) as handle:
        reader = _Reader(handle, file_size)
        if reader.read_exact(4) != b"GGUF":
            raise GGUFError("model does not contain GGUF magic")
        version = int(reader.unpack("<I"))
        if version not in (2, 3):
            raise GGUFError(f"unsupported GGUF version: {version}")
        tensor_count = int(reader.unpack("<Q"))
        metadata_count = int(reader.unpack("<Q"))
        if tensor_count > 1_000_000:
            raise GGUFError("GGUF tensor count exceeds the managed bound")
        if metadata_count > 100_000:
            raise GGUFError("GGUF metadata count exceeds the managed bound")

        reader.mark_metadata_start()
        metadata: dict[str, object] = {}
        for _ in range(metadata_count):
            key = reader.read_string(decode=True, maximum_decoded=4096)
            assert key is not None
            if not key or len(key) > 4096:
                raise GGUFError("GGUF metadata key is invalid")
            value_type = int(reader.unpack("<I"))
            retain = key in _INTERESTING_KEYS or key.endswith(".context_length")
            value = reader.read_value(value_type, retain=retain)
            if retain and value is not None:
                metadata[key] = value

        parameter_count = 0
        tensor_types: Counter[str] = Counter()
        for _ in range(tensor_count):
            reader.read_string(decode=False)
            dimension_count = int(reader.unpack("<I"))
            if dimension_count < 1 or dimension_count > 8:
                raise GGUFError("GGUF tensor dimension count is invalid")
            parameters = 1
            for _dimension in range(dimension_count):
                dimension = int(reader.unpack("<Q"))
                if dimension < 1 or dimension > 10_000_000_000:
                    raise GGUFError("GGUF tensor dimension is invalid")
                parameters *= dimension
                if parameters > 10_000_000_000_000:
                    raise GGUFError("GGUF tensor parameter count exceeds the managed bound")
            parameter_count += parameters
            if parameter_count > 100_000_000_000_000:
                raise GGUFError("GGUF model parameter count exceeds the managed bound")
            tensor_type = int(reader.unpack("<I"))
            reader.unpack("<Q")  # data offset
            tensor_types[_TENSOR_TYPES.get(tensor_type, f"TYPE_{tensor_type}")] += 1

    return GGUFInfo(
        path=str(path),
        size_bytes=file_size,
        version=version,
        tensor_count=tensor_count,
        metadata_count=metadata_count,
        parameter_count=parameter_count,
        tensor_types=dict(tensor_types),
        metadata=metadata,
    )


def inspect_gguf(path_text: str) -> GGUFInfo:
    """Inspect one root:devops GGUF below the managed Llama model directory."""

    return _inspect_gguf_file(_validate_model_path(path_text))
