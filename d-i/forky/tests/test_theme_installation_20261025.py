#!/usr/bin/python3
"""Unexecuted fixtures for offline theme publication and provider preflight.

Repository policy forbids running these fixtures. All prospective filesystem
work is confined to the explicitly owned tree; package discovery is mocked.
"""
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import contextlib
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

LIB = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/lib/python3.14/dist-packages'
_isolation_sys.path.insert(0, str(LIB))
from managed_workflows.fs import Tree
from labwc_appearance import theme_archive, theme_assets, theme_install, themes
from labwc_managed_app import mounts


class ArchiveBoundsFixtures(unittest.TestCase):
    def archive(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('theme/gtk-3.0/gtk.css', b'window {}')
            archive.writestr('theme/gtk-4.0/gtk.css', b'window {}')
        return bytearray(output.getvalue())

    def reject_before_member_allocation(self, blob, message):
        with mock.patch.object(theme_archive.zipfile, 'ZipFile') as reader, \
                mock.patch.object(theme_archive.time, 'monotonic', return_value=0), \
                self.assertRaisesRegex(ValueError, message):
            theme_archive.Archive(bytes(blob), 'fixture.zip', deadline=1)
        reader.assert_not_called()

    def test_understated_member_count_is_rejected_before_zipinfo_allocation(self):
        blob = self.archive()
        end = blob.rfind(b'PK\x05\x06')
        struct.pack_into('<2H', blob, end + 8, 1, 1)
        self.reject_before_member_allocation(blob, 'count mismatch')

    def test_truncated_central_record_is_rejected_before_zipinfo_allocation(self):
        blob = self.archive()
        central = blob.index(b'PK\x01\x02')
        struct.pack_into('<H', blob, central + 30, 65535)
        self.reject_before_member_allocation(blob, 'truncated')

    def test_unaccounted_directory_bytes_are_rejected_before_zipinfo_allocation(self):
        blob = self.archive()
        end = blob.rfind(b'PK\x05\x06')
        size = struct.unpack_from('<I', blob, end + 12)[0]
        struct.pack_into('<I', blob, end + 12, size - 1)
        self.reject_before_member_allocation(blob, 'supported bounds')

    def test_valid_central_directory_preserves_regular_asset_bytes(self):
        with mock.patch.object(theme_archive.time, 'monotonic', return_value=0):
            archive = theme_archive.Archive(bytes(self.archive()), 'fixture.zip', deadline=1)
            self.assertEqual(archive.read('theme/gtk-3.0/gtk.css'), b'window {}')
            self.assertEqual(archive.read('theme/gtk-4.0/gtk.css'), b'window {}')

    def xz_reader(self):
        reader = object.__new__(theme_archive.Archive)
        reader.deadline = 1
        return reader

    def test_xz_dictionary_memory_is_bounded_independently_of_output(self):
        blob = lzma.compress(b'fixture data')
        with mock.patch.object(theme_archive.time, 'monotonic', return_value=0), \
                mock.patch.object(theme_archive, 'MAX_DECODER_MEMORY', 1024), \
                self.assertRaisesRegex(ValueError, 'decoder memory limit'):
            self.xz_reader()._expand_xz(blob)

    def test_xz_concatenation_and_padding_preserve_all_stream_bytes(self):
        blob = lzma.compress(b'first') + b'\x00' * 4 + lzma.compress(b'second') + b'\x00' * 8
        with mock.patch.object(theme_archive.time, 'monotonic', return_value=0):
            self.assertEqual(self.xz_reader()._expand_xz(blob), b'firstsecond')

    def test_xz_truncation_and_output_overflow_fail_before_tar_parsing(self):
        blob = lzma.compress(b'123456789')
        with mock.patch.object(theme_archive.time, 'monotonic', return_value=0):
            with self.assertRaisesRegex(ValueError, 'truncated'):
                self.xz_reader()._expand_xz(blob[:-1])
            with mock.patch.object(theme_archive, 'MAX_ARCHIVE', 8), \
                    self.assertRaisesRegex(ValueError, 'size limit'):
                self.xz_reader()._expand_xz(blob)

    def test_zip_lzma_member_is_rejected_before_decoder_allocation(self):
        blob = self.archive()
        central = blob.index(b'PK\x01\x02')
        struct.pack_into('<H', blob, central + 10, zipfile.ZIP_LZMA)
        with mock.patch.object(theme_archive.time, 'monotonic', return_value=0), \
                mock.patch.object(theme_archive.zipfile.ZipFile, 'open') as opened, \
                self.assertRaisesRegex(ValueError, 'unsupported compressed'):
            theme_archive.Archive(bytes(blob), 'fixture.zip', deadline=1)
        opened.assert_not_called()


@unittest.skipUnless(os.geteuid() == 0, 'Fixture metadata models the root installer')
class PublicationFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='theme-publication-fixture-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = self.root / 'registry'
        self.inputs = self.registry / '.installer-themes'
        self.public = self.root / 'public'
        self.inputs.mkdir(parents=True, mode=0o700)
        self.public.mkdir(mode=0o755)
        self.registry.chmod(0o755)
        self.candidate = theme_assets.Candidate()
        self.destination = 'themes/Labwc-fixture-dark'
        self.candidate.add(self.destination, {'gtk-3.0/gtk.css': b'window { color:#abc; }',
                                              'gtk-4.0/gtk.css': b'window { color:#abc; }'})
        self.candidate.variants = {'fixture-dark': (self.destination,)}
        raw = b'fixture license data\n'
        with Tree(self.inputs, uid=0, private=True) as source:
            source.write('licenses/fixture.txt', raw)
            source.put_json('sources.json', {'schema': 1, 'files': {'licenses/fixture.txt': {
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}})
            source.write('.files.list', b'licenses/fixture.txt\n')
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in (('REGISTRY', self.registry), ('SOURCE', self.inputs), ('PUBLIC', self.public)):
            self.stack.enter_context(mock.patch.object(theme_install, key, value))
        self.stack.enter_context(mock.patch.object(theme_install, 'dependencies', return_value={}))
        self.stack.enter_context(mock.patch.object(theme_install, 'prepare', return_value=self.candidate))
        def fixture_tree(path, *args, **kwargs):
            # No ambient HOME, package database, /usr, service or device access.
            if Path(path) not in (self.registry, self.inputs, self.public):
                raise AssertionError('fixture attempted a non-owned filesystem root')
            return Tree(path, *args, **kwargs)
        self.stack.enter_context(mock.patch.object(theme_install, 'Tree', side_effect=fixture_tree))

    def pending(self):
        return json.loads((self.registry / theme_install.PENDING).read_bytes())

    def test_success_publishes_complete_data_and_removes_only_verified_inputs(self):
        self.assertEqual(theme_install.main(['--install']), 0)
        self.assertFalse(self.inputs.exists())
        self.assertFalse((self.registry / theme_install.PENDING).exists())
        inventory = json.loads((self.registry / theme_install.INVENTORY).read_bytes())
        for path, metadata in inventory['files'].items():
            data = (self.public / path).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), metadata['sha256'])
        self.assertFalse(list(self.public.rglob('.labwc-theme-stage-*')))

    def test_failure_before_publication_retains_candidate_and_previous_inventory(self):
        previous = b'{"fixture":"previous"}\n'
        (self.registry / theme_install.INVENTORY).write_bytes(previous)
        original = Tree.write
        def interrupted(tree, path, data, **options):
            if tree.root == self.public and path.endswith('gtk.css'):
                raise OSError('fixture staged write failure')
            return original(tree, path, data, **options)
        with mock.patch.object(Tree, 'write', interrupted), self.assertRaisesRegex(RuntimeError, 'before publication'):
            theme_install.main(['--install'])
        self.assertEqual((self.registry / theme_install.INVENTORY).read_bytes(), previous)
        self.assertFalse((self.public / self.destination).exists())
        self.assertEqual(self.pending()['phase'], 'preparing')
        self.assertTrue(self.inputs.is_dir())

    def test_missing_asset_preparation_failure_preserves_inputs_and_previous_inventory(self):
        previous = b'{"fixture":"previous"}\n'
        (self.registry / theme_install.INVENTORY).write_bytes(previous)
        with mock.patch.object(theme_install, 'prepare', side_effect=ValueError('vendor theme refers to a missing local asset')), \
                self.assertRaisesRegex(ValueError, 'missing local asset'):
            theme_install.main(['--install'])
        self.assertEqual((self.registry / theme_install.INVENTORY).read_bytes(), previous)
        self.assertTrue(self.inputs.is_dir())
        self.assertFalse((self.public / self.destination).exists())
        self.assertFalse((self.registry / theme_install.PENDING).exists())
        self.assertEqual(list(self.public.iterdir()), [])

    def test_rename_lost_reply_is_unknown_and_never_retried(self):
        rename = os.rename
        def lost_reply(source, destination, **options):
            rename(source, destination, **options)
            if destination == 'Labwc-fixture-dark':
                raise OSError('fixture lost publication reply')
        with mock.patch.object(theme_install.os, 'rename', side_effect=lost_reply), self.assertRaises(theme_install.OutcomeUnknown):
            theme_install.main(['--install'])
        self.assertTrue((self.public / self.destination).is_dir())
        self.assertFalse((self.registry / theme_install.INVENTORY).exists())
        self.assertEqual(self.pending()['phase'], 'publishing')
        with mock.patch.object(theme_install, 'prepare') as prepare, self.assertRaises(theme_install.OutcomeUnknown):
            theme_install.main(['--install'])
        prepare.assert_not_called()

    def test_destination_appearing_during_staging_is_preserved(self):
        put = Tree.put_json
        foreign = self.public / self.destination
        def concurrent(tree, path, value, **options):
            if tree.root == self.registry and path == theme_install.PENDING and value['phase'] == 'publishing':
                foreign.mkdir()
                (foreign / 'foreign.txt').write_bytes(b'concurrent data')
            return put(tree, path, value, **options)
        with mock.patch.object(Tree, 'put_json', concurrent), self.assertRaisesRegex(RuntimeError, 'before publication'):
            theme_install.main(['--install'])
        self.assertEqual((foreign / 'foreign.txt').read_bytes(), b'concurrent data')
        self.assertFalse((self.registry / theme_install.INVENTORY).exists())
        self.assertTrue(self.pending()['identities'])

    def test_staged_directory_identity_replacement_prevents_publication(self):
        put = Tree.put_json
        def substituted(tree, path, value, **options):
            if tree.root == self.registry and path == theme_install.PENDING and value['phase'] == 'publishing':
                stage = self.public / value['stages']['themes'] / 'Labwc-fixture-dark'
                stage.rename(stage.with_name('retained-original'))
                stage.mkdir(mode=0o755)
            return put(tree, path, value, **options)
        with mock.patch.object(Tree, 'put_json', substituted), self.assertRaisesRegex(RuntimeError, 'before publication'):
            theme_install.main(['--install'])
        self.assertFalse((self.public / self.destination).exists())
        self.assertTrue(self.pending()['identities'])

    def test_cleanup_failure_is_distinct_from_unknown_publication(self):
        with mock.patch.object(theme_install, 'remove_inputs', side_effect=OSError('fixture cleanup failure')), \
                self.assertRaises(theme_install.CleanupPending):
            theme_install.main(['--install'])
        self.assertEqual(self.pending()['phase'], 'committed')
        self.assertTrue((self.registry / theme_install.INVENTORY).is_file())
        self.assertTrue((self.public / self.destination / 'gtk-4.0/gtk.css').is_file())
        self.assertTrue(self.inputs.is_dir())

    def test_expired_operation_stops_before_publication(self):
        with mock.patch.object(theme_install.time, 'monotonic', side_effect=(0, 601)), self.assertRaises(TimeoutError):
            theme_install.main(['--install'])
        self.assertFalse((self.public / self.destination).exists())
        self.assertTrue(self.inputs.is_dir())


