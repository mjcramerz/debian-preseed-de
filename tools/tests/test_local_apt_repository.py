#!/usr/bin/python3
"""Offline regression tests; assemble tiny fixture archives, never build software."""
import contextlib
import gzip
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[2] / 'd-i/forky/hooks/target/usr/local/libexec/local-apt-repository'
loader = importlib.machinery.SourceFileLoader('local_apt_repository', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
repo = importlib.util.module_from_spec(spec)
loader.exec_module(repo)


def fixture(path, version='1.0', package='fixture-app', arch='all', depends='libc6, libexample (>= 1) | libother, libextra:any'):
    control = {'Package': package, 'Version': version, 'Architecture': arch,
               'Maintainer': 'Offline Test <test@localhost>', 'Description': 'Offline repository fixture'}
    if depends:
        control['Depends'] = depends
    streams = []
    for name, data in [('control', repo.control_bytes(control)), ('usr/share/fixture-app/data', b'unchanged payload\n')]:
        target = io.BytesIO()
        with tarfile.open(fileobj=target, mode='w:', format=tarfile.GNU_FORMAT) as archive:
            member = tarfile.TarInfo('./' + name)
            member.size = len(data)
            member.mode = 0o644
            member.mtime = 0
            archive.addfile(member, io.BytesIO(data))
        streams.append(gzip.compress(target.getvalue(), mtime=0))
    with path.open('xb') as out:
        out.write(b'!<arch>\n')
        for name, data in [('debian-binary', b'2.0\n'), ('control.tar.gz', streams[0]), ('data.tar.gz', streams[1])]:
            out.write(repo.ar_header(name, len(data)))
            out.write(data)
            if len(data) % 2:
                out.write(b'\n')
    os.chmod(path, 0o600)
    return streams[1]


class RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Production paths reject writable ancestors. Use a root-owned private
        # test workspace under /var/tmp's parent, not the world-writable /tmp.
        cls.base = Path('/var/lib/local-apt-tests')
        cls.base.mkdir(mode=0o755, exist_ok=True)

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(dir=self.base))
        self.root = self.directory / 'software'
        self.etc = self.directory / 'etc'
        self.repository = repo.Repository(self.root, self.etc)
        self.package = self.directory / 'input.deb'
        self.payload = fixture(self.package)

    def tearDown(self):
        home = self.root / 'repository-signing'
        if home.exists():
            subprocess.run(['/usr/bin/gpgconf', '--homedir', str(home), '--kill', 'gpg-agent'], check=False, capture_output=True)
        shutil.rmtree(self.directory)

    def test_ingest_signed_indexes_and_no_nested_apt(self):
        with self.repository.locked():
            item = self.repository.ingest(self.repository.stage(self.package))
            self.repository.publish()
            self.assertTrue((self.repository.repo / item['filename']).is_file())
            self.assertFalse(list(self.repository.inbox.glob('*.deb')))
            self.assertIn('pool/', (self.repository.repo / 'Packages').read_text())
            self.assertEqual(gzip.decompress((self.repository.repo / 'Packages.gz').read_bytes()), (self.repository.repo / 'Packages').read_bytes())
            self.assertIn('Acquire-By-Hash: yes', (self.repository.repo / 'Release').read_text())
            self.assertIn('by-hash=force', self.repository.source.read_text())
            subprocess.run(['/usr/bin/gpgv', '--keyring', str(self.repository.keyring), str(self.repository.repo / 'InRelease')], check=True, capture_output=True)
            for parent in (self.repository.repo / item['filename']).parents:
                if parent == self.root:
                    break
                self.assertEqual(parent.stat().st_mode & 0o005, 0o005)
        source = SOURCE.read_text()
        self.assertNotIn('"/usr/bin/apt', source)
        self.assertNotIn('"--install"', source)

    def test_empty_repository_is_signed(self):
        with self.repository.locked():
            self.repository.publish()
            self.assertEqual((self.repository.repo / 'Packages').read_bytes(), b'')
            self.assertTrue((self.repository.repo / 'InRelease').is_file())

    def test_dependency_metadata_only(self):
        with self.repository.locked():
            record = self.repository.ingest(self.repository.stage(self.package),
                {'automatic': False, 'remove_depends': ['libexample', 'libextra'], 'local_revision': 1})
            self.repository.publish()
            self.assertEqual(record['version'], '1.0+localrepo1')
            self.assertEqual(record['control']['Depends'], 'libc6, libother')
            with (self.repository.repo / record['filename']).open('rb') as stream:
                for name, size, offset in repo.ar_members(stream):
                    if name == 'data.tar.gz':
                        stream.seek(offset)
                        self.assertEqual(stream.read(size), self.payload)

    def test_unknown_dependency_rejected(self):
        with self.assertRaises(repo.Error):
            repo.remove_dependencies('libc6, libother', ['not-present'])

    def test_reject_html_wrong_arch_and_identity(self):
        with self.repository.locked():
            html = self.directory / 'html.deb'
            html.write_text('<html>not a package</html>')
            for path in [html]:
                with self.assertRaises(repo.Error):
                    self.repository.ingest(self.repository.stage(path))
            with self.assertRaises(repo.Error):
                self.repository.ingest(self.repository.stage(self.package), expected=('other-package', 'all'))
            wrong = self.directory / 'wrong.deb'
            fixture(wrong, arch='not-a-real-arch')
            with self.assertRaises(repo.Error):
                self.repository.ingest(self.repository.stage(wrong))

    def test_atomic_signing_failure_retains_previous_generation(self):
        with self.repository.locked():
            self.repository.ingest(self.repository.stage(self.package))
            self.repository.publish()
            before = os.readlink(self.repository.repo / 'current')
            second = self.directory / 'new.deb'
            fixture(second, version='2.0')
            incoming = self.repository.stage(second)
            self.repository.ingest(incoming)
            original = repo.run
            def fail_signing(argv, **kwargs):
                if '--clearsign' in argv:
                    raise repo.Error('injected signature failure')
                return original(argv, **kwargs)
            with mock.patch.object(repo, 'run', side_effect=fail_signing):
                with self.assertRaises(repo.Error):
                    self.repository.publish()
            self.assertEqual(os.readlink(self.repository.repo / 'current'), before)
            self.assertTrue(incoming.exists())
            self.assertIn('Version: 1.0\n', (self.repository.repo / 'Packages').read_text())

    def test_reject_same_version_changed_bytes_and_downgrade(self):
        with self.repository.locked():
            self.repository.ingest(self.repository.stage(self.package))
            self.repository.publish()
            for version, depends in [('1.0', 'libchanged'), ('0.9', 'libc6')]:
                path = self.directory / (version + '.deb')
                fixture(path, version=version, depends=depends)
                with self.assertRaises(repo.Error):
                    self.repository.ingest(self.repository.stage(path))
            self.assertEqual(self.repository.catalog['packages']['fixture-app:all']['version'], '1.0')

    def test_static_package_never_downloads(self):
        with self.repository.locked():
            self.repository.ingest(self.repository.stage(self.package), {'automatic': False, 'url': 'https://example.test/pkg'})
            self.repository.publish()
            with mock.patch.object(repo, 'download', side_effect=AssertionError('unexpected network')):
                self.repository.refresh()

    def test_delete_publishes_empty_keeps_cached_pool(self):
        with self.repository.locked():
            item = self.repository.ingest(self.repository.stage(self.package))
            self.repository.publish()
            with mock.patch('builtins.input', return_value='1'):
                repo.interactive_delete(self.repository)
            self.assertEqual((self.repository.repo / 'Packages').read_bytes(), b'')
            self.assertTrue((self.repository.repo / item['filename']).exists())
            self.assertIn('fixture-app:all', self.repository.catalog['disabled_seeds'])

    def test_https_only(self):
        for value in ['http://example.test/a', 'https://u:p@example.test/a', 'https://example.test/a\n', 'file:///etc/passwd']:
            with self.assertRaises(repo.Error):
                repo.https_url(value)
        self.assertEqual(repo.https_url('https://example.test/raw?id=1'), 'https://example.test/raw?id=1')

    def test_release_asset_urls_discover_project_releases(self):
        for url, kind, expected in [
            ('https://github.com/team/app/releases/download/v1.0/fixture-app_1.0_amd64.deb', 'github',
             'https://api.github.com/repos/team/app/releases?per_page=100'),
            ('https://gitlab.example.test/team/app/-/releases/v1.0/downloads/fixture-app_1.0_amd64.deb', 'gitlab',
             'https://gitlab.example.test/api/v4/projects/team%2Fapp/releases?per_page=100&order_by=released_at&sort=desc'),
            ('https://sourceforge.net/projects/app/files/1.0/fixture-app_1.0_amd64.deb/download', 'sourceforge',
             'https://sourceforge.net/projects/app/rss?path=/&limit=100'),
        ]:
            source = repo.source_for(url)
            self.assertEqual(source['kind'], kind)
            self.assertEqual(source['url'], expected)
            self.assertEqual(source['family'], 'fixture-app_{version}_amd64.deb')
        raw = 'https://example.test/raw?id=1'
        self.assertEqual(repo.source_for(raw), {'kind': 'direct', 'url': raw})

    def test_release_api_urls_and_malformed_metadata(self):
        for url, kind in [
            ('https://api.github.com/repos/team/app/releases/tags/v1.0', 'github'),
            ('https://gitlab.example.test/api/v4/projects/team%2Fapp/releases/v1.0', 'gitlab'),
        ]:
            source = repo.source_for(url)
            self.assertEqual(source['kind'], kind)
            self.assertIn('/releases?per_page=100', source['url'])
        source = repo.source_for('https://github.com/team/app/releases/latest')
        for document in [{}, [None], [{'tag_name': 'v1.0', 'published_at': '2026-01-01T00:00:00Z', 'assets': 'invalid'}]]:
            with mock.patch.object(self.repository.discovery, 'metadata', return_value=json.dumps(document).encode()):
                with self.assertRaises(repo.Error):
                    self.repository.discovery.release(source, 'fixture-app', 'amd64', self.directory)

    def test_prebuilt_payload_archival_preserves_bytes_and_hardlinks(self):
        tree = self.directory / 'prebuilt'
        tree.mkdir()
        binary = tree / 'AppRun'
        binary.write_bytes(b'prebuilt-payload-bytes\0not-executed')
        binary.chmod(0o6755)
        os.link(binary, tree / 'hardlink')
        (tree / 'symlink').symlink_to('AppRun')
        repo.normalize_staged_tree(tree)
        self.assertEqual(binary.stat().st_mode & 0o7777, 0o755)
        output = self.directory / 'vendor.deb'
        fields = {'Package': 'fixture-app', 'Version': '1.0+localrepo1', 'Architecture': 'amd64',
                  'Maintainer': 'Offline Test <test@localhost>', 'Description': 'Prebuilt fixture'}
        repo.assemble_binary_package(output, tree, '/opt/fixture-app', fields,
                                     {'tuta.installed.sha256': 'a' * 64 + '\n'}, 'tuta')
        self.assertEqual(repo.inspect_deb(output, {'amd64', 'all'})['Version'], '1.0+localrepo1')
        with output.open('rb') as stream:
            for name, size, offset in repo.ar_members(stream):
                if name == 'data.tar.xz':
                    stream.seek(offset)
                    with tarfile.open(fileobj=io.BytesIO(stream.read(size)), mode='r:xz') as archive:
                        item = archive.getmember('./opt/fixture-app/AppRun')
                        self.assertEqual(item.mode, 0o755)
                        self.assertEqual(archive.extractfile(item).read(), binary.read_bytes())
                        self.assertTrue(archive.getmember('./opt/fixture-app/hardlink').islnk())
                        self.assertTrue(archive.getmember('./opt/fixture-app/symlink').issym())

    def test_prebuilt_payload_escape_rejected(self):
        tree = self.directory / 'unsafe-tree'
        tree.mkdir()
        (tree / 'escape').symlink_to('/etc/passwd')
        with self.assertRaises(repo.Error):
            repo.assemble_binary_package(self.directory / 'unsafe-vendor.deb', tree,
                                         '/opt/fixture-app', {}, {}, 'tuta')

    def test_symlink_source_and_symlink_root_rejected(self):
        link = self.directory / 'link.deb'
        link.symlink_to(self.package)
        with self.repository.locked():
            with self.assertRaises(OSError):
                self.repository.stage(link)
        unsafe = self.directory / 'unsafe'
        unsafe.symlink_to(self.root)
        with self.assertRaises(repo.Error):
            with repo.Repository(unsafe, self.etc).locked():
                pass


if __name__ == '__main__':
    unittest.main(verbosity=2)
