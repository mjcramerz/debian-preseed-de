#!/usr/bin/env python3
"""Build browser policies only; user-imported exports live in Workspace/netscape.

No browser or extension databases are written. Extension installation policy
does not populate managed extension storage or lock the user's import settings.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import runpy
import stat

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'browser-config'
TARGET = ROOT / 'd-i/forky/hooks/target'
# Full uBlock Origin is MV2; current Chrome requires its upstream MV3 variant.
UBOL = 'ddkjiahejlhfcafbddmgiahcphecmpfh'
NOSCRIPT = 'doojmbjmlfjjnbmnoijecmcbfeoakpjm'
BADGER = 'pkehgijcmpdhfbdbbnkijodmdjhbjlgp'
FAMILIES = ('etc/vivaldi', 'etc/chromium', 'etc/opt/edge', 'etc/opt/chrome')
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


def generate() -> dict[Path, bytes]:
    policy = json.loads((CONFIG / 'policies.json').read_text(encoding='utf-8'),
                        object_pairs_hook=unique_object)
    sections = {'security', 'telemetry', 'edge_security', 'edge_telemetry', 'recommended', 'extensions'}
    if (not isinstance(policy, dict) or set(policy) != sections
            or any(not isinstance(value, dict) for value in policy.values())):
        raise ValueError('invalid browser policy sections')
    if set(policy['extensions']) != {'ExtensionSettings'}:
        raise ValueError('only extension installation policy is allowed; managed storage locks user settings')
    expected = {'installation_mode': 'normal_installed',
                'update_url': 'https://clients2.google.com/service/update2/crx',
                'toolbar_pin': 'default_pinned'}
    settings = policy['extensions']['ExtensionSettings']
    if (not isinstance(settings, dict) or set(settings) != {UBOL, NOSCRIPT, BADGER}
            or any(value != expected for value in settings.values())):
        raise ValueError('invalid browser extension IDs or user-adjustable installation policy')
    for section in sections - {'extensions'}:
        if any(key == '3rdparty' or (key.startswith('Extension') and key != 'ExtensionDeveloperModeSettings')
               for key in policy[section]):
            raise ValueError('extension policies belong only in the installation section')
    if not set(policy['recommended']) <= RECOMMENDABLE:
        raise ValueError('unsupported recommended browser policy')

    output: dict[Path, bytes] = {}
    def emit(path: Path, value: dict) -> None:
        output[path] = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    for family in FAMILIES:
        base = TARGET / family / 'policies'
        prefix = 'edge_' if family == 'etc/opt/edge' else ''
        emit(base / 'managed/security.json', policy[prefix + 'security'])
        emit(base / 'managed/telemetry.json', policy[prefix + 'telemetry'])
        emit(base / 'managed/performance.json', {})
        emit(base / 'managed/extensions.json', policy['extensions'])
        emit(base / 'recommended/defaults.json', policy['recommended'])
    for profile in ('chromium', 'microsoft-edge', 'vivaldi'):
        emit(TARGET / 'etc/skel-desktop/.config' / profile / 'Default/Preferences', {
            'browser': {'custom_chrome_frame': False}, 'enable_do_not_track': False,
            'profile': {'default_content_setting_values': {'notifications': 2, 'popups': 2, 'sensors': 2}}})
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        writer = runpy.run_path(str(ROOT / 'tools/publication.py'))['atomic_write']
        changed = []
        for path, data in generate().items():
            if path.parent.exists() and path.parent.resolve(strict=True) != path.parent:
                raise ValueError(f'symlinked browser artifact parent: {path.relative_to(ROOT)}')
            if path.exists() or path.is_symlink():
                info = path.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()):
                    raise ValueError(f'unsafe browser artifact: {path.relative_to(ROOT)}')
                if stat.S_IMODE(info.st_mode) == 0o644 and path.read_bytes() == data:
                    continue
            changed.append(str(path.relative_to(ROOT)))
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                writer(path, data, 0o644)
        if args.check and changed:
            parser.exit(1, 'Stale browser artifacts:\n' + '\n'.join(changed) + '\n')
        print('Browser artifacts current' if args.check else f'Updated {len(changed)} browser artifacts')
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Browser policy build failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
