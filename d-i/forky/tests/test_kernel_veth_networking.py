"""Kernel networking contracts: offline administration mocks and real local IPC.

No host routes, firewall rules, services, or namespaces are changed here.
"""
from __future__ import annotations

import array
import contextlib
import importlib.util
import ipaddress
import io
import json
import os
from pathlib import Path
import runpy
import signal
import socket
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from payload_fixture import python_library, read_text

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / "hooks/target"
LIBRARY = python_library(TARGET / "usr/local/lib/python3.14/dist-packages")
sys.path.insert(0, str(LIBRARY))
from labwc_managed_app import network_client as client
from labwc_managed_app import network_namespace as supervisor
from labwc_managed_app import generic, profiles, sandbox

broker = types.ModuleType("tested_veth_broker")
broker.__file__ = str(TARGET / "usr/local/sbin/app-veth")
exec(compile(Path(broker.__file__).read_text(encoding="utf-8"), broker.__file__, "exec"), broker.__dict__)
podman_adapter = types.ModuleType("tested_podman_adapter")
podman_adapter.__file__ = str(TARGET / "usr/local/libexec/app-veth-podman")
exec(compile(Path(podman_adapter.__file__).read_text(encoding="utf-8"), podman_adapter.__file__, "exec"), podman_adapter.__dict__)


class ConfigurationPublisherTests(unittest.TestCase):
    """Exercise the production POSIX map renderer, not string replacement."""

    def render(self, directory, *, account="desktop", port=None):
        script = r'''
set -eu
. "$1/scripts/common/modules/files-logging.sh"
. "$1/scripts/late/target-assets.sh"
. "$1/scripts/late/security.sh"
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
TMP_ENV_DIR=$2
cp "$1/hooks/target/etc/app-veth.json.tmpl" "$2/config.json"
apply_placeholder_map_to_target "$2/config.json" app_veth_placeholder_map
installer_assert_no_unresolved_installer_placeholders "$2/config.json" app-veth
'''
        environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C",
                       "ACCOUNT_USERNAME": account}
        if port is not None:
            environment["LABWC_QBITTORRENT_PORT"] = port
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
                    self.assertEqual(json.loads(path.read_text()),
                                     {"desktop_user": "desktop", "peer_port": int(port or "50309")})
                    # Target-root ownership is modeled here; the parser itself
                    # and the rendered bytes are production code.
                    metadata = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_nlink=1)
                    with mock.patch.object(broker, "CONFIG", str(path)), \
                            mock.patch.object(broker.os, "fstat", return_value=metadata), \
                            mock.patch.object(broker.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=1000)):
                        self.assertEqual(broker.configuration(), (1000, int(port or "50309")))

    def test_invalid_network_policy_fails_during_rendering(self):
        for account, port in (("root", "50309"), ("desktop", "1023"), ("desktop", "65536"),
                              ("desktop", "050309"), ("desktop", "50309\nmalformed")):
            with self.subTest(account=account, port=port), tempfile.TemporaryDirectory() as directory:
                for result in self.render(directory, account=account, port=port):
                    self.assertNotEqual(result.returncode, 0)

    def test_config_check_cli_validates_without_network_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"desktop_user":"desktop","peer_port":50309}\n', encoding="ascii")
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
            code = ('import runpy,sys; module=runpy.run_path(sys.argv[1]); '
                    'check=module["configuration"]; check.__globals__["CONFIG"]=sys.argv[2]; check()')
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, broker.__file__, str(path)],
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe managed network configuration", result.stderr)


