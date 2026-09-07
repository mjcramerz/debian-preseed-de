#!/usr/bin/env python3
"""Offline transport, source selection, cache and immutable snapshot tests.

HTTP and HTTPS fixtures bind only to loopback. Nothing partitions disks, starts
systemd units, installs packages, or contacts GitHub/TinyURL/the Internet.
"""
from __future__ import annotations
import collections
import contextlib
import gzip
import hashlib
import http.server
import io
import os
from pathlib import Path
import shlex
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import threading
import unittest
from process_fixture import stop_test_tree, wait_file
from urllib.parse import urlsplit, unquote

FORKY = Path(__file__).resolve().parents[1]
SOURCE = FORKY / 'scripts/common/source.sh'
ROOT = FORKY.parents[1]
ROLE = 'server' if 'REPOSITORY_ROLE="server"' in (FORKY / 'repo.env').read_text() else 'desktop'
RAW_PREFIX = '/owner/repository/refs/heads/mcr/main/d-i/forky'

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

class Endpoint:
    def __init__(self, root: Path, tls: ssl.SSLContext | None = None):
        self.root, self.counts = root, collections.Counter()
        self.redirects = {'/short': RAW_PREFIX + '/preseed.cfg?fixture=1',
                          '/chain/start': '../short',
                          '/relative': 'short'}
        endpoint = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def handle(self):
                # Certificate-rejection tests intentionally abort the connection.
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def do_GET(self):
                path = unquote(urlsplit(self.path).path)
                endpoint.counts[path] += 1
                if path in endpoint.redirects:
                    self.send_response(302)
                    self.send_header('Location', endpoint.redirects[path])
                    self.end_headers()
                    return
                if not path.startswith(RAW_PREFIX + '/'):
                    self.send_error(404)
                    return
                relative = path[len(RAW_PREFIX) + 1:]
                file = endpoint.root / relative
                if '..' in Path(relative).parts or not file.is_file():
                    self.send_error(404)
                    return
                data = file.read_bytes()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        if tls:
            self.server.socket = tls.wrap_socket(self.server.socket, server_side=True)
        self.url = ('https' if tls else 'http') + f'://127.0.0.1:{self.server.server_port}'
        self.base = self.url + RAW_PREFIX
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .03}, daemon=True)
        self.thread.start()
    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

class TransportFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='preseed-transport-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.env = {**os.environ, 'INSTALLER_RUNTIME_DIR': str(self.runtime),
                    'INSTALLER_CMDLINE': '', 'INSTALLER_FETCH_TIMEOUT': '3'}
        self.env.pop('INSTALLER_SOURCE_ROOT', None)
        # Context preparation now correctly applies selections. Never seed the
        # host database, and never inherit a live installer frontend in tests.
        for key in list(self.env):
            if key.startswith(('DEBCONF_', 'DEBIAN_')):
                self.env.pop(key)
        db = self.root / 'debconf.conf'
        db.write_text('Config: test_config\nTemplates: test_templates\n\n'
                      f'Name: test_config\nDriver: File\nMode: 600\nFilename: {self.root}/config.dat\n\n'
                      f'Name: test_templates\nDriver: File\nMode: 600\nFilename: {self.root}/templates.dat\n')
        self.env.update(DEBCONF_SYSTEMRC=str(db), DEBIAN_FRONTEND='noninteractive')
    def shell(self, script: str, *, env=None, timeout=25):
        return subprocess.run(['/bin/sh', '-eu', '-c', f'. {shlex.quote(str(SOURCE))}\n{script}'],
            text=True, capture_output=True, env={**self.env, **(env or {})}, timeout=timeout)
    def endpoint(self, root=FORKY, tls=None):
        endpoint = Endpoint(root, tls)
        self.addCleanup(endpoint.close)
        return endpoint

