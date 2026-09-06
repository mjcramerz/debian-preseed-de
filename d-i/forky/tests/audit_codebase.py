#!/usr/bin/env python3
"""Inventory and offline syntax checks for every requested review scope.

Run in a disposable Linux environment with Python 3.11+, Perl and a POSIX shell:
  python3 -B d-i/forky/tests/audit_codebase.py --output audit.json
This does not start services or apply configuration. Perl -c can execute BEGIN
blocks, so run only on a source tree you trust. Missing external dependencies
and templates are reported separately, never counted as passing checks.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
FORKY = ROOT / 'd-i/forky'
SCOPE_NAMES = ['hooks/target', 'hooks/installer']
PLACEHOLDER = re.compile(r'__[A-Z][A-Z0-9_]+__')
UNIT_SUFFIXES = ('.service', '.socket', '.target', '.timer', '.path', '.slice', '.mount')


def files_under(path: Path) -> set[Path]:
    if path.is_file():
        return {path}
    return {p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def unit_structure(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Lexical structure only: repeated keys are legal in systemd unit files."""
    section = ''
    values: dict[str, list[str]] = {}
    pending = ''
    problems: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.endswith('\\'):
            pending += line[:-1] + ' '
            continue
        line = pending + line
        pending = ''
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            continue
        if PLACEHOLDER.fullmatch(line):
            continue
        if '=' not in line or not section:
            problems.append(f'line {number}: invalid section/key structure')
            continue
        key, value = line.split('=', 1)
        values.setdefault(f'{section}.{key.strip()}', []).append(value.strip())
    if pending:
        problems.append('unterminated continuation')
    return values, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    scopes = {name: files_under(FORKY / name) for name in SCOPE_NAMES}
    scope_paths = set().union(*scopes.values())
    paths = scope_paths | files_under(FORKY / 'scripts') | files_under(FORKY / 'hosts')
    perl_dirs = []
    base = FORKY / 'hooks/target/usr/local/lib/perl5/site_perl'
    if base.exists():
        perl_dirs.extend(str(p) for p in sorted(base.iterdir()) if p.is_dir())
    perl_args = [arg for directory in perl_dirs for arg in ('-I', directory)]

    def scan(path: Path) -> dict:
        raw = path.read_bytes()
        text = raw.decode('utf-8', errors='replace')
        first = text.split('\n', 1)[0]
        relative = str(path.relative_to(ROOT))
        name = path.name.removesuffix('.tmpl')
        kind = 'config-or-data'
        state = 'inventory-only'
        detail = ''
        cmd = None
        stdin = None
        facts = {}
        if (first.startswith('#!') and 'python' in first) or name.endswith('.py'):
            kind = 'python'
        elif (first.startswith('#!') and 'perl' in first) or name.endswith(('.pm', '.pl')):
            kind = 'perl'
            cmd = ['perl', *perl_args, '-c', str(path)]
        elif ((first.startswith('#!') and re.search(r'\b(sh|bash|dash)\b', first))
              or name.endswith(('.sh', '.env')) or '/etc/default/grub.d/' in relative
              or name in ('.bashrc', '.bash_profile', '.profile')):
            kind = 'shell'
            cmd = ['bash' if 'bash' in first or name.startswith('.bash') else 'sh', '-n', str(path)]
        elif '/polkit-1/rules.d/' in relative:
            kind = 'javascript'
            cmd = ['node', '--check']
            stdin = text
        elif (name.endswith(UNIT_SUFFIXES) or re.search(r'/[^/]+\.(?:service|socket|slice|target)\.d/', relative)):
            kind = 'systemd-structure'
        elif name.endswith('.json'):
            kind = 'json'
        elif name.endswith('.toml'):
            kind = 'toml'
        elif name.endswith('.xml') or text.lstrip().startswith(('<?xml', '<!DOCTYPE busconfig', '<busconfig')):
            kind = 'xml'
        try:
            if kind == 'python':
                ast.parse(text, filename=relative)
                state = 'pass'
            elif kind == 'json':
                json.loads(text)
                state = 'pass'
            elif kind == 'toml':
                # Unquoted tokens are intentionally not valid TOML before rendering.
                if PLACEHOLDER.search(text):
                    state = 'template-needs-render'
                else:
                    tomllib.loads(text)
                    state = 'pass'
            elif kind == 'xml':
                ET.fromstring(text)
                state = 'pass'
            elif kind == 'systemd-structure':
                values, errors = unit_structure(text)
                facts = {k: v for k, v in values.items() if k.split('.', 1)[-1] in {
                    'Type', 'ExecStart', 'ExecStartPre', 'ExecStop', 'ExecStopPost',
                    'KillMode', 'TimeoutStartSec', 'TimeoutStopSec', 'Restart',
                    'PartOf', 'BindsTo', 'Requires', 'Wants', 'After', 'Before',
                    'TasksMax', 'MemoryMax', 'NoNewPrivileges', 'User', 'Delegate'}}
                state = 'fail' if errors else 'structure-pass'
                detail = '; '.join(errors)
            elif cmd:
                if not shutil.which(cmd[0]):
                    state = 'blocked-tool'
                    detail = f'{cmd[0]} is not installed'
                else:
                    result = subprocess.run(cmd, input=stdin, text=True,
                        capture_output=True, timeout=20,
                        env={**os.environ, 'LC_ALL': 'C', 'PERL5OPT': ''})
                    state = 'pass' if result.returncode == 0 else 'fail'
                    if result.returncode:
                        detail = result.stderr[-4000:].replace(str(ROOT), '$ROOT')
                        if kind == 'perl' and ('Can\'t locate ' in detail or 'Can\'t load ' in detail):
                            state = 'blocked-dependency'
                        elif PLACEHOLDER.search(text):
                            state = 'template-needs-render'
        except subprocess.TimeoutExpired:
            state, detail = 'blocked-timeout', 'syntax checker exceeded 20 seconds'
        except (SyntaxError, ValueError, ET.ParseError) as exc:
            state = 'template-needs-render' if PLACEHOLDER.search(text) else 'fail'
            detail = str(exc).replace(str(ROOT), '$ROOT')
        return {'path': relative, 'requested_scope': path in scope_paths,
                'kind': kind, 'check': state, 'detail': detail, 'unit_facts': facts,
                'lines': len(raw.splitlines()), 'bytes': len(raw),
                'mode': oct(path.stat().st_mode & 0o777),
                'sha256': hashlib.sha256(raw).hexdigest(),
                'placeholder_count': len(PLACEHOLDER.findall(text))}

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(scan, sorted(paths)))
    checks = Counter(record['check'] for record in records)
    report = {
        'scope_counts': {name: len(items) for name, items in scopes.items()},
        'requested_unique_files': len(scope_paths), 'total_with_installers_and_hosts': len(records),
        'check_counts': dict(sorted(checks.items())),
        'kind_counts': dict(sorted(Counter(r['kind'] for r in records).items())),
        'limits': ['Syntax and inventory are not semantic or runtime proof.',
                   'Systemd structure checks do not resolve vendor units or template values.',
                   'Blocked dependency/template checks are not passes.',
                   'No kernel policies, network changes, services or installers are applied.'],
        'files': records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=args.output.parent, delete=False) as stream:
        temporary = stream.name
        json.dump(report, stream, indent=2)
        stream.write('\n')
    os.replace(temporary, args.output)
    print(json.dumps({k: report[k] for k in ('requested_unique_files', 'total_with_installers_and_hosts', 'check_counts', 'kind_counts')}, indent=2))
    return 1 if checks.get('fail') else 0


if __name__ == '__main__':
    raise SystemExit(main())
