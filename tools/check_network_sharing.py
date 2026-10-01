#!/usr/bin/env python3
"""Validate every NFS profile before publication, without executing profile shell.

Only double-quoted data and ${PREVIOUS_VARIABLE} expansion are permitted for
these settings. The target configurator is the single scalar policy authority.
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
ASSIGNMENT = re.compile(r'([A-Z][A-Z0-9_]*)="([^"\\`\x00-\x1f\x7f]*)"')
EXTRA = {'NETWORK_SHARING_ROOT_PATH', 'NFT_PROFILE', 'MANAGED_NETWORK_ETHERNET_IFACE',
         'MANAGED_NETWORK_WIFI_IFACE', 'ACCOUNT_USERNAME', 'ACCOUNT_HOME'}


def read_values(path: Path, initial: dict[str, str] | None = None) -> dict[str, str]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= 1024 * 1024:
        raise ValueError(f'{path.name}: profile must be a bounded regular file')
    values = dict(initial or {})
    seen: set[str] = set()
    for number, original in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = original.strip()
        if not line or line.startswith('#'):
            continue
        candidate = re.match(r'(?:export\s+)?([A-Z][A-Z0-9_]*)', line)
        if not candidate or not (candidate[1].startswith('NFS_') or candidate[1] in EXTRA):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if not match or match[1] in seen:
            raise ValueError(f'{path.name}:{number}: malformed or duplicate NFS policy assignment')
        key, value = match.groups()
        def expand(variable: re.Match[str]) -> str:
            if variable[1] not in values:
                raise ValueError(f'{path.name}:{number}: unknown/forward NFS variable: {variable[1]}')
            return values[variable[1]]
        value = re.sub(r'\$\{([A-Z][A-Z0-9_]*)\}', expand, value)
        if '$' in value:
            raise ValueError(f'{path.name}:{number}: executable or unsupported shell expansion in NFS policy')
        values[key] = value
        seen.add(key)
    return values


def check(seed: Path = SEED) -> int:
    profiles = sorted((seed/'hosts/profiles').glob('*.env'))
    if not profiles:
        raise ValueError('no network sharing profiles found')
    helper = runpy.run_path(str(seed/'scripts/late/network-sharing.py'), run_name='network_sharing_policy')
    account = read_values(seed/'hosts/installer/account.env')
    for path in profiles:
        try:
            helper['Settings'].from_environment(read_values(path, account))
        except ValueError as error:
            raise ValueError(f'NFS policy validation failed ({path.name}): {error}') from error
    return len(profiles)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        count = check()
    except (OSError, ValueError) as error:
        print('network-sharing preflight: ' + str(error), file=sys.stderr)
        return 1
    print(f'network-sharing: {count} profiles validated with the target policy (offline)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
