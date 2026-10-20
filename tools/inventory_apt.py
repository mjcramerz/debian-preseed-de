"""Explicit acquisition of public APT index data for the offline inventory.

No host APT state, package tools, shell, credentials or downloaded code is used.
HTTPS plus Release SHA-256 checks establish transport/byte consistency only;
this collector does not claim OpenPGP verification. Consumers must authenticate
Release metadata against the configured archive keys before trusting packages.
"""
from __future__ import annotations

import bz2
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_COMPRESSED = 64 * 1024**2
MAX_EXPANDED = 512 * 1024**2
MAX_LINE = 256 * 1024
MAX_STANZA = 1024 * 1024
MAX_PACKAGES = 500000
MAX_INDEXES = 300
MAX_ROWS = 2000000
TIMEOUT = 120
SNAPSHOT_NAME = 'inventory-apt.json'


class Budget:
    def __init__(self):
        self.lock = threading.Lock()
        self.expanded = 0
        self.records = 0

    def consume(self, expanded=0, records=0):
        with self.lock:
            self.expanded += expanded
            self.records += records
            if self.expanded > 8 * 1024**3 or self.records > MAX_ROWS:
                raise ValueError('aggregate APT metadata work limit exceeded')


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.port not in {None, 443}
            or parsed.hostname in {'localhost', 'localhost.localdomain'}
            or re.fullmatch(r'[0-9.:]+', parsed.hostname)):
        raise ValueError('APT metadata URL must be public HTTPS without credentials')
    return url


class Redirects(HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, request, fp, code, message, headers, newurl):
        public_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch(url: str, limit: int) -> bytes:
    public_url(url)
    deadline = time.monotonic() + TIMEOUT
    opener = build_opener(ProxyHandler({}), Redirects())
    request = Request(url, headers={'User-Agent': 'preseed-inventory/1', 'Accept-Encoding': 'identity'})
    output = bytearray()
    with opener.open(request, timeout=15) as response:
        public_url(response.url)
        while True:
            if time.monotonic() >= deadline:
                raise ValueError('APT metadata transfer deadline exceeded')
            block = response.read(min(65536, limit + 1 - len(output)))
            if not block:
                return bytes(output)
            output.extend(block)
            if len(output) > limit:
                raise ValueError('APT metadata transfer exceeds byte limit')


def stanzas(stream, budget=None):
    fields, previous, total, stanza_size = {}, None, 0, 0
    while True:
        line = stream.readline(MAX_LINE + 1)
        if not line:
            if fields:
                yield fields
            return
        total += len(line)
        if budget:
            budget.consume(expanded=len(line))
        stanza_size += len(line)
        if len(line) > MAX_LINE or total > MAX_EXPANDED or stanza_size > MAX_STANZA:
            raise ValueError('APT metadata expansion or stanza limit exceeded')
        line = line.decode('utf-8').rstrip('\r\n')
        if not line:
            if fields:
                yield fields
            fields, previous, stanza_size = {}, None, 0
        elif line.startswith((' ', '\t')) and previous:
            fields[previous] += '\n' + line[1:]
        elif ':' in line:
            key, value = line.split(':', 1)
            previous = key
            fields[key] = value.strip()


def filename_url(base: str, filename: str) -> str:
    path = PurePosixPath(filename.removeprefix('./'))
    if (path.is_absolute() or '..' in path.parts or not path.parts
            or not re.fullmatch(r'[A-Za-z0-9_.+~:/%-]+', str(path)) or ':' in str(path)
            or '%' in str(path)):
        raise ValueError('unsafe package filename in index')
    return base.rstrip('/') + '/' + str(path)


def release_metadata(repo: dict) -> tuple[dict, dict]:
    raw = fetch(repo['release_url'], 8 * 1024**2)
    records = list(stanzas(io.BytesIO(raw)))
    if len(records) != 1:
        raise ValueError('invalid Release metadata')
    release = records[0]
    checksums = {}
    for line in release.get('SHA256', '').splitlines():
        fields = line.split()
        if len(fields) == 3 and re.fullmatch('[0-9a-f]{64}', fields[0]):
            checksums[fields[2]] = (fields[0], int(fields[1]))
    if not checksums:
        raise ValueError('Release metadata has no SHA-256 index entries')
    details = {key: release[key] for key in ('Origin', 'Label', 'Suite', 'Codename', 'Version', 'Date',
                                            'Valid-Until', 'Architectures', 'Components', 'NotAutomatic',
                                            'ButAutomaticUpgrades') if key in release}
    details['url'] = repo['release_url']
    details['sha256'] = hashlib.sha256(raw).hexdigest()
    details['signature_verification'] = 'not_performed'
    return details, checksums


