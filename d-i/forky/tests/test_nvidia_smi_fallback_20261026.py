"""Static contract checks for the NVIDIA nvidia-smi clock fallback.

The fixture intentionally does not import the target hardware module, invoke
NVML, execute nvidia-smi, read host devices, or load AppArmor policy.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from pathlib import Path
import unittest


class NvidiaSmiFallbackStaticTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_fallback_uses_fixed_bounded_commands_and_modern_legacy_modes(self):
        source = (self.root / 'hooks/target/usr/local/lib/hardware_tuning/nvidia.py').read_text()
        policy = (self.root / 'hooks/target/etc/apparmor.d/abstractions/hardware-tuning-nvidia').read_text()
        self.assertIn("COMMAND = Path('/usr/bin/nvidia-smi')", source)
        self.assertIn("subprocess.run(", source)
        self.assertIn("timeout=10", source)
        self.assertIn("'--applications-clocks='", source)
        self.assertIn("'--reset-applications-clocks'", source)
        self.assertIn("'--lock-gpu-clocks='", source)
        self.assertIn("'--lock-memory-clocks='", source)
        self.assertIn('except NVMLUnsupported:', source)
        self.assertIn('smi_fallback', source)
        self.assertIn('/usr/bin/nvidia-smi rix,', policy)
        self.assertNotIn('shell=True', source)


if __name__ == '__main__':
    raise SystemExit(unittest.main())
