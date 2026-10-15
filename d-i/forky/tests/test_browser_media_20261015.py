"""Browser media contracts using fixture files and mocked launch operations."""
from __future__ import annotations

# Refuse host execution before fixture discovery, imports or file creation.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock
import sys

from payload_fixture import python_library

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
LIB = python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')
sys.path.insert(0, str(LIB))
from labwc_managed_app import browsers, dbus_proxy, sandbox


class VivaldiMediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='browser-media-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for relative in ('usr', 'opt/vivaldi', 'var/opt/vivaldi'):
            (self.root / relative).mkdir(mode=0o755, parents=True)
        self.launcher = self.root / 'opt/vivaldi/vivaldi'
        self.launcher.write_text('FFMPEG_VERSIONS="8.3-153-S-fixture 8.2-152-Z-fixture"\n')
        self.launcher.chmod(0o755)
        self.media = self.root / 'var/opt/vivaldi'

    def codec(self, version='8.3-153-S-fixture'):
        directory = self.media / ('media-codecs-' + version)
        directory.mkdir(mode=0o755)
        library = directory / 'libffmpeg.so'
        # Synthetic metadata fixture, never loaded or presented as a decoder.
        library.write_bytes(bytes(65536))
        library.chmod(0o644)
        return library

    def test_current_vendor_inventory_selects_only_a_compatible_system_codec(self):
        self.codec('old-unsupported')
        with self.assertRaisesRegex(ValueError, 'no compatible system media codec'):
            browsers.vivaldi_media_directory(root=self.root)
        self.codec('8.2-152-Z-fixture')
        self.assertEqual(browsers.vivaldi_media_directory(root=self.root), str(self.media))

    def test_missing_library_is_actionable(self):
        with self.assertRaisesRegex(ValueError, '/opt/vivaldi/update-ffmpeg --system'):
            browsers.vivaldi_media_directory(root=self.root)

    def test_inventory_is_bounded_and_never_evaluates_shell(self):
        marker = self.root / 'should-not-exist'
        for source in ('FFMPEG_VERSIONS="$(touch ' + str(marker) + ')"\n',
                       'FFMPEG_VERSIONS="one"\nFFMPEG_VERSIONS="two"\n',
                       'FFMPEG_VERSIONS="../escape"\n', 'x' * 131073):
            with self.subTest(source=source[:80]):
                self.launcher.write_text(source)
                with self.assertRaises(ValueError):
                    browsers.vivaldi_media_directory(root=self.root)
                self.assertFalse(marker.exists())

    def test_symlink_library_and_version_directory_are_rejected(self):
        library = self.codec()
        copy = self.root / 'other-library'
        library.rename(copy)
        library.symlink_to(copy)
        with self.assertRaisesRegex(ValueError, 'unsafe Vivaldi media path'):
            browsers.vivaldi_media_directory(root=self.root)
        library.unlink()
        copy.rename(library)
        directory = library.parent
        moved = self.root / 'other-directory'
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe Vivaldi media path'):
            browsers.vivaldi_media_directory(root=self.root)

    def test_writable_wrong_owner_hardlinked_and_truncated_inputs_are_rejected(self):
        library = self.codec()
        for path in (self.media, library.parent, library, self.launcher):
            original = path.stat().st_mode & 0o777
            path.chmod(original | 0o020)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'unsafe Vivaldi'):
                browsers.vivaldi_media_directory(root=self.root)
            path.chmod(original)
        with mock.patch.object(browsers, 'system_owner', return_value=(os.getuid() + 1, os.getgid())):
            with self.assertRaisesRegex(ValueError, 'unsafe Vivaldi'):
                browsers.vivaldi_media_directory(root=self.root)
        link = self.root / 'linked-codec'
        os.link(library, link)
        with self.assertRaisesRegex(ValueError, 'invalid Vivaldi codec library'):
            browsers.vivaldi_media_directory(root=self.root)
        link.unlink()
        library.write_bytes(b'incomplete')
        with self.assertRaisesRegex(ValueError, 'invalid Vivaldi codec library'):
            browsers.vivaldi_media_directory(root=self.root)

    def test_shared_proxy_builder_mounts_verified_codec_read_only(self):
        with mock.patch.object(sandbox, 'vivaldi_media_directory', return_value=str(self.media)), \
                mock.patch.object(sandbox, 'require_root_owned_regular_file', side_effect=lambda label, path, **kw: path), \
                mock.patch.object(sandbox, 'require_root_owned_executable', side_effect=lambda label, path: path):
            for online in (False, True):
                command = []
                argv = sandbox.proxy_session_argv(command, ['/usr/bin/vivaldi-stable'], 'vivaldi', online=online)
                triplets = [command[i:i+3] for i in range(len(command)-2)]
                self.assertIn(['--ro-bind', str(self.media), str(self.media)], triplets)
                self.assertNotIn(['--bind', str(self.media), str(self.media)], triplets)
                self.assertEqual(argv[-1], '/usr/bin/vivaldi-stable')


