#!/usr/bin/env python3
"""r3 launch/policy regressions. No compiler, target service or GUI is used."""
from __future__ import annotations

import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
PACKAGE = TARGET / 'usr/local/lib/python3.14/dist-packages'
sys.path.insert(0, str(PACKAGE))
from labwc_managed_app import electron, generic, profiles, session


def script_module(relative):
    path = TARGET / relative
    module = types.ModuleType('fixture_' + path.name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def profile(name):
    text = (TARGET / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
    start = text.index('profile ' + name + ' ')
    end = text.find('\nprofile ', start + 1)
    return text[start:end if end >= 0 else len(text)]


class MullvadNamespaceTests(unittest.TestCase):
    def command(self, kind, path, *args):
        with mock.patch.object(generic, 'assert_launch_allowed'), \
             mock.patch.object(generic, 'restart_token', return_value='fixture'), \
             mock.patch.object(generic, 'menu_action_wait_arguments', return_value=[]):
            return generic.transient_argv(kind, 'auto', [path, *args], {})

    def test_only_canonical_bootstrap_and_vendor_gui_keep_root_uid_view(self):
        for kind, path in (('wayland', '/usr/local/bin/mullvad-vpn'),
                           ('electron', '/opt/Mullvad VPN/mullvad-vpn')):
            with self.subTest(kind=kind):
                cmd = self.command(kind, path)
                for prop in ('PrivateTmp=', 'PrivateIPC=', 'ProtectSystem='):
                    self.assertFalse(any(v.startswith('--property=' + prop) for v in cmd))
                for prop in ('PrivateUsers=no', 'PrivatePIDs=no', 'NoNewPrivileges=no', 'Requisite=labwc-session.target',
                             'PartOf=labwc-session.target', 'KillMode=control-group',
                             'ExitType=cgroup', 'TimeoutStopSec=20s', 'SendSIGKILL=yes'):
                    self.assertIn('--property=' + prop, cmd)
                self.assertNotIn('--uid=0', cmd)
                self.assertEqual(cmd[-1], path)

    def test_same_basename_untrusted_paths_and_wrong_wrapper_keep_namespaces(self):
        for kind, path in (('wayland', '/tmp/mullvad-vpn'),
                           ('wayland', '/opt/Mullvad VPN/mullvad-vpn'),
                           ('electron', '/usr/local/bin/mullvad-vpn'),
                           ('electron', '/tmp/Mullvad VPN/mullvad-vpn'),
                           ('electron', '/opt/Mullvad VPN/mullvad-vpn-evil'),
                           ('electron', '/opt/Other/other')):
            with self.subTest(kind=kind, path=path):
                cmd = self.command(kind, path)
                for prop in ('PrivateTmp=yes', 'PrivateIPC=yes', 'ProtectSystem=full'):
                    self.assertIn('--property=' + prop, cmd)

    def test_mullvad_electron_keeps_native_wayland_and_rejects_sandbox_bypass(self):
        cmd = generic.electron_command(['/opt/Mullvad VPN/mullvad-vpn'])
        self.assertIn('--ozone-platform=wayland', cmd)
        self.assertNotIn('--no-sandbox', cmd)
        with self.assertRaises(SystemExit):
            generic.electron_command(['/opt/Mullvad VPN/mullvad-vpn', '--no-sandbox'])


class MullvadHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = (TARGET / 'usr/local/bin/mullvad-vpn').read_text()
        self.cgroup = self.root / 'cgroup'
        self.uid_map = self.root / 'uid_map'
        self.cgroup.write_text('0::/user.slice/user-1000.slice/user@1000.service/session.slice/labwc-compositor.service\n')
        self.uid_map.write_text('         0          0 4294967295\n')
        self.trace = self.root / 'trace'
        self.active = self.root / 'active'
        self.unit = 'labwc-wayland-mullvad-vpn-' + 'a' * 32 + '.service'

    def function(self, name):
        text = self.source.split(name + '() {', 1)[1].split('\n}\n', 1)[0]
        return name + '() {' + text + '\n}\n'

    def predicate(self, name):
        text = ('set -eu\nfatal() { echo "$*" >&2; exit 65; }\n' + self.function(name) + name)
        text = text.replace('/proc/self/cgroup', str(self.cgroup)).replace('/proc/self/uid_map', str(self.uid_map))
        return subprocess.run(['/bin/sh', '-c', text], capture_output=True, text=True, timeout=5)

    def test_membership_requires_unified_cgroup_exact_prefix_and_32_hex_token(self):
        self.cgroup.write_text('0::/user.slice/' + self.unit + '\n')
        self.assertEqual(self.predicate('in_managed_host_unit').returncode, 0)
        for value in ('0::/labwc-compositor.service',
                      '0::/' + self.unit + '/child',
                      '0::/labwc-wayland-mullvad-vpn-a.service',
                      '0::/labwc-wayland-mullvad-vpn-' + 'g' * 32 + '.service',
                      '0::/labwc-wayland-mullvad-vpn-' + 'a' * 33 + '.service',
                      '1:name=systemd:/' + self.unit,
                      '0::/evil-' + self.unit, ''):
            with self.subTest(cgroup=value):
                self.cgroup.write_text(value + '\n')
                self.assertNotEqual(self.predicate('in_managed_host_unit').returncode, 0)

    def test_root_uid_must_map_to_real_host_root(self):
        for content, status in (('0 0 4294967295\n', 0), ('1000 1000 1\n', 1),
                                ('0 1000 1\n', 1), ('0 0 0\n', 1), ('', 1)):
            with self.subTest(mapping=content):
                self.uid_map.write_text(content)
                self.assertEqual(self.predicate('has_host_root_mapping').returncode, status)

    def test_missing_cgroup_fails_closed(self):
        self.cgroup.unlink()
        result = self.predicate('in_managed_host_unit')
        self.assertEqual(result.returncode, 65)
        self.assertIn('cannot verify', result.stderr)

    def fixture(self, *, managed=False, active=False, auth_status=0, bad_root=False, args=()):
        if managed:
            self.cgroup.write_text('0::/user.slice/' + self.unit + '\n')
        if active:
            self.active.touch()
        if bad_root:
            self.uid_map.write_text('1000 1000 1\n')
        replacements = {}
        commands = {
            '/usr/local/bin/labwc-wayland-app': 'printf "handoff:%s\\n" "$*" >>"$TRACE"\n',
            '/usr/local/bin/labwc-electron-app': 'printf "electron:%s:display=%s\\n" "$*" "${DISPLAY-unset}" >>"$TRACE"\n',
            '/usr/bin/systemctl': '[ -f "$ACTIVE" ]\n',
            '/usr/bin/pkexec': 'printf "pkexec:%s\\n" "$*" >>"$TRACE"\n[ "$AUTH_STATUS" -eq 0 ] || exit "$AUTH_STATUS"\ntouch "$ACTIVE"\n',
            '/usr/local/libexec/mullvad-daemon-start': 'exit 0\n',
            '/opt/Mullvad VPN/mullvad-vpn': 'exit 0\n',
        }
        for index, (original, body) in enumerate(commands.items()):
            target = self.root / ('tool-' + str(index))
            target.write_text('#!/bin/sh\nset -eu\n' + body)
            target.chmod(0o700)
            replacements[original] = str(target)
        text = self.source
        # Only bypass session validation for routing fixtures, not in production.
        # The production ordering and retained validation are asserted separately.
        text = text.replace('\nvalidate_wayland_session\n', '\n:\n')
        text = text.replace('/proc/self/cgroup', str(self.cgroup)).replace('/proc/self/uid_map', str(self.uid_map))
        for original, target in replacements.items():
            text = text.replace(original, target)
        wrapper = self.root / 'wrapper'
        wrapper.write_text(text)
        result = subprocess.run(['/bin/sh', str(wrapper), *args], env=dict(os.environ,
                                TRACE=str(self.trace), ACTIVE=str(self.active), AUTH_STATUS=str(auth_status),
                                DISPLAY=':123', LABWC_SESSION_APP='1', LABWC_MULLVAD_HOST='1'),
                                capture_output=True, text=True, timeout=5)
        return result, self.trace.read_text() if self.trace.exists() else ''

    def test_fuzzel_context_hands_off_before_pkexec_even_with_spoofed_environment(self):
        result, trace = self.fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(trace.startswith('handoff:auto -- '))
        self.assertNotIn('pkexec:', trace)
        self.assertNotIn('electron:', trace)

    def test_host_unit_authenticates_then_launches_native_gui(self):
        result, trace = self.fixture(managed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(trace.startswith('pkexec:'))
        self.assertIn('\nelectron:auto -- ', trace)
        self.assertIn('display=unset', trace)
        self.assertNotIn('handoff:', trace)

    def test_already_running_daemon_needs_no_authentication(self):
        result, trace = self.fixture(managed=True, active=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(trace.startswith('electron:'))
        self.assertNotIn('pkexec:', trace)

    def test_cancelled_authorization_does_not_launch_gui(self):
        result, trace = self.fixture(managed=True, auth_status=126)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('status 126', result.stderr)
        self.assertNotIn('electron:', trace)

    def test_wrong_root_mapping_fails_instead_of_recursive_handoff_or_auth(self):
        result, trace = self.fixture(managed=True, bad_root=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('host root UID mapping', result.stderr)
        self.assertEqual(trace, '')

    def test_invalid_arguments_rejected_before_handoff(self):
        result, trace = self.fixture(args=('--arbitrary',))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(trace, '')

    def test_argument_and_session_checks_still_precede_handoff(self):
        self.assertLess(self.source.index('[ "$#" -eq 0 ]'), self.source.index('\nvalidate_wayland_session\n'))
        self.assertLess(self.source.index('\nvalidate_wayland_session\n'), self.source.index('if ! in_managed_host_unit;'))
        self.assertLess(self.source.index('if ! in_managed_host_unit;'), self.source.index('daemon_unit='))
        self.assertIn('[ "$runtime_mode" = 700 ]', self.source)
        self.assertIn('[ "$wayland_links" = 1 ]', self.source)
        self.assertIn('[ "$current_uid" -gt 0 ]', self.source)


class ChromiumFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'apparmor.d'
        self.directory.mkdir()
        text = (FORKY / 'scripts/late/security.sh').read_text()
        self.production = text
        self.function = 'apparmor_require_disconnected_profile_flags() {' + text.split(
            'apparmor_require_disconnected_profile_flags() {', 1)[1].split('\napparmor_obsolete_profile_files()', 1)[0]
        self.function = self.function.replace('/target/etc/apparmor.d/', str(self.directory) + '/')
        self.path = self.directory / 'chromium'

    def normalize(self, path=None):
        return subprocess.run(['/bin/sh', '-c', 'set -eu\ninstaller_fatal() { echo "$*" >&2; exit 65; }\n' +
                              self.function + '\napparmor_require_disconnected_profile_flags "$1" chromium strip-unconfined',
                              'fixture', str(path or self.path)], text=True, capture_output=True, timeout=5)

    def test_actual_installer_call_targets_package_chromium_not_an_unused_local_header(self):
        self.assertRegex(self.production, r'apparmor_require_disconnected_profile_flags\s*\\\n\s*"/target/etc/apparmor.d/chromium"\s*\\\n\s*chromium\s*\\\n\s*strip-unconfined')

    def test_adds_flags_and_preserves_attachment_and_local_include(self):
        for flags in ('', ' flags=(unconfined)', ' flags=(complain)',
                      ' flags=(attach_disconnected, mediate_deleted)'):
            with self.subTest(flags=flags):
                self.path.write_text('profile chromium /usr/lib/chromium/chromium' + flags + ' {\n  include if exists <local/chromium>\n}\n')
                result = self.normalize()
                self.assertEqual(result.returncode, 0, result.stderr)
                first = self.path.read_bytes()
                self.assertIn(b'flags=(', first)
                self.assertEqual(first.count(b'attach_disconnected'), 1)
                self.assertEqual(first.count(b'mediate_deleted'), 1)
                self.assertNotIn(b'unconfined', first)
                self.assertIn(b'profile chromium /usr/lib/chromium/chromium', first)
                self.assertIn(b'include if exists <local/chromium>', first)
                self.assertEqual(self.normalize().returncode, 0)
                self.assertEqual(self.path.read_bytes(), first)
                self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)

    def test_default_allow_unknown_header_and_duplicate_label_fail_without_publish(self):
        for source in ('profile chromium flags=(default_allow) {\n}\n',
                       'profile different {\n}\n',
                       'profile chromium {\n}\nprofile chromium {\n}\n'):
            with self.subTest(source=source):
                self.path.write_text(source)
                self.assertNotEqual(self.normalize().returncode, 0)
                self.assertEqual(self.path.read_text(), source)
                self.assertEqual(list(self.directory.glob('*.flags.*')), [])

    def test_symlink_source_rejected(self):
        target = self.root / 'untrusted'
        target.write_text('profile chromium {\n}\n')
        self.path.symlink_to(target)
        self.assertNotEqual(self.normalize().returncode, 0)
        self.assertEqual(target.read_text(), 'profile chromium {\n}\n')

    def test_nested_path_and_oversized_source_rejected(self):
        nested = self.directory / 'nested'
        nested.mkdir()
        child = nested / 'chromium'
        child.write_text('profile chromium {\n}\n')
        self.assertNotEqual(self.normalize(child).returncode, 0)
        self.path.write_text('#' * 1048577)
        self.assertNotEqual(self.normalize().returncode, 0)


class AppArmorCoverageTests(unittest.TestCase):
    def test_both_git_entrypoints_use_named_confined_transition(self):
        for name in ('managed-codex-wrapper', 'managed-labwc-chatgpt'):
            self.assertIn('/usr/local/bin/git-ssh rpx -> managed-git-ssh,', profile(name))
        helper = profile('managed-git-ssh')
        self.assertIn('peer=(name=org.freedesktop.systemd1)', helper)
        self.assertIn('openssh_agent} rw,', helper)
        self.assertIn('/usr/local/libexec/managed-ssh-checks r,', helper)
        self.assertNotRegex(helper, r'network\s+inet')
        self.assertNotRegex(helper, r'capability\s')
        self.assertNotIn('PUx', helper)
        self.assertNotIn('unconfined)', helper)
        self.assertNotIn('*.gpg rw', helper)

    def test_git_helper_shutdown_permissions_cover_both_sides_without_global_attachment(self):
        helper = profile('managed-git-ssh')
        self.assertTrue(helper.startswith('profile managed-git-ssh flags='))
        for name in ('managed-codex-wrapper', 'managed-labwc-chatgpt'):
            self.assertIn('signal (send) set=(hup int quit kill term) peer=managed-git-ssh,',
                          profile(name))
            self.assertIn('signal (receive) set=(hup int quit kill term) peer=' + name + ',',
                          helper)

    def test_mullvad_pts_and_handoff_permissions_are_limited(self):
        wrapper = profile('managed-mullvad-vpn')
        root = profile('managed-mullvad-daemon-start')
        self.assertIn('owner /dev/pts/[0-9]* rw,', wrapper)
        self.assertIn('/dev/pts/[0-9]* rw,', root)
        self.assertIn('uid_map r,', wrapper)
        self.assertIn('/usr/local/bin/labwc-wayland-app rPx -> managed-labwc-generic-app,', wrapper)
        self.assertNotIn('/dev/** rw', wrapper + root)

    def test_terminal_metadata_rules_do_not_grant_dpkg_or_system_subtree_writes(self):
        text = (TARGET / 'etc/apparmor.d/managed-desktop-utilities').read_text()
        text = text.split('profile managed-desktop-launcher ', 1)[1].split('\nprofile ', 1)[0]
        self.assertIn('/usr/lib/git-core/git rix,', text)
        self.assertIn('/var/lib/apt/lists/** r,', text)
        self.assertIn('owner /data/codex/usr/.git/** rwkl,', text)
        self.assertIn('/data/codex/usr/** r,', text)
        self.assertNotIn('/data/codex/usr/** rw', text)
        self.assertNotRegex(text, r'/var/lib/(apt|dpkg)/[^\n]*\s+[a-z]*w')
        self.assertNotIn('/.system/', text)

    def test_crashpad_memory_is_owner_read_only_and_shm_already_permitted(self):
        local = (TARGET / 'etc/apparmor.d/local/chromium').read_text()
        self.assertIn('owner @{PROC}/[0-9]*/mem r,', local)
        runtime = (TARGET / 'etc/apparmor.d/abstractions/managed-electron-runtime').read_text()
        self.assertIn('owner /dev/shm/** rwkl,', runtime)

    def test_bitwarden_retains_libsecret_and_ready_dbus_keyring(self):
        self.assertEqual(electron.electron_password_store_arg('bitwarden'),
                         '--password-store=gnome-libsecret')
        keyring = (TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-kwallet-portal.service').read_text()
        self.assertIn('Type=dbus', keyring)
        self.assertIn('BusName=org.freedesktop.secrets', keyring)
        self.assertIn('ExecStartPost=', keyring)
        self.assertNotIn('--password-store=basic', keyring)

    def test_bitwarden_token_warning_is_not_filtered_or_converted_to_success(self):
        panel = (TARGET / 'usr/local/libexec/labwc-panel-run').read_text()
        self.assertNotIn('Refresh token', panel)
        source = (PACKAGE / 'labwc_managed_app/session.py').read_text()
        fragment = source.split('def bitwarden_session_unit_argv', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('labwc-kwallet-portal.service', fragment)
        self.assertNotIn('SuccessExitStatus=', fragment)
        self.assertNotIn('PrivateUsers', fragment)
        self.assertEqual(set(profiles.WAYLAND_COMPAT_APPS), {'zoom', 'discord'})


class WaybarDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.panel = script_module('usr/local/libexec/labwc-panel-run')

    def line(self, assertion, timestamp='16:04:24.656', pid=7420):
        return f'(waybar:{pid}): Gtk-CRITICAL **: {timestamp}: '.encode() + assertion + b'\n'

    def test_only_two_known_assertions_coalesce_across_timestamps(self):
        out = io.BytesIO()
        counter = self.panel.Coalescer(self.panel.MESSAGES['waybar'])
        for message in sorted(self.panel.WAYBAR_GTK_ASSERTIONS):
            first = self.line(message)
            counter.line(out, first)
            counter.line(out, self.line(message, '16:04:25.001'))
            counter.line(out, self.line(message, '16:04:26.500', 9000))
            self.assertIn(first, out.getvalue())
        counter.flush(final=True)
        self.assertEqual(out.getvalue().count(b'repeated 2 times:'), 2)
        self.assertEqual(out.getvalue().count(b'Gtk-CRITICAL'), 2)

    def test_unknown_assertions_and_different_process_names_are_lossless(self):
        out = io.BytesIO()
        counter = self.panel.Coalescer(self.panel.MESSAGES['waybar'])
        known = sorted(self.panel.WAYBAR_GTK_ASSERTIONS)[0]
        lines = [self.line(b'unknown-assertion failed'),
                 self.line(known).replace(b'(waybar:', b'(other:'),
                 self.line(known) + b'continuation\n',
                 b'normal message\n', b'Refresh token not found in secure storage.\n']
        # The continuation-containing record is not a single diagnostic line.
        data = b''.join(lines * 2)
        for line in lines * 2:
            counter.line(out, line)
        counter.flush(final=True)
        self.assertEqual(out.getvalue(), data)

    def test_other_panel_does_not_filter_waybar_diagnostic(self):
        out = io.BytesIO()
        counter = self.panel.Coalescer(self.panel.MESSAGES['crystal-dock'])
        line = self.line(sorted(self.panel.WAYBAR_GTK_ASSERTIONS)[0])
        counter.line(out, line)
        counter.line(out, line)
        counter.flush(final=True)
        self.assertEqual(out.getvalue(), line * 2)

    def test_stderr_stdout_are_counted_independently_and_periodic_summary_is_bounded(self):
        first, second = io.BytesIO(), io.BytesIO()
        counter = self.panel.Coalescer(self.panel.MESSAGES['waybar'], interval=0)
        line = self.line(sorted(self.panel.WAYBAR_GTK_ASSERTIONS)[0])
        for output in (first, second):
            counter.line(output, line)
            counter.line(output, line)
        counter.flush()
        for output in (first, second):
            self.assertIn(line, output.getvalue())
            self.assertIn(b'repeated 1 times:', output.getvalue())
        self.assertEqual(counter.repeats, {})
        self.assertEqual(len(counter.seen), 2)


if __name__ == '__main__':
    unittest.main()
