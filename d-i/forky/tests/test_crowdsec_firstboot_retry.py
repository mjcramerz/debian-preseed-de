"""Exercise CrowdSec firstboot retry decisions without a daemon or remote API."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


FORKY = Path(__file__).resolve().parents[1]
SOURCE = (FORKY / "scripts/firstboot/assets/var/lib/firstboot/bin/crowdsec-firstboot.tmpl").read_text(encoding="utf-8")
UNIT = (FORKY / "scripts/firstboot/assets/etc/systemd/system/crowdsec-firstboot.service.tmpl").read_text(encoding="utf-8")
SHELLS = (("dash", ["/bin/dash"]),)
BUSYBOX = shutil.which("busybox")
if BUSYBOX:
    SHELLS += (("busybox", [BUSYBOX, "sh"]),)


def source_function(name: str) -> str:
    start = SOURCE.index(name + "() {")
    return SOURCE[start:SOURCE.index("\n}\n", start) + 2]


class CrowdSecFirstbootRetryTests(unittest.TestCase):
    def test_hub_failures_distinguish_remote_forbidden_from_local_permissions(self):
        code = source_function("run_crowdsec_command") + """
work_dir=$1
log_line() { printf 'event=%s\\n' "$*"; }
timeout() { printf '%s\\n' "$CASE_MESSAGE"; return 1; }
run_crowdsec_command optional hub-update cscli hub update || :
"""
        for message, expected in (("HTTP 403 Forbidden", "remote-forbidden"),
                                  ("open /etc/crowdsec: permission denied", "local-permission-denied"),
                                  ("network timeout", "command-failed")):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as root:
                result = subprocess.run(["/bin/dash", "-eu", "-c", code,
                    "crowdsec-fixture", root], env={"PATH": "/usr/bin:/bin",
                    "CASE_MESSAGE": message}, text=True, encoding="utf-8",
                    capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("hub-update=failed reason=" + expected, result.stdout)
                self.assertNotIn(message, result.stdout + result.stderr)

    def test_console_distinguishes_invalid_key_from_forbidden_and_keeps_output_private(self):
        code = source_function("enroll_console") + """
work_dir=$1
CROWDSEC_ENROLL_ATTEMPTS=1
CROWDSEC_ENROLL_RETRY_DELAY_SECONDS=10
log_line() { printf 'event=%s\\n' "$*"; }
timeout() {
  printf 'attempt\\n' >>"$work_dir/calls"
  printf '%s\\n' "$CASE_MESSAGE"
  return 1
}
if enroll_console fixture-token fixture-host; then
  printf 'result=0\\n'
else
  printf 'result=%s\\n' "$?"
fi
"""
        cases = (
            ("the attachment key provided is not valid", 2),
            ('API error: Forbidden; fixture-token', 3),
            ("bad HTTP code 403", 3),
            ("connection reset by peer", 1),
        )
        for label, shell in SHELLS:
            for message, expected in cases:
                with self.subTest(shell=label, response=message), tempfile.TemporaryDirectory() as root:
                    result = subprocess.run(
                        [*shell, "-eu", "-c", code, "crowdsec-fixture", root],
                        env={"PATH": "/usr/bin:/bin", "CASE_MESSAGE": message},
                        text=True, encoding="utf-8", capture_output=True, timeout=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f"result={expected}\n", result.stdout)
                    self.assertEqual((Path(root) / "calls").read_text(encoding="ascii"), "attempt\n")
                    self.assertNotIn("fixture-token", result.stdout + result.stderr)

    def test_verified_core_retry_does_not_update_hub_or_restart_services(self):
        start = SOURCE.index('if [ -f "$CROWDSEC_CORE_READY_FILE" ] &&')
        end = SOURCE.index("\nenrollment_status=skipped", start)
        # Only the absolute verifier is replaced; all other shell control flow
        # runs from the production source against inert command fixtures.
        body = SOURCE[start:end].replace(
            "/usr/local/libexec/crowdsec-bouncer-verify >/dev/null 2>&1",
            "bouncer_verify >/dev/null 2>&1",
        )
        code = """
