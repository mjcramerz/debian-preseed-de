"""Offline checks for the dedicated torrent launcher and display profile wiring."""
from __future__ import annotations

import configparser
import contextlib
import io
import os
from pathlib import Path
import pwd
import runpy
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from payload_fixture import python_library, network_identity_text

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / "hooks/target"
QBIT = runpy.run_path(str(TARGET / "usr/local/bin/labwc-qbittorrent"), run_name="test")
sys.path.insert(0, str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')))
from labwc_managed_app import network_namespace, network_client
LAUNCHERS = runpy.run_path(
    str(TARGET / "usr/local/bin/labwc-sync-application-launchers.tmpl"),
    run_name="test",
)
QBIT_CONFIG_TEMPLATE = TARGET / "etc/qbittorrent/qBittorrent.conf.d/10-managed-security.conf.tmpl"


def rendered_managed_config(port: str = "50309", username: str = "fixture") -> bytes:
    text = network_identity_text(QBIT_CONFIG_TEMPLATE.read_text(encoding="utf-8"))
    return text.replace("__INSTALLER_LABWC_QBITTORRENT_PORT__", port).replace(
        "__INSTALLER_ACCOUNT_USERNAME__", username
    ).encode("utf-8")


def copy_profile_home(profile_home: Path, port: str = "50309", username: str = "fixture") -> Path:
    with mock.patch.dict(
        QBIT["copy_managed_config"].__globals__,
        read_managed_config=lambda: rendered_managed_config(port, username),
    ):
        return QBIT["copy_managed_config"](profile_home)


def copy_profile(paths, port: str = "50309", username: str = "fixture") -> Path:
    return copy_profile_home(paths["profile_home"], port, username)


class TorrentIntegrationTests(unittest.TestCase):
    def test_defaults_reader_rejects_special_oversize_and_malformed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'desktop.conf'
            globals_ = QBIT['load_defaults'].__globals__
            # Ownership is a fixture seam; open/read/type/size checks are real.
            original = globals_['os'].fstat
            def owned(fd):
                values = list(original(fd)); values[4] = 0
                return os.stat_result(values)
            for data in (b'x' * (QBIT['MAX_DEFAULTS_BYTES'] + 1), b'\xff'):
                path.write_bytes(data)
                metadata = list(path.lstat()); metadata[4] = 0; metadata[6] = 0
                with mock.patch.object(Path, 'lstat', return_value=os.stat_result(metadata)), \
                        mock.patch.object(globals_['os'], 'fstat', side_effect=owned), \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    QBIT['load_defaults'](path)
            path.unlink(); os.mkfifo(path)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                QBIT['load_defaults'](path)

    def test_network_ready_and_disabled_network_copy_the_install_rendered_profile(self):
        for policy in ({"network": True, "peer_port": 50309},
                       {"network": True, "peer_port": None},
                       {"network": False, "peer_port": None}, None):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = QBIT['prepare_storage'](root)
                account = pwd.struct_passwd(('fixture', 'x', os.getuid(), os.getgid(), '', directory, '/bin/sh'))
                online = policy is not None and policy['network']
                expected_port = 50309
                runtime = types.SimpleNamespace(VETH_DNS_ADDRESS='10.0.2.3',
                    veth_resolv_conf=lambda: 'nameserver 10.0.2.3\n')
                def launch(command, payload, temporary, descriptors, **options):
                    self.assertEqual(options['network'], online)
                    self.assertEqual((Path(temporary) / 'resolv.conf').read_text(encoding='ascii'),
                                     'nameserver 10.0.2.3\n' if online else '# Networking is disabled.\n')
                    if online:
                        options['on_network_ready'](types.SimpleNamespace(
                            peer_port=policy['peer_port'], interface='eth0', address='10.203.0.114'))
                    else:
                        self.assertIsNone(options['on_network_ready'])
                    config = configparser.ConfigParser(interpolation=None)
                    config.optionxform = str
                    config.read(paths['profile_home'] / '.config/qBittorrent/qBittorrent.conf', encoding='utf-8')
                    self.assertEqual(config['BitTorrent'][r'Session\Port'], str(expected_port))
                    self.assertEqual(config['BitTorrent'][r'Session\AnnouncePort'], str(expected_port))
                    self.assertEqual(config['BitTorrent'][r'Session\Interface'], 'eth0')
                    self.assertEqual(config['BitTorrent'][r'Session\InterfaceAddress'], '10.203.0.114')
                    return 0
                runtime.run_veth_sandbox = launch
                globals_ = QBIT['run_new_instance'].__globals__
                temporary_directory = tempfile.TemporaryDirectory
                with mock.patch.object(network_client, 'configured_network_policy', return_value=policy), \
                        mock.patch.dict(globals_, network_runtime=lambda: runtime,
                                        build_command=lambda *args: ['bwrap', '/usr/bin/qbittorrent']), \
                        mock.patch.dict(globals_, copy_managed_config=copy_profile_home), \
                        mock.patch.object(globals_['signal'], 'signal'), \
                        mock.patch.object(tempfile, 'TemporaryDirectory',
                                          side_effect=lambda **options: temporary_directory(dir=directory)):
                    if online and policy['peer_port'] is None:
                        with self.assertRaises(SystemExit):
                            QBIT['run_new_instance'](account, root, paths, 'launch', [], 50309)
                        self.assertFalse((paths['profile_home'] / '.config/qBittorrent/qBittorrent.conf').exists())
                    else:
                        self.assertEqual(QBIT['run_new_instance'](account, root, paths, 'launch', [], 50309), 0)

    def test_ready_peer_port_must_match_the_launcher_before_config_is_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = QBIT['prepare_storage'](root)
            account = pwd.struct_passwd(('fixture', 'x', os.getuid(), os.getgid(), '', str(root), '/bin/sh'))
            globals_ = QBIT['run_new_instance'].__globals__
            temporary_directory = tempfile.TemporaryDirectory
            for broker_port in (50309, 50308, None):
                (paths['profile_home'] / '.config/qBittorrent/qBittorrent.conf').unlink(missing_ok=True)
                runtime = types.SimpleNamespace(VETH_DNS_ADDRESS='10.0.2.3',
                    veth_resolv_conf=lambda: 'nameserver 10.0.2.3\nsearch fixture.example\n')
                def ready(command, payload, temporary, descriptors, **options):
                    self.assertEqual(options['app'], 'qbittorrent')
                    self.assertEqual((Path(temporary) / 'resolv.conf').read_text(encoding='ascii'),
                                     runtime.veth_resolv_conf())
                    options['on_network_ready'](types.SimpleNamespace(
                        peer_port=broker_port, interface='eth0', address='10.203.0.114'))
                    return 0
                runtime.run_veth_sandbox = ready
                with self.subTest(broker_port=broker_port), \
                        mock.patch.object(network_client, "configured_network_policy", return_value={"network": True, "peer_port": 50309}), \
                        mock.patch.dict(globals_, network_runtime=lambda: runtime,
                                        build_command=lambda *args: ['bwrap', '/usr/bin/qbittorrent']), \
                        mock.patch.dict(globals_, copy_managed_config=copy_profile_home), \
                        mock.patch.object(globals_['signal'], 'signal'), \
                        mock.patch.object(tempfile, 'TemporaryDirectory',
                                          side_effect=lambda **options: temporary_directory(dir=directory)):
                    if broker_port == 50309:
                        self.assertEqual(QBIT['run_new_instance'](account, root, paths, 'launch', [], 50309), 0)
                    else:
                        with self.assertRaises(SystemExit):
                            QBIT['run_new_instance'](account, root, paths, 'launch', [], 50309)
                        self.assertFalse((paths['profile_home'] / '.config/qBittorrent/qBittorrent.conf').exists())

    def test_copy_replaces_previous_profile_configuration_with_install_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = QBIT['prepare_storage'](Path(directory))
            config = copy_profile(paths)
            config.write_text('[BitTorrent]\nSession\\Port=22\n'
                              '[Preferences]\nGeneral\\Locale=sv\n', encoding='utf-8')
            copy_profile_home(paths['profile_home'])
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(config, encoding='utf-8')
            self.assertEqual(parser['BitTorrent'][r'Session\Port'], '50309')
            self.assertNotIn(r'General\Locale', parser['Preferences'])
    def test_payload_command_keeps_namespace_isolation_and_drops_all_capabilities(self):
        account = pwd.struct_passwd(('fixture', 'x', os.getuid(), os.getgid(), '', '/home/fixture', '/bin/sh'))
        globals_ = QBIT['build_command'].__globals__
        # Command construction only. Socket availability, optional host binds,
        # and GPU discovery are explicit fixtures; no namespace is created.
        with mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}',
                                         'WAYLAND_DISPLAY': 'wayland-7',
                                         'QT_STYLE_OVERRIDE': 'Adwaita'}, clear=True), \
             mock.patch.dict(globals_, {'require_socket': mock.Mock(),
                                       'optional_ro_bind': mock.Mock(),
                                       'add_gpu_device_binds': mock.Mock()}), \
             mock.patch.object(shutil, 'which', side_effect=lambda name: '/usr/bin/' + name):
            command = QBIT['build_command'](account, Path('/run/media/fixture/bittorrent'),
                                             Path('/run/media/fixture/bittorrent/.qbittorrent-profile'), 'launch', [],
                                             Path('/run/user/1000/fixture/resolv.conf'))
        self.assertEqual(command[0], '/usr/bin/bwrap')
        self.assertEqual(command[-1], '/usr/bin/qbittorrent')
        self.assertEqual(command[command.index('--cap-drop') + 1], 'ALL')
        for argument in ('--unshare-all', '--new-session', '--die-with-parent', '--clearenv'):
            self.assertIn(argument, command)
        self.assertNotIn('--cap-add', command)
        self.assertNotIn('--no-sandbox', command)
        self.assertNotIn('--share-net', command)
        self.assertNotIn('/dev/net/tun', command)
        self.assertIn(['/run/user/1000/fixture/resolv.conf', '/etc/resolv.conf'],
                      [command[i+1:i+3] for i, item in enumerate(command) if item == '--ro-bind'])
        index = command.index('QT_QPA_PLATFORM')
        self.assertEqual(command[index - 1:index + 2], ['--setenv', 'QT_QPA_PLATFORM', 'wayland'])
        index = command.index('QT_STYLE_OVERRIDE')
        self.assertEqual(command[index - 1:index + 2], ['--setenv', 'QT_STYLE_OVERRIDE', 'Fusion'])
        self.assertNotIn('Adwaita', command)

    def test_application_modes_keep_the_qbittorrent_style_override_scoped(self):
        with mock.patch.object(sys, 'path', [
                str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')), *sys.path]):
            from labwc_managed_app import environment
        with mock.patch.multiple(environment, desktop_activation_environment=lambda: {},
                                 current_user_home=lambda: '/home/fixture',
                                 current_user_name=lambda: 'fixture',
                                 current_user_runtime_dir=lambda: '/run/user/1000',
                                 managed_library_path=lambda name: ''), \
             mock.patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-7',
                                         'QT_STYLE_OVERRIDE': 'Adwaita'}, clear=True):
            for mode in ('launch', 'intel', 'nvidia', 'pure-privacy'):
                with self.subTest(mode=mode):
                    values = environment.build_environment('qbittorrent', mode)
                    self.assertEqual(values['QT_STYLE_OVERRIDE'], 'Fusion')
                    self.assertEqual(values['QT_QPA_PLATFORM'], 'wayland')
            self.assertNotIn('QT_STYLE_OVERRIDE', environment.build_environment('retroarch', 'launch'))

    def test_desktop_entry_uses_the_dedicated_service(self):
        config = next(
            item for item in LAUNCHERS["APP_CONFIG"]
            if item["action_app"] == "qbittorrent"
        )
        self.assertEqual(config["default_mode"], "launch")
        self.assertEqual(LAUNCHERS["managed_default_exec"]("qbittorrent", "%U", "launch"),
                         "/usr/local/bin/labwc-qbittorrent %U")
        self.assertEqual(LAUNCHERS["managed_exec"]("intel", "qbittorrent", "%U"),
                         "/usr/local/bin/labwc-qbittorrent --acceleration=intel %U")

    def test_absent_storage_fails_without_creating_a_home_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            account = pwd.struct_passwd(
                ("user", "x", os.getuid(), os.getgid(), "", str(home), "/bin/sh")
            )
            with self.assertRaises(SystemExit):
                QBIT["select_storage_root"](account, home / "missing" / "bittorrent")
            self.assertEqual(list(home.iterdir()), [])

    def test_storage_left_on_run_fails_without_creating_a_home_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            account = pwd.struct_passwd(
                ("user", "x", os.getuid(), os.getgid(), "", str(home), "/bin/sh")
            )
            configured = home / "volume"
            configured.mkdir()
            metadata = configured.stat()
            original_stat = Path.stat
            def same_runtime_device(path, *args, **kwargs):
                return metadata if path == Path('/run') else original_stat(path, *args, **kwargs)
            with mock.patch.object(Path, 'stat', autospec=True, side_effect=same_runtime_device):
                with self.assertRaises(SystemExit):
                    QBIT["select_storage_root"](account, configured)
            self.assertEqual(list(home.iterdir()), [configured])
            self.assertEqual(list(configured.iterdir()), [])

    def test_install_rendered_config_covers_all_native_policy_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = QBIT["prepare_storage"](root)
            config = copy_profile(paths)
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(config)
            self.assertEqual(parser["BitTorrent"][r"Session\Port"], "50309")
            for key in (r"Session\DHTEnabled", r"Session\PeXEnabled",
                        r"Session\LSDEnabled", r"Session\ValidateHTTPSTrackerCertificate"):
                self.assertEqual(parser["BitTorrent"][key],
                                 "true" if "Validate" in key else "false")
            self.assertEqual(parser["Preferences"][r"WebUI\Enabled"], "false")
            self.assertEqual(parser["Network"]["PortForwardingEnabled"], "false")
            self.assertEqual(parser['BitTorrent'][r'Session\Interface'], 'eth0')
            self.assertEqual(parser['BitTorrent'][r'Session\InterfaceAddress'], '10.203.0.114')
            for key in (r'Session\AnnounceToAllTiers', r'Session\AnnounceToAllTrackers'):
                self.assertEqual(parser['BitTorrent'][key], 'false')
            self.assertEqual(parser['BitTorrent'][r'Session\AnnouncePort'], '50309')
            self.assertEqual(parser['BitTorrent'][r'Session\BlockPeersOnPrivilegedPorts'], 'true')
            self.assertEqual(parser['Application'][r'FileLogger\Path'],
                             '/home/user/.local/share/qBittorrent/logs')
            self.assertEqual(parser['BitTorrent'][r'Session\BTProtocol'], '0')
            for key in ('TrackerEnabled', 'MergeTrackersEnabled',
                        r'Session\IPFilteringEnabled', r'Session\TrackerFilteringEnabled',
                        r'Session\MultiConnectionsPerIp'):
                self.assertEqual(parser['BitTorrent'][key], 'false')
            for key in (r'Session\SaveResumeDataInterval', r'Session\SaveStatisticsInterval',
                        r'Session\StopTrackerTimeout'):
                self.assertEqual(parser['BitTorrent'][key], '5')
            self.assertEqual(parser['AutoRun']['enabled'], 'false')
            self.assertEqual(parser['AutoRun'][r'OnTorrentAdded\Enabled'], 'false')

    def test_wrapper_contains_no_native_configuration_keys_or_renderer(self):
        wrapper = (TARGET / 'usr/local/bin/labwc-qbittorrent').read_text(encoding='utf-8')
        for token in ('configparser', 'managed_settings', 'write_config',
                      r'Session\Port', r'Session\Interface', r'Preferences',
                      r'FileLogger\Enabled', r'BlockPeersOnPrivilegedPorts'):
            self.assertNotIn(token, wrapper)
        self.assertIn('copy_managed_config', wrapper)
        self.assertIn('read_managed_config', wrapper)

    def test_copy_preserves_exact_install_rendered_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = QBIT['prepare_storage'](Path(directory))
            config = copy_profile(paths, port='50308')
            self.assertEqual(config.read_bytes(), rendered_managed_config(port='50308'))

    def test_copy_is_atomic_and_restores_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = QBIT['prepare_storage'](Path(directory))
            config = copy_profile(paths)
            content = config.read_text(encoding='utf-8') + '# stale profile data\n'
            config.write_text(content, encoding='utf-8')
            config.chmod(0o644)
            with mock.patch.object(QBIT['copy_managed_config'].__globals__['os'], 'replace', wraps=os.replace) as replace, \
                 mock.patch.dict(QBIT['copy_managed_config'].__globals__,
                                 read_managed_config=lambda: rendered_managed_config()):
                QBIT['copy_managed_config'](paths['profile_home'])
                replace.assert_called_once()
            self.assertNotIn('stale profile data', config.read_text(encoding='utf-8'))
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_copy_rejects_unsafe_profile_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = QBIT['prepare_storage'](Path(directory))
            config = copy_profile(paths)
            for kind in ('symlink', 'hardlink', 'fifo'):
                config.unlink()
                source = Path(directory) / 'input'
                source.unlink(missing_ok=True)
                source.write_bytes(rendered_managed_config())
                if kind == 'symlink':
                    config.symlink_to(source)
                elif kind == 'hardlink':
                    os.link(source, config)
                elif kind == 'fifo':
                    os.mkfifo(config)
                with self.subTest(kind=kind), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    with mock.patch.dict(QBIT['copy_managed_config'].__globals__,
                                         read_managed_config=lambda: rendered_managed_config()):
                        QBIT['copy_managed_config'](paths['profile_home'])

    def test_install_policy_contains_the_managed_qt_style(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = QBIT['prepare_storage'](root)
            config = copy_profile(paths)
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(config, encoding='utf-8')
            self.assertEqual(parser['Appearance']['Style'], 'Fusion')
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_existing_transient_storage_is_preserved_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            account = pwd.struct_passwd(
                ("user", "x", os.getuid(), os.getgid(), "", str(home), "/bin/sh")
            )
            configured = home / "bittorrent-volume"
            configured.mkdir()
            self.assertEqual(QBIT["select_storage_root"](account, configured), configured)
            configured.rmdir()
            configured.symlink_to("/etc")
            with self.assertRaises(SystemExit):
                QBIT["select_storage_root"](account, configured)

    def test_removed_home_fallback_has_no_apparmor_write_grant(self):
        for path in (TARGET / 'etc/apparmor.d/desktop-wrappers.tmpl',
                     TARGET / 'etc/apparmor.d/abstractions/qbittorrent-runtime'):
            self.assertFalse('@{HOME}/bittorrent/' in path.read_text(encoding='utf-8'), str(path))

    def test_firewall_peer_port_has_no_packet_cap(self):
        overlay = (TARGET / "etc/nftables/services/qbittorrent.yml.tmpl").read_text()
        self.assertIn("- tcp", overlay)
        self.assertIn("- udp", overlay)
        self.assertIn("- __INSTALLER_LABWC_QBITTORRENT_PORT__", overlay)
        self.assertNotIn("rate_limit:", overlay)
        self.assertIn("qbittorrent)", (FORKY / "scripts/late/security.sh").read_text())

    def test_install_profile_peer_port_is_rendered_into_both_application_keys(self):
        for value in ('1024', '50308', '50309', '65535'):
            port = QBIT['configured_peer_port']({'LABWC_QBITTORRENT_PORT': value})
            with tempfile.TemporaryDirectory() as directory:
                paths = QBIT['prepare_storage'](Path(directory))
                config = copy_profile(paths, port=value)
                parser = configparser.ConfigParser(interpolation=None)
                parser.optionxform = str; parser.read(config, encoding='utf-8')
                self.assertEqual(parser['BitTorrent'][r'Session\Port'], value)
                self.assertEqual(parser['BitTorrent'][r'Session\AnnouncePort'], value)
        for value in ('', '22', '1023', '65536', '-50309', '050309', '50309;id', '9' * 1024):
            with self.subTest(invalid_port=value[:20]), self.assertRaises(SystemExit):
                QBIT['configured_peer_port']({'LABWC_QBITTORRENT_PORT': value})

    def test_profile_peer_port_reaches_the_actual_firewall_publisher_in_dash_and_ash(self):
        code = '''set -eu
QBIT_SEED=$1
installer_fatal() { printf '%s\\n' "$*" >&2; exit 91; }
. "$QBIT_SEED/scripts/common/modules/files-logging.sh"
. "$QBIT_SEED/scripts/common/target.sh"
. "$QBIT_SEED/scripts/late/target-assets.sh"
. "$QBIT_SEED/scripts/late/security.sh"
installer_repo_join_var() { printf '%s/hooks/target/%s\\n' "$QBIT_SEED" "$2"; }
fetch_hook() { cp "$1.tmpl" "$2"; }
stage_target_nftables_service_assets qbittorrent
'''
        ports = {QBIT['configured_peer_port']({'LABWC_QBITTORRENT_PORT':
                    next(line.split('=', 1)[1].strip('"') for line in profile.read_text(encoding='utf-8').splitlines()
                         if line.startswith('LABWC_QBITTORRENT_PORT='))})
                 for profile in (FORKY/'hosts/profiles').glob('*.env')}
        self.assertTrue(ports)
        shells = [['/bin/dash']]
        if shutil.which('busybox'):
            shells.append([shutil.which('busybox'), 'sh'])
        for shell in shells:
            for port in (*sorted(ports), 1024, 65535, 22, 65536, '050309', '50309;id'):
                with tempfile.TemporaryDirectory() as directory:
                    environment = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
                                   'INSTALLER_TARGET_DIR': directory, 'TMP_ENV_DIR': directory,
                                   'LABWC_QBITTORRENT_PORT': str(port)}
                    result = subprocess.run([*shell, '-c', code, 'qbit-port-fixture', str(FORKY)],
                        env=environment, capture_output=True, text=True, encoding='utf-8', timeout=10)
                    published = Path(directory)/'etc/nftables/services/qbittorrent.yml'
                    with self.subTest(shell=shell, port=port):
                        if type(port) is int and 1024 <= port <= 65535:
                            self.assertEqual(result.returncode, 0, result.stderr)
                            text = published.read_text(encoding='utf-8')
                            self.assertIn('    - ' + str(port) + '\n', text)
                            self.assertIn('- tcp', text); self.assertIn('- udp', text)
                            self.assertNotIn('__INSTALLER_', text)
                            self.assertEqual(published.stat().st_mode & 0o777, 0o644)
                        else:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertFalse(published.exists())

    def test_repeated_launch_sends_qt_ipc_without_starting_another_network_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            ipc = profile / '.config/qBittorrent/ipc-socket'
            ipc.parent.mkdir(parents=True)
            received = []
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(ipc)); server.listen(1); server.settimeout(5)
                def receive():
                    with server.accept()[0] as channel:
                        channel.settimeout(5)
                        payload = channel.recv(4096)
                        received.append(payload)
                        channel.sendall(b'a'); channel.sendall(b'ck')
                worker = threading.Thread(target=receive); worker.start()
                self.assertTrue(QBIT['forward_to_existing'](profile, ['magnet:?xt=urn:btih:fixture']))
                worker.join(timeout=5); self.assertFalse(worker.is_alive())
            self.assertEqual(received, [struct.pack('!I', 27) + b'magnet:?xt=urn:btih:fixture'])


    def test_concurrent_start_waits_for_first_instances_real_ipc(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)
            first_lock = QBIT['acquire_launch_lock'](profile, [])
            self.assertIsInstance(first_lock, int)
            ipc = profile/'.config/qBittorrent/ipc-socket'; ipc.parent.mkdir(parents=True)
            received = []
            def serve():
                time.sleep(.05)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                    server.bind(str(ipc)); server.listen(1); server.settimeout(5)
                    with server.accept()[0] as channel:
                        channel.settimeout(5); received.append(channel.recv(4096)); channel.sendall(b'ack')
            worker = threading.Thread(target=serve); worker.start()
            try:
                second = QBIT['acquire_launch_lock'](profile, ['magnet:?xt=urn:btih:fixture'])
                self.assertIsNone(second)
            finally:
                os.close(first_lock); worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(received, [struct.pack('!I', 27) + b'magnet:?xt=urn:btih:fixture'])

    def test_launcher_lock_rejects_a_symlink_or_unsafe_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory); outside = profile/'outside'
            outside.write_text('preserved', encoding='ascii')
            lock = profile/'.launcher.lock'; lock.symlink_to(outside)
            with self.assertRaises(OSError): QBIT['acquire_launch_lock'](profile, [])
            self.assertEqual(outside.read_text(encoding='ascii'), 'preserved')
            lock.unlink(); lock.write_text('', encoding='ascii'); lock.chmod(0o666)
            with self.assertRaises(SystemExit): QBIT['acquire_launch_lock'](profile, [])


    def test_external_fuzzel_geometry_across_profiles(self):
        profiles = sorted((FORKY / "hosts/profiles").glob("*.env"))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            with self.subTest(profile=path.name):
                assignments = dict(
                    line.split("=", 1) for line in path.read_text().splitlines()
                    if line.startswith("FUZZEL_") and "=" in line
                )
                for mode in ("LAUNCHER", "MENU"):
                    self.assertEqual(assignments[f"FUZZEL_{mode}_EXTERNAL_WIDTH"], '"60"')
                self.assertEqual(assignments["FUZZEL_EXTERNAL_FONT_SIZE"], '"19"')
                self.assertEqual(assignments["FUZZEL_EXTERNAL_LINE_HEIGHT"], '"32"')


if __name__ == "__main__":
    unittest.main()
