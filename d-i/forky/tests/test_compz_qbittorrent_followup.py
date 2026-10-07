"""Offline checks for the dedicated torrent launcher and display profile wiring."""
from __future__ import annotations

import configparser
import contextlib
import json
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

from payload_fixture import python_library

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / "hooks/target"
QBIT = runpy.run_path(str(TARGET / "usr/local/bin/labwc-qbittorrent"), run_name="test")
sys.path.insert(0, str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')))
from labwc_managed_app import network_namespace
LAUNCHERS = runpy.run_path(
    str(TARGET / "usr/local/bin/labwc-sync-application-launchers.tmpl"),
    run_name="test",
)


class TorrentIntegrationTests(unittest.TestCase):
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
            command = QBIT['build_command'](account, Path('/home/fixture/bittorrent'),
                                             Path('/home/fixture/bittorrent/.qbittorrent-profile'), 'launch', [],
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

    def test_absent_transient_storage_uses_private_persistent_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            account = pwd.struct_passwd(
                ("user", "x", os.getuid(), os.getgid(), "", str(home), "/bin/sh")
            )
            root = QBIT["select_storage_root"](account, home / "missing" / "bittorrent")
            self.assertEqual(root, home / "bittorrent")
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            paths = QBIT["prepare_storage"](root)
            config = QBIT["write_config"](paths["profile_home"], paths, ('tap0', '10.0.2.100'))
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(config)
            self.assertEqual(parser["BitTorrent"][r"Session\Port"], "50309")
            for key in (r"Session\DHTEnabled", r"Session\PeXEnabled",
                        r"Session\LSDEnabled", r"Session\UseRandomPort",
                        r"Session\UseUPnP", r"Session\ValidateHTTPSTrackerCertificate"):
                self.assertEqual(parser["BitTorrent"][key],
                                 "true" if "Validate" in key else "false")
            self.assertEqual(parser["Preferences"][r"WebUI\Enabled"], "false")
            self.assertEqual(parser['BitTorrent'][r'Session\Interface'], 'tap0')
            self.assertEqual(parser['BitTorrent'][r'Session\InterfaceAddress'], '10.0.2.100')
            for key in (r'Session\AnnounceToAllTiers', r'Session\AnnounceToAllTrackers'):
                self.assertEqual(parser['BitTorrent'][key], 'false')

    def test_saved_adwaita_style_is_replaced_and_unrelated_preferences_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = QBIT['prepare_storage'](root)
            profile = paths['profile_home']
            config = QBIT['write_config'](profile, paths, ('tap0', '10.0.2.100'))
            config.write_text('[Appearance]\nStyle=Adwaita\n[Preferences]\nGeneral\\Locale=sv\n',
                              encoding='utf-8')
            QBIT['write_config'](profile, paths, ('tap0', '10.0.2.100'))
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(config, encoding='utf-8')
            self.assertEqual(parser['Appearance']['Style'], 'Fusion')
            self.assertEqual(parser['Preferences'][r'General\Locale'], 'sv')
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
            self.assertEqual(QBIT["select_storage_root"](account, configured), configured)
            with self.assertRaises(SystemExit):
                QBIT["prepare_storage"](configured)

    def test_firewall_peer_port_has_no_packet_cap(self):
        overlay = (TARGET / "etc/nftables/services/qbittorrent.yml.tmpl").read_text()
        self.assertIn("- tcp", overlay)
        self.assertIn("- udp", overlay)
        self.assertIn("- __INSTALLER_LABWC_QBITTORRENT_PORT__", overlay)
        self.assertNotIn("rate_limit:", overlay)
        self.assertIn("qbittorrent)", (FORKY / "scripts/late/security.sh").read_text())

    def test_profile_peer_port_is_validated_and_used_by_both_application_keys(self):
        for value in ('1024', '50308', '50309', '65535'):
            port = QBIT['configured_peer_port']({'LABWC_QBITTORRENT_PORT': value})
            with tempfile.TemporaryDirectory() as directory:
                paths = QBIT['prepare_storage'](Path(directory))
                config = QBIT['write_config'](paths['profile_home'], paths, ('tap0', '10.0.2.100'), port)
                parser = configparser.ConfigParser(interpolation=None)
                parser.optionxform = str; parser.read(config, encoding='utf-8')
                self.assertEqual(parser['BitTorrent'][r'Session\Port'], value)
                self.assertEqual(parser['Preferences'][r'Connection\PortRangeMin'], value)
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

    def test_route_binding_uses_the_active_source_and_rejects_non_internet_routes(self):
        for interface, source, accepted in (('eth0', '192.168.50.88', True),
                                           ('wg0', '10.64.0.2', True),
                                           ('tailscale0', '100.65.244.106', False),
                                           ('lo', '127.0.0.1', False),
                                           ('eth0', '169.254.1.2', False)):
            result = subprocess.CompletedProcess([], 0, json.dumps([{'dev': interface, 'prefsrc': source}]).encode(), b'')
            with self.subTest(interface=interface), mock.patch.object(subprocess, 'run', return_value=result) as execute:
                if accepted:
                    self.assertEqual(QBIT['network_binding'](), (interface, source))
                else:
                    with self.assertRaises(SystemExit): QBIT['network_binding']()
                self.assertEqual(execute.call_args.args[0],
                                 ['/usr/sbin/ip', '-j', '-4', 'route', 'get', '1.1.1.1'])
                self.assertEqual(execute.call_args.kwargs['timeout'], 5)

    def test_route_lookup_fails_closed_on_timeout_invalid_or_missing_route(self):
        for output in (b'{}', b'[]', b'not json', b'x' * 16385,
                       b'[{"dev":"eth0","prefsrc":true}]', b'[{"dev":"eth0","prefsrc":3232235777}]'):
            with mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, b'')):
                with self.assertRaises(SystemExit): QBIT['network_binding']()
        with mock.patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('ip', 5)):
            with self.assertRaises(SystemExit): QBIT['network_binding']()
        with mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, b'', b'')):
            with self.assertRaises(SystemExit): QBIT['network_binding']()

    def test_private_dns_keeps_only_servers_on_the_selected_route(self):
        binding = ('eth0', '192.168.50.88')
        config = (b'nameserver 127.0.0.53\nnameserver 2001:db8::53\n'
                  b'nameserver 100.100.100.100\nnameserver 10.64.0.1\n'
                  b'nameserver 192.168.50.1\nnameserver 192.168.50.1\n')
        routes = {'100.100.100.100': ('tailscale0', '100.65.244.106'),
                  '10.64.0.1': ('wg0', '10.64.0.2'),
                  '192.168.50.1': binding}
        globals_ = QBIT['select_routed_dns_servers'].__globals__
        with mock.patch.dict(globals_, {'route_binding': lambda address: routes[address]}):
            self.assertEqual(QBIT['select_routed_dns_servers'](config, binding),
                             ['192.168.50.1'])
            with self.assertRaises(SystemExit):
                QBIT['select_routed_dns_servers'](b'nameserver 127.0.0.53\n'
                    b'nameserver 100.100.100.100\n', binding)

    def test_private_dns_is_mounted_and_disables_slirp_host_dns_proxy(self):
        account = pwd.struct_passwd(('fixture', 'x', os.getuid(), os.getgid(), '',
                                     '/home/fixture', '/bin/sh'))
        with tempfile.TemporaryDirectory() as directory:
            captured = []
            def launch(*args, **kwargs):
                command = args[0]
                resolver = Path(command[command.index('--ro-bind') + 1])
                captured.append((resolver.read_text(encoding='ascii'), kwargs))
                return 0
            runtime = types.SimpleNamespace(SLIRP4NETNS_BINARY='/usr/bin/true',
                                            run_slirp4netns_sandbox=launch)
            globals_ = QBIT['run_new_instance'].__globals__
            with mock.patch.dict(globals_, {'network_binding': lambda: ('eth0', '192.168.50.88'),
                                           'routed_dns_servers': lambda binding: ['192.168.50.1'],
                                           'write_config': mock.Mock(), 'network_runtime': lambda: runtime,
                                           'build_command': lambda *args: ['bwrap', '--ro-bind',
                                               str(args[-1]), '/etc/resolv.conf', 'qbittorrent']}), \
                 mock.patch.object(tempfile, 'TemporaryDirectory',
                                   return_value=contextlib.nullcontext(directory)), \
                 mock.patch.object(Path, 'lstat', return_value=types.SimpleNamespace(
                     st_mode=stat.S_IFREG | 0o755, st_uid=0)), \
                 mock.patch.object(QBIT['run_new_instance'].__globals__['signal'], 'signal'):
                self.assertEqual(QBIT['run_new_instance'](account, Path(directory),
                    {'profile_home': Path(directory)}, 'launch', [], 50309), 0)
            self.assertEqual(captured[0][0],
                             'nameserver 192.168.50.1\noptions timeout:2 attempts:2\n')
            self.assertEqual(captured[0][1]['peer_forward'], ('192.168.50.88', 50309))
            self.assertTrue(captured[0][1]['disable_dns'])

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

    def test_peer_forward_api_installs_tcp_and_udp_only_on_the_route_address(self):
        with tempfile.TemporaryDirectory() as directory:
            api = str(Path(directory) / 'api')
            received = []
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(api); server.listen(2); server.settimeout(5)
                def receive():
                    for _ in range(2):
                        with server.accept()[0] as channel:
                            channel.settimeout(5)
                            payload = bytearray()
                            while chunk := channel.recv(4096): payload.extend(chunk)
                            received.append(json.loads(payload))
                            channel.sendall(b'{"return":{"id":1}}')
                worker = threading.Thread(target=receive); worker.start()
                network_namespace.configure_peer_forward(api, '192.168.50.88', 50309)
                worker.join(timeout=5); self.assertFalse(worker.is_alive())
            self.assertEqual([item['arguments']['proto'] for item in received], ['tcp', 'udp'])
            for item in received:
                self.assertEqual(item['arguments']['host_addr'], '192.168.50.88')
                self.assertEqual(item['arguments']['guest_addr'], '10.0.2.100')
                self.assertEqual(item['arguments']['host_port'], 50309)
                self.assertEqual(item['arguments']['guest_port'], 50309)
            self.assertEqual(Path(api).stat().st_mode & 0o777, 0o600)

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

    def test_failed_forward_never_releases_the_payload_and_reaps_both_children(self):
        bwrap, slirp = mock.Mock(), mock.Mock()
        bwrap.poll.return_value = slirp.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(network_namespace.subprocess, 'Popen', side_effect=[bwrap, slirp]) as launch, \
                mock.patch.object(network_namespace, '_read_bwrap_sandbox_pid', return_value=1234), \
                mock.patch.object(network_namespace.os, 'pidfd_open', return_value=None), \
                mock.patch.object(network_namespace, '_wait_for_slirp4netns_ready'), \
                mock.patch.object(network_namespace, 'configure_peer_forward', side_effect=SystemExit(1)), \
                mock.patch.object(network_namespace.os, 'write') as release, \
                self.assertRaises(SystemExit):
            network_namespace.run_slirp4netns_sandbox(
                ['/usr/bin/bwrap', '--unshare-all'], ['/usr/bin/qbittorrent'], directory, (),
                slirp_binary='/usr/bin/slirp4netns', peer_forward=('192.168.50.88', 50309),
                disable_dns=True)
        release.assert_not_called()
        bwrap.terminate.assert_called_once()
        bwrap.wait.assert_called()
        slirp.wait.assert_called()
        helper_command = launch.call_args_list[1].args[0]
        self.assertIn('--disable-host-loopback', helper_command)
        self.assertIn('--disable-dns', helper_command)
        self.assertIn('--outbound-addr=192.168.50.88', helper_command)
        self.assertIn('--api-socket', helper_command)

    def test_invalid_peer_policy_has_no_listener_or_namespace_side_effects(self):
        for address, port in (('127.0.0.1', 50309), ('0.0.0.0', 50309), ('169.254.1.1', 50309),
                              ('::1', 50309), (3232235777, 50309), (True, 50309),
                              ('255.255.255.255', 50309), ('192.168.1.2', True), ('192.168.1.2', 22)):
            with self.subTest(address=address, port=port), \
                    mock.patch.object(network_namespace.subprocess, 'Popen') as launch, \
                    self.assertRaises(SystemExit):
                network_namespace.run_slirp4netns_sandbox([], [], '/unused', (),
                    slirp_binary='/usr/bin/slirp4netns', peer_forward=(address, port))
            launch.assert_not_called()

    def test_packaged_slirp_forwards_tcp_and_udp_to_a_real_private_payload(self):
        for executable in ('/usr/bin/bwrap', '/usr/bin/slirp4netns', '/usr/bin/python3', '/dev/net/tun'):
            if executable == '/dev/net/tun' and not Path(executable).exists():
                self.skipTest('host TUN device unavailable; no live packet forwarding was exercised')
            if executable == '/dev/net/tun':
                continue
            if not Path(executable).is_file():
                self.skipTest('fixture prerequisite unavailable: ' + executable)
        command = ['/usr/bin/bwrap', '--unshare-all', '--cap-drop', 'ALL', '--new-session',
                   '--die-with-parent', '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev']
        probe = subprocess.run([*command, '/usr/bin/true'], capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('private namespaces unavailable: ' + probe.stderr.decode('utf-8', 'replace')[:300])
        # Reserve the same ephemeral loopback port for both transports. The
        # policy validator is mocked ONLY to keep this inert fixture off LAN;
        # its production rejection of loopback is covered independently above.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            tcp.bind(('127.0.0.1', 0))
            port = tcp.getsockname()[1]
            udp.bind(('127.0.0.1', port))
        payload = '''import socket,sys
port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
    tcp.bind(('10.0.2.100', port)); tcp.listen(1); tcp.settimeout(5)
    udp.bind(('10.0.2.100', port)); udp.settimeout(5)
    channel, _ = tcp.accept()
    with channel:
        channel.settimeout(5); channel.sendall(channel.recv(64))
    message, address = udp.recvfrom(64); udp.sendto(message, address)
'''
        received, errors = [], []
        def exchange():
            try:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        channel = socket.create_connection(('127.0.0.1', port), timeout=1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.05)
                with channel:
                    channel.settimeout(5); channel.sendall(b'private-tcp')
                    received.append(channel.recv(64))
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                    udp.settimeout(5); udp.sendto(b'private-udp', ('127.0.0.1', port))
                    received.append(udp.recvfrom(64)[0])
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=exchange)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(network_namespace, 'validate_peer_forward', return_value='127.0.0.1'):
            try:
                result = network_namespace.run_slirp4netns_sandbox(command,
                    ['/usr/bin/python3', '-I', '-B', '-c', payload, str(port)], directory, (),
                    slirp_binary='/usr/bin/slirp4netns', peer_forward=('127.0.0.1', port),
                    pre_payload_check=worker.start)
            finally:
                if worker.ident is not None:
                    worker.join(timeout=12)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result, 0)
            self.assertEqual(received, [b'private-tcp', b'private-udp'])

    def test_real_failed_helper_kills_the_blocked_namespace_before_pipe_eof(self):
        if not Path('/usr/bin/bwrap').is_file():
            self.skipTest('Bubblewrap unavailable')
        command = ['/usr/bin/bwrap', '--unshare-all', '--cap-drop', 'ALL', '--die-with-parent',
                   '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev']
        probe = subprocess.run([*command, '/usr/bin/true'], capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('private namespaces unavailable: ' + probe.stderr.decode('utf-8', 'replace')[:300])
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(network_namespace, 'validate_peer_forward', return_value='127.0.0.1'):
            marker = Path(directory) / 'payload-started'
            with self.assertRaises(SystemExit):
                network_namespace.run_slirp4netns_sandbox(
                    [*command, '--bind', directory, directory],
                    ['/usr/bin/python3', '-I', '-B', '-c',
                     'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("started",encoding="ascii")', str(marker)],
                    directory, (), slirp_binary='/usr/bin/false', peer_forward=('127.0.0.1', 50309))
            self.assertFalse(marker.exists(), 'setup failure executed the blocked payload')

    def test_real_failed_namespace_pin_does_not_execute_the_payload(self):
        if not Path('/usr/bin/bwrap').is_file():
            self.skipTest('Bubblewrap unavailable')
        command = ['/usr/bin/bwrap', '--unshare-all', '--cap-drop', 'ALL', '--die-with-parent',
                   '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev']
        probe = subprocess.run([*command, '/usr/bin/true'], capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('private namespaces unavailable: ' + probe.stderr.decode('utf-8', 'replace')[:300])
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(network_namespace, 'validate_peer_forward', return_value='127.0.0.1'), \
                mock.patch.object(network_namespace.os, 'pidfd_open', side_effect=OSError('fixture pin failure')):
            marker = Path(directory) / 'payload-started'
            with self.assertRaises(SystemExit):
                network_namespace.run_slirp4netns_sandbox(
                    [*command, '--bind', directory, directory],
                    ['/usr/bin/python3', '-I', '-B', '-c',
                     'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("started",encoding="ascii")', str(marker)],
                    directory, (), slirp_binary='/usr/bin/false', peer_forward=('127.0.0.1', 50309))
            deadline = time.monotonic() + 1
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(marker.exists(), 'failed namespace pin executed the payload')

    def test_real_peer_startup_gate_preserves_arguments_and_execs_after_readiness(self):
        if not Path('/usr/bin/bwrap').is_file():
            self.skipTest('Bubblewrap unavailable')
        command = ['/usr/bin/bwrap', '--unshare-all', '--cap-drop', 'ALL', '--die-with-parent',
                   '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev']
        probe = subprocess.run([*command, '/usr/bin/true'], capture_output=True, timeout=5)
        if probe.returncode:
            self.skipTest('private namespaces unavailable: ' + probe.stderr.decode('utf-8', 'replace')[:300])
        real_popen = subprocess.Popen
        def launch(argv, **kwargs):
            if argv[0] == '/usr/bin/slirp4netns':
                # Only network readiness is simulated; Bubblewrap, the gate
                # interpreter, exec and child cleanup all execute locally.
                argv = ['/usr/bin/python3', '-I', '-B', '-c', 'import time; time.sleep(10)']
            return real_popen(argv, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'payload-started'
            literal = 'literal;$(not-a-command)'
            def configured(*args):
                self.assertFalse(marker.exists(), 'payload ran before forwarding readiness')
            with mock.patch.object(network_namespace, 'validate_peer_forward', return_value='127.0.0.1'), \
                    mock.patch.object(network_namespace.subprocess, 'Popen', side_effect=launch), \
                    mock.patch.object(network_namespace, '_wait_for_slirp4netns_ready'), \
                    mock.patch.object(network_namespace, 'configure_peer_forward', side_effect=configured) as forward:
                result = network_namespace.run_slirp4netns_sandbox(
                    [*command, '--bind', directory, directory],
                    ['/usr/bin/python3', '-I', '-B', '-c',
                     'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2],encoding="ascii")',
                     str(marker), literal], directory, (), slirp_binary='/usr/bin/slirp4netns',
                    peer_forward=('127.0.0.1', 50309))
            self.assertEqual(result, 0)
            forward.assert_called_once()
            self.assertEqual(marker.read_text(encoding='ascii'), literal)

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
