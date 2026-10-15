"""Kernel networking contracts: offline administration mocks and real local IPC.

No host routes, firewall rules, services, or namespaces are changed here.
"""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import array
import contextlib
import importlib.util
import ipaddress
import io
import json
import os
import pwd
import grp
import re
from pathlib import Path
import runpy
import select
import shlex
import signal
import socket
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

from payload_fixture import python_library, read_text, network_identity_text, network_identity_environment, network_identity_values

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / "hooks/target"
LIBRARY = python_library(TARGET / "usr/local/lib/python3.14/dist-packages")
sys.path.insert(0, str(LIBRARY))
import app_veth_policy as policy_parser
from labwc_managed_app import network_client as client
from labwc_managed_app import network_namespace as supervisor
from labwc_managed_app import generic, profiles, sandbox

DEFAULT_CONFIG_RAW = network_identity_text((TARGET / "etc/app-veth.json.tmpl").read_text(encoding="utf-8")).replace(
    "__INSTALLER_ACCOUNT_USERNAME__", "desktop").replace("__INSTALLER_LABWC_QBITTORRENT_PORT__", "50309")
DEFAULT_CONFIGURATION = policy_parser.parse_configuration(DEFAULT_CONFIG_RAW.encode())
DEFAULT_POLICIES = DEFAULT_CONFIGURATION["apps"]


def fixture_raw(apps):
    """Complete current policy with explicit, isolated fixture reservations."""
    pool = ipaddress.IPv4Network(DEFAULT_CONFIGURATION["network"]["ipv4_cidr"])
    return json.dumps({"version": 2, "desktop_user": "desktop",
                       "network": DEFAULT_CONFIGURATION["network"],
                       "apps": {name: {"slots": [slot],
                                       "addresses": [str(pool.network_address + slot * 4 + 2)], **policy}
                                for slot, (name, policy) in enumerate(apps.items())}}).encode()


def fixture_configuration(apps):
    return policy_parser.parse_configuration(fixture_raw(apps))


broker = types.ModuleType("tested_veth_broker")
broker.__file__ = str(TARGET / "usr/local/sbin/app-veth")
exec(compile(Path(broker.__file__).read_text(encoding="utf-8"), broker.__file__, "exec"), broker.__dict__)
# Read canonical fixture bytes, never the image/host installed ruleset.
broker.read_ruleset_template = lambda: network_identity_text(
    (TARGET / "etc/app-veth.nft.tmpl").read_text(encoding="ascii"))
broker.apply_network_identity(DEFAULT_CONFIGURATION["network"])
podman_adapter = types.ModuleType("tested_podman_adapter")
podman_adapter.__file__ = str(TARGET / "usr/local/libexec/app-veth-podman")
exec(compile(Path(podman_adapter.__file__).read_text(encoding="utf-8"), podman_adapter.__file__, "exec"), podman_adapter.__dict__)


