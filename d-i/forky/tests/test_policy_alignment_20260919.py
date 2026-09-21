"""Focused desktop, numeric asset and effective CPU-family GRUB invariants."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import test_hardware_restore as hardware

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'


class PolicyAlignmentTests(unittest.TestCase):
    def test_switcher_rgb_matches_waybar_without_losing_alpha(self):
        css = (TARGET / 'etc/skel-desktop/.config/waybar/style.css.tmpl').read_text()
        rgb = re.search(r'@define-color\s+emeraldgreen\s+(#[A-Fa-f0-9]{6});', css)[1]
        self.assertEqual(rgb.upper(), '#50C878')
        block = re.search(r'^#custom-window-switcher \{([^}]+)\}', css, re.M)[1]
        self.assertIn('@emeraldgreen', block)
        theme = (TARGET / 'etc/skel-desktop/.config/labwc/themerc-override').read_text()
        values = dict(line.split(': ', 1) for line in theme.splitlines() if ': ' in line and not line.startswith('#'))
        self.assertEqual(values['osd.window-switcher.style-thumbnail.item.active.border.color'].upper(), rgb.upper())
        background = values['osd.window-switcher.style-thumbnail.item.active.bg.color']
        self.assertEqual(background[:7].upper(), rgb.upper()); self.assertEqual(background[7:], '26')
        self.assertEqual(values['osd.window-switcher.preview.border.color'].upper(), f'{rgb},#0c1017,{rgb}'.upper())

    def test_exact_numeric_modprobe_set_and_references_exist(self):
        expected = set('05-mei-blacklist 10-net-proto-blacklist 20-virtualization-blacklist 30-legacy-bus-blacklist 40-filesystem-blacklist 50-nouveau-blacklist 60-ses-blacklist 70-vfio-pci 71-thunderbolt 72-nvme-blacklist 73-nvme 74-usbcore 75-cfg80211 76-iwlwifi 77-e1000e 78-snd-hda-intel 79-thinkpad-acpi 79-ideapad-acpi 79-chromebook 80-i915 81-amdgpu 82-nvidia 90-zram'.split())
        directory = TARGET / 'etc/modprobe.d'
        self.assertEqual({p.stem for p in directory.glob('*.conf')}, expected)
        for path in directory.glob('*.conf'):
            self.assertRegex(path.name, r'^[0-9]{2}-[a-z0-9][a-z0-9.-]*\.conf$')
        for line in (FORKY / 'classes/configs/target-assets.tsv').read_text().splitlines():
            if not line or line.startswith('#'): continue
            group, kind, destination, source = line.split('\t')
            self.assertTrue((TARGET / source).is_file(), source)
            if '/modprobe.d/' in destination:
                self.assertEqual(Path(destination).name, Path(source).name)
                self.assertIn(Path(source).stem, expected)
        runtime = (FORKY / 'hosts/installer/runtime.env').read_text()
        paths = re.findall(r'^FILE_MODPROBE_[A-Z0-9_]+="\$\{DIR_MODPROBE_D\}/([^"\n]+)"', runtime, re.M)
        self.assertGreaterEqual(len(paths), 14)
        for name in paths: self.assertTrue((directory / name).is_file(), name)

    def test_grub_pcie_usb_effective_tokens_once(self):
        result = subprocess.run(['/bin/sh', '-eu', '-c', 'GRUB_CMDLINE_LINUX=sentinel; . "$1"; printf "%s\\n" "$GRUB_CMDLINE_LINUX"', 'test', str(TARGET / 'etc/default/grub.d/73-pcie-power.cfg')], capture_output=True, text=True, check=True)
        tokens = result.stdout.split()
        for token in ('sentinel', 'pcie_aspm.policy=powersave', 'pcie_ports=native', 'usbcore.autosuspend=2'):
            self.assertEqual(tokens.count(token), 1)
        for token in ('pcie_aspm=off', 'pcie_port_pm=off', 'usbcore.autosuspend=-1'):
            self.assertNotIn(token, tokens)

    def test_thunderbolt_and_usb_have_one_effective_directive(self):
        for name, expected in (('71-thunderbolt.conf', 'options thunderbolt xdomain=0 clx=1'), ('74-usbcore.conf', 'options usbcore autosuspend=2')):
            lines = [line.strip() for line in (TARGET / 'etc/modprobe.d' / name).read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
            self.assertEqual(lines, [expected])

    def test_profile_font_pins_and_architecture_neutral_boot_flags(self):
        for path in (FORKY / 'hosts/profiles').glob('*.env'):
            text = path.read_text()
            for prefix, name, sha in (('APTOS', 'MicrosoftAptosFonts', '54f4cae474cfa96dfb30f9f39fa947959bb2fbda40aea46420299f22ff7c12aa'), ('MICROSOFT', 'MicrosoftLocalFonts', 'c37f2ebeca338f0c35c19957fa0671ecdeb7ea2a8a58397e963f22c87ce32c6a')):
                self.assertIn(f'LABWC_FONT_{prefix}_URL="https://github.com/mjcramerz/fonts/releases/download/microsoft-fonts-v0.0.1/{name}.tar.xz"', text)
                self.assertIn(f'LABWC_FONT_{prefix}_SHA256="{sha}"', text)
            for flags in re.findall(r'^GRUB_PROFILE_(?:DEFAULT|HARDENED|PERFORMANCE)_FLAGS="([^"]*)"', text, re.M):
                self.assertNotIn('cpufreq.default_governor=', flags)

    def test_actual_grub_generator_keeps_family_governors_and_iommu(self):
        for family in ('intel', 'amd', 'generic-arm64', 'vm'):
            fixture = hardware.GrubGeneratorTests(); fixture.setUp()
            try:
                fragment = fixture.root / 'etc/default/grub.d/80-cpu-profile-flags.cfg'
                if family == 'vm': fragment.unlink()
                else: shutil.copyfile(TARGET / f'etc/default/grub.d/80-cpu-profile-flags.{family}.cfg', fragment)
                profile_name = 'btrfs-de' if family == 'vm' else 'btrfs-de-flex'
                data = (FORKY / f'hosts/profiles/{profile_name}.env').read_text()
                for index, label in ((17, 'DEFAULT'), (18, 'PERFORMANCE'), (19, 'HARDENED')):
                    fixture.args[index] = re.search(r'^GRUB_PROFILE_' + label + r'_FLAGS="([^"]*)"', data, re.M)[1]
                result = fixture.invoke(install=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = (fixture.root / 'boot/grub/custom.cfg').read_text()
                lines = [line.split() for line in output.splitlines() if line.strip().startswith('linux ')]
                self.assertEqual(len(lines), 4)
                for line in lines:
                    governors = [t for t in line if t.startswith('cpufreq.default_governor=')]
                    self.assertLessEqual(len(governors), 1)
                    self.assertFalse('intel_pstate=active' in line and 'cpufreq.default_governor=schedutil' in line)
                # The rescue entry precedes Default, Performance, Hardened.
                expected = ('powersave', 'powersave', 'schedutil') if family == 'intel' else ('schedutil', 'performance', 'powersave')
                for line, governor in zip(lines[1:], expected):
                    if family == 'vm': self.assertFalse(any(t.startswith('cpufreq.default_governor=') for t in line))
                    else: self.assertIn('cpufreq.default_governor=' + governor, line)
                if family == 'intel':
                    self.assertIn('intel_iommu=on', lines[1]); self.assertIn('iommu.strict=1', lines[1])
                    self.assertIn('iommu=pt', lines[2]); self.assertIn('iommu.strict=0', lines[2])
                    self.assertIn('intel_pstate=passive', lines[3])
            finally: fixture.doCleanups()


if __name__ == '__main__': unittest.main()
