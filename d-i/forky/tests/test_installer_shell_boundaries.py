"""Test argument delivery through the real installer/target shell boundary.

run_in_target records arguments or executes against disposable files. A chroot
prevents a quoting regression from executing commands in the host environment.
No EFI variables or block devices are accessed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_hardware_restore import copy_binary, make_chroot

SEED = Path(__file__).resolve().parents[1]
# The project convention closes a multiline -c argument with a single quote
# at the start of a line (optionally indented), followed by whitespace. Both
# portable single-quote escape spellings used by existing scripts are handled.
MULTILINE_COMMAND = re.compile(
    r"(?m)^(?P<header>.*(?: -c| -[A-Za-z]*c) )'\n(?P<body>[\s\S]*?)^[ \t]*'(?=[ \t\r\n\\]|$)"
)
QUOTE_ESCAPES = ("'\\''", "'\"'\"'")


def target_commands():
    for directory in (SEED / "scripts", SEED / "hooks"):
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in (".sh", ".tmpl", ""):
                continue
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            for match in MULTILINE_COMMAND.finditer(text):
                line = text[:match.start("body")].count("\n") + 1
                yield path, line, match.group("header"), match.group("body")


def decoded_body(body: str) -> str:
    for spelling in QUOTE_ESCAPES:
        body = body.replace(spelling, "'")
    return body


class MultilineCommandContracts(unittest.TestCase):
    def test_every_multiline_target_argument_escapes_literal_single_quotes(self):
        commands = list(target_commands())
        self.assertGreaterEqual(len(commands), 100)
        for path, line, _, body in commands:
            with self.subTest(file=str(path.relative_to(SEED)), line=line):
                for spelling in QUOTE_ESCAPES:
                    body = body.replace(spelling, "")
                self.assertNotIn("'", body, "literal quote terminates the enclosing installer argument")


@unittest.skipUnless(os.geteuid() == 0 and shutil.which("busybox") and shutil.which("chroot"),
                     "root, chroot and BusyBox required for installer shell boundaries")
class TargetShellBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="installer-shell-boundary-", dir="/root")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_chroot(self.root)
        copy_binary(self.root, "/bin/dash")
        shutil.copy2(SEED / "scripts/late/grub.sh", self.root / "grub.sh")
        shutil.copy2(SEED / "scripts/desktop/verify.sh.tmpl", self.root / "verify.sh")

    def run_shell(self, shell: str, script: str):
        return subprocess.run(["/usr/sbin/chroot", str(self.root), shell, "-c", script],
                              env={"PATH": "/bin:/usr/bin"}, capture_output=True, timeout=10)

    def test_all_multiline_arguments_survive_both_real_installer_shells(self):
        for path, line, header, body in target_commands():
            for shell in ("/bin/sh", "/bin/dash"):
                with self.subTest(file=str(path.relative_to(SEED)), line=line, shell=shell):
                    result = self.run_shell(shell, "set -eu\nprintf '%s\\000' '\n" + body + "'\n")
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.assertEqual(result.stdout, ("\n" + decoded_body(body)).encode() + b"\0")
                    if "/bin/sh" in header:
                        parsed = subprocess.run(["/usr/sbin/chroot", str(self.root), shell, "-n"],
                                                input=decoded_body(body), capture_output=True,
                                                text=True, timeout=10)
                        self.assertEqual(parsed.returncode, 0, parsed.stderr)
                    elif "/usr/bin/python3" in header:
                        compile(decoded_body(body), f"{path}:{line}", "exec")

    def test_desktop_verifiers_receive_one_script_without_installer_expansion(self):
        cases = (("desktop_verify_staged_files", "verify Labwc desktop staged file metadata", []),
                 ("desktop_verify_greeter_access", "verify Labwc greeter seat and DRM access", ["greeter"]))
        for function, label, expected_tail in cases:
            for shell in ("/bin/sh", "/bin/dash"):
                with self.subTest(function=function, shell=shell):
                    result = self.run_shell(shell, r'''
set -eu
. /verify.sh
run_in_target() { printf '%s\000' "$@"; }
LABWC_GREETER_USER=greeter
''' + function + "\n")
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    args = result.stdout.decode().split("\0")
                    self.assertEqual(args.pop(), "")
                    self.assertEqual(len(args), 5 + len(expected_tail), args)
                    self.assertEqual(args[:3], [label, "/bin/sh", "-c"])
                    self.assertEqual(args[4:], ["sh"] + expected_tail)
                    if function == "desktop_verify_staged_files":
                        self.assertIn("-f='${Status}'", args[3])
                        self.assertIn("fatal 'sleep.target does not require the package lock guard'", args[3])
                    else:
                        self.assertIn("'ConditionUser=!root'", args[3])

    def test_grub_defaults_execute_correctly_in_an_existing_target_file(self):
        for shell in ("/bin/sh", "/bin/dash"):
            with self.subTest(shell=shell):
                target = self.root / "etc/default/grub"
                target.write_text("# preserve administrator setting\nGRUB_CMDLINE_LINUX=\"quiet\"\n"
                                  "GRUB_DEFAULT=0\nGRUB_DEFAULT=1\nGRUB_TIMEOUT=3\n")
                result = self.run_shell(shell, r'''
set -eu
. /grub.sh
run_in_target() { shift; "$@"; }
GRUB_DEFAULT_ENTRY="Debian GNU/Linux>Balanced"
set_target_grub_default_entry
''')
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                lines = target.read_text().splitlines()
                self.assertIn("# preserve administrator setting", lines)
                self.assertIn('GRUB_CMDLINE_LINUX="quiet"', lines)
                self.assertIn('GRUB_DEFAULT="Debian GNU/Linux>Balanced"', lines)
                self.assertIn("GRUB_TIMEOUT=-1", lines)
                self.assertIn("GRUB_TIMEOUT_STYLE=menu", lines)
                self.assertIn("GRUB_RECORDFAIL_TIMEOUT=500", lines)
                self.assertIn("GRUB_DISABLE_RECOVERY=true", lines)
                self.assertIn("GRUB_DISABLE_SUBMENU=y", lines)
                self.assertEqual(sum(line.startswith("GRUB_DEFAULT=") for line in lines), 1)
                self.assertEqual(target.stat().st_mode & 0o7777, 0o644)

    def test_secure_boot_script_and_all_arguments_cross_boundary_unchanged(self):
        for shell in ("/bin/sh", "/bin/dash"):
            with self.subTest(shell=shell):
                result = self.run_shell(shell, r'''
set -eu
. /grub.sh
run_in_target() { printf '%s\000' "$@"; }
DEV_INSTALL_DISK=/dev/nvme0n1
DEV_PART_EFI=/dev/nvme0n1p1
INSTALLER_GRUB_SHIM_EFI_PATH=/EFI/debian/shimx64.efi
repair_target_secure_boot_nvram_entry
''')
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                args = result.stdout.decode().split("\0")
                self.assertEqual(args.pop(), "")
                self.assertEqual(len(args), 8, args)
                self.assertEqual(args[:3], ["ensure firmware boot entry uses shim", "/bin/sh", "-c"])
                self.assertEqual(args[4:], ["sh", "/dev/nvme0n1", "/dev/nvme0n1p1", "/EFI/debian/shimx64.efi"])
                script = args[3]
                parsed = subprocess.run(["/usr/sbin/chroot", str(self.root), shell, "-n"],
                                        input=script, capture_output=True, text=True, timeout=10)
                self.assertEqual(parsed.returncode, 0, parsed.stderr)
                selector = next(line for line in script.splitlines() if line.startswith("part_num="))
                selected = self.run_shell(shell, 'set -eu; efi_part=/dev/nvme0n1p1; '
                                          'lsblk() { printf "\\n1\\n2\\n"; };\n' + selector +
                                          '\n[ "$part_num" = 1 ]')
                self.assertEqual(selected.returncode, 0, selected.stderr.decode())


if __name__ == "__main__":
    unittest.main()
