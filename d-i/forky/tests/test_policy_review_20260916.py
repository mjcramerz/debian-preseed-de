"""R4 regression boundaries and offline AppArmor compilation.

No profile is loaded into the host kernel. Package local fragments are tested
under synthetic envelopes, not passed off as target-vendor integration tests.
"""
from __future__ import annotations

from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

import test_systemd_resource_policy as resource

SEED = resource.SEED
TARGET = resource.TARGET
AA = TARGET / 'etc/apparmor.d'
USER = TARGET / resource.USER_BASE


def block(file: str, name: str) -> str:
    text = (AA / file).read_text()
    start = text.index('profile ' + name + ' ')
    end = text.find('\nprofile ', start + 1)
    return text[start:end if end >= 0 else len(text)]


def active(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


class SystemdReviewTests(unittest.TestCase):
    def test_profile_socket_policy_has_no_concurrency_knob(self):
        for profile in resource.PROFILES:
            with self.subTest(profile=profile.name):
                text = profile.read_text()
                self.assertNotIn('SYSTEMD_COREDUMP_MAX_CONNECTIONS', text)
                self.assertIn('SYSTEMD_COREDUMP_POLL_LIMIT_BURST="64"', text)
        path = TARGET / 'etc/systemd/system/systemd-coredump.socket.d/60-poll-limit.conf'
        self.assertEqual(active(path.read_text()), [
            '[Socket]', 'PollLimitIntervalSec=__SYSTEMD_COREDUMP_POLL_LIMIT_INTERVAL_SEC__s',
            'PollLimitBurst=__SYSTEMD_COREDUMP_POLL_LIMIT_BURST__'])
        self.assertFalse(path.with_name('60-concurrency.conf').exists())
        publisher = (SEED / 'scripts/late/storage-maintenance.sh').read_text()
        self.assertIn('systemd-coredump.socket.d/60-poll-limit.conf', publisher)
        self.assertNotIn('60-concurrency.conf', publisher)

    def test_administrator_can_restore_vendor_poll_rate(self):
        runner = resource.ResourcePolicyTests()
        for enabled in ('true', 'false'):
            with self.subTest(io=enabled), tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / 'socket.conf'
                dest.write_text((TARGET / 'etc/systemd/system/systemd-coredump.socket.d/60-poll-limit.conf').read_text())
                runner.shell('TMP_ENV_DIR=' + shlex.quote(tmp) +
                             '\napply_systemd_resource_placeholders ' + shlex.quote(str(dest)),
                             override=f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\nSYSTEMD_COREDUMP_POLL_LIMIT_BURST=150')
                self.assertEqual(active(dest.read_text()),
                                 ['[Socket]', 'PollLimitIntervalSec=2s', 'PollLimitBurst=150'])

    def test_only_essential_components_get_session_overrides(self):
        for unit in ('waybar', 'crystal-dock'):
            self.assertEqual(active((USER / f'{unit}.service.d/60-resource-class.conf').read_text()),
                             ['[Service]', 'Slice=app.slice'])
            self.assertNotIn('Slice=session.slice', (USER / f'{unit}.service').read_text())
        vendor = TARGET / 'etc/systemd/user'
        # R6 explicitly requests this class; retain the no-extra-weight boundary.
        self.assertEqual(active((vendor / 'wireplumber.service.d/60-resource-class.conf').read_text()),
                         ['[Service]', 'Slice=session.slice'])
        self.assertEqual(active((vendor / 'mako.service.d/60-resource-class.conf').read_text()),
                         ['[Service]', 'Slice=app.slice'])
        for unit in ('pipewire', 'pipewire-pulse', 'filter-chain'):
            self.assertEqual(active((vendor / f'{unit}.service.d/60-resources.conf').read_text()),
                             ['[Service]', 'CPUWeight=__SYSTEMD_CPUWEIGHT_USER_AUDIO_SERVICE_D__'])

    def test_explicit_scope_class_keeps_original_lifecycle(self):
        self.assertEqual(sorted(p.name for p in (USER / 'app-.scope.d').iterdir()),
                         ['50-session-labwc.conf', '60-resource-class.conf'])
        self.assertEqual(active((USER / 'app-.scope.d/60-resource-class.conf').read_text()),
                         ['[Scope]', 'Slice=app.slice'])
        package = TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app'
        for name in ('generic.py', 'session.py'):
            text = (package / name).read_text()
            self.assertIn('--slice=app.slice', text)
            self.assertNotIn('"--scope"', text)
        worker = (TARGET / 'usr/local/libexec/labwc-admin-action-worker').read_text()
        self.assertIn('--unit=labwc-power-lock-', worker)
        self.assertNotIn('--slice=app.slice', worker)  # session drop-in is not overridden


class AppArmorReviewTests(unittest.TestCase):
    def test_git_and_glib_execution_inherits_only_selected_paths(self):
        text = block('managed-desktop-utilities', 'managed-desktop-launcher')
        for rule in ('/usr/lib/git-core/git rix,', '/usr/lib/git-core/git-* rix,',
                     '/usr/lib/@{multiarch}/glib-2.0/gio-launch-desktop rix,'):
            self.assertIn(rule, text)
        self.assertNotIn('/usr/lib/** rix,', text)
        self.assertNotIn('/usr/lib/git-core/** rix,', text)
        self.assertNotIn('//null-', text)

    def test_existing_apt_policy_is_read_only(self):
        text = block('managed-desktop-utilities', 'managed-desktop-launcher')
        for rule in ('/var/lib/apt/lists/** r,', '/var/cache/apt/{pkgcache,srcpkgcache}.bin r,',
                     '/var/lib/dpkg/{status,triggers/File,triggers/Unincorp} r,'):
            self.assertIn(rule, text)

    def test_new_status_peers_are_exact_and_read_only(self):
        text = block('managed-desktop-utilities', 'managed-desktop-launcher')
        for peer in ('code', 'microsoft-edge-stable', 'labwc-microsoft-edge-launcher',
                     'mullvad-browser', 'labwc-mullvad-browser-launcher', 'mullvad',
                     'obsidian', 'managed-desktop-editors'):
            self.assertIn(f'ptrace (read) peer={peer},', text)
        self.assertNotRegex(text, r'ptrace\s*\([^)]*trace[^)]*\)')
        self.assertNotRegex(text, r'ptrace\s*\(read\)\s*peer=[^,]*\*')

    def test_udev_queries_do_not_add_device_access(self):
        text = block('managed-desktop-utilities', 'managed-desktop-launcher')
        self.assertIn('/run/udev/data/{b[0-9]*:[0-9]*,c189:[0-9]*,+usb:*} r,', text)
        self.assertNotRegex(text, r'(?m)^\s*/dev/(?:sd|nvme|bus/usb)')

    def test_editor_queries_and_extensionless_documents_are_owner_scoped(self):
        text = block('managed-desktop-utilities', 'managed-desktop-editors')
        self.assertIn('owner @{PROC}/[0-9]*/{stat,cmdline} r,', text)
        self.assertIn('owner @{HOME}/[^.]* rwk,', text)
        self.assertNotIn('owner @{HOME}/**', text)
        self.assertNotIn('/WOW', text)
        self.assertNotIn('owner @{PROC}/[0-9]*/mem', text)

    def test_inherited_panel_status_is_read_only_and_profile_local(self):
        for name in ('managed-labwc-brightness-control', 'managed-labwc-capture'):
            text = block('managed-desktop-wrappers', name)
            self.assertIn('@{sys}/devices/**/power_supply/*/cycle_count r,', text)
        text = block('managed-desktop-wrappers', 'managed-labwc-brightness-control')
        self.assertIn('owner @{PROC}/[0-9]*/net/dev r,', text)
        text = block('managed-desktop-wrappers', 'managed-labwc-bluetooth')
        self.assertIn('@{sys}/devices/system/cpu/present r,', text)

    def test_nnp_link_handler_does_not_escape_by_exec_transition(self):
        text = block('managed-desktop-wrappers', 'managed-labwc-managed-app')
        child = text.split('  profile managed-app-bwrap ', 1)[1]
        self.assertIn('/usr/bin/{xdg-open,systemd-run} rix,', child)
        self.assertIn('/usr/local/bin/labwc-wayland-app rix,', child)
        self.assertIn('#include <abstractions/managed-wrapper-python>', child)
        self.assertNotRegex('\n'.join(active(child)), r'\s[rwmkl]*[pPcCuU][^ ,]*x\s')
        self.assertNotIn('labwc_managed_app/**', child)
        abstraction = (AA / 'abstractions/managed-wrapper-python').read_text()
        self.assertIn('deny owner @{HOME}/.local/lib/python*/** mrwkl,', abstraction)

    def test_edge_decoder_has_no_workspace_or_browser_database_grants(self):
        text = (AA / 'local/microsoft-edge-stable').read_text()
        parent, child = text.split('profile edge-glycin-bwrap ', 1)
        self.assertIn('/usr/bin/bwrap rCx -> edge-glycin-bwrap,', parent)
        self.assertTrue(child.startswith('flags=(mediate_deleted) {'))
        for body in (parent, child):
            self.assertIn('deny @{HOME}/Workspace/** rwklmx,', body)
            for line in active(body):
                if 'Workspace' in line:
                    self.assertTrue(line.startswith('deny '), line)
        for prefix in ('/oldroot', '/newroot', '/tmp/{oldroot,newroot}'):
            self.assertIn('deny ' + prefix + '@{HOME}/Workspace/** rwklmx,', child)
        self.assertIn('/usr/libexec/glycin-loaders/2+/{glycin-image-rs,glycin-svg} rix,', child)
        for forbidden in ('managed-user-documents', 'managed-desktop-application',
                          'network inet', 'BrowserMetrics', 'EdgeLanguageDetectionModel',
                          '/dev/dri', '/opt/microsoft/msedge/**'):
            self.assertNotIn(forbidden, child)
        self.assertNotRegex('\n'.join(active(child)), r'\s[rwmkl]*[pPcCuU][^ ,]*x\s')

    def test_modified_profiles_are_published_by_existing_installer(self):
        text = (SEED / 'scripts/late/security.sh').read_text()
        for name in ('managed-desktop-utilities', 'managed-desktop-wrappers', 'microsoft-edge-stable'):
            self.assertIn(name, text)
        modes = (TARGET / 'etc/apparmor/managed-modes.conf.tmpl').read_text()
        for name in ('managed-desktop-utilities', 'managed-desktop-wrappers', 'microsoft-edge-stable'):
            self.assertIn(name, modes)
        # Child labels are discovered from parser output, not a separate manual list.
        verify = (TARGET / 'usr/local/lib/perl5/site_perl/apparmor-managed-modes/AppArmor/ManagedModes/Verify.pm').read_text()
        self.assertIn('for my $profile_label (@$labels)', verify)


@unittest.skipUnless(shutil.which('apparmor_parser') and Path('/etc/apparmor.d/tunables/global').is_file(),
                     'AppArmor parser and package policy data required')
class AppArmorCompileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='apparmor-r4-')
        cls.stage = Path(cls.tmp.name)
        shutil.copytree('/etc/apparmor.d', cls.stage, dirs_exist_ok=True, symlinks=True)
        shutil.copytree(AA, cls.stage, dirs_exist_ok=True, symlinks=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile_policy(self, path):
        result = subprocess.run(['apparmor_parser', '-Q', '-K', '-b', str(self.stage),
                                 '-I', str(self.stage), str(path)],
                                text=True, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_all_repository_profile_sources_compile_without_kernel_load(self):
        for source in sorted(p for p in AA.iterdir() if p.is_file()):
            with self.subTest(profile=source.name):
                self.compile_policy(self.stage / source.name)

    def test_all_local_fragments_compile_in_synthetic_package_envelopes(self):
        for source in sorted(p for p in (AA / 'local').iterdir() if p.is_file()):
            with self.subTest(fragment=source.name):
                name = 'r4-test-' + source.name
                path = self.stage / name
                path.write_text('abi "/usr/share/apparmor-features/features",\n#include <tunables/global>\n'
                                'profile ' + name + ' flags=(attach_disconnected, mediate_deleted) {\n'
                                '#include <local/' + source.name + '>\n}\n')
                self.compile_policy(path)


if __name__ == '__main__':
    unittest.main()