class PolicyParsingTests(unittest.TestCase):
    def parse(self, apps):
        return fixture_configuration(apps)

    def test_typed_policy_defaults_and_optional_peer_forwarding(self):
        rows = self.parse({"future-client": {"network": True, "peer_port": 4242,
                                           "executables": ["/opt/future-client/client"]},
                           "offline": {"network": False}})["apps"]
        self.assertTrue(rows["future-client"]["pin_route"])
        self.assertEqual(rows["future-client"]["executables"], ("/opt/future-client/client",))
        self.assertIsNone(rows["offline"]["peer_port"])

    def test_qbittorrent_accepts_exact_distinct_ethernet_wifi_ports(self):
        ports = {"ethernet": 50309, "wifi": 50409}
        row = self.parse({"qbittorrent": {"network": True, "peer_port": ports}})["apps"]["qbittorrent"]
        self.assertEqual(row["peer_port"], ports)
        self.assertTrue(row["pin_route"])
        invalid = ({"ethernet": 50309}, {"ethernet": 50309, "wifi": 50309},
                   {"ethernet": True, "wifi": 50409}, {"ethernet": 50309, "wifi": 65536},
                   {"ethernet": 50309, "wifi": "50409"}, {**ports, "extra": 50410})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse({"qbittorrent": {"network": True, "peer_port": value}})
        with self.assertRaises(ValueError):
            self.parse({"future-client": {"network": True, "peer_port": ports}})

    def test_explicit_slots_are_stable_across_launch_order_and_reuse(self):
        rows = DEFAULT_POLICIES
        self.assertEqual(broker.application_slot(rows['qbittorrent'], {}), 28)
        self.assertEqual(rows['qbittorrent']['addresses'], ('10.203.0.114',))
        active = {'browser': types.SimpleNamespace(slot=4), 'code': types.SimpleNamespace(slot=6)}
        self.assertEqual(broker.application_slot(rows['qbittorrent'], active), 28)
        active['torrent'] = types.SimpleNamespace(slot=28)
        with self.assertRaisesRegex(ValueError, 'reserved network slots'):
            broker.application_slot(rows['qbittorrent'], active)
        del active['torrent']
        self.assertEqual(broker.application_slot(rows['qbittorrent'], active), 28)
        self.assertEqual(broker.application_slot(rows['chromium'], active), 5)
        active['second-browser'] = types.SimpleNamespace(slot=5)
        with self.assertRaisesRegex(ValueError, 'reserved network slots'):
            broker.application_slot(rows['chromium'], active)
        del active['browser']
        self.assertEqual(broker.application_slot(rows['chromium'], active), 4)

    def test_builtin_apps_have_two_slots_with_singleton_qbittorrent_and_future_capacity(self):
        self.assertEqual(len(DEFAULT_POLICIES), 24)
        used = set()
        for app, policy in DEFAULT_POLICIES.items():
            with self.subTest(app=app):
                self.assertEqual(len(policy['slots']), 1 if app == 'qbittorrent' else 2)
                self.assertFalse(used.intersection(policy['slots']))
                used.update(policy['slots'])
        self.assertEqual(used, set(range(47)))
        self.assertEqual(DEFAULT_CONFIGURATION['network']['max_leases'], 128)
        self.assertEqual(len(set(range(128)) - used), 81)

    def test_future_apps_accept_unused_slots_without_a_builtin_allowlist(self):
        source = json.loads(DEFAULT_CONFIG_RAW)
        source['apps']['future-client'] = {
            'network': True, 'executables': ['/opt/future-client/client'],
            'slots': [47, 48], 'addresses': ['10.203.0.190', '10.203.0.194']}
        policy = policy_parser.parse_configuration(json.dumps(source).encode())['apps']['future-client']
        self.assertEqual(broker.application_slot(policy, {}), 47)
        occupied = {'first': types.SimpleNamespace(slot=47)}
        self.assertEqual(broker.application_slot(policy, occupied), 48)
        occupied['second'] = types.SimpleNamespace(slot=48)
        with self.assertRaisesRegex(ValueError, 'reserved network slots'):
            broker.application_slot(policy, occupied)

    def test_route_pinning_and_peer_forwarding_require_singleton_slots(self):
        for settings in ({'pin_route': True}, {'peer_port': 4242}):
            source = json.loads(DEFAULT_CONFIG_RAW)
            source['apps']['bitwarden'].update(settings)
            with self.subTest(settings=settings), self.assertRaisesRegex(ValueError, 'reserved application network slots'):
                policy_parser.parse_configuration(json.dumps(source).encode())

    def test_reconnection_uses_its_own_exact_reserved_slot(self):
        policy = DEFAULT_POLICIES['chromium']
        self.assertEqual(broker.application_slot(policy, {}, policy['addresses'][1]), policy['slots'][1])
        occupied = {'other-instance': types.SimpleNamespace(slot=policy['slots'][1])}
        with self.assertRaisesRegex(ValueError, 'slot is in use'):
            broker.application_slot(policy, occupied, policy['addresses'][1])
        for address in (DEFAULT_POLICIES['qbittorrent']['addresses'][0], [], '10.203.0.999'):
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, 'not reserved'):
                broker.application_slot(policy, {}, address)

    def test_version_two_rejects_missing_unsafe_and_colliding_identities(self):
        source = json.loads(DEFAULT_CONFIG_RAW)
        for field, value in (('ipv4_cidr', '192.0.2.0/24'), ('ipv4_cidr', '10.203.0.1/24'),
                             ('max_leases', True), ('max_leases', 44), ('max_leases', 129),
                             ('host_interface_prefix', 'veth;exec'), ('namespace_interface', 'lo'),
                             ('dns_address', '10.203.0.2'), ('dns_host_address', '0.0.0.0')):
            conf = json.loads(DEFAULT_CONFIG_RAW)
            conf['network'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                policy_parser.parse_configuration(json.dumps(conf).encode())
        for slots in ([], [True], [64], [0, 0], [4]):
            conf = json.loads(DEFAULT_CONFIG_RAW)
            conf['apps']['bitwarden']['slots'] = slots
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                policy_parser.parse_configuration(json.dumps(conf).encode())
        del source['network']
        with self.assertRaises(ValueError):
            policy_parser.parse_configuration(json.dumps(source).encode())
        for version in (1, 3):
            source = json.loads(DEFAULT_CONFIG_RAW)
            source['version'] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                policy_parser.parse_configuration(json.dumps(source).encode())
        source = json.loads(DEFAULT_CONFIG_RAW)
        del source['apps']['bitwarden']['slots']
        with self.assertRaises(ValueError):
            policy_parser.parse_configuration(json.dumps(source).encode())
        for addresses in (None, [], ['10.203.0.6'], ['010.203.0.2', '10.203.0.6']):
            source = json.loads(DEFAULT_CONFIG_RAW)
            source['apps']['bitwarden']['addresses'] = addresses
            with self.subTest(addresses=addresses), self.assertRaises(ValueError):
                policy_parser.parse_configuration(json.dumps(source).encode())

    def test_configured_subnet_conflict_never_selects_a_different_address_pool(self):
        with mock.patch.object(broker, 'run', return_value='[{"dst":"10.203.0.0/16"}]'):
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                broker.select_pool()
        with mock.patch.object(broker, 'run', return_value='[{"dst":"default"}]'):
            self.assertEqual(str(broker.select_pool()), '10.203.0.0/23')
        with mock.patch.object(broker, 'run', return_value='[{"dst":"0.0.0.0/1","dev":"tun0"},{"dst":"128.0.0.0/1","dev":"tun0"}]'):
            self.assertEqual(str(broker.select_pool()), '10.203.0.0/23')

    def test_unknown_keys_malformed_flags_ports_paths_and_duplicates_fail_closed(self):
        bad = ({}, {"network": "true"}, {"network": True, "block_lan": 1},
               {"network": True, "pin_route": "false"}, {"network": True, "peer_port": True},
               {"network": True, "peer_port": 1023}, {"network": True, "peer_port": 65536},
               {"network": False, "peer_port": 4242}, {"network": True, "peer_port": 4242, "pin_route": False},
               {"network": True, "shell": "malicious"}, {"network": True, "executables": ["/tmp/app"]},
               {"network": True, "executables": ["/opt/../tmp/app"]},
               {"network": True, "executables": ["/usr/bin/app", "/usr/bin/app"]})
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.parse({"client": row})
        with self.assertRaises(ValueError):
            self.parse({"../client": {"network": True}})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            policy_parser.parse_configuration(b'{"version":2,"desktop_user":"desktop","apps":{"client":{"network":true,"network":false}}}')
        with self.assertRaises(ValueError):
            policy_parser.parse_configuration(b"x" * (policy_parser.MAX_CONFIG_BYTES + 1))

    def test_real_file_reload_and_unsafe_symlink_mode_and_hardlink_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            def write(apps):
                path.write_bytes(fixture_raw(apps))
                path.chmod(0o644)
            write({"future-client": {"network": True}})
            self.assertIn("future-client", policy_parser.read_configuration(str(path), owner_uid=os.getuid())["apps"])
            write({})
            self.assertEqual(policy_parser.read_configuration(str(path), owner_uid=os.getuid())["apps"], {})
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                policy_parser.read_configuration(str(path), owner_uid=os.getuid())
            path.chmod(0o644)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                policy_parser.read_configuration(str(link), owner_uid=os.getuid())
            os.link(path, Path(directory) / "hardlink")
            with self.assertRaises(ValueError):
                policy_parser.read_configuration(str(path), owner_uid=os.getuid())


class ConfigurationPublisherTests(unittest.TestCase):
    """Exercise the production POSIX map renderer, not string replacement."""

    def render(self, directory, *, account="desktop", port=None, app_veth_override=None, network_overrides=None):
        script = r'''
set -eu
. "$1/scripts/common/modules/files-logging.sh"
. "$1/scripts/late/target-assets.sh"
. "$1/scripts/late/security.sh"
. "$1/scripts/common/modules/app-veth-identity.sh"
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
TMP_ENV_DIR=$2
cp "$1/hooks/target/etc/app-veth.json.tmpl" "$2/config.json"
apply_placeholder_map_to_target "$2/config.json" app_veth_placeholder_map
installer_assert_no_unresolved_installer_placeholders "$2/config.json" app-veth
cp "$1/hooks/target/etc/nftables/profiles/desktop.yml.tmpl" "$2/firewall.yml"
apply_placeholder_map_to_target "$2/firewall.yml" nftables_app_veth_profile_placeholder_map
cp "$1/hooks/target/etc/NetworkManager/conf.d/70-app-veth.conf.tmpl" "$2/network-manager.conf"
apply_placeholder_map_to_target "$2/network-manager.conf" app_veth_identity_placeholder_map
cp "$1/hooks/target/etc/apparmor.d/app-veth.tmpl" "$2/apparmor.conf"
apply_placeholder_map_to_target "$2/apparmor.conf" app_veth_identity_placeholder_map
'''
        environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C",
                       "ACCOUNT_USERNAME": account, **network_identity_environment()}
        environment.update(network_overrides or {})
        if port is not None:
            environment["LABWC_QBITTORRENT_PORT"] = port
        if app_veth_override is not None:
            environment["APP_VETH_OVERRIDE"] = app_veth_override
        shells = [["/bin/sh"]]
        if shutil.which("busybox"):
            shells.append([shutil.which("busybox"), "sh"])
        for shell in shells:
            with self.subTest(shell=shell):
                yield subprocess.run([*shell, "-c", script, "fixture", str(SEED), str(directory)],
                                     env=environment, capture_output=True, text=True, timeout=10)

    def test_default_and_explicit_ports_render_valid_broker_configuration(self):
        for port in (None, "1024", "50309", "65535"):
            with self.subTest(port=port), tempfile.TemporaryDirectory() as directory:
                for result in self.render(directory, port=port):
                    self.assertEqual(result.returncode, 0, result.stderr)
                    path = Path(directory) / "config.json"
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual(data["desktop_user"], "desktop")
                    self.assertEqual(data["version"], 2)
                    self.assertEqual(data["apps"]["qbittorrent"]["peer_port"], int(port or "50309"))
                    self.assertNotIn("keepassxc", data["apps"])
                    import yaml
                    host_policy = yaml.safe_load((Path(directory)/'firewall.yml').read_text())['app_veth']
                    self.assertEqual(host_policy['interfaces'], [f'veth{slot}-app' for slot in range(data['network']['max_leases'])])
                    self.assertEqual(host_policy['dns_host_address'], data['network']['dns_host_address'])
                    self.assertEqual(host_policy['dns_host_port'], data['network']['dns_host_port'])
                    for name in ('config.json', 'firewall.yml', 'network-manager.conf', 'apparmor.conf'):
                        self.assertNotIn('__INSTALLER_', (Path(directory)/name).read_text())
                    # Target-root ownership is modeled here; the parser itself
                    # and the rendered bytes are production code.
                    metadata = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_nlink=1)
                    with mock.patch.object(broker, "CONFIG", str(path)), \
                            mock.patch.object(broker.os, "fstat", return_value=metadata), \
                            mock.patch.object(broker.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=1000)):
                        self.assertEqual(broker.configuration(), (1000, policy_parser.parse_configuration(path.read_bytes())["apps"]))

    def test_invalid_network_policy_fails_during_rendering(self):
        for account, port in (("root", "50309"), ("desktop", "1023"), ("desktop", "65536"),
                              ("desktop", "050309"), ("desktop", "50309\nmalformed"),
                              ("desktop", "50309,50309"), ("desktop", "50309,65536"),
                              ("desktop", "50309,50409,50410")):
            with self.subTest(account=account, port=port), tempfile.TemporaryDirectory() as directory:
                for result in self.render(directory, account=account, port=port):
                    self.assertNotEqual(result.returncode, 0)

    def test_each_profile_pair_renders_the_typed_qbittorrent_policy(self):
        for port in ("50308,50408", "50309,50408", "50309,50409", "50309,50410"):
            with self.subTest(port=port), tempfile.TemporaryDirectory() as directory:
                for result in self.render(directory, port=port):
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = (Path(directory) / "config.json").read_bytes()
                    row = policy_parser.parse_configuration(data)["apps"]["qbittorrent"]
                    self.assertEqual(row["peer_port"], dict(zip(("ethernet", "wifi"), map(int, port.split(',')))))
                    self.assertEqual(row["slots"], (28,))

    def test_app_veth_override_renders_only_selected_two_slot_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            for result in self.render(directory, app_veth_override="bitwarden,vivaldi"):
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads((Path(directory) / "config.json").read_text(encoding="utf-8"))
                self.assertEqual(set(data["apps"]), {"bitwarden", "vivaldi"})
                self.assertEqual(data["apps"]["bitwarden"]["slots"], [0, 1])
                self.assertEqual(data["apps"]["vivaldi"]["slots"], [2, 3])
                self.assertEqual(data["apps"]["vivaldi"]["addresses"],
                                 ["10.203.0.10", "10.203.0.14"])
                self.assertNotIn("__INSTALLER_", (Path(directory) / "config.json").read_text(encoding="ascii"))

    def test_f2fs_host_profiles_keep_spare_slots_and_render_all_identity_consumers(self):
        for name in ('f2fs-de-hp14', 'f2fs-de-hp14-duo', 'f2fs-de-x360', 'f2fs-de-x360-duo'):
            text = (SEED / 'hosts/profiles' / (name + '.env')).read_text(encoding='utf-8')
            overrides = {key: shlex.split(value)[0] for key, value in
                         re.findall(r'^(APP_VETH_[A-Z0-9_]+)=(.*)$', text, re.M) if shlex.split(value)[0]}
            with self.subTest(profile=name), tempfile.TemporaryDirectory() as directory:
                for result in self.render(directory, network_overrides=overrides):
                    self.assertEqual(result.returncode, 0, result.stderr)
                    data = policy_parser.parse_configuration((Path(directory) / 'config.json').read_bytes())
                    self.assertEqual(set(data['apps']), set(overrides['APP_VETH_OVERRIDE'].split(',')))
                    self.assertEqual(len(data['apps']), 7)
                    self.assertTrue(all(len(policy['slots']) == 2 for policy in data['apps'].values()))
                    self.assertEqual(data['network']['max_leases'], 64)
                    self.assertEqual(sum(len(policy['slots']) for policy in data['apps'].values()), 14)
                    import yaml
                    firewall = yaml.safe_load((Path(directory) / 'firewall.yml').read_text(encoding='utf-8'))['app_veth']
                    self.assertEqual(len(firewall['interfaces']), 64)
                    for asset in ('config.json', 'firewall.yml', 'network-manager.conf', 'apparmor.conf'):
                        self.assertNotIn('__INSTALLER_', (Path(directory) / asset).read_text(encoding='utf-8'))

    def test_config_check_cli_validates_without_network_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(DEFAULT_CONFIG_RAW, encoding="ascii")
            open_file = os.open
            def mapped_open(value, flags, *arguments, **options):
                return open_file(path if value == "/etc/app-veth.json" else value,
                                 flags, *arguments, **options)
            metadata = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_nlink=1)
            output = io.StringIO()
            with mock.patch.object(sys, "argv", [broker.__file__, "--check-config"]), \
                    mock.patch.object(os, "open", side_effect=mapped_open), \
                    mock.patch.object(os, "fstat", return_value=metadata), \
                    mock.patch.object(broker.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=1000)), \
                    mock.patch.object(broker.signal, "signal"), \
                    mock.patch.object(subprocess, "run") as commands, \
                    contextlib.redirect_stdout(output):
                runpy.run_path(broker.__file__, run_name="__main__")
            commands.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["event"], "network_configuration_validated")

    def test_configuration_rejects_a_fifo_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            os.mkfifo(path, mode=0o600)
            # Exercise the real open and metadata guard in a bounded child so
            # a regression cannot hang the entire validation process.
            code = ('import runpy,sys; sys.path.insert(0,sys.argv[3]); module=runpy.run_path(sys.argv[1]); '
                    'check=module["configuration"]; check.__globals__["CONFIG"]=sys.argv[2]; check()')
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, broker.__file__, str(path), str(LIBRARY)],
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe managed network configuration", result.stderr)


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        configured = fixture_configuration({"qbittorrent": {"network": True, "peer_port": 50309}})
        self.patch = mock.patch.object(client, "_configuration", return_value=configured)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_omitted_and_disabled_apps_are_rejected_and_new_configured_apps_are_accepted(self):
        policies = fixture_configuration({"new-client": {"network": True}, "keepassxc": {"network": False}})["apps"]
        for app in ("codex", "keepassxc"):
            with self.subTest(app=app), self.assertRaises(ValueError):
                self.request({"app": app}, policies=policies)
        _pid, _uid, app, descriptor, _address = self.request({"app": "new-client"}, policies=policies)
        os.close(descriptor)
        self.assertEqual(app, "new-client")

    def test_client_preserves_broker_error_and_distinguishes_early_disconnect(self):
        for response, expected in ((b"", "closed the request"),
                (json.dumps({"ready": False, "error": "Nexthop has invalid gateway.",
                             "correlation_id": "a" * 32}).encode(), "Nexthop has invalid gateway")):
            channel = mock.Mock()
            channel.getsockopt.return_value = struct.pack("3i", 12, 0, 0)
            channel.recvmsg.return_value = (response, [], 0, None)
            with self.subTest(response=response), mock.patch.object(client, "control_socket_owner", return_value=0), \
                    mock.patch.object(client.socket, "socket", return_value=channel), self.assertRaisesRegex(ValueError, expected):
                client.Lease(3, "codex")
            channel.close.assert_called_once()

    def test_host_namespace_is_rejected_without_admin_commands(self):
        fd = os.open("/proc/self/ns/net", os.O_RDONLY)
        try:
            with self.assertRaisesRegex(ValueError, "host namespace"), mock.patch.object(broker, "run") as commands:
                broker.namespace_owner(fd, os.getuid())
            commands.assert_not_called()
        finally:
            os.close(fd)

    def test_non_namespace_fd_is_rejected(self):
        with open("/dev/null", "rb") as stream, self.assertRaises(OSError):
            broker.namespace_owner(stream.fileno(), os.getuid())

    def request(self, request, *, count=1, uid=None, authorize=True, policies=DEFAULT_POLICIES):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        descriptor = os.open("/dev/null", os.O_RDONLY)
        try:
            raw = json.dumps(request).encode("ascii")
            left.sendmsg([raw], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                  array.array("i", [descriptor] * count))])
            with mock.patch.object(broker.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=123)), \
                    mock.patch.object(broker, "namespace_owner") as ownership:
                if not authorize:
                    ownership.side_effect = ValueError("foreign namespace")
                return broker.receive(right, os.getuid() if uid is None else uid, policies)
        finally:
            left.close(); right.close(); os.close(descriptor)

    def test_real_fd_transfer_is_cloexec_and_ownership_checked(self):
        _pid, uid, app, fd, _address = self.request({"app": "codex"})
        try:
            self.assertEqual((uid, app), (os.getuid(), "codex"))
            self.assertFalse(os.get_inheritable(fd))
        finally:
            os.close(fd)

    def test_reconnect_address_is_validated_before_namespace_transfer(self):
        address = DEFAULT_POLICIES['codex']['addresses'][1]
        _pid, _uid, _app, fd, requested = self.request({'app': 'codex', 'address': address})
        try:
            self.assertEqual(requested, address)
            self.assertFalse(os.get_inheritable(fd))
        finally:
            os.close(fd)
        for invalid in (None, [], DEFAULT_POLICIES['qbittorrent']['addresses'][0], '127.0.0.1'):
            with self.subTest(address=invalid), self.assertRaisesRegex(ValueError, 'not reserved'):
                self.request({'app': 'codex', 'address': invalid})

    def test_untrusted_app_or_extra_request_fields_fail_closed(self):
        before = len(list(Path("/proc/self/fd").iterdir()))
        for request in ({"app": []}, {"app": "unknown"}, {"app": "codex", "port": 22}, [], {"app": True}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.request(request)
        self.assertEqual(len(list(Path("/proc/self/fd").iterdir())), before)

    def test_multiple_fds_and_wrong_uid_are_rejected_without_leaks(self):
        before = len(list(Path("/proc/self/fd").iterdir()))
        with self.assertRaises(ValueError):
            self.request({"app": "codex"}, count=2)
        with self.assertRaises(ValueError):
            self.request({"app": "codex"}, uid=os.getuid()+1)
        with self.assertRaises(ValueError):
            self.request({"app": "codex"}, authorize=False)
        self.assertEqual(len(list(Path("/proc/self/fd").iterdir())), before)

    def test_desktop_cannot_request_podman_identity(self):
        with self.assertRaises(ValueError):
            self.request({"app": "podman"})

    def test_client_rejects_non_root_server(self):
        channel = mock.Mock()
        channel.getsockopt.return_value = struct.pack("3i", 12, 1000, 1000)
        with mock.patch.object(client, "control_socket_owner", return_value=0), \
                mock.patch.object(client.socket, "socket", return_value=channel), self.assertRaises(ValueError):
            client.Lease(3, "codex")
        channel.sendmsg.assert_not_called()
        channel.close.assert_called_once()

    def test_client_rejects_invalid_readiness_and_closes_socket(self):
        for response, flags in ((b'{"ready":false}', 0), (b'[]', 0), (b'{}', socket.MSG_TRUNC),
                                (b'{"ready":true,"address":"::1","gateway":"1.2.3.4","interface":"eth0"}', 0)):
            channel = mock.Mock()
            channel.getsockopt.return_value = struct.pack("3i", 12, 0, 0)
            channel.recvmsg.return_value = (response, [], flags, None)
            with self.subTest(response=response), mock.patch.object(client, "control_socket_owner", return_value=0), \
                    mock.patch.object(client.socket, "socket", return_value=channel), self.assertRaises(ValueError):
                client.Lease(3, "codex")
            channel.close.assert_called_once()

    def test_client_rejects_missing_and_non_text_network_readiness_fields(self):
        ready = {"ready": True, "address": "10.203.0.2", "gateway": "10.203.0.1", "interface": "eth0"}
        for field in ('address', 'gateway', 'interface'):
            for value in (None, True, 1, [], {}):
                response = dict(ready, **{field: value})
                if value is None:
                    del response[field]
                channel = mock.Mock()
                channel.getsockopt.return_value = struct.pack('3i', 12, 0, 0)
                channel.recvmsg.return_value = (json.dumps(response).encode(), [], 0, None)
                with self.subTest(field=field, value=value), \
                        mock.patch.object(client, 'control_socket_owner', return_value=0), \
                        mock.patch.object(client.socket, 'socket', return_value=channel), self.assertRaises(ValueError):
                    client.Lease(3, 'codex')
                channel.close.assert_called_once()

    def test_peer_forwarding_port_requires_a_canonical_ready_integer(self):
        for port in (None, True, "50309", 1023, 65536, 50309):
            channel = mock.Mock()
            channel.getsockopt.return_value = struct.pack("3i", 12, 0, 0)
            channel.recvmsg.return_value = (json.dumps({"ready": True, "address": "10.203.0.2",
                "gateway": "10.203.0.1", "interface": "eth0", "peer_port": port}).encode(), [], 0, None)
            with self.subTest(port=port), mock.patch.object(client, "control_socket_owner", return_value=0), \
                    mock.patch.object(client.socket, "socket", return_value=channel):
                if type(port) is int and port == 50309:
                    lease = client.Lease(3, "qbittorrent")
                    self.assertEqual(lease.peer_port, port)
                    lease.close()
                else:
                    with self.assertRaises(ValueError):
                        client.Lease(3, "qbittorrent")
            channel.close.assert_called_once()

    def test_client_authenticates_root_translated_by_podman_user_namespace(self):
        for root_uid in (0, 65534):
            with self.subTest(root_uid=root_uid):
                metadata = [types.SimpleNamespace(st_mode=kind | mode, st_uid=root_uid, st_gid=root_uid)
                            for kind, mode in ((stat.S_IFDIR, 0o755), (stat.S_IFDIR, 0o755), (stat.S_IFSOCK, 0o666))]
                channel = mock.Mock()
                channel.getsockopt.return_value = struct.pack("3i", 12, root_uid, root_uid)
                channel.recvmsg.return_value = (b'{"ready":true,"address":"10.203.0.2","gateway":"10.203.0.1","interface":"eth0"}', [], 0, None)
                with mock.patch.object(client, "_configuration", return_value=fixture_configuration({"podman": {"network": True}})), \
                        mock.patch.object(client, "system_owner", return_value=(root_uid, root_uid)), \
                        mock.patch.object(client.Path, "lstat", side_effect=metadata), \
                        mock.patch.object(client.socket, "socket", return_value=channel):
                    lease = client.Lease(3, "podman")
                    lease.close()
                channel.sendmsg.assert_called_once()

    def test_client_rejects_mutable_or_symlink_control_endpoints_before_fd_transfer(self):
        for kind, mode, owner in ((stat.S_IFLNK, 0o755, 0), (stat.S_IFDIR, 0o777, 0), (stat.S_IFDIR, 0o755, 1000)):
            metadata = types.SimpleNamespace(st_mode=kind | mode, st_uid=owner, st_gid=owner)
            channel = mock.Mock()
            with self.subTest(kind=kind, mode=mode, owner=owner), \
                    mock.patch.object(client, "system_owner", return_value=(0, 0)), \
                    mock.patch.object(client.Path, "lstat", return_value=metadata), \
                    mock.patch.object(client.socket, "socket", return_value=channel), self.assertRaises(ValueError):
                client.Lease(3, "podman")
            channel.sendmsg.assert_not_called()


class LeaseRecoveryTests(unittest.TestCase):
    def make_lease(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        left.setblocking(False)
        lease = object.__new__(client.Lease)
        lease.socket = left
        lease.namespace_fd = os.open('/dev/null', os.O_RDONLY | os.O_CLOEXEC)
        lease.app = 'qbittorrent'
        lease.address = DEFAULT_POLICIES[lease.app]['addresses'][0]
        lease.gateway = str(ipaddress.IPv4Address(lease.address) - 1)
        lease.interface = DEFAULT_CONFIGURATION['network']['namespace_interface']
        lease.peer_port = DEFAULT_POLICIES[lease.app]['peer_port']
        lease.peer_port_policy = lease.peer_port
        lease.retry_at = None
        self.addCleanup(lease.close)
        self.addCleanup(right.close)
        return lease, right

    def channel(self, lease, *, uid=0):
        channel = mock.Mock()
        channel.getsockopt.return_value = struct.pack('3i', 12, uid, uid)
        response = {'ready': True, 'address': lease.address, 'gateway': lease.gateway,
                    'interface': lease.interface, 'peer_port': lease.peer_port}
        channel.recvmsg.return_value = (json.dumps(response).encode(), [], 0, None)
        return channel

    def test_live_lease_has_no_periodic_retry_or_reconnection(self):
        lease, _peer = self.make_lease()
        with mock.patch.object(client, 'control_socket_owner') as ownership, \
                mock.patch.object(client.time, 'monotonic') as clock:
            lease.maintain()
            self.assertIsNone(lease.retry_timeout())
        ownership.assert_not_called()
        clock.assert_not_called()

    def test_typed_peer_port_notification_updates_the_live_lease_without_reconnecting(self):
        lease, peer = self.make_lease()
        lease.peer_port_policy = {"ethernet": 50309, "wifi": 50409}
        peer.send(b'{"peer_port":50409}')
        with mock.patch.object(client, 'control_socket_owner') as ownership:
            lease.maintain()
        self.assertEqual(lease.peer_port, 50409)
        self.assertIsNone(lease.retry_at)
        ownership.assert_not_called()

    def test_peer_port_notifications_reject_unknown_and_malformed_frames(self):
        for data in (b'{"peer_port":50410}', b'{"peer_port":true}', b'{"peer_port":"50409"}',
                     b'{"peer_port":50409,"extra":1}', b'bad', b'x' * 4097):
            with self.subTest(data=data[:60]):
                lease, peer = self.make_lease()
                lease.peer_port_policy = {"ethernet": 50309, "wifi": 50409}
                peer.send(data)
                with self.assertRaises(ValueError):
                    lease.maintain()
                self.assertEqual(lease.peer_port, 50309)

    def test_reconnect_accepts_another_selected_port_from_the_same_typed_policy(self):
        lease, peer = self.make_lease()
        ports = {"ethernet": 50309, "wifi": 50409}
        lease.peer_port_policy = ports
        configuration = json.loads(DEFAULT_CONFIG_RAW)
        configuration['apps']['qbittorrent']['peer_port'] = ports
        configuration = policy_parser.parse_configuration(json.dumps(configuration).encode())
        channel = self.channel(lease)
        response = {'ready': True, 'address': lease.address, 'gateway': lease.gateway,
                    'interface': lease.interface, 'peer_port': 50409}
        channel.recvmsg.return_value = (json.dumps(response).encode(), [], 0, None)
        peer.close()
        with mock.patch.object(client, '_configuration', return_value=configuration), \
                mock.patch.object(client, 'control_socket_owner', return_value=0), \
                mock.patch.object(client.socket, 'socket', return_value=channel), \
                mock.patch.object(client, 'emit'):
            lease.maintain()
        self.assertIs(lease.socket, channel)
        self.assertEqual(lease.peer_port, 50409)
        self.assertEqual(lease.peer_port_policy, ports)

    def test_broker_restart_authenticates_and_requests_the_same_namespace_and_address(self):
        lease, peer = self.make_lease()
        peer.close()
        namespace = lease.namespace_fd
        channel = self.channel(lease)
        with mock.patch.object(client, '_configuration', return_value=DEFAULT_CONFIGURATION), \
                mock.patch.object(client, 'control_socket_owner', return_value=0), \
                mock.patch.object(client.socket, 'socket', return_value=channel), \
                mock.patch.object(client, 'emit'):
            lease.maintain()
        self.assertIs(lease.socket, channel)
        self.assertIsNone(lease.retry_at)
        packet, ancillary = channel.sendmsg.call_args.args
        self.assertEqual(json.loads(packet[0]), {'app': 'qbittorrent', 'address': lease.address})
        self.assertEqual(list(ancillary[0][2]), [namespace])
        self.assertFalse(os.get_inheritable(namespace))
        lease.close()
        channel.close.assert_called_once()
        with self.assertRaises(OSError):
            os.fstat(namespace)

    def test_untrusted_broker_leaves_gui_offline_and_retries_only_after_deadline(self):
        lease, peer = self.make_lease()
        peer.close()
        channel = self.channel(lease, uid=1000)
        with mock.patch.object(client, 'control_socket_owner', return_value=0), \
                mock.patch.object(client.socket, 'socket', return_value=channel) as connect, \
                mock.patch.object(client.time, 'monotonic', return_value=100), \
                mock.patch.object(client, 'emit'):
            lease.maintain()
            lease.maintain()
            self.assertEqual(lease.retry_timeout(), 5)
        self.assertIsNone(lease.socket)
        self.assertEqual(lease.retry_at, 105)
        self.assertEqual(connect.call_count, 1)
        channel.sendmsg.assert_not_called()
        channel.close.assert_called_once()
        self.assertGreaterEqual(lease.namespace_fd, 0)

    def test_acquisition_failure_closes_the_retained_descriptor(self):
        source = os.open('/dev/null', os.O_RDONLY | os.O_CLOEXEC)
        duplicate = os.dup(source)
        try:
            with mock.patch.object(client.os, 'dup', return_value=duplicate), \
                    mock.patch.object(client.Lease, '__init__', side_effect=ValueError('untrusted')):
                with self.assertRaisesRegex(ValueError, 'untrusted'):
                    client.Lease.for_namespace(source, 'qbittorrent')
            with self.assertRaises(OSError):
                os.fstat(duplicate)
            os.fstat(source)
        finally:
            os.close(source)


class CommandResultTests(unittest.TestCase):
    def test_empty_conntrack_delete_is_distinguished_from_administrative_errors(self):
        command = ['/usr/sbin/conntrack', '-D', '-f', 'ipv4', '--orig-src', '10.203.0.114']
        cases = ((1, b'conntrack v1.4.9 (conntrack-tools): 0 flow entries have been deleted.\n', True),
                 (1, b'conntrack v1.4.9 (conntrack-tools): Operation failed: Permission denied\n', False),
                 (1, b'', False), (2, b'0 flow entries have been deleted.\n', False))
        for status, output, accepted in cases:
            def result(argv, **options):
                self.assertEqual(argv, command)
                self.assertEqual(options['env'], broker.ENV)
                self.assertEqual(options['timeout'], 5)
                self.assertEqual(options['stdout'], subprocess.DEVNULL)
                options['stderr'].write(output)
                return types.SimpleNamespace(returncode=status)
            with self.subTest(status=status, output=output), \
                    mock.patch.object(broker.subprocess, 'run', side_effect=result):
                if accepted:
                    self.assertEqual(broker.run(command, empty_conntrack_delete=True), output.decode())
                else:
                    with self.assertRaises(RuntimeError):
                        broker.run(command, empty_conntrack_delete=True)


class ResolverTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(client, "_configuration", return_value=DEFAULT_CONFIGURATION)
        patch.start(); self.addCleanup(patch.stop)

    def test_only_resolved_search_suffixes_enter_the_private_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stub-resolv.conf"
            path.write_text("# resolved\nnameserver 127.0.0.53\nsearch lan.example vpn.example.\noptions edns0 trust-ad\n", encoding="ascii")
            with mock.patch.object(client, "STUB_RESOLVER_PATH", str(path)):
                self.assertEqual(client.resolver_configuration(), "nameserver 10.0.2.3\noptions timeout:2 attempts:3\n" + "search lan.example vpn.example.\n")

    def test_unsafe_domain_data_and_nonregular_files_fail_boundedly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resolver"
            for text in ("search ../escape\n", "search ~vpn.example\n", "search lan..\n", "x" * 65537):
                path.write_text(text, encoding="ascii")
                with self.subTest(text=text[:20]), mock.patch.object(client, "STUB_RESOLVER_PATH", str(path)), self.assertRaises(ValueError):
                    client.resolver_configuration()
            path.unlink()
            os.mkfifo(path)
            with mock.patch.object(client, "STUB_RESOLVER_PATH", str(path)), self.assertRaises(ValueError):
                client.resolver_configuration()
            path.unlink()
            path.symlink_to("/dev/null")
            with mock.patch.object(client, "STUB_RESOLVER_PATH", str(path)), self.assertRaises(OSError):
                client.resolver_configuration()

    def test_resolved_empty_search_root_and_international_domains_are_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stub"
            for text, expected in (("search .\n", "."), ("search büro.example\n", "xn--bro-hoa.example")):
                path.write_text(text, encoding="utf-8")
                with self.subTest(text=text), mock.patch.object(client, "STUB_RESOLVER_PATH", str(path)):
                    self.assertEqual(client.resolver_configuration(), "nameserver 10.0.2.3\noptions timeout:2 attempts:3\n" + "search " + expected + "\n")

    def test_missing_resolved_snapshot_keeps_broker_stub_without_public_fallback(self):
        with mock.patch.object(client.os, "open", side_effect=FileNotFoundError):
            self.assertEqual(client.resolver_configuration(), "nameserver 10.0.2.3\noptions timeout:2 attempts:3\n")


class CodexSocketBindTests(unittest.TestCase):
    def test_missing_codex_socket_tree_is_optional(self):
        with tempfile.TemporaryDirectory(prefix="codex-sockets-missing-") as directory:
            with mock.patch.object(client, "CODEX_SOCKET_ROOT", Path(directory) / "absent"):
                self.assertEqual(client.codex_socket_arguments(), [])

    def test_codex_socket_bind_arguments_include_control_mcp_and_backend_runtime(self):
        with tempfile.TemporaryDirectory(prefix="codex-sockets-") as directory:
            base = Path(directory)
            socket_root = base / "sockets"
            socket_root.mkdir(mode=0o700)
            daemon_root = base / "tmp"
            daemon_root.mkdir(mode=0o755)
            daemon_directory = daemon_root / f"codex-daemon-{os.getuid()}"
            daemon_directory.mkdir(mode=0o700)

            open_sockets = []
            try:
                for path in (socket_root / "app-server-control.sock",
                             socket_root / "codex-mcp.sock",
                             daemon_directory / "backend"):
                    channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    channel.bind(str(path))
                    path.chmod(0o600)
                    open_sockets.append(channel)
                (socket_root / "app-server-backend.sock").symlink_to(
                    daemon_directory / "backend"
                )
                with mock.patch.object(client, "CODEX_SOCKET_ROOT", socket_root), \
                        mock.patch.object(client, "CODEX_SOCKET_DAEMON_ROOT", daemon_root):
                    arguments = client.codex_socket_arguments()
                triples = list(zip(arguments, arguments[1:], arguments[2:]))
                self.assertIn(
                    ("--bind", str(socket_root / "app-server-control.sock"),
                     str(socket_root / "app-server-control.sock")), triples)
                self.assertIn(
                    ("--bind", str(socket_root / "codex-mcp.sock"),
                     str(socket_root / "codex-mcp.sock")), triples)
                self.assertIn(
                    ("--bind", str(daemon_directory), str(daemon_directory)), triples)
            finally:
                for channel in open_sockets:
                    channel.close()


class RecoveryTests(unittest.TestCase):
    def pair(self, *, alias="", flags=None):
        return [{"ifname": "veth3-app", "link": "veth3-peer", "ifalias": alias,
                 "flags": flags or [], "linkinfo": {"info_kind": "veth"}},
                {"ifname": "veth3-peer", "link": "veth3-app", "flags": [],
                 "linkinfo": {"info_kind": "veth"}}]

    def recover(self, links, addresses=None):
        calls = []
        def run(argv, **options):
            calls.append(argv)
            if argv == ["/usr/sbin/ip", "-j", "-d", "link", "show"]:
                return json.dumps(links)
            if "addr" in argv:
                return json.dumps([{"addr_info": addresses or []}])
            return ""
        with mock.patch.object(broker, "run", side_effect=run):
            broker.recover_endpoints()
        return [argv for argv in calls if argv[:3] == ["/usr/sbin/ip", "link", "del"]]

    def test_incomplete_reserved_down_pair_is_recovered_but_foreign_state_is_preserved(self):
        self.assertEqual(self.recover(self.pair()), [["/usr/sbin/ip", "link", "del", "dev", "veth3-app"]])
        for links, addresses in ((self.pair(alias="administrator"), []),
                                 (self.pair(flags=["UP"]), []),
                                 (self.pair(), [{"local": "192.0.2.1", "prefixlen": 24}]),
                                 ([self.pair()[0]], [])):
            with self.subTest(links=links, addresses=addresses):
                self.assertEqual(self.recover(links, addresses), [])
        unrelated = self.pair()
        unrelated[0]["link"] = "veth4-peer"
        self.assertEqual(self.recover(unrelated), [])

    def test_only_tagged_reserved_veth_names_can_recover_an_active_lease(self):
        row = {"ifname": "veth3-app", "ifalias": "app-veth:" + "a" * 32,
               "flags": ["UP"], "linkinfo": {"info_kind": "veth"}}
        self.assertEqual(self.recover([row]), [["/usr/sbin/ip", "link", "del", "dev", "veth3-app"]])
        for changes in ({"ifname": "veth128-app"}, {"ifname": "eth0"}, {"ifname": "veth3-vivaldi"},
                        {"ifalias": "app-veth:not-a-tag"}, {"linkinfo": {"info_kind": "bridge"}},
                        {"ifalias": ""}):
            with self.subTest(changes=changes):
                self.assertEqual(self.recover([{**row, **changes}]), [])


class AdministrationTests(unittest.TestCase):
    def commands(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if "--" in argv and argv[-3:] == ["-j", "link", "show"]:
            return '[{"ifname":"lo"}]'
        return ""

    def setUp(self):
        self.calls = []
        self.transactions = []
        self.original_route = broker.route
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(broker, "run", side_effect=self.commands))
        self.stack.enter_context(mock.patch.object(broker, "route", return_value=("wg0", "192.0.2.8", 1420)))
        self.stack.enter_context(mock.patch.object(broker, "nft", side_effect=self.transactions.append))
        self.stack.enter_context(mock.patch.object(broker, "event"))
        self.stack.enter_context(mock.patch.object(broker.Network, "reserve"))
        self.endpoints = broker.EndpointPool(ipaddress.IPv4Network("10.203.0.0/24"))
        self.addCleanup(self.endpoints.close)
        self.boot_calls = list(self.calls)
        self.calls.clear()

    def network(self, app="codex"):
        policy = DEFAULT_POLICIES.get(app, {"network": True, "peer_port": None, "pin_route": False, "block_lan": False})
        return broker.Network(3, 70, app, 1000, policy, ipaddress.IPv4Network("10.203.0.0/24"), self.endpoints)

    def test_kernel_link_is_tagged_and_route_mtu_preserved_without_tun(self):
        network = self.network()
        self.addCleanup(network.close)
        batch = next(options["data"] for argv, options in self.boot_calls if argv == ["/usr/sbin/ip", "-batch", "-"])
        self.assertEqual(batch.count("type veth"), broker.MAX_LEASES)
        self.assertIn("app-veth:" + self.endpoints.ids[3], batch)
        self.assertIn("addr add 10.203.0.13/30 dev veth3-app", batch)
        self.assertIn((["/usr/sbin/ip", "link", "set", "dev", "veth3-app", "mtu", "1420", "up"], {}), self.calls)
        self.assertEqual(sum('/usr/bin/nsenter' not in argv and argv[:3] == ['/usr/sbin/ip', 'link', 'set']
                             and 'mtu' in argv for argv, _ in self.calls), 1)
        self.assertTrue(any("/proc/self/fd/70" in argv and "veth3-peer" in argv for argv, _ in self.calls))
        self.assertFalse(any("add" in argv and "link" in argv for argv, _ in self.calls))
        self.assertNotIn("/dev/net/tun", str(self.calls))
        self.assertEqual((network.gateway, network.address), ("10.203.0.13", "10.203.0.14"))
        self.assertFalse(any("tc" in argv for argv, _ in self.calls))

    def test_guest_link_is_up_before_default_route_and_host_link_after_firewall_commit(self):
        events = []
        def command(argv, **kwargs):
            events.append(("command", argv, kwargs))
            return self.commands(argv, **kwargs)
        with mock.patch.object(broker, "run", side_effect=command), \
                mock.patch.object(broker, "nft", side_effect=lambda text: events.append(("firewall", text))):
            network = self.network()
        self.addCleanup(network.close)
        transaction = next(i for i,e in enumerate(events) if e[0] == "firewall")
        guest = next(i for i,e in enumerate(events) if e[0] == "command" and "--" in e[1] and e[1][-2:] == ["-batch", "-"])
        setup = events[guest][2]["data"].splitlines()
        self.assertLess(setup.index("link set eth0 up"), setup.index("route add default via 10.203.0.13 dev eth0"))
        host_up = next(i for i,e in enumerate(events) if e[0] == "command" and e[1] ==
                       ["/usr/sbin/ip", "link", "set", "dev", "veth3-app", "mtu", "1420", "up"])
        self.assertLess(guest, transaction)
        self.assertLess(transaction, host_up)

    def test_failed_guest_batch_reclaims_the_peer_without_enabling_host_access(self):
        def command(argv, **kwargs):
            result = self.commands(argv, **kwargs)
            if "--" in argv and argv[-2:] == ["-batch", "-"]:
                raise RuntimeError("guest batch failed")
            return result
        with mock.patch.object(broker, "run", side_effect=command), \
                self.assertRaisesRegex(RuntimeError, "guest batch failed"):
            self.network()
        self.assertFalse(any('veth3-app' in argv and argv[-1] == 'up' for argv, _ in self.calls))
        self.assertTrue(any(argv[-3:] == ["veth3-peer", "netns", f"/proc/self/fd/{self.endpoints.host_fd}"] for argv, _ in self.calls))
        self.assertEqual(self.transactions, [])

    def test_qbittorrent_dnat_is_exact_tcp_udp_and_route_pinned(self):
        network = self.network("qbittorrent")
        self.addCleanup(network.close)
        transaction = ''.join(self.transactions)
        for transport in ("tcp", "udp"):
            self.assertIn(f'192.0.2.8 . {transport} . 50309 : 10.203.0.14 . 50309', transaction)
            self.assertIn(f'"veth3-app" . {transport} . 50309 : 192.0.2.8 . 50309', transaction)
        self.assertIn('snat ip to iifname . meta l4proto . th sport map @peer_snat', broker.RULESET)
        self.assertIn('add element inet app_veth snat_map { "veth3-app" : 192.0.2.8 }', transaction)
        self.assertNotIn('add element inet app_veth snat {', transaction)
        self.assertIn('pinned { "veth3-app" . "wg0" }', transaction)
        self.assertNotIn('outbound {', transaction)
        self.assertEqual(broker.Network.reserve.call_count, 2)
        self.assertIn('add element inet app_veth no_http { "veth3-app" }', transaction)
        forward = broker.RULESET.split('chain forward_guard {', 1)[1]
        self.assertLess(forward.index('iifname @no_http'), forward.index('iifname @outbound accept'))
        self.assertLess(forward.index('iifname @no_http'), forward.index('iifname . oifname @pinned accept'))
        network.close()
        self.assertIn('delete element inet app_veth no_http { "veth3-app" }', self.transactions[-1])

    def dual_port_network(self):
        policy = {**DEFAULT_POLICIES['qbittorrent'], 'peer_port': {'ethernet': 50309, 'wifi': 50409}}
        # No real sysfs discovery: this fixture's two names define the link type.
        self.stack.enter_context(mock.patch.object(broker, 'wireless_interface', side_effect=lambda name: name == 'wifi-fixture'))
        return broker.Network(3, 70, 'qbittorrent', 1000, policy,
                              ipaddress.IPv4Network('10.203.0.0/24'), self.endpoints)

    def test_peer_ingress_exists_only_in_the_active_route_transaction(self):
        for route, port in ((('ethernet-fixture', '192.0.2.8', 1500), 50309),
                            (('wifi-fixture', '192.0.2.9', 1500), 50409), (None, None)):
            with self.subTest(route=route), mock.patch.object(broker, 'route', return_value=route):
                self.transactions.clear()
                network = self.dual_port_network()
                try:
                    self.assertNotIn('incoming {', self.transactions[0])
                    self.assertFalse(any('incoming {' in row for row in network.remove))
                    if port is None:
                        self.assertEqual(network.route_remove, [])
                        self.assertEqual(len(self.transactions), 1)
                    else:
                        self.assertEqual(len(self.transactions), 2)
                        transaction = self.transactions[1]
                        self.assertEqual(transaction.count('add element inet app_veth incoming'), 2)
                        for protocol in ('tcp', 'udp'):
                            self.assertIn(f'incoming {{ "veth3-app" . 10.203.0.14 . {protocol} . {port} }}', transaction)
                        other = 50409 if port == 50309 else 50309
                        self.assertNotIn(f' . {other}', transaction)
                        self.assertEqual(sum('incoming {' in row for row in network.route_remove), 2)
                finally:
                    network.close()

    def test_wifi_switch_replaces_both_transport_maps_and_notifies_only_its_owner(self):
        network = self.dual_port_network()
        self.addCleanup(network.close)
        network.channel = mock.Mock()
        network.channel.send.side_effect = len
        self.calls.clear(); self.transactions.clear()
        network.refresh_route(('wifi-fixture', '192.0.2.9', 1500))
        self.assertEqual(network.peer_port, 50409)
        transaction = ''.join(self.transactions)
        self.assertEqual(len(self.transactions), 1)
        for protocol in ('tcp', 'udp'):
            self.assertIn(f'delete element inet app_veth incoming {{ "veth3-app" . 10.203.0.14 . {protocol} . 50309 }}', transaction)
            self.assertIn(f'add element inet app_veth incoming {{ "veth3-app" . 10.203.0.14 . {protocol} . 50409 }}', transaction)
            self.assertIn(f'delete element inet app_veth forwards {{ 192.0.2.8 . {protocol} . 50309 }}', transaction)
            self.assertIn(f'192.0.2.9 . {protocol} . 50409 : 10.203.0.14 . 50409', transaction)
            self.assertIn(f'"veth3-app" . {protocol} . 50409 : 192.0.2.9 . 50409', transaction)
        self.assertEqual(json.loads(network.channel.send.call_args.args[0]), {'peer_port': 50409})
        network.channel.send.reset_mock()
        self.transactions.clear()
        network.refresh_route(('wifi-fixture', '192.0.2.9', 1400))
        network.channel.send.assert_not_called()
        self.assertEqual(self.transactions, [])
        network.refresh_route(None)
        self.assertEqual(network.peer_port, 50409)
        self.assertEqual(network.route_remove, [])
        offline = self.transactions[-1]
        self.assertNotIn('add element', offline)
        for protocol in ('tcp', 'udp'):
            self.assertIn(f'delete element inet app_veth incoming {{ "veth3-app" . 10.203.0.14 . {protocol} . 50409 }}', offline)
        network.channel.send.assert_not_called()
        network.refresh_route(('ethernet-fixture', '192.0.2.10', 1500))
        self.assertEqual(network.peer_port, 50309)
        self.assertEqual(json.loads(network.channel.send.call_args.args[0]), {'peer_port': 50309})

    def test_ingress_and_nat_commit_together_between_host_link_down_and_up(self):
        network = self.dual_port_network()
        self.addCleanup(network.close)
        events = []
        def command(argv, **options):
            events.append(('command', argv))
            return self.commands(argv, **options)
        with mock.patch.object(broker, 'run', side_effect=command), \
                mock.patch.object(broker, 'nft', side_effect=lambda text: events.append(('nft', text))):
            network.update_route(('wifi-fixture', '192.0.2.9', 1500))
        commits = [i for i, event in enumerate(events) if event[0] == 'nft']
        self.assertEqual(len(commits), 1)
        down = events.index(('command', ['/usr/sbin/ip', 'link', 'set', 'dev', 'veth3-app', 'down']))
        up = events.index(('command', ['/usr/sbin/ip', 'link', 'set', 'dev', 'veth3-app', 'mtu', '1500', 'up']))
        self.assertLess(down, commits[0]); self.assertLess(commits[0], up)
        transaction = events[commits[0]][1]
        for element in ('incoming', 'forwards', 'peer_snat'):
            self.assertIn(f'delete element inet app_veth {element}', transaction)
            self.assertIn(f'add element inet app_veth {element}', transaction)
        self.assertFalse(any('50309' in row for row in transaction.splitlines()
                             if row.startswith('add element')))

    def test_rejected_route_transaction_keeps_exact_old_ingress_cleanup_for_retry(self):
        network = self.dual_port_network()
        self.addCleanup(network.close)
        previous = list(network.route_remove)
        self.calls.clear()
        target = ('wifi-fixture', '192.0.2.9', 1500)
        with mock.patch.object(broker, 'nft', side_effect=RuntimeError('fixture atomic rejection')), \
                mock.patch.object(broker.time, 'monotonic', return_value=100):
            network.refresh_route(target)
        self.assertEqual(network.route_remove, previous)
        self.assertEqual(network.peer_port, 50309)
        self.assertEqual(network.route_retry_at, 105)
        self.assertFalse(any(argv[-1] == 'up' for argv, _ in self.calls))
        with mock.patch.object(broker.time, 'monotonic', return_value=105):
            network.refresh_route(target)
        for protocol in ('tcp', 'udp'):
            self.assertIn(f'delete element inet app_veth incoming {{ "veth3-app" . 10.203.0.14 . {protocol} . 50309 }}', self.transactions[-1])
        self.assertEqual(network.peer_port, 50409)

    def test_post_commit_failure_retains_new_ingress_cleanup_and_link_stays_down(self):
        network = self.dual_port_network()
        self.addCleanup(network.close)
        target = ('wifi-fixture', '192.0.2.9', 1500)
        self.calls.clear()
        def command(argv, **options):
            result = self.commands(argv, **options)
            if argv[0] == '/usr/sbin/conntrack':
                raise RuntimeError('fixture conntrack failure after commit')
            return result
        with mock.patch.object(broker, 'run', side_effect=command), \
                mock.patch.object(broker.time, 'monotonic', return_value=100):
            network.refresh_route(target)
        self.assertFalse(any(argv[-1] == 'up' for argv, _ in self.calls))
        self.assertEqual(network.peer_port, 50309)
        self.assertTrue(any('incoming {' in row and '50409' in row for row in network.route_remove))
        self.assertFalse(any('50309' in row for row in network.route_remove))
        with mock.patch.object(broker.time, 'monotonic', return_value=105):
            network.refresh_route(target)
        self.assertEqual(network.peer_port, 50409)
        network.close()
        for protocol in ('tcp', 'udp'):
            self.assertIn(f'delete element inet app_veth incoming {{ "veth3-app" . 10.203.0.14 . {protocol} . 50409 }}', self.transactions[-1])
        self.assertEqual(network.route_remove, [])

    def test_stalled_port_receiver_leaves_host_link_down_until_bounded_retry(self):
        network = self.dual_port_network()
        self.addCleanup(network.close)
        network.channel = mock.Mock()
        network.channel.send.side_effect = BlockingIOError('fixture receiver full')
        self.calls.clear()
        with mock.patch.object(broker.time, 'monotonic', return_value=100):
            network.refresh_route(('wifi-fixture', '192.0.2.9', 1500))
        self.assertEqual(network.peer_port, 50309)
        self.assertEqual(network.route_retry_at, 105)
        self.assertTrue(any(argv[-2:] == ['veth3-app', 'down'] for argv, _ in self.calls))
        self.assertFalse(any(argv[-1] == 'up' for argv, _ in self.calls))

    def test_browser_port_guard_is_lease_owned_and_precedes_egress_accepts(self):
        for app in ("chromium", "microsoft-edge", "vivaldi", "mullvad-browser"):
            with self.subTest(app=app):
                network = self.network(app)
                transaction = self.transactions[-1]
                self.assertIn('add element inet app_veth web_tls_only { "veth3-app" }', transaction)
                network.close()
                self.assertIn('delete element inet app_veth web_tls_only { "veth3-app" }', self.transactions[-1])
        forward = broker.RULESET.split('chain forward_guard {', 1)[1]
        for guard in ('meta l4proto != tcp', 'tcp dport != @web_ports'):
            self.assertLess(forward.index(guard), forward.index('iifname @outbound accept'))
            self.assertLess(forward.index(guard), forward.index('iifname . oifname @pinned accept'))
        host = broker.RULESET.split('chain host_guard {', 1)[1].split('chain forward_guard', 1)[0]
        self.assertIn('iifname @web_tls_only iifname != @lan_blocked', host)

    def test_tor_lease_blocks_dns_before_dnat_and_randomizes_only_the_guest_mac(self):
        with mock.patch.object(broker.os, 'urandom', return_value=b'\xff\x01\x02\x03\x04\x05'):
            network = self.network('tor-browser')
        self.addCleanup(network.close)
        transaction = self.transactions[-1]
        self.assertIn('add element inet app_veth tor_transport { "veth3-app" }', transaction)
        self.assertIn('add element inet app_veth lan_blocked { "veth3-app" }', transaction)
        self.assertNotIn('web_tls_only', transaction)
        guest = next(options['data'] for argv, options in self.calls
                     if '--' in argv and argv[-2:] == ['-batch', '-'])
        self.assertIn('link set eth0 address fe:01:02:03:04:05\n', guest)
        self.assertLess(guest.index(' address '), guest.index('link set eth0 up'))
        self.assertFalse(any('address' in argv and '--' not in argv for argv, _ in self.calls))
        guard = broker.RULESET.split('chain source_guard {', 1)[1].split('chain dns_and_peers', 1)[0]
        self.assertIn('priority -150', guard)
        self.assertIn('iifname @tor_transport meta l4proto { tcp, udp } th dport 53 counter drop', guard)
        self.assertIn('iifname @tor_transport meta l4proto != tcp counter drop', guard)
        network.close()
        self.assertIn('delete element inet app_veth tor_transport { "veth3-app" }', self.transactions[-1])

    def test_discord_rpc_is_only_fixed_host_loopback_ports(self):
        network = self.network("discord")
        self.addCleanup(network.close)
        transaction = self.transactions[0]
        self.assertEqual(transaction.count("add element inet app_veth rpc"), 10)
        self.assertEqual(transaction.count("add element inet app_veth incoming"), 10)
        self.assertIn("6463 : 10.203.0.14 . 16463", transaction)
        self.assertIn('"veth3-app" . 10.203.0.14 . tcp . 16463', transaction)
        for call in broker.Network.reserve.call_args_list:
            self.assertEqual(call.args[0], "127.0.0.1")

    def test_qbittorrent_privacy_lease_also_blocks_port_80_and_reclaims_the_guard(self):
        network = self.network('qbittorrent-privacy')
        self.addCleanup(network.close)
        self.assertIn('add element inet app_veth no_http { "veth3-app" }', self.transactions[0])
        self.assertIn('outbound { "veth3-app" }', self.transactions[0])
        network.close()
        self.assertIn('delete element inet app_veth no_http { "veth3-app" }', self.transactions[-1])

    def test_freerdp_egress_is_routed_to_lan_and_wan_without_destination_or_port_pin(self):
        network = self.network("freerdp")
        self.addCleanup(network.close)
        self.assertIn('outbound { "veth3-app" }', self.transactions[0])
        self.assertNotIn('pinned {', self.transactions[0])
        self.assertNotIn('incoming {', self.transactions[0])
        self.assertNotIn('no_http {', self.transactions[0])
        broker.route.assert_called_with(allow_lan=True)
        forward = broker.RULESET.split('chain forward_guard {', 1)[1].split('chain nat {', 1)[0]
        self.assertIn('iifname @outbound accept', forward)
        self.assertIn('oifname @links ct state established,related accept', forward)
        self.assertNotIn('lan_blocked {', self.transactions[0])
        self.assertLess(forward.index('iifname @lan_blocked ip daddr @lan_ipv4 drop'),
                        forward.index('iifname @outbound accept'))
        self.assertIn('iifname @outbound masquerade', broker.RULESET)

    def test_lan_only_route_uses_active_connected_links_without_requiring_wan(self):
        def replies(argv, **options):
            if argv[-2:] == ['get', '1.1.1.1']:
                raise RuntimeError('Network is unreachable')
            if argv[-3:] == ['show', 'scope', 'link']:
                return json.dumps([
                    {'dst':'10.203.0.0/30','dev':'veth0-app','prefsrc':'10.203.0.1'},
                    {'dst':'192.168.4.0/24','dev':'eth0','prefsrc':'192.168.4.7'},
                    {'dst':'10.1.0.0/24','dev':'eth1','prefsrc':'10.1.0.7'}])
            return json.dumps([{'mtu':9000 if argv[-1] == 'eth1' else 1500,'flags':['UP']}])
        with mock.patch.object(broker, "run", side_effect=replies), \
                mock.patch.object(broker, "route", wraps=self.original_route):
            self.assertEqual(broker.route(allow_lan=True), ('eth0', '192.168.4.7', 1500))
            with self.assertRaises(RuntimeError):
                broker.route(allow_lan=False)

    def test_failed_transaction_returns_the_boot_endpoint_without_releasing_payload(self):
        with mock.patch.object(broker, "nft", side_effect=RuntimeError("reject")), self.assertRaises(RuntimeError):
            self.network()
        self.assertIn((["/usr/sbin/ip", "link", "set", "dev", "veth3-app", "down"], {}), self.calls)
        self.assertTrue(any(argv[-3:] == ["veth3-peer", "netns", f"/proc/self/fd/{self.endpoints.host_fd}"] for argv, _ in self.calls))
        self.assertFalse(any(argv[:3] == ["/usr/sbin/ip", "link", "del"] for argv, _ in self.calls))
        self.assertFalse(any('veth3-app' in argv and argv[-1] == 'up' for argv, _ in self.calls))

    def test_internet_route_rejects_a_down_interface(self):
        for flags, operstate, route_flags in (([], 'DOWN', []),
                (['UP', 'NO-CARRIER'], 'DOWN', []), (['UP'], 'LOWERLAYERDOWN', []),
                (['UP', 'LOWER_UP'], 'UP', ['linkdown'])):
            with self.subTest(flags=flags, operstate=operstate, route_flags=route_flags):
                def replies(argv, **options):
                    if argv[-2:] == ['get', '1.1.1.1']:
                        return json.dumps([{'dev': 'eth0', 'prefsrc': '192.0.2.56', 'flags': route_flags}])
                    return json.dumps([{'mtu': 1500, 'flags': flags, 'operstate': operstate}])
                with mock.patch.object(broker, 'run', side_effect=replies), \
                        self.assertRaisesRegex(ValueError, 'Internet interface is down'):
                    self.original_route()

    def test_kernel_selected_ethernet_wifi_and_vpn_use_the_same_route_reader(self):
        for iface, source, state in (('eth0', '192.0.2.56', 'UP'),
                                    ('wifi0', '192.0.2.57', 'UP'),
                                    ('wg0', '198.51.100.2', 'UNKNOWN')):
            with self.subTest(iface=iface):
                def replies(argv, **options):
                    if argv[-2:] == ['get', '1.1.1.1']:
                        return json.dumps([{'dev': iface, 'prefsrc': source}])
                    return json.dumps([{'mtu': 1500, 'flags': ['UP'], 'operstate': state}])
                with mock.patch.object(broker, 'run', side_effect=replies) as commands:
                    self.assertEqual(self.original_route(), (iface, source, 1500))
                self.assertEqual(commands.call_args_list[0].args[0],
                    ['/usr/sbin/ip', '-j', '-4', 'route', 'get', '1.1.1.1'])

    def test_malformed_route_and_link_snapshots_fail_with_a_controlled_error(self):
        for route in (None, [], {}, {'dev': []}, {'dev': 'eth0', 'prefsrc': True}):
            with self.subTest(route=route), self.assertRaises(ValueError):
                broker.route_interface(route)
        for links in ([], {}, [None], [{'mtu': 1500}], [{'mtu': True, 'flags': ['UP']}],
                      [{'mtu': 1500, 'flags': 'UP'}], [{'mtu': 1500, 'flags': ['UP'], 'operstate': {}}]):
            with self.subTest(links=links), mock.patch.object(broker, 'run', return_value=json.dumps(links)), \
                    self.assertRaises(ValueError):
                broker.route_interface({'dev': 'eth0', 'prefsrc': '192.0.2.8'})
        for flags in (None, 'linkdown', [False]):
            with self.subTest(route_flags=flags), mock.patch.object(broker, 'run',
                    return_value=json.dumps([{'mtu': 1500, 'flags': ['UP']}])), self.assertRaises(ValueError):
                broker.route_interface({'dev': 'eth0', 'prefsrc': '192.0.2.8', 'flags': flags})

    def test_close_removes_packet_path_before_rule_elements(self):
        network = self.network()
        events = []
        with mock.patch.object(broker, "run", side_effect=lambda *args, **kwargs: events.append("link")), \
                mock.patch.object(broker, "nft", side_effect=lambda *_: events.append("rules")):
            network.close()
        self.assertEqual(events, ["link"] * 5 + ["rules"])
        self.assertEqual(network.name, "veth3-app")

    def test_failed_link_cleanup_revokes_access_and_can_be_retried(self):
        network = self.network()
        with mock.patch.object(broker, "run", side_effect=RuntimeError("delete failed")), \
                self.assertRaises(broker.NetworkCleanupError):
            network.close()
        self.assertTrue(network.attached)
        self.assertFalse(network.installed)
        self.assertIn('delete element inet app_veth sources', self.transactions[-1])
        network.close()
        self.assertFalse(network.attached)

    def test_failed_firewall_cleanup_retains_the_exact_retry_transaction(self):
        network = self.network()
        removal = list(network.remove)
        with mock.patch.object(broker, "nft", side_effect=RuntimeError("delete failed")), \
                self.assertRaises(broker.NetworkCleanupError):
            network.close()
        self.assertFalse(network.attached)
        self.assertTrue(network.installed)
        self.assertEqual(network.remove, removal)
        network.close()
        self.assertFalse(network.installed)

    def test_namespace_with_existing_links_is_rejected_before_host_mutation(self):
        with mock.patch.object(broker, "run", return_value='[{"ifname":"eth0"}]') as commands, self.assertRaises(ValueError):
            self.network()
        self.assertEqual(commands.call_count, 1)

    def test_podman_bridge_can_reacquire_an_uplink_but_existing_eth0_is_never_replaced(self):
        def with_bridge(argv, **options):
            if "--" in argv and argv[-3:] == ["-j", "link", "show"]:
                return '[{"ifname":"lo"},{"ifname":"podman0"}]'
            return self.commands(argv, **options)
        with mock.patch.object(broker, "run", side_effect=with_bridge):
            network = self.network("podman")
            network.close()
        with mock.patch.object(broker, "run", return_value='[{"ifname":"lo"},{"ifname":"eth0"}]') as commands, self.assertRaises(ValueError):
            self.network("podman")
        self.assertEqual(commands.call_count, 1)

    def test_packet_guard_blocks_cross_namespace_before_established(self):
        rules = broker.RULESET
        forward = rules.split("chain forward_guard {", 1)[1].split("chain nat {", 1)[0]
        self.assertLess(forward.index(f'iifname {broker.INTERFACE_MATCH} oifname {broker.INTERFACE_MATCH} drop'), forward.index('ct state established,related'))
        self.assertIn('iifname . ip saddr != @sources drop', rules)
        self.assertIn(f'iifname {broker.INTERFACE_MATCH} meta nfproto != ipv4 drop', rules)
        self.assertIn('dnat to 127.0.0.1:53053', rules)
        dns_guard = 'iifname @links meta l4proto { tcp, udp } th dport 53 drop'
        self.assertLess(forward.index(dns_guard), forward.index('iifname @outbound accept'))
        self.assertLess(forward.index(dns_guard), forward.index('iifname . oifname @pinned accept'))
        self.assertNotIn('flush ruleset', rules)

    def test_block_lan_is_lease_specific_and_precedes_established_or_outbound_allow(self):
        network = self.network("bitwarden")
        self.addCleanup(network.close)
        self.assertIn('lan_blocked { "veth3-app" }', self.transactions[0])
        rules = broker.RULESET.split("chain forward_guard {", 1)[1].split("chain nat {", 1)[0]
        self.assertLess(rules.index("iifname @lan_blocked ip daddr @lan_ipv4 drop"), rules.index("iifname @outbound accept"))
        self.assertLess(rules.index("iifname @lan_blocked ip daddr @lan_ipv4 drop"), rules.index("ct state established,related"))
        network.close()
        self.assertIn('delete element inet app_veth lan_blocked', self.transactions[-1])

    def test_lan_snapshot_covers_public_connected_subnets_but_preserves_tunnel_internet(self):
        def replies(argv, **options):
            if argv[-2:] == ["scope", "link"]:
                return json.dumps([{"dst": "203.0.113.0/24", "dev": "eth0"},
                                   {"dst": "0.0.0.0/1", "dev": "tun0"}])
            return json.dumps([{"ifname": "eth0"}, {"ifname": "tun0", "linkinfo": {"info_kind": "tun"}}])
        with mock.patch.object(broker, "run", side_effect=replies):
            values = broker.refresh_lan_networks(None)
            self.assertIn("203.0.113.0/24", values)
            self.assertIn("100.64.0.0/10", values)
            self.assertNotIn("0.0.0.0/1", values)
            count = len(self.transactions)
            broker.refresh_lan_networks(values)
            self.assertEqual(len(self.transactions), count)
        self.assertIn("flush set inet app_veth lan_ipv4", self.transactions[0])

    def test_peer_forwarding_policy_works_for_a_new_app_without_a_broker_code_change(self):
        policy = fixture_configuration({"new-client": {"network": True, "peer_port": 4242}})["apps"]["new-client"]
        network = broker.Network(3, 70, "new-client", 1000, policy, ipaddress.IPv4Network("10.203.0.0/24"), self.endpoints)
        self.addCleanup(network.close)
        self.assertIn('192.0.2.8 . tcp . 4242 : 10.203.0.14 . 4242', ''.join(self.transactions))
        self.assertIn('192.0.2.8 . udp . 4242 : 10.203.0.14 . 4242', ''.join(self.transactions))
        self.assertIn('pinned { "veth3-app" . "wg0" }', ''.join(self.transactions))

    def test_uplink_switch_and_prolonged_outage_keep_the_same_namespace_and_lease(self):
        network = self.network('qbittorrent')
        self.addCleanup(network.close)
        channel = mock.Mock()
        leases = {channel: network}
        original = (network.nsfd, network.slot, network.address, network.interface)
        for current in (('eth0', '192.0.2.56', 1500), ('wifi0', '192.0.2.57', 1500), None, None,
                        ('eth0', '192.0.2.56', 1400), ('tailscale0', '100.64.0.1', 1280)):
            self.calls.clear()
            self.transactions.clear()
            kwargs = {'return_value': current} if current is not None else {'side_effect': ValueError('offline')}
            with mock.patch.object(broker, 'route', **kwargs):
                broker.refresh_routes(leases)
            self.assertEqual((network.nsfd, network.slot, network.address, network.interface), original)
            self.assertEqual(leases, {channel: network})
            channel.close.assert_not_called()
            self.assertEqual(network.uplink, current)
            if current is None:
                self.assertFalse(any(argv[-1] == 'up' for argv, _ in self.calls))
                self.assertEqual(network.route_remove, [])
            else:
                transaction = ''.join(self.transactions)
                self.assertIn(f'"veth3-app" . "{current[0]}"', transaction)
                self.assertIn(f'{current[1]} . tcp . 50309 : 10.203.0.14 . 50309', transaction)
                self.assertIn(f'{current[1]} . udp . 50309 : 10.203.0.14 . 50309', transaction)
                self.assertEqual([argv for argv, _ in self.calls if argv[0] == '/usr/sbin/conntrack'],
                    [['/usr/sbin/conntrack', '-D', '-f', 'ipv4', direction, '10.203.0.14']
                     for direction in ('--orig-src', '--reply-src')])
                self.assertIn((['/usr/sbin/ip', 'link', 'set', 'dev', 'veth3-app', 'mtu', str(current[2]), 'up'], {}), self.calls)

    def test_offline_initial_launch_retains_guards_and_recovers_without_recreating_links(self):
        for app in ('qbittorrent', 'vivaldi'):
            with self.subTest(app=app), mock.patch.object(broker, 'route', side_effect=ValueError('offline')):
                network = self.network(app)
            self.addCleanup(network.close)
            self.assertTrue(network.installed)
            self.assertTrue(network.attached)
            self.assertIsNone(network.uplink)
            self.calls.clear()
            network.refresh_route(('wifi0', '192.0.2.9', 1500))
            self.assertEqual(network.uplink, ('wifi0', '192.0.2.9', 1500))
            self.assertFalse(any('netns' in argv or 'add' in argv for argv, _ in self.calls))
            network.close()

    def test_failed_route_transaction_keeps_link_down_and_retries_without_closing_lease(self):
        network = self.network('qbittorrent')
        self.addCleanup(network.close)
        self.calls.clear()
        target = ('wifi0', '192.0.2.9', 1500)
        with mock.patch.object(broker, 'nft', side_effect=RuntimeError('atomic update failed')), \
                mock.patch.object(broker.time, 'monotonic', return_value=100):
            network.refresh_route(target)
            network.refresh_route(target)  # Its own DOWN notification must not busy-loop.
        self.assertEqual(network.route_retry_at, 105)
        self.assertEqual(sum(argv[-1] == 'down' for argv, _ in self.calls), 1)
        self.assertFalse(any(argv[-1] == 'up' for argv, _ in self.calls))
        self.assertTrue(network.attached)
        self.assertTrue(network.installed)
        with mock.patch.object(broker.time, 'monotonic', return_value=105):
            network.refresh_route(target)
        self.assertIsNone(network.route_retry_at)
        self.assertIn('delete element inet app_veth pinned { "veth3-app" . "wg0" }', self.transactions[-1])
        self.assertIn('add element inet app_veth pinned { "veth3-app" . "wifi0" }', self.transactions[-1])

    def test_unchanged_route_does_not_reset_live_connections_or_spawn_commands(self):
        network = self.network('qbittorrent')
        self.addCleanup(network.close)
        self.calls.clear()
        self.transactions.clear()
        network.refresh_route(network.uplink)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.transactions, [])

    def test_mtu_only_change_preserves_firewall_ports_and_conntrack(self):
        network = self.network('qbittorrent')
        self.addCleanup(network.close)
        self.calls.clear()
        self.transactions.clear()
        reserves = broker.Network.reserve.call_count
        network.refresh_route(('wg0', '192.0.2.8', 1400))
        self.assertEqual(network.uplink, ('wg0', '192.0.2.8', 1400))
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all('mtu' in argv and argv[-1] == '1400' for argv, _ in self.calls))
        self.assertEqual(self.transactions, [])
        self.assertEqual(broker.Network.reserve.call_count, reserves)

    def test_all_current_and_future_app_policies_reuse_fixed_host_names_without_renaming(self):
        for app in sorted(set(DEFAULT_POLICIES) | {"future-desktop-app"}):
            with self.subTest(app=app):
                self.calls.clear()
                network = self.network(app)
                self.assertEqual(network.name, "veth3-app")
                network.close()
                self.assertEqual(network.name, "veth3-app")
                self.assertEqual(network.peer_name, "veth3-peer")
                for argv, _options in self.calls:
                    if argv[:5] == ["/usr/sbin/ip", "link", "set", "dev", "veth3-app"]:
                        self.assertNotIn("name", argv)
                        self.assertNotIn("alias", argv)
                    self.assertFalse("link" in argv and "add" in argv)
                self.assertTrue(any(call.kwargs.get("app") == app and call.kwargs.get("interface") == "veth3-app"
                                    for call in broker.event.call_args_list))


