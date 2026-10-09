#!/usr/bin/env python3
"""Broker policy, diversion and install-graph tests without a running bus."""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_is_file as payload_source_is_file, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

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
    exec(compile(payload_read_bytes(path), str(path), 'exec'), module.__dict__)
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

    def test_fifo_configuration_is_rejected_without_waiting_for_a_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config'
            os.mkfifo(path, 0o600)
            with self.assertRaisesRegex(RuntimeError, 'unsafe root-owned configuration'):
                self.helper.read_owned_file(path)

    def test_final_reload_call_uses_only_the_remaining_budget(self) -> None:
        with mock.patch.object(self.helper.Path, 'is_socket', return_value=True), \
                mock.patch.object(self.helper.Path, 'glob', return_value=[]), \
                mock.patch.object(self.helper.time, 'monotonic', side_effect=[10, 39.5]), \
                mock.patch.object(self.helper, 'command') as command:
            self.helper.reload_active_buses()
        self.assertEqual(command.call_args.kwargs['timeout'], 0.5)

    def test_local_activation_directory_mode_is_normalized_after_private_umask(self) -> None:
        source = payload_read_text(Path(self.helper.__file__))
        self.assertIn('os.fchmod(fd, mode)', source)
        self.assertIn('stat.S_IMODE(os.fstat(fd).st_mode) != mode', source)
        self.assertIn('trusted_directory(LOCAL_SERVICES)', source)

    def test_runtime_maintenance_never_restarts_message_bus(self) -> None:
        source = payload_read_text(Path(self.helper.__file__))
        self.assertIn("'ReloadConfig'", source)
        self.assertNotIn("'restart'", source)
        self.assertNotIn("'try-reload-or-restart'", source)
        hook = payload_read_text(SHARED / 'etc/dpkg/dpkg.cfg.d/90-dbus-broker')
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
            self.assertNotIn('eavesdrop=', payload_read_text(session))
            alias = local / 'org.freedesktop.Notifications.service'
            self.assertFalse(alias.is_symlink())
            self.assertIn('SystemdService=mako.service', alias.read_text(encoding='utf-8'))
            self.assertIn('Exec=/usr/bin/false', alias.read_text(encoding='utf-8'))
            vendor = Path(str(session) + '.distrib')
            vendor.write_text('<busconfig><policy><allow eavesdrop="true"/><allow own="org.example.New"/></policy></busconfig>')
            h.refresh_files()
            self.assertIn('org.example.New', payload_read_text(session))
            before = payload_source_stat(session).st_mtime_ns
            h.refresh_files()
            self.assertEqual(payload_source_stat(session).st_mtime_ns, before)

    def test_notification_activation_cannot_revert_to_a_second_daemon_after_package_refresh(self):
        # Real local publication; vendor ownership/diversion are explicit
        # fixtures so this check needs no privileged dpkg or running user bus.
        h = self.helper
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); vendor = root/'vendor'; local = root/'local'
            vendor.mkdir(); local.mkdir()
            session = vendor/'session.conf'
            session.write_text('<busconfig><policy><allow own="*"/></policy></busconfig>', encoding='utf-8')
            mako = vendor/'mako.service'
            mako.write_text('[D-BUS Service]\nName=org.freedesktop.Notifications\nExec=/usr/bin/mako\n', encoding='utf-8')
            def source(path):
                if path == session: return session
                if path.name == 'fr.emersion.mako.service': return mako
                return None
            with mock.patch.multiple(h, SESSION=session, SERVICES=vendor, LOCAL_SERVICES=local), \
                    mock.patch.object(h, 'diverted_source', side_effect=source), \
                    mock.patch.object(h, 'read_owned_file', side_effect=lambda path: path.read_bytes()), \
                    mock.patch.object(h, 'trusted_directory'):
                h.refresh_files()
                alias = local/'org.freedesktop.Notifications.service'
                initial = alias.read_bytes()
                mako.write_text('[D-BUS Service]\nName=org.freedesktop.Notifications\nExec=/usr/bin/mako --vendor-new-argument\n', encoding='utf-8')
                h.refresh_files()
                self.assertEqual(alias.read_bytes(), initial)
                self.assertIn(b'SystemdService=mako.service', initial)
                self.assertNotIn(b'Exec=/usr/bin/mako', initial)
                self.assertEqual(alias.stat().st_mode & 0o777, 0o644)
            dropin = (SHARED/'etc/systemd/user/mako.service.d/10-labwc-session.conf').read_text(encoding='utf-8')
            self.assertIn('Type=dbus\nBusName=org.freedesktop.Notifications', dropin)
            self.assertIn('ExecStartPre=/usr/bin/sleep 5', dropin)

    @unittest.skipUnless(os.geteuid() == 0, 'checks actual root-owned files in an isolated temporary directory')
    def test_atomic_write_failure_preserves_previous_configuration(self) -> None:
        with tempfile.TemporaryDirectory(prefix='broker-test-') as name:
            path = Path(name) / 'config'
            path.write_bytes(b'previous')
            path.chmod(0o644)
            with mock.patch.object(self.helper.os, 'replace', side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):
                    self.helper.atomic_write(path, b'new')
            self.assertEqual(payload_read_bytes(path), b'previous')
            self.assertEqual([p.name for p in path.parent.iterdir()], ['config'])


