"""Notification placement/click/size regression tests, without live host changes."""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from payload_fixture import installed_argv as payload_installed_argv
from payload_fixture import read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values

import contextlib
import configparser
import ctypes.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from test_native_tomat_20260920 import FORKY, SKEL, bars, load


def rendered_profile_styles(output_class='external'):
    from waybar_fixture import profiles, style
    return {p.stem: style(p, output_class) for p in profiles()}


class NotificationsFollowupTests(unittest.TestCase):
    def test_mako_enforces_urgency_timeouts_without_application_overrides(self):
        policy = configparser.ConfigParser(interpolation=None)
        policy.read_string('[global]\n' + payload_read_text(SKEL / 'mako/config'))
        self.assertEqual(policy.get('global', 'ignore-timeout'), '1')
        self.assertEqual(policy.get('global', 'default-timeout'), '5000')
        for urgency, timeout in (('low', '5000'), ('normal', '10000'), ('critical', '15000')):
            self.assertEqual(policy.get('urgency=' + urgency, 'default-timeout'), timeout)
        for section in policy.sections():
            if section != 'global':
                self.assertFalse(policy.has_option(section, 'ignore-timeout'), section)
                if not section.startswith('urgency='):
                    self.assertFalse(policy.has_option(section, 'default-timeout'), section)

    def test_both_real_bar_layouts_end_with_controls_notifications_lock_power(self):
        configurations = bars()
        self.assertEqual(len(configurations), 2)
        for bar in configurations:
            with self.subTest(bar=bar['name']):
                controls = 'group/quick-controls'
                right = bar['modules-right']
                self.assertEqual(right[-4:], [controls, 'custom/notifications', 'custom/lock', 'custom/power'])
                self.assertEqual(right.count('custom/notifications'), 1)
                self.assertEqual(right[right.index(controls) - 2], 'memory')
                self.assertEqual(right[right.index(controls) - 1], 'tray')
                self.assertNotIn('custom/notifications', bar[controls]['modules'])

    def test_forky_waybar_enables_sni_tray_by_default(self):
        for bar in bars():
            self.assertIn('tray', bar['modules-left'] + bar['modules-right'])

    def test_every_host_profile_declares_the_same_enabled_tray_policy(self):
        profiles = sorted((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertTrue(profiles)
        for profile in profiles:
            matches = re.findall(
                r'(?m)^LABWC_WAYBAR_TRAY_ENABLE="([^"]*)"$',
                profile.read_text(encoding='utf-8'),
            )
            self.assertEqual(matches, ['true'], profile.name)

    def test_json_bell_is_outside_the_drawer_on_every_output_profile(self):
        from waybar_fixture import profiles, rendered_assets
        host_profiles = profiles()
        self.assertEqual(len(host_profiles), 10)
        for profile in host_profiles:
            configurations = json.loads(rendered_assets(profile)['config'])
            self.assertEqual([bar['name'] for bar in configurations], ['internal', 'external'])
            for bar in configurations:
                with self.subTest(profile=profile.name, output=bar['name']):
                    self.assertEqual(bar['modules-right'].count('custom/notifications'), 1)
                    self.assertNotIn('custom/notifications', bar['group/quick-controls']['modules'])
                    self.assertEqual(bar['modules-right'][-3:],
                                     ['custom/notifications', 'custom/lock', 'custom/power'])
                    entry = bar['custom/notifications']
                    self.assertEqual(entry['format'], '{}')
                    self.assertEqual(entry['return-type'], 'json')
                    self.assertTrue(entry['escape'])
                    self.assertEqual(entry['exec'], '/usr/local/libexec/labwc-waybar-exec '
                                     '/usr/local/libexec/labwc-waybar-events notifications')
                    self.assertEqual(entry['restart-interval'], 30)
                    self.assertFalse(entry['exec-on-event'])
                    for key in ('exec-if', 'interval', 'signal', 'hide-empty-text'):
                        self.assertNotIn(key, entry)
                    self.assertTrue(entry['tooltip'])
                    self.assertNotIn('tooltip-format', entry)

    def test_left_click_opens_the_same_native_gtk_dropdown_on_all_profiles(self):
        from waybar_fixture import profiles, rendered_assets
        for profile in profiles():
            assets = rendered_assets(profile)
            menu = ET.fromstring(assets['notifications-menu.xml'])
            self.assertIsNotNone(menu.find('./object[@class="GtkMenu"][@id="menu"]'))
            actions = {item.get('id') for item in menu.iter('object')
                       if item.get('class') == 'GtkMenuItem' and item.get('id')}
            for bar in json.loads(assets['config']):
                with self.subTest(profile=profile.name, output=bar['name']):
                    entry = bar['custom/notifications']
                    self.assertEqual(entry['menu'], 'on-click')
                    self.assertNotIn('on-click', entry)
                    self.assertNotIn('on-click-release', entry)
                    self.assertNotIn('on-click', entry.get('actions', {}))
                    self.assertEqual(entry['menu-file'], '~/.config/waybar/notifications-menu.xml')
                    self.assertEqual(set(entry['menu-actions']), actions)

    def test_native_left_click_menu_has_no_competing_left_click_command(self):
        for bar in bars():
            entry = bar['custom/notifications']
            self.assertEqual(entry['menu'], 'on-click')
            self.assertNotIn('on-click', entry)
            self.assertNotIn('on-click-release', entry)
            self.assertTrue(entry['on-click-middle'].endswith(' -- /usr/local/libexec/labwc-notifications dnd'))
            self.assertTrue(entry['on-click-right'].endswith(' -- /usr/local/libexec/labwc-notifications dnd-dismiss'))
            self.assertEqual(entry['format'], '{}')
            self.assertTrue(entry['escape'])
            self.assertEqual(entry['return-type'], 'json')
            self.assertEqual(entry['menu-file'], '~/.config/waybar/notifications-menu.xml')
            self.assertEqual(set(entry['menu-actions']), {
                'notifications_dnd', 'notifications_clear', 'notifications_center',
                'notifications_dnd_on', 'notifications_dnd_off', 'notifications_restore', 'notifications_dismiss'})
            for action in entry['menu-actions'].values():
                for option in ('--user', '--service-type=exec', '--expand-environment=no',
                               '--property=Requisite=labwc-session.target',
                               '--property=PartOf=labwc-session.target',
                               '--property=ExitType=cgroup', '--property=KillMode=control-group'):
                    self.assertIn(option, action)

    def test_status_uses_bell_icons_and_describes_actual_mouse_bindings(self):
        helper = load('labwc-notifications')
        for modes, icon, state in (('default\n', '\U0001f514', 'normal'),
                                   ('default\ndo-not-disturb\n', '\U0001f515', 'dnd')):
            with self.subTest(state=state), mock.patch.object(helper, 'environment', return_value={}), \
                    mock.patch.object(helper, 'mako', return_value=modes) as mako:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(helper.main(['status']), 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result['text'], icon)
                self.assertEqual(result['class'], state)
                self.assertIn('Left: menu | Middle: DND | Right: DND on + dismiss all', result['tooltip'])
                mako.assert_called_once_with(['mode'], {})

    def test_right_click_enables_dnd_before_dismissing_all_and_never_toggles(self):
        helper = load('labwc-notifications')
        with mock.patch.object(helper, 'environment', return_value={}), \
                mock.patch.object(helper, 'mako', return_value='') as mako:
            for _ in range(2):
                self.assertEqual(helper.main(['dnd-dismiss']), 0)
            self.assertEqual(mako.call_args_list, [
                mock.call(['mode', '-a', 'do-not-disturb'], {}),
                mock.call(['dismiss', '--all'], {}),
            ] * 2)

    def test_right_click_propagates_each_failure_without_retry_or_unmuting(self):
        helper = load('labwc-notifications')
        expected = [mock.call(['mode', '-a', 'do-not-disturb'], {}),
                    mock.call(['dismiss', '--all'], {})]
        for failure_index in (0, 1):
            error = helper.Error('fixture request failed')
            with self.subTest(failure_index=failure_index), \
                    mock.patch.object(helper, 'environment', return_value={}), \
                    mock.patch.object(helper, 'mako', side_effect=[''] * failure_index + [error]) as mako:
                with self.assertRaises(helper.Error) as raised:
                    helper.main(['dnd-dismiss'])
                self.assertIs(raised.exception, error)
                self.assertEqual(mako.call_args_list, expected[:failure_index + 1])

    def test_every_desktop_profile_css_resolves_session_geometry(self):
        styles = rendered_profile_styles()
        self.assertEqual(len(styles), 10)
        for name, css in styles.items():
            with self.subTest(profile=name):
                self.assertNotIn('__INSTALLER_', css)
                for module in ('notifications', 'lock', 'power'):
                    self.assertIn('#custom-' + module + ' {', css)
                    self.assertIn('#custom-' + module + ' {', css)
                self.assertIn('#custom-notifications:hover {\n  background: ' +
                              theme_values()['WAYBAR_BUTTON_NOTIFICATIONS_HOVER_BACKGROUND_COLOR'] + ';', css)

    def test_native_gtk_sizes_fonts_and_gold_hover_for_all_profiles(self):
        if not shutil.which('xvfb-run') or not ctypes.util.find_library('gtk-3'):
            self.skipTest('native GTK3 / Xvfb unavailable')
        with tempfile.TemporaryDirectory() as work:
            paths = []
            for name, css in rendered_profile_styles().items():
                path = Path(work) / (name + '.css')
                path.write_text(css)
                paths.append(str(path))
            # This probes GTK labels with Waybar's CSS names/classes; it does not
            # claim Wayland compositor or input-event integration acceptance.
            result = subprocess.run(
                payload_installed_argv(['xvfb-run', '-a', '/usr/bin/python3', '-I', '-B',
                 str(FORKY / 'tests/fixtures/waybar-session-buttons-gtk.py'), *paths]),
                env={**os.environ, 'GDK_BACKEND': 'x11', 'NO_AT_BRIDGE': '1'},
                text=True, capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['gtk_cases'], 10 * 2 * 2 * 2)
            self.assertEqual(len(report['records']), report['gtk_cases'])
            for record in report['records']:
                if record['hover']:
                    self.assertEqual(record['hover_rgb'], [236, 184, 96])


class PerlNotificationArgumentTests(unittest.TestCase):
    """Capture arguments without loading managed modules or invoking senders."""

    def source(self, relative):
        return (FORKY / 'hooks/target/usr/local/lib/perl5/site_perl' / relative).read_text()

    def function(self, source, name):
        match = re.search(r'^sub ' + re.escape(name) + r' \{.*?^\}', source, re.M | re.S)
        self.assertIsNotNone(match, name)
        return match[0]

    def perl(self, program, *arguments):
        with tempfile.TemporaryDirectory() as work:
            result = subprocess.run(['/usr/bin/perl', '-e', program, *arguments], cwd=work,
                                    env={'PATH': '/usr/bin:/bin', 'HOME': work, 'LC_ALL': 'C',
                                         'DBUS_SESSION_BUS_ADDRESS': 'fixture-only'},
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def test_action_success_and_failure_keep_content_and_urgency(self):
        cases = (
            ('labwc-security-action/LabwcSecurityAction/Client.pm.tmpl', '_notify',
             'Security Maintenance', 'Security action'),
            ('labwc-network-scan-action/LabwcNetworkScanAction/Client.pm.tmpl', '_notify',
             'Network Scanning', 'Network scan'),
            ('labwc-adb/AndroidADB/Notification.pm.tmpl', 'notify_result',
             'Android Device', 'Android action'),
        )
        for relative, method, app_name, title in cases:
            with self.subTest(sender=relative):
                function = self.function(self.source(relative), method)
                program = '''use strict; use warnings; use JSON::PP qw(encode_json);
our @calls;
sub command { return $_[0]; }
sub config { return $_[0]; }
sub executable { return '/fixture/notify-send'; }
sub tool { return '/fixture/notify-send'; }
sub run { shift; push @calls, [@_]; return 0; }
sub run_quiet { shift; my $deadline = shift; die 'changed delivery deadline' unless $deadline == 10;
                push @calls, [@_]; return 0; }
''' + function + '''
my $self = bless {}, 'main';
my $method = $ARGV[0];
$self->$method(0, 'fixture-action');
$self->$method(17, 'fixture-action');
print encode_json(\\@calls);
'''
                calls = self.perl(program, method)
                self.assertEqual(len(calls), 2)
                for call, status in zip(calls, (0, 17)):
                    self.assertEqual(call[:5], ['/fixture/notify-send', '-a', app_name, '-u',
                                                'normal' if status == 0 else 'critical'])
                    self.assertEqual(call[5], '-i')
                    self.assertTrue(call[6])
                    self.assertEqual(call[7:9], ['-c', 'x-labwc.maintenance'])
                    self.assertEqual(call[9:], [title + (' completed' if status == 0 else ' failed'),
                        'The fixture-action action ' + ('completed successfully.' if status == 0
                                                       else 'failed with status 17.')])

    def test_software_statuses_delegate_expiry_and_preserve_command_deadline(self):
        source = self.source('apt-repo-local/APTRepoLocal/Servicing/Notifier.pm.tmpl')
        declarations = '\n'.join(re.findall(r'^my %(?:APP_LABEL|FAILURE_BODY) = \(.*?^\);',
                                            source, re.M | re.S))
        self.assertEqual(declarations.count('my %'), 2)
        program = '''use strict; use warnings; use JSON::PP qw(encode_json decode_json);
our @calls;
BEGIN { *CORE::GLOBAL::system = sub { push @main::calls, [@_]; return 0; }; }
''' + declarations + '\n' + self.function(source, '_notify') + '\n' + self.function(source, '_deliver') + '''
my $self = bless {}, 'main';
$self->_deliver(@$_) for @{decode_json($ARGV[0])};
print encode_json(\\@calls);
'''
        events = [
            ('checking', 'all', '-', '-'), ('downloading', 'bitwarden', '1', '2'),
            ('downloaded', 'bitwarden', '1', '2'), ('applying', 'bitwarden', '1', '2'),
            ('updated', 'bitwarden', '1', '2'), ('failed', 'bitwarden', 'install', '-'),
            ('download-complete', 'all', '2', '1'), ('apply-complete', 'all', '2', '1'),
            ('no-updates', 'all', '-', '-'),
        ]
        calls = self.perl(program, json.dumps(events))
        self.assertEqual(len(calls), len(events))
        summaries = ['Checking managed software updates', 'Downloading Bitwarden Desktop',
                     'Bitwarden Desktop download ready', 'Applying Bitwarden Desktop',
                     'Bitwarden Desktop updated', 'Bitwarden Desktop update failed',
                     'Managed software download complete', 'Managed software update complete',
                     'Managed software is current']
        for call, event, summary in zip(calls, events, summaries):
            self.assertEqual(call[:8], ['/usr/bin/timeout', '--kill-after=1s', '3s', '/usr/bin/notify-send',
                                       '-a', 'Software Updater', '-u',
                                       'critical' if event[0] == 'failed' else 'normal'])
            self.assertEqual(call[8], '-i')
            self.assertTrue(call[9])
            self.assertEqual(call[10:14], ['-c', 'system.software-update', '--', summary])
            self.assertEqual(len(call), 15)
            self.assertTrue(call[14])


class NotificationExpiryQueueTests(unittest.TestCase):
    """Exercise the production wire format and relay only in private fixtures."""

    def function(self, name):
        source = (FORKY / 'hooks/target/usr/local/bin/labwc-health-notify.tmpl').read_text()
        match = re.search(r'^' + re.escape(name) + r'\(\) \{.*?^\}', source, re.M | re.S)
        self.assertIsNotNone(match, name)
        return match[0]

    def test_queue_writer_serializes_content_without_expiry(self):
        source = (FORKY / 'hooks/target/usr/local/sbin/labwc-notify.tmpl').read_text()
        writer = re.search(r"^printf '%s\|.*? >\"\$EVENT_TMP\"", source, re.M | re.S)[0]
        fields = dict(app_name='Fixture App', urgency='critical', icon='dialog-error',
                      category='device.error', summary='Fixture summary', body='Fixture body')
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / 'event'
            script = 'EVENT_TMP=$1\n' + '\n'.join(key + '=' + shlex.quote(value)
                                                  for key, value in fields.items()) + '\n' + writer
            result = subprocess.run(['/bin/sh', '-eu', '-c', script, 'queue-writer', str(path)],
                                    env={'PATH': '/usr/bin:/bin', 'HOME': work, 'LC_ALL': 'C.UTF-8'},
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_text(), '|'.join(fields.values()) + '\n')

    def relay(self, record, *, failure=False):
        functions = '\n'.join(self.function(name) for name in (
            'validate_queued_notification_text', 'validate_queued_notification_app_name',
            'validate_queued_notification_token', 'check_system_events'))
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            events, seen = root / 'events', root / 'seen'
            events.mkdir(mode=0o700)
            seen.mkdir(mode=0o700)
            name = '0000000001-0000000001-0001.event'
            (events / name).write_text(record + '\n')
            (events / name).chmod(0o600)
            arguments = root / 'arguments'
            script = '\n'.join((
                'SYSTEM_EVENT_DIR=$1', 'SYSTEM_SEEN_DIR=$2', 'SYSTEM_EVENT_OWNER_UID=$3',
                'NOTIFY_ARGS=$4', 'notification_failures=0', 'prune_seen() { :; }',
                'atomic_state() { : > "$1"; }',
                'notify() { printf "%s\\n" "$@" > "$NOTIFY_ARGS"; return ' + str(int(failure)) + '; }',
                functions, 'check_system_events', 'exit "$notification_failures"'))
            result = subprocess.run(['/bin/sh', '-eu', '-c', script, 'queue-relay',
                                     str(events), str(seen), str(os.getuid()), str(arguments)],
                                    env={'PATH': '/usr/bin:/bin', 'HOME': work, 'LC_ALL': 'C.UTF-8'},
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, int(failure), result.stderr)
            return (arguments.read_text().splitlines() if arguments.exists() else [],
                    (seen / (name + '.seen')).exists())

    def test_current_and_legacy_records_deliver_without_expiry(self):
        prefix = 'Fixture App|critical|dialog-error|device.error|'
        for expiry in ('', '0|', '12000|', '600000|'):
            with self.subTest(legacy_expiry=expiry):
                arguments, acknowledged = self.relay(prefix + expiry + 'Fixture summary|Fixture body')
                self.assertEqual(arguments, ['-a', 'Fixture App', '-u', 'critical', '-i', 'dialog-error',
                                             '-c', 'device.error', '--', 'Fixture summary', 'Fixture body'])
                self.assertTrue(acknowledged)

    def test_invalid_legacy_fields_or_extra_delimiters_are_not_delivered(self):
        prefix = 'Fixture App|critical|dialog-error|device.error|'
        for tail in ('bad|Summary|Body', '600001|Summary|Body', '0000000|Summary|Body',
                     '0|Summary|Body|extra', '|Body'):
            with self.subTest(tail=tail):
                self.assertEqual(self.relay(prefix + tail), ([], False))

    def test_failed_relay_retains_pending_record_without_acknowledging(self):
        arguments, acknowledged = self.relay(
            'Fixture App|critical|dialog-error|device.error|Summary|Body', failure=True)
        self.assertTrue(arguments)
        self.assertFalse(acknowledged)

    def test_health_deduplication_keeps_summary_and_body_after_removing_expiry(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            arguments = root / 'arguments'
            script = '\n'.join((
                'STATE_DIR=$1', 'NOTIFY_ARGS=$2', 'APP_NAME="Desktop Health"',
                'read_state() { [ ! -f "$1" ] || /usr/bin/cat -- "$1"; }',
                'atomic_state() { /usr/bin/cat > "$1"; }',
                'notify() { printf "%s\\n" "$@" >> "$NOTIFY_ARGS"; }',
                self.function('send_notification'),
                'send_notification fixture critical dialog-error device.error "Fixture summary" "Fixture body"',
                'send_notification fixture critical dialog-error device.error "Fixture summary" "Fixture body"'))
            result = subprocess.run(['/bin/sh', '-eu', '-c', script, 'health-dedup', work, str(arguments)],
                                    env={'PATH': '/usr/bin:/bin', 'HOME': work, 'LC_ALL': 'C.UTF-8'},
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(arguments.read_text().splitlines(), [
                '-a', 'Desktop Health', '-u', 'critical', '-i', 'dialog-error', '-c', 'device.error',
                '--', 'Fixture summary', 'Fixture body'])
            self.assertEqual((root / 'fixture.state').read_text().splitlines(), [
                'critical', 'dialog-error', 'device.error', 'Fixture summary', 'Fixture body'])


if __name__ == '__main__':
    unittest.main()
