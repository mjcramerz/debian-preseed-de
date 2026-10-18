"""Filen policy and failure fixtures; requires the disposable test image.

No login, release download, package install, service operation or host helper is
performed. These fixtures are not native Bun, AppArmor or cloud acceptance.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation
require_test_isolation()

import hashlib
import io
import json
import os
import stat
import subprocess
import tempfile
import types
import unittest
from unittest import mock
import urllib.error

SEED = Path(__file__).resolve().parents[1]
installer = types.ModuleType('filen_installer_fixture')
exec(compile((SEED / 'scripts/desktop/filen-install.py').read_bytes(), 'filen-fixture', 'exec'), installer.__dict__)


class DownloadPolicyTests(unittest.TestCase):
    def test_redirect_target_is_checked_before_request_and_no_secret_url_is_logged(self):
        for target in ('http://github.com/asset', 'https://example.invalid/asset',
                       'https://user:password@github.com/asset', 'https://github.com:444/asset'):
            opener = mock.Mock()
            opener.open.side_effect = urllib.error.HTTPError('https://github.com/release', 302, 'redirect',
                {'Location': target}, io.BytesIO())
            with self.subTest(target=target), mock.patch.object(installer.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaisesRegex(ValueError, 'redirect violates'):
                    installer.download('https://github.com/release', '0' * 64, 1024)
            self.assertEqual(opener.open.call_count, 1)

    def test_bad_hash_and_oversized_stream_fail_before_publication(self):
        for data, digest, maximum, error in ((b'good', '0' * 64, 16, 'SHA-256'),
                (b'overflow', hashlib.sha256(b'overflow').hexdigest(), 2, 'exceeds')):
            opener = mock.Mock()
            opener.open.return_value = io.BytesIO(data)
            with self.subTest(error=error), mock.patch.object(installer.urllib.request, 'build_opener', return_value=opener), \
                    mock.patch.object(installer, 'publish') as publish:
                with self.assertRaisesRegex(ValueError, error):
                    installer.download('https://github.com/release', digest, maximum)
            publish.assert_not_called()

    def test_redirect_hops_are_bounded(self):
        opener = mock.Mock()
        def redirect(*args, **kwargs):
            raise urllib.error.HTTPError('https://github.com/release', 302, 'redirect',
                {'Location': 'https://github.com/another'}, io.BytesIO())
        opener.open.side_effect = redirect
        with mock.patch.object(installer.urllib.request, 'build_opener', return_value=opener), self.assertRaises(ValueError):
            installer.download('https://github.com/release', '0' * 64, 1024)
        self.assertEqual(opener.open.call_count, 5)

    def test_valid_bytes_arriving_after_deadline_are_rejected(self):
        now = [0.0]
        class SlowResponse(io.BytesIO):
            def read1(self, count):
                now[0] = 301.0
                return super().read1(count)
        opener = mock.Mock()
        opener.open.return_value = SlowResponse(b'fixture')
        with mock.patch.object(installer.time, 'monotonic', side_effect=lambda: now[0]), \
                mock.patch.object(installer.urllib.request, 'build_opener', return_value=opener), \
                self.assertRaisesRegex(ValueError, 'deadline exceeded'):
            installer.download('https://github.com/release', hashlib.sha256(b'fixture').hexdigest(), 1024)


class EnablementTests(unittest.TestCase):
    def test_second_account_compile_failure_prevents_all_enablement(self):
        identities = {name: types.SimpleNamespace(pw_uid=uid, pw_gid=uid)
                      for name, uid in (('private', 991), ('offsec', 992))}
        def command(argv, **kwargs):
            if kwargs.get('identity') is identities['offsec']:
                raise subprocess.CalledProcessError(2, argv)
            return b''
        with mock.patch.object(installer, 'command', side_effect=command) as commands, \
                self.assertRaises(subprocess.CalledProcessError):
            installer.enable_services(identities)
        self.assertEqual(len(commands.call_args_list), 2)
        self.assertTrue(all('-c' in call.args[0] for call in commands.call_args_list))
        self.assertEqual([call.kwargs['identity'] for call in commands.call_args_list], list(identities.values()))

    def test_compile_command_drops_uid_gid_and_supplementary_groups(self):
        identity = types.SimpleNamespace(pw_uid=991, pw_gid=992)
        with mock.patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'')) as run:
            installer.command(['/usr/bin/perl', '-T', '-c', '/fixture/wrapper'], identity=identity)
        self.assertEqual(run.call_args.kwargs['user'], 991)
        self.assertEqual(run.call_args.kwargs['group'], 992)
        self.assertEqual(run.call_args.kwargs['extra_groups'], [])
        self.assertEqual(run.call_args.kwargs['env'], installer.ENV)


class RuntimeOutputTests(unittest.TestCase):
    def test_perl_supervisor_distinguishes_error_messages_from_path_contents(self):
        local = '/data/sharing/filen-private'
        remote = '/日本語 Invalid credentials No such cloud file or directory: notes'
        rows = [f'Syncing {local} to {remote} (twoWay)...\n',
                f'Done syncing {local} to {remote} (twoWay)\n',
                'Invalid credentials!\n', '\x1b[31mInvalid credentials!\x1b[0m\n',
                '\x1b[31mInvalid Two Factor Authentication code!\x1b[0m\n',
                f'\x1b[31mNo such cloud file or directory: {remote}\x1b[0m\n',
                'No such cloud file or directory: /different\n',
                'Error in filename: Invalid credentials!\n', 'Syncing unknown pair\n']
        code = r'''
use FilenSync::Daemon;
use JSON::PP qw(decode_json encode_json);
use Encode qw(encode);
my $input = decode_json(do { local $/; <STDIN> });
my $daemon = FilenSync::Daemon->new(account => 'private');
my $messages = $daemon->output_messages($input->{settings});
print encode_json([map { $messages->{encode('UTF-8', $_)} // q{} } @{$input->{rows}}]);
'''
        libraries = SEED / 'hooks/target/usr/local/lib/perl5/site_perl'
        result = subprocess.run(['/usr/bin/perl', '-I' + str(libraries / 'filen'),
            '-I' + str(libraries / 'runtime'), '-e', code],
            input=json.dumps({'settings': {'local': local, 'remote': remote, 'mode': 'twoWay'}, 'rows': rows}),
            text=True, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'HOME': '/nonexistent'}, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['initializing', '', 'authentication', 'authentication',
            'authentication', 'remote-directory', '', '', ''])


@unittest.skipUnless(os.geteuid() == 0, 'private publication fixtures require disposable-image root')
class PublicationTests(unittest.TestCase):
    def test_private_umask_keeps_public_parents_traversable_and_private_parents_private(self):
        with tempfile.TemporaryDirectory(prefix='filen-publication-') as temporary:
            root = Path(temporary)
            previous = os.umask(0o077)
            try:
                installer.directory(root / 'modules' / 'FilenSync')
                installer.directory(root / 'credentials', 0o700)
                installer.publish(root / 'modules' / 'FilenSync' / 'Fixture.pm', b'fixture')
                installer.publish(root / 'credentials' / 'password', b'fixture-secret', 0o600)
            finally:
                os.umask(previous)
            for path in (root / 'modules', root / 'modules' / 'FilenSync'):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
                self.assertEqual((path.stat().st_uid, path.stat().st_gid), (0, 0))
            self.assertEqual(stat.S_IMODE((root / 'credentials').stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((root / 'credentials' / 'password').stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((root / 'modules' / 'FilenSync' / 'Fixture.pm').stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)  # Existing private parent is preserved.

    def test_ownership_failure_preserves_previous_bytes_and_removes_candidate(self):
        with tempfile.TemporaryDirectory(prefix='filen-publication-') as temporary:
            path = Path(temporary) / 'owned'
            path.write_bytes(b'previous')
            path.chmod(0o644)
            with mock.patch.object(installer.os, 'fchown', side_effect=PermissionError('fixture')):
                with self.assertRaises(PermissionError):
                    installer.publish(path, b'candidate')
            self.assertEqual(path.read_bytes(), b'previous')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            self.assertEqual(list(path.parent.iterdir()), [path])


class ConfigurationTests(unittest.TestCase):
    def test_remote_paths_reject_ambiguous_and_control_input_without_shell_restrictions(self):
        for value in ('relative', '//other', '/a/../b', '/a//b', '/a\nprivate', '/a\0'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                installer.remote_value(value)
        for value in ('/', '/my files', '/a:twoWay:b', '/日本語'):
            self.assertEqual(installer.remote_value(value), value)

    def environment(self):
        return {'FILEN_CLI_VERSION': '0.0.36', 'FILEN_CLI_ARCHITECTURE': 'amd64',
                'FILEN_CLI_URL': 'https://github.com/FilenCloudDienste/filen-cli/releases/download/v0.0.36/filen-cli-v0.0.36-linux-x64',
                'FILEN_CLI_SHA256': 'b' * 64, 'FILEN_CLI_MAXIMUM_BYTES': '201326592',
                'NETWORK_SHARING_ROOT_PATH': '/data/sharing', 'NETWORK_SHARING_HOME_BIND_PATH': 'Sharing',
                'ACCOUNT_HOME': '/home/fixture', 'ACCOUNT_USERNAME': 'fixture',
                'FILEN_CLI_PRIV_ENABLE': 'true', 'FILEN_CLI_OFFSEC_ENABLE': 'true',
                'FILEN_CLI_PRIV_SYNC_MODE': 'twoWay', 'FILEN_CLI_OFFSEC_SYNC_MODE': 'cloudBackup',
                'FILEN_CLI_PRIV_REMOTE_PATH': '/', 'FILEN_CLI_OFFSEC_REMOTE_PATH': '/'}

    def test_bad_private_inputs_and_modes_fail_without_download_or_external_writes(self):
        env = self.environment()
        sharing = json.dumps({'version': 3, 'profile': env}).encode()
        for changed, secret in (({'FILEN_CLI_PRIV_SYNC_MODE': 'twoWay;sh'}, b'valid'),
                                ({}, b'bad\npassword'), ({}, b'bad\0password'),
                                ({}, b'AAAAAAAAAAAAAAAAA')):
            def read(path, *args, **kwargs):
                if str(path) == '/etc/network-sharing/config.json':
                    return sharing
                return secret
            with self.subTest(changed=changed, secret_length=len(secret)), \
                    mock.patch.object(installer, 'command', return_value=b'amd64\n'), \
                    mock.patch.object(installer.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=1000, pw_dir='/home/fixture')), \
                    mock.patch.object(installer, 'read', side_effect=read), \
                    mock.patch.object(installer, 'download') as download, \
                    mock.patch.object(installer, 'publish') as publish, self.assertRaises(ValueError):
                installer.install(Path('/private-fixture'), {**env, **changed})
            download.assert_not_called()
            publish.assert_not_called()

    def test_both_disabled_accounts_do_not_read_credentials_or_download(self):
        env = {**self.environment(), 'FILEN_CLI_PRIV_ENABLE': 'false', 'FILEN_CLI_OFFSEC_ENABLE': 'false'}
        def read(path, *args, **kwargs):
            if str(path) != '/etc/network-sharing/config.json':
                raise AssertionError('unexpected secret or host input')
            return json.dumps({'version': 3, 'profile': env}).encode()
        with mock.patch.object(installer, 'command', return_value=b'amd64\n'), \
                mock.patch.object(installer.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=1000, pw_dir='/home/fixture')), \
                mock.patch.object(installer, 'read', side_effect=read), \
                mock.patch.object(installer, 'download') as download, mock.patch.object(installer, 'publish') as publish:
            installer.install(Path('/private-fixture'), env)
        download.assert_not_called()
        publish.assert_not_called()


@unittest.skipUnless(os.geteuid() == 0, 'isolated native ACL fixture requires disposable-image root')
class SyncTreeACLTests(unittest.TestCase):
    def test_default_acl_inherits_both_uids_without_granting_other_access(self):
        # The test image has no capabilities. Mock ownership publication;
        # exercise actual packaged ACL inheritance only in this private tree.
        desktop_uid, service_uid = 55010, 55011
        with tempfile.TemporaryDirectory(prefix='filen-acl-') as temporary:
            parent = Path(temporary)
            parent.chmod(0o755)
            local = parent / 'sync'
            with mock.patch.object(installer.os, 'chown') as ownership:
                installer.sync_tree(local, types.SimpleNamespace(pw_uid=service_uid, pw_gid=service_uid), desktop_uid)
            ownership.assert_called_once_with(local, service_uid, service_uid)
            child = local / 'directory'
            child.mkdir()
            document = child / 'document'
            document.write_bytes(b'fixture')
            for path, permissions in ((child, 'rwx'), (document, 'rw-')):
                acl = installer.command(['/usr/bin/getfacl', '--absolute-names', '--numeric', '--omit-header', '--', str(path)]).decode()
                self.assertIn('user:' + str(desktop_uid) + ':rwx', acl)
                self.assertIn('user:' + str(service_uid) + ':rwx', acl)
                self.assertIn('mask::' + permissions, acl)
                self.assertIn('other::---', acl)
            self.assertIn('default:user:' + str(service_uid) + ':rwx',
                installer.command(['/usr/bin/getfacl', '--numeric', '--omit-header', '--', str(child)]).decode())


if __name__ == '__main__':
    unittest.main()
