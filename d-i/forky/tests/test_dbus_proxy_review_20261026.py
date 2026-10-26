"""Unexecuted static fixtures for the filtered D-Bus proxy contract.

The repository forbids running these fixtures on the host. They inspect source
text only and never start a bus, proxy, service manager, or desktop session.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import ast
from pathlib import Path
import unittest


class DbusProxyReviewFixtures(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_proxy_starts_with_private_socket_creation_and_validated_policy(self):
        source = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/dbus_proxy.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        self.assertIn('umask=0o077', source)
        self.assertIn('_validated_policy_arguments', source)
        self.assertIn('_validated_dbus_names', source)
        self.assertIn('socket path is accessible by another user', source)
        self.assertTrue(any(isinstance(node, ast.FunctionDef) and node.name == 'start_filtered_dbus_proxy' for node in tree.body))

    def test_unreaped_proxy_socket_is_retained_for_diagnosis(self):
        source = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/dbus_proxy.py').read_text(encoding='utf-8')
        sandbox = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py').read_text(encoding='utf-8')
        self.assertIn('if stopped:', source)
        self.assertIn('if proxy_process is None or proxy_process.poll() is not None:', source)
        self.assertIn('xdg-dbus-proxy cleanup deadline expired', source)
        self.assertIn('cleanup_private_temp_root', sandbox)
        self.assertIn('entry.is_socket()', sandbox)

    def test_session_bus_parser_rejects_duplicate_or_nonlocal_transport_options(self):
        source = (self.root / 'hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/runtime.py').read_text(encoding='utf-8')
        self.assertIn('key in transport_options', source)
        self.assertIn('key not in {"path", "guid"}', source)
        self.assertIn('must reference the current desktop session bus', source)

    def test_broker_refresh_validates_all_aliases_before_publication(self):
        source = (self.root / 'hooks/target/usr/local/libexec/dbus-broker-maintain').read_text(encoding='utf-8')
        self.assertIn('validate_activation_alias', source)
        self.assertIn('planned_aliases', source)
        self.assertIn('All vendor inputs and existing aliases are validated before', source)
        self.assertIn('atomic_write(SESSION, rendered_session)', source)


if __name__ == '__main__':
    raise SystemExit(unittest.main())
