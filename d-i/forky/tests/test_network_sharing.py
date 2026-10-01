"""Offline NFS configuration, firewall, menu, confinement and failure tests.

No live mount, service start, module load, export, firewall update or sysctl
write is performed. Root-only filesystem tests use disposable private trees.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import ipaddress
import itertools
import json
import os
from pathlib import Path
import pwd
import grp
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
PROFILES = SEED / 'hosts/profiles'


def module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    loader.exec_module(result)
    return result


NFS = module('network_sharing_installer_test', SEED / 'scripts/late/network-sharing.py')
MENU = module('network_sharing_menu_test', TARGET / 'usr/local/bin/labwc-network-sharing')
REPORT = module('network_sharing_report_test', TARGET / 'usr/local/libexec/network-sharing-report')
NFT = module('network_sharing_nft_test', TARGET / 'usr/local/sbin/nft-policy-generate.py')


def profile(path=None, **overrides):
    path = path or PROFILES / 'btrfs-de.env'
    result = subprocess.run(['/bin/sh', '-c', 'set -a; . "$1"; . "$2"; env -0',
                             'profile-test', str(path), str(SEED / 'hosts/installer/account.env')],
                            check=True, capture_output=True)
    values = dict(field.decode().split('=', 1) for field in result.stdout.split(b'\0') if b'=' in field)
    values.update(overrides)
    return values


class SettingsTests(unittest.TestCase):
    def test_all_ten_profiles_have_complete_safe_defaults(self):
        profiles = sorted(PROFILES.glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            with self.subTest(profile=path.name):
                settings = NFS.Settings.from_environment(profile(path))
                self.assertFalse(settings.active)
                self.assertEqual(settings['NETWORK_SHARING_ROOT_PATH'], '/data/sharing')
                self.assertFalse(settings.enabled('NFS_SERVER_BIND_ENABLE'))
                self.assertFalse(settings.enabled('NFS_CLIENT_BIND_ENABLE'))

    def test_exact_cidr_coverage_and_permissions_all_profiles(self):
        expected = {str(ipaddress.ip_address('192.168.50.' + str(i))): mode
                    for start, end, mode in ((82, 100, 'rw'), (112, 122, 'ro'), (212, 222, 'rw'))
                    for i in range(start, end + 1)}
        for path in PROFILES.glob('*.env'):
            peers = NFS.Settings.from_environment(profile(path)).peers
            actual = {str(ip): mode for cidr, mode in peers for ip in ipaddress.ip_network(cidr)}
            self.assertEqual(actual, expected, path.name)
            self.assertEqual(sum(ipaddress.ip_network(cidr).num_addresses for cidr, _ in peers), 41)

    def test_all_valid_role_and_bind_combinations(self):
        for server, client in itertools.product(range(3), repeat=2):
            for ro in ('true', 'false'):
                with self.subTest(server=server, client=client, ro=ro):
                    values = profile(NFS_SERVER_ENABLE=str(server > 0).lower(),
                                     NFS_CLIENT_ENABLE=str(client > 0).lower(),
                                     NFS_SERVER_BIND_ENABLE=str(server == 2).lower(),
                                     NFS_CLIENT_BIND_ENABLE=str(client == 2).lower(),
                                     NFS_CLIENT_READ_ONLY=ro)
                    s = NFS.Settings.from_environment(values)
                    entries = NFS.fstab_entries(s)
                    self.assertEqual(len(entries), int(client > 0) + int(server == 2) + int(client == 2))
                    if client:
                        source, where, kind, options, *_ = entries[0].split()
                        self.assertEqual(source, '192.168.50.212:/')
                        self.assertEqual(where, '/data/sharing/nfs-client')
                        self.assertEqual(kind, 'nfs')
                        self.assertTrue({'hard', '_netdev', 'nofail', 'sec=sys', 'resvport', 'nosuid', 'nodev', 'noexec', 'x-systemd.automount'} <= set(options.split(',')))
                        self.assertNotIn('soft', options)
                        self.assertIn('ro' if ro == 'true' else 'rw', options.split(','))
                    for entry in entries[int(client > 0):]:
                        self.assertIn('x-systemd.requires-mounts-for=' + entry.split()[0], entry)

    def test_path_and_policy_injections_are_rejected(self):
        invalid = {
            'NETWORK_SHARING_ROOT_PATH': ['/etc/sharing', '/', '/data/../etc', '/data/share path', '/data//share', '/data/x%y', '/data/x\nroot'],
            'NFS_SERVER_PATH': ['/data/sharing', '/data/sharing/nfs-client', '/data/sharing/nfs-client/child', '/etc/passwd'],
            'NFS_CLIENT_HOME_BIND_PATH': ['../.ssh', '/home/x', 'Documents', 'Sharing//x', 'Sharing/nfs-server'],
            'NFS_CLIENT_TARGET_IP': ['127.0.0.1', '::1', '8.8.8.8', '192.168.50.2;true', '192.168.50.212/24'],
            'NFS_SHARED_GID': ['0', '65534', '-1', '2050\n'],
            'NFS_SHARED_GROUP': ['root', 'nogroup', '-bad', 'group;sh'],
            'NFS_SERVER_ENABLE': ['yes', '1', 'TRUE', 'true\n'],
            'NFS_INTERFACES': ['*', 'eth+', 'lo', '', 'eth0\"'],
            'NFS_CLIENT_VERSION': ['3', '4', '4.0', '4.2,soft'],
            'NFS_IDMAP_DOMAIN': ['-bad.example', 'a..b', 'a\nb', 'A.local'],
            'NFS_CLIENT_DEPS': ['nfs-common', '--option', 'nfs-common $(touch /tmp/attack)'],
            'NFS_CLIENT_BIND_PATH': ['Different/path'],
            'NFS_TCP_RMEM': ['8192 4096 32768', '4096 131072 67108864', '1 2', '-1 8192 16384'],
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    NFS.Settings.from_environment(profile(**{key: value}))

    def test_bind_needs_role_and_nfs_needs_firewall(self):
        for options in ({'NFS_CLIENT_BIND_ENABLE': 'true'}, {'NFS_SERVER_BIND_ENABLE': 'true'},
                        {'NFS_CLIENT_ENABLE': 'true', 'NFT_PROFILE': 'none'},
                        {'NFS_SERVER_ENABLE': 'true', 'NFT_PROFILE': 'none'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                NFS.Settings.from_environment(profile(**options))

    def test_exports_never_widen_implicitly(self):
        baseline = profile()['NFS_SERVER_EXPORTS']
        for line in (baseline.replace('root_squash', 'no_root_squash'), baseline.replace('sync,', 'async,'),
                     baseline.replace('secure,', 'insecure,'), baseline.replace('sec=sys', 'sec=none'),
                     baseline.replace('192.168.50.82/31', '*'), baseline.replace('192.168.50.82/31', '192.168.50.83/31'),
                     baseline + ' ' + baseline.split()[1], baseline + '\n',
                     baseline.replace('rw,sync', 'rw,crossmnt,sync'), baseline.replace('rw,sync', 'rw,ro,sync')):
            with self.subTest(line=line), self.assertRaises(ValueError):
                NFS.parse_exports(line, '/data/sharing/nfs-server')

    def test_unit_names_match_systemd_escape(self):
        for path in ('/data/sharing/nfs-client', '/home/test/Sharing/nfs-client', '/srv/.hidden/nfs.foo', '/data/a_b/c-d'):
            for suffix in ('mount', 'automount'):
                result = subprocess.run(['systemd-escape', '--path', '--suffix=' + suffix, path], text=True, capture_output=True, check=True)
                self.assertEqual(NFS.unit_name(path, suffix), result.stdout.strip())

    def test_escaped_unit_name_length_is_validated_before_publication(self):
        with self.assertRaisesRegex(ValueError, 'unit-name limit'):
            NFS.Settings.from_environment(profile(NFS_CLIENT_HOME_BIND_PATH='Sharing/' + '-' * 64,
                                                  NFS_CLIENT_BIND_PATH='Sharing/' + '-' * 64))

    def test_template_rendering_has_no_unresolved_tokens(self):
        settings = NFS.Settings.from_environment(profile(NFS_SERVER_ENABLE='true', NFS_CLIENT_ENABLE='true'))
        for path in (TARGET/'etc/exports.tmpl', TARGET/'etc/idmapd.conf.tmpl', TARGET/'etc/nfs.conf.d/60-network-sharing.conf.tmpl',
                     TARGET/'etc/sysctl.d/60-network-sharing.conf.tmpl', TARGET/'etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl',
                     TARGET/'etc/systemd/system/network-sharing-report.service.tmpl'):
            rendered = NFS.render(path, settings)
            self.assertNotRegex(rendered, r'__[A-Z][A-Z0-9_]+__', str(path))
        text = NFS.render(TARGET/'etc/sysctl.d/60-network-sharing.conf.tmpl', settings)
        self.assertIn('net.core.wmem_max = 16777216', text)
        self.assertNotIn('wmen_max', text)


class CommandLifecycleTests(unittest.TestCase):
    def test_command_success_and_failure_are_preserved(self):
        NFS.run([sys.executable, '-I', '-c', 'raise SystemExit(0)'], timeout=10)
        with self.assertRaises(subprocess.CalledProcessError) as error:
            NFS.run([sys.executable, '-I', '-c', 'raise SystemExit(37)'], timeout=10)
        self.assertEqual(error.exception.returncode, 37)

    def test_timeout_signals_only_an_unreaped_owned_group(self):
        for already_reaped in (False, True):
            with self.subTest(already_reaped=already_reaped):
                child = mock.MagicMock()
                child.__enter__.return_value = child
                child.pid = 12345
                child.returncode = 0 if already_reaped else None
                child.wait.side_effect = subprocess.TimeoutExpired(['fixture'], 1)
                with mock.patch.object(NFS.subprocess, 'Popen', return_value=child) as launch, \
                     mock.patch.object(NFS.os, 'killpg') as kill:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        NFS.run(['/fixture'], timeout=1)
                self.assertTrue(launch.call_args.kwargs['start_new_session'])
                if already_reaped:
                    kill.assert_not_called()
                else:
                    kill.assert_called_once_with(child.pid, NFS.signal.SIGKILL)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux child-subreaper fixture required')
    def test_timeout_stops_a_real_descendant_and_reaps_the_command(self):
        # Subreaper state exists only in this disposable probe, not in the
        # installer or unittest runner. All adopted fixture children are reaped.
        script = r'''import ctypes,json,os,runpy,subprocess,sys,tempfile,time
from pathlib import Path
# The fixture alone becomes a subreaper, so it can reap the adopted grandchild.
libc=ctypes.CDLL(None,use_errno=True)
if libc.prctl(36,1,0,0,0):
    raise OSError(ctypes.get_errno(), 'fixture subreaper')
helper=runpy.run_path(sys.argv[1],run_name='timeout_test')
with tempfile.TemporaryDirectory() as tmp:
    marker=Path(tmp)/'late-write'
    ready=Path(tmp)/'ready'
    release=Path(tmp)/'release'
    code="""import os,sys,time
