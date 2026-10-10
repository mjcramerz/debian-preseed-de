"""Regressions for every distinct denial in the supplied October 4 audit."""
from pathlib import Path
import json
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from payload_fixture import python_library, read_text
from theme_fixture import render_theme_tree


SEED = Path(__file__).resolve().parents[1]
AA = SEED / 'hooks/target/etc/apparmor.d'
INCIDENTS = json.loads((SEED / 'tests/fixtures/installed-apparmor-20261004.json').read_text(encoding='utf-8'))
OCTOBER_9 = json.loads((SEED / 'tests/fixtures/installed-apparmor-20261009.json').read_text(encoding='utf-8'))


def body(file, label):
    text = read_text(AA / file)
    header = re.search(r'(?m)^\s*profile ' + re.escape(label) + r'\s[^\n]*\{\s*$', text)
    if header is None:
        raise AssertionError('missing profile: ' + label)
    result = []
    depth = 1
    for line in text[header.end():].splitlines():
        if not line.lstrip().startswith('#'):
            depth += line.count('{') - line.count('}')
        if depth == 0:
            return '\n'.join(result)
        result.append(line)
    raise AssertionError('unterminated profile: ' + label)


def chatgpt_handoff_paths():
    return [f'/run/user/{uid}/labwc-chatgpt-tmp/{directory}{filename}'
            for uid in ('1000', '23456')
            for directory in ('', 'preview-X/', 'some nested/child/')
            for filename in ('archive.tar.gz', 'document.pdf', 'image.png', 'no-extension',
                             '.partial', 'a file.txt', 'literal[brackets].txt')]


class ChatGPTFileHandoffTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('apparmor_parser') and importlib.util.find_spec('apparmor'),
                         'native AppArmor parser/rule reader unavailable')
    def test_all_repository_profiles_parse_offline_and_expanded_proxy_covers_shared_tree(self):
        from apparmor.rule.file import FileRule
        with tempfile.TemporaryDirectory(prefix='apparmor-file-handoff-') as temporary:
            work = Path(temporary)
            base = work / 'apparmor.d'
            shutil.copytree('/etc/apparmor.d', base, symlinks=True)
            for template in AA.rglob('*.tmpl'):
                (base / template.relative_to(AA).with_name(template.name[:-5])).unlink(missing_ok=True)
            shutil.copytree(AA, base, dirs_exist_ok=True, symlinks=True)
            (base / 'firstboot').unlink(missing_ok=True)
            shutil.copyfile(SEED / 'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl',
                            base / 'firstboot.tmpl')
            render_theme_tree(base)
            media = base / 'local/abstractions/desktop-user-media'
            media.write_text(media.read_text(encoding='utf-8').replace(
                '__INSTALLER_ACCOUNT_USERNAME__', 'fixture'), encoding='utf-8')
            config = work / 'parser.conf'
            config.write_text('', encoding='utf-8')
            cache = work / 'cache'
            cache.mkdir(mode=0o700)
            argv = ['apparmor_parser', '--config-file', str(config),
                    '--cache-loc', str(cache), '-b', str(base), '-I', str(base),
                    '--skip-kernel-load', '--skip-cache', '-j', '1']
            policies = sorted(path.name.removesuffix('.tmpl') for path in AA.iterdir() if path.is_file())
            policies.append('firstboot')
            self.assertTrue(policies)
            for name in policies:
                with self.subTest(policy=name):
                    # One -d checks syntax without building native code or
                    # loading policy. The private config/cache prevent host writes.
                    result = subprocess.run([*argv, '-d', str(base / name)],
                        capture_output=True, text=True, encoding='utf-8', timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            result = subprocess.run([*argv, '-p', str(base / 'desktop-wrappers')],
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            stack = []
            rules = []
            for line in result.stdout.splitlines():
                header = re.match(r'^\s*profile\s+(\S+)\s[^\n]*\{\s*$', line)
                if header:
                    stack.append('//'.join((*stack[-1:], header[1])))
                elif line.strip() == '}':
                    stack.pop()
                elif stack and stack[-1] == 'labwc-chatgpt//chatgpt-dbus-proxy' and line.strip().startswith('owner /run/user/'):
                    rules.append(FileRule.create_instance(line.strip()))
            self.assertEqual(stack, [])
            for path in chatgpt_handoff_paths():
                with self.subTest(shared_file=path):
                    requested = FileRule(path, {'r'}, None, FileRule.ALL, owner=True, log_event=True)
                    self.assertTrue(any(not rule.deny and rule.is_covered(requested) for rule in rules))
            self.assertEqual(list(cache.iterdir()), [])

    def test_proxy_child_has_independent_read_grants_for_shared_files(self):
        policy = body('desktop-wrappers', 'chatgpt-dbus-proxy')
        rule = 'owner /run/user/[0-9]*/{doc,labwc-chatgpt-tmp}/{,**} r,'
        self.assertIn(rule, policy)
        self.assertIn('owner @{HOME}/{Desktop,Documents,Downloads,Music,Pictures,Public,Templates,Videos,Workspace}/{,**} r,', policy)
        self.assertIn('/data/downloads/{,**} r,', policy)
        self.assertIn('/pool/{,**} r,', policy)
        for line in policy.splitlines():
            if 'labwc-chatgpt-tmp' in line or line.strip().startswith(('/data/downloads/', '/pool/')):
                self.assertTrue(line.strip().endswith(' r,'), line)
        self.assertNotIn('/run/user/[0-9]*/** r,', policy)

    @unittest.skipUnless(importlib.util.find_spec('apparmor'), 'native AppArmor rule reader unavailable')
    def test_shared_temp_globs_cover_varied_names_depths_and_uids(self):
        from apparmor.rule.file import FileRule
        policy = body('desktop-wrappers', 'chatgpt-dbus-proxy')
        rules = [FileRule.create_instance(line.strip()) for line in policy.splitlines()
                 if line.strip().startswith(('owner /', '/data/downloads/', '/pool/'))]
        for path in chatgpt_handoff_paths():
            with self.subTest(shared_file=path):
                # Denial paths are literal filenames, including spaces and
                # glob characters; they are not AppArmor policy expressions.
                requested = FileRule(path, {'r'}, None, FileRule.ALL, owner=True, log_event=True)
                self.assertTrue(any(not rule.deny and rule.is_covered(requested) for rule in rules))
                for rule in rules:
                    if rule.path.match(path):
                        self.assertTrue(rule.owner)
                        self.assertEqual(rule.perms, {'r'})
                        self.assertIsNone(rule.exec_perms)
        for path in ('/run/user/1000/labwc-other-tmp/file',
                     '/run/user/1000/labwc-chatgpt-tmp-neighbor/file'):
            requested = FileRule.create_instance(f'owner "{path}" r,')
            self.assertFalse(any(not rule.deny and rule.is_covered(requested) for rule in rules))
        requested = FileRule.create_instance('"/run/user/1000/labwc-chatgpt-tmp/file" r,')
        self.assertFalse(any(not rule.deny and rule.is_covered(requested) for rule in rules))

    def test_launcher_payload_and_desktop_tools_cover_same_user_temp_tree(self):
        for label in ('labwc-chatgpt', 'chatgpt-bwrap'):
            policy = body('desktop-wrappers', label)
            self.assertIn('owner /run/user/[0-9]*/labwc-chatgpt-tmp/ rw,', policy)
            self.assertIn('owner /run/user/[0-9]*/labwc-chatgpt-tmp/** rwkl,', policy)
        documents = read_text(AA / 'abstractions/user-documents')
        self.assertIn('owner /run/user/[0-9]*/labwc-chatgpt-tmp/{,**} rwkl,', documents)
        self.assertIn('#include <abstractions/user-documents>', body('desktop-utilities', 'desktop-launcher'))
        parent = body('desktop-wrappers', 'labwc-chatgpt')
        self.assertIn('/usr/bin/xdg-dbus-proxy rCx -> chatgpt-dbus-proxy,', parent)
        self.assertIn('/usr/bin/bwrap rCx -> chatgpt-bwrap,', parent)
        child = body('desktop-wrappers', 'chatgpt-bwrap')
        self.assertIn('/usr/lib/chatgpt/ChatGPT rix,', child)
        self.assertNotRegex(child, r'/usr/lib/chatgpt/ChatGPT\s+[^,]*[pPcCuU]')


class SuppliedDenialTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('apparmor'), 'native AppArmor rule reader unavailable')
    def test_october_9_signal_and_netlink_requests_are_covered_by_exact_rules(self):
        from apparmor.rule.signal import SignalRule
        from apparmor.rule.network import NetworkRule
        for event in OCTOBER_9['events']:
            if event['class'] == 'signal':
                policy = body('desktop-utilities', event['profile'])
                requested = SignalRule.create_instance(
                    f"signal ({event['requested_mask']}) set=({event['signal']}) peer={event['peer']},")
                rules = [SignalRule.create_instance(line.strip()) for line in policy.splitlines()
                         if line.strip().startswith('signal ')]
                self.assertTrue(any(not rule.deny and rule.is_covered(requested) for rule in rules), event)
            elif event['class'] == 'net':
                policy = body('desktop-utilities', event['profile'])
                requested = NetworkRule.create_instance(f"network {event['family']} {event['sock_type']},")
                rules = [NetworkRule.create_instance(line.strip()) for line in policy.splitlines()
                         if line.strip().startswith('network ')]
                self.assertTrue(any(not rule.deny and rule.is_covered(requested) for rule in rules), event)
            else:
                self.assertEqual(event['class'], 'file', event)

    def test_codex_apt_state_read_and_btop_transition_do_not_add_privilege(self):
        runtime = read_text(AA / 'abstractions/codex-runtime')
        self.assertIn('/var/lib/apt/extended_states r,', runtime)
        monitor = body('desktop-utilities', 'desktop-btop')
        self.assertIn('signal (send),', monitor)
        self.assertIn('ptrace (read),', monitor)
        self.assertNotRegex(monitor, r'(?m)^\s*capability (?:kill|setuid|setgid),')
        self.assertIn('capability sys_ptrace,', monitor)
        self.assertIn('deny ptrace (trace),', monitor)
        self.assertIn('@{PROC}/[0-9]*/ r,', monitor)
        self.assertIn('@{PROC}/[0-9]*/net/{tcp,tcp6,udp,udp6} r,', monitor)
        self.assertIn('@{PROC}/[0-9]*/{cmdline,comm,exe,limits,loginuid,oom_score,oom_score_adj,stat,statm,status,io,sched,schedstat,smaps_rollup,wchan,cgroup} r,', monitor)
        self.assertNotRegex(monitor, r'(?m)^\s*(?:allow )?ptrace\s*\([^)]*\btrace\b')
        self.assertNotRegex(monitor, r'(?m)^\s*/(?:usr/bin|bin)/[^\n]*\s+[^,]*x')
        self.assertIn('/usr/bin/btop rPx -> desktop-btop,', body('desktop-utilities', 'desktop-launcher'))
        self.assertIn('/usr/bin/btop rPx -> desktop-btop,', body('labwc-session', 'waybar'))
        receiver = read_text(AA / 'abstractions/base.d/managed-process-monitor')
        self.assertIn('signal (receive) peer=desktop-btop,', receiver)
        self.assertIn('ptrace (readby) peer=desktop-btop,', receiver)
        self.assertNotRegex(receiver, r'(?m)^\s*(?:signal \(send|ptrace \(trace|capability|/[^\n]+\s+[^,]*[wx])')
        stages = read_text(SEED / 'scripts/late/security.sh')
        self.assertIn('"/etc/apparmor.d/abstractions/base.d/managed-process-monitor" 0644', stages)
        waybar = read_text(SEED / 'hooks/target/etc/skel-desktop/.config/waybar/config.tmpl')
        btop_actions = [line for line in waybar.splitlines() if 'labwc-terminal -e btop' in line]
        self.assertEqual(len(btop_actions), 4)
        for action in btop_actions:
            self.assertIn('"on-click": "/usr/local/bin/labwc-terminal -e btop"', action)
        terminal = read_text(SEED / 'hooks/target/usr/local/bin/labwc-terminal')
        self.assertIn('exec /usr/local/bin/labwc-wayland-app auto -- "$terminal_exec" -e "$@"', terminal)
        with mock.patch.object(sys, 'path', [str(python_library(
                SEED / 'hooks/target/usr/local/lib/python3.14/dist-packages')), *sys.path]):
            from labwc_managed_app import generic
        with mock.patch.object(generic, 'assert_launch_allowed'), \
             mock.patch.object(generic, 'restart_token', return_value='fixture'), \
             mock.patch.object(generic, 'menu_action_wait_arguments', return_value=[]):
            for executable in ('/usr/bin/foot', '/usr/bin/kitty', '/usr/bin/terminal-emulator'):
                argv = generic.transient_argv('wayland', 'auto', [executable, '-e', 'btop'], {})
                for property_ in ('ExitType=main', 'ProtectProc=default', 'ProcSubset=all'):
                    self.assertIn('--property=' + property_, argv)

    @unittest.skipUnless(shutil.which('apparmor_parser') and importlib.util.find_spec('apparmor'),
                         'native AppArmor parser/rule reader unavailable')
    def test_native_parser_expands_btop_receiver_for_apps_and_future_profiles(self):
        from apparmor.rule.signal import SignalRule
        from apparmor.rule.ptrace import PtraceRule
        with tempfile.TemporaryDirectory(prefix='btop-user-signals-') as temporary:
            base = Path(temporary) / 'apparmor.d'
            shutil.copytree('/etc/apparmor.d', base, symlinks=True)
            for template in AA.rglob('*.tmpl'):
                (base / template.relative_to(AA).with_name(template.name[:-5])).unlink(missing_ok=True)
            shutil.copytree(AA, base, dirs_exist_ok=True, symlinks=True)
            render_theme_tree(base)
            config = base / 'parser.conf'
            config.write_text('', encoding='utf-8')
            future = base / 'future-fixture'
            future.write_text('#include <tunables/global>\nprofile future-app-fixture {\n include <abstractions/base>\n}\n', encoding='utf-8')
            seen = set()
            labels = ('labwc-chatgpt//chatgpt-bwrap', 'labwc-app//app-bwrap', 'labwc-app//code-bwrap',
                      'codex-wrapper//codex-bwrap', 'labwc-wayland-compat-app//wayland-compat-app-bwrap',
                      'labwc-qbittorrent//qbittorrent-bwrap', 'desktop-btop', 'future-app-fixture')
            for name in ('desktop-wrappers', 'desktop-utilities', 'zoom-discord-compat', 'chatgpt', 'future-fixture'):
                result = subprocess.run(['apparmor_parser', '--config-file', str(config), '-b', str(base), '-I', str(base),
                    '-Q', '-K', '-p', str(base / name)], capture_output=True, text=True, encoding='utf-8', timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                policies = {}
                stack = []
                for line in result.stdout.splitlines():
                    header = re.match(r'^\s*profile\s+(\S+)\s[^\n]*\{\s*$', line)
                    if header:
                        label = '//'.join((*stack[-1:], header[1]))
                        stack.append(label)
                        policies[label] = []
                    elif line.strip() == '}':
                        stack.pop()
                    elif stack:
                        policies[stack[-1]].append(line.strip())
                for label in labels:
                    if label not in policies:
                        continue
                    seen.add(label)
                    rules = policies[label]
                    signals = [SignalRule.create_instance(line) for line in rules if re.match(r'^(?:audit |deny )*signal\b', line)]
                    receivers = [rule for rule in signals if not rule.deny and 'receive' in (rule.access or ('send', 'receive'))
                                 and not rule.all_peers and rule.peer.regex == 'desktop-btop']
                    self.assertTrue(receivers, 'missing btop receive permission: ' + label)
                    if label == 'desktop-btop':
                        self.assertTrue(any(not rule.deny and 'send' in (rule.access or ('send', 'receive')) and rule.all_peers for rule in signals))
                    observers = [PtraceRule.create_instance(line) for line in rules if re.match(r'^(?:audit |deny )*ptrace\b', line)]
                    self.assertTrue(any(not rule.deny and 'readby' in (rule.access or ('read', 'readby', 'trace', 'tracedby')) and not rule.all_peers
                                        and rule.peer.regex == 'desktop-btop' for rule in observers), label)
            self.assertEqual(seen, set(labels))

    def test_external_drives_native_metadata_probe_needs_no_root_directory_grant(self):
        policy = body('desktop-wrappers', 'labwc-external-drives')
        self.assertNotIn('  / r,', policy)
        self.assertNotIn('  /**/ r,', policy)
        worker = read_text(SEED / 'hooks/target/usr/local/bin/labwc-external-drives')
        self.assertIn('metadata = os.lstat(sys.argv[1])', worker)
        self.assertIn('/usr/bin/python3 -I -B -c', worker)
        self.assertNotIn('find -P "$runtime_root"', worker)
        self.assertNotRegex(policy, r'(?m)^\s*(?:owner )?/\*\*\s+[^,]*[rw]')
        self.assertNotRegex(policy, r'(?m)^\s*/\s+[^,]*[wxmk]')

    def test_mpv_proc_identity_and_state_access_stays_scoped(self):
        policy = body('desktop-utilities', 'desktop-media')
        self.assertIn('owner @{PROC}/[0-9]*/task/[0-9]*/comm rw,', policy)
        self.assertIn('@{sys}/devices/virtual/dmi/id/{board_vendor,bios_vendor} r,', policy)
        self.assertIn('owner @{HOME}/.local/state/mpv/ rw,', policy)
        self.assertIn('owner @{HOME}/.local/state/mpv/** rwklm,', policy)
        # The media profile must not gain generic procfs or sysfs write access
        # while fixing these observed, same-user read/write denials.
        self.assertNotRegex(policy, r'(?m)^\s*@\{PROC\}/\*\*\s+[rw]')
        self.assertNotRegex(policy, r'(?m)^\s*@\{sys\}/\*\*\s+[rw]')

    def test_october_6_apt_can_read_private_archives_without_dac_write_override(self):
        policy = body('desktop-wrappers', 'labwc-wrap-desktop-files')
        self.assertIn('capability dac_read_search,', policy)
        self.assertNotRegex(policy, r'(?m)^\s*capability dac_override,')
        self.assertIn('/home/*/**.deb r,', policy)
        self.assertIn('/var/lib/labwc-desktop-files/{,**} rw,', policy)
        self.assertIn('/usr/bin/{gzip,tar,xz,zstd} rix,', policy)

    def test_october_6_mount_credential_drop_is_isolated_from_desktop_tools(self):
        parent = body('desktop-utilities', 'desktop-launcher')
        child = body('desktop-utilities', 'mount-user')
        self.assertIn('/usr/bin/{mount,umount} rCx -> mount-user,', parent)
        self.assertNotRegex(parent, r'(?m)^  capability (?:setuid|setgid),$')
        self.assertIn('capability setuid,', child)
        self.assertIn('capability setgid,', child)
        self.assertNotIn('capability sys_admin,', child)
        self.assertNotRegex(child, r'(?m)^\s*(?:mount|umount)\b')

    def test_october_6_pgrep_reads_metadata_and_keeps_environments_private(self):
        child = body('desktop-wrappers', 'waypaper-pgrep')
        self.assertIn('@{PROC}/[0-9]*/{cmdline,stat,status,cgroup} r,', child)
        self.assertIn('@{PROC}/tty/drivers r,', child)
        self.assertIn('@{sys}/devices/system/node/ r,', child)
        self.assertIn('deny @{PROC}/[0-9]*/environ r,', child)
        self.assertIn('deny ptrace (read),', child)
        self.assertIn('deny capability sys_ptrace,', child)

    @unittest.skipUnless(importlib.util.find_spec('apparmor'), 'native AppArmor rule reader unavailable')
    def test_native_rule_reader_keeps_env_and_qbittorrent_inherit_execution(self):
        from apparmor.rule.file import FileRule
        for file, label, executable in (
                ('labwc-session', 'labwc-compositor', '/usr/bin/env'),
                ('desktop-wrappers', 'qbittorrent-bwrap', '/usr/bin/qbittorrent')):
            lines = [line.strip() for line in body(file, label).splitlines()
                     if line.strip().startswith(executable + ' ')]
            self.assertEqual(len(lines), 1)
            rule = FileRule.create_instance(lines[0])
            self.assertEqual(rule.path.regex, executable)
            self.assertEqual(rule.exec_perms, 'ix')
            self.assertTrue(rule.all_targets)
            self.assertFalse(rule.deny)

    @unittest.skipUnless(importlib.util.find_spec('apparmor'), 'native AppArmor rule reader unavailable')
    def test_tailscale_desktop_probe_inherits_confinement_under_no_new_privileges(self):
        from apparmor.rule.file import FileRule
        parent = body('usr.sbin.tailscaled', 'usr.sbin.tailscaled')
        lines = [line.strip() for line in parent.splitlines()
                 if line.strip().startswith('/usr/bin/loginctl ')]
        self.assertEqual(len(lines), 1)
        rule = FileRule.create_instance(lines[0])
        self.assertEqual(rule.exec_perms, 'ix')
        self.assertTrue(rule.all_targets)
        self.assertFalse(rule.deny)
        self.assertNotIn('profile loginctl ', parent)
        service = read_text(SEED / 'hooks/target/etc/systemd/system/tailscaled.service.d/override.conf')
        self.assertIn('NoNewPrivileges=true', service)

    def test_compositor_env_helper_inherits_confinement_without_missing_transition(self):
        policy = body('labwc-session', 'labwc-compositor')
        self.assertIn('/usr/bin/env rix,', policy)
        self.assertIn('/usr/bin/* rPx,', policy)
        self.assertIn('/usr/local/{bin,sbin,libexec}/** rPx,', policy)
        self.assertNotRegex(policy, r'/usr/bin/env\s+[^,]*[pPcCuU]')
        self.assertNotRegex(policy, r'/usr/bin/\*\s+[^,]*[uU]')
        generic = body('desktop-wrappers', 'labwc-generic-app')
        self.assertIn('/usr/local/bin/labwc-{electron,wayland}-app rix,', generic)
        self.assertIn('#include <abstractions/managed-app-config>', generic)
        config = read_text(AA / 'abstractions/managed-app-config')
        for location in ('.cache', '.config', '.local/share', '.local/state', '.var/app'):
            self.assertIn(f'owner @{{HOME}}/{location}/** rwkl,', config)
        staging = read_text(SEED / 'scripts/late/security.sh')
        self.assertIn('etc/apparmor.d/abstractions/managed-app-config', staging)
        self.assertIn('"/etc/apparmor.d/abstractions/managed-app-config"', staging)
        launcher = body('desktop-utilities', 'desktop-launcher')
        self.assertIn('/usr/bin/** rPix,', launcher)
        self.assertRegex(read_text(AA / 'desktop-utilities'),
                         r'(?m)^profile desktop-launcher /usr/bin/\{[^}]*\bthunar\b')

    @unittest.skipUnless(shutil.which('apparmor_parser'), 'native AppArmor parser unavailable')
    def test_native_parser_permissions_cover_nested_documents_usb_and_unclean_journals(self):
        # These are the parser's effective expanded file-rule masks and glob
        # expressions, not a textual include check or a kernel policy load.
        with tempfile.TemporaryDirectory(prefix='desktop-permissions-') as temporary:
            base = Path(temporary) / 'apparmor.d'
            shutil.copytree('/etc/apparmor.d', base, symlinks=True)
            for template in AA.rglob('*.tmpl'):
                (base / template.relative_to(AA).with_name(template.name[:-5])).unlink(missing_ok=True)
            shutil.copytree(AA, base, dirs_exist_ok=True, symlinks=True)
            (base / 'firstboot').unlink(missing_ok=True)
            shutil.copyfile(SEED / 'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl',
                            base / 'firstboot.tmpl')
            render_theme_tree(base)
            # The installer renders the validated primary account separately
            # from appearance/logging. This fixture has no real account data.
            media = base / 'local/abstractions/desktop-user-media'
            media.write_text(media.read_text(encoding='utf-8').replace(
                '__INSTALLER_ACCOUNT_USERNAME__', 'fixture'), encoding='utf-8')
            config = base / 'parser.conf'
            config.write_text('', encoding='utf-8')
            argv = ['apparmor_parser', '--config-file', str(config), '-b', str(base), '-I', str(base),
                    '-Q', '-K', '-j', '1']
            debug_output = []
            converted_output = []
            # Each policy owns its ABI declaration. Parse the actual policy
            # files independently, then combine only the parser's output.
            for name in ('desktop-wrappers', 'desktop-utilities', 'document-applications',
                         'usr.bin.qbittorrent', 'usr.sbin.tailscaled', 'firstboot', 'app-veth',
                         'zoom-discord-compat', 'labwc-session', 'opt.postman.app.Postman'):
                for option, output in (('-d', debug_output), ('--dump=rule-exprs', converted_output)):
                    result = subprocess.run([*argv, option, str(base / name)], capture_output=True,
                                            text=True, encoding='utf-8', timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output.extend((result.stdout, result.stderr))
            normalize = lambda value: re.sub(r'/+', '/', value)
            file_patterns = {normalize(pattern) for pattern in
                             re.findall(r'^Perms:.*Name:\s*\((.*)\)$', '\n'.join(debug_output), re.M)}
            expressions = {normalize(pattern): re.compile(expression) for pattern, expression in
                           re.findall(r'^aare: (.*?)[ \t]+->\s+(.*)$', '\n'.join(converted_output), re.M)
                           if normalize(pattern) in file_patterns}
            rules = {}
            native_rules = {}
            name = label = None
            for line in '\n'.join(debug_output).splitlines():
                if line.startswith('Name:'):
                    name = line.split(':', 1)[1].strip()
                elif line.startswith('Local To:'):
                    parent = line.split(':', 1)[1].strip()
                    label = name if parent == '<NULL>' else parent + '//' + name
                    rules[label] = []
                    native_rules[label] = []
                elif line.startswith('Perms:'):
                    match = re.fullmatch(r'Perms:\s*([^:]*):([^ ]*)\s+priority=\d+\s+Name:\s*\((.*)\)', line)
                    self.assertIsNotNone(match, line)
                    owner, other, pattern = match.groups()
                    rules[label].append((expressions[normalize(pattern)], set(owner), set(other)))
                elif label is not None:
                    native_rules[label].append(line)
            def permissions(label, filename, owned=True):
                result = set()
                for expression, owner, other in rules[label]:
                    if expression.fullmatch(filename):
                        result.update(owner if owned else other)
                return result
            for event in OCTOBER_9['events']:
                if event['class'] != 'file':
                    continue
                with self.subTest(installed_october_9=event):
                    self.assertLessEqual(set(event['requested_mask']), set('crwxmd'))
                    required = set(event['requested_mask'].replace('c', 'w').replace('d', 'w'))
                    self.assertLessEqual(required, permissions(event['profile'], event['name'],
                                                              owned=event['fsuid'] == event['ouid']))
            # Replay every file denial class from the October 9 installed logs.
            for filename in ('/home/fixture/.local/state/btop.log',
                             '/home/fixture/.local/state/btop.log.1'):
                self.assertTrue(set('rw') <= permissions('desktop-btop', filename))
                self.assertNotIn('w', permissions('desktop-btop', filename, owned=False))
            payload = 'labwc-app//app-bwrap'
            # Replay the new browser/notification denials with compiler-expanded
            # owner bounds and inherited execution in the existing payload.
            for helper in ('hostname', 'file', 'expr'):
                for prefix in ('/usr/bin/', '/bin/'):
                    self.assertTrue(set('rx') <= permissions(payload, prefix + helper, owned=False))
                self.assertIn('/{,usr/}bin/{hostname,file,expr} rix,',
                              read_text(AA / 'abstractions/desktop-runtime'))
            for filename in ('/etc/chromium.d/90-performance-flags',
                             '/etc/magic', '/usr/lib/file/magic.mgc'):
                self.assertIn('r', permissions(payload, filename, owned=False))
                self.assertNotIn('w', permissions(payload, filename, owned=False))
            for label in ('labwc-app//app-bwrap', 'qbittorrent',
                          'labwc-qbittorrent//qbittorrent-bwrap', 'postman', 'session-controls'):
                self.assertTrue(set('rx') <= permissions(label, '/usr/bin/hostname', owned=False))
                self.assertIn('w', permissions(label, '/home/fixture/'))
                self.assertNotIn('w', permissions(label, '/home/fixture/', owned=False))
            self.assertTrue(set('rw') <= permissions(payload, '/run/user/1000/pulse/'))
            self.assertNotIn('w', permissions(payload, '/run/user/1000/pulse/', owned=False))
            # Direct audio clients retain read-only host-directory metadata.
            self.assertNotIn('w', permissions('postman', '/run/user/1000/pulse/'))
            self.assertTrue(set('rw') <= permissions('postman', '/home/fixture/Postman/files/'))
            self.assertTrue(set('rw') <= permissions(payload, '/home/fixture/Postman/files/'))
            self.assertNotIn('w', permissions(payload, '/home/fixture/Postman/files/', owned=False))
            cdm = '/home/fixture/.config/vivaldi/WidevineCdm/4.10.3112.0/_platform_specific/linux_x64/libwidevinecdm.so'
            self.assertIn('m', permissions(payload, cdm))
            self.assertNotIn('m', permissions(payload, cdm, owned=False))
            self.assertNotIn('m', permissions(payload, '/home/fixture/.config/vivaldi/unrelated.so'))
            for label in ('session-controls', 'session-glycin-bwrap'):
                for app, prefix in (('vivaldi', 'com.vivaldi.Vivaldi'),
                                    ('chromium', 'org.chromium.Chromium'),
                                    ('microsoft-edge', 'com.microsoft.Edge')):
                    icon = f'/run/user/1000/labwc-{app}-tmp/.{prefix}.scoped_dir.r8I9pb/icon.png'
                    self.assertEqual(permissions(label, icon), {'r'})
                    self.assertFalse(permissions(label, icon, owned=False))
                    for filename in (icon.replace('icon.png', 'Cookies'),
                                     icon.replace('icon.png', 'nested/icon.png'),
                                     icon.replace('icon.png', 'icon.png.exe'),
                                     icon.replace('-tmp/', '-tmp-neighbor/'),
                                     icon.replace('labwc-' + app, 'labwc-code')):
                        self.assertFalse(permissions(label, filename), (label, filename))
            self.assertTrue(set('rw') <= permissions(payload, '/etc/opt/'))
            for directory in ('/etc/opt/chrome/', '/etc/opt/chrome/native-messaging-hosts/'):
                self.assertTrue(set('rw') <= permissions(payload, directory))
                self.assertNotIn('w', permissions(payload, directory, owned=False))
            self.assertNotIn('w', permissions(payload, '/etc/opt/chrome/policies/managed/policy.json'))
            self.assertNotIn('w', permissions(payload, '/etc/opt/chrome/native-messaging-hosts/untrusted.json'))
            self.assertNotIn('w', permissions(payload, '/etc/opt/edge/policies/managed/policy.json', owned=False))
            proxy = '/home/fixture/.mozilla/native-messaging-hosts/.bitwarden_desktop_proxy'
            self.assertTrue(set('rwx') <= permissions(payload, proxy))
            self.assertNotIn('w', permissions(payload, proxy, owned=False))
            self.assertFalse(permissions(payload, '/home/fixture/.mozilla/native-messaging-hosts/unrelated-helper'))
            for filename in ('/usr/share/keepassxc/translations/keepassxc_en.qm',
                             '/usr/share/keepassxc/wordlists/',
                             '/usr/share/keepassxc/wordlists/eff_large.wordlist',
                             '/sys/devices/pci0000:00/0000:00:0d.0/usb1/speed',
                             '/sys/devices/pci0000:00/0000:00:14.0/usb3/3-1/speed'):
                self.assertEqual(permissions(payload, filename, owned=False), {'r'})
            self.assertNotIn('w', permissions(payload, '/sys/devices/pci0000:00/usb1/speed', owned=False))
            # LPL-746: opening /proc/self/ns/net was mediated as the nsfs
            # root "/" under attach_disconnected. Numeric procfs rules and
            # /net:[inode] alone missed this path and stopped the boot pool.
            # Check the actual compiler masks for the broker and every shared
            # namespace client, including Podman and the compatibility parent.
            for label in ('app-veth', 'app-veth-podman', 'codex-wrapper', 'codex-runtime',
                          'labwc-chatgpt', 'labwc-app', 'labwc-qbittorrent',
                          'labwc-wayland-compat-app'):
                with self.subTest(disconnected_namespace_reader=label):
                    self.assertEqual(permissions(label, '/', owned=False), {'r'}, label)
                    self.assertIn('r', permissions(label, '/proc/12345/ns/net', owned=False))
                    self.assertIn('r', permissions(label, '/net:[4026531840]', owned=False))
                    if label not in ('app-veth', 'app-veth-podman'):
                        self.assertIn('r', permissions(label, '/pid:[4026531836]', owned=False))
            self.assertEqual(permissions('app-veth', '/user:[4026531837]', owned=False), {'r'})
            # An exact root read must not grant recursive reads or any writes
            # to the host filesystem, nor other users' procfs file descriptors.
            for label in ('app-veth', 'app-veth-podman'):
                for filename in ('/root/private.txt', '/home/other/private.txt',
                                 '/proc/12345/fd/9'):
                    self.assertFalse(permissions(label, filename, owned=False), (label, filename))
            # nsfs bind mounts have root-owned inode metadata even though the
            # surrounding Podman runtime belongs to devops. Permit that exact
            # endpoint without granting access to other accounts' runtime data.
            endpoint = '/run/podman-devops/containers/networks/rootless-netns/rootless-netns'
            self.assertEqual(permissions('app-veth-podman', endpoint, owned=False), {'r'})
            self.assertFalse(permissions('app-veth-podman',
                                         '/run/podman-devops/private.env', owned=False))
            # Forky's /usr/sbin/ip is a compatibility symlink to /usr/bin/ip;
            # AppArmor mediates the resolved executable path.
            for executable in ('/usr/sbin/ip', '/usr/bin/ip'):
                self.assertTrue(set('rx') <= permissions('app-veth', executable, owned=False), executable)
            for filename in ('/usr/share/iproute2/group', '/usr/share/iproute2/rt_tables',
                             '/usr/share/iproute2/rt_realms'):
                self.assertEqual(permissions('app-veth', filename, owned=False), {'r'}, filename)
            for label in ('labwc-app//app-bwrap', 'desktop-editors', 'focuswriter', 'zathura', 'desktop-launcher'):
                for directory in ('Downloads', 'Documents', 'Pictures', 'Workspace', 'Syncthing'):
                    with self.subTest(label=label, directory=directory):
                        self.assertTrue(set('rwk') <= permissions(label, f'/home/fixture/{directory}/nested/document.pdf'))
                self.assertTrue(set('rwk') <= permissions(label, '/run/media/fixture/USB/nested/document.pdf'))
                self.assertTrue(set('rwk') <= permissions(
                    label, '/run/media/fixture/USB/nested/group-owned.pdf', owned=False))
                self.assertNotIn('w', permissions(
                    label, '/run/media/another-account/USB/document.pdf', owned=False))
            for path in (
                    '/home/fixture/.config/future-app/settings.json',
                    '/home/fixture/.cache/future-app/cache.db',
                    '/home/fixture/.local/share/future-app/data.db',
                    '/home/fixture/.local/state/future-app/state',
                    '/home/fixture/.var/app/future-app/config'):
                with self.subTest(managed_app_state=path):
                    self.assertTrue(set('rwk') <= permissions('labwc-generic-app', path))
            self.assertNotIn('w', permissions('labwc-generic-app', '/home/fixture/.ssh/id_ed25519'))
            for location in ('run', 'var'):
                filename = f'/{location}/log/journal/machine/user-1000@rotated.journal~'
                self.assertIn('r', permissions('desktop-launcher', filename, owned=False))
                self.assertNotIn('w', permissions('desktop-launcher', filename, owned=False))
            # thunar-volman inherits desktop-launcher. Replay the October 7
            # root-owned udev input metadata reads and preserve their bounds.
            for filename in ('+input:input33', '+input:input34', 'c13:73', 'c13:72', 'c13:34',
                             '+input:input0', '+input:input1234', 'c13:0', 'c13:1234'):
                with self.subTest(thunar_volman_metadata=filename):
                    self.assertEqual(permissions('desktop-launcher', '/run/udev/data/' + filename,
                                                 owned=False), {'r'})
            for filename in ('/run/udev/data/+input:inputx', '/run/udev/data/c13:x',
                             '/run/udev/data/+net:eth0', '/run/udev/data/c14:73',
                             '/run/udev/data/+input:input33/child', '/run/udev/data/c13:73/child'):
                with self.subTest(thunar_volman_excluded_path=filename):
                    self.assertFalse(permissions('desktop-launcher', filename, owned=False))
            execution = permissions('labwc-qbittorrent//qbittorrent-bwrap',
                                    '/usr/bin/qbittorrent', owned=False)
            # The compiler debug mask reports r/x/m, while the native rule
            # reader above independently reports the inherited execution mode.
            self.assertTrue(set('rx') <= execution, execution)
            self.assertFalse(permissions('labwc-qbittorrent', '/usr/bin/pasta', owned=False))
            self.assertTrue(set('rw') <= permissions('labwc-qbittorrent', '/run/app-veth/control.sock', owned=False))
            query = 'usr.sbin.tailscaled'
            self.assertTrue(set('rx') <= permissions('usr.sbin.tailscaled', '/usr/bin/loginctl', owned=False))
            self.assertNotIn('usr.sbin.tailscaled//loginctl', native_rules)
            self.assertTrue(set('rw') <= permissions(query, '/run/dbus/system_bus_socket', owned=False))
            for path in ('/usr/bin/bash', '/usr/bin/sudo'):
                self.assertFalse(permissions(query, path, owned=False))
            sends = [line for line in native_rules[query] if line.startswith('dbus ( send )')]
            logind = [line for line in sends if 'name="org.freedesktop.login1"' in line]
            self.assertEqual(len(logind), 2)
            self.assertTrue(any('member="{ListSessions,ListSessionsEx,GetSession}"' in line
                                and 'path="/org/freedesktop/login1"' in line for line in logind))
            self.assertTrue(any('member="{Get,GetAll}"' in line
                                and 'path="/org/freedesktop/login1/session/*"' in line for line in logind))
            self.assertFalse(permissions('labwc-qbittorrent//qbittorrent-bwrap', '/dev/net/tun', owned=False))
            self.assertFalse(permissions('labwc-qbittorrent//qbittorrent-bwrap', '/run/app-veth/control.sock', owned=False))
            for parent, child in (
                    ('codex-wrapper', 'codex-wrapper//codex-bwrap'),
                    ('codex-runtime', 'codex-runtime//codex-bwrap'),
                    ('labwc-chatgpt', 'labwc-chatgpt//chatgpt-bwrap'),
                    ('labwc-app', 'labwc-app//app-bwrap'),
                    ('labwc-app', 'labwc-app//code-bwrap'),
                    ('labwc-qbittorrent', 'labwc-qbittorrent//qbittorrent-bwrap')):
                with self.subTest(namespace_reader=parent, payload=child):
                    self.assertIn('r', permissions(parent, '/proc/12345/ns/net', owned=False))
                    self.assertTrue(set('rw') <= permissions(parent, '/run/app-veth/control.sock', owned=False))
                    if child.endswith('//code-bwrap'):
                        # The debug masks also list deny rules. Confirm this
                        # explicit denial through the native rule reader;
                        # AppArmor deny always overrides an inherited allow.
                        from apparmor.rule.file import FileRule
                        rule = FileRule.create_instance('deny /run/app-veth/{,**} rw,')
                        self.assertTrue(rule.deny)
                        self.assertIn('deny /run/app-veth/{,**} rw,', body('desktop-wrappers', 'code-bwrap'))
                    else:
                        self.assertFalse(permissions(child, '/run/app-veth/control.sock', owned=False))
                    for table in ('tcp', 'tcp6', 'udp', 'udp6'):
                        self.assertEqual(permissions(child, '/proc/12345/net/' + table, owned=False), {'r'})
            self.assertTrue(set('rx') <= permissions('labwc-app//app-bwrap', '/usr/bin/mpv', owned=False))
            self.assertTrue(set('rx') <= permissions('labwc-app//app-bwrap', '/usr/bin/liferea', owned=False))
            self.assertEqual(permissions('labwc-app//app-bwrap', '/proc/2/cmdline', owned=False), {'r'})
            self.assertTrue(set('rx') <= permissions('labwc-app//app-bwrap', '/usr/bin/wl-copy', owned=False))
            self.assertTrue(set('rw') <= permissions('labwc-app//app-bwrap', '/run/user/1000/.obsidian-cli.sock'))
            self.assertNotIn('w', permissions('labwc-app//app-bwrap', '/run/user/1000/.obsidian-cli.sock', owned=False))
            self.assertTrue(set('rw') <= permissions('labwc-app', '/run/user/1000/labwc-chromium-tmp/'))
            self.assertFalse(permissions('labwc-app//app-bwrap', '/usr/bin/sudo', owned=False))
            self.assertTrue(set('rx') <= permissions('labwc-app//code-bwrap', '/usr/bin/git', owned=False))
            self.assertTrue(set('rw') <= permissions('desktop-media', '/proc/12345/task/12346/comm'))
            self.assertEqual(permissions('desktop-media', '/sys/devices/virtual/dmi/id/board_vendor', owned=False), {'r'})
            self.assertEqual(permissions('desktop-media', '/sys/devices/virtual/dmi/id/bios_vendor', owned=False), {'r'})
            self.assertTrue(set('rw') <= permissions('desktop-media', '/dev/pts/0'))
            self.assertNotIn('w', permissions('desktop-media', '/dev/pts/0', owned=False))
            self.assertTrue(set('rw') <= permissions('desktop-media', '/home/fixture/.local/state/mpv/'))
            filen_helper = '/home/fixture/.config/@filen/desktop/rclone/bin/1.74.3/.copy-1.74.3-2'
            self.assertTrue(set('rx') <= permissions('labwc-app//app-bwrap', filen_helper))
            self.assertNotIn('x', permissions('labwc-app//app-bwrap', filen_helper, owned=False))
            self.assertFalse(permissions('labwc-external-drives', '/', owned=False))
            self.assertFalse(permissions('labwc-external-drives', '/root/private.txt', owned=False))
            self.assertTrue(set('rx') <= permissions('crowdsec-firstboot', '/usr/bin/sha256sum', owned=False))
            self.assertTrue(set('rw') <= permissions('crowdsec-firstboot',
                                                   '/var/lib/firstboot/crowdsec/capi-activated', owned=False))
            for directory in ('Desktop', 'Documents', 'Downloads', 'Music', 'Pictures',
                              'Public', 'Templates', 'Videos'):
                self.assertTrue(set('rwk') <= permissions('labwc-chatgpt//chatgpt-bwrap',
                    f'/home/fixture/{directory}/nested/download.pdf'))
            self.assertTrue(set('rwk') <= permissions('labwc-chatgpt//chatgpt-bwrap',
                '/run/user/1000/doc/fixture/download.pdf'))
            self.assertNotIn('w', permissions('labwc-chatgpt', '/home/fixture/.ssh/id_ed25519'))
            # Replay all October 7 qBittorrent file denials in the compiler's
            # effective policy for both direct and Bubblewrap launches.
            for label in ('qbittorrent', 'labwc-qbittorrent//qbittorrent-bwrap'):
                with self.subTest(qbittorrent_profile=label):
                    self.assertEqual(permissions(label, '/sys/block/', owned=False), {'r'})
                    self.assertNotIn('r', permissions(label, '/sys/block/sda/size', owned=False))
                    for device in ('/sys/devices/virtual/block/dm-1', '/sys/devices/virtual/block/zram0',
                                   '/sys/devices/pci0000:00/nvme/nvme0/nvme0n1',
                                   '/sys/devices/pci0000:00/usb1/1-2/block/sda'):
                        for leaf in ('dev', 'queue/rotational', 'queue/dax'):
                            self.assertEqual(permissions(label, device + '/' + leaf, owned=False), {'r'})
                    for device in ('/dev/dm-1', '/dev/zram0', '/dev/sda', '/dev/nvme0n1',
                                   '/sys/devices/virtual/block/dm-1/size'):
                        self.assertFalse(permissions(label, device, owned=False))
                    for pid in ('2', '21822'):
                        for attribute in ('cmdline', 'stat'):
                            filename = f'/proc/{pid}/{attribute}'
                            self.assertEqual(permissions(label, filename), {'r'})
                            self.assertNotIn('r', permissions(label, filename, owned=False))
                        self.assertNotIn('r', permissions(label, f'/proc/{pid}/environ'))
                    self.assertTrue(set('rw') <= permissions(label, '/dev/pts/0'))
            for label in ('codex-wrapper//codex-bwrap', 'codex-runtime//codex-bwrap'):
                with self.subTest(codex_profile=label):
                    self.assertEqual(permissions(label, '/var/lib/dpkg/diversions', owned=False), {'r'})
            self.assertIn('r', permissions('labwc-qbittorrent', '/proc/12058/fd/'))
            self.assertNotIn('r', permissions('labwc-qbittorrent', '/proc/12058/fd/', owned=False))
            self.assertIn('r', permissions('labwc-qbittorrent',
                                           '/run/systemd/resolve/resolv.conf', owned=False))
            self.assertNotIn('w', permissions('labwc-qbittorrent',
                                              '/run/systemd/resolve/resolv.conf', owned=False))
            # The direct profile has no namespace-construction grants, so a
            # terminal from another account does not acquire access here.
            self.assertFalse(permissions('qbittorrent', '/dev/pts/0', owned=False))
            usb = '/sys/devices/pci0000:00/0000:00:14.0/usb1/1-2'
            for attribute in ('bcdDevice', 'version', 'bDeviceClass', 'bDeviceSubClass',
                              'bDeviceProtocol', 'devpath', 'speed', 'bConfigurationValue',
                              'bInterfaceNumber', 'bInterfaceClass', 'bInterfaceSubClass',
                              'bInterfaceProtocol', 'interface'):
                with self.subTest(samloader_attribute=attribute):
                    directory = usb + '/1-2:1.0' if attribute.startswith('bInterface') or attribute == 'interface' else usb
                    path = directory + '/' + attribute
                    allowed = permissions('samloader', path, owned=False)
                    self.assertIn('r', allowed)
                    self.assertNotIn('w', allowed)
            for attribute in ('cmdline', 'stat', 'status'):
                self.assertIn('r', permissions('waypaper//waypaper-pgrep',
                                              '/proc/1234/' + attribute, owned=False))
            # -d lists a deny entry with its requested mask too; it does not
            # distinguish deny from allow. Check the policy's explicit denial
            # and that this is the sole native entry matching environments.
            self.assertIn('deny @{PROC}/[0-9]*/environ r,', body('desktop-wrappers', 'waypaper-pgrep'))
            environment_entries = [entry for entry in rules['waypaper//waypaper-pgrep']
                                   if entry[0].fullmatch('/proc/1234/environ')]
            self.assertEqual(len(environment_entries), 1)
            for desktop in ('md.obsidian.Obsidian.desktop', 'obsidian.desktop'):
                allowed = permissions('apt-repo-local-software-update',
                                      '/usr/share/applications/' + desktop, owned=False)
                self.assertIn('r', allowed)
                self.assertFalse(set('wx') & allowed)
            for archive in ('/home/fixture/Workspace/iocost-lab/output/session/dependencies/apt-archives/oomd.deb',
                            '/var/cache/apt/archives/oomd.deb'):
                allowed = permissions('labwc-wrap-desktop-files', archive, owned=False)
                self.assertIn('r', allowed)
                self.assertFalse(set('wx') & allowed)
            self.assertTrue(set('rx') <= permissions('labwc-wrap-desktop-files', '/usr/bin/tar', owned=False))
            for scratch in ('/var/lib/labwc-desktop-files/metadata-fixture',
                            '/var/lib/labwc-desktop-files/#1234'):
                self.assertTrue(set('rw') <= permissions('labwc-wrap-desktop-files', scratch))
            for outside in ('/tmp/tmpfixture', '/var/tmp/tmpfixture', '/home/fixture/private.txt'):
                self.assertNotIn('w', permissions('labwc-wrap-desktop-files', outside))

    def test_qbittorrent_kernel_network_keeps_authority_in_supervisor(self):
        payload = body('desktop-wrappers', 'qbittorrent-bwrap')
        parent = body('desktop-wrappers', 'labwc-qbittorrent')
        self.assertIn('#include <abstractions/python>', payload)
        self.assertIn('/usr/bin/python3{,.[0-9]*} rix,', payload)
        self.assertIn('signal (receive) set=(exists kill term) peer=labwc-qbittorrent,', payload)
        self.assertIn('signal (send) peer=labwc-qbittorrent//qbittorrent-bwrap,', parent)
        self.assertIn('#include <abstractions/app-veth-client>', parent)
        self.assertNotIn('app-veth-client', payload)
        self.assertNotIn('/dev/net/tun', payload)
        self.assertNotIn('/usr/bin/pasta', parent)

    def test_document_media_identity_map_is_validated_and_staged(self):
        source = (SEED / 'scripts/late/security.sh').read_text(encoding='utf-8')
        start = source.index('apparmor_document_media_placeholder_map() {')
        function = source[start:source.index('\n}', start) + 2]
        code = 'set -eu\ninstaller_fatal() { printf "%s\\n" "$*" >&2; return 1; }\n' + function + '\napparmor_document_media_placeholder_map\n'
        for shell in (['/bin/dash'], ['busybox', 'sh']):
            for account in ('fixture', '_desktop', 'desktop-user_2'):
                result = subprocess.run([*shell, '-c', code], env={'PATH': '/usr/bin:/bin', 'ACCOUNT_USERNAME': account},
                                        capture_output=True, text=True, encoding='utf-8', timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, f'ACCOUNT_USERNAME={account}\n')
            for account in ('', 'root', 'nobody', 'nogroup', '../fixture', '*', 'fixture/other', 'Fixture', '1fixture', 'f' * 33):
                result = subprocess.run([*shell, '-c', code], env={'PATH': '/usr/bin:/bin', 'ACCOUNT_USERNAME': account},
                                        capture_output=True, text=True, encoding='utf-8', timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
        stage = source.split('stage_target_desktop_apparmor_profiles() {', 1)[1].split('\n}', 1)[0]
        self.assertRegex(stage, r'render_target_asset_with_placeholder_map\s+\\\n.*local/abstractions/desktop-user-media[.]tmpl[\s\S]*?0644\s+\\\n\s+apparmor_document_media_placeholder_map')
        self.assertIn('include if exists <local/abstractions/desktop-user-media>',
                      read_text(AA / 'abstractions/user-documents'))

    def test_document_media_rule_is_published_by_the_actual_scalar_renderer(self):
        # Only transport is replaced with a local copy. The repository's real
        # private-work-directory publisher and scalar renderer run in /tmp.
        code = '''set -eu
installer_fatal() { printf '%s\\n' "$*" >&2; return 1; }
. "$1/scripts/common/modules/files-logging.sh"
. "$1/scripts/common/target.sh"
. "$1/scripts/late/target-assets.sh"
. "$1/scripts/late/security.sh"
fetch_hook() { cp "$1" "$2"; }
render_target_asset_with_placeholder_map "$2" /etc/apparmor.d/local/abstractions/desktop-user-media 0644 apparmor_document_media_placeholder_map
'''
        template = AA / 'local/abstractions/desktop-user-media.tmpl'
        for shell in (['/bin/dash'], ['busybox', 'sh']):
            with tempfile.TemporaryDirectory(prefix='media-rule-publication-') as temporary:
                root = Path(temporary)
                environment = {'PATH': '/usr/bin:/bin', 'ACCOUNT_USERNAME': 'fixture',
                               'INSTALLER_TARGET_DIR': str(root)}
                argv = [*shell, '-c', code, 'media-rule-fixture', str(SEED), str(template)]
                result = subprocess.run(argv, env=environment, capture_output=True, text=True,
                                        encoding='utf-8', timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                destination = root / 'etc/apparmor.d/local/abstractions/desktop-user-media'
                expected = template.read_text(encoding='utf-8').replace('__INSTALLER_ACCOUNT_USERNAME__', 'fixture')
                self.assertEqual(destination.read_text(encoding='utf-8'), expected)
                self.assertEqual(destination.stat().st_mode & 0o777, 0o644)
                result = subprocess.run(argv, env={**environment, 'ACCOUNT_USERNAME': '../other'},
                                        capture_output=True, text=True, encoding='utf-8', timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(destination.read_text(encoding='utf-8'), expected)
                self.assertFalse(list(root.rglob('.installer-asset.*')))

    def test_ksecretd_gpgme_smime_probe_inherits_wallet_confinement(self):
        policy = body('labwc-session', 'ksecretd')
        self.assertIn('/usr/bin/gpgsm rix,', policy)
        self.assertNotRegex(policy, r'/usr/bin/gpg\*')
        self.assertNotRegex(policy, r'\b[uU][xX]\b')

    def test_all_logged_file_and_execution_requests_have_scoped_grants(self):
        sources = {
            'wpctl': body('labwc-session', 'wpctl'),
            'labwc-generic-app': body('desktop-wrappers', 'labwc-generic-app'),
            'mullvad-vpn': body('desktop-wrappers', 'mullvad-vpn'),
            'mullvad': read_text(AA / 'local/mullvad'),
            'labwc-wayland-compat-app//wayland-compat-app-bwrap':
                body('zoom-discord-compat', 'wayland-compat-app-bwrap'),
        }
        requests = [r for r in INCIDENTS if r['class'] == 'file' and r['profile'] in sources
                    and r['operation'] != 'mkdir']
        self.assertEqual(len(requests), 6)
        for event in requests:
            with self.subTest(event=event):
                policy = sources[event['profile']]
                if event['name'].startswith('/proc/'):
                    self.assertEqual(event['denied_mask'], 'r')
                    self.assertTrue(event['name'].endswith('/cmdline'))
                    # Root-owned inodes are present in the supplied namespace
                    # audit, so an owner-qualified permission is insufficient.
                    self.assertRegex(policy, r'(?m)^\s*@\{PROC\}/\[0-9\]\*/cmdline r,$')
                else:
                    mode = 'rix' if event['denied_mask'] == 'x' else 'r'
                    self.assertRegex(policy, r'(?m)^\s*' + re.escape(event['name']) + ' ' + mode + ',$')

    def test_process_reads_are_allowed_by_reader_and_each_target(self):
        reader = body('desktop-wrappers', 'waypaper-ps')
        targets = {
            'bitwarden': body('opt.Bitwarden.bitwarden', 'bitwarden'),
            'hardware-tuning-client': body('hardware-tuning', 'hardware-tuning-client'),
            'mullvad': read_text(AA / 'local/mullvad'),
            'vivaldi-bin': read_text(AA / 'local/vivaldi-bin'),
            'vivaldi-stable': read_text(AA / 'local/vivaldi-stable'),
            'whisper-record-toggle': body('desktop-wrappers', 'whisper-record-toggle'),
        }
        requests = [r for r in INCIDENTS if r['class'] == 'ptrace'
                    and r['profile'] == 'waypaper//waypaper-ps']
        self.assertEqual({r['peer'] for r in requests}, set(targets))
        for event in requests:
            with self.subTest(event=event):
                self.assertEqual(event['profile'], 'waypaper//waypaper-ps')
                self.assertEqual(event['denied_mask'], 'read')
                self.assertIn('ptrace (read) peer=' + event['peer'] + ',', reader)
                self.assertIn('ptrace (readby) peer=waypaper//waypaper-ps,', targets[event['peer']])
        self.assertNotRegex(reader, r'ptrace\s*\([^)]*\btrace\b')
        self.assertNotRegex(reader, r'ptrace\s*\([^)]*\)\s*peer=[^,]*\*')

    @unittest.skipUnless(shutil.which('apparmor_parser') and importlib.util.find_spec('apparmor'),
                         'native AppArmor parser/rule reader unavailable')
    def test_waypaper_process_reads_cover_managed_app_and_helper_peers(self):
        # October 5 events 1429-1469 repeat nine reader/peer pairs. Expand the
        # actual includes so nested children cannot pass on a parent's rule.
        from apparmor.rule.ptrace import PtraceRule
        peers = (
            'labwc-chatgpt-log-runner', 'labwc-chatgpt',
            'labwc-chatgpt//chatgpt-dbus-proxy', 'labwc-chatgpt//chatgpt-bwrap',
            'labwc-app', 'labwc-app//app-bwrap',
            'codex-wrapper', 'codex-wrapper//codex-bwrap',
        )
        with tempfile.TemporaryDirectory(prefix='waypaper-process-policy-') as temporary:
            base = Path(temporary) / 'apparmor.d'
            shutil.copytree('/etc/apparmor.d', base, symlinks=True)
            for template in AA.rglob('*.tmpl'):
                (base / template.relative_to(AA).with_name(template.name[:-5])).unlink(missing_ok=True)
            shutil.copytree(AA, base, dirs_exist_ok=True, symlinks=True)
            render_theme_tree(base)
            config = base / 'parser.conf'
            config.write_text('', encoding='utf-8')
            result = subprocess.run(
                ['apparmor_parser', '--config-file', str(config), '-b', str(base), '-I', str(base),
                 '-Q', '-K', '-p', str(base / 'desktop-wrappers')],
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        profiles = {}
        stack = []
        for line in result.stdout.splitlines():
            header = re.match(r'^\s*profile\s+(\S+)\s[^\n]*\{\s*$', line)
            if header:
                label = '//'.join((*stack[-1:], header[1]))
                stack.append(label)
                profiles[label] = []
            elif line.strip() == '}':
                stack.pop()
            elif stack and re.match(r'\s*(?:(?:audit|deny|allow)\s+)*ptrace\b', line):
                profiles[stack[-1]].append(PtraceRule.create_instance(line.strip()))
        self.assertEqual(stack, [])
        for parent, child in (
                ('codex-wrapper', 'codex-wrapper//codex-bwrap'),
                ('codex-runtime', 'codex-runtime//codex-bwrap'),
                ('labwc-chatgpt', 'labwc-chatgpt//chatgpt-bwrap'),
                ('labwc-app', 'labwc-app//app-bwrap'),
                ('labwc-app', 'labwc-app//code-bwrap'),
                ('labwc-qbittorrent', 'labwc-qbittorrent//qbittorrent-bwrap')):
            for label, peer, access in ((parent, child, 'read'), (child, parent, 'readby')):
                with self.subTest(namespace_reader=label, peer=peer):
                    grants = [rule for rule in profiles[label] if not rule.all_peers and rule.peer.regex == peer]
                    self.assertTrue(grants)
                    self.assertTrue(all(not rule.deny and rule.access == {access} for rule in grants))
        observer = 'waypaper//waypaper-ps'
        reader = profiles[observer]
        for rule in reader:
            self.assertFalse(rule.all_access)
            self.assertFalse(rule.deny)
            self.assertTrue(rule.access <= {'read', 'readby', 'tracedby'})
            # The distribution base permits incoming readby/tracedby;
            # Waypaper's outgoing reads must still name an exact peer.
            if 'read' in rule.access:
                self.assertFalse(rule.all_peers)
                self.assertNotIn('*', rule.peer.regex)
        for peer in peers:
            with self.subTest(peer=peer):
                grants = [rule for rule in reader if not rule.all_peers and rule.peer.regex == peer]
                self.assertTrue(grants, 'missing reader grant for ' + peer)
                self.assertTrue(all(rule.access == {'read'} for rule in grants))
                reciprocal = [rule for rule in profiles[peer]
                              if not rule.all_peers and rule.peer.regex == observer]
                self.assertTrue(reciprocal, 'missing peer readby grant for ' + peer)
                self.assertTrue(all(not rule.deny and not rule.all_access
                                    and rule.access == {'readby'} for rule in reciprocal))

    def test_rfkill_and_proc_grants_do_not_add_writes_or_execution(self):
        for file, label in (('labwc-session', 'wpctl'), ('desktop-wrappers', 'labwc-generic-app')):
            with self.subTest(profile=label):
                rules = [l.strip() for l in body(file, label).splitlines()
                         if l.strip().startswith('/dev/rfkill ')]
                self.assertEqual(rules, ['/dev/rfkill r,'])
        child = body('zoom-discord-compat', 'wayland-compat-app-bwrap')
        self.assertNotRegex(child, r'(?m)^\s*@\{PROC\}/\*\*')
        rules = [l.strip() for l in child.splitlines()
                 if l.strip().startswith('@{PROC}/[0-9]*/cmdline ')]
        self.assertEqual(rules, ['@{PROC}/[0-9]*/cmdline r,'])

    def test_microphone_pulse_client_has_only_the_observed_extra_file_access(self):
        requests = [r for r in INCIDENTS if r['profile'] == 'labwc-mute-default-microphone']
        self.assertEqual({(r['operation'], r['name'], r['denied_mask']) for r in requests}, {
            ('open', '/dev/shm/', 'r'), ('open', '/etc/machine-id', 'r'),
            ('chmod', '/run/user/1000/pulse/', 'w'), ('rmdir', '/run/user/1000/pulse/', 'd')})
        policy = body('desktop-wrappers', 'labwc-mute-default-microphone')
        self.assertIn('/dev/shm/ r,', policy)
        self.assertIn('/etc/machine-id r,', policy)
        self.assertIn('owner /run/user/[0-9]*/pulse/ rw,', policy)
        audio = read_text(AA / 'abstractions/pipewire-audio')
        self.assertIn('owner /run/user/[0-9]*/pulse/{native,pid} rwk,', audio)
        self.assertIn('deny /dev/snd/** rwklm,', audio)
        self.assertNotRegex(policy, r'(?m)^\s*(?:owner )?/dev/shm/\*\*')
        self.assertNotRegex(policy, r'(?m)^\s*(?:owner )?/etc/machine-id [^,]*[wxmk]')

    def test_qbittorrent_exec_inherits_payload_runtime_under_no_new_privs(self):
        requests = [r for r in INCIDENTS if r['profile'] == 'labwc-qbittorrent//qbittorrent-bwrap']
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['info'], 'no new privs')
        child = body('desktop-wrappers', 'qbittorrent-bwrap')
        self.assertIn('/usr/bin/qbittorrent rix,', child)
        self.assertIn('#include <abstractions/qbittorrent-runtime>', child)
        self.assertNotRegex(child, r'/usr/bin/qbittorrent r[PpCc].*->')
        self.assertNotRegex(child, r'\b[uU][xX]\b')
        payload = body('usr.bin.qbittorrent', 'qbittorrent')
        self.assertIn('#include <abstractions/qbittorrent-runtime>', payload)
        self.assertNotIn('bwrap-common', payload)

    def test_october_5_tuta_child_and_document_apps_have_document_access(self):
        # Validate the domain actually named by the supplied audit, not just
        # the direct /opt/tuta-mail attachment which is unused inside bwrap.
        for policy in (body('desktop-wrappers', 'labwc-app'),
                       body('desktop-wrappers', 'app-bwrap')):
            self.assertIn('#include <abstractions/user-documents>', policy)
            self.assertNotRegex(policy, r'(?m)^\s*deny .*\b(?:Downloads|Documents|Pictures|Workspace)\b')
        runtime = read_text(AA / 'abstractions/document-runtime')
        self.assertIn('#include <abstractions/user-documents>', runtime)
        for file, label in (('document-applications', 'focuswriter'),
                            ('document-applications', 'zathura'),
                            ('desktop-utilities', 'desktop-editors')):
            self.assertIn('#include <abstractions/document-runtime>', body(file, label))
        importer = body('document-applications', 'focuswriter-import')
        self.assertIn('/run/media/{,**} r,', importer)

    def test_user_journal_backup_access_is_read_only_in_both_locations(self):
        policy = body('desktop-utilities', 'desktop-launcher')
        self.assertIn('/{run,var}/log/journal/*/user-[0-9]*.journal{,~} r,', policy)
        self.assertNotRegex(policy, r'(?m)^\s*/.*log/journal/.*\s+[a-z]*[wka][a-z]*,')

    def test_btop_peers_have_both_read_only_endpoints(self):
        requests = [r for r in INCIDENTS if r['profile'] == 'desktop-launcher']
        self.assertEqual({r['peer'] for r in requests},
                         {'labwc-waybar-battery', 'labwc-brightness-control'})
        reader = body('desktop-utilities', 'desktop-launcher')
        base = read_text(AA / 'abstractions/wrapper-base')
        self.assertIn('ptrace (readby) peer=desktop-launcher,', base)
        for event in requests:
            self.assertEqual(event['denied_mask'], 'read')
            self.assertIn('ptrace (read) peer=' + event['peer'] + ',', reader)
        battery = body('labwc-session', 'labwc-waybar-battery')
        brightness = body('desktop-wrappers', 'labwc-brightness-control')
        self.assertIn('#include <abstractions/wrapper-python>', battery)
        self.assertIn('#include <abstractions/wrapper-desktop>', brightness)
        for abstraction in ('wrapper-python', 'wrapper-desktop'):
            self.assertIn('#include <abstractions/wrapper-base>',
                          read_text(AA / ('abstractions/' + abstraction)))

    def test_codex_worker_accepts_termination_from_its_own_wrapper(self):
        requests = [r for r in INCIDENTS if r['class'] == 'signal']
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['peer'], 'codex-wrapper')
        self.assertEqual(requests[0]['signal'], 'kill')
        parent = body('desktop-wrappers', 'codex-wrapper')
        child = body('desktop-wrappers', 'codex-bwrap')
        self.assertIn('signal (send, receive) peer=codex-wrapper//codex-bwrap,', parent)
        self.assertIn('signal (receive) set=(exists hup int quit term kill) peer=codex-wrapper,', child)
        self.assertNotRegex(child, r'(?m)^\s*signal\s*(?:\([^)]*\))?\s*,$')

    def test_mullvad_dconf_cache_does_not_allow_settings_database_writes(self):
        requests = [r for r in INCIDENTS if r['profile'] == 'mullvad' and r['operation'] == 'mkdir']
        self.assertEqual(len(requests), 1)
        policy = read_text(AA / 'local/mullvad')
        self.assertIn('owner @{HOME}/.cache/dconf/ rw,', policy)
        self.assertIn('owner @{HOME}/.cache/dconf/user rw,', policy)
        self.assertNotRegex(policy, r'(?m)^\s*(?:owner )?@\{HOME\}/\.config/dconf/.*w')


if __name__ == '__main__':
    unittest.main()
