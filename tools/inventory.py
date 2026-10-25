#!/usr/bin/env python3
"""Manually inventory installer sources into one self-contained inventory.json.

Discovery reads checkout source as data. --refresh-apt acquires public repository
and declared download metadata, selects binaries under installer policy, and
attaches matching source archives. Requires Python 3.11 or newer for TOML data;
manual Python dependency acquisition also requires PyPA packaging >= 23.2.
No installer, package manager or downloaded code runs.
This developer tool must never be called by installation, builds or validation.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict, deque
from contextlib import contextmanager
import fcntl
import fnmatch
from functools import cmp_to_key
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'd-i/forky/'
SCHEMA = 4
GENERATOR_VERSION = 3
MAX_FILE = 16 * 1024**2
MAX_JSON = 128 * 1024**2
MAX_TOTAL = 256 * 1024**2
MAX_MEMBERS = 20000
MAX_EXPANSIONS = 128
MAX_FACTS = 250000
PRIVATE = {'preseed.env', 'git_ed25519', 'git_ed25519.pub', 'id_git_ed25519'}
BINARY = {'.png', '.jpeg', '.jpg', '.gif', '.ico', '.ttf', '.otf', '.woff',
          '.woff2', '.gz', '.xz', '.zip', '.deb', '.udeb', '.pdf', '.webp'}
SECRET = re.compile(r'(?i)(?:password|passwd|token|secret|credential|api_?key|access_?key|private_?key|passphrase)')
ASSIGN = re.compile(r'^\s*(?:export\s+|local\s+)?([A-Za-z_]\w*)=(.*)$')
DEBCONF = re.compile(r'^\s*(\S+)\s+(\S+)\s+(string|select|multiselect|boolean)\s+(.*?)\s*$')
URL = re.compile(r'(?:https?|ftp|ssh|git)://[^\s\x22\x27<>`]+|git@[A-Za-z0-9.-]+:[A-Za-z0-9_./+-]+')
ARCHIVE_URL = re.compile(r'\.(?:deb|udeb|dsc|rpm|whl|tar|tar\.gz|tgz|tar\.bz2|tbz2|tar\.xz|txz|tar\.zst|tzst|gz|bz2|xz|zst|zip|7z|jar|iso|img|bin|run|AppImage|msi|exe|gguf)(?:$|\?)', re.I)
VARIABLE = re.compile(r'\$\{([A-Za-z_]\w*)(?:(:-|-)([^{}]*))?\}|\$([A-Za-z_]\w*)')
PACKAGE = re.compile(r'[a-z0-9][a-z0-9+.-]*(?::(?:any|native|amd64|arm64))?(?:[=/][A-Za-z0-9.+:~_-]+)?\Z')
NETWORK = re.compile(r'(?i)\b(?:curl|wget|urlopen|download_file|fetch_url|source_transfer|source_http_get|'
                     r'git\s+(?:clone|fetch|checkout|switch)|managed_git_ssh_target_action|'
                     r'apt-get|anna-install|cscli\s+(?:hub|collections|parsers|scenarios|postoverflows|contexts|appsec-rules|appsec-configs)|'
                     r'cargo\s+install|rustup\s+(?:component|target|toolchain)|'
                     r'pipx?\s+install|npm\s+install|packer\s+init|podman\s+pull)\b')
INTEREST = re.compile(r'(?i)(?:url|uri|repository|branch|commit|revision|sha256|sha512|fingerprint|version|'
                      r'tag|architecture|target_triple|toolchain|kernel|packages|apt_deps|modules|apt_preferences|source_build|release|filename|minimum_bytes|maximum_bytes|_enable|'
                      r'wrangler_node_root|wrangler_node_requirement|wrangler_package_name|npm_integrity|node_[0-9]+_install_root)')
TRANSFER_COMMANDS = {'source_transfer', 'fetch_hook_file', 'bootstrap_source_module',
                     'installer_fetch_seed_path'}
CUDA_LEGACY_URL = 'https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/'
CUDA_LEGACY_OPTIONS = ('arch=amd64 trusted=yes allow-insecure=yes allow-weak=yes '
                       'allow-downgrade-to-insecure=yes check-valid-until=no check-date=no')


def archive_url(value: str) -> bool:
    return bool(ARCHIVE_URL.search(value))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def read_file(path: Path, limit: int = MAX_FILE) -> bytes:
    """Read bounded regular data without following any path component symlink."""
    if not path.is_absolute() or '..' in path.parts or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError('symlink input is not permitted: ' + path.name)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    directory = os.open(path.anchor, directory_flags)
    try:
        for component in path.parts[1:-1]:
            next_directory = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('input must be a bounded regular file: ' + path.name)
            data = stream.read(limit + 1)
            if file_identity(info) != file_identity(os.fstat(stream.fileno())) or len(data) != info.st_size:
                raise ValueError('input changed while reading: ' + path.name)
    finally:
        os.close(directory)
    if len(data) > limit:
        raise ValueError('input exceeds size limit: ' + path.name)
    return data


def file_identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('inventory JSON repeats a field')
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError('inventory JSON contains a nonfinite number')


EXCLUDED_DIRS = {'tests', 'backup', '__pycache__', '.git', '.pytest_cache'}
GENERATED = {'payload.tar.gz', 'payload.manifest', 'preseed.cfg'}


class DiscoveryBudget:
    def __init__(self):
        self.records = 0
        self.bytes = 0

    def consume(self, value):
        self.records += 1
        self.bytes += len(json.dumps(value, ensure_ascii=False).encode('utf-8'))
        if self.records > MAX_FACTS or self.bytes > MAX_JSON:
            raise ValueError('aggregate source discovery limit exceeded')


class Facts(list):
    def __init__(self, budget):
        super().__init__()
        self.budget = budget

    def append(self, value):
        self.budget.consume(value)
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)


def checkout_paths(root: Path) -> list[Path]:
    """Bound traversal before allocating lists; never follow source symlinks."""
    seed = root / PREFIX.rstrip('/')
    todo, files, entries = [seed], [], 0
    while todo:
        directory = todo.pop()
        if directory.is_symlink() or directory.resolve(strict=True) != directory:
            raise ValueError('source directory must not be a symlink')
        with os.scandir(directory) as children:
            for entry in children:
                entries += 1
                if entries > MAX_MEMBERS:
                    raise ValueError('checkout entry limit exceeded')
                if entry.name in EXCLUDED_DIRS or entry.name in PRIVATE:
                    continue
                path = Path(entry.path)
                if entry.is_symlink():
                    raise ValueError('source symlink is not permitted')
                if entry.is_dir(follow_symlinks=False):
                    todo.append(path)
                elif entry.is_file(follow_symlinks=False):
                    if path.parent == seed and path.name in GENERATED:
                        continue
                    staged_theme = path.is_relative_to(seed / 'assets/desktop-themes')
                    if not staged_theme and (path.suffix.lower() in BINARY or path.name.endswith(('.md', '.md.tmpl'))):
                        continue
                    files.append(path)
                else:
                    raise ValueError('nonregular checkout source is not permitted')
    return sorted(files)


def scan_checkout(root: Path) -> tuple[dict, dict, dict]:
    """Scan live installer inputs, without extracting, importing or sourcing."""
    scans, identities, observed, total, fingerprint = {}, {}, {}, 0, hashlib.sha256()
    paths = checkout_paths(root)
    budget = DiscoveryBudget()
    for path in paths:
        before = file_identity(path.lstat())
        data = read_file(path)
        if before != file_identity(path.lstat()):
            raise ValueError('checkout source changed during discovery')
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError('aggregate checkout source byte limit exceeded')
        name = path.relative_to(root).as_posix()
        identities[name] = before
        checksum = hashlib.sha256(data)
        observed[name] = {'bytes': len(data), 'sha256': checksum.hexdigest()}
        fingerprint.update(name.encode() + b'\0' + checksum.digest())
        if re.match(rb'\s*-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----', data[:256]):
            raise ValueError('private key is not an inventory input')
        if path.suffix.lower() in BINARY or b'\0' in data:
            continue
        try:
            source = data.decode('utf-8')
        except UnicodeDecodeError:
            continue
        scans[name] = scan_file(name, source, budget)
    if not scans:
        raise ValueError('installer source tree is empty')
    manifest = scans.get(PREFIX + 'assets/desktop-themes/sources.json', {}).get('manifest_files', [])
    staged = scans.get(PREFIX + 'scripts/desktop/desktop-theme-assets.list', {}).get('constants', {}).get('STAGED_THEME_FILES')
    if manifest or staged is not None:
        if staged is None or set(staged) != {item['asset_path'] for item in manifest}:
            raise ValueError('desktop theme manifest and installer staging list differ')
        for item in manifest:
            actual = observed.get(PREFIX + 'assets/desktop-themes/' + item['asset_path'])
            if actual != {key: item[key] for key in ('bytes', 'sha256')}:
                raise ValueError('staged desktop theme source differs from its pinned manifest')
    stamp = {'path': PREFIX.rstrip('/'), 'sha256': fingerprint.hexdigest(), 'files': len(paths)}
    return scans, stamp, identities


def unchanged_checkout(root: Path, identities: dict) -> bool:
    paths = checkout_paths(root)
    return ({path.relative_to(root).as_posix(): file_identity(path.lstat()) for path in paths}
            == identities)


def clean_url(value: str) -> str:
    """Keep stable public query parameters, never credentials or signed queries."""
    value = value.rstrip('.,;)]')
    if value.startswith('git@'):
        return value
    try:
        parts = urlsplit(value)
        if not parts.hostname or parts.username or parts.password:
            return '[credential-bearing or malformed URL omitted]'
        query = []
        for item in parts.query.split('&') if parts.query else []:
            key, equal, val = item.partition('=')
            query.append(key + equal + ('[redacted]' if SECRET.search(key) or key.lower().startswith('x-amz-') else val))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '&'.join(query), ''))
    except ValueError:
        return '[malformed URL omitted]'


def safe_text(value: str) -> str:
    value = URL.sub(lambda m: clean_url(m.group()), value)
    value = re.sub(r'(?i)\b(\w*(?:PASSWORD|TOKEN|SECRET|CREDENTIAL|PASSPHRASE)\w*\s*=)\s*(?:\x22[^\x22]*\x22|\x27[^\x27]*\x27|[^\s;]+)',
                   r'\1[redacted]', value)
    value = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*', 'Bearer [redacted]', value)
    return value[:4096]


def logical_lines(text: str):
    start, pieces = 1, []
    for number, line in enumerate(text.splitlines(), 1):
        if not pieces:
            start = number
        line = line.rstrip()
        more = line.endswith('\\')
        pieces.append(line[:-1] if more else line)
        if not more:
            yield start, ' '.join(pieces)
            pieces = []
    if pieces:
        yield start, ' '.join(pieces)


def scalar(value: str) -> str | None:
    """Read shell scalar syntax as data; command substitutions remain unresolved."""
    value = value.strip()
    if value.startswith(('\x22', '\x27')):
        quote = value[0]
        end = value.rfind(quote)
        if end > 0 and (not value[end + 1:].strip() or value[end + 1:].lstrip().startswith('#')):
            return value[1:end]
        return None
    value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
    if re.search(r'\s|[;|&]', value):
        return None
    return value


def paragraphs(text: str):
    fields, start = {}, 1
    for n, line in enumerate(text.splitlines() + [''], 1):
        if not line.strip():
            if fields:
                yield start, fields
            fields, start = {}, n + 1
        elif line.startswith((' ', '\t')) and fields:
            last = next(reversed(fields))
            fields[last] += ' ' + line.strip()
        elif not line.lstrip().startswith('#') and ':' in line:
            key, value = line.split(':', 1)
            fields[key.strip()] = value.strip()


def context(name: str) -> dict:
    parts = PurePosixPath(name.removeprefix(PREFIX)).parts
    if parts[:2] == ('hosts', 'profiles'):
        return {'profile': PurePosixPath(name).stem}
    if parts[:1] == ('classes',) and len(parts) >= 3:
        group = {'class-apps': 'apps', 'class-addon': 'addon'}.get(parts[1])
        if group:
            return {'class': group + '/' + PurePosixPath(name).stem}
        if parts[1] in {'class-auto', 'class-select'} and len(parts) == 4:
            return {'class': parts[2] + '/' + PurePosixPath(name).stem}
    if '/backup/' in name:
        return {'phase': 'inactive_backup'}
    if '/scripts/firstboot/' in name:
        return {'phase': 'first_boot'}
    if '/scripts/desktop/' in name:
        return {'class': 'role/desktop', 'phase': 'late'}
    if name.endswith('/scripts/late/tor-browser.sh'):
        return {'class': 'addon/software', 'phase': 'late'}
    if name.endswith('/scripts/late/mullvad.sh'):
        return {'class': 'apps/mullvad', 'phase': 'late'}
    match = re.search(r'/scripts/late/(devops|software|whisper|ch341a|qemu|crowdsec|tailscale|cuda-legacy)(?:[./-])', name)
    if match:
        return {'class': 'addon/' + match[1], 'phase': 'late'}
    if '/scripts/late/' in name or name.endswith('/hooks/installer/late_command.sh'):
        return {'phase': 'late'}
    if '/hooks/installer/pre-pkgsel.d/' in name:
        return {'phase': 'pre_pkgsel'}
    if '/hooks/target/' in name:
        return {'phase': 'installed_capability'}
    return {'phase': 'installation'}


def package_arguments(statement: str) -> list[dict]:
    if not re.search(r'\b(?:apt(?:-get)?|anna-install|(?:hook_)?(?:ensure|preload|try)_installer_\w+)\b', statement):
        return []
    # Commands are only tokenized, never evaluated or executed.
    try:
        lexer = shlex.shlex(statement, posix=True, punctuation_chars=';&|()<>')
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []
    return package_tokens(tokens)


def package_tokens(tokens: list[str]) -> list[dict]:
    """Read argv as data, retaining options that change download selection."""
    def option(options, setting):
        key, separator, value = setting.partition('=')
        if not separator:
            options['unresolved_options'] = True
        elif key == 'APT::Default-Release':
            options['target_release'] = value
        elif key in {'APT::Install-Recommends', 'APT::Install-Suggests'}:
            if value.lower() not in {'1', 'true', 'yes', 'on', '0', 'false', 'no', 'off'}:
                options['unresolved_options'] = True
            else:
                options[key.rsplit('::', 1)[-1].lower().replace('-', '_')] = value.lower() in {'1', 'true', 'yes', 'on'}
        elif key.startswith(('Dir::Etc::', 'Dir::State::', 'APT::Architecture', 'APT::Solver')):
            # A private source list, preferences file, architecture or solver
            # cannot silently inherit the default checkout repository policy.
            options['unresolved_options'] = True

    result = []
    for pos, token in enumerate(tokens):
        command = token.rsplit('/', 1)[-1]
        if command not in {'apt', 'apt-get'}:
            continue
        words = []
        for word in tokens[pos + 1:]:
            if word in {'||', '&&', ';', ')', 'then', '|'} or word.startswith(('>', '<')):
                break
            words.append(word)
        action = next((i for i, word in enumerate(words) if word in {'install', 'download'}), None)
        if action is None:
            continue
        if any(word in {'-s', '--simulate', '--dry-run', '--just-print', '--print-uris', '--no-act'} for word in words):
            continue
        options, arguments, index = {'operation': words[action]}, [], 0
        while index < len(words):
            word = words[index]
            index += 1
            if index - 1 == action:
                continue
            if word in {'-o', '-t', '--option', '--target-release', '-c', '--config-file'}:
                if index >= len(words):
                    options['unresolved_options'] = True
                    continue
                value = words[index]
                index += 1
                if word in {'-t', '--target-release'}:
                    options['target_release'] = value
                elif word in {'-o', '--option'}:
                    option(options, value)
                else:
                    options['unresolved_options'] = True
                continue
            if word.startswith(('--target-release=', '-t')) and word != '-t':
                options['target_release'] = word.partition('=')[2] if word.startswith('--') else word[2:]
            elif word == '--install-recommends':
                options['install_recommends'] = True
            elif word == '--no-install-recommends':
                options['install_recommends'] = False
            elif word == '--install-suggests':
                options['install_suggests'] = True
            elif word == '--no-install-suggests':
                options['install_suggests'] = False
            elif word in {'--download-only', '-d'}:
                options['download_only'] = True
            elif word.startswith(('-o', '--option=')):
                option(options, word[2:] if word.startswith('-o') else word.partition('=')[2])
            if word.startswith('-'):
                continue
            if index - 1 > action and (PACKAGE.fullmatch(word) or '$' in word or '`' in word):
                arguments.append(word)
        result.extend(dict(selector=word, type='deb', **options) for word in arguments)
    for pos, token in enumerate(tokens):
        if token in {'anna-install', 'hook_ensure_installer_udeb', 'hook_preload_installer_udeb', 'hook_try_installer_udeb'}:
            if pos + 1 < len(tokens) and PACKAGE.fullmatch(tokens[pos + 1]):
                result.append({'selector': tokens[pos + 1], 'type': 'udeb', 'operation': 'install'})
        elif token in {'hook_ensure_installer_command', 'hook_preload_installer_command', 'ensure_installer_command', 'ensure_installer_command_logged'}:
            if pos + 2 < len(tokens) and PACKAGE.fullmatch(tokens[pos + 2]):
                result.append({'selector': tokens[pos + 2], 'type': 'udeb', 'operation': 'install'})
    return unique(result)


def scan_file(name: str, text: str, budget=None) -> dict:
    if len(text) > MAX_FILE or text.count('\n') > 100000:
        raise ValueError('source parser size or line limit exceeded')
    budget = budget or DiscoveryBudget()
    facts = {key: Facts(budget) for key in (
        'variables', 'packages', 'settings', 'urls', 'operations', 'transfers',
        'pins', 'classes', 'sources', 'modules', 'plugins', 'collections', 'diagnostics', 'manifest_files')}
    facts.update(constants={}, references={})
    crowdsec_ssh_blocks = []
    if name == PREFIX + 'scripts/firstboot/assets/var/lib/firstboot/bin/crowdsec-firstboot.tmpl':
        for block in re.finditer(r'(?m)^  if \[ "\$CROWDSEC_SSH_SERVER_ENABLE" = true \]; then\n'
                                r'(?:(?!^  (?:if|else|elif|fi)\b)[\s\S])*?^  fi[ \t]*$', text):
            if crowdsec_ssh_blocks:
                raise ValueError('CrowdSec SSH profile source contains more than one guarded block')
            crowdsec_ssh_blocks.append((text.count('\n', 0, block.start()) + 1,
                                       text.count('\n', 0, block.end()) + 1))
    if name == PREFIX + 'assets/desktop-themes/sources.json':
        manifest = json.loads(text, object_pairs_hook=json_pairs, parse_constant=reject_constant)
        files = manifest.get('files') if isinstance(manifest, dict) else None
        if (not isinstance(files, dict) or manifest.get('schema') != 1 or not 0 < len(files) <= 256):
            raise ValueError('invalid staged desktop theme manifest')
        for path, fields in files.items():
            if (not isinstance(path, str) or not re.fullmatch(r'(?:gtk|qt|licenses)/[A-Za-z0-9._/+@-]{1,190}', path)
                    or '..' in path or '//' in path or not isinstance(fields, dict)
                    or type(fields.get('bytes')) is not int or not 0 < fields['bytes'] <= MAX_FILE
                    or not re.fullmatch(r'[a-f0-9]{64}', fields.get('sha256', ''))
                    or not isinstance(fields.get('url'), str) or not fields['url'].startswith('https://')
                    or clean_url(fields['url']) != fields['url'] or urlsplit(fields['url']).query):
                raise ValueError('invalid staged desktop theme file descriptor')
            facts['manifest_files'].append(dict(asset_path=path,
                **{key: fields[key] for key in ('url', 'bytes', 'sha256', 'commit') if key in fields}))
    if name == PREFIX + 'scripts/desktop/desktop-theme-assets.list':
        paths = text.splitlines()
        if not 0 < len(paths) <= 256 or len(paths) != len(set(paths)):
            raise ValueError('invalid desktop theme staging list')
        facts['constants']['STAGED_THEME_FILES'] = paths
    if name == PREFIX + 'scripts/common/modules/context-target.sh':
        match = re.search(r'(?m)^installer_cuda_source_line\(\) \(\n(.*?)^\)', text, re.S)
        if (match and '[ "$repository" = ' + CUDA_LEGACY_URL + ' ]' in match[1]
                and '[ "$suite" = / ] && [ -z "$components" ]' in match[1]
                and "printf 'deb [" + CUDA_LEGACY_OPTIONS + "] %s /\\n'" in match[1]):
            facts['constants']['CUDA_LEGACY_POLICY'] = {
                'mode': 'source-authorized-insecure', 'temporary': True,
                'options': CUDA_LEGACY_OPTIONS.split(),
                'source': ref(name, text[:match.start()].count('\n') + 1)}
    if name == PREFIX + 'scripts/desktop/xwayland.sh':
        # This adapter passes package/architecture/release as positional argv
        # into sh -c. Read its source table; do not interpret that shell or
        # confuse these private extractions with installed system packages.
        specs = re.search(r"(?m)^XWAYLAND_PRIVATE_DEPENDENCY_SPECS='\n([^']*)'\s*$", text)
        if not specs or len(specs[1]) > 8192:
            raise ValueError('private Xwayland dependency declaration is unavailable')
        words = specs[1].split()
        if not 0 < len(words) <= 64 or any(not re.fullmatch(
                r'[a-z0-9][a-z0-9+.-]*:[A-Za-z0-9_.+-]+', word) for word in words):
            raise ValueError('private Xwayland dependency declaration is invalid')
        line = text[:specs.start()].count('\n') + 1
        facts['packages'].extend({'selector': word.partition(':')[0] + ':${LABWC_XWAYLAND_ARCHITECTURE}',
                                  'type': 'deb', 'operation': 'download',
                                  'target_release': '$XWAYLAND_PRIVATE_DEPENDENCY_RELEASE',
                                  'line': line, 'via': 'private_xwayland_dependency_table',
                                  'purpose': 'private_extraction_for_Zoom_and_Discord'} for word in words)
    lines = list(logical_lines(text))
    for number, line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        assignment = ASSIGN.match(line)
        if assignment and SECRET.search(assignment[1]):
            continue
        for reference in re.finditer(r'\b[A-Z][A-Z0-9_]{2,}\b', line):
            key = reference[0]
            if SECRET.search(key) or assignment and key == assignment[1] and reference.start() < assignment.start(2):
                continue
            if key not in facts['references']:
                budget.consume({'reference': key, 'line': number})
                facts['references'][key] = number
            if len(facts['references']) > 10000:
                raise ValueError('source reference limit exceeded')
        if assignment and not SECRET.search(assignment[1]):
            value = scalar(assignment[2])
            if value is not None and len(value) <= 8192:
                # Private account data and arbitrary profile settings are not cached.
                if INTEREST.search(assignment[1]) or URL.search(value) or VARIABLE.search(value) or re.search(r'(?i)pkg|deps', assignment[1]):
                    facts['variables'].append({'name': assignment[1], 'value': safe_text(value), 'line': number})
                # Public package lists feed helpers that construct argv later
                # (for example Settings.packages in network-sharing.py).
                if re.search(r'(?:_APT_DEPS|_PACKAGES|_UDEBS)$', assignment[1]):
                    words = value.split()
                    if words and len(words) <= 256 and all(PACKAGE.fullmatch(word) for word in words):
                        kind = 'udeb' if assignment[1].endswith('_UDEBS') else 'deb'
                        facts['packages'].extend({'selector': word, 'type': kind, 'line': number,
                                                  'via': 'variable:' + assignment[1]} for word in words)
        match = DEBCONF.match(line)
        if match:
            owner, question, dtype, value = match.groups()
            if question.startswith(('mirror/', 'apt-setup/', 'pkgsel/', 'base-installer/', 'anna/')):
                facts['settings'].append({'question': question, 'value': safe_text(value), 'line': number})
            package_type = 'udeb' if question == 'anna/choose_modules' else 'deb'
            if question in {'pkgsel/include', 'base-installer/includes', 'base-installer/kernel/linux/extra-packages',
                            'base-installer/kernel/linux/initramfs-generators',
                            'base-installer/kernel/image', 'anna/choose_modules'}:
                for item in re.split(r'[\s,]+', value):
                    if item != 'none' and PACKAGE.fullmatch(item):
                        facts['packages'].append({'selector': item, 'type': package_type, 'line': number, 'via': question})
        for package in package_arguments(line):
            facts['packages'].append(dict(package, line=number, via='command'))
        for match in URL.finditer(line):
            facts['urls'].append({'url': clean_url(match.group()), 'line': number})
        if NETWORK.search(line):
            facts['operations'].append({'line': number, 'text': safe_text(stripped)})
        if name == PREFIX + 'scripts/desktop/waypaper.sh' and '/usr/bin/pipx' in line and ' install ' in line:
            tokens = shlex.split(line, comments=True)
            if tokens.count('/usr/bin/pipx') != 1 or tokens.count('/usr/bin/env') != 1:
                raise ValueError('Waypaper installer lacks one explicit pipx environment')
            start, command = tokens.index('/usr/bin/env'), tokens.index('/usr/bin/pipx')
            if start + 1 >= command or tokens[start + 1] != '-i':
                raise ValueError('Waypaper pipx environment is not cleared before installation')
            environment = {}
            for token in tokens[start + 2:command]:
                key, separator, value = token.partition('=')
                if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or key in environment:
                    raise ValueError('Waypaper pipx environment contains an ambiguous assignment')
                environment[key] = value
            arguments = tokens[command + 1:]
            if arguments and arguments[-1] == 'then':
                arguments.pop()
            if arguments != ['install', '--force', '--system-site-packages', '--python', '/usr/bin/python3', '$waypaper_wheel']:
                raise ValueError('Waypaper pipx arguments require a new download policy adapter')
            expected = {'PIP_CONFIG_FILE': '/dev/null', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
                        'PIP_NO_CACHE_DIR': '1', 'PIP_NO_INPUT': '1', 'PIP_ONLY_BINARY': ':all:',
                        'PYTHONNOUSERSITE': '1', 'PIPX_DEFAULT_PYTHON': '/usr/bin/python3',
                        'PATH': '/usr/local/bin:/usr/bin:/bin'}
            permitted = set(expected) | {'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME',
                                        'XDG_DATA_HOME', 'XDG_STATE_HOME', 'PIP_DEFAULT_TIMEOUT', 'PIP_RETRIES',
                                        'PIPX_HOME', 'PIPX_BIN_DIR', 'PIPX_MAN_DIR'}
            if (any(environment.get(key) != value for key, value in expected.items())
                    or set(environment) - permitted):
                raise ValueError('Waypaper pipx environment requires a new download policy adapter')
            if 'WAYPAPER_PIPX_CONTRACT' in facts['constants']:
                raise ValueError('Waypaper source declares more than one pipx installation')
            facts['constants']['WAYPAPER_PIPX_CONTRACT'] = dict(expected, line=number,
                index_url='https://pypi.org/simple/', arguments=arguments)
        # Repository-relative transfers are downloads during installation even
        # when the source base is a local mirror. Tokenize only; never expand
        # command substitutions or execute the helper.
        try:
            tokens = shlex.split(line, comments=True) if any(command in line for command in TRANSFER_COMMANDS) else []
        except ValueError:
            tokens = []
        for position, token in enumerate(tokens):
            command = token.lstrip('(')
            if command not in TRANSFER_COMMANDS or command.endswith('()'):
                continue
            if position and tokens[position - 1] == '-v':
                continue
            argument = tokens[position + 1] if position + 1 < len(tokens) else None
            if command == 'source_transfer':
                argument = tokens[position + 2] if position + 2 < len(tokens) else None
            if argument is None:
                continue
            if argument.startswith(('>', '<')):
                continue
            dynamic = ('$' in argument or '`' in argument or '(' in argument
                       or argument.startswith(('/', '<')))
            facts['transfers'].append({
                'kind': command,
                'path': None if dynamic else argument,
                'expression': argument if dynamic else None,
                'line': number,
            })
        if 'for pair in' in line:
            for pair in re.findall(r"'([A-Za-z0-9_./+-]+)\s+([A-Za-z0-9_./+-]+)'", line):
                facts['transfers'].append({'kind': 'source_bootstrap', 'path': pair[0],
                                           'destination': pair[1], 'expression': None, 'line': number})
        match = re.search(r'\bcscli\s+(collections|parsers|scenarios|postoverflows|contexts|appsec-rules|appsec-configs)\s+install\s+(.+)', line)
        if match:
            condition = {}
            if name == PREFIX + 'scripts/firstboot/assets/var/lib/firstboot/bin/crowdsec-firstboot.tmpl':
                # This source adapter binds the profile condition to its actual
                # enclosing block. A similarly named unguarded item is not SSH
                # conditional just because of its name.
                for start, end in crowdsec_ssh_blocks:
                    if start < number <= end:
                        condition = {'variable': 'SSH_SERVER_ENABLE', 'equals': 'true'}
            facts['collections'].extend(dict(name=token, type=match[1], line=number, condition=condition)
                                        for token in match[2].split()
                                        if re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', token))
            if (name == PREFIX + 'scripts/firstboot/assets/var/lib/firstboot/bin/crowdsec-firstboot.tmpl'
                    and match[1] == 'collections' and 'crowdsecurity/sshd' in match[2].split() and not condition):
                raise ValueError('CrowdSec SSH collection lacks its reviewed profile condition')
        if re.search(r'\b(?:modprobe|insmod)\s', line) or 'module_udeb=' in line:
            facts['modules'].append({'line': number, 'text': safe_text(stripped)})
    if name.endswith('.pref'):
        for number, fields in paragraphs(text):
            if {'Package', 'Pin', 'Pin-Priority'} <= fields.keys():
                facts['pins'].append({'packages': fields['Package'].split(), 'pin': fields['Pin'],
                                      'priority': int(fields['Pin-Priority']), 'line': number})
    if '/classes/configs/' in name and name.endswith('.cfg'):
        for number, fields in paragraphs(text):
            if fields.get('Type') == 'class':
                facts['classes'].append(dict(fields, line=number))
    if name.endswith(('.sources', '.sources.in.tmpl')):
        for number, fields in paragraphs(text):
            if 'URIs' in fields:
                facts['sources'].append(dict(fields, line=number))
    if name.endswith('.pkr.hcl.tmpl'):
        for match in re.finditer(r'(\w+)\s*=\s*\{\s*source\s*=\s*"([^"]+)"\s*version\s*=\s*"= ([0-9.]+)"\s*\}', text):
            facts['plugins'].append({'name': match[1], 'repository': match[2], 'version': match[3],
                                     'line': text[:match.start()].count('\n') + 1})
    if name.endswith(('.py', '.py.tmpl')) or re.match(r'#![^\n]*\bpython(?:3(?:\.\d+)?)?\b', text):
        if len(text) > 2 * 1024**2:
            raise ValueError('Python source exceeds the static AST parser limit')
        try:
            tree = ast.parse(text, filename=name)
        except SyntaxError as error:
            # A renderable template may not be Python until installation.
            facts['diagnostics'].append({'reason': 'python_ast_unavailable', 'line': error.lineno})
            tree = None
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
                    first = node.elts[0]
                    if (isinstance(first, ast.Constant) and isinstance(first.value, str)
                            and first.value.rsplit('/', 1)[-1] in {'apt', 'apt-get'}):
                        # Stop at the first computed argument. Never evaluate
                        # attributes, calls, starred lists or comprehensions.
                        words = []
                        for element in node.elts:
                            if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                                break
                            words.append(element.value)
                        facts['packages'].extend(dict(package, line=node.lineno, via='python_argv')
                                                  for package in package_tokens(words))
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    key = node.targets[0].id
                    if SECRET.search(key):
                        continue
                    if (name == PREFIX + 'hooks/target/usr/local/libexec/discord-distro'
                            and key in {'HOST_DELTA_FIELDS', 'MODULE_DELTA_FIELDS'}
                            and isinstance(node.value, ast.Name) and node.value.id in facts['constants']):
                        facts['constants'][key] = facts['constants'][node.value.id]
                        continue
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, TypeError, SyntaxError):
                        continue
                    if isinstance(value, str) and (INTEREST.search(key) or URL.search(value)):
                        facts['variables'].append({'name': key, 'value': safe_text(value), 'line': node.lineno})
                    if (re.search(r'(?:_APT_DEPS|_PACKAGES|_UDEBS)$', key)
                            and isinstance(value, (list, tuple)) and 0 < len(value) <= 256
                            and all(isinstance(word, str) and PACKAGE.fullmatch(word) for word in value)):
                        facts['packages'].extend({'selector': word, 'type': 'udeb' if key.endswith('_UDEBS') else 'deb',
                                                  'line': node.lineno, 'via': 'python_literal:' + key} for word in value)
                    # Small literal architecture/ref tables are useful to download consumers.
                    if key in {'RELEASES', 'COMMUNITY_RELEASES'}:
                        facts['constants'][key] = repr(value)
                    if (name == PREFIX + 'hooks/target/usr/local/libexec/discord-distro'
                            and key in {'APPROVED_DISTRO_HOSTS', 'REQUIRED_MODULES', 'MANIFEST_FIELDS',
                                        'HOST_FULL_FIELDS', 'HOST_DELTA_FIELDS', 'MODULE_FIELDS', 'MODULE_FULL_FIELDS',
                                        'MODULE_DELTA_FIELDS', 'MAX_DELTAS'}):
                        if isinstance(value, set) and 0 < len(value) <= 64 and all(
                                isinstance(word, str) and len(word) <= 100 for word in value):
                            facts['constants'][key] = repr(sorted(value))
                        elif key == 'MAX_DELTAS' and type(value) is int and 0 < value <= 64:
                            facts['constants'][key] = repr(value)
    return facts


def package_phase(path: str, item: dict) -> str:
    """Follow the installation boundary of each declaration, without running it."""
    if item['type'] == 'udeb':
        return 'installer_udeb'
    if item['via'].startswith('base-installer/'):
        return 'base_system'
    if item['via'] in {'pkgsel/include', 'variable:SECURE_BOOT_SUPPORT_PACKAGES'}:
        return 'pkgsel'
    if item['via'] in {'variable:NFS_SERVER_APT_DEPS', 'variable:NFS_CLIENT_APT_DEPS'}:
        return 'late'
    phase = context(path).get('phase')
    return phase if phase and phase != 'installation' else 'late'


def package_requests(scans: dict, variables: Variables) -> tuple[list, list, list]:
    """Keep selectors and their origins; exclusions never become downloads."""
    excluded = {}
    for path, facts in scans.items():
        for item in facts['settings']:
            if item['question'] == 'base-installer/excludes':
                for name in item['value'].split():
                    if PACKAGE.fullmatch(name):
                        excluded.setdefault(name, []).append(ref(path, item['line']))
    requests = defaultdict(list)
    dynamic = []
    for path, facts in scans.items():
        kernel_skipped = any(setting['question'] == 'base-installer/kernel/skip-install'
                             and setting['value'] == 'true' for setting in facts['settings'])
        for item in facts['packages']:
            if kernel_skipped and item['via'].startswith('base-installer/kernel/'):
                continue
            condition = {}
            gate = {'variable:NFS_SERVER_APT_DEPS': 'NFS_SERVER_ENABLE',
                    'variable:NFS_CLIENT_APT_DEPS': 'NFS_CLIENT_ENABLE'}.get(item['via'])
            if gate:
                values = variables.global_values.get(gate, set())
                if values and not values.intersection({'1', 'true', 'yes'}):
                    continue
                condition = {'requires_setting': {gate: 'true'}}
                profiles = sorted(PurePosixPath(profile).stem for profile, settings in variables.local.items()
                                  if context(profile).get('profile') and
                                  settings.get(gate, set()).intersection({'1', 'true', 'yes'}))
                if profiles:
                    condition['profiles'] = profiles
            for expanded in variables.expand(item['selector'], path):
                for selector in expanded.split():
                    if not PACKAGE.fullmatch(selector) or selector == 'none':
                        if '$' in selector or '`' in selector or '@@' in selector:
                            dynamic.append({'expression': safe_text(selector), 'type': item['type'],
                                            'source': dict(ref(path, item['line']), **context(path))})
                        continue
                    name = re.split(r'[=/:]', selector)[0]
                    if name in excluded:
                        continue
                    options = {key: item[key] for key in ('operation', 'target_release', 'download_only', 'purpose',
                               'install_recommends', 'install_suggests', 'unresolved_options') if key in item}
                    options.setdefault('operation', 'install')
                    options.update(selector=selector, type=item['type'], phase=package_phase(path, item))
                    targets = variables.expand(options['target_release'], path) if options.get('target_release') else [None]
                    for target in targets:
                        descriptor = dict(options)
                        if target is not None:
                            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', target):
                                dynamic.append({'expression': safe_text(target), 'reason': 'unresolved_target_release',
                                                'source': ref(path, item['line'])})
                                continue
                            descriptor['target_release'] = target
                        key = json.dumps(descriptor, sort_keys=True)
                        requests[key].append(dict(ref(path, item['line']), via=item['via'],
                                                  **dict(context(path), phase=options['phase']), **condition))
    return ([dict(json.loads(key), id='request-' + digest(key.encode())[:24],
                  name=re.split(r'[=/:]', json.loads(key)['selector'])[0], sources=unique(sources))
             for key, sources in sorted(requests.items())],
            [{'name': name, 'sources': sources} for name, sources in sorted(excluded.items())], unique(dynamic))


class Variables:
    def __init__(self, scans: dict):
        self.local = defaultdict(lambda: defaultdict(set))
        self.global_values = defaultdict(set)
        for name, facts in scans.items():
            if context(name).get('phase') == 'inactive_backup':
                continue
            for item in facts['variables']:
                self.local[name][item['name']].add(item['value'])
                if item['name'].isupper() and name.endswith(('.env', '.py')):
                    self.global_values[item['name']].add(item['value'])

    def expand(self, text: str, path: str, seen: tuple = ()) -> list[str]:
        match = VARIABLE.search(text)
        if not match or len(seen) > 12:
            return [text]
        key, default_op, default, bare = match.groups()
        key = key or bare
        if key in seen or SECRET.search(key):
            return [text]
        values = self.local[path].get(key) or self.global_values.get(key)
        if not values and default_op:
            values = {default}
        if not values:
            # Move past an unknown variable to expand the remaining known ones.
            tail = self.expand(text[match.end():], path, seen)
            return [text[:match.end()] + value for value in tail]
        results = set()
        for value in sorted(values):
            for expanded in self.expand(value, path, seen + (key,)):
                for tail in self.expand(text[match.end():], path, seen):
                    results.add(text[:match.start()] + expanded + tail)
                    if len(results) >= MAX_EXPANSIONS:
                        raise ValueError('variable expansion limit exceeded in ' + path)
        return sorted(results)


def ref(path: str, line: int) -> dict:
    return {'path': path, 'line': line}


def unique(items: list) -> list:
    return [json.loads(key) for key in sorted({json.dumps(item, sort_keys=True) for item in items})]


def repo_id(url: str, suite: str) -> str:
    return 'apt-' + digest((url.rstrip('/') + '\n' + suite).encode())[:16]


def version_compare(left: str, right: str) -> int:
    """Debian epoch/upstream/revision ordering, without consulting host dpkg."""
    def split(value):
        epoch, separator, tail = value.partition(':')
        epoch, value = (int(epoch), tail) if separator else (0, value)
        upstream, separator, revision = value.rpartition('-')
        return epoch, upstream if separator else value, revision if separator else '0'

    def part(a, b):
        def order(char):
            return -1 if char == '~' else 0 if not char else ord(char) if char.isalpha() else ord(char) + 256
        while a or b:
            while (a and not a[0].isdigit()) or (b and not b[0].isdigit()):
                x, y = a[:1] if a[:1] and not a[0].isdigit() else '', b[:1] if b[:1] and not b[0].isdigit() else ''
                if order(x) != order(y):
                    return 1 if order(x) > order(y) else -1
                a, b = a[len(x):], b[len(y):]
            am, bm = re.match(r'\d*', a)[0], re.match(r'\d*', b)[0]
            x, y = am.lstrip('0'), bm.lstrip('0')
            if (len(x), x) != (len(y), y):
                return 1 if (len(x), x) > (len(y), y) else -1
            a, b = a[len(am):], b[len(bm):]
        return 0

    a, b = split(left), split(right)
    if a[0] != b[0]:
        return 1 if a[0] > b[0] else -1
    return part(a[1], b[1]) or part(a[2], b[2])


def pin_matches(rule: dict, package: dict, repo: dict, release: dict, native_architecture=None) -> bool:
    name = package['package']
    matched = False
    for pattern in rule['packages']:
        if pattern.startswith('/') and pattern.endswith('/'):
            raise ValueError('regular-expression APT package pins require an explicit policy adapter')
        target = package.get('source', name).split()[0] if pattern.startswith('src:') else name
        pattern = pattern.removeprefix('src:')
        qualifier = re.search(r':(any|native|amd64|arm64)$', pattern)
        if qualifier and qualifier[1] not in {'any', 'native', native_architecture or package.get('architecture')}:
            continue
        pattern = re.sub(r':(?:any|native|amd64|arm64)$', '', pattern)
        matched |= fnmatch.fnmatchcase(target, pattern)
    if not matched:
        return False
    kind, _, value = rule['pin'].partition(' ')
    if kind == 'version':
        return fnmatch.fnmatchcase(package['version'], value)
    if kind == 'source-version':
        match = re.fullmatch(r'\S+\s+\(([^)]+)\)', package.get('source', name))
        return fnmatch.fnmatchcase(match[1] if match else package['version'], value)
    if kind == 'origin':
        return fnmatch.fnmatchcase(urlsplit(repo['url']).hostname or '', value.strip('"'))
    if kind == 'release':
        fields = {'o': 'Origin', 'l': 'Label', 'a': 'Suite', 'n': 'Codename', 'v': 'Version', 'c': 'Component'}
        if not value or any('=' not in condition for condition in value.split(',')):
            raise ValueError('unsupported APT release pin expression')
        conditions = dict(condition.strip().split('=', 1) for condition in value.split(','))
        for key, pattern in conditions.items():
            actual = package.get('component', '') if key == 'c' else release.get(fields.get(key, ''), '')
            if key not in fields or not fnmatch.fnmatchcase(actual, pattern):
                return False
        return True
    raise ValueError('unsupported APT pin type')


def policy_context(scans: dict, pins: list, classes: list) -> tuple[set, dict]:
    global_preferences = {'00-excluded-desktop-apps'}
    for path, facts in scans.items():
        if path.endswith('/repo.env'):
            for item in facts['variables']:
                if item['name'] == 'DEBIAN_APT_PREFERENCES':
                    global_preferences.update(re.split(r'[,\s]+', item['value']))
    class_map = {item['Group'] + '/' + item['Name']: item for item in classes}
    for rule in pins:
        rule['id'] = 'pin-' + digest(json.dumps(rule, sort_keys=True).encode())[:16]
        preference = Path(rule['source']['path']).stem
        rule['preference'] = preference
        rule['activation'] = {'always': preference in global_preferences,
                              'classes': sorted(key for key, item in class_map.items() if preference in
                                                re.split(r'[,\s]+', item.get('DebianAptPreferences', '')))}
        if preference == 'nvidia-opt-in':
            rule['activation']['hardware_condition'] = 'no_selected_NVIDIA_class_with_detected_NVIDIA_display_hardware'
    return global_preferences, class_map


def preference_scope(selected: str | None, global_preferences: set, classes: dict) -> set:
    preferences, todo, visited = set(global_preferences), [selected] if selected else [], set()
    while todo:
        name = todo.pop()
        if name in visited:
            continue
        visited.add(name)
        fields = classes.get(name, {})
        preferences.update(re.split(r'[,\s]+', fields.get('DebianAptPreferences', '')))
        todo.extend(re.split(r'[,\s]+', fields.get('RequiresClasses', '')))
    return preferences


def specific_pin(rule: dict) -> bool:
    kind, _, pattern = rule['pin'].partition(' ')
    return rule['packages'] != ['*'] or kind in {'version', 'source-version'} and pattern != '*'


def pin_priority(package: dict, repo: dict, release: dict, rules: list, preferences: set, target_suite=None,
                 native_architecture=None) -> int:
    default = 500
    if release.get('NotAutomatic') == 'yes':
        default = 100 if release.get('ButAutomaticUpgrades') == 'yes' else 1
    general = []
    for rule in sorted(rules, key=lambda r: (Path(r['source']['path']).name, r['line'])):
        if rule['preference'] not in preferences or not pin_matches(rule, package, repo, release, native_architecture):
            continue
        if specific_pin(rule):
            return rule['priority']
        general.append(rule['priority'])
    if target_suite and target_suite in {repo['suite'], release.get('Suite'), release.get('Codename')}:
        return 990
    return max(general) if general else default


def resolve_catalog(database, apt: dict, releases: dict) -> tuple[list, list]:
    """Select named requests, then one satisfiable dependency alternative.

    This is a bounded metadata resolver, not libapt's transaction solver. It
    reports unsatisfied/ambiguous relationships instead of retaining every
    provider or falling back to host APT. Only selected rows leave scratch.
    """
    repos = {row['id']: row for row in apt['repositories']}
    classes = {row['Group'] + '/' + row['Name']: row for row in apt['classes']}
    excluded = {row['name'] for row in apt['exclusions']}
    selected, selection_budget = {}, DiscoveryBudget()
    issues = Facts(selection_budget)
    relationships = re.compile(r'([a-z0-9][a-z0-9+.-]*)(?::([a-z0-9-]+))?'
                               r'(?:\s*\((<<|<=|=|>=|>>)\s*([A-Za-z0-9.+:~_-]+)\))?\Z')

    def closure(scope):
        todo, result = [scope] if scope else [], {'role/desktop'}
        while todo:
            key = todo.pop()
            if key in result and key != 'role/desktop':
                continue
            result.add(key)
            todo.extend(re.split(r'[,\s]+', classes.get(key, {}).get('RequiresClasses', '').strip()))
            todo = [key for key in todo if key and key not in result]
        return result

    def eligible_repo(row, enabled):
        return any(not definition.get('class') or definition['class'] in enabled
                   for definition in repos[row['repository']]['definitions'])

    def satisfies(version, operator, required):
        if not operator:
            return True
        order = version_compare(version, required)
        return {'<<': order < 0, '<=': order <= 0, '=': order == 0,
                '>=': order >= 0, '>>': order > 0}[operator]

    def check_coinstall(snapshot, context_id, phase, architecture):
        """Check one modeled installed snapshot, excluding historical versions."""
        names, providers = defaultdict(list), defaultdict(list)
        for (_, kind), row in snapshot.items():
            names[(kind, row['package'])].append((row, row['version']))
            for provided in row.get('provides', '').split(','):
                match = re.fullmatch(r'\s*([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9-]+)?'
                                     r'(?:\s*\(=\s*([A-Za-z0-9.+:~_-]+)\))?\s*', provided)
                if match:
                    providers[(kind, match[1])].append((row, match[2]))
        for (_, kind), row in snapshot.items():
            if kind != ('udeb' if phase == 'installer_udeb' else 'deb'):
                continue
            for field in ('conflicts', 'breaks'):
                for group in row.get(field, '').split(','):
                    if not group.strip():
                        continue
                    hit = False
                    for alternative in group.split('|'):
                        match = relationships.fullmatch(alternative.strip())
                        if not match:
                            issues.append({'context': context_id, 'phase': phase, 'architecture': architecture,
                                           'package': row['package'], 'field': field,
                                           'relationship': group.strip(), 'reason': 'unsupported_conflict_expression'})
                            continue
                        name, qualifier, operator, required = match.groups()
                        if qualifier and qualifier not in {'any', 'native', architecture}:
                            continue
                        for other, effective_version in names.get((kind, name), []) + providers.get((kind, name), []):
                            if other['package'] == row['package']:
                                continue
                            # An unversioned virtual Provide cannot satisfy a
                            # versioned Conflicts/Breaks relationship.
                            if not operator or effective_version is not None and satisfies(effective_version, operator, required):
                                hit = True
                                break
                        if hit:
                            break
                    if hit:
                        issues.append({'context': context_id, 'phase': phase, 'architecture': architecture,
                                       'package': row['package'], 'field': field,
                                       'relationship': group.strip(), 'reason': 'selected_package_conflict_or_breaks'})

    def choose(name, kind, architecture, enabled, preferences, *, operator=None, version=None, suite=None,
               repository=None, target_release=None, allow_downgrade=False):
        choice_errors.pop(name, None)
        if name in excluded:
            return None
        query = ('SELECT p.data, NULL FROM packages p WHERE p.name=? AND p.kind=? '
                 'AND p.architecture IN (?,\'all\') UNION ALL '
                 'SELECT p.data, v.version FROM provides v JOIN packages p ON p.id=v.package_id '
                 'WHERE v.name=? AND p.kind=? AND p.architecture IN (?,\'all\')')
        instances = defaultdict(list)
        seen_rows = 0
        for encoded, provided_version in database.execute(query, (name, kind, architecture, name, kind, architecture)):
            seen_rows += 1
            if seen_rows > 4096:
                raise ValueError('per-package APT candidate limit exceeded')
            row = json.loads(encoded)
            if row.get('indexed_architecture', architecture) != architecture:
                continue
            if repository and row['repository'] != repository:
                continue
            if phase in {'base_system', 'installer_udeb'} and repos[row['repository']]['role'] != 'base_mirror':
                continue
            if phase == 'base_upgrade' and repos[row['repository']].get('available_from_phase') == 'pre_pkgsel':
                continue
            if phase in {'first_boot', 'installed_capability'} and repos[row['repository']].get('temporary'):
                continue
            if not eligible_repo(row, enabled):
                continue
            if row['package'] in excluded:
                continue
            actual_version = row['version'] if row['package'] == name else provided_version
            if operator and (not actual_version or not satisfies(actual_version, operator, version)):
                continue
            instances[(row['package'], row['version'], row['architecture'])].append(row)
        choices = []
        for copies in instances.values():
            if suite and not any(suite in {repos[row['repository']]['suite'],
                    releases[row['repository']].get('Suite'), releases[row['repository']].get('Codename')} for row in copies):
                continue
            priority = None
            if kind != 'udeb':
                for rule in sorted(apt['pin_rules'], key=lambda rule: (Path(rule['source']['path']).name, rule['line'])):
                    if (specific_pin(rule) and rule['preference'] in preferences and any(
                            pin_matches(rule, row, repos[row['repository']], releases[row['repository']], architecture) for row in copies)):
                        priority = rule['priority']
                        break
            if priority is None:
                priority = (500 if kind == 'udeb' else max(pin_priority(
                    row, repos[row['repository']], releases[row['repository']], apt['pin_rules'], preferences,
                    target_release, architecture) for row in copies))
            if priority > 0:
                # APT pins select a VERSION. For that version, sources.list
                # order chooses the download instance, including copies in
                # another configured suite. Never publish all tied instances.
                first = min(copies, key=lambda row: (repos[row['repository']]['order'],
                    repos[row['repository']]['components'].index(row['component']) if row.get('component') else -1,
                    row['index_url'], row['url']))
                choices.append(dict(first, pin_priority=priority))
        if not choices:
            return None
        real = [row for row in choices if row['package'] == name]
        if real:
            choices = real
        else:
            present = [row for row in choices if row['package'] in planned
                       and planned[row['package']]['version'] == row['version']]
            if present:
                choices = present
            elif len({row['package'] for row in choices}) > 1:
                choice_errors[name] = {'reason': 'ambiguous_virtual_provider',
                                       'providers': sorted({row['package'] for row in choices})}
                return None

        def compare(a, b):
            return ((a['pin_priority'] > b['pin_priority']) - (a['pin_priority'] < b['pin_priority'])
                    or version_compare(a['version'], b['version'])
                    or repos[b['repository']]['order'] - repos[a['repository']]['order']
                    or (a['package'] == name) - (b['package'] == name)
                    or (b['url'] > a['url']) - (b['url'] < a['url']))
        candidate = max(choices, key=cmp_to_key(compare))
        previous = installed.get((candidate['package'], kind))
        if (previous and not allow_downgrade and candidate['pin_priority'] <= 1000
                and version_compare(candidate['version'], previous['version']) < 0
                and satisfies(previous['version'], operator, version)):
            return previous
        return candidate

    contexts = sorted({source.get('class', '') for request in apt['requests'] for source in request['sources']})
    # Profiles with identical package gates share one context. A server-only
    # package list must not seed a disabled client or another host profile.
    profile_conditions = sorted({tuple(source.get('profiles') or [source['profile']])
                                 for request in apt['requests'] for source in request['sources']
                                 if source.get('profiles') or source.get('profile')})
    profile_names = apt.get('profiles', [])
    profile_groups = defaultdict(list)
    for profile in profile_names:
        signature = tuple(profile in profiles for profiles in profile_conditions)
        profile_groups[signature].append(profile)
    groups = list(profile_groups.values()) or [[]]
    if len(contexts) * len(groups) > 512:
        raise ValueError('conditional installation context limit exceeded')
    for scope, architecture, profiles in itertools.product(contexts, ['amd64', 'arm64'], groups):
        enabled = closure(scope)
        required_arches = {key.split('/', 1)[1] for key in enabled if key.startswith('arch/')}
        if required_arches and required_arches != {architecture}:
            continue
        enabled.add('arch/' + architecture)
        configured_preferences = preference_scope(scope, set(apt['global_preferences']), classes)
        configured_preferences |= preference_scope('role/desktop', set(), classes)
        if not enabled.intersection({'addon/nvidia', 'addon/nvidia-legacy', 'addon/cuda', 'addon/cuda-legacy'}):
            configured_preferences.add('nvidia-opt-in')
        context_id = (scope or 'base') + ':' + architecture
        if profile_conditions:
            context_id += ':profiles-' + digest('\n'.join(profiles).encode())[:12]
        installed = {}
        for phase in ('installer_udeb', 'base_system', 'base_upgrade', 'pre_pkgsel', 'pkgsel', 'late',
                      'first_boot', 'installed_capability'):
            preferences = set() if phase in {'installer_udeb', 'base_system'} else configured_preferences
            default_release = (apt.get('post_install_default_release', {}).get('suite')
                               if phase in {'first_boot', 'installed_capability'} else None)
            todo, visited, versions, choice_errors = deque(), set(), {}, {}
            planned = {name: row for (name, kind), row in installed.items()
                       if kind == ('udeb' if phase == 'installer_udeb' else 'deb')}
            # debootstrap precedes apt-setup and the staged target preferences.
            # Its base set and dependencies come only from the installer mirror.
            if phase == 'base_system':
                for repository in (repo for repo in repos.values() if repo['role'] == 'base_mirror'):
                    names = database.execute(
                        'SELECT DISTINCT name FROM packages WHERE repository=? AND kind=\'deb\' '
                        'AND architecture IN (?,\'all\') AND (essential=1 OR priority IN (\'required\',\'important\'))',
                        (repository['id'], architecture))
                    for (name,) in names:
                        row = choose(name, 'deb', architecture, enabled, preferences, repository=repository['id'])
                        if row:
                            planned[row['package']] = row
                            todo.append((row, {'context': context_id, 'phase': phase,
                                               'reason': 'installer_base_system', 'operation': 'install'}))
            if phase == 'base_upgrade' and apt.get('base_upgrade', {}).get('mode', 'none') != 'none':
                for (name, kind), previous in sorted(installed.items()):
                    if kind != 'deb':
                        continue
                    row = choose(name, kind, architecture, enabled, preferences)
                    if row and row['version'] != previous['version']:
                        planned[row['package']] = row
                        todo.append((row, {'context': context_id, 'phase': phase, 'operation': 'install',
                                           'reason': 'pkgsel_base_upgrade',
                                           'upgrade_mode': apt['base_upgrade']['mode']}))
            for request in apt['requests']:
                if request['phase'] != phase:
                    continue
                origins = [source for source in request['sources']
                           if (not source.get('class') or source['class'] in enabled)
                           and (not source.get('profile') or source['profile'] in profiles)
                           and (not source.get('profiles') or set(source['profiles']).intersection(profiles))]
                if not origins:
                    continue
                selector = request['selector']
                name = re.split(r'[=/:]', selector)[0]
                # answers.sh applies this architecture filter to pkgsel only.
                if phase == 'pkgsel' and name in {'rar', 'microsoft-edge-stable'} and architecture == 'arm64':
                    continue
                qualifier = re.search(r':(any|native|amd64|arm64)', selector)
                if qualifier and qualifier[1] not in {'any', 'native', architecture}:
                    continue
                use = {'context': context_id, 'phase': phase, 'request_id': request['id'],
                       'profiles': profiles,
                       'reason': 'explicit_request', 'selector': selector, 'sources': origins,
                       'operation': request['operation'],
                       'download_only': request.get('download_only', False),
                       'install_recommends': request.get('install_recommends', False),
                       'install_suggests': request.get('install_suggests', False),
                       'target_release': request.get('target_release', default_release)}
                if request.get('unresolved_options'):
                    issues.append(dict(use, reason='unresolved_apt_command_options'))
                    continue
                version, suite = selector.partition('=')[2] or None, selector.partition('/')[2] or None
                row = choose(name, request['type'], architecture, enabled, preferences,
                             operator='=' if version else None, version=version, suite=suite,
                             target_release=use['target_release'], allow_downgrade=bool(version or suite))
                if row is None:
                    issues.append({'context': context_id, 'phase': phase, 'request_id': request['id'],
                                   'request': selector, 'type': request['type'],
                                   **choice_errors.get(name, {'reason': 'no_eligible_index_record'}), 'sources': origins})
                else:
                    if use['operation'] == 'install' and not use['download_only']:
                        planned[row['package']] = row
                    todo.append((row, use))
            while todo:
                if len(todo) > 10000:
                    raise ValueError('pending installation dependency limit exceeded')
                row, use = todo.popleft()
                identity = (row['repository'], row['package'], row['type'], row['version'], row['architecture'])
                mutates = use['operation'] == 'install' and not use.get('download_only')
                if mutates:
                    version_key = (row['package'], row['type'])
                    previous = versions.setdefault(version_key, row['version'])
                    if previous != row['version']:
                        issues.append({'context': context_id, 'phase': phase, 'package': row['package'],
                                       'reason': 'multiple_versions_within_phase_require_transaction_order',
                                       'versions': sorted({previous, row['version']})})
                    installed[version_key] = row
                if identity not in selected:
                    selection_budget.consume(row)
                    selected[identity] = dict(row, uses=[])
                stored = selected[identity]
                if any(stored.get(key) != row.get(key) for key in ('url', 'filename', 'size', 'sha256', 'source')):
                    raise ValueError('selected binary identity conflicts across repository indexes')
                provenance = dict(use, pin_priority=row['pin_priority'], architecture=architecture,
                                  index_url=row['index_url'])
                selection_budget.consume(provenance)
                stored['uses'].append(provenance)
                # apt-get download fetches the named binary, without resolving
                # dependencies. install --download-only resolves dependencies
                # without adding them to the later installed-state model.
                if use['operation'] == 'download':
                    continue
                dependency_mode = (identity, use.get('target_release'), use.get('download_only', False),
                                   use.get('install_recommends', False), use.get('install_suggests', False))
                if dependency_mode in visited:
                    continue
                visited.add(dependency_mode)
                if len(visited) > 10000 or len(selected) > 50000:
                    raise ValueError('selected installation package limit exceeded')
                fields = ['pre_depends', 'depends']
                fields += ['recommends'] if use.get('install_recommends') else []
                fields += ['suggests'] if use.get('install_suggests') else []
                for field in fields:
                    for group in row.get(field, '').split(','):
                        if not group.strip():
                            continue
                        candidate = first = None
                        for alternative in group.split('|'):
                            match = relationships.fullmatch(alternative.strip())
                            if not match:
                                issues.append({'context': context_id, 'phase': phase, 'package': row['package'],
                                               'reason': 'unsupported_dependency_expression', 'field': field})
                                continue
                            name, qualifier, operator, required = match.groups()
                            if qualifier and qualifier not in {'any', 'native', architecture}:
                                continue
                            present = planned.get(name)
                            if present and satisfies(present['version'], operator, required):
                                candidate = present
                                break
                            candidate = choose(name, row['type'], architecture, enabled, preferences,
                                               operator=operator, version=required,
                                               target_release=use.get('target_release'))
                            if candidate and first is None:
                                first = candidate
                            if candidate and candidate['package'] in planned:
                                present = planned[candidate['package']]
                                if present['version'] == candidate['version']:
                                    break
                            candidate = None
                        candidate = candidate or first
                        if candidate:
                            if mutates:
                                planned[candidate['package']] = candidate
                            todo.append((candidate, dict(use, reason=field, required_by=row['package'],
                                                         relationship=group.strip())))
                        elif field not in {'recommends', 'suggests'}:
                            issues.append({'context': context_id, 'phase': phase, 'package': row['package'],
                                           'reason': 'unsatisfied_dependency', 'field': field,
                                           'relationship': group.strip()})
            check_coinstall(installed, context_id, phase, architecture)
    records = []
    for row in selected.values():
        row['uses'] = unique(row['uses'])
        records.append(row)
    return sorted(records, key=lambda row: (row['package'], row['type'], row['architecture'], row['version'], row['repository'])), unique(issues)


def repositories(scans: dict) -> list[dict]:
    result = {}

    def add(url, suite, components, source, **extra):
        parsed = urlsplit(url)
        local = parsed.scheme == 'file'
        if (not local and (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                           or parsed.query or parsed.fragment or clean_url(url) != url)
                or local and (not parsed.path.startswith('/') or parsed.netloc or parsed.query or parsed.fragment
                              or parsed.username or parsed.password)
                or not re.fullmatch(r'[A-Za-z0-9_.+/-]+', suite) or '..' in PurePosixPath(suite).parts
                or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', part) for part in components)
                or not local and bool(components) == suite.endswith('/')):
            raise ValueError('unsupported or unsafe installer repository declaration')
        identifier = repo_id(url, suite)
        row = result.setdefault(identifier, {'id': identifier, 'url': url.rstrip('/'), 'suite': suite,
                    'components': components, 'architectures': ['amd64', 'arm64'], 'definitions': [],
                    'order': len(result), **extra})
        row['definitions'].append(source)
        row['components'] = list(dict.fromkeys(row['components'] + components))
        return row

    for name, facts in scans.items():
        settings = {s['question']: s for s in facts['settings']}
        if 'mirror/suite' in settings and 'mirror/protocol' in settings:
            proto = settings['mirror/protocol']['value']
            host = settings.get('mirror/' + proto + '/hostname', {}).get('value')
            directory = settings.get('mirror/' + proto + '/directory', {}).get('value')
            if host and directory:
                components = ['main'] + [p for p in ['contrib', 'non-free', 'non-free-firmware']
                                        if settings.get('apt-setup/' + p, {}).get('value') == 'true']
                url, suite = proto + '://' + host + '/' + directory.strip('/'), settings['mirror/suite']['value']
                source = ref(name, settings['mirror/suite']['line'])
                add(url, suite, components, source, role='base_mirror', udeb_suite=settings.get('mirror/udeb/suite', {}).get('value', suite))
                services = settings.get('apt-setup/services-select', {}).get('value', '').replace(',', ' ').split()
                for service in services:
                    if service == 'security':
                        host = settings.get('apt-setup/security_host', {}).get('value', 'security.debian.org')
                        path = settings.get('apt-setup/security_path', {}).get('value', '/debian-security')
                        add(proto + '://' + host + path, suite + '-security', components, source, role='optional_installer_service')
                    elif service in {'updates', 'backports'}:
                        add(url, suite + '-' + service, components, source, role='optional_installer_service')
        for question, setting in settings.items():
            match = re.fullmatch(r'apt-setup/(local\d+)/repository', question)
            if not match:
                continue
            words = setting['value'].split()
            if len(words) < 2:
                raise ValueError('invalid repository declaration in ' + name)
            prefix = 'apt-setup/' + match[1] + '/'
            row = add(words[0], words[1], words[2:], dict(ref(name, setting['line']), **context(name)),
                      role='class_archive', local_index=int(match[1].removeprefix('local')))
            row.setdefault('key_urls', []).extend(URL.findall(settings.get(prefix + 'key', {}).get('value', '')))
            row.setdefault('labels', []).append(settings.get(prefix + 'comment', {}).get('value', ''))
            row['source_packages_enabled'] = settings.get(prefix + 'source', {}).get('value') == 'true'
        for fields in facts['sources']:
            if fields.get('Enabled', 'yes').lower() == 'no':
                continue
            for url, suite in itertools.product(fields['URIs'].split(), fields.get('Suites', './').split()):
                if url.startswith(('https://', 'http://')):
                    add(url, suite, fields.get('Components', '').split(), ref(name, fields['line']), role='installed_source')
                elif url.startswith('file:'):
                    add(url, suite, fields.get('Components', '').split(), ref(name, fields['line']),
                        role='local_staging')
    ordered = sorted(result.values(), key=lambda row: (
        {'base_mirror': 0, 'optional_installer_service': 1, 'class_archive': 2, 'installed_source': 3,
         'local_staging': 4}[row['role']],
        row.get('local_index', 0), row['order']))
    for order, row in enumerate(ordered):
        row['order'] = order
        row['definitions'] = unique(row['definitions'])
        row['key_urls'] = sorted(set(row.get('key_urls', [])))
        row['labels'] = sorted(set(row.get('labels', [])))
        if row['url'] == CUDA_LEGACY_URL.rstrip('/') and row['suite'] == '/' and not row['key_urls']:
            policies = [facts['constants']['CUDA_LEGACY_POLICY'] for facts in scans.values()
                        if 'CUDA_LEGACY_POLICY' in facts['constants']]
            if len(policies) != 1:
                raise ValueError('legacy CUDA archive lacks its explicit source authentication policy')
            row['authentication'] = policies[0]
            row['temporary'] = policies[0]['temporary']
            row['available_from_phase'] = 'pre_pkgsel'
            row['architectures'] = ['amd64']
        row['index_urls'] = []
        if row['role'] == 'local_staging':
            row['source_lookup'] = 'runtime_local_repository_staging'
            row['release_url'] = None
            continue
        release_base = (row['url'] + '/' + row['suite'].lstrip('./') if row['suite'].endswith('/')
                        else f'{row["url"]}/dists/{row["suite"]}/')
        binary_release_url = (row['url'] + '/' + row['suite'].lstrip('./') + 'Release'
                              if row['suite'].endswith('/') else f'{row["url"]}/dists/{row["suite"]}/Release')
        udeb_release_url = None
        if row['role'] == 'base_mirror':
            udeb_release_url = (row['url'] + '/' + row['udeb_suite'].lstrip('./') + 'Release'
                               if row['udeb_suite'].endswith('/')
                               else f'{row["url"]}/dists/{row["udeb_suite"]}/Release')
        for arch in row['architectures']:
            if row['suite'].endswith('/'):
                row['index_urls'].append({'architecture': arch, 'type': 'deb', 'url': row['url'] + '/' + row['suite'].lstrip('./') + 'Packages',
                                          'release_url': binary_release_url})
            else:
                for component in row['components']:
                    row['index_urls'].append({'architecture': arch, 'type': 'deb', 'component': component,
                        'url': f'{row["url"]}/dists/{row["suite"]}/{component}/binary-{arch}/Packages',
                        'release_url': binary_release_url})
                    if row.get('role') == 'base_mirror':
                        row['index_urls'].append({'architecture': arch, 'type': 'udeb', 'component': component,
                            'url': f'{row["url"]}/dists/{row["udeb_suite"]}/{component}/debian-installer/binary-{arch}/Packages',
                            'release_url': udeb_release_url})
        if row['suite'].endswith('/'):
            row['index_urls'].append({'architecture': 'source', 'type': 'source', 'url': release_base + 'Sources',
                                      'release_url': binary_release_url})
        else:
            for component in row['components']:
                row['index_urls'].append({'architecture': 'source', 'type': 'source', 'component': component,
                                         'url': release_base + component + '/source/Sources',
                                         'release_url': binary_release_url})
        # Collect matching source artifacts even when installation disables
        # deb-src. That flag controls APT activation, not source availability.
        row['source_lookup'] = 'advertised_Sources_indexes_in_the_selected_binary_repository'
        row['release_url'] = binary_release_url
    return sorted(result.values(), key=lambda row: row['order'])


def artifacts(scans: dict, variables: Variables) -> tuple[list, list, list]:
    downloads, clones, references = [], [], defaultdict(list)
    consumers = defaultdict(list)
    for path, facts in scans.items():
        if '/scripts/' in path or '/hooks/' in path:
            for key, line in facts['references'].items():
                consumers[key].append(dict(ref(path, line), **context(path)))
    for path, facts in scans.items():
        if context(path).get('phase') == 'inactive_backup':
            continue
        for asset in facts['manifest_files']:
            downloads.append({'name': 'desktop-theme:' + asset['asset_path'], 'kind': 'staged_theme_data',
                              'url': asset['url'], 'size': asset['bytes'], 'sha256': asset['sha256'],
                              'repository_path': PREFIX + 'assets/desktop-themes/' + asset['asset_path'],
                              'resolution': 'pinned_staged_file',
                              'sources': [{'path': path, 'json_pointer': '/files/' + asset['asset_path'].replace('/', '~1')}],
                              'selection': [{'class': 'role/desktop', 'phase': 'late'}]})
        definitions = {item['name']: item for item in facts['variables']}
        for item in facts['variables']:
            key, value = item['name'], item['value']
            if not URL.search(value) and not re.search(r'(?i)(?:url|uri)$', key):
                continue
            if not value or '$(' in value or '`' in value:
                continue
            urls = [url for url in variables.expand(value, path) if URL.match(url)]
            for url in urls:
                stem = re.sub(r'(?i)(?:_repository)?_(?:url|uri)$', '', key)
                metadata = {}
                for suffix in ('VERSION', 'SHA256', 'SHA512', 'FINGERPRINT', 'BRANCH', 'COMMIT', 'REVISION', 'TAG', 'RELEASE_TAG',
                               'ARCHITECTURE', 'SOURCE_BUILD', 'FILENAME', 'MINIMUM_BYTES', 'MAXIMUM_BYTES'):
                    candidate = definitions.get(stem + '_REPOSITORY_' + suffix) or definitions.get(stem + '_' + suffix)
                    base_stem = re.sub(r'_(?:SOURCE|DOWNLOAD|RELEASE)$', '', stem)
                    candidate = candidate or definitions.get(base_stem + '_' + suffix)
                    if suffix == 'SHA256' and 'huggingface.co' in url:
                        candidate = definitions.get(base_stem + '_MODEL_SHA256') or candidate
                    if suffix == 'FINGERPRINT' and stem.endswith('_KEY'):
                        candidate = definitions.get(stem.removesuffix('_KEY') + '_FINGERPRINT') or candidate
                    if candidate:
                        metadata[suffix.lower()] = candidate['value']
                selections = [dict(context(path), **{key: value for key, value in consumer.items()
                                                     if key in {'class', 'phase'}})
                              for consumer in consumers[key] if consumer.get('class')]
                record = {'name': stem, 'url': clean_url(url), **metadata,
                          'resolution': 'template' if re.search(r'[$`{}*\\]|__\w+__', url) else 'declared',
                          'sources': [dict(ref(path, item['line']), variable=key)],
                          'selection': selections or [context(path)], 'consumers': consumers[key]}
                if 'REPOSITORY' in key.upper() or url.startswith(('git@', 'ssh://', 'git://')) or url.endswith('.git'):
                    record['authentication'] = 'ssh_identity_required' if url.startswith(('git@', 'ssh://')) else 'public'
                    clones.append(record)
                else:
                    if not path.endswith('.env') and not ('/scripts/' in path or '/usr/local/lib' in path or '/usr/local/bin/' in path):
                        continue
                    record['kind'] = ('metadata' if re.search(r'(?i)(registry|api|metadata|base)', key)
                                      else 'model' if '/resolve/' in url and 'huggingface.co' in url
                                      else 'archive' if archive_url(url)
                                      else 'download_endpoint')
                    if re.search(r'CONNECTIVITY|PLANS_|OBS_API|APTLY_(?:PUBLIC_BASE|R2_ENDPOINT)', key) or key == 'fruux_root_url':
                        record['kind'] = 'service_endpoint'
                    downloads.append(record)
                    if key == 'SOFTWARE_TOR_BROWSER_URL':
                        downloads.append({'name': 'SOFTWARE_TOR_BROWSER_SIGNATURE', 'url': url + '.asc',
                                          'kind': 'signature', 'resolution': 'derived_from_installer_policy',
                                          'byte_identity': 'detached_signature_without_advertised_hash',
                                          'sources': [dict(ref(path, item['line']), variable=key)],
                                          'selection': record['selection'], 'consumers': consumers[key]})
                    elif re.fullmatch(r'MULLVAD_(?:AMD64|ARM64)_DEB_URL', key):
                        downloads.append({'name': key.removesuffix('_URL') + '_SIGNATURE',
                                          'url': url.rstrip('/') + '/signature', 'kind': 'signature',
                                          'resolution': 'derived_from_installer_policy',
                                          'byte_identity': 'detached_signature_without_advertised_hash',
                                          'sources': [dict(ref(path, item['line']), variable=key)],
                                          'selection': record['selection'], 'consumers': consumers[key]})
        for item in facts['urls']:
            for url in variables.expand(item['url'], path):
                references[clean_url(url)].append(ref(path, item['line']))
        # Perl adapters and Python call arguments can own downloads without a
        # shell assignment. Keep their literal endpoints in the consumer list.
        operational = ('/scripts/' in path or '/APTRepoLocal/Servicing/' in path or '/usr/local/libexec/apt-repo-local' in path)
        if operational:
            declared = {row['url'] for row in downloads + clones}
            for item in facts['urls']:
                for url in variables.expand(item['url'], path):
                    try:
                        host = urlsplit(url).hostname or ''
                    except ValueError:
                        continue
                    if (not re.fullmatch(r'[A-Za-z0-9.-]+', host) or '\\' in url
                            or url.endswith(('}', '|', '(')) or '*)' in url or url == 'https://github.com/'):
                        continue
                    if url in declared:
                        for row in downloads + clones:
                            if row.get('url') == url:
                                row.setdefault('sources', []).append(ref(path, item['line']))
                                row.setdefault('selection', []).append(context(path))
                        continue
                    row = {'name': Path(path).stem, 'url': url,
                                      'kind': 'metadata' if re.search(r'/api/|/manifests/|\.ya?ml$|releases/latest$', url) else 'source_literal',
                                      'resolution': 'template' if re.search(r'[$`{}*\\]|__\w+__', url) else 'declared',
                                      'sources': [ref(path, item['line'])], 'selection': [context(path)]}
                    if url.endswith('.git') or url.startswith(('git@', 'ssh://', 'git://')):
                        row.pop('kind')
                        row['authentication'] = 'ssh_identity_required' if url.startswith(('git@', 'ssh://')) else 'public'
                        clones.append(row)
                    else:
                        downloads.append(row)
    def coalesce(rows):
        grouped = {}
        for row in rows:
            base = {key: value for key, value in row.items() if key not in {'sources', 'selection'}}
            key = json.dumps(base, sort_keys=True)
            merged = grouped.setdefault(key, dict(base, sources=[], selection=[]))
            merged['sources'].extend(row['sources'])
            merged['selection'].extend(row['selection'])
        for row in grouped.values():
            row['sources'], row['selection'] = unique(row['sources']), unique(row['selection'])
        return sorted(grouped.values(), key=lambda row: (row['name'], row['url']))
    return coalesce(downloads), coalesce(clones), [{'url': url, 'sources': unique(sources)} for url, sources in sorted(references.items())]


def npm_environments(variables: Variables) -> list[dict]:
    """Keep each public profile's package, registry and Node pins together."""
    grouped = {}
    fields = {'name': 'PACKAGE_NAME', 'version': 'VERSION', 'url': 'URL', 'sha512': 'SHA512',
              'integrity': 'NPM_INTEGRITY', 'registry_url': 'NPM_REGISTRY_URL', 'node_root': 'NODE_ROOT',
              'node_requirement': 'NODE_REQUIREMENT'}
    for path, settings in variables.local.items():
        profile = context(path).get('profile')
        if not profile or 'DEVOPS_WRANGLER_VERSION' not in settings:
            continue

        def one(key):
            values = {expanded for value in settings.get(key, set()) for expanded in variables.expand(value, path)}
            if len(values) != 1:
                raise ValueError('npm profile requires one literal declaration for ' + key)
            value = next(iter(values))
            if re.search(r'[$`{}]|__\w+__', value):
                raise ValueError('npm profile contains an unresolved declaration for ' + key)
            return value

        environment = {key: one('DEVOPS_WRANGLER_' + suffix) for key, suffix in fields.items()}
        roots = [key.removesuffix('_INSTALL_ROOT') for key, values in settings.items()
                 if re.fullmatch(r'DEVOPS_NODE_[0-9]+_INSTALL_ROOT', key) and environment['node_root'] in values]
        if len(roots) != 1:
            raise ValueError('Wrangler Node root lacks one matching pinned Node release')
        environment['node_version'] = one(roots[0] + '_VERSION')
        architecture = one('DEVOPS_UPSTREAM_ARCHITECTURE')
        if architecture not in {'x86_64', 'aarch64'}:
            raise ValueError('unsupported npm target architecture declaration')
        environment['architecture'] = {'x86_64': 'amd64', 'aarch64': 'arm64'}[architecture]
        environment.update(platform='linux', libc='glibc')
        encoded = json.dumps(environment, sort_keys=True)
        grouped.setdefault(encoded, dict(environment, profiles=[], sources=[]))['profiles'].append(profile)
        grouped[encoded]['sources'].append({'path': path})
        if len(grouped) > 128:
            raise ValueError('npm profile environment count exceeds its limit')
    if not grouped:
        raise ValueError('npm installation lacks a pinned public profile environment')
    return [grouped[key] for key in sorted(grouped)]


