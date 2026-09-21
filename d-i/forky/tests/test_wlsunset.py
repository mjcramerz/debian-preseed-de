#!/usr/bin/env python3
"""Native colour-service configuration, ownership, lifecycle and installer tests.

Uses real AF_UNIX peer credentials and flock; user-manager commands are fixtures.
No target service is started, no GPU accessed and no AppArmor policy is loaded.
"""
from __future__ import annotations
import importlib.machinery
import array
import fcntl
import importlib.util
import os
from pathlib import Path
import pwd
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
SCRIPT = TARGET / 'usr/local/bin/labwc-wlsunset'
loader = importlib.machinery.SourceFileLoader('wlsunset_test_module', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
W = importlib.util.module_from_spec(spec)
loader.exec_module(W)
DEFAULTS = {
    'WLSUNSET_ENABLED': 'true', 'WLSUNSET_LATITUDE': '55.60587', 'WLSUNSET_LONGITUDE': '13.00073',
    'WLSUNSET_TEMPERATURE_DAY': '6500', 'WLSUNSET_TEMPERATURE_NIGHT': '4500', 'WLSUNSET_GAMMA': '1.0',
    'WLSUNSET_SUNRISE': '', 'WLSUNSET_SUNSET': '', 'WLSUNSET_TRANSITION_SECONDS': '1800', 'WLSUNSET_OUTPUTS': '',
}


def config_text(values):
    return ''.join(key + '=' + shlex.quote(value) + '\n' for key, value in values.items())


class ConfigTests(unittest.TestCase):
    def test_default_is_enabled_and_solar(self):
        self.assertEqual(W.daemon_argv(DEFAULTS), ['/usr/bin/wlsunset', '-T', '6500', '-t', '4500',
                         '-g', '1.0', '-l', '55.60587', '-L', '13.00073'])

    def test_global_coordinate_boundaries_and_hemispheres(self):
        for latitude, longitude in [('-90', '-180'), ('90', '180'), ('0', '0'),
                                    ('-33.8688', '+151.2093'), ('40.7', '-74.0')]:
            with self.subTest(latitude=latitude, longitude=longitude):
                args = W.daemon_argv({**DEFAULTS, 'WLSUNSET_LATITUDE': latitude, 'WLSUNSET_LONGITUDE': longitude})
                self.assertEqual(args[-4:], ['-l', latitude, '-L', longitude])

    def test_invalid_decimals_are_rejected(self):
        invalid = ('nan', 'inf', '1e1', '91', '-90.1', '1;true', '$(id)', '`id`', '1\n2',
                   '1 2', '--90', '.', '', '1' * 40)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(W.PolicyError):
                W.validate_config({**DEFAULTS, 'WLSUNSET_LATITUDE': value})
        for value in ('180.1', '-180.1'):
            with self.assertRaises(W.PolicyError):
                W.validate_config({**DEFAULTS, 'WLSUNSET_LONGITUDE': value})

    def test_temperatures_gamma_and_strict_boolean(self):
        for key, values in {
            'WLSUNSET_TEMPERATURE_DAY': ('4500', '999', '10001', '6500.0', '6500;true'),
            'WLSUNSET_TEMPERATURE_NIGHT': ('6500', '999', '10001'),
            'WLSUNSET_GAMMA': ('0', '-1', '10.1', 'NaN'),
            'WLSUNSET_ENABLED': ('1', 'yes', 'TRUE', ''),
            'WLSUNSET_TRANSITION_SECONDS': ('0', '-1', '21601', '1.5'),
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(W.PolicyError):
                    W.validate_config({**DEFAULTS, key: value})

    def test_manual_schedule_never_mixes_coordinates(self):
        args = W.daemon_argv({**DEFAULTS, 'WLSUNSET_SUNRISE': '06:30', 'WLSUNSET_SUNSET': '18:30'})
        self.assertEqual(args[-6:], ['-S', '06:30', '-s', '18:30', '-d', '1800'])
        self.assertNotIn('-l', args)
        self.assertNotIn('-L', args)

    def test_partial_and_wrapping_manual_schedules_fail(self):
        for sunrise, sunset in [('06:30', ''), ('', '18:30'), ('6:30', '18:30'), ('06:30', '24:00'),
                                ('00:01', '18:30'), ('18:30', '06:30'), ('06:30', '23:59'), ('06:30', '06:30')]:
            with self.subTest(sunrise=sunrise, sunset=sunset), self.assertRaises(W.PolicyError):
                W.validate_config({**DEFAULTS, 'WLSUNSET_SUNRISE': sunrise, 'WLSUNSET_SUNSET': sunset})

    def test_output_filter_is_repeated_argv_not_shell(self):
        args = W.daemon_argv({**DEFAULTS, 'WLSUNSET_OUTPUTS': 'eDP-1 DP-2'})
        self.assertEqual(args[-4:], ['-o', 'eDP-1', '-o', 'DP-2'])
        for value in ('--help', 'DP-1 DP-1', 'DP-1;id', 'DP-1\nDP-2', 'DP-1/../../x',
                      ' '.join('DP-' + str(i) for i in range(17))):
            with self.subTest(value=value), self.assertRaises(W.PolicyError):
                W.validate_config({**DEFAULTS, 'WLSUNSET_OUTPUTS': value})

    def test_missing_or_unknown_key_rejected(self):
        with self.assertRaises(W.PolicyError): W.validate_config({})
        with self.assertRaises(W.PolicyError): W.validate_config({**DEFAULTS, 'WLSUNSET_EXTRA_ARGS': '--help'})


@unittest.skipUnless(os.getuid() == 0, 'root-owned configuration fixtures; no system files modified')
class ConfigFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.wlsunset-', dir=pwd.getpwuid(os.getuid()).pw_dir)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'config'
        self.path.write_text(config_text(DEFAULTS))
        self.path.chmod(0o644)

    def test_read_literal_config(self):
        self.assertEqual(W.read_config(self.path), DEFAULTS)
        text = self.path.read_text().replace("WLSUNSET_SUNRISE=''", 'WLSUNSET_SUNRISE=')
        self.path.write_text(text)
        self.assertEqual(W.read_config(self.path), DEFAULTS)

    def test_duplicate_key_rejected(self):
        self.path.write_text(self.path.read_text() + 'WLSUNSET_ENABLED=false\n')
        with self.assertRaises(W.PolicyError): W.read_config(self.path)

    def test_config_never_executes_shell(self):
        victim = self.root / 'never-created'
        self.path.write_text(config_text({**DEFAULTS, 'WLSUNSET_LATITUDE': '$(touch ' + str(victim) + ')'}))
        with self.assertRaises(W.PolicyError): W.read_config(self.path)
        self.assertFalse(victim.exists())

    def test_leaf_symlink_rejected(self):
        link = self.root / 'link'; link.symlink_to(self.path)
        with self.assertRaises(OSError): W.read_config(link)

    def test_parent_symlink_rejected(self):
        link = self.root / 'link'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): W.read_config(link / 'config')

    def test_fifo_is_rejected_without_blocking(self):
        self.path.unlink(); os.mkfifo(self.path, 0o600)
        with self.assertRaises(W.PolicyError): W.read_config(self.path)

    def test_hardlink_and_writable_config_rejected(self):
        other = self.root / 'other'; os.link(self.path, other)
        with self.assertRaises(W.PolicyError): W.read_config(self.path)
        other.unlink(); self.path.chmod(0o666)
        with self.assertRaises(W.PolicyError): W.read_config(self.path)

    def test_oversized_and_wrong_owner_rejected(self):
        self.path.write_text('#' * 9000)
        with self.assertRaises(W.PolicyError): W.read_config(self.path)
        self.path.write_text(config_text(DEFAULTS)); os.chown(self.path, 1234, -1)
        with self.assertRaises(W.PolicyError): W.read_config(self.path)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wls-peer-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.server.close)
        self.server.bind(str(self.root / 'wayland-7')); self.server.listen(8)
        self.uid = os.getuid()
        self.pid = str(os.getpid())
        self.env = {'XDG_RUNTIME_DIR': str(self.root)}
        self.values = {'XDG_RUNTIME_DIR': str(self.root), 'WAYLAND_DISPLAY': 'wayland-7',
                       'LABWC_SESSION_OWNER': 'desktop', 'XDG_SESSION_TYPE': 'wayland', 'LABWC_PID': self.pid}

    def props(self, unit, env):
        return {'ActiveState': 'active', 'LoadState': 'loaded', 'MainPID': self.pid}

    def session(self):
        with mock.patch.object(W, 'manager_environment', return_value=self.values), \
             mock.patch.object(W, 'properties', side_effect=self.props):
            return W.active_session(self.env, self.uid)

    def test_real_peer_credentials_and_authoritative_environment(self):
        with mock.patch.dict(os.environ, WAYLAND_DISPLAY='wrong', DISPLAY=':99'):
            result = self.session()
        self.assertEqual(result['WAYLAND_DISPLAY'], 'wayland-7')
        self.assertNotIn('DISPLAY', result)
        self.assertNotIn('DBUS_SESSION_BUS_ADDRESS', result)

    def test_absolute_managed_socket_is_normalized(self):
        self.values['WAYLAND_DISPLAY'] = str(self.root / 'wayland-7')
        self.assertEqual(self.session()['WAYLAND_DISPLAY'], 'wayland-7')

    def test_socket_from_other_compositor_is_rejected(self):
        self.pid = str(os.getpid() + 10000)
        self.values['LABWC_PID'] = self.pid
        with self.assertRaisesRegex(W.PolicyError, 'peer differs'): self.session()

    def test_missing_and_redirected_display_rejected(self):
        for value in ('../wayland-7', '/tmp/wayland-7', 'wayland-7\n', ''):
            self.values['WAYLAND_DISPLAY'] = value
            with self.subTest(value=value), self.assertRaises(W.PolicyError): self.session()
        (self.root / 'wayland-8').symlink_to(self.root / 'wayland-7')
        self.values['WAYLAND_DISPLAY'] = 'wayland-8'
        with self.assertRaises(W.PolicyError): self.session()

    def test_stale_manager_pid_and_non_wayland_session_rejected(self):
        for key, value in (('LABWC_PID', '1'), ('XDG_SESSION_TYPE', 'x11'),
                           ('LABWC_SESSION_OWNER', 'greeter'), ('XDG_RUNTIME_DIR', '/run/user/other')):
            old = self.values[key]; self.values[key] = value
            with self.subTest(key=key), self.assertRaises(W.PolicyError): self.session()
            self.values[key] = old

    def test_inactive_target_rejected(self):
        with mock.patch.object(W, 'manager_environment', return_value=self.values), \
             mock.patch.object(W, 'properties', return_value={'ActiveState': 'inactive'}):
            with self.assertRaises(W.PolicyError): W.active_session(self.env, self.uid)

    def test_manager_environment_parses_only_allowlisted_keys(self):
        response = subprocess.CompletedProcess([], 0,
            "DISPLAY=:99\nLD_PRELOAD=/tmp/bad\nWAYLAND_DISPLAY='wayland-7'\nLABWC_PID=55\n", '')
        with mock.patch.object(W, 'systemctl', return_value=response):
            self.assertEqual(W.manager_environment({}), {'WAYLAND_DISPLAY': 'wayland-7', 'LABWC_PID': '55'})


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.state = None
        self.runs = []; self.stops = []
        self.session = {'XDG_RUNTIME_DIR': '/run/user/1000', 'WAYLAND_DISPLAY': 'wayland-1',
                        'LABWC_SESSION_OWNER': 'desktop', 'LABWC_PID': '1234',
                        'XDG_SESSION_TYPE': 'wayland', 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
        for name, kwargs in [('properties', {'side_effect': self.properties}),
                             ('command', {'side_effect': self.fake_run}),
                             ('systemctl', {'side_effect': self.ctl}),
                             ('active_session', {'return_value': self.session})]:
            patch = mock.patch.object(W, name, **kwargs); patch.start(); self.addCleanup(patch.stop)

    def properties(self, unit, env):
        return self.state or {'LoadState': 'not-found', 'ActiveState': 'inactive'}

    def fake_run(self, args, env):
        self.runs.append(args)
        self.state = {'LoadState': 'loaded', 'ActiveState': 'active', 'Transient': 'yes', 'Description': W.DESCRIPTION}
        return subprocess.CompletedProcess(args, 0, '', '')

    def ctl(self, args, env):
        if args == ['stop', W.UNIT]: self.stops.append(args); self.state = None
        return subprocess.CompletedProcess(args, 0, '', '')

    def test_repeated_starts_are_singleton(self):
        self.assertEqual(W.operate('start', DEFAULTS, {}, 1000), 0)
        self.assertEqual(W.operate('start', DEFAULTS, {}, 1000), 0)
        self.assertEqual(len(self.runs), 1); self.assertEqual(len(self.stops), 0)

    def test_disabled_policy_stops_previous_instance(self):
        W.operate('start', DEFAULTS, {}, 1000)
        W.operate('start', {**DEFAULTS, 'WLSUNSET_ENABLED': 'false'}, {}, 1000)
        self.assertEqual(len(self.stops), 1); self.assertEqual(len(self.runs), 1)

    def test_restart_replaces_in_order_and_uses_new_policy(self):
        W.operate('start', DEFAULTS, {}, 1000)
        W.operate('restart', {**DEFAULTS, 'WLSUNSET_LATITUDE': '-33.9'}, {}, 1000)
        self.assertEqual(len(self.stops), 1); self.assertEqual(len(self.runs), 2)
        self.assertIn('-33.9', self.runs[-1])

    def test_invalid_restart_preserves_running_instance(self):
        W.operate('start', DEFAULTS, {}, 1000)
        with self.assertRaises(W.PolicyError):
            W.operate('restart', {**DEFAULTS, 'WLSUNSET_GAMMA': '0'}, {}, 1000)
        self.assertEqual(len(self.stops), 0); self.assertEqual(len(self.runs), 1)

    def test_non_managed_unit_is_never_replaced(self):
        self.state = {'LoadState': 'loaded', 'ActiveState': 'active', 'Transient': 'no', 'Description': 'Other'}
        with self.assertRaises(W.PolicyError): W.operate('restart', DEFAULTS, {}, 1000)
        self.assertFalse(self.runs); self.assertFalse(self.stops)

    def test_stop_without_config_or_active_compositor(self):
        W.operate('start', DEFAULTS, {}, 1000)
        with mock.patch.object(W, 'active_session', side_effect=AssertionError('must not query compositor')):
            self.assertEqual(W.operate('stop', None, {}, 1000), 0)
            self.assertEqual(W.operate('stop', None, {}, 1000), 0)
        self.assertEqual(len(self.stops), 1)

    def test_command_failure_is_visible_and_not_retried(self):
        with mock.patch.object(W, 'command', return_value=subprocess.CompletedProcess([], 1, '', 'fixture failed')) as call:
            with self.assertRaisesRegex(RuntimeError, 'fixture failed'): W.operate('start', DEFAULTS, {}, 1000)
            self.assertEqual(call.call_count, 1)

    def test_secure_transient_service_shape(self):
        args = W.start_argv(DEFAULTS, self.session)
        for arg in ('--user', '--collect', '--service-type=exec', '--expand-environment=no',
                    '--unit=labwc-wlsunset.service', '--property=PartOf=labwc-session.target',
                    '--property=BindsTo=labwc-compositor.service', '--property=KillMode=control-group',
                    '--property=RestrictAddressFamilies=AF_UNIX', '--property=NoNewPrivileges=yes',
                    '--property=MemoryDenyWriteExecute=yes', '--property=Restart=always',
                    '--property=StartLimitBurst=3', '--setenv=WAYLAND_DISPLAY=wayland-1'):
            self.assertIn(arg, args)
        self.assertEqual(args[args.index('--') + 1:], W.daemon_argv(DEFAULTS))
        for prefix in ('--scope', '--wait', '--no-block', '--property=AppArmorProfile=',
                       '--property=RuntimeMaxSec=', '--setenv=DISPLAY=', '--property=PrivateNetwork='):
            self.assertFalse(any(arg.startswith(prefix) for arg in args), prefix)


@unittest.skipUnless(os.getuid() == 0, 'chowned private lock fixtures require root')
class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='.wls-lock-', dir=pwd.getpwuid(os.getuid()).pw_dir)
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        os.chown(self.runtime, 1234, -1); self.runtime.chmod(0o700)
        self.bus = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.bus.close)
        self.bus.bind(str(self.runtime / 'bus')); os.chown(self.runtime / 'bus', 1234, -1)
        self.lock = self.runtime / 'labwc-wlsunset.lock'; self.lock.touch(mode=0o600); os.chown(self.lock, 1234, -1)
        patch = mock.patch.object(W, 'Path', side_effect=lambda value: self.runtime if value == '/run/user/1234' else Path(value))
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(W.pwd, 'getpwuid', return_value=types.SimpleNamespace(pw_dir='/home/test', pw_name='test'))
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.runtime))
        patch.start(); self.addCleanup(patch.stop)

    def test_private_runtime_environment_and_lock_inode_persists(self):
        inode = self.lock.stat().st_ino
        with W.locked_runtime(1234) as env:
            self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=' + str(self.runtime / 'bus'))
            self.assertNotIn('DISPLAY', env)
        self.assertEqual(self.lock.stat().st_ino, inode)

    def test_concurrent_operation_cannot_acquire_lock(self):
        with W.locked_runtime(1234):
            with mock.patch.object(W.time, 'monotonic', side_effect=[0, 11]):
                with self.assertRaisesRegex(RuntimeError, 'in progress'):
                    with W.locked_runtime(1234): pass

    def test_fifo_symlink_and_hardlink_locks_rejected(self):
        self.lock.unlink(); os.mkfifo(self.lock, 0o600); os.chown(self.lock, 1234, -1)
        with self.assertRaises(W.PolicyError):
            with W.locked_runtime(1234): pass
        self.lock.unlink(); self.lock.symlink_to(self.runtime / 'bus')
        with self.assertRaises(OSError):
            with W.locked_runtime(1234): pass
        self.lock.unlink(); self.lock.touch(mode=0o600); os.chown(self.lock, 1234, -1)
        os.link(self.lock, self.runtime / 'alias')
        with self.assertRaises(W.PolicyError):
            with W.locked_runtime(1234): pass

    def test_wrong_directory_mode_and_root_launch_rejected(self):
        with self.assertRaises(W.PolicyError):
            with W.locked_runtime(0): pass
        self.runtime.chmod(0o755)
        with self.assertRaises(W.PolicyError):
            with W.locked_runtime(1234): pass


