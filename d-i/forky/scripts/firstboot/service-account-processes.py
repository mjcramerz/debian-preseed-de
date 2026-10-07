#!/usr/bin/python3 -I
"""List real-UID process names without ps reading unrelated ptrace-gated fields."""
from __future__ import annotations

from pathlib import Path
import sys


def process_names(uid: int, proc: Path = Path('/proc')) -> list[str]:
    if not 0 < uid < 4294967295:
        raise ValueError('expected a non-root service-account UID')
    names = []
    for entry in proc.iterdir():
        if not entry.name.isascii() or not entry.name.isdecimal():
            continue
        try:
            # /proc/PID/status exposes Name and real UID without reading stat,
            # exe, fd or memory. Ignore only processes that have exited.
            with (entry / 'status').open('r', encoding='utf-8', errors='surrogateescape') as stream:
                status = stream.read(65537)
        except (FileNotFoundError, ProcessLookupError):
            continue
        fields = {}
        for line in status.splitlines():
            key, _, value = line.partition(':')
            if key in ('Name', 'Uid'):
                if key in fields:
                    raise ValueError('duplicate process identity field')
                fields[key] = value.strip()
        uids = fields.get('Uid', '').split()
        if (len(status) > 65536 or not fields.get('Name') or len(uids) != 4
                or any(not value.isascii() or not value.isdecimal() for value in uids)):
            raise ValueError('incomplete process identity')
        if int(uids[0]) == uid:
            names.append(fields['Name'])
    return names


def main(arguments: list[str]) -> int:
    if len(arguments) != 1 or not arguments[0].isascii() or not arguments[0].isdecimal():
        raise ValueError('usage: service-account-processes.py UID')
    for name in process_names(int(arguments[0])):
        print(name)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError) as exc:
        print(f'service-account-processes: {exc}', file=sys.stderr)
        raise SystemExit(1)
