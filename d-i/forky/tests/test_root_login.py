"""Root account policy and real isolated debconf integration regressions.

All passwords below are test fixtures, never deployed defaults. Debconf tests
use a temporary database, and the /preseed.env test uses a temporary chroot.
No test modifies the host's account database, /preseed.env, or debconf database.
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

from test_environment import skip_unless_trusted_credential_ancestry

FORKY = Path(__file__).resolve().parents[1]
os.environ["INSTALLER_SOURCE_LIBRARY"] = str(FORKY / "scripts/common/source.sh")
RUNTIME = FORKY / "scripts/runtime/common.sh"
ACCOUNT = FORKY / "scripts/runtime/account.sh"
POLICY = FORKY / "hosts/installer/account.env"
INSTALLER = FORKY / "scripts/common/lib.sh"
SHELLS = [("dash", ["/bin/sh"])]
if shutil.which("bash"):
    SHELLS.append(("bash-posix", [shutil.which("bash"), "--posix"]))
if shutil.which("busybox"):
    SHELLS.append(("busybox-ash", [shutil.which("busybox"), "sh"]))
TEST_ROOT = "Root-Fixture-Only!2026"
TEST_USER = "User-Fixture-Only!2026"


class RootFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="root-login-test-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.envfile = self.path / "preseed.env"
        self.answers = self.path / "account.answers.cfg"
        self.effective = self.path / "account.env"
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
            "HOME": str(self.path),
            "LC_ALL": "C",
            "INSTALLER_CMDLINE": "quiet primary_password=" + TEST_USER,
            "INSTALLER_PRESEED_ENV_FILE": str(self.envfile),
        }
        self.preamble = (
            "set -eu\n"
            f". {shlex.quote(str(RUNTIME))}\n"
            f". {shlex.quote(str(ACCOUNT))}\n"
            f". {shlex.quote(str(POLICY))}\n"
        )

    def seed_env(self, value=TEST_ROOT):
        self.envfile.write_text("PRESEED_ROOT_PASSWORD=" + shlex.quote(value) + "\n")
        self.envfile.chmod(0o600)

    def run_shell(self, script, shell=None, env=None):
        return subprocess.run(
            (shell or SHELLS[0][1]) + ["-c", script],
            env=self.env if env is None else env,
            cwd=self.path, text=True, capture_output=True, timeout=15,
        )

    def render(self, shell=None, prefix="", suffix=""):
        return self.run_shell(
            self.preamble + prefix +
            f"runtime_write_account_answers {shlex.quote(str(self.answers))}\n" + suffix,
            shell,
        )

    def assert_answers(self, password):
        text = self.answers.read_text()
        self.assertIn("d-i passwd/root-login boolean true\n", text)
        self.assertIn("d-i passwd/root-password-crypted password\n", text)
        self.assertIn(f"d-i passwd/root-password password {password}\n", text)
        self.assertIn(f"d-i passwd/root-password-again password {password}\n", text)
        self.assertNotIn("d-i passwd/root-login boolean false\n", text)
        self.assertNotIn("d-i passwd/root-password-crypted password !", text)
        self.assertEqual(stat.S_IMODE(self.answers.stat().st_mode), 0o600)

    def assert_render_fails(self, prefix=""):
        result = self.render(prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.answers.exists())
        self.assertNotIn(TEST_ROOT, result.stdout + result.stderr)
        self.assertNotIn(TEST_USER, result.stdout + result.stderr)
        return result


class RootAccountTests(RootFixture):
    @skip_unless_trusted_credential_ancestry
    def test_cmdline_wins_over_preseed_env_in_all_shells(self):
        self.seed_env("Fallback-Fixture-Only!2026")
        self.env["INSTALLER_CMDLINE"] += " root_password=" + TEST_ROOT
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                result = self.render(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_answers(TEST_ROOT)
                self.assertEqual(result.stdout + result.stderr, "")

    def test_first_duplicate_parameter_wins(self):
        self.seed_env("Fallback-Fixture-Only!2026")
        self.env["INSTALLER_CMDLINE"] += (
            " root_password=" + TEST_ROOT + " root_password=Second-Fixture-Only!2026"
        )
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                result = self.render(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_answers(TEST_ROOT)

    @skip_unless_trusted_credential_ancestry
    def test_absent_parameter_uses_preseed_env_in_all_shells(self):
        self.seed_env()
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                result = self.render(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_answers(TEST_ROOT)

    def test_missing_root_credential_stops_instead_of_disabling_root(self):
        result = self.assert_render_fails()
        self.assertIn("root password is required", result.stderr)

    def test_empty_preseed_env_credential_stops(self):
        self.seed_env("")
        self.assert_render_fails()

    def test_empty_cmdline_parameter_blocks_fallback(self):
        self.seed_env()
        self.env["INSTALLER_CMDLINE"] += " root_password="
        self.assert_render_fails()

    def test_bare_cmdline_parameter_blocks_fallback(self):
        self.seed_env()
        self.env["INSTALLER_CMDLINE"] += " root_password"
        self.assert_render_fails()

    def test_first_empty_parameter_does_not_use_second_value(self):
        self.seed_env()
        self.env["INSTALLER_CMDLINE"] += " root_password= root_password=" + TEST_ROOT
        self.assert_render_fails()

    @skip_unless_trusted_credential_ancestry
    def test_old_root_login_environment_cannot_reinstate_disabled_default(self):
        self.seed_env()
        self.env["ROOT_LOGIN"] = "false"
        self.env["ROOT_PASSWORD_CRYPTED"] = "!"
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_answers(TEST_ROOT)

    @skip_unless_trusted_credential_ancestry
    def test_explicit_disabled_policy_is_rejected(self):
        self.seed_env()
        result = self.assert_render_fails("ROOT_LOGIN=false\n")
        self.assertIn("ROOT_LOGIN must be true", result.stderr)

    def test_legacy_hash_is_not_an_undeclared_third_password_source(self):
        self.env["ROOT_PASSWORD_CRYPTED"] = "$6$test-only$not-a-password-hash"
        self.assert_render_fails()

    def test_inherited_preseed_variable_is_not_a_third_password_source(self):
        self.envfile.write_text("# no root credential in this file\n")
        self.env["PRESEED_ROOT_PASSWORD"] = TEST_ROOT
        self.assert_render_fails()

    def test_symlinked_preseed_env_is_rejected(self):
        real = self.path / "private.env"
        real.write_text("PRESEED_ROOT_PASSWORD=" + shlex.quote(TEST_ROOT) + "\n")
        self.envfile.symlink_to(real)
        self.assert_render_fails()

    @skip_unless_trusted_credential_ancestry
    def test_invalid_root_credential_does_not_leak_in_diagnostic(self):
        self.seed_env(TEST_ROOT + " with whitespace")
        result = self.assert_render_fails()
        self.assertIn("single printable token", result.stderr)

    def test_cmdline_glob_characters_are_literal_not_filesystem_patterns(self):
        (self.path / "root_password=Expanded-Not-The-Password").touch()
        password = "*"
        self.env["INSTALLER_CMDLINE"] += " root_password=" + password
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                result = self.render(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_answers(password)

    def test_root_password_shell_metacharacters_are_not_executed(self):
        password = "$(touch${IFS}SHOULD_NOT_EXIST);x'\"`:$[]?*\\end"
        self.env["INSTALLER_CMDLINE"] += " root_password=" + password
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_answers(password)
        self.assertFalse((self.path / "SHOULD_NOT_EXIST").exists())

    @skip_unless_trusted_credential_ancestry
    def test_exact_key_matching_does_not_accept_a_prefix(self):
        self.seed_env()
        self.env["INSTALLER_CMDLINE"] += " other_root_password=wrong root_password_extra=wrong"
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_answers(TEST_ROOT)

    @skip_unless_trusted_credential_ancestry
    def test_effective_account_environment_does_not_persist_root_secret(self):
        self.seed_env()
        result = self.render(suffix=(
            f"runtime_write_effective_account_env {shlex.quote(str(self.effective))}\n"
        ))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.effective.read_text()
        self.assertIn("ROOT_LOGIN='true'", text)
        self.assertNotIn(TEST_ROOT, text)
        self.assertNotIn("ROOT_PASSWORD", text)
        self.assertEqual(stat.S_IMODE(self.effective.stat().st_mode), 0o600)

    @skip_unless_trusted_credential_ancestry
    def test_repeated_render_is_idempotent(self):
        self.seed_env()
        self.assertEqual(self.render().returncode, 0)
        before = self.answers.read_bytes()
        self.assertEqual(self.render().returncode, 0)
        self.assertEqual(self.answers.read_bytes(), before)

    def test_cmdline_file_runtime_path(self):
        cmdline_file = self.path / "cmdline"
        cmdline_file.write_text(self.env["INSTALLER_CMDLINE"] + " root_password=" + TEST_ROOT)
        self.env["INSTALLER_CMDLINE"] = ""
        self.env["INSTALLER_CMDLINE_FILE"] = str(cmdline_file)
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_answers(TEST_ROOT)

    @skip_unless_trusted_credential_ancestry
    def test_installer_and_runtime_resolvers_agree_and_preserve_caller_state(self):
        self.seed_env()
        cases = [("quiet", TEST_ROOT),
                 ("root_password=first root_password=second", "first"),
                 ("root_password= root_password=second", ""),
                 ("root_password root_password=second", ""),
                 ("root_password=*", "*")]
        (self.path / "root_password=Wrong-Expansion").touch()
        for lib, prefix in ((RUNTIME, "runtime"), (INSTALLER, "installer")):
            for name, shell in SHELLS:
                for cmdline, expected in cases:
                    with self.subTest(lib=prefix, shell=name, cmdline=cmdline):
                        env = {**self.env, "INSTALLER_CMDLINE": cmdline}
                        script = (
                            f"set -eu\n. {shlex.quote(str(lib))}\n"
                            "set +f\nIFS=:; old_ifs=$IFS\n"
                            f"{prefix}_cmdline_value root_password\n"
                            "[ \"$IFS\" = \"$old_ifs\" ]\n"
                            "case $- in *f*) exit 92 ;; esac\n"
                        )
                        result = self.run_shell(script, shell, env)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout, expected + "\n")

    def test_ssh_policy_remains_root_denied(self):
        for relative in (
            "ssh/sshd_config",
        ):
            text = (FORKY / relative).read_text()
            values = re.findall(r"(?mi)^\s*PermitRootLogin\s+(\S+)", text)
            self.assertEqual(values, ["no"], relative)
            self.assertIn("DenyUsers devops", text)

    def test_every_storage_family_uses_shared_account_preseed(self):
        early = (FORKY / "hooks/installer/d-i/early.sh").read_text()
        self.assertIn('runtime_write_account_answers "$RUNTIME_ACCOUNT_FILE"', early)
        self.assertIn('runtime_apply_answers_file "$RUNTIME_ACCOUNT_FILE"', early)
        self.assertIn('scripts/runtime/account.sh', early)
        dispatcher = (FORKY / "scripts/early/dispatch.sh").read_text()
        self.assertIn("family_d_i_early_main", dispatcher)
        self.assertIn("btrfs|vm)", dispatcher)
        self.assertIn("f2fs)", dispatcher)
        for name in ("btrfs", "f2fs"):
            self.assertIn(f"DIR_SCRIPTS_RUNTIME {name}.sh", dispatcher)


@unittest.skipUnless(shutil.which("debconf-set-selections") and
                     shutil.which("debconf-communicate"), "Debian debconf tools required")
class DebconfRootTests(RootFixture):
    def setUp(self):
        super().setUp()
        self.seed_env()
        conf = self.path / "debconf.conf"
        conf.write_text(
            "Config: root_test_config\nTemplates: root_test_templates\n\n"
            "Name: root_test_config\nDriver: File\nMode: 600\n"
            f"Filename: {self.path / 'config.dat'}\n\n"
            "Name: root_test_templates\nDriver: File\nMode: 600\n"
            f"Filename: {self.path / 'templates.dat'}\n"
        )
        self.env.update(DEBCONF_SYSTEMRC=str(conf), DEBIAN_FRONTEND="noninteractive")

    def debconf(self, command):
        result = subprocess.run(
            [shutil.which("debconf-communicate")], input=command + "\n",
            env=self.env, cwd=self.path, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("0"), result.stdout)
        return result.stdout.rstrip("\n")[2:]

    def assert_database(self, password):
        self.assertEqual(self.debconf("GET passwd/root-login"), "true")
        self.assertEqual(self.debconf("GET passwd/root-password-crypted"), "")
        self.assertEqual(self.debconf("GET passwd/root-password"), password)
        self.assertEqual(self.debconf("GET passwd/root-password-again"), password)
        self.assertEqual(self.debconf("FGET passwd/root-password seen"), "true")

    def apply(self, shell=None, mode="runtime_apply_answers_file"):
        return self.render(shell, suffix=(
            f"{mode} {shlex.quote(str(self.answers))}\n"
        ))

    @skip_unless_trusted_credential_ancestry
    def test_real_debconf_receives_unlocked_root_and_exact_password(self):
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                result = self.apply(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_database(TEST_ROOT)

    @skip_unless_trusted_credential_ancestry
    def test_reapply_clears_stale_root_disable_and_locked_hash(self):
        self.assertEqual(self.apply().returncode, 0)
        self.debconf("SET passwd/root-login false")
        self.debconf("SET passwd/root-password-crypted !")
        self.debconf("SET passwd/root-password stale-test-only")
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_database(TEST_ROOT)

    @skip_unless_trusted_credential_ancestry
    def test_protocol_fallback_clears_hash_without_overwriting_password_with_seen(self):
        self.assertEqual(self.apply().returncode, 0)  # Register real templates.
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                self.debconf("SET passwd/root-login false")
                self.debconf("SET passwd/root-password-crypted !")
                result = self.apply(shell, "runtime_seed_answers_file")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_database(TEST_ROOT)
                self.assertEqual(self.debconf("GET passwd/user-fullname"), "Matthew Cramer")

    @skip_unless_trusted_credential_ancestry
    def test_literal_trailing_backslash_password_round_trips_in_all_shells(self):
        password = TEST_ROOT + "\\"
        self.seed_env(password)
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                result = self.apply(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_database(password)

    def test_literal_punctuation_round_trips_through_real_debconf(self):
        password = "test-only-$x!'\"[]*?=one\\two\\\\"
        self.env["INSTALLER_CMDLINE"] += " root_password=" + password
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_database(password)

    def test_set_selections_failure_is_not_reported_as_success(self):
        result = self.render(
            prefix="debconf-set-selections() { return 23; }\n",
            suffix=f"runtime_apply_answers_file {shlex.quote(str(self.answers))}\n",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(TEST_ROOT, result.stderr + result.stdout)

    def test_protocol_errors_are_detected_without_leaking_response_secrets(self):
        for output, status in (("10 " + TEST_ROOT, 0), ("", 0), ("0 ", 42)):
            with self.subTest(status=status, empty=not output):
                result = self.run_shell(
                    self.preamble +
                    "debconf-communicate() { "
                    f"printf '%s\\n' {shlex.quote(output)}; return {status}; }}\n"
                    f"runtime_seed_debconf_value passwd/root-password {shlex.quote(TEST_ROOT)}\n"
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(TEST_ROOT, result.stdout + result.stderr)

    @skip_unless_trusted_credential_ancestry
    def test_seen_false_changes_flag_not_password(self):
        self.assertEqual(self.apply().returncode, 0)
        fragment = self.path / "seen.answers"
        fragment.write_text("d-i passwd/root-password seen false\n")
        result = self.run_shell(
            self.preamble + f"runtime_seed_answers_file {shlex.quote(str(fragment))}\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.debconf("GET passwd/root-password"), TEST_ROOT)
        self.assertEqual(self.debconf("FGET passwd/root-password seen"), "false")


@unittest.skipUnless(os.geteuid() == 0 and shutil.which("chroot") and
                     shutil.which("busybox") and shutil.which("ldd"),
                     "root, chroot, ldd, and busybox required")
class InstallerRootFilesystemTests(RootFixture):
    def test_default_path_is_installer_slash_preseed_env_not_target(self):
        root = self.path / "chroot"
        root.mkdir()
        binary = Path(shutil.which("busybox"))
        destinations = [(binary, Path("bin/busybox"))]
        linked = subprocess.run(["ldd", str(binary)], text=True, capture_output=True, timeout=5)
        for dependency in re.findall(r"(/[^\s()]+)", linked.stdout):
            dep = Path(dependency)
            if dep.is_file():
                destinations.append((dep, Path(dependency.lstrip("/"))))
        for source, relative in destinations:
            dest = root / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
            dest.chmod(0o755)
        for applet in ("sh", "cat", "id", "ls", "chmod", "mktemp", "sed", "rm"):
            (root / "bin" / applet).symlink_to("busybox")
        (root / "tmp").mkdir(mode=0o1777)
        (root / "tmp").chmod(0o1777)
        (root / "proc").mkdir()
        (root / "dev").mkdir()
        # A regular sink suffices for stderr redirection in this isolated fixture.
        (root / "dev/null").touch()
        (root / "target").mkdir()
        (root / "proc/cmdline").write_text("quiet\n")
        (root / "preseed.env").write_text("PRESEED_ROOT_PASSWORD='Installer-Root-Fixture'\n")
        (root / "target/preseed.env").write_text("PRESEED_ROOT_PASSWORD='Wrong-Target-Fixture'\n")
        (root / "preseed.env").chmod(0o600)
        (root / "target/preseed.env").chmod(0o600)
        shutil.copyfile(RUNTIME, root / "runtime-common.sh")
        shutil.copyfile(INSTALLER, root / "installer-common.sh")
        for prefix in ("runtime", "installer"):
            for commandline, expected in (
                ("quiet", "Installer-Root-Fixture"),
                ("quiet root_password=First-Fixture root_password=Second-Fixture", "First-Fixture"),
            ):
                with self.subTest(resolver=prefix, cmdline=commandline):
                    (root / "proc/cmdline").write_text(commandline + "\n")
                    result = subprocess.run(
                        [shutil.which("chroot"), str(root), "/bin/busybox", "sh", "-c",
                         f"set -eu; . /{prefix}-common.sh; {prefix}_cmdline_value root_password"],
                        env={"PATH": "/bin", "LC_ALL": "C"},
                        text=True, capture_output=True, timeout=5,
                    )
                    if result.returncode and "Operation not permitted" in result.stderr:
                        self.skipTest("container does not allow chroot")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected + "\n")


if __name__ == "__main__":
    unittest.main()