def python_environments(variables: Variables) -> list[dict]:
    """Keep the local wheel identity bound to its declaring public profiles."""
    grouped = {}
    fields = {'version': 'VERSION', 'url': 'URL', 'sha256': 'SHA256',
              'minimum_bytes': 'MINIMUM_BYTES', 'maximum_bytes': 'MAXIMUM_BYTES'}
    for path, settings in variables.local.items():
        profile = context(path).get('profile')
        if not profile or 'LABWC_WAYPAPER_VERSION' not in settings:
            continue
        environment = {'name': 'waypaper'}
        for field, suffix in fields.items():
            key = 'LABWC_WAYPAPER_' + suffix
            values = {expanded for value in settings.get(key, set()) for expanded in variables.expand(value, path)}
            if len(values) != 1:
                raise ValueError('Python wheel profile requires one literal declaration for ' + key)
            value = next(iter(values))
            if re.search(r'[$`{}]|__\w+__', value):
                raise ValueError('Python wheel profile contains an unresolved declaration for ' + key)
            if field.endswith('_bytes'):
                if not value.isdecimal():
                    raise ValueError('Python wheel profile has a nonnumeric archive bound')
                value = int(value)
            environment[field] = value
        if (not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}', environment['version'])
                or not re.fullmatch(r'[a-f0-9]{64}', environment['sha256'])
                or not 16384 <= environment['minimum_bytes'] <= environment['maximum_bytes'] <= 1024**2
                or not re.fullmatch(r'https://files\.pythonhosted\.org/packages/(?:[a-f0-9]+/)+waypaper-'
                                    + re.escape(environment['version']) + r'-py3-none-any\.whl', environment['url'])):
            raise ValueError('Python wheel profile has an invalid immutable archive declaration')
        encoded = json.dumps(environment, sort_keys=True)
        row = grouped.setdefault(encoded, dict(environment, profiles=[], sources=[]))
        row['profiles'].append(profile)
        row['sources'].append({'path': path})
        if len(grouped) > 128:
            raise ValueError('Python wheel environment count exceeds its limit')
    if not grouped:
        raise ValueError('Python installation lacks a pinned public profile wheel')
    return [grouped[key] for key in sorted(grouped)]


