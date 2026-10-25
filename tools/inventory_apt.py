"""Manual acquisition of public download metadata for the single-file inventory.

No host APT state, package tools, shell or credentials are used. Downloaded
source and archive metadata are read as data; downloaded code never executes.
Python dependency resolution uses the developer's PyPA packaging >= 23.2 library
as a parser, with explicit target values; it does not query host package state.
HTTPS plus Release SHA-256 checks establish transport/byte consistency only;
this collector does not claim OpenPGP verification. Consumers must authenticate
Release metadata against the configured archive keys before trusting packages.
"""
from __future__ import annotations

import base64
import bz2
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextlib import closing, contextmanager
from email.parser import BytesParser
import gzip
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import struct
import tarfile
import tempfile
import threading
import time
import tomllib
import zlib
import zipfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_COMPRESSED = 64 * 1024**2
MAX_EXPANDED = 512 * 1024**2
MAX_LINE = 256 * 1024
MAX_STANZA = 1024 * 1024
MAX_PACKAGES = 500000
MAX_INDEXES = 300
MAX_ROWS = 2000000
TIMEOUT = 120
MAX_SOURCE_FILES = 64
MAX_PROTOCOL_FILES = 4096

# Reviewed upstream v1.7.4 and v1.8.0 protocol sources. A selected engine's tag must
# expose the same contract bytes before this adapter infers its hub behavior.
# These are inspection evidence, never executable imports or source builds.
CROWDSEC_CONTRACT = {
    'cmd/crowdsec-cli/core/require/branch.go': (
        '6fd2b2b1b9033097060131d2b14b8d99f7bc12b5396a0d6a39ceb15821d4a835',
        'fb050fe7ab73b230601ed5743a3a5ac387489f3212c56117fbd2565217c867fd'),
    'pkg/csconfig/cscli.go': ('16fec0158c3c3f241acb64743b3e0f6971b6650f3747f2be77e07c3d3a77c517',),
    'pkg/cwversion/version.go': ('1a6808f868ac7e0f9401b89f3712cca7dbb0b17e3bda087cf5e1fb9d62b5f061',),
    'pkg/cwhub/download.go': (
        'de805aa5c3f4f9fee39dbd885e4fe951f8e9c6c9f8083d433daf9c869d4fbc92',
        '7de661d5bd70b89b3a2efaaeb99eb0933d136a9b235b38389182aa6733754757'),
    'pkg/cwhub/fetch.go': ('20ea21a2e134deea693b2ea380704e804dd7bfc6396ff7db444705ce06496912',),
    'pkg/cwhub/item.go': (
        '7ec1ac8239ebf1704a64e599898f2d1096cbc8a82e97e5be0081f7ed063a4a76',
        '0739c0910e33828a6ac8499a421b9cf148f57239e64a1a70355c0b8d0038ac40'),
    'pkg/hubops/download.go': (
        '0c861dd122458e60166f7caa96d842c10250228cf86d000ce25fc4d69fd395f9',
        'b882ab2249f1edb037fb4d00c3d217a3390f0c48cae85e52371be70938f4f44e'),
}

PIPX_PROTOCOL_SOURCES = {
    # These exact installed sources were inspected in Debian's 1.15.0-1
    # archive. They describe automatic backend selection and local wheel
    # probing; a package version string alone does not establish this policy.
    'shared_libs.py': 'b30e0ca4540e4d4ac894d32e9cb0616bb6a69811378b025580c24e4e54422e7b',
    'venv.py': 'ea3de11e6e608d6c9f2cc9a7146257c523984f766c7b5bad68c2ce378b418ddf',
    'commands/common.py': 'b029a591ce2473beea47aa60d51b12c170a40bd92291a1d65dd15ed52606b493',
    'commands/install.py': '7de3f2072ee077a946bab9b5f652effd75877c33b9f4210e52ae3be64526cf1a',
    'backends/__init__.py': '0bd2d51327763006d40fc7c428243c6ada2606566ddecf8867547e861fbc98b3',
    'backends/pip.py': '38d4bd6776559603073185856184381fb956fe4d2a30c985e95670867a31fe68',
    'backends/uv.py': '20591d813cab9ea5dae51d3567f306980ed10ffdcbcfd703acb6932f2e88c4af',
}


class Budget:
    def __init__(self):
        self.lock = threading.Lock()
        self.expanded = 0
        self.records = 0
        self.deadline = time.monotonic() + 1800

    def consume(self, expanded=0, records=0):
        with self.lock:
            if time.monotonic() >= self.deadline:
                raise ValueError('APT metadata operation deadline exceeded')
            self.expanded += expanded
            self.records += records
            if self.expanded > 8 * 1024**3 or self.records > MAX_ROWS:
                raise ValueError('aggregate APT metadata work limit exceeded')