class AuthorizationTests(unittest.TestCase):
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

    def request(self, request, *, count=1, uid=None, authorize=True):
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
                return broker.receive(right, os.getuid() if uid is None else uid)
        finally:
            left.close(); right.close(); os.close(descriptor)

    def test_real_fd_transfer_is_cloexec_and_ownership_checked(self):
        _pid, uid, app, fd = self.request({"app": "codex"})
        try:
            self.assertEqual((uid, app), (os.getuid(), "codex"))
            self.assertFalse(os.get_inheritable(fd))
        finally:
            os.close(fd)

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

    def test_peer_forwarding_port_requires_a_canonical_ready_integer(self):
        for port in (None, True, "50309", 1023, 65536, 50309):
            channel = mock.Mock()
            channel.getsockopt.return_value = struct.pack("3i", 12, 0, 0)
            channel.recvmsg.return_value = (json.dumps({"ready": True, "address": "10.203.0.2",
                "gateway": "10.203.0.1", "interface": "eth0", "peer_port": port}).encode(), [], 0, None)
            with self.subTest(port=port), mock.patch.object(client, "control_socket_owner", return_value=0), \
                    mock.patch.object(client.socket, "socket", return_value=channel):
                if port == 50309:
                    lease = client.Lease(3, "qbittorrent")
                    self.assertEqual(lease.peer_port, 50309)
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
                with mock.patch.object(client, "system_owner", return_value=(root_uid, root_uid)), \
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