def indirect_downloads(scans: dict, variables: Variables) -> list[dict]:
    """Represent discovery protocols and transitive downloads as typed recipes."""
    result = []
    for path, facts in scans.items():
        for plugin in facts.get('plugins', []):
            name, version = plugin['name'], plugin['version']
            helper = next((key for key in scans if key.endswith('/scripts/late/packer-plugins.py')), None)
            constants = {item['name']: item['value'] for item in scans[helper]['variables']} if helper else {}
            community = ast.literal_eval(scans[helper]['constants'].get('COMMUNITY_RELEASES', '{}')) if helper else {}
            base = (f'https://github.com/hashicorp/packer-plugin-{name}/releases/download/v{version}/' if name == 'proxmox'
                    else constants.get('ORIGIN', 'https://releases.hashicorp.com') + f'/packer-plugin-{name}/{version}/')
            item = {'kind': 'packer_plugin', 'name': name, 'version': version, 'repository': plugin['repository'],
                    'base_url': base, 'architectures': ['amd64', 'arm64'], 'sources': [ref(path, plugin['line'])],
                    'selection': {'class': 'addon/devops'}, 'resolution': 'signed_checksum_filename_selection'}
            if name == 'proxmox':
                item['archives'] = [{'architecture': arch,
                    'url': base + f'packer-plugin-{name}_v{version}_x5.0_linux_{arch}.zip',
                    'sha256': community.get((name, version, arch))} for arch in ['amd64', 'arm64']]
                if any(not isinstance(row['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', row['sha256'])
                       for row in item['archives']):
                    raise ValueError('Packer community release lacks its source-pinned digest')
                item['resolution'] = 'source_pinned_release'
            else:
                sums = base + f'packer-plugin-{name}_{version}_SHA256SUMS'
                item.update(checksums_url=sums, signature_url=sums + '.sig', key_url=constants.get('KEY_URL'),
                            signing_key_fingerprint=constants.get('FINGERPRINT'),
                            filename_pattern=f'packer-plugin-{name}_(v)?{version}(_xPROTOCOL)?_linux_ARCH.zip')
            result.append(item)
        for name, encoded in facts.get('constants', {}).items():
            if name == 'RELEASES' and path.endswith('/compz-codecs-install.py'):
                table = ast.literal_eval(encoded)
                tag = next(item['value'] for item in facts['variables'] if item['name'] == 'TAG')
                result.append({'kind': 'architecture_release_table', 'name': '7-Zip-zstd', 'tag': tag,
                    'archives': [{'architecture': arch, 'sha256': fields[2],
                                  'url': f'https://github.com/mcmilk/7-Zip-zstd/releases/download/{tag}/linux-gcc-{fields[0]}.zip'}
                                 for arch, fields in sorted(table.items())], 'sources': [{'path': path}]})
        if facts.get('collections'):
            items = []
            for request in facts['collections']:
                item = {key: request[key] for key in ('type', 'name')}
                if request.get('condition'):
                    condition = request['condition']
                    profiles = []
                    for profile, settings in variables.local.items():
                        if not context(profile).get('profile'):
                            continue
                        values = settings.get(condition['variable'], set())
                        if not values or values - {'true', 'false'} or len(values) != 1:
                            raise ValueError('CrowdSec profile condition lacks one literal boolean')
                        if condition['equals'] in values:
                            profiles.append(context(profile)['profile'])
                    item.update(condition=condition, profiles=sorted(profiles))
                items.append(item)
            result.append({'kind': 'crowdsec_hub', 'phase': 'first_boot', 'selection': {'class': 'addon/crowdsec'},
                'items': unique(items),
                'resolution': 'cscli_hub_index_and_recursive_collection_dependencies',
                'sources': [ref(path, item['line']) for item in facts['collections']]})
        if path.endswith('/scripts/late/devops/main-orchestration.sh'):
            source = {'path': path}
            channels = sorted(variables.global_values.get('DEVOPS_RUSTUP_TOOLCHAIN', set()))
            triples = sorted(variables.global_values.get('DEVOPS_RUSTUP_TARGET_TRIPLE', set()))
            result.append({'kind': 'rustup_distribution', 'toolchains': channels, 'target_triples': triples,
                'profile': 'minimal', 'additional_components': ['rustfmt'],
                'manifest_url_template': 'https://static.rust-lang.org/dist/channel-rust-{toolchain}.toml',
                'resolution': 'rustup_v2_manifest_profiles_minimal_plus_rustfmt_preview',
                'protocol_documentation': 'https://forge.rust-lang.org/infra/channel-layout.html',
                'selection': {'class': 'addon/devops'}, 'sources': [source]})
            for tool in ['DOTSLASH', 'UV']:
                enabled = variables.global_values.get('DEVOPS_' + tool + '_SOURCE_BUILD', set())
                if not enabled.intersection({'1', 'true', 'yes'}):
                    continue
                result.append({'kind': 'cargo_source_install', 'name': tool.lower(),
                    'versions': sorted(variables.global_values.get('DEVOPS_' + tool + '_VERSION', set())),
                    'commits': sorted(variables.global_values.get('DEVOPS_' + tool + '_COMMIT', set())),
                    'repositories': sorted(variables.global_values.get('DEVOPS_' + tool + '_REPOSITORY_URL', set())),
                    'enabled_values': sorted(variables.global_values.get('DEVOPS_' + tool + '_SOURCE_BUILD', set())),
                    'selection': {'class': 'addon/devops', 'requires_source_build_flag': '1'},
                    'resolution': 'git_revision_or_crates_io_version_plus_locked_cargo_dependencies', 'sources': [source]})
        if path.endswith('/scripts/desktop/labwc.sh'):
            installer_urls = sorted(variables.global_values.get('DEVOPS_CODEX_STANDALONE_INSTALLER_URL', set()))
            if installer_urls:
                helper = PREFIX + 'hooks/target/usr/local/bin/codex-standalone-install'
                pins = [item['value'] for item in scans.get(helper, {}).get('variables', [])
                        if item['name'] == 'installer_sha256']
                if len(pins) != 1 or not re.fullmatch(r'[a-f0-9]{64}', pins[0]):
                    raise ValueError('standalone Codex installer lacks its exact source digest pin')
                result.append({'kind': 'codex_standalone_distribution', 'name': 'codex-standalone',
                    'installer_urls': installer_urls, 'installer_sha256': pins[0], 'release': 'latest',
                    'resolution': 'official_installer_owned_package_manifest_and_architecture_downloads',
                    'requires_all_classes': ['addon/devops', 'role/desktop'],
                    'selection': {'class': 'addon/devops', 'phase': 'late'},
                    'sources': [{'path': path}, {'path': helper}]})
        if path.endswith('/scripts/late/devops-tools.py'):
            result.append({'kind': 'npm_dependencies', 'name': 'wrangler',
                'environments': npm_environments(variables),
                'versions': sorted(variables.global_values.get('DEVOPS_WRANGLER_VERSION', set())),
                'registry_urls': sorted(variables.global_values.get('DEVOPS_WRANGLER_NPM_REGISTRY_URL', set())),
                'resolution': 'package_json_dependencies_and_optional_dependencies_using_npm_semver',
                'omit': ['dev'], 'package_lock': False, 'lifecycle_scripts_enabled': True,
                'selection': {'class': 'addon/devops'}, 'sources': [{'path': path}]})
        if path.endswith('/scripts/desktop/waypaper.sh'):
            contract = facts['constants'].get('WAYPAPER_PIPX_CONTRACT')
            if not contract:
                raise ValueError('Waypaper source lacks its reviewed pipx installation contract')
            result.append({'kind': 'python_dependencies', 'name': 'waypaper',
                'versions': sorted(variables.global_values.get('LABWC_WAYPAPER_VERSION', set())),
                'environments': python_environments(variables), 'installer_policy': contract,
                'checkout_uv_entrypoints': [key for key in scans if key in {
                    PREFIX + 'hooks/target/usr/local/bin/uv', PREFIX + 'hooks/target/usr/bin/uv',
                    PREFIX + 'hooks/target/usr/lib/python3/dist-packages/uv/__init__.py'}],
                'resolution': 'wheel_METADATA_Requires-Dist_with_target_python_markers_and_system_site_packages',
                'binary_only': True, 'python': '/usr/bin/python3', 'system_site_packages': True,
                'selection': {'class': 'role/desktop', 'phase': 'late'}, 'sources': [{'path': path}]})
        if path.endswith('/APTRepoLocal/Servicing/Discord.pm'):
            manifest = next((item['url'] for item in facts['urls'] if '/manifests/latest?' in item['url']), None)
            helper = PREFIX + 'hooks/target/usr/local/libexec/discord-distro'
            policy = {key: ast.literal_eval(value) for key, value in scans.get(helper, {}).get('constants', {}).items()}
            required_policy = {'APPROVED_DISTRO_HOSTS', 'REQUIRED_MODULES', 'MANIFEST_FIELDS', 'HOST_FULL_FIELDS', 'HOST_DELTA_FIELDS',
                               'MODULE_FIELDS', 'MODULE_FULL_FIELDS', 'MODULE_DELTA_FIELDS', 'MAX_DELTAS'}
            if policy.keys() != required_policy or not manifest:
                raise ValueError('Discord distribution source lacks its complete manifest policy')
            result.append({'kind': 'discord_distribution', 'manifest_url': manifest,
                'architectures': ['amd64'],
                'manifest_policy': policy,
                'resolution': 'manifest_host_and_all_modules_full_distro_urls_and_sha256',
                'module_selection': 'all_modules_in_manifest', 'sources': [{'path': path}],
                'selection': {'class': 'addon/software'}, 'phase': 'installation_and_updates'})
    classes = {item['Group'] + '/' + item['Name']: item for facts in scans.values() for item in facts['classes']}
    for item in result:
        todo, enabled = [item.get('selection', {}).get('class')], set()
        while todo:
            key = todo.pop()
            if not key or key in enabled:
                continue
            enabled.add(key)
            todo.extend(re.split(r'[,\s]+', classes.get(key, {}).get('RequiresClasses', '')))
        required = {key.split('/', 1)[1] for key in enabled if key.startswith('arch/')}
        architectures = sorted(required or {'amd64', 'arm64'})
        if len(required) > 1 or set(architectures) - {'amd64', 'arm64'}:
            raise ValueError('indirect download has inconsistent class architecture requirements')
        item['architectures'] = [arch for arch in item.get('architectures', architectures) if arch in architectures]
        if 'archives' in item:
            item['archives'] = [row for row in item['archives'] if row.get('architecture') in item['architectures']]
        item['id'] = 'protocol-' + digest(json.dumps(item, sort_keys=True).encode())[:24]
        item['status'] = ('resolved_literal' if item.get('archives') and all(row.get('sha256') for row in item['archives'])
                          else 'requires_metadata_refresh')
    return unique(result)


def apt_declarations(scans: dict) -> dict:
    variables = Variables(scans)
    requests, exclusions, dynamic = package_requests(scans, variables)
    pins, classes = [], []
    for path, facts in scans.items():
        pins.extend(dict(item, source=ref(path, item['line'])) for item in facts['pins'])
        classes.extend(dict(item, source=ref(path, item['line'])) for item in facts['classes'])
    preferences, _ = policy_context(scans, pins, classes)
    post_install_default, upgrades = {}, []
    for path, facts in scans.items():
        upgrades.extend(dict(item, source=ref(path, item['line'])) for item in facts['settings']
                        if item['question'] == 'pkgsel/upgrade')
        if path == PREFIX + 'hooks/installer/finish-install.d/95-normalize-apt':
            suites = [item for item in facts['variables'] if item['name'] == 'default_release_suite']
            if len(suites) != 1 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', suites[0]['value']):
                raise ValueError('finish-install default-release declaration is ambiguous')
            post_install_default = {'suite': suites[0]['value'], 'source': ref(path, suites[0]['line']),
                                    'phases': ['first_boot', 'installed_capability']}
    upgrade_modes = {item['value'] for item in upgrades}
    if len(upgrade_modes) > 1 or upgrade_modes - {'none', 'safe-upgrade', 'full-upgrade'}:
        raise ValueError('pkgsel base upgrade policy requires an explicit conditional adapter')
    return {'repositories': repositories(scans), 'pin_rules': pins, 'classes': classes,
            'requests': requests, 'dynamic_requests': dynamic, 'exclusions': exclusions,
            'global_preferences': sorted(preferences),
            'post_install_default_release': post_install_default,
            'base_upgrade': {'mode': next(iter(upgrade_modes), 'none'), 'sources': upgrades},
            'profiles': sorted({context(path)['profile'] for path in scans if context(path).get('profile')}),
            'installation_settings': [dict(item, source=ref(path, item['line']), **context(path))
                                      for path, facts in scans.items() for item in facts['settings']]}


def git_declarations(rows: list) -> list:
    """Coalesce declarations and literal adapters for the same checkout ref."""
    grouped = {}
    for row in rows:
        if row.get('source_build') in {'0', 'false', 'no'}:
            continue
        identity = {key: row.get(key) for key in ('url', 'branch', 'commit', 'revision', 'tag')}
        encoded = json.dumps(identity, sort_keys=True)
        item = grouped.setdefault(encoded, dict(identity, id='git-' + digest(encoded.encode())[:24],
            names=[], sources=[], selection=[], consumers=[], authentication=row['authentication']))
        item['names'].append(row['name'])
        for key in ('sources', 'selection', 'consumers'):
            item[key].extend(row.get(key, []))
    for item in grouped.values():
        item['names'] = sorted(set(item['names']))
        for key in ('sources', 'selection', 'consumers'):
            item[key] = unique(item[key])
        if any(selection.get('class') for selection in item['selection']):
            item['selection'] = [selection for selection in item['selection'] if selection.get('class')]
        item['resolution'] = 'pinned_commit' if item.get('commit') or item.get('revision') else 'moving_ref'
    return sorted(grouped.values(), key=lambda item: item['id'])


def download_records(apt: dict, artifacts: list) -> list:
    """Canonical, directly consumable URL/size/hash records, with stable IDs."""
    records = {}

    def add(url, kind, **fields):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return None
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or port not in {None, 443}
                or parsed.hostname in {'localhost', 'localhost.localdomain'}
                or parsed.hostname.endswith(('.localhost', '.local', '.internal'))
                or not re.fullmatch(r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}', parsed.hostname)
                or re.search(r'[$`{}*\\]|__\w+__|@@\w+@@', url)):
            return None
        if clean_url(url) != url or '[redacted]' in url:
            return None
        for field, width in (('sha256', 64), ('sha512', 128)):
            if field in fields and not re.fullmatch('[a-fA-F0-9]{' + str(width) + '}', fields[field]):
                return None
            if field in fields:
                fields[field] = fields[field].lower()
        if 'fingerprint' in fields and not re.fullmatch(r'[A-Fa-f0-9]{40}', fields['fingerprint']):
            return None
        if 'fingerprint' in fields:
            fields['fingerprint'] = fields['fingerprint'].upper()
        if 'fallback_urls' in fields:
            fallbacks = fields['fallback_urls']
            if (not isinstance(fallbacks, list) or len(fallbacks) > 4 or any(
                    not isinstance(value, str) or not value.startswith('https://') or clean_url(value) != value
                    or re.search(r'[$`{}*\\]|__\w+__|@@\w+@@', value) for value in fallbacks)):
                raise ValueError('invalid concrete download fallback URL declaration')
        key = 'download-' + digest(url.encode())[:24]
        candidate = dict(id=key, kinds=[kind], url=url, **fields)
        previous = records.setdefault(key, candidate)
        if previous != candidate:
            # Shared source tarballs may belong to multiple source versions;
            # their byte identity must agree, while provenance may be merged.
            for field in ('size', 'sha256', 'sha512', 'fingerprint', 'byte_identity'):
                if previous.get(field) and candidate.get(field) and previous[field] != candidate[field]:
                    raise ValueError('one download URL declares conflicting byte identities')
            previous['kinds'] = sorted(set(previous['kinds']) | {kind})
            for field in ('size', 'sha256', 'sha512', 'fingerprint', 'byte_identity'):
                if field not in previous and field in candidate:
                    previous[field] = candidate[field]
            if candidate.get('fallback_urls'):
                previous['fallback_urls'] = sorted(set(previous.get('fallback_urls', [])) | set(candidate['fallback_urls']))
        return key

    for row in apt.get('packages', []):
        row['download_id'] = add(row['url'], row['type'], size=row['size'], sha256=row['sha256'])
    for row in apt.get('source_packages', []):
        for item in row['files']:
            item['download_id'] = add(item['url'], 'apt_source', size=item['size'], sha256=item['sha256'])
    for row in apt['repositories']:
        row['key_download_ids'] = [identifier for url in row.get('key_urls', [])
                                   if (identifier := add(url, 'apt_signing_key'))]
    for row in artifacts:
        if row.get('kind') in {'service_endpoint', 'metadata'}:
            continue
        url = row['url']
        # Base URLs, APIs and arbitrary string references are not file downloads.
        if row.get('kind') == 'source_literal' and not archive_url(url):
            continue
        fields = {key: row[key] for key in ('size', 'sha256', 'sha512', 'fingerprint', 'architecture', 'version',
                                            'fallback_urls', 'byte_identity') if key in row}
        identifier = add(url, row.get('kind', 'external'), **fields)
        if identifier:
            row['download_id'] = identifier
    return sorted(records.values(), key=lambda row: row['url'])


