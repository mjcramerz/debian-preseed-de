"""Idle state, rollback, hotkey and PAM lifecycle regressions; no live desktop."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import socket
import stat
import subprocess
import tempfile
import threading
import time
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
SOURCE = TARGET / 'usr/local/bin/labwc-idle-toggle'


def load():
    module = types.ModuleType('idle_fixture')
    exec(compile(SOURCE.read_bytes(), str(SOURCE), 'exec'), module.__dict__)
    return module


class IdleTests(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.directory)
        self.policy = {self.m.ENABLED: True, self.m.LOCK_SECONDS: 1844,
                       self.m.DPMS_SECONDS: 3800, self.m.SUSPEND_SECONDS: 0}
        self.calls = []

    def command(self, argv, timeout=25):
        self.calls.append(argv)

    def toggle(self):
        with mock.patch.object(self.m, 'command', side_effect=self.command):
            self.m.toggle(self.directory, self.policy)

    def state(self):
        return self.m.read_state(self.directory)

    def test_toggle_round_trip_preserves_config_and_saved_values(self):
        self.policy.update({self.m.LOCK_SECONDS: 2111, self.m.DPMS_SECONDS: 4222})
        original = dict(self.policy)
        self.toggle()
        state = self.state()
        self.assertEqual([state[self.m.LOCK_SECONDS], state[self.m.DPMS_SECONDS]], [0, 0])
        self.assertEqual([state['saved_lock'], state['saved_dpms']], [2111, 4222])
        self.assertEqual(stat.S_IMODE((self.root/self.m.STATE).stat().st_mode), 0o600)
        self.assertEqual(list(self.root.glob('.labwc-idle.*')), [])
        self.toggle()
        self.assertEqual([self.state()[self.m.LOCK_SECONDS], self.state()[self.m.DPMS_SECONDS]], [2111, 4222])
        self.assertEqual(self.policy, original)
        notifications = [c for c in self.calls if c[0].endswith('labwc-notification-send')]
        self.assertEqual([c[-2] for c in notifications],
                         ['Automatic lock and DPMS disabled', 'Automatic lock and DPMS restored'])
        self.assertTrue(any(c[-2:] == ['restart', 'swayidle.service'] for c in self.calls))
        self.assertTrue(any(c[-1] == '--dpms-on' for c in self.calls))
        self.assertFalse(any('stop' in c or 'labwc-lock.service' in c for c in self.calls))

    def test_initial_zero_policy_restores_requested_defaults(self):
        self.policy.update({self.m.LOCK_SECONDS: 0, self.m.DPMS_SECONDS: 0})
        self.toggle()
        self.assertEqual([self.state()[self.m.LOCK_SECONDS], self.state()[self.m.DPMS_SECONDS]], [1844, 3800])

    def test_one_zero_timer_is_preserved_across_pause(self):
        for lock, dpms in ((0, 3800), (1844, 0)):
            with self.subTest(lock=lock, dpms=dpms):
                if self.state() is not None:
                    self.m.write_state(self.directory, None)
                self.policy.update({self.m.LOCK_SECONDS: lock, self.m.DPMS_SECONDS: dpms})
                self.toggle(); self.toggle()
                self.assertEqual([self.state()[self.m.LOCK_SECONDS], self.state()[self.m.DPMS_SECONDS]], [lock, dpms])

    def test_failed_restart_restores_absent_state_and_restarts_previous_policy(self):
        failed = False
        def command(argv, timeout=25):
            nonlocal failed
            self.calls.append(argv)
            if argv[-2:] == ['restart', 'swayidle.service'] and not failed:
                failed = True
                raise subprocess.CalledProcessError(1, argv)
        with mock.patch.object(self.m, 'command', side_effect=command), \
                self.assertRaisesRegex(self.m.Error, 'previous policy restored'):
            self.m.toggle(self.directory, self.policy)
        self.assertIsNone(self.state())
        self.assertEqual(sum(c[-2:] == ['restart', 'swayidle.service'] for c in self.calls), 2)
        self.assertFalse(any(c[0].endswith('notification-send') for c in self.calls))

    def test_output_failure_restores_existing_state(self):
        self.toggle()
        original = (self.root/self.m.STATE).read_bytes()
        def command(argv, timeout=25):
            if argv[-1] == '--dpms-on':
                raise subprocess.CalledProcessError(1, argv)
        with mock.patch.object(self.m, 'command', side_effect=command), \
                self.assertRaisesRegex(self.m.Error, 'previous policy restored'):
            self.m.toggle(self.directory, self.policy)
        self.assertEqual((self.root/self.m.STATE).read_bytes(), original)

    def test_failed_recovery_is_reported_as_failed_recovery(self):
        def command(argv, timeout=25):
            if argv[-2:] == ['restart', 'swayidle.service']:
                raise subprocess.CalledProcessError(1, argv)
        with mock.patch.object(self.m, 'command', side_effect=command), \
                self.assertRaisesRegex(self.m.Error, 'recovery failed'):
            self.m.toggle(self.directory, self.policy)
        self.assertIsNone(self.state())

    def test_disabled_installer_policy_does_not_publish_state(self):
        self.policy[self.m.ENABLED] = False
        with self.assertRaisesRegex(self.m.Error, 'disabled'):
            self.toggle()
        self.assertIsNone(self.state())
        self.assertEqual(self.calls, [])

    def test_notification_failure_restores_policy_instead_of_silently_disabling_lock(self):
        def command(argv, timeout=25):
            if argv[0].endswith('notification-send'):
                raise subprocess.CalledProcessError(1, argv)
        with mock.patch.object(self.m, 'command', side_effect=command), \
                self.assertRaisesRegex(self.m.Error, 'previous policy restored'):
            self.m.toggle(self.directory, self.policy)
        self.assertIsNone(self.state())

    def test_interruption_during_refresh_restores_policy(self):
        interrupted = False
        def command(argv, timeout=25):
            nonlocal interrupted
            if argv[-2:] == ['restart', 'swayidle.service'] and not interrupted:
                interrupted = True
                raise self.m.Error('idle toggle interrupted')
        with mock.patch.object(self.m, 'command', side_effect=command), \
                self.assertRaisesRegex(self.m.Error, 'previous policy restored'):
            self.m.toggle(self.directory, self.policy)
        self.assertIsNone(self.state())

    def test_two_concurrent_presses_are_serialized_and_restore_the_original_policy(self):
        first_restart = threading.Event()
        errors = []
        def command(argv, timeout=25):
            if argv[-2:] == ['restart', 'swayidle.service'] and not first_restart.is_set():
                first_restart.set()
                time.sleep(0.1)
        def press():
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.m.toggle(directory, self.policy)
            except BaseException as exc:
                errors.append(exc)
            finally:
                os.close(directory)
        with mock.patch.object(self.m, 'command', side_effect=command):
            first = threading.Thread(target=press); first.start()
            self.assertTrue(first_restart.wait(2))
            second = threading.Thread(target=press); second.start()
            first.join(3); second.join(3)
            self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual([self.state()[self.m.LOCK_SECONDS], self.state()[self.m.DPMS_SECONDS]], [1844, 3800])

    def test_state_symlink_hardlink_and_bad_mode_are_rejected_without_target_write(self):
        outside = self.root/'outside'; outside.write_text('unchanged')
        outside.chmod(0o600)
        path = self.root/self.m.STATE
        for kind in ('symlink', 'hardlink', 'mode'):
            with self.subTest(kind=kind):
                if kind == 'symlink': path.symlink_to(outside)
                elif kind == 'hardlink': os.link(outside, path)
                else: path.write_text('{}'); path.chmod(0o644)
                with self.assertRaises((OSError, self.m.Error)):
                    self.toggle()
                path.unlink()
                self.assertEqual(outside.read_text(), 'unchanged')

    def test_invalid_and_duplicate_json_fields_are_rejected(self):
        good = {self.m.LOCK_SECONDS: 0, self.m.DPMS_SECONDS: 0, 'saved_lock': 1844, 'saved_dpms': 3800}
        invalid = ['{}', '[]', '{"saved_lock":1,"saved_lock":2}', json.dumps({**good, 'saved_lock': True}),
                   json.dumps({**good, 'saved_dpms': 1}), json.dumps({**good, self.m.LOCK_SECONDS: -1})]
        for text in invalid:
            path = self.root/self.m.STATE; path.write_text(text); path.chmod(0o600)
            with self.subTest(text=text), self.assertRaises((self.m.Error, ValueError)):
                self.state()

    def test_zero_is_omitted_and_sleep_locks_survive_the_pause(self):
        self.policy[self.m.SUSPEND_SECONDS] = 7200
        paused = {self.m.LOCK_SECONDS: 0, self.m.DPMS_SECONDS: 0, 'saved_lock': 1844, 'saved_dpms': 3800}
        argv = self.m.daemon_argv(self.policy, paused)
        self.assertNotIn('timeout', argv)
        self.assertEqual(argv[1:4], ['-C', '/dev/null', '-w'])
        self.assertIn('before-sleep', argv)
        self.assertIn('after-resume', argv)
        self.assertEqual(argv[-2:], ['lock', '/usr/local/bin/labwc-lock'])
        active = self.m.daemon_argv(self.policy, None)
        self.assertEqual([active[i+1] for i, v in enumerate(active) if v == 'timeout'], ['1844', '3800', '7200'])

    def test_timeout_order_and_scalar_bounds_allow_disabled_timers(self):
        for values in ((0, 0, 0), (0, 3800, 7200), (1844, 0, 7200), (1844, 3800, 0)):
            self.m.validate_timeouts(*values)
        for values in ((-1, 3800, 0), (True, 3800, 0), (1844, 1844, 0), (0, 86401, 0), (1844, 0, 100)):
            with self.subTest(values=values), self.assertRaises(self.m.Error):
                self.m.validate_timeouts(*values)

    def test_run_reads_current_atomic_state_and_closes_its_directory_before_exec(self):
        self.toggle()
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        with mock.patch.object(self.m, 'read_policy', return_value=self.policy), \
                mock.patch.object(self.m, 'runtime_fd', return_value=directory), \
                mock.patch.object(self.m.os, 'execv') as execute:
            self.m.main(['--run'])
        self.assertNotIn('timeout', execute.call_args.args[1])
        with self.assertRaises(OSError): os.fstat(directory)

    @unittest.skipUnless(os.getuid() == 0, 'root-owned policy fixture')
    def test_policy_is_literal_and_rejects_duplicates_unsafe_metadata_and_code(self):
        path = self.root/'desktop.conf'
        text = "LABWC_ENABLE_SWAYIDLE='true'\nLABWC_IDLE_LOCK_SECONDS='1844'\nLABWC_IDLE_DPMS_SECONDS='3800'\nLABWC_IDLE_SUSPEND_SECONDS='0'\n"
        path.write_text(text); path.chmod(0o644)
        with mock.patch.object(self.m, 'CONFIG', path):
            self.assertEqual(self.m.read_policy(), self.policy)
            path.write_text(text.replace("'1844'", "'01844'").replace("'0'", "'000'"))
            self.assertEqual(self.m.read_policy(), self.policy)
            for content in (text + "LABWC_IDLE_LOCK_SECONDS='0'\n", text.replace("'1844'", "'$(id)'"),
                            text.replace("'3800'", "'1800'")):
                path.write_text(content)
                with self.assertRaises(self.m.Error): self.m.read_policy()
            path.write_text(text); path.chmod(0o666)
            with self.assertRaises(self.m.Error): self.m.read_policy()


class WiringTests(unittest.TestCase):
    def test_lock_service_uses_host_namespace_independent_cgroup_and_readiness(self):
        unit = (TARGET/'etc/systemd/user/labwc-lock.service').read_text()
        for setting in ('Type=forking', 'ExitType=cgroup', 'GuessMainPID=no', 'NoNewPrivileges=no',
                        'PrivateUsers=no', 'PrivatePIDs=no', 'PartOf=labwc-session.target',
                        'ExecStart=/usr/local/libexec/labwc-swaylock', 'KillMode=control-group'):
            self.assertIn(setting, unit)
        self.assertNotIn('WantedBy=', unit)
        helper = (TARGET/'usr/local/libexec/labwc-swaylock.tmpl').read_text()
        self.assertIn('/proc/self/gid_map', helper)
        self.assertIn('NoNewPrivs:', helper)
        self.assertIn('/usr/bin/swaylock -f ', helper)
        pam = (TARGET/'etc/pam.d/swaylock').read_text()
        self.assertIn('@include common-auth', pam)
        self.assertIn('@include common-account', pam)
        self.assertNotIn('pam_permit', pam)

    def test_locker_refuses_no_new_privileges_before_acquiring_a_lock(self):
        helper = TARGET/'usr/local/libexec/labwc-swaylock.tmpl'
        result = subprocess.run(['/usr/bin/setpriv', '--no-new-privs', '/bin/sh', str(helper)],
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires the host user namespace and NoNewPrivileges=no', result.stderr)

    def test_new_files_are_staged_and_lock_unit_is_never_checked_as_executable(self):
        staging = (SEED/'scripts/desktop/components/target-assets.sh').read_text()
        for path, mode in (('usr/local/bin/labwc-idle-toggle', '0755'),
                           ('usr/local/libexec/labwc-swaylock', '0755'),
                           ('etc/systemd/user/labwc-lock.service', '0644')):
            self.assertIn(f'desktop_stage_role_asset {path} /{path} {mode}', staging)
        verification = (SEED/'scripts/desktop/verify.sh.tmpl').read_text()
        self.assertEqual(verification.count('/etc/systemd/user/labwc-lock.service \\\n'), 1)
        self.assertEqual(verification.count('seen_bindings = set()'), 1)
        self.assertIn('ge 1.8.6', verification)
        self.assertIn('InhibitDelayMaxSec=30s', (TARGET/'etc/systemd/logind.conf.d/70-labwc-lock.conf').read_text())
        session = (TARGET/'usr/local/bin/labwc-session.tmpl').read_text()
        self.assertEqual(session.count('/usr/bin/rm -f -- "$XDG_RUNTIME_DIR/labwc-idle.json"'), 2)

    def test_hotkeys_have_no_modifier_order_collisions_and_chords_use_release(self):
        root = ET.fromstring((TARGET/'etc/skel-desktop/.config/labwc/rc.xml.tmpl').read_text())
        seen = set(); bindings = {}
        for binding in root.findall('keyboard/keybind'):
            key = binding.get('key'); parts = key.split('-')
            normalized = (frozenset(parts[:-1]), parts[-1].lower())
            self.assertNotIn(normalized, seen); seen.add(normalized)
            bindings[key] = binding
        for key, command in (('C-l', '/usr/local/bin/labwc-lock'), ('W-l', '/usr/local/bin/labwc-lock'),
                             ('C-W-l', '/usr/local/bin/labwc-idle-toggle')):
            self.assertEqual(bindings[key].get('onRelease'), 'yes')
            self.assertEqual(bindings[key].find('action').get('command'), command)
        self.assertEqual(bindings['C-Super_L'].get('onRelease'), 'yes')

    def test_idle_notifications_remain_visible_in_do_not_disturb(self):
        mako = (TARGET/'etc/skel-desktop/.config/mako/config.tmpl').read_text()
        do_not_disturb = mako.index('[mode=do-not-disturb]\ninvisible=1')
        idle = mako.index('[app-name="Labwc Idle" category=desktop.idle]\ninvisible=0')
        self.assertGreater(idle, do_not_disturb)
        module = load()
        with mock.patch.object(module, 'command') as command:
            module.notify('Automatic lock and DPMS disabled', 'Saved delays: lock 1844s, DPMS 3800s.')
        argv = command.call_args.args[0]
        self.assertEqual(argv[argv.index('--app-name')+1], 'Labwc Idle')
        self.assertEqual(argv[argv.index('--category')+1], 'desktop.idle')

    def test_lock_client_waits_for_manager_and_propagates_failed_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); calls = root/'calls'
            try:
                sock = socket.socket(socket.AF_UNIX)
            except PermissionError:
                self.skipTest('execution sandbox prohibits Unix sockets')
            self.addCleanup(sock.close); sock.bind(str(root/'wayland-1'))
            identity = root/'id'; identity.write_text('#!/bin/sh\nprintf "1000\\n"\n'); identity.chmod(0o700)
            manager = root/'systemctl'
            manager.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n'
                               'case "$*" in *"start labwc-lock.service"*) exit "${FAIL_LOCK:-0}" ;; esac\n')
            manager.chmod(0o700)
            source = (TARGET/'usr/local/bin/labwc-lock.tmpl').read_text()
            source = source.replace('"/run/user/$uid"', shlex.quote(str(root)))
            source = source.replace('/usr/bin/id', str(identity)).replace('/usr/bin/systemctl', str(manager))
            env = {**os.environ, 'XDG_RUNTIME_DIR': str(root), 'LABWC_SESSION_OWNER': 'desktop',
                   'XDG_SESSION_TYPE': 'wayland', 'WAYLAND_DISPLAY': 'wayland-1', 'CALLS': str(calls)}
            result = subprocess.run(['/bin/sh', '-c', source], env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls.read_text().splitlines()[-2:],
                             ['--user start labwc-lock.service', '--user --quiet is-active labwc-lock.service'])
            env['FAIL_LOCK'] = '1'
            result = subprocess.run(['/bin/sh', '-c', source], env=env, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('screen lock failed', result.stderr)


if __name__ == '__main__':
    unittest.main()
