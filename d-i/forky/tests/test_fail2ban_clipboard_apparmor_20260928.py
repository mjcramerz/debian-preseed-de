"""Installer wiring for the supplied fail2ban, Cage, and AppArmor failures."""

from __future__ import annotations

import configparser
import os
from pathlib import Path
import subprocess
import unittest


SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / "hooks/target"
FAIL2BAN = TARGET / "etc/fail2ban"


class Fail2banPolicyTests(unittest.TestCase):
    def test_ssh_monitor_is_enabled_independently_of_ssh_addon(self):
        config = (FAIL2BAN / "jail.d/10-sshd.local.tmpl").read_text()
        installer = (SEED / "scripts/late/security.sh").read_text()
        renderer = installer.split("fail2ban_jail_placeholder_map() {", 1)[1].split("\n}", 1)[0]
        stage = installer.split("configure_target_fail2ban() {", 1)[1].split(
            "\nconfigure_target_apparmor_auditd()", 1
        )[0]
        self.assertIn("enabled = true", config)
        self.assertIn("render_target_asset_with_placeholder_map", stage)
        self.assertNotIn("SSH_SERVER_ENABLED", renderer)
        self.assertNotIn("SSH_SERVER_ENABLED", stage)
        self.assertNotIn("SSHD_JAIL_ENABLED", installer + config)
        self.assertIn("stage_target_systemd_unit_enabled fail2ban.service system", stage)
        self.assertNotIn("unstage_target_systemd_unit_enabled fail2ban.service", stage)
        parsed = configparser.RawConfigParser()
        parsed.read_string("[sshd]\nenabled = false\n")
        parsed.read_string(config.replace("__INSTALLER_SSH_PORT__", "2222"))
        self.assertTrue(parsed.getboolean("sshd", "enabled"))
        self.assertEqual(parsed.get("sshd", "port"), "2222")

    def test_port_renderer_uses_default_and_cmdline_port_without_class_gate(self):
        script = r"""
set -eu
. "$1"
. "$2"
runtime_cmdline_value() {
  [ "$1" = ssh_port ] && [ -n "${TEST_SSH_PORT:-}" ] || return 1
  printf '%s\n' "$TEST_SSH_PORT"
}
runtime_require_positive_integer() {
  case "$2" in ''|*[!0-9]*) return 1 ;; esac
  [ "$2" -gt 0 ]
}
runtime_fatal() { exit 1; }
fail2ban_jail_placeholder_map
"""
        env = os.environ.copy()
        env.pop("SSH_PORT_DEFAULT", None)
        env.pop("RUNTIME_SSH_CMDLINE_READY", None)
        for selected in ("true", "false"):
            for port, expected in (("", "22"), ("2222", "2222")):
                with self.subTest(selected=selected, port=port):
                    run = subprocess.run(
                        ["sh", "-c", script, "test", str(SEED / "scripts/late/security.sh"),
                         str(SEED / "scripts/runtime/modules/classes.sh")],
                        env={**env, "SSH_SERVER_ENABLED": selected, "TEST_SSH_PORT": port},
                        text=True, capture_output=True, check=True,
                    )
                    self.assertEqual(run.stdout, f"SSH_PORT={expected}\n")
        for invalid in ("0", "65536", "22;touch /tmp/unwanted"):
            with self.subTest(invalid=invalid):
                run = subprocess.run(
                    ["sh", "-c", script, "test", str(SEED / "scripts/late/security.sh"),
                     str(SEED / "scripts/runtime/modules/classes.sh")],
                    env={**env, "SSH_SERVER_ENABLED": "false", "TEST_SSH_PORT": invalid},
                    text=True, capture_output=True,
                )
                self.assertNotEqual(run.returncode, 0)

    def test_security_profiles_install_daemon_and_nft_action_dependency(self):
        for profile in ("standard", "enhanced"):
            with self.subTest(profile=profile):
                packages = (SEED / f"classes/class-select/security/{profile}.cfg").read_text()
                self.assertIn(" nftables fail2ban ", packages)

    def test_repeat_bans_have_bounded_duration_and_retained_history(self):
        jail = configparser.RawConfigParser()
        jail.read_string((FAIL2BAN / "jail.d/10-sshd.local.tmpl").read_text())
        database = configparser.RawConfigParser()
        database.read(FAIL2BAN / "fail2ban.d/10-managed.local")
        self.assertTrue(jail.getboolean("DEFAULT", "bantime.increment"))
        self.assertEqual(jail.get("DEFAULT", "bantime.maxtime"), "1w")
        self.assertEqual(database.get("DEFAULT", "dbpurgeage"), "14d")

    def test_crowdsec_and_tailscale_have_separate_signals_and_ban_owners(self):
        crowdsec_acquisition = (TARGET / "etc/crowdsec/acquis.d/20-sshd.yaml").read_text()
        crowdsec_bouncer = (TARGET / "etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml.local.tmpl").read_text()
        nft_action = (FAIL2BAN / "action.d/nftables.local").read_text()
        ssh_jail = (FAIL2BAN / "jail.d/10-sshd.local.tmpl").read_text()
        self.assertIn('_SYSTEMD_UNIT=ssh.service', crowdsec_acquisition)
        self.assertIn('mode: nftables', crowdsec_bouncer)
        self.assertIn('table = fail2ban', nft_action)
        self.assertIn('journalmatch = _SYSTEMD_UNIT=ssh.service', ssh_jail)
        self.assertNotIn('tailscaled.service', ssh_jail)

    def test_package_defaults_are_extended_with_staged_local_policies(self):
        installer = (SEED / "scripts/late/security.sh").read_text()
        for path in (
            "action.d/nftables.local", "fail2ban.d/10-managed.local",
            "filter.d/sshd.local", "paths-overrides.local",
        ):
            with self.subTest(path=path):
                self.assertTrue((FAIL2BAN / path).is_file())
                self.assertIn(path, installer)
        self.assertFalse((FAIL2BAN / "paths-common.conf").exists())
        self.assertFalse((FAIL2BAN / "paths-debian.conf").exists())
        self.assertEqual(
            (FAIL2BAN / "filter.d/sshd.local").read_text().split("journalmatch = ", 1)[1].strip(),
            "_SYSTEMD_UNIT=ssh.service",
        )
        self.assertIn("journalmatch = _SYSTEMD_UNIT=ssh.service", (FAIL2BAN / "jail.d/10-sshd.local.tmpl").read_text())
        action = (FAIL2BAN / "action.d/nftables.local").read_text()
        self.assertIn("table_family = inet", action)
        self.assertIn("chain_hook = input", action)
        self.assertIn("blocktype = drop", action)
        self.assertIn("banaction = nftables\n", (FAIL2BAN / "jail.d/10-sshd.local.tmpl").read_text())
        self.assertIn("logpath = %(nginx_error_log)s", (FAIL2BAN / "jail.d/20-nginx-botsearch.local").read_text())
        self.assertIn('"validate Fail2ban configuration"', installer)
        self.assertIn("/usr/bin/fail2ban-client", installer)


