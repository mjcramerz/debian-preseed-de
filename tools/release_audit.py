#!/usr/bin/env python3
"""Inventory every release file and run non-executing shell/Python syntax checks.

Do not confuse an inventory entry with a validated runtime configuration. Perl
checks (including explicit dependency blocks) are in the repository audit target.
"""
from __future__ import annotations
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'validation/whole-tree.json')
    args = parser.parse_args()
    records = []
    errors = []
    busybox = shutil.which('busybox')
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT)
        if '.git' in rel.parts or rel.parts[0] == 'validation' or path.is_dir():
            continue
        info = path.lstat()
        item = {'path':str(rel), 'mode':oct(stat.S_IMODE(info.st_mode)), 'bytes':info.st_size}
        records.append(item)
        if path.is_symlink():
            item['kind'] = 'symlink'
            if not path.resolve().is_relative_to(ROOT):
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
              'perl':'See make audit / validation/audit.json; missing dependencies are BLOCKED, not PASS.',
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
