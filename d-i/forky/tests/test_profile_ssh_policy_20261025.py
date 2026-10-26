"""Unexecuted profile SSH policy fixtures; no target or host management calls."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / "tools"))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

SEED = Path(__file__).resolve().parents[1]


class ProfileSSHPolicyTests(unittest.TestCase):
    def test_client_and_server_prefer_hybrid_kex_and_keep_authentication_policy(self):
        expected = ['mlkem768x25519-sha256', 'sntrup761x25519-sha512',
                    'sntrup761x25519-sha512@openssh.com', 'curve25519-sha256',
                    'curve25519-sha256@libssh.org']
        for name in ('config', 'sshd_config'):
            text = (SEED / 'ssh' / name).read_text()
            algorithms, = re.findall(r'^\s*KexAlgorithms\s+(\S+)$', text, re.M)
            self.assertEqual(algorithms.split(','), expected)
        server = (SEED / 'ssh/sshd_config').read_text()
        self.assertNotRegex(server, r'(?m)^\s*GSSAPIAuthentication\s')
        for line in ('AuthenticationMethods publickey', 'PasswordAuthentication no',
                     'KbdInteractiveAuthentication no', 'PermitRootLogin no',
                     'DisableForwarding yes', 'AllowUsers __INSTALLER_ACCOUNT_USERNAME__'):
            self.assertIn('\n' + line + '\n', server)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="profile-ssh-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "state").mkdir(mode=0o700)
        for source, name in (("scripts/common/modules/profiles.sh", "profiles.sh"),
                             ("scripts/runtime/modules/classes.sh", "classes.sh")):
            shutil.copyfile(SEED / source, self.root / name)

    def shell(self, body, **variables):
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.root / "home"), "LC_ALL": "C",
                       "FIXTURE_ROOT": str(self.root), **variables}
        return subprocess.run(["/bin/sh", "-eu", "-c", body], cwd=self.root,
                              env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=5)

    def policy(self, text):
        (self.root / "profile.env").write_text(text)
        return self.shell('''
. "$FIXTURE_ROOT/profiles.sh"
installer_runtime_state_dir() { printf '%s/state\n' "$FIXTURE_ROOT"; }
installer_profile_env_path() { printf '%s/profile.env\n' "$FIXTURE_ROOT"; }
installer_fetch_seed_path() {
  case "$2" in "$FIXTURE_ROOT/profile.env") ;; *) exit 90 ;; esac
  case "$3" in "$FIXTURE_ROOT"/state/profile-ssh.*) ;; *) exit 91 ;; esac
  cp -- "$2" "$3"
}
installer_fatal() { printf '%s\n' 'fixture policy rejected' >&2; exit 1; }
INSTALLER_HOST_PROFILE_ENV_DIR=override
INSTALLER_HOST_PROFILE_ENV_NAME=fixture
installer_profile_ssh_policy fixture-source
''')

    def test_each_profile_declares_exact_policy_and_unique_requested_range_port(self):
        ports = set()
        profiles = sorted((SEED / "hosts/profiles").glob("*.env"))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            enabled = "false" if "p15s" in path.stem else "true"
            text = path.read_text()
            port, = re.findall(r'^SSH_SERVER_PORT="([0-9]{5})"$', text, re.M)
            self.assertTrue(30000 <= int(port) <= 40000)
            self.assertNotIn(port, ports)
            ports.add(port)
            result = self.policy(text)
            self.assertEqual((result.returncode, result.stdout), (0, enabled + "|" + port + "\n"))
            self.assertEqual(list((self.root / "state").iterdir()), [])

    def test_missing_duplicate_nonliteral_and_out_of_range_policy_rejects(self):
        good = 'SSH_SERVER_ENABLE="true"\nSSH_SERVER_PORT="32006"\n'
        cases = [good.replace('"true"', '"yes"'), good + 'SSH_SERVER_ENABLE="true"\n',
                 good.replace('"32006"', '"29999"'), good.replace('"32006"', '"40001"'),
                 good.replace('SSH_SERVER_PORT="32006"\n', ''),
                 good.replace('"true"', '"$(touch $FIXTURE_ROOT/escaped)"'),
                 good.replace('SSH_SERVER_ENABLE=', 'export SSH_SERVER_ENABLE=')]
        for text in cases:
            with self.subTest(text_length=len(text)):
                self.assertNotEqual(self.policy(text).returncode, 0)
                self.assertFalse((self.root / "escaped").exists())
                self.assertEqual(list((self.root / "state").iterdir()), [])

    def runtime(self, enabled="true", selected="true", port="32006", legacy=""):
        return self.shell('''
. "$FIXTURE_ROOT/classes.sh"
runtime_fatal() { printf '%s\n' 'fixture runtime rejected' >&2; exit 1; }
installer_selected_class_refs() { printf '%s\n' role/desktop; }
installer_selected_class_reference_is_selected() { [ "$FIXTURE_SELECTED" = true ]; }
runtime_cmdline_value() { [ -n "$FIXTURE_LEGACY" ] && printf '%s\n' "$FIXTURE_LEGACY"; }
runtime_apply_ssh_from_classes
printf '%s|%s\n' "$SSH_SERVER_ENABLED" "$SSH_PORT"
''', SSH_SERVER_ENABLE=enabled, SSH_SERVER_PORT=port, FIXTURE_SELECTED=selected, FIXTURE_LEGACY=legacy)

    def test_runtime_profile_is_sufficient_without_ssh_port_boot_argument(self):
        for enabled in ("true", "false"):
            result = self.runtime(enabled=enabled, selected=enabled)
            self.assertEqual((result.returncode, result.stdout), (0, enabled + "|32006\n"))
        self.assertEqual(self.runtime(legacy="32006").returncode, 0)

    def test_runtime_rejects_missing_class_disabled_conflict_and_legacy_port_conflict(self):
        for values in ({"selected": "false"}, {"enabled": "false"}, {"legacy": "22"},
                       {"port": "65536"}, {"port": "32006;false"}, {"enabled": "yes"}):
            result = self.runtime(**values)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