class ResolverTests(unittest.TestCase):
    def test_only_resolved_search_suffixes_enter_the_private_resolver(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stub-resolv.conf"
            path.write_text("# resolved\nnameserver 127.0.0.53\nsearch lan.example vpn.example.\noptions edns0 trust-ad\n", encoding="ascii")
            with mock.patch.object(client, "STUB_RESOLVER_PATH", str(path)):
                self.assertEqual(client.resolver_configuration(), client.RESOLVER_CONFIGURATION + "search lan.example vpn.example.\n")

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
                    self.assertEqual(client.resolver_configuration(), client.RESOLVER_CONFIGURATION + "search " + expected + "\n")

    def test_missing_resolved_snapshot_keeps_broker_stub_without_public_fallback(self):
        with mock.patch.object(client.os, "open", side_effect=FileNotFoundError):
            self.assertEqual(client.resolver_configuration(), client.RESOLVER_CONFIGURATION)


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
        for changes in ({"ifname": "veth32-app"}, {"ifname": "eth0"}, {"ifname": "veth3-vivaldi"},
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
        return broker.Network(3, 70, app, 1000, 50309, ipaddress.IPv4Network("10.203.0.0/24"), self.endpoints)

    def test_kernel_link_is_tagged_and_route_mtu_preserved_without_tun(self):
        network = self.network()
        self.addCleanup(network.close)
        batch = next(options["data"] for argv, options in self.boot_calls if argv == ["/usr/sbin/ip", "-batch", "-"])
        self.assertEqual(batch.count("type veth"), broker.MAX_LEASES)
        self.assertIn("app-veth:" + self.endpoints.ids[3], batch)
        self.assertIn("addr add 10.203.0.13/30 dev veth3-app", batch)
        self.assertIn((["/usr/sbin/ip", "link", "set", "dev", "veth3-app", "mtu", "1420"], {}), self.calls)
        self.assertTrue(any("/proc/self/fd/70" in argv and "veth3-peer" in argv for argv, _ in self.calls))
        self.assertFalse(any("add" in argv and "link" in argv for argv, _ in self.calls))
        self.assertNotIn("/dev/net/tun", str(self.calls))
        self.assertEqual((network.gateway, network.address), ("10.203.0.13", "10.203.0.14"))
        self.assertFalse(any("tc" in argv for argv, _ in self.calls))

    def test_firewall_commits_atomically_before_link_is_up(self):
        events = []
        def command(argv, **kwargs):
            events.append(("command", argv))
            return self.commands(argv, **kwargs)
        with mock.patch.object(broker, "run", side_effect=command), \
                mock.patch.object(broker, "nft", side_effect=lambda text: events.append(("firewall", text))):
            network = self.network()
        self.addCleanup(network.close)
        transaction = next(i for i,e in enumerate(events) if e[0] == "firewall")
        up = [i for i,e in enumerate(events) if e[0] == "command" and e[1][-1] == "up" and "lo" not in e[1]]
        self.assertTrue(up)
        self.assertTrue(all(i > transaction for i in up))

    def test_qbittorrent_dnat_is_exact_tcp_udp_and_route_pinned(self):
        network = self.network("qbittorrent")
        self.addCleanup(network.close)
        transaction = self.transactions[0]
        for transport in ("tcp", "udp"):
            self.assertIn(f'192.0.2.8 . {transport} . 50309 : 10.203.0.14 . 50309', transaction)
        self.assertIn('add element inet app_veth snat_map { "veth3-app" : 192.0.2.8 }', transaction)
        self.assertNotIn('add element inet app_veth snat {', transaction)
        self.assertIn('pinned { "veth3-app" . "wg0" }', transaction)
        self.assertNotIn('outbound {', transaction)
        self.assertEqual(broker.Network.reserve.call_count, 2)

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

    def test_freerdp_egress_is_routed_to_lan_and_wan_without_destination_or_port_pin(self):
        network = self.network("freerdp")
        self.addCleanup(network.close)
        self.assertIn('outbound { "veth3-app" }', self.transactions[0])
        self.assertNotIn('pinned {', self.transactions[0])
        self.assertNotIn('incoming {', self.transactions[0])
        broker.route.assert_called_with(allow_lan=True)
        forward = broker.RULESET.split('chain forward_guard {', 1)[1].split('chain nat {', 1)[0]
        self.assertIn('iifname @outbound accept', forward)
        self.assertIn('oifname @links ct state established,related accept', forward)
        self.assertNotIn('ip daddr', forward.split('iifname @outbound accept', 1)[0])
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
        self.assertFalse(any(argv[-2:] == ["eth0", "up"] for argv, _ in self.calls))

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
        self.assertLess(rules.index(f'iifname {broker.INTERFACE_MATCH} oifname {broker.INTERFACE_MATCH} drop'), rules.index('ct state established,related'))
        self.assertIn('iifname . ip saddr != @sources drop', rules)
        self.assertIn(f'iifname {broker.INTERFACE_MATCH} meta nfproto != ipv4 drop', rules)
        self.assertIn('dnat to 127.0.0.1:53053', rules)
        self.assertNotIn('flush ruleset', rules)

    def test_all_current_and_future_app_policies_reuse_fixed_host_names_without_renaming(self):
        for app in sorted(broker.APPS | {"future-desktop-app"}):
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


class SupervisorTests(unittest.TestCase):
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

    def test_lease_loss_stops_payload_and_closes_lease(self):
        sandbox = mock.Mock()
        sandbox.poll.return_value = None
        lease = mock.Mock()
        lease.check.side_effect = [None, RuntimeError("lease lost")]
        pidfd = os.open("/dev/null", os.O_RDONLY)
        with mock.patch.object(supervisor.subprocess, "Popen", return_value=sandbox), \
                mock.patch.object(supervisor, "_read_bwrap_sandbox_pid", return_value=1234), \
                mock.patch.object(supervisor, "pin_sandbox_init", return_value=pidfd), \
                mock.patch.object(client.Lease, "for_pid", return_value=lease), \
                mock.patch.object(supervisor.signal, "pidfd_send_signal") as terminate_namespace, \
                mock.patch.object(supervisor.os, "write"), \
                mock.patch.object(supervisor, "_stop_subprocess") as stop, self.assertRaises(SystemExit):
            supervisor.run_veth_sandbox(["/usr/bin/bwrap"], ["/usr/bin/true"], "/unused", (), app="codex")
        stop.assert_called_once_with(sandbox)
        terminate_namespace.assert_called_once_with(pidfd, supervisor.signal.SIGKILL)
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

    def test_pid_namespace_cleanup_rejects_the_current_host_namespace(self):
        with self.assertRaisesRegex(ValueError, "separate PID namespace"):
            supervisor.pin_sandbox_init(os.getpid())

    def test_real_startup_gate_rejects_eof_and_preserves_literal_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/"payload"
            for readiness in (b"", b"1"):
                with self.subTest(readiness=readiness):
                    reader, writer = os.pipe()
                    literal = 'literal $(touch unsafe); "two words"'
                    command = [sys.executable, "-I", "-B", "-c", supervisor.PEER_STARTUP_GATE, str(reader),
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

    def test_native_persistent_launches_gate_payload_and_preserve_only_configured_state(self):
        apps = set(profiles.PERSISTENT_SANDBOX_CONFIG) - {"chatgpt", "discord", "zoom", "tutanota", "qbittorrent", "qoredb"}
        for app in sorted(apps):
            with self.subTest(app=app), tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
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
                stack.enter_context(mock.patch.object(sandbox, "current_user_runtime_socket", return_value=str(runtime/"wayland-0")))
                for name in ("start_session_bus_proxy", "start_system_bus_proxy"):
                    stack.enter_context(mock.patch.object(sandbox, name, return_value=(None, None, None)))
                for name in ("stop_dbus_proxies", "require_running_dbus_proxies", "add_gpu_device_binds", "add_video_device_binds", "add_native_device_binds"):
                    stack.enter_context(mock.patch.object(sandbox, name))
                stack.enter_context(mock.patch.object(sandbox.mounts, "add_user_media_directory_bind"))
                def launch(command, payload, temporary, inherited, **options):
                    self.assertEqual(options["app"], app)
                    self.assertEqual(payload, [profiles.APPS[app]["exec"], "literal-url"])
                    self.assertNotIn("literal-url", command)
                    self.assertNotIn("--share-net", command)
                    self.assertIn("--unshare-all", command)
                    sandbox.validate_private_procfs(command)
                    resolver = command[command.index("/etc/resolv.conf")-1]
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
                stack.enter_context(mock.patch.object(sandbox, "run_veth_sandbox", side_effect=launch))
                self.assertEqual(sandbox.run_persistent_sandbox(app, "launch", []), 37)

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
            stack.enter_context(mock.patch.object(sandbox, "current_user_runtime_socket", return_value=str(root/"wayland-0")))
            stack.enter_context(mock.patch.object(sandbox, "current_user_home", return_value=str(root)))
            stack.enter_context(mock.patch.object(sandbox, "start_session_bus_proxy", return_value=(None, None, None)))
            stack.enter_context(mock.patch.object(sandbox, "stop_dbus_proxy"))
            stack.enter_context(mock.patch.object(sandbox, "require_running_dbus_proxy"))
            captured = {}
            def launch(command, payload, temporary, inherited, **options):
                captured.update(command=command, payload=payload, app=options["app"])
                self.assertEqual((Path(temporary)/"resolv.conf").read_text(encoding="utf-8"), sandbox.veth_resolv_conf())
                self.assertNotIn("--share-net", command)
                self.assertNotIn("literal-url", command)
                sandbox.validate_private_procfs(command)
                return 37
            stack.enter_context(mock.patch.object(sandbox, "run_veth_sandbox", side_effect=launch))
            self.assertEqual(sandbox.run_pure_privacy("chromium", []), 37)
            self.assertEqual(captured["payload"], ["/usr/bin/chromium", "literal-url"])
            self.assertEqual(captured["app"], "chromium")

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
            lease = stack.enter_context(mock.patch.object(sandbox, "run_veth_sandbox"))
            def launch(command, **options):
                self.assertNotIn("--share-net", command)
                self.assertEqual(command[-1], "/usr/bin/keepassxc")
                resolver = command[command.index("/etc/resolv.conf")-1]
                self.assertEqual(Path(resolver).read_text(encoding="utf-8"), "# Networking is disabled.\n")
                sandbox.validate_private_procfs(command)
                return subprocess.CompletedProcess(command, 37)
            stack.enter_context(mock.patch.object(sandbox.subprocess, "run", side_effect=launch))
            self.assertEqual(sandbox.run_pure_privacy("keepassxc", []), 37)
            lease.assert_not_called()


class PodmanAdapterTests(unittest.TestCase):
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
        lease.close.side_effect = left.close
        os.write(exit_write, b"stop")
        try:
            with mock.patch.object(podman_adapter, "Lease", return_value=lease) as constructor:
                status = podman_adapter.main(["-c", "-r", str(ready_write), "-e", str(exit_read),
                                              "--netns-type=path", "--disable-host-loopback", "--mtu=65520",
                                              "/dev/null", "tap0"])
                self.assertEqual(constructor.call_args.args[1], "podman")
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
fixture=json.load(sys.stdin)
def ip(*args, data=None):
    result=subprocess.run(["/usr/sbin/ip",*args],input=data,capture_output=True,text=True,timeout=5)
    assert result.returncode == 0, result.stderr
    return result.stdout
ip("-batch","-",data=fixture["batch"])
links={row["ifname"]:row for row in json.loads(ip("-j","-d","link","show"))}
addresses={row["ifname"]:row for row in json.loads(ip("-j","-4","addr","show"))}
assert len(links) == 65
for slot in range(32):
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
    ip("link","set","dev",name,"mtu","1420")
    current=json.loads(ip("-j","link","show","dev",name))[0]
    assert current["ifindex"] == links[name]["ifindex"] and current["ifname"] == name
    assert current["ifalias"] == "app-veth:"+fixture["ids"][str(slot)]
    assert "UP" not in current["flags"]
import runpy
recovery=runpy.run_path(sys.argv[1])["recover_endpoints"]
recovery()
assert [row["ifname"] for row in json.loads(ip("-j","link","show"))] == ["lo"]
ip("link","add","name","veth0-app","type","veth","peer","name","veth0-peer")
recovery()
assert [row["ifname"] for row in json.loads(ip("-j","link","show"))] == ["lo"]
print("native boot pool: 32 fixed pairs DOWN, gateway addresses, stable names/indexes and recovery passed")
'''
        result = subprocess.run(["/usr/bin/unshare", "-Urn", sys.executable, "-I", "-B", "-c", script, broker.__file__],
                                input=json.dumps({"batch": batch, "ids": identities}), capture_output=True,
                                text=True, encoding="utf-8", timeout=20)
        if result.returncode and result.stderr.startswith("unshare: unshare failed: Operation not permitted"):
            self.skipTest("unprivileged kernel namespaces are unavailable")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("32 fixed pairs DOWN", result.stdout)

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
                "--ro-bind", "/", "/", "--proc", "/proc", "--info-fd", str(info_write),
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
                network = broker.Network(0, 70, app, 1000, 50309, ipaddress.IPv4Network("10.203.0.0/24"), endpoints)
                network.close()
            endpoints.close()
        result = subprocess.run(["/usr/bin/unshare", "-Urn", "/usr/sbin/nft", "--check", "-f", "-"],
                                input=broker.RULESET + "".join(transactions), capture_output=True,
                                text=True, encoding="utf-8", timeout=15)
        if result.returncode and result.stderr.startswith("unshare: unshare failed: Operation not permitted"):
            self.skipTest("unprivileged kernel namespaces are unavailable")
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(all(shutil.which(tool) for tool in ("unshare", "ip", "nft", "nsenter")), "kernel networking tools unavailable")
    def test_real_veth_dns_and_host_isolation_inside_unprivileged_namespaces(self):
        # All links, sysctls and nft state belong to this new user/network
        # namespace. The host network is never entered or modified. A local
        # UDP echo endpoint stands in for resolved; this verifies packet/NAT
        # plumbing, not resolved's DNS processing or any Internet access.
        script = '''import importlib.machinery, importlib.util, ipaddress, os, socket, subprocess, sys, threading
loader=importlib.machinery.SourceFileLoader("fixture_broker",sys.argv[1])
spec=importlib.util.spec_from_loader(loader.name,loader)
b=importlib.util.module_from_spec(spec); loader.exec_module(b)
b.run(["/usr/sbin/ip","link","set","lo","up"])
b.run(["/usr/sbin/sysctl","-q","-w","net.ipv4.ip_forward=1"])
b.run(["/usr/sbin/ip","link","add","dummy0","type","dummy"])
b.run(["/usr/sbin/ip","addr","add","192.0.2.1/24","dev","dummy0"])
b.run(["/usr/sbin/ip","link","set","dummy0","up"])
b.route=lambda **options:("dummy0","192.0.2.1",1500)
b.nft(b.RULESET)
endpoints=b.EndpointPool(ipaddress.IPv4Network("10.203.0.0/24"))
child=subprocess.Popen(["/usr/bin/unshare","-n","/usr/bin/sleep","30"])
fd=None; network=None
try:
    import time
    for attempt in range(100):
        time.sleep(.01)
        fd=os.open(f"/proc/{child.pid}/ns/net",os.O_RDONLY)
        if os.fstat(fd).st_ino != os.stat("/proc/self/ns/net").st_ino: break
        os.close(fd);fd=None
    assert fd is not None
    network=b.Network(0,fd,"chromium",os.getuid(),50309,ipaddress.IPv4Network("10.203.0.0/24"),endpoints)
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
    # Exercise the actual qBittorrent source-NAT map transaction too.
    network=b.Network(0,fd,"qbittorrent",os.getuid(),50309,ipaddress.IPv4Network("10.203.0.0/24"),endpoints)
    network.close();network=None
    print("isolated kernel veth UDP DNS NAT, host guard and qBittorrent transaction passed")
finally:
    if network is not None: network.close()
    endpoints.close()
    if fd is not None: os.close(fd)
    child.terminate();child.wait(timeout=5)
'''
        result = subprocess.run(["/usr/bin/unshare", "-Urnmpf", "--mount-proc", sys.executable, "-I", "-B", "-c", script, broker.__file__],
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        if result.returncode and result.stderr.startswith("unshare: unshare failed: Operation not permitted"):
            self.skipTest("unprivileged kernel namespaces are unavailable")
        if result.returncode and 'sysctl: permission denied on key "net.ipv4.ip_forward"' in result.stderr:
            self.skipTest("environment denies sysctl writes even in an isolated user/network namespace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("isolated kernel veth UDP DNS NAT", result.stdout)


class InstallationTests(unittest.TestCase):
    def test_boot_pool_is_ready_before_socket_publication_and_greeter_ordering(self):
        source = Path(broker.__file__).read_text(encoding="utf-8")
        main = source[source.index("def main():"):]
        self.assertLess(main.index("endpoints = EndpointPool(pool)"), main.index("listener.bind(SOCKET_PATH)"))
        self.assertLess(main.index("endpoints = EndpointPool(pool)"), main.index('b"READY=1"'))
        constructor = source[source.index("class Network:"):source.index("def receive(")]
        self.assertNotIn('"link", "add"', constructor)
        service = read_text(TARGET / "etc/systemd/system/app-veth.service")
        self.assertIn("Before=podman-devops.service greetd.service", service)
        policy = read_text(TARGET / "etc/NetworkManager/conf.d/70-app-veth.conf")
        patterns = policy.split("match-device=", 1)[1].splitlines()[0].split(";")
        self.assertTrue(all(pattern.startswith("interface-name:=") for pattern in patterns))
        patterns = [pattern.removeprefix("interface-name:=") for pattern in patterns]
        self.assertEqual(len(set(patterns)), 2 * broker.MAX_LEASES)
        for slot in range(broker.MAX_LEASES):
            for name in (f"veth{slot}-app", f"veth{slot}-peer"):
                self.assertIn(name, patterns)
        for name in ("eth0", "tailscale0", "podman0", "vethabcd123", "veth32-app"):
            self.assertNotIn(name, patterns)
        self.assertIn("managed=0", policy)
        installer = (TARGET.parents[1] / "scripts/late/security.sh").read_text()
        self.assertIn("etc/NetworkManager/conf.d/70-app-veth.conf", installer)

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
                self.assertTrue(policy["veth"])

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
                     "/etc/systemd/resolved.conf.d/60-app-veth.conf"):
            self.assertIn(path, source)
        self.assertNotIn("/usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_client.py", source)
        self.assertIn('/usr/local/sbin/app-veth --check-config', source)
        managed_apps = read_text(SEED/"scripts/desktop/components/managed-apps.sh")
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
