#!/usr/bin/env python3
"""Hardware selection, actual asset publication, block rendering and GRUB tests.

No kernel modules are loaded. Destructive late stages and vendor activation
are not run; target publication and GRUB generation use disposable roots.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
os.environ["INSTALLER_SOURCE_LIBRARY"] = str(FORKY / "scripts/common/source.sh")
HARDWARE = FORKY / 'hooks/target'
SHARED = FORKY / 'hooks/target'
REQUESTED = {
    'etc/default/grub.d/75-intel-vfio.cfg': 'vfio-pci.ids=8086:02e0',
    'etc/default/grub.d/80-cpu-profile-flags.intel.cfg': 'iommu.strict=1',
    'etc/modprobe.d/cfg80211.conf': 'ieee80211_regdom=SE',
    'etc/modprobe.d/e1000e.conf': 'InterruptThrottleRate=3000 RxIntDelay=0 TxIntDelay=0',
    'etc/modprobe.d/thinkpad-acpi.conf': 'fan_control=1 brightness_enable=1',
    'etc/modprobe.d/thunderbolt.conf': 'options thunderbolt clx=0',
    'etc/modprobe.d/vfio-pci.conf': 'ids=8086:02e0',
    'etc/modules-load.d/35-vfio.conf': 'vfio_pci',
    'etc/udev/rules.d/85-wifi-regdom.rules': '/usr/sbin/iw reg set SE',
    'etc/default/grub.d/72-nvme-platform.cfg': 'nvme_core.default_ps_max_latency_us=3200',
    'etc/default/grub.d/73-pcie-power.cfg': 'pcie_aspm=off pcie_port_pm=off usbcore.autosuspend=-1',
    'etc/initramfs-tools/modules.nvme.tmpl': 'xxhash_generic',
    'etc/modprobe.d/nvme.conf': 'default_ps_max_latency_us=3200 io_timeout=30',
    'etc/modprobe.d/usbcore.conf': 'autosuspend=-1',
    'etc/modules-load.d/10-btrfs.nvme.conf': 'xxhash_generic',
    'etc/default/grub.d/87-gpu-nvidia.cfg': 'pci=realloc=on',
    'etc/modprobe.d/nvidia.conf': 'NVreg_PreserveVideoMemoryAllocations=1',
}


# Payload sources are independent of installed paths.
DESTINATIONS = {'etc/default/grub.d/75-intel-vfio.cfg': 'etc/default/grub.d/75-intel-vfio.cfg', 'etc/default/grub.d/80-cpu-profile-flags.intel.cfg': 'etc/default/grub.d/80-cpu-profile-flags.cfg', 'etc/modprobe.d/cfg80211.conf': 'etc/modprobe.d/cfg80211.conf', 'etc/modprobe.d/e1000e.conf': 'etc/modprobe.d/e1000e.conf', 'etc/modprobe.d/thinkpad-acpi.conf': 'etc/modprobe.d/thinkpad-acpi.conf', 'etc/modprobe.d/thunderbolt.conf': 'etc/modprobe.d/thunderbolt.conf', 'etc/modprobe.d/vfio-pci.conf': 'etc/modprobe.d/vfio-pci.conf', 'etc/modules-load.d/35-vfio.conf': 'etc/modules-load.d/35-vfio.conf', 'etc/udev/rules.d/85-wifi-regdom.rules': 'etc/udev/rules.d/85-wifi-regdom.rules', 'etc/default/grub.d/72-nvme-platform.cfg': 'etc/default/grub.d/72-nvme-platform.cfg', 'etc/default/grub.d/73-pcie-power.cfg': 'etc/default/grub.d/73-pcie-power.cfg', 'etc/initramfs-tools/modules.nvme.tmpl': 'etc/initramfs-tools/modules', 'etc/modprobe.d/nvme.conf': 'etc/modprobe.d/nvme.conf', 'etc/modprobe.d/usbcore.conf': 'etc/modprobe.d/usbcore.conf', 'etc/modules-load.d/10-btrfs.nvme.conf': 'etc/modules-load.d/10-btrfs.conf', 'etc/default/grub.d/87-gpu-nvidia.cfg': 'etc/default/grub.d/87-gpu-nvidia.cfg', 'etc/modprobe.d/nvidia.conf': 'etc/modprobe.d/nvidia.conf'}


def active(text: str) -> str:
    return '\n'.join(x for x in text.splitlines() if x.strip() and not x.lstrip().startswith('#'))


def run_shell(code: str, env=None):
    return subprocess.run(['/bin/sh', '-e', '-c', code], capture_output=True, text=True,
                          env=env, timeout=30)


def copy_binary(root: Path, binary: str, destination=None):
    path = Path(binary)
    dependencies = subprocess.run(['ldd', str(path)], capture_output=True, text=True, timeout=5)
    entries = [(path, Path(destination or str(path)).relative_to('/'))]
    for name in re.findall(r'(/[^\s()]+)', dependencies.stdout):
        if Path(name).is_file():
            entries.append((Path(name), Path(name).relative_to('/')))
    for source, relative in entries:
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        dest.chmod(0o755)


def make_chroot(root: Path):
    copy_binary(root, shutil.which('busybox'), '/bin/busybox')
    for name in ('sh', 'sed', 'head', 'tr', 'readlink', 'sort', 'stat', 'cat', 'chmod',
                 'mkdir', 'install', 'mktemp', 'rm', 'dirname'):
        (root / 'bin' / name).symlink_to('busybox')
    for directory in ('dev', 'tmp', 'etc/default/grub.d', 'etc/grub.d', 'boot/grub'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / 'tmp').chmod(0o1777)
    (root / 'dev/null').touch()
    (root / 'bin/blkid').write_text('#!/bin/sh\nprintf "fixture-uuid\\n"\n')
    (root / 'bin/blkid').chmod(0o755)


class HardwareFilesTests(unittest.TestCase):
    def test_all_seventeen_files_have_active_settings(self):
        self.assertEqual(len(REQUESTED), 17)
        for relative, expected in REQUESTED.items():
            with self.subTest(file=relative):
                self.assertIn(expected, active((HARDWARE / relative).read_text()))

    def test_vfio_never_enables_unsafe_noiommu(self):
        for name in ('default/grub.d/75-intel-vfio.cfg', 'modprobe.d/vfio-pci.conf'):
            text = active((HARDWARE / 'etc' / name).read_text())
            self.assertNotIn('enable_unsafe_noiommu_mode=1', text)
            self.assertNotIn('allow_unsafe_interrupts=1', text)

    def test_regdom_and_required_package_agree(self):
        self.assertIn(' iw ', (FORKY / 'classes/class-auto/cpu/intel.cfg').read_text())
        self.assertIn('wireless-regdb', (FORKY / 'fragments/apt.cfg').read_text())
        self.assertIn('reg set SE', (HARDWARE / 'etc/udev/rules.d/85-wifi-regdom.rules').read_text())

    def test_canonical_hash_module_in_both_boot_paths(self):
        for name in ('initramfs-tools/modules.tmpl', 'modules-load.d/10-btrfs.conf'):
            text = active((HARDWARE / 'etc' / name.replace('modules.tmpl', 'modules.nvme.tmpl').replace('10-btrfs.conf', '10-btrfs.nvme.conf')).read_text())
            self.assertEqual(text.splitlines().count('xxhash_generic'), 1)
            self.assertNotIn('\nxxhash64_generic\n', '\n' + text + '\n')
            self.assertLess(text.index('xxhash_generic'), text.index('btrfs'))

    def test_nvidia_false_branch_removes_only_target_assets(self):
        for family in ('btrfs-family.sh', 'f2fs-family.sh'):
            text = (FORKY / 'scripts/late' / family).read_text()
            self.assertIn('remove_target_asset "${DIR_MODPROBE_D}/nvidia.conf"', text)
            self.assertNotIn('rm -f \\\n      "${DIR_MODPROBE_D}/50-nouveau-blacklist.conf"', text)


class SelectionTests(unittest.TestCase):
    def preamble(self, cpu='intel', disk='nvme', family='btrfs', nvidia=True):
        q = shlex.quote
        return f'''
BOOTPROFILE_DEFAULT=balanced; BOOTPROFILE_HARDENED=hardened; BOOTPROFILE_PERFORMANCE=performance
INSTALLER_SOURCE_ROOT={q(str(FORKY))}
. {q(str(FORKY / 'hosts/installer/runtime.env'))}
. {q(str(FORKY / 'scripts/common/lib.sh'))}
. {q(str(FORKY / 'scripts/common/target.sh'))}
. {q(str(FORKY / 'scripts/late/target-assets.sh'))}
. {q(str(FORKY / 'scripts/late/grub.sh'))}
. {q(str(FORKY / 'scripts/late/core.sh'))}
. {q(str(FORKY / 'scripts/late/btrfs-family.sh'))}
installer_fatal() {{ printf 'fatal: %s\\n' "$*" >&2; exit 1; }}
CPU_CLASS={cpu}; DISK_CLASS={disk}; HOOK_FAMILY={family}; GPU_CLASSES=generic
NVIDIA_ADDON_SELECTED={'true' if nvidia else 'false'}; NVIDIA_GPU_DETECTED={'true' if nvidia else 'false'}
select_btrfs_hardware_policy
'''

    def policy(self, **kwargs):
        result = run_shell(self.preamble(**kwargs) + '''
printf 'vfio=%s\nnvme=%s\nnvidia=%s\nmodules=%s\n' "$FILE_MODPROBE_VFIO" "$FILE_MODPROBE_NVME_OPTS" "$FILE_MODPROBE_NVIDIA" "$VFIO_INITRAMFS_MODULES"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_intel_nvme_enables_entire_vfio_chain(self):
        text = self.policy()
        self.assertIn('vfio=/etc/modprobe.d/vfio-pci.conf', text)
        self.assertIn('modules=vfio\nvfio_pci\nvfio_iommu_type1', text)

    def test_amd_nvme_does_not_get_intel_vfio(self):
        text = self.policy(cpu='amd')
        self.assertIn('vfio=\n', text)
        self.assertIn('nvme=/etc/modprobe.d/nvme.conf', text)

    def test_vm_does_not_get_nvme_or_platform_vfio(self):
        text = self.policy(disk='vm', family='vm', nvidia=False)
        self.assertIn('vfio=\n', text)
        self.assertIn('nvme=\n', text)
        self.assertIn('nvidia=\n', text)

    def test_gpu_configuration_is_still_opt_in(self):
        self.assertIn('nvidia=\n', self.policy(nvidia=False))

    def test_mismatched_vm_storage_fails(self):
        result = run_shell(self.preamble(disk='nvme', family='vm'))
        self.assertNotEqual(result.returncode, 0)

    def test_real_staging_publishes_all_seventeen_target_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'target'
            target.mkdir()
            work = Path(temp) / 'work'
            work.mkdir()
            (work / 'swap-fallback.service.tmpl').write_text('[Unit]\nDescription=fixture\n')
            source = (FORKY / 'scripts/late/btrfs-family.sh').read_text()
            function = source[source.index('write_target_kernel_tunables() {'):].split('\n}\n', 1)[0] + '\n}\n'
            q = shlex.quote
            code = self.preamble() + f'''
INSTALLER_TARGET_DIR={q(str(target))}; TMP_ENV_DIR={q(str(work))}
DIR_HOOKS_TARGET={q(str(SHARED))}; INSTALLER_SOURCE_ROOT={q(str(FORKY))}
. {q(str(FORKY / 'scripts/late/target-assets.sh'))}
. {q(str(FORKY / 'scripts/late/templates.sh'))}
installer_repo_join_var() {{ eval 'base=${{'"$1"'}}'; printf '%s/%s\\n' "$base" "$2"; }}
fetch_hook() {{ cp "$1" "$2"; }}
render_target_template_placeholder_map() {{ printf 'CPU_CRC32C_MODULE=%s\\n' "$CPU_CRC32C_MODULE"; }}
apply_tmpfs_policy_placeholders() {{ :; }}
apply_tmpfs_pre_clean_placeholders() {{ :; }}
apply_apt_refresh_placeholders() {{ :; }}
apply_sysctl_profile_placeholders() {{ :; }}
render_target_asset() {{
 case "$1" in
  */etc/initramfs-tools/modules.nvme.tmpl) publish_target_asset "$1" "$2" "$3" template ;;
  *) : ;;
 esac
}}
install_target_bootprofile_assets() {{ :; }}
stage_target_zram_assets() {{ :; }}
write_target_swap_fallback_config() {{ :; }}
stage_target_common_storage_maintenance_assets() {{ :; }}
run_in_target() {{ printf '%s\\n' "$*" >> {q(str(work / 'in-target.log'))}; }}
{function}
# The legacy unrelated swap unit uses a literal /target destination; isolate it.
FILE_SWAP_FALLBACK_SERVICE={q(str(target / 'swap-fixture.service'))}
# Only skip that unrelated direct render; the modules path above uses publication.
render_target_template() (
 case "$1" in
  */swap-fallback.service.tmpl) exit 0 ;;
 esac
 _render_target_template_in_place "$1" "$2" "$3"
)
write_target_kernel_tunables
'''
            result = run_shell(code)
            self.assertEqual(result.returncode, 0, result.stderr)
            for relative, expected in REQUESTED.items():
                destination = DESTINATIONS[relative]
                path = target / destination
                with self.subTest(destination=destination):
                    self.assertTrue(path.is_file(), destination)
                    self.assertIn(expected, active(path.read_text()))
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
                    self.assertNotIn('__INSTALLER_', path.read_text())
            modules = active((target / 'etc/initramfs-tools/modules').read_text()).splitlines()
            for module in ('vfio', 'vfio_pci', 'vfio_iommu_type1', 'nvidia', 'nvidia_modeset',
                           'nvidia_uvm', 'nvidia_drm', 'kvm', 'kvm_intel', 'vhost_net', 'vhost_vsock'):
                self.assertIn(module, modules)
            self.assertIn('enable NVIDIA video-memory preservation', (work / 'in-target.log').read_text())
            self.assertTrue((target / 'usr/local/libexec/nvidia-vram-check').is_file())


class TemplateBlockTests(unittest.TestCase):
    def render(self, content, modules='', scalar_map=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'modules'
            path.write_text(content)
            map_path = Path(temp) / 'map'
            map_path.write_text(scalar_map or '')
            code = f'. {shlex.quote(str(FORKY / "scripts/late/templates.sh"))}\n'
            code += f'VFIO_INITRAMFS_MODULES={shlex.quote(modules)}\n'
            code += f'render_target_module_placeholders {shlex.quote(str(path))}\n'
            if scalar_map is not None:
                code += f'render_target_scalar_placeholders {shlex.quote(str(path))} {shlex.quote(str(map_path))}\n'
            result = run_shell(code)
            return result, path.read_text()

    def test_all_module_lines_survive(self):
        result, text = self.render('before\n__INSTALLER_VFIO_INITRAMFS_MODULES__\nafter\n', 'vfio\nvfio_pci\nvfio_iommu_type1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(text, 'before\nvfio\nvfio_pci\nvfio_iommu_type1\nafter\n')

    def test_empty_block_is_removed(self):
        result, text = self.render('before\n__INSTALLER_VFIO_INITRAMFS_MODULES__\nafter\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(text, 'before\nafter\n')

    def test_duplicate_module_names_are_emitted_once(self):
        result, text = self.render('__VFIO_INITRAMFS_MODULES__\n', 'vfio vfio_pci vfio')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(text, 'vfio\nvfio_pci\n')

    def test_invalid_module_preserves_input_and_fails(self):
        original = '__INSTALLER_VFIO_INITRAMFS_MODULES__\n'
        result, text = self.render(original, 'vfio\n../../bad')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(text, original)

    def test_scalar_values_are_literal_and_not_recursive(self):
        value = r'$HOME & | \a=b __INSTALLER_B__'
        result, text = self.render('__INSTALLER_A__\n', scalar_map=f'A={value}\nB=changed\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(text, value + '\n')

    def test_adjacent_scalar_placeholders(self):
        result, text = self.render('__INSTALLER_A____B__\n', scalar_map='A=left\nB=right\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(text, 'leftright\n')

    def test_malformed_scalar_map_fails(self):
        result, text = self.render('__INSTALLER_A__\n', scalar_map='A=first\naccidental-second-line\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(text, '__INSTALLER_A__\n')


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('busybox') and shutil.which('chroot'),
                     'root and BusyBox chroot required')
class GrubGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_chroot(self.root)
        (self.root / 'boot/vmlinuz-6.12-fixture').touch()
        (self.root / 'boot/initrd.img-6.12-fixture').touch()
        (self.root / 'boot/grub/grubenv').write_text('fixture\n')
        template = (SHARED / 'etc/default/grub-profiles.tmpl').read_text()
        template = template.replace('__INSTALLER_GRUB_MOK_MANAGER_EFI_PATH__', '/EFI/debian/mmx64.efi')
        template = template.replace('__INSTALLER_GRUB_REMOVABLE_BOOT_EFI_PATH__', '/EFI/BOOT/BOOTX64.EFI')
        (self.root / 'generator').write_text(template)
        (self.root / 'generator').chmod(0o755)
        rows = (FORKY / 'classes/configs/target-assets.tsv').read_text().splitlines()
        for row in rows:
            if not row or row.startswith('#'):
                continue
            group, kind, leaf, payload = row.split('\t')
            if (group, kind) in {('cpu', 'intel'), ('disk', 'nvme'), ('gpu', 'nvidia')} and leaf.startswith('etc/default/grub.d/'):
                dest = self.root / leaf
                shutil.copyfile(HARDWARE / payload, dest)
                dest.chmod(0o644)
        self.args = ['/dev/boot', '/dev/root', '/dev/efi', 'balanced', 'performance', 'hardened',
                     'rootfstype=btrfs', 'fsck.mode=auto', '', 'cgroup_no_v1=all',
                     'security=apparmor', '', '', 'slab_nomerge', '', '', '',
                     'mitigations=auto', 'mitigations=auto', 'mitigations=auto',
                     '/mok.der', 'installer-lastboot', '', 'keep', 'false']
        self.assertEqual(len(self.args), 25)

    def invoke(self, install=False):
        return subprocess.run([shutil.which('chroot'), str(self.root), '/bin/sh', '/generator',
                               *(self.args if install else [])], text=True, capture_output=True,
                              env={'PATH': '/bin', 'SKIP_MOK_SIGNING': '1', 'LC_ALL': 'C'}, timeout=10)

    def test_initial_and_regenerated_menu_include_hardware_values(self):
        result = self.invoke(install=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        initial = (self.root / 'boot/grub/custom.cfg').read_text()
        regen = self.invoke()
        self.assertEqual(regen.returncode, 0, regen.stderr)
        self.assertEqual(regen.stdout, initial)
        lines = [x for x in initial.splitlines() if x.strip().startswith('linux ')]
        self.assertEqual(len(lines), 4)
        for line in lines:
            for flag in ('vfio-pci.ids=8086:02e0', 'nvme_core.default_ps_max_latency_us=3200',
                         'pcie_aspm=off', 'usbcore.autosuspend=-1'):
                self.assertIn(flag, line)
        for line in lines[1:]:
            self.assertIn('nvidia-drm.modeset=1', line)
            self.assertIn('pci=realloc=on', line)
        self.assertIn('iommu.passthrough=0', lines[1])
        self.assertIn('iommu=pt', lines[2])

    def test_repeated_regeneration_does_not_accumulate_flags(self):
        self.assertEqual(self.invoke(install=True).returncode, 0)
        first, second = self.invoke(), self.invoke()
        self.assertEqual(first.stdout, second.stdout)
        self.assertNotIn('vfio-pci.ids', (self.root / 'etc/default/grub-profiles.conf').read_text())

    def test_changed_hardware_dropin_takes_effect_without_reinstall(self):
        self.assertEqual(self.invoke(install=True).returncode, 0)
        path = self.root / 'etc/default/grub.d/75-intel-vfio.cfg'
        path.write_text(path.read_text().replace('8086:02e0', '8086:1234'))
        output = self.invoke()
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertIn('8086:1234', output.stdout)
        self.assertNotIn('8086:02e0', output.stdout)

    def test_removed_optional_fragment_is_not_cached(self):
        self.assertEqual(self.invoke(install=True).returncode, 0)
        (self.root / 'etc/default/grub.d/75-intel-vfio.cfg').unlink()
        self.assertNotIn('vfio-pci.ids', self.invoke().stdout)

    def test_writable_hardware_fragment_rejected(self):
        (self.root / 'etc/default/grub.d/75-intel-vfio.cfg').chmod(0o666)
        result = self.invoke(install=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('writable by non-root', result.stderr)

    def test_indirect_hardware_fragment_rejected(self):
        path = self.root / 'etc/default/grub.d/75-intel-vfio.cfg'
        path.unlink()
        path.symlink_to('/generator')
        result = self.invoke(install=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a direct regular file', result.stderr)


if __name__ == '__main__':
    unittest.main()
