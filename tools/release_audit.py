#!/usr/bin/env python3
"""Inventory every release file and run non-executing shell/Python syntax checks.

Do not confuse an inventory entry with a validated runtime configuration. Perl
checks (including explicit dependency blocks) are in the repository audit target.
"""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[1] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import argparse
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_ENTRIES = 100_000


def release_entries(root: Path, output: Path):
    """Classify entries without following directory links or scanning evidence."""
    root = root.resolve(strict=True)
    if '..' in output.parts:
        raise ValueError('release evidence must not contain parent traversal')
    output = output.absolute()
    if not output.is_relative_to(root) or output == root:
        raise ValueError('release evidence must stay inside the private checkout')
    for parent in (output, *output.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('release evidence must not use symlinks')
    excluded = {root / '.git', root / '.build/validation', root / 'validation'}
    # A file directly in the source root excludes only itself. A dedicated
    # evidence directory excludes all earlier runs as well as the current one.
    excluded.add(output.parent if output.parent != root else output)
    pending = [root]
    count = 0
    while pending:
        directory = pending.pop()
        entries = []
        with os.scandir(directory) as scan:
            for entry in scan:
                count += 1
                if count > MAX_SOURCE_ENTRIES:
                    raise ValueError('release source entry limit exceeded')
                path = Path(entry.path)
                if path in excluded:
                    continue
                info = entry.stat(follow_symlinks=False)
                entries.append((path, info))
        for path, info in sorted(entries, key=lambda item: item[0].name):
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
            else:
                yield path, info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.build/validation/whole-tree.json')
    args = parser.parse_args()
    args.output = args.output.absolute()
    records = []
    errors = []
    busybox = shutil.which('busybox')
    for path, info in release_entries(ROOT, args.output):
        rel = path.relative_to(ROOT)
        item = {'path':str(rel), 'mode':oct(stat.S_IMODE(info.st_mode)), 'bytes':info.st_size}
        records.append(item)
        if stat.S_ISLNK(info.st_mode):
            item['kind'] = 'symlink'
            try:
                target = path.resolve(strict=True)
            except (OSError, RuntimeError):
                errors.append(str(rel)+': unresolved symlink')
            else:
                if not target.is_relative_to(ROOT):
                    errors.append(str(rel)+': escaping symlink')
            continue
        if not stat.S_ISREG(info.st_mode):
            errors.append(str(rel)+': unsupported file type')
            continue
        data = path.read_bytes()
        item['sha256'] = hashlib.sha256(data).hexdigest()
        if '__pycache__' in rel.parts or path.suffix in ('.pyc','.pyo','.swp'):
            errors.append(str(rel)+': forbidden cache/editor artifact')
        if info.st_mode & 0o6000:
            errors.append(str(rel)+': unexpected setuid/setgid source file')
        if info.st_mode & 0o002:
            errors.append(str(rel)+': world-writable source file')
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            item['check'] = 'binary-inventory-only'
            continue
        if re.search(r'^-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----\s*$',text,re.M):
            errors.append(str(rel)+': private-key material requires removal')
        first = text.splitlines()[0] if text else ''
        language = ('python' if path.suffix == '.py' or ('#!' in first and 'python' in first)
                    else 'bash' if first.startswith('#!') and 'bash' in first
                    else 'sh' if path.suffix == '.sh' or (first.startswith('#!') and re.search(r'\bsh\b',first))
                    else '')
        if path.suffix == '.tmpl':
            item['check'] = 'template-needs-render'
        elif language == 'python':
            try:
                ast.parse(text,filename=str(rel))
                item['check'] = 'python-syntax-pass'
            except SyntaxError as exc:
                item['check'] = 'FAIL'; errors.append(f'{rel}: Python syntax line {exc.lineno}')
        elif language in ('sh','bash'):
            commands = [[shutil.which(language) or language,'-n',str(path)]]
            if language == 'sh' and busybox:
                commands.append([busybox,'sh','-n',str(path)])
            item['check'] = 'shell-syntax-pass'
            for command in commands:
                result = subprocess.run(command,capture_output=True,text=True,timeout=15)
                if result.returncode:
                    item['check'] = 'FAIL'
                    errors.append(f'{rel}: {Path(command[0]).name} syntax failed: {result.stderr[:300]}')
        else:
            item['check'] = 'inventory-only'
    result = {'success':not errors,'file_count':len(records),
              'check_counts':dict(sorted(Counter(r.get('check',r.get('kind','unknown')) for r in records).items())),
              'shellcheck':'available-not-invoked' if shutil.which('shellcheck') else 'NOT RUN: executable unavailable',
              'perl':'See make audit / .build/validation/audit.json; missing dependencies are BLOCKED, not PASS.',
              'limits':['No code execution for Python AST or shell -n checks.',
                        'Templates require renderer/runtime tests; inventory is not runtime validation.',
                        '.git and self-generated validation evidence excluded from the source inventory.'],
              'errors':errors,'files':records}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('files',)},indent=2))
    return 0 if not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
