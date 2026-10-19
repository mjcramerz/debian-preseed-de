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


class ManualServiceTests(unittest.TestCase):
    def test_second_account_compile_failure_prevents_all_enablement(self):
        identities = {name: types.SimpleNamespace(pw_uid=uid, pw_gid=uid)
                      for name, uid in (('private', 991), ('offsec', 992))}
        def command(argv, **kwargs):
            if kwargs.get('identity') is identities['offsec']:
                raise subprocess.CalledProcessError(2, argv)
            return b'glibc 2.44\n' if argv[0] == '/usr/bin/getconf' else b''
        with mock.patch.object(installer, 'command', side_effect=command) as commands, \
                mock.patch.object(installer, 'read', return_value=b'\x7fELF'), \
                self.assertRaises(subprocess.CalledProcessError):
            installer.validate_services(identities)
        compiles = [call for call in commands.call_args_list if '-c' in call.args[0]]
        self.assertEqual(len(commands.call_args_list), 3)
        self.assertEqual([call.kwargs['identity'] for call in compiles], list(identities.values()))
        self.assertFalse(any(call.args[0][0] == '/usr/bin/systemctl' for call in commands.call_args_list))

    def test_unavailable_native_libc_probe_prevents_all_enablement(self):
        identity = types.SimpleNamespace(pw_uid=991, pw_gid=991)
        for content, response, error in ((b'#!/bin/sh', b'glibc 2.44\n', None),
                (b'\x7fELF', b'', None), (b'\x7fELF', b'musl 1.2.5\n', None),
                (b'\x7fELF', b'glibc 2.44\nextra\n', None),
                (b'\x7fELF', b'', subprocess.CalledProcessError(1, ['/usr/bin/getconf'])),
                (b'\x7fELF', b'', subprocess.TimeoutExpired(['/usr/bin/getconf'], 30))):
            with self.subTest(content=content, error=type(error).__name__, response=response):
                def command(argv, **kwargs):
                    if argv[0] == '/usr/bin/getconf':
                        self.assertIs(kwargs['identity'], identity)
                        if error:
                            raise error
                        return response
                    return b''
                with mock.patch.object(installer, 'read', return_value=content), \
                        mock.patch.object(installer, 'command', side_effect=command) as commands, \
                        self.assertRaises((ValueError, subprocess.SubprocessError)):
                    installer.validate_services({'private': identity})
                self.assertFalse(any(call.args[0][0] == '/usr/bin/systemctl' for call in commands.call_args_list))

    def test_compile_command_drops_uid_gid_and_supplementary_groups(self):
        identity = types.SimpleNamespace(pw_uid=991, pw_gid=992)
        with mock.patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'')) as run:
            installer.command(['/usr/bin/perl', '-T', '-c', '/fixture/wrapper'], identity=identity)
        self.assertEqual(run.call_args.kwargs['user'], 991)
        self.assertEqual(run.call_args.kwargs['group'], 992)
        self.assertEqual(run.call_args.kwargs['extra_groups'], [])
        self.assertEqual(run.call_args.kwargs['env'], installer.ENV)

    def test_valid_services_are_checked_without_boot_enablement(self):
        identities = {name: types.SimpleNamespace(pw_uid=uid, pw_gid=uid)
                      for name, uid in (('private', 991), ('offsec', 992))}
        def command(argv, **kwargs):
            return b'glibc 2.44\n' if argv[0] == '/usr/bin/getconf' else b''
        with mock.patch.object(installer, 'command', side_effect=command) as commands, \
                mock.patch.object(installer, 'read', return_value=b'\x7fELF'):
            installer.validate_services(identities)
        self.assertEqual(len(commands.call_args_list), 4)
        self.assertFalse(any(call.args[0][0] == '/usr/bin/systemctl' for call in commands.call_args_list))
        unit = (SEED / 'hooks/target/etc/systemd/system/filen-sync@.service.tmpl').read_text()
        self.assertNotIn('WantedBy=', unit)
        self.assertNotIn('[Install]', unit)


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
        self.assertNotIn('Statement unlikely to be reached', result.stderr)
        self.assertEqual(json.loads(result.stdout), ['initializing', '', 'authentication', 'authentication',
            'authentication', 'remote-directory', '', '', ''])


