#!/usr/bin/python3
"""Metadata-first repository regressions, including real curl/TLS and APT.

Tiny .deb fixtures are ar/tar serialization only; no software is compiled or
installed. Remote providers are represented by bounded metadata fixtures.
"""
import copy
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from test_local_apt_repository import repo, fixture, SOURCE

TARGET = SOURCE.parents[3]
ROOT = Path(__file__).resolve().parents[2]


class Workspace(unittest.TestCase):
    def setUp(self):
        base = Path('/var/lib/local-apt-tests')
        base.mkdir(mode=0o755, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(dir=base))
        self.repository = repo.Repository(self.work / 'software', self.work / 'etc')
        self.deb = self.work / 'input.deb'
        fixture(self.deb)

    def tearDown(self):
        home = self.repository.signing
        if home.exists():
            subprocess.run(['/usr/bin/gpgconf', '--homedir', str(home), '--kill', 'gpg-agent'], capture_output=True)
        shutil.rmtree(self.work)

    def record(self, policy=None):
        result = self.repository.ingest(self.repository.stage(self.deb), policy=policy)
        self.repository.publish()
        return result


def github_release(version='2.0', assets=None, **extra):
    return dict(id=int(version.split('.')[0]), tag_name='v' + version, draft=False, prerelease=False,
                published_at='2026-08-01T00:00:00Z', assets=assets or [
                    {'id': 100 + int(version.split('.')[0]), 'name': f'fixture-app_{version}_all.deb',
                     'browser_download_url': f'https://downloads.example.test/{version}/app.deb',
                     'updated_at': '2026-08-01T00:00:00Z', 'state': 'uploaded'}], **extra)


