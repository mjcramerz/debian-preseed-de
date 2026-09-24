#!/usr/bin/env python3
"""Target staging visibility regressions; no mounts, services or hardware writes.

Real shell publishers, Perl network generation and Python hardware installation
run in disposable chroots. Renaming the fixture's /run away models d-i covering
/target/run during in-target; it is deliberately NOT a real bind-mount test.
Only installed interpreter binaries/libraries are copied: nothing is compiled.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import time
import subprocess
import tempfile
import unittest

from test_hardware_restore import FORKY, copy_binary, make_chroot
from payload_fixture import installed_script

SHELLS = [["/bin/sh"]]
if shutil.which("busybox"):
    SHELLS.append([shutil.which("busybox"), "sh"])

PREAMBLE = r'''
set -eu
. "$FORKY/scripts/common/lib.sh"
. "$FORKY/scripts/common/target.sh"
. "$FORKY/scripts/late/target-assets.sh"
. "${NETWORK_SOURCE:-$FORKY/scripts/late/network.sh}"
. "${HARDWARE_SOURCE:-$FORKY/scripts/desktop/hardware-tuning.sh}"
installer_fatal() { printf 'fatal: %s\n' "$*" >&2; exit 1; }
installer_info() { :; }
installer_warn() { :; }
desktop_log() { :; }
installer_repo_join_var() {
  case "$1" in
    DIR_HOOKS_TARGET) printf 'hooks/target/%s\n' "$2" ;;
    DIR_SCRIPTS_LATE) printf 'scripts/late/%s\n' "$2" ;;
    *) exit 95 ;;
  esac
}
fetch_hook() (
  case "${FAULT:-}:$1" in
    fetch-generator:*/network-generate.pl|fetch-manifest:*/network-assets.list|fetch-fragment:*/inet4.tmpl|fetch-hardware:*/hardware-tuning-config.py|fetch-hardware-asset:*/hardware-tuning.socket.tmpl)
      return 43 ;;
  esac
  fixture_source=$FORKY/$1
  [ -f "$fixture_source" ] || fixture_source=$fixture_source.tmpl
  cp "$fixture_source" "$2" || exit 1
  case "${FAULT:-}:$1" in
    unknown-marker:*/inet4.tmpl) printf '\n__INSTALLER_NOT_A_NETWORK_FIELD__\n' >> "$2" ;;
  esac
)
desktop_stage_role_asset() { stage_target_asset "hooks/target/$1" "$2" "$3"; }
desktop_hardware_intel_detected() { return 0; }
installer_nvidia_addon_selected() { return 0; }
installer_nvidia_gpu_detected() { return 0; }
network_answer_value() {
  case "$1" in
    netcfg/get_ipaddress) printf '%s\n' 192.0.2.20 ;;
    netcfg/get_netmask) printf '%s\n' 255.255.255.0 ;;
    netcfg/get_gateway) printf '%s\n' 192.0.2.1 ;;
    netcfg/get_nameservers) printf '%s\n' 192.0.2.53 ;;
    netcfg/wireless_essid) printf '%s\n' FixtureWifi ;;
    netcfg/wireless_security_type) printf '%s\n' wpa ;;
    netcfg/wireless_wpa) printf '%s\n' fixture-only-psk-12345 ;;
    *) return 1 ;;
  esac
}
installer_cmdline_value() {
  [ "${DUAL_STACK:-false}" = true ] || return 1
  case "$1" in
    ipv6_address) printf '%s\n' 2001:db8::20/64 ;;
    ipv6_gateway) printf '%s\n' 2001:db8::1 ;;
    ipv6_nameservers) printf '%s\n' 2001:db8::53 ;;
    *) return 1 ;;
  esac
}
installer_network_interface_for_handoff() {
  case "$1" in ethernet) printf '%s\n' enp1s0 ;; wifi) printf '%s\n' wlp2s0 ;; esac
}
installer_interface_mac_address() {
  case "$1" in enp1s0) printf '%s\n' 02:00:00:00:00:01 ;; wlp2s0) printf '%s\n' 02:00:00:00:00:02 ;; esac
}
target_host_variant_class() { printf '%s\n' fixture; }
fixture_target_call() (
  shift
  printf '%s\n' "$*" >> "$FIXTURE/target-calls"
  # Record staging permissions, not input contents (which can include a PSK).
  find "$INSTALLER_TARGET_DIR/tmp" "$INSTALLER_TARGET_DIR/run" -type d -name 'installer-*' -printf '%m %p\n' >> "$FIXTURE/modes"
  find "$INSTALLER_TARGET_DIR/tmp" -type f \( -name policy.env -o -name network-input.env \) -printf '%m %p\n' >> "$FIXTURE/modes"
  case "${FAULT:-}" in
    target) return 44 ;;
    wait-for-signal) : > "$FIXTURE/ready"; sleep 30; return 0 ;;
  esac
  mv "$INSTALLER_TARGET_DIR/run" "$INSTALLER_TARGET_DIR/run-covered"
  mkdir "$INSTALLER_TARGET_DIR/run"
  trap 'rmdir "$INSTALLER_TARGET_DIR/run"; mv "$INSTALLER_TARGET_DIR/run-covered" "$INSTALLER_TARGET_DIR/run"' 0
  if [ "$1" = /usr/sbin/apparmor_parser ]; then
    # Native parsing is exercised independently by check_hardware_tuning.py;
    # assert the install boundary requests parsing only, never kernel loading.
    [ "$2" = --skip-kernel-load ] && [ "$3" = --skip-cache ] || exit 96
    [ "${FAULT:-}" != apparmor ] || exit 45
    [ -f "$INSTALLER_TARGET_DIR$4" ] || exit 97
    exit 0
  fi
  target_exec "$@" || exit "$?"
  case "${FAULT:-}" in
    missing-state) rm "$INSTALLER_TARGET_DIR"/tmp/installer-network.*/network-state.env ;;
    symlink-state)
      for fixture_state in "$INSTALLER_TARGET_DIR"/tmp/installer-network.*/network-state.env; do
        rm "$fixture_state"
        ln -s "$FIXTURE/foreign-state" "$fixture_state"
      done ;;
  esac
)
attempt_in_target() { fixture_target_call "$@"; }
run_in_target() { fixture_target_call "$@"; }
'''

# Isolated publisher fixtures need definitions only; actual payload/module
# loading is exercised separately by test_modular_installer.py.
PREAMBLE = PREAMBLE.replace('. "$FORKY/scripts/common/lib.sh"',
    '. ' + shlex.quote(str(installed_script(FORKY / 'scripts/common/lib.sh'))))


class PrivateStageTests(unittest.TestCase):
    def run_shell(self, root: Path, code: str, shell: list[str]):
        return subprocess.run(shell + ["-c", PREAMBLE + code],
            env=dict(os.environ, FORKY=str(FORKY), INSTALLER_TARGET_DIR=str(root)),
            capture_output=True, text=True, timeout=10)

    def test_unique_private_paths_and_preserved_parent_under_both_shells(self):
        for shell in SHELLS:
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="stage root ") as tmp:
                root = Path(tmp)
                (root / "tmp").mkdir(mode=0o1777)
                before = (root / "tmp").stat().st_mode
                result = self.run_shell(root, "umask 000\ntarget_private_stage_dir network\ntarget_private_stage_dir network\n", shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                names = result.stdout.splitlines()
                self.assertEqual(len(set(names)), 2)
                for name in names:
                    self.assertRegex(name, r"^/tmp/installer-network\.[A-Za-z0-9]+$")
                    self.assertEqual((root / name.lstrip("/")).stat().st_mode & 0o777, 0o700)
                self.assertEqual((root / "tmp").stat().st_mode, before)

    def test_symlink_or_missing_parent_is_rejected(self):
        for shell in SHELLS:
            for kind in ("missing", "symlink", "dangling"):
                with self.subTest(shell=shell, kind=kind), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    outside = root / "outside"
                    outside.mkdir()
                    if kind != "missing":
                        (root / "tmp").symlink_to(outside if kind == "symlink" else root / "absent")
                    result = self.run_shell(root, "target_private_stage_dir network\n", shell)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(result.stdout)
                    self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_names_are_rejected_even_in_conditional_call(self):
        for shell in SHELLS:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "tmp").mkdir()
                for name in ("", "../run", "net/work", "x;y", "name with space", "a" * 33):
                    with self.subTest(shell=shell, name=name):
                        code = f"if target_private_stage_dir {shlex.quote(name)}; then exit 90; else exit 0; fi\n"
                        result = self.run_shell(root, code, shell)
                        self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(list((root / "tmp").iterdir()), [])


@unittest.skipUnless(os.geteuid() == 0 and shutil.which("busybox") and shutil.which("perl"),
                     "real interpreter chroots require root, BusyBox and Perl")
class TargetStageChrootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_temp = tempfile.TemporaryDirectory(prefix="stage-chroot-base-", dir="/root")
        cls.addClassCleanup(cls.base_temp.cleanup)
        cls.base = Path(cls.base_temp.name)
        make_chroot(cls.base)
        for binary in ("/usr/bin/env", "/usr/bin/perl", "/usr/bin/python3"):
            copy_binary(cls.base, binary)
        perl_paths = subprocess.check_output(["/usr/bin/perl", "-MConfig", "-e",
            'print "$Config{privlib}\\n$Config{archlib}\\n"'], text=True).splitlines()
        stdlib = Path(subprocess.check_output(["/usr/bin/python3", "-c",
            "import sysconfig; print(sysconfig.get_path('stdlib'))"], text=True).strip())
        for library in [*(Path(p) for p in perl_paths), stdlib]:
            shutil.copytree(library, cls.base / str(library).lstrip("/"), dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "test", "tests", "dist-packages"))
        # Copy dependencies of binary interpreter extensions without compiling.
        for module in (stdlib / "lib-dynload").glob("*.so"):
            copy_binary(cls.base, str(module))
        # Supply the target bridge's C.UTF-8 locale, rather than hiding warnings.
        locale = Path("/usr/lib/locale/C.utf8")
        if locale.is_dir():
            shutil.copytree(locale, cls.base / "usr/lib/locale/C.utf8")
        (cls.base / "run").mkdir()
        (cls.base / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/sh\ndesktop:x:1000:1000:Desktop:/home/desktop:/bin/sh\n")
        (cls.base / "etc/group").write_text("root:x:0:\ndesktop:x:1000:\n")
        for name, mac in (("enp1s0", "02:00:00:00:00:01"), ("wlp2s0", "02:00:00:00:00:02")):
            interface = cls.base / "sys/class/net" / name
            (interface / "device").mkdir(parents=True)
            if name.startswith("wlp"):
                (interface / "wireless").mkdir()
            for key, value in {"type": "1", "address": mac, "carrier": "1", "operstate": "up"}.items():
                (interface / key).write_text(value + "\n")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="stage-chroot-", dir="/root")
        self.addCleanup(self.temp.cleanup)
        self.fixture = Path(self.temp.name)
        self.root = self.fixture / "target root"
        shutil.copytree(self.base, self.root, symlinks=True)
        (self.fixture / "state").mkdir(mode=0o700)
        (self.fixture / "foreign-state").write_text("FOREIGN=unchanged\n")
        self.environment = dict(os.environ, FORKY=str(FORKY), FIXTURE=str(self.fixture),
            INSTALLER_TARGET_DIR=str(self.root), TMP_ENV_DIR=str(self.fixture / "state"),
            SYSTEM_HOSTNAME="fixture", SYSTEM_DOMAIN="example.test", ACCOUNT_USERNAME="desktop")

    def run_shell(self, code: str, *, shell=None, **environment):
        return subprocess.run((shell or SHELLS[0]) + ["-c", PREAMBLE + code],
            env=dict(self.environment, **environment), capture_output=True, text=True, timeout=30)

    def assert_clean(self):
        self.assertEqual(list((self.root / "tmp").glob("installer-*")), [])
        self.assertEqual(list((self.root / "run").iterdir()), [])
        self.assertFalse((self.root / "run-covered").exists())
        self.assertEqual((self.fixture / "foreign-state").read_text(), "FOREIGN=unchanged\n")

    def assert_modes(self):
        lines = (self.fixture / "modes").read_text().splitlines()
        self.assertTrue(lines)
        for line in lines:
            mode, path = line.split(" ", 1)
            self.assertEqual(mode, "600" if path.endswith(("policy.env", "network-input.env")) else "700", line)

    def test_real_network_generator_with_covered_run_and_repeat(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell("generate_target_managed_network_config static ethernet\n"
                                        '[ "$MANAGED_NETWORK_GENERATED" = true ]\n', shell=shell)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                state = self.fixture / "state/network-state.env"
                self.assertIn("192.0.2.20/32", state.read_text())
                self.assertEqual(state.stat().st_mode & 0o777, 0o600)
                network = (self.root / "etc/network/interfaces.d/50-network").read_text()
                self.assertIn("iface eth0 inet static", network)
                self.assertIn("address 192.0.2.20", network)
                self.assertIn("02:00:00:00:00:01", (self.root / "etc/systemd/network/10-ethernet.link").read_text())
                self.assert_clean()
                self.assert_modes()

    def test_dual_stack_ethernet_wifi_secret_stays_out_of_state_and_logs(self):
        result = self.run_shell("generate_target_managed_network_config static 'ethernet wifi'\n", DUAL_STACK="true")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        network = self.root / "etc/network/interfaces.d/50-network"
        self.assertEqual(network.stat().st_mode & 0o777, 0o600)
        for wanted in ("iface eth0 inet6 static", "iface wifi0 inet6 static", "fixture-only-psk-12345"):
            self.assertIn(wanted, network.read_text())
        state = (self.fixture / "state/network-state.env").read_text()
        self.assertIn("2001:db8::20/128", state)
        for data in (state, result.stdout, result.stderr,
                     (self.root / "etc/network/host.conf").read_text(), (self.fixture / "target-calls").read_text()):
            self.assertNotIn("fixture-only-psk-12345", data)
        self.assert_clean()
        self.assert_modes()

    def test_staging_and_generator_failures_do_not_publish_state_or_leak_inputs(self):
        for shell in SHELLS:
            for fault in ("fetch-generator", "fetch-manifest", "fetch-fragment", "target", "missing-state", "symlink-state", "unknown-marker"):
                with self.subTest(shell=shell, fault=fault):
                    result = self.run_shell("if generate_target_managed_network_config static ethernet; then exit 90; else exit 41; fi\n", shell=shell, FAULT=fault)
                    self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
                    self.assertFalse((self.fixture / "state/network-state.env").exists())
                    self.assert_clean()
        # Missing staged assets must fail before any target execution.
        self.assertEqual(len((self.fixture / "target-calls").read_text().splitlines()), 8)

    def hardware_profile(self):
        profile = self.fixture / "profile.env"
        profile.write_text((FORKY / "hosts/profiles/btrfs-de-p15s.env").read_text() + '\nACCOUNT_PASSWORD="must-not-copy"\n')
        self.environment["LATE_COMMAND_HOST_ENV"] = str(profile)
        config = self.root / "etc/skel-desktop/.config/waybar/config"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps([
            {"name": name, "battery": {"on-click": "keep-left-" + name}}
            for name in ("internal", "external")]))

    def test_real_hardware_installation_is_visible_and_remains_opt_in(self):
        self.hardware_profile()
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_shell("desktop_install_hardware_tuning\n", shell=shell,
                    HARDWARE_INTEL_CPU_TUNING_ENABLE="true", HARDWARE_NVIDIA_GPU_TUNING_ENABLE="true")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                broker = self.root / "etc/hardware-tuning/broker.json"
                config = json.loads(broker.read_text())
                self.assertEqual(config["vendors"], ["intel", "nvidia"])
                self.assertEqual(config["uid"], 1000)
                self.assertEqual(broker.stat().st_mode & 0o777, 0o600)
                for vendor in ("intel", "nvidia"):
                    policy = json.loads((broker.parent / (vendor + ".json")).read_text())
                    self.assertFalse(policy["allow_overclock"])
                    self.assertFalse(policy["allow_power_increase"])
                    for name in ("performance", "high", "balanced", "silent"):
                        self.assertTrue((self.root / f"etc/systemd/user/{vendor}-{name}.target").is_file())
                        self.assertTrue((self.root / f"etc/systemd/user/hardware-tuning-{vendor}-{name}.service").is_file())
                system = self.root / "etc/systemd/system"
                self.assertTrue((system / "sockets.target.wants/hardware-tuning.socket").is_symlink())
                self.assertTrue((system / "sleep.target.requires/hardware-tuning-sleep.service").is_symlink())
                self.assertFalse((system / "multi-user.target.wants/hardware-tuning-autostart.service").is_symlink())
                bars = json.loads((self.root / "etc/skel-desktop/.config/waybar/config").read_text())
                for bar in bars:
                    self.assertEqual(bar["battery"]["on-click"], "keep-left-" + bar["name"])
                    self.assertIn("labwc-hardware-tuning menu", bar["battery"]["on-click-right"])
                self.assert_clean()
                self.assert_modes()
                self.assertNotIn("must-not-copy", (self.fixture / "target-calls").read_text())

    def install_one_vendor(self, vendor):
        self.hardware_profile()
        result = self.run_shell("desktop_install_hardware_tuning\n",
            HARDWARE_INTEL_CPU_TUNING_ENABLE=str(vendor == "intel").lower(),
            HARDWARE_NVIDIA_GPU_TUNING_ENABLE=str(vendor == "nvidia").lower())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        policy = self.root / "etc/hardware-tuning"
        self.assertEqual(sorted(p.name for p in policy.iterdir()), ["broker.json", vendor + ".json"])
        self.assertEqual(json.loads((policy / "broker.json").read_text())["vendors"], [vendor])
        excluded = "nvidia" if vendor == "intel" else "intel"
        self.assertFalse((self.root / f"usr/local/lib/hardware_tuning/{excluded}.py").exists())
        self.assertFalse((self.root / f"etc/apparmor.d/abstractions/hardware-tuning-{excluded}").exists())
        self.assert_clean()

    def test_real_intel_only_installation(self):
        self.install_one_vendor("intel")

    def test_real_nvidia_only_installation(self):
        self.install_one_vendor("nvidia")

    def test_termination_cleans_both_stages_under_both_shells(self):
        self.hardware_profile()
        for shell in SHELLS:
            for command in ("generate_target_managed_network_config static ethernet", "desktop_install_hardware_tuning"):
                with self.subTest(shell=shell, command=command):
                    ready = self.fixture / "ready"
                    ready.unlink(missing_ok=True)
                    process = subprocess.Popen(shell + ["-c", PREAMBLE + command + "\n"],
                        env=dict(self.environment, FAULT="wait-for-signal",
                            HARDWARE_INTEL_CPU_TUNING_ENABLE="true", HARDWARE_NVIDIA_GPU_TUNING_ENABLE="true"),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
                    try:
                        deadline = time.monotonic() + 10
                        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                            time.sleep(0.02)
                        self.assertTrue(ready.exists(), "target call was not reached")
                        os.killpg(process.pid, signal.SIGTERM)
                        stdout, stderr = process.communicate(timeout=5)
                        self.assertNotEqual(process.returncode, 0, stdout + stderr)
                        self.assert_clean()
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.communicate(timeout=5)

    def test_hardware_staging_failures_are_fatal_and_clean(self):
        self.hardware_profile()
        for shell in SHELLS:
            for fault in ("fetch-hardware", "fetch-hardware-asset", "target", "apparmor"):
                with self.subTest(shell=shell, fault=fault):
                    result = self.run_shell("if desktop_install_hardware_tuning; then exit 90; else exit 41; fi\n", shell=shell,
                        FAULT=fault, HARDWARE_INTEL_CPU_TUNING_ENABLE="true", HARDWARE_NVIDIA_GPU_TUNING_ENABLE="true")
                    self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
                    self.assert_clean()


if __name__ == "__main__":
    unittest.main()
