#!/usr/bin/env python3
"""Offline lifecycle regressions; no root privileges, network or live bus needed."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
FORKY = ROOT / "d-i/forky"
SHARED = FORKY / "hooks/target"


class FirstbootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="firstboot-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.stages = self.path / "stages"
        self.stages.mkdir()
        self.env = dict(os.environ, FIRSTBOOT_LOG_DIR=str(self.path / "logs"),
                        FIRSTBOOT_STATE_DIR=str(self.path / "state"),
                        FIRSTBOOT_SCRIPT_DIR=str(self.stages), FIRSTBOOT_STAGE_TIMEOUT="2")
        self.wrapper = FORKY / "scripts/firstboot/firstboot.sh"
        for stage in ("01-early.sh", "02-collect.sh", "03-network.sh", "04-validation.sh"):
            self.stage(stage, "exit 0\n")
        self.stage("05-cleanup.sh", (FORKY / "scripts/firstboot/05-cleanup.sh").read_text())

    def stage(self, name: str, body: str) -> None:
        script = self.stages / name
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o700)

    def run_wrapper(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["/bin/sh", str(self.wrapper)], env=self.env,
                              text=True, capture_output=True, timeout=15)

    def test_success_marker_and_idempotent_rerun(self) -> None:
        self.assertEqual(self.run_wrapper().returncode, 0)
        marker = self.path / "state/complete"
        self.assertIn("status=0\n", marker.read_text())
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        original = marker.stat().st_mtime_ns
        self.stage("01-early.sh", "exit 42\n")
        self.assertEqual(self.run_wrapper().returncode, 0)
        self.assertEqual(marker.stat().st_mtime_ns, original)

    def test_failure_is_visible_retryable_and_never_complete(self) -> None:
        self.stage("04-validation.sh", "exit 42\n")
        self.assertEqual(self.run_wrapper().returncode, 1)
        self.assertFalse((self.path / "state/complete").exists())
        self.assertIn("status=1\n", (self.path / "logs/status.env").read_text())
        self.stage("04-validation.sh", "exit 0\n")
        self.assertEqual(self.run_wrapper().returncode, 0)
        self.assertTrue((self.path / "state/complete").exists())

    def test_missing_stage_fails(self) -> None:
        (self.stages / "02-collect.sh").unlink()
        self.assertEqual(self.run_wrapper().returncode, 1)
        self.assertFalse((self.path / "state/complete").exists())

    def test_failed_legacy_marker_does_not_suppress_retry(self) -> None:
        (self.path / "state").mkdir()
        (self.path / "state/complete").write_text("status=1\n")
        self.assertEqual(self.run_wrapper().returncode, 0)
        self.assertIn("status=0\n", (self.path / "state/complete").read_text())

    def test_cleanup_refuses_unknown_status(self) -> None:
        result = subprocess.run(["/bin/sh", str(self.stages / "05-cleanup.sh")],
                                env=self.env, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.path / "state/complete").exists())

    def test_log_open_failure_is_not_success(self) -> None:
        self.env["FIRSTBOOT_LOG_FILE"] = str(self.path / "missing/log")
        self.assertNotEqual(self.run_wrapper().returncode, 0)

    def test_stage_deadline_fails_without_marker(self) -> None:
        self.env["FIRSTBOOT_STAGE_TIMEOUT"] = "1"
        self.stage("02-collect.sh", "sleep 30\n")
        start = time.monotonic()
        self.assertEqual(self.run_wrapper().returncode, 1)
        self.assertLess(time.monotonic() - start, 8)
        self.assertFalse((self.path / "state/complete").exists())

    def test_concurrent_run_is_locked_and_term_cleans_child(self) -> None:
        pidfile = self.path / "child.pid"
        self.env["FIRSTBOOT_STAGE_TIMEOUT"] = "10"
        self.stage("01-early.sh", f"sleep 30 &\nprintf '%s\\n' \"$!\" > '{pidfile}'\nwait\n")
        process = subprocess.Popen(["/bin/sh", str(self.wrapper)], env=self.env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(pidfile.exists())
        self.assertEqual(self.run_wrapper().returncode, 75)
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=8), 143)
        child = int(pidfile.read_text())
        procstat = Path(f"/proc/{child}/stat")
        # A descendant zombie may briefly await the container's PID 1; it must
        # not remain running or retain any open files or locks.
        if procstat.exists():
            self.assertEqual(procstat.read_text().split(") ", 1)[1][0], "Z")
        self.assertFalse((self.path / "state/complete").exists())


class AssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="asset-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.target = self.path / "target"
        self.target.mkdir()
        self.source = self.path / "source"
        self.source.write_text("new content\n")
        self.script = FORKY / "scripts/late/target-assets.sh"
        self.preamble = f"""
