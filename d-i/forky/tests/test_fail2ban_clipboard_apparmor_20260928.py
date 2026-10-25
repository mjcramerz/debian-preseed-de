"""Installer wiring for the supplied fail2ban, Cage, and AppArmor failures."""

from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import configparser
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from payload_fixture import read_text as payload_read_text


SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / "hooks/target"
FAIL2BAN = TARGET / "etc/fail2ban"


class Fail2banPolicyTests(unittest.TestCase):
    def test_ssh_monitor_and_daemon_follow_installed_services(self):
        config = (FAIL2BAN / "jail.d/10-sshd.local.tmpl").read_text()
        installer = (SEED / "scripts/late/security.sh").read_text()
        renderer = installer.split("fail2ban_jail_placeholder_map() {", 1)[1].split("\n}", 1)[0]
        stage = installer.split("configure_target_fail2ban() {", 1)[1].split(
            "\nconfigure_target_apparmor_auditd()", 1
        )[0]
        self.assertIn("enabled = __INSTALLER_SSHD_JAIL_ENABLED__", config)
        self.assertIn("render_target_asset_with_placeholder_map", stage)
        self.assertIn("SSH_SERVER_ENABLED", renderer)
        self.assertIn("fail2ban_has_jails=$SSH_SERVER_ENABLED", stage)
        self.assertIn("service/web", stage)
        self.assertIn("SSHD_JAIL_ENABLED", installer + config)
        self.assertIn("stage_target_systemd_unit_enabled fail2ban.service system", stage)
        self.assertIn("    jail.local \\", stage)
        local = configparser.RawConfigParser()
        local.read(FAIL2BAN / "jail.local")
        # The local entrypoint does not freeze a copy of package-owned jails.
        self.assertEqual(local.sections(), [])
        self.assertIn("security_mask_target_systemd_unit_if_available fail2ban.service system", stage)
        for enabled in ("true", "false"):
            parsed = configparser.RawConfigParser()
            parsed.read_string("[sshd]\nenabled = true\n")
            parsed.read_string(config.replace("__INSTALLER_SSH_PORT__", "32006").replace(
                "__INSTALLER_SSHD_JAIL_ENABLED__", enabled))
            self.assertEqual(parsed.getboolean("sshd", "enabled"), enabled == "true")
            self.assertEqual(parsed.get("sshd", "port"), "32006")

    def test_port_renderer_uses_profile_and_rejects_conflicting_cmdline(self):
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
        with tempfile.TemporaryDirectory() as directory:
            sources = []
            for index, relative in enumerate(("scripts/late/security.sh", "scripts/runtime/modules/classes.sh")):
                source = Path(directory) / f"source-{index}.sh"
                source.write_text((SEED / relative).read_text())
                sources.append(str(source))
            env = {"PATH": "/usr/bin:/bin", "HOME": directory, "LC_ALL": "C", "SSH_SERVER_PORT": "32006"}
            for selected in ("true", "false"):
                for port in ("", "32006"):
                    with self.subTest(selected=selected, port=port):
                        run = subprocess.run(
                            ["/bin/sh", "-c", script, "test", *sources],
                            env={**env, "SSH_SERVER_ENABLED": selected, "TEST_SSH_PORT": port},
                            text=True, capture_output=True, check=True, timeout=5,
                        )
                        self.assertEqual(run.stdout, f"SSH_PORT=32006\nSSHD_JAIL_ENABLED={selected}\n")
            for invalid in ("0", "65536", "32007", "22;touch /tmp/unwanted"):
                with self.subTest(invalid=invalid):
                    run = subprocess.run(
                        ["/bin/sh", "-c", script, "test", *sources],
                        env={**env, "SSH_SERVER_ENABLED": "false", "TEST_SSH_PORT": invalid},
                        text=True, capture_output=True, timeout=5,
                    )
                    self.assertNotEqual(run.returncode, 0)

    def test_security_profiles_install_daemon_and_nft_action_dependency(self):
        for profile in ("standard", "enhanced"):
            with self.subTest(profile=profile):
                packages = (SEED / f"classes/class-select/security/{profile}.cfg").read_text()
                self.assertIn(" nftables fail2ban ", packages)
                self.assertIn(" python3-pyinotify ", packages)

    def test_repeat_bans_have_bounded_duration_and_retained_history(self):
        jail = configparser.RawConfigParser()
        jail.read_string((FAIL2BAN / "jail.d/10-sshd.local.tmpl").read_text())
        database = configparser.RawConfigParser()
        database.read(FAIL2BAN / "fail2ban.d/10-security.local")
        self.assertTrue(jail.getboolean("DEFAULT", "bantime.increment"))
        self.assertEqual(jail.get("DEFAULT", "bantime.maxtime"), "1w")
        self.assertEqual(database.get("DEFAULT", "dbpurgeage"), "14d")

    def test_crowdsec_and_tailscale_have_separate_signals_and_ban_owners(self):
        crowdsec_acquisition = payload_read_text(TARGET / "etc/crowdsec/acquis.d/20-sshd.yaml")
        crowdsec_bouncer = (TARGET / "etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml.local.tmpl").read_text()
        nft_action = (FAIL2BAN / "action.d/nftables.local").read_text()
        ssh_jail = payload_read_text(FAIL2BAN / "jail.d/10-sshd.local")
        self.assertIn('source: file', crowdsec_acquisition)
        self.assertIn('/var/log/managed/security/auth/auth.log', crowdsec_acquisition)
        self.assertIn('mode: nftables', crowdsec_bouncer)
        self.assertIn('table = fail2ban', nft_action)
        self.assertIn('backend = pyinotify', ssh_jail)
        self.assertIn('logpath = /var/log/managed/security/auth/auth.log', ssh_jail)
        self.assertNotIn('backend = systemd', ssh_jail)
        self.assertNotIn('tailscaled.service', ssh_jail)

    def test_package_defaults_are_extended_with_staged_local_policies(self):
        installer = (SEED / "scripts/late/security.sh").read_text()
        for path in (
            "action.d/nftables.local", "fail2ban.d/10-security.local",
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
        self.assertIn("backend = pyinotify", (FAIL2BAN / "jail.d/10-sshd.local.tmpl").read_text())
        self.assertIn("/etc/tmpfiles.d/59-log-layout.conf", installer)
        stage = installer.split("configure_target_fail2ban() {", 1)[1].split("\nconfigure_target_apparmor_auditd()", 1)[0]
        self.assertLess(stage.index('"create Fail2ban managed state"'), stage.index('"validate Fail2ban configuration"'))
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
        policy = (TARGET / "etc/apparmor.d/zoom-discord-compat.tmpl").read_text()
        compat_child = policy.split("profile wayland-compat-app-bwrap ", 1)[1].split("\n  }", 1)[0]
        self.assertIn("/usr/bin/{wl-copy,wl-paste,xclip} rix,", compat_child)
        self.assertIn("owner /run/user/[0-9]*/labwc-clipboard-wayland-[0-9]*.lock rwk,", compat_child)
        self.assertNotIn("owner /run/user/[0-9]*/** rwk,", compat_child)
        packages = (SEED / "classes/class-select/role/desktop.cfg").read_text()
        self.assertIn(" wl-clipboard xclip wf-recorder ", packages)
        self.assertIn("  xclip " + "\\", (SEED / "scripts/desktop/verify.sh.tmpl").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