CROWDSEC_CORE_READY_FILE=$1
systemctl() {
  case "$1" in
    is-enabled|is-active)
      printf 'checked=%s:%s\\n' "$1" "$3"
      return 0
      ;;
  esac
  printf 'unexpected-systemctl=%s\\n' "$*"
  return 1
}
timeout() { return 0; }
bouncer_verify() { return 0; }
log_line() { printf 'event=%s\\n' "$*"; }
""" + body
        for label, shell in SHELLS:
            with self.subTest(shell=label), tempfile.TemporaryDirectory() as root:
                marker = Path(root) / "core-ready"
                marker.write_text("ready\n", encoding="ascii")
                result = subprocess.run(
                    [*shell, "-eu", "-c", code, "crowdsec-fixture", str(marker)],
                    env={"PATH": "/usr/bin:/bin"}, text=True, encoding="utf-8",
                    capture_output=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("core_bootstrap=already-verified", result.stdout)
                for action in ("is-enabled", "is-active"):
                    for unit in ("crowdsec.service", "crowdsec-firewall-bouncer.service"):
                        self.assertIn(f"checked={action}:{unit}", result.stdout)
                self.assertNotIn("hub_update=true", result.stdout)
                self.assertNotIn("restarting_services=true", result.stdout)

    def test_missing_bouncer_state_rechecks_core_before_retrying_console(self):
        start = SOURCE.index('if [ -f "$CROWDSEC_CORE_READY_FILE" ] &&')
        end = SOURCE.index("\nenrollment_status=skipped", start)
        body = SOURCE[start:end].replace(
            "/usr/local/libexec/crowdsec-bouncer-verify >/dev/null 2>&1",
            "bouncer_verify >/dev/null 2>&1",
        )
        code = """
CROWDSEC_CORE_READY_FILE=$1
systemctl() {
  case "$1" in
    is-enabled|is-active)
      [ "$1:$3" != "$FAIL_CHECK" ]
      return $?
      ;;
    *) return 0 ;;
  esac
}
timeout() { return 0; }
bouncer_verify() { return 0; }
wait_for_unit() { return 0; }
wait_for_lapi() { return 0; }
run_optional_crowdsec_command() { return 0; }
run_required_crowdsec_command() { return 0; }
ensure_capi_registration() { return 0; }
ensure_bouncer_api_key() { return 0; }
write_core_ready_marker() { return 0; }
log_line() { printf 'event=%s\\n' "$*"; }
""" + body
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "core-ready"
            marker.write_text("ready\n", encoding="ascii")
            for failure in ("is-enabled:crowdsec-firewall-bouncer.service",
                            "is-active:crowdsec-firewall-bouncer.service"):
                with self.subTest(failure=failure):
                    result = subprocess.run(
                        ["/bin/dash", "-eu", "-c", code, "crowdsec-fixture", str(marker)],
                        env={"PATH": "/usr/bin:/bin", "FAIL_CHECK": failure},
                        text=True, encoding="utf-8", capture_output=True, timeout=5,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("hub_update=true", result.stdout)
                    self.assertIn("core_bootstrap=complete", result.stdout)
                    self.assertNotIn("core_bootstrap=already-verified", result.stdout)

    def test_core_ready_marker_is_atomic_and_private(self):
        code = source_function("write_core_ready_marker") + "\nCROWDSEC_CORE_READY_FILE=$1\nwrite_core_ready_marker\n"
        for label, shell in SHELLS:
            with self.subTest(shell=label), tempfile.TemporaryDirectory() as root:
                marker = Path(root) / "core-ready"
                result = subprocess.run(
                    [*shell, "-eu", "-c", code, "crowdsec-fixture", str(marker)],
                    env={"PATH": "/usr/bin:/bin"}, text=True, encoding="utf-8",
                    capture_output=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(marker.read_text(encoding="ascii"), "ready\n")
                self.assertEqual(os.stat(marker).st_mode & 0o777, 0o600)
                self.assertEqual(list(Path(root).iterdir()), [marker])

    def test_retry_unit_and_cleanup_preserve_core_and_token_contract(self):
        self.assertIn("Environment=CROWDSEC_ENROLL_ATTEMPTS=1", UNIT)
        self.assertIn("RestartSec=1h", UNIT)
        self.assertIn("RestartPreventExitStatus=2", UNIT)
        self.assertNotIn("StartLimitIntervalSec=infinity", UNIT)
        self.assertLess(SOURCE.index("systemctl enable crowdsec.service"),
                        SOURCE.index("write_core_ready_marker || {"))
        self.assertLess(SOURCE.index("write_core_ready_marker || {"),
                        SOURCE.index("enrollment_status=skipped"))
        cleanup = (FORKY / "scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup").read_text(encoding="utf-8")
        self.assertIn('"${crowdsec_state_dir}/core-ready"', cleanup)


if __name__ == "__main__":
    unittest.main()
