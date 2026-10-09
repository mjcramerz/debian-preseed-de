"""Installed entrypoint bytecode policy, including real kernel shebang execution."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

SEED = Path(__file__).resolve().parents[1]
ROOTS = (SEED / "hooks/target", SEED / "scripts/firstboot")


class InstalledBytecodeTests(unittest.TestCase):
    def test_explicit_interpreters_disable_bytecode_when_the_shebang_is_bypassed(self):
        pattern = re.compile(r'(?:^|[\s=])/usr/bin/python3((?:\s+-[A-Za-z]+)*)\s+/(?:usr/local|var/lib/firstboot|data)/', re.M)
        variants = set()
        for root in ROOTS:
            for path in root.rglob('*'):
                if not path.is_file():
                    continue
                for match in pattern.finditer(path.read_bytes().decode('utf-8', errors='replace')):
                    flags = tuple(match[1].split())
                    with self.subTest(path=path, flags=flags):
                        self.assertTrue(any(flag.startswith('-') and 'B' in flag for flag in flags))
                    variants.add(flags)
        self.assertTrue(variants)
        for flags in sorted(variants):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory(prefix='bytecode-interpreter-') as directory:
                root = Path(directory)
                (root / 'cache_probe.py').write_text('VALUE = 42\n', encoding='ascii')
                script = root / 'entrypoint'
                # A flag-free shebang demonstrates that direct interpreter
                # options enforce this contract independently of the header.
                script.write_text('#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\n'
                                  'sys.path.insert(0, str(Path(__file__).parent))\n'
                                  'import cache_probe\nassert cache_probe.VALUE == 42\n'
                                  'assert sys.dont_write_bytecode\n', encoding='ascii')
                result = subprocess.run(['/usr/bin/python3', *flags, str(script)],
                    env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'PYTHONDONTWRITEBYTECODE': '0'},
                    capture_output=True, text=True, encoding='utf-8', timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((root / '__pycache__').exists())

    def test_every_installed_python_shebang_disables_bytecode(self):
        variants = set()
        for root in ROOTS:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                first = path.read_bytes().split(b"\n", 1)[0].decode("utf-8", errors="replace")
                if first.startswith("#!") and "python3" in first:
                    with self.subTest(path=path):
                        flags = first.split("python3", 1)[1].strip().split()
                        self.assertTrue(any(flag.startswith("-") and "B" in flag for flag in flags), first)
                    variants.add(first)
        self.assertTrue(variants)
        for shebang in sorted(variants):
            with self.subTest(shebang=shebang), tempfile.TemporaryDirectory(prefix="bytecode-shebang-") as directory:
                root = Path(directory)
                (root / "cache_probe.py").write_text("VALUE = 42\n", encoding="ascii")
                script = root / "entrypoint"
                script.write_text(shebang + "\nimport sys\nfrom pathlib import Path\n"
                                  "sys.path.insert(0, str(Path(__file__).parent))\n"
                                  "import cache_probe\nassert cache_probe.VALUE == 42\n"
                                  "assert sys.dont_write_bytecode\n", encoding="ascii")
                script.chmod(0o700)
                result = subprocess.run([str(script)], env={"PATH": "/usr/bin:/bin", "LC_ALL": "C",
                    "PYTHONDONTWRITEBYTECODE": "0"}, capture_output=True, text=True, encoding="utf-8", timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse((root / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
