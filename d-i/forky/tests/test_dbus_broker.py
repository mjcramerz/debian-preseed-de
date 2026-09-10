#!/usr/bin/env python3
"""Broker policy, diversion and install-graph tests without a running bus."""
from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

FORKY = Path(__file__).resolve().parents[1]
os.environ["INSTALLER_SOURCE_LIBRARY"] = str(FORKY / "scripts/common/source.sh")
SHARED = FORKY / 'hooks/target'


def load_helper() -> types.ModuleType:
    path = SHARED / 'usr/local/libexec/dbus-broker-maintain'
    module = types.ModuleType('tested_broker_maintenance')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class BrokerPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = load_helper()

    def test_multiline_eavesdrop_rules_become_explicit_receive_types(self) -> None:
        source = b'''<busconfig><type>session</type><policy context="default">
          <allow send_destination="*"/><allow own="*"/>
          <allow\n eavesdrop = 'true' />
          </policy></busconfig>'''
        output = self.helper.broker_session_config(source)
        root = ET.fromstring(output)
        rules = root.find('policy').findall('allow')
        self.assertEqual([r.attrib for r in rules[:2]], [{'send_destination': '*'}, {'own': '*'}])
        self.assertEqual({r.attrib['receive_type'] for r in rules[2:]},
                         {'method_call', 'method_return', 'error', 'signal'})
        self.assertNotIn(b'eavesdrop=', output)

    def test_non_eavesdrop_attributes_preserved(self) -> None:
        source = b'<busconfig><policy context="default"><allow eavesdrop="false" receive_sender="org.example.Test"/></policy></busconfig>'
        root = ET.fromstring(self.helper.broker_session_config(source))
        self.assertEqual(root.find('policy/allow').attrib, {'receive_sender': 'org.example.Test'})

    def test_unknown_deny_semantics_fail_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            self.helper.broker_session_config(b'<busconfig><policy><deny eavesdrop="true"/></policy></busconfig>')

    def test_attribute_free_policy_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            self.helper.broker_session_config(b'<busconfig><policy><allow/></policy></busconfig>')

    def test_entity_declaration_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            self.helper.broker_session_config(b'<!DOCTYPE busconfig [<!ENTITY x "y">]><busconfig/>')

    def test_wrong_root_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            self.helper.broker_session_config(b'<invalid/>')

    def test_duplicate_activation_names_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            self.helper.service_name(b'[D-BUS Service]\nName=org.example.One\nName=org.example.Two\n')

    def test_activation_name_comes_from_correct_section(self) -> None:
        data = b'[Other]\nName=incorrect\n[D-BUS Service]\nName=org.example.Correct\n'
        self.assertEqual(self.helper.service_name(data), 'org.example.Correct')

    def test_foreign_diversion_rejected(self) -> None:
        with mock.patch.object(self.helper, 'command', side_effect=['other-package', '/some/other/path']):
            with self.assertRaisesRegex(RuntimeError, 'foreign diversion'):
                self.helper.diverted_source(Path('/usr/share/dbus-1/session.conf'))

    def test_local_activation_directory_mode_is_normalized_after_private_umask(self) -> None:
        source = Path(self.helper.__file__).read_text()
        self.assertIn('os.fchmod(fd, mode)', source)
        self.assertIn('stat.S_IMODE(os.fstat(fd).st_mode) != mode', source)
        self.assertIn('trusted_directory(LOCAL_SERVICES)', source)

    def test_runtime_maintenance_never_restarts_message_bus(self) -> None:
        source = Path(self.helper.__file__).read_text()
        self.assertIn("'ReloadConfig'", source)
        self.assertNotIn("'restart'", source)
        self.assertNotIn("'try-reload-or-restart'", source)
        hook = (SHARED / 'etc/dpkg/dpkg.cfg.d/90-managed-dbus-broker').read_text()
        self.assertIn('post-invoke=/usr/local/libexec/dbus-broker-maintain --refresh', hook)

    @unittest.skipUnless(os.geteuid() == 0, 'checks actual root-owned files in an isolated temporary directory')
    def test_vendor_update_regenerates_config_and_preserves_live_alias(self) -> None:
        h = self.helper
        with tempfile.TemporaryDirectory(prefix='broker-test-') as name, ExitStack() as stack:
            base = Path(name)
            session = base / 'session.conf'
            session.write_text('<busconfig><policy><allow eavesdrop="true"/></policy></busconfig>')
            session.chmod(0o644)
            services = base / 'services'
            services.mkdir()
            local = base / 'local'
            original = services / 'fr.emersion.mako.service'
            original.write_text('[D-BUS Service]\nName=org.freedesktop.Notifications\nExec=/usr/bin/mako\n')
            original.chmod(0o644)
            registry: dict[str, str] = {}

            def dpkg(argv: list[str], timeout: int = 30) -> str:
                path = argv[-1]
                if '--listpackage' in argv:
                    return 'LOCAL' if path in registry else ''
                if '--truename' in argv:
                    return registry.get(path, path)
                if '--add' in argv:
                    destination = argv[argv.index('--divert') + 1]
                    shutil.move(path, destination)
                    registry[path] = destination
                    return ''
                raise AssertionError(argv)

            stack.enter_context(mock.patch.multiple(h, SESSION=session, SERVICES=services, LOCAL_SERVICES=local))
            stack.enter_context(mock.patch.object(h, 'command', side_effect=dpkg))
            h.refresh_files()
            self.assertNotIn('eavesdrop=', session.read_text())
            alias = local / 'org.freedesktop.Notifications.service'
            self.assertEqual(alias.resolve(), Path(str(original) + '.distrib'))
            vendor = Path(str(session) + '.distrib')
            vendor.write_text('<busconfig><policy><allow eavesdrop="true"/><allow own="org.example.New"/></policy></busconfig>')
            h.refresh_files()
            self.assertIn('org.example.New', session.read_text())
            before = session.stat().st_mtime_ns
            h.refresh_files()
            self.assertEqual(session.stat().st_mtime_ns, before)

    @unittest.skipUnless(os.geteuid() == 0, 'checks actual root-owned files in an isolated temporary directory')
    def test_atomic_write_failure_preserves_previous_configuration(self) -> None:
        with tempfile.TemporaryDirectory(prefix='broker-test-') as name:
            path = Path(name) / 'config'
            path.write_bytes(b'previous')
            path.chmod(0o644)
            with mock.patch.object(self.helper.os, 'replace', side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):
                    self.helper.atomic_write(path, b'new')
            self.assertEqual(path.read_bytes(), b'previous')
            self.assertEqual([p.name for p in path.parent.iterdir()], ['config'])


