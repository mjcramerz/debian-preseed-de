#!/usr/bin/env python3
"""Serialize the manifest's download declarations to inventory.json, without execution.

Normal generation is offline, uses only checkout files, and writes only
inventory.json. --refresh-apt is a separate, explicit metadata acquisition step;
it never runs apt, dpkg, shell snippets, installed helpers or package code.
"""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import fnmatch
from functools import cmp_to_key
import hashlib
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import sys
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publication import atomic_write

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'd-i/forky/'
SCHEMA = 2
APT_SNAPSHOT = 'inventory-apt.json'
MAX_FILE = 16 * 1024**2
MAX_JSON = 128 * 1024**2
MAX_TOTAL = 256 * 1024**2
MAX_MEMBERS = 20000
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
                      r'tag|architecture|target_triple|toolchain|kernel|packages|modules|apt_preferences|source_build|release)')
TRANSFER_COMMANDS = {'source_transfer', 'fetch_hook_file', 'bootstrap_source_module',
                     'installer_fetch_seed_path'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def read_file(path: Path, limit: int = MAX_FILE) -> bytes:
    """Never follow a manifest member or parent link outside the checkout."""
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
    finally:
        os.close(directory)
    if len(data) > limit:
        raise ValueError('input exceeds size limit: ' + path.name)
    return data


def load_json(path: Path):
    return json.loads(read_file(path, MAX_JSON))


def apt_snapshot_path(root: Path) -> Path:
    """Return the one canonical APT snapshot at the repository root."""
    return root / APT_SNAPSHOT


def metadata_value(metadata: dict, name: str, default):
    """Read the structured v2 snapshot and accept the prior flat shape."""
    if name in metadata:
        return metadata[name]
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


def manifest_paths(data: bytes) -> list[str]:
    """Use only the second column. Hashes in the manifest are not trusted inputs."""
    members = set()
    for line in data.decode('utf-8').splitlines():
        if not line.strip():
            continue
        fields = line.split(None, 1)
        if len(fields) != 2:
            raise ValueError('manifest record has no member path')
        name = fields[1].removeprefix('*')
        path = PurePosixPath(name)
        if (not re.fullmatch(r'[A-Za-z0-9_./@+-]+', name) or path.is_absolute()
                or '..' in path.parts or path.as_posix() != name
                or path.name in PRIVATE or name in {'payload.tar.gz', 'payload.manifest', 'preseed.cfg'}):
            raise ValueError('unsafe manifest member')
        if name in members:
            raise ValueError('duplicate manifest member: ' + name)
        members.add(name)
        if len(members) > MAX_MEMBERS:
            raise ValueError('manifest member limit exceeded')
    if not members:
        raise ValueError('empty payload manifest')
    return sorted(members)


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
    result = []
    # Commands are only tokenized, never evaluated or executed.
    try:
        tokens = shlex.split(statement, comments=True)
    except ValueError:
        return result
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
            tokens = shlex.split(line, comments=True)
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
                          'resolution': 'template' if VARIABLE.search(url) or re.search(r'[{}*]|__\w+__', url) else 'declared',
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
                                      'resolution': 'template' if VARIABLE.search(url) or re.search(r'[{}*]|__\w+__', url) else 'declared',
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
    for item in metadata_value(metadata, 'packages', []):
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
            item = dict(item, repository_url=repo['url'], repository_suite=repo['suite'],
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
                winners = unique([{'package': item['package'], 'version': item['version'], 'repository': item['repository'],
                                   'url': item['url'], 'pin_priority': priority} for priority, item in eligible
                                  if priority == best[0] and version_compare(item['version'], best[1]['version']) == 0])
                selected.append({'class': scope or None, 'architecture': architecture,
                                 'status': 'preferred_index_candidates', 'candidates': winners})
        rows.append({'name': base_name, 'selector': selector, 'type': kind,
                     'category': ('kernel' if base_name.startswith(('linux-image', 'linux-headers', 'linux-xanmod')) else
                                  'module' if 'modules' in base_name or base_name.endswith('-dkms') else 'package'),
                     'sources': unique(sources), 'candidates': matches, 'source_selection': selected,
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
        'Rolling, latest, unlocked and runtime-discovered endpoints remain typed recipes until installation.',
        'APT Release OpenPGP signatures are not verified by the metadata collector.',
    ]
    dependency_candidates = [item for key, values in sorted(candidates.items()) if key not in
                             {(r['name'], r['type']) for r in rows} for item in values]
    candidate_record_count = sum(len(values) for values in candidates.values())
    metadata_summary = {key: value for key, value in metadata.items()
                        if key not in {'packages', 'candidates'}}
    return {'schema': {'name': 'debian-preseed-download-inventory', 'version': SCHEMA,
                       'ordering': 'all arrays and object keys are deterministic'},
            'scope': {'manifest': PREFIX + 'payload.manifest', 'manifest_hashes_used': False,
                      'architectures': ['amd64', 'arm64'], 'selection': 'union_of_all_manifest_classes_and_profiles',
                      'network_during_generation': False, 'installer_code_executed': False},
            'apt': {'repositories': repos, 'pin_rules': pins, 'packages': rows,
                    'metadata': {**metadata_summary,
                                 'matches_repository_configuration': metadata_scope_matches},
                    'dependency_candidates': dependency_candidates,
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


def generate(root: Path = ROOT) -> tuple[bytes, dict]:
    root = root.resolve(strict=True)
    manifest = read_file(root / PREFIX / 'payload.manifest')
    paths = manifest_paths(manifest)
    output = root / 'inventory.json'
    old = load_json(output) if output.exists() else {}
    if not isinstance(old, dict):
        raise ValueError('inventory cache must be a JSON object')
    scanner_hash = digest(read_file(Path(__file__).resolve()))
    compatible = old.get('schema_version') == SCHEMA and old.get('generator', {}).get('sha256') == scanner_hash
    old_hashes = old.get('source_hashes', {}) if compatible else {}
    cache = old.get('_scan_cache', {}) if compatible else {}
    discovery = old.get('_discovery_hashes', {}) if compatible else {}
    scans, hashes, negatives = {}, {}, {}
    total, rescanned, reused = 0, 0, 0
    for relative in paths:
        name = PREFIX + relative
        if PurePosixPath(relative).suffix.lower() in BINARY:
            continue
        raw = read_file(root / name)
        total += len(raw)
        if total > MAX_TOTAL:
            raise ValueError('aggregate source byte limit exceeded')
        if b'\0' in raw:
            continue
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        checksum = digest(raw)
        if old_hashes.get(name) == checksum and name in cache:
            hashes[name] = checksum
            scans[name] = cache[name]
            reused += 1
        elif discovery.get(name) == checksum:
            negatives[name] = checksum
            reused += 1
        else:
            facts = scan_file(name, text)
            relevant = (any(facts[key] for key in ('packages', 'settings', 'pins', 'classes', 'sources',
                                                  'operations', 'transfers', 'modules', 'constants', 'plugins', 'collections'))
                        or facts['urls'] or any(INTEREST.search(item['name']) for item in facts['variables']))
            if relevant and '/backup/' not in name and not name.endswith(('.md', '.md.tmpl')):
                hashes[name] = checksum
                scans[name] = facts
            else:
                negatives[name] = checksum
            rescanned += 1
    metadata_path = apt_snapshot_path(root)
    metadata = load_json(metadata_path) if metadata_path.exists() else {}
    metadata_hash = digest(read_file(metadata_path, MAX_JSON)) if metadata_path.exists() else None
    result = {'source_hashes': hashes, 'schema_version': SCHEMA,
              'generator': {'path': 'tools/inventory.py', 'sha256': scanner_hash},
              'apt_metadata_sha256': metadata_hash, **assemble(scans, metadata),
              '_scan_cache': scans}
    # Negative discovery is only an optimization. Preserve its old bytes when
    # unrelated sources change, so cache maintenance cannot replace inventory.
    old_content = {key: value for key, value in old.items() if key != '_discovery_hashes'}
    result['_discovery_hashes'] = discovery if result == old_content else negatives
    return encode(result), {'rescanned': rescanned, 'reused': reused, 'manifest_members': len(paths)}


def publish(root: Path = ROOT) -> dict:
    data, stats = generate(root)
    output = root / 'inventory.json'
    if output.exists() and read_file(output, MAX_JSON) == data:
        stats['written'] = False
    else:
        atomic_write(output, data, 0o644)
        stats['written'] = True
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-apt', action='store_true', help='explicitly fetch public APT metadata into root inventory-apt.json, then generate inventory')
    args = parser.parse_args()
    try:
        if args.refresh_apt:
            from inventory_apt import refresh
            data, _ = generate()
            refresh(ROOT, json.loads(data)['apt'])
        stats = publish()
        print('inventory: ' + ('updated' if stats['written'] else 'unchanged') +
              f'; {stats["rescanned"]} files rescanned, {stats["reused"]} cached, {stats["manifest_members"]} manifest members')
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print('inventory failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
