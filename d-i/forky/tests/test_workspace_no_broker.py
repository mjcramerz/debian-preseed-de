"""Broker retirement and native workspace configuration regressions.

The fixtures relocate only the installation root. They do not start services,
contact Wayland, modify the host, compile binaries or claim live GUI acceptance.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
FORKY = ROOT / 'd-i/forky'
TARGET = FORKY / 'hooks/target'
FIXTURE = FORKY / 'tests/fixtures/workspaces/render.sh'


def embedded_code(filename: str, function: str) -> str:
    source = (FORKY / 'scripts/desktop' / filename).read_text()
    section = source.split(function + '() {', 1)[1].split('\n}\n', 1)[0]
    code = section.split("-c '\n", 1)[1].split("\n' ", 1)[0]
    ast.parse(code)
    return code


def relocate(code: str, root: Path) -> str:
    assert code.count('root = Path("/")') == 1
    return code.replace('root = Path("/")', 'root = Path(' + repr(str(root)) + ')')


def run_code(code: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, '-I', '-B', '-c', code, *arguments],
                          capture_output=True, text=True, timeout=10)


def render(root: Path, count: int, style: str) -> subprocess.CompletedProcess:
    return subprocess.run(['/bin/sh', str(FIXTURE), str(ROOT), str(root), str(count), style],
                          capture_output=True, text=True, timeout=20)


def complete_fixture(root: Path, count: int = 4, style: str = 'thumbnail') -> None:
    result = render(root, count, style)
    if result.returncode:
        raise AssertionError(result.stderr)
    config = root / 'etc/skel-desktop/.config'
    units = config / 'systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    for name in ('waybar.service', 'labwc-session-restore.service'):
        shutil.copyfile(TARGET / 'etc/skel-desktop/.config/systemd/user' / name, units / name)
    shutil.copytree(config, root / 'home/test/.config')


def verifier(root: Path) -> str:
    code = embedded_code('verify.sh', 'desktop_verify_native_workspace_config')
    # Target-version checks are intentionally not faked into GUI acceptance.
    # Test the exact subsequent production checks against a relocated target.
    start = code.index('for package, minimum in ')
    end = code.index('root = Path(', start)
    return relocate(code[:start] + code[end:], root)


class NativeWorkspaceRenderingTests(unittest.TestCase):
    def test_all_twelve_counts_use_native_thumbnails(self):
        for count in range(1, 13):
            with self.subTest(workspaces=count), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                result = render(root, count, 'thumbnail')
                self.assertEqual(result.returncode, 0, result.stderr)
                if count > 1:
                    self.assertIn('task strip omitted', result.stderr)
                else:
                    self.assertNotIn('task strip omitted', result.stderr)
                config = root / 'etc/skel-desktop/.config'
                rc = ET.parse(config / 'labwc/rc.xml').getroot()
                self.assertEqual(int(rc.findtext('desktops/number')), count)
                self.assertEqual([n.text for n in rc.findall('desktops/names/name')],
                                 [str(i) for i in range(1, count + 1)])
                for key, action in (('A-Tab', 'NextWindow'), ('A-S-Tab', 'PreviousWindow')):
                    binding = rc.findall(f'keyboard/keybind[@key="{key}"]')
                    self.assertEqual(len(binding), 1)
                    actions = binding[0].findall('action')
                    self.assertEqual(len(actions), 1)
                    self.assertEqual(actions[0].attrib, dict(name=action, workspace='current',
                                                            output='all', identifier='all'))
                self.assertEqual(rc.find("keyboard/keybind[@key='F13']/action").attrib,
                                 {'name': 'NextWindow', 'workspace': 'current',
                                  'output': 'all', 'identifier': 'all'})
                switchers = rc.findall('windowSwitcher')
                self.assertEqual(len(switchers), 1)
                self.assertEqual(switchers[0].attrib,
                                 dict(preview='yes', outlines='yes', unshade='yes', order='focus'))
                self.assertEqual(switchers[0].find('osd').attrib,
                                 dict(show='yes', style='thumbnail', output='focused',
                                      thumbnailLabelFormat='%n \u2014 %T  %S  %o'))
                # Preserve the existing direct keys for workspaces 1--9.
                # Higher workspaces remain reachable through ext/workspaces.
                for index in range(1, min(count, 9) + 1):
                    for key, name in ((f'W-{index}', 'GoToDesktop'),
                                      (f'W-S-{index}', 'SendToDesktop')):
                        action = rc.find(f'keyboard/keybind[@key="{key}"]/action')
                        self.assertIsNotNone(action)
                        self.assertEqual(action.attrib, dict(name=name, to=str(index)))
                bars = json.loads((config / 'waybar/config').read_text())
                self.assertEqual(len(bars), 2)
                for bar in bars:
                    expected = ['custom/launcher', 'ext/workspaces', 'custom/tomat', 'custom/wayscriber', 'custom/window-switcher', 'group/apps']
                    if count == 1:
                        expected += ['wlr/taskbar']
                    self.assertEqual(bar['modules-left'], expected)
                    self.assertEqual(bar['ext/workspaces']['on-click'], 'activate')
                    self.assertTrue(bar['ext/workspaces']['all-outputs'])
                    self.assertFalse(bar['ext/workspaces']['active-only'])
                    taskbar = bar['wlr/taskbar']
                    self.assertEqual(taskbar['format'], '{icon}')
                    self.assertEqual(taskbar['icon-theme'], 'Papirus-Dark')
                    self.assertFalse(taskbar['all-outputs'])
                    self.assertFalse(taskbar['sort-by-app-id'])
                    self.assertEqual(taskbar['on-click'], 'minimize-raise')
                    self.assertEqual(taskbar['on-click-right'], 'minimize-raise')
                    self.assertEqual(taskbar['on-click-middle'], 'close')
                    self.assertNotIn('group/workspace-taskbar', bar)
                for name in ('waybar/config', 'waybar/style.css', 'labwc/rc.xml'):
                    self.assertNotIn('__INSTALLER_', (config / name).read_text())

    def test_valid_alternative_switcher_profile(self):
        choices = dict(LABWC_WINDOW_SWITCHER_ORDER='age', LABWC_WINDOW_SWITCHER_PREVIEW='no',
                       LABWC_WINDOW_SWITCHER_OUTLINES='no', LABWC_WINDOW_SWITCHER_UNSHADE='no',
                       LABWC_WINDOW_SWITCHER_OSD_OUTPUT='cursor', LABWC_WINDOW_SWITCHER_CYCLE_OUTPUT='focused')
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(['/bin/sh', str(FIXTURE), str(ROOT), temporary, '4', 'thumbnail'],
                                    env=dict(os.environ, **choices), capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            rc = ET.parse(Path(temporary) / 'etc/skel-desktop/.config/labwc/rc.xml').getroot()
            switcher = rc.find('windowSwitcher')
            self.assertEqual(switcher.attrib, dict(order='age', preview='no', outlines='no', unshade='no'))
            self.assertEqual(switcher.find('osd').get('output'), 'cursor')
            for key in ('A-Tab', 'A-S-Tab'):
                action = rc.find(f'keyboard/keybind[@key="{key}"]/action')
                self.assertEqual(action.get('workspace'), 'current')
                self.assertEqual(action.get('output'), 'focused')

    def test_native_theme_geometry_preserved(self):
        text = (TARGET / 'etc/skel-desktop/.config/labwc/themerc-override').read_text()
        for line in ('osd.window-switcher.style-thumbnail.width.max: 82%',
                     'osd.window-switcher.style-thumbnail.item.width: 300',
                     'osd.window-switcher.style-thumbnail.item.height: 230'):
            self.assertIn(line, text)

    def test_switcher_enums_reject_invalid_values(self):
        source = (FORKY / 'scripts/desktop/detect.sh').read_text()
        start = source.index('  case "${LABWC_WINDOW_SWITCHER_STYLE:-thumbnail}"')
        end = source.index('  desktop_validate_uint_range LABWC_QBITTORRENT_PORT', start)
        checks = source[start:end]
        for key, value in (('STYLE', 'broken'), ('STYLE', 'classic'), ('ORDER', 'focus" />'), ('PREVIEW', 'true'),
                           ('OUTLINES', 'yes; id'), ('UNSHADE', 'YES'), ('OSD_OUTPUT', 'HDMI-A-1'),
                           ('CYCLE_OUTPUT', 'other')):
            with self.subTest(key=key):
                env = dict(os.environ, **{'LABWC_WINDOW_SWITCHER_' + key: value})
                code = '. "$1"; installer_fatal() { exit 17; }; ' + checks
                result = subprocess.run(['/bin/sh', '-c', code, 'test',
                                         str(FORKY / 'scripts/desktop/detect.sh')],
                                        env=env, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 17)

    def test_workspace_module_generator_validates_input(self):
        script = ('. "$1"; . "$2"; installer_fatal() { exit 17; }; '
                  'desktop_waybar_modules_left_json')
        for count in ('0', '13', '1; id', '-1', 'one'):
            with self.subTest(count=count):
                result = subprocess.run(['/bin/sh', '-c', script, 'test',
                                         str(FORKY / 'scripts/desktop/detect.sh'),
                                         str(FORKY / 'scripts/desktop/components.sh')],
                                        env=dict(os.environ, LABWC_WORKSPACE_COUNT=count),
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 17)


class InstalledVerifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        complete_fixture(self.root)
        self.code = verifier(self.root)

    def verify(self):
        return run_code(self.code, '/home/test')

    def test_accepts_native_multi_workspace_configuration(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('native=current broker=absent taskbar=omitted-no-workspace-protocol', result.stdout)

    def test_accepts_native_single_workspace_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            complete_fixture(root, 1, 'thumbnail')
            result = run_code(verifier(root), '/home/test')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('taskbar=native-single-workspace', result.stdout)

    def test_rejects_global_taskbar_in_nested_group(self):
        path = self.root / 'etc/skel-desktop/.config/waybar/config'
        bars = json.loads(path.read_text())
        bars[0]['group/apps']['modules'].append('wlr/taskbar')
        path.write_text(json.dumps(bars))
        self.assertIn('global task list enabled', self.verify().stderr)

    def test_rejects_global_alt_tab_in_account_copy(self):
        path = self.root / 'home/test/.config/labwc/rc.xml'
        tree = ET.parse(path)
        tree.find("./keyboard/keybind[@key='A-Tab']/action").set('workspace', 'all')
        tree.write(path, encoding='unicode')
        self.assertIn('non-local A-Tab', self.verify().stderr)

    def test_rejects_list_f13_in_account_copy(self):
        path = self.root / 'home/test/.config/labwc/rc.xml'
        tree = ET.parse(path)
        tree.find("./keyboard/keybind[@key='F13']/action").set('name', 'ShowMenu')
        tree.write(path, encoding='unicode')
        self.assertIn('panel must use the native thumbnail switcher', self.verify().stderr)

    def test_rejects_misplaced_window_switcher_button(self):
        path = self.root / 'etc/skel-desktop/.config/waybar/config'
        bars = json.loads(path.read_text())
        bars[0]['modules-left'].remove('custom/window-switcher')
        path.write_text(json.dumps(bars))
        self.assertIn('native switcher button order changed', self.verify().stderr)

    def test_rejects_classic_list_style(self):
        path = self.root / 'home/test/.config/labwc/rc.xml'
        tree = ET.parse(path)
        tree.find('windowSwitcher/osd').set('style', 'classic')
        tree.write(path, encoding='unicode')
        self.assertIn('native thumbnail switcher required', self.verify().stderr)

    def test_rejects_classic_list_fields(self):
        path = self.root / 'home/test/.config/labwc/rc.xml'
        tree = ET.parse(path)
        fields = ET.SubElement(tree.find('windowSwitcher'), 'fields')
        ET.SubElement(fields, 'field', content='title', width='100%')
        tree.write(path, encoding='unicode')
        self.assertIn('classic list fields must not be configured', self.verify().stderr)

    def test_rejects_stale_broker_executable(self):
        path = self.root / 'usr/local/libexec/labwc-workspace-broker'
        path.parent.mkdir(parents=True)
        path.write_text('retired')
        self.assertIn('retired taskbar executable remains', self.verify().stderr)

    def test_rejects_dangling_broker_enablement(self):
        path = self.root / 'home/test/.config/systemd/user/labwc-session.target.wants/labwc-workspace-broker.service'
        path.parent.mkdir(parents=True)
        path.symlink_to('../labwc-workspace-broker.service')
        self.assertIn('retired taskbar unit remains', self.verify().stderr)

    def test_rejects_stale_service_dependency(self):
        path = self.root / 'home/test/.config/systemd/user/waybar.service'
        path.write_text(path.read_text() + '\nWants=labwc-workspace-broker.service\n')
        self.assertIn('retired dependency', self.verify().stderr)

    def test_rejects_invented_workspace_option(self):
        path = self.root / 'etc/skel-desktop/.config/waybar/config'
        bars = json.loads(path.read_text())
        bars[0]['wlr/taskbar']['current-workspace-only'] = True
        path.write_text(json.dumps(bars))
        self.assertIn('unsupported taskbar workspace option', self.verify().stderr)

    def test_rejects_unresolved_template(self):
        path = self.root / 'etc/skel-desktop/.config/waybar/style.css'
        path.write_text(path.read_text() + '\n/* __INSTALLER_BROKEN__ */\n')
        self.assertIn('unresolved workspace configuration', self.verify().stderr)


class RetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.code = relocate(embedded_code('components.sh', 'desktop_retire_workspace_broker'), self.root)

    def cleanup(self, home='/home/test'):
        return run_code(self.code, home)

    def put(self, relative, text='retired'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_empty_target_is_noop_and_idempotent(self):
        for _ in range(2):
            result = self.cleanup()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('removed=0', result.stdout)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_removes_all_known_modules_and_units_preserves_other_services(self):
        parsed = ast.parse(self.code)
        assignment = next(n for n in parsed.body if isinstance(n, ast.Assign) and
                          any(isinstance(t, ast.Name) and t.id == 'modules' for t in n.targets))
        modules = ast.literal_eval(assignment.value)
        self.assertEqual(len(modules), 15)
        for module in modules:
            self.put('usr/local/lib/labwc-workspace-broker/' + module)
        for entry in ('usr/local/libexec/labwc-workspace-broker',
                      'usr/local/libexec/labwc-workspace-wayland-adapter',
                      'usr/local/bin/labwc-workspace-broker-client'):
            self.put(entry)
        retained = []
        for directory in ('etc/skel-desktop/.config/systemd/user', 'home/test/.config/systemd/user'):
            self.put(directory + '/labwc-workspace-broker.service')
            link = self.root / directory / 'labwc-session.target.wants/labwc-workspace-broker.service'
            link.parent.mkdir(parents=True)
            link.symlink_to('../labwc-workspace-broker.service')
            retained.append(self.put(directory + '/waybar.service', 'leave unchanged'))
            other = link.with_name('dbus.service')
            other.symlink_to('../dbus.service')
            retained.append(other)
        result = self.cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('removed=22', result.stdout)
        self.assertFalse((self.root / 'usr/local/lib/labwc-workspace-broker').exists())
        for path in retained:
            self.assertTrue(path.exists() or path.is_symlink())
        self.assertIn('removed=0', self.cleanup().stdout)

    def test_unlinks_final_symlinks_without_touching_destination(self):
        target = self.put('keep-me', 'not retired')
        link = self.root / 'usr/local/bin/labwc-workspace-broker-client'
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        result = self.cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(link.is_symlink())
        self.assertEqual(target.read_text(), 'not retired')

    def test_symlink_parent_rejected_before_any_deletion(self):
        retained = self.put('usr/local/libexec/labwc-workspace-broker')
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'usr/local/bin').symlink_to(outside, target_is_directory=True)
        result = self.cleanup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlinked retired asset parent', result.stderr)
        self.assertTrue(retained.exists())

    def test_user_unit_symlink_parent_rejected(self):
        retained = self.put('usr/local/libexec/labwc-workspace-broker')
        home = self.root / 'home/test'
        home.mkdir(parents=True)
        (home / '.config').symlink_to(self.root / 'outside')
        result = self.cleanup()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(retained.exists())

    def test_unknown_private_files_preserved(self):
        custom = self.put('usr/local/lib/labwc-workspace-broker/operator-notes.txt', 'keep')
        self.put('usr/local/lib/labwc-workspace-broker/PROTOCOL-LICENSES.txt')
        result = self.cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(custom.read_text(), 'keep')
        self.assertIn('preserved unrecognized files', result.stderr)

    def test_non_file_retired_entry_rejected(self):
        path = self.root / 'usr/local/libexec/labwc-workspace-broker'
        path.mkdir(parents=True)
        result = self.cleanup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing non-file', result.stderr)

    def test_invalid_home_does_not_delete_assets(self):
        retained = self.put('usr/local/libexec/labwc-workspace-broker')
        for home in ('/', '', 'relative', '/home/../root', '/home//test', '/home/test/'):
            with self.subTest(home=home):
                result = self.cleanup(home)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(retained.exists())


class SourceWiringTests(unittest.TestCase):
    def test_retired_runtime_files_absent(self):
        for relative in ('usr/local/lib/labwc-workspace-broker',
                         'usr/local/libexec/labwc-workspace-broker',
                         'usr/local/libexec/labwc-workspace-wayland-adapter',
                         'usr/local/bin/labwc-workspace-broker-client',
                         'etc/skel-desktop/.config/systemd/user/labwc-workspace-broker.service'):
            self.assertFalse((TARGET / relative).exists())
        for path in TARGET.rglob('*'):
            if path.is_file() and path.suffix not in ('.png', '.jpg', '.zip', '.gz', '.xz'):
                self.assertNotIn(b'labwc-workspace-broker', path.read_bytes(), str(path))

    def test_cleanup_and_verification_are_wired(self):
        components = (FORKY / 'scripts/desktop/components.sh').read_text()
        self.assertIn('desktop_stage_labwc_user_session_assets() {\n  desktop_retire_workspace_broker', components)
        verification = (FORKY / 'scripts/desktop/verify.sh').read_text()
        stage = verification.split('desktop_verify_target_staging() {', 1)[1]
        self.assertIn('desktop_verify_native_workspace_config', stage)
        self.assertNotIn('desktop_verify_workspace_broker', stage)
        for path in (FORKY / 'scripts/desktop/detect.sh', TARGET / 'etc/default/labwc-desktop.tmpl'):
            self.assertNotIn('LABWC_WORKSPACE_BROKER_', path.read_text())
        packages = (FORKY / 'classes/class-select/role/desktop.cfg').read_text().split()
        self.assertNotIn('python3-pywayland', packages)
        # These dependencies predated the broker and are not removed wholesale.
        self.assertIn('libmoo-perl', packages)
        self.assertIn('libmoox-options-perl', packages)


if __name__ == '__main__':
    unittest.main()
