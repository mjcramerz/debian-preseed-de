"""Current source, launcher and session boundaries; no target services are started."""
from __future__ import annotations
from payload_fixture import read_text as module_text

import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import tempfile
import types
import unittest
from unittest import mock

SEED = Path(__file__).resolve().parents[1]
ROOT = SEED.parents[1]
TARGET = SEED / 'hooks/target'
CUSTOM_APPS = ('chatgpt', 'computer-management', 'discord', 'ledger-live',
               'postman', 'remote-desktop-management', 'show-desktop', 'sleek')


def load(relative):
    path = TARGET / relative
    module = types.ModuleType('cleanup_under_test')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class SourceContracts(unittest.TestCase):
    def test_validation_reports_are_nested_and_no_wildcard_dropin_directories(self):
        self.assertEqual({p.name for p in ROOT.glob('*.md')}, {'README.md', 'SECURITY.md'})
        self.assertTrue((ROOT / 'docs/security-hardening.md').is_file())
        self.assertTrue((ROOT / 'docs/validation').is_dir())
        self.assertFalse(any(ROOT.glob('validation*')))
        self.assertFalse(any('*' in p.name for p in (TARGET / 'etc/systemd/user').iterdir()))

    def test_installer_layout_catalogs_have_one_canonical_name(self):
        for family in ('btrfs', 'f2fs'):
            self.assertTrue((SEED / f'hosts/installer/{family}.env').is_file())
            self.assertFalse((SEED / f'hosts/installer/layout-{family}.env').exists())
        source = module_text(SEED / 'scripts/common/lib.sh')
        self.assertIn('"${host_layout_family}.env"', source)
        self.assertNotIn('"layout-${host_layout_family}.env"', source)

    def test_dynamic_devops_templates_are_target_assets(self):
        self.assertFalse((SEED / 'scripts/late/templates/devops').exists())
        code = module_text(SEED / 'scripts/late/devops.sh.tmpl').replace('\\\n', ' ')
        for name in ('aptly.conf.tmpl', 'oscrc.tmpl', 'oscrc.json.tmpl'):
            self.assertTrue((TARGET / 'usr/local/share/devops/templates' / name).is_file())
            self.assertRegex(code, r'DIR_HOOKS_TARGET\s+usr/local/share/devops/templates/' + re.escape(name))

    def test_custom_launchers_are_local_overrides_not_package_payloads(self):
        for name in CUSTOM_APPS:
            with self.subTest(app=name):
                self.assertTrue((TARGET / f'usr/local/share/applications/{name}.desktop.tmpl').is_file())
                self.assertFalse((TARGET / f'usr/share/applications/{name}.desktop.tmpl').exists())
        for module, app in (('Discord', 'discord'), ('Postman', 'postman'), ('Ledger', 'ledger-live')):
            source = (TARGET / f'usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/{module}.pm').read_text()
            self.assertIn(f'/usr/local/share/applications/{app}.desktop', source)
            self.assertNotIn(f'/usr/share/applications/{app}.desktop', source)
            self.assertIn("system('/usr/bin/update-desktop-database', '/usr/local/share/applications');", source)
            self.assertNotIn("system('/usr/bin/update-desktop-database', '/usr/share/applications');", source)
        # Sleek's vendor package still owns its upstream launcher, not our override.
        sleek = (TARGET / 'usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/Sleek.pm').read_text()
        self.assertIn('/usr/share/applications/sleek.desktop', sleek)
        source = (TARGET / 'usr/local/libexec/apt-repo-local').read_text()
        block = source.split('            desktop_paths = ', 1)[1].split('            for filename', 1)[0]
        self.assertNotIn('.desktop', block)
        self.assertNotIn('/usr/local/', block)

    def test_only_family_tuning_dropins_are_present(self):
        unit_root = TARGET / 'etc/systemd/user'
        for family in ('native', 'wayland', 'electron', 'devops'):
            self.assertEqual([p.name for p in unit_root.glob(f'labwc-{family}-*.service.d')],
                             [f'labwc-{family}-.service.d'])
        packages = '\n'.join(p.read_text() for p in (SEED / 'classes').rglob('*.cfg'))
        self.assertNotRegex(packages, r'\b(?:firefox(?:-esr)?|blender|kdenlive)\b')
        generator = (SEED / 'hooks/installer/apt-setup/generators/99-apt-preferences').read_text()
        self.assertIn('fetch_and_install_pref 00-excluded-desktop-apps.pref\nstage_configured_preferences', generator)


