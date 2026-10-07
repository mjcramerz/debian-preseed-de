"""R4 regression boundaries and offline AppArmor compilation.

No profile is loaded into the host kernel. Package local fragments are tested
under synthetic envelopes, not passed off as target-vendor integration tests.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file
from payload_fixture import read_text as payload_read_text

from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from theme_fixture import render_theme_tree

import test_systemd_resource_policy as resource

SEED = resource.SEED
TARGET = resource.TARGET
AA = TARGET / 'etc/apparmor.d'
USER = TARGET / resource.USER_BASE


def block(file: str, name: str) -> str:
    text = payload_read_text(AA / file)
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
                text = payload_read_text(profile)
                self.assertNotIn('SYSTEMD_COREDUMP_MAX_CONNECTIONS', text)
                self.assertIn('SYSTEMD_COREDUMP_POLL_LIMIT_BURST="64"', text)
        path = TARGET / 'etc/systemd/system/systemd-coredump.socket.d/60-poll-limit.conf'
        self.assertEqual(active(payload_read_text(path)), [
            '[Socket]', 'PollLimitIntervalSec=__SYSTEMD_COREDUMP_POLL_LIMIT_INTERVAL_SEC__s',
            'PollLimitBurst=__SYSTEMD_COREDUMP_POLL_LIMIT_BURST__'])
        self.assertFalse(payload_source_exists(path.with_name('60-concurrency.conf')))
        publisher = payload_read_text(SEED / 'scripts/late/storage-maintenance.sh')
        self.assertIn('systemd-coredump.socket.d/60-poll-limit.conf', publisher)
        self.assertNotIn('60-concurrency.conf', publisher)

    def test_administrator_can_restore_vendor_poll_rate(self):
        runner = resource.ResourcePolicyTests()
        for enabled in ('true', 'false'):
            with self.subTest(io=enabled), tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / 'socket.conf'
                dest.write_text(payload_read_text(TARGET / 'etc/systemd/system/systemd-coredump.socket.d/60-poll-limit.conf'))
                runner.shell('TMP_ENV_DIR=' + shlex.quote(tmp) +
                             '\napply_systemd_resource_placeholders ' + shlex.quote(str(dest)),
                             override=f'SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE={enabled}\nSYSTEMD_COREDUMP_POLL_LIMIT_BURST=150')
                self.assertEqual(active(payload_read_text(dest)),
                                 ['[Socket]', 'PollLimitIntervalSec=2s', 'PollLimitBurst=150'])

    def test_only_essential_components_get_session_overrides(self):
        for unit in ('waybar', 'crystal-dock'):
            self.assertEqual(active(payload_read_text(USER / f'{unit}.service.d/60-resource-class.conf')),
                             ['[Service]', 'Slice=app.slice'])
            self.assertNotIn('Slice=session.slice', payload_read_text(USER / f'{unit}.service'))
        vendor = TARGET / 'etc/systemd/user'
        # R6 explicitly requests this class; retain the no-extra-weight boundary.
        self.assertEqual(active(payload_read_text(vendor / 'wireplumber.service.d/60-resource-class.conf')),
                         ['[Service]', 'Slice=session.slice'])
        self.assertEqual(active(payload_read_text(vendor / 'mako.service.d/60-resource-class.conf')),
                         ['[Service]', 'Slice=app.slice'])
        for unit in ('pipewire', 'pipewire-pulse', 'filter-chain'):
            self.assertEqual(active(payload_read_text(vendor / f'{unit}.service.d/60-resources.conf')),
                             ['[Service]', '__SYSTEMD_CPUWEIGHT_USER_AUDIO_SERVICE_D__'])

    def test_explicit_scope_class_keeps_original_lifecycle(self):
        self.assertEqual(sorted(p.name for p in (USER / 'app-.scope.d').iterdir()),
                         ['50-session-labwc.conf', '60-resource-class.conf'])
        self.assertEqual(active(payload_read_text(USER / 'app-.scope.d/60-resource-class.conf')),
                         ['[Scope]', 'Slice=app.slice'])
        package = TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app'
        for name in ('generic.py', 'session.py'):
            text = payload_read_text(package / name)
            self.assertIn('--slice=app.slice', text)
            self.assertNotIn('"--scope"', text)
        worker = payload_read_text(TARGET / 'usr/local/libexec/labwc-admin-action-worker')
        self.assertIn('--unit=labwc-power-lock-', worker)
        self.assertNotIn('--slice=app.slice', worker)  # session drop-in is not overridden


class AppArmorReviewTests(unittest.TestCase):
    def test_git_and_glib_execution_inherits_only_selected_paths(self):
        text = block('desktop-utilities', 'desktop-launcher')
        for rule in ('/usr/lib/git-core/git rix,', '/usr/lib/git-core/git-* rix,',
                     '/usr/lib/@{multiarch}/glib-2.0/gio-launch-desktop rix,'):
            self.assertIn(rule, text)
        self.assertNotIn('/usr/lib/** rix,', text)
        self.assertNotIn('/usr/lib/git-core/** rix,', text)
        self.assertNotIn('//null-', text)

    def test_existing_apt_policy_is_read_only(self):
        text = block('desktop-utilities', 'desktop-launcher')
        for rule in ('/var/lib/apt/lists/** r,', '/var/cache/apt/{pkgcache,srcpkgcache}.bin r,',
                     '/var/lib/dpkg/{status,triggers/File,triggers/Unincorp} r,'):
            self.assertIn(rule, text)

    def test_new_status_peers_are_exact_and_read_only(self):
        text = block('desktop-utilities', 'desktop-launcher')
        for peer in ('code', 'microsoft-edge-stable', 'labwc-microsoft-edge-launcher',
                     'mullvad-browser', 'labwc-mullvad-browser-launcher', 'mullvad',
                     'obsidian', 'desktop-editors'):
            self.assertIn(f'ptrace (read) peer={peer},', text)
        self.assertNotRegex(text, r'ptrace\s*\([^)]*trace[^)]*\)')
        self.assertNotRegex(text, r'ptrace\s*\(read\)\s*peer=[^,]*\*')

    def test_udev_queries_do_not_add_device_access(self):
        text = block('desktop-utilities', 'desktop-launcher')
        self.assertIn('/run/udev/data/{b[0-9]*:[0-9]*,c189:[0-9]*,+usb:*} r,', text)
        self.assertNotRegex(text, r'(?m)^\s*/dev/(?:sd|nvme|bus/usb)')

    def test_editor_queries_and_extensionless_documents_are_owner_scoped(self):
        text = block('desktop-utilities', 'desktop-editors')
        self.assertIn('owner @{PROC}/[0-9]*/{stat,cmdline} r,', text)
        self.assertIn('owner @{HOME}/[^.]* rwk,', text)
        self.assertNotIn('owner @{HOME}/**', text)
        self.assertNotIn('/WOW', text)
        self.assertNotIn('owner @{PROC}/[0-9]*/mem', text)

    def test_inherited_panel_status_is_read_only_and_profile_local(self):
        for name in ('labwc-brightness-control', 'labwc-capture'):
            text = block('desktop-wrappers', name)
            self.assertIn('@{sys}/devices/**/power_supply/*/cycle_count r,', text)
        text = block('desktop-wrappers', 'labwc-brightness-control')
        self.assertIn('owner @{PROC}/[0-9]*/net/dev r,', text)
        text = block('desktop-wrappers', 'labwc-bluetooth')
        self.assertIn('@{sys}/devices/system/cpu/present r,', text)

    def test_nnp_link_handler_does_not_escape_by_exec_transition(self):
        text = block('desktop-wrappers', 'labwc-app')
        child = text.split('  profile app-bwrap ', 1)[1]
        self.assertIn('/usr/bin/{xdg-open,systemd-run} rix,', child)
        self.assertIn('/usr/local/bin/labwc-wayland-app rix,', child)
        self.assertIn('#include <abstractions/wrapper-python>', child)
        self.assertNotRegex('\n'.join(active(child)), r'\s[rwmkl]*[pPcCuU][^ ,]*x\s')
        self.assertNotIn('labwc_managed_app/**', child)
        abstraction = payload_read_text(AA / 'abstractions/wrapper-python')
        self.assertIn('deny owner @{HOME}/.local/lib/python*/** mrwkl,', abstraction)

    def test_edge_decoder_has_no_workspace_or_browser_database_grants(self):
        text = payload_read_text(AA / 'local/microsoft-edge-stable')
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
        for forbidden in ('user-documents', 'desktop-application',
                          'network inet', 'BrowserMetrics', 'EdgeLanguageDetectionModel',
                          '/dev/dri', '/opt/microsoft/msedge/**'):
            self.assertNotIn(forbidden, child)
        self.assertNotRegex('\n'.join(active(child)), r'\s[rwmkl]*[pPcCuU][^ ,]*x\s')

    def test_modified_profiles_are_published_by_existing_installer(self):
        text = payload_read_text(SEED / 'scripts/late/security.sh')
        for name in ('desktop-utilities', 'desktop-wrappers', 'microsoft-edge-stable'):
            self.assertIn(name, text)
        modes = payload_read_text(TARGET / 'etc/apparmor/modes.conf.tmpl')
        for name in ('desktop-utilities', 'desktop-wrappers', 'microsoft-edge-stable'):
            self.assertIn(name, modes)
        # Child labels are discovered from parser output, not a separate manual list.
        verify = payload_read_text(TARGET / 'usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/Verify.pm')
        self.assertIn('for my $profile_label (@$labels)', verify)


@unittest.skipUnless(shutil.which('apparmor_parser') and payload_source_is_file(Path('/etc/apparmor.d/tunables/global')),
                     'AppArmor parser and package policy data required')
class AppArmorCompileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='apparmor-r4-')
        cls.stage = Path(cls.tmp.name)
        shutil.copytree('/etc/apparmor.d', cls.stage, dirs_exist_ok=True, symlinks=True)
        shutil.copytree(AA, cls.stage, dirs_exist_ok=True, symlinks=True)
        render_theme_tree(cls.stage)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compile_policy(self, path):
        result = subprocess.run(payload_installed_argv(['apparmor_parser', '-Q', '-K', '-b', str(self.stage),
                                 '-I', str(self.stage), str(path)]),
                                text=True, capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_all_repository_profile_sources_compile_without_kernel_load(self):
        for source in sorted(p for p in AA.iterdir() if payload_source_is_file(p)):
            with self.subTest(profile=source.name):
                self.compile_policy(self.stage / source.name.removesuffix('.tmpl'))

    def test_all_local_fragments_compile_in_synthetic_package_envelopes(self):
        for source in sorted(p for p in (AA / 'local').iterdir() if payload_source_is_file(p)):
            with self.subTest(fragment=source.name):
                name = 'r4-test-' + source.name
                path = self.stage / name
                path.write_text('abi "/usr/share/apparmor-features/features",\n#include <tunables/global>\n'
                                'profile ' + name + ' flags=(attach_disconnected, mediate_deleted) {\n'
                                '#include <local/' + source.name.removesuffix('.tmpl') + '>\n}\n')
                self.compile_policy(path)


if __name__ == '__main__':
    unittest.main()
