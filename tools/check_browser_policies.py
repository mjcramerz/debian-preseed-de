#!/usr/bin/env python3
"""Check authoritative native browser policies without generating or writing files."""
from __future__ import annotations

# Policy validation is permitted only in the disposable validation image.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parent))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'd-i/forky/hooks/target'
FAMILIES = ('etc/vivaldi', 'etc/chromium', 'etc/opt/edge', 'etc/opt/chrome')
UBOL = 'ddkjiahejlhfcafbddmgiahcphecmpfh'
NOSCRIPT = 'doojmbjmlfjjnbmnoijecmcbfeoakpjm'
BADGER = 'pkehgijcmpdhfbdbbnkijodmdjhbjlgp'
PROTON_VPN = 'jplgfhpmjnbigmhklmmbgecoobifkmpa'
RECOMMENDABLE = {'BackgroundModeEnabled', 'BlockThirdPartyCookies', 'NetworkPredictionOptions',
                'SearchSuggestEnabled', 'AutofillAddressEnabled', 'AutofillCreditCardEnabled',
                'PasswordManagerEnabled'}


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate browser policy key: {key}')
        result[key] = value
    return result


def check(target: Path = TARGET) -> None:
    """Inspect each browser independently; native JSON is the only policy input."""
    for family in FAMILIES:
        base = target / family / 'policies'
        for scope in ('managed', 'recommended'):
            directory = base / scope
            if directory.resolve(strict=True) != directory or not directory.is_dir():
                raise ValueError(f'unsafe browser policy directory: {directory}')
            paths = sorted((*directory.glob('*.json'), *directory.glob('*.json.tmpl')))
            required = ({'security.json', 'telemetry.json', 'performance.json', 'extensions.json'}
                        if scope == 'managed' else {'defaults.json'})
            if not required <= {path.name for path in paths}:
                raise ValueError(f'missing browser policy files: {directory}')
            seen = {}
            for path in paths:
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f'unsafe browser policy file: {path}')
                with path.open('rb') as stream:
                    data = stream.read(1024 * 1024 + 1)
                if len(data) > 1024 * 1024:
                    raise ValueError(f'browser policy file exceeds 1 MiB: {path}')
                policy = json.loads(data.decode('utf-8'), object_pairs_hook=unique_object)
                if not isinstance(policy, dict):
                    raise ValueError(f'browser policy must be a JSON object: {path}')
                for key in policy:
                    if key in seen:
                        raise ValueError(f'duplicate {scope} policy {key}: {seen[key]} and {path}')
                    seen[key] = path
                if scope == 'managed' and path.name == 'extensions.json':
                    expected = {extension_id: {
                        'installation_mode': 'normal_installed',
                        'update_url': 'https://clients2.google.com/service/update2/crx',
                        'toolbar_pin': 'default_pinned',
                    } for extension_id in (UBOL, NOSCRIPT, BADGER)}
                    # Native policy no longer manages Proton VPN (the entry
                    # was removed in 05d62b4). Do not restore it in a checker.
                    if policy != {'ExtensionSettings': expected}:
                        raise ValueError(f'invalid browser extension installation policy: {path}')
                elif any(key == '3rdparty' or (key.startswith('Extension')
                         and key != 'ExtensionDeveloperModeSettings') for key in policy):
                    raise ValueError(f'extension policies belong only in managed/extensions.json: {path}')
                if scope == 'recommended' and not policy.keys() <= RECOMMENDABLE:
                    raise ValueError(f'unsupported recommended browser policy: {path}')


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        check()
        print('native browser policies are valid; no files generated')
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(f'browser policy validation failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
