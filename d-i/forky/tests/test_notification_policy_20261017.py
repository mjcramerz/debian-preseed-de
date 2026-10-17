#!/usr/bin/env python3
"""Notification policy fixtures; execute only in the prepared disposable image."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'hooks/target/usr/local/libexec/labwc-plans.pl'
FAKE_TOKEN = '12345:' + 'x' * 24
PROGRAM = r'''
use strict;
use warnings;
do $ARGV[0] or die "cannot load fixture source: $@ $!";
my $base = LabwcPlans::Config->from_environment();
my $config = LabwcPlans::Config->new({%{$base}, policy_file => $ARGV[1]});
if ($ARGV[2] eq 'enabled') {
    print $config->channel_enabled($ARGV[3]) ? "enabled\n" : "disabled\n";
} elsif ($ARGV[2] eq 'send') {
    my $transport = LabwcPlans::Transport->new(config => $config,
        dry_run => 0, logger => LabwcPlans::Logger->new(), http => bless({}, 'NoNetwork'));
    my $result = $transport->send($ARGV[3], {id => 'a' x 64, message => 'fixture', title => 'fixture'});
    print JSON::PP->new()->canonical()->encode($result), "\n";
} elsif ($ARGV[2] eq 'cancel') {
    my $store = LabwcPlans::State->new(directory => $ARGV[3], max_bytes => 1_048_576,
        logger => LabwcPlans::Logger->new());
    $store->acquire_lock();
    $store->load();
    $store->cancel_disabled_channels($config);
    print JSON::PP->new()->canonical()->encode($store->state()), "\n";
} else { die "invalid fixture action\n"; }
package NoNetwork;
sub request { die "fixture must never make an HTTP request\n"; }
'''


@unittest.skipUnless(os.geteuid() == 0, 'policy fixtures require namespace UID 0 in the disposable image')
class NotificationPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='notification-policy-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.policy = self.root / 'plans.conf'
        self.environment = {
            'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'LC_ALL': 'C.UTF-8',
            'LABWC_PLANS_ENABLED': 'true', 'LABWC_PLANS_TELEGRAM_ENABLED': 'true',
            'LABWC_PLANS_TELEGRAM_API_KEY': FAKE_TOKEN, 'LABWC_PLANS_TELEGRAM_CHAT_ID': '12345',
            'LABWC_PLANS_NTFY_ENABLED': 'false',
        }
        self.write_policy()

    def write_policy(self, **overrides):
        values = {
            'LABWC_PLANS_ENABLED': 'true', 'LABWC_PLANS_TELEGRAM_ENABLED': 'true',
            'LABWC_PLANS_TELEGRAM_API_BASE': 'https://api.telegram.org',
            'LABWC_PLANS_TELEGRAM_API_KEY': FAKE_TOKEN, 'LABWC_PLANS_TELEGRAM_CHAT_ID': '12345',
            'LABWC_PLANS_NTFY_ENABLED': 'false', 'LABWC_PLANS_NTFY_BASE_URL': 'https://ntfy.sh',
            'LABWC_PLANS_NTFY_TOPIC': '', 'LABWC_PLANS_NTFY_ACCESS_TOKEN': '',
            'LABWC_PLANS_NTFY_READER_ACCESS_CONFIRMED': 'false',
        }
        values.update(overrides)
        self.policy.write_text(''.join(f"{key}='{value}'\n" for key, value in values.items()), encoding='utf-8')
        self.policy.chmod(0o600)

    def run_fixture(self, action, argument, *, success=True):
        result = subprocess.run(['/usr/bin/perl', '-e', PROGRAM, str(SOURCE), str(self.policy),
                                 action, str(argument)], env=self.environment, cwd=self.root,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_ntfy_default_never_reaches_transport(self):
        result = json.loads(self.run_fixture('send', 'ntfy').stdout)
        self.assertFalse(result['ok'])
        self.assertTrue(result['disabled'])

    def test_live_disable_overrides_running_environment(self):
        self.write_policy(LABWC_PLANS_TELEGRAM_ENABLED='false')
        result = json.loads(self.run_fixture('send', 'telegram').stdout)
        self.assertTrue(result['disabled'])

    def test_ntfy_policy_change_does_not_disable_telegram(self):
        self.write_policy(LABWC_PLANS_NTFY_TOPIC='another-topic')
        self.assertEqual(self.run_fixture('enabled', 'telegram').stdout, 'enabled\n')

    def test_destination_change_cannot_send_using_old_environment(self):
        self.write_policy(LABWC_PLANS_TELEGRAM_CHAT_ID='54321')
        self.assertTrue(json.loads(self.run_fixture('send', 'telegram').stdout)['disabled'])

    def test_unsafe_policy_is_rejected_before_transport(self):
        self.policy.chmod(0o660)
        self.run_fixture('send', 'telegram', success=False)
        self.policy.chmod(0o600)
        alias = self.root / 'alias'
        alias.symlink_to(self.policy.name)
        self.policy = alias
        self.run_fixture('send', 'telegram', success=False)

    def test_hardlinked_policy_is_rejected_before_transport(self):
        os.link(self.policy, self.root / 'second-name')
        result = self.run_fixture('send', 'telegram', success=False)
        self.assertIn('unsafe notification policy file', result.stderr)

    def test_global_disable_cancels_persisted_backlog_without_resurrection(self):
        state_dir = self.root / 'state'
        state_dir.mkdir(mode=0o700)
        identifier = 'a' * 64
        state = {
            'version': 1, 'initialized': 1, 'last_scan_epoch': 0, 'seen_entries': {}, 'sent': {},
            'notifications': {identifier: {
                'id': identifier, 'created_epoch': 0, 'due_epoch': 0, 'priority': 'A',
                'title': 'fixture', 'message': 'fixture',
                'channels': {name: {'status': 'pending', 'attempts': 0, 'next_attempt': 0}
                             for name in ('telegram', 'ntfy')},
            }},
        }
        path = state_dir / 'state.json'
        path.write_text(json.dumps(state), encoding='utf-8')
        path.chmod(0o600)
        self.write_policy(LABWC_PLANS_ENABLED='false')
        first = json.loads(self.run_fixture('cancel', state_dir).stdout)
        self.assertEqual({row['status'] for row in first['notifications'][identifier]['channels'].values()}, {'disabled'})
        self.write_policy()
        second = json.loads(self.run_fixture('cancel', state_dir).stdout)
        self.assertEqual(second['notifications'], first['notifications'])


if __name__ == '__main__':
    unittest.main()
