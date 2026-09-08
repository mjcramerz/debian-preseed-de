"""Failure injection against real helpers; all disk/target paths are fixtures.

Terminal installer tests kill only their own process trees. They never partition,
mount, chroot the host, signal a real main-menu, or activate target services.
"""
from pathlib import Path
import ctypes
import importlib.util
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from process_fixture import stop_test_tree, wait_file

ROOT = Path(__file__).resolve().parents[1]
LC = ROOT / 'scripts/common/lifecycle.sh'
CORE = ROOT / 'scripts/late/core.sh'
GUARD = ROOT / 'scripts/preseed/guard-hook.sh'
APT = ROOT / 'scripts/common/apt-sources.sh'
Q = shlex.quote


def shell(text, env=None, shell_path='/bin/sh'):
    return subprocess.run([shell_path, '-eu', '-c', text], env={**os.environ, **(env or {})},
                          capture_output=True, text=True, timeout=15)


def module(path, name):
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    loader.exec_module(result)
    return result


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='installer-lifecycle-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.state = self.runtime / 'state'
        self.env = {**os.environ, 'INSTALLER_RUNTIME_DIR': str(self.runtime),
                    'INSTALLER_TARGET_DIR': str(self.root / 'not-mounted')}
        (self.runtime / 'bootstrap').mkdir(parents=True)
        shutil.copyfile(LC, self.runtime / 'bootstrap/source.sh')

    def run_lc(self, code):
        return shell(f'. {Q(str(LC))}\n{code}', self.env)

    def held(self, code, executable='/bin/sh'):
        p = subprocess.Popen([executable, '-eu', '-c', f'. {Q(str(LC))}\n{code}'],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(stop_test_tree, p)
        return p

    def test_udeb_metadata_needs_no_stat_sets_id_or_timeout_applet(self):
        bindir=self.root/'bin'; bindir.mkdir()
        for name in ('stat','setsid','timeout'):
            p=bindir/name; p.write_text('#!/bin/sh\nexit 127\n'); p.chmod(0o755)
        self.env['PATH']=str(bindir)+':'+os.environ['PATH']
        result=self.run_lc('installer_lifecycle_begin late; '
                           'installer_run_supervised /bin/sh -c "exit 0"; '
                           'installer_lifecycle_complete')
        self.assertEqual(result.returncode,0,result.stderr)
        for mode in (0o600,0o640,0o755,0o1777,0o2750):
            p=self.root/'metadata'; p.touch(); p.chmod(mode)
            result=self.run_lc('installer_metadata_value '+Q(str(p))+' mode')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),format(mode,'o'))

    def test_udeb_fetch_budget_enforces_timeout_and_preserves_other_status(self):
        for command, status in [('exit 37',37), ('sleep 20',124)]:
            start=time.monotonic()
            result=self.run_lc('installer_run_bounded 1 /bin/sh -c '+Q(command))
            self.assertEqual(result.returncode,status,result.stderr)
            self.assertLess(time.monotonic()-start,5)

    def test_first_failure_is_retained_and_success_invalidated(self):
        result = self.run_lc('installer_lifecycle_paths; touch "$LC_STATE/installation.success"; '
                             'installer_record_failure 37 render root-cause; '
                             'installer_record_failure 99 cleanup secondary')
        self.assertEqual(result.returncode, 0, result.stderr)
        record = (self.state / 'first-failure').read_text()
        self.assertIn('status=37', record)
        self.assertIn('detail=root-cause', record)
        self.assertNotIn('secondary', record)
        self.assertFalse((self.state / 'installation.success').exists())
        self.assertEqual((self.state / 'first-failure').stat().st_mode & 0o777, 0o600)

    def test_success_is_explicit_and_repeat_phase_is_noop(self):
        result = self.run_lc('installer_lifecycle_begin late; installer_lifecycle_complete')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_lc('if installer_lifecycle_begin late; then exit 91; else test "$?" = 10; fi')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.state / 'late.done').is_file())
        self.assertFalse((self.state / 'installation.success').exists())

    def test_zero_exit_without_completion_is_fatal(self):
        p = self.held('installer_lifecycle_begin late; exit 0')
        self.assertTrue(wait_file(self.state / 'first-failure'))
        self.assertIn('status=125', (self.state / 'first-failure').read_text())
        self.assertIsNone(p.poll())

    def test_already_fatal_cannot_execute_late(self):
        self.assertEqual(self.run_lc('installer_record_failure 37 render first').returncode, 0)
        for _ in range(2):
            p = self.held('installer_lifecycle_begin late; touch "$LC_STATE/UNSAFE"')
            time.sleep(.12)
            self.assertIsNone(p.poll())
        self.assertFalse((self.state / 'UNSAFE').exists())
        self.assertIn('status=37', (self.state / 'first-failure').read_text())

    def test_interrupted_phase_is_not_resumed(self):
        self.state.mkdir()
        (self.state / 'partman.running').mkdir()
        p = self.held('installer_lifecycle_begin partman; touch "$LC_STATE/UNSAFE"')
        self.assertTrue(wait_file(self.state / 'first-failure'))
        self.assertFalse((self.state / 'UNSAFE').exists())
        self.assertIn('interrupted or concurrent', (self.state / 'first-failure').read_text())
        self.assertIsNone(p.poll())

    def test_failed_child_and_cleanup_preserve_original_status(self):
        child = self.root / 'child'
        child.write_text('#!/bin/sh\ntrap \'s=$?; false || :; exit "$s"\' 0\nexit 41\n')
        child.chmod(0o755)
        p = subprocess.Popen(['/bin/sh', str(GUARD), 'hook-finish-07preseed', str(child)],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(stop_test_tree, p)
        self.assertTrue(wait_file(self.state / 'first-failure'))
        self.assertIn('status=41', (self.state / 'first-failure').read_text())
        self.assertFalse((self.state / 'hook-finish-07preseed.done').exists())
        self.assertIsNone(p.poll())

    def test_finish_install_failure_stops_actual_main_menu_ancestor(self):
        child = self.root / 'late'
        child.write_text('#!/bin/sh\necho attempt >>"$INSTALLER_RUNTIME_DIR/attempts"\nexit 47\n')
        child.chmod(0o755)
        # Reproduce d-i's dangerous contract: swallowing hook errors then
        # automatically re-entering finish-install. The real guard must not return.
        program = '''import ctypes,subprocess,sys,os
ctypes.CDLL(None).prctl(15,b'main-menu',0,0,0)
for attempt in range(5):
 subprocess.run(['/bin/sh',sys.argv[1],'hook-finish-07preseed',sys.argv[2]])
 open(os.environ['INSTALLER_RUNTIME_DIR']+'/continued','w').write('unsafe')
'''
        p = subprocess.Popen([sys.executable, '-c', program, str(GUARD), str(child)],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(stop_test_tree, p)
        self.assertTrue(wait_file(self.state / 'first-failure'))
        deadline = time.monotonic() + 3
        status = ''
        while time.monotonic() < deadline:
            status = Path(f'/proc/{p.pid}/status').read_text()
            if 'State:\tT' in status:
                break
            time.sleep(.025)
        self.assertIn('State:\tT', status)
        self.assertEqual((self.runtime / 'attempts').read_text().splitlines(), ['attempt'])
        self.assertFalse((self.runtime / 'continued').exists())
        self.assertIn('status=47', (self.state / 'first-failure').read_text())

    def test_reboot_gate_rejects_missing_prior_completion(self):
        child = self.root / '99reboot'
        child.write_text('#!/bin/sh\ntouch "$INSTALLER_RUNTIME_DIR/reboot"\nexit 11\n')
        child.chmod(0o755)
        p = subprocess.Popen(['/bin/sh', str(GUARD), 'hook-finish-99reboot', str(child)],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(stop_test_tree, p)
        self.assertTrue(wait_file(self.state / 'first-failure'))
        self.assertFalse((self.runtime / 'reboot').exists())
        self.assertFalse((self.state / 'installation.success').exists())

    def test_signal_supervision_is_bounded_and_records_original_signal(self):
        child = self.root / 'child'
        child.write_text('#!/bin/sh\necho $$ >"$INSTALLER_RUNTIME_DIR/child-pid"\nsleep 60\n')
        child.chmod(0o755)
        p = self.held(f'installer_lifecycle_begin late; installer_run_supervised {Q(str(child))}; installer_lifecycle_complete')
        self.assertTrue(wait_file(self.runtime / 'child-pid'))
        pid = int((self.runtime / 'child-pid').read_text())
        p.send_signal(signal.SIGTERM)
        self.assertTrue(wait_file(self.state / 'first-failure'))
        self.assertIn('status=143', (self.state / 'first-failure').read_text())
        deadline = time.monotonic() + 7
        while Path(f'/proc/{pid}').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertFalse(Path(f'/proc/{pid}').exists())
        self.assertIsNone(p.poll())

    def test_symlink_state_directory_is_rejected_without_writing(self):
        other = self.root / 'other'; other.mkdir()
        self.state.symlink_to(other, target_is_directory=True)
        result = self.run_lc('installer_record_failure 37 render root')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(other.iterdir()), [])


class FamilyFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='family-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root / 'policy'
        self.policy.write_text('INSTALLER_PKGSEL_INCLUDE=fixture\nINSTALLER_SECURE_BOOT_BOOT_CHAIN_PACKAGES=fixture\nINSTALLER_SECURE_BOOT_TARGET_PACKAGES=fixture\n')

    def family(self, family, arch, failure='render'):
        script = 'btrfs-family.sh' if family in ('btrfs', 'vm') else 'f2fs-family.sh'
        invoke = f'run_btrfs_family_late_command {family}' if family != 'f2fs' else 'run_f2fs_family_late_command'
        text = f'''. {Q(str(CORE))}
. {Q(str(ROOT/'scripts/late'/script))}
TMP_ENV_DIR={Q(str(self.root))}
FILE_LOGIND_OVERRIDE_CONF=/etc/systemd/logind.conf.d/override.conf
INSTALLER_ARCH_CLASS={arch}
installer_fatal() {{ echo "fatal: $*" >&2; exit 1; }}
installer_class_policy_env_path() {{ echo {Q(str(self.policy))}; }}
installer_repo_join_var() {{ echo fixture; }}
late_command_shared_init() {{ :; }}
late_command_fetch_common_assets() {{ {'return 71' if failure == 'early' else ':'}; }}
fetch_hook() {{ :; }}
late_command_load_runtime_env() {{ :; }}
late_command_load_host_env() {{ :; }}
render_target_asset() {{
 printf '%s|%s|%s\n' "$INSTALLER_GRUB_EFI_TARGET" "$INSTALLER_GRUB_MOK_MANAGER_EFI_PATH" "$INSTALLER_GRUB_REMOVABLE_BOOT_EFI_PATH"
 return 37
}}
stage_target_asset() {{ echo UNSAFE; return 0; }}
install_target_wpa_supplicant_runtime_policy() {{ echo UNSAFE; return 0; }}
{invoke}
echo UNSAFE
'''
        return shell(text)

    def test_arch_policy_precedes_all_family_renderers(self):
        for family in ('btrfs', 'vm', 'f2fs'):
            for arch, expected in [('amd64', 'x86_64-efi|/EFI/debian/mmx64.efi|/EFI/BOOT/BOOTX64.EFI'),
                                   ('arm64', 'arm64-efi|/EFI/debian/mmaa64.efi|/EFI/BOOT/BOOTAA64.EFI')]:
                with self.subTest(family=family, arch=arch):
                    result = self.family(family, arch)
                    self.assertEqual(result.returncode, 37, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_early_family_failure_cannot_be_masked(self):
        for family in ('btrfs', 'vm', 'f2fs'):
            with self.subTest(family=family):
                result = self.family(family, 'amd64', 'early')
                self.assertEqual(result.returncode, 71, result.stderr)
                self.assertNotIn('UNSAFE', result.stdout)

    def test_conditional_host_loader_preserves_failed_profile(self):
        result = shell(f'. {Q(str(CORE))}\nlate_command_load_profile_env() {{ return 38; }}\n'
                       'late_command_load_account_env() { echo UNSAFE; }\n'
                       'if late_command_load_host_env; then exit 91; else exit "$?"; fi')
        self.assertEqual(result.returncode, 38)
        self.assertNotIn('UNSAFE', result.stdout)

    def test_conditional_wpa_loader_stops_on_first_failed_asset(self):
        text = f'. {Q(str(CORE))}\n'
        for name in ('CONF', 'P2P_DEVICE_CONF', 'DBUS_SERVICE_OVERRIDE', 'DBUS_SERVICE_ALIAS'):
            text += f'FILE_WPA_SUPPLICANT_{name}=/fixture\n'
        text += 'FILE_NETWORKMANAGER_LINK_PRIVACY_CONF=/fixture\ninstaller_repo_join_var() { echo fixture; }\n'
        text += 'stage_target_asset() { echo attempt; return 39; }\n'
        text += 'if install_target_wpa_supplicant_runtime_policy; then exit 91; else exit "$?"; fi'
        result = shell(text)
        self.assertEqual(result.returncode, 39, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['attempt'])

    def test_unsupported_arch_is_rejected(self):
        result = self.family('vm', 'riscv64')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported arch', result.stderr)

    def test_final_kernel_repair_precedes_grub_generation(self):
        for name in ('btrfs-family.sh', 'f2fs-family.sh'):
            text = (ROOT / 'scripts/late' / name).read_text()
            self.assertLess(text.index('\n  repair_target_installed_kernels\n'), text.index('\n  run_target_grub_config_update\n'))


class AptBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='installer-apt-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'etc/apt/sources.list.d').mkdir(parents=True)

    def test_cdrom_list_and_deb822_removed_before_network_source_publication(self):
        (self.root / 'etc/apt/sources.list').write_text('deb cdrom:[fixture] /\ndeb https://mirror.invalid/debian trixie main\n')
        src = self.root / 'etc/apt/sources.list.d/media.sources'
        src.write_text('Types: deb\nURIs: cdrom:fixture\nSuites: trixie\n\nTypes: deb\nURIs: https://safe.invalid/debian\nSuites: trixie\n')
        result = shell(f'. {Q(str(LC))}\n. {Q(str(APT))}; installer_apt_strip_cdrom {Q(str(self.root))}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('cdrom:', src.read_text())
        self.assertIn('https://safe.invalid', src.read_text())
        self.assertIn('https://mirror.invalid', (self.root / 'etc/apt/sources.list').read_text())

    def test_indirect_source_cannot_overwrite_external_file(self):
        external = self.root / 'external'; external.write_text('retain')
        (self.root / 'etc/apt/sources.list').symlink_to(external)
        result = shell(f'. {Q(str(LC))}\n. {Q(str(APT))}; installer_apt_strip_cdrom {Q(str(self.root))}')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(external.read_text(), 'retain')

    def test_bootstrap_adapter_is_idempotent_and_substitutes_apt_boundary(self):
        helper = self.root / 'helper'; helper.write_text('echo "normalized:$1"\nexit 100\n')
        script = self.root / 'bootstrap-base.postinst'
        script.write_text('#!/bin/sh\nset -e\nDISTRIBUTION=trixie\nwaypoint() { "$2"; }\napt_update() { echo UNSAFE; }\nwaypoint 3 apt_update\necho UNSAFE\n')
        script.chmod(0o755)
        command = [str(ROOT / 'scripts/preseed/base-apt-adapter.sh'), str(script), str(helper)]
        for _ in range(2):
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(script)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 100)
        self.assertEqual(result.stdout.splitlines(), ['normalized:trixie'])

    def test_unknown_bootstrap_version_is_rejected_before_mutation(self):
        script = self.root / 'bootstrap'; script.write_text('#!/bin/sh\nwaypoint 4 apt_update\n'); script.chmod(0o755)
        helper = self.root / 'helper'; helper.touch()
        result = subprocess.run([str(ROOT / 'scripts/preseed/base-apt-adapter.sh'), str(script), str(helper)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(script.read_text(), '#!/bin/sh\nwaypoint 4 apt_update\n')


class CodexStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = module(ROOT / 'scripts/late/codex-state.py', 'installer_codex_state_tests')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codex-state-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.expected = self.root / 'expected'; self.expected.mkdir(mode=0o750)
        self.uid, self.gid = os.getuid(), os.getgid()
        self.commit, self.url = 'a' * 40, 'https://example.invalid/pinned'
        for path, content, mode in [('.git/HEAD', self.commit+'\n', 0o640),
                ('.git/config', '[core]\n bare = false\n[remote "origin"]\n url = '+self.url+'\n', 0o640),
                ('home/config.toml', 'policy = "pinned"\n', 0o640),
                ('home/history.jsonl', '', 0o660), ('home/memories/.git', '', 0o660)]:
            p = self.expected / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content); p.chmod(mode)
        for p in [self.expected, *self.expected.rglob('*')]:
            if p.is_dir(): p.chmod(0o750)
        for name in self.mod.MUTABLE_TREES:
            p = self.expected / name; p.mkdir(exist_ok=True); p.chmod(0o2770)
        (self.expected / 'home/packages').symlink_to('/data/codex/packages')
        self.actual = self.root / 'actual'; shutil.copytree(self.expected, self.actual, symlinks=True)

    def compare(self):
        self.mod.compare_trees(self.expected, self.actual, self.uid, self.gid, self.commit, self.url)

    def test_correct_pinned_state_succeeds_repeatedly(self):
        self.compare(); self.compare()

    def test_legitimate_account_runtime_changes_converge(self):
        auth = self.actual / 'home/auth.json'
        auth.write_text('{"private":"not-logged"}')
        auth.chmod(0o600)
        session = self.actual / 'home/sessions/new.jsonl'; session.write_text('runtime'); session.chmod(0o660)
        self.compare(); self.compare()

    def test_optional_auth_contents_are_opaque(self):
        auth = self.actual / 'home/auth.json'
        auth.write_bytes(b'\xffnot-installer-configuration\x00')
        auth.chmod(0o600)
        self.compare()
        self.assertEqual(self.mod.snapshot(self.actual)['home/auth.json'].digest, '')

    def test_installer_candidate_must_not_stage_auth(self):
        auth = self.expected / 'home/auth.json'
        auth.write_text('{}')
        auth.chmod(0o600)
        with self.assertRaises(self.mod.StateError): self.compare()

    def test_immutable_conflict_fails(self):
        (self.actual / 'home/config.toml').write_text('tampered')
        with self.assertRaises(self.mod.StateError): self.compare()

    def test_partial_unpublished_tree_fails_without_touching_existing(self):
        (self.actual / 'home/packages').unlink()
        with self.assertRaises(self.mod.StateError): self.compare()
        self.assertTrue((self.actual / 'home/config.toml').is_file())
        # An operator can restore the *verified* missing publication, not weaken
        # comparison or take over unrelated state. Correct state then converges.
        (self.actual / 'home/packages').symlink_to('/data/codex/packages')
        self.compare()

    def test_malicious_git_config_is_not_executed(self):
        p = self.actual / '.git/config'
        p.write_text(p.read_text()+'[include]\n path = /etc/shadow\n')
        with self.assertRaises(self.mod.StateError): self.compare()

    def test_wrong_pin_remains_fatal(self):
        (self.actual / '.git/HEAD').write_text('b'*40+'\n')
        with self.assertRaises(self.mod.StateError): self.compare()

    def test_mutable_symlink_escape_is_rejected(self):
        (self.actual / 'home/sessions/escape').symlink_to('/etc/shadow')
        with self.assertRaises(self.mod.StateError): self.compare()

    def test_hardlinks_and_world_writable_state_are_rejected(self):
        p = self.actual / 'home/config.toml'
        os.link(p, self.actual / 'home/extra')
        with self.assertRaises(self.mod.StateError): self.compare()
        (self.actual / 'home/extra').unlink()
        auth = self.actual / 'home/auth.json'
        auth.write_text('{}')
        auth.chmod(0o666)
        with self.assertRaises(self.mod.StateError): self.compare()

    def test_optional_auth_symlink_and_hardlink_are_rejected(self):
        auth = self.actual / 'home/auth.json'
        auth.symlink_to('config.toml')
        with self.assertRaises(self.mod.StateError): self.compare()
        auth.unlink()
        os.link(self.actual / 'home/config.toml', auth)
        with self.assertRaises(self.mod.StateError): self.compare()

    def test_installer_does_not_create_prelogin_auth_state(self):
        tmpfiles = (ROOT / 'hooks/target/etc/tmpfiles.d/80-codex-storage.conf.tmpl').read_text()
        devops = (ROOT / 'scripts/late/devops.sh').read_text()
        self.assertNotIn('__INSTALLER_DEVOPS_CODEX_HOME__/auth.json', tmpfiles)
        self.assertNotIn('__INSTALLER_DEVOPS_CODEX_ROOT__/credentials/auth.json', tmpfiles)
        self.assertNotRegex(devops, r'candidate_home_path[^\n]*auth\.json')
        self.assertNotIn('$codex_root/credentials/auth.json', devops)
        self.assertIn(
            'Codex app-server unit must not require or overmount pre-login auth.json state',
            devops,
        )
        self.assertNotIn('does not bind its auth credential over CODEX_HOME/auth.json', devops)

    def test_missing_packages_tmpfiles_rule_regression(self):
        text = (ROOT / 'hooks/target/etc/tmpfiles.d/80-codex-storage.conf.tmpl').read_text()
        self.assertIn('L __INSTALLER_DEVOPS_CODEX_HOME__/packages ', text)


class StorageSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='disk-safety-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for p in ('sys', 'dev', 'btrfs'): (self.root / p).mkdir()
        for p in ('mounts', 'swaps', 'cmdline'): (self.root / p).touch()
        self.script = (ROOT / 'scripts/partman/detect-disk.sh').read_text().rsplit('\ndetect_disk_main "$@"', 1)[0]
        # Function seams only: production main never accepts substituted /sys.
        self.prefix = self.script + '\ndisk_is_block() { test -f "$1"; }\n'
        for key, value in [('disk_sys_root','sys'),('disk_dev_root','dev'),('disk_btrfs_root','btrfs'),('disk_mounts','mounts'),('disk_swaps','swaps'),('disk_cmdline','cmdline')]:
            self.prefix += f'{key}={Q(str(self.root/value))}\n'

    def disk(self, name='nvme0n1', removable='0', logical='4096'):
        dev = self.root / 'dev' / name; dev.touch()
        base = self.root / 'sys' / name; (base / 'queue').mkdir(parents=True)
        for name, val in [('removable',removable),('ro','0'),('size','100000000'),('dev','259:0'),('queue/logical_block_size',logical)]:
            (base / name).write_text(val+'\n')
        return dev

    def run_disk(self, command): return shell(self.prefix+command)

    def test_4kn_capacity_is_not_multiplied_by_eight(self):
        dev = self.disk(); result = self.run_disk(f'disk_identity {Q(str(dev))}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.split()[0]), 64)
        self.assertEqual((self.root/'sys/nvme0n1/size').read_text().strip(), '100000000')

    def test_removable_installer_is_rejected_even_when_explicit(self):
        dev = self.disk('sda', '1'); result = self.run_disk(f'disk_canonical {Q(str(dev))}')
        self.assertNotEqual(result.returncode, 0)

    def test_nonremovable_mounted_installer_partition_is_rejected(self):
        dev = self.disk('sda')
        part = self.root/'sys/sda/sda1'; part.mkdir(); (part/'partition').write_text('1\n')
        (self.root/'sys/sda1').symlink_to(part, target_is_directory=True)
        (self.root/'dev/sda1').touch()
        (self.root/'mounts').write_text(f'{self.root}/dev/sda1 /hd-media vfat rw 0 0\n')
        self.assertNotEqual(self.run_disk(f'disk_canonical {Q(str(dev))}').returncode, 0)

    def test_unmounted_hd_media_cmdline_is_protected(self):
        dev = self.disk('sda'); (self.root/'cmdline').write_text(f'shared/enter_device={dev}\n')
        self.assertNotEqual(self.run_disk(f'disk_canonical {Q(str(dev))}').returncode, 0)

    def test_malformed_geometry_fails(self):
        dev = self.disk(logical='0')
        self.assertNotEqual(self.run_disk(f'disk_canonical {Q(str(dev))}').returncode, 0)


    def test_ambiguous_auto_selection_fails_instead_of_guessing(self):
        one=self.disk('sda'); two=self.disk('sdb')
        result=self.run_disk(f'INSTALL_DISK_CANDIDATES={Q(str(one)+" "+str(two))}; detect_disk_select')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('ambiguous',result.stderr)

    def test_explicit_unsafe_override_never_falls_back(self):
        bad=self.disk('sda','1'); good=self.disk('sdb')
        result=self.run_disk(f'DEV_INSTALL_DISK={Q(str(bad))}; INSTALL_DISK_CANDIDATES={Q(str(good))}; detect_disk_select')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn(str(good),result.stdout)


class DispatchAndPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='installer-publication-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_actual_late_dispatch_returns_child_status_not_later_success(self):
        runtime = self.root / 'runtime'; (runtime/'bootstrap').mkdir(parents=True)
        boot = runtime/'bootstrap/bootstrap.sh'
        boot.write_text(r"""bootstrap_source_common_lib() { :; }
installer_init_log_file() { :; }
installer_runtime_log_file() { echo /dev/null; }
installer_finalize_log() { echo "final=$1"; }
installer_seed_base() { echo fixture; }
installer_ensure_context_loaded() { INSTALLER_HOOK_FAMILY=vm; }
installer_resolve_host_profile() { echo fixture; }
installer_repo_join_var() { echo "$*"; }
installer_selected_class_reference_is_selected() { return 1; }
installer_fetch_file() {
 case "$3" in
 */shared-late.sh) printf 'run_btrfs_family_late_command() { exit 43; }\n' >"$3" ;;
 *) : >"$3" ;;
 esac
}
""")
        result = subprocess.run(['/bin/sh', str(ROOT/'scripts/late/dispatch.sh')],
                                env={**os.environ, 'INSTALLER_RUNTIME_DIR': str(runtime)},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 43, result.stderr)
        self.assertIn('final=43', result.stdout)
        self.assertFalse((runtime/'bootstrap/role-late.sh').exists())

    def test_virtual_and_versioned_pkgsel_status_detection(self):
        text = (ROOT/'scripts/late/storage-maintenance.sh').read_text()
        start = text.index("/bin/sh -c '\nset -eu\n") + len("/bin/sh -c '")
        end = text.index("' sh \"${INSTALLER_PKGSEL_INCLUDE}\"", start)
        child = text[start:end].replace("'\\''", "'")
        bindir = self.root/'bin'; bindir.mkdir()
        dpkg = bindir/'dpkg-query'
        dpkg.write_text('#!/bin/sh\nprintf "install ok installed\\tmesa-utils\\tmesa-utils-extra\\t9.0\\ninstall ok installed\\tpython3\\t\\t3.13\\n"\n')
        dpkg.chmod(0o755)
        result = subprocess.run(['/bin/sh','-eu','-c',child,'sh','mesa-utils-extra python3=3.13 python3=3.14 absent/trixie'],
                                env={**os.environ,'PATH':str(bindir)+':'+os.environ['PATH']}, capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['python3=3.14','absent/trixie'])

    @unittest.skipUnless(os.geteuid() == 0, 'production ownership contract requires root in this private fixture')
    def test_real_codex_publication_rolls_back_only_current_invocation(self):
        text = (ROOT/'scripts/late/devops.sh').read_text()
        start = text.index('devops_install_pinned_codex()')
        a = text.index('publication_committed=0',start)
        b = text.index('staging_dir=$(mktemp',a)
        setup = text[a:b].replace("'\"'\"'", "'")
        a = text.index('publish_binary_directory=0',b)
        b = text.index('\n[ -x "$binary_path" ]',a)
        publication = text[a:b]
        for fail in (0,1,2,3,4,5):
            with self.subTest(fail_at_rename=fail):
                root=self.root/str(fail); root.mkdir()
                codex=root/'codex'; (codex/'share/bin').mkdir(parents=True)
                (codex/'share/bin').chmod(0o755)
                unrelated=codex/'retain'; unrelated.write_text('external state')
                stage=root/'stage'; stage.mkdir()
                paths={'codex_root':codex, 'staging_dir':stage, 'config_staging':stage/'config',
                       'schema_path':codex/'schema', 'user_root':codex/'usr',
                       'system_config_dir':root/'config', 'archive_helper_path':root/'helper1',
                       'state_helper_path':root/'helper2', 'extracted_binary_dir':stage/'bin',
                       'extracted_schema_path':stage/'schema', 'repository_staging':stage/'usr',
                       'candidate_release_marker':stage/'release'}
                for name in ('config_staging','extracted_binary_dir','repository_staging'):
                    paths[name].mkdir(); (paths[name]/'payload').write_text('pinned')
                for name in ('extracted_schema_path','candidate_release_marker'): paths[name].write_text('pinned')
                env='\n'.join(f'{key}={Q(str(value))}' for key,value in paths.items())+'\n'
                code=env+setup+f"""
moves=0
mv() {{ moves=$((moves+1)); [ "$moves" -ne {fail} ] || return 71; command mv "$@"; }}
codex_fatal() {{ exit 71; }}
codex_tree_matches() {{ diff -r "$1" "$2" >/dev/null; }}
codex_file_matches() {{ cmp -s "$1" "$2"; }}
"""+publication+'\npublication_committed=1\n'
                result=shell(code)
                self.assertEqual(result.returncode,0 if fail==0 else 71,result.stderr)
                self.assertEqual(unrelated.read_text(),'external state')
                self.assertEqual((codex/'.managed-codex-release').exists(),fail==0)
                if fail:
                    self.assertFalse(paths['user_root'].exists())
                    self.assertFalse(paths['schema_path'].exists())
                    self.assertTrue((codex/'share/bin').is_dir())


class ConfigurationOrderingTests(unittest.TestCase):
    def test_crowdsec_target_package_checks_preserve_dpkg_status_format(self):
        source = (ROOT / 'scripts/late/crowdsec.sh').read_text()
        cases = (
            ('verify CrowdSec engine before bouncer enrollment',
             'crowdsec', '/etc/crowdsec/config.yaml'),
            ('validate CrowdSec bouncer package configuration',
             'crowdsec-firewall-bouncer-nftables',
             '/etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml'),
        )
        with tempfile.TemporaryDirectory(prefix='crowdsec-target-check-') as tmp:
            root = Path(tmp)
            bindir = root / 'bin'
            bindir.mkdir()
            commands = {
                'dpkg-query': r'''#!/bin/sh
[ "$1" = -W ] && [ "$2" = '-f=${Status}' ] && [ "$3" = "$EXPECTED_PACKAGE" ] || exit 81
printf '%s' 'install ok installed'
''',
                'cscli': r'''#!/bin/sh
[ "$*" = 'config show --key Config.Common.LogMedia -o raw' ] || exit 82
''',
                'stat': r'''#!/bin/sh
[ "$1" = -c ] && [ "$2" = %h ] && [ "$3" = "$EXPECTED_CONFIG" ] || exit 83
printf '%s\n' 1
''',
                'chown': r'''#!/bin/sh
[ "$1" = root:root ] && [ "$2" = "$EXPECTED_CONFIG" ] || exit 84
''',
                'chmod': r'''#!/bin/sh
[ "$1" = 0600 ] && [ "$2" = "$EXPECTED_CONFIG" ] || exit 85
''',
            }
            for name, command in commands.items():
                path = bindir / name
                path.write_text(command)
                path.chmod(0o755)

            shells = (('/bin/sh',),)
            if busybox := shutil.which('busybox'):
                shells += ((busybox, 'sh'),)
            for index, (label, package, target_config) in enumerate(cases):
                config = root / f'config-{index}.yaml'
                config.write_text('fixture: true\n')
                start = f'run_in_target "{label}" /bin/sh -eu -c \'\n'
                program = source.split(start, 1)[1].split("\n' sh", 1)[0]
                program = program.replace(target_config, str(config))
                env = {**os.environ, 'PATH': f'{bindir}:/usr/bin:/bin',
                       'EXPECTED_PACKAGE': package, 'EXPECTED_CONFIG': str(config)}
                for shell_command in shells:
                    with self.subTest(label=label, shell=shell_command):
                        result = subprocess.run([*shell_command, '-eu', '-c', program],
                                                env=env, capture_output=True,
                                                text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)

    def test_crowdsec_engine_config_precedes_bouncer_install(self):
        cfg = (ROOT/'classes/class-addon/crowdsec.cfg').read_text()
        self.assertNotIn('crowdsec-firewall-bouncer-nftables', '\n'.join(l for l in cfg.splitlines() if l.startswith('d-i pkgsel/include')))
        text = (ROOT/'scripts/late/crowdsec.sh').read_text()
        self.assertLess(text.index('cscli config show'), text.index('install crowdsec-firewall-bouncer-nftables'))
        helper = (ROOT/'hooks/target/usr/local/libexec/crowdsec-firstboot').read_text()
        self.assertNotIn('bouncers add', helper)
        self.assertIn('crowdsec-bouncer-verify', helper)
        unit = (ROOT/'hooks/target/etc/systemd/system/crowdsec-firstboot.service').read_text()
        self.assertIn('StartLimitIntervalSec=infinity', unit)
        self.assertIn('StartLimitBurst=3', unit)

    def test_mullvad_offline_validation_and_runtime_activation_are_distinct(self):
        text = (ROOT/'scripts/late/mullvad.sh').read_text()
        self.assertIn('--skip-kernel-load --skip-cache', text)
        self.assertIn('cmp ', text)
        unit = (ROOT/'hooks/target/etc/systemd/system/mullvad-apparmor.service').read_text()
        self.assertIn('apparmor_parser --replace --skip-cache', unit)
        dep = (ROOT/'hooks/target/etc/systemd/system/mullvad-daemon.service.d/10-apparmor.conf').read_text()
        self.assertIn('Requires=mullvad-apparmor.service', dep)

    def test_network_fetch_has_wall_clock_bound_and_never_disables_tls(self):
        text = (ROOT/'scripts/common/source.sh').read_text()
        self.assertIn('installer_run_bounded "$wall_timeout"', text)
        self.assertIn('for attempt in 1 2 3', text)
        self.assertNotIn('set -- "$@" --no-check-certificate', text)
        self.assertIn('bypass is forbidden', text)

    def test_normalization_and_validation_precede_unmount(self):
        text = (ROOT/'hooks/installer/d-i/early.sh').read_text()
        self.assertIn('94zz-10-normalize-apt', text)
        self.assertIn('94zz-20-normalize-finish', text)
        self.assertIn('94zz-99-validate-target', text)
        self.assertTrue('94zz-99-validate-target' < '95umount')


class FinalBootValidationTests(unittest.TestCase):
    def test_amd64_skipped_installer_kernel_does_not_generate_orphan_initrd(self):
        source=(ROOT/'classes/class-auto/arch/amd64.cfg').read_text()
        self.assertIn('d-i base-installer/kernel/skip-install boolean true\n',source)
        self.assertIn('d-i base-installer/kernel/image select none\n',source)
        self.assertIn('d-i base-installer/kernel/linux/initrd boolean false\n',source)
        self.assertNotIn('d-i base-installer/kernel/linux/initrd boolean true\n',source)

    def test_mok_enrollment_queue_keeps_entry_id_inside_target_shell(self):
        source = ROOT / 'scripts/late/grub.sh'
        result = shell(f'''\
. {Q(str(source))}
run_in_target() {{
  [ "$#" -eq 8 ] || exit 91
  [ "$1" = "queue one-shot GRUB boot into MokManager" ] || exit 92
  [ "$2" = /bin/sh ] || exit 93
  [ "$3" = -c ] || exit 94
  [ "$5" = sh ] || exit 95
  [ "$6" = installer-mok-enrollment ] || exit 96
  [ "$7" = /EFI/debian/mmx64.efi ] || exit 97
  [ "$8" = /boot/efi/EFI/debian/MOK.der ] || exit 98
  printf "%s\n" "$4"
}}
INSTALLER_GRUB_MOK_MANAGER_EFI_PATH=/EFI/debian/mmx64.efi
FILE_SECURE_BOOT_MOK_CERT_DER_ESP=/boot/efi/EFI/debian/MOK.der
queue_target_grub_mok_enrollment_boot
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('mok_entry_id=$1', result.stdout)
        self.assertIn('grep -F -q -- "$mok_entry_marker" "$grub_cfg"', result.stdout)

    def test_signature_listing_requires_a_signature_not_just_zero_exit(self):
        source=(ROOT/'hooks/installer/finish-install.d/94zz-99-validate-target').read_text()
        body=source[source.index('require_signature() {'):].split('\n}',1)[0]+'\n}\n'
        for listing,status in [('No signature table present',1),('signature 1',0)]:
            result=shell(body+'sbverify() { printf "%s\\n" '+Q(listing)+'; }\nrequire_signature fixture')
            self.assertEqual(result.returncode,status,result.stderr)

    def test_missing_debian_kernel_initrd_is_rebuilt_even_without_module_changes(self):
        source=(ROOT/'hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl').read_text()
        body=source[source.index('repair_kernel() {'):].split('\n}',1)[0]+'\n}\n'
        with tempfile.TemporaryDirectory(prefix='boot-repair-') as tmp:
            root=Path(tmp); (root/'boot').mkdir(); (root/'lib/modules/fixture').mkdir(parents=True)
            (root/'boot/vmlinuz-fixture').write_text('signed fixture')
            body=body.replace('/boot/',str(root)+'/boot/').replace('/lib/modules/',str(root)+'/lib/modules/')
            result=shell(body+f"""
log() {{ :; }}
fatal() {{ exit 1; }}
sign_modules_for_kernel() {{ SIGN_MODULES_CHANGED=0; }}
kernel_image_has_debian_signature() {{ return 0; }}
refresh_initramfs_for_kernel() {{ printf initrd >{Q(str(root/'boot/initrd.img-fixture'))}; }}
cleanup_kernel_artifacts() {{ :; }}
repair_kernel fixture
""")
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((root/'boot/initrd.img-fixture').read_text(),'initrd')

    def test_actual_arm64_cpu_detection_does_not_require_x86_vendor(self):
        source=(ROOT/'scripts/preseed/class-auto.sh').read_text().rsplit('case "${1:-report}" in',1)[0]
        result=shell(source+'arch_raw() { printf aarch64; }\ncpu_vendor() { printf 0x41; }\ncpu_class')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'generic-arm64')


if __name__ == '__main__': unittest.main()
