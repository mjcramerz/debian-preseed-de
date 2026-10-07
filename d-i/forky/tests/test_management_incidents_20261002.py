"""Offline firmware dispatch and appearance namespace regressions.

All commands use temporary fixtures: no daemon, GUI or firmware is operated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
from payload_fixture import python_library

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
HELPER = TARGET / 'usr/local/libexec/labwc-system-action-root'


class FirmwareActionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.calls = self.root / 'calls'
        for name, body in {
            'id': '[ "$*" = "-u" ] || exit 90; printf "0\\n"',
            'getent': '[ "$*" = "passwd 1000" ] || exit 90',
        }.items():
            command = self.root / name
            command.write_text('#!/bin/sh\n' + body + '\n'); command.chmod(0o700)
        command = self.root / 'fwupdmgr'
        command.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
with open(os.environ['FW_TEST_CALLS'], 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
commands = {'refresh': 'REFRESH', 'get-updates': 'QUERY',
            'get-devices': 'DEVICES', 'update': 'UPDATE'}
selected = [item for item in sys.argv[1:] if item in commands]
if len(selected) != 1:
    sys.exit(90)
sys.exit(int(os.environ.get('FW_TEST_' + commands[selected[0]] + '_STATUS', '0')))
''')
        command.chmod(0o700)
        source = HELPER.read_text()
        original = 'PATH=/usr/sbin:/usr/bin:/sbin:/bin'
        self.assertEqual(source.count(original), 1)
        self.helper = self.root / 'helper'
        self.helper.write_text(source.replace(original, 'PATH=' + str(self.root)))

    def invoke(self, action, *arguments, **environment):
        self.calls.unlink(missing_ok=True)
        result = subprocess.run(['/bin/sh', str(self.helper), action, *arguments],
            env={**os.environ, 'PKEXEC_UID': '1000', 'FW_TEST_CALLS': str(self.calls), **environment},
            capture_output=True, text=True, timeout=5)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        for call in calls:
            self.assertEqual(call[:4], ['--assume-yes', '--no-unreported-check',
                                        '--no-remote-check', '--no-reboot-check'])
            self.assertTrue({'--no-safety-check', '--ignore-power', '--allow-older',
                             '--allow-reinstall', '--disable-ssl-strict'}.isdisjoint(call))
        return result, calls

    def test_no_updates_is_success_after_metadata_refresh(self):
        for status in ('0', '2'):
            with self.subTest(refresh=status):
                result, calls = self.invoke('firmware-updates', FW_TEST_REFRESH_STATUS=status,
                                            FW_TEST_QUERY_STATUS='2')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('nothing to do', result.stdout)
                self.assertEqual([call[4:] for call in calls],
                                 [['refresh'], ['--no-metadata-check', 'get-updates']])

    def test_real_errors_survive_and_refresh_failure_stops_the_query(self):
        for status in ('1', '3', '7'):
            with self.subTest(status=status):
                result, calls = self.invoke('firmware-updates', FW_TEST_REFRESH_STATUS=status)
                self.assertEqual(result.returncode, int(status)); self.assertEqual(len(calls), 1)
                result, calls = self.invoke('firmware-updates', FW_TEST_QUERY_STATUS=status)
                self.assertEqual(result.returncode, int(status)); self.assertEqual(len(calls), 2)

    def test_device_listing_and_explicit_refresh_handle_no_action(self):
        for action, expected, variable in (
                ('firmware-devices', ['get-devices'], 'FW_TEST_DEVICES_STATUS'),
                ('refresh-firmware-metadata', ['refresh', '--force'], 'FW_TEST_REFRESH_STATUS')):
            with self.subTest(action=action):
                result, calls = self.invoke(action, **{variable: '2'})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls[0][4:], expected)
                result, calls = self.invoke(action, 'unexpected')
                self.assertNotEqual(result.returncode, 0); self.assertEqual(calls, [])

    def test_update_requires_exact_confirmation_and_retains_safety_checks(self):
        for arguments in ((), ('wrong',), ('confirmed-system-action', 'extra')):
            with self.subTest(arguments=arguments):
                result, calls = self.invoke('apply-firmware-updates', *arguments)
                self.assertNotEqual(result.returncode, 0); self.assertEqual(calls, [])
        for status in ('0', '2', '1', '3'):
            with self.subTest(status=status):
                result, calls = self.invoke('apply-firmware-updates', 'confirmed-system-action',
                                            FW_TEST_UPDATE_STATUS=status)
                self.assertEqual(result.returncode, 0 if status == '2' else int(status))
                self.assertEqual([call[4:] for call in calls],
                                 [['refresh'], ['--no-metadata-check', 'update']])
                self.assertTrue(all('--force' not in call for call in calls))
                self.assertEqual('perform it manually' in result.stdout, status in ('0', '2'))
        result, calls = self.invoke('apply-firmware-updates', 'confirmed-system-action',
                                    FW_TEST_REFRESH_STATUS='1')
        self.assertEqual(result.returncode, 1); self.assertEqual(len(calls), 1)


class AppearanceLaunchTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(sys, 'path', [
            str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')), *sys.path]))
        from labwc_managed_app import generic
        self.generic = generic

    def argv(self, kind, arguments):
        with mock.patch.object(self.generic, 'assert_launch_allowed'), \
             mock.patch.object(self.generic, 'restart_token', return_value='fixture'), \
             mock.patch.dict(os.environ, {'LABWC_MENU_ACTION_WAIT': '1'}):
            return self.generic.transient_argv(kind, 'auto', arguments, {})

    def test_appearance_has_host_uid_semantics_and_waits_for_its_session_service(self):
        argv = self.argv('wayland', ['/usr/local/bin/labwc-desktop-appearance'])
        for property in ('PrivateUsers=no', 'PrivatePIDs=no', 'PartOf=labwc-session.target',
                         'Requisite=labwc-session.target', 'KillMode=control-group', 'ExitType=cgroup'):
            self.assertIn('--property=' + property, argv)
        self.assertIn('--wait', argv)
        self.assertNotIn('--property=PrivateTmp=yes', argv)
        self.assertEqual(argv[argv.index('--') + 1:], ['/usr/local/bin/labwc-desktop-appearance'])

    def test_lookalike_paths_and_other_launcher_kind_keep_generic_isolation(self):
        for kind, path in (('wayland', '/tmp/labwc-desktop-appearance'),
                           ('wayland', '/usr/local/bin/labwc-desktop-appearance-other'),
                           ('electron', '/usr/local/bin/labwc-desktop-appearance')):
            with self.subTest(kind=kind, path=path):
                argv = self.argv(kind, [path])
                self.assertIn('--property=PrivateTmp=yes', argv)
                self.assertNotIn('--property=PrivateUsers=no', argv)

    def test_management_dispatch_hands_off_exact_appearance_workflow_and_preserves_status(self):
        module = types.ModuleType('management_fixture')
        source = TARGET / 'usr/local/bin/labwc-computer-management'
        exec(compile(source.read_bytes(), str(source), 'exec'), module.__dict__)
        with mock.patch.object(module.Path, 'is_file', return_value=False), \
             mock.patch.object(module.subprocess, 'run', return_value=types.SimpleNamespace(returncode=5)) as run:
            self.assertEqual(module.run_action(('labwc-desktop-appearance',)), 5)
            self.assertEqual(run.call_args.args[0], ('/usr/local/bin/labwc-wayland-app', 'auto', '--',
                                                    '/usr/local/bin/labwc-desktop-appearance'))
            self.assertEqual(module.run_action(('labwc-display-configuration',)), 5)
            self.assertEqual(run.call_args.args[0], ('/usr/local/bin/labwc-display-configuration',))
