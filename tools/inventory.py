#!/usr/bin/env python3
"""Serialize download declarations from payload.tar.gz, without execution.

Normal generation is offline, uses only checkout files, and writes only
inventory.json. --refresh-apt is a separate, explicit metadata acquisition step;
it never runs apt, dpkg, shell snippets, installed helpers or package code.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from contextlib import contextmanager
import fcntl
import fnmatch
from functools import cmp_to_key
import hashlib
import gzip
import io
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publication import atomic_write

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'd-i/forky/'
SCHEMA = 3
GENERATOR_VERSION = 2
PAYLOAD = PREFIX + 'payload.tar.gz'
APT_SNAPSHOT = 'inventory-apt.json'
MAX_FILE = 16 * 1024**2
MAX_JSON = 128 * 1024**2
MAX_TOTAL = 256 * 1024**2
MAX_MEMBERS = 20000
MAX_PAYLOAD = 128 * 1024**2
MAX_EXPANSIONS = 128
PRIVATE = {'preseed.env', 'git_ed25519', 'git_ed25519.pub', 'id_git_ed25519'}
BINARY = {'.png', '.jpeg', '.jpg', '.gif', '.ico', '.ttf', '.otf', '.woff',
          '.woff2', '.gz', '.xz', '.zip', '.deb', '.udeb', '.pdf', '.webp'}
SECRET = re.compile(r'(?i)(?:password|passwd|token|secret|credential|api_?key|access_?key|private_?key|passphrase)')
ASSIGN = re.compile(r'^\s*(?:export\s+|local\s+)?([A-Za-z_]\w*)=(.*)$')
DEBCONF = re.compile(r'^\s*(\S+)\s+(\S+)\s+(string|select|multiselect|boolean)\s+(.*?)\s*$')
URL = re.compile(r'(?:https?|ftp|ssh|git)://[^\s\x22\x27<>`]+|git@[A-Za-z0-9.-]+:[A-Za-z0-9_./+-]+')
VARIABLE = re.compile(r'\$\{([A-Za-z_]\w*)(?:(:-|-)([^{}]*))?\}|\$([A-Za-z_]\w*)')
PACKAGE = re.compile(r'[a-z0-9][a-z0-9+.-]*(?::(?:any|native|amd64|arm64))?(?:[=/][A-Za-z0-9.+:~_-]+)?\Z')
NETWORK = re.compile(r'(?i)\b(?:curl|wget|urlopen|download_file|fetch_url|source_transfer|source_http_get|'
                     r'git\s+(?:clone|fetch|checkout|switch)|managed_git_ssh_target_action|'
                     r'apt-get|anna-install|cscli\s+hub|cscli\s+collections|'
                     r'cargo\s+install|rustup\s+(?:component|target|toolchain)|'
                     r'pipx?\s+install|npm\s+install|packer\s+init|podman\s+pull)\b')
INTEREST = re.compile(r'(?i)(?:url|uri|repository|branch|commit|revision|sha256|sha512|version|'
                      r'tag|architecture|target_triple|toolchain|kernel|packages|apt_deps|modules|apt_preferences|source_build|release)')
TRANSFER_COMMANDS = {'source_transfer', 'fetch_hook_file', 'bootstrap_source_module',
                     'installer_fetch_seed_path'}
CUDA_LEGACY_URL = 'https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/'
CUDA_LEGACY_OPTIONS = ('arch=amd64 trusted=yes allow-insecure=yes allow-weak=yes '
                       'allow-downgrade-to-insecure=yes check-valid-until=no check-date=no')


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


def apt_snapshot_path(root: Path) -> Path:
    """Return the one canonical APT snapshot at the repository root."""
    return root / APT_SNAPSHOT


def metadata_value(metadata: dict, name: str, default):
    """Read one collection from the structured APT snapshot."""
    sections = {
        'requested_packages': ('request_set', 'packages'),
        'releases': ('release_files',),
        'indexes': ('package_indexes',),
        'packages': ('candidates', 'records'),
    }
    cursor = metadata
    for key in sections.get(name, ()):
        cursor = cursor.get(key, {}) if isinstance(cursor, dict) else {}
    return cursor if cursor not in ({}, None) else default


class ArchiveReader:
    """Bound decompression, including headers/extensions, before tarfile allocates."""
    def __init__(self, stream):
        self.stream = stream
        self.remaining = MAX_TOTAL + MAX_MEMBERS * 2048 + 10240

    def read(self, size):
        if size < 0 or size > self.remaining:
            raise ValueError('payload expansion limit exceeded')
        data = self.stream.read(min(size, self.remaining + 1))
        self.remaining -= len(data)
        if self.remaining < 0:
            raise ValueError('payload expansion limit exceeded')
        return data


def scan_payload(raw: bytes) -> tuple[dict, dict]:
    """Read regular archive members as data. Never extract or read loose sources."""
    scans, names, total, text_files = {}, set(), 0, 0
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        reader = ArchiveReader(compressed)
        with tarfile.open(fileobj=reader, mode='r|', encoding='utf-8', errors='strict') as archive:
            for item in archive:
                name = item.name
                path = PurePosixPath(name)
                if (not re.fullmatch(r'[A-Za-z0-9_./@+-]+', name) or path.is_absolute()
                        or '..' in path.parts or path.as_posix() != name or not path.parts
                        or path.name in PRIVATE or name in {'payload.tar.gz', 'payload.manifest', 'preseed.cfg'}
                        or not item.isreg() or item.sparse or item.pax_headers or item.mode & 0o7000):
                    raise ValueError('unsupported or unsafe payload member')
                if name in names:
                    raise ValueError('duplicate payload member')
                names.add(name)
                total += item.size
                if len(names) > MAX_MEMBERS or not 0 <= item.size <= MAX_FILE or total > MAX_TOTAL:
                    raise ValueError('payload member or byte limit exceeded')
                archive.members.clear()
                if path.suffix.lower() in BINARY or '/backup/' in '/' + name or name.endswith(('.md', '.md.tmpl')):
                    continue
                stream = archive.extractfile(item)
                if stream is None:
                    raise ValueError('unreadable payload member')
                with stream:
                    data = stream.read(item.size + 1)
                if len(data) != item.size:
                    raise ValueError('truncated payload member')
                if re.match(rb'\s*-----BEGIN (?:OPENSSH |RSA |EC |DSA |ENCRYPTED )?PRIVATE KEY-----', data[:256]):
                    raise ValueError('private key in payload')
                if b'\0' in data:
                    continue
                try:
                    text = data.decode('utf-8')
                except UnicodeDecodeError:
                    continue
                text_files += 1
                facts = scan_file(PREFIX + name, text)
                relevant = (any(facts[key] for key in ('packages', 'settings', 'pins', 'classes', 'sources',
                             'operations', 'transfers', 'modules', 'constants', 'plugins', 'collections', 'urls'))
                            or any(INTEREST.search(row['name']) for row in facts['variables']))
                if relevant:
                    scans[PREFIX + name] = facts
        # Consume the remainder to check gzip integrity and the expansion bound.
        while reader.read(min(65536, reader.remaining)):
            if not reader.remaining:
                raise ValueError('payload expansion limit exceeded')
    if not names:
        raise ValueError('empty payload archive')
    return dict(sorted(scans.items())), {'payload_members': len(names), 'payload_bytes': total,
                                        'text_files_scanned': text_files, 'source_files': len(scans)}


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
        return {'class': 'role/desktop', 'phase': 'installation'}
    match = re.search(r'/scripts/late/(devops|software|whisper|ch341a|qemu|crowdsec|tailscale|cuda-legacy)(?:[./-])', name)
    if match:
        return {'class': 'addon/' + match[1], 'phase': 'installation'}
    if '/hooks/target/' in name:
        return {'phase': 'installed_capability'}
    return {'phase': 'installation'}


def package_arguments(statement: str) -> list[tuple[str, str]]:
    if not re.search(r'\b(?:apt(?:-get)?|anna-install|(?:hook_)?(?:ensure|preload|try)_installer_\w+)\b', statement):
        return []
    # Commands are only tokenized, never evaluated or executed.
    try:
        tokens = shlex.split(statement, comments=True)
    except ValueError:
        return []
    return package_tokens(tokens)


def package_tokens(tokens: list[str]) -> list[tuple[str, str]]:
    """Read literal argv data shared by shell and Python consumers."""
    result = []
    for pos, token in enumerate(tokens):
        command = token.rsplit('/', 1)[-1]
        if command not in {'apt', 'apt-get'}:
            continue
        words = tokens[pos + 1:]
        action = next((i for i, word in enumerate(words) if word in {'install', 'download', 'build-dep'}), None)
        if action is None:
            continue
        skip = False
        for word in words[action + 1:]:
            if word in {'||', '&&', ';', ')', 'then'} or word.startswith(('>', '<')):
                break
            if skip:
                skip = False
                continue
            if word in {'-o', '-t', '--option', '--target-release'}:
                skip = True
                continue
            if word.startswith('-'):
                continue
            if PACKAGE.fullmatch(word):
                result.append((word, 'deb'))
    for pos, token in enumerate(tokens):
        if token in {'anna-install', 'hook_ensure_installer_udeb', 'hook_preload_installer_udeb', 'hook_try_installer_udeb'}:
            if pos + 1 < len(tokens) and PACKAGE.fullmatch(tokens[pos + 1]):
                result.append((tokens[pos + 1], 'udeb'))
        elif token in {'hook_ensure_installer_command', 'hook_preload_installer_command', 'ensure_installer_command', 'ensure_installer_command_logged'}:
            if pos + 2 < len(tokens) and PACKAGE.fullmatch(tokens[pos + 2]):
                result.append((tokens[pos + 2], 'udeb'))
    return sorted(set(result))


def scan_file(name: str, text: str) -> dict:
    facts = {'variables': [], 'packages': [], 'settings': [], 'urls': [],
             'operations': [], 'transfers': [], 'pins': [], 'classes': [], 'sources': [], 'modules': [], 'constants': {},
             'plugins': [], 'collections': []}
    if name == PREFIX + 'scripts/common/modules/context-target.sh':
        match = re.search(r'(?m)^installer_cuda_source_line\(\) \(\n(.*?)^\)', text, re.S)
        if (match and '[ "$repository" = ' + CUDA_LEGACY_URL + ' ]' in match[1]
                and '[ "$suite" = / ] && [ -z "$components" ]' in match[1]
                and "printf 'deb [" + CUDA_LEGACY_OPTIONS + "] %s /\\n'" in match[1]):
            facts['constants']['CUDA_LEGACY_POLICY'] = {
                'mode': 'source-authorized-insecure', 'temporary': True,
                'options': CUDA_LEGACY_OPTIONS.split(),
                'source': ref(name, text[:match.start()].count('\n') + 1)}
    lines = list(logical_lines(text))
    for number, line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        assignment = ASSIGN.match(line)
        if assignment and not SECRET.search(assignment[1]):
            value = scalar(assignment[2])
            if value is not None and len(value) <= 8192:
                # Private account data and arbitrary profile settings are not cached.
                if INTEREST.search(assignment[1]) or URL.search(value) or VARIABLE.search(value):
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
                            'base-installer/kernel/image', 'anna/choose_modules'}:
                for item in re.split(r'[\s,]+', value):
                    if item != 'none' and PACKAGE.fullmatch(item):
                        facts['packages'].append({'selector': item, 'type': package_type, 'line': number, 'via': question})
        for selector, kind in package_arguments(line):
            facts['packages'].append({'selector': selector, 'type': kind, 'line': number, 'via': 'command'})
        for match in URL.finditer(line):
            facts['urls'].append({'url': clean_url(match.group()), 'line': number})
        if NETWORK.search(line):
            facts['operations'].append({'line': number, 'text': safe_text(stripped)})
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
        match = re.search(r'\bcscli\s+collections\s+install\s+(.+)', line)
        if match:
            facts['collections'].extend({'name': token, 'line': number} for token in match[1].split()
                                        if re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', token))
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
    if name.endswith('.py'):
        try:
            tree = ast.parse(text, filename=name)
        except SyntaxError:
            # A renderable template may not be Python until installation.
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
                        facts['packages'].extend({'selector': selector, 'type': kind, 'line': node.lineno,
                                                  'via': 'python_argv'} for selector, kind in package_tokens(words))
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    key = node.targets[0].id
                    if SECRET.search(key):
                        continue
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, TypeError, SyntaxError):
                        continue
                    if isinstance(value, str) and (INTEREST.search(key) or URL.search(value)):
                        facts['variables'].append({'name': key, 'value': safe_text(value), 'line': node.lineno})
                    # Small literal architecture/ref tables are useful to download consumers.
                    if key in {'RELEASES', 'COMMUNITY_RELEASES'}:
                        facts['constants'][key] = repr(value)
    return facts


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


def pin_matches(rule: dict, package: dict, repo: dict, release: dict) -> bool:
    name = package['package']
    matched = False
    for pattern in rule['packages']:
        target = package.get('source', name).split()[0] if pattern.startswith('src:') else name
        pattern = pattern.removeprefix('src:')
        pattern = re.sub(r':(?:any|native|amd64|arm64)$', '', pattern)
        matched |= fnmatch.fnmatchcase(target, pattern)
    if not matched:
        return False
    kind, _, value = rule['pin'].partition(' ')
    if kind == 'version':
        return fnmatch.fnmatchcase(package['version'], value)
    if kind == 'origin':
        return fnmatch.fnmatchcase(urlsplit(repo['url']).hostname or '', value.strip('"'))
    if kind == 'release':
        fields = {'o': 'Origin', 'l': 'Label', 'a': 'Suite', 'n': 'Codename', 'v': 'Version'}
        for condition in value.split(','):
            key, equal, pattern = condition.strip().partition('=')
            if not equal or key not in fields or not fnmatch.fnmatchcase(release.get(fields[key], ''), pattern):
                return False
        return True
    return False


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


def pin_priority(package: dict, repo: dict, release: dict, rules: list, preferences: set, target_suite=None) -> int:
    default = 500
    if release.get('NotAutomatic') == 'yes':
        default = 100 if release.get('ButAutomaticUpgrades') == 'yes' else 1
    general = []
    for rule in sorted(rules, key=lambda r: (Path(r['source']['path']).name, r['line'])):
        if rule['preference'] not in preferences or not pin_matches(rule, package, repo, release):
            continue
        if rule['packages'] != ['*']:
            return rule['priority']
        general.append(rule['priority'])
    if target_suite and target_suite in {repo['suite'], release.get('Suite'), release.get('Codename')}:
        return 990
    return max(general) if general else default


def repositories(scans: dict) -> list[dict]:
    result = {}

    def add(url, suite, components, source, **extra):
        identifier = repo_id(url, suite)
        row = result.setdefault(identifier, {'id': identifier, 'url': url.rstrip('/'), 'suite': suite,
                    'components': components, 'architectures': ['amd64', 'arm64'], 'definitions': [], **extra})
        row['definitions'].append(source)
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
            row = add(words[0], words[1], words[2:], dict(ref(name, setting['line']), **context(name)), role='class_archive')
            row.setdefault('key_urls', []).extend(URL.findall(settings.get(prefix + 'key', {}).get('value', '')))
            row.setdefault('labels', []).append(settings.get(prefix + 'comment', {}).get('value', ''))
            row['source_packages_enabled'] = settings.get(prefix + 'source', {}).get('value') == 'true'
        for fields in facts['sources']:
            if fields.get('Enabled', 'yes').lower() == 'no':
                continue
            for url, suite in itertools.product(fields['URIs'].split(), fields.get('Suites', './').split()):
                if url.startswith(('https://', 'http://')):
                    add(url, suite, fields.get('Components', '').split(), ref(name, fields['line']), role='installed_source')
    for row in result.values():
        row['definitions'] = unique(row['definitions'])
        row['key_urls'] = sorted(set(row.get('key_urls', [])))
        row['labels'] = sorted(set(row.get('labels', [])))
        if row['url'] == CUDA_LEGACY_URL.rstrip('/') and row['suite'] == '/' and not row['key_urls']:
            policies = [facts['constants']['CUDA_LEGACY_POLICY'] for facts in scans.values()
                        if 'CUDA_LEGACY_POLICY' in facts['constants']]
            if len(policies) != 1:
                raise ValueError('legacy CUDA archive lacks its explicit source authentication policy')
            row['authentication'] = policies[0]
            row['architectures'] = ['amd64']
        row['index_urls'] = []
        for arch in row['architectures']:
            if row['suite'].endswith('/'):
                row['index_urls'].append({'architecture': arch, 'type': 'deb', 'url': row['url'] + '/' + row['suite'].lstrip('./') + 'Packages'})
            else:
                for component in row['components']:
                    row['index_urls'].append({'architecture': arch, 'type': 'deb', 'component': component,
                        'url': f'{row["url"]}/dists/{row["suite"]}/{component}/binary-{arch}/Packages'})
                    if row.get('role') == 'base_mirror':
                        row['index_urls'].append({'architecture': arch, 'type': 'udeb', 'component': component,
                            'url': f'{row["url"]}/dists/{row["udeb_suite"]}/{component}/debian-installer/binary-{arch}/Packages'})
        row['release_url'] = (row['url'] + '/' + row['suite'].lstrip('./') + 'Release' if row['suite'].endswith('/')
                              else f'{row["url"]}/dists/{row["suite"]}/Release')
    return sorted(result.values(), key=lambda row: (row['url'], row['suite']))


def artifacts(scans: dict, variables: Variables) -> tuple[list, list, list]:
    downloads, clones, references = [], [], defaultdict(list)
    for path, facts in scans.items():
        if context(path).get('phase') == 'inactive_backup':
            continue
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
                for suffix in ('VERSION', 'SHA256', 'SHA512', 'BRANCH', 'COMMIT', 'REVISION', 'TAG', 'RELEASE_TAG', 'ARCHITECTURE', 'SOURCE_BUILD'):
                    candidate = definitions.get(stem + '_REPOSITORY_' + suffix) or definitions.get(stem + '_' + suffix)
                    base_stem = re.sub(r'_(?:SOURCE|DOWNLOAD|RELEASE)$', '', stem)
                    candidate = candidate or definitions.get(base_stem + '_' + suffix)
                    if suffix == 'SHA256' and 'huggingface.co' in url:
                        candidate = definitions.get(base_stem + '_MODEL_SHA256') or candidate
                    if candidate:
                        metadata[suffix.lower()] = candidate['value']
                record = {'name': stem, 'url': clean_url(url), **metadata,
                          'resolution': 'template' if re.search(r'[$`{}*\\]|__\w+__', url) else 'declared',
                          'sources': [dict(ref(path, item['line']), variable=key)], 'selection': [context(path)]}
                if 'REPOSITORY' in key.upper() or url.startswith(('git@', 'ssh://', 'git://')) or url.endswith('.git'):
                    record['authentication'] = 'ssh_identity_required' if url.startswith(('git@', 'ssh://')) else 'public'
                    clones.append(record)
                else:
                    if not path.endswith('.env') and not ('/scripts/' in path or '/usr/local/lib' in path or '/usr/local/bin/' in path):
                        continue
                    record['kind'] = ('metadata' if re.search(r'(?i)(registry|api|metadata|base)', key)
                                      else 'model' if '/resolve/' in url and 'huggingface.co' in url
                                      else 'archive' if re.search(r'\.(deb|udeb|whl|gz|xz|zip|bin|AppImage|tgz)(?:$|\?)', url)
                                      else 'download_endpoint')
                    if re.search(r'CONNECTIVITY|PLANS_|OBS_API|APTLY_(?:PUBLIC_BASE|R2_ENDPOINT)', key) or key == 'fruux_root_url':
                        record['kind'] = 'service_endpoint'
                    downloads.append(record)
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
                    downloads.append({'name': Path(path).stem, 'url': url,
                                      'kind': 'metadata' if re.search(r'/api/|/manifests/|\.ya?ml$|releases/latest$', url) else 'source_literal',
                                      'resolution': 'template' if re.search(r'[$`{}*\\]|__\w+__', url) else 'declared',
                                      'sources': [ref(path, item['line'])], 'selection': [context(path)]})
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


def indirect_downloads(scans: dict, variables: Variables) -> list[dict]:
    """Represent discovery protocols and transitive downloads as typed recipes."""
    result = []
    for path, facts in scans.items():
        for plugin in facts.get('plugins', []):
            name, version = plugin['name'], plugin['version']
            helper = next((key for key in scans if key.endswith('/scripts/late/packer-plugins.py')), None)
            constants = {item['name']: item['value'] for item in scans[helper]['variables']} if helper else {}
            base = (f'https://github.com/hashicorp/packer-plugin-{name}/releases/download/v{version}/' if name == 'proxmox'
                    else constants.get('ORIGIN', 'https://releases.hashicorp.com') + f'/packer-plugin-{name}/{version}/')
            item = {'kind': 'packer_plugin', 'name': name, 'version': version, 'repository': plugin['repository'],
                    'base_url': base, 'architectures': ['amd64', 'arm64'], 'sources': [ref(path, plugin['line'])],
                    'selection': {'class': 'addon/devops'}, 'resolution': 'signed_checksum_filename_selection'}
            if name == 'proxmox':
                item['archives'] = [{'architecture': arch,
                    'url': base + f'packer-plugin-{name}_v{version}_x5.0_linux_{arch}.zip'} for arch in ['amd64', 'arm64']]
                item['resolution'] = 'source_pinned_release'
            else:
                sums = base + f'packer-plugin-{name}_{version}_SHA256SUMS'
                item.update(checksums_url=sums, signature_url=sums + '.sig', key_url=constants.get('KEY_URL'),
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
            result.append({'kind': 'crowdsec_hub', 'phase': 'first_boot', 'selection': {'class': 'addon/crowdsec'},
                'collections': sorted({item['name'] for item in facts['collections']}),
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
                result.append({'kind': 'codex_standalone_distribution', 'name': 'codex-standalone',
                    'installer_urls': installer_urls,
                    'resolution': 'official_installer_owned_package_manifest_and_architecture_downloads',
                    'requires_all_classes': ['addon/devops', 'role/desktop'],
                    'selection': {'class': 'addon/devops', 'phase': 'installation'},
                    'sources': [{'path': path}, {'path': PREFIX + 'hooks/target/usr/local/bin/codex-standalone-install'}]})
        if path.endswith('/scripts/late/devops-tools.py'):
            result.append({'kind': 'npm_dependencies', 'name': 'wrangler',
                'versions': sorted(variables.global_values.get('DEVOPS_WRANGLER_VERSION', set())),
                'registry_urls': sorted(variables.global_values.get('DEVOPS_WRANGLER_NPM_REGISTRY_URL', set())),
                'resolution': 'package_json_dependencies_and_optional_dependencies_using_npm_semver',
                'omit': ['dev'], 'package_lock': False, 'lifecycle_scripts_enabled': True,
                'selection': {'class': 'addon/devops'}, 'sources': [{'path': path}]})
        if path.endswith('/scripts/desktop/waypaper.sh'):
            result.append({'kind': 'python_dependencies', 'name': 'waypaper',
                'versions': sorted(variables.global_values.get('LABWC_WAYPAPER_VERSION', set())),
                'resolution': 'wheel_METADATA_Requires-Dist_with_target_python_markers_and_system_site_packages',
                'binary_only': True, 'python': '/usr/bin/python3', 'system_site_packages': True,
                'selection': {'class': 'role/desktop'}, 'sources': [{'path': path}]})
        if path.endswith('/APTRepoLocal/Servicing/Discord.pm'):
            manifest = next((item['url'] for item in facts['urls'] if '/manifests/latest?' in item['url']), None)
            result.append({'kind': 'discord_distribution', 'manifest_url': manifest,
                'resolution': 'manifest_host_and_all_modules_full_distro_urls_and_sha256',
                'module_selection': 'all_modules_in_manifest', 'sources': [{'path': path}],
                'selection': {'class': 'addon/software'}, 'phase': 'installation_and_updates'})
    return result


def assemble(scans: dict, metadata: dict) -> dict:
    variables = Variables(scans)
    repos = repositories(scans)
    downloads, clones, urls = artifacts(scans, variables)
    packages = defaultdict(list)
    pins, classes, operations, modules, transfers = [], [], [], [], []
    for path, facts in scans.items():
        if context(path).get('phase') == 'inactive_backup':
            continue
        for item in facts['packages']:
            packages[(item['selector'], item['type'])].append(dict(ref(path, item['line']), via=item['via'], **context(path)))
        for item in facts['pins']:
            pins.append(dict(item, source=ref(path, item['line'])))
        for item in facts['classes']:
            classes.append(dict(item, source=ref(path, item['line'])))
        for item in facts['operations']:
            operations.append(dict(item, source=ref(path, item['line']), **context(path)))
        for item in facts.get('transfers', []):
            transfers.append(dict(item, source=ref(path, item['line']), **context(path)))
        for item in facts['modules']:
            modules.append(dict(item, source=ref(path, item['line'])))
    candidates = defaultdict(list)
    allowed_repos = {r['id']: r for r in repos}
    declarations = [{key: repo[key] for key in ('id', 'url', 'suite', 'components', 'architectures', 'index_urls', 'release_url')}
                    for repo in repos]
    metadata_scope_matches = metadata.get('repository_definitions_sha256') == digest(json.dumps(declarations, sort_keys=True).encode())
    metadata_requests = {(row['name'], row['type']) for row in metadata_value(metadata, 'requested_packages', [])}
    global_preferences, class_map = policy_context(scans, pins, classes)
    releases = metadata_value(metadata, 'releases', {})
    for repo in repos:
        release = releases.get(repo['id'], {})
        representative = {'package': '*', 'version': '', 'source': '*'}
        repo['pin_priority'] = pin_priority(representative, repo, release, pins, global_preferences)
        repo['pin_rules'] = [rule['id'] for rule in pins if rule['packages'] == ['*'] and
                             pin_matches(rule, representative, repo, release)]
        repo['class_priority_overrides'] = {}
        for selected in sorted(class_map):
            priority = pin_priority(representative, repo, release, pins,
                                    preference_scope(selected, global_preferences, class_map))
            if priority != repo['pin_priority']:
                repo['class_priority_overrides'][selected] = priority
    provider_names = defaultdict(set)
    for candidate_index, item in enumerate(metadata_value(metadata, 'packages', []) if metadata_scope_matches else []):
        if item.get('repository') in allowed_repos:
            repo = allowed_repos[item['repository']]
            if not any(item['index_url'] == index['url'] + suffix for index in repo['index_urls'] for suffix in ['', '.xz', '.gz', '.bz2']):
                continue
            filename = item['filename'].removeprefix('./')
            member = PurePosixPath(filename)
            if (member.is_absolute() or '..' in member.parts or ':' in filename or '%' in filename
                    or not re.fullmatch(r'[A-Za-z0-9_./+~-]+', filename)
                    or item['url'] != repo['url'].rstrip('/') + '/' + filename
                    or not PACKAGE.fullmatch(item['package']) or item['type'] not in {'deb', 'udeb'}
                    or item['architecture'] not in {'amd64', 'arm64', 'all'}
                    or not isinstance(item['size'], int) or not 0 < item['size'] <= 64 * 1024**3
                    or item.get('sha256') is not None and not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])):
                raise ValueError('invalid APT snapshot package identity, URL or digest')
            item = dict(item, candidate_index=candidate_index,
                        repository_url=repo['url'], repository_suite=repo['suite'],
                        pin_priority=pin_priority(item, repo, releases.get(repo['id'], {}), pins, global_preferences))
            candidates[(item['package'], item['type'])].append(item)
            for provided in re.findall(r'(?:^|,)\s*([a-z0-9][a-z0-9+.-]*)', item.get('provides', '')):
                provider_names[(provided, item['type'])].add(item['package'])
    rows = []
    for (selector, kind), sources in sorted(packages.items()):
        name = re.split(r'[=/]', selector)[0]
        base_name = name.split(':')[0]
        matches = list(candidates.get((base_name, kind), []))
        for provider in sorted(provider_names.get((base_name, kind), set())):
            matches.extend(candidates[(provider, kind)])
        selected = []
        scopes = sorted({source.get('class', '') for source in sources})
        for scope, architecture in itertools.product(scopes, ['amd64', 'arm64']):
            preferences = preference_scope(scope, global_preferences, class_map)
            target_suite = selector.split('/', 1)[1] if '/' in selector else None
            exact_version = selector.split('=', 1)[1] if '=' in selector else None
            eligible = []
            for candidate in matches:
                if candidate['architecture'] not in {architecture, 'all'} or (exact_version and candidate['version'] != exact_version):
                    continue
                repo = allowed_repos[candidate['repository']]
                if target_suite and target_suite not in {repo['suite'], releases.get(repo['id'], {}).get('Suite'), releases.get(repo['id'], {}).get('Codename')}:
                    continue
                priority = pin_priority(candidate, repo, releases.get(repo['id'], {}), pins, preferences, target_suite)
                if kind == 'udeb':
                    priority = 500  # Anna selects providers from the installer suite, not target APT pins.
                if priority > 0:
                    eligible.append((priority, candidate))
            if eligible:
                def compare(a, b):
                    return (a[0] > b[0]) - (a[0] < b[0]) or version_compare(a[1]['version'], b[1]['version'])
                best = sorted(eligible, key=cmp_to_key(compare), reverse=True)[0]
                winners = unique([{'candidate_index': item['candidate_index'],
                                   'package': item['package'], 'version': item['version'], 'repository': item['repository'],
                                   'url': item['url'], 'pin_priority': priority} for priority, item in eligible
                                  if priority == best[0] and version_compare(item['version'], best[1]['version']) == 0])
                selected.append({'class': scope or None, 'architecture': architecture,
                                 'status': 'preferred_index_candidates', 'candidates': winners})
        rows.append({'name': base_name, 'selector': selector, 'type': kind,
                     'category': ('kernel' if base_name.startswith(('linux-image', 'linux-headers', 'linux-xanmod')) else
                                  'module' if 'modules' in base_name or base_name.endswith('-dkms') else 'package'),
                     'sources': unique(sources), 'candidate_indices': sorted({item['candidate_index'] for item in matches}),
                     'source_selection': selected,
                     'dependency_solver_verified': False,
                     'resolution': ('virtual_package_providers' if provider_names.get((base_name, kind)) and not candidates.get((base_name, kind)) else
                                    'indexed_candidates' if matches else 'not_present_in_acquired_indexes'
                                    if metadata_scope_matches and (base_name, kind) in metadata_requests else 'requires_repository_metadata_refresh')})
    recipes = indirect_downloads(scans, variables)
    bootstrap = []
    seen_bootstrap = set()
    for item in transfers:
        key = json.dumps(item, sort_keys=True)
        if key in seen_bootstrap:
            continue
        seen_bootstrap.add(key)
        row = dict(item)
        row['resolution'] = 'literal_repository_relative_path' if item.get('path') else 'dynamic_repository_relative_path'
        bootstrap.append(row)
    # These two files are fetched before any manifest member can be used. The
    # generated preseed pins their bytes, but the inventory intentionally does
    # not trust or reparse generated-product hashes.
    for path, destination, line in [
            ('payload.manifest', 'bootstrap/payload.manifest', None),
            ('payload.tar.gz', 'bootstrap/payload.tar.gz', None)]:
        existing = next((row for row in bootstrap
                         if row.get('kind') == 'source_transfer' and row.get('path') == path), None)
        if existing is not None:
            existing['destination'] = destination
            existing['resolution'] = 'generated_bootstrap_artifact'
            existing['selection'] = {'phase': 'installer_bootstrap'}
            continue
        row = {'kind': 'source_transfer', 'path': path, 'destination': destination,
               'resolution': 'generated_bootstrap_artifact',
               'selection': {'phase': 'installer_bootstrap'},
               'source': {'path': PREFIX + 'scripts/common/source.sh', 'line': 552 if path.endswith('manifest') else 554}}
        bootstrap.append(row)
    bootstrap = sorted(bootstrap, key=lambda row: json.dumps(row, sort_keys=True))
    limitations = [
        'APT candidates are indexed metadata and dependency/provider unions, not an APT solver transaction.',
        'Rolling, latest, unlocked and runtime-discovered endpoints require typed acquisition during the offline media build.',
        'APT Release OpenPGP signatures are not verified by the metadata collector.',
    ]
    requested_names = {(row['name'], row['type']) for row in rows}
    dependency_candidates = sorted({item['candidate_index'] for key, values in candidates.items()
                                   if key not in requested_names for item in values})
    candidate_record_count = sum(len(values) for values in candidates.values())
    metadata_summary = {'path': APT_SNAPSHOT, 'schema_version': metadata.get('schema_version'),
                        'candidate_record_count': len(metadata_value(metadata, 'packages', [])),
                        'signature_verification': 'not_performed'}
    return {'schema': {'name': 'debian-preseed-download-inventory', 'version': SCHEMA,
                       'ordering': 'all arrays and object keys are deterministic'},
            'scope': {'manifest': PREFIX + 'payload.manifest', 'scan_input': PAYLOAD,
                      'architectures': ['amd64', 'arm64'], 'selection': 'union_of_all_payload_classes_and_profiles',
                      'network_during_scan': False, 'installer_code_executed': False},
            'apt': {'repositories': repos, 'pin_rules': pins, 'packages': rows,
                    'installation_settings': [dict(item, source=ref(path, item['line']), **context(path))
                                              for path, facts in scans.items() for item in facts['settings']],
                    'metadata': {**metadata_summary,
                                 'matches_repository_configuration': metadata_scope_matches},
                    'dependency_candidate_indices': dependency_candidates,
                    'selection_contract': 'Candidates are repository snapshots; selected classes, pin rules, architecture, version constraints and dependency solving determine the installation transaction.'},
            'external_artifacts': downloads, 'git_repositories': clones, 'classes': classes,
            'indirect_downloads': recipes,
            'kernel_module_operations': modules, 'repository_transfers': bootstrap,
            'download_operations': operations, 'url_references': urls,
            'coverage': {'source_files': len(scans), 'apt_repositories': len(repos),
                         'apt_requests': len(rows), 'apt_candidate_records': candidate_record_count,
                         'external_artifacts': len(downloads), 'git_repositories': len(clones),
                         'indirect_recipes': len(recipes),
                         'repository_transfers': len(bootstrap), 'download_operations': len(operations),
                         'url_references': len(urls), 'limitations': limitations}}


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


def current_pair(inventory: dict, metadata: dict, apt_raw: bytes | None, payload: dict) -> bool:
    for value, name in ((inventory, 'debian-preseed-download-inventory'), (metadata, 'debian-apt-metadata')):
        schema = value.get('schema')
        if (value.get('schema_version') != SCHEMA or not isinstance(schema, dict) or schema.get('name') != name
                or schema.get('version') != SCHEMA or value.get('payload') != payload):
            return False
    if (apt_raw is None or inventory.get('apt_metadata_sha256') != digest(apt_raw)
            or inventory.get('generator') != {'path': 'tools/inventory.py', 'version': GENERATOR_VERSION}
            or metadata.get('errors') != []):
        return False
    apt, candidates = inventory.get('apt'), metadata.get('candidates')
    if (not isinstance(apt, dict) or not isinstance(apt.get('packages'), list)
            or not isinstance(candidates, dict) or not isinstance(candidates.get('records'), list)
            or type(candidates.get('record_count')) is not int
            or candidates['record_count'] != len(candidates['records'])):
        return False
    references = [row.get('candidate_indices') if isinstance(row, dict) else None for row in apt['packages']]
    references.append(apt.get('dependency_candidate_indices'))
    return all(isinstance(indices, list)
               and all(type(index) is int and 0 <= index < candidates['record_count'] for index in indices)
               and indices == sorted(set(indices)) for indices in references)


def generate(root: Path = ROOT, *, refresh_apt: bool = False, force: bool = False) -> tuple[bytes, bytes | None, dict]:
    root = root.resolve(strict=True)
    before = file_identity((root / PAYLOAD).lstat())
    raw = read_file(root / PAYLOAD, MAX_PAYLOAD)
    if before != file_identity((root / PAYLOAD).lstat()):
        raise ValueError('payload changed while reading; existing inventories retained')
    payload = {'path': PAYLOAD, 'sha256': digest(raw), 'size': len(raw)}
    old_raw, old = existing_document(root / 'inventory.json')
    apt_raw, metadata = existing_document(apt_snapshot_path(root))
    if not force and current_pair(old, metadata, apt_raw, payload):
        return old_raw, None, {'current': True, 'written': False, 'text_files_scanned': 0}
    scans, stats = scan_payload(raw)
    if refresh_apt:
        from inventory_apt import refresh
        requests = sorted({(re.split(r'[=/:]', item['selector'])[0], item['type'])
                           for facts in scans.values() for item in facts['packages']})
        apt = {'repositories': repositories(scans),
               'packages': [{'name': name, 'type': kind} for name, kind in requests]}
        metadata = refresh(root, apt, payload)
        apt_raw = encode(metadata)
    result = {'schema_version': SCHEMA, 'payload': payload,
              'generator': {'path': 'tools/inventory.py', 'version': GENERATOR_VERSION},
              'apt_metadata_sha256': digest(apt_raw) if apt_raw is not None else None,
              **assemble(scans, metadata)}
    result['coverage'].update(stats)
    missing = [row['selector'] for row in result['apt']['packages'] if not row['candidate_indices']]
    result['coverage']['missing_package_requests'] = missing
    # Discovery preserves the installer's exact requests, including names not
    # present in the acquired indexes. Record the gap; never rewrite a source
    # declaration or omit the request to make coverage appear complete.
    result['coverage']['requested_package_coverage_complete'] = not missing
    data = encode(result)
    if len(data) > MAX_JSON or apt_raw is not None and len(apt_raw) > MAX_JSON:
        raise ValueError('generated inventory exceeds byte limit')
    if before != file_identity((root / PAYLOAD).lstat()):
        raise ValueError('payload changed during generation; existing inventories retained')
    return data, apt_raw if refresh_apt else None, dict(stats, current=False)


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


def publish_products(root: Path, products: dict[str, bytes]) -> bool:
    """Prepare the pair before writing; restore handled publication failures.

    The APT digest in inventory.json detects an interrupted two-file publish.
    Private previous bytes survive if restoration cannot be proven.
    """
    if (not products or not set(products) <= {'inventory.json', APT_SNAPSHOT}
            or any(type(data) is not bytes or len(data) > MAX_JSON for data in products.values())):
        raise ValueError('publication requires bounded inventory products')
    previous, changed = {}, []
    for name, data in products.items():
        path = root / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            previous[name] = None
        else:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
                raise ValueError('unsafe inventory output: ' + name)
            previous[name] = (read_file(path, MAX_JSON), stat.S_IMODE(info.st_mode))
        if previous[name] != (data, 0o644):
            changed.append(name)
    if not changed:
        return False
    recovery = Path(tempfile.mkdtemp(prefix='.inventory-recovery-', dir=root))
    attempted = []
    restored = True
    try:
        for name in changed:
            old = previous[name]
            if old is not None:
                atomic_write(recovery / name, old[0], 0o600)
        atomic_write(recovery / 'state.json', encode({name: None if previous[name] is None else previous[name][1]
                                                     for name in changed}), 0o600)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        for name in changed:
            attempted.append(name)
            atomic_write(root / name, products[name], 0o644)
    except BaseException as error:
        for name in reversed(attempted):
            old = previous[name]
            try:
                if old is None:
                    (root / name).unlink(missing_ok=True)
                    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                else:
                    atomic_write(root / name, *old)
            except BaseException:
                restored = False
        if not restored:
            raise ValueError('inventory publication outcome unknown; recovery retained at ' + str(recovery)) from error
        raise
    finally:
        if restored:
            for path in recovery.iterdir():
                path.unlink()
            recovery.rmdir()
    return True


def publish(root: Path = ROOT, *, refresh_apt: bool = False, force: bool = False) -> dict:
    root = root.resolve(strict=True)
    with generation_lock(root):
        data, apt_data, stats = generate(root, refresh_apt=refresh_apt, force=force)
        if not stats['current']:
            products = {APT_SNAPSHOT: apt_data} if apt_data is not None else {}
            products['inventory.json'] = data
            stats['written'] = publish_products(root, products)
        return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-apt', action='store_true', help='explicitly fetch public APT metadata into root inventory-apt.json, then generate inventory')
    parser.add_argument('--force', action='store_true', help='regenerate even when the payload matches; with --refresh-apt, refresh rolling APT metadata')
    args = parser.parse_args()
    try:
        stats = publish(refresh_apt=args.refresh_apt, force=args.force)
        if stats['current']:
            print('The generated inventory files are already up to date')
        else:
            print(f'inventory: generated from {stats["payload_members"]} payload members; '
                  f'{stats["text_files_scanned"]} text files scanned, {stats["source_files"]} relevant files')
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError, tarfile.TarError, EOFError) as error:
        print('inventory failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