class BrokerInstallTests(unittest.TestCase):
    def test_package_repair_cannot_remove_unrelated_apps(self) -> None:
        source = (FORKY / 'scripts/late/dbus-broker.sh').read_text()
        self.assertIn('--no-remove install', source)
        self.assertIn('dpkg --purge dbus dbus-daemon dbus-x11', source)
        self.assertNotIn('-y purge', source)

    def test_helper_hook_and_login_probe_are_staged(self) -> None:
        source = (FORKY / 'scripts/late/dbus-broker.sh').read_text()
        for path in ['usr/local/libexec/dbus-broker-maintain', 'usr/local/libexec/dbus-broker-check',
                     'etc/dpkg/dpkg.cfg.d/90-managed-dbus-broker']:
            self.assertIn(path, source)
            self.assertTrue((SHARED / path).is_file())
        login = (FORKY / 'hooks/target/usr/local/bin/labwc-session.tmpl').read_text()
        self.assertIn('/usr/local/libexec/dbus-broker-check --user', login)

    def test_cyclic_also_units_fail_with_diagnostic(self) -> None:
        path = FORKY / 'scripts/late/dbus-broker.sh'
        script = f'''
set -eu
. '{path}'
installer_fatal() {{ printf '%s\\n' "$*" >&2; exit 1; }}
target_systemd_unit_path() {{ printf '/usr/lib/systemd/system/%s\\n' "$1"; }}
target_systemd_scope_base_dir() {{ printf '%s\\n' /etc/systemd/system; }}
target_systemd_install_values() {{
  [ "$2" = Also ] || return 0
  case "$1" in */one.service) printf '%s\\n' two.service ;; *) printf '%s\\n' one.service ;; esac
}}
stage_target_systemd_unit_enabled one.service system
'''
        result = subprocess.run(['/bin/sh'], input=script, text=True, capture_output=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cyclic systemd Also=', result.stderr)


if __name__ == '__main__':
    unittest.main()
