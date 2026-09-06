#!/usr/bin/env python3
"""Exercise the core-only Perl supervisor with real Linux child processes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

FORKY = Path(__file__).resolve().parents[1]
os.environ["INSTALLER_SOURCE_LIBRARY"] = str(FORKY / "scripts/common/source.sh")
LIB = FORKY / "hooks/target/usr/local/lib/perl5/site_perl/managed-runtime"
RUNNER = r'''
use Managed::Process qw(capture_command);
use JSON::PP qw(encode_json);
my ($seconds, $limit) = (shift @ARGV, shift @ARGV);
local $/; my $input = <STDIN>;
my $result = capture_command(argv => \@ARGV, timeout => $seconds,
    limit => $limit, input => $input);
print encode_json($result);
'''


class ProcessCaptureTests(unittest.TestCase):
    def command(self, *argv: str, seconds: float = 3, limit: int = 1048576) -> list[str]:
        return ["/usr/bin/perl", "-I", str(LIB), "-e", RUNNER, str(seconds), str(limit), *argv]

    def run_capture(self, *argv: str, input: str = "", seconds: float = 3,
                    limit: int = 1048576) -> subprocess.CompletedProcess[str]:
        return subprocess.run(self.command(*argv, seconds=seconds, limit=limit),
                              input=input, text=True, capture_output=True, timeout=10)

    def test_exit_status_stdout_and_stderr(self) -> None:
        result = self.run_capture("/bin/sh", "-c", "printf hello; printf error >&2; exit 17")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"stdout": "hello", "stderr": "error", "status": 17 << 8, "error": ""})

    def test_simultaneous_large_input_and_output_cannot_deadlock(self) -> None:
        code = "import sys; sys.stdout.write('x'*500000); sys.stdout.flush(); print(len(sys.stdin.read()))"
        result = self.run_capture("/usr/bin/python3", "-c", code, input="y" * 1000000)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], 0)
        self.assertEqual(data["stdout"], "x" * 500000 + "1000000\n")

    def test_output_overflow_cleans_up_instead_of_blocking_in_wait(self) -> None:
        code = "import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); os.write(2,b'x'*20000); time.sleep(30)"
        start = time.monotonic()
        result = self.run_capture("/usr/bin/python3", "-c", code, limit=4096)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds 4096", result.stderr)
        self.assertLess(time.monotonic() - start, 4)

    def test_timeout_covers_term_resistant_child_and_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            pidfile = Path(name) / "pids"
            code = ("import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "child=os.fork(); "
                    f"open({str(pidfile)!r},'a').write(str(os.getpid())+'\\n'); "
                    "time.sleep(30)")
            result = self.run_capture("/usr/bin/python3", "-c", code, seconds=0.3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], 124 << 8)
            for pid in map(int, pidfile.read_text().splitlines()):
                path = Path(f"/proc/{pid}/stat")
                if path.exists():
                    self.assertEqual(path.read_text().split(") ", 1)[1][0], "Z")

    def test_descendant_retaining_pipe_is_bounded_after_parent_exit(self) -> None:
        code = "import os,time; child=os.fork(); os._exit(0) if child else time.sleep(30)"
        result = self.run_capture("/usr/bin/python3", "-c", code, seconds=0.2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["error"], "timeout")

    def test_early_stdin_close_does_not_kill_supervisor_with_sigpipe(self) -> None:
        result = self.run_capture("/bin/true", input="x" * 1000000)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], 0)

    def test_relative_executable_rejected(self) -> None:
        result = self.run_capture("true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absolute executable", result.stderr)

    def test_exec_failure_is_reported(self) -> None:
        result = self.run_capture("/no-such-managed-process-test-command")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], 127 << 8)

    def test_invalid_limits_rejected_before_fork(self) -> None:
        for seconds, limit in [(0, 100), (-1, 100), (1, 0), (1, 16777217)]:
            with self.subTest(seconds=seconds, limit=limit):
                result = self.run_capture("/bin/true", seconds=seconds, limit=limit)
                self.assertNotEqual(result.returncode, 0)

    def test_repeated_term_does_not_interrupt_reaping(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            pidfile = Path(name) / "pid"
            code = ("import os, signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    f"open({str(pidfile)!r},'w').write(str(os.getpid())); time.sleep(30)")
            process = subprocess.Popen(self.command("/usr/bin/python3", "-c", code),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 3
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pidfile.exists())
                process.send_signal(signal.SIGTERM)
                time.sleep(0.05)
                process.send_signal(signal.SIGTERM)
                _out, err = process.communicate(timeout=4)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("interrupted by TERM", err)
                self.assertFalse(Path(f"/proc/{int(pidfile.read_text())}").exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
