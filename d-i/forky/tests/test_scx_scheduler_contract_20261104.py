"""Static SCX loader and DevOps handoff contract.

These tests inspect source and profile data only. They do not import managed
target modules, contact D-Bus or systemd, or execute a scheduler.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / "d-i/forky"
PROFILES = sorted((SEED / "hosts/profiles").glob("*.env"))


class ScxSchedulerContractTests(unittest.TestCase):
    def test_every_profile_uses_loader_on_demand_mode(self):
        self.assertEqual(len(PROFILES), 10)
        for profile in PROFILES:
            text = profile.read_text(encoding="utf-8")
            self.assertIn('HARDWARE_CPU_SCHEDULER_SCX_ENABLE="true"', text)
            self.assertIn('HARDWARE_CPU_SCHEDULER_SCX_MODE="on-demand"', text)
            self.assertNotIn('HARDWARE_CPU_SCHEDULER_SCX_MODE="direct"', text)

    def test_loader_defaults_to_long_running_scheduler(self):
        config = (SEED / "hooks/target/etc/scx_loader/config.toml").read_text(encoding="utf-8")
        self.assertIn('default_sched = "scx_rusty"', config)
        self.assertIn('default_mode = "Auto"', config)

    def test_on_demand_stages_loader_as_the_only_boot_backend(self):
        source = (SEED / "scripts/desktop/scx-scheds.sh").read_text(encoding="utf-8")
        self.assertIn("desktop_disable_unit_if_available scx.service system", source)
        self.assertIn("desktop_enable_unit_if_available scx_loader.service system", source)
        self.assertIn("desktop_disable_unit_if_available scx_loader.service system", source)
        self.assertIn("desktop_enable_unit_if_available scx.service system", source)
        self.assertIn("/usr/bin/scx_rusty", source)
        self.assertIn("/usr/bin/scx_flash", source)

    def test_devops_handoff_is_bounded_and_idempotent(self):
        source = (SEED / "hooks/target/etc/skel-desktop/.profile.d/71-devops-de.sh").read_text(encoding="utf-8")
        self.assertIn("devops_de_select_scx_scheduler()", source)
        self.assertIn("/usr/bin/scxctl get", source)
        self.assertIn("/usr/bin/scxctl start --sched scx_flash --mode auto", source)
        self.assertIn("/usr/bin/scxctl switch --sched scx_flash --mode auto", source)
        self.assertIn('"running Flash"|"running Flash "*)', source)
        self.assertIn("--kill-after=2s 10s", source)
        self.assertIn("the shell remains usable", source)


if __name__ == "__main__":
    unittest.main()
