"""Bounded, strict, length-prefixed JSON; no semantic/taskbar policy."""
from __future__ import annotations
import json
import struct
from typing import Any

MAX_FRAME = 262144
MAX_QUEUE = 8 * 1024 * 1024


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        key.encode('utf-8', 'strict')
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError('non-JSON numeric constant')


def decode(payload: bytes) -> dict[str, Any]:
    if not 0 < len(payload) <= MAX_FRAME:
        raise ValueError('frame length')
    result = json.loads(payload.decode('utf-8', 'strict'), object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_constant)
    if not isinstance(result, dict):
        raise ValueError('JSON root')
    todo = [(result, 0)]
    while todo:
        value, depth = todo.pop()
        if depth > 20:
            raise ValueError('JSON nesting')
        if isinstance(value, dict):
            todo.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            todo.extend((v, depth + 1) for v in value)
        elif isinstance(value, str):
            value.encode('utf-8', 'strict')  # Reject lone surrogates.
    return result


def encode(value: dict[str, Any]) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if not 0 < len(payload) <= MAX_FRAME:
        raise ValueError('outbound frame length')
    return struct.pack('!I', len(payload)) + payload


def take(buffer: bytearray, budget: int = 64) -> list[dict[str, Any]]:
    frames = []
    while len(buffer) >= 4 and len(frames) < budget:
        length = struct.unpack_from('!I', buffer)[0]
        if not 0 < length <= MAX_FRAME:
            raise ValueError('frame length')
        if len(buffer) < length + 4:
            break
        frames.append(decode(bytes(buffer[4:4 + length])))
        del buffer[:4 + length]
    return frames


def exact(obj: dict[str, Any], *keys: str) -> None:
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise ValueError('unexpected fields')


def integer(value: Any, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('integer range')
    return value
