"""Payload inventory, paired freshness and publication failure fixtures."""
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[2] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import json
import hashlib
import io
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest
from unittest import mock

import inventory
import inventory_apt


class InventoryContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.seed = self.root / 'd-i/forky'
        self.seed.mkdir(parents=True)

    def source(self, name, text):
        path = self.seed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def payload(self, *names):
        with tarfile.open(self.seed / 'payload.tar.gz', mode='w:gz', format=tarfile.USTAR_FORMAT) as archive:
            for name in names:
                data = (self.seed / name).read_bytes()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def metadata(self, root, apt, payload):
        declarations = [{key: row[key] for key in ('id', 'url', 'suite', 'components', 'architectures', 'index_urls', 'release_url')}
                        for row in apt['repositories']]
        return {'schema_version': 3, 'schema': {'name': 'debian-apt-metadata', 'version': 3},
                'payload': payload, 'errors': [], 'release_files': {}, 'package_indexes': [],
                'repository_definitions_sha256': hashlib.sha256(json.dumps(declarations, sort_keys=True).encode()).hexdigest(),
                'request_set': {'packages': apt['packages']}, 'candidates': {'record_count': 0, 'records': []}}

    def publish_pair(self, **kwargs):
        with mock.patch.object(inventory_apt, 'refresh', side_effect=self.metadata):
            return inventory.publish(self.root, refresh_apt=True, **kwargs)

    def test_payload_hash_fast_path_skips_scan_and_network_and_preserves_both_outputs(self):
        profile = self.source('hosts/profiles/one.env', 'VERSION="1.2.3"\nAPP_URL="https://example.org/${VERSION}/app-${VERSION}.zip"\n')
        self.source('scripts/install.sh', 'curl --url "$APP_URL"\n')
        self.payload('hosts/profiles/one.env', 'scripts/install.sh')
        first = self.publish_pair()
        self.assertEqual(first['text_files_scanned'], 2)
        outputs = [self.root / name for name in ('inventory.json', 'inventory-apt.json')]
        previous = [(p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in outputs]
        with mock.patch.object(inventory, 'scan_payload', side_effect=AssertionError('unchanged payload rescanned')), \
                mock.patch.object(inventory_apt, 'refresh', side_effect=AssertionError('unchanged payload refreshed')):
            second = inventory.publish(self.root, refresh_apt=True)
        self.assertFalse(second['written'])
        self.assertTrue(second['current'])
        self.assertEqual(previous, [(p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in outputs])
        profile.write_text(profile.read_text().replace('1.2.3', '2.0.0'))
        self.assertTrue(self.publish_pair()['current'])
        self.payload('hosts/profiles/one.env', 'scripts/install.sh')
        changed = self.publish_pair()
        self.assertFalse(changed['current'])
        value = json.loads(outputs[0].read_bytes())
        self.assertIn('https://example.org/2.0.0/app-2.0.0.zip', [row['url'] for row in value['external_artifacts']])
        for key in ('source_hashes', '_scan_cache', '_discovery_hashes'):
            self.assertNotIn(key, value)

    def test_changed_payload_reaggregates_cross_file_url_definitions(self):
        version = self.source('hosts/installer/runtime.env', 'APP_VERSION=1\n')
        self.source('scripts/fetch.sh', 'APP_URL="https://example.org/${APP_VERSION}/app.zip"\n')
        self.payload('hosts/installer/runtime.env', 'scripts/fetch.sh')
        inventory.publish(self.root)
        version.write_text('APP_VERSION=2\n')
        self.payload('hosts/installer/runtime.env', 'scripts/fetch.sh')
        inventory.publish(self.root)
        value = json.loads((self.root / 'inventory.json').read_bytes())
        self.assertIn('https://example.org/2/app.zip', [row['url'] for row in value['external_artifacts']])

    def test_only_payload_members_are_scanned_even_if_loose_sources_and_manifest_differ(self):
        self.source('scripts/fetch.sh', 'APP_URL=https://example.org/archive.zip\n')
        self.source('common.cfg', 'd-i pkgsel/include string curl\n')
        self.payload('scripts/fetch.sh', 'common.cfg')
        inventory.publish(self.root)
        self.payload('common.cfg')
        (self.seed / 'payload.manifest').write_text('untrusted  scripts/fetch.sh\n')
        inventory.publish(self.root)
        value = json.loads((self.root / 'inventory.json').read_bytes())
        self.assertEqual(value['external_artifacts'], [])

    def test_loose_sources_are_never_opened(self):
        self.source('common.cfg', 'd-i pkgsel/include string curl\n')
        unrelated = self.source('hooks/target/etc/example.conf', 'Color=blue\n')
        self.payload('common.cfg', 'hooks/target/etc/example.conf')
        inventory.publish(self.root)
        output = self.root / 'inventory.json'
        previous = output.stat()
        unrelated.write_text('Color=green\n')
        (self.seed / 'common.cfg').unlink()
        result = inventory.publish(self.root)
        self.assertFalse(result['written'])
        self.assertEqual((previous.st_ino, previous.st_mtime_ns), (output.stat().st_ino, output.stat().st_mtime_ns))

    def test_private_traversal_and_duplicate_members_are_rejected(self):
        for member in ['../../private', '/etc/passwd', 'hosts/preseed.env', 'a//b', 'a/./b']:
            with self.subTest(member=member), self.assertRaises(ValueError):
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode='w:gz', format=tarfile.USTAR_FORMAT) as archive:
                    archive.addfile(tarfile.TarInfo(member))
                inventory.scan_payload(buffer.getvalue())
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz', format=tarfile.USTAR_FORMAT) as archive:
            archive.addfile(tarfile.TarInfo('same'))
            archive.addfile(tarfile.TarInfo('same'))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            inventory.scan_payload(buffer.getvalue())

    def test_symbolic_link_member_cannot_leave_seed(self):
        with tarfile.open(self.seed / 'payload.tar.gz', mode='w:gz') as archive:
            item = tarfile.TarInfo('scripts/fetch.sh')
            item.type, item.linkname = tarfile.SYMTYPE, '/etc/passwd'
            archive.addfile(item)
        with self.assertRaises(ValueError):
            inventory.publish(self.root)

    def test_never_execute_profile_shell_or_contact_network(self):
        marker = self.root / 'executed'
        self.source('hosts/profiles/one.env', 'APP_URL=$(touch ' + str(marker) + ')\nPASSWORD=private-fixture-secret\n')
        self.payload('hosts/profiles/one.env')
        with mock.patch('subprocess.Popen', side_effect=AssertionError('executed shell')), \
                mock.patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network during serialization')):
            inventory.publish(self.root)
        self.assertFalse(marker.exists())
        self.assertNotIn(b'private-fixture-secret', (self.root / 'inventory.json').read_bytes())

    def test_udeb_and_apt_commands_exclude_diagnostic_strings(self):
        text = ('hook_ensure_installer_command mkfs.f2fs f2fs-tools-udeb\n'
                'installer_info "anna-install fallbacks are available"\n'
                'anna-install wget-udeb\n'
                'apt-get -o APT::Install-Recommends=false -y install curl thunar/forky\n')
        facts = inventory.scan_file('d-i/forky/scripts/install.sh', text)
        self.assertEqual({(row['selector'], row['type']) for row in facts['packages']},
                         {('f2fs-tools-udeb', 'udeb'), ('wget-udeb', 'udeb'), ('curl', 'deb'), ('thunar/forky', 'deb')})

    def test_repository_relative_transfers_are_structured_without_execution(self):
        facts = inventory.scan_file(
            'd-i/forky/scripts/common/source.sh',
            "source_transfer \"$base\" payload.manifest \"$work/payload.manifest\"\n"
            "fetch_hook_file scripts/preseed/network-apt.sh \"$runtime/apt.sh\"\n"
            "bootstrap_source_module 'scripts/common/credentials.sh'\n")
        self.assertEqual(
            {(row['kind'], row['path'], row['expression']) for row in facts['transfers']},
            {('source_transfer', 'payload.manifest', None),
             ('fetch_hook_file', 'scripts/preseed/network-apt.sh', None),
             ('bootstrap_source_module', 'scripts/common/credentials.sh', None)})

    def test_root_apt_snapshot_is_the_only_snapshot(self):
        root_snapshot = self.root / 'inventory-apt.json'
        root_snapshot.write_bytes(b'{"same":true}\n')
        self.assertEqual(inventory.apt_snapshot_path(self.root), root_snapshot)

    def test_missing_mismatched_and_corrupt_pair_bypass_fast_path(self):
        self.source('common.cfg', 'd-i pkgsel/include string curl\n')
        self.payload('common.cfg')
        self.publish_pair()
        metadata_path = self.root / 'inventory-apt.json'
        original = metadata_path.read_bytes()
        for content in (b'{', original + b' ', inventory.encode({**json.loads(original), 'payload': {}})):
            metadata_path.write_bytes(content)
            self.assertFalse(self.publish_pair()['current'])
        metadata_path.unlink()
        self.assertFalse(self.publish_pair()['current'])
        self.assertFalse(self.publish_pair(force=True)['current'])

    def test_refresh_failure_preserves_both_outputs(self):
        self.source('common.cfg', 'd-i pkgsel/include string curl\n')
        self.payload('common.cfg')
        self.publish_pair()
        previous = {name: (self.root / name).read_bytes() for name in ('inventory.json', 'inventory-apt.json')}
        with mock.patch.object(inventory_apt, 'refresh', side_effect=ValueError('fixture unavailable')):
            with self.assertRaisesRegex(ValueError, 'fixture unavailable'):
                inventory.publish(self.root, refresh_apt=True, force=True)
        self.assertEqual(previous, {name: (self.root / name).read_bytes() for name in previous})

    def test_pair_publication_restores_previous_bytes_modes_and_absence(self):
        for previous_inventory in (None, b'previous inventory'):
            output = self.root / 'inventory.json'
            if previous_inventory is not None:
                output.write_bytes(previous_inventory)
                output.chmod(0o640)
            (self.root / 'inventory-apt.json').write_bytes(b'previous apt')
            writer = inventory.atomic_write
            failed = False

            def fail_second(path, data, mode):
                nonlocal failed
                if path == output and not failed:
                    failed = True
                    writer(path, data, mode)
                    raise OSError('fixture post-replace failure')
                writer(path, data, mode)

            with mock.patch.object(inventory, 'atomic_write', side_effect=fail_second):
                with self.assertRaisesRegex(OSError, 'post-replace'):
                    inventory.publish_products(self.root, {'inventory-apt.json': b'new apt', 'inventory.json': b'new inventory'})
            self.assertEqual((self.root / 'inventory-apt.json').read_bytes(), b'previous apt')
            if previous_inventory is None:
                self.assertFalse(output.exists())
            else:
                self.assertEqual(output.read_bytes(), previous_inventory)
                self.assertEqual(output.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(self.root.glob('.inventory-recovery-*')), [])

    def test_failed_rollback_retains_recovery_and_reports_unknown(self):
        (self.root / 'inventory.json').write_bytes(b'previous inventory')
        (self.root / 'inventory-apt.json').write_bytes(b'previous apt')
        writer = inventory.atomic_write

        def failed(path, data, mode):
            if path == self.root / 'inventory.json':
                raise OSError('fixture persistent failure')
            writer(path, data, mode)

        with mock.patch.object(inventory, 'atomic_write', side_effect=failed):
            with self.assertRaisesRegex(ValueError, 'outcome unknown; recovery retained'):
                inventory.publish_products(self.root, {'inventory-apt.json': b'new apt', 'inventory.json': b'new inventory'})
        recovery, = self.root.glob('.inventory-recovery-*')
        self.assertEqual((recovery / 'inventory.json').read_bytes(), b'previous inventory')
        with self.assertRaisesRegex(ValueError, 'recovery'):
            with inventory.generation_lock(self.root):
                self.fail('uncertain publication was automatically retried')

    def test_concurrent_inventory_writers_are_rejected(self):
        with inventory.generation_lock(self.root):
            with self.assertRaisesRegex(ValueError, 'already running'):
                with inventory.generation_lock(self.root):
                    self.fail('second writer acquired the lock')

    def test_archive_member_and_expansion_limits_are_enforced(self):
        self.source('common.cfg', 'd-i pkgsel/include string curl\n')
        self.payload('common.cfg')
        raw = (self.seed / 'payload.tar.gz').read_bytes()
        for limit, value in (('MAX_FILE', 1), ('MAX_TOTAL', 1), ('MAX_MEMBERS', 0)):
            with mock.patch.object(inventory, limit, value), self.subTest(limit=limit), self.assertRaises(ValueError):
                inventory.scan_payload(raw)
        with self.assertRaises((OSError, EOFError)):
            inventory.scan_payload(raw[:-6])

    def test_package_urls_use_index_filename_not_package_name(self):
        actual = inventory_apt.filename_url('https://example.org/debian', 'pool/main/s/source/binary_1.2_all.deb')
        self.assertEqual(actual, 'https://example.org/debian/pool/main/s/source/binary_1.2_all.deb')
        for name in ['../secret', '/pool/pkg.deb', 'https://elsewhere/pkg.deb', 'pool/%2e%2e/pkg.deb']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                inventory_apt.filename_url('https://example.org/debian', name)

    def test_indexed_dependency_lookup_retains_virtual_alternatives_and_base_packages(self):
        with sqlite3.connect(':memory:') as database:
            database.execute('CREATE TABLE packages (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, priority TEXT, essential INTEGER, data TEXT)')
            database.execute('CREATE TABLE provides (name TEXT, package_id INTEGER)')
            for name, kind, depends, provides, essential in (
                    ('application', 'deb', 'virtual-api | other-api', '', False),
                    ('provider', 'deb', '', 'virtual-api', False),
                    ('other-api', 'deb', '', '', False),
                    ('base', 'deb', '', '', True),
                    ('provider', 'udeb', '', 'virtual-api', False),
                    ('unrelated', 'deb', '', '', False)):
                row = {'package': name, 'type': kind, 'depends': depends, 'pre_depends': '', 'provides': provides,
                       'architecture': 'amd64', 'repository': 'fixture', 'version': '1', 'url': name, 'index_url': 'fixture'}
                cursor = database.execute('INSERT INTO packages (name,kind,priority,essential,data) VALUES (?,?,?,?,?)',
                                          (name, kind, 'optional', essential, json.dumps(row)))
                if provides:
                    database.execute('INSERT INTO provides VALUES (?,?)', (provides, cursor.lastrowid))
            database.execute('CREATE INDEX names ON packages (name,kind)')
            database.execute('CREATE INDEX virtuals ON provides (name)')
            rows = inventory_apt.select_packages(database, {('application', 'deb')})
        self.assertEqual({(row['package'], row['type']) for row in rows},
                         {('application', 'deb'), ('provider', 'deb'), ('other-api', 'deb'), ('base', 'deb')})

    def test_credential_bearing_urls_are_not_exported(self):
        self.assertEqual(inventory.clean_url('https://user:private@example.org/archive'),
                         '[credential-bearing or malformed URL omitted]')
        self.assertNotIn('private-value', inventory.clean_url('https://example.org/archive?token=private-value'))

    def test_pin_priority_class_and_exact_version_contracts(self):
        repo = {'url': 'https://example.org/debian', 'suite': 'forky'}
        release = {'Origin': 'Debian', 'Codename': 'forky', 'Suite': 'testing'}
        package = {'package': 'agent', 'version': '0.1.3-2', 'source': 'agent'}
        rules = [
            {'packages': ['*'], 'pin': 'release n=forky', 'priority': 900, 'preference': 'forky', 'line': 1,
             'source': {'path': 'forky.pref'}},
            {'packages': ['agent:any'], 'pin': 'version 0.1.3-*', 'priority': 1001, 'preference': 'agent', 'line': 1,
             'source': {'path': 'agent.pref'}},
            {'packages': ['agent:any'], 'pin': 'version *', 'priority': -1, 'preference': 'agent', 'line': 5,
             'source': {'path': 'agent.pref'}},
        ]
        self.assertEqual(inventory.pin_priority(package, repo, release, rules, {'forky'}), 900)
        self.assertEqual(inventory.pin_priority(package, repo, release, rules, {'forky', 'agent'}), 1001)
        package['version'] = '0.2.0-1'
        self.assertEqual(inventory.pin_priority(package, repo, release, rules, {'forky', 'agent'}), -1)
        self.assertEqual(inventory.pin_priority(package, repo, release, rules, {'forky'}, 'forky'), 990)

    def test_debian_epoch_tilde_and_revision_ordering(self):
        for old, new in [('1.0~rc1-1', '1.0-1'), ('1.9-1', '1.10-1'), ('2.0-1', '1:1.0-1'),
                         ('1.0-1', '1.0-1+b1'), ('1.0-1+b9', '1.0-1+b10')]:
            with self.subTest(old=old, new=new):
                self.assertLess(inventory.version_compare(old, new), 0)
                self.assertGreater(inventory.version_compare(new, old), 0)
        self.assertEqual(inventory.version_compare('1.0', '1.0-0'), 0)

    def test_packer_pins_are_read_from_hcl_without_running_plugins(self):
        text = 'packer { required_plugins { qemu = { source = "github.com/hashicorp/qemu" version = "= 1.1.6" } } }\n'
        name = 'd-i/forky/hooks/target/etc/skel-desktop/.config/packer/template.pkr.hcl.tmpl'
        facts = inventory.scan_file(name, text)
        recipes = inventory.indirect_downloads({name: facts}, inventory.Variables({name: facts}))
        self.assertEqual(len(recipes), 1)
        self.assertEqual(recipes[0]['version'], '1.1.6')
        self.assertEqual(recipes[0]['checksums_url'],
                         'https://releases.hashicorp.com/packer-plugin-qemu/1.1.6/packer-plugin-qemu_1.1.6_SHA256SUMS')

    def test_failed_metadata_refresh_preserves_previous_snapshot(self):
        snapshot = self.root / 'inventory-apt.json'
        previous = b'{"fixture":"previous-metadata"}\n'
        snapshot.write_bytes(previous)
        with mock.patch.object(inventory_apt, 'release_metadata', side_effect=inventory_apt.URLError('fixture')):
            with self.assertRaisesRegex(ValueError, 'existing metadata retained'):
                inventory_apt.refresh(self.root, {'repositories': [{'id': 'fixture-repository', 'index_urls': []}], 'packages': []}, {})
        self.assertEqual(snapshot.read_bytes(), b'{"fixture":"previous-metadata"}\n')


if __name__ == '__main__':
    unittest.main()