class DNSFrontendReadinessTests(unittest.TestCase):
    def test_native_listener_ready_immediately_or_after_a_refused_connection(self):
        create_connection = socket.create_connection
        for delayed in (False, True):
            with self.subTest(delayed=delayed), socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.settimeout(1)
                if not delayed:
                    listener.listen(1)
                calls = []
                def connect(address, timeout):
                    self.assertEqual(address, ("127.0.0.1", 53053))
                    self.assertGreater(timeout, 0)
                    self.assertLessEqual(timeout, .25)
                    if delayed and calls:
                        listener.listen(1)
                    calls.append(address)
                    return create_connection(listener.getsockname(), timeout=timeout)
                with mock.patch.object(broker.socket, "create_connection", side_effect=connect):
                    broker.wait_dns_frontend()
                self.assertEqual(len(calls), 2 if delayed else 1)
                channel, _ = listener.accept()
                with channel:
                    channel.settimeout(1)
                    self.assertEqual(channel.recv(1), b"", "readiness connection leaked")

    def test_unavailable_listener_fails_when_readiness_deadline_expires(self):
        clock = types.SimpleNamespace(monotonic=mock.Mock(side_effect=(0, 0, 5)), sleep=mock.Mock())
        cause = ConnectionRefusedError("listener unavailable")
        with mock.patch.object(broker, "time", clock), \
                mock.patch.object(broker.socket, "create_connection", side_effect=cause), \
                self.assertRaisesRegex(RuntimeError, "DNS frontend did not become ready") as failure:
            broker.wait_dns_frontend()
        self.assertIs(failure.exception.__cause__, cause)
        clock.sleep.assert_not_called()

    def test_denied_listener_fails_immediately_without_retry(self):
        with mock.patch.object(broker.socket, "create_connection", side_effect=PermissionError("denied")) as connect, \
                mock.patch.object(broker, "time", types.SimpleNamespace(monotonic=lambda: 0, sleep=mock.Mock())) as clock, \
                self.assertRaises(PermissionError):
            broker.wait_dns_frontend()
        connect.assert_called_once()
        clock.sleep.assert_not_called()

    def test_failed_readiness_does_not_publish_firewall_or_endpoint_pool(self):
        with mock.patch.object(broker.os, "geteuid", return_value=0), \
                mock.patch.object(broker, "configuration", return_value=(1000, DEFAULT_POLICIES)), \
                mock.patch.object(broker, "recover_endpoints"), \
                mock.patch.object(broker, "select_pool", return_value=ipaddress.IPv4Network("10.203.0.0/24")), \
                mock.patch.object(broker.Path, "read_text", return_value="1"), \
                mock.patch.object(broker, "wait_dns_frontend", side_effect=RuntimeError("DNS unavailable")), \
                mock.patch.object(broker, "nft") as firewall, \
                mock.patch.object(broker, "EndpointPool") as pool, \
                self.assertRaisesRegex(RuntimeError, "DNS unavailable"):
            broker.main()
        firewall.assert_not_called()
        pool.assert_not_called()