from pathlib import Path
if os.fork() == 0:
    Path(sys.argv[2]).write_text(str(os.getpid()))
    deadline=time.monotonic()+15
    while not Path(sys.argv[3]).exists() and time.monotonic()<deadline:
        time.sleep(.01)
    Path(sys.argv[1]).write_text('unsafe late child')
    os._exit(0)
time.sleep(20)
"""
    real_popen=subprocess.Popen
    def launch(*args,**kwargs):
        child=real_popen(*args,**kwargs)
        # Begin the tested deadline only after the process hierarchy exists.
        # This makes the regression independent of machine startup/load speed.
        deadline=time.monotonic()+10
        while not ready.exists():
            if child.poll() is not None or time.monotonic()>=deadline:
                child.kill()
                child.wait()
                raise AssertionError('fixture did not start')
            time.sleep(.01)
        return child
    subprocess.Popen=launch
    timed_out=False
    try:
        helper['run']([sys.executable,'-I','-c',code,str(marker),str(ready),str(release)],timeout=.1)
    except subprocess.TimeoutExpired:
        timed_out=True
    finally:
        subprocess.Popen=real_popen
        release.touch()
    statuses=[]
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        try:
            pid,status=os.waitpid(-1,os.WNOHANG)
        except ChildProcessError:
            break
        if pid:
            statuses.append(os.waitstatus_to_exitcode(status))
        else:
            time.sleep(.02)
    else:
        raise AssertionError('fixture child survived')
    print(json.dumps({'timed_out':timed_out,'started':ready.exists(),
                      'late_write':marker.exists(),'statuses':statuses}))
'''
        result = subprocess.run([sys.executable, '-I', '-c', script,
                                 str(SEED/'scripts/late/network-sharing.py')],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'timed_out': True, 'started': True, 'late_write': False, 'statuses': [-9]})


class FollowUpPolicyTests(unittest.TestCase):
    def test_multiple_leading_slashes_are_not_normalized_paths(self):
        for path in ('//', '//data/sharing', '///export'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'normalized'):
                NFS.normalized_path(path, allow_root=True)
        with self.assertRaises(ValueError):
            NFS.Settings.from_environment(profile(NFS_CLIENT_EXPORT_PATH='//export'))

    def test_bind_roles_require_immutable_flag_tool_package(self):
        for role in ('SERVER', 'CLIENT'):
            values = profile(**{f'NFS_{role}_ENABLE': 'true'})
            values[f'NFS_{role}_DEPS'] = ' '.join(p for p in values[f'NFS_{role}_DEPS'].split() if p != 'e2fsprogs')
            # No home bind: no immutable-flag requirement.
            NFS.Settings.from_environment(values)
            values[f'NFS_{role}_BIND_ENABLE'] = 'true'
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'e2fsprogs'):
                NFS.Settings.from_environment(values)

    def test_every_profile_supplies_bind_dependency_for_both_roles(self):
        for path in PROFILES.glob('*.env'):
            values = profile(path)
            for role in ('SERVER', 'CLIENT'):
                self.assertIn('e2fsprogs', values[f'NFS_{role}_DEPS'].split(), (path.name, role))

    def test_server_explicitly_disables_every_legacy_protocol(self):
        import configparser
        settings = NFS.Settings.from_environment(profile(NFS_SERVER_ENABLE='true'))
        config = configparser.ConfigParser()
        config.read_string(NFS.render(TARGET/'etc/nfs.conf.d/60-network-sharing.conf.tmpl', settings))
        for key in ('vers2', 'vers3', 'vers4.0', 'udp', 'rdma'):
            self.assertEqual(config['nfsd'][key], 'n', key)
        for key in ('vers4', 'vers4.1', 'vers4.2', 'tcp'):
            self.assertEqual(config['nfsd'][key], 'y', key)

    def test_mountd_can_use_native_kernel_netlink_caches(self):
        text = (TARGET/'etc/systemd/system/nfs-mountd.service.d/60-network-sharing.conf').read_text()
        lines = [line for line in text.splitlines() if line.startswith('RestrictAddressFamilies=')]
        self.assertEqual(lines, ['RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK'])
        self.assertIn('NoNewPrivileges=yes', text)
        self.assertIn('ProtectSystem=full', text)

    def test_server_requires_completed_nfs_and_managed_firewall_configuration(self):
        text = (TARGET/'etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl').read_text()
        expected = ['/etc/network-sharing/config.json', '/etc/nfs.conf.d/60-network-sharing.conf',
                    '/etc/nftables.d/20-filter.nft', '/etc/systemd/system/nftables.service.d/override.conf']
        self.assertEqual([line.split('=', 1)[1] for line in text.splitlines() if line.startswith('AssertPathExists=')], expected)
        self.assertNotIn('ConditionPathExists=', text)

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'native systemd assertion checker unavailable')
    def test_native_systemd_rejects_incomplete_server_prerequisites(self):
        text = (TARGET/'etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl').read_text()
        paths = [line.split('=', 1)[1] for line in text.splitlines() if line.startswith('AssertPathExists=')]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = [root/path.lstrip('/') for path in paths]
            def evaluate():
                return subprocess.run(['systemd-analyze', 'condition', *['AssertPathExists='+str(p) for p in files]],
                                      text=True, capture_output=True, timeout=15)
            self.assertNotEqual(evaluate().returncode, 0)
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            result = evaluate()
            self.assertEqual(result.returncode, 0, result.stderr)
            for path in files:
                with self.subTest(missing=path.relative_to(root)):
                    path.unlink()
                    self.assertNotEqual(evaluate().returncode, 0)
                    path.touch()

    def test_export_refresh_errors_fail_start_and_reload(self):
        text = (TARGET/'etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl').read_text()
        for key in ('ExecStartPre', 'ExecReload'):
            values = [line.split('=', 1)[1] for line in text.splitlines() if line.startswith(key + '=')]
            self.assertEqual(values, ['', '/usr/sbin/exportfs -r'])
        self.assertNotIn('ExecStart=', text)
        self.assertNotIn('ExecStop=', text)


class FirewallTests(unittest.TestCase):
    def render(self, path, server, client, shell='/bin/sh'):
        values = profile(path, NFS_SERVER_ENABLE=server, NFS_CLIENT_ENABLE=client)
        script = '. "$1"; . "$2"; network_sharing_nftables_placeholder_map'
        argv = ([shell, 'sh'] if shell.endswith('busybox') else [shell])
        result = subprocess.run([*argv, '-c', script, 'map', str(SEED/'scripts/late/security.sh'), str(SEED/'scripts/late/network-sharing.sh')],
                                text=True, capture_output=True, env=values, check=True)
        tokens = dict(line.split('=', 1) for line in result.stdout.splitlines())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = (TARGET/'etc/nftables/profiles/desktop.yml.tmpl').read_text()
            for key in ('MANAGED_NETWORK_ETHERNET_IFACE', 'MANAGED_NETWORK_WIFI_IFACE'):
                text = text.replace('__INSTALLER_' + key + '__', values[key])
            (root/'profile.yml').write_text(text)
            overlays = []
            for name in ('nfs-server', 'nfs-client'):
                text = (TARGET/f'etc/nftables/services/{name}.yml.tmpl').read_text()
                for key, value in tokens.items():
                    text = text.replace('__INSTALLER_' + key + '__', value)
                self.assertNotIn('__INSTALLER_', text)
                destination = root/(name + '.yml')
                destination.write_text(text)
                overlays.append(destination)
            context = NFT.RenderContext()
            policy = NFT.load_policy(root/'profile.yml', overlays, False, context)
            NFT.validate_unresolved(policy)
            maps = NFT.build_define_maps(policy, context)
            return NFT.render_filter(policy, maps, context, False)

    def test_all_profiles_and_roles_render_exact_nfs_policy(self):
        for path in PROFILES.glob('*.env'):
            for server, client in itertools.product(('false', 'true'), repeat=2):
                with self.subTest(profile=path.name, server=server, client=client):
                    text = self.render(path, server, client)
                    inbound = [line for line in text.splitlines() if 'service nfs_server inbound' in line]
                    outbound = [line for line in text.splitlines() if 'service nfs_client outbound' in line]
                    self.assertEqual(bool(inbound), server == 'true')
                    self.assertEqual(bool(outbound), client == 'true')
                    for line in inbound:
                        self.assertIn('iifname', line)
                        self.assertIn('tcp dport 2049', line)
                        self.assertIn('ip saddr', line)
                        self.assertNotIn('ip6 ', line)
                    if inbound:
                        for cidr, _ in NFS.Settings.from_environment(profile(path)).peers:
                            self.assertIn(cidr, '\n'.join(inbound))
                        self.assertNotIn('192.168.50.0/24', '\n'.join(inbound))
                    for line in outbound:
                        self.assertIn('ip daddr 192.168.50.212/32', line)
                        self.assertIn('oifname', line)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox unavailable')
    def test_busybox_map_matches_dash(self):
        path = PROFILES/'btrfs-de.env'
        self.assertEqual(self.render(path, 'true', 'true'), self.render(path, 'true', 'true', shutil.which('busybox')))


class PublicationAndGeneratorTests(unittest.TestCase):
    def test_build_gate_matches_target_policy_for_every_profile(self):
        checker = module('network_sharing_build_test', SEED.parents[1]/'tools/check_network_sharing.py')
        self.assertEqual(checker.check(SEED), 10)
        for path in PROFILES.glob('*.env'):
            values = checker.read_values(path, checker.read_values(SEED/'hosts/installer/account.env'))
            expected = NFS.Settings.from_environment(profile(path)).values
            actual = NFS.Settings.from_environment(values).values
            self.assertEqual(actual, expected)

    def test_publication_parser_rejects_commands_duplicates_and_forward_references(self):
        checker = module('network_sharing_build_reject_test', SEED.parents[1]/'tools/check_network_sharing.py')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'profile.env'
            for text in ('NFS_SERVER_ENABLE="$(touch /tmp/never-execute)"',
                         'NFS_SERVER_ENABLE="true"\nNFS_SERVER_ENABLE="false"',
                         'NFS_SERVER_PATH="${UNDEFINED}/server"',
                         'NFS_SERVER_ENABLE="`id`"'):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    checker.read_values(path)

    @unittest.skipUnless(Path('/usr/lib/systemd/system-generators/systemd-fstab-generator').is_file(), 'native fstab generator unavailable')
    def test_native_generator_produces_real_dependencies_and_timeouts(self):
        settings = NFS.Settings.from_environment(profile(NFS_SERVER_ENABLE='true', NFS_CLIENT_ENABLE='true',
                                                         NFS_SERVER_BIND_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true'))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fstab = root/'fstab'
            fstab.write_text('\n'.join(NFS.fstab_entries(settings))+'\n')
            for directory in ('normal', 'early', 'late'):
                (root/directory).mkdir()
            result = subprocess.run(['/usr/lib/systemd/system-generators/systemd-fstab-generator',
                                     str(root/'normal'), str(root/'early'), str(root/'late')],
                                    env={**os.environ, 'SYSTEMD_FSTAB': str(fstab), 'SYSTEMD_SYSROOT_FSTAB': '/dev/null',
                                         'SYSTEMD_IN_INITRD': '0'}, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            generated = root/'normal'
            mount = (generated/NFS.unit_name(settings['NFS_CLIENT_PATH'])).read_text()
            self.assertIn('Requires=nfs-client.target nftables.service', mount)
            self.assertIn('After=nfs-client.target nftables.service', mount)
            self.assertIn('TimeoutSec=30s', mount)
            for role in ('SERVER', 'CLIENT'):
                home = settings['ACCOUNT_HOME']+'/'+settings[f'NFS_{role}_HOME_BIND_PATH']
                self.assertIn('RequiresMountsFor='+settings[f'NFS_{role}_PATH'], (generated/NFS.unit_name(home)).read_text())
            self.assertTrue((generated/NFS.unit_name(settings['NFS_CLIENT_PATH'], 'automount')).is_file())


class MarkerTests(unittest.TestCase):
    def test_preserve_unmanaged_text_and_replace_only_one_block(self):
        text = '# before\n' + NFS.BEGIN + '\nold\n' + NFS.END + '\n# after\n'
        self.assertEqual(NFS.without_managed_block(text), '# before\n# after\n')
        self.assertEqual(NFS.without_managed_block('# comments\n'), '# comments\n')

    def test_corrupt_marker_pairs_fail(self):
        for text in (NFS.BEGIN, NFS.END, NFS.END+'\n'+NFS.BEGIN+'\n',
                     NFS.BEGIN+' extra\n'+NFS.END, 'x'+NFS.BEGIN+'\n'+NFS.END,
                     NFS.BEGIN+'\n'+NFS.BEGIN+'\n'+NFS.END):
            with self.subTest(text=text), self.assertRaises(ValueError):
                NFS.without_managed_block(text)


@unittest.skipUnless(os.geteuid() == 0, 'private root-owned filesystem fixtures require root')
class TargetFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nfs-test-', dir='/root')
        self.root = Path(self.tmp.name)
        for directory in ('etc', 'usr/sbin', 'usr/bin', 'home/mcramer'):
            (self.root/directory).mkdir(parents=True, exist_ok=True)
        os.chown(self.root/'home/mcramer', 1000, 1000)
        (self.root/'home/mcramer').chmod(0o700)
        (self.root/'etc/fstab').write_text('# existing\nUUID=unchanged / ext4 defaults 0 1\n')
        self.account = pwd.struct_passwd(('mcramer', 'x', 1000, 1000, '', '/home/mcramer', '/bin/bash'))
        self.group = grp.struct_group(('nfs-sharing', 'x', 2050, ['mcramer']))
        def mapped(value):
            path = Path(value)
            if path.is_absolute() and not path.is_relative_to(self.root):
                return self.root / str(path).lstrip('/')
            return path
        self.stack = []
        for patch in (mock.patch.object(NFS, 'Path', side_effect=mapped),
                      mock.patch.object(NFS, 'run'), mock.patch.object(NFS.pwd, 'getpwnam', return_value=self.account),
                      mock.patch.object(NFS.grp, 'getgrnam', return_value=self.group)):
            self.stack.append(patch)
        self.path_mock, self.run, _, _ = [patch.start() for patch in self.stack]

    def tearDown(self):
        for patch in reversed(self.stack):
            patch.stop()
        self.tmp.cleanup()

    def configure(self, **options):
        settings = NFS.Settings.from_environment(profile(**options))
        NFS.configure(settings, TARGET)
        return settings

    def test_disabled_still_creates_root_without_packages_or_services(self):
        self.configure()
        self.assertTrue((self.root/'data/sharing').is_dir())
        self.assertFalse((self.root/'etc/exports').exists())
        self.run.assert_not_called()
        self.assertEqual((self.root/'etc/fstab').read_text(), '# existing\nUUID=unchanged / ext4 defaults 0 1\n')
        self.assertFalse(json.loads((self.root/'etc/network-sharing/config.json').read_text())['server_enabled'])

    def test_both_roles_binds_idempotence_permissions_and_no_live_calls(self):
        settings = dict(NFS_SERVER_ENABLE='true', NFS_CLIENT_ENABLE='true', NFS_SERVER_BIND_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true')
        self.configure(**settings)
        fstab = (self.root/'etc/fstab').read_text()
        exports = (self.root/'etc/exports').read_text()
        self.configure(**settings)
        self.assertEqual(fstab, (self.root/'etc/fstab').read_text())
        self.assertEqual(exports, (self.root/'etc/exports').read_text())
        self.assertEqual(stat.S_IMODE((self.root/'data/sharing/nfs-server').stat().st_mode), 0o2770)
        self.assertEqual((self.root/'data/sharing/nfs-server').stat().st_gid, 2050)
        self.assertEqual(stat.S_IMODE((self.root/'data/sharing/nfs-client').stat().st_mode), 0)
        self.assertEqual(stat.S_IMODE((self.root/'home/mcramer/Sharing/nfs-client').stat().st_mode), 0)
        self.assertEqual((self.root/'etc/modules-load.d/60-network-sharing.conf').read_text(), 'sunrpc\nnfs\nnfsv4\nnfsd\n')
        modprobe = (self.root/'etc/modprobe.d/60-network-sharing.conf').read_text()
        self.assertIn('options nfs nfs4_disable_idmapping=0', modprobe)
        self.assertIn('options nfsd nfs4_disable_idmapping=0', modprobe)
        self.assertIn('/usr/sbin/nfsidmap -t 600 %k %d', (self.root/'etc/request-key.d/id_resolver.conf').read_text())
        for call in self.run.call_args_list:
            argv = call.args[0]
            if argv[0].endswith('systemctl'):
                self.assertIn('--root=/', argv)
                self.assertFalse({'start', 'restart', 'daemon-reload', '--now'} & set(argv))
            self.assertNotIn(argv[0], ['/usr/bin/mount', '/usr/sbin/exportfs', '/usr/sbin/sysctl', '/usr/sbin/modprobe'])
        dropin = self.root/'etc/systemd/system'/('home-mcramer-Sharing-nfs\\x2dclient.mount.d')/'60-network-sharing.conf'
        self.assertIn('BindsTo=data-sharing-nfs\\x2dclient.mount', dropin.read_text())

    def test_private_installer_umask_still_publishes_traversable_directories(self):
        previous = os.umask(0o077)
        try:
            self.configure(NFS_SERVER_ENABLE='true', NFS_SERVER_BIND_ENABLE='true')
        finally:
            os.umask(previous)
        for relative in ('data/sharing', 'etc/network-sharing', 'home/mcramer/Sharing'):
            self.assertEqual(stat.S_IMODE((self.root/relative).stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.root/'home/mcramer/Sharing/nfs-server').stat().st_mode), 0)

    def test_server_only_never_installs_client_mount_or_upcall(self):
        self.configure(NFS_SERVER_ENABLE='true')
        self.assertTrue((self.root/'etc/exports').exists())
        self.assertFalse((self.root/'etc/request-key.d/id_resolver.conf').exists())
        self.assertEqual((self.root/'etc/modules-load.d/60-network-sharing.conf').read_text(), 'sunrpc\nnfsd\n')
        self.assertNotIn(NFS.BEGIN, (self.root/'etc/fstab').read_text())

    def test_client_only_never_installs_export_or_server_daemon_policy(self):
        self.configure(NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true', NFS_CLIENT_READ_ONLY='true')
        self.assertFalse((self.root/'etc/exports').exists())
        self.assertFalse((self.root/'etc/nfs.conf.d/60-network-sharing.conf').exists())
        self.assertFalse((self.root/'etc/systemd/system/nfs-server.service.d').exists())
        self.assertEqual((self.root/'etc/modules-load.d/60-network-sharing.conf').read_text(), 'sunrpc\nnfs\nnfsv4\n')
        fstab = (self.root/'etc/fstab').read_text()
        self.assertIn('ro,hard', fstab)
        self.assertIn('30s,ro', fstab)

    def test_changed_profile_rerun_refused(self):
        self.configure()
        with self.assertRaisesRegex(ValueError, 'configured differently'):
            self.configure(NFS_CLIENT_ENABLE='true')
        self.run.assert_not_called()

    def test_existing_exports_and_mounts_are_not_silently_replaced(self):
        exports = self.root/'etc/exports'
        exports.write_text('/old *(rw)\n')
        with self.assertRaisesRegex(ValueError, 'unmanaged exports'):
            self.configure(NFS_SERVER_ENABLE='true')
        self.assertEqual(exports.read_text(), '/old *(rw)\n')
        self.run.assert_not_called()

    def test_conflicting_fstab_fails_before_package_install(self):
        (self.root/'etc/fstab').write_text('/dev/other /data/sharing/nfs-client ext4 defaults 0 0\n')
        with self.assertRaisesRegex(ValueError, 'unmanaged fstab'):
            self.configure(NFS_CLIENT_ENABLE='true')
        self.run.assert_not_called()

    def test_alias_fstab_destinations_fail_before_package_install(self):
        for destination in ('/data//sharing/nfs-client', '//data/sharing/nfs-client',
                            '/data/sharing/./nfs-client', '/data/other/../sharing/nfs-client',
                            r'/data/sharing/nfs\055client', r'/data/sharing/\156fs-client'):
            (self.root/'etc/fstab').write_text('/srv/existing ' + destination + ' none bind,nofail 0 0\n')
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, 'unmanaged fstab'):
                self.configure(NFS_CLIENT_ENABLE='true')
            self.run.assert_not_called()
            self.assertFalse((self.root/'etc/network-sharing/config.json').exists())

    def test_symlinked_root_is_rejected(self):
        (self.root/'data').mkdir()
        (self.root/'data/sharing').symlink_to(self.root/'etc', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.configure()
        self.run.assert_not_called()

    def test_mount_destination_must_be_empty(self):
        path = self.root/'data/sharing/nfs-client'
        path.mkdir(parents=True)
        (path/'do-not-hide').write_text('content')
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            self.configure(NFS_CLIENT_ENABLE='true')
        self.assertEqual((path/'do-not-hide').read_text(), 'content')

    def test_home_symlinks_and_user_owned_parents_rejected(self):
        path = self.root/'home/mcramer/Sharing'
        path.symlink_to(self.root/'etc', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.configure(NFS_SERVER_ENABLE='true', NFS_SERVER_BIND_ENABLE='true')
        self.assertFalse((self.root/'etc/nfs-server').exists())

    def test_configuration_symlinks_hardlinks_and_fifo_rejected(self):
        path = self.root/'etc/unsafe'
        real = self.root/'etc/real'
        real.write_text('keep')
        path.symlink_to(real)
        with self.assertRaises((OSError, ValueError)):
            NFS.atomic_write(path, 'overwrite')
        path.unlink()
        os.link(real, path)
        with self.assertRaises(ValueError):
            NFS.atomic_write(path, 'overwrite')
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            NFS.read_regular(path)
        self.assertEqual(real.read_text(), 'keep')

    def test_home_bind_parent_locked_once_after_all_endpoints_exist(self):
        locked = []
        def check(argv, **kwargs):
            if argv[0] == '/usr/bin/chattr':
                self.assertEqual(argv, ['/usr/bin/chattr', '+i', '--', str(self.root/'home/mcramer/Sharing')])
                for role in ('server', 'client'):
                    self.assertEqual(stat.S_IMODE((self.root/f'home/mcramer/Sharing/nfs-{role}').stat().st_mode), 0)
                self.assertNotIn(NFS.BEGIN, (self.root/'etc/fstab').read_text())
                self.assertFalse((self.root/'etc/network-sharing/config.json').exists())
                locked.append(argv[-1])
        self.run.side_effect = check
        self.configure(NFS_SERVER_ENABLE='true', NFS_CLIENT_ENABLE='true',
                       NFS_SERVER_BIND_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true')
        self.assertEqual(len(locked), 1)

    def test_distinct_home_bind_parents_locked_in_stable_order(self):
        self.configure(NFS_SERVER_ENABLE='true', NFS_CLIENT_ENABLE='true',
                       NFS_SERVER_BIND_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true',
                       NFS_SERVER_HOME_BIND_PATH='ServerShare/nested/server',
                       NFS_CLIENT_HOME_BIND_PATH='ClientShare/nested/client',
                       NFS_CLIENT_BIND_PATH='ClientShare/nested/client')
        calls = [call.args[0] for call in self.run.call_args_list if call.args[0][0] == '/usr/bin/chattr']
        self.assertEqual(calls, [['/usr/bin/chattr', '+i', '--', str(self.root/'home/mcramer'/name)]
                                 for name in ('ClientShare', 'ServerShare')])

    def test_home_bind_lock_failure_prevents_mount_publication_and_enablement(self):
        def fail_lock(argv, **kwargs):
            if argv[0] == '/usr/bin/chattr':
                raise subprocess.CalledProcessError(1, argv)
        self.run.side_effect = fail_lock
        with self.assertRaises(subprocess.CalledProcessError):
            self.configure(NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true')
        self.assertNotIn(NFS.BEGIN, (self.root/'etc/fstab').read_text())
        self.assertFalse((self.root/'etc/network-sharing/config.json').exists())
        self.assertFalse(any(call.args[0][0] == '/usr/bin/systemctl' for call in self.run.call_args_list))

    def test_no_home_bind_means_no_immutable_directory_change(self):
        self.configure(NFS_SERVER_ENABLE='true', NFS_CLIENT_ENABLE='true')
        self.assertFalse(any(call.args[0][0] == '/usr/bin/chattr' for call in self.run.call_args_list))
        self.assertFalse((self.root/'home/mcramer/Sharing').exists())

    def test_existing_user_owned_home_bind_parent_is_not_taken_over(self):
        path = self.root/'home/mcramer/Sharing'
        path.mkdir()
        os.chown(path, 1000, 1000)
        with self.assertRaisesRegex(ValueError, 'root-owned'):
            self.configure(NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true')
        self.assertEqual(path.stat().st_uid, 1000)
        self.assertFalse(any(call.args[0][0] == '/usr/bin/chattr' for call in self.run.call_args_list))

    def test_export_root_acl_replaces_named_entries_without_recursion(self):
        self.configure(NFS_SERVER_ENABLE='true')
        calls = [call.args[0] for call in self.run.call_args_list if call.args[0][0] == '/usr/bin/setfacl']
        self.assertEqual(calls, [['/usr/bin/setfacl', '--set',
                                 'u::rwx,g::rwx,o::---,d:u::rwx,d:g::rwx,d:m::rwx,d:o::---',
                                 '--', '/data/sharing/nfs-server']])

    def test_server_start_guard_is_installed_before_packages_can_enable_units(self):
        def fail_apt(argv, **kwargs):
            if argv[0] == '/usr/bin/apt-get':
                dropin = self.root/'etc/systemd/system/nfs-server.service.d/60-network-sharing.conf'
                self.assertIn('AssertPathExists=/etc/network-sharing/config.json', dropin.read_text())
                self.assertFalse((self.root/'etc/network-sharing/config.json').exists())
                raise subprocess.CalledProcessError(1, argv)
        self.run.side_effect = fail_apt
        with self.assertRaises(subprocess.CalledProcessError):
            self.configure(NFS_SERVER_ENABLE='true')
        self.assertFalse((self.root/'etc/exports').exists())
        self.assertNotIn(NFS.BEGIN, (self.root/'etc/fstab').read_text())

    def test_package_policy_restored_on_failure(self):
        policy = self.root/'usr/sbin/policy-rc.d'
        policy.write_text('#!/bin/sh\nexit 77\n')
        policy.chmod(0o751)
        self.run.side_effect = subprocess.CalledProcessError(1, ['apt-get'])
        with self.assertRaises(subprocess.CalledProcessError):
            self.configure(NFS_CLIENT_ENABLE='true')
        self.assertEqual(policy.read_text(), '#!/bin/sh\nexit 77\n')
        self.assertEqual(stat.S_IMODE(policy.stat().st_mode), 0o751)
        self.assertFalse(list(policy.parent.glob('.network-sharing-policy-*')))


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.config = dict(version=1, server_enabled=True, client_enabled=True,
                           client_mount='data-sharing-nfs\\x2dclient.mount',
                           client_automount='data-sharing-nfs\\x2dclient.automount',
                           client_bind_mount='home-user-Sharing-nfs\\x2dclient.mount',
                           client_bind_automount='home-user-Sharing-nfs\\x2dclient.automount', server_bind_mount='')

    def test_menu_catalog_includes_required_actions(self):
        for label in ('Connect to NFS Server', 'Check Connected NFS Clients', 'Disconnect from NFS Server', 'Reload NFS Exports'):
            self.assertIn(label, MENU.ACTIONS)
        text = (TARGET/'usr/local/bin/labwc-computer-management').read_text()
        self.assertIn("'Network Sharing': ('labwc-network-sharing',)", text)

    def test_disconnect_cancel_has_no_effect(self):
        with mock.patch.object(MENU, 'confirm', return_value=False), mock.patch.object(MENU, 'systemctl') as command:
            MENU.action(self.config, 'Disconnect from NFS Server')
            command.assert_not_called()

    def test_disconnect_stops_both_automounts_and_mounts_no_force(self):
        with mock.patch.object(MENU, 'confirm', return_value=True), mock.patch.object(MENU, 'systemctl') as command, mock.patch.object(MENU, 'completed'):
            MENU.action(self.config, 'Disconnect from NFS Server')
            command.assert_called_once_with(self.config, 'stop', [self.config[key] for key in ('client_bind_automount', 'client_bind_mount', 'client_automount', 'client_mount')])

    def test_disabled_role_does_not_trigger_privileged_action(self):
        self.config['client_enabled'] = False
        with mock.patch.object(MENU, 'show'), mock.patch.object(MENU, 'systemctl') as command:
            MENU.action(self.config, 'Connect to NFS Server')
            command.assert_not_called()

    def test_systemctl_rejects_other_units_and_verbs(self):
        for verb, units in [('start', ['sshd.service']), ('enable', ['nfs-server.service']), ('start', ['--root=/']), ('stop', [])]:
            with self.subTest(verb=verb, units=units), self.assertRaises(ValueError):
                MENU.systemctl(self.config, verb, units)

    def test_failed_report_never_uses_stale_data(self):
        failure = subprocess.CompletedProcess([], 1, stdout='denied')
        with mock.patch.object(MENU, 'systemctl', return_value=failure), mock.patch.object(MENU, 'read_json') as reader:
            with self.assertRaises(RuntimeError):
                MENU.report(self.config)
            reader.assert_not_called()

    def test_skipped_successful_report_start_cannot_return_stale_data(self):
        stale = {'version': 1, 'created_utc': '2000-01-01T00:00:00+00:00'}
        with mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')), \
             mock.patch.object(MENU, 'read_json', return_value=stale):
            with self.assertRaisesRegex(RuntimeError, 'fresh report'):
                MENU.report(self.config)

    def test_successful_report_accepts_only_fresh_timestamped_data(self):
        from datetime import datetime, timezone
        def freshly_published(path):
            return {'version': 1, 'created_utc': datetime.now(timezone.utc).isoformat()}
        with mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')), \
             mock.patch.object(MENU, 'read_json', side_effect=freshly_published):
            self.assertEqual(MENU.report(self.config)['version'], 1)

    def test_picker_cancellation_and_unknown_output_are_not_actions(self):
        for status, output in ((1, ''), (0, '/bin/sh\n'), (0, 'Connect to NFS Server\nextra\n')):
            with mock.patch.object(MENU.subprocess, 'run', return_value=subprocess.CompletedProcess([], status, output)):
                self.assertIsNone(MENU.choose(list(MENU.ACTIONS), 'Network Sharing'))

    def test_command_environment_drops_bus_and_loader_injections(self):
        with mock.patch.dict(os.environ, {'DBUS_SYSTEM_BUS_ADDRESS': 'unix:path=/evil', 'LD_PRELOAD': '/evil', 'SYSTEMD_HOST': 'evil'}), mock.patch.object(MENU.subprocess, 'run') as run:
            MENU.command(['/usr/bin/systemctl', 'show'], 5)
            env = run.call_args.kwargs['env']
            self.assertNotIn('DBUS_SYSTEM_BUS_ADDRESS', env)
            self.assertNotIn('LD_PRELOAD', env)
            self.assertNotIn('SYSTEMD_HOST', env)
            self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
            self.assertNotIn('shell', run.call_args.kwargs)


class ReporterTests(unittest.TestCase):
    def test_missing_kernel_records_are_not_reported_as_zero_clients(self):
        with tempfile.TemporaryDirectory() as temp:
            result = REPORT.clients(Path(temp)/'missing')
            self.assertIn('unavailable', result)

    def test_client_cap_numeric_names_symlinks_and_control_characters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(REPORT.MAX_CLIENTS + 1):
                (root/str(index)).mkdir()
                (root/str(index)/'info').write_text('address: 192.168.50.82\nname: attacker\x1b[31m\n')
            (root/'nonnumeric').mkdir()
            (root/'9999').symlink_to(root/'0', target_is_directory=True)
            result = REPORT.clients(root)
            self.assertTrue(result['truncated'])
            self.assertEqual(len(result['entries']), REPORT.MAX_CLIENTS)
            self.assertNotIn('\x1b', json.dumps(result, ensure_ascii=False))
            for item in result['entries']:
                self.assertRegex(item['kernel_id'], r'^\d+$')

    def test_bounded_reads_report_truncation_and_refuse_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'info'
            path.write_text('a'*100)
            self.assertEqual(REPORT.read_bounded(path, 10), 'a'*10+'\n[truncated]')
            link = Path(temp)/'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                REPORT.read_bounded(link)


class IntegrationWiringTests(unittest.TestCase):
    def test_both_storage_families_and_installer_dispatch(self):
        for name in ('btrfs-family.sh', 'f2fs-family.sh'):
            text = (SEED/'scripts/late'/name).read_text()
            self.assertIn('configure_target_network_sharing', text)
            self.assertLess(text.index('configure_target_network_sharing'), text.index('configure_target_apparmor_auditd'))
        for path in (SEED/'scripts/late/dispatch.sh', SEED/'hooks/installer/late_command.sh'):
            self.assertIn('network-sharing', path.read_text())
        self.assertIn('labwc-network-sharing 0755', (SEED/'scripts/desktop/components/target-assets.sh').read_text())

    def test_apparmor_registry_and_service_transition(self):
        self.assertIn('__DESKTOP_APPARMOR_STATE__ required network-sharing -', (TARGET/'etc/apparmor/modes.conf.tmpl').read_text())
        self.assertIn('network-sharing', (SEED/'scripts/late/security.sh').read_text())
        unit = (TARGET/'etc/systemd/system/network-sharing-report.service.tmpl').read_text()
        for text in ('AppArmorProfile=network-sharing-report', 'CapabilityBoundingSet=', 'TimeoutStartSec=20s', 'ProtectSystem=strict', 'KillMode=control-group'):
            self.assertIn(text, unit)
        self.assertNotIn('PrivateNetwork=yes', unit)
        self.assertIn('/usr/local/bin/labwc-network-sharing rPx,', (TARGET/'etc/apparmor.d/desktop-wrappers.tmpl').read_text())

    def test_cross_profile_child_timeout_and_completion_permissions(self):
        policy = (TARGET/'etc/apparmor.d/network-sharing').read_text()
        self.assertIn('signal (send) set=(term, kill) peer=labwc-network-sharing//{systemctl,journalctl},', policy)
        self.assertEqual(policy.count('signal (receive) set=(term, kill) peer=labwc-network-sharing,'), 2)
        wrappers = (TARGET/'etc/apparmor.d/desktop-wrappers.tmpl').read_text()
        for name in ('labwc-fuzzel', 'labwc-fzf-menu'):
            section = wrappers.split('profile ' + name + ' /', 1)[1].split('\n}', 1)[0]
            self.assertIn('signal (send) set=(chld) peer=labwc-network-sharing,', section)
            self.assertIn('signal (receive) set=(term, kill) peer=labwc-network-sharing,', section)

    @unittest.skipUnless(shutil.which('apparmor_parser'), 'AppArmor parser unavailable')
    def test_apparmor_profiles_parse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree('/etc/apparmor.d', root, dirs_exist_ok=True)
            for directory in ('abstractions', 'local'):
                if (TARGET/'etc/apparmor.d'/directory).is_dir():
                    shutil.copytree(TARGET/'etc/apparmor.d'/directory, root/directory, dirs_exist_ok=True)
            path = root/'network-sharing'
            path.write_text((TARGET/'etc/apparmor.d/network-sharing').read_text())
            result = subprocess.run(['apparmor_parser', '-Q', '-T', '-I', str(root), str(path)], text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