class TransportTests(TransportFixture):
    def test_raw_style_ref_path_is_not_truncated(self):
        web = self.endpoint()
        result = self.shell('source_resolve_seed', env={'INSTALLER_CMDLINE': f'url={web.base}/preseed.cfg'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), web.base)
    def test_shortener_and_relative_redirect_chain(self):
        web = self.endpoint()
        result = self.shell('source_resolve_seed', env={'INSTALLER_CMDLINE': f'preseed/url={web.url}/chain/start'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), web.base)
        self.assertEqual(web.counts['/short'], 1)
    def test_persisted_effective_url_wins_without_re_download(self):
        web = self.endpoint()
        env = {'INSTALLER_CMDLINE': f'url={web.url}/short'}
        first = self.shell('source_resolve_seed', env=env)
        second = self.shell('source_resolve_seed', env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(web.counts['/short'], 1)
    def test_file_and_preseed_file_aliases(self):
        for alias in ('file', 'preseed/file'):
            with self.subTest(alias=alias):
                shutil.rmtree(self.runtime, ignore_errors=True)
                result = self.shell('source_resolve_seed', env={'INSTALLER_CMDLINE': f'{alias}={FORKY}/preseed.cfg'})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), str(FORKY))
    def test_file_uri(self):
        result = self.shell('source_resolve_seed', env={'INSTALLER_CMDLINE': f'url=file://{FORKY}/preseed.cfg'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(FORKY))
    def test_conflicting_sources_fail_before_network(self):
        web = self.endpoint()
        for cmdline in (f'url={web.url}/short file={FORKY}/preseed.cfg',
                        f'url={web.url}/short preseed/url={web.url}/other'):
            with self.subTest(cmdline=cmdline):
                result = self.shell('source_resolve_seed', env={'INSTALLER_CMDLINE': cmdline})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('fatal:', result.stderr)
        self.assertEqual(sum(web.counts.values()), 0)
    def test_missing_source_and_missing_local_preseed_fail(self):
        for value in ('', 'file=/does/not/exist.cfg'):
            result = self.shell('source_resolve_seed', env={'INSTALLER_CMDLINE': value})
            self.assertNotEqual(result.returncode, 0)
    def test_url_and_relative_path_validation(self):
        for path in ('../secret', 'a/../secret', '/etc/passwd', 'a//b', 'a/./b', '$(id)', 'a b'):
            result = self.shell('source_validate_relative ' + shlex.quote(path))
            self.assertNotEqual(result.returncode, 0, path)
        for url in ('ftp://host/file', 'https://user:password@host/file', 'https://host/a b'):
            result = self.shell('source_validate_url ' + shlex.quote(url))
            self.assertNotEqual(result.returncode, 0, url)
    def test_exact_base_hash_prevents_sanitized_cache_collisions(self):
        result = self.shell('source_cache_root http://example.test/a/b; source_cache_root http://example.test/a_b')
        self.assertEqual(result.returncode, 0, result.stderr)
        first, second = result.stdout.splitlines()
        self.assertNotEqual(first, second)
        self.assertEqual(len(Path(first).name), 64)
    def test_library_adapters_share_one_get_and_accept_empty_profile(self):
        web = self.endpoint()
        p = shlex.quote
        script = f'''
. {p(str(FORKY / 'scripts/common/bootstrap.sh'))}
. {p(str(FORKY / 'scripts/common/lib.sh'))}
bootstrap_fetch_seed_file {p(web.base)} repo.env {p(str(self.root / 'a'))} 0600
installer_fetch_seed_path {p(web.base)} repo.env {p(str(self.root / 'b'))} 0600
installer_seed_path_exists {p(web.base)} repo.env
'''
        result = self.shell(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(web.counts[RAW_PREFIX + '/repo.env'], 1)
        profile = next((FORKY / 'classes/class-profile').glob('*.cfg')).relative_to(FORKY)
        result = self.shell(f'source_fetch {p(web.base)} {p(str(profile))} {p(str(self.root / "profile"))}')
        self.assertEqual(result.returncode, 0, result.stderr)
    def test_failed_http_fetch_preserves_existing_destination(self):
        web = self.endpoint()
        dest = self.root / 'output'
        dest.write_text('keep-me')
        result = self.shell(f'source_http_get {shlex.quote(web.base + "/missing")} {shlex.quote(str(dest))}')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(dest.read_text(), 'keep-me')
        self.assertFalse(list(self.root.glob('output.part.*')))
        self.assertTrue(Path(str(dest) + '.fetch-error').is_file())
        self.assertEqual(web.counts[RAW_PREFIX + '/missing'], 1)
    def test_local_symlink_escape_is_rejected(self):
        local = self.root / 'seed'
        local.mkdir()
        (local / 'escape').symlink_to('/etc/passwd')
        result = self.shell(f'source_transfer {shlex.quote(str(local))} escape {shlex.quote(str(self.root / "out"))}')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'out').exists())
    def test_https_downgrade_and_non_http_redirect_are_rejected(self):
        header = self.root / 'headers'
        for location in ('http://host/path', 'file:///etc/passwd'):
            header.write_text('  Location: ' + location + '\n')
            result = self.shell(f'source_effective_url https://host/seed.cfg {shlex.quote(str(header))}')
            self.assertNotEqual(result.returncode, 0)
    def test_tls_verification_default_and_bypass_is_rejected(self):
        if not shutil.which('openssl'):
            self.skipTest('openssl needed to generate a local self-signed certificate')
        cert, key = self.root / 'cert.pem', self.root / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=localhost', '-keyout', str(key), '-out', str(cert)],
                       check=True, capture_output=True, timeout=15)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        web = self.endpoint(tls=ctx)
        command = f'source_http_get {shlex.quote(web.base + "/repo.env")} {shlex.quote(str(self.root / "tls"))}'
        strict = self.shell(command)
        self.assertNotEqual(strict.returncode, 0)
        self.assertFalse((self.root / 'tls').exists())
        for flag in ('allow_unauthenticated_ssl', 'allow_unauthenticated_ssl=true',
                     'debian-installer/allow_unauthenticated_ssl=true'):
            result = self.shell(command, env={'INSTALLER_CMDLINE': flag})
            self.assertNotEqual(result.returncode, 0, result.stderr)
            self.assertIn("bypass is forbidden", result.stderr)
        explicit_false = self.shell(command, env={'INSTALLER_CMDLINE': 'allow_unauthenticated_ssl=false'})
        self.assertNotEqual(explicit_false.returncode, 0)
    def test_busybox_wget_redirects(self):
        busybox = shutil.which('busybox')
        if not busybox:
            self.skipTest('BusyBox is not installed')
        bindir = self.root / 'bin'
        bindir.mkdir()
        wget = bindir / 'wget'
        wget.write_text('#!/bin/sh\nexec ' + shlex.quote(busybox) + ' wget "$@"\n')
        wget.chmod(0o755)
        web = self.endpoint()
        result = self.shell('source_resolve_seed', env={'PATH': str(bindir) + ':' + os.environ['PATH'],
                            'INSTALLER_CMDLINE': f'url={web.url}/short'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), web.base)

