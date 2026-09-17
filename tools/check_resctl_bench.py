#!/usr/bin/env python3
"""Validate every desktop profile's resctl-bench pins without sourcing shell.

This is an offline publishing gate, not a download or native-CPU acceptance test.
The trusted repository helper supplies the SAME policy used inside the target.
Every profile must have all eight pins exactly once, as literal assignments,
and all profiles must agree. Update the complete set together for a new release.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import runpy
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'd-i/forky'
FIELDS = {
    'VERSION': 'version',
    'TAG': 'tag',
    'ARCHITECTURE': 'architecture',
    'URL': 'url',
    'SHA256': 'sha256',
    'MAXIMUM_BYTES': 'max_archive',
    'MAXIMUM_EXTRACTED_BYTES': 'max_extracted',
    'MAXIMUM_MEMBERS': 'max_members',
}
INTEGER_FIELDS = frozenset({'MAXIMUM_BYTES', 'MAXIMUM_EXTRACTED_BYTES', 'MAXIMUM_MEMBERS'})
# No shell expansions, escapes, commands, concatenation or duplicate assignments.
ASSIGNMENT = re.compile(r'RESCTL_BENCH_([A-Z0-9_]+)="([^"\\$`\r\n]*)"')


def read_pins(path: Path) -> dict[str, str]:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or not 1 <= st.st_size <= 1024 * 1024:
        raise ValueError(f'{path.name}: profile must be a bounded regular file')
    pins: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if line.startswith('#') or 'RESCTL_BENCH_' not in line:
            continue
        match = ASSIGNMENT.fullmatch(line)
        if not match:
            raise ValueError(f'{path.name}:{number}: resctl-bench pins require literal '
                             'double-quoted assignments, without shell expressions')
        key, value = match.groups()
        if key not in FIELDS:
            raise ValueError(f'{path.name}:{number}: unknown RESCTL_BENCH_{key}')
        if key in pins:
            raise ValueError(f'{path.name}:{number}: duplicate RESCTL_BENCH_{key}')
        pins[key] = value
    missing = FIELDS.keys() - pins.keys()
    if missing:
        raise ValueError(f'{path.name}: missing ' + ', '.join('RESCTL_BENCH_' + k for k in sorted(missing)))
    return pins


def arguments(pins: dict[str, str]) -> argparse.Namespace:
    values: dict[str, str | int] = {}
    for key, name in FIELDS.items():
        value = pins[key]
        if key in INTEGER_FIELDS:
            if not re.fullmatch(r'[0-9]{1,10}', value):
                raise ValueError(f'RESCTL_BENCH_{key} must be a bounded decimal integer')
            values[name] = int(value)
        else:
            values[name] = value
    return argparse.Namespace(**values)


def check(seed: Path = SEED) -> int:
    profiles = sorted((seed / 'hosts/profiles').glob('*.env'))
    if not profiles:
        raise ValueError('no desktop profiles found for resctl-bench validation')
    # Load definitions only, never the helper's __main__ installation entry point.
    helper = runpy.run_path(str(seed / 'scripts/desktop/resctl-bench-install.py'),
                            run_name='resctl_release_policy')
    reference: dict[str, str] | None = None
    reference_name = ''
    for profile in profiles:
        try:
            pins = read_pins(profile)
            helper['policy'](arguments(pins))
        except (ValueError, helper['Error']) as exc:
            raise ValueError(f'resctl-bench profile validation failed ({profile.name}): {exc}') from exc
        if reference is None:
            reference, reference_name = pins, profile.name
        elif pins != reference:
            changed = ', '.join('RESCTL_BENCH_' + key for key in FIELDS if pins[key] != reference[key])
            raise ValueError(f'{profile.name}: resctl-bench pins differ from {reference_name}: '
                             f'{changed}; update all profiles together')
    return len(profiles)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        count = check()
    except (OSError, ValueError) as exc:
        print(f'resctl-bench preflight: {exc}', file=sys.stderr)
        return 1
    print(f'resctl-bench: {count} profiles have identical, valid release pins (offline)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
