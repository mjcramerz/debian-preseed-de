#!/usr/bin/env python3
"""Validate shared logging data, template naming and native sink ownership.

The installer's POSIX AWK validator is authoritative. No daemon is executed.
"""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'd-i/forky'
TOKEN = re.compile(r'__INSTALLER_(LOG_[A-Z0-9_]+)__')
TEMPLATE_TOKEN = re.compile(r'__(?:INSTALLER|SYSTEMD|THEME)_[A-Z0-9_]+__')
ENGINE_EXCEPTIONS = {'scripts/late/volatile-storage.sh'}

def source_path(path: Path) -> Path:
    template = path.with_name(path.name + '.tmpl')
    if path.exists() and template.exists():
        raise ValueError(f'ambiguous plain/template source: {path}')
    return template if template.is_file() else path

def load_logging(seed: Path = SEED) -> dict[str, str]:
    result = subprocess.run(['awk', '-f', str(seed / 'scripts/common/logging-validate.awk'),
        str(seed / 'hosts/logging/observability-schema.tsv'), str(seed / 'hosts/logging/observability.env')],
        capture_output=True, text=True, timeout=15, check=False, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'logging catalog validation failed')
    return dict(line.split('=', 1) for line in result.stdout.splitlines())

def render_logging(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        try:
            return values[match[1]]
        except KeyError as exc:
            raise ValueError(f'unknown logging template key: {match[1]}') from exc
    rendered = TOKEN.sub(replace, text)
    if '__INSTALLER_LOG_' in rendered:
        raise ValueError('malformed or unresolved logging token')
    return rendered

def check(seed: Path = SEED) -> dict[str, int]:
    values = load_logging(seed)
    references = Counter()
    templates = logging_templates = 0
    for directory in ('hooks', 'scripts'):
        for path in sorted((seed / directory).rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            if path.name.endswith('.tmpl') and path.with_name(path.name[:-5]).exists():
                raise ValueError(f'ambiguous physical template: {path.relative_to(seed)}')
            data = path.read_bytes()
            if b'\0' in data:
                continue
            try:
                text = data.decode('utf-8')
            except UnicodeError:
                continue
            rel = path.relative_to(seed).as_posix()
            if rel in ENGINE_EXCEPTIONS or rel.startswith('scripts/common/'):
                continue
            if TEMPLATE_TOKEN.search(text):
                templates += 1
                if not path.name.endswith('.tmpl'):
                    raise ValueError(f'template input lacks .tmpl suffix: {rel}')
            if TOKEN.search(text):
                logging_templates += 1
                render_logging(text, values)
                references.update(TOKEN.findall(text))
            if rel.startswith('hooks/target/etc/rsyslog'):
                active = '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))
                # The sole file input reads native auditd records for the
                # AppArmor side log; broad journal or category mirrors remain
                # forbidden.
                if rel == 'hooks/target/etc/rsyslog.d/30-apparmor.conf.tmpl':
                    module = 'module(load="imfile" mode="polling" pollingInterval="2")'
                    if (active.count(module) != 1 or
                            active.count('input(type="imfile" File="__INSTALLER_LOG_AUDIT_FILE__"') != 1):
                        raise ValueError(f'invalid native audit file input: {rel}')
                    active = active.replace(module, '').replace('input(type="imfile"', 'input(type="managed-audit"')
                if re.search(r'\bimfile\b|/(?:vendor|runtime)\.log', active):
                    raise ValueError(f'obsolete file mirroring or category log: {rel}')
    references.update(re.findall(r'\$\{(LOG_[A-Z0-9_]+)\}', (seed/'hosts/logging/observability.env').read_text()))
    unused = values.keys() - references.keys()
    if unused:
        raise ValueError('logging values without consumers: ' + ', '.join(sorted(unused)))
    profiles = sorted((seed / 'hosts/profiles').glob('*.env'))
    for profile in profiles:
        text = profile.read_text()
        if re.search(r'^LOG_[A-Z0-9_]+=', text, re.M):
            raise ValueError(f'{profile.name}: shared LOG_* values belong in hosts/logging/observability.env')
        if len(re.findall(r'^SYSTEMD_JOURNAL_VOLATILE_ENABLE="(?:true|false)"$', text, re.M)) != 1:
            raise ValueError(f'{profile.name}: missing/duplicate explicit journal storage choice')
    return {'variables': len(values), 'templates': templates, 'logging_templates': logging_templates, 'profiles': len(profiles)}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=Path, default=SEED)
    args = parser.parse_args()
    try:
        stats = check(args.seed)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'logging: {exc}', file=sys.stderr)
        return 1
    print('logging: ' + ', '.join(f'{k}={v}' for k, v in stats.items()))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
