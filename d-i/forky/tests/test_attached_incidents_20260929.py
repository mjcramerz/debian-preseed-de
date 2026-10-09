"""Offline regressions for the attached P15s launch and policy failures.

No user units, GUI programs, mounts, journal keys or hardware are operated.
"""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from payload_fixture import installed_script, python_library, read_text

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'


class TorrentServiceTests(unittest.TestCase):
    def setUp(self):
        self.m = types.ModuleType('torrent_incident_fixture')
        path = TARGET / 'usr/local/bin/labwc-qbittorrent'
        exec(compile(path.read_bytes(), str(path), 'exec'), self.m.__dict__)
        self.runtime = Path('/run/user/1000')
        self.environment = dict(XDG_RUNTIME_DIR=str(self.runtime), WAYLAND_DISPLAY='wayland-0',
                                DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/1000/bus',
                                LD_PRELOAD='untrusted.so', PYTHONPATH='/untrusted', DISPLAY=':0',
                                LABWC_SESSION_APP='1')
        self.account = pwd.struct_passwd(('desktop', 'x', 1000, 1000, '', '/home/desktop', '/bin/sh'))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def metadata(self, path):
        return types.SimpleNamespace(st_mode=(stat.S_IFDIR | 0o700) if path == self.runtime else
                                     stat.S_IFSOCK | 0o600, st_uid=1000, st_nlink=1)

    def redirect(self, membership='0::/user.slice/session.scope\n', **updates):
        environment = dict(self.environment, **updates)
        with mock.patch.dict(self.m.os.environ, environment, clear=True), \
             mock.patch.object(self.m.os, 'getuid', return_value=1000), \
             mock.patch.object(self.m.pwd, 'getpwuid', return_value=self.account), \
             mock.patch.object(self.m.pathlib.Path, 'lstat', autospec=True, side_effect=self.metadata), \
             mock.patch.object(self.m.pathlib.Path, 'exists', return_value=False), \
             mock.patch.object(self.m.pathlib.Path, 'open', return_value=io.StringIO(membership)), \
             mock.patch.object(self.m.sys, 'argv', ['/usr/local/bin/labwc-qbittorrent', 'magnet:?xt=fixture']), \
             mock.patch.object(self.m.os, 'execve') as executed:
            self.m.redirect_to_user_service()
        return executed

    def test_direct_launch_scrubs_environment_and_sets_the_user_bus_explicitly(self):
        executed = self.redirect()
        executable, argv, environment = executed.call_args.args
        self.assertEqual(executable, '/usr/bin/systemd-run')
        self.assertIn('--setenv=DBUS_SESSION_BUS_ADDRESS', argv)
        self.assertEqual(environment['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=/run/user/1000/bus')
        self.assertEqual(environment['HOME'], '/home/desktop')
        self.assertTrue({'LD_PRELOAD', 'PYTHONPATH', 'DISPLAY', 'LABWC_SESSION_APP'}.isdisjoint(environment))
        for item in ('--collect', '--property=Requisite=labwc-session.target',
                     '--property=PartOf=labwc-session.target', '--property=ExitType=main',
                     '--property=KillMode=control-group', '--property=UMask=0077'):
            self.assertIn(item, argv)
        self.assertEqual(argv[argv.index('--') + 1:],
                         ['/usr/local/bin/labwc-qbittorrent', 'magnet:?xt=fixture'])

    def test_only_real_managed_service_membership_skips_the_handoff(self):
        for prefix in ('labwc-native-qbittorrent-', 'labwc-qbittorrent-',
                       'labwc-wayland-qbittorrent-', 'labwc-wayland-labwc-qbittorrent-'):
            for marker in ('', '1'):
                with self.subTest(prefix=prefix, marker=marker):
                    executed = self.redirect('0::/user.slice/' + prefix + 'a' * 32 + '.service\n',
                                             LABWC_QBITTORRENT_SESSION_UNIT=marker)
                    executed.assert_not_called()
        for membership in ('0::/user.slice/not-qbittorrent.service\n',
                           '0::/user.slice/labwc-wayland-qbittorrent-evil-' + 'a' * 32 + '.service\n',
                           '0::/user.slice/labwc-wayland-labwc-qbittorrent-' + 'a' * 31 + '.service\n',
                           '0::/user.slice/labwc-qbittorrent-' + 'a' * 32 + '.service/child\n'):
            with self.subTest(membership=membership), self.assertRaises(SystemExit):
                self.redirect(membership, LABWC_QBITTORRENT_SESSION_UNIT='1')

    def test_missing_foreign_or_multiple_session_bus_fails_before_service_creation(self):
        for value in ('', 'unix:path=/run/user/1001/bus',
                      'unix:path=/run/user/1000/bus;unix:path=/tmp/bus'):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                self.redirect(DBUS_SESSION_BUS_ADDRESS=value)

    def test_foreign_socket_or_symlink_is_not_accepted(self):
        for mode, uid, links in ((stat.S_IFSOCK, 1001, 1), (stat.S_IFLNK, 1000, 1),
                                 (stat.S_IFSOCK, 1000, 2)):
            metadata = types.SimpleNamespace(st_mode=mode, st_uid=uid, st_nlink=links)
            with mock.patch.object(self.m.os, 'getuid', return_value=1000), \
                 mock.patch.object(self.m.pathlib.Path, 'lstat', return_value=metadata), \
                 self.assertRaises(SystemExit):
                self.m.require_socket(self.runtime / 'bus', 'bus')

    def test_cgroup_input_is_bounded(self):
        with self.assertRaises(SystemExit):
            self.redirect('x' * 65537)


class ConnectionNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(sys, 'path', [
            str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')), *sys.path]))
        from labwc_managed_app import generic
        self.m = generic

    def argv(self, kind, arguments):
        with mock.patch.object(self.m, 'assert_launch_allowed'), \
             mock.patch.object(self.m, 'restart_token', return_value='fixture'), \
             mock.patch.object(self.m, 'menu_action_wait_arguments', return_value=[]):
            return self.m.transient_argv(kind, 'auto', arguments, {})

    def test_freerdp_connection_worker_keeps_host_uid_mapping_and_session_lifetime(self):
        argv = self.argv('wayland', ['/usr/local/bin/labwc-remote-desktop', '_connect', 'fixture'])
        self.assertIn('--property=PrivateUsers=no', argv)
        self.assertNotIn('--property=PrivateTmp=yes', argv)
        for item in ('--property=PartOf=labwc-session.target', '--property=ExitType=cgroup',
                     '--property=KillMode=control-group', '--property=SendSIGKILL=yes'):
            self.assertIn(item, argv)

    def test_freerdp_menu_and_similarly_named_commands_keep_generic_isolation(self):
        for kind, arguments in (('wayland', ['/usr/local/bin/labwc-remote-desktop']),
                                ('wayland', ['/usr/local/bin/labwc-remote-desktop', '_connect-evil']),
                                ('wayland', ['/tmp/labwc-remote-desktop', '_connect']),
                                ('electron', ['/usr/local/bin/labwc-remote-desktop', '_connect'])):
            with self.subTest(kind=kind, arguments=arguments):
                argv = self.argv(kind, arguments)
                self.assertIn('--property=PrivateTmp=yes', argv)
                self.assertNotIn('--property=PrivateUsers=no', argv)

    def test_direct_mullvad_package_gui_has_host_daemon_access(self):
        argv = self.argv('electron', ['/opt/Mullvad VPN/mullvad-gui'])
        self.assertIn('--property=PrivateUsers=no', argv)
        for path in ('/tmp/Mullvad VPN/mullvad-gui', '/opt/Mullvad VPN/mullvad-gui-evil'):
            self.assertIn('--property=PrivateTmp=yes', self.argv('electron', [path]))
        arguments = self.m.electron_command(['/opt/Mullvad VPN/mullvad-gui'])
        self.assertIn('--ozone-platform=wayland', arguments)
        self.assertNotIn('--no-sandbox', arguments)


class MullvadVendorPolicyTests(unittest.TestCase):
    def test_only_the_known_managed_header_flags_can_differ_from_vendor_policy(self):
        source = (SEED / 'scripts/late/mullvad.sh').read_text()
        check = 'normalize_header=' + source.split('normalize_header=', 1)[1].split(
            'apparmor_parser --skip-kernel-load', 1)[0]
        vendor = ('abi <abi/4.0>,\ninclude <tunables/global>\n'
                  'profile mullvad "/opt/Mullvad VPN/mullvad-gui" flags=(unconfined) {\n'
                  '  userns,\n  include if exists <local/mullvad>\n}\n')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / 'mullvad'; reference = root / 'vendor'
            reference.write_text(vendor)
            check = check.replace('"/opt/Mullvad VPN/resources/apparmor_mullvad"', '"$2"')
            check = check.replace('/tmp/mullvad-apparmor.XXXXXXXXXX', str(root / 'check.XXXXXXXXXX'))
            script = 'set -eu\nprofile=$1\n' + check
            variants = ((vendor, True),
                        (vendor.replace('unconfined', 'attach_disconnected, mediate_deleted'), True),
                        (vendor.replace('unconfined', 'complain, attach_disconnected, mediate_deleted'), True),
                        (vendor.replace('unconfined', 'audit, attach_disconnected, mediate_deleted'), True),
                        (vendor.replace('unconfined', 'prompt'), False),
                        (vendor.replace('  userns,', '  capability sys_admin,'), False),
                        (vendor + '\n', False))
            for content, accepted in variants:
                with self.subTest(content=content):
                    policy.write_text(content)
                    result = subprocess.run(['/bin/sh', '-c', script, 'policy-fixture', str(policy),
                                             str(reference)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                    self.assertEqual(sorted(p.name for p in root.iterdir()), ['mullvad', 'vendor'])


@unittest.skipUnless(shutil.which('perl'), 'Perl unavailable')
class ScannerTagTests(unittest.TestCase):
    def test_every_routed_scanner_tag_is_accepted_by_the_real_perl_validator(self):
        dependency = subprocess.run(['perl', '-MMoo', '-MMooX::StrictConstructor', '-MMooX::TypeTiny',
                                     '-e', '1'], capture_output=True, timeout=10)
        if dependency.returncode:
            self.skipTest('Moo/MooX runtime dependencies unavailable')
        route = read_text(TARGET / 'etc/rsyslog.d/39-security-scanners.conf')
        tags = sorted(set(re.findall(r'"([a-z-]+-scan)"', route)))
        self.assertEqual(len(tags), 8)
        path = installed_script(TARGET / 'usr/local/lib/perl5/site_perl/labwc-security-action/'
                                'LabwcSecurityAction/ScannerLog.pm')
        source = r'''
require $ARGV[0];
my $logger = LabwcSecurityAction::ScannerLog->new(socket_path => '/run/rsyslog/scanners/scanners.sock');
for my $tag (@ARGV[1..$#ARGV]) {
    $logger->_validate_run(argv => ['/usr/bin/true'], tag => $tag, label => 'fixture');
}
for my $tag ('managed-lynis', 'unknown-scan', "lynis-scan\n", 'lynis-scan;injected') {
    eval { $logger->_validate_run(argv => ['/usr/bin/true'], tag => $tag, label => 'fixture'); 1 }
        and die "invalid tag accepted";
    $@ =~ /invalid managed scanner log tag/ or die "wrong validation failure: $@";
}
print "scanner tag routing verified\n";
'''
        result = subprocess.run(['perl', '-e', source, str(path), *tags],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('routing verified', result.stdout)


if __name__ == '__main__':
    unittest.main()
