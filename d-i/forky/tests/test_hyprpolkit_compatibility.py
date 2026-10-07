"""Hyprpolkit compatibility, native-session lifetime and package selection.

No polkit agent, package installation or compositor is started. APT tests use
synthetic local indexes and simulated transactions in an isolated state tree.
"""
from __future__ import annotations

import contextlib
from email.utils import formatdate
import hashlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
HELPER = TARGET / 'usr/local/libexec/labwc-hyprpolkit-agent'
PIN = TARGET / 'etc/apt/preferences.d/default/hyprpolkitagent.pref'
UNIT = TARGET / 'etc/systemd/user/hyprpolkitagent.service.d'


def load_helper():
    loader = importlib.machinery.SourceFileLoader('hyprpolkit_fixture', str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def metadata(version='0.1.3-2', depends=None, state='installed'):
    depends = depends or 'libpolkit-qt6-1-1 (>= 0.200.0), libqt6quickcontrols2-6 (>= 6.6.0)'
    return f'{state}\n{version}\n{depends}\n'


class AgentGuardTests(unittest.TestCase):
    def setUp(self):
        self.m = load_helper()

    def test_debian_qt_revisions_are_accepted(self):
        for version in ('0.1.3-2', '0.1.3-2+b1', '0.1.3-3', '0.1.3-2+deb14u1'):
            with self.subTest(version=version):
                self.assertEqual(self.m.check_metadata(metadata(version)), version)

    def test_unreviewed_and_git_versions_are_rejected(self):
        for version in ('0.2.0-1', '0.1.3+git20260927-1', '0.1.4-1', '0.1.3',
                        '0.1.3-', '0.1.30-1', '1:0.1.3-2', '0.1.3-2\nextra'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.m.check_metadata(metadata(version))

    def test_half_configured_and_missing_metadata_are_rejected(self):
        for record in ('', 'installed\n0.1.3-2\n', metadata(state='unpacked'),
                       metadata(state='config-files'), metadata(state='half-configured')):
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.m.check_metadata(record)

    def test_same_version_with_toolkit_or_wrong_dependencies_is_rejected(self):
        for depends in ('libhyprtoolkit5, libpolkit-qt6-1-1, libqt6quickcontrols2-6',
                        'libaquamarine7, libpolkit-qt6-1-1, libqt6quickcontrols2-6',
                        'libpolkit-agent-1-0, libc6', 'libpolkit-qt6-1-1'):
            with self.subTest(depends=depends), self.assertRaises(ValueError):
                self.m.check_metadata(metadata(depends=depends))

    def valid_info(self, path):
        kind = stat.S_IFREG if path == self.m.BINARY else stat.S_IFDIR
        return SimpleNamespace(st_mode=kind | 0o755, st_uid=0)

    def test_binary_requires_exact_debian_ownership(self):
        for owner in ('hyprpolkitagent: /usr/libexec/hyprpolkitagent\n',
                      'hyprpolkitagent:amd64: /usr/libexec/hyprpolkitagent\n'):
            with mock.patch.object(Path, 'lstat', lambda path: self.valid_info(path)), \
                 mock.patch.object(self.m, 'package_query', return_value=owner):
                self.m.check_binary()
        for owner in ('other: /usr/libexec/hyprpolkitagent',
                      'local diversion from: /usr/libexec/hyprpolkitagent',
                      'hyprpolkitagent: /usr/libexec/hyprpolkitagent\nother: /usr/libexec/hyprpolkitagent'):
            with mock.patch.object(Path, 'lstat', lambda path: self.valid_info(path)), \
                 mock.patch.object(self.m, 'package_query', return_value=owner), self.assertRaises(ValueError):
                self.m.check_binary()

    def test_binary_and_parents_cannot_be_symlinked_writable_or_unowned(self):
        for bad_path in (*self.m.BINARY.parents, self.m.BINARY):
            for bad in (SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0),
                        SimpleNamespace(st_mode=stat.S_IFREG | 0o777, st_uid=0),
                        SimpleNamespace(st_mode=stat.S_IFDIR | 0o775, st_uid=0),
                        SimpleNamespace(st_mode=stat.S_IFREG | 0o4755, st_uid=0),
                        SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=1000)):
                def info(path):
                    return bad if path == bad_path else self.valid_info(path)
                with self.subTest(path=bad_path, info=bad), mock.patch.object(Path, 'lstat', info), \
                     mock.patch.object(self.m, 'package_query') as query, self.assertRaises(ValueError):
                    self.m.check_binary()
                query.assert_not_called()

    def test_package_query_is_read_only_absolute_and_bounded(self):
        with mock.patch.object(self.m.subprocess, 'run', return_value=SimpleNamespace(stdout='record')) as run:
            self.assertEqual(self.m.package_query('-W', 'hyprpolkitagent'), 'record')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/dpkg-query', '-W', 'hyprpolkitagent'])
        self.assertEqual(run.call_args.kwargs['timeout'], 5)
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_read_only_check_does_not_require_or_start_a_session(self):
        with mock.patch.object(self.m, 'check', return_value='0.1.3-2'), \
             mock.patch.object(self.m.os, 'execve') as execute, \
             mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.main(['--check']), 0)
        execute.assert_not_called()

    def test_exec_replaces_guard_with_same_agent_and_native_software_environment(self):
        env = {'LABWC_SESSION_OWNER': 'desktop', 'XDG_SESSION_TYPE': 'wayland',
               'WAYLAND_DISPLAY': 'wayland-1', 'XDG_RUNTIME_DIR': '/run/user/1000',
               'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus',
               'DISPLAY': ':0', 'XAUTHORITY': '/tmp/should-not-be-used',
               'QT_QPA_PLATFORM': 'xcb', 'QT_QUICK_BACKEND': 'rhi',
               'QSG_RHI_BACKEND': 'vulkan', 'QMLSCENE_DEVICE': 'openvg'}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(self.m, 'check', return_value='0.1.3-2'), \
             mock.patch.object(self.m.os, 'execve', side_effect=SystemExit(0)) as execute, \
             self.assertRaises(SystemExit):
            self.m.main(['--exec'])
        binary, argv, launched = execute.call_args.args
        self.assertEqual(binary, '/usr/libexec/hyprpolkitagent')
        self.assertEqual(argv, [binary])
        self.assertEqual(launched['QT_QPA_PLATFORM'], 'wayland')
        self.assertEqual(launched['QT_QUICK_BACKEND'], 'software')
        self.assertEqual(launched['DBUS_SESSION_BUS_ADDRESS'], env['DBUS_SESSION_BUS_ADDRESS'])
        self.assertEqual(launched['XDG_RUNTIME_DIR'], env['XDG_RUNTIME_DIR'])
        for key in ('DISPLAY', 'XAUTHORITY', 'QSG_RHI_BACKEND', 'QMLSCENE_DEVICE'):
            self.assertNotIn(key, launched)
        self.assertEqual(env['QT_QUICK_BACKEND'], 'rhi')  # never mutate caller data

    def test_non_desktop_or_non_wayland_launch_is_rejected(self):
        for env in ({}, {'LABWC_SESSION_OWNER': 'greeter'},
                    {'LABWC_SESSION_OWNER': 'desktop', 'XDG_SESSION_TYPE': 'x11'},
                    {'LABWC_SESSION_OWNER': 'desktop', 'XDG_SESSION_TYPE': 'wayland'}):
            with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                self.m.launch_environment()

    def test_invalid_package_timeout_and_usage_do_not_start_or_loop(self):
        for failure in (ValueError('incompatible toolkit'), OSError('missing package'),
                        subprocess.TimeoutExpired('dpkg-query', 5)):
            with mock.patch.object(self.m, 'check', side_effect=failure), \
                 mock.patch.object(self.m.os, 'execve') as execute, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.m.main(['--exec']), 78)
            execute.assert_not_called()
        with mock.patch.object(self.m, 'check') as check, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.m.main(['--exec', '--other-agent']), 78)
            self.assertEqual(self.m.main([]), 78)
        check.assert_not_called()