set -eu
INSTALLER_TARGET_DIR='{self.target}'
TMP_ENV_DIR='{self.path}'
installer_fatal() {{ printf '%s\\n' "$*" >&2; exit 1; }}
target_normalize_systemd_config_parent_modes() {{ :; }}
fetch_hook() {{ cp "$1" "$2"; }}
. '{self.script}'
"""

    def shell(self, body: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["/bin/sh", "-c", self.preamble + body],
                              text=True, capture_output=True, timeout=5)

    def test_custom_target_and_private_parent_mode(self) -> None:
        parent = self.target / "private"
        parent.mkdir(mode=0o700)
        result = self.shell(f"stage_target_asset '{self.source}' /private/file 0640")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((parent / "file").read_text(), "new content\n")
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((parent / "file").stat().st_mode), 0o640)
        self.assertEqual(sorted(p.name for p in parent.iterdir()), ["file"])

    def test_failed_fetch_preserves_old_file(self) -> None:
        target = self.target / "file"
        target.write_text("old content")
        result = self.shell(f"fetch_hook() {{ printf partial > \"$2\"; return 1; }}\n"
                            f"stage_target_asset '{self.source}' /file 0644")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "old content")
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["file"])

    def test_failed_map_never_publishes_raw_template(self) -> None:
        target = self.target / "file"
        target.write_text("old content")
        result = self.shell(f"fail_map() {{ return 1; }}\n"
                            f"render_target_asset_with_placeholder_map '{self.source}' /file 0644 fail_map")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "old content")
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), ["file"])

    def test_symlink_parent_cannot_escape_install_root(self) -> None:
        outside = self.path / "outside"
        outside.mkdir()
        (self.target / "escape").symlink_to(outside, target_is_directory=True)
        result = self.shell(f"stage_target_asset '{self.source}' /escape/new/file 0644")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_dotdot_rejected(self) -> None:
        result = self.shell(f"stage_target_asset '{self.source}' /../escaped 0644")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.path / "escaped").exists())

    def test_target_symlink_replaced_not_followed(self) -> None:
        outside = self.path / "outside"
        outside.write_text("untouched")
        (self.target / "file").symlink_to(outside)
        result = self.shell(f"stage_target_asset '{self.source}' /file 0644")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outside.read_text(), "untouched")
        self.assertFalse((self.target / "file").is_symlink())


class PublishingEntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="publishing-entrypoints-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.target = self.path / "target"
        self.target.mkdir()
        source = (FORKY / "scripts/late/devops.sh").read_text()
        link_helper = source.split(
            "devops_stage_publishing_command_link() (", 1
        )[1].split("\n)\n\ndevops_stage_publishing_entrypoints() {", 1)[0]
        stage_helper = source.split(
            "devops_stage_publishing_entrypoints() {", 1
        )[1].split("\n}\n\ndevops_install_pending_credential() {", 1)[0]
        self.script = f'''\
set -eu
target_root=$TEST_TARGET_ROOT
tmp_env_dir=$TEST_TMP_ENV_DIR
devops_fatal() {{ printf 'fatal: %s\\n' "$*" >&2; exit 1; }}
installer_repo_join_var() {{ printf '%s\\n' "$2"; }}
devops_stage_target_asset() {{
  : > "${{target_root}}$2"
  chmod "$3" "${{target_root}}$2"
}}
chown() {{ :; }}
devops_stage_publishing_command_link() (
{link_helper}
)
devops_stage_publishing_entrypoints() {{
{stage_helper}
}}
'''
        self.env = dict(
            os.environ,
            TEST_TARGET_ROOT=str(self.target),
            TEST_TMP_ENV_DIR=str(self.path),
        )

    def run_stage(
        self, body: str = "devops_stage_publishing_entrypoints"
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/sh", "-c", self.script + body],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=5,
        )

    def test_retry_accepts_exact_managed_links(self) -> None:
        result = self.run_stage(
            "devops_stage_publishing_entrypoints\n"
            "devops_stage_publishing_entrypoints\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {
            "aptly-publishing-bin/aptly": "../aptly-publishing",
            "aptly-publishing-bin/aptly-publish-local": "../aptly-publishing",
            "aptly-publishing-bin/dpkg-buildpackage": "../aptly-publishing",
            "obs-publishing-bin/obs-checkout-source": "../obs-publishing",
            "obs-publishing-bin/obs-publish-source": "../obs-publishing",
            "obs-publishing-bin/osc": "../obs-publishing",
        }
        libexec = self.target / "usr/local/libexec"
        for relative_path, target in expected.items():
            with self.subTest(path=relative_path):
                link = libexec / relative_path
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link), target)

    def test_wrong_symlink_is_rejected_without_replacement(self) -> None:
        link = self.target / "usr/local/libexec/aptly-publishing-bin/aptly"
        link.parent.mkdir(parents=True)
        link.symlink_to("../unexpected")
        result = self.run_stage()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has an unexpected target", result.stderr)
        self.assertEqual(os.readlink(link), "../unexpected")

    def test_regular_file_collision_is_rejected_without_replacement(self) -> None:
        link = self.target / "usr/local/libexec/aptly-publishing-bin/aptly"
        link.parent.mkdir(parents=True)
        link.write_text("unmanaged\n")
        result = self.run_stage()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "managed Aptly publication entrypoint already exists: "
            "/usr/local/libexec/aptly-publishing-bin/aptly",
            result.stderr,
        )
        self.assertEqual(link.read_text(), "unmanaged\n")


class CleanupAndUnitTests(unittest.TestCase):
    def tmpfs_policy_output(self, function: str) -> str:
        volatile_storage = FORKY / "scripts/late/volatile-storage.sh"
        source = f"""\
