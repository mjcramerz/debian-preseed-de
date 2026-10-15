#!/usr/bin/env python3
"""Validate installer source and generated artifacts in the disposable image.

This is the explicit validation entrypoint. tools/build.py only serializes the
three installer products and never invokes this command during normal builds.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[1] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import argparse
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

from build import build, payload_files, payload_source

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'd-i/forky'
SAFE_PATH = re.compile(r'[A-Za-z0-9_./@+-]+\Z')

def resolve_python_interpreter() -> str:
    candidate = sys.executable or shutil.which('python3')
    if not candidate:
        raise ValueError('build validation requires a Python 3 interpreter')
    path = Path(candidate)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f'unsafe Python interpreter path: {candidate!r}')
    return str(path)

def refuse_private_inputs() -> None:
    """Catch private initrd material accidentally placed in the served tree.

    This is a fail-closed publishing guard, not a general secret scanner. Private
    media, backups and renamed/containerized secrets still belong outside ROOT.
    """
    forbidden = {'preseed.env', 'git_ed25519', 'git_ed25519.pub', 'id_git_ed25519'}
    private_header = re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----')
    for directory, names, files in os.walk(ROOT, followlinks=False):
        names[:] = [name for name in names if name not in {'.git', '__pycache__', '.pytest_cache'}]
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(ROOT)
            if name in forbidden:
                raise ValueError(f'private initrd input must not be published: {relative}')
            # Never follow a link merely to scan it. payload_files separately
            # rejects links in the distributable installer subtree.
            if path.is_symlink() or not path.is_file():
                continue
            with path.open('rb') as stream:
                beginning = stream.read(128).lstrip()
            if private_header.match(beginning):
                raise ValueError(f'private key must not be published: {relative}')

def validate_apparmor_modes() -> None:
    """Every repository policy file must have exactly one master-mode row."""
    directory = SEED / 'hooks/target/etc/apparmor.d'
    names = {p.name.removesuffix('.tmpl') for p in directory.iterdir() if p.is_file()}
    names.add('firstboot')  # Staged from scripts/firstboot/assets after security.
    config = SEED / 'hooks/target/etc/apparmor/modes.conf.tmpl'
    rows = [line.split() for line in config.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    if not rows or any(len(row) != 4 or
                       (row != ['enforce', 'optional' if row[2] == 'hardware-tuning' else 'required', row[2], '-']
                        if row[2] in ('hardware-tuning', 'app-veth')
                        else row[0] != '__DESKTOP_APPARMOR_STATE__')
                       for row in rows):
        raise ValueError('managed AppArmor rows must select the desktop state, except enforced hardware-tuning')
    declared = [row[2] for row in rows]
    if len(declared) != len(set(declared)):
        raise ValueError('duplicate managed AppArmor profile mode row')
    missing = names - set(declared)
    if missing:
        raise ValueError('unmanaged repository AppArmor profile: ' + ', '.join(sorted(missing)))

def validate(paths: list[Path]) -> None:
    validate_apparmor_modes()
    logging_checker = runpy.run_path(str(ROOT / 'tools/check_logging.py'))
    logging_checker['check'](SEED)
    theme_checker = runpy.run_path(str(ROOT / 'tools/check_themes.py'))
    theme_checker['check'](SEED)
    metadata_checker = runpy.run_path(str(ROOT / 'tools/check_shells.py'))
    forbidden = metadata_checker['external_metadata_dependencies'](ROOT)
    if forbidden:
        raise ValueError("forbidden external metadata executable: " + ", ".join(forbidden))
    repo = (SEED / 'repo.env').read_text()
    role_match = re.search(r'^REPOSITORY_ROLE="(desktop|server)"$', repo, re.M)
    if not role_match:
        raise ValueError('repo.env must declare exactly one repository role')
    role = role_match.group(1)
    for name, directory in re.findall(r'^(DIR_[A-Z_]+)="([^"]+)"$', repo, re.M):
        if not SAFE_PATH.fullmatch(directory) or '..' in Path(directory).parts:
            raise ValueError(f'unsafe directory: {name}')
        if not (SEED / directory).is_dir():
            raise ValueError(f'{name} points to a missing directory: {directory}')
    # Validate every literal path join in installer shell code, including
    # installer hooks. Dynamic hardware paths are checked by target-assets.tsv.
    directories = dict(re.findall(r'^(DIR_[A-Z_]+)="([^"]+)"$', repo, re.M))
    reference = re.compile(r"(?:installer|bootstrap)_repo_join_var\s+(DIR_[A-Z_]+)\s+[\"']?([A-Za-z0-9_./@+-]+)[\"']?\s*\)")
    for directory in ('scripts', 'hooks/installer'):
        for script in sorted((SEED / directory).rglob('*')):
            if not script.is_file():
                continue
            text = script.read_text().replace('\\\n', ' ')
            for variable in set(re.findall(r'\bDIR_(?:HOSTS|HOOKS|SCRIPTS)_[A-Z_]+\b', text)):
                if variable not in directories:
                    raise ValueError(f'undeclared path variable {variable} in {script.relative_to(SEED)}')
            for variable, leaf in reference.findall(text):
                if variable not in directories or not payload_source(SEED / directories[variable] / leaf).exists():
                    raise ValueError(f'missing literal payload {variable}/{leaf} in {script.relative_to(SEED)}')
    for p in paths:
        rel = p.relative_to(SEED).as_posix()
        if (rel.startswith('scripts/') and (p.name.endswith('.sh') or p.name.endswith('.sh.tmpl'))) or p.suffix == '.env':
            q = subprocess.run(['/bin/sh', '-n', str(p)], capture_output=True, text=True)
            if q.returncode:
                raise ValueError(f'shell syntax error in {rel}: {q.stderr.strip()}')
    mapping = SEED / 'classes/configs/target-assets.tsv'
    keys: set[tuple[str, str, str]] = set()
    for number, line in enumerate(mapping.read_text().splitlines(), 1):
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 4:
            raise ValueError(f'malformed hardware mapping line {number}')
        group, kind, destination, source = fields
        key = (group, kind, destination)
        if key in keys:
            raise ValueError(f'duplicate hardware mapping: {key}')
        keys.add(key)
        for name in (destination, source):
            if not SAFE_PATH.fullmatch(name) or '..' in Path(name).parts or name.startswith('/'):
                raise ValueError(f'unsafe hardware mapping: {key}')
        if not (SEED / 'hooks/target' / source).is_file():
            raise ValueError(f'hardware mapping has no payload: {source}')
    # Class metadata must not refer to a fragment belonging to the other repo.
    group_source: dict[str, str] = {}
    records = []
    for p in sorted((SEED / 'classes/configs').glob('*.cfg')):
        for stanza in re.split(r'\n\s*\n', p.read_text()):
            fields = {}
            for line in stanza.splitlines():
                if ': ' in line and not line.startswith('#'):
                    k, v = line.split(': ', 1)
                    fields[k] = v
            if fields:
                records.append(fields)
            if fields.get('Type') == 'group':
                group_source[fields['Name']] = fields['Source']
    for fields in records:
        if fields.get('Type') != 'class':
            continue
        group, name = fields['Group'], fields['Name']
        source = group_source[group]
        if source in {'class-auto', 'class-select'}:
            path = SEED / 'classes' / source / group / f'{name}.cfg'
        else:
            path = SEED / 'classes' / source / f'{name}.cfg'
        if not path.is_file():
            raise ValueError(f'class metadata has no fragment: {path.relative_to(SEED)}')
        helper = fields.get('LateHelper')
        if helper and not payload_source(SEED / 'scripts/late' / (helper + '.sh')).is_file():
            raise ValueError(f'class helper missing: {helper}')
        if group == 'profile':
            if not (SEED / 'hosts/profiles' / f'{name}.env').is_file():
                raise ValueError(f'profile class has no environment: {name}')
    other = 'server' if role == 'desktop' else 'desktop'
    if (SEED / 'classes/class-select/role' / f'{other}.cfg').exists():
        raise ValueError('opposite role leaked into this repository')

def validate_iocost_profiles() -> None:
    """Validate literal profile data using the exact target-side scalar policy."""
    helper = SEED / 'scripts/late/iocost.sh'
    for profile in sorted((SEED / 'hosts/profiles').glob('*.env')):
        values = {}
        for line in profile.read_text().splitlines():
            if not line.startswith(('IOCOST_', 'IO_COST_')):
                continue
            match = re.fullmatch(r'([A-Z0-9_]+)="([^"\\$`\x00-\x1f\x7f]*)"', line)
            if not match or match[1] in values:
                raise ValueError(f'{profile.name}: malformed or duplicate IOCost input')
            values[match[1]] = match[2]
        result = subprocess.run(['/bin/sh', '-eu', '-c', '. "$1"; iocost_placeholder_map',
                                 'iocost-profile-check', str(helper)],
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', **values},
                                text=True, capture_output=True, timeout=15)
        if result.returncode or set(values) != {line.split('=', 1)[0] for line in result.stdout.splitlines()}:
            raise ValueError(f'{profile.name}: invalid IOCost policy: {result.stderr.strip()}')

def validate_systemd_profiles() -> None:
    helper = SEED / 'scripts/late/templates.sh'
    for profile in sorted((SEED / 'hosts/profiles').glob('*.env')):
        values = {}
        for line in profile.read_text().splitlines():
            if not line.startswith(('SYSTEMD_', 'TMPFS_VAR_LOG=')):
                continue
            match = re.fullmatch(r'([A-Z0-9_]+)="([^"\\$`\x00-\x1f\x7f]*)"', line)
            if not match or match[1] in values:
                raise ValueError(f'{profile.name}: malformed or duplicate systemd policy')
            values[match[1]] = match[2]
        result = subprocess.run(['/bin/sh', '-eu', '-c',
            'installer_fatal() { printf "%s\\n" "$*" >&2; return 1; }; . "$1"; systemd_resource_placeholder_map',
            'systemd-profile-check', str(helper)],
            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', **values},
            text=True, capture_output=True, timeout=15)
        if result.returncode:
            raise ValueError(f'{profile.name}: invalid systemd policy: {result.stderr.strip()}')

def validate_obsidian_git_profiles() -> None:
    """Reject an absent, duplicate or ambiguous automation flag before publication."""
    for profile in sorted((SEED / 'hosts/profiles').glob('*.env')):
        rows = [line for line in profile.read_text().splitlines()
                if re.match(r'^\s*OBSIDIAN_GIT_AUTO_ENABLE\b', line)]
        if len(rows) != 1 or not re.fullmatch(r'OBSIDIAN_GIT_AUTO_ENABLE="(?:true|false)"', rows[0]):
            raise ValueError(f'{profile.name}: OBSIDIAN_GIT_AUTO_ENABLE must be exactly one quoted true/false assignment')

def validate_browser_repository_profiles() -> None:
    """Every profile uses the same SSH checkout contract, with no commit pin."""
    expected = {'BROWSER_NETSCAPE_REPOSITORY_URL': 'git@gitlab.com:core-assets/helpers/netscape.git',
                'BROWSER_NETSCAPE_REPOSITORY_BRANCH': 'mcr/main',
                'BROWSER_NETSCAPE_DIRECTORY': 'Workspace/netscape'}
    profiles = sorted((SEED / 'hosts/profiles').glob('*.env'))
    if not profiles:
        raise ValueError('no desktop profiles available for browser repository validation')
    for profile in profiles:
        values = {}
        for line in profile.read_text().splitlines():
            if not re.match(r'^\s*(?:export\s+)?BROWSER_NETSCAPE_', line):
                continue
            match = re.fullmatch(r'(BROWSER_NETSCAPE_[A-Z_]+)="([^"\\$`\x00-\x1f\x7f]*)"', line)
            if not match or match[1] in values:
                raise ValueError(f'{profile.name}: malformed or duplicate browser repository assignment')
            values[match[1]] = match[2]
        if values != expected:
            raise ValueError(f'{profile.name}: unapproved browser repository, branch or checkout policy')

def validate_tomat_profiles() -> None:
    """Reject absent/unsafe bootstrap pins before publishing any installer files."""
    required = {"SOFTWARE_TOMAT_TAG", "SOFTWARE_TOMAT_URL", "SOFTWARE_TOMAT_SHA256"}
    profiles = sorted((SEED / "hosts/profiles").glob("*.env"))
    if not profiles:
        raise ValueError("no desktop profiles available for Tomat pin validation")
    for profile in profiles:
        values = {}
        for line in profile.read_text().splitlines():
            if not re.match(r"\s*(?:export\s+)?SOFTWARE_TOMAT_", line):
                continue
            match = re.fullmatch(r'([A-Z0-9_]+)="([^"\\$`\x00-\x1f\x7f]*)"', line)
            if not match or match[1] in values or match[1] not in required:
                raise ValueError(f"{profile.name}: malformed, duplicate or unknown Tomat pin")
            values[match[1]] = match[2]
        if set(values) != required:
            raise ValueError(f"{profile.name}: missing Tomat tag, URL or SHA-256")
        tag = values["SOFTWARE_TOMAT_TAG"]
        match = re.fullmatch(r"v([0-9]+\.[0-9]+\.[0-9]+)", tag)
        if not match or len(match[1]) > 32:
            raise ValueError(f"{profile.name}: invalid Tomat release tag")
        expected_url = (r"https://github\.com/jolars/tomat/releases/download/" + re.escape(tag)
                        + r"/tomat_" + re.escape(match[1]) + r"-[1-9][0-9]{0,8}_amd64\.deb")
        if not re.fullmatch(expected_url, values["SOFTWARE_TOMAT_URL"]):
            raise ValueError(f"{profile.name}: Tomat URL does not match its tag and amd64 asset")
        if not re.fullmatch(r"[0-9a-f]{64}", values["SOFTWARE_TOMAT_SHA256"]):
            raise ValueError(f"{profile.name}: invalid Tomat SHA-256")

def validate_dns_policy() -> None:
    """Validate the public map and ordered endpoints without network probes."""
    result = subprocess.run(['/bin/sh', '-eu', '-c',
                             '. "$1"; . "$2"; . "$3"; app_veth_dns_placeholder_map', 'dns-policy',
                             str(SEED / 'hosts/installer/identity.env'),
                             str(SEED / 'scripts/common/modules/app-veth-identity.sh'),
                             str(SEED / 'scripts/late/security.sh')],
                            capture_output=True, timeout=15, check=True,
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
    helper = runpy.run_path(str(SEED / 'scripts/late/stubby-config.py'), run_name='stubby_policy')
    helper['parse_policy'](result.stdout)

def verify_lifecycle_helpers() -> None:
    begin, end = '# BEGIN EMBEDDED LIFECYCLE\n', '# END EMBEDDED LIFECYCLE\n'
    canonical = (SEED / 'scripts/common/lifecycle.sh').read_text()
    source = SEED / 'scripts/common/source.sh'
    text = source.read_text()
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError('invalid lifecycle embedding markers: scripts/common/source.sh')
    embedded = text.split(begin, 1)[1].split(end, 1)[0]
    if embedded != canonical:
        raise ValueError('stale lifecycle embedding: update scripts/common/source.sh from lifecycle.sh')


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        refuse_private_inputs()
        subprocess.run([resolve_python_interpreter(), '-I', '-B',
                        str(ROOT / 'tools/check_resctl_bench.py')], check=True)
        runpy.run_path(str(ROOT / 'tools/check_modules.py'))['check'](SEED)
        validate_iocost_profiles()
        validate_systemd_profiles()
        validate_obsidian_git_profiles()
        validate_browser_repository_profiles()
        validate_tomat_profiles()
        runpy.run_path(str(ROOT / 'tools/check_network_sharing.py'))['check'](SEED)
        validate_dns_policy()
        subprocess.run([resolve_python_interpreter(), '-I', '-B',
                        str(ROOT / 'tools/check_browser_policies.py')], check=True)
        verify_lifecycle_helpers()
        validate(payload_files())
        products = build()
        stale = [name for name, data in products.items()
                 if not (SEED / name).is_file() or (SEED / name).read_bytes() != data]
        if stale:
            raise ValueError('stale generated files; run make build: ' + ', '.join(stale))
        print('installer source and three generated products are current')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('build validation failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
