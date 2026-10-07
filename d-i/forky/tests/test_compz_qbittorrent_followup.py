"""Offline checks for the dedicated torrent launcher and display profile wiring."""
from __future__ import annotations

import configparser
import os
from pathlib import Path
import pwd
import runpy
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from payload_fixture import python_library

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / "hooks/target"
QBIT = runpy.run_path(str(TARGET / "usr/local/bin/labwc-qbittorrent"), run_name="test")
LAUNCHERS = runpy.run_path(
    str(TARGET / "usr/local/bin/labwc-sync-application-launchers.tmpl"),
    run_name="test",
)


class TorrentIntegrationTests(unittest.TestCase):
    def test_payload_command_keeps_namespace_isolation_and_drops_all_capabilities(self):
        account = pwd.struct_passwd(('fixture', 'x', os.getuid(), os.getgid(), '', '/home/fixture', '/bin/sh'))
        globals_ = QBIT['build_command'].__globals__
        # Command construction only. Socket availability, optional host binds,
        # and GPU discovery are explicit fixtures; no namespace is created.
        with mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}',
                                         'WAYLAND_DISPLAY': 'wayland-7',
                                         'QT_STYLE_OVERRIDE': 'Adwaita'}, clear=True), \
             mock.patch.dict(globals_, {'require_socket': mock.Mock(),
                                       'optional_ro_bind': mock.Mock(),
                                       'add_gpu_device_binds': mock.Mock()}), \
             mock.patch.object(shutil, 'which', side_effect=lambda name: '/usr/bin/' + name):
            command = QBIT['build_command'](account, Path('/home/fixture/bittorrent'),
                                             Path('/home/fixture/bittorrent/.qbittorrent-profile'), 'launch', [])
        self.assertEqual(command[0], '/usr/bin/bwrap')
        self.assertEqual(command[-1], '/usr/bin/qbittorrent')
        self.assertEqual(command[command.index('--cap-drop') + 1], 'ALL')
        for argument in ('--unshare-all', '--new-session', '--die-with-parent', '--clearenv'):
            self.assertIn(argument, command)
        self.assertNotIn('--cap-add', command)
        self.assertNotIn('--no-sandbox', command)
        index = command.index('QT_QPA_PLATFORM')
        self.assertEqual(command[index - 1:index + 2], ['--setenv', 'QT_QPA_PLATFORM', 'wayland'])
        index = command.index('QT_STYLE_OVERRIDE')
        self.assertEqual(command[index - 1:index + 2], ['--setenv', 'QT_STYLE_OVERRIDE', 'Fusion'])
        self.assertNotIn('Adwaita', command)

    def test_application_modes_keep_the_qbittorrent_style_override_scoped(self):
        with mock.patch.object(sys, 'path', [
                str(python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')), *sys.path]):
            from labwc_managed_app import environment
        with mock.patch.multiple(environment, desktop_activation_environment=lambda: {},
                                 current_user_home=lambda: '/home/fixture',
                                 current_user_name=lambda: 'fixture',
                                 current_user_runtime_dir=lambda: '/run/user/1000',
                                 managed_library_path=lambda name: ''), \
             mock.patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-7',
                                         'QT_STYLE_OVERRIDE': 'Adwaita'}, clear=True):
            for mode in ('launch', 'intel', 'nvidia', 'pure-privacy'):
                with self.subTest(mode=mode):
                    values = environment.build_environment('qbittorrent', mode)
                    self.assertEqual(values['QT_STYLE_OVERRIDE'], 'Fusion')
                    self.assertEqual(values['QT_QPA_PLATFORM'], 'wayland')
            self.assertNotIn('QT_STYLE_OVERRIDE', environment.build_environment('retroarch', 'launch'))

    def test_desktop_entry_uses_the_dedicated_service(self):
        config = next(
            item for item in LAUNCHERS["APP_CONFIG"]
            if item["action_app"] == "qbittorrent"
        )
        self.assertEqual(config["default_mode"], "launch")
        self.assertEqual(LAUNCHERS["managed_default_exec"]("qbittorrent", "%U", "launch"),
                         "/usr/local/bin/labwc-qbittorrent %U")
        self.assertEqual(LAUNCHERS["managed_exec"]("intel", "qbittorrent", "%U"),
                         "/usr/local/bin/labwc-qbittorrent --acceleration=intel %U")

    def test_absent_transient_storage_uses_private_persistent_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            account = pwd.struct_passwd(
                ("user", "x", os.getuid(), os.getgid(), "", str(home), "/bin/sh")
            )
            root = QBIT["select_storage_root"](account, home / "missing" / "bittorrent")
            self.assertEqual(root, home / "bittorrent")
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            paths = QBIT["prepare_storage"](root)
            config = QBIT["write_config"](paths["profile_home"], paths)
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(config)
            self.assertEqual(parser["BitTorrent"][r"Session\Port"], "50309")
            for key in (r"Session\DHTEnabled", r"Session\PeXEnabled",
                        r"Session\LSDEnabled", r"Session\UseRandomPort",
                        r"Session\UseUPnP", r"Session\ValidateHTTPSTrackerCertificate"):
                self.assertEqual(parser["BitTorrent"][key],
                                 "true" if "Validate" in key else "false")
            self.assertEqual(parser["Preferences"][r"WebUI\Enabled"], "false")

    def test_saved_adwaita_style_is_replaced_and_unrelated_preferences_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = QBIT['prepare_storage'](root)
            profile = paths['profile_home']
            config = QBIT['write_config'](profile, paths)
            config.write_text('[Appearance]\nStyle=Adwaita\n[Preferences]\nGeneral\\Locale=sv\n',
                              encoding='utf-8')
            QBIT['write_config'](profile, paths)
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(config, encoding='utf-8')
            self.assertEqual(parser['Appearance']['Style'], 'Fusion')
            self.assertEqual(parser['Preferences'][r'General\Locale'], 'sv')
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_existing_transient_storage_is_preserved_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            account = pwd.struct_passwd(
                ("user", "x", os.getuid(), os.getgid(), "", str(home), "/bin/sh")
            )
            configured = home / "bittorrent-volume"
            configured.mkdir()
            self.assertEqual(QBIT["select_storage_root"](account, configured), configured)
            configured.rmdir()
            configured.symlink_to("/etc")
            self.assertEqual(QBIT["select_storage_root"](account, configured), configured)
            with self.assertRaises(SystemExit):
                QBIT["prepare_storage"](configured)

    def test_firewall_peer_port_has_no_packet_cap(self):
        overlay = (TARGET / "etc/nftables/services/qbittorrent.yml.tmpl").read_text()
        self.assertIn("- tcp", overlay)
        self.assertIn("- udp", overlay)
        self.assertIn("- 50309", overlay)
        self.assertNotIn("rate_limit:", overlay)
        self.assertIn("qbittorrent)", (FORKY / "scripts/late/security.sh").read_text())

    def test_external_fuzzel_geometry_across_profiles(self):
        profiles = sorted((FORKY / "hosts/profiles").glob("*.env"))
        self.assertEqual(len(profiles), 10)
        for path in profiles:
            with self.subTest(profile=path.name):
                assignments = dict(
                    line.split("=", 1) for line in path.read_text().splitlines()
                    if line.startswith("FUZZEL_") and "=" in line
                )
                for mode in ("LAUNCHER", "MENU"):
                    self.assertEqual(assignments[f"FUZZEL_{mode}_EXTERNAL_WIDTH"], '"60"')
                self.assertEqual(assignments["FUZZEL_EXTERNAL_FONT_SIZE"], '"19"')
                self.assertEqual(assignments["FUZZEL_EXTERNAL_LINE_HEIGHT"], '"32"')


if __name__ == "__main__":
    unittest.main()