def assemble(scans: dict, metadata: dict, *, resolved_recipes: list | None = None) -> dict:
    variables = Variables(scans)
    apt = apt_declarations(scans)
    downloads, clones, _ = artifacts(scans, variables)
    discovery_endpoints = [row for row in downloads if row.get('kind') in {'metadata', 'service_endpoint'}]
    downloads = [row for row in downloads if row not in discovery_endpoints
                 and (row.get('kind') != 'source_literal' or archive_url(row['url']))]
    # A disabled source-build branch is a declaration, not a Git download.
    clones = git_declarations(clones)
    operations, modules, transfers = [], [], []
    for path, facts in scans.items():
        operations.extend(dict(item, source=ref(path, item['line']), **context(path)) for item in facts['operations'])
        modules.extend(dict(item, source=ref(path, item['line'])) for item in facts['modules'])
        transfers.extend(dict(item, source=ref(path, item['line']), **context(path)) for item in facts['transfers'])
    apt.update(metadata or {'acquired': False, 'packages': [], 'source_packages': [],
                            'releases': {}, 'indexes': [], 'unresolved': []})
    request_links = defaultdict(set)
    for row in apt['packages']:
        for use in row.get('uses', []):
            if use.get('reason') == 'explicit_request':
                request_links[use['request_id']].add(row['url'])
    for request in apt['requests']:
        request['selected_urls'] = sorted(request_links[request['id']])
        request['status'] = ('selected' if request['selected_urls'] else 'unresolved'
                             if apt['acquired'] else 'requires_metadata_refresh')
    recipes = indirect_downloads(scans, variables) if resolved_recipes is None else resolved_recipes
    embedded_files = []
    for recipe in recipes:
        embedded_files.extend(dict(item, protocol_id=recipe['id'], sources=recipe['sources'])
                              for item in recipe.get('embedded_files', []))
        for archive in recipe.get('archives', []):
            fields = dict(archive)
            fields.setdefault('selection', [recipe.get('selection', {})])
            downloads.append(dict(fields, name=recipe.get('name', recipe['kind']), kind=recipe['kind'],
                                  protocol_id=recipe['id'], sources=recipe['sources'],
                                  resolution=recipe['status']))
        for item in recipe.get('metadata_files', []):
            downloads.append(dict(item, name=recipe.get('name', recipe['kind']), kind='protocol_metadata',
                                  protocol_id=recipe['id'], sources=recipe['sources'],
                                  selection=[recipe.get('selection', {})], resolution='declared'))
    for name in ('payload.manifest', 'payload.tar.gz'):
        transfers.append({'kind': 'installer_bootstrap', 'path': name,
                          'selection': {'phase': 'installer_bootstrap'},
                          'resolution': 'generated_bootstrap_artifact'})
    catalog = download_records(apt, downloads)
    incomplete_artifacts = [row['name'] for row in downloads
                            if row.get('kind') != 'service_endpoint' and not row.get('download_id')]
    missing_requests = [row['selector'] for row in apt['requests'] if not row['selected_urls']]
    protocol_complete = all(item['status'] in {'resolved', 'resolved_literal'} for item in recipes)
    download_plan_complete = bool(apt.get('acquired') and not missing_requests and not apt.get('unresolved')
                                  and not incomplete_artifacts and protocol_complete)
    limits = [
        'Static metadata selection is not a verified libapt transaction; conflicts and installed-state changes need transaction evidence.',
        'Rolling endpoints, indirect package managers and dynamic shell expressions require their recorded discovery protocol.',
        'Release and index hashes establish byte consistency; OpenPGP signature verification has not been performed.',
    ]
    return {'schema': {'name': 'debian-preseed-download-inventory', 'version': SCHEMA,
                       'ordering': 'deterministic keys and arrays; repository order follows installer definitions'},
            'scope': {'scan_input': PREFIX.rstrip('/'), 'architectures': ['amd64', 'arm64'],
                      'selection': 'conditional_installer_classes_and_profiles',
                      'network_during_scan': False, 'installer_code_executed': False,
                      'standalone_manual_tool': True},
            'apt': apt, 'downloads': catalog, 'external_artifacts': downloads,
            'embedded_files': embedded_files,
            'discovery_endpoints': discovery_endpoints,
            'git_repositories': clones, 'indirect_downloads': recipes,
            'kernel_module_operations': unique(modules), 'repository_transfers': unique(transfers),
            'download_operations': unique(operations),
            'coverage': {'source_files': len(scans), 'apt_repositories': len(apt['repositories']),
                         'apt_requests': len(apt['requests']), 'apt_selected_binaries': len(apt['packages']),
                         'apt_selected_sources': len(apt['source_packages']),
                         'embedded_files': len(embedded_files),
                         'missing_package_requests': missing_requests,
                         'unresolved_artifacts': sorted(set(incomplete_artifacts)),
                         'requires_indirect_resolution': sum(item['status'] not in {'resolved', 'resolved_literal'} for item in recipes),
                         'limitations': limits,
                         'source_diagnostics': [dict(item, path=path) for path, facts in scans.items()
                                                for item in facts['diagnostics']],
                         'download_plan_complete': download_plan_complete}}