class RuntimeProbeTests(unittest.TestCase):
    def test_target_glibc_probe_succeeds_without_a_shell_or_ldd(self):
        # Native libc-bin from the disposable image, not a fixture returning
        # an invented version. detect-libc 1.0.3 falls back to ldd only when
        # this exact command fails. No Filen account or cloud input is used.
        self.assertEqual(Path('/usr/bin/getconf').read_bytes()[:4], b'\x7fELF')
        with tempfile.TemporaryDirectory(prefix='filen-libc-') as temporary:
            result = subprocess.run(['/usr/bin/getconf', 'GNU_LIBC_VERSION'],
                cwd=temporary, env={'PATH': '/usr/bin', 'LC_ALL': 'C', 'HOME': temporary},
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertRegex(result.stdout, rb'\Aglibc [0-9]+\.[0-9]+(?:\.[0-9]+)?\n\Z')

    def test_probe_policy_retains_own_account_and_no_shell_boundaries(self):
        source = (SEED / 'hooks/target/etc/apparmor.d/filen-sync.tmpl').read_text()
        for account, other in (('private', 'offsec'), ('offsec', 'private')):
            with self.subTest(account=account):
                policy = source.replace('__ACCOUNT__', account).replace('__SHARING_ROOT__', '/data/sharing')
                self.assertIn('/usr/bin/getconf rix,', policy)
                self.assertIn('/usr/bin/ldd r,', policy)
                self.assertIn('/var/{,lib/} r,', policy)
                self.assertNotRegex(policy, r'/usr/bin/ldd [^,]*x')
                self.assertIn('deny /{,usr/}bin/{sh,bash,dash} x,', policy)
                self.assertIn('owner @{PROC}/@{pid}/{stat,statm,status,', policy)
                self.assertIn(r'@{sys}/fs/cgroup/system.slice/system-filen\\x2dsync.slice/'
                    + f'filen-sync@{account}.service/memory.{{high,max}} r,', policy)
                self.assertNotIn(f'filen-sync@{other}.service', policy)
                self.assertNotIn('capability ', policy)
                self.assertNotIn('Ux', policy)


@unittest.skipUnless(os.geteuid() == 0, 'credential ownership fixtures require disposable-image root')
class CredentialLayoutTests(unittest.TestCase):
    def test_systemd_acl_mask_is_accepted_only_for_fixed_service_credentials(self):
        # Redirect only the fixed credential prefix into an owned fixture.
        # No real /run credentials, account database, or service is accessed.
        source = (SEED / 'hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Config.pm').read_text()
        code = r'''
use FilenSync::Config;
my ($path, $private) = @ARGV;
my $config = FilenSync::Config->new(account => 'private');
my $accepted = eval { $config->read_file($path, $private); 1 };
print $accepted ? "accepted\n" : "rejected\n";
'''
        with tempfile.TemporaryDirectory(prefix='filen-credentials-') as temporary:
            root = Path(temporary)
            modules = root / 'modules/FilenSync'
            modules.mkdir(parents=True)
            (modules / 'Config.pm').write_text(source.replace('/run/credentials/filen-sync@', str(root / 'filen-sync@')))
            credentials = root / 'filen-sync@private.service'
            credentials.mkdir(mode=0o700)
            secret = credentials / 'seed'
            ordinary = root / 'ordinary'
            ordinary.write_bytes(b'fixture')
            for mode, private, fixed, expected in (
                    (0o400, 1, True, 'accepted'), (0o600, 1, True, 'accepted'),
                    (0o440, 1, True, 'accepted'), (0o640, 1, True, 'rejected'),
                    (0o444, 1, True, 'rejected'), (0o460, 1, True, 'rejected'),
                    (0o440, 1, False, 'rejected'), (0o444, 0, False, 'accepted')):
                with self.subTest(mode=oct(mode), private=private, fixed=fixed):
                    path = secret if fixed else ordinary
                    if path.exists():
                        path.chmod(0o600)
                    path.write_bytes(b'fixture')
                    path.chmod(mode)
                    result = subprocess.run(['/usr/bin/perl', '-T', '-I' + str(modules.parent), '-e', code,
                        str(path), str(private)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'HOME': str(root)}, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected + '\n')
            secret.chmod(0o440)
            os.link(secret, root / 'extra-link')
            result = subprocess.run(['/usr/bin/perl', '-T', '-I' + str(modules.parent), '-e', code,
                str(secret), '1'], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'HOME': str(root)}, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'rejected\n')

    def test_credential_directory_rejects_other_access_before_reading_secrets(self):
        source = (SEED / 'hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Config.pm').read_text()
        code = r'''
use FilenSync::Config;
my $config = FilenSync::Config->new(account => 'private');
my $accepted = eval { $config->credentials; 1 };
print $accepted ? "accepted\n" : "rejected\n";
'''
        with tempfile.TemporaryDirectory(prefix='filen-credentials-') as temporary:
            root = Path(temporary)
            modules = root / 'modules/FilenSync'
            modules.mkdir(parents=True)
            (modules / 'Config.pm').write_text(source.replace('/run/credentials/filen-sync@', str(root / 'filen-sync@')))
            credentials = root / 'filen-sync@private.service'
            credentials.mkdir(mode=0o750)
            for name, value in (('email', b'fixture@example.invalid'), ('password', b'fixture-secret'),
                                ('seed', b'JBSWY3DPEHPK3PXP')):
                path = credentials / name
                path.write_bytes(value)
                path.chmod(0o440)
            for mode, expected in ((0o750, 'accepted'), (0o700, 'accepted'),
                                   (0o755, 'rejected'), (0o770, 'rejected')):
                with self.subTest(mode=oct(mode)):
                    credentials.chmod(mode)
                    result = subprocess.run(['/usr/bin/perl', '-T', '-I' + str(modules.parent), '-e', code],
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'HOME': str(root),
                             'CREDENTIALS_DIRECTORY': str(credentials)}, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected + '\n')


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
