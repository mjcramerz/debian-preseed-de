"""Offline NFS configuration, firewall, menu, confinement and failure tests.

No live mount, service start, module load, export, firewall update or sysctl
write is performed. Root-only filesystem tests use disposable private trees.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import errno
import ipaddress
import itertools
import io
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
from theme_fixture import render_theme_defaults, theme_values
from fuzzel_fixture import geometry_environment, wrapper_script

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
IDENTITY = module('network_sharing_identity_test', TARGET / 'usr/local/libexec/network-sharing-identity')
NFT = module('network_sharing_nft_test', TARGET / 'usr/local/sbin/nft-policy-generate.py')


def profile(path=None, **overrides):
    path = path or PROFILES / 'btrfs-de.env'
    hosting = SEED / 'hosts/installer/hosting.env'
    shared = set(re.findall(r'^(NFS_[A-Z_]+)=', hosting.read_text(), re.M))
    before = '\n'.join(key + '=' + shlex.quote(value) for key, value in overrides.items())
    after = '\n'.join(key + '=' + shlex.quote(value) for key, value in overrides.items() if key in shared)
    script = 'set -a; . "$1"\n' + before + '\n. "$2"\n' + after + '\n. "$3"; env -0'
    result = subprocess.run(['/bin/sh', '-c', script, 'profile-test', str(path), str(hosting),
                             str(SEED / 'hosts/installer/account.env')], check=True, capture_output=True,
                            env={**os.environ, 'ACCOUNT_USERNAME': 'mcramer', 'ACCOUNT_HOME': '/home/mcramer',
                                 'SYSTEM_DOMAIN': 'validation.invalid'})
    return dict(field.decode().split('=', 1) for field in result.stdout.split(b'\0') if b'=' in field)


class SettingsTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('gi'), 'native GIO fixture unavailable')
    def test_native_glib_filters_bind_entries_despite_gvfs_show(self):
        import gi
        gi.require_version('GioUnix', '2.0')
        from gi.repository import GioUnix
        if not hasattr(GioUnix, 'mount_points_get_from_file'):
            self.skipTest('native GIO cannot parse an alternate fstab fixture')
        with tempfile.TemporaryDirectory(prefix='nfs-gvfs-fstab-') as directory:
            fstab = Path(directory)/'fstab'
            fstab.write_text('/srv/share /home/fixture/Sharing/nfs-client none bind,auto,x-gvfs-show 0 0\n'
                             '192.168.50.82:/ /srv/client nfs auto,x-gvfs-show 0 0\n', encoding='utf-8')
            points, _ = GioUnix.mount_points_get_from_file(str(fstab))
            self.assertEqual([point.get_mount_path() for point in points], ['/srv/client'])

    def test_fstab_format_preserves_semantics_comments_and_alignment(self):
        records = ('# fixture\nUUID=11111111-1111-1111-1111-111111111111 / btrfs rw,subvol=@ 0 0\n'
                   'UUID=11111111-1111-1111-1111-111111111111 /usr/local btrfs rw,subvol=@local 0 0\n'
                   'UUID=22222222-2222-2222-2222-222222222222 /home ext4 defaults 0 2\n\n'
                   '# network\n/srv/lan /home/user/Sharing/server none bind,nosuid,nodev,noexec 0 0 # keep me\n')
        formatted = NFS.format_fstab(records)
        self.assertEqual(formatted, NFS.format_fstab(formatted))
        self.assertEqual([line.split() for line in formatted.splitlines() if line and not line.startswith('#')],
                         [line.split() for line in records.splitlines() if line and not line.startswith('#')])
        self.assertIn('\n\nUUID=222', formatted)
        columns = [tuple(match.start() for match in list(re.finditer(r'\S+', line))[:6])
                   for line in formatted.splitlines() if line and not line.startswith('#')]
        self.assertTrue(all(column == columns[0] for column in columns))
        with self.assertRaises(ValueError):
            NFS.format_fstab('bad record\n')

    def test_home_bind_visibility_and_bookmarks_follow_configured_paths(self):
        settings = NFS.Settings.from_environment(profile(
            NFS_SERVER_ENABLE='true', NFS_SERVER_BIND_ENABLE='true',
            NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true',
            ACCOUNT_HOME='/home/lanuser', NFS_SERVER_HOME_BIND_PATH='LAN/server',
            NFS_CLIENT_HOME_BIND_PATH='LAN/client'))
        for row in NFS.fstab_entries(settings)[1:]:
            self.assertIn('x-gvfs-show', row.split()[3].split(','))
        self.assertEqual(NFS.home_bind_bookmarks(settings),
                         'file:///home/lanuser/LAN/server nfs-server\nfile:///home/lanuser/LAN/client nfs-client\n')

    def test_shared_policy_lives_only_in_hosting_and_every_profile_has_a_port(self):
        hosting = (SEED/'hosts/installer/hosting.env').read_text()
        shared = ('NFS_SERVER_RW_OPTIONS', 'NFS_SERVER_RO_OPTIONS', 'NFS_SERVER_APT_DEPS',
                  'NFS_CLIENT_APT_DEPS', 'NFS_CLIENT_VERSION', 'NFS_SERVER_EXPORTS',
                  'NFS_SHARED_GROUP', 'NFS_SHARED_GID', 'NFS_ACCOUNT_UID', 'NFS_ACCOUNT_GID',
                  'NFS_MNT_SERVER_BIND_HOME_OPTS', 'NFS_MNT_CLIENT_BIND_HOME_OPTS',
                  'NFS_MNT_CLIENT_TARGET_SHARE_OPTS')
        for name in shared:
            self.assertEqual(len(re.findall(r'^' + name + '=', hosting, re.M)), 1)
        for path in PROFILES.glob('*.env'):
            text = path.read_text()
            for name in (*shared, 'NFS_SERVER_DEPS', 'NFS_CLIENT_DEPS'):
                self.assertNotRegex(text, r'(?m)^' + name + '=')
            self.assertEqual(re.findall(r'^NFS_SERVER_PORT="([0-9]+)"$', text, re.M), ['2049'])

    def test_custom_paths_port_timeout_and_configured_order_reach_fstab(self):
        values = profile(NFS_SERVER_ENABLE='true', NFS_CLIENT_ENABLE='true',
                         NFS_SERVER_BIND_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true',
                         NETWORK_SHARING_ROOT_PATH='/srv/lan-sharing',
                         NFS_SERVER_PATH='/srv/lan-sharing/server', NFS_CLIENT_PATH='/srv/lan-sharing/client',
                         ACCOUNT_USERNAME='lanuser', ACCOUNT_HOME='/home/lanuser',
                         NFS_SERVER_HOME_BIND_PATH='LAN/server', NFS_CLIENT_HOME_BIND_PATH='LAN/client',
                         NFS_SERVER_PORT='32049', NFS_CLIENT_MOUNT_TIMEOUT='45')
        # Configured ordering is used verbatim, rather than silently replacing
        # administrator-supplied options with a separate hard-coded list.
        for name in ('NFS_MNT_SERVER_BIND_HOME_OPTS', 'NFS_MNT_CLIENT_BIND_HOME_OPTS',
                     'NFS_MNT_CLIENT_TARGET_SHARE_OPTS'):
            values[name] = ','.join(reversed(values[name].split(',')))
        settings = NFS.Settings.from_environment(values)
        entries = [entry.split() for entry in NFS.fstab_entries(settings)]
        self.assertEqual([entry[1] for entry in entries],
                         ['/srv/lan-sharing/client', '/home/lanuser/LAN/server', '/home/lanuser/LAN/client'])
        for entry, name in zip(entries, ('NFS_MNT_CLIENT_TARGET_SHARE_OPTS',
                                         'NFS_MNT_SERVER_BIND_HOME_OPTS', 'NFS_MNT_CLIENT_BIND_HOME_OPTS')):
            self.assertEqual(entry[3], values[name])
        self.assertIn('port=32049', entries[0][3])
        self.assertIn('x-systemd.mount-timeout=45s', entries[0][3])
        self.assertIn('port = 32049\n', NFS.render(TARGET/'etc/nfs.conf.d/60-network-sharing.conf.tmpl', settings))

    def test_mount_policy_cannot_remove_guards_or_override_transport(self):
        values = profile()
        invalid = []
        for name in ('NFS_MNT_SERVER_BIND_HOME_OPTS', 'NFS_MNT_CLIENT_BIND_HOME_OPTS',
                     'NFS_MNT_CLIENT_TARGET_SHARE_OPTS'):
            for option in values[name].split(','):
                invalid.append((name, ','.join(o for o in values[name].split(',') if o != option)))
            for extra in ('exec', 'suid', 'dev', 'soft', 'rw,ro', 'auto', 'noauto', 'x-systemd.automount', 'x-systemd.idle-timeout=1s',
                          'x-systemd.requires=/tmp/unsafe', 'noexec', 'rw\nroot'):
                invalid.append((name, values[name] + ',' + extra))
        for name, value in invalid:
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                NFS.Settings.from_environment({**values, name: value})
        for port in ('0', '111', '65536', '02049', '2049,tcp', '2049\n'):
            with self.subTest(port=port), self.assertRaises(ValueError):
                NFS.Settings.from_environment(profile(NFS_SERVER_PORT=port))

    def test_read_only_source_policy_is_inherited_by_the_home_bind(self):
        values = profile(NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true')
        values['NFS_MNT_CLIENT_TARGET_SHARE_OPTS'] = values['NFS_MNT_CLIENT_TARGET_SHARE_OPTS'].replace('rw,', 'ro,')
        entries = NFS.fstab_entries(NFS.Settings.from_environment(values))
        for entry in entries:
            self.assertIn('ro', entry.split()[3].split(','))
            self.assertNotIn('rw', entry.split()[3].split(','))

    def test_client_mount_policy_requires_auto_and_rejects_noauto(self):
        values = profile(NFS_CLIENT_ENABLE='true', NFS_CLIENT_BIND_ENABLE='true')
        for name in ('NFS_MNT_CLIENT_TARGET_SHARE_OPTS', 'NFS_MNT_CLIENT_BIND_HOME_OPTS'):
            with self.subTest(name=name):
                options = values[name].split(',')
                self.assertIn('auto', options)
                self.assertNotIn('noauto', options)
                disabled = ','.join('noauto' if option == 'auto' else option for option in options)
                with self.assertRaises(ValueError):
                    NFS.Settings.from_environment({**values, name: disabled})

    def test_literal_lan_export_address_is_an_exact_host_peer(self):
        line = '/data/sharing/nfs-server 192.168.50.82(' + profile()['NFS_SERVER_RW_OPTIONS'] + ')'
        self.assertEqual(NFS.parse_exports(line, '/data/sharing/nfs-server'), [('192.168.50.82/32', 'rw')])
        for replacement in ('8.8.8.8', '127.0.0.1', 'lan.example', '*'):
            with self.subTest(peer=replacement), self.assertRaises(ValueError):
                NFS.parse_exports(line.replace('192.168.50.82', replacement), '/data/sharing/nfs-server')

    def test_all_ten_profiles_have_complete_safe_defaults(self):
        profiles = sorted(PROFILES.glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            with self.subTest(profile=path.name):
                settings = NFS.Settings.from_environment(profile(path))
                # The supplied p15s profile deliberately enables its server
                # and home bind. Preserve that profile's installed policy.
                server = path.stem == 'btrfs-de-p15s'
                client = path.stem == 'btrfs-de-flex-duo'
                self.assertEqual(settings.enabled('NFS_SERVER_ENABLE'), server)
                self.assertEqual(settings.enabled('NFS_CLIENT_ENABLE'), client)
                self.assertEqual(settings['NETWORK_SHARING_ROOT_PATH'], '/data/sharing')
                self.assertEqual(settings.enabled('NFS_SERVER_BIND_ENABLE'), server)
                self.assertEqual(settings.enabled('NFS_CLIENT_BIND_ENABLE'), client)

    def test_exact_cidr_coverage_and_permissions_all_profiles(self):
        expected = {str(ipaddress.ip_address('192.168.50.' + str(i))): mode
                    for start, end, mode in ((82, 100, 'rw'), (112, 122, 'ro'), (212, 222, 'rw'))
                    for i in range(start, end + 1)}
        for path in PROFILES.glob('*.env'):
            peers = NFS.Settings.from_environment(profile(path)).peers
            actual = {str(ip): mode for cidr, mode in peers for ip in ipaddress.ip_network(cidr)}
            self.assertEqual(actual, expected, path.name)
            self.assertEqual(sum(ipaddress.ip_network(cidr).num_addresses for cidr, _ in peers), 41)

    def test_domain_is_derived_from_runtime_identity_and_bind_path_is_canonical(self):
        for path in PROFILES.glob('*.env'):
            values = profile(path, SYSTEM_DOMAIN='Lab.Example')
            settings = NFS.Settings.from_environment(values)
            rendered = NFS.render(TARGET/'etc/idmapd.conf.tmpl', settings)
            self.assertIn('Domain = sharing.lab.example\n', rendered)
            self.assertIn('No-Strip = none\n', rendered)
            self.assertEqual(settings['NFS_ACCOUNT_UID'], '1000')
            self.assertEqual(settings['NFS_ACCOUNT_GID'], '1000')
            for obsolete in ('NFS_IDMAP_DOMAIN', 'NFS_CLIENT_BIND_PATH'):
                self.assertNotIn(obsolete, settings.values)
                self.assertNotIn(obsolete+'=', path.read_text())

    def test_domain_length_includes_the_sharing_prefix_and_has_no_runtime_fallback(self):
        # 4 labels plus 3 separators: 245 bytes, 253 with sharing. prefixed.
        maximum = '.'.join(['a'*63]*3+['b'*53])
        NFS.Settings.from_environment(profile(SYSTEM_DOMAIN=maximum))
        with self.assertRaises(ValueError):
            NFS.Settings.from_environment(profile(SYSTEM_DOMAIN=maximum+'c'))
        values = profile()
        del values['SYSTEM_DOMAIN']
        with self.assertRaisesRegex(ValueError, 'SYSTEM_DOMAIN'):
            NFS.Settings.from_environment(values)

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
                        self.assertTrue({'hard', '_netdev', 'nofail', 'auto', 'sec=sys', 'resvport', 'nosuid', 'nodev', 'noexec'} <= set(options.split(',')))
                        self.assertNotIn('noauto', options.split(','))
                        self.assertNotIn('x-systemd.automount', options)
                        self.assertNotIn('soft', options)
                        self.assertIn('ro' if ro == 'true' else 'rw', options.split(','))
                    for entry in entries[int(client > 0):]:
                        self.assertIn('x-systemd.requires-mounts-for=' + entry.split()[0], entry)
                        if entry.split()[0] == s['NFS_CLIENT_PATH']:
                            self.assertIn('auto', entry.split()[3].split(','))
                            self.assertNotIn('noauto', entry.split()[3].split(','))
                            self.assertNotIn('x-systemd.automount', entry)

    def test_published_configuration_and_menu_use_mount_units_without_autofs(self):
        for server, client, bind in itertools.product(('false', 'true'), repeat=3):
            if client == 'false' and bind == 'true':
                continue
            settings = NFS.Settings.from_environment(profile(
                NFS_SERVER_ENABLE=server, NFS_CLIENT_ENABLE=client, NFS_CLIENT_BIND_ENABLE=bind))
            config = NFS.public_config(settings)
            with self.subTest(server=server, client=client, bind=bind), \
                    mock.patch.object(MENU, 'read_json', return_value=config):
                self.assertEqual(MENU.load_config(), config)
                self.assertEqual(config['version'], 2)
                self.assertFalse(any('automount' in key for key in config))
                self.assertFalse(any(unit.endswith('.automount') for unit in MENU.units(config)))

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
            'SYSTEM_DOMAIN': ['', '-bad.example', 'a..b', 'a\nb', 'label-' + '.example', 'a.' + 'b' * 64],
            'NFS_ACCOUNT_UID': ['0', '65534', '-1'],
            'NFS_ACCOUNT_GID': ['0', '65534', '2050'],
            'NFS_CLIENT_APT_DEPS': ['nfs-common', '--option', 'nfs-common $(touch /tmp/attack)'],
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
                     baseline.replace('subtree_check', 'no_subtree_check'),
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
            NFS.Settings.from_environment(profile(NFS_CLIENT_HOME_BIND_PATH='Sharing/' + '-' * 64))

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
            values[f'NFS_{role}_APT_DEPS'] = ' '.join(p for p in values[f'NFS_{role}_APT_DEPS'].split() if p != 'e2fsprogs')
            # No home bind: no immutable-flag requirement.
            NFS.Settings.from_environment(values)
            values[f'NFS_{role}_BIND_ENABLE'] = 'true'
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'e2fsprogs'):
                NFS.Settings.from_environment(values)

    def test_every_profile_supplies_bind_dependency_for_both_roles(self):
        for path in PROFILES.glob('*.env'):
            values = profile(path)
            for role in ('SERVER', 'CLIENT'):
                self.assertIn('e2fsprogs', values[f'NFS_{role}_APT_DEPS'].split(), (path.name, role))

    def test_server_explicitly_disables_every_legacy_protocol(self):
        import configparser
        settings = NFS.Settings.from_environment(profile(NFS_SERVER_ENABLE='true'))
        config = configparser.ConfigParser()
        config.read_string(NFS.render(TARGET/'etc/nfs.conf.d/60-network-sharing.conf.tmpl', settings))
        for key in ('vers2', 'vers3', 'vers4.0', 'udp'):
            self.assertEqual(config['nfsd'][key], 'n', key)
        for key in ('rdma', 'rdma-port'):
            self.assertNotIn(key, config['nfsd'], key)
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
            probe = evaluate()
            if ('Failed to initialize unit search paths' in probe.stderr
                    or "Failed to create directory '/run/systemd/':" in probe.stderr):
                self.skipTest('native systemd condition checker cannot initialize in this environment')
            self.assertNotEqual(probe.returncode, 0)
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
            self.assertEqual(values, ['', '/usr/sbin/exportfs -r'] if key == 'ExecStartPre' else
                             ['', '/usr/local/libexec/network-sharing-identity', '/usr/sbin/exportfs -r'])

    def test_server_uses_packaged_procfs_start_and_stop(self):
        text = (TARGET/'etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl').read_text()
        for key, command in (('ExecStart', '/usr/sbin/rpc.nfsd'), ('ExecStop', '/usr/sbin/rpc.nfsd 0')):
            values = [line.split('=', 1)[1] for line in text.splitlines() if line.startswith(key + '=')]
            self.assertEqual(values, ['', command])
        self.assertNotIn('nfsdctl', '\n'.join(line for line in text.splitlines() if not line.startswith('#')))
        self.assertNotIn('ExecStopPost=', text)


class FirewallTests(unittest.TestCase):
    def test_custom_port_reaches_both_guards_without_allowlist_bypass(self):
        text = self.render(PROFILES/'btrfs-de.env', 'true', 'true', NFS_SERVER_PORT='32049')
        nfs_rules = [line for line in text.splitlines()
                     if 'nfs_server' in line or 'nfs_client' in line or 'allowlist guard' in line]
        guarded = [line for line in nfs_rules if 'tcp dport' in line]
        self.assertTrue(guarded)
        self.assertTrue(all('tcp dport 32049' in line for line in guarded))
        self.assertEqual(self.guard_verdict(text, 'allow_nfs_server_inbound', '192.168.50.82', 'eth0'), 'return')
        for peer, interface in (('192.168.50.81', 'eth0'), ('8.8.8.8', 'eth0'),
                                ('192.168.50.82', 'tailscale0'), ('fd00::1', 'eth0')):
            self.assertEqual(self.guard_verdict(text, 'allow_nfs_server_inbound', peer, interface), 'drop')

    def render(self, path, server, client, shell='/bin/sh', base='desktop', **overrides):
        values = profile(path, NFS_SERVER_ENABLE=server, NFS_CLIENT_ENABLE=client, **overrides)
        script = '. "$1"; . "$2"; network_sharing_nftables_placeholder_map'
        argv = ([shell, 'sh'] if shell.endswith('busybox') else [shell])
        result = subprocess.run([*argv, '-c', script, 'map', str(SEED/'scripts/late/security.sh'), str(SEED/'scripts/late/network-sharing.sh')],
                                text=True, capture_output=True, env=values, check=True)
        tokens = dict(line.split('=', 1) for line in result.stdout.splitlines())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = (TARGET/f'etc/nftables/profiles/{base}.yml.tmpl').read_text()
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
                    guards = [line for line in text.splitlines() if 'allowlist guard' in line]
                    self.assertEqual(len(guards), (server == 'true') + (client == 'true'))
                    for guard in guards:
                        self.assertLess(text.index(guard), text.index('ct state established,related'))
                        self.assertLess(text.index(guard), text.index('base loopback'))
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
                        self.assertIn('ip daddr ' + profile(path)['NFS_CLIENT_TARGET_IP'] + '/32', line)
                        self.assertIn('oifname', line)

    @staticmethod
    def guard_verdict(text, chain, peer, interface):
        # Evaluate the rendered NFS regular-chain matches independently of the
        # generator. This is an offline policy check, not kernel enforcement.
        address = ipaddress.ip_address(peer)
        prefix = 'add rule inet labwc_filter ' + chain + ' '
        for line in text.splitlines():
            if not line.startswith(prefix):
                continue
            rule = line[len(prefix):].split(' comment ', 1)[0]
            if rule == 'counter drop':
                return 'drop'
            match = re.fullmatch(r'(?:iifname|oifname) (.+) (ip6|ip) (?:saddr|daddr) (.+) counter return', rule)
            if not match:
                raise AssertionError('unexpected NFS guard rule: ' + rule)
            interfaces = re.findall(r'"([^"]+)"', match[1])
            networks = [ipaddress.ip_network(value.strip()) for value in match[3].strip('{} ').split(',')]
            if interface in interfaces and address.version == (6 if match[2] == 'ip6' else 4) and any(address in network for network in networks):
                return 'return'
        raise AssertionError('NFS allowlist has no terminal drop')

    def test_server_guard_preserves_exact_peers_and_blocks_wrong_interface_and_ipv6(self):
        text = self.render(PROFILES/'btrfs-de.env', 'true', 'false')
        interfaces = profile()['NFS_INTERFACES'].split()
        allowed = set(range(82, 101)) | set(range(112, 123)) | set(range(212, 223))
        for suffix in range(1, 255):
            peer = '192.168.50.' + str(suffix)
            for interface in interfaces:
                self.assertEqual(self.guard_verdict(text, 'allow_nfs_server_inbound', peer, interface),
                                 'return' if suffix in allowed else 'drop')
        for peer, interface in (('192.168.50.82', 'lo'), ('192.168.50.212', 'wg0'),
                                ('192.168.50.112', 'untrusted0'), ('fd00::82', interfaces[0])):
            self.assertEqual(self.guard_verdict(text, 'allow_nfs_server_inbound', peer, interface), 'drop')
        self.assertNotIn('ct state', '\n'.join(line for line in text.splitlines() if 'allow_nfs_server_inbound ' in line))

    def test_server_lan_ingress_has_a_real_accept_for_the_configured_port(self):
        # Inspect the actual compiled input accept, not just a return from
        # the allowlist guard. No packet or host firewall is used here.
        path = PROFILES/'btrfs-de-p15s.env'
        for base, port in itertools.product(('desktop', 'baseline'), ('2049', '32049')):
            with self.subTest(base=base, port=port):
                text = self.render(path, 'true', 'false', base=base, NFS_SERVER_PORT=port)
                rules = [line for line in text.splitlines() if 'service nfs_server inbound' in line]
                self.assertEqual(len(rules), 1)
                match = re.fullmatch(r'add rule inet labwc_filter input iifname (.+) ip saddr (.+) '
                    r'tcp dport (\d+) ct state new counter accept comment "service nfs_server inbound"', rules[0])
                self.assertIsNotNone(match, rules[0])
                interfaces = set(re.findall(r'"([^"]+)"', match[1]))
                networks = {str(ipaddress.ip_network(item.strip())) for item in match[2].strip('{} ').split(',')}
                expected = NFS.Settings.from_environment(profile(path, NFS_SERVER_PORT=port))
                self.assertEqual(interfaces, set(expected['NFS_INTERFACES'].split()))
                self.assertEqual(networks, {cidr for cidr, _ in expected.peers})
                self.assertEqual(match[3], port)
                for cidr, _ in expected.peers:
                    for peer in ipaddress.ip_network(cidr):
                        for interface in interfaces:
                            self.assertEqual(self.guard_verdict(text, 'allow_nfs_server_inbound', str(peer), interface), 'return')
                self.assertLess(text.index('allowlist guard'), text.index(rules[0]))
                self.assertNotIn('udp dport '+port, text)

    def test_enabled_server_overlay_is_selected_when_omitted_from_service_list(self):
        script = r'''
. "$1"
late_command_nftables_services() { printf '%s\n' dns-client; }
installer_selected_class_reference_is_selected() { return 1; }
nftables_tailscale_selected() { return 1; }
nftables_qemu_selected() { return 1; }
nftables_software_selected() { return 1; }
installer_info() { :; }
late_command_nftables_effective_services
'''
        for server, client in itertools.product(('false', 'true'), repeat=2):
            result = subprocess.run(['/bin/sh', '-c', script, 'nfs-overlay-fixture',
                str(SEED/'scripts/late/security.sh')],
                env={**os.environ, 'NFS_SERVER_ENABLE': server, 'NFS_CLIENT_ENABLE': client,
                     'SSH_SERVER_ENABLED': 'false'}, capture_output=True, text=True, encoding='utf-8', timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            services = result.stdout.split()
            self.assertEqual('nfs-server' in services, server == 'true')
            self.assertEqual('nfs-client' in services, client == 'true')

    def test_client_guard_is_effective_despite_general_output_accept(self):
        text = self.render(PROFILES/'btrfs-de.env', 'false', 'true')
        interface = profile()['NFS_INTERFACES'].split()[0]
        self.assertEqual(self.guard_verdict(text, 'allow_nfs_client_outbound', '192.168.50.212', interface), 'return')
        for peer, iface in (('192.168.50.211', interface), ('192.168.50.213', interface),
                            ('10.0.0.1', interface), ('fd00::212', interface),
                            ('192.168.50.212', 'lo'), ('192.168.50.212', 'wg0')):
            self.assertEqual(self.guard_verdict(text, 'allow_nfs_client_outbound', peer, iface), 'drop')
        self.assertIn('tcp dport 2049 jump allow_nfs_client_outbound', text)
        self.assertNotIn('udp dport 2049', text)

    def test_allowlist_guards_are_opt_in_and_leave_other_filtering_intact(self):
        service = {'enabled': True, 'direction': 'outbound', 'protocols': ['tcp'], 'ports': [2049],
                   'allow_to': {'ipv4': ['192.168.50.212/32'], 'interfaces': ['eth0']}}
        policy = {'services': {'nfs_client': service}, 'interfaces': {'wan': ['eth0']}}
        maps = NFT.build_define_maps(policy, NFT.RenderContext())
        base = NFT.render_filter(policy, maps, NFT.RenderContext(), False)
        self.assertNotIn('allowlist', base)
        service['enforce_allowlist'] = True
        hardened = NFT.render_filter(policy, maps, NFT.RenderContext(), False)
        remaining = '\n'.join(line for line in hardened.split('\n') if 'allow_nfs_client_outbound' not in line)
        self.assertEqual(remaining, base)
        chain = [line for line in hardened.splitlines() if line.startswith('add rule inet labwc_filter allow_nfs_client_outbound ')]
        self.assertTrue(chain)
        self.assertFalse(any('accept' in line for line in chain))

    def test_malformed_enforced_allowlists_fail_closed(self):
        baseline = {'enabled': True, 'enforce_allowlist': True, 'direction': 'outbound',
                    'protocols': ['tcp'], 'ports': [2049],
                    'allow_to': {'ipv4': ['192.168.50.212/32'], 'interfaces': ['eth0']}}
        for changes in ({'allow_to': {}}, {'allow_to': {'ipv4': ['192.168.50.212/32']}},
                        {'allow_to': {'ipv4_groups': ['missing'], 'interfaces': ['eth0']}},
                        {'ports': []}, {'source_ports': [2049]}, {'direction': 'bidirectional'},
                        {'enforce_allowlist': 'invalid'}):
            with self.subTest(changes=changes), self.assertRaises(NFT.PolicyError):
                NFT.render_filter({'services': {'nfs_client': {**baseline, **changes}}}, {}, NFT.RenderContext(), False)
        policy = {'services': {'nfs_client': baseline},
                  'nftables': {'chain_names': {'output': 'allow_nfs_client_outbound'}}}
        with self.assertRaises(NFT.PolicyError):
            NFT.render_filter(policy, {}, NFT.RenderContext(), False)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox unavailable')
    def test_busybox_map_matches_dash(self):
        path = PROFILES/'btrfs-de.env'
        self.assertEqual(self.render(path, 'true', 'true'), self.render(path, 'true', 'true', shutil.which('busybox')))


class PublicationAndGeneratorTests(unittest.TestCase):
    def test_build_gate_matches_target_policy_for_every_profile(self):
        checker = module('network_sharing_build_test', SEED.parents[1]/'tools/check_network_sharing.py')
        self.assertEqual(checker.check(SEED), 10)
        for path in PROFILES.glob('*.env'):
            values = checker.profile_values(SEED, path)
            expected = NFS.Settings.from_environment(profile(path, ACCOUNT_USERNAME='validation-user',
                                                                      ACCOUNT_HOME='/home/validation-user')).values
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
            self.assertIn('Requires=nfs-client.target nftables.service network-sharing-identity.service', mount)
            self.assertIn('After=nfs-client.target nftables.service network-sharing-identity.service', mount)
            self.assertIn('TimeoutSec=30s', mount)
            for role in ('SERVER', 'CLIENT'):
                home = settings['ACCOUNT_HOME']+'/'+settings[f'NFS_{role}_HOME_BIND_PATH']
                self.assertIn('RequiresMountsFor='+settings[f'NFS_{role}_PATH'], (generated/NFS.unit_name(home)).read_text())
            # Both client entries are wanted at boot. The bind still requires
            # the real source mount; no autofs or path unit is involved.
            self.assertFalse(list(generated.rglob('*.automount')))
            self.assertFalse(list(generated.rglob('*.path')))
            for path in (settings['NFS_CLIENT_PATH'],
                         settings['ACCOUNT_HOME']+'/'+settings['NFS_CLIENT_HOME_BIND_PATH']):
                name = NFS.unit_name(path)
                options = re.search(r'^Options=(.*)$', (generated/name).read_text(encoding='utf-8'), re.M)[1].split(',')
                self.assertIn('auto', options)
                self.assertNotIn('noauto', options)
                links = [entry for entry in generated.rglob('*') if entry.is_symlink() and
                         entry.name == name and entry.parent.name.endswith(('.wants', '.requires'))]
                self.assertEqual(links, [generated/'remote-fs.target.wants'/name], name)
            self.assertTrue((generated/'local-fs.target.wants'/NFS.unit_name(
                settings['ACCOUNT_HOME']+'/'+settings['NFS_SERVER_HOME_BIND_PATH'])).is_symlink())


@unittest.skipIf(os.geteuid() == 0, 'navigation fixture must exercise ordinary-user permissions')
class ClientDirectoryPermissionTests(unittest.TestCase):
    def test_disconnected_home_client_is_navigable_under_private_umask(self):
        for relative in ('Sharing/nfs-client', 'LAN/nested/client'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory(prefix='nfs-client-access-') as temporary:
                home = Path(temporary)/'home'
                home.mkdir(mode=0o700)
                settings = NFS.Settings.from_environment(profile(NFS_CLIENT_ENABLE='true',
                    NFS_CLIENT_BIND_ENABLE='true', NFS_CLIENT_HOME_BIND_PATH=relative))
                # Only the ownership boundary is simulated. Directory modes
                # and ordinary-user list/chdir access use the real filesystem.
                settings.values['ACCOUNT_HOME'] = str(home)
                account = pwd.struct_passwd(('fixture', 'x', os.getuid(), os.getgid(), '', str(home), '/bin/sh'))
                previous = os.umask(0o077)
                endpoint = home/relative
                try:
                    with mock.patch.object(NFS, 'trusted_parents'), mock.patch.object(NFS.os, 'chown') as chown:
                        NFS.home_bind_directory(settings, 'CLIENT', account)
                    self.assertEqual(stat.S_IMODE(endpoint.stat().st_mode), 0o755)
                    for call in chown.call_args_list:
                        self.assertEqual(call.args[1:], (0, 0))
                    self.assertEqual(list(endpoint.iterdir()), [])
                    result = subprocess.run(['/bin/sh', '-c', 'cd -- "$1" && pwd -P', 'nfs-navigation', str(endpoint)],
                                            text=True, encoding='utf-8', capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), str(endpoint))
                finally:
                    os.umask(previous)
                    if endpoint.exists():
                        endpoint.chmod(0o755)


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
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ('etc', 'usr/sbin', 'usr/bin', 'home/mcramer'):
            (self.root/directory).mkdir(parents=True, exist_ok=True)
        try:
            os.chown(self.root/'home/mcramer', 1000, 1000)
        except OSError as error:
            if error.errno in (errno.EINVAL, errno.EPERM, errno.EACCES):
                self.skipTest('runtime cannot establish the required numeric ownership fixture')
            raise
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
                      mock.patch.object(NFS.pwd, 'getpwuid', return_value=self.account),
                      mock.patch.object(NFS.grp, 'getgrnam', return_value=self.group),
                      mock.patch.object(NFS.grp, 'getgrgid', return_value=self.group)):
            self.stack.append(patch)
        self.path_mock, self.run, _, _, _, _ = [patch.start() for patch in self.stack]

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
        self.assertEqual((self.root/'data/sharing/nfs-server').stat().st_uid, 1000)
        bookmarks = (self.root/'etc/skel-desktop/.config/gtk-3.0/bookmarks').read_text()
        self.assertEqual(bookmarks, 'file:///home/mcramer/Sharing/nfs-server nfs-server\n'
                                   'file:///home/mcramer/Sharing/nfs-client nfs-client\n')
        for path in (self.root/'data/sharing/nfs-client', self.root/'home/mcramer/Sharing/nfs-client'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), (0, 0))
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
        binds = [line.split() for line in fstab.splitlines() if line.strip() and not line.startswith('#')]
        self.assertIn('ro', binds[-1][3].split(','))

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
                for role, mode in (('server', 0), ('client', 0o755)):
                    self.assertEqual(stat.S_IMODE((self.root/f'home/mcramer/Sharing/nfs-{role}').stat().st_mode), mode)
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
                       NFS_CLIENT_HOME_BIND_PATH='ClientShare/nested/client')
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
        self.config = dict(version=2, server_enabled=True, client_enabled=True,
                           client_mount='data-sharing-nfs\\x2dclient.mount',
                           client_bind_mount='home-user-Sharing-nfs\\x2dclient.mount', server_bind_mount='',
                           profile={'NFS_SHARED_GID': '2050', 'NFS_SHARED_GROUP': 'nfs-sharing'})
        groups = mock.patch.object(MENU.os, 'getgroups', return_value=[2050])
        groups.start()
        self.addCleanup(groups.stop)

    def test_stale_login_group_does_not_block_ordered_mount_retry(self):
        with mock.patch.object(MENU.os, 'getgroups', return_value=[]), \
                mock.patch.object(MENU.os, 'getgid', return_value=1000), \
                mock.patch.object(MENU, 'show') as show, \
                mock.patch.object(MENU, 'completed'), \
                mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')) as command:
            MENU.action(self.config, 'Connect to NFS Server')
        self.assertEqual(command.call_args_list, [mock.call(self.config, 'start', [self.config[key]])
                                                for key in ('client_mount', 'client_bind_mount')])
        show.assert_not_called()

    def test_menu_catalog_includes_required_actions(self):
        for label in ('Connect to NFS Server', 'Check Connected NFS Clients', 'Disconnect from NFS Server', 'Reload NFS Exports'):
            self.assertIn(label, MENU.ACTIONS)
        text = (TARGET/'usr/local/bin/labwc-computer-management').read_text()
        self.assertIn("'Network Sharing': ('labwc-network-sharing',)", text)

    def test_disconnect_cancel_has_no_effect(self):
        with mock.patch.object(MENU, 'confirm', return_value=False), mock.patch.object(MENU, 'systemctl') as command:
            MENU.action(self.config, 'Disconnect from NFS Server')
            command.assert_not_called()

    def test_disconnect_stops_home_bind_then_source_without_automounts_or_force(self):
        with mock.patch.object(MENU, 'confirm', return_value=True), mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')) as command, mock.patch.object(MENU, 'completed'):
            MENU.action(self.config, 'Disconnect from NFS Server')
            self.assertEqual(command.call_args_list, [mock.call(self.config, 'stop', [self.config[key]]) for key in ('client_bind_mount', 'client_mount')])

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
            return {'version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                    'server_enabled': True, 'client_enabled': True}
        with mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')), \
             mock.patch.object(MENU, 'read_json', side_effect=freshly_published):
            self.assertEqual(MENU.report(self.config)['version'], 1)

    def test_diagnostic_format_is_independent_of_the_new_config_format(self):
        with mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')), \
                mock.patch.object(MENU, 'read_json', return_value={'version': 2}):
            with self.assertRaisesRegex(RuntimeError, 'diagnostic format'):
                MENU.report(self.config)

    def test_connect_waits_for_remote_mount_before_starting_home_bind(self):
        with mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')) as command, mock.patch.object(MENU, 'completed'):
            MENU.action(self.config, 'Connect to NFS Server')
        self.assertEqual(command.call_args_list, [mock.call(self.config, 'start', [self.config[key]]) for key in ('client_mount', 'client_bind_mount')])

    def test_connection_and_disconnect_failures_stop_at_each_failed_job(self):
        for label, keys in (
            ('Connect to NFS Server', ('client_mount', 'client_bind_mount')),
            ('Disconnect from NFS Server', ('client_bind_mount', 'client_mount')),
        ):
            for index in range(len(keys)):
                replies = [subprocess.CompletedProcess([], 0, '')]*index + [subprocess.CompletedProcess([], 1, 'busy or denied')]
                with self.subTest(label=label, index=index), mock.patch.object(MENU, 'confirm', return_value=True), mock.patch.object(MENU, 'systemctl', side_effect=replies) as command, mock.patch.object(MENU, 'completed') as completed:
                    MENU.action(self.config, label)
                self.assertEqual(command.call_count, index+1)
                self.assertEqual(command.call_args.args[2], [self.config[keys[index]]])
                completed.assert_called_once_with(replies[-1])

    def test_client_without_home_bind_manages_only_the_remote_mount(self):
        self.config.update(client_bind_mount='')
        for label, keys, verb in (
            ('Connect to NFS Server', ('client_mount',), 'start'),
            ('Disconnect from NFS Server', ('client_mount',), 'stop'),
        ):
            with self.subTest(label=label), mock.patch.object(MENU, 'confirm', return_value=True), mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')) as command, mock.patch.object(MENU, 'completed'):
                MENU.action(self.config, label)
            self.assertEqual(command.call_args_list, [mock.call(self.config, verb, [self.config[key]]) for key in keys])

    def test_all_server_mutations_have_exact_dispatch_and_cancel_guards(self):
        for label, verb in (('Start NFS Server', 'start'), ('Stop NFS Server', 'stop'), ('Restart NFS Server', 'restart'), ('Reload NFS Exports', 'reload')):
            for confirmed in (False, True):
                with self.subTest(label=label, confirmed=confirmed), mock.patch.object(MENU, 'confirm', return_value=confirmed) as confirm, mock.patch.object(MENU, 'systemctl') as command, mock.patch.object(MENU, 'completed'):
                    MENU.action(self.config, label)
                if verb == 'start' or confirmed:
                    command.assert_called_once_with(self.config, verb, ['nfs-server.service'])
                else:
                    command.assert_not_called()
                self.assertEqual(confirm.call_count, int(verb != 'start'))

    def test_every_disabled_role_action_avoids_privileged_operations(self):
        roles = {
            'client': ('Connect to NFS Server', 'Disconnect from NFS Server'),
            'server': ('Start NFS Server', 'Stop NFS Server', 'Restart NFS Server', 'Reload NFS Exports', 'Check Connected NFS Clients', 'Show Configured Exports'),
        }
        for role, labels in roles.items():
            self.config[role+'_enabled'] = False
            for label in labels:
                with self.subTest(label=label), mock.patch.object(MENU, 'show'), mock.patch.object(MENU, 'systemctl') as command, mock.patch.object(MENU, 'report') as report:
                    MENU.action(self.config, label)
                command.assert_not_called()
                report.assert_not_called()

    def test_dependencies_are_query_only_and_other_verbs_fail_closed(self):
        for verb, selected in (
            ('stop', ['nftables.service']), ('restart', ['nfs-idmapd.service']),
            ('start', ['network-sharing-identity.service']), ('stop', ['network-sharing-report.service']),
            ('reload', [self.config['client_mount']]), ('restart', [self.config['client_mount']]),
            ('start', [self.config['client_mount'].removesuffix('.mount')+'.automount']),
            ('start', [self.config['client_bind_mount'].removesuffix('.mount')+'.automount']),
        ):
            with self.subTest(verb=verb, selected=selected), mock.patch.object(MENU, 'command') as command, self.assertRaises(ValueError):
                MENU.systemctl(self.config, verb, selected)
            command.assert_not_called()

    def test_read_only_errors_never_look_like_successful_empty_status_or_logs(self):
        self.config['profile'] = {}
        failure = subprocess.CompletedProcess([], 1, 'fixture bus or journal error')
        for label in ('Sharing Status', 'Recent NFS Logs'):
            with self.subTest(label=label), mock.patch.object(MENU, 'systemctl', return_value=failure), mock.patch.object(MENU, 'command', return_value=failure), mock.patch.object(MENU, 'show') as show:
                with self.assertRaisesRegex(RuntimeError, 'fixture bus or journal error'):
                    MENU.action(self.config, label)
            show.assert_not_called()

    def test_report_role_mismatch_is_rejected(self):
        from datetime import datetime, timezone
        stale = {'version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                 'server_enabled': False, 'client_enabled': True}
        with mock.patch.object(MENU, 'systemctl', return_value=subprocess.CompletedProcess([], 0, '')), mock.patch.object(MENU, 'read_json', side_effect=lambda path: {**stale, 'created_utc': datetime.now(timezone.utc).isoformat()}):
            with self.assertRaisesRegex(RuntimeError, 'role settings'):
                MENU.report(self.config)

    def test_configuration_error_is_visible_in_graphical_menu(self):
        with mock.patch.object(MENU.os, 'geteuid', return_value=1000), mock.patch.object(MENU, 'load_config', side_effect=ValueError('invalid config')), mock.patch.object(MENU, 'show') as show:
            self.assertEqual(MENU.main([]), 2)
        show.assert_called_once_with('Network Sharing Configuration Error', ['invalid config'])

    def test_load_config_rejects_legacy_automounts_disabled_binds_and_wrong_suffix(self):
        valid = {**self.config, 'profile': {}}
        with mock.patch.object(MENU, 'read_json', return_value=valid):
            self.assertEqual(MENU.load_config(), valid)
        for change in (
            {'version': 1}, {'client_automount': 'other.automount'}, {'client_mount': 'wrong.automount'},
            {'client_bind_automount': ''}, {'server_bind_automount': ''}, {'client_mount': ''},
            {'client_enabled': False}, {'server_enabled': False, 'server_bind_mount': 'home-test-server.mount'},
            {'client_mount': '--evil.mount'}, {'client_automount': 'one.automount\nextra.automount'},
        ):
            # Legacy trigger metadata and automatic unit types fail before
            # any privileged operation, even with otherwise valid fields.
            with self.subTest(change=change), mock.patch.object(MENU, 'read_json', return_value={**valid, **change}), self.assertRaises(ValueError):
                MENU.load_config()

    def test_status_exports_help_and_logs_dispatch_without_mutating_units(self):
        self.config.update(profile=profile(), peers=[['192.168.50.82/31', 'rw']])
        for label, title in (
            ('Sharing Status', 'Sharing Status'),
            ('Show Configured Exports', 'Configured Export Policy (not a live export listing)'),
            ('Sharing Help', 'Network Sharing Help'), ('Recent NFS Logs', 'Recent NFS Logs'),
        ):
            reply = subprocess.CompletedProcess([], 0, 'fixture status or log\n')
            with self.subTest(label=label), mock.patch.object(MENU, 'systemctl', return_value=reply) as control, mock.patch.object(MENU, 'command', return_value=reply) as command, mock.patch.object(MENU, 'show') as show:
                MENU.action(self.config, label)
            self.assertEqual(show.call_args.args[0], title)
            if label == 'Sharing Status':
                control.assert_called_once_with(self.config, 'show', MENU.units(self.config))
            else:
                control.assert_not_called()
            if label == 'Recent NFS Logs':
                self.assertEqual(command.call_args.args[0][0], '/usr/bin/journalctl')
            else:
                command.assert_not_called()

    def test_both_diagnostic_actions_show_unavailable_data_explicitly(self):
        self.config['profile'] = profile()
        data = {'version': 1, 'created_utc': '2026-10-01T00:00:00+00:00',
                'notice': 'Kernel records are not a live connection count.',
                'client_records': {'entries': [], 'unavailable': 'server stopped'},
                'client_rpc_statistics': {'unavailable': 'client module not loaded'}}
        for label in ('Check Connected NFS Clients', 'Identity Mapping and RPC Diagnostics'):
            with self.subTest(label=label), mock.patch.object(MENU, 'report', return_value=data) as report, mock.patch.object(MENU, 'show') as show:
                MENU.action(self.config, label)
            report.assert_called_once_with(self.config)
            self.assertIn('unavailable' if label.startswith('Check') else 'not loaded', '\n'.join(show.call_args.args[1]))

    def test_no_roles_does_not_start_report_or_offer_privileged_maintenance(self):
        self.config.update(server_enabled=False, client_enabled=False,
                           client_bind_mount='')
        with mock.patch.object(MENU, 'show'), mock.patch.object(MENU, 'systemctl') as control:
            self.assertIsNone(MENU.report(self.config))
        control.assert_not_called()
        for verb, selected in (('start', ['network-sharing-report.service']),
                               ('start', ['nfs-server.service']), ('start', [self.config['client_mount']])):
            with self.subTest(verb=verb, selected=selected), self.assertRaises(ValueError):
                MENU.systemctl(self.config, verb, selected)

    def test_unknown_action_and_back_cannot_mutate(self):
        with mock.patch.object(MENU, 'command') as command, self.assertRaises(ValueError):
            MENU.action(self.config, '/bin/sh')
        command.assert_not_called()
        for selected in ('Back', None):
            with mock.patch.object(MENU.os, 'geteuid', return_value=1000), mock.patch.object(MENU, 'load_config', return_value=self.config), mock.patch.object(MENU, 'choose', return_value=selected), mock.patch.object(MENU, 'action') as action:
                self.assertEqual(MENU.main([]), 0)
            action.assert_not_called()

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


class MenuIconTests(unittest.TestCase):
    ICONS = {
        'Network Sharing': ('NETWORK_SHARING', 'folder-remote'),
        'Sharing Status': ('SHARING_STATUS', 'dialog-information'),
        'Connect to NFS Server': ('CONNECT_TO_NFS_SERVER', 'network-connect'),
        'Disconnect from NFS Server': ('DISCONNECT_FROM_NFS_SERVER', 'network-disconnect'),
        'Check Connected NFS Clients': ('CHECK_CONNECTED_NFS_CLIENTS', 'network-workgroup'),
        'Start NFS Server': ('START_NFS_SERVER', 'media-playback-start'),
        'Stop NFS Server': ('STOP_NFS_SERVER', 'media-playback-stop'),
        'Reload NFS Exports': ('RELOAD_NFS_EXPORTS', 'view-refresh'),
        'Restart NFS Server': ('RESTART_NFS_SERVER', 'system-reboot'),
        'Identity Mapping and RPC Diagnostics': ('IDENTITY_MAPPING_AND_RPC_DIAGNOSTICS', 'system-search'),
        'Show Configured Exports': ('SHOW_CONFIGURED_EXPORTS', 'folder-publicshare'),
        'Recent NFS Logs': ('RECENT_NFS_LOGS', 'text-x-log'),
        'Sharing Help': ('SHARING_HELP', 'help-browser'),
        'Continue': ('CONTINUE', 'go-next'),
        'Back': ('BACK', 'go-previous'), 'Cancel': ('CANCEL', 'dialog-cancel'),
    }

    def test_native_icons_cover_every_action_and_preserve_exact_dispatch(self):
        self.assertTrue(set(MENU.ACTIONS) <= self.ICONS.keys())
        with tempfile.TemporaryDirectory(prefix='sharing-icons-') as directory:
            root = Path(directory)
            config = root/'home/.config/fuzzel'
            runtime = root/'runtime'
            config.mkdir(parents=True)
            runtime.mkdir(mode=0o700)
            for name in ('base.ini', 'fuzzel.ini', 'menu.ini', 'computer-management.ini'):
                (config/name).write_text('[main]\n')
            fake = root/'fuzzel'
            fake.write_text('''#!/usr/bin/python3
import os,sys
from pathlib import Path
data=sys.stdin.buffer.read()
Path(os.environ['CAPTURE']).write_bytes(data)
sys.stdout.buffer.write(data.split(b'\\n')[int(os.environ['SELECTED'])].split(b'\\0')[0]+b'\\n')
''')
            fake.chmod(0o700)
            wrapper = wrapper_script(root, fake)
            labels = list(self.ICONS)
            capture = root/'payload'
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(root/'home'),
                   'XDG_CONFIG_HOME': str(root/'home/.config'), 'XDG_RUNTIME_DIR': str(runtime),
                   'CAPTURE': str(capture), 'LABWC_FUZZEL_MANAGED_ICONS': '1',
                   'LABWC_FUZZEL_PALETTE': 'computer-management', **geometry_environment()}
            for index, label in enumerate(labels):
                with self.subTest(label=label):
                    result = subprocess.run(['/bin/sh', str(wrapper), 'computer-management', '--dmenu', '--prompt',
                                             'Computer Management / Network & Remote / Network Sharing'],
                                            input=''.join(item+'\n' for item in labels).encode(),
                                            env={**env, 'SELECTED': str(index)}, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.decode(), label+'\n')
            rows = capture.read_bytes().splitlines()
            self.assertEqual(rows[:-1], [(label+'\0icon\x1f'+icon).encode()
                                         for label, (_, icon) in self.ICONS.items() if label != 'Cancel'])
            # The shared graphical picker presents Cancel as Back; collision
            # decoration must still round-trip to the original Cancel value.
            cancel_label, cancel_icon = rows[-1].split(b'\0icon\x1f')
            self.assertTrue(cancel_label.startswith(b'Back'))
            self.assertEqual(cancel_icon, b'go-previous')
            self.assertFalse(list(runtime.glob('labwc-fuzzel-menu.*')))

    def test_terminal_icons_and_colors_cover_the_same_raw_actions(self):
        path = TARGET/'usr/local/bin/labwc-fzf-menu.tmpl'
        namespace = types.ModuleType('sharing_fzf_icons')
        source = render_theme_defaults(path.read_text(), {'FZF_MANAGEMENT_SHARING_STATUS_ICON_COLOR': '#123456'})
        exec(compile(source, str(path), 'exec'), namespace.__dict__)
        labels = list(self.ICONS)
        prompt = 'Computer Management / Network & Remote / Network Sharing'
        displayed = namespace.display_choices(labels, prompt)
        offered, accepted, ansi = namespace.color_choices(displayed, prompt)
        self.assertTrue(ansi)
        self.assertEqual(set(displayed.values()), set(labels))
        values = theme_values()
        for label, (key, _) in self.ICONS.items():
            with self.subTest(label=label):
                self.assertIn(label, namespace.ICONS)
                self.assertEqual(namespace.icon_for(label), values['FZF_MANAGEMENT_'+key+'_ICON_GLYPH'])
        for offered_label in offered:
            reply = subprocess.CompletedProcess([], 0, offered_label+'\n')
            with mock.patch.object(namespace.subprocess, 'run', return_value=reply):
                self.assertEqual(namespace.select(labels, prompt), (0, accepted[offered_label]))


class ReporterTests(unittest.TestCase):
    def test_legacy_or_malformed_config_never_collects_or_publishes(self):
        for config in ([], {}, {'version': 1, 'server_enabled': True, 'client_enabled': False},
                       {'version': 2, 'server_enabled': True, 'client_enabled': 'true'}):
            with self.subTest(config=config), \
                 mock.patch.object(REPORT.os, 'getuid', return_value=0), \
                 mock.patch.object(REPORT.os, 'geteuid', return_value=0), \
                 mock.patch.object(REPORT, 'require_confinement'), \
                 mock.patch.object(REPORT, 'read_bounded', return_value=json.dumps(config)), \
                 mock.patch.object(REPORT, 'collect') as collect, \
                 mock.patch.object(REPORT, 'publish') as publish:
                with self.assertRaises(ValueError):
                    REPORT.main([])
                collect.assert_not_called()
                publish.assert_not_called()

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


class IdentityPrerequisiteTests(unittest.TestCase):
    def test_export_security_and_peer_drift_are_rejected(self):
        original = self.settings['NFS_SERVER_EXPORTS']
        for text in (original.replace('root_squash', 'no_root_squash'),
                     original.replace('subtree_check', 'no_subtree_check'),
                     original.replace('secure,', 'insecure,'),
                     original.replace('192.168.50.82/31', '0.0.0.0/0'),
                     original + '\n/srv/other *(rw,no_root_squash)\n', ''):
            self.texts['exports'] = text
            with self.subTest(exports=text), self.assertRaisesRegex(ValueError, 'export policy changed'):
                IDENTITY.check(self.config)
        self.texts['exports'] = '# retained comment\n' + original + '\n'
        IDENTITY.check(self.config)

    def test_extra_exports_file_is_rejected_even_when_main_export_is_unchanged(self):
        directory = self.root/'etc/exports.d'
        directory.mkdir()
        (directory/'extra.exports').touch()
        self.texts['extra.exports'] = '/srv/other *(rw)\n'
        fields = list(directory.lstat())
        fields[4] = 0  # The private rootless fixture models a trusted directory.
        with mock.patch.object(Path, 'lstat', return_value=os.stat_result(fields)):
            with self.assertRaisesRegex(ValueError, 'unmanaged NFS export'):
                IDENTITY.check(self.config)
            self.texts['extra.exports'] = '# no active export\n'
            IDENTITY.check(self.config)

    def test_custom_server_port_must_match_effective_daemon_configuration(self):
        self.settings.values['NFS_SERVER_PORT'] = '32049'
        with self.assertRaisesRegex(ValueError, 'daemon policy changed'):
            IDENTITY.check(self.config)
        self.daemon = self.daemon.replace('port = 2049', 'port = 32049')
        IDENTITY.check(self.config)

    def test_nfsconf_rootdir_cannot_redirect_the_validated_export(self):
        original = self.daemon
        for section in ('exports', 'Exports', 'EXPORTS'):
            for rootdir in ('/srv/other', '/home', '"/srv/other"'):
                self.daemon = original + '\n[' + section + ']\nRootDir = ' + rootdir + '\n'
                with self.subTest(section=section, rootdir=rootdir), self.assertRaisesRegex(ValueError, 'export root was redirected'):
                    IDENTITY.check(self.config)
        self.daemon = original + '\n[exports]\nrootdir = /\n'
        IDENTITY.check(self.config)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SEED.parents[1])
        self.root = Path(self.tmp.name)
        self.settings = NFS.Settings.from_environment(profile(NFS_SERVER_ENABLE='true', NFS_CLIENT_ENABLE='true'))
        self.config = {'version': 2, 'profile': self.settings.values,
                       'server_enabled': True, 'client_enabled': True}
        self.account = pwd.struct_passwd(('mcramer', 'x', 1000, 1000, '', '/home/mcramer', '/bin/bash'))
        nobody = pwd.struct_passwd(('nobody', 'x', 65534, 65534, '', '/nonexistent', '/usr/sbin/nologin'))
        sharing = grp.struct_group(('nfs-sharing', 'x', 2050, ['mcramer']))
        nogroup = grp.struct_group(('nogroup', 'x', 65534, []))
        self.mapping = NFS.render(TARGET/'etc/idmapd.conf.tmpl', self.settings)
        self.daemon = NFS.render(TARGET/'etc/nfs.conf.d/60-network-sharing.conf.tmpl', self.settings)
        self.texts = {'idmapd.conf': self.mapping,
                      'exports': self.settings['NFS_SERVER_EXPORTS'] + '\n',
                      'id_resolver.conf': '# managed\ncreate id_resolver * * /usr/sbin/nfsidmap -t 600 %k %d\n'}
        self.query_impl = IDENTITY.query
        for name in ('nfs', 'nfsd'):
            path = self.root/'sys/module'/name/'parameters/nfs4_disable_idmapping'
            path.parent.mkdir(parents=True)
            path.write_text('N\n')
        (self.root/'etc/request-key.d').mkdir(parents=True)
        def mapped(value):
            path = Path(value)
            return self.root/str(path).lstrip('/') if path.is_absolute() else path
        def query(argv):
            if argv == ['/usr/sbin/nfsidmap', '-d']:
                return 'sharing.validation.invalid\n'
            if argv == ['/usr/sbin/nfsconf', '--dump']:
                return self.daemon
            raise AssertionError('unmanaged command')
        self.patches = [
            mock.patch.object(IDENTITY, 'Path', side_effect=mapped),
            mock.patch.object(IDENTITY, 'read_local', side_effect=lambda p: self.texts[p.name]),
            mock.patch.object(IDENTITY, 'query', side_effect=query),
            mock.patch.object(IDENTITY.pwd, 'getpwnam', side_effect=lambda name: self.account if name == 'mcramer' else nobody),
            mock.patch.object(IDENTITY.pwd, 'getpwuid', side_effect=lambda uid: self.account),
            mock.patch.object(IDENTITY.grp, 'getgrnam', side_effect=lambda name: sharing if name == 'nfs-sharing' else nogroup),
            mock.patch.object(IDENTITY.grp, 'getgrgid', return_value=sharing),
            mock.patch.object(IDENTITY.os, 'getgrouplist', side_effect=lambda name, gid: [1000, 2050] if name == 'mcramer' else [65534]),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def test_valid_identity_all_active_role_combinations(self):
        for server, client in ((True, False), (False, True), (True, True)):
            with self.subTest(server=server, client=client):
                IDENTITY.check({**self.config, 'server_enabled': server, 'client_enabled': client})

    def test_valid_quoted_nfsconf_dump(self):
        self.daemon = '\n'.join(line.split('=', 1)[0]+'= "'+line.split('=', 1)[1].strip()+'"' if '=' in line else line
                                for line in self.daemon.splitlines())
        IDENTITY.check(self.config)

    def test_account_uid_gid_home_drift_denied(self):
        for uid, gid, home in ((1001, 1000, '/home/mcramer'), (1000, 1001, '/home/mcramer'), (1000, 1000, '/home/elsewhere')):
            self.account = pwd.struct_passwd(('mcramer', 'x', uid, gid, '', home, '/bin/bash'))
            with self.subTest(uid=uid, gid=gid, home=home), self.assertRaisesRegex(ValueError, 'UID/GID/home'):
                IDENTITY.check(self.config)

    def test_shared_membership_and_gid_drift_denied(self):
        for field, value in (('gr_gid', 2051), ('gr_name', 'other')):
            group = grp.struct_group((value if field == 'gr_name' else 'nfs-sharing', 'x',
                                      value if field == 'gr_gid' else 2050, ['mcramer']))
            with mock.patch.object(IDENTITY.grp, 'getgrgid', return_value=group), self.assertRaisesRegex(ValueError, 'shared group'):
                IDENTITY.check(self.config)
        group = grp.struct_group(('nfs-sharing', 'x', 2050, []))
        with mock.patch.object(IDENTITY.grp, 'getgrnam', return_value=group), self.assertRaisesRegex(ValueError, 'shared group'):
            IDENTITY.check(self.config)

    def test_anonymous_membership_never_gains_access(self):
        group = grp.struct_group(('nfs-sharing', 'x', 2050, ['mcramer', 'nobody']))
        nogroup = grp.struct_group(('nogroup', 'x', 65534, []))
        with mock.patch.object(IDENTITY.grp, 'getgrnam', side_effect=lambda name: group if name == 'nfs-sharing' else nogroup), self.assertRaisesRegex(ValueError, 'anonymous'):
            IDENTITY.check(self.config)

    def test_identity_check_never_enumerates_unrelated_nss_group_providers(self):
        with mock.patch.object(IDENTITY.os, 'getgrouplist', side_effect=AssertionError('unbounded NSS enumeration')) as enumeration:
            IDENTITY.check(self.config)
        enumeration.assert_not_called()

    def test_unknown_name_fallback_and_domain_policy_cannot_be_overridden(self):
        for old, new in (('No-Strip = none', 'No-Strip = both'), ('Nobody-User = nobody', 'Nobody-User = mcramer'),
                         ('Nobody-Group = nogroup', 'Nobody-Group = nfs-sharing'), ('Method = nsswitch', 'Method = static'),
                         ('sharing.validation.invalid', 'sharing.foreign.invalid')):
            self.texts['idmapd.conf'] = self.mapping.replace(old, new)
            with self.subTest(change=new), self.assertRaisesRegex(ValueError, 'name-mapping policy'):
                IDENTITY.check(self.config)

    def test_later_idmap_dropins_are_refused(self):
        directory = self.root/'etc/idmapd.conf.d'
        directory.mkdir()
        (directory/'99-domain.conf').touch()
        self.texts['99-domain.conf'] = '[General]\nDomain = foreign.invalid\n'
        metadata = directory.lstat()
        fields = list(metadata)
        fields[4] = 0  # Model a trusted configuration directory for rootless tests.
        with mock.patch.object(Path, 'lstat', return_value=os.stat_result(fields)), self.assertRaisesRegex(ValueError, 'override settings'):
            IDENTITY.check(self.config)

    def test_effective_mapping_domain_is_checked(self):
        with mock.patch.object(IDENTITY, 'query', return_value='foreign.invalid\n'), self.assertRaisesRegex(ValueError, 'effective NFS identity domain'):
            IDENTITY.check(self.config)

    def test_missing_or_numeric_only_kernel_mapping_is_refused(self):
        for name in ('nfs', 'nfsd'):
            path = self.root/'sys/module'/name/'parameters/nfs4_disable_idmapping'
            path.write_text('Y\n')
            with self.subTest(role=name), self.assertRaisesRegex(ValueError, 'name mapping is not enabled'):
                IDENTITY.check(self.config)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                IDENTITY.check(self.config)
            path.write_text('0\n')
        IDENTITY.check(self.config)

    def test_client_resolver_changes_and_more_specific_handlers_denied(self):
        self.texts['id_resolver.conf'] += 'create id_resolver uid:* * /bin/false\n'
        with self.assertRaisesRegex(ValueError, 'upcall policy'):
            IDENTITY.check(self.config)
        self.texts['id_resolver.conf'] = 'create id_resolver * * /usr/sbin/nfsidmap -t 600 %k %d\n'
        for name in ('request-key.conf', 'earlier.conf'):
            path = self.root/'etc'/name if name == 'request-key.conf' else self.root/'etc/request-key.d'/name
            path.touch()
            self.texts[name] = 'create id_resolver uid:* * /bin/false\n'
            with self.subTest(file=name), self.assertRaisesRegex(ValueError, 'conflicting NFS request-key'):
                IDENTITY.check(self.config)
            self.texts[name] = 'create dns_resolver * * /bin/false\nnegate * * * /bin/false\n'
            IDENTITY.check(self.config)

    def test_effective_server_protocol_and_group_overrides_denied(self):
        baseline = self.daemon
        for old, new in (('vers3 = n', 'vers3 = y'), ('udp = n', 'udp = y'),
                         ('manage-gids = y', 'manage-gids = n'), ('vers4.0 = n', 'vers4.0 = y')):
            self.daemon = baseline.replace(old, new)
            with self.subTest(change=new), self.assertRaisesRegex(ValueError, 'daemon policy'):
                IDENTITY.check(self.config)

    def test_effective_rdma_settings_are_refused_including_legacy_port_values(self):
        baseline = self.daemon
        for key in ('rdma', 'rdma-port'):
            for value in ('n', '0', 'false', 'off', '', '""', '"n"', 'y', '1', '20049', 'nfsrdma'):
                self.daemon = baseline.replace('[nfsd]\n', '[nfsd]\n' + key + ' = ' + value + '\n')
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'RDMA must remain unset'):
                    IDENTITY.check(self.config)

    @unittest.skipUnless(shutil.which('nfsconf'), 'native nfs-utils configuration reader unavailable')
    def test_native_nfsconf_disables_rdma_and_detects_inherited_settings(self):
        binary = shutil.which('nfsconf')
        config = self.root/'nfs.conf'
        config.write_text('[nfsd]\n# rdma=n\n# rdma-port=20049\n')
        directory = config.with_name(config.name + '.d')
        directory.mkdir()
        (directory/'60-network-sharing.conf').write_text(self.daemon)
        def dump():
            result = subprocess.run([binary, '--file', str(config), '--dump'],
                                    text=True, capture_output=True, timeout=10, check=True,
                                    env=IDENTITY.TOOL_ENV)
            return result.stdout
        self.daemon = dump()
        IDENTITY.check(self.config)
        for key in ('rdma', 'rdma-port'):
            result = subprocess.run([binary, '--file', str(config), '--isset', 'nfsd', key],
                                    text=True, capture_output=True, timeout=10, env=IDENTITY.TOOL_ENV)
            self.assertNotEqual(result.returncode, 0, key)
        for location in (config, directory/'99-unmanaged.conf'):
            for key, value in (('rdma', 'n'), ('rdma', '0'), ('rdma', 'y'), ('rdma-port', '20049')):
                location.write_text('[nfsd]\n' + key + '=' + value + '\n')
                self.daemon = dump()
                with self.subTest(location=location.name, key=key, value=value), self.assertRaisesRegex(ValueError, 'RDMA must remain unset'):
                    IDENTITY.check(self.config)
            location.write_text('[nfsd]\n')

    def test_disabled_and_malformed_config_does_not_run_queries(self):
        for config in ({}, {**self.config, 'server_enabled': False, 'client_enabled': False},
                       {**self.config, 'version': 1}, {**self.config, 'client_enabled': 'true'}):
            with mock.patch.object(IDENTITY, 'query') as query, self.assertRaises(ValueError):
                IDENTITY.check(config)
            query.assert_not_called()

    def test_query_is_bounded_read_only_and_drops_environment_injections(self):
        with mock.patch.object(IDENTITY.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'domain\n')) as query:
            self.assertEqual(self.query_impl(['/usr/sbin/nfsidmap', '-d']), 'domain\n')
        call = query.call_args
        self.assertEqual(call.args[0], ['/usr/sbin/nfsidmap', '-d'])
        self.assertEqual(call.kwargs['timeout'], 10)
        self.assertEqual(call.kwargs['stdin'], subprocess.DEVNULL)
        self.assertTrue(call.kwargs['check'])
        self.assertEqual(call.kwargs['env'], IDENTITY.TOOL_ENV)


class HelperConfinementTests(unittest.TestCase):
    def invoke(self, helper, labels, mode='enforce', policy=None):
        opened = []
        def path(value):
            value = str(value)
            opened.append(value)
            result = mock.Mock()
            label = labels.get(value)
            if label is None:
                result.open.side_effect = FileNotFoundError(value)
            elif isinstance(label, Exception):
                result.open.side_effect = label
            else:
                result.open.side_effect = lambda **kw: io.StringIO(label)
            return result
        reader = 'read_local' if helper is IDENTITY else 'read_bounded'
        processor = 'check' if helper is IDENTITY else 'collect'
        config = {'version': 2, 'server_enabled': True, 'client_enabled': False}
        config_reads = []
        def read_input(value, *args, **kwargs):
            if value == helper.MODE_CONFIG:
                if isinstance(policy, Exception):
                    raise policy
                return policy if policy is not None else mode + ' required network-sharing -\n'
            if value == helper.CONFIG:
                config_reads.append(value)
                return json.dumps(config)
            raise AssertionError('unexpected helper input: ' + str(value))
        with mock.patch.object(helper, 'Path', side_effect=path), \
             mock.patch.object(helper.os, 'getuid', return_value=0), \
             mock.patch.object(helper.os, 'geteuid', return_value=0), \
             mock.patch.object(helper, reader, side_effect=read_input), \
             mock.patch.object(helper, processor) as process, \
             mock.patch.object(REPORT, 'publish'):
            try:
                self.assertEqual(helper.main([]), 0)
            except (ValueError, OSError):
                self.assertEqual(config_reads, [])
                process.assert_not_called()
                raise
            self.assertEqual(config_reads, [helper.CONFIG])
            process.assert_called_once()
        return opened

    def test_both_root_helpers_require_their_own_selected_mode(self):
        for helper, name in ((IDENTITY, 'network-sharing-identity'), (REPORT, 'network-sharing-report')):
            for mode, other in (('enforce', 'complain'), ('complain', 'enforce')):
                for label in ('unconfined', name + ' (' + other + ')', 'other (' + mode + ')',
                              '', name + ' (' + mode + ') ' + 'x' * 256):
                    with self.subTest(helper=name, mode=mode, label=label), self.assertRaises(ValueError):
                        self.invoke(helper, {'/proc/self/attr/apparmor/current': label}, mode=mode)
                self.invoke(helper, {'/proc/self/attr/apparmor/current': name + ' (' + mode + ')\n'}, mode=mode)

    def test_desktop_state_is_rendered_and_used_by_both_helpers(self):
        for state in ('enforce', 'complain'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                config = Path(directory)/'modes.conf'
                config.write_text((TARGET/'etc/apparmor/modes.conf.tmpl').read_text())
                result = subprocess.run(
                    ['/bin/sh', '-eu', '-c',
                     '. "$1"; installer_fatal() { echo "$*" >&2; return 1; }; '
                     'installer_info() { :; }; apparmor_apply_desktop_state "$2"',
                     'test-network-mode', str(SEED/'scripts/late/security.sh'), str(config)],
                    env={**os.environ, 'DESKTOP_APPARMOR_STATE': state},
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                policy = config.read_text()
                self.assertIn(state + ' required network-sharing -\n', policy)
                for helper, name in ((IDENTITY, 'network-sharing-identity'), (REPORT, 'network-sharing-report')):
                    self.invoke(helper, {'/proc/self/attr/apparmor/current': name + ' (' + state + ')'}, policy=policy)

    def test_missing_duplicate_disabled_or_malformed_mode_policy_blocks_root_work(self):
        policies = ('', '# no network-sharing row\n', 'disable required network-sharing -\n',
                    'unknown required network-sharing -\n', 'enforce optional network-sharing -\n',
                    'enforce required network-sharing /usr/sbin/nfsidmap\n',
                    'enforce required network-sharing\n',
                    'enforce required network-sharing -\nenforce required network-sharing -\n',
                    'enforce required network-sharing -\ncomplain required network-sharing -\n')
        for helper, name in ((IDENTITY, 'network-sharing-identity'), (REPORT, 'network-sharing-report')):
            for policy in policies:
                with self.subTest(helper=name, policy=policy), self.assertRaises(ValueError):
                    self.invoke(helper, {'/proc/self/attr/apparmor/current': name + ' (enforce)'}, policy=policy)

    def test_unavailable_or_untrusted_mode_policy_blocks_root_work(self):
        for helper, name in ((IDENTITY, 'network-sharing-identity'), (REPORT, 'network-sharing-report')):
            for error in (FileNotFoundError('missing'), PermissionError('denied'), ValueError('unsafe')):
                with self.subTest(helper=name, error=type(error).__name__), self.assertRaises(type(error)):
                    self.invoke(helper, {'/proc/self/attr/apparmor/current': name + ' (enforce)'}, policy=error)

    def test_missing_lsm_specific_path_uses_the_legacy_kernel_interface(self):
        for helper, name in ((IDENTITY, 'network-sharing-identity'), (REPORT, 'network-sharing-report')):
            opened = self.invoke(helper, {'/proc/self/attr/current': name + ' (enforce)'})
            self.assertEqual(opened, ['/proc/self/attr/apparmor/current', '/proc/self/attr/current'])

    def test_disabled_lsm_or_denied_label_cannot_start_root_work(self):
        for helper in (IDENTITY, REPORT):
            with self.subTest(helper=helper), self.assertRaises(ValueError):
                self.invoke(helper, {})
            with self.assertRaises(PermissionError):
                self.invoke(helper, {'/proc/self/attr/apparmor/current': PermissionError('denied')})

    def test_legacy_label_cannot_override_an_existing_unconfined_lsm_label(self):
        for helper, name in ((IDENTITY, 'network-sharing-identity'), (REPORT, 'network-sharing-report')):
            with self.subTest(helper=name), self.assertRaises(ValueError):
                self.invoke(helper, {'/proc/self/attr/apparmor/current': 'unconfined',
                                     '/proc/self/attr/current': name + ' (enforce)'})


class IntegrationWiringTests(unittest.TestCase):
    def test_both_storage_families_and_installer_dispatch(self):
        for name in ('btrfs-family.sh', 'f2fs-family.sh'):
            text = (SEED/'scripts/late'/name).read_text()
            self.assertIn('configure_target_network_sharing', text)
            self.assertLess(text.index('configure_target_network_sharing'), text.index('configure_target_apparmor_auditd'))
        for path in (SEED/'scripts/late/dispatch.sh', SEED/'hooks/installer/late_command.sh'):
            self.assertIn('network-sharing', path.read_text())
        self.assertIn('labwc-network-sharing 0755', (SEED/'scripts/desktop/components/target-assets.sh').read_text())

    def test_mapper_identity_guard_and_firewall_have_explicit_lifecycle_dependencies(self):
        server = (TARGET/'etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl').read_text()
        self.assertIn('BindsTo=nftables.service nfs-idmapd.service\n', server)
        self.assertIn('Requires=nfs-idmapd.service network-sharing-identity.service\n', server)
        mapper = (TARGET/'etc/systemd/system/nfs-idmapd.service.d/60-network-sharing.conf').read_text()
        self.assertIn('Requires=proc-fs-nfsd.mount network-sharing-identity.service\n', mapper)
        self.assertIn('After=proc-fs-nfsd.mount network-sharing-identity.service\n', mapper)
        settings = NFS.Settings.from_environment(profile(NFS_CLIENT_ENABLE='true'))
        self.assertIn('x-systemd.requires=network-sharing-identity.service', NFS.fstab_entries(settings)[0])
        unit = (TARGET/'etc/systemd/system/network-sharing-identity.service').read_text()
        for field in ('Type=oneshot', 'RemainAfterExit=no', 'CapabilityBoundingSet=', 'ProtectKernelTunables=yes',
                      'AppArmorProfile=network-sharing-identity', 'TimeoutStartSec=30s', 'KillMode=control-group'):
            self.assertIn(field, unit)
        self.assertIn('InaccessiblePaths=-/data -/pool -/srv', unit)
        self.assertNotIn('RequiresMountsFor=', unit)
        self.assertIn('ProtectSystem=strict', unit)

    def test_root_helpers_wait_for_mode_policy_and_have_read_only_label_access(self):
        policy = (TARGET/'etc/apparmor.d/network-sharing').read_text()
        for name, suffix in (('identity', ''), ('report', '.tmpl')):
            unit = (TARGET/f'etc/systemd/system/network-sharing-{name}.service{suffix}').read_text()
            self.assertIn('Requires=apparmor.service apparmor-modes.service\n', unit)
            self.assertIn('After=apparmor.service apparmor-modes.service', unit)
            section = policy.split('profile network-sharing-' + name + ' /', 1)[1]
            if name == 'report':
                section = section.split('profile network-sharing-identity', 1)[0]
            self.assertIn('owner @{PROC}/@{pid}/attr/{current,apparmor/current} r,', section)
            self.assertIn('/etc/apparmor/modes.conf r,', section)
        identity = policy.split('profile network-sharing-identity /', 1)[1]
        self.assertNotIn('#include <abstractions/nameservice>', identity)
        for family in ('inet', 'inet6', 'netlink'):
            self.assertEqual(identity.count('deny network ' + family + ','), 2)

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
    def test_native_nfs_query_file_permissions(self):
        # Check concrete operations against included rules and the parser's
        # own glob-to-regex conversion, rather than assuming a valid profile
        # or a matching pathname also permits LOCK_SH or library mappings.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            include = os.environ.get('APPARMOR_INCLUDE_DIR', '/etc/apparmor.d')
            shutil.copytree(include, root, dirs_exist_ok=True)
            for directory in ('abstractions', 'local'):
                if (TARGET/'etc/apparmor.d'/directory).is_dir():
                    shutil.copytree(TARGET/'etc/apparmor.d'/directory, root/directory, dirs_exist_ok=True)
            path = root/'network-sharing'
            path.write_text((TARGET/'etc/apparmor.d/network-sharing').read_text() + '''
profile network-sharing-documents-fixture {
  #include <abstractions/user-documents>
}
''')
            # The installed parser.conf can prepend /etc/apparmor.d to -I.
            # Use only this source-overlay fixture and disable all caching.
            parser_config = root/'parser.conf'
            parser_config.write_text('', encoding='utf-8')
            command = ['apparmor_parser', '--config-file', str(parser_config), '-b', str(root),
                       '-I', str(root), '-Q', '-K', '-j', '1', str(path)]
            debug = subprocess.run([*command, '-d'], text=True, capture_output=True, timeout=30)
            converted = subprocess.run([*command, '--dump=rule-exprs'], text=True, capture_output=True, timeout=30)
            for result in (debug, converted):
                self.assertEqual(result.returncode, 0, result.stderr)
            normalize = lambda value: re.sub(r'/+', '/', value)
            expressions = {}
            for pattern, expression in re.findall(r'^aare: (.*?)\s+->\s+(.*)$',
                                                   converted.stdout + '\n' + converted.stderr, re.M):
                expressions[normalize(pattern)] = re.compile(expression)
            rules = {}
            name = label = None
            for line in (debug.stdout + '\n' + debug.stderr).splitlines():
                if line.startswith('Name:'):
                    name = line.split(':', 1)[1].strip()
                elif line.startswith('Local To:'):
                    parent = line.split(':', 1)[1].strip()
                    label = name if parent == '<NULL>' else parent + '//' + name
                    rules[label] = []
                elif line.startswith('Perms:'):
                    match = re.fullmatch(r'Perms:\s*([^:]*):([^ ]*)\s+priority=\d+\s+Name:\s*\((.*)\)', line)
                    self.assertIsNotNone(match, line)
                    owner, other, pattern = match.groups()
                    pattern = normalize(pattern)
                    self.assertIn(pattern, expressions, 'parser did not convert ' + pattern)
                    rules[label].append((expressions[pattern], set(owner), set(other)))

            def permissions(label, filename):
                owner, other = set(), set()
                for expression, owner_mask, other_mask in rules[label]:
                    if expression.fullmatch(filename):
                        owner.update(owner_mask)
                        other.update(other_mask)
                return owner & other

            parent = 'network-sharing-identity'
            for tool, config in (('nfsidmap', 'idmapd'), ('nfsconf', 'nfs')):
                for label in (parent, parent + '//' + tool):
                    for prefix in ('/etc', '/usr/etc'):
                        base = prefix + '/' + config + '.conf'
                        for filename in (base, base + '.d/00-vendor.conf', base + '.d/60-network-sharing.conf',
                                         base + '.d/99-local.conf'):
                            with self.subTest(label=label, filename=filename):
                                self.assertEqual(permissions(label, filename), {'r', 'k'})
                        self.assertEqual(permissions(label, base + '.d/'), {'r'})
                        for filename in (base + '.d/private.key', base + '.d/subdir/private.conf'):
                            self.assertFalse(permissions(label, filename), (label, filename))
                    for filename in ('/lib/x86_64-linux-gnu/libc.so.6', '/lib64/ld-linux-x86-64.so.2',
                                     '/etc/ld.so.cache', '/usr/sbin/' + tool):
                        self.assertTrue({'r', 'm'} <= permissions(label, filename), (label, filename))
                    self.assertFalse(permissions(label, '/etc/shadow'))
                    self.assertFalse(permissions(label, '/proc/keys'))
            for label in (parent, parent + '//nfsidmap'):
                for filename in ('/usr/lib/x86_64-linux-gnu/libnfsidmap.so.1',
                                 '/usr/lib/x86_64-linux-gnu/libnfsidmap/nsswitch.so'):
                    self.assertTrue({'r', 'm'} <= permissions(label, filename), (label, filename))
                for filename in ('/etc/passwd', '/etc/group', '/etc/nsswitch.conf'):
                    self.assertEqual(permissions(label, filename), {'r'})
            # Native parser expansion: ordinary accounts can list the
            # root-owned parent without gaining parent writes or execution.
            documents = 'network-sharing-documents-fixture'
            self.assertEqual(permissions(documents, '/home/fixture/Sharing/'), {'r'})
            self.assertEqual(permissions(documents, '/home/fixture/Sharing/nfs-client/'), {'r', 'w', 'a', 'k', 'l'})
            self.assertEqual(permissions(documents, '/home/fixture/Sharing/nfs-server/peer.txt'), {'r', 'w', 'a', 'k', 'l'})
            self.assertFalse(permissions(documents, '/home/fixture/Sharing/private/secret'))

    @unittest.skipUnless(shutil.which('apparmor_parser'), 'AppArmor parser unavailable')
    def test_apparmor_profiles_parse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Permit offline checks against an extracted Debian package.
            include = os.environ.get('APPARMOR_INCLUDE_DIR', '/etc/apparmor.d')
            shutil.copytree(include, root, dirs_exist_ok=True)
            for directory in ('abstractions', 'local'):
                if (TARGET/'etc/apparmor.d'/directory).is_dir():
                    shutil.copytree(TARGET/'etc/apparmor.d'/directory, root/directory, dirs_exist_ok=True)
            path = root/'network-sharing'
            path.write_text((TARGET/'etc/apparmor.d/network-sharing').read_text())
            parser_config = root/'parser.conf'
            parser_config.write_text('', encoding='utf-8')
            command = ['apparmor_parser', '--config-file', str(parser_config),
                       '-b', str(root), '-I', str(root), '-K', str(path)]
            names = subprocess.run([*command, '-N'], text=True, capture_output=True, timeout=30)
            self.assertEqual(names.returncode, 0, names.stderr)
            loaded = set(names.stdout.splitlines())
            result = subprocess.run([*command, '-S', '-Q', '-T'], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            # Syntax alone accepts a leading '&' even when the implicit
            # executable attachment does not exist. Check the serialized
            # transition labels against the profiles actually emitted.
            strings = [value.decode() for value in re.findall(rb'[ -~]{5,}', result.stdout)]
            stacks = {value for value in strings if '&network-sharing-identity//' in value}
            self.assertEqual(len(stacks), 2)
            children = set()
            for label in stacks:
                components = label.split('//&')
                self.assertEqual(len(components), 2, 'transition requires an implicit executable attachment: ' + label)
                self.assertIn('network-sharing-identity', components, 'transition drops the parent confinement')
                self.assertTrue(set(components) <= loaded, 'transition target was not emitted: ' + label)
                children.update(set(components) - {'network-sharing-identity'})
            self.assertEqual(children, {'network-sharing-identity//nfsidmap',
                                        'network-sharing-identity//nfsconf'})


if __name__ == '__main__':
    unittest.main()
