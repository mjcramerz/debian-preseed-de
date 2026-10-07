#!/usr/bin/env python3
"""Validate executable module wiring without generating or modifying sources."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import subprocess
import sys

SEED = Path(__file__).resolve().parents[1] / 'd-i/forky'
# Written plainly so shell quoting and validation are easy to review together.
CALL = re.compile(r'''^bootstrap_source_module '([^']+)' \|\| (?:return|exit) "\$\?"$''', re.M)
MODULE_DIRS = ('scripts/common/modules', 'scripts/runtime/modules',
               'scripts/desktop/components', 'scripts/late/devops')
ENTRYPOINTS = ('scripts/common/lib.sh', 'scripts/runtime/common.sh',
               'scripts/desktop/components.sh', 'scripts/late/devops.sh.tmpl')
SHARED = {'scripts/common/debconf.sh', 'scripts/common/lifecycle.sh',
          'scripts/common/apt-sources.sh', 'scripts/common/credentials.sh'}


def module_file(seed: Path, relative: str) -> Path:
    if not re.fullmatch(r'scripts/[A-Za-z0-9_/-]+[.]sh', relative) or '..' in relative:
        raise ValueError(f'unsafe module reference: {relative!r}')
    path = seed / relative
    template = path.with_name(path.name + '.tmpl')
    if path.exists() and template.exists():
        raise ValueError(f'ambiguous module: {relative}')
    path = template if template.exists() else path
    for p in (path, *path.relative_to(seed).parents):
        p = p if p.is_absolute() else seed / p
        if p.is_symlink():
            raise ValueError(f'symlinked module: {relative}')
    if not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError(f'missing or hardlinked module: {relative}')
    return path


def check(seed: Path = SEED) -> int:
    seed = seed.resolve()
    if (seed.parents[1] / 'src').exists():
        raise ValueError('root src/ is not an installer input; keep editable code in d-i/forky/')
    used = set()
    for relative in ENTRYPOINTS:
        path = seed / relative
        text = path.read_text()
        names = CALL.findall(text)
        lines = [line for line in text.splitlines() if line.startswith('bootstrap_source_module ')]
        if not names or len(names) != len(lines) or len(set(names)) != len(names):
            raise ValueError(f'invalid, empty or repeated module list: {relative}')
        for name in names:
            module = module_file(seed, name)
            if name not in SHARED and name in used:
                raise ValueError(f'module has multiple owners: {name}')
            used.add(name)
            parsed = subprocess.run(['/bin/sh', '-n', str(module)], capture_output=True, text=True)
            if parsed.returncode:
                raise ValueError(f'module syntax error: {name}: {parsed.stderr.strip()}')
    inventory = {p.relative_to(seed).as_posix().removesuffix('.tmpl')
                 for directory in MODULE_DIRS for p in (seed / directory).rglob('*') if p.is_file()}
    if inventory != used - SHARED:
        raise ValueError(f'unwired or missing module: {sorted(inventory ^ (used - SHARED))}')
    # These two inputs used to be checked by the removed profile generator.
    # Validate the directly edited files now; never synthesize their contents.
    for path in sorted((seed / 'hosts/profiles').glob('*.env')):
        for key in ('TMPFS_VAR_SPOOL_RSYSLOG', 'SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB'):
            values = re.findall(r'^' + key + r'="([^"\n]*)"$', path.read_text(), re.M)
            occurrences = re.findall(r'^\s*(?:export\s+)?' + key + r'=', path.read_text(), re.M)
            if len(values) != 1 or len(occurrences) != 1:
                raise ValueError(f'{path.name}: missing or duplicate {key}')
            value = values[0]
            if key == 'TMPFS_VAR_SPOOL_RSYSLOG':
                valid = value in ('true', 'false')
            else:
                valid = bool(re.fullmatch(r'[1-9][0-9]{0,9}', value)) and 1 <= int(value) <= 65536
            if not valid:
                raise ValueError(f'{path.name}: invalid {key}')
    return len(inventory)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        print(f'{check()} runtime modules wired; environment files are read-only inputs')
        return 0
    except (OSError, ValueError) as exc:
        print(f'module validation failed: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