class DiscoveryTests(Workspace):
    def discover(self, documents, url='https://github.com/team/app/releases', arch='all'):
        with mock.patch.object(self.repository.discovery, 'metadata', return_value=json.dumps(documents).encode()):
            return self.repository.discovery.release(repo.source_for(url), 'fixture-app', arch, self.work)

    def test_pinned_github_asset_tracks_new_releases_and_preserves_edition(self):
        assets = [{'id': index, 'name': name, 'browser_download_url': 'https://example.test/' + name}
                  for index, name in enumerate(['fixture-app_2.0_amd64.deb', 'fixture-app_2.0_arm64.deb',
                                                'fixture-app-pro_2.0_amd64.deb'])]
        candidate = self.discover([github_release('2.0', assets)],
            'https://github.com/team/app/releases/download/v1.0/fixture-app_1.0_amd64.deb', 'amd64')
        self.assertEqual(candidate['name'], 'fixture-app_2.0_amd64.deb')
        self.assertEqual(candidate['version'], '2.0')

    def test_no_payload_request_when_release_version_not_newer(self):
        with self.repository.locked():
            record = self.record({'automatic': True, 'url': 'https://github.com/team/app/releases'})
            candidate = self.discover([github_release('1.0')])
            with mock.patch.object(self.repository.discovery, 'candidate', return_value=candidate), \
                 mock.patch.object(repo, 'retrieve_candidate', side_effect=AssertionError('package GET')):
                self.assertEqual(self.repository.refresh(), 0)
            self.assertEqual(record['version'], '1.0')

    def test_release_candidate_is_not_committed_when_download_fails(self):
        with self.repository.locked():
            self.record({'automatic': True, 'url': 'https://github.com/team/app/releases'})
            before = os.readlink(self.repository.repo / 'current')
            candidate = self.discover([github_release('2.0')])
            with mock.patch.object(self.repository.discovery, 'candidate', return_value=candidate), \
                 mock.patch.object(repo, 'retrieve_candidate', side_effect=repo.Error('network unavailable')) as get:
                self.assertEqual(self.repository.refresh(), 3)
                self.assertEqual(self.repository.refresh(), 3)
                self.assertEqual(get.call_count, 2)
            self.assertEqual(os.readlink(self.repository.repo / 'current'), before)
            self.assertNotIn('tracking', self.repository.catalog['packages']['fixture-app:all']['policy'])

    def test_only_stable_published_releases_are_considered(self):
        stable = github_release('2.0')
        prerelease = github_release('3.0'); prerelease['prerelease'] = True
        draft = github_release('4.0'); draft['draft'] = True
        future = github_release('5.0'); future['published_at'] = '2999-01-01T00:00:00Z'
        self.assertEqual(self.discover([draft, future, prerelease, stable])['version'], '2.0')

    def test_republished_old_release_cannot_win_by_timestamp(self):
        old = github_release('1.0'); old['published_at'] = '2026-09-01T00:00:00Z'
        self.assertEqual(self.discover([old, github_release('2.0')])['version'], '2.0')

    def test_ambiguous_edition_fails_closed(self):
        assets = [{'name': name, 'browser_download_url': 'https://example.test/' + name}
                  for name in ('fixture-app_2.0_all.deb', 'fixture-app-pro_2.0_all.deb')]
        with self.assertRaisesRegex(repo.Error, 'ambiguous'):
            self.discover([github_release('2.0', assets)])

    def test_all_architecture_does_not_select_amd64(self):
        assets = [{'name': 'fixture-app_2.0_amd64.deb', 'browser_download_url': 'https://example.test/app.deb'}]
        with self.assertRaises(repo.Error):
            self.discover([github_release('2.0', assets)])
        self.assertTrue(repo.compatible_asset('fixture-app_2.0_x86_64.deb', 'amd64'))
        self.assertFalse(repo.compatible_asset('fixture-app_2.0_armhf.deb', 'amd64'))

    def test_gitlab_old_asset_url_uses_latest_list_not_old_tag(self):
        releases = [{'tag_name': 'v2.0', 'released_at': '2026-08-01T00:00:00Z', 'assets': {'links': [
            {'id': 7, 'name': 'fixture-app_2.0_all.deb', 'url': 'https://example.test/current.deb'}]}}]
        candidate = self.discover(releases, 'https://gitlab.example.test/a/b/c/-/releases/v1.0/downloads/fixture-app_1.0_all.deb')
        self.assertEqual(candidate['kind'], 'gitlab')
        self.assertEqual(candidate['version'], '2.0')
        self.assertIn('a%2Fb%2Fc', repo.source_for('https://gitlab.example.test/a/b/c/-/releases')['url'])

    def test_sourceforge_feed_uses_matching_latest_deb(self):
        xml = b'''<rss version="2.0"><channel>
        <item><link>https://sourceforge.net/projects/app/files/1.0/fixture-app_1.0_all.deb/download</link><pubDate>Sat, 01 Aug 2026 00:00:00 GMT</pubDate></item>
        <item><link>https://sourceforge.net/projects/app/files/2.0/fixture-app_2.0_all.deb/download</link><pubDate>Sun, 02 Aug 2026 00:00:00 GMT</pubDate></item>
        <item><link>https://sourceforge.net/projects/app/files/2.0/fixture-app_2.0_amd64.deb/download</link><pubDate>Sun, 02 Aug 2026 00:00:00 GMT</pubDate></item>
        </channel></rss>'''
        source = repo.source_for('https://downloads.sourceforge.net/project/app/1.0/fixture-app_1.0_all.deb')
        with mock.patch.object(self.repository.discovery, 'metadata', return_value=xml) as get:
            candidate = self.repository.discovery.release(source, 'fixture-app', 'all', self.work)
        self.assertEqual(candidate['version'], '2.0')
        self.assertEqual(get.call_args.kwargs['interval'], 1800)

    def test_sourceforge_rejects_entities(self):
        with mock.patch.object(self.repository.discovery, 'metadata', return_value=b'<!DOCTYPE rss [<!ENTITY e SYSTEM "file:///etc/passwd">]><rss/>'):
            with self.assertRaisesRegex(repo.Error, 'DTD'):
                self.repository.discovery.release(repo.source_for('https://sourceforge.net/projects/app'), 'fixture-app', 'all', self.work)

    def test_metadata_cache_reuses_body_after_304_and_honors_sf_interval(self):
        url = 'https://example.test/releases'
        def fake_request(url, destination, **kwargs):
            destination.write_bytes(b'[]')
            return {'status': 200, 'url': url, 'headers': {'etag': '"metadata-1"'}}
        with self.repository.locked(), mock.patch.object(repo, 'request', side_effect=fake_request):
            self.assertEqual(self.repository.discovery.metadata(url, self.work), b'[]')
        self.repository.discovery.memory.clear()
        with mock.patch.object(repo, 'request', return_value={'status': 304, 'url': url, 'headers': {}}) as get:
            self.assertEqual(self.repository.discovery.metadata(url, self.work), b'[]')
            self.assertEqual(get.call_args.kwargs['headers'], {'If-None-Match': '"metadata-1"'})
        self.repository.discovery.memory.clear()
        with mock.patch.object(repo, 'request', side_effect=AssertionError('polled too soon')):
            self.assertEqual(self.repository.discovery.metadata(url, self.work, interval=1800), b'[]')

    def test_release_same_version_mutation_does_not_download_again(self):
        candidate = self.discover([github_release('1.0')])
        record = {'sha256': 'a' * 64, 'version': '1.0', 'policy': {'tracking': dict(candidate, token='old')}}
        with self.assertRaisesRegex(repo.Error, 'without a newer'):
            repo.update_decision(candidate, record)

    def test_debian_epoch_does_not_hide_upstream_tag_update(self):
        candidate = self.discover([github_release('2.0')])
        self.assertEqual(repo.update_decision(candidate, {'version': '1:1.0-1', 'sha256': 'a' * 64}), 'download')

    def test_changed_direct_etag_does_not_get_overruled_by_equal_filename_version(self):
        candidate = {'kind': 'direct', 'source': 'a', 'token': 'new', 'version': '1.0', 'validators': {'etag': '"new"'}}
        record = {'version': '1.0', 'sha256': 'a' * 64, 'policy': {'tracking': {
            'source': 'a', 'token': 'old', 'validators': {'etag': '"old"'}}}}
        self.assertEqual(repo.update_decision(candidate, record), 'download')

    def test_static_package_makes_no_metadata_or_body_requests(self):
        with self.repository.locked():
            self.record({'automatic': False, 'url': 'https://github.com/team/app/releases'})
            with mock.patch.object(repo, 'request', side_effect=AssertionError('static network access')):
                self.assertEqual(self.repository.refresh(), 0)

    def test_unknown_direct_baseline_does_not_trigger_initial_body_download(self):
        source = repo.source_for('https://example.test/app.deb')
        candidate = {'source': repo.source_id(source), 'kind': 'direct', 'token': 'one', 'version': '',
                     'validators': {'etag': '"one"'}, 'url': source['url']}
        with self.repository.locked():
            record = self.record({'automatic': True, 'url': source['url']})
            with mock.patch.object(self.repository.discovery, 'candidate', return_value=candidate), \
                 mock.patch.object(repo, 'retrieve_candidate', side_effect=AssertionError('baseline GET')):
                self.assertEqual(self.repository.refresh(), 0)
            self.assertTrue(record['policy']['tracking']['observed_only'])

    def test_matching_vendor_manifest_skips_fetch_even_without_upgrade(self):
        for app, digest in [('discord', 'a' * 64), ('ledger', 'b' * 128)]:
            with self.subTest(app=app), self.repository.locked():
                record = self.record({'automatic': True, 'adapter': app})
                record['control']['X-Local-Source-Digest'] = digest
                record['control']['X-Local-Upstream-Version'] = '1.0'
                def descriptor(action, requested, work=None):
                    self.assertEqual(action, 'probe')
                    self.assertEqual(requested, app)
                    return {'source_id': digest, 'upstream_version': '1.0'}
                with mock.patch.object(self.repository, 'vendor_descriptor', side_effect=descriptor):
                    self.assertEqual(self.repository.refresh(), 0)

    def test_init_removes_known_legacy_hook_and_wrapper(self):
        hook = self.repository.etc / 'apt/apt.conf.d/90-local-apt-repository'
        old = self.repository.etc.parent / 'usr/local/bin/local-add-deb'
        hook.parent.mkdir(parents=True)
        old.parent.mkdir(parents=True)
        hook.write_text('APT::Update::Pre-Invoke { "/usr/local/libexec/local-apt-repository refresh"; };\n')
        old.write_bytes(b'#!/bin/sh\nset -eu\nif [ "$#" -ne 1 ]; then\n    printf \'%s\\n\' \'Usage: sudo local-add-deb FILE.deb | sudo local-add-deb --delete\' >&2\n    exit 64\nfi\nif [ "$1" = --delete ]; then\n    exec /usr/local/libexec/local-apt-repository delete\nfi\nexec /usr/local/libexec/local-apt-repository add -- "$1"\n')
        self.repository.retire_pre_update_hook()
        self.assertFalse(hook.exists())
        self.assertFalse(old.exists())

    def test_customized_legacy_hook_is_not_silently_deleted(self):
        hook = self.repository.etc / 'apt/apt.conf.d/90-local-apt-repository'
        hook.parent.mkdir(parents=True)
        hook.write_text('APT::Update::Pre-Invoke { "/admin/custom"; };\n')
        with self.assertRaises(repo.Error):
            self.repository.retire_pre_update_hook()
        self.assertTrue(hook.exists())

    def test_hook_with_additional_custom_command_is_preserved(self):
        hook = self.repository.etc / 'apt/apt.conf.d/90-local-apt-repository'
        hook.parent.mkdir(parents=True)
        hook.write_text('APT::Update::Pre-Invoke { "/usr/local/libexec/local-apt-repository refresh"; };\nAPT::Update::Post-Invoke { "/admin/custom"; };\n')
        with self.assertRaises(repo.Error):
            self.repository.retire_pre_update_hook()
        self.assertTrue(hook.exists())

    def test_unverified_baseline_does_not_silently_become_verified(self):
        record = {'policy': {'tracking': {'source': 's', 'token': 't', 'observed_only': True}}}
        self.repository.remember_candidate(record, {'source': 's', 'token': 't'})
        self.assertTrue(record['policy']['tracking']['observed_only'])

    def test_same_version_conflicting_release_digest_is_not_adopted(self):
        candidate = self.discover([github_release('1.0')])
        candidate['sha256'] = 'b' * 64
        with self.assertRaisesRegex(repo.Error, 'different bytes'):
            repo.update_decision(candidate, {'version': '1.0', 'sha256': 'a' * 64})

    def test_stale_body_cannot_satisfy_new_release_metadata(self):
        candidate = self.discover([github_release('2.0')])
        def retrieve(candidate, saved, destination):
            destination.write_bytes(self.deb.read_bytes())
            return candidate
        with self.repository.locked():
            record = self.record({'automatic': True, 'url': 'https://github.com/team/app/releases'})
            before = os.readlink(self.repository.repo / 'current')
            with mock.patch.object(self.repository.discovery, 'candidate', return_value=candidate), \
                 mock.patch.object(repo, 'retrieve_candidate', side_effect=retrieve):
                self.assertEqual(self.repository.refresh(), 3)
            self.assertEqual(os.readlink(self.repository.repo / 'current'), before)
            self.assertNotIn('tracking', record['policy'])

    def test_last_modified_only_check_and_download_precondition(self):
        before = 'Tue, 01 Sep 2026 00:00:00 GMT'
        after = 'Wed, 02 Sep 2026 00:00:00 GMT'
        saved = {'source': 's', 'token': 'before', 'validators': {'last_modified': before}}
        record = {'version': '1.0', 'sha256': 'a' * 64, 'policy': {'tracking': saved}}
        candidate = {'kind': 'direct', 'source': 's', 'token': 'after', 'url': 'https://example.test/app.deb',
                     'validators': {'last_modified': after}}
        self.assertEqual(repo.conditional_headers(saved['validators']), {'If-Modified-Since': before})
        self.assertEqual(repo.update_decision(candidate, record), 'download')
        def request(url, destination, **kwargs):
            self.assertEqual(kwargs['headers'], {'If-Unmodified-Since': after})
            destination.write_bytes(self.deb.read_bytes())
            return {'status': 200, 'headers': {'last-modified': after}}
        with mock.patch.object(repo, 'request', side_effect=request):
            repo.retrieve_candidate(candidate, saved, self.work / 'modified.deb')
        candidate['validators']['last_modified'] = 'Mon, 31 Aug 2026 00:00:00 GMT'
        with self.assertRaisesRegex(repo.Error, 'backwards'):
            repo.update_decision(candidate, record)

    def test_changed_validators_between_head_and_get_fail_closed(self):
        candidate = {'kind': 'direct', 'source': 's', 'token': 't', 'url': 'https://example.test/app.deb',
                     'validators': {'etag': '"head"'}}
        def request(url, destination, **kwargs):
            destination.write_bytes(self.deb.read_bytes())
            return {'status': 200, 'headers': {'etag': '"get"'}}
        with mock.patch.object(repo, 'request', side_effect=request):
            with self.assertRaisesRegex(repo.Error, 'between HEAD and GET'):
                repo.retrieve_candidate(candidate, {}, self.work / 'raced.deb')

    def test_discovered_size_and_digest_are_verified(self):
        def request(url, destination, **kwargs):
            destination.write_bytes(self.deb.read_bytes())
            return {'status': 200, 'headers': {}}
        base = {'kind': 'github', 'source': 's', 'token': 't', 'url': 'https://example.test/app.deb'}
        with mock.patch.object(repo, 'request', side_effect=request):
            for index, extra in enumerate(({'size': 1}, {'sha256': '0' * 64})):
                with self.subTest(metadata=extra), self.assertRaises(repo.Error):
                    repo.retrieve_candidate(dict(base, **extra), {}, self.work / f'mismatch-{index}.deb')

    def test_weekly_noop_refresh_does_not_republish_or_retrieve(self):
        candidate = self.discover([github_release('1.0')])
        with self.repository.locked():
            self.record({'automatic': True, 'url': 'https://github.com/team/app/releases', 'tracking': candidate})
            before = os.readlink(self.repository.repo / 'current')
            with mock.patch.object(self.repository.discovery, 'candidate', return_value=candidate), \
                 mock.patch.object(repo, 'retrieve_candidate', side_effect=AssertionError('no-op retrieval')):
                self.assertEqual(self.repository.refresh(), 0)
                self.assertEqual(self.repository.refresh(), 0)
            self.assertEqual(os.readlink(self.repository.repo / 'current'), before)

    def test_old_source_etag_is_not_sent_to_new_source(self):
        candidate = {'kind': 'direct', 'source': 'new-source', 'url': 'https://example.test/app.deb',
                     'validators': {'etag': '"new"'}, 'token': 'new'}
        saved = {'source': 'old-source', 'validators': {'etag': '"old"'}}
        def request(url, destination, **kwargs):
            self.assertNotIn('If-None-Match', kwargs['headers'])
            destination.write_bytes(self.deb.read_bytes())
            return {'status': 200, 'headers': {'etag': '"new"'}}
        with mock.patch.object(repo, 'request', side_effect=request):
            repo.retrieve_candidate(candidate, saved, self.work / 'new-source.deb')

    def test_release_filename_prerelease_is_excluded(self):
        release = github_release('3.0', [{'name': 'fixture-app_3.0-beta_all.deb',
                    'browser_download_url': 'https://example.test/fixture-app_3.0-beta_all.deb'}])
        self.assertEqual(self.discover([release, github_release('2.0')])['version'], '2.0')

    def test_header_parser_uses_final_redirect_block_and_rejects_duplicates(self):
        raw = b'HTTP/1.1 302 Found\r\nETag: "redirect"\r\n\r\nHTTP/2 200\r\nETag: "file"\r\n\r\n'
        self.assertEqual(repo.http_headers(raw, 200)['etag'], '"file"')
        with self.assertRaises(repo.Error):
            repo.http_headers(b'HTTP/2 200\r\nETag: "a"\r\nETag: "b"\r\n\r\n', 200)

    def test_new_wrapper_argument_contract_and_installer_units(self):
        wrapper = TARGET / 'usr/local/bin/local-apt-init'
        for argv, status in [([], 64), (['file.deb'], 64), (['--add'], 64), (['--refresh', 'extra'], 64), (['--help'], 0)]:
            result = subprocess.run(['/bin/sh', str(wrapper), *argv], capture_output=True)
            self.assertEqual(result.returncode, status)
        self.assertFalse((TARGET / 'usr/local/bin/local-add-deb').exists())
        self.assertFalse((TARGET / 'etc/apt/apt.conf.d/90-local-apt-repository').exists())
        timer = (TARGET / 'etc/systemd/system/local-apt-refresh.timer').read_text()
        self.assertIn('OnCalendar=weekly', timer)
        self.assertIn('Persistent=true', timer)
        script = (ROOT / 'd-i/forky/scripts/late/software.sh').read_text()
        self.assertIn('enable local-apt-inbox.path local-apt-refresh.timer', script)
        self.assertNotIn('etc/apt/apt.conf.d/90-local-apt-repository', script)


class TLSHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def response(self, body):
        state = self.server.test_state
        state['requests'].append((self.command, self.path, dict(self.headers)))
        if self.path == '/head-unsupported' and self.command == 'HEAD':
            self.send_error(405); return
        if self.path == '/downgrade':
            self.send_response(302)
            self.send_header('Location', 'http://127.0.0.1/plain')
            self.end_headers(); return
        etag = '"v' + str(state['version']) + '"'
        modified = f'0{state["version"]} Sep 2026 00:00:00 GMT'
        # Weekday is deliberately stable here; parsing still yields the date.
        modified = 'Tue, ' + modified
        tags = self.path != '/no-validators'
        if tags and self.headers.get('If-None-Match') == etag:
            self.send_response(304); self.end_headers(); return
        if self.headers.get('If-Match') and self.headers['If-Match'] != etag:
            self.send_error(412); return
        data = state['bodies'][state['version']]
        self.send_response(200)
        self.send_header('Content-Type', 'application/vnd.debian.binary-package')
        if tags:
            self.send_header('ETag', etag)
            self.send_header('Last-Modified', modified)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data)

    def do_HEAD(self): self.response(False)
    def do_GET(self): self.response(True)


class RealTransportTests(Workspace):
    def setUp(self):
        super().setUp()
        cert, key = self.work / 'test.crt', self.work / 'test.key'
        subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-days', '1', '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1',
                        '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
        bodies = {1: self.deb.read_bytes()}
        for version in (2, 3):
            path = self.work / f'v{version}.deb'; fixture(path, version=f'{version}.0')
            bodies[version] = path.read_bytes()
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), TLSHandler)
        self.server.test_state = {'version': 1, 'bodies': bodies, 'requests': []}
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'https://127.0.0.1:{self.server.server_port}'
        validate = repo.https_url
        # Test-only origin exception for an ephemeral local TLS port. Production
        # still accepts only HTTPS:443 and always verifies the server certificate.
        self.url_patch = mock.patch.object(repo, 'https_url', side_effect=lambda url: url if url.startswith(self.base + '/') else validate(url))
        self.env_patch = mock.patch.dict(repo.ENV, {'CURL_CA_BUNDLE': str(cert)})
        self.url_patch.start(); self.env_patch.start()

    def tearDown(self):
        self.url_patch.stop(); self.env_patch.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        super().tearDown()

    def initialize(self, endpoint='/app.deb'):
        policy = {'automatic': True, 'url': self.base + endpoint}
        record = self.repository.ingest(self.repository.stage(self.deb), policy=policy)
        self.repository.initialize_tracking(record, self.work)
        self.repository.publish()
        return record

    def test_real_head_304_then_changed_get_publish_then_no_get(self):
        with self.repository.locked():
            self.initialize()
            self.assertEqual(self.repository.refresh(), 0)
            self.assertEqual([r[0] for r in self.server.test_state['requests']], ['HEAD', 'HEAD'])
            old = os.readlink(self.repository.repo / 'current')
            self.server.test_state['version'] = 2
            self.assertEqual(self.repository.refresh(), 0)
            record = self.repository.catalog['packages']['fixture-app:all']
            self.assertEqual(record['version'], '2.0')
            self.assertNotEqual(os.readlink(self.repository.repo / 'current'), old)
            self.assertEqual(self.repository.refresh(), 0)
            requests = self.server.test_state['requests']
            self.assertEqual(sum(r[0] == 'GET' for r in requests), 1)
            get = next(r for r in requests if r[0] == 'GET')
            self.assertEqual(get[2]['If-Match'], '"v2"')
            self.assertEqual(get[2]['If-None-Match'], '"v1"')

    def test_head_unsupported_or_missing_validators_never_falls_back_to_get(self):
        for endpoint in ('/no-validators', '/head-unsupported'):
            with self.subTest(endpoint=endpoint), self.repository.locked():
                self.record({'automatic': True, 'url': self.base + endpoint})
                self.assertEqual(self.repository.refresh(), 3)
        self.assertFalse(any(r[0] == 'GET' for r in self.server.test_state['requests']))

    def test_bad_body_cannot_advance_validator_receipt_and_retry_recovers(self):
        with self.repository.locked():
            self.initialize()
            good = self.server.test_state['bodies'][2]
            self.server.test_state['bodies'][2] = b'<html>not a Debian package</html>'
            self.server.test_state['version'] = 2
            self.assertEqual(self.repository.refresh(), 3)
            record = self.repository.catalog['packages']['fixture-app:all']
            self.assertEqual(record['version'], '1.0')
            self.assertEqual(record['policy']['tracking']['validators']['etag'], '"v1"')
            self.server.test_state['bodies'][2] = good
            self.assertEqual(self.repository.refresh(), 0)
            self.assertEqual(self.repository.catalog['packages']['fixture-app:all']['version'], '2.0')

    def test_signing_failure_does_not_commit_download_validators(self):
        with self.repository.locked():
            self.initialize()
            old = os.readlink(self.repository.repo / 'current')
            self.server.test_state['version'] = 2
            original = repo.run
            def fail_sign(argv, **kwargs):
                if '--clearsign' in argv:
                    raise repo.Error('injected signing failure')
                return original(argv, **kwargs)
            with mock.patch.object(repo, 'run', side_effect=fail_sign):
                with self.assertRaises(repo.Error):
                    self.repository.refresh()
            self.assertEqual(os.readlink(self.repository.repo / 'current'), old)
        recovered = repo.Repository(self.repository.root, self.repository.etc)
        with recovered.locked():
            record = recovered.catalog['packages']['fixture-app:all']
            self.assertEqual(record['policy']['tracking']['validators']['etag'], '"v1"')
            recovered.process_inbox(); recovered.publish()
            self.assertEqual(recovered.catalog['packages']['fixture-app:all']['version'], '2.0')

    def test_curl_refuses_https_to_http_redirect(self):
        with self.assertRaises(repo.Error):
            repo.request(self.base + '/downgrade', self.work / 'head', method='HEAD')

    def test_apt_update_reads_signed_metadata_without_contacting_upstream(self):
        with self.repository.locked():
            self.initialize()
            before = len(self.server.test_state['requests'])
            apt = self.work / 'apt'; apt.mkdir()
            for sub in ('lists/partial', 'cache/archives/partial', 'sourceparts', 'configparts'):
                (apt / sub).mkdir(parents=True)
            (apt / 'status').write_text('')
            config = [
                '-o', f'Dir::Etc::sourcelist={self.repository.source}',
                '-o', f'Dir::Etc::sourceparts={apt / "sourceparts"}',
                '-o', f'Dir::Etc::parts={apt / "configparts"}',
                '-o', 'Dir::Etc::main=/dev/null',
                '-o', f'Dir::State::status={apt / "status"}',
                '-o', f'Dir::State::lists={apt / "lists"}',
                '-o', f'Dir::Cache={apt / "cache"}',
                '-o', 'APT::Sandbox::User=root',
            ]
            env = dict(repo.ENV, APT_CONFIG='/dev/null')
            subprocess.run(['/usr/bin/apt-get', *config, 'update'], check=True, env=env, capture_output=True)
            self.assertEqual(len(self.server.test_state['requests']), before)
            self.server.test_state['version'] = 2
            self.assertEqual(self.repository.refresh(), 0)
            before = len(self.server.test_state['requests'])
            subprocess.run(['/usr/bin/apt-get', *config, 'update'], check=True, env=env, capture_output=True)
            policy = subprocess.run(['/usr/bin/apt-cache', *config, 'policy', 'fixture-app'], check=True, env=env, capture_output=True, text=True).stdout
            self.assertIn('Candidate: 2.0', policy)
            self.assertEqual(len(self.server.test_state['requests']), before)
            self.assertEqual((apt / 'status').read_text(), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