class LifecycleContracts(unittest.TestCase):
    def test_owned_clients_cannot_pull_in_the_desktop(self):
        checked = 0
        for root in (TARGET / 'etc/systemd/user', TARGET / 'etc/skel-desktop/.config/systemd/user'):
            for path in root.rglob('*'):
                if not path.is_file() or path.name == 'labwc-compositor.service':
                    continue
                text = path.read_text()
                if not re.search(r'^PartOf=.*\blabwc-session\.target\b', text, re.M):
                    continue
                with self.subTest(path=str(path.relative_to(TARGET))):
                    self.assertRegex(text, r'(?m)^Requisite=.*\blabwc-session\.target\b')
                    self.assertRegex(text, r'(?m)^After=.*\blabwc-session\.target\b')
                    self.assertNotRegex(text, r'(?m)^(?:BindsTo|Requires|Wants)=.*\blabwc-(?:session\.target|compositor\.service)\b')
                    self.assertNotIn('ExecCondition=/bin/sh -eu -c ', text)
                    checked += 1
        self.assertGreater(checked, 45)
        target = (TARGET / 'etc/skel-desktop/.config/systemd/user/labwc-session.target').read_text()
        self.assertIn('BindsTo=labwc-compositor.service', target)
        self.assertIn('DefaultDependencies=no', target)


    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd-analyze required')
    def test_late_session_sockets_do_not_order_before_basic_target(self):
        # Real source Unit sections, with disposable executable/vendor fixtures.
        # Verify only: neither socket nor service is activated by this command.
        for name in ('foot-server', 'ssh-agent'):
            with self.subTest(socket=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = TARGET / f'etc/systemd/user/{name}.socket.d/10-labwc-session.conf'
                dropin = root / source.parent.name / source.name
                dropin.parent.mkdir()
                text = source.read_text()
                for directive in ('DefaultDependencies=no', 'Before=shutdown.target', 'Conflicts=shutdown.target'):
                    self.assertIn(directive, text)
                dropin.write_text(text)
                for service in ('dbus', name):
                    (root / f'{service}.service').write_text(
                        '[Unit]\nDescription=Offline vendor fixture\n'
                        '[Service]\nExecStart=/usr/bin/true\n')
                for socket_name in ('dbus', name):
                    (root / f'{socket_name}.socket').write_text(
                        '[Unit]\nDescription=Offline vendor socket fixture\n'
                        f'[Socket]\nListenStream=%t/{socket_name}.socket\n')
                source_root = TARGET / 'etc/skel-desktop/.config/systemd/user'
                (root / 'labwc-session.target').write_text((source_root / 'labwc-session.target').read_text())
                compositor = (source_root / 'labwc-compositor.service').read_text()
                # One Type=exec command; retain the complete real Unit section.
                unit = compositor.split('[Service]', 1)[0]
                (root / 'labwc-compositor.service').write_text(
                    unit + '[Service]\nType=exec\nExecStart=/usr/bin/true\n')
                wants = root / 'labwc-session.target.wants'; wants.mkdir()
                (wants / f'{name}.socket').symlink_to(f'../{name}.socket')
                environment = dict(os.environ, SYSTEMD_UNIT_PATH=f'{root}:/usr/lib/systemd/user',
                                   XDG_RUNTIME_DIR=str(root), SYSTEMD_LOG_LEVEL='warning')
                command = ['systemd-analyze', '--user', '--generators=no', '--man=no',
                           'verify', str(root / 'labwc-session.target'), str(root / f'{name}.socket')]
                valid = subprocess.run(command, env=environment, text=True, capture_output=True, timeout=15)
                self.assertEqual(valid.returncode, 0, valid.stderr)
                self.assertNotIn('ordering cycle', valid.stderr)
                # Negative control: former ordering is cyclic, even when the
                # manager can break the cycle by discarding a weak startup job.
                dropin.write_text(text.replace('DefaultDependencies=no\n', '', 1))
                broken = subprocess.run(command, env=environment, text=True, capture_output=True, timeout=15)
                self.assertIn('ordering cycle', broken.stderr)


class LocalLauncherPrecedence(unittest.TestCase):
    def setUp(self):
        self.module = load('usr/local/bin/labwc-sync-application-launchers.tmpl')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.local = self.root / 'local'; self.local.mkdir()
        self.vendor = self.root / 'vendor'; self.vendor.mkdir()
        self.module.LOCAL_APPLICATION_DIR = str(self.local)
        self.module.SYSTEM_APPLICATION_DIR = str(self.vendor)

    def test_directory_precedence_wins_over_vendor_alias_order(self):
        (self.local / 'alternate.desktop').write_text('[Desktop Entry]\nName=Local\n')
        (self.vendor / 'primary.desktop').write_text('[Desktop Entry]\nName=Vendor\n')
        self.assertEqual(self.module.find_desktop_file(('primary.desktop', 'alternate.desktop')),
                         ('alternate.desktop', str(self.local / 'alternate.desktop')))

    def test_absent_local_file_uses_vendor(self):
        (self.vendor / 'app.desktop').write_text('[Desktop Entry]\nName=Vendor\n')
        self.assertEqual(self.module.find_desktop_file(('app.desktop',)),
                         ('app.desktop', str(self.vendor / 'app.desktop')))

    def test_broken_local_symlink_does_not_fall_back(self):
        (self.local / 'app.desktop').symlink_to(self.root / 'missing')
        (self.vendor / 'app.desktop').write_text('[Desktop Entry]\nName=Vendor\n')
        _, path = self.module.find_desktop_file(('app.desktop',))
        self.assertEqual(path, str(self.local / 'app.desktop'))
        with self.assertRaises(OSError):
            self.module.read_system_desktop_text(path)

    def test_local_metadata_error_is_not_silently_ignored(self):
        with mock.patch.object(self.module.os, 'lstat', side_effect=PermissionError), self.assertRaises(PermissionError):
            self.module.find_desktop_file(('app.desktop',))


class SessionReadiness(unittest.TestCase):
    def setUp(self):
        self.module = load('usr/local/libexec/labwc-session-check')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.canonical = f'/run/user/{os.getuid()}'
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        try:
            self.socket.bind(str(self.root / 'wayland-1'))
        except OSError as exc:
            self.skipTest(f'filesystem UNIX sockets unavailable: {exc}')
        self.environment = mock.patch.dict(os.environ, XDG_RUNTIME_DIR=self.canonical, WAYLAND_DISPLAY='wayland-1')
        self.environment.start(); self.addCleanup(self.environment.stop)
        patch = mock.patch.object(self.module, 'Path', side_effect=lambda path: self.root if path == self.canonical else Path(path))
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(self.module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0))
        self.run = patch.start(); self.addCleanup(patch.stop)

    def test_live_owned_socket_requires_active_target_with_bounded_check(self):
        self.assertEqual(self.module.main(['session-ready']), 0)
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0], ['/usr/bin/systemctl', '--user', '--quiet', 'is-active', 'labwc-session.target'])
        self.assertEqual(self.run.call_args.kwargs['timeout'], 3)

    def test_closed_target_is_not_ready(self):
        self.run.return_value = subprocess.CompletedProcess([], 3)
        self.assertEqual(self.module.main(['session-ready']), 1)

    def test_any_closing_marker_including_broken_symlink_blocks_readiness(self):
        marker = self.root / 'labwc-session-closing'
        for symlink in (False, True):
            if symlink:
                marker.symlink_to(self.root / 'missing')
            else:
                marker.touch()
            self.assertEqual(self.module.main(['session-ready']), 1)
            marker.unlink()
        self.run.assert_not_called()

    def test_socket_symlink_is_not_trusted(self):
        (self.root / 'wayland-alias').symlink_to(self.root / 'wayland-1')
        with mock.patch.dict(os.environ, WAYLAND_DISPLAY='wayland-alias'):
            self.assertEqual(self.module.main(['session-ready']), 1)
        self.run.assert_not_called()

    def test_runtime_and_display_cannot_escape_the_session_directory(self):
        for runtime, display in ((str(self.root), 'wayland-1'), (self.canonical, '../wayland-1'),
                                 (self.canonical, '/tmp/wayland-1'), (self.canonical, '..')):
            with self.subTest(runtime=runtime, display=display), mock.patch.dict(os.environ, XDG_RUNTIME_DIR=runtime, WAYLAND_DISPLAY=display):
                self.assertEqual(self.module.main(['session-ready']), 1)
        self.run.assert_not_called()

    def test_shared_runtime_directory_is_not_trusted(self):
        self.root.chmod(0o755)
        self.assertEqual(self.module.main(['session-ready']), 1)
        self.run.assert_not_called()