class ApparmorEvidenceTests(unittest.TestCase):
    def test_exact_read_only_peers_from_supplied_audit(self):
        desktop = (TARGET / "etc/apparmor.d/desktop-utilities").read_text()
        firstboot = (SEED / "scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl").read_text()
        desktop_profile = desktop.split("profile desktop-launcher ", 1)[1].split("\n}", 1)[0]
        firstboot_profile = firstboot.split("profile firstboot ", 1)[1].split("\n}", 1)[0]
        self.assertIn("ptrace (read) peer=labwc-capture,", desktop_profile)
        self.assertIn("ptrace (read) peer=unconfined,", firstboot_profile)
        self.assertNotIn("ptrace (trace)", firstboot_profile)

    def test_private_clipboard_tool_is_confined_to_zoom_discord_child(self):
        policy = (TARGET / "etc/apparmor.d/desktop-wrappers.tmpl").read_text()
        compat_child = policy.split("profile wayland-compat-app-bwrap ", 1)[1].split("\n  }", 1)[0]
        self.assertIn("/usr/bin/{wl-copy,wl-paste,xclip} rix,", compat_child)
        self.assertIn("owner /run/user/[0-9]*/labwc-clipboard-wayland-[0-9]*.lock rwk,", compat_child)
        self.assertNotIn("owner /run/user/[0-9]*/** rwk,", compat_child)
        packages = (SEED / "classes/class-select/role/desktop.cfg").read_text()
        self.assertIn(" wl-clipboard xclip wf-recorder ", packages)
        self.assertIn("  xclip " + "\\", (SEED / "scripts/desktop/verify.sh.tmpl").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