class InstallerTests(unittest.TestCase):
    def shell_validate(self, settings):
        env = {**os.environ, **settings}
        return subprocess.run(['/bin/sh', '-c', 'set -eu; desktop_fatal(){ echo "$*" >&2; exit 1; }; '
                               '. "$1"; desktop_validate_wlsunset_policy', 'fixture',
                               str(FORKY / 'scripts/desktop/detect.sh')], env=env, capture_output=True, text=True, timeout=10)

    def test_all_ten_profiles_render_every_setting(self):
        profiles = sorted((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for profile in profiles:
            with self.subTest(profile=profile.name):
                result = subprocess.run(['/bin/sh', '-c',
                    'set -eu; . "$1"; . "$2"; . "$3"; desktop_stage_role_asset(){ :; }; run_in_target(){ :; }; '
                    'desktop_render_role_target_template(){ printf "%s\\0" "$@"; }; desktop_stage_wlsunset',
                    'fixture', str(profile), str(FORKY / 'scripts/common/target.sh'),
                    str(FORKY / 'scripts/desktop/components.sh')],
                    capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = result.stdout.decode().split('\0')[:-1]
                self.assertEqual(args[:3], ['etc/default/labwc-wlsunset.tmpl', '/etc/default/labwc-wlsunset', '0644'])
                rendered = {k: shlex.split(v)[0] for k, v in zip(args[3::2], args[4::2])}
                self.assertEqual(rendered, DEFAULTS)
                self.assertEqual(self.shell_validate(rendered).returncode, 0)
                for key in DEFAULTS:
                    self.assertEqual(len(re.findall('^' + key + '=', profile.read_text(), re.M)), 1)

    def test_shell_and_python_validators_agree(self):
        for key, value in [('WLSUNSET_LATITUDE', '-33.8688'), ('WLSUNSET_LONGITUDE', '-180'),
                           ('WLSUNSET_LATITUDE', '91'), ('WLSUNSET_LATITUDE', '1\n2'),
                           ('WLSUNSET_GAMMA', '1;id'), ('WLSUNSET_GAMMA', 'NaN'),
                           ('WLSUNSET_OUTPUTS', 'DP-1\nDP-2'), ('WLSUNSET_OUTPUTS', 'DP-1 DP-1'),
                           ('WLSUNSET_OUTPUTS', 'DP-1 eDP-1'), ('WLSUNSET_ENABLED', 'false'),
                           ('WLSUNSET_ENABLED', 'TRUE'), ('WLSUNSET_SUNRISE', '06:30'),
                           ('WLSUNSET_TEMPERATURE_DAY', '006500'), ('WLSUNSET_SUNSET', '19:00\nignored')]:
            cfg = {**DEFAULTS, key: value}
            try: W.validate_config(cfg); valid = True
            except W.PolicyError: valid = False
            with self.subTest(key=key, value=value):
                result = self.shell_validate(cfg)
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_old_runtime_implementation_and_dependencies_are_absent(self):
        role = (FORKY / 'classes/class-select/role/desktop.cfg').read_text().split()
        self.assertIn('wlsunset', role)
        self.assertNotIn('gammastep', role); self.assertNotIn('geoclue-2.0', role)
        self.assertNotIn('gir1.2-ayatanaappindicator3-0.1', role)
        self.assertFalse(list(TARGET.rglob('*gammastep*')))
        for profile in (FORKY / 'hosts/profiles').glob('*.env'):
            self.assertNotIn('GAMMASTEP_', profile.read_text())
        self.assertNotIn('GeoClue2', (TARGET / 'etc/apparmor.d/managed-labwc-session').read_text())

    def test_autostart_order_and_app_armor_transitions(self):
        script = (TARGET / 'usr/local/bin/labwc-autostart').read_text()
        call = script.index('session_systemctl start labwc-wlsunset-start.service')
        for step in ('sync_user_activation_environment\n', 'start_session_target\n', 'wait_for_wayland_output\n'):
            self.assertLess(script.rindex(step), call)
        policy = (TARGET / 'etc/apparmor.d/managed-labwc-session').read_text()
        self.assertIn('profile managed-wlsunset /usr/bin/wlsunset flags=(attach_disconnected, mediate_deleted)', policy)
        self.assertEqual(policy.count('owner /tmp/wlsunset-shared-?????? rw,'), 2)
        self.assertIn('peer=(label=managed-labwc-compositor)', policy)
        self.assertIn('deny /dev/dri/** rw,', policy)
        wrappers = (TARGET / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
        self.assertIn('/usr/local/bin/labwc-wlsunset rPx -> managed-labwc-wlsunset,', wrappers)

    def test_gamma_descriptor_transfer_preserves_read_write_open_mode(self):
        # Real Linux SCM_RIGHTS semantics, not an AppArmor enforcement fixture.
        # mkstemp's O_RDWR mode survives unlink and receipt by the compositor;
        # the kernel's file_receive LSM hook therefore requests both permissions.
        with tempfile.TemporaryDirectory(prefix='gamma-fd-test-') as temporary:
            path = Path(temporary) / 'wlsunset-shared-Ab3xYz'
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            received = None
            sender, receiver = socket.socketpair()
            try:
                os.unlink(path)
                sender.sendmsg([b'x'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))])
                _, controls, _, _ = receiver.recvmsg(1, socket.CMSG_SPACE(array.array('i').itemsize))
                self.assertEqual(controls[0][:2], (socket.SOL_SOCKET, socket.SCM_RIGHTS))
                descriptors = array.array('i'); descriptors.frombytes(controls[0][2])
                received = descriptors[0]
                self.assertEqual(fcntl.fcntl(received, fcntl.F_GETFL) & os.O_ACCMODE, os.O_RDWR)
                self.assertEqual(os.fstat(received).st_nlink, 0)
                os.write(received, b'gamma')
                os.lseek(fd, 0, os.SEEK_SET)
                self.assertEqual(os.read(fd, 5), b'gamma')
            finally:
                sender.close(); receiver.close(); os.close(fd)
                if received is not None: os.close(received)

    def test_switcher_shares_menu_hover_gradient_without_overrides(self):
        css = (TARGET / 'etc/skel-desktop/.config/waybar/style.css.tmpl').read_text()
        matches = re.findall(r'([^{}]+)\{([^{}]*)\}', css)
        blocks = [(selectors, body) for selectors, body in matches if '#custom-window-switcher:hover' in selectors]
        self.assertEqual(len(blocks), 1)
        selectors, body = blocks[0]
        self.assertEqual(selectors.strip(), '#custom-window-switcher:hover')
        self.assertIn('background: rgba(15, 56, 39, 0.86);', body)
        self.assertIn('border-color: @emeraldgreen;', body)
        self.assertNotIn('color: #08111f;', body)
        self.assertNotIn('#workspaces button:hover', selectors)



if __name__ == '__main__': unittest.main()
