#!/usr/bin/env python3
"""Repeat the real short-URL bootstrap against a private loopback endpoint.

Each attempt uses its own runtime directory, Debconf database and HTTP server.
Nothing applies host selections, changes devices or contacts public services.
JSON is written to stdout; nonzero exit means at least one probe failed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'd-i/forky/tests'))
import test_repository_transport as transport


def run_probe(index: int) -> dict[str, Any]:
    case = transport.RealBootstrapTests(
        'test_complete_short_url_bootstrap_fetches_snapshot_once'
    )
    try:
        case.setUp()
        endpoint = case.endpoint()
        result = case.include(
            f'url={endpoint.url}/short classes=prod;{transport.ROLE};standard;dhcp;ssh'
        )
        counts = dict(endpoint.counts)
        expected = {'/short': 1}
        expected.update({transport.RAW_PREFIX + '/' + name: 1 for name in (
            'preseed.cfg', 'scripts/common/source.sh', 'payload.manifest', 'payload.tar.gz'
        )})
        record: dict[str, Any] = {
            'index': index, 'returncode': result.returncode, 'counts': counts,
            'success': result.returncode == 0 and counts == expected,
        }
        if not record['success']:
            record['stderr'] = result.stderr
        return record
    except Exception as error:
        return {'index': index, 'success': False, 'error': repr(error)}
    finally:
        case.doCleanups()


def positive_int(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 64:
        raise argparse.ArgumentTypeError('expected an integer from 1 to 64')
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=positive_int, default=24)
    parser.add_argument('--workers', type=positive_int, default=3)
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=min(args.runs, args.workers)) as executor:
        records = list(executor.map(run_probe, range(args.runs)))
    success = all(record['success'] for record in records)
    print(json.dumps({'success': success, 'runs': args.runs,
                      'concurrency': min(args.runs, args.workers),
                      'records': records}, indent=2))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