class InstalledProviderFixtures(unittest.TestCase):
    def test_preflight_reads_only_chosen_root_owned_provider_and_qt6_plugins(self):
        theme = themes.variant('arc-dark')
        payload = {
            'themes/' + theme.gtk + '/gtk-' + v + '/gtk.css': b'window { color:#fff; }'
            for v in ('3.0', '4.0')}
        payload.update({'Kvantum/' + theme.kvantum + '/' + theme.kvantum + ext: b'fixture Qt data'
                        for ext in ('.kvconfig', '.svg')})
        plugins = {'lib/fixture-linux-gnu/qt6/plugins/' + path: b'\x7fELFfixture'
                   for path in ('styles/libkvantum.so', 'platformthemes/libqt6ct.so')}
        manifest = {'schema': 1, 'variants': dict.fromkeys(themes.VARIANTS, []),
                    'files': {p: {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
                              for p, b in payload.items()},
                    'packages': {'multiarch': 'fixture-linux-gnu', 'plugins': {
                        p: hashlib.sha256(b).hexdigest() for p, b in plugins.items()}}}
        manifest['variants'][theme.identity] = ['themes/' + theme.gtk, 'Kvantum/' + theme.kvantum]
        roots = {'/usr/local/share/labwc-appearance': {'themes.json': json.dumps(manifest).encode()},
                 '/usr/share': payload, '/usr': plugins}
        reads = []
        class ReadOnlyFixture:
            def __init__(self, root, *, uid):
                if uid != 0 or str(root) not in roots:
                    raise AssertionError('unexpected provider root')
                self.root = str(root)
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, path, *, limit=8 * 1024**2, missing=False):
                reads.append((self.root, path))
                if missing and path not in roots[self.root]: return None
                blob = roots[self.root][path]
                if len(blob) > limit: raise ValueError('fixture read exceeds limit')
                return blob
        with mock.patch.object(themes, 'Tree', ReadOnlyFixture):
            themes.require_installed(theme.identity)
            self.assertEqual(set(p for r, p in reads if r == '/usr/share'), set(payload))
            payload[next(iter(payload))] = b'changed asset'
            with self.assertRaisesRegex(ValueError, 'assets changed'):
                themes.require_installed(theme.identity)


class QtThemeMountFixtures(unittest.TestCase):
    def test_qt6_palette_absolute_path_and_payload_home_share_only_readonly_theme_directories(self):
        command = []
        with mock.patch.object(mounts, 'resolve_optional_home_relative_directory',
                               side_effect=lambda home, relative: home + '/' + relative) as resolve:
            mounts.add_qt_theme_directory_binds(command, '/fixture/desktop', '/home/user')
        binds = [command[index + 1:index + 3] for index, value in enumerate(command) if value == '--ro-bind']
        self.assertEqual(binds, [
            ['/fixture/desktop/.config/qt6ct', '/home/user/.config/qt6ct'],
            ['/fixture/desktop/.config/qt6ct', '/fixture/desktop/.config/qt6ct'],
            ['/fixture/desktop/.config/Kvantum', '/home/user/.config/Kvantum'],
        ])
        self.assertEqual(resolve.call_args_list, [mock.call('/fixture/desktop', '.config/qt6ct'),
                                                 mock.call('/fixture/desktop', '.config/Kvantum')])
        self.assertNotIn('--bind', command)


if __name__ == '__main__':
    unittest.main()
