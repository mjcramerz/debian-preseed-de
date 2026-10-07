"""Exact-release provisioning, signature verification and safe prebuilt extraction.

Network/Packer execution is not simulated as a live installation. Local GnuPG
fixtures exercise real signatures without putting a key or binary in the repo.
"""
from __future__ import annotations

import importlib.util
import hashlib
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

FORKY = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packer = load('compz_test_packer_plugins', FORKY / 'scripts/late/packer-plugins.py')
codec = load('compz_test_codec_installer', FORKY / 'scripts/desktop/compz-codecs-install.py')
TEMPLATE = (FORKY / 'hooks/target/etc/skel-desktop/.config/packer/template.pkr.hcl.tmpl').read_text().replace(
    '__INSTALLER_DEVOPS_PACKER_VERSION__', '1.16.0')
BINARY = 'packer-plugin-ansible_v1.1.6_x5.0_linux_amd64'


def elf(machine=62):
    data = bytearray(64)
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 18, machine)
    return bytes(data)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='packer-release-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / 'output'
        self.target.mkdir()

    def archive(self, entries):
        path = self.root / 'archive.zip'
        with zipfile.ZipFile(path, 'w') as output:
            for name, payload, mode in entries:
                info = zipfile.ZipInfo(name)
                info.external_attr = mode << 16
                output.writestr(info, payload)
        return path

    def test_managed_template_has_all_exact_pins(self):
        version, plugins = packer.requirements(TEMPLATE)
        self.assertEqual(version, '1.16.0')
        self.assertEqual(plugins, {'amazon': '1.8.2', 'ansible': '1.1.6', 'azure': '2.6.3',
                                  'docker': '1.1.4', 'googlecompute': '1.2.7', 'proxmox': '1.2.4', 'qemu': '1.1.6'})

    def test_template_drift_fails_closed(self):
        variants = [TEMPLATE.replace('= 1.1.6', '>= 1.1.6'),
                    TEMPLATE.replace('github.com/hashicorp/ansible', 'github.com/other/ansible'),
                    TEMPLATE.replace('ansible =', 'amazon ='),
                    TEMPLATE + '\nsource "evil" {}\n',
                    TEMPLATE.replace('= 1.16.0', '= ${VERSION}'),
                    TEMPLATE.replace('qemu =', 'newplugin =')]
        for text in variants:
            with self.subTest(text=text[-90:]), self.assertRaises(packer.Error):
                packer.requirements(text)

    def test_modern_and_legacy_checksum_names(self):
        for name in ('packer-plugin-ansible_1.1.6_linux_amd64.zip',
                     'packer-plugin-ansible_v1.1.6_x5.0_linux_amd64.zip'):
            digest = 'a' * 64
            self.assertEqual(packer.archive_checksum(f'{digest}  {name}\n', 'ansible', '1.1.6', 'amd64'),
                             (name, digest))

    def test_checksum_selection_rejects_ambiguity_and_wrong_arch(self):
        name = 'packer-plugin-ansible_1.1.6_linux_amd64.zip'
        line = f'{"f" * 64}  {name}\n'
        for text in (line + line, line.replace('amd64', 'arm64'), 'no-checksum ' + name,
                     line.replace(name, '../' + name)):
            with self.subTest(text=text), self.assertRaises(packer.Error):
                packer.archive_checksum(text, 'ansible', '1.1.6', 'amd64')

    def test_valid_plugin_extracts_only_expected_elf(self):
        path = self.archive([(BINARY, elf(), stat.S_IFREG | 0o755), ('LICENSE.txt', b'license', stat.S_IFREG | 0o644)])
        result = packer.unpack(path, self.target, 'ansible', '1.1.6', 'amd64')
        self.assertEqual(result.read_bytes(), elf())
        self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o700)
        self.assertFalse((self.target / 'LICENSE.txt').exists())

    def test_path_and_symlink_plugin_members_rejected(self):
        for name, mode in (('../' + BINARY, stat.S_IFREG | 0o755),
                           (BINARY, stat.S_IFLNK | 0o777),
                           ('sub/' + BINARY, stat.S_IFREG | 0o755)):
            path = self.archive([(name, elf(), mode)])
            with self.subTest(name=name, mode=mode), self.assertRaises(packer.Error):
                packer.unpack(path, self.target, 'ansible', '1.1.6', 'amd64')

    def test_wrong_architecture_rejected(self):
        path = self.archive([(BINARY, elf(183), stat.S_IFREG | 0o755)])
        with self.assertRaises(packer.Error):
            packer.unpack(path, self.target, 'ansible', '1.1.6', 'amd64')

    def test_proxmox_is_an_explicit_digest_pinned_exception(self):
        self.assertEqual(packer.COMMUNITY_RELEASES[('proxmox', '1.2.4', 'amd64')],
                         '84a50e8204180756708671809df0f4ec7bcdde9d702c74c7c4e005d3ce9d89e5')
        self.assertNotIn(('proxmox', '1.2.5', 'amd64'), packer.COMMUNITY_RELEASES)
        source = (FORKY / 'scripts/late/packer-plugins.py').read_text()
        self.assertIn("if name == 'proxmox':", source)
        self.assertIn("'plugins', 'install', '--path'", source)
        self.assertIn("env['TMPDIR'] = str(work)", source)
        self.assertIn("'CHECKPOINT_DISABLE': '1'", source)
        self.assertNotIn("'init', str(template)", source)

    def test_local_plugins_must_match_checksum_and_hcl_without_remote_init(self):
        root = self.root / 'plugins'
        binary = root / 'github.com/hashicorp/ansible' / BINARY
        binary.parent.mkdir(parents=True)
        binary.write_bytes(elf())
        binary.chmod(0o700)
        checksum = Path(str(binary) + '_SHA256SUM')
        checksum.write_text(hashlib.sha256(binary.read_bytes()).hexdigest() + '\n')
        template = self.root / 'template.pkr.hcl'
        template.write_text(TEMPLATE)
        def output(args, **kwargs):
            if args[1:3] == ['plugins', 'installed']:
                return str(binary) + '\n'
            if args[1:3] == ['plugins', 'required']:
                return 'github.com/hashicorp/ansible\n  ' + str(binary) + '\n'
            self.fail('unexpected Packer invocation: ' + repr(args))
        with mock.patch.object(subprocess, 'check_output', side_effect=output) as commands:
            packer.verify_local_plugins(Path('/usr/bin/packer'), template, root,
                                        {'ansible': '1.1.6'}, 'amd64', {})
            self.assertTrue(any(call.args[0][1:3] == ['plugins', 'required'] for call in commands.call_args_list))
            checksum.write_text('0' * 64 + '\n')
            with self.assertRaisesRegex(packer.Error, 'checksum mismatch'):
                packer.verify_local_plugins(Path('/usr/bin/packer'), template, root,
                                            {'ansible': '1.1.6'}, 'amd64', {})
            checksum.write_text(hashlib.sha256(binary.read_bytes()).hexdigest() + '\n')
        with mock.patch.object(subprocess, 'check_output', side_effect=[str(binary) + '\n',
                                                                       'github.com/hashicorp/ansible\n']):
            with self.assertRaisesRegex(packer.Error, 'does not select'):
                packer.verify_local_plugins(Path('/usr/bin/packer'), template, root,
                                            {'ansible': '1.1.6'}, 'amd64', {})

    def test_fetch_enforces_https_and_bounded_transport(self):
        destination = self.root / 'download'
        destination.write_bytes(b'fixture')
        with mock.patch.object(subprocess, 'run') as run:
            packer.fetch('https://releases.hashicorp.com/example', destination, 1024, {})
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('--proto') + 1], '=https')
        self.assertEqual(command[command.index('--proto-redir') + 1], '=https')
        self.assertEqual(command[command.index('--max-filesize') + 1], '1024')
        self.assertNotIn('--insecure', command)

    def test_installer_refuses_root_plugin_execution(self):
        with mock.patch.object(os, 'geteuid', return_value=0), self.assertRaises(packer.Error):
            packer.install(self.root / 'template', Path('/usr/bin/true'), self.root)

    def test_directory_symlink_rejected(self):
        (self.root / 'link').symlink_to(self.target, target_is_directory=True)
        with self.assertRaises(packer.Error):
            packer.directory(self.root / 'link')

    def test_flzma2_release_pins_and_architectures(self):
        self.assertEqual(codec.TAG, 'v26.02-v1.5.7-R2')
        self.assertEqual(codec.RELEASES['amd64'][2],
                         'be246e5a284d3b5e738bad5cbb24c2662996ddb9776e09575b5099ab53fa0ba3')
        self.assertEqual(codec.RELEASES['arm64'][1], 183)

    def test_flzma2_extracts_prebuilt_standalone_binary(self):
        path = self.archive([('7zz', elf(), stat.S_IFREG | 0o755), ('7za', b'unused', stat.S_IFREG | 0o755)])
        codec.extract_binary(path, self.target / '7zz', 62)
        self.assertEqual((self.target / '7zz').read_bytes(), elf())
        self.assertFalse((self.target / '7za').exists())

    def test_flzma2_rejects_path_traversal_or_wrong_arch(self):
        for index, entries in enumerate([
                [('../7zz', elf(), stat.S_IFREG | 0o755)],
                [('7zz', elf(183), stat.S_IFREG | 0o755)],
                [('7zz', elf(), stat.S_IFLNK | 0o777)]]):
            with self.subTest(index=index), self.assertRaises(codec.Error):
                codec.extract_binary(self.archive(entries), self.target / f'7zz-{index}', 62)

    def test_packer_shell_cleanup_and_nonroot_invocation(self):
        source = (FORKY / 'scripts/late/devops/tool-configs.sh').read_text()
        body = source[source.index('devops_initialize_packer_plugins()'):]
        self.assertIn('devops_run_as_account', body)
        self.assertIn('bootstrap_fetch_seed_file', body)
        self.assertIn('trap ', body)
        self.assertIn('/usr/bin/python3 -I -B', body)
        result = subprocess.run(['/bin/sh', '-n', str(FORKY / 'scripts/late/devops/tool-configs.sh')],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(shutil.which('gpg') and shutil.which('gpgconf'), 'GnuPG not installed')
class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='packer-signature-test-')
        cls.root = Path(cls.temporary.name)
        cls.signer = cls.root / 'signer'
        cls.signer.mkdir(mode=0o700)
        cls.gpg = ['/usr/bin/gpg', '--no-options', '--batch', '--no-tty', '--homedir', str(cls.signer)]
        subprocess.run(cls.gpg + ['--pinentry-mode', 'loopback', '--passphrase', '', '--quick-generate-key',
                                 'Offline Fixture <fixture.invalid@example.invalid>', 'ed25519', 'sign', '1d'],
                       env=packer.ENV, capture_output=True, check=True, timeout=30)
        result = subprocess.check_output(cls.gpg + ['--with-colons', '--list-keys'], env=packer.ENV, text=True)
        cls.fingerprint = next(line.split(':')[9] for line in result.splitlines() if line.startswith('fpr:'))
        cls.key = cls.root / 'public.asc'
        cls.key.write_bytes(subprocess.check_output(cls.gpg + ['--armor', '--export', cls.fingerprint], env=packer.ENV))
        cls.sums = cls.root / 'SHA256SUMS'
        cls.sums.write_text('a' * 64 + '  packer-plugin-ansible_1.1.6_linux_amd64.zip\n')
        cls.signature = cls.root / 'SHA256SUMS.sig'
        subprocess.run(cls.gpg + ['--pinentry-mode', 'loopback', '--passphrase', '', '--detach-sign',
                                 '--output', str(cls.signature), str(cls.sums)], env=packer.ENV,
                       capture_output=True, timeout=30, check=True)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(['/usr/bin/gpgconf', '--homedir', str(cls.signer), '--kill', 'gpg-agent'],
                       capture_output=True, timeout=10, check=False)
        cls.temporary.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='verifier-', dir=self.root)
        self.addCleanup(self.temp.cleanup)
        self.verifier = ['/usr/bin/gpg', '--no-options', '--no-autostart', '--batch', '--no-tty',
                         '--homedir', self.temp.name]

    def test_actual_good_signature_and_pinned_primary(self):
        with mock.patch.object(packer, 'FINGERPRINT', self.fingerprint):
            packer.import_release_key(self.verifier, self.key, packer.ENV)
            packer.verify_checksums(self.verifier, self.signature, self.sums, packer.ENV)

    def test_actual_wrong_key_pin_rejected(self):
        with mock.patch.object(packer, 'FINGERPRINT', '0' * 40), self.assertRaises(packer.Error):
            packer.import_release_key(self.verifier, self.key, packer.ENV)

    def test_actual_tampered_checksums_rejected(self):
        bad = Path(self.temp.name) / 'tampered'
        bad.write_text(self.sums.read_text().replace('a' * 64, 'b' * 64))
        with mock.patch.object(packer, 'FINGERPRINT', self.fingerprint):
            packer.import_release_key(self.verifier, self.key, packer.ENV)
            with self.assertRaises(subprocess.CalledProcessError):
                packer.verify_checksums(self.verifier, self.signature, bad, packer.ENV)


if __name__ == '__main__':
    unittest.main()
