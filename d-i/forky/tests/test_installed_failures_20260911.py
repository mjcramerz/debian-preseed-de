"""Offline regressions for the supplied September 11 installed-system failures.

Audit coverage checks the scoped source rules and masks, not kernel enforcement.
No test starts host services, rewrites installed applications or loads policy.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file, source_stat as payload_source_stat
from payload_fixture import python_library
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

from collections import Counter
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
PACKAGE = python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')
sys.path.insert(0, str(PACKAGE))
from labwc_managed_app import runtime, session


def load_sync():
    path = TARGET / 'usr/local/bin/labwc-sync-application-launchers'
    module = types.ModuleType('installed_failure_sync')
    module.__file__ = str(path)
    exec(compile(payload_read_bytes(path), str(path), 'exec'), module.__dict__)
    return module


class AutostartPermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.parent = self.home / '.config/autostart'
        self.parent.mkdir(parents=True, mode=0o700)
        (self.home / '.config').chmod(0o700)
        self.file = self.parent / 'bitwarden.desktop'
        self.file.write_text('[Desktop Entry]\nType=Application\nName=Bitwarden\nExec=/opt/Bitwarden/bitwarden\n')
        self.file.chmod(0o660)
        self.sync = load_sync()
        self.uid, self.gid = os.geteuid(), os.getegid()

    def adopt(self):
        return self.sync.normalize_bitwarden_autostart_mode(
            str(self.home), str(self.file), self.file.lstat(), self.uid, self.gid)

    def test_private_owner_created_0660_is_adopted_as_0600(self):
        self.assertTrue(self.adopt())
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.file).st_mode), 0o600)
        self.assertFalse(self.adopt())

    def test_hardlink_is_not_adopted(self):
        os.link(self.file, self.parent / 'other')
        with self.assertRaises(RuntimeError):
            self.adopt()
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.file).st_mode), 0o660)

    def test_group_accessible_parent_is_not_adopted(self):
        self.parent.chmod(0o770)
        with self.assertRaises(RuntimeError):
            self.adopt()

    def test_wrong_owner_is_not_adopted(self):
        with self.assertRaises(RuntimeError):
            self.sync.normalize_bitwarden_autostart_mode(
                str(self.home), str(self.file), self.file.lstat(), self.uid + 1, self.gid)

    def test_replaced_inode_is_not_adopted(self):
        before = self.file.lstat()
        self.file.rename(self.parent / 'old')
        self.file.write_text('different')
        self.file.chmod(0o660)
        with self.assertRaises(RuntimeError):
            self.sync.normalize_bitwarden_autostart_mode(
                str(self.home), str(self.file), before, self.uid, self.gid)

    def test_symlink_is_rejected_before_synchronizing(self):
        self.file.rename(self.parent / 'original')
        self.file.symlink_to('original')
        with self.assertRaises(RuntimeError):
            self.sync.synchronize_bitwarden_autostart(str(self.home), self.uid, self.gid, None)

    def test_general_reader_still_rejects_writable_input(self):
        with self.assertRaises(RuntimeError):
            self.sync.read_regular_text(str(self.file), {self.uid})

    def test_world_writable_file_is_not_normalized(self):
        self.file.chmod(0o666)
        self.assertFalse(self.adopt())
        with self.assertRaises(RuntimeError):
            self.sync.read_regular_text(str(self.file), {self.uid})


class SessionOwnershipTests(unittest.TestCase):
    def launch(self, app='filen', owner=65534, marker='', args=None):
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {
                session.NATIVE_SESSION_UNIT_MARKER: marker, 'WAYLAND_DISPLAY': 'wayland-1'}, clear=True))
            stack.enter_context(mock.patch.object(session, 'system_owner', return_value=(owner, owner)))
            stack.enter_context(mock.patch.object(session, 'require_root_owned_executable', return_value='/usr/bin/systemd-run'))
            stack.enter_context(mock.patch.object(session, 'managed_session_unit_environment', return_value={'HOME': '/home/test'}))
            stack.enter_context(mock.patch.object(session, 'current_user_runtime_socket'))
            stack.enter_context(mock.patch.object(session, 'assert_launch_allowed'))
            stack.enter_context(mock.patch.object(session.Path, 'open', mock.mock_open(
                read_data='0::/user.slice/app.slice/labwc-native-' + app + '-' + 'a' * 32 + '.service\n')))
            call = stack.enter_context(mock.patch.object(session.os, 'execve'))
            session.redirect_native_from_private_users(app, 'intel', args or [])
            return call

    def test_private_namespace_handoff_preserves_arguments_and_output(self):
        call = self.launch(args=['--example', 'a b', '$HOME', ';false'])
        executable, argv, env = call.call_args.args
        self.assertEqual(executable, '/usr/bin/systemd-run')
        self.assertNotIn('--pipe', argv)
        self.assertIn('--property=StandardOutput=journal', argv)
        self.assertNotIn('--wait', argv)
        self.assertIn('--expand-environment=no', argv)
        self.assertEqual(argv[-4:], ['--example', 'a b', '$HOME', ';false'])
        self.assertIn('--property=Requisite=labwc-session.target', argv)

    def test_chatgpt_handoff_preserves_its_dedicated_profile_and_log_pipes(self):
        argv = self.launch(app='chatgpt', args=['a b', '$HOME']).call_args.args[1]
        command = argv[argv.index('--') + 1:]
        self.assertEqual(command, [session.CHATGPT_SESSION_PATH, 'intel', 'a b', '$HOME'])
        self.assertIn('--pipe', argv)
        self.assertIn('--wait', argv)
        policy = payload_read_text(TARGET / 'etc/apparmor.d/desktop-wrappers')
        block = policy.split('profile labwc-chatgpt-session ', 1)[1].split('\nprofile ', 1)[0]
        self.assertIn('/usr/local/bin/labwc-app rPx -> labwc-chatgpt,', block)
        stub = payload_read_text(TARGET / 'usr/local/libexec/labwc-chatgpt-session')
        self.assertIn('exec /usr/local/bin/labwc-app "$mode" chatgpt "$@"', stub)
        self.assertNotIn('log-runner', stub)
        self.assertNotIn('/dev/null', stub)
        self.assertIn('usr/local/libexec/labwc-chatgpt-session /usr/local/libexec/labwc-chatgpt-session 0755',
                      payload_read_text(FORKY / 'scripts/desktop/components.sh'))

    def test_host_namespace_also_isolates_normal_apps(self):
        call = self.launch(owner=0)
        call.assert_called_once()
        argv = call.call_args.args[1]
        self.assertIn('--property=ExitType=cgroup', argv)
        self.assertIn('--property=KillMode=control-group', argv)

    def test_native_marker_prevents_loop(self):
        self.launch(owner=0, marker='1').assert_not_called()
        with self.assertRaises(SystemExit):
            self.launch(owner=65534, marker='1')

    def test_invalid_marker_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.launch(marker='yes')

    def test_tuta_waits_for_secret_service_even_on_host(self):
        argv = self.launch(app='tutanota', owner=0).call_args.args[1]
        self.assertIn('--property=After=labwc-session.target labwc-kwallet-portal.service', argv)
        self.assertIn('--property=Requisite=labwc-session.target labwc-kwallet-portal.service', argv)

    def test_executable_owner_uses_anchor_without_loosening_modes(self):
        metadata = types.SimpleNamespace(st_uid=65534, st_mode=stat.S_IFREG | 0o755)
        with mock.patch.object(runtime.os, 'lstat', return_value=metadata), \
             mock.patch.object(runtime.os, 'access', return_value=True), \
             mock.patch.object(runtime, 'system_owner', return_value=(65534, 65534)):
            self.assertEqual(runtime.require_root_owned_executable('tool', '/usr/bin/tool'), '/usr/bin/tool')
            metadata.st_mode = stat.S_IFREG | 0o775
            with self.assertRaises(SystemExit):
                runtime.require_root_owned_executable('tool', '/usr/bin/tool')
            metadata.st_mode = stat.S_IFLNK | 0o777
            with self.assertRaises(SystemExit):
                runtime.require_root_owned_executable('tool', '/usr/bin/tool')
            metadata.st_mode = stat.S_IFREG | 0o755
            metadata.st_uid = 1000
            with self.assertRaises(SystemExit):
                runtime.require_root_owned_executable('tool', '/usr/bin/tool')


class InstallerFailureContractTests(unittest.TestCase):
    def test_busybox_public_parent_creation_keeps_private_parents(self):
        busybox = shutil.which('busybox')
        if not busybox:
            self.skipTest('BusyBox is unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'target'
            root.mkdir()
            private = root / 'private'
            private.mkdir(mode=0o700)
            script = r'''
set -eu
INSTALLER_TARGET_DIR=$1
. "$2"
installer_fatal() { echo "$*" >&2; exit 1; }
target_normalize_systemd_config_parent_modes() { :; }
install() { "$BUSYBOX" install "$@"; }
umask 077
ensure_target_asset_parent /usr/local/share/icons/test.png
ensure_target_asset_parent /private/subdir/data
[ "$(umask)" = 0077 ]
'''
            result = subprocess.run(payload_installed_argv([busybox, 'ash', '-c', script, 'test', str(root),
                                     str(FORKY / 'scripts/late/target-assets.sh')]),
                                    env={**os.environ, 'BUSYBOX': busybox}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            for relative in ('usr', 'usr/local', 'usr/local/share', 'usr/local/share/icons'):
                self.assertEqual(stat.S_IMODE(payload_source_stat(root / relative).st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(payload_source_stat(private).st_mode), 0o700)

    def test_global_portals_do_not_require_account_local_compositor(self):
        for name in ('xdg-desktop-portal', 'xdg-desktop-portal-gtk', 'xdg-desktop-portal-wlr', 'xdg-desktop-portal-lxqt'):
            text = payload_read_text(TARGET / f'etc/systemd/user/{name}.service.d/10-labwc-session.conf')
            self.assertNotIn('BindsTo=labwc-compositor.service', text)
            self.assertIn('ConditionEnvironment=LABWC_SESSION_OWNER=desktop', text)
            self.assertIn('PartOf=labwc-session.target', text)
        self.assertIn('GDK_DEBUG=no-portals', payload_read_text(TARGET / 'usr/local/bin/labwc-greeter-session.tmpl'))

    def test_greeter_bus_policy_blocks_portal_activation_without_affecting_desktop_user(self):
        template = payload_read_text(
            TARGET / 'etc/dbus-1/session.d/70-labwc-greeter-no-portals.conf.tmpl')
        self.assertEqual(template.count('__INSTALLER_LABWC_GREETER_USER__'), 1)
        root = ET.fromstring(template.replace('__INSTALLER_LABWC_GREETER_USER__', '_greetd'))
        self.assertEqual(root.tag, 'busconfig')
        self.assertEqual(len(root), 1)
        policy = root[0]
        self.assertEqual(policy.tag, 'policy')
        self.assertEqual(policy.attrib, {'user': '_greetd'})
        self.assertIn({'send_destination': 'org.freedesktop.portal.Desktop'},
                      [rule.attrib for rule in policy.findall('deny')])
        # Unowned names cannot satisfy send_destination. The path and interface
        # rules match the outgoing request before activation of the service.
        self.assertIn({'send_path': '/org/freedesktop/portal/desktop'},
                      [rule.attrib for rule in policy.findall('deny')])
        self.assertIn({'send_interface': 'org.freedesktop.portal.Settings'},
                      [rule.attrib for rule in policy.findall('deny')])
        staging = payload_read_text(FORKY / 'scripts/desktop/components/target-assets.sh')
        self.assertIn('/etc/dbus-1/session.d/70-labwc-greeter-no-portals.conf 0644', staging)
        validation = payload_read_text(FORKY / 'scripts/firstboot/04-validation.sh.tmpl')
        self.assertIn('desktop-greeter-portal-bus-policy', validation)
        self.assertIn('send_path=\\\"/org/freedesktop/portal/desktop\\\"', validation)

    def test_bitwarden_managed_policy_is_wired_without_transformer(self):
        software = payload_read_text(FORKY / 'scripts/late/software.sh')
        cli = payload_read_text(TARGET / 'usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/CLI.pm')
        bitwarden_path = TARGET / 'usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/Bitwarden.pm'
        self.assertTrue(payload_source_is_file(bitwarden_path))
        bitwarden = payload_read_text(bitwarden_path)
        self.assertNotIn('x-bitwarden-package', software)
        self.assertIn('APTRepoLocal/Servicing/Bitwarden.pm', software)
        self.assertIn('use APTRepoLocal::Servicing::Bitwarden;', cli)
        self.assertRegex(
            cli,
            r'return APTRepoLocal::Servicing::Bitwarden->new\(\)->policy_valid\(\)\s+'
            r"if \$app->\{name\} eq 'bitwarden';",
        )
        self.assertIn('sub policy_valid', bitwarden)
        self.assertNotIn('sub repack', bitwarden)
        self.assertNotIn("'transform'", bitwarden)
        for fragment in (
            'ELECTRON_OZONE_PLATFORM_HINT',
            '--password-store=gnome-libsecret',
            'UseOzonePlatform',
            'labwc-kwallet-portal.service',
            'org.freedesktop.secrets',
            '/etc/apparmor.d/opt.Bitwarden.bitwarden',
            'profile ksecretd',
        ):
            self.assertIn(fragment, bitwarden)
        self.assertRegex(software, r'software_install_deb\s+\\\n\s*"Bitwarden Desktop"\s+\\\n\s*"\$bitwarden_deb"')
        self.assertFalse(payload_source_exists(TARGET / 'usr/local/libexec/x-bitwarden-package'))
        self.assertNotIn('x-bitwarden-package',
                         payload_read_text(TARGET / 'etc/apparmor.d/desktop-wrappers'))
        self.assertIn('vendor_sha256', cli)
        self.assertIn('$vendor_installed &&', cli)
        repository = payload_read_text(TARGET / 'usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/Repository.pm')
        self.assertIn('next if !$self->bitwarden_vendor_digest_matches(', repository)
        engine = payload_read_text(TARGET / 'usr/local/libexec/apt-repo-local')
        self.assertIn('payload_path == path', engine)
        self.assertIn('.vendor-sha256', engine)
        self.assertIn('immutable pool object failed its digest check', engine)

    def test_misc_failure_contracts(self):
        templates = TARGET / 'data/config/podman/templates/devops'
        reboot = payload_read_text(templates / 'podman-devops-restart.service.tmpl')
        self.assertIn('stop --all --ignore --time 20', reboot)
        self.assertNotIn('stop --service', reboot)
        self.assertIn('podman --remote=false', payload_read_text(templates / 'podman-devops.service.tmpl'))
        self.assertIn('--skip-read-cache --write-cache', payload_read_text(TARGET / 'etc/systemd/system/mullvad-apparmor.service'))
        network = payload_read_text(FORKY / 'scripts/late/templates/network/inet6.tmpl')
        self.assertIn('keep_addr_on_down=1', network)
        components = payload_read_text(FORKY / 'scripts/desktop/components.sh')
        self.assertIn('find "$account_home/.config/systemd/user" -xdev -type f -exec chmod 0600 {} +', components)
        for app in ('labwc-tweaks', 'hyprpolkitagent'):
            text = payload_read_text(TARGET / f'usr/local/share/applications/{app}.desktop')
            self.assertIn(f'StartupWMClass={app}', text)


class RecordedAppArmorCoverageTests(unittest.TestCase):
    """A finite regression of observed masks against explicit scoped grants."""
    def test_fixture_exactly_matches_the_supplied_raw_audit_events(self):
        data = json.loads(payload_read_text(FORKY / 'tests/fixtures/installed-apparmor-20260911.json'))
        raw_path = FORKY.parents[1] / 'todo/managed/apparmor/apparmor.log'
        if not payload_source_is_file(raw_path):
            self.skipTest('original managed/apparmor/apparmor.log not supplied; parsed fixture checks remain enabled')
        raw_text = payload_read_text(raw_path)
        raw_lines = [
            line for line in raw_text.splitlines()
            if 'apparmor="ALLOWED"' in line
        ]
        fixture_fields = sorted(
            {key for row in data['records'] for key in row} - {'count'}
        )

        def field(line, name):
            match = re.search(
                rf'(?:^| ){re.escape(name)}=(?:"([^"]*)"|([^ ]+))',
                line,
            )
            if match is None:
                return None
            return match.group(1) if match.group(1) is not None else match.group(2)

        raw_records = Counter()
        for line in raw_lines:
            row = {}
            for name in fixture_fields:
                value = field(line, name)
                if value is None:
                    continue
                if name in {'name', 'target'}:
                    value = re.sub(r'\A/home/[^/]+/', '/home/ACCOUNT/', value)
                row[name] = value
            raw_records[tuple(sorted(row.items()))] += 1

        fixture_records = Counter()
        for row in data['records']:
            record = tuple(sorted(
                (key, str(value)) for key, value in row.items() if key != 'count'
            ))
            fixture_records[record] += row['count']

        self.assertEqual(len(raw_lines), data['events'])
        self.assertEqual(raw_records, fixture_records)
        self.assertNotIn('apparmor="DENIED"', raw_text)

    def test_all_592_records_have_scoped_grants(self):
        data = json.loads(payload_read_text(FORKY / 'tests/fixtures/installed-apparmor-20260911.json'))
        self.assertEqual(data['events'], 592)
        self.assertEqual(sum(row['count'] for row in data['records']), 592)
        policies = '\n'.join(payload_read_text(TARGET / f'etc/apparmor.d/{name}') for name in
                             ('labwc-session', 'desktop-utilities', 'desktop-wrappers'))
        for row in data['records']:
            with self.subTest(profile=row['profile'], operation=row['operation'], name=row.get('name')):
                # Preserve the supplied audit evidence; translate only its old profile identity.
                name = row['profile'].split('//')[0].removeprefix('x-')
                start = policies.index(f'profile {name} ')
                end = policies.find('\nprofile ', start + 1)
                block = policies[start:] if end < 0 else policies[start:end]
                if 'deleted entry' in row.get('info', ''):
                    self.assertIn('mediate_deleted', block.split('{\n', 1)[0])
                if row['class'] == 'cap':
                    self.assertIn(f"capability {row['capname']},", block)
                elif row['class'] == 'namespace':
                    self.assertIn('userns,', block)
                elif row['class'] == 'net':
                    self.assertEqual((row['family'], row['sock_type']), ('inet6', 'dgram'))
                    self.assertIn('network inet6 dgram,', block)
                elif row['class'] == 'signal':
                    self.assertIn(f"signal ({row['denied_mask']}) set=(kill term) peer={row['peer'].removeprefix('x-')},", block)
                else:
                    # Exec target is a complain-mode null profile, not a path.
                    for path in (row['name'], row.get('target') if row['operation'] == 'link' else None):
                        if path is not None:
                            rule, permissions = self.file_grant(name, path)
                            self.assertIn(rule, block)
                            mask = row['denied_mask'].replace('c', 'w').replace('d', 'w')
                            self.assertLessEqual(set(mask), set(permissions))
                            if rule.startswith('owner '):
                                self.assertEqual(row['fsuid'], row['ouid'])

    @staticmethod
    def file_grant(profile, path):
        if profile == 'session-glycin-bwrap':
            if path.startswith('/usr/share/backgrounds/'):
                return '/usr/share/backgrounds/** r,', 'r'
            if path.startswith('/usr/share/icons/'):
                return '/usr/{,local/}share/icons/** r,', 'r'
        if profile == 'crystal-dock' and path.startswith('/home/ACCOUNT/.config/crystal-dock/'):
            return 'owner @{HOME}/.config/crystal-dock/** rwkl,', 'rwkl'
        if profile == 'labwc-chatgpt' and re.fullmatch(r'/run/user/\d+/python/pycache/', path):
            return 'owner /run/user/[0-9]*/python/pycache/ rw,', 'rw'
        if profile == 'desktop-launcher' and path == '/run/mount/utab':
            return '/run/mount/utab r,', 'r'
        if profile == 'desktop-media':
            rules = (
                (r'/usr/lib/qt6/libexec/QtWebEngineProcess', '/usr/lib/qt6/libexec/QtWebEngineProcess rix,', 'rx'),
                (r'/proc/', '@{PROC}/ r,', 'r'),
                (r'/proc/sys/fs/inotify/max_user_watches', '@{PROC}/sys/fs/inotify/max_user_watches r,', 'r'),
                (r'/proc/sys/kernel/yama/ptrace_scope', '@{PROC}/sys/kernel/yama/ptrace_scope r,', 'r'),
                (r'/proc/\d+/(cmdline|stat|statm|fd/)', 'owner @{PROC}/[0-9]*/{cmdline,stat,statm,fd/} r,', 'r'),
                (r'/proc/\d+/task/', 'owner @{PROC}/[0-9]*/task/ r,', 'r'),
                (r'/proc/\d+/task/\d+/status', 'owner @{PROC}/[0-9]*/task/[0-9]*/status r,', 'r'),
                (r'/proc/\d+/(setgroups|gid_map|uid_map|oom_score_adj)', 'owner @{PROC}/[0-9]*/{setgroups,gid_map,uid_map,oom_score_adj} rw,', 'rw'),
                (r'/usr/share/qt6/resources/locales/', '/usr/share/qt6/resources/locales/ rw,', 'rw'),
                (r'/home/ACCOUNT/\.config/Recoll\.org/.+', 'owner @{HOME}/.config/Recoll.org/** rwkl,', 'rwkl'),
                (r'/home/ACCOUNT/\.cache/Recoll\.org/.+', 'owner @{HOME}/.cache/Recoll.org/** rwkl,', 'rwkl'),
                (r'/home/ACCOUNT/\.cache/qtshadercache-[^/]+/.+', 'owner @{HOME}/.cache/qtshadercache-*/** rwkl,', 'rwkl'),
                (r'/run/user/\d+/recoll-[^/]+-index.pid', 'owner /run/user/[0-9]*/recoll-*-index.pid rwk,', 'rwk'),
            )
            for regex, rule, permissions in rules:
                if re.fullmatch(regex, path):
                    return rule, permissions
        raise AssertionError(f'Uncovered record: {profile}: {path}')


if __name__ == '__main__':
    unittest.main()
