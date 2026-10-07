"""APT metadata/lifecycle and desktop regressions without installing packages.

Temporary files use the invoking account; root identity is mocked explicitly.
MOK helpers and audio/server connections are spies, never live unlocks/sockets.
The optional .deb fixture is constructed from text, with no source compilation.
"""
from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import shlex
import tempfile
import types
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'


def helper(name):
    path = TARGET / 'usr/local/libexec' / name
    module = types.ModuleType('fixture_' + name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def protocol(package, action='**CONFIGURE**', version=2):
    fields = f'{package} - < 1 {action}' if version == 2 else f'{package} - - none < 1 amd64 none {action}'
    return io.StringIO(f'VERSION {version}\n\n{fields}\n')


class MokProtocolTests(unittest.TestCase):
    def setUp(self):
        self.m = helper('apt-mok-prehook')

    def test_all_signing_package_families_and_protocols(self):
        packages = ('linux-image-amd64', 'linux-xanmod-x64v3', 'linux-headers-test',
                    'grub-efi-amd64-signed', 'shim-signed', 'initramfs-tools',
                    'nvidia-kernel-dkms', 'cuda-drivers', 'libnvidia-gl-580',
                    'libcublas12', 'libcudnn9', 'libnccl2', 'libnvfatbin12',
                    'libcuobjclient12', 'libcuinj64', 'zfs-dkms', 'virtualbox-modules-test',
                    'cccl-13-3', 'cuquantum0', 'libnvptxcompiler-13-3', 'datacenter-gpu-manager-4-core')
        for version in (2, 3):
            for package in packages:
                with self.subTest(version=version, package=package):
                    self.assertTrue(self.m.relevant_actions(protocol(package, version=version)))

    def test_irrelevant_packages_and_remove_action(self):
        for package in ('foot', 'curl', 'perl-modules-5.42', 'libpam-modules'):
            self.assertFalse(self.m.relevant_actions(protocol(package)))
        self.assertTrue(self.m.relevant_actions(protocol('linux-image-test', '**REMOVE**')))

    def test_invalid_protocol_has_no_side_effects(self):
        for content in ('VERSION 1\n\n', 'VERSION 2\n', 'VERSION 2\n\ninvalid\n',
                        'VERSION 2\nDPkg::Options::=--root=/other\n\n',
                        'VERSION 2\ndpkg::options::=--root\ndpkg::options::=/other\n\n',
                        'VERSION 3\nDPkg::Options::=--admindir=/other\n\n',
                        'VERSION 2\n\nlinux-image-test - < 1 **ERROR**\n',
                        'VERSION 2\n\n' + 'x' * 65537):
            with self.subTest(content=content[:40]), self.assertRaises(ValueError):
                self.m.relevant_actions(io.StringIO(content))

    def test_state_ownership_and_modes(self):
        valid = dict(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)
        self.m.trusted(types.SimpleNamespace(**valid))
        for field, value in (('st_uid', 1000), ('st_mode', stat.S_IFREG | 0o644),
                             ('st_mode', stat.S_IFLNK | 0o600), ('st_nlink', 2)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.m.trusted(types.SimpleNamespace(**{**valid, field: value}))

    def test_helper_timeout_kills_and_reaps_the_process_group(self):
        # An actual subprocess, with no MOK helper, mount, key or terminal.
        with self.assertRaises(subprocess.TimeoutExpired):
            self.m.run([sys.executable, '-I', '-B', '-c',
                        'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'],
                       quiet=True, timeout=0.05)


class MokLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.m = helper('apt-mok-prehook')
        self.temp = tempfile.TemporaryDirectory(prefix='mok-hook-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.m.STATE = root / 'state'
        self.m.MARKER = self.m.STATE / 'opened'
        self.m.OPEN = str(root / 'open')
        Path(self.m.OPEN).touch(mode=0o600)
        self.enterContext(mock.patch.object(self.m.os, 'geteuid', return_value=0))
        original = self.m.trusted
        def fixture_trusted(metadata, **options):
            original(types.SimpleNamespace(st_mode=metadata.st_mode, st_uid=0,
                                           st_nlink=metadata.st_nlink), **options)
        self.enterContext(mock.patch.object(self.m, 'trusted', side_effect=fixture_trusted))
        self.run = self.enterContext(mock.patch.object(self.m, 'run'))
        self.run.return_value = subprocess.CompletedProcess([], 0)
        self.ready = self.enterContext(mock.patch.object(self.m, 'ready', side_effect=[False, True]))
        self.notify = self.enterContext(mock.patch.object(self.m, 'notify'))
        self.enterContext(redirect_stderr(io.StringIO()))

    def pre(self, package='linux-image-test'):
        reader, writer = os.pipe()
        try:
            os.write(writer, protocol(package).getvalue().encode())
            os.close(writer); writer = -1
            with mock.patch.dict(os.environ, {'APT_HOOK_INFO_FD': str(reader)}):
                return self.m.main([])
        finally:
            os.close(reader)
            if writer != -1:
                os.close(writer)

    def mounted(self, command, **options):
        status = 1 if command == [self.m.TOOL, 'state-mounted'] else 0
        return subprocess.CompletedProcess(command, status)

    def test_irrelevant_transaction_does_not_touch_state_or_mounts(self):
        self.assertEqual(self.pre('curl'), 0)
        self.assertFalse(self.m.STATE.exists())
        self.run.assert_not_called(); self.ready.assert_not_called()
        self.assertEqual(self.m.main(['--post']), 0)
        self.run.assert_not_called()

    def test_administrator_open_is_not_closed(self):
        self.ready.side_effect = None; self.ready.return_value = True
        self.assertEqual(self.pre(), 0)
        self.assertFalse(self.m.MARKER.exists())
        self.assertEqual(self.m.main(['--post']), 0)
        self.run.assert_not_called()

    def test_hook_open_is_closed_once_and_marker_is_removed(self):
        self.run.side_effect = self.mounted
        self.assertEqual(self.pre(), 0)
        self.assertTrue(self.m.MARKER.exists())
        self.assertEqual(stat.S_IMODE(self.m.MARKER.stat().st_mode), 0o600)
        self.assertEqual(self.m.main(['--post']), 0)
        self.assertFalse(self.m.MARKER.exists())
        self.assertEqual(self.m.main(['--post']), 0)
        self.assertEqual(sum(call.args[0] == [self.m.CLOSE] for call in self.run.call_args_list), 1)

    def test_open_failure_rolls_back_its_marker(self):
        def failed(command, **options):
            if command == [self.m.OPEN]:
                raise subprocess.CalledProcessError(1, command)
            return self.mounted(command, **options)
        self.run.side_effect = failed
        with self.assertRaises(subprocess.CalledProcessError):
            self.pre()
        self.assertFalse(self.m.MARKER.exists())
        self.assertIn(mock.call([self.m.CLOSE]), self.run.call_args_list)

    def test_close_failure_keeps_retry_intent(self):
        self.run.side_effect = self.mounted; self.pre()
        self.run.side_effect = subprocess.CalledProcessError(1, [self.m.CLOSE])
        with self.assertRaises(subprocess.CalledProcessError):
            self.m.main(['--post'])
        self.assertTrue(self.m.MARKER.exists())
        self.assertEqual(self.notify.call_args.args[-1], 'critical')

    def test_mounted_but_unready_does_not_close_administrator_storage(self):
        self.ready.side_effect = None; self.ready.return_value = False
        with self.assertRaises(ValueError):
            self.pre()
        self.assertFalse(self.m.MARKER.exists())
        self.assertNotIn(mock.call([self.m.CLOSE]), self.run.call_args_list)


class DesktopTransactionTests(unittest.TestCase):
    def setUp(self):
        self.m = helper('labwc-wrap-desktop-files')
        self.temp = tempfile.TemporaryDirectory(prefix='desktop-transaction-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for variable, name in (('DPKG_INFO', 'info'), ('OUTPUT_DIR', 'output'), ('STATE_DIR', 'state')):
            path = self.root / name; path.mkdir(mode=0o700); setattr(self.m, variable, path)
        self.vendor = self.root / 'vendor'; self.vendor.mkdir()
        self.m.APPLICATION_DIRS = (self.vendor,)
        self.m.MANIFEST = self.m.STATE_DIR / 'overrides.json'
        self.m.PENDING = self.m.STATE_DIR / 'pending.json'
        self.m.DATABASE_DIRTY = self.m.STATE_DIR / 'database-dirty'
        original = self.m.trusted_file
        self.enterContext(mock.patch.object(self.m, 'trusted_file',
            side_effect=lambda path, **kw: original(path, **{**kw, 'owner_uid': os.geteuid()})))
        self.enterContext(mock.patch.object(self.m, 'trusted_directory'))

    def test_installed_metadata_collects_only_package_desktops(self):
        (self.m.DPKG_INFO / 'foot.list').write_text('/usr/bin/foot\n/usr/share/applications/foot.desktop\n', encoding='utf-8')
        (self.m.DPKG_INFO / 'curl.list').write_text('/usr/bin/curl\n', encoding='utf-8')
        self.assertEqual(self.m.apt_desktop_names(protocol('curl')), set())
        self.assertEqual(self.m.apt_desktop_names(protocol('foot', '**REMOVE**')), {'foot.desktop'})

    def test_unsafe_metadata_paths_and_pending_names_are_rejected(self):
        for name in ('../escape.desktop', 'a//b.desktop', 'a/./b.desktop', 'bad\n.desktop'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.m.desktop_names(['/usr/share/applications/' + name])
        pending = self.m.STATE_DIR / 'apt.json'; pending.write_text('["../escape.desktop"]', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.m.pending_names(pending)

    def test_invalid_transaction_metadata_fails_before_package_queries(self):
        for content in ('VERSION 2\nDPkg::Options::=--instdir /other\n\n',
                        'VERSION 2\ndpkg::options::=--admindir\n\n',
                        'VERSION 3\n\nfoot - - none < 1 amd64 none **ERROR**\n'):
            with self.subTest(content=content), mock.patch.object(self.m.DPKG_INFO.__class__, 'glob') as query:
                with self.assertRaises(ValueError):
                    self.m.apt_desktop_names(io.StringIO(content))
                query.assert_not_called()

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'dpkg-deb control archive fixture')
    def test_new_packages_with_and_without_md5sums_need_no_global_tempdir(self):
        package = self.root / 'package'
        (package / 'DEBIAN').mkdir(parents=True)
        (package / 'DEBIAN').chmod(0o755)
        (package / 'usr/share/applications').mkdir(parents=True)
        (package / 'DEBIAN/control').write_text('Package: fixture-desktop\nVersion: 1\nArchitecture: all\nMaintainer: Fixture <fixture@example.invalid>\nDescription: Metadata fixture\n', encoding='utf-8')
        desktop = package / 'usr/share/applications/fixture.desktop'
        desktop.write_text('[Desktop Entry]\nType=Application\nName=Fixture\nExec=/usr/bin/true\n', encoding='utf-8')
        for checksums in (False, True):
            with self.subTest(checksums=checksums):
                if checksums:
                    (package / 'DEBIAN/md5sums').write_text(hashlib.md5(desktop.read_bytes()).hexdigest() + '  usr/share/applications/fixture.desktop\n', encoding='utf-8')
                archive = self.root / 'fixture with spaces.deb'
                built = subprocess.run(['/usr/bin/dpkg-deb', '--root-owner-group', '--build', str(package), str(archive)],
                                       capture_output=True, timeout=15)
                self.assertEqual(built.returncode, 0, built.stderr.decode('utf-8', errors='replace'))
                archive.chmod(0o644)
                # Model the reported failure without changing /tmp or policy:
                # the real tempfile module must use the explicit state path.
                with mock.patch.object(self.m.tempfile, 'tempdir', None), \
                     mock.patch.object(self.m.tempfile, '_get_default_tempdir',
                                       side_effect=FileNotFoundError('no usable global temporary directory')) as probe:
                    self.assertEqual(self.m.apt_desktop_names(protocol('fixture-desktop', str(archive))), {'fixture.desktop'})
                    probe.assert_not_called()
                self.assertEqual(list(self.m.STATE_DIR.iterdir()), [])

    def test_metadata_scratch_initializes_private_state_and_cleans_up(self):
        self.m.STATE_DIR.rmdir()
        with mock.patch.object(self.m.tempfile, 'tempdir', None), \
             mock.patch.object(self.m.tempfile, '_get_default_tempdir',
                               side_effect=FileNotFoundError('no usable global temporary directory')) as probe:
            with self.m.archive_output([sys.executable, '-I', '-B', '-c', 'print("fixture metadata")']) as output:
                self.assertEqual(output.read(), b'fixture metadata\n')
                self.assertEqual(stat.S_IMODE(self.m.STATE_DIR.stat().st_mode), 0o700)
                self.m.trusted_directory.assert_called_with(self.m.STATE_DIR)
                self.assertEqual(stat.S_IMODE(os.fstat(output.fileno()).st_mode), 0o600)
            probe.assert_not_called()
        self.assertTrue(output.closed)
        self.assertEqual(list(self.m.STATE_DIR.iterdir()), [])

    def test_partial_update_preserves_unrelated_override_without_inspecting_it(self):
        for name in ('foot.desktop', 'demo.desktop'):
            (self.vendor / name).write_text('[Desktop Entry]\nType=Application\nName=Fixture\nExec=/usr/bin/true\n', encoding='utf-8')
        foot = self.m.OUTPUT_DIR / 'foot.desktop'; foot.write_text('administrator override\n', encoding='utf-8')
        before = foot.stat()
        with mock.patch.object(self.m, 'package_for', return_value='demo') as package, \
             mock.patch.object(self.m, 'is_electron', return_value=False), \
             mock.patch.object(self.m, 'validate_desktop'), redirect_stderr(io.StringIO()) as log:
            self.m.generate_overrides({'wayland': '/usr/local/bin/labwc-wayland-app intel',
                                       'electron': '/usr/local/bin/labwc-electron-app intel'}, {'demo.desktop'})
        package.assert_called_once_with(self.vendor / 'demo.desktop')
        self.assertEqual(foot.read_text(encoding='utf-8'), 'administrator override\n')
        self.assertEqual(foot.stat().st_ino, before.st_ino)
        self.assertNotIn('foot.desktop', log.getvalue())
        self.assertIn('labwc-wayland-app intel -- /usr/bin/true', (self.m.OUTPUT_DIR / 'demo.desktop').read_text(encoding='utf-8'))


class CodexAliasTests(unittest.TestCase):
    def setUp(self):
        self.m = helper('codex-app-server-wait-ready')
        self.uid = os.getuid()
        self.parent = os.path.dirname(self.m.BACKEND_SOCKET)
        self.directory = '/tmp/codex-daemon-' + str(self.uid)
        self.target = self.directory + '/' + hashlib.sha256(os.fsencode(self.m.BACKEND_SOCKET)).hexdigest()
        def metadata(mode, inode):
            return types.SimpleNamespace(st_mode=mode, st_uid=self.uid, st_dev=1, st_ino=inode)
        self.entries = {self.parent: metadata(stat.S_IFDIR | 0o700, 1),
                        self.directory: metadata(stat.S_IFDIR | 0o700, 2),
                        self.m.BACKEND_SOCKET: metadata(stat.S_IFLNK | 0o777, 3),
                        self.target: metadata(stat.S_IFSOCK | 0o600, 4)}
        self.enterContext(mock.patch.object(self.m.os.path, 'realpath', side_effect=lambda path: path))
        self.enterContext(mock.patch.object(self.m.os, 'lstat', side_effect=lambda path: self.entries[path]))
        self.alias = self.enterContext(mock.patch.object(self.m.os, 'readlink', return_value=self.target))

    def test_exact_protected_alias_and_direct_socket(self):
        self.assertEqual(self.m.endpoint_snapshot(self.uid), (self.target, (1, 3, 1, 4)))
        self.entries[self.m.BACKEND_SOCKET] = self.entries[self.target]
        self.assertEqual(self.m.endpoint_snapshot(self.uid)[0], self.m.BACKEND_SOCKET)

    def test_arbitrary_alias_or_public_socket_is_rejected(self):
        self.alias.return_value = '/tmp/arbitrary.sock'
        with self.assertRaises(ValueError): self.m.endpoint_snapshot(self.uid)
        self.alias.return_value = self.target
        self.entries[self.target].st_mode = stat.S_IFSOCK | 0o666
        with self.assertRaises(ValueError): self.m.endpoint_snapshot(self.uid)

    def test_alias_directory_must_be_private_owned_and_regular_directory(self):
        for field, value in (('st_uid', self.uid + 1), ('st_mode', stat.S_IFDIR | 0o755),
                             ('st_mode', stat.S_IFLNK | 0o700)):
            entry = self.entries[self.directory]; previous = getattr(entry, field)
            setattr(entry, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError): self.m.endpoint_snapshot(self.uid)
            setattr(entry, field, previous)


class CodexToolPathTests(unittest.TestCase):
    def wrapper(self):
        path = TARGET / 'data/codex/lib/codex.tmpl'
        module = types.ModuleType('fixture_codex_wrapper')
        module.__file__ = str(path)
        exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
        return module

    def test_minimal_manager_path_supplies_all_standard_tool_directories(self):
        module = self.wrapper()
        with mock.patch.dict(os.environ), mock.patch.object(module, '_path_components_are_safe', return_value=True):
            result = module.codex_sanitize_path('/usr/bin:/bin:relative:/usr/bin:/data/codex/lib')
        paths = result.split(':')
        self.assertEqual(paths[:2], ['/usr/bin', '/bin'])
        for directory in ('/usr/local/sbin', '/usr/local/bin', '/usr/sbin', '/usr/bin', '/sbin', '/bin'):
            self.assertEqual(paths.count(directory), 1)
        self.assertNotIn('relative', paths)
        self.assertNotIn(module.CODEX_WRAPPER_DIRECTORY, paths)
        self.assertEqual(paths[-1], module.CODEX_RELEASE_BINARY_DIRECTORY)

    def test_offline_manager_state_is_private_per_launch(self):
        module = self.wrapper()
        with tempfile.TemporaryDirectory(prefix='codex-manager-') as temporary, \
             mock.patch.object(module, 'codex_control_root', return_value=temporary), \
             mock.patch.object(module, 'codex_generate_uuid', return_value='12345678-1234-1234-1234-123456789abc'), \
             mock.patch.object(module, '_read_bounded_text', return_value='nameserver 127.0.0.53'), \
             mock.patch.dict(os.environ, {'HOME': '/home/fixture'}):
            first = Path(module.codex_prepare_identity_files(os.getuid(), os.getgid()))
            second = Path(module.codex_prepare_identity_files(os.getuid(), os.getgid()))
            self.assertNotEqual(first, second)
            for directory in (first / 'systemd', second / 'systemd'):
                self.assertEqual(directory.stat().st_uid, os.getuid())
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            # Inspect the complete mount plan without executing Bubblewrap.
            fixture = __import__('test_desktop_sandbox').CodexTests()
            fixture.codex = module
            arguments = fixture.bwrap_arguments()
            index = arguments.index('/run/systemd')
            self.assertEqual(arguments[index - 2:index + 1], ['--bind', '/control/systemd', '/run/systemd'])
            self.assertLess(arguments.index('/run'), index)


class ThinkPadMaskTests(unittest.TestCase):
    def test_only_supported_brightness_bits_are_added_and_other_bits_survive(self):
        m = helper('labwc-thinkpad-hotkeys')
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(m.os, 'geteuid', return_value=0), \
             mock.patch.object(m.sys, 'argv', ['fixture']):
            m.ROOT = Path(temporary)
            for supported in (0xfffffffb, 0x8000, 0):
                (m.ROOT / 'hotkey_mask').write_text('0x00400001\n', encoding='ascii')
                (m.ROOT / 'hotkey_all_mask').write_text(f'0x{supported:08x}\n', encoding='ascii')
                self.assertEqual(m.main(), 0)
                self.assertEqual(m.read_mask('hotkey_mask'), 0x00400001 | (supported & 0x18000))


class AudioSelectionTests(unittest.TestCase):
    PERL = r'''
use strict; use warnings; use JSON::PP qw(decode_json encode_json);
use WhisperMode::Audio;
my $fixture = decode_json(do { local $/; <STDIN> });
my @profiles = WhisperMode::Audio::_speaker_profiles_from_json(encode_json($fixture->{cards}));
my @sinks = WhisperMode::Audio::_speaker_records_from_json(encode_json($fixture->{sinks}));
my @calls;
if ($fixture->{select}) {
    no warnings 'redefine';
    local *WhisperMode::Systemd::run_command = sub {
        my ($deadline, $limit, @argv) = @_;
        die 'unbounded audio subprocess' unless $deadline > 0 && $deadline <= 2 && $limit <= 1048576;
        push @calls, \@argv;
        my $output = $argv[-1] eq 'cards' ? encode_json($fixture->{cards})
            : $argv[-1] eq 'sinks' ? encode_json($fixture->{sinks}) : '';
        return {status => 0, stdout => $output, stderr => ''};
    };
    WhisperMode::Audio->new(pactl_binary => '/usr/bin/true')->set_default_speakers();
}
print encode_json({profiles => \@profiles, sinks => \@sinks, calls => \@calls});
'''

    def audio(self, cards, sinks, select=False):
        roots = TARGET / 'usr/local/lib/perl5/site_perl'
        command = ['perl', '-I', str(roots / 'runtime'), '-I', str(roots / 'whisper'), '-e', self.PERL]
        result = subprocess.run(command, input=json.dumps(dict(cards=cards, sinks=sinks, select=select)),
                                capture_output=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_split_ucm_profile_then_speaker_sink_are_selected(self):
        card = {'name': 'alsa_card.pci-fixture', 'active_profile': 'HiFi (Headphones)',
                'profiles': {'HiFi (Speaker)': {'available': 'yes'}, 'HiFi (Headphones)': {'available': 'yes'}}}
        sinks = [{'name': 'alsa_output.pci-fixture.HiFi__Headphones__sink'},
                 {'name': 'alsa_output.pci-fixture.HiFi__Speaker__sink'}]
        result = self.audio([card], sinks, True)
        self.assertEqual(result['calls'], [
            ['/usr/bin/true', '--format=json', 'list', 'cards'],
            ['/usr/bin/true', 'set-card-profile', card['name'], 'HiFi (Speaker)'],
            ['/usr/bin/true', '--format=json', 'list', 'sinks'],
            ['/usr/bin/true', 'set-default-sink', sinks[1]['name']]])

    def test_acp_headphones_port_is_replaced_with_available_speaker_port(self):
        sink = {'name': 'alsa_output.pci-fixture.analog-stereo', 'active_port': 'analog-output-headphones',
                'ports': [{'name': 'analog-output-headphones', 'availability': 'yes'},
                          {'name': 'analog-output-speaker', 'availability': 'unknown'}]}
        ports = sink['ports']
        for representation in (ports, {p['name']: {'availability': p['availability']} for p in ports}):
            with self.subTest(ports=representation):
                result = self.audio([], [{**sink, 'ports': representation}], True)
                self.assertEqual(result['calls'][-2:], [
                    ['/usr/bin/true', 'set-sink-port', sink['name'], 'analog-output-speaker'],
                    ['/usr/bin/true', 'set-default-sink', sink['name']]])

    def test_usb_hdmi_and_unavailable_speakers_are_not_chosen(self):
        card = {'name': 'alsa_card.usb-fixture', 'active_profile': 'Headphones',
                'profiles': [{'name': 'Speaker', 'available': 'yes'}]}
        sinks = [{'name': 'alsa_output.usb-fixture.Speaker'},
                 {'name': 'virtual-speaker', 'properties': {'device.bus': 'pci'}},
                 {'name': 'alsa_output.pci-fixture.HDMI__Speaker__sink'},
                 {'name': 'alsa_output.pci-fixture.analog-stereo',
                  'ports': {'speaker': {'name': 'analog-output-speaker', 'availability': 'no'}}}]
        result = self.audio([card], sinks)
        self.assertEqual(result['profiles'], []); self.assertEqual(result['sinks'], [])


class ServiceNotificationTests(unittest.TestCase):
    def notify(self, units, status=0, scope='user'):
        source = (TARGET / 'usr/local/bin/labwc-health-notify.tmpl').read_text(encoding='utf-8')
        function = re.search(r'^check_failed_services\(\) \{.*?^\}', source, re.M | re.S)[0]
        with tempfile.TemporaryDirectory(prefix='notify-services-') as temporary:
            fake = Path(temporary) / 'systemctl'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(units) + '\nexit ' + str(status) + '\n', encoding='utf-8')
            fake.chmod(0o700)
            function = function.replace('/usr/bin/systemctl', shlex.quote(str(fake)))
            script = ('send_notification() { printf "NOTIFY\\n%s\\n" "$@"; }\n'
                      'clear_notification_state() { printf "CLEAR\\n%s\\n" "$@"; }\n'
                      + function + '\ncheck_failed_services ' + shlex.quote(scope))
            result = subprocess.run(['/bin/sh', '-c', script], capture_output=True, encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_failure_and_recovery_are_detailed(self):
        output = self.notify('codex-app-server.service loaded failed failed Managed backend')
        self.assertIn('Desktop services need attention', output)
        self.assertIn('codex-app-server.service', output)
        self.assertIn('journalctl --user -u UNIT -b', output)
        self.assertIn('CLEAR\nservices-system', self.notify('', scope='system'))

    def test_failed_probe_never_announces_recovery(self):
        self.assertEqual(self.notify('', status=1), '')

    def test_unit_count_and_identity_lengths_are_bounded(self):
        output = self.notify('\n'.join(f'fixture-{number}.service loaded failed failed' for number in range(25)))
        self.assertIn('Additional failed units: 5', output)
        self.assertNotIn('fixture-24.service', output)


class UnattendedPolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('apt-config'), 'native APT configuration parser')
    def test_native_hook_protocol_settings_and_cleanup_order(self):
        files = ('01mok-maintenance-cleanup', '52unattended-upgrades',
                 '71labwc-desktop-apps', '99mok-maintenance')
        with tempfile.TemporaryDirectory(prefix='apt-config-') as temporary:
            config = Path(temporary) / 'apt.conf'
            config.write_text('Dir::Etc::Parts "/nonexistent-preseed-config";\n'
                              'Dir::Etc::main "/dev/null";\n' + ''.join(
                '#include "' + str(TARGET / 'etc/apt/apt.conf.d' / name) + '";\n'
                for name in files), encoding='utf-8')
            result = subprocess.run(['/usr/bin/apt-config', 'dump'],
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'APT_CONFIG': str(config)},
                capture_output=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        pre = [line for line in lines if line.startswith('DPkg::Pre-Install-Pkgs:: ')]
        post = [line for line in lines if line.startswith('DPkg::Post-Invoke:: ')]
        self.assertEqual(len(pre), 2)
        self.assertEqual(len(post), 2)
        self.assertIn('apt-mok-prehook --post', post[0])
        for command in ('apt-mok-prehook', 'labwc-wrap-desktop-files'):
            prefix = 'DPkg::Tools::Options::/usr/local/libexec/' + command
            self.assertIn(prefix + '::Version "2";', lines)
            self.assertIn(prefix + '::InfoFD "3";', lines)
        self.assertIn('Unattended-Upgrade::Remove-Unused-Kernel-Packages "false";', lines)
        self.assertIn('Unattended-Upgrade::AutoFixInterruptedDpkg "false";', lines)
        mok_pattern = helper('apt-mok-prehook').RELEVANT.pattern
        self.assertIn('Unattended-Upgrade::Package-Blacklist:: '
                      + json.dumps(mok_pattern) + ';', lines)

    @staticmethod
    def blacklist():
        text = (TARGET / 'etc/apt/apt.conf.d/52unattended-upgrades').read_text(encoding='utf-8')
        section = text.split('Unattended-Upgrade::Package-Blacklist {', 1)[1].split('};', 1)[0]
        return [re.compile(pattern) for pattern in re.findall(r'"([^"\n]+)";', section)]

    def test_exact_mok_expression_is_in_blacklist(self):
        relevant = helper('apt-mok-prehook').RELEVANT
        self.assertTrue(relevant.pattern.startswith('^'))
        self.assertEqual(relevant.flags, re.compile(relevant.pattern).flags)
        self.assertIn(relevant.pattern, [pattern.pattern for pattern in self.blacklist()],
                      'every package accepted by the MOK gate must be blacklisted')

    def test_mok_package_boundaries_and_all_runtime_families_are_blacklisted(self):
        mok = helper('apt-mok-prehook')
        patterns = self.blacklist()
        boot = ('linux', 'kernel', 'grub', 'shim', 'initramfs-tools', 'dracut',
                'dkms', 'kmod', 'module-assistant', 'virtualbox-module', 'virtualbox-modules')
        runtimes = ('cudnn', 'nccl', 'nsight', 'tensorrt', 'libcublas', 'libcudart',
                    'libcufft', 'libcufile', 'libcudnn', 'libcudss', 'libcuinj',
                    'libcuobjclient', 'libcupti', 'libcurand', 'libcusolver',
                    'libcusparse', 'libcutensor', 'libnccl', 'libnpp', 'libnvblas',
                    'libnvcuvid', 'libnvfatbin', 'libnvinfer', 'libnvjitlink',
                    'libnvjpeg', 'libnvonnxparsers', 'libnvoptix', 'libnvparsers',
                    'libnvrtc', 'libnvtoolsext', 'libnvvm')
        management = ('cccl', 'collectx-bringup', 'cublas', 'cuquantum', 'cusparselt',
                      'cutensor', 'cuvs', 'datacenter-gpu-manager', 'dcgmi', 'gds-tools',
                      'libdcgm', 'libnvptxcompiler', 'libnvsdm', 'libxnvctrl', 'mft',
                      'nv-hostengine', 'nvcomp', 'nvfwupd', 'nvimgcodec', 'nvjpeg2k',
                      'nvlink', 'nvlsm', 'nvshmem', 'nvtiff', 'nvvct')
        packages = [name + suffix for name in boot for suffix in ('', '-fixture')]
        packages += [name + suffix for name in runtimes + management
                     for suffix in ('', '-fixture', '1', '13-3')]
        packages += ['zfs-dkms', 'wireguard-dkms', 'broadcom-sta-dkms',
                     'nvidia-driver', 'libnvidia-gl-590', 'python3-nvidia-ml',
                     'xserver-xorg-video-nvidia', 'cuda-toolkit-13-0', 'python3-cuda',
                     'libcuda1', 'vendor-cuda-runtime']
        for package in packages:
            with self.subTest(package=package):
                self.assertTrue(mok.relevant_actions(protocol(package)))
                self.assertTrue(any(pattern.match(package) for pattern in patterns))
        for package in ('foot', 'curl', 'jq'):
            with self.subTest(package=package):
                self.assertFalse(mok.relevant_actions(protocol(package)))
                self.assertFalse(any(pattern.match(package) for pattern in patterns))
        for package in ('perl-modules-5.42', 'libpam-modules', 'dkmscope', 'kmodel',
                        'module-assistantship', 'linuxdoc-tools', 'grubby', 'shimmer',
                        'kernelshark', 'virtualbox', 'virtualbox-modulesomething',
                        'ccclogs', 'cutensorial', 'nvcompanion'):
            with self.subTest(package=package):
                self.assertFalse(mok.relevant_actions(protocol(package)))

    def test_foreign_architecture_names_cannot_escape_mok_blacklist(self):
        mok = helper('apt-mok-prehook')
        patterns = self.blacklist()
        # APT's hook protocol supplies the base name, while Python APT's
        # Package.name can append the architecture for a foreign package.
        packages = ('linux', 'kernel', 'grub', 'shim', 'initramfs-tools', 'dracut',
                    'dkms', 'kmod', 'module-assistant', 'zfs-dkms',
                    'virtualbox-module', 'virtualbox-modules', 'cublas', 'cutensor',
                    'libxnvctrl', 'nvcomp', 'libnccl2', 'nvidia-driver')
        for package in packages:
            self.assertTrue(mok.relevant_actions(protocol(package)))
            for architecture in ('amd64', 'i386', 'arm64'):
                qualified = package + ':' + architecture
                with self.subTest(package=qualified):
                    self.assertTrue(any(pattern.match(qualified) for pattern in patterns))

    def test_all_selected_archives_and_gpu_system_examples_are_covered(self):
        text = (TARGET / 'etc/apt/apt.conf.d/52unattended-upgrades').read_text(encoding='utf-8')
        sites = set(re.findall(r'"site=([^";]+)"', text))
        from urllib.parse import urlsplit
        archives = set()
        for path in TARGET.parents[1].rglob('*.cfg'):
            for line in path.read_text(encoding='utf-8').splitlines():
                repository = re.match(r'^\s*d-i apt-setup/[^ ]+/repository string (https?://[^\s]+)', line)
                if repository:
                    archives.add(urlsplit(repository[1]).hostname)
        self.assertGreater(len(archives), 10, 'archive inventory must not be empty or truncated')
        self.assertLessEqual(archives, sites)
        patterns = self.blacklist()
        for package in ('systemd', 'systemd-sysv', 'libudev1', 'wireplumber', 'pipewire-pulse',
                        'polkitd', 'libcap2', 'libblkid1', 'python3-minimal', 'gnupg',
                        'python3.14', 'libpython3.14-minimal',
                        'libpulsedsp', 'libssl3t64', 'grep', 'rsyslog', 'usr-is-merged',
                        'libpulse0', 'alsa-ucm-conf', 'grub-efi-amd64-signed', 'linux-image-amd64',
                        'linux-xanmod-x64v3', 'nvidia-driver', 'cuda-toolkit-13-0', 'libnccl2',
                        'libcudnn9', 'nsight-systems-2026.1', 'libcuinj64', 'libnvfatbin12',
                        'libnvinfer10', 'python3-libnvinfer', 'nfs-common', 'labwc',
                        'cccl-13-3', 'cuquantum0', 'libnvptxcompiler-13-3', 'datacenter-gpu-manager-4-core'):
            with self.subTest(package=package):
                self.assertTrue(any(pattern.match(package) for pattern in patterns))


if __name__ == '__main__':
    unittest.main()
