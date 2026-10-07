"""Hardware menu discoverability, bounded broker waits and unchanged gates."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1]/'hooks/target'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


management = load('management_hardware_visibility', TARGET/'usr/local/bin/labwc-computer-management')
common = load('management_hardware_common', TARGET/'usr/local/lib/hardware_tuning/common.py')
with mock.patch.dict(sys.modules, {'common': common}):
    client = load('management_hardware_client', TARGET/'usr/local/lib/hardware_tuning/client.py')


class HardwareVisibilityTests(unittest.TestCase):
    def test_top_level_and_nested_entries_are_always_visible(self):
        with mock.patch.object(management, 'choose', side_effect=['Hardware Tuning', 'Exit']) as choose, mock.patch.object(management, 'open_hardware_tuning') as tuning:
            self.assertEqual(management.run_menu(), 0)
        self.assertIn('Hardware Tuning', choose.call_args_list[0].args[0])
        tuning.assert_called_once_with()
        with mock.patch.object(management, 'choose', side_effect=['Devices & Desktop', 'Hardware Tuning', 'Back', 'Exit']) as choose, mock.patch.object(management, 'open_hardware_tuning') as tuning:
            self.assertEqual(management.run_menu(), 0)
        self.assertIn('Hardware Tuning', choose.call_args_list[1].args[0])
        tuning.assert_called_once_with()

    def test_uninstalled_gated_client_explains_without_enabling_hardware(self):
        with mock.patch.object(management.Path, 'is_file', return_value=False), mock.patch.object(management, 'choose', return_value='Back') as choose, mock.patch.object(management, 'run_action') as action:
            self.assertEqual(management.open_hardware_tuning(), 0)
        action.assert_not_called()
        self.assertEqual(choose.call_args.args[0], ['Back'])
        self.assertIn('host enable flags / hardware / addon gates', choose.call_args.args[1])

    def test_installed_client_uses_only_existing_allowlisted_dispatch(self):
        with mock.patch.object(management.Path, 'is_file', return_value=True), mock.patch.object(management.os, 'access', return_value=True), mock.patch.object(management, 'run_action', return_value=0) as action, mock.patch.object(management, 'choose') as choose:
            self.assertEqual(management.open_hardware_tuning(), 0)
        action.assert_called_once_with(('labwc-hardware-tuning', 'menu'))
        choose.assert_not_called()

    def test_failed_client_is_visible_and_recoverable(self):
        with mock.patch.object(management.Path, 'is_file', return_value=True), mock.patch.object(management.os, 'access', return_value=True), mock.patch.object(management, 'run_action', return_value=1), mock.patch.object(management, 'choose', return_value='Back') as choose:
            self.assertEqual(management.open_hardware_tuning(), 1)
        self.assertIn('hardware-tuning.service', choose.call_args.args[1])

    def test_picker_rejects_freeform_command_output(self):
        reply = subprocess.CompletedProcess([], 0, 'Hardware Tuning; id\n')
        with mock.patch.object(management.subprocess, 'run', return_value=reply):
            self.assertIsNone(management.choose(['Hardware Tuning', 'Exit'], 'Computer Management'))

    def test_status_and_back_are_read_only(self):
        for selection in ('Show Hardware Tuning Status', 'Back', None):
            with mock.patch.object(client, 'request', return_value={'vendors': ['intel'], 'automatic': False}) as request, mock.patch.object(client, 'choose', return_value=selection) as choose, mock.patch.object(client, 'notify') as notify:
                self.assertEqual(client.menu(), 0)
            request.assert_called_once_with('status')
            self.assertIn('Back', choose.call_args.args[0])
            self.assertIn('Show Hardware Tuning Status', choose.call_args.args[0])
            self.assertEqual(notify.call_count, int(selection == 'Show Hardware Tuning Status'))

    def test_status_connect_and_response_have_short_timeouts(self):
        channel = mock.Mock()
        channel.recv.return_value = b'{"ok":true,"result":{"vendors":["intel"]}}\n'
        with mock.patch.object(client.socket, 'socket', return_value=channel), mock.patch.object(client.time, 'monotonic', return_value=100):
            connection, result = client.connect_request({'action': 'status'})
        self.assertIs(connection, channel)
        self.assertEqual(result['vendors'], ['intel'])
        self.assertEqual([call.args[0] for call in channel.settimeout.call_args_list], [5, 15, 15])
        channel.close.assert_not_called()
        connection.close()

    def test_slow_response_cannot_extend_overall_deadline(self):
        channel = mock.Mock()
        channel.recv.return_value = b'{'
        with mock.patch.object(client.socket, 'socket', return_value=channel), mock.patch.object(client.time, 'monotonic', side_effect=[100, 100, 101, 116]):
            with self.assertRaises(TimeoutError):
                client.connect_request({'action': 'status'})
        channel.close.assert_called_once_with()
        self.assertEqual(channel.recv.call_count, 1)

    def test_mutation_retains_existing_transaction_allowance(self):
        channel = mock.Mock()
        channel.recv.return_value = b'{"ok":true,"result":{}}\n'
        with mock.patch.object(client.socket, 'socket', return_value=channel), mock.patch.object(client.time, 'monotonic', return_value=100):
            connection, result = client.connect_request({'action': 'manual', 'vendor': 'intel', 'profile': 'balanced'})
        self.assertEqual([call.args[0] for call in channel.settimeout.call_args_list], [5, 360, 360])
        connection.close()


if __name__ == '__main__':
    unittest.main()
