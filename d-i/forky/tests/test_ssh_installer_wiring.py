"""Installer SSH wiring, failure propagation and cleanup; no remote connections.

The real bootstrap, fetch, SSH shell helper and DevOps allocator run together
inside a disposable installer chroot. Target Python and mounts are explicit
recording fixtures, not claims of live SSH authentication or kernel mounts.
Existing managed-Git and clone tests exercise the Python/agent/Git components.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

from test_hardware_restore import copy_binary, make_chroot

SEED = Path(__file__).resolve().parents[1]
BOOTSTRAP = SEED / "scripts/common/bootstrap.sh"
SHELLS = ["/bin/dash", "/bin/sh"]

# Deliberately identical to the standalone DevOps imports: no late/core.sh and
# no fixture fetch_hook function to conceal a missing cross-phase dependency.
INITIALIZE = r'''
set -eu
PATH=/bin:/usr/bin:/sbin:/usr/sbin
export PATH
INSTALLER_RUNTIME_DIR=/runtime
INSTALLER_SOURCE_ROOT=/seed
INSTALLER_CMDLINE=
export INSTALLER_RUNTIME_DIR INSTALLER_SOURCE_ROOT INSTALLER_CMDLINE
. /seed/scripts/common/bootstrap.sh
bootstrap_source_common_lib /seed
bootstrap_source_common_support_libs /seed /support target fetch ssh
installer_fatal() { printf 'fatal: %s\n' "$*" >&2; exit 1; }
installer_info() { :; }
installer_warn() { :; }
ACCOUNT_USERNAME=desktop
ACCOUNT_HOME=/home/desktop
[ "${FETCH_OVERRIDE:-}" != missing-helper ] || unset -f fetch_hook_file
case "${FETCH_OVERRIDE:-}" in
  fail) fetch_hook_file() { return 37; } ;;
  empty) fetch_hook_file() { : > "$2"; } ;;
  symlink) fetch_hook_file() { ln -s /git_ed25519 "$2"; } ;;
  directory) fetch_hook_file() { mkdir "$2"; } ;;
esac
mount() {
  printf 'mount %s\n' "$*" >> /mount-calls
  [ "${MOUNT_FAULT:-}" != all ] || return 38
  case "$*" in *'/dev') [ "${MOUNT_FAULT:-}" != dev ] || return 39 ;; esac
  for mounted_path do :; done
  printf 'fixture %s fixture rw 0 0\n' "$mounted_path" >> /proc/mounts
}
umount() {
  printf 'umount %s\n' "$*" >> /mount-calls
  [ "${UMOUNT_FAULT:-}" != yes ] || return 40
  grep -v " $1 " /proc/mounts > /proc/mounts.new || :
  mv /proc/mounts.new /proc/mounts
}
'''

PROBE = r'''#!/bin/sh
# Test interpreter boundary: do not execute the SSH client or contact a server.
set -eu
[ "$HOME:$USER:$LOGNAME:$PATH:$LC_ALL" = '/root:root:root:/usr/sbin:/usr/bin:/sbin:/bin:C.UTF-8' ]
[ -z "${UNTRUSTED_ENV:-}${SSH_AUTH_SOCK:-}${PRESEED_GIT_SSH_PASSPHRASE:-}" ]
[ "$1" = -I ] && [ "$2" = -B ]
shift 2
script=$1 action=$2 account=$3 stage=$4
shift 4
[ "$script" = "$stage/ssh-install.py" ] && [ "$account" = desktop ]
[ -f "$script" ] && [ -s "$stage/clone.conf.tmpl" ] && [ -x "$stage/ssh-install-askpass" ]
[ "$(find -P "$stage" -maxdepth 0 -printf '%U:%m')" = 0:700 ]
for file in ssh-install.py ssh-install-askpass; do
  [ "$(find -P "$stage/$file" -maxdepth 0 -printf '%U:%m')" = 0:700 ]
done
for file in clone.conf.tmpl private public; do
  [ "$(find -P "$stage/$file" -maxdepth 0 -printf '%U:%m')" = 0:600 ]
done
(cd "$stage"; sha256sum -c /expected-assets >/dev/null)
[ "$(cat)" = 'Fixture-Only-Secret!42' ]
printf '%s %s\n' "$action" "$stage" >> /target-calls
case "$action" in
  clone-codex) [ "$#" -eq 1 ]; mkdir "$1" ;;
  seal) [ "$1" = --gpg-fingerprint ] && [ "${#2}" -eq 40 ] ;;
  provision) [ "$#" -eq 0 ] ;;
  *) exit 64 ;;
esac
[ ! -f /child-fail ] || exit 42
if [ -f /child-wait ]; then : > /child-ready; sleep 30; fi
'''


def allocator_source() -> str:
    text = (SEED / "scripts/late/devops/codex-release.sh").read_text()
    start = text.index("devops_install_pinned_codex() (")
    end = text.index("\n)\n\ndevops_install_codex_from_clone()", start) + 3
    return text[start:end]


@unittest.skipUnless(os.geteuid() == 0 and shutil.which("busybox"),
                     "root and installed BusyBox required for disposable installer chroot")
class InstallerSSHBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_tmp = tempfile.TemporaryDirectory(prefix="ssh-installer-base-", dir="/root")
        cls.addClassCleanup(cls.base_tmp.cleanup)
        cls.base = Path(cls.base_tmp.name)
        make_chroot(cls.base)
        copy_binary(cls.base, "/bin/dash")
        for command in ("chroot", "wc", "ls", "id", "cp", "tee", "grep", "sleep", "ln", "sha256sum", "rmdir", "chown", "cut", "uname", "tail", "touch"):
            path = cls.base / "bin" / command
            if not path.exists():
                path.symlink_to("busybox")
        (cls.base / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/sh\n")
        (cls.base / "etc/group").write_text("root:x:0:\n")
        for path in ("root", "proc", "runtime", "seed/scripts/late/ssh"):
            (cls.base / path).mkdir(parents=True, exist_ok=True)
        (cls.base / "proc/mounts").write_text("")
        shutil.copytree(SEED / "scripts/common", cls.base / "seed/scripts/common")
        for path in ("repo.env", "preseed.cfg"):
            shutil.copy2(SEED / path, cls.base / "seed" / path)
        for source in (SEED / "scripts/late/ssh").iterdir():
            if source.is_file():
                shutil.copy2(source, cls.base / "seed/scripts/late/ssh" / source.name)
        (cls.base / "preseed.env").write_text("PRESEED_GIT_SSH_PASSPHRASE='Fixture-Only-Secret!42'\n")
        (cls.base / "preseed.env").chmod(0o600)
        for name, text in (("git_ed25519", "encrypted-key-fixture\n"),
                           ("git_ed25519.pub", "ssh-ed25519 Zml4dHVyZQ== fixture\n")):
            (cls.base / name).write_text(text)
            (cls.base / name).chmod(0o600)
        target = cls.base / "target"
        make_chroot(target)
        copy_binary(target, "/usr/bin/env")
        for name in ("sha256sum", "sleep"):
            (target / "bin" / name).symlink_to("busybox")
        (target / "usr/bin/python3").write_text(PROBE)
        (target / "usr/bin/python3").chmod(0o755)
        (target / "data/codex").mkdir(parents=True)
        (target / "data/codex").chmod(0o3770)
        sums = []
        for name in ("ssh-install.py", "ssh-install-askpass", "clone.conf.tmpl"):
            digest = hashlib.sha256((SEED / "scripts/late/ssh" / name).read_bytes()).hexdigest()
            sums.append(f"{digest}  {name}\n")
        (target / "expected-assets").write_text("".join(sums))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ssh-installer-", dir="/root")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "installer"
        shutil.copytree(self.base, self.root, symlinks=True)
        self.target_name = "/target"

    @property
    def target(self):
        return self.root / self.target_name.lstrip("/")

    def run_shell(self, body: str, *, shell="/bin/sh", env=None, timeout=20):
        environment = {"PATH": "/usr/bin:/bin", **(env or {})}
        return subprocess.run(["/usr/sbin/chroot", str(self.root), shell, "-c", INITIALIZE + body],
                              env=environment, capture_output=True, text=True, timeout=timeout)

    def call(self, action="provision", *, shell="/bin/sh", prefix="", env=None):
        arguments = {"provision": "provision", "seal": "seal --gpg-fingerprint " + "A" * 40,
                     "clone-codex": "clone-codex /data/codex/.home-clone.Fixture123/repository"}
        if action == "clone-codex":
            parent = self.target / "data/codex/.home-clone.Fixture123"
            parent.mkdir(exist_ok=True)
            parent.chmod(0o700)
        return self.run_shell(prefix + f"\nmanaged_git_ssh_target_action {arguments[action]} || exit $?\n",
                              shell=shell, env=env)

    def assert_clean(self, *, mounts=True):
        self.assertEqual(list((self.target / "tmp").glob("git-ssh.*")), [])
        if mounts:
            self.assertEqual((self.root / "proc/mounts").read_text(), "")

    def assert_no_target_execution(self):
        self.assertFalse((self.target / "target-calls").exists())
        self.assertFalse((self.root / "mount-calls").exists())
        self.assert_clean()

    def test_standalone_imports_stage_all_three_actions_under_both_shells(self):
        for shell in SHELLS:
            for action in ("provision", "seal", "clone-codex"):
                with self.subTest(shell=shell, action=action):
                    result = self.call(action, shell=shell, env={"UNTRUSTED_ENV": "must-not-reach-target",
                        "SSH_AUTH_SOCK": "/foreign-agent", "PRESEED_GIT_SSH_PASSPHRASE": "foreign"})
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn("Fixture-Only-Secret", result.stdout + result.stderr)
                    self.assert_clean()
                    if action == "clone-codex":
                        shutil.rmtree(self.target / "data/codex/.home-clone.Fixture123")
        self.assertEqual(len((self.target / "target-calls").read_text().splitlines()), 6)

    def test_fetched_asset_failures_stop_before_mounts_or_target_execution(self):
        for failure in ("fail", "empty", "symlink", "directory", "missing-helper"):
            for shell in SHELLS:
                with self.subTest(failure=failure, shell=shell):
                    result = self.call(shell=shell, env={"FETCH_OVERRIDE": failure})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("SSH", result.stderr)
                    self.assertNotIn("not found", result.stderr)
                    self.assert_no_target_execution()

    def test_each_missing_source_is_rejected_without_cascading(self):
        for name in ("ssh-install.py", "ssh-install-askpass", "clone.conf.tmpl"):
            with self.subTest(asset=name):
                source = self.root / "seed/scripts/late/ssh" / name
                original = source.read_bytes()
                source.unlink()
                shutil.rmtree(self.root / "runtime", ignore_errors=True)
                result = self.call()
                source.write_bytes(original)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                self.assert_no_target_execution()

    def test_private_stage_clears_inherited_setgid_and_parent_is_unchanged(self):
        path = self.target / "tmp"
        path.chmod(0o3777)
        result = self.call(prefix="umask 000\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(path.stat().st_mode & 0o7777, 0o3777)
        self.assert_clean()

    def test_symlinked_tmp_is_rejected_without_touching_its_target(self):
        path = self.target / "tmp"
        path.rmdir()
        (self.root / "foreign").mkdir()
        path.symlink_to("/foreign")
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "mount-calls").exists())
        self.assertEqual(list((self.root / "foreign").iterdir()), [])

    def test_failed_key_copy_cannot_reach_the_target(self):
        result = self.call(prefix=r'''
install() {
  case "$*" in *'/git_ed25519 '*) return 43 ;; esac
  /bin/busybox install "$@"
}
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot stage", result.stderr)
        self.assert_no_target_execution()

    def test_failed_asset_chmod_cannot_reach_the_target(self):
        result = self.call(prefix=r'''
chmod() {
  case "$*" in *'/clone.conf.tmpl') return 44 ;; esac
  /bin/busybox chmod "$@"
}
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot secure private SSH asset", result.stderr)
        self.assert_no_target_execution()

    def test_mount_failure_unwinds_only_owned_mounts_and_stage(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.call(shell=shell, env={"MOUNT_FAULT": "dev"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cannot bind target devices", result.stderr)
                calls = (self.root / "mount-calls").read_text()
                self.assertIn("umount /target/proc", calls)
                self.assertNotIn("umount /target/dev", calls)
                self.assertFalse((self.target / "target-calls").exists())
                self.assert_clean()
                (self.root / "mount-calls").unlink()

    def test_preexisting_mounts_are_preserved(self):
        mounts = "fixture /target/proc proc rw 0 0\nfixture /target/dev devtmpfs rw 0 0\n"
        (self.root / "proc/mounts").write_text(mounts)
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "mount-calls").exists())
        self.assertEqual((self.root / "proc/mounts").read_text(), mounts)
        self.assert_clean(mounts=False)

    def test_cleanup_failure_is_not_reported_as_success(self):
        result = self.call(env={"UMOUNT_FAULT": "yes"})
        self.assertNotEqual(result.returncode, 0)
        self.assert_clean(mounts=False)
        calls = (self.root / "mount-calls").read_text()
        self.assertIn("umount /target/proc", calls)
        self.assertIn("umount /target/dev", calls)

    def test_target_failure_propagates_and_cleans_stage_and_mounts(self):
        (self.target / "child-fail").touch()
        result = self.call()
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        self.assert_clean()

    def test_clone_allocator_uses_its_target_and_never_publishes_on_failure(self):
        self.target_name = "/other-target"
        (self.root / "target").rename(self.target)
        body = r'''
target_root=/other-target
devops_fatal() { installer_fatal "$@"; }
devops_install_codex_from_clone() { [ -d "$target_root$1" ]; touch /published; }
''' + allocator_source() + "\ndevops_install_pinned_codex\n"
        result = self.run_shell(body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "published").exists())
        (self.root / "published").unlink()
        (self.target / "child-fail").touch()
        result = self.run_shell(body)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed to clone codex-home", result.stderr)
        self.assertFalse((self.root / "published").exists())
        self.assertEqual(list((self.target / "data/codex").glob(".home-clone.*")), [])
        self.assert_clean()

    def test_sigterm_cleans_private_stage_and_owned_mounts(self):
        (self.target / "child-wait").touch()
        process = subprocess.Popen(["/usr/sbin/chroot", str(self.root), "/bin/sh", "-c",
            INITIALIZE + "managed_git_ssh_target_action provision || exit $?\n"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            deadline = time.monotonic() + 8
            while not (self.target / "child-ready").exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    self.fail("fixture did not reach the target wait boundary")
                time.sleep(0.02)
            os.killpg(process.pid, signal.SIGTERM)
            out, err = process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            self.assertNotIn("Fixture-Only-Secret", out + err)
            self.assert_clean()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)


class BootstrapFailurePropagationTests(unittest.TestCase):
    def run_case(self, code, shell="/bin/sh"):
        with tempfile.TemporaryDirectory(prefix="bootstrap-failure-") as temp:
            script = f'. {shlex.quote(str(BOOTSTRAP))}\n' + r'''
set -eu
bootstrap_require_seed_base() { printf '%s\n' /seed; }
bootstrap_persist_seed_source() { :; }
bootstrap_ensure_repo_env() { :; }
bootstrap_repo_join_var() { printf 'scripts/common/%s\n' "$2"; }
''' + code
            return subprocess.run([shell, "-c", script], env=dict(os.environ, FIXTURE=temp),
                                  text=True, capture_output=True, timeout=10)

    def test_failed_support_fetch_does_not_source_stale_file_or_continue(self):
        code = r'''
printf 'printf STALE\n' > "$FIXTURE/target-common.sh"
bootstrap_fetch_seed_file() { printf 'FETCH %s\n' "$2"; return 37; }
if bootstrap_source_common_support_libs /seed "$FIXTURE" target fetch ssh; then
  exit 90
else
  status=$?
  [ "$status" -eq 37 ] || exit 91
fi
'''
        for shell in ("/bin/sh", "/bin/dash"):
            result = self.run_case(code, shell)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("STALE", result.stdout)
            self.assertEqual(result.stdout.splitlines(), ["FETCH scripts/common/target.sh"])

    def test_failed_support_source_does_not_continue_to_next_library(self):
        code = r'''
bootstrap_fetch_seed_file() { printf 'FETCH %s\n' "$2"; printf '/bin/sh -c "exit 45"\n' > "$3"; }
bootstrap_source_common_support_libs /seed "$FIXTURE" target fetch ssh || exit $?
printf UNEXPECTED
'''
        result = self.run_case(code)
        self.assertEqual(result.returncode, 45, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["FETCH scripts/common/target.sh"])

    def test_failed_common_fetch_does_not_source_stale_file(self):
        result = self.run_case(r'''
printf 'printf STALE\n' > "$FIXTURE/common.sh"
bootstrap_fetch_seed_file() { return 46; }
if bootstrap_source_common_lib /seed "$FIXTURE/common.sh"; then exit 90; else [ "$?" -eq 46 ]; fi
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("STALE", result.stdout)

    def test_failed_base_resolution_never_fetches(self):
        result = self.run_case(r'''
bootstrap_require_seed_base() { return 47; }
bootstrap_fetch_seed_file() { printf UNEXPECTED; return 0; }
if bootstrap_source_common_support_libs /seed "$FIXTURE" target; then exit 90; else [ "$?" -eq 47 ]; fi
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("UNEXPECTED", result.stdout)

    def test_failed_repository_path_resolution_never_fetches(self):
        for invocation in ('bootstrap_source_common_support_libs /seed "$FIXTURE" target',
                           'bootstrap_source_common_lib /seed "$FIXTURE/common.sh"'):
            with self.subTest(invocation=invocation):
                result = self.run_case(r'''
bootstrap_repo_join_var() { return 49; }
bootstrap_fetch_seed_file() { printf UNEXPECTED; }
''' + f'if {invocation}; then exit 90; else [ "$?" -eq 49 ]; fi\n')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("UNEXPECTED", result.stdout)

    def test_repo_join_does_not_publish_a_suffix_after_base_failure(self):
        script = f'. {shlex.quote(str(BOOTSTRAP))}\n' + r'''
set -eu
bootstrap_repo_dir_value() { return 50; }
if bootstrap_repo_join_var DIR_SCRIPTS_COMMON ssh.sh; then exit 90; else [ "$?" -eq 50 ]; fi
'''
        result = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_shared_fetch_does_not_continue_with_unresolved_seed(self):
        code = f'. {shlex.quote(str(SEED / "scripts/common/fetch.sh"))}\n' + r'''
installer_current_seed_base() { return 48; }
installer_fetch_file() { printf UNEXPECTED; }
if fetch_hook_file scripts/late/ssh/ssh-install.py "$FIXTURE/asset"; then exit 90; else [ "$?" -eq 48 ]; fi
'''
        result = self.run_case(code)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("UNEXPECTED", result.stdout)


class SSHServerArgumentTests(unittest.TestCase):
    def test_server_install_snippet_receives_every_positional_argument(self):
        source = (SEED / "scripts/common/ssh.sh").read_text()
        match = re.search(r'run_in_target "install SSH configuration and keys" /bin/sh -c \'(.*?)\' sh ([^\n]+)',
                          source, re.S)
        self.assertIsNotNone(match)
        script, supplied = match.groups()
        arguments = shlex.split(supplied)
        positions = [int(n) for n in re.findall(r'\$(\d+)', script)]
        self.assertLessEqual(max(positions), len(arguments), "target SSH publisher reads an absent argument")
        # Execute the real argument decoding, stopping before any user mutation.
        prefix = script.split('uid=$(id -u "$account_user")', 1)[0]
        for shell in ("/bin/sh", "/bin/dash"):
            result = subprocess.run([shell, "-c", prefix + '\nprintf "%s\\n" "$stage"', "sh",
                "desktop", "/home/desktop", "/home/desktop/.ssh/authorized_keys", "/tmp/install-ssh.fixture"],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "/tmp/install-ssh.fixture")


if __name__ == "__main__":
    unittest.main()