class BrowserGraphicsAndTorTests(unittest.TestCase):
    def test_vivaldi_uses_early_native_gpu_sandbox_and_one_opengl_backend(self):
        for mode in ('launch', 'intel', 'nvidia'):
            argv = browsers.browser_args('vivaldi', mode)
            self.assertIn('--gpu-sandbox-start-early', argv)
            self.assertEqual(argv.count('--use-webgpu-adapter=opengles'), 1)
            self.assertIn('--use-gl=angle', argv)
            self.assertIn('--use-angle=gl', argv)
            self.assertNotIn('--ignore-gpu-blocklist', argv)
            self.assertFalse(any('disable-gpu-sandbox' in arg for arg in argv))
            self.assertFalse(any('enable-angle-features' in arg for arg in argv))

    def test_accelerated_browser_modes_use_current_decoder_feature_names(self):
        for browser in ('chromium', 'microsoft-edge', 'vivaldi'):
            for mode in ('intel', 'nvidia'):
                argv = browsers.browser_args(browser, mode)
                enabled = next(arg for arg in argv if arg.startswith('--enable-features=')).split('=', 1)[1].split(',')
                self.assertIn('AcceleratedVideoDecoder', enabled)
                self.assertIn('AcceleratedVideoDecodeLinuxGL', enabled)
                self.assertNotIn('VaapiVideoDecoder', enabled)
                self.assertNotIn('VaapiVideoEncoder', enabled)
                self.assertEqual(argv.count('--use-webgpu-adapter=opengles'), 1)

    def test_upower_proxy_allows_only_service_discovery_properties_and_enumeration(self):
        policy = dbus_proxy.READ_ONLY_UPOWER_POLICY
        self.assertIn('--see=org.freedesktop.UPower', policy)
        self.assertFalse(any(arg.startswith('--talk=') for arg in policy))
        calls = [arg for arg in policy if arg.startswith('--call=')]
        allowed = {'org.freedesktop.UPower.EnumerateDevices', 'org.freedesktop.UPower.GetDisplayDevice',
                   'org.freedesktop.DBus.Properties.Get', 'org.freedesktop.DBus.Properties.GetAll'}
        for call in calls:
            destination, method = call.removeprefix('--call=').split('=', 1)
            self.assertEqual(destination, 'org.freedesktop.UPower')
            self.assertIn(method.split('@', 1)[0], allowed)
        # xdg-dbus-proxy recognizes a subtree only with the /* suffix. A
        # shell-style /UPower* matches no valid D-Bus object path.
        changes = [arg for arg in policy if '.PropertiesChanged@' in arg]
        self.assertEqual(changes, [
            '--broadcast=org.freedesktop.UPower='
            'org.freedesktop.DBus.Properties.PropertiesChanged@/org/freedesktop/UPower/*',
        ])
        for argument in policy:
            if '@' not in argument:
                continue
            path = argument.split('@', 1)[1]
            self.assertTrue(path == '/org/freedesktop/UPower' or path.startswith('/org/freedesktop/UPower/'))
            self.assertNotIn('*', path.removesuffix('/*'))

    def test_both_stacked_tor_profiles_receive_exact_pulse_directory_permissions(self):
        abstraction = (TARGET / 'etc/apparmor.d/abstractions/tor-browser-runtime').read_text()
        policy = (TARGET / 'etc/apparmor.d/desktop-wrappers.tmpl').read_text()
        self.assertIn('owner /run/user/[0-9]*/pulse/ rw,', abstraction)
        self.assertNotIn('owner /run/user/[0-9]*/pulse/** rw', abstraction)
        self.assertIn('#include <abstractions/dbus-strict>', abstraction)
        self.assertIn('member=NameOwnerChanged peer=(name=org.freedesktop.DBus),', abstraction)
        tor = policy.split('profile tor-bwrap ', 1)[1].split('include if exists <local/usr.local.bin.labwc-app>', 1)[0]
        self.assertEqual(tor.count('#include <abstractions/tor-browser-runtime>'), 2)
        self.assertIn('deny network inet,', tor)
        self.assertIn('deny network inet6,', tor)


if __name__ == '__main__':
    unittest.main()
