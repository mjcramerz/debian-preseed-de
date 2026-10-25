"""Unexecuted native GPU identity and wrong-renderer regression fixtures."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / "tools"))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

from payload_fixture import python_library
TARGET = Path(__file__).resolve().parents[1] / "hooks/target"
sys.path.insert(0, str(python_library(TARGET / "usr/local/lib/python3.14/dist-packages")))
from labwc_managed_app import gpu


class NativeGPUSelection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-gpu-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dev, self.sys, self.proc, self.egl = [self.root / name for name in ("dev", "sys", "proc", "egl")]
        (self.dev / "dri").mkdir(parents=True)
        (self.sys / "class/drm").mkdir(parents=True)
        self.egl.mkdir()
        for filename, vendor in (("10_nvidia.json", "nvidia"), ("50_mesa.json", "mesa")):
            (self.egl / filename).write_text(json.dumps({
                "file_format_version": "1.0.0", "ICD": {"library_path": f"libEGL_{vendor}.so.0"}}))
        self.nodes = {}
        self.original_lstat = Path.lstat
        # Failure fixtures do not contact the system syslog transport.
        failure = mock.patch.object(gpu, "fail", side_effect=lambda message: (_ for _ in ()).throw(SystemExit(message)))
        failure.start()
        self.addCleanup(failure.stop)

    def node(self, name, major, minor):
        path = self.dev / name
        path.write_text("inert device fixture")
        path.chmod(0o666)
        self.nodes[path] = (major, minor)
        return path

    def render(self, minor, pci, vendor, driver):
        node = self.node(f"dri/renderD{minor}", 226, minor)
        device = self.sys / "devices" / pci
        entry = device / "drm" / node.name
        entry.mkdir(parents=True)
        (entry / "dev").write_text(f"226:{minor}\n")
        (device / "vendor").write_text(vendor + "\n")
        driver_path = self.sys / "bus/pci/drivers" / driver
        driver_path.mkdir(parents=True, exist_ok=True)
        (device / "driver").symlink_to(driver_path, target_is_directory=True)
        (entry / "device").symlink_to(device, target_is_directory=True)
        (self.sys / "class/drm" / node.name).symlink_to(entry, target_is_directory=True)
        if driver == "nvidia":
            info = self.proc / "driver/nvidia/gpus" / pci / "information"
            info.parent.mkdir(parents=True)
            info.write_text("Device Minor: 2\n")
            self.node("nvidiactl", 195, 255)
            self.node("nvidia2", 195, 2)
        return node, device

    def metadata(self, path, **kwargs):
        raw = self.original_lstat(path, **kwargs)
        if path not in self.nodes or stat.S_ISLNK(raw.st_mode):
            return raw
        fields = {name: getattr(raw, name) for name in dir(raw) if name.startswith("st_")}
        fields.update(st_mode=stat.S_IFCHR | stat.S_IMODE(raw.st_mode),
                      st_rdev=os.makedev(*self.nodes[path]))
        return types.SimpleNamespace(**fields)

    def select(self, mode):
        with mock.patch.object(Path, "lstat", lambda path, **kw: self.metadata(path, **kw)):
            return gpu.select(mode, dev_root=self.dev, sys_root=self.sys, proc_root=self.proc,
                              egl_root=self.egl, owner=os.getuid())

    def test_reported_mapping_and_reversed_enumeration(self):
        for intel, nvidia in ((128, 129), (131, 128)):
            with self.subTest(intel=intel, nvidia=nvidia):
                # Each mapping uses its own private, bounded fixture tree.
                self.setUp()
                intel_node, _ = self.render(intel, "0000:00:02.0", "0x8086", "i915")
                nvidia_node, _ = self.render(nvidia, "0000:2d:00.0", "0x10de", "nvidia")
                for mode, node, pci in (("intel", intel_node, "0000:00:02.0"),
                                        ("nvidia", nvidia_node, "0000:2d:00.0")):
                    selected = self.select(mode)
                    self.assertEqual((selected.vendor, selected.node, selected.pci), (mode, node, pci))
                    command = []
                    with mock.patch.object(Path, "lstat", lambda path, **kw: self.metadata(path, **kw)):
                        selected.add_binds(command, dev_root=self.dev)
                    self.assertIn("/dev/dri/" + node.name, command)
                    self.assertNotIn("/dev/dri/" + (intel_node if mode == "nvidia" else nvidia_node).name, command)
                    self.assertFalse(any("card0" in arg or "uvm" in arg or "kfd" in arg for arg in command))

    def test_environment_cannot_fall_back_to_other_egl_vendor(self):
        self.render(128, "0000:00:02.0", "0x8086", "i915")
        self.render(129, "0000:2d:00.0", "0x10de", "nvidia")
        environment = {name: "hostile-selection" for name in gpu.SELECTOR_NAMES}
        selected = self.select("nvidia")
        selected.apply_environment(environment)
        self.assertNotIn("DRI_PRIME", environment)
        self.assertNotIn("__EGL_VENDOR_LIBRARY_DIRS", environment)
        self.assertEqual(environment["__EGL_VENDOR_LIBRARY_FILENAMES"], "/usr/share/glvnd/egl_vendor.d/10_nvidia.json")
        self.assertEqual(environment["MOZ_DRM_DEVICE"], str(selected.node))
        self.select("intel").apply_environment(environment)
        self.assertEqual(environment["DRI_PRIME"], "pci-0000_00_02_0")
        self.assertNotIn("__NV_PRIME_RENDER_OFFLOAD", environment)
        self.assertNotIn("GBM_BACKEND", environment)

    def test_missing_ambiguous_driver_mismatch_and_missing_vendor_reject(self):
        node, device = self.render(128, "0000:00:02.0", "0x8086", "i915")
        with self.assertRaises(SystemExit): self.select("nvidia")
        self.render(129, "0000:00:03.0", "0x8086", "xe")
        with self.assertRaises(SystemExit): self.select("intel")
        (device / "vendor").write_text("0x10de\n")
        with self.assertRaises(SystemExit): self.select("nvidia")
        (device / "vendor").write_text("0x8086\n")
        (self.egl / "50_mesa.json").unlink()
        # The other GPU is still ambiguous: do not bypass that gate to guess.
        with self.assertRaises(SystemExit): self.select("launch")

    def test_missing_or_inconsistent_egl_manifest_rejects(self):
        self.render(128, "0000:00:02.0", "0x8086", "i915")
        (self.egl / "50_mesa.json").write_text('{"file_format_version":"1.0.0","ICD":{"library_path":"other.so"}}')
        with self.assertRaises(SystemExit): self.select("intel")
        (self.egl / "50_mesa.json").unlink()
        with self.assertRaises(SystemExit): self.select("intel")

    def test_other_unavailable_adapter_does_not_block_explicit_intel(self):
        node, _ = self.render(128, "0000:00:02.0", "0x8086", "i915")
        _, other = self.render(129, "0000:2d:00.0", "0x10de", "nvidia")
        (other / "driver").unlink()
        self.assertEqual(self.select("intel").node, node)
        with self.assertRaises(SystemExit): self.select("nvidia")

    def test_automatic_nonpci_renderer_retains_software_launch_but_cannot_satisfy_explicit_vendor(self):
        _, device = self.render(128, "0000:00:03.0", "0x1af4", "virtio_gpu")
        self.assertIsNone(self.select("launch"))
        (device / "vendor").unlink()
        self.assertIsNone(self.select("launch"))
        with self.assertRaises(SystemExit): self.select("intel")
        with self.assertRaises(SystemExit): self.select("nvidia")

    def test_replaced_device_rejects_without_publishing_partial_binds(self):
        node, _ = self.render(128, "0000:00:02.0", "0x8086", "i915")
        selected = self.select("intel")
        self.nodes[node] = (226, 129)
        command = ["existing"]
        with mock.patch.object(Path, "lstat", lambda path, **kw: self.metadata(path, **kw)):
            with self.assertRaises(SystemExit): selected.add_binds(command, dev_root=self.dev)
        self.assertEqual(command, ["existing"])

    def test_chromium_exact_node_replaces_conflicts_preserving_operands(self):
        self.render(129, "0000:2d:00.0", "0x10de", "nvidia")
        selected = self.select("nvidia")
        result = selected.chromium_arguments(["browser", "--render-node-override=/dev/dri/renderD128",
                                               "--", "--render-node-override=operand"])
        self.assertEqual(result, ["browser", "--render-node-override=" + str(selected.node),
                                  "--", "--render-node-override=operand"])


if __name__ == "__main__":
    unittest.main()
