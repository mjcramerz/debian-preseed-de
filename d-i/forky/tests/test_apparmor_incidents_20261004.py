"""Regressions for every distinct denial in the supplied October 4 audit."""
from pathlib import Path
import json
import importlib.util
import re
import shutil
import subprocess
import tempfile
import unittest

from payload_fixture import read_text
from theme_fixture import render_theme_tree


SEED = Path(__file__).resolve().parents[1]
AA = SEED / 'hooks/target/etc/apparmor.d'
INCIDENTS = json.loads((SEED / 'tests/fixtures/installed-apparmor-20261004.json').read_text(encoding='utf-8'))


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


class SuppliedDenialTests(unittest.TestCase):
    def test_october_6_apt_can_read_private_archives_without_dac_write_override(self):
        policy = body('desktop-wrappers', 'labwc-wrap-desktop-files')
        self.assertIn('capability dac_read_search,', policy)
        self.assertNotRegex(policy, r'(?m)^\s*capability dac_override,')
        self.assertIn('/home/*/**.deb r,', policy)
        self.assertIn('/var/lib/labwc-desktop-files/{,**} rw,', policy)

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

    def test_compositor_env_helper_inherits_confinement_without_missing_transition(self):
        policy = body('labwc-session', 'labwc-compositor')
        self.assertIn('/usr/bin/env rix,', policy)
        self.assertIn('/usr/bin/* rPx,', policy)
        self.assertIn('/usr/local/{bin,sbin,libexec}/** rPx,', policy)
        self.assertNotRegex(policy, r'/usr/bin/env\s+[^,]*[pPcCuU]')
        self.assertNotRegex(policy, r'/usr/bin/\*\s+[^,]*[uU]')
        generic = body('desktop-wrappers', 'labwc-generic-app')
        self.assertIn('/usr/local/bin/labwc-{electron,wayland}-app rix,', generic)
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
            for name in ('desktop-wrappers', 'desktop-utilities', 'document-applications', 'usr.bin.qbittorrent'):
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
            name = label = None
            for line in '\n'.join(debug_output).splitlines():
                if line.startswith('Name:'):
                    name = line.split(':', 1)[1].strip()
                elif line.startswith('Local To:'):
                    parent = line.split(':', 1)[1].strip()
                    label = name if parent == '<NULL>' else parent + '//' + name
                    rules[label] = []
                elif line.startswith('Perms:'):
                    match = re.fullmatch(r'Perms:\s*([^:]*):([^ ]*)\s+priority=\d+\s+Name:\s*\((.*)\)', line)
                    self.assertIsNotNone(match, line)
                    owner, other, pattern = match.groups()
                    rules[label].append((expressions[normalize(pattern)], set(owner), set(other)))
            def permissions(label, filename, owned=True):
                result = set()
                for expression, owner, other in rules[label]:
                    if expression.fullmatch(filename):
                        result.update(owner if owned else other)
                return result
            for label in ('labwc-app//app-bwrap', 'desktop-editors', 'focuswriter', 'zathura', 'desktop-launcher'):
                for directory in ('Downloads', 'Documents', 'Pictures', 'Workspace', 'Syncthing'):
                    with self.subTest(label=label, directory=directory):
                        self.assertTrue(set('rwk') <= permissions(label, f'/home/fixture/{directory}/nested/document.pdf'))
                self.assertTrue(set('rwk') <= permissions(label, '/run/media/fixture/USB/nested/document.pdf'))
                self.assertTrue(set('rwk') <= permissions(
                    label, '/run/media/fixture/USB/nested/group-owned.pdf', owned=False))
                self.assertNotIn('w', permissions(
                    label, '/run/media/another-account/USB/document.pdf', owned=False))
            for location in ('run', 'var'):
                filename = f'/{location}/log/journal/machine/user-1000@rotated.journal~'
                self.assertIn('r', permissions('desktop-launcher', filename, owned=False))
                self.assertNotIn('w', permissions('desktop-launcher', filename, owned=False))
            execution = permissions('labwc-qbittorrent//qbittorrent-bwrap',
                                    '/usr/bin/qbittorrent', owned=False)
            # The compiler debug mask reports r/x/m, while the native rule
            # reader above independently reports the inherited execution mode.
            self.assertTrue(set('rx') <= execution, execution)
            # Replay all October 7 qBittorrent file denials in the compiler's
            # effective policy for both direct and Bubblewrap launches.
            for label in ('qbittorrent', 'labwc-qbittorrent//qbittorrent-bwrap'):
                with self.subTest(qbittorrent_profile=label):
                    self.assertEqual(permissions(label, '/sys/block/', owned=False), {'r'})
                    self.assertNotIn('r', permissions(label, '/sys/block/sda/size', owned=False))
                    for pid in ('2', '21822'):
                        for attribute in ('cmdline', 'stat'):
                            filename = f'/proc/{pid}/{attribute}'
                            self.assertEqual(permissions(label, filename), {'r'})
                            self.assertNotIn('r', permissions(label, filename, owned=False))
                        self.assertNotIn('r', permissions(label, f'/proc/{pid}/environ'))
                    self.assertTrue(set('rw') <= permissions(label, '/dev/pts/0'))
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
            for scratch in ('/var/lib/labwc-desktop-files/metadata-fixture',
                            '/var/lib/labwc-desktop-files/#1234'):
                self.assertTrue(set('rw') <= permissions('labwc-wrap-desktop-files', scratch))
            for outside in ('/tmp/tmpfixture', '/var/tmp/tmpfixture', '/home/fixture/private.txt'):
                self.assertNotIn('w', permissions('labwc-wrap-desktop-files', outside))

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
            'chatgpt-slirp4netns', 'labwc-app', 'labwc-app//app-bwrap',
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
