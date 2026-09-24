#!/usr/bin/env python3
"""Build the pinned installer snapshot and its generated preseed entry point.

Run from any directory. Python 3.11+ standard library only. --check detects
unpublished edits without changing files. The generated payload deliberately
excludes preseed.cfg, so hashes do not form a circular dependency.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import os
import tempfile
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'd-i/forky'
GENERATED = {'preseed.cfg', 'payload.tar.gz', 'payload.manifest'}
EXCLUDED_DIRS = {'tests', '__pycache__', '.git', '.pytest_cache'}
SAFE_PATH = re.compile(r'[A-Za-z0-9_./@+-]+\Z')

def resolve_python_interpreter() -> str:
    candidate = sys.executable or shutil.which('python3')
    if not candidate:
        raise ValueError('building browser configuration requires a Python 3 interpreter')
    path = Path(candidate)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f'unsafe Python interpreter path: {candidate!r}')
    return str(path)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

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

def payload_files() -> list[Path]:
    paths = []
    for p in sorted(SEED.rglob('*')):
        rel = p.relative_to(SEED)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if str(rel) in GENERATED:
            continue
        if p.is_symlink():
            raise ValueError(f'symlinks cannot be published: {rel}')
        if not p.is_file():
            continue
        if not SAFE_PATH.fullmatch(rel.as_posix()):
            raise ValueError(f'unsupported payload path: {rel}')
        paths.append(p)
    if not paths:
        raise ValueError('empty repository')
    return paths

def payload_source(path: Path) -> Path:
    template = path.with_name(path.name + '.tmpl')
    if path.exists() and template.exists():
        raise ValueError(f'ambiguous plain/template payload: {path}')
    return template if template.is_file() else path

def validate(paths: list[Path]) -> None:
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

def generate_preseed(archive_sha: str, manifest_sha: str, source_sha: str) -> bytes:
    source = (SEED / 'scripts/common/source.sh').read_text()
    core = source.split('# BEGIN BOOTSTRAP CORE\n', 1)[1].split('# END BOOTSTRAP CORE', 1)[0]
    # Every core shell statement has an explicit delimiter; newlines are layout
    # only. The syntax check here catches an accidental non-embeddable edit.
    core = ' '.join(line.strip() for line in core.splitlines() if line.strip() and not line.lstrip().startswith('#'))
    # The debconf RFC822 backend decodes literal \n when reloading a value;
    # GET then truncates multiline replies. Octal LF escapes preserve identical
    # printf/awk/tr behavior without corrupting a generated command on reload.
    # The source files keep readable escapes; only the embedded copy is encoded.
    core = core.replace(r'\n', r'\012')
    command = ('set -eu; umask 077; ' + core +
        ' installer_lifecycle_arm preflight; base=$(source_resolve_seed) || exit "$?"; '
        'boot=${INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}/bootstrap; '
        'cached_hash=; if [ -f "$boot/source.sh" ]; then cached_hash=$(source_hash <"$boot/source.sh"); fi; '
        f'if [ "${{cached_hash%% *}}" != {source_sha} ]; then '
        'source_transfer "$base" scripts/common/source.sh "$boot/source.sh" || exit 1; fi; '
        'actual=$(source_hash <"$boot/source.sh"); '
        f'[ "${{actual%% *}}" = {source_sha} ] || {{ source_error "transport checksum differs from preseed pin"; exit 1; }}; '
        '. "$boot/source.sh"; '
        f'source_bootstrap "$base" {archive_sha} {manifest_sha}; installer_lifecycle_complete')
    # Generate one logical command. The readable implementation lives in
    # scripts/common/source.sh; never hand-maintain its quoted bootstrap copy.
    quoted = shlex.quote(command)
    text = '''# Generated by tools/build.py. Edit sources, then rebuild before publishing.
# Repository execution is privileged: only boot from a trusted preseed source.
d-i debconf/priority select critical
d-i debconf/priority seen true
d-i clock-setup/utc boolean true
d-i clock-setup/utc seen true
d-i clock-setup/ntp boolean false
d-i clock-setup/ntp seen true

# Resolve the effective URL, validate the complete payload, then include local files.
'''
    # Do not split arbitrary tokens or shell quotes. A single long value is
    # valid debconf syntax and avoids a second escaping/continuation language.
    text += 'd-i preseed/include_command string /bin/sh -c ' + quoted + '\n\n'
    text += 'd-i preseed/run string file:///tmp/install-runtime/bootstrap/preseed-apply.sh\n\n'
    for question, phase in [('preseed/early_command', 'early'), ('partman/early_command', 'partman'), ('preseed/late_command', 'late')]:
        runner = ('set -eu; ' + core + f' installer_lifecycle_arm entry-{phase}; boot=${{INSTALLER_RUNTIME_DIR:-/tmp/install-runtime}}/bootstrap; '
                  '[ -f "$boot/preflight.ok" ] && [ -x "$boot/preseed-bootstrap-entry.sh" ] || '
                  '{ echo "fatal: installer repository preflight did not complete" >&2; exit 1; }; '
                  f'installer_run_supervised "$boot/preseed-bootstrap-entry.sh" {phase} /tmp/installer.log; installer_lifecycle_complete')
        text += f'd-i {question} string /bin/sh -c {shlex.quote(runner)}\n'
    # Validate every generated command at both shell boundaries before any
    # product is published. Parsing the readable source alone is insufficient.
    busybox = shutil.which('busybox')
    if not busybox:
        raise ValueError('building installer commands requires BusyBox for ash syntax checks')
    for line in text.splitlines():
        fields = line.split(None, 3)
        if len(fields) != 4 or not fields[1].endswith('_command'):
            continue
        value = fields[3]
        words = shlex.split(value)
        if len(words) != 3 or words[:2] != ['/bin/sh', '-c']:
            raise ValueError(f'malformed generated command: {fields[1]}')
        for shell in (['/bin/sh'], [busybox, 'sh']):
            for code in (value, words[2]):
                parsed = subprocess.run([*shell, '-n', '-c', code], capture_output=True, text=True)
                if parsed.returncode:
                    raise ValueError(f'invalid generated {fields[1]}: {parsed.stderr.strip()}')
    return text.encode()

def sync_apt_helpers(check: bool) -> None:
    begin = '# BEGIN EMBEDDED APT SOURCES\n'
    end = '# END EMBEDDED APT SOURCES\n'
    path = SEED / 'scripts/common/lib.sh'
    text = path.read_text()
    before, rest = text.split(begin, 1)
    _, after = rest.split(end, 1)
    expected = before + begin + (SEED / 'scripts/common/apt-sources.sh').read_text() + end + after
    if expected != text:
        if check:
            raise ValueError('stale APT source helper embedding')
        path.write_text(expected)

def sync_credential_helpers(check: bool) -> None:
    """Embed one canonical reader in early/standalone libs without boot deps."""
    begin = '# BEGIN EMBEDDED INITRD CREDENTIALS\n'
    end = '# END EMBEDDED INITRD CREDENTIALS\n'
    canonical = (SEED / 'scripts/common/credentials.sh').read_text()
    for name in ('scripts/common/lib.sh', 'scripts/runtime/common.sh'):
        path = SEED / name
        text = path.read_text()
        if text.count(begin) != 1 or text.count(end) != 1:
            raise ValueError(f'credential embedding markers invalid: {name}')
        before, rest = text.split(begin, 1)
        _, after = rest.split(end, 1)
        expected = before + begin + canonical + end + after
        if text == expected:
            continue
        if check:
            raise ValueError(f'stale embedded credentials in {name}; run tools/build.py')
        fd, temporary = tempfile.mkstemp(prefix='.credentials.', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(expected)
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

def sync_debconf_helpers(check: bool) -> None:
    begin, end = '# BEGIN EMBEDDED DEBCONF\n', '# END EMBEDDED DEBCONF\n'
    canonical = (SEED / 'scripts/common/debconf.sh').read_text()
    for name in ('scripts/common/lib.sh', 'scripts/runtime/common.sh'):
        path = SEED / name
        text = path.read_text()
        before, rest = text.split(begin, 1)
        _, after = rest.split(end, 1)
        expected = before + begin + canonical + end + after
        if text != expected:
            if check:
                raise ValueError(f'stale debconf embedding: {name}')
            path.write_text(expected)

def sync_lifecycle_helpers(check: bool) -> None:
    begin, end = '# BEGIN EMBEDDED LIFECYCLE\n', '# END EMBEDDED LIFECYCLE\n'
    canonical = (SEED / 'scripts/common/lifecycle.sh').read_text()
    for name in ('scripts/common/source.sh', 'scripts/common/lib.sh'):
        path = SEED / name
        text = path.read_text()
        before, rest = text.split(begin, 1)
        _, after = rest.split(end, 1)
        expected = before + begin + canonical + end + after
        if text != expected:
            if check:
                raise ValueError(f'stale lifecycle embedding: {name}')
            path.write_text(expected)

def build() -> dict[str, bytes]:
    paths = payload_files()
    validate(paths)
    manifest = ''.join(f'{sha(p.read_bytes())}  {p.relative_to(SEED).as_posix()}\n' for p in paths).encode()
    archive = io.BytesIO()
    with gzip.GzipFile(fileobj=archive, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as tf:
            for p in paths:
                data = p.read_bytes()
                info = tarfile.TarInfo(p.relative_to(SEED).as_posix())
                info.size = len(data)
                info.mode = 0o755 if p.stat().st_mode & 0o111 else 0o644
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                tf.addfile(info, io.BytesIO(data))
    payload = archive.getvalue()
    return {'payload.tar.gz': payload, 'payload.manifest': manifest,
            'preseed.cfg': generate_preseed(sha(payload), sha(manifest), sha((SEED / 'scripts/common/source.sh').read_bytes()))}

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
            if not line.startswith('SYSTEMD_'):
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

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if generated files are stale')
    args = parser.parse_args()
    try:
        refuse_private_inputs()
        # Run the target installer's policy on every profile before generating
        # ANY release products. Shell syntax alone cannot detect invalid pins.
        subprocess.run([resolve_python_interpreter(), '-I', '-B',
                        str(ROOT / 'tools/check_resctl_bench.py')], check=True)
        validate_iocost_profiles()
        validate_systemd_profiles()
        validate_tomat_profiles()
        subprocess.run([resolve_python_interpreter(), '-B', str(ROOT / 'tools/build_browser_config.py')] +
                       (['--check'] if args.check else []), check=True)
        sync_credential_helpers(args.check)
        sync_debconf_helpers(args.check)
        sync_lifecycle_helpers(args.check)
        sync_apt_helpers(args.check)
        products = build()
        stale = [name for name, data in products.items() if not (SEED / name).is_file() or (SEED / name).read_bytes() != data]
        if args.check:
            if stale:
                print('stale generated files; run python3 tools/build.py: ' + ', '.join(stale), file=sys.stderr)
                return 1
            print('snapshot, pins and preseed are current')
        else:
            for name, data in products.items():
                fd, temporary = tempfile.mkstemp(prefix='.' + name + '.', dir=SEED)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(temporary, 0o644)
                    os.replace(temporary, SEED / name)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            print(f'built {len(products["payload.manifest"].splitlines())} payload files; publish the complete repository atomically')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'build failed: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
