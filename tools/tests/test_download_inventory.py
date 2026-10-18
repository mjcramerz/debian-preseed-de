"""Download inventory boundary and incremental cross-file behavior fixtures."""
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[2] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import json
from pathlib import Path
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

    def manifest(self, *names):
        # The manifest digest column deliberately does not match any source.
        (self.seed / 'payload.manifest').write_text(''.join('ignored-digest  ' + name + '\n' for name in names))

    def test_unattended_sources_are_data_and_cached_per_file(self):
        profile = self.source('hosts/profiles/one.env', 'VERSION="1.2.3"\nAPP_URL="https://example.org/${VERSION}/app-${VERSION}.zip"\n')
        self.source('scripts/install.sh', 'curl --url "$APP_URL"\n')
        self.manifest('hosts/profiles/one.env', 'scripts/install.sh')
        first = inventory.publish(self.root)
        self.assertEqual(first['rescanned'], 2)
        output = self.root / 'inventory.json'
        previous = output.stat()
        with mock.patch.object(inventory, 'scan_file', side_effect=AssertionError('unchanged file rescanned')):
            second = inventory.publish(self.root)
        self.assertFalse(second['written'])
        self.assertEqual(second['reused'], 2)
        self.assertEqual((previous.st_ino, previous.st_mtime_ns), (output.stat().st_ino, output.stat().st_mtime_ns))
        profile.write_text(profile.read_text().replace('1.2.3', '2.0.0'))
        with mock.patch.object(inventory, 'scan_file', wraps=inventory.scan_file) as scanner:
            changed = inventory.publish(self.root)
        self.assertEqual(scanner.call_args_list[0].args[0], 'd-i/forky/hosts/profiles/one.env')
        self.assertEqual(changed['rescanned'], 1)
        value = json.loads(output.read_bytes())
        self.assertIn('https://example.org/2.0.0/app-2.0.0.zip', [row['url'] for row in value['external_artifacts']])

    def test_changed_reference_reaggregates_cached_url_definitions(self):
        version = self.source('hosts/installer/runtime.env', 'APP_VERSION=1\n')
        self.source('scripts/fetch.sh', 'APP_URL="https://example.org/${APP_VERSION}/app.zip"\n')
        self.manifest('hosts/installer/runtime.env', 'scripts/fetch.sh')
        inventory.publish(self.root)
        version.write_text('APP_VERSION=2\n')
        inventory.publish(self.root)
        value = json.loads((self.root / 'inventory.json').read_bytes())
        self.assertIn('https://example.org/2/app.zip', [row['url'] for row in value['external_artifacts']])

    def test_removed_manifest_member_is_not_kept_from_cache(self):
        self.source('scripts/fetch.sh', 'APP_URL=https://example.org/archive.zip\n')
        self.source('common.cfg', 'd-i pkgsel/include string curl\n')
        self.manifest('scripts/fetch.sh', 'common.cfg')
        inventory.publish(self.root)
        self.manifest('common.cfg')
        inventory.publish(self.root)
        value = json.loads((self.root / 'inventory.json').read_bytes())
        self.assertNotIn('d-i/forky/scripts/fetch.sh', value['source_hashes'])
        self.assertEqual(value['external_artifacts'], [])

    def test_unrelated_text_change_does_not_replace_inventory(self):
        self.source('common.cfg', 'd-i pkgsel/include string curl\n')
        unrelated = self.source('hooks/target/etc/example.conf', 'Color=blue\n')
        self.manifest('common.cfg', 'hooks/target/etc/example.conf')
        inventory.publish(self.root)
        output = self.root / 'inventory.json'
        previous = output.stat()
        unrelated.write_text('Color=green\n')
        result = inventory.publish(self.root)
        self.assertFalse(result['written'])
        self.assertEqual((previous.st_ino, previous.st_mtime_ns), (output.stat().st_ino, output.stat().st_mtime_ns))

    def test_private_and_traversal_members_are_rejected_before_read(self):
        for member in ['../../private', '/etc/passwd', 'hosts/preseed.env', 'a//b', 'a/./b']:
            with self.subTest(member=member), self.assertRaises(ValueError):
                inventory.manifest_paths(('ignored  ' + member + '\n').encode())

    def test_symbolic_link_member_cannot_leave_seed(self):
        source = self.source('scripts/fetch.sh', 'APP_URL=https://example.org/archive.zip\n')
        source.rename(source.with_suffix('.original'))
        source.symlink_to(source.with_suffix('.original'))
        self.manifest('scripts/fetch.sh')
        with self.assertRaises(ValueError):
            inventory.publish(self.root)

    def test_never_execute_profile_shell_or_contact_network(self):
        marker = self.root / 'executed'
        self.source('hosts/profiles/one.env', 'APP_URL=$(touch ' + str(marker) + ')\nPASSWORD=private-fixture-secret\n')
        self.manifest('hosts/profiles/one.env')
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

    def test_package_urls_use_index_filename_not_package_name(self):
        actual = inventory_apt.filename_url('https://example.org/debian', 'pool/main/s/source/binary_1.2_all.deb')
        self.assertEqual(actual, 'https://example.org/debian/pool/main/s/source/binary_1.2_all.deb')
        for name in ['../secret', '/pool/pkg.deb', 'https://elsewhere/pkg.deb', 'pool/%2e%2e/pkg.deb']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                inventory_apt.filename_url('https://example.org/debian', name)

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
                inventory_apt.refresh(self.root, {'repositories': [{'id': 'fixture-repository'}], 'packages': []})
        self.assertEqual(snapshot.read_bytes(), b'{"fixture":"previous-metadata"}\n')


if __name__ == '__main__':
    unittest.main()