set -eu
TMPFS_VAR_LOG=true
TMPFS_VAR_CACHE=true
TMPFS_VAR_LIB_APT_LISTS=false
TMPFS_DEV_SHM=true
TMPFS_DATA_RUN=true
TMPFS_SYSTEMD_COREDUMP=true
DIR_TMP=/tmp
DIR_DEV_SHM=/dev/shm
DIR_VAR_LOG=/var/log
DIR_VAR_CACHE=/var/cache
DIR_APT_LISTS=/var/lib/apt/lists
DIR_SYSTEMD_COREDUMP=/var/lib/systemd/coredump
DIR_DATA_RUN=/data/run
DIR_DATA=/data
. '{volatile_storage}'
{function}
"""
        result = subprocess.run(["/bin/sh"], input=source, text=True,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_tmpfs_pre_clean_policy_handles_inherited_dev_shm(self) -> None:
        self.assertEqual(
            self.tmpfs_policy_output("tmpfs_pre_clean_mount_units_for_enabled_policy"),
            "tmp.mount dev-shm.mount var-log.mount var-cache.mount "
            "var-lib-systemd-coredump.mount data-run.mount\n",
        )
        self.assertEqual(
            self.tmpfs_policy_output("tmpfs_pre_clean_targets_for_enabled_policy"),
            "DIR_TMP|/tmp DIR_VAR_LOG|/var/log DIR_VAR_CACHE|/var/cache "
            "DIR_SYSTEMD_COREDUMP|/var/lib/systemd/coredump "
            "DIR_DATA_RUN|/data/run\n",
        )
        self.assertEqual(
            self.tmpfs_policy_output("tmpfs_pre_clean_read_write_paths_for_enabled_policy"),
            "/tmp /var/log /var/cache /var/lib/systemd/coredump /data/run\n",
        )
        self.assertEqual(
            self.tmpfs_policy_output("tmpfs_pre_clean_condition_lines_for_enabled_policy"),
            "ConditionPathExists=/tmp\n"
            "ConditionPathIsDirectory=/tmp\n"
            "ConditionPathIsMountPoint=!/tmp\n"
            "ConditionPathExists=/var/log\n"
            "ConditionPathIsDirectory=/var/log\n"
            "ConditionPathIsMountPoint=!/var/log\n"
            "ConditionPathExists=/var/cache\n"
            "ConditionPathIsDirectory=/var/cache\n"
            "ConditionPathIsMountPoint=!/var/cache\n"
            "ConditionPathExists=/var/lib/systemd/coredump\n"
            "ConditionPathIsDirectory=/var/lib/systemd/coredump\n"
            "ConditionPathIsMountPoint=!/var/lib/systemd/coredump\n"
            "ConditionPathExists=/data/run\n"
            "ConditionPathIsDirectory=/data/run\n"
            "ConditionPathIsMountPoint=!/data/run\n",
        )

    def test_tmpfs_cleanup_preserves_symlink_destination(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pre-clean-") as name:
            base = Path(name)
            clean = base / "clean"
            clean.mkdir()
            (clean / "nested").mkdir()
            (clean / "nested/file").write_text("delete")
            outside = base / "outside"
            outside.write_text("keep")
            (clean / "link").symlink_to(outside)
            source = (SHARED / "usr/local/libexec/tmpfs-pre-clean.tmpl").read_text()
            source = source.replace("__INSTALLER_TMPFS_PRE_CLEAN_TARGETS__", f"test|{clean}")
            result = subprocess.run(["/bin/sh"], input=source, text=True,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(clean.iterdir()), [])
            self.assertEqual(outside.read_text(), "keep")

    def test_tmpfs_preflight_refuses_mountinfo_descendant(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pre-clean-") as name:
            base = Path(name)
            clean = base / "clean"
            clean.mkdir()
            (clean / "file").write_text("keep")
            mountinfo = base / "mountinfo"
            mountinfo.write_text(f"1 2 0:1 / {clean}/mounted rw - tmpfs none rw\n")
            source = (SHARED / "usr/local/libexec/tmpfs-pre-clean.tmpl").read_text()
            source = source.replace("__INSTALLER_TMPFS_PRE_CLEAN_TARGETS__", f"test|{clean}")
            source = source.replace("/proc/self/mountinfo", str(mountinfo))
            result = subprocess.run(["/bin/sh"], input=source, text=True,
                                    capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((clean / "file").read_text(), "keep")

    def test_apt_refresh_does_not_wait_for_persistent_dispatcher_exit(self) -> None:
        unit = (SHARED / "etc/systemd/system/apt-refresh-lists.service.tmpl").read_text()
        self.assertNotIn("systemctl is-active", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertIn("StartLimitBurst=3", unit)
        helper = (SHARED / "usr/local/libexec/apt-refresh-lists.tmpl").read_text()
        self.assertIn("APT::Update::Error-Mode=any", helper)
        self.assertIn("return 75", helper)

    def test_firstboot_does_not_hold_sysinit_until_diagnostics_finish(self) -> None:
        unit = (SHARED / "etc/systemd/system/firstboot.service").read_text()
        self.assertIn("Type=exec", unit)
        self.assertNotIn("Type=oneshot", unit)
        self.assertIn("RuntimeMaxSec=35min", unit)
        self.assertIn("KillMode=control-group", unit)


if __name__ == "__main__":
    unittest.main()