class BrokerLifecycleTests(unittest.TestCase):
    def test_only_failed_administrative_updates_have_retry_deadlines(self):
        healthy = types.SimpleNamespace(route_retry_at=None)
        offline = types.SimpleNamespace(route_retry_at=None)
        with mock.patch.object(broker.time, 'monotonic', return_value=102) as clock:
            self.assertIsNone(broker.route_retry_timeout({}))
            self.assertIsNone(broker.route_retry_timeout({1: healthy, 2: offline}))
            clock.assert_not_called()
            failed = {1: types.SimpleNamespace(route_retry_at=105),
                      2: types.SimpleNamespace(route_retry_at=106)}
            self.assertEqual(broker.route_retry_timeout(failed), 3)
        with mock.patch.object(broker.time, 'monotonic', return_value=107):
            self.assertEqual(broker.route_retry_timeout(failed), 0)

    def test_main_route_notification_updates_lease_and_only_shutdown_closes_it(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            nsfd = os.open('/dev/null', os.O_RDONLY | os.O_CLOEXEC)
            network = mock.Mock(nsfd=nsfd, slot=28, address='10.203.0.114',
                gateway='10.203.0.113', interface='eth0', pinned=True, route_retry_at=None)
            channel, listener, watcher, selector = [mock.Mock() for _ in range(4)]
            listener.accept.return_value = (channel, None)
            watcher.recv.side_effect = BlockingIOError
            waits = []
            def select_events(timeout):
                waits.append(timeout)
                if len(waits) == 1:
                    return [(types.SimpleNamespace(fileobj=listener), 1)]
                if len(waits) == 2:
                    return [(types.SimpleNamespace(fileobj=watcher), 1)]
                network.close.assert_not_called()
                channel.close.assert_not_called()
                selector.unregister.assert_not_called()
                raise KeyboardInterrupt
            selector.select.side_effect = select_events
            for name, value in (('recover_endpoints', None), ('wait_dns_frontend', None),
                    ('select_pool', ipaddress.IPv4Network('10.203.0.0/23')),
                    ('configuration', (1000, DEFAULT_POLICIES)), ('refresh_lan_networks', ()),
                    ('EndpointPool', mock.Mock()), ('Network', network), ('nft', None)):
                stack.enter_context(mock.patch.object(broker, name, return_value=value))
            stack.enter_context(mock.patch.object(broker, 'receive', return_value=(1234, 1000, 'qbittorrent', nsfd, None)))
            stack.enter_context(mock.patch.object(broker, 'route', side_effect=ValueError('offline')))
            stack.enter_context(mock.patch.object(broker, 'event'))
            stack.enter_context(mock.patch.object(broker.os, 'geteuid', return_value=0))
            stack.enter_context(mock.patch.object(broker.os, 'chmod'))
            stack.enter_context(mock.patch.object(broker.Path, 'read_text', return_value='1'))
            stack.enter_context(mock.patch.object(broker, 'SOCKET_PATH', str(Path(directory) / 'control.sock')))
            stack.enter_context(mock.patch.object(broker.selectors, 'DefaultSelector', return_value=selector))
            stack.enter_context(mock.patch.object(broker.socket, 'socket', side_effect=(watcher, listener)))
            stack.enter_context(mock.patch.dict(broker.os.environ, {'NOTIFY_SOCKET': ''}))
            stack.enter_context(mock.patch.object(broker.signal, 'signal'))
            with self.assertRaises(KeyboardInterrupt):
                broker.main()
            self.assertEqual(waits, [None, None, None])
            network.refresh_route.assert_called_once_with(None)
            network.close.assert_called_once()
            channel.close.assert_called_once()
            with self.assertRaises(OSError):
                os.fstat(nsfd)

    def test_startup_failure_closes_owned_resources_and_preserves_unsafe_socket_paths(self):
        for fault in ('route', 'unsafe-socket', 'pool'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                path = Path(directory) / 'control.sock'
                if fault == 'unsafe-socket':
                    path.write_text('preserve', encoding='ascii')
                pool = mock.Mock()
                selector = mock.Mock()
                route_watch = mock.Mock()
                listener = mock.Mock()
                if fault == 'route':
                    route_watch.bind.side_effect = OSError('route watch failed')
                stack.enter_context(mock.patch.object(broker.os, 'geteuid', return_value=0))
                stack.enter_context(mock.patch.object(broker, 'configuration', return_value=(1000, DEFAULT_POLICIES)))
                stack.enter_context(mock.patch.object(broker, 'recover_endpoints'))
                stack.enter_context(mock.patch.object(broker, 'select_pool', return_value=ipaddress.IPv4Network('10.203.0.0/24')))
                stack.enter_context(mock.patch.object(broker.Path, 'read_text', return_value='1'))
                stack.enter_context(mock.patch.object(broker.socket, 'create_connection'))
                firewall = stack.enter_context(mock.patch.object(broker, 'nft'))
                stack.enter_context(mock.patch.object(broker, 'EndpointPool', return_value=pool,
                    side_effect=RuntimeError('pool failed') if fault == 'pool' else None))
                stack.enter_context(mock.patch.object(broker.selectors, 'DefaultSelector', return_value=selector))
                sockets = stack.enter_context(mock.patch.object(broker.socket, 'socket', side_effect=(route_watch, listener)))
                stack.enter_context(mock.patch.object(broker, 'refresh_lan_networks', return_value=()))
                stack.enter_context(mock.patch.object(broker.signal, 'signal'))
                stack.enter_context(mock.patch.object(broker, 'SOCKET_PATH', str(path)))
                expected = {'route': 'route watch failed', 'unsafe-socket': 'socket is unsafe', 'pool': 'pool failed'}[fault]
                with self.assertRaisesRegex((OSError, ValueError, RuntimeError), expected):
                    broker.main()
                if fault == 'pool':
                    pool.close.assert_not_called()
                    sockets.assert_not_called()
                    firewall.assert_called_once_with(broker.RULESET)
                else:
                    pool.close.assert_called_once()
                    selector.close.assert_called_once()
                    route_watch.close.assert_called_once()
                    self.assertEqual(firewall.call_args.args, ('destroy table inet app_veth\n',))
                if fault == 'unsafe-socket':
                    self.assertEqual(path.read_bytes(), b'preserve')
                    listener.close.assert_called_once()

    def test_unregister_failure_keeps_the_lease_owned_for_service_cleanup(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        namespace_fd = os.open('/dev/null', os.O_RDONLY)
        network = mock.Mock(nsfd=namespace_fd)
        leases = {left: network}
        try:
            with broker.selectors.DefaultSelector() as selector:
                with self.assertRaises(KeyError):
                    broker.release_lease(selector, leases, left)
                self.assertIs(leases[left], network)
                network.close.assert_not_called()
                os.fstat(namespace_fd)
                selector.register(left, broker.selectors.EVENT_READ)
                broker.release_lease(selector, leases, left)
                self.assertEqual(leases, {})
                network.close.assert_called_once()
                with self.assertRaises(OSError):
                    os.fstat(namespace_fd)
        finally:
            supervisor.close_file_descriptor(namespace_fd)
            left.close()
            right.close()


class SupervisorTests(unittest.TestCase):
    def test_sandbox_wrapper_forwards_shutdown_policy_and_callbacks_to_real_signature(self):
        command = ['/usr/bin/bwrap', '--unshare-all', '--proc', '/proc']
        payload = ['/usr/bin/chromium']
        precheck, runtime_check, deadline, failure = (mock.Mock() for _ in range(4))
        for graceful in (False, True):
            with self.subTest(graceful=graceful), mock.patch.object(
                    supervisor, 'run_veth_sandbox', autospec=True, return_value=37) as launch:
                self.assertEqual(sandbox.run_veth_sandbox(
                    command, payload, '/fixture', (7,), app='chromium',
                    pre_payload_check=precheck, runtime_check=runtime_check,
                    cleanup_deadline=deadline, cleanup_failure=failure,
                    network=False, graceful_shutdown=graceful), 37)
                launch.assert_called_once_with(
                    command, payload, '/fixture', (7,), app='chromium',
                    pre_payload_check=precheck, runtime_check=runtime_check,
                    cleanup_deadline=deadline, cleanup_failure=failure,
                    network=False, graceful_shutdown=graceful)
        with mock.patch.object(supervisor, 'run_veth_sandbox', autospec=True, return_value=0) as launch:
            self.assertEqual(sandbox.run_veth_sandbox(command, payload, '/fixture', (), app='keepassxc'), 0)
            self.assertFalse(launch.call_args.kwargs['graceful_shutdown'])
            self.assertTrue(launch.call_args.kwargs['network'])

    def test_native_wait_observes_child_exit_without_polling(self):
        with subprocess.Popen([sys.executable, '-I', '-B', '-c', 'raise SystemExit(37)']) as process:
            self.assertEqual(supervisor.wait_for_payload(process, None), 37)

    def test_native_wait_observes_payload_exit_with_a_live_lease(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        lease = object.__new__(client.Lease)
        lease.socket = left
        lease.retry_at = None
        opened = []
        native_open = os.pidfd_open
        with subprocess.Popen([sys.executable, '-I', '-B', '-c',
                               'import sys; sys.stdin.buffer.read(1); raise SystemExit(37)'],
                              stdin=subprocess.PIPE) as process:
            def open_then_release(pid):
                descriptor = native_open(pid)
                opened.append(descriptor)
                process.stdin.write(b'x')
                process.stdin.flush()
                return descriptor
            try:
                with mock.patch.object(supervisor.os, 'pidfd_open', side_effect=open_then_release):
                    self.assertEqual(supervisor.wait_for_payload(process, lease), 37)
                self.assertEqual(len(opened), 1)
                with self.assertRaises(OSError):
                    os.fstat(opened[0])
            finally:
                process.stdin.close()
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=3)
                left.close()
                right.close()

    def test_payload_wait_survives_broker_loss_until_normal_process_exit(self):
        descriptor = os.open('/dev/null', os.O_RDONLY | os.O_CLOEXEC)
        process = mock.Mock(pid=1234)
        process.poll.return_value = None
        process.wait.return_value = 37
        lease = mock.Mock(socket=mock.Mock())
        lease.retry_timeout.return_value = None
        def disconnected():
            lease.socket = None
            lease.retry_timeout.return_value = 5
        lease.maintain.side_effect = disconnected
        with mock.patch.object(supervisor.os, 'pidfd_open', return_value=descriptor), \
                mock.patch.object(supervisor.select, 'select', return_value=([descriptor], [], [])) as wait:
            self.assertEqual(supervisor.wait_for_payload(process, lease), 37)
        wait.assert_called_once_with([descriptor], [], [], 5)
        lease.check.assert_not_called()
        process.terminate.assert_not_called()
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_offline_payload_is_gated_and_its_namespace_is_reaped_without_a_lease(self):
        process = mock.Mock()
        process.poll.side_effect = [None, 0]
        pidfd = os.open("/dev/null", os.O_RDONLY)
        with mock.patch.object(supervisor.subprocess, "Popen", return_value=process), \
                mock.patch.object(supervisor, "_read_bwrap_sandbox_pid", return_value=1234), \
                mock.patch.object(supervisor, "pin_sandbox_init", return_value=pidfd), \
                mock.patch.object(client.Lease, "for_pid") as acquire, \
                mock.patch.object(supervisor.os, "write", return_value=1) as release, \
                mock.patch.object(supervisor.signal, "pidfd_send_signal") as stop, \
                mock.patch.object(supervisor, "_stop_subprocess"):
            self.assertEqual(supervisor.run_veth_sandbox(["bwrap"], ["app"], "/unused", (), app="keepassxc", network=False), 0)
        acquire.assert_not_called()
        self.assertEqual(release.call_count, 2)
        stop.assert_called_once_with(pidfd, supervisor.signal.SIGKILL)

    def test_failed_network_kills_pinned_init_before_closing_release_fds(self):
        events = []
        sandbox = mock.Mock()
        sandbox.poll.return_value = None
        pidfd = os.open("/dev/null", os.O_RDONLY)
        original_close = supervisor.close_file_descriptor
        def close(fd):
            events.append(("close", fd))
            original_close(fd)
        with mock.patch.object(supervisor.subprocess, "Popen", return_value=sandbox), \
                mock.patch.object(supervisor, "_read_bwrap_sandbox_pid", return_value=1234), \
                mock.patch.object(supervisor, "pin_sandbox_init", return_value=pidfd), \
                mock.patch.object(client.Lease, "for_pid", side_effect=ValueError("rejected")), \
                mock.patch.object(supervisor.signal, "pidfd_send_signal", side_effect=lambda *a: events.append(("kill", a))), \
                mock.patch.object(supervisor, "close_file_descriptor", side_effect=close), \
                mock.patch.object(supervisor, "_stop_subprocess") as stop, \
                mock.patch.object(supervisor.os, "write") as release, self.assertRaises(SystemExit):
            supervisor.run_veth_sandbox(["/usr/bin/bwrap"], ["/usr/bin/true"], "/unused", (), app="codex")
        stop.assert_called_once_with(sandbox)
        release.assert_not_called()
        kill_index = next(i for i,item in enumerate(events) if item[0] == "kill")
        self.assertTrue(all(i > kill_index for i,item in enumerate(events) if item == ("close", pidfd)))

    def test_runtime_network_pause_does_not_stop_the_payload(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.return_value = 37
        lease = mock.Mock()
        pidfd = os.open('/dev/null', os.O_RDONLY)
        with mock.patch.object(supervisor.subprocess, 'Popen', return_value=process), \
                mock.patch.object(supervisor, '_read_bwrap_sandbox_pid', return_value=1234), \
                mock.patch.object(supervisor, 'pin_sandbox_init', return_value=pidfd), \
                mock.patch.object(client.Lease, 'for_pid', return_value=lease), \
                mock.patch.object(supervisor.signal, 'pidfd_send_signal'), \
                mock.patch.object(supervisor.os, 'write'), \
                mock.patch.object(supervisor, '_stop_subprocess'):
            self.assertEqual(supervisor.run_veth_sandbox(['/usr/bin/bwrap'], ['/usr/bin/true'],
                '/unused', (), app='codex', runtime_check=mock.Mock()), 37)
        lease.check.assert_called_once()  # Strict startup acknowledgment.
        lease.maintain.assert_called_once()  # Runtime recovery does not throw for broker loss.
        lease.close.assert_called_once()

    def test_normal_payload_exit_ends_pinned_namespace_before_releasing_network(self):
        events = []
        process = mock.Mock()
        process.poll.side_effect = [None, 0]
        lease = mock.Mock()
        lease.close.side_effect = lambda: events.append("lease-close")
        pidfd = os.open("/dev/null", os.O_RDONLY)
        with mock.patch.object(supervisor.subprocess, "Popen", return_value=process), \
                mock.patch.object(supervisor, "_read_bwrap_sandbox_pid", return_value=1234), \
                mock.patch.object(supervisor, "pin_sandbox_init", return_value=pidfd), \
                mock.patch.object(client.Lease, "for_pid", return_value=lease), \
                mock.patch.object(supervisor.os, "write"), \
                mock.patch.object(supervisor.signal, "pidfd_send_signal", side_effect=lambda *args: events.append("namespace-stop")) as stop, \
                mock.patch.object(supervisor, "_stop_subprocess"):
            self.assertEqual(supervisor.run_veth_sandbox(["bwrap"], ["app"], "/unused", (), app="mpv"), 0)
        stop.assert_called_once_with(pidfd, supervisor.signal.SIGKILL)
        self.assertEqual(events, ["namespace-stop", "lease-close"])

    def test_requested_shutdown_waits_only_for_an_authorized_payload_before_namespace_cleanup(self):
        for outcome in ('exit', 'timeout', 'setup-stop', 'lease-loss'):
            with self.subTest(outcome=outcome):
                events = []
                handlers = {}
                process = mock.Mock()
                process.poll.return_value = None
                lease = mock.Mock()
                lease.close.side_effect = lambda: events.append('lease-close')
                pidfd = os.open('/dev/null', os.O_RDONLY)
                original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, ())

                def wait(timeout):
                    self.assertEqual(timeout, supervisor.PROCESS_GRACEFUL_STOP_TIMEOUT_SECONDS)
                    events.append('graceful-wait')
                    if outcome == 'timeout':
                        raise subprocess.TimeoutExpired('fixture', timeout)
                    return 0

                process.wait.side_effect = wait
                def interrupted(*args):
                    if outcome == 'lease-loss':
                        raise RuntimeError('lease lost')
                    handlers[signal.SIGINT](signal.SIGINT, None)

                def register(signum, handler):
                    previous = handlers.get(signum, signal.SIG_DFL)
                    handlers[signum] = handler
                    return previous

                setup_check = interrupted if outcome == 'setup-stop' else None
                with mock.patch.object(supervisor.subprocess, 'Popen', return_value=process), \
                        mock.patch.object(supervisor, '_read_bwrap_sandbox_pid', return_value=1234), \
                        mock.patch.object(supervisor, 'pin_sandbox_init', return_value=pidfd), \
                        mock.patch.object(client.Lease, 'for_pid', return_value=lease), \
                        mock.patch.object(supervisor.os, 'write'), \
                        mock.patch.object(supervisor, 'wait_for_payload', side_effect=interrupted), \
                        mock.patch.object(supervisor.signal, 'signal', side_effect=register), \
                        mock.patch.object(supervisor.signal, 'pidfd_send_signal',
                                          side_effect=lambda *args: events.append('namespace-stop')), \
                        mock.patch.object(supervisor, '_stop_subprocess'), self.assertRaises(SystemExit):
                    supervisor.run_veth_sandbox(['bwrap'], ['app'], '/unused', (), app='qbittorrent',
                        pre_payload_check=setup_check, graceful_shutdown=True)
                expected = ['namespace-stop', 'lease-close']
                if outcome in ('exit', 'timeout'):
                    expected.insert(0, 'graceful-wait')
                self.assertEqual(events, expected)
                self.assertEqual(handlers, {watched: signal.SIG_DFL for watched in
                                           (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)})
                self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, ()), original_mask)
                with self.assertRaises(OSError):
                    os.fstat(pidfd)

    def test_teardown_errors_still_close_every_pipe_pidfd_and_network_lease(self):
        for fault in ('stop', 'deadline'):
            with self.subTest(fault=fault), contextlib.ExitStack() as stack:
                process = mock.Mock()
                process.poll.side_effect = [None, 0]
                lease = mock.Mock()
                pidfd = os.open('/dev/null', os.O_RDONLY)
                pipes = []
                native_pipe = os.pipe
                def pipe():
                    pair = native_pipe()
                    pipes.extend(pair)
                    return pair
                stack.enter_context(mock.patch.object(supervisor.os, 'pipe', side_effect=pipe))
                stack.enter_context(mock.patch.object(supervisor.subprocess, 'Popen', return_value=process))
                stack.enter_context(mock.patch.object(supervisor, '_read_bwrap_sandbox_pid', return_value=1234))
                stack.enter_context(mock.patch.object(supervisor, 'pin_sandbox_init', return_value=pidfd))
                stack.enter_context(mock.patch.object(client.Lease, 'for_pid', return_value=lease))
                stack.enter_context(mock.patch.object(supervisor.os, 'write'))
                stack.enter_context(mock.patch.object(supervisor.signal, 'pidfd_send_signal'))
                stack.enter_context(mock.patch.object(supervisor, '_stop_subprocess',
                    side_effect=OSError('stop failed') if fault == 'stop' else None))
                deadline = mock.Mock(side_effect=RuntimeError('deadline failed')) if fault == 'deadline' else None
                with self.assertRaisesRegex((OSError, RuntimeError), f'{fault} failed'):
                    supervisor.run_veth_sandbox(['bwrap'], ['app'], '/unused', (), app='codex',
                        pre_payload_check=mock.Mock(side_effect=ValueError('payload readiness failed')),
                        cleanup_deadline=deadline)
                lease.close.assert_called_once()
                for descriptor in (*pipes, pidfd):
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_pid_namespace_cleanup_rejects_the_current_host_namespace(self):
        with self.assertRaisesRegex(ValueError, "separate PID namespace"):
            supervisor.pin_sandbox_init(os.getpid())

    def test_real_startup_gate_rejects_eof_and_preserves_literal_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/"payload"
            for gate, readiness in ((supervisor.PEER_STARTUP_GATE, b""),
                                    (supervisor.PEER_STARTUP_GATE, b"1"),
                                    (supervisor.GRACEFUL_PEER_STARTUP_GATE, b""),
                                    (supervisor.GRACEFUL_PEER_STARTUP_GATE, b"1")):
                with self.subTest(graceful=gate == supervisor.GRACEFUL_PEER_STARTUP_GATE, readiness=readiness):
                    reader, writer = os.pipe()
                    literal = 'literal $(touch unsafe); "two words"'
                    command = [sys.executable, "-I", "-B", "-c", gate, str(reader),
                        sys.executable, "-I", "-B", "-c", 'import sys;from pathlib import Path;Path(sys.argv[1]).write_text(sys.argv[2])', str(marker), literal]
                    with subprocess.Popen(command, pass_fds=(reader,)) as process:
                        os.close(reader)
                        if readiness:
                            os.write(writer, readiness)
                        os.close(writer)
                        status = process.wait(timeout=5)
                    if readiness:
                        self.assertEqual(status, 0)
                        self.assertEqual(marker.read_text(encoding="utf-8"), literal)
                    else:
                        self.assertNotEqual(status, 0)
                        self.assertFalse(marker.exists())


class DesktopLaunchTests(unittest.TestCase):
    def setUp(self):
        # Policies come from the rendered production template; only installed
        # file ownership/path access is modeled for these mount-plan fixtures.
        patch = mock.patch.object(client, "_configuration", return_value=DEFAULT_CONFIGURATION)
        patch.start()
        self.addCleanup(patch.stop)

    def test_tor_actions_accept_web_uris_and_reject_runtime_switches(self):
        for mode in ('launch', 'intel', 'nvidia', 'pure-privacy'):
            for arguments in ([], ['https://example.org/'], ['http://example.onion/']):
                with self.subTest(mode=mode, arguments=arguments):
                    sandbox.validate_managed_arguments(mode, arguments, app_name='tor-browser')
            for arguments in (['--profile=/tmp/unsafe'], ['--no-sandbox'], ['--anon'],
                              ['file:///etc/passwd'], ['https://user:password@example.org/'],
                              ['https://example.org/\n'], ['https://example.org/', 'https://second.org/']):
                with self.subTest(mode=mode, arguments=arguments), self.assertRaises(SystemExit):
                    sandbox.validate_managed_arguments(mode, arguments, app_name='tor-browser')

    def test_known_desktop_executables_and_aliases_reenter_managed_launchers(self):
        for app, policy in profiles.APPS.items():
            for executable in (policy["exec"], *generic.MANAGED_EXECUTABLE_ALIASES.get(app, ())):
                with self.subTest(app=app, executable=executable):
                    command = generic.managed_network_command("intel", [executable, "literal argument; $HOME"])
                    self.assertIsNotNone(command)
                    self.assertEqual(command[-1], "literal argument; $HOME")
                    if app in profiles.WAYLAND_COMPAT_APPS:
                        self.assertEqual(command[:3], ["/usr/local/bin/labwc-wayland-compat-app", "intel", app])
                    elif app == "chatgpt":
                        self.assertEqual(command[:2], ["/usr/local/bin/chatgpt", "intel"])
                    elif app == "qbittorrent":
                        self.assertEqual(command[:2], ["/usr/local/bin/labwc-qbittorrent", "--acceleration=intel"])
                    else:
                        self.assertEqual(command[:3], ["/usr/local/bin/labwc-app", "intel", app])
        self.assertIsNone(generic.managed_network_command("launch", ["/usr/bin/thunar"]))
        self.assertIsNone(generic.managed_network_command("launch", ["/home/user/code"]))

    def test_future_executable_policy_reenters_the_user_service_worker_with_literal_arguments(self):
        future = fixture_configuration({"new-client": {"network": True, "block_lan": True,
                                    "executables": ["/opt/new-client/client"]}})
        with mock.patch.object(client, "_configuration", return_value=future):
            self.assertEqual(generic.managed_network_command("intel", ["/opt/new-client/client", "literal; $HOME"], kind="electron"),
                ["/usr/local/libexec/app-veth-run", "electron", "intel", "new-client", "--", "/opt/new-client/client", "literal; $HOME"])
        with mock.patch.object(client, "_configuration", return_value={"apps": {}}):
            self.assertIsNone(generic.managed_network_command("intel", ["/opt/new-client/client"]))

    def test_executable_aliases_are_fresh_and_ambiguous_policies_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second, alias = (Path(directory) / name for name in ('first', 'second', 'alias'))
            first.write_text('', encoding='ascii')
            second.write_text('', encoding='ascii')
            alias.symlink_to(first)
            apps = {'first': {'executables': (str(first),)}, 'second': {'executables': (str(second),)}}
            with mock.patch.object(client, '_configuration', return_value={'network': DEFAULT_CONFIGURATION['network'], 'apps': apps}):
                self.assertEqual(client.configured_executable_application(str(alias)), 'first')
                alias.unlink()
                alias.symlink_to(second)
                self.assertEqual(client.configured_executable_application(str(alias)), 'second')
                apps['first']['executables'] = (str(second),)
                with self.assertRaisesRegex(ValueError, 'more than one'):
                    client.configured_executable_application(str(alias))

    def test_future_client_keeps_vendor_label_without_restart_metadata(self):
        original = ["/opt/new-client/client", "literal; $HOME"]
        worker = ["/usr/local/libexec/app-veth-run", "electron", "intel", "new-client", "--", *original]
        environment = {}
        with mock.patch.object(generic, "assert_launch_allowed"):
            command = generic.transient_argv("electron", "intel", worker, environment,
                                             application_arguments=original)
        self.assertNotIn("LABWC_SESSION_RESTORE", environment)
        self.assertEqual(command[command.index("--") + 1:], worker)
        self.assertTrue(any(value.startswith("--unit=labwc-electron-client-") for value in command))
        self.assertEqual(set(environment[generic.CONFIGURED_ENVIRONMENT_NAMES].split()), {"LABWC_SESSION_APP"})

    def test_configured_worker_preserves_explicit_environment_without_importing_manager_values(self):
        names = "HOME VENDOR_OPTION LABWC_SESSION_APP"
        with mock.patch.dict(os.environ, {generic.CONFIGURED_ENVIRONMENT_NAMES: names,
                "HOME": "/home/desktop", "VENDOR_OPTION": "literal; $HOME",
                "LABWC_SESSION_APP": "1",
                "UNRELATED_MANAGER_SECRET": "not-forwarded"}, clear=True):
            environment = generic.configured_worker_environment({"HOME": "/home/desktop"})
        self.assertEqual(environment, {"HOME": "/home/desktop", "VENDOR_OPTION": "literal; $HOME",
                                      "LABWC_SESSION_APP": "1"})
        for names, values in (("LD_PRELOAD", {"LD_PRELOAD": "/tmp/injected.so"}),
                              ("HOME", {"HOME": "/root"}), ("MISSING", {}),
                              ("OPTION OPTION", {"OPTION": "value"}),
                              ("OPTION", {"OPTION": "x" * 65537})):
            with self.subTest(names=names), \
                    mock.patch.dict(os.environ, {generic.CONFIGURED_ENVIRONMENT_NAMES: names, **values}, clear=True), \
                    self.assertRaises(SystemExit):
                generic.configured_worker_environment({"HOME": "/home/desktop"})

    def test_administration_launchers_do_not_depend_on_network_policy_availability(self):
        with mock.patch.object(client, "configured_executable_application", side_effect=ValueError("malformed JSON")) as policy:
            for executable in ("/usr/bin/foot", "/usr/bin/thunar", "/usr/local/bin/labwc-terminal",
                               "/usr/bin/labwc-tweaks", "/usr/bin/qt6ct"):
                self.assertIsNone(generic.managed_network_command("launch", [executable]))
        policy.assert_not_called()

    def test_compositor_settings_keep_host_identity_ipc_and_persistent_config(self):
        for executable in ("/usr/bin/labwc-tweaks", "/usr/bin/qt6ct"):
            environment = {"HOME": "/home/desktop", "XDG_CONFIG_HOME": "/home/desktop/.config"}
            with self.subTest(executable=executable), mock.patch.object(generic, "assert_launch_allowed"), \
                    mock.patch.dict(os.environ, {"LABWC_PID": "4567"}, clear=True):
                command = generic.transient_argv("wayland", "auto", [executable], environment)
            for option in ("PrivatePIDs=no", "PrivateUsers=no", "PrivateIPC=no"):
                self.assertIn("--property=" + option, command)
            self.assertNotIn("--property=PrivateTmp=yes", command)
            self.assertEqual(environment["XDG_CONFIG_HOME"], "/home/desktop/.config")
            self.assertEqual(environment.get("LABWC_PID"), "4567" if executable.endswith("labwc-tweaks") else None)
        with mock.patch.object(generic, "assert_launch_allowed"), \
                mock.patch.dict(os.environ, {"LABWC_PID": "1; kill -9 1"}, clear=True), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            generic.transient_argv("wayland", "auto", ["/usr/bin/labwc-tweaks"], {})

    def test_configured_generic_worker_keeps_private_network_procfs_and_hides_broker_endpoint(self):
        for online in (True, False):
            future = fixture_configuration({"new-client": {"network": online, "executables": ["/usr/bin/true"]}})
            with self.subTest(online=online), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(client, "_configuration", return_value=future))
                stack.enter_context(mock.patch.object(generic.os, "geteuid", return_value=1000))
                stack.enter_context(mock.patch.object(generic, "assert_launch_allowed"))
                stack.enter_context(mock.patch.object(generic, "session_environment", return_value={"XDG_RUNTIME_DIR": directory}))
                stack.enter_context(mock.patch.object(generic, "load_managed_defaults", return_value={}))
                stack.enter_context(mock.patch.object(generic, "acceleration_availability_from_defaults", return_value={"intel": True, "nvidia": True}))
                stack.enter_context(mock.patch.object(generic, "require_root_owned_executable", side_effect=lambda label, path: path))
                stack.enter_context(mock.patch.dict(os.environ, {
                    generic.CONFIGURED_ENVIRONMENT_NAMES: "VENDOR_TOKEN", "VENDOR_TOKEN": "fixture-token"}, clear=True))
                def launch(command, payload, temporary, inherited, **options):
                    self.assertIn("--unshare-net", command)
                    self.assertIn("--unshare-pid", command)
                    self.assertIn("--proc", command)
                    self.assertEqual(command[command.index("/run/app-veth") - 1], "--tmpfs")
                    self.assertNotIn("/run/app-veth/control.sock", command)
                    self.assertEqual((Path(temporary) / "resolv.conf").read_text(encoding="ascii"),
                                     client.resolver_configuration() if online else "# Networking is disabled.\n")
                    self.assertEqual(payload[-2:], ["/usr/bin/true", "literal; $HOME"])
                    self.assertEqual(payload[:4], ["/usr/bin/python3", "-I", "-B", "-c"])
                    environment_path = Path(temporary) / "environment.json"
                    environment = json.loads(environment_path.read_text(encoding="utf-8"))
                    self.assertEqual(environment["VENDOR_TOKEN"], "fixture-token")
                    self.assertEqual(stat.S_IMODE(environment_path.stat().st_mode), 0o600)
                    self.assertFalse(any("fixture-token" in item for item in (*command, *payload)))
                    self.assertEqual(payload[5], "/tmp/.labwc-app-environment.json")
                    # Execute the loader against its real private fixture file.
                    result = subprocess.run([*payload[:5], str(environment_path), *payload[6:]],
                                            capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(options, {"app": "new-client", "network": online})
                    return 37
                stack.enter_context(mock.patch.object(supervisor, "run_veth_sandbox", side_effect=launch))
                self.assertEqual(generic.run_configured_network(["wayland", "intel", "new-client", "--", "/usr/bin/true", "literal; $HOME"]), 37)

    def test_native_persistent_launches_gate_payload_and_preserve_only_configured_state(self):
        self._check_persistent_launches(DEFAULT_POLICIES)

    def test_removing_all_app_policies_keeps_persistent_apps_offline(self):
        self._check_persistent_launches({})

    def _check_persistent_launches(self, policies):
        apps = set(profiles.PERSISTENT_SANDBOX_CONFIG) - {"chatgpt", "discord", "zoom", "tutanota", "qbittorrent", "qoredb"}
        for app in sorted(apps):
            with self.subTest(app=app), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(client, "_configuration", return_value={"network": DEFAULT_CONFIGURATION["network"], "apps": policies}))
                root = Path(directory)
                home, runtime = root / "home", root / "runtime"
                home.mkdir(); runtime.mkdir(mode=0o700)
                for path in ("Downloads", "Documents", "Pictures", "Workspace", "Music", "Videos"):
                    (home/path).mkdir()
                env = {"HOME": str(home), "XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-0"}
                if app == "code":
                    # Exercise the real directory validator against private
                    # fixture data, never depend on this machine's /pool.
                    policy = dict(profiles.PERSISTENT_SANDBOX_CONFIG[app], rw_bind_paths=(str(home/"Workspace"),))
                    stack.enter_context(mock.patch.dict(sandbox.PERSISTENT_SANDBOX_CONFIG, {app: policy}))
                stack.enter_context(mock.patch.object(sandbox, "build_environment", return_value=env))
                stack.enter_context(mock.patch.object(sandbox, "persistent_sandbox_argv", return_value=[profiles.APPS[app]["exec"], "literal-url"]))
                stack.enter_context(mock.patch.object(sandbox, "require_root_owned_executable", side_effect=lambda label, path: path))
                stack.enter_context(mock.patch.object(sandbox, "require_root_owned_regular_file", side_effect=lambda label, path, **options: path))
                optional_bind = stack.enter_context(mock.patch.object(sandbox, "add_optional_bind", wraps=sandbox.add_optional_bind))
                stack.enter_context(mock.patch.object(sandbox, "current_user_runtime_socket", return_value=str(runtime/"wayland-0")))
                session_proxy = stack.enter_context(mock.patch.object(sandbox, "start_session_bus_proxy", return_value=(None, None, None)))
                stack.enter_context(mock.patch.object(sandbox, "start_system_bus_proxy", return_value=(None, None, None)))
                for name in ("stop_dbus_proxies", "require_running_dbus_proxies", "add_gpu_device_binds", "add_video_device_binds", "add_native_device_binds"):
                    stack.enter_context(mock.patch.object(sandbox, name))
                stack.enter_context(mock.patch.object(sandbox.mounts, "add_user_media_directory_bind"))
                def launch(command, payload, temporary, inherited, **options):
                    self.assertEqual(options["app"], app)
                    self.assertEqual(options["network"], app in policies)
                    expected_payload = [profiles.APPS[app]["exec"], "literal-url"]
                    if app in sandbox.BROWSER_PROXY_POLICIES:
                        expected_payload = ['/usr/local/libexec/labwc-proxy-session', app,
                                            *([] if options['network'] else ['--offline']),
                                            *expected_payload]
                    self.assertEqual(payload, expected_payload)
                    self.assertEqual(options['graceful_shutdown'], app in sandbox.BROWSER_PROXY_POLICIES)
                    self.assertNotIn("literal-url", command)
                    self.assertNotIn("--share-net", command)
                    self.assertIn("--unshare-all", command)
                    if app in {"chromium", "microsoft-edge", "vivaldi"}:
                        optional_bind.assert_any_call(command, "--ro-bind", "/etc/opt/chrome", "/etc/opt/chrome")
                    sandbox.validate_private_procfs(command)
                    resolver = command[command.index("/etc/resolv.conf")-1]
                    if app in policies:
                        self.assertEqual(Path(resolver).read_text(encoding="utf-8"), sandbox.veth_resolv_conf())
                    bindings = [command[i+1:i+3] for i, value in enumerate(command) if value == "--bind"]
                    for relative in profiles.PERSISTENT_SANDBOX_CONFIG[app]["persistent_paths"]:
                        self.assertIn([str(home/relative), str(home/relative)], bindings)
                    self.assertNotIn([str(home), str(home)], bindings)
                    self.assertNotIn("/run/app-veth/control.sock", command)
                    private_temp = str(runtime/f"labwc-{app}-tmp")
                    self.assertIn([private_temp, private_temp], bindings)
                    self.assertEqual(env["TMPDIR"], private_temp)
                    if app == "code":
                        self.assertEqual(command[:4], ["/usr/bin/aa-exec", "--profile=labwc-app//code-bwrap", "--", "/usr/bin/bwrap"])
                    return 37
                stack.enter_context(mock.patch.object(supervisor, "run_veth_sandbox", autospec=True, side_effect=launch))
                self.assertEqual(sandbox.run_persistent_sandbox(app, "launch", []), 37)
                session_proxy.assert_called_once()
                self.assertEqual(session_proxy.call_args.args[2],
                                 ("org.mpris.MediaPlayer2.vivaldi.*",) if app == "vivaldi"
                                 else profiles.PERSISTENT_SANDBOX_CONFIG[app].get("dbus_own_names", ()))

    def test_pure_privacy_veth_gets_payload_after_gate_and_private_resolver(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            env = {"HOME": "/home/user", "XDG_RUNTIME_DIR": str(root), "WAYLAND_DISPLAY": "wayland-0",
                   "XDG_CONFIG_HOME": "/home/user/.config", "XDG_CACHE_HOME": "/home/user/.cache",
                   "XDG_DATA_HOME": "/home/user/.local/share", "XDG_STATE_HOME": "/home/user/.local/state",
                   "TMPDIR": "/home/user/.tmp"}
            stack.enter_context(mock.patch.object(sandbox, "pure_privacy_environment", return_value=env))
            stack.enter_context(mock.patch.object(sandbox, "pure_privacy_argv", return_value=["/usr/bin/chromium", "literal-url"]))
            stack.enter_context(mock.patch.object(sandbox, "require_root_owned_executable", return_value="/usr/bin/bwrap"))
            stack.enter_context(mock.patch.object(sandbox, "require_root_owned_regular_file", side_effect=lambda label, path, **options: path))
            stack.enter_context(mock.patch.object(sandbox, "current_user_runtime_socket", return_value=str(root/"wayland-0")))
            stack.enter_context(mock.patch.object(sandbox, "current_user_home", return_value=str(root)))
            stack.enter_context(mock.patch.object(sandbox, "start_session_bus_proxy", return_value=(None, None, None)))
            stack.enter_context(mock.patch.object(sandbox, "stop_dbus_proxy"))
            stack.enter_context(mock.patch.object(sandbox, "require_running_dbus_proxy"))
            captured = {}
            def launch(command, payload, temporary, inherited, **options):
                captured.update(command=command, payload=payload, **options)
                self.assertEqual((Path(temporary)/"resolv.conf").read_text(encoding="utf-8"), sandbox.veth_resolv_conf())
                self.assertNotIn("--share-net", command)
                self.assertNotIn("literal-url", command)
                sandbox.validate_private_procfs(command)
                return 37
            stack.enter_context(mock.patch.object(supervisor, "run_veth_sandbox", autospec=True, side_effect=launch))
            self.assertEqual(sandbox.run_pure_privacy("chromium", []), 37)
            self.assertEqual(captured["payload"], ['/usr/local/libexec/labwc-proxy-session', 'chromium',
                                                   '/usr/bin/chromium', 'literal-url'])
            self.assertEqual(captured["app"], "chromium")
            self.assertTrue(captured['graceful_shutdown'])
            with mock.patch.object(sandbox, 'pure_privacy_argv', return_value=['/usr/bin/qbittorrent']):
                self.assertEqual(sandbox.run_pure_privacy('qbittorrent', []), 37)
            self.assertEqual(captured['app'], 'qbittorrent-privacy')
            self.assertTrue(captured['graceful_shutdown'])
            self.assertEqual(captured['payload'], ['/usr/local/libexec/labwc-proxy-session', 'qbittorrent', '--privacy', '/usr/bin/qbittorrent'])
            readonly = [captured['command'][i+1:i+3] for i, value in enumerate(captured['command']) if value == '--ro-bind']
            for path in ('/etc/labwc/3proxy/qbittorrent.conf', '/etc/qbittorrent/qBittorrent.conf.d/20-managed-privacy.conf'):
                self.assertIn([path, path], readonly)

    def test_tor_ram_actions_keep_transport_native_and_filter_all_host_bus_services(self):
        for mode in ('launch', 'intel', 'nvidia', 'pure-privacy'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                root = Path(directory)
                env = {'HOME': '/home/user', 'XDG_RUNTIME_DIR': str(root), 'WAYLAND_DISPLAY': 'wayland-0',
                       'XDG_CONFIG_HOME': '/home/user/.config', 'XDG_CACHE_HOME': '/home/user/.cache',
                       'XDG_DATA_HOME': '/home/user/.local/share', 'XDG_STATE_HOME': '/home/user/.local/state',
                       'TMPDIR': '/home/user/.tmp'}
                stack.enter_context(mock.patch.object(sandbox, 'pure_privacy_environment', return_value=env))
                stack.enter_context(mock.patch.object(sandbox, 'pure_privacy_argv',
                    return_value=['/usr/local/libexec/tor-browser-run', '--anon']))
                stack.enter_context(mock.patch.object(sandbox, 'build_argv',
                    return_value=['/usr/local/libexec/tor-browser-run']))
                stack.enter_context(mock.patch.object(sandbox, 'require_root_owned_executable', return_value='/usr/bin/bwrap'))
                stack.enter_context(mock.patch.object(sandbox, 'bwrap_command', return_value=['/usr/bin/bwrap']))
                stack.enter_context(mock.patch.object(sandbox, 'current_user_runtime_socket', return_value=str(root/'wayland-0')))
                stack.enter_context(mock.patch.object(sandbox, 'current_user_home', return_value=str(root/'host-home')))
                stack.enter_context(mock.patch.object(sandbox, 'add_optional_bind'))
                stack.enter_context(mock.patch.object(sandbox, 'add_runtime_bind'))
                stack.enter_context(mock.patch.object(sandbox, 'add_synthetic_sysfs_masks'))
                gpu = stack.enter_context(mock.patch.object(sandbox, 'add_gpu_device_binds'))
                dbus = stack.enter_context(mock.patch.object(sandbox, 'start_session_bus_proxy'))
                stack.enter_context(mock.patch.dict(os.environ,
                    {'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/fixture/session-bus'}, clear=True))
                validate_bus = stack.enter_context(mock.patch.object(sandbox, 'validate_session_bus_address',
                    return_value='unix:path=/fixture/session-bus'))
                proxy, lifecycle = mock.Mock(), mock.Mock()
                filtered = stack.enter_context(mock.patch.object(sandbox, 'start_filtered_dbus_proxy',
                    return_value=(proxy, '/fixture/filtered-bus', lifecycle)))
                stopped = stack.enter_context(mock.patch.object(sandbox, 'stop_dbus_proxy'))
                stack.enter_context(mock.patch.object(sandbox, 'require_running_dbus_proxy'))
                captured = {}
                def launch(command, payload, temporary, inherited, **options):
                    captured.update(command=command, payload=payload, **options)
                    self.assertEqual((Path(temporary)/'resolv.conf').read_text(), sandbox.TOR_NO_DNS_RESOLV_CONF)
                    self.assertIn(['--tmpfs', '/home/user'], [command[i:i+2] for i in range(len(command)-1)])
                    self.assertIn('--unshare-all', command)
                    self.assertNotIn(str(root/'host-home'), command)
                    self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'], f'unix:path={root}/bus')
                    self.assertIn(['--bind', '/fixture/filtered-bus', str(root/'bus')],
                                  [command[i:i+3] for i in range(len(command)-2)])
                    self.assertNotIn('/fixture/session-bus', command)
                    return 37
                stack.enter_context(mock.patch.object(supervisor, 'run_veth_sandbox', autospec=True, side_effect=launch))
                result = (sandbox.run_pure_privacy('tor-browser', []) if mode == 'pure-privacy'
                          else sandbox.run_tor_ram(mode, []))
                self.assertEqual(result, 37)
                self.assertEqual(captured['app'], 'tor-browser')
                self.assertTrue(captured['graceful_shutdown'])
                self.assertEqual(captured['payload'], ['/usr/local/libexec/tor-browser-run', '--anon']
                                 if mode == 'pure-privacy' else ['/usr/local/libexec/tor-browser-run'])
                dbus.assert_not_called()
                validate_bus.assert_called_once_with('unix:path=/fixture/session-bus')
                self.assertEqual(filtered.call_count, 1)
                self.assertEqual(filtered.call_args.args[1:],
                                 ('session-bus', 'unix:path=/fixture/session-bus', ()))
                stopped.assert_called_once_with(proxy, lifecycle, '/fixture/filtered-bus')
                if mode == 'pure-privacy':
                    gpu.assert_not_called()
                else:
                    gpu.assert_called_once_with(captured['command'], mode)
                self.assertEqual(list(root.iterdir()), [])

    def test_privacy_setup_failures_reclaim_private_files_and_started_proxy(self):
        for fault in ('resolver', 'mount'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                root = Path(directory)
                env = {"HOME": "/home/user", "XDG_RUNTIME_DIR": str(root), "WAYLAND_DISPLAY": "wayland-0"}
                stack.enter_context(mock.patch.object(sandbox, 'pure_privacy_environment', return_value=env))
                stack.enter_context(mock.patch.object(sandbox, 'pure_privacy_argv', return_value=['/usr/bin/chromium']))
                stack.enter_context(mock.patch.object(sandbox, 'require_root_owned_executable', return_value='/usr/bin/bwrap'))
                stack.enter_context(mock.patch.object(sandbox, 'current_user_runtime_socket', return_value=str(root/'wayland-0')))
                proxy = mock.Mock()
                lifecycle = mock.Mock()
                started = stack.enter_context(mock.patch.object(sandbox, 'start_session_bus_proxy', return_value=(proxy, '/proxy', lifecycle)))
                stopped = stack.enter_context(mock.patch.object(sandbox, 'stop_dbus_proxy'))
                if fault == 'resolver':
                    stack.enter_context(mock.patch.object(sandbox, 'veth_resolv_conf', side_effect=ValueError('resolver failed')))
                else:
                    stack.enter_context(mock.patch.object(sandbox, 'add_dir_chain', side_effect=ValueError('mount failed')))
                with self.assertRaisesRegex(ValueError, fault + ' failed'):
                    sandbox.run_pure_privacy('chromium', [])
                self.assertEqual(list(root.iterdir()), [])
                if fault == 'resolver':
                    started.assert_not_called()
                    stopped.assert_not_called()
                else:
                    stopped.assert_called_once_with(proxy, lifecycle, '/proxy')

    def test_persistent_resolver_failure_reclaims_private_setup_directory(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            home, runtime = root/'home', root/'runtime'
            home.mkdir(); runtime.mkdir(mode=0o700)
            env = {"HOME": str(home), "XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wayland-0"}
            stack.enter_context(mock.patch.object(sandbox, 'build_environment', return_value=env))
            stack.enter_context(mock.patch.object(sandbox, 'require_root_owned_executable', return_value='/usr/bin/bwrap'))
            stack.enter_context(mock.patch.object(sandbox, 'current_user_runtime_socket', return_value=str(runtime/'wayland-0')))
            stack.enter_context(mock.patch.object(sandbox, 'create_veth_resolver_file', side_effect=ValueError('resolver failed')))
            with self.assertRaisesRegex(ValueError, 'resolver failed'):
                sandbox.run_persistent_sandbox('chromium', 'launch', [])
            self.assertFalse(list(runtime.glob('labwc-chromium-sandbox-*')))

    def test_offline_privacy_never_requests_a_network_lease(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            env = {"HOME": "/home/user", "XDG_RUNTIME_DIR": str(root), "WAYLAND_DISPLAY": "wayland-0",
                   "XDG_CONFIG_HOME": "/home/user/.config", "XDG_CACHE_HOME": "/home/user/.cache",
                   "XDG_DATA_HOME": "/home/user/.local/share", "XDG_STATE_HOME": "/home/user/.local/state",
                   "TMPDIR": "/home/user/.tmp"}
            stack.enter_context(mock.patch.object(sandbox, "pure_privacy_environment", return_value=env))
            stack.enter_context(mock.patch.object(sandbox, "pure_privacy_argv", return_value=["/usr/bin/keepassxc"]))
            stack.enter_context(mock.patch.object(sandbox, "require_root_owned_executable", return_value="/usr/bin/bwrap"))
            stack.enter_context(mock.patch.object(sandbox, "current_user_runtime_socket", return_value=str(root/"wayland-0")))
            stack.enter_context(mock.patch.object(sandbox, "current_user_home", return_value=str(root)))
            stack.enter_context(mock.patch.object(sandbox, "start_session_bus_proxy", return_value=(None, None, None)))
            stack.enter_context(mock.patch.object(sandbox, "stop_dbus_proxy"))
            stack.enter_context(mock.patch.object(sandbox, "require_running_dbus_proxy"))
            def launch(command, payload, temporary, inherited, **options):
                self.assertNotIn("--share-net", command)
                self.assertEqual(payload, ["/usr/bin/keepassxc"])
                self.assertFalse(options["network"])
                resolver = command[command.index("/etc/resolv.conf")-1]
                self.assertEqual(Path(resolver).read_text(encoding="utf-8"), "# Networking is disabled.\n")
                sandbox.validate_private_procfs(command)
                return 37
            stack.enter_context(mock.patch.object(sandbox, "run_veth_sandbox", side_effect=launch))
            self.assertEqual(sandbox.run_pure_privacy("keepassxc", []), 37)


class PodmanAdapterTests(unittest.TestCase):
    def test_shared_ready_exit_descriptor_is_rejected_before_namespace_access(self):
        with mock.patch.object(podman_adapter.os, 'open') as opened, self.assertRaisesRegex(ValueError, 'distinct'):
            podman_adapter.main(['-c', '-r', '3', '-e', '3', '--netns-type=path', '/dev/null', 'tap0'])
        opened.assert_not_called()

    def test_version_probe_is_side_effect_free_before_any_namespace_import(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, \
                mock.patch.object(podman_adapter.os, "open") as opened, \
                mock.patch.object(podman_adapter, "network_lease_type") as constructor:
            self.assertEqual(podman_adapter.main(["--version"]), 0)
        self.assertEqual(output.getvalue(), "app-veth-podman version 1.0.0\n")
        opened.assert_not_called()
        constructor.assert_not_called()

    def test_ready_and_exit_fds_follow_the_configured_bridge_helper_lifecycle(self):
        ready_read, ready_write = os.pipe()
        exit_read, exit_write = os.pipe()
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        lease = mock.Mock(socket=left)
        lease.retry_timeout.return_value = None
        lease.close.side_effect = left.close
        os.write(exit_write, b"stop")
        try:
            with mock.patch.object(podman_adapter, "Lease") as constructor:
                constructor.for_namespace.return_value = lease
                status = podman_adapter.main(["-c", "-r", str(ready_write), "-e", str(exit_read),
                                              "--netns-type=path", "--disable-host-loopback", "--mtu=65520",
                                              "/dev/null", "tap0"])
                self.assertEqual(constructor.for_namespace.call_args.args[1], "podman")
            self.assertEqual(status, 0)
            self.assertEqual(os.read(ready_read, 2), b"1")
            lease.check.assert_called_once()
            lease.close.assert_called_once()
            for descriptor in (ready_write, exit_read):
                with self.assertRaises(OSError):
                    os.fstat(descriptor)
        finally:
            os.close(ready_read); os.close(exit_write)
            left.close(); right.close()

    def test_unsupported_routing_is_rejected_before_namespace_access(self):
        for option in ("--enable-ipv6", "--outbound-addr=192.0.2.8", "--api-socket=/tmp/api.sock", "--cidr=10.0.2.0/24"):
            with self.subTest(option=option), mock.patch.object(podman_adapter.os, "open") as opened, self.assertRaises(ValueError):
                podman_adapter.main(["-c", "-r", "3", "--netns-type=path", option, "/run/podman-devops/netns", "tap0"])
            opened.assert_not_called()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(podman_adapter.main(["--help"]), 0)
        self.assertNotIn("--enable-ipv6", output.getvalue())


class KernelFixtureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("unshare") and shutil.which("ip"), "native iproute2 tools unavailable")
    def test_native_gateway_rejects_down_guest_and_accepts_up_guest_with_host_peer_down(self):
        commands = []
        def command(argv, **options):
            commands.append((argv, options))
            return '[{"ifname":"lo"}]' if argv[-3:] == ['-j', 'link', 'show'] else ''
        with mock.patch.object(broker, 'run', side_effect=command), \
                mock.patch.object(broker, 'route', return_value=('eth0', '192.0.2.1', 1500)), \
                mock.patch.object(broker, 'nft'), mock.patch.object(broker, 'event'):
            endpoints = types.SimpleNamespace(ids={0: 'fixture'}, host_fd=70)
            network = broker.Network(0, 70, 'codex', 1000, DEFAULT_POLICIES['codex'],
                                     ipaddress.IPv4Network('10.203.0.0/24'), endpoints)
            network.close()
        batch = next(options['data'] for argv, options in commands if '--' in argv and argv[-2:] == ['-batch', '-'])
        script = '''import json,subprocess,sys
def ip(*args,data=None):
    return subprocess.run(["/usr/sbin/ip",*args],input=data,capture_output=True,text=True,encoding="utf-8",timeout=3)
for args in (("link","add","eth0","type","veth","peer","name","host0"),
             ("addr","add","10.203.0.2/30","dev","eth0")):
    result=ip(*args);assert result.returncode==0,result.stderr
bad=ip("-batch","-",data="route add default via 10.203.0.1 dev eth0\\nlink set eth0 up\\n")
assert bad.returncode!=0 and "invalid gateway" in bad.stderr,bad.stderr
assert "UP" not in json.loads(ip("-j","link","show","dev","eth0").stdout)[0]["flags"]
result=ip("addr","del","10.203.0.2/30","dev","eth0");assert result.returncode==0,result.stderr
good=ip("-batch","-",data=sys.stdin.read())
assert good.returncode==0,good.stderr
assert "UP" not in json.loads(ip("-j","link","show","dev","host0").stdout)[0]["flags"]
assert json.loads(ip("-j","route","show","default").stdout)[0]["gateway"]=="10.203.0.1"
'''
        result = subprocess.run(["/usr/bin/unshare", "-Urn", sys.executable, "-I", "-B", "-c", script],
                                input=batch, capture_output=True, text=True, encoding="utf-8", timeout=10)
        if result.returncode and result.stderr.startswith("unshare: unshare failed: Operation not permitted"):
            self.skipTest("unprivileged kernel namespaces are unavailable")
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("unshare") and shutil.which("ip"), "native iproute2 tools unavailable")
    def test_native_boot_batch_precreates_fixed_down_pairs_and_recovers_without_recreation(self):
        # Native link creation/recovery run in a fresh user/net namespace.
        # Sysctl policy is verified separately: this check does not write it.
        commands = []
        with mock.patch.object(broker, "run", side_effect=lambda argv, **options: commands.append((argv, options))), \
                mock.patch.object(broker, "event"):
            endpoints = broker.EndpointPool(ipaddress.IPv4Network("10.203.0.0/24"))
            batch = next(options["data"] for argv, options in commands if argv == ["/usr/sbin/ip", "-batch", "-"])
            identities = dict(endpoints.ids)
            endpoints.close()
        script = '''import ipaddress,json,subprocess,sys
sys.path.insert(0,sys.argv[2])
fixture=json.load(sys.stdin)
def ip(*args, data=None):
    result=subprocess.run(["/usr/sbin/ip",*args],input=data,capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stderr
    return result.stdout
ip("-batch","-",data=fixture["batch"])
links={row["ifname"]:row for row in json.loads(ip("-j","-d","link","show"))}
addresses={row["ifname"]:row for row in json.loads(ip("-j","-4","addr","show"))}
assert len(links) == len(fixture["ids"])*2+1
for slot in range(len(fixture["ids"])):
    for name in (f"veth{slot}-app",f"veth{slot}-peer"):
        assert links[name]["linkinfo"]["info_kind"] == "veth"
        assert "UP" not in links[name]["flags"]
    name=f"veth{slot}-app"
    assert links[name]["ifalias"] == "app-veth:"+fixture["ids"][str(slot)]
    addr=addresses[name]["addr_info"]
    assert len(addr) == 1 and addr[0]["prefixlen"] == 30
    assert addr[0]["local"] == str(ipaddress.IPv4Address(int(ipaddress.IPv4Address("10.203.0.0"))+slot*4+1))
for slot in (0,1,31):
    name=f"veth{slot}-app"
    ip("link","set","dev",name,"mtu","1420","up")
    current=json.loads(ip("-j","link","show","dev",name))[0]
    assert current["ifindex"] == links[name]["ifindex"] and current["ifname"] == name
    assert current["ifalias"] == "app-veth:"+fixture["ids"][str(slot)]
    assert "UP" in current["flags"] and current["mtu"] == 1420
    ip("link","set","dev",name,"down")
import runpy
module=runpy.run_path(sys.argv[1])
module["apply_network_identity"].__globals__["read_ruleset_template"]=lambda:fixture["ruleset"]
module["apply_network_identity"](fixture["network"])
recovery=module["recover_endpoints"]
recovery()
assert [row["ifname"] for row in json.loads(ip("-j","link","show"))] == ["lo"]
ip("link","add","name","veth0-app","type","veth","peer","name","veth0-peer")
recovery()
assert [row["ifname"] for row in json.loads(ip("-j","link","show"))] == ["lo"]
print("native boot pool: fixed pairs DOWN, gateway addresses, stable names/indexes and recovery passed")
'''
        result = subprocess.run(["/usr/bin/unshare", "-Urn", sys.executable, "-I", "-B", "-c", script, broker.__file__, str(LIBRARY)],
                                input=json.dumps({"batch": batch, "ids": identities, "network": DEFAULT_CONFIGURATION["network"], "ruleset": broker.read_ruleset_template()}), capture_output=True,
                                text=True, encoding="utf-8", timeout=20)
        if result.returncode and result.stderr.startswith("unshare: unshare failed: Operation not permitted"):
            self.skipTest("unprivileged kernel namespaces are unavailable")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fixed pairs DOWN", result.stdout)

    @unittest.skipUnless(shutil.which("bwrap") and hasattr(os, "pidfd_open"), "native Bubblewrap or pidfds unavailable")
    def test_real_blocked_bubblewrap_init_can_be_inspected_and_pinned_by_its_creator(self):
        # This exercises Linux namespace ownership and real pidfds. It does
        # not load or prove enforcement of the repository's AppArmor policy.
        info_read, info_write = os.pipe()
        block_read, block_write = os.pipe()
        process = None
        pidfd = None
        try:
            process = subprocess.Popen([shutil.which("bwrap"), "--unshare-user", "--unshare-pid", "--unshare-net",
                "--tmpfs", "/", "--ro-bind", "/usr", "/usr",
                "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
                "--symlink", "usr/lib64", "/lib64", "--proc", "/proc",
                "--dev", "/dev", "--cap-drop", "ALL", "--info-fd", str(info_write),
                "--block-fd", str(block_read), "/usr/bin/true"],
                pass_fds=(info_write, block_read), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            os.close(info_write); info_write = None
            os.close(block_read); block_read = None
            pid = supervisor._read_bwrap_sandbox_pid(info_read, process)
            pidfd = client.pin_sandbox_init(pid)
            namespace_fd = os.open(f"/proc/{pid}/ns/net", os.O_RDONLY | os.O_CLOEXEC)
            try:
                broker.namespace_owner(namespace_fd, os.getuid())
            finally:
                os.close(namespace_fd)
            self.assertIsNone(process.poll())
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            process.wait(timeout=5)
        finally:
            if pidfd is not None:
                try:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.close(pidfd)
            for fd in (info_read, info_write, block_read, block_write):
                if fd is not None:
                    os.close(fd)
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                process.stderr.close()

    @unittest.skipUnless(shutil.which('bwrap') and hasattr(os, 'pidfd_open'), 'native Bubblewrap or pidfds unavailable')
    def test_real_bubblewrap_monitor_survives_group_stop_until_the_payload_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'payload.py'
            payload.write_text('''import signal, sys, time
from pathlib import Path
root = Path(sys.argv[1])
def stopped(signum, frame):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    time.sleep(0.1)
    (root / 'closed').write_text('graceful')
    raise SystemExit(0)
signal.signal(signal.SIGINT, stopped)
(root / 'ready').write_text('ready')
time.sleep(30)
''', encoding='utf-8')
            worker = '''import subprocess, sys
from pathlib import Path
library, directory, bwrap = sys.argv[1:]
sys.path.insert(0, library)
from labwc_managed_app import network_namespace as supervisor
root = Path(directory)
native_pin = supervisor.pin_sandbox_init
native_popen = subprocess.Popen
def pin(pid):
    descriptor = native_pin(pid)
    (root / 'init.pid').write_text(str(pid))
    return descriptor
def launch(*args, **options):
    process = native_popen(*args, **options)
    (root / 'monitor.pid').write_text(str(process.pid))
    return process
supervisor.pin_sandbox_init = pin
supervisor.subprocess.Popen = launch
command = [bwrap, '--unshare-user', '--unshare-pid', '--unshare-net', '--new-session',
           '--die-with-parent', '--tmpfs', '/', '--ro-bind', '/usr', '/usr',
           '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
           '--symlink', 'usr/lib64', '/lib64', '--ro-bind', library, library,
           '--bind', directory, directory, '--proc', '/proc', '--dev', '/dev',
           '--cap-drop', 'ALL']
raise SystemExit(supervisor.run_veth_sandbox(command,
    [sys.executable, '-I', '-B', str(root / 'payload.py'), directory], directory, (),
    app='qbittorrent', network=False, graceful_shutdown=True))
'''
            process = subprocess.Popen([sys.executable, '-I', '-B', '-c', worker,
                str(LIBRARY), directory, shutil.which('bwrap')], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
            payload_pidfd = monitor_pidfd = None
            try:
                deadline = time.monotonic() + 5
                while not (root / 'ready').exists():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        self.fail('private Bubblewrap fixture did not become ready')
                    time.sleep(0.01)
                init_pid = int((root / 'init.pid').read_text(encoding='utf-8'))
                children = Path(f'/proc/{init_pid}/task/{init_pid}/children').read_text(encoding='ascii').split()
                self.assertEqual(len(children), 1)
                payload_pidfd = os.pidfd_open(int(children[0]))
                monitor_pidfd = os.pidfd_open(int((root / 'monitor.pid').read_text(encoding='utf-8')))
                # Model systemd's control-group SIGINT: the monitor and payload
                # are in different process groups because of --new-session.
                signal.pidfd_send_signal(monitor_pidfd, signal.SIGINT)
                signal.pidfd_send_signal(payload_pidfd, signal.SIGINT)
                process.send_signal(signal.SIGINT)
                _, errors = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 130, errors.decode('utf-8'))
                self.assertTrue((root / 'closed').is_file(), 'Bubblewrap ended the payload before graceful close')
                self.assertEqual((root / 'closed').read_text(encoding='utf-8'), 'graceful')
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
                for descriptor in (payload_pidfd, monitor_pidfd):
                    if descriptor is not None:
                        os.close(descriptor)

    @unittest.skipUnless(shutil.which("unshare") and shutil.which("nft"), "native nftables tools unavailable")
    def test_native_nftables_accepts_static_rules_and_all_lease_transactions(self):
        transactions = []
        def command(argv, **options):
            return '[{"ifname":"lo"}]' if argv[-3:] == ["-j", "link", "show"] else ""
        with mock.patch.object(broker, "run", side_effect=command), \
                mock.patch.object(broker, "route", return_value=("wg0", "192.0.2.8", 1420)), \
                mock.patch.object(broker, "nft", side_effect=transactions.append), \
                mock.patch.object(broker, "event"), mock.patch.object(broker.Network, "reserve"):
            endpoints = broker.EndpointPool(ipaddress.IPv4Network("10.203.0.0/24"))
            for app in ("codex", "podman", "qbittorrent", "discord"):
                network = broker.Network(0, 70, app, 1000, DEFAULT_POLICIES[app], ipaddress.IPv4Network("10.203.0.0/24"), endpoints)
                network.close()
            endpoints.close()
        result = subprocess.run(["/usr/bin/unshare", "-Urn", "/usr/sbin/nft", "--check", "-f", "-"],
                                input=broker.RULESET + "".join(transactions), capture_output=True,
                                text=True, encoding="utf-8", timeout=15)
        if result.returncode and result.stderr.startswith("unshare: unshare failed: Operation not permitted"):
            self.skipTest("unprivileged kernel namespaces are unavailable")
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(all(shutil.which(tool) for tool in ("unshare", "ip", "nft", "nsenter", "conntrack")), "kernel networking tools unavailable")
    def test_real_veth_dns_and_host_isolation_inside_unprivileged_namespaces(self):
        # All links, sysctls and nft state belong to this new user/network
        # namespace. The host network is never entered or modified. A local
        # UDP echo endpoint stands in for resolved; this verifies packet/NAT
        # plumbing, not resolved's DNS processing or any Internet access.
        script = '''import importlib.machinery, importlib.util, ipaddress, json, os, select, socket, subprocess, sys, threading
sys.path.insert(0,sys.argv[2])
policies=json.loads(sys.argv[3])
loader=importlib.machinery.SourceFileLoader("fixture_broker",sys.argv[1])
spec=importlib.util.spec_from_loader(loader.name,loader)
b=importlib.util.module_from_spec(spec); loader.exec_module(b)
b.run(["/usr/sbin/ip","link","set","lo","up"])
b.run(["/usr/sbin/sysctl","-q","-w","net.ipv4.ip_forward=1"])
b.run(["/usr/sbin/ip","link","add","dummy0","type","dummy"])
b.run(["/usr/sbin/ip","addr","add","192.0.2.1/24","dev","dummy0"])
b.run(["/usr/sbin/ip","link","set","dummy0","up"])
b.route=lambda **options:("dummy0","192.0.2.1",1500)
b.read_ruleset_template=lambda:sys.argv[4]
b.apply_network_identity(json.loads(sys.argv[5]))
b.nft(b.RULESET)
endpoints=b.EndpointPool(ipaddress.IPv4Network("10.203.0.0/24"))
child=subprocess.Popen(["/usr/bin/unshare","-n","/usr/bin/sleep","30"])
fd=None; network=None; remote=None; remote_fd=None
try:
    import time
    for attempt in range(100):
        time.sleep(.01)
        fd=os.open(f"/proc/{child.pid}/ns/net",os.O_RDONLY)
        if os.fstat(fd).st_ino != os.stat("/proc/self/ns/net").st_ino: break
        os.close(fd);fd=None
    assert fd is not None
    network=b.Network(0,fd,"chromium",os.getuid(),policies["chromium"],ipaddress.IPv4Network("10.203.0.0/24"),endpoints)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as dns:
        dns.bind(("127.0.0.1",53053));dns.settimeout(5)
        def answer():
            data,peer=dns.recvfrom(1024);dns.sendto(data,peer)
        thread=threading.Thread(target=answer);thread.start()
        query="import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(3);s.sendto(b'fixture',('10.0.2.3',53));assert s.recv(1024)==b'fixture'"
        b.run(["/usr/bin/nsenter",f"--net=/proc/self/fd/{fd}","--",sys.executable,"-I","-B","-c",query],fds=(fd,))
        thread.join(timeout=5);assert not thread.is_alive()
    blocked="import socket;s=socket.socket();s.settimeout(.2);assert s.connect_ex(('10.203.0.1',53053)) != 0"
    b.run(["/usr/bin/nsenter",f"--net=/proc/self/fd/{fd}","--",sys.executable,"-I","-B","-c",blocked],fds=(fd,))
    network.close();network=None
    # Model an Internet peer behind an isolated routed uplink. The peer's
    # public test address is outside the LAN blocklist; no real network exists.
    remote=subprocess.Popen(["/usr/bin/unshare","-n","/usr/bin/sleep","30"])
    for attempt in range(100):
        time.sleep(.01)
        remote_fd=os.open(f"/proc/{remote.pid}/ns/net",os.O_RDONLY)
        if os.fstat(remote_fd).st_ino != os.stat("/proc/self/ns/net").st_ino: break
        os.close(remote_fd);remote_fd=None
    assert remote_fd is not None
    b.run(["/usr/sbin/ip","link","del","dummy0"])
    b.run(["/usr/sbin/ip","link","add","dummy0","type","veth","peer","name","wanpeer"])
    b.run(["/usr/sbin/ip","link","set","wanpeer","netns",f"/proc/self/fd/{remote_fd}"],fds=(remote_fd,))
    b.run(["/usr/sbin/ip","-batch","-"],data="addr add 192.0.2.1/24 dev dummy0\\nlink set dummy0 up\\nroute add 203.0.113.2/32 via 192.0.2.2 dev dummy0\\n")
    b.run(["/usr/bin/nsenter",f"--net=/proc/self/fd/{remote_fd}","--","/usr/sbin/ip","-batch","-"],
          data="link set lo up\\naddr add 203.0.113.2/32 dev lo\\naddr add 192.0.2.2/24 dev wanpeer\\nlink set wanpeer up\\nroute add default via 192.0.2.1 dev wanpeer\\n",fds=(remote_fd,))
    b.refresh_lan_networks(None)
    # A second forward hook defaults to drop, as the installed base policy does.
    b.nft('table inet fixture_base { chain forward { type filter hook forward priority 0; policy drop; '
          'iifname '+b.INTERFACE_MATCH+' accept; oifname '+b.INTERFACE_MATCH+' accept; } }')
    network=b.Network(0,fd,"qbittorrent",os.getuid(),policies["qbittorrent"],ipaddress.IPv4Network("10.203.0.0/24"),endpoints)
    port=policies["qbittorrent"]["peer_port"]
    server_code="""import socket,sys
kind=int(sys.argv[1]); address=sys.argv[2]; port=int(sys.argv[3]); expected=sys.argv[4]
with socket.socket(socket.AF_INET,kind) as listener:
    listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    listener.settimeout(4); listener.bind((address,port))
    if kind==socket.SOCK_STREAM: listener.listen(1)
    print('ready',flush=True)
    if kind==socket.SOCK_DGRAM:
        data,peer=listener.recvfrom(2048)
        assert peer[0]==expected
        if expected=='192.0.2.1': assert peer[1]==int(sys.argv[5])
        listener.sendto(data,peer)
    else:
        connection,peer=listener.accept()
        with connection:
            connection.settimeout(4); assert peer[0]==expected
            if expected=='192.0.2.1': assert peer[1]==int(sys.argv[5])
            received=b''
            while len(received)<131072:
                part=connection.recv(65536); assert part; received+=part
            connection.sendall(received)
"""
    client_code="""import socket,sys
kind=int(sys.argv[1]); address=sys.argv[2]; port=int(sys.argv[3]); source=sys.argv[4]; source_port=int(sys.argv[5])
payload=b'p'*(1024 if kind==socket.SOCK_DGRAM else 131072)
with socket.socket(socket.AF_INET,kind) as connection:
    connection.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    connection.settimeout(4); connection.bind((source,source_port)); connection.connect((address,port))
    connection.sendall(payload); received=b''
    while len(received)<len(payload):
        part=connection.recv(65536); assert part; received+=part
    assert received==payload
"""
    def exchange(server_fd,client_fd,kind,server_address,destination,listen_port,source,source_port,expected):
        prefix=["/usr/bin/nsenter",f"--net=/proc/self/fd/{server_fd}","--",sys.executable,"-I","-B","-c"]
        server=subprocess.Popen([*prefix,server_code,str(kind),server_address,str(listen_port),expected,str(port)],
                                pass_fds=(server_fd,),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        try:
            assert select.select([server.stdout],[],[],5)[0], 'peer fixture did not become ready'
            assert server.stdout.readline()=='ready\\n'
            b.run(["/usr/bin/nsenter",f"--net=/proc/self/fd/{client_fd}","--",sys.executable,"-I","-B","-c",
                   client_code,str(kind),destination,str(listen_port),source,str(source_port)],fds=(client_fd,))
            output,error=server.communicate(timeout=5)
            assert server.returncode==0,error
        finally:
            if server.poll() is None: server.kill()
            server.communicate(timeout=5)
    for kind in (socket.SOCK_STREAM,socket.SOCK_DGRAM):
        exchange(remote_fd,fd,kind,'203.0.113.2','203.0.113.2',4242,network.address,port,'192.0.2.1')
        exchange(fd,remote_fd,kind,network.address,'192.0.2.1',port,'203.0.113.2',0,'203.0.113.2')
    b.run(["/usr/bin/nsenter",f"--net=/proc/self/fd/{fd}","--",sys.executable,"-I","-B","-c",blocked],fds=(fd,))
    network.close();network=None
    print("isolated kernel veth UDP DNS NAT, host guard and qBittorrent bidirectional TCP/UDP payloads passed")
finally:
    if network is not None: network.close()
    endpoints.close()
    if fd is not None: os.close(fd)
    if remote_fd is not None: os.close(remote_fd)
    if remote is not None: remote.terminate();remote.wait(timeout=5)
    child.terminate();child.wait(timeout=5)
'''
        result = subprocess.run(["/usr/bin/unshare", "-Urnmpf", "--mount-proc", sys.executable, "-I", "-B", "-c", script, broker.__file__, str(LIBRARY), json.dumps(DEFAULT_POLICIES), broker.RULESET, json.dumps(DEFAULT_CONFIGURATION["network"])],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        if result.returncode and result.stderr.startswith("unshare: unshare failed: Operation not permitted"):
            self.skipTest("unprivileged kernel namespaces are unavailable")
        if result.returncode and 'sysctl: permission denied on key "net.ipv4.ip_forward"' in result.stderr:
            self.skipTest("environment denies sysctl writes even in an isolated user/network namespace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("isolated kernel veth UDP DNS NAT", result.stdout)


class DNSFrontendFixtureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dnsmasq"), "packaged dnsmasq is required for the loopback fixture")
    def test_native_frontend_caches_valid_answers_clears_ad_and_flushes_on_hup(self):
        # Only this private high-port daemon and handcrafted loopback upstream
        # run. No host resolver, service, firewall, route or DNS data changes.
        def wire_name(name):
            return b"".join(bytes([len(label)]) + label.encode("ascii") for label in name.split(".")) + b"\0"

        def response(query, data, *, authenticated=False, failure=False):
            end = 12
            while query[end]:
                end += query[end] + 1
            question = query[12:end + 5]
            kind, dns_class = struct.unpack("!HH", question[-4:])
            flags = (0x8180 | (struct.unpack("!H", query[2:4])[0] & 0x10)
                     | (0x20 if authenticated else 0) | (2 if failure else 0))
            # A short upstream TTL exercises the configured local minimum.
            answer = b"" if failure else b"\xc0\x0c" + struct.pack("!HHIH", kind, dns_class, 5, len(data)) + data
            return query[:2] + struct.pack("!HHHHH", flags, 1, 0 if failure else 1, 0, 0) + question + answer

        def receive_exact(channel, count):
            data = b""
            while len(data) < count:
                part = channel.recv(count - len(data))
                self.assertTrue(part, "fixture TCP stream closed early")
                data += part
            return data

        with tempfile.TemporaryDirectory(prefix="veth-dns-frontend-") as directory, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream, \
                socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_upstream, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
            upstream.bind(("127.0.0.1", 0))
            upstream.settimeout(3)
            upstream_port = upstream.getsockname()[1]
            tcp_upstream.bind(("127.0.0.1", upstream_port))
            tcp_upstream.listen(1)
            tcp_upstream.settimeout(3)
            client_socket.settimeout(3)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            config = Path(directory) / "dnsmasq.conf"
            text = read_text(TARGET / "etc/dnsmasq-app-veth.conf")
            rendered = SystemDNSRenderingTests().mapping()
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            values = dict(line.split("=", 1) for line in rendered.stdout.splitlines())
            for name, value in values.items():
                text = text.replace("__INSTALLER_" + name + "__", value)
            self.assertNotIn("__INSTALLER_", text)
            text = text.replace("port=53053\n", f"port={port}\n").replace(
                "server=127.0.0.1#53054\n", f"server=127.0.0.1#{upstream_port}\n")
            config.write_text(text, encoding="ascii")
            with (Path(directory) / "daemon.log").open("w+", encoding="utf-8") as log:
                process = subprocess.Popen([shutil.which("dnsmasq"), "--keep-in-foreground",
                    "--conf-file=" + str(config), "--pid-file=",
                    "--user=" + pwd.getpwuid(os.getuid()).pw_name,
                    "--group=" + grp.getgrgid(os.getgid()).gr_name], stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        if process.poll() is not None:
                            log.seek(0)
                            self.fail("dnsmasq exited before readiness: " + log.read(2000))
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=.1):
                                break
                        except OSError:
                            if time.monotonic() >= deadline:
                                self.fail("fixture dnsmasq listener did not become ready")
                            time.sleep(.01)
                    # Dnsmasq's own interface discovery opens NETLINK_ROUTE.
                    netlink = Path("/proc/net/netlink").read_text(encoding="ascii")
                    self.assertTrue(any(row.split()[1:3] == ["0", str(process.pid)]
                                        for row in netlink.splitlines()[1:]), netlink)
                    cases = (("host.private", 1, socket.inet_aton("10.1.2.3"), False, False),
                             ("authenticated.private", 1, socket.inet_aton("10.9.8.7"), True, False),
                             ("printer", 1, socket.inet_aton("192.168.1.4"), False, False),
                             ("host.private", 28, socket.inet_pton(socket.AF_INET6, "fd00::123"), False, False),
                             ("3.2.1.10.in-addr.arpa", 12, wire_name("host.private"), False, False),
                             ("text.private", 16, b"\x05hello", True, False),
                             ("bogus.example", 1, b"", False, True))
                    for name, kind, data, authenticated, failure in cases:
                        with self.subTest(name=name, kind=kind, authenticated=authenticated):
                            query = struct.pack("!HHHHHH", 1234, 0x120, 1, 0, 0, 0) + wire_name(name) + struct.pack("!HH", kind, 1)
                            client_socket.sendto(query, ("127.0.0.1", port))
                            forwarded, peer = upstream.recvfrom(4096)
                            upstream.sendto(response(forwarded, data, authenticated=authenticated, failure=failure), peer)
                            # Dnsmasq may retry a SERVFAIL before returning it.
                            # Bound and answer those retries on the same fixture.
                            for attempt in range(4):
                                ready, _, _ = select.select([client_socket, upstream], [], [], 3)
                                self.assertTrue(ready, "fixture DNS response timed out")
                                if client_socket in ready:
                                    reply = client_socket.recv(4096)
                                    break
                                forwarded, peer = upstream.recvfrom(4096)
                                upstream.sendto(response(forwarded, data, authenticated=authenticated, failure=failure), peer)
                            else:
                                self.fail("fixture DNS retry limit reached")
                            flags = struct.unpack("!H", reply[2:4])[0]
                            self.assertEqual(flags & 0xf, 2 if failure else 0)
                            # The cache owns the frontend response; Stubby's
                            # authenticated AD bit is intentionally not
                            # proxied through cached dnsmasq answers.
                            self.assertFalse(flags & 0x20)
                            if data:
                                self.assertTrue(reply.endswith(data), reply)
                            if not failure and kind in (1, 16):
                                client_socket.sendto(query, ("127.0.0.1", port))
                                ready, _, _ = select.select([client_socket, upstream], [], [], 3)
                                self.assertIn(client_socket, ready, "cache hit contacted upstream")
                                self.assertNotIn(upstream, ready, "cache hit contacted upstream")
                                cached = client_socket.recv(4096)
                                self.assertTrue(cached.endswith(data), cached)
                                self.assertFalse(struct.unpack("!H", cached[2:4])[0] & 0x20)
                                end = 12
                                while cached[end]:
                                    end += cached[end] + 1
                                answer_start = end + 5
                                ttl = struct.unpack("!I", cached[answer_start + 6:answer_start + 10])[0]
                                self.assertGreaterEqual(ttl, int(values["SYSTEM_DNS_CACHE_MIN_TTL"]) - 1)
                    # Policy changes require a Stubby restart (which also
                    # restarts this PartOf frontend). SIGHUP is also a native
                    # dnsmasq cache flush, verified here without host services.
                    process.send_signal(signal.SIGHUP)
                    query = struct.pack("!HHHHHH", 1236, 0x120, 1, 0, 0, 0) + wire_name("host.private") + struct.pack("!HH", 1, 1)
                    deadline = time.monotonic() + 3
                    while True:
                        client_socket.sendto(query, ("127.0.0.1", port))
                        ready, _, _ = select.select([client_socket, upstream], [], [], .1)
                        if upstream in ready:
                            forwarded, peer = upstream.recvfrom(4096)
                            updated = socket.inet_aton("10.5.6.7")
                            upstream.sendto(response(forwarded, updated, authenticated=True), peer)
                            break
                        if client_socket in ready:
                            client_socket.recv(4096)
                        self.assertLess(time.monotonic(), deadline, "SIGHUP did not clear cache")
                    reply = client_socket.recv(4096)
                    self.assertTrue(reply.endswith(updated), reply)
                    self.assertFalse(struct.unpack("!H", reply[2:4])[0] & 0x20)
                    # Negative caching uses the upstream SOA's TTL/minimum.
                    # Keep the negative record separate from all positive cases.
                    query = struct.pack("!HHHHHH", 1237, 0x100, 1, 0, 0, 0) + wire_name("absent.example") + struct.pack("!HH", 1, 1)
                    client_socket.sendto(query, ("127.0.0.1", port))
                    forwarded, peer = upstream.recvfrom(4096)
                    end = 12
                    while forwarded[end]:
                        end += forwarded[end] + 1
                    question = forwarded[12:end + 5]
                    soa = wire_name("ns.example") + wire_name("hostmaster.example") + struct.pack("!IIIII", 1, 60, 60, 600, 5)
                    authority = wire_name("example") + struct.pack("!HHIH", 6, 1, 5, len(soa)) + soa
                    negative = forwarded[:2] + struct.pack("!HHHHH", 0x8183, 1, 0, 1, 0) + question + authority
                    upstream.sendto(negative, peer)
                    reply = client_socket.recv(4096)
                    self.assertEqual(struct.unpack("!H", reply[2:4])[0] & 0xf, 3)
                    client_socket.sendto(query, ("127.0.0.1", port))
                    ready, _, _ = select.select([client_socket, upstream], [], [], 3)
                    self.assertIn(client_socket, ready, "negative cache hit contacted upstream")
                    self.assertNotIn(upstream, ready, "negative cache hit contacted upstream")
                    cached = client_socket.recv(4096)
                    self.assertEqual(struct.unpack("!H", cached[2:4])[0] & 0xf, 3)
                    # A client's explicit Checking Disabled request must not
                    # populate the shared cache used by validating clients.
                    question = wire_name("checking-disabled.example") + struct.pack("!HH", 1, 1)
                    query = struct.pack("!HHHHHH", 1238, 0x110, 1, 0, 0, 0) + question
                    client_socket.sendto(query, ("127.0.0.1", port))
                    forwarded, peer = upstream.recvfrom(4096)
                    self.assertTrue(struct.unpack("!H", forwarded[2:4])[0] & 0x10)
                    unchecked = socket.inet_aton("192.0.2.10")
                    upstream.sendto(response(forwarded, unchecked), peer)
                    self.assertTrue(client_socket.recv(4096).endswith(unchecked))
                    query = struct.pack("!HHHHHH", 1239, 0x100, 1, 0, 0, 0) + question
                    client_socket.sendto(query, ("127.0.0.1", port))
                    ready, _, _ = select.select([client_socket, upstream], [], [], 3)
                    self.assertIn(upstream, ready, "checking-disabled answer contaminated the shared cache")
                    self.assertNotIn(client_socket, ready, "validating client received an unchecked cached answer")
                    forwarded, peer = upstream.recvfrom(4096)
                    self.assertFalse(struct.unpack("!H", forwarded[2:4])[0] & 0x10)
                    checked = socket.inet_aton("192.0.2.20")
                    upstream.sendto(response(forwarded, checked), peer)
                    self.assertTrue(client_socket.recv(4096).endswith(checked))
                    # TCP clients must retain the same upstream policy.
                    with socket.create_connection(("127.0.0.1", port), timeout=3) as tcp_client:
                        query = struct.pack("!HHHHHH", 1235, 0x120, 1, 0, 0, 0) + wire_name("tcp.private") + struct.pack("!HH", 1, 1)
                        tcp_client.sendall(struct.pack("!H", len(query)) + query)
                        channel, _ = tcp_upstream.accept()
                        with channel:
                            channel.settimeout(3)
                            forwarded = receive_exact(channel, struct.unpack("!H", receive_exact(channel, 2))[0])
                            answer = response(forwarded, socket.inet_aton("10.2.3.4"), authenticated=True)
                            channel.sendall(struct.pack("!H", len(answer)) + answer)
                        reply = receive_exact(tcp_client, struct.unpack("!H", receive_exact(tcp_client, 2))[0])
                        self.assertTrue(reply.endswith(socket.inet_aton("10.2.3.4")))
                        self.assertFalse(struct.unpack("!H", reply[2:4])[0] & 0x20)
                finally:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


class SystemDNSRenderingTests(unittest.TestCase):
    stubby_binary = shutil.which("stubby")
    root_key = Path("/usr/share/dns/root.key")

    @staticmethod
    def identity_policy():
        # Read the canonical public policy as literal data; tests must not pin
        # production provider addresses or TLS names to their current defaults.
        text = read_text(SEED / "hosts/installer/identity.env")
        return dict(re.findall(r'^SYSTEM_NAMESERVERS_([A-Z0-9_]+)="([^"\n]*)"$', text, re.M))

    def mapping(self, overrides=None, *, cache_overrides=None):
        arguments = [str(SEED / "scripts/late/security.sh"), str(SEED / "hosts/installer/identity.env")]
        if cache_overrides is not None and overrides is None:
            policy = self.identity_policy()
            overrides = tuple(policy[name] for name in ("IPV4_DNS1", "IPV6_DNS1", "HOSTNAME_DNS1",
                              "IPV4_DNS2", "IPV6_DNS2", "HOSTNAME_DNS2", "PORT"))
        if overrides is not None:
            arguments.extend(overrides)
        if cache_overrides is not None:
            arguments.extend(cache_overrides)
        code = '''
. "$2"
if [ "$#" -ge 9 ]; then
  SYSTEM_NAMESERVERS_IPV4_DNS1=$3
  SYSTEM_NAMESERVERS_IPV6_DNS1=$4
  SYSTEM_NAMESERVERS_HOSTNAME_DNS1=$5
  SYSTEM_NAMESERVERS_IPV4_DNS2=$6
  SYSTEM_NAMESERVERS_IPV6_DNS2=$7
  SYSTEM_NAMESERVERS_HOSTNAME_DNS2=$8
  SYSTEM_NAMESERVERS_PORT=$9
fi
if [ "$#" -eq 11 ]; then
  SYSTEM_DNS_CACHE_SIZE=${10}
  SYSTEM_DNS_CACHE_MIN_TTL=${11}
fi
. "$1"
identity_root=${2%/hosts/installer/identity.env}
. "$identity_root/scripts/common/modules/app-veth-identity.sh"
app_veth_dns_placeholder_map
'''
        return subprocess.run(["/bin/sh", "-eu", "-c", code, "dns-fixture", *arguments],
                              capture_output=True, text=True, encoding="utf-8", timeout=5)

    def test_default_upstreams_and_firewall_follow_the_canonical_identity_policy(self):
        result = self.mapping()
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines())
        policy = self.identity_policy()
        for family in (4, 6):
            addresses = [policy[f"IPV{family}_DNS{i}"] for i in (1, 2) if policy[f"IPV{family}_DNS{i}"]]
            self.assertEqual(json.loads(values[f"SYSTEM_NAMESERVERS_IPV{family}_ALLOWLIST"]), addresses)
        upstreams = values["SYSTEM_NAMESERVERS_UPSTREAMS"]
        endpoints = [(policy[f"IPV{family}_DNS{i}"], policy[f"HOSTNAME_DNS{i}"])
                     for i in (1, 2) for family in (4, 6) if policy[f"IPV{family}_DNS{i}"]]
        self.assertEqual(upstreams.count("address_data:"), len(endpoints))
        previous = -1
        for address, name in endpoints:
            self.assertIn('{address_data: "' + address + '", tls_auth_name: "' + name + '", tls_port: ' + str(int(policy["PORT"])) + '}', upstreams)
            position = upstreams.index('address_data: "' + address + '"')
            self.assertGreater(position, previous)
            previous = position
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mapping = root / "map"
            mapping.write_text(result.stdout, encoding="ascii")
            for source, name in ((TARGET / "etc/stubby/stubby.yml.tmpl", "stubby.yml"),
                                 (TARGET / "etc/dnsmasq-app-veth.conf.tmpl", "dnsmasq.conf"),
                                 (TARGET / "etc/systemd/resolved.conf.d/60-app-veth.conf.tmpl", "resolved.conf"),
                                 (TARGET / "etc/nftables/services/dns-client.yml.tmpl", "dns-client.yml")):
                destination = root / name
                destination.write_text(read_text(source), encoding="ascii")
                rendered = subprocess.run(["/bin/sh", "-eu", "-c",
                    '. "$1"; . "$2"; . "$3"; . "$4"; identity_root=${4%/hosts/installer/identity.env}; . "$identity_root/scripts/common/modules/app-veth-identity.sh"; TMP_ENV_DIR=$6; '
                    'apply_placeholder_map_to_target "$5" app_veth_dns_placeholder_map', "render-fixture",
                    str(SEED / "scripts/common/modules/files-logging.sh"),
                    str(SEED / "scripts/late/target-assets.sh"), str(SEED / "scripts/late/security.sh"),
                    str(SEED / "hosts/installer/identity.env"), str(destination), str(root)],
                    capture_output=True, text=True, encoding="utf-8", timeout=5)
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                text = destination.read_text(encoding="ascii")
                self.assertNotIn("__INSTALLER_", text)

    def test_cache_policy_is_bounded_and_rejects_injection_without_partial_output(self):
        result = self.mapping(cache_overrides=("10000", "60"))
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines())
        self.assertEqual(values["SYSTEM_DNS_CACHE_SIZE"], "10000")
        self.assertEqual(values["SYSTEM_DNS_CACHE_MIN_TTL"], "60")
        for size, ttl in (("0", "60"), ("1000001", "60"), ("-1", "60"),
                          ("10000\nINJECT=yes", "60"), ("10000", "3601"),
                          ("10000", "-1"), ("10000", "$(id)"), ("10000", "")):
            with self.subTest(size=size, ttl=ttl):
                result = self.mapping(cache_overrides=(size, ttl))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("fatal: invalid SYSTEM_DNS_CACHE", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_native_stubby_loads_dnssec_anchors_instead_of_accepting_an_empty_list(self):
        if not self.stubby_binary or not self.root_key.is_file():
            self.skipTest("packaged Stubby and dns-root-data are required for native anchor validation")
        result = self.mapping()
        self.assertEqual(result.returncode, 0, result.stderr)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines())
        with tempfile.TemporaryDirectory(prefix="stubby-anchor-fixture-") as directory:
            root = Path(directory)
            cache = root / "cache"
            cache.mkdir(mode=0o700)
            text = read_text(TARGET / "etc/stubby/stubby.yml.tmpl")
            text = text.replace("__INSTALLER_SYSTEM_NAMESERVERS_UPSTREAMS__", values["SYSTEM_NAMESERVERS_UPSTREAMS"])
            text = text.replace("__INSTALLER_SYSTEM_DNS_UPSTREAM_TLS_CA_FILE__", values["SYSTEM_DNS_UPSTREAM_TLS_CA_FILE"])
            text = text.replace("/usr/share/dns/root.key", str(self.root_key)).replace("/var/cache/stubby", str(cache))
            config = root / "stubby.yml"
            config.write_text(text, encoding="utf-8")
            result = subprocess.run([self.stubby_binary, "-i", "-C", str(config)],
                capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            anchors = re.search(r'"dnssec_trust_anchors":\s*(\[.*?\])', result.stdout, re.S)
            self.assertIsNotNone(anchors, "native context did not report DNSSEC trust anchors")
            self.assertIn('"type": GETDNS_RRTYPE_DNSKEY', anchors[1], "native context loaded no DNSKEY trust anchors")
            self.assertIn("GETDNS_AUTHENTICATION_REQUIRED", result.stdout)
            self.assertIn("GETDNS_TRANSPORT_TLS", result.stdout)
            self.assertRegex(result.stdout, r'"round_robin_upstreams":\s*0\b')
            previous = -1
            for address in re.findall(r'address_data: "([^"]+)"', values["SYSTEM_NAMESERVERS_UPSTREAMS"]):
                position = result.stdout.index("<bindata for " + str(ipaddress.ip_address(address)) + ">")
                self.assertGreater(position, previous, "native upstream ordering changed")
                previous = position

    def test_optional_dns2_independent_address_families_and_custom_port(self):
        for overrides, expected in ((("192.0.2.53", "", "dns.example", "", "", "", "443"), 1),
            (("", "2001:db8::53", "dns.example", "", "", "", "853"), 1),
            (("192.0.2.53", "2001:db8::53", "dns.example", "", "", "", "853"), 2),
            (("192.0.2.53", "", "one.example", "", "2001:db8::54", "two.example", "8853"), 2),
            (("", "2001:db8::53", "one.example", "192.0.2.54", "", "two.example", "853"), 2)):
            with self.subTest(overrides=overrides):
                result = self.mapping(overrides)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.count("address_data:"), expected)
                self.assertIn("tls_port: " + overrides[6], result.stdout)
                if not any(overrides[3:6]):
                    self.assertEqual(result.stdout.count("tls_auth_name:"), expected)

    def test_malformed_policy_is_rejected_without_partial_output(self):
        valid = ["192.0.2.53", "2001:db8::53", "dns.example", "192.0.2.54", "2001:db8::54", "dns2.example", "853"]
        for index, invalid in ((0, "999.2.3.4"), (0, "192.0.2.1 192.0.2.2"),
                               (0, "01.2.3.4"), (1, "2001:::53"), (1, "2001::db8::53"),
                               (1, "12345::53"), (1, "2001:db8:1:2:3:4:5:6:7"),
                               (2, "-dns.example"), (2, "dns-.example"), (2, "dns..example"),
                               (2, "x" * 64 + ".example"), (2, "dns.example\nINJECT=yes"),
                               (2, "$(id)"), (2, ""), (3, "999.2.3.4"), (4, "2001:::54"),
                               (5, ""), (5, "dns2.example dns3.example"),
                               (6, "0"), (6, "65536"), (6, "853;id")):
            with self.subTest(index=index, invalid=invalid):
                policy = valid.copy()
                policy[index] = invalid
                result = self.mapping(policy)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("fatal: invalid SYSTEM_NAMESERVERS", result.stderr)
                self.assertEqual(result.stdout, "")
        for policy in (("", "", "dns.example", "", "", "", "853"),
                       ("", "", "", "192.0.2.54", "", "dns2.example", "853"),
                       ("192.0.2.53", "", "dns.example", "", "", "dns2.example", "853"),
                       ("192.0.2.53", "", "dns.example", "192.0.2.54", "", "", "853")):
            with self.subTest(policy=policy):
                result = self.mapping(policy)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_new_identity_variables_keep_target_network_on_global_dns(self):
        code = '''
. "$1"
. "$2"
if [ "$3" = single ]; then
  SYSTEM_NAMESERVERS_IPV4_DNS2=
  SYSTEM_NAMESERVERS_IPV6_DNS2=
  SYSTEM_NAMESERVERS_HOSTNAME_DNS2=
fi
network_mode=static
target_managed_network_state_target_path() { printf /etc/network/host.conf; }
target_host_variant_class() { printf btrfs-de; }
write_shell_config_var() { printf "%s=%s\\n" "$1" "$2"; }
network_input_placeholder_map
'''
        for mode in ("dual", "single"):
            result = subprocess.run(["/bin/sh", "-e", "-c", code, "network-dns-fixture",
                str(SEED / "scripts/late/network.sh"), str(SEED / "hosts/installer/identity.env"), mode],
                capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MANAGED_NETWORK_DNS_MODE=global\n", result.stdout)

    def test_dns_overlay_is_required_and_custom_tls_port_reaches_both_firewall_families(self):
        code = '''
. "$1"
selected=$2
late_command_nftables_services() { printf "%s\\n" "$selected"; }
installer_selected_class_reference_is_selected() { return 1; }
nftables_tailscale_selected() { return 1; }
nftables_qemu_selected() { return 1; }
nftables_software_selected() { return 1; }
installer_info() { :; }
SSH_SERVER_ENABLED=false
NFS_SERVER_ENABLE=false
NFS_CLIENT_ENABLE=false
late_command_nftables_effective_services
'''
        for selected in ("", "lan-share", "egress", "dns-client"):
            result = subprocess.run(["/bin/sh", "-eu", "-c", code, "dns-overlay-fixture",
                str(SEED / "scripts/late/security.sh"), selected], capture_output=True,
                text=True, encoding="utf-8", timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.split().count("dns-client"), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Use the real YAML merge/renderer; the host nft ruleset is untouched.
            profile = root / "desktop.yml"
            text = read_text(TARGET / "etc/nftables/profiles/desktop.yml")
            text = text.replace("__INSTALLER_MANAGED_NETWORK_ETHERNET_IFACE__", "enp1s0").replace(
                "__INSTALLER_MANAGED_NETWORK_WIFI_IFACE__", "wlan0")
            profile.write_text(text, encoding="utf-8")
            overlay = root / "dns-client.yml"
            overlay.write_text(read_text(TARGET / "etc/nftables/services/dns-client.yml.tmpl").replace(
                "__INSTALLER_SYSTEM_NAMESERVERS_PORT__", "8853").replace(
                "__INSTALLER_SYSTEM_NAMESERVERS_IPV4_ALLOWLIST__", '["192.0.2.53"]').replace(
                "__INSTALLER_SYSTEM_NAMESERVERS_IPV6_ALLOWLIST__", '["2001:db8::53"]'), encoding="ascii")
            result = subprocess.run([sys.executable, "-I", "-B",
                str(TARGET / "usr/local/sbin/nft-policy-generate.py"), "--profile", str(profile),
                "--overlay", str(TARGET / "etc/nftables/services/egress.yml"), "--overlay", str(overlay),
                "--print"], capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            rules = [line for line in result.stdout.splitlines() if "dns_over_tls_client outbound" in line]
            self.assertEqual(len(rules), 2, rules)
            self.assertTrue(any("ip daddr" in line for line in rules), rules)
            self.assertTrue(any("ip6 daddr" in line for line in rules), rules)
            self.assertTrue(all("tcp dport 8853" in line for line in rules), rules)
            self.assertNotIn("udp dport 8853", result.stdout)
            for slot in range(int(network_identity_values()['APP_VETH_MAX_LEASES'])):
                self.assertIn(f'"veth{slot}-app"', result.stdout)
            self.assertNotIn('"veth128-app"', result.stdout)
            self.assertIn('th dport 53053 ct status dnat accept', result.stdout)

    def test_base_firewall_rejects_wildcards_and_unsafe_dns_identity(self):
        nft_policy = runpy.run_path(str(TARGET/'usr/local/sbin/nft-policy-generate.py'))
        valid = {'interfaces': ['veth0-app', 'veth63-app'],
                 'dns_host_address': '127.0.0.2', 'dns_host_port': 54053}
        self.assertEqual(nft_policy['app_veth_identity']({'app_veth': valid}),
                         ('{ "veth0-app", "veth63-app" }', '127.0.0.2', 54053))
        for key, value in (('interfaces', ['veth*']), ('interfaces', ['eth0']),
                           ('interfaces', ['veth0-app', 'veth0-app']),
                           ('dns_host_address', '0.0.0.0'), ('dns_host_port', True),
                           ('dns_host_port', 53)):
            with self.subTest(key=key, value=value), self.assertRaises(nft_policy['PolicyError']):
                nft_policy['app_veth_identity']({'app_veth': {**valid, key: value}})

    def test_installer_nameserver_is_rendered_from_identity_for_every_site(self):
        answers = read_text(SEED / "scripts/preseed/answers.sh")
        read_function = answers[answers.index("read_static_network_answers() {"):
                                answers.index("\nread_wifi_answers() {")]
        write_function = answers[answers.index("write_installer_nameserver_answers() {"):
                                 answers.index("\nwrite_include_list() {")]
        validator = answers[answers.index("validate_ipv4_address() {"):
                            answers.index("\nvalidate_ipv4_address_list() {")]
        code = '''
. "$1"
NETWORK_MODE=$2
if [ "$#" -eq 3 ]; then STATIC_INSTALLER_NAMESERVER=$3; fi
static_network_requested() { [ "$NETWORK_MODE" = static ]; }
installer_fatal() { exit 1; }
answer_value() {
  case "$1" in
    netcfg/get_ipaddress) printf "%s\\n" 192.0.2.20 ;;
    netcfg/get_netmask) printf "%s\\n" 255.255.255.0 ;;
    netcfg/get_gateway) printf "%s\\n" 192.0.2.1 ;;
    netcfg/get_nameservers) printf "%s\\n" 192.0.2.53 ;;
  esac
}
''' + validator + read_function + write_function + "\nread_static_network_answers\nwrite_static_network_answers\nwrite_installer_nameserver_answers\n"
        default = re.search(r'^STATIC_INSTALLER_NAMESERVER="([^"\n]+)"$',
                            read_text(SEED / "hosts/installer/identity.env"), re.M).group(1)
        for mode in ("static", "dhcp"):
            for override in (None, "192.0.2.54"):
                arguments = [str(SEED / "hosts/installer/identity.env"), mode]
                if override:
                    arguments.append(override)
                result = subprocess.run(["/bin/sh", "-eu", "-c", code, "installer-fixture", *arguments],
                                        capture_output=True, text=True, encoding="utf-8", timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("d-i netcfg/get_nameservers string " + (override or default) + "\n", result.stdout)
                self.assertIn("d-i netcfg/get_nameservers seen true", result.stdout)
        for site in ("prod", "lab", "dmz"):
            self.assertNotIn("netcfg/get_nameservers string", read_text(SEED / "classes/class-select/site" / (site + ".cfg")))

    @unittest.skipUnless(shutil.which("perl"), "packaged Perl is required for the network generator fixture")
    def test_target_interfaces_use_global_dns_without_bootstrap_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            sysnet = root / "sysnet"
            interface = sysnet / "enp1s0"
            (interface / "device").mkdir(parents=True)
            for key, value in {"type": "1", "address": "02:00:00:00:00:01", "carrier": "1", "operstate": "up"}.items():
                (interface / key).write_text(value + "\n", encoding="ascii")
            values = {"MANAGED_NETWORK_TARGET_ROOT": str(target), "MANAGED_NETWORK_SYS_CLASS_NET": str(sysnet),
                      "MANAGED_NETWORK_WAIT_SECONDS": "1", "MANAGED_NETWORK_DOMAIN": "example.test",
                      "MANAGED_NETWORK_IPV4_ADDRESS": "192.0.2.20", "MANAGED_NETWORK_IPV4_NETMASK": "255.255.255.0",
                      "MANAGED_NETWORK_IPV4_GATEWAY": "192.0.2.1", "MANAGED_NETWORK_IPV4_DNS": "192.0.2.53",
                      "MANAGED_NETWORK_IPV6_ENABLED": "true", "MANAGED_NETWORK_IPV6_ADDRESS": "2001:db8::20/64",
                      "MANAGED_NETWORK_IPV6_GATEWAY": "2001:db8::1", "MANAGED_NETWORK_IPV6_DNS": "2001:db8::53"}
            for mode in ("link", "global"):
                values["MANAGED_NETWORK_DNS_MODE"] = mode
                config = root / "network-input.env"
                config.write_text("".join(key + "='" + value + "'\n" for key, value in values.items()), encoding="ascii")
                result = subprocess.run([shutil.which("perl"), str(SEED / "scripts/late/network-generate.pl"),
                    "--input", str(config), "--target-templates", str(TARGET),
                    "--fragments", str(SEED / "scripts/late/templates/network")],
                    capture_output=True, text=True, encoding="utf-8", timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                network = (target / "etc/network/interfaces.d/50-network").read_text(encoding="ascii")
                self.assertIn("iface eth0 inet6 static", network)
                self.assertIn("dns-search example.test", network)
                if mode == "global":
                    self.assertNotIn("dns-nameservers", network)
                    self.assertNotIn(values["MANAGED_NETWORK_IPV4_DNS"], network)
                else:
                    self.assertIn("dns-nameservers " + values["MANAGED_NETWORK_IPV4_DNS"], network)
                self.assertIn("MANAGED_NETWORK_DNS_MODE='" + mode + "'", (target / "etc/network/host.conf").read_text(encoding="ascii"))


class InstallationTests(unittest.TestCase):
    def test_descriptor_limit_covers_full_future_pool_with_peer_and_rpc_reservations(self):
        service = read_text(TARGET / 'etc/systemd/system/app-veth.service')
        limit = int(re.search(r'(?m)^LimitNOFILE=([0-9]+)$', service).group(1))
        # Namespace FD + lifecycle socket + TCP/UDP reservation per slot,
        # two Discord RPC listeners and margin for manager/command descriptors.
        self.assertGreaterEqual(limit, 4 * 128 + 2 * 10 + 32)

    def test_boot_pool_is_ready_before_socket_publication_and_greeter_ordering(self):
        source = Path(broker.__file__).read_text(encoding="utf-8")
        main = source[source.index("def main():"):]
        self.assertLess(main.index("endpoints = EndpointPool(pool)"), main.index("listener.bind(SOCKET_PATH)"))
        self.assertLess(main.index("endpoints = EndpointPool(pool)"), main.index('b"READY=1"'))
        constructor = source[source.index("class Network:"):source.index("def receive(")]
        self.assertNotIn('"link", "add"', constructor)
        service = read_text(TARGET / "etc/systemd/system/app-veth.service")
        self.assertIn("Before=podman-devops.service greetd.service", service)
        self.assertIn("Requires=nftables.service stubby.service dnsmasq-app-veth.service apparmor.service", service)
        identity = read_text(SEED / "hosts/installer/identity.env")
        for name in ("IPV4_DNS1", "IPV6_DNS1", "HOSTNAME_DNS1", "IPV4_DNS2", "IPV6_DNS2", "HOSTNAME_DNS2", "PORT"):
            self.assertRegex(identity, r'(?m)^SYSTEM_NAMESERVERS_' + name + r'="[^"\n]*"$')
        stubby = read_text(TARGET / "etc/stubby/stubby.yml.tmpl")
        self.assertIn("listen_addresses:\n  - 127.0.0.1@53054", stubby)
        self.assertIn("dns_transport_list:\n  - GETDNS_TRANSPORT_TLS", stubby)
        self.assertIn("tls_authentication: GETDNS_AUTHENTICATION_REQUIRED", stubby)
        self.assertIn("round_robin_upstreams: 0", stubby)
        self.assertIn("dnssec: GETDNS_EXTENSION_TRUE", stubby)
        self.assertIn('dnssec_trust_anchors: "/usr/share/dns/root.key"', stubby)
        self.assertIn("__INSTALLER_SYSTEM_NAMESERVERS_UPSTREAMS__", stubby)
        self.assertRegex(identity, r'(?m)^STATIC_INSTALLER_NAMESERVER="[^"\n]+"$')
        self.assertNotIn("STATIC_NAMESERVERS_DEFAULT", identity)
        dnsmasq = read_text(TARGET / "etc/dnsmasq-app-veth.conf")
        self.assertIn("listen-address=127.0.0.1", dnsmasq)
        self.assertIn("port=53053", dnsmasq)
        self.assertIn("server=127.0.0.1#53054", dnsmasq)
        self.assertIn("cache-size=__INSTALLER_SYSTEM_DNS_CACHE_SIZE__", dnsmasq)
        self.assertIn("min-cache-ttl=__INSTALLER_SYSTEM_DNS_CACHE_MIN_TTL__", dnsmasq)
        self.assertIn("clear-on-reload", dnsmasq)
        self.assertNotIn("proxy-dnssec", dnsmasq)
        for option in ("dnssec", "domain-needed", "bogus-priv", "stop-dns-rebind"):
            self.assertNotIn(option, dnsmasq.splitlines())
        dns_service = read_text(TARGET / "etc/systemd/system/dnsmasq-app-veth.service")
        self.assertIn("Type=exec\n", dns_service)
        self.assertIn("Group=nogroup", dns_service)
        self.assertIn("ExecStart=/usr/sbin/dnsmasq", dns_service)
        self.assertIn("RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK", dns_service)
        self.assertIn("RestartMode=direct", dns_service)
        self.assertNotIn("systemd-resolved.service", dns_service)
        self.assertIn("PartOf=stubby.service", dns_service)
        self.assertIn("RestartMode=direct", read_text(TARGET / "etc/systemd/system/stubby.service.d/60-app-veth.conf"))
        resolved = read_text(TARGET / "etc/systemd/resolved.conf.d/60-app-veth.conf.tmpl")
        self.assertIn("DNS=127.0.0.1:53054", resolved)
        self.assertIn("FallbackDNS=\n", resolved)
        self.assertIn("DNSOverTLS=no\n", resolved)
        self.assertIn("Cache=yes\nCacheFromLocalhost=yes", resolved)
        policy = read_text(TARGET / "etc/NetworkManager/conf.d/70-app-veth.conf")
        patterns = policy.split("match-device=", 1)[1].splitlines()[0].split(";")
        self.assertTrue(all(pattern.startswith("interface-name:=") for pattern in patterns))
        patterns = [pattern.removeprefix("interface-name:=") for pattern in patterns]
        self.assertEqual(len(set(patterns)), 2 * int(network_identity_values()["APP_VETH_MAX_LEASES"]))
        for slot in range(int(network_identity_values()["APP_VETH_MAX_LEASES"])):
            for name in (f"veth{slot}-app", f"veth{slot}-peer"):
                self.assertIn(name, patterns)
        for name in ("eth0", "tailscale0", "podman0", "vethabcd123", "veth128-app"):
            self.assertNotIn(name, patterns)
        self.assertIn("managed=0", policy)
        installer = (TARGET.parents[1] / "scripts/late/security.sh").read_text()
        self.assertIn("etc/NetworkManager/conf.d/70-app-veth.conf", installer)
        self.assertIn("etc/stubby/stubby.yml.tmpl", installer)
        self.assertIn("app_veth_dns_placeholder_map", installer)

    def test_namespace_inspection_and_cleanup_permissions_cover_shared_callers(self):
        shared = read_text(TARGET / "etc/apparmor.d/abstractions/app-veth-client")
        self.assertIn("capability sys_ptrace,", shared)
        rules = read_text(TARGET / "etc/apparmor.d/desktop-wrappers")
        for setting in ("signal (send) set=(kill term) peer=labwc-app//app-bwrap,",
                        "signal (receive) set=(kill term) peer=labwc-app,"):
            self.assertIn(setting, rules)
        self.assertIn("/usr/share/iproute2/{,**} r,", read_text(TARGET / "etc/apparmor.d/app-veth"))

    def test_podman_adapter_and_import_are_staged_before_offline_setup_on_a_fresh_target(self):
        script = r'''
set -eu
SEED=$1
INSTALLER_TARGET_DIR=$2
ACCOUNT_USERNAME=fixture
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
installer_info() { :; }
installer_repo_join_var() { [ "$1" = DIR_HOOKS_TARGET ]; printf '%s/hooks/target/%s\n' "$SEED" "$2"; }
stage_target_asset() {
  destination="$INSTALLER_TARGET_DIR$2"
  mkdir -p -- "${destination%/*}"
  cp -- "$1" "$destination"
  chmod "$3" "$destination"
}
stage_target_helper_docs() { :; }
install_target_account_shell_assets() { :; }
run_in_target() {
  phase=$1
  shift
  case "$phase" in
    'validate staged kernel Podman network adapter')
      [ "$1" = /usr/bin/python3 ] && [ "$2" = -I ] && [ "$3" = -B ]
      shift 3
      [ "$1" = /usr/local/libexec/app-veth-podman ] && [ "$2" = --help ]
      [ -x "$INSTALLER_TARGET_DIR$1" ] || { printf '%s\n' 'missing executable at validation' >&2; exit 1; }
      "$FIXTURE_PYTHON" -I -B -c '
import pathlib,runpy,sys
library=pathlib.Path(sys.argv[1])
sys.path.insert(0,str(library))
from labwc_managed_app import network_client
assert pathlib.Path(network_client.__file__).is_relative_to(library)
script=sys.argv[2]
sys.argv=[script,"--help"]
runpy.run_path(script,run_name="__main__")
' "$INSTALLER_TARGET_DIR/usr/local/lib/python3.14/dist-packages" "$INSTALLER_TARGET_DIR$1"
      ;;
    'provision locked devops rootless engine')
      [ "$1" = /usr/local/libexec/podman-devops-host ] && [ "$2" = setup ]
      [ -x "$INSTALLER_TARGET_DIR/usr/local/libexec/app-veth-podman" ] || exit 1
      [ -f "$INSTALLER_TARGET_DIR/usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_client.py" ] || exit 1
      printf '%s\n' 'offline setup received its staged network dependencies'
      ;;
    *) exit 1 ;;
  esac
}
. "$SEED/scripts/late/podman.sh"
configure_target_rootless_podman
'''
        for family in ('btrfs-family.sh', 'f2fs-family.sh'):
            body = read_text(SEED / 'scripts/late' / family)
            self.assertLess(body.index('\nconfigure_target_rootless_podman_if_selected\n'),
                            body.index('\nconfigure_target_apparmor_auditd\n'))
        with tempfile.TemporaryDirectory(prefix='podman-install-order-') as directory:
            target = Path(directory) / 'target'
            target.mkdir()
            result = subprocess.run(['/bin/dash', '-c', script, 'fixture', str(SEED), str(target)],
                env={**os.environ, 'FIXTURE_PYTHON': sys.executable},
                capture_output=True, text=True, encoding='utf-8', timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('managed kernel network:', result.stdout)
            self.assertIn('offline setup received its staged network dependencies', result.stdout)
            self.assertEqual(stat.S_IMODE((target / 'usr/local/libexec/app-veth-podman').stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((target / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_client.py').stat().st_mode), 0o644)
            self.assertTrue((target / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/__init__.py').exists())
            self.assertFalse((target / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/__pycache__').exists())

    def test_freerdp_selected_folder_has_an_explicit_bind_path_without_exposing_host_home(self):
        with tempfile.TemporaryDirectory(prefix='freerdp-share-') as directory:
            home = Path(directory) / 'home'
            home.mkdir()
            shared = home / 'Shared folder with spaces'
            shared.mkdir()
            arguments = ['/v:192.168.10.25', '/drive:Shared,' + str(shared)]
            mapped, source = sandbox.freerdp_shared_folder(arguments, str(home))
            self.assertEqual(mapped, ['/v:192.168.10.25', '/drive:Shared,/rdp-shared'])
            self.assertEqual(source, str(shared))
            self.assertEqual(arguments[1], '/drive:Shared,' + str(shared))
            self.assertEqual(sandbox.freerdp_shared_folder(['/v:192.168.10.25'], str(home)),
                             (['/v:192.168.10.25'], None))
            outside = Path(directory) / 'outside'
            outside.mkdir()
            link = home / 'escaped'
            link.symlink_to(outside, target_is_directory=True)
            for selected in (str(outside), str(link), str(shared) + ',ro', 'relative'):
                with self.subTest(selected=selected), self.assertRaises(SystemExit):
                    sandbox.freerdp_shared_folder(['/drive:Shared,' + selected], str(home))
            with self.assertRaises(SystemExit):
                sandbox.freerdp_shared_folder(['/drive:Shared,' + str(shared)] * 2, str(home))

    def test_online_managed_apps_have_private_veth_policies(self):
        expected = {
            "chromium", "microsoft-edge", "vivaldi", "code", "mullvad-browser",
            "bitwarden", "chatgpt", "obsidian", "qoredb", "postman", "sleek",
            "spotify", "filen", "discord", "ledger-live", "tutanota", "zoom",
            "telegram-desktop", "retroarch", "keepassxc", "mpv", "liferea", "freerdp",
        }
        self.assertTrue(expected <= set(profiles.PERSISTENT_SANDBOX_CONFIG))
        for app in expected:
            with self.subTest(app=app):
                self.assertTrue(profiles.APPS[app]["persistent_sandbox"])
                policy = profiles.PERSISTENT_SANDBOX_CONFIG[app]
                self.assertFalse(policy["share_net"])
                self.assertNotIn("veth", policy)
        for app in ("keepassxc", "sleek", "mpv", "retroarch"):
            self.assertNotIn(app, DEFAULT_POLICIES)

    def test_packages_do_not_install_packet_proxies(self):
        for path in (SEED/"classes").rglob("*.cfg"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("d-i pkgsel/include "):
                    self.assertNotIn("slirp4netns", line.split(), path)
                    self.assertNotIn("passt", line.split(), path)
        config = read_text(TARGET/"data/config/podman/templates/devops/containers.conf")
        self.assertIn('network_cmd_path = "/usr/local/libexec/app-veth-podman"', config)
        self.assertIn('network_backend = "netavark"', config)
        self.assertIn('netns = "bridge"', config)

    def test_installer_and_logging_include_new_assets(self):
        source = read_text(SEED/"scripts/late/security.sh")
        self.assertIn("  configure_target_app_veth\n", source)
        for path in ("/usr/local/sbin/app-veth", "/usr/local/libexec/app-veth-podman",
                     "/etc/app-veth.json",
                     "/etc/systemd/resolved.conf.d/60-app-veth.conf",
                     "/etc/stubby/stubby.yml", "/etc/dnsmasq-app-veth.conf",
                     "/etc/systemd/system/dnsmasq-app-veth.service",
                     "/etc/systemd/system/stubby.service.d/60-app-veth.conf"):
            self.assertIn(path, source)
        self.assertNotIn("/usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_client.py", source)
        self.assertIn('/usr/local/sbin/app-veth --check-config', source)
        managed_apps = read_text(SEED/"scripts/desktop/components/apps.sh")
        self.assertNotIn("managed application package destination already exists in fresh target", managed_apps)
        self.assertIn('mv -- "$managed_app_stage_dir" "$managed_app_package_dir"', managed_apps)
        self.assertIn('LOG_VETH_FILE="${LOG_NETWORK_DIR}/veth.log"', (SEED/"hosts/logging/observability.env").read_text(encoding="utf-8"))
        for file in ("usr/local/libexec/log-layout", "usr/local/libexec/rsyslog-size-rotate", "etc/tmpfiles.d/59-log-layout.conf"):
            self.assertIn("/var/log/managed/network/veth.log", read_text(TARGET/file))

    def test_caller_and_payload_apparmor_authority_are_separate(self):
        rules = read_text(TARGET/"etc/apparmor.d/app-veth")
        self.assertIn("capability net_admin,", rules)
        self.assertNotIn("capability sys_ptrace,", rules)
        self.assertNotIn("/dev/net/tun", rules)
        self.assertIn("/run/podman-devops/**/rootless-netns/rootless-netns r,", rules)
        self.assertIn("enforce required app-veth -", read_text(TARGET/"etc/apparmor/modes.conf"))
        for file in ("etc/apparmor.d/desktop-wrappers", "etc/apparmor.d/zoom-discord-compat"):
            self.assertIn("abstractions/app-veth-client", read_text(TARGET/file))
        self.assertIn("/run/podman-devops/podman.sock rw,", read_text(TARGET/"etc/apparmor.d/abstractions/codex-runtime"))
        for file in ("etc/apparmor.d/abstractions/bwrap-desktop-runtime",
                     "etc/apparmor.d/abstractions/codex-runtime"):
            self.assertIn("@{PROC}/@{pid}/net/{tcp,tcp6,udp,udp6} r,", read_text(TARGET/file))


if __name__ == "__main__":
    unittest.main()
