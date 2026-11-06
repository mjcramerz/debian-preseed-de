#!/usr/bin/env python3
"""Static changed-file and payload checks for d-i/trixie-server only.

This checker deliberately ignores unrelated Forky working-tree changes. It
does not execute installer code, load policy, contact services, or provision an
environment. The Trixie payload manifest uses byte sizes and paths only.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tomllib
import xml.etree.ElementTree as ElementTree

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'd-i/trixie-server'
GENERATED = ('payload.tar.gz', 'payload.manifest', 'preseed.cfg')
FORBIDDEN = (
    b'sha256', b'sha-256', b'sha256sum', b'checksum', b'zsh', b'xwayland',
    b'/var/cache/ci', b'/var/lib/ci', b'/var/cache/bazel', b'/var/lib/bazel',
    b'/var/lib/codex', b'file:///cdrom', b'/cdrom/d-i',
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=30, check=False,
    )


def changed_trixie_files() -> list[Path]:
    names: set[str] = set()
    for command in (
        ['git', 'diff', '--name-only', '-z', '--diff-filter=ACMRTUXB'],
        ['git', 'diff', '--cached', '--name-only', '-z', '--diff-filter=ACMRTUXB'],
        ['git', 'ls-files', '--others', '--exclude-standard', '-z'],
    ):
        result = _run(command)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip()[:300])
        names.update(part for part in result.stdout.split('\0') if part)
    paths = []
    for name in sorted(names):
        path = ROOT / name
        if path.is_file() and not path.is_symlink() and path.is_relative_to(SEED):
            paths.append(path)
    return paths


def read_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.name.endswith('.tar.gz'):
        return data
    if b'\0' in data:
        raise ValueError(f'NUL byte: {path.relative_to(ROOT)}')
    data.decode('utf-8')
    return data


def shell_kind(path: Path) -> str | None:
    if path.name.endswith('.tar.gz'):
        return None
    first = path.read_text(encoding='utf-8', errors='replace').splitlines()[:1]
    line = first[0] if first else ''
    if 'bash' in line and line.startswith('#!'):
        return 'bash'
    if line.startswith('#!') and ('/sh' in line or 'dash' in line):
        return 'sh'
    if path.suffix in {'.env', '.sh'} or path.name.endswith('.sh.tmpl'):
        return 'sh'
    return None


def check_shell(path: Path) -> None:
    kind = shell_kind(path)
    if not kind:
        return
    interpreter = 'bash' if kind == 'bash' else 'dash'
    result = _run([interpreter, '-n', str(path)])
    if result.returncode:
        raise ValueError(f'{path.relative_to(ROOT)}: shell syntax: {(result.stderr or result.stdout).strip()}')


def check_structured(path: Path, data: bytes) -> None:
    if path.name.endswith('.tar.gz'):
        return
    suffix = path.name.removesuffix('.tmpl').rsplit('.', 1)[-1].lower()
    text = data.decode('utf-8')
    if suffix == 'json':
        json.loads(text)
    elif suffix == 'toml':
        tomllib.loads(text)
    elif suffix == 'xml':
        ElementTree.fromstring(text)
    elif suffix == 'py':
        ast.parse(text, filename=str(path.relative_to(ROOT)))


def check_target_assets() -> None:
    manifest = SEED / 'classes/configs/target-assets.tsv'
    for number, line in enumerate(manifest.read_text(encoding='utf-8').splitlines(), 1):
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 4:
            raise ValueError(f'target-assets.tsv line {number} is not four columns')
        source = SEED / 'hooks/target' / fields[2]
        if not source.is_file() or source.is_symlink():
            raise ValueError(f'target-assets.tsv line {number} source is missing: {fields[2]}')
        if 'trixie-server' in fields[3]:
            raise ValueError(f'installed target path contains installer name: {fields[3]}')


def check_forky_bridge_lists() -> None:
    payload_list = SEED / 'forky-payload.list'
    zram_manifest = SEED / 'zram-source.manifest'

    def read_list(path: Path, marked: bool) -> set[str]:
        entries = set()
        for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if marked:
                marker, separator, line = line.partition(' ')
                if marker != '*' or not separator or not line:
                    raise ValueError(f'{path.name} line {number} is malformed')
            if line.startswith('/') or '..' in line.split('/') or line in entries:
                raise ValueError(f'{path.name} line {number} has an unsafe or duplicate path')
            source = ROOT / 'd-i/forky' / line
            if not source.is_file() or source.is_symlink():
                raise ValueError(f'{path.name} line {number} source is missing: {line}')
            entries.add(line)
        if not entries:
            raise ValueError(f'{path.name} is empty')
        return entries

    payload_entries = read_list(payload_list, False)
    zram_entries = read_list(zram_manifest, True)
    if not zram_entries <= payload_entries:
        missing = sorted(zram_entries - payload_entries)
        raise ValueError(f'ZRAM bridge entries are absent from forky-payload.list: {missing}')
    module_root = ROOT / 'd-i/forky/hooks/target/usr/local/lib/perl5/site_perl/zram-writeback'
    module_entries = {
        path.relative_to(ROOT / 'd-i/forky').as_posix()
        for path in module_root.rglob('*.pm')
    }
    if not module_entries <= zram_entries:
        missing = sorted(module_entries - zram_entries)
        raise ValueError(f'ZRAM Perl modules are absent from zram-source.manifest: {missing}')


def check_payload_products() -> int:
    archive_path, manifest_path, preseed_path = (SEED / name for name in GENERATED)
    if not all(path.is_file() and not path.is_symlink() for path in (archive_path, manifest_path, preseed_path)):
        raise ValueError('Trixie build products are missing; run make build-trixie')
    entries: dict[str, int] = {}
    lines = manifest_path.read_text(encoding='utf-8').splitlines()
    if lines[:2] != ['format=1', 'format_description=size<TAB>path']:
        raise ValueError('Trixie payload manifest header is invalid')
    for line in lines[2:]:
        size, separator, name = line.partition('\t')
        if not separator or not size.isdigit() or not name or name.startswith('/') or '..' in name.split('/'):
            raise ValueError(f'invalid Trixie payload manifest row: {line!r}')
        if name in entries:
            raise ValueError(f'duplicate Trixie payload manifest row: {name}')
        entries[name] = int(size)
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        actual = {}
        for member in members:
            if not member.isfile() or member.name.startswith('/') or '..' in member.name.split('/'):
                raise ValueError(f'unsafe Trixie payload member: {member.name}')
            actual[member.name] = member.size
    if actual != entries:
        raise ValueError('Trixie payload archive and manifest differ')
    return len(entries)


def check_contracts() -> None:
    source = (SEED / 'scripts/common/source.sh').read_text(encoding='utf-8')
    preseed = (SEED / 'preseed.cfg.tmpl').read_text(encoding='utf-8')
    for required in (
        'scripts/common/source.sh', 'preseed.cfg', 'payload.manifest',
        'payload.tar.gz',
    ):
        if required not in source and required != 'scripts/common/source.sh':
            raise ValueError(f'Trixie source transport does not fetch {required}')
    if 'server_source=https://' not in preseed or 'file:///cdrom' in preseed:
        raise ValueError('Trixie preseed must require HTTPS payload source')
    if 'server_source_prepare_payload' not in preseed or '/tmp/server-install' not in preseed:
        raise ValueError('Trixie preseed does not stage the fetched payload')
    if 'server_source_prepare_payload' not in source or 'tar -xzf' not in source:
        raise ValueError('Trixie source transport does not extract payload archive')
    identity = (SEED / 'hosts/installer/identity.env').read_text(encoding='utf-8')
    if 'SYSTEM_PREFIX="LPL"' not in identity:
        raise ValueError('Trixie identity prefix must be LPL')
    if any(key in identity for key in ('HOST_IDENTITY_SOURCE=', 'HOSTNAME_SOURCE=', 'DOMAIN_SOURCE=', 'PRIMARY_USERNAME_SOURCE=')):
        raise ValueError('Trixie identity contains metadata absent from Forky identity.env')
    for profile in sorted((SEED / 'hosts/profiles').glob('*.env')):
        if profile.name == 'shared-srv.env':
            continue
        values = {}
        for line in profile.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key] = value.strip().strip('"')
        expected = {
            'NFS_SERVER_ENABLE': 'false', 'NFS_SERVER_THREADS': '8',
            'NFS_CLIENT_ENABLE': 'true', 'NFS_CLIENT_TARGET_IP': '192.168.50.82',
            'NFS_CLIENT_READ_ONLY': 'false',
        }
        if any(values.get(key) != value for key, value in expected.items()):
            raise ValueError(f'NFS profile contract failed: {profile.name}')


def main() -> int:
    try:
        paths = changed_trixie_files()
        for path in paths:
            data = read_bytes(path)
            if not path.name.endswith('.tar.gz') and any(token in data.lower() for token in FORBIDDEN):
                raise ValueError(f'forbidden Trixie token in {path.relative_to(ROOT)}')
            check_shell(path)
            check_structured(path, data)
        check_target_assets()
        check_forky_bridge_lists()
        check_contracts()
        count = check_payload_products()
        print(f'Trixie post-change static audit: PASS (changed_files={len(paths)}, payload_files={count})')
        return 0
    except (OSError, UnicodeError, ValueError, RuntimeError, tarfile.TarError, json.JSONDecodeError, tomllib.TOMLDecodeError, ElementTree.ParseError, SyntaxError) as error:
        print(f'Trixie post-change static audit: FAIL: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