@contextmanager
def private_workspace(root: Path):
    """Own scratch bytes and retain them when worker termination is uncertain."""
    path = Path(tempfile.mkdtemp(prefix='.inventory-apt-', dir=root))
    retained = False

    def retain():
        nonlocal retained
        retained = True

    try:
        yield path, retain
    finally:
        if not retained:
            shutil.rmtree(path)


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if (len(url) > 8192 or re.search(r'[\x00-\x20\x7f\\]', url)
            or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.port not in {None, 443}
            or parsed.hostname in {'localhost', 'localhost.localdomain'}
            or parsed.hostname.endswith(('.localhost', '.local', '.internal'))
            or not re.fullmatch(r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}', parsed.hostname)):
        raise ValueError('APT metadata URL must be public HTTPS without credentials')
    # Public archive CDNs may issue expiring signed redirects. Query strings
    # stay inside the transfer and are never persisted or logged. Repository
    # declarations themselves are validated separately and forbid queries.
    return url


class Redirects(HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, request, fp, code, message, headers, newurl):
        public_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def fetch(url: str, limit: int, *, operation_deadline: float | None = None) -> bytes:
    public_url(url)
    deadline = time.monotonic() + TIMEOUT
    if operation_deadline is not None:
        deadline = min(deadline, operation_deadline)
    if time.monotonic() >= deadline:
        raise ValueError('public metadata operation deadline exceeded')
    opener = build_opener(ProxyHandler({}), Redirects())
    request = Request(url, headers={'User-Agent': 'preseed-inventory/1', 'Accept-Encoding': 'identity'})
    output = bytearray()
    with opener.open(request, timeout=15) as response:
        public_url(response.url)
        while True:
            if time.monotonic() >= deadline:
                raise ValueError('APT metadata transfer deadline exceeded')
            # read1 bounds one socket read, so a peer cannot keep read(n)
            # alive indefinitely by sending a byte before each idle timeout.
            block = response.read1(min(65536, limit + 1 - len(output)))
            if not block:
                return bytes(output)
            output.extend(block)
            if len(output) > limit:
                raise ValueError('APT metadata transfer exceeds byte limit')


def sha256_record(url: str, blob: bytes) -> dict:
    return {'url': public_url(url), 'size': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}


def json_object(blob: bytes) -> dict:
    # Check JSON structure before the decoder allocates nested lists/dicts.
    # Quotes and escapes are scanned as bytes; full syntax/UTF-8 validation
    # remains the decoder's job. Bounds apply to all public metadata adapters.
    depth, nodes, quoted, escaped = 0, 0, False, False
    for byte in blob:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
            continue
        if byte == 34:
            quoted = True
        elif byte in {91, 123}:
            depth += 1
            nodes += 1
        elif byte in {93, 125}:
            depth -= 1
        elif byte in {44, 58}:
            nodes += 1
        if not 0 <= depth <= 64 or nodes > 2000000:
            raise ValueError('public JSON metadata exceeds its nesting or aggregate structure bounds')

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('public JSON metadata repeats a field')
            value[key] = item
        return value

    def constant(_):
        raise ValueError('public JSON metadata contains a nonfinite number')

    value = json.loads(blob, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError('public JSON metadata is not an object')
    return value


def rustup_downloads(recipe: dict, budget: Budget) -> dict:
    """Resolve the source-selected profile using Rustup 1.29 manifest ordering."""
    channels, triples = recipe['toolchains'], recipe['target_triples']
    if not 0 < len(channels) <= 16 or not 0 < len(triples) <= 16:
        raise ValueError('Rustup channel/target declaration exceeds its bounds')
    archives, metadata, manifests = [], [], []
    for channel in channels:
        dated = re.fullmatch(r'(stable|beta|nightly)(?:-([0-9]{4}-[0-9]{2}-[0-9]{2}))?', channel)
        if dated:
            path = (dated[2] + '/' if dated[2] else '') + 'channel-rust-' + dated[1] + '.toml'
        elif re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', channel):
            path = 'channel-rust-' + channel + '.toml'
        else:
            raise ValueError('unsupported configured Rustup toolchain selector')
        url = 'https://static.rust-lang.org/dist/' + path
        budget.consume()
        sums = fetch(url + '.sha256', 8192, operation_deadline=budget.deadline)
        match = re.fullmatch(rb'\s*([a-f0-9]{64})(?:\s+\*?[A-Za-z0-9_.+-]+)?\s*', sums)
        if not match:
            raise ValueError('invalid Rustup manifest checksum descriptor')
        blob = fetch(url, 8 * 1024**2, operation_deadline=budget.deadline)
        budget.consume(expanded=len(blob) + len(sums))
        if hashlib.sha256(blob).hexdigest() != match[1].decode('ascii'):
            raise ValueError('Rustup manifest changed or failed its checksum')
        document = tomllib.loads(blob.decode('utf-8'))
        if (document.get('manifest-version') != '2'
                or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', document.get('date', ''))):
            raise ValueError('unsupported Rustup manifest identity')
        profile = document.get('profiles', {}).get(recipe['profile'])
        if (not isinstance(profile, list) or not 0 < len(profile) <= 32
                or any(not isinstance(name, str) for name in profile)):
            raise ValueError('Rustup manifest lacks its configured installation profile')
        components = sorted(set(profile + recipe['additional_components']))
        if len(components) > 64 or any(not re.fullmatch(r'[a-z][a-z0-9-]*', name) for name in components):
            raise ValueError('Rustup component declaration exceeds its bounds')
        for triple in triples:
            if not re.fullmatch(r'(?:x86_64|aarch64)-unknown-linux-gnu', triple):
                raise ValueError('unsupported configured Rustup Linux target')
            architecture = 'amd64' if triple.startswith('x86_64-') else 'arm64'
            if architecture not in recipe['architectures']:
                continue
            for component in components:
                budget.consume(records=1)
                package = document.get('renames', {}).get(component, {}).get('to', component)
                if not isinstance(package, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,127}', package):
                    raise ValueError('invalid Rustup component rename')
                details = document.get('pkg', {}).get(package, {})
                version = details.get('version')
                if not isinstance(version, str) or not 0 < len(version) <= 256:
                    raise ValueError('invalid Rustup component version metadata')
                target = details.get('target', {}).get(triple) or details.get('target', {}).get('*')
                if not isinstance(target, dict) or target.get('available') is not True:
                    raise ValueError('configured Rustup component is unavailable for its target')
                # Rustup 1.29 constructs bins in Zstandard, XZ, gzip order
                # and selects the first available pair. Do not emit all formats.
                for url_key, hash_key, compression in (('zst_url', 'zst_hash', 'zstd'),
                        ('xz_url', 'xz_hash', 'xz'), ('url', 'hash', 'gzip')):
                    if target.get(url_key) is not None and target.get(hash_key) is not None:
                        archive_url, checksum = target[url_key], target[hash_key]
                        break
                else:
                    raise ValueError('Rustup component lacks a downloadable archive/hash pair')
                parsed = urlsplit(public_url(archive_url))
                if (parsed.hostname != 'static.rust-lang.org' or parsed.query
                        or not parsed.path.startswith('/dist/') or not re.fullmatch(r'[a-f0-9]{64}', checksum)):
                    raise ValueError('Rustup component archive is outside its public distribution policy')
                if len(archives) >= MAX_PROTOCOL_FILES:
                    raise ValueError('Rustup archive selection exceeds the aggregate file limit')
                archives.append({'url': archive_url, 'sha256': checksum, 'architecture': architecture,
                                 'component': package, 'target': triple, 'toolchain': channel,
                                 'version': version, 'compression': compression,
                                 'manifest_url': url, 'manifest_date': document['date']})
        metadata.extend((sha256_record(url, blob), sha256_record(url + '.sha256', sums)))
        manifests.append({'toolchain': channel, 'date': document['date'], **sha256_record(url, blob)})
    if not archives:
        raise ValueError('Rustup declaration selects no eligible installation target')
    return dict(recipe, archives=archives, metadata_files=metadata, manifests=manifests, status='resolved',
                trust={'transport': 'HTTPS', 'manifest_consistency': 'SHA256', 'signature_verification': 'not_performed'})


def packer_downloads(recipe: dict, budget: Budget) -> dict:
    """Select the same unique Linux filename as the installer's signed sums adapter."""
    name, version = recipe['name'], recipe['version']
    if not re.fullmatch(r'[a-z]+', name) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('invalid exact Packer plugin declaration')
    if not recipe['architectures'] or set(recipe['architectures']) - {'amd64', 'arm64'}:
        raise ValueError('invalid Packer plugin architecture declaration')
    budget.consume()
    blob = fetch(recipe['checksums_url'], 1024 * 1024, operation_deadline=budget.deadline)
    budget.consume(expanded=len(blob))
    rows = {}
    for line in blob.decode('ascii').splitlines():
        fields = line.split()
        if (len(fields) != 2 or not re.fullmatch(r'[a-fA-F0-9]{64}', fields[0])
                or not re.fullmatch(r'\*?[A-Za-z0-9._-]{1,255}', fields[1])):
            raise ValueError('malformed Packer plugin checksum record')
        filename = fields[1].removeprefix('*')
        if filename in rows or len(rows) >= 4096:
            raise ValueError('duplicate or excessive Packer plugin checksum records')
        rows[filename] = fields[0].lower()
    archives = []
    for arch in recipe['architectures']:
        pattern = re.compile(r'packer-plugin-' + re.escape(name) + r'_(?:v)?' + re.escape(version)
                             + r'(?:_x[0-9]+\.[0-9]+)?_linux_' + re.escape(arch) + r'\.zip')
        matches = [(filename, checksum) for filename, checksum in rows.items() if pattern.fullmatch(filename)]
        if len(matches) != 1:
            raise ValueError('Packer plugin lacks a unique exact-version Linux archive')
        filename, checksum = matches[0]
        archives.append({'url': public_url(recipe['base_url'] + filename), 'filename': filename,
                         'sha256': checksum, 'architecture': arch, 'version': version})
    metadata = [sha256_record(recipe['checksums_url'], blob)]
    for key in ('signature_url', 'key_url'):
        if not recipe.get(key):
            raise ValueError('Packer plugin lacks its signing metadata declaration')
        metadata.append({'url': public_url(recipe[key])})
    fingerprint = recipe.get('signing_key_fingerprint')
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[A-F0-9]{40}', fingerprint):
        raise ValueError('Packer plugin lacks its pinned signing-key fingerprint')
    return dict(recipe, archives=archives, metadata_files=metadata, status='resolved',
                trust={'checksum_consistency': 'SHA256', 'signature_verification': 'not_performed',
                       'required_signing_key_fingerprint': fingerprint})


def discord_downloads(recipe: dict, budget: Budget) -> dict:
    """Read the installer's full host/all-module distribution policy as data."""
    policy = recipe['manifest_policy']
    url = recipe['manifest_url']
    if url != 'https://updates.discord.com/distributions/app/manifests/latest?channel=stable&platform=linux&arch=x64':
        raise ValueError('unsupported Discord distribution manifest endpoint')
    budget.consume()
    blob = fetch(url, 1024 * 1024, operation_deadline=budget.deadline)
    budget.consume(expanded=len(blob))
    manifest = json_object(blob)

    def fields(value, key):
        if not isinstance(value, dict) or set(value) != set(policy[key]):
            raise ValueError('Discord distribution metadata differs from its source-defined schema')
        return value

    def version(value):
        if not isinstance(value, list) or len(value) != 3 or any(
                type(part) is not int or not 0 <= part <= 999999 for part in value):
            raise ValueError('invalid Discord host version triple')
        return '.'.join(str(part) for part in value)

    def module_version(value):
        if type(value) is not int or not 1 <= value <= 999999:
            raise ValueError('invalid Discord module version')
        return value

    def artifact(value, expected_path):
        checksum, artifact_url = value.get('package_sha256'), value.get('url')
        if not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
            raise ValueError('invalid Discord distribution SHA-256')
        if not isinstance(artifact_url, str) or len(artifact_url) > 2048:
            raise ValueError('invalid Discord distribution URL')
        parsed = urlsplit(public_url(artifact_url))
        if (parsed.hostname not in policy['APPROVED_DISTRO_HOSTS'] or parsed.query
                or parsed.path != expected_path):
            raise ValueError('Discord distribution URL differs from its declared identity')
        return {'url': artifact_url, 'sha256': checksum, 'architecture': 'amd64'}

    def deltas(value, *, module=None, module_pin=None):
        if not isinstance(value, list) or len(value) > policy['MAX_DELTAS']:
            raise ValueError('invalid Discord delta metadata bounds')
        for delta in value:
            fields(delta, 'MODULE_DELTA_FIELDS' if module else 'HOST_DELTA_FIELDS')
            source = version(delta['host_version'])
            if module:
                source_module = module_version(delta['module_version'])
                if source == current and source_module == module_pin:
                    raise ValueError('Discord module delta repeats its full package')
                path = f'{base}/{module}/{module_pin}/from/{source}/{source_module}'
            else:
                if source == current:
                    raise ValueError('Discord host delta repeats its full package')
                path = f'{base}/from/{source}'
            artifact(delta, path)  # Validation only; the installer fetches full distributions.

    fields(manifest, 'MANIFEST_FIELDS')
    full = fields(manifest['full'], 'HOST_FULL_FIELDS')
    current = version(full['host_version'])
    base = '/distro/app/stable/linux/x64/' + current
    if type(manifest['required_update']) is not bool or (manifest['metadata_version'] is not None and
            (type(manifest['metadata_version']) is not int or manifest['metadata_version'] < 0)):
        raise ValueError('invalid Discord manifest metadata identity')
    modules, required = manifest['modules'], manifest['required_modules']
    if (not isinstance(modules, dict) or not len(policy['REQUIRED_MODULES']) <= len(modules) <= 32
            or not isinstance(required, list) or len(required) > 32
            or any(not isinstance(name, str) or not re.fullmatch(r'discord_[a-z0-9_]{1,64}', name) for name in required)
            or len(required) != len(set(required)) or not set(policy['REQUIRED_MODULES']).issubset(required)
            or not set(required).issubset(modules)):
        raise ValueError('invalid Discord required module selection')
    archives = [dict(artifact(full, base + '/full.distro'), component='host', version=current)]
    deltas(manifest['deltas'])
    for name, package in sorted(modules.items()):
        budget.consume(records=1)
        if not re.fullmatch(r'discord_[a-z0-9_]{1,64}', name):
            raise ValueError('invalid Discord module name')
        fields(package, 'MODULE_FIELDS')
        full = fields(package['full'], 'MODULE_FULL_FIELDS')
        if version(full['host_version']) != current:
            raise ValueError('Discord module targets another host version')
        pin = module_version(full['module_version'])
        deltas(package['deltas'], module=name, module_pin=pin)
        archives.append(dict(artifact(full, f'{base}/{name}/{pin}/full.distro'), component=name,
                             version=pin, host_version=current, required=name in required))
    return dict(recipe, archives=archives, metadata_files=[sha256_record(url, blob)], status='resolved',
                host_version=current, trust={'transport': 'HTTPS', 'artifact_consistency': 'manifest_SHA256',
                                             'signature_verification': 'not_performed'})


def codex_standalone_downloads(recipe: dict, budget: Budget) -> dict:
    """Resolve the reviewed install.sh's metadata protocol without running it."""
    reviewed_url = ('https://raw.githubusercontent.com/openai/codex/'
                    '89461ea6833832b0551ce24ee32205824d5c108d/scripts/install/install.sh')
    reviewed_sha256 = '95d14ccaba915e52a3f0cc590638ca5ac510086ff6a23dc9ac9f77e957403a93'
    if (recipe['installer_urls'] != [reviewed_url] or recipe['installer_sha256'] != reviewed_sha256
            or recipe['release'] != 'latest'):
        raise ValueError('standalone Codex installer revision needs a reviewed metadata adapter')
    budget.consume()
    source = fetch(reviewed_url, 1024 * 1024, operation_deadline=budget.deadline)
    budget.consume(expanded=len(source))
    if hashlib.sha256(source).hexdigest() != reviewed_sha256:
        raise ValueError('standalone Codex installer source differs from its pinned digest')
    platforms = {'amd64': ('x86_64-unknown-linux-musl', 'linux-x64'),
                 'arm64': ('aarch64-unknown-linux-musl', 'linux-arm64')}
    if not recipe['architectures'] or set(recipe['architectures']) - platforms.keys():
        raise ValueError('unsupported standalone Codex architecture selection')
    selected, attempts = None, []
    for endpoint, origin in (('https://releases.openai.com/codex/channels/latest', 'openai_releases'),
                             ('https://api.github.com/repos/openai/codex/releases/latest', 'github_releases')):
        budget.consume()
        try:
            blob = fetch(endpoint, 4 * 1024**2, operation_deadline=budget.deadline)
            budget.consume(expanded=len(blob))
            document = json_object(blob)
            tag, assets = document.get('tag_name'), document.get('assets')
            if not isinstance(tag, str) or not tag.startswith('rust-v') or not re.fullmatch(
                    r'[0-9]+\.[0-9]+\.[0-9]+(?:-alpha(?:\.[0-9]+){0,2}|-beta(?:\.[0-9]+)?)?', tag[6:]):
                raise ValueError('invalid standalone Codex release identity')
            version = tag[6:]
            if not isinstance(assets, list) or not 0 < len(assets) <= 1024:
                raise ValueError('invalid standalone Codex release asset bounds')
            checksums = {}
            for asset in assets:
                if not isinstance(asset, dict):
                    raise ValueError('invalid standalone Codex asset metadata')
                name, checksum = asset.get('name'), asset.get('digest')
                if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9._+-]{1,255}', name):
                    raise ValueError('invalid standalone Codex asset name')
                if name in checksums:
                    raise ValueError('standalone Codex release repeats an asset name')
                if isinstance(checksum, str) and re.fullmatch(r'sha256:[a-fA-F0-9]{64}', checksum):
                    checksums[name] = checksum[7:].lower()
            chosen = []
            for arch in recipe['architectures']:
                target, npm = platforms[arch]
                package, sums = 'codex-package-' + target + '.tar.gz', 'codex-package_SHA256SUMS'
                legacy = f'codex-npm-{npm}-{version}.tgz'
                if package in checksums and sums in checksums:
                    chosen.append((arch, package, sums, 'package'))
                elif legacy in checksums:
                    chosen.append((arch, legacy, None, 'legacy-platform-npm'))
                else:
                    raise ValueError('standalone Codex release lacks the selected Linux archive')
            selected = (endpoint, origin, blob, version, checksums, chosen)
            break
        except (OSError, ValueError, URLError) as error:
            attempts.append({'origin': origin, 'error': type(error).__name__})
    if selected is None:
        raise ValueError('standalone Codex release metadata is unavailable from both configured origins')
    endpoint, origin, blob, version, checksums, chosen = selected
    github = f'https://github.com/openai/codex/releases/download/rust-v{version}/'
    base = f'https://releases.openai.com/codex/releases/{version}/' if origin == 'openai_releases' else github
    metadata, archives, downloaded_sums = [sha256_record(reviewed_url, source), sha256_record(endpoint, blob)], [], {}
    for arch, filename, sums, layout in chosen:
        expected = checksums[filename]
        if sums:
            if sums not in downloaded_sums:
                candidates = list(dict.fromkeys((base + sums, github + sums)))
                for candidate in candidates:
                    budget.consume()
                    try:
                        sums_blob = fetch(candidate, 1024 * 1024, operation_deadline=budget.deadline)
                        budget.consume(expanded=len(sums_blob))
                        if hashlib.sha256(sums_blob).hexdigest() != checksums[sums]:
                            raise ValueError('standalone Codex checksum file differs from release metadata')
                        downloaded_sums[sums] = (candidate, sums_blob)
                        metadata.append(sha256_record(candidate, sums_blob))
                        break
                    except (OSError, ValueError, URLError):
                        continue
                else:
                    raise ValueError('standalone Codex package checksum file is unavailable or inconsistent')
            candidate, sums_blob = downloaded_sums[sums]
            matches = [line.split()[0].lower() for line in sums_blob.decode('ascii').splitlines()
                       if len(line.split()) == 2 and line.split()[1] == filename
                       and re.fullmatch(r'[a-fA-F0-9]{64}', line.split()[0])]
            if len(matches) != 1 or matches[0] != expected:
                raise ValueError('standalone Codex archive digest differs between release and package metadata')
        archive = {'url': public_url(base + filename), 'filename': filename, 'sha256': expected,
                   'architecture': arch, 'version': version, 'layout': layout}
        if base != github:
            archive['fallback_urls'] = [public_url(github + filename)]
        archives.append(archive)
    return dict(recipe, archives=archives, metadata_files=metadata, status='resolved', release_origin=origin,
                resolved_version=version, metadata_attempts=attempts,
                trust={'installer_source': 'checkout_SHA256_pin', 'artifact_consistency': 'release_and_package_SHA256',
                       'signature_verification': 'not_performed'})


def npm_version(value: str) -> tuple:
    """Strict SemVer precedence; never compare npm versions lexicographically."""
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError('invalid npm version bounds')
    match = re.fullmatch(r'v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
                         r'(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?', value)
    if not match:
        raise ValueError('unsupported npm version syntax')
    core = tuple(int(part) for part in match.groups()[:3])
    if any(part > 2**53 - 1 for part in core):
        raise ValueError('npm version component exceeds the SemVer integer limit')
    pre = []
    for part in match[4].split('.') if match[4] else []:
        if part.isdecimal() and len(part) > 1 and part.startswith('0'):
            raise ValueError('npm prerelease number has a leading zero')
        pre.append((0, int(part)) if part.isdecimal() else (1, part))
    return core + (not bool(pre), tuple(pre))


def npm_range(requirement: str) -> list:
    """Compile npm's common comparator, wildcard, caret, tilde and hyphen forms.

    Git, URL, alias, workspace, loose-version and build-metadata selectors need
    an explicit adapter. Unsupported input never becomes an unconstrained range.
    """
    if not isinstance(requirement, str) or len(requirement) > 4096 or requirement.count('||') > 15:
        raise ValueError('invalid npm range bounds')
    result = []
    for arm in requirement.split('||'):
        comparisons, prereleases = [], set()

        def partial(text):
            text = text.removeprefix('v')
            # A prerelease must declare its complete core version.
            if '-' in text:
                key = npm_version(text)
                prereleases.add(key[:3])
                return key[:3], 3, text
            parts = text.split('.')
            if not 1 <= len(parts) <= 3:
                raise ValueError('unsupported npm partial-version syntax')
            numbers, wildcard = [], False
            for part in parts:
                if part in {'*', 'x', 'X'}:
                    wildcard = True
                elif wildcard or not re.fullmatch(r'0|[1-9][0-9]*', part):
                    raise ValueError('unsupported npm partial-version component')
                else:
                    number = int(part)
                    if number > 2**53 - 1:
                        raise ValueError('npm range component exceeds the SemVer integer limit')
                    numbers.append(number)
            core = tuple(numbers + [0] * (3 - len(numbers)))
            return core, len(numbers), '.'.join(str(part) for part in core)

        def compare(operator, value):
            comparisons.append((operator, npm_version(value)))

        def upper(core, position):
            parts = list(core)
            parts[position] += 1
            for index in range(position + 1, 3):
                parts[index] = 0
            return '.'.join(str(part) for part in parts)

        arm = arm.strip()
        hyphen = re.fullmatch(r'(\S+)\s+-\s+(\S+)', arm)
        if hyphen:
            low, precision, value = partial(hyphen[1])
            if precision:
                compare('>=', value)
            high, precision, value = partial(hyphen[2])
            if precision == 3:
                compare('<=', value)
            elif precision:
                compare('<', upper(high, precision - 1) + '-0')
        else:
            arm = re.sub(r'([<>=~^])\s+', r'\1', arm.replace('~>', '~'))
            tokens = arm.split() or ['*']
            if len(tokens) > 64:
                raise ValueError('npm comparator count exceeds its limit')
            for token in tokens:
                match = re.fullmatch(r'(<=|>=|<|>|=|~|\^)?(.+)', token)
                if match is None:
                    raise ValueError('unsupported npm comparator syntax')
                operator, operand = match[1] or '=', match[2]
                core, precision, value = partial(operand)
                if precision == 0:
                    if operator in {'<', '>'}:
                        compare('<', '0.0.0-0')  # An unsatisfiable comparator.
                    continue
                if operator == '^':
                    position = (0 if core[0] or precision == 1 else
                                1 if core[1] or precision == 2 else 2)
                    compare('>=', value)
                    compare('<', upper(core, position) + '-0')
                elif operator == '~':
                    compare('>=', value)
                    compare('<', upper(core, 0 if precision == 1 else 1) + '-0')
                elif precision == 3:
                    compare(operator, value)
                elif operator == '=':
                    compare('>=', value)
                    compare('<', upper(core, precision - 1) + '-0')
                elif operator in {'>', '<='}:
                    compare('>=' if operator == '>' else '<', upper(core, precision - 1) +
                            ('' if operator == '>' else '-0'))
                else:
                    compare(operator, value + ('-0' if operator == '<' else ''))
        result.append((comparisons, prereleases))
    return result


def npm_matches(version: tuple, compiled: list) -> bool:
    for comparisons, prereleases in compiled:
        if not version[3] and version[:3] not in prereleases:
            continue
        if all({'=': version == bound, '>': version > bound, '<': version < bound,
                '>=': version >= bound, '<=': version <= bound}[operator]
               for operator, bound in comparisons):
            return True
    return False


def npm_archive_data(environment: dict, budget: Budget, *, include_files: tuple = ()) -> tuple[dict, dict, dict]:
    """Read bounded npm archive metadata and selected inert source bytes."""
    if len(include_files) > 16 or any(not isinstance(path, str) or not re.fullmatch(
            r'package/[A-Za-z0-9_./+-]{1,255}', path) or '..' in PurePosixPath(path).parts for path in include_files):
        raise ValueError('invalid npm selected metadata file declaration')
    blob = fetch(environment['url'], MAX_COMPRESSED, operation_deadline=budget.deadline)
    if hashlib.sha512(blob).hexdigest() != environment['sha512']:
        raise ValueError('npm root archive differs from its configured SHA512 pin')
    record = dict(sha256_record(environment['url'], blob), sha512=environment['sha512'])

    class ExpandedReader:
        def __init__(self, stream):
            self.stream, self.count = stream, 0

        def read(self, size):
            if size < 0 or size > 1024**2:
                raise ValueError('unbounded npm archive metadata read is prohibited')
            block = self.stream.read1(size)
            self.count += len(block)
            budget.consume(expanded=len(block))
            if self.count > MAX_EXPANDED:
                raise ValueError('npm archive exceeds its expanded byte limit')
            return block

    headers, header_bytes, header_depth = 0, 0, 0

    class BoundedTarInfo(tarfile.TarInfo):
        def _proc_member(self, archive):
            # TarFile processes PAX/GNU headers before yielding members. Bound
            # those headers before its parser allocates their data or recurses.
            nonlocal headers, header_bytes, header_depth
            headers += 1
            header_bytes += 512
            budget.consume(records=1)
            if headers > 8192 or self.size < 0 or self.size > MAX_EXPANDED:
                raise ValueError('npm archive header/count limit exceeded')
            if self.type in {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE}:
                # PAX can request GNU sparse processing before TarInfo is
                # returned. This root adapter accepts USTAR/GNU names only;
                # do not enter an unbounded sparse/PAX expansion path.
                raise ValueError('npm PAX archive metadata requires an explicit bounded adapter')
            if self.type in {tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK} and self.size > 64 * 1024:
                raise ValueError('npm extended archive header exceeds 64 KiB')
            if self.type in {tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}:
                header_bytes += self.size
            if header_bytes > 8 * 1024**2:
                raise ValueError('npm aggregate archive header metadata exceeds eight MiB')
            if self.type == tarfile.GNUTYPE_SPARSE:
                raise ValueError('npm sparse archive metadata is unsupported')
            if header_depth >= 16:
                raise ValueError('npm extended archive header recursion exceeds its bound')
            header_depth += 1
            try:
                return super()._proc_member(archive)
            finally:
                header_depth -= 1

    package, members, declared, bundled, shrinkwrap, gypfile = None, 0, 0, False, False, False
    source_files, selected_bytes = {}, 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
            with tarfile.open(fileobj=ExpandedReader(stream), mode='r|', tarinfo=BoundedTarInfo) as archive:
                for member in archive:
                    budget.consume(records=1)
                    members += 1
                    declared += member.size
                    if members > 8192 or declared > MAX_EXPANDED or member.size < 0:
                        raise ValueError('npm archive member/declared-byte limit exceeded')
                    path = member.name.rstrip('/') if member.isdir() else member.name
                    if (path != 'package' and not path.startswith('package/') or path.startswith('/')
                            or '\\' in path or '\x00' in path or '..' in PurePosixPath(path).parts
                            or '//' in path or '/./' in path or path.endswith('/.')):
                        raise ValueError('unsafe npm archive metadata member path')
                    shrinkwrap = shrinkwrap or path == 'package/npm-shrinkwrap.json'
                    gypfile = gypfile or path == 'package/binding.gyp'
                    bundled = bundled or path.startswith('package/node_modules/')
                    if path != 'package/package.json' and path not in include_files:
                        continue
                    limit = 1024**2 if path == 'package/package.json' else 128 * 1024
                    if ((path == 'package/package.json' and package is not None) or path in source_files
                            or not member.isfile() or member.sparse is not None or member.size > limit):
                        raise ValueError('npm archive has duplicate, nonregular or oversized package metadata')
                    reader = archive.extractfile(member)
                    if reader is None:
                        raise ValueError('npm archive package metadata is unreadable')
                    with reader:
                        data = reader.read(limit + 1)
                    selected_bytes += len(data)
                    if len(data) != member.size or selected_bytes > 4 * 1024**2:
                        raise ValueError('npm selected archive metadata exceeds its length/aggregate bounds')
                    if path == 'package/package.json':
                        package = json_object(data)
                    else:
                        source_files[path] = data
    except (tarfile.TarError, EOFError, OSError, zlib.error) as error:
        raise ValueError('npm archive metadata is not a readable bounded tar stream') from error
    if package is None or package.get('name') != environment['name'] or package.get('version') != environment['version']:
        raise ValueError('npm archive package identity differs from the selected manifest')
    if shrinkwrap:
        package['hasShrinkwrap'] = True
    if gypfile:
        package['gypfile'] = True
    if bundled:
        package['bundledDependencies'] = True
    return package, record, source_files


def npm_archive_manifest(environment: dict, budget: Budget) -> tuple[dict, dict]:
    """Bind a local-tarball root to exactly the package metadata npm consumes."""
    package, record, _ = npm_archive_data(environment, budget)
    if (not isinstance(package.get('engines'), dict)
            or package['engines'].get('node') != environment['node_requirement']):
        raise ValueError('npm root archive Node requirement differs from installer policy')
    return package, record


def npm_integrity_fields(integrity: str) -> dict:
    if not isinstance(integrity, str) or len(integrity) > 4096:
        raise ValueError('invalid npm archive integrity bounds')
    fields = {}
    for value in integrity.split():
        match = re.fullmatch(r'(sha512|sha256)-([A-Za-z0-9+/]+={0,2})', value)
        if not match:
            continue
        digest = base64.b64decode(match[2], validate=True)
        if len(digest) != {'sha512': 64, 'sha256': 32}[match[1]]:
            raise ValueError('invalid npm archive integrity digest length')
        if match[1] in fields and fields[match[1]] != digest.hex():
            raise ValueError('npm archive advertises alternative digests requiring explicit resolution')
        fields[match[1]] = digest.hex()
    if not fields:
        raise ValueError('npm archive requires a SHA256/SHA512 integrity adapter')
    return fields


def npm_install_hook(item: dict, selected: dict, environment: dict, budget: Budget) -> tuple[dict, dict | None]:
    """Recognize two reviewed hooks by archive and script byte identity only."""
    contracts = {
        ('esbuild', '0.28.1'): {
            'archive_sha512': '1eb26bbd9bf96b2c41ccf7f0a613a837393338822589fce4d0a26b18ad9cf11e3e2caa4cb6960b41e51d8e7c235affcb665907da569993ee30efca62f7d0f857',
            'script_sha256': '612294e278914443bdcf81cb17f54afec34dbdd2ebd999a6ee187912320cc315',
            'targets': {'amd64': '@esbuild/linux-x64', 'arm64': '@esbuild/linux-arm64'},
            'binary_path': 'bin/esbuild'},
        ('workerd', '1.20260826.1'): {
            'archive_sha512': 'a131bda2de73c4ef4e8e3282b24b7cebe9d5ac12f492252a1311e761a4e0e0e0a41dffcae33afef6162f830986f03742586d1340612b1f30fed61e744cce5bfb',
            'script_sha256': 'c3b7a7dfa6a727d5c0654c7d738cb64ce1b28d30a4533f12577ba4704ca77c91',
            'targets': {'amd64': '@cloudflare/workerd-linux-64', 'arm64': '@cloudflare/workerd-linux-arm64'},
            'binary_path': 'bin/workerd'},
    }
    contract = contracts.get((item['name'], item['version']))
    unresolved = {'package': item['name'] + '@' + item['version'], 'status': 'requires_source_review'}
    if contract is None:
        return unresolved, None
    if item['lifecycle'] != {'postinstall': 'node install.js'}:
        raise ValueError('reviewed npm install-hook command differs from the selected package metadata')
    dist = item.get('dist', {})
    fields = npm_integrity_fields(dist.get('integrity'))
    if fields.get('sha512') != contract['archive_sha512']:
        raise ValueError('npm install-hook archive differs from its reviewed source identity')
    package, record, files = npm_archive_data({'name': item['name'], 'version': item['version'],
        'url': dist['tarball'], 'sha512': fields['sha512']}, budget, include_files=('package/install.js',))
    script = files.get('package/install.js')
    if script is None or hashlib.sha256(script).hexdigest() != contract['script_sha256']:
        raise ValueError('npm install-hook script differs from the reviewed protocol')
    if package.get('scripts', {}).get('postinstall') != 'node install.js':
        raise ValueError('npm archive install hook differs from its registry declaration')
    if any(package.get(field) for field in ('bundleDependencies', 'bundledDependencies', 'hasShrinkwrap', 'gypfile')):
        return dict(unresolved, reason='install_hook_archive_requires_dependency_resolution'), record
    native_name = contract['targets'].get(environment['architecture'])
    native = selected.get(native_name + '@' + item['version']) if native_name else None
    if (native is None or package.get('optionalDependencies', {}).get(native_name) != item['version']
            or any(native.get(field) for field in ('dependencies', 'optionalDependencies', 'peerDependencies',
                   'bundleDependencies', 'bundledDependencies', 'hasShrinkwrap', 'gypfile', 'hasInstallScript', 'lifecycle'))):
        return dict(unresolved, reason='native_fallback_dependency_requires_resolution'), record
    unscoped = native_name.partition('/')[2]
    url = 'https://registry.npmjs.org/' + native_name + '/-/' + unscoped + '-' + item['version'] + '.tgz'
    if native.get('dist', {}).get('tarball') != url:
        return dict(unresolved, reason='native_fallback_url_requires_identity_resolution'), record
    binary_hash = None
    if item['name'] == 'esbuild':
        binary_hash = package.get('esbuild.binaryHashes', {}).get(native_name + '/' + contract['binary_path'])
        if not isinstance(binary_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', binary_hash):
            raise ValueError('reviewed esbuild hook lacks its selected fallback binary SHA256')
    return {'package': unresolved['package'], 'status': 'resolved', 'script_path': 'package/install.js',
            'script_sha256': contract['script_sha256'], 'source_archive_url': dist['tarball'],
            'required_platform_package': native_name, 'version': item['version'],
            'binary_path': contract['binary_path'], 'fallback_member_sha256': binary_hash,
            'fallback_url': url, 'fallback_condition': 'matching_optional_platform_package_unavailable',
            'additional_archives_beyond_selected_platform_package': False}, record


def npm_downloads(recipe: dict, budget: Budget) -> dict:
    """Resolve production metadata; expose placement and hook uncertainty.

    A graph is promoted only when candidate reuse cannot change its set of
    package versions. This is a deliberately checked condition, not a claim
    that this stdlib reader implements npm Arborist's full placement solver.
    """
    environments = recipe['environments']
    if not isinstance(environments, list) or not 0 < len(environments) <= 128:
        raise ValueError('npm environment count exceeds its bounds')
    node_url = 'https://nodejs.org/dist/index.json'
    blob = fetch(node_url, 4 * 1024**2, operation_deadline=budget.deadline)
    budget.consume(expanded=len(blob))
    nodes = json.loads(blob)
    if not isinstance(nodes, list) or len(nodes) > 10000 or any(not isinstance(row, dict) for row in nodes):
        raise ValueError('invalid Node release metadata bounds')
    evidence = {node_url: sha256_record(node_url, blob)}
    answers, archives, graphs, unresolved, retained = {}, {}, [], [], 0

    def retain(value):
        nonlocal retained
        retained += len(json.dumps(value, allow_nan=False).encode('utf-8'))
        if retained > 32 * 1024**2:
            raise ValueError('npm retained protocol metadata exceeds its byte limit')

    def document(url, limit):
        blob = fetch(url, limit, operation_deadline=budget.deadline)
        budget.consume(expanded=len(blob), records=1)
        record = sha256_record(url, blob)
        if url in evidence and evidence[url] != record:
            raise ValueError('npm metadata changed within one inventory acquisition')
        if url not in evidence:
            retain(record)
            evidence[url] = record
        return json_object(blob)

    def package_name(name):
        if not isinstance(name, str) or not re.fullmatch(r'(?:@[a-z0-9_.-]+/)?[a-z0-9_][a-z0-9_.-]{0,213}', name):
            raise ValueError('unsupported npm registry package name')
        return name

    def engine_ok(item, node_version, npm_cli):
        engines = item.get('engines', {})
        if not isinstance(engines, dict):
            raise ValueError('invalid npm package engine constraints')
        return all(not engines.get(key) or npm_matches(value, npm_range(engines[key]))
                   for key, value in (('node', node_version), ('npm', npm_cli)))

    def manifest(registry, name, wanted, node_version, npm_cli):
        package_name(name)
        key = (registry, name, wanted, node_version, npm_cli)
        if key in answers:
            return answers[key]
        try:
            exact = npm_version(wanted)
        except ValueError:
            exact = None
        endpoint = registry + quote(name, safe='@')
        if exact is not None:
            item = document(endpoint + '/' + quote(wanted.removeprefix('v'), safe=''), 1024**2)
        else:
            compiled = npm_range(wanted)
            packument = document(endpoint, 32 * 1024**2)
            versions = packument.get('versions')
            if (not isinstance(versions, dict) or not 0 < len(versions) <= 50000
                    or packument.get('policyRestrictions') or packument.get('stagedVersions')):
                raise ValueError('npm registry version policy requires an explicit adapter')
            tags = packument.get('dist-tags', {})
            if not isinstance(tags, dict):
                raise ValueError('invalid npm registry distribution tags')
            latest = tags.get('latest')
            item, best_rank = None, None
            for version, candidate in versions.items():
                budget.consume()
                order = npm_version(version)
                if not npm_matches(order, compiled):
                    continue
                if not isinstance(candidate, dict):
                    raise ValueError('npm version manifest is not an object')
                compatible = engine_ok(candidate, node_version, npm_cli)
                deprecated = bool(candidate.get('deprecated'))
                if version == latest and compatible and not deprecated:
                    item = candidate
                    break
                rank = (compatible and not deprecated, compatible, not deprecated, order)
                if best_rank is None or rank > best_rank:
                    item, best_rank = candidate, rank
            if item is None:
                raise ValueError('npm dependency has no version matching its declared range')
        if item.get('name') != name:
            raise ValueError('npm manifest name differs from the requested package')
        order = npm_version(item.get('version'))
        if exact is not None and order != exact:
            raise ValueError('npm exact version manifest differs from its selector')
        # Avoid retaining readmes, user identities, development scripts and
        # every unselected upstream version in the inventory or its cache.
        item = trim(item)
        retain(item)
        if len(answers) >= MAX_PROTOCOL_FILES:
            raise ValueError('npm selected manifest count exceeds its limit')
        answers[key] = item
        return item

    def trim(item):
        scripts = item.get('scripts', {})
        dist = item.get('dist', {})
        if not isinstance(scripts, dict) or not isinstance(dist, dict) or any(
                not isinstance(scripts[key], str) or len(scripts[key]) > 8192
                for key in ('preinstall', 'install', 'postinstall') if key in scripts):
            raise ValueError('invalid npm lifecycle or distribution metadata')
        fields = ('name', 'version', 'dependencies', 'optionalDependencies', 'peerDependencies',
                  'peerDependenciesMeta', 'bundleDependencies', 'bundledDependencies',
                  'hasShrinkwrap', 'hasInstallScript', 'gypfile', 'os', 'cpu', 'libc', 'engines', 'dist')
        return {field: item[field] for field in fields if field in item} | {
            'lifecycle': {field: scripts[field] for field in ('preinstall', 'install', 'postinstall') if field in scripts}}

    def platform_ok(item, environment):
        for field, target in (('os', environment['platform']), ('libc', environment['libc']),
                              ('cpu', {'amd64': 'x64', 'arm64': 'arm64'}[environment['architecture']])):
            restrictions = item.get(field, [])
            if isinstance(restrictions, str):
                restrictions = [restrictions]
            if not isinstance(restrictions, list) or len(restrictions) > 64 or any(
                    not isinstance(value, str) for value in restrictions):
                raise ValueError('invalid npm platform restrictions')
            positive = [value for value in restrictions if not value.startswith('!')]
            if '!' + target in restrictions or positive and target not in positive and 'any' not in positive:
                return False
        return True

    def dependencies(item, field):
        result = item.get(field, {})
        if not isinstance(result, dict) or len(result) > 256 or any(
                not isinstance(value, str) or len(value) > 4096 for value in result.values()):
            raise ValueError('invalid npm dependency map bounds')
        for name in result:
            package_name(name)
        return result

    for environment in environments:
        architecture = environment['architecture']
        if architecture not in recipe['architectures']:
            continue
        registry = public_url(environment['registry_url'])
        if not registry.endswith('/') or urlsplit(registry).query:
            raise ValueError('npm registry must be a public HTTPS base without a query')
        node_rows = [row for row in nodes if row.get('version') == environment['node_version']]
        if len(node_rows) != 1 or not isinstance(node_rows[0].get('npm'), str):
            raise ValueError('pinned Node release lacks one bundled npm version in official metadata')
        node_version, npm_cli = npm_version(environment['node_version']), npm_version(node_rows[0]['npm'])
        source_url = ('https://raw.githubusercontent.com/npm/cli/v' + node_rows[0]['npm']
                      + '/node_modules/npm-pick-manifest/lib/index.js')
        if source_url not in evidence:
            source = fetch(source_url, 256 * 1024, operation_deadline=budget.deadline)
            budget.consume(expanded=len(source), records=1)
            record = sha256_record(source_url, source)
            if record['sha256'] != '541017d95a059450a9c1527c4fdd742741c9ecc941e47f82fabb6fdd17947242':
                raise ValueError('bundled npm selection source differs from the reviewed 11.19.0 contract')
            retain(record)
            evidence[source_url] = record
        selection = dict(recipe['selection'], phase='late', profiles=environment['profiles'], architecture=architecture)
        root = manifest(registry, environment['name'], environment['version'], node_version, npm_cli)
        root_dist = root.get('dist', {})
        if root_dist.get('tarball') != environment['url'] or root_dist.get('integrity') != environment['integrity']:
            raise ValueError('npm root registry identity differs from the configured immutable archive')
        pin = re.fullmatch(r'sha512-([A-Za-z0-9+/]+={0,2})', environment['integrity'])
        if (not pin or not re.fullmatch(r'[a-f0-9]{128}', environment['sha512'])
                or base64.b64decode(pin[1], validate=True).hex() != environment['sha512']):
            raise ValueError('npm configured root SHA512 and integrity pins disagree')
        package, root_archive = npm_archive_manifest(environment, budget)
        root = trim(dict(package, dist=root_dist))
        retain([root, root_archive])
        if environment['url'] in evidence and evidence[environment['url']] != root_archive:
            raise ValueError('npm root archive changed within one inventory acquisition')
        evidence[environment['url']] = root_archive
        # Metadata traversal never runs npm or any install/prepare script.
        todo = [(root, None, environment['version'], False)]
        selected, edges, omitted, peers, hooks, problems = {}, [], [], [], [], []

        def problem(value):
            retain(value)
            problems.append(value)

        while todo:
            budget.consume(records=1)
            if len(todo) + len(selected) > MAX_PROTOCOL_FILES:
                raise ValueError('npm dependency traversal exceeds its package limit')
            item, parent, wanted, optional = todo.pop(0)
            identity = item['name'] + '@' + item['version']
            edge = {'from': parent, 'name': item['name'], 'range': wanted,
                    'version': item['version'], 'optional': optional}
            if not platform_ok(item, environment):
                if not optional:
                    raise ValueError('required npm package is unavailable on the declared target platform')
                retain(edge)
                omitted.append(edge)
                continue
            retain(edge)
            edges.append(edge)
            if identity in selected:
                continue
            selected[identity] = item
            if item.get('bundleDependencies') or item.get('bundledDependencies') or item.get('hasShrinkwrap'):
                problem({'package': identity, 'reason': 'bundled_or_shrinkwrapped_dependencies_require_archive_resolution'})
            if item['lifecycle'] or item.get('hasInstallScript') or item.get('gypfile'):
                hook = {'package': identity, 'scripts': item['lifecycle'],
                        'implicit_install_requires_archive_review': bool(item.get('gypfile') or
                            item.get('hasInstallScript') and not item['lifecycle'])}
                retain(hook)
                hooks.append(hook)
            required = dependencies(item, 'dependencies')
            options = dependencies(item, 'optionalDependencies')
            for name, spec in sorted((required | options).items()):
                candidate = manifest(registry, name, spec, node_version, npm_cli)
                if len(todo) + len(selected) >= MAX_PROTOCOL_FILES:
                    raise ValueError('npm pending dependency count exceeds its limit')
                todo.append((candidate, identity, spec, name in options))
            metadata = item.get('peerDependenciesMeta', {})
            if not isinstance(metadata, dict):
                raise ValueError('invalid npm peer-dependency metadata')
            for name, spec in dependencies(item, 'peerDependencies').items():
                entry = metadata.get(name, {})
                if not isinstance(entry, dict) or 'optional' in entry and type(entry['optional']) is not bool:
                    raise ValueError('invalid npm optional-peer declaration')
                peer = {'from': identity, 'name': name, 'range': spec, 'optional': entry.get('optional', False)}
                retain(peer)
                peers.append(peer)
        by_name = {}
        for item in selected.values():
            by_name.setdefault(item['name'], []).append(item)
        for name, versions in by_name.items():
            if len(versions) != 1:
                problem({'package': name, 'reason': 'multiple_versions_require_npm_placement_resolution'})
        for peer in peers:
            present = by_name.get(peer['name'], [])
            if not present and peer['optional']:
                continue
            if len(present) != 1 or not npm_matches(npm_version(present[0]['version']), npm_range(peer['range'])):
                problem(dict(peer, reason='peer_set_requires_npm_placement_resolution'))
        if not problems:
            for hook in hooks:
                details, record = npm_install_hook(selected[hook['package']], selected, environment, budget)
                retain(details)
                hook.update(details)
                if record is not None:
                    url = record['url']
                    if url in evidence and evidence[url] != record:
                        raise ValueError('npm install-hook archive changed within one acquisition')
                    if url not in evidence:
                        retain(record)
                        evidence[url] = record
        graph = {'selection': selection, 'node_version': environment['node_version'], 'npm_version': node_rows[0]['npm'],
                 'packages': list(selected.values()), 'edges': edges, 'omitted_optional_packages': omitted,
                 'peers': peers, 'lifecycle_hooks': hooks, 'unresolved': problems}
        retain(graph)
        graphs.append(graph)
        if problems:
            for issue in problems:
                record = dict(issue, selection=selection)
                retain(record)
                unresolved.append(record)
            continue
        for item in selected.values():
            dist = item.get('dist', {})
            url, integrity = dist.get('tarball'), dist.get('integrity')
            if not isinstance(url, str) or urlsplit(public_url(url)).query or not isinstance(integrity, str):
                raise ValueError('npm selected archive lacks a public URL and content integrity')
            fields = npm_integrity_fields(integrity)
            if url in evidence:
                fields.update({key: evidence[url][key] for key in ('size', 'sha256') if key in evidence[url]})
            if item is root and fields.get('sha512') != environment['sha512']:
                raise ValueError('npm root SHA512 differs from its source pin')
            if item is root:
                fields.update({key: root_archive[key] for key in ('size', 'sha256')})
            candidate = dict(url=url, package=item['name'], version=item['version'], integrity=integrity,
                             architecture=architecture, selection=[selection], **fields)
            if url in archives:
                previous = archives[url]
                if any(previous.get(key) != candidate.get(key) for key in ('sha256', 'sha512', 'version', 'package')):
                    raise ValueError('npm archive URL has conflicting selected identities')
                if selection not in previous['selection']:
                    retain(selection)
                    previous['selection'].append(selection)
            else:
                if len(archives) >= MAX_PROTOCOL_FILES:
                    raise ValueError('npm selected archive count exceeds its limit')
                retain(candidate)
                archives[url] = candidate
        pending_hooks = [item['package'] for item in hooks if item.get('status') != 'resolved']
        if pending_hooks:
            record = {'selection': selection, 'reason': 'install_lifecycle_network_requires_source_review',
                      'packages': pending_hooks}
            retain(record)
            unresolved.append(record)
    status = ('requires_npm_target_environment' if not graphs else
              'requires_npm_protocol_resolution' if unresolved else 'resolved')
    return dict(recipe, status=status,
                archives=sorted(archives.values(), key=lambda row: row['url']), dependency_graphs=graphs,
                protocol_evidence=list(evidence.values()), unresolved=unresolved,
                trust={'archive_consistency': 'registry_SRI_and_configured_root_pin',
                       'signature_verification': 'not_performed'})


def crowdsec_data_files(blob: bytes) -> list:
    """Read root data sequences in hub YAML without loading a YAML interpreter.

    Only plain block mappings/sequences and quoted scalar values are accepted
    in data sections. Flow mappings, anchors, aliases and merges require a
    reviewed parser extension instead of silently omitting possible downloads.
    Other YAML content is retained as inert text, including expressions.
    """
    if len(blob) > 1024**2:
        raise ValueError('CrowdSec item exceeds the content byte limit')
    lines = blob.decode('utf-8').splitlines()
    result, position, document_data, root_key = [], 0, False, None
    key_pattern = re.compile(r'''^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[A-Za-z_][A-Za-z0-9_-]*|<<)\s*:\s*(.*)$''')

    def scalar(value):
        value = value.strip()
        if value.startswith('"'):
            decoder = json.JSONDecoder()
            parsed, end = decoder.raw_decode(value)
            rest = value[end:].strip()
            if not isinstance(parsed, str) or rest and not rest.startswith('#'):
                raise ValueError('unsupported CrowdSec data quoted scalar')
            return parsed
        if value.startswith("'"):
            match = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", value)
            if not match:
                raise ValueError('unsupported CrowdSec data quoted scalar')
            return match[1].replace("''", "'")
        value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
        if not value or value[0] in '&*!|>[]{},' or re.search(r'\s', value):
            raise ValueError('unsupported CrowdSec data scalar syntax')
        return value

    def finish(item):
        if not item:
            return
        if 'source_url' not in item or not item['source_url']:
            return  # The selected upstream downloader skips an empty source.
        url, path = item['source_url'], item.get('dest_file', '')
        parsed = urlsplit(public_url(url))
        if (parsed.query or not re.fullmatch(r'[A-Za-z0-9_./+-]{1,255}', path)
                or path.startswith('/') or '..' in PurePosixPath(path).parts or '//' in path):
            raise ValueError('unsafe CrowdSec data URL or relative destination')
        if len(result) >= 64:
            raise ValueError('CrowdSec item data-file count exceeds its limit')
        result.append({'url': url, 'destination': '/var/lib/crowdsec/data/' + path,
                       'component': 'hub_data', 'byte_identity': 'mutable_upstream_without_advertised_hash'})

    while position < len(lines):
        line = lines[position]
        position += 1
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line.startswith(('---', '...')):
            document_data = False
            root_key = None
            continue
        if line.startswith((' ', '\t')):
            if re.match(r'''^\s+(?:data|"data"|'data')\s*:''', line):
                raise ValueError('indented CrowdSec data mappings require explicit resolution')
            continue
        if (line == '-' or line.startswith('- ')) and root_key is not None:
            continue  # An indentationless sequence belonging to another key.
        field = key_pattern.fullmatch(line)
        if field is None:
            raise ValueError('unsupported CrowdSec YAML root mapping syntax')
        key = scalar(field[1])
        root_key = key
        # YAML root merges can hide a data section behind an alias. Do not
        # assume that an unparsed merge carries no network inputs.
        if key == '<<':
            raise ValueError('CrowdSec root YAML merges require explicit resolution')
        if key != 'data':
            continue
        if document_data:
            raise ValueError('CrowdSec YAML document repeats its data section')
        document_data = True
        tail = re.split(r'\s+#', field[2], maxsplit=1)[0].strip()
        if tail in {'[]', 'null', '~'}:
            continue
        if tail and not tail.startswith('#'):
            raise ValueError('CrowdSec data section requires a plain block sequence')
        item, sequence_indent = {}, None
        while position < len(lines):
            line = lines[position]
            if not line.strip() or line.lstrip().startswith('#'):
                position += 1
                continue
            if line.startswith(('---', '...')):
                break
            indent = len(line) - len(line.lstrip(' '))
            entry = line[indent:]
            # YAML allows an indentationless sequence immediately under data.
            if indent == 0 and entry != '-' and not entry.startswith('- '):
                break
            position += 1
            if '\t' in line[:indent + 1]:
                raise ValueError('unsupported CrowdSec data indentation')
            if entry == '-' or entry.startswith('- '):
                if sequence_indent is None:
                    sequence_indent = indent
                if indent != sequence_indent:
                    raise ValueError('nested CrowdSec data sequences require explicit resolution')
                finish(item)
                item = {}
                entry = entry[1:].strip()
                if not entry:
                    continue
            elif sequence_indent is None or indent != sequence_indent + 2:
                raise ValueError('unsupported CrowdSec data mapping indentation')
            field = key_pattern.fullmatch(entry)
            key = scalar(field[1]) if field else None
            if key not in {'source_url', 'dest_file', 'type'} or key in item:
                raise ValueError('unsupported or repeated CrowdSec data field')
            item[key] = scalar(field[2])
        finish(item)
    return result


def crowdsec_downloads(recipe: dict, budget: Budget, apt: dict) -> dict:
    """Bind selected engines to their hub branches, recursive items and data."""
    item_types = {'collections', 'parsers', 'scenarios', 'postoverflows', 'contexts',
                  'appsec-configs', 'appsec-rules'}
    roots = recipe['items']
    if not isinstance(roots, list) or not 0 < len(roots) <= 256:
        raise ValueError('invalid CrowdSec direct item declaration bounds')
    for root in roots:
        if (root.get('type') not in item_types or not isinstance(root.get('name'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', root['name'])):
            raise ValueError('invalid CrowdSec direct hub item identity')
    evidence, retained = [], 0

    def retain(value):
        nonlocal retained
        retained += len(value) if isinstance(value, bytes) else len(json.dumps(value, allow_nan=False).encode('utf-8'))
        if retained > 32 * 1024**2:
            raise ValueError('CrowdSec retained protocol data exceeds its byte limit')

    phase_order = {name: rank for rank, name in enumerate(('installer_udeb', 'base_system', 'base_upgrade',
                    'pre_pkgsel', 'pkgsel', 'late', 'first_boot'))}
    terminal = {}
    for row in apt.get('packages', []):
        if row['package'] != 'crowdsec':
            continue
        for use in row.get('uses', []):
            budget.consume(records=1)
            if (use.get('operation') != 'install' or use.get('download_only')
                    or use.get('phase') not in phase_order):
                continue
            key = (use['context'], use['architecture'])
            previous = terminal.get(key)
            rank = phase_order[use['phase']]
            if previous and rank == previous[0] and row['version'] != previous[1]['version']:
                raise ValueError('CrowdSec final engine version needs within-phase transaction ordering')
            if previous is None or rank > previous[0]:
                terminal[key] = (rank, row, use)
            if len(terminal) > 16384:
                raise ValueError('CrowdSec installation context count exceeds its limit')
    if not terminal:
        return dict(recipe, status='requires_selected_crowdsec_engine')
    versions = {}
    for _, engine, use in terminal.values():
        match = re.fullmatch(r'(?:[0-9]+:)?v?([0-9]+\.[0-9]+\.[0-9]+)(?:[-+~][A-Za-z0-9.+~_-]+)?', engine['version'])
        if not match:
            raise ValueError('selected CrowdSec engine needs an explicit upstream-version adapter')
        identity = {key: engine[key] for key in ('version', 'architecture', 'repository', 'url', 'sha256')}
        identity['selected_for'] = {key: use[key] for key in ('context', 'architecture', 'profiles', 'phase') if key in use}
        retain(identity)
        versions.setdefault('v' + match[1], []).append(identity)
    if len(versions) > 16:
        raise ValueError('CrowdSec selected-engine version count exceeds its limit')
    for version in sorted(versions):
        for path, checksums in CROWDSEC_CONTRACT.items():
            url = 'https://raw.githubusercontent.com/crowdsecurity/crowdsec/' + version + '/' + path
            blob = fetch(url, 256 * 1024, operation_deadline=budget.deadline)
            budget.consume(expanded=len(blob), records=1)
            if hashlib.sha256(blob).hexdigest() not in checksums:
                raise ValueError('selected CrowdSec protocol source differs from the reviewed contract; version=' + version)
            record = sha256_record(url, blob)
            retain(record)
            evidence.append(record)
    latest_url = 'https://version.crowdsec.net/latest'
    blob = fetch(latest_url, 64 * 1024, operation_deadline=budget.deadline)
    budget.consume(expanded=len(blob))
    latest = json_object(blob).get('name')
    if not isinstance(latest, str) or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', latest):
        raise ValueError('invalid CrowdSec latest-version response')
    metadata, archives, embedded, manifests = [sha256_record(latest_url, blob)], {}, {}, []

    def add_file(destination, key, candidate):
        if key in destination:
            raise ValueError('CrowdSec hub index repeats a selected item URL')
        if len(archives) + len(embedded) + len(metadata) >= MAX_PROTOCOL_FILES:
            raise ValueError('CrowdSec selected file count exceeds its limit')
        retain(candidate)
        destination[key] = candidate

    latest_order = tuple(int(part) for part in latest[1:].split('.'))
    branches = {}
    for version, identities in sorted(versions.items()):
        order = tuple(int(part) for part in version[1:].split('.'))
        branch = 'master' if order >= latest_order else version
        branches.setdefault(branch, []).extend(identities)
    for branch, identities in sorted(branches.items()):
        base = 'https://cdn-hub.crowdsec.net/crowdsecurity/' + branch + '/'
        index_url = base + '.index.json'
        blob = fetch(index_url, 32 * 1024**2, operation_deadline=budget.deadline)
        budget.consume(expanded=len(blob))
        index = json_object(blob)
        if any(not isinstance(value, dict) for key, value in index.items() if key in item_types):
            raise ValueError('invalid CrowdSec hub index item map')
        if sum(len(index.get(key, {})) for key in item_types) > 50000:
            raise ValueError('CrowdSec hub index item count exceeds its limit')
        record = sha256_record(index_url, blob)
        manifest = {'branch': branch, 'selected_engines': identities, 'latest_version': latest, **record}
        retain([record, manifest])
        if len(archives) + len(embedded) + len(metadata) >= MAX_PROTOCOL_FILES:
            raise ValueError('CrowdSec selected file count exceeds its limit')
        metadata.append(record)
        manifests.append(manifest)
        contents = {}
        for root in roots:
            if root.get('condition') and not root.get('profiles'):
                continue
            selection = dict(recipe['selection'], phase=recipe['phase'])
            selection['engine_package_urls'] = sorted({item['url'] for item in identities})
            if root.get('condition'):
                selection.update(profiles=root['profiles'], condition=root['condition'])
            todo, visited = [(root['type'], root['name'])], set()
            while todo:
                budget.consume(records=1)
                if len(todo) + len(visited) > MAX_PROTOCOL_FILES:
                    raise ValueError('CrowdSec dependency traversal exceeds its item limit')
                kind, name = todo.pop()
                identity = kind + ':' + name
                if identity in visited:
                    continue
                visited.add(identity)
                item = index.get(kind, {}).get(name)
                if not isinstance(item, dict):
                    raise ValueError('selected CrowdSec hub item or dependency is absent from its index')
                path, version = item.get('path'), item.get('version')
                if (not isinstance(path, str) or not re.fullmatch(r'[A-Za-z0-9_./+-]{1,512}', path)
                        or path.startswith('/') or '..' in PurePosixPath(path).parts or '//' in path
                        or not path.startswith(kind + '/') or not path.endswith(('.yml', '.yaml'))
                        or not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', version)):
                    raise ValueError('invalid CrowdSec hub item path or version')
                record = item.get('versions', {}).get(version)
                checksum = record.get('digest') if isinstance(record, dict) else None
                if not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
                    raise ValueError('CrowdSec hub item lacks its exact-version SHA-256')
                for dependency_type in sorted(item_types):
                    dependencies = item.get(dependency_type, [])
                    if not isinstance(dependencies, list) or len(dependencies) > 256 or any(
                            not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+', value)
                            for value in dependencies):
                        raise ValueError('invalid CrowdSec recursive dependency declaration')
                    if len(todo) + len(visited) + len(dependencies) > MAX_PROTOCOL_FILES:
                        raise ValueError('CrowdSec pending dependency count exceeds its limit')
                    todo.extend((dependency_type, dependency) for dependency in dependencies)
                url = base + path
                if identity not in contents:
                    content = item.get('content', '')
                    if not isinstance(content, str) or len(content) > 2 * 1024**2:
                        raise ValueError('CrowdSec embedded item content exceeds its bounds')
                    if content:
                        try:
                            content_bytes = base64.b64decode(content, validate=True)
                        except ValueError:
                            content_bytes = content.encode('utf-8')
                    else:
                        content_bytes = fetch(url, 1024**2, operation_deadline=budget.deadline)
                    budget.consume(expanded=len(content_bytes))
                    if len(content_bytes) > 1024**2 or hashlib.sha256(content_bytes).hexdigest() != checksum:
                        raise ValueError('CrowdSec item bytes differ from the selected index identity')
                    retain(content_bytes)
                    data_files = crowdsec_data_files(content_bytes)
                    contents[identity] = data_files
                    fields = {'component': 'hub_item', 'item_type': kind, 'item_name': name, 'version': version,
                              'sha256': checksum, 'size': len(content_bytes), 'branch': branch,
                              'index_url': index_url, 'destination': '/etc/crowdsec/hub/' + path, 'selection': []}
                    if content:
                        candidate = dict(fields, content_base64=base64.b64encode(content_bytes).decode('ascii'))
                        add_file(embedded, (branch, identity), candidate)
                    else:
                        candidate = dict(fields, url=url)
                        add_file(archives, url, candidate)
                    for data_file in data_files:
                        if data_file['url'] not in archives:
                            candidate = dict(data_file, selection=[], required_by=[])
                            add_file(archives, data_file['url'], candidate)
                        previous = archives[data_file['url']]
                        if previous.get('destination') != data_file['destination']:
                            raise ValueError('CrowdSec data URL has inconsistent staging destinations')
                item_record = embedded.get((branch, identity)) or archives[url]
                if selection not in item_record['selection']:
                    retain(selection)
                    item_record['selection'].append(selection)
                for data_file in contents[identity]:
                    data_record = archives[data_file['url']]
                    if selection not in data_record['selection']:
                        retain(selection)
                        data_record['selection'].append(selection)
                    reference = {'type': kind, 'name': name, 'branch': branch}
                    if reference not in data_record['required_by']:
                        retain(reference)
                        data_record['required_by'].append(reference)
                if len(archives) + len(embedded) + len(metadata) > MAX_PROTOCOL_FILES:
                    raise ValueError('CrowdSec selected file count exceeds its limit')
    return dict(recipe, status='resolved', archives=sorted(archives.values(), key=lambda row: row['url']),
                embedded_files=list(embedded.values()), metadata_files=metadata,
                protocol_evidence=evidence, manifests=manifests,
                trust={'item_consistency': 'index_SHA256', 'data_consistency': 'upstream_does_not_advertise_hashes',
                       'signature_verification': 'not_performed'})


def python_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9._-]{0,212}[A-Za-z0-9])?', value):
        raise ValueError('invalid Python distribution name')
    return re.sub(r'[-_.]+', '-', value).lower()


def python_metadata(blob: bytes) -> dict:
    """Read Core Metadata headers, including repeated dependency declarations."""
    if len(blob) > 1024**2 or b'\0' in blob:
        raise ValueError('Python distribution metadata exceeds its bounds')
    blob.decode('utf-8')
    headers = BytesParser().parsebytes(blob, headersonly=True)
    if headers.defects:
        raise ValueError('Python distribution metadata has malformed headers')

    def values(key):
        rows = [re.sub(r'\r?\n[ \t]+', ' ', str(value)).strip() for value in headers.get_all(key, [])]
        if len(rows) > 256 or any(len(value) > 8192 or re.search(r'[\x00-\x1f\x7f]', value) for value in rows):
            raise ValueError('Python distribution metadata header limits exceeded')
        return rows

    result = {}
    for field, key in (('name', 'Name'), ('version', 'Version'), ('requires_python', 'Requires-Python'),
                       ('metadata_version', 'Metadata-Version')):
        rows = values(key)
        if len(rows) > 1 or field in {'name', 'version', 'metadata_version'} and not rows:
            raise ValueError('Python distribution metadata has a missing or repeated identity header')
        result[field] = rows[0] if rows else None
    result['name'] = python_name(result['name'])
    if (not re.fullmatch(r'[A-Za-z0-9.!+_-]{1,128}', result['version'])
            or not re.fullmatch(r'[12]\.[0-9]+', result['metadata_version'])):
        raise ValueError('unsupported Python distribution metadata identity or format')
    result['requires_dist'] = values('Requires-Dist')
    result['provides_extra'] = sorted({python_name(value) for value in values('Provides-Extra')})
    result['dynamic'] = values('Dynamic')
    return result


def python_wheel_metadata(environment: dict, budget: Budget, *, version_parser=None) -> tuple[dict, dict]:
    """Inspect a digest-bound wheel in memory, without extraction or imports."""
    limit = environment.get('maximum_bytes', MAX_COMPRESSED)
    if type(limit) is not int or not 0 < limit <= MAX_COMPRESSED:
        raise ValueError('invalid Python wheel compressed byte bound')
    blob = fetch(environment['url'], limit, operation_deadline=budget.deadline)
    budget.consume(expanded=len(blob), records=1)
    record = sha256_record(environment['url'], blob)
    if (record['sha256'] != environment['sha256'] or len(blob) < environment.get('minimum_bytes', 1)
            or environment.get('size', len(blob)) != len(blob)):
        raise ValueError('Python wheel differs from its selected SHA256 or byte bounds')
    # Bound the central-directory parser before ZipFile allocates its member
    # list. ZIP64 and multi-disk metadata need their own bounded adapter.
    end = blob.rfind(b'PK\x05\x06', max(0, len(blob) - 65557))
    if end < 0 or len(blob) - end < 22 or not blob.startswith(b'PK\x03\x04'):
        raise ValueError('Python wheel lacks an ordinary ZIP directory')
    _, disk, directory_disk, disk_count, count, size, offset, comment = struct.unpack_from('<4s4H2LH', blob, end)
    if (disk or directory_disk or disk_count != count or not 0 < count <= 8192
            or size > 8 * 1024**2 or offset + size != end or end + 22 + comment != len(blob)):
        raise ValueError('Python wheel ZIP directory exceeds its bounds or needs ZIP64 support')
    position, observed = offset, 0
    while position < end:
        budget.consume(records=1)
        observed += 1
        if observed > count or position + 46 > end or blob[position:position + 4] != b'PK\x01\x02':
            raise ValueError('Python wheel ZIP directory count or record is invalid')
        name, extra, note = struct.unpack_from('<3H', blob, position + 28)
        position += 46 + name + extra + note
    if position != end or observed != count:
        raise ValueError('Python wheel ZIP directory lengths do not match its declaration')
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            members, names, expanded, metadata, wheel = archive.infolist(), set(), 0, None, None
            if len(members) != count:
                raise ValueError('Python wheel ZIP directory changed during parsing')
            for member in members:
                budget.consume(records=1)
                path = member.filename.rstrip('/') if member.is_dir() else member.filename
                expanded += member.file_size
                if (path in names or not path or path.startswith('/') or '\\' in path or '\x00' in path
                        or '..' in PurePosixPath(path).parts or '//' in path or '/./' in path
                        or path.endswith('/.') or member.file_size < 0 or expanded > MAX_EXPANDED
                        or member.flag_bits & 1 or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                    raise ValueError('Python wheel has unsafe, duplicate or unbounded ZIP members')
                names.add(path)
                parts = path.split('/')
                if len(parts) != 2 or not parts[0].endswith('.dist-info') or parts[1] not in {'METADATA', 'WHEEL'}:
                    continue
                if member.is_dir() or (member.external_attr >> 16) & 0o170000 not in {0, 0o100000}:
                    raise ValueError('Python wheel selected metadata is not regular file data')
                if member.file_size > 1024**2 or member.compress_size > 1024**2:
                    raise ValueError('Python wheel selected metadata exceeds one MiB')
                with archive.open(member) as stream:
                    data = stream.read(1024**2 + 1)
                budget.consume(expanded=len(data))
                if len(data) != member.file_size:
                    raise ValueError('Python wheel selected metadata length does not match')
                if parts[1] == 'METADATA':
                    if metadata is not None:
                        raise ValueError('Python wheel has more than one distribution metadata directory')
                    metadata = (parts[0], python_metadata(data), hashlib.sha256(data).hexdigest())
                else:
                    if wheel is not None:
                        raise ValueError('Python wheel has more than one WHEEL declaration')
                    wheel = (parts[0], BytesParser().parsebytes(data, headersonly=True))
    except (zipfile.BadZipFile, EOFError, OSError, zlib.error) as error:
        raise ValueError('Python wheel is not a readable bounded ZIP archive') from error
    if (metadata is None or wheel is None or metadata[0] != wheel[0]
            or metadata[1]['name'] != python_name(environment['name'])):
        raise ValueError('Python wheel metadata differs from its selected distribution identity')
    if metadata[1]['version'] != environment['version'] and (version_parser is None
            or version_parser(metadata[1]['version']) != version_parser(environment['version'])):
        raise ValueError('Python wheel metadata version differs from its selected distribution identity')
    headers = wheel[1]
    tags = headers.get_all('Tag', [])
    if (headers.defects or headers.get_all('Wheel-Version', []) != ['1.0']
            or headers.get_all('Root-Is-Purelib', []) not in [['true'], ['false']]
            or not 0 < len(tags) <= 128
            or any(not re.fullmatch(r'[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+', value) for value in tags)):
        raise ValueError('Python wheel format or compatibility tags need an explicit adapter')
    return dict(metadata[1], metadata_sha256=metadata[2], tags=sorted(tags),
                root_is_purelib=headers['Root-Is-Purelib'] == 'true'), record


def python_egg_requirements(blob: bytes) -> list[dict]:
    """Preserve legacy egg requirements and their extra/marker sections."""
    if len(blob) > 65536 or b'\0' in blob:
        raise ValueError('Python egg requirement data exceeds its bounds')
    result, extra, marker = [], None, None
    for line in blob.decode('utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if len(line) > 8192 or re.search(r'[\x00-\x1f\x7f]', line):
            raise ValueError('Python egg requirement has invalid bounds or controls')
        if line.startswith('['):
            if not line.endswith(']') or '[' in line[1:] or ']' in line[:-1]:
                raise ValueError('Python egg requirement has an invalid section')
            name, separator, condition = line[1:-1].partition(':')
            extra, marker = python_name(name) if name else None, condition.strip() if separator else None
            if not extra and not marker:
                raise ValueError('Python egg requirement has an empty section')
            continue
        if len(result) >= 256:
            raise ValueError('Python egg dependency count exceeds its bound')
        result.append({'requirement': line, 'extra': extra, 'marker': marker})
    return result


def debian_python_metadata(package: dict, budget: Budget, *, include_files: tuple = ()) -> tuple[list, dict, dict]:
    """Inspect selected Debian Python metadata; never extract or load its code."""
    if len(include_files) > 16 or any(not isinstance(path, str) or not re.fullmatch(
            r'usr/lib/[A-Za-z0-9_./+-]{1,255}', path) or '..' in PurePosixPath(path).parts for path in include_files):
        raise ValueError('invalid Debian selected source metadata path')
    blob = fetch(package['url'], MAX_COMPRESSED, operation_deadline=budget.deadline)
    record = sha256_record(package['url'], blob)
    budget.consume(expanded=len(blob), records=1)
    if record['sha256'] != package['sha256'] or record['size'] != package['size']:
        raise ValueError('selected Debian Python archive differs from its APT identity')
    if not blob.startswith(b'!<arch>\n'):
        raise ValueError('selected Debian Python archive is not an ar container')
    position, members = 8, {}
    while position < len(blob):
        budget.consume(records=1)
        if position + 60 > len(blob) or len(members) >= 8:
            raise ValueError('Debian archive header/count bound exceeded')
        header = blob[position:position + 60]
        name = header[:16].decode('ascii').strip().removesuffix('/')
        length = header[48:58].strip()
        if (header[-2:] != b'`\n' or not re.fullmatch(r'[a-z][a-z0-9.-]{0,31}', name)
                or name in members or not length.isdigit()):
            raise ValueError('Debian archive has an unsupported or duplicate member header')
        length = int(length)
        position += 60
        if position + length > len(blob):
            raise ValueError('Debian archive member exceeds the compressed byte bound')
        members[name] = memoryview(blob)[position:position + length]
        position += length
        if length % 2:
            if blob[position:position + 1] != b'\n':
                raise ValueError('Debian archive member has invalid padding')
            position += 1
    if members.get('debian-binary') != b'2.0\n':
        raise ValueError('unsupported Debian archive format version')
    data = [(name, value) for name, value in members.items() if name.startswith('data.tar')]
    if len(data) != 1:
        raise ValueError('Debian archive lacks one data archive')
    name, raw = data[0]
    raw = bytes(raw)
    if name == 'data.tar.xz':
        stream = io.BufferedReader(XZReader(raw))
    elif name == 'data.tar.gz':
        stream = gzip.GzipFile(fileobj=io.BytesIO(raw))
    elif name == 'data.tar.bz2':
        stream = bz2.BZ2File(io.BytesIO(raw))
    elif name == 'data.tar':
        stream = io.BytesIO(raw)
    else:
        raise ValueError('selected Debian Python data archive compression requires a bounded adapter')
    headers, extended, expanded, header_depth = 0, 0, 0, 0

    class ExpandedReader:
        def read(self, size):
            nonlocal expanded
            if not 0 <= size <= 1024**2:
                raise ValueError('unbounded Debian archive metadata read is prohibited')
            block = stream.read1(size) if hasattr(stream, 'read1') else stream.read(size)
            expanded += len(block)
            budget.consume(expanded=len(block))
            if expanded > MAX_EXPANDED:
                raise ValueError('Debian Python archive expanded byte limit exceeded')
            return block

    class BoundedTarInfo(tarfile.TarInfo):
        def _proc_member(self, archive):
            nonlocal headers, extended, header_depth
            headers += 1
            budget.consume(records=1)
            if (headers > 20000 or not 0 <= self.size <= MAX_EXPANDED
                    or self.type in {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE, tarfile.GNUTYPE_SPARSE}):
                raise ValueError('Debian archive header bound or supported metadata format exceeded')
            if self.type in {tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}:
                extended += self.size
                if self.size > 65536 or extended > 1024**2:
                    raise ValueError('Debian extended archive metadata exceeds its byte bound')
            if header_depth >= 16:
                raise ValueError('Debian extended archive header recursion exceeds its bound')
            header_depth += 1
            try:
                return super()._proc_member(archive)
            finally:
                header_depth -= 1

    distributions, legacy, files, selected_paths, declared, retained = [], {}, {}, set(), 0, 0
    pattern = re.compile(r'usr/lib/python3(?:\.[0-9]+)?/dist-packages/'
                         r'(?:[^/]+\.dist-info/METADATA|[^/]+\.egg-info(?:/(?:PKG-INFO|requires\.txt))?)')
    try:
        with stream, tarfile.open(fileobj=ExpandedReader(), mode='r|', tarinfo=BoundedTarInfo) as archive:
            for member in archive:
                budget.consume(records=1)
                declared += member.size
                path = member.name.removeprefix('./').rstrip('/') if member.isdir() else member.name.removeprefix('./')
                if path in {'', '.'} and member.isdir():
                    continue
                if (not path or path.startswith('/') or '\\' in path or '\x00' in path or '//' in path
                        or '/./' in path or path.endswith('/.') or '..' in PurePosixPath(path).parts
                        or declared > MAX_EXPANDED):
                    raise ValueError('Debian Python archive has unsafe paths or excessive declared bytes')
                metadata = pattern.fullmatch(path)
                if member.isdir() or not metadata and path not in include_files:
                    continue
                if (path in selected_paths or not member.isfile() or member.sparse is not None
                        or member.size > 1024**2 or len(selected_paths) >= 128):
                    raise ValueError('Debian selected metadata is duplicate, nonregular or oversized')
                selected_paths.add(path)
                reader = archive.extractfile(member)
                if reader is None:
                    raise ValueError('Debian selected metadata is unreadable')
                with reader:
                    content = reader.read(1024**2 + 1)
                retained += len(content)
                if len(content) != member.size or retained > 4 * 1024**2:
                    raise ValueError('Debian selected metadata exceeds its aggregate byte bound')
                if metadata and path.endswith('.egg-info/requires.txt'):
                    legacy[path.removesuffix('/requires.txt')] = {
                        'requirements': python_egg_requirements(content), 'sha256': hashlib.sha256(content).hexdigest()}
                elif metadata:
                    distributions.append(dict(python_metadata(content), path=path,
                        metadata_sha256=hashlib.sha256(content).hexdigest(),
                        apt_package={key: package[key] for key in ('package', 'version', 'repository', 'url', 'sha256')}))
                else:
                    files[path] = content
    except (tarfile.TarError, EOFError, OSError, zlib.error, lzma.LZMAError) as error:
        raise ValueError('Debian Python archive metadata is not a readable bounded tar stream') from error
    for distribution in distributions:
        directory = distribution['path'].removesuffix('/PKG-INFO')
        if directory in legacy:
            distribution['legacy_requires_txt'] = legacy.pop(directory)
    if legacy:
        raise ValueError('Debian Python egg requirements lack their owning package metadata')
    return distributions, record, files


def python_target_packages(apt: dict, budget: Budget) -> list[dict]:
    """Model the installed APT snapshot at the desktop late-install boundary."""
    phases = {name: rank for rank, name in enumerate(('base_system', 'base_upgrade', 'pre_pkgsel', 'pkgsel', 'late'))}
    contexts = {}
    for row in apt.get('packages', []):
        if row['type'] != 'deb':
            continue
        for use in row.get('uses', []):
            budget.consume(records=1)
            if (use.get('operation') != 'install' or use.get('download_only') or use.get('phase') not in phases):
                continue
            key = (use['context'], use['architecture'])
            snapshot = contexts.setdefault(key, {'context': key[0], 'architecture': key[1], 'profiles': set(), 'packages': {}})
            snapshot['profiles'].update(use.get('profiles', []))
            previous = snapshot['packages'].get(row['package'])
            rank = phases[use['phase']]
            if previous and rank == previous[0] and row['version'] != previous[1]['version']:
                raise ValueError('Python target package snapshot needs within-phase transaction ordering')
            if previous is None or rank > previous[0]:
                snapshot['packages'][row['package']] = (rank, row)
            if len(contexts) > 16384:
                raise ValueError('Python APT target context count exceeds its limit')
    result = []
    for snapshot in contexts.values():
        packages = snapshot['packages']
        if 'pipx' not in packages:
            continue
        result.append(dict(snapshot, profiles=sorted(snapshot['profiles']),
                           packages={name: row for name, (_, row) in packages.items()}))
    return sorted(result, key=lambda row: (row['context'], row['architecture']))


def python_packaging() -> dict:
    """Load a manual developer dependency, without installing or probing tools."""
    try:
        import packaging
        from packaging.requirements import Requirement
        from packaging.specifiers import SpecifierSet
        from packaging.tags import compatible_tags, cpython_tags, parse_tag
        from packaging.utils import parse_wheel_filename
        from packaging.version import Version
    except ImportError as error:
        raise ValueError('manual Python dependency resolution requires PyPA packaging >= 23.2') from error
    if Version(packaging.__version__) < Version('23.2'):
        raise ValueError('manual Python dependency resolution requires PyPA packaging >= 23.2')
    return {'Requirement': Requirement, 'SpecifierSet': SpecifierSet, 'Version': Version,
            'compatible_tags': compatible_tags, 'cpython_tags': cpython_tags, 'parse_tag': parse_tag,
            'parse_wheel_filename': parse_wheel_filename, 'version': packaging.__version__}


def python_target_environment(target: dict, parsers: dict) -> dict:
    packages = target['packages']
    defaults, libc = packages.get('python3'), packages.get('libc6')
    if defaults is None or libc is None:
        raise ValueError('Python target lacks selected python3 defaults or libc6 metadata')
    names = set(re.findall(r'(?:^|[,|])\s*(python3\.[0-9]+)(?=[:\s,(]|$)', defaults.get('depends', '')))
    if len(names) != 1:
        raise ValueError('Python defaults do not select one CPython interpreter package')
    name = next(iter(names))
    interpreter = packages.get(name)
    if interpreter is None:
        raise ValueError('Python defaults interpreter is absent from the selected APT snapshot')
    match = re.fullmatch(r'(?:[0-9]+:)?([0-9]+\.[0-9]+\.[0-9]+)(~(?:a|b|rc)[0-9]+)?'
                         r'(?:\+[A-Za-z0-9.]+)?-[A-Za-z0-9.+~]+', interpreter['version'])
    glibc = re.match(r'(?:[0-9]+:)?([0-9]+)\.([0-9]+)(?:[.-]|$)', libc['version'])
    if match is None or glibc is None or int(glibc[1]) != 2:
        raise ValueError('selected CPython/glibc package version requires an explicit target adapter')
    full = match[1] + (match[2].removeprefix('~') if match[2] else '')
    parsed = parsers['Version'](full)
    if parsed.is_prerelease:
        raise ValueError('selected prerelease CPython needs a reviewed pip Requires-Python target adapter')
    minor = parsed.release[:2]
    if name != 'python' + '.'.join(map(str, minor)) or minor[0] != 3 or not 8 <= minor[1] <= 99:
        raise ValueError('selected CPython defaults and interpreter versions disagree')
    architecture = target['architecture']
    if architecture not in {'amd64', 'arm64'}:
        raise ValueError('unsupported Python target architecture')
    machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}[architecture]
    platforms = []
    floor = 4 if architecture == 'amd64' else 16
    if not floor < int(glibc[2]) <= 100:
        raise ValueError('selected glibc version exceeds supported manylinux platform bounds')
    for version in range(int(glibc[2]), floor, -1):
        platforms.append('manylinux_2_' + str(version) + '_' + machine)
        alias = {17: 'manylinux2014', 12: 'manylinux2010', 5: 'manylinux1'}.get(version)
        if alias and (architecture == 'amd64' or version == 17):
            platforms.append(alias + '_' + machine)
    platforms.append('linux_' + machine)
    abi = 'cp' + ''.join(map(str, minor))
    tags = list(parsers['cpython_tags'](python_version=minor, abis=[abi], platforms=platforms))
    tags.extend(parsers['compatible_tags'](python_version=minor, interpreter=abi, platforms=platforms))
    return {'markers': {'implementation_name': 'cpython', 'implementation_version': full, 'os_name': 'posix',
                        'platform_machine': machine, 'platform_system': 'Linux', 'sys_platform': 'linux',
                        'python_full_version': full, 'python_version': '.'.join(map(str, minor)),
                        'platform_python_implementation': 'CPython'},
            'tags': {tag: rank for rank, tag in reversed(list(enumerate(tags)))},
            'python': full, 'glibc': '.'.join(glibc.groups()),
            'packages': {key: {field: row[field] for field in ('package', 'version', 'repository', 'url', 'sha256')}
                         for key, row in (('defaults', defaults), ('interpreter', interpreter), ('libc', libc))}}


def python_marker_matches(marker, environment: dict, extras: set) -> bool:
    if marker is None:
        return True
    expression = str(marker)
    # Inspect only variable names outside parsed quoted literals. Supplying all
    # standard fields prevents the parser's host defaults from contributing a
    # value. Unknown target kernel/release fields are rejected when referenced.
    unquoted = re.sub(r'''(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')''', '', expression)
    used = set(re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', unquoted)) - {'and', 'or', 'in', 'not'}
    if used - set(environment) - {'extra'}:
        raise ValueError('Python requirement marker needs unavailable target environment fields')
    standard = {'implementation_name', 'implementation_version', 'os_name', 'platform_machine', 'platform_release',
                'platform_system', 'platform_version', 'python_full_version', 'platform_python_implementation',
                'python_version', 'sys_platform'}
    values = {key: environment.get(key, '') for key in standard}
    return any(marker.evaluate(environment=dict(values, extra=extra)) for extra in sorted(extras | {''}))


def python_requirements(metadata: dict, environment: dict, extras: set, parsers: dict) -> list:
    declarations = [{'requirement': value, 'extra': None, 'marker': None} for value in metadata['requires_dist']]
    if not declarations:
        declarations = metadata.get('legacy_requires_txt', {}).get('requirements', [])
    result = []
    for entry in declarations:
        if entry['extra'] is not None and entry['extra'] not in extras:
            continue
        value = entry['requirement']
        if value.count('(') > 32 or value.count('[') > 32:
            raise ValueError('Python requirement parser nesting bound exceeded')
        requirement = parsers['Requirement'](value)
        if requirement.url is not None:
            raise ValueError('Python direct-URL requirements need an explicit download adapter')
        if entry['marker']:
            section = parsers['Requirement']('section; ' + entry['marker'])
            if not python_marker_matches(section.marker, environment, extras):
                continue
        if python_marker_matches(requirement.marker, environment, extras):
            result.append(requirement)
    return result


def python_wheel_graph(root: dict, system: list, environment: dict, selection: dict,
                       budget: Budget, parsers: dict, cache: dict, evidence, retain) -> dict:
    """Resolve a checked single-version graph, retaining ordering uncertainty.

    Satisfied system distributions stay installed. A newly discovered constraint
    that invalidates an earlier choice requires backtracking; no transitive
    archive from that provisional graph is promoted into the download catalog.
    """
    Version, SpecifierSet = parsers['Version'], parsers['SpecifierSet']
    by_name = {}
    for row in system:
        by_name.setdefault(row['name'], []).append(row)
    chosen, constraints, edges, problems, skipped_extras, visited = {}, {}, [], [], [], set()
    root_extras = set()
    todo = deque([(root, set())])
    archives = {}

    def compatible(specifier):
        if not isinstance(specifier, str) or len(specifier) > 8192 or specifier.count(',') > 128:
            raise ValueError('Python version constraint exceeds its parser bounds')
        return not specifier or SpecifierSet(specifier).contains(environment['python'], prereleases=True)

    def target_tags(value):
        fields = value.split('-')
        if len(fields) != 3 or len(value) > 512:
            raise ValueError('Python wheel compatibility tag exceeds its bounds')
        product = 1
        for field in fields:
            product *= len(field.split('.'))
        if product > 128:
            raise ValueError('Python compressed wheel tag expansion exceeds its bound')
        return parsers['parse_tag'](value)

    def candidate(name, requirement):
        key = (name, str(requirement), environment['python'], environment['glibc'], selection['architecture'])
        if key in cache:
            cached = cache[key]
            return (cached[0], dict(cached[1], selection=[selection])) if cached is not None else None
        if len(cache) >= MAX_PROTOCOL_FILES:
            raise ValueError('Python candidate metadata cache exceeds its bounds')
        url = 'https://pypi.org/pypi/' + quote(name, safe='') + '/json'
        blob = fetch(url, 32 * 1024**2, operation_deadline=budget.deadline)
        budget.consume(expanded=len(blob), records=1)
        evidence(sha256_record(url, blob))
        project = json_object(blob)
        releases = project.get('releases')
        if not isinstance(releases, dict) or len(releases) > 50000:
            raise ValueError('Python project release metadata exceeds its bounds')
        candidates, files = [], 0
        allow_yanked = any(item.operator in {'==', '==='} and '*' not in item.version for item in requirement)
        for version, rows in releases.items():
            budget.consume(records=1)
            if not isinstance(rows, list):
                raise ValueError('Python release file metadata is not a list')
            files += len(rows)
            if files > 50000:
                raise ValueError('Python project file count exceeds its bounds')
            try:
                order = Version(version)
            except ValueError:
                continue  # pip ignores historical non-PEP-440 index versions.
            if not requirement.contains(order, prereleases=True):
                continue
            for row in rows:
                budget.consume(records=1)
                if not isinstance(row, dict):
                    raise ValueError('Python release file metadata is not an object')
                if row.get('packagetype') != 'bdist_wheel' or row.get('yanked') and not allow_yanked:
                    continue
                filename = row.get('filename')
                if not isinstance(filename, str) or not 0 < len(filename) <= 512:
                    raise ValueError('Python wheel filename exceeds its bounds')
                fields = filename.removesuffix('.whl').rsplit('-', 3)
                if len(fields) != 4:
                    raise ValueError('Python wheel filename lacks its compatibility fields')
                target_tags('-'.join(fields[-3:]))
                wheel_name, wheel_version, build, tags = parsers['parse_wheel_filename'](filename)
                if python_name(wheel_name) != name or wheel_version != order:
                    raise ValueError('Python index wheel identity differs from its release metadata')
                ranks = [environment['tags'][tag] for tag in tags if tag in environment['tags']]
                if not ranks or not compatible(row.get('requires_python') or ''):
                    continue
                path = urlsplit(public_url(row.get('url', '')))
                digests = row.get('digests')
                if not isinstance(digests, dict):
                    raise ValueError('Python wheel index lacks content digest metadata')
                checksum, size = digests.get('sha256'), row.get('size')
                if (path.hostname != 'files.pythonhosted.org' or path.query or path.fragment
                        or unquote(path.path.rsplit('/', 1)[-1]) != filename
                        or not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum)
                        or type(size) is not int or not 0 < size <= MAX_COMPRESSED):
                    raise ValueError('Python selected wheel lacks a public immutable archive identity')
                candidates.append((order, -min(ranks), build, row))
        allowed = set(requirement.filter({row[0] for row in candidates}))
        candidates = [row for row in candidates if row[0] in allowed]
        candidates.sort(key=lambda row: (row[0], row[1], row[2], row[3]['filename']), reverse=True)
        if len(candidates) > 1 and candidates[0][:3] == candidates[1][:3]:
            raise ValueError('Python equal-rank wheel choice requires pip index link ordering evidence')
        for attempt, (_, _, _, row) in enumerate(candidates):
            if attempt >= 64:
                raise ValueError('Python candidate archive inspection count exceeds its bounds')
            metadata, record = python_wheel_metadata({'name': name,
                'version': str(parsers['parse_wheel_filename'](row['filename'])[1]),
                'url': row['url'], 'sha256': row['digests']['sha256'], 'size': row['size']}, budget, version_parser=Version)
            evidence(record)
            if not compatible(metadata['requires_python'] or ''):
                continue
            actual_tags = set()
            for value in metadata['tags']:
                actual_tags.update(target_tags(value))
                if len(actual_tags) > 4096:
                    raise ValueError('Python wheel aggregate compatibility tags exceed their bounds')
            if actual_tags != set(parsers['parse_wheel_filename'](row['filename'])[3]):
                raise ValueError('Python wheel WHEEL tags differ from its index filename')
            archive = dict(record, package=name, version=metadata['version'], filename=row['filename'],
                           architecture=selection['architecture'], component='python_dependency',
                           selection=[selection], yanked=bool(row.get('yanked')))
            result = (metadata, archive)
            retain([metadata, archive])
            cache[key] = result
            return result
        cache[key] = None
        return None

    while todo:
        budget.consume(records=1)
        if len(todo) + len(chosen) > MAX_PROTOCOL_FILES or len(edges) > 16384:
            raise ValueError('Python dependency traversal exceeds its package/edge bounds')
        parent, extras = todo.popleft()
        visit = (parent['name'], parent['version'], tuple(sorted(extras)))
        if visit in visited:
            continue
        if len(visited) >= MAX_PROTOCOL_FILES:
            raise ValueError('Python dependency traversal visit count exceeds its bounds')
        visited.add(visit)
        if not compatible(parent.get('requires_python') or ''):
            raise ValueError('selected Python distribution does not support the target interpreter')
        for requirement in python_requirements(parent, environment['markers'], extras, parsers):
            if len(edges) + len(problems) + len(skipped_extras) >= 16384 or len(requirement.extras) > 128:
                raise ValueError('Python dependency edge or extra count exceeds its bounds')
            name = python_name(requirement.name)
            declarations = constraints.setdefault(name, [])
            specifier = str(requirement.specifier)
            if len(declarations) >= 256 and specifier not in declarations:
                raise ValueError('Python combined dependency constraint count exceeds its bounds')
            if specifier not in declarations:
                declarations.append(specifier)
            combined = SpecifierSet(','.join(value for value in declarations if value))
            edge = {'from': parent['name'] + '==' + parent['version'], 'requirement': str(requirement), 'name': name}
            retain(edge)
            if name == root['name']:
                if not combined.contains(Version(root['version']), prereleases=True):
                    problems.append(dict(edge, reason='local_root_version_conflicts_with_dependency'))
                else:
                    root_extras.update({python_name(value) for value in requirement.extras} & set(root['provides_extra']))
                    edges.append(dict(edge, version=root['version'], origin='local_root_wheel'))
                    todo.append((root, set(root_extras)))
                continue
            current = chosen.get(name)
            if current and not combined.contains(Version(current['metadata']['version']), prereleases=True):
                problems.append(dict(edge, reason='requires_python_dependency_backtracking',
                                     selected_version=current['metadata']['version']))
                continue
            if current is None:
                installed = by_name.get(name, [])
                if len(installed) > 1:
                    problems.append(dict(edge, reason='multiple_system_distribution_copies_require_target_path_order'))
                    continue
                if installed and combined.contains(Version(installed[0]['version']), prereleases=True):
                    current = {'metadata': installed[0], 'origin': 'selected_APT_system_site_packages', 'extras': set()}
                else:
                    found = candidate(name, combined)
                    if found is None:
                        problems.append(dict(edge, reason='no_compatible_binary_wheel_for_target'))
                        continue
                    metadata, archive = found
                    current = {'metadata': metadata, 'origin': 'PyPI_wheel', 'extras': set()}
                    archives[archive['url']] = archive
                chosen[name] = current
            requested = {python_name(value) for value in requirement.extras}
            supported = set(current['metadata']['provides_extra'])
            for extra in sorted(requested - supported):
                if len(edges) + len(problems) + len(skipped_extras) >= 16384:
                    raise ValueError('Python dependency edge or extra count exceeds its bounds')
                skipped_extras.append(dict(edge, extra=extra, reason='extra_not_provided_by_selected_distribution'))
            current['extras'].update(requested & supported)
            edges.append(dict(edge, version=current['metadata']['version'], origin=current['origin']))
            todo.append((current['metadata'], set(current['extras'])))
    return {'status': 'requires_python_dependency_resolution' if problems else 'resolved',
            'archives': [] if problems else sorted(archives.values(), key=lambda row: row['url']),
            'graph': {'selection': selection, 'root': {'name': root['name'], 'version': root['version']},
                      'packages': [dict(row['metadata'], origin=row['origin'], extras=sorted(row['extras']))
                                   for _, row in sorted(chosen.items())],
                      'edges': edges, 'omitted_extras': skipped_extras, 'unresolved': problems}}


def python_downloads(recipe: dict, budget: Budget, apt: dict) -> dict:
    """Bind local wheel metadata before resolving target-specific dependencies."""
    environments = recipe['environments']
    if not isinstance(environments, list) or not 0 < len(environments) <= 128:
        raise ValueError('Python wheel environment count exceeds its bounds')
    archives, evidence, graphs, unresolved, retained = [], {}, [], [], 0
    package_metadata, distributions, pipx_protocols, candidate_cache = {}, {}, {}, {}
    parsers = python_packaging()
    targets = python_target_packages(apt, budget)

    def retain(value):
        nonlocal retained
        retained += len(json.dumps(value, allow_nan=False).encode('utf-8'))
        if retained > 32 * 1024**2:
            raise ValueError('Python retained protocol metadata exceeds its byte limit')

    def add_evidence(record):
        previous = evidence.get(record['url'])
        if previous is not None and previous != record:
            raise ValueError('Python selected archive changed within one acquisition')
        if previous is None:
            retain(record)
            evidence[record['url']] = record

    for environment in environments:
        metadata, record = python_wheel_metadata(environment, budget, version_parser=parsers['Version'])
        add_evidence(record)
        selection = dict(recipe['selection'], profiles=environment['profiles'])
        archive = dict(record, package=metadata['name'], version=metadata['version'],
                       component='local_root_wheel', architecture='all', selection=[selection])
        retain(archive)
        archives.append(archive)
        applicable = [row for row in targets if row['architecture'] in recipe['architectures']
                      and (not row['profiles'] or set(row['profiles']).intersection(environment['profiles']))]
        models = []
        for target in applicable:
            identifiers = []
            for name, package in sorted(target['packages'].items()):
                # Debian Python packages declare interpreter/library runtime
                # dependencies. Include Python applications as well as the
                # python3-* modules, and inspect their packaged metadata.
                if (not name.startswith(('python3', 'libpython3')) and name != 'pipx'
                        and not re.search(r'(?:^|[,|])\s*python3(?:[.-][a-z0-9]+)*(?=[:\s,(]|$)',
                                          package.get('depends', '') + ',' + package.get('pre_depends', ''))):
                    continue
                url = package['url']
                if url not in package_metadata:
                    if len(package_metadata) >= 512:
                        raise ValueError('Python selected Debian archive count exceeds its limit')
                    prefix = 'usr/lib/python3/dist-packages/pipx/'
                    requested_sources = tuple(prefix + path for path in PIPX_PROTOCOL_SOURCES) if name == 'pipx' else ()
                    rows, acquired, source_files = debian_python_metadata(package, budget, include_files=requested_sources)
                    add_evidence(acquired)
                    if name == 'pipx':
                        digests = {path: hashlib.sha256(data).hexdigest() for path, data in source_files.items()}
                        reviewed = digests == {prefix + path: value for path, value in PIPX_PROTOCOL_SOURCES.items()}
                        protocol = {'apt_package': {key: package[key] for key in ('package', 'version', 'repository', 'url', 'sha256')},
                                    'source_files': digests,
                                    'status': 'reviewed_protocol_sources' if reviewed else 'requires_source_review'}
                        if reviewed:
                            protocol.update(backend_selection='visible_uv_else_pip_for_new_environment',
                                local_wheel_name_probe='install_without_dependencies_in_temporary_environment',
                                pip_backend_shared_requirement='pip >= 23.1',
                                shared_requirement_conditions=['pip_backend_and_invalid_shared_environment',
                                    'existing_pip_environment_and_shared_upgrade_required'],
                                uv_backend_shared_pip=False,
                                uv_backend_binary_policy='requires_uv_environment_and_configuration_review')
                        retain(protocol)
                        pipx_protocols[url] = protocol
                    ids = []
                    for row in rows:
                        identifier = 'python-system-' + hashlib.sha256((url + '\n' + row['path']).encode()).hexdigest()[:24]
                        candidate = dict(row, id=identifier)
                        retain(candidate)
                        distributions[identifier] = candidate
                        ids.append(identifier)
                    package_metadata[url] = {'sha256': package['sha256'], 'size': package['size'], 'ids': ids}
                cached = package_metadata[url]
                if cached['sha256'] != package['sha256'] or cached['size'] != package['size']:
                    raise ValueError('Python selected Debian archive has conflicting APT identities')
                identifiers.extend(cached['ids'])
            model = {'context': target['context'], 'architecture': target['architecture'],
                     'profiles': sorted(set(target['profiles']).intersection(environment['profiles']))
                                 if target['profiles'] else environment['profiles'],
                     'system_distribution_ids': sorted(set(identifiers)),
                     'pipx_protocol_url': target['packages']['pipx']['url']}
            pipx = pipx_protocols[model['pipx_protocol_url']]
            selected_distributions = [distributions[identifier] for identifier in model['system_distribution_ids']]
            visible_uv = bool({'uv', 'uvx', 'python3-uv'}.intersection(target['packages'])
                              or any(re.search(r'(?:^|,)\s*uv(?:\s|\(|,|$)', row.get('provides', ''))
                                     for row in target['packages'].values())
                              or any(row['name'] == 'uv' for row in selected_distributions)
                              or recipe.get('checkout_uv_entrypoints'))
            if pipx['status'] != 'reviewed_protocol_sources':
                model['unresolved'] = [{'reason': 'selected_pipx_protocol_requires_source_review'}]
            elif visible_uv:
                model['unresolved'] = [{'reason': 'requires_uv_backend_dependency_and_binary_policy_resolution'}]
            else:
                target_environment = python_target_environment(target, parsers)
                chosen_profiles = model['profiles']
                selected_for = dict(recipe['selection'], context=model['context'], architecture=model['architecture'],
                                    profiles=chosen_profiles, backend='pip', installation_state='fresh_pipx_environment')
                model.update(backend='pip', target_environment={key: value for key, value in target_environment.items() if key != 'tags'})
                stages = []
                # A clean pipx home creates a venv and seeds shared pip using
                # Debian ensurepip. Both the venv implementation for the
                # selected interpreter and the packaged pip wheel are required;
                # a pipx row alone does not establish either prerequisite.
                interpreter_name = target_environment['packages']['interpreter']['package']
                venv_candidates = ('python3-venv', interpreter_name + '-venv')
                missing_bootstrap = [name for name in ('python3-pip-whl',)
                                     if name not in target['packages']]
                if not any(name in target['packages'] for name in venv_candidates):
                    missing_bootstrap.append(' or '.join(venv_candidates))
                if missing_bootstrap:
                    model['unresolved'] = [{'reason': 'requires_selected_Debian_python_bootstrap_packages',
                                            'missing_packages': missing_bootstrap}]
                else:
                    bootstrap = {'name': 'pipx-shared-bootstrap', 'version': '0', 'requires_python': None,
                                 'requires_dist': [pipx['pip_backend_shared_requirement']], 'provides_extra': []}
                    for name, root_metadata, installed in [('pipx_shared_pip', bootstrap, []),
                                                           ('application_dependencies', metadata, selected_distributions)]:
                        stage_selection = dict(selected_for, stage=name)
                        try:
                            resolved = python_wheel_graph(root_metadata, installed, target_environment, stage_selection,
                                                          budget, parsers, candidate_cache, add_evidence, retain)
                        except ValueError as error:
                            if type(error).__module__.startswith('packaging.'):
                                raise ValueError('invalid public Python dependency metadata; parser=' + type(error).__name__) from error
                            raise
                        retain(resolved['graph'])
                        stages.append(dict(resolved['graph'], stage=name, status=resolved['status']))
                        for item in resolved['archives']:
                            retain(item)
                            archives.append(item)
                    model.update(stages=stages, unresolved=[issue for stage in stages for issue in stage['unresolved']])
            retain(model)
            models.append(model)
        graph = {'selection': selection, 'root': metadata, 'target_contexts': models}
        retain(graph)
        graphs.append(graph)
        issues = [dict(issue, selection={'context': model['context'], 'architecture': model['architecture'],
                                         'profiles': model['profiles']}) for model in models for issue in model.get('unresolved', [])]
        if not applicable:
            issues.append({'selection': selection, 'reason': 'requires_selected_python_target_packages'})
        retain(issues)
        unresolved.extend(issues)
    grouped = {}
    for archive in archives:
        key = (archive['url'], archive['architecture'])
        if key in grouped:
            previous = grouped[key]
            if any(previous[field] != archive[field] for field in ('sha256', 'size', 'package', 'version')):
                raise ValueError('Python archive identity conflicts across target contexts')
            for condition in archive['selection']:
                if condition not in previous['selection']:
                    retain(condition)
                    previous['selection'].append(condition)
        else:
            grouped[key] = dict(archive, selection=list(archive['selection']))
    return dict(recipe, status='requires_python_protocol_resolution' if unresolved else 'resolved',
                archives=[grouped[key] for key in sorted(grouped)],
                dependency_graphs=graphs, system_distributions=list(distributions.values()),
                pipx_protocols=list(pipx_protocols.values()),
                parser_library={'name': 'packaging', 'version': parsers['version']},
                protocol_evidence=list(evidence.values()), unresolved=unresolved,
                trust={'root_archive_consistency': 'configured_SHA256_pin',
                       'system_metadata_consistency': 'selected_APT_binary_SHA256_and_size',
                       'signature_verification': 'not_performed'})


def resolve_indirect(recipes: list, *, apt: dict | None = None) -> list:
    """Fetch metadata only; never execute a manager, installer or downloaded code."""
    if len(recipes) > 256:
        raise ValueError('indirect download protocol limit exceeded')
    result, budget, count, serialized = [], Budget(), 0, 0
    for recipe in recipes:
        budget.consume()
        try:
            if recipe['status'] == 'resolved_literal':
                resolved = recipe
            elif recipe['kind'] == 'rustup_distribution':
                resolved = rustup_downloads(recipe, budget)
            elif recipe['kind'] == 'packer_plugin' and recipe.get('checksums_url'):
                resolved = packer_downloads(recipe, budget)
            elif recipe['kind'] == 'discord_distribution':
                resolved = discord_downloads(recipe, budget)
            elif recipe['kind'] == 'codex_standalone_distribution':
                resolved = codex_standalone_downloads(recipe, budget)
            elif recipe['kind'] == 'crowdsec_hub':
                resolved = crowdsec_downloads(recipe, budget, apt or {})
            elif recipe['kind'] == 'npm_dependencies':
                resolved = npm_downloads(recipe, budget)
            elif recipe['kind'] == 'python_dependencies':
                resolved = python_downloads(recipe, budget, apt or {})
            else:
                resolved = dict(recipe, status='requires_protocol_resolution')
        except (OSError, URLError) as error:
            # Do not print a server-controlled HTTP reason or signed redirect
            # URL. Preserve the original exception as the diagnostic cause.
            status = str(error.code) if isinstance(error, HTTPError) else 'unavailable'
            raise ValueError('indirect metadata transfer failed; protocol=' + recipe['kind']
                             + '; error=' + type(error).__name__ + '; http_status=' + status) from error
        count += (len(resolved.get('archives', [])) + len(resolved.get('metadata_files', []))
                  + len(resolved.get('embedded_files', [])))
        serialized += len(json.dumps(resolved).encode('utf-8'))
        if count > MAX_PROTOCOL_FILES or serialized > 32 * 1024**2:
            raise ValueError('indirect download result exceeds aggregate file/byte limits')
        result.append(resolved)
    return result


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
        elif line.startswith('#'):
            continue
        elif line.startswith((' ', '\t')) and previous:
            fields[previous] += '\n' + line[1:]
        elif ':' in line:
            key, value = line.split(':', 1)
            if key in fields or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*', key):
                raise ValueError('APT metadata repeats or malforms a field')
            previous = key
            fields[key] = value.strip()
        else:
            raise ValueError('APT metadata contains an invalid field line')


def filename_url(base: str, filename: str) -> str:
    filename = filename.removeprefix('./')
    path = PurePosixPath(filename)
    if (path.is_absolute() or '..' in path.parts or not path.parts
            or not re.fullmatch(r'[A-Za-z0-9_.+~:/%-]+', str(path)) or ':' in str(path)
            or '%' in str(path) or path.as_posix() != filename):
        raise ValueError('unsafe package filename in index')
    return base.rstrip('/') + '/' + str(path)


def release_metadata(repo: dict, budget: Budget | None = None, release_url: str | None = None) -> tuple[dict, dict]:
    release_url = release_url or repo['release_url']
    raw = fetch(release_url, 8 * 1024**2,
                operation_deadline=budget.deadline if budget else None)
    records = list(stanzas(io.BytesIO(raw)))
    if len(records) != 1:
        raise ValueError('invalid Release metadata')
    release = records[0]
    checksums = {}
    for line in release.get('SHA256', '').splitlines():
        fields = line.split()
        if not fields:
            continue
        if (len(fields) != 3 or not re.fullmatch('[0-9a-f]{64}', fields[0])
                or not fields[1].isdecimal() or fields[2] in checksums):
            raise ValueError('invalid or duplicate Release SHA-256 index entry')
        filename_url(repo['url'], fields[2])
        checksums[fields[2]] = (fields[0], int(fields[1]))
    if not checksums:
        raise ValueError('Release metadata has no SHA-256 index entries')
    details = {key: release[key] for key in ('Origin', 'Label', 'Suite', 'Codename', 'Version', 'Date',
                                            'Valid-Until', 'Architectures', 'Components', 'NotAutomatic',
                                            'ButAutomaticUpgrades') if key in release}
    details['url'] = release_url
    details['sha256'] = hashlib.sha256(raw).hexdigest()
    details['signature_verification'] = 'not_performed'
    return details, checksums


class XZReader(io.RawIOBase):
    """Bound the decoder dictionary AND each produced chunk before parsing."""
    def __init__(self, raw: bytes):
        super().__init__()
        self.raw = raw
        self.offset = 0
        self.decoder = lzma.LZMADecompressor(memlimit=128 * 1024**2)

    def readable(self):
        return True

    def readinto(self, buffer):
        if not len(buffer):
            return 0
        while True:
            if self.decoder.eof:
                padding = self.decoder.unused_data + self.raw[self.offset:]
                if len(padding) % 4 or padding.strip(b'\0'):
                    raise ValueError('trailing data in XZ package index')
                return 0
            block = b''
            if self.decoder.needs_input:
                block = self.raw[self.offset:self.offset + 65536]
                self.offset += len(block)
                if not block:
                    raise EOFError('truncated XZ package index')
            output = self.decoder.decompress(block, max_length=len(buffer))
            if output:
                buffer[:len(output)] = output
                return len(output)


def relationship_field(item: dict, name: str) -> str:
    value = item.get(name, '')
    if len(value) > 65536 or not re.fullmatch(r'[A-Za-z0-9+.:<>=~_(),|* \n\r\t-]*', value):
        raise ValueError('unsupported or oversized binary package relationship field')
    return ' '.join(value.split())


def acquire_index(repo: dict, index: dict, release: dict, sums: dict, target: Path, budget: Budget) -> dict:
    release_url = index.get('release_url', repo['release_url'])
    prefix = release_url.rsplit('/', 1)[0] + '/'
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
    raw = fetch(url, MAX_COMPRESSED, operation_deadline=budget.deadline)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('package index does not match Release SHA-256/size')
    buffer = io.BytesIO(raw)
    stream = (io.BufferedReader(XZReader(raw)) if selected.endswith('.xz') else
              gzip.GzipFile(fileobj=buffer) if selected.endswith('.gz') else
              bz2.BZ2File(buffer) if selected.endswith('.bz2') else buffer)
    count = 0
    with stream, target.open('x', encoding='utf-8') as output:
        for item in stanzas(stream, budget):
            count += 1
            budget.consume(records=1)
            if count > MAX_PACKAGES:
                raise ValueError('APT index record limit exceeded')
            if index['type'] == 'source':
                row = source_record(repo, item, url)
                output.write(json.dumps(row, separators=(',', ':')) + '\n')
                continue
            name, version, architecture = item.get('Package'), item.get('Version'), item.get('Architecture')
            filename = item.get('Filename')
            if not name or not version or not architecture or not filename:
                raise ValueError('package index record is missing its identity or filename')
            if (not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', name)
                    or not re.fullmatch(r'[A-Za-z0-9.+:~_-]+', version)
                    or not re.fullmatch(r'[a-f0-9]{64}', item.get('SHA256', ''))
                    or not 0 < int(item.get('Size', '0')) <= 64 * 1024**3):
                raise ValueError('package index record has an invalid identity, size or SHA-256')
            if architecture not in {index['architecture'], 'all'}:
                continue
            row = {'package': name, 'version': version, 'architecture': architecture, 'type': index['type'],
                   'repository': repo['id'], 'url': filename_url(repo['url'], filename), 'filename': filename,
                   'size': int(item['Size']), 'sha256': item.get('SHA256'), 'source': item.get('Source', name),
                   'depends': relationship_field(item, 'Depends'), 'pre_depends': relationship_field(item, 'Pre-Depends'),
                   'provides': relationship_field(item, 'Provides'), 'priority': item.get('Priority'),
                   'essential': item.get('Essential') == 'yes', 'index_url': url,
                   'indexed_architecture': index['architecture'],
                   'component': index.get('component'), 'multi_arch': item.get('Multi-Arch'),
                   'conflicts': relationship_field(item, 'Conflicts'), 'breaks': relationship_field(item, 'Breaks'),
                   'recommends': relationship_field(item, 'Recommends'),
                   'suggests': relationship_field(item, 'Suggests')}
            output.write(json.dumps(row, separators=(',', ':')) + '\n')
    return dict(record, status='acquired', url=url, sha256=expected, compressed_bytes=size, records=count,
                release_sha256=release['sha256'])


def source_record(repo: dict, item: dict, index_url: str) -> dict:
    """Use Directory and every SHA-256 file, including .dsc and orig tarballs."""
    name, version, directory = item.get('Package', ''), item.get('Version', ''), item.get('Directory', '').removeprefix('./')
    if (not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', name)
            or not re.fullmatch(r'[A-Za-z0-9.+:~_-]+', version) or not directory):
        raise ValueError('source index lacks a valid name, version or Directory')
    filename_url(repo['url'], directory)
    files, names = [], set()
    for line in item.get('Checksums-Sha256', '').splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError('invalid source SHA-256 record')
        checksum, size, filename = parts
        if (not re.fullmatch(r'[0-9a-f]{64}', checksum) or not size.isdecimal()
                or not 0 < int(size) <= 64 * 1024**3 or '/' in filename or filename in names):
            raise ValueError('invalid source file identity, size or SHA-256')
        names.add(filename)
        if len(names) > MAX_SOURCE_FILES:
            raise ValueError('source package file limit exceeded')
        files.append({'filename': directory.rstrip('/') + '/' + filename,
                      'url': filename_url(repo['url'], directory.rstrip('/') + '/' + filename),
                      'size': int(size), 'sha256': checksum})
    if not files or not any(row['filename'].endswith('.dsc') for row in files):
        raise ValueError('source index record lacks a SHA-256 file list or .dsc')
    return {'package': name, 'version': version, 'type': 'source', 'repository': repo['id'],
            'directory': directory, 'index_url': index_url,
            'files': sorted(files, key=lambda row: row['filename'])}


def attach_sources(database: sqlite3.Connection, packages: list, indexes: list) -> list:
    """Bind source name AND source version in the selected binary repository."""
    selected = {}
    identity = re.compile(r'([a-z0-9][a-z0-9+.-]*)(?:\s+\(([A-Za-z0-9.+:~_-]+)\))?\Z')
    for package in packages:
        match = identity.fullmatch(package.get('source') or package['package'])
        if not match:
            raise ValueError('selected binary has an invalid Source field')
        name, version = match[1], match[2] or package['version']
        key = (package['repository'], name, version)
        records, index_urls, copies = {}, set(), 0
        for (encoded,) in database.execute('SELECT data FROM sources WHERE repository=? AND name=? AND version=?', key):
            copies += 1
            if copies > MAX_SOURCE_FILES:
                raise ValueError('selected source duplicate-record limit exceeded')
            record = json.loads(encoded)
            index_urls.add(record.pop('index_url'))
            records[json.dumps(record, sort_keys=True)] = record
            if len(records) > 1:
                raise ValueError('selected source identity has conflicting archive records')
        source_indexes = [row for row in indexes if row['repository'] == key[0] and row['type'] == 'source']
        if not records:
            package['source_package'] = {'name': name, 'version': version,
                'status': 'version_not_in_advertised_sources' if any(row['status'] == 'acquired' for row in source_indexes)
                          else 'source_index_not_advertised', 'repository': key[0]}
            continue
        record = next(iter(records.values()))
        identifier = 'source-' + hashlib.sha256(('\n'.join(key)).encode()).hexdigest()[:24]
        selected[identifier] = dict(record, id=identifier, index_urls=sorted(index_urls))
        package['source_package'] = {'id': identifier, 'name': name, 'version': version,
                                     'repository': key[0], 'status': 'available'}
    return sorted(selected.values(), key=lambda row: (row['package'], row['version'], row['repository']))


def refresh(root: Path, apt: dict, source: dict, resolver) -> dict:
    """Acquire in private scratch. Return data; never publish a second inventory.

    Repository indexes must be streamed to discover their actual Filenames and
    source versions. The temporary catalog is not the inventory: only rows
    reached from checkout requests under installer policy leave this function.
    """
    repositories = apt['repositories']
    indexes, releases, errors, jobs = [], {}, [], []
    budget = Budget()
    if len(repositories) > 256 or sum(len(repo['index_urls']) for repo in repositories) > MAX_INDEXES:
        raise ValueError('APT repository or index job limit exceeded')
    release_jobs = {}
    for repo in repositories:
        for index in repo['index_urls']:
            release_url = index.get('release_url', repo['release_url'])
            release_jobs.setdefault((repo['id'], release_url), repo)
    executor = ThreadPoolExecutor(max_workers=4)
    futures = {executor.submit(release_metadata, repo, budget, release_url): (repo, release_url)
               for (repo_id, release_url), repo in release_jobs.items()}
    try:
        for future in as_completed(futures, timeout=max(0.1, budget.deadline - time.monotonic())):
            budget.consume()
            repo, release_url = futures[future]
            acquired = False
            try:
                details, sums = future.result()
                acquired = True
                if release_url == repo['release_url']:
                    releases[repo['id']] = details
                for index in repo['index_urls']:
                    if index.get('release_url', repo['release_url']) != release_url:
                        continue
                    if (index['type'] != 'source' and details.get('Architectures')
                            and index['architecture'] not in details['Architectures'].split()):
                        continue
                    jobs.append((repo, index, details, sums))
            except (OSError, ValueError, URLError) as error:
                errors.append({'repository': repo['id'], 'release_url': release_url, 'stage': 'Release', 'error': type(error).__name__,
                               'http_status': error.code if isinstance(error, HTTPError) else None})
            print('inventory APT: Release ' + repo['id'] + ' ' + release_url +
                  (' acquired' if acquired else ' unavailable'), flush=True)
    except FuturesTimeoutError as error:
        raise ValueError('APT Release acquisition operation deadline exceeded; previous inventory retained') from error
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if errors:
        failed = ','.join(sorted({error['repository'] for error in errors}))
        raise ValueError('APT Release acquisition incomplete; previous inventory retained; repositories=' + failed)
    if len(jobs) > MAX_INDEXES:
        raise ValueError('APT index job limit exceeded')
    jobs.sort(key=lambda job: (job[0]['id'], job[1]['url'], job[1]['architecture'], job[1]['type']))
    with private_workspace(root) as (private, retain_workspace):
        executor = ThreadPoolExecutor(max_workers=4)
        futures = {executor.submit(acquire_index, repo, index, details, sums, private / f'{n}.jsonl', budget): (n, repo, index)
                   for n, (repo, index, details, sums) in enumerate(jobs)}
        try:
            for future in as_completed(futures, timeout=max(0.1, budget.deadline - time.monotonic())):
                budget.consume()
                n, repo, index = futures[future]
                try:
                    record = future.result()
                    indexes.append(record)
                except (OSError, ValueError, URLError, EOFError, lzma.LZMAError) as error:
                    errors.append({'repository': repo['id'], 'stage': 'index', 'architecture': index['architecture'],
                                   'type': index['type'], 'error': type(error).__name__,
                                   'http_status': error.code if isinstance(error, HTTPError) else None})
                    (private / f'{n}.jsonl').unlink(missing_ok=True)
                print(f'inventory APT: {len(indexes) + len(errors)}/{len(jobs)} indexes', flush=True)
        except FuturesTimeoutError as error:
            retain_workspace()
            raise ValueError('APT index acquisition operation deadline exceeded; previous inventory retained; scratch=' + private.name) from error
        except BaseException:
            retain_workspace()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if errors:
            failed = ','.join(sorted({error['repository'] for error in errors}))
            raise ValueError('APT index acquisition incomplete; previous inventory retained; repositories=' + failed)
        with closing(sqlite3.connect(private / 'indexes.sqlite')) as database:
            # All state is private checkout scratch, never host APT state.
            database.execute('PRAGMA temp_store=MEMORY')
            database.execute('PRAGMA max_page_count=524288')
            database.execute('CREATE TABLE packages (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, repository TEXT, architecture TEXT, priority TEXT, essential INTEGER, data TEXT)')
            database.execute('CREATE TABLE provides (name TEXT, version TEXT, package_id INTEGER)')
            database.execute('CREATE TABLE sources (repository TEXT, name TEXT, version TEXT, data TEXT)')
            count = 0
            for path in sorted(private.glob('*.jsonl')):
                with path.open(encoding='utf-8') as stream:
                    for line in stream:
                        budget.consume()
                        if len(line) > MAX_STANZA * 2:
                            raise ValueError('serialized APT row exceeds byte limit')
                        row = json.loads(line)
                        count += 1
                        if count > MAX_ROWS:
                            raise ValueError('aggregate APT record limit exceeded')
                        if row['type'] == 'source':
                            database.execute('INSERT INTO sources VALUES (?,?,?,?)',
                                             (row['repository'], row['package'], row['version'], line))
                            continue
                        cursor = database.execute('INSERT INTO packages (name,kind,repository,architecture,priority,essential,data) VALUES (?,?,?,?,?,?,?)',
                                                  (row['package'], row['type'], row['repository'], row['architecture'],
                                                   row['priority'], row['essential'], line))
                        for provided in row['provides'].split(','):
                            if not provided.strip():
                                continue
                            match = re.fullmatch(r'\s*([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9-]+)?(?:\s*\(=\s*([A-Za-z0-9.+:~_-]+)\))?\s*', provided)
                            if not match:
                                raise ValueError('invalid virtual package Provides field')
                            database.execute('INSERT INTO provides VALUES (?,?,?)', (match[1], match[2], cursor.lastrowid))
                path.unlink()
            database.execute('CREATE INDEX names ON packages (name,kind,architecture)')
            database.execute('CREATE INDEX virtuals ON provides (name)')
            database.execute('CREATE INDEX source_names ON sources (repository,name,version)')
            database.set_progress_handler(lambda: int(time.monotonic() >= budget.deadline), 10000)
            selected, unresolved = resolver(database, apt, releases)
            sources = attach_sources(database, selected, indexes)
    value = {'source': source, 'acquired': True,
             'trust': {'transport': 'HTTPS', 'index_consistency': 'Release_SHA256_and_size',
                       'signature_verification': 'not_performed'},
             'releases': releases,
             'indexes': sorted(indexes, key=lambda row: (row['repository'], row['url'], row['architecture'])),
             'packages': selected, 'source_packages': sources, 'unresolved': unresolved,
             'dependency_policy': ('phase-specific base and explicit requests plus selected Depends/Pre-Depends alternatives; '
                                   'Recommends/Suggests only for an explicit command override; '
                                   'download actions have no dependency closure; no host installed state')}
    print(f'inventory APT: selected {len(selected)} binary records and {len(sources)} source packages', flush=True)
    return value
