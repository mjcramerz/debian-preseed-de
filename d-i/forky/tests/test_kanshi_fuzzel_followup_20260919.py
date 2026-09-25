"""Opt-in output management and native menu metadata: no live target mutations.

Package endpoints are mocked. Filesystem cleanup and shell gate/check logic run
against isolated trees. Fuzzel's endpoint is a protocol fixture; this is not a
Wayland/optical acceptance test. Real GIO discovery uses the existing C ABI probe.
"""
from __future__ import annotations
from payload_fixture import shell_directory, installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
from theme_fixture import render_theme_defaults, render_theme_bytes, theme_values
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile
import types
import unittest
from unittest import mock

import test_categorized_menu as categorized
import test_desktop_sandbox as sandbox

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
BIN = TARGET / 'usr/local/bin'
COMPONENTS = render_theme_defaults(payload_read_text(FORKY / 'scripts/desktop/components.sh'))


def load(path):
    module = types.ModuleType('tested_' + path.name.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(render_theme_bytes(payload_read_bytes(path)), str(path), 'exec'), module.__dict__)
    return module


def shell_function(text, name):
    start = text.index(name + '() {\n')
    return text[start:text.index('\n}\n', start) + 3]


class InstallerLoaderTests(unittest.TestCase):
    def test_role_loads_conditional_verifier_before_use(self):
        loader = render_theme_defaults(payload_read_text(FORKY / 'scripts/late/desktop.sh'))
        modules = re.search(r'for desktop_module in ([^;]+); do', loader).group(1).split()
        self.assertIn('verify', modules)
        source = '. "${desktop_module_dir}/verify.sh"'
        self.assertEqual(loader.count(source), 1)
        self.assertLess(loader.index(source), loader.index('run_desktop_late_command "'))
        # Execute the actual fetch/source tail with endpoint-only stubs. Loading
        # modules must define the verifier, not start a broad desktop audit.
        tail = loader[loader.index('desktop_module_dir='):loader.index(': >"$desktop_late_stage_stamp"')]
        with tempfile.TemporaryDirectory(prefix='kanshi-loader-') as temp:
            prelude = """set -eu
runtime_dir=$1
seed=$2
desktop_fixture=$3
requested_seed_base=fixture
requested_host_profile=fixture
fetch_hook() {
  case "$1" in
    scripts/desktop/*) cp -- "$desktop_fixture/${1##*/}" "$2" ;;
    *) fixture_source="$seed/$1"; [ -f "$fixture_source" ] || fixture_source=$fixture_source.tmpl; cp -- "$fixture_source" "$2" ;;
  esac
}
"""
            # The role function is replaced only at its call, leaving the real
            # loader's source list in place, and never running installer writes.
            tail = tail.replace('run_desktop_late_command "$requested_seed_base" "$requested_host_profile"',
                                'command -v desktop_verify_kanshi_policy >/dev/null')
            result = subprocess.run(payload_installed_argv(['/bin/sh', '-c', prelude + tail, 'test', temp, str(FORKY), str(shell_directory(FORKY/'scripts/desktop'))]),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


class KanshiPackageTests(unittest.TestCase):
    def setUp(self):
        self.policy = load(FORKY / 'scripts/desktop/kanshi-policy.py')
        self.temp = tempfile.TemporaryDirectory(prefix='kanshi-policy-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.roots = tuple(self.root / p for p in ('global', 'skel', 'home/.config/systemd/user'))
        for base in self.roots:
            base.mkdir(parents=True, exist_ok=True)
        self.policy.unit_roots = lambda _home: self.roots
        self.policy.WRAPPER = self.root / 'labwc-kanshi'
        self.policy.EXECUTABLES = (self.root / 'bin/kanshi',)

    def managed_tree(self):
        base = TARGET / 'etc/skel-desktop/.config/systemd/user'
        for directory in self.roots:
            (directory / 'kanshi.service').write_bytes(render_theme_bytes(payload_read_bytes(base / 'kanshi.service')))
            (directory / 'kanshi.service.d').mkdir()
            (directory / 'kanshi.service.d/60-resource-class.conf').write_bytes(
                render_theme_bytes(payload_read_bytes(base / 'kanshi.service.d/60-resource-class.conf')))
            wants = directory / 'labwc-session.target.wants'
            wants.mkdir()
            (wants / 'kanshi.service').symlink_to('../kanshi.service')
        self.policy.WRAPPER.write_bytes(render_theme_bytes(payload_read_bytes(TARGET / 'usr/local/libexec/labwc-kanshi')))

    def test_known_fingerprints_match_all_current_installer_assets(self):
        self.managed_tree()
        self.assertEqual(len(self.policy.cleanup_plan(self.home)), 10)

    def test_disabled_fresh_install_does_not_install_package_or_create_assets(self):
        with mock.patch.object(self.policy, 'package_state', return_value='not-installed'), \
                mock.patch.object(self.policy, 'command') as command:
            self.policy.reconcile(False, self.home)
        command.assert_not_called()
        self.assertEqual(self.policy.cleanup_plan(self.home), [])

    def test_disabled_cleanup_removes_only_managed_activation_and_preserves_profiles(self):
        self.managed_tree()
        profile = self.home / '.config/kanshi/config'
        profile.parent.mkdir()
        profile.write_text('administrator monitor calibration\n')
        unrelated = self.roots[2] / 'waybar.service'
        unrelated.write_text('unchanged')
        for _ in range(2):
            with mock.patch.object(self.policy, 'package_state', return_value='not-installed'), \
                    mock.patch.object(self.policy, 'command') as command:
                self.policy.reconcile(False, self.home)
            command.assert_not_called()
        self.assertEqual(self.policy.cleanup_plan(self.home), [])
        self.assertEqual(render_theme_defaults(payload_read_text(profile)), 'administrator monitor calibration\n')
        self.assertEqual(render_theme_defaults(payload_read_text(unrelated)), 'unchanged')
        self.assertFalse(payload_source_exists(self.policy.WRAPPER))
        self.assertFalse(any(payload_source_exists(p / 'kanshi.service.d') for p in self.roots))

    def test_only_exact_package_is_purged_and_never_autoremoved(self):
        self.managed_tree()
        with mock.patch.object(self.policy, 'package_state', side_effect=['installed', 'not-installed']), \
                mock.patch.object(self.policy, 'command') as command:
            self.policy.reconcile(False, self.home)
        command.assert_called_once_with(['/usr/bin/dpkg', '--purge', 'kanshi'])

    def test_reverse_dependency_failure_stops_without_removing_managed_files(self):
        self.managed_tree()
        original = self.policy.cleanup_plan(self.home)
        with mock.patch.object(self.policy, 'package_state', return_value='installed'), \
                mock.patch.object(self.policy, 'command', side_effect=subprocess.CalledProcessError(1, 'dpkg')), \
                self.assertRaises(subprocess.CalledProcessError):
            self.policy.reconcile(False, self.home)
        self.assertEqual(self.policy.cleanup_plan(self.home), original)

    def test_modified_or_unmanaged_files_fail_before_any_package_mutation(self):
        self.managed_tree()
        unit = self.roots[1] / 'kanshi.service'
        unit.write_text('administrator unit\n')
        with mock.patch.object(self.policy, 'command') as command, self.assertRaises(ValueError):
            self.policy.reconcile(False, self.home)
        command.assert_not_called()
        self.assertEqual(render_theme_defaults(payload_read_text(unit)), 'administrator unit\n')
        self.assertTrue(payload_source_exists(self.roots[0] / 'kanshi.service'))

    def test_unknown_dropin_and_foreign_wants_link_are_preserved(self):
        self.managed_tree()
        foreign = self.roots[2] / 'kanshi.service.d/99-admin.conf'
        foreign.write_text('admin')
        with self.assertRaises(ValueError): self.policy.cleanup_plan(self.home)
        self.assertTrue(payload_source_exists(foreign))
        foreign.unlink()
        link = self.roots[2] / 'labwc-session.target.wants/kanshi.service'
        link.unlink(); link.symlink_to('/foreign.service')
        with self.assertRaises(ValueError): self.policy.cleanup_plan(self.home)
        self.assertEqual(os.readlink(link), '/foreign.service')

    def test_symlink_unit_and_parent_are_refused(self):
        unit = self.roots[0] / 'kanshi.service'
        unit.symlink_to('/never-follow')
        with self.assertRaises(ValueError): self.policy.cleanup_plan(self.home)
        unit.unlink()
        self.roots[0].rmdir(); self.roots[0].symlink_to(self.roots[1])
        with self.assertRaises(ValueError): self.policy.cleanup_plan(self.home)

    def test_enabled_installs_authenticated_exact_package_without_removing_others(self):
        with mock.patch.object(self.policy, 'package_state', return_value='installed'), \
                mock.patch.object(self.policy, 'command') as command:
            self.policy.reconcile(True, self.home)
        argv = command.call_args_list[0].args[0]
        self.assertEqual(argv[-2:], ['install', 'kanshi'])
        for option in ('--no-remove', '--no-install-recommends', '--no-install-suggests',
                       'Acquire::AllowInsecureRepositories=false', 'APT::Get::AllowUnauthenticated=false'):
            self.assertIn(option, argv)
        self.assertNotIn('--allow-unauthenticated', argv)

    def test_enabled_missing_package_is_an_error_not_silent_success(self):
        with mock.patch.object(self.policy, 'package_state', return_value='not-installed'), \
                mock.patch.object(self.policy, 'command'), self.assertRaises(RuntimeError):
            self.policy.reconcile(True, self.home)

    def test_dpkg_query_errors_not_confused_with_absence(self):
        for code, expected in ((0, 'installed'), (1, 'not-installed'), (2, None)):
            result = subprocess.CompletedProcess([], code, 'installed', 'failure')
            with self.subTest(code=code), mock.patch.object(self.policy, 'command', return_value=result):
                if expected is None:
                    with self.assertRaises(RuntimeError): self.policy.package_state()
                else: self.assertEqual(self.policy.package_state(), expected)

    def test_command_clean_environment_and_failure_propagation(self):
        result = self.policy.command(['/usr/bin/env'], capture=True)
        self.assertIn('DEBIAN_FRONTEND=noninteractive', result.stdout)
        self.assertNotIn('PYTHONPATH=', result.stdout)
        with self.assertRaises(subprocess.CalledProcessError): self.policy.command(['/usr/bin/false'])

    def test_timeout_reaps_owned_child_and_restores_signal_handlers(self):
        pidfile = self.root / 'pid'
        code = 'import os,time;open(' + repr(str(pidfile)) + ',"w").write(str(os.getpid()));time.sleep(30)'
        before = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        with self.assertRaises(subprocess.TimeoutExpired):
            self.policy.command(['/usr/bin/python3', '-c', code], timeout=.3)
        pid = int(render_theme_defaults(payload_read_text(pidfile)))
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
        self.assertEqual(before, {sig: signal.getsignal(sig) for sig in before})


class KanshiWiringTests(unittest.TestCase):
    def test_package_class_and_all_shipped_profiles_are_opt_out(self):
        role = render_theme_defaults(payload_read_text(FORKY / 'classes/class-select/role/desktop.cfg'))
        self.assertNotIn('kanshi', role.split())
        profiles = list((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            self.assertIn('LABWC_ENABLE_KANSHI="false"', render_theme_defaults(payload_read_text(path)), path.name)

    def test_boolean_policy_and_missing_default(self):
        function = shell_function(render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/detect.sh')), 'desktop_kanshi_enabled')
        for value, expected in (('true',0),('yes',0),('1',0),('on',0),('false',1),('no',1),('0',1),('off',1),('',1),('typo',2)):
            result = subprocess.run(payload_installed_argv(['/bin/sh', '-c', 'desktop_fatal() { exit 2; };\n'+function+'\ndesktop_kanshi_enabled']),
                                    env={'PATH':'/usr/bin:/bin', 'LABWC_ENABLE_KANSHI':value})
            self.assertEqual(result.returncode, expected, value)

    def test_real_staging_gate_and_rendering_do_nothing_when_disabled(self):
        detect = shell_function(render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/detect.sh')), 'desktop_kanshi_enabled')
        gates = re.findall(r'  if desktop_kanshi_enabled; then\n(.*?)\n  fi', COMPONENTS, re.S)
        self.assertEqual(len(gates), 3)
        render = shell_function(COMPONENTS, 'desktop_render_kanshi_config')
        script = detect + '\n' + render + '''
        desktop_log() { :; }
        desktop_stage_role_asset() { printf 'asset %s\\n' "$2"; }
        desktop_render_role_target_template() { printf 'config %s\\n' "$2"; }
        desktop_stage_user_unit_wanted_by() { printf 'enable %s %s\\n' "$1" "$2"; }
        ''' + '\n'.join('if desktop_kanshi_enabled; then\n'+gate+'\nfi' for gate in gates) + '\ndesktop_render_kanshi_config'
        for value in ('false', 'true'):
            result = subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', script]), env={'PATH':'/usr/bin:/bin','LABWC_ENABLE_KANSHI':value},
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if value == 'false': self.assertEqual(result.stdout, '')
            else:
                self.assertEqual(result.stdout.count('\n'), 4)
                self.assertIn('enable kanshi.service labwc-session.target', result.stdout)
                self.assertIn('config /etc/skel-desktop/.config/kanshi/config', result.stdout)

    def test_resource_dropin_requires_base_service_and_copy_is_conditional(self):
        block = COMPONENTS.split('  for resource_unit in \\\n',1)[1].split('\n  done',1)[0]
        self.assertIn('[ -f "$(target_asset_host_path "$resource_base")" ] || continue', block)
        copying = COMPONENTS.split('  for rel in \\\n',1)[1].split('\n  do',1)[0]
        self.assertNotIn('.config/kanshi', copying)
        self.assertIn('if [ "$kanshi_enabled" = true ]; then\n  src=/etc/skel-desktop/.config/kanshi',COMPONENTS)
        activation = COMPONENTS.split('  for unit in \\\n    labwc-output-watch.service',1)[1].split('\n  done',1)[0]
        self.assertNotIn('kanshi',activation)

    def test_install_reconcile_precedes_staging_and_target_check_follows_enablement(self):
        script = render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/labwc.sh')).split('run_desktop_late_command() {',1)[1]
        self.assertLess(script.index('  desktop_install_kanshi_policy'), script.index('  desktop_stage_target_assets'))
        self.assertLess(script.index('  desktop_enable_target_services'), script.index('  desktop_verify_kanshi_policy'))
        self.assertIn('stage_target_asset \\\n', render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/labwc.sh')))

    def verifier(self):
        installer = render_theme_defaults(payload_read_text(FORKY/'scripts/desktop/verify.sh'))
        firstboot = render_theme_defaults(payload_read_text(FORKY/'scripts/firstboot/04-validation.sh'))
        begin='set -eu\n. /etc/labwc/desktop.conf\nhome=$1\n'
        end='printf "desktop_kanshi_verification enabled=%s\\n" "$enabled"'
        scripts=[]
        for source in (installer,firstboot):
            start=source.index(begin); scripts.append(source[start:source.index(end,start)+len(end)])
        self.assertEqual(*scripts)
        return scripts[0]

    def test_both_installed_policy_verifiers_accept_only_matching_states(self):
        script = self.verifier()
        with tempfile.TemporaryDirectory(prefix='kanshi-check-') as directory:
            root=Path(directory); home=root/'home'; home.mkdir()
            (root/'etc/default').mkdir(parents=True)
            commands=root/'commands'; commands.mkdir()
            query=commands/'dpkg-query'; query.write_text('#!/bin/sh\nprintf "%s" "$QUERY_STATE"\nexit "$QUERY_STATUS"\n');query.chmod(0o700)
            script=re.sub(r'(?<![A-Za-z0-9_])/(etc|usr|bin)/', lambda m: str(root)+m.group(0), script)
            env={'PATH':str(commands)+':/usr/bin:/bin', 'QUERY_STATE':'', 'QUERY_STATUS':'1'}
            defaults=root/'etc/labwc/desktop.conf'
            def invoke():
                return subprocess.run(payload_installed_argv(['/bin/sh','-eu','-c',script,'sh',str(home)]), env=env, capture_output=True,text=True)
            defaults.parent.mkdir(parents=True, exist_ok=True)
            defaults.write_text('LABWC_ENABLE_KANSHI=false\n')
            self.assertEqual(invoke().returncode,0)
            env['QUERY_STATUS']='2';self.assertEqual(invoke().returncode,2)
            env.update(QUERY_STATUS='0',QUERY_STATE='installed');self.assertNotEqual(invoke().returncode,0)
            defaults.write_text('LABWC_ENABLE_KANSHI=true\n')
            self.assertNotEqual(invoke().returncode,0)
            for path in ('usr/bin/kanshi','usr/local/libexec/labwc-kanshi'):
                executable=root/path;executable.parent.mkdir(parents=True,exist_ok=True);executable.touch();executable.chmod(0o700)
            for base in (root/'etc/skel-desktop',home):
                for relative in ('.config/kanshi/config','.config/systemd/user/kanshi.service','.config/systemd/user/kanshi.service.d/60-resource-class.conf'):
                    path=base/relative;path.parent.mkdir(parents=True,exist_ok=True);path.touch()
                link=base/'.config/systemd/user/labwc-session.target.wants/kanshi.service'
                link.parent.mkdir();link.symlink_to('../kanshi.service')
            self.assertEqual(invoke().returncode,0,invoke().stderr)
            link.unlink();link.symlink_to('/wrong')
            self.assertNotEqual(invoke().returncode,0)


class NativeMenuTests(unittest.TestCase):
    def setUp(self): self.menu=load(BIN/'labwc-main-menu')

    def test_icons_accept_native_theme_and_absolute_unicode_paths_but_not_protocol_injection(self):
        for icon in ('org.mozilla.firefox', 'code', '/usr/share/icons/app with space.svg', '/home/u/\u00e5.png'):
            self.assertEqual(self.menu.safe_icon(icon), icon)
        for icon in (None, '', 'relative/icon.svg', 'evil\nRow', 'evil\0icon\x1fx', 'a\rB', 'x\x1finfo', 'x'*4097, 'x\u2028y'):
            self.assertEqual(self.menu.safe_icon(icon), self.menu.DEFAULT_ICON)

    def test_exact_native_metadata_and_plain_returned_label(self):
        labels={'Firefox':'firefox.desktop','File icon':'example.desktop',self.menu.BACK:None}
        icons={'Firefox':'firefox','File icon':'/opt/app/icon.png'}
        with mock.patch.object(self.menu.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='Firefox\n')) as run:
            self.assertEqual(self.menu.choose(labels,'Internet',icons),'Firefox')
        self.assertEqual(run.call_args.kwargs['input'], 'Firefox\0icon\x1ffirefox\nFile icon\0icon\x1f/opt/app/icon.png\n'+self.menu.BACK+'\0icon\x1fgo-previous\n')
        self.assertEqual(run.call_args.kwargs['env']['LABWC_FUZZEL_MANAGED_ICONS'],'0')

    def test_duplicate_app_names_keep_individual_native_icon_and_desktop_id(self):
        apps=[{'id':'a.desktop','name':'Same','category':'Other','icon':'a'},
              {'id':'b.desktop','name':'Same','category':'Other','icon':'/opt/b.svg'}]
        with mock.patch.object(self.menu,'choose',side_effect=['Other','Same [b.desktop]']) as choose, \
             mock.patch.object(self.menu.subprocess,'run',return_value=types.SimpleNamespace(stdout=json.dumps(apps))) as run:
            self.menu.run_menu()
        self.assertEqual(choose.call_args.args[2],{'Same [a.desktop]':'a','Same [b.desktop]':'/opt/b.svg'})
        self.assertEqual(run.call_args.args[0], [self.menu.SELF,'--launch=b.desktop'])

    def test_search_root_and_management_configs_all_enable_native_icons(self):
        config=TARGET/'etc/skel-desktop/.config/fuzzel'
        self.assertIn('icons-enabled=yes', render_theme_defaults(payload_read_text(config/'menu.ini.tmpl')))
        self.assertNotIn('icons-enabled=no','\n'.join(render_theme_defaults(payload_read_text(p)) for p in config.glob('*') if payload_source_is_file(p)))
        for key in self.menu.ACTIONS.keys()|self.menu.SETTINGS_ACTIONS.keys()|set(self.menu.DISPLAY_CATEGORIES):
            self.assertIn(key,self.menu.MENU_ICONS)
        self.assertIn('icon-theme=' + theme_values()['FUZZEL_MENU_ICON_THEME'], render_theme_defaults(payload_read_text(config/'base.ini.tmpl')))


class RealGioIconTests(unittest.TestCase):
    setUp=categorized.RealGioSemanticTests.setUp
    write=categorized.RealGioSemanticTests.write
    probe=categorized.RealGioSemanticTests.probe

    def test_effective_user_icon_follows_same_xdg_precedence_as_name_and_exec(self):
        self.write(extra='Icon=vendor-icon\n')
        override=self.write(root=self.data,title='User',extra='Icon=/opt/user icon.svg\n')
        apps=self.probe();self.assertEqual(apps[0]['name'],'User');self.assertEqual(apps[0]['icon'],'/opt/user icon.svg')
        override.unlink(); self.assertEqual(self.probe()[0]['icon'],'vendor-icon')

    def test_absent_and_line_injected_icons_get_safe_fallback(self):
        self.write(name='absent.desktop')
        self.write(name='invalid.desktop',extra=r'Icon=bad\nrow'+'\n')
        apps=self.probe()
        self.assertEqual({app['icon'] for app in apps},{'application-x-executable'})


class NativeShellProtocolTests(unittest.TestCase):
    setUp=sandbox.FuzzelOutputSizingTests.setUp

    def pick(self, labels, *, index=0, prompt='Management', root=False, output=None, mode=None, native=0):
        payload=self.root/'payload'
        fake=self.bin/'fuzzel'
        fake.write_text('''#!/usr/bin/python3
import os,sys
from pathlib import Path
data=sys.stdin.buffer.read();Path(os.environ['CAPTURE']).write_bytes(data)
rows=data.split(b'\\n')
if os.environ.get('OUTPUT_HEX'):
 sys.stdout.buffer.write(bytes.fromhex(os.environ['OUTPUT_HEX']))
else:
 sys.stdout.buffer.write(rows[int(os.environ['INDEX'])].split(b'\\0',1)[0]+b'\\n')
sys.exit(int(os.environ['STATUS']))
''');fake.chmod(0o700)
        env={**self.environment,'LABWC_FUZZEL_MANAGED_ICONS':'1','CAPTURE':str(payload),'INDEX':str(index),'STATUS':str(native),
             'LABWC_FUZZEL_ROOT_MENU':'1' if root else '0'}
        if mode is not None: env['LABWC_MENU_INPUT_MODE']=mode
        if output is not None: env['OUTPUT_HEX']=output.hex()
        data=labels if isinstance(labels,bytes) else ''.join(x+'\n' for x in labels).encode()
        result=subprocess.run(payload_installed_argv(['/bin/sh',str(self.wrapper),'menu','--dmenu','--prompt',prompt]),input=data,env=env,capture_output=True,timeout=10)
        return result,render_theme_bytes(payload_read_bytes(payload)) if payload_source_exists(payload) else b''

    def test_all_six_management_groups_and_twenty_four_actions_have_native_metadata(self):
        management=load(BIN/'labwc-computer-management')
        labels=[*management.MENUS, *(label for entries in management.MENUS.values() for label in entries)]
        result,payload=self.pick(labels,root=True)
        self.assertEqual(result.returncode,0,result.stderr)
        rows=payload.rstrip(b'\n').split(b'\n');self.assertEqual(len(rows),30)
        for label,row in zip(labels,rows):
            text,icon=row.split(b'\0icon\x1f')
            self.assertEqual(text.decode(),label)
            self.assertRegex(icon.decode(),r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
            self.assertNotEqual(icon,b'go-next',label)

    def test_native_icons_roundtrip_legacy_markers_without_changing_dispatch_data(self):
        for label in ('\u2b9e Security Auditing', '\uf07b Package Maintenance', 'Quotes $;\'"` & |', 'Unicode \u00e5\u4e2d'):
            with self.subTest(label=label):
                result,payload=self.pick([label],root=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.decode(),label+'\n')
                self.assertIn(b'\0icon\x1f',payload)
                self.assertNotIn('\u2b9e'.encode(),payload)

    def test_close_returns_original_and_root_exit_is_not_back(self):
        result,payload=self.pick(['Close'])
        self.assertEqual(result.stdout,b'Close\n');self.assertEqual(payload,b'Back\0icon\x1fgo-previous\n')
        result,payload=self.pick(['Exit'],root=True)
        self.assertEqual(result.stdout,b'Exit\n');self.assertIn(b'Exit\0icon\x1fsystem-log-out\n',payload)

    def test_explicit_back_is_not_duplicated_and_added_back_returns_empty(self):
        result,payload=self.pick(['Action','Back'],index=1)
        self.assertEqual(result.stdout,b'Back\n');self.assertEqual(len(payload.splitlines()),2)
        result,payload=self.pick(['Action'],index=1)
        self.assertEqual(result.stdout,b'\n')
        result,payload=self.pick(['\u2190 Back'])
        self.assertEqual(result.stdout,'\u2190 Back\n'.encode())
        self.assertEqual(payload,b'Back\0icon\x1fgo-previous\n')

    def test_collision_suffix_preserves_distinct_raw_rows(self):
        labels=['Same','\u2b9e Same','Same [2:1]']
        for index,label in enumerate(labels):
            result,payload=self.pick(labels,index=index,root=True)
            self.assertEqual(result.stdout.decode(),label+'\n')
            rows=payload.rstrip(b'\n').split(b'\n')
            self.assertEqual(len({row.split(b'\0')[0] for row in rows}),3)

    def test_control_protocol_injection_and_multirow_selection_fail(self):
        for payload in (b'A\0icon\x1fevil\n', b'A\x1fB\n', b'A\rB\n'):
            result,_=self.pick(payload)
            self.assertEqual(result.returncode,2,result.stderr)
        result,_=self.pick(['Allowed'],output=b'Allowed\nExtra\n')
        self.assertEqual(result.returncode,2)

    def test_cancel_and_config_failure_stay_distinct_and_cleanup_occurs(self):
        for native,expected in ((2,1),(1,2),(127,127)):
            result,_=self.pick(['Allowed'],native=native)
            self.assertEqual(result.returncode,expected)
            self.assertFalse(payload_source_exists(self.runtime/'labwc-fuzzel.pid'))
            self.assertFalse(list(self.runtime.glob('labwc-fuzzel-menu.*')))


class ManagementRoutingTests(unittest.TestCase):
    def setUp(self):self.menu=load(BIN/'labwc-computer-management')

    def test_graphical_default_and_explicit_terminal_preserve_scoped_wait_and_icons(self):
        for argv,backend in (([],'fuzzel'),(['--graphical'],'fuzzel'),(['--terminal'],'fzf')):
            with self.subTest(argv=argv), mock.patch.dict(os.environ,{},clear=True), \
                 mock.patch.object(self.menu.os,'geteuid',return_value=1000), mock.patch('builtins.open',mock.mock_open()) as opened, \
                 mock.patch.object(self.menu,'run_menu',return_value=0):
                self.assertEqual(self.menu.main(argv),0)
                self.assertEqual(os.environ['LABWC_MENU_BACKEND'],backend)
                self.assertEqual(os.environ['LABWC_FUZZEL_MANAGED_ICONS'],'1')
                self.assertEqual(os.environ['LABWC_MENU_ACTION_WAIT'],'1')
                self.assertEqual(opened.call_count, int(backend=='fzf'))

    def test_every_route_executes_the_fixed_existing_entrypoint_as_argv(self):
        for entries in self.menu.MENUS.values():
            for label,route in entries.items():
                with self.subTest(label=label),mock.patch.dict(os.environ,{'LABWC_MENU_BACKEND':'fuzzel'}), \
                     mock.patch.object(self.menu.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)) as run, \
                     mock.patch.object(self.menu.Path,'is_file',return_value=False):
                    self.assertEqual(self.menu.run_action(route),0)
                    exe=route[0] if route[0].startswith('/') else '/usr/local/bin/'+route[0]
                    self.assertEqual(run.call_args.args[0], (exe,*route[1:]))
                    self.assertNotIn('shell',run.call_args.kwargs)
                    if exe.startswith('/usr/local/'):
                        self.assertTrue(payload_source_exists(TARGET/exe.lstrip('/')),exe)

    def test_ai_reuses_tty_only_in_explicit_terminal_mode(self):
        with mock.patch.dict(os.environ,{'LABWC_MENU_BACKEND':'fzf'}), \
             mock.patch.object(self.menu.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)) as run, \
             mock.patch.object(self.menu.Path,'is_file',return_value=False):
            self.menu.run_action(('labwc-ai-copilots',))
            self.assertEqual(run.call_args.args[0],('/usr/local/bin/labwc-ai-copilots','--terminal'))

    def test_root_and_child_pick_requests_have_correct_back_policy(self):
        for prompt,expected in (('Computer Management','1'),('Computer Management / System & Recovery','0')):
            with mock.patch.object(self.menu.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='Allowed\n')) as run:
                self.assertEqual(self.menu.choose(['Allowed'],prompt),'Allowed')
                self.assertEqual(run.call_args.kwargs['env']['LABWC_FUZZEL_ROOT_MENU'],expected)
                self.assertEqual(run.call_args.kwargs['env']['LABWC_FUZZEL_MANAGED_ICONS'],'1')


if __name__ == '__main__': unittest.main()
