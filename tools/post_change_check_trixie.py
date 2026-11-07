#!/usr/bin/env python3
"""Static changed-file and payload checks for d-i/trixie-server only.

This checker deliberately ignores unrelated Forky working-tree changes. It
does not execute installer code, load policy, contact services, or provision an
environment. The Trixie payload manifest uses versioned byte sizes, SHA-256
digests and paths, plus an archive digest.
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
    b'zsh', b'xwayland',
    b'/var/cache/ci/', b'/var/lib/ci/', b'/var/cache/bazel/', b'/var/lib/bazel/',
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
    forbidden_target_tokens = (
        'waybar', 'labwc', 'greetd', 'xwayland', 'thunar', 'sway', 'wofi',
        'fuzzel', 'mako', 'cage', 'gnome', 'kde', 'xfce', 'lxde', 'mate',
        'cinnamon',
    )
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
        target_name = fields[3].lower()
        if any(token in target_name.split('/') for token in forbidden_target_tokens):
            raise ValueError(f'Trixie target asset names a desktop component: {fields[3]}')


def check_forky_bridge_lists() -> None:
    payload_list = SEED / 'forky-payload.list'

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
    forky_root = ROOT / 'd-i/forky'
    zram_entries = {'scripts/late/zram-swap.sh'}
    zram_entries.update(
        path.relative_to(forky_root).as_posix()
        for path in (forky_root / 'hooks/target').rglob('*')
        if path.is_file() and 'zram' in path.as_posix().lower()
    )
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
        raise ValueError(f'ZRAM Perl modules are absent from the embedded Forky ZRAM set: {missing}')


def check_payload_products() -> int:
    archive_path, manifest_path, preseed_path = (SEED / name for name in GENERATED)
    if not all(path.is_file() and not path.is_symlink() for path in (archive_path, manifest_path, preseed_path)):
        raise ValueError('Trixie build products are missing; run make build-trixie')
    entries: dict[str, tuple[int, str]] = {}
    lines = manifest_path.read_text(encoding='utf-8').splitlines()
    if (len(lines) < 4 or lines[0] != 'format=2'
            or not lines[1].startswith('archive_sha256=')
            or len(lines[1].split('=', 1)[1]) != 64
            or lines[2] != 'format_description=size<TAB>sha256<TAB>path'):
        raise ValueError('Trixie payload manifest header is invalid')
    archive_digest = lines[1].split('=', 1)[1]
    if any(character not in '0123456789abcdef' for character in archive_digest):
        raise ValueError('Trixie payload archive digest is invalid')
    for line in lines[3:]:
        fields = line.split('\t')
        if len(fields) != 3:
            raise ValueError(f'invalid Trixie payload manifest row: {line!r}')
        size, digest, name = fields
        if (not size.isdigit() or len(digest) != 64
                or any(character not in '0123456789abcdef' for character in digest)
                or not name or name.startswith('/') or '..' in name.split('/')
                or len(name) > 240 or len(name.split('/')) > 32):
            raise ValueError(f'invalid Trixie payload manifest row: {line!r}')
        if name in entries:
            raise ValueError(f'duplicate Trixie payload manifest row: {name}')
        entries[name] = (int(size), digest)
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        actual: dict[str, tuple[int, str]] = {}
        expanded = 0
        for member in members:
            if (not member.isfile() or member.name.startswith('/')
                    or '..' in member.name.split('/') or len(member.name) > 240
                    or len(member.name.split('/')) > 32 or member.size > 16777216):
                raise ValueError(f'unsafe Trixie payload member: {member.name}')
            if member.name in actual:
                raise ValueError(f'duplicate Trixie payload archive member: {member.name}')
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f'cannot read Trixie payload member: {member.name}')
            data = stream.read(16777217)
            if len(data) != member.size or len(data) > 16777216:
                raise ValueError(f'Trixie payload member exceeds its limit: {member.name}')
            expanded += len(data)
            if expanded > 268435456:
                raise ValueError('Trixie payload expanded-byte limit exceeded')
            import hashlib
            actual[member.name] = (member.size, hashlib.sha256(data).hexdigest())
    if actual != entries:
        raise ValueError('Trixie payload archive and manifest differ')
    import hashlib
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != archive_digest:
        raise ValueError('Trixie payload archive digest differs from manifest')
    return len(entries)


def check_contracts() -> None:
    source = (SEED / 'scripts/common/source.sh').read_text(encoding='utf-8')
    preseed = (SEED / 'preseed.cfg.tmpl').read_text(encoding='utf-8')
    for required in (
        'scripts/common/source.sh', 'payload.manifest',
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
    for installer_env in ('boot.env', 'layout.env', 'btrfs.env', 'f2fs.env'):
        forky_env = ROOT / 'd-i/forky/hosts/installer' / installer_env
        trixie_env = SEED / 'hosts/installer' / installer_env
        if forky_env.read_bytes() != trixie_env.read_bytes():
            raise ValueError(f'Trixie installer environment diverges from Forky: {installer_env}')
    gui_package_prefixes = (
        'waybar', 'labwc', 'greetd', 'xwayland', 'thunar', 'sway',
        'wofi', 'fuzzel', 'mako', 'cage', 'gnome-', 'kde-', 'xfce-',
    )
    package_fragments = [SEED / 'fragments/apt.cfg']
    package_fragments.extend((SEED / 'classes').rglob('*.cfg'))
    for fragment in package_fragments:
        for line in fragment.read_text(encoding='utf-8').splitlines():
            fields = line.split()
            if len(fields) < 4 or fields[:3] != ['d-i', 'pkgsel/include', 'string']:
                continue
            packages = fields[3:]
            if any(package == prefix or package.startswith(prefix) for package in packages for prefix in gui_package_prefixes):
                raise ValueError(f'Trixie package fragment selects a desktop package: {fragment.relative_to(ROOT)}')
    identity = (SEED / 'hosts/installer/identity.env').read_text(encoding='utf-8')
    if 'SYSTEM_PREFIX="LPL"' not in identity:
        raise ValueError('Trixie identity prefix must be LPL')
    if any(key in identity for key in ('HOST_IDENTITY_SOURCE=', 'HOSTNAME_SOURCE=', 'DOMAIN_SOURCE=', 'PRIMARY_USERNAME_SOURCE=')):
        raise ValueError('Trixie identity contains metadata absent from Forky identity.env')
    def parse_values(path: Path) -> dict[str, str]:
        values = {}
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key] = value.strip().strip('"')
        return values

    shared_values = parse_values(SEED / 'hosts/profiles/shared-srv.env')
    expected_subids = (
        f"github-runner:{shared_values.get('CI_RUNNER_GITHUB_SUBUID', '')}",
        f"gitlab-runner:{shared_values.get('CI_RUNNER_GITLAB_SUBUID', '')}",
    )
    for name in ('subuid', 'subgid'):
        path = SEED / 'hooks/target/etc' / name
        lines = tuple(line for line in path.read_text(encoding='utf-8').splitlines() if line)
        if lines != expected_subids:
            raise ValueError(f'CI {name} mapping does not match the Trixie profile')

    filen_keys = (
        'FILEN_CLI_PRIV_ENABLE', 'FILEN_CLI_OFFSEC_ENABLE',
        'FILEN_CLI_PRIV_SYNC_MODE', 'FILEN_CLI_OFFSEC_SYNC_MODE',
    )
    filen_modes = {'twoWay', 'localToCloud', 'cloudToLocal', 'localBackup', 'cloudBackup'}
    for profile in sorted((SEED / 'hosts/profiles').glob('*.env')):
        if profile.name == 'shared-srv.env':
            continue
        values = parse_values(profile)
        if any(key not in values for key in filen_keys):
            raise ValueError(f'FILEN profile switches are incomplete: {profile.name}')
        if any(values[key] not in {'true', 'false'} for key in filen_keys[:2]):
            raise ValueError(f'FILEN profile enable switch is invalid: {profile.name}')
        if any(values[key] not in filen_modes for key in filen_keys[2:]):
            raise ValueError(f'FILEN profile sync mode is invalid: {profile.name}')

    hardware_profiles = {
        'btrfs-srv-flex.env': '79-ideapad-acpi.conf',
        'btrfs-srv-flex-duo.env': '79-ideapad-acpi.conf',
        'f2fs-srv-hp14.env': '79-chromebook.conf',
    }
    server_install = (SEED / 'scripts/late/server-install.sh').read_text(encoding='utf-8')
    if 'SYSTEM_HARDWARE_SPEC' not in server_install or 'install_device_asset' not in server_install:
        raise ValueError('Trixie server installer does not wire profile hardware assets')
    if '81-labwc-thinkpad-backlight.rules' in server_install:
        raise ValueError('Trixie server installer still stages the Labwc backlight hook')
    for profile_name, expected in hardware_profiles.items():
        values = parse_values(SEED / 'hosts/profiles' / profile_name)
        if values.get('SYSTEM_HARDWARE_SPEC') != expected:
            raise ValueError(f'{profile_name} selects the wrong SYSTEM_HARDWARE_SPEC')
        if not (SEED / 'hooks/target/etc/modprobe.d' / expected).is_file():
            raise ValueError(f'missing hardware asset for {profile_name}: {expected}')
    gitlab_template = (SEED / 'hooks/target/etc/system-config/ci-runners/gitlab/config.toml.tmpl').read_text(encoding='utf-8')
    if 'RUNNER_TOKEN' in gitlab_template or '@RUNNER_TOKEN@' in gitlab_template:
        raise ValueError('GitLab runner template contains a registration token placeholder')
    shared = parse_values(SEED / 'hosts/profiles/shared-srv.env')
    image = shared.get('CI_GITLAB_RUNNER_IMAGE', '')
    if '@sha256:' not in image or not image.startswith('docker.io/library/'):
        raise ValueError('GitLab image policy is not an immutable approved image')
    for podman_config in (SEED / 'hooks/target/etc/system-config/ci-runners/podman').glob('*/containers.conf'):
        podman_text = podman_config.read_text(encoding='utf-8')
        if 'allow_host_loopback' in podman_text or 'host.containers.internal' in podman_text:
            raise ValueError(f'runner Podman config exposes host loopback: {podman_config.name}')
    registration = (SEED / 'hooks/target/usr/local/libexec/ci-register').read_text(encoding='utf-8')
    if 'mktemp "$registration_stage/.registration.XXXXXX"' not in registration:
        raise ValueError('GitLab registration does not use the protected staging directory')
    gitlab_tmpfiles = (SEED / 'hooks/target/etc/tmpfiles.d/90-ci-gitlab.conf').read_text(encoding='utf-8')
    if '/run/ci-runners/gitlab-registration 0750 root gitlab-runner' not in gitlab_tmpfiles:
        raise ValueError('GitLab registration staging directory is not in the class tmpfiles policy')
    gitlab_unit = (SEED / 'hooks/target/etc/systemd/system/ci-gitlab-register.service').read_text(encoding='utf-8')
    if 'ExecStartPre=/usr/bin/install -d' in gitlab_unit:
        raise ValueError('GitLab registration unit mutates its runtime directory at start')


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
