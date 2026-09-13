#!/usr/bin/python3
"""Source normalization in a private filesystem; no APT/network operations."""
import importlib.machinery
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'd-i/forky/hooks/target/usr/local/libexec/local-apt-normalize-sources'
loader = importlib.machinery.SourceFileLoader('apt_vendor_normalize', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
normalizer = importlib.util.module_from_spec(spec)
loader.exec_module(normalizer)


class Deb822RepairTests(unittest.TestCase):
    def parse(self, text):
        repairs = []
        return normalizer.deb822(text, repairs.append), repairs

    def test_duplicate_fields_are_collapsed_without_losing_multivalue_options(self):
        records, repairs = self.parse(
            'Types: deb\n'
            'URIs: https://repo.test\n'
            'Suites: stable\n'
            'Components: main\n'
            'Components: contrib main\n'
            'Signed-By: /etc/apt/keyrings/one.gpg\n'
            'Signed-By: /etc/apt/keyrings/two.gpg\n'
            'Enabled: yes\n'
            'Enabled: no\n'
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['components'], 'main contrib')
        self.assertEqual(
            records[0]['signed-by'],
            '/etc/apt/keyrings/two.gpg',
        )
        self.assertEqual(records[0]['enabled'], 'no')
        self.assertEqual(sum('collapsed duplicate field' in item for item in repairs), 3)

    def test_common_malformed_field_syntax_is_repaired_and_garbage_is_discarded(self):
        records, repairs = self.parse(
            ' Types: deb\n'
            'URIs = https://repo.test\n'
            'Suites stable\n'
            ' Components: main\n'
            'not-a-field\n'
        )
        self.assertEqual(records, [{
            'types': 'deb',
            'uris': 'https://repo.test',
            'suites': 'stable',
            'components': 'main',
        }])
        self.assertTrue(any('repaired field separator for Types' in item for item in repairs))
        self.assertTrue(any('repaired field separator for URIs' in item for item in repairs))
        self.assertTrue(any('repaired field separator for Suites' in item for item in repairs))
        self.assertTrue(any('removed indentation from field Components' in item for item in repairs))
        self.assertTrue(any('discarded irrecoverable non-field content' in item for item in repairs))

    def test_repeated_types_repairs_a_missing_stanza_separator(self):
        records, repairs = self.parse(
            'Types: deb\nURIs: https://one.test\nSuites: stable\n'
            'Types: deb\nURIs: https://two.test\nSuites: testing\n'
        )
        self.assertEqual([record['uris'] for record in records], ['https://one.test', 'https://two.test'])
        self.assertTrue(any('inserted missing stanza separator' in item for item in repairs))


class VendorSourcesTests(unittest.TestCase):
    def setUp(self):
        base = Path('/var/lib/local-apt-tests')
        base.mkdir(mode=0o755, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=base))
        self.parts = self.root / 'etc/apt/sources.list.d'
        self.parts.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, name, text):
        path = self.parts / name
        path.write_text(text)
        return path

    def test_requested_vendors_and_edge_deduplication(self):
        edge = 'deb [signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main\n'
        self.write('edge-stable.list', edge)
        self.write('microsoft-edge.sources', 'Types: deb\nURIs: https://packages.microsoft.com/repos/edge/\nSuites: stable\nComponents: main\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/microsoft.gpg\n')
        self.write('code-stable.list', 'deb https://packages.microsoft.com/repos/code stable main\n')
        self.write('microsoft-debian-trixie-prod-trixie.list', 'deb https://packages.microsoft.com/debian/13/prod trixie main\n')
        self.write('local-apt-repository.sources', 'Types: deb\nURIs: file:/var/lib/software/repo\nSuites: ./\nSigned-By: /etc/apt/keyrings/local-apt-repository.gpg\nBy-Hash: force\n')
        self.write('misc.list', '\n'.join([
            'deb http://deb.debian.org/debian forky main non-free-firmware',
            'deb https://repo.vivaldi.com/stable/deb stable main',
            'deb https://mise.jdx.dev/deb stable main',
            'deb https://deb.xanmod.org releases main',
            'deb https://repository.mullvad.net/deb/stable stable main',
        ]) + '\n')
        names = normalizer.normalize(self.root)
        self.assertEqual(names, ['debian.sources', 'local-apt-repository.sources', 'microsoft.sources', 'mise.sources', 'mullvad.sources', 'vivaldi.sources', 'xanmod.sources'])
        self.assertTrue((self.parts / 'local-apt-repository.sources').is_file())
        self.assertIn('Signed-By: /etc/apt/keyrings/local-apt-repository.gpg\n', (self.parts / 'local-apt-repository.sources').read_text())
        microsoft = (self.parts / 'microsoft.sources').read_text()
        self.assertEqual(microsoft.count('URIs: https://packages.microsoft.com/repos/edge\n'), 1)
        self.assertNotIn('Architectures:', microsoft)
        self.assertEqual(len(list(self.parts.iterdir())), 7)
        self.assertIn('https://deb.debian.org/debian', (self.parts / 'debian.sources').read_text())
        self.assertTrue(list((self.root / 'var/lib/apt/source-normalization').iterdir()))
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.parts.iterdir()}
        self.assertEqual(normalizer.normalize(self.root), names)
        self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.parts.iterdir()})

    def test_multi_uri_suite_type_options_are_preserved(self):
        self.write('mixed.sources', 'Types: deb deb-src\nURIs: https://deb.debian.org/debian https://mirror.example.test/debian\nSuites: forky forky-updates\nComponents: main contrib\nArchitectures: amd64 arm64\nEnabled: no\nCheck-Valid-Until: no\n')
        normalizer.normalize(self.root)
        records = [item for path in self.parts.iterdir() for item in normalizer.deb822(path.read_text())]
        self.assertEqual(len(records), 8)
        self.assertTrue(all(record['enabled'] == 'no' and record['check-valid-until'] == 'no' for record in records))
        self.assertTrue(all(record['architectures'] == 'amd64 arm64' for record in records))

    def test_equal_key_bytes_different_paths_are_deduplicated(self):
        directory = self.root / 'etc/apt/keyrings'
        directory.mkdir()
        for name in ('old.gpg', 'new.gpg'):
            (directory / name).write_bytes(b'identical test key bytes')
            self.write(name + '.list', 'deb [signed-by=/etc/apt/keyrings/' + name + '] https://packages.microsoft.com/repos/edge stable main\n')
        normalizer.normalize(self.root)
        stanzas = normalizer.deb822((self.parts / 'microsoft.sources').read_text())
        self.assertEqual(len(stanzas), 1)
        self.assertEqual(stanzas[0]['signed-by'], '/etc/apt/keyrings/new.gpg')

    def test_conflicting_keys_across_components_abort_before_writes(self):
        for name, component in (('one', 'main'), ('two', 'contrib')):
            self.write(name + '.list', f'deb [signed-by=/etc/apt/keyrings/{name}.gpg] https://repo.test stable {component}\n')
        before = {path.name: path.read_bytes() for path in self.parts.iterdir()}
        with self.assertRaisesRegex(normalizer.Error, 'conflicting Signed-By'):
            normalizer.normalize(self.root)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.parts.iterdir()})

    def test_architecture_union_does_not_invent_component_cross_product(self):
        self.write('input.list', 'deb [arch=amd64] https://repo.test stable main\ndeb [arch=arm64] https://repo.test stable main\ndeb [arch=armhf] https://repo.test stable contrib\n')
        normalizer.normalize(self.root)
        records = normalizer.deb822(next(self.parts.glob('*.sources')).read_text())
        self.assertEqual({r['components']: r['architectures'] for r in records}, {'main': 'amd64 arm64', 'contrib': 'armhf'})

    def test_disabled_lines_comments_and_modernize_backups_are_archived(self):
        original = '# operator comment\n# deb https://disabled.test stable main\ndeb https://active.test stable main\n'
        self.write('input.list', original)
        self.write('input.list.bak', 'exact backup\n')
        normalizer.normalize(self.root)
        self.assertFalse((self.parts / 'input.list.bak').exists())
        contents = [p.read_text() for p in (self.root / 'var/lib/apt/source-normalization').iterdir()]
        self.assertIn(original, contents)
        self.assertIn('exact backup\n', contents)

    def test_source_symlink_is_rejected(self):
        path = self.root / 'target'
        path.write_text('deb https://test.test stable main\n')
        (self.parts / 'unsafe.list').symlink_to(path)
        with self.assertRaises(OSError):
            normalizer.normalize(self.root)
        self.assertEqual(path.read_text(), 'deb https://test.test stable main\n')

    def test_unsafe_inactive_backup_is_checked_before_active_writes(self):
        active = self.write('old.list', 'deb https://test.test stable main\n')
        (self.parts / 'old.list.bak').symlink_to(active)
        with self.assertRaises(OSError):
            normalizer.normalize(self.root)
        self.assertTrue(active.exists())
        self.assertFalse(list(self.parts.glob('*.sources')))

    def test_inline_signed_by_preserved(self):
        self.write('inline.sources', 'Types: deb\nURIs: https://repo.test\nSuites: stable\nComponents: main\nSigned-By:\n -----BEGIN PGP PUBLIC KEY BLOCK-----\n .\n example\n -----END PGP PUBLIC KEY BLOCK-----\n')
        normalizer.normalize(self.root)
        stanza = normalizer.deb822(next(self.parts.glob('*.sources')).read_text())[0]
        self.assertIn('\n .\n', stanza['signed-by'])

    def test_malformed_and_duplicate_deb822_is_rewritten_instead_of_aborting(self):
        self.write(
            'broken.sources',
            ' Types: deb\n'
            'URIs = https://repo.test\n'
            'Suites stable\n'
            'Components: main\n'
            'Components: contrib\n'
            'not-a-field\n\n'
            'Types: deb\nBroken: incomplete\n',
        )
        self.assertEqual(normalizer.normalize(self.root), ['test.sources'])
        records = normalizer.deb822((self.parts / 'test.sources').read_text())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['components'], 'contrib main')
        self.assertEqual(records[0]['uris'], 'https://repo.test')


if __name__ == '__main__':
    unittest.main()