def existing_document(path: Path) -> tuple[bytes | None, dict]:
    try:
        raw = read_file(path, MAX_JSON)
    except FileNotFoundError:
        return None, {}
    try:
        value = json.loads(raw, object_pairs_hook=json_pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        return raw, {}
    return raw, value if isinstance(value, dict) else {}


def generator_identity() -> dict:
    fingerprint = hashlib.sha256()
    directory = Path(__file__).resolve().parent
    for name in ('inventory.py', 'inventory_apt.py'):
        fingerprint.update(name.encode('ascii') + b'\0' + hashlib.sha256(read_file(directory / name)).digest())
    return {'path': 'tools/inventory.py', 'version': GENERATOR_VERSION, 'sha256': fingerprint.hexdigest()}


def current_inventory(value: dict, stamp: dict, *, require_apt: bool, generator: dict) -> bool:
    apt = value.get('apt')
    integrity = value.get('content_sha256')
    if (not isinstance(integrity, str) or not re.fullmatch('[a-f0-9]{64}', integrity)
            or integrity != digest(encode({key: item for key, item in value.items() if key != 'content_sha256'}))):
        return False
    return (value.get('schema_version') == SCHEMA
            and value.get('schema') == {'name': 'debian-preseed-download-inventory', 'version': SCHEMA,
                'ordering': 'deterministic keys and arrays; repository order follows installer definitions'}
            and value.get('source') == stamp
            and value.get('generator') == generator
            and isinstance(apt, dict) and (not require_apt or apt.get('acquired') is True)
            and isinstance(apt.get('packages'), list) and isinstance(apt.get('source_packages'), list)
            and isinstance(value.get('downloads'), list))


def generate(root: Path = ROOT, *, refresh_apt: bool = False, force: bool = False) -> tuple[bytes, dict]:
    root = root.resolve(strict=True)
    generator = generator_identity()
    scans, stamp, identities = scan_checkout(root)
    old_raw, old = existing_document(root / 'inventory.json')
    stats = {'text_files_scanned': len(scans), 'source_files': stamp['files']}
    # A requested metadata refresh must observe rolling APT archives and
    # indirect channels again even when checkout declarations are unchanged.
    if not force and not refresh_apt and current_inventory(old, stamp, require_apt=False, generator=generator):
        if not unchanged_checkout(root, identities) or generator_identity() != generator:
            raise ValueError('checkout changed during discovery; previous inventory retained')
        return old_raw, dict(stats, current=True, written=False)
    metadata, recipes = {}, indirect_downloads(scans, Variables(scans))
    if refresh_apt:
        # Load precisely the sibling collector without adding checkout paths
        # to sys.path, where they could shadow standard-library modules.
        specification = importlib.util.spec_from_file_location(
            '_standalone_inventory_apt', Path(__file__).resolve().with_name('inventory_apt.py'))
        if specification is None or specification.loader is None:
            raise ValueError('standalone inventory collector is unavailable')
        collector = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(collector)
        try:
            metadata = collector.refresh(root, apt_declarations(scans), stamp, resolve_catalog)
            recipes = collector.resolve_indirect(recipes, apt=metadata)
        except collector.sqlite3.Error as error:
            raise ValueError('private APT catalog failed: ' + type(error).__name__) from error
    result = {'schema_version': SCHEMA, 'source': stamp,
              'generator': generator,
              **assemble(scans, metadata, resolved_recipes=recipes)}
    result['coverage'].update(stats)
    # This checks document byte consistency, not publisher authenticity.
    result['content_sha256'] = digest(encode(result))
    data = encode(result)
    if len(data) > MAX_JSON:
        raise ValueError('generated inventory exceeds byte limit')
    if not unchanged_checkout(root, identities) or generator_identity() != generator:
        raise ValueError('checkout changed during generation; previous inventory retained')
    return data, dict(stats, current=False)


UNSPECIFIED = object()


def atomic_write(path: Path, data: bytes, mode: int, *, expected=UNSPECIFIED, receipt=None) -> None:
    """Private, durable single-file replacement, with a verified final identity."""
    if (not path.is_absolute() or '..' in path.parts
            or path.parent.resolve(strict=True) != path.parent):
        raise ValueError('inventory destination must have canonical parents')
    before = None
    try:
        before = path.lstat()
    except FileNotFoundError:
        pass
    if before is not None and (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                               or before.st_uid != os.geteuid()):
        raise ValueError('unsafe inventory publication destination')
    if expected is not UNSPECIFIED and expected != (None if before is None else file_identity(before)):
        raise ValueError('inventory destination changed before publication')
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
            identity = file_identity(os.fstat(stream.fileno()))
            if receipt is not None:
                receipt['candidate'] = identity[:5]
        try:
            now = path.lstat()
        except FileNotFoundError:
            now = None
        if (None if before is None else file_identity(before)) != (None if now is None else file_identity(now)):
            raise ValueError('inventory destination changed before replacement')
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        after = path.lstat()
        # rename changes ctime on some filesystems; preserve the pinned inode,
        # mode, size and content identity rather than assuming ctime stability.
        if ((after.st_dev, after.st_ino, after.st_mode, after.st_size) != identity[:4]
                or after.st_uid != os.geteuid() or after.st_nlink != 1
                or read_file(path, MAX_JSON) != data):
            raise ValueError('inventory publication postcondition failed')
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def generation_lock(root: Path):
    """Serialize inventory writers without an extra persistent lock artifact."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('inventory generation is already running') from None
        if next(root.glob('.inventory-recovery-*'), None) is not None:
            raise ValueError('inventory recovery material exists; resolve the previous publication before retrying')
        yield
    finally:
        os.close(descriptor)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publication_state(path: Path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        raise ValueError('unsafe inventory output')
    data = read_file(path, MAX_JSON)
    if file_identity(info) != file_identity(path.lstat()):
        raise ValueError('inventory output changed while taking its snapshot')
    return data, stat.S_IMODE(info.st_mode), file_identity(info)


def publish_products(root: Path, products: dict[str, bytes]) -> bool:
    """Publish one product; restore only a pinned candidate or retain evidence."""
    if (set(products) != {'inventory.json'} or type(products['inventory.json']) is not bytes
            or len(products['inventory.json']) > MAX_JSON):
        raise ValueError('publication requires only bounded inventory.json bytes')
    data, path = products['inventory.json'], root / 'inventory.json'
    previous = publication_state(path)
    if previous is not None and previous[:2] == (data, 0o644):
        return False
    recovery = Path(tempfile.mkdtemp(prefix='.inventory-recovery-', dir=root))
    receipt, attempted, retain = {}, False, False
    try:
        if previous is not None:
            atomic_write(recovery / 'inventory.json', previous[0], 0o600)
        atomic_write(recovery / 'state.json', encode({'previous_mode': previous[1] if previous else None,
            'previous_sha256': digest(previous[0]) if previous else None,
            'candidate_sha256': digest(data)}), 0o600)
        sync_directory(recovery)
        sync_directory(root)
        attempted = True
        atomic_write(path, data, 0o644, expected=previous[2] if previous else None, receipt=receipt)
    except BaseException as error:
        if attempted:
            try:
                current = publication_state(path)
                if current == previous:
                    pass  # Failure occurred before replacement; prove exact old state.
                elif (current is not None and current[0] == data
                      and current[2][:5] == receipt.get('candidate')):
                    if previous is None:
                        # The writer lock also owns cleanup. Restat the pinned
                        # candidate immediately before removing our publication.
                        if file_identity(path.lstat()) != current[2]:
                            raise ValueError('inventory candidate identity changed before restoration')
                        path.unlink()
                        sync_directory(root)
                    else:
                        atomic_write(path, previous[0], previous[1], expected=current[2])
                    restored = publication_state(path)
                    if ((previous is None and restored is not None)
                            or (previous is not None and (restored is None or restored[:2] != previous[:2]))):
                        raise ValueError('inventory restoration postcondition failed')
                else:
                    raise ValueError('publication identity is uncertain; no foreign output was overwritten')
            except BaseException:
                retain = True
                raise ValueError('inventory publication outcome unknown; recovery retained at ' + str(recovery)) from error
        raise
    finally:
        if not retain:
            for item in recovery.iterdir():
                item.unlink()
            recovery.rmdir()
            sync_directory(root)
    return True


def publish(root: Path = ROOT, *, refresh_apt: bool = False, force: bool = False) -> dict:
    root = root.resolve(strict=True)
    with generation_lock(root):
        data, stats = generate(root, refresh_apt=refresh_apt, force=force)
        if not stats['current']:
            stats['written'] = publish_products(root, {'inventory.json': data})
        return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-apt', action='store_true', help='refresh public APT and declared download manifests; embed selected binaries, sources and protocol files in inventory.json')
    parser.add_argument('--force', action='store_true', help='regenerate offline discovery even when source and generator fingerprints are unchanged')
    args = parser.parse_args()
    try:
        stats = publish(refresh_apt=args.refresh_apt, force=args.force)
        if stats['current']:
            print('inventory.json is already up to date')
        else:
            print(f'inventory: inventory.json generated from {stats["text_files_scanned"]} installer source files')
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, EOFError) as error:
        print('inventory failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