class AgentWiringTests(unittest.TestCase):
    def test_hyprpolkit_remains_the_only_selected_agent(self):
        desktop = (SEED / 'classes/class-select/role/desktop.cfg').read_text()
        packages = desktop.split()
        self.assertIn('hyprpolkitagent', packages)
        self.assertNotIn('hyprpolkitagent/forky', packages)
        self.assertNotIn('mate-polkit', packages)
        self.assertIn('qt6-wayland', packages)
        self.assertIn('d-i apt-setup/local28/repository string https://deb.debian.org/debian trixie-backports main\n', desktop)
        self.assertIn('d-i apt-setup/local28/key string https://ftp-master.debian.org/keys/archive-key-13.asc\n', desktop)
        self.assertIn('d-i apt-setup/local28/source boolean false\n', desktop)
        self.assertNotIn('trixie-backports', (SEED / 'fragments/apt.cfg').read_text())
        for base in (TARGET / 'etc/systemd/user', TARGET / 'etc/skel-desktop/.config/systemd/user',
                     TARGET / 'usr/local/share/applications'):
            self.assertFalse(list(base.glob('*labwc-polkit-agent*')))
        for rel in ('scripts/desktop/components/services.sh', 'scripts/desktop/components/user-session.sh',
                    'scripts/desktop/components/desktop-helpers.sh', 'scripts/desktop/verify.sh.tmpl',
                    'scripts/firstboot/04-validation.sh.tmpl', 'hooks/target/usr/local/bin/labwc-autostart'):
            text = (SEED / rel).read_text()
            self.assertIn('hyprpolkitagent.service', text, rel)
            self.assertNotIn('labwc-polkit-agent.service', text, rel)
        self.assertNotIn('desktop_mask_unit_if_available hyprpolkitagent.service',
                         (SEED / 'scripts/desktop/components/services.sh').read_text())

    def test_compatibility_pin_is_staged_before_pkgsel_by_existing_class_contract(self):
        text = (SEED / 'classes/configs/system.cfg').read_text().split('\n\n', 1)[0]
        self.assertIn('Group: role\nName: desktop\n', text)
        self.assertIn('DebianAptPreferences: hyprpolkitagent', text)
        self.assertIn('Pin: version 0.1.3-*', PIN.read_text())
        self.assertIn('Pin: release a=experimental,n=rc-buggy\nPin-Priority: -1', PIN.read_text())
        self.assertIn('Pin: release n=sid\nPin-Priority: -1', PIN.read_text())
        self.assertNotIn('Package: *\n', PIN.read_text())
        self.assertNotIn('trusted=yes', PIN.read_text())

    def test_agent_has_bounded_lifecycle_no_x11_and_no_authentication_bypass(self):
        session = (UNIT / '10-labwc-session.conf').read_text()
        for line in ('Requisite=labwc-session.target', 'PartOf=labwc-session.target',
                     'ConditionEnvironment=LABWC_SESSION_OWNER=desktop',
                     'ConditionEnvironment=XDG_SESSION_TYPE=wayland', 'ConditionEnvironment=WAYLAND_DISPLAY',
                     'ExecCondition=/usr/local/libexec/labwc-session-check session-ready',
                     'ExecStart=\nExecStart=/usr/local/libexec/labwc-hyprpolkit-agent --exec',
                     'RestartPreventExitStatus=78', 'KillMode=control-group', 'UMask=0077',
                     'StartLimitIntervalSec=30s', 'StartLimitBurst=5',
                     'Environment=QT_QPA_PLATFORM=wayland', 'Environment=QT_QUICK_BACKEND=software',
                     'UnsetEnvironment=DISPLAY XAUTHORITY QSG_RHI_BACKEND QMLSCENE_DEVICE'):
            self.assertIn(line, session)
        self.assertNotIn('NoNewPrivileges=yes', session)  # polkit PAM uses a privileged helper
        self.assertNotIn('PrivateUsers=yes', session)
        self.assertIn('LimitCORE=0', (UNIT / '70-no-core.conf').read_text())
        self.assertIn('Slice=session.slice', (UNIT / '60-resource-class.conf').read_text())
        self.assertFalse((TARGET / 'etc/skel-desktop/.config/systemd/user/hyprpolkitagent.service').exists())

    @unittest.skipUnless(os.geteuid() == 0 and Path('/usr/lib/systemd/systemd').is_file(),
                         'offline user-manager fixture needs systemd and UID isolation')
    def test_merged_vendor_unit_keeps_guard_native_environment_and_resource_policy(self):
        # --test builds/dumps a transaction; it never runs these fixture units.
        with tempfile.TemporaryDirectory(prefix='hyprpolkit-unit-') as temporary:
            root = Path(temporary)
            root.chmod(0o755)
            units = root / 'units'
            units.mkdir(mode=0o755)
            vendor = ('[Unit]\nDescription=Hyprpolkit vendor unit fixture\n'
                      'PartOf=graphical-session.target\nAfter=graphical-session.target\n'
                      'ConditionEnvironment=WAYLAND_DISPLAY\n[Service]\n'
                      'ExecStart=/usr/libexec/hyprpolkitagent\nSlice=session.slice\n'
                      'TimeoutStopSec=5sec\nRestart=on-failure\n[Install]\n'
                      'WantedBy=graphical-session.target\n')
            (units / 'hyprpolkitagent.service').write_text(vendor)
            dropins = units / 'hyprpolkitagent.service.d'
            dropins.mkdir()
            for source in UNIT.glob('*.conf'):
                shutil.copyfile(source, dropins / source.name)
            (units / 'hyprpolkit-test.target').write_text(
                '[Unit]\nDescription=Offline fixture\n'
                'Wants=hyprpolkitagent.service labwc-session.target labwc-compositor.service\n')
            (units / 'labwc-session.target').write_text(
                '[Unit]\nDescription=Offline session boundary\nDefaultDependencies=no\n')
            (units / 'labwc-compositor.service').write_text('[Service]\nExecStart=/usr/bin/true\n')
            for name in ('home', 'run', 'config', 'data'):
                directory = root / name
                directory.mkdir(mode=0o700)
                os.chown(directory, 65534, 65534)
            env = dict(os.environ, HOME=str(root / 'home'), XDG_RUNTIME_DIR=str(root / 'run'),
                       XDG_CONFIG_HOME=str(root / 'config'), XDG_DATA_HOME=str(root / 'data'),
                       SYSTEMD_UNIT_PATH=str(units) + ':', SYSTEMD_LOG_LEVEL='warning',
                       SYSTEMD_LOG_TARGET='console', LABWC_SESSION_OWNER='desktop',
                       WAYLAND_DISPLAY='wayland-fixture', XDG_SESSION_TYPE='wayland')
            def unprivileged():
                os.setgroups([])
                os.setgid(65534)
                os.setuid(65534)
            result = subprocess.run(['/usr/lib/systemd/systemd', '--user', '--test',
                                     '--unit=hyprpolkit-test.target'], env=env,
                                    preexec_fn=unprivileged, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotRegex(result.stderr, r'Unknown (key|section)|Failed to parse|Invalid argument')
            match = re.search(r'\n\s*\u2192 Unit hyprpolkitagent\.service:\n(.*?)(?=\n\s*\u2192 Unit |\Z)',
                              result.stdout, re.S)
            self.assertIsNotNone(match, result.stdout)
            body = match.group(1)
            for expected in ('Unit Active State: inactive', 'Slice: session.slice',
                             'Requisite: labwc-session.target', 'PartOf: labwc-session.target',
                             'Restart: on-failure', 'KillMode: control-group', 'UMask: 0077',
                             'Environment: QT_QPA_PLATFORM=wayland',
                             'Environment: QT_QUICK_BACKEND=software',
                             'UnsetEnvironment: DISPLAY', 'UnsetEnvironment: XAUTHORITY',
                             'LimitCORE: 0', 'LimitCORESoft: 0',
                             'Command Line: /usr/local/libexec/labwc-hyprpolkit-agent --exec'):
                self.assertIn(expected, body)
            self.assertNotIn('Command Line: /usr/libexec/hyprpolkitagent', body)

    def test_package_guard_is_required_at_install_and_firstboot(self):
        assets = (SEED / 'scripts/desktop/components/target-assets.sh').read_text()
        self.assertIn('desktop_stage_role_asset usr/local/libexec/labwc-hyprpolkit-agent /usr/local/libexec/labwc-hyprpolkit-agent 0755', assets)
        self.assertIn('run_in_target "verify packaged Hyprpolkit Labwc compatibility" /usr/local/libexec/labwc-hyprpolkit-agent --check', assets)
        self.assertIn('check_command desktop-hyprpolkit-compatibility /usr/local/libexec/labwc-hyprpolkit-agent --check',
                      (SEED / 'scripts/firstboot/04-validation.sh.tmpl').read_text())
        policy = (SEED / 'scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl').read_text()
        self.assertIn('/usr/local/libexec/labwc-hyprpolkit-agent rix,', policy)
        self.assertIn('/usr/libexec/hyprpolkitagent r,', policy)
        self.assertNotIn('/usr/libexec/hyprpolkitagent rix,', policy)


@unittest.skipUnless(shutil.which('apt-get') and shutil.which('apt-cache'), 'APT tools unavailable')
class AgentAptPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hyprpolkit-apt-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        sources = []
        for name, origin, versions in (
                ('forky', 'Debian', ('0.2.0-1', '0.1.3+git20260927-1')),
                ('trixie-backports', 'Debian', ('0.1.3-2~bpo13+1',)),
                ('sid', 'Debian', ('0.1.3-99',)),
                ('experimental', 'Debian', ('0.1.3-100',)),
                ('obs', 'obs://build.opensuse.org/home:cramerz:debian/Debian_Unstable', ('0.1.3-200',))):
            repo = self.root / name
            repo.mkdir()
            records = []
            for arch in ('amd64', 'i386'):
                for version in versions:
                    records.append(self.record('hyprpolkitagent', version, arch))
                if name == 'forky':
                    records.append(self.record('unrelated-package', '10.0-1', arch))
                if name == 'trixie-backports':
                    records.append(self.record('unrelated-package', '11.0-1', arch))
            package_index = '\n'.join(records).encode()
            (repo / 'Packages').write_bytes(package_index)
            codename = {'obs': 'Debian_Unstable', 'experimental': 'rc-buggy'}.get(name, name)
            suite = 'experimental' if name == 'experimental' else codename
            label = 'home:cramerz:debian' if name == 'obs' else 'Debian'
            backports_policy = 'NotAutomatic: yes\nButAutomaticUpgrades: yes\n' if name == 'trixie-backports' else ''
            (repo / 'Release').write_text(f'Origin: {origin}\nLabel: {label}\nSuite: {suite}\n'
                                          f'Codename: {codename}\nArchitectures: amd64 i386\n'
                                          f'Date: {formatdate(usegmt=True)}\n{backports_policy}'
                                          f'SHA256:\n {hashlib.sha256(package_index).hexdigest()} '
                                          f'{len(package_index)} Packages\n')
            # Trust bypass is confined to inert local TEST indexes, never payload policy.
            sources.append(f'deb [trusted=yes] file:{repo} ./')
        (self.root / 'sources.list').write_text('\n'.join(sources) + '\n')
        (self.root / 'empty-etc').mkdir()
        (self.root / 'apt.conf').write_text(
            f'Dir::Etc::parts "{self.root / "empty-etc"}";\n'
            f'Dir::Etc::main "{self.root / "empty.conf"}";\n')
        (self.root / 'status').touch()
        for directory in ('lists/partial', 'archives/partial', 'log', 'trusted'):
            (self.root / directory).mkdir(parents=True)
        settings = {
            'Dir::Etc::main': '-', 'Dir::Etc::parts': '-',
            'Dir::Etc::sourcelist': str(self.root / 'sources.list'), 'Dir::Etc::sourceparts': '-',
            'Dir::Etc::trusted': str(self.root / 'absent.gpg'), 'Dir::Etc::trustedparts': str(self.root / 'trusted'),
            'Dir::Etc::preferences': str(PIN), 'Dir::Etc::preferencesparts': '-',
            'Dir::State::status': str(self.root / 'status'), 'Dir::State::lists': str(self.root / 'lists'),
            'Dir::State::extended_states': str(self.root / 'extended_states'),
            'Dir::Cache::archives': str(self.root / 'archives'), 'Dir::Cache::pkgcache': '', 'Dir::Cache::srcpkgcache': '',
            'Dir::Log': str(self.root / 'log'), 'APT::Architecture': 'amd64', 'APT::Default-Release': '',
            'APT::Sandbox::User': pwd.getpwuid(os.getuid()).pw_name,
            'Debug::NoLocking': 'true', 'Acquire::Languages': 'none',
        }
        self.options = [arg for key, value in settings.items() for arg in ('-o', f'{key}={value}')]
        self.options += ['-o', 'APT::Architectures::=amd64', '-o', 'APT::Architectures::=i386']
        result = self.apt('apt-get', 'update')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @staticmethod
    def record(name, version, arch):
        return (f'Package: {name}\nVersion: {version}\nArchitecture: {arch}\n'
                f'Filename: pool/{name}_{version}_{arch}.deb\nSize: 1\nSHA256: ' + 'a' * 64 +
                '\nDescription: Inert offline policy fixture\n')

    def replace_index(self, name, content):
        repo = self.root / name
        index = content.encode()
        (repo / 'Packages').write_bytes(index)
        release = repo / 'Release'
        header = release.read_text().split('SHA256:\n', 1)[0]
        release.write_text(f'{header}SHA256:\n {hashlib.sha256(index).hexdigest()} '
                           f'{len(index)} Packages\n')

    def apt(self, tool, *args):
        return subprocess.run([tool, *self.options, *args], capture_output=True, text=True,
                              env={**os.environ, 'LC_ALL': 'C', 'APT_CONFIG': str(self.root / 'apt.conf'),
                                   'TMPDIR': str(self.root)}, timeout=20)

    def test_reviewed_qt_series_wins_on_both_architectures(self):
        for arch in ('amd64', 'i386'):
            result = self.apt('apt-cache', 'policy', f'hyprpolkitagent:{arch}')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Candidate: 0.1.3-2~bpo13+1', result.stdout)
            self.assertRegex(result.stdout, r'0\.2\.0-1\s+-1\b')
            self.assertRegex(result.stdout, r'0\.1\.3\+git20260927-1\s+-1\b')
            self.assertRegex(result.stdout, r'0\.1\.3-99\s+-1\b')
            self.assertRegex(result.stdout, r'0\.1\.3-100\s+-1\b')
            self.assertRegex(result.stdout, r'0\.1\.3-200\s+-1\b')

    def test_pkgsel_plain_package_request_respects_compatibility_pin(self):
        result = self.apt('apt-get', '--simulate', 'install', 'hyprpolkitagent')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Inst hyprpolkitagent (0.1.3-2~bpo13+1 ', result.stdout)
        self.assertNotIn('Inst hyprpolkitagent (0.2.', result.stdout)

    def test_compatible_forky_revision_takes_precedence_when_available(self):
        packages = self.root / 'forky/Packages'
        self.replace_index('forky', packages.read_text() + self.record('hyprpolkitagent', '0.1.3-3', 'amd64') + '\n')
        shutil.rmtree(self.root / 'lists')
        (self.root / 'lists/partial').mkdir(parents=True)
        self.assertEqual(self.apt('apt-get', 'update').returncode, 0)
        result = self.apt('apt-get', '--simulate', 'install', 'hyprpolkitagent')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Inst hyprpolkitagent (0.1.3-3 ', result.stdout)

    def test_package_pin_does_not_change_unrelated_packages(self):
        result = self.apt('apt-cache', 'policy', 'unrelated-package')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Candidate: 10.0-1', result.stdout)
        self.assertRegex(result.stdout, r'10\.0-1\s+500\b')
        self.assertRegex(result.stdout, r'11\.0-1\s+100\b')

    def test_missing_compatible_series_does_not_fallback_to_toolkit(self):
        self.replace_index('trixie-backports', self.record('hyprpolkitagent', '0.2.0-1', 'amd64'))
        # This intentionally tiny unsigned fixture has no Release checksum:
        # discard ONLY its private indexes so APT cannot retain the prior list.
        shutil.rmtree(self.root / 'lists')
        (self.root / 'lists/partial').mkdir(parents=True)
        self.assertEqual(self.apt('apt-get', 'update').returncode, 0)
        result = self.apt('apt-get', '--simulate', 'install', 'hyprpolkitagent')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
