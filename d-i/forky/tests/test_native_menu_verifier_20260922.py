"""Execute the installer's actual native-menu verifier on rendered fixtures.

Only target boundaries (filesystem root/UIDs, account lookup, GTK import and
installed package/CLI probes) are simulated. The shell handoff, renderer, XML,
TOML validator and every Python assertion run unchanged. Real GTK widget tests
remain in test_native_menu_hover_20260920; this is not a boot qualification.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from test_native_tomat_20260920 import FORKY, LIBEXEC, SKEL

HOME = '/home/native-menu-fixture'
USERNAME = 'native-menu-fixture'
MENUS = ('tomat', 'audio', 'notifications', 'power', 'calendar')
HELPERS = ('labwc-tomat', 'labwc-tomat-hook', 'labwc-notifications', 'labwc-calendar')


def rendered_verifier(profile: Path, count: int | None = None):
    """Capture real template substitutions and the exact run_in_target argv."""
    script = r'''
. "$1"
. "$2/detect.sh"
. "$2/components.sh"
. "$2/verify.sh"
if [ "$3" != profile ]; then LABWC_WORKSPACE_COUNT=$3; fi
ACCOUNT_HOME=/home/native-menu-fixture
ACCOUNT_USERNAME=native-menu-fixture
desktop_render_role_target_template_deferred() { shift 3; printf '%s\0' "$@"; }
desktop_assert_role_target_template_resolved() { :; }
desktop_log() { :; }
installer_warn() { :; }
desktop_render_waybar_config
printf '\0'
desktop_verify_native_drawer_icons() { :; }
run_in_target() { shift; printf '%s\0' "$@"; }
desktop_verify_native_menus
'''
    response = subprocess.run(
        ['/bin/sh', '-eu', '-c', script, 'native-menu-verifier', str(profile),
         str(FORKY / 'scripts/desktop'), 'profile' if count is None else str(count)],
        env={'PATH': '/usr/bin:/bin'}, capture_output=True, check=True, timeout=10)
    substitutions, command = response.stdout.decode().split('\0\0', 1)
    fields = substitutions.split('\0')
    if len(fields) % 2:
        raise AssertionError('incomplete renderer substitution pair')
    text = (SKEL / 'waybar/config.tmpl').read_text()
    for key, value in zip(fields[::2], fields[1::2]):
        text = text.replace('__INSTALLER_' + key + '__', value)
    if '__INSTALLER_' in text:
        raise AssertionError('unresolved Waybar template')
    argv = command.split('\0')[:-1]
    if argv[:4] != ['/usr/bin/python3', '-I', '-B', '-c']:
        raise AssertionError('unexpected target verifier interpreter')
    return json.loads(text), argv


class TargetFixture:
    """All writable files and service-mask symlinks stay in a temporary root."""
    def __init__(self, root: Path, bars, command, whisper: bool = False):
        self.root = root
        self.command = command
        self.owners = {}
        self.arch = 'amd64'
        self.mako_version = '1.11.0-1'
        self.probes = []
        self.controller = runpy.run_path(str(LIBEXEC / 'labwc-tomat'))
        for name in HELPERS:
            destination = self.path('/usr/local/libexec/' + name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(LIBEXEC / name, destination)
            destination.chmod(0o755)
            self.owners[destination] = 0
        for base, uid in (('/etc/skel-desktop', 0), (HOME, 1000)):
            config = self.path(base) / '.config'
            (config / 'waybar').mkdir(parents=True)
            (config / 'tomat').mkdir()
            for name in MENUS:
                destination = config / 'waybar' / (name + '-menu.xml')
                shutil.copyfile(SKEL / 'waybar' / destination.name, destination)
                destination.chmod(0o644)
                self.owners[destination] = uid
            toml = config / 'tomat/config.toml'
            shutil.copyfile(SKEL / 'tomat/config.toml', toml)
            toml.chmod(0o600)
            self.owners[toml] = uid
            (config / 'waybar/config').write_text(json.dumps(bars))
            if whisper:
                unit = config / 'systemd/user/whisper-transcribe.service'
                unit.parent.mkdir(parents=True)
                unit.write_text('[Service]\nExecStart=/usr/bin/true\n')
            # Execute the real install-time optional-menu transformation for
            # BOTH copies, rather than manufacturing the XML state in the test.
            source = (FORKY / 'scripts/desktop/components.sh').read_text()
            code = source.split('run_in_target "configure optional native audio menu" '
                                '/usr/bin/python3 -I -c \'\n', 1)[1].split(
                                    '\n\' "$native_menu_whisper"', 1)[0]
            with mock.patch('pathlib.Path', return_value=config / 'waybar/audio-menu.xml'), \
                    mock.patch.object(sys, 'argv', ['-c', str(int(whisper))]):
                exec(compile(code, 'actual-native-audio-staging', 'exec'), {})
        for relative in ('/etc/systemd/system/tomat.service', '/etc/systemd/user/tomat.service'):
            destination = self.path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to('/dev/null')
        binary = self.path('/usr/bin/tomat')
        binary.parent.mkdir(parents=True)
        binary.write_text('Fixture only; never executed.\n')
        binary.chmod(0o755)

    def path(self, value):
        value = Path(value)
        if not value.is_absolute() or '..' in value.parts:
            raise AssertionError('unexpected target path: ' + str(value))
        return self.root / value.relative_to('/')

    def rewrite_bar(self, base: str, layout: int, change):
        path = self.path(base) / '.config/waybar/config'
        bars = json.loads(path.read_text())
        change(bars[layout])
        path.write_text(json.dumps(bars))

    def verify(self):
        real_lstat = Path.lstat
        real_run = subprocess.run
        account = types.SimpleNamespace(pw_uid=1000, pw_dir=HOME)
        gi = types.ModuleType('gi')
        gi.require_version = mock.Mock()
        repository = types.ModuleType('gi.repository')
        repository.Gtk = types.SimpleNamespace(get_major_version=lambda: 3)

        def metadata(path, *args, **kwargs):
            result = real_lstat(path, *args, **kwargs)
            if path in self.owners:
                values = list(result)
                values[4] = self.owners[path]
                result = os.stat_result(values)
            return result

        def output(argv, **kwargs):
            self.probes.append(argv)
            if argv == ['/usr/bin/dpkg-query', '-W', '-f=${Version}', 'mako-notifier']:
                return self.mako_version + '\n'
            if argv == ['/usr/bin/dpkg', '--print-architecture']:
                return self.arch + '\n'
            raise AssertionError('unexpected package probe: ' + repr(argv))

        def run(argv, **kwargs):
            self.probes.append(argv)
            if argv[:2] == ['/usr/bin/dpkg', '--compare-versions']:
                return real_run(argv, **kwargs)
            if argv in (['/usr/bin/tomat', 'daemon', 'run', '--help'],
                        ['/usr/bin/tomat', 'watch', '--help']):
                return subprocess.CompletedProcess(argv, 0)
            raise AssertionError('unexpected command (no daemons permitted): ' + repr(argv))

        def controller(path):
            if path != '/usr/local/libexec/labwc-tomat':
                raise AssertionError('unexpected helper import: ' + path)
            return self.controller

        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch('pathlib.Path', side_effect=self.path))
            stack.enter_context(mock.patch.object(Path, 'lstat', metadata))
            stack.enter_context(mock.patch('pwd.getpwnam', return_value=account))
            stack.enter_context(mock.patch('runpy.run_path', side_effect=controller))
            stack.enter_context(mock.patch('subprocess.check_output', side_effect=output))
            stack.enter_context(mock.patch('subprocess.run', side_effect=run))
            stack.enter_context(mock.patch.dict(sys.modules, {'gi': gi, 'gi.repository': repository}))
            stack.enter_context(mock.patch.object(sys, 'argv', ['-c', *self.command[5:]]))
            stack.enter_context(contextlib.redirect_stdout(out))
            exec(compile(self.command[4], 'actual-native-menu-verifier', 'exec'), {})
        gi.require_version.assert_called_once_with('Gtk', '3.0')
        return out.getvalue()


class NativeMenuVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = sorted(path for path in (FORKY / 'hosts/profiles').glob('*.env')
                              if 'LABWC_WAYBAR_FONT_SIZE=' in path.read_text())
        cls.rendered = {path.name: rendered_verifier(path) for path in cls.profiles}

    def fixture(self, root, *, bars=None, command=None, whisper=False):
        original_bars, original_command = next(iter(self.rendered.values()))
        return TargetFixture(root, copy.deepcopy(original_bars if bars is None else bars),
                             original_command if command is None else command, whisper)

    def test_actual_verifier_accepts_all_rendered_profiles_and_optional_audio_states(self):
        self.assertEqual(len(self.profiles), 10)
        for name, (bars, command) in self.rendered.items():
            for whisper in (False, True):
                with self.subTest(profile=name, whisper=whisper), tempfile.TemporaryDirectory() as work:
                    target = self.fixture(Path(work), bars=bars, command=command, whisper=whisper)
                    self.assertIn('menus=5 tomat=isolated power=native calendar=native', target.verify())
                    self.assertIn(['/usr/bin/tomat', 'daemon', 'run', '--help'], target.probes)
                    self.assertIn(['/usr/bin/tomat', 'watch', '--help'], target.probes)

    def test_shell_handoff_and_all_twelve_workspace_counts(self):
        for count in range(1, 13):
            with self.subTest(workspaces=count), tempfile.TemporaryDirectory() as work:
                bars, command = rendered_verifier(self.profiles[0], count)
                self.assertEqual(command[5:7], [HOME, USERNAME])
                self.assertEqual(len(command), 8)
                expected = ['custom/launcher', 'ext/workspaces', 'custom/tomat', 'custom/wayscriber',
                            'custom/window-switcher', 'group/apps']
                if count == 1:
                    expected.append('wlr/taskbar')
                self.assertEqual(json.loads(command[7]), expected)
                for bar in bars:
                    self.assertEqual(bar['modules-left'], expected)
                self.assertIn('menus=5', self.fixture(Path(work), bars=bars, command=command).verify())

    def test_generator_failure_stops_before_target_verification(self):
        script = r'''
. "$1"
desktop_verify_native_drawer_icons() { :; }
desktop_waybar_modules_left_json() { return 17; }
desktop_fatal() { printf '%s\n' "$*" >&2; exit 41; }
run_in_target() { printf 'UNEXPECTED target call\n'; }
desktop_verify_native_menus
'''
        for shell in (['/bin/sh'], ['busybox', 'sh']):
            with self.subTest(shell=shell):
                result = subprocess.run(
                    [*shell, '-eu', '-c', script, 'native-menu-fail-closed',
                     str(FORKY / 'scripts/desktop/verify.sh')],
                    text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 41, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertIn('failed to resolve native Waybar menu button order', result.stderr)

    def test_missing_duplicate_reordered_and_legacy_modules_fail_in_both_copies_and_layouts(self):
        changes = {
            'missing-tomat': lambda left: left.remove('custom/tomat'),
            'duplicate-tomat': lambda left: left.append('custom/tomat'),
            'missing-switcher': lambda left: left.remove('custom/window-switcher'),
            'legacy-order': lambda left: left.__setitem__(slice(None), [
                'custom/launcher', 'ext/workspaces', 'custom/wayscriber', 'custom/tomat', 'group/apps']),
            'reordered': lambda left: left.reverse(),
            'unexpected-taskbar': lambda left: left.append('wlr/taskbar'),
        }
        for base in ('/etc/skel-desktop', HOME):
            for layout in (0, 1):
                for name, change in changes.items():
                    with self.subTest(base=base, layout=layout, change=name), tempfile.TemporaryDirectory() as work:
                        target = self.fixture(Path(work))
                        target.rewrite_bar(base, layout, lambda bar: change(bar['modules-left']))
                        with self.assertRaisesRegex(SystemExit, 'wrong native menu button order') as error:
                            target.verify()
                        self.assertIn(base + '/.config/waybar/config', str(error.exception))
                        self.assertIn('internal' if layout == 0 else 'external', str(error.exception))

    def test_menu_event_ids_and_lifecycle_checks_still_fail_closed(self):
        changes = (
            ('native menu event conflict', lambda entry: entry.update({'on-click-right': '/usr/bin/true'})),
            ('menu/action IDs differ', lambda entry: entry['menu-actions'].pop('tomat_stop')),
            ('blocking/unscoped/unresolved', lambda entry: entry['menu-actions'].update({
                'tomat_stop': entry['menu-actions']['tomat_stop'].replace('--no-block ', '')})),
            ('blocking/unscoped/unresolved', lambda entry: entry['menu-actions'].update({
                'tomat_stop': entry['menu-actions']['tomat_stop'].replace(
                    '--property=PartOf=labwc-session.target ', '')})),
        )
        for message, change in changes:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as work:
                target = self.fixture(Path(work))
                target.rewrite_bar(HOME, 1, lambda bar: change(bar['custom/tomat']))
                with self.assertRaisesRegex(SystemExit, message):
                    target.verify()

    def test_file_permissions_types_and_owners_still_fail_closed(self):
        cases = (
            ('/usr/local/libexec/labwc-tomat', 0o777, None, 'unsafe or missing native menu helper'),
            ('/usr/local/libexec/labwc-tomat-hook', None, 1000, 'unsafe or missing native menu helper'),
            (HOME + '/.config/tomat/config.toml', 0o644, None, 'unsafe Tomat configuration'),
            (HOME + '/.config/tomat/config.toml', None, 0, 'unsafe Tomat configuration'),
            (HOME + '/.config/waybar/tomat-menu.xml', 0o666, None, 'unsafe menu file'),
            (HOME + '/.config/waybar/audio-menu.xml', None, 0, 'unsafe menu file'),
        )
        for name, mode, uid, message in cases:
            with self.subTest(path=name, mode=mode, uid=uid), tempfile.TemporaryDirectory() as work:
                target = self.fixture(Path(work))
                path = target.path(name)
                if mode is not None:
                    path.chmod(mode)
                if uid is not None:
                    target.owners[path] = uid
                with self.assertRaisesRegex(SystemExit, message):
                    target.verify()
        with tempfile.TemporaryDirectory() as work:
            target = self.fixture(Path(work))
            path = target.path(HOME + '/.config/waybar/tomat-menu.xml')
            path.unlink()
            path.symlink_to('audio-menu.xml')
            with self.assertRaisesRegex(SystemExit, 'unsafe menu file'):
                target.verify()

    def test_stock_service_masks_and_mako_floor_still_required(self):
        for relative in ('/etc/systemd/system/tomat.service', '/etc/systemd/user/tomat.service'):
            with self.subTest(mask=relative), tempfile.TemporaryDirectory() as work:
                target = self.fixture(Path(work))
                target.path(relative).unlink()
                with self.assertRaisesRegex(SystemExit, 'stock Tomat service is not masked'):
                    target.verify()
        with tempfile.TemporaryDirectory() as work:
            target = self.fixture(Path(work))
            target.mako_version = '1.10.0-1'
            with self.assertRaisesRegex(SystemExit, 'mako-notifier >= 1.11'):
                target.verify()

    def test_optional_audio_availability_mismatch_still_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            target = self.fixture(Path(work), whisper=True)
            target.path(HOME + '/.config/systemd/user/whisper-transcribe.service').unlink()
            with self.assertRaisesRegex(SystemExit, 'optional Whisper menu/service availability differs'):
                target.verify()

    def test_non_amd64_keeps_native_menu_checks_without_requiring_tomat_binary(self):
        with tempfile.TemporaryDirectory() as work:
            target = self.fixture(Path(work))
            target.arch = 'arm64'
            target.path('/usr/bin/tomat').unlink()
            self.assertIn('menus=5', target.verify())
            self.assertFalse(any(argv[0] == '/usr/bin/tomat' for argv in target.probes))


if __name__ == '__main__':
    unittest.main()