@unittest.skipUnless(shutil.which('apt-get') and shutil.which('apt-cache'), 'Debian APT tools required')
class ExcludedPackagePolicy(unittest.TestCase):
    """Real APT against synthetic local indexes; every installation is simulated."""
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='excluded-apt-')
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        repo = root / 'repo'; repo.mkdir()
        cls.names = ('firefox', 'firefox-esr', 'blender', 'blender-data', 'kdenlive', 'kdenlive-data')
        records = []
        for name in (*cls.names, 'cleanup-allowed', 'cleanup-needs-firefox'):
            for arch in ('amd64', 'i386'):
                record = f'Package: {name}\nVersion: 1.0\nArchitecture: {arch}\n'
                if name == 'cleanup-needs-firefox':
                    record += 'Depends: firefox\n'
                record += f'Filename: pool/{name}_1.0_{arch}.deb\nSize: 1\nSHA256: ' + 'a' * 64 + '\nDescription: offline dependency fixture\n'
                records.append(record)
        (repo / 'Packages').write_text('\n'.join(records))
        sources = root / 'sources.list'; sources.write_text(f'deb [trusted=yes] file:{repo} ./\n')
        status = root / 'status'; status.touch()
        for directory in ('lists/partial', 'archives/partial', 'log', 'trusted'):
            (root / directory).mkdir(parents=True)
        settings = {
            'Dir::Etc::main': '-', 'Dir::Etc::parts': '-',
            'Dir::Etc::sourcelist': str(sources), 'Dir::Etc::sourceparts': '-',
            'Dir::Etc::trusted': str(root / 'absent.gpg'), 'Dir::Etc::trustedparts': str(root / 'trusted'),
            'Dir::Etc::preferences': str(TARGET / 'etc/apt/preferences.d/default/00-excluded-desktop-apps.pref'),
            'Dir::Etc::preferencesparts': '-', 'Dir::State::status': str(status),
            'Dir::State::lists': str(root / 'lists'), 'Dir::State::extended_states': str(root / 'extended_states'),
            'Dir::Cache::archives': str(root / 'archives'), 'Dir::Cache::pkgcache': '',
            'Dir::Cache::srcpkgcache': '', 'Dir::Log': str(root / 'log'),
            'APT::Architecture': 'amd64', 'APT::Sandbox::User': pwd.getpwuid(os.getuid()).pw_name,
            'Debug::NoLocking': 'true', 'Acquire::Languages': 'none',
        }
        cls.options = [arg for key, value in settings.items() for arg in ('-o', f'{key}={value}')]
        cls.options += ['-o', 'APT::Architectures::=amd64', '-o', 'APT::Architectures::=i386']
        cls.environment = {**os.environ, 'LC_ALL': 'C', 'APT_CONFIG': '/dev/null'}
        result = cls.apt('apt-get', 'update')
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def apt(cls, tool, *args):
        return subprocess.run([tool, *cls.options, *args], text=True, capture_output=True,
                              env=cls.environment, timeout=20, check=False)

    def test_excluded_packages_have_no_candidate_on_both_architectures(self):
        for package in self.names:
            for arch in ('amd64', 'i386'):
                with self.subTest(package=package, arch=arch):
                    result = self.apt('apt-cache', 'policy', f'{package}:{arch}')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('Candidate: (none)', result.stdout)
                    self.assertRegex(result.stdout, r'1\.0\s+-1\b')

    def test_explicit_and_transitive_requests_fail_but_unrelated_packages_resolve(self):
        for package in ('firefox', 'blender', 'kdenlive', 'cleanup-needs-firefox'):
            with self.subTest(package=package):
                result = self.apt('apt-get', '--simulate', 'install', package)
                self.assertNotEqual(result.returncode, 0, result.stdout)
        allowed = self.apt('apt-get', '--simulate', 'install', 'cleanup-allowed')
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertIn('Inst cleanup-allowed', allowed.stdout)


if __name__ == '__main__':
    unittest.main()
