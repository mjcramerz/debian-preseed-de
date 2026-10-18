"""Private netkit contracts. Every external operation is an explicit fixture.

These tests require the repository's disposable environment before importing
the runtime source. They do not provide native network or AppArmor acceptance.
"""
from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation
require_test_isolation()

from contextlib import redirect_stdout
import copy
import io
import json
import os
import signal
import tempfile
import types
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
netkit = types.ModuleType('netkit_fixture')
exec(compile((TARGET / 'usr/local/libexec/tailscale-netkit').read_bytes(), 'netkit-fixture', 'exec'), netkit.__dict__)
RUN = netkit.run
ssh = types.ModuleType('netkit_ssh_fixture')
exec(compile((TARGET / 'usr/local/libexec/tailscale-ssh-host').read_bytes(), 'ssh-fixture', 'exec'), ssh.__dict__)
firewall = types.ModuleType('netkit_firewall_fixture')
sys.modules[firewall.__name__] = firewall
exec(compile((TARGET / 'usr/local/sbin/nft-policy-generate.py').read_bytes(), 'firewall-fixture', 'exec'), firewall.__dict__)

CONFIG = {'version': 1, 'interface': 'tailscale0', 'physical_interfaces': ['eth0', 'wifi0'],
          'port': 41641, 'dns_address': '127.0.0.1', 'dns_port': 53053, 'accept_dns': False}
ALIAS = 'tailscale-netkit:' + '1' * 32


class NetkitTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(CONFIG)
        temporary = tempfile.TemporaryDirectory(prefix='netkit-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        for name, value in (('RUNTIME', self.root), ('STOP', False), ('CLEANUP_DEADLINE', None)):
            patcher = mock.patch.object(netkit, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Any command not explicitly replaced by a test is a fixture failure.
        patcher = mock.patch.object(netkit, 'run', side_effect=AssertionError('uncontrolled external command'))
        self.commands = patcher.start()
        self.addCleanup(patcher.stop)

    def state(self):
        path = self.root / 'state.json'
        path.write_text(json.dumps({'interface': 'tailscale0', 'alias': ALIAS, 'ifindex': 42}))
        path.chmod(0o600)
        return path

    def test_service_dispatch_accepts_both_centrally_selected_apparmor_modes(self):
        daemon_args = ['--tun=tailscale0', '--port=41641',
                       '--state=/var/lib/tailscale/tailscaled.state',
                       '--socket=/run/tailscale/tailscaled.sock', '--no-logs-no-support']
        for mode in ('enforce', 'complain'):
            with self.subTest(mode=mode), \
                    mock.patch.dict(os.environ, {'DESKTOP_APPARMOR_STATE': mode}, clear=True), \
                    mock.patch.object(netkit.os, 'geteuid', return_value=0), \
                    mock.patch('builtins.open', side_effect=AssertionError('unexpected state read')), \
                    mock.patch.object(netkit, 'configuration', return_value=self.config), \
                    mock.patch.object(netkit, 'mount_handoff') as handoff, \
                    mock.patch.object(netkit, 'builder') as builder, \
                    mock.patch.object(netkit, 'daemon') as daemon, \
                    mock.patch.object(netkit, 'supervise', return_value=0) as supervise, \
                    mock.patch.object(netkit, 'cleanup_cgroup_is_drained') as drained, \
                    mock.patch.object(netkit, 'cleanup') as cleanup, \
                    mock.patch.object(netkit.signal, 'signal'):
                # Delegates and lifecycle operations must not require a loaded
                # enforce label. Mode reconciliation belongs to modes.conf.
                self.assertEqual(netkit.main(['mount-handoff']), 0)
                self.assertEqual(netkit.main(['builder', '77']), 1)
                self.assertEqual(netkit.main(['daemon', '77', '78', '79', *daemon_args]), 1)
                self.assertEqual(netkit.main(['run', *daemon_args]), 0)
                self.assertEqual(netkit.main(['cleanup']), 0)
                handoff.assert_called_once_with()
                builder.assert_called_once_with(77)
                daemon.assert_called_once_with(77, 78, 79, daemon_args)
                supervise.assert_called_once_with(self.config, daemon_args)
                drained.assert_called_once_with()
                cleanup.assert_called_once_with(self.config)
        self.commands.assert_not_called()

    def test_configuration_rejects_injection_overlaps_and_wrong_scalar_types(self):
        for replacement in ({'interface': 'veth0-host'}, {'interface': 'eth0'},
                            {'physical_interfaces': [['nested'], 'wifi0']}, {'port': True},
                            {'dns_address': '0.0.0.0'}, {'accept_dns': 'false'},
                            {'interface': 'tailscale0;flush ruleset'}):
            with self.subTest(replacement=replacement):
                value = {**self.config, **replacement}
                with mock.patch.object(netkit, 'regular', return_value=json.dumps(value).encode()), \
                        self.assertRaises(netkit.Error):
                    netkit.configuration()
        self.commands.assert_not_called()

    def test_configuration_rejects_duplicate_keys(self):
        with mock.patch.object(netkit, 'regular', return_value=b'{"version":1,"version":1}'), \
                self.assertRaisesRegex(netkit.Error, 'duplicate'):
            netkit.configuration()

    def test_fresh_setup_uses_netkit_and_owns_only_fixed_policy_rules(self):
        calls = []
        def command(argv, **kwargs):
            calls.append((argv, kwargs))
            return b'{"nftables":[]}' if argv[-2:] == ['list', 'tables'] else b''
        with mock.patch.object(netkit, 'run', side_effect=command), \
                mock.patch.object(netkit, 'objects', return_value=[]), \
                mock.patch.object(netkit, 'mark_created_link'), \
                mock.patch.object(netkit, 'owned_link', return_value={'ifindex': 42}), \
                mock.patch.object(netkit, 'ip') as ip:
            state = netkit.setup(self.config, 77)
        self.assertEqual(state['ifindex'], 42)
        arguments = [call.args[0] for call in ip.call_args_list]
        self.assertTrue(any('netkit' in args and 'l3' in args for args in arguments))
        self.assertFalse(any('veth' in args or 'macvlan' in args for args in arguments))
        for peer, family in ((netkit.PEER4, '-4'), (netkit.PEER6, '-6')):
            self.assertIn([family, 'rule', 'add', 'pref', '5191', 'from', peer, 'unreachable',
                           'protocol', netkit.ROUTE_PROTOCOL], arguments)
        self.assertTrue((self.root / 'state.json').is_file())

    def test_new_link_marker_uses_pinned_device_and_does_not_trust_create_alias(self):
        device = self.root / 'device'
        device.mkdir()
        (device / 'ifindex').write_text('42\n')
        (device / 'ifalias').write_text('')
        state = {'interface': 'tailscale0', 'alias': ALIAS}
        pair = [{'ifname': name, 'ifindex': index, 'link': other, 'flags': [],
                 'linkinfo': {'info_kind': 'netkit', 'info_data': {'mode': 'l3', 'type': role}}}
                for name, index, other, role in [('tailscale0', 42, 'ts-uplink', 'primary'), ('ts-uplink', 43, 'tailscale0', 'peer')]]
        original_open = os.open
        def opened(path, flags, *args, **kwargs):
            if str(path) == '/sys/class/net/tailscale0':
                path = device
            elif str(path) in ('ifindex', 'ifalias'):
                self.assertIn('dir_fd', kwargs)
            elif not str(path).startswith(str(self.root)):
                raise AssertionError('uncontrolled fixture access')
            return original_open(path, flags, *args, **kwargs)
        with mock.patch.object(netkit, 'objects', return_value=pair), \
                mock.patch.object(netkit.os, 'open', side_effect=opened), \
                mock.patch.object(netkit, 'owned_link', return_value={'ifindex': 42}):
            netkit.mark_created_link(self.config, state)
        self.assertEqual((device / 'ifalias').read_text(), ALIAS + '\n')
        self.assertEqual(state['ifindex'], 42)
        (device / 'ifalias').write_text('')
        (device / 'ifindex').write_text('44\n')
        with mock.patch.object(netkit, 'objects', return_value=pair), \
                mock.patch.object(netkit.os, 'open', side_effect=opened), \
                self.assertRaisesRegex(netkit.Error, 'index changed'):
            netkit.mark_created_link(self.config, state)
        self.assertEqual((device / 'ifalias').read_text(), '')
        self.commands.assert_not_called()

    def test_empty_route_table_is_not_queried_as_a_missing_fib(self):
        with mock.patch.object(netkit, 'objects', return_value=[{'table': 'main', 'dst': 'default'}]) as query:
            self.assertEqual(netkit.table_routes('-4', '52'), [])
        query.assert_called_once_with(['-4', 'route', 'show', 'table', 'all'], None)

    def test_route_mirror_updates_source_and_ignores_private_non_tun_routes(self):
        status = {'BackendState': 'Running', 'Self': {'TailscaleIPs': ['100.100.1.2']}}
        def objects(args, namespace=None):
            if args[:2] == ['-4', 'address']:
                return [{'addr_info': [{'local': netkit.HOST4}, {'local': '100.100.1.2'}]}]
            return []
        def routes(family, table, namespace=None):
            if family == '-6':
                return []
            if namespace is not None:
                return [{'dev': 'tailscale0', 'dst': '100.101.0.0/16'},
                        {'dev': 'ts-uplink', 'dst': '203.0.113.0/24'}]
            return [{'dev': 'tailscale0', 'dst': '100.101.0.0/16', 'gateway': netkit.PEER4,
                     'protocol': int(netkit.ROUTE_PROTOCOL), 'prefsrc': '100.100.1.1'}]
        with mock.patch.object(netkit, 'objects', side_effect=objects), \
                mock.patch.object(netkit, 'table_routes', side_effect=routes), \
                mock.patch.object(netkit, 'ip') as ip, redirect_stdout(io.StringIO()):
            netkit.mirror(self.config, 77, (), status)
        self.assertEqual(ip.call_count, 1)
        self.assertIn('replace', ip.call_args.args[0])
        self.assertEqual(ip.call_args.args[0][-3:], ['100.100.1.2', 'protocol', netkit.ROUTE_PROTOCOL])

    def test_foreign_route_aborts_without_replacing_it(self):
        status = {'BackendState': 'Stopped'}
        with mock.patch.object(netkit, 'objects', return_value=[]), \
                mock.patch.object(netkit, 'table_routes', return_value=[{'protocol': 'static', 'dev': 'foreign'}]), \
                mock.patch.object(netkit, 'ip') as ip, self.assertRaisesRegex(netkit.Error, 'ownership'):
            netkit.mirror(self.config, 77, (), status)
        ip.assert_not_called()

    def test_exit_node_block_and_lan_exception_survive_without_ipv6_self_address(self):
        status = {'BackendState': 'Running', 'Self': {'TailscaleIPs': ['100.100.1.2']}}
        def records(args, namespace=None):
            if args[:2] == ['-4', 'address']:
                return [{'addr_info': [{'local': netkit.HOST4}, {'local': '100.100.1.2'}]}]
            return [{'addr_info': [{'local': netkit.HOST6}, {'local': 'fe80::1'}]}]
        def routes(family, table, namespace=None):
            if namespace is None:
                return []
            if family == '-6':
                return [{'type': 'unreachable', 'dst': 'default'}]
            return [{'type': 'throw', 'dst': '192.168.0.0/16'}]
        with mock.patch.object(netkit, 'objects', side_effect=records), \
                mock.patch.object(netkit, 'table_routes', side_effect=routes), \
                mock.patch.object(netkit, 'ip') as ip, redirect_stdout(io.StringIO()):
            netkit.mirror(self.config, 77, (), status)
        arguments = [call.args[0] for call in ip.call_args_list]
        self.assertIn(['-6', 'route', 'replace', 'unreachable', 'table', '52', 'default',
                       'protocol', netkit.ROUTE_PROTOCOL], arguments)
        self.assertIn(['-4', 'route', 'replace', 'throw', 'table', '52', '192.168.0.0/16',
                       'protocol', netkit.ROUTE_PROTOCOL], arguments)
        self.assertFalse(any('address' in args for args in arguments))

    def test_cleanup_gate_includes_systemd_control_subgroup_and_rejects_live_descendant(self):
        cgroup = self.root / 'cgroup'
        control = cgroup / '.control'
        control.mkdir(parents=True)
        (cgroup / 'cgroup.procs').write_text('')
        (control / 'cgroup.procs').write_text(str(os.getpid()) + '\n')
        original_open, original_scandir = open, os.scandir
        fixed = Path('/sys/fs/cgroup/system.slice/tailscaled.service')
        def fixture_path(path):
            path = Path(path)
            if path.is_relative_to(fixed):
                return cgroup / path.relative_to(fixed)
            if path.is_relative_to(cgroup):
                return path
            raise AssertionError('uncontrolled fixture path')
        def read(path, mode):
            if str(path) == '/proc/self/cgroup':
                return io.BytesIO(b'0::/system.slice/tailscaled.service/.control\n')
            return original_open(fixture_path(path), mode)
        with mock.patch('builtins.open', side_effect=read), \
                mock.patch.object(netkit.os, 'scandir', side_effect=lambda path: original_scandir(fixture_path(path))):
            netkit.cleanup_cgroup_is_drained()
            (cgroup / 'cgroup.procs').write_text('900001\n')
            with self.assertRaisesRegex(netkit.OutcomeUnknown, 'processes remain'):
                netkit.cleanup_cgroup_is_drained()

    def test_replaced_interface_retains_recovery_without_any_command(self):
        state = self.state()
        with mock.patch.object(netkit, 'device_objects', return_value=[
                {'ifindex': 43, 'ifalias': ALIAS, 'linkinfo': {'info_kind': 'netkit'}}]), \
                self.assertRaisesRegex(netkit.Error, 'identity changed'):
            netkit.cleanup(self.config)
        self.assertTrue(state.exists())
        self.commands.assert_not_called()

    def test_foreign_packet_table_retains_recovery_without_deletion(self):
        state = self.state()
        responses = [b'{"nftables":[{"table":{"family":"inet","name":"tailscale_netkit"}}]}',
                     b'{"nftables":[{"table":{"comment":"foreign"}}]}']
        with mock.patch.object(netkit, 'owned_link', return_value=None), \
                mock.patch.object(netkit, 'run', side_effect=responses) as run, \
                self.assertRaisesRegex(netkit.Error, 'packet policy identity'):
            netkit.cleanup(self.config)
        self.assertTrue(state.exists())
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all('delete' not in call.args[0] for call in run.call_args_list))

    def test_foreign_rule_selector_is_checked_before_removing_link(self):
        state = self.state()
        with mock.patch.object(netkit, 'owned_link', return_value={'ifindex': 42}), \
                mock.patch.object(netkit, 'run', return_value=b'{"nftables":[]}'), \
                mock.patch.object(netkit, 'objects', return_value=[
                    {'priority': 5190, 'protocol': int(netkit.ROUTE_PROTOCOL), 'src': '192.0.2.2', 'table': 'main'}]), \
                mock.patch.object(netkit, 'ip') as ip, self.assertRaisesRegex(netkit.Error, 'route rule'):
            netkit.cleanup(self.config)
        ip.assert_not_called()
        self.assertTrue(state.exists())

    def test_cleanup_accepts_iprule_json_actions_and_numeric_string_tables(self):
        def records(args, namespace=None):
            if args[1:] != ['rule', 'show']:
                return []
            peer = netkit.PEER4 if args[0] == '-4' else netkit.PEER6
            return [{'priority': 5190, 'src': peer, 'table': '254', 'protocol': '242'},
                    {'priority': 5191, 'src': peer, 'action': action, 'protocol': '242'},
                    {'priority': 5270, 'src': 'all', 'table': '52', 'protocol': '242'}]
        # -N is part of the real ip() invocation. iprule's action name uses
        # rtnl_rtntype_n2a too, so it becomes "7", not "unreachable".
        for action in ('7', 'unreachable'):
            with self.subTest(action=action):
                state = self.state()
                with mock.patch.object(netkit, 'owned_link', return_value={'ifindex': 42}), \
                        mock.patch.object(netkit, 'run', return_value=b'{"nftables":[]}'), \
                        mock.patch.object(netkit, 'objects', side_effect=records), \
                        mock.patch.object(netkit, 'ip') as ip:
                    netkit.cleanup(self.config)
                self.assertFalse(state.exists())
                self.assertEqual(ip.call_args_list, [mock.call(['link', 'delete', 'dev', 'tailscale0']),
                    *[mock.call([family, 'rule', 'delete', 'pref', str(priority), 'protocol', '242'])
                      for family in ('-4', '-6') for priority in (5190, 5191, 5270)]])

    def test_cleanup_rejects_changed_rule_action_extra_selectors_and_source_prefix(self):
        for replacement in ({'action': 'blackhole'}, {'action': '6'}, {'action': '8'},
                            {'table': '254'}, {'fwmark': '0x1'},
                            {'src': netkit.PEER4 + '/24'}, {'type': 'unreachable'}):
            with self.subTest(replacement=replacement):
                state = self.state()
                record = {'priority': 5191, 'src': netkit.PEER4,
                          'action': 'unreachable', 'protocol': '242', **replacement}
                with mock.patch.object(netkit, 'owned_link', return_value={'ifindex': 42}), \
                        mock.patch.object(netkit, 'run', return_value=b'{"nftables":[]}'), \
                        mock.patch.object(netkit, 'owned_routes', return_value={}), \
                        mock.patch.object(netkit, 'objects', return_value=[record]), \
                        mock.patch.object(netkit, 'ip') as ip, \
                        self.assertRaisesRegex(netkit.Error, 'route rule'):
                    netkit.cleanup(self.config)
                self.assertTrue(state.exists())
                ip.assert_not_called()

    def test_mount_preparation_persists_init_identity_without_binding_its_namespace(self):
        original_mkdir, original_open, original_close = Path.mkdir, os.open, os.close
        def mkdir(path, *args, **kwargs):
            if str(path) == '/run/tailscale':
                return  # Explicit fixture for the API directory, no host access.
            if not path.is_relative_to(self.root):
                raise AssertionError('uncontrolled fixture directory')
            return original_mkdir(path, *args, **kwargs)
        def opened(path, flags, *args, **kwargs):
            if str(path) in {'/proc/self/ns/net', '/proc/1/ns/mnt'}:
                return 71 if str(path).endswith('/net') else 72
            if not Path(path).is_relative_to(self.root):
                raise AssertionError('uncontrolled fixture input')
            return original_open(path, flags, *args, **kwargs)
        with mock.patch.object(Path, 'mkdir', mkdir), \
                mock.patch.object(netkit.os, 'open', side_effect=opened), \
                mock.patch.object(netkit.os, 'close', side_effect=lambda fd: None if fd in (71, 72) else original_close(fd)), \
                mock.patch.object(netkit.os, 'fstat', return_value=types.SimpleNamespace(st_dev=2, st_ino=12)), \
                mock.patch.object(netkit, 'ns_type') as kinds, \
                mock.patch.object(netkit, 'run') as run:
            netkit.prepare_files()
        self.assertEqual(kinds.call_args_list, [mock.call(71, os.CLONE_NEWNET), mock.call(72, os.CLONE_NEWNS)])
        run.assert_called_once_with(['/usr/bin/mount', '--bind', '/proc/self/fd/71', str(self.root / 'host.net')], fds=(71,))
        self.assertEqual((self.root / 'host.mnt').read_bytes(), b'2:12\n')
        self.assertEqual((self.root / 'host.mnt').stat().st_mode & 0o777, 0o600)

    def test_cleanup_removes_owned_mount_identity_and_retains_malformed_identity(self):
        for data in (b'2:12\n', b'not-an-identity\n'):
            with self.subTest(valid=data == b'2:12\n'):
                state = self.state()
                identity = self.root / 'host.mnt'
                identity.write_bytes(data)
                identity.chmod(0o600)
                with mock.patch.object(netkit, 'owned_link', return_value=None), \
                        mock.patch.object(netkit, 'run', return_value=b'{"nftables":[]}'), \
                        mock.patch.object(netkit, 'objects', return_value=[]), \
                        mock.patch.object(netkit, 'ns_type', side_effect=OSError('fixture regular file')):
                    if data == b'2:12\n':
                        netkit.cleanup(self.config)
                        self.assertFalse(state.exists() or identity.exists())
                    else:
                        with self.assertRaisesRegex(netkit.Error, 'namespace mount identity'):
                            netkit.cleanup(self.config)
                        self.assertTrue(state.exists() and identity.exists())

    def test_recovery_never_flushes_shared_policy(self):
        state = self.state()
        with mock.patch.object(netkit, 'owned_link', return_value={'ifindex': 42}), \
                mock.patch.object(netkit, 'run', return_value=b'{"nftables":[]}'), \
                mock.patch.object(netkit, 'objects', return_value=[]), mock.patch.object(netkit, 'ip') as ip:
            netkit.cleanup(self.config)
        ip.assert_called_once_with(['link', 'delete', 'dev', 'tailscale0'])
        self.assertFalse(state.exists())

    def test_failed_cleanup_retains_its_state(self):
        state = self.state()
        with mock.patch.object(netkit, 'owned_link', return_value={'ifindex': 42}), \
                mock.patch.object(netkit, 'run', return_value=b'{"nftables":[]}'), \
                mock.patch.object(netkit, 'objects', return_value=[]), \
                mock.patch.object(netkit, 'ip', side_effect=netkit.Error('fixture link deletion refused')), \
                self.assertRaisesRegex(netkit.Error, 'deletion refused'):
            netkit.cleanup(self.config)
        self.assertTrue(state.exists())
        self.assertIsNone(netkit.CLEANUP_DEADLINE)

    def test_dns_disabled_never_reads_private_or_host_dns(self):
        with mock.patch.object(netkit, 'regular', side_effect=AssertionError('unexpected DNS read')):
            self.assertEqual(netkit.mirror_dns(self.config, ()), ())
        self.commands.assert_not_called()

    def test_dns_mirror_never_uses_transit_resolver_as_host_uplink(self):
        self.config['accept_dns'] = True
        with mock.patch.object(netkit, 'regular', return_value=b'nameserver 169.254.253.1\n'), \
                mock.patch.object(netkit, 'run') as run:
            netkit.mirror_dns(self.config, (('100.100.100.100',), ()))
        run.assert_called_once_with(['/usr/bin/resolvectl', 'revert', 'tailscale0'])

    def test_transport_policy_is_scoped_and_has_no_veth_or_global_flush(self):
        policy = netkit.packet_policy(self.config, ALIAS).decode()
        self.assertNotIn('flush ', policy)
        self.assertNotIn('veth', policy)
        self.assertNotIn('macvlan', policy)
        self.assertIn('oifname { "eth0", "wifi0" } masquerade', policy)
        self.assertIn('ip saddr 169.254.253.2 ip daddr 127.0.0.1', policy)
        self.assertIn('comment "' + ALIAS + '"', policy)

    def test_failed_pidfd_pin_leaves_no_numeric_pid_signal_fallback(self):
        process = types.SimpleNamespace(pid=42, stdout=io.BytesIO(), stderr=io.BytesIO())
        with mock.patch.object(netkit.subprocess, 'Popen', return_value=process), \
                mock.patch.object(netkit.os, 'pidfd_open', side_effect=OSError('fixture pin failure')), \
                mock.patch.object(netkit.os, 'kill') as kill, \
                mock.patch.object(netkit.signal, 'pidfd_send_signal') as pinned_signal, \
                self.assertRaises(netkit.OutcomeUnknown):
            RUN(['/fixture/command'])
        kill.assert_not_called()
        pinned_signal.assert_not_called()
        self.assertTrue(process.stdout.closed and process.stderr.closed)

    def test_mount_constructor_deadlines_report_the_stage_and_retain_recovery(self):
        for stage in ('early-exit', 'connection', 'descriptor', 'exit', 'termination'):
            with self.subTest(stage=stage):
                state = self.state()
                now = [0.0]
                listener, connection = mock.MagicMock(), mock.MagicMock()
                process = mock.Mock(pid=42)
                process.poll.return_value = 23 if stage == 'early-exit' else None
                process.wait.return_value = 0
                def accept():
                    if stage in ('early-exit', 'connection', 'termination'):
                        now[0] += 1
                        raise TimeoutError
                    return connection, None
                listener.accept.side_effect = accept
                import struct
                connection.getsockopt.return_value = struct.pack('3i', 42, 0, 0)
                descriptors = netkit.array.array('i', [81, 82]).tobytes()
                connection.recvmsg.return_value = (b'M', [(netkit.socket.SOL_SOCKET,
                    netkit.socket.SCM_RIGHTS, descriptors)], 0, None)
                if stage == 'descriptor':
                    connection.recvmsg.side_effect = TimeoutError
                if stage == 'exit':
                    process.wait.side_effect = [netkit.subprocess.TimeoutExpired('fixture', 1), 0]
                if stage == 'termination':
                    process.wait.side_effect = netkit.subprocess.TimeoutExpired('fixture', 3)
                expected = ('exited before connection status=23' if stage == 'early-exit'
                    else 'termination outcome unknown' if stage == 'termination'
                    else stage + ' deadline exceeded')
                error_type = netkit.OutcomeUnknown if stage == 'termination' else netkit.Error
                with mock.patch.object(netkit.socket, 'socket') as socket_factory, \
                        mock.patch.object(netkit.subprocess, 'Popen', return_value=process), \
                        mock.patch.object(netkit.os, 'pidfd_open', return_value=77), \
                        mock.patch.object(netkit.os, 'close') as close, \
                        mock.patch.object(netkit.os, 'fstat', return_value=types.SimpleNamespace(
                            st_mode=0o40755, st_uid=0)), \
                        mock.patch.object(netkit, 'ns_type'), \
                        mock.patch.object(netkit.time, 'monotonic', side_effect=lambda: now[0]), \
                        mock.patch.object(netkit.signal, 'pidfd_send_signal') as pinned_signal, \
                        mock.patch.object(netkit.os, 'kill') as numeric_signal:
                    socket_factory.return_value.__enter__.return_value = listener
                    connection.__enter__.return_value = connection
                    with self.assertRaisesRegex(error_type, expected):
                        netkit.build_mount_namespace(70)
                self.assertTrue(state.exists())
                pinned_signal.assert_called_once_with(77, signal.SIGKILL)
                numeric_signal.assert_not_called()
                closed = [call.args[0] for call in close.call_args_list]
                self.assertIn(77, closed)
                for descriptor in (81, 82):
                    self.assertEqual(closed.count(descriptor), 1 if stage == 'exit' else 0)

    def test_mount_constructor_accepts_queued_descriptors_after_child_exit(self):
        for accept_timeout in (False, True):
            with self.subTest(handoff_queued_after_accept_timeout=accept_timeout):
                listener, connection = mock.MagicMock(), mock.MagicMock()
                process = mock.Mock(pid=42)
                process.poll.return_value = 0
                process.wait.return_value = 0
                listener.accept.side_effect = ([TimeoutError] if accept_timeout else []) + [(connection, None)]
                import struct
                connection.getsockopt.return_value = struct.pack('3i', 42, 0, 0)
                descriptors = netkit.array.array('i', [81, 82]).tobytes()
                connection.recvmsg.return_value = (b'M', [(netkit.socket.SOL_SOCKET,
                    netkit.socket.SCM_RIGHTS, descriptors)], 0, None)
                with mock.patch.object(netkit.socket, 'socket') as socket_factory, \
                        mock.patch.object(netkit.subprocess, 'Popen', return_value=process), \
                        mock.patch.object(netkit.os, 'pidfd_open', return_value=77), \
                        mock.patch.object(netkit.os, 'close') as close, \
                        mock.patch.object(netkit.os, 'fstat', return_value=types.SimpleNamespace(st_mode=0o40755, st_uid=0)), \
                        mock.patch.object(netkit, 'ns_type'), \
                        mock.patch.object(netkit.time, 'monotonic', return_value=0):
                    socket_factory.return_value.__enter__.return_value = listener
                    connection.__enter__.return_value = connection
                    self.assertEqual(netkit.build_mount_namespace(70), (81, 82))
                self.assertEqual(process.poll.call_count, int(accept_timeout))
                close.assert_called_once_with(77)

    def test_streaming_output_limit_kills_only_the_pinned_command(self):
        process = mock.Mock(pid=42)
        process.stdout.fileno.return_value = 101
        process.stderr.fileno.return_value = 102
        process.wait.return_value = -signal.SIGKILL
        class Selector:
            def __init__(self):
                self.entries = {}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def register(self, stream, events, data):
                self.entries[stream] = data
            def get_map(self):
                return self.entries
            def select(self, timeout):
                stream = next(iter(self.entries))
                return [(types.SimpleNamespace(fileobj=stream, data=self.entries[stream]), 1)]
        with mock.patch.object(netkit.subprocess, 'Popen', return_value=process), \
                mock.patch.object(netkit.os, 'pidfd_open', return_value=77), \
                mock.patch.object(netkit.os, 'set_blocking'), mock.patch.object(netkit.os, 'close'), \
                mock.patch.object(netkit.os, 'read', return_value=b'x' * 16384), \
                mock.patch.object(netkit.selectors, 'DefaultSelector', Selector), \
                mock.patch.object(netkit.signal, 'pidfd_send_signal') as pinned_signal, \
                self.assertRaisesRegex(netkit.Error, 'output exceeds limit'):
            RUN(['/fixture/command'])
        pinned_signal.assert_called_once_with(77, signal.SIGKILL)
        process.wait.assert_called_once_with(timeout=3)


class SSHHostHandoffTests(unittest.TestCase):
    def invoke(self, *, replaced=False):
        root = types.SimpleNamespace(st_mode=0o40700, st_uid=0)
        def info(fd):
            if fd == 10:
                return types.SimpleNamespace(st_mode=0o100600, st_uid=0, st_gid=0, st_nlink=1)
            return types.SimpleNamespace(st_mode=0o40755, st_uid=0, st_dev=2,
                                         st_ino=99 if replaced and fd == 12 else 12)
        identity = mock.mock_open(read_data=b'2:12\n')
        identity.return_value.fileno.return_value = 10
        with mock.patch.object(ssh.sys, 'argv', ['/usr/bin/su', '-l', 'alice', '-c', 'id']), \
                mock.patch.object(ssh.os, 'geteuid', return_value=0), \
                mock.patch.object(ssh.Path, 'lstat', return_value=root), \
                mock.patch.object(ssh.os, 'open', side_effect=[10, 11, 12, 14]), \
                mock.patch.object(ssh.os, 'fdopen', identity), \
                mock.patch.object(ssh.os, 'fstat', side_effect=info), \
                mock.patch.object(ssh.fcntl, 'ioctl', side_effect=[ssh.os.CLONE_NEWNET, ssh.os.CLONE_NEWNS]), \
                mock.patch.object(ssh.os, 'setns') as enter, \
                mock.patch.object(ssh.os, 'fchdir') as root_fd, mock.patch.object(ssh.os, 'chroot') as chroot, \
                mock.patch.object(ssh.os, 'chdir'), mock.patch.object(ssh.os, 'close') as close, \
                mock.patch.object(ssh.os, 'execv') as execute:
            if replaced:
                with self.assertRaisesRegex(RuntimeError, 'namespace changed'):
                    ssh.main()
                enter.assert_not_called()
                execute.assert_not_called()
            else:
                ssh.main()
                self.assertEqual(enter.call_args_list, [mock.call(11, ssh.os.CLONE_NEWNET), mock.call(12, ssh.os.CLONE_NEWNS)])
                root_fd.assert_called_once_with(14)
                chroot.assert_called_once_with('.')
                execute.assert_called_once_with('/usr/bin/su', ['/usr/bin/su', '-l', 'alice', '-c', 'id'])
                self.assertEqual(close.call_args_list, [mock.call(11), mock.call(12), mock.call(14)])

    def test_both_namespaces_and_host_root_are_restored_before_native_pam(self):
        self.invoke()

    def test_changed_init_namespace_is_rejected_before_any_namespace_change(self):
        self.invoke(replaced=True)


class FirewallIntegrationTests(unittest.TestCase):
    def test_transport_rules_are_absent_without_overlay(self):
        self.assertEqual(firewall.tailscale_netkit_rules({}, 'input', 'forward'), [])

    def test_transport_overlay_rejects_wildcards_and_public_dns(self):
        value = {'interface': 'tailscale0', 'physical_interfaces': ['eth0', 'wifi0'],
                 'dns_host_address': '127.0.0.1', 'dns_host_port': 53053, 'udp_port': 41641}
        for replacement in ({'physical_interfaces': ['en*', 'wifi0']},
                            {'dns_host_address': '0.0.0.0'}, {'udp_port': True}):
            with self.subTest(replacement=replacement), self.assertRaises(firewall.PolicyError):
                firewall.tailscale_netkit_rules({'tailscale_netkit': {**value, **replacement}}, 'input', 'forward')


if __name__ == '__main__':
    unittest.main()