def acquire_index(repo: dict, index: dict, release: dict, sums: dict, target: Path, budget: Budget) -> dict:
    prefix = repo['release_url'].rsplit('/', 1)[0] + '/'
    base = index['url']
    if not base.startswith(prefix):
        raise ValueError('index is outside repository release directory')
    relative = base[len(prefix):]
    # Acquire only a format actually listed in Release. Never guess package paths.
    selected = next((relative + suffix for suffix in ('.xz', '.gz', '.bz2', '') if relative + suffix in sums), None)
    record = {'repository': repo['id'], **index}
    if selected is None:
        return dict(record, status='not_advertised')
    expected, size = sums[selected]
    if not 0 <= size <= MAX_COMPRESSED:
        raise ValueError('advertised package index exceeds byte limit')
    url = prefix + selected
    raw = fetch(url, MAX_COMPRESSED)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('package index does not match Release SHA-256/size')
    buffer = io.BytesIO(raw)
    stream = (lzma.LZMAFile(buffer) if selected.endswith('.xz') else
              gzip.GzipFile(fileobj=buffer) if selected.endswith('.gz') else
              bz2.BZ2File(buffer) if selected.endswith('.bz2') else buffer)
    count = 0
    with stream, target.open('x', encoding='utf-8') as output:
        for item in stanzas(stream, budget):
            name, version, architecture = item.get('Package'), item.get('Version'), item.get('Architecture')
            filename = item.get('Filename')
            if not name or not version or not architecture or not filename:
                raise ValueError('package index record is missing its identity or filename')
            if (not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', name)
                    or not re.fullmatch(r'[A-Za-z0-9.+:~_-]+', version)
                    or not re.fullmatch(r'[a-f0-9]{64}', item.get('SHA256', ''))
                    or not 0 < int(item.get('Size', '0')) <= 64 * 1024**3):
                raise ValueError('package index record has an invalid identity, size or SHA-256')
            count += 1
            budget.consume(records=1)
            if count > MAX_PACKAGES:
                raise ValueError('package index record limit exceeded')
            if architecture not in {index['architecture'], 'all'}:
                continue
            row = {'package': name, 'version': version, 'architecture': architecture, 'type': index['type'],
                   'repository': repo['id'], 'url': filename_url(repo['url'], filename), 'filename': filename,
                   'size': int(item['Size']), 'sha256': item.get('SHA256'), 'source': item.get('Source', name),
                   'depends': item.get('Depends', ''), 'pre_depends': item.get('Pre-Depends', ''),
                   'provides': item.get('Provides', ''), 'priority': item.get('Priority'),
                   'essential': item.get('Essential') == 'yes', 'index_url': url}
            output.write(json.dumps(row, separators=(',', ':')) + '\n')
    return dict(record, status='acquired', url=url, sha256=expected, compressed_bytes=size, records=count,
                release_sha256=release['sha256'])


def relationship_names(text: str) -> list[str]:
    return re.findall(r'(?:^|[,|])\s*([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9-]+)?', text)


def select_packages(database: sqlite3.Connection, requested: set) -> list:
    """Union of all dependency alternatives/providers; never pretend to solve APT."""
    todo = set(requested)
    for name, kind in database.execute('SELECT DISTINCT name, kind FROM packages WHERE essential=1 OR priority IN (\'required\',\'important\')'):
        todo.add((name, kind))
    visited, selected, retained_bytes = set(), {}, 0
    while todo:
        name, kind = todo.pop()
        if (name, kind) in visited:
            continue
        visited.add((name, kind))
        for identifier, encoded in database.execute(
                'SELECT id, data FROM packages WHERE id IN ('
                'SELECT id FROM packages WHERE name=? AND kind=? UNION '
                'SELECT p.id FROM provides v JOIN packages p ON p.id=v.package_id WHERE v.name=? AND p.kind=?'
                ') ORDER BY id', (name, kind, name, kind)):
            if identifier in selected:
                continue
            retained_bytes += len(encoded)
            if retained_bytes > 96 * 1024**2:
                raise ValueError('APT retained candidate byte limit exceeded')
            row = json.loads(encoded)
            selected[identifier] = row
            if len(selected) > 100000:
                raise ValueError('APT dependency candidate limit exceeded')
            todo.update((dep, kind) for dep in relationship_names(row['depends'] + ',' + row['pre_depends']))
    return sorted(selected.values(), key=lambda r: (r['package'], r['type'], r['architecture'], r['repository'], r['version'], r['url'], r['index_url']))