class BrokerInstallTests(unittest.TestCase):
    def test_install_parser_handles_sections_continuations_resets_and_duplicates(self) -> None:
        source = payload_read_text(FORKY/'scripts/late/dbus-broker.sh')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Redirect the literal installer target only in this test copy.
            helper = root/'helper.sh'
            helper.write_text(source.replace('/target', str(root)), encoding='utf-8')
            unit = root/'fixture.service'
            unit.write_text('[Unit]\nWantedBy=wrong.target\n[Install]\nWantedBy=old.target\n'
                            'WantedBy=\nWantedBy = first.target \\\n# ignored continuation comment\n'
                            ' second.target first.target\nWantedBy=third.target\n'
                            'Alias=alias.service\n[Service]\nWantedBy=wrong-again.target\n', encoding='utf-8')
            script = '. "$1"; installer_fatal() { printf "%s\\n" "$*" >&2; exit 1; }; target_systemd_install_values /fixture.service WantedBy'
            for shell in (['/bin/sh'], [shutil.which('busybox'), 'sh'] if shutil.which('busybox') else []):
                if not shell:
                    continue
                with self.subTest(shell=shell):
                    result = subprocess.run([*shell, '-eu', '-c', script, 'fixture', str(helper)],
                                            capture_output=True, text=True, encoding='utf-8', timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), ['first.target', 'second.target', 'third.target'])

    def test_republishing_the_same_unit_symlink_preserves_its_inode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)/'alias.service'
            destination.symlink_to('/usr/lib/systemd/system/dbus-broker.service')
            before = destination.lstat().st_ino
            script = '. "$1"; installer_fatal() { exit 1; }; stage_target_atomic_unit_symlink "$2" "$3"'
            result = subprocess.run(['/bin/sh', '-eu', '-c', script, 'fixture',
                                     str(FORKY/'scripts/late/dbus-broker.sh'), os.readlink(destination), str(destination)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.lstat().st_ino, before)

    def test_package_repair_cannot_remove_unrelated_apps(self) -> None:
        source = payload_read_text(FORKY / 'scripts/late/dbus-broker.sh')
        self.assertIn('--no-remove install', source)
        self.assertIn('dpkg --purge dbus dbus-daemon dbus-x11', source)
        self.assertNotIn('-y purge', source)

    def test_helper_hook_and_login_probe_are_staged(self) -> None:
        source = payload_read_text(FORKY / 'scripts/late/dbus-broker.sh')
        for path in ['usr/local/libexec/dbus-broker-maintain', 'usr/local/libexec/dbus-broker-check',
                     'etc/dpkg/dpkg.cfg.d/90-dbus-broker']:
            self.assertIn(path, source)
            self.assertTrue(payload_source_is_file(SHARED / path))
        login = payload_read_text(FORKY / 'hooks/target/usr/local/bin/labwc-session.tmpl')
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
        result = subprocess.run(payload_installed_argv(['/bin/sh']), input=script, text=True, capture_output=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cyclic systemd Also=', result.stderr)


if __name__ == '__main__':
    unittest.main()