class SnapshotTests(TransportFixture):
    def make_payload(self, files=None, special=None):
        seed = self.root / 'seed'
        seed.mkdir()
        files = files or {'repo.env': b'REPOSITORY_ROLE="server"\n',
                          'scripts/common/lib.sh': b'#!/bin/sh\ntrue\n',
                          'common.cfg': b'# fixture\n'}
        manifest = ''.join(f'{digest(data)}  {name}\n' for name, data in files.items()).encode()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as tf:
            for name, data in files.items():
                p = seed / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o644
                tf.addfile(info, io.BytesIO(data))
            if special:
                tf.addfile(special)
        (seed / 'payload.tar.gz').write_bytes(archive.getvalue())
        (seed / 'payload.manifest').write_bytes(manifest)
        return seed, digest(archive.getvalue()), digest(manifest)
    def prepare(self, seed, archive, manifest):
        return self.shell(f'source_prepare_payload {shlex.quote(str(seed))} {archive} {manifest}')
    def test_manifest_pin_mismatch_fails_without_ready_marker(self):
        seed, archive, manifest = self.make_payload()
        result = self.prepare(seed, archive, '0' * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('manifest differs', result.stderr)
        self.assertFalse((self.runtime / 'bootstrap/payload.ready').exists())
    def test_archive_pin_mismatch_fails_without_ready_marker(self):
        seed, archive, manifest = self.make_payload()
        result = self.prepare(seed, '0' * 64, manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('archive differs', result.stderr)
        self.assertFalse((self.runtime / 'bootstrap/payload.ready').exists())
    def test_local_edit_requires_rebuild(self):
        seed, archive, manifest = self.make_payload()
        (seed / 'common.cfg').write_text('# unpublished edit\n')
        result = self.prepare(seed, archive, manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('changed after build', result.stderr)
    def test_symlink_member_is_rejected_before_extraction(self):
        member = tarfile.TarInfo('escape')
        member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
        seed, archive, manifest = self.make_payload(special=member)
        result = self.prepare(seed, archive, manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('non-regular', result.stderr)
    def test_missing_snapshot_file_cannot_fall_back_to_network(self):
        seed, archive, manifest = self.make_payload()
        web = self.endpoint(seed)
        result = self.prepare(web.base, archive, manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        (seed / 'new-file').write_text('not in the pinned snapshot')
        result = self.shell(f'source_fetch {shlex.quote(web.base)} new-file {shlex.quote(str(self.root / "out"))}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('absent from validated payload', result.stderr)
        self.assertEqual(web.counts[RAW_PREFIX + '/new-file'], 0)
    def test_duplicate_archive_member_is_rejected(self):
        member = tarfile.TarInfo('common.cfg')
        member.size = 0
        seed, archive, manifest = self.make_payload(special=member)
        result = self.prepare(seed, archive, manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate', result.stderr)
    def test_archive_path_traversal_is_rejected(self):
        member = tarfile.TarInfo('../escape')
        member.size = 0
        seed, archive, manifest = self.make_payload(special=member)
        result = self.prepare(seed, archive, manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('traversal', result.stderr)
        self.assertFalse((self.runtime / 'bootstrap/escape').exists())
    def test_invalid_installer_shell_fails_before_ready_marker(self):
        seed, archive, manifest = self.make_payload({
            'repo.env': b'REPOSITORY_ROLE="server"\n',
            'scripts/common/lib.sh': b'#!/bin/sh\nif then\n'})
        result = self.prepare(seed, archive, manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid shell syntax', result.stderr)
        self.assertFalse((self.runtime / 'bootstrap/payload.ready').exists())
    def test_snapshot_cache_reuses_archive_and_manifest(self):
        seed, archive, manifest = self.make_payload()
        web = self.endpoint(seed)
        for _ in range(2):
            result = self.prepare(web.base, archive, manifest)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(web.counts[RAW_PREFIX + '/payload.tar.gz'], 1)
        self.assertEqual(web.counts[RAW_PREFIX + '/payload.manifest'], 1)

class RealBootstrapTests(TransportFixture):
    def include(self, cmdline):
        text = (FORKY / 'preseed.cfg').read_text().replace('\\\n', '')
        line = next(line for line in text.splitlines() if line.startswith('d-i preseed/include_command string '))
        command = line.split(' string ', 1)[1]
        return subprocess.run(['/bin/sh', '-c', command], capture_output=True, text=True,
            env={**self.env, 'INSTALLER_CMDLINE': cmdline}, timeout=45)
    def test_complete_local_bootstrap_and_flat_profile(self):
        result = self.include(f'file={FORKY}/preseed.cfg classes=prod;{ROLE};standard;dhcp;ssh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 5)
        for line in result.stdout.splitlines():
            self.assertTrue(line.startswith('file:///'))
            self.assertTrue(Path(line.removeprefix('file://')).is_file())
        self.assertTrue((self.runtime / 'bootstrap/preflight.ok').is_file())
        self.assertIn(f'role/{ROLE}', (self.runtime / 'state/context.env').read_text())
        self.assertTrue((self.runtime / 'state/selected-host.env').is_file())
    def test_complete_short_url_bootstrap_fetches_snapshot_once(self):
        web = self.endpoint()
        result = self.include(f'url={web.url}/short classes=prod;{ROLE};standard;dhcp;ssh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(web.counts[RAW_PREFIX + '/scripts/common/source.sh'], 1)
        self.assertEqual(web.counts[RAW_PREFIX + '/payload.tar.gz'], 1)
        self.assertEqual(web.counts[RAW_PREFIX + '/payload.manifest'], 1)
        # Individual envs, class fragments and late assets never hit the network.
        self.assertEqual(sum(web.counts.values()), 5)
    def test_opposite_role_fails_before_preflight_marker(self):
        other = 'desktop' if ROLE == 'server' else 'server'
        text = (FORKY / 'preseed.cfg').read_text().replace('\\\n', '')
        line = next(line for line in text.splitlines() if line.startswith('d-i preseed/include_command string '))
        command = line.split(' string ', 1)[1]
        process = subprocess.Popen(['/bin/sh', '-c', command], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
            env={**self.env, 'INSTALLER_CMDLINE': f'file={FORKY}/preseed.cfg classes=prod;{other};standard;dhcp'})
        try:
            failure = self.runtime / 'state/first-failure'
            self.assertTrue(wait_file(failure), 'bootstrap did not retain its fatal record')
            self.assertIsNone(process.poll(), 'fatal bootstrap returned to the installer')
            self.assertFalse((self.runtime / 'bootstrap/preflight.ok').exists())
            self.assertIn('state=FATAL', failure.read_text())
        finally:
            stop_test_tree(process)

if __name__ == '__main__':
    unittest.main()
