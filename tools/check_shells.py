#!/usr/bin/env python3
"""Parse every shell source/template and the generated preseed command values.

The generated values are checked at BOTH shell boundaries: the command passed
by d-i and the body passed to its nested /bin/sh -c. No script is executed by
this checker. Runtime bootstrap tests live in test_bootstrap_portability.py.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '__pycache__', '.pytest_cache', 'validation'}
COMMAND_KEYS = {'preseed/include_command', 'preseed/early_command',
                'partman/early_command', 'preseed/late_command'}


def preseed_commands(path: Path) -> dict[str, str]:
    commands: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        fields = raw.split(None, 3)
        if len(fields) < 2 or fields[1] not in COMMAND_KEYS:
            continue
        if len(fields) != 4 or fields[0] != 'd-i' or fields[2] != 'string':
            raise ValueError(f'{path}:{number}: malformed command field')
        if fields[1] in commands:
            raise ValueError(f'{path}:{number}: duplicate command field')
        commands[fields[1]] = fields[3]
    if commands.keys() != COMMAND_KEYS:
        raise ValueError('generated preseed does not contain every mandatory command')
    return commands


def shell_sources(root: Path):
    for path in sorted(root.rglob('*')):
        if not path.is_file() or any(part in EXCLUDED for part in path.relative_to(root).parts):
            continue
        data = path.read_bytes()
        first = data.split(b'\n', 1)[0].decode('utf-8', errors='replace')
        name = path.name.removesuffix('.tmpl')
        relative = path.relative_to(root).as_posix()
        if name.startswith('.bash') or (first.startswith('#!') and re.search(r'\bbash\b', first)):
            yield path, 'bash'
        elif (name.endswith(('.sh', '.env')) or name == '.profile'
              or '/etc/default/grub.d/' in relative
              or (first.startswith('#!') and re.search(r'\b(sh|dash|ash)\b', first))):
            yield path, 'posix'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    busybox = shutil.which('busybox')
    dash = shutil.which('dash')
    bash = shutil.which('bash')
    if not busybox or not dash or not bash:
        print('shell validation requires busybox, dash and bash; no silent skips', file=sys.stderr)
        return 1
    shells = {'dash': [dash], 'busybox-ash': [busybox, 'sh']}
    results = []

    def check(label: str, command: list[str]) -> None:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            results.append({'source': label, 'returncode': result.returncode,
                            'detail': result.stderr.strip()})
        except subprocess.TimeoutExpired:
            results.append({'source': label, 'returncode': 124, 'detail': 'parser timed out'})

    sources = list(shell_sources(ROOT))
    for path, kind in sources:
        interpreters = {'bash': [bash]} if kind == 'bash' else shells
        for name, executable in interpreters.items():
            check(f'{path.relative_to(ROOT)} [{name}]', [*executable, '-n', str(path)])
    try:
        commands = preseed_commands(ROOT / 'd-i/forky/preseed.cfg')
        for question, value in commands.items():
            words = shlex.split(value)
            if len(words) != 3 or words[:2] != ['/bin/sh', '-c']:
                raise ValueError(f'{question}: expected a single /bin/sh -c command')
            for name, executable in shells.items():
                check(f'{question}:outer [{name}]', [*executable, '-n', '-c', value])
                check(f'{question}:inner [{name}]', [*executable, '-n', '-c', words[2]])
    except ValueError as error:
        results.append({'source': 'generated preseed', 'returncode': 1, 'detail': str(error)})
    failures = [item for item in results if item['returncode']]
    report = {'success': not failures, 'shell_files': len(sources),
              'parser_checks': len(results), 'failures': failures,
              'scope': 'parse checks only; runtime execution is a separate test stage'}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    for failure in failures:
        print(f"FAIL {failure['source']}: {failure['detail']}", file=sys.stderr)
    print(f"{len(sources)} shell files; {len(results)} parser checks; "
          + ('PASS' if not failures else 'FAIL'))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