def refresh(root: Path, apt: dict, payload: dict) -> dict:
    """Acquire a complete candidate in private scratch; the caller publishes both JSONs."""
    repositories = apt['repositories']
    indexes, releases, errors = [], {}, []
    requested = {(row['name'], row['type']) for row in apt['packages']}
    jobs = []
    if len(repositories) > 256 or sum(len(repo['index_urls']) for repo in repositories) > MAX_INDEXES:
        raise ValueError('APT repository or index job limit exceeded')
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(release_metadata, repo): repo for repo in repositories}
        for future in as_completed(futures):
            repo = futures[future]
            try:
                details, sums = future.result()
                releases[repo['id']] = details
                for index in repo['index_urls']:
                    if details.get('Architectures') and index['architecture'] not in details['Architectures'].split():
                        continue
                    jobs.append((repo, index, details, sums))
            except (OSError, ValueError, URLError) as error:
                errors.append({'repository': repo['id'], 'stage': 'Release', 'error': type(error).__name__,
                               'http_status': error.code if isinstance(error, HTTPError) else None})
            print('inventory APT: Release ' + repo['id'] + (' acquired' if repo['id'] in releases else ' unavailable'), flush=True)
    if errors:
        failed = ','.join(sorted({error['repository'] for error in errors}))
        raise ValueError('APT Release acquisition incomplete; existing metadata retained; repositories=' + failed)
    if len(jobs) > MAX_INDEXES:
        raise ValueError('APT index job limit exceeded')
    jobs.sort(key=lambda job: (job[0]['id'], job[1]['url'], job[1]['architecture'], job[1]['type']))
    budget = Budget()
    with tempfile.TemporaryDirectory(prefix='.inventory-apt-', dir=root) as temporary:
        private = Path(temporary)
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(acquire_index, repo, index, details, sums, private / f'{n}.jsonl', budget): (n, repo, index)
                       for n, (repo, index, details, sums) in enumerate(jobs)}
            for future in as_completed(futures):
                n, repo, index = futures[future]
                try:
                    record = future.result()
                    indexes.append(record)
                except (OSError, ValueError, URLError, EOFError, lzma.LZMAError) as error:
                    errors.append({'repository': repo['id'], 'stage': 'Packages', 'architecture': index['architecture'],
                                   'type': index['type'], 'url': index['url'], 'error': type(error).__name__,
                                   'http_status': error.code if isinstance(error, HTTPError) else None})
                    (private / f'{n}.jsonl').unlink(missing_ok=True)
                print(f'inventory APT: {len(indexes) + len([e for e in errors if e["stage"] == "Packages"])}/{len(jobs)} indexes', flush=True)
        if errors:
            failed = ','.join(sorted({error['repository'] for error in errors}))
            raise ValueError('APT index acquisition incomplete; existing metadata retained; repositories=' + failed)
        with sqlite3.connect(private / 'indexes.sqlite') as database:
            database.execute('PRAGMA temp_store=MEMORY')
            database.execute('CREATE TABLE packages (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, priority TEXT, essential INTEGER, data TEXT)')
            database.execute('CREATE TABLE provides (name TEXT, package_id INTEGER)')
            count = 0
            for path in sorted(private.glob('*.jsonl')):
                with path.open(encoding='utf-8') as stream:
                    for line in stream:
                        row = json.loads(line)
                        count += 1
                        if count > MAX_ROWS:
                            raise ValueError('aggregate APT record limit exceeded')
                        cursor = database.execute('INSERT INTO packages (name,kind,priority,essential,data) VALUES (?,?,?,?,?)',
                                                  (row['package'], row['type'], row['priority'], row['essential'], line))
                        for name in relationship_names(row['provides']):
                            database.execute('INSERT INTO provides VALUES (?,?)', (name, cursor.lastrowid))
                path.unlink()
            database.execute('CREATE INDEX names ON packages (name,kind)')
            database.execute('CREATE INDEX virtuals ON provides (name)')
            selected = select_packages(database, requested)
    # Identical all-architecture records may occur in both architecture indexes.
    selected = list({json.dumps(row, sort_keys=True): row for row in selected}.values())
    declarations = [{key: repo[key] for key in ('id', 'url', 'suite', 'components', 'architectures', 'index_urls', 'release_url')}
                    for repo in repositories]
    value = {'schema': {'name': 'debian-apt-metadata', 'version': 3,
                        'ordering': 'all arrays and object keys are deterministic'},
             'schema_version': 3, 'payload': payload,
             'trust': 'HTTPS and Release SHA-256 consistency; OpenPGP signature verification not performed',
             'repository_definitions_sha256': hashlib.sha256(json.dumps(declarations, sort_keys=True).encode()).hexdigest(),
             'request_set': {'packages': [{'name': name, 'type': kind} for name, kind in sorted(requested)]},
             'release_files': releases,
             'package_indexes': sorted(indexes, key=lambda r: (r['repository'], r['url'], r['architecture'])),
             'errors': sorted(errors, key=lambda r: json.dumps(r, sort_keys=True)),
             'dependency_policy': 'union of Depends/Pre-Depends alternatives and virtual providers, plus required/important/essential base packages',
             'candidates': {'record_count': len(selected), 'records': selected}}
    print(f'inventory APT: retained {len(selected)} package candidates; {len(errors)} unavailable metadata requests', flush=True)
    return value
