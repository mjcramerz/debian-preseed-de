#!/usr/bin/python3
"""Offline package-policy tests: serialize archives; never compile/install code."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import unittest
from unittest import mock

import test_local_apt_repository as base_tests
from test_local_apt_repository import repo, SOURCE

TARGET = SOURCE.parents[3]


def package(path, name='fixture-app', version='1.0', script=None, extra=None):
    payload = {
        'usr/lib/example/app': b'vendor binary placeholder\n',
        'etc/apt/sources.list.d/vendor.sources': b'Types: deb\nURIs: https://vendor.test\nSuites: stable\n',
        'usr/share/keyrings/vendor.gpg': b'vendor key\n',
    }
    payload.update(extra or {})
    control = {
        'Package': name, 'Version': version, 'Architecture': 'all',
        'Maintainer': 'Fixture <test@localhost>', 'Description': 'Archive fixture',
        'Depends': 'libc6, libx11-6 | libx11-dev, xwayland, nvidia-driver, libextra',
    }
    metadata = {'control': repo.control_bytes(control),
                'conffiles': b'/etc/apt/sources.list.d/vendor.sources\n',
                'md5sums': ''.join(hashlib.md5(data).hexdigest() + '  ' + name + '\n'
                                   for name, data in payload.items()).encode()}
    if script is not None:
        metadata['postinst'] = script
    streams = []
    for files in (metadata, payload):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:', format=tarfile.GNU_FORMAT) as archive:
            for name, data in files.items():
                member = tarfile.TarInfo('./' + name)
                member.size, member.mode = len(data), 0o755 if name == 'postinst' else 0o644
                archive.addfile(member, io.BytesIO(data))
        streams.append(gzip.compress(stream.getvalue(), mtime=0))
    with path.open('wb') as stream:
        stream.write(b'!<arch>\n')
        for name, data in zip(('debian-binary', 'control.tar.gz', 'data.tar.gz'), (b'2.0\n', *streams)):
            stream.write(repo.ar_header(name, len(data)))
            stream.write(data)
            if len(data) % 2:
                stream.write(b'\n')
    path.chmod(0o600)
    return payload


def members(path, part):
    blob = subprocess.run(['/usr/bin/dpkg-deb', '--' + part + '-tarfile', str(path)],
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
        return {repo.archive_name(item.name): archive.extractfile(item).read()
                for item in archive if item.isfile()}


class PersistedPolicyTests(unittest.TestCase):
    setUpClass = classmethod(base_tests.RepositoryTests.setUpClass.__func__)
    setUp = base_tests.RepositoryTests.setUp
    tearDown = base_tests.RepositoryTests.tearDown

    def registry(self, value):
        path = self.repository.policy_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        path.chmod(0o644)

    def configure_chatgpt(self):
        self.registry(json.loads((TARGET / 'usr/local/share/software/package-policies.json').read_text()))
        assets = self.directory / 'usr/local/share/software/chatgpt'
        assets.mkdir()
        for name in ('default', 'apparmor.profile', 'chatgpt.desktop', 'chatgpt.png'):
            (assets / name).write_bytes(('managed ' + name).encode())

    def test_chatgpt_first_import_and_new_version_use_mandatory_policy(self):
        self.configure_chatgpt()
        with self.repository.locked():
            for version in ('1.0', '2.0'):
                package(self.package, name='chatgpt', version=version,
                        script=b'#!/bin/sh\nexit 97 # sources.list recreation\n')
                original = self.package.read_bytes()
                item = self.repository.ingest(self.repository.stage(self.package))
                self.repository.publish()
                self.assertEqual(item['control']['Depends'], 'libc6, libextra')
                self.assertEqual(item['upstream_version'], version)
                self.assertTrue(item['version'].startswith(version + '+localrepo'))
                result = self.repository.repo / item['filename']
                data = members(result, 'fsys')
                self.assertFalse(any(repo.vendor_apt_path(name) for name in data))
                self.assertEqual(data['etc/default/chatgpt'], b'managed default')
                self.assertEqual(data['usr/share/pixmaps/chatgpt.png'], b'managed chatgpt.png')
                control = members(result, 'ctrl')
                self.assertIn(b'configure-chatgpt', control['postinst'])
                self.assertNotIn(b'exit 97', control['postinst'])
                self.assertNotIn(b'vendor.sources', control['conffiles'])
                self.assertNotIn(b'vendor.gpg', control['md5sums'])
                self.assertEqual((self.repository.root / item['upstream_filename']).read_bytes(), original)
                self.assertEqual(item['control']['X-Local-Policy-SHA256'], repo.policy_digest(item['policy']))

    def test_mandatory_chatgpt_policy_cannot_be_disabled_by_import(self):
        self.configure_chatgpt()
        policy = self.repository.effective_policy('chatgpt', {'remove_vendor_apt': False, 'drop_maintainer_scripts': []})
        self.assertTrue(policy['remove_vendor_apt'])
        self.assertIn('postinst', policy['drop_maintainer_scripts'])

    def test_generic_policy_survives_new_download_import(self):
        with self.repository.locked():
            for version in ('1.0', '2.0'):
                package(self.package, version=version)
                policy = {'remove_depends': ['libextra'], 'remove_vendor_apt': True} if version == '1.0' else None
                item = self.repository.ingest(self.repository.stage(self.package), policy=policy)
                self.repository.publish()
                self.assertNotIn('libextra', item['control']['Depends'])
                self.assertFalse(any(repo.vendor_apt_path(name) for name in members(self.repository.repo / item['filename'], 'fsys')))
                self.assertTrue(item['policy']['remove_vendor_apt'])

    def test_refresh_current_metadata_still_reconciles_new_mandatory_policy(self):
        with self.repository.locked():
            package(self.package)
            initial = self.repository.ingest(self.repository.stage(self.package))
            self.repository.publish()
            self.registry({'fixture-app': {'remove_depends': ['libextra'], 'remove_vendor_apt': True}})
            with mock.patch.object(repo, 'retrieve_candidate', side_effect=AssertionError('network access')):
                self.assertEqual(self.repository.refresh(), 0)
            result = self.repository.select('fixture-app')[1]
            self.assertNotEqual(initial['sha256'], result['sha256'])
            self.assertNotIn('libextra', result['control']['Depends'])
            self.assertEqual(result['upstream_sha256'], initial['upstream_sha256'])

    def test_actual_refresh_download_path_applies_persisted_policy(self):
        with self.repository.locked():
            package(self.package)
            first = self.repository.ingest(self.repository.stage(self.package), policy={
                'automatic': True, 'url': 'https://github.com/example/fixture/releases',
                'remove_depends': ['libextra'], 'remove_vendor_apt': True})
            self.repository.publish()
            candidate = {'kind': 'github', 'source': 'fixture-release', 'token': 'release-2',
                         'version': '2.0', 'url': 'https://example.test/fixture-app_2.0_all.deb'}
            def retrieve(found, saved, destination):
                package(destination, version='2.0')
                return dict(found)
            with mock.patch.object(self.repository.discovery, 'candidate', return_value=candidate), \
                    mock.patch.object(repo, 'retrieve_candidate', side_effect=retrieve):
                self.assertEqual(self.repository.refresh(), 0)
            item = self.repository.select('fixture-app')[1]
            self.assertEqual(item['upstream_version'], '2.0')
            self.assertNotIn('libextra', item['control']['Depends'])
            self.assertFalse(any(repo.vendor_apt_path(name) for name in members(self.repository.repo / item['filename'], 'fsys')))
            self.assertNotEqual(first['upstream_sha256'], item['upstream_sha256'])

    def test_reapply_uses_original_archive_and_increments_local_revision(self):
        with self.repository.locked():
            package(self.package)
            first = self.repository.ingest(self.repository.stage(self.package), policy={'remove_depends': ['libextra']})
            self.repository.publish()
            second = self.repository.reapply('fixture-app', {'remove_vendor_apt': True})
            self.assertTrue(repo.newer(second['version'], first['version']))
            third = self.repository.reapply('fixture-app', {'remove_depends': []})
            self.assertIn('libextra', third['control']['Depends'])
            self.assertTrue(third['policy']['remove_vendor_apt'])
            self.assertEqual(third['upstream_sha256'], first['upstream_sha256'])

    def test_vendor_source_script_requires_explicit_review_before_publication(self):
        with self.repository.locked():
            self.repository.publish()
            before = (self.repository.repo / 'current').readlink()
            package(self.package, script=b'#!/bin/sh\necho bad > /etc/apt/sources.list.d/vendor.list\n')
            with self.assertRaisesRegex(repo.Error, 'postinst may recreate'):
                self.repository.ingest(self.repository.stage(self.package), policy={'remove_vendor_apt': True})
            self.assertEqual((self.repository.repo / 'current').readlink(), before)
            self.assertEqual(self.repository.catalog['packages'], {})
            result = self.repository.ingest(self.repository.stage(self.package),
                    policy={'remove_vendor_apt': True, 'drop_maintainer_scripts': ['postinst']})
            self.assertNotIn('postinst', members(self.repository.repo / result['filename'], 'ctrl'))

    def test_corrupt_retained_archive_cannot_be_reapplied(self):
        with self.repository.locked():
            item = self.repository.ingest(self.repository.stage(self.package))
            self.repository.publish()
            (self.repository.root / item['upstream_filename']).write_bytes(b'corrupted')
            with self.assertRaisesRegex(repo.Error, 'failed verification'):
                self.repository.reapply('fixture-app')

    def test_malformed_and_traversing_policy_is_rejected(self):
        for policy in ({'url': None}, {'remove_vendor_apt': 'yes'}, {'remove_paths': ['/../../etc/passwd']},
                       {'drop_maintainer_scripts': ['../../postinst']}, {'remove_depends': ['libc6;id']},
                       {'shell_command': 'id'}, {'local_revision': True}):
            with self.subTest(policy=policy), self.assertRaises(repo.Error):
                repo.validate_policy(policy)

    def test_inspect_does_not_execute_package_script(self):
        package(self.package, script=b'#!/bin/sh\nexit 97 # apt-key\n')
        result = repo.inspect_policy_input(self.package, {'all'})
        self.assertTrue(result['maintainer_scripts']['postinst']['may_write_vendor_apt'])
        self.assertEqual(result['sha256'], repo.digest_file(self.package))

    def test_canonical_source_is_reconciled(self):
        with self.repository.locked():
            source = self.repository.source
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('Types: deb\nURIs: https://custom.test\nSuites: stable\n')
            self.repository.write_source()
            self.assertNotIn('custom.test', source.read_text())
            self.assertIn(f'Signed-By: {self.repository.keyring}\n', source.read_text())

    def test_global_vendor_hooks_are_not_shipped(self):
        self.assertFalse((TARGET / 'etc/dpkg/dpkg.cfg.d/94-local-apt-vendor-policy').exists())
        self.assertFalse((TARGET / 'usr/local/bin/apt-local-repo').exists())
        self.assertTrue((TARGET / 'usr/local/bin/local-apt-init').is_file())
        bridge = (TARGET / 'usr/local/libexec/local-apt-vendor').read_text()
        self.assertNotIn('policy-before', bridge)
        self.assertNotIn('policy-after', bridge)


if __name__ == '__main__':
    unittest.main()
