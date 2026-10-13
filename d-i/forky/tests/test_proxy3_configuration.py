"""Proxy installation and input-boundary regressions; disposable image only."""
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / "tools"))
_isolation_sys.path.insert(0, "/workspace/repository/tools")
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import ast
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / "hooks/target"
MODULE = SEED / "scripts/common/modules/app-veth-identity.sh"
PROFILES = tuple(sorted((SEED / "hosts/profiles").glob("*.env")))
TOKEN = re.compile(r"__INSTALLER_(PROXY3_[A-Z0-9_]+)__")


class ProxyConfigurationTests(unittest.TestCase):
    def test_namespace_reader_accepts_unmapped_root_only_on_an_immutable_mount(self):
        source = (TARGET / "usr/local/libexec/labwc-proxy-session").read_text()
        reader = next(node for node in ast.parse(source).body
                      if isinstance(node, ast.FunctionDef) and node.name == "read_policy")
        namespace = {"os": os, "stat": stat}
        exec(compile(ast.Module(body=[reader], type_ignores=[]), "fixture-policy-reader", "exec"), namespace)
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "policy.conf"
            policy.write_bytes(b"deny *\n")
            metadata = SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=65534, st_nlink=1)
            with patch.object(os, "fstat", return_value=metadata), patch.object(
                    os, "fstatvfs", return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
                self.assertEqual(namespace["read_policy"](str(policy)), b"deny *\n")
            with patch.object(os, "fstat", return_value=metadata), patch.object(
                    os, "fstatvfs", return_value=SimpleNamespace(f_flag=0)):
                with self.assertRaisesRegex(ValueError, "bound read-only"):
                    namespace["read_policy"](str(policy))
            for mode, links in ((stat.S_IFREG | 0o666, 1), (stat.S_IFREG | 0o644, 2)):
                unsafe = SimpleNamespace(st_mode=mode, st_uid=65534, st_nlink=links)
                with patch.object(os, "fstat", return_value=unsafe):
                    with self.assertRaisesRegex(ValueError, "unsafe managed proxy configuration"):
                        namespace["read_policy"](str(policy))
        native = (TARGET / "usr/local/bin/labwc-qbittorrent").read_text()
        self.assertIn("read_managed_config(pathlib.Path(proxy_policy))", native)
        self.assertIn('["--ro-bind", proxy_policy, proxy_policy]', native)

    def test_managed_directory_permissions_do_not_change_vendor_assets(self):
        source = (SEED / "scripts/desktop/components/stage-assets.sh").read_text()
        function = re.search(r"^desktop_normalize_proxy3_directories\(\) \{.*?^\}", source, re.M | re.S)
        self.assertIsNotNone(function)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root / "etc/3proxy"
            vendor.mkdir(parents=True, mode=0o700)
            vendor_file = vendor / "3proxy.cfg"
            vendor_file.write_bytes(b"private vendor configuration\n")
            vendor_file.chmod(0o600)
            managed = root / "etc/labwc/3proxy"
            managed.mkdir(parents=True, mode=0o700)
            managed.parent.chmod(0o700)
            helper = root / "normalize.sh"
            helper.write_text(
                "#!/bin/sh\nset -eu\nfixture_root=$1\n"
                "installer_fatal() { printf '%s\\n' \"$*\" >&2; exit 1; }\n"
                "ensure_target_asset_parent() { mkdir -p -- \"$fixture_root${1%/*}\"; }\n"
                "target_asset_host_path() { printf '%s%s\\n' \"$fixture_root\" \"$1\"; }\n"
                # Ownership is recorded by an explicit fixture implementation;
                # the real ownership command is never reached by this test.
                "chown() { [ \"$1\" = root:root ]; printf '%s\\n' \"$2\" >>\"$fixture_root/owners\"; }\n"
                + function.group() + "\ndesktop_normalize_proxy3_directories\n"
            )
            result = subprocess.run(
                ["/bin/sh", "-eu", str(helper), str(root)],
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": directory},
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "owners").read_text().splitlines(),
                             [str(managed.parent), str(managed)])
            for path in (managed.parent, managed):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(vendor.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(vendor_file.stat().st_mode), 0o600)
            self.assertEqual(vendor_file.read_bytes(), b"private vendor configuration\n")
        staging = (SEED / "scripts/desktop/components/target-assets.sh").read_text()
        self.assertLess(staging.index("desktop_normalize_proxy3_directories"),
                        staging.index("for proxy3_app in"))

    def map(self, profile):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "selected-proxy-values.env"
            # Exercise the production map with only the selected profile fields.
            # Other installer profile assignments do not belong to this fixture.
            source = profile.read_text()
            if profile in PROFILES:
                source = "\n".join(re.findall(r"^PROXY3_[A-Z0-9_]+=.*$", source, re.M)) + "\n"
            fixture.write_text(source)
            return subprocess.run(
                ["/bin/sh", "-eu", "-c", '. "$1"; . "$2"; proxy3_placeholder_map',
                 "proxy-fixture", str(fixture), str(MODULE)],
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": directory}, capture_output=True, text=True, timeout=5)

    def test_each_profile_renders_every_proxy_and_browser_policy_without_tokens(self):
        assets = list((TARGET / "etc/labwc/3proxy").glob("*.tmpl"))
        assets += list((TARGET / "etc").glob("**/policies/managed/3proxy.json.tmpl"))
        assets += [TARGET / "usr/lib/mullvad-browser/distribution/policies.json.tmpl"]
        for profile in PROFILES:
            with self.subTest(profile=profile.name):
                result = self.map(profile)
                self.assertEqual(result.returncode, 0, result.stderr)
                values = dict(line.split("=", 1) for line in result.stdout.splitlines())
                self.assertEqual(len(values), 8)
                for asset in assets:
                    rendered = TOKEN.sub(lambda match: values[match[1]], asset.read_text())
                    self.assertNotIn("__INSTALLER_", rendered)
                    if asset.name.endswith("json.tmpl"):
                        json.loads(rendered)
                    else:
                        self.assertIn(" HTTP_CONNECT\ndeny *\nproxy -4 -a -i127.0.0.1", rendered)
                        self.assertNotRegex(rendered, r"(?m)^(?:daemon|log|socks|admin|users|parent)\b")

    def test_unsafe_port_and_timeout_inputs_fail_before_publication(self):
        values = {
            "PROXY3_PORTS_ALLOW_WEB_BROWSER": ("", "443,80", "443,443", "0", "65536", "443\nallow *", "443;8443"),
            "PROXY3_PORT_LISTEN_QBITTORRENT": ("0", "443", "65536", "3128\nlog /tmp/leak"),
            "PROXY3_MAXCONN_WEB_BROWSER": ("0", "4097", "-1"),
            "PROXY3_TIMEOUTS_WEB_BROWSER": ("1 5", "1 5 30 60 180 1800 15 60 0 5"),
        }
        for name, bad_values in values.items():
            for bad in bad_values:
                with self.subTest(name=name, bad=bad), tempfile.TemporaryDirectory() as directory:
                    # Minimal fixture profile, never an environment override of
                    # a real profile: the profile itself owns production values.
                    profile = Path(directory) / "profile.env"
                    quoted = "'" + bad.replace("'", "'\"'\"'") + "'"
                    profile.write_text(name + "=" + quoted + "\n")
                    result = self.map(profile)
                    if bad == "":
                        # Empty optional values intentionally select defaults.
                        self.assertEqual(result.returncode, 0, result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("fatal: invalid ", result.stderr)

    def test_browser_supervisor_is_shared_without_qbittorrent_profile_state(self):
        source = (TARGET / "usr/local/libexec/labwc-proxy-session").read_text()
        self.assertIn("os.pidfd_open(process.pid)", source)
        self.assertIn("select.select(descriptors, [], [])", source)
        self.assertIn("read_policy(proxy_config)", source)
        staging = (SEED / "scripts/desktop/components/target-assets.sh").read_text()
        self.assertIn("/usr/local/libexec/labwc-proxy-session 0755", staging)
        self.assertIn("proxy3_placeholder_map", staging)
        sandbox = (TARGET / "usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py").read_text()
        self.assertEqual(sandbox.count("argv = proxy_session_argv("), 2)
        self.assertIn("graceful_shutdown=app_name in BROWSER_PROXY_POLICIES", sandbox)
